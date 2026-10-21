import logging
import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from src.core.config import settings

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 3


def _check_connection(engine: Engine) -> bool:
    """Проверяет соединение с БД."""
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        return True
    except DBAPIError:
        return False


def run_migrations() -> None:
    """Применяет миграции alembic до актуальной версии."""
    sync_url = settings.SQLALCHEMY_SYNC_DB_URL
    engine = create_engine(sync_url)
    try:
        alembic_cfg = Config()
        alembic_cfg.set_main_option('script_location', str(Path(__file__).parent.parent / 'alembic'))
        alembic_cfg.set_main_option('sqlalchemy.url', sync_url)
        command.upgrade(alembic_cfg, 'head')
    finally:
        engine.dispose()


def run_migrations_with_retry() -> None:
    """Повторяет миграции, пока БД недоступна (контейнер может стартовать раньше неё)."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        engine = create_engine(settings.SQLALCHEMY_SYNC_DB_URL)
        try:
            if _check_connection(engine):
                break
        except DBAPIError as exc:
            logger.warning('Проверка соединения не удалась (попытка %d/%d): %s', attempt, MAX_ATTEMPTS, exc)
        finally:
            engine.dispose()

        if attempt == MAX_ATTEMPTS:
            raise RuntimeError('Не удалось подключиться к базе данных после нескольких попыток')
        time.sleep(RETRY_DELAY_SECONDS)

    run_migrations()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
    try:
        run_migrations_with_retry()
        logger.info('Миграции применены')
    except Exception:
        logger.exception('Не удалось применить миграции')
        sys.exit(1)
