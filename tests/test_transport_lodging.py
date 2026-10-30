"""이동 수단 + 숙소 테스트 (2026-10-30, WhatsApp 요청).

- 이동 수단(렌트카/가이드 투어/대중교통)이 여행 조건·일정표 이동 칸·예산
  지출 항목 이름에 반영되는지 확인한다.
- 숙소를 고르면 일정표에 박 수만큼 '숙박' 행이 들어가는지 확인한다.
- 정직성: 투어·대중교통은 소요시간 숫자를 지어내지 않는다.
- 화면 흐름(AppTest)까지 확인한다. 실제 API는 호출하지 않는다.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from unittest import mock

import pytest
from streamlit.testing.v1 import AppTest

from src.candidates import find_lodging
from src.errors import UpstreamError
from src.itinerary import build_rows, transport_estimate
from src.models import Candidate, FilmLocation, ResolvedPlace
from src.nearby import haversine_m
from src.trip import (DEFAULT_TRANSPORT, TRANSPORT_MODES, DayPlan,
                      TripSettings, plan_inputs_match,
                      transport_expense_label, validate_settings)

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")
FONT = os.path.expanduser("~/.fonts/NanumGothic-Regular.ttf")


def _loc(name, lat=34.70, lon=135.51):
    return FilmLocation(name=name, address=f"{name} 주소", lat=lat, lon=lon,
                        google_maps_uri=f"https://maps.example/{name}")


def _hotel(name="호텔 그레이스리"):
    return ResolvedPlace(place_id="HOTEL1", name=name,
                         address=f"{name} 주소", lat=34.69, lon=135.50,
                         google_maps_uri=f"https://maps.example/{name}")


def _trip(start=date(2026, 11, 1), days=3, mode="rental_car"):
    return TripSettings(party_size=2, start_date=start,
                        end_date=start + timedelta(days=days - 1),
                        budget_amount=0, transport_mode=mode)


# --- 이동 수단 단위 테스트 -------------------------------------------------

def test_transport_modes_expected_set():
    assert TRANSPORT_MODES == {"rental_car": "렌트카",
                               "guided_tour": "가이드 투어",
                               "transit": "대중교통"}
    assert DEFAULT_TRANSPORT == "rental_car"


def test_validate_settings_rejects_unknown_mode():
    bad = _trip(mode="helicopter")
    assert any("이동 수단" in p for p in validate_settings(bad))
    assert validate_settings(_trip(mode="transit")) == []


def test_transport_expense_label():
    assert transport_expense_label("rental_car") == "렌터카"
    assert transport_expense_label("guided_tour") == "투어 비용"
    assert transport_expense_label("transit") == "교통비"


def test_transport_estimate_guided_tour_has_no_fabricated_time():
    txt = transport_estimate(_loc("A"), _loc("B", 34.75, 135.56),
                             haversine_m, "guided_tour")
    assert "투어" in txt and "직선" in txt
    assert "분" not in txt and "시간은 투어 일정 확인" in txt


def test_transport_estimate_transit_has_no_fabricated_time():
    txt = transport_estimate(_loc("A"), _loc("B", 34.75, 135.56),
                             haversine_m, "transit")
    assert "대중교통" in txt and "확인 필요" in txt
    assert "분" not in txt


def test_build_rows_transport_text_follows_mode():
    days = [DayPlan(day=1, stops=[_loc("오사카성"), _loc("쓰텐카쿠", 34.65, 135.51)])]
    labels = {"오사카성": "historic", "쓰텐카쿠": "historic"}
    for mode, token in [("rental_car", "차 약"), ("guided_tour", "투어 이동"),
                        ("transit", "대중교통")]:
        rows = build_rows(days, {}, _trip(days=1, mode=mode),
                          labels.get, lambda c: c, haversine_m)
        assert token in rows[1].transport


# --- 숙소 단위 테스트 ------------------------------------------------------

def test_build_rows_lodging_adds_per_night_rows():
    days = [DayPlan(day=1, stops=[_loc("오사카성")]),
            DayPlan(day=2, stops=[_loc("미노오 공원", 34.85, 135.47)]),
            DayPlan(day=3, stops=[_loc("만박기념공원", 34.81, 135.53)])]
    rows = build_rows(days, {}, _trip(days=3), lambda n: "historic",
                      lambda c: c, haversine_m, lodging=_hotel())
    nights = [r for r in rows if r.time == "숙박"]
    assert len(nights) == 2               # 2박 3일: 마지막 날은 체크아웃
    assert nights[0].date.startswith("11월 1일")
    assert "1박째" in nights[0].description
    assert nights[1].date.startswith("11월 2일")
    assert "2박째" in nights[1].description
    assert all(r.place == "호텔 그레이스리" for r in nights)
    assert all(r.cost is None for r in nights)   # 비용은 사용자가 적는다
    assert all(r.link.startswith("https://") for r in nights)


def test_build_rows_lodging_row_on_free_day_too():
    """자유 일정인 날에도 그 날 밤 숙박 행은 들어간다."""
    days = [DayPlan(day=1, stops=[_loc("오사카성")]),
            DayPlan(day=2, stops=[], note="자유 일정")]
    rows = build_rows(days, {2: []}, _trip(days=2), lambda n: "historic",
                      lambda c: c, haversine_m, lodging=_hotel())
    places = [(r.date, r.place) for r in rows]
    assert ("11월 1일 (일)", "호텔 그레이스리") in places
    assert any(p == "자유 일정" for _d, p in places)


def test_build_rows_no_lodging_no_rows():
    days = [DayPlan(day=1, stops=[_loc("오사카성")])]
    rows = build_rows(days, {}, _trip(days=1), lambda n: "historic",
                      lambda c: c, haversine_m)
    assert all(r.time != "숙박" for r in rows)


def test_build_rows_day_trip_no_lodging_row():
    """당일치기(0박)에는 숙소를 골라도 숙박 행이 없다."""
    days = [DayPlan(day=1, stops=[_loc("오사카성")])]
    rows = build_rows(days, {}, _trip(days=1), lambda n: "historic",
                      lambda c: c, haversine_m, lodging=_hotel())
    assert all(r.time != "숙박" for r in rows)


def test_find_lodging_filters_and_sorts():
    dest = ResolvedPlace(place_id="D1", name="오사카", address="a",
                         lat=34.6937, lon=135.5023)
    near = ResolvedPlace(place_id="H1", name="가까운호텔", address="a",
                         lat=34.695, lon=135.505)
    far = ResolvedPlace(place_id="H2", name="먼호텔", address="a",
                        lat=35.5, lon=136.0)     # 반경 밖
    self_ = ResolvedPlace(place_id="D1", name="오사카", address="a",
                          lat=34.6937, lon=135.5023)
    places = mock.Mock()
    places.nearby_search.return_value = [far, near, self_]
    found, warnings, calls = find_lodging(dest, places, radius_m=10_000)
    assert calls == 1
    assert [p.name for p in found] == ["가까운호텔"]
    assert warnings == []
    args = places.nearby_search.call_args
    assert args.kwargs["included_types"] == ["lodging"]


def test_find_lodging_error_returns_warning():
    dest = ResolvedPlace(place_id="D1", name="오사카", address="a",
                         lat=34.6937, lon=135.5023)
    places = mock.Mock()
    places.nearby_search.side_effect = UpstreamError("500")
    found, warnings, calls = find_lodging(dest, places)
    assert found == [] and calls == 1
    assert any("숙소 검색 실패" in w for w in warnings)


# --- plan_inputs_match 확장 -------------------------------------------------

def _current(**over):
    base = {
        "dates": (date(2026, 11, 1), date(2026, 11, 3)),
        "party": 2, "budget": 0, "basis": "total", "airfare": True,
        "companions": "", "picks": ["오사카성"],
        "transport": "rental_car", "lodging": "호텔 그레이스리",
    }
    base.update(over)
    return base


def test_plan_inputs_match_transport_change_mismatch():
    trip = _trip()
    assert plan_inputs_match(trip, ["오사카성"], _current(),
                             saved_lodging="호텔 그레이스리")
    assert not plan_inputs_match(
        trip, ["오사카성"], _current(transport="guided_tour"),
        saved_lodging="호텔 그레이스리")


def test_plan_inputs_match_lodging_change_mismatch():
    trip = _trip()
    assert not plan_inputs_match(
        trip, ["오사카성"], _current(lodging="다른 호텔"),
        saved_lodging="호텔 그레이스리")
    assert not plan_inputs_match(
        trip, ["오사카성"], _current(lodging=None),
        saved_lodging="호텔 그레이스리")


def test_plan_inputs_match_legacy_keys_still_work():
    """transport/lodging 키가 없는 옛 호출은 그 항목을 비교하지 않는다."""
    trip = _trip()
    cur = _current()
    del cur["transport"]
    del cur["lodging"]
    assert plan_inputs_match(trip, ["오사카성"], cur)


# --- 화면 흐름 (AppTest) ----------------------------------------------------

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


def _hotels():
    return [_rp("HO1", "호텔 그레이스리", 34.69, 135.50),
            _rp("HO2", "난바 인", 34.68, 135.50)]


def _click(at: AppTest, label: str) -> AppTest:
    for b in at.button:
        if b.label == label:
            b.click()
            return at.run()
    raise AssertionError(f"버튼 없음: {label} "
                         f"(있는 버튼: {[b.label for b in at.button]})")


def _make_plan_with_lodging(monkeypatch, mode="guided_tour") -> AppTest:
    for key in ("TAVILY_API_KEY", "BRAVE_API_KEY", "GOOGLE_PLACES_API_KEY"):
        monkeypatch.setenv(key, "dummy")
    monkeypatch.setenv("CINEMAP_PDF_FONT", FONT)
    with mock.patch("src.candidates.find_destination", return_value=[DEST]), \
         mock.patch("src.candidates.find_candidates",
                    return_value=(_cands(), [], 6)), \
         mock.patch("src.candidates.find_film_candidates",
                    return_value=([], [], 0, 0)), \
         mock.patch("src.candidates.find_lodging",
                    return_value=(_hotels(), [], 1)):
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        at.text_input(key="dest_query").input("오사카")
        at.run()
        at = _click(at, "여행지 찾기")
        at = _click(at, "이 여행지로 정하기")
        at = _click(at, "명소 후보 찾기")
        at.date_input(key="trip_dates").set_value(
            (date(2026, 11, 1), date(2026, 11, 3)))
        at.number_input(key="trip_budget").set_value(1_000_000)
        at.radio(key="trip_transport").set_value(mode)
        at.run()
        at = _click(at, "숙소 후보 찾기")
        at.radio(key="lodging_pick").set_value("호텔 그레이스리")
        at.run()
        at = _click(at, "일정 초안 만들기")
        return at


@pytest.mark.skipif(not os.path.isfile(FONT), reason="테스트용 한글 글꼴 없음")
def test_flow_transport_and_lodging_in_share_table(monkeypatch):
    at = _make_plan_with_lodging(monkeypatch, mode="guided_tour")
    assert not at.exception
    # 계획 머리에 이동 수단·숙소가 보인다
    assert any("가이드 투어" in c.value and "숙소" in c.value
               for c in at.caption)
    # 일정표에 숙박 행과 투어 기준 이동 문구가 들어간다
    # (str(repr)은 긴 표를 잘라 보여주므로 셀 값을 직접 합쳐서 본다)
    def df_text(df):
        return " ".join(str(v) for row in df.values for v in row)
    editors = [d for d in at.dataframe if "호텔 그레이스리" in df_text(d.value)]
    assert len(editors) == 1
    cell_text = df_text(editors[0].value)
    assert "숙박" in cell_text
    assert "1박째" in cell_text and "2박째" in cell_text
    assert "투어 이동" in cell_text
    assert "시간은 투어 일정 확인" in cell_text
    # 예산 지출 항목이 이동 수단을 따라간다 (렌터카 → 투어 비용)
    labels = [n.label for n in at.number_input]
    assert "투어 비용" in labels
    # PDF 버튼도 나온다 (PDF에 같은 행이 들어간다)
    assert len(at.download_button) == 1
    assert not at.warning


@pytest.mark.skipif(not os.path.isfile(FONT), reason="테스트용 한글 글꼴 없음")
def test_flow_lodging_change_marks_plan_stale(monkeypatch):
    at = _make_plan_with_lodging(monkeypatch, mode="rental_car")
    assert not at.exception
    # 숙소를 바꾸면 초안이 이전 입력 기준이라는 안내가 뜬다
    at.radio(key="lodging_pick").set_value("난바 인")
    at = at.run()
    assert any("이전 입력" in w.value for w in at.warning)


@pytest.mark.skipif(not os.path.isfile(FONT), reason="테스트용 한글 글꼴 없음")
def test_flow_transport_change_marks_plan_stale(monkeypatch):
    at = _make_plan_with_lodging(monkeypatch, mode="rental_car")
    assert not at.exception
    at.radio(key="trip_transport").set_value("transit")
    at = at.run()
    assert any("이전 입력" in w.value for w in at.warning)


@pytest.mark.skipif(not os.path.isfile(FONT), reason="테스트용 한글 글꼴 없음")
def test_flow_without_lodging_pick_no_stay_rows(monkeypatch):
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
        assert not at.exception
        assert any("숙소: 미정" in c.value for c in at.caption)
        editors = [d for d in at.dataframe
                   if any(str(v) == "숙박" for row in d.value.values
                          for v in row)]
        assert editors == []
        assert len(at.download_button) == 1
