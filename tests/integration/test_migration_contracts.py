import os
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text
from sqlmodel import create_engine

from app.config import settings
import app.db as db_module


class MigrationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "migration_contracts.db"
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)

        self.old_engine = db_module.engine
        self.old_db_url = settings.DB_URL
        settings.DB_URL = str(self.engine.url)
        db_module.engine = self.engine

    def tearDown(self) -> None:
        self.engine.dispose()
        db_module.engine = self.old_engine
        settings.DB_URL = self.old_db_url
        self.temp_dir.cleanup()

    def test_assert_schema_current_rejects_stale_revision(self) -> None:
        db_module.run_migrations(revision="4a5b6c7d8e9f", db_url=str(self.engine.url))

        with self.assertRaises(RuntimeError) as ctx:
            db_module.assert_schema_current()

        self.assertIn("out of date", str(ctx.exception))
        self.assertIn("Current revision:", str(ctx.exception))
        self.assertIn("required head:", str(ctx.exception))
        self.assertIn("alembic upgrade head", str(ctx.exception))

    def test_assert_schema_current_accepts_head_revision(self) -> None:
        db_module.run_migrations(db_url=str(self.engine.url))
        db_module.assert_schema_current()

    def test_assert_schema_current_rejects_missing_alembic_version_table(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        with self.assertRaises(RuntimeError) as ctx:
            db_module.assert_schema_current()

        message = str(ctx.exception)
        self.assertIn("not initialized with Alembic", message)
        self.assertIn("alembic upgrade head", message)

    def test_run_migrations_uses_explicit_db_url_over_environment_override(self) -> None:
        env_db_path = Path(self.temp_dir.name) / "env_override.db"
        env_engine = create_engine(f"sqlite:///{env_db_path}", echo=False)
        old_env_db_url = os.environ.get("DB_URL")
        try:
            os.environ["DB_URL"] = str(env_engine.url)
            db_module.run_migrations(db_url=str(self.engine.url))
        finally:
            if old_env_db_url is None:
                os.environ.pop("DB_URL", None)
            else:
                os.environ["DB_URL"] = old_env_db_url

        with self.engine.connect() as conn:
            version_table = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='alembic_version'"
                )
            ).fetchone()
        self.assertIsNotNone(version_table)

        with env_engine.connect() as conn:
            env_version_table = conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='alembic_version'"
                )
            ).fetchone()
        self.assertIsNone(env_version_table)
        env_engine.dispose()


if __name__ == "__main__":
    unittest.main()
