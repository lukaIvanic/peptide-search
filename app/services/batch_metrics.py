from __future__ import annotations

import re
from typing import Optional

from ..config import settings
from ..persistence.models import BatchRun
from ..time_utils import utc_now


# Prices are USD per 1M tokens. Cached-input discounts are not applied here yet.
_BASE_MODEL_PRICING = {
    "gpt-5.2": {"input": 1.75, "output": 14.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "moonshotai/kimi-k2.5": {"input": 0.45, "output": 2.25},
    "kimi-k2.5": {"input": 0.45, "output": 2.25},
    "gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
    "google/gemini-3-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-3-flash": {"input": 0.50, "output": 3.00},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "google/gemini-3-flash": {"input": 0.50, "output": 3.00},
    "google/gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "google/gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "z-ai/glm-4.7": {"input": 0.40, "output": 1.50},
    "glm-4.7": {"input": 0.40, "output": 1.50},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "mock-model": {"input": 0, "output": 0},
}
MODEL_PRICING = {
    key.strip().lower(): value
    for key, value in _BASE_MODEL_PRICING.items()
}
if settings.OPENAI_MODEL:
    MODEL_PRICING.setdefault(
        settings.OPENAI_MODEL.strip().lower(),
        MODEL_PRICING["gpt-4o"],
    )
if settings.OPENAI_MODEL_MINI:
    MODEL_PRICING[settings.OPENAI_MODEL_MINI.strip().lower()] = MODEL_PRICING["gpt-5-mini"]
if settings.OPENAI_MODEL_NANO:
    MODEL_PRICING[settings.OPENAI_MODEL_NANO.strip().lower()] = MODEL_PRICING["gpt-5-nano"]


def generate_batch_id(model_name: str) -> str:
    """Generate a unique batch ID with timestamp and model name."""
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    safe_model = re.sub(r"[^a-zA-Z0-9-]", "", model_name.replace(" ", "-"))
    return f"{timestamp}_{safe_model}"


def get_model_name_for_provider(provider: str) -> str:
    """Get the model name for a given provider."""
    provider_models = {
        "openai": settings.OPENAI_MODEL,
        "openai-full": settings.OPENAI_MODEL,
        "openai-mini": settings.OPENAI_MODEL_MINI,
        "openai-nano": settings.OPENAI_MODEL_NANO,
        "deepseek": settings.DEEPSEEK_MODEL,
        "gemini": settings.GEMINI_MODEL,
        "openrouter": settings.OPENROUTER_MODEL,
        "mock": "mock-model",
    }
    return provider_models.get(provider, provider)


def compute_batch_cost(batch: BatchRun) -> Optional[float]:
    model_key = (batch.model_name or "").strip().lower()
    pricing = MODEL_PRICING.get(model_key)
    if not pricing:
        return None
    input_cost = (batch.total_input_tokens / 1_000_000) * pricing["input"]
    output_cost = (batch.total_output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def compute_match_rate(batch: BatchRun) -> Optional[float]:
    if not batch.total_expected_entities:
        return None
    return batch.matched_entities / batch.total_expected_entities


def compute_wall_clock_time_ms(batch: BatchRun) -> int:
    if not batch.created_at:
        return 0
    end_time = batch.completed_at if batch.completed_at else utc_now()
    delta = end_time - batch.created_at
    return int(delta.total_seconds() * 1000)
