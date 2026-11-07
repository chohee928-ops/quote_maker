"""환경변수 로딩. 비밀값은 .env 에만 두고 코드에 넣지 않는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y")


@dataclass(frozen=True)
class Config:
    data_source: str          # "csv" | "sheets"
    sheets_id: str
    service_account_file: str
    mock_ai: bool
    anthropic_api_key: str
    claude_model: str = "claude-opus-5-5"
    service_account_json: str = ""   # Streamlit Cloud 용: 파일 대신 JSON 문자열

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
        return f"{key[:7]}...{key[-4:]}" if len(key) > 12 else ("(없음)" if not key else "(설정됨)")


def get_config() -> Config:
    source = os.getenv("DATA_SOURCE", "csv").strip().lower()
    if source not in ("csv", "sheets"):
        source = "csv"
    return Config(
        data_source=source,
        sheets_id=os.getenv("GOOGLE_SHEETS_ID", "").strip(),
        service_account_file=os.getenv(
            "GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service_account.json"
        ).strip(),
        mock_ai=_flag("MOCK_AI", "true"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-opus-5-5").strip(),
        service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
    )
