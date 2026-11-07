"""환경변수 로딩. 비밀값은 .env 에만 두고 코드에 넣지 않는다.

설정값이 오타여도 조용히 넘어가지 않는다. 예를 들어 MOCK_AI=sheets 처럼
엉뚱한 값이 들어오면 false 로 처리하면서 경고를 남기고, 화면에 표시한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")

TRUE_WORDS = ("1", "true", "yes", "y", "on")
FALSE_WORDS = ("0", "false", "no", "n", "off", "")
VALID_SOURCES = ("csv", "sheets")


@dataclass(frozen=True)
class Config:
    data_source: str          # "csv" | "sheets"
    sheets_id: str
    service_account_file: str
    mock_ai: bool
    anthropic_api_key: str
    claude_model: str = "claude-opus-5-5"
    service_account_json: str = ""   # Streamlit Cloud 용: 파일 대신 JSON 문자열
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_service_account(self) -> bool:
        """키 파일이 있거나, JSON 문자열이 주어졌으면 인증할 수 있다."""
        return bool(self.service_account_json.strip()) or Path(self.service_account_file).exists()

    @property
    def sheets_ready(self) -> bool:
        return bool(self.sheets_id) and self.has_service_account

    @property
    def claude_ready(self) -> bool:
        return self.mock_ai or bool(self.anthropic_api_key)

    def masked_key(self) -> str:
        """로그/화면에 전체 키를 절대 출력하지 않는다."""
        key = self.anthropic_api_key
        if not key:
            return "(없음)"
        return f"{key[:7]}...{key[-4:]}" if len(key) > 12 else "(설정됨)"


def _flag(name: str, default: str, warnings: list[str]) -> bool:
    """true/false 로 해석한다. 해석할 수 없는 값은 경고를 남기고 기본값을 쓴다."""
    raw = os.getenv(name)
    if raw is None:
        raw = default
    text = raw.strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    warnings.append(
        f"{name} 값 '{raw}' 을 알 수 없어 기본값({default})을 사용합니다. "
        f"true 또는 false 로 적어주세요."
    )
    return default.strip().lower() in TRUE_WORDS


def get_config() -> Config:
    warnings: list[str] = []

    raw_source = os.getenv("DATA_SOURCE", "csv").strip().lower()
    if raw_source in VALID_SOURCES:
        source = raw_source
    else:
        warnings.append(
            f"DATA_SOURCE 값 '{raw_source}' 은 올바르지 않아 csv 를 사용합니다. "
            f"{' 또는 '.join(VALID_SOURCES)} 중 하나로 적어주세요."
        )
        source = "csv"

    mock_ai = _flag("MOCK_AI", "true", warnings)
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    sheets_id = os.getenv("GOOGLE_SHEETS_ID", "").strip()
    account_file = os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service_account.json"
    ).strip()
    account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

    if not mock_ai and not api_key:
        warnings.append(
            "MOCK_AI 가 false 인데 ANTHROPIC_API_KEY 가 없습니다. "
            "AI 분석을 누르면 오류가 납니다."
        )
    if api_key and not api_key.startswith("sk-ant-"):
        warnings.append("ANTHROPIC_API_KEY 형식이 평소와 다릅니다 (sk-ant- 로 시작하지 않음).")
    if source == "sheets" and not sheets_id:
        warnings.append("DATA_SOURCE 가 sheets 인데 GOOGLE_SHEETS_ID 가 비어 있습니다.")

    return Config(
        data_source=source,
        sheets_id=sheets_id,
        service_account_file=account_file,
        mock_ai=mock_ai,
        anthropic_api_key=api_key,
        claude_model=os.getenv("CLAUDE_MODEL", "claude-opus-5-5").strip(),
        service_account_json=account_json,
        warnings=tuple(warnings),
    )
