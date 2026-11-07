"""데이터 검증 로직 테스트.  실행: pytest -q"""
import pandas as pd
import pytest

from core.config import Config
from core.datasource import (
    DataSourceError,
    _clean_customers,
    _clean_products,
    _to_number,
    load_catalog,
)


def _products(rows):
    cols = ["product_id", "product_name", "category", "unit_price",
            "cost_price", "stock_quantity", "currency", "active"]
    return pd.DataFrame(rows, columns=cols)


def _customers(rows):
    cols = ["customer_id", "company_name", "contact_name",
            "email", "customer_tier", "discount_rate"]
    return pd.DataFrame(rows, columns=cols)


def test_to_number_handles_separators_and_junk():
    assert _to_number("3,200,000") == 3200000.0
    assert _to_number(" 0.08 ") == 0.08
    assert _to_number(5) == 5.0
    assert _to_number("") is None
    assert _to_number("약 20대") is None


def test_bad_price_rows_are_dropped():
    df = _products([
        ["P-1", "Monitor", "Monitor", "3200000", "2400000", "10", "VND", "TRUE"],
        ["P-2", "Keyboard", "Keyboard", "", "100000", "10", "VND", "TRUE"],
        ["P-3", "Mouse", "Mouse", "-50", "40", "10", "VND", "TRUE"],
    ])
    warnings = []
    out = _clean_products(df, warnings)
    assert list(out["product_id"]) == ["P-1"]
    assert any("단가" in w for w in warnings)


def test_blank_name_and_empty_stock():
    df = _products([
        ["P-1", "  ", "Monitor", "100", "80", "5", "VND", "TRUE"],
        ["P-2", "Paper", "Paper", "78000", "59000", "", "VND", "TRUE"],
    ])
    warnings = []
    out = _clean_products(df, warnings)
    assert list(out["product_id"]) == ["P-2"]
    assert out.iloc[0]["stock_quantity"] == 0
    assert any("재고" in w for w in warnings)


def test_duplicate_product_id_keeps_first():
    df = _products([
        ["P-1", "Monitor A", "Monitor", "100", "80", "5", "VND", "TRUE"],
        ["P-1", "Monitor B", "Monitor", "200", "80", "5", "VND", "TRUE"],
    ])
    warnings = []
    out = _clean_products(df, warnings)
    assert len(out) == 1
    assert out.iloc[0]["product_name"] == "Monitor A"
    assert any("중복" in w for w in warnings)


def test_inactive_product_is_flagged_not_dropped():
    df = _products([["P-9", "Old Printer", "Printer", "100", "80", "0", "VND", "FALSE"]])
    out = _clean_products(df, [])
    assert len(out) == 1
    assert out.iloc[0]["active"] is False or out.iloc[0]["active"] == False  # noqa: E712


def test_missing_column_raises_readable_error():
    df = pd.DataFrame([{"product_id": "P-1", "product_name": "Monitor"}])
    with pytest.raises(DataSourceError) as err:
        _clean_products(df, [])
    assert "필수 컬럼" in str(err.value)


def test_out_of_range_discount_becomes_zero():
    df = _customers([
        ["C-1", "Good Co", "A", "a@x.vn", "GOLD", "0.10"],
        ["C-2", "Bad Co", "B", "b@x.vn", "GOLD", "1.5"],
        ["C-3", "Empty Co", "C", "c@x.vn", "BRONZE", ""],
    ])
    warnings = []
    out = _clean_customers(df, warnings)
    assert out.set_index("customer_id").loc["C-1", "discount_rate"] == 0.10
    assert out.set_index("customer_id").loc["C-2", "discount_rate"] == 0.0
    assert out.set_index("customer_id").loc["C-3", "discount_rate"] == 0.0
    assert any("할인율" in w for w in warnings)


def test_real_csv_loads_cleanly():
    """data/ 폴더의 실제 가상 데이터가 경고 없이 읽히는지 확인."""
    cfg = Config(
        data_source="csv", sheets_id="", service_account_file="",
        mock_ai=True, anthropic_api_key="",
    )
    catalog = load_catalog(cfg)
    assert len(catalog.products) == 34
    assert len(catalog.customers) == 8
    assert catalog.tax_rate == 0.1
    assert catalog.valid_days == 14
    assert catalog.warnings == [], catalog.warnings
    # P003 (단종) 1개는 목록에 남아 있지만 active_products 에서는 빠진다
    assert len(catalog.active_products()) == 33
    # 재고 0 상품(P025)도 데이터에는 남아 있어야 한다 (매칭에서 경고로 쓴다)
    assert (catalog.products["stock_quantity"] == 0).sum() == 1


def test_xlsx_file_gets_its_own_explanation():
    """.xlsx 를 가리키면 공유 권한 문제로 오해하지 않게 따로 안내한다."""
    from core.datasource import _sheets_error_message

    msg = _sheets_error_message(
        RuntimeError("APIError: [400]: This operation is not supported for this "
                     "document. The document must not be an Office file.")
    )
    assert "Google Sheets로 저장" in msg
    assert "보기' 권한" not in msg
