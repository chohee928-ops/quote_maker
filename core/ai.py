"""Claude API로 고객 문의를 구조화한다.

중요한 원칙 2개:
1. 금액 계산은 절대 AI에게 맡기지 않는다. 이 스키마에는 가격 필드가 없다.
2. AI 결과를 그대로 믿지 않는다. validate_extraction() 을 반드시 통과시킨다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from .config import Config, get_config

MAX_INQUIRY_CHARS = 4000
MAX_QUANTITY = 1_000_000
MAX_ITEMS = 50


class AIError(RuntimeError):
    """사용자에게 그대로 보여줄 수 있는 AI 호출 오류."""


# --- Claude 가 채우는 스키마 (가격 필드가 없는 것이 의도적이다) ---------------

class RequestedItem(BaseModel):
    product_term: str = Field(description="영어 일반 상품명. 예: Monitor, Wireless Mouse, A4 Copy Paper")
    quantity: int = Field(description="고객이 명시한 수량. 명시되지 않으면 이 상품을 넣지 말 것")
    quoted_text: str = Field(description="이 상품이 언급된 고객 원문 표현")


class InquiryExtraction(BaseModel):
    items: list[RequestedItem]
    requested_delivery_text: str | None = Field(
        default=None,
        description="고객이 쓴 납기 표현을 그대로. 날짜로 변환하지 말 것. 없으면 null",
    )
    customer_notes: list[str] = Field(
        default_factory=list, description="수량/상품 외의 요구사항이나 질문"
    )
    language: str = Field(description="문의 언어: ko, en, vi 중 하나")


# --- 검증 후 앱이 쓰는 결과 -------------------------------------------------

@dataclass
class ParsedInquiry:
    items: list[RequestedItem]
    requested_delivery_text: str | None
    customer_notes: list[str]
    language: str
    is_mock: bool
    warnings: list[str] = field(default_factory=list)


SYSTEM_PROMPT = """\
당신은 베트남 B2B 사무용품 유통사의 견적 담당자를 돕는 추출 도구다.
고객 문의에서 '명시적으로 적힌 것만' 뽑아낸다.

규칙:
- product_term 은 영어 일반 상품명으로 정규화한다 (한국어/베트남어 문의도 영어로).
  예: "모니터" -> "Monitor", "무선 마우스" -> "Wireless Mouse", "A4 용지" -> "A4 Copy Paper"
- 특정 브랜드나 모델명을 만들어내지 않는다. 고객이 쓴 수준의 일반명으로만.
- 수량이 명시되지 않은 상품은 items 에 넣지 않고 customer_notes 에 적는다.
- 납기는 고객이 쓴 표현을 그대로 옮긴다. 실제 날짜로 계산하거나 추측하지 않는다.
- 가격, 재고, 할인은 절대 추측하지 않는다. 그 정보는 이 작업의 범위가 아니다.
- 문의에 없는 상품을 추가하지 않는다.
"""

MOCK_NOTICE = "MOCK 모드입니다. 아래 결과는 Claude API 호출 없이 만들어진 고정 예시입니다."


def _mock_extraction() -> InquiryExtraction:
    return InquiryExtraction(
        items=[
            RequestedItem(product_term="Monitor", quantity=20, quoted_text="모니터 20대"),
            RequestedItem(product_term="Keyboard", quantity=30, quoted_text="키보드 30개"),
            RequestedItem(product_term="Wireless Mouse", quantity=30, quoted_text="무선 마우스 30개"),
        ],
        requested_delivery_text="다음 주까지",
        customer_notes=["다음 주까지 납품 가능한지 확인 요청"],
        language="ko",
    )


def validate_extraction(raw: InquiryExtraction) -> tuple[list[RequestedItem], list[str]]:
    """AI 결과를 신뢰하지 않고 걸러낸다. (유효한 항목, 경고) 를 돌려준다."""
    warnings: list[str] = []
    items: list[RequestedItem] = []

    for item in raw.items[:MAX_ITEMS]:
        term = item.product_term.strip()
        if not term:
            warnings.append("상품명이 빈 추출 결과를 버렸습니다.")
            continue
        if len(term) > 100:
            warnings.append(f"상품명이 비정상적으로 긴 결과를 버렸습니다: {term[:30]}...")
            continue
        if item.quantity < 1:
            warnings.append(f"'{term}' 의 수량({item.quantity})이 1 미만이라 버렸습니다.")
            continue
        if item.quantity > MAX_QUANTITY:
            warnings.append(f"'{term}' 의 수량({item.quantity:,})이 비정상적으로 큽니다. 확인이 필요합니다.")
            continue
        items.append(RequestedItem(product_term=term, quantity=item.quantity,
                                   quoted_text=item.quoted_text.strip()))

    if len(raw.items) > MAX_ITEMS:
        warnings.append(f"추출 항목이 {MAX_ITEMS}개를 넘어 뒷부분을 잘랐습니다.")
    if not items:
        warnings.append("수량이 명시된 상품을 찾지 못했습니다. 문의 내용을 확인해 주세요.")

    return items, warnings


def parse_inquiry(text: str, cfg: Config | None = None) -> ParsedInquiry:
    """고객 문의 자연어 -> 구조화된 ParsedInquiry. 실패하면 AIError."""
    cfg = cfg or get_config()

    # 외부 서비스를 호출하기 전에 입력값을 먼저 검증한다.
    text = (text or "").strip()
    if not text:
        raise AIError("문의 내용이 비어 있습니다.")
    if len(text) > MAX_INQUIRY_CHARS:
        raise AIError(
            f"문의가 너무 깁니다 ({len(text):,}자). {MAX_INQUIRY_CHARS:,}자 이하로 줄여주세요."
        )

    if cfg.mock_ai:
        raw = _mock_extraction()
    else:
        raw = _call_claude(text, cfg)

    items, warnings = validate_extraction(raw)
    if cfg.mock_ai:
        warnings.insert(0, MOCK_NOTICE)

    return ParsedInquiry(
        items=items,
        requested_delivery_text=(raw.requested_delivery_text or "").strip() or None,
        customer_notes=[n.strip() for n in raw.customer_notes if n.strip()],
        language=raw.language.strip().lower()[:5] or "ko",
        is_mock=cfg.mock_ai,
        warnings=warnings,
    )


def _call_claude(text: str, cfg: Config) -> InquiryExtraction:
    import anthropic

    if not cfg.anthropic_api_key:
        raise AIError("ANTHROPIC_API_KEY 가 설정되지 않았습니다. .env 를 확인하세요.")

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    try:
        response = client.messages.parse(
            model=cfg.claude_model,
            max_tokens=4000,
            output_config={"effort": "low"},   # 단순 추출 작업이므로 낮은 effort로 충분
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"<고객문의>\n{text}\n</고객문의>"}],
            output_format=InquiryExtraction,
        )
    except anthropic.AuthenticationError as exc:
        raise AIError("Claude API 인증 실패: API 키가 올바른지 확인하세요.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIError("Claude API 권한 오류: 이 키로는 해당 모델을 쓸 수 없습니다.") from exc
    except anthropic.NotFoundError as exc:
        raise AIError(f"모델을 찾을 수 없습니다: {cfg.claude_model}") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("Claude API 호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Claude API 연결 실패: 네트워크를 확인하세요.") from exc
    except anthropic.APIStatusError as exc:
        # 원문 메시지에 키가 섞여 나오지 않도록 상태코드만 노출한다.
        raise AIError(f"Claude API 오류 (HTTP {exc.status_code}). 잠시 후 다시 시도하세요.") from exc

    if response.stop_reason == "refusal":
        raise AIError("Claude가 이 요청의 처리를 거부했습니다. 문의 내용을 확인해 주세요.")
    if response.parsed_output is None:
        raise AIError("Claude 응답을 구조화하지 못했습니다. 다시 시도해 주세요.")

    return response.parsed_output
