# -*- coding: utf-8 -*-
"""總帳 C3b · 既有傳票登記為原生事件（mode=native）與獎金 E07。
反向控制：native 事件不產生傳票、不被批次確認碰、不被當成來源消失；傳票作廢後不登記；改指向新傳票 ⇒ 舊列 superseded；契約驗證缺 native_voucher_id。
"""
import json
from datetime import datetime

import pytest

import db
from core import registry
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


def _voucher(conn, date="2173-06-10", amount=5000, origin="bonus_accrual"):
    v = registry.single_provider("voucher.draft")(
        conn, voucher_date=date, summary="獎金分潤", created_by="t", now="2173-06-10T00:00:00", origin=origin,
        lines=[{"account_code": "6111", "summary": "x", "debit": amount, "credit": 0},
               {"account_code": "2191", "summary": "x", "debit": 0, "credit": amount}])
    conn.commit()
    return v["id"]


def _award(conn, accrual=0, payment=0):
    _N[0] += 1
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO bonus_case_awards(quote_no, status, net_profit, rate_bp, split_json, pool_amount, created_by, created_at, updated_by, updated_at,"
        " accrual_voucher_id, payment_voucher_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("MQ-C3B-%d" % _N[0], "待發放", "1000", 1000, "{}", 100, "t", now, "t", now, accrual, payment))
    conn.commit()
    return cur.lastrowid


def _native(conn, key, vid, date="2173-06-10", code="E07a", src="bonus_accrual"):
    return {"source_type": src, "source_key": key, "event_code": code, "event_date": date, "mode": "native", "native_voucher_id": vid}


def test_contract_native_needs_voucher_id_and_no_lines():
    ok = _native(None, "1", 5)
    assert C.validate_event(ok) == []
    assert any("native_voucher_id" in p for p in C.validate_event(dict(ok, native_voucher_id=0)))
    assert any("native_voucher_id" in p for p in C.validate_event({k: v for k, v in ok.items() if k != "native_voucher_id"}))
    assert C.canonical_hash(ok) != C.canonical_hash(dict(ok, native_voucher_id=6))


def test_bonus_provider_emits_native_events_in_window(conn):
    va, vp = _voucher(conn), _voucher(conn, date="2173-07-02", origin="bonus_payment")
    aid = _award(conn, va, vp)
    june = G.gl_events("2173-06-01", "2173-06-30")
    (a,) = [e for e in june["events"] if e["event_code"] == "E07a" and e["source_key"] == str(aid)]
    assert a["mode"] == "native" and a["native_voucher_id"] == va and a["event_date"] == "2173-06-10"
    assert not [e for e in june["events"] if e["event_code"] == "E07b" and e["source_key"] == str(aid)]
    july = G.gl_events("2173-07-01", "2173-07-31")
    assert [e for e in july["events"] if e["event_code"] == "E07b" and e["source_key"] == str(aid)]


def test_voided_bonus_voucher_is_not_registered(conn):
    va = _voucher(conn)
    aid = _award(conn, va)
    conn.execute("UPDATE vouchers_all SET voided_at='2173-06-11T00:00:00' WHERE id=?", (va,))
    conn.commit()
    res = G.gl_events("2173-06-01", "2173-06-30")
    assert not [e for e in res["events"] if e["source_key"] == str(aid)]


def test_bonus_voucher_carries_origin(conn):
    va = _voucher(conn)
    assert conn.execute("SELECT origin FROM vouchers_all WHERE id=?", (va,)).fetchone()[0] == "bonus_accrual"


def test_engine_registers_native_without_creating_a_voucher(conn):
    va = _voucher(conn)
    aid = _award(conn, va)
    before = conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0]
    r = E.run(conn, "2173-06-01", "2173-06-30", "acc")
    conn.commit()
    assert r["stats"]["native"] >= 1 and conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0] == before
    row = conn.execute("SELECT status, voucher_id, amount FROM gl_source_events WHERE source_key=? AND event_code='E07a'", (str(aid),)).fetchone()
    assert (row["status"], row["voucher_id"], row["amount"]) == ("native", va, 5000)
    again = E.run(conn, "2173-06-01", "2173-06-30", "acc")
    conn.commit()
    assert again["stats"]["native"] == 0 and again["stats"]["created"] == 0 and again["stats"]["orphans"] == 0
    assert conn.execute("SELECT COUNT(*) FROM gl_source_events WHERE source_key=? AND event_code='E07a'", (str(aid),)).fetchone()[0] == 1


def test_native_repoints_to_new_voucher_and_supersedes_old(conn):
    va = _voucher(conn)
    aid = _award(conn, va)
    E.run(conn, "2173-06-01", "2173-06-30", "acc")
    conn.commit()
    conn.execute("UPDATE vouchers_all SET voided_at='2173-06-12T00:00:00' WHERE id=?", (va,))
    vb = _voucher(conn, amount=6000)
    conn.execute("UPDATE bonus_case_awards SET accrual_voucher_id=? WHERE id=?", (vb, aid))
    conn.commit()
    E.run(conn, "2173-06-01", "2173-06-30", "acc")
    conn.commit()
    rows = conn.execute("SELECT rev, status, voucher_id FROM gl_source_events WHERE source_key=? AND event_code='E07a' ORDER BY rev", (str(aid),)).fetchall()
    assert [(r["rev"], r["status"], r["voucher_id"]) for r in rows] == [(1, "superseded", va), (2, "native", vb)]


def test_native_vouchers_are_not_touched_by_batch_confirm(client, conn):
    va = _voucher(conn)
    _award(conn, va)
    E.run(conn, "2173-06-01", "2173-06-30", "acc")
    conn.commit()
    kind = conn.execute("SELECT kind FROM vouchers_all WHERE id=?", (va,)).fetchone()[0]
    assert kind not in ("auto", "reversal")                # 批次確認只處理 auto／reversal ⇒ 獎金傳票不會被整批送審／過帳
