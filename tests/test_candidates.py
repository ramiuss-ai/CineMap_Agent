"""1단계 개편 후보 수집(src/candidates.py) 테스트. 실제 API는 호출하지 않는다."""
from __future__ import annotations

import pytest

from src.candidates import (CATEGORIES, FILM_CATEGORY, collect_spare,
                            candidate_to_film_location, find_candidates,
                            find_destination, find_film_candidates)
from src.errors import UpstreamError
from src.models import Candidate, ResolvedPlace, WebResult
from src.trip import build_itinerary

DEST = ResolvedPlace(place_id="D1", name="오사카", address="일본 오사카부 오사카시",
                     lat=34.6937, lon=135.5023,
                     google_maps_uri="https://maps.example/osaka",
                     country_code="JP")


def _rp(pid, name, lat, lon, types=None):
    return ResolvedPlace(place_id=pid, name=name, address=f"{name} 주소",
                         lat=lat, lon=lon, types=types or [],
                         google_maps_uri=f"https://maps.example/{pid}")


class StubPlaces:
    """GooglePlacesClient 가짜. 호출 기록을 남긴다."""

    def __init__(self, nearby_by_types=None, text_results=None):
        self.nearby_by_types = nearby_by_types or {}
        self.text_results = list(text_results or [])
        self.nearby_calls = []
        self.text_calls = []

    def nearby_search(self, lat, lon, radius_m, included_types, max_results=10,
                      **kw):
        self.nearby_calls.append((radius_m, tuple(included_types)))
        return self.nearby_by_types.get(tuple(included_types), [])

    def text_search(self, query, page_size=3, **kw):
        self.text_calls.append(query)
        if not self.text_results:
            return []
        item = self.text_results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class StubBrave:
    def __init__(self, results):
        self._results = results
        self.calls = []

    def search(self, query, count=10, **kw):
        self.calls.append(query)
        return self._results


# --- find_candidates -------------------------------------------------------


def test_candidates_one_call_per_category_and_radius_filter():
    near = _rp("N1", "근처 사원", 34.70, 135.51)
    far = _rp("F1", "먼 사원", 34.0, 134.0)  # 반경 밖
    places = StubPlaces(nearby_by_types={
        tuple(CATEGORIES["historic"]["types"]): [near, far, DEST],
    })
    found, warnings, calls = find_candidates(DEST, places, ["historic"],
                                             radius_m=10_000)
    assert calls == 1 and warnings == []
    assert [c.place.name for c in found] == ["근처 사원"]  # 반경 밖·여행지 자신 제외
    assert found[0].category == "historic"


def test_candidates_dedupe_across_categories():
    shared = _rp("S1", "겹치는 명소", 34.70, 135.51)
    places = StubPlaces(nearby_by_types={
        tuple(CATEGORIES["historic"]["types"]): [shared],
        tuple(CATEGORIES["culture"]["types"]): [shared],
    })
    found, _, _ = find_candidates(DEST, places, ["historic", "culture"],
                                  radius_m=10_000)
    assert [c.place.name for c in found] == ["겹치는 명소"]
    assert found[0].category == "historic"  # 먼저 온 카테고리가 이긴다


def test_candidates_restaurants_local_food_first():
    local = _rp("L1", "현지 식당", 34.70, 135.51,
                types=["restaurant", "japanese_restaurant"])
    fast = _rp("Q1", "패스트푸드", 34.69, 135.50,
               types=["restaurant", "fast_food_restaurant"])
    plain = _rp("P1", "그냥 식당", 34.695, 135.505, types=["restaurant"])
    places = StubPlaces(nearby_by_types={
        tuple(CATEGORIES["restaurants"]["types"]): [fast, plain, local],
    })
    found, _, _ = find_candidates(DEST, places, ["restaurants"],
                                  radius_m=10_000)
    assert [c.place.name for c in found] == ["현지 식당", "그냥 식당", "패스트푸드"]


def test_candidates_per_category_limit_and_failure_warning():
    many = [_rp(f"H{i}", f"명소{i}", 34.70, 135.50 + i * 0.001)
            for i in range(8)]
    places = StubPlaces(nearby_by_types={
        tuple(CATEGORIES["historic"]["types"]): many,
    })
    found, _, _ = find_candidates(DEST, places, ["historic"], radius_m=10_000)
    assert len(found) == CATEGORIES["historic"]["limit"]

    broken = StubPlaces(nearby_by_types={})
    broken.nearby_search = lambda *a, **k: (_ for _ in ()).throw(
        UpstreamError("다운"))
    found, warnings, calls = find_candidates(DEST, broken, ["historic"],
                                             radius_m=10_000)
    assert found == [] and calls == 1
    assert any("역사 명소 검색 실패" in w for w in warnings)


# --- find_destination ------------------------------------------------------


def test_find_destination_single_text_search():
    places = StubPlaces(text_results=[[DEST]])
    assert find_destination("오사카", places) == [DEST]
    assert places.text_calls == ["오사카"]


# --- find_film_candidates --------------------------------------------------


def _film_web_results():
    return [
        WebResult(title="오사카 영화 촬영지 총정리",
                  url="https://a.example/osaka-film",
                  description="촬영지: 쓰텐카쿠, 도톤보리", engine="brave"),
        WebResult(title="Osaka filming locations",
                  url="https://b.example/osaka-locations",
                  description="Scenes were filmed at Osaka Castle Park",
                  engine="brave"),
    ]


def test_film_candidates_grounded_and_capped():
    near = _rp("F1", "쓰텐카쿠", 34.6525, 135.5063)
    far = _rp("F2", "도쿄타워", 35.6586, 139.7454)  # 오사카에서 수백 km
    places = StubPlaces(text_results=[[near], [far], [near]])
    brave = StubBrave(_film_web_results())
    found, warnings, p_calls, w_calls = find_film_candidates(
        DEST, brave, None, places, radius_m=10_000)
    assert w_calls == 2                     # Brave 쿼리 2개 (Tavily 없음)
    assert [c.place.name for c in found] == ["쓰텐카쿠"]  # 먼 곳 제외
    c = found[0]
    assert c.film and c.category == FILM_CATEGORY
    assert c.source_urls                    # 근거 링크가 함께 온다
    assert c.confidence is not None and c.confidence > 0


def test_film_candidates_resolve_call_cap():
    names = ", ".join(f"장소{i}" for i in range(12))
    results = [WebResult(title="t", url="https://a.example/x",
                         description=f"촬영지: {names}", engine="brave")]
    places = StubPlaces(text_results=[[_rp(f"F{i}", f"장소{i}", 34.70, 135.50)]
                                      for i in range(12)])
    brave = StubBrave(results)
    find_film_candidates(DEST, brave, None, places, radius_m=10_000)
    assert len(places.text_calls) <= 6      # max_resolve 상한


def test_film_candidates_no_results_message():
    brave = StubBrave([])
    found, warnings, _, _ = find_film_candidates(DEST, brave, None,
                                                 StubPlaces(), 10_000)
    assert found == []
    assert any("촬영지" in w for w in warnings)


# --- collect_spare / 변환 ---------------------------------------------------


def _cand(pid, name, cat):
    return Candidate(category=cat, place=_rp(pid, name, 34.70, 135.51),
                     distance_m=1000.0)


def test_collect_spare_fills_free_days_and_skips_restaurants_and_picks():
    loc = candidate_to_film_location(_cand("A1", "오사카성", "historic"))
    days = build_itinerary([loc], 3)        # 1일차만 배정, 2~3일차 빈 날
    candidates = [
        _cand("A1", "오사카성", "historic"),   # 이미 고른 후보 → 제외
        _cand("B1", "미노오 공원", "trekking"),
        _cand("C1", "국립 미술관", "culture"),
        _cand("R1", "이치란", "restaurants"),  # 맛집은 채우지 않는다
        _cand("D1", "신세카이", "film"),
    ]
    extras = collect_spare(days, candidates)
    placed = [c.place.name for lst in extras.values() for c in lst]
    assert placed == ["미노오 공원", "국립 미술관", "신세카이"]
    assert extras[2] and extras[3]
    assert "오사카성" not in placed and "이치란" not in placed


def test_collect_spare_empty_when_no_free_days():
    loc = candidate_to_film_location(_cand("A1", "오사카성", "historic"))
    days = build_itinerary([loc], 1)
    assert collect_spare(days, [_cand("B1", "공원", "trekking")]) == {}


def test_candidate_to_film_location_keeps_evidence():
    c = Candidate(category=FILM_CATEGORY,
                  place=_rp("F1", "쓰텐카쿠", 34.6525, 135.5063),
                  distance_m=800.0, film=True,
                  source_urls=["https://example.com/film"], confidence=0.8)
    loc = candidate_to_film_location(c)
    assert loc.source == "film"
    assert loc.source_urls == ["https://example.com/film"]
    assert loc.confidence == 0.8
    assert loc.google_maps_uri == "https://maps.example/F1"


def test_categories_use_only_table_a_types():
    # 2026-10-28 공식 타입 표 A 확인분. 잘못된 타입은 API 400 오류라 테스트로 고정.
    known = {
        "restaurant", "hiking_area", "national_park", "park",
        "historical_place", "monument", "museum", "art_gallery",
        "shopping_mall", "department_store", "market",
        "amusement_park", "aquarium", "zoo", "adventure_sports_center",
        "water_park", "botanical_garden", "tourist_attraction",
    }
    for spec in CATEGORIES.values():
        assert set(spec["types"]) <= known