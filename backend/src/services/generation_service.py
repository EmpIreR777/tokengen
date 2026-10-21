import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.core.exceptions import (
    InsufficientTokensError,
    NoSuitableLegError,
    ProviderUnavailableError,
    TooManyActiveTasksError,
)
from src.integrations.provider_client import provider_client
from src.models.model import ModelLeg
from src.models.task import ErrorType, TaskStatus
from src.models.user import OperationType
from src.repositories.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

MAX_ACTIVE_TASKS = 3


class GenerationService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_generation(
        self,
        user_id: UUID,
        model_slug: str,
        prompt: str,
        ref_images: list[str],
    ) -> UUID:
        model = await self.uow.models.get_model_with_legs(model_slug)
        if not model:
            raise NoSuitableLegError(f'Модель {model_slug} не найдена')

        user = await self.uow.users.get_by_id(user_id)
        if not user:
            raise NoSuitableLegError(f'Пользователь {user_id} не найден')

        suitable_legs = [leg for leg in model.legs if leg.max_ref_images >= len(ref_images)]
        if not suitable_legs:
            raise NoSuitableLegError(f'Нет подходящей ноги для {len(ref_images)} референсных изображений')

        # Одна транзакция: создаём задачу, списываем токены и резервируем слот
        # под активную задачу. Списание атомарно проверяет баланс (balance +
        # amount >= 0), резерв — лимит активных задач. При отказе откатывается
        # всё вместе, включая саму задачу.
        async with self.uow:
            task = await self.uow.tasks.create(
                user_id=user_id,
                model_slug=model_slug,
                prompt=prompt,
                ref_images_count=len(ref_images),
                current_leg_id=suitable_legs[0].id,
                status=TaskStatus.processing,
            )

            # Списание токенов и создание попытки — в одной транзакции с задачей.
            debited = await self.uow.users.add_balance_operation(
                user_id=user_id,
                amount=-model.price,
                operation_type=OperationType.debit,
                reference_id=str(task.id),
                idempotency_key=f'gen:{task.id}',
            )
            if not debited:
                raise InsufficientTokensError(f'У пользователя {user_id} недостаточно токенов')

            reserved = await self.uow.users.reserve_active_slot(user_id)
            if not reserved:
                raise TooManyActiveTasksError('Превышен лимит активных задач (максимум 3)')

            await self.uow.commit()

        # Отправка провайдеру происходит вне транзакции: не держим соединение с БД
        # во время сети. Перебираем подходящие ноги по приоритету.
        last_index = len(suitable_legs) - 1
        for index, leg in enumerate(suitable_legs):
            try:
                external_id = await provider_client.send_task(
                    provider=leg.provider,
                    task_id=task.id,
                    model_slug=model_slug,
                    prompt=prompt,
                    ref_images=ref_images,
                )
            except ProviderUnavailableError:
                logger.warning(
                    'Провайдер %s не принял задачу %s (нога %d/%d)',
                    leg.provider,
                    task.id,
                    index + 1,
                    len(suitable_legs),
                )
                # Синхронный отказ считаем как technical: фиксируем попытку и
                # переходим к следующей ноге.
                await self._record_failed_attempt(task.id, leg, ErrorType.technical)
                if index == last_index:
                    await self._fail_task(task.id, model.price)
                continue

            async with self.uow:
                await self.uow.tasks.add_attempt(
                    task_id=task.id,
                    leg_id=leg.id,
                    provider=leg.provider,
                    external_id=external_id,
                )
                if index > 0:
                    await self.uow.tasks.set_current_leg(task.id, leg.id)
                await self.uow.commit()
            logger.info(
                'Задача %s отправлена провайдеру %s (нога %d/%d)',
                task.id,
                leg.provider,
                index + 1,
                len(suitable_legs),
            )
            return task.id

        return task.id

    async def _record_failed_attempt(
        self,
        task_id: UUID,
        leg: ModelLeg,
        error_type: ErrorType,
    ) -> None:
        """Зафиксировать неудачную синхронную отправку на ногу.

        external_id от провайдера нет, поэтому храним уникальный маркер —
        колонка external_id имеет глобальный уникальный индекс.
        """
        async with self.uow:
            await self.uow.tasks.add_attempt(
                task_id=task_id,
                leg_id=leg.id,
                provider=leg.provider,
                external_id=f'sync-fail:{uuid4()}',
                error_type=error_type,
                completed_at=datetime.now(UTC),
            )
            await self.uow.commit()

    async def _fail_task(self, task_id: UUID, price: int) -> None:
        """Все ноги исчерпаны: задача failed, возврат токенов ровно один раз.

        Возврат идемпотентен по ключу `refund:{task_id}` — сколько бы ни
        пришлось сюда попасть (повторный вызов, гонка вордеров), операция
        записи в журнал сработает только один раз.
        """
        async with self.uow:
            task = await self.uow.tasks.get_by_id(task_id)
            if task is None or task.status == TaskStatus.failed:
                return
            await self.uow.tasks.update_status(
                task_id=task_id,
                status=TaskStatus.failed,
                error_type=ErrorType.technical,
            )
            await self.uow.users.decrement_active_tasks(task.user_id)
            await self.uow.users.add_balance_operation(
                user_id=task.user_id,
                amount=price,
                operation_type=OperationType.refund,
                reference_id=str(task_id),
                idempotency_key=f'refund:{task_id}',
            )
            await self.uow.commit()
            logger.info('Задача %s провалена, токены возвращены', task_id)
