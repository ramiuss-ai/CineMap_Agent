"""모듈 2 파이프라인: 제목(ko/en) → TMDB 영화 후보 → 사용자 확정 → Movie.

흐름:
1) search_movies(): TMDB 검색을 ko-KR로 먼저, 결과가 없으면 en-US로 폴백.
   둘 다 나오면 ko 결과를 우선하되 같은 tmdb_id는 합친다.
2) confirm_movie(): 선택한 후보의 상세+credits를 가져와 감독/영어제목을 확정.
   영어 제목은 original_title이 로마자면 그것을, 아니면(한국 영화 등)
   en-US 상세의 title을 한 번 더 가져와 쓴다.
3) 확정된 Movie(english_title + year)를 모듈 1 find_film_locations()에 넣는다.
"""
from __future__ import annotations

import re

from .models import Movie, MovieCandidate
from .sources.tmdb_client import poster_url

_ASCII_RE = re.compile(r"[A-Za-z]")


def _year_of(item: dict) -> int | None:
    date = (item.get("release_date") or "")[:4]
    return int(date) if date.isdigit() else None


def _to_candidate(item: dict) -> MovieCandidate:
    return MovieCandidate(
        title=item.get("title") or item.get("original_title") or "",
        year=_year_of(item),
        source_url=f"https://www.themoviedb.org/movie/{item.get('id')}",
        tmdb_id=item.get("id"),
        original_title=item.get("original_title"),
        overview=item.get("overview") or "",
        poster_url=poster_url(item.get("poster_path")),
    )


def search_movies(title: str, year: int | None = None, tmdb=None,
                  max_candidates: int = 8) -> list[MovieCandidate]:
    """TMDB에서 영화 후보를 찾는다. ko-KR 우선, en-US 폴백/보강."""
    ko_results = tmdb.search_movie(title, year=year, language="ko-KR")
    en_results: list[dict] = []
    if not ko_results or len(ko_results) < max_candidates:
        # ko 결과가 없거나 적으면 en-US로 보강 (같은 id는 ko 쪽 우선)
        en_results = tmdb.search_movie(title, year=year, language="en-US")

    candidates: list[MovieCandidate] = []
    by_id: dict[int, MovieCandidate] = {}
    for item in ko_results + en_results:
        mid = item.get("id")
        if mid is None or mid in by_id:
            # ko 결과가 먼저라 이미 있으면, 비어 있는 개요만 en으로 채운다
            if mid in by_id and not by_id[mid].overview:
                by_id[mid].overview = item.get("overview") or ""
            continue
        cand = _to_candidate(item)
        by_id[mid] = cand
        candidates.append(cand)
        if len(candidates) >= max_candidates:
            break
    return candidates


def _director_of(details: dict) -> str | None:
    crew = (details.get("credits") or {}).get("crew") or []
    names = [m.get("name") for m in crew if m.get("job") == "Director" and m.get("name")]
    return ", ".join(names) if names else None


def _looks_latin(text: str | None) -> bool:
    return bool(text) and bool(_ASCII_RE.search(text))


def confirm_movie(candidate: MovieCandidate, tmdb,
                  language: str = "ko-KR") -> Movie:
    """후보를 확정 Movie로 만든다. english_title은 모듈 1 검색용."""
    details = tmdb.movie_details(candidate.tmdb_id, language=language)

    title = details.get("title") or candidate.title
    original_title = details.get("original_title") or candidate.original_title

    # 영어 제목 결정: original_title이 로마자면 충분. 아니면 en-US 상세를 한 번 더.
    if _looks_latin(original_title):
        english_title = original_title
    else:
        en_details = tmdb.movie_details(candidate.tmdb_id, language="en-US")
        english_title = en_details.get("title") or original_title or title

    overview = details.get("overview") or candidate.overview
    poster = poster_url(details.get("poster_path")) or candidate.poster_url
    year = _year_of(details) or candidate.year
    countries = [c.get("iso_3166_1") for c in details.get("production_countries") or []
                 if c.get("iso_3166_1")]

    return Movie(
        tmdb_id=candidate.tmdb_id,
        title=title,
        english_title=english_title,
        year=year,
        director=_director_of(details),
        overview=overview,
        poster_url=poster,
        original_title=original_title,
        tmdb_url=f"https://www.themoviedb.org/movie/{candidate.tmdb_id}",
        production_countries=countries,
    )
