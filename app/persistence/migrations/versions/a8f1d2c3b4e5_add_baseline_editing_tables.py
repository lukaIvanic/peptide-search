"""add baseline editing tables

Revision ID: a8f1d2c3b4e5
Revises: 9d7f4a5c2b10
Create Date: 2026-02-10 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8f1d2c3b4e5"
down_revision: Union[str, Sequence[str], None] = "9d7f4a5c2b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("batch_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("metrics_stale", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index("ix_batch_run_metrics_stale", ["metrics_stale"], unique=False)

    op.create_table(
        "baseline_dataset",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("source_file", sa.String(), nullable=True),
        sa.Column("original_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "baseline_case",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dataset_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.String(), nullable=True),
        sa.Column("n_terminal", sa.String(), nullable=True),
        sa.Column("c_terminal", sa.String(), nullable=True),
        sa.Column("labels_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("doi", sa.String(), nullable=True),
        sa.Column("pubmed_id", sa.String(), nullable=True),
        sa.Column("paper_url", sa.String(), nullable=True),
        sa.Column("pdf_url", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("source_unverified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["baseline_dataset.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_baseline_case_dataset_id", "baseline_case", ["dataset_id"], unique=False)
    op.create_index("ix_baseline_case_doi", "baseline_case", ["doi"], unique=False)
    op.create_index("ix_baseline_case_pubmed_id", "baseline_case", ["pubmed_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_baseline_case_pubmed_id", table_name="baseline_case")
    op.drop_index("ix_baseline_case_doi", table_name="baseline_case")
    op.drop_index("ix_baseline_case_dataset_id", table_name="baseline_case")
    op.drop_table("baseline_case")
    op.drop_table("baseline_dataset")

    with op.batch_alter_table("batch_run", schema=None) as batch_op:
        batch_op.drop_index("ix_batch_run_metrics_stale")
        batch_op.drop_column("metrics_stale")
