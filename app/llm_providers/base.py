from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
	"""Minimal interface for LLM providers returning JSON text."""

	def name(self) -> str:
		...

	async def generate_json(
		self,
		system_prompt: str,
		user_prompt: str,
		temperature: float = 0.2,
		max_tokens: int = 2000,
	) -> str:
		"""Return a JSON string as produced by the model."""
		...


