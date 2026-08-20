"""Phone OTP patient login. This is a trust boundary, so the tests are about the
security properties, not just the happy path."""

import pytest

from app.services import otp


@pytest.fixture
def phone(client):
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _one():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            p = (await conn.execute(text("select phone from patients limit 1"))).scalar_one()
        await engine.dispose()
        return p

    return client.portal.call(_one)


@pytest.fixture(autouse=True)
def clear_otp_state(client, phone):
    from app import events

    async def _clear():
        await events.delete(otp._code_key(phone))
        await events.delete(otp._rate_key(phone))
        await events.delete(otp._rate_key("9999000011"))

    client.portal.call(_clear)
    yield
    client.portal.call(_clear)


def code_from_outbox(client, admin_token) -> str:
    rows = client.get(
        "/api/v1/notifications?limit=20", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    body = next(r for r in rows if r["template"] == "otp")["body"]
    return "".join(c for c in body if c.isdigit())[:6]


def test_codes_are_six_random_digits():
    codes = {otp.new_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150, "a generator this predictable is not a generator"


def test_the_response_is_identical_for_a_number_we_do_not_have(client, phone):
    """Otherwise this endpoint is a directory of who is registered where."""
    known = client.post("/api/v1/auth/otp/request", json={"phone": phone}).json()
    unknown = client.post("/api/v1/auth/otp/request", json={"phone": "9999000011"}).json()
    assert known == unknown


def test_the_code_never_appears_in_the_http_response(client, phone, admin_token):
    body = client.post("/api/v1/auth/otp/request", json={"phone": phone}).text
    code = code_from_outbox(client, admin_token)
    assert code not in body


def test_the_code_goes_by_sms_not_whatsapp(client, phone, admin_token):
    """WhatsApp needs opt-in; an auth code that silently fails to arrive is worse
    than one that costs a rupee."""
    client.post("/api/v1/auth/otp/request", json={"phone": phone})
    rows = client.get(
        "/api/v1/notifications?limit=20", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    assert next(r for r in rows if r["template"] == "otp")["channel"] == "SMS"


def test_a_valid_code_returns_a_patient_token(client, phone, admin_token):
    client.post("/api/v1/auth/otp/request", json={"phone": phone})
    r = client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "code": code_from_outbox(client, admin_token)},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "PATIENT"


def test_a_code_works_exactly_once(client, phone, admin_token):
    client.post("/api/v1/auth/otp/request", json={"phone": phone})
    code = code_from_outbox(client, admin_token)
    assert (
        client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code}).status_code
        == 200
    )
    assert (
        client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code}).status_code
        == 401
    )


def test_a_code_dies_after_three_wrong_guesses(client, phone, admin_token):
    client.post("/api/v1/auth/otp/request", json={"phone": phone})
    code = code_from_outbox(client, admin_token)
    for _ in range(3):
        assert (
            client.post(
                "/api/v1/auth/otp/verify", json={"phone": phone, "code": "000000"}
            ).status_code
            == 401
        )
    # the real code is now burned too — a stolen one cannot be brute-forced
    assert (
        client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code}).status_code
        == 401
    )


def test_requests_are_rate_limited(client, phone):
    """Otherwise this endpoint is a denial-of-wallet on the SMS bill."""
    for _ in range(otp.MAX_REQUESTS_PER_WINDOW):
        client.post("/api/v1/auth/otp/request", json={"phone": phone})

    async def _sent_again():
        from app.db import SessionLocal

        async with SessionLocal() as db:
            return await otp.request_code(db, phone)

    assert client.portal.call(_sent_again) is False


def test_a_patient_token_cannot_reach_staff_endpoints(client, phone, admin_token):
    client.post("/api/v1/auth/otp/request", json={"phone": phone})
    token = client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "code": code_from_outbox(client, admin_token)},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    for path in ("/api/v1/presence", "/api/v1/scheduling/clinic", "/api/v1/notifications"):
        assert client.get(path, headers=headers).status_code == 403, path


def test_a_patient_token_reads_its_own_record(client, phone, admin_token):
    client.post("/api/v1/auth/otp/request", json={"phone": phone})
    token = client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "code": code_from_outbox(client, admin_token)},
    ).json()["access_token"]
    me = client.get("/api/v1/me/context", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["patient"]["name"]
    assert me["departments"]


def test_staff_tokens_are_not_patient_tokens(client, admin_token):
    r = client.get("/api/v1/me/context", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 403
