"""network profiles

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'network_profiles',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('bridge', sa.String(length=32), nullable=False),
        sa.Column('vlan', sa.Integer(), nullable=True),
        sa.Column('cidr', sa.String(length=18), nullable=False),
        sa.Column('gateway', sa.String(length=15), nullable=False),
        sa.Column('dns', sa.JSON(), nullable=False),
        sa.Column('search_domain', sa.String(length=253), nullable=True),
        sa.Column('range_start', sa.String(length=15), nullable=False),
        sa.Column('range_end', sa.String(length=15), nullable=False),
        sa.Column('dhcp_start', sa.String(length=15), nullable=True),
        sa.Column('dhcp_end', sa.String(length=15), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )


def downgrade() -> None:
    op.drop_table('network_profiles')
