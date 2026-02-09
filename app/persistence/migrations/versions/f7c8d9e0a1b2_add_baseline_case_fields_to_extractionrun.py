"""Add baseline case fields to ExtractionRun

Revision ID: f7c8d9e0a1b2
Revises: c1f2a3b4c5d6
Create Date: 2026-01-24 17:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7c8d9e0a1b2"
down_revision: Union[str, Sequence[str], None] = "c1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("extraction_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("baseline_case_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("baseline_dataset", sa.String(), nullable=True))
        batch_op.create_index(batch_op.f("ix_extraction_run_baseline_case_id"), ["baseline_case_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_run_baseline_dataset"), ["baseline_dataset"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("extraction_run", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_extraction_run_baseline_dataset"))
        batch_op.drop_index(batch_op.f("ix_extraction_run_baseline_case_id"))
        batch_op.drop_column("baseline_dataset")
        batch_op.drop_column("baseline_case_id")
