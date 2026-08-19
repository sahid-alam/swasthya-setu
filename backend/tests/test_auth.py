from app.seed import ADMIN_PHONE


def test_login_returns_role(client, admin_token):
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert me["role"] == "ADMIN"
    assert me["hospital_id"]


def test_wrong_password_rejected(client):
    r = client.post("/api/v1/auth/token", data={"username": ADMIN_PHONE, "password": "nope"})
    assert r.status_code == 401


def test_unknown_phone_rejected(client):
    r = client.post("/api/v1/auth/token", data={"username": "0000000000", "password": "x"})
    assert r.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_garbage_token_rejected(client):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_role_gate_blocks_non_admin(client):
    """A valid DOCTOR token must not reach an ADMIN-only route."""
    from app.models import UserRole
    from app.security import make_token

    doctor = make_token("00000000-0000-0000-0000-000000000000", UserRole.DOCTOR)
    r = client.post(
        "/api/v1/dev/publish",
        json={"topic": "alert.raised", "payload": {}},
        headers={"Authorization": f"Bearer {doctor}"},
    )
    assert r.status_code == 403
