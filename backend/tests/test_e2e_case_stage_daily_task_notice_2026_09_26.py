"""每日任務模組（M12）不在時，案件執行進度的勾選／取消勾選／刪除要在畫面上明說少了什麼（AUDIT-X-C-batch1 B-1）。

API 早就回 `notice`，但 `updateStage` 只做 `Object.assign`、`removeStage` 不讀回應 ⇒ 使用者什麼都看不到。
觀測點：畫面上的提示（`.mui-toast`）文字；點的是真正的勾選框與「×」，不是直接呼叫方法。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests.platform.test_case_stage_connectors import _without  # noqa: E402
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "MQ-DTNOTICE-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
BOXES = ".stage-card__head input[type=checkbox]"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        a = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?)", (NO, "施工", 0, 0, now, now)).lastrowid
        # M12 在的時候勾過、建立過任務 77，之後 M12 被拿掉
        b = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, daily_task_id,"
                         " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         (NO, "叫料出貨", 1, 1, "2026-09-11", 77, now, now)).lastrowid
        cr = {"payment": {"items": []}, "stages": [{"id": a, "label": "施工", "done": False},
                                                   {"id": b, "label": "叫料出貨", "done": True, "doneAt": "2026-09-11"}]}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


def _toast(page, text):
    page.locator(".mui-toast", has_text=text).first.wait_for(state="visible", timeout=8000)


@pytest.mark.e2e
def test_without_m12_the_page_says_what_was_not_done(live_server, make_user, e2e_browser, monkeypatch):
    _without(monkeypatch, "daily_task.external", "daily_tasks")
    u = make_user(username="dtn_e1", role="superadmin")
    _seed()
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/case-management.html?q={NO}&tab=exec")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    boxes = page.locator(BOXES)
    boxes.first.wait_for(state="visible", timeout=10000)

    # 記下每一則提示（提示幾秒後會消失，數畫面上的元素會與消失時間賽跑）
    page.evaluate("() => { window.__toasts = []; const o = MotrixUI.toast;"
                  " MotrixUI.toast = (m, opt) => { window.__toasts.push(m); return o(m, opt) } }")
    notices = "() => window.__toasts.filter(m => m.includes('每日任務'))"

    boxes.nth(0).check()                                              # 勾選：沒有建立
    _toast(page, "未建立每日任務")                                     # 真的顯示在畫面上

    boxes.nth(1).uncheck()                                            # 取消勾選：原本的任務沒有收回
    _toast(page, "未收回每日任務")

    page.locator(".btn-del").nth(1).click()                          # 刪除那個階段：同樣沒有收回
    page.locator(".mui-btn--danger").click()
    page.wait_for_function(f"() => {DATA_JS}.cr.caseRecord.stages.length === 1", timeout=8000)
    page.wait_for_function(f"() => ({notices})().length >= 3", timeout=8000)
    got = page.evaluate(notices)
    assert [m.split("：")[0] for m in got] == ["未建立每日任務", "未收回每日任務", "未收回每日任務"], got
