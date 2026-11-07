"""the desired state of a managed cluster as it is now

Revision ID: 0007
Revises: 0006

A create records what it built in its own parameters, but a cluster changes after that (a disk grows, a node is
added), so every later change starts from this column: the parameters of the last create or update that Terraform
applied. It is empty for a cluster ECM built before this existed, and lifecycle changes refuse such a cluster.
"""
import sqlalchemy as sa
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('clusters') as batch:
        batch.add_column(sa.Column('desired', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('clusters') as batch:
        batch.drop_column('desired')
