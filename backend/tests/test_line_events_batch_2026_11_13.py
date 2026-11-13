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


# ── M1（hichan-9 審查、PM 裁示）：重要告警「實際收件人變成 0」或「縮小」也要確認 ───────────

BE = "backup_error"                       # priority=critical


def _on_for(client, sa, **aud):
    body = {"keys": [BE], "enabled": True, "audience": aud or {"mode": "business"}}
    assert client.post(URL, json=body, headers=sa).status_code == 200


def _need_confirm(client, sa, body, keys=(BE,)):
    before = _snapshot()
    r = client.post(URL, json=body, headers=sa)
    assert r.status_code == 400, r.text
    d = r.json()["detail"]
    assert d["code"] == "confirm_critical_required" and [x["key"] for x in d["critical"]] == list(keys)
    assert _snapshot() == before, "沒確認 ⇒ 不改"
    ok = client.post(URL, json={**body, "confirm_critical": True}, headers=sa)
    assert ok.status_code == 200, ok.text
    return ok


def test_critical_roles_cleared_to_empty_needs_confirm(client, env):
    """backup_error 照原樣開著，把角色篩選清成 []（沒有任何人符合）⇒ 等同靜音 ⇒ 必須確認（原本會直接放行）。"""
    sa = _hdr(client, "sa")
    _on_for(client, sa)
    _need_confirm(client, sa, {"keys": [BE], "roles": []})
    assert _cfg()["event_roles"][BE] == []


def _more_superadmins(env, *names, line=True):
    """重要的系統告警只有最高管理者看得到 ⇒ 要有第二、第三位最高管理者才有「縮小」可言。"""
    for n in names:
        _mk(env["make_user"], n, "superadmin", line=line)


def test_critical_only_audience_of_departed_or_unbound_users_needs_confirm(client, env):
    sa = _hdr(client, "sa")
    _more_superadmins(env, "sa2")
    _more_superadmins(env, "sa3", line=False)                             # 沒綁定 LINE
    _on_for(client, sa, mode="only", users=["sa", "sa2"])
    from db import get_db
    c = get_db()
    c.execute("UPDATE users SET active=0 WHERE username='sa2'")           # 離職
    c.commit()
    c.close()
    from helpers import line_notify as L
    n = L.preview_events_batch([BE], audience={"mode": "only", "roles": [], "users": ["sa3"]})
    assert n["events"][0]["n_after"] == 0, "指定的人沒綁定 ⇒ 實際收件人 0"
    _need_confirm(client, sa, {"keys": [BE], "audience": {"mode": "only", "users": ["sa3"]}})


def test_critical_narrowing_the_recipient_set_needs_confirm_but_widening_does_not(client, env):
    sa = _hdr(client, "sa")
    _more_superadmins(env, "sa2", "sa3")
    _on_for(client, sa, mode="only", users=["sa", "sa2"])
    _need_confirm(client, sa, {"keys": [BE], "audience": {"mode": "only", "users": ["sa"]}})        # 2 → 1：縮小
    r = client.post(URL, json={"keys": [BE], "audience": {"mode": "only", "users": ["sa", "sa2", "sa3"]}}, headers=sa)
    assert r.status_code == 200, r.text                                                              # 1 → 3：放寬不用確認
    r = client.post(URL, json={"keys": [BE], "audience": {"mode": "only", "users": ["sa", "sa2", "sa3"]}}, headers=sa)
    assert r.status_code == 200                                                                      # 沒變：不用確認


def test_changes_mode_has_the_same_critical_narrowing_rule(client, env):
    sa = _hdr(client, "sa")
    _on_for(client, sa)
    before = _snapshot()
    r = client.post(URL, json=_save_body(client, sa, {BE: {"roles": []}}), headers=sa)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "confirm_critical_required"
    assert _snapshot() == before
    assert client.post(URL, json=_save_body(client, sa, {BE: {"roles": []}}, confirm_critical=True), headers=sa).status_code == 200


def test_preview_flags_critical_narrowing_separately_from_off(client, env):
    sa = _hdr(client, "sa")
    _on_for(client, sa)
    P = "/api/settings/line-notify/events/batch-preview"
    rows = client.post(P, json={"keys": [BE], "roles": []}, headers=sa).json()["events"]
    assert rows[0]["critical_narrow"] is True and rows[0]["critical_off"] is False
    rows = client.post(P, json={"keys": [BE], "enabled": False}, headers=sa).json()["events"]
    assert rows[0]["critical_off"] is True and rows[0]["critical_narrow"] is False


def test_undo_never_needs_confirm_even_when_it_restores_a_narrow_state(client, env):
    sa = _hdr(client, "sa")
    _on_for(client, sa)
    before = {BE: _state_of(BE)}
    ok = _need_confirm(client, sa, {"keys": [BE], "roles": []})
    r = client.post(UNDO, json={"states": before, "expect": ok.json()["after"]}, headers=sa)
    assert r.status_code == 200, r.text


def test_batch_without_any_real_change_does_not_write(client, env, writes):
    sa = _hdr(client, "sa")
    _on_for(client, sa)
    writes.clear()
    r = client.post(URL, json={"keys": [BE], "enabled": True}, headers=sa)
    assert r.status_code == 200 and r.json()["changed"] == [] and writes == []


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


# ── 收件人數 recipient_count／批次預覽（PM 2026-11-13：確認視窗顯示「預估每月 X → Y 則」）─────────────

PREVIEW = "/api/settings/line-notify/events/batch-preview"


def _events_by_key(client, sa):
    j = client.get("/api/settings/line-notify", headers=sa).json()
    return {e["key"]: e for e in j["events"]}


def test_get_events_carry_recipient_count_and_exactness(client, env):
    from helpers import line_notify as L
    sa = _hdr(client, "sa")
    k = "approval_request"
    L.set_event(k, True)
    L.set_audience(k, "only", [], ["sa"])
    e = _events_by_key(client, sa)[k]
    assert e["recipient_count"] == 1 and e["recipient_exact"] is True, "只發給指定 ⇒ 人數精確"
    L.set_audience(k, "only", ["superadmin", "admin"], [])
    e = _events_by_key(client, sa)[k]
    assert e["recipient_count"] == 2, "角色成員（最高管理者＋管理員）各一位，且都已綁定 LINE"
    L.set_audience(k, "business", [], [])
    e = _events_by_key(client, sa)[k]
    assert e["recipient_exact"] is False, "照原本收件人：每一則的收件人不同，人數是上限"
    assert isinstance(e["recipient_count"], int) and e["recipient_count"] >= 0


def test_recipient_count_skips_unlinked_muted_and_inactive(client, env):
    from helpers import line_notify as L, line_recipients as LR
    from db import get_db
    sa = _hdr(client, "sa")
    k = "approval_request"
    L.set_event(k, True)
    L.set_audience(k, "only", ["superadmin", "admin"], [])
    assert _events_by_key(client, sa)[k]["recipient_count"] == 2
    LR.set_muted("bob", k, True)
    assert _events_by_key(client, sa)[k]["recipient_count"] == 1, "本人退訂的不算"
    LR.set_muted("bob", k, False)
    L.unlink_user("bob")
    assert _events_by_key(client, sa)[k]["recipient_count"] == 1, "沒綁定 LINE 的不算"
    c = get_db()
    c.execute("UPDATE users SET active=0 WHERE username='sa'")
    c.commit()
    c.close()
    assert LR.potential_counts([k])[k]["n"] == 0, "停用的帳號不算"


def test_preview_writes_nothing_and_reports_before_after(client, env, writes):
    from helpers import line_notify as L
    sa = _hdr(client, "sa")
    k = "approval_request"
    L.set_event(k, True)
    L.set_audience(k, "only", [], ["sa"])
    snap = _snapshot()
    n_writes = len(writes)
    audits = _count_audit("settings.line_notify.batch")
    r = client.post(PREVIEW, json={"keys": [k], "audience": {"mode": "only", "roles": ["superadmin", "admin"], "users": []}}, headers=sa)
    assert r.status_code == 200, r.text
    row = r.json()["events"][0]
    assert row["key"] == k and row["name"] and row["n_before"] == 1 and row["n_after"] == 2 and row["changed"] is True
    assert _snapshot() == snap and len(writes) == n_writes and _count_audit("settings.line_notify.batch") == audits, "預覽不寫入、不記稽核"


def test_preview_estimates_monthly_messages_from_30_day_history(client, env):
    from helpers import line_notify as L
    sa = _hdr(client, "sa")
    on, off, fresh = "approval_request", "next_tier", "returned"
    L.set_event(on, True)
    L.set_audience(on, "only", [], ["sa"])
    L._usage_add(on, 6)
    L._usage_add(off, 9)                                    # 有歷史但目前關閉
    body = {"keys": [on, off, fresh], "enabled": True, "audience": {"mode": "only", "roles": ["superadmin", "admin"], "users": []}}
    j = client.post(PREVIEW, json=body, headers=sa).json()
    rows = {r["key"]: r for r in j["events"]}
    assert rows[on]["sent30"] == 6 and rows[on]["est_after"] == 12, "1 人 → 2 人：近 30 天 6 則 ⇒ 預估 12 則"
    n0 = rows[off]["n_before"]
    assert n0 > 1 and rows[off]["n_after"] == 2 and rows[off]["est_after"] == round(9 * 2 / n0), "目前關閉但有歷史：按『照原本』的可能人數比例推算"
    assert rows[fresh]["est_after"] is None and rows[fresh]["sent30"] == 0, "沒有歷史推播量 ⇒ 無法估算"
    assert j["total"]["sent30"] == 15 and j["total"]["est_after"] == 12 + rows[off]["est_after"] and j["total"]["unknown"] == 1
    off_body = {"keys": [on], "enabled": False}
    r2 = client.post(PREVIEW, json=off_body, headers=sa).json()["events"][0]
    assert r2["est_after"] == 0 and r2["enabled_after"] is False, "關閉 ⇒ 之後 0 則"


def test_preview_validates_like_batch_and_is_superadmin_only(client, env):
    sa, bob = _hdr(client, "sa"), _hdr(client, "bob")
    assert client.post(PREVIEW, json={"keys": ["approval_request"], "enabled": True}, headers=bob).status_code == 403
    for body in ({}, {"keys": []}, {"keys": ["approval_request"]}, {"keys": ["nope"], "enabled": True}, {"keys": ["approval_request"], "enabled": "yes"},
                 {"keys": ["approval_request"], "audience": {"mode": "weird"}}, {"keys": ["approval_request"], "extra": 1, "enabled": True},
                 {"keys": ["approval_request"], "audience": {"mode": "only", "users": ["ghost"]}}):
        assert client.post(PREVIEW, json=body, headers=sa).status_code == 400, body


# ── 草稿儲存：`changes`（每個事件各自的改動）＋ `expect`（載入時的 version；PM 2026-11-13 草稿＋儲存列模型）──────────

def _versions(client, sa):
    j = client.get("/api/settings/line-notify", headers=sa).json()
    return {e["key"]: e["version"] for e in j["events"]}, j["audit_mark"]


def _save_body(client, sa, changes, **extra):
    """草稿儲存的請求本體：照頁面做法，expect＝目前每個事件的 version（儲存一定要帶）。"""
    ver, mark = _versions(client, sa)
    return {"changes": changes, "expect": {k: ver.get(k, "x") for k in changes}, "since_audit": mark, **extra}


def test_changes_apply_per_event_with_one_write_and_one_audit_row(client, env, writes):
    sa = _hdr(client, "sa")
    a, b, c = NORMAL
    body = _save_body(client, sa, {a: {"enabled": True, "audience": {"mode": "only", "roles": [], "users": ["amy"]}},
                                   b: {"enabled": True},
                                   c: {"roles": ["admin", "sales"]}})
    r = client.post(URL, json=body, headers=sa)
    assert r.status_code == 200, r.text
    j = r.json()
    assert sorted(j["changed"]) == sorted(NORMAL) and set(j["after"]) == set(NORMAL) and j["audit_mark"] > 0
    assert len(writes) == 1 and _count_audit("settings.line_notify.batch") == 1
    cfg = _cfg()
    assert cfg["events"][a] is True and cfg["audiences"][a] == {"mode": "only", "roles": [], "users": ["amy"]}
    assert cfg["events"][b] is True and cfg["audiences"][b] == {"mode": "only", "roles": [], "users": ["sa"]}, "沒帶對象的新開事件：預設只發給操作者本人"
    assert cfg["event_roles"][c] == ["admin", "sales"] and cfg["events"].get(c) is not True


def test_changes_all_or_nothing_on_any_invalid_entry(client, env, writes):
    sa = _hdr(client, "sa")
    snap = _snapshot()
    a, b, _c = NORMAL
    for changes in ({a: {"enabled": True}, b: {"audience": {"mode": "only", "users": ["ghost"]}}},
                    {a: {"enabled": True}, "not_wired": {"enabled": True}},
                    {a: {"enabled": True}, b: {}},
                    {a: {"enabled": True}, b: {"enabled": "yes"}},
                    {a: {"enabled": True}, b: {"unknown_field": 1}},
                    {a: {"enabled": True}, b: {"roles": ["nobody"]}}):
        assert client.post(URL, json=_save_body(client, sa, changes), headers=sa).status_code == 400, changes
    assert _snapshot() == snap and not writes


@pytest.mark.parametrize("body", [
    {"changes": []}, {"changes": {}}, {"changes": {"approval_request": {"enabled": True}}, "keys": ["approval_request"]},
    {"changes": {"approval_request": {"enabled": True}}, "enabled": True},
    {"changes": {"approval_request": {"enabled": True}}, "expect": {"approval_request": 5}},
    {"changes": {"approval_request": {"enabled": True}}, "since_audit": "1"},
    {"changes": {"approval_request": {"enabled": True}}, "confirm_critical": "yes"},
])
def test_changes_rejects_malformed_bodies(client, env, body):
    sa = _hdr(client, "sa")
    snap = _snapshot()
    assert client.post(URL, json=body, headers=sa).status_code == 400
    assert _snapshot() == snap


def test_changes_critical_off_requires_confirm_and_only_superadmin(client, env):
    sa, bob = _hdr(client, "sa"), _hdr(client, "bob")
    _turn_on(client, sa, CRIT)
    r = client.post(URL, json=_save_body(client, sa, {CRIT: {"enabled": False}}), headers=sa)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "confirm_critical_required"
    assert _cfg()["events"][CRIT] is True
    assert client.post(URL, json=_save_body(client, sa, {CRIT: {"enabled": False}}, confirm_critical=True), headers=sa).status_code == 200
    assert _cfg()["events"][CRIT] is False
    assert client.post(URL, json=_save_body(client, sa, {CRIT: {"enabled": False}}), headers=bob).status_code == 403


def test_changes_expect_detects_edits_made_after_page_load(client, env, writes):
    sa = _hdr(client, "sa")
    k1, k2, _ = NORMAL
    ver, mark = _versions(client, sa)
    # 載入之後，別的視窗改了 k2
    assert client.put("/api/settings/line-notify/events/%s" % k2, json={"enabled": True}, headers=sa).status_code == 200
    snap = _snapshot()
    n = len(writes)
    body = {"changes": {k1: {"enabled": True}, k2: {"enabled": False}}, "expect": {k1: ver[k1], k2: ver[k2]}, "since_audit": mark}
    r = client.post(URL, json=body, headers=sa)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["code"] == "conflict" and [x["key"] for x in d["keys"]] == [k2] and d["by"] and d["at"]
    assert _snapshot() == snap and len(writes) == n, "衝突 ⇒ 整批都不存（包含沒被改過的 k1）"
    ver2, mark2 = _versions(client, sa)
    ok = client.post(URL, json={"changes": {k1: {"enabled": True}, k2: {"enabled": False}}, "expect": {k1: ver2[k1], k2: ver2[k2]}, "since_audit": mark2}, headers=sa)
    assert ok.status_code == 200, ok.text
    ver3, _ = _versions(client, sa)
    assert ver3[k1] != ver2[k1] and ver3[k2] != ver2[k2], "version 會隨狀態改變"


def test_get_version_is_stable_and_changes_with_state(client, env):
    sa = _hdr(client, "sa")
    v1, _ = _versions(client, sa)
    v2, _ = _versions(client, sa)
    assert v1 == v2
    assert client.put("/api/settings/line-notify/events/approval_request/roles", json={"roles": ["admin"]}, headers=sa).status_code == 200
    v3, _ = _versions(client, sa)
    assert v3["approval_request"] != v1["approval_request"] and v3["next_tier"] == v1["next_tier"]


def test_preview_with_changes_writes_nothing(client, env, writes):
    sa = _hdr(client, "sa")
    snap = _snapshot()
    a, b, _ = NORMAL
    r = client.post(PREVIEW, json={"changes": {a: {"enabled": True, "audience": {"mode": "only", "roles": ["superadmin", "admin"], "users": []}}, b: {"enabled": True}}}, headers=sa)
    assert r.status_code == 200, r.text
    rows = {x["key"]: x for x in r.json()["events"]}
    assert rows[a]["n_after"] == 2 and rows[a]["changed"] and rows[b]["defaulted"] and rows[b]["n_after"] == 1
    assert _snapshot() == snap and not writes and _count_audit("settings.line_notify.batch") == 0
    assert client.post(PREVIEW, json={"changes": {a: {"enabled": "x"}}}, headers=sa).status_code == 400


def test_changes_save_requires_expect_for_every_key_and_noop_leaves_no_audit(client, env, writes):
    sa = _hdr(client, "sa")
    a, b, _c = NORMAL
    snap = _snapshot()
    for body in ({"changes": {a: {"enabled": True}}},                                          # 沒帶 expect：會悄悄蓋掉別人的修改
                 {"changes": {a: {"enabled": True}, b: {"enabled": True}}, "expect": {a: "x"}}):   # 少一個事件的 version
        r = client.post(URL, json=body, headers=sa)
        assert r.status_code == 400 and "expect" in r.json()["detail"], body
    assert _snapshot() == snap and not writes
    # 預覽不需要 expect
    assert client.post(PREVIEW, json={"changes": {a: {"enabled": True}}}, headers=sa).status_code == 200
    # 沒有實質變動的儲存：不寫設定、不留稽核
    ok = client.post(URL, json=_save_body(client, sa, {a: {"enabled": False}}), headers=sa)
    assert ok.status_code == 200 and ok.json()["changed"] == [] and not writes and _count_audit("settings.line_notify.batch") == 0


# ── hichan-9 L2／L5／L6 ───────────────────────────────────────────────────────

def test_conflict_who_matches_exact_event_keys_not_substrings(client, env):
    """稽核明細裡有 `next_tier_approved` 之類較長的代碼，不能被「approved」子字串誤認成同一個事件的修改者。"""
    from db import get_db
    from routers.system import _line_conflict_who
    c = get_db()
    try:
        c.execute("INSERT INTO audit_log (at, username, display_name, action, target_type, target_id, detail) VALUES (?,?,?,?,?,?,?)",
                  ("2026-11-13 10:00:00", "bob", "Bob", "settings.line_notify.batch", "settings", "", '{"changes": {"next_tier_approved": {"enabled": true}}}'))
        c.execute("INSERT INTO audit_log (at, username, display_name, action, target_type, target_id, detail) VALUES (?,?,?,?,?,?,?)",
                  ("2026-11-13 10:05:00", "amy", "Amy", "settings.line_notify.batch", "settings", "", '{"changes": {"approved": {"enabled": true}}}'))
        c.commit()
    finally:
        c.close()
    assert _line_conflict_who(["approved"], 0)["by"] == "Amy"
    assert _line_conflict_who(["next_tier_approved"], 0)["by"] == "Bob"
    assert _line_conflict_who(["appro"], 0) == {"by": "", "at": ""}


def test_undo_error_names_the_possible_reason_when_a_prior_user_is_gone(client, env):
    sa = _hdr(client, "sa")
    _more_superadmins(env, "sa2")
    _on_for(client, sa, mode="only", users=["sa", "sa2"])
    before = {BE: _state_of(BE)}
    ok = _need_confirm(client, sa, {"keys": [BE], "audience": {"mode": "only", "users": ["sa"]}})
    from db import get_db
    c = get_db()
    c.execute("DELETE FROM users WHERE username='sa2'")
    c.commit()
    c.close()
    r = client.post(UNDO, json={"states": before, "expect": ok.json()["after"]}, headers=sa)
    assert r.status_code == 400 and "無法復原" in r.json()["detail"] and "離職" in r.json()["detail"]


def test_usage_prune_day_is_recorded_only_after_a_successful_commit(env, monkeypatch):
    from helpers import line_notify as L
    monkeypatch.setattr(L, "_usage_pruned_day", "")
    import db as _db
    real = _db.get_db

    class Boom:
        def __init__(self, c):
            self.c = c

        def execute(self, *a, **k):
            return self.c.execute(*a, **k)

        def commit(self):
            raise RuntimeError("disk full")

        def close(self):
            self.c.close()
    monkeypatch.setattr(_db, "get_db", lambda: Boom(real()))
    L._usage_daily_add("approval_request", 1)                          # 內部吞掉例外（計數失敗不影響寄送）
    assert L._usage_pruned_day == "", "commit 失敗 ⇒ 不能記成「今天清過了」"
