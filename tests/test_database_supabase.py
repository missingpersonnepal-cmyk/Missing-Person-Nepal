def test_postgres_url_defaults_to_psycopg_driver():
    from app import database

    assert database._normalize_database_url("postgresql://user:pass@host/db") == "postgresql+psycopg://user:pass@host/db"
    assert database._normalize_database_url("postgres://user:pass@host/db") == "postgresql+psycopg://user:pass@host/db"


def test_ready_endpoint_reports_database_status(monkeypatch, client):
    import app.main

    monkeypatch.setattr(app.main, "check_database_ready", lambda: (True, None))
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


def test_ready_endpoint_reports_database_failure(monkeypatch, client):
    import app.main

    monkeypatch.setattr(app.main, "check_database_ready", lambda: (False, "timeout"))
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "down"
