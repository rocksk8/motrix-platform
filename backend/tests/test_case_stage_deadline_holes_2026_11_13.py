# -*- coding: utf-8 -*-
"""T84：案件階段到期通知（`case_deadlines._check_case_stage_deadline`）的三個既有的洞。

① `casestage_notif.*` 去重鍵只寫不修 ⇒ 每次掃描尾端修剪（只留還沒完成、到期日 ≥ 今天－1 的階段）
② 同一個人同一天 N 個階段 ⇒ N 則站內通知＋N 封信 ⇒ 彙整成一則＋一封（主管同理）
③ 先寫鍵再發送（daemon thread）⇒ 站內通知與鍵同交易、信件同步等結果、寄出才寫最終鍵；暫時失敗 ⇒ 之後只重試外部通道，不重發站內通知
另釘：上線不補發（舊格式鍵＝已處理；過去已逾期的永遠不會被選到；到期前 1～2 天沒有鍵的不會憑空新發）。
"""
import json
from datetime import date, timedelta

import pytest

from core import events as EV
from tests._requires import requires_module
from tests.test_completion_notes_2026_09_12 import _make_case

pytestmark = requires_module("case", "本檔的題打 M01（案件）的每日到期檢查")

TODAY = date.today()
D0 = TODAY.isoformat()
D1 = (TODAY + timedelta(days=1)).isoformat()
D2 = (TODAY + timedelta(days=2)).isoformat()
D3 = (TODAY + timedelta(days=3)).isoformat()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
LONG_AGO = (TODAY - timedelta(days=40)).isoformat()


class FakeSender:
    """取代 `CD._send_stage_digest`：記下每一次呼叫；`script` 是依序要回的結果（用完就回 sent）。"""

    def __init__(self, script=None):
        self.calls = []
        self.script = list(script or [])

    def __call__(self, items, *, assignee_username="", manager_username="", out=None, line_key=""):
        self.calls.append({"assignee": assignee_username, "manager": manager_username, "n": len(items),
                           "stages": sorted((i["quote_no"], i["label"]) for i in items), "line_key": line_key})
        outcome = self.script.pop(0) if self.script else "sent"
        if out is not None:
            out["outcome"] = outcome
        return outcome in ("sent", "unknown", "permanent_fail", "no_recipient")


@pytest.fixture()
def cd(client, monkeypatch):
    from modules.case import case_deadlines as CD
    sender = FakeSender()
    monkeypatch.setattr(CD, "_send_stage_digest", sender)
    CD.sender = sender
    return CD


def _stage(quote_no, label, due, assignees, done=0):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute("INSERT INTO case_stages (quote_no, label, due_date, assigned_to, done, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                           (quote_no, label, due, json.dumps(assignees), done, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _states():
    import db
    conn = db.get_db()
    try:
        return {r["key"]: json.loads(r["value_json"]) for r in conn.execute(
            "SELECT key, value_json FROM system_settings WHERE key LIKE 'casestage_notif.%'").fetchall()}
    finally:
        conn.close()


def _put(key, value):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, json.dumps(value), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _notifs(username, type_="case_stage_deadline"):
    import db
    conn = db.get_db()
    try:
        return [r["message"] for r in conn.execute("SELECT message FROM notifications WHERE username=? AND type=? ORDER BY id", (username, type_)).fetchall()]
    finally:
        conn.close()


def _org(manager, member):
    """建一個部門：manager 是主管、member 是成員。"""
    import db
    conn = db.get_db()
    try:
        mid = conn.execute("SELECT id FROM users WHERE username=?", (manager,)).fetchone()["id"]
        conn.execute("INSERT INTO divisions (name, sort_order, created_at, manager_user_id) VALUES ('T84處', 0, '2026-01-01T00:00:00', NULL)")
        div = conn.execute("SELECT id FROM divisions WHERE name='T84處'").fetchone()["id"]
        conn.execute("INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) VALUES (?, 'T84部', 0, ?, '2026-01-01T00:00:00')", (div, mid))
        dep = conn.execute("SELECT id FROM departments WHERE name='T84部'").fetchone()["id"]
        conn.execute("UPDATE users SET department_id=? WHERE username=?", (dep, member))
        conn.commit()
    finally:
        conn.close()


# ── ① 修剪 ───────────────────────────────────────────────────────────────────────────
def test_prune_keeps_only_live_keys(cd, make_user):
    make_user(username="t84_u", role="admin")
    make_user(username="t84.dot", role="admin")
    _make_case("MQ-T84-A")
    live = _stage("MQ-T84-A", "活的", D2, ["t84_u"])
    done = _stage("MQ-T84-A", "已完成", D2, ["t84_u"], done=1)
    old = _stage("MQ-T84-A", "早過期", LONG_AGO, ["t84_u"])
    edge = _stage("MQ-T84-A", "昨天到期", YESTERDAY, ["t84_u"])           # 到期日 = 今天－1 ⇒ 還在緩衝內
    seeded = {
        f"casestage_notif.MQ-T84-A.{live}.t84_u.3d": D3,
        f"casestage_notif.MQ-T84-A.{live}.t84.dot.3d": D3,                  # 帳號含 "."
        f"casestage_notif.MQ-T84-A.{done}.t84_u.3d": D3,
        f"casestage_notif.MQ-T84-A.{old}.t84_u.deadline": LONG_AGO,
        f"casestage_notif.MQ-T84-A.{edge}.t84_u.deadline": YESTERDAY,
        "casestage_notif.MQ-T84-GONE.999.t84_u.3d": LONG_AGO,               # 案件／階段已不存在
        "casestage_notif.weird": "x",                                       # 看不懂格式 ⇒ 不動
    }
    for k, v in seeded.items():
        _put(k, v)
    cd._check_case_stage_deadline()
    left = set(_states())
    assert left == {f"casestage_notif.MQ-T84-A.{live}.t84_u.3d", f"casestage_notif.MQ-T84-A.{live}.t84.dot.3d",
                    f"casestage_notif.MQ-T84-A.{edge}.t84_u.deadline", "casestage_notif.weird"}


def test_prune_runs_even_when_the_scan_body_fails(cd, make_user, monkeypatch):
    make_user(username="t84_pf", role="admin")
    _make_case("MQ-T84-PF")
    _put("casestage_notif.MQ-T84-GONE.1.t84_pf.3d", LONG_AGO)
    monkeypatch.setattr(cd, "_stage_put_states", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _stage("MQ-T84-PF", "x", D3, ["t84_pf"])
    cd._check_case_stage_deadline()
    assert "casestage_notif.MQ-T84-GONE.1.t84_pf.3d" not in _states()


# ── ② 彙整 ───────────────────────────────────────────────────────────────────────────
def test_same_person_same_day_gets_one_notification_and_one_mail(cd, make_user):
    make_user(username="t84_a", role="admin")
    make_user(username="t84_b", role="admin")
    _make_case("MQ-T84-B1")
    _make_case("MQ-T84-B2")
    _stage("MQ-T84-B1", "施工", D3, ["t84_a"])
    _stage("MQ-T84-B1", "驗收", D3, ["t84_a", "t84_b"])
    _stage("MQ-T84-B2", "請款", D0, ["t84_a"])
    cd._check_case_stage_deadline()
    a, b = _notifs("t84_a"), _notifs("t84_b")
    assert len(a) == 1 and all(s in a[0] for s in ("施工", "驗收", "請款")), a
    assert len(b) == 1 and "驗收" in b[0], b                    # 只有一個階段 ⇒ 單項措辭（與舊版相同）
    assert b[0] == "案件執行進度「驗收」3 天後到期"
    by = {c["assignee"]: c for c in cd.sender.calls}
    assert sorted(by) == ["t84_a", "t84_b"] and len(cd.sender.calls) == 2
    assert by["t84_a"]["n"] == 3 and by["t84_b"]["n"] == 1


def test_manager_gets_one_digest_for_all_members(cd, make_user):
    make_user(username="t84_m", role="admin")
    make_user(username="t84_s1", role="admin")
    make_user(username="t84_s2", role="admin")
    _org("t84_m", "t84_s1")
    _org_extra = __import__("db").get_db()
    try:
        dep = _org_extra.execute("SELECT department_id d FROM users WHERE username='t84_s1'").fetchone()["d"]
        _org_extra.execute("UPDATE users SET department_id=? WHERE username='t84_s2'", (dep,))
        _org_extra.commit()
    finally:
        _org_extra.close()
    _make_case("MQ-T84-M")
    _stage("MQ-T84-M", "一", D3, ["t84_s1"])
    _stage("MQ-T84-M", "二", D3, ["t84_s1"])
    _stage("MQ-T84-M", "三", D3, ["t84_s2"])
    cd._check_case_stage_deadline()
    assert len(_notifs("t84_m", "case_stage_deadline_manager")) == 1
    mgr_calls = [c for c in cd.sender.calls if c["manager"] == "t84_m"]
    assert len(mgr_calls) == 1 and mgr_calls[0]["n"] == 3
    assert len([c for c in cd.sender.calls if c["assignee"]]) == 2


def test_digest_content_single_item_keeps_the_old_fields_and_multi_is_a_list():
    from helpers import email_notify as EN
    one = [{"quote_no": "Q-1", "label": "施工", "due": D3, "days_left": 3, "customer": "甲", "project": "乙", "display": "小明"}]
    p1 = EN._case_stage_digest_parts(one, manager=False)
    assert p1["title"] == "案件執行進度即將到期" and ("階段", "施工") in p1["rows"] and ("負責人員", "小明") in p1["rows"] and "尚餘 3 天" in p1["reason"]
    pm = EN._case_stage_digest_parts(one, manager=True)
    assert pm["title"] == "部門成員案件執行進度即將到期" and "您部門的 小明" in pm["reason"]
    many = one + [{"quote_no": "Q-2", "label": "驗收", "due": D0, "days_left": 0, "customer": "", "project": "", "display": "小華"}]
    pn = EN._case_stage_digest_parts(many, manager=True)
    assert "2 個階段" in pn["title"] and len(pn["rows"]) == 2 and "其中 1 個今天到期" in pn["reason"] and pn["badge_color"] == "#DC2626"


# ── ③ 先寄成功才寫最終鍵（兩階段）──────────────────────────────────────────────────────
def test_transient_failure_keeps_the_key_pending_then_retry_sends_mail_only(cd, make_user):
    make_user(username="t84_t", role="admin")
    _make_case("MQ-T84-T")
    sid = _stage("MQ-T84-T", "施工", D3, ["t84_t"])
    key = f"casestage_notif.MQ-T84-T.{sid}.t84_t.3d"
    cd.sender.script = ["transient_fail"]
    cd._check_case_stage_deadline()
    assert len(_notifs("t84_t")) == 1                                       # 站內通知先送
    assert _states()[key] == f"p::{D0}"                                      # 信件沒送成 ⇒ 還不是最終
    cd._check_case_stage_deadline()                                          # 下一次檢查（同一天再跑一次當作隔天）
    assert len(cd.sender.calls) == 2                                         # 信件重試了
    assert len(_notifs("t84_t")) == 1                                        # 站內通知不重發
    assert _states()[key] == D0                                              # 最終
    cd._check_case_stage_deadline()
    assert len(cd.sender.calls) == 2 and len(_notifs("t84_t")) == 1          # 最終之後不再發


@pytest.mark.parametrize("outcome", ["sent", "unknown", "permanent_fail", "no_recipient"])
def test_every_final_outcome_writes_the_final_key(cd, make_user, outcome):
    make_user(username="t84_f", role="admin")
    _make_case("MQ-T84-F")
    sid = _stage("MQ-T84-F", "施工", D3, ["t84_f"])
    cd.sender.script = [outcome]
    cd._check_case_stage_deadline()
    assert _states()[f"casestage_notif.MQ-T84-F.{sid}.t84_f.3d"] == D0


def test_skipped_also_stays_pending(cd, make_user):
    make_user(username="t84_sk", role="admin")
    _make_case("MQ-T84-SK")
    sid = _stage("MQ-T84-SK", "施工", D3, ["t84_sk"])
    cd.sender.script = ["skipped"]
    cd._check_case_stage_deadline()
    assert _states()[f"casestage_notif.MQ-T84-SK.{sid}.t84_sk.3d"] == f"p::{D0}"


def test_transient_failure_halts_the_rest_of_the_round(cd, make_user):
    for u in ("t84_h1", "t84_h2"):
        make_user(username=u, role="admin")
    _make_case("MQ-T84-H")
    _stage("MQ-T84-H", "一", D3, ["t84_h1"])
    _stage("MQ-T84-H", "二", D3, ["t84_h2"])
    cd.sender.script = ["transient_fail"]
    cd._check_case_stage_deadline()
    assert len(cd.sender.calls) == 1                                         # 第一封暫時失敗 ⇒ 不再逐封各等一次
    assert len(_notifs("t84_h1")) == 1 and len(_notifs("t84_h2")) == 1       # 站內通知兩人都有
    cd._check_case_stage_deadline()
    assert len(cd.sender.calls) == 3                                         # 下次補：兩封都送
    assert set(_states().values()) == {D0}


def test_sender_exception_counts_as_transient(cd, make_user, monkeypatch):
    make_user(username="t84_ex", role="admin")
    _make_case("MQ-T84-EX")
    sid = _stage("MQ-T84-EX", "施工", D3, ["t84_ex"])

    def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(cd, "_send_stage_digest", boom)
    cd._check_case_stage_deadline()
    assert _states()[f"casestage_notif.MQ-T84-EX.{sid}.t84_ex.3d"] == f"p::{D0}"
    assert len(_notifs("t84_ex")) == 1


def test_manager_mail_retries_without_resending_the_assignee_mail(cd, make_user):
    make_user(username="t84_mm", role="admin")
    make_user(username="t84_ms", role="admin")
    _org("t84_mm", "t84_ms")
    _make_case("MQ-T84-MR")
    sid = _stage("MQ-T84-MR", "施工", D3, ["t84_ms"])
    key = f"casestage_notif.MQ-T84-MR.{sid}.t84_ms.3d"
    cd.sender.script = ["sent", "transient_fail"]                           # 負責人那封成功、主管那封暫時失敗
    cd._check_case_stage_deadline()
    assert _states()[key] == f"p:a:{D0}"
    cd._check_case_stage_deadline()
    assert [c["assignee"] or c["manager"] for c in cd.sender.calls] == ["t84_ms", "t84_mm", "t84_mm"]   # 第二輪只補主管那封
    assert _states()[key] == D0
    assert len(_notifs("t84_ms")) == 1 and len(_notifs("t84_mm", "case_stage_deadline_manager")) == 1


def test_pending_key_is_retried_on_days_between_three_and_zero(cd, make_user):
    """首次嘗試只在 3 天前與當天；但已經有 p: 鍵的（上一次信件沒送成）在 2、1 天前也會補。"""
    make_user(username="t84_r", role="admin")
    _make_case("MQ-T84-R")
    sid = _stage("MQ-T84-R", "施工", D2, ["t84_r"])
    key = f"casestage_notif.MQ-T84-R.{sid}.t84_r.3d"
    _put(key, f"p::{D1}")
    cd._check_case_stage_deadline()
    assert len(cd.sender.calls) == 1 and _notifs("t84_r") == [] and _states()[key] == D0


def test_notification_and_pending_key_are_one_transaction(cd, make_user, monkeypatch):
    make_user(username="t84_tx", role="admin")
    _make_case("MQ-T84-TX")
    sid = _stage("MQ-T84-TX", "施工", D3, ["t84_tx"])
    real = cd._stage_put_states
    calls = []

    def fail_once(conn, states):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("disk full")
        return real(conn, states)
    monkeypatch.setattr(cd, "_stage_put_states", fail_once)
    cd._check_case_stage_deadline()
    assert _notifs("t84_tx") == [] and _states() == {}                       # 寫鍵失敗 ⇒ 通知一起回滾
    cd._check_case_stage_deadline()
    assert len(_notifs("t84_tx")) == 1                                       # 下次當作全新的再發（不會漏、不會重）
    assert f"casestage_notif.MQ-T84-TX.{sid}.t84_tx.3d" in _states()


def test_event_is_emitted_once_even_when_mail_is_retried(cd, make_user):
    make_user(username="t84_ev", role="admin")
    _make_case("MQ-T84-EV")
    _stage("MQ-T84-EV", "施工", D3, ["t84_ev"])
    got = []
    state = EV.snapshot()
    EV.subscribe("case.deadline_near", lambda p: got.append(p), "test_t84")
    try:
        cd.sender.script = ["transient_fail"]
        cd._check_case_stage_deadline()
        cd._check_case_stage_deadline()
    finally:
        EV.restore(state)
    assert [(p["quoteNo"], p["assignee"]) for p in got if p["quoteNo"] == "MQ-T84-EV"] == [("MQ-T84-EV", "t84_ev")]


# ── 上線不補發 ───────────────────────────────────────────────────────────────────────
def test_rollout_does_not_resend_what_the_old_version_already_marked(cd, make_user):
    make_user(username="t84_o", role="admin")
    _make_case("MQ-T84-O")
    s3 = _stage("MQ-T84-O", "三天", D3, ["t84_o"])
    s0 = _stage("MQ-T84-O", "今天", D0, ["t84_o"])
    s2 = _stage("MQ-T84-O", "兩天後", D2, ["t84_o"])                         # 沒有任何鍵：不是首次嘗試的日子 ⇒ 不新發
    _stage("MQ-T84-O", "昨天逾期", YESTERDAY, ["t84_o"])                     # 已逾期：永遠不會被選到
    _stage("MQ-T84-O", "很久以前", LONG_AGO, ["t84_o"])
    _put(f"casestage_notif.MQ-T84-O.{s3}.t84_o.3d", "2026-11-10")            # 舊版寫的格式（純日期）
    _put(f"casestage_notif.MQ-T84-O.{s0}.t84_o.deadline", "2026-11-13")
    cd._check_case_stage_deadline()
    assert cd.sender.calls == [] and _notifs("t84_o") == []
    assert _states()[f"casestage_notif.MQ-T84-O.{s3}.t84_o.3d"] == "2026-11-10"      # 舊鍵原封不動
    assert f"casestage_notif.MQ-T84-O.{s2}.t84_o.3d" not in _states()


def test_historical_backfilled_quotes_are_still_silent(cd, make_user):
    import db
    make_user(username="t84_hist", role="admin")
    _make_case("MQ-T84-HIST")
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no='MQ-T84-HIST'",
                     (json.dumps({"approval": {"historical": True}, "dealTag": "已成案"}, ensure_ascii=False),))
        conn.commit()
    finally:
        conn.close()
    _stage("MQ-T84-HIST", "x", D3, ["t84_hist"])
    cd._check_case_stage_deadline()
    assert cd.sender.calls == [] and _notifs("t84_hist") == [] and _states() == {}
