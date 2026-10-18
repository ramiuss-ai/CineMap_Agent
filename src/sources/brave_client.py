"""Brave Search API (Web Search) 클라이언트.

공식 문서 확인일: 2026-10-18
- 엔드포인트: GET https://api.search.brave.com/res/v1/web/search
- 인증: X-Subscription-Token 헤더
- 주요 파라미터: q, count(최대 20), offset(최대 9), country, search_lang, safesearch
- 과금: 종량제 크레딧, 웹 검색 $5/1,000건 (brave.com/search/api 기준)
"""
from __future__ import annotations

import time

import requests

from ..errors import AuthError, RateLimitError, UpstreamError
from ..models import WebResult

BASE_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchClient:
    def __init__(self, api_key: str, timeout: float = 10.0, max_retries: int = 2,
                 session: requests.Session | None = None,
                 sleep_fn=time.sleep):
        if not api_key:
            raise AuthError("Brave Search API 키가 없어요 (BRAVE_API_KEY).")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = session or requests.Session()
        self._sleep = sleep_fn  # 테스트에서 대기 없이 주입

    def search(self, query: str, count: int = 10, country: str | None = None,
               search_lang: str | None = None,
               safesearch: str = "moderate") -> list[WebResult]:
        params: dict = {"q": query, "count": min(count, 20), "safesearch": safesearch}
        if country:
            params["country"] = country
        if search_lang:
            params["search_lang"] = search_lang

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._session.get(
                    BASE_URL,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": self._api_key,
                    },
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                raise UpstreamError(f"Brave 검색 연결 실패: {exc}") from exc

            if resp.status_code == 200:
                return self._parse(resp)
            if resp.status_code in (401, 403):
                raise AuthError(f"Brave Search 인증 실패 (HTTP {resp.status_code}). 키를 확인하세요.")
            if resp.status_code in (402, 429):
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                if attempt < self._max_retries:
                    self._sleep(retry_after or 1.0 * (attempt + 1))
                    continue
                raise RateLimitError("Brave Search 호출 한도를 초과했어요.", retry_after)
            if resp.status_code >= 500 and attempt < self._max_retries:
                self._sleep(0.5 * (attempt + 1))
                last_error = UpstreamError(f"Brave 서버 오류 (HTTP {resp.status_code})")
                continue
            raise UpstreamError(f"Brave 검색 실패 (HTTP {resp.status_code}): {resp.text[:200]}")
        raise last_error or UpstreamError("Brave 검색 실패")

    @staticmethod
    def _parse(resp: requests.Response) -> list[WebResult]:
        try:
            data = resp.json()
        except ValueError as exc:
            raise UpstreamError("Brave 응답이 JSON이 아니에요.") from exc
        results = (data.get("web") or {}).get("results") or []
        return [
            WebResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                description=item.get("description", ""),
                engine="brave",
            )
            for item in results
        ]


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
