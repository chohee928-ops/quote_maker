"""이메일 초안 테스트. 실제 Claude API 는 호출하지 않는다."""
from datetime import date

import pytest

from core.ai import AIError
from core.config import Config
from core.email_draft import LANGUAGES, _facts, write_email_draft
from core.pdf import QuotationMeta
from core.pricing import LineInput, calculate_quote

MOCK_CFG = Config(data_source="csv", sheets_id="", service_account_file="",
                  mock_ai=True, anthropic_api_key="")


def _quote():
    return calculate_quote(
        [
            LineInput("P001", "Monitor 24 inch FHD IPS", 20, 2_850_000),
            LineInput("P007", "Mouse Wireless", 30, 165_000),
        ],
        discount_rate=0.10,
        tax_rate=0.10,
    )


def _meta(**kw):
    defaults = dict(
        quote_number="QT-20261107-1200-AB12",
        quote_date=date(2026, 11, 7),
        valid_until=date(2026, 11, 21),
        customer_company="Daewoo Vina Co., Ltd.",
        customer_contact="김재훈",
        customer_email="jh.kim@daewoovina.com.vn",
        customer_tier="VIP",
        company_name="ANB Office Solutions Co., Ltd.",
        company_email="sales@anb-office.vn",
        delivery_request="다음 주까지",
    )
    defaults.update(kw)
    return QuotationMeta(**defaults)


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_every_language_produces_a_draft(language):
    draft = write_email_draft(_quote(), _meta(), language=language, cfg=MOCK_CFG)
    assert draft.language == language
    assert draft.is_mock is True
    assert draft.subject.strip()
    assert len(draft.body) > 80
    assert "[담당자명]" in draft.body        # 서명은 사람이 채운다


@pytest.mark.parametrize("language,marker", [
    ("ko", "감사합니다"),
    ("en", "Best regards"),
    ("vi", "Trân trọng"),
])
def test_draft_is_written_in_the_requested_language(language, marker):
    draft = write_email_draft(_quote(), _meta(), language=language, cfg=MOCK_CFG)
    assert marker in draft.body


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_total_matches_the_calculated_quote(language):
    """이메일의 금액은 Python 이 계산한 합계와 같아야 한다."""
    quote = _quote()
    draft = write_email_draft(quote, _meta(), language=language, cfg=MOCK_CFG)
    assert f"{quote.total:,}" in draft.body


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_draft_never_promises_a_delivery_date(language):
    """확정되지 않은 납기를 약속하지 않는다."""
    draft = write_email_draft(_quote(), _meta(), language=language, cfg=MOCK_CFG)
    promises = {
        "ko": "재고 확인 후",
        "en": "after we verify stock",
        "vi": "sau khi kiểm tra tồn kho",
    }
    assert promises[language] in draft.body


def test_unsupported_language_is_rejected():
    with pytest.raises(AIError) as err:
        write_email_draft(_quote(), _meta(), language="ja", cfg=MOCK_CFG)
    assert "지원하지 않는" in str(err.value)


def test_empty_quote_is_rejected():
    class Empty:
        lines = ()
    with pytest.raises(AIError):
        write_email_draft(Empty(), _meta(), language="ko", cfg=MOCK_CFG)


# --- AI 에게 넘기는 '사실' 블록 ------------------------------------------

def test_facts_block_contains_the_exact_numbers():
    quote = _quote()
    facts = _facts(quote, _meta())
    assert f"{quote.subtotal:,}" in facts
    assert f"{quote.discount_amount:,}" in facts
    assert f"{quote.tax_amount:,}" in facts
    assert f"{quote.total:,}" in facts


def test_facts_block_marks_requested_delivery_as_unconfirmed():
    facts = _facts(_quote(), _meta(delivery_request="다음 주까지"))
    assert "확정 아님" in facts


def test_facts_block_surfaces_stock_warnings():
    facts = _facts(_quote(), _meta(stock_warnings=["Mouse Wireless: 12개 부족"]))
    assert "12개 부족" in facts
    assert "재고 확인이 필요한 항목" in facts


def test_facts_block_says_none_when_stock_is_fine():
    assert "재고 부족 항목: 없음" in _facts(_quote(), _meta())
