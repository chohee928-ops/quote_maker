"""견적서와 함께 보낼 비즈니스 이메일 초안을 Claude 로 작성한다.

이 단계에서는 실제로 발송하지 않는다 (초안 텍스트만 돌려준다).

AI 가 금액이나 납기를 새로 만들어내지 못하도록, 확정된 숫자는 프롬프트에
'이미 계산된 사실'로 넣어주고 재계산을 금지한다. 납기는 확정되지 않았다는
사실을 반드시 담도록 지시한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from .ai import AIError
from .config import Config, get_config
from .pdf import QuotationMeta
from .pricing import Quotation, format_money

LANGUAGES = {
    "ko": "한국어",
    "en": "English",
    "vi": "Tiếng Việt",
}

MAX_SUBJECT = 200
MAX_BODY = 4000


class EmailDraftSchema(BaseModel):
    subject: str = Field(description="이메일 제목. 한 줄.")
    body: str = Field(description="이메일 본문. 인사-본문-맺음말. 서명 자리는 [담당자명] 으로.")


@dataclass
class EmailDraft:
    language: str
    subject: str
    body: str
    is_mock: bool


SYSTEM_PROMPT = """\
당신은 베트남 B2B 사무용품 유통사의 영업 담당자다. 고객에게 견적서를 첨부해
보낼 정중한 비즈니스 이메일을 쓴다.

반드시 지킬 것:
- 주어진 숫자(합계, 할인, 세금, 유효기간)를 그대로 쓴다. 다시 계산하지 않는다.
- 주어지지 않은 금액, 할인, 상품, 재고를 만들어내지 않는다.
- 납기를 약속하지 않는다. 재고 확인 후 안내한다는 표현을 쓴다.
- 재고 부족 항목이 있으면 숨기지 않고 정중하게 알린다.
- 과장된 마케팅 문구를 쓰지 않는다. 사실만 간결하게.
- 서명란의 담당자 이름은 [담당자명] 으로 비워 둔다.
- 요청된 언어로만 작성한다.
"""


def _mock_draft(language: str, quote: Quotation, meta: QuotationMeta) -> EmailDraftSchema:
    total = format_money(quote.total, quote.currency)
    templates = {
        "ko": (
            f"[견적서] {meta.quote_number} — {meta.company_name}",
            f"""{meta.customer_company} {meta.customer_contact or ''} 님께,

안녕하세요. {meta.company_name} 입니다.
요청하신 견적서를 첨부하여 보내드립니다.

- 견적번호: {meta.quote_number}
- 견적금액: {total} (부가세 포함)
- 유효기간: {meta.valid_until.isoformat()}

납기는 재고 확인 후 별도로 안내드리겠습니다.
문의사항이 있으시면 언제든 연락 주십시오.

감사합니다.
[담당자명]
{meta.company_name}
{meta.company_email}""",
        ),
        "en": (
            f"[Quotation] {meta.quote_number} — {meta.company_name}",
            f"""Dear {meta.customer_contact or meta.customer_company},

Thank you for your inquiry. Please find our quotation attached.

- Quotation No.: {meta.quote_number}
- Total amount: {total} (VAT included)
- Valid until: {meta.valid_until.isoformat()}

The delivery date will be confirmed after we verify stock availability.
Please let us know if you have any questions.

Best regards,
[담당자명]
{meta.company_name}
{meta.company_email}""",
        ),
        "vi": (
            f"[Báo giá] {meta.quote_number} — {meta.company_name}",
            f"""Kính gửi {meta.customer_contact or meta.customer_company},

Cảm ơn Quý khách đã quan tâm. Chúng tôi xin gửi kèm báo giá.

- Số báo giá: {meta.quote_number}
- Tổng tiền: {total} (đã bao gồm VAT)
- Hiệu lực đến: {meta.valid_until.isoformat()}

Thời gian giao hàng sẽ được xác nhận sau khi kiểm tra tồn kho.
Nếu Quý khách có thắc mắc, xin vui lòng liên hệ với chúng tôi.

Trân trọng,
[담당자명]
{meta.company_name}
{meta.company_email}""",
        ),
    }
    subject, body = templates[language]
    return EmailDraftSchema(subject=subject, body=body.strip())


def _facts(quote: Quotation, meta: QuotationMeta) -> str:
    """AI 에게 넘기는 '이미 확정된 사실'. 여기 없는 숫자는 쓰지 못한다."""
    items = "\n".join(
        f"  - {line.product_name} x {line.quantity:,} = "
        f"{format_money(line.line_total, quote.currency)}"
        for line in quote.lines
    )
    lines = [
        f"회사명: {meta.company_name}",
        f"회사 이메일: {meta.company_email}",
        f"고객사: {meta.customer_company}",
        f"고객 담당자: {meta.customer_contact or '(미기재)'}",
        f"견적번호: {meta.quote_number}",
        f"견적일자: {meta.quote_date.isoformat()}",
        f"유효기간: {meta.valid_until.isoformat()}",
        "품목:",
        items,
        f"공급가액: {format_money(quote.subtotal, quote.currency)}",
        f"할인({quote.discount_rate * 100:g}%): -{format_money(quote.discount_amount, quote.currency)}",
        f"부가세({quote.tax_rate * 100:g}%): {format_money(quote.tax_amount, quote.currency)}",
        f"합계(부가세 포함): {format_money(quote.total, quote.currency)}",
    ]
    if meta.delivery_request:
        lines.append(f"고객이 요청한 납기 표현(확정 아님): {meta.delivery_request}")
    if meta.stock_warnings:
        lines.append("재고 확인이 필요한 항목:")
        lines += [f"  - {w}" for w in meta.stock_warnings]
    else:
        lines.append("재고 부족 항목: 없음")
    return "\n".join(lines)


def write_email_draft(
    quote: Quotation,
    meta: QuotationMeta,
    language: str = "ko",
    cfg: Config | None = None,
) -> EmailDraft:
    """견적서 첨부용 이메일 초안을 만든다. 실제로 발송하지 않는다."""
    cfg = cfg or get_config()
    language = (language or "ko").strip().lower()
    if language not in LANGUAGES:
        raise AIError(f"지원하지 않는 언어입니다: {language}. {', '.join(LANGUAGES)} 중 선택하세요.")
    if not quote.lines:
        raise AIError("견적 품목이 없어 이메일을 쓸 수 없습니다.")

    if cfg.mock_ai:
        raw = _mock_draft(language, quote, meta)
    else:
        raw = _call_claude(language, quote, meta, cfg)

    subject = " ".join(raw.subject.split())[:MAX_SUBJECT].strip()
    body = raw.body.strip()[:MAX_BODY]
    if not subject or not body:
        raise AIError("이메일 초안이 비어 있습니다. 다시 시도해 주세요.")

    return EmailDraft(language=language, subject=subject, body=body, is_mock=cfg.mock_ai)


def _call_claude(
    language: str, quote: Quotation, meta: QuotationMeta, cfg: Config
) -> EmailDraftSchema:
    import anthropic

    if not cfg.anthropic_api_key:
        raise AIError("ANTHROPIC_API_KEY 가 설정되지 않았습니다. .env 를 확인하세요.")

    prompt = (
        f"아래 확정된 견적 정보를 바탕으로 {LANGUAGES[language]}로 이메일을 작성하세요.\n"
        f"숫자는 그대로 인용하고 새로 계산하지 마세요.\n\n"
        f"<견적정보>\n{_facts(quote, meta)}\n</견적정보>"
    )

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    try:
        response = client.messages.parse(
            model=cfg.claude_model,
            max_tokens=4000,
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=EmailDraftSchema,
        )
    except anthropic.AuthenticationError as exc:
        raise AIError("Claude API 인증 실패: API 키가 올바른지 확인하세요.") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("Claude API 호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Claude API 연결 실패: 네트워크를 확인하세요.") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"Claude API 오류 (HTTP {exc.status_code}). 잠시 후 다시 시도하세요.") from exc

    if response.stop_reason == "refusal":
        raise AIError("Claude가 이 요청의 처리를 거부했습니다.")
    if response.parsed_output is None:
        raise AIError("이메일 초안을 구조화하지 못했습니다. 다시 시도해 주세요.")

    return response.parsed_output
