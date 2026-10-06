# -*- coding: utf-8 -*-
"""站內通知基礎（第44班）：`link` 欄位、`_notify(…, link=)`、核准類去重、`/api/notifications/mine` 帶 link。"""
import threading

import db
from helpers.audit import _notify


def _rows(user=None):
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM notifications" + (" WHERE username=?" if user else "") + " ORDER BY id", (user,) if user else ())]
    finally:
        conn.close()


def test_migration_adds_link_column_and_indexes_idempotently(client):
    from core import migrations as M
    conn = db.get_db()
    try:
        for fn in M._PENDING:
            fn(conn)
            fn(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(notifications)")}
        idx = {r[1] for r in conn.execute("PRAGMA index_list(notifications)")}
    finally:
        conn.close()
    assert "link" in cols and {"idx_notifications_user_created", "idx_notifications_created"} <= idx


def test_notify_stores_link_and_old_five_argument_calls_still_work(client):
    _notify("bell_a", "approval_request", "Q-1", "Q-1", "請簽核", "quotation-edit.html?no=Q-1")
    _notify("bell_a", "info", "x", "x", "舊式五參數呼叫")
    rows = _rows("bell_a")
    assert [r["link"] for r in rows] == ["quotation-edit.html?no=Q-1", ""]


def test_approved_rows_are_deduped_per_type_ref_and_user_others_are_not(client):
    for _ in range(3):
        _notify("bell_b", "shipping_approved", "S-1", "S-1", "已核准", "shipping.html?no=S-1")
    _notify("bell_c", "shipping_approved", "S-1", "S-1", "已核准", "shipping.html?no=S-1")      # 另一個人 ⇒ 另一列
    _notify("bell_b", "shipping_approved", "S-2", "S-2", "已核准")                                # 另一張單 ⇒ 另一列
    for _ in range(2):
        _notify("bell_b", "approval_request", "S-1", "S-1", "待簽核")                              # 非核准類 ⇒ 照舊每次一列
    got = [(r["username"], r["type"], r["ref_id"]) for r in _rows()]
    assert got.count(("bell_b", "shipping_approved", "S-1")) == 1
    assert ("bell_c", "shipping_approved", "S-1") in got and ("bell_b", "shipping_approved", "S-2") in got
    assert got.count(("bell_b", "approval_request", "S-1")) == 2


def test_approved_dedupe_is_race_safe(client):
    ts = [threading.Thread(target=_notify, args=("bell_r", "payment_request_approved", "P-9", "P-9", "已核准")) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len([r for r in _rows("bell_r") if r["type"] == "payment_request_approved"]) == 1


def test_mine_endpoint_returns_link_and_only_own_rows(client, make_user):
    make_user(username="bell_u1", role="viewer")
    make_user(username="bell_u2", role="viewer")
    _notify("bell_u1", "info", "z", "z", "給 u1", "customers.html")
    _notify("bell_u2", "info", "z", "z", "給 u2", "customers.html")
    r = client.post("/api/auth/login", json={"username": "bell_u1", "password": "Test-Pass-123"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    items = client.get("/api/notifications/mine", headers=h).json()["items"]
    assert [i["message"] for i in items] == ["給 u1"] and items[0]["link"] == "customers.html"
