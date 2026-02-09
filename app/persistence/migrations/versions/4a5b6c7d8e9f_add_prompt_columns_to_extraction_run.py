"""add prompt foreign key columns to extraction_run

Revision ID: 4a5b6c7d8e9f
Revises: 23d3f1cf037f
Create Date: 2026-02-09 22:41:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4a5b6c7d8e9f"
down_revision: Union[str, Sequence[str], None] = "23d3f1cf037f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col["name"] for col in inspector.get_columns("extraction_run")}

    with op.batch_alter_table("extraction_run", schema=None) as batch_op:
        if "prompt_id" not in columns:
            batch_op.add_column(sa.Column("prompt_id", sa.Integer(), nullable=True))
            batch_op.create_index(batch_op.f("ix_extraction_run_prompt_id"), ["prompt_id"], unique=False)
        if "prompt_version_id" not in columns:
            batch_op.add_column(sa.Column("prompt_version_id", sa.Integer(), nullable=True))
            batch_op.create_index(
                batch_op.f("ix_extraction_run_prompt_version_id"),
                ["prompt_version_id"],
                unique=False,
            )


def downgrade() -> None:
    with op.batch_alter_table("extraction_run", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_extraction_run_prompt_version_id"))
        batch_op.drop_column("prompt_version_id")
        batch_op.drop_index(batch_op.f("ix_extraction_run_prompt_id"))
        batch_op.drop_column("prompt_id")
