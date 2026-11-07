"""견적 계산 테스트. 금액은 사람이 손으로 검산할 수 있는 숫자로 확인한다."""
import pytest

from core.pricing import (
    LineInput,
    PricingError,
    calculate_quote,
    format_money,
    lines_from_matches,
)


def test_known_numbers_by_hand():
    """손 검산:
      Monitor 24": 2,850,000 x 20 = 57,000,000
      Keyboard Wireless: 420,000 x 30 = 12,600,000
      Mouse Wireless: 165,000 x 30 =  4,950,000
      소계                           = 74,550,000
      VIP 할인 10%                   =  7,455,000
      과세표준                        = 67,095,000
      VAT 10%                        =  6,709,500 -> 6,709,500 (정수)
      합계                           = 73,804,500
    """
    quote = calculate_quote(
        [
            LineInput("P001", "Monitor 24 inch FHD IPS", 20, 2_850_000),
            LineInput("P005", "Keyboard Wireless", 30, 420_000),
            LineInput("P007", "Mouse Wireless", 30, 165_000),
        ],
        discount_rate=0.10,
        tax_rate=0.10,
    )
    assert quote.subtotal == 74_550_000
    assert quote.discount_amount == 7_455_000
    assert quote.taxable_base == 67_095_000
    assert quote.tax_amount == 6_709_500
    assert quote.total == 73_804_500
    assert quote.quantity_total == 80


def test_line_totals_sum_exactly_to_subtotal():
    """품목 합계의 합이 소계와 1동도 어긋나지 않아야 한다."""
    quote = calculate_quote(
        [LineInput(f"P{n:03d}", f"Item {n}", n + 1, 33_333) for n in range(20)],
        discount_rate=0.07,
        tax_rate=0.1,
    )
    assert sum(line.line_total for line in quote.lines) == quote.subtotal
    assert quote.taxable_base == quote.subtotal - quote.discount_amount
    assert quote.total == quote.taxable_base + quote.tax_amount


def test_discount_applied_before_tax():
    """할인 후 과세. 할인 전 과세였다면 세금이 더 컸을 것이다."""
    quote = calculate_quote(
        [LineInput("P1", "Thing", 1, 1_000_000)], discount_rate=0.5, tax_rate=0.1
    )
    assert quote.discount_amount == 500_000
    assert quote.taxable_base == 500_000
    assert quote.tax_amount == 50_000      # 할인 전이었다면 100,000
    assert quote.total == 550_000


def test_rounding_is_half_up_and_integer():
    """125 * 0.07 = 8.75 -> 9 (올림 반올림), 소수가 남지 않는다."""
    quote = calculate_quote(
        [LineInput("P1", "Thing", 1, 125)], discount_rate=0.07, tax_rate=0
    )
    assert quote.discount_amount == 9
    assert isinstance(quote.discount_amount, int)
    assert quote.total == 116


def test_zero_rates_are_allowed():
    quote = calculate_quote(
        [LineInput("P1", "Thing", 3, 1000)], discount_rate=0, tax_rate=0
    )
    assert quote.subtotal == quote.total == 3000
    assert quote.discount_amount == 0 and quote.tax_amount == 0


def test_zero_price_item_is_allowed():
    """사은품(단가 0)은 허용한다. 음수만 막는다."""
    quote = calculate_quote(
        [LineInput("P1", "Free sample", 5, 0)], discount_rate=0, tax_rate=0.1
    )
    assert quote.total == 0


# --- 계산을 중단해야 하는 경우 --------------------------------------------

@pytest.mark.parametrize("quantity", [0, -5])
def test_bad_quantity_stops_calculation(quantity):
    with pytest.raises(PricingError) as err:
        calculate_quote([LineInput("P1", "Thing", quantity, 1000)], 0, 0.1)
    assert "수량" in str(err.value)


def test_negative_price_stops_calculation():
    with pytest.raises(PricingError) as err:
        calculate_quote([LineInput("P1", "Thing", 1, -1000)], 0, 0.1)
    assert "음수" in str(err.value)


def test_non_integer_quantity_stops_calculation():
    with pytest.raises(PricingError) as err:
        calculate_quote([LineInput("P1", "Thing", 2.5, 1000)], 0, 0.1)
    assert "정수" in str(err.value)


def test_boolean_is_not_accepted_as_quantity():
    """파이썬에서 True == 1 이지만 수량으로는 받지 않는다."""
    with pytest.raises(PricingError):
        calculate_quote([LineInput("P1", "Thing", True, 1000)], 0, 0.1)


def test_blank_product_name_stops_calculation():
    with pytest.raises(PricingError) as err:
        calculate_quote([LineInput("P1", "   ", 1, 1000)], 0, 0.1)
    assert "상품명" in str(err.value)


@pytest.mark.parametrize("rate", [-0.1, 1.5])
def test_out_of_range_discount_stops_calculation(rate):
    with pytest.raises(PricingError) as err:
        calculate_quote([LineInput("P1", "Thing", 1, 1000)], rate, 0.1)
    assert "할인율" in str(err.value)


def test_out_of_range_tax_stops_calculation():
    with pytest.raises(PricingError) as err:
        calculate_quote([LineInput("P1", "Thing", 1, 1000)], 0, 2.0)
    assert "세율" in str(err.value)


def test_empty_quote_stops_calculation():
    with pytest.raises(PricingError) as err:
        calculate_quote([], 0, 0.1)
    assert "품목이 없습니다" in str(err.value)


def test_duplicate_product_stops_calculation():
    with pytest.raises(PricingError) as err:
        calculate_quote(
            [LineInput("P1", "Thing", 1, 1000), LineInput("P1", "Thing", 2, 1000)], 0, 0.1
        )
    assert "두 번" in str(err.value)


def test_unresolved_matches_are_skipped():
    """상품이 확정되지 않은 줄은 견적에 들어가지 않는다."""
    class FakeLine:
        def __init__(self, selected, quantity):
            self.selected = selected
            self.quantity = quantity

    class FakeProduct:
        product_id = "P001"
        product_name = "Monitor 24 inch FHD IPS"
        unit_price = 2_850_000.0

    inputs = lines_from_matches([FakeLine(None, 20), FakeLine(FakeProduct(), 5)])
    assert len(inputs) == 1
    assert inputs[0].unit_price == 2_850_000
    assert isinstance(inputs[0].unit_price, int)


def test_format_money():
    assert format_money(73_804_500) == "73,804,500 VND"
