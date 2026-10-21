"""Тест 3: первая нога падает с technical-ошибкой → задача завершается на второй."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import fetch, fetch_all, signature_for

from src.core.exceptions import ProviderUnavailableError
from src.models.model import ModelLeg, ProviderEnum
from src.models.task import ErrorType, Task, TaskAttempt, TaskStatus
from src.models.user import BalanceOperation, User


@pytest.mark.asyncio
async def test_leg_fallback_completes_on_second_leg(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    make_task,
    mock_provider,
) -> None:
    """Failed-вебхук первой ноги переключает задачу на вторую и сохраняет обе попытки."""
    created = await make_task(committed_user, provider=ProviderEnum.alpha)
    task_id = created['task_id']
    first_external_id = created['external_id']

    first_leg_id = created['leg_id']

    payload = {'external_id': first_external_id, 'status': 'failed', 'error_type': 'technical'}
    response = await concurrent_client.post(
        '/api/v1/webhooks/providers/alpha',
        json=payload,
        headers={'X-Signature': signature_for(payload)},
    )
    assert response.status_code == 200

    task = await fetch(session, Task, task_id)
    assert task is not None

    # Задача переключилась на вторую ногу и осталась в обработке.
    assert task.status == TaskStatus.processing
    assert task.current_leg_id != first_leg_id

    # В истории две попытки: первая провалена, вторая — новая.
    attempts = await fetch_all(
        session,
        select(TaskAttempt).where(TaskAttempt.task_id == task_id).order_by(TaskAttempt.started_at),
    )
    assert len(attempts) == 2
    assert attempts[0].error_type == ErrorType.technical
    assert attempts[0].completed_at is not None
    assert attempts[1].error_type is None
    assert attempts[1].completed_at is None
    assert attempts[1].leg_id == task.current_leg_id

    # Возврата токенов пока нет — задача не в терминальном статусе.
    refunds = await session.execute(
        select(func.count())
        .select_from(BalanceOperation)
        .where(BalanceOperation.idempotency_key == f'refund:{task_id}')
    )
    assert refunds.scalar_one() == 0

    # Провайдеру действительно ушла задача на второй ноге.
    assert len(mock_provider) == 1
    assert mock_provider[0]['provider'] == ProviderEnum.beta


@pytest.mark.asyncio
async def test_completed_webhook_on_second_leg_finishes_task(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    make_task,
    mock_provider,
) -> None:
    """Задача, ушедшая на вторую ногу, успешно завершается её вебхуком."""
    created = await make_task(committed_user, provider=ProviderEnum.beta)
    task_id = created['task_id']
    external_id = created['external_id']

    payload = {
        'external_id': external_id,
        'status': 'completed',
        'result_url': 'https://cdn.example.com/result.png',
    }
    response = await concurrent_client.post(
        '/api/v1/webhooks/providers/beta',
        json=payload,
        headers={'X-Signature': signature_for(payload)},
    )
    assert response.status_code == 200

    task = await fetch(session, Task, task_id)
    assert task is not None
    assert task.status == TaskStatus.completed
    assert task.result_url == 'https://cdn.example.com/result.png'


@pytest.mark.asyncio
async def test_sync_failure_on_first_leg_falls_back_to_second(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    monkeypatch,
) -> None:
    """Синхронный отказ первой ноги (503/timeout) ведёт на вторую ногу."""
    import importlib
    import uuid

    provider_module = importlib.import_module('src.integrations.provider_client')
    webhook_module = importlib.import_module('src.services.webhook_service')
    calls: list[dict[str, object]] = []

    async def _fake_send_task(provider, task_id, model_slug, prompt, ref_images):
        calls.append(
            {
                'provider': provider,
                'task_id': task_id,
                'model_slug': model_slug,
                'prompt': prompt,
                'ref_images': ref_images,
            }
        )
        if provider == ProviderEnum.alpha:
            raise ProviderUnavailableError('alpha down')
        return f'{provider.value}-fallback-{uuid.uuid4()}'

    monkeypatch.setattr(provider_module.provider_client, 'send_task', _fake_send_task)
    monkeypatch.setattr(webhook_module.provider_client, 'send_task', _fake_send_task)

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

    task = await fetch(session, Task, task_id)
    assert task is not None
    assert task.status == TaskStatus.processing

    legs = (
        (await session.execute(select(ModelLeg).where(ModelLeg.model_slug == 'image-fast').order_by(ModelLeg.priority)))
        .scalars()
        .all()
    )
    assert task.current_leg_id == legs[1].id  # beta

    attempts = await fetch_all(
        session,
        select(TaskAttempt).where(TaskAttempt.task_id == task_id).order_by(TaskAttempt.started_at),
    )
    assert len(attempts) == 2
    assert attempts[0].provider == ProviderEnum.alpha
    assert attempts[0].error_type == ErrorType.technical
    assert attempts[0].completed_at is not None
    assert attempts[1].provider == ProviderEnum.beta
    assert attempts[1].error_type is None
    assert attempts[1].completed_at is None

    # Возврата токенов пока нет — задача не в терминальном статусе.
    refunds = await session.execute(
        select(func.count())
        .select_from(BalanceOperation)
        .where(BalanceOperation.idempotency_key == f'refund:{task_id}')
    )
    assert refunds.scalar_one() == 0

    assert [c['provider'] for c in calls] == [ProviderEnum.alpha, ProviderEnum.beta]


@pytest.mark.asyncio
async def test_sync_failure_on_all_legs_refunds_once(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    monkeypatch,
) -> None:
    """Все ноги отвергли задачу синхронно → failed и ровно один возврат."""
    import importlib
    import uuid

    provider_module = importlib.import_module('src.integrations.provider_client')
    calls: list[dict[str, object]] = []

    async def _fake_send_task(provider, task_id, model_slug, prompt, ref_images):
        calls.append(
            {
                'provider': provider,
                'task_id': task_id,
                'model_slug': model_slug,
                'prompt': prompt,
                'ref_images': ref_images,
            }
        )
        raise ProviderUnavailableError(f'{provider.value} down')

    monkeypatch.setattr(provider_module.provider_client, 'send_task', _fake_send_task)

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

    task = await fetch(session, Task, task_id)
    assert task is not None
    assert task.status == TaskStatus.failed
    assert task.error_type == ErrorType.technical

    # Обе ноги tried.
    assert [c['provider'] for c in calls] == [ProviderEnum.alpha, ProviderEnum.beta]

    # Ровно один возврат и баланс как до генерации.
    refunds = await session.execute(
        select(func.count())
        .select_from(BalanceOperation)
        .where(BalanceOperation.idempotency_key == f'refund:{task_id}')
    )
    assert refunds.scalar_one() == 1
    balance = await session.execute(select(User.balance).where(User.id == committed_user.id))
    assert balance.scalar_one() == 100

    active = await session.execute(select(User.active_tasks).where(User.id == committed_user.id))
    assert active.scalar_one() == 0
