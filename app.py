"""AI Quote Maker - Streamlit 화면.

이 파일은 화면만 담당한다. 계산/조회/AI 로직은 core/ 안에 둔다.
(2단계에서 FastAPI로 옮길 때 core/ 를 그대로 재사용하기 위함)
"""
from __future__ import annotations

import streamlit as st

from core.ai import AIError, parse_inquiry
from core.config import get_config
from core.datasource import DataSourceError, load_catalog

st.set_page_config(page_title="AI Quote Maker", page_icon="📄", layout="wide")

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

# 구현이 끝난 단계 수 (STEPS 기준). 단계를 완성할 때마다 올린다.
STEPS_DONE = 2

SAMPLE_INQUIRY = """안녕하세요. 모니터 20대, 키보드 30개,
무선 마우스 30개가 필요합니다.
다음 주까지 납품 가능한지 확인해 주시고
견적 부탁드립니다."""


def vnd(amount: float) -> str:
    return f"{amount:,.0f} ₫"


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


# ---------------------------------------------------------------- 사이드바
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
        st.info("MOCK 모드입니다. AI 결과는 가짜 데이터입니다.", icon="🧪")

catalog, load_error = get_catalog()

# ---------------------------------------------------------------- 페이지
if page == "Dashboard":
    st.header("Dashboard")

    if load_error:
        st.error(load_error)
        st.stop()

    show_warnings(catalog)

    low_stock = catalog.active_products()
    low_stock = low_stock[low_stock["stock_quantity"] < 10]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("판매 중 상품", len(catalog.active_products()))
    col2.metric("등록 고객", len(catalog.customers))
    col3.metric("재고 10개 미만", len(low_stock))
    col4.metric("세율", f"{catalog.tax_rate * 100:.0f}%")

    st.divider()
    st.subheader("견적 작성 흐름")
    cols = st.columns(len(STEPS))
    for col, (index, label) in zip(cols, enumerate(STEPS, start=1)):
        col.markdown(f"**{index}. {label}**")
        col.caption("✅ 사용 가능" if index <= STEPS_DONE else "🚧 구현 예정")

    if len(low_stock):
        st.divider()
        st.subheader("재고 주의 상품")
        st.dataframe(
            low_stock[["product_id", "product_name", "stock_quantity"]],
            hide_index=True,
            width="stretch",
        )

elif page == "Product Search":
    st.header("Product Search")

    if load_error:
        st.error(load_error)
        st.stop()

    show_warnings(catalog)

    query = st.text_input("상품명 검색", placeholder="예: Monitor, Keyboard, Paper")
    only_active = st.checkbox("판매 중인 상품만", value=True)

    table = catalog.active_products() if only_active else catalog.products
    if query.strip():
        mask = table["product_name"].str.contains(query.strip(), case=False, na=False)
        mask |= table["category"].str.contains(query.strip(), case=False, na=False)
        table = table[mask]

    st.caption(f"{len(table)}개 상품 · 표시 가격은 **세전(VAT 별도)** 입니다.")
    view = table.copy()
    view["unit_price"] = view["unit_price"].map(vnd)
    st.dataframe(
        view[["product_id", "product_name", "category", "unit_price", "stock_quantity", "active"]],
        hide_index=True,
        width="stretch",
    )

elif page == "Settings / Connection":
    st.header("Settings / Connection Status")

    st.subheader("연결 상태")
    rows = [
        ("데이터 소스", cfg.data_source, "OK" if not load_error else "오류"),
        ("Google Sheets ID", "설정됨" if cfg.sheets_id else "미설정",
         "OK" if cfg.data_source == "csv" or cfg.sheets_ready else "확인 필요"),
        ("Claude API 키", cfg.masked_key(), "OK" if cfg.claude_ready else "확인 필요"),
        ("AI 모드", "MOCK" if cfg.mock_ai else "실제 API 호출", "OK"),
    ]
    for name, value, status in rows:
        col1, col2, col3 = st.columns([2, 3, 1])
        col1.write(f"**{name}**")
        col2.write(value)
        col3.write("✅" if status == "OK" else "⚠️")

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
        "값을 바꾸려면 프로젝트 폴더의 `.env` 파일을 수정하고 앱을 다시 시작하세요. "
        "API 키는 화면과 로그에 전체가 출력되지 않습니다."
    )

elif page == "New Quotation":
    st.header("New Quotation")

    cols = st.columns(len(STEPS))
    for col, (index, label) in zip(cols, enumerate(STEPS, start=1)):
        col.markdown(f"**{index}. {label}**" if index <= STEPS_DONE else f"{index}. {label}")
        col.caption("" if index <= STEPS_DONE else "구현 예정")
    st.divider()

    st.subheader("1. 고객 문의 입력")
    if st.button("예시 문의 채우기"):
        st.session_state["inquiry_text"] = SAMPLE_INQUIRY

    inquiry = st.text_area(
        "고객이 보낸 문의 내용",
        key="inquiry_text",
        height=160,
        placeholder="예: 모니터 20대, 키보드 30개가 필요합니다. 다음 주까지 납품 가능한가요?",
    )

    if st.button("AI로 분석하기", type="primary", disabled=not inquiry.strip()):
        try:
            with st.spinner("Claude가 문의를 분석하는 중..."):
                st.session_state["parsed"] = parse_inquiry(inquiry)
        except AIError as exc:
            st.session_state.pop("parsed", None)
            st.error(str(exc))

    parsed = st.session_state.get("parsed")
    if parsed:
        st.divider()
        st.subheader("2. AI 요청 분석 결과")
        if parsed.is_mock:
            st.warning("🧪 **MOCK 결과** — Claude API를 호출하지 않은 고정 예시입니다.", icon="🧪")
        else:
            st.success(f"🤖 **실제 Claude API 결과** · 감지 언어: `{parsed.language}`", icon="🤖")

        if parsed.items:
            st.dataframe(
                [
                    {
                        "상품명 (AI 추출)": item.product_term,
                        "수량": item.quantity,
                        "고객 원문": item.quoted_text,
                    }
                    for item in parsed.items
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("수량이 명시된 상품을 찾지 못했습니다.", icon="ℹ️")

        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown("**요청 납기 (고객 표현)**")
            if parsed.requested_delivery_text:
                st.write(f"> {parsed.requested_delivery_text}")
                st.caption("⚠️ 고객이 쓴 표현을 그대로 옮긴 것입니다. 확정 납기가 아닙니다.")
            else:
                st.caption("납기 언급 없음")
        with col_right:
            st.markdown("**기타 요구사항**")
            if parsed.customer_notes:
                for note in parsed.customer_notes:
                    st.write("•", note)
            else:
                st.caption("없음")

        if parsed.warnings:
            for warning in parsed.warnings:
                st.caption(f"⚠️ {warning}")

        st.divider()
        st.info(
            "다음 단계(상품 자동 매칭)에서 이 결과를 Products 데이터와 연결합니다. "
            "AI는 상품명과 수량만 추출하며, 가격·재고·납기는 만들어내지 않습니다.",
            icon="🚧",
        )

else:
    st.header(page)
    st.info("7단계(견적 검토 화면)에서 구현합니다.", icon="🚧")
    st.caption("지금은 Dashboard, New Quotation, Product Search, Settings 를 사용할 수 있습니다.")
