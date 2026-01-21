"""Add entity_index and quality rules config

Revision ID: c1f2a3b4c5d6
Revises: b1d8c4d2e1a5
Create Date: 2026-01-19 23:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "b1d8c4d2e1a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("extraction_entity", schema=None) as batch_op:
        batch_op.add_column(sa.Column("entity_index", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_extraction_entity_entity_index"), ["entity_index"], unique=False)

    op.create_table(
        "quality_rule_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rules_json", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("quality_rule_config")

    with op.batch_alter_table("extraction_entity", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_extraction_entity_entity_index"))
        batch_op.drop_column("entity_index")
