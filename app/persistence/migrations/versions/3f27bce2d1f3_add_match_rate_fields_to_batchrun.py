"""add match rate fields to batchrun

Revision ID: 3f27bce2d1f3
Revises: 2e16aca1ebc1
Create Date: 2026-02-09 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f27bce2d1f3'
down_revision: Union[str, Sequence[str], None] = '2e16aca1ebc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add matched_entities and total_expected_entities to batch_run."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Check if batch_run table exists
    existing_tables = inspector.get_table_names()
    if 'batch_run' not in existing_tables:
        return

    existing_columns = [c['name'] for c in inspector.get_columns('batch_run')]

    with op.batch_alter_table('batch_run', schema=None) as batch_op:
        if 'matched_entities' not in existing_columns:
            batch_op.add_column(sa.Column('matched_entities', sa.Integer(), nullable=False, server_default='0'))
        if 'total_expected_entities' not in existing_columns:
            batch_op.add_column(sa.Column('total_expected_entities', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Remove matched_entities and total_expected_entities from batch_run."""
    with op.batch_alter_table('batch_run', schema=None) as batch_op:
        batch_op.drop_column('total_expected_entities')
        batch_op.drop_column('matched_entities')
