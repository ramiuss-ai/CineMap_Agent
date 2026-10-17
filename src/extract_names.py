"""웹 문서(마크다운/텍스트/스니펫)에서 촬영지 후보 문구를 뽑는 규칙 기반 추출기.

LLM 없이 동작하므로 완벽하지 않다. 노이즈가 섞일 수 있어서
이후 Google Places 확인 단계에서 걸러지는 구조다.
"""
from __future__ import annotations

import re

from .models import LocationMention, WebResult

# 한국어 촬영지 관련 키워드
KO_KEYWORDS = ("촬영지", "촬영 장소", "로케이션", "촬영된", "촬영한 곳", "촬영했다")
# 영어 키워드
EN_KEYWORDS = ("filming location", "filmed at", "filmed in", "shot at", "shot in",
               "was filmed", "were filmed", "took place in")

# "X에서 촬영" 패턴: 조사 '에서' 앞의 장소명(한글 2~20자, 공백 포함)
_KO_PLACE_RE = re.compile(r"([가-힣][가-힣A-Za-z0-9·\- ]{1,20}?)에서\s*촬영")
# 콜론/대시 뒤 장소 나열: "촬영지: 통영 동피랑, 여수 향일암"
_KO_LIST_RE = re.compile(r"(?:촬영지|로케이션|촬영 장소)\s*[:：\-]\s*([^\n]{2,120})")
# 영어: filmed at/in X, shot at/in X (X는 대문자로 시작하는 장소명 조각)
_EN_PLACE_RE = re.compile(
    r"(?:filmed|shot)\s+(?:at|in)\s+([A-Z][A-Za-z0-9'&.,\- ]{2,60})")
# 마크다운 목록 항목 "- 장소명" (촬영지 섹션 안에서만 사용)
_MD_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s*(.+?)\s*$")

_MIN_LEN = 2
_MAX_LEN = 60


def extract_mentions(text: str, source_url: str, max_mentions: int = 15) -> list[LocationMention]:
    """문서 하나에서 촬영지 후보 문구를 뽑는다."""
    if not text:
        return []
    mentions: list[LocationMention] = []
    seen: set[str] = set()

    def add(raw: str, snippet: str):
        cleaned = _clean(raw)
        if not (_MIN_LEN <= len(cleaned) <= _MAX_LEN):
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        mentions.append(LocationMention(raw_text=cleaned, source_url=source_url,
                                        snippet=snippet.strip()[:200]))

    for line in text.splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        lower = line_s.lower()

        for m in _KO_PLACE_RE.finditer(line_s):
            add(m.group(1), line_s)
        for m in _KO_LIST_RE.finditer(line_s):
            # 콤마/가운데점으로 나열된 장소들을 쪼갠다
            for part in re.split(r"[,，、·/]", m.group(1)):
                add(part, line_s)
        if any(k in lower for k in EN_KEYWORDS):
            for m in _EN_PLACE_RE.finditer(line_s):
                add(m.group(1), line_s)
        # 촬영지 키워드가 있는 섹션의 목록 항목
        if any(k in line_s for k in KO_KEYWORDS) or any(k in lower for k in EN_KEYWORDS):
            m = _MD_ITEM_RE.match(line_s)
            if m:
                add(m.group(1), line_s)
        if len(mentions) >= max_mentions:
            break

    return mentions[:max_mentions]


def mentions_from_results(results: list[WebResult],
                          max_per_result: int = 5) -> list[LocationMention]:
    """검색 결과의 제목+스니펫에서 추출 (본문 추출 실패 시 폴백)."""
    out: list[LocationMention] = []
    for r in results:
        text = f"{r.title}\n{r.description}"
        out.extend(extract_mentions(text, r.url, max_mentions=max_per_result))
    return out


def _clean(raw: str) -> str:
    """마크다운 꾸밈, 괄호 설명, 양끝 조사/불필요 문자 정리."""
    s = re.sub(r"[*_`\[\]#>]", "", raw)
    s = re.sub(r"\([^)]*\)", "", s)  # (설명) 제거
    s = re.sub(r"\s+", " ", s).strip(" ,.;:!?·-")
    return s
