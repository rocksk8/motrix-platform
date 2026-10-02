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
    n = _q("SELECT COUNT(*) AS n, COALESCE(SUM(amount_approved),0) AS s FROM case_material_payments WHERE status NOT IN ('作廢','已退回')")[0]
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
    live = _q("SELECT COALESCE(SUM(amount_approved),0) AS s FROM case_material_payments WHERE status NOT IN ('作廢','已退回')")[0]["s"]
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



def test_huge_payment_and_fee_what_gets_recorded(client, world):
    """出納登錄 1e15 實付／1e12 手續費：被接受（200）——看它進了哪裡、有沒有走多付審核、手續費會不會直接進報表支出。"""
    w = world
    pid = _approved(client, w, 6000)
    r = client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-05", "actualAmount": 1e15}, headers=w["cash"])
    lines = _q("SELECT amount, fee, remit_review FROM case_material_payment_lines")
    print("HUGE-pay %s lines=%s" % (r.status_code, [dict(x) for x in lines]))
    pid2 = _approved(client, w, 4000)
    r2 = client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid2, json={"paidDate": "2031-03-06", "actualAmount": 100, "hasFee": True, "fee": 1e12}, headers=w["cash"])
    lines = _q("SELECT amount, fee, remit_review FROM case_material_payment_lines ORDER BY id")
    print("HUGE-fee %s lines=%s" % (r2.status_code, [dict(x) for x in lines]))
    ex = client.get("/api/cashier/remit-reviews", headers=w["adm"]).json()["items"]
    print("remit-reviews items=%s" % [(i.get("source"), i.get("amount"), i.get("fee")) for i in ex])


# ═════════════ 收款人個資告知（伺服端強制、ack 紀錄、GET／POST 權限）═════════════

def _create_raw(client, w, body_extra, who="adm", amount=6000):
    from modules.case.tests.test_material_payment_api_2026_10_02 import BODY
    body = dict(BODY, supplierId=w["sid"], amount=amount)
    body.update(body_extra)
    for k in [k for k, v in body.items() if v == "__DEL__"]:
        del body[k]
    return client.post("/api/quotations/%s/material-orders/%s/payments" % (NO, ITEM), json=body, headers=w[who])


@pytest.mark.parametrize("extra", [{"payeeNoticeAcked": "__DEL__"}, {"payeeNoticeAcked": False}, {"payeeNoticeAcked": "true"},
                                   {"payeeNoticeAcked": 1}, {"payeeNoticeAcked": None}, {"payeeNoticeAcked": "yes"}])
def test_ack_is_enforced_server_side_and_nothing_is_created_otherwise(client, world, extra):
    w = world
    r = _create_raw(client, w, extra)
    n = _q("SELECT COUNT(*) AS n FROM case_material_payments")[0]["n"]
    print("ack-enforce %r -> %s rows=%s" % (extra, r.status_code, n))
    assert r.status_code == 400 and n == 0


def test_ack_record_is_server_stamped_audited_and_client_cannot_forge_it(client, world):
    w = world
    r = _create_raw(client, w, {"payeeNoticeAcked": True, "ackedBy": "someone_else", "ackedAt": "1999-01-01", "ack": {"by": "x", "at": "1999"}})
    assert r.status_code == 200, r.text
    code = r.json()["payment"]["docCode"]
    pid = r.json()["payment"]["id"]
    acks = json.loads(_q("SELECT value_json FROM system_settings WHERE key='privacy_notice_acks'")[0]["value_json"])
    rec = acks.get("material_payment:" + code)
    print("ack record:", json.dumps(rec, ensure_ascii=False)[:300])
    assert rec and rec.get("at") and "1999" not in json.dumps(rec) and "someone_else" not in json.dumps(rec), "紀錄必須由伺服器蓋章"
    assert "material_payment.privacy_notice_ack" in [x["action"] for x in _q("SELECT action FROM audit_log ORDER BY id")]
    g = {who: client.get("/api/material-payments/%d/privacy-notice" % pid, headers=w[who]).status_code for who in ("sa", "adm", "adm2", "cash", "boss", "eng", "out")}
    print("GET privacy-notice matrix:", g)
    assert g["out"] in (403, 404) and g["adm"] == 200 and g["sa"] == 200
    p = {who: client.post("/api/material-payments/%d/privacy-notice/ack" % pid, headers=w[who]).status_code for who in ("adm", "eng", "out", "boss")}
    print("POST ack matrix:", p)
    assert p["eng"] == 403 and p["out"] in (403, 404)
    again = json.loads(_q("SELECT value_json FROM system_settings WHERE key='privacy_notice_acks'")[0]["value_json"]).get("material_payment:" + code)
    assert again == rec, "補記是冪等的：已記錄的不覆蓋"


def test_ack_recording_failure_must_not_leave_a_payment_without_an_ack(client, world, monkeypatch):
    """伺服器記錄告知失敗（例如紀錄檔壞了）：申請是否仍被建立？（建立端點的 _record_payee_ack 把例外吞成 None）"""
    from helpers import privacy_notice as PN

    def boom(*a, **k):
        raise RuntimeError("ack store unavailable")
    monkeypatch.setattr(PN, "record_purpose_ack", boom)
    w = world
    r = _create_raw(client, w, {"payeeNoticeAcked": True})
    n = _q("SELECT COUNT(*) AS n FROM case_material_payments")[0]["n"]
    print("ack store down -> create %s rows=%s" % (r.status_code, n))
    assert n == 0 or r.status_code >= 400, "告知紀錄寫不進去，申請卻建立了：沒有告知紀錄的申請存在"


# ═════════════ 金額 half-up ═════════════

@pytest.mark.parametrize("v,want", [(0.145, 0.15), (2.675, 2.68), (1.005, 1.01), (0.005, 0.01), (0.004, 0.0), (-0.145, -0.15), (10.0, 10.0), (1234567.895, 1234567.9)])
def test_r2_is_half_up(v, want):
    from modules.case import material_payment as MP
    assert MP.r2(v) == want


def test_fractional_payment_is_stored_half_up_and_remaining_follows(client, world):
    w = world
    pid = _approved(client, w, 10)
    r = client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-05", "actualAmount": 2.675}, headers=w["cash"])
    line = _q("SELECT amount, fee FROM case_material_payment_lines")[0]
    items = _pending_items(client, w)
    print("half-up pay -> %s line=%s remaining=%s" % (r.status_code, dict(line), [i["amount"] for i in items]))
    assert r.status_code == 200 and line["amount"] == 2.68 and items and items[0]["amount"] == 7.32


# ═════════════ 簽核佇列與紅點（一般使用者簽核人）═════════════

def test_queue_and_dot_count_for_a_plain_approver_across_both_types(client, world):
    w = world
    sid = w["sid"]
    cr = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])
    cr["caseRecord"]["materialOrders"].append({"itemId": "N1", "itemName": "新品", "quantity": 1, "unit": "式", "unitPrice": 100, "totalPrice": 100,
                                               "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "supplierId": sid})
    _x("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(cr), NO))
    _x("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
       (NO, "N1", "MO-20310101-0002", "草稿", "2031-01-01", "2031-01-01"))
    _flow([{"order": 0, "approvers": [{"username": w["boss_name"], "displayName": "主管"}]}])
    assert client.post("/api/quotations/%s/material-orders/N1/submit" % NO, headers=w["adm"]).status_code == 200
    p = _create(client, w, 6000).json()["payment"]
    assert client.post("/api/material-payments/%d/submit" % p["id"], headers=w["adm"]).status_code == 200
    cnt = {who: client.get("/api/approval-queue/count", headers=w[who]).json().get("count") for who in ("boss", "adm", "eng", "out")}
    q = client.get("/api/approval-queue", headers=w["boss"]).json()
    groups = q.get("queue") if isinstance(q, dict) and "queue" in q else q
    types = sorted({i.get("type") for g in (groups or []) for i in g.get("items", [])})
    print("queue payload keys:", list(q.keys()) if isinstance(q, dict) else type(q))
    print("queue counts:", cnt, "types:", types)
    assert cnt["boss"] == 2 and cnt["eng"] == 0 and cnt["out"] == 0 and {"material_order", "material_payment"} <= set(types)
    assert client.post("/api/quotations/%s/material-orders/N1/approve" % NO, headers=w["boss"]).status_code == 200
    assert client.get("/api/approval-queue/count", headers=w["boss"]).json().get("count") == 1


# ═════════════ 個資備份拆分 ═════════════

def test_archive_general_copy_strips_the_account_and_the_pii_copy_keeps_it(client, world):
    import archive
    w = world
    _approved(client, w, 6000)
    tables = archive._daily_backup_tables()
    key = "模組-case-case_material_payments"
    print("archive has table key:", key in tables)
    assert key in tables
    import db
    conn = db.get_db()
    try:
        rows = [dict(r) for r in conn.execute(tables[key]).fetchall()]
    finally:
        conn.close()
    gen = json.dumps([archive._general_row(key, r) for r in rows], ensure_ascii=False)
    full = json.dumps(rows, ensure_ascii=False)
    print("general has acct:", ACCT in gen, "| has acct name:", "甲供應商有限公司" in gen, "| pii has acct:", ACCT in full)
    assert ACCT not in gen and "甲供應商有限公司" not in gen and ACCT in full
    # 付款明細、叫料單 JSON 本身不含帳戶（一般份）
    for t in ("case_material_payment_lines",):
        assert ACCT not in json.dumps([dict(r) for r in _q("SELECT * FROM %s" % t)], ensure_ascii=False)


# ═════════════ has_payments 守門／舊單基線／自簽 ═════════════

def _put_orders(client, w, mutate):
    cr = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])["caseRecord"]
    rows = cr["materialOrders"]
    mutate(rows)
    return client.patch("/api/quotations/%s/material-orders" % NO, json={"materialOrders": rows}, headers=w["adm"])


def test_has_payments_guard_blocks_edit_delete_cancel_and_void_with_lines(client, world):
    w = world
    pid = _approved(client, w, 6000)
    r1 = _put_orders(client, w, lambda rows: rows[0].update({"unitPrice": 4000, "totalPrice": 8000}))
    rej = (r1.json() or {}).get("rejected") if r1.status_code == 200 else r1.text
    print("edit with live payment ->", r1.status_code, rej)
    assert _order_json()["totalPrice"] == 10000
    r2 = _put_orders(client, w, lambda rows: rows.clear())
    print("delete with payment ->", r2.status_code, (r2.json() or {}).get("rejected") if r2.status_code == 200 else r2.text[:80])
    assert _order_json()["itemId"] == ITEM
    assert client.post("/api/quotations/%s/material-orders/%s/cancel" % (NO, ITEM), json={"reason": "x"}, headers=w["adm"]).status_code == 409
    client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-05", "actualAmount": 1000}, headers=w["cash"])
    v = client.post("/api/material-payments/%d/void" % pid, json={"reason": "想作廢"}, headers=w["adm"])
    print("void with payment lines ->", v.status_code, v.text[:80])
    assert v.status_code in (400, 409)
    # 作廢（沒有付款明細的另一張）之後，叫料單可以改了嗎？
    pid2 = _create(client, w, 4000).json()["payment"]["id"]
    client.post("/api/material-payments/%d/void" % pid2, json={"reason": "改下次"}, headers=w["adm"])
    r3 = _put_orders(client, w, lambda rows: rows[0].update({"unitPrice": 4000, "totalPrice": 8000}))
    print("edit after voiding the unpaid one (the first still live) ->", r3.status_code, (r3.json() or {}).get("rejected"))


def test_legacy_order_baseline_creates_payments_with_legacy_paid_deducted(client, world):
    w = world
    _x("DELETE FROM case_material_approvals")                                         # 舊單：沒有疊加列
    cr = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])
    cr["caseRecord"]["materialOrders"][0].update({"paidStatus": "partial", "paidAmount": 4000, "paidDate": "2031-02-01", "supplierId": w["sid"]})
    _x("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(cr), NO))
    _flow([])
    ok = _create(client, w, 6000)
    over = _create(client, w, 1)
    g = client.get("/api/quotations/%s/material-payments" % NO, headers=w["adm"]).json()["orders"][ITEM]["quota"]
    print("legacy: create 6000 ->", ok.status_code, "; +1 ->", over.status_code, "; quota:", g)
    assert ok.status_code == 200 and over.status_code == 409 and g["legacyPaid"] == 4000.0
    o = _order_json()
    print("legacy order paid fields after first application: %s/%s" % (o.get("paidStatus"), o.get("paidAmount")))


def test_requester_can_self_approve_when_listed_in_the_tier_same_as_other_tiered_docs(client, world):
    """同第 30 班派發觀察 O-1：叫料單送審人也在簽核層／是唯一簽核人時可自簽（共用引擎）。"""
    w = world
    cr = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])
    cr["caseRecord"]["materialOrders"].append({"itemId": "N1", "itemName": "新品", "quantity": 1, "unit": "式", "unitPrice": 100, "totalPrice": 100,
                                               "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "supplierId": w["sid"]})
    _x("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(cr), NO))
    _x("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
       (NO, "N1", "MO-20310101-0003", "草稿", "2031-01-01", "2031-01-01"))
    _flow([{"order": 0, "approvers": [{"username": "mpa_adm", "displayName": "申請人本人"}]}])
    assert client.post("/api/quotations/%s/material-orders/N1/submit" % NO, headers=w["adm"]).status_code == 200
    r = client.post("/api/quotations/%s/material-orders/N1/approve" % NO, headers=w["adm"])
    st = _q("SELECT status FROM case_material_approvals WHERE item_id='N1'")[0]["status"]
    print("self-approve as the only approver ->", r.status_code, st)
