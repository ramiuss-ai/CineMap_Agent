"""TMDB API 클라이언트 (모듈 2: 영화 식별).

공식 문서 확인일: 2026-10-18 (developer.themoviedb.org)
- 검색:   GET https://api.themoviedb.org/3/search/movie
          params: query(필수), language, year, primary_release_year, page, include_adult
- 상세:   GET https://api.themoviedb.org/3/movie/{id}?append_to_response=credits
          (credits.crew 중 job == "Director"가 감독)
- 인증:   v3 API 키는 ?api_key= 쿼리 파라미터,
          v4 Read Access Token은 Authorization: Bearer 헤더.
          두 방식 모두 v3 엔드포인트에서 동작 (공식 authentication 문서).
- 이미지: https://image.tmdb.org/t/p/{size}{poster_path}  (예: w342)
- 레이트리밋: 초당 약 40회 상한. 429를 받으면 Retry-After를 존중.
- 약관:   캐시는 최대 6개월까지만 허용. 앱에 TMDB 로고와 고지 문구를 표시해야 함
          ("This application uses TMDB and the TMDB APIs but is not endorsed,
          certified, or otherwise approved by TMDB.")
"""
from __future__ import annotations

import time

import requests

from ..errors import AuthError, RateLimitError, UpstreamError

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"

# 약관상 캐시 상한은 6개월. 앱/클라이언트 캐시는 이보다 훨씬 짧게(시간 단위) 잡는다.
CACHE_TTL_SECONDS = 3600  # 1시간


def poster_url(poster_path: str | None, size: str = "w342") -> str | None:
    """poster_path를 전체 이미지 URL로. 없으면 None."""
    if not poster_path:
        return None
    return f"{IMAGE_BASE}/{size}{poster_path}"


class TMDBClient:
    """v3 api_key와 v4 read access token을 모두 지원하는 최소 클라이언트."""

    def __init__(self, credential: str, timeout: float = 20.0,
                 max_retries: int = 1,
                 session: requests.Session | None = None,
                 sleep_fn=time.sleep,
                 min_interval: float = 0.25):
        if not credential:
            raise AuthError("TMDB API 키가 없어요 (TMDB_API_KEY).")
        self._credential = credential
        # v4 Read Access Token은 JWT 형태(마침표 2개). v3 키는 32자 16진수.
        self._use_bearer = credential.count(".") >= 2
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = session or requests.Session()
        self._sleep = sleep_fn
        self._min_interval = min_interval  # 초당 40회 상한에 대한 여유 있는 자체 제한
        self._last_call = 0.0
        self._cache: dict[tuple, tuple[float, dict]] = {}

    # --- 공개 메서드 ------------------------------------------------------

    def search_movie(self, query: str, year: int | None = None,
                     language: str = "ko-KR", page: int = 1) -> list[dict]:
        """영화 검색. raw result dict 리스트를 돌려준다."""
        params: dict = {
            "query": query,
            "language": language,
            "include_adult": "false",
            "page": page,
        }
        if year:
            params["year"] = str(year)
        data = self._get("/search/movie", params)
        return data.get("results", [])

    def movie_details(self, movie_id: int, language: str = "ko-KR") -> dict:
        """영화 상세 + credits (감독 포함)를 한 번에."""
        return self._get(f"/movie/{movie_id}",
                         {"language": language, "append_to_response": "credits"})

    # --- 내부 --------------------------------------------------------------

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)

    def _get(self, path: str, params: dict) -> dict:
        cache_key = (path, tuple(sorted((k, str(v)) for k, v in params.items())))
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

        url = BASE_URL + path
        params = dict(params)
        headers = {"accept": "application/json"}
        if self._use_bearer:
            headers["Authorization"] = f"Bearer {self._credential}"
        else:
            params["api_key"] = self._credential

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                resp = self._session.get(url, params=params, headers=headers,
                                         timeout=self._timeout)
            except requests.RequestException as exc:
                raise UpstreamError(f"TMDB 연결 실패: {exc}") from exc
            finally:
                self._last_call = time.monotonic()

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise UpstreamError("TMDB 응답이 JSON이 아니에요.") from exc
                self._cache[cache_key] = (time.monotonic(), data)
                return data
            if resp.status_code in (401, 403):
                raise AuthError("TMDB 인증 실패 (HTTP "
                                f"{resp.status_code}). 키/토큰을 확인하세요.")
            if resp.status_code == 429:
                if attempt < self._max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    self._sleep(float(retry_after) if retry_after else 1.0)
                    continue
                raise RateLimitError("TMDB 호출 한도를 초과했어요.")
            if resp.status_code >= 500 and attempt < self._max_retries:
                self._sleep(0.5 * (attempt + 1))
                last_error = UpstreamError(f"TMDB 서버 오류 (HTTP {resp.status_code})")
                continue
            raise UpstreamError(
                f"TMDB 요청 실패 (HTTP {resp.status_code}): {resp.text[:200]}")
        raise last_error or UpstreamError("TMDB 요청 실패")