import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.core.db import async_session_factory
from src.repositories.unit_of_work import UnitOfWork
from src.services.watchdog_service import WatchdogService

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 10

scheduler = AsyncIOScheduler()


async def watchdog_job() -> None:
    """Job для проверки зависших задач. Запускается каждые 10 секунд.

    Каждый из 4 воркеров бэкенда запускает этот job, но проход выполняет ровно
    один: WatchdogService.check_stale_tasks берёт pg_try_advisory_lock, остальные
    пропускают итерацию. Работа не задваивается.
    """
    async with async_session_factory() as session:
        try:
            uow = UnitOfWork(session)
            watchdog = WatchdogService(uow)
            await watchdog.check_stale_tasks()
        except Exception:
            logger.exception('Watchdog: ошибка при выполнении')
            await session.rollback()


def start_scheduler() -> None:
    """Запустить планировщик."""
    scheduler.add_job(
        watchdog_job,
        trigger=IntervalTrigger(seconds=CHECK_INTERVAL_SECONDS),
        id='watchdog',
        name='Watchdog: проверка зависших задач',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info('APScheduler запущен')


def stop_scheduler() -> None:
    """Остановить планировщик."""
    scheduler.shutdown(wait=False)
    logger.info('APScheduler остановлен')
