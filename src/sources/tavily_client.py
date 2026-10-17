"""Tavily Search/Extract API 클라이언트.

공식 문서 확인일: 2026-10-18 (docs.tavily.com OpenAPI)
- Search:  POST https://api.tavily.com/search
- Extract: POST https://api.tavily.com/extract
- 인증: Authorization: Bearer tvly-...
- 크레딧: search basic 1크레딧/회, advanced 2크레딧/회.
  extract basic 1크레딧/성공 5URL, advanced 2크레딧/성공 5URL.
- 무료 플랜: 월 1,000 크레딧 (카드 불필요)
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from ..errors import AuthError, RateLimitError, UpstreamError
from ..models import WebResult

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"


@dataclass
class ExtractedDoc:
    url: str
    content: str  # markdown 또는 text


class TavilyClient:
    def __init__(self, api_key: str, timeout: float = 30.0, max_retries: int = 1,
                 session: requests.Session | None = None,
                 sleep_fn=time.sleep):
        if not api_key:
            raise AuthError("Tavily API 키가 없어요 (TAVILY_API_KEY).")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = session or requests.Session()
        self._sleep = sleep_fn

    def search(self, query: str, max_results: int = 8,
               search_depth: str = "basic") -> list[WebResult]:
        """웹 검색. basic은 1크레딧, advanced는 2크레딧."""
        payload = {
            "query": query,
            "max_results": min(max_results, 20),
            "search_depth": search_depth,
        }
        data = self._post(SEARCH_URL, payload)
        return [
            WebResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                description=item.get("content", ""),
                engine="tavily",
            )
            for item in data.get("results", [])
        ]

    def extract(self, urls: list[str], extract_depth: str = "basic",
                fmt: str = "text") -> list[ExtractedDoc]:
        """URL 본문 추출. basic은 성공 5URL당 1크레딧."""
        if not urls:
            return []
        payload = {"urls": urls[:20], "extract_depth": extract_depth, "format": fmt}
        data = self._post(EXTRACT_URL, payload)
        return [
            ExtractedDoc(url=item.get("url", ""), content=item.get("raw_content", "") or "")
            for item in data.get("results", [])
        ]

    def _post(self, url: str, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._session.post(url, json=payload, headers=headers,
                                          timeout=self._timeout)
            except requests.RequestException as exc:
                raise UpstreamError(f"Tavily 연결 실패: {exc}") from exc

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise UpstreamError("Tavily 응답이 JSON이 아니에요.") from exc
            if resp.status_code == 401:
                raise AuthError("Tavily 인증 실패 (HTTP 401). 키를 확인하세요.")
            if resp.status_code in (402, 429):
                if attempt < self._max_retries:
                    self._sleep(1.0 * (attempt + 1))
                    continue
                raise RateLimitError("Tavily 크레딧 한도를 초과했어요.")
            if resp.status_code >= 500 and attempt < self._max_retries:
                self._sleep(0.5 * (attempt + 1))
                last_error = UpstreamError(f"Tavily 서버 오류 (HTTP {resp.status_code})")
                continue
            raise UpstreamError(f"Tavily 요청 실패 (HTTP {resp.status_code}): {resp.text[:200]}")
        raise last_error or UpstreamError("Tavily 요청 실패")
