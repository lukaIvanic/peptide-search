"""OpenAI LLM provider with PDF URL and file support."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from ...config import settings
from .base import DocumentInput, InputType, LLMCapabilities, LLMProvider

logger = logging.getLogger(__name__)

# API endpoints
CHAT_COMPLETIONS_ENDPOINT = "https://api.openai.com/v1/chat/completions"
RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
FILES_ENDPOINT = "https://api.openai.com/v1/files"


class OpenAIProvider:
    """OpenAI provider with support for direct PDF processing via Responses API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._model = model or settings.OPENAI_MODEL

    def name(self) -> str:
        return "openai"
    
    def model_name(self) -> str:
        return self._model

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            supports_pdf_url=True,
            supports_pdf_file=True,
            supports_json_mode=True,
        )

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        document: Optional[DocumentInput] = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> str:
        """Generate JSON response, handling different input types."""
        if document is None or document.input_type == InputType.TEXT:
            # Text-only: use Chat Completions API
            full_prompt = user_prompt
            if document and document.text:
                full_prompt = f"{user_prompt}\n\nDocument text:\n{document.text}"
            return await self._call_chat_completions(
                system_prompt=system_prompt,
                user_prompt=full_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        
        elif document.input_type == InputType.URL:
            # URL: use Responses API with file_url
            return await self._call_responses_api_with_url(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                pdf_url=document.url,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        
        elif document.input_type == InputType.FILE:
            # File: upload then use Responses API with file_id
            return await self._call_responses_api_with_file(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                file_content=document.file_content,
                filename=document.filename or "document.pdf",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        
        raise ValueError(f"Unsupported input type: {document.input_type}")

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ):
        """Stream JSON response tokens for text-only follow-ups."""
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

        supports_temperature = not any(
            self._model.startswith(prefix) for prefix in ("o1", "o3", "gpt-5")
        )

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "stream": True,
        }

        if supports_temperature:
            payload["temperature"] = temperature

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                CHAT_COMPLETIONS_ENDPOINT,
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    raise RuntimeError(f"OpenAI API error ({resp.status_code}): {text.decode('utf-8', 'ignore')}")

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content

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

        supports_temperature = not any(
            self._model.startswith(prefix) for prefix in ("o1", "o3", "gpt-5")
        )

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        if supports_temperature:
            payload["temperature"] = temperature

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(CHAT_COMPLETIONS_ENDPOINT, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI API error ({resp.status_code}): {resp.text}")
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        text = self._clean_json_response(content)
        json.loads(text)  # Validate
        return text

    async def _call_responses_api_with_url(
        self,
        system_prompt: str,
        user_prompt: str,
        pdf_url: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Call the Responses API with a file URL."""
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        input_content: List[Dict[str, Any]] = [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt},
                    {"type": "input_file", "file_url": pdf_url},
                ],
            },
        ]

        supports_temperature = not any(
            self._model.startswith(prefix) for prefix in ("o1", "o3", "gpt-5")
        )

        payload: Dict[str, Any] = {
            "model": self._model,
            "input": input_content,
            "text": {"format": {"type": "json_object"}},
        }

        if supports_temperature:
            payload["temperature"] = temperature
        if max_tokens:
            payload["max_output_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=300) as client:
            logger.info(f"Calling OpenAI Responses API with PDF: {pdf_url}")
            resp = await client.post(RESPONSES_ENDPOINT, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI API error ({resp.status_code}): {resp.text}")
            data = resp.json()

        return self._extract_response_text(data)

    async def _call_responses_api_with_file(
        self,
        system_prompt: str,
        user_prompt: str,
        file_content: bytes,
        filename: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Upload file and call Responses API with file_id."""
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
            await self._delete_file(file_id)

    async def _upload_file(self, file_content: bytes, filename: str) -> str:
        """Upload a file to OpenAI Files API and return the file ID."""
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        headers = {"Authorization": f"Bearer {self._api_key}"}
        files = {
            "file": (filename, file_content, "application/pdf"),
            "purpose": (None, "user_data"),
        }

        async with httpx.AsyncClient(timeout=120) as client:
            logger.info(f"Uploading file to OpenAI: {filename}")
            resp = await client.post(FILES_ENDPOINT, headers=headers, files=files)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI file upload error ({resp.status_code}): {resp.text}")
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

        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
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
        """Call the Responses API with a file ID."""
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        input_content: List[Dict[str, Any]] = [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt},
                    {"type": "input_file", "file_id": file_id},
                ],
            },
        ]

        supports_temperature = not any(
            self._model.startswith(prefix) for prefix in ("o1", "o3", "gpt-5")
        )

        payload: Dict[str, Any] = {
            "model": self._model,
            "input": input_content,
            "text": {"format": {"type": "json_object"}},
        }

        if supports_temperature:
            payload["temperature"] = temperature
        if max_tokens:
            payload["max_output_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=300) as client:
            logger.info(f"Calling OpenAI Responses API with file_id: {file_id}")
            resp = await client.post(RESPONSES_ENDPOINT, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI API error ({resp.status_code}): {resp.text}")
            data = resp.json()

        return self._extract_response_text(data)

    def _extract_response_text(self, data: dict) -> str:
        """Extract text from Responses API response."""
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
                        if content.get("type") in ("output_text", "text"):
                            output_text = content.get("text", "")
                            if output_text:
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
