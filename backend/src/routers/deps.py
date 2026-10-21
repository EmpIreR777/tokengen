from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db import get_db
from src.repositories.model_repo import ModelRepository
from src.repositories.payment_repo import PaymentRepository
from src.repositories.task_repo import TaskRepository
from src.repositories.unit_of_work import UnitOfWork
from src.repositories.user_repo import UserRepository
from src.services.generation_service import GenerationService
from src.services.payment_service import PaymentService
from src.services.watchdog_service import WatchdogService
from src.services.webhook_service import WebhookService


async def get_uow(session: AsyncSession = Depends(get_db)) -> UnitOfWork:
    return UnitOfWork(session)


async def get_user_repo(uow: UnitOfWork = Depends(get_uow)) -> UserRepository:
    return uow.users


async def get_model_repo(uow: UnitOfWork = Depends(get_uow)) -> ModelRepository:
    return uow.models


async def get_task_repo(uow: UnitOfWork = Depends(get_uow)) -> TaskRepository:
    return uow.tasks


async def get_payment_repo(uow: UnitOfWork = Depends(get_uow)) -> PaymentRepository:
    return uow.payments


async def get_generation_service(uow: UnitOfWork = Depends(get_uow)) -> GenerationService:
    return GenerationService(uow)


async def get_webhook_service(uow: UnitOfWork = Depends(get_uow)) -> WebhookService:
    return WebhookService(uow)


async def get_payment_service(uow: UnitOfWork = Depends(get_uow)) -> PaymentService:
    return PaymentService(uow)


async def get_watchdog_service(uow: UnitOfWork = Depends(get_uow)) -> WatchdogService:
    return WatchdogService(uow)
