import logging
from datetime import UTC, datetime
from typing import Any

from src.core.exceptions import WebhookSignatureError
from src.core.security import verify_signature
from src.integrations.provider_client import provider_client
from src.models.task import ErrorType, Task, TaskAttempt, TaskStatus
from src.models.user import OperationType
from src.repositories.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class WebhookService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def handle_provider_webhook(
        self,
        body: bytes,
        payload: dict[str, Any],
        signature: str,
    ) -> None:
        # Подпись проверяется по исходному телу запроса: любая пересборка JSON
        # (например, через model_dump) меняет байты и ломает HMAC.
        if not verify_signature(body, signature):
            raise WebhookSignatureError('Неверная подпись вебхука')

        external_id = payload.get('external_id')
        status = payload.get('status')  # 'completed' или 'failed'
        error_type = payload.get('error_type')
        result_url = payload.get('result_url')

        if not external_id:
            return  # игнорируем некорректный вебхук

        # Идемпотентность: попытка уже была завершена каким-то вебхуком.
        attempt = await self.uow.tasks.get_attempt_by_external_id(external_id)
        if not attempt or attempt.completed_at is not None:
            return

        task = await self.uow.tasks.get_with_attempts(attempt.task_id)
        if not task or task.status in (TaskStatus.completed, TaskStatus.failed):
            if task is not None:
                logger.warning(
                    'Late %s ignored for task %s: already %s',
                    status,
                    task.id,
                    task.status.value,
                )
            # Правило 6: поздний completed/failed для терминальной задачи
            # не меняет результат и не вызывает повторного возврата.
            return

        # Фиксируем завершение попытки и коммитим ДО любого вызова провайдера:
        # дубликат этого же вебхука не получит ход, а параллельный watchdog
        # увидит завершённую попытку и не пойдёт по следующей ноге.
        attempt.completed_at = datetime.now(UTC)
        attempt.error_type = ErrorType(error_type) if error_type else None
        async with self.uow:
            await self.uow.commit()

        if status == 'completed':
            await self._handle_completed(task, result_url)
        elif status == 'failed':
            await self._handle_failed(task, attempt, error_type)

    async def _handle_completed(
        self,
        task: Task,
        result_url: str | None,
    ) -> None:
        async with self.uow:
            await self.uow.tasks.update_status(
                task_id=task.id,
                status=TaskStatus.completed,
                result_url=result_url,
            )
            await self.uow.users.decrement_active_tasks(task.user_id)
            await self.uow.commit()

    async def _handle_failed(
        self,
        task: Task,
        attempt: TaskAttempt,
        error_type: str | None,
    ) -> None:
        parsed = ErrorType(error_type) if error_type else ErrorType.technical

        # Правило 2: отказ payload — задача падает сразу, следующей ноги нет.
        if parsed == ErrorType.payload:
            await self._fail_task(task)
            return

        # Определяем следующую ногу (respect skip_on_moderation).
        model = await self.uow.models.get_model_with_legs(task.model_slug)
        next_leg = None
        if model:
            current_leg_index = next(
                (i for i, leg in enumerate(model.legs) if leg.id == attempt.leg_id),
                -1,
            )
            for candidate in model.legs[current_leg_index + 1 :]:
                if parsed == ErrorType.moderation and candidate.skip_on_moderation:
                    continue
                next_leg = candidate
                break

        # Вызов провайдера — вне транзакции, не держим соединение с БД во время сети.
        external_id = None
        if next_leg is not None:
            try:
                external_id = await provider_client.send_task(
                    provider=next_leg.provider,
                    task_id=task.id,
                    model_slug=task.model_slug,
                    prompt=task.prompt,
                    ref_images=[],  # референсы уже отправлены в первой попытке
                )
            except Exception:
                logger.debug('Следующая нога не приняла задачу', exc_info=True)
                next_leg = None

        async with self.uow:
            if next_leg is not None and external_id is not None:
                await self.uow.tasks.set_current_leg(task.id, next_leg.id)
                await self.uow.tasks.add_attempt(
                    task_id=task.id,
                    leg_id=next_leg.id,
                    provider=next_leg.provider,
                    external_id=external_id,
                )
                await self.uow.commit()
                logger.info('Задача %s переключена на ногу %s', task.id, next_leg.provider)
                return
            # Ноги кончились (или следующая не приняла задачу) — возврат средств.
            await self._fail_task(task)

    async def _fail_task(self, task: Task) -> None:
        async with self.uow:
            db_task = await self.uow.tasks.get_by_id(task.id)
            if db_task is None or db_task.status == TaskStatus.failed:
                return
            await self.uow.tasks.update_status(
                task_id=db_task.id,
                status=TaskStatus.failed,
                error_type=ErrorType.technical,
            )
            await self.uow.users.decrement_active_tasks(db_task.user_id)

            # Возврат средств — идемпотентно по ключу refund:{task_id}.
            model = await self.uow.models.get_model_with_legs(db_task.model_slug)
            if model:
                await self.uow.users.add_balance_operation(
                    user_id=db_task.user_id,
                    amount=model.price,
                    operation_type=OperationType.refund,
                    reference_id=str(db_task.id),
                    idempotency_key=f'refund:{db_task.id}',
                )
            await self.uow.commit()
