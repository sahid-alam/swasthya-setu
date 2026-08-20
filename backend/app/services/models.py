"""ML inference. Artifacts are loaded once at import and never trained at runtime
(docs/ARCHITECTURE.md D5) — a demo must not depend on a training run succeeding.

If the artifacts are missing the service degrades to returning None rather than
failing: a missing model must cost you a prediction, not the whole clinic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("swasthya.models")


def _artifacts_dir() -> Path:
    """Repo layout puts ml/ beside backend/; docker mounts it at /ml. Env wins."""
    import os

    if env := os.environ.get("ML_ARTIFACTS"):
        return Path(env)
    for candidate in (
        Path(__file__).resolve().parents[3] / "ml" / "artifacts",  # repo checkout
        Path("/ml/artifacts"),  # docker compose mount
    ):
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[3] / "ml" / "artifacts"


ARTIFACTS = _artifacts_dir()

NOSHOW_FEATURES = [
    "lead_days",
    "age",
    "is_female",
    "sms_received",
    "hypertension",
    "diabetes",
    "alcoholism",
    "handicap",
    "appointment_dow",
    "scheduled_hour",
]
WAIT_FEATURES = [
    "ahead_in_queue",
    "avg_consult_minutes",
    "current_delay_minutes",
    "noshow_rate",
    "minutes_elapsed",
]


@lru_cache(maxsize=1)
def _bundle():
    """(noshow_model, wait_model, manifest). Cached: loading is not free."""
    try:
        import xgboost as xgb
    except Exception:  # pragma: no cover - only when the optional stack is absent
        log.warning("xgboost unavailable; predictions disabled")
        return None, None, {}

    def load(name, cls):
        path = ARTIFACTS / name
        if not path.exists():
            log.warning("missing artifact %s — predictions from it will be None", path)
            return None
        model = cls()
        model.load_model(path)
        return model

    manifest_path = ARTIFACTS / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    return load("noshow.json", xgb.XGBClassifier), load("wait.json", xgb.XGBRegressor), manifest


def available() -> bool:
    noshow, wait, _ = _bundle()
    return noshow is not None and wait is not None


def predict_noshow(
    *,
    booked_at: datetime,
    appointment_at: datetime,
    age: int | None,
    is_female: bool,
    sms_received: bool = True,
    hypertension: bool = False,
    diabetes: bool = False,
    alcoholism: bool = False,
    handicap: bool = False,
) -> float | None:
    """Probability this patient does not attend."""
    model, _, _ = _bundle()
    if model is None:
        return None
    lead_days = max((appointment_at - booked_at).total_seconds() / 86400, 0.0)
    row = [
        lead_days,
        age if age is not None else 35,
        int(is_female),
        int(sms_received),
        int(hypertension),
        int(diabetes),
        int(alcoholism),
        int(handicap),
        appointment_at.weekday(),
        booked_at.hour,
    ]
    return round(float(model.predict_proba([row])[0][1]), 3)


def predict_wait_minutes(
    *,
    ahead_in_queue: int,
    avg_consult_minutes: int,
    current_delay_minutes: float = 0.0,
    noshow_rate: float = 0.2,
    minutes_elapsed: float = 0.0,
) -> int | None:
    """Minutes until this patient is seen, given what the queue looks like now."""
    _, model, _ = _bundle()
    if model is None:
        return None
    row = [
        ahead_in_queue,
        avg_consult_minutes,
        current_delay_minutes,
        noshow_rate,
        minutes_elapsed,
    ]
    return max(0, int(round(float(model.predict([row])[0]))))


def metrics() -> dict:
    """What the models actually scored, including which one is synthetic. This is the
    honesty slide, served from the same artifacts the predictions come from."""
    _, _, manifest = _bundle()
    out = {"manifest": manifest, "loaded": available(), "models": {}}
    for name in ("noshow", "wait"):
        path = ARTIFACTS / f"{name}_metrics.json"
        if path.exists():
            out["models"][name] = json.loads(path.read_text())
    return out
