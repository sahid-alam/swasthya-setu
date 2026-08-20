"""Patient OTP login by phone or email. This is a trust boundary, so the tests are
about the security properties, not just the happy path."""

import pytest

from app.services import otp

EMAIL = "demo.patient@example.test"


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
        for kind, value in (
            otp.identity(phone=phone),
            otp.identity(phone="9999000011"),
            otp.identity(email=EMAIL),
        ):
            await events.delete(otp._code_key(kind, value))
            await events.delete(otp._rate_key(kind, value))

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
            return await otp.request_code(db, phone=phone)

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


# ------------------------------------------------------------------ email OTP


@pytest.fixture
def emailed_patient(client, phone):
    """Give the patient the tests already use an address, and take it back after."""
    import os

    from sqlalchemy import NullPool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _set(value):
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(
                text("update patients set email = :e where phone = :p"),
                {"e": value, "p": phone},
            )
        await engine.dispose()

    client.portal.call(_set, EMAIL)
    yield EMAIL
    client.portal.call(_set, None)


def test_an_email_code_logs_a_patient_in(client, emailed_patient, admin_token):
    assert (
        client.post("/api/v1/auth/otp/request", json={"email": emailed_patient}).status_code == 200
    )
    token = client.post(
        "/api/v1/auth/otp/verify",
        json={"email": emailed_patient, "code": code_from_outbox(client, admin_token)},
    ).json()
    assert token["role"] == "PATIENT" and token["access_token"]


def test_the_email_code_goes_only_to_the_inbox(client, emailed_patient, admin_token):
    """An OTP that also fans out to SMS is an OTP delivered to whoever holds either."""
    client.post("/api/v1/auth/otp/request", json={"email": emailed_patient})
    rows = client.get(
        "/api/v1/notifications?limit=5", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    latest = next(r for r in rows if r["template"] == "otp")
    assert latest["channel"] == "EMAIL"
    assert latest["to"] == emailed_patient


def test_an_email_code_cannot_be_spent_as_a_phone_code(client, emailed_patient, phone, admin_token):
    """Phone and email are separate Redis namespaces on purpose."""
    client.post("/api/v1/auth/otp/request", json={"email": emailed_patient})
    code = code_from_outbox(client, admin_token)
    assert (
        client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code}).status_code
        == 401
    )


def test_an_unknown_address_is_answered_identically(client):
    known = client.post("/api/v1/auth/otp/request", json={"email": "nobody@example.test"})
    assert known.status_code == 200
    assert known.json()["message"] == "If that contact is registered, we have sent it a code."


def test_a_patient_with_no_address_gets_no_email_row(client, phone, admin_token):
    """The seeded patients have no email. Asking for one must not invent a delivery."""
    before = client.get(
        "/api/v1/notifications?limit=1", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    client.post("/api/v1/auth/otp/request", json={"email": "someone.else@example.test"})
    after = client.get(
        "/api/v1/notifications?limit=1", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    assert before == after


@pytest.mark.parametrize(
    "body",
    [
        {"phone": "9418000001", "email": EMAIL},  # both
        {"code": "123456"},  # neither
    ],
)
def test_exactly_one_contact_is_required(client, body):
    assert client.post("/api/v1/auth/otp/request", json=body).status_code == 422


def test_a_live_adapter_with_no_credentials_degrades_rather_than_500s(
    client, emailed_patient, admin_token
):
    """Iron Rule 4: flipping a service to live is one flag, and getting that flag
    wrong must fall back, not crash. SmtpEmail raises while being *constructed* when
    SMTP_* is unset, which is the case a try around `.send()` alone would miss."""
    from app.adapters import factory
    from app.config import get_settings

    settings = get_settings()
    settings.email_mock_mode = False
    factory.messaging.cache_clear()
    try:
        r = client.post("/api/v1/auth/otp/request", json={"email": emailed_patient})
        assert r.status_code == 200
        rows = client.get(
            "/api/v1/notifications?limit=1", headers={"Authorization": f"Bearer {admin_token}"}
        ).json()
        assert rows[0]["channel"] == "EMAIL" and rows[0]["status"] == "FAILED"
    finally:
        settings.email_mock_mode = True
        factory.messaging.cache_clear()
