import hashlib
import hmac

from src.core.config import settings


def verify_signature(body: bytes, signature: str) -> bool:
    """Проверить HMAC-SHA256 подпись вебхука."""
    expected = hmac.new(
        settings.PROVIDER_SHARED_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def sign_payload(payload: bytes) -> str:
    """Создать HMAC-SHA256 подпись для исходящего вебхука."""
    return hmac.new(
        settings.PROVIDER_SHARED_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
