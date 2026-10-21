import contextlib

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel

from src.core.exceptions import WebhookSignatureError
from src.routers.deps import get_payment_service, get_webhook_service
from src.services.payment_service import PaymentService
from src.services.webhook_service import WebhookService

router = APIRouter(prefix='/api/v1', tags=['webhooks'])


class ProviderWebhookPayload(BaseModel):
    external_id: str
    status: str  # 'completed' | 'failed'
    error_type: str | None = None
    result_url: str | None = None


class PaymentWebhookPayload(BaseModel):
    payment_id: str
    user_id: str
    tokens: int


@router.post(
    '/webhooks/providers/{provider_name}',
    status_code=status.HTTP_200_OK,
)
async def provider_webhook(
    provider_name: str,
    request: Request,
    payload: ProviderWebhookPayload,
    x_signature: str = Header(alias='X-Signature'),
    service: WebhookService = Depends(get_webhook_service),
) -> dict[str, str]:
    """Вебхук от провайдеров генерации (alpha/beta). Всегда возвращает 200."""
    # Подпись сверяется с исходным телом: пересборка JSON ломает HMAC.
    body = await request.body()
    with contextlib.suppress(WebhookSignatureError):
        await service.handle_provider_webhook(
            body=body,
            payload=payload.model_dump(),
            signature=x_signature,
        )
    return {'status': 'ok'}


@router.post(
    '/webhooks/payments',
    status_code=status.HTTP_200_OK,
)
async def payment_webhook(
    request: Request,
    payload: PaymentWebhookPayload,
    x_signature: str = Header(alias='X-Signature'),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, str]:
    """Вебхук от платежной системы. Всегда возвращает 200."""
    body = await request.body()
    with contextlib.suppress(WebhookSignatureError):
        await service.handle_payment_webhook(
            body=body,
            payload=payload.model_dump(),
            signature=x_signature,
        )
    return {'status': 'ok'}
