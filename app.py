"""모듈 1 데모: 영화 제목 → 촬영지 후보.

실행: streamlit run app.py
키 설정: .streamlit/secrets.toml (secrets.toml.example 참고)
"""
from __future__ import annotations

import streamlit as st

from src.config import load_settings
from src.errors import AuthError, RateLimitError, SourceError
from src.pipeline import find_film_locations
from src.sources.brave_client import BraveSearchClient
from src.sources.gplaces import GooglePlacesClient
from src.sources.tavily_client import TavilyClient

st.set_page_config(page_title="영화 촬영지 찾기 (모듈 1)", page_icon="🎬")
st.title("🎬 영화 촬영지 찾기 — 모듈 1")
st.caption("영화 제목(한글/영어)을 넣으면 촬영지 후보와 좌표를 찾아줘요. "
           "Tavily + Brave 검색으로 찾고, Google Places로 확인해요.")

settings = load_settings()

# --- 클라이언트 준비 (키 없으면 안내만) --------------------------------
clients = {}
if settings.brave_api_key:
    clients["brave"] = BraveSearchClient(settings.brave_api_key)
if settings.tavily_api_key:
    clients["tavily"] = TavilyClient(settings.tavily_api_key)
if settings.google_places_api_key:
    clients["places"] = GooglePlacesClient(settings.google_places_api_key)

missing = settings.missing()
if missing:
    st.warning("설정이 필요한 키: " + ", ".join(missing) +
               " — .streamlit/secrets.toml 또는 배포 환경의 Secrets에 넣어 주세요.")

title = st.text_input("영화 제목", placeholder="예: 부산행, 기생충, La La Land")
year = st.number_input("개봉 연도 (모를 땐 0)", min_value=0, max_value=2100, value=0,
                       help="같은 제목의 영화가 여러 편이면 연도로 좁혀져요.")
run = st.button("촬영지 찾기", type="primary", disabled=not title.strip())


def confidence_badge(c: float) -> str:
    if c >= 0.8:
        return "🟢 높음"
    if c >= 0.5:
        return "🟡 보통"
    return "🔴 낮음"


if run:
    last = st.session_state.get("last_result")
    try:
        with st.spinner("검색하고 확인하는 중… (최대 30초)"):
            result = find_film_locations(
                title.strip(),
                year=int(year) if year else None,
                brave=clients.get("brave"),
                tavily=clients.get("tavily"),
                places=clients.get("places"),
            )
        st.session_state["last_result"] = result
    except AuthError as exc:
        st.error(f"API 키 문제예요: {exc}")
        if last:
            st.info("아래는 이전 결과예요.")
            result = last
        else:
            st.stop()
    except RateLimitError as exc:
        st.error(f"호출 한도를 초과했어요: {exc} — 잠시 후 다시 시도해 주세요.")
        if st.button("다시 시도"):
            st.rerun()
        if last:
            st.info("아래는 이전 결과예요.")
            result = last
        else:
            st.stop()
    except SourceError as exc:
        st.error(f"외부 서비스 오류: {exc}")
        if last:
            st.info("아래는 이전 결과예요.")
            result = last
        else:
            st.stop()

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
