"""1단계 개편: 여행지 중심 명소 후보 수집 (2026-10-28 사용자 합의, WhatsApp).

- 영화 먼저가 아니라 여행지(도시/지역)를 먼저 고른다.
- 영화 촬영지는 별도 출발점이 아니라, 고른 여행지의 명소를 찾는 과정에서
  웹 검색으로 발견되면 근거 링크와 함께 방문 후보에 넣는다.
- 해외 여행 먼저 (국내는 카카오 키가 필요해 나중에).
- 관심사: 기존 맛집·자연/트래킹·역사 + 박물관/미술관·쇼핑·액티비티.

비용 원칙 (개편안 2026-10-28):
- 검색은 버튼을 누를 때만.
- 카테고리당 Places Nearby Search 1회 (선택한 카테고리 수만큼, 최대 6회).
- 영화 촬영지 찾기를 켜면 웹 검색 최대 4회(Brave+Tavily × 쿼리 2개),
  본문 추출 최대 4회(URL), 장소 확인 최대 max_resolve회가 더 나간다.
- Places 타입은 Nearby Search에 쓸 수 있는 Table A 타입만 쓴다
  (2026-10-28 developers.google.com/maps/documentation/places/web-service/place-types 확인).
- 호출 수는 결과와 함께 화면에 보여준다.
"""
from __future__ import annotations

from .errors import SourceError
from .extract_names import extract_mentions, mentions_from_results
from .models import (Candidate, FilmLocation, ResolvedPlace, WebResult)
from .nearby import haversine_m, restaurant_score
from .trip import MAX_STOPS_PER_DAY, DayPlan

# 관심사 카테고리. types는 Places (New) Nearby Search includedTypes (Table A).
CATEGORIES: dict[str, dict] = {
    "restaurants": {"label": "맛집", "types": ["restaurant"], "limit": 3},
    "trekking": {"label": "자연·트래킹",
                 "types": ["hiking_area", "national_park", "park"], "limit": 5},
    "historic": {"label": "역사 명소",
                 "types": ["historical_place", "monument"], "limit": 5},
    "culture": {"label": "박물관·미술관",
                "types": ["museum", "art_gallery"], "limit": 5},
    "shopping": {"label": "쇼핑",
                 "types": ["shopping_mall", "department_store", "market"],
                 "limit": 5},
    "activities": {"label": "액티비티",
                   "types": ["amusement_park", "aquarium", "zoo",
                             "adventure_sports_center", "water_park",
                             "botanical_garden", "tourist_attraction"],
                   "limit": 5},
}
FILM_CATEGORY = "film"
FILM_LABEL = "영화 촬영지"

# 영화 촬영지는 도시 바깥(교외 로케이션)에 있을 수 있어 후보 검색 반경보다
# 넓게 잡되, 다른 도시·다른 나라 장소가 섞이지 않게 상한을 둔다.
FILM_RADIUS_MIN_M = 30_000.0
FILM_RADIUS_MAX_M = 60_000.0
FILM_RADIUS_FACTOR = 3.0
# 확인 비용 상한
FILM_MAX_RESOLVE = 6        # Places 장소 확인 최대 횟수
FILM_MAX_EXTRACT_URLS = 4   # Tavily 본문 추출 URL 수


def find_destination(query: str, places,
                     page_size: int = 5) -> list[ResolvedPlace]:
    """여행지 이름(도시/지역)을 Places Text Search로 확인한다. 1회 호출."""
    return places.text_search(query, page_size=page_size)


def find_candidates(destination: ResolvedPlace, places,
                    categories: list[str],
                    radius_m: float = 10_000.0
                    ) -> tuple[list[Candidate], list[str], int]:
    """관심사 카테고리별 명소 후보를 모은다.

    반환: (후보 목록, 경고 목록, Places 호출 수).
    - 카테고리당 Nearby Search 1회 (실패한 호출도 과금될 수 있어 호출 수에 포함).
    - 여행지 자신과 카테고리 간 중복 place_id는 제외.
    - 맛집은 '현지 식사' 휴리스틱(restaurant_score)으로, 나머지는 거리순.
    """
    out: list[Candidate] = []
    warnings: list[str] = []
    calls = 0
    seen: set[str] = {destination.place_id}
    for cat in categories:
        spec = CATEGORIES[cat]
        calls += 1
        try:
            found = places.nearby_search(
                destination.lat, destination.lon, radius_m=radius_m,
                included_types=spec["types"], max_results=20)
        except SourceError as exc:
            warnings.append(f"{spec['label']} 검색 실패: {exc}")
            continue
        items: list[Candidate] = []
        for pl in found:
            if pl.place_id in seen:
                continue
            dist = haversine_m(destination.lat, destination.lon, pl.lat, pl.lon)
            if dist > radius_m * 1.05:  # 원 경계 근처 오차 여유 5%
                continue
            seen.add(pl.place_id)
            items.append(Candidate(category=cat, place=pl, distance_m=dist))
        if cat == "restaurants":
            items.sort(key=lambda c: (-restaurant_score(c.place), c.distance_m))
        else:
            items.sort(key=lambda c: c.distance_m)
        out.extend(items[: spec["limit"]])
    return out, warnings, calls


# 숙소 검색 (2026-10-30 추가, WhatsApp 요청). 관심사 카테고리가 아니라
# 여행 계획의 '숙소 고르기'에서 따로 부른다. Places Nearby Search 1회.
LODGING_TYPES = ["lodging"]
LODGING_LIMIT = 8


def find_lodging(destination: ResolvedPlace, places,
                 radius_m: float = 10_000.0, limit: int = LODGING_LIMIT
                 ) -> tuple[list[ResolvedPlace], list[str], int]:
    """여행지 주변 숙소 후보를 찾는다.

    반환: (숙소 목록, 경고 목록, Places 호출 수).
    - Nearby Search(includedTypes=["lodging"]) 1회. 실패해도 과금될 수 있어
      호출 수에 포함한다.
    - 후보에 이미 뜬 장소와 중복 place_id는 제외하지 않는다 (숙소는 별도
      목록이라 겹쳐도 문제없다) — 다만 여행지 자신은 뺀다.
    - 평점·가격 데이터는 Pro SKU 범위에 없어서 거리순으로만 보여준다.
      순위가 '좋은 숙소'를 뜻하지 않는다는 점을 화면에도 밝힌다.
    """
    warnings: list[str] = []
    calls = 1
    try:
        found = places.nearby_search(
            destination.lat, destination.lon, radius_m=radius_m,
            included_types=LODGING_TYPES, max_results=20)
    except SourceError as exc:
        return [], [f"숙소 검색 실패: {exc}"], calls
    out: list[ResolvedPlace] = []
    for pl in found:
        if pl.place_id == destination.place_id:
            continue
        dist = haversine_m(destination.lat, destination.lon, pl.lat, pl.lon)
        if dist > radius_m * 1.05:  # 원 경계 근처 오차 여유 5%
            continue
        out.append((dist, pl))
    out.sort(key=lambda t: t[0])
    if not out:
        warnings.append("검색 반경 안에서 숙소를 찾지 못했어요. "
                        "반경을 넓혀 다시 찾아 보세요.")
    return [pl for _d, pl in out[:limit]], warnings, calls


def find_film_candidates(destination: ResolvedPlace, brave, tavily, places,
                         radius_m: float = 10_000.0,
                         max_resolve: int = FILM_MAX_RESOLVE,
                         max_extract_urls: int = FILM_MAX_EXTRACT_URLS
                         ) -> tuple[list[Candidate], list[str], int, int]:
    """웹 검색으로 '이 여행지의 영화 촬영지'를 찾아 후보로 만든다.

    모듈 1과 같은 규칙 기반 추출 + Places 확인이지만, 출발점이 영화 제목이
    아니라 여행지다. 확인된 장소가 여행지 주변(반경의 FILM_RADIUS_FACTOR배,
    최소/최대 상한)을 벗어나면 다른 지역 로케이션으로 보고 버린다.

    반환: (후보 목록, 경고 목록, Places 호출 수, 웹(Brave/Tavily) 호출 수).
    """
    label = destination.name
    queries = [f"{label} 영화 촬영지", f"{label} filming locations"]
    results: list[WebResult] = []
    warnings: list[str] = []
    places_calls = 0
    web_calls = 0
    for q in queries:
        if brave is not None:
            web_calls += 1
            try:
                results.extend(brave.search(q, count=8))
            except SourceError as exc:
                warnings.append(f"Brave 검색 실패: {exc}")
        if tavily is not None:
            web_calls += 1
            try:
                results.extend(tavily.search(q, max_results=8))
            except SourceError as exc:
                warnings.append(f"Tavily 검색 실패: {exc}")
    if not results:
        if warnings:
            return [], warnings, places_calls, web_calls
        return [], ["이 지역의 촬영지 언급을 찾지 못했어요."], places_calls, web_calls

    # 본문 확보: Tavily Extract (실패해도 스니펫으로 계속)
    mentions = []
    extracted_urls: set[str] = set()
    if tavily is not None:
        top_urls = _dedupe_urls(results)[:max_extract_urls]
        web_calls += 1
        try:
            for doc in tavily.extract(top_urls):
                extracted_urls.add(doc.url)
                mentions.extend(extract_mentions(doc.content, doc.url))
        except SourceError as exc:
            warnings.append(f"페이지 본문 추출 실패, 검색 요약으로 대체해요: {exc}")
    remaining = [r for r in results if r.url not in extracted_urls]
    mentions.extend(mentions_from_results(remaining))
    if not mentions:
        return [], warnings + ["촬영지 언급을 뽑지 못했어요."], places_calls, web_calls

    # 같은 문구끼리 묶고 독립 출처 수를 센다
    grouped: dict[str, dict] = {}
    for m in mentions:
        key = m.raw_text.lower()
        g = grouped.setdefault(key, {"mention": m, "urls": set()})
        g["urls"].add(m.source_url)

    area_radius = min(max(radius_m * FILM_RADIUS_FACTOR, FILM_RADIUS_MIN_M),
                      FILM_RADIUS_MAX_M)
    out: list[Candidate] = []
    seen: set[str] = set()
    for g in sorted(grouped.values(),
                    key=lambda x: -len(x["urls"]))[:max_resolve]:
        mention = g["mention"]
        places_calls += 1
        try:
            # 여행지 이름을 붙여 다른 지역의 같은 이름 장소로 튀는 걸 줄인다
            found = places.text_search(f"{mention.raw_text} {label}", page_size=1)
        except SourceError as exc:
            warnings.append(f"장소 확인 실패 ({mention.raw_text}): {exc}")
            continue
        if not found:
            continue
        place = found[0]
        if place.place_id in seen:
            continue
        dist = haversine_m(destination.lat, destination.lon, place.lat, place.lon)
        if dist > area_radius:
            continue  # 다른 지역 로케이션
        seen.add(place.place_id)
        out.append(Candidate(category=FILM_CATEGORY, place=place,
                             distance_m=dist, film=True,
                             source_urls=sorted(g["urls"]),
                             confidence=_confidence(len(g["urls"]))))
    return out, warnings, places_calls, web_calls


# 남는 날에 채울 카테고리. 맛집은 식사 옵션이라 하루 일정 항목으로 채우지 않는다
# (기존 모듈 4의 ATTRACTION_CATEGORIES 규칙과 같은 생각).
SPARE_CATEGORIES = ("trekking", "historic", "culture", "shopping",
                    "activities", FILM_CATEGORY)


def collect_spare(days: list[DayPlan], candidates: list[Candidate],
                  per_day: int = MAX_STOPS_PER_DAY
                  ) -> dict[int, list[Candidate]]:
    """초안의 빈 날에, 일정에 고르지 않은 후보를 중복 없이 채운다.

    trip.collect_attractions(모듈 4 남는 날 채우기)와 같은 규칙을
    여행지 후보(Candidate)에 적용한다. 새 API 호출은 없다.
    반환: {DayPlan.day: [Candidate, ...]} — 후보가 모자라면 빈 목록이 남는다.
    """
    free = [p.day for p in days if not p.stops]
    out: dict[int, list[Candidate]] = {d: [] for d in free}
    if not free or not candidates:
        return out
    taken = {loc.name.strip().lower() for p in days for loc in p.stops}
    eligible: list[Candidate] = []
    for c in candidates:
        if c.category not in SPARE_CATEGORIES:
            continue
        key = c.place.name.strip().lower()
        if key in taken:
            continue
        taken.add(key)
        eligible.append(c)
    # 빈 날들에 고르게 나눈다 (한 날에 몰아넣지 않게). 날마다 per_day 상한.
    n, k = len(eligible), len(free)
    pos = 0
    for idx, d in enumerate(free):
        quota = min(n // k + (1 if idx < n % k else 0), per_day)
        out[d] = eligible[pos:pos + quota]
        pos += len(out[d])
    return out


def candidate_to_film_location(c: Candidate) -> FilmLocation:
    """일정 초안(모듈 4)은 FilmLocation을 쓰므로 후보를 그 형태로 바꾼다."""
    return FilmLocation(
        name=c.place.name,
        address=c.place.address,
        lat=c.place.lat,
        lon=c.place.lon,
        source="film" if c.film else "places",
        source_id=c.place.place_id,
        source_urls=list(c.source_urls),
        confidence=c.confidence if c.confidence is not None else 0.0,
        google_maps_uri=c.place.google_maps_uri,
    )


def _dedupe_urls(results: list[WebResult]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for r in results:
        if r.url and r.url not in seen:
            seen.add(r.url)
            urls.append(r.url)
    return urls


def _confidence(source_count: int) -> float:
    """독립 출처 수 기반 신뢰도 (모듈 1과 같은 기준, Places 확인 통과가 전제)."""
    base = {1: 0.4, 2: 0.6}.get(source_count, 0.8 if source_count >= 3 else 0.3)
    return min(1.0, base + 0.2)