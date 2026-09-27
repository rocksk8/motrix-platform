# -*- coding: utf-8 -*-
"""請款流程整條（CORE-SPEC「請款流程（下一版）」，2026-09-27 使用者裁示）：
我的工作 → 新增請款 → 挑案件 → 上傳附件 → 送審 → 核准 → 補發票（核准後只有發票可以補）→
出納「請款待付款」看到並登錄付款（IP-100 寫回付款日）→ 月支出（權責／現金兩種口徑；草稿不計）。

跨 M01（請款）、M05（出納）、M08（月支出）⇒ 三個模組都要在；斷言打在畫面與 DB，核准走簽核人的 API（簽核頁本身另有題）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = [requires_module("case", "請款＝M01 額外支出"), requires_module("arap", "出納待付款（M05）"),
              requires_module("analytics", "月支出（M08）")]

NO = "MQ-PRE-001"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
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


def _token(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _png(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return str(p)


def _other(client, h, year, basis):
    r = client.get("/api/reports/expenses-monthly?year=%s&basis=%s" % (year, basis), headers=h)
    assert r.status_code == 200, r.text
    return [(d["date"], d["amount"], d.get("pending"), d.get("provisional"))
            for d in r.json()["expenses"]["details"]["other"] if d["quoteNo"] == NO]


@pytest.mark.e2e
def test_payment_request_end_to_end(live_server, make_user, new_context, client, tmp_path):
    eng = make_user(username="pre_eng", role="sales")
    mgr = make_user(username="pre_mgr", role="admin")
    cash = make_user(username="pre_cash", role="sales", modules=["cashier"])
    boss = make_user(username="pre_boss", role="superadmin")
    eng_id = _q("SELECT id FROM users WHERE username=?", (eng[0],))[0]["id"]
    mgr_id = _q("SELECT id FROM users WHERE username=?", (mgr[0],))[0]["id"]
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "請款客戶", "機房擴充", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
        "2026-01-01T00:00:00", "已成案", "", json.dumps([eng_id])))
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"includeSubmitterManagerTier": False, "tiers": [
           {"order": 0, "approvers": [{"userId": mgr_id, "username": mgr[0], "displayName": "主管乙"}]}]}), "2026-01-01T00:00:00"))

    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, eng[0], eng[1])

    # ① 我的工作 → 新增請款（選單來自 M01 module.json，group mywork）
    page.goto(live_server + "/pages/approval-history.html")
    link = page.locator('#app-mainnav a[href*="payment-request.html"]')
    link.first.wait_for(state="attached", timeout=15000)
    assert "新增請款" in link.first.text_content()
    page.goto(live_server + "/pages/" + link.first.get_attribute("href").split("/")[-1])

    # ② 挑案件（搜尋）→ 填 → 附件 → 送審
    page.fill("#pr-case-q", "MQ-PRE")
    page.click('[data-case-pick="%s"]' % NO)
    page.wait_for_selector("#pr-form", state="visible")
    page.wait_for_function("() => document.querySelectorAll('#pr-category option').length > 1")
    page.select_option("#pr-category", "差旅")
    page.fill("#pr-date", "2031-07-03")
    page.fill("#pr-amount", "4500")
    page.fill("#pr-desc", "高鐵來回（機房擴充）")
    page.set_input_files("#pr-files", _png(tmp_path, "receipt.png"))
    page.click("#pr-submit")
    page.wait_for_selector('#pr-result[data-status="待審核"]', timeout=15000)
    row = _q("SELECT * FROM case_extra_expenses WHERE quote_no=? AND total_cost=4500", (NO,))[0]
    eid = row["id"]
    assert row["status"] == "待審核" and row["created_by"] == eng[0] and row["expense_date"] == "2031-07-03"
    assert [f.get("kind") for f in json.loads(row["files_json"])] == ["other"]

    # 另存一筆草稿：月支出不計（裁示 ③）
    page.wait_for_function("() => document.getElementById('pr-new').dataset.busy === '0'")
    page.fill("#pr-amount", "999")
    page.fill("#pr-desc", "還沒要送的")
    page.click("#pr-save-draft")
    page.wait_for_selector('#pr-result[data-status="草稿"]', timeout=15000)

    # ③ 核准（簽核人）
    r = client.post("/api/quotations/%s/extra-expenses/%d/approve" % (NO, eid), headers=_token(client, *mgr), json={})
    assert r.status_code == 200, r.text
    assert _q("SELECT status FROM case_extra_expenses WHERE id=?", (eid,))[0]["status"] == "已核准"

    # ④ 我的請款：核准後補發票（只有發票能補）
    page.click("#pr-tab-mine")
    page.wait_for_selector('[data-payreq-row="%d"][data-status="已核准"]' % eid, timeout=15000)
    page.set_input_files('[data-invoice-upload="%d"]' % eid, _png(tmp_path, "invoice.png"))
    page.fill('[data-invoice-no="%d"]' % eid, "AB12345678")
    page.click('[data-invoice-save="%d"]' % eid)
    page.wait_for_selector('[data-payreq-row="%d"] [data-invoice-count="1"]' % eid, timeout=15000)
    row = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert row["invoice_no"] == "AB12345678"
    assert [f.get("kind") for f in json.loads(row["files_json"])] == ["other", "invoice"]
    assert _q("SELECT COUNT(*) AS n FROM audit_log WHERE action='extra_expense.invoice_after_approval' AND target_id=?", (NO,))[0]["n"] == 1

    # ⑤ 出納：請款待付款看到 → 登錄付款 ⇒ 消失、寫回付款日
    cp = new_context().new_page()
    cp.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(cp, live_server, cash[0], cash[1])
    cp.goto(live_server + "/pages/cashier.html")
    cp.click('[data-testid="cashier-payreq-tab"]')
    tid = "case-%d" % eid
    cp.wait_for_selector('[data-testid="cashier-payreq-row-%s"]' % tid, timeout=15000)
    assert "AB12345678" in cp.locator('[data-testid="cashier-payreq-row-%s"]' % tid).inner_text()
    cp.fill('[data-testid="cashier-payreq-date-%s"]' % tid, "2031-07-25")
    cp.click('[data-testid="cashier-payreq-pay-%s"]' % tid)
    cp.wait_for_selector('[data-testid="cashier-payreq-row-%s"]' % tid, state="detached", timeout=15000)
    assert _q("SELECT paid_date FROM case_extra_expenses WHERE id=?", (eid,))[0]["paid_date"] == "2031-07-25"

    # 請款人看得到付款日
    page.click("#pr-tab-new")
    page.click("#pr-tab-mine")
    page.wait_for_selector('[data-payreq-row="%d"] [data-paid-date="2031-07-25"]' % eid, timeout=15000)

    # ⑥ 月支出：現金口徑用付款日、不是暫用；權責口徑沒有發票日 ⇒ 核准日；兩種口徑草稿都不計
    h = _token(client, *boss)
    assert _other(client, h, 2031, "cash") == [("2031-07-25", 4500, False, False)]
    approved = _q("SELECT approval_json FROM case_extra_expenses WHERE id=?", (eid,))[0]["approval_json"]
    from modules.case.recognition import _approved_at
    day = _approved_at(approved)
    assert day, approved
    assert _other(client, h, int(day[:4]), "accrual") == [(day, 4500, False, True)]
    assert not [a for y in (2031, int(day[:4])) for b in ("cash", "accrual") for _d, a, _p, _v in _other(client, h, y, b) if a == 999]
    assert not errors, errors
