"""瀏覽器端對端：案件管理的資料遺失三類（2026-09-24）。

① 打完字 1.5 秒內切換案件 → 原本 selectCase() 取消待存計時器並 dirty=false，
   剛打的內容消失。現在要先存完上一張再切換。
② sidebar.js 的離頁警告旗標會被任何成功請求清掉，包括每 8～15 秒一次的
   同時編輯心跳（/api/edit-presence）⇒ 打完字最多 15 秒警告就失效。
③ 刪除款項期別等沒有確認就刪（且 1.5 秒後自動存檔，無法復原）。

裁示 F1～F3（hichan-0a 代裁，待使用者確認）。觀測點打在資料庫落地值。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

NOTE_INPUT = 'input[placeholder="收款備註..."]'


@pytest.fixture()
def live_server(client):
    """比照 test_e2e_t100_unconfirm_2026_09_10.py 的同名 fixture。"""
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1", port=free_safe_port(), log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
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
        thread.join(timeout=5)


def _login(page, base_url, username, password):
    page.goto(f"{base_url}/pages/login.html")
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)


def _seed(quote_no):
    import db
    items = [
        {"id": 1, "type": "訂金款", "pct": 30, "amount": 30000, "received": False, "note": ""},
        {"id": 2, "type": "尾款", "pct": 70, "amount": 70000, "received": False, "note": ""},
    ]
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "遺失測客", "遺失測專", 100000, 95238,
             json.dumps({"dealTag": "已成案", "caseRecord": {
                 "payment": {"items": items}, "materials": [],
                 "stages": [{"label": "訂單確認"}]}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-08-01"),
        )
        conn.commit()
    finally:
        conn.close()


def _items(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["caseRecord"]["payment"]["items"]


def _open(page, base, quote_no):
    # CU5（2026-09-24）：收款搬到「財務」分頁 ⇒ 以 ?tab=fin 直接開到那一頁
    page.goto(f"{base}/pages/case-management.html?q={quote_no}&tab=fin")
    page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=15000)


def _wait_saved(page):
    page.wait_for_function(
        "() => { const e = document.querySelector('span.save-label');"
        " return e && e.textContent.includes('已儲存') }", timeout=15000)


@pytest.mark.e2e
def test_switching_case_right_after_typing_keeps_the_input(live_server, make_user):
    username, password = make_user(username="e2e_loss1", role="admin")
    _seed("MQ-E2ELOSS-A")
    _seed("MQ-E2ELOSS-B")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            _open(page, live_server, "MQ-E2ELOSS-A")
            page.locator(NOTE_INPUT).first.fill("切換前打的字")
            # 1.5 秒防抖還沒到就切換
            page.locator('.cm-card[data-quote-no="MQ-E2ELOSS-B"]').click()
            page.locator('.cm-card.selected[data-quote-no="MQ-E2ELOSS-B"]').wait_for(timeout=15000)
            assert _items("MQ-E2ELOSS-A")[0]["note"] == "切換前打的字"
        finally:
            browser.close()


# 在頁面裡用 sidebar.js 包過的 fetch 打一次請求（等同頁面自己發出）
_FETCH_JS = """async ([url, method, body]) => {
  const tok = JSON.parse(localStorage.getItem('motrix_session') || '{}').token
  const r = await fetch(url, { method, headers: { Authorization: 'Bearer ' + tok,
    'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  return r.status
}"""
PRESENCE = "/api/edit-presence"


@pytest.mark.e2e
def test_dirty_flag_survives_presence_heartbeat(live_server, make_user):
    """edit-presence.js 每 8～15 秒 POST 一次；sidebar.js 原本「任何成功請求就清掉」，
    打完字最多 15 秒離頁警告就失效。"""
    username, password = make_user(username="e2e_loss2", role="admin")
    _seed("MQ-E2ELOSS-C")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            _open(page, live_server, "MQ-E2ELOSS-C")
            page.wait_for_load_state("networkidle")
            page.locator(NOTE_INPUT).first.fill("x")
            assert page.evaluate("() => window.motrixIsDirty") is True
            status = page.evaluate(_FETCH_JS, [PRESENCE, "POST",
                                               {"doc_type": "case", "doc_id": "MQ-E2ELOSS-C"}])
            assert 200 <= status < 300, status
            assert page.evaluate("() => window.motrixIsDirty") is True, "心跳不是存檔，不可以清掉"
            _wait_saved(page)
            assert page.evaluate("() => window.motrixIsDirty") is False, "存完不應再警告"
        finally:
            browser.close()


@pytest.mark.e2e
def test_other_pages_still_clear_flag_after_successful_save(live_server, make_user):
    """現行行為不退：不相干的頁面，成功的寫入請求照樣清掉旗標。"""
    username, password = make_user(username="e2e_loss2b", role="admin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/parts.html")
            page.wait_for_load_state("networkidle")
            page.evaluate("() => { window.motrixIsDirty = true }")
            status = page.evaluate(_FETCH_JS, ["/api/list-prefs/e2e_dirty_probe", "PUT",
                                               {"sortMode": "", "sortDir": "desc", "customOrder": []}])
            assert 200 <= status < 300, status
            assert page.evaluate("() => window.motrixIsDirty") is False
        finally:
            browser.close()


@pytest.mark.e2e
def test_deleting_payment_item_asks_first(live_server, make_user):
    username, password = make_user(username="e2e_loss3", role="admin")
    _seed("MQ-E2ELOSS-D")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            _open(page, live_server, "MQ-E2ELOSS-D")
            seen = []
            answer = {"accept": False}

            def _on_dialog(d):
                seen.append(d.message)
                d.accept() if answer["accept"] else d.dismiss()
            page.on("dialog", _on_dialog)

            first_del = page.locator(
                "xpath=(//label[.//span[normalize-space()='未收']]"
                "/following-sibling::button[contains(@class,'btn-del')])[1]")
            first_del.click()
            assert seen and "訂金款" in seen[0], seen
            time.sleep(2.0)   # 超過 1.5 秒防抖：若沒有確認就刪，這時已經存進去了
            assert [it["id"] for it in _items("MQ-E2ELOSS-D")] == [1, 2], "取消之後不可以刪"

            answer["accept"] = True
            first_del.click()
            _wait_saved(page)
            assert [it["id"] for it in _items("MQ-E2ELOSS-D")] == [2]
        finally:
            browser.close()


@pytest.mark.e2e
def test_other_deletes_are_gated_by_confirm(live_server, make_user):
    """階段、拜訪、材料、設備（單台／依物件）四類刪除：使用者按取消就不刪。
    直接呼叫元件方法，把 confirm 換成回傳 false——驗的是「方法本身有問」，
    不依賴各自藏在哪個分頁的按鈕位置。"""
    username, password = make_user(username="e2e_loss4", role="admin")
    _seed("MQ-E2ELOSS-E")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            _open(page, live_server, "MQ-E2ELOSS-E")
            result = page.evaluate("""async () => {
              const el = [...document.querySelectorAll('[x-data]')].find(e => e._x_dataStack && e._x_dataStack[0].selectCase)
              const c = el._x_dataStack[0]
              const rec = c.cr.caseRecord
              rec.materials = [{ id: 1, name: '測試料件' }]
              rec.devices = [{ id: 7, name: '測試設備', sn: 'SN1' }]
              rec.stages = [{ id: 999999, label: '測試階段', visits: [{ id: 5, visitDate: '2026-09-01' }] }]
              const asked = []
              window.confirm = (m) => { asked.push(m); return false }
              const calls = []
              window.fetch = (...a) => { calls.push(a[0]); return Promise.resolve(new Response('{}')) }
              c.removeMaterial(0)
              c.removeDevice(0)
              c.removeDeviceByObj(rec.devices[0])
              await c.removeStage(0)
              await c.removeVisit(0, 0)
              return { asked, calls, m: rec.materials.length, d: rec.devices.length,
                       s: rec.stages.length, v: rec.stages[0].visits.length }
            }""")
            assert len(result["asked"]) == 5, result
            assert "測試料件" in result["asked"][0] and "測試設備" in result["asked"][1]
            assert "測試階段" in result["asked"][3]
            assert (result["m"], result["d"], result["s"], result["v"]) == (1, 1, 1, 1), result
            assert result["calls"] == [], "按取消不可以送出 DELETE"
        finally:
            browser.close()


@pytest.mark.e2e
def test_remaining_deletes_are_gated_by_confirm(live_server, make_user):
    """N11（使用者 2026-09-24 裁示「刪除確認全部都加」）：叫料品項、派工人員、派工品項、
    出貨品項、階段負責人——按取消就不刪，也不送出 DELETE。確認訊息帶出名稱。"""
    username, password = make_user(username="e2e_loss5", role="admin")
    _seed("MQ-E2ELOSS-F")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            _open(page, live_server, "MQ-E2ELOSS-F")
            result = page.evaluate("""async () => {
              const el = [...document.querySelectorAll('[x-data]')].find(e => e._x_dataStack && e._x_dataStack[0].selectCase)
              const c = el._x_dataStack[0]
              c.materialOrders = [{ itemName: '測試叫料' }]
              c.dispatchForm = Object.assign({}, c.dispatchForm || {}, {
                personnel: [{ name: '派工甲', amount: 1 }], items: [{ description: '派工品項', amount: 1 }] })
              c.shippingForm = Object.assign({}, c.shippingForm || {}, { items: [{ description: '出貨品項' }] })
              const st = { id: 999999, label: '測試階段', assignedTo: ['someone'] }
              const asked = []
              window.confirm = (m) => { asked.push(m); return false }
              const calls = []
              window.fetch = (...a) => { calls.push(a[0]); return Promise.resolve(new Response('{}')) }
              c.moRemoveItem(0)
              c.removeDispatchPersonnel(0)
              c.removeDispatchItem(0)
              c.removeShippingItem(0)
              await c.removeStageAssignee(st, 'someone')
              return { asked, calls, mo: c.materialOrders.length, dp: c.dispatchForm.personnel.length,
                       di: c.dispatchForm.items.length, si: c.shippingForm.items.length, sa: st.assignedTo.length }
            }""")
            assert len(result["asked"]) == 5, result
            for name, msg in zip(("測試叫料", "派工甲", "派工品項", "出貨品項", "測試階段"), result["asked"]):
                assert name in msg, (name, msg)
            assert (result["mo"], result["dp"], result["di"], result["si"], result["sa"]) == (1, 1, 1, 1, 1), result
            assert result["calls"] == [], "按取消不可以送出 DELETE"
        finally:
            browser.close()
