"""OpenRouter provider with URL/file multimodal support."""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional

import httpx

from ...config import settings
from .base import DocumentInput, InputType, LLMCapabilities

OPENROUTER_CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider:
    """OpenRouter chat-completions provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or settings.OPENROUTER_API_KEY
        self._model = model or settings.OPENROUTER_MODEL
        self._provider_name = (provider_name or "openrouter").lower()
        self._last_usage: Optional[Dict[str, Optional[int]]] = None

    def name(self) -> str:
        return self._provider_name

    def model_name(self) -> str:
        return self._model

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            supports_pdf_url=True,
            supports_pdf_file=True,
            supports_json_mode=True,
        )

    def get_last_usage(self) -> Optional[Dict[str, Optional[int]]]:
        if not self._last_usage:
            return None
        return dict(self._last_usage)

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        document: Optional[DocumentInput] = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")

        self._last_usage = None
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.append(self._build_user_message(user_prompt, document))

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(OPENROUTER_CHAT_ENDPOINT, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenRouter API error ({resp.status_code}): {resp.text}")
            data = resp.json()

        self._last_usage = self._normalize_usage(data)
        text = self._extract_response_text(data)
        text = self._clean_json_response(text)
        json.loads(text)
        return text

    @staticmethod
    def _build_user_message(user_prompt: str, document: Optional[DocumentInput]) -> Dict[str, Any]:
        if not document or document.input_type == InputType.TEXT:
            full_prompt = user_prompt
            if document and document.text:
                full_prompt = f"{user_prompt}\n\nDocument text:\n{document.text}"
            return {"role": "user", "content": full_prompt}

        content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        if document.input_type == InputType.URL and document.url:
            content.append({"type": "file", "file": {"url": document.url}})
        elif document.input_type == InputType.FILE and document.file_content:
            encoded = base64.b64encode(document.file_content).decode("utf-8")
            data_url = f"data:application/pdf;base64,{encoded}"
            content.append(
                {
                    "type": "file",
                    "file": {
                        "filename": document.filename or "document.pdf",
                        "file_data": data_url,
                    },
                }
            )
        elif document.input_type == InputType.MULTI_FILE:
            files = document.files or []
            if not files:
                raise RuntimeError("No files provided for OpenRouter MULTI_FILE input")
            for idx, (raw, filename) in enumerate(files):
                encoded = base64.b64encode(raw).decode("utf-8")
                data_url = f"data:application/pdf;base64,{encoded}"
                content.append(
                    {
                        "type": "file",
                        "file": {
                            "filename": filename or f"document_{idx + 1}.pdf",
                            "file_data": data_url,
                        },
                    }
                )
        else:
            raise RuntimeError("Unsupported OpenRouter document input")
        return {"role": "user", "content": content}

    @staticmethod
    def _extract_response_text(data: Dict[str, Any]) -> str:
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenRouter response missing choices")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            pieces: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        pieces.append(text)
            if pieces:
                return "\n".join(pieces)
        raise RuntimeError("OpenRouter response contained no text content")

    @staticmethod
    def _clean_json_response(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            split = cleaned.split("\n", 1)
            if len(split) == 2:
                cleaned = split[1]
            cleaned = cleaned[:-3] if cleaned.endswith("```") else cleaned
        return cleaned.strip()

    @staticmethod
    def _normalize_usage(data: Dict[str, Any]) -> Dict[str, Optional[int]]:
        usage = data.get("usage", {}) or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        reasoning_tokens = usage.get("reasoning_tokens")
        return {
            "input_tokens": int(input_tokens) if isinstance(input_tokens, int) else None,
            "output_tokens": int(output_tokens) if isinstance(output_tokens, int) else None,
            "reasoning_tokens": int(reasoning_tokens) if isinstance(reasoning_tokens, int) else None,
            "total_tokens": int(total_tokens) if isinstance(total_tokens, int) else None,
        }
