"""瀏覽器端對端：預定付款日缺口（承攬商匯款／叫料匯款；docs/platform/plans/PAYDATE-GAP-DESIGN-T48.md G1／G2／G3）。

- 承攬商匯款「建立」視窗可填預定付款日（選填、與合約應付款日不同、不互相預填）→ 送到後端落地 → 派發卡片顯示 → 出納「應付」佇列改期／清除；
- 叫料匯款申請建立時帶預定付款日 → 申請列表顯示 → 核准後出納待付款清單改期。
觀測點打資料庫落地值與元件狀態，不打頁面寫死的文字。

（提醒信／行事曆／站內通知的 e2e 要等第 47 班 L1 `payable_due_core` 進 platform 才寫，見檔尾的標記題。）
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = [requires_module("case", "案件頁"), requires_module("arap", "出納（M05）")]

Q = "MQ-PGAP-001"
DATA = "Alpine.$data(document.querySelector('[x-data]'))"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _wait(page, pred, what, timeout=20):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return
        page.wait_for_timeout(300)
    raise AssertionError("資料庫沒有達到預期狀態：" + what)


def _seed_case():
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (Q, "已送出", "預付客", "預付專案", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", "[]"))


def _login_hdr(client, name, pw):
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _dispatch(client, h, label):
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "廠商" + label, "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": Q, "vendor_id": r.json()["id"], "status": "completed", "payable_date": "2031-08-01",
            "items_json": [{"description": "測試品項", "qty": 1, "unit": "式", "unitPrice": 10000, "amount": 10000}]}
    r = client.post("/api/contractor-dispatches", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _open_dispatch_tab(page, base):
    page.goto(f"{base}/pages/case-management.html?q={Q}")
    page.wait_for_selector('.cm-tab:has-text("承攬商")', timeout=20000)
    page.click('.cm-tab:has-text("承攬商")')


def _create_voucher_in_dialog(page, planned):
    page.locator('[data-testid="cv-create-btn"]').first.wait_for(timeout=20000)
    page.locator('[data-testid="cv-create-btn"]').first.click()
    page.locator('[data-testid="cv-planned-pay-date"]').wait_for(state="visible", timeout=10000)
    # 合約應付款日與預定付款日是兩個欄位，不互相預填
    assert page.evaluate(f"() => {DATA}.createVoucherPlannedDate") == ""
    if planned:
        page.fill('[data-testid="cv-planned-pay-date"]', planned)
    page.click('[data-testid="cv-create-confirm"]')


@pytest.mark.e2e
def test_contractor_voucher_dialog_sends_planned_date_card_shows_it_cashier_edits_and_clears(live_server, make_user, e2e_browser, client):
    requires_module("subcontract", "承攬商匯款在 M04")
    sa, sp = make_user(username="pg_sa", role="superadmin")
    _seed_case()
    h = _login_hdr(client, sa, sp)
    _dispatch(client, h, "PG1")
    page = e2e_browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, sa, sp)
    _open_dispatch_tab(page, live_server)
    _create_voucher_in_dialog(page, "2031-09-15")
    _wait(page, lambda: len(_q("SELECT voucher_no FROM contractor_payment_vouchers")) == 1, "匯款申請已建立")
    row = _q("SELECT voucher_no, planned_pay_date FROM contractor_payment_vouchers")[0]
    assert row["planned_pay_date"] == "2031-09-15", "G1：建立視窗填的預定付款日要落地"
    no = row["voucher_no"]
    # 合約應付款日不受影響（兩件事）
    assert _q("SELECT payable_date FROM contractor_dispatches")[0]["payable_date"] == "2031-08-01"

    # G2：派發卡片顯示預定付款日
    card = page.locator('[data-testid="cv-planned-%s"]' % no)
    card.wait_for(state="visible", timeout=15000)
    assert "2031-09-15" in card.inner_text()

    # 出納「應付」佇列：看得到同一個日期、可改期、可清除（核准後才進佇列）
    _x("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (no,))
    page.goto(f"{live_server}/pages/cashier.html")
    page.wait_for_function(f"() => {DATA}.cashierSub !== undefined", timeout=20000)
    page.evaluate(f"() => {{ {DATA}.cashierSub = 'payable' }}")
    inp = page.locator('[data-testid="cashier-payable-planned-input-%s"]' % no)
    inp.wait_for(state="visible", timeout=20000)
    assert inp.input_value() == "2031-09-15"
    inp.fill("2031-09-20")
    _wait(page, lambda: _q("SELECT planned_pay_date FROM contractor_payment_vouchers WHERE voucher_no=?", (no,))[0]["planned_pay_date"] == "2031-09-20", "出納改期落地")
    inp.fill("")
    _wait(page, lambda: _q("SELECT planned_pay_date FROM contractor_payment_vouchers WHERE voucher_no=?", (no,))[0]["planned_pay_date"] == "", "出納清除落地")
    assert not errors, errors


@pytest.mark.e2e
def test_contractor_voucher_planned_date_is_optional(live_server, make_user, e2e_browser, client):
    requires_module("subcontract", "承攬商匯款在 M04")
    sa, sp = make_user(username="pg_sa2", role="superadmin")
    _seed_case()
    h = _login_hdr(client, sa, sp)
    _dispatch(client, h, "PG2")
    page = e2e_browser.new_page()
    inject_login(page, live_server, sa, sp)
    _open_dispatch_tab(page, live_server)
    _create_voucher_in_dialog(page, "")
    _wait(page, lambda: len(_q("SELECT voucher_no FROM contractor_payment_vouchers")) == 1, "匯款申請已建立")
    assert _q("SELECT planned_pay_date FROM contractor_payment_vouchers")[0]["planned_pay_date"] == ""
    assert page.locator('span[data-testid^="cv-planned-"]:visible').count() == 0, "沒填 ⇒ 卡片不顯示預定付款日"


@pytest.mark.e2e
def test_material_payment_create_with_planned_date_shows_in_list_and_cashier_edits_it(live_server, make_user, e2e_browser):
    sa, sp = make_user(username="pg_sa3", role="superadmin")
    item = "mo-pg-1"
    order = {"itemId": item, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 5000, "totalPrice": 10000,
             "paidStatus": "pending", "paidAmount": 0, "paidDate": None, "notes": "", "supplierId": None}
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
       (Q + "-M", "已送出", "匯款客", "匯款專案", 100000, 95238, json.dumps({"dealTag": "已成案", "caseRecord": {"materialOrders": [order]}}, ensure_ascii=False),
        "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-01"))
    _x("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
       (Q + "-M", item, "MO-20260101-0099", "已核准", "2026-01-01", "2026-01-01"))
    _x("INSERT INTO suppliers (name, code, created_at, updated_at) VALUES (?,?,?,?)", ("甲供應商", "S-099", "2026-01-01", "2026-01-01"))
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
    panel = "#fin-material-orders"
    page = e2e_browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, sa, sp)
    page.goto(f"{live_server}/pages/case-management.html?q={Q}-M")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    page.wait_for_selector(f'{panel} [data-testid="mo-pay-quota"]', timeout=20000)
    page.click(f'{panel} [data-testid="mo-pay-new"]')
    page.wait_for_function("() => document.querySelectorAll('#fin-material-orders [data-testid=mo-pay-supplier] option').length >= 2", timeout=15000)
    page.fill(f'{panel} [data-testid="mo-pay-amount"]', "6000")
    page.select_option(f'{panel} [data-testid="mo-pay-supplier"]', label="S-099 甲供應商")
    page.fill(f'{panel} [data-testid="mo-pay-bankcode"]', "812")
    page.fill(f'{panel} [data-testid="mo-pay-acctname"]', "甲供應商有限公司")
    page.fill(f'{panel} [data-testid="mo-pay-acctno"]', "28881234567890")
    page.fill(f'{panel} [data-testid="mo-pay-planned"]', "2031-10-10")
    page.check(f'{panel} [data-testid="mo-pay-ack"]')
    page.click(f'{panel} [data-testid="mo-pay-create"]')
    _wait(page, lambda: len(_q("SELECT id FROM case_material_payments")) == 1, "叫料匯款申請已建立")
    pid = _q("SELECT id, planned_pay_date FROM case_material_payments")[0]
    assert pid["planned_pay_date"] == "2031-10-10"
    pid = pid["id"]
    shown = page.locator(f'{panel} [data-testid="mo-pay-planned-{pid}"]')
    shown.wait_for(state="visible", timeout=15000)
    assert "2031-10-10" in shown.inner_text(), "申請列表顯示預定付款日"
    page.click(f'{panel} [data-testid="mo-pay-submit"]')                       # 沒設簽核層 ⇒ 核准
    _wait(page, lambda: _q("SELECT status FROM case_material_payments WHERE id=?", (pid,))[0]["status"] == "已核准", "核准")

    # 出納待付款清單：看得到、可改期
    page.goto(f"{live_server}/pages/cashier.html")
    page.wait_for_function(f"() => {DATA}.cashierSub !== undefined", timeout=20000)
    page.evaluate(f"() => {{ {DATA}.cashierSub = 'payreq' }}")
    tid = "case_material-%s" % pid
    inp = page.locator('[data-testid="cashier-payreq-planned-input-case_material-%s"]' % pid)
    inp.wait_for(state="visible", timeout=20000)
    assert inp.input_value() == "2031-10-10", tid
    inp.fill("2031-10-18")
    _wait(page, lambda: _q("SELECT planned_pay_date FROM case_material_payments WHERE id=?", (pid,))[0]["planned_pay_date"] == "2031-10-18", "出納改期落地")
    assert not errors, errors


@pytest.mark.e2e
@pytest.mark.skip(reason="等第 47 班 L1（payable_due_core）進 platform 才寫：以假日期呼叫 run_reminders(today=…)，斷言逾期站內通知落地且內容不含金額／受款人／廠商名；"
                         "對照 train/t47-int 或 wip/t45-paydate-l1 的 subcontract/payable_due.py、case/material_payable_event.py")
def test_overdue_reminder_in_app_notice_content_after_l1_lands():
    raise AssertionError("placeholder：L1 落地後實作")
