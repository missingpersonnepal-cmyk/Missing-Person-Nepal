import pytest

from app.services.search_providers import (
    SearchProviderUnavailable,
    SerperPublicSearch,
    serper_status,
)


class FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "organic": [
                {
                    "position": 1,
                    "title": "Person Missing Test Person",
                    "link": (
                        "https://www.facebook.com/example/posts/123/"
                    ),
                    "snippet": (
                        "Person Missing Test Person has been "
                        "out of contact in Rasuwa."
                    ),
                },
                {
                    # Exact duplicate should be suppressed.
                    "position": 2,
                    "title": "Duplicate result",
                    "link": (
                        "https://www.facebook.com/example/posts/123/"
                    ),
                    "snippet": "duplicate",
                },
            ]
        }


def test_serper_requires_api_key(monkeypatch):
    monkeypatch.delenv(
        "SERPER_API_KEY",
        raising=False,
    )

    with pytest.raises(SearchProviderUnavailable):
        SerperPublicSearch()


def test_serper_status_without_key(monkeypatch):
    monkeypatch.delenv(
        "SERPER_API_KEY",
        raising=False,
    )

    status = serper_status()

    assert status.available is False


def test_serper_parses_and_deduplicates_results(
    monkeypatch,
):
    monkeypatch.setenv(
        "SERPER_API_KEY",
        "x" * 40,
    )

    provider = SerperPublicSearch()

    monkeypatch.setattr(
        provider.client,
        "post",
        lambda *args, **kwargs: FakeResponse(),
    )

    results = provider.search(
        'site:facebook.com "Person Missing" Rasuwa',
        max_results=10,
    )

    assert len(results) == 1

    assert (
        results[0].url
        == "https://facebook.com/example/posts/123"
    )

    assert "Test Person" in results[0].title

    assert "Rasuwa" in results[0].snippet


def test_serper_sends_minimal_validated_payload(
    monkeypatch,
):
    monkeypatch.setenv(
        "SERPER_API_KEY",
        "x" * 40,
    )

    provider = SerperPublicSearch()

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResponse()

    monkeypatch.setattr(
        provider.client,
        "post",
        fake_post,
    )

    provider.search(
        'site:facebook.com "Buddha Sang Ghale"',
    )

    assert captured["url"] == (
        "https://google.serper.dev/search"
    )

    assert captured["json"] == {
        "q": 'site:facebook.com "Buddha Sang Ghale"'
    }
