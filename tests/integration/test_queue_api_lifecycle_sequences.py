import unittest

from sqlmodel import Session, select

from app.persistence.models import BatchRun, BatchStatus, ExtractionRun, QueueJob, QueueJobStatus, RunStatus
from queue_invariant_helpers import assert_queue_invariants
from support import ApiIntegrationTestCase


class QueueApiLifecycleSequenceTests(ApiIntegrationTestCase):
    def test_batch_control_sequence_preserves_invariants(self) -> None:
        batch_id = "sequence_batch_controls"
        paper_a = self.create_paper(title="Sequence Paper A")
        paper_b = self.create_paper(title="Sequence Paper B")

        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id=batch_id,
                label="Sequence Batch",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.RUNNING.value,
                total_papers=2,
                completed=0,
                failed=1,
            )
            session.add(batch)
            session.commit()

        running = self.create_run_row(
            paper_id=paper_a,
            status=RunStatus.PROVIDER.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/sequence-running.pdf",
        )
        failed = self.create_run_row(
            paper_id=paper_b,
            status=RunStatus.FAILED.value,
            batch_id=batch_id,
            baseline_dataset="self_assembly",
            model_provider="mock",
            model_name="mock-model",
            failure_reason="provider error: temp",
            pdf_url="https://example.org/sequence-failed.pdf",
        )
        self.create_queue_job(
            run_id=running.id,
            pdf_url=running.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="sequence-claim-token",
            claimed_by="sequence-worker",
        )
        self.create_source_lock(run_id=running.id, source_url=running.pdf_url)

        stop_first = self.client.post("/api/baseline/batch-stop", json={"batch_id": batch_id})
        self.assertEqual(stop_first.status_code, 200)
        stop_first_payload = stop_first.json()
        self.assertEqual(stop_first_payload.get("cancelled_runs"), 1)
        self.assertEqual(stop_first_payload.get("cancelled_jobs"), 1)
        assert_queue_invariants(self, self.db_module.engine, context="sequence:after-first-stop")

        # Idempotency check: repeating stop should never corrupt queue/run state.
        stop_second = self.client.post("/api/baseline/batch-stop", json={"batch_id": batch_id})
        self.assertEqual(stop_second.status_code, 200)
        stop_second_payload = stop_second.json()
        self.assertGreaterEqual(stop_second_payload.get("cancelled_runs", -1), 0)
        self.assertGreaterEqual(stop_second_payload.get("cancelled_jobs", -1), 0)
        assert_queue_invariants(self, self.db_module.engine, context="sequence:after-second-stop")

        retry = self.client.post(
            "/api/baseline/batch-retry",
            json={"batch_id": batch_id, "provider": "mock"},
        )
        self.assertEqual(retry.status_code, 200)
        retry_payload = retry.json()
        self.assertEqual(retry_payload.get("retried"), 1)
        assert_queue_invariants(self, self.db_module.engine, context="sequence:after-retry")

        with Session(self.db_module.engine) as session:
            retried = session.get(ExtractionRun, failed.id)
            self.assertIsNotNone(retried)
            self.assertEqual(retried.status, RunStatus.QUEUED.value)
            batch = session.exec(select(BatchRun).where(BatchRun.batch_id == batch_id)).first()
            self.assertIsNotNone(batch)
            self.assertEqual(batch.status, BatchStatus.RUNNING.value)

        delete = self.client.delete(f"/api/baseline/batch/{batch_id}")
        self.assertEqual(delete.status_code, 200)
        assert_queue_invariants(self, self.db_module.engine, context="sequence:after-delete")

        with Session(self.db_module.engine) as session:
            batch = session.exec(select(BatchRun).where(BatchRun.batch_id == batch_id)).first()
            self.assertIsNone(batch)
            run_count = session.exec(
                select(ExtractionRun).where(ExtractionRun.batch_id == batch_id)
            ).all()
            self.assertEqual(run_count, [])
            leftover_jobs = session.exec(
                select(QueueJob).where(QueueJob.run_id.in_([running.id, failed.id]))
            ).all()
            self.assertEqual(leftover_jobs, [])


if __name__ == "__main__":
    unittest.main()
