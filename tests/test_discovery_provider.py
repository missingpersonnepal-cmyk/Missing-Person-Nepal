import httpx

from app.services.discovery import DuckDuckGoPublicSearch


class FakeClient:
    def post(self, *args, **kwargs):
        html = '''
        <html><body>
          <div class="result">
            <a class="result__a" href="https://www.facebook.com/groups/rasuwa/posts/123">Missing person Rasuwa</a>
            <div class="result__snippet">सम्पर्कविहीन Timure Rasuwa</div>
          </div>
        </body></html>
        '''
        return httpx.Response(200, text=html, request=httpx.Request("POST", "https://html.duckduckgo.com/html/"))


def test_public_search_provider_parses_candidate():
    provider = DuckDuckGoPublicSearch()
    provider.client = FakeClient()
    rows = provider.search('site:facebook.com "Rasuwa" "सम्पर्कविहीन"')
    assert len(rows) == 1
    assert rows[0].url == "https://facebook.com/groups/rasuwa/posts/123"
    assert "सम्पर्कविहीन" in rows[0].snippet
