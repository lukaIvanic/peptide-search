"""Queue service backed by persistent queue jobs with SSE support."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

try:
    import psutil as _psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _psutil = None
    _PSUTIL_AVAILABLE = False


def _ram_mb() -> Optional[float]:
    """Return current process RSS memory in MB, or None if psutil unavailable."""
    if not _PSUTIL_AVAILABLE:
        return None
    try:
        return _psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return None


def _system_ram_available_mb() -> Optional[float]:
    """Return system-wide available RAM in MB, or None if psutil unavailable."""
    if not _PSUTIL_AVAILABLE:
        return None
    try:
        return _psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        return None

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
from .queue_errors import RunCancelledError

logger = logging.getLogger(__name__)
_RUN_TERMINAL_STATUSES = (RunStatus.STORED, RunStatus.FAILED, RunStatus.CANCELLED)
_RUN_TERMINAL_STATUS_VALUES = {status.value for status in _RUN_TERMINAL_STATUSES}


class ClaimLostError(RuntimeError):
    """Raised when a worker no longer owns the queue claim."""


@dataclass
class QueueItem:
    """Compatibility item for legacy callsites that still call queue.enqueue."""

    run_id: int
    paper_id: int
    pdf_url: str
    title: str
    pdf_urls: Optional[List[str]] = None
    provider: str = "openai"
    model: Optional[str] = None
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
        concurrency: int = 128,
        broadcaster: Optional[SSEBroadcaster] = None,
        coordinator: Optional[QueueCoordinator] = None,
    ):
        self.concurrency = concurrency
        self.broadcaster = broadcaster or SSEBroadcaster()
        self.coordinator = coordinator or QueueCoordinator()
        self._workers: List[asyncio.Task] = []
        self._recovery_task: Optional[asyncio.Task] = None
        self._active_runs: Dict[int, ClaimedJob] = {}
        self._running = False
        self._lock = asyncio.Lock()
        self._extract_callback: Optional[Callable[..., Any]] = None
        self.shard_count = int(getattr(settings, "QUEUE_SHARD_COUNT", 1) or 1)
        self.shard_id = int(getattr(settings, "QUEUE_SHARD_ID", 0) or 0)

    def set_extract_callback(self, callback: Callable[..., Any]) -> None:
        self._extract_callback = callback

    async def start(self) -> None:
        if self._running:
            return
        if self.concurrency > 0 and not self._extract_callback:
            raise RuntimeError("Queue extraction callback must be set before start().")
        self._running = True
        stale_after = self._claim_timeout_seconds()
        heartbeat_seconds = self._claim_heartbeat_seconds()
        if stale_after > 0 and heartbeat_seconds >= stale_after:
            logger.warning(
                "QUEUE_CLAIM_HEARTBEAT_SECONDS (%s) should be lower than "
                "QUEUE_CLAIM_TIMEOUT_SECONDS (%s) to avoid stale claim recovery races.",
                heartbeat_seconds,
                stale_after,
            )

        await self._recover_stale_claims_once()
        self._recovery_task = asyncio.create_task(self._stale_recovery_loop())

        if self.concurrency <= 0:
            logger.info("Queue started in passive mode (concurrency=%s)", self.concurrency)
            return

        for index in range(self.concurrency):
            task = asyncio.create_task(self._worker(index))
            self._workers.append(task)
        logger.info(
            "Queue started with %s workers (shard=%s/%s)",
            self.concurrency,
            self.shard_id,
            self.shard_count,
        )

    async def stop(self) -> None:
        self._running = False
        if self._recovery_task:
            self._recovery_task.cancel()
            await asyncio.gather(self._recovery_task, return_exceptions=True)
            self._recovery_task = None
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
                model=item.model,
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

    async def diagnostics(self) -> Dict[str, Any]:
        with session_scope() as session:
            snapshot = self.coordinator.queue_health_snapshot(
                session,
                stale_after_seconds=self._claim_timeout_seconds(),
            )
        async with self._lock:
            active_claims = len(self._active_runs)
        snapshot.update(
            {
                "running": self._running,
                "configured_concurrency": self.concurrency,
                "worker_tasks": len(self._workers),
                "active_claims": active_claims,
                "claim_timeout_seconds": self._claim_timeout_seconds(),
                "claim_heartbeat_seconds": self._claim_heartbeat_seconds(),
                "recovery_interval_seconds": int(
                    getattr(settings, "QUEUE_RECOVERY_INTERVAL_SECONDS", 30)
                ),
                "shard_count": self.shard_count,
                "shard_id": self.shard_id,
            }
        )
        return snapshot

    async def _worker(self, worker_id: int) -> None:
        worker_name = f"worker-{worker_id}"
        logger.info("%s started", worker_name)
        while self._running:
            try:
                claimed: Optional[ClaimedJob] = await asyncio.to_thread(
                    self._claim_next_job_sync,
                    worker_name,
                )
            except Exception as exc:
                logger.warning("%s claim error (will retry): %s", worker_name, exc)
                await asyncio.sleep(1.0)
                continue
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

        rss_before = _ram_mb()
        avail_before = _system_ram_available_mb()
        logger.info(
            "%s processing run %s | ram_rss=%.1fMB ram_avail=%.1fMB",
            worker_name, run_id,
            rss_before or 0, avail_before or 0,
        )
        heartbeat_stop = asyncio.Event()
        claim_lost = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._claim_heartbeat_loop(
                claimed=claimed,
                stop_event=heartbeat_stop,
                claim_lost=claim_lost,
                worker_name=worker_name,
            )
        )

        try:
            await self._ensure_claim_active_or_raise(
                claimed=claimed,
                claim_lost=claim_lost,
                worker_name=worker_name,
                stage="before-fetching",
            )
            await self._update_run_status(run_id, RunStatus.FETCHING)

            await self._ensure_claim_active_or_raise(
                claimed=claimed,
                claim_lost=claim_lost,
                worker_name=worker_name,
                stage="before-provider",
            )
            await self._update_run_status(run_id, RunStatus.PROVIDER)
            if not self._extract_callback:
                raise RuntimeError("No extraction callback configured")

            await self._extract_callback(
                run_id=run_id,
                paper_id=payload.paper_id,
                pdf_url=payload.pdf_url,
                pdf_urls=payload.pdf_urls,
                provider=payload.provider,
                model=payload.model,
                prompt_id=payload.prompt_id,
                prompt_version_id=payload.prompt_version_id,
                claim_job_id=claimed.id,
                claim_token=claimed.claim_token,
            )

            await self._ensure_claim_active_or_raise(
                claimed=claimed,
                claim_lost=claim_lost,
                worker_name=worker_name,
                stage="after-provider",
            )
            rss_after = _ram_mb()
            avail_after = _system_ram_available_mb()
            logger.info(
                "%s finished extraction run %s | ram_rss=%.1fMB (delta=%.1fMB) ram_avail=%.1fMB",
                worker_name, run_id,
                rss_after or 0,
                (rss_after or 0) - (rss_before or 0),
                avail_after or 0,
            )
            await self._update_run_status(run_id, RunStatus.VALIDATING)
            await self._update_run_status(run_id, RunStatus.STORED)

            await self._ensure_claim_active_or_raise(
                claimed=claimed,
                claim_lost=claim_lost,
                worker_name=worker_name,
                stage="before-finish",
            )
            await self._finish_claimed_job(claimed, QueueJobStatus.DONE)
            logger.info(
                "%s finished run %s successfully (attempt=%s)",
                worker_name,
                run_id,
                claimed.attempt,
            )
        except ClaimLostError as exc:
            logger.warning(
                "%s lost claim for run %s (attempt=%s): %s",
                worker_name,
                run_id,
                claimed.attempt,
                exc,
            )
        except RunCancelledError as exc:
            await self._update_run_status(run_id, RunStatus.CANCELLED, failure_reason=str(exc))
            await self._finish_claimed_job(claimed, QueueJobStatus.CANCELLED)
            logger.warning(
                "%s cancelled run %s (attempt=%s): %s",
                worker_name,
                run_id,
                claimed.attempt,
                exc,
            )
        except Exception as exc:
            error_msg = str(exc)
            await self._update_run_status(run_id, RunStatus.FAILED, failure_reason=error_msg)
            await self._finish_claimed_job(claimed, QueueJobStatus.FAILED)
            logger.error(
                "%s failed run %s (attempt=%s): %s",
                worker_name,
                run_id,
                claimed.attempt,
                error_msg,
            )
        finally:
            heartbeat_stop.set()
            with contextlib.suppress(Exception):
                await heartbeat_task

    async def _finish_claimed_job(self, claimed: ClaimedJob, status: QueueJobStatus) -> None:
        try:
            await asyncio.to_thread(self._finish_claimed_job_sync, claimed, status)
        except Exception:
            logger.exception(
                "Failed to finalize queue job id=%s run_id=%s status=%s",
                claimed.id,
                claimed.run_id,
                status.value,
            )
            raise

    def _finish_claimed_job_sync(self, claimed: ClaimedJob, status: QueueJobStatus) -> None:
        try:
            with session_scope() as session:
                self.coordinator.finish_job(
                    session,
                    job_id=claimed.id,
                    claim_token=claimed.claim_token,
                    status=status,
                )
        except Exception:
            raise

    async def _update_run_status(
        self,
        run_id: int,
        status: RunStatus,
        failure_reason: Optional[str] = None,
    ) -> None:
        payload = await asyncio.to_thread(
            self._update_run_status_sync,
            run_id,
            status,
            failure_reason,
        )
        if payload:
            await self.broadcaster.broadcast("run_status", payload)

    def _update_run_status_sync(
        self,
        run_id: int,
        status: RunStatus,
        failure_reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        with session_scope() as session:
            run = session.get(ExtractionRun, run_id)
            if not run:
                return None
            previous_status = run.status

            # Terminal statuses are sticky for queue workers.
            if previous_status in _RUN_TERMINAL_STATUS_VALUES and previous_status != status.value:
                return None
            # Respect explicit cancellation; do not allow worker status updates to resurrect the run.
            if run.status == RunStatus.CANCELLED.value and status != RunStatus.CANCELLED:
                return None
            run.status = status.value
            if failure_reason:
                run.failure_reason = failure_reason
            session.add(run)
            session.commit()

            entered_terminal = (
                status in _RUN_TERMINAL_STATUSES
                and previous_status not in _RUN_TERMINAL_STATUS_VALUES
            )
            if run.batch_id and entered_terminal:
                self._update_batch_counters(session, run, status)

            stmt = select(BaselineCaseRun.baseline_case_id).where(BaselineCaseRun.run_id == run_id)
            linked_case_ids = [row for row in session.exec(stmt).all()]
            if run.baseline_case_id and run.baseline_case_id not in linked_case_ids:
                linked_case_ids.append(run.baseline_case_id)

            return {
                "run_id": run_id,
                "paper_id": run.paper_id,
                "status": status.value,
                "failure_reason": failure_reason,
                "baseline_case_id": run.baseline_case_id,
                "baseline_case_ids": linked_case_ids,
                "baseline_dataset": run.baseline_dataset,
                "batch_id": run.batch_id,
            }

    async def _recover_stale_claims_once(self) -> None:
        stale_after = self._claim_timeout_seconds()
        max_attempts = int(getattr(settings, "QUEUE_MAX_ATTEMPTS", 3))
        recovery = await asyncio.to_thread(
            self._recover_stale_claims_sync,
            stale_after,
            max_attempts,
        )
        if recovery.requeued or recovery.failed:
            logger.info(
                "Recovered stale queue claims: requeued=%s failed=%s",
                recovery.requeued,
                recovery.failed,
            )

    def _recover_stale_claims_sync(self, stale_after: int, max_attempts: int):
        with session_scope() as session:
            return self.coordinator.recover_stale_claims(
                session,
                stale_after_seconds=stale_after,
                max_attempts=max_attempts,
            )

    async def _stale_recovery_loop(self) -> None:
        interval = max(5, int(getattr(settings, "QUEUE_RECOVERY_INTERVAL_SECONDS", 30)))
        while self._running:
            try:
                await asyncio.sleep(interval)
                if not self._running:
                    return
                await self._recover_stale_claims_once()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Stale claim recovery loop failed.")

    async def _claim_heartbeat_loop(
        self,
        *,
        claimed: ClaimedJob,
        stop_event: asyncio.Event,
        claim_lost: asyncio.Event,
        worker_name: str,
    ) -> None:
        interval = self._claim_heartbeat_seconds()
        while self._running and not stop_event.is_set() and not claim_lost.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass

            try:
                refreshed = await asyncio.to_thread(
                    self._heartbeat_claim_sync,
                    claimed.id,
                    claimed.claim_token,
                )
                if not refreshed:
                    claim_lost.set()
                    logger.warning(
                        "%s claim heartbeat rejected for run %s (job=%s, attempt=%s)",
                        worker_name,
                        claimed.run_id,
                        claimed.id,
                        claimed.attempt,
                    )
                    return
            except Exception:
                logger.exception(
                    "%s claim heartbeat failed for run %s (job=%s)",
                    worker_name,
                    claimed.run_id,
                    claimed.id,
                )

    def _heartbeat_claim_sync(self, job_id: int, claim_token: str) -> bool:
        with session_scope() as session:
            return self.coordinator.heartbeat_claim(
                session,
                job_id=job_id,
                claim_token=claim_token,
            )

    async def _ensure_claim_active_or_raise(
        self,
        *,
        claimed: ClaimedJob,
        claim_lost: asyncio.Event,
        worker_name: str,
        stage: str,
    ) -> None:
        if claim_lost.is_set():
            raise ClaimLostError("claim lease was lost")
        active = await asyncio.to_thread(
            self._is_claim_active_sync,
            claimed.id,
            claimed.claim_token,
        )
        if not active:
            claim_lost.set()
            raise ClaimLostError(f"claim inactive at stage={stage} worker={worker_name}")

    def _is_claim_active_sync(self, job_id: int, claim_token: str) -> bool:
        with session_scope() as session:
            return self.coordinator.is_claim_active(
                session,
                job_id=job_id,
                claim_token=claim_token,
            )

    def _claim_next_job_sync(self, worker_name: str) -> Optional[ClaimedJob]:
        with session_scope() as session:
            return self.coordinator.claim_next_job_for_shard(
                session,
                worker_id=worker_name,
                shard_count=self.shard_count,
                shard_id=self.shard_id,
            )

    @staticmethod
    def _claim_timeout_seconds() -> int:
        return max(0, int(getattr(settings, "QUEUE_CLAIM_TIMEOUT_SECONDS", 300)))

    @staticmethod
    def _claim_heartbeat_seconds() -> int:
        return max(1, int(getattr(settings, "QUEUE_CLAIM_HEARTBEAT_SECONDS", 30)))

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
        elif status in (RunStatus.FAILED, RunStatus.CANCELLED):
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
        concurrency = int(getattr(settings, "QUEUE_CONCURRENCY", 128))
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
