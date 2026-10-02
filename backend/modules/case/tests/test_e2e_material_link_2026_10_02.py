"""32-S4e／33-M1 瀏覽器端對端（一個檔、一個瀏覽器、一題連續流程）：材料申請只能從「已核准的採購單明細」帶入。
入口：沒有「＋ 新增項目」、沒有「從報價單品項帶入」；審核中的採購單明細列出但不能勾（採購單尚未通過）→ 已核准的明細帶入 ⇒ 顯示對應的採購單、
沒有標註、同一明細不會再被帶入 → 沒選供應商存檔被擋 → 選供應商存檔 → 採購單作廢後重新載入 ⇒ 標註「已失效」回來 → 送審被後端擋下（需先申請請購單、再申請採購單…）、
狀態仍是草稿。舊單（已核准、沒有採購單連結）不受影響。終點以資料庫與頁面狀態為準；截圖存 logs/e2e-shots/wip-t32-s4a-2e。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

NO = "MQ-E2E-ML-1"
PANEL = "#fin-material-orders"
NOPO = "該材料申請未申請採購單"
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "logs", "e2e-shots", "wip-t32-s4a-2e")
Q = {"items": [
    {"id": "a", "description": "交換器", "qty": 10, "unit": "台", "unitPrice": 2000, "amount": 20000, "cost": 1000},
    {"id": "b", "description": "線材", "qty": 100, "unit": "米", "unitPrice": 10, "amount": 1000, "cost": 5},
]}



def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    page.screenshot(path=os.path.join(SHOTS, "s4e-%s.png" % name), full_page=False)


def _cr():
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]).get("caseRecord", {})
    finally:
        c.close()


def _orders():
    return {o["itemId"]: o for o in _cr().get("materialOrders", [])}


def _wait_db(page, pred, what, timeout=20):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return
        page.wait_for_timeout(400)                                    # 不用 time.sleep：Playwright 只在呼叫它的 API 時處理瀏覽器事件
    raise AssertionError("資料庫沒有達到預期狀態：" + what)


@pytest.mark.e2e
def test_material_request_link_flow_in_the_browser(live_server, make_user, e2e_browser):
    import db
    from helpers import _set_setting
    adm, ap = make_user(username="ml_adm", role="superadmin")
    boss, bp = make_user(username="ml_boss", role="superadmin")
    c = db.get_db()
    try:
        data = dict(Q, dealTag="已成案", caseRecord={"materialOrders": [
            {"itemId": "K", "itemName": "交換器（已申請）", "quantity": 4, "unit": "台", "unitPrice": 1000, "totalPrice": 4000, "paidStatus": "pending",
             "paidAmount": 0, "paidDate": "", "notes": "", "invoiceDate": "", "supplierId": 1, "quoteItemId": "a"},
            {"itemId": "Z", "itemName": "線材（已申請完）", "quantity": 100, "unit": "米", "unitPrice": 5, "totalPrice": 500, "paidStatus": "pending",
             "paidAmount": 0, "paidDate": "", "notes": "", "invoiceDate": "", "supplierId": 1, "quoteItemId": "b"}]})
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 21000, 21000, json.dumps(data, ensure_ascii=False),
                                                       "2026-10-02T00:00:00", "2026-10-02T00:00:00", "已成案", "2026-10-02"))
        c.execute("INSERT INTO suppliers (id, name, code, created_at, updated_at) VALUES (1, '甲供應商', 'S-001', '2026-10-02', '2026-10-02')")
        for iid in ("K", "Z"):
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,'已核准')", (NO, iid))
        c.commit()
    finally:
        c.close()
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})        # 採購單：送審即核准

    ctx = e2e_browser.new_context(viewport={"width": 1400, "height": 1100})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sess = inject_login(page, live_server, adm, ap)
    H = {"Authorization": "Bearer " + sess["token"]}

    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_selector(PANEL, timeout=20000)
    page.wait_for_function("() => document.querySelector('[data-testid=mo-card-K]') && !(document.querySelector('#fin-material-orders').innerText.includes('載入中'))", timeout=20000)
    page.wait_for_function("() => document.querySelector('[data-testid=ml-tab-approved]')", timeout=10000)

    # ── 0 沒有手動新增、沒有報價品項入口；空白提示指向採購單 ──
    assert page.locator('[data-testid="ml-open-quote"]').count() == 0
    assert page.locator(f'{PANEL} button:has-text("＋ 新增項目")').count() == 0
    assert "已核准的採購單明細" in page.locator('[data-testid="mo-po-only-note"]').inner_text()

    # ── 1 採購單：A 已核准（送審即核准）、B 審核中（有簽核人、還沒簽） ──
    from modules.case.tests.test_purchase_item_lines_2026_10_02 import _body, _ln
    r = ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses", headers=H, data=_body("purchase_order", [_ln("a", 3, unitCost=1000, summary="交換器（採購單）")]))
    assert r.status == 201, r.text()
    eid, doc = r.json()["id"], r.json()["docCode"]
    assert ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses/{eid}/submit", headers=H).status == 200
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [{"order": 0, "approvers": [{"username": boss, "displayName": "主管"}]}]})
    r = ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses", headers=H, data=_body("purchase_order", [_ln("a", 2, unitCost=1000, summary="交換器二號（採購單）")]))
    assert r.status == 201, r.text()
    eid2, doc2 = r.json()["id"], r.json()["docCode"]
    rs = ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses/{eid2}/submit", headers=H)
    assert rs.status == 200, rs.text()

    page.click('[data-testid="ml-open-po"]')
    row, row2 = page.locator(f'[data-testid="ml-p-{doc}-1"]'), page.locator(f'[data-testid="ml-p-{doc2}-1"]')
    row.wait_for(state="visible", timeout=15000)
    row2.wait_for(state="visible", timeout=15000)
    assert row2.locator("input").is_disabled() and "採購單尚未通過" in row2.inner_text()          # 審核中：列出但不能勾
    assert row.locator("input").is_enabled()
    _shot(page, "01-po-panel")
    row.locator("input").check()
    page.click('[data-testid="ml-import"]')
    page.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid^=ml-row-]').length === 3", timeout=10000)
    po_card = page.locator('[data-testid^="mo-card-"]').last
    assert po_card.locator('[data-testid^="ml-badge-"]').is_hidden()                                 # 連到採購單 ⇒ 沒有標註
    assert po_card.locator('[data-testid="mo-po-hint"]').is_hidden()                                 # 有採購單 ⇒ 沒有送審前提示

    # ── 2 沒選供應商存檔被擋；選了才存 ──
    page.locator(f'{PANEL} button[\@click="moSave()"]').click()
    page.wait_for_function("() => /供應商/.test(document.querySelector('#fin-material-orders').innerText)", timeout=10000)
    assert not any(o.get("poDocCode") == doc for o in _orders().values())
    page.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid=mo-supplier] option').length >= 2", timeout=15000)
    po_card.locator('[data-testid="mo-supplier"]').select_option(label="S-001 甲供應商")
    page.locator(f'{PANEL} button[\@click="moSave()"]').click()
    _wait_db(page, lambda: any(o.get("poDocCode") == doc for o in _orders().values()), "採購單連結已存")
    po_id = [k for k, o in _orders().items() if o.get("poDocCode") == doc][0]
    page.wait_for_function("(id) => { const e = document.querySelector('[data-testid=ml-linked-' + id + ']'); return e && e.offsetParent !== null }", arg=po_id, timeout=15000)
    assert doc in page.locator(f'[data-testid="ml-linked-{po_id}"]').inner_text()
    assert page.locator(f'[data-testid="ml-badge-{po_id}"]').is_hidden()
    _shot(page, "02-linked-no-badge")
    # 同一明細不能被第二筆材料申請再帶入
    page.click('[data-testid="ml-open-po"]')
    page.wait_for_function("() => !document.querySelector('[data-testid=ml-panel]').innerText.includes('載入中')", timeout=10000)
    assert page.locator(f'[data-testid="ml-p-{doc}-1"]').count() == 0
    page.click('[data-testid="ml-open-po"]')

    # ── 3 採購單作廢 ⇒ 連結失效 ⇒ 重新載入後標註回來；送審被擋、仍是草稿 ──
    c = db.get_db()
    c.execute("UPDATE case_extra_expenses SET status='已作廢' WHERE id=?", (eid,))
    c.commit()
    c.close()
    page.reload()
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_selector(PANEL, timeout=20000)
    page.click('[data-testid="ml-tab-all"]')
    page.wait_for_function("(id) => { const b = document.querySelector('[data-testid=ml-badge-' + id + ']'); return b && b.offsetParent !== null }", arg=po_id, timeout=20000)
    assert "已失效" in page.locator(f'[data-testid="ml-badge-{po_id}"]').inner_text()
    _shot(page, "03-link-went-stale")
    card = page.locator(f'[data-testid="mo-card-{po_id}"]')
    card.locator('[data-testid="mo-submit"]').click()
    page.wait_for_function("() => /請款單|採購單/.test(document.querySelector('#fin-material-orders').innerText) && /退回|無效|請重新申請|需先申請/.test(document.querySelector('#fin-material-orders').innerText)", timeout=15000)
    assert _status_of(po_id) in (None, "草稿")                                                      # 沒送成
    # 舊單 K（已核准、沒有採購單連結）不受影響：沒有送審前提示
    assert page.locator('[data-testid="mo-card-K"] [data-testid="mo-po-hint"]').is_hidden()
    assert not errors, errors


def _status_of(item_id):
    import db
    c = db.get_db()
    try:
        r = c.execute("SELECT status FROM case_material_approvals WHERE quote_no=? AND item_id=?", (NO, item_id)).fetchone()
        return r["status"] if r else None
    finally:
        c.close()
