"""AI가 추출한 상품명을 Products 데이터의 실제 상품에 연결하고 재고를 비교한다.

AI는 상품을 '만들어내지' 못한다. 여기서 반환하는 후보는 전부 Products 테이블의
실제 행이며, 가격도 테이블의 unit_price 를 그대로 쓴다.

fuzzy 매칭은 표준 라이브러리 difflib 로 한다 (의존성 추가 없음).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum

import pandas as pd

# 토큰이 전부 일치하면 '확정', 유사도만 높으면 '후보'로 다룬다.
SIMILARITY_FLOOR = 0.45     # 이보다 낮으면 후보로도 보지 않는다
MAX_CANDIDATES = 6

# 재고가 이 수량 미만이면 충분해도 화면에서 주의 표시를 한다.
LOW_STOCK_THRESHOLD = 10


class MatchStatus(str, Enum):
    EXACT = "exact"          # 후보가 1개로 확정됨
    AMBIGUOUS = "ambiguous"  # 후보가 여러 개 — 사용자가 골라야 한다
    NOT_FOUND = "not_found"  # 확인 필요


class StockStatus(str, Enum):
    OK = "ok"                 # 재고 충분
    LOW = "low"               # 충분하지만 여유가 적다
    SHORTAGE = "shortage"     # 재고 부족
    UNKNOWN = "unknown"       # 상품 미확정 — 판단 불가
    INACTIVE = "inactive"     # 단종/판매중지 상품


@dataclass
class Candidate:
    product_id: str
    product_name: str
    category: str
    unit_price: float
    stock_quantity: int
    active: bool
    score: float


@dataclass
class MatchedLine:
    """추출된 요청 1건에 대한 매칭 결과."""
    product_term: str              # AI가 추출한 상품명
    quantity: int
    quoted_text: str
    status: MatchStatus
    candidates: list[Candidate] = field(default_factory=list)
    selected_product_id: str | None = None

    @property
    def selected(self) -> Candidate | None:
        if not self.selected_product_id:
            return None
        return next(
            (c for c in self.candidates if c.product_id == self.selected_product_id), None
        )

    @property
    def needs_user_choice(self) -> bool:
        return self.selected is None

    def stock_status(self) -> StockStatus:
        product = self.selected
        if product is None:
            return StockStatus.UNKNOWN
        if not product.active:
            return StockStatus.INACTIVE
        if product.stock_quantity < self.quantity:
            return StockStatus.SHORTAGE
        if product.stock_quantity - self.quantity < LOW_STOCK_THRESHOLD:
            return StockStatus.LOW
        return StockStatus.OK

    def shortage_quantity(self) -> int:
        """부족 수량. 부족하지 않으면 0."""
        product = self.selected
        if product is None or product.stock_quantity >= self.quantity:
            return 0
        return int(self.quantity - product.stock_quantity)


def _normalize(text: str) -> list[str]:
    """비교용 토큰. 영문 소문자 단어와 숫자만 남긴다."""
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [tok for tok in cleaned.split() if tok]


def _score(term_tokens: list[str], name_tokens: list[str], name: str, term: str) -> float:
    """0~1 유사도. 요청 토큰이 상품명에 모두 들어 있으면 크게 가산한다."""
    if not term_tokens or not name_tokens:
        return 0.0
    name_set = set(name_tokens)
    covered = sum(1 for tok in term_tokens if tok in name_set)
    coverage = covered / len(term_tokens)
    ratio = SequenceMatcher(None, term.lower(), name.lower()).ratio()
    # 토큰 포함 여부를 주로 보고, 문자열 유사도로 순위를 가린다.
    return round(0.75 * coverage + 0.25 * ratio, 4)


def match_product(term: str, products: pd.DataFrame) -> tuple[MatchStatus, list[Candidate]]:
    """상품명 1개 -> (상태, 후보 목록). 후보는 점수 내림차순."""
    term = (term or "").strip()
    if not term or products.empty:
        return MatchStatus.NOT_FOUND, []

    term_tokens = _normalize(term)
    scored: list[Candidate] = []
    for row in products.itertuples(index=False):
        name = str(row.product_name)
        score = _score(term_tokens, _normalize(name), name, term)
        if score < SIMILARITY_FLOOR:
            continue
        scored.append(
            Candidate(
                product_id=str(row.product_id),
                product_name=name,
                category=str(row.category),
                unit_price=float(row.unit_price),
                stock_quantity=int(row.stock_quantity),
                active=bool(row.active),
                score=score,
            )
        )

    if not scored:
        return MatchStatus.NOT_FOUND, []

    # 판매 중인 상품을 먼저, 그 안에서 점수 높은 순.
    scored.sort(key=lambda c: (c.active, c.score), reverse=True)
    scored = scored[:MAX_CANDIDATES]

    sellable = [c for c in scored if c.active]
    # 요청 토큰을 전부 포함하는 판매중 상품이 딱 하나면 확정으로 본다.
    full_cover = [c for c in sellable if _covers_all(term_tokens, c.product_name)]
    if len(full_cover) == 1:
        return MatchStatus.EXACT, scored
    if len(sellable) == 1 and not full_cover:
        return MatchStatus.EXACT, scored
    return MatchStatus.AMBIGUOUS, scored


def _covers_all(term_tokens: list[str], name: str) -> bool:
    name_set = set(_normalize(name))
    return all(tok in name_set for tok in term_tokens)


def match_inquiry(items, products: pd.DataFrame) -> list[MatchedLine]:
    """ParsedInquiry.items -> MatchedLine 목록. 확정된 건만 자동 선택한다."""
    lines: list[MatchedLine] = []
    for item in items:
        status, candidates = match_product(item.product_term, products)
        line = MatchedLine(
            product_term=item.product_term,
            quantity=item.quantity,
            quoted_text=item.quoted_text,
            status=status,
            candidates=candidates,
        )
        if status is MatchStatus.EXACT:
            # 확정이어도 판매중인 후보만 자동 선택한다.
            best = next((c for c in candidates if c.active), None)
            if best is not None:
                line.selected_product_id = best.product_id
        lines.append(line)
    return lines


def stock_summary(lines: list[MatchedLine]) -> dict[str, int]:
    """화면 상단 배지용 집계."""
    counts = {status.value: 0 for status in StockStatus}
    for line in lines:
        counts[line.stock_status().value] += 1
    counts["unresolved"] = sum(1 for line in lines if line.needs_user_choice)
    return counts
