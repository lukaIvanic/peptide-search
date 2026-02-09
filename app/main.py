from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.errors import register_error_handlers
from .api.routers import (
    baseline_router,
    extraction_router,
    metadata_router,
    papers_router,
    runs_router,
    search_router,
    system_router,
)
from .config import settings
from .db import assert_schema_current
from .services.queue_service import get_queue, start_queue, stop_queue
from .services.runtime_maintenance import (
    backfill_failed_runs,
    cancel_stale_runs,
    ensure_runtime_defaults,
)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        assert_schema_current()
        ensure_runtime_defaults()
        backfill_failed_runs()
        cancel_stale_runs()
        await start_queue()
        from .services.extraction_service import run_queued_extraction

        queue = get_queue()
        queue.set_extract_callback(run_queued_extraction)
        logger.info("Application started")
        try:
            yield
        finally:
            await stop_queue()
            logger.info("Application shutdown")

    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    register_error_handlers(app)
    cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    static_dir: Path = settings.STATIC_DIR
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir), html=False), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        @app.get("/runs/{run_id}", include_in_schema=False)
        async def run_detail(run_id: int) -> FileResponse:
            return FileResponse(static_dir / "run.html")

        @app.get("/runs/{run_id}/edit", include_in_schema=False)
        async def run_edit_page(run_id: int) -> FileResponse:
            return FileResponse(static_dir / "run_editor.html")

        @app.get("/entities", include_in_schema=False)
        async def entities_page() -> FileResponse:
            return FileResponse(static_dir / "entities.html")

        @app.get("/help", include_in_schema=False)
        async def help_page() -> FileResponse:
            return FileResponse(static_dir / "help.html")

        @app.get("/baseline", include_in_schema=False)
        async def baseline_overview_page() -> FileResponse:
            return FileResponse(static_dir / "batch-overview.html")

        @app.get("/baseline/{batch_id}", include_in_schema=False)
        async def baseline_detail_page(batch_id: str) -> FileResponse:
            return FileResponse(static_dir / "baseline.html")

        @app.get("/topbar_animations.html", include_in_schema=False)
        async def topbar_animations_page() -> FileResponse:
            return FileResponse(static_dir / "topbar_animations.html")

        @app.get("/topbar-animations", include_in_schema=False)
        async def topbar_animations_alias() -> FileResponse:
            return FileResponse(static_dir / "topbar_animations.html")

    app.include_router(system_router)
    app.include_router(search_router)
    app.include_router(extraction_router)
    app.include_router(papers_router)
    app.include_router(runs_router)
    app.include_router(metadata_router)
    app.include_router(baseline_router)

    return app


app = create_app()
