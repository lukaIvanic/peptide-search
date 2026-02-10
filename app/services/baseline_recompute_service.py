from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import select

from ..db import session_scope
from ..persistence.models import BaselineCaseRun, BatchRun, BatchStatus, ExtractionRun, RunStatus
from ..services.baseline_store import BaselineStore
from ..services.queue_service import get_broadcaster
from ..services.serializers import iso_z
from ..time_utils import utc_now

logger = logging.getLogger(__name__)


@dataclass
class RecomputeState:
    running: bool = False
    queued: bool = False
    last_started_at: Optional[datetime] = None
    last_finished_at: Optional[datetime] = None


_state = RecomputeState()
_state_lock = asyncio.Lock()


def _normalize_sequence(seq: Optional[str]) -> str:
    if not seq:
        return ""
    return re.sub(r"[^A-Za-z]", "", seq).upper()


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


async def mark_batches_stale_and_trigger(*, dataset: Optional[str] = None) -> None:
    with session_scope() as session:
        stmt = select(BatchRun)
        if dataset:
            stmt = stmt.where(BatchRun.dataset == dataset)
        batches = session.exec(stmt).all()
        for batch in batches:
            batch.metrics_stale = True
            session.add(batch)
    await _schedule_recompute()


def recompute_batches_now(*, dataset: Optional[str] = None) -> int:
    """Synchronously recompute metrics for batches.

    Intended for maintenance/admin flows that must return fully consistent
    batch counters immediately (for example baseline reset).
    """
    with session_scope() as session:
        stmt = select(BatchRun)
        if dataset:
            stmt = stmt.where(BatchRun.dataset == dataset)
        batch_ids = [batch.batch_id for batch in session.exec(stmt).all()]

    for batch_id in batch_ids:
        _recompute_batch(batch_id)
    return len(batch_ids)


async def _schedule_recompute() -> None:
    async with _state_lock:
        if _state.running:
            _state.queued = True
            return
        _state.running = True
        _state.queued = False
        _state.last_started_at = utc_now()

    loop = asyncio.get_running_loop()
    loop.create_task(_run_recompute())


async def _run_recompute() -> None:
    broadcaster = get_broadcaster()
    try:
        await broadcaster.broadcast(
            "baseline_recompute_started",
            {
                "started_at": iso_z(_state.last_started_at),
            },
        )

        processed = 0
        while True:
            with session_scope() as session:
                stale_batches = session.exec(
                    select(BatchRun)
                    .where(BatchRun.metrics_stale == True)  # noqa: E712
                    .order_by(BatchRun.created_at.asc())
                    .limit(20)
                ).all()
                batch_ids = [batch.batch_id for batch in stale_batches]

            if not batch_ids:
                break

            for batch_id in batch_ids:
                _recompute_batch(batch_id)
                processed += 1
                await broadcaster.broadcast(
                    "baseline_recompute_progress",
                    {
                        "batch_id": batch_id,
                        "processed": processed,
                    },
                )

        _state.last_finished_at = utc_now()
        await broadcaster.broadcast(
            "baseline_recompute_finished",
            {
                "processed": processed,
                "finished_at": iso_z(_state.last_finished_at),
            },
        )
    except Exception as exc:
        logger.exception("Baseline recompute failed: %s", exc)
        _state.last_finished_at = utc_now()
        await broadcaster.broadcast(
            "baseline_recompute_finished",
            {
                "processed": 0,
                "error": str(exc),
                "finished_at": iso_z(_state.last_finished_at),
            },
        )
    finally:
        rerun = False
        async with _state_lock:
            rerun = _state.queued
            _state.running = False
            _state.queued = False
        if rerun:
            await _schedule_recompute()


def _recompute_batch(batch_id: str) -> None:
    with session_scope() as session:
        batch = session.exec(select(BatchRun).where(BatchRun.batch_id == batch_id)).first()
        if not batch:
            return

        store = BaselineStore(session)
        cases = store.list_cases(batch.dataset)
        groups: Dict[str, List[dict]] = {}
        for case in cases:
            paper_key = case.get("paper_key") or f"case:{case.get('id')}"
            groups.setdefault(paper_key, []).append(case)

        total_papers = len(groups)
        completed = 0
        failed = 0
        matched_entities = 0
        total_expected_entities = 0

        for group_cases in groups.values():
            case_ids = [case["id"] for case in group_cases if case.get("id")]
            if not case_ids:
                continue

            run = session.exec(
                select(ExtractionRun)
                .join(BaselineCaseRun, BaselineCaseRun.run_id == ExtractionRun.id)
                .where(BaselineCaseRun.baseline_case_id.in_(case_ids))
                .where(ExtractionRun.batch_id == batch_id)
                .order_by(ExtractionRun.created_at.desc())
                .limit(1)
            ).first()
            if not run:
                continue

            if run.status == RunStatus.STORED.value:
                completed += 1
                extracted = _extract_sequences(run.raw_json)
                expected = 0
                matched = 0
                for case in group_cases:
                    sequence = _normalize_sequence(case.get("sequence"))
                    if not sequence:
                        continue
                    expected += 1
                    if sequence in extracted:
                        matched += 1
                matched_entities += matched
                total_expected_entities += expected
            elif run.status in {RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
                failed += 1

        batch.total_papers = total_papers
        batch.completed = completed
        batch.failed = failed
        batch.matched_entities = matched_entities
        batch.total_expected_entities = total_expected_entities

        if total_papers == 0:
            batch.status = BatchStatus.COMPLETED.value
            batch.completed_at = utc_now()
        elif completed + failed >= total_papers:
            if failed == 0:
                batch.status = BatchStatus.COMPLETED.value
            elif completed == 0:
                batch.status = BatchStatus.FAILED.value
            else:
                batch.status = BatchStatus.PARTIAL.value
            batch.completed_at = utc_now()
        else:
            batch.status = BatchStatus.RUNNING.value
            batch.completed_at = None

        batch.metrics_stale = False
        session.add(batch)


def get_recompute_status() -> Dict[str, object]:
    with session_scope() as session:
        stale_batches = session.exec(
            select(BatchRun).where(BatchRun.metrics_stale == True)  # noqa: E712
        ).all()
    return {
        "running": _state.running,
        "queued": _state.queued,
        "stale_batches": len(stale_batches),
        "processing_batches": 1 if _state.running else 0,
        "last_started_at": iso_z(_state.last_started_at),
        "last_finished_at": iso_z(_state.last_finished_at),
    }
