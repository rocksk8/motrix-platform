"""瀏覽器端對端：自訂報表頁（T87 B2-S4）。

流程：選條件 → 預覽 → 存成我的報表 → 重新整理後還在 → 匯出 Excel；無金額權限者的矩陣；旗標關閉時頁面與報表中心卡片；
a11y 規格（h5 r2 nits）：焦點保留、表頭核取框 indeterminate、批次復原會被後續編輯作廢、鎖定列每列只有一個 Tab 停駐點。
每一步等的是「這一次預覽完成」的條件（摘要文字），不是立刻讀畫面。
"""
import io

import openpyxl
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests.platform.test_custom_reports_export_t87 import _quote, _set  # noqa: E402

PREVIEW_ROWS = "[data-testid=cr-preview] tbody tr"


@pytest.fixture(autouse=True)
def _flag(client):
    _set(enabled=1)
    yield
    _set(enabled=0)


def _open(live_server, make_user, e2e_browser, name, role="superadmin", modules=None, path="custom-reports.html", viewport=(1440, 900)):
    username, password = make_user(username=name, role=role, **({"modules": modules, "legacy_finance_flag": False} if modules else {}))
    page = e2e_browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/{path}")
    return page


def _ready(page):
    page.wait_for_selector("[data-testid=cr-matrix] tbody tr", timeout=20000)
    page.wait_for_selector("[data-testid=cr-summary]", timeout=20000)


def _summary(page):
    return page.locator("[data-testid=cr-summary]").inner_text()


def _filter_customer(page, text, expect_total):
    page.check("[data-fk='m:customer_name:f']")
    page.fill("[aria-label='客戶 值']", text)
    page.wait_for_function(
        """(n) => { const s = document.querySelector('[data-testid=cr-summary]');
                    return s && s.innerText.startsWith('共 ' + n + ' 筆') && !document.querySelector('[data-testid=cr-loading]') }""",
        arg=expect_total, timeout=20000)


@pytest.mark.e2e
def test_build_save_reload_and_export(live_server, make_user, e2e_browser):
    _quote(no="E2E-CR-1", customer_name="端到端甲", total=1200)
    _quote(no="E2E-CR-2", customer_name="端到端甲", total=3400)
    _quote(no="E2E-CR-3", customer_name="端到端乙", total=99)
    page = _open(live_server, make_user, e2e_browser, "e2e_cr1")
    _ready(page)
    # 還沒存：不能匯出
    assert page.locator("[data-testid=cr-export]").is_disabled()
    _filter_customer(page, "端到端甲", 2)
    assert page.locator(PREVIEW_ROWS).count() == 2
    # 儲存
    page.click("[data-testid=cr-save]")
    page.fill("[data-testid=cr-name]", "端到端報表")
    page.click("[data-testid=cr-name-ok]")
    page.wait_for_function("() => document.getElementById('sbTitle').textContent === '端到端報表' && !document.getElementById('btnExport').disabled", timeout=20000)
    # 重新整理：報表還在、條件還在
    page.goto(f"{live_server}/pages/custom-reports.html")
    page.wait_for_selector("[data-testid^=cr-report-]", timeout=20000)
    page.click("[data-testid^=cr-report-]:has-text('端到端報表')")
    page.wait_for_selector("[aria-label='客戶 值']", timeout=20000)
    assert page.input_value("[aria-label='客戶 值']") == "端到端甲"
    page.wait_for_function("() => { const s = document.querySelector('[data-testid=cr-summary]'); return s && s.innerText.startsWith('共 2 筆') }", timeout=20000)
    # 匯出 Excel：只有兩筆「端到端甲」
    page.click("[data-testid=cr-export]")
    with page.expect_download(timeout=30000) as dl:
        page.click("[data-testid=cr-export-go]")
    with open(dl.value.path(), "rb") as fh:
        wb = openpyxl.load_workbook(io.BytesIO(fh.read()))
    ws = wb["報表"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "E2E-CR-1" in flat and "E2E-CR-2" in flat and "E2E-CR-3" not in flat
    assert wb["說明"]["A1"].value == "資料來源"
    page.close()


@pytest.mark.e2e
def test_user_without_money_permission_sees_locked_cells_with_one_tab_stop_per_row(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_cr2", role="engineer", modules=["quotation"])
    _ready(page)
    locked = page.locator("[data-testid=cr-matrix] tbody tr[aria-describedby]")
    assert locked.count() >= 1
    n = locked.count()
    # 每個鎖定列只有「顯示」格一個 Tab 停駐點；圖例以 aria-describedby 掛在列層
    assert page.locator("[data-testid=cr-matrix] tbody tr[aria-describedby] td[tabindex='0']").count() == n
    assert page.locator("[data-testid=cr-matrix] tbody tr[aria-describedby] td.lock").first.inner_text().startswith("無權限")
    assert page.locator("#lg-lock").count() == 1
    # 表頭「顯示」核取框只看可用欄：全選時不是 indeterminate
    page.close()


@pytest.mark.e2e
def test_focus_kept_indeterminate_header_and_undo_invalidated_by_other_edits(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_cr3")
    _ready(page)
    box = "[data-fk='m:status:show']"
    was = page.is_checked(box)
    page.focus(box)
    page.keyboard.press("Space")
    assert page.is_checked(box) != was
    assert page.evaluate("() => document.activeElement.getAttribute('data-fk')") == "m:status:show"      # 重畫後焦點還在同一格
    # 部分欄位顯示：表頭核取框是 indeterminate
    assert page.evaluate("() => document.querySelector('[data-fk=showAll]').indeterminate") is True
    # 批次 → 出現「復原上一次批次」；之後做了別的編輯 ⇒ 復原鈕作廢
    page.click("[data-fk='batch:hide']")
    assert page.locator("#btnUndo").is_visible()
    page.check("[data-fk='m:customer_name:g']")
    assert page.locator("#btnUndo").is_hidden()
    # 批次訊息：略過 0 項時不寫「略過」
    page.check("[data-fk='m:quote_no:pick']")
    page.click("[data-fk='batch:show']")
    assert "略過" not in page.locator("#batchMsg").inner_text()
    # 提示節點常駐 DOM
    assert page.locator("#toast[role=status]").count() == 1
    page.close()


@pytest.mark.e2e
def test_flag_off_shows_not_open_and_hides_hub_card(live_server, make_user, e2e_browser):
    _set(enabled=0)
    page = _open(live_server, make_user, e2e_browser, "e2e_cr4")
    page.wait_for_selector("#crLoadError:not([hidden])", timeout=20000)
    assert "尚未開放" in page.locator("#crLoadError").inner_text()
    hub = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    hub.add_init_script(page.evaluate("() => localStorage.getItem('motrix_session')") and
                        "try{localStorage.setItem('motrix_session', %r)}catch(e){}" % page.evaluate("() => localStorage.getItem('motrix_session')"))
    hub.goto(f"{live_server}/pages/reports-hub.html")
    hub.wait_for_selector("[data-testid^=rh-card-]", timeout=20000)
    hub.wait_for_timeout(800)
    assert hub.locator("[data-testid*='custom-reports']").count() == 0
    _set(enabled=1)
    hub.reload()
    hub.wait_for_selector("[data-testid*='custom-reports']", timeout=20000)
    hub.close()
    page.close()
