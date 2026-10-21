from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.model_repo import ModelRepository
from src.repositories.payment_repo import PaymentRepository
from src.repositories.task_repo import TaskRepository
from src.repositories.user_repo import UserRepository
from src.repositories.watchdog_repo import WatchdogRepository


class UnitOfWork:
    """Единица работы: одна сессия, её репозитории и граница транзакции."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.models = ModelRepository(session)
        self.tasks = TaskRepository(session)
        self.payments = PaymentRepository(session)
        self.watchdog = WatchdogRepository(session)

    async def __aenter__(self) -> 'UnitOfWork':
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
