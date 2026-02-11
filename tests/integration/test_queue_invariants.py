import asyncio
import os
import unittest
from datetime import timedelta

from sqlmodel import Session, select

from app.persistence.models import BatchRun, BatchStatus, ExtractionRun, QueueJob, QueueJobStatus, RunStatus
from app.services.queue_coordinator import QueueCoordinator
from app.services.queue_service import ExtractionQueue
from app.time_utils import utc_now
from queue_invariant_helpers import assert_queue_invariants
from support import ApiIntegrationTestCase


def _deep_enabled() -> bool:
    return os.getenv("RUN_QUEUE_RELIABILITY_DEEP", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@unittest.skipUnless(
    _deep_enabled(),
    "Deep queue reliability tests are disabled. Set RUN_QUEUE_RELIABILITY_DEEP=1.",
)
class QueueInvariantDeterministicTests(ApiIntegrationTestCase):
    settings_overrides = {
        "QUEUE_CLAIM_HEARTBEAT_SECONDS": 1,
        "QUEUE_CLAIM_TIMEOUT_SECONDS": 5,
    }

    def _assert_invariants(self, context: str) -> None:
        assert_queue_invariants(self, self.db_module.engine, context=context)

    def _create_running_batch(self, batch_id: str, *, total_papers: int, failed: int = 0) -> None:
        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id=batch_id,
                label=f"Batch {batch_id}",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.RUNNING.value,
                total_papers=total_papers,
                completed=0,
                failed=failed,
            )
            session.add(batch)
            session.commit()

    def test_retry_failed_while_another_claim_exists(self) -> None:
        pdf_url = "https://example.org/invariant-retry-claimed.pdf"
        blocker = self.create_run_row(
            paper_id=self.create_paper(title="Invariant blocker"),
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url=pdf_url,
        )
        self.create_queue_job(
            run_id=blocker.id,
            pdf_url=pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="blocker-token",
            claimed_by="worker-blocker",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=blocker.id, source_url=pdf_url)

        failed_run = self.create_run_row(
            paper_id=self.create_paper(title="Invariant failed"),
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            model_name="mock-model",
            pdf_url=pdf_url,
        )

        response = self.client.post(f"/api/runs/{failed_run.id}/retry")
        self.assertEqual(response.status_code, 200)
        self.assertIn("already queued", response.json().get("message", "").lower())

        with Session(self.db_module.engine) as session:
            refreshed = session.get(ExtractionRun, failed_run.id)
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed.status, RunStatus.FAILED.value)

        self._assert_invariants("deterministic:retry-with-active-claim")

    def test_stop_batch_while_claimed(self) -> None:
        batch_id = "deterministic_batch_stop"
        self._create_running_batch(batch_id, total_papers=2)

        running_run = self.create_run_row(
            status=RunStatus.PROVIDER.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/deterministic-stop-1.pdf",
        )
        self.create_run_row(
            status=RunStatus.STORED.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/deterministic-stop-2.pdf",
        )
        self.create_queue_job(
            run_id=running_run.id,
            pdf_url=running_run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="det-stop-token",
            claimed_by="worker-det-stop",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=running_run.id, source_url=running_run.pdf_url)

        response = self.client.post("/api/baseline/batch-stop", json={"batch_id": batch_id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("cancelled_runs"), 1)
        self.assertEqual(payload.get("cancelled_jobs"), 1)

        self._assert_invariants("deterministic:batch-stop")

    def test_delete_batch_with_queued_and_claimed_runs(self) -> None:
        batch_id = "deterministic_batch_delete"
        self._create_running_batch(batch_id, total_papers=3, failed=1)

        queued_run = self.create_run_row(
            status=RunStatus.QUEUED.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/deterministic-delete-queued.pdf",
        )
        claimed_run = self.create_run_row(
            status=RunStatus.PROVIDER.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/deterministic-delete-claimed.pdf",
        )
        self.create_run_row(
            status=RunStatus.FAILED.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            failure_reason="provider error",
            pdf_url="https://example.org/deterministic-delete-failed.pdf",
        )

        self.create_queue_job(
            run_id=queued_run.id,
            pdf_url=queued_run.pdf_url,
            status=QueueJobStatus.QUEUED.value,
        )
        self.create_source_lock(run_id=queued_run.id, source_url=queued_run.pdf_url)

        self.create_queue_job(
            run_id=claimed_run.id,
            pdf_url=claimed_run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="det-delete-token",
            claimed_by="worker-det-delete",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=claimed_run.id, source_url=claimed_run.pdf_url)

        response = self.client.delete(f"/api/baseline/batch/{batch_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "ok")

        with Session(self.db_module.engine) as session:
            batch = session.exec(select(BatchRun).where(BatchRun.batch_id == batch_id)).first()
            self.assertIsNone(batch)

        self._assert_invariants("deterministic:batch-delete")

    def test_stale_recovery_with_mixed_attempts(self) -> None:
        coordinator = QueueCoordinator()

        requeue_run = self.create_run_row(
            paper_id=self.create_paper(title="Det stale requeue"),
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/deterministic-stale-requeue.pdf",
        )
        self.create_queue_job(
            run_id=requeue_run.id,
            pdf_url=requeue_run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            attempt=0,
            claim_token="det-requeue-token",
            claimed_by="worker-a",
            claimed_at=utc_now() - timedelta(minutes=5),
        )
        self.create_source_lock(run_id=requeue_run.id, source_url=requeue_run.pdf_url)

        fail_run = self.create_run_row(
            paper_id=self.create_paper(title="Det stale fail"),
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/deterministic-stale-fail.pdf",
        )
        self.create_queue_job(
            run_id=fail_run.id,
            pdf_url=fail_run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            attempt=1,
            claim_token="det-fail-token",
            claimed_by="worker-b",
            claimed_at=utc_now() - timedelta(minutes=5),
        )
        self.create_source_lock(run_id=fail_run.id, source_url=fail_run.pdf_url)

        with Session(self.db_module.engine) as session:
            summary = coordinator.recover_stale_claims(
                session,
                stale_after_seconds=0,
                max_attempts=2,
            )
            self.assertEqual(summary.requeued, 1)
            self.assertEqual(summary.failed, 1)

        self._assert_invariants("deterministic:stale-recovery")

    def test_terminal_status_is_monotonic_for_mixed_transitions(self) -> None:
        coordinator = QueueCoordinator()
        batch_id = "deterministic_terminal_monotonic"
        self._create_running_batch(batch_id, total_papers=1)

        run = self.create_run_row(
            paper_id=self.create_paper(title="Det terminal monotonic"),
            status=RunStatus.PROVIDER.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/deterministic-terminal.pdf",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="det-terminal-token",
            claimed_by="worker-det-terminal",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=run.id, source_url=run.pdf_url)

        queue = ExtractionQueue(concurrency=0)
        asyncio.run(queue._update_run_status(run.id, RunStatus.STORED))

        with Session(self.db_module.engine) as session:
            coordinator.finish_job(
                session,
                job_id=job_id,
                claim_token="det-terminal-token",
                status=QueueJobStatus.DONE,
            )

        asyncio.run(queue._update_run_status(run.id, RunStatus.PROVIDER))

        with Session(self.db_module.engine) as session:
            refreshed_run = session.get(ExtractionRun, run.id)
            refreshed_batch = session.exec(select(BatchRun).where(BatchRun.batch_id == batch_id)).first()
            self.assertIsNotNone(refreshed_run)
            self.assertIsNotNone(refreshed_batch)
            self.assertEqual(refreshed_run.status, RunStatus.STORED.value)
            self.assertEqual(refreshed_batch.completed, 1)
            self.assertEqual(refreshed_batch.failed, 0)
            self.assertEqual(refreshed_batch.status, BatchStatus.COMPLETED.value)

        self._assert_invariants("deterministic:terminal-monotonic")


if __name__ == "__main__":
    unittest.main()
