from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import IdempotencyConflictError
from src.models.payment import PaymentWebhook, PaymentWebhookStatus


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_if_not_exists(
        self,
        payment_id: str,
        user_id: UUID,
        tokens: int,
    ) -> tuple[PaymentWebhook, bool]:
        """Создать вебхук платежа если не существует. Возвращает (webhook, created)."""
        existing = await self.get_by_payment_id(payment_id)
        if existing is not None:
            return existing, False

        webhook = PaymentWebhook(
            payment_id=payment_id,
            user_id=user_id,
            tokens=tokens,
            status=PaymentWebhookStatus.received,
        )
        self.session.add(webhook)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            # Гонка: параллельный запрос успел вставить тот же payment_id.
            existing = await self.get_by_payment_id(payment_id)
            if existing is not None:
                return existing, False
            # Остальные нарушения целостности (например, неизвестный user_id) —
            # это не конфликт идемпотентности, отдаём исходную ошибку.
            raise IdempotencyConflictError(
                f'Не удалось сохранить платёж {payment_id}: нарушение целостности данных'
            ) from exc
        return webhook, True

    async def get_by_payment_id(self, payment_id: str) -> PaymentWebhook | None:
        result = await self.session.execute(select(PaymentWebhook).where(PaymentWebhook.payment_id == payment_id))
        return result.scalar_one_or_none()

    async def mark_processed(self, payment_id: str) -> None:
        webhook = await self.get_by_payment_id(payment_id)
        if webhook:
            webhook.status = PaymentWebhookStatus.processed
            await self.session.flush()
