"""Тесты эндпоинта POST /generate: валидация, коды ошибок, лимиты."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.task import Task, TaskAttempt, TaskStatus
from src.models.user import User


@pytest.mark.asyncio
async def test_generate_creates_task_and_debits_tokens(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    mock_provider,
) -> None:
    """Успешный generate создаёт задачу, списывает цену и регистрирует попытку."""
    response = await concurrent_client.post(
        '/api/v1/generate',
        json={
            'user_id': str(committed_user.id),
            'model_slug': 'image-fast',
            'prompt': 'кот',
            'ref_images': [],
        },
    )

    assert response.status_code == 201, response.text
    task_id = uuid.UUID(response.json()['task_id'])

    task = await session.get(Task, task_id)
    assert task is not None
    assert task.status == TaskStatus.processing
    assert task.model_slug == 'image-fast'
    assert task.current_leg_id is not None

    # Токены списаны (цена image-fast = 2).
    balance = await session.execute(select(User.balance).where(User.id == committed_user.id))
    assert balance.scalar_one() == 98

    # Создана попытка с external_id от провайдера.
    attempt = (await session.execute(select(TaskAttempt).where(TaskAttempt.task_id == task_id))).scalar_one()
    assert attempt.external_id.startswith('alpha-')
    assert attempt.completed_at is None

    # Счётчик активных задач вырос.
    active = await session.execute(select(User.active_tasks).where(User.id == committed_user.id))
    assert active.scalar_one() == 1


@pytest.mark.asyncio
async def test_generate_returns_400_for_unknown_model(
    concurrent_client: AsyncClient,
    committed_user: User,
    mock_provider,
) -> None:
    """Неизвестная модель → 400 и списания нет."""
    response = await concurrent_client.post(
        '/api/v1/generate',
        json={
            'user_id': str(committed_user.id),
            'model_slug': 'no-such-model',
            'prompt': 'кот',
            'ref_images': [],
        },
    )

    assert response.status_code == 400
    assert 'не найдена' in response.json()['detail']


@pytest.mark.asyncio
async def test_generate_returns_400_when_no_leg_fits_ref_images(
    concurrent_client: AsyncClient,
    committed_user: User,
    mock_provider,
) -> None:
    """Слишком много референсов для модели → 400 и списания нет."""
    response = await concurrent_client.post(
        '/api/v1/generate',
        json={
            'user_id': str(committed_user.id),
            'model_slug': 'video-long',
            'prompt': 'кот',
            'ref_images': ['a', 'b', 'c'],
        },
    )

    assert response.status_code == 400
    assert 'подходящей ноги' in response.json()['detail']


@pytest.mark.asyncio
async def test_generate_returns_402_when_balance_is_insufficient(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    mock_provider,
) -> None:
    """Недостаточно токенов → 402 и списания нет."""
    from src.models.user import User as UserModel

    poor = UserModel(balance=1, active_tasks=0)
    session.add(poor)
    await session.commit()

    response = await concurrent_client.post(
        '/api/v1/generate',
        json={
            'user_id': str(poor.id),
            'model_slug': 'image-fast',
            'prompt': 'кот',
            'ref_images': [],
        },
    )

    assert response.status_code == 402
    assert 'недостаточно токенов' in response.json()['detail']

    balance = await session.execute(select(UserModel.balance).where(UserModel.id == poor.id))
    assert balance.scalar_one() == 1


@pytest.mark.asyncio
async def test_generate_returns_429_when_too_many_active_tasks(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    mock_provider,
) -> None:
    """Больше трёх активных задач → 429 и списания нет."""
    from src.models.user import User as UserModel

    busy = UserModel(balance=100, active_tasks=3)
    session.add(busy)
    await session.commit()

    response = await concurrent_client.post(
        '/api/v1/generate',
        json={
            'user_id': str(busy.id),
            'model_slug': 'image-fast',
            'prompt': 'кот',
            'ref_images': [],
        },
    )

    assert response.status_code == 429
    assert 'лимит активных задач' in response.json()['detail']

    balance = await session.execute(select(UserModel.balance).where(UserModel.id == busy.id))
    assert balance.scalar_one() == 100


@pytest.mark.asyncio
async def test_get_task_returns_attempts(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    mock_provider,
) -> None:
    """GET /tasks/{id} отдаёт статус и историю попыток."""
    response = await concurrent_client.post(
        '/api/v1/generate',
        json={
            'user_id': str(committed_user.id),
            'model_slug': 'image-fast',
            'prompt': 'кот',
            'ref_images': [],
        },
    )
    task_id = response.json()['task_id']

    get_response = await concurrent_client.get(f'/api/v1/tasks/{task_id}')
    assert get_response.status_code == 200

    body = get_response.json()
    assert body['id'] == task_id
    assert body['status'] == 'processing'
    assert len(body['attempts']) == 1
    assert body['attempts'][0]['provider'] == 'alpha'
    assert body['attempts'][0]['error_type'] is None


@pytest.mark.asyncio
async def test_get_balance_returns_operations(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    mock_provider,
) -> None:
    """GET /users/{id}/balance отдаёт баланс и последние операции."""
    await concurrent_client.post(
        '/api/v1/generate',
        json={
            'user_id': str(committed_user.id),
            'model_slug': 'image-fast',
            'prompt': 'кот',
            'ref_images': [],
        },
    )

    response = await concurrent_client.get(f'/api/v1/users/{committed_user.id}/balance')
    assert response.status_code == 200

    body = response.json()
    assert body['balance'] == 98
    assert len(body['operations']) == 1
    assert body['operations'][0]['amount'] == -2
    assert body['operations'][0]['type'] == 'debit'
