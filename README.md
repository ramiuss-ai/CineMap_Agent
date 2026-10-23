# 🎬 영화 촬영지 찾기

영화 제목을 넣으면 촬영지 후보와 지도 좌표를 찾아주는 Streamlit 앱.

- **모듈 2 (영화 확정)**: TMDB에서 영화를 찾아 포스터·감독·줄거리를 보고 정확히 고른다.
  한글/영어 제목 모두 검색되고 (ko-KR 우선, en-US 폴백), 연도로 좁힐 수 있다.
- **모듈 1 (촬영지)**: 확정된 영화의 **영어 제목 + 연도**로 촬영지를 검색한다.
  Tavily + Brave 웹 검색으로 촬영지 언급을 모으고, Google Places( Text Search New )로
  이름/주소/좌표를 확인한다.

- **한국 장소 제외 (패치, 2026-10-20)**: 확정한 영화의 TMDB 제작 국가에 한국(KR)이
  없으면, 촬영지 후보에서 한국에 있는 장소를 뺀다. 외국 영화 검색에 한국 업소가
  억지로 끼어드는 걸 막기 위해서다. 제작 국가 정보가 없거나 한국 영화면 그대로 둔다.
- **모듈 3 (주변 추천)**: 촬영지마다 반경(기본 10km, 렌터카 기준) 안의 맛집·트래킹·
  역사 명소를 Google Places Nearby Search(New)로 찾는다. 맛집은 현지 요리 타입
  (예: KR이면 korean_restaurant)을 우선 보여주는 휴리스틱을 쓴다.

- **모듈 4 (여행 계획, 2026-10-23)**: 찾은 촬영지를 골라 여행 날짜·인원·동행인·
  예산(1인/전체 기준, 항공료 포함 여부)을 넣으면 하루 단위 일정 초안을 만든다.
  가까운 촬영지끼리 같은 날로 묶고(직선거리 80km, 하루 최대 3곳), 남는 날은
  '자유 일정'으로 둔다. 직선거리 기준 초안이라 실제 이동 시간·국경/페리·
  영업시간은 확인하지 않으며, 일수에 맞춰 먼 곳끼리 합친 날은 경고를 표시한다. 예상 지출(항공료·숙소·식비 등)을 채우면 남은 예산을
  바로 계산해준다. 외부 API는 부르지 않아서 비용이 들지 않는다.

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
app.py                    Streamlit UI (영화 선택 → 촬영지 → 주변 추천 → 여행 계획)
src/trip.py               모듈 4: 여행 조건(인원/날짜/예산) + 일정 초안
src/movie_search.py       모듈 2: TMDB 검색/확정 파이프라인
src/pipeline.py           모듈 1: 촬영지 검색 파이프라인 (+한국 장소 필터)
src/nearby.py             모듈 3: 주변 맛집/트래킹/역사 명소
src/models.py             Movie, FilmLocation, NearbyPlace/NearbyGroup 등
src/config.py             키 읽기 (환경변수 → st.secrets)
src/errors.py             AuthError / RateLimitError / UpstreamError
src/sources/tmdb_client.py    TMDB v3/v4 인증, 검색, 상세+credits
src/sources/tavily_client.py  Tavily Search/Extract
src/sources/brave_client.py   Brave Web Search
src/sources/gplaces.py        Google Places Text Search/Nearby Search (New)
tests/                    97개 테스트 (실제 API 호출 없이 가짜 응답 사용)
```

## TMDB 관련 참고

- 인증: v3 `api_key` 쿼리 파라미터와 v4 Bearer 토큰 모두 지원 (자동 구분).
- 레이트리밋: TMDB 상한은 초당 약 40회. 클라이언트가 호출 간격 0.25초를 스스로 지키고,
  429 응답이 오면 `Retry-After`만큼 기다렸다가 한 번 재시도한다.
- 캐시: TMDB 약관상 캐시는 최대 6개월. 앱은 1시간만 캐시한다 (st.cache_data ttl=3600).
- 어트리뷰션: 약관에 따라 앱 하단에 TMDB 로고와 고지 문구를 표시한다.

## Google Places 비용 메모 (2026-10-20 문서 기준)

- Text Search, Nearby Search 모두 요청 필드를 **Pro SKU** 범위로 고정했다
  (displayName, formattedAddress, location, types, googleMapsUri, addressComponents).
  rating/전화번호/영업시간 등은 Enterprise SKU라 일부러 제외했다.
- 검색 1회당 Places 호출: 모듈 1 최대 12회(Text Search) + 모듈 3은
  촬영지 1곳당 3회(Nearby Search, 카테고리별 1회). 모듈 3은 버튼을 눌렀을 때만 돈다.
- 무료 한도: SKU별 월 무료 호출이 있다. 정확한 최신 한도는 Google Cloud 콘솔 확인.

## 테스트

```bash
python3 -m pytest tests -q   # 97개 통과, 네트워크 호출 없음
```
