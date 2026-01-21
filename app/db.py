from contextlib import contextmanager
from typing import Iterator

from sqlmodel import SQLModel, Session, create_engine

from .config import settings

# Import models to register them with SQLModel metadata
from .persistence.models import Paper, Extraction, ExtractionRun, ExtractionEntity


engine = create_engine(settings.DB_URL, echo=False)


def init_db() -> None:
	"""Create database tables if they do not exist."""
	SQLModel.metadata.create_all(engine)


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


