# 영화 촬영지 찾기 — 모듈 1

영화 제목(한글/영어)을 입력하면 촬영지 후보를 찾아주는 Streamlit 앱의 첫 번째 모듈이에요.

- **Tavily + Brave Search**로 "이 영화 어디서 찍었지?"를 검색하고
- 규칙 기반 추출기가 촬영지 문구를 뽑고 (출처 URL과 함께)
- **Google Places API (New)** 로 각 장소를 이름·주소·좌표·place_id로 확인해요

설계 문서(2026-10-18 File)와의 차이: 원래 설계는 TMDB/KOBIS/KMDb/TourAPI를 쓰지만,
지금 가진 키가 Tavily·Brave·Google Places뿐이라 모듈 1은 이 세 개로만 만들었어요.
데이터 모델은 설계의 `FilmLocation`을 그대로 확장했고(`source_urls`, `confidence`,
`google_maps_uri` 추가), 영화 확정용 `Movie`는 TMDB가 있는 다음 모듈에서 만들어요.

## 파일 구성

```
movie-trip/
├── app.py                     # Streamlit 데모 화면
├── requirements.txt
├── .streamlit/secrets.toml.example  # 키 넣는 곳 (복사해서 사용)
├── src/
│   ├── models.py              # dataclass: FilmLocation, MovieCandidate 등
│   ├── errors.py              # API 오류 종류 (인증/한도/기타)
│   ├── config.py              # 환경변수·st.secrets에서 키 읽기
│   ├── extract_names.py       # 촬영지 문구 규칙 기반 추출 (한/영)
│   ├── pipeline.py            # 전체 흐름: 검색 → 추출 → Places 확인 → 신뢰도
│   └── sources/
│       ├── brave_client.py    # Brave Web Search API
│       ├── tavily_client.py   # Tavily Search + Extract API
│       └── gplaces.py         # Google Places Text Search (New)
└── tests/                     # pytest (실제 API 호출 없이 목 응답 사용)
```

## 실행 방법

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml에 키 3개를 채운 뒤
streamlit run app.py
```

배포(Streamlit Community Cloud)에서는 리포를 연결하고, 키는 앱 설정의
**Secrets**에 같은 이름(`TAVILY_API_KEY`, `BRAVE_API_KEY`, `GOOGLE_PLACES_API_KEY`)으로 넣으면 돼요.
`secrets.toml`은 `.gitignore`에 포함되어 커밋되지 않아요.

테스트(실제 API를 부르지 않고 응답을 흉내낸 목 데이터로 확인):

```bash
python -m pytest tests -q
```

## API 비용·한도 (2026-10-18 공식 문서 기준)

| API | 비용 | 참고 |
|---|---|---|
| Tavily | 무료 플랜 월 1,000 크레딧. 검색 basic 1크레딧/회, 본문 추출 basic 1크레딧/성공 5URL | 한 영화당 검색 2회 + 추출 1회 ≈ 3~4 크레딧 |
| Brave Search | 종량제 크레딧, 웹 검색 $5/1,000건, 초당 50건 | 대시보드에서 크레딧 충전 필요 |
| Google Places (New) | Text Search Pro SKU — 월 무료 호출 제공(2025년 3월 개편 기준 Pro 월 5,000건), 결제계정 필요 | 코드는 Pro SKU 필드만 요청하도록 필드 마스크 고정 (rating 등 고가 SKU 제외) |

한 번 검색하면 대략: Brave 2회 + Tavily 검색 2회 + 추출 1회 + Places 확인 최대 12회.
Places 확인 횟수는 `find_film_locations(..., max_resolve=...)`로 줄일 수 있어요.

## 동작 방식과 한계

1. **모호한 제목**: "부산행"처럼 같은 제목이 여러 편이면 연도 후보를 보여주고 멈춰요
   (Places 크레딧을 쓰기 전에 확인). 연도를 넣으면 바로 진행해요.
2. **결과 없음**: 촬영지 언급을 못 찾으면 에러가 아니라 "못 찾음"으로 안내해요.
3. **부분 실패**: 한 검색 엔진이 죽어도 다른 엔진 결과로 계속하고, 경고를 남겨요.
   한도 초과·인증 오류는 화면에 안내 + "다시 시도" 버튼, 직전 결과가 있으면 함께 보여줘요.
4. **신뢰도(confidence)**: 독립 출처 수(1개 0.6 / 2개 0.8 / 3개+ 1.0, Places 확인 포함)로
   계산하는 단순 추정치예요. 웹 검색 기반이라 **틀린 장소가 섞일 수 있어요** — 근거 링크를
   꼭 열어 확인하세요.
5. **추출기는 규칙 기반**이에요. "촬영지: …", "…에서 촬영", "filmed at …" 같은 패턴을
   찾기 때문에 문장이 특이하면 놓칠 수 있어요. Places 확인 단계가 노이즈를 걸러줘요.

## 다음 모듈에서 할 일 (설계 기준)

- TMDB 키로 영화 확정(포스터·감독) → `Movie` 모델
- 주변 맛집·명소 (TourAPI 또는 Places Nearby Search)
- 일정 생성 엔진 (`DayPlan`)
