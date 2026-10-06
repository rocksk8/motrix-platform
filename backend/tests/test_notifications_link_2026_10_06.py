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


# ── 連結驗證、金額遮罩、90 天清理、核准通知（第44班）────────────────────────────────

import pytest  # noqa: E402


@pytest.mark.parametrize("bad", ["http://evil.example/a.html", "//evil/a.html", "../a.html", "javascript:alert(1)", "a.html?x=<s>", "a.html#h", "/pages/a.html", "a b.html"])
def test_invalid_links_are_dropped_but_the_notification_is_still_written(client, bad):
    _notify("bell_l", "info", "r", "r", "壞連結", bad)
    r = _rows("bell_l")
    assert len(r) == 1 and r[0]["link"] == ""


def test_money_in_message_is_masked_for_recipients_without_financial_visibility(client, make_user):
    for name, role in (("bm_viewer", "viewer"), ("bm_admin", "admin"), ("bm_sales", "sales"), ("bm_fin", "finance"), ("bm_sa", "superadmin")):
        make_user(username=name, role=role)
        _notify(name, "info", "k", "金額 NT$ 9,999 單", "差額 NT$ 1,300.5；實付 2,000 元；單號 MQ-1；共 3 元件")
    got = {r["username"]: r for r in _rows() if r["username"].startswith("bm_")}
    for u in ("bm_viewer", "bm_admin", "bm_sales"):
        assert "NT$" not in got[u]["message"] and "2,000" not in got[u]["message"] and "（金額略）" in got[u]["message"], got[u]
        assert "MQ-1" in got[u]["message"] and "3 元件" in got[u]["message"], "非金額文字不能被誤遮"
        assert "9,999" not in got[u]["ref_label"]
    for u in ("bm_fin", "bm_sa"):
        assert "NT$ 1,300.5" in got[u]["message"] and "2,000 元" in got[u]["message"] and "9,999" in got[u]["ref_label"]


def test_purge_old_notifications_deletes_read_and_unread_older_than_90_days_in_batches(client, monkeypatch):
    from datetime import datetime, timedelta
    from helpers import audit
    now = datetime(2026, 10, 6, 8, 0, 0)
    conn = db.get_db()
    try:
        def ins(days, read, user="bell_p"):
            conn.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at) VALUES (?,?,?,?,?,?,?)",
                         (user, "info", "x", "x", "m", read, (now - timedelta(days=days)).isoformat()))
        for d, rd in ((91, 0), (91, 1), (200, 0), (89, 0), (89, 1), (90, 0), (1, 0)):
            ins(d, rd)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(audit, "_PURGE_BATCH", 2)                      # 分批：3 列要跑兩批以上
    assert audit.purge_old_notifications(now=now) == 3                 # 91(未讀)、91(已讀)、200；90 天整（含）與以內留著
    assert audit.purge_old_notifications(now=now) == 0                 # 冪等
    left = sorted((now - datetime.fromisoformat(r["created_at"])).days for r in _rows("bell_p"))
    assert left == [1, 89, 89, 90]


def test_purge_is_bounded_per_run(client, monkeypatch):
    from datetime import datetime, timedelta
    from helpers import audit
    now = datetime(2026, 10, 6, 8, 0, 0)
    conn = db.get_db()
    try:
        conn.executemany("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at) VALUES (?,?,?,?,?,?,?)",
                         [("bell_q", "info", "x", "x", "m", 0, (now - timedelta(days=120)).isoformat())] * 7)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(audit, "_PURGE_BATCH", 2)
    monkeypatch.setattr(audit, "_PURGE_MAX_BATCHES", 2)
    assert audit.purge_old_notifications(now=now) == 4                 # 每次最多 2 批 × 2 列
    assert audit.purge_old_notifications(now=now) == 3                 # 下次接著清（先取到 batch 滿的才繼續）
    assert len(_rows("bell_q")) == 0 or len(_rows("bell_q")) == 0


def test_daily_check_runs_the_purge_and_survives_its_failure(client, monkeypatch):
    from helpers import audit, daily_checks
    calls = []
    monkeypatch.setattr(audit, "purge_old_notifications", lambda *a, **k: calls.append(1) or 0)
    monkeypatch.setattr(daily_checks.system_checks, "run_all", lambda **k: calls.append("sys"))
    daily_checks.run_once("startup")
    assert calls == [1, "sys"]
    monkeypatch.setattr(audit, "purge_old_notifications", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    calls.clear()
    daily_checks.run_once("daily")
    assert calls == ["sys"], "清理失敗不可擋住其他每日檢查"


def test_quotation_approval_writes_a_deduped_row_for_the_applicant_with_a_link(client, make_user):
    import json
    make_user(username="qa_sales", role="sales", modules=["quotation", "case_manage"])
    make_user(username="qa_appr", role="admin")
    appr = {"requestedBy": "qa_sales", "status": "pending", "currentTier": 0,
            "tiers": [{"approvers": [{"username": "qa_appr", "displayName": "qa_appr", "status": "pending"}]}]}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?,?,?)", ("MQ-QA-1", "待審核", "核准客", "專案", 105000, json.dumps({"approval": appr}, ensure_ascii=False),
                                                  "2026-10-06", "2026-10-06"))
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/auth/login", json={"username": "qa_appr", "password": "Test-Pass-123"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    resp = client.post("/api/quotations/MQ-QA-1/approve", headers=h, json={})
    assert resp.status_code == 200, resp.text
    rows = [x for x in _rows("qa_sales") if x["type"] == "quotation_approved"]
    assert len(rows) == 1 and rows[0]["link"] == "quotation-form.html?id=MQ-QA-1" and "NT$" not in rows[0]["message"] and "核准客" in rows[0]["message"], rows
    assert [x for x in _rows("qa_appr") if x["type"] == "quotation_approved"] == [], "核准人自己不會收到"


def test_quotation_approval_notification_is_wired_in_source():
    import inspect
    from modules.case.api import quotations as Q
    src = inspect.getsource(Q.approve_quotation)
    assert '"quotation_approved"' in src and 'quotation-form.html?id=' in src and "_notify" in src
