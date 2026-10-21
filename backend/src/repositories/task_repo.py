from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.model import ProviderEnum
from src.models.task import ErrorType, Task, TaskAttempt, TaskStatus


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        user_id: UUID,
        model_slug: str,
        prompt: str,
        ref_images_count: int,
        current_leg_id: UUID,
        status: TaskStatus = TaskStatus.processing,
    ) -> Task:
        task = Task(
            user_id=user_id,
            model_slug=model_slug,
            prompt=prompt,
            ref_images_count=ref_images_count,
            status=status,
            current_leg_id=current_leg_id,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def get_by_id(self, task_id: UUID) -> Task | None:
        return await self.session.get(Task, task_id)

    async def get_with_attempts(self, task_id: UUID) -> Task | None:
        result = await self.session.execute(
            select(Task).where(Task.id == task_id).options(selectinload(Task.attempts).selectinload(TaskAttempt.leg))
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        result_url: str | None = None,
        error_type: ErrorType | None = None,
        current_leg_id: UUID | None = None,
    ) -> Task | None:
        task = await self.get_by_id(task_id)
        if task:
            task.status = status
            if result_url is not None:
                task.result_url = result_url
            if error_type is not None:
                task.error_type = error_type
            if current_leg_id is not None:
                task.current_leg_id = current_leg_id
            await self.session.flush()
        return task

    async def set_current_leg(self, task_id: UUID, leg_id: UUID) -> Task | None:
        return await self.update_status(task_id, TaskStatus.processing, current_leg_id=leg_id)

    async def add_attempt(
        self,
        task_id: UUID,
        leg_id: UUID,
        provider: ProviderEnum,
        external_id: str,
        error_type: ErrorType | None = None,
        completed_at: datetime | None = None,
    ) -> TaskAttempt:
        attempt = TaskAttempt(
            task_id=task_id,
            leg_id=leg_id,
            provider=provider,
            external_id=external_id,
            error_type=error_type,
            completed_at=completed_at,
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def get_attempt_by_external_id(self, external_id: str) -> TaskAttempt | None:
        result = await self.session.execute(select(TaskAttempt).where(TaskAttempt.external_id == external_id))
        return result.scalar_one_or_none()

    async def get_stale_tasks(self, timeout_seconds: int) -> list[Task]:
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        result = await self.session.execute(
            select(Task)
            .where(
                Task.status == TaskStatus.processing,
                Task.updated_at < cutoff,
            )
            .options(selectinload(Task.attempts).selectinload(TaskAttempt.leg))
        )
        return list(result.scalars().all())
