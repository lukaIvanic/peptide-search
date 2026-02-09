from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import secrets
from typing import Any, Optional

from sqlalchemy import delete, func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..persistence.models import ActiveSourceLock, ExtractionRun, QueueJob, QueueJobStatus, RunStatus
from ..time_utils import utc_now


DEFAULT_STALE_FAILURE_REASON = "Queue worker claim timed out repeatedly"


@dataclass
class EnqueuePayload:
    run_id: int
    paper_id: int
    pdf_url: str
    title: str
    provider: str
    pdf_urls: Optional[list[str]] = None
    prompt_id: Optional[int] = None
    prompt_version_id: Optional[int] = None


@dataclass
class QueueEnqueueResult:
    enqueued: bool
    run_id: int
    run_status: str
    message: str
    conflict_run_id: Optional[int] = None
    conflict_run_status: Optional[str] = None


@dataclass
class ClaimedJob:
    id: int
    run_id: int
    claim_token: str
    attempt: int
    payload: EnqueuePayload


@dataclass
class QueueRecoverySummary:
    requeued: int = 0
    failed: int = 0


class QueueCoordinator:
    """DB-backed queue orchestration (enqueue, claim, finish, stale recovery)."""

    @staticmethod
    def canonicalize_source_url(url: str) -> str:
        return url.strip()

    @classmethod
    def source_fingerprint(cls, url: str) -> str:
        canonical = cls.canonicalize_source_url(url)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def source_fingerprints(cls, pdf_url: str, pdf_urls: Optional[list[str]] = None) -> list[str]:
        urls: list[str] = []
        if pdf_urls:
            urls.extend([u for u in pdf_urls if u and u.strip()])
        if pdf_url and pdf_url.strip() and pdf_url not in urls:
            urls.insert(0, pdf_url)
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in urls:
            canonical = cls.canonicalize_source_url(raw)
            if not canonical:
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            normalized.append(canonical)
        return [cls.source_fingerprint(url) for url in normalized]

    @staticmethod
    def _lock_conflict_result(
        *,
        requested_run_id: int,
        lock: ActiveSourceLock,
        run: Optional[ExtractionRun],
    ) -> QueueEnqueueResult:
        return QueueEnqueueResult(
            enqueued=False,
            run_id=requested_run_id,
            run_status=run.status if run else RunStatus.QUEUED.value,
            message="Already queued",
            conflict_run_id=lock.run_id,
            conflict_run_status=run.status if run else None,
        )

    def enqueue_new_run(
        self,
        session: Session,
        *,
        run: ExtractionRun,
        title: str,
        pdf_urls: Optional[list[str]] = None,
    ) -> QueueEnqueueResult:
        run.status = RunStatus.QUEUED.value
        run.failure_reason = None

        primary_url = run.pdf_url or ""
        fingerprints = self.source_fingerprints(primary_url, pdf_urls)
        if not primary_url.strip() or not fingerprints:
            raise ValueError("Cannot enqueue without a source URL")

        conflict_lock = session.exec(
            select(ActiveSourceLock)
            .where(ActiveSourceLock.source_fingerprint.in_(fingerprints))
            .limit(1)
        ).first()
        if conflict_lock:
            conflict_run = session.get(ExtractionRun, conflict_lock.run_id)
            return self._lock_conflict_result(
                requested_run_id=run.id or 0,
                lock=conflict_lock,
                run=conflict_run,
            )

        try:
            session.add(run)
            session.flush()
            payload = EnqueuePayload(
                run_id=run.id,
                paper_id=run.paper_id or 0,
                pdf_url=primary_url,
                pdf_urls=pdf_urls,
                title=title,
                provider=run.model_provider or "openai",
                prompt_id=run.prompt_id,
                prompt_version_id=run.prompt_version_id,
            )
            self._insert_locks_and_job(session, payload=payload, fingerprints=fingerprints)
            session.commit()
            session.refresh(run)
            return QueueEnqueueResult(
                enqueued=True,
                run_id=run.id,
                run_status=run.status,
                message="Queued",
            )
        except IntegrityError:
            session.rollback()
            # Another worker won a race on the lock PK.
            conflict_lock = session.exec(
                select(ActiveSourceLock)
                .where(ActiveSourceLock.source_fingerprint.in_(fingerprints))
                .limit(1)
            ).first()
            if not conflict_lock:
                raise
            conflict_run = session.get(ExtractionRun, conflict_lock.run_id)
            return self._lock_conflict_result(
                requested_run_id=run.id or 0,
                lock=conflict_lock,
                run=conflict_run,
            )

    def enqueue_existing_run(
        self,
        session: Session,
        *,
        run: ExtractionRun,
        title: str,
        provider: Optional[str] = None,
        pdf_url: Optional[str] = None,
        pdf_urls: Optional[list[str]] = None,
        prompt_id: Optional[int] = None,
        prompt_version_id: Optional[int] = None,
    ) -> QueueEnqueueResult:
        if not run.id:
            raise ValueError("Existing run must have an ID")

        effective_pdf_url = (pdf_url or run.pdf_url or "").strip()
        fingerprints = self.source_fingerprints(effective_pdf_url, pdf_urls)
        if not effective_pdf_url or not fingerprints:
            raise ValueError("Cannot enqueue without a source URL")

        conflict_lock = session.exec(
            select(ActiveSourceLock)
            .where(ActiveSourceLock.source_fingerprint.in_(fingerprints))
            .limit(1)
        ).first()
        if conflict_lock and conflict_lock.run_id != run.id:
            conflict_run = session.get(ExtractionRun, conflict_lock.run_id)
            return self._lock_conflict_result(
                requested_run_id=run.id,
                lock=conflict_lock,
                run=conflict_run,
            )

        existing_job = session.exec(select(QueueJob).where(QueueJob.run_id == run.id)).first()
        if existing_job and existing_job.status in {
            QueueJobStatus.QUEUED.value,
            QueueJobStatus.CLAIMED.value,
        }:
            return QueueEnqueueResult(
                enqueued=False,
                run_id=run.id,
                run_status=run.status,
                message="Already queued",
                conflict_run_id=run.id,
                conflict_run_status=run.status,
            )

        use_provider = provider or run.model_provider or "openai"
        use_prompt_id = prompt_id if prompt_id is not None else run.prompt_id
        use_prompt_version_id = (
            prompt_version_id if prompt_version_id is not None else run.prompt_version_id
        )

        run.status = RunStatus.QUEUED.value
        run.failure_reason = None
        run.model_provider = use_provider
        run.pdf_url = effective_pdf_url
        run.prompt_id = use_prompt_id
        run.prompt_version_id = use_prompt_version_id

        payload = EnqueuePayload(
            run_id=run.id,
            paper_id=run.paper_id or 0,
            pdf_url=effective_pdf_url,
            pdf_urls=pdf_urls,
            title=title,
            provider=use_provider,
            prompt_id=use_prompt_id,
            prompt_version_id=use_prompt_version_id,
        )

        try:
            session.add(run)
            if existing_job:
                now = utc_now()
                existing_job.status = QueueJobStatus.QUEUED.value
                existing_job.claimed_by = None
                existing_job.claim_token = None
                existing_job.claimed_at = None
                existing_job.finished_at = None
                existing_job.available_at = now
                existing_job.updated_at = now
                existing_job.source_fingerprint = fingerprints[0]
                existing_job.payload_json = self._dump_payload(payload)
                session.add(existing_job)
            else:
                self._insert_locks_and_job(session, payload=payload, fingerprints=fingerprints)
            session.commit()
            return QueueEnqueueResult(
                enqueued=True,
                run_id=run.id,
                run_status=run.status,
                message="Queued",
            )
        except IntegrityError:
            session.rollback()
            conflict_lock = session.exec(
                select(ActiveSourceLock)
                .where(ActiveSourceLock.source_fingerprint.in_(fingerprints))
                .limit(1)
            ).first()
            if not conflict_lock:
                raise
            conflict_run = session.get(ExtractionRun, conflict_lock.run_id)
            return self._lock_conflict_result(
                requested_run_id=run.id,
                lock=conflict_lock,
                run=conflict_run,
            )

    def claim_next_job(self, session: Session, *, worker_id: str) -> Optional[ClaimedJob]:
        now = utc_now()
        for _ in range(3):
            job = session.exec(
                select(QueueJob)
                .where(QueueJob.status == QueueJobStatus.QUEUED.value)
                .where(QueueJob.available_at <= now)
                .order_by(QueueJob.available_at.asc(), QueueJob.id.asc())
                .limit(1)
            ).first()
            if not job:
                return None

            token = secrets.token_hex(16)
            result = session.exec(
                update(QueueJob)
                .where(QueueJob.id == job.id)
                .where(QueueJob.status == QueueJobStatus.QUEUED.value)
                .values(
                    status=QueueJobStatus.CLAIMED.value,
                    claimed_by=worker_id,
                    claim_token=token,
                    claimed_at=now,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                continue
            session.commit()
            refreshed = session.get(QueueJob, job.id)
            if not refreshed:
                return None
            payload = self._load_payload(refreshed.payload_json)
            return ClaimedJob(
                id=refreshed.id,
                run_id=refreshed.run_id,
                claim_token=token,
                attempt=refreshed.attempt,
                payload=payload,
            )
        return None

    def finish_job(
        self,
        session: Session,
        *,
        job_id: int,
        claim_token: str,
        status: QueueJobStatus,
    ) -> None:
        job = session.get(QueueJob, job_id)
        if not job:
            return
        if job.claim_token != claim_token:
            return

        now = utc_now()
        job.status = status.value
        job.finished_at = now
        job.updated_at = now
        job.claimed_by = None
        job.claim_token = None
        job.claimed_at = None
        session.add(job)

        if status in {
            QueueJobStatus.DONE,
            QueueJobStatus.FAILED,
            QueueJobStatus.CANCELLED,
        }:
            session.exec(delete(ActiveSourceLock).where(ActiveSourceLock.run_id == job.run_id))

        session.commit()

    def recover_stale_claims(
        self,
        session: Session,
        *,
        stale_after_seconds: int,
        max_attempts: int,
    ) -> QueueRecoverySummary:
        now = utc_now()
        cutoff = now
        if stale_after_seconds > 0:
            from datetime import timedelta

            cutoff = now - timedelta(seconds=stale_after_seconds)

        stale_jobs = session.exec(
            select(QueueJob)
            .where(QueueJob.status == QueueJobStatus.CLAIMED.value)
            .where(QueueJob.claimed_at.is_not(None))
            .where(QueueJob.claimed_at <= cutoff)
        ).all()

        summary = QueueRecoverySummary()
        for job in stale_jobs:
            next_attempt = (job.attempt or 0) + 1
            job.attempt = next_attempt
            job.updated_at = now
            job.claimed_by = None
            job.claim_token = None
            job.claimed_at = None

            run = session.get(ExtractionRun, job.run_id)
            if next_attempt >= max_attempts:
                job.status = QueueJobStatus.FAILED.value
                job.finished_at = now
                if run:
                    run.status = RunStatus.FAILED.value
                    if not run.failure_reason:
                        run.failure_reason = DEFAULT_STALE_FAILURE_REASON
                    session.add(run)
                session.exec(delete(ActiveSourceLock).where(ActiveSourceLock.run_id == job.run_id))
                summary.failed += 1
            else:
                job.status = QueueJobStatus.QUEUED.value
                job.available_at = now
                job.finished_at = None
                summary.requeued += 1
            session.add(job)

        if stale_jobs:
            session.commit()

        return summary

    def queue_stats(self, session: Session) -> dict[str, int]:
        queued = session.exec(
            select(func.count(QueueJob.id)).where(QueueJob.status == QueueJobStatus.QUEUED.value)
        ).one()
        processing = session.exec(
            select(func.count(QueueJob.id)).where(QueueJob.status == QueueJobStatus.CLAIMED.value)
        ).one()
        return {"queued": int(queued or 0), "processing": int(processing or 0)}

    @classmethod
    def has_active_lock_for_urls(
        cls,
        session: Session,
        *,
        pdf_url: Optional[str],
        pdf_urls: Optional[list[str]] = None,
    ) -> tuple[bool, Optional[int]]:
        if not pdf_url and not pdf_urls:
            return False, None
        if not (pdf_url or "").strip() and not pdf_urls:
            return False, None
        fingerprints = cls.source_fingerprints(pdf_url or "", pdf_urls)
        if not fingerprints:
            return False, None
        lock = session.exec(
            select(ActiveSourceLock)
            .where(ActiveSourceLock.source_fingerprint.in_(fingerprints))
            .limit(1)
        ).first()
        return (lock is not None), (lock.run_id if lock else None)

    @staticmethod
    def _dump_payload(payload: EnqueuePayload) -> str:
        return json.dumps(
            {
                "run_id": payload.run_id,
                "paper_id": payload.paper_id,
                "pdf_url": payload.pdf_url,
                "pdf_urls": payload.pdf_urls,
                "title": payload.title,
                "provider": payload.provider,
                "prompt_id": payload.prompt_id,
                "prompt_version_id": payload.prompt_version_id,
            }
        )

    @staticmethod
    def _load_payload(raw: Optional[str]) -> EnqueuePayload:
        data: dict[str, Any] = {}
        if raw:
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
        return EnqueuePayload(
            run_id=int(data.get("run_id") or 0),
            paper_id=int(data.get("paper_id") or 0),
            pdf_url=str(data.get("pdf_url") or ""),
            pdf_urls=data.get("pdf_urls") if isinstance(data.get("pdf_urls"), list) else None,
            title=str(data.get("title") or ""),
            provider=str(data.get("provider") or "openai"),
            prompt_id=data.get("prompt_id"),
            prompt_version_id=data.get("prompt_version_id"),
        )

    def _insert_locks_and_job(
        self,
        session: Session,
        *,
        payload: EnqueuePayload,
        fingerprints: list[str],
    ) -> None:
        now = utc_now()
        for fingerprint in fingerprints:
            session.add(
                ActiveSourceLock(
                    source_fingerprint=fingerprint,
                    run_id=payload.run_id,
                    created_at=now,
                )
            )
        job = QueueJob(
            run_id=payload.run_id,
            source_fingerprint=fingerprints[0],
            status=QueueJobStatus.QUEUED.value,
            claimed_by=None,
            claim_token=None,
            attempt=0,
            available_at=now,
            claimed_at=None,
            finished_at=None,
            payload_json=self._dump_payload(payload),
            created_at=now,
            updated_at=now,
        )
        session.add(job)
