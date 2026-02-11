import unittest
from datetime import timedelta

from sqlmodel import Session, select

from app.persistence.models import (
    BatchRun,
    BatchStatus,
    ExtractionRun,
    QueueJob,
    QueueJobStatus,
    RunStatus,
)
from app.services.queue_coordinator import QueueCoordinator
from app.services.runtime_maintenance import reconcile_orphan_run_states
from app.time_utils import utc_now
from queue_invariant_helpers import assert_queue_invariants
from support import ApiIntegrationTestCase


class QueueReliabilitySmokeTests(ApiIntegrationTestCase):
    def test_enqueue_and_claim_path(self) -> None:
        coordinator = QueueCoordinator()
        paper_id = self.create_paper(title="Smoke enqueue+claim")

        with Session(self.db_module.engine) as session:
            run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                model_name="mock-model",
                pdf_url="https://example.org/smoke-enqueue-claim.pdf",
            )
            result = coordinator.enqueue_new_run(session, run=run, title="Smoke")
            self.assertTrue(result.enqueued)

        with Session(self.db_module.engine) as session:
            claimed = coordinator.claim_next_job(session, worker_id="smoke-worker")
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.run_id, result.run_id)

        assert_queue_invariants(self, self.db_module.engine, context="smoke:enqueue+claim")

    def test_claim_heartbeat_active_vs_invalid_token(self) -> None:
        coordinator = QueueCoordinator()
        paper_id = self.create_paper(title="Smoke heartbeat")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/smoke-heartbeat.pdf",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="token-ok",
            claimed_by="worker-smoke",
            claimed_at=utc_now() - timedelta(minutes=2),
        )

        with Session(self.db_module.engine) as session:
            self.assertTrue(
                coordinator.heartbeat_claim(
                    session,
                    job_id=job_id,
                    claim_token="token-ok",
                )
            )
            self.assertFalse(
                coordinator.heartbeat_claim(
                    session,
                    job_id=job_id,
                    claim_token="token-wrong",
                )
            )

        assert_queue_invariants(self, self.db_module.engine, context="smoke:heartbeat")

    def test_batch_stop_cancels_claimed_and_releases_lock(self) -> None:
        batch_id = "smoke_batch_stop"
        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id=batch_id,
                label="Smoke Batch Stop",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.RUNNING.value,
                total_papers=2,
                completed=0,
                failed=0,
            )
            session.add(batch)
            session.commit()

        run = self.create_run_row(
            status=RunStatus.PROVIDER.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/smoke-stop-1.pdf",
        )
        self.create_run_row(
            status=RunStatus.STORED.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/smoke-stop-2.pdf",
        )
        self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="smoke-stop-token",
            claimed_by="smoke-worker",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=run.id, source_url=run.pdf_url)

        response = self.client.post("/api/baseline/batch-stop", json={"batch_id": batch_id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("cancelled_runs"), 1)
        self.assertEqual(payload.get("cancelled_jobs"), 1)

        assert_queue_invariants(self, self.db_module.engine, context="smoke:batch-stop")

    def test_stale_claim_recovery_requeues_and_fails(self) -> None:
        coordinator = QueueCoordinator()

        run_requeue = self.create_run_row(
            paper_id=self.create_paper(title="Smoke stale requeue"),
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/smoke-stale-requeue.pdf",
        )
        self.create_queue_job(
            run_id=run_requeue.id,
            pdf_url=run_requeue.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            attempt=0,
            claim_token="requeue-token",
            claimed_by="worker-a",
            claimed_at=utc_now() - timedelta(minutes=10),
        )
        self.create_source_lock(run_id=run_requeue.id, source_url=run_requeue.pdf_url)

        run_fail = self.create_run_row(
            paper_id=self.create_paper(title="Smoke stale fail"),
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/smoke-stale-fail.pdf",
        )
        self.create_queue_job(
            run_id=run_fail.id,
            pdf_url=run_fail.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            attempt=1,
            claim_token="fail-token",
            claimed_by="worker-b",
            claimed_at=utc_now() - timedelta(minutes=10),
        )
        self.create_source_lock(run_id=run_fail.id, source_url=run_fail.pdf_url)

        with Session(self.db_module.engine) as session:
            summary = coordinator.recover_stale_claims(
                session,
                stale_after_seconds=0,
                max_attempts=2,
            )
            self.assertEqual(summary.requeued, 1)
            self.assertEqual(summary.failed, 1)

            jobs = session.exec(select(QueueJob).order_by(QueueJob.id.asc())).all()
            self.assertEqual(jobs[0].status, QueueJobStatus.QUEUED.value)
            self.assertEqual(jobs[1].status, QueueJobStatus.FAILED.value)

        assert_queue_invariants(self, self.db_module.engine, context="smoke:stale-recovery")

    def test_reconcile_orphan_transient_run_without_job(self) -> None:
        orphan = self.create_run_row(
            paper_id=self.create_paper(title="Smoke orphan"),
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/smoke-orphan.pdf",
        )

        reconcile_orphan_run_states()

        with Session(self.db_module.engine) as session:
            refreshed = session.get(ExtractionRun, orphan.id)
            self.assertIsNotNone(refreshed)
            self.assertEqual(refreshed.status, RunStatus.CANCELLED.value)

        assert_queue_invariants(self, self.db_module.engine, context="smoke:reconcile-orphan")


if __name__ == "__main__":
    unittest.main()
