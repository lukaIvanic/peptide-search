import unittest
from datetime import timedelta

from sqlmodel import Session, select

from app.persistence.models import ActiveSourceLock, ExtractionRun, QueueJob, QueueJobStatus, RunStatus
from app.services.queue_coordinator import DEFAULT_STALE_FAILURE_REASON, QueueCoordinator
from app.time_utils import utc_now
from support import ApiIntegrationTestCase


class QueueEngineCoordinatorTests(ApiIntegrationTestCase):
    def test_enqueue_new_run_rejects_blank_source_url(self) -> None:
        coordinator = QueueCoordinator()
        paper_id = self.create_paper(title="Blank source")
        with Session(self.db_module.engine) as session:
            run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                pdf_url="   ",
            )
            with self.assertRaises(ValueError):
                coordinator.enqueue_new_run(session, run=run, title="Blank source")

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

    def test_enqueue_new_run_deduplicates_across_pdf_url_and_pdf_urls(self) -> None:
        coordinator = QueueCoordinator()
        paper_id_a = self.create_paper(title="Multi A", url="https://example.org/multi-a")
        with Session(self.db_module.engine) as session:
            run_a = ExtractionRun(
                paper_id=paper_id_a,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                pdf_url="https://example.org/main.pdf",
            )
            result_a = coordinator.enqueue_new_run(
                session,
                run=run_a,
                title="Multi A",
                pdf_urls=[" https://example.org/main.pdf ", "https://example.org/supp.pdf"],
            )
            self.assertTrue(result_a.enqueued)
            run_a_id = result_a.run_id

        paper_id_b = self.create_paper(title="Multi B", url="https://example.org/multi-b")
        with Session(self.db_module.engine) as session:
            run_b = ExtractionRun(
                paper_id=paper_id_b,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                pdf_url="https://example.org/supp.pdf",
            )
            result_b = coordinator.enqueue_new_run(session, run=run_b, title="Multi B")
            self.assertFalse(result_b.enqueued)
            self.assertEqual(result_b.conflict_run_id, run_a_id)

    def test_enqueue_new_run_returns_conflict_metadata_for_existing_lock(self) -> None:
        coordinator = QueueCoordinator()
        source_url = "https://example.org/locked.pdf"
        locked_paper_id = self.create_paper(title="Locked", url="https://example.org/locked")
        locked_run = self.create_run_row(
            paper_id=locked_paper_id,
            status=RunStatus.FETCHING.value,
            model_provider="mock",
            pdf_url=source_url,
        )
        self.create_source_lock(run_id=locked_run.id, source_url=source_url)

        paper_id = self.create_paper(title="Contender", url="https://example.org/contender")
        with Session(self.db_module.engine) as session:
            contender = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                pdf_url=source_url,
            )
            result = coordinator.enqueue_new_run(session, run=contender, title="Contender")
            self.assertFalse(result.enqueued)
            self.assertEqual(result.conflict_run_id, locked_run.id)
            self.assertEqual(result.conflict_run_status, RunStatus.FETCHING.value)

    def test_enqueue_existing_run_returns_already_queued_for_claimed_job(self) -> None:
        coordinator = QueueCoordinator()
        source_url = "https://example.org/claimed.pdf"
        paper_id = self.create_paper(title="Claimed")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            pdf_url=source_url,
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=source_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="token-1",
            claimed_by="worker-1",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=run.id, source_url=source_url)

        with Session(self.db_module.engine) as session:
            run_row = session.get(ExtractionRun, run.id)
            result = coordinator.enqueue_existing_run(
                session,
                run=run_row,
                title="Claimed",
                provider="mock",
                pdf_url=source_url,
            )
            self.assertFalse(result.enqueued)
            self.assertEqual(result.conflict_run_id, run.id)
            self.assertEqual(result.message, "Already queued")

            job = session.get(QueueJob, job_id)
            self.assertEqual(job.status, QueueJobStatus.CLAIMED.value)
            self.assertEqual(job.claim_token, "token-1")

    def test_enqueue_existing_run_requeues_failed_job_and_resets_claim_fields(self) -> None:
        coordinator = QueueCoordinator()
        source_url = "https://example.org/requeue-failed.pdf"
        paper_id = self.create_paper(title="Requeue failed")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider timeout",
            model_provider="mock",
            pdf_url=source_url,
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=source_url,
            status=QueueJobStatus.FAILED.value,
            attempt=2,
            claim_token="old-token",
            claimed_by="worker-old",
            claimed_at=utc_now() - timedelta(minutes=5),
            finished_at=utc_now() - timedelta(minutes=4),
        )
        self.create_source_lock(run_id=run.id, source_url=source_url)

        with Session(self.db_module.engine) as session:
            run_row = session.get(ExtractionRun, run.id)
            result = coordinator.enqueue_existing_run(
                session,
                run=run_row,
                title="Requeue failed",
                provider="openai-mini",
                pdf_url=source_url,
            )
            self.assertTrue(result.enqueued)

            refreshed_run = session.get(ExtractionRun, run.id)
            self.assertEqual(refreshed_run.status, RunStatus.QUEUED.value)
            self.assertIsNone(refreshed_run.failure_reason)
            self.assertEqual(refreshed_run.model_provider, "openai-mini")

            job = session.get(QueueJob, job_id)
            self.assertEqual(job.status, QueueJobStatus.QUEUED.value)
            self.assertIsNone(job.claim_token)
            self.assertIsNone(job.claimed_by)
            self.assertIsNone(job.claimed_at)
            self.assertIsNone(job.finished_at)
            self.assertEqual(job.attempt, 2)

    def test_enqueue_existing_run_updates_locks_when_source_changes(self) -> None:
        coordinator = QueueCoordinator()
        old_url = "https://example.org/old.pdf"
        new_url = "https://example.org/new.pdf"
        new_supp = "https://example.org/new-si.pdf"
        paper_id = self.create_paper(title="Lock update")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider timeout",
            model_provider="mock",
            pdf_url=old_url,
        )
        self.create_queue_job(
            run_id=run.id,
            pdf_url=old_url,
            status=QueueJobStatus.FAILED.value,
        )
        old_fp = self.create_source_lock(run_id=run.id, source_url=old_url)

        with Session(self.db_module.engine) as session:
            run_row = session.get(ExtractionRun, run.id)
            result = coordinator.enqueue_existing_run(
                session,
                run=run_row,
                title="Lock update",
                provider="mock",
                pdf_url=new_url,
                pdf_urls=[new_url, f" {new_supp} "],
            )
            self.assertTrue(result.enqueued)

            fingerprints = set(
                session.exec(
                    select(ActiveSourceLock.source_fingerprint).where(ActiveSourceLock.run_id == run.id)
                ).all()
            )
            self.assertNotIn(old_fp, fingerprints)
            self.assertIn(QueueCoordinator.source_fingerprint(new_url), fingerprints)
            self.assertIn(QueueCoordinator.source_fingerprint(new_supp), fingerprints)

    def test_claim_next_job_respects_available_at_order(self) -> None:
        coordinator = QueueCoordinator()
        paper_a = self.create_paper(title="Future")
        run_a = self.create_run_row(
            paper_id=paper_a,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url="https://example.org/future.pdf",
        )
        self.create_queue_job(
            run_id=run_a.id,
            pdf_url=run_a.pdf_url,
            status=QueueJobStatus.QUEUED.value,
            available_at=utc_now() + timedelta(minutes=2),
        )

        paper_b = self.create_paper(title="Now")
        run_b = self.create_run_row(
            paper_id=paper_b,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url="https://example.org/now.pdf",
        )
        self.create_queue_job(
            run_id=run_b.id,
            pdf_url=run_b.pdf_url,
            status=QueueJobStatus.QUEUED.value,
            available_at=utc_now() - timedelta(minutes=2),
        )

        with Session(self.db_module.engine) as session:
            claimed = coordinator.claim_next_job(session, worker_id="worker-order")
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.run_id, run_b.id)

    def test_claim_next_job_returns_none_when_no_claimable_jobs(self) -> None:
        coordinator = QueueCoordinator()
        paper_id = self.create_paper(title="No claimable")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url="https://example.org/no-claimable.pdf",
        )
        self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.QUEUED.value,
            available_at=utc_now() + timedelta(minutes=5),
        )

        with Session(self.db_module.engine) as session:
            claimed = coordinator.claim_next_job(session, worker_id="worker-none")
            self.assertIsNone(claimed)

    def test_has_active_lock_for_urls_handles_blank_and_pdf_urls(self) -> None:
        coordinator = QueueCoordinator()
        paper_id = self.create_paper(title="Active lock probe")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url="https://example.org/probe-main.pdf",
        )
        self.create_source_lock(run_id=run.id, source_url="https://example.org/probe-si.pdf")

        with Session(self.db_module.engine) as session:
            pending_blank, run_id_blank = coordinator.has_active_lock_for_urls(
                session,
                pdf_url="   ",
                pdf_urls=None,
            )
            self.assertFalse(pending_blank)
            self.assertIsNone(run_id_blank)

            pending, pending_run_id = coordinator.has_active_lock_for_urls(
                session,
                pdf_url="https://example.org/probe-main.pdf",
                pdf_urls=["https://example.org/probe-si.pdf"],
            )
            self.assertTrue(pending)
            self.assertEqual(pending_run_id, run.id)

    def test_finish_job_wrong_claim_token_is_noop(self) -> None:
        coordinator = QueueCoordinator()
        source_url = "https://example.org/finish-noop.pdf"
        paper_id = self.create_paper(title="Finish noop")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url=source_url,
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=source_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="right-token",
            claimed_by="worker-x",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=run.id, source_url=source_url)

        with Session(self.db_module.engine) as session:
            coordinator.finish_job(
                session,
                job_id=job_id,
                claim_token="wrong-token",
                status=QueueJobStatus.DONE,
            )
            job = session.get(QueueJob, job_id)
            self.assertEqual(job.status, QueueJobStatus.CLAIMED.value)
            self.assertEqual(job.claim_token, "right-token")
            lock = session.exec(select(ActiveSourceLock).where(ActiveSourceLock.run_id == run.id)).first()
            self.assertIsNotNone(lock)

    def test_finish_job_terminal_status_releases_lock(self) -> None:
        coordinator = QueueCoordinator()
        source_url = "https://example.org/finish-cancel.pdf"
        paper_id = self.create_paper(title="Finish cancel")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url=source_url,
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=source_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="claim-token",
            claimed_by="worker-c",
            claimed_at=utc_now(),
        )
        self.create_source_lock(run_id=run.id, source_url=source_url)

        with Session(self.db_module.engine) as session:
            coordinator.finish_job(
                session,
                job_id=job_id,
                claim_token="claim-token",
                status=QueueJobStatus.CANCELLED,
            )
            job = session.get(QueueJob, job_id)
            self.assertEqual(job.status, QueueJobStatus.CANCELLED.value)
            lock = session.exec(select(ActiveSourceLock).where(ActiveSourceLock.run_id == run.id)).first()
            self.assertIsNone(lock)

    def test_recover_stale_claims_zero_timeout_requeues_all_claimed(self) -> None:
        coordinator = QueueCoordinator()
        run_ids: list[int] = []
        for idx in range(2):
            paper_id = self.create_paper(title=f"Requeue all {idx}")
            run = self.create_run_row(
                paper_id=paper_id,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                pdf_url=f"https://example.org/requeue-all-{idx}.pdf",
            )
            run_ids.append(run.id)
            self.create_queue_job(
                run_id=run.id,
                pdf_url=run.pdf_url,
                status=QueueJobStatus.CLAIMED.value,
                claim_token=f"token-{idx}",
                claimed_by="worker-a",
                claimed_at=utc_now(),
            )

        with Session(self.db_module.engine) as session:
            summary = coordinator.recover_stale_claims(session, stale_after_seconds=0, max_attempts=3)
            self.assertEqual(summary.requeued, 2)
            self.assertEqual(summary.failed, 0)
            jobs = session.exec(
                select(QueueJob).where(QueueJob.run_id.in_(run_ids)).order_by(QueueJob.run_id.asc())
            ).all()
            self.assertEqual([job.status for job in jobs], [QueueJobStatus.QUEUED.value, QueueJobStatus.QUEUED.value])
            self.assertEqual([job.attempt for job in jobs], [1, 1])

    def test_recover_stale_claims_ignores_claimed_without_claimed_at(self) -> None:
        coordinator = QueueCoordinator()
        paper_id = self.create_paper(title="No claimed_at")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url="https://example.org/no-claimed-at.pdf",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="token-na",
            claimed_by="worker-na",
            claimed_at=None,
        )

        with Session(self.db_module.engine) as session:
            summary = coordinator.recover_stale_claims(session, stale_after_seconds=0, max_attempts=3)
            self.assertEqual(summary.requeued, 0)
            self.assertEqual(summary.failed, 0)
            job = session.get(QueueJob, job_id)
            self.assertEqual(job.status, QueueJobStatus.CLAIMED.value)
            self.assertEqual(job.attempt, 0)

    def test_recover_stale_claims_fails_at_attempt_threshold(self) -> None:
        coordinator = QueueCoordinator()
        source_url = "https://example.org/stale-threshold.pdf"
        paper_id = self.create_paper(title="Stale threshold", url="https://example.org/stale")
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url=source_url,
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=source_url,
            status=QueueJobStatus.CLAIMED.value,
            attempt=2,
            claim_token="token-th",
            claimed_by="worker-th",
            claimed_at=utc_now() - timedelta(minutes=20),
        )
        self.create_source_lock(run_id=run.id, source_url=source_url)

        with Session(self.db_module.engine) as session:
            summary = coordinator.recover_stale_claims(
                session,
                stale_after_seconds=60,
                max_attempts=3,
            )
            self.assertEqual(summary.requeued, 0)
            self.assertEqual(summary.failed, 1)

            job = session.get(QueueJob, job_id)
            self.assertEqual(job.status, QueueJobStatus.FAILED.value)
            self.assertEqual(job.attempt, 3)

            run_row = session.get(ExtractionRun, run.id)
            self.assertEqual(run_row.status, RunStatus.FAILED.value)
            self.assertEqual(run_row.failure_reason, DEFAULT_STALE_FAILURE_REASON)

            lock = session.exec(
                select(ActiveSourceLock).where(ActiveSourceLock.run_id == run.id)
            ).first()
            self.assertIsNone(lock)

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
