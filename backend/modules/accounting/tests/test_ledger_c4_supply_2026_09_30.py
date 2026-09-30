# -*- coding: utf-8 -*-
"""總帳 C4 · supply 事件提供者：進貨入庫 E08、進貨發票進項稅額 E08b、進貨付款 E09；會計補登 input_tax／invoice_date 覆寫估算。
反向控制：成本 0 的批次不入帳並 notice；沒發票號碼就沒有 E08b 與稅額；補登稅額同步調整 E09 的應付與銀行；補登壞值忽略；引擎整合冪等。
"""
import pytest

import db
from modules.accounting.ledger import contract as C
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import roles as ROLES
from modules.supply import gl_events as G

_N = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


def _batch(conn, qty=3, cost=1000, invoice_no="", paid_at="", created="2175-05-10T09:00:00", bank=""):
    _N[0] += 1
    part = "P-C4-%d-%d" % (id(_N), _N[0])
    batch = "PO-C4-%d-%d" % (id(_N), _N[0])
    conn.execute("INSERT OR IGNORE INTO parts(part_no, name, cost) VALUES (?,?,?)", (part, "測試料件", cost))
    conn.execute("INSERT INTO stock_batches(batch_no, part_no, supplier_name, invoice_no, is_paid, paid_at, paid_bank_account_code, created_at) "
                 "VALUES (?,?,?,?,?,?,?,?)", (batch, part, "甲供應商", invoice_no, 1 if paid_at else 0, paid_at, bank, created))
    for i in range(qty):
        conn.execute("INSERT INTO stock_items(part_no, serial_no, status, batch_no, cost, created_at) VALUES (?,?,?,?,?,?)",
                     (part, "%s-SN%d" % (batch, i), "in_stock", batch, cost, created))
    conn.commit()
    return batch


def _by(res, code, key):
    return [e for e in res["events"] if e["event_code"] == code and e["source_key"] == key]


def _lines(ev):
    return [(l["role"], l["side"], l["amount"]) for l in ev["lines"]]


def test_e08_receipt_without_invoice(conn):
    b = _batch(conn)
    res = G.gl_events("2175-05-01", "2175-05-31")
    (ev,) = _by(res, "E08", b)
    assert _lines(ev) == [("INVENTORY", "D", 3000), ("AP", "C", 3000)] and ev["event_date"] == "2175-05-10" and C.validate_event(ev) == []
    assert not _by(res, "E08b", b) and not _by(res, "E09", b)                     # 沒發票號碼、沒付款


def test_e08b_estimated_tax_when_invoice_no_present(conn):
    b = _batch(conn, invoice_no="AB12345678")
    res = G.gl_events("2175-05-01", "2175-05-31")
    (ev,) = _by(res, "E08b", b)
    assert _lines(ev) == [("INPUT_TAX", "D", 150), ("AP", "C", 150)] and ev["tax_code"] == "IN-5" and ev["meta"]["tax_estimated"] is True
    assert C.validate_event(ev) == [] and "估計" in res["notice"]


def test_e09_payment_includes_tax_and_bank_account(conn):
    b = _batch(conn, invoice_no="AB12345678", paid_at="2175-05-20", bank="1113")
    res = G.gl_events("2175-05-01", "2175-05-31")
    (ev,) = _by(res, "E09", b)
    assert _lines(ev) == [("AP", "D", 3150), ("BANK", "C", 3150)] and ev["lines"][1]["account_code"] == "1113" and ev["event_date"] == "2175-05-20"


def test_zero_cost_batch_is_reported_not_posted(conn):
    b = _batch(conn, cost=0)
    res = G.gl_events("2175-05-01", "2175-05-31")
    assert not _by(res, "E08", b) and "成本合計為 0" in res["notice"]


def test_windows_payment_in_later_month(conn):
    b = _batch(conn, invoice_no="AB12345678", paid_at="2175-06-05")
    may, june = G.gl_events("2175-05-01", "2175-05-31"), G.gl_events("2175-06-01", "2175-06-30")
    assert _by(may, "E08", b) and not _by(may, "E09", b)
    assert _by(june, "E09", b) and not _by(june, "E08", b)


def _annotate(conn, source_type, key, field, value):
    conn.execute("INSERT INTO gl_source_annotations(source_type, source_key, field, value) VALUES (?,?,?,?)", (source_type, key, field, value))
    conn.commit()


def test_annotation_overrides_tax_and_payment_follows(conn):
    b = _batch(conn, invoice_no="AB12345678", paid_at="2175-05-20")
    _annotate(conn, "stock_batch_invoice", b, "input_tax", "140")
    evs = C.collect("2175-05-01", "2175-05-31", conn=conn)["events"]
    inv = [e for e in evs if e["event_code"] == "E08b" and e["source_key"] == b][0]
    pay = [e for e in evs if e["event_code"] == "E09" and e["source_key"] == b][0]
    assert _lines(inv) == [("INPUT_TAX", "D", 140), ("AP", "C", 140)] and inv["meta"]["tax_annotated"] is True
    assert _lines(pay) == [("AP", "D", 3140), ("BANK", "C", 3140)] and pay["meta"]["tax_annotated"] is True
    assert C.validate_event(pay) == []


def test_annotation_invoice_date_moves_the_e08b_date_only(conn):
    b = _batch(conn, invoice_no="AB12345678")
    _annotate(conn, "stock_batch_invoice", b, "invoice_date", "2175-05-28")
    evs = C.collect("2175-05-01", "2175-05-31", conn=conn)["events"]
    assert [e for e in evs if e["event_code"] == "E08b" and e["source_key"] == b][0]["event_date"] == "2175-05-28"
    assert [e for e in evs if e["event_code"] == "E08" and e["source_key"] == b][0]["event_date"] == "2175-05-10"


def test_bad_annotation_values_are_ignored_and_marked(conn):
    b = _batch(conn, invoice_no="AB12345678", paid_at="2175-05-20")
    _annotate(conn, "stock_batch_invoice", b, "input_tax", "abc")
    _annotate(conn, "stock_batch_invoice", b, "invoice_date", "not-a-date")
    evs = C.collect("2175-05-01", "2175-05-31", conn=conn)["events"]
    inv = [e for e in evs if e["event_code"] == "E08b" and e["source_key"] == b][0]
    pay = [e for e in evs if e["event_code"] == "E09" and e["source_key"] == b][0]
    assert _lines(inv)[0] == ("INPUT_TAX", "D", 150) and "annotation_ignored" in inv["meta"] and inv["event_date"] == "2175-05-10"
    assert _lines(pay)[0] == ("AP", "D", 3150) and "annotation_ignored" in pay["meta"]


def test_engine_with_real_supply_provider_end_to_end(conn):
    _batch(conn, invoice_no="AB12345678", paid_at="2175-05-20")
    r = E.run(conn, "2175-05-01", "2175-05-31", "acc")
    conn.commit()
    assert r["sources"]["supply"] == "ok" and r["stats"]["created"] >= 3
    again = E.run(conn, "2175-05-01", "2175-05-31", "acc")
    assert again["stats"]["created"] == 0 and again["stats"]["drift"] == 0
