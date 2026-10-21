# Фейковые провайдеры

Референсная реализация провайдера генерации:
два независимых HTTP-сервиса (`alpha` и `beta`), которые ведут себя как
настоящие провайдеры генерации.

Это не часть бэкенда — у провайдеров отдельный образ, отдельные зависимости и
собственный жизненный цикл. Бэкенд общается с ними по HTTP.

---

## Файлы

| Файл | Назначение |
|------|------------|
| `provider_app.py` | FastAPI-приложение: `POST /tasks`, отправка вебхуков |
| `config.py` | Поведение провайдера из переменных окружения |
| `Dockerfile` | Образ провайдера (общий для alpha и beta) |
| `pyproject.toml` | Зависимости |

---

## Запуск

```bash
docker compose up -d provider-alpha provider-beta
```

- provider-alpha — http://localhost:8001
- provider-beta — http://localhost:8002

Оба собираются из одного Dockerfile, различаются только переменными окружения.

---

## Настройки поведения

| Переменная | Значения | Смысл |
|------------|----------|-------|
| `PROVIDER_NAME` | `alpha`, `beta` | Имя провайдера (используется в URL вебхука) |
| `FAILURE_RATE` | `0.0`…`1.0` | Доля задач, которые падают |
| `FAILURE_TYPE` | `technical`, `moderation`, `payload` | Тип ошибки при падении |
| `SYNC_FAILURE` | `none`, `503`, `timeout` | Отказ на этапе `POST /tasks` |
| `DUPLICATE_WEBHOOK` | `true`/`false` | Отправлять один и тот же вебхук дважды |
| `NO_WEBHOOK` | `true`/`false` | Не отправлять вебхук вовсе (сценарий watchdog) |
| `LATE_COMPLETED` | `true`/`false` | Сначала `failed`, потом `completed` (правило 6) |
| `WEBHOOK_BASE_URL` | URL | Куда отправлять вебхук |
| `PROVIDER_SHARED_SECRET` | строка | Секрет для подписи вебхуков |

### Сценарии проверки

```bash
# alpha всегда падает технической ошибкой → задача уходит на beta
PROVIDER_ALPHA_FAILURE_RATE=1.0 docker compose up -d provider-alpha

# alpha молчит → срабатывает watchdog (заодно уменьшаем таймаут)
PROVIDER_ALPHA_NO_WEBHOOK=true PROVIDER_TIMEOUT=15 docker compose up -d provider-alpha backend

# alpha присылает вебхук дважды → проверка идемпотентности
PROVIDER_ALPHA_DUPLICATE_WEBHOOK=true docker compose up -d provider-alpha

# alpha шлёт поздний completed после failed → проверка правила 6
PROVIDER_ALPHA_LATE_COMPLETED=true docker compose up -d provider-alpha
```

Сбросить поведение к штатному:

```bash
docker compose up -d provider-alpha provider-beta
```

---

## Служебные эндпоинты

- `GET /health` — проверка живости.
- `GET /config` — текущие настройки поведения (удобно проверять, что переменные
  окружения применились).

---

## Проверка

Сквозные сценарии живут в `backend/scripts/`:

```bash
cd backend
make e2e           # платёж → генерация → вебхук → успех
make e2e-watchdog  # провайдер молчит → watchdog переводит на вторую ногу
```

Требуется поднятый `docker compose` (бэкенд на http://localhost:8000).
