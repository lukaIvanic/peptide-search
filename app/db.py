from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine

from .config import settings

# Import models so SQLModel metadata is fully registered for Alembic autogenerate.
from .persistence import models as _models  # noqa: F401


engine = create_engine(settings.DB_URL, echo=False)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _build_alembic_config(db_url: Optional[str] = None) -> Config:
    cfg = Config(str(_project_root() / "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        str(_project_root() / "app" / "persistence" / "migrations"),
    )
    cfg.set_main_option("sqlalchemy.url", db_url or str(engine.url))
    return cfg


def run_migrations(*, revision: str = "head", db_url: Optional[str] = None) -> None:
    """Apply Alembic migrations (used by tests/setup scripts only)."""
    cfg = _build_alembic_config(db_url=db_url)
    command.upgrade(cfg, revision)


def _head_revision() -> str:
    cfg = _build_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if not head:
        raise RuntimeError("Unable to resolve Alembic head revision.")
    return head


def assert_schema_current() -> None:
    """Fail fast unless the DB schema is exactly at Alembic head."""
    required_head = _head_revision()
    with engine.connect() as conn:
        inspector = inspect(conn)
        if "alembic_version" not in inspector.get_table_names():
            raise RuntimeError(
                "Database schema is not initialized with Alembic. "
                "Run: alembic upgrade head"
            )
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        current = rows[0][0] if rows else None
        if current != required_head:
            raise RuntimeError(
                "Database schema is out of date. "
                f"Current revision: {current or 'none'}, required head: {required_head}. "
                "Run: alembic upgrade head"
            )


def init_db() -> None:
    """Compatibility shim: validation only (no runtime schema mutation)."""
    assert_schema_current()


def get_session() -> Iterator[Session]:
    """FastAPI dependency to provide a session per-request."""
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for scripts/background tasks."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
