from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from ..persistence.models import ExtractionRun, Paper, RunStatus
from ..persistence.repository import BaselineCaseRunRepository
from ..schemas import BulkRetryRequest, BulkRetryResponse
from ..time_utils import utc_now
from .baseline_helpers import link_cases_to_run
from .failure_reason import bucket_failure_reason, normalize_failure_reason
from .queue_service import ExtractionQueue, QueueItem
from .retry_policies import failure_matches_filters, reconcile_skipped_count, resolve_retry_source_url


@dataclass
class ServiceError(Exception):
    status_code: int
    detail: str


async def retry_run(
    *,
    session: Session,
    run_id: int,
    queue: ExtractionQueue,
    default_provider: str,
) -> dict:
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

    if run.pdf_url and await queue.is_url_pending(run.pdf_url):
        return {
            "id": run.id,
            "status": run.status,
            "message": "Run already queued for processing",
        }

    run.status = RunStatus.QUEUED.value
    run.failure_reason = None
    session.add(run)
    session.commit()
    session.refresh(run)

    await queue.enqueue(
        QueueItem(
            run_id=run.id,
            paper_id=paper.id,
            pdf_url=run.pdf_url,
            title=paper.title,
            provider=run.model_provider or default_provider,
            force=True,
            prompt_id=run.prompt_id,
            prompt_version_id=run.prompt_version_id,
        )
    )

    return {
        "id": run.id,
        "status": run.status,
        "message": "Run re-queued for processing",
    }


async def retry_run_with_source(
    *,
    session: Session,
    run_id: int,
    source_url: Optional[str],
    provider: Optional[str],
    prompt_id: Optional[int],
    queue: ExtractionQueue,
    default_provider: str,
) -> dict:
    run = session.get(ExtractionRun, run_id)
    if not run:
        raise ServiceError(status_code=404, detail="Run not found")
    paper = session.get(Paper, run.paper_id) if run.paper_id else None
    if not paper:
        raise ServiceError(status_code=404, detail="Paper not found")

    resolved_source_url = resolve_retry_source_url(source_url, run.pdf_url, paper.url)
    if not resolved_source_url:
        raise ServiceError(status_code=400, detail="No source URL available for retry")

    use_provider = provider or run.model_provider or default_provider
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
        model_provider=use_provider,
        pdf_url=resolved_source_url,
        prompt_id=use_prompt_id,
        prompt_version_id=run.prompt_version_id,
        parent_run_id=run.id,
    )
    session.add(new_run)
    session.commit()
    session.refresh(new_run)

    linked_cases = BaselineCaseRunRepository(session).list_case_ids_for_run(run.id)
    if not linked_cases and run.baseline_case_id:
        linked_cases = [run.baseline_case_id]
    link_cases_to_run(session, linked_cases, new_run.id)

    await queue.enqueue(
        QueueItem(
            run_id=new_run.id,
            paper_id=paper.id,
            pdf_url=resolved_source_url,
            title=paper.title or "(Untitled)",
            provider=use_provider,
            force=True,
            prompt_id=use_prompt_id,
            prompt_version_id=run.prompt_version_id,
        )
    )

    return {
        "id": new_run.id,
        "status": new_run.status,
        "message": "New run created and queued",
    }


async def retry_failed_runs(
    *,
    session: Session,
    req: BulkRetryRequest,
    queue: ExtractionQueue,
    default_provider: str,
) -> BulkRetryResponse:
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
    to_enqueue: list[QueueItem] = []

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

        run.status = RunStatus.QUEUED.value
        run.failure_reason = None
        session.add(run)
        to_enqueue.append(
            QueueItem(
                run_id=run.id,
                paper_id=paper.id,
                pdf_url=run.pdf_url,
                title=paper.title or "(Untitled)",
                provider=run.model_provider or default_provider,
                force=True,
                prompt_id=run.prompt_id,
                prompt_version_id=run.prompt_version_id,
            )
        )

    session.commit()
    for item in to_enqueue:
        await queue.enqueue(item)
        enqueued += 1

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
                "created_at": run.created_at.isoformat() + "Z" if run.created_at else None,
                "paper_title": paper.title if paper else None,
                "paper_doi": paper.doi if paper else None,
                "paper_url": paper.url if paper else None,
                "paper_source": paper.source if paper else None,
                "paper_year": paper.year if paper else None,
            }
        )
        if len(items) >= limit:
            break

    window_start = cutoff.isoformat() + "Z"
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
    stmt = (
        select(ExtractionRun)
        .where(ExtractionRun.paper_id == run.paper_id)
        .order_by(ExtractionRun.created_at.desc())
    )
    versions = []
    for item in session.exec(stmt).all():
        versions.append(
            {
                "id": item.id,
                "parent_run_id": item.parent_run_id,
                "status": item.status,
                "model_provider": item.model_provider,
                "model_name": item.model_name,
                "created_at": item.created_at.isoformat() + "Z" if item.created_at else None,
            }
        )
    return {"paper_id": run.paper_id, "versions": versions}
