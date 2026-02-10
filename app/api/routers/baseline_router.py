from __future__ import annotations

import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, update
from sqlmodel import Session, select

from ...baseline.loader import get_case, list_cases, resolve_all_local_pdf_paths, resolve_local_pdf_path
from ...config import settings
from ...db import get_session
from ...persistence.models import (
    BaselineCaseRun,
    BatchRun,
    BatchStatus,
    ActiveSourceLock,
    ExtractionEntity,
    ExtractionRun,
    Paper,
    QueueJob,
    QueueJobStatus,
    RunStatus,
)
from ...persistence.repository import ExtractionRepository, PaperRepository
from ...schemas import (
    BaselineCase,
    BaselineCaseSummary,
    BaselineCasesResponse,
    BaselineEnqueueRequest,
    BaselineEnqueueResponse,
    BaselineEnqueuedRun,
    BaselineRetryRequest,
    BaselineShadowSeedRequest,
    BaselineShadowSeedResponse,
    BatchEnqueueRequest,
    BatchEnqueueResponse,
    BatchInfo,
    BatchListResponse,
    BatchRetryRequest,
    BatchRetryResponse,
    DeleteBatchResponse,
    ExtractionPayload,
    LocalPdfInfoResponse,
    LocalPdfSiInfoResponse,
    PaperMeta,
    ResolvedSourceResponse,
    RetryResponse,
    RunPayloadResponse,
)
from ...services.baseline_helpers import (
    baseline_dataset_infos,
    baseline_title,
    build_baseline_run_summary,
    get_latest_baseline_run,
    get_latest_baseline_runs,
    get_latest_run_for_cases,
    get_source_key,
    get_source_keys,
    link_cases_to_run,
    load_shadow_entries,
    resolve_baseline_source,
)
from ...services.baseline_retry_service import retry_baseline_case as retry_baseline_case_service
from ...services.baseline_retry_service import retry_batch_runs
from ...services.batch_metrics import (
    compute_batch_cost,
    compute_match_rate,
    compute_wall_clock_time_ms,
    generate_batch_id,
    get_model_name_for_provider,
)
from ...services.queue_coordinator import QueueCoordinator
from ...services.queue_service import get_queue
from ...services.serializers import iso_z
from ...services.upload_store import store_upload
from ...services.view_builders import build_run_payload
from ...services.runs_retry_service import ServiceError
from ...time_utils import utc_now

router = APIRouter(tags=["baseline"])

PROCESSING_STATUSES = {
    RunStatus.QUEUED.value,
    RunStatus.FETCHING.value,
    RunStatus.PROVIDER.value,
    RunStatus.VALIDATING.value,
}


@router.get("/api/baseline/cases", response_model=BaselineCasesResponse)
async def list_baseline_cases(
    dataset: Optional[str] = Query(None),
    session: Session = Depends(get_session),
) -> BaselineCasesResponse:
    cases_raw = list_cases(dataset)
    datasets = baseline_dataset_infos(dataset)
    case_ids = [case.get("id") for case in cases_raw if case.get("id")]
    latest_by_case = get_latest_baseline_runs(session, case_ids)

    cases: List[BaselineCaseSummary] = []
    for case_data in cases_raw:
        case = BaselineCase(**case_data)
        cases.append(
            BaselineCaseSummary(
                **case.model_dump(),
                latest_run=latest_by_case.get(case.id),
            )
        )

    return BaselineCasesResponse(
        cases=cases,
        datasets=datasets,
        total_cases=len(cases_raw),
    )


@router.get("/api/baseline/cases/{case_id}", response_model=BaselineCaseSummary)
async def get_baseline_case(
    case_id: str,
    session: Session = Depends(get_session),
) -> BaselineCaseSummary:
    case_data = get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Baseline case not found")
    run = get_latest_baseline_run(session, case_id)
    case = BaselineCase(**case_data)
    return BaselineCaseSummary(
        **case.model_dump(),
        latest_run=build_baseline_run_summary(run) if run else None,
    )


@router.get("/api/baseline/cases/{case_id}/latest-run", response_model=RunPayloadResponse)
async def get_baseline_latest_run(
    case_id: str,
    session: Session = Depends(get_session),
) -> RunPayloadResponse:
    run = get_latest_baseline_run(session, case_id)
    if not run:
        raise HTTPException(status_code=404, detail="No runs for baseline case")
    paper = session.get(Paper, run.paper_id) if run.paper_id else None
    return RunPayloadResponse(**build_run_payload(run, paper))


@router.post("/api/baseline/cases/{case_id}/resolve-source", response_model=ResolvedSourceResponse)
async def resolve_baseline_case_source(
    case_id: str,
    local_only: bool = Query(False),
) -> ResolvedSourceResponse:
    case_data = get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Baseline case not found")
    case = BaselineCase(**case_data)
    source = await resolve_baseline_source(case, local_only=local_only)
    if not source:
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


@router.get("/api/baseline/cases/{case_id}/local-pdf-info", response_model=LocalPdfInfoResponse)
async def get_baseline_case_local_pdf_info(case_id: str) -> LocalPdfInfoResponse:
    case_data = get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Baseline case not found")
    case = BaselineCase(**case_data)
    local_path = resolve_local_pdf_path(case.doi)
    if not local_path or not local_path.exists():
        return LocalPdfInfoResponse(found=False)
    return LocalPdfInfoResponse(found=True, filename=local_path.name)


@router.get("/api/baseline/cases/{case_id}/local-pdf")
async def get_baseline_case_local_pdf(case_id: str) -> FileResponse:
    case_data = get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Baseline case not found")
    case = BaselineCase(**case_data)
    local_path = resolve_local_pdf_path(case.doi)
    if not local_path or not local_path.exists():
        raise HTTPException(status_code=404, detail="Local PDF not found for baseline case")
    return FileResponse(
        local_path,
        media_type="application/pdf",
        filename=local_path.name,
        headers={"Content-Disposition": f'inline; filename="{local_path.name}"'},
    )


@router.get("/api/baseline/cases/{case_id}/local-pdf-si-info", response_model=LocalPdfSiInfoResponse)
async def get_baseline_case_local_pdf_si_info(case_id: str) -> LocalPdfSiInfoResponse:
    """Get info about supplementary PDF availability for a baseline case."""
    case_data = get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Baseline case not found")
    case = BaselineCase(**case_data)
    all_paths = resolve_all_local_pdf_paths(case.doi)
    main_path = resolve_local_pdf_path(case.doi)
    si_paths = [p for p in all_paths if p != main_path]
    if not si_paths:
        return LocalPdfSiInfoResponse(found=False, filenames=[], count=0)
    return LocalPdfSiInfoResponse(
        found=True,
        filenames=[p.name for p in si_paths],
        count=len(si_paths),
    )


@router.get("/api/baseline/cases/{case_id}/local-pdf-si")
async def get_baseline_case_local_pdf_si(case_id: str, index: int = 0) -> FileResponse:
    """Serve SI PDF by index (default 0 for first SI)."""
    case_data = get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Baseline case not found")
    case = BaselineCase(**case_data)
    all_paths = resolve_all_local_pdf_paths(case.doi)
    main_path = resolve_local_pdf_path(case.doi)
    si_paths = [p for p in all_paths if p != main_path]
    if not si_paths:
        raise HTTPException(status_code=404, detail="No SI PDFs found for baseline case")
    if index < 0 or index >= len(si_paths):
        raise HTTPException(status_code=404, detail=f"SI PDF index {index} out of range (0-{len(si_paths)-1})")
    local_path = si_paths[index]
    return FileResponse(
        local_path,
        media_type="application/pdf",
        filename=local_path.name,
        headers={"Content-Disposition": f'inline; filename="{local_path.name}"'},
    )


@router.post("/api/baseline/cases/{case_id}/retry", response_model=RetryResponse)
async def retry_baseline_case(
    case_id: str,
    req: BaselineRetryRequest,
    session: Session = Depends(get_session),
) -> RetryResponse:
    queue = get_queue()
    try:
        payload = await retry_baseline_case_service(
            session=session,
            case_id=case_id,
            req=req,
            queue=queue,
            default_provider=settings.LLM_PROVIDER,
        )
        return RetryResponse(**payload)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/baseline/cases/{case_id}/upload", response_model=RetryResponse)
async def upload_baseline_case(
    case_id: str,
    file: UploadFile = File(...),
    provider: Optional[str] = Form(None),
    prompt_id: Optional[int] = Form(None),
    session: Session = Depends(get_session),
) -> RetryResponse:
    coordinator = QueueCoordinator()
    case_data = get_case(case_id)
    if not case_data:
        raise HTTPException(status_code=404, detail="Baseline case not found")
    case = BaselineCase(**case_data)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    upload_url = store_upload(content, file.filename)
    case_ids = [case.id]
    source_keys = get_source_keys(case, None)
    if source_keys:
        for other_data in list_cases():
            other = BaselineCase(**other_data)
            other_keys = get_source_keys(other, None)
            if any(key in source_keys for key in other_keys):
                case_ids.append(other.id)
    case_ids = sorted(set(case_ids))

    meta = PaperMeta(
        title=baseline_title(case),
        doi=case.doi,
        url=case.paper_url,
        source="upload",
    )
    paper_repo = PaperRepository(session)
    paper_id = paper_repo.upsert(meta)

    use_provider = provider or settings.LLM_PROVIDER
    run = ExtractionRun(
        paper_id=paper_id,
        status=RunStatus.QUEUED.value,
        model_provider=use_provider,
        pdf_url=upload_url,
        prompt_id=prompt_id,
    )
    result = coordinator.enqueue_new_run(
        session,
        run=run,
        title=meta.title or baseline_title(case),
        pdf_urls=None,
    )
    if not result.enqueued:
        return RetryResponse(
            id=result.conflict_run_id,
            status=result.conflict_run_status or RunStatus.QUEUED.value,
            message="Upload source already queued",
        )
    link_cases_to_run(session, case_ids, result.run_id)

    return RetryResponse(
        id=result.run_id,
        status=result.run_status,
        message="Upload accepted and queued for processing",
    )


@router.post("/api/baseline/enqueue", response_model=BaselineEnqueueResponse)
async def enqueue_baseline(
    req: BaselineEnqueueRequest,
    session: Session = Depends(get_session),
) -> BaselineEnqueueResponse:
    queue = get_queue()
    coordinator = QueueCoordinator()
    paper_repo = PaperRepository(session)
    cases_raw = list_cases(req.dataset)
    cases = [BaselineCase(**case_data) for case_data in cases_raw]

    runs: List[BaselineEnqueuedRun] = []
    enqueued = 0
    skipped = 0

    entries: List[dict] = []
    local_upload_cache: Dict[str, str] = {}
    for case in cases:
        source = await resolve_baseline_source(case, local_upload_cache)
        resolved_url = source.pdf_url if source and source.pdf_url else (source.url if source else None)
        source_key = get_source_key(case, resolved_url)
        entries.append(
            {
                "case": case,
                "source": source,
                "resolved_url": resolved_url,
                "source_key": source_key,
            }
        )

    grouped: dict[str, List[dict]] = {}
    for entry in entries:
        group_key = entry["source_key"] or f"case:{entry['case'].id}"
        grouped.setdefault(group_key, []).append(entry)

    for group_entries in grouped.values():
        case_ids = [entry["case"].id for entry in group_entries]
        resolved_url = next((entry["resolved_url"] for entry in group_entries if entry["resolved_url"]), None)
        source = next((entry["source"] for entry in group_entries if entry["source"]), None)
        case = group_entries[0]["case"]

        existing = None
        if resolved_url:
            stmt = (
                select(ExtractionRun)
                .where(ExtractionRun.pdf_url == resolved_url)
                .order_by(ExtractionRun.created_at.desc())
                .limit(1)
            )
            existing = session.exec(stmt).first()
        if not existing:
            existing = get_latest_run_for_cases(session, case_ids)

        if resolved_url and await queue.is_url_pending(resolved_url):
            if existing:
                link_cases_to_run(session, case_ids, existing.id)
            for case_id in case_ids:
                runs.append(
                    BaselineEnqueuedRun(
                        baseline_case_id=case_id,
                        run_id=existing.id if existing else None,
                        status=existing.status if existing else None,
                        skipped=True,
                        skip_reason="Already queued",
                    )
                )
            skipped += len(case_ids)
            continue

        if existing:
            if existing.status in PROCESSING_STATUSES:
                link_cases_to_run(session, case_ids, existing.id)
                skip_reason = "Already queued" if existing.status == RunStatus.QUEUED.value else "Already in progress"
                for case_id in case_ids:
                    runs.append(
                        BaselineEnqueuedRun(
                            baseline_case_id=case_id,
                            run_id=existing.id,
                            status=existing.status,
                            skipped=True,
                            skip_reason=skip_reason,
                        )
                    )
                skipped += len(case_ids)
                continue
            if existing.status == RunStatus.STORED.value and not req.force:
                link_cases_to_run(session, case_ids, existing.id)
                for case_id in case_ids:
                    runs.append(
                        BaselineEnqueuedRun(
                            baseline_case_id=case_id,
                            run_id=existing.id,
                            status=existing.status,
                            skipped=True,
                            skip_reason="Already stored",
                        )
                    )
                skipped += len(case_ids)
                continue

        if not resolved_url:
            meta = PaperMeta(
                title=baseline_title(case),
                doi=case.doi,
                url=case.paper_url,
                source="baseline",
                year=None,
                authors=[],
            )
            paper_id = paper_repo.upsert(meta)
            run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="No source URL resolved for baseline case",
                raw_json=json.dumps({"error": "No source URL resolved for baseline case"}),
                model_provider=req.provider,
                pdf_url=resolved_url,
                prompt_id=req.prompt_id,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            link_cases_to_run(session, case_ids, run.id)
            for case_id in case_ids:
                runs.append(
                    BaselineEnqueuedRun(
                        baseline_case_id=case_id,
                        run_id=run.id,
                        status=run.status,
                        skipped=False,
                    )
                )
            continue

        meta = PaperMeta(
            title=(source.title if source else None) or baseline_title(case),
            doi=(source.doi if source else None) or case.doi,
            url=(source.url if source else None) or case.paper_url,
            source=source.source if source else "baseline",
            year=source.year if source else None,
            authors=source.authors if source and source.authors else [],
        )
        paper_id = paper_repo.upsert(meta)
        run = ExtractionRun(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider=req.provider,
            pdf_url=resolved_url,
            prompt_id=req.prompt_id,
        )
        result = coordinator.enqueue_new_run(
            session,
            run=run,
            title=meta.title or baseline_title(case),
            pdf_urls=source.pdf_urls if source and source.pdf_urls else None,
        )
        if not result.enqueued:
            conflict_id = result.conflict_run_id or (existing.id if existing else None)
            conflict_status = result.conflict_run_status or (
                existing.status if existing else RunStatus.QUEUED.value
            )
            if conflict_id:
                link_cases_to_run(session, case_ids, conflict_id)
            for case_id in case_ids:
                runs.append(
                    BaselineEnqueuedRun(
                        baseline_case_id=case_id,
                        run_id=conflict_id,
                        status=conflict_status,
                        skipped=True,
                        skip_reason="Already queued",
                    )
                )
            skipped += len(case_ids)
            continue
        link_cases_to_run(session, case_ids, result.run_id)
        enqueued += len(case_ids)

        for case_id in case_ids:
            runs.append(
                BaselineEnqueuedRun(
                    baseline_case_id=case_id,
                    run_id=result.run_id,
                    status=result.run_status,
                    skipped=False,
                )
            )

    return BaselineEnqueueResponse(
        runs=runs,
        total=len(cases_raw),
        enqueued=enqueued,
        skipped=skipped,
    )


@router.post("/api/baseline/shadow-seed", response_model=BaselineShadowSeedResponse)
async def seed_shadow_baseline(
    req: BaselineShadowSeedRequest,
    session: Session = Depends(get_session),
) -> BaselineShadowSeedResponse:
    if settings.ENV != "development":
        raise HTTPException(status_code=403, detail="Shadow seeding is only available in development.")

    entries = load_shadow_entries(req.dataset)
    total = len(entries)
    if total == 0:
        return BaselineShadowSeedResponse(total=0, seeded=0, skipped=0)

    seeded = 0
    skipped = 0
    paper_repo = PaperRepository(session)
    extraction_repo = ExtractionRepository(session)

    for entry in entries:
        if req.limit is not None and seeded >= req.limit:
            break
        case_id = entry.get("case_id")
        dataset = entry.get("dataset")
        if not case_id:
            continue

        if not req.force:
            stmt = (
                select(BaselineCaseRun)
                .where(BaselineCaseRun.baseline_case_id == case_id)
                .limit(1)
            )
            existing_link = session.exec(stmt).first()
            if existing_link:
                skipped += 1
                continue
            stmt = (
                select(ExtractionRun)
                .where(ExtractionRun.baseline_case_id == case_id)
                .limit(1)
            )
            existing = session.exec(stmt).first()
            if existing:
                skipped += 1
                continue

        payload = ExtractionPayload.model_validate(entry.get("payload", {}))
        paper_id = paper_repo.upsert(payload.paper)
        run_id, _entity_ids = extraction_repo.save_extraction(
            payload=payload,
            paper_id=paper_id,
            provider_name="shadow",
            model_name="shadow-data",
            status=RunStatus.STORED.value,
            baseline_case_id=case_id,
            baseline_dataset=dataset,
        )
        link_cases_to_run(session, [case_id], run_id)
        seeded += 1

    return BaselineShadowSeedResponse(
        total=total,
        seeded=seeded,
        skipped=skipped,
    )


@router.get("/api/baseline/batches", response_model=BatchListResponse)
async def list_batches(
    dataset: Optional[str] = None,
    session: Session = Depends(get_session),
) -> BatchListResponse:
    """List all batch runs, optionally filtered by dataset."""
    stmt = select(BatchRun).order_by(BatchRun.created_at.desc())
    if dataset:
        stmt = stmt.where(BatchRun.dataset == dataset)
    batches = session.exec(stmt).all()
    return BatchListResponse(
        batches=[
            BatchInfo(
                id=b.id,
                batch_id=b.batch_id,
                label=b.label,
                dataset=b.dataset,
                model_provider=b.model_provider,
                model_name=b.model_name,
                status=b.status,
                total_papers=b.total_papers,
                completed=b.completed,
                failed=b.failed,
                total_input_tokens=b.total_input_tokens,
                total_output_tokens=b.total_output_tokens,
                total_time_ms=compute_wall_clock_time_ms(b),
                matched_entities=b.matched_entities,
                total_expected_entities=b.total_expected_entities,
                match_rate=compute_match_rate(b),
                estimated_cost_usd=compute_batch_cost(b),
                created_at=iso_z(b.created_at) or "",
            )
            for b in batches
        ]
    )


@router.post("/api/baseline/batch-enqueue", response_model=BatchEnqueueResponse)
async def batch_enqueue(
    req: BatchEnqueueRequest,
    session: Session = Depends(get_session),
) -> BatchEnqueueResponse:
    """Create a batch and enqueue all papers from a dataset."""
    coordinator = QueueCoordinator()
    paper_repo = PaperRepository(session)

    model_name = get_model_name_for_provider(req.provider)
    batch_id = generate_batch_id(model_name)

    batch = BatchRun(
        batch_id=batch_id,
        label=req.label,
        dataset=req.dataset,
        model_provider=req.provider,
        model_name=model_name,
        status=BatchStatus.RUNNING.value,
        total_papers=0,
        completed=0,
        failed=0,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)

    cases_raw = list_cases(req.dataset)
    cases = [BaselineCase(**case_data) for case_data in cases_raw]

    runs_enqueued = 0
    cases_enqueued = 0
    local_upload_cache: Dict[str, str] = {}

    entries: List[dict] = []
    for case in cases:
        source = await resolve_baseline_source(case, local_upload_cache)
        resolved_url = source.pdf_url if source and source.pdf_url else (source.url if source else None)
        source_key = get_source_key(case, resolved_url)
        entries.append(
            {
                "case": case,
                "source": source,
                "resolved_url": resolved_url,
                "source_key": source_key,
            }
        )

    grouped: dict[str, List[dict]] = {}
    for entry in entries:
        group_key = entry["source_key"] or f"case:{entry['case'].id}"
        grouped.setdefault(group_key, []).append(entry)

    for group_entries in grouped.values():
        case_ids = [entry["case"].id for entry in group_entries]
        resolved_url = next((entry["resolved_url"] for entry in group_entries if entry["resolved_url"]), None)
        source = next((entry["source"] for entry in group_entries if entry["source"]), None)
        case = group_entries[0]["case"]

        if not resolved_url:
            continue

        meta = PaperMeta(
            title=(source.title if source else None) or baseline_title(case),
            doi=(source.doi if source else None) or case.doi,
            url=(source.url if source else None) or case.paper_url,
            source=source.source if source else "baseline",
            year=source.year if source else None,
            authors=source.authors if source and source.authors else [],
        )
        paper_id = paper_repo.upsert(meta)
        run = ExtractionRun(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider=req.provider,
            pdf_url=resolved_url,
            prompt_id=req.prompt_id,
            batch_id=batch_id,
        )
        all_pdf_urls = source.pdf_urls if source and source.pdf_urls else None
        result = coordinator.enqueue_new_run(
            session,
            run=run,
            title=meta.title or baseline_title(case),
            pdf_urls=all_pdf_urls,
        )
        if not result.enqueued:
            continue
        link_cases_to_run(session, case_ids, result.run_id)
        runs_enqueued += 1
        cases_enqueued += len(case_ids)

    batch.total_papers = runs_enqueued
    session.add(batch)
    session.commit()

    return BatchEnqueueResponse(
        batch_id=batch_id,
        total_papers=len(cases_raw),
        enqueued=runs_enqueued,
        skipped=len(cases_raw) - cases_enqueued,
    )


@router.post("/api/baseline/batch-retry", response_model=BatchRetryResponse)
async def batch_retry(
    req: BatchRetryRequest,
    session: Session = Depends(get_session),
) -> BatchRetryResponse:
    queue = get_queue()
    try:
        return await retry_batch_runs(
            session=session,
            batch_id=req.batch_id,
            provider=req.provider,
            queue=queue,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/baseline/batch/{batch_id}", response_model=BatchInfo)
async def get_batch(
    batch_id: str,
    session: Session = Depends(get_session),
) -> BatchInfo:
    """Get details of a specific batch."""
    stmt = select(BatchRun).where(BatchRun.batch_id == batch_id)
    batch = session.exec(stmt).first()
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")
    return BatchInfo(
        id=batch.id,
        batch_id=batch.batch_id,
        label=batch.label,
        dataset=batch.dataset,
        model_provider=batch.model_provider,
        model_name=batch.model_name,
        status=batch.status,
        total_papers=batch.total_papers,
        completed=batch.completed,
        failed=batch.failed,
        total_input_tokens=batch.total_input_tokens,
        total_output_tokens=batch.total_output_tokens,
        total_time_ms=compute_wall_clock_time_ms(batch),
        matched_entities=batch.matched_entities,
        total_expected_entities=batch.total_expected_entities,
        match_rate=compute_match_rate(batch),
        estimated_cost_usd=compute_batch_cost(batch),
        created_at=iso_z(batch.created_at) or "",
    )


@router.delete("/api/baseline/batch/{batch_id}", response_model=DeleteBatchResponse)
async def delete_batch(
    batch_id: str,
    session: Session = Depends(get_session),
) -> DeleteBatchResponse:
    """Delete a batch and all its associated runs."""
    stmt = select(BatchRun).where(BatchRun.batch_id == batch_id)
    batch = session.exec(stmt).first()
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")

    stmt = select(ExtractionRun).where(ExtractionRun.batch_id == batch_id)
    runs = session.exec(stmt).all()
    run_ids = [r.id for r in runs]

    if run_ids:
        now = utc_now()
        session.exec(
            update(QueueJob)
            .where(QueueJob.run_id.in_(run_ids))
            .where(QueueJob.status.in_([QueueJobStatus.QUEUED.value, QueueJobStatus.CLAIMED.value]))
            .values(
                status=QueueJobStatus.CANCELLED.value,
                claimed_by=None,
                claim_token=None,
                claimed_at=None,
                finished_at=now,
                updated_at=now,
            )
        )
        session.exec(delete(ActiveSourceLock).where(ActiveSourceLock.run_id.in_(run_ids)))
        session.exec(delete(QueueJob).where(QueueJob.run_id.in_(run_ids)))
        session.exec(delete(BaselineCaseRun).where(BaselineCaseRun.run_id.in_(run_ids)))
        session.exec(delete(ExtractionEntity).where(ExtractionEntity.run_id.in_(run_ids)))

    for run in runs:
        session.delete(run)

    session.delete(batch)
    session.commit()

    return DeleteBatchResponse(status="ok", deleted_runs=len(runs))
