from __future__ import annotations


class RunCancelledError(RuntimeError):
    """Raised when a queued run is cancelled while a worker is processing it."""

