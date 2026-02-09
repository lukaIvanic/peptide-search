from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable


def iso_z(value: datetime | None) -> str | None:
    if not value:
        return None
    return f"{value.isoformat()}Z"


def parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def parse_json_list(value: str | None) -> list[Any]:
    parsed = parse_json(value, [])
    return parsed if isinstance(parsed, list) else []


def parse_json_object(value: str | None) -> dict[str, Any]:
    parsed = parse_json(value, {})
    return parsed if isinstance(parsed, dict) else {}


def coerce_str_list(value: Iterable[Any] | None) -> list[str]:
    if not value:
        return []
    return [str(item) for item in value if item is not None]
