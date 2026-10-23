"""영화 촬영지 찾기 — 모듈 1(촬영지) + 모듈 2(TMDB 영화 확정)
+ 모듈 3(주변 맛집/트래킹/역사) + 모듈 4(여행 조건·일정 초안).

실행: streamlit run app.py
키 설정: .streamlit/secrets.toml (secrets.toml.example 참고)

흐름 (TMDB 키가 있을 때):
  1) 제목(한글/영어) + 연도(선택)로 TMDB에서 영화를 찾는다
  2) 포스터/감독/줄거리를 보고 맞는 영화를 고른다
  3) 확정된 영화의 영어 제목 + 연도로 촬영지를 찾는다 (모듈 1)
TMDB 키가 없으면 모듈 1 방식(제목 직접 검색)으로 동작한다.
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from src.config import load_settings
from src.errors import AuthError, RateLimitError, SourceError
from src.models import Movie
from src.movie_search import confirm_movie, search_movies
from src.nearby import CATEGORY_LABELS, find_nearby
from src.pipeline import find_film_locations
from src.trip import (BUDGET_BASIS_LABELS, EXPENSE_CATEGORIES, TripSettings,
                      budget_summary, build_itinerary, validate_settings)
from src.sources.brave_client import BraveSearchClient
from src.sources.gplaces import GooglePlacesClient
from src.sources.tavily_client import TavilyClient
from src.sources.tmdb_client import TMDBClient

# TMDB 약관상 앱에 로고와 고지 문구를 보여줘야 한다 (2026-10-18 확인).
TMDB_LOGO_URL = ("https://www.themoviedb.org/assets/v4/logos/v2/"
                 "blue_short-8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c.svg")
TMDB_NOTICE = ("This application uses TMDB and the TMDB APIs but is not "
               "endorsed, certified, or otherwise approved by TMDB.")

st.set_page_config(page_title="영화 촬영지 찾기", page_icon="🎬")
st.title("🎬 영화 촬영지 찾기")
st.caption("영화를 정확히 고른 뒤(TMDB), 촬영지 후보와 좌표를 찾아줘요. "
           "촬영지는 Tavily + Brave 검색으로 찾고 Google Places로 확인해요.")

settings = load_settings()


@st.cache_resource
def get_clients(tavily_key, brave_key, places_key, tmdb_key):
    """API 클라이언트들. 키가 없는 건 None."""
    return {
        "tavily": TavilyClient(tavily_key) if tavily_key else None,
        "brave": BraveSearchClient(brave_key) if brave_key else None,
        "places": GooglePlacesClient(places_key) if places_key else None,
        "tmdb": TMDBClient(tmdb_key) if tmdb_key else None,
    }


clients = get_clients(settings.tavily_api_key, settings.brave_api_key,
                      settings.google_places_api_key, settings.tmdb_api_key)

missing = settings.missing()
if missing:
    st.warning("설정이 필요한 키: " + ", ".join(missing) +
               " — .streamlit/secrets.toml 또는 배포 환경의 Secrets에 넣어 주세요.")

use_tmdb = clients["tmdb"] is not None
if not use_tmdb:
    st.info("TMDB_API_KEY를 넣으면 영화를 포스터 보고 정확히 고를 수 있어요. "
            "지금은 제목 그대로 검색해요.")


# --- TMDB 호출 캐시: 약관상 캐시는 6개월까지 가능, 여기선 1시간만 ----------
@st.cache_data(ttl=3600, show_spinner=False)
def cached_search_movies(title: str, year: int | None):
    return search_movies(title, year=year, tmdb=clients["tmdb"])


@st.cache_data(ttl=3600, show_spinner=False)
def cached_confirm_movie(tmdb_id: int, title: str, year: int | None,
                         original_title, overview: str, poster_url):
    from src.models import MovieCandidate
    cand = MovieCandidate(title=title, year=year, tmdb_id=tmdb_id,
                          original_title=original_title, overview=overview,
                          poster_url=poster_url)
    return confirm_movie(cand, clients["tmdb"])


def confidence_badge(c: float) -> str:
    if c >= 0.8:
        return "🟢 높음"
    if c >= 0.5:
        return "🟡 보통"
    return "🔴 낮음"


def show_locations(result) -> None:
    """모듈 1 결과 렌더링."""
    for w in result.warnings:
        st.warning(w)
    if result.status == "ambiguous":
        st.subheader("같은 제목의 영화가 여러 편 있어요")
        st.write("연도를 보고 위 입력창에 개봉 연도를 넣어 다시 검색해 주세요.")
        for c in result.movie_candidates:
            label = f"{c.title} ({c.year})" if c.year else c.title
            st.markdown(f"- **{label}** — [출처]({c.source_url})")
    elif result.status == "no_results":
        st.info("촬영지 정보를 찾지 못했어요. 제목을 다르게 써 보거나, "
                "개봉 연도를 함께 넣어 보세요.")
    elif result.status == "error":
        st.error(f"검색에 실패했어요: {result.error}")
    else:
        st.subheader(f"촬영지 후보 {len(result.locations)}곳")
        if result.locations:
            st.map([{"lat": loc.lat, "lon": loc.lon} for loc in result.locations])
        for loc in result.locations:
            with st.expander(f"{loc.name} — 신뢰도 {confidence_badge(loc.confidence)} "
                             f"({loc.confidence:.1f})"):
                st.write(loc.address)
                if loc.google_maps_uri:
                    st.markdown(f"[Google 지도에서 보기]({loc.google_maps_uri})")
                st.caption("근거: " + ", ".join(
                    f"[링크{i+1}]({u})" for i, u in enumerate(loc.source_urls)))
        if result.unresolved_mentions:
            with st.expander("확인하지 못한 촬영지 언급 (Google Places에서 못 찾음)"):
                for m in result.unresolved_mentions:
                    st.markdown(f"- {m.raw_text} — [출처]({m.source_url})")
        nearby_section(result)
        trip_section(result)


def _fmt_km(distance_m: float) -> str:
    return f"{distance_m/1000:.1f}km" if distance_m >= 1000 else f"{int(distance_m)}m"


def show_nearby(groups) -> None:
    """모듈 3 결과 렌더링: 촬영지별 맛집/트래킹/역사 명소."""
    for g in groups:
        with st.expander(f"📍 {g.location.name} 주변", expanded=True):
            for w in g.warnings:
                st.warning(w)
            cols = st.columns(3)
            for col, key in zip(cols, ("restaurants", "trekking", "historic")):
                with col:
                    st.markdown(f"**{CATEGORY_LABELS[key]}**")
                    items = getattr(g, key)
                    if not items:
                        st.caption("찾은 곳이 없어요.")
                    for n in items:
                        line = f"{n.place.name} ({_fmt_km(n.distance_m)})"
                        if n.place.google_maps_uri:
                            st.markdown(f"- [{line}]({n.place.google_maps_uri})")
                        else:
                            st.markdown(f"- {line}")
                        st.caption(n.place.address)


def nearby_section(result) -> None:
    """모듈 3: 촬영지 주변 맛집/트래킹/역사 명소 찾기.

    촬영지마다 카테고리 3번씩 Nearby Search를 부르므로(API 비용) 버튼을 눌렀을 때만
    실행한다. 반경 기본 10km(렌터카 기준), 맛집은 현지 식사 우선.
    """
    if not result.locations or clients["places"] is None:
        return
    st.divider()
    st.subheader("🍜 주변 맛집 / 🥾 트래킹 / 🏛️ 역사 명소")
    radius_km = st.slider("검색 반경 (km)", min_value=1, max_value=30, value=10,
                          help="렌터카 이동 기준 기본 10km예요.")
    if st.button("주변 찾기", type="primary"):
        try:
            with st.spinner(f"촬영지 {len(result.locations)}곳 주변을 찾는 중… "
                            "(촬영지 1곳당 검색 3번)"):
                st.session_state["nearby_groups"] = find_nearby(
                    result.locations, clients["places"],
                    radius_m=radius_km * 1000, per_category=3)
        except AuthError as exc:
            st.error(f"API 키 문제예요: {exc}")
        except RateLimitError as exc:
            st.error(f"호출 한도를 초과했어요: {exc} — 잠시 후 다시 시도해 주세요.")
        except SourceError as exc:
            st.error(f"외부 서비스 오류: {exc}")
    groups = st.session_state.get("nearby_groups") or []
    if groups:
        show_nearby(groups)


def trip_section(result) -> None:
    """모듈 4: 동행인·여행 날짜·예산을 입력받아 일정 초안과 예산 가늠을 만든다.

    외부 API를 부르지 않는다 — 화면 입력값과 이미 찾은 촬영지/주변 결과만 쓴다.
    '일정 초안 만들기'를 눌러 세션에 저장하면 재실행(슬라이더 조작 등) 후에도
    아래에서 다시 그려지므로, 앞 단계와 같은 방식으로 화면이 유지된다.
    """
    if not result.locations:
        return
    st.divider()
    st.subheader("🗓️ 여행 계획 세우기")
    st.caption("찾은 촬영지를 여행 날짜에 맞춰 하루 단위 초안으로 묶고, "
               "예산을 가늠해요. 아직 예약은 하지 않아요.")

    today = date.today()
    dates = st.date_input(
        "여행 날짜 (출발일 ~ 귀국일)",
        value=(today + timedelta(days=30), today + timedelta(days=32)),
        key="trip_dates")
    col1, col2 = st.columns(2)
    with col1:
        party_size = st.number_input("인원 (본인 포함)", min_value=1, max_value=20,
                                     value=2, key="trip_party")
        companions_in = st.text_input("동행인 이름 (선택, 쉼표로 구분)",
                                      placeholder="예: 아내, 큰아이",
                                      key="trip_companions")
    with col2:
        budget_amount = st.number_input(
            "예산 (원)", min_value=0, step=100000, value=0,
            help="0이면 예산 없이 일정 초안만 만들어요.", key="trip_budget")
        budget_basis = st.radio("예산 기준", ["total", "per_person"],
                                format_func=lambda k: BUDGET_BASIS_LABELS[k],
                                horizontal=True, key="trip_basis")
        includes_airfare = st.checkbox("예산에 항공료 포함", value=True,
                                       key="trip_airfare")
    loc_names = [loc.name for loc in result.locations]
    picked = st.multiselect("일정에 넣을 촬영지", loc_names, default=loc_names,
                            key="trip_picks")

    if st.button("일정 초안 만들기", type="primary", key="trip_make"):
        if not isinstance(dates, (tuple, list)) or len(dates) != 2:
            st.error("출발일과 귀국일을 모두 골라 주세요.")
        else:
            companions = tuple(n.strip() for n in companions_in.split(",")
                               if n.strip())
            settings = TripSettings(
                party_size=int(party_size), start_date=dates[0],
                end_date=dates[1], budget_amount=int(budget_amount),
                budget_basis=budget_basis, includes_airfare=includes_airfare,
                companions=companions)
            problems = validate_settings(settings)
            if problems:
                for msg in problems:
                    st.error(msg)
            else:
                stops = [loc for loc in result.locations if loc.name in picked]
                st.session_state["trip_plan"] = {
                    "settings": settings,
                    "days": build_itinerary(stops, settings.days),
                }

    plan = st.session_state.get("trip_plan")
    if plan:
        show_trip_plan(plan)


def show_trip_plan(plan) -> None:
    """세션에 저장된 일정 초안과 예산 가늠 렌더링."""
    settings: TripSettings = plan["settings"]
    header = (f"**🧳 {settings.start_date:%Y-%m-%d} ~ "
              f"{settings.end_date:%m-%d} · {settings.nights}박 "
              f"{settings.days}일 · {settings.party_size}명**")
    if settings.companions:
        header += f" (동행: {', '.join(settings.companions)})"
    st.markdown(header)
    st.caption("초안은 **직선거리**로 가까운 곳끼리 묶은 거예요. 실제 이동 시간, "
               "국경·페리, 영업시간, 입출국 동선은 확인하지 않았어요. "
               "실제 동선은 지도에서 꼭 확인해 주세요.")

    # 주변 찾기 결과(모듈 3)가 있으면 각 촬영지 밑에 함께 보여준다.
    nearby = {g.location.name: g
              for g in st.session_state.get("nearby_groups") or []}
    for day in plan["days"]:
        label = f"{day.day}일차" + (f" — {day.note}" if day.note else "")
        with st.expander(label, expanded=True):
            if day.merged:
                st.warning("일수에 맞추느라 멀리 떨어진 촬영지를 같은 날에 넣었어요. "
                           "이동 시간을 확인하지 않은 조합이라 하루에 다 보기 "
                           "어려울 수 있어요.")
            if not day.stops:
                st.caption("배정된 촬영지가 없어요. 여유로운 날이에요.")
            for loc in day.stops:
                st.markdown(f"- 🎬 **{loc.name}** ({loc.address})")
                g = nearby.get(loc.name)
                if g:
                    for key, label_k in (("restaurants", "맛집"),
                                         ("trekking", "트래킹"),
                                         ("historic", "역사 명소")):
                        items = getattr(g, key)
                        if items:
                            st.caption("　" + label_k + ": " + ", ".join(
                                n.place.name for n in items))

    if settings.budget_amount <= 0:
        return
    st.markdown("**💰 예산 가늠**")
    basis_txt = BUDGET_BASIS_LABELS[settings.budget_basis]
    basis_txt += " · 항공료 포함" if settings.includes_airfare else " · 항공료 별도"
    st.caption(f"입력 예산 {settings.budget_amount:,}원 ({basis_txt}).")
    st.caption("예상 지출은 **일행 전원의 여행 전체 기간 합계**로 넣어 주세요 — "
               "예산 총액과 비교해요. 빈 칸(0원)은 무료가 아니라 "
               "아직 입력하지 않은 항목이에요.")
    expenses = {}
    cols = st.columns(3)
    for i, (key, label) in enumerate(EXPENSE_CATEGORIES):
        with cols[i % 3]:
            expenses[key] = st.number_input(label, min_value=0, step=10000,
                                            value=0, key=f"trip_exp_{key}")
    summary = budget_summary(settings, expenses)
    c1, c2, c3 = st.columns(3)
    c1.metric("전체 예산", f"{summary['total']:,}원")
    c2.metric("1인당", f"{summary['per_person']:,}원")
    c3.metric("하루당", f"{summary['per_day']:,}원")
    st.caption(f"예상 지출 합계 {summary['spent']:,}원 → "
               f"남은 예산 **{summary['remaining']:,}원**")
    if summary["remaining"] < 0:
        st.warning("예상 지출이 예산을 넘었어요. 일정이나 항목을 조정해 보세요.")


def run_location_search(title: str, year: int | None,
                        allow_korea: bool = True) -> None:
    """모듈 1 호출 + 오류 처리 + 렌더링."""
    # 새 촬영지 검색이면 이전 '주변 찾기' 결과는 지운다 (다른 촬영지 기준이라).
    st.session_state.pop("nearby_groups", None)
    st.session_state.pop("trip_plan", None)
    try:
        with st.spinner("촬영지를 찾는 중… (최대 30초)"):
            result = find_film_locations(
                title, year=year,
                brave=clients["brave"], tavily=clients["tavily"],
                places=clients["places"],
                allow_korea=allow_korea,
            )
        st.session_state["last_result"] = result
        st.session_state["last_query"] = (title, year)
    except AuthError as exc:
        st.error(f"API 키 문제예요: {exc}")
        result = st.session_state.get("last_result")
        if not result:
            return
        st.info("아래는 이전 결과예요.")
    except RateLimitError as exc:
        st.error(f"호출 한도를 초과했어요: {exc} — 잠시 후 다시 시도해 주세요.")
        result = st.session_state.get("last_result")
        if not result:
            return
        st.info("아래는 이전 결과예요.")
    except SourceError as exc:
        st.error(f"외부 서비스 오류: {exc}")
        result = st.session_state.get("last_result")
        if not result:
            return
        st.info("아래는 이전 결과예요.")
    show_locations(result)


def reshow_last_result(query) -> None:
    """버튼을 누르지 않은 재실행(슬라이더 조작, '주변 찾기' 클릭 등)에서
    세션의 마지막 촬영지 결과를 다시 그린다.

    Streamlit은 위젯을 건드릴 때마다 스크립트 전체를 다시 실행하는데,
    결과를 버튼을 누른 그 실행에서만 그리면 다음 재실행 때 화면이
    처음으로 돌아가 버린다. 검색어(또는 확정 영화)가 같을 때만 다시 그린다.
    """
    result = st.session_state.get("last_result")
    if result is not None and st.session_state.get("last_query") == query:
        show_locations(result)


# === UI ================================================================

title = st.text_input("영화 제목", placeholder="예: 해리포터, 기생충, La La Land")
year_in = st.number_input("개봉 연도 (모를 땐 0)", min_value=0, max_value=2100,
                          value=0,
                          help="같은 제목의 영화가 여러 편이면 연도로 좁혀져요.")
year = int(year_in) if year_in else None

if use_tmdb:
    # --- 1단계: 영화 찾기 ------------------------------------------------
    if st.button("영화 찾기", type="primary", disabled=not title.strip()):
        try:
            with st.spinner("TMDB에서 영화를 찾는 중…"):
                candidates = cached_search_movies(title.strip(), year)
            st.session_state["candidates"] = candidates
            st.session_state.pop("movie", None)
        except (AuthError, RateLimitError, SourceError) as exc:
            st.error(f"영화 검색 실패: {exc}")

    candidates = st.session_state.get("candidates") or []
    if not candidates and "candidates" in st.session_state:
        st.info("찾는 영화가 없어요. 제목을 다르게 써 보세요.")

    # --- 2단계: 후보에서 선택 ---------------------------------------------
    for i, c in enumerate(candidates):
        with st.container(border=True):
            col1, col2 = st.columns([1, 4])
            with col1:
                if c.poster_url:
                    st.image(c.poster_url, width=90)
            with col2:
                label = f"**{c.title}** ({c.year})" if c.year else f"**{c.title}**"
                st.markdown(label)
                if c.original_title and c.original_title != c.title:
                    st.caption(c.original_title)
                if c.overview:
                    st.write(c.overview[:150] + ("…" if len(c.overview) > 150 else ""))
                if st.button("이 영화예요", key=f"pick_{c.tmdb_id}"):
                    try:
                        with st.spinner("영화 정보를 확인하는 중…"):
                            st.session_state["movie"] = cached_confirm_movie(
                                c.tmdb_id, c.title, c.year, c.original_title,
                                c.overview, c.poster_url)
                    except (AuthError, RateLimitError, SourceError) as exc:
                        st.error(f"영화 정보 확인 실패: {exc}")

    # --- 3단계: 확정된 영화로 촬영지 찾기 ----------------------------------
    movie: Movie | None = st.session_state.get("movie")
    if movie:
        with st.container(border=True):
            col1, col2 = st.columns([1, 4])
            with col1:
                if movie.poster_url:
                    st.image(movie.poster_url, width=110)
            with col2:
                st.subheader(f"✅ {movie.title}"
                             + (f" ({movie.year})" if movie.year else ""))
                if movie.director:
                    st.write(f"감독: {movie.director}")
                st.caption(f"촬영지 검색에는 영어 제목 “{movie.english_title}”"
                           + (f" ({movie.year})" if movie.year else "")
                           + "을 써요.")
                if movie.tmdb_url:
                    st.markdown(f"[TMDB에서 보기]({movie.tmdb_url})")
        # 제작 국가에 한국(KR)이 없는 외국 영화면 한국 장소 후보를 제외한다.
        # 제작 국가 정보가 아예 없으면(알 수 없음) 필터를 켜지 않는다.
        allow_korea = (not movie.production_countries
                       or "KR" in movie.production_countries)
        if movie.production_countries:
            st.caption("제작 국가(TMDB): " + ", ".join(movie.production_countries)
                       + ("" if allow_korea
                          else " — 한국이 아니라서 한국 장소는 결과에서 뺄게요."))
        if st.button("이 영화로 촬영지 찾기", type="primary"):
            run_location_search(movie.english_title, movie.year,
                                allow_korea=allow_korea)
        else:
            reshow_last_result((movie.english_title, movie.year))

    # --- TMDB 어트리뷰션 (약관 필수) ---------------------------------------
    st.divider()
    col1, col2 = st.columns([1, 5])
    with col1:
        st.image(TMDB_LOGO_URL, width=100)
    with col2:
        st.caption(TMDB_NOTICE)
        st.caption("영화 정보: [TMDB](https://www.themoviedb.org) — "
                   "캐시는 1시간만 유지해요 (약관상 최대 6개월).")
else:
    # --- TMDB 키 없음: 모듈 1 방식 그대로 ----------------------------------
    if st.button("촬영지 찾기", type="primary", disabled=not title.strip()):
        run_location_search(title.strip(), year)
    elif title.strip():
        reshow_last_result((title.strip(), year))
