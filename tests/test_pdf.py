"""PDF 생성 테스트.

가장 중요한 검증은 '폰트가 실제로 모든 문자를 가지고 있는가' 이다. 글리프가
없으면 ReportLab 은 오류를 내지 않고 빈칸으로 렌더링하므로, PDF 가 만들어졌다는
사실만으로는 한글·베트남어가 깨지지 않았다고 말할 수 없다.
"""
from datetime import date

import pytest
from reportlab.pdfbase.ttfonts import TTFont

from core.config import Config
from core.datasource import load_catalog
from core.pdf import (
    FONT_PATH,
    PdfError,
    QuotationMeta,
    build_pdf,
    make_quote_number,
)
from core.pricing import LineInput, calculate_quote

CFG = Config(data_source="csv", sheets_id="", service_account_file="",
             mock_ai=True, anthropic_api_key="")

# PDF 에 실제로 찍히는 고정 문구들 (core/pdf.py 에서 사용하는 라벨).
PDF_LABELS = (
    "QUOTATION 견적서 Báo giá 고객사 Customer 담당자 Contact 이메일 Email 등급 Tier "
    "견적번호 견적일자 유효기간 요청납기 미기재 상품 Description 수량 Qty 단가 Unit price "
    "금액 Amount 공급가액 Subtotal 할인 Discount 과세표준 Taxable 부가세 VAT 합계 TOTAL "
    "재고 확인 필요 Stock requires confirmation 납기 안내 Delivery notice 비고 Remarks "
    "본 견적의 납기는 확정되지 않았습니다 재고 확인 후 별도로 안내드립니다 "
    "표시 금액은 기준이며 공급가액은 세전 금액입니다 까지 유효합니다 "
    "재고는 실시간으로 변동될 수 있어 주문 확정 시 재확인이 필요합니다 "
    "이 견적서는 모드 미호출 로 추출된 요청을 바탕으로 작성되었습니다 "
    "Delivery date is not confirmed in this quotation and will be advised after stock check "
    "고객 요청 납기 확인 전 page ₫ · ⚠ “”"
)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(CFG)


@pytest.fixture(scope="module")
def font_cmap():
    return TTFont("probe", str(FONT_PATH)).face.charToGlyph


def test_font_file_is_bundled():
    assert FONT_PATH.exists(), f"폰트가 없습니다: {FONT_PATH}"
    assert FONT_PATH.stat().st_size > 1_000_000


def test_font_covers_every_character_in_the_data(catalog, font_cmap):
    """고객명(김재훈, Phạm Thị Hương)·주소(Nguyễn Huệ)가 전부 렌더링돼야 한다."""
    text = "".join(
        str(value)
        for frame in (catalog.products, catalog.customers)
        for value in frame.values.ravel()
    ) + "".join(catalog.settings) + "".join(catalog.settings.values())

    missing = sorted({c for c in text if not c.isspace() and ord(c) not in font_cmap})
    assert not missing, f"폰트에 없는 문자: {''.join(missing)}"


def test_font_covers_every_pdf_label(font_cmap):
    missing = sorted({c for c in PDF_LABELS if not c.isspace() and ord(c) not in font_cmap})
    assert not missing, f"폰트에 없는 문자: {''.join(missing)}"


def _meta(**overrides) -> QuotationMeta:
    defaults = dict(
        quote_number="QT-20261107-1200-AB12",
        quote_date=date(2026, 11, 7),
        valid_until=date(2026, 11, 21),
        customer_company="Daewoo Vina Co., Ltd.",
        customer_contact="김재훈",
        customer_email="jh.kim@daewoovina.com.vn",
        customer_tier="VIP",
        company_name="ANB Office Solutions Co., Ltd.",
        company_address="123 Nguyễn Huệ, District 1, Ho Chi Minh City, Vietnam",
        company_email="sales@anb-office.vn",
        delivery_request="다음 주까지",
        notes="첫 거래 감사합니다.\nCảm ơn quý khách — Phạm Thị Hương 담당.",
    )
    defaults.update(overrides)
    return QuotationMeta(**defaults)


def _quote():
    return calculate_quote(
        [
            LineInput("P001", "Monitor 24 inch FHD IPS", 20, 2_850_000),
            LineInput("P005", "Keyboard Wireless", 30, 420_000),
            LineInput("P007", "Mouse Wireless", 30, 165_000),
        ],
        discount_rate=0.10,
        tax_rate=0.10,
    )


def test_build_pdf_produces_a_real_pdf():
    data = build_pdf(_quote(), _meta())
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 10_000


def test_pdf_with_stock_warnings_is_larger():
    """경고가 있으면 문서에 경고 박스가 추가되므로 더 커진다 (= 숨겨지지 않는다)."""
    plain = build_pdf(_quote(), _meta())
    warned = build_pdf(_quote(), _meta(stock_warnings=[
        "Mouse Wireless: 주문 30개 / 재고 18개 — 12개 부족",
        "Monitor: 상품이 확정되지 않았습니다 — 확인 필요",
    ]))
    assert len(warned) > len(plain)


def test_mock_mode_is_disclosed_in_pdf():
    plain = build_pdf(_quote(), _meta())
    mocked = build_pdf(_quote(), _meta(is_mock_ai=True))
    assert len(mocked) > len(plain)


def test_empty_quote_cannot_make_pdf():
    class Empty:
        lines = ()
    with pytest.raises(PdfError):
        build_pdf(Empty(), _meta())


def test_missing_optional_fields_do_not_crash():
    meta = QuotationMeta(
        quote_number="QT-1", quote_date=date(2026, 1, 1), valid_until=date(2026, 1, 15),
        customer_company="X Co",
    )
    assert build_pdf(_quote(), meta).startswith(b"%PDF-")


def test_quote_number_shape_and_uniqueness():
    numbers = {make_quote_number() for _ in range(200)}
    assert len(numbers) > 150, "난수 4자리로 충분히 분산되어야 한다"
    sample = next(iter(numbers))
    assert sample.startswith("QT-")
    assert len(sample.split("-")) == 4


def test_many_lines_paginate_without_error():
    lines = [LineInput(f"P{n:03d}", f"Product line number {n}", n + 1, 100_000 + n)
             for n in range(60)]
    data = build_pdf(calculate_quote(lines, 0.07, 0.1), _meta())
    assert data.startswith(b"%PDF-")


# --- 실제 PDF 에서 텍스트를 다시 꺼내 확인한다 (글리프 + ToUnicode 왕복) ------

def test_multilingual_text_round_trips_through_the_pdf():
    """한글·베트남어·금액이 PDF 안에 올바르게 들어갔는지 추출해서 확인한다.

    글리프가 없으면 ReportLab 은 조용히 빈칸을 그리므로, 추출해서 비교하는 것이
    '깨지지 않았다'를 증명하는 유일한 방법이다.
    """
    pypdf = pytest.importorskip("pypdf")

    data = build_pdf(_quote(), _meta(stock_warnings=[
        "Mouse Wireless: 주문 30개 / 재고 18개 — 12개 부족",
    ]))
    reader = pypdf.PdfReader(__import__("io").BytesIO(data))
    text = "\n".join(page.extract_text() for page in reader.pages)

    for probe in (
        "QUOTATION",
        "견적서",
        "Báo giá",
        "김재훈",                      # 한글 고객 담당자
        "Nguyễn Huệ",                  # 베트남어 주소
        "Phạm Thị Hương",              # 비고의 베트남어 성조
        "Cảm ơn quý khách",
        "다음 주까지",                  # 고객이 쓴 납기 표현
        "74,550,000 VND",              # 공급가액
        "7,455,000 VND",               # 할인
        "6,709,500 VND",               # 부가세
        "73,804,500 VND",              # 합계
        "12개 부족",                    # 재고 경고가 문서에 남아 있다
        "납기는 확정되지 않았습니다",      # 확정되지 않은 납기를 보장하지 않는다
    ):
        assert probe in text, f"PDF 에서 찾지 못함: {probe!r}"
