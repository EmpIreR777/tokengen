from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.task import Task


class OperationType(StrEnum):
    debit = 'debit'
    credit = 'credit'
    refund = 'refund'


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'users'

    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    active_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    balance_operations: Mapped[list['BalanceOperation']] = relationship(
        back_populates='user',
        lazy='selectin',
    )
    tasks: Mapped[list['Task']] = relationship(
        back_populates='user',
        lazy='selectin',
    )


class BalanceOperation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'balance_operations'

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type: Mapped[OperationType] = mapped_column(Enum(OperationType), nullable=False)
    # Ссылка на операцию-источник: task_id (UUID) или payment_id (строка) — храним строкой.
    reference_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    user: Mapped[User] = relationship(back_populates='balance_operations', lazy='selectin')
