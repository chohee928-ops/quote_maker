"""견적 금액 계산. 모든 계산은 Python 이 하고, AI 는 관여하지 않는다.

금액은 전부 정수 VND 로 다룬다. VND 는 보조 단위(전/센트)가 없고, float 로
비율을 곱하면 0.0000001 같은 오차가 합계에서 드러나기 때문이다. 비율 곱셈은
Decimal + ROUND_HALF_UP 으로 반올림한다.

적용 순서 (이 순서가 금액을 바꾸므로 명시한다):
    1. 품목 합계      line_total = unit_price * quantity
    2. 공급가 소계    subtotal   = sum(line_total)
    3. 등급 할인      discount   = round(subtotal * discount_rate)
    4. 과세 표준      taxable    = subtotal - discount
    5. 부가세         tax        = round(taxable * tax_rate)
    6. 최종 금액      total      = taxable + tax
즉 할인을 먼저 적용하고, 할인된 금액에 세금을 매긴다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MAX_QUANTITY = 1_000_000
MAX_UNIT_PRICE = 10_000_000_000


class PricingError(ValueError):
    """계산을 중단해야 하는 입력 오류. 사용자에게 그대로 보여준다."""


@dataclass(frozen=True)
class LineInput:
    """검토 화면에서 사용자가 수정할 수 있는 견적 한 줄."""
    product_id: str
    product_name: str
    quantity: int
    unit_price: int


@dataclass(frozen=True)
class QuoteLine:
    product_id: str
    product_name: str
    quantity: int
    unit_price: int
    line_total: int


@dataclass(frozen=True)
class Quotation:
    lines: tuple[QuoteLine, ...]
    subtotal: int
    discount_rate: float
    discount_amount: int
    taxable_base: int
    tax_rate: float
    tax_amount: int
    total: int
    currency: str = "VND"

    @property
    def quantity_total(self) -> int:
        return sum(line.quantity for line in self.lines)


def _round_money(amount: Decimal) -> int:
    """VND 는 소수점이 없으므로 1동 단위로 반올림한다."""
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _check_rate(value: float, label: str) -> Decimal:
    try:
        rate = Decimal(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise PricingError(f"{label}이(가) 숫자가 아닙니다: {value!r}") from exc
    if rate < 0 or rate > 1:
        raise PricingError(f"{label}은 0~1 사이여야 합니다. 받은 값: {value}")
    return rate


def _check_line(line: LineInput, index: int) -> QuoteLine:
    where = f"{index + 1}번째 품목"
    name = (line.product_name or "").strip()
    if not name:
        raise PricingError(f"{where}의 상품명이 비어 있습니다.")
    if not isinstance(line.quantity, int) or isinstance(line.quantity, bool):
        raise PricingError(f"'{name}'의 수량이 정수가 아닙니다: {line.quantity!r}")
    if not isinstance(line.unit_price, int) or isinstance(line.unit_price, bool):
        raise PricingError(f"'{name}'의 단가가 정수가 아닙니다: {line.unit_price!r}")
    if line.quantity < 1:
        raise PricingError(f"'{name}'의 수량({line.quantity})이 1 미만입니다.")
    if line.quantity > MAX_QUANTITY:
        raise PricingError(f"'{name}'의 수량({line.quantity:,})이 너무 큽니다. 확인해 주세요.")
    if line.unit_price < 0:
        raise PricingError(f"'{name}'의 단가({line.unit_price:,})가 음수입니다.")
    if line.unit_price > MAX_UNIT_PRICE:
        raise PricingError(f"'{name}'의 단가({line.unit_price:,})가 비정상적으로 큽니다.")
    return QuoteLine(
        product_id=line.product_id,
        product_name=name,
        quantity=line.quantity,
        unit_price=line.unit_price,
        line_total=line.unit_price * line.quantity,   # 둘 다 정수이므로 오차가 없다
    )


def calculate_quote(
    lines: list[LineInput],
    discount_rate: float,
    tax_rate: float,
    currency: str = "VND",
) -> Quotation:
    """견적 금액을 계산한다. 입력이 잘못되면 PricingError 로 계산을 중단한다."""
    if not lines:
        raise PricingError("견적에 포함할 품목이 없습니다.")

    discount = _check_rate(discount_rate, "할인율")
    tax = _check_rate(tax_rate, "세율")

    quote_lines = tuple(_check_line(line, i) for i, line in enumerate(lines))

    seen: set[str] = set()
    for line in quote_lines:
        if line.product_id and line.product_id in seen:
            raise PricingError(
                f"같은 상품이 두 번 들어 있습니다: {line.product_name} ({line.product_id}). "
                "수량을 합쳐 주세요."
            )
        seen.add(line.product_id)

    subtotal = sum(line.line_total for line in quote_lines)
    discount_amount = _round_money(Decimal(subtotal) * discount)
    taxable_base = subtotal - discount_amount
    tax_amount = _round_money(Decimal(taxable_base) * tax)
    total = taxable_base + tax_amount

    return Quotation(
        lines=quote_lines,
        subtotal=subtotal,
        discount_rate=float(discount),
        discount_amount=discount_amount,
        taxable_base=taxable_base,
        tax_rate=float(tax),
        tax_amount=tax_amount,
        total=total,
        currency=currency,
    )


def lines_from_matches(matched_lines) -> list[LineInput]:
    """MatchedLine 목록 -> LineInput 목록. 상품이 확정되지 않은 줄은 제외한다."""
    inputs: list[LineInput] = []
    for line in matched_lines:
        product = line.selected
        if product is None:
            continue
        inputs.append(
            LineInput(
                product_id=product.product_id,
                product_name=product.product_name,
                quantity=int(line.quantity),
                unit_price=int(product.unit_price),
            )
        )
    return inputs


def format_money(amount: float | int, currency: str = "VND") -> str:
    return f"{int(round(amount)):,} {currency}"
