def test_health_reports_both_backing_services(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["postgres"] is True and body["redis"] is True


def test_health_says_which_adapters_are_mocked(client):
    """A client has to be able to tell before it does something that costs money —
    `infra/demo_check.py` refuses to walk the spine against a live SMS gateway."""
    mocks = client.get("/api/v1/health").json()["mocks"]
    assert set(mocks) == {"sms", "whatsapp", "telegram", "email", "ivr"}
    # conftest forces every flag to mock, whatever .env says
    assert all(mocks.values())
