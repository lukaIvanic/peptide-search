"""DeepSeek LLM provider (OpenAI-compatible API)."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from ...config import settings
from .base import DocumentInput, InputType, LLMCapabilities, LLMProvider

DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"


class DeepSeekProvider:
    """DeepSeek provider using OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or settings.DEEPSEEK_API_KEY
        self._model = model or settings.DEEPSEEK_MODEL

    def name(self) -> str:
        return "deepseek"
    
    def model_name(self) -> str:
        return self._model

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            supports_pdf_url=False,
            supports_pdf_file=False,
            supports_json_mode=True,
        )

    def get_last_usage(self) -> Optional[Dict[str, Optional[int]]]:
        return None

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        document: Optional[DocumentInput] = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        """
        Generate JSON response.
        
        DeepSeek only supports text input, so document must be pre-extracted text.
        """
        if not self._api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")

        # Build the full prompt with document text
        full_prompt = user_prompt
        if document:
            if document.input_type == InputType.TEXT and document.text:
                full_prompt = f"{user_prompt}\n\nDocument text:\n{document.text}"
            elif document.input_type in (InputType.URL, InputType.FILE, InputType.MULTI_FILE):
                raise RuntimeError(
                    f"DeepSeek provider does not support {document.input_type.name} input. "
                    "Text must be extracted first."
                )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": full_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(DEEPSEEK_ENDPOINT, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        text = self._clean_json_response(content)
        
        # Validate JSON
        json.loads(text)
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
