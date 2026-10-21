import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.core.exceptions import AppError

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """Приводит значение к JSON-совместимому виду.

    В ошибках валидации FastAPI встречаются байты (например, тело запроса
    без Content-Type) — их нельзя отдать в JSONResponse как есть.
    """
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 на невалидные входные данные Pydantic."""
    errors = _json_safe(exc.errors())
    logger.warning('Ошибка валидации на %s %s: %s', request.method, request.url.path, errors)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={'detail': errors},
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Перевод доменных исключений в HTTP-коды — единая точка вместо try/except в роутерах."""
    logger.warning('Ошибка домена %s на %s %s: %s', exc.status_code, request.method, request.url.path, exc.message)
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.message})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """500 на любую неожиданную ошибку — наружу не отдаём детали, только в лог."""
    logger.exception('Необработанная ошибка на %s %s', request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={'detail': 'Internal Server Error'},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Подключить глобальные обработчики ошибок к приложению."""
    # Starlette типизирует add_exception_handler под общий Exception, хотя в рантайме
    # сопоставляет хендлер по MRO типа исключения — точечные ignore штатны.
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
