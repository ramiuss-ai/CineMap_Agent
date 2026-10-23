"""모듈 4: 여행 조건(동행인·날짜·예산) 입력과 일정 초안.

사용자 요청 (2026-10-23, WhatsApp): "동행인, 여행날짜, 여행예산 등등".
앱 흐름상 촬영지(모듈 1~2)와 주변 장소(모듈 3)를 찾은 다음 단계로,
찾은 촬영지를 여행 날짜에 맞춰 하루 단위 초안으로 묶고 예산을 가늠한다.

설계:
- 외부 API를 부르지 않는다 (전부 화면 입력값과 이미 찾은 결과의 계산).
- 예산은 1인 기준/전체 기준을 구분하고, 항공료 포함 여부를 고를 수 있다.
- 일정 초안은 촬영지 좌표를 가까운 곳끼리 묶어(직선거리) 하루에 배정한다.
  촬영지 묶음이 여행 일수보다 많으면 가장 가까운 묶음끼리 합치고,
  적으면 남는 날은 '자유 일정'으로 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .nearby import haversine_m
from .models import FilmLocation

BUDGET_BASIS_LABELS = {"per_person": "1인 기준", "total": "전체 기준"}

# 예산 지출 항목 (키, 화면 라벨). 항공료는 '포함' 설정일 때만 예산 차감에 넣는다.
EXPENSE_CATEGORIES: list[tuple[str, str]] = [
    ("airfare", "항공료"),
    ("lodging", "숙소"),
    ("food", "식비"),
    ("activities", "입장·체험"),
    ("car", "렌터카"),
    ("etc", "기타"),
]

# 같은 하루로 묶을 직선거리 기준과 하루 최대 방문 수 (렌터카 이동 전제, 모듈 3과 같은 가정)
SAME_DAY_GAP_KM = 80.0
MAX_STOPS_PER_DAY = 3


@dataclass
class TripSettings:
    """사용자가 입력한 여행 조건."""
    party_size: int                 # 본인 포함 인원
    start_date: date
    end_date: date
    budget_amount: int = 0          # 원 (0이면 예산 미정)
    budget_basis: str = "total"     # "per_person" | "total"
    includes_airfare: bool = True   # 항공료를 예산 안에 포함하는지
    companions: tuple[str, ...] = ()  # 동행인 이름 (선택 입력)

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def nights(self) -> int:
        return self.days - 1

    @property
    def total_budget(self) -> int:
        """전체 여행 예산(원). 1인 기준 입력이면 인원수를 곱한다."""
        if self.budget_basis == "per_person":
            return self.budget_amount * self.party_size
        return self.budget_amount

    @property
    def per_person_budget(self) -> int:
        if self.party_size < 1:
            return 0
        if self.budget_basis == "per_person":
            return self.budget_amount
        return round(self.total_budget / self.party_size)

    @property
    def per_day_budget(self) -> int:
        if self.days < 1:
            return 0
        return round(self.total_budget / self.days)


def validate_settings(s: TripSettings) -> list[str]:
    """입력값 문제 목록. 비어 있으면 사용 가능."""
    problems = []
    if s.party_size < 1:
        problems.append("인원은 1명 이상이어야 해요.")
    if s.end_date < s.start_date:
        problems.append("귀국일은 출발일 이후여야 해요.")
    if s.budget_amount < 0:
        problems.append("예산은 0 이상이어야 해요.")
    if s.budget_basis not in BUDGET_BASIS_LABELS:
        problems.append("예산 기준이 올바르지 않아요.")
    return problems


def cluster_locations(locations: list[FilmLocation],
                      max_gap_km: float = SAME_DAY_GAP_KM,
                      max_stops: int = MAX_STOPS_PER_DAY
                      ) -> list[list[FilmLocation]]:
    """가까운 촬영지끼리 같은 하루 묶음으로 만든다.

    위도→경도 순으로 정렬한 뒤 순서대로 보면서, 묶음의 첫 촬영지에서
    max_gap_km 안이고 아직 max_stops 미만이면 같은 묶음에 넣는다.
    단순한 규칙이라 결과를 눈으로 검증하기 쉽다.
    """
    ordered = sorted(locations, key=lambda loc: (loc.lat, loc.lon))
    clusters: list[list[FilmLocation]] = []
    for loc in ordered:
        if (clusters and len(clusters[-1]) < max_stops
                and haversine_m(clusters[-1][0].lat, clusters[-1][0].lon,
                                loc.lat, loc.lon) <= max_gap_km * 1000):
            clusters[-1].append(loc)
        else:
            clusters.append([loc])
    return clusters


@dataclass
class DayPlan:
    """일정 초안의 하루."""
    day: int                        # 1일차, 2일차, ...
    stops: list[FilmLocation] = field(default_factory=list)
    note: str = ""                  # 예: "자유 일정", "빡빡한 일정"
    merged: bool = False            # 일수에 맞추느라 먼 묶음끼리 합친 날 (이동 시간 미검증)


def build_itinerary(locations: list[FilmLocation], days: int) -> list[DayPlan]:
    """촬영지를 여행 일수에 맞춰 하루 단위 초안으로 배정한다."""
    if days < 1:
        return []
    clusters = cluster_locations(locations)
    merged = [False] * len(clusters)
    # 묶음이 일수보다 많으면 가장 가까운 두 묶음을 합친다 (하루에 몰아넣기).
    # 이렇게 합쳐진 날은 이동 거리를 검증하지 않은 것이라 merged로 표시한다.
    while len(clusters) > days:
        best_i, best_d = 0, float("inf")
        for i in range(len(clusters) - 1):
            a, b = clusters[i][0], clusters[i + 1][0]
            d = haversine_m(a.lat, a.lon, b.lat, b.lon)
            if d < best_d:
                best_i, best_d = i, d
        clusters[best_i] = clusters[best_i] + clusters[best_i + 1]
        merged[best_i] = True
        del clusters[best_i + 1]
        del merged[best_i + 1]
    plans = []
    for i in range(days):
        if i < len(clusters):
            stops = clusters[i]
            note = "빡빡한 일정" if len(stops) > MAX_STOPS_PER_DAY else ""
            plans.append(DayPlan(day=i + 1, stops=stops, note=note,
                                 merged=merged[i]))
        else:
            plans.append(DayPlan(day=i + 1, stops=[], note="자유 일정"))
    return plans


def budget_summary(settings: TripSettings,
                   expenses: dict[str, int]) -> dict[str, int]:
    """예산 사용 현황.

    항공료 '미포함'이면 항공료는 보여주되 예산 차감에서는 뺀다.
    반환: total/per_person/per_day/spent/remaining (전부 원).
    """
    spent = sum(max(0, int(v)) for v in expenses.values())
    counted = spent if settings.includes_airfare else spent - max(0, int(expenses.get("airfare", 0)))
    return {
        "total": settings.total_budget,
        "per_person": settings.per_person_budget,
        "per_day": settings.per_day_budget,
        "spent": counted,
        "remaining": settings.total_budget - counted,
    }
