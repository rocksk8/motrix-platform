# -*- coding: utf-8 -*-
"""W1（2026-09-30）出納匯款手續費整條（畫面＋DB）：
出納在「請款待付款」填付款日、實付 985（應付 1000）、勾手續費 15 → 登錄付款 ⇒ 單據送「差額待審核」、付款日照寫；
出納頁「差額審核」頁籤只有管理員看得到核可／退回鈕：先退回（回待付款、新欄位清空），再重新登錄後核可（留核可人）；
營運報表：手續費以付款日列其他支出、現金口徑金額用實付。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = [requires_module("case", "請款＝M01 額外支出"), requires_module("arap", "出納（M05）"),
              requires_module("analytics", "月支出（M08）")]

NO = "MQ-RFE-001"


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
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@pytest.mark.e2e
def test_cashier_remit_fee_diff_review_end_to_end(live_server, make_user, new_context, client):
    cash = make_user(username="rfe_cash", role="sales", modules=["cashier"])
    boss = make_user(username="rfe_boss", role="superadmin")
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "手續費客戶", "機房", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
        "2026-01-01T00:00:00", "已成案", "", "[]"))
    eid = _x("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date,"
             " files_json, created_by, created_by_name, payer_name, created_at, updated_at, status, paid_date)"
             " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (NO, "差旅", "高鐵", 1, "", 1000, 1000, "2031-08-01", "[]", "rfe_eng", "工程師", "", "2031-08-01", "2031-08-01",
              "已核准", ""))
    tid = "case-%d" % eid
    errors = []

    # ① 出納登錄：實付 985＋手續費 15
    cp = new_context().new_page()
    cp.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(cp, live_server, cash[0], cash[1])
    cp.goto(live_server + "/pages/cashier.html")
    cp.click('[data-testid="cashier-payreq-tab"]')
    cp.wait_for_selector('[data-testid="cashier-payreq-row-%s"]' % tid, timeout=15000)
    cp.fill('[data-testid="cashier-payreq-date-%s"]' % tid, "2031-08-05")
    cp.fill('[data-testid="cashier-payreq-actual-%s"]' % tid, "985")
    cp.check('[data-testid="cashier-payreq-hasfee-%s"]' % tid)
    cp.fill('[data-testid="cashier-payreq-fee-%s"]' % tid, "15")
    assert "差 -15" in cp.locator('[data-testid="cashier-payreq-row-%s"]' % tid).inner_text()      # 畫面即時警示
    cp.click('[data-testid="cashier-payreq-pay-%s"]' % tid)
    cp.wait_for_selector('[data-testid="cashier-payreq-row-%s"]' % tid, state="detached", timeout=15000)
    assert "已送管理員審核" in cp.locator('[data-testid="cashier-payreq-result"]').inner_text()
    row = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert (row["paid_date"], row["remit_actual"], row["remit_fee"], row["remit_review"]) == ("2031-08-05", 985, 15, "pending")

    # 出納看得到待審核，但沒有核可鈕
    cp.click('[data-testid="cashier-remit-tab"]')
    cp.wait_for_selector('[data-testid="cashier-remit-row-%s"]' % tid, timeout=15000)
    # 第42班：出納與財務合併為「財務」角色，財務角色本來就是差額審核的決定者（頁面可以有核可鈕）；
    # 「登錄付款的人不能自己核可」（稽核 M4）由後端規則守，下面第③段仍由 superadmin 核可。

    # ② 管理員：先退回（要原因）⇒ 回待付款、新欄位清空
    ap = new_context().new_page()
    ap.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(ap, live_server, boss[0], boss[1])
    ap.goto(live_server + "/pages/cashier.html")
    ap.click('[data-testid="cashier-remit-tab"]')
    ap.wait_for_selector('[data-testid="cashier-remit-row-%s"]' % tid, timeout=15000)
    ap.click('[data-testid="cashier-remit-reject-%s"]' % tid)                                    # 沒填原因 ⇒ 不送出
    assert "原因" in ap.locator('[data-testid="cashier-remit-result"]').inner_text()
    assert _q("SELECT remit_review FROM case_extra_expenses WHERE id=?", (eid,))[0]["remit_review"] == "pending"
    ap.fill('[data-testid="cashier-remit-note-%s"]' % tid, "金額不對，重匯")
    ap.click('[data-testid="cashier-remit-reject-%s"]' % tid)
    ap.wait_for_selector('[data-testid="cashier-remit-row-%s"]' % tid, state="detached", timeout=15000)
    row = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert (row["paid_date"], row["remit_actual"], row["remit_fee"], row["remit_review"]) == ("", None, 0, "")

    # ③ 重新登錄同樣差額 ⇒ 管理員核可（留核可人）
    # （稽核 M4：登錄付款的人不能自己核可 ⇒ 由出納重新登錄、管理員核可）
    cp.goto(live_server + "/pages/cashier.html")
    cp.click('[data-testid="cashier-payreq-tab"]')
    cp.wait_for_selector('[data-testid="cashier-payreq-row-%s"]' % tid, timeout=15000)
    cp.fill('[data-testid="cashier-payreq-date-%s"]' % tid, "2031-08-06")
    cp.fill('[data-testid="cashier-payreq-actual-%s"]' % tid, "985")
    cp.check('[data-testid="cashier-payreq-hasfee-%s"]' % tid)
    cp.fill('[data-testid="cashier-payreq-fee-%s"]' % tid, "15")
    cp.click('[data-testid="cashier-payreq-pay-%s"]' % tid)
    cp.wait_for_selector('[data-testid="cashier-payreq-row-%s"]' % tid, state="detached", timeout=15000)
    ap.goto(live_server + "/pages/cashier.html")
    ap.click('[data-testid="cashier-remit-tab"]')
    ap.wait_for_selector('[data-testid="cashier-remit-row-%s"]' % tid, timeout=15000)
    ap.click('[data-testid="cashier-remit-approve-%s"]' % tid)
    ap.wait_for_selector('[data-testid="cashier-remit-row-%s"]' % tid, state="detached", timeout=15000)
    row = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert (row["remit_review"], row["remit_review_by"]) == ("approved", boss[0]) and row["paid_date"] == "2031-08-06"

    # ④ 營運報表（現金口徑）：其他支出＝實付 985＋手續費 15（各一筆，付款日）
    r = client.post("/api/auth/login", json={"username": boss[0], "password": boss[1]})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    rep = client.get("/api/reports/expenses-monthly?year=2031&basis=cash", headers=h)
    assert rep.status_code == 200, rep.text
    other = [(d["date"], d["amount"], d.get("category")) for d in rep.json()["expenses"]["details"]["other"] if d["quoteNo"] == NO]
    assert ("2031-08-06", 985, "差旅") in other and ("2031-08-06", 15, "匯款手續費") in other, other
    assert not errors, errors
