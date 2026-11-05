"""a separate Terraform token on a Proxmox connection

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('proxmox_connections') as batch:
        batch.add_column(sa.Column('terraform_credential_id', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('terraform_token_id', sa.String(length=255), nullable=True))
        batch.create_foreign_key('fk_proxmox_connections_terraform_credential', 'credentials',
                                 ['terraform_credential_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('proxmox_connections') as batch:
        batch.drop_constraint('fk_proxmox_connections_terraform_credential', type_='foreignkey')
        batch.drop_column('terraform_token_id')
        batch.drop_column('terraform_credential_id')
