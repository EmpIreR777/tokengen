#!/usr/bin/env python3
"""Сквозной тест watchdog: провайдер не отвечает → watchdog переводит задачу на вторую ногу.

Запуск (из каталога backend, при поднятом docker compose):

    PROVIDER_ALPHA_NO_WEBHOOK=true PROVIDER_TIMEOUT=15 docker compose up -d
    uv run python scripts/e2e_watchdog.py или через make
"""

import asyncio
import hashlib
import hmac
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BACKEND = 'http://localhost:8000'
SECRET = 'dev-secret-change-in-production'  # noqa: S105


def sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def create_user() -> str:
    from src.core.db import async_session_factory
    from src.models.user import User

    async def _create() -> str:
        async with async_session_factory() as session:
            user = User(balance=0, active_tasks=0)
            session.add(user)
            await session.commit()
            return str(user.id)

    return asyncio.run(_create())


def main() -> int:
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0

    with httpx.Client(timeout=15) as client:
        user_id = create_user()
        payment_id = f'pay-{uuid.uuid4()}'
        payment_payload = {'payment_id': payment_id, 'user_id': user_id, 'tokens': 100}
        payment_body = json.dumps(payment_payload, separators=(',', ':'), ensure_ascii=False).encode()
        client.post(
            f'{BACKEND}/api/v1/webhooks/payments',
            content=payment_body,
            headers={'X-Signature': sign(payment_body), 'Content-Type': 'application/json'},
        )

        response = client.post(
            f'{BACKEND}/api/v1/generate',
            json={
                'user_id': user_id,
                'model_slug': 'image-fast',
                'prompt': 'кот',
                'ref_images': [],
            },
        )
        assert response.status_code == 201, response.text
        task_id = response.json()['task_id']
        print(f'Задача создана: {task_id}')

        deadline = time.time() + timeout
        while time.time() < deadline:
            task = client.get(f'{BACKEND}/api/v1/tasks/{task_id}').json()
            attempts = [(a['provider'], a['error_type']) for a in task['attempts']]
            print(f'  статус={task["status"]} попытки={attempts}')
            if task['status'] in ('completed', 'failed'):
                break
            time.sleep(3)

        assert task['status'] == 'completed', f'Задача не завершилась: {task}'
        providers = [a['provider'] for a in task['attempts']]
        assert providers == ['alpha', 'beta'], f'Ожидались обе ноги, получено {providers}'
        assert task['attempts'][0]['error_type'] == 'timeout', task['attempts'][0]

        balance = client.get(f'{BACKEND}/api/v1/users/{user_id}/balance').json()['balance']
        print(f'Баланс: {balance} (ожидается 98)')
        assert balance == 98, f'Ожидался баланс 98, получен {balance}'

    print('\nWatchdog-проверка пройдена')
    return 0


if __name__ == '__main__':
    sys.exit(main())
