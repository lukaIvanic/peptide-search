"""Queue service backed by persistent queue jobs with SSE support."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from sqlmodel import select

from ..config import settings
from ..db import session_scope
from ..persistence.models import (
    BaselineCaseRun,
    BatchRun,
    BatchStatus,
    ExtractionRun,
    QueueJobStatus,
    RunStatus,
)
from ..time_utils import utc_now
from .queue_coordinator import ClaimedJob, QueueCoordinator

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    """Compatibility item for legacy callsites that still call queue.enqueue."""

    run_id: int
    paper_id: int
    pdf_url: str
    title: str
    pdf_urls: Optional[List[str]] = None
    provider: str = "openai"
    force: bool = False
    prompt_id: Optional[int] = None
    prompt_version_id: Optional[int] = None


@dataclass
class QueueStats:
    """Statistics for persistent queue state."""

    queued: int = 0
    processing: int = 0


class SSEBroadcaster:
    """Manages SSE connections and broadcasts events."""

    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
        logger.info("SSE subscriber added. Total: %s", len(self._subscribers))
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)
        logger.info("SSE subscriber removed. Total: %s", len(self._subscribers))

    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        message = {
            "event": event_type,
            "data": data,
            "timestamp": utc_now().isoformat() + "Z",
        }

        async with self._lock:
            dead_queues: list[asyncio.Queue] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    dead_queues.append(queue)
            for queue in dead_queues:
                self._subscribers.discard(queue)


class ExtractionQueue:
    """Persistent queue worker pool backed by queue_job + source lock tables."""

    def __init__(
        self,
        concurrency: int = 3,
        broadcaster: Optional[SSEBroadcaster] = None,
        coordinator: Optional[QueueCoordinator] = None,
    ):
        self.concurrency = concurrency
        self.broadcaster = broadcaster or SSEBroadcaster()
        self.coordinator = coordinator or QueueCoordinator()
        self._workers: List[asyncio.Task] = []
        self._active_runs: Dict[int, ClaimedJob] = {}
        self._running = False
        self._lock = asyncio.Lock()
        self._extract_callback: Optional[Callable[..., Any]] = None

    def set_extract_callback(self, callback: Callable[..., Any]) -> None:
        self._extract_callback = callback

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        stale_after = int(getattr(settings, "QUEUE_CLAIM_TIMEOUT_SECONDS", 300))
        max_attempts = int(getattr(settings, "QUEUE_MAX_ATTEMPTS", 3))
        with session_scope() as session:
            recovery = self.coordinator.recover_stale_claims(
                session,
                stale_after_seconds=stale_after,
                max_attempts=max_attempts,
            )
        if recovery.requeued or recovery.failed:
            logger.info(
                "Recovered stale queue claims: requeued=%s failed=%s",
                recovery.requeued,
                recovery.failed,
            )

        if self.concurrency <= 0:
            logger.info("Queue started in passive mode (concurrency=%s)", self.concurrency)
            return

        for index in range(self.concurrency):
            task = asyncio.create_task(self._worker(index))
            self._workers.append(task)
        logger.info("Queue started with %s workers", self.concurrency)

    async def stop(self) -> None:
        self._running = False
        for task in self._workers:
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        async with self._lock:
            self._active_runs.clear()
        logger.info("Queue stopped")

    async def is_url_pending(self, url: str) -> bool:
        if not url:
            return False
        with session_scope() as session:
            pending, _run_id = self.coordinator.has_active_lock_for_urls(
                session,
                pdf_url=url,
                pdf_urls=None,
            )
            return pending

    async def enqueue(self, item: QueueItem) -> bool:
        """Compatibility enqueue path (used by remaining legacy callsites)."""
        with session_scope() as session:
            run = session.get(ExtractionRun, item.run_id)
            if not run:
                return False
            result = self.coordinator.enqueue_existing_run(
                session,
                run=run,
                title=item.title,
                provider=item.provider,
                pdf_url=item.pdf_url,
                pdf_urls=item.pdf_urls,
                prompt_id=item.prompt_id,
                prompt_version_id=item.prompt_version_id,
            )
            return result.enqueued

    async def get_stats(self) -> QueueStats:
        with session_scope() as session:
            stats = self.coordinator.queue_stats(session)
            return QueueStats(queued=stats["queued"], processing=stats["processing"])

    async def _worker(self, worker_id: int) -> None:
        worker_name = f"worker-{worker_id}"
        logger.info("%s started", worker_name)
        while self._running:
            claimed: Optional[ClaimedJob] = None
            with session_scope() as session:
                claimed = self.coordinator.claim_next_job(session, worker_id=worker_name)
            if not claimed:
                await asyncio.sleep(0.4)
                continue

            async with self._lock:
                self._active_runs[claimed.run_id] = claimed
            try:
                await self._process_claimed_job(claimed, worker_name)
            except Exception as exc:
                logger.exception("%s unexpected error for run %s: %s", worker_name, claimed.run_id, exc)
            finally:
                async with self._lock:
                    self._active_runs.pop(claimed.run_id, None)
        logger.info("%s stopped", worker_name)

    async def _process_claimed_job(self, claimed: ClaimedJob, worker_name: str) -> None:
        run_id = claimed.run_id
        payload = claimed.payload

        logger.info("%s processing run %s", worker_name, run_id)
        await self._update_run_status(run_id, RunStatus.FETCHING)

        try:
            await self._update_run_status(run_id, RunStatus.PROVIDER)
            if not self._extract_callback:
                raise RuntimeError("No extraction callback configured")

            await self._extract_callback(
                run_id=run_id,
                paper_id=payload.paper_id,
                pdf_url=payload.pdf_url,
                pdf_urls=payload.pdf_urls,
                provider=payload.provider,
                prompt_id=payload.prompt_id,
                prompt_version_id=payload.prompt_version_id,
            )
            await self._update_run_status(run_id, RunStatus.VALIDATING)
            await self._update_run_status(run_id, RunStatus.STORED)

            with session_scope() as session:
                self.coordinator.finish_job(
                    session,
                    job_id=claimed.id,
                    claim_token=claimed.claim_token,
                    status=QueueJobStatus.DONE,
                )
        except Exception as exc:
            error_msg = str(exc)
            await self._update_run_status(run_id, RunStatus.FAILED, failure_reason=error_msg)
            with session_scope() as session:
                self.coordinator.finish_job(
                    session,
                    job_id=claimed.id,
                    claim_token=claimed.claim_token,
                    status=QueueJobStatus.FAILED,
                )

    async def _update_run_status(
        self,
        run_id: int,
        status: RunStatus,
        failure_reason: Optional[str] = None,
    ) -> None:
        with session_scope() as session:
            run = session.get(ExtractionRun, run_id)
            if not run:
                return
            run.status = status.value
            if failure_reason:
                run.failure_reason = failure_reason
            session.add(run)
            session.commit()

            if run.batch_id and status in (RunStatus.STORED, RunStatus.FAILED):
                self._update_batch_counters(session, run, status)

            stmt = select(BaselineCaseRun.baseline_case_id).where(BaselineCaseRun.run_id == run_id)
            linked_case_ids = [row for row in session.exec(stmt).all()]
            if run.baseline_case_id and run.baseline_case_id not in linked_case_ids:
                linked_case_ids.append(run.baseline_case_id)

            await self.broadcaster.broadcast(
                "run_status",
                {
                    "run_id": run_id,
                    "paper_id": run.paper_id,
                    "status": status.value,
                    "failure_reason": failure_reason,
                    "baseline_case_id": run.baseline_case_id,
                    "baseline_case_ids": linked_case_ids,
                    "baseline_dataset": run.baseline_dataset,
                    "batch_id": run.batch_id,
                },
            )

    def _update_batch_counters(self, session, run: ExtractionRun, status: RunStatus) -> None:
        stmt = select(BatchRun).where(BatchRun.batch_id == run.batch_id)
        batch = session.exec(stmt).first()
        if not batch:
            return

        if status == RunStatus.STORED:
            batch.completed += 1
            if run.input_tokens:
                batch.total_input_tokens += run.input_tokens
            if run.output_tokens:
                batch.total_output_tokens += run.output_tokens
            if run.extraction_time_ms:
                batch.total_time_ms += run.extraction_time_ms
            matched, expected = self._compute_run_matches(session, run)
            batch.matched_entities += matched
            batch.total_expected_entities += expected
        elif status == RunStatus.FAILED:
            batch.failed += 1

        if batch.completed + batch.failed >= batch.total_papers:
            if batch.failed == 0:
                batch.status = BatchStatus.COMPLETED.value
            elif batch.completed == 0:
                batch.status = BatchStatus.FAILED.value
            else:
                batch.status = BatchStatus.PARTIAL.value
            batch.completed_at = utc_now()

        session.add(batch)
        session.commit()

    @staticmethod
    def _normalize_sequence(seq: str) -> str:
        import re

        if not seq:
            return ""
        return re.sub(r"[^A-Za-z]", "", seq).upper()

    def _compute_run_matches(self, session, run: ExtractionRun) -> tuple[int, int]:
        from ..baseline.loader import list_cases

        stmt = select(BaselineCaseRun.baseline_case_id).where(BaselineCaseRun.run_id == run.id)
        linked_ids = list(session.exec(stmt).all())
        if run.baseline_case_id and run.baseline_case_id not in linked_ids:
            linked_ids.append(run.baseline_case_id)
        if not linked_ids:
            return 0, 0

        all_cases = list_cases()
        case_map = {case.get("id"): case for case in all_cases if case.get("id")}
        baseline_cases = [case_map[case_id] for case_id in linked_ids if case_id in case_map]
        if not baseline_cases:
            return 0, 0

        extracted_sequences: set[str] = set()
        if run.raw_json:
            try:
                raw = json.loads(run.raw_json)
                entities = raw.get("entities", []) if isinstance(raw, dict) else []
                for entity in entities:
                    if not isinstance(entity, dict):
                        continue
                    peptide = entity.get("peptide") or {}
                    seq = peptide.get("sequence_one_letter", "") if isinstance(peptide, dict) else ""
                    if seq:
                        extracted_sequences.add(self._normalize_sequence(seq))
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        matched = 0
        expected = len(baseline_cases)
        for case in baseline_cases:
            baseline_seq = case.get("sequence", "")
            if baseline_seq and self._normalize_sequence(baseline_seq) in extracted_sequences:
                matched += 1
        return matched, expected


_queue: Optional[ExtractionQueue] = None
_broadcaster: Optional[SSEBroadcaster] = None


def get_broadcaster() -> SSEBroadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = SSEBroadcaster()
    return _broadcaster


def get_queue() -> ExtractionQueue:
    global _queue, _broadcaster
    if _queue is None:
        _broadcaster = get_broadcaster()
        concurrency = int(getattr(settings, "QUEUE_CONCURRENCY", 3))
        _queue = ExtractionQueue(concurrency=concurrency, broadcaster=_broadcaster)
    return _queue


async def start_queue() -> None:
    queue = get_queue()
    await queue.start()


async def stop_queue() -> None:
    global _queue
    if _queue:
        await _queue.stop()
        _queue = None
