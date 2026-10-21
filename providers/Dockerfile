FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /providers

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN uv pip install --system fastapi uvicorn httpx pydantic

COPY config.py provider_app.py ./

CMD ["uvicorn", "provider_app:app", "--host", "0.0.0.0", "--port", "8001"]
