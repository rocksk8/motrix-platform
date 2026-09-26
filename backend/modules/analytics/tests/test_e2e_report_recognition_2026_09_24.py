"""自 `tests/test_e2e_report_recognition_2026_09_24.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import pytest
pytest.importorskip("playwright.sync_api")
from tests.test_e2e_material_orders_2026_09_11 import _login  # noqa: F401
from tests.test_report_recognition_basis_2026_09_24 import _case, _stage, _dispatch, _db
from tests.test_e2e_report_recognition_2026_09_24 import (  # noqa: E402,F401  含 fixture
    RPT,
    _page,
)

from core import source_tree as _source_tree
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

#: 跨 M04×M08 的題（2026-09-26 第六班列車交會：外包工班與營運分析兩邊都把它搬進自己的 tests/，只留這一份）：
#: 同時需要外包工班；外包工班不在時略過——那時的行為（報表明說少了派工）由 test_reports_dispatch_row_consumer 負責。
needs_subcontract = pytest.mark.skipif(not _source_tree.module_installed("modules/subcontract/"),
                                       reason="需要外包工班模組（M04）")



@needs_subcontract
@pytest.mark.e2e
def test_report_shows_basis_note_and_flag_list_and_switches_basis(live_server, make_user, e2e_browser):
    _case("MQ-RBE-001")
    _dispatch("MQ-RBE-001", dispatch_date="2026-03-15")
    u = make_user(username="rbe_sa", role="superadmin")
    browser = e2e_browser
    page = _page(browser, live_server, u)
    page.goto(f"{live_server}/pages/reports.html")
    page.wait_for_function(f"() => {RPT} && typeof {RPT}.showExpensesTab === 'function'", timeout=20000)
    page.evaluate(f"() => {{ const c = {RPT}; c.expensesYear = 2026; c.showExpensesTab() }}")
    note = page.locator('[data-testid="basis-note"]')
    note.wait_for(state="visible", timeout=20000)
    assert "權責" in note.inner_text()
    flag = page.locator('[data-testid="flag-dispatch_no_invoice"]')
    flag.wait_for(state="visible", timeout=10000)
    flag.click()
    link = page.locator('[data-testid="recognition-flags"] a:has-text("MQ-RBE-001")')
    link.wait_for(state="visible", timeout=5000)
    assert link.get_attribute("href") == "case-management.html?q=MQ-RBE-001&tab=dispatch"

    page.click('[data-testid="basis-cash"]')
    page.wait_for_function(f"() => ({RPT}.expensesData || {{}}).basis === 'cash'", timeout=20000)
    assert "現金" in note.inner_text()
    assert page.evaluate(f"() => {RPT}.incomeTaxLabel") == "含稅"
