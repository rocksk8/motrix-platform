# -*- coding: utf-8 -*-
"""總帳 C5 · 營業稅 401：由總帳分錄彙總（稅碼＋科目類別）、對帳、警示、稅額結轉草稿（E14）、API 與 Excel。
反向控制：未過帳的傳票不算；發票對不上 ⇒ 不可產生結轉；估計稅額／免稅銷售警示；已過帳的結轉傳票不可重做；留抵與用完留抵的分錄平衡。
"""
import io
import json

import pytest
from openpyxl import load_workbook

import db
from core import registry
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import features as F
from modules.accounting.ledger import roles as ROLES
from modules.accounting.ledger import tax401 as T

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


def _ev(kind, date, **kw):
    _N[0] += 1
    key = "T401-%d-%d" % (id(_N), _N[0])
    if kind == "sale":
        lines = [{"role": "AR", "side": "D", "amount": 10500}, {"role": "REV_SALES", "side": "C", "amount": 10000}, {"role": "OUTPUT_TAX", "side": "C", "amount": 500}]
        e = {"source_type": "t_sale", "event_code": "E01", "tax_code": "OUT-5"}
    elif kind == "zero":
        lines = [{"role": "AR", "side": "D", "amount": 3000}, {"role": "REV_SALES", "side": "C", "amount": 3000}]
        e = {"source_type": "t_zero", "event_code": "E01", "tax_code": "OUT-0"}
    elif kind == "exempt":
        lines = [{"role": "AR", "side": "D", "amount": 800}, {"role": "REV_SALES", "side": "C", "amount": 800}]
        e = {"source_type": "t_ex", "event_code": "E01", "tax_code": "OUT-EX"}
    elif kind == "buy":
        lines = [{"role": "COST_PROJECT", "side": "D", "amount": 2000}, {"role": "INPUT_TAX", "side": "D", "amount": 100}, {"role": "AP", "side": "C", "amount": 2100}]
        e = {"source_type": "t_buy", "event_code": "E04", "tax_code": "IN-5"}
    elif kind == "bigbuy":
        lines = [{"role": "COST_PROJECT", "side": "D", "amount": 4000}, {"role": "INPUT_TAX", "side": "D", "amount": 200}, {"role": "AP", "side": "C", "amount": 4200}]
        e = {"source_type": "t_bigbuy", "event_code": "E04", "tax_code": "IN-5"}
    e.update({"source_key": key, "event_date": date, "doc_no": key, "case_no": "", "party": {"key": "12345678", "name": "甲"}, "mode": "snapshot", "lines": lines})
    e.update(kw)
    return e


def _run_and_post(conn, fake, events, start, end, post=True):
    fake["events"] = events
    E.run(conn, start, end, "acc")
    if post:
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE kind='auto' AND status='草稿' AND voided_at=''")
    conn.commit()


def test_bimonthly_periods():
    assert T.bimonthly(2178, 1) == ("2178-01-01", "2178-02-28")
    assert T.bimonthly(2176, 1) == ("2176-01-01", "2176-02-29")          # 閏年
    assert T.bimonthly(2178, 6) == ("2178-11-01", "2178-12-31")
    with pytest.raises(T.TaxError):
        T.bimonthly(2178, 7)


def test_summary_from_posted_lines_and_calc(conn, fake):
    _run_and_post(conn, fake, [_ev("sale", "2178-01-10"), _ev("zero", "2178-01-15"), _ev("buy", "2178-02-05")], "2178-01-01", "2178-02-28")
    s = T.summarize(conn, 2178, 1)
    by = {r["tax_code"]: r for r in s["rows"]}
    assert (by["OUT-5"]["amount"], by["OUT-5"]["tax"]) == (10000, 500) and by["OUT-0"]["zero_amount"] == 3000
    assert (by["IN-5"]["amount"], by["IN-5"]["tax"]) == (2000, 100)
    assert s["calc"] == {"101": 500, "107": 100, "108": 0, "110": 100, "111": 400, "112": 0, "25": 13000}
    assert s["reconciled"] is True and [c["ok"] for c in s["checks"][:2]] == [True, True]
    assert by["OUT-5"]["field_amt"] == "5" and by["IN-5"]["field_tax"] == "29"


def test_unposted_vouchers_are_not_counted(conn, fake):
    _run_and_post(conn, fake, [_ev("sale", "2178-01-10")], "2178-01-01", "2178-02-28", post=False)
    s = T.summarize(conn, 2178, 1)
    assert s["rows"] == [] and s["calc"]["101"] == 0


def test_invoice_comparison_ok_and_mismatch(conn, fake):
    _run_and_post(conn, fake, [_ev("sale", "2178-01-10")], "2178-01-01", "2178-02-28")
    ok = T.summarize(conn, 2178, 1, [{"invoiceDate": "2178-01-10", "amountPretax": 10000, "taxAmount": 500}])
    assert ok["reconciled"] is True and [c["ok"] for c in ok["checks"] if c["key"].startswith("invoices")] == [True, True]
    bad = T.summarize(conn, 2178, 1, [{"invoiceDate": "2178-01-10", "amountPretax": 10000, "taxAmount": 501}])
    assert bad["reconciled"] is False
    none = T.summarize(conn, 2178, 1, None)
    assert [c for c in none["checks"] if c["key"] == "invoices"][0]["ok"] is None and none["reconciled"] is True


def test_warnings_for_exempt_and_estimated_tax(conn, fake):
    est = _ev("buy", "2178-01-20")
    est["meta"] = {"tax_estimated": True}
    _run_and_post(conn, fake, [_ev("exempt", "2178-01-12"), est], "2178-01-01", "2178-02-28")
    keys = {w["key"] for w in T.summarize(conn, 2178, 1)["warnings"]}
    assert {"exempt", "estimated"} <= keys


def _settle(conn, y=2178, n=1):
    r = T.generate_settlement(conn, y, n, "acc")
    conn.commit()
    return r


def _vlines(conn, vid):
    return sorted((r["account_code"], r["debit"], r["credit"]) for r in conn.execute("SELECT account_code, debit, credit FROM voucher_lines WHERE voucher_id=?", (vid,)))


def test_settlement_payable_case_and_regenerate(conn, fake):
    _run_and_post(conn, fake, [_ev("sale", "2178-01-10"), _ev("buy", "2178-02-05")], "2178-01-01", "2178-02-28")
    r = _settle(conn)
    assert (r["payable"], r["carry_new"]) == (400, 0)
    assert _vlines(conn, r["voucher_id"]) == sorted([("2204", 500, 0), ("1268", 0, 100), ("2194", 0, 400)])
    row = conn.execute("SELECT * FROM gl_tax_settlements WHERE period_start='2178-01-01'").fetchone()
    assert (row["output_tax"], row["input_tax"], row["payable"], row["voucher_id"]) == (500, 100, 400, r["voucher_id"])
    r2 = _settle(conn)                                                       # 重建：舊草稿作廢
    assert r2["voucher_id"] != r["voucher_id"] and conn.execute("SELECT voided_at FROM vouchers_all WHERE id=?", (r["voucher_id"],)).fetchone()[0] != ""
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (r2["voucher_id"],))
    conn.commit()
    with pytest.raises(T.TaxError):
        T.generate_settlement(conn, 2178, 1, "acc")                           # 已過帳 ⇒ 不重做


def test_settlement_blocked_when_not_reconciled_or_empty(conn, fake):
    _run_and_post(conn, fake, [_ev("sale", "2178-01-10")], "2178-01-01", "2178-02-28")
    with pytest.raises(T.TaxError):
        T.generate_settlement(conn, 2178, 1, "acc", [{"invoiceDate": "2178-01-10", "amountPretax": 1, "taxAmount": 1}])
    with pytest.raises(T.TaxError):
        T.generate_settlement(conn, 2178, 3, "acc")                           # 沒有稅額的期別


def test_carry_forward_then_used_up_next_period(conn, fake):
    _run_and_post(conn, fake, [_ev("bigbuy", "2178-03-10")], "2178-03-01", "2178-04-30")           # 只有進項 200
    r1 = _settle(conn, 2178, 2)
    assert (r1["payable"], r1["carry_new"]) == (0, 200)
    assert _vlines(conn, r1["voucher_id"]) == sorted([("1268", 0, 200), ("1269", 200, 0)])
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (r1["voucher_id"],))
    conn.commit()
    _run_and_post(conn, fake, [_ev("sale", "2178-05-10")], "2178-05-01", "2178-06-30")            # 下期銷項 500
    s = T.summarize(conn, 2178, 3)
    assert s["calc"]["108"] == 200 and s["calc"]["111"] == 300 and s["reconciled"] is True         # 上期留抵被承接（結轉傳票不重複算進 101/107）
    r2 = _settle(conn, 2178, 3)
    assert (r2["payable"], r2["carry_new"]) == (300, 0)
    assert _vlines(conn, r2["voucher_id"]) == sorted([("2204", 500, 0), ("1269", 0, 200), ("2194", 0, 300)])


def test_api_flag_gate_summary_export_and_settlement(client, conn, fake, make_user):
    u, p = make_user(username="t401_admin%d" % id(client), role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    assert client.get("/api/ledger/tax401?year=2178&period=1", headers=h).status_code == 409           # 旗標預設關
    F.set_flag(conn, "tax401", True)
    conn.commit()
    _run_and_post(conn, fake, [_ev("sale", "2178-01-10"), _ev("buy", "2178-02-05")], "2178-01-01", "2178-02-28")
    r = client.get("/api/ledger/tax401?year=2178&period=1", headers=h)
    assert r.status_code == 200 and r.json()["calc"]["111"] == 400
    assert client.get("/api/ledger/tax401?year=2178&period=9", headers=h).status_code == 400
    x = client.get("/api/ledger/tax401/export?year=2178&period=1", headers=h)
    assert x.status_code == 200
    ws = load_workbook(io.BytesIO(x.content)).active
    assert any(c.value == "本期應實繳稅額" for row in ws.iter_rows() for c in row)
    s = client.post("/api/ledger/tax401/settlement", headers=h, json={"year": 2178, "period": 1})
    assert s.status_code == 200 and s.json()["payable"] == 400
    assert client.post("/api/ledger/tax401/settlement", headers=h, json={"year": 2178, "period": 4}).status_code == 400
