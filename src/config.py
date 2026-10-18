"""API 키 읽기.

우선순위: 환경변수 → Streamlit secrets (st.secrets).
코드에 키를 적지 않는다. 로컬은 .streamlit/secrets.toml (git 제외),
배포는 Streamlit Community Cloud의 Secrets 설정을 쓴다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

ENV_NAMES = {
    "tavily": "TAVILY_API_KEY",
    "brave": "BRAVE_API_KEY",
    "google_places": "GOOGLE_PLACES_API_KEY",
}


@dataclass
class Settings:
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    google_places_api_key: str | None = None

    def missing(self) -> list[str]:
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
    )
