"""Model metrics — PRD §M2 accept: "how do you know the wait predictions are any good?"

Served from the same artifact directory the predictions load from, so the numbers on
the slide and the numbers in the running system cannot drift apart.
"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import UserRole
from app.security import require_roles
from app.services import impact as impact_service
from app.services import models

ARTIFACTS = Path(__file__).resolve().parents[4] / "ml" / "artifacts"

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


class ImpactOut(BaseModel):
    patients_told: int
    told_in_time: int
    told_too_late: int
    told_in_time_pct: float
    median_notice_minutes: float | None
    still_pending: int
    replans: int
    fastest_replan_ms: int | None
    slowest_replan_ms: int | None


@router.get("/impact", response_model=ImpactOut)
async def impact(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles(UserRole.ADMIN, UserRole.STAFF)),
) -> ImpactOut:
    """The problem statement's own metric: how much waiting the presence layer avoided.

    Reported as notice given, not as hours of travel saved. See services/impact.py —
    inventing the travel time would make the number bigger and the answer worse.
    """
    result = await impact_service.wait_avoided(db)
    return ImpactOut(**{**result.__dict__, "told_in_time_pct": result.told_in_time_pct})


@router.get("/fcfs")
async def fcfs_comparison(
    _=Depends(require_roles(UserRole.ADMIN, UserRole.STAFF)),
) -> dict:
    """CP-SAT against first-come-first-served on identical demand.

    Served from the committed artifact so the chart on the dashboard and the file the
    simulation wrote cannot drift apart. `honest_reading` travels with the numbers on
    purpose: this comparison does NOT say everyone waits less, and the UI renders that
    sentence rather than letting a presenter improvise it.
    """
    path = ARTIFACTS / "fcfs_comparison.json"
    if not path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "run `python ml/compare_fcfs.py` to build the comparison"
        )
    return json.loads(path.read_text())
