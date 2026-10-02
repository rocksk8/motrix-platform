# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖）：出納「請款待付款」頁籤對費用單據（A2-3）。

每個新控制項都操作、驗動作終點狀態（資料庫＋畫面）：類型標籤、請購單不出現、採購單匯款日＋付款條件（沒填登錄鈕不可按、填了登錄成功）、
零用金付款方式必選、差旅預設轉帳、收款人銀行資料清單只有遮罩／按「查看收款人資料」才顯示完整並留稽核。
只能檢視的人（財務）不能開出納頁：其權限由 API 題 `test_non_cashier_cannot_pay_or_read_bank` 驗。
截圖：暫存夾（BK19），事後複製到 D:\\開發測試檔\\shots\\wip-w2-expense-a2\\。"""
import json
import os
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

SENT = "/api/quotations/-/extra-expenses"


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w2-shots"), "wip-w2-expense-a2")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _no_tiers():
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


def _setup(live_server, make_user, browser):
    u = {n: make_user(username=n, role=r, modules=m) for n, r, m in (
        ("e2p_form", "sales", ["expense_forms"]), ("e2p_cash", "engineer", ["cashier"]), ("e2p_fin", "engineer", ["finance"]))}
    req = browser.new_context().request
    tok = req.post(f"{live_server}/api/auth/login", data={"username": "e2p_form", "password": u["e2p_form"][1]}).json()["token"]
    hdr = {"Authorization": "Bearer " + tok}
    _no_tiers()
    ids = {}
    for kind, extra in (("purchase_req", {}), ("purchase_order", {"payeeType": "vendor", "payeeName": "力霸廠商"}),
                        ("petty_cash", {"payeeType": "employee", "payeeName": "王小明"}),
                        ("travel", {"payeeType": "employee", "payeeName": "李小華", "payeeBank": "玉山", "payeeAccount": "9876543210123"})):
        r = req.post(f"{live_server}{SENT}", headers=hdr, data={"kind": kind, "lines": [{"category": "其他", "summary": kind, "amount": 1200}],
                                                                 "data": {"applicant": "e2p_form"}, **extra})
        assert r.ok, r.text()
        ids[kind] = r.json()["id"]
        assert req.post(f"{live_server}{SENT}/{ids[kind]}/submit", headers=hdr).json()["status"] == "已核准"
    return u, ids


def _open(browser, live_server, cred):
    page = browser.new_context().new_page()
    inject_login(page, live_server, *cred)
    page.goto(live_server + "/pages/cashier.html")
    tab = page.locator('[data-testid="cashier-payreq-tab"]')
    tab.wait_for(state="visible", timeout=20000)
    tab.click()
    return page


def _row(page, eid):
    return page.locator('[data-testid="cashier-payreq-row-case-%d"]' % eid)


@pytest.mark.e2e
def test_cashier_pays_each_kind_with_its_required_fields(live_server, make_user, e2e_browser):
    u, ids = _setup(live_server, make_user, e2e_browser)
    page = _open(e2e_browser, live_server, u["e2p_cash"])
    po, pc, tv, rq = ids["purchase_order"], ids["petty_cash"], ids["travel"], ids["purchase_req"]
    _row(page, po).wait_for(timeout=15000)
    assert _row(page, rq).count() == 0                                                     # 請購單不進出納
    assert "採購單" in page.inner_text('[data-testid="cashier-payreq-kind-case-%d"]' % po)
    _shot(page, "01-queue")
    # 採購單：沒填匯款日／付款條件 ⇒ 錯誤提示、登錄鈕不可按
    page.fill('[data-testid="cashier-payreq-date-case-%d"]' % po, "2026-10-01")
    pay = page.locator('[data-testid="cashier-payreq-pay-case-%d"]' % po)
    assert pay.is_disabled() and "匯款日" in page.inner_text('[data-testid="cashier-payreq-extra-err-case-%d"]' % po)
    page.fill('[data-testid="cashier-payreq-remitdate-case-%d"]' % po, "2026-10-05")
    assert pay.is_disabled()                                                               # 只填匯款日還不夠
    page.fill('[data-testid="cashier-payreq-terms-case-%d"]' % po, "月結 30 天")
    page.wait_for_function("(id) => !document.querySelector('[data-testid=\"cashier-payreq-pay-case-' + id + '\"]').disabled", arg=po, timeout=5000)
    _shot(page, "02-po-filled")
    pay.click()
    page.wait_for_function("(id) => !document.querySelector('[data-testid=\"cashier-payreq-row-case-' + id + '\"]')", arg=po, timeout=15000)
    r = _q("SELECT paid_date, pay_terms, remit_date, pay_method, paid_by FROM case_extra_expenses WHERE id=?", (po,))[0]
    assert (r["paid_date"], r["pay_terms"], r["remit_date"], r["pay_method"], r["paid_by"]) == ("2026-10-01", "月結 30 天", "2026-10-05", "transfer", "e2p_cash")
    # 零用金：付款方式必選
    page.fill('[data-testid="cashier-payreq-date-case-%d"]' % pc, "2026-10-01")
    pay = page.locator('[data-testid="cashier-payreq-pay-case-%d"]' % pc)
    assert pay.is_disabled() and "付款方式" in page.inner_text('[data-testid="cashier-payreq-extra-err-case-%d"]' % pc)
    page.select_option('[data-testid="cashier-payreq-method-case-%d"]' % pc, "petty_cash")
    page.wait_for_function("(id) => !document.querySelector('[data-testid=\"cashier-payreq-pay-case-' + id + '\"]').disabled", arg=pc, timeout=5000)
    _shot(page, "03-petty-cash-method")
    pay.click()
    page.wait_for_function("(id) => !document.querySelector('[data-testid=\"cashier-payreq-row-case-' + id + '\"]')", arg=pc, timeout=15000)
    assert _q("SELECT pay_method FROM case_extra_expenses WHERE id=?", (pc,))[0]["pay_method"] == "petty_cash"
    # 差旅：清單只有遮罩；按「查看收款人資料」才顯示完整並留稽核；不選付款方式＝預設轉帳
    assert "****0123" in page.inner_text('[data-testid="cashier-payreq-bank-masked-case-%d"]' % tv)
    assert "9876543210123" not in page.inner_text('[data-testid="cashier-payreq-row-case-%d"]' % tv)
    page.locator('[data-testid="cashier-payreq-bank-view-case-%d"]' % tv).click()
    page.locator('[data-testid="cashier-payreq-bank-full-case-%d"]' % tv).wait_for(timeout=10000)
    assert "9876543210123" in page.inner_text('[data-testid="cashier-payreq-bank-full-case-%d"]' % tv)
    assert _q("SELECT COUNT(*) AS n FROM audit_log WHERE action='cashier.payee_bank_view'")[0]["n"] == 1
    assert not any("9876543210123" in (x["detail"] or "") for x in _q("SELECT detail FROM audit_log WHERE action='cashier.payee_bank_view'"))
    _shot(page, "04-bank-full-on-demand")
    page.fill('[data-testid="cashier-payreq-date-case-%d"]' % tv, "2026-10-01")
    page.locator('[data-testid="cashier-payreq-pay-case-%d"]' % tv).click()
    page.wait_for_function("(id) => !document.querySelector('[data-testid=\"cashier-payreq-row-case-' + id + '\"]')", arg=tv, timeout=15000)
    assert _q("SELECT pay_method, paid_by FROM case_extra_expenses WHERE id=?", (tv,))[0] == {"pay_method": "transfer", "paid_by": "e2p_cash"}
    _shot(page, "05-all-paid")
