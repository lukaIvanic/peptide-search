from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RunRetryWithSourceRequest(BaseModel):
    source_url: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_id: Optional[int] = None


class ExtractionListItem(BaseModel):
    id: int
    paper_id: Optional[int] = None
    entity_count: int = 0
    comment: Optional[str] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    created_at: Optional[str] = None


class ExtractionDetailResponse(BaseModel):
    id: int
    paper_id: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    created_at: Optional[str] = None


class RunListItem(BaseModel):
    id: int
    paper_id: Optional[int] = None
    parent_run_id: Optional[int] = None
    status: Optional[str] = None
    failure_reason: Optional[str] = None
    prompts: Optional[Dict[str, Any]] = None
    raw_json: Optional[Dict[str, Any]] = None
    comment: Optional[str] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    pdf_url: Optional[str] = None
    entity_count: int = 0
    created_at: Optional[str] = None


class RunPaperInfo(BaseModel):
    id: int
    title: str
    doi: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    status: Optional[str] = None


class PaperRunsResponse(BaseModel):
    paper: RunPaperInfo
    runs: List[RunListItem]


class RecentRunPaperInfo(BaseModel):
    id: Optional[int] = None
    title: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None


class RecentRunItem(BaseModel):
    id: int
    paper_id: Optional[int] = None
    status: str
    failure_reason: Optional[str] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    created_at: Optional[str] = None
    paper: RecentRunPaperInfo


class RecentRunsResponse(BaseModel):
    runs: List[RecentRunItem]


class RunPayloadPaper(BaseModel):
    id: Optional[int] = None
    title: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)


class RunPayloadRun(BaseModel):
    id: int
    paper_id: Optional[int] = None
    parent_run_id: Optional[int] = None
    batch_id: Optional[str] = None
    baseline_case_id: Optional[str] = None
    baseline_dataset: Optional[str] = None
    status: str
    failure_reason: Optional[str] = None
    prompts: Optional[Dict[str, Any]] = None
    raw_json: Optional[Dict[str, Any]] = None
    comment: Optional[str] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    pdf_url: Optional[str] = None
    created_at: Optional[str] = None


class RunPayloadResponse(BaseModel):
    paper: RunPayloadPaper
    run: RunPayloadRun


class RunHistoryItem(BaseModel):
    id: int
    parent_run_id: Optional[int] = None
    status: str
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    created_at: Optional[str] = None


class RunHistoryResponse(BaseModel):
    paper_id: Optional[int] = None
    versions: List[RunHistoryItem]


class RetryResponse(BaseModel):
    id: Optional[int] = None
    status: Optional[str] = None
    message: str
    source_url: Optional[str] = None


class FailureBucketItem(BaseModel):
    key: str
    label: Optional[str] = None
    count: int
    example_run_id: Optional[int] = None
    example_paper_id: Optional[int] = None
    example_title: Optional[str] = None


class FailureSummaryResponse(BaseModel):
    total_failed: int
    runs_analyzed: int
    window_days: int
    window_start: Optional[str] = None
    buckets: List[FailureBucketItem]
    providers: List[FailureBucketItem]
    sources: List[FailureBucketItem]
    reasons: List[FailureBucketItem]


class FailedRunItem(BaseModel):
    id: int
    paper_id: Optional[int] = None
    status: str
    failure_reason: Optional[str] = None
    bucket: str
    normalized_reason: str
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    created_at: Optional[str] = None
    paper_title: Optional[str] = None
    paper_doi: Optional[str] = None
    paper_url: Optional[str] = None
    paper_source: Optional[str] = None
    paper_year: Optional[int] = None


class FailedRunsResponse(BaseModel):
    items: List[FailedRunItem]
    total: int
    window_days: int
    window_start: Optional[str] = None


class BulkRetryRequest(BaseModel):
    days: int = 30
    limit: int = 25
    max_runs: int = 1000
    bucket: Optional[str] = None
    provider: Optional[str] = None
    source: Optional[str] = None
    reason: Optional[str] = None


class BulkRetryResponse(BaseModel):
    requested: int
    enqueued: int
    skipped: int
    skipped_missing_pdf: int
    skipped_missing_paper: int
    skipped_not_failed: int
