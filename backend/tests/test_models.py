"""ML inference. Artifacts are committed, so these assert on the real models."""

from datetime import UTC, datetime, timedelta

from app.services import models

NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def test_artifacts_load():
    assert models.available(), "committed artifacts should load without training"


def test_a_far_off_booking_is_likelier_to_be_missed_than_a_same_day_one():
    """Lead time is the strongest real signal in the 110k dataset."""
    far = models.predict_noshow(
        booked_at=NOW, appointment_at=NOW + timedelta(days=45), age=25, is_female=True
    )
    soon = models.predict_noshow(
        booked_at=NOW, appointment_at=NOW + timedelta(hours=2), age=25, is_female=True
    )
    assert far > soon


def test_noshow_is_a_probability():
    p = models.predict_noshow(
        booked_at=NOW, appointment_at=NOW + timedelta(days=3), age=40, is_female=False
    )
    assert 0.0 <= p <= 1.0


def test_wait_grows_with_the_queue():
    short = models.predict_wait_minutes(ahead_in_queue=1, avg_consult_minutes=10)
    long = models.predict_wait_minutes(ahead_in_queue=12, avg_consult_minutes=10)
    assert long > short
    assert short >= 0


def test_metrics_report_which_model_is_synthetic():
    """Honesty is a design feature: the wait model must never claim to be real data."""
    m = models.metrics()
    assert m["loaded"] is True
    assert m["models"]["noshow"]["source"]["rows"] > 100_000
    assert m["models"]["wait"]["source"]["synthetic"] is True
    assert m["manifest"]["models"]["wait"]["synthetic"] is True
    assert m["manifest"]["models"]["noshow"]["synthetic"] is False


def test_noshow_beats_predicting_the_base_rate():
    n = models.metrics()["models"]["noshow"]["metrics"]
    assert n["brier"] < n["baseline_brier"], "a model no better than the base rate is not a model"
    assert n["roc_auc"] > 0.65


def test_wait_beats_the_arithmetic_a_reception_desk_already_does():
    w = models.metrics()["models"]["wait"]["metrics"]
    assert w["mae_minutes"] < w["naive_mae_minutes"]
