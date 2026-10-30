"""장소 중심 여행 스케줄러 — 1단계 (여행지 입력 + 관심사 명소 후보 수집).

실행: streamlit run app.py
키 설정: .streamlit/secrets.toml (secrets.toml.example 참고)

흐름:
  1) 여행지(도시/지역)를 찾아 확정한다
  2) 관심사(맛집·자연/트래킹·역사·박물관/미술관·쇼핑·액티비티)를 골라
     명소 후보를 모은다. 켜 두면 웹 검색으로 이 지역 영화 촬영지도 찾는다.
  3) 고른 후보를 날짜·인원·동행인·예산에 맞춰 하루 단위 초안으로 묶는다.

2026-10-28 개편 (사용자 합의, WhatsApp):
- 영화 먼저가 아니라 여행지 먼저. 영화 촬영지는 여행지 명소를 찾는 과정에서
  발견되면 근거 링크와 함께 후보에 넣는다 (앱이 영화와의 연결을 지어내지 않는다).
- 해외 여행 먼저. 국내는 카카오 키가 필요해 나중에.
- 예산은 기존 수동 입력 유지 (자동 견적은 아직).
- 기존 영화 우선 흐름(모듈 1·2) 코드는 src/pipeline.py·src/movie_search.py에
  그대로 남겨 뒀고, 메인 화면에서는 뺐다 (영화 테마로 재배치할 예정).
- 실제 이동시간·운영시간을 반영한 시간표는 2단계 작업이라 아직 없다.
  일정 초안은 기존처럼 직선거리 묶음이고, 그 한계를 화면에 그대로 표시한다.

2026-10-30 추가 (사용자 요청, WhatsApp):
- 이동 수단 고르기: 렌트카·가이드 투어·대중교통. 일정표의 이동 칸 문구와
  예산 지출 항목(렌터카/투어 비용/교통비)에 반영한다. 실제 소요시간 계산은
  2단계라 렌트카 외에는 시간을 지어내지 않는다.
- 숙소 고르기: Places Nearby Search(lodging) 1회로 여행지 주변 숙소 후보를
  찾아 고르면, 공유용 일정표·PDF에 박 수마다 '숙박' 행으로 들어간다.
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from src.candidates import (CATEGORIES, FILM_CATEGORY, FILM_LABEL, Candidate,
                            candidate_to_film_location, collect_spare,
                            find_candidates, find_destination,
                            find_film_candidates, find_lodging)
from src.config import load_settings
from src.errors import AuthError, RateLimitError, SourceError
from src.models import CandidateSet, ResolvedPlace
from src.sources.brave_client import BraveSearchClient
from src.sources.gplaces import GooglePlacesClient
from src.sources.tavily_client import TavilyClient
from src.nearby import haversine_m
from src.itinerary import EMPTY, build_rows, budget_lines, format_date
from src.pdf_export import FONT_HELP, build_pdf, find_fonts
from src.trip import (BUDGET_BASIS_LABELS, EXPENSE_CATEGORIES,
                      TRANSPORT_MODES, TripSettings, budget_summary,
                      build_itinerary, plan_inputs_match,
                      transport_expense_label, validate_settings)

st.set_page_config(page_title="장소 중심 여행 스케줄러", page_icon="🧭")
st.title("🧭 장소 중심 여행 스케줄러")
st.caption("여행지를 고르면 관심사 명소 후보를 모으고, 고른 후보로 "
           "날짜·인원·예산에 맞춘 일정 초안을 만들어요. "
           "실제 이동시간·운영시간을 반영한 시간표는 다음 단계에서 만들 예정이에요.")

settings = load_settings()


@st.cache_resource
def get_clients(tavily_key, brave_key, places_key):
    """API 클라이언트들. 키가 없는 건 None."""
    return {
        "tavily": TavilyClient(tavily_key) if tavily_key else None,
        "brave": BraveSearchClient(brave_key) if brave_key else None,
        "places": GooglePlacesClient(places_key) if places_key else None,
    }


clients = get_clients(settings.tavily_api_key, settings.brave_api_key,
                      settings.google_places_api_key)

if clients["places"] is None:
    st.warning("GOOGLE_PLACES_API_KEY가 없어요 — 여행지 확인과 명소 검색에 꼭 "
               "필요해요. .streamlit/secrets.toml 또는 배포 환경의 Secrets에 "
               "넣어 주세요.")
if clients["brave"] is None and clients["tavily"] is None:
    st.info("BRAVE_API_KEY·TAVILY_API_KEY가 없으면 영화 촬영지 찾기는 "
            "건너뛰어요. (웹 검색으로 촬영지를 찾는 기능이라 키가 필요해요)")


def confidence_badge(c: float) -> str:
    if c >= 0.8:
        return "🟢 높음"
    if c >= 0.5:
        return "🟡 보통"
    return "🔴 낮음"


def _fmt_km(distance_m: float) -> str:
    return f"{distance_m/1000:.1f}km" if distance_m >= 1000 else f"{int(distance_m)}m"


def _maps_link(place: ResolvedPlace) -> str:
    """장소의 지도 링크. API가 googleMapsUri를 주면 그걸, 아니면 좌표 링크."""
    return (place.google_maps_uri
            or f"https://www.google.com/maps/search/?api=1&query={place.lat},{place.lon}")


def _category_label(cat: str) -> str:
    return FILM_LABEL if cat == FILM_CATEGORY else CATEGORIES[cat]["label"]


# === 1. 여행지 고르기 =====================================================

st.header("1️⃣ 여행지 고르기")
dest_q = st.text_input("여행지 (도시·지역 — 지금은 해외 여행 기준이에요)",
                       placeholder="예: 오사카, 다낭, 방콕, 파리",
                       key="dest_query")
if st.button("여행지 찾기", disabled=not dest_q.strip()
             or clients["places"] is None, key="dest_search"):
    try:
        with st.spinner("여행지를 확인하는 중… (Places 1회)"):
            st.session_state["dest_choices"] = find_destination(
                dest_q.strip(), clients["places"])
    except (AuthError, RateLimitError, SourceError) as exc:
        st.error(f"여행지 검색 실패: {exc}")

choices: list[ResolvedPlace] = st.session_state.get("dest_choices") or []
if choices:
    if not st.session_state.get("destination"):
        st.caption("맞는 여행지를 골라 주세요.")
    for c in choices:
        with st.container(border=True):
            st.markdown(f"**{c.name}**")
            st.caption(c.address)
            st.markdown(f"[Google 지도에서 보기]({_maps_link(c)})")
            if st.button("이 여행지로 정하기", key=f"dest_pick_{c.place_id}"):
                prev = st.session_state.get("destination")
                if prev is None or prev.place_id != c.place_id:
                    # 여행지가 바뀌면 기존 후보·숙소·일정은 다른 지역 기준이라 지운다
                    for k in ("cand_set", "trip_plan", "lodging_choices",
                              "lodging_pick"):
                        st.session_state.pop(k, None)
                st.session_state["destination"] = c

destination: ResolvedPlace | None = st.session_state.get("destination")
if destination:
    st.success(f"✅ 여행지: {destination.name} — {destination.address}")


# === 2. 관심사 명소 후보 찾기 ==============================================

def run_candidate_search(destination: ResolvedPlace, categories: list[str],
                         radius_km: float, film_on: bool) -> None:
    """버튼을 눌렀을 때만 외부 API를 부른다 (비용 원칙)."""
    candidates: list[Candidate] = []
    warnings: list[str] = []
    places_calls = 0
    web_calls = 0
    try:
        with st.spinner("명소 후보를 찾는 중…"):
            found, w, n = find_candidates(
                destination, clients["places"], categories,
                radius_m=radius_km * 1000)
            candidates += found
            warnings += w
            places_calls += n
            if film_on:
                films, w2, np_, nw = find_film_candidates(
                    destination, clients["brave"], clients["tavily"],
                    clients["places"], radius_m=radius_km * 1000)
                candidates += films
                warnings += w2
                places_calls += np_
                web_calls += nw
        st.session_state["cand_set"] = CandidateSet(
            destination=destination, candidates=candidates,
            warnings=warnings, places_calls=places_calls, web_calls=web_calls)
        # 새 후보 검색이면 이전 일정 초안은 다른 후보 기준이라 지운다
        st.session_state.pop("trip_plan", None)
    except (AuthError, RateLimitError, SourceError) as exc:
        st.error(f"후보 검색 실패: {exc}")


st.header("2️⃣ 관심사 명소 후보 찾기")
cat_keys = list(CATEGORIES.keys())
picked_cats = st.multiselect(
    "관심사", options=cat_keys, default=cat_keys,
    format_func=lambda k: CATEGORIES[k]["label"], key="interest_cats")
radius_km = st.slider("검색 반경 (km)", min_value=1, max_value=30, value=10,
                      help="렌터카 이동 기준 기본 10km예요.", key="cand_radius")
can_film = clients["brave"] is not None or clients["tavily"] is not None
film_on = st.checkbox(
    "🎬 이 지역의 영화 촬영지도 함께 찾기",
    value=True, disabled=not can_film, key="film_on",
    help="웹 검색(Brave/Tavily)으로 이 지역 촬영지 언급을 찾고 "
         "Google Places로 확인해요. 찾은 곳은 근거 링크와 함께 후보에 넣어요.")
web_extra = (" + 웹 검색 최대 5회·장소 확인 최대 6회"
             if (film_on and can_film) else "")
st.caption(f"후보 찾기 1회 = Places {len(picked_cats)}회 (카테고리당 1회){web_extra}. "
           "버튼을 눌렀을 때만 검색해요.")
if st.button("명소 후보 찾기", type="primary", key="cand_search",
             disabled=destination is None or not picked_cats
             or clients["places"] is None):
    run_candidate_search(destination, picked_cats, radius_km,
                         film_on and can_film)

cand_set: CandidateSet | None = st.session_state.get("cand_set")
if cand_set:
    for w in cand_set.warnings:
        st.warning(w)
    if not cand_set.candidates:
        st.info("조건에 맞는 후보를 찾지 못했어요. 반경을 넓히거나 "
                "관심사를 바꿔 보세요.")
    else:
        n_film = sum(1 for c in cand_set.candidates if c.film)
        cost_bits = [f"Places {cand_set.places_calls}회"]
        if cand_set.web_calls:
            cost_bits.append(f"웹 검색 {cand_set.web_calls}회")
        film_txt = f" (영화 촬영지 {n_film}곳 포함)" if n_film else ""
        st.subheader(f"명소 후보 {len(cand_set.candidates)}곳{film_txt}")
        st.caption(f"이번 검색 호출: {', '.join(cost_bits)}")
        st.map([{"lat": c.place.lat, "lon": c.place.lon}
                for c in cand_set.candidates])
        by_cat: dict[str, list[Candidate]] = {}
        for c in cand_set.candidates:
            by_cat.setdefault(c.category, []).append(c)
        for cat in list(CATEGORIES.keys()) + [FILM_CATEGORY]:
            items = by_cat.get(cat)
            if not items:
                continue
            with st.expander(f"{_category_label(cat)} {len(items)}곳",
                             expanded=True):
                if cat == FILM_CATEGORY:
                    st.caption("웹에서 영화 촬영지로 소개된 곳이에요. "
                               "어떤 영화와 이어지는지는 근거 링크에서 꼭 "
                               "확인해 주세요.")
                for c in items:
                    line = f"{c.place.name} ({_fmt_km(c.distance_m)})"
                    if c.film and c.confidence is not None:
                        line += f" · 신뢰도 {confidence_badge(c.confidence)}"
                    st.markdown(f"- [{line}]({_maps_link(c.place)})")
                    st.caption(c.place.address)
                    if c.film and c.source_urls:
                        st.caption("근거: " + ", ".join(
                            f"[링크{i+1}]({u})"
                            for i, u in enumerate(c.source_urls)))


# === 3. 여행 계획 세우기 (모듈 4 재사용) =====================================

def lodging_section(cand_set: CandidateSet):
    """숙소 고르기 (선택). 고른 숙소(ResolvedPlace) 또는 None을 돌려준다.

    2026-10-30 추가: 이 사용자의 여행은 숙소를 정하고 움직이는 편이라,
    일정표에 숙소를 박 수로 표시한다. 검색은 버튼을 눌렀을 때만 Places
    Nearby Search(lodging) 1회 — 비용 원칙은 후보 찾기와 같다.
    """
    st.markdown("**🏨 숙소 (선택)**")
    if st.button("숙소 후보 찾기", key="lodging_search",
                 disabled=clients["places"] is None,
                 help=f"여행지 중심으로 Places Nearby Search 1회 "
                      f"(lodging 타입, 반경은 2단계의 검색 반경과 같아요)."):
        try:
            with st.spinner("숙소 후보를 찾는 중… (Places 1회)"):
                found, w, _n = find_lodging(
                    cand_set.destination, clients["places"],
                    radius_m=st.session_state.get("cand_radius", 10) * 1000)
            st.session_state["lodging_choices"] = found
            for m in w:
                st.warning(m)
        except (AuthError, RateLimitError, SourceError) as exc:
            st.error(f"숙소 검색 실패: {exc}")
    lodging_choices: list[ResolvedPlace] =         st.session_state.get("lodging_choices") or []
    if not lodging_choices:
        st.caption("숙소를 정하면 일정표와 PDF에 박 수마다 숙박이 표시돼요. "
                   "아직이면 비워 둬도 돼요.")
        return None
    options = ["아직 안 정함"] + [p.name for p in lodging_choices]
    picked = st.radio("숙소 고르기 (여행지에서 가까운 순)", options=options,
                      key="lodging_pick",
                      help="거리순 목록이에요. 가격·평점 데이터는 아직 "
                           "가져오지 않아서(과금 등급) 가까운 순으로만 "
                           "보여줘요.")
    if picked and picked != "아직 안 정함":
        for pl in lodging_choices:
            if pl.name == picked:
                st.caption(f"숙소: [{pl.name}]({_maps_link(pl)}) — {pl.address}")
                return pl
    return None


def trip_section(cand_set: CandidateSet) -> None:
    """고른 후보를 날짜·인원·동행인·예산에 맞춰 하루 단위 초안으로 묶는다.

    외부 API를 부르지 않는다 — 화면 입력값과 이미 찾은 후보만 쓴다.
    '일정 초안 만들기'를 눌러 세션에 저장하면 위젯 조작으로 재실행돼도
    아래에서 다시 그려진다 (주변 찾기 버그 수정과 같은 방식).
    """
    candidates = cand_set.candidates
    all_names = [c.place.name for c in candidates]
    # 맛집은 하루 일정 항목이 아니라 식사 옵션이라 기본 선택에서 뺀다
    default_picks = [c.place.name for c in candidates
                     if c.category != "restaurants"]
    dates_in = st.date_input("여행 날짜",
                             value=(date.today() + timedelta(days=30),
                                    date.today() + timedelta(days=33)),
                             key="trip_dates")
    party_in = st.number_input("인원 (본인 포함)", min_value=1, max_value=20,
                               value=2, key="trip_party")
    companions_in = st.text_input("동행인 (쉼표로 구분, 비워 둬도 돼요)",
                                  key="trip_companions")
    budget_in = st.number_input("여행 예산 (원, 0이면 미정)", min_value=0,
                                step=100000,
                                help="0이면 예산 없이 일정 초안만 만들어요.",
                                key="trip_budget")
    basis_in = st.radio("예산 기준", options=["total", "per_person"],
                        format_func=lambda k: BUDGET_BASIS_LABELS[k],
                        horizontal=True, key="trip_basis")
    airfare_in = st.checkbox("예산에 항공료 포함", value=True,
                             key="trip_airfare")
    picks_in = st.multiselect("일정에 넣을 후보", options=all_names,
                              default=default_picks, key="trip_picks")
    st.caption("맛집은 식사 옵션이라 기본 선택에서는 뺐어요. "
               "일정에 넣고 싶으면 직접 골라 주세요.")
    transport_in = st.radio(
        "이동 수단", options=list(TRANSPORT_MODES.keys()),
        format_func=lambda k: TRANSPORT_MODES[k], horizontal=True,
        key="trip_transport",
        help="일정표의 이동 안내가 고른 수단 기준으로 바뀌어요. 실제 "
             "소요시간 계산은 2단계 작업이라, 렌트카 외에는 시간 대신 "
             "'확인 필요'로 표시해요.")
    lodging_obj = lodging_section(cand_set)
    if st.button("일정 초안 만들기", type="primary", key="trip_make"):
        dates = (tuple(dates_in) if isinstance(dates_in, (tuple, list))
                 else (dates_in,))
        if len(dates) != 2:
            st.error("출발일과 귀국일을 모두 골라 주세요.")
        else:
            companions = tuple(n.strip() for n in companions_in.split(",")
                               if n.strip())
            trip = TripSettings(party_size=int(party_in),
                                start_date=dates[0], end_date=dates[1],
                                budget_amount=int(budget_in),
                                budget_basis=basis_in,
                                includes_airfare=bool(airfare_in),
                                companions=companions,
                                transport_mode=transport_in)
            problems = validate_settings(trip)
            if problems:
                for p in problems:
                    st.error(p)
            else:
                by_name = {c.place.name: c for c in candidates}
                picked = [candidate_to_film_location(by_name[n])
                          for n in picks_in if n in by_name]
                # 일정표 편집(비용 칸) 키를 새로 시작해 이전 초안의
                # 편집값이 새 초안 행에 잘못 붙지 않게 한다
                seq = st.session_state.get("plan_seq", 0) + 1
                st.session_state["plan_seq"] = seq
                st.session_state["trip_plan"] = {
                    "settings": trip,
                    "days": build_itinerary(picked, trip.days),
                    "picks": tuple(picks_in),
                    "lodging": lodging_obj,
                    "seq": seq,
                }
    plan = st.session_state.get("trip_plan")
    if plan:
        show_trip_plan(plan, cand_set)


def show_trip_plan(plan, cand_set: CandidateSet) -> None:
    trip: TripSettings = plan["settings"]
    lodging_choices = st.session_state.get("lodging_choices") or []
    lodging_now = st.session_state.get("lodging_pick")
    if lodging_now in (None, "아직 안 정함"):
        lodging_now = None
    saved_lodging = plan.get("lodging")
    current = {
        "dates": st.session_state.get("trip_dates"),
        "party": st.session_state.get("trip_party"),
        "budget": st.session_state.get("trip_budget"),
        "basis": st.session_state.get("trip_basis"),
        "airfare": st.session_state.get("trip_airfare"),
        "companions": st.session_state.get("trip_companions"),
        "picks": st.session_state.get("trip_picks") or [],
        "transport": st.session_state.get("trip_transport"),
        "lodging": lodging_now,
    }
    st.markdown(f"### 🧳 일정 초안 — {trip.start_date:%m월 %d일} ~ "
                f"{trip.end_date:%m월 %d일} "
                f"({trip.nights}박 {trip.days}일, {trip.party_size}명)")
    mode_label = TRANSPORT_MODES.get(trip.transport_mode, trip.transport_mode)
    lodging_label = (f"[{saved_lodging.name}]({_maps_link(saved_lodging)})"
                     if saved_lodging is not None else "미정")
    st.caption(f"이동 수단: **{mode_label}** · 숙소: {lodging_label}")
    if not plan_inputs_match(trip, plan.get("picks"), current,
                             saved_lodging=(saved_lodging.name
                                            if saved_lodging else None)):
        st.warning("아래 초안은 **이전 입력** 기준이에요 — 바뀐 "
                   "날짜·인원·예산·후보·이동 수단·숙소는 아직 반영되지 "
                   "않았어요. '일정 초안 만들기'를 다시 눌러 주세요.")
    st.caption("초안은 **직선거리**로 가까운 곳끼리 묶은 거예요. "
               "실제 이동 시간·교통편·운영시간은 아직 반영하지 않았어요 "
               "(2단계 작업).")
    extras = collect_spare(plan["days"], cand_set.candidates)
    for day in plan["days"]:
        extra = extras.get(day.day) or []
        note = day.note
        if not day.stops and extra:
            note = "남은 후보 채우기"
        label = f"{day.day}일차" + (f" — {note}" if note else "")
        with st.expander(label, expanded=True):
            if day.merged:
                st.warning("일수에 맞추느라 멀리 떨어진 곳을 같은 날에 넣었어요. "
                           "이동 시간을 확인하지 않은 조합이라 하루에 다 보기 "
                           "어려울 수 있어요.")
            if not day.stops:
                if extra:
                    st.caption("일정이 남는 날이라, 고르지 않은 후보를 "
                               "채웠어요 (추가 검색 없음).")
                    for c in extra:
                        st.markdown(
                            f"- [{c.place.name}]({_maps_link(c.place)}) "
                            f"({_category_label(c.category)})")
                        st.caption(c.place.address)
                else:
                    st.caption("배정된 후보가 없어요. 남은 후보도 없어 "
                               "비워 뒀어요.")
            for loc in day.stops:
                st.markdown(f"- **{loc.name}**")
                st.caption(loc.address)
                if loc.google_maps_uri:
                    st.markdown(f"  [Google 지도에서 보기]({loc.google_maps_uri})")
    restaurants = [c for c in cand_set.candidates
                   if c.category == "restaurants"]
    if restaurants:
        with st.expander(f"🍜 맛집 후보 {len(restaurants)}곳 (식사 옵션)"):
            for c in restaurants:
                st.markdown(f"- [{c.place.name} "
                            f"({_fmt_km(c.distance_m)})]({_maps_link(c.place)})")
                st.caption(c.place.address)

    summary = None
    if trip.budget_amount <= 0:
        st.caption("예산을 입력하지 않아 예산 가늠은 생략했어요.")
        share_section(plan, cand_set, extras, summary)
        return
    st.markdown("**💰 예산 가늠**")
    basis_txt = BUDGET_BASIS_LABELS[trip.budget_basis]
    basis_txt += " · 항공료 포함" if trip.includes_airfare else " · 항공료 별도"
    st.caption(f"입력 예산 {trip.budget_amount:,}원 ({basis_txt}).")
    st.caption("예상 지출은 **일행 전원의 여행 전체 기간 합계**로 넣어 주세요 — "
               "예산 총액과 비교해요. 빈 칸(0원)은 무료가 아니라 "
               "아직 입력하지 않은 항목이에요.")
    expenses = {}
    cols = st.columns(3)
    for i, (key, label) in enumerate(EXPENSE_CATEGORIES):
        if key == "car":
            # 이동 수단에 맞춘 지출 항목 이름 (렌터카/투어 비용/교통비)
            label = transport_expense_label(trip.transport_mode)
        with cols[i % 3]:
            expenses[key] = st.number_input(label, min_value=0, step=10000,
                                            value=0, key=f"trip_exp_{key}")
    summary = budget_summary(trip, expenses)
    c1, c2, c3 = st.columns(3)
    c1.metric("전체 예산", f"{summary['total']:,}원")
    c2.metric("1인당", f"{summary['per_person']:,}원")
    c3.metric("하루당", f"{summary['per_day']:,}원")
    st.caption(f"예상 지출 합계 {summary['spent']:,}원 → "
               f"남은 예산 **{summary['remaining']:,}원**")
    if summary["remaining"] < 0:
        st.warning("예상 지출이 예산을 넘었어요. 일정이나 항목을 조정해 보세요.")
    share_section(plan, cand_set, extras, summary)


def share_section(plan, cand_set: CandidateSet, extras, summary) -> None:
    """공유용 일정표 (날짜·시간·장소·설명·교통·비용) + PDF 내보내기.

    2026-10-30 WhatsApp 요청: 결과를 표로 예쁘게 보여주고 동행인에게
    보낼 파일로 내보내기. 시간·교통은 2단계 전까지 추정이라 추정임을
    표시하고, 비용은 앱에 데이터가 없어 사용자가 직접 적는 칸이다.
    """
    trip: TripSettings = plan["settings"]
    category_of = {c.place.name: c.category for c in cand_set.candidates}
    lodging = plan.get("lodging")
    rows = build_rows(plan["days"], extras, trip, category_of.get,
                      _category_label, haversine_m, lodging=lodging)
    st.markdown("### 📋 공유용 일정표")
    st.caption("시간(오전/오후/저녁)과 이동은 **직선거리 기준 추정**이에요 — "
               "실제 교통편·소요시간·운영시간은 꼭 확인해 주세요. "
               "비용 칸은 눌러서 직접 적을 수 있어요 (PDF에도 반영돼요).")
    if not rows:
        st.caption("일정에 넣은 장소가 없어요.")
        return
    seq = plan.get("seq", 0)
    # 비용은 숫자 칸으로 두면 빈 칸이 'None'으로 보여(이 Streamlit 버전)
    # 텍스트 칸으로 두고 숫자만 받는다
    import pandas as pd
    data = pd.DataFrame(
        [{"날짜": r.date, "시간 (추정)": r.time, "장소": r.place,
          "링크": (r.link or ""), "설명": r.description,
          "이동 (추정)": r.transport,
          "비용 (원)": (str(r.cost) if r.cost is not None else "")}
         for r in rows])
    edited = st.data_editor(
        data, key=f"itin_editor_{seq}", hide_index=True,
        disabled=["날짜", "시간 (추정)", "장소", "링크", "설명", "이동 (추정)"],
        column_config={
            "날짜": st.column_config.TextColumn(width=100),
            "시간 (추정)": st.column_config.TextColumn(width=60),
            "장소": st.column_config.TextColumn(width=100),
            "링크": st.column_config.LinkColumn(width=70,
                                               display_text="지도 열기"),
            "설명": st.column_config.TextColumn(width=180),
            "이동 (추정)": st.column_config.TextColumn(width=130),
            "비용 (원)": st.column_config.TextColumn(
                width=80,
                help="장소별 예상 비용을 직접 적는 칸이에요. "
                     "숫자만 적어 주세요 (예: 1500)."),
        })
    # 화면에서 적은 비용을 행 데이터에 반영한다 (PDF에 들어간다)
    edited_records = (edited.to_dict("records")
                      if hasattr(edited, "to_dict") else edited)
    for r, e in zip(rows, edited_records):
        digits = "".join(ch for ch in str(e.get("비용 (원)") or "")
                         if ch.isdigit())
        r.cost = int(digits) if digits else None

    regular, _bold = find_fonts()
    if regular is None:
        st.warning(FONT_HELP)
        return
    dest = cand_set.destination
    title = f"{dest.name} {trip.nights}박 {trip.days}일 여행 일정 (초안)"
    info = [f"{trip.start_date.year}년 {format_date(trip.start_date)} ~ "
            f"{format_date(trip.end_date)} "
            f"({trip.nights}박 {trip.days}일, {trip.party_size}명)"]
    if trip.companions:
        info.append("동행인: " + ", ".join(trip.companions))
    info.append(f"이동 수단: {TRANSPORT_MODES.get(trip.transport_mode, trip.transport_mode)}")
    if lodging is not None:
        info.append(f"숙소: {lodging.name} — {lodging.address}")
    notes = ["시간(오전/오후/저녁)과 이동 거리·시간은 직선거리 기준 "
             "추정이에요. 실제 교통편·소요시간·운영시간은 확인이 필요해요.",
             f"이동 칸은 {TRANSPORT_MODES.get(trip.transport_mode, trip.transport_mode)} "
             "기준 표시예요. 투어·대중교통은 소요시간을 계산하지 않아 "
             "'확인 필요'로 적었어요.",
             "비용은 일정표에 직접 적은 값만 표시돼요."]
    merged_days = [d.day for d in plan["days"] if d.merged]
    if merged_days:
        notes.append(f"{', '.join(map(str, merged_days))}일차는 일수에 "
                     "맞추느라 먼 곳끼리 합친 날이라 이동이 길 수 있어요.")
    notes.append("CineMap 일정 초안 — 장소는 Google Places·웹 검색 기준이에요.")
    restaurants = [c for c in cand_set.candidates
                   if c.category == "restaurants"]
    try:
        pdf_bytes = build_pdf(
            title=title, info_lines=info, note_lines=notes, rows=rows,
            restaurants=[(c.place.name, _maps_link(c.place))
                         for c in restaurants],
            budget=budget_lines(trip, summary))
    except ImportError:
        st.warning("PDF를 만들려면 fpdf2가 필요해요: pip install fpdf2")
        return
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    st.download_button("📄 PDF로 내보내기 (동행인에게 공유)",
                       data=pdf_bytes,
                       file_name=f"cinemap-{dest.name}-"
                                 f"{trip.start_date:%m%d}-{trip.end_date:%m%d}.pdf",
                       mime="application/pdf",
                       key=f"pdf_dl_{seq}")


st.header("3️⃣ 여행 계획 세우기")
if not cand_set or not cand_set.candidates:
    st.caption("명소 후보를 찾으면 일정 초안을 만들 수 있어요.")
else:
    trip_section(cand_set)