from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.exceptions import (
    InsufficientTokensError,
    NoSuitableLegError,
    TooManyActiveTasksError,
)
from src.routers.deps import get_generation_service
from src.services.generation_service import GenerationService

router = APIRouter(prefix='/api/v1', tags=['generation'])


class GenerateRequest(BaseModel):
    user_id: UUID
    model_slug: str
    prompt: str
    ref_images: list[str] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    task_id: UUID


@router.post(
    '/generate',
    response_model=GenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_generation(
    request: GenerateRequest,
    service: GenerationService = Depends(get_generation_service),
) -> GenerateResponse:
    try:
        task_id = await service.create_generation(
            user_id=request.user_id,
            model_slug=request.model_slug,
            prompt=request.prompt,
            ref_images=request.ref_images,
        )
        return GenerateResponse(task_id=task_id)
    except NoSuitableLegError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except InsufficientTokensError as e:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(e))
    except TooManyActiveTasksError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
