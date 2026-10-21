from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.repositories.user_repo import UserRepository
from src.routers.deps import get_user_repo

router = APIRouter(prefix='/api/v1', tags=['users'])


class BalanceOperationResponse(BaseModel):
    amount: int
    type: str
    # Ссылка на операцию-источник: task_id (UUID) или payment_id (строка).
    reference_id: str
    created_at: datetime


class BalanceResponse(BaseModel):
    balance: int
    operations: list[BalanceOperationResponse]


@router.get(
    '/users/{user_id}/balance',
    response_model=BalanceResponse,
)
async def get_balance(
    user_id: UUID,
    user_repo: UserRepository = Depends(get_user_repo),
) -> BalanceResponse:
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Пользователь не найден')

    operations = await user_repo.get_balance_operations(user_id, limit=20)

    return BalanceResponse(
        balance=user.balance,
        operations=[
            BalanceOperationResponse(
                amount=op.amount,
                type=op.type.value,
                reference_id=op.reference_id,
                created_at=op.created_at,
            )
            for op in operations
        ],
    )
