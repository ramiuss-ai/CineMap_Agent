"""Google Places API (New) - Text Search 클라이언트.

공식 문서 확인일: 2026-10-18 (developers.google.com/maps/documentation/places/web-service/text-search)
- 엔드포인트: POST https://places.googleapis.com/v1/places:searchText
- 인증: X-Goog-Api-Key 헤더
- 필드 마스크 필수: X-Goog-FieldMask
  여기서 쓰는 필드(id, displayName, formattedAddress, location, types,
  googleMapsUri)는 모두 Text Search Pro SKU. rating 등은 Enterprise+Atmosphere
  SKU로 비싸지므로 일부러 제외했다.
- 무료 한도: SKU별 월 무료 호출 제공 (2025년 3월 가격 개편 기준 Pro 월 5,000건).
  최신 한도는 Google Cloud 콘솔에서 확인.
"""
from __future__ import annotations

import time

import requests

from ..errors import AuthError, RateLimitError, UpstreamError
from ..models import ResolvedPlace

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"
# addressComponents는 formattedAddress 등과 같은 Text Search Pro SKU라
# 추가해도 과금 등급이 안 오른다 (2026-10-20 문서 확인).
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.location,places.types,places.googleMapsUri,"
    "places.addressComponents"
)


class GooglePlacesClient:
    def __init__(self, api_key: str, timeout: float = 10.0, max_retries: int = 1,
                 session: requests.Session | None = None,
                 sleep_fn=time.sleep):
        if not api_key:
            raise AuthError("Google Places API 키가 없어요 (GOOGLE_PLACES_API_KEY).")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = session or requests.Session()
        self._sleep = sleep_fn

    def text_search(self, query: str, language_code: str = "ko",
                    region_code: str | None = None,
                    page_size: int = 3) -> list[ResolvedPlace]:
        payload: dict = {
            "textQuery": query,
            "languageCode": language_code,
            "pageSize": max(1, min(page_size, 20)),
        }
        if region_code:
            payload["regionCode"] = region_code
        resp = self._post(TEXT_SEARCH_URL, payload)
        return self._parse(resp)

    def nearby_search(self, lat: float, lon: float, radius_m: float,
                      included_types: list[str], max_results: int = 10,
                      language_code: str = "ko",
                      rank_preference: str = "POPULARITY") -> list[ResolvedPlace]:
        """Nearby Search (New). 모듈 3(주변 맛집/트래킹/역사 명소)에서 쓴다.

        공식 문서 확인일: 2026-10-20
        (developers.google.com/maps/documentation/places/web-service/nearby-search)
        - radius는 0~50000m, maxResultCount는 1~20.
        - rankPreference: POPULARITY(기본) 또는 DISTANCE.
        - 쓰는 필드는 전부 Nearby Search Pro SKU (text_search와 같은 등급).
        """
        payload: dict = {
            "includedTypes": included_types,
            "maxResultCount": max(1, min(max_results, 20)),
            "languageCode": language_code,
            "rankPreference": rank_preference,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": float(radius_m),
                }
            },
        }
        resp = self._post(NEARBY_SEARCH_URL, payload)
        return self._parse(resp)

    def _post(self, url: str, payload: dict) -> requests.Response:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._session.post(url, json=payload,
                                          headers=headers, timeout=self._timeout)
            except requests.RequestException as exc:
                raise UpstreamError(f"Google Places 연결 실패: {exc}") from exc

            if resp.status_code == 200:
                return resp
            if resp.status_code in (400, 401, 403):
                raise AuthError(
                    f"Google Places 인증/설정 오류 (HTTP {resp.status_code}): {resp.text[:200]}"
                )
            if resp.status_code == 429:
                if attempt < self._max_retries:
                    self._sleep(1.0 * (attempt + 1))
                    continue
                raise RateLimitError("Google Places 호출 한도를 초과했어요.")
            if resp.status_code >= 500 and attempt < self._max_retries:
                self._sleep(0.5 * (attempt + 1))
                last_error = UpstreamError(f"Google Places 서버 오류 (HTTP {resp.status_code})")
                continue
            raise UpstreamError(f"Google Places 요청 실패 (HTTP {resp.status_code}): {resp.text[:200]}")
        raise last_error or UpstreamError("Google Places 요청 실패")

    @staticmethod
    def _parse(resp: requests.Response) -> list[ResolvedPlace]:
        try:
            data = resp.json()
        except ValueError as exc:
            raise UpstreamError("Google Places 응답이 JSON이 아니에요.") from exc
        places = []
        for item in data.get("places", []) or []:
            loc = item.get("location") or {}
            lat, lng = loc.get("latitude"), loc.get("longitude")
            if lat is None or lng is None:
                continue  # 좌표 없는 결과는 지도에 쓸 수 없어 제외
            places.append(ResolvedPlace(
                place_id=item.get("id", ""),
                name=(item.get("displayName") or {}).get("text", ""),
                address=item.get("formattedAddress", ""),
                lat=float(lat),
                lon=float(lng),
                types=item.get("types", []) or [],
                google_maps_uri=item.get("googleMapsUri"),
                country_code=_country_code(item),
            ))
        return places


def _country_code(item: dict) -> str | None:
    """addressComponents에서 국가 코드(ISO 3166-1, 예: "KR")를 뽑는다."""
    for comp in item.get("addressComponents") or []:
        if "country" in (comp.get("types") or []):
            code = comp.get("shortText")
            if code:
                return str(code).upper()
    return None
