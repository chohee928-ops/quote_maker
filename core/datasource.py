"""상품/고객/설정 데이터 읽기. CSV와 Google Sheets 둘 다 같은 결과를 돌려준다.

Google Sheets는 읽기 전용으로만 사용한다 (쓰기 함수를 두지 않는다).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import DATA_DIR, Config, get_config

PRODUCT_COLUMNS = [
    "product_id", "product_name", "category", "unit_price",
    "cost_price", "stock_quantity", "currency", "active",
]
CUSTOMER_COLUMNS = [
    "customer_id", "company_name", "contact_name",
    "email", "customer_tier", "discount_rate",
]

BLANKS = ("", "nan", "None")


class DataSourceError(RuntimeError):
    """사용자에게 그대로 보여줄 수 있는 데이터 소스 오류."""


@dataclass
class Catalog:
    products: pd.DataFrame
    customers: pd.DataFrame
    settings: dict[str, str]
    source: str                              # "csv" | "sheets"
    warnings: list[str] = field(default_factory=list)

    @property
    def tax_rate(self) -> float:
        return _to_number(self.settings.get("tax_rate", 0)) or 0.0

    @property
    def valid_days(self) -> int:
        return int(_to_number(self.settings.get("quotation_valid_days", 14)) or 14)

    def active_products(self) -> pd.DataFrame:
        return self.products[self.products["active"]]


def _to_number(value) -> float | None:
    """'3,200,000' / ' 0.08 ' / 3200000 -> float. 변환 불가면 None.

    shortcut: 점(.)은 소수점으로만 해석한다. 베트남식 '3.200.000' 표기는
    지원하지 않는다 - Sheets는 UNFORMATTED_VALUE로 읽어 숫자 그대로 오고,
    CSV는 우리가 만든 파일이라 발생하지 않는다. 사용자가 손으로 점 구분자를
    입력하는 사례가 생기면 로케일 파서로 교체한다.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_bool(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "o")


def _read_csv() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    try:
        products = pd.read_csv(DATA_DIR / "products.csv", dtype=str, keep_default_na=False)
        customers = pd.read_csv(DATA_DIR / "customers.csv", dtype=str, keep_default_na=False)
        raw_settings = pd.read_csv(DATA_DIR / "settings.csv", dtype=str, keep_default_na=False)
    except FileNotFoundError as exc:
        raise DataSourceError(
            "CSV 파일을 찾을 수 없습니다: {}\n"
            "data/ 폴더에 products.csv, customers.csv, settings.csv 가 있어야 합니다.".format(exc.filename)
        ) from exc
    settings = dict(zip(raw_settings.iloc[:, 0], raw_settings.iloc[:, 1]))
    return products, customers, settings


def _read_sheets(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    if not cfg.sheets_id:
        raise DataSourceError("GOOGLE_SHEETS_ID 가 .env 에 설정되지 않았습니다.")
    try:
        import gspread
    except ImportError as exc:
        raise DataSourceError(
            "gspread 가 설치되지 않았습니다: pip install -r requirements.txt"
        ) from exc

    try:
        client = gspread.service_account(filename=cfg.service_account_file)
        book = client.open_by_key(cfg.sheets_id)
    except FileNotFoundError as exc:
        raise DataSourceError(
            "서비스 계정 키 파일이 없습니다: {}\n"
            "README의 Google Sheets 설정 안내를 따라주세요.".format(cfg.service_account_file)
        ) from exc
    except Exception as exc:
        # 인증/권한/네트워크 오류. 원문 메시지에 키나 토큰이 섞여 나올 수 있어
        # 예외 타입만 노출한다.
        raise DataSourceError(
            "Google Sheets 연결 실패: {}. 스프레드시트를 서비스 계정 이메일에 "
            "'보기' 권한으로 공유했는지, 시트 ID가 맞는지 확인하세요.".format(type(exc).__name__)
        ) from exc

    def tab(name: str) -> list[dict]:
        try:
            sheet = book.worksheet(name)
            return sheet.get_all_records(value_render_option="UNFORMATTED_VALUE")
        except Exception as exc:
            raise DataSourceError(
                "'{}' 탭을 읽을 수 없습니다: {}".format(name, type(exc).__name__)
            ) from exc

    products = pd.DataFrame(tab("Products"))
    customers = pd.DataFrame(tab("Customers"))
    settings = {str(r.get("key", "")): str(r.get("value", "")) for r in tab("Settings")}
    return products, customers, settings


def _require_columns(
    df: pd.DataFrame, columns: list[str], tab: str, warnings: list[str]
) -> pd.DataFrame:
    if not list(df.columns):
        raise DataSourceError("'{}' 탭이 비어 있습니다.".format(tab))
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise DataSourceError(
            "'{}' 탭에 필수 컬럼이 없습니다: {}\n"
            "첫 행은 컬럼명이어야 합니다. 기대 컬럼: {}".format(
                tab, ", ".join(missing), ", ".join(columns)
            )
        )
    extra = [c for c in df.columns if c not in columns]
    if extra:
        warnings.append(
            "'{}' 탭의 알 수 없는 컬럼은 무시했습니다: {}".format(tab, ", ".join(extra))
        )
    return df[columns].copy()


def _drop_duplicate_ids(
    df: pd.DataFrame, id_col: str, tab: str, warnings: list[str]
) -> pd.DataFrame:
    dupes = df[df[id_col].duplicated(keep="first")][id_col].unique()
    if len(dupes):
        warnings.append(
            "'{}' 탭의 중복 {}는 첫 행만 사용했습니다: {}".format(
                tab, id_col, ", ".join(map(str, dupes[:5]))
            )
        )
    return df.drop_duplicates(subset=[id_col], keep="first").reset_index(drop=True)


def _clean_products(df: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    df = _require_columns(df, PRODUCT_COLUMNS, "Products", warnings)
    df["product_id"] = df["product_id"].astype(str).str.strip()
    df["product_name"] = df["product_name"].astype(str).str.strip()
    df["unit_price"] = df["unit_price"].map(_to_number)
    df["cost_price"] = df["cost_price"].map(_to_number)
    df["stock_quantity"] = df["stock_quantity"].map(_to_number)
    df["active"] = df["active"].map(_to_bool)

    blank = df["product_name"].isin(BLANKS)
    if blank.any():
        warnings.append("상품명이 빈 행 {}개를 제외했습니다.".format(int(blank.sum())))

    bad_price = df["unit_price"].isna() | (df["unit_price"] < 0)
    if bad_price.any():
        ids = ", ".join(df.loc[bad_price, "product_id"].head(5))
        warnings.append("단가가 없거나 음수인 상품을 제외했습니다: {}".format(ids))

    no_stock = df["stock_quantity"].isna()
    if no_stock.any():
        warnings.append(
            "재고 수량이 비어 있는 상품 {}개를 0으로 처리했습니다.".format(int(no_stock.sum()))
        )
        df.loc[no_stock, "stock_quantity"] = 0

    df = df[~(blank | bad_price)].copy()
    return _drop_duplicate_ids(df, "product_id", "Products", warnings)


def _clean_customers(df: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    df = _require_columns(df, CUSTOMER_COLUMNS, "Customers", warnings)
    df["customer_id"] = df["customer_id"].astype(str).str.strip()
    df["company_name"] = df["company_name"].astype(str).str.strip()
    df["discount_rate"] = df["discount_rate"].map(_to_number)

    bad = df["discount_rate"].isna() | (df["discount_rate"] < 0) | (df["discount_rate"] > 1)
    if bad.any():
        ids = ", ".join(df.loc[bad, "customer_id"].head(5))
        warnings.append(
            "할인율이 0~1 범위를 벗어난 고객의 할인율을 0으로 처리했습니다: {}".format(ids)
        )
        df.loc[bad, "discount_rate"] = 0.0

    blank = df["company_name"].isin(BLANKS)
    if blank.any():
        warnings.append("회사명이 빈 고객 {}개를 제외했습니다.".format(int(blank.sum())))

    df = df[~blank].copy()
    return _drop_duplicate_ids(df, "customer_id", "Customers", warnings)


def load_catalog(cfg: Config | None = None) -> Catalog:
    """상품·고객·설정을 읽고 검증한다. 실패하면 DataSourceError 를 던진다."""
    cfg = cfg or get_config()
    if cfg.data_source == "sheets":
        products, customers, settings = _read_sheets(cfg)
    else:
        products, customers, settings = _read_csv()

    warnings: list[str] = []
    clean_settings = {
        str(k).strip(): str(v).strip() for k, v in settings.items() if str(k).strip()
    }
    for key in ("company_name", "tax_rate", "quotation_valid_days"):
        if not clean_settings.get(key):
            warnings.append("Settings에 '{}' 가 없어 기본값을 사용합니다.".format(key))

    return Catalog(
        products=_clean_products(products, warnings),
        customers=_clean_customers(customers, warnings),
        settings=clean_settings,
        source=cfg.data_source,
        warnings=warnings,
    )
