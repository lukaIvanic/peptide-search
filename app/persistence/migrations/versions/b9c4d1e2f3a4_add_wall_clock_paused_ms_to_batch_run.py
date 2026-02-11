"""add wall_clock_paused_ms to batch_run

Revision ID: b9c4d1e2f3a4
Revises: a8f1d2c3b4e5
Create Date: 2026-02-10 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9c4d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8f1d2c3b4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("batch_run", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "wall_clock_paused_ms",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("batch_run", schema=None) as batch_op:
        batch_op.drop_column("wall_clock_paused_ms")
