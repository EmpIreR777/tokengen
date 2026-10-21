# Бэкенд tokengen

Сервис генерации: принимает заявку на генерацию, списывает токены с баланса
пользователя, отправляет задачу провайдеру (alpha/beta) с fallback между
ногами модели, обрабатывает вебхуки провайдеров и возвращает токены при неудаче.

## Стек

Python 3.11+ · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic 2 ·
pydantic-settings · APScheduler · PostgreSQL 16 · httpx · uv · pytest

Внимание: в репозитории используются отдельные окружения — `backend/.venv` и
`providers/.venv`.

## Быстрый старт

Через docker compose (из корня репозитория):

```bash
cp .env.example .env
docker compose up -d        # db, backend (4 воркера), provider-alpha, provider-beta
docker compose logs -f backend
```

Миграции применяются автоматически при старте контейнера backend
(`entrypoint.sh` → `src.run_migrations`).

Проверка:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Остановка:

```bash
docker compose down
docker compose down -v      # также удалить volumes с данными БД
```

### Локально без Docker

```bash
cd backend
uv sync                     # зависимости (включая dev-группу)
uv run alembic upgrade head # применить миграции к локальной PostgreSQL
uv run uvicorn src.app:app --host 127.0.0.1 --port 8000 --reload
```

Бэкенд ожидает PostgreSQL по `POSTGRES_HOST`/`POSTGRES_PORT` (см.
`backend/.env.example` — по умолчанию `localhost:5433`, что совпадает с
пробросом порта compose).

## Миграции

Схема создаётся alembic-миграциями в каталоге `alembic/versions` и применяется
автоматически при старте контейнера. Применение вручную:

```bash
cd backend
uv run alembic upgrade head
```

Добавить следующую миграцию:

```bash
cd backend
uv run alembic revision --autogenerate -m "описание изменений"
# сгенерированный файл в alembic/versions стоит проверить и при необходимости
# отредактировать вручную, а затем применить:
uv run alembic upgrade head
```

В compose миграции применяются при каждом (пере)старте контейнера backend через
`entrypoint.sh`, поэтому новую ревизию достаточно запушить и пересобрать
сервис.

## Тесты

Интеграционные и юнит-тесты ходят в ту же БД, что и compose (`localhost:5433`):

```bash
cd backend
uv run pytest -v
```

## Переменные окружения

См. `backend/.env.example` и корневой `README.md` (раздел «Конфигурация»).

## Структура

```text
backend/
  src/
    core/          конфиг, БД, исключения, логирование, безопасность, middleware
    models/        SQLAlchemy 2 модели
    repositories/  доступ к БД + UnitOfWork
    services/      бизнес-логика: генерация, вебхуки, платежи, watchdog
    integrations/  HTTP-клиент к провайдерам
    routers/       HTTP-слой
    tasks/         APScheduler-задачи (watchdog)
  alembic/         миграции
  tests/           тесты
```

Слои: `routers → services → repositories / integrations`. Роутеры не содержат
бизнес-логики, сервисы не знают про HTTP.

## Ключевые свойства

- **Ровно один раз** (exactly-once) для начисления и возврата токенов —
  детерминированные ключи идемпотентности (`gen:{task_id}`,
  `payment:{payment_id}`, `refund:{task_id}`) с уникальными индексами в БД.
- **Fallback** между ногами модели при технических отказах, 5xx, таймаутах и
  отказе по модерации (с учётом `skip_on_moderation`).
- **Watchdog** зависших задач на APScheduler (каждые 10 с); координация между 4
  воркерами через `pg_try_advisory_lock` в PostgreSQL — проход выполняет ровно
  один воркер.
- Баланс пользователя всегда равен сумме его журнала (`balance_operations`);
  изменения баланса и записи журнала делаются в одной транзакции.

Подробнее — в корневом `README.md`.
