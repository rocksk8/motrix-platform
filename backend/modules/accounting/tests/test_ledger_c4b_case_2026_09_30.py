# -*- coding: utf-8 -*-
"""總帳 C4b · case 事件提供者：額外支出 E11／E11b、叫料 E12／E12b；補登 input_tax 把未拆稅金額拆成成本＋進項稅額。
反向控制：未核准的額外支出不入帳；付款差額待審核不產生並 notice；補登不合理的稅額忽略並標記；沒日期的叫料明說不入帳；引擎整合冪等。
"""
import json

import pytest

import db
from modules.accounting.ledger import contract as C
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import roles as ROLES
from modules.case import gl_events as G

_N = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


def _quote(conn, orders=None):
    _N[0] += 1
    qn = "MQ-C4B-%d-%d" % (id(_N), _N[0])
    data = {"dealTag": "已成案", "caseRecord": {"materialOrders": orders or []}}
    conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (qn, "已送出", "測試客", "測試案", 0, 0, json.dumps(data, ensure_ascii=False), "2177-01-01T00:00:00", "2177-01-01T00:00:00", "已成案", "2177-01-01"))
    conn.commit()
    return qn


def _extra(conn, qn, total=1050, status="已核准", invoice_date="2177-02-10", paid_date="", actual=None, fee=0, review="", approved="2177-02-12"):
    appr = json.dumps({"steps": [{"approvedAt": approved}]}) if approved else "{}"
    cur = conn.execute(
        "INSERT INTO case_extra_expenses(quote_no, category, description, total_cost, expense_date, doc_no, status, approval_json, invoice_date, paid_date, "
        "remit_actual, remit_fee, remit_review, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (qn, "材料", "測試支出", total, "2177-02-01", "D-1", status, appr, invoice_date, paid_date, actual, fee, review, "2177-02-01T00:00:00"))
    conn.commit()
    return str(cur.lastrowid)


def _by(res, code, key):
    return [e for e in res["events"] if e["event_code"] == code and e["source_key"] == key]


def _lines(ev):
    return [(l["role"], l["side"], l["amount"]) for l in ev["lines"]]


def test_e11_approved_extra_expense_by_invoice_date(conn):
    qn = _quote(conn)
    k = _extra(conn, qn)
    res = G.gl_events("2177-02-01", "2177-02-28")
    (ev,) = _by(res, "E11", k)
    assert _lines(ev) == [("COST_PROJECT", "D", 1050), ("AP", "C", 1050)] and ev["case_no"] == qn and ev["event_date"] == "2177-02-10"
    assert C.validate_event(ev) == [] and ev["meta"]["tax_unsplit"] is True and "未拆稅" in res["notice"]


def test_e11_date_falls_back_to_approval_then_voucher_day(conn):
    qn = _quote(conn)
    a = _extra(conn, qn, invoice_date="")
    b = _extra(conn, qn, invoice_date="", approved="")
    res = G.gl_events("2177-02-01", "2177-02-28")
    assert _by(res, "E11", a)[0]["event_date"] == "2177-02-12" and _by(res, "E11", a)[0]["meta"]["date_estimated"] is True
    assert _by(res, "E11", b)[0]["event_date"] == "2177-02-01"


def test_unapproved_extra_expenses_do_not_post(conn):
    qn = _quote(conn)
    ks = [_extra(conn, qn, status=s) for s in ("草稿", "待審核", "簽核中", "已駁回")]
    res = G.gl_events("2177-02-01", "2177-02-28")
    assert not any(e["source_key"] in ks for e in res["events"])


def test_e11b_payment_with_fee_and_approved_difference(conn):
    qn = _quote(conn)
    k1 = _extra(conn, qn, paid_date="2177-02-20", fee=15)
    k2 = _extra(conn, qn, paid_date="2177-02-21", actual=1000, review="approved")
    res = G.gl_events("2177-02-01", "2177-02-28")
    assert _lines(_by(res, "E11b", k1)[0]) == [("AP", "D", 1050), ("FEE", "D", 15), ("BANK", "C", 1065)]
    assert _lines(_by(res, "E11b", k2)[0]) == [("AP", "D", 1050), ("EXP_OTHER", "C", 50), ("BANK", "C", 1000)]
    for k in (k1, k2):
        assert C.validate_event(_by(res, "E11b", k)[0]) == []


def test_e11b_pending_difference_is_not_guessed(conn):
    qn = _quote(conn)
    k = _extra(conn, qn, paid_date="2177-02-20", actual=900, review="pending")
    res = G.gl_events("2177-02-01", "2177-02-28")
    assert not _by(res, "E11b", k) and "尚未核可" in res["notice"] and _by(res, "E11", k)


def test_e12_material_order_and_payment(conn):
    qn = _quote(conn, [{"itemId": "m1", "itemName": "線材", "totalPrice": 2100, "invoiceDate": "2177-03-05", "paidStatus": "paid", "paidDate": "2177-03-20", "paidAmount": 2100},
                       {"itemId": "m2", "itemName": "無日期", "totalPrice": 500}])
    res = G.gl_events("2177-03-01", "2177-03-31")
    (a,) = _by(res, "E12", "%s::m1" % qn)
    assert _lines(a) == [("COST_PROJECT", "D", 2100), ("AP", "C", 2100)] and a["event_date"] == "2177-03-05"
    (p,) = _by(res, "E12b", "%s::m1" % qn)
    assert _lines(p) == [("AP", "D", 2100), ("BANK", "C", 2100)] and p["event_date"] == "2177-03-20"
    assert not _by(res, "E12", "%s::m2" % qn) and "沒有發票日也沒有付款日" in res["notice"]


def _annotate(conn, st, key, value):
    conn.execute("INSERT INTO gl_source_annotations(source_type, source_key, field, value) VALUES (?,?,'input_tax',?)", (st, key, value))
    conn.commit()


def test_annotation_splits_unsplit_extra_expense_and_material(conn):
    qn = _quote(conn, [{"itemId": "m1", "itemName": "線材", "totalPrice": 2100, "invoiceDate": "2177-03-05"}])
    k = _extra(conn, qn)
    _annotate(conn, "case_extra_expense", k, "50")
    _annotate(conn, "case_material_order", "%s::m1" % qn, "100")
    evs = C.collect("2177-02-01", "2177-03-31", conn=conn)["events"]
    e11 = [e for e in evs if e["event_code"] == "E11" and e["source_key"] == k][0]
    e12 = [e for e in evs if e["event_code"] == "E12" and e["source_key"] == "%s::m1" % qn][0]
    assert _lines(e11) == [("COST_PROJECT", "D", 1000), ("INPUT_TAX", "D", 50), ("AP", "C", 1050)] and e11["meta"]["tax_annotated"] is True
    assert _lines(e12) == [("COST_PROJECT", "D", 2000), ("INPUT_TAX", "D", 100), ("AP", "C", 2100)]
    assert C.validate_event(e11) == [] and C.validate_event(e12) == []


def test_unreasonable_annotation_is_ignored_and_marked(conn):
    qn = _quote(conn)
    k = _extra(conn, qn)
    _annotate(conn, "case_extra_expense", k, "2000")                         # 稅額比成本還大
    e11 = [e for e in C.collect("2177-02-01", "2177-02-28", conn=conn)["events"] if e["event_code"] == "E11" and e["source_key"] == k][0]
    assert _lines(e11) == [("COST_PROJECT", "D", 1050), ("AP", "C", 1050)] and "annotation_ignored" in e11["meta"]


def test_engine_with_real_case_provider_end_to_end(conn):
    qn = _quote(conn)
    _extra(conn, qn, paid_date="2177-02-20")
    r = E.run(conn, "2177-02-01", "2177-02-28", "acc")
    conn.commit()
    assert r["sources"]["case"] == "ok" and r["stats"]["created"] >= 2
    again = E.run(conn, "2177-02-01", "2177-02-28", "acc")
    assert again["stats"]["created"] == 0 and again["stats"]["drift"] == 0
