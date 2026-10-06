# -*- coding: utf-8 -*-
"""MAIL-CAL 階段 2：三個日期型行事曆事件（保固到期 warranty_expiry／區間工作事項結束 range_task_due／專案預計完成 project_end）。

使用者裁示（2026-10-05）：預設關、由管理員在矩陣勾選；事件走 t41 的 upsert／delete；事件內容不放金額。
守門：
 ① 矩陣：三個代碼各掛在既有信件列（warranty_expiry／range_task_deadline／case_project_overdue），預設關，停用原因消失
 ② 預設關＝零行為改變：每日檢查不讀資料庫、不打 Google、不寫對帳表
 ③ 對帳（helpers/calendar_sync）：冪等、改日期／內容更新、來源消失刪除、日期已過不建（Q9）、過期保留歷史、
    開關關著時不前進（重新打開可補齊）、單次呼叫上限
 ④ 三個來源（案件保固／案件專案期間／區間工作事項）各自組出正確的項目；事件內容沒有金額
 ⑤ 反向對照：矩陣完整性守門在「少一條 EVENT_LINKS／多一條指向不存在代碼」時真的會紅
斷言打在 push_event_upsert／delete 的呼叫紀錄與 system_settings，不打畫面文字。
"""
import json
from datetime import date, timedelta

import pytest

from helpers import google_calendar as gc
from helpers import mail_types as mt
from helpers import notify_matrix as nm
from helpers import calendar_sync as cs
from helpers.settings import _get_setting, _set_setting

NEW = {"warranty_expiry": "warranty_expiry", "range_task_due": "range_task_deadline", "project_end": "case_project_overdue"}
TODAY = date.today()


def _d(n):
    return (TODAY + timedelta(days=n)).isoformat()


@pytest.fixture(autouse=True)
def _clean(client):
    """同一個 worker 的資料庫跨測試共用：每個測試前後清掉我們寫過的設定與資料。"""
    def wipe():
        import db
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM system_settings WHERE key LIKE 'calsync.%' OR key IN ('google_calendar', 'mail_recipient_overrides') "
                         "OR key LIKE 'caseproj_notif.%'")
            conn.execute("DELETE FROM quotations WHERE quote_no LIKE 'Q-W_' OR quote_no LIKE 'Q-P_' OR quote_no LIKE 'Q-I_'")
            conn.execute("DELETE FROM daily_task_completions WHERE username IN ('alice_zz', 'bob_zz')")
            conn.execute("DELETE FROM daily_tasks WHERE created_by='x' AND title IN ('進行中', '全員完成', '單日', '已刪除')")
            conn.commit()
        finally:
            conn.close()
    wipe()
    yield
    wipe()


@pytest.fixture
def calls(monkeypatch):
    rec = []
    monkeypatch.setattr(gc, "_upsert_event_strict", lambda code, s, d, dt, key: rec.append(("up", code, key, str(dt), s, d)) or True)
    monkeypatch.setattr(gc, "_delete_event_strict", lambda code, key: rec.append(("del", code, key)) or True)
    return rec


def _cal(on=(), enabled=True):
    _set_setting("google_calendar", {"enabled": enabled, "events": {c: True for c in on}})


def _sa(client, make_user):
    u, p = make_user(username="p2_sa", role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _linkage_problems(d):
    """三個新事件都要掛在各自的信件主列上（缺一條 EVENT_LINKS，矩陣會自動把它當成「僅行事曆」列而通過完整性——所以要另外守）。"""
    out = []
    for code, mail in NEW.items():
        row = next((x for x in d["items"] if x["key"] == mail), None)
        if not row or row["calendar"]["code"] != code or not row["calendar"]["primary"]:
            out.append("%s 沒有掛在信件列 %s" % (code, mail))
    return out


def _completeness_problems(d, links=None):
    """矩陣完整性守門的判斷式（與階段 1 同一條），抽出來才能做反向對照。回問題清單，空＝通過。"""
    links = nm.EVENT_LINKS if links is None else links
    out = []
    only = {c["code"] for c in d["calendarOnly"]}
    linked = {x["calendar"]["code"] for x in d["items"] if x["calendar"]["code"]}
    if only | linked != set(gc.EVENT_CODES) or (only & linked):
        out.append("行事曆代碼沒有剛好對應到一列")
    for code, link in links.items():
        if code not in gc.EVENT_CODES:
            out.append("EVENT_LINKS 指向不存在的行事曆代碼 " + code)
        for k in (link["mail"], *link["also"]):
            if mt.get(k) is None:
                out.append("EVENT_LINKS 指向不存在的信件 " + k)
    for x in d["items"]:
        c = x["calendar"]
        if bool(c["code"]) == bool(c["disabledReason"]):
            out.append("%s：行事曆格不是可勾就要有停用原因" % x["key"])
    return out


# ── ① 矩陣 ───────────────────────────────────────────────────────────

def test_new_events_sit_on_their_existing_mail_rows_default_off(client, make_user):
    h = _sa(client, make_user)
    d = client.get("/api/mail-types", headers=h).json()
    assert _completeness_problems(d) == [] and _linkage_problems(d) == []
    for code, mail in NEW.items():
        row = next(x for x in d["items"] if x["key"] == mail)
        assert row["calendar"]["code"] == code and row["calendar"]["primary"] is True and row["calendar"]["enabled"] is False, code
        assert row["calendar"]["disabledReason"] == "" and row["calendar"]["note"]
        assert gc.event_switches({})[code] is False
    assert {c["code"] for c in d["calendarOnly"]}.isdisjoint(NEW)          # 三個不是「僅行事曆」列：信件格仍可用
    # 勾選就是既有的那支 PUT（與行事曆設定頁同一份）
    r = client.put("/api/settings/google-calendar", headers=h, json={"events": {"project_end": True}})
    assert r.status_code == 200 and r.json()["changed"] == ["project_end"]
    d = client.get("/api/mail-types", headers=h).json()
    assert next(x for x in d["items"] if x["key"] == "case_project_overdue")["calendar"]["enabled"] is True


def test_new_event_descriptions_carry_no_money_wording():
    for code in NEW:
        label, desc = next((t[1], t[3]) for t in gc.EVENT_TYPES if t[0] == code)
        assert not any(w in label + desc for w in ("金額", "$", "元", "價")), code


# ── ⑤ 反向對照（守門真的會紅）─────────────────────────────────────────

def test_reverse_control_completeness_guard_goes_red(client, make_user, monkeypatch):
    h = _sa(client, make_user)
    monkeypatch.delitem(nm.EVENT_LINKS, "warranty_expiry")                  # 少一條配對 ⇒ 矩陣把它當僅行事曆列（完整性過），掛載守門要紅
    d = client.get("/api/mail-types", headers=h).json()
    assert _completeness_problems(d) == [] and _linkage_problems(d) == ["warranty_expiry 沒有掛在信件列 warranty_expiry"]
    monkeypatch.setitem(nm.EVENT_LINKS, "warranty_expiry", {"mail": "warranty_expiry", "also": (), "note": "x"})
    monkeypatch.setitem(nm.EVENT_LINKS, "ghost_code", {"mail": "no_such_mail", "also": (), "note": "x"})
    d = client.get("/api/mail-types", headers=h).json()
    probs = _completeness_problems(d)
    assert any("ghost_code" in p for p in probs) and any("no_such_mail" in p for p in probs)


# ── ② 預設關＝零行為改變 ───────────────────────────────────────────────

def test_default_off_daily_checks_touch_nothing(calls, monkeypatch):
    from modules.case import case_deadlines as cd
    from modules.daily_tasks import api as dt
    def boom(*a, **k):
        raise AssertionError("開關關著時不該讀資料庫")
    monkeypatch.setattr(cd, "get_db", boom)
    monkeypatch.setattr(dt, "get_db", boom)
    for on in (False, True):                                                 # 沒有任何設定／只開總開關
        if on:
            _cal()
        cd._sync_warranty_calendar(); cd._sync_project_end_calendar(); dt._sync_range_task_calendar()
        assert calls == []
        assert [k for k in ("calsync.warranty_expiry", "calsync.range_task_due", "calsync.project_end") if _get_setting(k) is not None] == []


def test_run_daily_checks_survives_a_sync_failure(monkeypatch):
    from modules.case import case_deadlines as cd
    ran = []
    monkeypatch.setattr(cd, "_check_warranty_expiry", lambda: ran.append("w"))
    monkeypatch.setattr(cd, "_check_case_stage_deadline", lambda: ran.append("s"))
    monkeypatch.setattr(cd, "_check_case_project_timeline_deadline", lambda: ran.append("p"))
    monkeypatch.setattr(cd, "_sync_warranty_calendar", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(cd, "_sync_project_end_calendar", lambda: ran.append("e"))
    cd.run_daily_checks("daily")
    assert ran == ["w", "s", "p", "e"]


# ── ③ 對帳 ───────────────────────────────────────────────────────────

def _item(days, s="標題", d="說明"):
    return (_d(days), s, d)


def test_sync_creates_is_idempotent_updates_and_deletes(calls):
    _cal(["project_end"])
    cur = {"A": _item(5), "B": _item(9)}
    st = cs.sync_dated_events("project_end", cur)
    assert st["upserted"] == 2 and sorted(c[2] for c in calls if c[0] == "up") == ["A", "B"]
    calls.clear()
    assert cs.sync_dated_events("project_end", cur)["upserted"] == 0 and calls == []          # 冪等：不重打
    cur["A"] = _item(7)                                                                        # 改日期
    cs.sync_dated_events("project_end", cur)
    assert [(c[0], c[2], c[3]) for c in calls] == [("up", "A", _d(7))]
    calls.clear()
    cur["B"] = _item(9, s="改名")                                                              # 改內容
    cs.sync_dated_events("project_end", cur)
    assert [(c[0], c[2]) for c in calls] == [("up", "B")]
    calls.clear()
    del cur["A"]                                                                               # 來源消失
    cs.sync_dated_events("project_end", cur)
    assert calls == [("del", "project_end", "A")] and set(_get_setting("calsync.project_end")) == {"B"}


def test_sync_skips_past_dates_and_keeps_history(calls):
    _cal(["warranty_expiry"])
    cs.sync_dated_events("warranty_expiry", {"old": _item(-3), "new": _item(2)})
    assert [c[2] for c in calls] == ["new"], "日期已過不建（Q9）"
    calls.clear()
    today_plus = date.today() + timedelta(days=3)
    cs.sync_dated_events("warranty_expiry", {"new": _item(2)}, today=today_plus)               # 日期不變、只是過期：保留事件、只從表移除
    assert calls == [] and _get_setting("calsync.warranty_expiry") == {}
    cs.sync_dated_events("warranty_expiry", {}, today=today_plus)                              # 再來來源消失也不會刪（已不在表裡）
    assert calls == []


def test_sync_date_moved_into_the_past_deletes_the_future_event(calls):
    _cal(["warranty_expiry"])
    cs.sync_dated_events("warranty_expiry", {"x": _item(4)})
    calls.clear()
    cs.sync_dated_events("warranty_expiry", {"x": _item(-1)})
    assert calls == [("del", "warranty_expiry", "x")]
    # 反向對照：同一個來源日期沒動而過期 ⇒ 不刪（上一個測試）；沒有日期（None）⇒ 視為不成立而刪
    _cal(["warranty_expiry"])
    cs.sync_dated_events("warranty_expiry", {"y": _item(4)})
    calls.clear()
    cs.sync_dated_events("warranty_expiry", {"y": (None, "t", "d")})
    assert calls == [("del", "warranty_expiry", "y")]


def test_sync_does_not_advance_while_switch_is_off_and_catches_up_after(calls):
    _cal(["range_task_due"])
    cs.sync_dated_events("range_task_due", {"1": _item(5)})
    calls.clear()
    _cal([])                                                                                   # 種類開關關
    assert cs.sync_dated_events("range_task_due", {"1": _item(6), "2": _item(7)})["skipped"] == "event_off"
    _cal(["range_task_due"], enabled=False)                                                    # 總開關關
    assert cs.sync_dated_events("range_task_due", {})["skipped"] == "calendar_off"
    assert calls == [] and set(_get_setting("calsync.range_task_due")) == {"1"} and _get_setting("calsync.range_task_due")["1"][0] == _d(5)
    _cal(["range_task_due"])
    cs.sync_dated_events("range_task_due", {"1": _item(6), "2": _item(7)})                     # 重新打開 ⇒ 補齊關著期間的差異
    assert sorted((c[0], c[2], c[3]) for c in calls) == [("up", "1", _d(6)), ("up", "2", _d(7))]


def test_sync_call_cap_leaves_the_rest_for_the_next_run(calls):
    _cal(["project_end"])
    cur = {"k%02d" % i: _item(3 + i) for i in range(5)}
    cs.sync_dated_events("project_end", cur, max_calls=2)
    assert len(calls) == 2 and len(_get_setting("calsync.project_end")) == 2
    calls.clear()
    cs.sync_dated_events("project_end", cur, max_calls=10)
    assert len(calls) == 3 and len(_get_setting("calsync.project_end")) == 5


# ── ④ 三個來源 ───────────────────────────────────────────────────────

def _quote(quote_no, deal_tag, case_record, customer="客戶甲", project="專案乙"):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at, deal_tag) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (quote_no, "已核准", customer, project, 987654, json.dumps({"dealTag": deal_tag, "caseRecord": case_record}),
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal_tag))
        conn.commit()
    finally:
        conn.close()


def _ups(calls, code):
    return {c[2]: c for c in calls if c[0] == "up" and c[1] == code}


def test_warranty_source_only_won_cases_future_expiry_and_no_money(calls):
    from modules.case import case_deadlines as cd
    start = (TODAY - timedelta(days=330)).isoformat()                          # 12 個月 ⇒ 約 35 天後到期
    old = (TODAY - timedelta(days=900)).isoformat()                            # 早已過期
    _quote("Q-W1", "已成案", {"devices": [{"name": "攝影機", "sn": "SN1", "warrantyStart": start, "warrantyMonths": 12},
                                          {"name": "舊設備", "sn": "SN2", "warrantyStart": old, "warrantyMonths": 12},
                                          {"name": "無保固", "sn": "SN3"}]})
    _quote("Q-W2", "洽談中", {"devices": [{"name": "未成案", "sn": "SN4", "warrantyStart": start, "warrantyMonths": 12}]})
    _cal(["warranty_expiry"])
    cd._sync_warranty_calendar()
    ups = _ups(calls, "warranty_expiry")
    assert list(ups) == ["Q-W1#i0"], "只有已成案、未過期、有保固資料的設備"
    c = ups["Q-W1#i0"]
    assert "攝影機" in c[4] and "Q-W1" in c[5] and "客戶甲" in c[5]
    assert "987654" not in c[4] + c[5], "事件不放金額"
    calls.clear()
    cd._sync_warranty_calendar()
    assert calls == []                                                          # 隔天再跑不重打
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET deal_tag='已結案', data_json=json_set(data_json,'$.dealTag','已結案') WHERE quote_no='Q-W1'")
        conn.commit()
    finally:
        conn.close()
    cd._sync_warranty_calendar()
    assert calls == [("del", "warranty_expiry", "Q-W1#i0")]                    # 不再是已成案 ⇒ 刪


def test_project_end_source_open_cases_only_and_follows_edits(calls):
    from modules.case import case_deadlines as cd
    _quote("Q-P1", "已成案", {"projectTimeline": {"endDate": _d(10)}})
    _quote("Q-P2", "已結案", {"projectTimeline": {"endDate": _d(10)}})
    _quote("Q-P3", "已成案", {"projectTimeline": {"endDate": _d(-5)}})
    _quote("Q-P4", "已成案", {"projectTimeline": {}})
    _cal(["project_end"])
    cd._sync_project_end_calendar()
    ups = _ups(calls, "project_end")
    assert list(ups) == ["Q-P1"] and ups["Q-P1"][3] == _d(10) and "987654" not in ups["Q-P1"][4] + ups["Q-P1"][5]
    calls.clear()
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET data_json=json_set(data_json,'$.caseRecord.projectTimeline.endDate',?) WHERE quote_no='Q-P1'", (_d(20),))
        conn.commit()
    finally:
        conn.close()
    cd._sync_project_end_calendar()
    assert [(c[0], c[2], c[3]) for c in calls] == [("up", "Q-P1", _d(20))]


def test_range_task_source_unfinished_only_without_assignee_names(calls):
    from modules.daily_tasks import api as dt
    import db
    conn = db.get_db()
    try:
        def task(title, rtype, end, assigned, deleted=0):
            return conn.execute(
                "INSERT INTO daily_tasks (task_date, title, assigned_to, created_by, created_at, updated_at, is_deleted, recurrence_type, recurrence_end_date) "
                "VALUES (?,?,?,?,?,?,?,?,?)", (_d(0), title, json.dumps(assigned), "x", "", "", deleted, rtype, end)).lastrowid
        t1 = task("進行中", "range", _d(6), ["alice_zz", "bob_zz"])
        t2 = task("全員完成", "range", _d(6), ["alice_zz"])
        task("單日", "once", _d(6), ["alice_zz"])
        task("已刪除", "range", _d(6), ["alice_zz"], deleted=1)
        conn.execute("INSERT INTO daily_task_completions (task_id, username, occurrence_date, completed) VALUES (?,?,?,1)", (t2, "alice_zz", _d(0)))
        conn.execute("INSERT INTO daily_task_completions (task_id, username, occurrence_date, completed) VALUES (?,?,?,1)", (t1, "alice_zz", _d(0)))
        conn.commit()
    finally:
        conn.close()
    _cal(["range_task_due"])
    dt._sync_range_task_calendar()
    ups = _ups(calls, "range_task_due")
    assert list(ups) == [str(t1)] and ups[str(t1)][3] == _d(6)                  # bob 還沒完成 ⇒ 仍有事件
    assert "alice_zz" not in ups[str(t1)][4] + ups[str(t1)][5] and "bob_zz" not in ups[str(t1)][4] + ups[str(t1)][5]
    calls.clear()
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO daily_task_completions (task_id, username, occurrence_date, completed) VALUES (?,?,?,1)", (t1, "bob_zz", _d(1)))
        conn.commit()
    finally:
        conn.close()
    dt._sync_range_task_calendar()
    assert calls == [("del", "range_task_due", str(t1))]                        # 全員完成 ⇒ 刪


def test_mail_side_is_independent_of_the_calendar_switch(calls):
    """行事曆事件開關與寄信互不影響：開了事件，信件 guard／收件人設定不被碰。"""
    before = _get_setting("mail_recipient_overrides", {})
    _cal(["warranty_expiry", "range_task_due", "project_end"])
    from modules.case import case_deadlines as cd
    _quote("Q-I1", "已成案", {"projectTimeline": {"endDate": _d(3)}})
    cd._sync_project_end_calendar()
    assert _get_setting("mail_recipient_overrides", {}) == before
    assert not [k for k in ("caseproj_notif.Q-I1.0",) if _get_setting(k)]


# ── 付款待辦（payable_due）與預定付款日提醒信配對（第 42 班信件；稽核補件）──────────────

def test_payable_due_is_paired_with_the_two_reminder_mails_default_unchanged(client, make_user):
    h = _sa(client, make_user)
    d = client.get("/api/mail-types", headers=h).json()
    assert _completeness_problems(d) == []
    today, soon = (next(x for x in d["items"] if x["key"] == k) for k in ("payable_due_today", "payable_due_soon"))
    assert today["calendar"]["code"] == soon["calendar"]["code"] == "payable_due"
    assert today["calendar"]["primary"] is True and soon["calendar"]["primary"] is False
    assert today["calendar"]["disabledReason"] == "" and soon["calendar"]["disabledReason"] == ""
    assert "payable_due" not in {c["code"] for c in d["calendarOnly"]}, "已配對就不再是僅行事曆列"
    assert today["calendar"]["enabled"] is False and gc.event_switches({})["payable_due"] is False      # 預設關
    assert today["mailOff"] is False and soon["mailOff"] is False and today["override"]["mode"] == "default"   # 信件不受影響
    for label, desc in ((t[1], t[3]) for t in gc.EVENT_TYPES if t[0] == "payable_due"):
        assert not any(w in label + desc for w in ("金額：", "$")) and "不含金額" in desc


def test_reverse_control_payable_pairing_guard_goes_red(client, make_user, monkeypatch):
    h = _sa(client, make_user)
    monkeypatch.delitem(nm.EVENT_LINKS, "payable_due")
    d = client.get("/api/mail-types", headers=h).json()
    today = next(x for x in d["items"] if x["key"] == "payable_due_today")
    assert today["calendar"]["code"] == "" and today["calendar"]["disabledReason"], "拿掉配對就退回『沒有日期』的停用格——這正是要擋的狀態"
    assert "payable_due" in {c["code"] for c in d["calendarOnly"]}


# ── 稽核第 3 輪：失敗不記為已同步、請求上限、設備 key、短路 ──────────────────────

def test_failed_push_does_not_advance_state_and_is_retried(monkeypatch):
    """Google 暫時失敗：不能把項目記成已同步（否則永遠不會重試）；恢復後下一次補上。反向對照：成功才記。"""
    _cal(["project_end"])
    fail = {"on": True}
    done = []
    def up(code, s, d, dt, key):
        if fail["on"]:
            raise RuntimeError("Google 5xx")
        done.append(key)
        return True
    monkeypatch.setattr(gc, "_upsert_event_strict", up)
    monkeypatch.setattr(gc, "_delete_event_strict", lambda code, key: True)
    cur = {"A": _item(5), "B": _item(6), "C": _item(7), "D": _item(8)}
    st = cs.sync_dated_events("project_end", cur)
    assert st["upserted"] == 0 and st["failed"] == cs.MAX_CONSECUTIVE_FAILURES, "連續失敗 3 次就收手，不整批打"
    assert not _get_setting("calsync.project_end"), "失敗不可進對帳表"
    fail["on"] = False
    st = cs.sync_dated_events("project_end", cur)
    assert sorted(done) == ["A", "B", "C", "D"] and set(_get_setting("calsync.project_end")) == {"A", "B", "C", "D"}


def test_failed_delete_keeps_the_record_so_it_is_retried(monkeypatch):
    _cal(["project_end"])
    monkeypatch.setattr(gc, "_upsert_event_strict", lambda *a: True)
    monkeypatch.setattr(gc, "_delete_event_strict", lambda code, key: (_ for _ in ()).throw(RuntimeError("x")))
    cs.sync_dated_events("project_end", {"A": _item(5)})
    cs.sync_dated_events("project_end", {})                                    # 來源消失、刪除失敗
    assert set(_get_setting("calsync.project_end")) == {"A"}, "刪除失敗要留著記錄、下次再刪"
    monkeypatch.setattr(gc, "_delete_event_strict", lambda code, key: True)
    cs.sync_dated_events("project_end", {})
    assert _get_setting("calsync.project_end") == {}


def test_strict_functions_raise_and_public_wrappers_swallow(monkeypatch):
    _cal(["project_end"])
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(gc, "_find_merged_event", boom)
    with pytest.raises(RuntimeError):
        gc._upsert_event_strict("project_end", "t", "d", _d(3), "k")
    with pytest.raises(RuntimeError):
        gc._delete_event_strict("project_end", "k")
    gc.push_event_upsert_for_module("project_end", "t", "d", _d(3), "k")      # 既有契約：fire-and-forget，不丟
    gc.push_event_delete_for_module("project_end", "k")
    _cal([], enabled=True)
    assert gc._upsert_event_strict("project_end", "t", "d", _d(3), "k") is False       # 開關關 ⇒ 沒做（False，不是成功）


def test_daily_checks_actually_call_the_range_task_sync(monkeypatch):
    """變異對照：run_daily_checks 忘了呼叫對帳 ⇒ 這題紅（三種模式都要呼叫）。"""
    from modules.daily_tasks import api as dt
    ran = []
    monkeypatch.setattr(dt, "_sync_range_task_calendar", lambda: ran.append(1))
    monkeypatch.setattr(dt, "_check_overdue_and_notify", lambda *a, **k: None)
    monkeypatch.setattr(dt, "_check_range_task_deadline", lambda: None)
    for mode in ("daily", "startup"):
        dt.run_daily_checks(mode)
    assert len(ran) == 2


def test_master_switch_off_short_circuits_before_the_source_query(monkeypatch):
    from modules.case import case_deadlines as cd
    from modules.daily_tasks import api as dt
    def boom(*a, **k):
        raise AssertionError("總開關關閉時不該查來源資料表")
    monkeypatch.setattr(cd, "get_db", boom)
    monkeypatch.setattr(dt, "get_db", boom)
    _set_setting("google_calendar", {"enabled": False, "events": {c: True for c in NEW}})        # 事件種類全開、總開關關
    cd._sync_warranty_calendar(); cd._sync_project_end_calendar(); dt._sync_range_task_calendar()


def test_warranty_devices_sharing_a_serial_get_distinct_keys(calls):
    from modules.case import case_deadlines as cd
    start = (TODAY - timedelta(days=330)).isoformat()
    _quote("Q-W3", "已成案", {"devices": [
        {"id": 111, "name": "甲", "sn": "SAME", "warrantyStart": start, "warrantyMonths": 12},
        {"id": 222, "name": "乙", "sn": "SAME", "warrantyStart": start, "warrantyMonths": 12},
        {"name": "無id甲", "sn": "", "warrantyStart": start, "warrantyMonths": 12},
        {"name": "無id乙", "sn": "", "warrantyStart": start, "warrantyMonths": 12}]})
    _cal(["warranty_expiry"])
    cd._sync_warranty_calendar()
    assert sorted(_ups(calls, "warranty_expiry")) == ["Q-W3#111", "Q-W3#222", "Q-W3#i2", "Q-W3#i3"]
