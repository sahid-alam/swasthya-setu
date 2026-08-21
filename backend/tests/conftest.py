import os

# Must be set before app.config is imported — the engine is built at import time.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://setu:setu@localhost:5432/swasthya")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("PRESENCE_SWEEP_SECONDS", "0")  # no background re-fusion mid-test
os.environ.setdefault("REFERRAL_SWEEP_SECONDS", "0")  # tests drive expire_due() themselves
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long-for-hs256")

# Not setdefault — an assignment, so it beats a live flag in .env. Real credentials
# exist on this machine, and a test suite that sends actual SMS off someone's SIM is a
# test suite nobody can run twice (CLAUDE.md §Conventions, live SMS).
for _flag in (
    "SMS_MOCK_MODE",
    "TELEGRAM_MOCK_MODE",
    "EMAIL_MOCK_MODE",
    "WHATSAPP_MOCK_MODE",
    "OSRM_MOCK_MODE",  # never reach for an OSRM container in a test
    "ERAKTKOSH_MOCK_MODE",  # never scrape a government portal from a test
):
    os.environ[_flag] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import ADMIN_PASSWORD, ADMIN_PHONE  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client) -> str:
    r = client.post(
        "/api/v1/auth/token", data={"username": ADMIN_PHONE, "password": ADMIN_PASSWORD}
    )
    assert r.status_code == 200, "run `make seed` first — tests need the seeded admin"
    return r.json()["access_token"]


@pytest.fixture
def fresh_badge(client):
    """Reset one doctor's presence + clinic list so a test does not inherit state from
    an earlier run. Tests may touch the database directly; simulators may not."""
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _wipe(badge: str) -> None:
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            doctor_id = (
                await conn.execute(text("select id from doctors where badge_id = :b"), {"b": badge})
            ).scalar_one()
            for table in ("presence_signals", "presence_transitions"):
                await conn.execute(
                    text(f"delete from {table} where doctor_id = :d"), {"d": doctor_id}
                )
            await conn.execute(
                text(
                    "update doctor_status set state='UNKNOWN', confidence=0, zone_id=null,"
                    " evidence='{}' where doctor_id = :d"
                ),
                {"d": doctor_id},
            )
        await engine.dispose()

    def wipe(badge: str) -> str:
        client.portal.call(_wipe, badge)
        return badge

    return wipe


@pytest.fixture
def clinic_list(client):
    """Give a doctor a known, upcoming clinic list.

    The replan tests mutate appointments, so they cannot lean on whatever the seed
    left behind or on the order tests happen to run in — each builds its own.
    """
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _build(badge: str, size: int) -> int:
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            doctor = (
                await conn.execute(
                    text("select id, department_id, hospital_id from doctors where badge_id = :b"),
                    {"b": badge},
                )
            ).one()
            # Reset the whole department, not just this doctor: a replan needs
            # colleagues with free seats and no leftover ON_LEAVE from an earlier
            # test, or there is nowhere to move anyone and the run looks like a bug.
            dep = {"dep": doctor.department_id}
            await conn.execute(
                text(
                    "delete from appointments where slot_id in (select id from slots"
                    " where department_id = :dep and starts_at >= now())"
                ),
                dep,
            )
            await conn.execute(
                text(
                    "update slots set status='OPEN'"
                    " where department_id = :dep and starts_at >= now()"
                ),
                dep,
            )
            await conn.execute(
                text(
                    "update doctor_status set state='UNKNOWN', confidence=0, evidence='{}'"
                    " where doctor_id in (select id from doctors where department_id = :dep)"
                ),
                dep,
            )
            slot_ids = [
                r[0]
                for r in (
                    await conn.execute(
                        text(
                            "select id from slots where doctor_id = :d and starts_at >= now()"
                            " order by starts_at limit :n"
                        ),
                        {"d": doctor.id, "n": size},
                    )
                ).all()
            ]
            patients = [
                r[0]
                for r in (
                    await conn.execute(text("select id from patients limit :n"), {"n": size})
                ).all()
            ]
            for slot_id, patient_id in zip(slot_ids, patients, strict=False):
                await conn.execute(
                    text(
                        "insert into appointments (patient_id, slot_id, hospital_id,"
                        " department_id, channel, priority_class, status)"
                        " values (:p, :s, :h, :dep, 'PWA', 'GENERAL', 'BOOKED')"
                    ),
                    {
                        "p": patient_id,
                        "s": slot_id,
                        "h": doctor.hospital_id,
                        "dep": doctor.department_id,
                    },
                )
                await conn.execute(
                    text("update slots set status='FULL' where id = :s"), {"s": slot_id}
                )
        await engine.dispose()
        return len(slot_ids)

    def build(badge: str, size: int = 40) -> int:
        return client.portal.call(_build, badge, size)

    return build
