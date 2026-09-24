"""全部階段完成不再彈確認視窗，改為內嵌提示條（2026-09-24 使用者表單）。

原本最後一個階段打勾 ⇒ 300ms 後跳 confirm「所有執行進度已完成！是否現在結案…」，
打斷正在做的事。改為執行進度上方的提示條「全部階段已完成 → 結案」：
最高管理者有「結案」鈕（開結案前檢查），其他人只有文字（結案只有最高管理者能按）。
觀測點：是否出現瀏覽器對話框、提示條與結案檢查視窗。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

NO = "MQ-ALLDONE-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
BAR = "[data-testid=all-done-bar]"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        cur = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                           " VALUES (?,?,?,?,?,?)", (NO, "施工", 0, 0, now, now))
        cr = {"payment": {"items": []}, "stages": [{"id": cur.lastrowid, "label": "施工", "done": False}]}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()




def _open(browser, base, user):
    page = browser.new_context().new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    inject_login(page, base, user[0], user[1])
    page.goto(f"{base}/pages/case-management.html?q={NO}&tab=exec")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    return page, dialogs


def _finish_last_stage(page):
    page.evaluate(f"async () => {{ const c = {DATA_JS}; await c.updateStage(c.cr.caseRecord.stages[0], {{ done: true }}) }}")


@pytest.mark.e2e
def test_superadmin_gets_inline_bar_instead_of_a_popup(live_server, make_user, e2e_browser):
    u = make_user(username="ad_e1", role="superadmin")
    _seed()
    browser = e2e_browser
    page, dialogs = _open(browser, live_server, u)
    assert page.locator(BAR).count() == 0 or not page.locator(BAR).is_visible()
    _finish_last_stage(page)
    bar = page.locator(BAR)
    bar.wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(800)                     # 舊版在 300ms 後才跳 confirm
    assert dialogs == [], f"不可以再彈確認視窗：{dialogs}"
    assert "全部階段已完成" in bar.inner_text()
    bar.locator("button").click()
    page.locator("[data-testid=close-check]").wait_for(state="visible", timeout=10000)


@pytest.mark.e2e
def test_others_see_the_bar_without_a_close_button(live_server, make_user, e2e_browser):
    u = make_user(username="ad_e2", role="admin")
    _seed()
    browser = e2e_browser
    page, dialogs = _open(browser, live_server, u)
    _finish_last_stage(page)
    bar = page.locator(BAR)
    bar.wait_for(state="visible", timeout=5000)
    assert bar.locator("button").count() == 0
    assert "最高管理者" in bar.inner_text()
    assert dialogs == []
