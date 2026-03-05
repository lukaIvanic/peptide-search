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


class UploadEnqueueResponse(BaseModel):
    """Response from upload enqueue endpoint."""

    run_id: int
    paper_id: Optional[int] = None
    status: str
    message: str
