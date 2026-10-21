import asyncio
import hashlib
import hmac
import json
import logging
import random
import uuid
from typing import Any

import httpx
from config import SyncFailure, config
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
logger = logging.getLogger('provider')


class TaskRequest(BaseModel):
    task_id: str
    model_slug: str
    prompt: str
    ref_images: list[str] = Field(default_factory=list)


class TaskAccepted(BaseModel):
    external_id: str
    status: str = 'accepted'


app = FastAPI(title=f'Fake provider {config.name}')


def _sign(body: bytes) -> str:
    return hmac.new(config.shared_secret.encode(), body, hashlib.sha256).hexdigest()


def _should_fail() -> bool:
    return random.random() < config.failure_rate  # noqa: S311


async def _send_webhook(
    external_id: str,
    status: str,
    error_type: str | None = None,
    result_url: str | None = None,
) -> None:
    """Отправить подписанный вебхук бэкенду."""
    payload: dict[str, Any] = {'external_id': external_id, 'status': status}
    if error_type:
        payload['error_type'] = error_type
    if result_url:
        payload['result_url'] = result_url

    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
    url = f'{config.webhook_base_url}/api/v1/webhooks/providers/{config.name}'

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            url,
            content=body,
            headers={'X-Signature': _sign(body), 'Content-Type': 'application/json'},
        )
        logger.info('Вебхук %s отправлен, статус %s', status, response.status_code)


async def _deliver_webhook(
    external_id: str,
    status: str,
    error_type: str | None = None,
    result_url: str | None = None,
) -> None:
    delay = random.uniform(config.webhook_delay_min, config.webhook_delay_max)  # noqa: S311
    await asyncio.sleep(delay)
    await _send_webhook(external_id, status, error_type, result_url)

    # Дубликат вебхука — проверка идемпотентности на стороне бэкенда.
    if config.duplicate_webhook:
        await _send_webhook(external_id, status, error_type, result_url)


@app.post('/tasks', response_model=TaskAccepted, status_code=202)
async def create_task(request: TaskRequest, background: BackgroundTasks) -> TaskAccepted:
    """Принять задачу и запланировать вебхук."""
    external_id = f'{config.name}-{uuid.uuid4()}'

    # Синхронный отказ: провайдер недоступен — бэкенд уйдёт на следующую ногу.
    if config.sync_failure == SyncFailure.unavailable:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail='Провайдер недоступен')

    if config.sync_failure == SyncFailure.timeout:
        await asyncio.sleep(120)

    if _should_fail():
        logger.info('Задача %s провалится с ошибкой %s', request.task_id, config.failure_type)
        background.add_task(
            _deliver_webhook,
            external_id,
            'failed',
            config.failure_type.value,
        )
        return TaskAccepted(external_id=external_id)

    if config.no_webhook:
        logger.info('Задача %s принята, вебхук не отправляется', request.task_id)
        return TaskAccepted(external_id=external_id)

    if config.late_completed:
        # Поздний completed: сначала провалим, чтобы watchdog успел сработать.
        background.add_task(_deliver_webhook, external_id, 'failed', 'technical')
        background.add_task(
            _deliver_webhook,
            external_id,
            'completed',
            None,
            f'https://cdn.example.com/{external_id}.png',
        )
        return TaskAccepted(external_id=external_id)

    logger.info('Задача %s принята, external_id=%s', request.task_id, external_id)
    background.add_task(
        _deliver_webhook,
        external_id,
        'completed',
        None,
        f'https://cdn.example.com/{external_id}.png',
    )
    return TaskAccepted(external_id=external_id)


@app.get('/config')
async def get_config() -> dict[str, Any]:
    """Текущие настройки поведения провайдера."""
    return {
        'name': config.name,
        'failure_rate': config.failure_rate,
        'failure_type': config.failure_type.value,
        'sync_failure': config.sync_failure.value,
        'duplicate_webhook': config.duplicate_webhook,
        'no_webhook': config.no_webhook,
        'late_completed': config.late_completed,
    }


@app.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}
