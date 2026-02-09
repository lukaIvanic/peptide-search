"""OpenAI health check using the official Python library."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import time

from dotenv import load_dotenv
from openai import OpenAI

MODEL = "gpt-5-nano"
TIMEOUT_SECONDS = 120
MAX_OUTPUT_TOKENS = 800
TARGET_INPUT_TOKENS = 100_000
CHARS_PER_TOKEN_EST = 4
BASE_PARAGRAPH = (
    "This is a synthetic benchmark paragraph for latency testing. "
    "It contains enough repetition to approximate a large input size "
    "without relying on external files or PDFs. "
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


def build_large_prompt() -> str:
    target_chars = TARGET_INPUT_TOKENS * CHARS_PER_TOKEN_EST
    chunk = BASE_PARAGRAPH.strip() + "\n"
    repetitions = max(1, target_chars // len(chunk) + 1)
    body = chunk * repetitions
    return (
        "Please answer briefly in under 2 sentences.\n\n"
        f"{body[:target_chars]}"
    )


async def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    prompt_text = build_large_prompt()

    start_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    client = OpenAI(api_key=api_key, timeout=TIMEOUT_SECONDS)
    response = client.responses.create(
        model=MODEL,
        input=prompt_text,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    elapsed = time.perf_counter() - start
    end_at = datetime.now(timezone.utc)

    print("OpenAI health check complete")
    print(f"start_utc: {start_at.isoformat()}")
    print(f"end_utc: {end_at.isoformat()}")
    print(f"elapsed_seconds: {elapsed:.2f}")
    print(f"input_chars: {len(prompt_text)}")
    print(f"input_words: {len(prompt_text.split())}")
    print(f"response_id: {response.id}")
    if getattr(response, "request_id", None):
        print(f"request_id: {response.request_id}")
    print(f"output_text: {response.output_text}")
    print(f"response: {response}")


if __name__ == "__main__":
    asyncio.run(main())
