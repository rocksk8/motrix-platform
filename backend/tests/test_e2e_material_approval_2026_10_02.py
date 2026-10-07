"""瀏覽器端對端（含截圖）：叫料審核（31-C S5）。

一條完整來回（真實頁面、真實後端）：財務分頁新增叫料 → 儲存（建審核單＝草稿）→ 送審 → 待審核時內容欄位反灰、可撤回 → 簽核人核准 →
重新載入顯示「已核准」＋到貨確認區 → 叫料管控頁：「已叫料」「已到料」一開始反灰（說明原因）→ 連結叫料單後可勾「已叫料」（自動存檔真的寫進資料庫）→
「已到料」仍反灰（還沒確認到貨）→ 回財務分頁確認到貨（日期＋確認人顯示）→ 叫料管控可勾「已到料」。
每個動作等**這一次動作的終點**（畫面文字／資料庫），不等「提示出現」。需要 playwright，沒裝的環境整檔 skip。
截圖：暫存夾（MOTRIX_SHOTS_DIR 或系統暫存的 w4-shots），事後複製到 D:\\開發測試檔\\shots\\t31-material\\。
"""
from tests._requires import requires_module  # noqa: E402
import json
import os
import tempfile
import time

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的端點或讀寫 M01 的資料")

NO = "MQ-MA-E2E"
PANEL = "#fin-material-orders"



@pytest.fixture(autouse=True)
def _po_rule_on(monkeypatch):
    """33-M1 畫面：本檔驗「強制採購單」之下的畫面流程，明確設成開（不依賴 material_approval.PO_REQUIRED 的出貨預設）。"""
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", True)


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w4-shots"), "t31-material")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _cr():
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]).get("caseRecord", {})
    finally:
        conn.close()


def _wait_db(page, pred, what, timeout=20):
    """等**資料庫**到達預期狀態。⚠️ 必須用 `page.wait_for_timeout`（Playwright 的等待）而不是 `time.sleep`：
    sync Playwright 只在呼叫它的 API 時才處理瀏覽器事件，而 conftest 的 `context.route(...)` 會讓**每個請求**先停下來等 Python 端放行——
    測試執行緒睡著時，頁面的自動存檔 PATCH 就卡在瀏覽器裡（伺服器完全沒收到），等到下一次 Playwright 呼叫才放出去
    （實測：約 40～50 秒後；整合樹 e2e 紅 1 題「已到料已存」＝這個）。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred(_cr()):
            return
        page.wait_for_timeout(400)
    raise AssertionError("資料庫沒有達到預期狀態：" + what + "；目前 " + json.dumps(_cr(), ensure_ascii=False)[:400])


def _approval_row():
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT status, doc_code, received_on, received_by FROM case_material_approvals WHERE quote_no=?", (NO,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _open_finance(page, base):
    page.goto(f"{base}/pages/case-management.html?q={NO}")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_selector(PANEL, timeout=20000)


def _status_text(page):
    return page.locator(f'{PANEL} [data-testid="mo-ap-status"]').first.inner_text()


@pytest.mark.e2e
def test_material_order_approval_round_trip_in_the_browser(live_server, make_user, e2e_browser):
    import db
    adm, ap = make_user(username="e2e_ma_adm", role="superadmin")
    boss, bp = make_user(username="e2e_ma_boss", role="sales")
    conn = db.get_db()
    try:
        cr = {"materials": [{"id": 1, "name": "交換器", "model": "", "qty": 2, "unit": "台", "ordered": False, "arrived": False, "devices": []}]}
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "叫料審核客", "叫料審核專", 100000, 95238, json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-01"))
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("unified_approval_flow", json.dumps({"tiers": [{"order": 0, "approvers": [{"username": boss, "displayName": "主管"}]}],
                                                            "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        conn.execute("INSERT INTO suppliers (name, code, created_at, updated_at) VALUES (?,?,?,?)", ("甲供應商", "S-001", "2026-01-01", "2026-01-01"))
        conn.commit()
    finally:
        conn.close()

    page = e2e_browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sess = inject_login(page, live_server, adm, ap)
    _open_finance(page, live_server)
    page.wait_for_function("() => { const t = document.querySelector('#fin-material-orders')?.innerText || ''; return t.includes('尚無材料申請項目') && !t.includes('載入中') }", timeout=20000)

    # 1 從已核准採購單帶入並儲存 ⇒ 建審核單（草稿）
    from tests._material_po import approved_po                                              # 33-M1：新申請只能從已核准的採購單明細帶入
    approved_po(page.context, live_server, {"Authorization": "Bearer " + sess["token"]}, NO, "交換器", 2, 1500, adm)
    page.click('[data-testid="ml-open-po"]')
    page.locator('[data-testid^="ml-p-"]').first.wait_for(state="visible", timeout=15000)
    page.locator('[data-testid^="ml-p-"] input').first.check()
    page.click('[data-testid="ml-import"]')
    page.wait_for_selector(f'{PANEL} input[placeholder="項目名稱（如：交換器）"]', timeout=10000)
    page.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid=mo-supplier] option').length >= 2", timeout=15000)
    page.select_option(f'{PANEL} [data-testid="mo-supplier"]', label="S-001 甲供應商")        # 31-C：新增叫料必選供應商
    assert _status_text(page) == "尚未送審"
    page.click(f'{PANEL} button:has-text("儲存材料申請")')
    for _ in range(150):                                                                   # 等**資料庫**真的建出審核單（畫面標籤存檔前後都是「尚未送審」，不能拿它當終點）
        if _approval_row():
            break
        page.wait_for_timeout(100)
    assert _approval_row() and _approval_row()["status"] == "草稿"
    page.wait_for_function("() => (document.querySelector('#fin-material-orders [data-testid=mo-ap-code]')?.innerText || '').startsWith('MO-')", timeout=15000)   # 畫面重新載入後才有單號
    row = _approval_row()
    assert row["status"] == "草稿" and row["doc_code"].startswith("MO-")
    code = row["doc_code"]
    assert page.locator(f'{PANEL} [data-testid="mo-ap-code"]').first.inner_text() == code
    item_id = _cr()["materialOrders"][0]["itemId"]
    _shot(page, "01-draft")

    # 2 送審 ⇒ 待審核：內容反灰、可撤回、不能再送審
    page.click(f'{PANEL} [data-testid="mo-submit"]')
    page.wait_for_function("() => document.querySelector('#fin-material-orders [data-testid=mo-ap-status]')?.innerText === '待審核'", timeout=15000)
    assert _approval_row()["status"] == "待審核"
    assert page.locator(f'{PANEL} input[placeholder="單價"]').first.is_disabled()
    assert page.locator(f'{PANEL} [data-testid="mo-submit"]').first.is_hidden() and page.locator(f'{PANEL} [data-testid="mo-withdraw"]').first.is_visible()
    assert "待簽：主管" in page.locator(f'{PANEL} [data-testid="mo-approval-{item_id}"]').inner_text()
    _shot(page, "02-pending")

    # 2b 材料申請（核准前）：不自動連結——旗標反灰、顯示「需先申請…」提示（原先在核准後才檢查；t45 自動連結上線後，核准後同名唯一相符會自動帶入）
    page.click('.cm-tab:has-text("執行管理")') if page.locator('.cm-tab:has-text("執行管理")').count() else None
    page.click('.cm-tab:has-text("材料申請")')
    page.wait_for_selector('[data-testid="mat-order-link"]', timeout=15000)
    assert page.locator('[data-testid="mat-order-link"]').first.input_value() == ""                 # 待審核：不自動連結
    assert page.locator('[data-testid="mat-ordered"]').first.is_disabled() and page.locator('[data-testid="mat-arrived"]').first.is_disabled()
    # 材料申請改字：沒有對應已核准申請時的提示（文案出自 MATERIAL-REQUEST-WORDING.md；閘門邏輯不變）
    assert "需先申請請購單，再申請採購單；採購單通過後，才能對應這筆材料申請。" in page.locator('[data-testid="mat-order-link"]').first.locator("xpath=ancestor::*[.//input[@data-testid='mat-ordered']][1]").inner_text()
    _shot(page, "03b-block-hint")
    other = page.evaluate("""() => { const d = Alpine.$data(document.querySelector('[data-testid=mat-order-link]'));
        d.moApprovals = Object.assign({}, d.moApprovals, { 'X-PENDING': { status: '待審核' } });
        return d.matTickHint({ orderItemId: 'X-PENDING' }, 'ordered'); }""")
    assert other == "這筆材料申請還沒核准。", other
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_selector(f'{PANEL} [data-testid="mo-ap-status"]', timeout=15000)

    # 3 簽核人核准（另一個身分走 API）→ 重新載入 ⇒ 已核准＋到貨確認區
    bctx = e2e_browser.new_context()                                                        # 另一個身分（簽核人）走 API；用瀏覽器自己的 request，不多引套件
    tok = bctx.request.post(live_server + "/api/auth/login", data={"username": boss, "password": bp}).json()["token"]
    r = bctx.request.post(f"{live_server}/api/quotations/{NO}/material-orders/{item_id}/approve", headers={"Authorization": "Bearer " + tok}, data={})
    assert r.status == 200 and r.json()["status"] == "已核准", r.text()
    _open_finance(page, live_server)
    page.wait_for_function("() => document.querySelector('#fin-material-orders [data-testid=mo-ap-status]')?.innerText === '已核准'", timeout=15000)
    assert page.locator(f'{PANEL} [data-testid="mo-recv"]').first.is_visible()
    _shot(page, "03-approved")

    # 4 材料申請：核准後重新載入 ⇒ 同名且恰好一筆已核准、有採購單的申請 ⇒ 自動連結（t45）；「已叫料」可勾、「已到料」仍反灰（尚未確認到貨）
    page.click('.cm-tab:has-text("執行管理")') if page.locator('.cm-tab:has-text("執行管理")').count() else None
    page.click('.cm-tab:has-text("材料申請")')
    page.wait_for_selector('[data-testid="mat-order-link"]', timeout=15000)
    page.wait_for_function("(id) => document.querySelector('[data-testid=mat-order-link]').value === id", arg=item_id, timeout=15000)   # 自動帶入
    assert not page.locator('[data-testid="mat-ordered"]').first.is_disabled()
    assert page.locator('[data-testid="mat-arrived"]').first.is_disabled()
    _wait_db(page, lambda c: c["materials"][0].get("orderItemId") == item_id and not c["materials"][0].get("ordered"), "自動連結已存（旗標沒被動）")
    # 手動取消連結 ⇒ 旗標又反灰（後端閘不變）；不會被自動連結又帶回來（只在開啟時比對一次）；再手動連結 ⇒ 可勾
    page.select_option('[data-testid="mat-order-link"]', "")
    page.wait_for_function("() => document.querySelector('[data-testid=mat-ordered]').disabled", timeout=10000)
    _wait_db(page, lambda c: not c["materials"][0].get("orderItemId"), "取消連結已存")
    page.wait_for_timeout(2500)                                                                  # 過了自動存檔週期，仍是未連結
    assert page.locator('[data-testid="mat-order-link"]').first.input_value() == ""
    page.wait_for_function(f"() => document.querySelector('[data-testid=mat-order-link]').querySelectorAll('option').length >= 2", timeout=15000)
    page.select_option('[data-testid="mat-order-link"]', item_id)
    page.wait_for_function("() => !document.querySelector('[data-testid=mat-ordered]').disabled", timeout=10000)
    assert page.locator('[data-testid="mat-arrived"]').first.is_disabled()
    page.check('[data-testid="mat-ordered"]')
    _wait_db(page, lambda c: c["materials"][0].get("ordered") is True and c["materials"][0].get("orderItemId") == item_id, "已申購＋連結已存")
    _shot(page, "04-ordered")

    # 5 回財務分頁確認到貨（日期＋確認人）⇒ 叫料管控可勾「已到料」
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_selector(f'{PANEL} [data-testid="mo-recv-date"]', timeout=15000)
    page.fill(f'{PANEL} [data-testid="mo-recv-date"]', "2031-03-05")
    page.click(f'{PANEL} [data-testid="mo-recv"]')
    page.wait_for_selector(f'{PANEL} [data-testid="mo-recv-done"]', timeout=15000)
    assert "2031-03-05" in page.locator(f'{PANEL} [data-testid="mo-recv-done"]').inner_text() and adm in page.locator(f'{PANEL} [data-testid="mo-recv-done"]').inner_text()
    row = _approval_row()
    assert (row["received_on"], row["received_by"]) == ("2031-03-05", adm)
    _shot(page, "05-received")
    page.click('.cm-tab:has-text("執行管理")') if page.locator('.cm-tab:has-text("執行管理")').count() else None
    page.click('.cm-tab:has-text("材料申請")')
    page.wait_for_function("() => !document.querySelector('[data-testid=mat-arrived]').disabled", timeout=10000)
    page.check('[data-testid="mat-arrived"]')
    _wait_db(page, lambda c: c["materials"][0].get("arrived") is True, "已到料已存")
    _shot(page, "06-arrived")
    assert not errors, errors
