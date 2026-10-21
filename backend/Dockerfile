FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /backend

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project


FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_NO_SYNC=1 \
    PATH="/usr/local/bin:${PATH}"

WORKDIR /backend

COPY --from=builder /usr/local /usr/local
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini .
COPY entrypoint.sh .

RUN chmod +x /backend/entrypoint.sh

ENTRYPOINT ["/backend/entrypoint.sh"]
