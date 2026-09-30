# -*- coding: utf-8 -*-
"""總帳 C2 · subcontract 事件提供者：承攬商發票 E04、匯款 E05、個人點工 E05b；會計補登進項稅額（gl_source_annotations）覆寫估算。
反向控制：待審核差額不產生事件並 notice；未驗收／無發票日不產生 E04；補登值壞掉忽略並標記；整合走真的 registry 與引擎（冪等）。
"""
import json

import pytest

import db
from modules.accounting.ledger import contract as C
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import roles as ROLES
from modules.subcontract import gl_events as G

_N = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


def _vendor(conn):
    _N[0] += 1
    cur = conn.execute("INSERT INTO vendor_contractors(name, tax_id, data_json, active) VALUES (?,?,?,1)",
                       ("乙工程行%d" % _N[0], "8765%04d" % _N[0], "{}"))
    return cur.lastrowid


def _dispatch(conn, quote, total=10000, rate=0.05, status="accepted", invoice_date="2171-03-10", invoice_no="ZZ00000001"):
    cur = conn.execute(
        "INSERT INTO contractor_dispatches(quote_no, vendor_id, dispatch_date, total_amount, tax_rate, status, invoice_no, invoice_date) "
        "VALUES (?,?,?,?,?,?,?,?)", (quote, _vendor(conn), "2171-03-01", total, rate, status, invoice_no, invoice_date))
    return cur.lastrowid


def _voucher(conn, did, quote, grand=10500, personnel=0, paid_at="2171-03-20", actual=None, fee=0, review="", bank="1113"):
    _N[0] += 1
    no = "PV-C2-%d" % _N[0]
    snap = {"vendorName": "乙工程行", "vendorTaxId": "87650001", "grandTotal": grand, "personnelTotal": personnel}
    conn.execute(
        "INSERT INTO contractor_payment_vouchers(voucher_no, dispatch_id, quote_no, status, snapshot_json, is_paid, paid_at, "
        "paid_bank_account_code, remit_actual, remit_fee, remit_review) VALUES (?,?,?,?,?,1,?,?,?,?,?)",
        (no, did, quote, "已核可", json.dumps(snap, ensure_ascii=False), paid_at, bank, actual, fee, review))
    conn.commit()
    return no


def _by(res, code, key_part=""):
    return [e for e in res["events"] if e["event_code"] == code and key_part in e["source_key"]]


def _lines(ev):
    return [(l["role"], l["side"], l["amount"]) for l in ev["lines"]]


def test_e04_invoice_estimated_tax(conn):
    did = _dispatch(conn, "MQ-C2-A")
    conn.commit()
    res = G.gl_events("2171-03-01", "2171-03-31")
    (ev,) = [e for e in _by(res, "E04") if e["source_key"] == str(did)]
    assert ev["event_date"] == "2171-03-10" and ev["doc_no"] == "ZZ00000001" and ev["tax_code"] == "IN-5"
    assert _lines(ev) == [("COST_PROJECT", "D", 10000), ("INPUT_TAX", "D", 500), ("AP", "C", 10500)]
    assert ev["meta"]["tax_estimated"] is True and C.validate_event(ev) == []
    assert "估算" in res["notice"]


def test_e04_skips_unaccepted_and_undated(conn):
    a = _dispatch(conn, "MQ-C2-B", status="draft")
    b = _dispatch(conn, "MQ-C2-B", invoice_date="")
    c = _dispatch(conn, "MQ-C2-B", invoice_date="2171-04-02")             # 窗外
    conn.commit()
    keys = {e["source_key"] for e in _by(G.gl_events("2171-03-01", "2171-03-31"), "E04")}
    assert not ({str(a), str(b), str(c)} & keys)


def test_e04_zero_tax_rate_has_no_input_tax_line(conn):
    did = _dispatch(conn, "MQ-C2-C", rate=0)
    conn.commit()
    (ev,) = [e for e in _by(G.gl_events("2171-03-01", "2171-03-31"), "E04") if e["source_key"] == str(did)]
    assert _lines(ev) == [("COST_PROJECT", "D", 10000), ("AP", "C", 10000)] and ev["tax_code"] == "IN-EX"


def test_e05_payment_with_fee_and_bank_account(conn):
    did = _dispatch(conn, "MQ-C2-D")
    vn = _voucher(conn, did, "MQ-C2-D", fee=30)
    res = G.gl_events("2171-03-01", "2171-03-31")
    (ev,) = _by(res, "E05", vn)
    assert _lines(ev) == [("AP", "D", 10500), ("FEE", "D", 30), ("BANK", "C", 10530)]
    assert ev["lines"][-1]["account_code"] == "1113" and ev["event_date"] == "2171-03-20" and C.validate_event(ev) == []
    assert not _by(res, "E05b", vn)


def test_e05_approved_difference_goes_to_other_expense(conn):
    d1, d2 = _dispatch(conn, "MQ-C2-E"), _dispatch(conn, "MQ-C2-E")
    over = _voucher(conn, d1, "MQ-C2-E", actual=10600, review="approved")
    under = _voucher(conn, d2, "MQ-C2-E", actual=10400, review="approved")
    res = G.gl_events("2171-03-01", "2171-03-31")
    assert _lines(_by(res, "E05", over)[0]) == [("AP", "D", 10500), ("EXP_OTHER", "D", 100), ("BANK", "C", 10600)]
    assert _lines(_by(res, "E05", under)[0]) == [("AP", "D", 10500), ("EXP_OTHER", "C", 100), ("BANK", "C", 10400)]
    for v in (over, under):
        assert C.validate_event(_by(res, "E05", v)[0]) == []


def test_e05_pending_difference_is_not_guessed(conn):
    did = _dispatch(conn, "MQ-C2-F")
    vn = _voucher(conn, did, "MQ-C2-F", actual=10000, review="pending")
    res = G.gl_events("2171-03-01", "2171-03-31")
    assert _by(res, "E05", vn) == [] and "尚未核可" in res["notice"]


def test_e05b_personnel_balances_ap_and_warns(conn):
    did = _dispatch(conn, "MQ-C2-G")
    vn = _voucher(conn, did, "MQ-C2-G", grand=13500, personnel=3000)
    res = G.gl_events("2171-03-01", "2171-03-31")
    (p,) = _by(res, "E05b", vn)
    assert _lines(p) == [("COST_PROJECT", "D", 3000), ("AP", "C", 3000)] and p["meta"]["no_withholding"] is True
    assert "未扣繳" in res["notice"]
    assert C.validate_event(_by(res, "E05", vn)[0]) == []


def test_uninvoiced_payment_is_reported(conn):
    did = _dispatch(conn, "MQ-C2-H", invoice_date="")
    vn = _voucher(conn, did, "MQ-C2-H")
    res = G.gl_events("2171-03-01", "2171-03-31")
    assert _by(res, "E05", vn) and "沒有登錄發票日" in res["notice"]


def _annotate(conn, did, value):
    conn.execute("INSERT INTO gl_source_annotations(source_type, source_key, field, value) VALUES ('contractor_dispatch', ?, 'input_tax', ?)",
                 (str(did), value))
    conn.commit()


def test_annotation_overrides_estimated_tax(conn):
    did = _dispatch(conn, "MQ-C2-I")
    _annotate(conn, did, "480")
    ev = [e for e in C.collect("2171-03-01", "2171-03-31", conn=conn)["events"] if e["event_code"] == "E04" and e["source_key"] == str(did)][0]
    assert _lines(ev) == [("COST_PROJECT", "D", 10000), ("INPUT_TAX", "D", 480), ("AP", "C", 10480)]
    assert ev["meta"]["tax_estimated"] is False and ev["meta"]["tax_annotated"] is True
    plain = [e for e in C.collect("2171-03-01", "2171-03-31")["events"] if e["source_key"] == str(did)][0]
    assert ev["content_hash"] != plain["content_hash"]                # 補登改變內容 ⇒ 已過帳的會被引擎偵測為 drift


def test_annotation_zero_removes_tax_line_and_bad_value_is_ignored(conn):
    d0, d1 = _dispatch(conn, "MQ-C2-J"), _dispatch(conn, "MQ-C2-J")
    _annotate(conn, d0, "0")
    _annotate(conn, d1, "abc")
    evs = {e["source_key"]: e for e in C.collect("2171-03-01", "2171-03-31", conn=conn)["events"] if e["event_code"] == "E04"}
    assert _lines(evs[str(d0)]) == [("COST_PROJECT", "D", 10000), ("AP", "C", 10000)]
    assert _lines(evs[str(d1)])[1] == ("INPUT_TAX", "D", 500) and "annotation_ignored" in evs[str(d1)]["meta"]


def test_engine_with_real_subcontract_provider_end_to_end(conn):
    did = _dispatch(conn, "MQ-C2-K")
    _voucher(conn, did, "MQ-C2-K", fee=30)
    r = E.run(conn, "2171-03-01", "2171-03-31", "acc")
    conn.commit()
    assert r["sources"]["subcontract"] == "ok" and r["stats"]["created"] >= 2
    again = E.run(conn, "2171-03-01", "2171-03-31", "acc")
    assert again["stats"]["created"] == 0 and again["stats"]["drift"] == 0
