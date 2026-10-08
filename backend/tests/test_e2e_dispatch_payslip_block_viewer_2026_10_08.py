# -*- coding: utf-8 -*-
"""派發頁「勞報單」區塊（第 46 班 P3）——非最高管理者看到什麼（第 47 班補的 e2e）。

最高管理者可新增／解除／點進勞報單頁；一般人員（案件管理＋承攬商權限）只看單號、狀態、受領人，**沒有金額，也沒有連結／解除／輸入欄**；
完全沒有相關模組的人整塊不顯示、也不送請求（不留紅字、不留 console 403）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _insert_payslip  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

NO = "MQ-DSLIP-001"
SLIP = "PS-203108-801"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
T0 = "2026-03-01T09:00:00"


def _seed():
    import db
    conn = db.get_db()
    try:
        vid = conn.execute("INSERT INTO vendor_contractors (name, address, active, created_at) VALUES (?,?,?,?)",
                           ("勞報區塊承攬", "台中市", 1, T0)).lastrowid
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                     " deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "客戶", "專案", 105000, 100000, json.dumps({"dealTag": "已成案"}), T0, T0, "已成案", "2026-03-01"))
        did = conn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, total_amount,"
                           " tax_rate, status, notes, created_by, created_at, updated_at, files_json, invoice_files_json)"
                           " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (NO, vid, "2026-03-08", "管線施工", "[]", "[]", 8000, 5, "進行中", "", "x", T0, T0, "[]", "[]")).lastrowid
        conn.commit()
    finally:
        conn.close()
    _insert_payslip(SLIP)
    return did


@pytest.fixture()
def world(client, make_user):
    did = _seed()
    sa = make_user(username="dslip_sa", role="superadmin")
    staff = make_user(username="dslip_staff", role="user", modules=["case_manage", "procurement", "contractor_list"], legacy_finance_flag=False)
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE quotations SET sales_person=? WHERE quote_no=?", (staff[0], NO))        # 案件列表只列「自己的案件」：把案件歸給一般人員
        c.commit()
    finally:
        c.close()
    r = client.post("/api/auth/login", json={"username": sa[0], "password": sa[1]})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    ok = client.post("/api/contractor-dispatches/%s/payslip-links" % did, headers=h, json={"slipNo": SLIP})
    assert ok.status_code == 201, ok.text
    return did, sa, staff


def _open_dispatch_tab(page, live_server, user, did):
    inject_login(page, live_server, user[0], user[1])
    page.goto("%s/pages/case-management.html" % live_server)
    page.wait_for_function("() => { const d = %s; return d && d.session && d.session.token && !d.loading && d.caseCounts }" % DATA_JS, timeout=30000)
    page.click(".cm-card[data-quote-no='%s']" % NO, timeout=30000)
    page.wait_for_function("() => %s.selected && %s.selected.quote_no === '%s'" % (DATA_JS, DATA_JS, NO), timeout=15000)
    page.evaluate("() => { %s.activeTab = 'dispatch' }" % DATA_JS)
    page.wait_for_selector("[data-testid=dispatch-slips-%s]" % did, state="attached", timeout=20000)


@pytest.mark.e2e
def test_staff_sees_slip_text_only_no_controls_no_money(live_server, world, new_context):
    did, _sa, staff = world
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    _open_dispatch_tab(page, live_server, staff, did)
    blk = page.locator("[data-testid=dispatch-slips-%s]" % did)
    page.wait_for_selector("[data-testid=dispatch-slip-text-%s]" % SLIP, state="visible", timeout=15000)
    assert page.locator("[data-testid=dispatch-slip-link-%s]" % SLIP).count() == 0, "非最高管理者：單號不是連結（沒有指向勞報單頁的 a）"
    assert not [h for h in blk.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href') || '')") if "payslips.html" in h]
    assert page.locator("[data-testid=dispatch-slip-unlink-%s]:visible" % SLIP).count() == 0
    assert page.locator("[data-testid=dispatch-slip-input-%s]:visible" % did).count() == 0
    txt = blk.inner_text()
    assert SLIP in txt and "測試承攬人" in txt
    assert "30000" not in txt and "30,000" not in txt and "NT$" not in txt, "不得出現金額"


@pytest.mark.e2e
def test_superadmin_gets_link_and_unlink_controls(live_server, world, new_context):
    did, sa, _staff = world
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    _open_dispatch_tab(page, live_server, sa, did)
    page.wait_for_selector("[data-testid=dispatch-slip-link-%s]" % SLIP, state="visible", timeout=15000)
    assert page.locator("[data-testid=dispatch-slip-unlink-%s]" % SLIP).is_visible()
    assert page.locator("[data-testid=dispatch-slip-input-%s]" % did).is_visible()


@pytest.mark.e2e
def test_viewer_without_any_related_module_gets_no_request_and_no_block(live_server, world, new_context):
    """前端判斷：沒有 procurement／case_manage／contractor_list／quotation 任一模組 ⇒ 不送 payslip-links 請求，整塊隱藏、無紅字。"""
    did, _sa, staff = world
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    _open_dispatch_tab(page, live_server, staff, did)
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "payslip-links" in r.url else None)
    page.evaluate("() => { const d = %s; d.session = { ...d.session, modules: [], role: 'user' }; d.dpSlips = {}; "
                  "d.dpSlipLoad({ id: %s }) }" % (DATA_JS, did))
    page.wait_for_function("() => { const s = %s.dpSlips[%s]; return s && s.hidden === true }" % (DATA_JS, did), timeout=10000)
    assert seen == [], "不應送出請求：%s" % seen
    assert not page.locator("[data-testid=dispatch-slips-%s]" % did).is_visible()
    assert "無法讀取勞報單關聯" not in page.inner_text("body")
