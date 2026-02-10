from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, update
from sqlmodel import Session, select

from ...baseline.loader import (
    get_case,
    is_local_pdf_unverified,
    list_cases,
    load_backup_dataset,
    load_backup_index,
    resolve_all_local_pdf_paths,
    resolve_local_pdf_path,
)
from ...config import settings
from ...db import get_session
from ...integrations.llm import ProviderSelectionError, resolve_provider_selection
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
    BaselineCaseCreateRequest,
    BaselineCaseDeleteRequest,
    BaselineCaseSummary,
    BaselineCasesResponse,
    BaselineEnqueueRequest,
    BaselineEnqueueResponse,
    BaselineEnqueuedRun,
    BaselineDeleteResponse,
    BaselineRecomputeStatusResponse,
    BaselineResetResponse,
    BaselineRetryRequest,
    BaselineShadowSeedRequest,
    BaselineShadowSeedResponse,
    BaselineCaseUpdateRequest,
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
    get_case_paper_key,
    get_latest_baseline_run,
    get_latest_baseline_runs,
    get_latest_run_for_cases,
    get_source_key,
    get_source_keys,
    link_cases_to_run,
    load_shadow_entries,
    resolve_baseline_source,
)
from ...services.baseline_recompute_service import (
    get_recompute_status,
    mark_batches_stale_and_trigger,
    recompute_batches_now,
)
from ...services.baseline_retry_service import retry_baseline_case as retry_baseline_case_service
from ...services.baseline_retry_service import retry_batch_runs
from ...services.baseline_store import (
    BaselineConflictError,
    BaselineNotFoundError,
    BaselineStore,
    BaselineValidationError,
)
from ...services.batch_metrics import (
    compute_batch_cost,
    compute_match_rate,
    compute_wall_clock_time_ms,
    generate_batch_id,
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


def _normalize_sequence(seq: Optional[str]) -> str:
    if not seq:
        return ""
    return re.sub(r"[^A-Za-z]", "", str(seq)).upper()


def _extract_sequences(raw_json: Optional[str]) -> set[str]:
    values: set[str] = set()
    if not raw_json:
        return values
    try:
        payload = json.loads(raw_json)
    except Exception:
        return values

    entities = payload.get("entities", []) if isinstance(payload, dict) else []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        peptide = entity.get("peptide") or {}
        seq = peptide.get("sequence_one_letter", "") if isinstance(peptide, dict) else ""
        normalized = _normalize_sequence(seq)
        if normalized:
            values.add(normalized)
    return values


def _compute_papers_all_matched_by_batch(
    session: Session,
    batches: List[BatchRun],
) -> Dict[str, int]:
    results = {
        batch.batch_id: 0
        for batch in batches
        if batch.batch_id
    }
    if not results:
        return results

    store = BaselineStore(session)
    datasets = sorted({batch.dataset for batch in batches if batch.dataset})
    dataset_groups: Dict[str, Dict[str, Dict[str, str]]] = {}
    dataset_case_to_paper: Dict[str, Dict[str, str]] = {}

    for dataset in datasets:
        groups: Dict[str, Dict[str, str]] = {}
        case_to_paper: Dict[str, str] = {}
        for case in store.list_cases(dataset):
            case_id = case.get("id")
            if not case_id:
                continue
            paper_key = case.get("paper_key") or f"case:{case_id}"
            case_to_paper[case_id] = paper_key
            sequence = _normalize_sequence(case.get("sequence"))
            if not sequence:
                continue
            groups.setdefault(paper_key, {})[case_id] = sequence
        dataset_groups[dataset] = groups
        dataset_case_to_paper[dataset] = case_to_paper

    if not any(dataset_groups.values()):
        return results

    batch_dataset = {
        batch.batch_id: batch.dataset
        for batch in batches
        if batch.batch_id and batch.dataset
    }

    runs = session.exec(
        select(ExtractionRun)
        .where(ExtractionRun.batch_id.in_(list(batch_dataset.keys())))
        .order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc())
    ).all()
    if not runs:
        return results

    run_ids = [run.id for run in runs if run.id is not None]
    run_case_links: Dict[int, List[str]] = {}
    if run_ids:
        rows = session.exec(
            select(BaselineCaseRun.run_id, BaselineCaseRun.baseline_case_id)
            .where(BaselineCaseRun.run_id.in_(run_ids))
        ).all()
        for run_id, case_id in rows:
            if run_id is None or not case_id:
                continue
            run_case_links.setdefault(run_id, []).append(case_id)

    latest_runs: Dict[tuple[str, str], ExtractionRun] = {}
    for run in runs:
        if not run.id or not run.batch_id:
            continue
        dataset = batch_dataset.get(run.batch_id)
        if not dataset:
            continue
        case_to_paper = dataset_case_to_paper.get(dataset, {})
        linked_case_ids = list(run_case_links.get(run.id, []))
        if run.baseline_case_id and run.baseline_case_id not in linked_case_ids:
            linked_case_ids.append(run.baseline_case_id)

        paper_keys = {case_to_paper.get(case_id) for case_id in linked_case_ids}
        for paper_key in paper_keys:
            if not paper_key:
                continue
            latest_runs.setdefault((run.batch_id, paper_key), run)

    for batch in batches:
        if not batch.batch_id:
            continue
        expected_by_paper = dataset_groups.get(batch.dataset, {})
        for paper_key, case_sequences in expected_by_paper.items():
            expected = len(case_sequences)
            if expected <= 0:
                continue
            run = latest_runs.get((batch.batch_id, paper_key))
            if not run or run.status != RunStatus.STORED.value:
                continue

            extracted = _extract_sequences(run.raw_json)
            if not extracted:
                continue

            matched = 0
            for sequence in case_sequences.values():
                if sequence in extracted:
                    matched += 1
            if matched >= expected:
                results[batch.batch_id] = results.get(batch.batch_id, 0) + 1

    return results


def _ensure_baseline_editing_enabled() -> None:
    if not settings.BASELINE_EDITING_ENABLED:
        raise HTTPException(status_code=403, detail="Baseline editing is disabled")


def _resolve_provider_selection_or_400(provider: Optional[str], model: Optional[str]):
    try:
        return resolve_provider_selection(provider=provider, model=model)
    except ProviderSelectionError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_request",
                "message": str(exc),
                "details": exc.details,
            },
        ) from exc


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
        case.paper_key = get_case_paper_key(case)
        if case_data.get("source_unverified") is None:
            case.source_unverified = is_local_pdf_unverified(case.doi)
        else:
            case.source_unverified = bool(case_data.get("source_unverified"))
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
    case.paper_key = get_case_paper_key(case)
    if case_data.get("source_unverified") is None:
        case.source_unverified = is_local_pdf_unverified(case.doi)
    else:
        case.source_unverified = bool(case_data.get("source_unverified"))
    return BaselineCaseSummary(
        **case.model_dump(),
        latest_run=build_baseline_run_summary(run) if run else None,
    )


@router.post("/api/baseline/cases", response_model=BaselineCaseSummary)
async def create_baseline_case(
    req: BaselineCaseCreateRequest,
    session: Session = Depends(get_session),
) -> BaselineCaseSummary:
    _ensure_baseline_editing_enabled()
    store = BaselineStore(session)
    try:
        case_data = store.create_case(req.model_dump())
    except BaselineConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BaselineValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    case = BaselineCase(**case_data)
    await mark_batches_stale_and_trigger(dataset=case.dataset)
    return BaselineCaseSummary(**case.model_dump(), latest_run=None)


@router.patch("/api/baseline/cases/{case_id}", response_model=BaselineCaseSummary)
async def update_baseline_case(
    case_id: str,
    req: BaselineCaseUpdateRequest,
    session: Session = Depends(get_session),
) -> BaselineCaseSummary:
    _ensure_baseline_editing_enabled()
    store = BaselineStore(session)
    payload = req.model_dump(exclude_none=True)
    expected_updated_at = payload.pop("expected_updated_at", None)
    try:
        case_data = store.update_case(case_id, payload, expected_updated_at)
    except BaselineNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BaselineConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BaselineValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    case = BaselineCase(**case_data)
    latest_run = get_latest_baseline_run(session, case.id)
    await mark_batches_stale_and_trigger(dataset=case.dataset)
    return BaselineCaseSummary(
        **case.model_dump(),
        latest_run=build_baseline_run_summary(latest_run) if latest_run else None,
    )


@router.delete("/api/baseline/cases/{case_id}", response_model=BaselineDeleteResponse)
async def delete_baseline_case(
    case_id: str,
    req: BaselineCaseDeleteRequest,
    session: Session = Depends(get_session),
) -> BaselineDeleteResponse:
    _ensure_baseline_editing_enabled()
    store = BaselineStore(session)
    existing = store.get_case(case_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Baseline case not found")

    try:
        deleted = store.delete_case(case_id, req.expected_updated_at)
    except BaselineConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BaselineValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Baseline case not found")

    await mark_batches_stale_and_trigger(dataset=existing.get("dataset"))
    return BaselineDeleteResponse(status="ok", deleted_cases=1)


@router.delete("/api/baseline/papers/{paper_key:path}", response_model=BaselineDeleteResponse)
async def delete_baseline_paper_group(
    paper_key: str,
    session: Session = Depends(get_session),
) -> BaselineDeleteResponse:
    _ensure_baseline_editing_enabled()
    store = BaselineStore(session)
    deleted = store.delete_paper_group(paper_key)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Baseline paper not found")
    await mark_batches_stale_and_trigger()
    return BaselineDeleteResponse(status="ok", deleted_cases=deleted)


@router.post("/api/baseline/reset-defaults", response_model=BaselineResetResponse)
async def reset_baseline_defaults(
    session: Session = Depends(get_session),
) -> BaselineResetResponse:
    _ensure_baseline_editing_enabled()
    index_payload = load_backup_index()
    dataset_cases: Dict[str, List[Dict[str, object]]] = {}
    for dataset_entry in index_payload.get("datasets", []):
        dataset_id = dataset_entry.get("id")
        if not dataset_id:
            continue
        seeded_rows: List[Dict[str, object]] = []
        for case_payload in load_backup_dataset(dataset_id):
            row = dict(case_payload or {})
            if row.get("source_unverified") is None:
                row["source_unverified"] = is_local_pdf_unverified(row.get("doi"))
            seeded_rows.append(row)
        dataset_cases[dataset_id] = seeded_rows

    store = BaselineStore(session)
    result = store.reset_from_backup(index_payload, dataset_cases)
    store.relink_runs_to_cases_from_papers()
    # Reset should return immediately consistent summaries for overview screens.
    recompute_batches_now()
    await mark_batches_stale_and_trigger()
    return BaselineResetResponse(status="ok", **result)


@router.get("/api/baseline/recompute-status", response_model=BaselineRecomputeStatusResponse)
async def get_baseline_recompute_status() -> BaselineRecomputeStatusResponse:
    return BaselineRecomputeStatusResponse(**get_recompute_status())


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
    model: Optional[str] = Form(None),
    prompt_id: Optional[int] = Form(None),
    session: Session = Depends(get_session),
) -> RetryResponse:
    coordinator = QueueCoordinator()
    selection = _resolve_provider_selection_or_400(provider or settings.LLM_PROVIDER, model)
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

    run = ExtractionRun(
        paper_id=paper_id,
        status=RunStatus.QUEUED.value,
        model_provider=selection.provider_id,
        model_name=selection.model_id,
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
    selection = _resolve_provider_selection_or_400(req.provider, req.model)
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
                model_provider=selection.provider_id,
                model_name=selection.model_id,
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
            model_provider=selection.provider_id,
            model_name=selection.model_id,
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
    papers_all_matched = _compute_papers_all_matched_by_batch(session, batches)
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
                papers_all_matched=papers_all_matched.get(b.batch_id, 0),
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
    selection = _resolve_provider_selection_or_400(req.provider, req.model)
    coordinator = QueueCoordinator()
    paper_repo = PaperRepository(session)

    cases_raw = list_cases(req.dataset)
    grouped_cases: Dict[str, List[BaselineCase]] = {}
    for case_data in cases_raw:
        case = BaselineCase(**case_data)
        case.paper_key = get_case_paper_key(case)
        grouped_cases.setdefault(case.paper_key or f"case:{case.id}", []).append(case)

    model_name = selection.model_id
    batch_id = generate_batch_id(model_name)

    batch = BatchRun(
        batch_id=batch_id,
        label=req.label,
        dataset=req.dataset,
        model_provider=selection.provider_id,
        model_name=model_name,
        status=BatchStatus.RUNNING.value,
        total_papers=len(grouped_cases),
        completed=0,
        failed=0,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)

    runs_enqueued = 0
    immediate_failed = 0
    local_upload_cache: Dict[str, object] = {}

    for paper_cases in grouped_cases.values():
        case_ids = [case.id for case in paper_cases]
        representative_case = paper_cases[0]
        source = None
        resolved_url = None
        for case in paper_cases:
            candidate_source = await resolve_baseline_source(case, local_upload_cache)
            candidate_url = (
                candidate_source.pdf_url
                if candidate_source and candidate_source.pdf_url
                else (candidate_source.url if candidate_source else None)
            )
            if candidate_url:
                source = candidate_source
                resolved_url = candidate_url
                representative_case = case
                break

        if not resolved_url:
            failed_run = ExtractionRun(
                status=RunStatus.FAILED.value,
                failure_reason="No source URL resolved for baseline paper",
                model_provider=selection.provider_id,
                model_name=selection.model_id,
                prompt_id=req.prompt_id,
                batch_id=batch_id,
                baseline_dataset=req.dataset,
            )
            session.add(failed_run)
            session.commit()
            session.refresh(failed_run)
            link_cases_to_run(session, case_ids, failed_run.id)
            batch.failed += 1
            immediate_failed += 1
            continue

        meta = PaperMeta(
            title=(source.title if source else None) or baseline_title(representative_case),
            doi=(source.doi if source else None) or representative_case.doi,
            url=(source.url if source else None) or representative_case.paper_url,
            source=source.source if source else "baseline",
            year=source.year if source else None,
            authors=source.authors if source and source.authors else [],
        )
        paper_id = paper_repo.upsert(meta)
        run = ExtractionRun(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider=selection.provider_id,
            model_name=selection.model_id,
            pdf_url=resolved_url,
            prompt_id=req.prompt_id,
            batch_id=batch_id,
            baseline_dataset=req.dataset,
        )
        all_pdf_urls = source.pdf_urls if source and source.pdf_urls else None
        result = coordinator.enqueue_new_run(
            session,
            run=run,
            title=meta.title or baseline_title(representative_case),
            pdf_urls=all_pdf_urls,
        )
        if not result.enqueued:
            failed_run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="Source already queued for another active run",
                model_provider=selection.provider_id,
                model_name=selection.model_id,
                prompt_id=req.prompt_id,
                batch_id=batch_id,
                baseline_dataset=req.dataset,
                pdf_url=resolved_url,
            )
            session.add(failed_run)
            session.commit()
            session.refresh(failed_run)
            link_cases_to_run(session, case_ids, failed_run.id)
            batch.failed += 1
            immediate_failed += 1
            continue
        link_cases_to_run(session, case_ids, result.run_id)
        runs_enqueued += 1

    if runs_enqueued == 0 and batch.total_papers > 0 and batch.failed >= batch.total_papers:
        batch.status = BatchStatus.FAILED.value
        batch.completed_at = utc_now()
    session.add(batch)
    session.commit()

    return BatchEnqueueResponse(
        batch_id=batch_id,
        total_papers=batch.total_papers,
        enqueued=runs_enqueued,
        skipped=immediate_failed,
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
            model=req.model,
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
    papers_all_matched = _compute_papers_all_matched_by_batch(session, [batch]).get(batch.batch_id, 0)
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
        papers_all_matched=papers_all_matched,
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
