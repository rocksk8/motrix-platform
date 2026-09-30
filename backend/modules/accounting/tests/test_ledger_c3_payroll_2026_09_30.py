# -*- coding: utf-8 -*-
"""總帳 C3 · payroll 事件提供者：勞報單應付 E06（簽回後）與付款 E06b（已付款）。
反向控制：草稿／已匯出不入帳；退回簽回⇒事件消失⇒引擎反向；扣繳大於給付不產生；實付矛盾以給付－扣繳平帳並 notice；不帶身分證字號。
"""
import pytest

import db
from modules.accounting.ledger import contract as C
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import roles as ROLES
from modules.payroll import gl_events as G

_N = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


def _slip(conn, status="已簽回", gross=10000, tax=1000, nhi=211, net=None, slip_date="2172-04-10", signed_at="2172-04-12T09:00:00",
          payment_date="", name="王小明"):
    _N[0] += 1
    no = "LB-C3-%d" % _N[0]
    net = gross - tax - nhi if net is None else net
    cid = conn.execute("INSERT INTO contractors(name, id_number) VALUES (?,?)", (name, "A123456789")).lastrowid
    conn.execute(
        "INSERT INTO payslips(slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, "
        "slip_date, status, signed_at, payment_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (no, cid, name, "9A", gross, tax, nhi, net, slip_date, status, signed_at, payment_date))
    conn.commit()
    return no


def _by(res, code, key):
    return [e for e in res["events"] if e["event_code"] == code and e["source_key"] == key]


def _lines(ev):
    return [(l["role"], l["side"], l["amount"]) for l in ev["lines"]]


def test_e06_accrual_after_signing(conn):
    no = _slip(conn)
    res = G.gl_events("2172-04-01", "2172-04-30")
    (ev,) = _by(res, "E06", no)
    assert _lines(ev) == [("EXP_LABOR", "D", 10000), ("WITHHOLD_TAX", "C", 1000), ("WITHHOLD_NHI", "C", 211), ("OTHER_PAYABLE", "C", 8789)]
    assert ev["event_date"] == "2172-04-10" and ev["doc_no"] == no and C.validate_event(ev) == []
    assert not _by(res, "E06b", no)


def test_party_has_no_national_id(conn):
    no = _slip(conn)
    (ev,) = _by(G.gl_events("2172-04-01", "2172-04-30"), "E06", no)
    assert ev["party"]["key"].startswith("C") and ev["party"]["name"] == "王小明"


def test_draft_and_exported_do_not_post(conn):
    a, b, c = _slip(conn, status="草稿"), _slip(conn, status="已匯出"), _slip(conn, status="已作廢")
    res = G.gl_events("2172-04-01", "2172-04-30")
    assert not any(e["source_key"] in (a, b, c) for e in res["events"])


def test_zero_withholding_has_no_withhold_lines(conn):
    no = _slip(conn, gross=5000, tax=0, nhi=0)
    (ev,) = _by(G.gl_events("2172-04-01", "2172-04-30"), "E06", no)
    assert _lines(ev) == [("EXP_LABOR", "D", 5000), ("OTHER_PAYABLE", "C", 5000)]


def test_withholding_larger_than_gross_is_not_posted(conn):
    no = _slip(conn, gross=100, tax=90, nhi=50, net=0)
    res = G.gl_events("2172-04-01", "2172-04-30")
    assert not _by(res, "E06", no) and no in res["notice"]


def test_inconsistent_net_is_balanced_and_reported(conn):
    no = _slip(conn, net=8000)
    res = G.gl_events("2172-04-01", "2172-04-30")
    (ev,) = _by(res, "E06", no)
    assert ev["lines"][-1]["amount"] == 8789 and "不一致" in res["notice"] and C.validate_event(ev) == []


def test_missing_slip_date_falls_back_to_signed_date(conn):
    no = _slip(conn, slip_date="", signed_at="2172-04-15T10:00:00")
    res = G.gl_events("2172-04-01", "2172-04-30")
    (ev,) = _by(res, "E06", no)
    assert ev["event_date"] == "2172-04-15" and ev["meta"]["date_from_signed"] is True and "沒有勞報日期" in res["notice"]


def test_e06b_payment_and_missing_payment_date(conn):
    paid = _slip(conn, status="已付款", payment_date="2172-04-25")
    nodate = _slip(conn, status="已付款", payment_date="")
    res = G.gl_events("2172-04-01", "2172-04-30")
    (pay,) = _by(res, "E06b", paid)
    assert _lines(pay) == [("OTHER_PAYABLE", "D", 8789), ("BANK", "C", 8789)] and pay["event_date"] == "2172-04-25"
    assert not _by(res, "E06b", nodate) and "沒有付款日期" in res["notice"]
    assert _by(res, "E06", nodate)                                                      # 應付照樣入帳


def test_payment_in_later_month_accrual_in_earlier(conn):
    no = _slip(conn, status="已付款", payment_date="2172-05-05")
    apr = G.gl_events("2172-04-01", "2172-04-30")
    may = G.gl_events("2172-05-01", "2172-05-31")
    assert _by(apr, "E06", no) and not _by(apr, "E06b", no)
    assert _by(may, "E06b", no) and not _by(may, "E06", no)


def test_engine_end_to_end_and_unsign_reverses(conn):
    no = _slip(conn)
    r = E.run(conn, "2172-04-01", "2172-04-30", "acc")
    conn.commit()
    assert r["sources"]["payroll"] == "ok" and r["stats"]["created"] >= 1
    assert E.run(conn, "2172-04-01", "2172-04-30", "acc")["stats"]["created"] == 0
    conn.execute("UPDATE payslips SET status='已匯出', signed_at='' WHERE slip_no=?", (no,))       # 退回簽回
    conn.commit()
    again = E.run(conn, "2172-04-01", "2172-04-30", "acc")
    conn.commit()
    assert again["stats"]["orphans"] >= 1
