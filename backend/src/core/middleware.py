import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_request_id_var: ContextVar[str | None] = ContextVar('request_id', default=None)


def get_request_id() -> str | None:
    """Получить request_id текущего запроса."""
    return _request_id_var.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware для добавления request_id в контекст логирования."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
        token = _request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers['X-Request-ID'] = request_id
            return response
        finally:
            _request_id_var.reset(token)
