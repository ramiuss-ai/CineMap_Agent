"""모듈 1 파이프라인: 영화 제목(ko/en) → 촬영지 후보 목록.

흐름:
1) 검색(Brave + Tavily)으로 같은 제목의 영화가 여러 편인지 확인 → ambiguous
2) "<제목> 촬영지", "<제목> filming locations" 검색
3) Tavily Extract로 상위 페이지 본문 확보 (실패 시 스니펫으로 폴백)
4) 규칙 기반 추출기로 촬영지 문구 수집
5) Google Places Text Search로 각 문구를 장소(이름/주소/좌표/place_id)로 확인
6) 언급 소스 수 + Places 확인 여부로 confidence 계산

비용을 아끼기 위해:
- 모호한 제목은 year가 정해질 때까지 Places를 호출하지 않는다.
- Places 확인은 고유 문구 상위 max_resolve개까지만.
"""
from __future__ import annotations

import re

from .errors import AuthError, SourceError
from .extract_names import extract_mentions, mentions_from_results
from .models import (FilmLocation, LocationMention, LocationSearchResult,
                     MovieCandidate, WebResult)

# 대한민국 대략 경계상자 (addressComponents에 국가 코드가 없을 때만 쓰는 폴백)
_KR_LAT_MIN, _KR_LAT_MAX = 33.0, 38.8
_KR_LON_MIN, _KR_LON_MAX = 124.0, 132.1


def is_korea_place(place) -> bool:
    """이 장소가 한국에 있는지 추정한다.

    1순위: Google Places addressComponents의 국가 코드 ("KR").
    2순위(코드가 없을 때): 주소의 "대한민국"/"South Korea" 문자열,
    마지막으로 좌표 경계상자. 경계상자는 휴전선 부근에서 다소 넓게 잡히지만,
    국가 코드가 빠진 드문 경우의 폴백이라 그 정도 오차는 감수한다.
    """
    code = getattr(place, "country_code", None)
    if code:
        return code.upper() == "KR"
    addr = (getattr(place, "address", "") or "").lower()
    if "대한민국" in addr or "south korea" in addr:
        return True
    lat, lon = getattr(place, "lat", None), getattr(place, "lon", None)
    if lat is None or lon is None:
        return False
    return _KR_LAT_MIN <= lat <= _KR_LAT_MAX and _KR_LON_MIN <= lon <= _KR_LON_MAX


_YEAR_RE = re.compile(r"\((\d{4})\)")
_FILM_WORD_RE = re.compile(r"(영화|film|movie)", re.IGNORECASE)
# 검색 결과 제목에서 영화 제목으로 보이는 패턴: "제목 (2016)" / "제목 (2016년 영화)"
_CANDIDATE_RE = re.compile(r"^(.+?)\s*\((\d{4})(?:년)?[^)]*\)")


def find_movie_candidates(query: str, brave, tavily,
                          max_candidates: int = 5) -> list[MovieCandidate]:
    """같은 제목의 영화가 여러 편인지 검색 결과 제목에서 추정한다."""
    results = _search_both(f"{query} 영화", brave, tavily, max_results=8)[0]
    candidates: list[MovieCandidate] = []
    seen: set[tuple[str, int | None]] = set()
    q_norm = query.strip().lower()

    for r in results:
        m = _CANDIDATE_RE.match(r.title.strip())
        if not m:
            continue
        title, year = m.group(1).strip(), int(m.group(2))
        # 입력 제목이 결과 제목에 포함되거나, 반대일 때만 후보로 인정
        if q_norm not in title.lower() and title.lower() not in q_norm:
            continue
        key = (title.lower(), year)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(MovieCandidate(title=title, year=year, source_url=r.url))
        if len(candidates) >= max_candidates:
            break
    return candidates


def find_film_locations(title: str, year: int | None = None,
                        brave=None, tavily=None, places=None,
                        max_resolve: int = 12,
                        max_extract_urls: int = 5,
                        allow_korea: bool = True) -> LocationSearchResult:
    """메인 진입점. title은 한글/영어 모두 가능, year가 있으면 모호성 해소.

    allow_korea=False이면 한국에 있는 장소를 후보에서 뺀다. 모듈 2에서 확정한
    영화의 제작 국가(production_countries)에 한국(KR)이 없을 때 쓴다 —
    외국 영화 검색에서 한국 업소가 억지로 끼어드는 걸 막기 위해서다.
    TMDB 확인 없이 모듈 1만 쓸 때는 기본값(True)이라 아무것도 빼지 않는다.
    """
    warnings: list[str] = []

    # 1) 모호성 확인: year가 없으면 후보가 2개 이상인지 먼저 본다
    if year is None and brave is not None and tavily is not None:
        try:
            candidates = find_movie_candidates(title, brave, tavily)
            distinct_years = {c.year for c in candidates if c.year}
            if len(candidates) >= 2 and len(distinct_years) >= 2:
                return LocationSearchResult(
                    query=title, status="ambiguous", movie_candidates=candidates)
        except SourceError as exc:
            warnings.append(f"영화 후보 확인 실패, 계속 진행해요: {exc}")

    # 2) 촬영지 검색 (한/영 두 쿼리, 두 엔진)
    label = f"{title} {year}" if year else title
    queries = [f"{label} 촬영지", f"{label} filming locations"]
    all_results: list[WebResult] = []
    for q in queries:
        results, errs = _search_both(q, brave, tavily, max_results=8)
        all_results.extend(results)
        warnings.extend(errs)

    if not all_results:
        if warnings:
            return LocationSearchResult(query=title, status="error",
                                        error="; ".join(warnings))
        return LocationSearchResult(query=title, status="no_results")

    # 3) 본문 확보: Tavily Extract (실패해도 스니펫으로 계속)
    mentions: list[LocationMention] = []
    extracted_urls: set[str] = set()
    if tavily is not None:
        top_urls = _dedupe_urls(all_results)[:max_extract_urls]
        try:
            for doc in tavily.extract(top_urls):
                extracted_urls.add(doc.url)
                mentions.extend(extract_mentions(doc.content, doc.url))
        except SourceError as exc:
            warnings.append(f"페이지 본문 추출 실패, 검색 요약으로 대체해요: {exc}")

    # 본문을 못 얻은 결과는 스니펫에서 추출
    remaining = [r for r in all_results if r.url not in extracted_urls]
    mentions.extend(mentions_from_results(remaining))

    if not mentions:
        return LocationSearchResult(query=title, status="no_results",
                                    warnings=warnings)

    # 4) 같은 문구끼리 묶고, 독립 소스 수를 센다
    grouped: dict[str, dict] = {}
    for m in mentions:
        key = m.raw_text.lower()
        g = grouped.setdefault(key, {"mention": m, "urls": set()})
        g["urls"].add(m.source_url)

    # 5) Google Places로 확인
    locations: list[FilmLocation] = []
    unresolved: list[LocationMention] = []
    excluded_korea: list[str] = []
    if places is None:
        warnings.append("Google Places 키가 없어 장소 확인(좌표/주소)을 건너뛰었어요.")
        unresolved = [g["mention"] for g in grouped.values()]
    else:
        seen_place_ids: set[str] = set()
        for g in sorted(grouped.values(),
                        key=lambda x: -len(x["urls"]))[:max_resolve]:
            mention = g["mention"]
            try:
                found = places.text_search(mention.raw_text, page_size=1)
            except AuthError:
                raise
            except SourceError as exc:
                warnings.append(f"장소 확인 실패 ({mention.raw_text}): {exc}")
                unresolved.append(mention)
                continue
            if not found:
                unresolved.append(mention)
                continue
            place = found[0]
            if place.place_id in seen_place_ids:
                continue
            seen_place_ids.add(place.place_id)
            if not allow_korea and is_korea_place(place):
                excluded_korea.append(place.name)
                continue
            locations.append(FilmLocation(
                name=place.name,
                address=place.address,
                lat=place.lat,
                lon=place.lon,
                source="web",
                source_id=place.place_id,
                source_urls=sorted(g["urls"]),
                confidence=_confidence(len(g["urls"]), resolved=True),
                google_maps_uri=place.google_maps_uri,
            ))

    if excluded_korea:
        names = ", ".join(excluded_korea)
        warnings.append(
            f"한국에 있는 장소 {len(excluded_korea)}곳({names})은 제외했어요 — "
            "확정된 영화의 제작 국가에 한국이 없거든요. "
            "한국 영화라면 영화 선택을 다시 확인해 주세요.")

    if not locations and not unresolved:
        return LocationSearchResult(query=title, status="no_results",
                                    warnings=warnings)

    locations.sort(key=lambda loc: (-loc.confidence, loc.name))
    return LocationSearchResult(
        query=title,
        status="ok" if locations else "no_results",
        locations=locations,
        unresolved_mentions=unresolved,
        warnings=warnings,
    )


def _search_both(query: str, brave, tavily, max_results: int = 8):
    """Brave와 Tavily를 모두 부르고, 한쪽이 죽어도 다른 쪽 결과로 계속."""
    results: list[WebResult] = []
    errors: list[str] = []
    if brave is not None:
        try:
            results.extend(brave.search(query, count=max_results))
        except SourceError as exc:
            errors.append(f"Brave 검색 실패: {exc}")
    if tavily is not None:
        try:
            results.extend(tavily.search(query, max_results=max_results))
        except SourceError as exc:
            errors.append(f"Tavily 검색 실패: {exc}")
    return results, errors


def _dedupe_urls(results: list[WebResult]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for r in results:
        if r.url and r.url not in seen:
            seen.add(r.url)
            urls.append(r.url)
    return urls


def _confidence(source_count: int, resolved: bool) -> float:
    """독립 출처 수 기반 신뢰도. Places 확인 통과가 전제."""
    base = {1: 0.4, 2: 0.6}.get(source_count, 0.8 if source_count >= 3 else 0.3)
    return min(1.0, base + (0.2 if resolved else 0.0))
