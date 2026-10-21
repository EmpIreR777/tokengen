from fastapi import APIRouter
from sqlalchemy import text

from src.core.db import engine

router = APIRouter(tags=['health'])


@router.get('/health')
async def health_check() -> dict[str, str]:
    """Проверка живости сервиса и БД."""
    async with engine.connect() as connection:
        await connection.execute(text('SELECT 1'))
    return {'status': 'ok'}
