"""데이터 모델.

설계 문서(https://files.instinct.com/sqwagzl5jups)의 FilmLocation을 바탕으로,
모듈 1(웹 검색 + Google Places)에 필요한 필드를 추가했다.
설계와 달라진 점:
- Movie 대신 MovieCandidate: TMDB 키가 없어 영화 확정은 검색 결과 기반으로만 한다.
- FilmLocation에 source_urls, confidence, google_maps_uri를 추가했다.
  (출처 URL과 신뢰도는 웹 검색 기반이라 필수 정보)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MovieCandidate:
    """같은 제목의 영화가 여러 편일 때 사용자가 고를 후보."""
    title: str
    year: int | None = None
    source_url: str | None = None


@dataclass
class WebResult:
    """검색 엔진(Brave/Tavily) 결과 한 건."""
    title: str
    url: str
    description: str = ""
    engine: str = ""  # "brave" | "tavily"


@dataclass
class LocationMention:
    """웹 문서에서 규칙 기반으로 뽑아낸 '촬영지일 수 있는' 원시 문자열."""
    raw_text: str          # 예: "통영 동피랑", "Glen Etive"
    source_url: str        # 이 문구가 나온 페이지
    snippet: str = ""      # 주변 문장 (근거 확인용)


@dataclass
class ResolvedPlace:
    """Google Places(Text Search New)로 확인한 장소."""
    place_id: str
    name: str
    address: str
    lat: float
    lon: float
    types: list[str] = field(default_factory=list)
    google_maps_uri: str | None = None


@dataclass
class FilmLocation:
    """촬영지 후보 한 곳. 설계 문서의 FilmLocation 확장."""
    name: str                       # 장소명 (Places 기준)
    address: str
    lat: float
    lon: float
    scene: str | None = None        # 어떤 장면 (모듈 1에서는 비어 있을 수 있음)
    source: str = "web"             # 설계: kofic/wikidata/user → 모듈 1은 web 검색
    source_id: str = ""             # Google place_id
    source_urls: list[str] = field(default_factory=list)  # 근거 페이지들
    confidence: float = 0.0         # 0.0~1.0
    google_maps_uri: str | None = None


@dataclass
class LocationSearchResult:
    """find_film_locations()의 반환값.

    status:
      "ok"          - 촬영지 후보를 1곳 이상 찾음
      "ambiguous"   - 같은 제목의 영화가 여러 편 → movie_candidates에서 골라야 함
      "no_results"  - 촬영지 언급을 못 찾음
      "error"       - API 오류 (error에 메시지)
    """
    query: str
    status: str
    movie_candidates: list[MovieCandidate] = field(default_factory=list)
    locations: list[FilmLocation] = field(default_factory=list)
    unresolved_mentions: list[LocationMention] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)   # 부분 실패 안내 (예: Tavily 다운)
    error: str | None = None
