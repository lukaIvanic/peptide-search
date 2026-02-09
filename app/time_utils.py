from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC time as naive datetime (legacy DB compatibility)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
