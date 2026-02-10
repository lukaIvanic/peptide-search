from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class PaperWithStatus(BaseModel):
    """Paper with latest run status for the unified table."""

    id: int
    title: str
    doi: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    latest_run_id: Optional[int] = None
    status: Optional[str] = None
    failure_reason: Optional[str] = None
    last_run_at: Optional[str] = None
    run_count: int = 0


class PapersWithStatusResponse(BaseModel):
    """Response for papers list with status."""

    papers: List[PaperWithStatus]
    queue_stats: Optional[dict] = None


class PaperRow(BaseModel):
    id: int
    title: str
    doi: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    extraction_count: int = 0


class PapersResponse(BaseModel):
    papers: List[PaperRow]


class ForceReextractResponse(BaseModel):
    id: Optional[int] = None
    paper_id: int
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: Optional[str] = None


class ProviderCapabilities(BaseModel):
    supports_pdf_url: bool
    supports_pdf_file: bool
    supports_json_mode: bool


class ProviderCatalogItem(BaseModel):
    provider_id: str
    label: str
    enabled: bool
    capabilities: ProviderCapabilities
    default_model: str
    curated_models: List[str] = Field(default_factory=list)
    supports_custom_model: bool = True
    supports_model_discovery: bool = False
    cache_ttl_seconds: Optional[int] = None
    last_refreshed_at: Optional[str] = None


class ProvidersResponse(BaseModel):
    providers: List[ProviderCatalogItem] = Field(default_factory=list)


class ProvidersRefreshWarning(BaseModel):
    provider_id: str
    message: str


class ProvidersRefreshResponse(ProvidersResponse):
    warnings: List[ProvidersRefreshWarning] = Field(default_factory=list)


class ClearExtractionsResponse(BaseModel):
    status: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
