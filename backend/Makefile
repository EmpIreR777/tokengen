.PHONY: run sync alembic-rev alembic-up alembic-down lint ruff mypy test e2e e2e-watchdog clean-cache

# =====================================================
# App
# =====================================================
run:
	uv run uvicorn src.app:app --host 127.0.0.1 --port 8000 --reload

# =====================================================
# Dependencies
# =====================================================
sync:
	uv sync --all-groups

# =====================================================
# Database / Alembic
# =====================================================
alembic-rev:
	uv run alembic revision --autogenerate -m "$(m)"

alembic-up:
	uv run alembic upgrade head

alembic-down:
	uv run alembic downgrade -1

# =====================================================
# Code Quality
# =====================================================
lint:
	uv run pre-commit run --all-files

ruff:
	uv run ruff check --fix && uv run ruff format .

mypy:
	uv run mypy src --cache-dir .mypy_cache

# =====================================================
# Tests
# =====================================================
test:
	uv run pytest -v

# Сквозные проверки — требуют поднятого docker compose
e2e:
	uv run python scripts/e2e_check.py

e2e-watchdog:
	# Скрипт ходит во внешнюю БД и проверяет watchdog, поэтому запускаем его
	# внутри контейнера backend, где POSTGRES_HOST=db и POSTGRES_PORT=5432.
	docker compose exec -T backend /bin/sh -lc 'cd /backend && python scripts/e2e_watchdog.py'

# =====================================================
# Maintenance
# =====================================================
clean-cache:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
