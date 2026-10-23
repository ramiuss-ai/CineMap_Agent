from __future__ import annotations

from src.models import ResolvedPlace
from src.movie_search import confirm_movie
from src.pipeline import find_film_locations, is_korea_place
from src.sources.gplaces import GooglePlacesClient
from tests.conftest import FakeResponse, FakeSession
from tests.test_movie_search import FakeTMDB, make_candidate, DETAILS_KO
from tests.test_pipeline import StubPlaces, StubSearch, StubTavily, _wr


def _place(country_code=None, address="", lat=37.5, lon=127.0, name="장소"):
    return ResolvedPlace(place_id=name, name=name, address=address,
                         lat=lat, lon=lon, country_code=country_code)


# --- is_korea_place 판정 -------------------------------------------------

class TestIsKoreaPlace:
    def test_country_code_wins(self):
        assert is_korea_place(_place(country_code="KR", lat=51.5, lon=-0.1))  # 좌표가 영국이어도 코드 우선
        assert not is_korea_place(_place(country_code="GB", lat=37.5, lon=127.0))
        assert not is_korea_place(_place(country_code="US"))

    def test_address_fallback(self):
        assert is_korea_place(_place(address="대한민국 서울특별시 강남구", lat=0.0, lon=0.0))
        assert is_korea_place(_place(address="123 Gangnam-daero, Seoul, South Korea",
                                     lat=0.0, lon=0.0))
        assert not is_korea_place(_place(address="Alnwick, Northumberland, UK",
                                         lat=0.0, lon=0.0))

    def test_bbox_fallback(self):
        assert is_korea_place(_place(address="부산 동구", lat=35.115, lon=129.041))
        assert is_korea_place(_place(address="제주", lat=33.38, lon=126.53))
        assert not is_korea_place(_place(address="Alnwick", lat=55.41, lon=-1.70))
        assert not is_korea_place(_place(address="도쿄", lat=35.68, lon=139.69))


# --- 파이프라인 필터링 ------------------------------------------------------

def _hp_mapping():
    return {
        "Harry Potter 2001 촬영지": [
            _wr("해리포터 촬영지", "https://a.com/loc", "촬영지: 앨닉 성"),
        ],
        "Harry Potter 2001 filming locations": [
            _wr("Harry Potter filming locations", "https://b.com/loc",
                "filmed at Alnwick Castle"),
        ],
        "extract:https://a.com/loc": "해리포터 촬영지: 앨닉 성, 강남역 맛집에서 촬영.",
        "extract:https://b.com/loc": "Filming locations: Alnwick Castle.",
    }


def _hp_places():
    return StubPlaces({
        "앨닉 성": [ResolvedPlace(place_id="GB1", name="앨닉 성",
                                  address="Alnwick, UK", lat=55.41, lon=-1.70,
                                  country_code="GB")],
        "강남역 맛집": [ResolvedPlace(place_id="KR1", name="강남역 맛집",
                                      address="대한민국 서울특별시 강남구",
                                      lat=37.497, lon=127.027, country_code="KR")],
        "Alnwick Castle": [ResolvedPlace(place_id="GB1", name="앨닉 성",
                                         address="Alnwick, UK", lat=55.41,
                                         lon=-1.70, country_code="GB")],
    })


def test_foreign_movie_excludes_korean_places():
    result = find_film_locations(
        "Harry Potter", year=2001,
        brave=StubSearch(_hp_mapping()), tavily=StubTavily(_hp_mapping()),
        places=_hp_places(), allow_korea=False)
    assert result.status == "ok"
    ids = [loc.source_id for loc in result.locations]
    assert "GB1" in ids
    assert "KR1" not in ids  # 한국 업소는 빠진다
    assert any("제외" in w and "강남역 맛집" in w for w in result.warnings)


def test_default_keeps_korean_places():
    """allow_korea 기본값(True)이면 모듈 1 단독 사용 때 아무것도 안 뺀다."""
    result = find_film_locations(
        "Harry Potter", year=2001,
        brave=StubSearch(_hp_mapping()), tavily=StubTavily(_hp_mapping()),
        places=_hp_places())
    ids = [loc.source_id for loc in result.locations]
    assert "GB1" in ids and "KR1" in ids
    assert not any("제외" in w for w in result.warnings)


def test_excluded_places_do_not_come_back_as_unresolved():
    """제외된 장소가 '확인 실패' 목록에 다시 나오면 안 된다."""
    mapping = {
        "Harry Potter 2001 촬영지": [],
        "Harry Potter 2001 filming locations": [
            _wr("HP locations", "https://b.com/loc", "filmed at Alnwick Castle"),
        ],
        "extract:https://b.com/loc": "Filming locations: filmed at Alnwick Castle. 촬영지: 강남역 맛집.",
    }
    places = StubPlaces({
        "Alnwick Castle": [ResolvedPlace(place_id="GB1", name="앨닉 성",
                                         address="Alnwick, UK", lat=55.41,
                                         lon=-1.70, country_code="GB")],
        "강남역 맛집": [ResolvedPlace(place_id="KR1", name="강남역 맛집",
                                      address="대한민국 서울특별시 강남구",
                                      lat=37.497, lon=127.027, country_code="KR")],
    })
    result = find_film_locations(
        "Harry Potter", year=2001,
        brave=StubSearch(mapping), tavily=StubTavily(mapping),
        places=places, allow_korea=False)
    assert [loc.source_id for loc in result.locations] == ["GB1"]
    assert result.unresolved_mentions == []  # 제외된 KR1이 미확인 목록에 재등장하면 안 됨


# --- TMDB 제작 국가 수집 -------------------------------------------------------

def test_confirm_movie_collects_production_countries():
    details = dict(DETAILS_KO, production_countries=[
        {"iso_3166_1": "GB", "name": "United Kingdom"},
        {"iso_3166_1": "US", "name": "United States of America"},
    ])
    tmdb = FakeTMDB(details_by_id={(671, "ko-KR"): details})
    movie = confirm_movie(make_candidate(), tmdb)
    assert movie.production_countries == ["GB", "US"]


def test_confirm_movie_without_countries_stays_empty():
    tmdb = FakeTMDB(details_by_id={(671, "ko-KR"): dict(DETAILS_KO)})
    movie = confirm_movie(make_candidate(), tmdb)
    assert movie.production_countries == []  # 정보 없음 = 필터 안 켠다


# --- Google Places 국가 코드 파싱 ----------------------------------------------

def test_gplaces_parses_country_code(no_sleep):
    payload = {"places": [{
        "id": "ChIJabc123",
        "displayName": {"text": "부산역", "languageCode": "ko"},
        "formattedAddress": "대한민국 부산광역시 동구",
        "location": {"latitude": 35.115, "longitude": 129.041},
        "types": ["train_station"],
        "addressComponents": [
            {"longText": "부산광역시", "shortText": "부산광역시",
             "types": ["administrative_area_level_1"]},
            {"longText": "대한민국", "shortText": "KR",
             "types": ["country", "political"]},
        ],
    }]}
    session = FakeSession(post_responses=[FakeResponse(200, payload)])
    client = GooglePlacesClient("gkey", session=session, sleep_fn=no_sleep)
    places = client.text_search("부산역")
    assert places[0].country_code == "KR"
    # 필드 마스크에 addressComponents가 들어갔는지 (Pro SKU라 추가 과금 등급 없음)
    _, _, kwargs = session.calls[0]
    assert "places.addressComponents" in kwargs["headers"]["X-Goog-FieldMask"]


def test_gplaces_country_code_none_when_missing(no_sleep):
    payload = {"places": [{
        "id": "X", "displayName": {"text": "어딘가"},
        "formattedAddress": "주소",
        "location": {"latitude": 1.0, "longitude": 1.0},
    }]}
    session = FakeSession(post_responses=[FakeResponse(200, payload)])
    client = GooglePlacesClient("gkey", session=session, sleep_fn=no_sleep)
    assert client.text_search("어딘가")[0].country_code is None
