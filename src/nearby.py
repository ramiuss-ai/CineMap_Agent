from __future__ import annotations

import math
import re

from .errors import SourceError
from .models import FilmLocation, NearbyGroup, NearbyPlace, ResolvedPlace

# Nearby Search의 includedTypes (Places 타입 표 A, 2026-10-20 문서 확인)
CATEGORIES: dict[str, list[str]] = {
    "restaurants": ["restaurant"],
    "trekking": ["hiking_area", "national_park", "park"],
    "historic": ["historical_place", "monument", "museum"],
}
CATEGORY_LABELS = {"restaurants": "맛집", "trekking": "트래킹", "historic": "역사 명소"}

# 국가 코드 → 그 나라 '현지 식사'에 해당하는 Places 타입.
# Places에 실제 있는 타입만 매핑한다 (예: british_restaurant 타입은 없음).
LOCAL_CUISINE_TYPES = {
    "KR": "korean_restaurant", "JP": "japanese_restaurant",
    "CN": "chinese_restaurant", "IT": "italian_restaurant",
    "FR": "french_restaurant", "TH": "thai_restaurant",
    "VN": "vietnamese_restaurant", "IN": "indian_restaurant",
    "MX": "mexican_restaurant", "US": "american_restaurant",
    "ES": "spanish_restaurant", "TR": "turkish_restaurant",
    "GR": "greek_restaurant", "DE": "german_restaurant",
    "BR": "brazilian_restaurant", "ID": "indonesian_restaurant",
}
_CUISINE_RE = re.compile(r"^[a-z]+_restaurant$")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 사이의 대략적인 직선거리(미터)."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def restaurant_score(place: ResolvedPlace) -> int:
    """'현지 식사' 선호 휴리스틱. 높을수록 먼저 보여준다.

    +2: 그 나라 현지 요리 타입 (예: KR이면 korean_restaurant)
    +1: 무언가 구체적인 요리 타입이 붙은 식당 (seafood_restaurant 등)
    -2: 패스트푸드
    평점/리뷰는 Enterprise SKU라 비용상 안 쓴다. 어디까지나 순위 힌트다.
    """
    types = place.types or []
    score = 0
    local = LOCAL_CUISINE_TYPES.get((place.country_code or "").upper())
    if local and local in types:
        score += 2
    if any(_CUISINE_RE.match(t) for t in types):
        score += 1
    if "fast_food_restaurant" in types:
        score -= 2
    return score


def find_nearby(locations: list[FilmLocation], places,
                radius_m: float = 10_000.0,
                per_category: int = 3,
                max_locations: int = 10) -> list[NearbyGroup]:
    """각 촬영지의 주변 추천을 모은다. places는 GooglePlacesClient (또는 스텁)."""
    groups: list[NearbyGroup] = []
    for loc in locations[:max_locations]:
        group = NearbyGroup(location=loc)
        for category, types in CATEGORIES.items():
            label = CATEGORY_LABELS[category]
            try:
                found = places.nearby_search(
                    loc.lat, loc.lon, radius_m=radius_m,
                    included_types=types, max_results=20,
                )
            except SourceError as exc:
                group.warnings.append(f"{loc.name} 주변 {label} 검색 실패: {exc}")
                continue
            candidates: list[NearbyPlace] = []
            seen: set[str] = set()
            for pl in found:
                if pl.place_id == loc.source_id or pl.place_id in seen:
                    continue  # 촬영지 자신이나 중복은 제외
                dist = haversine_m(loc.lat, loc.lon, pl.lat, pl.lon)
                if dist > radius_m * 1.05:  # 원 경계 근처 오차 여유 5%
                    continue
                seen.add(pl.place_id)
                candidates.append(NearbyPlace(category=category,
                                              distance_m=dist, place=pl))
            if category == "restaurants":
                candidates.sort(key=lambda n: (-restaurant_score(n.place),
                                               n.distance_m))
            else:
                candidates.sort(key=lambda n: n.distance_m)
            setattr(group, category, candidates[:per_category])
        groups.append(group)
    return groups
