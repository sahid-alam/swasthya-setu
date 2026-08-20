"""No-show probability, trained on the public 110k Brazilian appointment dataset.

    python ml/train_noshow.py

Downloads the CSV on first run (Iron Rule 5: real data where promised), trains, and
writes the artifact + metrics to ml/artifacts/. The CSV itself is gitignored; the
artifact, its metrics and the source checksum are committed, so a judge can see what
was trained on without the repo carrying 10 MB of someone else's data.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "noshow.csv"
ARTIFACTS = ROOT / "artifacts"
SOURCE_URL = (
    "https://raw.githubusercontent.com/mroker242/no-show-appointments/master/"
    "noshowappointments-kagglev2-may-2016.csv"
)

# Features we can actually reproduce for a Himachal patient at booking time. Anything
# the Brazilian file has that we cannot recreate (neighbourhood, welfare scholarship)
# is deliberately dropped — a model that needs columns production cannot supply is a
# demo prop, not a model.
FEATURES = [
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


def fetch() -> Path:
    if not DATA.exists():
        DATA.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {SOURCE_URL}")
        urllib.request.urlretrieve(SOURCE_URL, DATA)
    return DATA


def build_frame(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower().replace("-", "_") for c in df.columns]
    scheduled = pd.to_datetime(df["scheduledday"], utc=True)
    appointment = pd.to_datetime(df["appointmentday"], utc=True)

    out = pd.DataFrame(
        {
            # how far ahead the appointment was booked — the single strongest signal,
            # and one we always have
            "lead_days": (appointment - scheduled).dt.total_seconds() / 86400,
            "age": df["age"].clip(0, 110),
            "is_female": (df["gender"] == "F").astype(int),
            "sms_received": df["sms_received"].astype(int),
            "hypertension": df["hipertension"].astype(int),
            "diabetes": df["diabetes"].astype(int),
            "alcoholism": df["alcoholism"].astype(int),
            "handicap": (df["handcap"] > 0).astype(int),
            "appointment_dow": appointment.dt.dayofweek,
            "scheduled_hour": scheduled.dt.hour,
            "no_show": (df["no_show"].str.strip().str.lower() == "yes").astype(int),
        }
    )
    # a handful of rows have the appointment before it was booked
    out["lead_days"] = out["lead_days"].clip(lower=0)
    return out.dropna()


def main() -> None:
    path = fetch()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    df = build_frame(path)
    print(f"{len(df):,} appointments, no-show rate {df['no_show'].mean():.1%}")

    x_train, x_test, y_train, y_test = train_test_split(
        df[FEATURES],
        df["no_show"],
        test_size=0.2,
        random_state=2026,
        stratify=df["no_show"],
    )
    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.06,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        random_state=2026,
    )
    model.fit(x_train, y_train)

    probs = model.predict_proba(x_test)[:, 1]
    metrics = {
        "roc_auc": round(float(roc_auc_score(y_test, probs)), 4),
        "brier": round(float(brier_score_loss(y_test, probs)), 4),
        # what you would get by always predicting the base rate — the number that
        # makes the AUC above mean something
        "baseline_brier": round(
            float(brier_score_loss(y_test, np.full_like(probs, y_train.mean()))), 4
        ),
        "base_rate": round(float(y_train.mean()), 4),
        "n_train": len(x_train),
        "n_test": len(x_test),
    }
    print(json.dumps(metrics, indent=2))

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    model.save_model(ARTIFACTS / "noshow.json")
    (ARTIFACTS / "noshow_metrics.json").write_text(
        json.dumps(
            {
                "model": "xgboost-classifier",
                "target": "patient does not attend",
                "features": FEATURES,
                "metrics": metrics,
                "source": {
                    "name": "Medical Appointment No Shows (Vitoria, Brazil)",
                    "url": SOURCE_URL,
                    "rows": len(df),
                    "sha256": digest,
                },
                "importance": {
                    f: round(float(v), 4)
                    for f, v in sorted(
                        zip(FEATURES, model.feature_importances_, strict=True),
                        key=lambda kv: -kv[1],
                    )
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {ARTIFACTS/'noshow.json'}")


if __name__ == "__main__":
    main()
