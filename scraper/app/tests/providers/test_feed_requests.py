import logging

import httpx
import pytest

from app.providers.news_provider import DEFAULT_HEADERS, NewsProvider
from app.providers.primorskenovice import PrimorskeNoviceProvider


def _provider() -> NewsProvider:
    return NewsProvider(
        key="example",
        name="Example",
        url="https://example.com",
        rss_feeds=["https://example.com/rss.xml"],
    )


def _assert_request_timeout(timeout: httpx.Timeout) -> None:
    assert timeout == httpx.Timeout(20, connect=10)


def test_default_headers_use_current_chrome_and_slovenian_language():
    user_agent = DEFAULT_HEADERS["User-Agent"]
    assert "Chrome/157.0.0.0" in user_agent
    assert "Chrome/91" not in user_agent
    assert "Chrome/58" not in user_agent
    assert DEFAULT_HEADERS["Accept"]
    assert "text/html" in DEFAULT_HEADERS["Accept"]
    assert DEFAULT_HEADERS["Accept-Language"] == "sl-SI,sl;q=0.9,en;q=0.8"


@pytest.mark.asyncio
async def test_fetch_rss_feed_sends_shared_headers_and_timeout():
    captured: dict = {}

    class Client:
        def __init__(self):
            self.follow_redirects = False
            self.headers: dict = {}

        async def get(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs

            class Response:
                text = "<rss></rss>"

                def raise_for_status(self):
                    return None

            return Response()

    client = Client()
    articles = await _provider().fetch_rss_feed(client, "https://example.com/rss.xml")

    assert articles == []
    assert client.follow_redirects is True
    assert captured["url"] == "https://example.com/rss.xml"
    assert captured["kwargs"]["headers"] == DEFAULT_HEADERS
    _assert_request_timeout(captured["kwargs"]["timeout"])


@pytest.mark.asyncio
async def test_fetch_article_html_sends_shared_headers_and_timeout(monkeypatch):
    captured: dict = {}

    class Client:
        def __init__(self, *args, **kwargs):
            captured["client_kwargs"] = kwargs
            self.follow_redirects = False
            self.headers: dict = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            captured["follow_redirects"] = self.follow_redirects

            class Response:
                text = "<html>ok</html>"

                def raise_for_status(self):
                    return None

            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    html = await _provider().fetch_article_html("https://example.com/story")

    assert html == "<html>ok</html>"
    assert captured["follow_redirects"] is True
    assert captured["kwargs"]["headers"] == DEFAULT_HEADERS
    _assert_request_timeout(captured["kwargs"]["timeout"])


@pytest.mark.asyncio
async def test_rss_errors_log_exception_type_and_repr(caplog):
    provider = _provider()

    async def fail(client, feed_url):
        raise httpx.ConnectTimeout("")

    provider.fetch_rss_feed = fail
    with caplog.at_level(logging.ERROR):
        assert await provider.fetch_articles() == []

    message = caplog.records[-1].getMessage()
    assert "ConnectTimeout" in message
    assert "ConnectTimeout('')" in message
    assert "https://example.com/rss.xml" in message


def test_image_extraction_errors_log_exception_type_and_repr(caplog):
    class BrokenImages(NewsProvider):
        def parse_rss_entry_image_urls(self, entry):
            raise RuntimeError("")

        def extract_image_urls_from_html(self, html):
            raise RuntimeError("")

    provider = BrokenImages(
        key="example",
        name="Example",
        url="https://example.com",
        rss_feeds=[],
    )
    with caplog.at_level(logging.ERROR):
        article = provider.parse_rss_feed_entry(
            {"title": "Naslov", "link": "https://example.com/story"}
        )
        extracted = provider.extract_article_from_html(
            "<html><head><title>Naslov</title></head><body>Besedilo</body></html>",
            "https://example.com/story",
        )

    assert article.image_urls == []
    assert extracted.image_urls == []
    messages = [record.getMessage() for record in caplog.records]
    assert any("Error extracting image URLs for Example" in message for message in messages)
    assert any(
        "Error extracting image URLs from article HTML" in message for message in messages
    )
    for message in messages:
        assert "RuntimeError" in message
        assert "RuntimeError('')" in message


def test_extract_article_allows_missing_deck():
    # readability returns excerpt=None for pages like sta.si, which used to
    # reject the whole article because deck was required.
    provider = _provider()

    extracted = provider.extract_article_from_html(
        "<html><head><title>Naslov</title></head><body>Besedilo</body></html>",
        "https://www.sta.si/123",
    )

    assert extracted.deck is None
    assert extracted.title
    assert extracted.url == "https://www.sta.si/123"


def test_primorske_feed_uses_current_site():
    provider = PrimorskeNoviceProvider()

    assert provider.url == "https://primorske.si"
    assert provider.rss_feeds == ["https://primorske.si/rss.xml"]
