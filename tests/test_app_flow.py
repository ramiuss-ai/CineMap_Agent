"""앱 흐름 회귀 테스트 — streamlit AppTest로 실제 재실행(rerun)을 흉내낸다.

기존 영화 우선 흐름의 회귀(주변 찾기 누르면 첫 화면으로)와 같은 문제가
장소 중심 흐름에도 없는지 확인한다: 명소 후보·여행지 선택은 세션에
저장돼 위젯 조작 재실행 후에도 그대로 보여야 하고, 재실행에서 외부
API를 다시 부르면 안 된다 (버튼을 누를 때만 검색 = 비용 원칙).

실제 API는 호출하지 않는다 — 후보 수집 함수들은 전부 가짜로 대체한다.
"""
from __future__ import annotations

import os
from unittest import mock

from streamlit.testing.v1 import AppTest

from src.models import Candidate, CandidateSet, ResolvedPlace

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")

DEST = ResolvedPlace(place_id="D1", name="오사카",
                     address="일본 오사카부 오사카시",
                     lat=34.6937, lon=135.5023,
                     google_maps_uri="https://maps.example/osaka",
                     country_code="JP")
DEST2 = ResolvedPlace(place_id="D2", name="다낭",
                      address="베트남 다낭", lat=16.0544, lon=108.2022,
                      google_maps_uri="https://maps.example/danang",
                      country_code="VN")


def _rp(pid, name, lat=34.70, lon=135.51, types=None):
    return ResolvedPlace(place_id=pid, name=name, address=f"{name} 주소",
                         lat=lat, lon=lon, types=types or [],
                         google_maps_uri=f"https://maps.example/{pid}")


def _cands():
    return [
        Candidate(category="historic", place=_rp("H1", "오사카성"),
                  distance_m=2500.0),
        Candidate(category="restaurants",
                  place=_rp("R1", "이치란 도톤보리",
                            types=["restaurant", "japanese_restaurant"]),
                  distance_m=900.0),
        Candidate(category="film", place=_rp("F1", "쓰텐카쿠"),
                  distance_m=800.0, film=True,
                  source_urls=["https://example.com/film"], confidence=0.8),
    ]


def _patches():
    dests = [DEST, DEST2]
    films = [c for c in _cands() if c.film]
    spots = [c for c in _cands() if not c.film]
    return (mock.patch("src.candidates.find_destination", return_value=dests),
            mock.patch("src.candidates.find_candidates",
                       return_value=(spots, [], 5)),
            mock.patch("src.candidates.find_film_candidates",
                       return_value=(films, [], 1, 4)))


def _labels(elements) -> list[str]:
    return [e.label for e in elements]


def _click(at: AppTest, label: str) -> AppTest:
    for b in at.button:
        if b.label == label:
            b.click()
            return at.run()
    raise AssertionError(f"버튼 없음: {label} (있는 버튼: {_labels(at.button)})")


def _run_app(monkeypatch):
    for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
        monkeypatch.setenv(key, "dummy")
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def _search_destination(at: AppTest) -> AppTest:
    at.text_input[0].input("오사카")
    at.run()
    return _click(at, "여행지 찾기")


def _has_candidates_header(at: AppTest) -> bool:
    return any("명소 후보" in s.value for s in at.subheader)


def test_candidates_survive_widget_reruns_without_new_calls(monkeypatch):
    """슬라이더 등 위젯 조작 재실행 후에도 후보가 유지되고, API는 다시 안 부른다."""
    p_dest, p_cand, p_film = _patches()
    with p_dest as m_dest, p_cand as m_cand, p_film as m_film:
        at = _run_app(monkeypatch)
        at = _search_destination(at)
        at = _click(at, "이 여행지로 정하기")
        at = _click(at, "명소 후보 찾기")
        assert _has_candidates_header(at)
        assert m_dest.call_count == 1 and m_cand.call_count == 1
        assert m_film.call_count == 1      # 영화 촬영지 기본 ON

        # 위젯 조작 재실행 (반경 슬라이더 이동)
        for w in at.slider:
            if w.key == "cand_radius":
                w.set_value(15)
        at.run()
        assert _has_candidates_header(at)   # 화면 유지
        assert any("오사카성" in m.value or "쓰텐카쿠" in m.value
                   for m in at.markdown)
        # 재실행에서 API를 다시 부르지 않는다
        assert m_dest.call_count == 1 and m_cand.call_count == 1
        assert m_film.call_count == 1


def test_film_candidate_shows_evidence_links(monkeypatch):
    """영화 촬영지 후보는 근거 링크와 함께 보여야 한다."""
    p_dest, p_cand, p_film = _patches()
    with p_dest, p_cand, p_film:
        at = _run_app(monkeypatch)
        at = _search_destination(at)
        at = _click(at, "이 여행지로 정하기")
        at = _click(at, "명소 후보 찾기")
        assert any("근거" in c.value and "링크1" in c.value
                   for c in at.caption)
        assert any("쓰텐카쿠" in m.value for m in at.markdown)


def test_new_destination_resets_candidates(monkeypatch):
    """다른 여행지를 정하면 기존 후보·일정은 지워진다 (다른 지역 기준이라)."""
    p_dest, p_cand, p_film = _patches()
    with p_dest, p_cand, p_film:
        at = _run_app(monkeypatch)
        at = _search_destination(at)
        at = _click(at, "이 여행지로 정하기")
        at = _click(at, "명소 후보 찾기")
        assert _has_candidates_header(at)
        # 두 번째 여행지(다낭)로 변경
        for b in at.button:
            if b.label == "이 여행지로 정하기" and b.key == "dest_pick_D2":
                b.click()
                at = at.run()
                break
        assert not _has_candidates_header(at)
        assert any("다낭" in m.value for m in at.markdown)