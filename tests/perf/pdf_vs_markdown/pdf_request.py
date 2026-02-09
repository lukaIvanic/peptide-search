"""Benchmark PDF upload latency using the OpenAI provider."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import time

from app.config import settings
from app.prompts import build_system_prompt, build_user_prompt
from openai import OpenAI

PDF_PATH = Path(__file__).resolve().parent / "paper.pdf"
MODEL = "gpt-5-nano"
MAX_OUTPUT_TOKENS = 128


async def main() -> None:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF file not found: {PDF_PATH}")

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt("", "[PDF document attached - analyze the full document]")

    supports_temperature = not any(
        MODEL.startswith(prefix) for prefix in ("o1", "o3", "gpt-5")
    )

    start_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=120)
    with PDF_PATH.open("rb") as handle:
        uploaded = client.files.create(file=handle, purpose="user_data")
    input_content = [
        {
            "role": "developer",
            "content": [{"type": "input_text", "text": system_prompt}],
        },
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": user_prompt},
                {"type": "input_file", "file_id": uploaded.id},
            ],
        },
    ]
    payload = {
        "model": MODEL,
        "input": input_content,
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "low"},
    }
    if supports_temperature:
        payload["temperature"] = settings.TEMPERATURE
    response = client.responses.create(**payload)
    elapsed = time.perf_counter() - start
    end_at = datetime.now(timezone.utc)

    print("PDF benchmark complete")
    print(f"start_utc: {start_at.isoformat()}")
    print(f"end_utc: {end_at.isoformat()}")
    print(f"elapsed_seconds: {elapsed:.2f}")
    print(f"response_chars: {len(response.output_text)}")
    print(f"input_tokens: {response.usage.input_tokens}")
    print(f"output_tokens: {response.usage.output_tokens}")
    print(f"reasoning_tokens: {response.usage.output_tokens_details.reasoning_tokens}")


if __name__ == "__main__":
    asyncio.run(main())
