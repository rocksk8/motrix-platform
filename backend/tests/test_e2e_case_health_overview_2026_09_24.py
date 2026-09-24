"""案件資訊頁上方的案件健康總覽（2026-09-24 使用者表單）。

打開案件就看得到：五關狀態（與擋結案同一份判定，/close-gates）、逾期應收（未收款且
預計收款日已過）、待簽核（哪類單據、誰還沒簽）。點關卡可切到要處理的分頁。
快速切換案件時，總覽必須是最後選的那一件（回應晚到不可蓋掉）。
觀測點：頁面上總覽的文字與 activeTab。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

NO = "MQ-HEALTH-001"
NO2 = "MQ-HEALTH-002"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
PANEL = "[data-testid=case-health]"


def _seed(no, *, overdue_receipt=True, pending_ship=True, customer="健康客戶"):
    import db
    now = "2026-01-01T00:00:00"
    items = [
        {"id": 1, "type": "訂金款", "pct": 30, "received": True, "receivedAt": "2026-01-05",
         "expectedReceiptDate": "2026-01-01"},
        {"id": 2, "type": "尾款", "pct": 70, "received": False, "receivedAt": "",
         "expectedReceiptDate": "2026-02-01" if overdue_receipt else "2099-12-31"},
    ]
    conn = db.get_db()
    try:
        cur = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                           " VALUES (?,?,?,?,?,?)", (no, "施工", 0, 0, now, now))
        cr = {"payment": {"items": items},
              "stages": [{"id": cur.lastrowid, "label": "施工", "done": False}]}
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", customer, "健康專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", "2026-08-01"))
        if pending_ship:
            appr = {"tiers": [{"order": 0, "approvers": [
                {"username": "hl_boss", "displayName": "舊名字", "status": "pending"}]}], "currentTier": 0}
            conn.execute(
                "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, items_json, data_json,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                ("SN-" + no, no, "簽核中", customer, "[]",
                 json.dumps({"approval": appr}, ensure_ascii=False), now, now))
        conn.commit()
    finally:
        conn.close()


def _set_display_name(username, name):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name=? WHERE username=?", (name, username))
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


def _open(browser, base, user, no=NO):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    page.goto(f"{base}/pages/login.html")
    page.fill('input[x-model="username"]', user[0])
    page.fill('input[x-model="password"]', user[1])
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    page.goto(f"{base}/pages/case-management.html?q={no}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{no}'", timeout=20000)
    return page


@pytest.mark.e2e
def test_health_overview_shows_gates_overdue_receivable_and_pending_approvers(live_server, make_user):
    u = make_user(username="hl_e1", role="admin")
    make_user(username="hl_boss", role="admin")
    _set_display_name("hl_boss", "王經理")
    _seed(NO)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            panel = page.locator(PANEL)
            page.locator(f"{PANEL}[data-health-quote='{NO}']").wait_for(state="visible", timeout=10000)
            for label in ("進度", "收款", "單據", "精算", "變更"):
                assert panel.locator(f"[data-health-gate='{label}']").count() == 1, label
            text = panel.inner_text()
            assert "應收逾期 1 期" in text, text
            assert "尾款" in text, text
            assert "王經理" in text, text
            assert "出貨單" in text, text
            panel.locator("[data-health-gate='單據']").click()
            page.wait_for_function(f"() => {DATA_JS}.activeTab === 'shipping'", timeout=5000)
        finally:
            browser.close()


@pytest.mark.e2e
def test_health_overview_says_nothing_overdue_when_all_clear(live_server, make_user):
    u = make_user(username="hl_e2", role="admin")
    _seed(NO, overdue_receipt=False, pending_ship=False)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            page.locator(f"{PANEL}[data-health-quote='{NO}']").wait_for(state="visible", timeout=10000)
            text = page.locator(PANEL).inner_text()
            assert "應收逾期" not in text, text
            assert "待簽核" not in text, text
        finally:
            browser.close()


@pytest.mark.e2e
def test_health_overview_follows_the_last_selected_case(live_server, make_user):
    u = make_user(username="hl_e3", role="admin")
    _seed(NO)
    _seed(NO2, overdue_receipt=False, pending_ship=False, customer="第二客戶")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            # 第一件的總覽回應延後抵達：切到第二件之後才回來，不可蓋掉第二件的總覽
            page.route(f"**/api/quotations/{NO}/close-gates",
                       lambda route: (time.sleep(1.5), route.continue_()))
            page.evaluate(f"() => {{ const c = {DATA_JS}; c.selectCase('{NO}'); }}")
            page.evaluate(f"async () => {{ await {DATA_JS}.selectCase('{NO2}') }}")
            page.locator(f"{PANEL}[data-health-quote='{NO2}']").wait_for(state="visible", timeout=10000)
            page.wait_for_timeout(2500)
            assert page.locator(f"{PANEL}[data-health-quote='{NO2}']").count() == 1
            assert "應收逾期" not in page.locator(PANEL).inner_text()
        finally:
            browser.close()
