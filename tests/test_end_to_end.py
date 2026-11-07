"""명세의 '최종 완료 조건' 시나리오를 UI 를 실제로 조작해 검증한다.

    1. 고객 문의 입력      5. 재고 부족 시 경고
    2. 상품·수량 추출      6. 정확한 금액 계산
    3. Sheets/CSV 조회     7. 사용자 검토와 수정
    4. 상품 자동 매칭      8. PDF 다운로드
                          9. 이메일 초안 생성

MOCK_AI=true 를 강제하므로 실제 Claude API 를 호출하지 않는다 (비용 0).
"""
import os

import pytest
from streamlit.testing.v1 import AppTest

from core.config import PROJECT_ROOT

APP = str(PROJECT_ROOT / "app.py")
SAMPLE = "모니터 20대, 키보드 30개, 무선 마우스 30개가 필요합니다. 다음 주까지 가능한가요?"


@pytest.fixture(autouse=True)
def force_mock_mode(monkeypatch):
    """테스트에서 실제 API 를 호출하지 않도록 강제한다."""
    monkeypatch.setitem(os.environ, "MOCK_AI", "true")
    monkeypatch.setitem(os.environ, "DATA_SOURCE", "csv")


def _run_quotation_page() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("New Quotation").run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _click(at: AppTest, label: str) -> AppTest:
    for button in at.button:
        if button.label == label:
            return button.click().run()
    raise AssertionError(f"버튼을 찾을 수 없습니다: {label!r} "
                         f"(있는 버튼: {[b.label for b in at.button]})")


def _texts(at: AppTest) -> str:
    """화면에 나온 모든 텍스트를 한 덩어리로 모은다."""
    chunks = []
    for collection in (at.markdown, at.success, at.warning, at.error,
                       at.info, at.caption, at.metric):
        for element in collection:
            chunks.append(str(getattr(element, "value", "")))
            chunks.append(str(getattr(element, "label", "")))
    return "\n".join(chunks)


def test_step_1_and_2_inquiry_is_analyzed():
    at = _run_quotation_page()
    at = _click(at, "예시 문의 채우기")
    assert at.session_state["inquiry_text"].startswith("안녕하세요")

    at = _click(at, "AI로 분석하기")
    parsed = at.session_state["parsed"]
    assert parsed.is_mock is True
    assert len(parsed.items) == 3
    assert parsed.requested_delivery_text == "다음 주까지"
    # MOCK 임이 화면에 분명히 표시된다
    assert "MOCK" in _texts(at)


def test_step_3_and_4_products_are_matched_from_the_catalog():
    at = _run_quotation_page()
    at = _click(at, "예시 문의 채우기")
    at = _click(at, "AI로 분석하기")

    matched = at.session_state["matched"]
    assert len(matched) == 3
    terms = [line.product_term for line in matched]
    assert terms == ["Monitor", "Keyboard", "Wireless Mouse"]

    # Wireless Mouse 는 자동 확정되고, 단가는 Products 테이블 값이다
    mouse = matched[2]
    assert mouse.selected is not None
    assert mouse.selected.product_id == "P007"
    assert mouse.selected.unit_price == 165000

    # Monitor / Keyboard 는 후보가 여러 개라 사용자가 골라야 한다
    assert matched[0].needs_user_choice is True
    assert matched[1].needs_user_choice is True


def test_step_5_shortage_is_warned_on_screen():
    """Mouse Wireless 재고 18개 < 주문 30개 -> 12개 부족 경고."""
    at = _run_quotation_page()
    at = _click(at, "예시 문의 채우기")
    at = _click(at, "AI로 분석하기")

    screen = _texts(at)
    assert "재고 부족" in screen
    assert "12개 부족" in screen


def test_step_6_to_9_full_flow_with_user_choices():
    at = _run_quotation_page()
    at = _click(at, "예시 문의 채우기")
    at = _click(at, "AI로 분석하기")

    # --- 7. 사용자가 모호한 상품을 직접 선택한다 ---
    at.selectbox(key="pick_0").set_value("P001").run()   # Monitor 24 inch FHD IPS
    at.selectbox(key="pick_1").set_value("P005").run()   # Keyboard Wireless
    assert not at.exception, [e.value for e in at.exception]

    # --- 6. 금액 계산 (손 검산) ---
    # 2,850,000*20 + 420,000*30 + 165,000*30 = 74,550,000
    # C001 VIP 10% 할인 -> 7,455,000 / 과세 67,095,000 / VAT 10% 6,709,500
    # 합계 73,804,500
    quote, meta = at.session_state["last_quote"]
    assert quote.subtotal == 74_550_000
    assert quote.discount_amount == 7_455_000
    assert quote.tax_amount == 6_709_500
    assert quote.total == 73_804_500

    # 재고 부족이 견적서 경고로 넘어간다 (숨기지 않는다)
    assert any("12개 부족" in w for w in meta.stock_warnings)

    # --- 7. 수량을 수정하면 금액이 다시 계산된다 ---
    at.number_input(key="qty_0").set_value(10).run()
    quote_after, _ = at.session_state["last_quote"]
    assert quote_after.subtotal == 74_550_000 - (2_850_000 * 10)
    assert quote_after.total != quote.total

    # 수량을 되돌린다
    at.number_input(key="qty_0").set_value(20).run()

    # --- 7. 할인율을 수정해도 다시 계산된다 ---
    at.number_input(key="discount_pct").set_value(0.0).run()
    no_discount, _ = at.session_state["last_quote"]
    assert no_discount.discount_amount == 0
    assert no_discount.total == 74_550_000 + 7_455_000  # 74,550,000 + VAT 10%
    at.number_input(key="discount_pct").set_value(10.0).run()

    # --- 8. PDF 생성과 다운로드 ---
    at = _click(at, "PDF 견적서 만들기")
    pdf = at.session_state["pdf_bytes"]
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 10_000
    assert at.session_state["pdf_name"].endswith(".pdf")
    assert any(b.label == "⬇️ PDF 다운로드" for b in at.download_button)

    # --- 9. 이메일 초안 ---
    at = _click(at, "이메일 초안 작성")
    draft = at.session_state["email_draft"]
    assert draft.is_mock is True
    assert draft.subject.strip()
    assert f"{quote.total:,}" in draft.body

    assert not at.exception, [e.value for e in at.exception]


def test_email_draft_in_vietnamese():
    at = _run_quotation_page()
    at = _click(at, "예시 문의 채우기")
    at = _click(at, "AI로 분석하기")
    at.selectbox(key="pick_0").set_value("P001").run()
    at.selectbox(key="pick_1").set_value("P005").run()

    at.selectbox(key="email_language").set_value("vi").run()
    at = _click(at, "이메일 초안 작성")
    draft = at.session_state["email_draft"]
    assert draft.language == "vi"
    assert "Trân trọng" in draft.body


def test_preview_page_shows_the_last_quote():
    at = _run_quotation_page()
    at = _click(at, "예시 문의 채우기")
    at = _click(at, "AI로 분석하기")
    at.selectbox(key="pick_0").set_value("P001").run()
    at.selectbox(key="pick_1").set_value("P005").run()

    at.sidebar.radio[0].set_value("Quotation Preview").run()
    assert not at.exception, [e.value for e in at.exception]
    screen = _texts(at)
    assert "73,804,500" in screen


def test_unselected_products_are_excluded_and_flagged():
    """상품을 고르지 않으면 견적에서 빠지고, 견적서 경고에 남는다."""
    at = _run_quotation_page()
    at = _click(at, "예시 문의 채우기")
    at = _click(at, "AI로 분석하기")
    # Monitor / Keyboard 를 고르지 않은 상태 -> Wireless Mouse 만 견적에 들어간다
    quote, meta = at.session_state["last_quote"]
    assert len(quote.lines) == 1
    assert quote.lines[0].product_id == "P007"
    assert sum("확인 필요" in w for w in meta.stock_warnings) == 2


def test_changing_customer_resets_the_discount_to_the_new_tier():
    """고객을 바꾸면 이전 고객의 할인율이 남아 있어서는 안 된다."""
    at = _run_quotation_page()
    at = _click(at, "예시 문의 채우기")
    at = _click(at, "AI로 분석하기")
    at.selectbox(key="pick_0").set_value("P001").run()

    # C001 = VIP 10%
    first, meta = at.session_state["last_quote"]
    assert meta.customer_tier == "VIP"
    assert first.discount_rate == pytest.approx(0.10)
    assert first.discount_amount > 0

    # C008 = Standard 0% -> 할인이 0 으로 바뀌어야 한다
    at.selectbox(key="customer_id").set_value("C008").run()
    second, meta2 = at.session_state["last_quote"]
    assert meta2.customer_tier == "Standard"
    assert meta2.customer_company == "Can Tho Trading Co."
    assert second.discount_rate == pytest.approx(0.0)
    assert second.discount_amount == 0
    assert second.total > first.total      # 할인이 없어지면 합계가 커진다


def test_manual_discount_override_survives_a_rerun():
    """사용자가 직접 바꾼 할인율은 같은 고객에서는 유지된다."""
    at = _run_quotation_page()
    at = _click(at, "예시 문의 채우기")
    at = _click(at, "AI로 분석하기")
    at.selectbox(key="pick_0").set_value("P001").run()

    at.number_input(key="discount_pct").set_value(25.0).run()
    at.number_input(key="valid_days").set_value(30).run()   # 다른 입력을 건드려 rerun
    quote, _ = at.session_state["last_quote"]
    assert quote.discount_rate == pytest.approx(0.25)
