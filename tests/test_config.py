"""설정값 검증 테스트.

오타가 조용히 넘어가면 금액이나 동작이 틀어지는데도 아무도 모른다.
실제로 .env 에 MOCK_AI=sheets 오타가 들어간 적이 있어서 테스트로 고정한다.
"""
import pytest

from core.config import get_config


@pytest.fixture
def env(monkeypatch):
    """모든 관련 환경변수를 지운 깨끗한 상태에서 시작한다."""
    for key in ("DATA_SOURCE", "MOCK_AI", "ANTHROPIC_API_KEY", "GOOGLE_SHEETS_ID",
                "GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_SERVICE_ACCOUNT_JSON",
                "CLAUDE_MODEL"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_defaults_are_safe(env):
    """아무 설정이 없으면 CSV + MOCK 으로 안전하게 동작한다."""
    cfg = get_config()
    assert cfg.data_source == "csv"
    assert cfg.mock_ai is True
    assert cfg.claude_ready is True       # MOCK 이므로 키가 없어도 된다
    assert cfg.warnings == ()


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "y", "on"])
def test_truthy_values(env, value):
    env.setenv("MOCK_AI", value)
    cfg = get_config()
    assert cfg.mock_ai is True
    assert cfg.warnings == ()


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "n", "off"])
def test_falsy_values(env, value):
    env.setenv("MOCK_AI", value)
    env.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-1234567890")
    cfg = get_config()
    assert cfg.mock_ai is False
    assert cfg.warnings == ()


def test_the_real_typo_is_caught(env):
    """실제로 있었던 오타: DATA_SOURCE 대신 MOCK_AI 줄에 sheets 를 적었다."""
    env.setenv("MOCK_AI", "sheets")
    cfg = get_config()
    assert cfg.mock_ai is True                     # 기본값(true)으로 안전하게 처리
    assert any("MOCK_AI" in w for w in cfg.warnings)
    assert any("sheets" in w for w in cfg.warnings)


def test_invalid_data_source_falls_back_to_csv(env):
    env.setenv("DATA_SOURCE", "excel")
    cfg = get_config()
    assert cfg.data_source == "csv"
    assert any("DATA_SOURCE" in w for w in cfg.warnings)


def test_real_mode_without_key_is_warned(env):
    env.setenv("MOCK_AI", "false")
    cfg = get_config()
    assert cfg.mock_ai is False
    assert cfg.claude_ready is False
    assert any("ANTHROPIC_API_KEY 가 없습니다" in w for w in cfg.warnings)


def test_odd_looking_key_is_warned(env):
    env.setenv("ANTHROPIC_API_KEY", "my-secret-key")
    assert any("sk-ant-" in w for w in get_config().warnings)


def test_sheets_without_id_is_warned(env):
    env.setenv("DATA_SOURCE", "sheets")
    cfg = get_config()
    assert cfg.sheets_ready is False
    assert any("GOOGLE_SHEETS_ID" in w for w in cfg.warnings)


def test_api_key_is_masked(env):
    env.setenv("ANTHROPIC_API_KEY", "sk-ant-usr-0123456789abcdefghij")
    cfg = get_config()
    masked = cfg.masked_key()
    assert cfg.anthropic_api_key not in masked     # 전체 키가 노출되지 않는다
    assert masked.startswith("sk-ant-")
    assert masked.endswith("ghij")


def test_missing_key_is_not_masked_as_empty(env):
    assert get_config().masked_key() == "(없음)"


def test_service_account_json_counts_as_credentials(env):
    """Streamlit Cloud 는 키 파일을 올릴 수 없어 JSON 문자열로 받는다."""
    env.setenv("DATA_SOURCE", "sheets")
    env.setenv("GOOGLE_SHEETS_ID", "abc123")
    env.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "does/not/exist.json")
    env.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
    cfg = get_config()
    assert cfg.has_service_account is True
    assert cfg.sheets_ready is True
