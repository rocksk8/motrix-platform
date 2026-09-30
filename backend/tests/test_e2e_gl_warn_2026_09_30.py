# -*- coding: utf-8 -*-
"""MONEY-FLOWS §9 L3 的畫面：出納頁取消一筆**已入總帳**的收款 ⇒ 行內提示（非阻擋、可關閉、不用 alert）；
沒入帳的收款取消 ⇒ 沒有提示。斷言打在畫面（DOM）與資料庫；截圖存 D:/開發測試檔/shots/wip-w2-gl-warn/。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = [requires_module("case", "打 M01（案件）的資料"), requires_module("arap", "出納頁（M05）")]

# BK19 不准測試寫到 repo 與 tmp 之外：截圖先存 repo 內（logs 底下、不進 git），跑完由人搬到 shots 資料夾（D:/開發測試檔/shots/wip-w2-gl-warn/）
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "e2e-shots", "wip-w2-gl-warn")


def _seed(qno, posted):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (qno, "已送出", "客戶甲", "專案", 30000, 28571, json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": [
                      {"id": "it1", "type": "訂金款", "pct": 100, "amount": 30000, "received": True, "receivedAt": "2031-07-03",
                       "actualAmount": 30000, "feeAmount": 0, "invoiceNo": "AB12345678"}]}}}), "n", "n", "已成案"))
        if posted:
            c.execute("INSERT INTO gl_source_events (source_type, source_key, event_code, rev, event_date, status) VALUES (?,?,?,?,?,?)",
                      ("quotation_receipt", "%s::it1" % qno, "E03", 1, "2031-07-03", "posted"))
        c.commit()
    finally:
        c.close()


def _received(qno):
    import db
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qno,)).fetchone()[0])
        return d["caseRecord"]["payment"]["items"][0]["received"]
    finally:
        c.close()


def _open(new_context, live_server, user, qno):
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())                       # 「取消此款項的收款紀錄？」confirm
    inject_login(page, live_server, user[0], user[1])
    page.goto(live_server + "/pages/cashier.html")
    page.locator(".ctab", has_text="待收款").first.click()               # 預設是「待付款」；收款列在「待收款」
    page.locator(".period-type-btn", has_text="已收款").first.click()    # 預設篩選是「未收款」；這題要操作已收款的那一筆
    page.wait_for_selector("tr:has-text('%s')" % qno, timeout=20000)
    return page, errors


@pytest.mark.e2e
def test_cancelling_a_posted_receipt_shows_a_dismissible_inline_notice(live_server, new_context, make_user):
    user = make_user(username="gw_cash", role="superadmin", modules=[])
    _seed("MQ-GWE-001", posted=True)
    page, errors = _open(new_context, live_server, user, "MQ-GWE-001")
    row = page.locator("tr", has_text="MQ-GWE-001")
    row.locator("button.unreceive").click()
    notice = page.locator('[data-testid="gl-notice"]')
    notice.wait_for(state="visible", timeout=10000)
    assert "已入總帳" in notice.inner_text() and "沖轉草稿" in notice.inner_text()
    assert _received("MQ-GWE-001") is False                        # 寫入本身照常完成（提示不擋）
    os.makedirs(SHOTS, exist_ok=True)
    png = page.screenshot()                                        # 回傳 bytes（playwright 帶 path 會自己 makedirs，撞 BK19）
    with open(os.path.join(SHOTS, "cashier-gl-notice.png"), "wb") as f:
        f.write(png)
    page.locator('[data-testid="gl-notice-close"]').click()
    notice.wait_for(state="hidden", timeout=5000)
    assert not errors, errors


@pytest.mark.e2e
def test_cancelling_a_receipt_not_in_the_ledger_shows_no_notice(live_server, new_context, make_user):
    user = make_user(username="gw_cash2", role="superadmin", modules=[])
    _seed("MQ-GWE-002", posted=False)
    page, errors = _open(new_context, live_server, user, "MQ-GWE-002")
    page.locator("tr", has_text="MQ-GWE-002").locator("button.unreceive").click()
    page.wait_for_selector("tr:has-text('MQ-GWE-002')", state="detached", timeout=10000)   # 取消後這列不再屬於「已收款」篩選
    assert _received("MQ-GWE-002") is False
    assert page.locator('[data-testid="gl-notice"]').is_hidden()
    assert not errors, errors


# ── 案件管理・承攬商派工：改發票日／取消已匯款（已入帳）⇒ toast ─────────────────────────────

def _save_shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    png = page.screenshot()
    with open(os.path.join(SHOTS, name), "wb") as f:
        f.write(png)


def _dispatch_world(client, make_user, qno, vname):
    import db
    boss = make_user(username="gwd_boss_" + qno[-3:], role="superadmin")
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                  " deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (qno, "已送出", "派工客", "派工專案", 100000, 95238,
                   json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": []}, "materials": [], "stages": [{"label": "訂單確認"}]}},
                              ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-08-01"))
        c.commit()
    finally:
        c.close()
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": boss[0], "password": boss[1]}).json()["token"]}
    v = client.post("/api/vendor-contractors", headers=h, json={"name": vname, "data": {}})
    assert v.status_code == 201, v.text
    d = client.post("/api/contractor-dispatches", headers=h, json={
        "quote_no": qno, "vendor_id": v.json()["id"], "status": "completed", "scope": "既有派工",
        "items_json": [{"id": "i1", "description": "配線", "qty": 10, "unit": "米", "unitPrice": 100, "amount": 1000}]})
    assert d.status_code == 201, d.text
    return boss, h, d.json()["id"]


def _event_row(stype, key, code):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO gl_source_events (source_type, source_key, event_code, rev, event_date, status) VALUES (?,?,?,?,?,?)",
                  (stype, key, code, 1, "2031-07-03", "posted"))
        c.commit()
    finally:
        c.close()


@pytest.mark.e2e
def test_dispatch_invoice_date_change_on_posted_dispatch_shows_toast(live_server, new_context, make_user, client):
    qno = "MQ-GWE-101"
    boss, h, did = _dispatch_world(client, make_user, qno, "GW廠商甲")
    _event_row("contractor_dispatch", str(did), "E04")
    errors = []
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/case-management.html?q=%s&tab=dispatch" % qno)
    inp = page.locator('[data-testid="dispatch-invoice-date"]').first
    inp.wait_for(state="visible", timeout=20000)
    inp.fill("2031-08-05")
    toast = page.locator('[data-testid="ui-toast"]', has_text="已入總帳")
    toast.wait_for(state="visible", timeout=10000)
    assert "沖轉草稿" in toast.inner_text()
    import db
    c = db.get_db()
    try:
        assert c.execute("SELECT invoice_date FROM contractor_dispatches WHERE id=?", (did,)).fetchone()[0] == "2031-08-05"   # 寫入照常完成
    finally:
        c.close()
    _save_shot(page, "dispatch-invoice-date-toast.png")
    assert not errors, errors


@pytest.mark.e2e
def test_dispatch_invoice_date_change_on_not_posted_dispatch_shows_no_toast(live_server, new_context, make_user, client):
    qno = "MQ-GWE-102"
    boss, h, did = _dispatch_world(client, make_user, qno, "GW廠商乙")
    page = new_context().new_page()
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/case-management.html?q=%s&tab=dispatch" % qno)
    inp = page.locator('[data-testid="dispatch-invoice-date"]').first
    inp.wait_for(state="visible", timeout=20000)
    inp.fill("2031-08-06")
    import db
    page.wait_for_timeout(1500)
    c = db.get_db()
    try:
        assert c.execute("SELECT invoice_date FROM contractor_dispatches WHERE id=?", (did,)).fetchone()[0] == "2031-08-06"
    finally:
        c.close()
    assert page.locator('[data-testid="ui-toast"]', has_text="已入總帳").count() == 0


@pytest.mark.e2e
def test_unpay_posted_remit_voucher_shows_toast(live_server, new_context, make_user, client):
    from tests._ui_dialogs import answer_confirm
    qno = "MQ-GWE-103"
    boss, h, did = _dispatch_world(client, make_user, qno, "GW廠商丙")
    cv = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": did})
    assert cv.status_code == 201, cv.text
    vno = cv.json()["voucher_no"]
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE contractor_payment_vouchers SET status='已核准', is_paid=1, paid_at='2031-07-03', paid_by='t' WHERE voucher_no=?", (vno,))
        c.commit()
    finally:
        c.close()
    _event_row("contractor_voucher", vno, "E05")
    errors = []
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/case-management.html?q=%s&tab=dispatch" % qno)
    btn = page.locator("button:has-text('取消已匯款')").first
    btn.wait_for(state="visible", timeout=20000)
    btn.click()
    answer_confirm(page, ok=True, expect="取消")
    toast = page.locator('[data-testid="ui-toast"]', has_text="已入總帳")
    toast.wait_for(state="visible", timeout=10000)
    c = db.get_db()
    try:
        assert c.execute("SELECT is_paid FROM contractor_payment_vouchers WHERE voucher_no=?", (vno,)).fetchone()[0] == 0     # 取消照常完成
    finally:
        c.close()
    _save_shot(page, "remit-unpay-toast.png")
    assert not errors, errors
