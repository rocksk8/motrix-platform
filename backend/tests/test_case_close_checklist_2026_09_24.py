"""結案前先列出五關、可點過去修（2026-09-24 使用者表單）。

過去 closeCaseAction() 先跳 confirm、再存檔（失敗照樣往下送結案）、最後才被 400 擋下，
使用者看到的是一串理由、不知道去哪裡修；關卡矩陣的格子也不能點。

- GET /api/quotations/{no}/close-gates：五關（與擋結案同一份 _case_close_gates）＋
  單據關逐類待簽筆數＋待簽核人顯示名稱；可見性比照單筆讀取
- 頁面按「完結案」⇒ 先存檔，失敗就中止；成功後列出五關，未過的有「前往」；五關未全過不能按確認
- 關卡矩陣的格子可點，開案件並停在該關的分頁
觀測點：API 回應、資料庫 deal_tag、頁面 activeTab。
"""
import json
import threading
import time

import pytest

NO = "MQ-CLOSECK-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(*, received=False, stages_done=False, pending_ship=True, sales="", approver="ck_boss"):
    import db
    cr = {"payment": {"items": [{"id": 1, "type": "尾款", "pct": 100, "amount": 1000,
                                 "received": received, "receivedAt": "2026-09-01" if received else ""}]}}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        cur = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                           " VALUES (?,?,?,?,?,?)", (NO, "施工", 0, 1 if stages_done else 0, now, now))
        # 頁面以 caseRecord.stages 判斷要不要補預設階段；兩邊要一致，否則頁面會再多建五個
        cr["stages"] = [{"id": cur.lastrowid, "label": "施工", "done": stages_done}]
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, sales_person, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "結案客戶", "結案專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", sales, "2026-08-01"))
        if pending_ship:
            appr = {"tiers": [{"order": 0, "approvers": [
                {"username": approver, "displayName": "舊名字", "status": "pending"}]}], "currentTier": 0}
            conn.execute(
                "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, items_json, data_json,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                ("SN-CLOSECK-1", NO, "簽核中", "結案客戶", "[]",
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


def _deal_tag():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT deal_tag FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0]
    finally:
        conn.close()


# ── API ──────────────────────────────────────────────────────────────────

def test_close_gates_lists_five_gates_with_pending_approver_names(client, make_user):
    h = _login(client, *make_user(username="ck_admin", role="superadmin"))
    make_user(username="ck_boss", role="admin")
    _set_display_name("ck_boss", "王經理")
    _seed()
    r = client.get(f"/api/quotations/{NO}/close-gates", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [g["key"] for g in body["gates"]] == ["progress", "payment", "documents", "settlement", "extraExpense"]
    assert body["canClose"] is False
    docs = next(g for g in body["gates"] if g["key"] == "documents")
    assert docs["state"] == "blocked"
    # 待簽核人要是「現在的」顯示名稱，不是簽核流程建立時寫進去的舊名字
    assert [a["displayName"] for a in docs["pendingApprovers"]] == ["王經理"]
    assert {"table": "shipping_notes", "label": "出貨單", "count": 1} in docs["pendingDocs"]


def test_close_gates_can_close_matches_the_close_endpoint(client, make_user):
    h = _login(client, *make_user(username="ck_admin2", role="superadmin"))
    _seed(received=True, stages_done=True, pending_ship=False)
    body = client.get(f"/api/quotations/{NO}/close-gates", headers=h).json()
    assert body["canClose"] is True
    r = client.patch(f"/api/quotations/{NO}/deal-tag", headers=h, json={"deal_tag": "已結案"})
    assert r.status_code == 200, r.text


def test_close_gates_is_not_visible_to_another_salesperson(client, make_user):
    owner = _login(client, *make_user(username="ck_owner", role="sales"))
    h = _login(client, *make_user(username="ck_other", role="sales"))
    _seed(sales="ck_owner")
    # 正對照：自己名下的看得到（否則 404 可能只是端點不存在）
    assert client.get(f"/api/quotations/{NO}/close-gates", headers=owner).status_code == 200
    r = client.get(f"/api/quotations/{NO}/close-gates", headers=h)
    assert r.status_code == 403, r.text


# ── 頁面 ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def live_server(client):
    pytest.importorskip("playwright.sync_api")
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


def _open(browser, base, user, path=None):
    page = browser.new_context().new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    page.goto(f"{base}/pages/login.html")
    page.fill('input[x-model="username"]', user[0])
    page.fill('input[x-model="password"]', user[1])
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    page.goto(f"{base}/pages/case-management.html" + (path or f"?q={NO}"))
    if path is None:
        page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'",
                               timeout=20000)
    return page, dialogs


@pytest.mark.e2e
def test_close_button_shows_the_gates_first_and_goto_switches_tab(live_server, make_user):
    from playwright.sync_api import sync_playwright
    u = make_user(username="ck_e1", role="superadmin")
    make_user(username="ck_boss", role="admin")
    _set_display_name("ck_boss", "王經理")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page, dialogs = _open(browser, live_server, u)
            # CU5（2026-09-24）：「完結案」收進標頭「更多」選單
            page.click('[data-testid="cm-more"]')
            page.click("button.btn-close-case:not([data-testid])")
            dlg = page.locator("[data-testid=close-check]")
            dlg.wait_for(state="visible", timeout=10000)
            assert dialogs == [], f"列出五關之前就跳了確認框：{dialogs}"
            for label in ("進度", "收款", "單據", "精算", "變更"):
                assert dlg.locator(f"[data-gate-label='{label}']").count() == 1, label
            assert "王經理" in dlg.locator("[data-gate-label='單據']").inner_text()
            assert dlg.locator("[data-testid=close-confirm]").is_disabled(), "五關未過卻可以按確認結案"
            dlg.locator("[data-gate-label='進度'] [data-testid=gate-goto]").click()
            page.wait_for_function(f"() => {DATA_JS}.activeTab === 'exec'", timeout=5000)
            dlg.wait_for(state="hidden", timeout=5000)
            assert _deal_tag() == "已成案"
        finally:
            browser.close()


@pytest.mark.e2e
def test_close_stops_when_save_fails(live_server, make_user):
    from playwright.sync_api import sync_playwright
    u = make_user(username="ck_e2", role="superadmin")
    _seed(received=True, stages_done=True, pending_ship=False)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page, dialogs = _open(browser, live_server, u)
            # 已收款卻沒有收款日期 ⇒ 存檔失敗
            page.evaluate(f"() => {{ const c = {DATA_JS}; c.cr.caseRecord.payment.items[0].receivedAt = '' }}")
            page.evaluate(f"() => {DATA_JS}.closeCaseAction()")
            page.wait_for_timeout(1500)
            assert not page.locator("[data-testid=close-check]").is_visible(), "存檔失敗仍往下走"
            assert _deal_tag() == "已成案"
        finally:
            browser.close()


@pytest.mark.e2e
def test_all_gates_passed_confirm_closes_the_case(live_server, make_user):
    from playwright.sync_api import sync_playwright
    u = make_user(username="ck_e3", role="superadmin")
    _seed(received=True, stages_done=True, pending_ship=False)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page, _ = _open(browser, live_server, u)
            # CU5（2026-09-24）：「完結案」收進標頭「更多」選單
            page.click('[data-testid="cm-more"]')
            page.click("button.btn-close-case:not([data-testid])")
            btn = page.locator("[data-testid=close-check] [data-testid=close-confirm]")
            btn.wait_for(state="visible", timeout=10000)
            assert btn.is_enabled()
            btn.click()
            for _ in range(100):
                if _deal_tag() == "已結案":
                    break
                time.sleep(0.1)
            assert _deal_tag() == "已結案"
        finally:
            browser.close()


@pytest.mark.e2e
def test_gate_matrix_cell_opens_the_case_on_that_gates_tab(live_server, make_user):
    from playwright.sync_api import sync_playwright
    u = make_user(username="ck_e4", role="superadmin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page, _ = _open(browser, live_server, u, path="")
            page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.session && {DATA_JS}.session.token",
                                   timeout=20000)
            page.evaluate(f"() => {DATA_JS}.switchToMatrix()")
            cell = page.locator(f"tr[data-quote='{NO}'] td.cm-gate[data-gate='documents']")
            cell.wait_for(state="visible", timeout=10000)
            cell.click()
            page.wait_for_function(
                f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'"
                f" && {DATA_JS}.activeTab === 'shipping'", timeout=10000)
        finally:
            browser.close()
