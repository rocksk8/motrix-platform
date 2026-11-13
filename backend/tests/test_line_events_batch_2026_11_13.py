"""LINE 事件矩陣票（2026-11-13）：批次端點 `POST /api/settings/line-notify/events/batch`、「新開啟預設只發給我」、按日計數。

重點（PM／hichan-9 的審查點）：
- 整批要嘛全部成功、要嘛全部不改；整批只寫一次設定、只記一筆稽核
- 權限（只有最高管理者）、請求輸入嚴格（布林、keys 去重與上限、roles「沒帶」≠「null」、不認得的欄位）
- 批次關閉「重要」告警要 `confirm_critical`（伺服器端強制）
- `_lock` 不可重入：批次帶 audience 不會死結
- 事件從關到開、沒指定對象 ⇒ 預設只發給操作者（批次與單項端點）
- 按日計數：台灣日期、跨日／跨月、保留 31 天、舊的「本月」格式相容、前 30 天未滿要標示
夾具沿用 `test_line_events_all_2026_11_13`（LINE 啟用、五位使用者、攔截 push）。
"""
import threading
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_line_events_all_2026_11_13 import _hdr, _mk, env  # noqa: F401  夾具與小工具共用

URL = "/api/settings/line-notify/events/batch"
CRIT = "backup_stale"                    # priority=critical
NORMAL = ("approval_request", "next_tier", "returned")


def _cfg():
    from helpers import line_notify as L
    return L._cfg()


def _snapshot():
    import copy
    return copy.deepcopy(_cfg())


def _count_audit(action):
    from db import get_db
    c = get_db()
    try:
        return c.execute("SELECT COUNT(*) FROM audit_log WHERE action=?", (action,)).fetchone()[0]
    finally:
        c.close()


@pytest.fixture
def writes(monkeypatch):
    """計算對 `line_notify` 設定的寫入次數。"""
    from helpers import line_notify as L
    real = L._set_setting
    calls = []

    def counting(key, value):
        if key == L.SETTING_KEY:
            calls.append(value)
        return real(key, value)
    monkeypatch.setattr(L, "_set_setting", counting)
    return calls


# ── 基本：批次套用、整批只寫一次、只記一筆稽核 ───────────────────────────────

def test_batch_applies_to_all_keys_with_one_write_and_one_audit_row(client, env, writes):
    sa = _hdr(client, "sa")
    body = {"keys": list(NORMAL), "enabled": True, "audience": {"mode": "only", "roles": ["admin"], "users": ["amy"]}}
    r = client.post(URL, json=body, headers=sa)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and sorted(j["changed"]) == sorted(NORMAL) and j["unchanged"] == []
    assert len(writes) == 1, "整批只寫一次設定（不是每個事件各寫一次）"
    cfg = _cfg()
    assert all(cfg["events"][k] is True for k in NORMAL)
    assert all(cfg["audiences"][k] == {"mode": "only", "roles": ["admin"], "users": ["amy"]} for k in NORMAL)
    assert _count_audit("settings.line_notify.batch") == 1
    assert _count_audit("settings.line_notify.event") == 0 and _count_audit("settings.line_notify.audience") == 0, "批次不會另外記單項稽核"


def test_batch_reports_unchanged_and_is_idempotent(client, env):
    sa = _hdr(client, "sa")
    body = {"keys": ["approval_request"], "enabled": True, "audience": {"mode": "only", "roles": [], "users": ["amy"]}}
    assert client.post(URL, json=body, headers=sa).json()["changed"] == ["approval_request"]
    again = client.post(URL, json=body, headers=sa).json()
    assert again["changed"] == [] and again["unchanged"] == ["approval_request"]


def test_batch_keys_are_deduplicated_and_ordered(client, env):
    sa = _hdr(client, "sa")
    r = client.post(URL, json={"keys": ["next_tier", "approval_request", "next_tier"], "enabled": True, "audience": {"mode": "business"}}, headers=sa)
    assert r.status_code == 200 and r.json()["changed"] == ["next_tier", "approval_request"]


# ── 全部成功或全部不改 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    {"keys": ["approval_request", "no_such_event"], "enabled": True},                                   # 有一個不是已接線事件
    {"keys": ["approval_request", "bonus_submitted"], "enabled": True},                                  # 薪資獎金類永遠不接線
    {"keys": ["approval_request", "next_tier"], "audience": {"mode": "only", "users": ["ghost"]}},       # 帳號不存在
    {"keys": ["approval_request", "next_tier"], "audience": {"mode": "only"}},                           # only 沒有任何人
    {"keys": ["approval_request", "next_tier"], "audience": {"mode": "weird"}},
    {"keys": ["approval_request", "next_tier"], "audience": {"mode": "business", "users": ["amy"]}},     # business 不收指定人員
    {"keys": ["approval_request", "next_tier"], "roles": ["superadmin", "not_a_role"]},
])
def test_any_invalid_item_means_nothing_changes(client, env, writes, bad):
    sa = _hdr(client, "sa")
    before = _snapshot()
    r = client.post(URL, json=bad, headers=sa)
    assert r.status_code == 400, r.text
    assert _snapshot() == before, "整批不改"
    assert writes == [] and _count_audit("settings.line_notify.batch") == 0


def test_person_without_module_permission_for_one_event_rejects_the_whole_batch(client, env):
    """amy（業務）沒有會計模組：批次裡只要有一個事件需要會計權限，整批就不改。"""
    sa = _hdr(client, "sa")
    before = _snapshot()
    r = client.post(URL, json={"keys": ["approval_request", "voucher_submitted"], "enabled": True, "audience": {"mode": "only", "users": ["amy"]}}, headers=sa)
    assert r.status_code == 400 and "權限" in r.json()["detail"]
    assert _snapshot() == before


# ── 權限 ─────────────────────────────────────────────────────────────────────

def test_only_superadmin_may_batch(client, env):
    body = {"keys": ["approval_request"], "enabled": True}
    before = _snapshot()
    for who in ("bob", "amy", "carol", "dan"):
        assert client.post(URL, json=body, headers=_hdr(client, who)).status_code == 403, who
    assert client.post(URL, json=body).status_code in (401, 403)
    assert _snapshot() == before


# ── 重要告警：伺服器端強制二次確認 ──────────────────────────────────────────

def _turn_on(client, sa, *keys):
    r = client.post(URL, json={"keys": list(keys), "enabled": True, "audience": {"mode": "only", "users": ["sa"]}}, headers=sa)
    assert r.status_code == 200, r.text


def test_batch_off_with_critical_event_needs_confirm_critical(client, env, writes):
    sa = _hdr(client, "sa")
    _turn_on(client, sa, CRIT, "approval_request")
    writes.clear()
    before = _snapshot()
    r = client.post(URL, json={"keys": [CRIT, "approval_request"], "enabled": False}, headers=sa)
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["code"] == "confirm_critical_required" and [x["key"] for x in d["critical"]] == [CRIT] and d["critical"][0]["name"]
    assert _snapshot() == before and writes == [], "沒確認 ⇒ 連非重要的那一個也不關（整批不改）"
    for bad in ("true", 1, "yes", [True]):
        assert client.post(URL, json={"keys": [CRIT], "enabled": False, "confirm_critical": bad}, headers=sa).status_code == 400, bad
    assert _snapshot() == before
    ok = client.post(URL, json={"keys": [CRIT, "approval_request"], "enabled": False, "confirm_critical": True}, headers=sa)
    assert ok.status_code == 200 and ok.json()["critical_off"] == [CRIT]
    assert _cfg()["events"][CRIT] is False and _cfg()["events"]["approval_request"] is False


def test_non_critical_batch_off_and_critical_batch_on_need_no_confirm(client, env):
    sa = _hdr(client, "sa")
    _turn_on(client, sa, "approval_request", CRIT)
    assert client.post(URL, json={"keys": ["approval_request"], "enabled": False}, headers=sa).status_code == 200
    # 重要事件「已經是關的」再關：不需要確認；開啟重要事件也不需要
    assert client.post(URL, json={"keys": [CRIT], "enabled": False, "confirm_critical": True}, headers=sa).status_code == 200
    assert client.post(URL, json={"keys": [CRIT], "enabled": False}, headers=sa).status_code == 200
    assert client.post(URL, json={"keys": [CRIT], "enabled": True}, headers=sa).status_code == 200


def test_critical_confirm_is_rechecked_inside_the_lock(env, monkeypatch):
    """驗證到寫入之間別人把重要事件打開了：進鎖後複查，沒確認就拒絕。"""
    from helpers import line_notify as L
    calls = {"n": 0}
    real = L._plan_batch

    def racing(cfg, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:                                          # 進鎖前的第一次計畫：事件還是關的 ⇒ 不需要確認
            cfg = dict(cfg, events={**(cfg.get("events") or {}), CRIT: False})
        else:                                                         # 進鎖後：已經被別人打開
            cfg = dict(cfg, events={**(cfg.get("events") or {}), CRIT: True})
        return real(cfg, *a, **k)
    monkeypatch.setattr(L, "_plan_batch", racing)
    with pytest.raises(L.CriticalConfirmRequired):
        L.set_events_batch([CRIT], enabled=False)


# ── 請求輸入嚴格 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    {},                                                                  # 沒有 keys
    {"keys": []},
    {"keys": "approval_request", "enabled": True},                       # 不是清單
    {"keys": [1, 2], "enabled": True},
    {"keys": ["approval_request"]},                                      # 沒有要改的項目
    {"keys": ["approval_request"], "enabled": "false"},                  # 字串不算布林
    {"keys": ["approval_request"], "enabled": 0},
    {"keys": ["approval_request"], "enabled": True, "audience": "only"},
    {"keys": ["approval_request"], "enabled": True, "audience": None},
    {"keys": ["approval_request"], "enabled": True, "confirmCritical": True},     # 打錯欄位名不能被悄悄忽略
    {"keys": ["approval_request"], "roles": "finance"},
])
def test_malformed_requests_are_400_and_change_nothing(client, env, bad):
    before = _snapshot()
    assert client.post(URL, json=bad, headers=_hdr(client, "sa")).status_code == 400
    assert _snapshot() == before


def test_key_count_limits(client, env):
    from helpers import line_notify as L
    sa = _hdr(client, "sa")
    keys = list(L.wired_events())
    assert len(keys) > 100, "測試前提：已接線事件超過 100 個"
    assert client.post(URL, json={"keys": keys[:100], "enabled": False}, headers=sa).status_code == 200
    assert client.post(URL, json={"keys": keys[:101], "enabled": False}, headers=sa).status_code == 400
    # 重複的 key 先去重再算：101 個但只有 100 個不同 ⇒ 可以
    assert client.post(URL, json={"keys": keys[:100] + [keys[0]], "enabled": False}, headers=sa).status_code == 200
    assert client.post(URL, json={"keys": ["approval_request"] * 5000, "enabled": False}, headers=sa).status_code == 400


def test_roles_absent_vs_null_vs_list(client, env):
    sa = _hdr(client, "sa")
    k = "approval_request"
    assert client.post(URL, json={"keys": [k], "roles": ["finance"]}, headers=sa).status_code == 200
    assert _cfg()["event_roles"][k] == ["finance"]
    client.post(URL, json={"keys": [k], "enabled": True, "audience": {"mode": "business"}}, headers=sa)        # 沒帶 roles ⇒ 不動
    assert _cfg()["event_roles"][k] == ["finance"], "沒帶 roles ＝不動角色篩選"
    assert client.post(URL, json={"keys": [k], "roles": None}, headers=sa).status_code == 200
    assert k not in _cfg().get("event_roles", {}), "帶 null ＝移除篩選（所有角色）"
    assert client.post(URL, json={"keys": [k], "roles": []}, headers=sa).status_code == 200
    assert _cfg()["event_roles"][k] == [], "帶空清單 ＝沒有任何角色"


def test_mode_business_clears_audience_but_keeps_event_roles(client, env):
    sa = _hdr(client, "sa")
    k = "next_tier"
    client.post(URL, json={"keys": [k], "roles": ["admin"], "enabled": True, "audience": {"mode": "only", "users": ["amy"]}}, headers=sa)
    assert _cfg()["audiences"][k]["users"] == ["amy"] and _cfg()["event_roles"][k] == ["admin"]
    r = client.post(URL, json={"keys": [k], "audience": {"mode": "business"}}, headers=sa)
    assert r.status_code == 200 and k not in _cfg().get("audiences", {}), "business ＝拿掉指定對象"
    assert _cfg()["event_roles"][k] == ["admin"], "角色篩選保留"


# ── 不可重入的鎖：批次不會死結 ───────────────────────────────────────────────

def test_batch_with_audience_does_not_deadlock(env):
    from helpers import line_notify as L
    out = {}

    def run():
        out["r"] = L.set_events_batch(["approval_request", "next_tier"], enabled=True, audience={"mode": "only", "roles": [], "users": ["amy"]})
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive(), "set_events_batch 卡住了（鎖內不可再呼叫 set_audience／set_event）"
    assert out["r"]["changed"] == ["approval_request", "next_tier"]


def test_concurrent_batches_do_not_lose_each_others_changes(env):
    from helpers import line_notify as L
    groups = [["approval_request", "next_tier"], ["returned", "resubmit_requester"], ["approval_reminder", "shipping_submitted"]]
    errs = []

    def run(ks):
        try:
            L.set_events_batch(ks, enabled=True, audience={"mode": "only", "roles": [], "users": ["amy"]})
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)
    ts = [threading.Thread(target=run, args=(g,), daemon=True) for g in groups]
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    assert errs == []
    cfg = _cfg()
    assert all(cfg["events"][k] is True and cfg["audiences"][k]["users"] == ["amy"] for g in groups for k in g)


# ── 預設：從關切到開、沒有指定對象 ⇒ 只發給操作者 ───────────────────────────

def test_batch_turning_on_without_audience_defaults_to_only_me(client, env):
    sa = _hdr(client, "sa")
    k1, k2 = "approval_request", "next_tier"
    client.post(URL, json={"keys": [k2], "enabled": True, "audience": {"mode": "only", "roles": [], "users": ["amy"]}}, headers=sa)   # k2 已經有對象
    client.post(URL, json={"keys": [k2], "enabled": False}, headers=sa)
    r = client.post(URL, json={"keys": [k1, k2], "enabled": True}, headers=sa)
    assert r.status_code == 200 and r.json()["defaulted"] == [k1]
    cfg = _cfg()
    assert cfg["audiences"][k1] == {"mode": "only", "roles": [], "users": ["sa"]}, "新預設：只發給我"
    assert cfg["audiences"][k2]["users"] == ["amy"], "原本就有指定對象的不覆蓋"


def test_explicit_audience_wins_over_the_default(client, env):
    sa = _hdr(client, "sa")
    r = client.post(URL, json={"keys": ["approval_request"], "enabled": True, "audience": {"mode": "only", "roles": ["admin"], "users": []}}, headers=sa)
    assert r.json()["defaulted"] == [] and _cfg()["audiences"]["approval_request"]["roles"] == ["admin"]
    r = client.post(URL, json={"keys": ["next_tier"], "enabled": True, "audience": {"mode": "business"}}, headers=sa)
    assert r.json()["defaulted"] == [] and "next_tier" not in _cfg().get("audiences", {}), "明確選「照原本收件人」就照原本"


def test_already_on_events_are_not_touched_by_the_default(client, env):
    sa = _hdr(client, "sa")
    from helpers import line_notify as L
    L.set_event("approval_request", True)                                 # helper 直接呼叫：不帶 default_user ⇒ 與過去相同（業務收件人）
    assert "approval_request" not in _cfg().get("audiences", {})
    r = client.post(URL, json={"keys": ["approval_request"], "enabled": True}, headers=sa)
    assert r.json()["defaulted"] == [] and "approval_request" not in _cfg().get("audiences", {}), "原本就是開的 ⇒ 不套預設"


def test_single_event_endpoint_applies_the_same_default(client, env):
    sa = _hdr(client, "sa")
    u = "/api/settings/line-notify/events/approval_request"
    r = client.put(u, json={"enabled": True}, headers=sa)
    assert r.status_code == 200 and r.json() == {"ok": True, "key": "approval_request", "enabled": True, "audience_defaulted": True}
    assert _cfg()["audiences"]["approval_request"] == {"mode": "only", "roles": [], "users": ["sa"]}
    assert _count_audit("settings.line_notify.event") == 1
    client.put(u, json={"enabled": False}, headers=sa)
    r2 = client.put(u, json={"enabled": True}, headers=sa)
    assert r2.json()["audience_defaulted"] is False, "已經有指定對象 ⇒ 不再套預設"
    assert client.put(u, json={"enabled": "true"}, headers=sa).status_code == 400


def test_default_only_me_actually_limits_delivery_to_the_operator(client, env):
    from helpers import line_notify as L
    sa = _hdr(client, "sa")
    from tests.test_line_events_all_2026_11_13 import _targets
    client.put("/api/settings/line-notify/events/approval_request", json={"enabled": True}, headers=sa)
    assert L.deliver_event("approval_request", usernames=["amy", "bob", "sa"], title="t") == L.SEND_SENT
    assert _targets(env) == ["sa"], "預設只發給操作者本人，不是整份業務收件名單"


# ── GET：sent30／usage30 ─────────────────────────────────────────────────────

def test_get_exposes_sent30_and_usage30_without_changing_old_fields(client, env):
    sa = _hdr(client, "sa")
    from helpers import line_notify as L
    L._usage_add("approval_request", 3)
    j = client.get("/api/settings/line-notify", headers=sa).json()
    ev = {e["key"]: e for e in j["events"]}
    assert ev["approval_request"]["sent30"] == 3 and ev["next_tier"]["sent30"] == 0
    assert set(j["usage30"]) == {"days", "accumulated_days", "complete", "total"} and j["usage30"]["total"] == 3 and j["usage30"]["days"] == 30
    assert {"key", "name", "enabled", "roles", "group", "kind", "priority", "need", "follows", "audience"} <= set(ev["approval_request"])


# ── 按日計數 ─────────────────────────────────────────────────────────────────

def _rows():
    from db import get_db
    c = get_db()
    try:
        return {(r["day"], r["event_key"]): r["n"] for r in c.execute("SELECT day, event_key, n FROM line_event_usage_daily").fetchall()}
    finally:
        c.close()


def test_daily_usage_accumulates_per_day_and_keeps_the_monthly_counter(env):
    from helpers import line_notify as L
    from helpers.settings import _get_setting
    L._usage_add("approval_request", 2)
    L._usage_add("approval_request", 1)
    L._usage_add("next_tier", 4)
    today = L._tw_today().isoformat()
    assert _rows() == {(today, "approval_request"): 3, (today, "next_tier"): 4}
    mo = _get_setting(L.USAGE_KEY, {})
    assert mo["events"]["approval_request"] == 3 and mo["month"], "舊的 {month, events} 格式照舊（額度保留／每月上限仍用它）"
    assert L._usage_of("approval_request") == 3


def test_daily_date_is_taiwan_time_and_crosses_midnight_and_month(env):
    from helpers import line_notify as L
    utc = timezone.utc
    L._usage_daily_add("approval_request", 1, now=datetime(2026, 10, 31, 15, 59, tzinfo=utc))     # 台灣 23:59（10/31）
    L._usage_daily_add("approval_request", 1, now=datetime(2026, 10, 31, 16, 1, tzinfo=utc))      # 台灣 00:01（11/01）：跨日也跨月
    assert _rows() == {("2026-10-31", "approval_request"): 1, ("2026-11-01", "approval_request"): 1}
    assert L._tw_today(datetime(2026, 12, 31, 16, 0, tzinfo=utc)).isoformat() == "2027-01-01"      # 跨年


def test_daily_rows_older_than_31_days_are_pruned_once_per_day(env, monkeypatch):
    from db import get_db
    from helpers import line_notify as L
    c = get_db()
    for d in ("2026-09-01", "2026-10-13", "2026-10-14", "2026-11-12"):
        c.execute("INSERT INTO line_event_usage_daily (day, event_key, n) VALUES (?, 'approval_request', 1)", (d,))
    c.commit()
    c.close()
    monkeypatch.setattr(L, "_usage_pruned_day", "")
    now = datetime(2026, 11, 13, 4, 0, tzinfo=timezone(timedelta(hours=8)))
    L._usage_daily_add("next_tier", 1, now=now)
    days = sorted(d for d, _k in _rows())
    assert "2026-09-01" not in days and "2026-10-13" not in days, "超過 31 天的清掉"
    assert "2026-10-14" in days and "2026-11-12" in days and "2026-11-13" in days, "第 31 天（含今天）還在"


def test_usage_view_sums_the_last_30_days_and_flags_incomplete_history(env):
    from db import get_db
    from helpers import line_notify as L
    from helpers.settings import _set_setting
    c = get_db()
    for d, k, n in (("2026-11-13", "approval_request", 2), ("2026-10-15", "approval_request", 5), ("2026-10-14", "approval_request", 100), ("2026-11-10", "next_tier", 1)):
        c.execute("INSERT INTO line_event_usage_daily (day, event_key, n) VALUES (?, ?, ?)", (d, k, n))
    c.commit()
    c.close()
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    _set_setting(L.USAGE_SINCE_KEY, "2026-11-08")
    v = L.usage_daily_view(30, now=now)
    assert v["by_event"] == {"approval_request": 7, "next_tier": 1}, "近 30 天＝10/15～11/13（10/14 不算）"
    assert v["total"] == 8 and v["accumulated_days"] == 6 and v["complete"] is False, "資料從 11/08 才開始累積 ⇒ 已累積 6 天、未滿 30 天"
    _set_setting(L.USAGE_SINCE_KEY, "2026-09-01")
    v2 = L.usage_daily_view(30, now=now)
    assert v2["accumulated_days"] == 30 and v2["complete"] is True


def test_usage_view_never_raises_when_the_table_is_missing(env, monkeypatch):
    from db import get_db
    from helpers import line_notify as L
    c = get_db()
    c.execute("DROP TABLE line_event_usage_daily")
    c.commit()
    c.close()
    v = L.usage_daily_view(30)
    assert v["total"] == 0 and v["complete"] is False and v["by_event"] == {}
    L._usage_add("approval_request", 1)                                  # 寫入失敗只記 log；本月計數照常
    assert L._usage_of("approval_request") == 1


def test_migration_is_idempotent_and_keeps_the_first_since_date(env):
    from core import migrations as M
    from db import get_db
    from helpers.settings import _get_setting, _set_setting
    c = get_db()
    try:
        _set_setting("line_event_usage_since", "2026-01-02")
        assert M._core_next_line_event_usage_daily(c) is None and M._core_next_line_event_usage_daily(c) is None
        assert _get_setting("line_event_usage_since", "") == "2026-01-02", "已有開始日期就不改"
        cols = [r[1] for r in c.execute("PRAGMA table_info(line_event_usage_daily)").fetchall()]
        assert cols == ["day", "event_key", "n"]
    finally:
        c.close()


# ── 「復原這一批」：版本（指紋）檢查，不是計時（PM 裁示 N2）────────────────────────

UNDO = "/api/settings/line-notify/events/batch-undo"


def _state_of(k):
    """套用前的狀態，格式同前端 snapshot：{enabled, audience, roles}。"""
    from helpers import line_notify as L
    a = L.audience_view()[k]
    return {"enabled": L.event_enabled(k), "audience": {"mode": a["mode"], "roles": list(a["roles"]), "users": list(a["users"])}, "roles": L.event_roles_view()[k]}


def _apply(client, sa, keys, **fields):
    before = {k: _state_of(k) for k in keys}
    r = client.post(URL, json={"keys": list(keys), **fields}, headers=sa)
    assert r.status_code == 200, r.text
    return before, r.json()


def test_batch_response_carries_after_tokens_and_audit_mark(client, env):
    sa = _hdr(client, "sa")
    _before, j = _apply(client, sa, NORMAL, enabled=True, audience={"mode": "only", "roles": [], "users": ["amy"]})
    assert sorted(j["after"]) == sorted(NORMAL) and all(isinstance(v, str) and v for v in j["after"].values())
    assert isinstance(j["audit_mark"], int) and j["audit_mark"] > 0


def test_undo_restores_previous_states_atomically_with_one_write_and_one_audit_row(client, env, writes):
    sa = _hdr(client, "sa")
    # 兩個事件原本狀態不同：一個關、一個開且只發給 amy
    assert client.post(URL, json={"keys": [NORMAL[1]], "enabled": True, "audience": {"mode": "only", "roles": [], "users": ["amy"]}}, headers=sa).status_code == 200
    before, j = _apply(client, sa, NORMAL[:2], enabled=True, audience={"mode": "business"}, roles=["admin"])
    n_writes = len(writes)
    r = client.post(UNDO, json={"states": before, "expect": j["after"], "since_audit": j["audit_mark"]}, headers=sa)
    assert r.status_code == 200, r.text
    assert len(writes) == n_writes + 1, "整批復原只寫一次"
    assert sorted(r.json()["restored"]) == sorted(NORMAL[:2])
    for k in NORMAL[:2]:
        assert _state_of(k) == before[k], k
    assert _count_audit("settings.line_notify.batch_undo") == 1


def test_undo_refused_when_someone_else_changed_a_key_in_between(client, env, writes):
    sa, bob = _hdr(client, "sa"), _hdr(client, "bob")
    before, j = _apply(client, sa, NORMAL[:2], enabled=True, audience={"mode": "only", "roles": [], "users": ["amy"]})
    # 套用之後，另一個視窗把第二個事件的收件對象改了（用單項端點，同樣會被偵測）
    assert client.put("/api/settings/line-notify/events/%s/audience" % NORMAL[1], json={"mode": "only", "roles": ["admin"], "users": []}, headers=sa).status_code == 200
    snap = _snapshot()
    n_writes = len(writes)
    r = client.post(UNDO, json={"states": before, "expect": j["after"], "since_audit": j["audit_mark"]}, headers=sa)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["code"] == "conflict" and [x["key"] for x in d["keys"]] == [NORMAL[1]]
    assert d["by"] and d["at"], "要告訴使用者是誰、什麼時候改的"
    assert _snapshot() == snap and len(writes) == n_writes, "拒絕時一個都不復原（包含沒被改過的第一個事件）"
    assert _count_audit("settings.line_notify.batch_undo") == 0
    assert client.post(UNDO, json={"states": before, "expect": j["after"]}, headers=bob).status_code == 403


def test_undo_twice_is_refused_because_state_changed_after_the_first_undo(client, env):
    sa = _hdr(client, "sa")
    before, j = _apply(client, sa, [NORMAL[0]], enabled=True, audience={"mode": "only", "roles": [], "users": ["amy"]})
    body = {"states": before, "expect": j["after"]}
    assert client.post(UNDO, json=body, headers=sa).status_code == 200
    assert client.post(UNDO, json=body, headers=sa).status_code == 409, "復原一次之後再復原 ⇒ 狀態已不是『套用後』"


@pytest.mark.parametrize("mut", [
    lambda b: b.update(states={}),
    lambda b: b.update(expect={}),
    lambda b: b.update(states=[1]),
    lambda b: b["states"][NORMAL[0]].update(enabled="yes"),
    lambda b: b["states"][NORMAL[0]].pop("audience"),
    lambda b: b["states"][NORMAL[0]].update(roles=["nobody"]),
    lambda b: b["states"][NORMAL[0]]["audience"].update(mode="weird"),
    lambda b: b["states"][NORMAL[0]]["audience"].update(users=["ghost"]),
    lambda b: b["expect"].update({NORMAL[0]: 5}),
    lambda b: b.update(since_audit="1"),
    lambda b: b.update(extra=1),
    lambda b: b["states"].update({"not_a_wired_event": b["states"][NORMAL[0]]}),
])
def test_undo_rejects_malformed_bodies_without_changing_anything(client, env, mut):
    import copy
    sa = _hdr(client, "sa")
    before, j = _apply(client, sa, [NORMAL[0]], enabled=True, audience={"mode": "only", "roles": [], "users": ["amy"]})
    body = copy.deepcopy({"states": before, "expect": j["after"]})
    mut(body)
    snap = _snapshot()
    assert client.post(UNDO, json=body, headers=sa).status_code == 400
    assert _snapshot() == snap


def test_undo_restores_critical_off_state_without_second_confirm_and_roles_null(client, env):
    sa = _hdr(client, "sa")
    _turn_on(client, sa, CRIT)
    before = {CRIT: _state_of(CRIT)}
    r = client.post(URL, json={"keys": [CRIT], "enabled": False, "confirm_critical": True}, headers=sa)
    assert r.status_code == 200
    r2 = client.post(UNDO, json={"states": before, "expect": r.json()["after"]}, headers=sa)
    assert r2.status_code == 200, r2.text
    assert _state_of(CRIT) == before[CRIT] and _state_of(CRIT)["enabled"] is True
