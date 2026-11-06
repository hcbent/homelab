"""when a managed cluster finished bootstrapping

Revision ID: 0006
Revises: 0005

cluster.initial_master_nodes is rendered only while this is empty, and a create that has set it is never run again.
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('clusters') as batch:
        batch.add_column(sa.Column('bootstrapped_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('clusters') as batch:
        batch.drop_column('bootstrapped_at')
