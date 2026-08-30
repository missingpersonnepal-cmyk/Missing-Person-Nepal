import pytest

from app.services.search_providers import (
    BravePublicSearch,
    SearchProviderUnavailable,
    brave_status,
)


def test_brave_status_without_key(monkeypatch):
    monkeypatch.delenv(
        "BRAVE_SEARCH_API_KEY",
        raising=False,
    )

    status = brave_status()

    assert status.available is False


def test_brave_requires_key(monkeypatch):
    monkeypatch.delenv(
        "BRAVE_SEARCH_API_KEY",
        raising=False,
    )

    with pytest.raises(
        SearchProviderUnavailable
    ):
        BravePublicSearch()


def test_brave_status_with_key(monkeypatch):
    monkeypatch.setenv(
        "BRAVE_SEARCH_API_KEY",
        "test-key",
    )

    status = brave_status()

    assert status.available is True
