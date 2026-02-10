from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BaselineDatasetInfo(BaseModel):
    id: str
    label: Optional[str] = None
    description: Optional[str] = None
    count: int = 0


class BaselineRunSummary(BaseModel):
    run_id: int
    paper_id: Optional[int] = None
    status: str
    failure_reason: Optional[str] = None
    created_at: Optional[str] = None
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    batch_id: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    extraction_time_ms: Optional[int] = None


class BaselineCase(BaseModel):
    id: str
    dataset: str
    paper_key: Optional[str] = None
    updated_at: Optional[str] = None
    sequence: Optional[str] = None
    n_terminal: Optional[str] = None
    c_terminal: Optional[str] = None
    source_unverified: bool = False
    labels: List[str] = Field(default_factory=list)
    doi: Optional[str] = None
    pubmed_id: Optional[str] = None
    paper_url: Optional[str] = None
    pdf_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaselineCaseSummary(BaselineCase):
    latest_run: Optional[BaselineRunSummary] = None


class BaselineCasesResponse(BaseModel):
    cases: List[BaselineCaseSummary]
    datasets: List[BaselineDatasetInfo]
    total_cases: int


class BaselineEnqueuedRun(BaseModel):
    baseline_case_id: str
    run_id: Optional[int] = None
    status: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None


class BaselineEnqueueRequest(BaseModel):
    provider: str = "openai"
    model: Optional[str] = None
    prompt_id: Optional[int] = None
    force: bool = False
    dataset: Optional[str] = None


class BaselineEnqueueResponse(BaseModel):
    runs: List[BaselineEnqueuedRun]
    total: int
    enqueued: int
    skipped: int


class ResolvedSourceResponse(BaseModel):
    found: bool
    title: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)


class LocalPdfInfoResponse(BaseModel):
    found: bool
    filename: Optional[str] = None


class LocalPdfSiInfoResponse(BaseModel):
    found: bool
    filenames: List[str] = Field(default_factory=list)
    count: int = 0


class BaselineRetryRequest(BaseModel):
    source_url: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_id: Optional[int] = None


class BaselineCaseCreateRequest(BaseModel):
    id: str
    dataset: str
    sequence: Optional[str] = None
    n_terminal: Optional[str] = None
    c_terminal: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    doi: Optional[str] = None
    pubmed_id: Optional[str] = None
    paper_url: Optional[str] = None
    pdf_url: Optional[str] = None
    source_unverified: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaselineCaseUpdateRequest(BaseModel):
    expected_updated_at: str
    dataset: Optional[str] = None
    sequence: Optional[str] = None
    n_terminal: Optional[str] = None
    c_terminal: Optional[str] = None
    labels: Optional[List[str]] = None
    doi: Optional[str] = None
    pubmed_id: Optional[str] = None
    paper_url: Optional[str] = None
    pdf_url: Optional[str] = None
    source_unverified: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class BaselineCaseDeleteRequest(BaseModel):
    expected_updated_at: str


class BaselineDeleteResponse(BaseModel):
    status: str
    deleted_cases: int


class BaselineResetResponse(BaseModel):
    status: str
    deleted_cases: int
    inserted_cases: int
    total_cases: int


class BaselineRecomputeStatusResponse(BaseModel):
    running: bool
    queued: bool
    stale_batches: int
    processing_batches: int
    last_started_at: Optional[str] = None
    last_finished_at: Optional[str] = None


class BaselineShadowSeedRequest(BaseModel):
    dataset: Optional[str] = None
    limit: Optional[int] = None
    force: bool = False


class BaselineShadowSeedResponse(BaseModel):
    total: int
    seeded: int
    skipped: int


class BatchEnqueueRequest(BaseModel):
    """Request to create a batch and enqueue all papers."""

    dataset: str
    label: Optional[str] = None
    provider: str = "openai-nano"
    model: Optional[str] = None
    prompt_id: Optional[int] = None
    force: bool = False


class BatchInfo(BaseModel):
    """Summary of a batch run."""

    id: int
    batch_id: str
    label: Optional[str] = None
    dataset: str
    model_provider: str
    model_name: str
    status: str
    total_papers: int
    completed: int
    failed: int
    total_input_tokens: int
    total_output_tokens: int
    total_time_ms: int
    matched_entities: int = 0
    total_expected_entities: int = 0
    match_rate: Optional[float] = None
    papers_all_matched: int = 0
    estimated_cost_usd: Optional[float] = None
    created_at: str


class BatchListResponse(BaseModel):
    """Response for batch list."""

    batches: List[BatchInfo]


class BatchEnqueueResponse(BaseModel):
    """Response from batch enqueue."""

    batch_id: str
    total_papers: int
    enqueued: int
    skipped: int


class BatchRetryRequest(BaseModel):
    """Request to retry failed runs in a batch."""

    batch_id: str
    provider: Optional[str] = None
    model: Optional[str] = None


class BatchRetryResponse(BaseModel):
    """Response from batch retry."""

    batch_id: str
    retried: int
    skipped: int


class BatchStopRequest(BaseModel):
    """Request to stop all in-progress runs in a batch."""

    batch_id: str


class BatchStopResponse(BaseModel):
    """Response from batch stop."""

    batch_id: str
    cancelled_runs: int
    cancelled_jobs: int


class DeleteBatchResponse(BaseModel):
    status: str
    deleted_runs: int
