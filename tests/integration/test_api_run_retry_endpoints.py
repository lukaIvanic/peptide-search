import unittest

from sqlmodel import Session, select

from app.baseline.loader import list_cases
from app.persistence.models import BaselineCaseRun, ExtractionRun, QueueJobStatus, RunStatus
from support import ApiIntegrationTestCase


class ApiRunRetryEndpointTests(ApiIntegrationTestCase):
    def first_case_id(self) -> str:
        cases = list_cases()
        self.assertGreater(len(cases), 0)
        return cases[0]["id"]

    def assert_error(
        self,
        response,
        *,
        status_code: int,
        code: str,
        message_contains: str,
    ) -> None:
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(body["error"]["code"], code)
        self.assertIn(message_contains, body["error"]["message"])

    def test_retry_run_missing_run_returns_not_found_envelope(self) -> None:
        response = self.client.post("/api/runs/999999/retry")
        self.assert_error(
            response,
            status_code=404,
            code="not_found",
            message_contains="Run not found",
        )

    def test_retry_run_missing_paper_returns_not_found_envelope(self) -> None:
        orphan_run_id = self.create_run(
            paper_id=999999,
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            pdf_url="https://example.org/orphan.pdf",
        )

        response = self.client.post(f"/api/runs/{orphan_run_id}/retry")
        self.assert_error(
            response,
            status_code=404,
            code="not_found",
            message_contains="Paper not found",
        )

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

    def test_retry_run_pending_source_conflict_does_not_requeue(self) -> None:
        source_url = "https://example.org/conflict.pdf"
        paper_id = self.create_paper(doi="10.1000/conflict", url="https://example.org/conflict")
        retry_run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            pdf_url=source_url,
        )
        blocker_run = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url=source_url,
        )
        self.create_queue_job(
            run_id=blocker_run.id,
            pdf_url=source_url,
            status=QueueJobStatus.QUEUED,
        )
        self.create_source_lock(run_id=blocker_run.id, source_url=source_url)

        response = self.client.post(f"/api/runs/{retry_run_id}/retry")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], retry_run_id)
        self.assertEqual(payload["message"], "Run already queued for processing")

        with Session(self.db_module.engine) as session:
            run = session.get(ExtractionRun, retry_run_id)
            self.assertEqual(run.status, RunStatus.FAILED.value)

    def test_retry_with_source_missing_all_sources_returns_bad_request(self) -> None:
        paper_id = self.create_paper(doi="10.1000/no-source", url=None)
        run_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            pdf_url=None,
        )

        response = self.client.post(
            f"/api/runs/{run_id}/retry-with-source",
            json={},
        )
        self.assert_error(
            response,
            status_code=400,
            code="bad_request",
            message_contains="No source URL available for retry",
        )

    def test_retry_with_source_pending_conflict_does_not_create_child_run(self) -> None:
        paper_id = self.create_paper(doi="10.1000/retry-pending", url="https://example.org/retry-pending")
        parent_id = self.create_run(
            paper_id=paper_id,
            status=RunStatus.FAILED.value,
            failure_reason="provider error",
            model_provider="mock",
            pdf_url="https://example.org/parent.pdf",
        )
        source_url = "https://example.org/pending-source.pdf"
        blocker = self.create_run_row(
            paper_id=paper_id,
            status=RunStatus.QUEUED.value,
            model_provider="mock",
            pdf_url=source_url,
        )
        self.create_queue_job(
            run_id=blocker.id,
            pdf_url=source_url,
            status=QueueJobStatus.QUEUED,
        )
        self.create_source_lock(run_id=blocker.id, source_url=source_url)

        with Session(self.db_module.engine) as session:
            before_count = len(
                session.exec(select(ExtractionRun).where(ExtractionRun.paper_id == paper_id)).all()
            )

        response = self.client.post(
            f"/api/runs/{parent_id}/retry-with-source",
            json={"source_url": source_url, "provider": "mock"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], parent_id)
        self.assertEqual(payload["message"], "Run already queued for processing")

        with Session(self.db_module.engine) as session:
            after_count = len(
                session.exec(select(ExtractionRun).where(ExtractionRun.paper_id == paper_id)).all()
            )
        self.assertEqual(before_count, after_count)

    def test_retry_with_source_creates_child_run_and_copies_baseline_links(self) -> None:
        case_id = self.first_case_id()
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
