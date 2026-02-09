import unittest

from sqlmodel import Session, select

from app.baseline.loader import list_cases
from app.persistence.models import BaselineCaseRun, ExtractionRun, RunStatus
from support import ApiIntegrationTestCase


class ApiRunRetryEndpointTests(ApiIntegrationTestCase):
    def test_retry_run_rejects_non_failed_status(self) -> None:
        paper_id = self.create_paper(doi="10.1000/retry-nonfailed", url="https://example.org/nonfailed")
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.STORED.value,
            model_provider="mock",
            pdf_url="https://example.org/nonfailed.pdf",
        )

        response = self.client.post(f"/api/runs/{run_id}/retry")
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Can only retry failed runs",
            response.json().get("error", {}).get("message", ""),
        )

    def test_retry_run_transitions_failed_to_queued(self) -> None:
        paper_id = self.create_paper(doi="10.1000/retry-ok", url="https://example.org/retry-ok")
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error: timeout",
            model_provider="mock",
            pdf_url="https://example.org/retry-ok.pdf",
        )

        response = self.client.post(f"/api/runs/{run_id}/retry")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], RunStatus.QUEUED.value)
        self.assertEqual(payload["message"], "Run re-queued for processing")

        with Session(self.db_module.engine) as session:
            updated = session.get(ExtractionRun, run_id)
            self.assertEqual(updated.status, RunStatus.QUEUED.value)
            self.assertIsNone(updated.failure_reason)

    def test_retry_with_source_creates_child_run_and_copies_baseline_links(self) -> None:
        case_id = list_cases()[0]["id"]
        paper_id = self.create_paper(doi="10.1000/retry-source", url="https://example.org/retry-source")

        with Session(self.db_module.engine) as session:
            parent = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="provider error: empty",
                model_provider="mock",
                pdf_url="https://example.org/original.pdf",
                baseline_case_id=case_id,
            )
            session.add(parent)
            session.commit()
            session.refresh(parent)
            parent_id = parent.id
            session.add(BaselineCaseRun(baseline_case_id=case_id, run_id=parent_id))
            session.commit()

        source_url = "https://example.org/new-source.pdf"
        response = self.client.post(
            f"/api/runs/{parent_id}/retry-with-source",
            json={"source_url": source_url, "provider": "mock"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["message"], "New run created and queued")
        child_id = payload["id"]

        with Session(self.db_module.engine) as session:
            child = session.get(ExtractionRun, child_id)
            self.assertIsNotNone(child)
            self.assertEqual(child.parent_run_id, parent_id)
            self.assertEqual(child.status, RunStatus.QUEUED.value)
            self.assertEqual(child.pdf_url, source_url)

            links = session.exec(
                select(BaselineCaseRun)
                .where(BaselineCaseRun.run_id == child_id)
                .where(BaselineCaseRun.baseline_case_id == case_id)
            ).all()
            self.assertEqual(len(links), 1)


if __name__ == "__main__":
    unittest.main()
