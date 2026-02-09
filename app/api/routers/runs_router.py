from __future__ import annotations

import json
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import Session, func, select

from ...config import settings
from ...db import get_session
from ...integrations.document import DocumentExtractor
from ...persistence.models import BaselineCaseRun, Extraction, ExtractionEntity, ExtractionRun, Paper, RunStatus
from ...persistence.repository import BaselineCaseRunRepository
from ...schemas import (
    BulkRetryRequest,
    BulkRetryResponse,
    EditRunRequest,
    ExtractResponse,
    FailedRunsResponse,
    FailureSummaryResponse,
    FollowupRequest,
    ResolvedSourceResponse,
    RunRetryWithSourceRequest,
)
from ...services.baseline_helpers import link_cases_to_run, select_baseline_result
from ...services.extraction_service import run_edit, run_extraction_from_files, run_followup, run_followup_stream
from ...services.failure_reason import FAILURE_BUCKET_LABELS, bucket_failure_reason, normalize_failure_reason
from ...services.queue_service import get_queue
from ...services.runs_retry_service import (
    ServiceError,
    list_failed_runs_payload,
    retry_failed_runs as retry_failed_runs_service,
    retry_run as retry_run_service,
    retry_run_with_source as retry_run_with_source_service,
    run_history_payload,
)
from ...services.search_service import search_all_free_sources
from ...time_utils import utc_now
from ...services.view_builders import build_run_payload

router = APIRouter(tags=["runs"])


@router.get("/api/extractions")
async def list_extractions(session: Session = Depends(get_session)) -> list[dict]:
    has_run = session.exec(select(ExtractionRun.id).limit(1)).first()
    if has_run:
        subq = (
            select(ExtractionEntity.run_id, func.count(ExtractionEntity.id).label("cnt"))
            .group_by(ExtractionEntity.run_id)
            .subquery()
        )
        stmt = (
            select(ExtractionRun, subq.c.cnt)
            .outerjoin(subq, ExtractionRun.id == subq.c.run_id)
            .order_by(ExtractionRun.created_at.desc())
            .limit(200)
        )
        rows = session.exec(stmt).all()
        result: list[dict] = []
        for run, cnt in rows:
            result.append(
                {
                    "id": run.id,
                    "paper_id": run.paper_id,
                    "entity_count": int(cnt or 0),
                    "comment": run.comment,
                    "model_provider": run.model_provider,
                    "model_name": run.model_name,
                    "created_at": run.created_at.isoformat() + "Z",
                }
            )
        return result

    stmt = select(Extraction).order_by(Extraction.created_at.desc()).limit(200)
    rows = session.exec(stmt).all()
    result: list[dict] = []
    for r in rows:
        result.append(
            {
                "id": r.id,
                "paper_id": r.paper_id,
                "entity_type": r.entity_type,
                "sequence": r.peptide_sequence_one_letter,
                "chemical_formula": r.chemical_formula,
                "labels": json.loads(r.labels) if r.labels else [],
                "morphology": json.loads(r.morphology) if r.morphology else [],
                "created_at": r.created_at.isoformat() + "Z",
            }
        )
    return result


@router.get("/api/extractions/{extraction_id}")
async def get_extraction(extraction_id: int, session: Session = Depends(get_session)) -> dict:
    has_run = session.exec(select(ExtractionRun.id).limit(1)).first()
    if has_run:
        run = session.get(ExtractionRun, extraction_id)
        if not run:
            raise HTTPException(status_code=404, detail="ExtractionRun not found")
        try:
            payload = json.loads(run.raw_json or "{}")
        except Exception:
            payload = {}
        return {
            "id": run.id,
            "paper_id": run.paper_id,
            "payload": payload,
            "model_provider": run.model_provider,
            "model_name": run.model_name,
            "created_at": run.created_at.isoformat() + "Z",
        }

    row = session.get(Extraction, extraction_id)
    if not row:
        raise HTTPException(status_code=404, detail="Extraction not found")
    try:
        payload = json.loads(row.raw_json or "{}")
    except Exception:
        payload = {}
    return {
        "id": row.id,
        "paper_id": row.paper_id,
        "payload": payload,
        "model_provider": row.model_provider,
        "model_name": row.model_name,
        "created_at": row.created_at.isoformat() + "Z",
    }


@router.get("/api/runs")
async def list_runs(
    paper_id: int = Query(...),
    session: Session = Depends(get_session),
) -> dict:
    """List all runs for a paper, including prompts and raw JSON."""
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    authors = []
    if paper.authors_json:
        try:
            authors = json.loads(paper.authors_json)
        except Exception:
            authors = []

    stmt = (
        select(ExtractionRun)
        .where(ExtractionRun.paper_id == paper_id)
        .order_by(ExtractionRun.created_at.desc())
    )
    runs = session.exec(stmt).all()

    entity_counts: dict[int, int] = {}
    if runs:
        run_ids = [r.id for r in runs if r.id]
        count_stmt = (
            select(ExtractionEntity.run_id, func.count(ExtractionEntity.id))
            .where(ExtractionEntity.run_id.in_(run_ids))
            .group_by(ExtractionEntity.run_id)
        )
        for run_id, cnt in session.exec(count_stmt).all():
            entity_counts[run_id] = cnt

    runs_data = []
    for run in runs:
        prompts = None
        if run.prompts_json:
            try:
                prompts = json.loads(run.prompts_json)
            except Exception:
                prompts = {"raw": run.prompts_json}

        raw_json = None
        if run.raw_json:
            try:
                raw_json = json.loads(run.raw_json)
            except Exception:
                raw_json = {"raw": run.raw_json}

        runs_data.append(
            {
                "id": run.id,
                "paper_id": run.paper_id,
                "parent_run_id": run.parent_run_id,
                "status": run.status,
                "failure_reason": run.failure_reason,
                "prompts": prompts,
                "raw_json": raw_json,
                "comment": run.comment,
                "model_provider": run.model_provider,
                "model_name": run.model_name,
                "pdf_url": run.pdf_url,
                "entity_count": entity_counts.get(run.id, 0),
                "created_at": run.created_at.isoformat() + "Z" if run.created_at else None,
            }
        )

    latest_status = runs[0].status if runs else None

    return {
        "paper": {
            "id": paper.id,
            "title": paper.title,
            "doi": paper.doi,
            "url": paper.url,
            "source": paper.source,
            "year": paper.year,
            "authors": authors,
            "status": latest_status,
        },
        "runs": runs_data,
    }


@router.get("/api/runs/recent")
async def list_recent_runs(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(ExtractionRun).order_by(ExtractionRun.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(ExtractionRun.status == status)
    runs = session.exec(stmt).all()
    results = []
    for run in runs:
        paper = session.get(Paper, run.paper_id) if run.paper_id else None
        results.append(
            {
                "id": run.id,
                "paper_id": run.paper_id,
                "status": run.status,
                "failure_reason": run.failure_reason,
                "model_provider": run.model_provider,
                "model_name": run.model_name,
                "created_at": run.created_at.isoformat() + "Z" if run.created_at else None,
                "paper": {
                    "id": paper.id if paper else None,
                    "title": paper.title if paper else None,
                    "doi": paper.doi if paper else None,
                    "url": paper.url if paper else None,
                    "source": paper.source if paper else None,
                    "year": paper.year if paper else None,
                },
            }
        )
    return {"runs": results}


@router.get("/api/runs/failure-summary", response_model=FailureSummaryResponse)
async def get_failure_summary(
    days: int = Query(default=30, ge=1, le=365),
    max_runs: int = Query(default=1000, ge=50, le=10000),
    session: Session = Depends(get_session),
) -> FailureSummaryResponse:
    cutoff = utc_now() - timedelta(days=days)
    stmt = (
        select(ExtractionRun, Paper)
        .join(Paper, ExtractionRun.paper_id == Paper.id, isouter=True)
        .where(ExtractionRun.status == RunStatus.FAILED.value)
        .where(ExtractionRun.created_at >= cutoff)
        .order_by(ExtractionRun.created_at.desc())
        .limit(max_runs)
    )
    rows = session.exec(stmt).all()
    bucket_counts: dict = {}
    provider_counts: dict = {}
    source_counts: dict = {}
    reason_counts: dict = {}

    def _bump(target: dict, key: str, label: Optional[str], run: ExtractionRun, paper: Optional[Paper]) -> None:
        entry = target.get(key)
        if not entry:
            entry = {
                "key": key,
                "label": label or key,
                "count": 0,
                "example_run_id": None,
                "example_paper_id": None,
                "example_title": None,
            }
            target[key] = entry
        entry["count"] += 1
        if entry["example_run_id"] is None:
            entry["example_run_id"] = run.id
            entry["example_paper_id"] = run.paper_id
            entry["example_title"] = paper.title if paper else None

    for run, paper in rows:
        bucket_key = bucket_failure_reason(run.failure_reason)
        _bump(bucket_counts, bucket_key, FAILURE_BUCKET_LABELS.get(bucket_key, bucket_key), run, paper)
        provider_key = run.model_provider or "unknown"
        _bump(provider_counts, provider_key, provider_key, run, paper)
        source_key = paper.source if paper and paper.source else "unknown"
        _bump(source_counts, source_key, source_key, run, paper)
        reason_key = normalize_failure_reason(run.failure_reason)
        _bump(reason_counts, reason_key, reason_key, run, paper)

    def _sorted(values: dict) -> list:
        return sorted(values.values(), key=lambda item: item["count"], reverse=True)

    window_start = cutoff.isoformat() + "Z"
    return FailureSummaryResponse(
        total_failed=len(rows),
        runs_analyzed=len(rows),
        window_days=days,
        window_start=window_start,
        buckets=_sorted(bucket_counts),
        providers=_sorted(provider_counts),
        sources=_sorted(source_counts),
        reasons=_sorted(reason_counts),
    )


@router.get("/api/runs/failures", response_model=FailedRunsResponse)
async def list_failed_runs(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=25, ge=1, le=200),
    max_runs: int = Query(default=1000, ge=50, le=10000),
    bucket: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    reason: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
) -> FailedRunsResponse:
    payload = list_failed_runs_payload(
        session=session,
        days=days,
        limit=limit,
        max_runs=max_runs,
        bucket=bucket,
        provider=provider,
        source=source,
        reason=reason,
    )
    return FailedRunsResponse(**payload)


@router.post("/api/runs/failures/retry", response_model=BulkRetryResponse)
async def retry_failed_runs(
    req: BulkRetryRequest,
    session: Session = Depends(get_session),
) -> BulkRetryResponse:
    queue = get_queue()
    return await retry_failed_runs_service(
        session=session,
        req=req,
        queue=queue,
        default_provider=settings.LLM_PROVIDER,
    )


@router.get("/api/runs/{run_id}")
async def get_run(run_id: int, session: Session = Depends(get_session)) -> dict:
    run = session.get(ExtractionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    paper = session.get(Paper, run.paper_id) if run.paper_id else None
    return build_run_payload(run, paper)


@router.post("/api/runs/{run_id}/followup", response_model=ExtractResponse)
async def followup_run(
    run_id: int,
    req: FollowupRequest,
    session: Session = Depends(get_session),
) -> ExtractResponse:
    try:
        new_run_id, paper_id, payload = await run_followup(
            session=session,
            parent_run_id=run_id,
            instruction=req.instruction,
            provider_name=req.provider,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ExtractResponse(extraction=payload, extraction_id=new_run_id, paper_id=paper_id)


@router.post("/api/runs/{run_id}/followup-stream")
async def followup_run_stream(
    run_id: int,
    req: FollowupRequest,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    async def event_generator():
        async for event in run_followup_stream(
            session=session,
            parent_run_id=run_id,
            instruction=req.instruction,
            provider_name=req.provider,
        ):
            payload = json.dumps(event.get("data", {}))
            yield f"event: {event.get('event', 'message')}\n"
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/runs/{run_id}/edit", response_model=ExtractResponse)
async def edit_run(
    run_id: int,
    req: EditRunRequest,
    session: Session = Depends(get_session),
) -> ExtractResponse:
    try:
        new_run_id, paper_id, payload = run_edit(
            session=session,
            parent_run_id=run_id,
            payload=req.payload,
            reason=req.reason,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ExtractResponse(extraction=payload, extraction_id=new_run_id, paper_id=paper_id)


@router.get("/api/runs/{run_id}/history")
async def get_run_history(run_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        return run_history_payload(session=session, run_id=run_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/runs/{run_id}/retry")
async def retry_run(
    run_id: int,
    session: Session = Depends(get_session),
) -> dict:
    queue = get_queue()
    try:
        return await retry_run_service(
            session=session,
            run_id=run_id,
            queue=queue,
            default_provider=settings.LLM_PROVIDER,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/runs/{run_id}/resolve-source", response_model=ResolvedSourceResponse)
async def resolve_run_source(
    run_id: int,
    session: Session = Depends(get_session),
) -> ResolvedSourceResponse:
    run = session.get(ExtractionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    paper = session.get(Paper, run.paper_id) if run.paper_id else None
    if run.pdf_url and DocumentExtractor.looks_like_pdf_url(run.pdf_url):
        return ResolvedSourceResponse(
            found=True,
            title=paper.title if paper else None,
            doi=paper.doi if paper else None,
            url=paper.url if paper else None,
            pdf_url=run.pdf_url,
            source=paper.source if paper else None,
            year=paper.year if paper else None,
            authors=json.loads(paper.authors_json) if paper and paper.authors_json else [],
        )
    query = (paper.doi if paper else None) or (paper.url if paper else None)
    if not query:
        return ResolvedSourceResponse(found=False)
    results = await search_all_free_sources(query, per_source=3)
    source = select_baseline_result(results, paper.doi if paper else None)
    if not source:
        if paper and paper.url:
            return ResolvedSourceResponse(
                found=True,
                title=paper.title,
                doi=paper.doi,
                url=paper.url,
                pdf_url=run.pdf_url if run.pdf_url and DocumentExtractor.looks_like_pdf_url(run.pdf_url) else None,
                source=paper.source,
                year=paper.year,
                authors=json.loads(paper.authors_json) if paper.authors_json else [],
            )
        return ResolvedSourceResponse(found=False)
    return ResolvedSourceResponse(
        found=True,
        title=source.title,
        doi=source.doi,
        url=source.url,
        pdf_url=source.pdf_url,
        source=source.source,
        year=source.year,
        authors=source.authors or [],
    )


@router.post("/api/runs/{run_id}/retry-with-source")
async def retry_run_with_source(
    run_id: int,
    req: RunRetryWithSourceRequest,
    session: Session = Depends(get_session),
) -> dict:
    queue = get_queue()
    try:
        return await retry_run_with_source_service(
            session=session,
            run_id=run_id,
            source_url=req.source_url,
            provider=req.provider,
            prompt_id=req.prompt_id,
            queue=queue,
            default_provider=settings.LLM_PROVIDER,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/runs/{run_id}/upload", response_model=ExtractResponse)
async def upload_run_file(
    run_id: int,
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    provider: Optional[str] = Form(None),
    prompt_id: Optional[int] = Form(None),
    session: Session = Depends(get_session),
) -> ExtractResponse:
    run = session.get(ExtractionRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    paper = session.get(Paper, run.paper_id) if run.paper_id else None
    upload_files = files or ([file] if file else [])
    if not upload_files:
        raise HTTPException(status_code=400, detail="No files provided")

    file_payloads: List[tuple[bytes, str]] = []
    total_size = 0
    for upload in upload_files:
        if not upload or not upload.filename:
            raise HTTPException(status_code=400, detail="No file provided")
        if not upload.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        content = await upload.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty file")
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large (max 20MB)")
        total_size += len(content)
        if total_size > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Total upload too large (max 50MB)")
        file_payloads.append((content, upload.filename))

    use_prompt_id = prompt_id or run.prompt_id
    use_provider = provider or run.model_provider or settings.LLM_PROVIDER
    first_filename = file_payloads[0][1]
    if paper and paper.title:
        title = paper.title
    elif len(file_payloads) == 1:
        title = first_filename.rsplit(".", 1)[0]
    else:
        base_title = first_filename.rsplit(".", 1)[0]
        title = f"{base_title} (+{len(file_payloads) - 1} more)"
    try:
        extraction_id, paper_id, payload = await run_extraction_from_files(
            session=session,
            files=file_payloads,
            title=title,
            prompt_id=use_prompt_id,
            provider_name=use_provider,
            baseline_case_id=run.baseline_case_id,
            baseline_dataset=run.baseline_dataset,
            parent_run_id=run.id,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    linked_cases = BaselineCaseRunRepository(session).list_case_ids_for_run(run.id)
    if not linked_cases and run.baseline_case_id:
        linked_cases = [run.baseline_case_id]
    link_cases_to_run(session, linked_cases, extraction_id)

    return ExtractResponse(extraction=payload, extraction_id=extraction_id, paper_id=paper_id)
