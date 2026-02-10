from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SearchItem(BaseModel):
    """A search result item with optional processing status."""

    title: str
    doi: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    pdf_urls: Optional[List[str]] = None
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    seen: bool = False
    processed: bool = False


class SearchResponse(BaseModel):
    results: List[SearchItem]


class EnqueueItem(BaseModel):
    """A paper to enqueue for extraction."""

    title: str
    doi: Optional[str] = None
    url: Optional[str] = None
    pdf_url: str
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    force: bool = False


class EnqueueRequest(BaseModel):
    """Request to enqueue papers for extraction."""

    papers: List[EnqueueItem]
    provider: str = "openai"
    model: Optional[str] = None
    prompt_id: Optional[int] = None


class EnqueuedRun(BaseModel):
    """Info about an enqueued run."""

    run_id: int
    paper_id: int
    title: str
    status: str
    skipped: bool = False
    skip_reason: Optional[str] = None


class EnqueueResponse(BaseModel):
    """Response from enqueue endpoint."""

    runs: List[EnqueuedRun]
    total: int
    enqueued: int
    skipped: int


class UploadEnqueueResponse(BaseModel):
    """Response from upload enqueue endpoint."""

    run_id: int
    paper_id: Optional[int] = None
    status: str
    message: str
