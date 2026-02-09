import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine

from app.config import settings
from app.persistence.models import ActiveSourceLock, ExtractionRun, Paper, QueueJob, QueueJobStatus
from app.services.queue_coordinator import QueueCoordinator
from app.time_utils import utc_now


class ApiIntegrationTestCase(unittest.TestCase):
    """Reusable isolated app+db harness for integration API tests."""

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
        self.old_db_url = settings.DB_URL

        settings.QUEUE_CONCURRENCY = 0
        settings.DB_URL = str(self.test_engine.url)
        db_module.engine = self.test_engine
        db_module.run_migrations(db_url=str(self.test_engine.url))

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
        settings.DB_URL = self.old_db_url
        self.temp_dir.cleanup()

    def create_paper(
        self,
        title: str = "Test Paper",
        doi: Optional[str] = None,
        url: Optional[str] = None,
        source: str = "test",
    ) -> int:
        with Session(self.db_module.engine) as session:
            paper = Paper(title=title, doi=doi, url=url, source=source)
            session.add(paper)
            session.commit()
            session.refresh(paper)
            return paper.id

    def create_run(self, **kwargs) -> int:
        with Session(self.db_module.engine) as session:
            run = ExtractionRun(**kwargs)
            session.add(run)
            session.commit()
            session.refresh(run)
            return run.id

    def create_run_row(self, **kwargs) -> ExtractionRun:
        """Create a run row and return the hydrated object."""
        with Session(self.db_module.engine) as session:
            run = ExtractionRun(**kwargs)
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def create_queue_job(
        self,
        *,
        run_id: int,
        pdf_url: str,
        status: str = QueueJobStatus.QUEUED.value,
        attempt: int = 0,
        available_at=None,
        claimed_at=None,
        claim_token: Optional[str] = None,
        claimed_by: Optional[str] = None,
        finished_at=None,
    ) -> int:
        """Create a queue job with deterministic defaults for tests."""
        with Session(self.db_module.engine) as session:
            now = utc_now()
            payload = {
                "run_id": run_id,
                "paper_id": 0,
                "pdf_url": pdf_url,
                "title": "test",
                "provider": "mock",
            }
            job = QueueJob(
                run_id=run_id,
                source_fingerprint=QueueCoordinator.source_fingerprint(pdf_url),
                status=status,
                claimed_by=claimed_by,
                claim_token=claim_token,
                attempt=attempt,
                available_at=available_at or now,
                claimed_at=claimed_at,
                finished_at=finished_at,
                payload_json=json.dumps(payload),
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job.id

    def create_source_lock(self, *, run_id: int, source_url: str) -> str:
        """Create an active source lock and return its fingerprint."""
        fingerprint = QueueCoordinator.source_fingerprint(source_url)
        with Session(self.db_module.engine) as session:
            lock = ActiveSourceLock(
                source_fingerprint=fingerprint,
                run_id=run_id,
                created_at=utc_now(),
            )
            session.add(lock)
            session.commit()
        return fingerprint
