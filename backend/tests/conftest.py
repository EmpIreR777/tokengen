import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.core.security import sign_payload
from src.models.model import ModelLeg, ProviderEnum
from src.models.task import TaskStatus
from src.models.user import OperationType, User
from src.repositories.unit_of_work import UnitOfWork

# Тесты ходят в ту же БД, что и compose (хост 5433 — маппинг контейнера db).
# NullPool: pytest-asyncio даёт каждому тесту свой event loop, а пул с постоянными
# соединениями пережил бы их между тестами и ломался бы на «другом loop».
engine = create_async_engine(settings.SQLALCHEMY_DB_URL, poolclass=NullPool)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(scope='session')
def _check_db() -> AsyncIterator[None]:
    """Проверить, что БД доступна (миграции накатывает entrypoint контейнера)."""
    return


@pytest_asyncio.fixture
async def session(_check_db: None) -> AsyncIterator[AsyncSession]:
    """Сессия с откатом в конце теста — изоляция от остальных тестов.

    Коммитить внутри теста нельзя: откат в фикстуре перестанет работать.
    """
    async with session_factory() as db_session:
        transaction = await db_session.begin()
        try:
            yield db_session
        finally:
            if transaction.is_active:
                await transaction.rollback()


@pytest_asyncio.fixture
async def uow(session: AsyncSession) -> UnitOfWork:
    return UnitOfWork(session)


@pytest_asyncio.fixture
async def legs(session: AsyncSession) -> list[ModelLeg]:
    """Ноги модели image-fast в порядке приоритета."""
    result = await session.execute(
        select(ModelLeg).where(ModelLeg.model_slug == 'image-fast').order_by(ModelLeg.priority)
    )
    return list(result.scalars().all())


@pytest_asyncio.fixture
async def committed_user(_check_db: None) -> AsyncIterator[User]:
    """Пользователь, сохранённый отдельной транзакцией — виден конкурентным сессиям."""
    async with session_factory() as db_session:
        new_user = User(balance=100, active_tasks=0)
        db_session.add(new_user)
        await db_session.commit()
        await db_session.refresh(new_user)
        user_id = new_user.id

    yield new_user

    async with session_factory() as db_session:
        await db_session.execute(text('DELETE FROM balance_operations WHERE user_id = :uid'), {'uid': user_id})
        await db_session.execute(text('DELETE FROM payment_webhooks WHERE user_id = :uid'), {'uid': user_id})
        await db_session.execute(text('DELETE FROM tasks WHERE user_id = :uid'), {'uid': user_id})
        await db_session.execute(text('DELETE FROM users WHERE id = :uid'), {'uid': user_id})
        await db_session.commit()


@pytest_asyncio.fixture
async def make_task(_check_db: None):
    """Создаёт задачу с попыткой и списанными токенами — всё коммитится.

    Данные видны из других сессий, поэтому пригодны для конкурентных тестов.
    Списание идёт через репозиторий, чтобы баланс обновился согласованно.
    """
    created: list[dict[str, Any]] = []

    async def _factory(
        user: User,
        model_slug: str = 'image-fast',
        provider: ProviderEnum | None = None,
        amount: int = 2,
    ) -> dict[str, Any]:
        async with session_factory() as db_session:
            uow = UnitOfWork(db_session)
            model_legs = await uow.models.get_suitable_legs(model_slug, 0)
            leg = next(leg for leg in model_legs if leg.provider == provider) if provider is not None else model_legs[0]

            task = await uow.tasks.create(
                user_id=user.id,
                model_slug=model_slug,
                prompt='test prompt',
                ref_images_count=0,
                current_leg_id=leg.id,
                status=TaskStatus.processing,
            )
            await uow.users.add_balance_operation(
                user_id=user.id,
                amount=-amount,
                operation_type=OperationType.debit,
                reference_id=str(task.id),
                idempotency_key=f'gen:{task.id}',
            )
            await uow.users.increment_active_tasks(user.id)
            attempt = await uow.tasks.add_attempt(
                task_id=task.id,
                leg_id=leg.id,
                provider=leg.provider,
                external_id=f'{leg.provider.value}-{uuid.uuid4()}',
            )
            await uow.commit()
            created.append(
                {
                    'task_id': task.id,
                    'external_id': attempt.external_id,
                    'leg_id': leg.id,
                    'provider': leg.provider,
                }
            )
            return created[-1]

    yield _factory

    async with session_factory() as db_session:
        for item in created:
            task_id = item['task_id']
            await db_session.execute(text('DELETE FROM task_attempts WHERE task_id = :tid'), {'tid': task_id})
            await db_session.execute(
                text('DELETE FROM balance_operations WHERE idempotency_key = ANY(:keys)'),
                {'keys': [f'gen:{task_id}', f'refund:{task_id}']},
            )
            await db_session.execute(text('DELETE FROM tasks WHERE id = :tid'), {'tid': task_id})
        await db_session.commit()


@pytest_asyncio.fixture
async def concurrent_client(_check_db: None) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент, где каждый запрос получает свою сессию БД.

    Это нужно для честной проверки конкурентности: общая сессия сериализует запросы.
    """
    from src.app import app
    from src.core.db import get_db

    async def _fresh_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db_session:
            yield db_session

    app.dependency_overrides[get_db] = _fresh_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as http_client:
        yield http_client
    app.dependency_overrides.clear()


def signature_for(payload: dict[str, Any]) -> str:
    """Подпись вебхука для тела payload.

    Кодировка совпадает с httpx (`json=`): compact-разделители и ensure_ascii=False —
    иначе байты тела и подписанные байты разойдутся.
    """
    return sign_payload(payload_bytes(payload))


def payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


async def fetch(session: AsyncSession, model: Any, pk: Any) -> Any:
    """Читает объект, обновляя кэш identity map.

    Отношения с lazy='selectin' подтягивают связанные объекты в кэш заранее, поэтому
    обычный session.get вернул бы версию, устаревшую к моменту запроса.
    """
    return await session.get(model, pk, populate_existing=True)


async def fetch_all(session: AsyncSession, stmt: Any) -> list[Any]:
    """Выполняет SELECT, обновляя кэш identity map."""
    result = await session.execute(stmt.execution_options(populate_existing=True))
    return list(result.scalars().all())


@pytest.fixture
def external_id() -> str:
    return f'alpha-{uuid.uuid4()}'


@pytest.fixture
def mock_provider(monkeypatch):
    """Подменяет вызов провайдера — внешней зависимости в тестах нет.

    Возвращает список вызовов, чтобы проверять fallback.
    """
    import importlib

    from src.services import watchdog_service, webhook_service

    # src.integrations.__init__ переэкспортирует экземпляр под тем же именем,
    # поэтому модуль берём через importlib, а не через from-импорт пакета.
    provider_module = importlib.import_module('src.integrations.provider_client')

    calls: list[dict[str, Any]] = []

    async def _fake_send_task(
        provider,
        task_id,
        model_slug,
        prompt,
        ref_images,
    ) -> str:
        calls.append(
            {
                'provider': provider,
                'task_id': task_id,
                'model_slug': model_slug,
                'prompt': prompt,
                'ref_images': ref_images,
            }
        )
        return f'{provider.value}-{uuid.uuid4()}'

    # Патчим общий объект клиента и его импорты в сервисах.
    monkeypatch.setattr(provider_module.provider_client, 'send_task', _fake_send_task)
    monkeypatch.setattr(webhook_service.provider_client, 'send_task', _fake_send_task)
    monkeypatch.setattr(watchdog_service.provider_client, 'send_task', _fake_send_task)

    return calls
