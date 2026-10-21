from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.repositories.task_repo import TaskRepository
from src.routers.deps import get_task_repo

router = APIRouter(prefix='/api/v1', tags=['tasks'])


class TaskAttemptResponse(BaseModel):
    provider: str
    error_type: str | None
    started_at: datetime
    completed_at: datetime | None


class TaskResponse(BaseModel):
    id: UUID
    status: str
    current_leg: str | None
    attempts: list[TaskAttemptResponse]


@router.get(
    '/tasks/{task_id}',
    response_model=TaskResponse,
)
async def get_task(
    task_id: UUID,
    task_repo: TaskRepository = Depends(get_task_repo),
) -> TaskResponse:
    task = await task_repo.get_with_attempts(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Задача не найдена')

    return TaskResponse(
        id=task.id,
        status=task.status.value,
        current_leg=str(task.current_leg_id) if task.current_leg_id else None,
        attempts=[
            TaskAttemptResponse(
                provider=a.provider.value,
                error_type=a.error_type.value if a.error_type else None,
                started_at=a.started_at,
                completed_at=a.completed_at,
            )
            for a in task.attempts
        ],
    )
