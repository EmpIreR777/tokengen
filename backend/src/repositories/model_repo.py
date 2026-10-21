from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.model import Model, ModelLeg


class ModelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_model_with_legs(self, model_slug: str) -> Model | None:
        result = await self.session.execute(
            select(Model).where(Model.slug == model_slug).options(selectinload(Model.legs))
        )
        return result.scalar_one_or_none()

    async def get_leg_by_id(self, leg_id: UUID) -> ModelLeg | None:
        return await self.session.get(ModelLeg, leg_id)

    async def get_suitable_legs(self, model_slug: str, ref_images_count: int) -> list[ModelLeg]:
        model = await self.get_model_with_legs(model_slug)
        if not model:
            return []
        return [leg for leg in model.legs if leg.max_ref_images >= ref_images_count]
