from http import HTTPStatus


class AppError(Exception):
    """Базовое доменное исключение: глобальный handler переводит его в HTTP-ответ.

    Статус и текст задаются наследником, поэтому роутерам не нужен try/except —
    они просто пробрасывают исключение сервиса наружу.
    """

    status_code: HTTPStatus = HTTPStatus.INTERNAL_SERVER_ERROR
    default_message: str = 'Внутренняя ошибка сервера'

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


# ==================== Generation Exceptions ====================


class InsufficientTokensError(AppError):
    """Недостаточно токенов на балансе для генерации."""

    status_code = HTTPStatus.PAYMENT_REQUIRED
    default_message = 'Недостаточно токенов на балансе'


class TooManyActiveTasksError(AppError):
    """Превышен лимит активных задач (максимум 3)."""

    status_code = HTTPStatus.TOO_MANY_REQUESTS
    default_message = 'Превышен лимит активных задач'


class NoSuitableLegError(AppError):
    """Нет подходящей ноги модели для заданного количества референсных изображений."""

    status_code = HTTPStatus.BAD_REQUEST
    default_message = 'Нет подходящей конфигурации модели для указанных параметров'


# ==================== Provider Exceptions ====================


class ProviderError(AppError):
    """Базовая ошибка провайдера."""

    status_code = HTTPStatus.BAD_GATEWAY
    default_message = 'Ошибка провайдера генерации'


class ProviderUnavailableError(ProviderError):
    """Провайдер временно недоступен (503/timeout) — можно попробовать следующую ногу."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    default_message = 'Провайдер временно недоступен'


# ==================== Webhook Exceptions ====================


class WebhookSignatureError(AppError):
    """Неверная подпись вебхука."""

    status_code = HTTPStatus.FORBIDDEN
    default_message = 'Неверная подпись вебхука'


class IdempotencyConflictError(AppError):
    """Конфликт идемпотентности: операция с таким ключом уже выполнялась."""

    status_code = HTTPStatus.CONFLICT
    default_message = 'Операция с таким ключом идемпотентности уже выполнена'
