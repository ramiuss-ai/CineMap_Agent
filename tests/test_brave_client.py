import pytest

from src.errors import AuthError, RateLimitError, UpstreamError
from src.sources.brave_client import BraveSearchClient
from tests.conftest import FakeResponse, FakeSession

PAYLOAD = {
    "web": {
        "results": [
            {"title": "부산행 (2016) - 위키백과", "url": "https://ko.wikipedia.org/wiki/부산행",
             "description": "2016년 한국 영화"},
            {"title": "Train to Busan filming locations", "url": "https://example.com/loc",
             "description": "filmed at Dongdaegu Station"},
        ]
    }
}


def test_search_parses_results(no_sleep):
    session = FakeSession(responses=[FakeResponse(200, PAYLOAD)])
    client = BraveSearchClient("key", session=session, sleep_fn=no_sleep)
    results = client.search("부산행 영화", count=5, country="KR", search_lang="ko")
    assert len(results) == 2
    assert results[0].title.startswith("부산행")
    assert results[1].engine == "brave"
    # 요청 형태 확인: 헤더와 파라미터
    method, url, kwargs = session.calls[0]
    assert url == "https://api.search.brave.com/res/v1/web/search"
    assert kwargs["headers"]["X-Subscription-Token"] == "key"
    assert kwargs["params"]["q"] == "부산행 영화"
    assert kwargs["params"]["count"] == 5
    assert kwargs["params"]["country"] == "KR"
    assert kwargs["params"]["search_lang"] == "ko"


def test_empty_web_results(no_sleep):
    session = FakeSession(responses=[FakeResponse(200, {})])
    client = BraveSearchClient("key", session=session, sleep_fn=no_sleep)
    assert client.search("없는영화") == []


def test_auth_error_not_retried(no_sleep):
    session = FakeSession(responses=[FakeResponse(401, text="unauthorized")])
    client = BraveSearchClient("key", session=session, sleep_fn=no_sleep)
    with pytest.raises(AuthError):
        client.search("부산행")
    assert len(session.calls) == 1


def test_rate_limit_retry_then_success(no_sleep):
    session = FakeSession(responses=[
        FakeResponse(429, headers={"Retry-After": "0"}),
        FakeResponse(200, PAYLOAD),
    ])
    client = BraveSearchClient("key", session=session, sleep_fn=no_sleep)
    assert len(client.search("부산행")) == 2
    assert len(session.calls) == 2


def test_rate_limit_exhausted(no_sleep):
    session = FakeSession(responses=[FakeResponse(429) for _ in range(3)])
    client = BraveSearchClient("key", max_retries=2, session=session, sleep_fn=no_sleep)
    with pytest.raises(RateLimitError):
        client.search("부산행")
    assert len(session.calls) == 3


def test_server_error_retry_then_fail(no_sleep):
    session = FakeSession(responses=[FakeResponse(500), FakeResponse(503)])
    client = BraveSearchClient("key", max_retries=1, session=session, sleep_fn=no_sleep)
    with pytest.raises(UpstreamError):
        client.search("부산행")


def test_missing_key():
    with pytest.raises(AuthError):
        BraveSearchClient("")
