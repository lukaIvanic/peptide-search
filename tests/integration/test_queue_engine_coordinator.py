import unittest
from datetime import timedelta

from sqlmodel import Session, select

from app.persistence.models import ActiveSourceLock, ExtractionRun, QueueJob, QueueJobStatus, RunStatus
from app.services.queue_coordinator import DEFAULT_STALE_FAILURE_REASON, QueueCoordinator
from app.time_utils import utc_now
from support import ApiIntegrationTestCase


class QueueEngineCoordinatorTests(ApiIntegrationTestCase):
    def test_enqueue_new_run_deduplicates_source_and_persists_queue_job(self) -> None:
        coordinator = QueueCoordinator()
        source_url = "https://example.org/dedupe.pdf"

        paper_id_a = self.create_paper(title="Dedup A", url="https://example.org/a")
        with Session(self.db_module.engine) as session:
            run_a = ExtractionRun(
                paper_id=paper_id_a,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                pdf_url=source_url,
            )
            result_a = coordinator.enqueue_new_run(session, run=run_a, title="Dedup A")
            self.assertTrue(result_a.enqueued)
            first_run_id = result_a.run_id

        paper_id_b = self.create_paper(title="Dedup B", url="https://example.org/b")
        with Session(self.db_module.engine) as session:
            run_b = ExtractionRun(
                paper_id=paper_id_b,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                pdf_url=source_url,
            )
            result_b = coordinator.enqueue_new_run(session, run=run_b, title="Dedup B")
            self.assertFalse(result_b.enqueued)
            self.assertEqual(result_b.conflict_run_id, first_run_id)

        with Session(self.db_module.engine) as session:
            jobs = session.exec(select(QueueJob).where(QueueJob.source_fingerprint.is_not(None))).all()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].run_id, first_run_id)
            self.assertEqual(jobs[0].status, QueueJobStatus.QUEUED.value)

    def test_recover_stale_claims_requeues_then_fails_at_attempt_limit(self) -> None:
        coordinator = QueueCoordinator()
        source_url = "https://example.org/stale.pdf"
        paper_id = self.create_paper(title="Stale", url="https://example.org/stale")

        with Session(self.db_module.engine) as session:
            run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                pdf_url=source_url,
            )
            enqueue_result = coordinator.enqueue_new_run(session, run=run, title="Stale")
            self.assertTrue(enqueue_result.enqueued)
            run_id = enqueue_result.run_id

        with Session(self.db_module.engine) as session:
            claimed = coordinator.claim_next_job(session, worker_id="worker-1")
            self.assertIsNotNone(claimed)
            job = session.get(QueueJob, claimed.id)
            self.assertIsNotNone(job)
            job.claimed_at = utc_now() - timedelta(minutes=20)
            session.add(job)
            session.commit()

        with Session(self.db_module.engine) as session:
            summary = coordinator.recover_stale_claims(
                session,
                stale_after_seconds=60,
                max_attempts=3,
            )
            self.assertEqual(summary.requeued, 1)
            self.assertEqual(summary.failed, 0)

            job = session.exec(select(QueueJob).where(QueueJob.run_id == run_id)).first()
            self.assertIsNotNone(job)
            self.assertEqual(job.status, QueueJobStatus.QUEUED.value)
            self.assertEqual(job.attempt, 1)

        with Session(self.db_module.engine) as session:
            claimed_again = coordinator.claim_next_job(session, worker_id="worker-2")
            self.assertIsNotNone(claimed_again)
            job = session.get(QueueJob, claimed_again.id)
            job.claimed_at = utc_now() - timedelta(minutes=20)
            session.add(job)
            session.commit()

        with Session(self.db_module.engine) as session:
            summary = coordinator.recover_stale_claims(
                session,
                stale_after_seconds=60,
                max_attempts=2,
            )
            self.assertEqual(summary.requeued, 0)
            self.assertEqual(summary.failed, 1)

            job = session.exec(select(QueueJob).where(QueueJob.run_id == run_id)).first()
            self.assertEqual(job.status, QueueJobStatus.FAILED.value)

            run = session.get(ExtractionRun, run_id)
            self.assertEqual(run.status, RunStatus.FAILED.value)
            self.assertEqual(run.failure_reason, DEFAULT_STALE_FAILURE_REASON)

            lock = session.exec(
                select(ActiveSourceLock).where(ActiveSourceLock.run_id == run_id)
            ).first()
            self.assertIsNone(lock)


if __name__ == "__main__":
    unittest.main()
