"""Тест 2: 10 параллельных failed-вебхуков на последней ноге → ровно один возврат."""

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import fetch, signature_for

from src.models.model import ProviderEnum
from src.models.task import ErrorType, Task, TaskStatus
from src.models.user import BalanceOperation, User


@pytest.mark.asyncio
async def test_concurrent_failed_webhooks_refund_once(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
    make_task,
) -> None:
    """10 параллельных failed-вебхуков на последней ноге дают ровно один возврат."""
    # Задача на последней ноге image-fast (beta) — fallback'у некуда идти.
    created = await make_task(committed_user, provider=ProviderEnum.beta)
    external_id = created['external_id']

    payload = {'external_id': external_id, 'status': 'failed', 'error_type': 'technical'}

    responses = await asyncio.gather(
        *(
            concurrent_client.post(
                '/api/v1/webhooks/providers/beta',
                json=payload,
                headers={'X-Signature': signature_for(payload)},
            )
            for _ in range(10)
        )
    )

    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]

    # Ровно один возврат на 2 токена.
    refunds = await session.execute(
        select(func.count())
        .select_from(BalanceOperation)
        .where(BalanceOperation.idempotency_key == f'refund:{created["task_id"]}')
    )
    assert refunds.scalar_one() == 1

    # Баланс вернулся к исходным 100 (было списано 2, возвращено 2).
    balance = await session.execute(select(User.balance).where(User.id == committed_user.id))
    assert balance.scalar_one() == 100, 'Ожидался баланс 100 после возврата'

    # Задача в статусе failed.
    task = await fetch(session, Task, created['task_id'])
    assert task is not None
    assert task.status == TaskStatus.failed
    assert task.error_type == ErrorType.technical

    # Счётчик активных задач обнулён.
    active = await session.execute(select(User.active_tasks).where(User.id == committed_user.id))
    assert active.scalar_one() == 0
