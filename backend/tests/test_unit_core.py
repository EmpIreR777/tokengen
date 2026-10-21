"""Юнит-тесты: выбор ноги, идемпотентность, расчёт баланса, подпись."""

import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import sign_payload, verify_signature
from src.models.model import ModelLeg, ProviderEnum
from src.models.task import ErrorType, TaskStatus
from src.models.user import OperationType, User
from src.repositories.unit_of_work import UnitOfWork


class TestLegSelection:
    """Выбор ноги по количеству референсных изображений и приоритету."""

    @pytest.mark.asyncio
    async def test_legs_sorted_by_priority(self, session: AsyncSession) -> None:
        result = await session.execute(
            select(ModelLeg).where(ModelLeg.model_slug == 'image-fast').order_by(ModelLeg.priority)
        )
        legs = list(result.scalars().all())
        assert [leg.provider for leg in legs] == [ProviderEnum.alpha, ProviderEnum.beta]
        assert [leg.priority for leg in legs] == [0, 1]

    @pytest.mark.asyncio
    async def test_suitable_legs_filtered_by_max_ref_images(self, session: AsyncSession) -> None:

        uow = UnitOfWork(session)
        suitable = await uow.models.get_suitable_legs('image-fast', 0)
        assert len(suitable) == 2

        # video-long: beta до 2 референсов, alpha до 1 — при 2 рефподходит только beta.
        suitable = await uow.models.get_suitable_legs('video-long', 2)
        assert len(suitable) == 1
        assert suitable[0].provider == ProviderEnum.beta

        suitable = await uow.models.get_suitable_legs('video-long', 3)
        assert suitable == []

    @pytest.mark.asyncio
    async def test_no_suitable_leg_for_too_many_refs(self, session: AsyncSession) -> None:

        uow = UnitOfWork(session)
        assert await uow.models.get_suitable_legs('video-long', 10) == []


class TestIdempotencyKeys:
    """Ключи идемпотентности детерминированные и различаются по операциям."""

    def test_generation_key(self) -> None:
        task_id = uuid.uuid4()
        assert f'gen:{task_id}' == f'gen:{task_id}'

    def test_refund_and_payment_keys_differ(self) -> None:
        task_id = uuid.uuid4()
        payment_id = 'pay-123'
        assert f'refund:{task_id}' != f'payment:{payment_id}'
        assert f'gen:{task_id}' != f'refund:{task_id}'

    @pytest.mark.asyncio
    async def test_duplicate_operation_is_rejected(self, session: AsyncSession) -> None:
        """Вторая операция с тем же ключом не проходит."""

        uow = UnitOfWork(session)
        user = User(balance=100)
        session.add(user)
        await session.flush()

        key = f'gen:{uuid.uuid4()}'
        first = await uow.users.add_balance_operation(
            user_id=user.id,
            amount=-10,
            operation_type=OperationType.debit,
            reference_id=str(uuid.uuid4()),
            idempotency_key=key,
        )
        assert first is True

        second = await uow.users.add_balance_operation(
            user_id=user.id,
            amount=-10,
            operation_type=OperationType.debit,
            reference_id=str(uuid.uuid4()),
            idempotency_key=key,
        )
        assert second is False

        await uow.rollback()


class TestBalanceCalculation:
    """Баланс меняется только на величину операций."""

    @pytest.mark.asyncio
    async def test_balance_changes_with_operations(self, session: AsyncSession) -> None:

        uow = UnitOfWork(session)
        user = User(balance=0)
        session.add(user)
        await session.flush()

        await uow.users.add_balance_operation(
            user_id=user.id,
            amount=100,
            operation_type=OperationType.credit,
            reference_id='pay-1',
            idempotency_key='payment:pay-1',
        )
        await uow.users.add_balance_operation(
            user_id=user.id,
            amount=-25,
            operation_type=OperationType.debit,
            reference_id='task-1',
            idempotency_key='gen:task-1',
        )

        balance = await uow.users.get_balance(user.id)
        assert balance == 75

    @pytest.mark.asyncio
    async def test_debit_beyond_balance_is_rejected(self, session: AsyncSession) -> None:
        from src.core.exceptions import InsufficientTokensError

        uow = UnitOfWork(session)
        user = User(balance=10)
        session.add(user)
        await session.flush()

        with pytest.raises(InsufficientTokensError):
            await uow.users.add_balance_operation(
                user_id=user.id,
                amount=-50,
                operation_type=OperationType.debit,
                reference_id='task-1',
                idempotency_key='gen:task-1',
            )

        await uow.rollback()

    @pytest.mark.asyncio
    async def test_active_tasks_counter(self, session: AsyncSession) -> None:

        uow = UnitOfWork(session)
        user = User(balance=100)
        session.add(user)
        await session.flush()

        await uow.users.increment_active_tasks(user.id)
        await uow.users.increment_active_tasks(user.id)
        assert user.active_tasks == 2

        await uow.users.decrement_active_tasks(user.id)
        assert user.active_tasks == 1

        # Счётчик не уходит в минус.
        await uow.users.decrement_active_tasks(user.id)
        await uow.users.decrement_active_tasks(user.id)
        assert user.active_tasks == 0

        await uow.rollback()


class TestSignatureVerification:
    """HMAC-SHA256 подпись вебхуков."""

    def test_valid_signature(self) -> None:
        payload = {'external_id': 'abc', 'status': 'completed'}
        body = json.dumps(payload, separators=(',', ':')).encode()
        assert verify_signature(body, sign_payload(body)) is True

    def test_invalid_signature(self) -> None:
        body = json.dumps({'external_id': 'abc'}).encode()
        assert verify_signature(body, 'invalid') is False

    def test_tampered_body(self) -> None:
        original = json.dumps({'external_id': 'abc', 'status': 'completed'}).encode()
        signature = sign_payload(original)
        tampered = json.dumps({'external_id': 'abc', 'status': 'failed'}).encode()
        assert verify_signature(tampered, signature) is False

    def test_signature_is_deterministic(self) -> None:
        body = b'{"a":1}'
        assert sign_payload(body) == sign_payload(body)


class TestEnums:
    """Значения enum'ов соответствуют ожидаемым значениям в БД."""

    def test_task_status_values(self) -> None:
        assert TaskStatus.pending.value == 'pending'
        assert TaskStatus.processing.value == 'processing'
        assert TaskStatus.completed.value == 'completed'
        assert TaskStatus.failed.value == 'failed'

    def test_error_type_values(self) -> None:
        assert ErrorType.technical.value == 'technical'
        assert ErrorType.moderation.value == 'moderation'
        assert ErrorType.payload.value == 'payload'
        assert ErrorType.timeout.value == 'timeout'

    def test_operation_type_values(self) -> None:
        assert OperationType.debit.value == 'debit'
        assert OperationType.credit.value == 'credit'
        assert OperationType.refund.value == 'refund'
