import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import create_engine

import app.db as db_module
from app.config import settings


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


if __name__ == "__main__":
    unittest.main()
