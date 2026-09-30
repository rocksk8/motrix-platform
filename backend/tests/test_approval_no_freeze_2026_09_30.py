# -*- coding: utf-8 -*-
"""W3 approval-freeze：簽核時整個系統卡住約 3 秒（使用者回報正式機，2026-09-30）。

成因：`approve_quotation` 在 `write_txn`（BEGIN IMMEDIATE）區塊內呼叫 `_notify`（另開連線 INSERT）與 `notify_next_tier`，
新連線等同一個請求握著的寫鎖，等滿 busy timeout（30 秒）才失敗 ⇒ 通知遺失、期間全體寫入被卡住；
同一區塊 commit 之前就 `spawn_bg_thread(PDF)` ⇒ PDF 可能讀到簽核前的狀態，且 Edge 無頭 PDF 是 2～4 秒的 CPU 工作。

本檔三層：
  ① 靜態守門：`tools/platform/write_txn_scan.py` 全 repo 掃描——`with write_txn`（與手動 begin_write／BEGIN IMMEDIATE）持鎖期間不得呼叫
     _notify／_audit／spawn_bg_thread／notify_*／push_event_*／Thread／寄信（白名單要寫理由）；含正對照與流程判斷題
  ② 執行題：多層簽核中間層核准 < 1 秒、通知確實寫入；通知／寄信／PDF 被呼叫的當下**寫鎖已放掉**（另一條連線能拿到寫鎖）；
     PDF 被啟動的當下簽核結果已 commit
"""
import ast
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import write_txn_scan as W  # noqa: E402


# ── ① 靜態 ───────────────────────────────────────────────────────────────────

def test_repo_has_no_notify_or_spawn_inside_a_held_write_lock():
    """全 repo 掃描：write_txn 區塊（及手動 begin）持鎖期間沒有另開連線寫入／啟動背景工作的呼叫。"""
    probs = W.problems(W.scan(REPO))
    assert probs == [], "寫鎖內不得呼叫通知／稽核／背景工作（收集起來，commit 之後再做）：\n  " + "\n  ".join(probs)


def _hits(src):
    w = W._Walker()
    w.run(ast.parse(src))
    return sorted((fn, name) for fn, _l, name in w.hits)


def test_scanner_positive_controls():
    assert _hits("def f(conn):\n    with write_txn(conn):\n        _notify(1)\n        conn.commit()\n") == [("f", "_notify")]
    assert _hits("def f(conn):\n    with write_txn(conn):\n        if x:\n            spawn_bg_thread(g)\n") == [("f", "spawn_bg_thread")]
    assert _hits("def f(conn):\n    with write_txn(conn):\n        for u in us:\n            notify_next_tier(u)\n") == [("f", "notify_next_tier")]
    assert _hits("def f(conn):\n    with write_txn(conn):\n        _audit(1)\n") == [("f", "_audit")]
    assert _hits("def f(conn):\n    begin_write(conn)\n    push_event_for_x(1)\n    conn.commit()\n") == [("f", "push_event_for_x")]
    assert _hits("def f(conn):\n    conn.execute('BEGIN IMMEDIATE')\n    threading.Thread(target=g).start()\n    conn.commit()\n") == [("f", "Thread")]
    assert _hits("def f(conn):\n    try:\n        begin_write(conn)\n        _notify(1)\n    finally:\n        pass\n") == [("f", "_notify")]


def test_scanner_does_not_flag_what_runs_after_the_lock_is_released():
    # 頂層 commit／close／rollback 之後（寫鎖已放掉）
    assert _hits("def f(conn):\n    with write_txn(conn):\n        conn.commit()\n        conn.close()\n        _audit(1)\n        spawn_bg_thread(g)\n") == []
    # 分支內先 close 再通知再 raise（常見的錯誤出口）
    assert _hits("def f(conn):\n    with write_txn(conn):\n        if bad:\n            conn.close()\n            _audit(1)\n            raise E()\n") == []
    # 區塊外
    assert _hits("def f(conn):\n    with write_txn(conn):\n        conn.commit()\n    _notify(1)\n") == []
    # 區塊內只是「定義」稍後才執行的收集（lambda／partial 建構不算執行）
    assert _hits("def f(conn):\n    with write_txn(conn):\n        after.append(lambda: _notify(1))\n        conn.commit()\n") == []
    assert _hits("def f(conn):\n    with write_txn(conn):\n        def later():\n            _notify(1)\n        conn.commit()\n") == []
    # 不相干的函式
    assert _hits("def f(conn):\n    _notify(1)\n    with other(conn):\n        _audit(1)\n") == []


def test_allowlist_counts_must_match_and_stale_entries_are_red():
    hits = [("a.py", "f", 1, "_notify"), ("a.py", "f", 2, "_notify")]
    assert W.problems(hits, {("a.py", "f", "_notify"): (2, "理由")}) == []
    assert W.problems(hits, {("a.py", "f", "_notify"): (1, "理由")}), "次數不一致必須紅"
    assert W.problems([], {("a.py", "f", "_notify"): (1, "理由")}), "白名單過期（不再呼叫）必須紅"
    assert W.problems(hits, {}), "沒登記必須紅"


def test_every_allowlist_entry_has_a_reason():
    assert all(isinstance(v[1], str) and len(v[1]) >= 8 for v in W.ALLOWED.values())


# ── ② 執行 ───────────────────────────────────────────────────────────────────

def _login(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _lock_is_free():
    """另開一條連線嘗試拿寫鎖（timeout 0.2 秒）：拿得到 ⇒ 沒有人握著寫鎖。"""
    import db
    c = sqlite3.connect(db.DB_PATH if hasattr(db, "DB_PATH") else db._paths.DB_PATH, timeout=0.2)
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        c.close()


def _committed_status(quote_no):
    import db
    c = sqlite3.connect(db.DB_PATH if hasattr(db, "DB_PATH") else db._paths.DB_PATH, timeout=1)
    try:
        return c.execute("SELECT status FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()[0]
    finally:
        c.close()


@pytest.fixture
def two_tier(client, make_user):
    from tests.test_queue_and_feed_scoping_2026_09_15 import _insert_pending_quotation
    a1 = make_user("nf_appr1", "Conn-Pass-123", role="admin")[:2]
    a2 = make_user("nf_appr2", "Conn-Pass-123", role="admin")[:2]
    make_user("nf_sales", "Conn-Pass-123", role="sales")
    _insert_pending_quotation("MQ-NF-001", "nf_sales", [["nf_appr1"], ["nf_appr2"]])
    return a1, a2


def test_middle_tier_approval_is_fast_and_the_notification_is_written(client, two_tier):
    """量測：修前 _notify 等自己握著的寫鎖，等滿 busy timeout（30 秒）才失敗、通知遺失；修後 < 1 秒、通知寫入。"""
    a1, _a2 = two_tier
    h = _login(client, *a1)
    t0 = time.perf_counter()
    r = client.post("/api/quotations/MQ-NF-001/approve", headers=h, json={})
    dt = time.perf_counter() - t0
    print("\nAPPROVE middle-tier %.3fs status=%s" % (dt, r.status_code))
    assert r.status_code == 200 and r.json()["allDone"] is False, r.text[:300]
    assert dt < 1.0, "中間層核准花了 %.1f 秒（寫鎖內另開連線寫入通知？）" % dt
    import db
    c = db.get_db()
    try:
        n = c.execute("SELECT COUNT(*) FROM notifications WHERE username='nf_appr2' AND type='approval_request' AND ref_id='MQ-NF-001'").fetchone()[0]
    finally:
        c.close()
    assert n == 1, "下一層簽核人沒有收到站內通知（%d）" % n


def test_side_effects_run_only_after_the_write_lock_is_released(client, two_tier, monkeypatch):
    """通知／寄信／PDF 被呼叫的當下，另一條連線必須拿得到寫鎖；PDF 啟動時簽核結果必須已 commit。"""
    from modules.case.api import quotations as Q
    seen = {"notify": [], "next": [], "approved": [], "pdf": []}

    def spy(kind, real=None):
        def _f(*a, **kw):
            seen[kind].append((_lock_is_free(), _committed_status("MQ-NF-001")))
            return real(*a, **kw) if real else None
        return _f

    monkeypatch.setattr(Q, "_notify", spy("notify", Q._notify))
    monkeypatch.setattr(Q, "notify_next_tier", spy("next"))
    monkeypatch.setattr(Q, "notify_approved", spy("approved"))
    real_spawn = Q.spawn_bg_thread

    def spawn(fn, *a, **kw):
        if getattr(fn, "__name__", "") == "_generate_quotation_pdf":
            seen["pdf"].append((_lock_is_free(), _committed_status("MQ-NF-001")))
            return None                                        # 不真的產 PDF
        return real_spawn(fn, *a, **kw)
    monkeypatch.setattr(Q, "spawn_bg_thread", spawn)

    a1, a2 = two_tier
    assert client.post("/api/quotations/MQ-NF-001/approve", headers=_login(client, *a1), json={}).status_code == 200
    assert seen["notify"] and seen["next"], "中間層核准應該通知下一層"
    assert all(free for free, _ in seen["notify"] + seen["next"]), "通知／寄信被呼叫時寫鎖還沒放：%s" % (seen,)
    assert seen["pdf"] == [] and seen["approved"] == []
    assert client.post("/api/quotations/MQ-NF-001/approve", headers=_login(client, *a2), json={}).status_code == 200
    assert seen["pdf"] and seen["approved"]
    assert all(free and status == "已送出" for free, status in seen["pdf"]), "PDF 啟動時寫鎖未放或簽核結果尚未 commit：%s" % (seen["pdf"],)
    assert all(free for free, _ in seen["approved"])


def test_a_failing_side_effect_does_not_turn_a_committed_approval_into_a_500(client, two_tier, monkeypatch):
    from modules.case.api import quotations as Q

    def boom(*a, **kw):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(Q, "notify_next_tier", boom)
    a1, _ = two_tier
    r = client.post("/api/quotations/MQ-NF-001/approve", headers=_login(client, *a1), json={})
    assert r.status_code == 200, r.text[:300]
    assert _committed_status("MQ-NF-001") == "簽核中"


# ── ③ 待簽佇列效能：正常的單由 SQLite 取 $.approval，其餘形狀照舊走 Python ──────────────────────────

def _insert_raw(conn, quote_no, data_json, status="待審核"):
    conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (quote_no, status, "客", "案", 1, 1, data_json, "2026-09-01T00:00:00", "2026-09-01T00:00:00", "", "2026-09-01"))


def _appr(u="fp_appr", **extra):
    a = {"tiers": [{"order": 0, "approvers": [{"username": u, "displayName": "乙 甲", "status": "pending", "approvedAt": None}]}],
         "currentTier": 0, "requestedBy": "s", "requestedByDisplay": "業務", "requestedAt": "2026-09-01T00:00:00", "reasons": ["原因 é", 1.5, None]}
    a.update(extra)
    return a


SHAPES = {
    "normal": json.dumps({"approval": _appr()}, ensure_ascii=False),
    "normal_big": json.dumps({"items": [{"n": "x" * 50}] * 100, "approval": _appr(isEditApproval=True)}, ensure_ascii=False),
    "no_approval": json.dumps({"items": []}),
    "approval_null": json.dumps({"approval": None}),
    "approval_empty_list": json.dumps({"approval": []}),
    "approval_empty_str": json.dumps({"approval": ""}),
    "approval_truthy_list": json.dumps({"approval": [1]}),
    "approval_truthy_str": json.dumps({"approval": "x"}),
    "approval_number": json.dumps({"approval": 7}),
    "root_array": "[1,2]",
    "root_string": '"x"',
    "invalid": "{ not json",
    "empty_str": "",
    "duplicate_keys": '{"approval": {"currentTier": 5, "currentTier": 0, "tiers": []}}',
    "big_int": json.dumps({"approval": {"tiers": [], "n": 123456789012345678901234567890}}),
}


def test_queue_provider_fast_path_is_equivalent_to_the_python_parse_for_every_shape(client, monkeypatch):
    """每一種資料形狀：新查詢的結果與舊算法（Python 逐筆 approval_json_of＋_queue_tier_fields）逐筆相同；壞的照舊跳過。"""
    import db
    from modules.case.api import quotations as Q
    conn = db.get_db()
    try:
        for i, (name, dj) in enumerate(SHAPES.items()):
            _insert_raw(conn, "MQ-FP-%02d" % i, dj)
        conn.commit()
        got = {it["quoteNo"]: it for it in Q.approval_queue_items(conn) if it["type"] == "quotation" and it["quoteNo"].startswith("MQ-FP-")}
        for i, (name, dj) in enumerate(SHAPES.items()):
            qn = "MQ-FP-%02d" % i
            raw = Q._approval_json_of(dj, "quotation", qn)
            if raw is None:
                assert qn not in got, "%s：舊算法會跳過，新查詢卻列出" % name
                continue
            assert qn in got, "%s：舊算法會列出，新查詢漏掉" % name
            f = Q._queue_tier_fields(raw)
            it = got[qn]
            for k_item, k_f in (("tiers", "tiers"), ("currentTier", "currentTier"), ("requestedBy", "requestedBy"),
                                ("requestedAt", "requestedAt"), ("tierCount", "tierCount")):
                assert it[k_item] == f[k_f], "%s：%s 不同 %r ≠ %r" % (name, k_item, it[k_item], f[k_f])
            assert it["reasons"] == (f["appr"].get("reasons") or []) and it["isEditApproval"] == f["appr"].get("isEditApproval", False), name
        assert len(got) == len([1 for n, d in SHAPES.items() if Q._approval_json_of(d, "quotation", "x") is not None])
    finally:
        conn.close()


def test_a_bad_json_row_does_not_make_the_whole_class_disappear(client):
    import db
    from modules.case.api import quotations as Q
    conn = db.get_db()
    try:
        _insert_raw(conn, "MQ-FP-BAD", "{ not json")
        _insert_raw(conn, "MQ-FP-OK", SHAPES["normal"])
        conn.commit()
        nos = {it["quoteNo"] for it in Q.approval_queue_items(conn)}
        assert "MQ-FP-OK" in nos and "MQ-FP-BAD" not in nos
    finally:
        conn.close()


def _seed_many(n, kb):
    import db
    pad = [{"name": "品項%d" % i, "description": "說明 " * 30, "qty": 1, "price": 100} for i in range(max(1, kb * 1024 // 200))]
    conn = db.get_db()
    try:
        for i in range(n):
            _insert_raw(conn, "MQ-PF-%04d" % i, json.dumps({"items": pad, "approval": _appr("pf_appr")}, ensure_ascii=False))
        conn.commit()
    finally:
        conn.close()


def test_queue_and_badge_with_200_large_pending_quotations_stay_under_200ms(client, make_user):
    """量測（修前 200 張×60KB：佇列 441 ms、角標 400 ms）。使用者體感線 300 ms，這裡取 200 ms 留餘裕並讓任一項優化被退回都會紅；取 5 次中位數。"""
    a = make_user("pf_appr", "Conn-Pass-123", role="admin")[:2]
    make_user("s", "Conn-Pass-123", role="sales")
    h = _login(client, *a)
    _seed_many(200, 60)
    client.get("/api/approval-queue", headers=h)
    res = {}
    for name, url in (("queue", "/api/approval-queue"), ("count", "/api/approval-queue/count")):
        ts = []
        for _ in range(5):
            t = time.perf_counter()
            r = client.get(url, headers=h)
            ts.append((time.perf_counter() - t) * 1000)
            assert r.status_code == 200
        res[name] = sorted(ts)[2]
    print("\nQUEUE-200x60KB queue p50=%.0fms count p50=%.0fms" % (res["queue"], res["count"]))
    assert client.get("/api/approval-queue", headers=h).json()["total"] == 200
    assert res["queue"] < 200 and res["count"] < 200, res


# ── ④ Edge PDF：背景工作用低優先權 ─────────────────────────────────────────────────────

def test_edge_pdf_uses_below_normal_priority_only_for_background_work(monkeypatch):
    import subprocess
    from helpers import startup
    import db
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(kw))
    monkeypatch.setattr(startup.os, "name", "nt")
    monkeypatch.delenv("MOTRIX_EDGE_PDF_PRIORITY", raising=False)
    startup.run_edge_pdf(["edge"])                                   # 使用者正在等的 PDF：不降
    assert "creationflags" not in calls[-1]
    tok = db._BACKGROUND_WORK.set(True)
    try:
        startup.run_edge_pdf(["edge"])
        assert calls[-1].get("creationflags") == 0x00004000
        monkeypatch.setenv("MOTRIX_EDGE_PDF_PRIORITY", "normal")     # 可關掉
        startup.run_edge_pdf(["edge"])
        assert "creationflags" not in calls[-1]
    finally:
        db._BACKGROUND_WORK.reset(tok)
    monkeypatch.delenv("MOTRIX_EDGE_PDF_PRIORITY", raising=False)
    monkeypatch.setattr(startup.os, "name", "posix")                 # 非 Windows：一律不帶（POSIX 的 creationflags 只能是 0）
    tok = db._BACKGROUND_WORK.set(True)
    try:
        startup.run_edge_pdf(["edge"])
        assert "creationflags" not in calls[-1]
    finally:
        db._BACKGROUND_WORK.reset(tok)


def test_spawn_bg_thread_marks_only_the_child_as_background_work():
    import threading
    import db
    seen = []
    t = db.spawn_bg_thread(lambda: seen.append(db._BACKGROUND_WORK.get()))
    t.join(5)
    assert seen == [True] and db._BACKGROUND_WORK.get() is False, "背景旗標只能設在子執行緒的 context 複本裡"


def test_case_summary_deal_tag_fast_path_is_equivalent_for_every_shape(client):
    """`case.summary` 的 deal_tag：欄位優先；欄位空時 SQLite 取 `$.dealTag`（合法 JSON 的字串／null／缺）；其餘形狀走 Python。
    與舊算法（`(json.loads(data_json).get("dealTag") or "")`，壞 JSON ⇒ ""）逐形狀相同。"""
    import db
    from modules.case.quotations import case_summary
    from helpers.case_access import SYSTEM
    shapes = {
        "col_set": ("已成案", json.dumps({"dealTag": "x"})),
        "col_set_bad_json": ("已成案", "{ bad"),
        "json_text": ("", json.dumps({"dealTag": "已結案"}, ensure_ascii=False)),
        "json_empty_text": ("", json.dumps({"dealTag": ""})),
        "json_null": ("", json.dumps({"dealTag": None})),
        "json_missing": ("", json.dumps({"items": []})),
        "json_number": ("", json.dumps({"dealTag": 7})),
        "json_object": ("", json.dumps({"dealTag": {"a": 1}})),
        "json_list": ("", json.dumps({"dealTag": ["z"]})),
        "json_false": ("", json.dumps({"dealTag": False})),
        "root_array": ("", "[1]"),
        "root_string": ("", '"x"'),
        "invalid": ("", "{ not json"),
        "empty": ("", ""),
        "unicode_escape": ("", '{"dealTag": "\u5df2\u6210\u6848"}'),
    }
    conn = db.get_db()
    try:
        for i, (tag, dj) in enumerate(shapes.values()):
            conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("MQ-DT-%02d" % i, "待審核", "客", "案", 1, 1, dj, "t", "t", tag, "2026-09-01"))
        conn.commit()
        got = {r["quote_no"]: r["deal_tag"] for r in case_summary(conn, SYSTEM, ["MQ-DT-%02d" % i for i in range(len(shapes))])}
    finally:
        conn.close()

    def old(tag, dj):
        if tag:
            return tag
        try:
            d = json.loads(dj or "{}")
        except (TypeError, ValueError):
            return ""
        return (d.get("dealTag") or "") if isinstance(d, dict) else ""
    for i, (name, (tag, dj)) in enumerate(shapes.items()):
        assert got["MQ-DT-%02d" % i] == old(tag, dj), "%s：新 %r ≠ 舊 %r" % (name, got["MQ-DT-%02d" % i], old(tag, dj))
