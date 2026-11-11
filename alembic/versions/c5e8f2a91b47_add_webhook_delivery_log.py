"""add webhook delivery log with retries

Revision ID: c5e8f2a91b47
Revises: b41d9c8a7f31
Create Date: 2026-11-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e8f2a91b47'
down_revision: Union[str, Sequence[str], None] = 'b41d9c8a7f31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('webhook_node_id', sa.String(length=32), nullable=False),
        sa.Column('organization_id', sa.String(length=32), nullable=False),
        sa.Column('call_id', sa.String(length=32), nullable=True),
        sa.Column('event', sa.String(length=40), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['webhook_node_id'], ['webhook_nodes.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('webhook_node_id', 'event', 'call_id', name='uq_delivery_node_event_call'),
    )
    op.create_index(op.f('ix_webhook_deliveries_webhook_node_id'), 'webhook_deliveries', ['webhook_node_id'], unique=False)
    op.create_index(op.f('ix_webhook_deliveries_organization_id'), 'webhook_deliveries', ['organization_id'], unique=False)
    op.create_index(op.f('ix_webhook_deliveries_call_id'), 'webhook_deliveries', ['call_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_webhook_deliveries_call_id'), table_name='webhook_deliveries')
    op.drop_index(op.f('ix_webhook_deliveries_organization_id'), table_name='webhook_deliveries')
    op.drop_index(op.f('ix_webhook_deliveries_webhook_node_id'), table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')
