import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.core.db import engine
from src.core.exception_handlers import register_exception_handlers
from src.core.logging import setup_logging
from src.core.middleware import RequestContextMiddleware
from src.integrations.provider_client import provider_client
from src.routers import router as api_router
from src.tasks import start_scheduler, stop_scheduler

setup_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    logger.info('Приложение запущено')

    # Запуск APScheduler для watchdog
    start_scheduler()

    yield

    # Остановка
    stop_scheduler()
    await provider_client.close()
    await engine.dispose()
    logger.info('Приложение остановлено')


app = FastAPI(
    version=settings.API_VERSION,
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.add_middleware(RequestContextMiddleware)

register_exception_handlers(app)

app.include_router(api_router)
