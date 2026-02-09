from __future__ import annotations

import json
import logging

from sqlmodel import select

from ..db import session_scope
from ..persistence.models import ExtractionRun, RunStatus

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


def cancel_stale_runs() -> None:
    stale_statuses = {
        RunStatus.QUEUED.value,
        RunStatus.FETCHING.value,
        RunStatus.PROVIDER.value,
        RunStatus.VALIDATING.value,
    }
    with session_scope() as session:
        stmt = select(ExtractionRun).where(ExtractionRun.status.in_(stale_statuses))
        runs = session.exec(stmt).all()
        if not runs:
            return
        for run in runs:
            run.status = RunStatus.CANCELLED.value
            if not run.failure_reason:
                run.failure_reason = "Cancelled after server restart"
            session.add(run)
        session.commit()
        logger.info("Cancelled %s stale runs after restart", len(runs))
