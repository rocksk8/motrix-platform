"""自 `tests/test_e2e_view_filters_not_dirty_2026_09_25.py` 拆出的 reports 那一頁（M08 搬遷反向控制：需要營運分析模組）。本體共用原檔的 check_view_filters。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_view_filters_not_dirty_2026_09_25 import PAGES, check_view_filters  # noqa: E402

REPORTS = [p for p in PAGES if p[0] == "reports"]
assert REPORTS, "原檔 PAGES 裡找不到 reports"


@pytest.mark.e2e
@pytest.mark.parametrize("pg,filters,saved,setup", REPORTS, ids=[p[0] for p in REPORTS])
def test_changing_a_view_filter_does_not_arm_the_leave_warning(live_server, make_user, request, pg, filters, saved, setup, e2e_browser):
    check_view_filters(live_server, make_user, request, pg, filters, saved, setup, e2e_browser)
