"""공유용 일정표 만들기 (2026-10-30, WhatsApp 요청).

사용자 요청: 일정 초안을 날짜·시간·장소(링크)·설명·교통·비용 표로 보여주고,
동행인에게 보낼 수 있는 파일(PDF)로 내보내기.

정직성 원칙 (1단계 범위):
- 실제 이동시간·교통편·운영시간은 아직 구현하지 않았다 (2단계 작업).
  그래서 시간 칸은 오전/오후/저녁 같은 거친 추정만, 교통 칸은
  직선거리와 '차량 평균 30km/h' 가정의 추정치만 담고, 추정임을 표시한다.
- 장소별 비용 데이터는 앱에 없다. 비용 칸은 사용자가 직접 적는 칸이고,
  비워 두면 "—"로 나간다.

화면(Streamlit)과 PDF(src/pdf_export.py)가 같은 행 데이터를 쓰도록
여기서 순수 데이터(ItineraryRow)만 만든다. 외부 API는 부르지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .models import Candidate, FilmLocation
from .trip import DayPlan, TripSettings

# 하루를 나누는 거친 시간대. 시각(몇 시)은 지어내지 않는다.
TIME_SLOTS = ("오전", "오후", "저녁")

# 교통 추정에 쓰는 차량 평균 속도 (도심·관광지 이동 가정, 렌터카 전제는
# 모듈 3/4와 같다). 실제 소요시간이 아니라 하한에 가까운 참고치다.
ASSUMED_SPEED_KMH = 30.0

# 비용·교통 칸을 채울 수 없을 때 표시
EMPTY = "—"

_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


@dataclass
class ItineraryRow:
    """일정표의 한 행 (방문 장소 1곳)."""
    date: str          # "11월 1일 (토)"
    time: str          # "오전" | "오후" | "저녁" (추정)
    place: str         # 장소명
    link: str          # Google 지도 등 웹페이지 링크 (없으면 빈 문자열)
    description: str   # 카테고리 · 주소 (+ 촬영지는 근거 확인 안내)
    transport: str     # 직전 장소로부터의 추정 이동, 하루 첫 방문은 "—"
    cost: int | None = None   # 사용자가 화면에서 적는 칸 (원)


def assign_time_slots(n_stops: int) -> list[str]:
    """하루 방문 수에 따라 오전/오후/저녁을 고르게 배정한다.

    1곳이면 오전, 2곳이면 오전·오후, 3곳이면 오전·오후·저녁.
    4곳 이상(빡빡한 날)이면 앞에서부터 고르게 나눈다.
    """
    if n_stops < 1:
        return []
    if n_stops == 1:
        return ["오전"]
    if n_stops == 2:
        return ["오전", "오후"]
    return [TIME_SLOTS[min(i * 3 // n_stops, 2)] for i in range(n_stops)]


def format_date(d: date) -> str:
    """"11월 1일 (토)" 형태."""
    return f"{d.month}월 {d.day}일 ({_WEEKDAYS[d.weekday()]})"


def transport_estimate(prev: FilmLocation | None,
                       cur: FilmLocation,
                       haversine_m,
                       mode: str = "rental_car") -> str:
    """직전 장소에서 이동하는 데 대한 추정 문자열.

    렌트카는 직선거리와 ASSUMED_SPEED_KMH 가정으로 계산한 참고치를 보여준다.
    실제 도로 거리·교통편·대기 시간은 반영하지 않으므로 반드시 '추정'으로
    표시한다. 가이드 투어·대중교통은 소요시간을 계산할 근거가 없어
    (투어 일정표·노선도가 필요) 시간 숫자를 지어내지 않고 '확인 필요'로
    표시한다 — 정직성 원칙.
    하루 첫 방문(숙소 등 출발지를 모름)이면 추정할 수 없어 "—".
    """
    if prev is None:
        return EMPTY
    dist_m = haversine_m(prev.lat, prev.lon, cur.lat, cur.lon)
    km = dist_m / 1000.0
    dist_txt = f"{km:.1f}km" if km >= 1 else f"{int(round(dist_m, -1))}m"
    if mode == "guided_tour":
        return f"직선 {dist_txt} · 투어 이동 (시간은 투어 일정 확인)"
    if mode == "transit":
        return f"직선 {dist_txt} · 대중교통 (소요시간 확인 필요)"
    minutes = max(5, round((km / ASSUMED_SPEED_KMH) * 60 / 5) * 5)
    if minutes >= 60:
        dur = f"약 {minutes // 60}시간"
        if minutes % 60:
            dur += f" {minutes % 60}분"
    else:
        dur = f"약 {minutes}분"
    return f"직선 {dist_txt} · 차 {dur} (추정)"


def describe(category_key: str, loc: FilmLocation, category_label) -> str:
    """설명 칸: 카테고리 · 주소. 촬영지는 근거 확인 안내를 붙인다."""
    if category_key == "film":
        cat = "영화 촬영지 (어떤 영화인지는 근거 링크 확인)"
    else:
        cat = category_label(category_key)
    return f"{cat} · {loc.address}"


def build_rows(days: list[DayPlan],
               extras: dict[int, list[Candidate]],
               trip: TripSettings,
               category_of,
               category_label,
               haversine_m,
               lodging=None) -> list[ItineraryRow]:
    """일정 초안(DayPlan 목록)을 공유용 일정표 행으로 펼친다.

    days: src.trip.build_itinerary 결과.
    extras: src.candidates.collect_spare 결과 (빈 날에 채운 후보).
    category_of: 장소명 → 카테고리 키 함수 (배정된 후보는 원래 카테고리가
                 FilmLocation에 남지 않아서 이름으로 다시 찾는다).
    category_label: 카테고리 키 → 화면 라벨 함수.
    haversine_m: 직선거리 함수 (테스트에서 가짜로 바꿀 수 있게 인자로 받는다).
    lodging: 고른 숙소 (name·address·google_maps_uri를 가진 객체) 또는 None.
             주면 박 수마다 그 날 마지막에 '숙박' 행을 넣는다.
    """
    rows: list[ItineraryRow] = []
    mode = getattr(trip, "transport_mode", "rental_car")
    for day in days:
        day_date = trip.start_date + timedelta(days=day.day - 1)
        date_txt = format_date(day_date)
        # 하루의 방문 목록: (장소, 카테고리 키, 채우기 여부)
        stops: list[tuple[FilmLocation, str, bool]] = []
        for loc in day.stops:
            stops.append((loc, category_of(loc.name), False))
        if not day.stops:
            for c in extras.get(day.day) or []:
                stops.append((_candidate_as_location(c), c.category, True))
        if not stops:
            # 빈 날도 표에 한 줄 보여준다 (공유한 일정표에서 날짜가
            # 통째로 빠지면 동행인이 헷갈린다)
            rows.append(ItineraryRow(
                date=date_txt, time=EMPTY, place="자유 일정", link="",
                description="배정된 후보가 없어요", transport=EMPTY))
            _append_lodging_row(rows, lodging, trip, day, date_txt)
            continue
        slots = assign_time_slots(len(stops))
        prev: FilmLocation | None = None
        for (loc, cat_key, filled), slot in zip(stops, slots):
            desc_bits = []
            if day.note and day.note != "자유 일정":
                desc_bits.append(f"[{day.note}]")
            if filled:
                desc_bits.append("[남은 후보 채우기]")
            desc_bits.append(describe(cat_key, loc, category_label))
            rows.append(ItineraryRow(
                date=date_txt,
                time=slot,
                place=loc.name,
                link=(loc.google_maps_uri or ""),
                description=" ".join(desc_bits),
                transport=transport_estimate(prev, loc, haversine_m, mode),
            ))
            prev = loc
        _append_lodging_row(rows, lodging, trip, day, date_txt)
    return rows


def _append_lodging_row(rows: list[ItineraryRow], lodging,
                        trip: TripSettings, day: DayPlan, date_txt: str) -> None:
    """숙소를 골랐으면 그 날 밤의 숙박 행을 넣는다.

    마지막 날은 체크아웃이라 숙박이 없다 (박 수 = 일수 - 1). 자유 일정인
    날에도 그 날 밤은 숙소에서 자므로 행을 넣는다.
    """
    if lodging is None or day.day > trip.nights:
        return
    rows.append(ItineraryRow(
        date=date_txt,
        time="숙박",
        place=lodging.name,
        link=(getattr(lodging, "google_maps_uri", None) or ""),
        description=f"숙소 · {lodging.address} ({day.day}박째)",
        transport=EMPTY,
    ))


def budget_lines(trip: TripSettings,
                 summary: dict[str, int] | None) -> list[str]:
    """PDF에 넣을 예산 요약 문장들. 예산 미입력이면 안내 한 줄."""
    if trip.budget_amount <= 0 or summary is None:
        return ["예산을 입력하지 않았어요."]
    basis = "1인 기준" if trip.budget_basis == "per_person" else "전체 기준"
    basis += " · 항공료 포함" if trip.includes_airfare else " · 항공료 별도"
    lines = [
        f"입력 예산: {trip.budget_amount:,}원 ({basis})",
        f"전체 예산 {summary['total']:,}원 · 1인당 {summary['per_person']:,}원 "
        f"· 하루당 {summary['per_day']:,}원",
        f"예상 지출 합계 {summary['spent']:,}원 → 남은 예산 "
        f"{summary['remaining']:,}원",
    ]
    if summary["remaining"] < 0:
        lines.append("주의: 예상 지출이 예산을 넘었어요.")
    return lines


def _candidate_as_location(c: Candidate) -> FilmLocation:
    """채우기 후보(Candidate)를 표 행에 쓸 FilmLocation 형태로 바꾼다.

    src.candidates.candidate_to_film_location과 같은 변환이지만 순환
    임포트를 피하려고 필요한 필드만 여기서 옮긴다.
    """
    return FilmLocation(
        name=c.place.name,
        address=c.place.address,
        lat=c.place.lat,
        lon=c.place.lon,
        source="film" if c.film else "places",
        source_id=c.place.place_id,
        source_urls=list(c.source_urls),
        confidence=c.confidence if c.confidence is not None else 0.0,
        google_maps_uri=c.place.google_maps_uri,
    )
