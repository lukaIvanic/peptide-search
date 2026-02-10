from __future__ import annotations

import json
import logging

from sqlmodel import select

from ..baseline.loader import is_local_pdf_unverified, load_backup_dataset, load_backup_index
from ..db import session_scope
from ..persistence.models import ExtractionRun, QueueJob, QueueJobStatus, RunStatus
from ..persistence.repository import PromptRepository
from ..prompts import build_system_prompt
from .baseline_store import BaselineStore
from .quality_service import ensure_quality_rules

logger = logging.getLogger(__name__)


def backfill_failed_runs() -> None:
    with session_scope() as session:
        stmt = select(ExtractionRun).where(ExtractionRun.status == RunStatus.FAILED.value)
        updated = 0
        for run in session.exec(stmt).all():
            changed = False
            if not run.failure_reason:
                run.failure_reason = "Unknown failure (missing reason)"
                changed = True
            if not run.raw_json:
                run.raw_json = json.dumps({"error": run.failure_reason or "Unknown failure"})
                changed = True
            if changed:
                session.add(run)
                updated += 1
        if updated:
            logger.info("Backfilled %s failed runs missing metadata", updated)


def reconcile_orphan_run_states() -> None:
    """Reconcile transient runs that have no recoverable queue job backing them."""
    transient_statuses = {
        RunStatus.QUEUED.value,
        RunStatus.FETCHING.value,
        RunStatus.PROVIDER.value,
        RunStatus.VALIDATING.value,
    }
    recoverable_job_statuses = {
        QueueJobStatus.QUEUED.value,
        QueueJobStatus.CLAIMED.value,
    }
    with session_scope() as session:
        stmt = select(ExtractionRun).where(ExtractionRun.status.in_(transient_statuses))
        runs = session.exec(stmt).all()
        if not runs:
            return
        updated = 0
        for run in runs:
            job = session.exec(
                select(QueueJob)
                .where(QueueJob.run_id == run.id)
                .order_by(QueueJob.created_at.desc())
                .limit(1)
            ).first()
            if job and job.status in recoverable_job_statuses:
                continue

            if job and job.status == QueueJobStatus.FAILED.value:
                run.status = RunStatus.FAILED.value
                if not run.failure_reason:
                    run.failure_reason = "Recovered orphan run after failed queue job"
            elif job and job.status == QueueJobStatus.CANCELLED.value:
                run.status = RunStatus.CANCELLED.value
                if not run.failure_reason:
                    run.failure_reason = "Recovered orphan run after cancelled queue job"
            elif job and job.status == QueueJobStatus.DONE.value:
                # DONE should only happen once run reaches stored; treat as inconsistent failure.
                run.status = RunStatus.FAILED.value
                if not run.failure_reason:
                    run.failure_reason = "Recovered inconsistent run after completed queue job"
            else:
                run.status = RunStatus.CANCELLED.value
                if not run.failure_reason:
                    run.failure_reason = "Recovered orphan run after restart (no queue job)"
            session.add(run)
            updated += 1
        if updated:
            logger.info("Reconciled %s orphan transient runs after restart", updated)


def cancel_stale_runs() -> None:
    """Compatibility shim kept for older callsites/tests."""
    reconcile_orphan_run_states()


def ensure_runtime_defaults() -> None:
    """Initialize runtime-managed defaults outside request GET paths."""
    with session_scope() as session:
        repo = PromptRepository(session)
        repo.ensure_default_prompt(build_system_prompt())
        ensure_quality_rules(session)
        ensure_baseline_seeded(session)


def ensure_baseline_seeded(session) -> None:
    """Seed DB baseline tables once from backup JSON when empty."""
    store = BaselineStore(session)
    if store.has_cases():
        return

    index_payload = load_backup_index()
    dataset_cases = {}
    for dataset_entry in index_payload.get("datasets", []):
        dataset_id = dataset_entry.get("id")
        if not dataset_id:
            continue
        seeded_cases = []
        for case_payload in load_backup_dataset(dataset_id):
            row = dict(case_payload or {})
            if row.get("source_unverified") is None:
                row["source_unverified"] = is_local_pdf_unverified(row.get("doi"))
            seeded_cases.append(row)
        dataset_cases[dataset_id] = seeded_cases

    inserted = store.seed_from_backup(index_payload, dataset_cases)
    if inserted:
        logger.info("Seeded %s baseline cases into DB from backup JSON", inserted)
