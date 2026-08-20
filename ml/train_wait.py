"""Wait-time prediction per queue position.

    python ml/train_wait.py

No public dataset gives per-position OPD waits, so this trains on simulated clinic
days (Iron Rule 5: synthetic, same schema, labelled synthetic everywhere it surfaces).
The simulation is the honest part — consults are gamma-distributed rather than fixed,
patients no-show at the rate the real 110k dataset shows, and doctors start late.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).parent
ARTIFACTS = ROOT / "artifacts"

# Everything here is knowable while the patient is standing in the queue. In
# particular there is no feature derived from when they were *actually* seen — an
# earlier version leaked exactly that and scored a meaningless 1.3 min MAE.
FEATURES = [
    "ahead_in_queue",  # people before them still to be seen
    "avg_consult_minutes",
    "current_delay_minutes",  # how late the clinic is running right now
    "noshow_rate",
    "minutes_elapsed",  # how long the clinic has been going
]

NOSHOW_RATE = 0.202  # measured on the real dataset in train_noshow.py
DAYS = 4000


def simulate(rng: np.random.Generator) -> pd.DataFrame:
    """Run whole clinic days, then look at each day from the middle of the queue.

    For every patient we record what an observer could see at the moment the person
    ahead of them was called, and how long that patient then actually waited.
    """
    rows = []
    for _ in range(DAYS):
        avg = float(rng.choice([8, 10, 12, 15]))
        booked = int(rng.integers(12, 45))
        late = float(max(0.0, rng.normal(12, 10)))  # clinics rarely start on time
        noshow_rate = float(np.clip(rng.normal(NOSHOW_RATE, 0.05), 0.02, 0.45))

        # play the day out first, so "when was each patient actually seen" is known
        clock = late
        seen_at, attended_flags = [], []
        for _ in range(booked):
            attended = rng.random() > noshow_rate
            seen_at.append(clock)
            attended_flags.append(attended)
            # gamma keeps consults positive and right-skewed: most near the mean, a
            # few run long, which is what makes real queues drift
            clock += float(rng.gamma(shape=4.0, scale=avg / 4.0)) if attended else 1.0

        # now observe the queue from each patient's point of view
        for position in range(booked):
            if not attended_flags[position]:
                continue  # a no-show never waits
            for observer in range(position):
                now = seen_at[observer]
                scheduled_for_now = observer * avg
                rows.append(
                    {
                        "ahead_in_queue": position - observer,
                        "avg_consult_minutes": avg,
                        "current_delay_minutes": now - scheduled_for_now,
                        "noshow_rate": noshow_rate,
                        "minutes_elapsed": now,
                        "wait_minutes": seen_at[position] - now,
                    }
                )

    df = pd.DataFrame(rows)
    df["wait_minutes"] = df["wait_minutes"].clip(lower=0)
    # one row per patient-observation would explode; sample to keep training quick
    return df.sample(n=min(150_000, len(df)), random_state=2026).reset_index(drop=True)


def main() -> None:
    rng = np.random.default_rng(2026)
    df = simulate(rng)
    print(f"{len(df):,} queue observations sampled from {DAYS:,} simulated clinic days")

    x_train, x_test, y_train, y_test = train_test_split(
        df[FEATURES], df["wait_minutes"], test_size=0.2, random_state=2026
    )
    model = xgb.XGBRegressor(
        n_estimators=400,
        max_depth=6,
        learning_rate=0.06,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=2026,
    )
    model.fit(x_train, y_train)

    pred = model.predict(x_test)
    # the honest comparison: what you get from the obvious arithmetic everyone
    # already does — position x average consult length
    naive = x_test["ahead_in_queue"] * x_test["avg_consult_minutes"]
    metrics = {
        "mae_minutes": round(float(mean_absolute_error(y_test, pred)), 2),
        "naive_mae_minutes": round(float(mean_absolute_error(y_test, naive)), 2),
        "median_abs_error_minutes": round(float(np.median(np.abs(y_test - pred))), 2),
        "n_train": len(x_train),
        "n_test": len(x_test),
    }
    print(json.dumps(metrics, indent=2))

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    model.save_model(ARTIFACTS / "wait.json")
    (ARTIFACTS / "wait_metrics.json").write_text(
        json.dumps(
            {
                "model": "xgboost-regressor",
                "target": "minutes until the patient is seen",
                "features": FEATURES,
                "metrics": metrics,
                "source": {
                    "name": "SYNTHETIC — simulated clinic days",
                    "synthetic": True,
                    "why": (
                        "no public dataset gives per-position OPD waiting times; the "
                        "simulation uses the 20.2% no-show rate measured on the real "
                        "110k dataset and gamma-distributed consult lengths"
                    ),
                    "days_simulated": DAYS,
                    "rows": len(df),
                    "seed": 2026,
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
    print(f"wrote {ARTIFACTS/'wait.json'}")


if __name__ == "__main__":
    main()
