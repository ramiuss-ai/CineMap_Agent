"""영화 촬영지 찾기 — 모듈 1(촬영지) + 모듈 2(TMDB 영화 확정).

실행: streamlit run app.py
키 설정: .streamlit/secrets.toml (secrets.toml.example 참고)

흐름 (TMDB 키가 있을 때):
  1) 제목(한글/영어) + 연도(선택)로 TMDB에서 영화를 찾는다
  2) 포스터/감독/줄거리를 보고 맞는 영화를 고른다
  3) 확정된 영화의 영어 제목 + 연도로 촬영지를 찾는다 (모듈 1)
TMDB 키가 없으면 모듈 1 방식(제목 직접 검색)으로 동작한다.
"""
from __future__ import annotations

import streamlit as st

from src.config import load_settings
from src.errors import AuthError, RateLimitError, SourceError
from src.models import Movie
from src.movie_search import confirm_movie, search_movies
from src.pipeline import find_film_locations
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


def run_location_search(title: str, year: int | None) -> None:
    """모듈 1 호출 + 오류 처리 + 렌더링."""
    try:
        with st.spinner("촬영지를 찾는 중… (최대 30초)"):
            result = find_film_locations(
                title, year=year,
                brave=clients["brave"], tavily=clients["tavily"],
                places=clients["places"],
            )
        st.session_state["last_result"] = result
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
        if st.button("이 영화로 촬영지 찾기", type="primary"):
            run_location_search(movie.english_title, movie.year)

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