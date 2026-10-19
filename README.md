# 🎬 영화 촬영지 찾기

영화 제목을 넣으면 촬영지 후보와 지도 좌표를 찾아주는 Streamlit 앱.

- **모듈 2 (영화 확정)**: TMDB에서 영화를 찾아 포스터·감독·줄거리를 보고 정확히 고른다.
  한글/영어 제목 모두 검색되고 (ko-KR 우선, en-US 폴백), 연도로 좁힐 수 있다.
- **모듈 1 (촬영지)**: 확정된 영화의 **영어 제목 + 연도**로 촬영지를 검색한다.
  Tavily + Brave 웹 검색으로 촬영지 언급을 모으고, Google Places( Text Search New )로
  이름/주소/좌표를 확인한다.

TMDB 키가 없어도 모듈 1 방식(제목 그대로 검색)으로 동작한다.

## 설치

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml에 키 4개 입력
streamlit run app.py
```

## API 키

| 키 | 용도 | 없으면 |
|---|---|---|
| `TMDB_API_KEY` | 영화 확정 (모듈 2). v3 키 또는 v4 Read Access Token | 제목 그대로 검색 (모듈 1만) |
| `TAVILY_API_KEY` | 웹 검색 + 페이지 본문 추출 | 촬영지 검색 불가 |
| `BRAVE_API_KEY` | 웹 검색 | 촬영지 검색 불가 |
| `GOOGLE_PLACES_API_KEY` | 장소 확인(좌표/주소) | 좌표 없이 언급만 표시 |

## 구조

```
app.py                    Streamlit UI (영화 선택 → 촬영지)
src/movie_search.py       모듈 2: TMDB 검색/확정 파이프라인
src/pipeline.py           모듈 1: 촬영지 검색 파이프라인
src/models.py             Movie, MovieCandidate, FilmLocation 등
src/config.py             키 읽기 (환경변수 → st.secrets)
src/errors.py             AuthError / RateLimitError / UpstreamError
src/sources/tmdb_client.py    TMDB v3/v4 인증, 검색, 상세+credits
src/sources/tavily_client.py  Tavily Search/Extract
src/sources/brave_client.py   Brave Web Search
src/sources/gplaces.py        Google Places Text Search (New)
tests/                    59개 테스트 (실제 API 호출 없이 가짜 응답 사용)
```

## TMDB 관련 참고

- 인증: v3 `api_key` 쿼리 파라미터와 v4 Bearer 토큰 모두 지원 (자동 구분).
- 레이트리밋: TMDB 상한은 초당 약 40회. 클라이언트가 호출 간격 0.25초를 스스로 지키고,
  429 응답이 오면 `Retry-After`만큼 기다렸다가 한 번 재시도한다.
- 캐시: TMDB 약관상 캐시는 최대 6개월. 앱은 1시간만 캐시한다 (st.cache_data ttl=3600).
- 어트리뷰션: 약관에 따라 앱 하단에 TMDB 로고와 고지 문구를 표시한다.

## 테스트

```bash
python3 -m pytest tests -q   # 59개 통과, 네트워크 호출 없음
```