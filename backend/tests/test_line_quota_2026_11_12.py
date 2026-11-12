# -*- coding: utf-8 -*-
"""LINE 額度常駐監控與門檻告警契約題（2026-11-12；PM 裁示 D3／D4／D5／D6）。

釘住：門檻驗證與預設、純函式 `evaluate` 的邊界、快取（5 分鐘內不重打 LINE）、狀態只在有變時才寫、
同一門檻同月只寄一次、一次跨多個門檻只寄一封且全部記為已警示、等寄送結果才記（False＝下次重試）、
換月／用量回落重置、改門檻後的補寄、無上限與讀不到不告警、推播後去抖動（同時只排一個）、每日備援已接線、端點權限與驗證。
LINE 一律換掉 `line_notify._http`；時間一律注入。
"""
import json
from datetime import datetime, timedelta

import pytest

TOKEN = "tok-SECRET-0123456789"
T0 = datetime(2026, 11, 12, 9, 0, 0)


class _Line:
    """假的 LINE：quota 與 consumption 兩支唯讀 GET。"""
    def __init__(self, used=0, limit=200, qtype="limited", status=200):
        self.used, self.limit, self.qtype, self.status, self.calls = used, limit, qtype, status, []
        self.quota_body = self.consumption_body = None          # 要測「LINE 回了怪東西」時直接指定回應內容

    def __call__(self, method, path, token, payload=None):
        self.calls.append(path)
        if self.status != 200:
            return self.status, {}
        if path.endswith("/quota/consumption"):
            return 200, ({"totalUsage": self.used} if self.consumption_body is None else self.consumption_body)
        if self.quota_body is not None:
            return 200, self.quota_body
        return 200, ({"type": "limited", "value": self.limit} if self.qtype == "limited" else {"type": "none"})


@pytest.fixture
def q(client, monkeypatch):
    from helpers import line_notify as L, line_quota as lq
    from helpers import email_notify
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN})
    _set_setting(lq.STATE_KEY, {})
    fake = _Line()
    monkeypatch.setattr(L, "_http", fake)
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    lq._mem.update(checked_at=None, failed_at=None, error="", fp=None)
    lq._pending = False
    mails = []
    ret = {"v": True}
    monkeypatch.setattr(email_notify, "notify_line_quota_warning",
                        lambda used, limit, threshold, thresholds=None, month="": (mails.append((used, limit, threshold, list(thresholds or []), month)), ret["v"])[1])
    lq.fake, lq.mails, lq.ret = fake, mails, ret
    yield lq
    lq._mem.update(checked_at=None, failed_at=None, error="", fp=None)
    lq._pending = False


# ── 門檻 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("v, want", [([80, 100], [80, 100]), ([100, 50, 80], [50, 80, 100]), ([1], [1]), ([5, 10, 20, 30, 40], [5, 10, 20, 30, 40]),
                                     ((70, 90), [70, 90])])
def test_normalize_thresholds_accepts_and_sorts(v, want):
    from helpers import line_quota as lq
    assert lq.normalize_thresholds(v) == want


@pytest.mark.parametrize("bad", [[], None, "80,100", [0], [101], [-5], [80, 80], [True], [80.5], ["80"], [1, 2, 3, 4, 5, 6], 80, {"a": 1}])
def test_normalize_thresholds_rejects(bad):
    from helpers import line_quota as lq
    with pytest.raises(ValueError):
        lq.normalize_thresholds(bad)


def test_thresholds_default_and_corrupt_fall_back_to_default(q):
    from helpers.settings import _get_setting, _set_setting
    assert q.thresholds() == [80, 100] and q.DEFAULT_THRESHOLDS == (80, 100)
    c = _get_setting("line_notify", {})
    for bad in ("x", [0], [], None):
        c["quota_thresholds"] = bad
        _set_setting("line_notify", c)
        assert q.thresholds() == [80, 100]
    c["quota_thresholds"] = [50, 90]
    _set_setting("line_notify", c)
    assert q.thresholds() == [50, 90]


# ── evaluate（純函式）─────────────────────────────────────────────────────

def test_evaluate_boundaries_use_integer_math():
    from helpers.line_quota import evaluate
    assert evaluate(159, 200, [80, 100], [])["crossed"] == []
    assert evaluate(160, 200, [80, 100], [])["crossed"] == [80]
    assert evaluate(199, 200, [80, 100], [])["crossed"] == [80]
    assert evaluate(200, 200, [80, 100], [])["crossed"] == [80, 100]
    assert evaluate(250, 200, [80, 100], [])["crossed"] == [80, 100], "超過上限也是已達"
    assert evaluate(1, 3, [33], [])["crossed"] == [33], "100*1 >= 33*3：整數比較"
    assert evaluate(160, 200, [80, 100], [80])["new"] == []
    assert evaluate(200, 200, [80, 100], [80])["new"] == [100]


@pytest.mark.parametrize("used, limit", [(10, None), (10, 0), (None, 200), ("x", 200), (-1, 200), (True, 200)])
def test_evaluate_no_alert_when_limit_missing_or_garbage(used, limit):
    from helpers.line_quota import evaluate
    r = evaluate(used, limit, [80, 100], [])
    assert r["percent"] is None and r["crossed"] == [] and r["new"] == []


# ── snapshot／refresh／快取／寫入量 ────────────────────────────────────────

def test_not_configured_returns_ok_false_and_writes_nothing(client, monkeypatch):
    from helpers import line_quota as lq
    from helpers.settings import _get_setting, _set_setting
    _set_setting("line_notify", {})
    _set_setting(lq.STATE_KEY, {})
    lq._mem["checked_at"] = None
    v = lq.snapshot(now=T0)
    assert v["ok"] is False and "token" in v["error"] and v["level"] == "unknown"
    assert not _get_setting(lq.STATE_KEY, {})


def test_refresh_writes_state_and_view_shape(q):
    q.fake.used = 50
    v = q.refresh(T0)
    assert (v["ok"], v["used"], v["limit"], v["month"], v["level"], v["unlimited"]) == (True, 50, 200, "2026-11", "ok", False)
    assert v["percent"] == 25.0 and v["thresholds"] == [80, 100] and v["checked_at"] == T0.isoformat(timespec="seconds")
    from helpers.settings import _get_setting
    st = _get_setting(q.STATE_KEY, {})
    assert st["used"] == 50 and st["limit"] == 200 and st["alerted"] == []


def test_levels(q):
    for used, level in [(0, "ok"), (159, "ok"), (160, "warn"), (199, "warn"), (200, "alert")]:
        q.fake.used = used
        assert q.refresh(T0)["level"] == level, used


def test_snapshot_uses_cache_within_max_age_and_refreshes_after(q):
    q.fake.used = 10
    q.snapshot(now=T0)
    n = len(q.fake.calls)
    q.fake.used = 99
    assert q.snapshot(now=T0 + timedelta(seconds=299))["used"] == 10 and len(q.fake.calls) == n, "5 分鐘內不重打 LINE"
    assert q.snapshot(now=T0 + timedelta(seconds=301))["used"] == 99 and len(q.fake.calls) == n + 2
    assert q.snapshot(now=T0 + timedelta(seconds=302), force=True)["used"] == 99 and len(q.fake.calls) == n + 4, "force 一律重讀"


def test_state_is_only_written_when_content_changes(q, monkeypatch):
    writes = []
    real = q._set_setting
    monkeypatch.setattr(q, "_set_setting", lambda k, v: (writes.append(k), real(k, v))[1])
    q.fake.used = 10
    q.refresh(T0)
    assert writes == [q.STATE_KEY]
    q.refresh(T0 + timedelta(minutes=6))
    q.refresh(T0 + timedelta(minutes=12))
    assert writes == [q.STATE_KEY], "用量沒變不重寫（硬碟寫入越少越好）"
    q.fake.used = 11
    q.refresh(T0 + timedelta(minutes=18))
    assert writes == [q.STATE_KEY, q.STATE_KEY]


def test_unlimited_plan_shows_usage_without_percent_and_never_alerts(q):
    q.fake.qtype, q.fake.used = "none", 9999
    v = q.refresh(T0)
    assert v["ok"] and v["unlimited"] and v["limit"] is None and v["percent"] is None and v["level"] == "unlimited"
    r = q.check_and_alert(T0 + timedelta(minutes=10))
    assert r["alerted"] is False and q.mails == []


def test_line_api_failure_gives_ok_false_and_keeps_old_state(q):
    q.fake.used = 40
    q.refresh(T0)
    q.fake.status = 500
    v = q.refresh(T0 + timedelta(minutes=10))
    assert v["ok"] is False and v["error"] and v["used"] == 40, "沿用上次的數字當參考，但標示讀取失敗"
    assert q.check_and_alert(T0 + timedelta(minutes=20), force=True)["alerted"] is False and q.mails == []


def test_snapshot_never_raises(q, monkeypatch):
    from helpers import line_notify as L
    monkeypatch.setattr(L, "quota", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    v = q.snapshot(now=T0, force=True)
    assert v["ok"] is False and "RuntimeError" in v["error"]


# ── 告警 ──────────────────────────────────────────────────────────────────

def test_alert_once_per_threshold_per_month(q):
    q.fake.used = 150
    assert q.check_and_alert(T0)["alerted"] is False and q.mails == []
    q.fake.used = 160
    r = q.check_and_alert(T0 + timedelta(minutes=10))
    assert r["alerted"] is True and q.mails == [(160, 200, 80, [80, 100], "2026-11")]
    q.fake.used = 170
    assert q.check_and_alert(T0 + timedelta(minutes=20))["alerted"] is False and len(q.mails) == 1, "同一門檻不重寄"
    q.fake.used = 200
    assert q.check_and_alert(T0 + timedelta(minutes=30))["alerted"] is True
    assert q.mails[-1][2] == 100 and len(q.mails) == 2
    q.fake.used = 200
    assert q.check_and_alert(T0 + timedelta(minutes=40))["alerted"] is False and len(q.mails) == 2


def test_crossing_several_thresholds_at_once_sends_one_mail_and_records_all(q):
    from helpers.settings import _get_setting
    q.fake.used = 200
    r = q.check_and_alert(T0)
    assert r["alerted"] and len(q.mails) == 1 and q.mails[0][2] == 100, "一次跨多個只寄一封，講最高那個"
    assert _get_setting(q.STATE_KEY, {})["alerted"] == [80, 100]
    q.fake.used = 201
    q.check_and_alert(T0 + timedelta(minutes=10))
    assert len(q.mails) == 1, "80% 不會之後又補寄"


def test_flag_written_only_when_send_outcome_allows_and_retry_next_time(q):
    from helpers.settings import _get_setting
    q.fake.used = 170
    q.ret["v"] = False
    assert q.check_and_alert(T0)["alerted"] is False
    assert _get_setting(q.STATE_KEY, {})["alerted"] == [], "寄失敗不記，否則永遠不會再試"
    q.ret["v"] = True
    assert q.check_and_alert(T0 + timedelta(minutes=10))["alerted"] is True and len(q.mails) == 2
    assert q.check_and_alert(T0 + timedelta(minutes=20))["alerted"] is False and len(q.mails) == 2


def test_month_rollover_resets_alerted(q):
    q.fake.used = 170
    q.check_and_alert(T0)
    nxt = datetime(2026, 12, 1, 8, 0)
    q.fake.used = 20
    v = q.refresh(nxt)
    assert v["alerted"] == [] and v["month"] == "2026-12"
    q.fake.used = 165
    assert q.check_and_alert(nxt + timedelta(days=3))["alerted"] is True and len(q.mails) == 2, "新月份同一門檻可以再叫一次"


def test_usage_drop_in_same_month_is_a_new_cycle(q):
    q.fake.used = 170
    q.check_and_alert(T0)
    q.fake.used = 30                              # LINE 重置／換方案
    q.refresh(T0 + timedelta(hours=1))
    q.fake.used = 165
    assert q.check_and_alert(T0 + timedelta(hours=2))["alerted"] is True and len(q.mails) == 2


def test_dropping_below_threshold_only_updates_state_no_mail(q):
    q.fake.used = 170
    q.check_and_alert(T0)
    q.fake.used = 100
    r = q.check_and_alert(T0 + timedelta(minutes=10))
    assert r["alerted"] is False and len(q.mails) == 1 and r["view"]["used"] == 100


def test_changing_thresholds_resends_for_newly_added_crossed_threshold(q):
    from helpers.settings import _get_setting, _set_setting
    q.fake.used = 170
    q.check_and_alert(T0)                         # 預設 [80,100]：80 已寄
    assert [m[2] for m in q.mails] == [80]
    c = _get_setting("line_notify", {})
    c["quota_thresholds"] = [50, 100]
    _set_setting("line_notify", c)
    r = q.check_and_alert(T0 + timedelta(minutes=10), force=True)
    assert r["alerted"] is True and [m[2] for m in q.mails] == [80, 50], "新增且已超過的門檻補寄一次"
    q.check_and_alert(T0 + timedelta(minutes=20), force=True)
    assert len(q.mails) == 2
    c["quota_thresholds"] = [90, 100]             # 只留 100；舊的 80／50 紀錄不再算
    _set_setting("line_notify", c)
    q.fake.used = 190
    q.check_and_alert(T0 + timedelta(minutes=30), force=True)
    assert [m[2] for m in q.mails][-1] == 90


def test_check_and_alert_never_raises_and_mail_exception_does_not_mark(q, monkeypatch):
    from helpers import email_notify
    from helpers.settings import _get_setting
    monkeypatch.setattr(email_notify, "notify_line_quota_warning", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp")))
    q.fake.used = 190
    r = q.check_and_alert(T0)
    assert r["alerted"] is False and _get_setting(q.STATE_KEY, {})["alerted"] == []


# ── 推播後去抖動 ──────────────────────────────────────────────────────────

class _Timers:
    def __init__(self):
        self.made = []

    def __call__(self, delay, fn):
        t = type("T", (), {"daemon": False, "name": "", "delay": delay, "started": False})()
        t.fn = lambda: fn()
        t.start = lambda: setattr(t, "started", True)
        self.made.append(t)
        return t


@pytest.mark.line_quota_real_timer
def test_after_push_debounces_and_schedules_one_at_a_time(q, monkeypatch):
    timers = _Timers()
    monkeypatch.setattr(q.threading, "Timer", timers)
    q.after_push(T0)
    q.after_push(T0)
    q.after_push(T0)
    assert len(timers.made) == 1 and timers.made[0].started and timers.made[0].delay == q._SETTLE_SECONDS, "從沒刷新過＝快取已過期：只等結算延遲"
    timers.made[0].fn()                             # 排程到了：讀用量並檢查
    assert q.fake.calls, "到期後會去讀 LINE 用量"
    q.after_push(T0 + timedelta(seconds=1))
    assert len(timers.made) == 2, "上一個跑完後可以再排"


@pytest.mark.line_quota_real_timer
def test_after_push_delay_accounts_for_recent_refresh(q, monkeypatch):
    timers = _Timers()
    monkeypatch.setattr(q.threading, "Timer", timers)
    q.refresh(T0)
    q.after_push(T0 + timedelta(seconds=100))
    assert timers.made[-1].delay == pytest.approx(q.CACHE_SECONDS - 100)
    q._pending = False
    q.after_push(T0 + timedelta(seconds=299))
    assert timers.made[-1].delay == q._SETTLE_SECONDS, "至少等結算延遲"


@pytest.mark.line_quota_real_timer
def test_after_push_never_raises_and_clears_pending_when_timer_fails(q, monkeypatch):
    monkeypatch.setattr(q.threading, "Timer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no threads")))
    q.after_push(T0)
    assert q._pending is False


def test_successful_push_async_triggers_after_push_and_failed_push_does_not(q, monkeypatch):
    from helpers import line_notify as L
    hits = []
    monkeypatch.setattr(q, "after_push", lambda *a, **k: hits.append(1))
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    L.push_async(["U" + "a" * 32], "hi").join(5)
    assert hits == [1]
    monkeypatch.setattr(L, "_http", _Line(status=500))
    L.push_async(["U" + "a" * 32], "hi").join(5)
    assert hits == [1], "推播失敗不排額度檢查"


# ── 每日備援已接線 ─────────────────────────────────────────────────────────

def test_daily_backup_check_is_wired_and_starts_a_background_check(client, monkeypatch):
    import inspect
    import helpers.system_checks as sc
    from helpers import line_quota as lq
    assert "_check_line_quota()" in inspect.getsource(sc.run_all)
    started = []
    monkeypatch.setattr(sc.threading, "Thread", lambda target, args=(), kwargs=None, daemon=None, name=None:
                        type("T", (), {"start": lambda s: started.append(target)})())
    sc._check_line_quota()
    assert started == [lq.check_and_alert]


# ── 信件本體（本體要真的跑；不 patch 掉 notify_line_quota_warning）──────────

def _handle(outcome):
    class H:
        def wait(self):
            return outcome
    return H()


def test_mail_body_builds_and_returns_flag_permission(monkeypatch):
    import helpers.email_notify as en
    sent = []
    monkeypatch.setattr(en, "_admin_emails", lambda *a, **k: ["x@example.invalid"])
    monkeypatch.setattr(en, "_async_send", lambda to, subject, html: (sent.append((to, subject, html)), _handle(en.SEND_SENT))[1])
    assert en.notify_line_quota_warning(170, 200, 80, [80, 100], "2026-11") is True
    to, subject, html = sent[0]
    assert "85%" in subject and "170" in html and "200" in html and "80%" in html and "LINE" in html


@pytest.mark.parametrize("outcome, may_mark", [("sent", True), ("unknown", True), ("permanent_fail", True), ("transient_fail", False), ("skipped", False)])
def test_mail_flag_mapping(monkeypatch, outcome, may_mark):
    import helpers.email_notify as en
    monkeypatch.setattr(en, "_admin_emails", lambda *a, **k: ["x@example.invalid"])
    monkeypatch.setattr(en, "_async_send", lambda *a, **k: _handle(outcome))
    assert en.notify_line_quota_warning(170, 200, 80, [80, 100], "2026-11") is may_mark


def test_mail_without_recipients_returns_false(monkeypatch):
    import helpers.email_notify as en
    monkeypatch.setattr(en, "_admin_emails", lambda *a, **k: [])
    assert en.notify_line_quota_warning(170, 200, 80, [80], "2026-11") is False


def test_mail_type_registered_and_locked_on():
    from helpers import mail_types, notify_matrix
    t = mail_types.get("line_quota_warning")
    assert t is not None and t.group == "superadmins"
    assert "line_quota_warning" in notify_matrix.MAIL_OFF_LOCKED, "PM 裁示 D5：額度告警不可被關閉"


# ── 端點 ──────────────────────────────────────────────────────────────────

def _hdr(client, make_user, name, role):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_quota_endpoint_superadmin_only_and_refresh_param(client, q, make_user):
    sa = _hdr(client, make_user, "qsa", "superadmin")
    ad = _hdr(client, make_user, "qad", "admin")
    assert client.get("/api/settings/line-notify/quota", headers=ad).status_code == 403
    q.fake.used = 60
    g = client.get("/api/settings/line-notify/quota", headers=sa).json()
    assert g["ok"] and g["used"] == 60 and g["limit"] == 200 and g["thresholds"] == [80, 100]
    n = len(q.fake.calls)
    q.fake.used = 70
    assert client.get("/api/settings/line-notify/quota", headers=sa).json()["used"] == 60 and len(q.fake.calls) == n, "快取"
    assert client.get("/api/settings/line-notify/quota?refresh=true", headers=sa).json()["used"] == 70


def test_thresholds_saved_through_main_settings_with_validation_and_audit(client, q, make_user):
    sa = _hdr(client, make_user, "qsa2", "superadmin")
    for bad in ([], [0], [101], [80, 80], "80", [1, 2, 3, 4, 5, 6], [True]):
        r = client.put("/api/settings/line-notify", json={"quota_thresholds": bad}, headers=sa)
        assert r.status_code == 400, (bad, r.text)
    assert client.put("/api/settings/line-notify", json={"quota_thresholds": [95, 50]}, headers=sa).status_code == 200
    g = client.get("/api/settings/line-notify", headers=sa).json()
    assert g["quota_thresholds"] == [50, 95]
    assert client.put("/api/settings/line-notify", json={"include_links": False}, headers=sa).status_code == 200
    assert client.get("/api/settings/line-notify", headers=sa).json()["quota_thresholds"] == [50, 95], "沒帶欄位的儲存不會洗掉門檻"
    assert q.thresholds() == [50, 95]
    from helpers.settings import _get_setting
    assert TOKEN not in json.dumps(_get_setting(q.STATE_KEY, {})), "狀態裡不放 token"


# ══ K 審 F1：refresh 與「記旗標」交錯不可互相蓋掉 ═════════════════════════════

def test_refresh_and_flag_write_do_not_overwrite_each_other(q, monkeypatch):
    """設定頁載入（refresh）寫狀態到一半時，告警剛好要記旗標：兩者必須串行，最後 alerted 要保留、用量是最新的、信只一封。"""
    import threading
    import time
    from helpers.settings import _get_setting
    q.fake.used = 170
    q.refresh(T0)                                    # 狀態：used=170、alerted=[]
    q.fake.used = 171
    in_write = threading.Event()
    real = q._set_setting

    def slow(key, value):
        if threading.current_thread().name == "t_refresh":
            in_write.set()
            time.sleep(0.4)                          # 拖住 refresh 的寫入，讓另一條執行緒有機會在這段時間記旗標
        return real(key, value)
    monkeypatch.setattr(q, "_set_setting", slow)
    t1 = threading.Thread(target=lambda: q.refresh(T0 + timedelta(minutes=10)), name="t_refresh")
    t1.start()
    assert in_write.wait(5)
    out = {}
    t2 = threading.Thread(target=lambda: out.update(q.check_and_alert(T0 + timedelta(minutes=10, seconds=1))), name="t_check")
    t2.start()
    t1.join(10)
    t2.join(10)
    st = _get_setting(q.STATE_KEY, {})
    assert out.get("alerted") is True and len(q.mails) == 1
    assert st["alerted"] == [80], "旗標被 refresh 的舊值蓋回去了 ⇒ 下次會重寄同一門檻"
    assert st["used"] == 171, "refresh 的最新用量也要保留（不能被旗標寫入蓋成舊值）"


# ══ K 審 F2：LINE 回怪東西＝讀不到，不補 0、不當無上限 ═══════════════════════════

@pytest.mark.parametrize("cons, quota", [
    ({}, None),                                          # totalUsage 缺
    ({"totalUsage": None}, None),
    ({"totalUsage": "170"}, None),
    ({"totalUsage": True}, None),
    ({"totalUsage": -3}, None),
    (None, {"type": "limited"}),                         # limited 但 value 缺
    (None, {"type": "limited", "value": "200"}),
    (None, {"type": "limited", "value": None}),
    (None, {"type": "weird", "value": 200}),             # 不認得的類型
    (None, {}),                                          # 型別也缺
])
def test_malformed_line_answers_are_unreadable_not_zero_or_unlimited(q, cons, quota):
    from helpers import line_notify as L
    q.fake.consumption_body, q.fake.quota_body = cons, quota
    r = L.quota()
    assert r["ok"] is False and r["error"], r
    v = q.refresh(T0)
    assert v["ok"] is False and v["used"] is None and v["unlimited"] is False
    from helpers.settings import _get_setting
    assert not _get_setting(q.STATE_KEY, {}), "讀不到時不寫狀態"


def test_malformed_answer_does_not_clear_alerted_or_cause_a_second_mail(q):
    from helpers.settings import _get_setting
    q.fake.used = 170
    q.check_and_alert(T0)
    assert len(q.mails) == 1
    q.fake.consumption_body = {}                         # LINE 這一次回的資料缺 totalUsage（以前會被當 used=0 ⇒ 清掉 alerted）
    v = q.refresh(T0 + timedelta(minutes=10))
    assert v["ok"] is False
    q.fake.consumption_body = None
    q.fake.used = 171
    q.check_and_alert(T0 + timedelta(minutes=20), force=True)
    assert len(q.mails) == 1 and _get_setting(q.STATE_KEY, {})["alerted"] == [80]


def test_limited_without_value_is_not_shown_as_unlimited(q):
    q.fake.quota_body = {"type": "limited"}
    v = q.snapshot(now=T0, force=True)
    assert v["ok"] is False and v["unlimited"] is False


def test_real_unlimited_plan_still_reads_fine(q):
    q.fake.quota_body = {"type": "none"}
    q.fake.used = 5
    v = q.refresh(T0)
    assert v["ok"] and v["unlimited"] and v["limit"] is None and v["used"] == 5


# ══ K 審 F3：同月小幅回落不算新週期（遲滯）════════════════════════════════════

def test_small_dip_in_same_month_keeps_alerted_but_real_drop_clears_it(q):
    from helpers.settings import _get_setting
    q.fake.used = 170
    q.check_and_alert(T0)
    assert len(q.mails) == 1
    for i, used in enumerate([158, 150, 169, 161]):      # LINE 統計延遲造成的小幅起伏（150 剛好＝75%＝門檻 − 遲滯，仍保留）
        q.fake.used = used
        q.check_and_alert(T0 + timedelta(minutes=10 * (i + 1)), force=True)
    assert len(q.mails) == 1 and _get_setting(q.STATE_KEY, {})["alerted"] == [80], "小幅起伏不重寄"
    q.fake.used = 149                                    # < 75%：真的回落
    q.check_and_alert(T0 + timedelta(minutes=60), force=True)
    assert _get_setting(q.STATE_KEY, {})["alerted"] == []
    q.fake.used = 165
    q.check_and_alert(T0 + timedelta(minutes=70), force=True)
    assert len(q.mails) == 2


def test_plan_upgrade_with_bigger_limit_clears_alerted_when_no_longer_crossed(q):
    q.fake.used, q.fake.limit = 170, 200
    q.check_and_alert(T0)
    q.fake.limit = 1000                                   # 升級方案：17%
    q.refresh(T0 + timedelta(minutes=10))
    from helpers.settings import _get_setting
    assert _get_setting(q.STATE_KEY, {})["alerted"] == [], "上限放大後百分比掉到 17%：舊警示要清掉，之後再到 80% 才會再寄"
    q.fake.used = 850
    q.check_and_alert(T0 + timedelta(minutes=20), force=True)
    assert len(q.mails) == 2


# ══ K 審 F4：沒啟用／本機不允許對外發送 ⇒ 不連 LINE、不寄信 ═══════════════════════

def test_disabled_line_means_no_http_and_no_mail(q):
    from helpers.settings import _get_setting, _set_setting
    c = _get_setting("line_notify", {})
    c["enabled"] = False
    _set_setting("line_notify", c)
    q.fake.used = 190
    r = q.check_and_alert(T0, force=True)
    assert r["alerted"] is False and q.fake.calls == [] and q.mails == []


def test_dev_machine_marker_means_no_http_and_no_mail(q, monkeypatch):
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (False, "測試：開發機標記"))
    q.fake.used = 190
    r = q.check_and_alert(T0, force=True)
    assert r["alerted"] is False and q.fake.calls == [] and q.mails == []


@pytest.mark.line_quota_real_timer
def test_after_push_schedules_nothing_when_inactive(q, monkeypatch):
    timers = _Timers()
    monkeypatch.setattr(q.threading, "Timer", timers)
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (False, "測試：開發機標記"))
    q.after_push(T0)
    assert timers.made == [] and q._pending is False


def test_settings_page_snapshot_still_works_when_line_is_disabled_but_token_exists(q):
    """用量條只要有 token 就能看（停用 LINE 不影響「看」）；只有告警與備援檢查看啟用狀態。"""
    from helpers.settings import _get_setting, _set_setting
    c = _get_setting("line_notify", {})
    c["enabled"] = False
    _set_setting("line_notify", c)
    q.fake.used = 33
    assert q.snapshot(now=T0, force=True)["used"] == 33


# ══ K 審 F5：讀取失敗負快取 ═══════════════════════════════════════════════════

def test_failed_read_is_negatively_cached_for_a_minute_and_force_bypasses(q):
    q.fake.status = 503
    assert q.snapshot(now=T0)["ok"] is False
    n = len(q.fake.calls)
    assert q.snapshot(now=T0 + timedelta(seconds=30))["ok"] is False and len(q.fake.calls) == n, "60 秒內不重打"
    assert q.snapshot(now=T0 + timedelta(seconds=61))["ok"] is False and len(q.fake.calls) > n, "過了就再試"
    n = len(q.fake.calls)
    q.snapshot(now=T0 + timedelta(seconds=62), force=True)
    assert len(q.fake.calls) > n, "手動重新整理略過負快取"
    q.fake.status = 200
    q.fake.used = 5
    assert q.snapshot(now=T0 + timedelta(seconds=63), force=True)["ok"] is True
    n = len(q.fake.calls)
    assert q.snapshot(now=T0 + timedelta(seconds=64))["used"] == 5 and len(q.fake.calls) == n, "成功後負快取清掉、改用正快取"


# ══ T80 閘門 e2e 紅燈根因：負快取沒有跟著 token 失效 ═══════════════════════════════

def test_negative_cache_is_dropped_when_the_token_changes(q):
    """沒設 token 時打開設定頁 ⇒ 讀取失敗並記負快取；60 秒內設好 token 再開頁（非強制重讀），必須重新向 LINE 讀，不能回舊的失敗。
    （閘門 e2e：同一行程裡前一題開了通知設定頁＝失敗，下一題設好 token 再開頁卻 10 秒都顯示 null / null。）"""
    from helpers.settings import _get_setting, _set_setting
    good = _get_setting("line_notify", {})
    _set_setting("line_notify", {})                              # 沒 token
    assert q.snapshot(now=T0)["ok"] is False
    _set_setting("line_notify", good)                            # 管理員設好 token（可能是另一個人／另一個分頁）
    q.fake.used = 40
    v = q.snapshot(now=T0 + timedelta(seconds=5))
    assert v["ok"] is True and v["used"] == 40, v


def test_positive_cache_is_dropped_when_the_token_changes(q):
    from helpers.settings import _get_setting, _set_setting
    q.fake.used = 40
    assert q.snapshot(now=T0)["used"] == 40
    c = _get_setting("line_notify", {})
    c["channel_access_token"] = TOKEN + "B"              # 換成另一個官方帳號：舊帳號的用量不能留著
    _set_setting("line_notify", c)
    q.fake.used = 7
    assert q.snapshot(now=T0 + timedelta(seconds=5))["used"] == 7
