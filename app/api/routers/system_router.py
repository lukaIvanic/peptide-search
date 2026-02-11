from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import delete
from sqlmodel import Session

from ...config import settings
from ...db import get_session, ping_database
from ...integrations.llm import resolve_provider_selection
from ...persistence.models import ActiveSourceLock, ExtractionEntity, ExtractionRun, Paper, QueueJob
from ...schemas import ClearExtractionsResponse, HealthResponse
from ...services.queue_service import get_broadcaster, start_queue, stop_queue

router = APIRouter(tags=["system"])
logger = logging.getLogger(__name__)


@router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    if not ping_database():
        logger.warning("Health check database ping failed.")
    try:
        selection = resolve_provider_selection(
            provider=settings.LLM_PROVIDER,
            model=None,
            default_provider=settings.LLM_PROVIDER,
            require_enabled=False,
        )
        return HealthResponse(
            status="ok",
            provider=selection.provider_id,
            model=selection.model_id,
        )
    except Exception:
        return HealthResponse(status="ok", provider=settings.LLM_PROVIDER or "unknown", model=None)


@router.post("/api/admin/clear-extractions", response_model=ClearExtractionsResponse)
async def clear_extractions(session: Session = Depends(get_session)) -> ClearExtractionsResponse:
    """Dangerous: wipe all extracted runs and papers."""
    await stop_queue()
    try:
        session.exec(delete(ActiveSourceLock))
        session.exec(delete(QueueJob))
        session.exec(delete(ExtractionEntity))
        session.exec(delete(ExtractionRun))
        session.exec(delete(Paper))
        session.commit()
    finally:
        await start_queue()
    return ClearExtractionsResponse(status="ok")


@router.get("/api/stream")
async def stream_events() -> StreamingResponse:
    """SSE endpoint for live status updates."""
    broadcaster = get_broadcaster()
    queue = await broadcaster.subscribe()

    async def event_generator():
        try:
            yield f"data: {json.dumps({'event': 'connected', 'timestamp': ''})}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
