# -*- coding: utf-8 -*-
"""叫料審核（31-C S4）：營運報表成本與總帳事件的審核閘（與承攬商派發同一組規則）。

權責口徑：草稿／已退回／已取消**不計**；待審核／簽核中**計入並標 pending**；已核准與舊單（沒有審核單）照舊。
現金口徑：付出去的錢是事實 ⇒ 不因審核狀態排除（只標 pending）。總帳 E12：只有已核准與舊單入帳，審核中的不入帳並在 notice 說明。
手算（發票日 2031-03-10；小計＝L 1,000／A 2,000／P 4,000／D 8,000／R 16,000／C 32,000）：
  權責：L＋A＋P＝7,000（P 標待審核）；E12：L 1,000、A 2,000 兩筆（P 審核中不入帳）；現金（全部已付 2031-04-01）：63,000。
"""
import json

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料審核")

NO = "MQ-MATR-001"
Y = 2031


def _order(item, total):
    return {"itemId": item, "itemName": "品" + item, "quantity": 1, "unit": "式", "unitPrice": total, "totalPrice": total,
            "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "invoiceDate": "2031-03-10", "notes": ""}


@pytest.fixture
def seeded(client):
    import db
    orders = [_order("L", 1000), _order("A", 2000), _order("P", 4000), _order("D", 8000), _order("R", 16000), _order("C", 32000)]
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                     " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "報表客", "報表專案", 1, 1, json.dumps({"dealTag": "已成案", "caseRecord": {"materialOrders": orders}}),
                      "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", "[]"))
        for i, (item, st) in enumerate((("A", "已核准"), ("P", "待審核"), ("D", "草稿"), ("R", "已退回"), ("C", "已取消")), 1):
            conn.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                         (NO, item, "MO-20310301-%04d" % i, st, "2031-03-01", "2031-03-01"))
        conn.commit()
    finally:
        conn.close()
    return orders


def _set_paid_all():
    import db
    conn = db.get_db()
    try:
        data = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        for o in data["caseRecord"]["materialOrders"]:
            o.update({"paidStatus": "paid", "paidAmount": o["totalPrice"], "paidDate": "2031-04-01"})
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(data), NO))
        conn.commit()
    finally:
        conn.close()


def test_accrual_entries_follow_the_approval_state(seeded):
    import db
    from modules.case import recognition as REC
    conn = db.get_db()
    try:
        ents = REC.material_entries(conn, "accrual")
    finally:
        conn.close()
    got = {e["itemId"]: e for e in ents}
    assert sorted(got) == ["A", "L", "P"]                                              # 草稿 D／已退回 R／已取消 C 不計
    assert sum(e["amount"] for e in ents) == 7000
    assert {k: (v["pending"], v["approval"]) for k, v in got.items()} == {"L": (False, ""), "A": (False, "已核准"), "P": (True, "待審核")}


def test_cash_entries_keep_real_payments_and_only_flag_pending(seeded):
    import db
    from modules.case import recognition as REC
    _set_paid_all()
    conn = db.get_db()
    try:
        ents = REC.material_entries(conn, "cash")
    finally:
        conn.close()
    assert sum(e["amount"] for e in ents) == 63000 and len(ents) == 6                   # 付出去的錢都在
    assert [e["itemId"] for e in ents if e["pending"]] == ["P"]


def test_operating_report_counts_pending_with_a_flag_and_leaves_the_excluded_out(seeded):
    from modules.analytics.api import reports as R
    res = R._collect_expenses(Y, None, "accrual")
    mar = next(m for m in res["monthly"] if m["month"] == "%d-03" % Y)
    assert mar["material"] == 7000
    rows = [d for d in res["details"]["material"] if d["quoteNo"] == NO]
    assert sorted(d["desc"] for d in rows) == ["材料申請｜品A", "材料申請｜品L", "材料申請｜品P"]
    flagged = [d for d in rows if d["pending"]]
    assert [d["desc"] for d in flagged] == ["材料申請｜品P"] and "待審核" in flagged[0]["taxNote"]
    assert all(d["pending"] is False for d in rows if d["desc"] != "材料申請｜品P")


def test_ledger_e12_only_for_approved_or_legacy_and_says_why(seeded):
    from modules.case import gl_events as GE
    res = GE.gl_events("%d-01-01" % Y, "%d-12-31" % Y)
    e12 = {e["source_key"].split("::")[1]: e for e in res["events"] if e["event_code"] == "E12"}
    assert sorted(e12) == ["A", "L"]
    assert sorted(sum(l["amount"] for l in e["lines"] if l["side"] == "D") for e in e12.values()) == [1000, 2000]
    assert "1 筆材料申請審核中" in res["notice"]
    # 現金口徑（E12b）不受審核狀態影響：付出去的錢照入帳草稿
    _set_paid_all()
    res = GE.gl_events("%d-01-01" % Y, "%d-12-31" % Y)
    assert len([e for e in res["events"] if e["event_code"] == "E12b"]) == 6
