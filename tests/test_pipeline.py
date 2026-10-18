import pytest

from src.errors import AuthError, RateLimitError
from src.models import ResolvedPlace, WebResult
from src.pipeline import _confidence, find_film_locations, find_movie_candidates
from src.sources.tavily_client import ExtractedDoc


class StubSearch:
    """Brave/Tavily 공용 스텁: 쿼리별 결과를 미리 심어 둔다."""
    def __init__(self, mapping, engine="stub"):
        self.mapping = mapping
        self.engine = engine
        self.queries = []

    def search(self, query, **kwargs):
        self.queries.append(query)
        return list(self.mapping.get(query, []))


class StubTavily(StubSearch):
    def extract(self, urls, **kwargs):
        self.extracted = urls
        return [ExtractedDoc(url=u, content=self.mapping.get(f"extract:{u}", ""))
                for u in urls]


class StubPlaces:
    def __init__(self, mapping=None, fail_with=None):
        self.mapping = mapping or {}
        self.fail_with = fail_with
        self.queries = []

    def text_search(self, query, **kwargs):
        self.queries.append(query)
        if self.fail_with:
            raise self.fail_with
        return list(self.mapping.get(query, []))


def _wr(title, url, desc=""):
    return WebResult(title=title, url=url, description=desc, engine="stub")


# --- 모호성 -------------------------------------------------------------

def test_ambiguous_title_returns_candidates_without_places_calls():
    mapping = {
        "부산행 영화": [
            _wr("부산행 (2016) - 위키백과", "https://ko.wikipedia.org/wiki/부산행"),
            _wr("부산행 (2030) 영화 리뷰", "https://example.com/busan2030"),
        ]
    }
    brave, tavily = StubSearch(mapping), StubTavily(mapping)
    places = StubPlaces()
    result = find_film_locations("부산행", brave=brave, tavily=tavily, places=places)
    assert result.status == "ambiguous"
    years = {c.year for c in result.movie_candidates}
    assert years == {2016, 2030}
    assert places.queries == []  # 모호하면 Places 크레딧을 쓰지 않는다


def test_find_movie_candidates_filters_unrelated_titles():
    mapping = {
        "기생충 영화": [
            _wr("기생충 (2019) - 위키백과", "https://ko.wikipedia.org/wiki/기생충"),
            _wr("바퀴벌레 (1999)", "https://example.com/other"),  # 제목 불일치 → 제외
        ]
    }
    candidates = find_movie_candidates("기생충", StubSearch(mapping), StubTavily(mapping))
    assert [c.title for c in candidates] == ["기생충"]
    assert candidates[0].year == 2019


# --- 정상 경로 -------------------------------------------------------------

def _full_mapping():
    return {
        "부산행 2016 촬영지": [
            _wr("부산행 촬영지", "https://a.com/loc", "촬영지: 부산역"),
        ],
        "부산행 2016 filming locations": [
            _wr("Train to Busan filming locations", "https://b.com/loc",
                "filmed at Busan Station"),
        ],
        "extract:https://a.com/loc": "부산행 촬영지: 부산역, 동대구역에서 촬영했다.",
        "extract:https://b.com/loc": "Filming locations: filmed at Busan Station.",
    }


def test_happy_path_resolves_and_scores():
    brave = StubSearch(_full_mapping())
    tavily = StubTavily(_full_mapping())
    places = StubPlaces({
        "부산역": [ResolvedPlace(place_id="P1", name="부산역",
                                 address="부산 동구", lat=35.115, lon=129.041,
                                 google_maps_uri="https://maps.google.com/?cid=1")],
        "동대구역": [ResolvedPlace(place_id="P2", name="동대구역",
                                   address="대구 동구", lat=35.879, lon=128.628)],
        "Busan Station": [ResolvedPlace(place_id="P1", name="부산역",
                                        address="부산 동구", lat=35.115, lon=129.041)],
    })
    result = find_film_locations("부산행", year=2016, brave=brave, tavily=tavily,
                                 places=places)
    assert result.status == "ok"
    # P1 중복 제거(부산역/Busan Station) → 2곳
    ids = [loc.source_id for loc in result.locations]
    assert ids.count("P1") == 1
    assert "P2" in ids
    assert all(0 < loc.confidence <= 1.0 for loc in result.locations)
    assert all(loc.source_urls for loc in result.locations)


def test_places_unresolved_goes_to_unresolved_list():
    brave = StubSearch(_full_mapping())
    tavily = StubTavily(_full_mapping())
    places = StubPlaces({})  # 아무것도 확인 못 함
    result = find_film_locations("부산행", year=2016, brave=brave, tavily=tavily,
                                 places=places)
    assert result.status == "no_results"
    assert len(result.unresolved_mentions) >= 1


def test_places_failure_keeps_partial_result():
    brave = StubSearch(_full_mapping())
    tavily = StubTavily(_full_mapping())
    places = StubPlaces(fail_with=RateLimitError("한도 초과"))
    result = find_film_locations("부산행", year=2016, brave=brave, tavily=tavily,
                                 places=places)
    assert result.warnings  # 부분 실패 안내가 남는다
    assert result.unresolved_mentions


# --- 폴백과 오류 -------------------------------------------------------------

def test_tavily_extract_failure_falls_back_to_snippets():
    mapping = {
        "부산행 2016 촬영지": [_wr("촬영지", "https://a.com", "부산역에서 촬영했다")],
        "부산행 2016 filming locations": [],
    }

    class FailingTavily(StubTavily):
        def extract(self, urls, **kwargs):
            raise RateLimitError("크레딧 소진")

    places = StubPlaces({
        "부산역": [ResolvedPlace(place_id="P1", name="부산역", address="부산 동구",
                                 lat=35.115, lon=129.041)],
    })
    result = find_film_locations("부산행", year=2016,
                                 brave=StubSearch(mapping),
                                 tavily=FailingTavily(mapping), places=places)
    assert any("본문 추출 실패" in w for w in result.warnings)
    assert result.status == "ok"  # 스니펫 폴백으로 찾음
    assert result.locations[0].name == "부산역"


def test_one_engine_down_still_works():
    class DeadBrave:
        def search(self, query, **kwargs):
            raise RateLimitError("Brave 한도")

    result = find_film_locations("부산행", year=2016,
                                 brave=DeadBrave(), tavily=StubTavily(_full_mapping()),
                                 places=StubPlaces({}))
    assert any("Brave 검색 실패" in w for w in result.warnings)
    assert result.status in ("ok", "no_results")


def test_both_engines_down_is_error():
    class Dead:
        def search(self, query, **kwargs):
            raise RateLimitError("죽음")

    result = find_film_locations("부산행", year=2016, brave=Dead(), tavily=Dead(),
                                 places=StubPlaces())
    assert result.status == "error"
    assert result.error


def test_no_search_results():
    result = find_film_locations("세상에없는영화", year=2099,
                                 brave=StubSearch({}), tavily=StubTavily({}),
                                 places=StubPlaces())
    assert result.status == "no_results"
    assert result.locations == []


def test_places_auth_error_propagates():
    places = StubPlaces(fail_with=AuthError("키 문제"))
    with pytest.raises(AuthError):
        find_film_locations("부산행", year=2016,
                            brave=StubSearch(_full_mapping()),
                            tavily=StubTavily(_full_mapping()), places=places)


# --- 신뢰도 -------------------------------------------------------------

def test_confidence_scale():
    assert _confidence(1, resolved=True) == pytest.approx(0.6)
    assert _confidence(2, resolved=True) == pytest.approx(0.8)
    assert _confidence(3, resolved=True) == pytest.approx(1.0)
    assert _confidence(1, resolved=False) == pytest.approx(0.4)
