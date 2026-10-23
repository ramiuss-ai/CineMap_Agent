from __future__ import annotations

import pytest

from src.errors import RateLimitError, SourceError
from src.models import FilmLocation, ResolvedPlace
from src.nearby import (CATEGORIES, find_nearby, haversine_m,
                        restaurant_score)
from src.sources.gplaces import GooglePlacesClient
from tests.conftest import FakeResponse, FakeSession


def _rp(place_id, name, lat, lon, types=None, country_code=None):
    return ResolvedPlace(place_id=place_id, name=name, address=f"{name} 주소",
                         lat=lat, lon=lon, types=types or [],
                         country_code=country_code,
                         google_maps_uri=f"https://maps.google.com/?cid={place_id}")


def _loc():
    return FilmLocation(name="부산역", address="부산 동구", lat=35.115, lon=129.041,
                        source_id="LOC", confidence=0.8)


class StubNearbyPlaces:
    """nearby_search 쿼리를 (카테고리 타입 첫 번째) 키로 심어 두는 스텁."""
    def __init__(self, mapping=None, fail_types=None):
        self.mapping = mapping or {}
        self.fail_types = set(fail_types or [])
        self.calls = []

    def nearby_search(self, lat, lon, radius_m, included_types, max_results=20,
                      **kwargs):
        self.calls.append((lat, lon, radius_m, tuple(included_types)))
        key = included_types[0]
        if key in self.fail_types:
            raise RateLimitError("한도")
        return list(self.mapping.get(key, []))


# --- haversine ---------------------------------------------------------------

def test_haversine_seoul_busan():
    d = haversine_m(37.55, 126.99, 35.11, 129.04)
    assert 300_000 < d < 360_000  # 서울-부산 대략 325km


# --- 식당 순위 휴리스틱 ---------------------------------------------------------

def test_restaurant_score_prefers_local_cuisine():
    kr_local = _rp("1", "부산밀면", 35.1, 129.0,
                   types=["korean_restaurant", "restaurant"], country_code="KR")
    generic = _rp("2", "그냥식당", 35.1, 129.0,
                  types=["restaurant"], country_code="KR")
    fast = _rp("3", "버거집", 35.1, 129.0,
               types=["fast_food_restaurant", "restaurant"], country_code="KR")
    assert restaurant_score(kr_local) > restaurant_score(generic)
    assert restaurant_score(generic) > restaurant_score(fast)


# --- find_nearby -----------------------------------------------------------------

def test_groups_per_location_and_category():
    places = StubNearbyPlaces({
        "restaurant": [
            _rp("R1", "밀면집", 35.116, 129.042,
                types=["korean_restaurant", "restaurant"], country_code="KR"),
            _rp("R2", "패스트푸드", 35.1155, 129.0415,
                types=["fast_food_restaurant", "restaurant"], country_code="KR"),
            _rp("R3", "횟집", 35.118, 129.045,
                types=["seafood_restaurant", "restaurant"], country_code="KR"),
            _rp("R4", "먼식당", 35.500, 129.500,  # 반경 10km 밖 (~55km)
                types=["restaurant"], country_code="KR"),
        ],
        "hiking_area": [_rp("T1", "금정산", 35.20, 129.05,
                            types=["hiking_area", "park"], country_code="KR")],
        "historical_place": [_rp("H1", "범어사", 35.17, 129.05,
                                 types=["historical_place", "tourist_attraction"],
                                 country_code="KR")],
    })
    groups = find_nearby([_loc()], places, radius_m=10_000, per_category=3)
    assert len(groups) == 1
    g = groups[0]
    # 카테고리 3개 × 촬영지 1곳 = 호출 3번, 반경 10km 전달
    assert len(places.calls) == 3
    assert all(c[2] == 10_000 for c in places.calls)
    # 식당: 반경 밖 R4 제외, 현지 식사 R1이 맨 앞
    names = [n.place.name for n in g.restaurants]
    assert names[0] == "밀면집"
    assert "먼식당" not in names
    # 트래킹/역사도 채워짐
    assert [n.place.name for n in g.trekking] == ["금정산"]
    assert [n.place.name for n in g.historic] == ["범어사"]
    # 거리가 기록됨
    assert all(n.distance_m > 0 for n in g.restaurants)


def test_per_category_limit():
    many = [_rp(f"R{i}", f"식당{i}", 35.115 + i * 0.0001, 129.041,
                types=["restaurant"], country_code="KR") for i in range(10)]
    groups = find_nearby([_loc()], StubNearbyPlaces({"restaurant": many}),
                         radius_m=10_000, per_category=3)
    assert len(groups[0].restaurants) == 3


def test_location_itself_excluded():
    places = StubNearbyPlaces({
        "restaurant": [_rp("LOC", "부산역", 35.115, 129.041,
                           types=["restaurant"], country_code="KR")],
    })
    groups = find_nearby([_loc()], places)
    assert groups[0].restaurants == []


def test_category_failure_warns_but_others_survive():
    places = StubNearbyPlaces(
        {"hiking_area": [_rp("T1", "금정산", 35.20, 129.05, country_code="KR")]},
        fail_types={"restaurant"})
    groups = find_nearby([_loc()], places)
    assert groups[0].restaurants == []
    assert any("맛집 검색 실패" in w for w in groups[0].warnings)
    assert [n.place.name for n in groups[0].trekking] == ["금정산"]


def test_max_locations_cap():
    locs = [_loc(), _loc(), _loc()]
    places = StubNearbyPlaces({})
    groups = find_nearby(locs, places, max_locations=2)
    assert len(groups) == 2


def test_category_types_match_places_table_a():
    """카테고리 타입이 Places 타입 표에 있는 값인지(오타 방지)."""
    assert CATEGORIES["restaurants"] == ["restaurant"]
    assert "hiking_area" in CATEGORIES["trekking"]
    assert "historical_place" in CATEGORIES["historic"]


# --- gplaces.nearby_search 요청 형태 --------------------------------------------

NEARBY_PAYLOAD = {"places": [{
    "id": "ChIJr1",
    "displayName": {"text": "밀면집", "languageCode": "ko"},
    "formattedAddress": "대한민국 부산광역시",
    "location": {"latitude": 35.116, "longitude": 129.042},
    "types": ["korean_restaurant", "restaurant"],
    "addressComponents": [
        {"longText": "대한민국", "shortText": "KR", "types": ["country", "political"]},
    ],
    "googleMapsUri": "https://maps.google.com/?cid=r1",
}]}


def test_nearby_search_request_shape(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(200, NEARBY_PAYLOAD)])
    client = GooglePlacesClient("gkey", session=session, sleep_fn=no_sleep)
    out = client.nearby_search(35.115, 129.041, radius_m=10_000,
                               included_types=["restaurant"], max_results=10)
    assert out[0].name == "밀면집"
    assert out[0].country_code == "KR"
    method, url, kwargs = session.calls[0]
    assert url == "https://places.googleapis.com/v1/places:searchNearby"
    payload = kwargs["json"]
    assert payload["includedTypes"] == ["restaurant"]
    assert payload["maxResultCount"] == 10
    circle = payload["locationRestriction"]["circle"]
    assert circle["radius"] == 10_000.0
    assert circle["center"] == {"latitude": 35.115, "longitude": 129.041}


def test_nearby_search_rate_limit(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(429), FakeResponse(429)])
    client = GooglePlacesClient("gkey", max_retries=1, session=session,
                                sleep_fn=no_sleep)
    with pytest.raises(RateLimitError):
        client.nearby_search(35.1, 129.0, radius_m=1000,
                             included_types=["restaurant"])
