"""款項明細有未存修改時按「申請請款單」：用共用提示說明，不用原生 alert（CM12 P4，2026-09-24）。

原本 HTML 內嵌 alert('款項明細有未儲存的修改…')；改成 MotrixUI.toast(…, {kind:'error'})，
其餘行為不變（不跳頁）。觀測點：沒有瀏覽器原生對話框、畫面上出現提示、網址沒變。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

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


@pytest.fixture()
def live_server(client):
    import uvicorn
    import main
    from tests._ports import free_safe_port
    config = uvicorn.Config(main.app, host="127.0.0.1", port=free_safe_port(), log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("uvicorn 測試伺服器在時限內沒有啟動")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        t.join(timeout=5)


@pytest.mark.e2e
def test_unsaved_payment_shows_toast_not_native_alert(live_server, make_user):
    u = make_user(username="prh_e1", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            dialogs = []
            page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
            page.goto(f"{live_server}/pages/login.html")
            page.fill('input[x-model="username"]', u[0])
            page.fill('input[x-model="password"]', u[1])
            page.click('button:has-text("登入")')
            page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
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
        finally:
            browser.close()
