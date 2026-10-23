"""모듈 4 화면 흐름 테스트 — AppTest로 실제 재실행(rerun)을 흉내낸다.

모듈 3 버그 수정(2026-10-23)처럼, 일정 초안도 버튼을 누른 그 실행에서만
그리면 위젯 조작 시 사라진다. 세션 저장 + 재렌더링이 유지되는지 확인한다.
실제 API는 호출하지 않는다 — 파이프라인 함수들은 전부 가짜로 대체한다.
"""
from __future__ import annotations

import os
from datetime import date
from unittest import mock

from streamlit.testing.v1 import AppTest

from src.models import FilmLocation, LocationSearchResult

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")


def _fake_result() -> LocationSearchResult:
    locs = [
        FilmLocation(name="앨닉 성", address="Alnwick, UK", lat=55.4157,
                     lon=-1.7059, source_id="GB1",
                     source_urls=["https://example.com/hp"], confidence=0.9),
        FilmLocation(name="앨닉 정원", address="Alnwick, UK", lat=55.4130,
                     lon=-1.7000, source_id="GB2",
                     source_urls=["https://example.com/garden"], confidence=0.8),
    ]
    return LocationSearchResult(query="Harry Potter", status="ok",
                                locations=locs)


def _click(at: AppTest, label: str) -> AppTest:
    for b in at.button:
        if b.label == label:
            b.click()
            return at.run()
    raise AssertionError(f"버튼 없음: {label} "
                         f"(있는 버튼: {[b.label for b in at.button]})")


def _search(at: AppTest, result) -> AppTest:
    at.text_input[0].input("해리포터")
    at.run()
    return _click(at, "촬영지 찾기")


def _has_plan(at: AppTest) -> bool:
    return any("박" in m.value and "일차" not in m.value and "🧳" in m.value
               for m in at.markdown)


def _run_app(monkeypatch, result):
    monkeypatch.setenv("TAVILY_API_KEY", "dummy")
    monkeypatch.setenv("BRAVE_API_KEY", "dummy")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "dummy")
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    with mock.patch("src.pipeline.find_film_locations", return_value=result):
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        yield at


def test_plan_created_and_survives_reruns(monkeypatch):
    """일정 초안을 만든 뒤 다른 위젯을 건드려도 초안이 유지돼야 한다."""
    result = _fake_result()
    with mock.patch("src.pipeline.find_film_locations", return_value=result):
        for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
            monkeypatch.setenv(key, "dummy")
        monkeypatch.delenv("TMDB_API_KEY", raising=False)
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at = _search(at, result)

        # 모듈 4 입력: 3일, 3명, 1인 100만원, 촬영지 2곳 모두 포함
        at.date_input[0].set_value((date(2026, 11, 1), date(2026, 11, 3)))
        at.run()
        for w in at.number_input:
            if w.key == "trip_party":
                w.set_value(3)
            if w.key == "trip_budget":
                w.set_value(1_000_000)
        for w in at.radio:
            if w.key == "trip_basis":
                w.set_value("per_person")
        at.run()
        at = _click(at, "일정 초안 만들기")
        assert _has_plan(at), "일정 초안이 보여야 한다"
        # 2박 3일, 1인 기준이면 전체 예산은 300만원
        assert any("2박 3일" in m.value for m in at.markdown)
        assert any("3,000,000" in m.value for m in at.metric)

        # 초안의 한계 안내와 지출 입력 기준이 보여야 한다
        captions = [c.value for c in at.caption]
        assert any("직선거리" in c for c in captions)
        assert any("일행 전원의 여행 전체 기간 합계" in c for c in captions)

        # 반경 슬라이더(다른 위젯)를 건드려도 초안이 유지돼야 한다
        at.slider[0].set_value(5)
        at.run()
        assert _has_plan(at)


def test_plan_resets_on_new_search_and_validates_dates(monkeypatch):
    """새 촬영지 검색을 하면 이전 초안은 지워지고, 날짜가 거꾸로면 안내문."""
    result = _fake_result()
    with mock.patch("src.pipeline.find_film_locations", return_value=result):
        for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
            monkeypatch.setenv(key, "dummy")
        monkeypatch.delenv("TMDB_API_KEY", raising=False)
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at = _search(at, result)

        at.date_input[0].set_value((date(2026, 11, 1), date(2026, 11, 2)))
        at.run()
        at = _click(at, "일정 초안 만들기")
        assert _has_plan(at)

        # 새 촬영지 검색 → 초안이 사라져야 한다 (잔상 방지)
        at = _click(at, "촬영지 찾기")
        assert not _has_plan(at)

        # 귀국일이 출발일보다 빠르면 안내문을 보여준다
        at.date_input[0].set_value((date(2026, 11, 5), date(2026, 11, 1)))
        at.run()
        at = _click(at, "일정 초안 만들기")
        assert any("귀국일" in e.value for e in at.error)
        assert not _has_plan(at)
