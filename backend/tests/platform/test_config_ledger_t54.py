# -*- coding: utf-8 -*-
"""helper:config_ledger 的契約題（單位卡 [契約題]）：公開介面、事件狀態機、只增不改不刪、雙人核准、同交易稽核。
每一條都附正對照——拿掉被守的行為，題目要變紅。"""
import sqlite3
from datetime import datetime, timedelta

import pytest

from db import get_db
from helpers import config_ledger as L

DOMAIN = "setting:zz_ledger_contract"


@pytest.fixture()
def conn(client):
    c = get_db()
    yield c
    c.rollback()
    c.close()


def _later(days=8):
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")


def _pending(conn, approvals=0, actor="lc_a"):
    out = L.record(conn, DOMAIN, "k", [{"field": "f", "old": 1, "new": 2}], "測試", actor, risk="ops",
                   effective_at=_later(), approvals_required=approvals, audit_action="setting.test.pending")
    return out["ids"][0]


def test_public_interface_names_exist():
    for name in ("EVENTS", "HIGH_RISK", "RISKS", "audit_event", "record", "history", "pending", "approve", "cancel",
                 "supersede", "activate_due", "in_effect", "state_of", "cancel_pending_for", "register_domain",
                 "domains", "snapshot_version", "restore_version"):
        assert hasattr(L, name), name
    assert set(L.EVENTS) == {"pending", "approved", "activated", "cancelled", "superseded"}


def test_no_real_change_writes_nothing(conn):
    out = L.record(conn, DOMAIN, "k", [{"field": "f", "old": 1, "new": 1}], "沒變", "lc_a")
    assert out["ids"] == [] and out["audit_id"] is None


def test_immediate_has_no_event_and_is_in_effect(conn):
    out = L.record(conn, DOMAIN, "k", [{"field": "f", "old": 1, "new": 2}], "立即", "lc_a")
    cid = out["ids"][0]
    assert L.state_of(conn, cid) == "immediate"
    assert L.in_effect(L.history(conn, DOMAIN, "k")[0]) is True


def test_pending_not_in_effect_until_due_then_activates(conn):
    cid = _pending(conn)
    row = [r for r in L.history(conn, DOMAIN, "k") if r["id"] == cid][0]
    assert row["state"] == "pending" and L.in_effect(row) is False
    assert L.in_effect(row, _later(30)) is True                 # 讀取時判斷，不靠排程
    assert L.activate_due(conn, _later(30), DOMAIN) == [cid]
    assert L.state_of(conn, cid) == "activated"


def test_cancel_and_supersede_only_work_on_pending(conn):
    a, b = _pending(conn), _pending(conn)
    assert L.cancel(conn, a, "lc_a") is True and L.cancel(conn, a, "lc_a") is False
    assert L.supersede(conn, b, "lc_a") is True and L.supersede(conn, b, "lc_a") is False
    assert L.state_of(conn, a) == "cancelled" and L.state_of(conn, b) == "superseded"
    assert L.in_effect({"state": "cancelled"}) is False and L.in_effect({"state": "superseded"}) is False


def test_two_person_approval_rules(conn):
    cid = _pending(conn, approvals=1, actor="lc_a")
    row = [r for r in L.history(conn, DOMAIN, "k") if r["id"] == cid][0]
    assert L.in_effect(row, _later(30)) is False                # 票數不夠 ⇒ 到時間也不生效
    assert L.approve(conn, cid, "lc_a")["ok"] is False          # 申請人不能核准自己的
    assert L.approve(conn, cid, "lc_b")["ok"] is True
    assert L.approve(conn, cid, "lc_b")["ok"] is False          # 同一人不能投兩次
    row = [r for r in L.history(conn, DOMAIN, "k") if r["id"] == cid][0]
    assert L.in_effect(row, _later(30)) is True


def test_record_writes_audit_in_callers_transaction(conn):
    n0 = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='setting.test.pending'").fetchone()[0]
    _pending(conn)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='setting.test.pending'").fetchone()[0] == n0 + 1
    conn.rollback()                                             # 呼叫端回復 ⇒ 明細與稽核一起消失
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='setting.test.pending'").fetchone()[0] == n0
    assert conn.execute("SELECT COUNT(*) FROM config_changes WHERE domain=?", (DOMAIN,)).fetchone()[0] == 0


def test_audit_event_writes_one_row_without_commit(conn):
    n0 = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='setting.test.event'").fetchone()[0]
    L.audit_event(conn, "lc_a", "setting.test.event", "k", {"x": 1})
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='setting.test.event'").fetchone()[0] == n0 + 1
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='setting.test.event'").fetchone()[0] == n0


def test_ledger_tables_are_append_only(conn):
    cid = _pending(conn)
    conn.commit()
    try:
        for sql in ("UPDATE config_changes SET reason='x' WHERE id=%d" % cid,
                    "DELETE FROM config_changes WHERE id=%d" % cid,
                    "UPDATE config_change_events SET reason='x' WHERE change_id=%d" % cid,
                    "DELETE FROM config_change_events WHERE change_id=%d" % cid):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)
    finally:
        pass


def test_invalid_domain_and_risk_rejected(conn):
    with pytest.raises(ValueError):
        L.record(conn, "Bad Domain", "k", [{"field": "f", "old": 1, "new": 2}], "x", "lc_a")
    with pytest.raises(ValueError):
        L.record(conn, DOMAIN, "k", [{"field": "f", "old": 1, "new": 2}], "x", "lc_a", risk="nope")
