import logging
from datetime import UTC, datetime

from sqlalchemy import text

from src.core.config import settings
from src.integrations.provider_client import provider_client
from src.models.task import ErrorType, Task, TaskStatus
from src.models.user import OperationType
from src.repositories.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

# PostgreSQL advisory lock: гарантирует, что только один воркер
# будет обрабатывать watchdog-пройдью в один момент времени.
# Идентификатор lock уникален для всего приложения.
WATCHDOG_ADVISORY_LOCK_ID = 12345


class WatchdogService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def check_stale_tasks(self) -> None:
        """Проверить и обработать зависшие задачи (статус processing, но updated_at старый).

        `pg_try_advisory_lock` гарантирует, что только один воркер из 4-х ведёт
        проход в данный момент — остальные пропускают свою итерацию. Lock
        сессионный: гарантированно снимается при закрытии сессии (а также явно
        в блоке finally), поэтому падение процесса не блокирует watchdog надолго.
        """
        acquired = await self.uow.session.scalar(
            text('SELECT pg_try_advisory_lock(:lock_id)'),
            {'lock_id': WATCHDOG_ADVISORY_LOCK_ID},
        )
        if not acquired:
            logger.debug('Watchdog: lock занят другим воркером, пропускаем')
            return

        try:
            stale_tasks = await self.uow.tasks.get_stale_tasks(settings.PROVIDER_TIMEOUT)
            for task in stale_tasks:
                await self._handle_stale_task(task)
        finally:
            await self.uow.session.execute(
                text('SELECT pg_advisory_unlock(:lock_id)'),
                {'lock_id': WATCHDOG_ADVISORY_LOCK_ID},
            )
            await self.uow.session.commit()

    async def _handle_stale_task(self, task: Task) -> None:
        """Обработать зависшую задачу — то же, что ошибка technical (правило 5)."""

        # Перезагружаем свежее состояние: параллельный вебхук мог уже завершить
        # последнюю попытку — тогда задачу трогать не надо (правило 6).
        db_task = await self.uow.tasks.get_with_attempts(task.id)
        if not db_task or db_task.status != TaskStatus.processing:
            return

        last_attempt = db_task.attempts[-1] if db_task.attempts else None
        if last_attempt is not None and last_attempt.completed_at is not None:
            logger.warning(
                'Watchdog: задача %s уже завершена вебхуком, пропускаем',
                db_task.id,
            )
            return

        if last_attempt is None:
            await self._fail_task(db_task, ErrorType.timeout)
            return

        # Помечаем последнюю попытку как timeout и фиксируем перед сетевым вызовом,
        # чтобы дублирующий вебхук не ушёл на следующую ногу повторно.
        last_attempt.error_type = ErrorType.timeout
        last_attempt.completed_at = datetime.now(UTC)
        await self.uow.session.flush()

        # Таймаут считаем как technical: skip_on_moderation не применяется.
        model = await self.uow.models.get_model_with_legs(db_task.model_slug)
        next_leg = None
        if model:
            current_leg_index = next(
                (i for i, leg in enumerate(model.legs) if leg.id == last_attempt.leg_id),
                -1,
            )
            if current_leg_index != -1 and current_leg_index + 1 < len(model.legs):
                next_leg = model.legs[current_leg_index + 1]

        # Вызов провайдера — вне транзакции.
        external_id = None
        if next_leg is not None:
            try:
                external_id = await provider_client.send_task(
                    provider=next_leg.provider,
                    task_id=db_task.id,
                    model_slug=db_task.model_slug,
                    prompt=db_task.prompt,
                    ref_images=[],
                )
            except Exception:
                logger.debug('Watchdog: нога %s не приняла задачу', next_leg.id, exc_info=True)
                next_leg = None

        if next_leg is not None and external_id is not None:
            await self.uow.tasks.set_current_leg(db_task.id, next_leg.id)
            await self.uow.tasks.add_attempt(
                task_id=db_task.id,
                leg_id=next_leg.id,
                provider=next_leg.provider,
                external_id=external_id,
            )
            await self.uow.session.commit()
            logger.info('Watchdog: задача %s переключена на ногу %s', db_task.id, next_leg.id)
        else:
            await self._fail_task(db_task, ErrorType.timeout)

    async def _fail_task(self, task: Task, error_type: ErrorType) -> None:
        db_task = await self.uow.tasks.get_by_id(task.id)
        if db_task is None or db_task.status == TaskStatus.failed:
            return
        await self.uow.tasks.update_status(
            task_id=db_task.id,
            status=TaskStatus.failed,
            error_type=error_type,
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
        await self.uow.session.commit()
        logger.info('Watchdog: задача %s провалена, токены возвращены', db_task.id)
