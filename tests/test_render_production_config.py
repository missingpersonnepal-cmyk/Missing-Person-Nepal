from __future__ import annotations

import importlib
import sys

import pytest

def _reload(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_port_defaults_from_env(monkeypatch):
    monkeypatch.setenv("PORT", "12345")
    config = _reload("app.config")
    assert config.settings.port == 12345


def test_production_requires_database_url(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sys.modules.pop("app.config", None)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        _reload("app.config")


def test_production_rejects_sqlite_database(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./bad.db")
    sys.modules.pop("app.config", None)
    sys.modules.pop("app.database", None)
    config = _reload("app.config")
    assert config.settings.database_url == "sqlite:///./bad.db"
    with pytest.raises(RuntimeError, match="must point to PostgreSQL"):
        _reload("app.database")


def test_health_endpoint_is_lightweight(monkeypatch, client):
    import app.main

    called = {"count": 0}

    def boom():
        called["count"] += 1
        raise AssertionError("health should not touch the database")

    monkeypatch.setattr(app.main, "check_database_ready", boom)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert called["count"] == 0
