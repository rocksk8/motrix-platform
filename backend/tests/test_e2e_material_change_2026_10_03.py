"""瀏覽器端對端（含截圖）：材料申請變更申請（33-M2c；面板 case-management-mchange.js）。

一條完整來回（真實頁面、真實後端、真實案件側提案 `material_coverage.change_proposal`）：已核准的材料申請（連採購單 PO1×3）→ 又核准一張採購單 PO2×2 →
財務分頁出現「材料申請變更」面板 → 選材料申請、預覽（數量 3 → 5、小計、涵蓋採購單行；原因必填）→ 建立（草稿）→ 送審（待審核；**原材料申請內容照常有效**）→
簽核人核准（走 API）→ 重新載入 ⇒ 材料申請切換成數量 5、變更列「已核准」、面板不再有可發起的候選。再走一次退回：新採購單 PO3×1 → 提變更 → 送審 → 簽核人退回 ⇒
「已退回」＋退回原因、材料申請不變 → 修改後送審 → 撤回 ⇒「已撤回」。每個動作等**這一次動作的終點**（畫面文字／資料庫），不等提示。
等待一律用 `page.wait_for_timeout`（不用 `time.sleep`）。需要 playwright，沒裝的環境整檔 skip。截圖：暫存夾（MOTRIX_SHOTS_DIR 或系統暫存的 w4-shots）。
"""
from tests._requires import requires_module  # noqa: E402
import json
import os
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的端點或讀寫 M01 的資料")

NO = "MQ-MC-E2E"
PANEL = "#fin-material-changes"


@pytest.fixture(autouse=True)
def _po_rule_on(monkeypatch):
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", True)
    from modules.case import material_change as _MC
    monkeypatch.setattr(_MC, "SHIPPED_PROVIDER", lambda conn, q, i: 0.0)       # 沒有出貨單：出貨連動（c7）的真提供者進樹後改測真實那條（見 test_material_change_api 的真提供者題）


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w4-shots"), "t34-material-change")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _order():
    d = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])
    return d["caseRecord"]["materialOrders"][0]


def _change(doc_code=None):
    rows = _q("SELECT * FROM case_material_changes WHERE quote_no=? ORDER BY id", (NO,))
    return rows if doc_code is None else next(r for r in rows if r["doc_code"] == doc_code)


def _wait(page, pred, what, timeout=20):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return
        page.wait_for_timeout(300)
    raise AssertionError("沒有達到預期：" + what)


def _open_finance(page, base):
    page.goto(f"{base}/pages/case-management.html?q={NO}")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_selector("#fin-material-orders", timeout=20000)


def _status(page, doc):
    return page.locator(f'[data-testid="mc-status-{doc}"]').inner_text()


@pytest.mark.e2e
def test_material_change_request_round_trip_in_the_browser(live_server, make_user, e2e_browser):
    import db
    from modules.case import material_approval as MA
    from tests._material_po import approved_po
    adm, ap = make_user(username="e2e_mc_adm", role="superadmin")
    boss, bp = make_user(username="e2e_mc_boss", role="sales")
    conn = db.get_db()
    try:
        data = {"dealTag": "已成案", "items": [{"id": "a", "description": "交換器", "qty": 10, "unit": "台", "cost": 1000}], "caseRecord": {"materials": []}}
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "變更申請客", "變更申請專", 100000, 95238, json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-01"))
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("unified_approval_flow", json.dumps({"tiers": [{"order": 0, "approvers": [{"username": boss, "displayName": "主管"}]}],
                                                            "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()

    page = e2e_browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sess = inject_login(page, live_server, adm, ap)
    hdr = {"Authorization": "Bearer " + sess["token"]}
    _eid, po1 = approved_po(page.context, live_server, hdr, NO, "交換器", 3, 1000, adm, item_id="a")
    order = {"itemId": "m1", "itemName": "交換器", "quantity": 3, "unit": "台", "unitPrice": 1000, "totalPrice": 3000, "quoteItemId": "a", "poDocCode": po1, "poLine": 1,
             "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "supplierId": None}
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["caseRecord"]["materialOrders"] = [order]
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
        snap = {"snapshot": {"poSnapshot": [{"poDocCode": po1, "line": 1, "qty": 3.0, "unit": "台", "amount": 3000.0}]}, "history": []}
        conn.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, approval_json, content_hash, version, created_at)"
                     " VALUES (?,?,?,?,?,?,?,?)", (NO, "m1", "MO-20261004-0001", "已核准", json.dumps(snap), MA.content_hash(order), 1, MA.PO_REQUIRED_FROM + "T09:00:00"))
        conn.commit()
    finally:
        conn.close()
    _eid2, po2 = approved_po(page.context, live_server, hdr, NO, "交換器", 2, 1000, adm, item_id="a")        # 又一張已核准的採購單：多了可納入的行

    _open_finance(page, live_server)
    page.wait_for_selector(f"{PANEL} [data-testid=mc-form]", state="visible", timeout=20000)
    # 1 選材料申請 → 預覽：數量 3 → 5、涵蓋行多一張採購單；沒有原因時不能建立
    page.select_option(f"{PANEL} [data-testid=mc-item]", "m1")
    page.click(f"{PANEL} [data-testid=mc-preview-btn]")
    page.wait_for_selector(f"{PANEL} [data-testid=mc-diff-quantity]", timeout=15000)
    assert page.locator(f"{PANEL} [data-testid=mc-diff-quantity]").inner_text() == "數量：3 → 5"
    assert po2 in page.locator(f"{PANEL} [data-testid=mc-diff-poSnapshot]").inner_text()
    assert page.locator(f"{PANEL} [data-testid=mc-save]").is_disabled()                              # 原因必填
    page.fill(f"{PANEL} [data-testid=mc-reason]", "追加 2 台")
    _shot(page, "01-preview")
    page.click(f"{PANEL} [data-testid=mc-save]")
    _wait(page, lambda: len(_change()) == 1, "資料庫建出變更申請")
    ch = _change()[0]
    doc = ch["doc_code"]
    assert ch["status"] == "草稿" and ch["reason"] == "追加 2 台" and _order()["quantity"] == 3                # 草稿：原材料申請不動
    page.wait_for_selector(f'[data-testid="mc-row-{doc}"]', timeout=15000)
    assert _status(page, doc) == "草稿"
    assert page.locator(f'[data-testid="mc-submit-{doc}"]').is_visible() and page.locator(f'[data-testid="mc-withdraw-{doc}"]').is_visible()
    _shot(page, "02-draft")

    # 2 送審 ⇒ 待審核；原內容照常有效、不能再修改／送審、可撤回
    page.click(f'[data-testid="mc-submit-{doc}"]')
    _wait(page, lambda: _change(doc)["status"] == "待審核", "變更申請待審核")
    page.wait_for_function(f"() => document.querySelector('[data-testid=\"mc-status-{doc}\"]')?.innerText === '待審核'", timeout=15000)
    assert _order()["quantity"] == 3 and MA.status_of(db.get_db(), NO, "m1") == "已核准"
    assert page.locator(f'[data-testid="mc-submit-{doc}"]').is_hidden() and page.locator(f'[data-testid="mc-revise-{doc}"]').is_hidden()
    assert "主管" in page.locator(f'[data-testid="mc-row-{doc}"]').inner_text()
    _shot(page, "03-pending")

    # 3 簽核人核准（另一個身分走 API）→ 重新載入 ⇒ 材料申請切換成數量 5、變更列已核准
    bctx = e2e_browser.new_context()
    tok = bctx.request.post(live_server + "/api/auth/login", data={"username": boss, "password": bp}).json()["token"]
    r = bctx.request.post(f"{live_server}/api/quotations/{NO}/material-changes/{ch['id']}/approve", headers={"Authorization": "Bearer " + tok}, data={})
    assert r.status == 200 and r.json()["applied"], r.text()
    assert _order()["quantity"] == 5 and _order()["totalPrice"] == 5000 and _change(doc)["status"] == "已核准"
    _open_finance(page, live_server)
    page.wait_for_selector(f'[data-testid="mc-status-{doc}"]', timeout=15000)
    assert _status(page, doc) == "已核准"
    assert page.locator(f'[data-testid="mc-row-diff-{doc}-quantity"]').inner_text() == "數量：3 → 5"
    page.wait_for_function("() => (document.querySelector('#fin-material-orders')?.innerText || '').includes('5')", timeout=10000)
    _shot(page, "04-approved")

    # 4 退回路徑：新採購單 PO3×1 → 提變更 → 送審 → 簽核人退回 ⇒ 已退回＋原因、材料申請不變 → 修改 → 送審 → 撤回
    _eid3, po3 = approved_po(page.context, live_server, hdr, NO, "交換器", 1, 1000, adm, item_id="a")
    _open_finance(page, live_server)
    page.wait_for_selector(f"{PANEL} [data-testid=mc-form]", state="visible", timeout=20000)
    page.select_option(f"{PANEL} [data-testid=mc-item]", "m1")
    page.click(f"{PANEL} [data-testid=mc-preview-btn]")
    page.wait_for_selector(f"{PANEL} [data-testid=mc-diff-quantity]", timeout=15000)
    assert page.locator(f"{PANEL} [data-testid=mc-diff-quantity]").inner_text() == "數量：5 → 6"
    page.fill(f"{PANEL} [data-testid=mc-reason]", "再追加 1 台")
    page.click(f"{PANEL} [data-testid=mc-save]")
    _wait(page, lambda: len(_change()) == 2, "第二張變更申請")
    doc2 = _change()[1]["doc_code"]
    page.wait_for_selector(f'[data-testid="mc-submit-{doc2}"]', timeout=15000)
    page.click(f'[data-testid="mc-submit-{doc2}"]')
    _wait(page, lambda: _change(doc2)["status"] == "待審核", "第二張待審核")
    ch2 = _change(doc2)
    r = bctx.request.post(f"{live_server}/api/quotations/{NO}/material-changes/{ch2['id']}/reject", headers={"Authorization": "Bearer " + tok}, data={"reason": "不需要再追加"})
    assert r.status == 200 and r.json()["status"] == "已退回", r.text()
    assert _order()["quantity"] == 5                                                                        # 退回：原材料申請不動
    _open_finance(page, live_server)
    page.wait_for_selector(f'[data-testid="mc-status-{doc2}"]', timeout=15000)
    assert _status(page, doc2) == "已退回" and "不需要再追加" in page.locator(f'[data-testid="mc-row-{doc2}"]').inner_text()
    _shot(page, "05-returned")
    page.click(f'[data-testid="mc-revise-{doc2}"]')                                                         # 修改：表單帶入、預覽自動重算
    page.wait_for_selector(f"{PANEL} [data-testid=mc-diff-quantity]", timeout=15000)
    page.fill(f"{PANEL} [data-testid=mc-reason]", "再追加 1 台（補充說明）")
    page.click(f"{PANEL} [data-testid=mc-save]")
    _wait(page, lambda: _change(doc2)["reason"] == "再追加 1 台（補充說明）" and _change(doc2)["status"] == "草稿", "修改後回草稿")
    page.wait_for_function(f"() => document.querySelector('[data-testid=\"mc-status-{doc2}\"]')?.innerText === '草稿'", timeout=15000)
    page.click(f'[data-testid="mc-submit-{doc2}"]')
    _wait(page, lambda: _change(doc2)["status"] == "待審核", "重送審")
    page.wait_for_selector(f'[data-testid="mc-withdraw-{doc2}"]', state="visible", timeout=15000)
    page.click(f'[data-testid="mc-withdraw-{doc2}"]')
    _wait(page, lambda: _change(doc2)["status"] == "已撤回", "撤回")
    page.wait_for_function(f"() => document.querySelector('[data-testid=\"mc-status-{doc2}\"]')?.innerText === '已撤回'", timeout=15000)
    assert _order()["quantity"] == 5
    _shot(page, "06-withdrawn")
    assert not errors, errors
