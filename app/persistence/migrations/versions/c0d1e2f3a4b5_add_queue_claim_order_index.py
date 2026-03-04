"""add queue claim order composite index

Revision ID: c0d1e2f3a4b5
Revises: b9c4d1e2f3a4
Create Date: 2026-02-11 21:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c4d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {idx.get("name") for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    """Upgrade schema."""
    if "ix_queue_job_status_available_id" not in _index_names("queue_job"):
        op.create_index(
            "ix_queue_job_status_available_id",
            "queue_job",
            ["status", "available_at", "id"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    if "ix_queue_job_status_available_id" in _index_names("queue_job"):
        op.drop_index("ix_queue_job_status_available_id", table_name="queue_job")
