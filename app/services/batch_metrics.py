from __future__ import annotations

import re
from typing import Optional

from ..config import settings
from ..persistence.models import BatchRun
from ..time_utils import utc_now


MODEL_PRICING = {
    settings.OPENAI_MODEL: {"input": 2.50, "output": 10.00},
    settings.OPENAI_MODEL_MINI: {"input": 0.15, "output": 0.60},
    settings.OPENAI_MODEL_NANO: {"input": 0.10, "output": 0.40},
    "mock-model": {"input": 0, "output": 0},
}


def generate_batch_id(model_name: str) -> str:
    """Generate a unique batch ID with timestamp and model name."""
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    safe_model = re.sub(r"[^a-zA-Z0-9-]", "", model_name.replace(" ", "-"))
    return f"{timestamp}_{safe_model}"


def get_model_name_for_provider(provider: str) -> str:
    """Get the model name for a given provider."""
    provider_models = {
        "openai": settings.OPENAI_MODEL,
        "openai-mini": settings.OPENAI_MODEL_MINI,
        "openai-nano": settings.OPENAI_MODEL_NANO,
        "deepseek": settings.DEEPSEEK_MODEL,
        "mock": "mock-model",
    }
    return provider_models.get(provider, provider)


def compute_batch_cost(batch: BatchRun) -> Optional[float]:
    pricing = MODEL_PRICING.get(batch.model_name, MODEL_PRICING.get(settings.OPENAI_MODEL_NANO))
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
