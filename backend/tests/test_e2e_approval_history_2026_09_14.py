"""瀏覽器層級：簽核歷史頁真的把紀錄畫出來，而且搜尋有作用（2026-09-14）。

端點本身在 `test_approval_reassign_history_2026_09_14.py` 已經測過。這支測的是
另一半：**頁面有沒有把回來的資料接上去**。兩者分開才有意義——端點對、畫面空白
是這個專案最常見的失敗型態（Alpine 的欄位名打錯不會有任何錯誤訊息）。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')




def _login(page, base_url, username, password):
    inject_login(page, base_url, username, password)


def _seed_audit(username, display, action, target_id, label, detail, at):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO audit_log (at, user_id, username, display_name, action, target_type, "
            "target_id, target_label, detail) VALUES (?,?,?,?,?,?,?,?,?)",
            (at, 0, username, display, action, "quotation", target_id, label,
             json.dumps(detail or {}, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_history_page_renders_and_searches(live_server, make_user, e2e_browser):
    """兩筆不同月份的簽核 → 表格有兩列、月份籤有兩個；搜尋退回原因只剩一列。"""
    u, p = make_user(username="ah_e2e", role="superadmin")
    _seed_audit("ah_e2e", "歷史測試員", "quotation.approve", "MQ-AH-001",
                "MQ-AH-001（宏達電）", {"allDone": True}, "2026-09-05T10:00:00")
    _seed_audit("ah_e2e", "歷史測試員", "quotation.reject", "MQ-AH-002",
                "MQ-AH-002（台積電）", {"note": "單價抓錯要重報"}, "2026-08-20T10:00:00")

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/approval-history.html")
    page.wait_for_selector(".ah-table tbody tr", timeout=10000)

    rows = page.locator(".ah-table tbody tr")
    assert rows.count() == 2, page.inner_text(".ah-table")
    body = page.inner_text(".ah-table")
    # 觀測點挑「只有接上資料才會出現」的欄位：單號、動作中文、備註
    assert "MQ-AH-001" in body and "MQ-AH-002" in body, body
    assert "核准" in body and "退回" in body, body
    assert "單價抓錯要重報" in body, body
    assert "台積電" in body, body

    # 每個月幾筆：兩個月份各一筆
    chips = page.inner_text(".ah-months")
    assert "2026-09" in chips and "2026-08" in chips, chips

    # 搜尋簽核內容（不是只搜單號）——輸入退回原因裡的字
    # 用 id 而不是 x-model：頂欄的全域搜尋也是 x-model="q"（sidebar.js:137）
    page.fill('#ah-q', "單價抓錯")
    page.click('#ah-search')
    page.wait_for_function(
        """() => document.querySelectorAll('.ah-table tbody tr').length === 1""",
        timeout=10000)
    assert "MQ-AH-002" in page.inner_text(".ah-table")

    # 點月份籤只看那個月
    page.click('#ah-clear')
    page.wait_for_function(
        """() => document.querySelectorAll('.ah-table tbody tr').length === 2""",
        timeout=10000)
    page.click('.ah-month:has-text("2026-08")')
    page.wait_for_function(
        """() => document.querySelectorAll('.ah-table tbody tr').length === 1""",
        timeout=10000)
    assert "MQ-AH-002" in page.inner_text(".ah-table")


@pytest.mark.e2e
def test_history_sidebar_entry_and_scope_for_non_admin(live_server, make_user, e2e_browser):
    """一般人也看得到自己的簽核歷史，但沒有「全公司」這個選項。

    後端 `scope=all` 會 403；畫面上把選項留著只會讓人踩一次空。
    """
    # 給 `quotation` 模組：側欄的簽核三兄弟（佇列／代理人／歷史）都掛在這個模組下，
    # 沒有模組的業務本來就看不到簽核佇列，歷史跟著同一條線才不會出現「看得到歷史
    # 卻進不去佇列」的怪組合。
    u, p = make_user(username="ah_sales", role="sales", modules=["quotation"])
    _seed_audit("ah_sales", "業務乙", "quotation.approve", "MQ-AH-101",
                "MQ-AH-101（客戶丙）", {}, "2026-09-06T10:00:00")

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/index.html")     # 登入改注入 token 後不會自動停在 index；這一題要看 index 上的導覽列
    # 導覽要有入口——功能做了但沒人找得到等於沒做。
    # 2026-09-14：側欄退役（display:none），入口搬到上方導覽列 #app-mainnav。
    # 用 state="attached" 而不是預設的 visible：mega-menu 的第二層
    # （.mnav__panel）平常是 opacity:0/visibility:hidden，要 hover 或 focus
    # 才展開，等 visible 會一路等到超時。這裡要確認的是「選單裡有這個入口」，
    # attached 就是對的觀測點。
    page.wait_for_selector('#app-mainnav a[href*="approval-history.html"]',
                           state="attached", timeout=10000)

    page.goto(f"{live_server}/pages/approval-history.html")
    page.wait_for_selector(".ah-table tbody tr", timeout=10000)
    assert "MQ-AH-101" in page.inner_text(".ah-table")
    # 2026-09-14：範圍改成籤列之後，觀測點跟著搬到**看得見的那個元素**。
    # 原本是 `#ah-scope option[value="all"]:visible`——隱藏的 <select>
    # 底下的 option 對任何人都不算 visible，那個斷言會變成永遠成立的
    # 假綠燈（管理員看得到也照樣綠）。
    assert page.locator('#ah-scope-all:visible').count() == 0, (
        "非管理員不該看到「全公司」——後端 scope=all 會 403，畫面留著只會讓人踩空")
    assert page.locator('#ah-scope-mine:visible').count() == 1, (
        "反向控制：「我簽核的」必須看得見，否則上面那題可能只是整列都沒渲染")
