# -*- coding: utf-8 -*-
"""31-C 稽核（c7）獨立探針：叫料審核／叫料匯款申請。只補作者測試（test_material_*_2026_10_02.py）沒打的縫；斷言是「應該怎樣」，
印出實測值供報告引用。重用作者的 world／helper 以免重造夾具（讀碼確認過語意）。"""
import json
import threading

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料審核／匯款申請")

from modules.case.tests.test_material_payment_api_2026_10_02 import (  # noqa: E402,F401
    ACCT, ITEM, NO, _approved, _create, _flow, _login, _order_json, _pending_items, _q, _x, world)


def _all_text_hits(needle):
    """整個資料庫所有文字欄位裡含 needle 的 (表, 欄, 筆數) 清單（稽核的個資全庫掃描）。"""
    import db
    conn = db.get_db()
    hits = []
    try:
        for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            for c in conn.execute('PRAGMA table_info("%s")' % t).fetchall():
                col = c[1]
                try:
                    n = conn.execute('SELECT COUNT(*) FROM "%s" WHERE CAST("%s" AS TEXT) LIKE ?' % (t, col), ("%" + needle + "%",)).fetchone()[0]
                except Exception:                                                  # noqa: BLE001 — 虛擬表等
                    continue
                if n:
                    hits.append((t, col, n))
    finally:
        conn.close()
    return hits


# ── H7 個資：收款帳號全庫掃描（完整流程跑完後，帳號全碼只准出現在哪幾個欄位？）──────────────────────────────

def test_h7_full_account_number_appears_only_where_designed(client, world):
    w = world
    pid = _approved(client, w, 6000)
    client.get("/api/cashier/pending-payables/case_material/%d/payee-bank" % pid, headers=w["cash"])
    client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-05", "actualAmount": 2500}, headers=w["cash"])
    client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-09", "actualAmount": 3500, "hasFee": True, "fee": 15}, headers=w["cash"])
    hits = _all_text_hits(ACCT)
    print("H7 account full-number hits:", hits)
    allowed = {("case_material_payments", "snapshot_json")}
    extra = [h for h in hits if (h[0], h[1]) not in allowed]
    assert not extra, "帳號全碼出現在設計以外的欄位：%r" % (extra,)
    assert not [h for h in _all_text_hits("28881234") if h[0] == "audit_log"], "稽核不得含帳號前段"


# ── H5 額度鎖：兩個同時建立的申請各 7,000（小計 10,000）不可雙雙成功 ────────────────────────────────────────

def test_h5_concurrent_creates_cannot_both_take_the_same_quota(client, world):
    w = world
    out = []

    def go():
        out.append(_create(client, w, 7000).status_code)
    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    n = _q("SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS s FROM case_material_payments WHERE status NOT IN ('作廢','已退回')")[0]
    print("H5 statuses=%s live=%s sum=%s" % (sorted(out), n["n"], n["s"]))
    assert n["s"] <= 10000, "同一張叫料單的有效申請合計超過小計（無 overCapReason）：%s" % n["s"]


# ── H5 退回後再送審是否超額（退回釋出額度，別人用掉後原申請再送審）──────────────────────────────────────────

def test_h5_resubmit_after_reject_cannot_exceed_the_quota(client, world):
    w = world
    _flow([{"order": 0, "approvers": [{"username": w["boss_name"], "displayName": "主管"}]}])
    a = _create(client, w, 7000).json()["payment"]
    assert client.post("/api/material-payments/%d/submit" % a["id"], headers=w["adm"]).status_code == 200
    assert client.post("/api/material-payments/%d/reject" % a["id"], json={"reason": "先退"}, headers=w["boss"]).status_code == 200      # 釋出 7,000
    b = _create(client, w, 7000)                                                                                                         # 別張用掉
    assert b.status_code == 200, b.text
    r = client.post("/api/material-payments/%d/submit" % a["id"], headers=w["adm"])                                                      # 原申請再送審
    live = _q("SELECT COALESCE(SUM(amount),0) AS s FROM case_material_payments WHERE status NOT IN ('作廢','已退回')")[0]["s"]
    print("H5b resubmit -> %s ; live sum=%s" % (r.status_code, live))
    assert live <= 10000, "退回的申請重送審後有效額度超過小計：%s" % live


# ── 出納端輸入：負數／超大／非數字／壞日期／壞手續費 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"paidDate": "2031-03-05", "actualAmount": -100}, {"paidDate": "2031-03-05", "actualAmount": 1e15},
    {"paidDate": "2031-03-05", "actualAmount": "abc"}, {"paidDate": "not-a-date", "actualAmount": 100},
    {"paidDate": "2031-03-05", "actualAmount": 100, "hasFee": True, "fee": -5}, {"paidDate": "2031-03-05", "actualAmount": 100, "hasFee": True, "fee": 1e12}])
def test_cashier_pay_rejects_bad_numbers_and_dates(client, world, body):
    w = world
    pid = _approved(client, w, 6000)
    r = client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json=body, headers=w["cash"])
    n = _q("SELECT COUNT(*) AS n FROM case_material_payment_lines")[0]["n"]
    print("pay %r -> %s lines=%s" % (body, r.status_code, n))
    assert r.status_code in (400, 409, 422) and n == 0


# ── 自審：superadmin 自己登錄的多付也不能自己核可 ───────────────────────────────────────────────────────────

def test_overpay_self_review_is_blocked_even_for_superadmin(client, world):
    w = world
    pid = _approved(client, w, 6000)
    r = client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-20", "actualAmount": 6500}, headers=w["sa"])
    assert r.status_code == 200, r.text
    items = [i for i in client.get("/api/cashier/remit-reviews", headers=w["sa"]).json()["items"] if i["source"] == "case_material"]
    assert items, "多付應進待審核"
    d = client.post("/api/cashier/remit-reviews/case_material/%s/decision" % items[0]["key"], json={"decision": "approve"}, headers=w["sa"])
    print("superadmin self-review -> %s %s" % (d.status_code, d.text[:80]))
    assert d.status_code == 403


# ── payee-bank（完整帳號）端點的角色矩陣 ───────────────────────────────────────────────────────────────────

def test_payee_bank_endpoint_role_matrix(client, world):
    w = world
    pid = _approved(client, w, 6000)
    res = {who: client.get("/api/cashier/pending-payables/case_material/%d/payee-bank" % pid, headers=w[who]).status_code
           for who in ("sa", "adm", "adm2", "cash", "boss", "eng", "out")}
    print("payee-bank matrix:", res)
    assert res["eng"] == 403 and res["out"] in (403, 404) and res["boss"] in (403, 404)


# ── H8 舊的「登記已付」關閉：叫料專屬端點／整包存檔直接帶 paid 欄位都不能寫 ─────────────────────────────────

def test_h8_no_path_still_writes_paid_fields_directly(client, world):
    w = world
    cr = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])["caseRecord"]
    rows = cr["materialOrders"]
    rows[0].update({"paidStatus": "paid", "paidAmount": 10000, "paidDate": "2031-03-05"})
    r1 = client.patch("/api/quotations/%s/material-orders" % NO, json={"materialOrders": rows}, headers=w["adm"])
    r2 = client.patch("/api/quotations/%s/case-record" % NO, json={"case_record": cr}, headers=w["adm"])
    now = _order_json()
    print("H8 dedicated=%s case-record=%s now=%s/%s" % (r1.status_code, r2.status_code, now.get("paidStatus"), now.get("paidAmount")))
    assert (now.get("paidStatus") or "pending") == "pending" and not float(now.get("paidAmount") or 0)


# ── H1 舊單帶「已付」歷史被實質編輯：回草稿＋已付>0 的單？ ─────────────────────────────────────────────────

def test_h1_legacy_order_with_paid_history_edited_goes_to_draft_keeping_the_paid_fields(client, world):
    w = world
    _x("DELETE FROM case_material_approvals")                                         # 變回舊單（沒有疊加列）
    cr = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])
    cr["caseRecord"]["materialOrders"][0].update({"paidStatus": "paid", "paidAmount": 10000, "paidDate": "2031-02-01"})
    _x("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(cr), NO))
    rows = cr["caseRecord"]["materialOrders"]
    rows[0].update({"unitPrice": 5100, "totalPrice": 10200})
    r = client.patch("/api/quotations/%s/material-orders" % NO, json={"materialOrders": rows}, headers=w["adm"])
    st = _q("SELECT status FROM case_material_approvals WHERE quote_no=? AND item_id=?", (NO, ITEM))
    o = _order_json()
    print("H1 -> %s ; approval=%s ; paid=%s/%s ; total=%s" % (r.status_code, st[0]["status"] if st else None, o.get("paidStatus"), o.get("paidAmount"), o.get("totalPrice")))
