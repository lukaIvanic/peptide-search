"""Queue service for batch extraction with SSE support.

This module provides an in-process async queue for running extractions
with configurable concurrency. It broadcasts status updates via SSE.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

from ..config import settings
from ..persistence.models import Paper, ExtractionRun, RunStatus
from ..db import session_scope

logger = logging.getLogger(__name__)


@dataclass
class QueueItem:
    """An item in the extraction queue."""
    run_id: int
    paper_id: int
    pdf_url: str
    title: str
    provider: str = "openai"
    force: bool = False


@dataclass
class QueueStats:
    """Statistics for the queue."""
    total: int = 0
    queued: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0


class SSEBroadcaster:
    """Manages SSE connections and broadcasts events."""
    
    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
    
    async def subscribe(self) -> asyncio.Queue:
        """Subscribe to SSE events. Returns a queue to receive events."""
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
        logger.info(f"SSE subscriber added. Total: {len(self._subscribers)}")
        return queue
    
    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Unsubscribe from SSE events."""
        async with self._lock:
            self._subscribers.discard(queue)
        logger.info(f"SSE subscriber removed. Total: {len(self._subscribers)}")
    
    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcast an event to all subscribers."""
        message = {
            "event": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        async with self._lock:
            dead_queues = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    dead_queues.append(queue)
            
            for q in dead_queues:
                self._subscribers.discard(q)
        
        logger.debug(f"Broadcast {event_type}: {data.get('run_id', 'N/A')}")


class ExtractionQueue:
    """In-process queue for batch extraction with configurable concurrency."""
    
    def __init__(
        self,
        concurrency: int = 3,
        broadcaster: Optional[SSEBroadcaster] = None,
    ):
        self.concurrency = concurrency
        self.broadcaster = broadcaster or SSEBroadcaster()
        
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        self._active_runs: Dict[int, QueueItem] = {}
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._lock = asyncio.Lock()
        
        # Callback for actual extraction (set by extraction service)
        self._extract_callback: Optional[Callable] = None
    
    def set_extract_callback(self, callback: Callable) -> None:
        """Set the callback for running extraction."""
        self._extract_callback = callback
    
    async def start(self) -> None:
        """Start the queue workers."""
        if self._running:
            return
        
        self._running = True
        for i in range(self.concurrency):
            task = asyncio.create_task(self._worker(i))
            self._workers.append(task)
        
        logger.info(f"Queue started with {self.concurrency} workers")
    
    async def stop(self) -> None:
        """Stop the queue workers."""
        self._running = False
        
        for task in self._workers:
            task.cancel()
        
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        
        self._workers.clear()
        logger.info("Queue stopped")
    
    async def enqueue(self, item: QueueItem) -> None:
        """Add an item to the queue."""
        await self._queue.put(item)
        logger.info(f"Enqueued run {item.run_id} for paper {item.paper_id}")
    
    async def get_stats(self) -> QueueStats:
        """Get current queue statistics."""
        async with self._lock:
            return QueueStats(
                queued=self._queue.qsize(),
                processing=len(self._active_runs),
            )
    
    async def _worker(self, worker_id: int) -> None:
        """Worker coroutine that processes queue items."""
        logger.info(f"Worker {worker_id} started")
        
        while self._running:
            try:
                item = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            
            async with self._lock:
                self._active_runs[item.run_id] = item
            
            try:
                await self._process_item(item, worker_id)
            except Exception as e:
                logger.exception(f"Worker {worker_id} error processing run {item.run_id}: {e}")
            finally:
                async with self._lock:
                    self._active_runs.pop(item.run_id, None)
                self._queue.task_done()
        
        logger.info(f"Worker {worker_id} stopped")
    
    async def _process_item(self, item: QueueItem, worker_id: int) -> None:
        """Process a single queue item."""
        run_id = item.run_id
        
        logger.info(f"Worker {worker_id} processing run {run_id}")
        
        # Update status to FETCHING
        await self._update_run_status(run_id, RunStatus.FETCHING)
        
        try:
            # Update status to PROVIDER (calling LLM)
            await self._update_run_status(run_id, RunStatus.PROVIDER)
            
            if self._extract_callback:
                # Run the actual extraction
                result = await self._extract_callback(
                    run_id=run_id,
                    paper_id=item.paper_id,
                    pdf_url=item.pdf_url,
                    provider=item.provider,
                )
                
                # Update status to VALIDATING
                await self._update_run_status(run_id, RunStatus.VALIDATING)
                
                # Validation happens inside the callback, so if we get here it succeeded
                await self._update_run_status(run_id, RunStatus.STORED)
                logger.info(f"Run {run_id} completed successfully")
            else:
                raise RuntimeError("No extraction callback configured")
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Run {run_id} failed: {error_msg}")
            await self._update_run_status(run_id, RunStatus.FAILED, failure_reason=error_msg)
    
    async def _update_run_status(
        self,
        run_id: int,
        status: RunStatus,
        failure_reason: Optional[str] = None,
    ) -> None:
        """Update run status in database and broadcast SSE event."""
        with session_scope() as session:
            run = session.get(ExtractionRun, run_id)
            if run:
                run.status = status.value
                if failure_reason:
                    run.failure_reason = failure_reason
                session.add(run)
                session.commit()
                
                # Broadcast status update
                await self.broadcaster.broadcast("run_status", {
                    "run_id": run_id,
                    "paper_id": run.paper_id,
                    "status": status.value,
                    "failure_reason": failure_reason,
                })


# Global queue instance
_queue: Optional[ExtractionQueue] = None
_broadcaster: Optional[SSEBroadcaster] = None


def get_broadcaster() -> SSEBroadcaster:
    """Get the global SSE broadcaster."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = SSEBroadcaster()
    return _broadcaster


def get_queue() -> ExtractionQueue:
    """Get the global extraction queue."""
    global _queue, _broadcaster
    if _queue is None:
        _broadcaster = get_broadcaster()
        concurrency = int(getattr(settings, 'QUEUE_CONCURRENCY', 3))
        _queue = ExtractionQueue(concurrency=concurrency, broadcaster=_broadcaster)
    return _queue


async def start_queue() -> None:
    """Start the global queue."""
    queue = get_queue()
    await queue.start()


async def stop_queue() -> None:
    """Stop the global queue."""
    global _queue
    if _queue:
        await _queue.stop()
        _queue = None
