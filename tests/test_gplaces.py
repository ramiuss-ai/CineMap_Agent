import pytest

from src.errors import AuthError, RateLimitError
from src.sources.gplaces import FIELD_MASK, GooglePlacesClient
from tests.conftest import FakeResponse, FakeSession

PAYLOAD = {
    "places": [
        {
            "id": "ChIJabc123",
            "displayName": {"text": "부산역", "languageCode": "ko"},
            "formattedAddress": "부산광역시 동구 중앙대로 206",
            "location": {"latitude": 35.115, "longitude": 129.041},
            "types": ["train_station", "transit_station"],
            "googleMapsUri": "https://maps.google.com/?cid=123",
        },
        {   # 좌표 없는 결과는 걸러야 함
            "id": "ChIJnoloc",
            "displayName": {"text": "좌표없음", "languageCode": "ko"},
            "formattedAddress": "어딘가",
        },
    ]
}


def test_text_search_request_shape(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(200, PAYLOAD)])
    client = GooglePlacesClient("gkey", session=session, sleep_fn=no_sleep)
    places = client.text_search("부산역", language_code="ko", region_code="KR")
    assert len(places) == 1  # 좌표 없는 결과는 제외
    p = places[0]
    assert p.place_id == "ChIJabc123"
    assert p.name == "부산역"
    assert (p.lat, p.lon) == (35.115, 129.041)
    method, url, kwargs = session.calls[0]
    assert url == "https://places.googleapis.com/v1/places:searchText"
    assert kwargs["headers"]["X-Goog-Api-Key"] == "gkey"
    # 필드 마스크는 Pro SKU 범위로 고정 (rating 등 고가 SKU 제외)
    assert kwargs["headers"]["X-Goog-FieldMask"] == FIELD_MASK
    assert "rating" not in FIELD_MASK
    assert kwargs["json"]["textQuery"] == "부산역"
    assert kwargs["json"]["languageCode"] == "ko"
    assert kwargs["json"]["regionCode"] == "KR"


def test_empty_places(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(200, {})])
    client = GooglePlacesClient("gkey", session=session, sleep_fn=no_sleep)
    assert client.text_search("세상에없는장소") == []


def test_rate_limit(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(429), FakeResponse(429)])
    client = GooglePlacesClient("gkey", max_retries=1, session=session, sleep_fn=no_sleep)
    with pytest.raises(RateLimitError):
        client.text_search("부산역")


def test_forbidden_is_auth_error(no_sleep):
    session = FakeSession(post_responses=[FakeResponse(403, text="API not enabled")])
    client = GooglePlacesClient("gkey", session=session, sleep_fn=no_sleep)
    with pytest.raises(AuthError):
        client.text_search("부산역")


def test_missing_key():
    with pytest.raises(AuthError):
        GooglePlacesClient("")
