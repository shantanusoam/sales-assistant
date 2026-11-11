"""add billing plan/quota fields, token revocation, hint feedback, and invite/reset tokens

Revision ID: b41d9c8a7f31
Revises: 84b9772f527a
Create Date: 2026-11-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b41d9c8a7f31'
down_revision: Union[str, Sequence[str], None] = '84b9772f527a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('organizations', sa.Column('plan', sa.String(length=20), nullable=False, server_default='pilot'))
    op.add_column('organizations', sa.Column('monthly_call_limit_override', sa.Integer(), nullable=True))
    op.add_column('hints', sa.Column('feedback', sa.Integer(), nullable=True))
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)
    op.create_index(op.f('ix_password_reset_tokens_token_hash'), 'password_reset_tokens', ['token_hash'], unique=True)
    op.create_table(
        'invite_tokens',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('organization_id', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invite_tokens_user_id'), 'invite_tokens', ['user_id'], unique=False)
    op.create_index(op.f('ix_invite_tokens_organization_id'), 'invite_tokens', ['organization_id'], unique=False)
    op.create_index(op.f('ix_invite_tokens_token_hash'), 'invite_tokens', ['token_hash'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_invite_tokens_token_hash'), table_name='invite_tokens')
    op.drop_index(op.f('ix_invite_tokens_organization_id'), table_name='invite_tokens')
    op.drop_index(op.f('ix_invite_tokens_user_id'), table_name='invite_tokens')
    op.drop_table('invite_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_token_hash'), table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
    op.drop_column('hints', 'feedback')
    op.drop_column('organizations', 'monthly_call_limit_override')
    op.drop_column('organizations', 'plan')
    op.drop_column('users', 'token_version')
