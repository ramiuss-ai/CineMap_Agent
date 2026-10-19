"""API 키 읽기.

우선순위: 환경변수 → Streamlit secrets (st.secrets).
코드에 키를 적지 않는다. 로컬은 .streamlit/secrets.toml (git 제외),
배포는 Streamlit Community Cloud의 Secrets 설정을 쓴다.

TMDB_API_KEY는 모듈 2(영화 확정)용 선택 키다. v3 API 키나
v4 Read Access Token 둘 다 넣을 수 있다 (클라이언트가 자동 구분).
없어도 모듈 1(제목 직접 검색)은 동작한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

ENV_NAMES = {
    "tavily": "TAVILY_API_KEY",
    "brave": "BRAVE_API_KEY",
    "google_places": "GOOGLE_PLACES_API_KEY",
    "tmdb": "TMDB_API_KEY",  # 모듈 2. v3 키 또는 v4 Read Access Token
}


@dataclass
class Settings:
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    google_places_api_key: str | None = None
    tmdb_api_key: str | None = None  # 선택: 있으면 모듈 2(영화 확정) 활성화

    def missing(self) -> list[str]:
        """모듈 1 필수 키 중 없는 것. TMDB는 선택이라 여기 넣지 않는다."""
        out = []
        if not self.tavily_api_key:
            out.append(ENV_NAMES["tavily"])
        if not self.brave_api_key:
            out.append(ENV_NAMES["brave"])
        if not self.google_places_api_key:
            out.append(ENV_NAMES["google_places"])
        return out


def _from_streamlit_secrets(env_name: str) -> str | None:
    try:
        import streamlit as st  # 지연 임포트: 테스트/CLI에서는 없을 수 있음
        value = st.secrets.get(env_name)
        return str(value) if value else None
    except Exception:
        return None


def get_key(env_name: str) -> str | None:
    return os.environ.get(env_name) or _from_streamlit_secrets(env_name)


def load_settings() -> Settings:
    return Settings(
        tavily_api_key=get_key(ENV_NAMES["tavily"]),
        brave_api_key=get_key(ENV_NAMES["brave"]),
        google_places_api_key=get_key(ENV_NAMES["google_places"]),
        tmdb_api_key=get_key(ENV_NAMES["tmdb"]),
    )