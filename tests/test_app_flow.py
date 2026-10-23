"""앱 흐름 회귀 테스트 — streamlit AppTest로 실제 재실행(rerun)을 흉내낸다.

버그(2026-10-23 사용자 제보): 촬영지를 찾은 뒤 '주변 찾기'에서 반경을 조절하거나
버튼을 누르면 결과 화면이 사라지고 첫 화면으로 돌아갔다. 원인은 촬영지 결과를
'촬영지 찾기' 버튼을 누른 그 실행에서만 그렸기 때문. 지금은 세션의 마지막
결과를 매 재실행마다 다시 그린다 (app.py reshow_last_result).

실제 API는 호출하지 않는다 — 파이프라인 함수들은 전부 가짜로 대체한다.
"""
from __future__ import annotations

import os
from unittest import mock

from streamlit.testing.v1 import AppTest

from src.models import (FilmLocation, LocationSearchResult, Movie,
                        MovieCandidate, NearbyGroup, NearbyPlace, ResolvedPlace)

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")


def _fake_result() -> LocationSearchResult:
    loc = FilmLocation(name="앨닉 성", address="Alnwick, UK",
                       lat=55.4157, lon=-1.7059, source_id="GB1",
                       source_urls=["https://example.com/hp"],
                       confidence=0.9,
                       google_maps_uri="https://maps.example/alnwick")
    return LocationSearchResult(query="Harry Potter", status="ok",
                                locations=[loc])


def _fake_groups(result: LocationSearchResult) -> list[NearbyGroup]:
    place = ResolvedPlace(place_id="R1", name="트리프톤 식당", address="Alnwick",
                          lat=55.42, lon=-1.70)
    group = NearbyGroup(location=result.locations[0])
    group.restaurants = [NearbyPlace(category="restaurants", distance_m=800.0,
                                     place=place)]
    return [group]


def _labels(elements) -> list[str]:
    return [e.label for e in elements]


def _click(at: AppTest, label: str) -> AppTest:
    for b in at.button:
        if b.label == label:
            b.click()
            return at.run()
    raise AssertionError(f"버튼 없음: {label} (있는 버튼: {_labels(at.button)})")


def _has_locations_header(at: AppTest) -> bool:
    return any("촬영지 후보" in s.value for s in at.subheader)


def _has_nearby_place(at: AppTest) -> bool:
    return any("트리프톤 식당" in m.value for m in at.markdown)


def test_results_survive_widget_reruns_without_tmdb(monkeypatch):
    """모듈 1 단독: 슬라이더 조작/'주변 찾기' 클릭 후에도 결과가 유지돼야 한다."""
    monkeypatch.setenv("TAVILY_API_KEY", "dummy")
    monkeypatch.setenv("BRAVE_API_KEY", "dummy")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "dummy")
    monkeypatch.delenv("TMDB_API_KEY", raising=False)

    result = _fake_result()
    with mock.patch("src.pipeline.find_film_locations",
                    return_value=result), \
         mock.patch("src.nearby.find_nearby",
                    return_value=_fake_groups(result)) as nearby_mock:
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at.text_input[0].input("해리포터")
        at.run()
        at = _click(at, "촬영지 찾기")
        assert _has_locations_header(at)
        assert "주변 찾기" in _labels(at.button)

        # 반경 슬라이더를 움직여도(=재실행) 결과가 그대로여야 한다 (회귀 지점)
        at.slider[0].set_value(5)
        at.run()
        assert _has_locations_header(at)
        assert "주변 찾기" in _labels(at.button)
        assert not nearby_mock.called  # 슬라이더 조작만으로는 API를 부르면 안 됨

        # '주변 찾기' 클릭 → 결과가 유지되며 주변 추천이 나와야 한다
        at = _click(at, "주변 찾기")
        assert _has_locations_header(at)
        assert nearby_mock.called
        assert _has_nearby_place(at)

        # 그 다음 재실행에서도 촬영지 + 주변 결과가 모두 유지돼야 한다
        at.run()
        assert _has_locations_header(at)
        assert _has_nearby_place(at)


def test_results_survive_reruns_with_tmdb(monkeypatch):
    """모듈 2(TMDB 영화 확정) 흐름에서도 동일하게 유지돼야 한다."""
    for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY",
                "TMDB_API_KEY"):
        monkeypatch.setenv(key, "dummy")

    cand = MovieCandidate(
        title="해리 포터와 마법사의 돌", year=2001, tmdb_id=671,
        original_title="Harry Potter and the Philosopher's Stone")
    movie = Movie(tmdb_id=671, title="해리 포터와 마법사의 돌",
                  english_title="Harry Potter and the Philosopher's Stone",
                  year=2001, director="Chris Columbus",
                  production_countries=["GB", "US"])
    result = _fake_result()
    with mock.patch("src.movie_search.search_movies", return_value=[cand]), \
         mock.patch("src.movie_search.confirm_movie", return_value=movie), \
         mock.patch("src.pipeline.find_film_locations", return_value=result), \
         mock.patch("src.nearby.find_nearby",
                    return_value=_fake_groups(result)):
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at.text_input[0].input("해리포터")
        at.run()
        at = _click(at, "영화 찾기")
        at = _click(at, "이 영화예요")
        at = _click(at, "이 영화로 촬영지 찾기")
        assert _has_locations_header(at)

        at.slider[0].set_value(3)
        at.run()
        assert _has_locations_header(at)

        at = _click(at, "주변 찾기")
        assert _has_locations_header(at)
        assert _has_nearby_place(at)


def test_results_reset_when_new_search(monkeypatch):
    """새 영화를 찾으면 이전 촬영지/주변 결과는 사라져야 한다 (잔상 방지)."""
    for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY",
                "TMDB_API_KEY"):
        monkeypatch.setenv(key, "dummy")

    cand = MovieCandidate(title="해리 포터와 마법사의 돌", year=2001, tmdb_id=671,
                          original_title="Harry Potter and the Philosopher's Stone")
    movie = Movie(tmdb_id=671, title="해리 포터와 마법사의 돌",
                  english_title="Harry Potter and the Philosopher's Stone",
                  year=2001, production_countries=["GB", "US"])
    result = _fake_result()
    with mock.patch("src.movie_search.search_movies", return_value=[cand]), \
         mock.patch("src.movie_search.confirm_movie", return_value=movie), \
         mock.patch("src.pipeline.find_film_locations", return_value=result), \
         mock.patch("src.nearby.find_nearby",
                    return_value=_fake_groups(result)):
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at.text_input[0].input("해리포터")
        at.run()
        at = _click(at, "영화 찾기")
        at = _click(at, "이 영화예요")
        at = _click(at, "이 영화로 촬영지 찾기")
        assert _has_locations_header(at)

        # 다른 영화를 다시 찾으면 확정 영화가 사라지고 결과도 보이면 안 된다
        at = _click(at, "영화 찾기")
        assert not _has_locations_header(at)
