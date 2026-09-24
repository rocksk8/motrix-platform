"""存檔錯誤橫幅要一直留到存檔成功（W-2／W-3，2026-09-24 開發機實走發現）。

CU3 的紅色橫幅看的是 saveStatus==='error'。兩條路會在問題還在時把它清掉：
- W-2：前一次**成功**存檔排的「2 秒後清空狀態」計時器，在接著的失敗存檔之後觸發 ⇒ 橫幅消失
- W-3：存檔失敗後只要一打字（setDirty）⇒ saveStatus 變 'dirty' ⇒ 橫幅消失，要等自動存檔再失敗才回來
觀測點：畫面上的 [data-testid=save-banner]。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

NO = "MQ-BANNER-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
BANNER = "[data-testid=save-banner]"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        sid = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                           " VALUES (?,?,?,?,?,?)", (NO, "施工", 0, 0, now, now)).lastrowid
        cr = {"payment": {"items": [{"id": 1, "type": "尾款", "pct": 100, "received": False, "receivedAt": "", "note": ""}]},
              "stages": [{"id": sid, "label": "施工", "done": False}]}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()




def _open(browser, base, user):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.dismiss())
    page.goto(f"{base}/pages/login.html")
    page.fill('input[x-model="username"]', user[0])
    page.fill('input[x-model="password"]', user[1])
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    page.goto(f"{base}/pages/case-management.html?q={NO}&tab=fin")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    return page


def _break_and_save(page):
    page.evaluate(f"() => {{ const it = {DATA_JS}.cr.caseRecord.payment.items[0]; it.received = true; it.receivedAt = '' }}")
    page.click(".cm-header .btn-save")
    page.locator(BANNER).wait_for(state="visible", timeout=5000)


@pytest.mark.e2e
def test_banner_survives_the_previous_successs_clear_timer(live_server, make_user, e2e_browser):
    u = make_user(username="bnr_e1", role="admin")
    _seed()
    browser = e2e_browser
    page = _open(browser, live_server, u)
    page.evaluate(f"() => {{ {DATA_JS}.cr.caseRecord.payment.items[0].note = '先成功存一次' }}")
    page.click(".cm-header .btn-save")
    page.locator("[data-testid=save-toast]").wait_for(state="visible", timeout=5000)
    _break_and_save(page)                    # 2 秒內接著失敗
    page.wait_for_timeout(3000)              # 前一次成功排的清空計時器（2 秒）已觸發
    assert page.locator(BANNER).is_visible(), "問題還在，錯誤橫幅卻被上一次成功存檔的計時器清掉了"


@pytest.mark.e2e
def test_banner_survives_typing_after_an_error(live_server, make_user, e2e_browser):
    u = make_user(username="bnr_e2", role="admin")
    _seed()
    browser = e2e_browser
    page = _open(browser, live_server, u)
    _break_and_save(page)
    note = page.locator("[data-testid=fin-payment] input[placeholder='收款備註...']").first
    note.fill("打字")                          # @input ⇒ setDirty()
    page.wait_for_timeout(300)
    assert page.locator(BANNER).is_visible(), "一打字錯誤橫幅就消失了（問題還在）"
