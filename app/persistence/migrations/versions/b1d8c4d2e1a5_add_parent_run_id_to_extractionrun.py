"""Add parent_run_id to ExtractionRun

Revision ID: b1d8c4d2e1a5
Revises: 80a47444f56c
Create Date: 2026-01-19 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1d8c4d2e1a5"
down_revision: Union[str, Sequence[str], None] = "80a47444f56c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("extraction_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_run_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_extraction_run_parent_run_id"), ["parent_run_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_extraction_run_parent_run_id_extraction_run",
            "extraction_run",
            ["parent_run_id"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("extraction_run", schema=None) as batch_op:
        batch_op.drop_constraint("fk_extraction_run_parent_run_id_extraction_run", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_extraction_run_parent_run_id"))
        batch_op.drop_column("parent_run_id")
