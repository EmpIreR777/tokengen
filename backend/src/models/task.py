from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin
from src.models.model import ProviderEnum

if TYPE_CHECKING:
    from src.models.model import ModelLeg
    from src.models.user import User


class TaskStatus(StrEnum):
    pending = 'pending'
    processing = 'processing'
    completed = 'completed'
    failed = 'failed'


class ErrorType(StrEnum):
    technical = 'technical'
    moderation = 'moderation'
    payload = 'payload'
    timeout = 'timeout'


class Task(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'tasks'

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    model_slug: Mapped[str] = mapped_column(
        ForeignKey('models.slug', ondelete='RESTRICT'),
        nullable=False,
        index=True,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    ref_images_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus),
        default=TaskStatus.pending,
        nullable=False,
    )
    current_leg_id: Mapped[UUID | None] = mapped_column(
        ForeignKey('model_legs.id', ondelete='SET NULL'),
        nullable=True,
    )
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[ErrorType | None] = mapped_column(Enum(ErrorType), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped['User'] = relationship(back_populates='tasks', lazy='selectin')
    current_leg: Mapped['ModelLeg | None'] = relationship(lazy='selectin')
    attempts: Mapped[list['TaskAttempt']] = relationship(
        back_populates='task',
        lazy='selectin',
        order_by='TaskAttempt.started_at',
    )


class TaskAttempt(Base, UUIDMixin):
    __tablename__ = 'task_attempts'

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey('tasks.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    leg_id: Mapped[UUID] = mapped_column(
        ForeignKey('model_legs.id', ondelete='RESTRICT'),
        nullable=False,
    )
    provider: Mapped[ProviderEnum] = mapped_column(Enum(ProviderEnum), nullable=False)
    error_type: Mapped[ErrorType | None] = mapped_column(Enum(ErrorType), nullable=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates='attempts', lazy='selectin')
    leg: Mapped['ModelLeg'] = relationship(lazy='selectin')

    __table_args__ = (UniqueConstraint('task_id', 'provider', name='uq_task_attempt_task_provider'),)
