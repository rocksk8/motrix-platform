"""瀏覽器端對端：CT1 外包名冊「分行」——名冊清單欄、Excel 匯入結果、簽核佇列外包人員帳戶列。

API 與 PDF 見 test_contractor_bank_branch_2026_09_24.py。觀測點打在畫面上真的看得到的文字與資料庫落地值。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401
from tests.test_contractor_bank_branch_2026_09_24 import _add_contractor, _contractor, _seed_voucher, _xlsx


@pytest.mark.e2e
def test_roster_list_shows_branch_and_import_reports_result(live_server, make_user, tmp_path, e2e_browser):
    u = make_user(username="ct1_e2e", role="superadmin")
    cid = _add_contractor("王小明", "A123456789", branch="台中分局")
    xlsx = tmp_path / "舊名冊.xlsx"
    xlsx.write_bytes(_xlsx(["姓名", "證件號碼", "分行"], [["王小明", "******6789", "北屯分局"],
                                                         ["查無", "******0000", "X"]]))
    browser = e2e_browser
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.dismiss())
    _login(page, live_server, *u)
    page.goto(f"{live_server}/pages/contractors.html")
    page.locator("td", has_text="台中分局").first.wait_for(timeout=15000)
    heads = page.locator("table.data-table thead th").all_inner_texts()
    assert "分行" in [h.strip() for h in heads], heads

    page.set_input_files('input[x-ref="importFile"]', str(xlsx))
    box = page.locator('[data-testid="ct-import-result"]')
    box.wait_for(state="visible", timeout=10000)
    assert "更新 1 位" in box.inner_text() and "未匯入 1 列" in box.inner_text()
    page.locator("td", has_text="北屯分局").first.wait_for(timeout=10000)
    assert _contractor(cid)["bank_branch"] == "北屯分局"


@pytest.mark.e2e
def test_approval_queue_voucher_shows_each_personnel_bank(live_server, make_user, e2e_browser):
    u = make_user(username="ct1_sa", role="superadmin")
    _seed_voucher()
    browser = e2e_browser
    page = browser.new_context().new_page()
    _login(page, live_server, *u)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_selector("text=CV-CT1-001", timeout=15000)
    page.click("text=CV-CT1-001")
    box = page.locator('[data-testid="aq-personnel-banks"]')
    box.wait_for(state="visible", timeout=10000)
    text = box.inner_text()
    for want in ("外包甲", "中華郵政", "台中分局", "00012345678901", "外包乙", "台新銀行", "22222"):
        assert want in text, (want, text)
