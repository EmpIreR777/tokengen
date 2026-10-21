"""Тест 1: 20 параллельных одинаковых payment-вебхуков → ровно один кредит."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import signature_for

from src.models.payment import PaymentWebhook
from src.models.user import BalanceOperation, User


async def _balance(session: AsyncSession, user_id) -> int:
    result = await session.execute(select(User.balance).where(User.id == user_id))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_concurrent_payment_webhooks_credit_once(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
) -> None:
    """20 параллельных вебхуков с одним payment_id дают ровно один кредит."""
    payment_id = f'pay-{uuid.uuid4()}'
    tokens = 50

    payload = {'payment_id': payment_id, 'user_id': str(committed_user.id), 'tokens': tokens}

    responses = await asyncio.gather(
        *(
            concurrent_client.post(
                '/api/v1/webhooks/payments',
                json=payload,
                headers={'X-Signature': signature_for(payload)},
            )
            for _ in range(20)
        )
    )

    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]

    # Баланс вырос ровно на tokens, а не на tokens * 20.
    balance = await _balance(session, committed_user.id)
    assert balance == 100 + tokens, f'Ожидался баланс {100 + tokens}, получен {balance}'

    # Ровно одна операция начисления с этим ключом идемпотентности.
    operations = await session.execute(
        select(func.count())
        .select_from(BalanceOperation)
        .where(BalanceOperation.idempotency_key == f'payment:{payment_id}')
    )
    assert operations.scalar_one() == 1

    # Ровно одна запись в payment_webhooks.
    webhooks = await session.execute(
        select(func.count()).select_from(PaymentWebhook).where(PaymentWebhook.payment_id == payment_id)
    )
    assert webhooks.scalar_one() == 1


@pytest.mark.asyncio
async def test_payment_webhook_with_invalid_signature_is_ignored(
    concurrent_client: AsyncClient,
    session: AsyncSession,
    committed_user: User,
) -> None:
    """Вебхук с неверной подписью не начисляет токены."""
    payment_id = f'pay-{uuid.uuid4()}'
    payload = {'payment_id': payment_id, 'user_id': str(committed_user.id), 'tokens': 50}

    response = await concurrent_client.post(
        '/api/v1/webhooks/payments',
        json=payload,
        headers={'X-Signature': 'deadbeef' * 8},
    )

    assert response.status_code == 200

    balance = await _balance(session, committed_user.id)
    assert balance == 100
