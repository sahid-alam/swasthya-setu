def test_health_reports_both_backing_services(client):
    body = client.get("/api/v1/health").json()
    assert body == {"status": "ok", "postgres": True, "redis": True}
