import os

# Must be set before app.config is imported — the engine is built at import time.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://setu:setu@localhost:5432/swasthya")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("PRESENCE_SWEEP_SECONDS", "0")  # no background re-fusion mid-test
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long-for-hs256")

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
