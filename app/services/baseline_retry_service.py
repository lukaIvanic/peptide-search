from __future__ import annotations

from typing import Dict, Optional

from sqlmodel import Session, select

from ..baseline.loader import get_case, list_cases
from ..integrations.llm import ProviderSelectionError, resolve_provider_selection
from ..persistence.models import BaselineCaseRun, BatchRun, BatchStatus, ExtractionRun, RunStatus
from ..persistence.repository import PaperRepository
from ..schemas import BaselineCase, BaselineRetryRequest, BatchRetryResponse, PaperMeta
from ..time_utils import utc_now
from .baseline_helpers import (
    baseline_title,
    get_latest_run_for_cases,
    get_source_keys,
    link_cases_to_run,
    resolve_baseline_source,
    resolve_local_pdf_source,
)
from .queue_coordinator import QueueCoordinator
from .queue_service import ExtractionQueue
from .upload_store import is_upload_url
from .runs_retry_service import ServiceError


PROCESSING_STATUSES = {
    RunStatus.QUEUED.value,
    RunStatus.FETCHING.value,
    RunStatus.PROVIDER.value,
    RunStatus.VALIDATING.value,
}


def _resolve_selection_or_error(
    *,
    provider: Optional[str],
    model: Optional[str],
    default_provider: Optional[str],
    strict_model: bool,
):
    try:
        return resolve_provider_selection(
            provider=provider or default_provider,
            model=model,
            default_provider=default_provider,
            require_enabled=True,
        )
    except ProviderSelectionError as exc:
        if model and not strict_model:
            try:
                return resolve_provider_selection(
                    provider=provider or default_provider,
                    model=None,
                    default_provider=default_provider,
                    require_enabled=True,
                )
            except ProviderSelectionError:
                pass
        raise ServiceError(
            status_code=400,
            detail={
                "code": "bad_request",
                "message": str(exc),
                "details": exc.details,
            },
        ) from exc


async def retry_baseline_case(
    *,
    session: Session,
    case_id: str,
    req: BaselineRetryRequest,
    queue: ExtractionQueue,
    default_provider: str,
) -> dict:
    coordinator = QueueCoordinator()
    case_data = get_case(case_id)
    if not case_data:
        raise ServiceError(status_code=404, detail="Baseline case not found")
    case = BaselineCase(**case_data)

    source_url = req.source_url
    source = None
    if not source_url:
        source = await resolve_baseline_source(case)
        if source:
            source_url = source.pdf_url or source.url

    if not source_url:
        raise ServiceError(status_code=400, detail="No source URL resolved for baseline case")

    source_keys = get_source_keys(case, source_url)
    case_ids = [case.id]
    if source_keys:
        for other_data in list_cases():
            other = BaselineCase(**other_data)
            other_keys = get_source_keys(other, None)
            if any(key in source_keys for key in other_keys):
                case_ids.append(other.id)
    case_ids = sorted(set(case_ids))

    existing = None
    stmt = (
        select(ExtractionRun)
        .where(ExtractionRun.pdf_url == source_url)
        .order_by(ExtractionRun.created_at.desc())
        .limit(1)
    )
    existing = session.exec(stmt).first()
    if not existing:
        existing = get_latest_run_for_cases(session, case_ids)
    if existing and existing.status in PROCESSING_STATUSES:
        link_cases_to_run(session, case_ids, existing.id)
        return {
            "id": existing.id,
            "status": existing.status,
            "message": "Baseline case already queued for processing",
            "source_url": source_url,
        }

    if await queue.is_url_pending(source_url):
        if existing:
            link_cases_to_run(session, case_ids, existing.id)
            return {
                "id": existing.id,
                "status": existing.status,
                "message": "Baseline case already queued for processing",
                "source_url": source_url,
            }
        return {
            "id": None,
            "status": RunStatus.QUEUED.value,
            "message": "Baseline case already queued for processing",
            "source_url": source_url,
        }

    meta = PaperMeta(
        title=(source.title if source else None) or baseline_title(case),
        doi=(source.doi if source else None) or case.doi,
        url=(source.url if source else None) or case.paper_url,
        source=source.source if source else "baseline",
        year=source.year if source else None,
        authors=source.authors if source and source.authors else [],
    )
    paper_repo = PaperRepository(session)
    paper_id = paper_repo.upsert(meta)

    selection = _resolve_selection_or_error(
        provider=req.provider,
        model=req.model,
        default_provider=default_provider,
        strict_model=bool(req.model),
    )

    run = ExtractionRun(
        paper_id=paper_id,
        status=RunStatus.QUEUED.value,
        model_provider=selection.provider_id,
        model_name=selection.model_id,
        pdf_url=source_url,
        prompt_id=req.prompt_id,
    )
    result = coordinator.enqueue_new_run(
        session,
        run=run,
        title=meta.title or baseline_title(case),
        pdf_urls=None,
    )
    if not result.enqueued:
        conflict_run_id = result.conflict_run_id or (existing.id if existing else None)
        if conflict_run_id:
            link_cases_to_run(session, case_ids, conflict_run_id)
        return {
            "id": conflict_run_id,
            "status": result.conflict_run_status or RunStatus.QUEUED.value,
            "message": "Baseline case already queued for processing",
            "source_url": source_url,
        }
    link_cases_to_run(session, case_ids, result.run_id)

    return {
        "id": result.run_id,
        "status": result.run_status,
        "message": "Baseline case re-queued for processing",
        "source_url": source_url,
    }


async def retry_batch_runs(
    *,
    session: Session,
    batch_id: str,
    provider: str | None,
    model: str | None,
    queue: ExtractionQueue,
) -> BatchRetryResponse:
    coordinator = QueueCoordinator()
    stmt = select(BatchRun).where(BatchRun.batch_id == batch_id)
    batch = session.exec(stmt).first()
    if not batch:
        raise ServiceError(status_code=404, detail=f"Batch not found: {batch_id}")

    provider_candidate = provider or batch.model_provider
    model_candidate = model or batch.model_name

    stmt = (
        select(ExtractionRun)
        .where(ExtractionRun.batch_id == batch_id)
        .where(ExtractionRun.status == RunStatus.FAILED.value)
    )
    failed_runs = session.exec(stmt).all()

    local_upload_cache: Dict[str, str] = {}

    retried = 0
    skipped = 0

    for run in failed_runs:
        pdf_url = run.pdf_url

        if is_upload_url(pdf_url):
            baseline_case_id = run.baseline_case_id
            if not baseline_case_id:
                link_stmt = select(BaselineCaseRun.baseline_case_id).where(BaselineCaseRun.run_id == run.id).limit(1)
                linked_id = session.exec(link_stmt).first()
                if linked_id:
                    baseline_case_id = linked_id

            if baseline_case_id:
                case_data = get_case(baseline_case_id)
                if case_data:
                    case = BaselineCase(**case_data)
                    local_source = resolve_local_pdf_source(case, local_upload_cache)
                    if local_source and local_source.pdf_url:
                        pdf_url = local_source.pdf_url
                        run.pdf_url = pdf_url

        if not pdf_url:
            skipped += 1
            continue

        selection = _resolve_selection_or_error(
            provider=provider_candidate or run.model_provider,
            model=model_candidate or run.model_name,
            default_provider=provider_candidate or run.model_provider,
            strict_model=bool(model),
        )

        run.status = RunStatus.QUEUED.value
        run.failure_reason = None
        run.model_provider = selection.provider_id
        run.model_name = selection.model_id
        result = coordinator.enqueue_existing_run(
            session,
            run=run,
            title="",
            provider=selection.provider_id,
            model=selection.model_id,
            pdf_url=pdf_url,
            pdf_urls=None,
            prompt_id=run.prompt_id,
            prompt_version_id=run.prompt_version_id,
        )
        if result.enqueued:
            retried += 1
        else:
            skipped += 1

    batch.failed = max(0, batch.failed - retried)
    remaining = max(0, batch.total_papers - (batch.completed + batch.failed))
    if remaining > 0:
        batch.status = BatchStatus.RUNNING.value
        batch.completed_at = None
    elif batch.failed == 0:
        batch.status = BatchStatus.COMPLETED.value
        batch.completed_at = batch.completed_at or utc_now()
    elif batch.completed == 0:
        batch.status = BatchStatus.FAILED.value
        batch.completed_at = batch.completed_at or utc_now()
    else:
        batch.status = BatchStatus.PARTIAL.value
        batch.completed_at = batch.completed_at or utc_now()
    session.add(batch)
    session.commit()

    return BatchRetryResponse(
        batch_id=batch_id,
        retried=retried,
        skipped=skipped,
    )
