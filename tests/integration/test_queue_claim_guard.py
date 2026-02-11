import asyncio
import unittest

from sqlmodel import Session

from app.persistence.models import QueueJob, QueueJobStatus, RunStatus
from app.services.extraction_service import run_queued_extraction
from app.services.queue_errors import RunCancelledError
from support import ApiIntegrationTestCase


class QueueClaimGuardTests(ApiIntegrationTestCase):
    def test_run_queued_extraction_rejects_lost_claim(self) -> None:
        paper_id = self.create_paper(
            title="Claim Guard",
            doi="10.1000/claim-guard",
            url="https://example.org/claim-guard",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/claim-guard.pdf",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="correct-token",
            claimed_by="worker-test",
        )

        with self.assertRaises(RunCancelledError):
            asyncio.run(
                run_queued_extraction(
                    run_id=run.id,
                    paper_id=paper_id,
                    pdf_url=run.pdf_url or "",
                    provider="mock",
                    model="mock-model",
                    claim_job_id=job_id,
                    claim_token="wrong-token",
                )
            )

        with Session(self.db_module.engine) as session:
            refreshed_run = session.get(type(run), run.id)
            job = session.get(QueueJob, job_id)
            self.assertIsNotNone(refreshed_run)
            self.assertEqual(refreshed_run.status, RunStatus.PROVIDER.value)
            self.assertIsNone(refreshed_run.raw_json)
            self.assertIsNotNone(job)
            self.assertEqual(job.status, QueueJobStatus.CLAIMED.value)

    def test_run_queued_extraction_allows_active_claim(self) -> None:
        paper_id = self.create_paper(
            title="Claim Guard Success",
            doi="10.1000/claim-guard-ok",
            url="https://example.org/claim-guard-ok",
        )
        run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.PROVIDER.value,
            model_provider="mock",
            model_name="mock-model",
            pdf_url="https://example.org/claim-guard-ok.pdf",
        )
        job_id = self.create_queue_job(
            run_id=run.id,
            pdf_url=run.pdf_url,
            status=QueueJobStatus.CLAIMED.value,
            claim_token="active-token",
            claimed_by="worker-test",
        )

        result = asyncio.run(
            run_queued_extraction(
                run_id=run.id,
                paper_id=paper_id,
                pdf_url=run.pdf_url or "",
                provider="mock",
                model="mock-model",
                claim_job_id=job_id,
                claim_token="active-token",
            )
        )
        self.assertEqual(result["run_id"], run.id)

        with Session(self.db_module.engine) as session:
            refreshed_run = session.get(type(run), run.id)
            self.assertIsNotNone(refreshed_run)
            self.assertIsNotNone(refreshed_run.raw_json)


if __name__ == "__main__":
    unittest.main()
