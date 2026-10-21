"""Тест 4: watchdog сработал, затем пришёл late completed → результат игнорируется.

Правило 6: поздний `completed` после watchdog не сохраняет результат и не вызывает
повторный возврат — задача уже переведена на следующую ногу или провалена с возвратом.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import fetch, fetch_all, signature_for

from src.models.model import ProviderEnum
from src.models.task import ErrorType, Task, TaskAttempt, TaskStatus
from src.models.user import BalanceOperation, User


@pytest.mark.asyncio
async def test_late_completed_after_watchdog_is_ignored(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    make_task,
    mock_provider,
) -> None:
    """Watchdog переводит задачу на вторую ногу; поздний completed не меняет ничего."""
    created = await make_task(committed_user, provider=ProviderEnum.alpha)
    task_id = created['task_id']
    first_external_id = created['external_id']

    # Задача «зависла» — watchdog считает её устаревшей.
    task = await fetch(session, Task, task_id)
    assert task is not None
    task.updated_at = datetime.now(UTC) - timedelta(minutes=10)
    await session.commit()

    from src.repositories.unit_of_work import UnitOfWork
    from src.services.watchdog_service import WatchdogService

    uow = UnitOfWork(session)
    watchdog = WatchdogService(uow)
    await watchdog.check_stale_tasks()
    await uow.commit()

    attempts = await fetch_all(session, select(TaskAttempt).where(TaskAttempt.task_id == task_id))
    assert len(attempts) == 2
    first_attempt = attempts[0]

    # Watchdog пометил попытку как timeout и переключил на вторую ногу.
    assert first_attempt.error_type == ErrorType.timeout
    assert first_attempt.completed_at is not None

    task = await fetch(session, Task, task_id)
    assert task is not None
    assert task.status == TaskStatus.processing
    assert task.current_leg_id != created['leg_id']

    # Поздний completed от первой ноги — игнорируется.
    late_payload = {
        'external_id': first_external_id,
        'status': 'completed',
        'result_url': 'https://cdn.example.com/late.png',
    }
    response = await concurrent_client.post(
        '/api/v1/webhooks/providers/alpha',
        json=late_payload,
        headers={'X-Signature': signature_for(late_payload)},
    )
    assert response.status_code == 200

    task = await fetch(session, Task, task_id)
    assert task is not None

    # Результат не сохранён, статус не изменился.
    assert task.status == TaskStatus.processing
    assert task.result_url is None

    # Повторного возврата токенов не было.
    refunds = await session.execute(
        select(func.count())
        .select_from(BalanceOperation)
        .where(BalanceOperation.idempotency_key == f'refund:{task_id}')
    )
    assert refunds.scalar_one() == 0


@pytest.mark.asyncio
async def test_late_completed_after_failed_task_does_not_refund_twice(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    make_task,
    mock_provider,
) -> None:
    """Если задача уже провалена с возвратом, поздний completed не даёт второй возврат."""
    created = await make_task(committed_user, provider=ProviderEnum.beta)
    task_id = created['task_id']
    external_id = created['external_id']

    # Failed на последней ноге → задача failed, возврат токенов.
    failed_payload = {'external_id': external_id, 'status': 'failed', 'error_type': 'technical'}
    response = await concurrent_client.post(
        '/api/v1/webhooks/providers/beta',
        json=failed_payload,
        headers={'X-Signature': signature_for(failed_payload)},
    )
    assert response.status_code == 200

    task = await fetch(session, Task, task_id)
    assert task is not None
    assert task.status == TaskStatus.failed

    refunds = await session.execute(
        select(func.count())
        .select_from(BalanceOperation)
        .where(BalanceOperation.idempotency_key == f'refund:{task_id}')
    )
    assert refunds.scalar_one() == 1

    # Поздний completed не меняет статус и не добавляет возврат.
    late_payload = {
        'external_id': external_id,
        'status': 'completed',
        'result_url': 'https://cdn.example.com/late.png',
    }
    response = await concurrent_client.post(
        '/api/v1/webhooks/providers/beta',
        json=late_payload,
        headers={'X-Signature': signature_for(late_payload)},
    )
    assert response.status_code == 200

    task = await fetch(session, Task, task_id)
    assert task is not None
    assert task.status == TaskStatus.failed
    assert task.result_url is None

    refunds = await session.execute(
        select(func.count())
        .select_from(BalanceOperation)
        .where(BalanceOperation.idempotency_key == f'refund:{task_id}')
    )
    assert refunds.scalar_one() == 1
