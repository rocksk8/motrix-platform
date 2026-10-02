# -*- coding: utf-8 -*-
"""叫料匯款申請（31-C 匯款切片）：現金口徑與總帳 E12b 改讀「付款明細」（一筆明細一列）、舊單歷史已付、手續費、多付待審不入帳、不重複計算。

手算（2031 年；全部叫料單小計 10,000、已付日期都在 2031）：
  L1：申請 6,000，兩筆付款明細 03-05 付 2,500、03-09 付 3,500（手續費 15、付款科目 1111）。叫料單 JSON 的 paid* 投影＝partial 6,000（03-09）——
      現金口徑要看到兩列（2,500＠03-05、3,500＠03-09），**不是**一列 6,000＠03-09。
  L9：舊單、歷史已付 3,000（02-01），第一張申請 2,000 付 03-05 ⇒ 兩列（3,000＠02-01 舊單歷史、2,000＠03-05 明細）；JSON 投影 5,000 不可再算一次。
  L7：舊單、沒有任何申請、JSON 已付 1,000（02-10）⇒ 一列，維持讀 JSON。
  L8：申請 4,000，付 4,500（多付 500，差額待審核）03-20 ⇒ 現金口徑照計 4,500（錢付出去了），總帳 E12b 暫不入帳並在 notice 說明。
  現金月合計：02 月＝3,000＋1,000＝4,000；03 月＝2,500＋3,500＋2,000＋4,500＝12,500。
  E12b：L1 兩筆、L9 兩筆（舊單歷史 `案件::L9`、明細 `案件::L9::明細id`）、L7 一筆＝5 筆；L8 不入帳。L1 第二筆：借 AP 3,500＋借 FEE 15／貸 銀行 3,515（科目 1111）。
"""
import json

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料匯款申請")

NO = "MQ-MPR-001"
Y = 2031


def _order(item, paid=0, paid_date="", **kw):
    o = {"itemId": item, "itemName": "品" + item, "quantity": 1, "unit": "式", "unitPrice": 10000, "totalPrice": 10000,
         "paidStatus": "pending" if not paid else "partial", "paidAmount": paid, "paidDate": paid_date, "invoiceDate": "2031-01-10", "notes": ""}
    o.update(kw)
    return o


def _pay(conn, item, seq, amount, snap_extra=None):
    snap = {"itemName": "品" + item, "supplierName": "甲供應商", "totalPrice": 10000.0, "legacyPaid": 0.0, "legacyPaidDate": ""}
    snap.update(snap_extra or {})
    cur = conn.execute("INSERT INTO case_material_payments (doc_code, quote_no, item_id, seq, amount_approved, snapshot_json, status, created_at, updated_at)"
                       " VALUES (?,?,?,?,?,?,?,?,?)", ("MP-20310301-%04d" % (len(item) * 100 + seq + ord(item[-1])), NO, item, seq, amount, json.dumps(snap), "已核准", "2031-03-01", "2031-03-01"))
    return cur.lastrowid


def _line(conn, pid, day, amount, fee=0, review="", account="", method=""):
    return conn.execute("INSERT INTO case_material_payment_lines (payment_id, paid_at, amount, fee, remit_review, pay_account_code, pay_method, paid_by, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?)", (pid, day, amount, fee, review, account, method, "cashier", day)).lastrowid


@pytest.fixture
def seeded(client):
    import db
    from modules.case import material_payment as MP
    orders = [_order("L1"), _order("L9", 3000, "2031-02-01"), _order("L7", 1000, "2031-02-10"), _order("L8")]
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                     " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "報表客", "報表專案", 1, 1, json.dumps({"dealTag": "已成案", "caseRecord": {"materialOrders": orders}}),
                      "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", "[]"))
        a = _pay(conn, "L1", 1, 6000)
        l1a = _line(conn, a, "2031-03-05", 2500)
        l1b = _line(conn, a, "2031-03-09", 3500, fee=15, account="1111")
        b = _pay(conn, "L9", 1, 2000, {"legacyPaid": 3000.0, "legacyPaidDate": "2031-02-01"})
        l9 = _line(conn, b, "2031-03-05", 2000)
        c = _pay(conn, "L8", 1, 4000)
        l8 = _line(conn, c, "2031-03-20", 4500, review="pending")
        for it in ("L1", "L9", "L8"):
            MP.sync_order_paid(conn, NO, it)                                                  # 投影回叫料單 JSON（跟真實付款流程同一個函式）
        conn.commit()
        ids = {"l1a": l1a, "l1b": l1b, "l9": l9, "l8": l8}
    finally:
        conn.close()
    return ids


def _cash():
    import db
    from modules.case import recognition as REC
    conn = db.get_db()
    try:
        return REC.material_entries(conn, "cash")
    finally:
        conn.close()


def test_projection_on_the_order_json_is_what_the_old_readers_would_have_double_counted(seeded):
    import db
    conn = db.get_db()
    try:
        orders = {o["itemId"]: o for o in json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["caseRecord"]["materialOrders"]}
    finally:
        conn.close()
    assert (orders["L1"]["paidStatus"], orders["L1"]["paidAmount"], orders["L1"]["paidDate"]) == ("partial", 6000.0, "2031-03-09")
    assert (orders["L9"]["paidStatus"], orders["L9"]["paidAmount"], orders["L9"]["paidDate"]) == ("partial", 5000.0, "2031-03-05")
    assert (orders["L8"]["paidStatus"], orders["L8"]["paidAmount"]) == ("partial", 4500.0)
    assert (orders["L7"]["paidStatus"], orders["L7"]["paidAmount"]) == ("partial", 1000)        # 沒有申請的舊單：投影沒碰


def test_cash_entries_read_payment_lines_and_do_not_double_count(seeded):
    ents = _cash()
    got = sorted((e["itemId"], e["date"], e["amount"]) for e in ents)
    assert got == [("L1", "2031-03-05", 2500.0), ("L1", "2031-03-09", 3500.0), ("L7", "2031-02-10", 1000.0),
                   ("L8", "2031-03-20", 4500.0), ("L9", "2031-02-01", 3000.0), ("L9", "2031-03-05", 2000.0)], got
    assert sum(e["amount"] for e in ents) == 16500.0
    assert {e["itemId"]: e["remitPending"] for e in ents if e["date"] == "2031-03-20"} == {"L8": True}      # 多付待審：照計，標記
    assert [e["lineId"] for e in ents if e["itemId"] == "L9" and e["date"] == "2031-02-01"] == [""]         # 舊單歷史沒有明細 id
    assert [e.get("lineId", "") for e in ents if e["itemId"] == "L7"] == [""]                              # 沒有申請的舊單：維持讀 JSON（沒有明細 id）


def test_operating_report_cash_monthly_totals(seeded):
    from modules.analytics.api import reports as R
    res = R._collect_expenses(Y, None, "cash")
    by = {m["month"]: m["material"] for m in res["monthly"]}
    assert by["%d-02" % Y] == 4000 and by["%d-03" % Y] == 12500, by


def test_ledger_e12b_one_event_per_line_idempotent_keys_fee_and_pending_review(seeded):
    from modules.case import gl_events as GE
    res = GE.gl_events("%d-01-01" % Y, "%d-12-31" % Y)
    ev = [e for e in res["events"] if e["event_code"] == "E12b"]
    keys = sorted(e["source_key"] for e in ev)
    ids = seeded
    assert keys == sorted(["%s::L1::%d" % (NO, ids["l1a"]), "%s::L1::%d" % (NO, ids["l1b"]), "%s::L9" % NO, "%s::L9::%d" % (NO, ids["l9"]), "%s::L7" % NO]), keys
    assert len(set(keys)) == len(keys)                                                          # 冪等鍵不重複
    assert not [e for e in ev if e["source_key"].startswith("%s::L8" % NO)]                     # 多付待審不入帳
    assert "1 筆材料申請匯款的實付超過應付且尚未核可" in res["notice"]
    second = next(e for e in ev if e["source_key"].endswith("::%d" % ids["l1b"]))
    legs = [(l["role"], l["side"], l["amount"], l.get("account_code", "")) for l in second["lines"]]
    assert legs == [("AP", "D", 3500, ""), ("FEE", "D", 15, ""), ("BANK", "C", 3515, "1111")], legs
    assert second["event_date"] == "2031-03-09" and second["doc_no"].startswith("MP-")
    first = next(e for e in ev if e["source_key"].endswith("::%d" % ids["l1a"]))
    assert [(l["role"], l["side"], l["amount"]) for l in first["lines"]] == [("AP", "D", 2500), ("BANK", "C", 2500)]
    legacy = next(e for e in ev if e["source_key"] == "%s::L7" % NO)                            # 沒有申請的舊單：維持舊的單一事件
    assert [(l["role"], l["amount"]) for l in legacy["lines"]] == [("AP", 1000), ("BANK", 1000)]
    assert sum(next(l["amount"] for l in e["lines"] if l["side"] == "D" and l["role"] == "AP") for e in ev) == 2500 + 3500 + 3000 + 2000 + 1000
    again = GE.gl_events("%d-01-01" % Y, "%d-12-31" % Y)
    assert sorted(e["source_key"] for e in again["events"] if e["event_code"] == "E12b") == keys


def test_approving_the_overpayment_lets_it_into_the_ledger(seeded):
    import db
    from modules.case import gl_events as GE
    conn = db.get_db()
    try:
        conn.execute("UPDATE case_material_payment_lines SET remit_review='approved' WHERE id=?", (seeded["l8"],))
        conn.commit()
    finally:
        conn.close()
    res = GE.gl_events("%d-01-01" % Y, "%d-12-31" % Y)
    l8 = [e for e in res["events"] if e["event_code"] == "E12b" and "::L8::" in e["source_key"]]
    assert len(l8) == 1 and [(l["role"], l["amount"]) for l in l8[0]["lines"]] == [("AP", 4500), ("BANK", 4500)]
    assert "尚未核可" not in res["notice"]
