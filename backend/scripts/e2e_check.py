#!/usr/bin/env python3
"""Сквозной тест: платёж → генерация → вебхук провайдера → завершение задачи.

Запуск (из каталога backend, при поднятом docker compose):

    uv run python scripts/e2e_check.py или через make
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
    """Регистрация вне scope сервиса — создаём пользователя напрямую в БД."""
    from src.core.db import async_session_factory
    from src.models.user import User

    async def _create() -> str:
        async with async_session_factory() as session:
            user = User(balance=0, active_tasks=0)
            session.add(user)
            await session.commit()
            return str(user.id)

    return asyncio.run(_create())


def wait_for_task(task_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = httpx.get(f'{BACKEND}/api/v1/tasks/{task_id}', timeout=10)
        response.raise_for_status()
        payload = response.json()
        if payload['status'] in ('completed', 'failed'):
            return payload
        time.sleep(1)
    raise TimeoutError(f'Задача {task_id} не завершилась за {timeout}с')


def main() -> int:
    with httpx.Client(timeout=15) as client:
        # 0. Создаём пользователя (регистрация вне scope сервиса).
        user_id = create_user()
        print(f'0. Пользователь создан: {user_id}')

        # 1. Начисляем токены платёжным вебхуком.
        payment_id = f'pay-{uuid.uuid4()}'
        payment_payload = {'payment_id': payment_id, 'user_id': user_id, 'tokens': 100}
        payment_body = json.dumps(payment_payload, separators=(',', ':'), ensure_ascii=False).encode()
        response = client.post(
            f'{BACKEND}/api/v1/webhooks/payments',
            content=payment_body,
            headers={'X-Signature': sign(payment_body), 'Content-Type': 'application/json'},
        )
        print(f'1. Платёж: {response.status_code} {response.text.strip()}')
        assert response.status_code == 200, response.text

        # Повторный платёж с тем же payment_id — токены не должны начислиться дважды.
        response = client.post(
            f'{BACKEND}/api/v1/webhooks/payments',
            content=payment_body,
            headers={'X-Signature': sign(payment_body), 'Content-Type': 'application/json'},
        )
        assert response.status_code == 200, response.text

        # 2. Проверяем баланс.
        response = client.get(f'{BACKEND}/api/v1/users/{user_id}/balance')
        response.raise_for_status()
        balance = response.json()['balance']
        print(f'2. Баланс после дубля платежа: {balance} (ожидается 100)')
        assert balance == 100, f'Ожидался баланс 100, получен {balance}'

        # 3. Создаём задачу генерации.
        generate_payload = {
            'user_id': user_id,
            'model_slug': 'image-fast',
            'prompt': 'кот в шляпе',
            'ref_images': [],
        }
        response = client.post(f'{BACKEND}/api/v1/generate', json=generate_payload)
        print(f'3. Генерация: {response.status_code} {response.text.strip()}')
        assert response.status_code == 201, response.text
        task_id = response.json()['task_id']

        # 4. Ждём вебхук от провайдера.
        task = wait_for_task(task_id)
        print(f'4. Задача: статус={task["status"]} попыток={len(task["attempts"])}')
        for attempt in task['attempts']:
            print(f'   - {attempt["provider"]}: error={attempt["error_type"]}')
        assert task['status'] == 'completed', f'Задача не завершилась: {task}'

        # 5. Баланс после успешной генерации: 100 - 2 = 98.
        response = client.get(f'{BACKEND}/api/v1/users/{user_id}/balance')
        balance = response.json()['balance']
        print(f'5. Баланс после генерации: {balance} (ожидается 98)')
        assert balance == 98, f'Ожидался баланс 98, получен {balance}'

    print('\nE2E-проверка пройдена')
    return 0


if __name__ == '__main__':
    sys.exit(main())
