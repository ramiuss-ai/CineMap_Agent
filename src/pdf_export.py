"""공유용 일정표 PDF 만들기 (2026-10-30, WhatsApp 요청).

동행인에게 보낼 수 있도록 일정표를 PDF로 내보낸다.

한글 글꼴:
- PDF에 한글을 넣으려면 한글이 들어있는 TTF 글꼴이 필요하다.
- Windows에는 맑은 고딕(C:\\Windows\\Fonts\\malgun.ttf)이 기본 설치돼
  있어 로컬 실행에서는 따로 준비할 게 없다.
- Streamlit Community Cloud 등 리눅스에 배포할 때는 저장소 fonts/ 폴더에
  무료 한글 글꼴(예: Noto Sans KR, 나눔고딕)을 넣으면 된다.
- CINEMAP_PDF_FONT 환경변수로 글꼴 경로를 직접 지정할 수도 있다.
- 글꼴을 찾지 못하면 PDF를 만들지 않고 안내 메시지를 보여준다
  (깨진 PDF를 만들지 않는다).

의존성: fpdf2 (pip install fpdf2). 표 안 셀에는 링크를 못 걸어서
장소 링크는 표 아래 '장소 링크' 절에 모아 둔다 (인쇄해도 주소가 보인다).
"""
from __future__ import annotations

import os
from pathlib import Path

from .itinerary import EMPTY, ItineraryRow

# 글꼴을 못 찾았을 때 화면에 보여줄 안내
FONT_HELP = (
    "PDF에 쓸 한글 글꼴을 찾지 못했어요. 아래 중 하나를 해 주세요.\n"
    "- Windows: 맑은 고딕이 있으면 자동으로 찾아요 "
    "(C:\\Windows\\Fonts\\malgun.ttf).\n"
    "- 프로젝트 폴더에 fonts/ 를 만들고 무료 한글 글꼴을 넣어 주세요 "
    "(예: NotoSansKR-Regular.ttf — fonts.google.com/noto/fonts 에서 "
    "무료로 받을 수 있어요).\n"
    "- 또는 CINEMAP_PDF_FONT 환경변수에 글꼴 파일 경로를 지정해 주세요."
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# (regular 후보, bold 후보) 쌍. 위에서부터 찾는다.
_FONT_PAIRS: list[tuple[str, str | None]] = [
    ("fonts/NotoSansKR-Regular.ttf", "fonts/NotoSansKR-Bold.ttf"),
    ("fonts/NanumGothic-Regular.ttf", "fonts/NanumGothic-Bold.ttf"),
    ("fonts/malgun.ttf", "fonts/malgunbd.ttf"),
    (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
    ("/Library/Fonts/AppleGothic.ttf", None),
    ("/System/Library/Fonts/Supplemental/AppleGothic.ttf", None),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
     "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ("~/.fonts/NanumGothic-Regular.ttf", "~/.fonts/NanumGothic-Bold.ttf"),
]

_HEADERS = ("날짜", "시간", "장소", "설명", "이동 (추정)", "비용")
_COL_WIDTHS = (24, 13, 34, 57, 36, 26)  # 합계 190mm (A4 세로 여백 제외 폭)


def find_fonts() -> tuple[str | None, str | None]:
    """(regular, bold) 글꼴 경로. 못 찾으면 (None, None).

    bold가 없으면 regular를 bold 자리에도 쓴다 (fpdf2가 기울임 없이
    같은 글꼴을 등록한다).
    """
    env = os.environ.get("CINEMAP_PDF_FONT")
    if env and Path(env).is_file():
        p = Path(env)
        return str(p), _sibling_bold(p)
    for reg, bold in _FONT_PAIRS:
        reg_path = Path(reg).expanduser()
        if not reg_path.is_absolute():
            reg_path = _PROJECT_ROOT / reg_path
        if reg_path.is_file():
            bold_path = None
            if bold:
                b = Path(bold).expanduser()
                if not b.is_absolute():
                    b = _PROJECT_ROOT / b
                bold_path = str(b) if b.is_file() else None
            return str(reg_path), (bold_path or str(reg_path))
    return None, None


def _sibling_bold(regular: Path) -> str:
    """같은 폴더에서 흔한 Bold 파일명을 찾는다. 없으면 regular 반환."""
    stem = regular.stem
    for cand in (regular.with_name(stem + "-Bold" + regular.suffix),
                 regular.with_name(stem + "Bold" + regular.suffix),
                 regular.with_name("malgunbd.ttf")):
        if cand.is_file():
            return str(cand)
    return str(regular)


def _fmt_cost(cost: int | None) -> str:
    return f"{cost:,}원" if cost else EMPTY


def build_pdf(*, title: str, info_lines: list[str],
              note_lines: list[str], rows: list[ItineraryRow],
              restaurants: list[tuple[str, str]],
              budget: list[str]) -> bytes:
    """일정표 PDF를 만들어 바이트로 반환한다.

    title: "오사카 2박 3일 여행 일정 (초안)" 같은 제목.
    info_lines: 날짜·인원·동행인 등 한 줄 요약들.
    note_lines: 추정·한계 안내 문장들 (정직성 표기).
    rows: build_rows 결과 (cost는 화면에서 입력된 최신 값).
    restaurants: (이름, 링크) 식사 옵션 목록.
    budget: budget_lines() 결과.
    글꼴이 없으면 RuntimeError(FONT_HELP).
    """
    regular, bold = find_fonts()
    if regular is None:
        raise RuntimeError(FONT_HELP)

    from fpdf import FPDF  # 지연 임포트: fpdf2 미설치 시 앱 자체는 동작

    class _TripPDF(FPDF):
        def footer(self):
            self.set_y(-14)
            self.set_font("kfont", "", 8)
            self.set_text_color(140, 140, 140)
            self.cell(0, 6, f"CineMap 일정 초안 — {self.page_no()} / {{nb}}",
                      align="C")

    pdf = _TripPDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_font("kfont", "", regular)
    pdf.add_font("kfont", "B", bold or regular)
    pdf.add_page()

    pdf.set_font("kfont", "B", 16)
    pdf.multi_cell(0, 9, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("kfont", "", 10)
    for line in info_lines:
        pdf.multi_cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("kfont", "", 9)
    pdf.set_text_color(90, 90, 90)
    for line in note_lines:
        pdf.multi_cell(0, 5, "· " + line, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    links: list[tuple[str, str]] = []   # (장소명, URL) — 표 아래 링크 모음

    from fpdf.fonts import FontFace
    pdf.set_font("kfont", "", 9)
    headings = FontFace(emphasis="BOLD", fill_color=(235, 235, 235))
    with pdf.table(col_widths=_COL_WIDTHS, first_row_as_headings=True,
                   line_height=5.5, text_align="LEFT",
                   headings_style=headings) as table:
        header = table.row()
        for h in _HEADERS:
            header.cell(h)
        for r in rows:
            row = table.row()
            row.cell(r.date)
            row.cell(r.time)
            row.cell(r.place)
            row.cell(r.description)
            row.cell(r.transport)
            row.cell(_fmt_cost(r.cost))
            if r.link:
                links.append((r.place, r.link))
    if not rows:
        pdf.multi_cell(0, 6, "일정에 넣은 장소가 없어요.",
                       new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    if restaurants:
        pdf.set_font("kfont", "B", 12)
        pdf.multi_cell(0, 7, "맛집 후보 (식사 옵션)",
                       new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("kfont", "", 9)
        for name, url in restaurants:
            pdf.multi_cell(0, 5.5, f"- {name}", new_x="LMARGIN", new_y="NEXT")
            if url:
                links.append((name, url))
        pdf.ln(2)

    if budget:
        pdf.set_font("kfont", "B", 12)
        pdf.multi_cell(0, 7, "예산 가늠", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("kfont", "", 9)
        for line in budget:
            pdf.multi_cell(0, 5.5, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    if links:
        pdf.set_font("kfont", "B", 12)
        pdf.multi_cell(0, 7, "장소 링크", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("kfont", "", 9)
        for i, (name, url) in enumerate(links, start=1):
            pdf.write(5.5, f"{i}. {name} ")
            pdf.set_text_color(0, 0, 200)
            pdf.write(5.5, "지도 열기", link=url)
            pdf.set_text_color(0, 0, 0)
            pdf.ln()
            # 인쇄본에서도 쓸 수 있게 주소 전체를 작게 적는다
            pdf.set_font("kfont", "", 7)
            pdf.set_text_color(110, 110, 110)
            pdf.multi_cell(0, 4, url, new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("kfont", "", 9)

    return bytes(pdf.output())
