"""상품 매칭 + 재고 비교 테스트. 실제 data/products.csv 로 검증한다."""
import pytest

from core.ai import RequestedItem
from core.config import Config
from core.datasource import load_catalog
from core.matching import (
    MatchStatus,
    StockStatus,
    match_inquiry,
    match_product,
    stock_summary,
)

CFG = Config(data_source="csv", sheets_id="", service_account_file="",
             mock_ai=True, anthropic_api_key="")


@pytest.fixture(scope="module")
def products():
    return load_catalog(CFG).products


def test_monitor_is_ambiguous(products):
    """Monitor 는 24/27/22(단종) 3종이 있으므로 사용자가 골라야 한다."""
    status, candidates = match_product("Monitor", products)
    assert status is MatchStatus.AMBIGUOUS
    ids = [c.product_id for c in candidates]
    assert "P001" in ids and "P002" in ids
    # 판매중 상품이 단종 상품보다 앞에 온다
    assert candidates[0].active is True


def test_wireless_mouse_resolves_exactly(products):
    """'Wireless Mouse' 는 토큰이 전부 들어맞는 판매중 상품이 하나뿐이다."""
    status, candidates = match_product("Wireless Mouse", products)
    assert status is MatchStatus.EXACT
    assert candidates[0].product_id == "P007"
    assert candidates[0].unit_price == 165000


def test_unknown_product_is_not_found(products):
    status, candidates = match_product("Quantum Teleporter", products)
    assert status is MatchStatus.NOT_FOUND
    assert candidates == []


def test_empty_term_is_not_found(products):
    assert match_product("   ", products)[0] is MatchStatus.NOT_FOUND


def test_price_always_comes_from_the_table(products):
    """후보의 단가는 반드시 Products 테이블 값이어야 한다 (AI 생성 금지)."""
    _, candidates = match_product("A4 Paper", products)
    table = products.set_index("product_id")["unit_price"].to_dict()
    for candidate in candidates:
        assert candidate.unit_price == table[candidate.product_id]


def test_shortage_is_detected_with_exact_quantity(products):
    """Mouse Wireless 재고 18개 < 주문 30개 -> 12개 부족."""
    lines = match_inquiry(
        [RequestedItem(product_term="Wireless Mouse", quantity=30, quoted_text="무선 마우스 30개")],
        products,
    )
    line = lines[0]
    assert line.selected.product_id == "P007"
    assert line.stock_status() is StockStatus.SHORTAGE
    assert line.shortage_quantity() == 12


def test_sufficient_stock_is_ok(products):
    lines = match_inquiry(
        [RequestedItem(product_term="Wired USB Mouse", quantity=10, quoted_text="유선 마우스 10개")],
        products,
    )
    assert lines[0].stock_status() is StockStatus.OK
    assert lines[0].shortage_quantity() == 0


def test_low_stock_is_flagged_even_when_sufficient(products):
    """Filing Cabinet 재고 9개에서 5개 주문 -> 남는 4개, 충분하지만 LOW."""
    lines = match_inquiry(
        [RequestedItem(product_term="Filing Cabinet", quantity=5, quoted_text="캐비닛 5개")],
        products,
    )
    assert lines[0].stock_status() is StockStatus.LOW


def test_zero_stock_is_shortage(products):
    """Whiteboard Marker 재고 0 -> 전량 부족."""
    lines = match_inquiry(
        [RequestedItem(product_term="Whiteboard Marker", quantity=3, quoted_text="마커 3개")],
        products,
    )
    assert lines[0].stock_status() is StockStatus.SHORTAGE
    assert lines[0].shortage_quantity() == 3


def test_discontinued_product_is_never_auto_selected(products):
    """P003 은 active=FALSE 이므로 자동 선택되지 않는다."""
    lines = match_inquiry(
        [RequestedItem(product_term="Monitor 22 inch HD", quantity=2, quoted_text="22인치 모니터")],
        products,
    )
    line = lines[0]
    if line.selected is not None:
        assert line.selected.active is True
        assert line.selected.product_id != "P003"


def test_ambiguous_line_needs_user_choice(products):
    lines = match_inquiry(
        [RequestedItem(product_term="Monitor", quantity=20, quoted_text="모니터 20대")],
        products,
    )
    line = lines[0]
    assert line.needs_user_choice is True
    assert line.stock_status() is StockStatus.UNKNOWN
    assert line.shortage_quantity() == 0  # 판단 불가일 때 숫자를 만들지 않는다


def test_sample_inquiry_end_to_end(products):
    """예시 문의 3건: Monitor 모호 / Keyboard 모호 / Wireless Mouse 부족."""
    lines = match_inquiry(
        [
            RequestedItem(product_term="Monitor", quantity=20, quoted_text="모니터 20대"),
            RequestedItem(product_term="Keyboard", quantity=30, quoted_text="키보드 30개"),
            RequestedItem(product_term="Wireless Mouse", quantity=30, quoted_text="무선 마우스 30개"),
        ],
        products,
    )
    assert [line.status for line in lines] == [
        MatchStatus.AMBIGUOUS, MatchStatus.AMBIGUOUS, MatchStatus.EXACT,
    ]
    summary = stock_summary(lines)
    assert summary["unresolved"] == 2
    assert summary[StockStatus.SHORTAGE.value] == 1
