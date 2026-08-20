from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

from app.config import get_settings
from app.models import UserRole

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

ALGORITHM = "HS256"


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd.verify(raw, hashed)


def make_token(user_id: str, role: UserRole, hospital_id: str | None = None) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "hospital_id": str(hospital_id) if hospital_id else None,
        "exp": datetime.now(UTC) + timedelta(minutes=s.jwt_ttl_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])


def current_user(token: str | None = Depends(oauth2)) -> dict:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    try:
        return decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc


def current_patient_id(user: dict = Depends(current_user)) -> str:
    """A PATIENT token carries the patient id in `sub`. Any endpoint serving patient
    data must scope to this rather than trusting an id in the URL — otherwise the
    token is a key to everyone's records, not the holder's."""
    if user.get("role") != UserRole.PATIENT.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "patient token required")
    return user["sub"]


def require_roles(*roles: UserRole):
    """Route dependency: `Depends(require_roles(UserRole.ADMIN))`."""
    allowed = {r.value for r in roles}

    def _check(user: dict = Depends(current_user)) -> dict:
        if user.get("role") not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user

    return _check
