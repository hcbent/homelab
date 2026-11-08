"""the nodes whose configuration is waiting for a restart

Revision ID: 0008
Revises: 0007

A converge never restarts a node, so a configuration change it writes takes effect only at the node's next restart. This records, per node,
when ECM wrote such a change (a map of node name to an ISO time), so the Restart nodes panel can say which nodes are waiting. An entry goes
away when the node is seen to have been up for less time than has passed since (it restarted), or when ECM restarts it.
"""
import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('clusters') as batch:
        batch.add_column(sa.Column('pending_restart', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('clusters') as batch:
        batch.drop_column('pending_restart')
