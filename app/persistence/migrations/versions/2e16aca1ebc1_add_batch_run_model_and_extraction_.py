"""add batch run model and extraction timing

Revision ID: 2e16aca1ebc1
Revises: e2c3d4f5a6b7
Create Date: 2026-02-09 15:41:34.530795

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '2e16aca1ebc1'
down_revision: Union[str, Sequence[str], None] = 'e2c3d4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if batch_run table exists (may have been created by init_db)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'batch_run' not in existing_tables:
        op.create_table(
            'batch_run',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('batch_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('label', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column('dataset', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('model_provider', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('model_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('total_papers', sa.Integer(), nullable=False),
            sa.Column('completed', sa.Integer(), nullable=False),
            sa.Column('failed', sa.Integer(), nullable=False),
            sa.Column('total_input_tokens', sa.Integer(), nullable=False),
            sa.Column('total_output_tokens', sa.Integer(), nullable=False),
            sa.Column('total_time_ms', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_batch_run_batch_id'), 'batch_run', ['batch_id'], unique=True)
        op.create_index(op.f('ix_batch_run_dataset'), 'batch_run', ['dataset'], unique=False)
        op.create_index(op.f('ix_batch_run_status'), 'batch_run', ['status'], unique=False)

    # Add columns to extraction_run if they don't exist
    existing_columns = [c['name'] for c in inspector.get_columns('extraction_run')]

    with op.batch_alter_table('extraction_run', schema=None) as batch_op:
        if 'batch_id' not in existing_columns:
            batch_op.add_column(sa.Column('batch_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
            batch_op.create_index(batch_op.f('ix_extraction_run_batch_id'), ['batch_id'], unique=False)
        if 'extraction_time_ms' not in existing_columns:
            batch_op.add_column(sa.Column('extraction_time_ms', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('extraction_run', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_extraction_run_batch_id'))
        batch_op.drop_column('extraction_time_ms')
        batch_op.drop_column('batch_id')

    op.drop_index(op.f('ix_batch_run_status'), table_name='batch_run')
    op.drop_index(op.f('ix_batch_run_dataset'), table_name='batch_run')
    op.drop_index(op.f('ix_batch_run_batch_id'), table_name='batch_run')
    op.drop_table('batch_run')
