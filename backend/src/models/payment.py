from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from src.models.user import User


class PaymentWebhookStatus(StrEnum):
    received = 'received'
    processed = 'processed'


class PaymentWebhook(Base, UUIDMixin):
    __tablename__ = 'payment_webhooks'

    payment_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[PaymentWebhookStatus] = mapped_column(
        Enum(PaymentWebhookStatus),
        default=PaymentWebhookStatus.received,
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped['User'] = relationship(lazy='selectin')
