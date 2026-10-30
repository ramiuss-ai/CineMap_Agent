"""공유용 일정표 + PDF 내보내기 화면 흐름 테스트 (AppTest).

일정 초안을 만들면 공유용 일정표(날짜·시간·장소·링크·설명·이동·비용)가
보이고, PDF 다운로드 버튼이 나오는지, 비용 칸 편집이 유지되는지 확인한다.
실제 API는 호출하지 않는다 — 후보 수집 함수들은 전부 가짜로 대체한다.
PDF 글꼴은 테스트 환경의 나눔고딕을 CINEMAP_PDF_FONT로 지정한다.
"""
from __future__ import annotations

import os
from datetime import date
from unittest import mock

import pytest
from streamlit.testing.v1 import AppTest

from src.models import Candidate, ResolvedPlace

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")
FONT = os.path.expanduser("~/.fonts/NanumGothic-Regular.ttf")

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
        Candidate(category="culture", place=_rp("M1", "국립 미술관"),
                  distance_m=3200.0),
        Candidate(category="restaurants",
                  place=_rp("R1", "이치란 도톤보리",
                            types=["restaurant", "japanese_restaurant"]),
                  distance_m=900.0),
    ]


def _click(at: AppTest, label: str) -> AppTest:
    for b in at.button:
        if b.label == label:
            b.click()
            return at.run()
    raise AssertionError(f"버튼 없음: {label} "
                         f"(있는 버튼: {[b.label for b in at.button]})")


def _make_plan(monkeypatch) -> AppTest:
    for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
        monkeypatch.setenv(key, "dummy")
    monkeypatch.setenv("CINEMAP_PDF_FONT", FONT)
    with mock.patch("src.candidates.find_destination", return_value=[DEST]), \
         mock.patch("src.candidates.find_candidates",
                    return_value=(_cands(), [], 6)), \
         mock.patch("src.candidates.find_film_candidates",
                    return_value=([], [], 0, 0)):
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at.text_input(key="dest_query").input("오사카")
        at.run()
        at = _click(at, "여행지 찾기")
        at = _click(at, "이 여행지로 정하기")
        at = _click(at, "명소 후보 찾기")
        at.date_input(key="trip_dates").set_value(
            (date(2026, 11, 1), date(2026, 11, 3)))
        at.run()
        at = _click(at, "일정 초안 만들기")
        return at


def _has_share_table(at: AppTest) -> bool:
    return any("공유용 일정표" in m.value for m in at.markdown)


@pytest.mark.skipif(not os.path.isfile(FONT), reason="테스트용 한글 글꼴 없음")
def test_share_table_and_pdf_button(monkeypatch):
    at = _make_plan(monkeypatch)
    assert not at.exception
    assert _has_share_table(at)
    # 추정 안내가 보인다 (정직성 표기)
    assert any("직선거리 기준 추정" in c.value for c in at.caption)
    # 일정표 데이터 편집기에 방문지가 들어 있다
    # (이 AppTest 버전에서는 st.data_editor가 dataframe 요소로 잡힌다)
    editors = [d for d in at.dataframe if "오사카성" in str(d.value)]
    assert len(editors) == 1
    cell_text = str(editors[0].value)
    assert "국립 미술관" in cell_text
    assert "11월 1일" in cell_text
    assert "비용 (원)" in cell_text
    # PDF 다운로드 버튼
    # 버튼이 그려졌다는 것 자체가 PDF 바이트 생성 성공을 뜻한다
    # (생성 실패 시 버튼 대신 warning이 나온다)
    assert len(at.download_button) == 1
    assert "PDF" in at.download_button[0].label
    assert not at.warning


@pytest.mark.skipif(not os.path.isfile(FONT), reason="테스트용 한글 글꼴 없음")
def test_share_table_survives_widget_rerun(monkeypatch):
    """위젯 조작 재실행 후에도 일정표와 PDF 버튼이 유지된다."""
    at = _make_plan(monkeypatch)
    assert _has_share_table(at)
    at.slider(key="cand_radius").set_value(20)
    at = at.run()
    assert not at.exception
    assert _has_share_table(at)
    assert len(at.download_button) == 1
