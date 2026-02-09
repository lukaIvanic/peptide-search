from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


# Chat Completions API (for text-only)
CHAT_COMPLETIONS_ENDPOINT = "https://api.openai.com/v1/chat/completions"

# Responses API (for file URLs - newer models like gpt-4o, gpt-5, etc.)
RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"

# Files API (for uploading files)
FILES_ENDPOINT = "https://api.openai.com/v1/files"

OPENAI_TIMEOUTS = {
    "chat": 600,
    "responses_url": 1200,
    "responses_file": 1200,
    "upload": 600,
    "delete": 60,
}


class OpenAIProvider:
    """OpenAI provider that can process PDFs directly via URL using the Responses API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._model = model or settings.OPENAI_MODEL

    def name(self) -> str:
        return "openai"

    def supports_pdf_url(self) -> bool:
        """OpenAI models support PDF URLs directly via the Responses API."""
        return True

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> str:
        """Standard text-only generation using Chat Completions API."""
        return await self._call_chat_completions(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def generate_json_with_pdf_url(
        self,
        system_prompt: str,
        user_prompt: str,
        pdf_url: str,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> str:
        """
        Generate JSON by sending a PDF URL directly to OpenAI using the Responses API.
        This is the correct way to pass file URLs to newer models.
        """
        return await self._call_responses_api(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            pdf_url=pdf_url,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def generate_json_with_pdf_file(
        self,
        system_prompt: str,
        user_prompt: str,
        file_content: bytes,
        filename: str,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> str:
        """
        Generate JSON by uploading a PDF file to OpenAI and processing it.
        Uploads the file first, then uses the file_id in the Responses API.
        """
        # Upload the file to OpenAI
        file_id = await self._upload_file(file_content, filename)
        try:
            return await self._call_responses_api_with_file_id(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                file_id=file_id,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        finally:
            # Clean up: delete the file after processing
            await self._delete_file(file_id)

    async def _upload_file(self, file_content: bytes, filename: str) -> str:
        """Upload a file to OpenAI Files API and return the file ID."""
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }

        # Use multipart/form-data for file upload
        files = {
            "file": (filename, file_content, "application/pdf"),
            "purpose": (None, "user_data"),
        }

        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUTS["upload"]) as client:
            logger.info(f"Uploading file to OpenAI: {filename}")
            resp = await client.post(FILES_ENDPOINT, headers=headers, files=files)
            if resp.status_code != 200:
                error_text = resp.text
                raise RuntimeError(f"OpenAI file upload error ({resp.status_code}): {error_text}")
            data = resp.json()

        file_id = data.get("id")
        if not file_id:
            raise RuntimeError(f"No file ID returned from OpenAI: {data}")
        
        logger.info(f"File uploaded successfully: {file_id}")
        return file_id

    async def _delete_file(self, file_id: str) -> None:
        """Delete a file from OpenAI."""
        if not self._api_key:
            return

        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }

        try:
            async with httpx.AsyncClient(timeout=OPENAI_TIMEOUTS["delete"]) as client:
                await client.delete(f"{FILES_ENDPOINT}/{file_id}", headers=headers)
                logger.info(f"File deleted: {file_id}")
        except Exception as e:
            logger.warning(f"Failed to delete file {file_id}: {e}")

    async def _call_responses_api_with_file_id(
        self,
        system_prompt: str,
        user_prompt: str,
        file_id: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Call the OpenAI Responses API with a file ID."""
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        # Build input array with system instructions and user content
        input_content: List[Dict[str, Any]] = [
            {
                "role": "developer",
                "content": [
                    {"type": "input_text", "text": system_prompt},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt},
                    {"type": "input_file", "file_id": file_id},
                ],
            },
        ]

        # Some models don't support temperature
        models_without_temperature = ("o1", "o3", "gpt-5")
        supports_temperature = not any(self._model.startswith(prefix) for prefix in models_without_temperature)

        payload: Dict[str, Any] = {
            "model": self._model,
            "input": input_content,
            "text": {
                "format": {
                    "type": "json_object",
                },
            },
        }

        if supports_temperature:
            payload["temperature"] = temperature

        if max_tokens:
            payload["max_output_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUTS["responses_file"]) as client:
            logger.info(f"Calling OpenAI Responses API with file_id: {file_id}")
            resp = await client.post(RESPONSES_ENDPOINT, headers=headers, json=payload)
            if resp.status_code != 200:
                error_text = resp.text
                raise RuntimeError(f"OpenAI API error ({resp.status_code}): {error_text}")
            data = resp.json()

        # Same response parsing as _call_responses_api
        logger.info(f"OpenAI response keys: {list(data.keys())}")
        
        if data.get("error"):
            raise RuntimeError(f"OpenAI returned error: {data['error']}")
        
        status = data.get("status")
        if status and status != "completed":
            error_msg = f"OpenAI response status: {status}"
            if data.get("incomplete_details"):
                error_msg += f" - {data['incomplete_details']}"
            raise RuntimeError(error_msg)

        output_text = data.get("output_text", "")
        
        if not output_text:
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            output_text = content.get("text", "")
                            break
                        elif content.get("type") == "text":
                            output_text = content.get("text", "")
                            break

        if not output_text:
            logger.error(f"No output_text found in response: {json.dumps(data, indent=2)[:2000]}")
            raise RuntimeError(
                f"OpenAI returned empty response. Status: {data.get('status', 'unknown')}. "
                f"This may happen if the PDF couldn't be processed or the model refused. "
                f"Response keys: {list(data.keys())}"
            )

        text = self._clean_json_response(output_text)
        
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from OpenAI: {text[:500]}")
            raise RuntimeError(f"OpenAI returned invalid JSON: {e}. Response preview: {text[:200]}")
        
        return text

    async def _call_responses_api(
        self,
        system_prompt: str,
        user_prompt: str,
        pdf_url: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Call the OpenAI Responses API with a file URL."""
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        # Build input array with system instructions and user content
        input_content: List[Dict[str, Any]] = [
            {
                "role": "developer",
                "content": [
                    {"type": "input_text", "text": system_prompt},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt},
                    {"type": "input_file", "file_url": pdf_url},
                ],
            },
        ]

        # Some models don't support temperature
        models_without_temperature = ("o1", "o3", "gpt-5")
        supports_temperature = not any(self._model.startswith(prefix) for prefix in models_without_temperature)

        payload: Dict[str, Any] = {
            "model": self._model,
            "input": input_content,
            "text": {
                "format": {
                    "type": "json_object",
                },
            },
        }

        if supports_temperature:
            payload["temperature"] = temperature

        if max_tokens:
            payload["max_output_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUTS["responses_url"]) as client:
            logger.info(f"Calling OpenAI Responses API with PDF: {pdf_url}")
            resp = await client.post(RESPONSES_ENDPOINT, headers=headers, json=payload)
            if resp.status_code != 200:
                error_text = resp.text
                raise RuntimeError(f"OpenAI API error ({resp.status_code}): {error_text}")
            data = resp.json()

        # Log the response structure for debugging
        logger.info(f"OpenAI response keys: {list(data.keys())}")
        
        # Check for errors in response
        if data.get("error"):
            raise RuntimeError(f"OpenAI returned error: {data['error']}")
        
        # Check status
        status = data.get("status")
        if status and status != "completed":
            error_msg = f"OpenAI response status: {status}"
            if data.get("incomplete_details"):
                error_msg += f" - {data['incomplete_details']}"
            raise RuntimeError(error_msg)

        # Extract output_text from Responses API response
        output_text = data.get("output_text", "")
        
        if not output_text:
            # Fallback: try to find text in output array
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            output_text = content.get("text", "")
                            break
                        elif content.get("type") == "text":
                            output_text = content.get("text", "")
                            break

        if not output_text:
            # Log full response for debugging
            logger.error(f"No output_text found in response: {json.dumps(data, indent=2)[:2000]}")
            raise RuntimeError(
                f"OpenAI returned empty response. Status: {data.get('status', 'unknown')}. "
                f"This may happen if the PDF couldn't be processed or the model refused. "
                f"Response keys: {list(data.keys())}"
            )

        text = self._clean_json_response(output_text)
        
        # Validate JSON
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from OpenAI: {text[:500]}")
            raise RuntimeError(f"OpenAI returned invalid JSON: {e}. Response preview: {text[:200]}")
        
        return text

    async def _call_chat_completions(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Call the standard Chat Completions API for text-only requests."""
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        models_without_temperature = ("o1", "o3", "gpt-5")
        supports_temperature = not any(self._model.startswith(prefix) for prefix in models_without_temperature)

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        if supports_temperature:
            payload["temperature"] = temperature

        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUTS["chat"]) as client:
            resp = await client.post(CHAT_COMPLETIONS_ENDPOINT, headers=headers, json=payload)
            if resp.status_code != 200:
                error_text = resp.text
                raise RuntimeError(f"OpenAI API error ({resp.status_code}): {error_text}")
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        text = self._clean_json_response(content)
        json.loads(text)  # Validate
        return text

    def _clean_json_response(self, text: str) -> str:
        """Clean up response text, removing markdown fences if present."""
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            parts = text.split("\n", 1)
            if len(parts) == 2:
                _, remainder = parts
                if remainder.endswith("```"):
                    remainder = remainder[:-3]
                text = remainder.strip()
        return text
