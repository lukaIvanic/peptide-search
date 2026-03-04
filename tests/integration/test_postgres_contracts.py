import os
import json
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, text
from sqlmodel import Session, create_engine, select

import app.db as db_module
from app.config import settings
from app.persistence.models import ExtractionRun, Paper, QueueJob, QueueJobStatus, RunStatus
from app.services.queue_coordinator import QueueCoordinator
from app.time_utils import utc_now


class PostgresContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.postgres_url = os.getenv("TEST_POSTGRES_URL")
        if not cls.postgres_url:
            raise unittest.SkipTest("TEST_POSTGRES_URL is not set.")

    def setUp(self) -> None:
        self.old_engine = db_module.engine
        self.old_db_url = settings.DB_URL

        self.pg_engine = create_engine(
            self.postgres_url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        settings.DB_URL = self.postgres_url
        db_module.engine = self.pg_engine

    def tearDown(self) -> None:
        self.pg_engine.dispose()
        db_module.engine = self.old_engine
        settings.DB_URL = self.old_db_url

    def _require_isolated_claim_space(self) -> None:
        with Session(db_module.engine) as session:
            active_jobs = session.exec(
                select(func.count(QueueJob.id)).where(
                    QueueJob.status.in_(
                        [
                            QueueJobStatus.QUEUED.value,
                            QueueJobStatus.CLAIMED.value,
                        ]
                    )
                )
            ).one()
        if int(active_jobs or 0) > 0:
            self.skipTest(
                "Claim-path contracts require an isolated Postgres DB with no pre-existing queued/claimed jobs."
            )

    def test_postgres_connectivity(self) -> None:
        with db_module.engine.connect() as conn:
            value = conn.execute(text("SELECT 1")).scalar()
        self.assertEqual(value, 1)

    def test_postgres_schema_contract(self) -> None:
        db_module.assert_schema_current()
        inspector = inspect(db_module.engine)
        table_names = set(inspector.get_table_names())
        self.assertIn("alembic_version", table_names)
        self.assertIn("batch_run", table_names)
        self.assertIn("extraction_run", table_names)
        self.assertIn("baseline_case", table_names)

    def test_app_startup_contract_on_postgres(self) -> None:
        import app.main as main_module

        class _DummyQueue:
            def set_extract_callback(self, _callback) -> None:
                return None

        with (
            patch.object(main_module, "ensure_runtime_defaults", return_value=None),
            patch.object(main_module, "backfill_failed_runs", return_value=None),
            patch.object(main_module, "reconcile_orphan_run_states", return_value=None),
            patch.object(main_module, "start_queue", new=AsyncMock(return_value=None)),
            patch.object(main_module, "stop_queue", new=AsyncMock(return_value=None)),
            patch.object(main_module, "get_queue", return_value=_DummyQueue()),
        ):
            app = main_module.create_app()
            with TestClient(app) as client:
                response = client.get("/api/health")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertIn("status", payload)
                self.assertIn("provider", payload)

    def test_postgres_claim_path_claims_oldest_available_job(self) -> None:
        self._require_isolated_claim_space()
        coordinator = QueueCoordinator()
        with Session(db_module.engine) as session:
            paper_older = Paper(title="PG claim older", source="test")
            paper_newer = Paper(title="PG claim newer", source="test")
            session.add(paper_older)
            session.add(paper_newer)
            session.commit()
            session.refresh(paper_older)
            session.refresh(paper_newer)

            run_older = ExtractionRun(
                paper_id=paper_older.id,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                model_name="mock-model",
                pdf_url="https://example.org/postgres-claim-older.pdf",
            )
            run_newer = ExtractionRun(
                paper_id=paper_newer.id,
                status=RunStatus.QUEUED.value,
                model_provider="mock",
                model_name="mock-model",
                pdf_url="https://example.org/postgres-claim-newer.pdf",
            )
            session.add(run_older)
            session.add(run_newer)
            session.commit()
            session.refresh(run_older)
            session.refresh(run_newer)

            older_payload = {
                "run_id": run_older.id,
                "paper_id": run_older.paper_id or 0,
                "pdf_url": run_older.pdf_url,
                "title": "PG older",
                "provider": "mock",
                "model": "mock-model",
            }
            newer_payload = {
                "run_id": run_newer.id,
                "paper_id": run_newer.paper_id or 0,
                "pdf_url": run_newer.pdf_url,
                "title": "PG newer",
                "provider": "mock",
                "model": "mock-model",
            }
            now = utc_now()
            session.add(
                QueueJob(
                    run_id=run_older.id,
                    source_fingerprint=QueueCoordinator.source_fingerprint(run_older.pdf_url or ""),
                    status=QueueJobStatus.QUEUED.value,
                    available_at=now - timedelta(minutes=5),
                    payload_json=json.dumps(older_payload),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                QueueJob(
                    run_id=run_newer.id,
                    source_fingerprint=QueueCoordinator.source_fingerprint(run_newer.pdf_url or ""),
                    status=QueueJobStatus.QUEUED.value,
                    available_at=now - timedelta(minutes=1),
                    payload_json=json.dumps(newer_payload),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
            run_older_id = run_older.id

        with Session(db_module.engine) as session:
            claimed = coordinator.claim_next_job(session, worker_id="pg-claim-worker")
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.run_id, run_older_id)

            claimed_job = session.get(QueueJob, claimed.id)
            self.assertIsNotNone(claimed_job)
            self.assertEqual(claimed_job.status, QueueJobStatus.CLAIMED.value)
            self.assertEqual(claimed_job.claimed_by, "pg-claim-worker")
            self.assertIsNotNone(claimed_job.claim_token)
            self.assertIsNotNone(claimed_job.claimed_at)

    def test_postgres_claim_path_honors_shard_filter(self) -> None:
        self._require_isolated_claim_space()
        coordinator = QueueCoordinator()
        with Session(db_module.engine) as session:
            papers = [Paper(title=f"PG shard {idx}", source="test") for idx in range(4)]
            for paper in papers:
                session.add(paper)
            session.commit()
            for paper in papers:
                session.refresh(paper)

            runs: list[ExtractionRun] = []
            now = utc_now()
            for idx, paper in enumerate(papers):
                run = ExtractionRun(
                    paper_id=paper.id,
                    status=RunStatus.QUEUED.value,
                    model_provider="mock",
                    model_name="mock-model",
                    pdf_url=f"https://example.org/postgres-shard-{idx}.pdf",
                )
                session.add(run)
                session.commit()
                session.refresh(run)
                runs.append(run)
                payload = {
                    "run_id": run.id,
                    "paper_id": run.paper_id or 0,
                    "pdf_url": run.pdf_url,
                    "title": f"PG shard {idx}",
                    "provider": "mock",
                    "model": "mock-model",
                }
                session.add(
                    QueueJob(
                        run_id=run.id,
                        source_fingerprint=QueueCoordinator.source_fingerprint(run.pdf_url or ""),
                        status=QueueJobStatus.QUEUED.value,
                        available_at=now - timedelta(minutes=2),
                        payload_json=json.dumps(payload),
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.commit()

        with Session(db_module.engine) as session:
            claimed_even = coordinator.claim_next_job_for_shard(
                session,
                worker_id="pg-shard-even",
                shard_count=2,
                shard_id=0,
            )
            self.assertIsNotNone(claimed_even)
            self.assertEqual(claimed_even.run_id % 2, 0)

        with Session(db_module.engine) as session:
            claimed_odd = coordinator.claim_next_job_for_shard(
                session,
                worker_id="pg-shard-odd",
                shard_count=2,
                shard_id=1,
            )
            self.assertIsNotNone(claimed_odd)
            self.assertEqual(claimed_odd.run_id % 2, 1)


if __name__ == "__main__":
    unittest.main()
