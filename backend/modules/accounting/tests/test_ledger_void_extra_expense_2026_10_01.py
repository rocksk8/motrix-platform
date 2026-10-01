# -*- coding: utf-8 -*-
"""A2 作廢 × 總帳（S1 條件）：用**真的 case 提供者＋真的作廢 API**證明「來源狀態離開已核准 ⇒ 引擎自己沖轉」，不靠 docstring。
草稿傳票 ⇒ 作廢（總帳沒有這筆）；已過帳傳票 ⇒ 產生借貸對調的反向草稿（過帳後淨額為零）；
正對照：沒被作廢的列傳票原封不動；反向控制：作廢沒有讓狀態離開「已核准」（把 VOIDED_STATUS 改成已核准）⇒ 傳票不會被沖轉（證明這組斷言抓得到）。"""
import json

import pytest

import db
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import roles as ROLES

D1, D2 = "2177-03-01", "2177-03-31"


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


@pytest.fixture
def sa(client, make_user):
    name, pw = make_user(username="vg_sa", role="superadmin")
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _quote(conn, qn):
    conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (qn, "已送出", "客", "案", 0, 0, json.dumps({"dealTag": "已成案"}), "2177-01-01T00:00:00", "2177-01-01T00:00:00", "已成案", "2177-01-01"))
    conn.commit()


def _extra(conn, qn, total=1050):
    cur = conn.execute(
        "INSERT INTO case_extra_expenses(quote_no, category, description, total_cost, expense_date, doc_no, status, approval_json, invoice_date, paid_date, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (qn, "材料", "測試支出", total, "2177-03-01", "D-1", "已核准", json.dumps({"steps": [{"approvedAt": "2177-03-05"}]}), "2177-03-10", "", "2177-03-01T00:00:00"))
    conn.commit()
    return cur.lastrowid


def _run(conn):
    r = E.run(conn, D1, D2, "acc")
    conn.commit()
    return r


def _ev(conn, eid):
    return [dict(r) for r in conn.execute("SELECT * FROM gl_source_events WHERE source_type='case_extra_expense' AND source_key=? ORDER BY id", (str(eid),))]


def _v(conn, vid):
    return dict(conn.execute("SELECT * FROM vouchers_all WHERE id=?", (vid,)).fetchone())


def _lines(conn, vid):
    return [(r["account_code"], r["debit"], r["credit"]) for r in conn.execute("SELECT * FROM voucher_lines WHERE voucher_id=? ORDER BY line_no", (vid,))]


def _void(client, sa, qn, eid):
    return client.post("/api/quotations/%s/extra-expenses/%d/void" % (qn, eid), headers=sa, json={"reason": "測試作廢"})


def test_void_before_posting_voids_the_draft_voucher_and_keeps_the_control_row(client, conn, sa):
    _quote(conn, "MQ-GLV-1")
    gone, keep = _extra(conn, "MQ-GLV-1", 1050), _extra(conn, "MQ-GLV-1", 2100)
    assert _run(conn)["stats"]["created"] >= 2
    g0, k0 = _ev(conn, gone)[0], _ev(conn, keep)[0]
    assert g0["status"] == "drafted" and _lines(conn, g0["voucher_id"]) and _v(conn, g0["voucher_id"])["voided_at"] == ""        # 作廢前：有傳票、有分錄
    assert _void(client, sa, "MQ-GLV-1", gone).status_code == 200
    r = _run(conn)
    assert r["stats"]["orphans"] == 1
    g1, k1 = _ev(conn, gone)[0], _ev(conn, keep)[0]
    assert g1["status"] == "orphan" and _v(conn, g1["voucher_id"])["voided_at"] != ""                                        # 作廢列的草稿傳票被作廢
    assert k1["status"] == "drafted" and _v(conn, k1["voucher_id"])["voided_at"] == "" and k1["voucher_id"] == k0["voucher_id"]    # 正對照：另一列原封不動
    again = _run(conn)
    assert again["stats"]["created"] == 0 and again["stats"]["orphans"] == 0                                                 # 冪等：不會又重建


def test_void_after_posting_creates_a_mirrored_reversal_draft(client, conn, sa):
    _quote(conn, "MQ-GLV-2")
    eid = _extra(conn, "MQ-GLV-2", 1050)
    _run(conn)
    e = _ev(conn, eid)[0]
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (e["voucher_id"],))
    conn.commit()
    orig = _lines(conn, e["voucher_id"])
    assert orig and sum(d for _, d, _c in orig) == sum(c for _, _d, c in orig) == 1050
    assert _void(client, sa, "MQ-GLV-2", eid).status_code == 200
    assert _run(conn)["stats"]["orphans"] == 1
    e2 = _ev(conn, eid)[0]
    assert e2["status"] == "orphan" and e2["reversal_voucher_id"]
    assert _v(conn, e["voucher_id"])["status"] == "已過帳" and _v(conn, e["voucher_id"])["voided_at"] == ""                    # 已過帳的原傳票不動
    rev = _v(conn, e2["reversal_voucher_id"])
    assert rev["voided_at"] == "" and rev["reverses_no"] == _v(conn, e["voucher_id"])["voucher_no"]
    mirrored = [(a, c, d) for a, d, c in orig]                                                                                   # 借貸對調
    assert sorted(_lines(conn, e2["reversal_voucher_id"])) == sorted(mirrored)
    net = {}
    for acct, d, c in orig + _lines(conn, e2["reversal_voucher_id"]):
        net[acct] = net.get(acct, 0) + d - c
    assert set(net.values()) == {0}                                                                                              # 過帳後每個科目淨額為零


def test_reverse_control_if_void_did_not_leave_approved_the_voucher_would_stay(client, conn, sa, monkeypatch):
    """反向控制：把「作廢」做成不離開已核准的狀態（模擬排除失效）⇒ 引擎看來源還在 ⇒ 傳票不被沖轉。上面兩題因此是真的在驗排除。"""
    from modules.case.api import case_extra_expenses as X
    monkeypatch.setattr(X, "VOIDED_STATUS", "已核准")
    _quote(conn, "MQ-GLV-3")
    eid = _extra(conn, "MQ-GLV-3", 1050)
    _run(conn)
    vid = _ev(conn, eid)[0]["voucher_id"]
    r = client.post("/api/quotations/MQ-GLV-3/extra-expenses/%d/void" % eid, headers=sa, json={"reason": "x"})
    assert r.status_code in (200, 409)
    r2 = _run(conn)
    assert r2["stats"]["orphans"] == 0 and _ev(conn, eid)[0]["status"] == "drafted" and _v(conn, vid)["voided_at"] == ""


def test_voucher_summary_sources_skip_voided_rows(client, conn, sa):
    """傳票「摘要來源」列案件的額外支出：已作廢的不可再被拿來當來源（正對照：沒作廢的照列）。"""
    from modules.accounting.api import voucher_summary as VS
    _quote(conn, "MQ-GLV-4")
    gone, keep = _extra(conn, "MQ-GLV-4", 1050), _extra(conn, "MQ-GLV-4", 2100)
    assert {e["id"] for e in VS._case_expense_sources(conn, "MQ-GLV-4", sa["Authorization"]) if e["kind"] == "extra_expense"} == {gone, keep}
    assert _void(client, sa, "MQ-GLV-4", gone).status_code == 200
    assert {e["id"] for e in VS._case_expense_sources(conn, "MQ-GLV-4", sa["Authorization"]) if e["kind"] == "extra_expense"} == {keep}
