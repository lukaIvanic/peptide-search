import unittest

from sqlmodel import Session, select

from app.persistence.models import ExtractionRun, QueueJob, QueueJobStatus, RunStatus
from app.services.runtime_maintenance import reconcile_orphan_run_states
from support import ApiIntegrationTestCase


class RuntimeReconciliationTests(ApiIntegrationTestCase):
    def test_reconcile_orphan_run_states_keeps_recoverable_jobs_intact(self) -> None:
        queued_run = self.create_run_row(
            paper_id=None,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url="https://example.org/recoverable-queued.pdf",
        )
        claimed_run = self.create_run_row(
            paper_id=None,
            status=RunStatus.FETCHING.value,
            model_provider="mock",
            pdf_url="https://example.org/recoverable-claimed.pdf",
        )
        self.create_queue_job(
            run_id=queued_run.id,
            pdf_url=queued_run.pdf_url,
            status=QueueJobStatus.QUEUED,
        )
        self.create_queue_job(
            run_id=claimed_run.id,
            pdf_url=claimed_run.pdf_url,
            status=QueueJobStatus.CLAIMED,
        )

        reconcile_orphan_run_states()

        with Session(self.db_module.engine) as session:
            queued = session.get(ExtractionRun, queued_run.id)
            claimed = session.get(ExtractionRun, claimed_run.id)
            self.assertEqual(queued.status, RunStatus.QUEUED.value)
            self.assertEqual(claimed.status, RunStatus.FETCHING.value)

    def test_reconcile_orphan_run_states_cancels_transient_runs_without_queue_job(self) -> None:
        orphan = self.create_run_row(
            paper_id=None,
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            pdf_url="https://example.org/orphan-no-job.pdf",
        )

        reconcile_orphan_run_states()

        with Session(self.db_module.engine) as session:
            refreshed = session.get(ExtractionRun, orphan.id)
            self.assertEqual(refreshed.status, RunStatus.CANCELLED.value)
            self.assertIn("no queue job", (refreshed.failure_reason or "").lower())

    def test_reconcile_orphan_run_states_maps_terminal_queue_job_to_terminal_run(self) -> None:
        run = self.create_run_row(
            paper_id=None,
            status=RunStatus.VALIDATING.value,
            model_provider="mock",
            pdf_url="https://example.org/orphan-failed-job.pdf",
        )
        self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.FAILED,
        )

        reconcile_orphan_run_states()

        with Session(self.db_module.engine) as session:
            refreshed = session.get(ExtractionRun, run.id)
            job = session.exec(select(QueueJob).where(QueueJob.run_id == run.id)).first()
            self.assertEqual(job.status, QueueJobStatus.FAILED.value)
            self.assertEqual(refreshed.status, RunStatus.FAILED.value)
            self.assertTrue(refreshed.failure_reason)


if __name__ == "__main__":
    unittest.main()
