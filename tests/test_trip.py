"""모듈 4(여행 조건·일정 초안) 단위 테스트. 외부 API는 부르지 않는다."""
from __future__ import annotations

from datetime import date

from src.models import FilmLocation
from src.trip import (MAX_STOPS_PER_DAY, TripSettings, budget_summary,
                      build_itinerary, cluster_locations, validate_settings)


def _loc(name: str, lat: float, lon: float) -> FilmLocation:
    return FilmLocation(name=name, address=f"{name} 주소", lat=lat, lon=lon)


def _settings(**kw) -> TripSettings:
    base = dict(party_size=2, start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 4), budget_amount=2_000_000,
                budget_basis="total", includes_airfare=True)
    base.update(kw)
    return TripSettings(**base)


# --- TripSettings 날짜/예산 계산 --------------------------------------------

def test_days_and_nights():
    s = _settings()
    assert s.days == 4 and s.nights == 3
    same_day = _settings(end_date=date(2026, 11, 1))
    assert same_day.days == 1 and same_day.nights == 0


def test_total_budget_basis():
    # 전체 기준: 입력액이 곧 총예산
    assert _settings(budget_amount=2_000_000).total_budget == 2_000_000
    # 1인 기준: 인원수를 곱한다
    s = _settings(budget_amount=1_000_000, budget_basis="per_person",
                  party_size=4)
    assert s.total_budget == 4_000_000
    assert s.per_person_budget == 1_000_000


def test_per_person_and_per_day():
    s = _settings(budget_amount=2_000_000, party_size=2)  # 3박 4일
    assert s.per_person_budget == 1_000_000
    assert s.per_day_budget == 500_000


# --- validate_settings -------------------------------------------------------

def test_validate_ok():
    assert validate_settings(_settings()) == []


def test_validate_catches_bad_inputs():
    problems = validate_settings(_settings(
        party_size=0, end_date=date(2026, 10, 1), budget_amount=-5,
        budget_basis="weird"))
    assert len(problems) == 4


# --- cluster_locations --------------------------------------------------------

def test_cluster_groups_nearby_locations():
    # 앨닉 성과 앨닉 정원은 붙어 있고, 스코틀랜드 글렌 에티브는 멀다
    alnwick = _loc("앨닉 성", 55.4157, -1.7059)
    garden = _loc("앨닉 정원", 55.4130, -1.7000)
    glen = _loc("글렌 에티브", 56.62, -4.93)
    clusters = cluster_locations([alnwick, garden, glen])
    assert len(clusters) == 2
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]


def test_cluster_respects_max_stops():
    locs = [_loc(f"곳{i}", 55.41 + i * 0.001, -1.70) for i in range(5)]
    clusters = cluster_locations(locs)
    assert all(len(c) <= MAX_STOPS_PER_DAY for c in clusters)
    assert sum(len(c) for c in clusters) == 5


# --- build_itinerary ----------------------------------------------------------

def test_itinerary_free_days_when_fewer_clusters():
    alnwick = _loc("앨닉 성", 55.4157, -1.7059)
    plans = build_itinerary([alnwick], 3)
    assert len(plans) == 3
    assert plans[0].stops == [alnwick]
    assert plans[1].stops == [] and plans[1].note == "자유 일정"


def test_itinerary_merges_when_more_clusters_than_days():
    locs = [_loc(f"곳{i}", 37.0 + i * 2.0, 127.0) for i in range(4)]  # 전부 멂
    plans = build_itinerary(locs, 2)
    assert len(plans) == 2
    assert sum(len(p.stops) for p in plans) == 4  # 촬영지는 하나도 빠지지 않는다
    # 일수에 맞춰 합친 날은 merged=True (이동 시간 미검증 표시)
    assert any(p.merged for p in plans)


def test_itinerary_no_merge_flag_when_clusters_fit():
    locs = [_loc(f"곳{i}", 37.0 + i * 2.0, 127.0) for i in range(2)]
    plans = build_itinerary(locs, 2)
    assert not any(p.merged for p in plans)


def test_itinerary_zero_days():
    assert build_itinerary([_loc("a", 1, 1)], 0) == []


# --- budget_summary -----------------------------------------------------------

def test_budget_summary_counts_airfare_when_included():
    s = _settings(budget_amount=1_000_000, includes_airfare=True)
    r = budget_summary(s, {"airfare": 400_000, "food": 100_000})
    assert r["spent"] == 500_000
    assert r["remaining"] == 500_000


def test_budget_summary_excludes_airfare_when_separate():
    s = _settings(budget_amount=1_000_000, includes_airfare=False)
    r = budget_summary(s, {"airfare": 400_000, "food": 100_000})
    assert r["spent"] == 100_000  # 항공료는 예산 밖
    assert r["remaining"] == 900_000


def test_budget_summary_negative_remaining():
    s = _settings(budget_amount=100_000)
    r = budget_summary(s, {"lodging": 150_000})
    assert r["remaining"] == -50_000
