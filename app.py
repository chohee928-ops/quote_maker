"""AI Quote Maker - Streamlit 화면.

이 파일은 화면만 담당한다. 계산·조회·AI·PDF 로직은 모두 core/ 안에 있다.
(2단계에서 FastAPI 로 UI 를 교체할 때 core/ 를 그대로 재사용하기 위함)
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import streamlit as st

st.set_page_config(page_title="AI Quote Maker", page_icon="📄", layout="wide")


def _load_streamlit_secrets() -> None:
    """Streamlit Cloud 에는 .env 가 없고 st.secrets 를 쓴다.

    core/ 는 streamlit 을 import 하지 않아야 하므로, 화면 쪽에서 secrets 를
    환경변수로 옮겨주고 core/config.py 는 평소처럼 os.getenv 만 쓴다.
    이미 설정된 환경변수는 덮어쓰지 않는다 (로컬 .env 가 우선).
    """
    try:
        secrets = st.secrets
    except Exception:
        return
    for key in ("DATA_SOURCE", "GOOGLE_SHEETS_ID", "GOOGLE_SERVICE_ACCOUNT_FILE",
                "MOCK_AI", "ANTHROPIC_API_KEY", "CLAUDE_MODEL",
                "GOOGLE_SERVICE_ACCOUNT_JSON"):
        try:
            value = secrets[key]
        except Exception:
            continue
        if value and not os.getenv(key):
            os.environ[key] = str(value)


_load_streamlit_secrets()

from core.ai import AIError, parse_inquiry                      # noqa: E402
from core.config import get_config                              # noqa: E402
from core.datasource import DataSourceError, load_catalog        # noqa: E402
from core.email_draft import LANGUAGES, write_email_draft        # noqa: E402
from core.matching import MatchStatus, StockStatus, match_inquiry, stock_summary  # noqa: E402
from core.pdf import PdfError, QuotationMeta, build_pdf, make_quote_number        # noqa: E402
from core.pricing import (                                       # noqa: E402
    LineInput,
    PricingError,
    calculate_quote,
    format_money,
)

PAGES = [
    "Dashboard",
    "New Quotation",
    "Product Search",
    "Quotation Preview",
    "Settings / Connection",
]

STEPS = [
    "고객 문의 입력",
    "AI 요청 분석",
    "상품 자동 매칭",
    "가격·재고 확인",
    "견적 검토",
    "PDF 다운로드",
]

SAMPLE_INQUIRY = """안녕하세요. 모니터 20대, 키보드 30개,
무선 마우스 30개가 필요합니다.
다음 주까지 납품 가능한지 확인해 주시고
견적 부탁드립니다."""

STOCK_BADGE = {
    StockStatus.OK: ("✅", "재고 충분"),
    StockStatus.LOW: ("🟡", "재고 여유 적음"),
    StockStatus.SHORTAGE: ("🔴", "재고 부족"),
    StockStatus.UNKNOWN: ("⚪", "상품 미확정"),
    StockStatus.INACTIVE: ("⛔", "판매 중지 상품"),
}

LOW_STOCK_DASHBOARD = 10


# ----------------------------------------------------------------- 공통
def vnd(amount: float) -> str:
    return format_money(amount)


@st.cache_data(ttl=300, show_spinner="데이터를 불러오는 중...")
def cached_catalog(source: str, sheets_id: str):
    """source/sheets_id 가 바뀌면 자동으로 다시 읽는다."""
    return load_catalog()


def get_catalog():
    cfg = get_config()
    try:
        return cached_catalog(cfg.data_source, cfg.sheets_id), None
    except DataSourceError as exc:
        return None, str(exc)


def show_warnings(catalog) -> None:
    if catalog.warnings:
        with st.expander(f"⚠️ 데이터 경고 {len(catalog.warnings)}건", expanded=False):
            for warning in catalog.warnings:
                st.write("•", warning)


def step_bar(current: int) -> None:
    cols = st.columns(len(STEPS))
    for col, (index, label) in zip(cols, enumerate(STEPS, start=1)):
        if index < current:
            col.markdown(f"✅ **{index}. {label}**")
        elif index == current:
            col.markdown(f"🔵 **{index}. {label}**")
        else:
            col.markdown(f"<span style='color:#9AA5B1'>{index}. {label}</span>",
                         unsafe_allow_html=True)


def reset_from_analysis() -> None:
    """문의를 다시 분석할 때 뒤쪽 단계의 상태를 버린다."""
    for key in ("parsed", "matched", "pdf_bytes", "pdf_name", "email_draft"):
        st.session_state.pop(key, None)
    for key in list(st.session_state):
        if key.startswith(("pick_", "qty_", "price_")):
            st.session_state.pop(key, None)


# ----------------------------------------------------------------- 사이드바
cfg = get_config()

with st.sidebar:
    st.title("📄 AI Quote Maker")
    st.caption("B2B 견적 자동 생성 · 베트남 데모")
    page = st.radio("메뉴", PAGES, label_visibility="collapsed")

    st.divider()
    st.caption("상태")
    st.write("데이터: " + ("📊 Google Sheets" if cfg.data_source == "sheets" else "📁 로컬 CSV"))
    st.write("AI: " + ("🧪 MOCK 모드" if cfg.mock_ai else "🤖 Claude API"))
    if cfg.mock_ai:
        st.info("MOCK 모드입니다. AI 결과는 고정 예시입니다.", icon="🧪")
    else:
        st.caption(f"모델: `{cfg.claude_model}`")

catalog, load_error = get_catalog()


# ----------------------------------------------------------------- Dashboard
if page == "Dashboard":
    st.header("Dashboard")

    if load_error:
        st.error(load_error)
        st.stop()

    show_warnings(catalog)

    active = catalog.active_products()
    low_stock = active[active["stock_quantity"] < LOW_STOCK_DASHBOARD]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("판매 중 상품", len(active))
    col2.metric("등록 고객", len(catalog.customers))
    col3.metric(f"재고 {LOW_STOCK_DASHBOARD}개 미만", len(low_stock))
    col4.metric("세율", f"{catalog.tax_rate * 100:g}%")

    st.divider()
    st.subheader("견적 작성 흐름")
    step_bar(0)
    st.caption("왼쪽 메뉴의 **New Quotation** 에서 1단계부터 시작하세요.")

    if len(low_stock):
        st.divider()
        st.subheader("재고 주의 상품")
        view = low_stock[["product_id", "product_name", "category", "stock_quantity"]].copy()
        st.dataframe(view, hide_index=True, width="stretch")


# ----------------------------------------------------------------- New Quotation
elif page == "New Quotation":
    st.header("New Quotation")

    if load_error:
        st.error(load_error)
        st.stop()

    show_warnings(catalog)

    parsed = st.session_state.get("parsed")
    matched = st.session_state.get("matched")
    step_bar(1 if not parsed else (3 if not matched else 5))
    st.divider()

    # --- 1. 고객 선택 + 문의 입력 ------------------------------------
    st.subheader("1. 고객과 문의 내용")

    customers = catalog.customers
    labels = {
        row.customer_id: f"{row.company_name} · {row.customer_tier} "
                         f"(기본 할인 {float(row.discount_rate) * 100:g}%)"
        for row in customers.itertuples(index=False)
    }
    customer_id = st.selectbox(
        "고객사",
        options=list(labels),
        format_func=lambda cid: labels[cid],
        key="customer_id",
    )
    customer = customers.set_index("customer_id").loc[customer_id]

    if st.button("예시 문의 채우기"):
        st.session_state["inquiry_text"] = SAMPLE_INQUIRY
        reset_from_analysis()
        st.rerun()

    inquiry = st.text_area(
        "고객이 보낸 문의 내용",
        key="inquiry_text",
        height=150,
        placeholder="예: 모니터 20대, 키보드 30개가 필요합니다. 다음 주까지 납품 가능한가요?",
    )

    if st.button("AI로 분석하기", type="primary", disabled=not inquiry.strip()):
        reset_from_analysis()
        try:
            with st.spinner("Claude가 문의를 분석하는 중..."):
                st.session_state["parsed"] = parse_inquiry(inquiry)
        except AIError as exc:
            st.error(str(exc))
        st.rerun()

    parsed = st.session_state.get("parsed")
    if not parsed:
        st.info("문의 내용을 입력하고 **AI로 분석하기** 를 누르세요.", icon="⬆️")
        st.stop()

    # --- 2. AI 분석 결과 --------------------------------------------
    st.divider()
    st.subheader("2. AI 요청 분석 결과")
    if parsed.is_mock:
        st.warning("🧪 **MOCK 결과** — Claude API를 호출하지 않은 고정 예시입니다.", icon="🧪")
    else:
        st.success(f"🤖 **실제 Claude API 결과** · 감지 언어 `{parsed.language}`", icon="🤖")

    col_left, col_right = st.columns([3, 2])
    with col_left:
        if parsed.items:
            st.dataframe(
                [
                    {"AI 추출 상품명": item.product_term, "수량": item.quantity,
                     "고객 원문": item.quoted_text}
                    for item in parsed.items
                ],
                hide_index=True, width="stretch",
            )
        else:
            st.info("수량이 명시된 상품을 찾지 못했습니다.", icon="ℹ️")
    with col_right:
        st.markdown("**요청 납기 (고객 표현)**")
        if parsed.requested_delivery_text:
            st.write(f"> {parsed.requested_delivery_text}")
            st.caption("⚠️ 고객 표현을 그대로 옮긴 것입니다. 확정 납기가 아닙니다.")
        else:
            st.caption("납기 언급 없음")
        if parsed.customer_notes:
            st.markdown("**기타 요구사항**")
            for note in parsed.customer_notes:
                st.write("•", note)

    for warning in parsed.warnings:
        st.caption(f"⚠️ {warning}")

    if not parsed.items:
        st.stop()

    # --- 3. 상품 매칭 ------------------------------------------------
    st.divider()
    st.subheader("3. 상품 자동 매칭")
    st.caption("가격과 재고는 Products 데이터에서만 가져옵니다. AI가 만들어낸 값이 아닙니다.")

    if "matched" not in st.session_state:
        st.session_state["matched"] = match_inquiry(parsed.items, catalog.products)
    matched = st.session_state["matched"]

    for index, line in enumerate(matched):
        with st.container(border=True):
            head = f"**{line.product_term}** × {line.quantity:,}"
            st.markdown(f"{head} &nbsp;&nbsp;<span style='color:#6B7280'>"
                        f"고객 원문: {line.quoted_text}</span>", unsafe_allow_html=True)

            if line.status is MatchStatus.NOT_FOUND:
                st.error("❓ 일치하는 상품이 없습니다 — **확인 필요**. "
                         "Product Search 에서 상품명을 확인하거나 이 항목을 제외하세요.")
                continue

            options = [None] + [c.product_id for c in line.candidates]

            def _fmt(pid, _line=line):
                if pid is None:
                    return "— 선택하지 않음 (견적에서 제외) —"
                cand = next(c for c in _line.candidates if c.product_id == pid)
                mark = "" if cand.active else "  ⛔판매중지"
                return (f"{cand.product_name} · {vnd(cand.unit_price)} · "
                        f"재고 {cand.stock_quantity:,}{mark}")

            key = f"pick_{index}"
            if key not in st.session_state:
                st.session_state[key] = line.selected_product_id
            picked = st.selectbox(
                "상품 선택" if line.status is MatchStatus.AMBIGUOUS else "매칭된 상품",
                options=options, format_func=_fmt, key=key,
                help="후보가 여러 개면 직접 골라야 합니다." if line.status is MatchStatus.AMBIGUOUS else None,
            )
            line.selected_product_id = picked

            if line.status is MatchStatus.AMBIGUOUS and picked is None:
                st.warning(f"유사 상품이 {len(line.candidates)}개 있습니다. 하나를 선택하세요.", icon="🔎")

            icon, text = STOCK_BADGE[line.stock_status()]
            product = line.selected
            if product is None:
                st.caption(f"{icon} {text}")
            elif line.stock_status() is StockStatus.SHORTAGE:
                st.error(f"{icon} {text} — 주문 {line.quantity:,}개 / 재고 "
                         f"{product.stock_quantity:,}개 · **{line.shortage_quantity():,}개 부족**")
            elif line.stock_status() is StockStatus.INACTIVE:
                st.error(f"{icon} {text} — 판매가 중지된 상품입니다. 다른 상품을 선택하세요.")
            elif line.stock_status() is StockStatus.LOW:
                st.warning(f"{icon} {text} — 재고 {product.stock_quantity:,}개 중 "
                           f"{line.quantity:,}개 주문")
            else:
                st.success(f"{icon} {text} — 재고 {product.stock_quantity:,}개")

    # --- 4. 가격·재고 요약 -------------------------------------------
    summary = stock_summary(matched)
    st.divider()
    st.subheader("4. 가격·재고 확인")
    cols = st.columns(5)
    cols[0].metric("확정 품목", len(matched) - summary["unresolved"])
    cols[1].metric("미확정", summary["unresolved"])
    cols[2].metric("재고 부족", summary[StockStatus.SHORTAGE.value])
    cols[3].metric("재고 여유 적음", summary[StockStatus.LOW.value])
    cols[4].metric("판매 중지", summary[StockStatus.INACTIVE.value])

    usable = [line for line in matched
              if line.selected is not None and line.selected.active]
    if not usable:
        st.warning("견적에 넣을 수 있는 상품이 없습니다. 위에서 상품을 선택하세요.", icon="⚠️")
        st.stop()

    # --- 5. 견적 검토 (수정 가능) -------------------------------------
    st.divider()
    st.subheader("5. 견적 검토")
    st.caption("수량·단가를 바꾸면 아래 금액이 즉시 다시 계산됩니다. 표시 가격은 **세전**입니다.")

    edited: list[LineInput] = []
    for index, line in enumerate(matched):
        product = line.selected
        if product is None or not product.active:
            continue
        col_name, col_qty, col_price, col_total = st.columns([4, 1.4, 2, 2])
        col_name.markdown(f"**{product.product_name}**  \n"
                          f"<span style='color:#6B7280'>{product.product_id} · "
                          f"재고 {product.stock_quantity:,}</span>", unsafe_allow_html=True)
        quantity = col_qty.number_input(
            "수량", min_value=1, max_value=1_000_000, step=1,
            value=int(st.session_state.get(f"qty_{index}", line.quantity)),
            key=f"qty_{index}", label_visibility="visible" if index == 0 else "collapsed",
        )
        unit_price = col_price.number_input(
            f"단가 ({catalog.settings.get('default_currency', 'VND')})",
            min_value=0, max_value=10_000_000_000, step=1000,
            value=int(st.session_state.get(f"price_{index}", int(product.unit_price))),
            key=f"price_{index}", label_visibility="visible" if index == 0 else "collapsed",
        )
        col_total.markdown(f"**{vnd(quantity * unit_price)}**"
                           if index else f"금액  \n**{vnd(quantity * unit_price)}**")
        if quantity > product.stock_quantity:
            col_total.caption(f"🔴 {quantity - product.stock_quantity:,}개 부족")
        edited.append(LineInput(product.product_id, product.product_name, quantity, unit_price))

    st.markdown("")
    col_a, col_b, col_c = st.columns(3)
    default_discount = float(customer.discount_rate) * 100

    # 고객이 바뀌면 할인율을 새 고객의 등급 기본값으로 되돌린다.
    # (이전 고객의 할인율이 남아 잘못된 금액이 계산되는 것을 막는다)
    if st.session_state.get("_discount_customer") != customer_id:
        st.session_state["discount_pct"] = default_discount
        st.session_state["_discount_customer"] = customer_id

    discount_pct = col_a.number_input(
        "할인율 (%)", min_value=0.0, max_value=100.0, step=0.5, key="discount_pct",
        help=f"{customer.customer_tier} 등급 기본값 {default_discount:g}%. 직접 수정할 수 있습니다.",
    )
    valid_days = col_b.number_input(
        "견적 유효기간 (일)", min_value=1, max_value=365, step=1,
        value=int(st.session_state.get("valid_days", catalog.valid_days)), key="valid_days",
    )
    col_c.metric("세율 (Settings)", f"{catalog.tax_rate * 100:g}%",
                 help="세율은 코드에 고정하지 않고 Settings 탭의 tax_rate 를 사용합니다.")

    notes = st.text_area(
        "특이사항 / 비고 (견적서에 인쇄됩니다)",
        key="notes", height=80,
        placeholder="예: 첫 거래 감사합니다. 분할 납품 가능합니다.",
    )

    try:
        quote = calculate_quote(
            edited,
            discount_rate=discount_pct / 100,
            tax_rate=catalog.tax_rate,
            currency=catalog.settings.get("default_currency", "VND"),
        )
    except PricingError as exc:
        st.error(f"계산을 중단했습니다: {exc}")
        st.stop()

    st.markdown("")
    money_left, money_right = st.columns([3, 2])
    with money_right:
        rows = [
            ("공급가액 (세전)", vnd(quote.subtotal)),
            (f"할인 ({quote.discount_rate * 100:g}%)", "- " + vnd(quote.discount_amount)),
            ("과세표준", vnd(quote.taxable_base)),
            (f"부가세 ({quote.tax_rate * 100:g}%)", vnd(quote.tax_amount)),
        ]
        for label, value in rows:
            left, right = st.columns([2, 2])
            left.write(label)
            right.markdown(f"<div style='text-align:right'>{value}</div>",
                           unsafe_allow_html=True)
        st.divider()
        left, right = st.columns([2, 2])
        left.markdown("**합계**")
        right.markdown(f"<div style='text-align:right;font-size:1.3rem;color:#1D4ED8'>"
                       f"<b>{vnd(quote.total)}</b></div>", unsafe_allow_html=True)
    with money_left:
        st.caption("적용 순서: 품목합계 → 소계 → **할인** → 과세표준 → **세금** → 합계")
        st.caption(f"총 {quote.quantity_total:,}개 · {len(quote.lines)}품목")

    # 견적서에 들어갈 경고 모으기 (숨기지 않는다)
    stock_warnings: list[str] = []
    for line in matched:
        if line.selected is None:
            stock_warnings.append(
                f"{line.product_term}: 상품이 확정되지 않아 견적에서 제외됨 — 확인 필요")
        elif not line.selected.active:
            stock_warnings.append(
                f"{line.selected.product_name}: 판매 중지 상품으로 견적에서 제외됨")
    for index, line in enumerate(matched):
        product = line.selected
        if product is None or not product.active:
            continue
        quantity = int(st.session_state.get(f"qty_{index}", line.quantity))
        if quantity > product.stock_quantity:
            stock_warnings.append(
                f"{product.product_name}: 주문 {quantity:,}개 / 재고 "
                f"{product.stock_quantity:,}개 — {quantity - product.stock_quantity:,}개 부족")

    if stock_warnings:
        st.warning("아래 내용은 **견적서에도 함께 인쇄됩니다** (숨기지 않습니다).", icon="⚠️")
        for warning in stock_warnings:
            st.write("•", warning)

    # --- 6. PDF + 이메일 --------------------------------------------
    st.divider()
    st.subheader("6. PDF 견적서와 이메일 초안")

    today = date.today()
    meta = QuotationMeta(
        quote_number=st.session_state.setdefault("quote_number", make_quote_number()),
        quote_date=today,
        valid_until=today + timedelta(days=int(valid_days)),
        customer_company=str(customer.company_name),
        customer_contact=str(customer.contact_name),
        customer_email=str(customer.email),
        customer_tier=str(customer.customer_tier),
        company_name=catalog.settings.get("company_name", ""),
        company_address=catalog.settings.get("company_address", ""),
        company_email=catalog.settings.get("company_email", ""),
        company_phone=catalog.settings.get("company_phone", ""),
        delivery_request=parsed.requested_delivery_text or "",
        notes=notes,
        stock_warnings=stock_warnings,
        is_mock_ai=parsed.is_mock,
    )

    pdf_col, email_col = st.columns(2)

    with pdf_col:
        st.markdown(f"견적번호 `{meta.quote_number}` · 유효 {meta.valid_until.isoformat()}")
        if st.button("PDF 견적서 만들기", type="primary"):
            try:
                st.session_state["pdf_bytes"] = build_pdf(quote, meta)
                st.session_state["pdf_name"] = f"{meta.quote_number}.pdf"
            except PdfError as exc:
                st.session_state.pop("pdf_bytes", None)
                st.error(str(exc))
        if st.session_state.get("pdf_bytes"):
            st.success("PDF가 준비되었습니다.")
            st.download_button(
                "⬇️ PDF 다운로드",
                data=st.session_state["pdf_bytes"],
                file_name=st.session_state["pdf_name"],
                mime="application/pdf",
            )
            st.caption("새 번호로 다시 만들려면 아래 버튼을 누르세요.")
            if st.button("견적번호 새로 발급"):
                st.session_state["quote_number"] = make_quote_number()
                st.session_state.pop("pdf_bytes", None)
                st.rerun()

    with email_col:
        language = st.selectbox(
            "이메일 언어", options=list(LANGUAGES),
            format_func=lambda code: LANGUAGES[code], key="email_language",
        )
        if st.button("이메일 초안 작성"):
            try:
                with st.spinner("이메일 초안을 작성하는 중..."):
                    st.session_state["email_draft"] = write_email_draft(
                        quote, meta, language=language)
            except AIError as exc:
                st.session_state.pop("email_draft", None)
                st.error(str(exc))
        draft = st.session_state.get("email_draft")
        if draft:
            if draft.is_mock:
                st.warning("🧪 MOCK 초안입니다 (Claude API 미호출).", icon="🧪")
            else:
                st.success("🤖 Claude API로 작성된 초안입니다.", icon="🤖")
            st.text_input("제목", value=draft.subject, key="email_subject_view")
            st.text_area("본문", value=draft.body, height=320, key="email_body_view")
            st.caption("이 단계에서는 실제로 발송하지 않습니다. 복사해서 사용하세요.")

    st.session_state["last_quote"] = (quote, meta)


# ----------------------------------------------------------------- Product Search
elif page == "Product Search":
    st.header("Product Search")

    if load_error:
        st.error(load_error)
        st.stop()

    show_warnings(catalog)

    query = st.text_input("상품명 검색", placeholder="예: Monitor, Keyboard, Paper")
    col_a, col_b = st.columns([1, 3])
    only_active = col_a.checkbox("판매 중인 상품만", value=True)
    category = col_b.selectbox(
        "카테고리", options=["전체"] + sorted(catalog.products["category"].unique()))

    table = catalog.active_products() if only_active else catalog.products
    if category != "전체":
        table = table[table["category"] == category]
    if query.strip():
        needle = query.strip()
        mask = table["product_name"].str.contains(needle, case=False, na=False)
        mask |= table["category"].str.contains(needle, case=False, na=False)
        mask |= table["product_id"].str.contains(needle, case=False, na=False)
        table = table[mask]

    st.caption(f"{len(table)}개 상품 · 표시 가격은 **세전(VAT 별도)** 입니다.")
    view = table.copy()
    view["unit_price"] = view["unit_price"].map(vnd)
    st.dataframe(
        view[["product_id", "product_name", "category", "unit_price",
              "stock_quantity", "active"]],
        hide_index=True, width="stretch",
    )


# ----------------------------------------------------------------- Quotation Preview
elif page == "Quotation Preview":
    st.header("Quotation Preview")

    last = st.session_state.get("last_quote")
    if not last:
        st.info("아직 작성한 견적이 없습니다. **New Quotation** 에서 먼저 만들어 주세요.", icon="ℹ️")
        st.stop()

    quote, meta = last
    st.caption(f"견적번호 `{meta.quote_number}` · {meta.quote_date.isoformat()} · "
               f"{meta.customer_company}")

    st.dataframe(
        [
            {"상품": line.product_name, "수량": f"{line.quantity:,}",
             "단가": vnd(line.unit_price), "금액": vnd(line.line_total)}
            for line in quote.lines
        ],
        hide_index=True, width="stretch",
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("공급가액", vnd(quote.subtotal))
    col2.metric(f"할인 {quote.discount_rate * 100:g}%", "-" + vnd(quote.discount_amount))
    col3.metric(f"부가세 {quote.tax_rate * 100:g}%", vnd(quote.tax_amount))
    col4.metric("합계", vnd(quote.total))

    if meta.stock_warnings:
        st.warning("재고 확인이 필요한 항목", icon="⚠️")
        for warning in meta.stock_warnings:
            st.write("•", warning)

    if st.session_state.get("pdf_bytes"):
        st.download_button(
            "⬇️ PDF 다시 다운로드",
            data=st.session_state["pdf_bytes"],
            file_name=st.session_state.get("pdf_name", "quotation.pdf"),
            mime="application/pdf",
        )


# ----------------------------------------------------------------- Settings
else:
    st.header("Settings / Connection Status")

    st.subheader("연결 상태")
    rows = [
        ("데이터 소스", cfg.data_source, not load_error),
        ("Google Sheets ID", "설정됨" if cfg.sheets_id else "미설정",
         cfg.data_source == "csv" or cfg.sheets_ready),
        ("Claude API 키", cfg.masked_key(), cfg.claude_ready),
        ("AI 모드", "MOCK (고정 예시)" if cfg.mock_ai else f"실제 호출 · {cfg.claude_model}", True),
    ]
    for name, value, ok in rows:
        col1, col2, col3 = st.columns([2, 3, 1])
        col1.write(f"**{name}**")
        col2.write(value)
        col3.write("✅" if ok else "⚠️")

    if load_error:
        st.error(load_error)
    elif catalog:
        st.success(
            f"상품 {len(catalog.products)}건, 고객 {len(catalog.customers)}건, "
            f"설정 {len(catalog.settings)}건을 읽었습니다."
        )
        show_warnings(catalog)
        st.subheader("회사 정보 (Settings 탭)")
        st.table({"항목": list(catalog.settings), "값": list(catalog.settings.values())})

    if st.button("데이터 다시 읽기"):
        cached_catalog.clear()
        st.rerun()

    st.divider()
    st.caption(
        "값을 바꾸려면 `.env` 를 수정하고 앱을 다시 시작하세요. Streamlit Cloud 에서는 "
        "App settings → Secrets 에 같은 이름으로 넣습니다. "
        "API 키는 화면과 로그에 전체가 출력되지 않습니다."
    )
