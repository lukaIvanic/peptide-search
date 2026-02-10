"""Gemini LLM provider with PDF file support."""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional

import httpx

from ...config import settings
from .base import DocumentInput, InputType, LLMCapabilities

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    """Gemini provider using the Google Generative Language API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._model = model or settings.GEMINI_MODEL
        self._provider_name = (provider_name or "gemini").lower()
        self._last_usage: Optional[Dict[str, Optional[int]]] = None

    def name(self) -> str:
        return self._provider_name

    def model_name(self) -> str:
        return self._model

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            supports_pdf_url=False,
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
            raise RuntimeError("GEMINI_API_KEY is not set")

        self._last_usage = None
        parts: List[Dict[str, Any]] = [{"text": user_prompt}]
        if document:
            if document.input_type == InputType.TEXT and document.text:
                parts.append({"text": f"\n\nDocument text:\n{document.text}"})
            elif document.input_type == InputType.FILE:
                if not document.file_content:
                    raise RuntimeError("Missing file content for Gemini FILE input")
                parts.append(
                    {
                        "inlineData": {
                            "mimeType": "application/pdf",
                            "data": base64.b64encode(document.file_content).decode("utf-8"),
                        }
                    }
                )
            elif document.input_type == InputType.MULTI_FILE:
                files = document.files or []
                if not files:
                    raise RuntimeError("No files provided for Gemini MULTI_FILE input")
                for content, _filename in files:
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": "application/pdf",
                                "data": base64.b64encode(content).decode("utf-8"),
                            }
                        }
                    )
            elif document.input_type == InputType.URL:
                raise RuntimeError("Gemini provider does not support direct PDF URLs.")

        payload: Dict[str, Any] = {
            "systemInstruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }

        endpoint = f"{GEMINI_API_BASE}/models/{self._model}:generateContent?key={self._api_key}"
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(endpoint, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini API error ({resp.status_code}): {resp.text}")
            data = resp.json()

        self._last_usage = self._normalize_usage(data)
        text = self._extract_response_text(data)
        text = self._clean_json_response(text)
        json.loads(text)
        return text

    @staticmethod
    def _extract_response_text(data: Dict[str, Any]) -> str:
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini response missing candidates")
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        fragments: List[str] = []
        for part in parts:
            text = part.get("text")
            if text:
                fragments.append(text)
        if not fragments:
            raise RuntimeError("Gemini response contained no text parts")
        return "\n".join(fragments)

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
        usage = data.get("usageMetadata", {}) or {}
        input_tokens = usage.get("promptTokenCount")
        output_tokens = usage.get("candidatesTokenCount")
        total_tokens = usage.get("totalTokenCount")
        return {
            "input_tokens": int(input_tokens) if isinstance(input_tokens, int) else None,
            "output_tokens": int(output_tokens) if isinstance(output_tokens, int) else None,
            "reasoning_tokens": None,
            "total_tokens": int(total_tokens) if isinstance(total_tokens, int) else None,
        }
