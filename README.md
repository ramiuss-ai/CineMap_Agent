# 🗺️ CineMap — 여행지 중심 여행 계획

여행지를 고르면 관심사 명소 후보를 모으고, 고른 후보로 하루 단위 일정 초안을
만들어 주는 Streamlit 앱.

**1단계 개편 (2026-10-28)**: 영화 먼저가 아니라 **여행지 먼저**. 영화 촬영지는
별도 출발점이 아니라, 고른 여행지의 명소를 찾는 과정에서 웹 검색으로 발견되면
근거 링크와 함께 방문 후보에 넣는다. 지금은 **해외 여행 기준**이다 (국내는
카카오 로컬 키가 필요해 나중에).

## 화면 흐름

1. **여행지 고르기** — 도시·지역 이름을 넣으면 Google Places Text Search(1회)로
   확인하고, 주소와 Google 지도 링크를 보여준다.
2. **관심사 명소 후보 찾기** — 관심사(맛집 2~3곳·자연/트래킹·역사 명소·
   박물관/미술관·쇼핑·액티비티)를 고르고 반경(기본 10km, 렌터카 이동 기준)을
   정하면 카테고리별로 Places Nearby Search로 후보를 모은다. 모든 후보는
   주소 + 지도 링크를 보여준다. '🎬 이 지역의 영화 촬영지도 함께 찾기'(기본
   켜짐)를 두면 Brave/Tavily 웹 검색으로 이 지역 촬영지 언급을 모아 Places로
   확인한 뒤 근거 링크와 함께 후보에 넣는다. 근거 없는 촬영지 주장은
   만들지 않는다.
3. **여행 계획 세우기** — 고른 후보를 여행 날짜·인원·동행인·예산(수동 입력)에
   맞춰 하루 단위 초안으로 묶는다. 가까운 곳끼리 같은 날로 묶고(직선거리
   80km, 하루 최대 3곳), 남는 날에는 고르지 않은 후보를 추가 검색 없이 채운다.
   맛집은 하루 일정이 아니라 '식사 옵션'으로 따로 보여준다. 예상 지출을
   채우면 남은 예산을 바로 계산해 준다. **이동 수단(렌트카·가이드 투어·
   대중교통)**을 고르면 일정표의 이동 안내 문구와 예산 지출 항목 이름(렌터카/
   투어 비용/교통비)에 반영된다 (2026-10-30 추가). **숙소**는 '숙소 후보
   찾기' 버튼으로 Places Nearby Search(lodging) 1회를 실행해 여행지 주변
   숙소를 거리순으로 보여주고, 고른 숙소는 일정표·PDF에 박 수마다 '숙박'
   행으로 들어간다 (2026-10-30 추가). 숙소 검색 외에 이 단계는 외부 API를
   부르지 않는다.
4. **공유용 일정표 + PDF (2026-10-30 추가)** — 초안을 날짜·시간·장소(지도
   링크)·설명·이동·비용 표로 보여주고, '📄 PDF로 내보내기' 버튼으로 동행인에게
   보낼 PDF를 만든다. 시간(오전/오후/저녁)과 이동(직선거리·차량 30km/h 가정)은
   **추정**이라고 표시한다 — 실제 이동 시간·교통편·운영시간은 아직 반영하지
   않는다. 이동 칸은 고른 이동 수단 기준으로 표시하고, 투어·대중교통은
   소요시간을 지어내지 않고 '확인 필요'로 둔다. 숙소를 골랐으면 박 수마다
   '숙박' 행이 들어간다 (체크아웃 날 제외). 장소별 비용 데이터는 앱에 없어서,
   비용 칸은 사용자가 직접 적는다 (숙박 행도 같은 방식, PDF에 반영). 빈 날은
   '자유 일정' 행으로 표에 남는다.

## 1단계 범위 / 아직 안 하는 것

- 일정 초안은 **직선거리**로 가까운 곳끼리 묶은 것이다. 실제 이동 시간·
  교통편·운영시간·시간표는 아직 반영하지 않는다 (2단계 작업). 일수에 맞춰
  먼 곳끼리 합친 날은 경고를 표시한다.
- 국내 여행은 아직이다 (카카오 로컬 API 키 필요).
- 영화 제목으로 출발하는 옛 흐름(모듈 1·2)은 코드만 남기고 앱 화면에서는
  뺐다 (`src/pipeline.py`, `src/movie_search.py`, TMDB 클라이언트).
  TMDB 키는 더 이상 필요 없다.
- 예산은 자동 견적 없이 **수동 입력** 그대로다.
- 일정표의 시간·이동 칸은 추정이다 (위 4번 참고). 이동 수단 선택은 표시
  문구와 예산 항목 이름만 바꾼다 — 실제 경로·소요시간 계산은 2단계다.
- 숙소 후보는 Places가 주는 결과를 거리순으로 보여줄 뿐이다. 가격·평점은
  과금 등급(Enterprise SKU)이라 가져오지 않는다.

## 비용 원칙

- 검색은 **버튼을 누를 때만** 나간다. 위젯 조작으로 화면이 다시 그려져도
  재검색하지 않는다 (결과는 세션에 저장).
- 후보 찾기 1회 = Places Nearby Search **카테고리당 1회** (최대 6회).
- 숙소 찾기 1회 = Places Nearby Search(lodging) **1회**.
- 촬영지 찾기를 켜면 웹 검색 최대 5회(Brave·Tavily × 쿼리 2개 + Tavily 본문
  추출 1회) + Places 장소 확인 최대 6회가 더 나간다.
- 검색할 때마다 이번 검색의 호출 수를 화면에 보여준다.
- Places 요청 필드는 **Pro SKU** 범위로 고정했다 (displayName,
  formattedAddress, location, types, googleMapsUri, addressComponents).
  rating·전화번호·영업시간 등 Enterprise SKU 필드는 일부러 제외했다
  (맛집 순위는 평점 대신 현지 요리 타입 휴리스틱). 정확한 최신 과금 기준은
  Google Cloud 콘솔 확인.

## 설치

```bash
pip install -r requirements.txt   # fpdf2 포함 (PDF 내보내기용)
mkdir -p .streamlit
# .streamlit/secrets.toml에 키 입력 (아래 표 참고)
streamlit run app.py
```

## API 키

| 키 | 용도 | 없으면 |
|---|---|---|
| `GOOGLE_PLACES_API_KEY` | 여행지 확인(Text Search) + 명소 후보(Nearby Search) | 앱 사용 불가 |
| `BRAVE_API_KEY` | 촬영지 웹 검색 | 촬영지 찾기 꺼짐 (명소 후보는 동작) |
| `TAVILY_API_KEY` | 촬영지 웹 검색 + 페이지 본문 추출 | 촬영지 찾기 꺼짐 (명소 후보는 동작) |

키는 환경변수 또는 `.streamlit/secrets.toml`에 넣는다 (코드에 키를 적지
않는다). 배포는 Streamlit Community Cloud의 Secrets 설정을 쓴다.

## PDF 한글 글꼴

PDF에 한글을 넣으려면 한글 TTF 글꼴이 필요하다. 아래 순서로 찾는다.

1. `CINEMAP_PDF_FONT` 환경변수에 지정한 글꼴 파일
2. 프로젝트 `fonts/` 폴더의 NotoSansKR-Regular.ttf / NanumGothic-Regular.ttf
   (무료 글꼴, fonts.google.com/noto/fonts 등에서 받는다)
3. Windows 맑은 고딕 (`C:\Windows\Fonts\malgun.ttf`) — 로컬 실행이면
   따로 준비할 것 없음
4. macOS AppleGothic, 리눅스 나눔고딕(~/.fonts, Debian fonts-nanum)

**Streamlit Community Cloud에 배포한다면** 리눅스라 맑은 고딕이 없다.
저장소에 `fonts/NotoSansKR-Regular.ttf`(와 Bold)를 넣어 커밋하면 된다.
글꼴을 찾지 못하면 깨진 PDF를 만들지 않고 안내 메시지를 보여준다.

## 구조

```
app.py                    Streamlit UI (여행지 → 관심사 후보 → 여행 계획)
src/candidates.py         1단계 개편: 여행지 확인 + 관심사/촬영지 후보 수집
src/trip.py               여행 조건(인원/날짜/예산) + 일정 초안 (구 모듈 4)
src/extract_names.py      웹 본문에서 장소 언급 추출 (규칙 기반)
src/nearby.py             거리 계산·맛집 점수 등 공용 로직
src/itinerary.py          공유용 일정표 행 만들기 (시간대·이동 추정·예산 문장)
src/pdf_export.py         일정표 PDF 생성 (한글 글꼴 찾기 + fpdf2)
src/models.py             Candidate/CandidateSet, FilmLocation, TripSettings 등
src/config.py             키 읽기 (환경변수 → st.secrets)
src/errors.py             AuthError / RateLimitError / SourceError
src/sources/gplaces.py        Google Places Text/Nearby Search (New)
src/sources/brave_client.py   Brave Web Search
src/sources/tavily_client.py  Tavily Search/Extract
src/pipeline.py           (보류) 구 모듈 1: 영화 제목 → 촬영지
src/movie_search.py       (보류) 구 모듈 2: TMDB 영화 확정
src/sources/tmdb_client.py  (보류) TMDB 클라이언트
tests/                    131개 테스트 (실제 API 호출 없이 가짜 응답 사용)
```

## 테스트

```bash
python3 -m pytest tests -q   # 131개 통과, 네트워크 호출 없음
```