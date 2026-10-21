# tokengen

Сервис генерации токенов: принимает заявку на генерацию, списывает токены с баланса
пользователя, отправляет задачу провайдеру (alpha/beta), обрабатывает вебхуки провайдеров
и возвращает токены при неудаче.

Ключевые свойства: **exactly-once** по начислению/возврату токенов, **fallback** между
ногами модели, **watchdog** для зависших задач.

---

## Стек

Python 3.14 · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic 2 · pydantic-settings · APScheduler ·
PostgreSQL 16 · httpx · uv · pytest

Celery/RabbitMQ/Redis не используются: watchdog работает на APScheduler внутри процесса бэкенда,
координация — через advisory lock в PostgreSQL.

---

## Быстрый старт

Через Makefile (рекомендуется):

```bash
cp .env.example .env
make up            # поднимет db, backend, provider-alpha, provider-beta
make logs          # логи всех сервисов
```

Или напрямую через docker compose:

```bash
cp .env.example .env
docker compose up -d
make logs
```

Остановка и очистка:

```bash
make down
make clean
```

Миграции применяются автоматически при старте контейнера (`entrypoint.sh`).

Проверка:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Провайдеры:

- http://localhost:8001 — provider-alpha
- http://localhost:8002 — provider-beta

---

## Изменения в среде выполнения

### `.env` теперь в корне проекта

Бэкенд читает настройки из корневого `.env`, а не из `backend/.env`. Файлы
`backend/.env` и `backend/.env.example` удалены.

Для локальных тестов на хосте в корневом `.env`:

```
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
```

В `docker-compose.yml` для сервиса `backend` внутри сети Docker:
`POSTGRES_HOST=db`, `POSTGRES_PORT=5432`.

### Docker Compose

| Сервис | Хост:порт (с хоста) | Внутри сети |
|--------|---------------------|-------------|
| postgres | localhost:5433 | db:5432 |
| backend | http://localhost:8000 | — |
| provider-alpha | http://localhost:8001 | — |
| provider-beta | http://localhost:8002 | — |

### 4 воркера бэкенда

Приложение запускается как 4 синхронных воркера:
`uv run uvicorn src.app:app --host 127.0.0.1 --port 8000 --workers 4`.

Воркеры разделяют обработку: watchdog, сервисные действия и обработка вебхуков
должны быть синхронными, чтобы локальные ограничения механизма блокировок не
мешали обработке вебхука.

---

## Команды Makefile

В проекте есть два Makefile: корневой (docker compose) и в `backend/`.

### Корневой Makefile (docker compose)

| Команда | Смысл |
|---------|-------|
| `make up` | Собрать и запустить db, backend, alpha, beta |
| `make down` | Остановить контейнеры |
| `make logs` | Логи в реальном времени |
| `make clean` | Остановка с удалением volumes |

### Makefile в `backend/` (разработка)

| Команда | Смысл |
|---------|-------|
| `make run` | Запустить сервер с reload |
| `make sync` | Установить зависимости (включая dev-группу) |
| `make alembic-rev m="..."` | Создать миграцию |
| `make alembic-up` | Применить миграции |
| `make alembic-down` | Откатить на 1 |
| `make lint` | pre-commit (ruff, mypy, codespell) |
| `make ruff` | ruff check + format |
| `make mypy` | типовая проверка |
| `make test` | запуск тестов |
| `make e2e` | сквозные проверки (требуют поднятого compose) |
| `make e2e-watchdog` | e2e для watchdog |
| `make clean-cache` | очистка кешей |

---

## Структура

```
backend/
  src/
    core/          config, db, exceptions, logging, security, middleware, exception_handlers
    models/        SQLAlchemy 2 модели (users, models, model_legs, tasks, task_attempts, …)
    repositories/  доступ к БД + UnitOfWork
    services/      бизнес-логика: generation, webhook, payment, watchdog
    integrations/  HTTP-клиент к провайдерам
    routers/       HTTP-слой (валидация, тонкий)
    tasks/         APScheduler-задачи (watchdog)
  alembic/         миграции
  tests/           интеграционные и юнит-тесты
providers/         фейковые провайдеры alpha/beta (отдельный FastAPI-сервис)
```

Слои: `routers → services → repositories / integrations`. Роутеры не содержат
бизнес-логики, сервисы не знают про HTTP.

---

## API

### `POST /api/v1/generate`

```json
{
  "user_id": "uuid",
  "model_slug": "image-fast",
  "prompt": "кот в шляпе",
  "ref_images": []
}
```

Ответ `201`: `{"task_id": "uuid"}`

| Код | Причина |
|-----|---------|
| 400 | модель не найдена или нет ноги под число референсов |
| 402 | недостаточно токенов на балансе |
| 429 | больше 3 активных задач у пользователя |

### `POST /api/v1/webhooks/providers/{provider_name}`

Вебхук от провайдера. Подпись — `X-Signature` (HMAC-SHA256 от тела запроса).

```json
{"external_id": "alpha-...", "status": "completed", "result_url": "https://..."}
```

```json
{"external_id": "alpha-...", "status": "failed", "error_type": "technical"}
```

Всегда отвечает `200`: провайдер не должен ретратить вебхук, который мы уже учли,
или подпись которого не совпала.

### `POST /api/v1/webhooks/payments`

```json
{"payment_id": "pay-1", "user_id": "uuid", "tokens": 100}
```

### `GET /api/v1/tasks/{task_id}`

Статус задачи, текущая нога, история попыток.

### `GET /api/v1/users/{user_id}/balance`

Баланс и логи.

### `GET /health`

Проверка живости БД.

---

## Доменные правила

| Ошибка провайдера | Реакция |
|-------------------|---------|
| `technical` (5xx, таймаут) | следующая нога |
| `timeout` (watchdog) | следующая нога |
| `moderation` | следующая нога, если у неё `skip_on_moderation = false` |
| `payload` | задача `failed`, возврат токенов один раз |

Ноги кончились — задача `failed`, токены возвращаются.

### Идемпотентность (ровно один раз)

Ключи детерминированные, уникальность обеспечена на уровне БД:

| Операция | Ключ |
|----------|------|
| Списание за генерацию | `gen:{task_id}` |
| Начисление за платёж | `payment:{payment_id}` |
| Возврат | `refund:{task_id}` |

Повторный вебхук с тем же `payment_id` не начислит токены повторно: уникальный
индекс не даст создать вторую операцию, а транзакция откатится. То же самое —
для возврата токенов по `refund:{task_id}`.

### Что будет при падении процесса посреди обработки вебхука

Все изменения баланса и статуса задачи делаются в одной транзакции
PostgreSQL:
- если процесс падает **до коммита**, транзакция откатывается и задача
  остаётся в предыдущем состоянии — с точки зрения провайдера вебхук не
  доставлен;
- если процесс упал **после коммита**, но до ответа провайдеру, повторы вебхука
  не навредит: повторный вебхук с тем же `external_id` не создаст вторую
  операцию (попытка уже помечена завершённой), а повторный платёж — не начислит
  токены второй раз.

Задачу, которую провайдер принял, но чей вебхук так и не пришёл, перехватит
сторож (watchdog) по истечении `PROVIDER_TIMEOUT` секунд — она пойдёт по тем же
правилам: следующая нога или единственный возврат токенов.

### Правило 6: поздний `completed` после сторожа

Если watchdog уже перевёл задачу на следующую ногу или провалил её с возвратом
токенов, а потом приходит `completed` — **результат игнорируется**, логируется
предупреждение:

```
Late completed ignored for task {task_id}: already failed
```

Обоснование: состояние задачи уже изменено сторожем. Принятие позднего
результата нарушило бы «ровно один раз» и консистентность: задача получила бы
результат от попытки, которая была признана неуспешной, а возврат токенов мог
бы произойти дважды.

### Watchdog

Каждые 10 секунд каждый из 4 воркеров бэкенда запускает проверку, но проход
выполняет ровно один: `pg_try_advisory_lock(12345)` гарантирует, что остальные
пропускают итерацию. Lock сессионный — гарантированно снимается при закрытии
сессии (включая падение процесса).

Задача считается зависшей, если она в статусе `processing` дольше
`PROVIDER_TIMEOUT` секунд. Дальше — та же логика, что при `technical`-ошибке.

---

## Каталог моделей

Заполняется миграцией `a1b2c3d4e5f6`:

| slug | цена | ноги |
|------|------|------|
| `image-fast` | 2 | alpha (приоритет 0, до 4 референсов), beta (приоритет 1, до 4) |
| `video-long` | 25 | beta (приоритет 0, до 2, `skip_on_moderation=true`), alpha (приоритет 1, до 1) |

Нога подходит, если `max_ref_images >= кол-во референсов`. Если не подходит ни
одна — `400` до списания денег.

---

## Фейковые провайдеры

Фейковые провайдеры alpha/beta в каталоге `providers/` — референсная
реализация. Подключение другого провайдера сводится к добавлению ветки в
`src/integrations/provider_client.py` (`_get_provider_url`) и значения в
`ProviderEnum` (`src/models/model.py`); остальная логика не меняется.

Подробности — в [providers/README.md](providers/README.md).

Поведение задаётся переменными окружения (см. `docker-compose.yml`):

| Переменная | Значения | Смысл |
|------------|----------|-------|
| `FAILURE_RATE` | `0.0`…`1.0` | доля задач, которые падают |
| `FAILURE_TYPE` | `technical`, `moderation`, `payload` | тип ошибки |
| `SYNC_FAILURE` | `none`, `503`, `timeout` | отказ на этапе `POST /tasks` |
| `DUPLICATE_WEBHOOK` | `true`/`false` | отправлять вебхук дважды |
| `NO_WEBHOOK` | `true`/`false` | не отправлять вебхук вовсе (сценарий watchdog) |
| `LATE_COMPLETED` | `true`/`false` | сначала `failed`, потом `completed` (сценарий правила 6) |

Пример: включить поздний `completed` у alpha.

```bash
PROVIDER_ALPHA_LATE_COMPLETED=true docker compose up -d provider-alpha
```

---

## Разработка

### Корневой Makefile (docker compose)

```bash
make up            # сборка и запуск всех сервисов
make down          # остановка
make logs          # логи в реальном времени
make clean         # остановка с удалением volumes
```

### Бэкенд (backend/Makefile)

```bash
cd backend
make sync          # установить зависимости
make run           # uvicorn с reload
make alembic-rev m="описание"   # новая миграция (проверить автогенерацию!)
make alembic-up
make lint          # pre-commit: ruff, mypy, codespell
make mypy
make test
```

Тесты бьют по той же БД, что и compose (`localhost:5433`):

```bash
cd backend && uv run pytest -v
```

---

## Конфигурация

Все переменные — в `.env.example`:

| Переменная | Назначение |
|------------|------------|
| `POSTGRES_*` | подключение к БД |
| `PROVIDER_TIMEOUT` | таймаут провайдера и порог watchdog (секунды) |
| `PROVIDER_ALPHA_URL`, `PROVIDER_BETA_URL` | адреса провайдеров |
| `PROVIDER_SHARED_SECRET` | секрет для подписи вебхуков (HMAC-SHA256) |
| `WEBHOOK_BASE_URL` | адрес, по которому провайдеры шлют вебхуки |
| `LOG_LEVEL` | уровень логирования |

`PROVIDER_SHARED_SECRET` в продакшене обязательно заменить.

---

## Логи

JSON в stdout, с контекстом из contextvars (`request_id`, `task_id`, `user_id`).
Пример:

```json
{"timestamp": "2026-10-21T16:53:12.07+00:00", "level": "INFO", "logger": "src.tasks.watchdog", "message": "Watchdog: lock захвачен, проверяем зависшие задачи"}
```
