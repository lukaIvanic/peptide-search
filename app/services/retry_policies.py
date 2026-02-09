from __future__ import annotations

from typing import Optional

from .failure_reason import bucket_failure_reason, normalize_failure_reason


def failure_matches_filters(
    failure_reason: Optional[str],
    bucket: Optional[str] = None,
    reason: Optional[str] = None,
) -> bool:
    if bucket and bucket_failure_reason(failure_reason) != bucket:
        return False
    if reason and normalize_failure_reason(failure_reason) != reason:
        return False
    return True


def reconcile_skipped_count(
    *,
    requested: int,
    enqueued: int,
    skipped: int,
    skipped_not_failed: int,
) -> int:
    accounted = enqueued + skipped + skipped_not_failed
    if requested <= accounted:
        return skipped
    return skipped + (requested - accounted)


def resolve_retry_source_url(
    requested_source_url: Optional[str],
    run_pdf_url: Optional[str],
    paper_url: Optional[str],
) -> Optional[str]:
    return requested_source_url or run_pdf_url or paper_url
