from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from ..integrations.llm import ProviderSelectionError, resolve_provider_selection
from ..persistence.models import ExtractionRun, Paper, RunStatus
from ..persistence.repository import BaselineCaseRunRepository
from ..schemas import BulkRetryRequest, BulkRetryResponse
from ..time_utils import utc_now
from .baseline_helpers import link_cases_to_run
from .failure_reason import bucket_failure_reason, normalize_failure_reason
from .queue_coordinator import QueueCoordinator
from .queue_service import ExtractionQueue
from .retry_policies import failure_matches_filters, reconcile_skipped_count, resolve_retry_source_url
from .serializers import iso_z


@dataclass
class ServiceError(Exception):
    status_code: int
    detail: Any


def _resolve_retry_selection(
    *,
    provider: Optional[str],
    model: Optional[str],
    default_provider: str,
    strict_model: bool = False,
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


async def retry_run(
    *,
    session: Session,
    run_id: int,
    queue: ExtractionQueue,
    default_provider: str,
) -> dict:
    coordinator = QueueCoordinator()
    run = session.get(ExtractionRun, run_id)
    if not run:
        raise ServiceError(status_code=404, detail="Run not found")

    if run.status != RunStatus.FAILED.value:
        raise ServiceError(
            status_code=400,
            detail=f"Can only retry failed runs. Current status: {run.status}",
        )

    paper = session.get(Paper, run.paper_id)
    if not paper:
        raise ServiceError(status_code=404, detail="Paper not found")

    selection = _resolve_retry_selection(
        provider=run.model_provider or default_provider,
        model=run.model_name,
        default_provider=default_provider,
    )

    if run.pdf_url and await queue.is_url_pending(run.pdf_url):
        return {
            "id": run.id,
            "status": run.status,
            "message": "Run already queued for processing",
        }

    result = coordinator.enqueue_existing_run(
        session,
        run=run,
        title=paper.title or "(Untitled)",
        provider=selection.provider_id,
        model=selection.model_id,
        pdf_url=run.pdf_url,
        pdf_urls=None,
        prompt_id=run.prompt_id,
        prompt_version_id=run.prompt_version_id,
    )
    if not result.enqueued:
        return {
            "id": result.conflict_run_id or run.id,
            "status": result.conflict_run_status or RunStatus.QUEUED.value,
            "message": "Run already queued for processing",
        }

    return {
        "id": result.run_id,
        "status": result.run_status,
        "message": "Run re-queued for processing",
    }


async def retry_run_with_source(
    *,
    session: Session,
    run_id: int,
    source_url: Optional[str],
    provider: Optional[str],
    model: Optional[str],
    prompt_id: Optional[int],
    queue: ExtractionQueue,
    default_provider: str,
) -> dict:
    coordinator = QueueCoordinator()
    run = session.get(ExtractionRun, run_id)
    if not run:
        raise ServiceError(status_code=404, detail="Run not found")
    paper = session.get(Paper, run.paper_id) if run.paper_id else None
    if not paper:
        raise ServiceError(status_code=404, detail="Paper not found")

    resolved_source_url = resolve_retry_source_url(source_url, run.pdf_url, paper.url)
    if not resolved_source_url:
        raise ServiceError(status_code=400, detail="No source URL available for retry")

    selection = _resolve_retry_selection(
        provider=provider or run.model_provider or default_provider,
        model=model or run.model_name,
        default_provider=default_provider,
        strict_model=bool(model),
    )
    use_prompt_id = prompt_id or run.prompt_id
    if await queue.is_url_pending(resolved_source_url):
        return {
            "id": run.id,
            "status": RunStatus.QUEUED.value,
            "message": "Run already queued for processing",
        }

    new_run = ExtractionRun(
        paper_id=paper.id,
        status=RunStatus.QUEUED.value,
        model_provider=selection.provider_id,
        model_name=selection.model_id,
        pdf_url=resolved_source_url,
        prompt_id=use_prompt_id,
        prompt_version_id=run.prompt_version_id,
        parent_run_id=run.id,
    )
    result = coordinator.enqueue_new_run(
        session,
        run=new_run,
        title=paper.title or "(Untitled)",
        pdf_urls=None,
    )
    if not result.enqueued:
        return {
            "id": result.conflict_run_id or run.id,
            "status": result.conflict_run_status or RunStatus.QUEUED.value,
            "message": "Run already queued for processing",
        }

    linked_cases = BaselineCaseRunRepository(session).list_case_ids_for_run(run.id)
    if not linked_cases and run.baseline_case_id:
        linked_cases = [run.baseline_case_id]
    link_cases_to_run(session, linked_cases, result.run_id)

    return {
        "id": result.run_id,
        "status": result.run_status,
        "message": "New run created and queued",
    }


async def retry_failed_runs(
    *,
    session: Session,
    req: BulkRetryRequest,
    queue: ExtractionQueue,
    default_provider: str,
) -> BulkRetryResponse:
    coordinator = QueueCoordinator()
    cutoff = utc_now() - timedelta(days=req.days)
    stmt = (
        select(ExtractionRun, Paper)
        .join(Paper, ExtractionRun.paper_id == Paper.id, isouter=True)
        .where(ExtractionRun.status == RunStatus.FAILED.value)
        .where(ExtractionRun.created_at >= cutoff)
        .order_by(ExtractionRun.created_at.desc())
        .limit(req.max_runs)
    )
    if req.provider:
        stmt = stmt.where(ExtractionRun.model_provider == req.provider)
    if req.source:
        stmt = stmt.where(Paper.source == req.source)
    rows = session.exec(stmt).all()

    requested = 0
    enqueued = 0
    skipped = 0
    skipped_missing_pdf = 0
    skipped_missing_paper = 0
    skipped_not_failed = 0
    for run, paper in rows:
        if not failure_matches_filters(run.failure_reason, req.bucket, req.reason):
            continue
        if requested >= req.limit:
            break
        requested += 1

        if run.status != RunStatus.FAILED.value:
            skipped_not_failed += 1
            continue
        if not paper:
            skipped_missing_paper += 1
            skipped += 1
            continue
        if not run.pdf_url:
            skipped_missing_pdf += 1
            skipped += 1
            continue
        if await queue.is_url_pending(run.pdf_url):
            skipped += 1
            continue

        selection = _resolve_retry_selection(
            provider=run.model_provider or default_provider,
            model=run.model_name,
            default_provider=default_provider,
        )
        result = coordinator.enqueue_existing_run(
            session,
            run=run,
            title=paper.title or "(Untitled)",
            provider=selection.provider_id,
            model=selection.model_id,
            pdf_url=run.pdf_url,
            pdf_urls=None,
            prompt_id=run.prompt_id,
            prompt_version_id=run.prompt_version_id,
        )
        if result.enqueued:
            enqueued += 1
        else:
            skipped += 1

    skipped = reconcile_skipped_count(
        requested=requested,
        enqueued=enqueued,
        skipped=skipped,
        skipped_not_failed=skipped_not_failed,
    )

    return BulkRetryResponse(
        requested=requested,
        enqueued=enqueued,
        skipped=skipped,
        skipped_missing_pdf=skipped_missing_pdf,
        skipped_missing_paper=skipped_missing_paper,
        skipped_not_failed=skipped_not_failed,
    )


def list_failed_runs_payload(
    *,
    session: Session,
    days: int,
    limit: int,
    max_runs: int,
    bucket: Optional[str],
    provider: Optional[str],
    source: Optional[str],
    reason: Optional[str],
) -> dict:
    from datetime import timedelta

    cutoff = utc_now() - timedelta(days=days)
    stmt = (
        select(ExtractionRun, Paper)
        .join(Paper, ExtractionRun.paper_id == Paper.id, isouter=True)
        .where(ExtractionRun.status == RunStatus.FAILED.value)
        .where(ExtractionRun.created_at >= cutoff)
        .order_by(ExtractionRun.created_at.desc())
        .limit(max_runs)
    )
    if provider:
        stmt = stmt.where(ExtractionRun.model_provider == provider)
    if source:
        stmt = stmt.where(Paper.source == source)
    rows = session.exec(stmt).all()
    items = []
    for run, paper in rows:
        bucket_key = bucket_failure_reason(run.failure_reason)
        normalized_reason = normalize_failure_reason(run.failure_reason)
        if bucket and bucket_key != bucket:
            continue
        if reason and normalized_reason != reason:
            continue
        items.append(
            {
                "id": run.id,
                "paper_id": run.paper_id,
                "status": run.status,
                "failure_reason": run.failure_reason,
                "bucket": bucket_key,
                "normalized_reason": normalized_reason,
                "model_provider": run.model_provider,
                "model_name": run.model_name,
                "created_at": iso_z(run.created_at),
                "paper_title": paper.title if paper else None,
                "paper_doi": paper.doi if paper else None,
                "paper_url": paper.url if paper else None,
                "paper_source": paper.source if paper else None,
                "paper_year": paper.year if paper else None,
            }
        )
        if len(items) >= limit:
            break

    window_start = iso_z(cutoff)
    return {
        "items": items,
        "total": len(items),
        "window_days": days,
        "window_start": window_start,
    }


def run_history_payload(*, session: Session, run_id: int) -> dict:
    run = session.get(ExtractionRun, run_id)
    if not run:
        raise ServiceError(status_code=404, detail="Run not found")

    if run.paper_id is not None:
        stmt = (
            select(ExtractionRun)
            .where(ExtractionRun.paper_id == run.paper_id)
            .order_by(ExtractionRun.created_at.desc())
        )
        runs = session.exec(stmt).all()
    else:
        lineage_ids: set[int] = {run.id}

        # Walk ancestors.
        parent_id = run.parent_run_id
        while parent_id is not None and parent_id not in lineage_ids:
            lineage_ids.add(parent_id)
            parent = session.get(ExtractionRun, parent_id)
            if not parent:
                break
            parent_id = parent.parent_run_id

        # Walk descendants.
        frontier = [run.id]
        while frontier:
            child_ids = session.exec(
                select(ExtractionRun.id).where(ExtractionRun.parent_run_id.in_(frontier))
            ).all()
            next_frontier = [child_id for child_id in child_ids if child_id not in lineage_ids]
            if not next_frontier:
                break
            lineage_ids.update(next_frontier)
            frontier = next_frontier

        runs = session.exec(
            select(ExtractionRun)
            .where(ExtractionRun.id.in_(lineage_ids))
            .order_by(ExtractionRun.created_at.desc())
        ).all()

    versions = []
    for item in runs:
        versions.append(
            {
                "id": item.id,
                "parent_run_id": item.parent_run_id,
                "status": item.status,
                "model_provider": item.model_provider,
                "model_name": item.model_name,
                "created_at": iso_z(item.created_at),
            }
        )
    return {"paper_id": run.paper_id, "versions": versions}
