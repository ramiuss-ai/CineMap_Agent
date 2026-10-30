"""PDF 내보내기 테스트.

글꼴이 있으면 실제 PDF 바이트를 만들어 검증하고, 없으면 안내 오류가
나는지 확인한다. 한글 렌더링(글리프)은 별도의 시각 확인으로 검증했다
(테스트 환경의 나눔고딕으로 렌더링해 픽셀을 눈으로 확인).
"""
from __future__ import annotations

import os

import pytest

from src import pdf_export
from src.itinerary import ItineraryRow

FONT = os.path.expanduser("~/.fonts/NanumGothic-Regular.ttf")


def _rows():
    return [
        ItineraryRow(date="11월 1일 (일)", time="오전", place="오사카성",
                     link="https://maps.example/H1",
                     description="역사 명소 · 오사카성 주소",
                     transport="—", cost=1500),
        ItineraryRow(date="11월 1일 (일)", time="오후", place="쓰텐카쿠",
                     link="https://maps.example/F1",
                     description="영화 촬영지 (어떤 영화인지는 근거 링크 확인) "
                                 "· 쓰텐카쿠 주소",
                     transport="직선 2.4km · 차 약 5분 (추정)", cost=None),
    ]


@pytest.mark.skipif(not os.path.isfile(FONT), reason="테스트용 한글 글꼴 없음")
def test_build_pdf_bytes(monkeypatch):
    monkeypatch.setenv("CINEMAP_PDF_FONT", FONT)
    pdf = pdf_export.build_pdf(
        title="오사카 2박 3일 여행 일정 (초안)",
        info_lines=["2026년 11월 1일 (일) ~ 11월 3일 (화) (2박 3일, 2명)"],
        note_lines=["추정 안내"],
        rows=_rows(),
        restaurants=[("이치란 도톤보리", "https://maps.example/R1")],
        budget=["입력 예산: 1,000,000원 (전체 기준 · 항공료 포함)"])
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 5000   # 한글 글꼴이 내장돼 있어야 하는 크기


def test_build_pdf_without_font_raises_helpful_error(monkeypatch):
    monkeypatch.delenv("CINEMAP_PDF_FONT", raising=False)
    monkeypatch.setattr(pdf_export, "_FONT_PAIRS", [])
    with pytest.raises(RuntimeError) as excinfo:
        pdf_export.build_pdf(title="t", info_lines=[], note_lines=[],
                             rows=_rows(), restaurants=[], budget=[])
    # 깨진 PDF를 만드는 대신 한글 안내 메시지로 실패한다
    assert "한글 글꼴" in str(excinfo.value)


def test_find_fonts_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "MyFont-Regular.ttf"
    fake.write_bytes(b"fake")
    monkeypatch.setenv("CINEMAP_PDF_FONT", str(fake))
    regular, bold = pdf_export.find_fonts()
    assert regular == str(fake)
    assert bold == str(fake)   # Bold가 없으면 regular로 대체
