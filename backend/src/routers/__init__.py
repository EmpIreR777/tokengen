from fastapi import APIRouter

from src.routers.health import router as health_router
from src.routers.v1.generate import router as generate_router
from src.routers.v1.tasks import router as tasks_router
from src.routers.v1.users import router as users_router
from src.routers.v1.webhooks import router as webhooks_router

router = APIRouter()
router.include_router(health_router)
router.include_router(generate_router)
router.include_router(webhooks_router)
router.include_router(tasks_router)
router.include_router(users_router)
