# -*- coding: utf-8 -*-
"""33-M1 材料申請畫面（強制採購單）：
- 沒有「＋ 新增項目」與報價品項入口；導引文字指向「已核准的採購單明細」
- 送審前提示：新（非舊單）、沒採購單連結的材料申請顯示「需先申請請購單，再申請採購單…」；舊單、已有採購單連結者不顯示
- 送審被後端 po_required 擋下、狀態仍是草稿
- 已全額付款的列：數量、單價反灰並說明「已全額付款，金額不能修改；要調整請另開一筆材料申請」；未付清者可改
headless；終點等頁面狀態／資料庫。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

pytestmark = [pytest.mark.e2e, requires_module("case", "本檔讀寫 M01（案件）的資料與頁面")]

NO = "MQ-M1UI-1"
PANEL = "#fin-material-orders"
HINT = "需先申請請購單，再申請採購單；採購單通過後，才能對應這筆材料申請。"


@pytest.fixture(autouse=True)
def _po_rule_on(monkeypatch):
    """33-M1 畫面：本檔驗「強制採購單」之下的畫面流程，明確設成開（不依賴 material_approval.PO_REQUIRED 的出貨預設）。"""
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", True)


def _order(iid, name, **kw):
    d = {"itemId": iid, "itemName": name, "quantity": 2, "unit": "台", "unitPrice": 1000, "totalPrice": 2000, "paidStatus": "pending", "paidAmount": 0,
         "paidDate": "", "notes": "", "invoiceDate": "", "supplierId": 1}
    d.update(kw)
    return d


def _seed():
    import db
    c = db.get_db()
    try:
        orders = [_order("LEG", "舊單"),                                                                              # 沒有審核列＝舊單
                  _order("NEW", "新草稿（沒採購單）"),                                                                 # 規則上線後建立的草稿
                  _order("PAID", "已付清", paidStatus="paid", paidAmount=2000, paidDate="2026-10-02", poDocCode="PO-X", poLine=1),
                  _order("PART", "部分已付", paidStatus="partial", paidAmount=500, paidDate="2026-10-02", poDocCode="PO-X", poLine=2)]
        data = {"dealTag": "已成案", "caseRecord": {"materialOrders": orders}}
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 1, 1, json.dumps(data, ensure_ascii=False), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "已成案", "2026-10-02"))
        c.execute("INSERT INTO suppliers (id, name, code, created_at, updated_at) VALUES (1, '甲', 'S-1', '2026-10-02', '2026-10-02')")
        c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status, created_at) VALUES (?,?,'草稿','2026-10-04T00:00:00')", (NO, "NEW"))
        for iid in ("PAID", "PART"):
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status, created_at, doc_code) VALUES (?,?,'已核准','2026-10-02T00:00:00',?)", (NO, iid, "MO-" + iid))
        c.commit()
    finally:
        c.close()


@pytest.fixture()
def page(live_server, make_user, new_context):
    u, p = make_user(username="m1ui_sa", role="superadmin")
    _seed()
    pg = new_context(viewport={"width": 1400, "height": 1100}).new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pg, live_server, u, p)
    pg.goto("%s/pages/case-management.html?q=%s" % (live_server, NO))
    pg.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    pg.click('.cm-tab:has-text("財務")')
    pg.wait_for_selector('[data-testid="mo-card-NEW"]', timeout=20000)
    pg.click('[data-testid="ml-tab-all"]')
    yield pg
    assert not errors, errors


def card(pg, iid):
    return pg.locator('[data-testid="mo-card-%s"]' % iid)


def test_no_manual_add_no_quote_entry_and_guidance_points_to_approved_po(page):
    assert page.locator('[data-testid="ml-open-quote"]').count() == 0
    assert page.locator('%s button:has-text("＋ 新增項目")' % PANEL).count() == 0
    assert "已核准的採購單明細" in page.locator('[data-testid="mo-po-only-note"]').inner_text()
    assert page.locator('[data-testid="ml-open-po"]').is_visible()


def test_submit_hint_shows_only_on_new_requests_without_a_po_link(page):
    assert card(page, "NEW").locator('[data-testid="mo-po-hint"]').inner_text() == HINT
    assert card(page, "LEG").locator('[data-testid="mo-po-hint"]').is_hidden()                     # 舊單不受影響
    assert card(page, "PAID").locator('[data-testid="mo-po-hint"]').is_hidden()                    # 已核准、有採購單連結


def test_submit_without_po_is_refused_by_the_backend_and_stays_a_draft(page):
    card(page, "NEW").locator('[data-testid="mo-submit"]').click()
    page.wait_for_function("() => document.querySelector('#fin-material-orders').innerText.includes('需先申請請購單，再申請採購單')", timeout=15000)
    import db
    c = db.get_db()
    try:
        assert c.execute("SELECT status FROM case_material_approvals WHERE quote_no=? AND item_id='NEW'", (NO,)).fetchone()["status"] == "草稿"
    finally:
        c.close()


def test_paid_in_full_rows_gray_out_quantity_and_price_with_the_reason(page):
    paid, part, leg = card(page, "PAID"), card(page, "PART"), card(page, "LEG")
    assert paid.locator('input[placeholder="數量"]').is_disabled() and paid.locator('input[placeholder="單價"]').is_disabled()
    assert paid.locator('[data-testid="mo-paid-full-hint"]').inner_text() == "已全額付款，金額不能修改；要調整請另開一筆材料申請"
    assert paid.locator('input[placeholder="單價"]').get_attribute("title") == "已全額付款，金額不能修改；要調整請另開一筆材料申請"
    for c in (part, leg):                                                                          # 未付清、舊單：照舊可改
        assert c.locator('input[placeholder="數量"]').is_enabled() and c.locator('input[placeholder="單價"]').is_enabled()
        assert c.locator('[data-testid="mo-paid-full-hint"]').is_hidden()
