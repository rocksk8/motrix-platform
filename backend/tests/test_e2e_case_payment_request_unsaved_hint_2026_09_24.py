"""款項明細有未存修改時按「申請請款單」：用共用提示說明，不用原生 alert（CM12 P4，2026-09-24）。

原本 HTML 內嵌 alert('款項明細有未儲存的修改…')；改成 MotrixUI.toast(…, {kind:'error'})，
其餘行為不變（不跳頁）。觀測點：沒有瀏覽器原生對話框、畫面上出現提示、網址沒變。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "MQ-PRHINT-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        sid = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                           " VALUES (?,?,?,?,?,?)", (NO, "施工", 0, 0, now, now)).lastrowid
        cr = {"payment": {"items": [{"id": 1, "type": "尾款", "pct": 100, "received": False, "note": ""}]},
              "stages": [{"id": sid, "label": "施工", "done": False}]}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()




@pytest.mark.e2e
def test_unsaved_payment_shows_toast_not_native_alert(live_server, make_user, e2e_browser):
    u = make_user(username="prh_e1", role="admin")
    _seed()
    browser = e2e_browser
    page = browser.new_context().new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/case-management.html?q={NO}&tab=fin")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    page.evaluate(f"() => {{ {DATA_JS}.dirty = true }}")
    url = page.url
    page.locator("[data-testid=fin-payment] button:has-text('申請請款單')").first.click()
    page.wait_for_timeout(800)
    assert dialogs == [], f"不可以再用原生對話框：{dialogs}"
    toast = page.locator(".mui-toasts")
    toast.wait_for(state="visible", timeout=5000)
    assert "未儲存的修改" in toast.inner_text()
    assert page.url == url, "有未存修改時不可以跳頁"
