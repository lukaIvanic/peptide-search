from __future__ import annotations

from typing import Optional

FAILURE_BUCKET_LABELS = {
    "pdf_download": "PDF download (provider)",
    "pdf_processing": "PDF processing failed",
    "text_extraction": "Text extraction empty",
    "fetch_error": "Fetch error",
    "unsupported_doc": "Unsupported document",
    "legacy_bug": "Legacy extraction bug",
    "validation": "Parse/validation",
    "provider": "Provider error",
    "followup": "Follow-up error",
    "missing_raw_json": "Missing parent raw JSON",
    "not_found": "Missing record",
    "queue": "Queue/worker error",
    "other": "Other",
    "unknown": "Unknown",
}


def bucket_failure_reason(reason: Optional[str]) -> str:
    if not reason:
        return "unknown"
    lower = reason.lower()
    if "unknown failure" in lower:
        return "unknown"
    if "extractionrepository._entity_to_row" in lower or "entity_index" in lower:
        return "legacy_bug"
    if "timeout while downloading" in lower or "error while downloading" in lower:
        return "pdf_download"
    if "empty response" in lower or "couldn't be processed" in lower:
        return "pdf_download"
    if "failed to fetch the provided url" in lower:
        return "fetch_error"
    if "does not look like a pdf or html document" in lower:
        return "unsupported_doc"
    if "pdf processing failed" in lower:
        return "pdf_processing"
    if "no textual content could be extracted" in lower or "text extraction" in lower:
        return "text_extraction"
    if "parse/validation error" in lower or "failed to parse model output" in lower:
        return "validation"
    if "provider error" in lower:
        return "provider"
    if "failed to run followup" in lower or "followup" in lower:
        return "followup"
    if "prior run has no raw_json" in lower:
        return "missing_raw_json"
    if "not found" in lower:
        return "not_found"
    if "queue" in lower or "worker" in lower:
        return "queue"
    return "other"


def normalize_failure_reason(reason: Optional[str]) -> str:
    if not reason:
        return "Unknown failure"
    lower = reason.lower()
    if "unknown failure" in lower:
        return "Unknown failure"
    if "extractionrepository._entity_to_row" in lower or "entity_index" in lower:
        return "Legacy entity index bug"
    if "parse/validation error" in lower or "failed to parse model output" in lower:
        return "Parse/validation error"
    if "provider error" in lower:
        return "Provider error"
    if "failed to fetch the provided url" in lower:
        return "Fetch error"
    if "does not look like a pdf or html document" in lower:
        return "Unsupported document"
    if "timeout while downloading" in lower or "error while downloading" in lower:
        return "PDF download error"
    if "empty response" in lower or "couldn't be processed" in lower:
        return "PDF processing error"
    if "pdf processing failed" in lower:
        return "PDF processing failed"
    if "no textual content could be extracted" in lower or "text extraction" in lower:
        return "Text extraction empty"
    if "prior run has no raw_json" in lower:
        return "Parent run missing raw JSON"
    if "not found" in lower:
        return "Record not found"
    return reason[:120]
