#!/bin/sh
set -e

cd /backend

echo "Применяются миграции базы данных..."
PYTHONPATH=/backend python -m src.run_migrations

echo "Запуск приложения..."
exec "$@"
