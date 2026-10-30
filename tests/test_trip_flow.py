"""여행 계획 화면 흐름 테스트 — AppTest로 실제 재실행(rerun)을 흉내낸다.

일정 초안도 '일정 초안 만들기'를 누른 그 실행에서만 그리면 위젯 조작 시
사라진다. 세션 저장 + 재렌더링이 유지되는지, 입력이 바뀌면 '이전 입력
기준' 경고가 뜨는지, 새 후보 검색이 초안을 지우는지, 남는 날 채우기가
고르지 않은 후보로 동작하는지 확인한다.
실제 API는 호출하지 않는다 — 후보 수집 함수들은 전부 가짜로 대체한다.
"""
from __future__ import annotations

import os
from datetime import date
from unittest import mock

from streamlit.testing.v1 import AppTest

from src.models import Candidate, ResolvedPlace

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")

DEST = ResolvedPlace(place_id="D1", name="오사카",
                     address="일본 오사카부 오사카시",
                     lat=34.6937, lon=135.5023,
                     google_maps_uri="https://maps.example/osaka",
                     country_code="JP")


def _rp(pid, name, lat=34.70, lon=135.51, types=None):
    return ResolvedPlace(place_id=pid, name=name, address=f"{name} 주소",
                         lat=lat, lon=lon, types=types or [],
                         google_maps_uri=f"https://maps.example/{pid}")


def _cands():
    return [
        Candidate(category="historic", place=_rp("H1", "오사카성"),
                  distance_m=2500.0),
        Candidate(category="trekking",
                  place=_rp("T1", "미노오 공원", lat=34.85, lon=135.47),
                  distance_m=17000.0),
        Candidate(category="culture", place=_rp("M1", "국립 미술관"),
                  distance_m=3200.0),
        Candidate(category="restaurants",
                  place=_rp("R1", "이치란 도톤보리",
                            types=["restaurant", "japanese_restaurant"]),
                  distance_m=900.0),
    ]


def _patches():
    return (mock.patch("src.candidates.find_destination", return_value=[DEST]),
            mock.patch("src.candidates.find_candidates",
                       return_value=(_cands(), [], 6)),
            mock.patch("src.candidates.find_film_candidates",
                       return_value=([], [], 0, 0)))


def _click(at: AppTest, label: str) -> AppTest:
    for b in at.button:
        if b.label == label:
            b.click()
            return at.run()
    raise AssertionError(f"버튼 없음: {label} "
                         f"(있는 버튼: {[b.label for b in at.button]})")


def _search_candidates(at: AppTest) -> AppTest:
    at.text_input(key="dest_query").input("오사카")
    at.run()
    at = _click(at, "여행지 찾기")
    at = _click(at, "이 여행지로 정하기")
    return _click(at, "명소 후보 찾기")


def _has_plan(at: AppTest) -> bool:
    return any("🧳" in m.value for m in at.markdown)


def _make_plan(at: AppTest) -> AppTest:
    at.date_input(key="trip_dates").set_value(
        (date(2026, 11, 1), date(2026, 11, 3)))
    at.run()
    return _click(at, "일정 초안 만들기")


def test_plan_created_and_survives_reruns(monkeypatch):
    p_dest, p_cand, p_film = _patches()
    with p_dest as m_dest, p_cand as m_cand, p_film:
        for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
            monkeypatch.setenv(key, "dummy")
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at = _search_candidates(at)
        at = _make_plan(at)
        assert _has_plan(at)
        assert any("오사카성" in m.value for m in at.markdown)
        # 맛집은 기본 선택에서 빠지고 식사 옵션으로 따로 보인다
        assert any("식사 옵션" in e.label for e in at.expander)

        # 위젯 조작 재실행 후에도 초안 유지, API 재호출 없음
        at.slider(key="cand_radius").set_value(20)
        at.run()
        assert _has_plan(at)
        assert m_cand.call_count == 1


def test_plan_resets_on_new_candidate_search(monkeypatch):
    p_dest, p_cand, p_film = _patches()
    with p_dest as m_dest, p_cand as m_cand, p_film:
        for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
            monkeypatch.setenv(key, "dummy")
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at = _search_candidates(at)
        at = _make_plan(at)
        assert _has_plan(at)
        # 새 후보 검색 → 초안은 다른 후보 기준이라 지워진다
        at = _click(at, "명소 후보 찾기")
        assert not _has_plan(at)
        assert m_cand.call_count == 2


def test_stale_warning_when_inputs_change_after_plan(monkeypatch):
    p_dest, p_cand, p_film = _patches()
    with p_dest, p_cand, p_film:
        for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
            monkeypatch.setenv(key, "dummy")
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at = _search_candidates(at)
        at = _make_plan(at)
        assert _has_plan(at)
        assert not any("반영되지 않았어요" in w.value for w in at.warning)

        at.date_input(key="trip_dates").set_value(
            (date(2026, 11, 5), date(2026, 11, 8)))
        at.run()
        assert _has_plan(at)
        assert any("이전 입력" in w.value for w in at.warning)
        assert any("반영되지 않았어요" in w.value for w in at.warning)


def test_free_days_filled_with_unpicked_candidates(monkeypatch):
    """후보를 일부만 고르면, 남는 날에 고르지 않은 후보가 채워진다 (추가 검색 없음)."""
    p_dest, p_cand, p_film = _patches()
    with p_dest, p_cand, p_film:
        for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
            monkeypatch.setenv(key, "dummy")
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at = _search_candidates(at)
        at.date_input(key="trip_dates").set_value(
            (date(2026, 11, 1), date(2026, 11, 3)))
        at.run()
        # 오사카성·미노오 공원만 고른다 (국립 미술관은 남긴다)
        at.multiselect(key="trip_picks").set_value(["오사카성", "미노오 공원"])
        at.run()
        at = _click(at, "일정 초안 만들기")
        assert _has_plan(at)
        assert any("국립 미술관" in m.value for m in at.markdown)
        assert any("고르지 않은 후보" in c.value for c in at.caption)