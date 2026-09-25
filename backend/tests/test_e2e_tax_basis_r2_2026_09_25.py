# -*- coding: utf-8 -*-
"""R2 e2e：零稅率／免稅的依據（營業稅法 §7、§8；CUSTOMIZATION-SPEC §9.2）。

- 報價頁：選零稅率 ⇒ 出現依據下拉與說明；沒選依據就送審 ⇒ 擋下並說明；選了依據 ⇒ 送審成功、依據存進報價。
- 案件頁「申請開立發票」：免稅舊報價沒有依據 ⇒ 對話框要求補填；沒填 ⇒ 擋下；填了 ⇒ 開票申請快照帶依據。
"""
import json
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"


def _stored(no):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
    finally:
        conn.close()


@pytest.mark.e2e
def test_quote_form_requires_a_basis_before_submitting_zero_rate(live_server, make_user, new_page, login_as):
    from tests.test_case_extra_expenses_api_2026_09_11 import _set_empty_approval_flow
    _set_empty_approval_flow()
    u = make_user(username="r2e_q", role="superadmin")
    page = new_page()
    login_as(page, u)
    page.goto(live_server + "/pages/quotation-form.html")
    page.wait_for_function(f"() => window.Alpine && document.querySelector('[x-data]') && {ROOT}.q"
                           f" && {ROOT}.taxBasisOptions", timeout=20000)
    basis = page.locator("[data-tax-basis]")
    assert not basis.is_visible()
    page.locator("select[data-tax-type]").select_option("zero")
    basis.wait_for(state="visible", timeout=5000)
    codes = page.locator("select[data-tax-basis-code] option").evaluate_all("os => os.map(o => o.value)")
    assert codes[1:10] == ["7-%d" % i for i in range(1, 10)]
    page.evaluate(f"""() => {{ const d = {ROOT}; d.q.customerName = '零稅率客戶'; d.q.projectName = '外銷專案';
        d.q.items = [{{id: 1, type: 'item', description: '設備', qty: 1, cost: 0, unitPrice: 1000, amount: 1000, margin: 1}}];
        d.calcTotals() }}""")
    msgs = []
    page.on("dialog", lambda dl: (msgs.append(dl.message), dl.dismiss()))
    with page.expect_event("dialog", timeout=10000):
        page.evaluate(f"() => {ROOT}.submitQuote()")
    assert msgs and "零稅率依據" in msgs[0], msgs
    assert page.evaluate(f"() => {ROOT}.showSubmitModal") is False, "沒有依據不可以進到送審確認"
    err = page.locator("[data-tax-basis-error]")
    assert err.is_visible() and "零稅率依據" in err.inner_text()

    page.locator("select[data-tax-basis-code]").select_option("7-1")
    page.locator("input[data-tax-basis-note]").fill("出口報單 AB123")
    err.wait_for(state="hidden", timeout=5000)
    page.evaluate(f"() => {ROOT}.submitQuote()")
    page.wait_for_function(f"() => {ROOT}.showSubmitModal === true", timeout=5000)
    page.evaluate(f"() => {ROOT}.confirmSubmit()")
    page.wait_for_function(f"() => !{ROOT}.submitting && {ROOT}.q.quoteNo && !{ROOT}.isDirty", timeout=15000)
    no = page.evaluate(f"() => {ROOT}.q.quoteNo")
    stored = _stored(no)
    assert stored["taxBasis"] == {"code": "7-1", "note": "出口報單 AB123"}


def _seed_exempt_case(no):
    import db
    now = datetime.now().isoformat()
    data = {"quoteNo": no, "dealTag": "已成案", "taxRate": 0, "customerName": "免稅客", "projectName": "免稅案",
            "caseRecord": {"payment": {"items": []}},
            "items": [{"id": 1, "type": "item", "description": "設備", "qty": 1, "unitPrice": 20000, "amount": 20000}]}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
            "created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "免稅客", "免稅案", 20000, 20000, json.dumps(data, ensure_ascii=False),
             now, now, "已成案", "2026-09-01"))
        conn.commit()
    finally:
        conn.close()


def _vouchers(no):
    import db
    conn = db.get_db()
    try:
        return [json.loads(r[0]) for r in conn.execute(
            "SELECT snapshot_json FROM invoice_vouchers WHERE quote_no=?", (no,)).fetchall()]
    finally:
        conn.close()


@pytest.mark.e2e
def test_invoice_request_dialog_asks_for_the_missing_basis(live_server, make_user, new_page, login_as):
    no = "MQ-R2E2E"
    _seed_exempt_case(no)
    u = make_user(username="r2e_iv", role="superadmin")
    page = new_page()
    login_as(page, u)
    page.goto(f"{live_server}/pages/case-management.html?q={no}")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    btn = page.locator("button:has-text('申請開立發票')")
    btn.wait_for(state="visible", timeout=20000)
    page.evaluate("""() => { window.__toasts = []; const t = MotrixUI.toast;
        MotrixUI.toast = (m, o) => { window.__toasts.push(m); return t(m, o) };
        MotrixUI.confirm = async () => true }""")
    btn.click()
    box = page.locator("[data-iv-tax-basis]")
    box.wait_for(state="visible", timeout=15000)
    assert "報價單沒有記錄依據" in box.inner_text()
    page.wait_for_function(f"() => {ROOT}.ivTaxBasisOptions && !{ROOT}.ivRemainingLoading", timeout=10000)
    page.evaluate(f"() => {{ {ROOT}.ivAmountInput = 5000 }}")
    page.locator("button:has-text('送出建立')").click()
    page.wait_for_function("() => window.__toasts.length > 0", timeout=5000)
    assert "免稅依據" in page.evaluate("() => window.__toasts[0]")
    assert _vouchers(no) == [], "沒有依據不可以建立"

    box.locator("select[data-iv-tax-basis-code]").select_option("8")
    box.locator("input[data-iv-tax-basis-note]").fill("第 N 款（測試）")
    page.locator("button:has-text('送出建立')").click()
    page.wait_for_function(f"() => !{ROOT}.ivCreateModal && !{ROOT}.ivSubmitting", timeout=15000)
    [snap] = _vouchers(no)
    assert snap["taxBasis"] == {"code": "8", "note": "第 N 款（測試）"}
    assert snap["taxNote"].startswith("免稅依據：")
