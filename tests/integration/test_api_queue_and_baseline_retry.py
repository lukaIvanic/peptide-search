import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from app.baseline.loader import list_cases
from app.config import settings
from app.persistence.models import BaselineCaseRun, BatchRun, BatchStatus, ExtractionRun, Paper, RunStatus


class ApiQueueAndBaselineRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        import app.db as db_module
        import app.services.queue_service as queue_service
        from app.main import create_app

        self.db_module = db_module
        self.queue_service = queue_service

        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test_api.db"
        self.test_engine = create_engine(f"sqlite:///{db_path}", echo=False)

        self.old_engine = db_module.engine
        self.old_queue_concurrency = settings.QUEUE_CONCURRENCY

        settings.QUEUE_CONCURRENCY = 0
        db_module.engine = self.test_engine
        db_module.init_db()

        queue_service._queue = None
        queue_service._broadcaster = None

        self.app = create_app()
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.queue_service._queue = None
        self.queue_service._broadcaster = None
        self.test_engine.dispose()
        self.db_module.engine = self.old_engine
        settings.QUEUE_CONCURRENCY = self.old_queue_concurrency
        self.temp_dir.cleanup()

    def _create_paper(self, title: str = "Test Paper", doi: str | None = None, url: str | None = None) -> int:
        with Session(self.db_module.engine) as session:
            paper = Paper(title=title, doi=doi, url=url, source="test")
            session.add(paper)
            session.commit()
            session.refresh(paper)
            return paper.id

    def test_retry_failed_runs_api_transitions_to_queued(self) -> None:
        paper_id = self._create_paper(doi="10.1000/test-queue", url="https://example.org/queue")
        with Session(self.db_module.engine) as session:
            run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="provider error: timeout",
                model_provider="mock",
                pdf_url="https://example.org/queue.pdf",
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        response = self.client.post(
            "/api/runs/failures/retry",
            json={
                "days": 30,
                "limit": 10,
                "max_runs": 1000,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requested"], 1)
        self.assertEqual(payload["enqueued"], 1)
        self.assertEqual(payload["skipped"], 0)

        with Session(self.db_module.engine) as session:
            updated = session.get(ExtractionRun, run_id)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, RunStatus.QUEUED.value)
            self.assertIsNone(updated.failure_reason)

    def test_baseline_case_retry_requeues_once_and_then_deduplicates(self) -> None:
        case = list_cases()[0]
        case_id = case["id"]
        source_url = "https://example.org/baseline-case.pdf"

        paper_id = self._create_paper(doi=case.get("doi"), url=case.get("paper_url"))
        with Session(self.db_module.engine) as session:
            failed_run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="provider error: empty",
                model_provider="mock",
                pdf_url=source_url,
            )
            session.add(failed_run)
            session.commit()
            session.refresh(failed_run)
            session.add(BaselineCaseRun(baseline_case_id=case_id, run_id=failed_run.id))
            session.commit()

        first = self.client.post(
            f"/api/baseline/cases/{case_id}/retry",
            json={"source_url": source_url, "provider": "mock"},
        )
        self.assertEqual(first.status_code, 200)
        first_payload = first.json()
        self.assertEqual(first_payload["status"], RunStatus.QUEUED.value)
        self.assertEqual(first_payload["message"], "Baseline case re-queued for processing")

        second = self.client.post(
            f"/api/baseline/cases/{case_id}/retry",
            json={"source_url": source_url, "provider": "mock"},
        )
        self.assertEqual(second.status_code, 200)
        second_payload = second.json()
        self.assertEqual(second_payload["message"], "Baseline case already queued for processing")

        with Session(self.db_module.engine) as session:
            runs = session.exec(
                select(ExtractionRun)
                .where(ExtractionRun.pdf_url == source_url)
                .order_by(ExtractionRun.created_at.asc())
            ).all()
            self.assertEqual(len(runs), 2)
            self.assertEqual(runs[-1].status, RunStatus.QUEUED.value)

    def test_baseline_batch_retry_requeues_failed_runs(self) -> None:
        batch_id = "batch_retry_test"
        paper_id = self._create_paper(doi="10.1000/batch", url="https://example.org/batch")

        with Session(self.db_module.engine) as session:
            batch = BatchRun(
                batch_id=batch_id,
                label="Retry batch",
                dataset="self_assembly",
                model_provider="mock",
                model_name="mock-model",
                status=BatchStatus.FAILED.value,
                total_papers=1,
                completed=0,
                failed=1,
            )
            session.add(batch)
            run = ExtractionRun(
                paper_id=paper_id,
                status=RunStatus.FAILED.value,
                failure_reason="provider error: temp",
                model_provider="mock",
                pdf_url="https://example.org/batch.pdf",
                batch_id=batch_id,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            run_id = run.id

        response = self.client.post(
            "/api/baseline/batch-retry",
            json={"batch_id": batch_id, "provider": "mock"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["batch_id"], batch_id)
        self.assertEqual(payload["retried"], 1)
        self.assertEqual(payload["skipped"], 0)

        with Session(self.db_module.engine) as session:
            updated_run = session.get(ExtractionRun, run_id)
            self.assertEqual(updated_run.status, RunStatus.QUEUED.value)
            self.assertIsNone(updated_run.failure_reason)

            batch = session.exec(select(BatchRun).where(BatchRun.batch_id == batch_id)).first()
            self.assertEqual(batch.status, BatchStatus.RUNNING.value)
            self.assertEqual(batch.failed, 0)


if __name__ == "__main__":
    unittest.main()
