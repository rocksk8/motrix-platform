# -*- coding: utf-8 -*-
"""設定變更通知（新票 feat/settings-change-notify；使用者：「變更後要有通知，或是儲存選項；點選後沒人知道變動了」）＋設定中心輸入元件顯示目前值。

後端：收件人（全部在職最高管理者＋impact_scope.roles）、內容、commit 之後才發、待生效流程（送出／核准／撤銷／到期生效）、批次合併成一則、LINE 只給高風險且只給最高管理者。
前端（以 node 在「與 Alpine 同樣的範圍代理」下求值頁面上真正的綁定式）：int／float／str／選項（數字碼、字串碼）／bool 各一個「顯示目前值」的測試、
  草稿覆蓋、「建議值」徽章只出現在 recommended 那一項、離開頁面警告、儲存結果提示文字。
根因：元件方法叫 `valueOf` ⇒ x-for 範圍裡解析到 Object.prototype.valueOf，所有輸入元件拿不到目前值（單選不選取、數字框空白）。
"""
import json
import os
import re
import shutil
import subprocess

import pytest

from db import get_db
from helpers import settings_groups  # noqa: F401
from helpers import settings_notify as SN
from helpers import settings_registry as R

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(os.path.dirname(os.path.dirname(HERE)), "frontend", "pages", "settings-center.html")
FRONTEND = os.path.dirname(PAGE)


# ═══════════════════════════ 後端 ═══════════════════════════

def _hdr(client, make_user, name, role="superadmin"):
    username, password = make_user(username=name, role=role)
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _notes(user, type_="settings_changed"):
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT message, ref_id, ref_label, link FROM notifications WHERE username=? AND type=? ORDER BY id", (user, type_)).fetchall()]
    finally:
        conn.close()


def _display(user):
    conn = get_db()
    try:
        r = conn.execute("SELECT display_name FROM users WHERE username=?", (user,)).fetchone()
        return (r[0] if r and r[0] else user)
    finally:
        conn.close()


@pytest.fixture()
def line_calls(monkeypatch):
    calls = []
    from helpers import line_notify as LN
    monkeypatch.setattr(LN, "notify_event", lambda *a, **kw: calls.append((a, kw)))
    return calls


def test_immediate_change_notifies_every_active_superadmin_with_who_what_old_new_reason(client, make_user, line_calls):
    h = _hdr(client, make_user, "nt_sa1")
    make_user(username="nt_sa2", role="superadmin")
    make_user(username="nt_admin", role="admin")
    r = client.post("/api/settings-center/groups/uploads", json={"values": {"max_file_mb": 10}, "reason": "磁碟快滿了"}, headers=h)
    assert r.status_code == 200 and r.json()["changed"] is True
    label = R.groups()["uploads"]["label"]
    for u in ("nt_sa1", "nt_sa2"):                                  # 操作者本人也收到（看到「確實存了」）
        n = _notes(u)
        assert len(n) == 1, (u, n)
        m = n[0]["message"]
        assert _display("nt_sa1") in m and label in m and "10" in m and "磁碟快滿了" in m and "立即生效" in m and "→" in m
        assert n[0]["link"] == "settings-center.html"
    assert _notes("nt_admin") == []                                  # 管理員不是這個欄位的影響角色（ops 欄位沒有 impact_scope）
    assert not _notes("nt_sa1", "config_change")                     # 帳本的簡短通知不重複發
    assert line_calls == []                                          # ops 風險不發 LINE


def test_inactive_superadmin_is_not_notified(client, make_user):
    h = _hdr(client, make_user, "nt_sa3")
    make_user(username="nt_sa4", role="superadmin")
    conn = get_db()
    conn.execute("UPDATE users SET active=0 WHERE username='nt_sa4'")
    conn.commit()
    conn.close()
    assert client.post("/api/settings-center/groups/uploads", json={"values": {"max_file_mb": 11}, "reason": "測"}, headers=h).status_code == 200
    assert len(_notes("nt_sa3")) == 1 and _notes("nt_sa4") == []


def test_roles_listed_in_impact_scope_are_notified_and_unlisted_are_not(client, make_user, line_calls):
    h = _hdr(client, make_user, "nt_sa5")
    make_user(username="nt_sales", role="sales")
    make_user(username="nt_viewer", role="viewer")
    make_user(username="nt_admin2", role="admin")
    cur = R.get("quote_approval", "reconfirm_mode")
    r = client.post("/api/settings-center/groups/quote_approval", json={"values": {"reconfirm_mode": 2 if cur < 2 else 1}, "reason": "試行"}, headers=h)
    assert r.status_code == 200, r.text
    scope = R.field_defs("quote_approval")["reconfirm_mode"].impact_scope
    assert "業務" in scope["roles"] and "管理員" not in scope["roles"]
    assert len(_notes("nt_sales")) == 1                              # 「業務」⇒ sales
    assert _notes("nt_viewer") == [] and _notes("nt_admin2") == []
    assert len(_notes("nt_sa5")) == 1


def test_money_risk_goes_to_line_only_to_superadmins_without_free_text(client, make_user, line_calls):
    h = _hdr(client, make_user, "nt_sa6")
    make_user(username="nt_sa7", role="superadmin")
    make_user(username="nt_sales2", role="sales")
    cur = R.get("quote_approval", "reconfirm_mode")
    assert client.post("/api/settings-center/groups/quote_approval", json={"values": {"reconfirm_mode": 2 if cur < 2 else 1}, "reason": "機密原因文字"}, headers=h).status_code == 200
    assert len(line_calls) == 1
    args, kw = line_calls[0]
    assert args == ("settings_changed",)
    assert set(kw["usernames"]) >= {"nt_sa6", "nt_sa7"} and "nt_sales2" not in kw["usernames"]
    blob = json.dumps(kw, ensure_ascii=False)
    assert "機密原因文字" not in blob and "reason" not in kw           # LINE 不放自由文字
    assert kw["link"] == "settings-center.html"


def test_line_event_is_wired_line_only_and_audience_is_superadmins_by_default():
    from helpers import line_catalog as C
    from helpers import line_notify as LN
    assert "settings_changed" in C.LINE_ONLY_EVENTS and C.is_known("settings_changed")
    assert C.group_of("settings_changed") == "系統告警" and C.kind_of("settings_changed") == "line_only"
    assert LN.event_spec("settings_changed")["line_group"] is None      # 沒有群組收件人：只發給呼叫端指定的最高管理者
    assert LN.event_enabled("settings_changed") is False                # 沿用所有 LINE 事件的預設（全關，管理者勾選才發）


def test_pending_flow_submit_approve_cancel_each_notifies(client, make_user):
    h1 = _hdr(client, make_user, "nt_sa8")
    h2 = _hdr(client, make_user, "nt_sa9")
    r = client.post("/api/settings-center/groups/uploads", json={"values": {"max_file_mb": 50}, "reason": "客戶要傳大檔"}, headers=h1).json()
    pend = r["pending"][0]
    assert pend["approvalsRequired"] == 1
    sub = _notes("nt_sa9")[-1]["message"]
    assert "待第二位最高管理者核准" in sub and "預計" in sub and pend["effectiveAt"][:10] in sub
    assert client.post("/api/settings-center/pending/%d/approve" % pend["id"], json={"reason": "同意"}, headers=h2).status_code == 200
    ok = _notes("nt_sa8")[-1]["message"]
    assert "核准了" in ok and "1／1" in ok and _display("nt_sa9") in ok
    p2 = client.post("/api/settings-center/groups/uploads", json={"values": {"max_file_mb": 60}, "reason": "再大一點"}, headers=h1).json()["pending"][0]
    assert client.post("/api/settings-center/pending/%d/cancel" % p2["id"], json={"reason": "不用了"}, headers=h2).status_code == 200
    gone = _notes("nt_sa8")[-1]["message"]
    assert "撤銷了" in gone and "維持原設定" in gone


@pytest.fixture()
def zz_groups(client):
    R.invalidate()
    R.register_group("zz_nt_a", "通知測試甲", [
        R.SettingDef("limit", "int", 100, min=1, max=1000, risk="money", requires_pending=True, presets={"zzprofile": 300}, question="額度上限要設多少？", label="額度上限",
                     help="單筆核准的額度上限。", impact="影響之後送出的單據；確認期間後生效。", risk_text="額度調高後可核准更大的金額。"),
        R.SettingDef("days", "int", 7, min=1, max=30, risk="ops", presets={"zzprofile": 9}, question="提醒要提前幾天？", label="提前提醒天數",
                     help="到期前幾天開始提醒。", impact="影響之後產生的提醒，立即生效。"),
    ], help="測試用的設定群組。", risk="money")
    R.register_group("zz_nt_b", "通知測試乙", [
        R.SettingDef("cap", "int", 5, min=1, max=50, risk="ops", presets={"zzprofile": 8}, question="每日上限要設多少？", label="每日上限",
                     help="每日最多處理幾筆。", impact="影響之後的處理量，立即生效。"),
    ], help="測試用的設定群組。", risk="ops")
    yield
    R._GROUPS.pop("zz_nt_a", None)
    R._GROUPS.pop("zz_nt_b", None)
    R.invalidate()


def test_profile_apply_across_groups_sends_exactly_one_merged_notification(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_sa10")
    make_user(username="nt_sa11", role="superadmin")
    assert len(R.profile_preview("zzprofile")) == 3
    r = client.post("/api/settings-center/profiles/zzprofile/apply", json={"reason": "套預設組"}, headers=h)
    assert r.status_code == 200, r.text
    for u in ("nt_sa10", "nt_sa11"):
        n = _notes(u)
        assert len(n) == 1, (u, n)                                    # 兩個群組、三個欄位 ⇒ 一則
        m = n[0]["message"]
        assert "通知測試甲" in m and "通知測試乙" in m and "額度上限" in m and "每日上限" in m and "共 3 項" in m
        assert n[0]["ref_id"] == "batch"


def test_batch_context_collects_and_sends_once_even_when_a_later_publish_raises(client, make_user, zz_groups):
    _hdr(client, make_user, "nt_sa12")
    with pytest.raises(R.SettingError):
        with SN.batch():
            R.publish("zz_nt_b", {"cap": 9}, user="nt_sa12", reason="先成功")
            R.publish("zz_nt_b", {"cap": 999}, user="nt_sa12", reason="超出範圍")       # 驗證不過 ⇒ 丟例外
    n = _notes("nt_sa12")
    assert len(n) == 1 and "9" in n[0]["message"]                      # 已 commit 的第一筆照樣通知（一則）


def test_notification_is_sent_after_commit_and_outside_every_lock(client, make_user, zz_groups, monkeypatch):
    seen = {}
    caller = get_db()

    def fake_send(items, **_kw):
        probe = get_db()
        try:
            seen["visible"] = probe.execute("SELECT COUNT(*) FROM config_changes WHERE domain='setting:zz_nt_b'").fetchone()[0]
            probe.execute("BEGIN IMMEDIATE")                             # 寫鎖拿得到 ⇒ 呼叫端沒有握著寫交易
            probe.rollback()
        finally:
            probe.close()
        seen["caller_in_txn"] = caller.in_transaction
        seen["registry_lock_held"] = R._lock.locked()
        seen["items"] = len(items)

    monkeypatch.setattr(SN, "_send", fake_send)
    R.publish("zz_nt_b", {"cap": 12}, user="x", reason="測", conn=caller)
    caller.close()
    assert seen == {"visible": 1, "caller_in_txn": False, "registry_lock_held": False, "items": 1}


def test_a_failing_notifier_never_breaks_the_save(client, make_user, zz_groups, monkeypatch):
    h = _hdr(client, make_user, "nt_sa13")
    monkeypatch.setattr(SN, "_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 13}, "reason": "測"}, headers=h)
    assert r.status_code == 200 and r.json()["changed"] is True
    assert R.get("zz_nt_b", "cap") == 13


def test_no_change_no_notification(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_sa14")
    cur = R.get("zz_nt_b", "cap")
    client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": cur}, "reason": "沒變"}, headers=h)
    assert _notes("nt_sa14") == []


def test_due_pending_taking_effect_is_notified_once_merged(client, make_user, zz_groups, line_calls):
    _hdr(client, make_user, "nt_sa15")
    out = R.publish("zz_nt_a", {"limit": 200}, user="nt_sa15", reason="調高")
    assert out["pending"]
    before = len(_notes("nt_sa15"))
    assert R.materialize_due(now="2099-01-01T00:00:00") >= 1
    n = _notes("nt_sa15")
    assert len(n) == before + 1 and "已生效" in n[-1]["message"] and "額度上限" in n[-1]["message"]
    assert len(line_calls) >= 1 and all(c[0] == ("settings_changed",) for c in line_calls)   # money 風險：提出時與生效時都有 LINE


def test_reset_and_restore_paths_also_notify(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_sa16")
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 20}, "reason": "先改"}, headers=h).status_code == 200
    n0 = len(_notes("nt_sa16"))
    assert client.post("/api/settings-center/groups/zz_nt_b/reset", json={"fields": ["cap"], "reason": "改回預設"}, headers=h).status_code == 200
    assert len(_notes("nt_sa16")) == n0 + 1


def test_message_has_chinese_option_names_not_codes(client, make_user, line_calls):
    h = _hdr(client, make_user, "nt_sa17")
    cur = R.get("quote_approval", "reconfirm_mode")
    new = 2 if cur < 2 else 1
    assert client.post("/api/settings-center/groups/quote_approval", json={"values": {"reconfirm_mode": new}, "reason": "測試"}, headers=h).status_code == 200
    f = R.field_defs("quote_approval")["reconfirm_mode"]
    m = _notes("nt_sa17")[-1]["message"]
    assert R.show_value(f, new) in m and R.show_value(f, cur) in m


# ─────────── 通用化（SPEC §13-7）：通用項目、跨群組一次儲存、收件人預覽、復原一則、>8 行連結 ───────────

def test_generic_item_notify_change_reaches_superadmins_role_users_and_listed_accounts_and_line_for_security(client, make_user, line_calls):
    _hdr(client, make_user, "nt_g1")
    make_user(username="nt_g_sales", role="sales")
    make_user(username="nt_g_other", role="viewer")
    make_user(username="nt_g_named", role="viewer")
    SN.notify_change("permission", "王經理的權限：案件管理", "只能看", "可編輯", actor="nt_g1", reason="升任", risk="security", roles=["業務", "簽核人"],
                     recipients=["nt_g_named", "nobody_here"], plain=True, ref="perm:wang")
    for u in ("nt_g1", "nt_g_sales", "nt_g_named"):
        n = _notes(u)
        assert len(n) == 1, (u, n)
        assert "王經理的權限：案件管理" in n[0]["message"] and "只能看 → 可編輯" in n[0]["message"] and n[0]["ref_id"] == "perm:wang"
        assert n[0]["ref_label"].startswith("權限變更")
    assert _notes("nt_g_other") == []                                  # 角色不符、沒被點名
    assert len(line_calls) == 1 and line_calls[0][1]["title"] == "權限變更（高風險）" and "nt_g_sales" not in line_calls[0][1]["usernames"]
    assert "升任" not in json.dumps(line_calls[0][1], ensure_ascii=False)


def test_generic_item_unknown_kind_falls_back_and_values_are_clipped():
    it = SN.make_item("whatever", "x" * 200, "a" * 100, "b", risk="nonsense", roles=["業務"])
    assert it["kind"] == "setting" and len(it["label"]) <= 80 and len(it["oldText"]) <= 40 and it["risk"] == "none" and it["roles"] == ["業務"]
    assert SN.make_item("mail", "L", "o", "n")["kind"] == "mail"


def test_preview_recipients_is_a_dry_run_and_lists_unsupported_role_phrases(client, make_user, line_calls):
    _hdr(client, make_user, "nt_g2")
    make_user(username="nt_g2_sales", role="sales")
    before = get_db().execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    it = SN.make_item("approval_flow", "簽核流程／層級", "2 層", "3 層", "pending", actor="nt_g2", risk="money", roles=["業務", "簽核人", "受影響同仁的主管"])
    pv = SN.preview_recipients([it])
    assert _display("nt_g2") in pv["superadmins"]
    assert [o["username"] for o in pv["others"]] == ["nt_g2_sales"]
    assert pv["ignoredRoles"] == ["簽核人", "受影響同仁的主管"]       # 目前不支援的收件人：誠實列出
    assert pv["line"]["willSend"] is False and "未啟用" in pv["line"]["reason"]    # money 風險但 LINE 事件沒勾
    assert SN.preview_recipients([])["superadmins"] == []
    after = get_db().execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    assert after == before and line_calls == []                          # 沒寫通知、沒發 LINE


def test_plan_and_preview_route_return_recipients(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_g3")
    make_user(username="nt_g3_b", role="superadmin")
    r = client.post("/api/settings-center/groups/zz_nt_b/preview", json={"values": {"cap": 17}}, headers=h)
    assert r.status_code == 200
    rc = r.json()["recipients"]
    assert set(rc) == {"superadmins", "others", "ignoredRoles", "line"}
    assert len(rc["superadmins"]) >= 2 and rc["ignoredRoles"] == []
    same = client.post("/api/settings-center/groups/zz_nt_b/preview", json={"values": {"cap": R.get("zz_nt_b", "cap")}}, headers=h).json()
    assert same["recipients"]["superadmins"] == []                      # 沒有實際變更 ⇒ 沒有人會被通知
    assert _notes("nt_g3") == []                                          # 預覽不通知


def test_batch_endpoint_saves_several_groups_and_sends_exactly_one_message(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_g4")
    make_user(username="nt_g4_b", role="superadmin")
    body = {"groups": {"zz_nt_a": {"values": {"days": 11}}, "zz_nt_b": {"values": {"cap": 21}}}, "reason": "一次改兩組"}
    r = client.post("/api/settings-center/batch", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert set(r.json()["groups"]) == {"zz_nt_a", "zz_nt_b"}
    assert R.get("zz_nt_a", "days") == 11 and R.get("zz_nt_b", "cap") == 21
    for u in ("nt_g4", "nt_g4_b"):
        n = _notes(u)
        assert len(n) == 1 and n[0]["ref_id"] == "batch" and "通知測試甲" in n[0]["message"] and "通知測試乙" in n[0]["message"], (u, n)
    assert "共 2 項" in _notes("nt_g4")[0]["message"]


def test_batch_endpoint_all_validation_first_nothing_written_when_any_group_is_bad(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_g5")
    r = client.post("/api/settings-center/batch", json={"groups": {"zz_nt_a": {"values": {"days": 12}}, "zz_nt_b": {"values": {"cap": 999}}}, "reason": "含超出範圍"}, headers=h)
    assert r.status_code == 400 and "一組都沒寫入" in json.dumps(r.json(), ensure_ascii=False)
    assert R.get("zz_nt_a", "days") == 7 and _notes("nt_g5") == []


def test_batch_endpoint_input_rules_reason_empty_unknown_group_superadmin_only_and_preview_writes_nothing(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_g6")
    ok = {"zz_nt_b": {"values": {"cap": 22}}}
    assert client.post("/api/settings-center/batch", json={"groups": ok}, headers=h).status_code == 400                 # 沒填原因
    assert client.post("/api/settings-center/batch", json={"groups": {}, "reason": "x"}, headers=h).status_code == 400
    assert client.post("/api/settings-center/batch", json={"groups": {"no_such_group": {"values": {"a": 1}}}, "reason": "x"}, headers=h).status_code == 404
    assert client.post("/api/settings-center/batch", json={"groups": {"zz_nt_b": {"values": {}}}, "reason": "x"}, headers=h).status_code == 400
    assert R.get("zz_nt_b", "cap") == 5
    # 嚴格布林：preview 必須是 JSON true；字串 "yes" 不算預覽 ⇒ 會真的儲存（這裡沒填原因所以 400，什麼都沒寫）
    assert client.post("/api/settings-center/batch", json={"groups": ok, "preview": "yes"}, headers=h).status_code == 400 and R.get("zz_nt_b", "cap") == 5
    pv = client.post("/api/settings-center/batch", json={"groups": ok, "preview": True}, headers=h)
    assert pv.status_code == 200 and "recipients" in pv.json() and R.get("zz_nt_b", "cap") == 5 and _notes("nt_g6") == []
    # 多群組復原（undo／expectedValues）尚未開放：明確 400，絕不悄悄當成一般儲存
    assert client.post("/api/settings-center/batch", json={"groups": ok, "reason": "x", "undo": True}, headers=h).status_code == 400
    assert client.post("/api/settings-center/batch", json={"groups": {"zz_nt_b": {"values": {"cap": 22}, "expectedValues": {"cap": 5}}}, "reason": "x"}, headers=h).status_code == 400
    assert R.get("zz_nt_b", "cap") == 5
    low = _hdr(client, make_user, "nt_g6_admin", role="admin")
    assert client.post("/api/settings-center/batch", json={"groups": ok, "reason": "x"}, headers=low).status_code in (401, 403)


def test_restore_sends_one_restored_message_not_one_per_publish(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_g7")
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 31}, "reason": "一"}, headers=h).status_code == 200
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 32}, "reason": "二"}, headers=h).status_code == 200
    vs = client.get("/api/settings-center/groups/zz_nt_b/versions", headers=h).json()["versions"]
    first = min(v["version"] for v in vs)
    n0 = len(_notes("nt_g7"))
    r = client.post("/api/settings-center/groups/zz_nt_b/restore/%d" % first, json={"reason": "改回去"}, headers=h)
    assert r.status_code == 200, r.text
    n = _notes("nt_g7")
    assert len(n) == n0 + 1
    assert "已復原到第 %d 版" % first in n[-1]["message"] and "復原了" in n[-1]["message"] and R.get("zz_nt_b", "cap") == 31
    pv = len(_notes("nt_g7"))
    client.post("/api/settings-center/groups/zz_nt_b/restore/%d" % first, json={"preview": True}, headers=h)
    assert len(_notes("nt_g7")) == pv                                     # 預覽不通知


def test_more_than_eight_lines_ends_with_full_detail_line_and_links_to_the_change_log_tab():
    its = [SN.make_item("setting", "群組／項目%d" % i, "舊", "新", "updated", actor="a", ref="g%d" % (i % 2)) for i in range(11)]
    label, msg = SN.compose(its, {})
    lines = msg.split("\n")
    assert sum(1 for x in lines if x.startswith("• ")) == 8
    assert lines[-1].startswith("…另 3 項") and "完整明細：變更紀錄" in lines[-1]
    assert SN._link_for(its) == "settings-center.html?tab=versions"
    one_group = [SN.make_item("setting", "G／項目%d" % i, "舊", "新", "updated", ref="only") for i in range(9)]
    assert SN._link_for(one_group) == "settings-center.html?tab=versions&group=only"
    assert SN._link_for(its[:3]) == "settings-center.html"
    from helpers import audit
    assert audit._LINK_RE.match(SN._link_for(one_group))               # 通知連結守門接受（不含 #）


def test_notify_change_inside_batch_merges_with_registry_changes_into_one_message(client, make_user, zz_groups):
    _hdr(client, make_user, "nt_g8")
    with SN.batch():
        R.publish("zz_nt_b", {"cap": 33}, user="nt_g8", reason="設定")
        SN.notify_change("mail", "信件／寄件人", "舊", "新", actor="nt_g8", reason="信件")
    n = _notes("nt_g8")
    assert len(n) == 1 and "通知測試乙" in n[0]["message"] and "信件／寄件人" in n[0]["message"] and n[0]["ref_label"].startswith("設定變更")


def test_notify_change_never_raises(monkeypatch):
    monkeypatch.setattr(SN, "_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    SN.notify_change("permission", "x", "a", "b", risk="security")
    SN.emit([None, None])


def test_page_reads_tab_query_and_shows_recipients_line():
    html = open(PAGE, encoding="utf-8").read()
    assert "URLSearchParams(location.search)" in html and "'versions'" in html
    assert 'data-testid="sc-recipients"' in html and "recipientsText()" in html


# ═══════════════════════════ 前端（node＋Alpine 同款範圍代理）═══════════════════════════

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="沒有 node，前端行為題略過（CI 機有 node）")

_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const html = fs.readFileSync(input.page, 'utf8');
const at = html.indexOf('function settingsCenterPage'); const m = [null, html.slice(html.lastIndexOf('<script>', at) + 8, html.indexOf('</script>', at))];
const listeners = {};
const sandbox = { window: { addEventListener: (n, fn) => { listeners[n] = fn } }, localStorage: { getItem: () => null }, location: { hash: '' },
                  document: {}, fetch: async () => { throw new Error('no network') }, setTimeout, clearTimeout, console };
vm.createContext(sandbox);
vm.runInContext(m[1] + '\n;this.__page = settingsCenterPage;', sandbox);
// Alpine 3.17.1 的範圍代理（原樣照抄 alpine-3.17.1.min.js 的 pi）：has／get 用 Reflect.has（含原型鏈）
const pi = {
  has({ objects }, t) { return t == Symbol.unscopables ? false : objects.some(r => Object.prototype.hasOwnProperty.call(r, t) || Reflect.has(r, t)) },
  get({ objects }, t, r) { return t == 'toJSON' ? (() => {}) : Reflect.get(objects.find(n => Reflect.has(n, t)) || {}, t, r) },
  set({ objects }, t, v) { const o = objects.find(n => Reflect.has(n, t)) || objects[objects.length - 1]; o[t] = v; return true },
};
const out = [];
for (const c of input.cases) {
  const comp = sandbox.__page();
  Object.assign(comp, c.state || {});
  if (c.call) {
    let prevented = 0, e = { preventDefault() { prevented++ }, returnValue: 'unset' };
    if (c.call === 'init') {
      comp.loadGroups = async () => {}; comp.pick = async () => {}; comp.groups = [];
      comp.init().then(() => {
        const ev = { preventDefault() { prevented++ }, returnValue: 'unset' };
        listeners.beforeunload && listeners.beforeunload(ev);
        out.push({ registered: !!listeners.beforeunload, prevented, rv: ev.returnValue });
      });
      continue;
    }
    if (c.call === 'leaveGuard') { const r = comp.leaveGuard(e); out.push({ r: r === undefined ? null : r, prevented, rv: e.returnValue }); continue }
    if (c.call === 'saveSummary') { out.push(comp.saveSummary(c.arg)); continue }
  }
  const scope = new Proxy({ objects: [{ f: c.f, c: c.c }, comp] }, pi);
  const fn = new Function('scope', 'with (scope) { return (' + c.expr + ') }');
  let v;
  try { v = fn(scope) } catch (err) { v = '__ERR__' + err.message }
  out.push({ v: (v !== null && typeof v === 'object') ? '__OBJECT__' : v });
}
setTimeout(() => process.stdout.write(JSON.stringify(out)), 50);
"""


def _run_node(tmp_path, cases):
    h = tmp_path / "harness.js"
    h.write_text(_HARNESS, encoding="utf-8")
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"page": PAGE, "cases": cases}, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([NODE, str(h), str(inp)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _html():
    return open(PAGE, encoding="utf-8").read()


def _line(marker):
    for ln in _html().splitlines():
        if marker in ln:
            return ln
    raise AssertionError("頁面上找不到：" + marker)


def _expr(marker, attr):
    m = re.search(r'%s="([^"]+)"' % re.escape(attr), _line(marker))
    assert m, (marker, attr)
    return m.group(1).replace("&amp;", "&")


def _field(key, typ, value, **kw):
    f = {"key": key, "type": typ, "value": value, "default": value, "choices": [], "recommended": None}
    f.update(kw)
    return f


CHOICES_INT = [{"value": 0, "label": "關閉（預設）"}, {"value": 1, "label": "影子"}, {"value": 2, "label": "開啟"}]
CHOICES_STR = [{"value": "a", "label": "甲"}, {"value": "b", "label": "乙"}]


@needs_node
def test_every_input_type_shows_the_current_effective_value_under_alpines_scope_proxy(tmp_path):
    radio_checked = _expr("'sc-choice-' + f.key", ":checked")
    radio_cls = re.search(r"'is-on': ([^}]+)\}", _line('class="sc-choice"')).group(1)
    num_value = _expr("'sc-input-' + f.key", ":value")
    bool_checked = _expr("'sc-bool-' + f.key", ":checked")
    text_value = _expr("'sc-text-' + f.key", ":value")
    cases, expect = [], []

    def add(expr, f, c, want, drafts=None):
        cases.append({"expr": expr, "f": f, "c": c, "state": {"drafts": drafts or {}}})
        expect.append(want)

    # 選項型：數字碼（使用者回報的 reconfirm_mode：目前 2＝開啟 ⇒ 只有「開啟」被選取）
    f = _field("reconfirm_mode", "int", 2, choices=CHOICES_INT)
    for c in CHOICES_INT:
        add(radio_checked, f, c, c["value"] == 2)
        add(radio_cls, f, c, c["value"] == 2)
    add(radio_checked, f, CHOICES_INT[0], True, drafts={"reconfirm_mode": 0})            # 草稿覆蓋目前值
    add(radio_checked, f, CHOICES_INT[2], False, drafts={"reconfirm_mode": 0})
    add(radio_checked, _field("m", "int", 0, choices=CHOICES_INT), CHOICES_INT[0], True)  # 代碼 0 也要能選取（假值）
    # 選項型：字串碼；伺服器給數字、選項給字串（或反過來）也要選得到
    fs = _field("s", "str", "b", choices=CHOICES_STR)
    for c in CHOICES_STR:
        add(radio_checked, fs, c, c["value"] == "b")
    add(radio_checked, _field("mix", "int", 1, choices=[{"value": "1", "label": "一"}]), {"value": "1", "label": "一"}, True)
    # 數字型 int／float（使用者回報的 confirm_period_days：目前 7 ⇒ 輸入框顯示 7）
    add(num_value, _field("confirm_period_days", "int", 7), None, 7)
    add(num_value, _field("pct", "float", 1.5), None, 1.5)
    add(num_value, _field("zero", "int", 0), None, 0)
    add(num_value, _field("confirm_period_days", "int", 7), None, 9, drafts={"confirm_period_days": 9})
    # 開關型
    add(bool_checked, _field("on", "bool", True), None, True)
    add(bool_checked, _field("off", "bool", False), None, False)
    add(bool_checked, _field("on", "bool", True), None, False, drafts={"on": False})
    # 文字型
    add(text_value, _field("name", "str", "abc"), None, "abc")
    add(text_value, _field("name", "str", "abc"), None, "xyz", drafts={"name": "xyz"})
    got = [r["v"] for r in _run_node(tmp_path, cases)]
    assert got == expect


@needs_node
def test_harness_reproduces_the_original_bug_valueof_resolves_to_object_prototype(tmp_path):
    """對照：舊的 `valueOf(f)` 在 x-for 範圍代理下拿到的是範圍物件（不是值）。這題證明上面的題目真的抓得到那個 bug。"""
    got = _run_node(tmp_path, [{"expr": "valueOf(f)", "f": _field("k", "int", 7), "c": None, "state": {}}])
    assert got[0]["v"] == "__OBJECT__"


@needs_node
def test_recommended_badge_only_on_the_recommended_choice_and_reads_as_suggested_value(tmp_path):
    line = _line("'sc-rec-'")
    assert "建議值</span>" in line
    show = re.search(r'x-show="([^"]+)"', line).group(1)
    cases = [{"expr": show, "f": _field("k", "int", 2, choices=CHOICES_INT, recommended=0), "c": c, "state": {}} for c in CHOICES_INT]
    cases += [{"expr": show, "f": _field("k", "int", 2, choices=CHOICES_INT, recommended=None), "c": c, "state": {}} for c in CHOICES_INT]
    cases += [{"expr": show, "f": {"key": "k", "choices": CHOICES_INT}, "c": CHOICES_INT[0], "state": {}}]      # 欄位沒有 recommended 屬性
    got = [r["v"] for r in _run_node(tmp_path, cases)]
    assert got == [True, False, False, False, False, False, False]


@needs_node
def test_leave_page_warning_only_when_there_are_unsaved_drafts(tmp_path):
    got = _run_node(tmp_path, [
        {"call": "leaveGuard", "state": {"drafts": {"a": 1}}},
        {"call": "leaveGuard", "state": {"drafts": {}}},
        {"call": "init", "state": {"drafts": {"a": 1}}},
    ])
    assert got[0]["prevented"] == 1 and got[0]["rv"] == "" and "尚未儲存" in got[0]["r"]
    assert got[1] == {"r": None, "prevented": 0, "rv": "unset"}
    assert got[2] == {"registered": True, "prevented": 1, "rv": ""}      # init() 真的把 beforeunload 掛上去


@needs_node
def test_save_result_wording_instant_vs_waiting_for_second_superadmin(tmp_path):
    got = _run_node(tmp_path, [
        {"call": "saveSummary", "arg": {"changed": True, "pending": []}},
        {"call": "saveSummary", "arg": {"changed": False, "pending": [{"approvalsRequired": 1, "effectiveAt": "2026-11-20T10:00:00"}]}},
        {"call": "saveSummary", "arg": {"changed": False, "pending": [{"approvalsRequired": 0, "effectiveAt": "2026-11-18T10:00:00"}]}},
        {"call": "saveSummary", "arg": {"changed": True, "pending": [{"approvalsRequired": 1, "effectiveAt": "2026-11-20T10:00:00"}]}},
        {"call": "saveSummary", "arg": {"changed": False, "pending": []}},
    ])
    assert got[0] == {"kind": "ok", "text": "已生效"}
    assert got[1] == {"kind": "wait", "text": "已送出，待第二位最高管理者核准，預計 11 月 20 日生效"}
    assert got[2] == {"kind": "wait", "text": "已送出，確認期間後生效，預計 11 月 18 日生效"}
    assert got[3]["text"] == "已生效；已送出，待第二位最高管理者核准，預計 11 月 20 日生效"
    assert got[4]["text"] == "沒有任何變更"


def test_page_markup_unsaved_markers_bottom_bar_and_buttons():
    html = _html()
    assert re.search(r'class="sc-unsaved"[^>]*x-show="isDirty\(f\)"[^>]*>未儲存<', html) or ('sc-unsaved' in _line("'sc-unsaved-'") and "未儲存" in _line("'sc-unsaved-'"))
    bar = re.search(r'<div class="sc-bar"[^>]*>', html).group(0)
    assert 'x-show="dirtyCount()"' in bar                               # 任何頁籤都看得到
    assert "'有 ' + dirtyCount() + ' 項未儲存'" in html
    assert re.search(r'data-testid="sc-save"[^>]*>儲存</button>', html)
    assert re.search(r'data-testid="sc-discard"[^>]*>放棄</button>', html)
    assert 'data-testid="sc-toast"' in html and "beforeunload" in html


def test_no_alpine_component_method_shadows_an_object_prototype_member():
    """全站守門：x-data 元件的方法名不能是 Object.prototype 的成員（valueOf／toString…）：Alpine 的範圍代理會解析到繼承來的原生函式。"""
    bad = re.compile(r"^\s*(?:async\s+)?(valueOf|toString|toLocaleString|hasOwnProperty|isPrototypeOf|propertyIsEnumerable|constructor)\s*\([^)]*\)\s*\{", re.M)
    hits = []
    for root, dirs, files in os.walk(FRONTEND):
        dirs[:] = [d for d in dirs if d not in ("vendor", "node_modules")]
        for f in files:
            if f.endswith((".html", ".js")):
                p = os.path.join(root, f)
                src = open(p, encoding="utf-8", errors="ignore").read()
                hits += ["%s:%s" % (os.path.relpath(p, FRONTEND), m.group(1)) for m in bad.finditer(src)]
    assert hits == []
