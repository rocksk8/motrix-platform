# -*- coding: utf-8 -*-
"""總帳 C5 · 扣繳清單（代扣所得稅、二代健保）：引擎產生 E06 草稿時記入、來源消失／內容變動時未繳庫的列跟著走、已繳庫的保留；
期限（次月 10 日／次月底）、逾期、與 2252 貸方發生額對帳、API（旗標、權限、稽核）。
"""
import pytest

import db
from core import registry
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import features as F
from modules.accounting.ledger import roles as ROLES
from modules.accounting.ledger import withholding as W

_N = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS", {})
    monkeypatch.setattr(registry, "_LOADED", {})
    state = {"events": []}
    registry._LEGACY_PROVIDERS[("gl.events", "fake")] = lambda s, e, changed_since="": {"events": list(state["events"])}
    return state


def _slip(date="2179-03-10", gross=10000, tax=1000, nhi=211, key=None, income="9A"):
    _N[0] += 1
    key = key or "LB-WH-%d-%d" % (id(_N), _N[0])
    lines = [{"role": "EXP_LABOR", "side": "D", "amount": gross}]
    if tax:
        lines.append({"role": "WITHHOLD_TAX", "side": "C", "amount": tax})
    if nhi:
        lines.append({"role": "WITHHOLD_NHI", "side": "C", "amount": nhi})
    lines.append({"role": "OTHER_PAYABLE", "side": "C", "amount": gross - tax - nhi})
    return {"source_type": "payslip", "source_key": key, "event_code": "E06", "event_date": date, "doc_no": key, "case_no": "",
            "party": {"key": "C1", "name": "王"}, "tax_code": "", "mode": "snapshot", "lines": lines, "meta": {"income_type": income}}


def _run(conn, fake, events, start="2179-03-01", end="2179-03-31"):
    fake["events"] = events
    r = E.run(conn, start, end, "acc")
    conn.commit()
    return r


def _items(conn, key=None):
    q = "SELECT * FROM gl_withholding_items" + (" WHERE source_key=?" if key else "") + " ORDER BY id"
    return [dict(r) for r in conn.execute(q, (key,) if key else ())]


def test_due_dates():
    assert W.due_date("income_tax", "2179-03") == "2179-04-10"
    assert W.due_date("nhi", "2179-03") == "2179-04-30"
    assert W.due_date("income_tax", "2179-12") == "2180-01-10" and W.due_date("nhi", "2179-12") == "2180-01-31"
    assert W.due_date("nhi", "2180-01") == "2180-02-29"                                   # 閏年


def test_engine_records_tax_and_nhi_items(conn, fake):
    ev = _slip()
    _run(conn, fake, [ev])
    rows = {r["kind"]: r for r in _items(conn, ev["source_key"])}
    assert (rows["income_tax"]["amount"], rows["income_tax"]["gross"], rows["income_tax"]["period_ym"]) == (1000, 10000, "2179-03")
    assert rows["nhi"]["amount"] == 211 and rows["nhi"]["income_type"] == "9A" and rows["nhi"]["party_key"] == "C1"
    _run(conn, fake, [ev])                                                              # 冪等
    assert len(_items(conn, ev["source_key"])) == 2


def test_zero_withholding_records_nothing(conn, fake):
    ev = _slip(tax=0, nhi=0)
    _run(conn, fake, [ev])
    assert _items(conn, ev["source_key"]) == []


def test_source_change_updates_unremitted_amount(conn, fake):
    ev = _slip()
    _run(conn, fake, [ev])
    _run(conn, fake, [_slip(key=ev["source_key"], tax=1200, nhi=0, gross=12000)])
    rows = {r["kind"]: r for r in _items(conn, ev["source_key"])}
    assert rows["income_tax"]["amount"] == 1200 and "nhi" not in rows                    # 補充保費不再代扣 ⇒ 該列移除


def test_source_gone_removes_unremitted_but_keeps_remitted(conn, fake):
    a, b = _slip(), _slip()
    _run(conn, fake, [a, b])
    tax_b = [r for r in _items(conn, b["source_key"]) if r["kind"] == "income_tax"][0]
    assert W.mark_remitted(conn, [tax_b["id"]], "2179-04-08") == 1
    conn.commit()
    _run(conn, fake, [])                                                                # 兩張勞報單都不見了（退回簽回）
    left = _items(conn)
    assert [(r["source_key"], r["kind"]) for r in left if r["source_key"] in (a["source_key"], b["source_key"])] == [(b["source_key"], "income_tax")]


def test_remitted_rows_do_not_change_when_source_changes(conn, fake):
    ev = _slip()
    _run(conn, fake, [ev])
    ids = [r["id"] for r in _items(conn, ev["source_key"])]
    W.mark_remitted(conn, ids, "2179-04-08")
    conn.commit()
    _run(conn, fake, [_slip(key=ev["source_key"], tax=900, nhi=100, gross=10000)])
    got = {r["kind"]: r["amount"] for r in _items(conn, ev["source_key"])}
    assert got["income_tax"] == 1000 and got["nhi"] == 211                               # 已繳庫的不被改（差額由會計手工處理）


def test_report_groups_due_overdue_and_account_check(conn, fake):
    ev = _slip()
    _run(conn, fake, [ev])
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE kind='auto' AND status='草稿' AND voided_at=''")
    conn.commit()
    rep = W.report(conn, "2179-03", today="2179-04-11")
    g = {x["kind"]: x for x in rep["groups"]}
    assert g["income_tax"]["due"] == "2179-04-10" and g["income_tax"]["overdue"] is True and g["nhi"]["overdue"] is False and g["income_tax"]["unremitted"] == 1000
    assert rep["checks"][0]["left"] == 1211 and rep["checks"][0]["right"] == 1211 and rep["checks"][0]["ok"] is True
    W.mark_remitted(conn, [i["id"] for i in rep["items"] if i["kind"] == "income_tax"], "2179-04-09")
    conn.commit()
    rep2 = W.report(conn, "2179-03", today="2179-04-11")
    assert {x["kind"]: x for x in rep2["groups"]}["income_tax"]["overdue"] is False


def test_account_check_shows_unlisted_withholding(conn, fake):
    ev = _slip()
    _run(conn, fake, [ev])
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE kind='auto' AND status='草稿' AND voided_at=''")
    conn.execute("DELETE FROM gl_withholding_items WHERE kind='nhi' AND source_key=?", (ev["source_key"],))          # 模擬獎金代扣等『帳上有、清單沒有』
    conn.commit()
    assert W.report(conn, "2179-03")["checks"][0]["ok"] is False


def test_mark_remitted_validation(conn, fake):
    ev = _slip()
    _run(conn, fake, [ev])
    ids = [r["id"] for r in _items(conn, ev["source_key"])]
    with pytest.raises(W.WithholdingError):
        W.mark_remitted(conn, ids, "not-a-date")
    with pytest.raises(W.WithholdingError):
        W.mark_remitted(conn, [], "2179-04-09")
    with pytest.raises(W.WithholdingError):
        W.mark_remitted(conn, ids, "2179-04-09", "NO-SUCH-VOUCHER")
    assert W.mark_remitted(conn, ids, "2179-04-09") == 2 and W.mark_remitted(conn, ids, "2179-04-09") == 0        # 重複登記不再算
    assert W.unmark_remitted(conn, ids) == 2


def test_api_flag_permissions_and_audit(client, conn, fake, make_user):
    u, p = make_user(username="wh_admin%d" % id(client), role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.get("/api/ledger/withholding?ym=2179-03", headers=h).status_code == 409                # 旗標預設關
    F.set_flag(conn, "withholding", True)
    conn.commit()
    ev = _slip()
    _run(conn, fake, [ev])
    r = client.get("/api/ledger/withholding?ym=2179-03", headers=h)
    assert r.status_code == 200 and len(r.json()["items"]) == 2
    assert client.get("/api/ledger/withholding?ym=2179-13", headers=h).status_code == 400
    assert client.get("/api/ledger/withholding?kind=bogus", headers=h).status_code == 400
    ids = [i["id"] for i in r.json()["items"]]
    assert client.post("/api/ledger/withholding/remit", headers=h, json={"ids": ids, "remitted_at": "bad"}).status_code == 400
    ok = client.post("/api/ledger/withholding/remit", headers=h, json={"ids": ids, "remitted_at": "2179-04-09"})
    assert ok.status_code == 200 and ok.json() == {"updated": 2}
    assert client.post("/api/ledger/withholding/unremit", headers=h, json={"ids": ids}).json() == {"updated": 2}
    c = db.get_db()
    try:
        n = c.execute("SELECT COUNT(*) FROM audit_log WHERE action IN ('ledger.withholding.remit','ledger.withholding.unremit')").fetchone()[0]
    finally:
        c.close()
    assert n >= 2


def test_real_payroll_provider_feeds_the_list(conn):
    """不用 fake：勞報單（已簽回）經真的 payroll 提供者 ⇒ 引擎 ⇒ 扣繳清單。"""
    cid = conn.execute("INSERT INTO contractors(name, id_number) VALUES ('扣繳測','D123456789')").lastrowid
    conn.execute("INSERT INTO payslips(slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, "
                 "slip_date, status, signed_at) VALUES ('LB-WH-REAL', ?, '扣繳測', '9A', 10000, 1000, 211, 8789, '2179-05-10', '已簽回', '2179-05-11T00:00:00')", (cid,))
    conn.commit()
    r = E.run(conn, "2179-05-01", "2179-05-31", "acc")
    conn.commit()
    assert r["sources"]["payroll"] == "ok"
    got = {i["kind"]: i for i in _items(conn, "LB-WH-REAL")}
    assert got["income_tax"]["amount"] == 1000 and got["nhi"]["amount"] == 211 and got["nhi"]["party_key"] == "C%s" % cid


# ── 獎金發放的代扣（native 事件經 payroll 提供者帶進來）────────────────────────────────

def _bonus_award(conn, deductions_lines, date="2179-06-10"):
    import json
    from datetime import datetime
    _N[0] += 1
    v = registry.single_provider("voucher.draft")(
        conn, voucher_date=date, summary="獎金發放", created_by="t", now=date + "T00:00:00", origin="bonus_payment",
        lines=[{"account_code": "2191", "summary": "x", "debit": 80000, "credit": 0}, {"account_code": "1113", "summary": "x", "debit": 0, "credit": 80000}])
    now = datetime.now().isoformat()
    aid = conn.execute(
        "INSERT INTO bonus_case_awards(quote_no, status, net_profit, rate_bp, split_json, pool_amount, created_by, created_at, updated_by, updated_at,"
        " accrual_voucher_id, payment_voucher_id) VALUES (?,?,?,?,?,?,?,?,?,?,0,?)",
        ("MQ-WH-%d-%d" % (id(_N), _N[0]), "已發放", "1000", 1000, "{}", 100, "t", now, "t", now, v["id"])).lastrowid
    conn.execute("INSERT INTO bonus_case_award_edit_log(award_id, changed_by, changed_at, action, changes_json) VALUES (?,?,?,?,?)",
                 (aid, "t", now, "mark_paid", json.dumps({"deductions": {"lines": deductions_lines}})))
    conn.commit()
    return aid, v["id"]


def _bonus_items(conn, aid):
    return {(r["kind"], r["party_key"]): r for r in conn.execute("SELECT * FROM gl_withholding_items WHERE source_type='bonus_payment' AND source_key LIKE ?", ("%d::%%" % aid,))}


def test_bonus_payment_withholding_enters_the_list_and_follows_changes(conn):
    aid, vid = _bonus_award(conn, [{"username": "u1", "gross": 50000, "withholding": 5000, "nhiPremium": 1055},
                                   {"username": "u2", "gross": 30000, "withholding": 0, "nhiPremium": 0}])
    r = E.run(conn, "2179-06-01", "2179-06-30", "acc")
    conn.commit()
    assert r["stats"]["native"] >= 1
    got = _bonus_items(conn, aid)
    assert set(got) == {("income_tax", "u1"), ("nhi", "u1")} and got[("income_tax", "u1")]["amount"] == 5000 and got[("nhi", "u1")]["gross"] == 50000
    assert got[("nhi", "u1")]["income_type"] == "bonus" and got[("nhi", "u1")]["period_ym"] == "2179-06"
    E.run(conn, "2179-06-01", "2179-06-30", "acc")
    conn.commit()
    assert len(_bonus_items(conn, aid)) == 2                                               # 冪等
    import json
    conn.execute("INSERT INTO bonus_case_award_edit_log(award_id, changed_by, changed_at, action, changes_json) VALUES (?,?,?,?,?)",      # 編寫紀錄只增不改：以較新的一筆為準
                 (aid, "t", "2179-06-30T00:00:00", "mark_paid", json.dumps({"deductions": {"lines": [{"username": "u1", "gross": 50000, "withholding": 5000, "nhiPremium": 0}]}})))
    conn.commit()
    E.run(conn, "2179-06-01", "2179-06-30", "acc")
    conn.commit()
    assert set(_bonus_items(conn, aid)) == {("income_tax", "u1")}                          # 補充保費不再代扣 ⇒ 該列移除


def test_voided_bonus_voucher_removes_unremitted_rows_but_keeps_remitted(conn):
    aid, vid = _bonus_award(conn, [{"username": "u1", "gross": 50000, "withholding": 5000, "nhiPremium": 1055}])
    E.run(conn, "2179-06-01", "2179-06-30", "acc")
    conn.commit()
    tax = _bonus_items(conn, aid)[("income_tax", "u1")]
    W.mark_remitted(conn, [tax["id"]], "2179-07-08")
    conn.execute("UPDATE vouchers_all SET voided_at='2179-06-20T00:00:00' WHERE id=?", (vid,))
    conn.commit()
    E.run(conn, "2179-06-01", "2179-06-30", "acc")
    conn.commit()
    assert set(_bonus_items(conn, aid)) == {("income_tax", "u1")}                          # 未繳庫的補充保費移除；已繳庫的所得稅保留
