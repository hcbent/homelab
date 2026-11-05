"""operation approval, dry run and cleanup lineage

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('operations') as batch:
        batch.add_column(sa.Column('dry_run', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('parent_op_id', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('plan_digest', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('plan_summary', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('approved_digest', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('approved_by', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('result', sa.JSON(), nullable=True))
        batch.create_foreign_key('fk_operations_parent_op', 'operations', ['parent_op_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('operations') as batch:
        batch.drop_constraint('fk_operations_parent_op', type_='foreignkey')
        for column in ('result', 'approved_at', 'approved_by', 'approved_digest', 'plan_summary',
                       'plan_digest', 'parent_op_id', 'dry_run'):
            batch.drop_column(column)
