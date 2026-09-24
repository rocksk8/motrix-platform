"""瀏覽器端對端：案件管理同時編輯不再靜默覆蓋（CM1，2026-09-24）。

HANDOFF「🟢 CM」CM1（hichan-0a 已讀碼確認）：case-management.js 存檔只送 {case_record}、
不送版本，後端收到就整份取代 caseRecord ⇒ 兩個人同時編同一件，後存的人靜默蓋掉前一個人的改動
（包括前一個人剛上傳的發票檔）。

做法：分段存＋分段比對基準——只送改到的分段；伺服器比對「資料庫現值」與「頁面載入時的基準」，
一致才替換那一段，否則 409。
- 兩人改不同分頁 ⇒ 兩人的改動都在資料庫
- 兩人改同一分頁 ⇒ 後存者 409，沒有被靜默覆蓋，畫面說出是哪一段
- 自己在頁面上傳附件後再改同一分頁 ⇒ 不會被自己擋下，附件保留
觀測點打在資料庫落地值。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

NO = "MQ-E2ECC-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
NOTE_INPUT = 'input[placeholder="收款備注..."]'


@pytest.fixture()
def live_server(client):
    import main
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


def _login(page, base_url, username, password):
    page.goto(f"{base_url}/pages/login.html")
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)


def _seed():
    import db
    cr = {"payment": {"items": [
              {"id": 1, "type": "訂金款", "pct": 30, "amount": 30000, "received": False, "note": ""},
              {"id": 2, "type": "尾款", "pct": 70, "amount": 70000, "received": False, "note": ""}]},
          "materials": [{"id": 11, "name": "原始料件", "qty": 1, "unit": "台", "ordered": False, "arrived": False,
                         "model": "", "devices": []}],
          "stages": [{"label": "訂單確認"}]}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "同編客戶", "同編專案", 100000, 95238,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


def _cr():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["caseRecord"]


def _open(browser, base, user):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    # CU5（2026-09-24）：收款搬到「財務」分頁 ⇒ 以 ?tab=fin 直接開到那一頁
    page.goto(f"{base}/pages/case-management.html?q={NO}&tab=fin")
    page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=10000)
    return page


def _save(page):
    """直接呼叫存檔（不等 1.5 秒防抖），回傳存檔後的訊息。"""
    return page.evaluate(f"async () => {{ const c = {DATA_JS}; await c.saveCaseRecord(); return c.saveMsg }}")


@pytest.mark.e2e
def test_two_people_editing_different_tabs_both_survive(live_server, make_user):
    a = make_user(username="cc_a", role="admin")
    b = make_user(username="cc_b", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pa, pb = _open(browser, live_server, a), _open(browser, live_server, b)
            pa.evaluate(f"() => {{ {DATA_JS}.cr.caseRecord.payment.items[0].note = 'A 改收款' }}")
            pb.evaluate(f"() => {{ {DATA_JS}.cr.caseRecord.materials[0].name = 'B 改材料' }}")
            assert "已儲存" in _save(pa)
            assert "已儲存" in _save(pb)
            cr = _cr()
            assert cr["payment"]["items"][0]["note"] == "A 改收款", "B 的存檔把 A 的收款改動蓋掉了"
            assert cr["materials"][0]["name"] == "B 改材料"
        finally:
            browser.close()


@pytest.mark.e2e
def test_two_people_editing_same_tab_later_one_gets_conflict(live_server, make_user):
    a = make_user(username="cc_a2", role="admin")
    b = make_user(username="cc_b2", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pa, pb = _open(browser, live_server, a), _open(browser, live_server, b)
            pa.evaluate(f"() => {{ {DATA_JS}.cr.caseRecord.payment.items[0].note = 'A 先存' }}")
            pb.evaluate(f"() => {{ {DATA_JS}.cr.caseRecord.payment.items[1].note = 'B 後存' }}")
            assert "已儲存" in _save(pa)
            msg = _save(pb)
            assert "已被他人更新" in msg and "收款" in msg, msg
            cr = _cr()
            assert cr["payment"]["items"][0]["note"] == "A 先存", "後存者不可以靜默蓋掉先存者"
            assert cr["payment"]["items"][1]["note"] == ""
            # 「保留我的變更再試」：以伺服器現值為基準重存（明知並覆蓋那一段）
            pb.evaluate(f"async () => {{ await {DATA_JS}.resolveConflict('keep') }}")
            assert _cr()["payment"]["items"][1]["note"] == "B 後存"
        finally:
            browser.close()


@pytest.mark.e2e
def test_own_upload_then_edit_same_tab_does_not_conflict(live_server, make_user):
    a = make_user(username="cc_a3", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pa = _open(browser, live_server, a)
            ok = pa.evaluate(f"""async () => {{
              const c = {DATA_JS}
              const f = new File([new Uint8Array([0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A])], 'inv.png', {{ type: 'image/png' }})
              await c.uploadPaymentItemInvoiceFiles(0, {{ target: {{ files: [f], value: '' }} }})
              return (c.cr.caseRecord.payment.items[0].invoiceFiles || []).length
            }}""")
            assert ok == 1
            pa.evaluate(f"() => {{ {DATA_JS}.cr.caseRecord.payment.items[0].note = '上傳後再改' }}")
            msg = _save(pa)
            assert "已儲存" in msg, msg
            item = _cr()["payment"]["items"][0]
            assert item["note"] == "上傳後再改" and len(item.get("invoiceFiles") or []) == 1
        finally:
            browser.close()
