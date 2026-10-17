"""테스트 공용 가짜 객체. 실제 API는 절대 호출하지 않는다."""
from __future__ import annotations

import pytest


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text or (str(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """요청 순서대로 응답을 반환. 호출 기록도 남긴다."""

    def __init__(self, responses=None, post_responses=None):
        self.get_responses = list(responses or [])
        self.post_responses = list(post_responses or [])
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if not self.get_responses:
            raise AssertionError(f"예상 못한 GET 호출: {url}")
        item = self.get_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if not self.post_responses:
            raise AssertionError(f"예상 못한 POST 호출: {url}")
        item = self.post_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def no_sleep():
    return lambda _: None
