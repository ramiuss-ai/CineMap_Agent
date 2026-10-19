"""TMDBClient 테스트. 실제 API는 절대 호출하지 않고 가짜 세션을 쓴다."""
from __future__ import annotations

import pytest

from src.errors import AuthError, RateLimitError, UpstreamError
from src.sources.tmdb_client import TMDBClient, poster_url
from tests.conftest import FakeResponse, FakeSession

V3_KEY = "0123456789abcdef0123456789abcdef"
V4_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJ4In0.signature"  # JWT 형태


def make_client(responses, credential=V3_KEY, no_sleep=None):
    session = FakeSession(responses=responses)
    client = TMDBClient(credential, session=session,
                        sleep_fn=no_sleep or (lambda _: None),
                        min_interval=0)
    return client, session


class TestAuth:
    def test_v3_key_goes_in_query_param(self, no_sleep):
        client, session = make_client([FakeResponse(200, {"results": []})],
                                      no_sleep=no_sleep)
        client.search_movie("해리포터")
        _, url, kwargs = session.calls[0]
        assert kwargs["params"]["api_key"] == V3_KEY
        assert "Authorization" not in kwargs["headers"]

    def test_v4_token_goes_in_bearer_header(self, no_sleep):
        client, session = make_client([FakeResponse(200, {"results": []})],
                                      credential=V4_TOKEN, no_sleep=no_sleep)
        client.search_movie("harry potter")
        _, url, kwargs = session.calls[0]
        assert kwargs["headers"]["Authorization"] == f"Bearer {V4_TOKEN}"
        assert "api_key" not in kwargs["params"]

    def test_empty_key_raises(self):
        with pytest.raises(AuthError):
            TMDBClient("")


class TestSearchMovie:
    def test_params_and_parse(self, no_sleep):
        results = [{"id": 671, "title": "해리포터와 마법사의 돌",
                    "original_title": "Harry Potter and the Philosopher's Stone",
                    "release_date": "2001-11-16", "overview": "...", "poster_path": "/x.jpg"}]
        client, session = make_client([FakeResponse(200, {"results": results})],
                                      no_sleep=no_sleep)
        out = client.search_movie("해리포터", year=2001, language="ko-KR")
        assert out[0]["id"] == 671
        _, url, kwargs = session.calls[0]
        assert url.endswith("/3/search/movie")
        assert kwargs["params"]["query"] == "해리포터"
        assert kwargs["params"]["language"] == "ko-KR"
        assert kwargs["params"]["year"] == "2001"
        assert kwargs["params"]["include_adult"] == "false"

    def test_year_omitted_when_none(self, no_sleep):
        client, session = make_client([FakeResponse(200, {"results": []})],
                                      no_sleep=no_sleep)
        client.search_movie("기생충")
        assert "year" not in session.calls[0][2]["params"]


class TestMovieDetails:
    def test_append_to_response_credits(self, no_sleep):
        payload = {"id": 671, "title": "해리포터와 마법사의 돌",
                   "credits": {"crew": [{"job": "Director", "name": "Chris Columbus"}]}}
        client, session = make_client([FakeResponse(200, payload)], no_sleep=no_sleep)
        data = client.movie_details(671)
        assert data["credits"]["crew"][0]["name"] == "Chris Columbus"
        _, url, kwargs = session.calls[0]
        assert url.endswith("/3/movie/671")
        assert kwargs["params"]["append_to_response"] == "credits"


class TestErrors:
    def test_401_is_auth_error(self, no_sleep):
        client, _ = make_client([FakeResponse(401, text="bad key")], no_sleep=no_sleep)
        with pytest.raises(AuthError):
            client.search_movie("x")

    def test_403_is_auth_error(self, no_sleep):
        client, _ = make_client([FakeResponse(403, text="forbidden")],
                                no_sleep=no_sleep)
        with pytest.raises(AuthError):
            client.search_movie("x")

    def test_429_retry_then_rate_limit(self, no_sleep):
        client, session = make_client(
            [FakeResponse(429, headers={"Retry-After": "0"}, text="slow down"),
             FakeResponse(429, text="still")], no_sleep=no_sleep)
        with pytest.raises(RateLimitError):
            client.search_movie("x")
        assert len(session.calls) == 2  # 한 번 재시도

    def test_500_retry_then_success(self, no_sleep):
        client, _ = make_client(
            [FakeResponse(503, text="down"),
             FakeResponse(200, {"results": [{"id": 1}]})], no_sleep=no_sleep)
        assert client.search_movie("x") == [{"id": 1}]

    def test_other_http_error(self, no_sleep):
        client, _ = make_client([FakeResponse(404, text="nope")], no_sleep=no_sleep)
        with pytest.raises(UpstreamError):
            client.search_movie("x")

    def test_non_json_200(self, no_sleep):
        client, _ = make_client([FakeResponse(200, payload=None)], no_sleep=no_sleep)
        with pytest.raises(UpstreamError):
            client.search_movie("x")


class TestCache:
    def test_second_same_call_uses_cache(self, no_sleep):
        client, session = make_client([FakeResponse(200, {"results": []})],
                                      no_sleep=no_sleep)
        client.search_movie("x")
        client.search_movie("x")
        assert len(session.calls) == 1  # 캐시가 두 번째 호출을 막는다


class TestPosterUrl:
    def test_builds_url(self):
        assert poster_url("/abc.jpg") == "https://image.tmdb.org/t/p/w342/abc.jpg"

    def test_none_when_missing(self):
        assert poster_url(None) is None
        assert poster_url("") is None