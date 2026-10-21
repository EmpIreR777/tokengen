from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import InsufficientTokensError
from src.models.user import BalanceOperation, OperationType, User

MAX_ACTIVE_TASKS = 3


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_balance(self, user_id: UUID) -> int:
        """Баланс читаем напрямую из БД — кэш ORM может хранить устаревшее значение."""
        result = await self.session.execute(select(User.balance).where(User.id == user_id))
        return result.scalar_one_or_none() or 0

    async def reserve_active_slot(self, user_id: UUID) -> bool:
        """Атомарно зарезервировать слот под активную задачу (лимит 3).

        Возвращает True, если слот занят, и False, если лимит уже исчерпан.
        Операция выполняется одним UPDATE, поэтому одновременные запросы от
        одного пользователя не могут проскочить лимит за счёт lost update.
        """
        result = await self.session.execute(
            update(User)
            .where(User.id == user_id, User.active_tasks < MAX_ACTIVE_TASKS)
            .values(active_tasks=User.active_tasks + 1)
            .execution_options(synchronize_session='fetch'),
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def increment_active_tasks(self, user_id: UUID) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(active_tasks=User.active_tasks + 1)
            .execution_options(synchronize_session='fetch'),
        )

    async def decrement_active_tasks(self, user_id: UUID) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id, User.active_tasks > 0)
            .values(active_tasks=User.active_tasks - 1)
            .execution_options(synchronize_session='fetch'),
        )

    async def add_balance_operation(
        self,
        user_id: UUID,
        amount: int,
        operation_type: OperationType,
        reference_id: str,
        idempotency_key: str,
    ) -> bool:
        """Записать операцию и изменить баланс. False — операция уже выполнялась.

        Сначала вставляется операция с уникальным idempotency_key: только она
        определяет, была ли операция уже выполнена. Баланс меняется после, поэтому
        при дубликате он не затрагивается, а savepoint откатывает оба изменения.
        """
        try:
            async with self.session.begin_nested():
                self.session.add(
                    BalanceOperation(
                        user_id=user_id,
                        amount=amount,
                        type=operation_type,
                        reference_id=reference_id,
                        idempotency_key=idempotency_key,
                    )
                )
                await self.session.flush()

                updated = await self.session.execute(
                    update(User)
                    .where(User.id == user_id, User.balance + amount >= 0)
                    .values(balance=User.balance + amount)
                    # 'fetch' обновляет identity map: bulk UPDATE иначе оставляет
                    # в кэше устаревший баланс. RETURNING здесь нельзя — с ним
                    # ORM-синхронизация отключается.
                    .execution_options(synchronize_session='fetch')
                )
                if cast(CursorResult[Any], updated).rowcount == 0:
                    raise InsufficientTokensError(f'У пользователя {user_id} недостаточно токенов')
        except IntegrityError:
            return False
        return True

    async def get_balance_operations(self, user_id: UUID, limit: int = 20) -> list[BalanceOperation]:
        result = await self.session.execute(
            select(BalanceOperation)
            .where(BalanceOperation.user_id == user_id)
            .order_by(BalanceOperation.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
