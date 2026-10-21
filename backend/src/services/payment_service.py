import logging
from typing import Any
from uuid import UUID

from src.core.exceptions import WebhookSignatureError
from src.core.security import verify_signature
from src.models.user import OperationType
from src.repositories.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def handle_payment_webhook(
        self,
        body: bytes,
        payload: dict[str, Any],
        signature: str,
    ) -> None:
        # Подпись проверяется по исходному телу запроса — пересборка JSON ломает HMAC.
        if not verify_signature(body, signature):
            raise WebhookSignatureError('Неверная подпись вебхука платежа')

        payment_id = payload.get('payment_id')
        user_id = payload.get('user_id')
        tokens = payload.get('tokens')

        if not payment_id or not user_id or not tokens:
            logger.warning('Платёжный вебхук без обязательных полей — игнорируем')
            return

        parsed_user_id = UUID(str(user_id))
        parsed_payment_id = str(payment_id)
        amount = int(tokens)

        # Неизвестный пользователь — постоянная ошибка, повтор не поможет.
        if await self.uow.users.get_by_id(parsed_user_id) is None:
            logger.warning('Платёж %s ссылается на неизвестного пользователя %s', parsed_payment_id, parsed_user_id)
            return

        # Идемпотентность: уникальный ключ на payment_id в БД.
        _webhook, created = await self.uow.payments.create_if_not_exists(
            payment_id=parsed_payment_id,
            user_id=parsed_user_id,
            tokens=amount,
        )

        if not created:
            return  # уже обработан

        async with self.uow:
            # Начисляем токены
            credited = await self.uow.users.add_balance_operation(
                user_id=parsed_user_id,
                amount=amount,
                operation_type=OperationType.credit,
                reference_id=parsed_payment_id,
                idempotency_key=f'payment:{parsed_payment_id}',
            )
            if not credited:
                await self.uow.rollback()
                return

            # Помечаем вебхук как обработанный
            await self.uow.payments.mark_processed(parsed_payment_id)

            await self.uow.commit()
