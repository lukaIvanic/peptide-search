"""Add baseline_case_run linking table.

Revision ID: ab12cd34ef56
Revises: f7c8d9e0a1b2
Create Date: 2026-01-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ab12cd34ef56"
down_revision: Union[str, Sequence[str], None] = "f7c8d9e0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "baseline_case_run",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("baseline_case_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_run.id"]),
    )
    op.create_index(
        op.f("ix_baseline_case_run_baseline_case_id"),
        "baseline_case_run",
        ["baseline_case_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_baseline_case_run_run_id"),
        "baseline_case_run",
        ["run_id"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO baseline_case_run (baseline_case_id, run_id, created_at)
        SELECT baseline_case_id, id, created_at
        FROM extraction_run
        WHERE baseline_case_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_baseline_case_run_run_id"), table_name="baseline_case_run")
    op.drop_index(op.f("ix_baseline_case_run_baseline_case_id"), table_name="baseline_case_run")
    op.drop_table("baseline_case_run")
