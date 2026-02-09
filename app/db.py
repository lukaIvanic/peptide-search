from contextlib import contextmanager
from typing import Iterator

from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import inspect, text

from .config import settings

# Import models to register them with SQLModel metadata
from .persistence.models import (
	Paper,
	Extraction,
	ExtractionRun,
	ExtractionEntity,
	BasePrompt,
	PromptVersion,
	QualityRuleConfig,
)


engine = create_engine(settings.DB_URL, echo=False)


def _ensure_extraction_run_prompt_columns() -> None:
	"""Ensure newer extraction_run columns exist on legacy SQLite databases."""
	if engine.url.get_backend_name() != "sqlite":
		return
	inspector = inspect(engine)
	if "extraction_run" not in inspector.get_table_names():
		return
	columns = {col["name"] for col in inspector.get_columns("extraction_run")}
	alter_statements = []
	if "prompt_id" not in columns:
		alter_statements.append("ALTER TABLE extraction_run ADD COLUMN prompt_id INTEGER")
	if "prompt_version_id" not in columns:
		alter_statements.append("ALTER TABLE extraction_run ADD COLUMN prompt_version_id INTEGER")
	if "batch_id" not in columns:
		alter_statements.append("ALTER TABLE extraction_run ADD COLUMN batch_id VARCHAR")
	if "extraction_time_ms" not in columns:
		alter_statements.append("ALTER TABLE extraction_run ADD COLUMN extraction_time_ms INTEGER")
	if "input_tokens" not in columns:
		alter_statements.append("ALTER TABLE extraction_run ADD COLUMN input_tokens INTEGER")
	if "output_tokens" not in columns:
		alter_statements.append("ALTER TABLE extraction_run ADD COLUMN output_tokens INTEGER")
	if "reasoning_tokens" not in columns:
		alter_statements.append("ALTER TABLE extraction_run ADD COLUMN reasoning_tokens INTEGER")
	if "total_tokens" not in columns:
		alter_statements.append("ALTER TABLE extraction_run ADD COLUMN total_tokens INTEGER")
	if not alter_statements:
		return
	with engine.begin() as conn:
		for statement in alter_statements:
			conn.execute(text(statement))


def init_db() -> None:
	"""Create database tables if they do not exist."""
	SQLModel.metadata.create_all(engine)
	_ensure_extraction_run_prompt_columns()


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

