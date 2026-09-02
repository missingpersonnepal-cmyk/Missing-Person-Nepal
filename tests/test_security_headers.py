def test_public_responses_include_browser_security_headers(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_cross_origin_admin_mutation_is_rejected(admin_client):
    response = admin_client.post(
        "/admin/logout",
        headers={"Origin": "https://attacker.example"},
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_ready_does_not_expose_database_error(client, monkeypatch):
    monkeypatch.setattr("app.main.check_database_ready", lambda: (False, "internal hostname"))

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "down"}
    assert "hostname" not in response.text
