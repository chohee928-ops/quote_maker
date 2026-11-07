"""AI 추출 로직 테스트.

실제 Claude API는 호출하지 않는다 (비용/속도/재현성). 항상 mock_ai=True 설정을
주입하고, AI 결과 검증 로직은 가짜 응답으로 직접 테스트한다.
"""
import pytest

from core.ai import (
    MAX_ITEMS,
    AIError,
    InquiryExtraction,
    RequestedItem,
    parse_inquiry,
    validate_extraction,
)
from core.config import Config

MOCK_CFG = Config(
    data_source="csv", sheets_id="", service_account_file="",
    mock_ai=True, anthropic_api_key="", claude_model="claude-opus-5-5",
)


def _extraction(items, **kwargs):
    return InquiryExtraction(
        items=items,
        requested_delivery_text=kwargs.get("delivery"),
        customer_notes=kwargs.get("notes", []),
        language=kwargs.get("language", "ko"),
    )


def test_empty_inquiry_rejected_before_api_call():
    with pytest.raises(AIError) as err:
        parse_inquiry("   ", cfg=MOCK_CFG)
    assert "비어" in str(err.value)


def test_overlong_inquiry_rejected_before_api_call():
    with pytest.raises(AIError) as err:
        parse_inquiry("가" * 5000, cfg=MOCK_CFG)
    assert "너무 깁니다" in str(err.value)


def test_mock_mode_is_clearly_marked():
    result = parse_inquiry("모니터 20대 주세요", cfg=MOCK_CFG)
    assert result.is_mock is True
    assert any("MOCK" in w for w in result.warnings)
    assert len(result.items) == 3


def test_zero_and_negative_quantities_are_dropped():
    raw = _extraction([
        RequestedItem(product_term="Monitor", quantity=20, quoted_text="모니터 20대"),
        RequestedItem(product_term="Keyboard", quantity=0, quoted_text="키보드"),
        RequestedItem(product_term="Mouse", quantity=-5, quoted_text="마우스"),
    ])
    items, warnings = validate_extraction(raw)
    assert [i.product_term for i in items] == ["Monitor"]
    assert len(warnings) == 2


def test_absurd_quantity_is_flagged_not_accepted():
    raw = _extraction([
        RequestedItem(product_term="Paper", quantity=99_000_000, quoted_text="용지"),
    ])
    items, warnings = validate_extraction(raw)
    assert items == []
    assert any("비정상적으로 큽" in w for w in warnings)


def test_blank_and_overlong_product_names_dropped():
    raw = _extraction([
        RequestedItem(product_term="   ", quantity=5, quoted_text="?"),
        RequestedItem(product_term="X" * 200, quantity=5, quoted_text="?"),
    ])
    items, warnings = validate_extraction(raw)
    assert items == []
    assert len(warnings) == 3  # 빈 이름, 긴 이름, '상품을 찾지 못함'


def test_too_many_items_are_truncated():
    raw = _extraction([
        RequestedItem(product_term=f"Item {n}", quantity=1, quoted_text="x")
        for n in range(MAX_ITEMS + 10)
    ])
    items, warnings = validate_extraction(raw)
    assert len(items) == MAX_ITEMS
    assert any("잘랐습니다" in w for w in warnings)


def test_empty_result_produces_warning():
    items, warnings = validate_extraction(_extraction([]))
    assert items == []
    assert any("찾지 못했습니다" in w for w in warnings)


def test_schema_has_no_price_field():
    """AI가 가격을 만들어낼 수 없도록 스키마에 가격 필드가 없어야 한다."""
    fields = set(InquiryExtraction.model_fields) | set(RequestedItem.model_fields)
    for forbidden in ("price", "unit_price", "total", "amount", "discount", "tax"):
        assert forbidden not in fields
