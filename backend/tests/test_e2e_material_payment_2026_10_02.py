"""瀏覽器端對端（含截圖）：叫料匯款申請（31-C 匯款切片）。

一條完整來回（真實頁面、真實後端）：已核准的叫料單（小計 10,000）→ 財務分頁「＋ 開匯款申請」（填金額、選供應商、填收款帳戶）→ 建立草稿（畫面只顯示帳號末四碼、
額度「已申請／剩餘」更新）→ 送審（沒設簽核層＝核准）→ 出納（另一個身分走 API）分兩次登錄付款（2,500、再 3,500）→ 重新載入：兩筆付款明細、叫料單的付款狀態是
唯讀的「部分已付 6,000」→ 反向：畫面上沒有任何可手填的已付欄位。
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

NO = "MQ-MP-E2E"
ITEM = "mo-e2e-1"
PANEL = "#fin-material-orders"
ACCT = "28881234567890"


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w4-shots"), "t31-material")
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


def _order_json():
    return json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])["caseRecord"]["materialOrders"][0]


def _wait(page, pred, what, timeout=20):
    """等資料庫狀態。用 `page.wait_for_timeout`（讓 sync Playwright 處理事件、放行 route 攔下的請求），不用 `time.sleep`（見 test_e2e_material_approval 的說明）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return
        page.wait_for_timeout(400)
    raise AssertionError("資料庫沒有達到預期狀態：" + what)


def _open_finance(page, base):
    page.goto(f"{base}/pages/case-management.html?q={NO}")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_selector(f'{PANEL} [data-testid="mo-pay-quota"]', timeout=20000)


@pytest.mark.e2e
def test_material_payment_round_trip_in_the_browser(live_server, make_user, e2e_browser):
    import db
    adm, ap = make_user(username="e2e_mp_adm", role="superadmin")
    cash, cp = make_user(username="e2e_mp_cash", role="sales", modules=["cashier"])
    order = {"itemId": ITEM, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 5000, "totalPrice": 10000,
             "paidStatus": "pending", "paidAmount": 0, "paidDate": None, "notes": "", "supplierId": None}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "匯款客", "匯款專案", 100000, 95238, json.dumps({"dealTag": "已成案", "caseRecord": {"materialOrders": [order]}}, ensure_ascii=False),
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-01"))
        conn.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                     (NO, ITEM, "MO-20260101-0001", "已核准", "2026-01-01", "2026-01-01"))
        conn.execute("INSERT INTO suppliers (name, code, created_at, updated_at) VALUES (?,?,?,?)", ("甲供應商", "S-001", "2026-01-01", "2026-01-01"))
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()

    page = e2e_browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, adm, ap)
    _open_finance(page, live_server)
    quota = page.locator(f'{PANEL} [data-testid="mo-pay-quota"]').first
    assert "10,000" in quota.inner_text()                                                   # 已申請 0／剩餘 10,000
    assert page.locator(f'{PANEL} input[placeholder="已付金額"]').count() == 0              # 沒有可手填的已付欄位
    _shot(page, "p1-before")

    # 1 開匯款申請 ⇒ 草稿；畫面只給帳號末四碼
    page.click(f'{PANEL} [data-testid="mo-pay-new"]')
    page.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid=mo-pay-supplier] option').length >= 2", timeout=15000)
    page.fill(f'{PANEL} [data-testid="mo-pay-amount"]', "6000")
    page.select_option(f'{PANEL} [data-testid="mo-pay-supplier"]', label="S-001 甲供應商")
    page.fill(f'{PANEL} [data-testid="mo-pay-bankcode"]', "812")
    page.fill(f'{PANEL} [data-testid="mo-pay-acctname"]', "甲供應商有限公司")
    page.fill(f'{PANEL} [data-testid="mo-pay-acctno"]', ACCT)
    page.click(f'{PANEL} [data-testid="mo-pay-create"]')
    page.wait_for_function("() => document.querySelector('#fin-material-orders [data-testid=mo-pay-status]')?.innerText === '草稿'", timeout=15000)
    rows = _q("SELECT id, status, amount_approved, doc_code FROM case_material_payments")
    assert len(rows) == 1 and rows[0]["status"] == "草稿" and rows[0]["amount_approved"] == 6000 and rows[0]["doc_code"].startswith("MP-")
    pid = rows[0]["id"]
    text = page.locator(f'{PANEL} [data-testid="mo-pay-row-{pid}"]').inner_text()
    assert "****7890" in text and ACCT not in page.locator(PANEL).inner_text()
    assert "4,000" in page.locator(f'{PANEL} [data-testid="mo-pay-quota"]').first.inner_text()    # 剩餘 4,000
    _shot(page, "p2-draft")

    # 2 送審（沒設簽核層 ⇒ 直接核准）
    page.click(f'{PANEL} [data-testid="mo-pay-submit"]')
    page.wait_for_function("() => document.querySelector('#fin-material-orders [data-testid=mo-pay-status]')?.innerText === '已核准'", timeout=15000)
    assert _q("SELECT status FROM case_material_payments WHERE id=?", (pid,))[0]["status"] == "已核准"
    _shot(page, "p3-approved")

    # 3 出納（另一個身分）分兩次登錄付款
    ctx = e2e_browser.new_context()
    tok = ctx.request.post(live_server + "/api/auth/login", data={"username": cash, "password": cp}).json()["token"]
    hdr = {"Authorization": "Bearer " + tok}
    r = ctx.request.post(f"{live_server}/api/cashier/pending-payables/case_material/{pid}/pay", headers=hdr, data={"paidDate": "2031-03-05", "actualAmount": 2500})
    assert r.status == 200 and r.json()["remaining"] == 3500, r.text()
    r = ctx.request.post(f"{live_server}/api/cashier/pending-payables/case_material/{pid}/pay", headers=hdr, data={"paidDate": "2031-03-09"})
    assert r.status == 200 and r.json()["settled"] is True, r.text()
    _wait(page, lambda: len(_q("SELECT id FROM case_material_payment_lines")) == 2, "兩筆付款明細")
    o = _order_json()
    assert (o["paidStatus"], o["paidAmount"], o["paidDate"]) == ("partial", 6000, "2031-03-09")      # 6,000 ＜ 小計 10,000

    # 4 重新載入：兩筆明細、唯讀付款狀態、額度
    _open_finance(page, live_server)
    row_text = page.locator(f'{PANEL} [data-testid="mo-pay-row-{pid}"]').inner_text()
    assert "2031-03-05" in row_text and "2,500" in row_text and "2031-03-09" in row_text and "3,500" in row_text
    ro = page.locator(f'{PANEL} [data-testid="mo-paid-readonly"]').first.inner_text()
    assert "部分已付" in ro and "6,000" in ro
    assert page.locator(f'{PANEL} input[placeholder="已付金額"]').count() == 0
    _shot(page, "p4-paid")
    assert not errors, errors
