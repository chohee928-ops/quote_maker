"""ReportLab 으로 전문적인 PDF 견적서를 만든다.

폰트: assets/fonts/NotoSansKR.ttf 하나로 영문·한글·베트남어를 모두 렌더링한다.
윈도우에는 한글과 베트남어를 동시에 커버하는 기본 폰트가 없고(malgun 은 ệễịư
누락, arial 은 한글 누락), Streamlit Cloud 는 리눅스라 C:/Windows/Fonts 가 아예
없다. 그래서 시스템 폰트에 의존하지 않고 프로젝트에 포함한다.

shortcut: 굵은 글씨용 Bold 폰트는 넣지 않았다 (가변 폰트라 ReportLab 이 굵기
축을 적용하지 못한다). 강조는 글자 크기·색·배경으로 처리한다. 진짜 Bold 가
필요해지면 NotoSansKR-Bold 정적 폰트를 같은 폴더에 추가하고 register_fonts()
에서 등록한다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .config import PROJECT_ROOT
from .pricing import Quotation, format_money

FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "NotoSansKR.ttf"
LOGO_PATH = PROJECT_ROOT / "assets" / "logo.png"
FONT_NAME = "NotoSansKR"

INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#6B7280")
ACCENT = colors.HexColor("#1D4ED8")
WARN_BG = colors.HexColor("#FEF3C7")
WARN_INK = colors.HexColor("#92400E")
LINE = colors.HexColor("#D8DEE6")
HEAD_BG = colors.HexColor("#EEF2F7")

_registered = False


class PdfError(RuntimeError):
    """사용자에게 그대로 보여줄 수 있는 PDF 생성 오류."""


def register_fonts() -> str:
    """내장 폰트를 등록하고 폰트 이름을 돌려준다."""
    global _registered
    if _registered:
        return FONT_NAME
    if not FONT_PATH.exists():
        raise PdfError(
            f"폰트 파일이 없습니다: {FONT_PATH}\n"
            "한글·베트남어가 깨지지 않도록 Noto Sans KR 이 필요합니다. "
            "README의 '폰트' 항목을 참고하세요."
        )
    try:
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
    except Exception as exc:
        raise PdfError(f"폰트를 등록할 수 없습니다: {type(exc).__name__}") from exc
    _registered = True
    return FONT_NAME


def make_quote_number(when: datetime | None = None) -> str:
    """데모용 견적 번호.

    shortcut: 날짜 + 시각 + 난수 4자리이므로 이론상 중복이 가능하다. 2단계에서
    DB 시퀀스 기반 고유 번호로 바꾼다.
    """
    when = when or datetime.now()
    suffix = f"{random.randint(0, 0xFFFF):04X}"
    return f"QT-{when:%Y%m%d}-{when:%H%M}-{suffix}"


@dataclass
class QuotationMeta:
    quote_number: str
    quote_date: date
    valid_until: date
    customer_company: str
    customer_contact: str = ""
    customer_email: str = ""
    customer_tier: str = ""
    company_name: str = ""
    company_address: str = ""
    company_email: str = ""
    company_phone: str = ""
    delivery_request: str = ""
    notes: str = ""
    stock_warnings: list[str] = field(default_factory=list)
    is_mock_ai: bool = False


class LogoMark(Flowable):
    """로고 이미지가 없을 때 쓰는 대체 마크. 회사명 첫 글자들을 넣은 사각형."""

    def __init__(self, text: str, width: float = 16 * mm, height: float = 16 * mm):
        super().__init__()
        self.text = text[:2].upper() or "Q"
        self.width = width
        self.height = height

    def draw(self) -> None:
        canvas = self.canv
        canvas.setFillColor(ACCENT)
        canvas.roundRect(0, 0, self.width, self.height, 3 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont(FONT_NAME, 8 * mm * 0.72)
        canvas.drawCentredString(self.width / 2, self.height * 0.32, self.text)


def _initials(name: str) -> str:
    words = [w for w in name.replace(",", " ").split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]) or "Q"


def _styles(font: str) -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName=font, fontSize=9, leading=13, textColor=INK)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7.5, leading=10.5, textColor=MUTED),
        "title": ParagraphStyle("title", parent=base, fontSize=26, leading=30, textColor=ACCENT),
        "company": ParagraphStyle("company", parent=base, fontSize=12, leading=16),
        "label": ParagraphStyle("label", parent=base, fontSize=7.5, leading=10, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.5, leading=11.5),
        "cellr": ParagraphStyle("cellr", parent=base, fontSize=8.5, leading=11.5, alignment=TA_RIGHT),
        "head": ParagraphStyle("head", parent=base, fontSize=8, leading=11, textColor=MUTED),
        "headr": ParagraphStyle("headr", parent=base, fontSize=8, leading=11,
                                textColor=MUTED, alignment=TA_RIGHT),
        "warn": ParagraphStyle("warn", parent=base, fontSize=8.5, leading=12, textColor=WARN_INK),
        "total": ParagraphStyle("total", parent=base, fontSize=13, leading=17,
                                textColor=ACCENT, alignment=TA_RIGHT),
        "center": ParagraphStyle("center", parent=base, fontSize=7.5, leading=10,
                                 textColor=MUTED, alignment=TA_CENTER),
    }


def _header(meta: QuotationMeta, st: dict) -> Table:
    if LOGO_PATH.exists():
        from reportlab.platypus import Image
        logo = Image(str(LOGO_PATH), width=16 * mm, height=16 * mm, kind="proportional")
    else:
        logo = LogoMark(_initials(meta.company_name))

    left = [
        logo,
        Spacer(1, 3 * mm),
        Paragraph(meta.company_name or "-", st["company"]),
    ]
    contact = [line for line in (meta.company_address, meta.company_email, meta.company_phone) if line]
    if contact:
        left.append(Paragraph("<br/>".join(contact), st["small"]))

    right = [
        Paragraph("QUOTATION", st["title"]),
        Spacer(1, 1 * mm),
        Paragraph("견적서 · Báo giá", st["small"]),
    ]

    table = Table([[left, right]], colWidths=[95 * mm, 75 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _field_block(pairs: list[tuple[str, str]], st: dict, width: float) -> Table:
    rows = []
    for label, value in pairs:
        rows.append([
            Paragraph(label, st["label"]),
            Paragraph(value or "-", st["cell"]),
        ])
    table = Table(rows, colWidths=[width * 0.38, width * 0.62])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return table


def _meta_section(meta: QuotationMeta, st: dict) -> Table:
    customer = [
        ("고객사 / Customer", meta.customer_company),
        ("담당자 / Contact", meta.customer_contact),
        ("이메일 / Email", meta.customer_email),
        ("등급 / Tier", meta.customer_tier),
    ]
    quote = [
        ("견적번호 / No.", meta.quote_number),
        ("견적일자 / Date", meta.quote_date.isoformat()),
        ("유효기간 / Valid until", meta.valid_until.isoformat()),
        ("요청납기 / Requested", meta.delivery_request or "미기재"),
    ]
    table = Table(
        [[_field_block(customer, st, 80 * mm), _field_block(quote, st, 80 * mm)]],
        colWidths=[88 * mm, 82 * mm],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
    ]))
    return table


def _items_table(quote: Quotation, st: dict) -> Table:
    header = [
        Paragraph("#", st["head"]),
        Paragraph("상품 / Description", st["head"]),
        Paragraph("수량<br/>Qty", st["headr"]),
        Paragraph(f"단가 ({quote.currency})<br/>Unit price", st["headr"]),
        Paragraph(f"금액 ({quote.currency})<br/>Amount", st["headr"]),
    ]
    rows = [header]
    for index, line in enumerate(quote.lines, start=1):
        name = line.product_name
        if line.product_id:
            name += f'<br/><font size="7" color="#6B7280">{line.product_id}</font>'
        rows.append([
            Paragraph(str(index), st["cell"]),
            Paragraph(name, st["cell"]),
            Paragraph(f"{line.quantity:,}", st["cellr"]),
            Paragraph(f"{line.unit_price:,}", st["cellr"]),
            Paragraph(f"{line.line_total:,}", st["cellr"]),
        ])

    table = Table(rows, colWidths=[8 * mm, 82 * mm, 18 * mm, 30 * mm, 32 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFBFC")]),
    ]))
    return table


def _totals_table(quote: Quotation, st: dict) -> Table:
    discount_label = f"할인 / Discount ({quote.discount_rate * 100:g}%)"
    tax_label = f"부가세 / VAT ({quote.tax_rate * 100:g}%)"
    rows = [
        [Paragraph("공급가액 / Subtotal", st["cell"]),
         Paragraph(format_money(quote.subtotal, quote.currency), st["cellr"])],
        [Paragraph(discount_label, st["cell"]),
         Paragraph("- " + format_money(quote.discount_amount, quote.currency), st["cellr"])],
        [Paragraph("과세표준 / Taxable", st["cell"]),
         Paragraph(format_money(quote.taxable_base, quote.currency), st["cellr"])],
        [Paragraph(tax_label, st["cell"]),
         Paragraph(format_money(quote.tax_amount, quote.currency), st["cellr"])],
        [Paragraph("합계 / TOTAL", st["cell"]),
         Paragraph(format_money(quote.total, quote.currency), st["total"])],
    ]
    table = Table(rows, colWidths=[55 * mm, 45 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, ACCENT),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F5F8FF")),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    return table


def _notice_box(title: str, lines: list[str], st: dict, background=WARN_BG) -> Table:
    body = [Paragraph(title, st["warn"])]
    body += [Paragraph(f"• {text}", st["warn"]) for text in lines]
    table = Table([[body]], colWidths=[170 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("BOX", (0, 0), (-1, -1), 0.5, WARN_INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))
    return table


def build_pdf(quote: Quotation, meta: QuotationMeta) -> bytes:
    """견적서 PDF 를 바이트로 돌려준다."""
    if not quote.lines:
        raise PdfError("견적에 품목이 없어 PDF 를 만들 수 없습니다.")

    font = register_fonts()
    st = _styles(font)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Quotation {meta.quote_number}",
        author=meta.company_name or "Quotation",
        subject="Quotation",
    )

    story: list = [
        _header(meta, st),
        Spacer(1, 6 * mm),
        _meta_section(meta, st),
        Spacer(1, 6 * mm),
        _items_table(quote, st),
        Spacer(1, 5 * mm),
        _totals_table(quote, st),
        Spacer(1, 6 * mm),
    ]

    # 재고 부족·미확인 항목은 절대 숨기지 않는다.
    if meta.stock_warnings:
        story.append(_notice_box(
            "재고 확인 필요 / Stock requires confirmation",
            meta.stock_warnings, st,
        ))
        story.append(Spacer(1, 4 * mm))

    delivery_notice = [
        "본 견적의 납기는 확정되지 않았습니다. 재고 확인 후 별도로 안내드립니다.",
        "Delivery date is not confirmed in this quotation and will be advised after stock check.",
    ]
    if meta.delivery_request:
        delivery_notice.insert(0, f"고객 요청 납기: \u201c{meta.delivery_request}\u201d (확인 전)")
    story.append(_notice_box(
        "납기 안내 / Delivery notice", delivery_notice, st,
        background=colors.HexColor("#EFF6FF"),
    ))
    story.append(Spacer(1, 5 * mm))

    remarks = [
        Paragraph("비고 / Remarks", st["label"]),
        Spacer(1, 1.5 * mm),
        Paragraph(meta.notes.replace("\n", "<br/>") if meta.notes.strip() else "-", st["cell"]),
        Spacer(1, 3 * mm),
        Paragraph(
            f"· 표시 금액은 {quote.currency} 기준이며 공급가액은 세전 금액입니다.<br/>"
            f"· 본 견적은 {meta.valid_until.isoformat()} 까지 유효합니다.<br/>"
            "· 재고는 실시간으로 변동될 수 있어 주문 확정 시 재확인이 필요합니다.",
            st["small"],
        ),
    ]
    story.append(KeepTogether(remarks))

    if meta.is_mock_ai:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(
            "⚠ 이 견적서는 MOCK 모드(AI 미호출)로 추출된 요청을 바탕으로 작성되었습니다.",
            st["warn"],
        ))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(
            A4[0] / 2, 10 * mm,
            f"{meta.company_name}  ·  {meta.quote_number}  ·  page {document.page}",
        )
        canvas.restoreState()

    try:
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
    except Exception as exc:
        raise PdfError(f"PDF 생성 중 오류가 발생했습니다: {type(exc).__name__}: {exc}") from exc

    return buffer.getvalue()
