from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import delete, update
from sqlmodel import Session, func, select

from ..persistence.models import (
    ActiveSourceLock,
    BaselineCaseRun,
    ExtractionEntity,
    ExtractionRun,
    Paper,
    QueueJob,
    QueueJobStatus,
    RunStatus,
)


ACTIVE_QUEUE_JOB_STATUSES = {
    QueueJobStatus.QUEUED.value,
    QueueJobStatus.CLAIMED.value,
}


class DeletionNotFoundError(Exception):
    """Raised when a requested run/paper cannot be found."""


@dataclass
class DeletionSummary:
    deleted_runs: int = 0
    deleted_entities: int = 0
    deleted_queue_jobs: int = 0
    deleted_source_locks: int = 0
    deleted_case_links: int = 0
    affected_batch_ids: set[str] = field(default_factory=set)


def _unique_ids(values: Iterable[int]) -> list[int]:
    return sorted({int(value) for value in values if value is not None})


def _collect_run_subtree_ids_for_roots(session: Session, root_run_ids: Iterable[int]) -> list[int]:
    roots = _unique_ids(root_run_ids)
    if not roots:
        return []

    lineage_ids: set[int] = set(roots)
    frontier = roots
    while frontier:
        child_ids = _unique_ids(
            session.exec(
                select(ExtractionRun.id).where(ExtractionRun.parent_run_id.in_(frontier))
            ).all()
        )
        next_frontier = [child_id for child_id in child_ids if child_id not in lineage_ids]
        if not next_frontier:
            break
        lineage_ids.update(next_frontier)
        frontier = next_frontier

    return sorted(lineage_ids)


def collect_run_subtree_ids(session: Session, root_run_id: int) -> list[int]:
    """Collect root run + all descendants connected by parent_run_id."""
    root = session.get(ExtractionRun, root_run_id)
    if not root:
        return []
    return _collect_run_subtree_ids_for_roots(session, [root_run_id])


def delete_runs_by_ids(
    session: Session,
    run_ids: Iterable[int],
    *,
    deleted_by: str = "user",
    commit: bool = True,
) -> DeletionSummary:
    target_ids = _unique_ids(run_ids)
    if not target_ids:
        return DeletionSummary()

    runs = session.exec(select(ExtractionRun).where(ExtractionRun.id.in_(target_ids))).all()
    existing_run_ids = [run.id for run in runs if run.id is not None]
    if not existing_run_ids:
        return DeletionSummary()

    affected_batch_ids = {
        run.batch_id
        for run in runs
        if run.batch_id
    }

    active_run_ids = _unique_ids(
        session.exec(
            select(QueueJob.run_id)
            .where(QueueJob.run_id.in_(existing_run_ids))
            .where(QueueJob.status.in_(ACTIVE_QUEUE_JOB_STATUSES))
        ).all()
    )
    if active_run_ids:
        session.exec(
            update(ExtractionRun)
            .where(ExtractionRun.id.in_(active_run_ids))
            .values(
                status=RunStatus.CANCELLED.value,
                failure_reason=f"Deleted by {deleted_by}",
            )
        )

    deleted_entities = int(
        session.exec(
            select(func.count(ExtractionEntity.id)).where(ExtractionEntity.run_id.in_(existing_run_ids))
        ).one()
        or 0
    )
    deleted_queue_jobs = int(
        session.exec(
            select(func.count(QueueJob.id)).where(QueueJob.run_id.in_(existing_run_ids))
        ).one()
        or 0
    )
    deleted_source_locks = int(
        session.exec(
            select(func.count(ActiveSourceLock.source_fingerprint))
            .where(ActiveSourceLock.run_id.in_(existing_run_ids))
        ).one()
        or 0
    )
    deleted_case_links = int(
        session.exec(
            select(func.count(BaselineCaseRun.id)).where(BaselineCaseRun.run_id.in_(existing_run_ids))
        ).one()
        or 0
    )

    # Keep explicit cleanup order to avoid FK issues on stricter backends.
    session.exec(delete(ActiveSourceLock).where(ActiveSourceLock.run_id.in_(existing_run_ids)))
    session.exec(delete(QueueJob).where(QueueJob.run_id.in_(existing_run_ids)))
    session.exec(delete(BaselineCaseRun).where(BaselineCaseRun.run_id.in_(existing_run_ids)))
    session.exec(delete(ExtractionEntity).where(ExtractionEntity.run_id.in_(existing_run_ids)))
    session.exec(delete(ExtractionRun).where(ExtractionRun.id.in_(existing_run_ids)))

    if commit:
        session.commit()

    return DeletionSummary(
        deleted_runs=len(existing_run_ids),
        deleted_entities=deleted_entities,
        deleted_queue_jobs=deleted_queue_jobs,
        deleted_source_locks=deleted_source_locks,
        deleted_case_links=deleted_case_links,
        affected_batch_ids=affected_batch_ids,
    )


def delete_run_subtree(session: Session, run_id: int, *, deleted_by: str = "user") -> DeletionSummary:
    run = session.get(ExtractionRun, run_id)
    if not run:
        raise DeletionNotFoundError("Run not found")
    subtree_ids = collect_run_subtree_ids(session, run_id)
    return delete_runs_by_ids(session, subtree_ids, deleted_by=deleted_by, commit=True)


def delete_paper_with_runs(session: Session, paper_id: int, *, deleted_by: str = "user") -> DeletionSummary:
    paper = session.get(Paper, paper_id)
    if not paper:
        raise DeletionNotFoundError("Paper not found")

    root_run_ids = _unique_ids(
        session.exec(select(ExtractionRun.id).where(ExtractionRun.paper_id == paper_id)).all()
    )
    run_ids = _collect_run_subtree_ids_for_roots(session, root_run_ids)
    summary = delete_runs_by_ids(session, run_ids, deleted_by=deleted_by, commit=False)

    session.delete(paper)
    session.commit()
    return summary
