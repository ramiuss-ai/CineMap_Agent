from src.extract_names import extract_mentions, mentions_from_results
from src.models import WebResult


def test_korean_esco_pattern():
    text = "이 장면은 통영 동피랑에서 촬영했다고 한다."
    mentions = extract_mentions(text, "https://example.com")
    assert any("통영 동피랑" in m.raw_text for m in mentions)
    assert all(m.source_url == "https://example.com" for m in mentions)


def test_korean_list_pattern():
    text = "부산행 촬영지: 부산역, 동대구역, 해운대 해수욕장"
    mentions = extract_mentions(text, "https://example.com")
    raws = [m.raw_text for m in mentions]
    assert "부산역" in raws
    assert "동대구역" in raws
    assert "해운대 해수욕장" in raws


def test_english_pattern():
    text = "Several scenes were filmed at Glen Etive in the Scottish Highlands."
    mentions = extract_mentions(text, "https://example.com")
    assert any("Glen Etive" in m.raw_text for m in mentions)


def test_dedup_and_clean():
    text = "촬영지: **부산역** (KTX역)\n부산역에서 촬영했다."
    mentions = extract_mentions(text, "https://example.com")
    raws = [m.raw_text.lower() for m in mentions]
    assert raws.count("부산역") == 1  # 중복 제거
    assert "*" not in mentions[0].raw_text  # 마크다운 제거


def test_no_keywords_no_mentions():
    assert extract_mentions("전혀 상관없는 문장입니다.", "https://x.com") == []


def test_mentions_from_results_fallback():
    results = [WebResult(title="부산행 촬영지", url="https://a.com",
                         description="부산역에서 촬영한 장면이 유명하다", engine="brave")]
    mentions = mentions_from_results(results)
    assert any("부산역" in m.raw_text for m in mentions)
