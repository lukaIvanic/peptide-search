from __future__ import annotations

import json
from typing import Any, Dict

import httpx

from ..config import settings
from .base import LLMProvider


DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"


class DeepSeekProvider(LLMProvider):
	def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
		self._api_key = api_key or settings.DEEPSEEK_API_KEY
		self._model = model or settings.DEEPSEEK_MODEL

	def name(self) -> str:
		return "deepseek"

	async def generate_json(
		self,
		system_prompt: str,
		user_prompt: str,
		temperature: float = 0.2,
		max_tokens: int = 2000,
	) -> str:
		if not self._api_key:
			raise RuntimeError("DEEPSEEK_API_KEY is not set")

		headers = {
			"Authorization": f"Bearer {self._api_key}",
			"Content-Type": "application/json",
		}

		payload: Dict[str, Any] = {
			"model": self._model,
			"messages": [
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": user_prompt},
			],
			"temperature": temperature,
			"max_tokens": max_tokens,
		}

		# Some OpenAI-compatible providers support JSON mode
		# If DeepSeek supports response_format, pass it; otherwise it will be ignored.
		payload["response_format"] = {"type": "json_object"}

		async with httpx.AsyncClient(timeout=90) as client:
			resp = await client.post(DEEPSEEK_ENDPOINT, headers=headers, json=payload)
			resp.raise_for_status()
			data = resp.json()

		# OpenAI-compatible shape
		content = data["choices"][0]["message"]["content"]

		# Ensure it's a JSON string (if model returns markdown, try to strip code fences)
		text = content.strip()
		if text.startswith("```"):
			# Strip any ```json ... ``` fences
			text = text.strip("`")
			parts = text.split("\n", 1)
			if len(parts) == 2:
				_, remainder = parts
				if remainder.endswith("```"):
					remainder = remainder[:-3]
				text = remainder.strip()

		# Validate JSON parsability early (raises if invalid)
		json.loads(text)
		return text


