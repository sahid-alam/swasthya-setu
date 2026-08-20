from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User, UserRole
from app.security import current_user, make_token, verify_password
from app.services import otp

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


# --- patient login by phone OTP ------------------------------------------------
# Reuses the existing JWT and the existing mock SMS adapter. No new auth service.


class OtpRequestIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


class OtpRequestOut(BaseModel):
    sent: bool
    message: str


class OtpVerifyIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    code: str = Field(min_length=4, max_length=8)


@router.post("/otp/request", response_model=OtpRequestOut)
async def request_otp(body: OtpRequestIn, db: AsyncSession = Depends(get_db)) -> OtpRequestOut:
    """Always answers the same way.

    Saying "no such patient" would turn this endpoint into a directory of who is
    registered at which hospital, so the response is identical whether or not we sent
    anything. Rate limiting lives in the service.
    """
    await otp.request_code(db, body.phone)
    await db.commit()
    return OtpRequestOut(
        sent=True,
        message="If that number is registered, we have sent it a code.",
    )


@router.post("/otp/verify", response_model=Token)
async def verify_otp(body: OtpVerifyIn) -> Token:
    patient_id = await otp.verify_code(body.phone, body.code)
    if patient_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "that code is wrong or has expired")
    return Token(access_token=make_token(patient_id, UserRole.PATIENT), role=UserRole.PATIENT)
