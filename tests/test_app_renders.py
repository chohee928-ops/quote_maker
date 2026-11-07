"""화면이 깨지지 않는지 확인하는 연기(smoke) 테스트.  실행: pytest -q"""
import pytest
from streamlit.testing.v1 import AppTest

from app import PAGES
from core.config import PROJECT_ROOT

APP = str(PROJECT_ROOT / "app.py")


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(page):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
