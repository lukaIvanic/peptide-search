from __future__ import annotations

from typing import List

from sqlmodel import Session, select

from app.persistence.models import (
    ActiveSourceLock,
    BatchRun,
    BatchStatus,
    ExtractionRun,
    QueueJob,
    QueueJobStatus,
    RunStatus,
)

_TRANSIENT_RUN_STATUSES = {
    RunStatus.QUEUED.value,
    RunStatus.FETCHING.value,
    RunStatus.PROVIDER.value,
    RunStatus.VALIDATING.value,
}
_RECOVERABLE_JOB_STATUSES = {
    QueueJobStatus.QUEUED.value,
    QueueJobStatus.CLAIMED.value,
}
_TERMINAL_JOB_STATUSES = {
    QueueJobStatus.DONE.value,
    QueueJobStatus.FAILED.value,
    QueueJobStatus.CANCELLED.value,
}


def _latest_job_for_run(session: Session, run_id: int) -> QueueJob | None:
    return session.exec(
        select(QueueJob)
        .where(QueueJob.run_id == run_id)
        .order_by(QueueJob.created_at.desc(), QueueJob.id.desc())
        .limit(1)
    ).first()


def collect_queue_invariant_errors(session: Session) -> List[str]:
    errors: List[str] = []

    claimed_jobs = session.exec(
        select(QueueJob).where(QueueJob.status == QueueJobStatus.CLAIMED.value)
    ).all()
    for job in claimed_jobs:
        if not job.claimed_by:
            errors.append(f"claimed job {job.id} missing claimed_by")
        if not job.claim_token:
            errors.append(f"claimed job {job.id} missing claim_token")
        if not job.claimed_at:
            errors.append(f"claimed job {job.id} missing claimed_at")

    locks = session.exec(select(ActiveSourceLock)).all()
    for lock in locks:
        run = session.get(ExtractionRun, lock.run_id)
        if not run:
            errors.append(f"source lock {lock.source_fingerprint} points to missing run {lock.run_id}")
            continue
        latest_job = _latest_job_for_run(session, run.id or 0)
        if not latest_job:
            errors.append(
                f"source lock {lock.source_fingerprint} for run {run.id} has no queue job"
            )
            continue
        if latest_job.status not in _RECOVERABLE_JOB_STATUSES:
            errors.append(
                f"source lock {lock.source_fingerprint} for run {run.id} has non-recoverable "
                f"job status {latest_job.status}"
            )

    transient_runs = session.exec(
        select(ExtractionRun).where(ExtractionRun.status.in_(_TRANSIENT_RUN_STATUSES))
    ).all()
    for run in transient_runs:
        latest_job = _latest_job_for_run(session, run.id or 0)
        if not latest_job:
            errors.append(f"transient run {run.id} ({run.status}) has no queue job")
            continue
        if latest_job.status not in _RECOVERABLE_JOB_STATUSES:
            errors.append(
                f"transient run {run.id} ({run.status}) has non-recoverable job {latest_job.status}"
            )

    all_runs = session.exec(select(ExtractionRun)).all()
    for run in all_runs:
        latest_job = _latest_job_for_run(session, run.id or 0)
        if not latest_job:
            continue
        if latest_job.status in _TERMINAL_JOB_STATUSES and run.status in _TRANSIENT_RUN_STATUSES:
            errors.append(
                f"run {run.id} is transient ({run.status}) while latest queue job is terminal "
                f"({latest_job.status})"
            )

    batches = session.exec(select(BatchRun)).all()
    for batch in batches:
        if batch.total_papers < 0:
            errors.append(f"batch {batch.batch_id} has negative total_papers={batch.total_papers}")
        if batch.completed < 0:
            errors.append(f"batch {batch.batch_id} has negative completed={batch.completed}")
        if batch.failed < 0:
            errors.append(f"batch {batch.batch_id} has negative failed={batch.failed}")
        if batch.completed + batch.failed > batch.total_papers:
            errors.append(
                f"batch {batch.batch_id} has completed+failed={batch.completed + batch.failed} "
                f"> total_papers={batch.total_papers}"
            )

        if batch.total_papers <= 0:
            continue

        if batch.completed + batch.failed < batch.total_papers:
            expected_status = BatchStatus.RUNNING.value
        elif batch.failed == 0:
            expected_status = BatchStatus.COMPLETED.value
        elif batch.completed == 0:
            expected_status = BatchStatus.FAILED.value
        else:
            expected_status = BatchStatus.PARTIAL.value

        if batch.status != expected_status:
            errors.append(
                f"batch {batch.batch_id} status={batch.status} expected={expected_status} "
                f"for completed={batch.completed}, failed={batch.failed}, total={batch.total_papers}"
            )

    return errors


def assert_queue_invariants(testcase, engine, *, context: str = "") -> None:
    with Session(engine) as session:
        errors = collect_queue_invariant_errors(session)
    if errors:
        prefix = f"[{context}] " if context else ""
        testcase.fail(prefix + "Queue invariants violated:\n- " + "\n- ".join(errors))
