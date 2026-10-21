from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base

# Единственная строка с id=1: хранит время последнего прохода watchdog.
WATCHDOG_STATE_ID = 1


class WatchdogState(Base):
    """Состояние watchdog'а: время последнего выполненного прохода."""

    __tablename__ = 'watchdog_state'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
