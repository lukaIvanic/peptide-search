from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.access_gate import AccessGateMiddleware
from .api.errors import register_error_handlers
from .api.routers import (
    baseline_router,
    extraction_router,
    metadata_router,
    papers_router,
    providers_router,
    runs_router,
    search_router,
    system_router,
)
from .config import settings
from .db import assert_schema_current
from .services.queue_service import get_queue, start_queue, stop_queue
from .services.runtime_maintenance import (
    backfill_failed_runs,
    ensure_runtime_defaults,
    reconcile_orphan_run_states,
)

logger = logging.getLogger(__name__)


def _static_page_response(static_dir: Path, filename: str) -> FileResponse:
    return FileResponse(static_dir / filename)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        assert_schema_current()
        ensure_runtime_defaults()
        backfill_failed_runs()
        reconcile_orphan_run_states()
        try:
            await start_queue()
            from .services.extraction_service import run_queued_extraction

            queue = get_queue()
            queue.set_extract_callback(run_queued_extraction)
        except Exception:
            logger.exception("Application startup failed during queue initialization.")
            try:
                await stop_queue()
            except Exception:
                logger.exception("Queue cleanup failed after startup error.")
            raise
        logger.info("Application started")
        try:
            yield
        finally:
            try:
                await stop_queue()
                logger.info("Application shutdown")
            except Exception:
                logger.exception("Application shutdown encountered queue stop errors.")
                raise

    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
    register_error_handlers(app)
    if settings.ACCESS_GATE_ENABLED:
        app.add_middleware(
            AccessGateMiddleware,
            username=settings.ACCESS_GATE_USERNAME,
            password=settings.ACCESS_GATE_PASSWORD,
        )
    cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    if settings.REQUEST_LOGGING_ENABLED:
        @app.middleware("http")
        async def log_request_lifecycle(request: Request, call_next):
            if request.url.path.startswith("/static/"):
                return await call_next(request)

            request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
            started_at = time.perf_counter()
            try:
                response = await call_next(request)
            except Exception:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                logger.exception(
                    "request_failed request_id=%s method=%s path=%s elapsed_ms=%.2f",
                    request_id,
                    request.method,
                    request.url.path,
                    elapsed_ms,
                )
                raise

            elapsed_ms = (time.perf_counter() - started_at) * 1000
            response.headers["X-Request-Id"] = request_id
            logger.info(
                "request_completed request_id=%s method=%s path=%s status=%s elapsed_ms=%.2f",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
            return response

    static_dir: Path = settings.STATIC_DIR
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir), html=False), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return _static_page_response(static_dir, "index.html")

        @app.get("/runs/{run_id}", include_in_schema=False)
        async def run_detail(run_id: int) -> FileResponse:
            return _static_page_response(static_dir, "run.html")

        @app.get("/runs/{run_id}/edit", include_in_schema=False)
        async def run_edit_page(run_id: int) -> FileResponse:
            return _static_page_response(static_dir, "run_editor.html")

        @app.get("/entities", include_in_schema=False)
        async def entities_page() -> FileResponse:
            return _static_page_response(static_dir, "entities.html")

        @app.get("/help", include_in_schema=False)
        async def help_page() -> FileResponse:
            return _static_page_response(static_dir, "help.html")

        @app.get("/baseline", include_in_schema=False)
        async def baseline_overview_page() -> FileResponse:
            overview_path = static_dir / "batch-overview.html"
            if overview_path.exists():
                return FileResponse(overview_path)
            return _static_page_response(static_dir, "baseline.html")

        @app.get("/baseline/{batch_id}", include_in_schema=False)
        async def baseline_detail_page(batch_id: str) -> FileResponse:
            return _static_page_response(static_dir, "baseline.html")

        @app.get("/topbar_animations.html", include_in_schema=False)
        async def topbar_animations_page() -> FileResponse:
            return _static_page_response(static_dir, "topbar_animations.html")

        @app.get("/topbar-animations", include_in_schema=False)
        async def topbar_animations_alias() -> FileResponse:
            return _static_page_response(static_dir, "topbar_animations.html")

    app.include_router(system_router)
    app.include_router(providers_router)
    app.include_router(search_router)
    app.include_router(extraction_router)
    app.include_router(papers_router)
    app.include_router(runs_router)
    app.include_router(metadata_router)
    app.include_router(baseline_router)

    return app


app = create_app()
