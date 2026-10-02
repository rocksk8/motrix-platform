"""32-S4e 瀏覽器端對端（一個檔、一個瀏覽器、一題連續流程）：材料申請連結。
從報價單品項帶入（已申請的先扣量、剩餘 0 的不列）→ 超出計畫量要填原因 → 儲存 ⇒ 標註「該材料申請未申請採購單」出現 →
從採購單明細帶入另一筆 ⇒ 沒有標註、顯示對應的採購單 → 採購單作廢後重新載入 ⇒ 標註回來 → 送審 ⇒ 簽核人的佇列卡片帶同一個標註（tags）。
終點以資料庫與頁面狀態為準；截圖存 logs/e2e-shots/wip-t32-s4a-2e。用字照 MATERIAL-REQUEST-WORDING.md（本檔不依賴既有 31-C 字串）。"""
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



@pytest.fixture(autouse=True)
def _po_rule_off(monkeypatch):
    """33-M1 後端強制採購單已上線；這個檔的畫面流程（手動新增列）等前端「從採購單帶入」改版時再改寫。規則本身的題在 test_material_po_required_2026_10_03.py。"""
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", False)

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

    # ── 1 從報價單品項帶入：K 已申請 4 ⇒ 交換器剩 6；線材已申請完 ⇒ 不列 ──
    page.click('[data-testid="ml-open-quote"]')
    page.locator('[data-testid="ml-q-a"]').wait_for(state="visible", timeout=15000)
    assert "剩餘 6" in page.locator('[data-testid="ml-q-a"]').inner_text()
    assert page.locator('[data-testid="ml-q-b"]').count() == 0
    _shot(page, "01-import-panel")
    page.locator('[data-testid="ml-q-a"] input').check()
    page.click('[data-testid="ml-import"]')
    page.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid^=ml-row-]').length === 3", timeout=10000)
    new_card = page.locator('[data-testid^="mo-card-"]').last
    assert new_card.locator('input[placeholder="數量"]').input_value() == "6"
    assert new_card.locator('[data-testid^="ml-badge-"]').inner_text() == NOPO                  # 沒連採購單 ⇒ 標註（未儲存也即時顯示）

    # ── 2 數量改成 8（超出剩餘 6）⇒ 超出原因欄出現；選供應商、填原因、儲存 ──
    new_card.locator('input[placeholder="數量"]').fill("8")
    new_card.locator('[data-testid^="ml-reason-"]').wait_for(state="visible", timeout=5000)
    new_card.locator('[data-testid^="ml-reason-"]').fill("客戶追加兩台")
    page.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid=mo-supplier] option').length >= 2", timeout=15000)
    new_card.locator('[data-testid="mo-supplier"]').select_option(label="S-001 甲供應商")
    _shot(page, "02-over-plan-reason")
    page.locator(f'{PANEL} button[\\@click="moSave()"]').click()
    _wait_db(page, lambda: len(_orders()) == 3, "三筆材料申請已存")
    saved = [o for k, o in _orders().items() if k not in ("K", "Z")][0]
    assert saved["quoteItemId"] == "a" and saved["overPlanReason"] == "客戶追加兩台" and "poDocCode" not in saved   # 連結鍵原樣存下；沒連採購單的不寫 poDocCode
    new_id = saved["itemId"]
    page.wait_for_function("(id) => { const b = document.querySelector('[data-testid=mo-card-' + id + '] [data-testid=mo-ap-status]'); return b && b.offsetParent !== null && b.innerText === '尚未送審' }", arg=new_id, timeout=15000)   # 預設分頁直接看到「尚未送審」
    page.wait_for_function("(id) => { const b = document.querySelector('[data-testid=ml-badge-' + id + ']'); return b && b.offsetParent !== null && b.innerText.includes('未申請採購單') }", arg=new_id, timeout=15000)
    assert "尚未送審" in page.locator('[data-testid="ml-tab-approved"]').inner_text()
    _shot(page, "03-saved-badge")

    # ── 3 採購單：用 API 開一張交換器採購單並送審（核准）⇒ 從採購單明細帶入 ──
    from modules.case.tests.test_purchase_item_lines_2026_10_02 import _body, _ln
    r = ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses", headers=H, data=_body("purchase_order", [_ln("a", 3, unitCost=1000, summary="交換器（採購單）")]))
    assert r.status == 201, r.text()
    eid, doc = r.json()["id"], r.json()["docCode"]
    assert ctx.request.post(f"{live_server}/api/quotations/{NO}/extra-expenses/{eid}/submit", headers=H).status == 200
    page.click('[data-testid="ml-open-po"]')
    row = page.locator(f'[data-testid="ml-p-{doc}-1"]')
    row.wait_for(state="visible", timeout=15000)
    row.locator("input").check()
    page.click('[data-testid="ml-import"]')
    page.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid^=ml-row-]').length === 4", timeout=10000)
    po_card = page.locator('[data-testid^="mo-card-"]').last
    assert po_card.locator('[data-testid^="ml-badge-"]').is_hidden()                                 # 連到採購單 ⇒ 沒有標註
    po_card.locator('[data-testid="mo-supplier"]').select_option(label="S-001 甲供應商")
    page.locator(f'{PANEL} button[\\@click="moSave()"]').click()
    _wait_db(page, lambda: any(o.get("poDocCode") == doc for o in _orders().values()), "採購單連結已存")
    po_id = [k for k, o in _orders().items() if o.get("poDocCode") == doc][0]
    page.wait_for_function("(id) => { const e = document.querySelector('[data-testid=ml-linked-' + id + ']'); return e && e.offsetParent !== null }", arg=po_id, timeout=15000)
    assert doc in page.locator(f'[data-testid="ml-linked-{po_id}"]').inner_text()
    assert page.locator(f'[data-testid="ml-badge-{po_id}"]').is_hidden()
    _shot(page, "04-linked-no-badge")
    # 同一明細不能被第二筆材料申請再帶入
    page.click('[data-testid="ml-open-po"]')
    page.wait_for_function("() => !document.querySelector('[data-testid=ml-panel]').innerText.includes('載入中')", timeout=10000)
    assert page.locator(f'[data-testid="ml-p-{doc}-1"]').count() == 0
    page.click('[data-testid="ml-open-po"]')

    # ── 4 採購單作廢 ⇒ 連結失效 ⇒ 重新載入後標註回來（錢不消失；後端 S4c 已驗） ──
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
    _shot(page, "05-link-went-stale")

    # ── 5 送審新建的那筆 ⇒ 簽核人的佇列卡片帶同一個標註 ──
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [{"order": 0, "approvers": [{"username": boss, "displayName": "主管"}]}]})
    page.click('[data-testid="ml-tab-approved"]')                                                    # 預設分頁（草稿＝尚未送審在這裡）；「全部」不跳轉
    card = page.locator(f'[data-testid="mo-card-{new_id}"]')
    card.locator('[data-testid="mo-submit"]').click()
    _wait_db(page, lambda: _status_of(new_id) == "待審核", "送審後待審核")
    page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data]')).mlTab === 'review'", timeout=10000)      # 狀態變了，頁籤跟著該列走（不讓剛送審的列憑空消失）
    assert card.is_visible()
    bpage = ctx.browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    inject_login(bpage, live_server, boss, bp)
    bpage.goto(f"{live_server}/pages/approval-queue.html")
    tag = bpage.locator('[data-testid="aq-tag"]').first
    tag.wait_for(state="visible", timeout=20000)
    assert tag.inner_text() == NOPO
    _shot(bpage, "06-queue-card-tag")
    assert not errors, errors


def _status_of(item_id):
    import db
    c = db.get_db()
    try:
        r = c.execute("SELECT status FROM case_material_approvals WHERE quote_no=? AND item_id=?", (NO, item_id)).fetchone()
        return r["status"] if r else None
    finally:
        c.close()
