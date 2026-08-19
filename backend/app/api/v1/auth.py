from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User, UserRole
from app.security import current_user, make_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole


class Me(BaseModel):
    user_id: str
    role: UserRole
    hospital_id: str | None = None


@router.post("/token", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)
) -> Token:
    """`username` is the user's phone number."""
    user = (await db.execute(select(User).where(User.phone == form.username))).scalar_one_or_none()
    if not user or not user.password_hash or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad phone or password")
    return Token(access_token=make_token(str(user.id), user.role, user.hospital_id), role=user.role)


@router.get("/me", response_model=Me)
async def me(user: dict = Depends(current_user)) -> Me:
    return Me(user_id=user["sub"], role=user["role"], hospital_id=user.get("hospital_id"))
