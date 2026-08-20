"""Model metrics — PRD §M2 accept: "how do you know the wait predictions are any good?"

Served from the same artifact directory the predictions load from, so the numbers on
the slide and the numbers in the running system cannot drift apart.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.models import UserRole
from app.security import require_roles
from app.services import models

router = APIRouter(prefix="/metrics", tags=["metrics"])


class ModelMetrics(BaseModel):
    loaded: bool
    manifest: dict
    models: dict


@router.get("/models", response_model=ModelMetrics)
async def model_metrics(
    _=Depends(require_roles(UserRole.ADMIN, UserRole.STAFF)),
) -> ModelMetrics:
    """Honest numbers, including which model is trained on synthetic data."""
    return ModelMetrics(**models.metrics())
