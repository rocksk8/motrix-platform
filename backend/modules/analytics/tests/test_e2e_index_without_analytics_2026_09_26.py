"""自 `tests/test_e2e_index_without_analytics_2026_09_26.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import pytest
pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests.test_e2e_index_without_analytics_2026_09_26 import (  # noqa: E402,F401  含 fixture
    _MISSING,
    _open,
)


@pytest.mark.e2e
def test_index_shows_normal_hero_when_analytics_is_loaded(live_server, make_user, e2e_browser):
    """正對照：模組在 ⇒ 沒有「需要營運分析模組」的說明。"""
    page = _open(e2e_browser, live_server, make_user, "idx_an_ok", stats_404=False)
    page.wait_for_function("() => { const el = document.querySelector('[x-data]'); "
                           "return el && Alpine.$data(el) && Alpine.$data(el).statsLoaded === true }", timeout=15000)
    assert page.locator(_MISSING).count() == 0
