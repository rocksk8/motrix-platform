# -*- coding: utf-8 -*-
"""需要應收應付（M05）的題：刪掉 modules/arap 時隨模組消失（PLAYBOOK §B-11）。

（2026-09-26 自 tests/test_e2e_tax_basis_r2_2026_09_25.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
R2 e2e：零稅率／免稅的依據（營業稅法 §7、§8；CUSTOMIZATION-SPEC §9.2）。

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

    box.locator("select[data-iv-tax-basis-code]").select_option("8-3")
    box.locator("input[data-iv-tax-basis-note]").fill("醫療勞務（測試）")
    page.locator("button:has-text('送出建立')").click()
    page.wait_for_function(f"() => !{ROOT}.ivCreateModal && !{ROOT}.ivSubmitting", timeout=15000)
    [snap] = _vouchers(no)
    assert snap["taxBasis"] == {"code": "8-3", "note": "醫療勞務（測試）"}
    assert snap["taxNote"].startswith("免稅依據：")
