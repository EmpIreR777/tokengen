"""initial schema

Revision ID: 052d98b6b87a
Revises:
Create Date: 2026-10-21 19:11:49.783010

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '052d98b6b87a'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('balance', sa.BigInteger(), nullable=False),
        sa.Column('active_tasks', sa.Integer(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'models',
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('price', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('slug'),
    )
    op.create_table(
        'model_legs',
        sa.Column('model_slug', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.Enum('alpha', 'beta', name='providerenum'), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('max_ref_images', sa.Integer(), nullable=False),
        sa.Column('skip_on_moderation', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['model_slug'], ['models.slug'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('model_slug', 'provider', name='uq_model_leg_model_provider'),
    )
    op.create_index(op.f('ix_model_legs_model_slug'), 'model_legs', ['model_slug'], unique=False)
    op.create_table(
        'balance_operations',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.Enum('debit', 'credit', 'refund', name='operationtype'), nullable=False),
        sa.Column('reference_id', sa.String(length=255), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key'),
    )
    op.create_index(op.f('ix_balance_operations_user_id'), 'balance_operations', ['user_id'], unique=False)
    op.create_index(op.f('ix_balance_operations_reference_id'), 'balance_operations', ['reference_id'], unique=False)
    op.create_table(
        'tasks',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('model_slug', sa.String(length=100), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('ref_images_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='taskstatus'), nullable=False),
        sa.Column('current_leg_id', sa.Uuid(), nullable=True),
        sa.Column('result_url', sa.Text(), nullable=True),
        sa.Column(
            'error_type', sa.Enum('technical', 'moderation', 'payload', 'timeout', name='errortype'), nullable=True
        ),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['current_leg_id'], ['model_legs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['model_slug'], ['models.slug'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tasks_user_id'), 'tasks', ['user_id'], unique=False)
    op.create_index(op.f('ix_tasks_model_slug'), 'tasks', ['model_slug'], unique=False)
    op.create_table(
        'task_attempts',
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('leg_id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.Enum('alpha', 'beta', name='providerenum'), nullable=False),
        sa.Column(
            'error_type', sa.Enum('technical', 'moderation', 'payload', 'timeout', name='errortype'), nullable=True
        ),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['leg_id'], ['model_legs.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_id'),
        sa.UniqueConstraint('task_id', 'provider', name='uq_task_attempt_task_provider'),
    )
    op.create_index(op.f('ix_task_attempts_task_id'), 'task_attempts', ['task_id'], unique=False)
    op.create_table(
        'payment_webhooks',
        sa.Column('payment_id', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('tokens', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.Enum('received', 'processed', name='paymentwebhookstatus'), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payment_webhooks_payment_id'), 'payment_webhooks', ['payment_id'], unique=True)
    op.create_table(
        'watchdog_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('DROP TABLE IF EXISTS watchdog_state')
    op.drop_index(op.f('ix_payment_webhooks_payment_id'), table_name='payment_webhooks')
    op.drop_table('payment_webhooks')
    op.drop_index(op.f('ix_task_attempts_task_id'), table_name='task_attempts')
    op.drop_table('task_attempts')
    op.drop_index(op.f('ix_tasks_model_slug'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_user_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_balance_operations_reference_id'), table_name='balance_operations')
    op.drop_index(op.f('ix_balance_operations_user_id'), table_name='balance_operations')
    op.drop_table('balance_operations')
    op.drop_index(op.f('ix_model_legs_model_slug'), table_name='model_legs')
    op.drop_table('model_legs')
    op.drop_table('models')
    op.drop_table('users')
    # Типы enum'ов создаются вместе с таблицами — удаляем явно.
    op.execute('DROP TYPE IF EXISTS operationtype')
    op.execute('DROP TYPE IF EXISTS providerenum')
    op.execute('DROP TYPE IF EXISTS paymentwebhookstatus')
    op.execute('DROP TYPE IF EXISTS taskstatus')
    op.execute('DROP TYPE IF EXISTS errortype')
