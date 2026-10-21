from src.routers.v1.generate import router as generate_router
from src.routers.v1.tasks import router as tasks_router
from src.routers.v1.users import router as users_router
from src.routers.v1.webhooks import router as webhooks_router

__all__ = [
    'generate_router',
    'tasks_router',
    'users_router',
    'webhooks_router',
]
