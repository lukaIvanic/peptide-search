from __future__ import annotations

from fastapi import APIRouter

from ...integrations.llm import provider_catalog, refresh_provider_models
from ...schemas import ProvidersRefreshResponse, ProvidersResponse

router = APIRouter(tags=["providers"])


@router.get("/api/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    return ProvidersResponse(**provider_catalog())


@router.post("/api/providers/refresh", response_model=ProvidersRefreshResponse)
async def refresh_providers() -> ProvidersRefreshResponse:
    payload = await refresh_provider_models(force=True)
    return ProvidersRefreshResponse(**payload)
