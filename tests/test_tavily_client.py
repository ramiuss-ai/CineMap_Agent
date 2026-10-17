import pytest

from src.errors import AuthError, RateLimitError, UpstreamError
from src.sources.tavily_client import TavilyClient
from tests.conftest import FakeResponse, FakeSession

SEARCH_PAYLOAD = {
    "results": [
        {"title": "부산행 촬영지", "url": "https://example.com/a",
         "content": "부산역과 동대구역에서 촬영했다", "score": 0.9},
    ]
}
EXTRACT_PAYLOAD = {
    "results": [
        {"url": "https://example.com/a", "raw_content": "부산행 촬영지: 부산역, 동대구역"},
    ],
    "failed_results": [],
}


def test_search_request_shape_and_parse(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(200, SEARCH_PAYLOAD)])
    client = TavilyClient("tvly-test", session=session, sleep_fn=no_sleep)
    results = client.search("부산행 촬영지", max_results=8)
    assert len(results) == 1
    assert results[0].engine == "tavily"
    method, url, kwargs = session.calls[0]
    assert url == "https://api.tavily.com/search"
    assert kwargs["headers"]["Authorization"] == "Bearer tvly-test"
    assert kwargs["json"]["search_depth"] == "basic"  # 크레딧 절약 기본값
    assert kwargs["json"]["max_results"] == 8


def test_extract_request_shape_and_parse(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(200, EXTRACT_PAYLOAD)])
    client = TavilyClient("tvly-test", session=session, sleep_fn=no_sleep)
    docs = client.extract(["https://example.com/a"])
    assert len(docs) == 1
    assert "부산역" in docs[0].content
    method, url, kwargs = session.calls[0]
    assert url == "https://api.tavily.com/extract"
    assert kwargs["json"]["urls"] == ["https://example.com/a"]
    assert kwargs["json"]["format"] == "text"


def test_extract_empty_urls_skips_call(no_sleep):
    session = FakeSession()
    client = TavilyClient("tvly-test", session=session, sleep_fn=no_sleep)
    assert client.extract([]) == []
    assert session.calls == []


def test_auth_error(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(401, text="Unauthorized")])
    client = TavilyClient("tvly-bad", session=session, sleep_fn=no_sleep)
    with pytest.raises(AuthError):
        client.search("부산행")


def test_quota_error_402(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(402), FakeResponse(402)])
    client = TavilyClient("tvly-test", max_retries=1, session=session, sleep_fn=no_sleep)
    with pytest.raises(RateLimitError):
        client.search("부산행")


def test_missing_key():
    with pytest.raises(AuthError):
        TavilyClient(None)
