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
    assert _notes("nt_sa1") == []                                   # 操作者本人不收自己操作的站內通知（他自己知道；PM 2026-11-13）
    for u in ("nt_sa2",):                                           # 其他在職最高管理者收到（ops 風險、非敏感群組 ⇒ 看得到值與原因）
        n = _notes(u)
        assert len(n) == 1, (u, n)
        m = n[0]["message"]
        assert _display("nt_sa1") in m and label in m and "10" in m and "磁碟快滿了" in m and "立即生效" in m and "→" in m
        assert n[0]["link"] == "settings-center.html"
    assert _notes("nt_admin") == []                                  # 管理員不是這個欄位的影響角色（ops 欄位沒有 impact_scope）
    assert not _notes("nt_sa1", "config_change")                     # 帳本的簡短通知不重複發
    assert line_calls == []                                          # ops 風險不發 LINE


# ── 通知去重的水位線（publish 的 `_notice_watermark`；h11 審查：sqlite_sequence 取不到時不可以誤刪舊通知）──────────

def _cfg_notice_ids():
    conn = get_db()
    try:
        return [r[0] for r in conn.execute("SELECT id FROM notifications WHERE type='config_change' AND ref_label LIKE 'setting:%' ORDER BY id").fetchall()]
    finally:
        conn.close()


def _seed_old_cfg_notices(n):
    conn = get_db()
    try:
        ids = [conn.execute("INSERT INTO notifications (username, type, ref_label, message, created_at) VALUES ('nt_old', 'config_change', 'setting:old_zz', ?, '2026-01-01T00:00:00')",
                            ("舊通知 %d" % i,)).lastrowid for i in range(n)]
        conn.commit()
        return ids
    finally:
        conn.close()


def _db_exec(sql, args=()):
    conn = get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _db_rows(sql, args=()):
    conn = get_db()
    try:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _tighten_uploads(client, h, mb):
    r = client.post("/api/settings-center/groups/uploads", json={"values": {"max_file_mb": mb}, "reason": "測"}, headers=h)
    assert r.status_code == 200 and r.json()["changed"] is True, r.text


def test_dedupe_watermark_empty_notifications_table_still_dedupes_and_still_notifies(client, make_user):
    h = _hdr(client, make_user, "nt_e1")
    make_user(username="nt_e2", role="superadmin")
    _seed_old_cfg_notices(2)
    _db_exec("DELETE FROM notifications")                            # 表清空；sqlite_sequence 的列還在
    _tighten_uploads(client, h, 12)
    assert _cfg_notice_ids() == []                                   # 帳本的簡短通知被取代
    assert len(_notes("nt_e2")) == 1                                 # 設定中心的通知仍然發出


def test_dedupe_watermark_pruned_top_ids_keep_old_notices(client, make_user):
    h = _hdr(client, make_user, "nt_p1")
    make_user(username="nt_p2", role="superadmin")
    ids = _seed_old_cfg_notices(5)
    _db_exec("DELETE FROM notifications WHERE id>?", (ids[2],))      # 最大的幾個 id 被清掉：seq > MAX(id)
    _tighten_uploads(client, h, 13)
    assert _cfg_notice_ids() == ids[:3]                              # 舊的留著、這次的簡短通知被去重


def test_dedupe_watermark_missing_sequence_row_never_deletes_old_notices(client, make_user):
    h = _hdr(client, make_user, "nt_m1")
    make_user(username="nt_m2", role="superadmin")
    ids = _seed_old_cfg_notices(3)
    _db_exec("DELETE FROM sqlite_sequence WHERE name='notifications'")
    conn = get_db()
    try:
        mark = R._notice_watermark(conn)                             # 沒有 seq 列：回退讀 MAX(id)（唯一一筆登記在基準的 notifications 讀取）
        count = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    finally:
        conn.close()
    assert mark == max(ids)
    assert count == len(ids), "水位線不可以在 notifications 寫任何暫存列"
    assert _cfg_notice_ids() == ids
    _db_exec("DELETE FROM sqlite_sequence WHERE name='notifications'")
    _tighten_uploads(client, h, 14)
    assert _cfg_notice_ids() == ids                                  # 沒有 seq 列時存檔：舊通知不被去重的 DELETE 帶走


def test_dedupe_watermark_failure_returns_none_instead_of_breaking_the_save():
    class _Boom:
        def execute(self, *a, **k):
            raise RuntimeError("sqlite_sequence 不存在")
    assert R._notice_watermark(_Boom()) is None


def test_inactive_superadmin_is_not_notified(client, make_user):
    h = _hdr(client, make_user, "nt_sa3")
    make_user(username="nt_sa4", role="superadmin")
    make_user(username="nt_sa3b", role="superadmin")
    conn = get_db()
    conn.execute("UPDATE users SET active=0 WHERE username='nt_sa4'")
    conn.commit()
    conn.close()
    assert client.post("/api/settings-center/groups/uploads", json={"values": {"max_file_mb": 11}, "reason": "測"}, headers=h).status_code == 200
    assert len(_notes("nt_sa3b")) == 1 and _notes("nt_sa4") == [] and _notes("nt_sa3") == []


def test_roles_listed_in_impact_scope_are_notified_and_unlisted_are_not(client, make_user, line_calls):
    h = _hdr(client, make_user, "nt_sa5")
    make_user(username="nt_sa5b", role="superadmin")
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
    assert _notes("nt_sa5") == []                                    # 操作者本人不收
    assert len(_notes("nt_sa5b")) == 1 and "→" in _notes("nt_sa5b")[0]["message"]      # 其他最高管理者看得到值
    sales = _notes("nt_sales")[0]["message"]                         # money 風險：業務只知道「已變更」，看不到值與原因
    assert "設定已變更" in sales and "→" not in sales and "原因" not in sales and "試行" not in sales


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
    assert _notes("nt_sa10") == []                                    # 操作者本人不收
    for u in ("nt_sa11",):
        n = _notes(u)
        assert len(n) == 1, (u, n)                                    # 兩個群組、三個欄位 ⇒ 一則
        m = n[0]["message"]
        assert "通知測試甲" in m and "通知測試乙" in m and "額度上限" in m and "每日上限" in m and "共 3 項" in m
        assert n[0]["ref_id"] == "batch"


def test_batch_context_collects_and_sends_once_even_when_a_later_publish_raises(client, make_user, zz_groups):
    _hdr(client, make_user, "nt_sa12")
    make_user(username="nt_sa12b", role="superadmin")
    with pytest.raises(R.SettingError):
        with SN.batch():
            R.publish("zz_nt_b", {"cap": 9}, user="nt_sa12", reason="先成功")
            R.publish("zz_nt_b", {"cap": 999}, user="nt_sa12", reason="超出範圍")       # 驗證不過 ⇒ 丟例外
    n = _notes("nt_sa12b")
    assert len(n) == 1 and "9" in n[0]["message"] and _notes("nt_sa12") == []                      # 已 commit 的第一筆照樣通知（一則）


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
    make_user(username="nt_sa16b", role="superadmin")
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 20}, "reason": "先改"}, headers=h).status_code == 200
    n0 = len(_notes("nt_sa16b"))
    assert client.post("/api/settings-center/groups/zz_nt_b/reset", json={"fields": ["cap"], "reason": "改回預設"}, headers=h).status_code == 200
    assert len(_notes("nt_sa16b")) == n0 + 1


def test_message_has_chinese_option_names_not_codes(client, make_user, line_calls):
    h = _hdr(client, make_user, "nt_sa17")
    make_user(username="nt_sa17b", role="superadmin")
    cur = R.get("quote_approval", "reconfirm_mode")
    new = 2 if cur < 2 else 1
    assert client.post("/api/settings-center/groups/quote_approval", json={"values": {"reconfirm_mode": new}, "reason": "測試"}, headers=h).status_code == 200
    f = R.field_defs("quote_approval")["reconfirm_mode"]
    m = _notes("nt_sa17b")[-1]["message"]
    assert R.show_value(f, new) in m and R.show_value(f, cur) in m


# ─────────── 通用化（SPEC §13-7）：通用項目、跨群組一次儲存、收件人預覽、復原一則、>8 行連結 ───────────

def test_generic_item_notify_change_reaches_superadmins_role_users_and_listed_accounts_and_line_for_security(client, make_user, line_calls):
    _hdr(client, make_user, "nt_g1")
    make_user(username="nt_g1b", role="superadmin")
    make_user(username="nt_g_sales", role="sales")
    make_user(username="nt_g_other", role="viewer")
    make_user(username="nt_g_named", role="viewer")
    SN.notify_change("permission", "王經理的權限：案件管理", "只能看", "可編輯", actor="nt_g1", reason="升任", risk="security", roles=["業務", "簽核人"],
                     recipients=["nt_g_named", "nobody_here"], plain=True, ref="perm:wang")
    assert _notes("nt_g1") == []                                       # 操作者本人不收
    full = _notes("nt_g1b")
    assert len(full) == 1 and "只能看 → 可編輯" in full[0]["message"] and "升任" in full[0]["message"]        # 其他最高管理者：值與原因都看得到
    for u in ("nt_g1b", "nt_g_sales", "nt_g_named"):
        n = _notes(u)
        assert len(n) == 1, (u, n)
        assert "王經理的權限：案件管理" in n[0]["message"] and n[0]["ref_id"] == "perm:wang"
        assert n[0]["ref_label"].startswith("權限變更")
    for u in ("nt_g_sales", "nt_g_named"):                               # security 風險：非最高管理者只知道「已變更」，沒有值也沒有原因
        m = _notes(u)[0]["message"]
        assert "設定已變更" in m and "→" not in m and "只能看" not in m and "可編輯" not in m and "升任" not in m and "原因" not in m
    assert _notes("nt_g_other") == []                                  # 角色不符、沒被點名
    assert len(line_calls) == 1 and line_calls[0][1]["title"] == "權限變更（高風險）" and "nt_g_sales" not in line_calls[0][1]["usernames"]
    assert "升任" not in json.dumps(line_calls[0][1], ensure_ascii=False)


def test_generic_item_unknown_kind_falls_back_and_values_are_clipped():
    it = SN.make_item("whatever", "x" * 200, "a" * 100, "b", risk="nonsense", roles=["業務"])
    assert it["kind"] == "setting" and len(it["label"]) <= 80 and len(it["oldText"]) <= 40 and it["risk"] == "none" and it["roles"] == ["業務"]
    assert SN.make_item("mail", "L", "o", "n")["kind"] == "mail"


def test_preview_recipients_is_a_dry_run_and_lists_unsupported_role_phrases(client, make_user, line_calls):
    _hdr(client, make_user, "nt_g2")
    make_user(username="nt_g2b", role="superadmin")
    make_user(username="nt_g2_sales", role="sales")
    before = get_db().execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    it = SN.make_item("approval_flow", "簽核流程／層級", "2 層", "3 層", "pending", actor="nt_g2", risk="money", roles=["業務", "簽核人", "受影響同仁的主管"])
    pv = SN.preview_recipients([it])
    assert _display("nt_g2b") in pv["superadmins"] and _display("nt_g2") not in pv["superadmins"]      # 操作者本人不收站內通知 ⇒ 不列
    assert [o["username"] for o in pv["others"]] == ["nt_g2_sales"] and pv["redactedForOthers"] is True   # money 風險：業務只看到「已變更」
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
    assert set(rc) == {"superadmins", "others", "ignoredRoles", "redactedForOthers", "line"}
    assert len(rc["superadmins"]) >= 1 and _display("nt_g3") not in rc["superadmins"] and rc["ignoredRoles"] == []
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
    assert _notes("nt_g4") == []                                          # 操作者本人不收
    n = _notes("nt_g4_b")
    assert len(n) == 1 and n[0]["ref_id"] == "batch" and "通知測試甲" in n[0]["message"] and "通知測試乙" in n[0]["message"], n
    assert "共 2 項" in n[0]["message"]


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
    # 復原（undo）一定要每組帶 expectedValues、且涵蓋每個要改的欄位；格式不對一律 400，什麼都沒寫
    assert client.post("/api/settings-center/batch", json={"groups": ok, "reason": "x", "undo": True}, headers=h).status_code == 400
    assert client.post("/api/settings-center/batch", json={"groups": ok, "reason": "x", "undo": "yes"}, headers=h).status_code == 400
    assert client.post("/api/settings-center/batch", json={"groups": {"zz_nt_b": {"values": {"cap": 22}, "expectedValues": {}}}, "reason": "x"}, headers=h).status_code == 400
    assert client.post("/api/settings-center/batch", json={"groups": {"zz_nt_a": {"values": {"days": 12, "limit": 120}, "expectedValues": {"days": 7}}}, "reason": "x"}, headers=h).status_code == 400
    assert R.get("zz_nt_b", "cap") == 5 and R.get("zz_nt_a", "days") == 7
    low = _hdr(client, make_user, "nt_g6_admin", role="admin")
    assert client.post("/api/settings-center/batch", json={"groups": ok, "reason": "x"}, headers=low).status_code in (401, 403)


def _batch(client, h, groups, **kw):
    return client.post("/api/settings-center/batch", json={"groups": groups, **kw}, headers=h)


def test_batch_undo_restores_both_groups_with_one_restored_message(client, make_user, zz_groups):
    """S1d＋S1c：套用 → 復原（expectedValues＝套用後的值）→ 兩組都回到原值；只發一則「復原了…」，且預設原因＝復原批次。"""
    h = _hdr(client, make_user, "nt_u1")
    make_user(username="nt_u1b", role="superadmin")
    assert _batch(client, h, {"zz_nt_a": {"values": {"days": 11}}, "zz_nt_b": {"values": {"cap": 21}}}, reason="先改").status_code == 200
    n0 = len(_notes("nt_u1b"))
    r = _batch(client, h, {"zz_nt_a": {"values": {"days": 7}, "expectedValues": {"days": 11}},
                           "zz_nt_b": {"values": {"cap": 5}, "expectedValues": {"cap": 21}}}, undo=True)
    assert r.status_code == 200, r.text
    assert R.get("zz_nt_a", "days") == 7 and R.get("zz_nt_b", "cap") == 5
    n = _notes("nt_u1b")
    assert len(n) == n0 + 1 and "復原了" in n[-1]["message"] and "已復原批次儲存" in n[-1]["message"], n[-1]
    rows = _db_rows("SELECT reason FROM config_changes WHERE domain='setting:zz_nt_b' ORDER BY id DESC LIMIT 1")
    assert rows and rows[0][0] == "復原批次", rows                                     # 沒填原因 ⇒ 預設「復原批次」寫進帳本


def test_batch_undo_refused_when_someone_changed_a_field_after_apply_and_nothing_is_written(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_u2")
    make_user(username="nt_u2b", role="superadmin")
    assert _batch(client, h, {"zz_nt_a": {"values": {"days": 11}}, "zz_nt_b": {"values": {"cap": 21}}}, reason="先改").status_code == 200
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 33}, "reason": "別人又改"}, headers=h).status_code == 200
    n0 = len(_notes("nt_u2b"))
    r = _batch(client, h, {"zz_nt_a": {"values": {"days": 7}, "expectedValues": {"days": 11}},
                           "zz_nt_b": {"values": {"cap": 5}, "expectedValues": {"cap": 21}}}, undo=True)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "conflict", r.text
    assert [(x["group"], [k["key"] for k in x["keys"]]) for x in d["groups"]] == [("zz_nt_b", ["cap"])] and d["groups"][0]["label"] == "通知測試乙"
    assert d["applied"] == [] and d["failed"] is None and d["notApplied"] == ["zz_nt_a", "zz_nt_b"]
    assert R.get("zz_nt_a", "days") == 11 and R.get("zz_nt_b", "cap") == 33          # 預檢：連沒衝突的甲組也不寫
    assert len(_notes("nt_u2b")) == n0


def test_batch_save_with_expected_values_works_and_a_stale_one_is_409(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_u3")
    ok = _batch(client, h, {"zz_nt_b": {"values": {"cap": 22}, "expectedValues": {"cap": 5}}}, reason="帶 CAS 的一般儲存")
    assert ok.status_code == 200 and R.get("zz_nt_b", "cap") == 22
    stale = _batch(client, h, {"zz_nt_b": {"values": {"cap": 23}, "expectedValues": {"cap": 5}}}, reason="看到的是舊值")
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "conflict" and R.get("zz_nt_b", "cap") == 22


def test_batch_conflict_after_precheck_reports_applied_and_not_applied(client, make_user, zz_groups, monkeypatch):
    """預檢過了、寫入時才被別人改（競態）：照樣是 conflict 形狀，並說清楚已寫入／未處理。"""
    h = _hdr(client, make_user, "nt_u4")
    monkeypatch.setattr(R, "expected_conflict", lambda g, exp, **kw: None)           # 模擬預檢看不到、之後才變
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 40}, "reason": "搶先"}, headers=h).status_code == 200
    r = _batch(client, h, {"zz_nt_a": {"values": {"days": 12}, "expectedValues": {"days": 7}},
                           "zz_nt_b": {"values": {"cap": 6}, "expectedValues": {"cap": 5}}}, reason="競態")
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "conflict" and d["applied"] == ["zz_nt_a"] and d["failed"] == "zz_nt_b" and d["notApplied"] == [], r.text
    assert [x["group"] for x in d["groups"]] == ["zz_nt_b"] and R.get("zz_nt_a", "days") == 12 and R.get("zz_nt_b", "cap") == 40


def test_batch_pending_exists_has_its_own_message_and_code_not_plain_conflict(client, make_user, zz_groups):
    from routers import settings_center as SC
    pe = R.SettingConflict(["cap"], "王經理", "2026-11-13T10:00:00", code="pending_exists")
    one = SC._batch_conflict_body([("zz_nt_b", pe)], [], "zz_nt_b", [])
    assert one["code"] == "pending_exists" and "等待生效" in one["message"] and one["groups"][0]["code"] == "pending_exists", one
    assert one["groups"][0]["by"] == "王經理" and one["groups"][0]["label"] == "通知測試乙"
    plain = R.SettingConflict(["days"], "李", "t")
    mixed = SC._batch_conflict_body([("zz_nt_b", pe), ("zz_nt_a", plain)], [], None, [])
    assert mixed["code"] == "conflict" and [x["code"] for x in mixed["groups"]] == ["pending_exists", "conflict"]      # 混合 ⇒ 一般衝突（要重新整理）
    assert SC._batch_conflict_body([("zz_nt_a", plain)], [], None, [])["code"] == "conflict"


def test_batch_400_messages_are_plain_language_without_programmer_words(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_u6")
    bad = [
        {"groups": {"zz_nt_b": {"values": {"cap": 22}}}, "reason": "x", "undo": "yes"},                                           # undo 不是布林
        {"groups": {"zz_nt_b": {"values": {"cap": 22}}}, "reason": "x", "undo": True},                                            # 復原沒帶比對資料
        {"groups": {"zz_nt_b": {"values": {"cap": 22}, "expectedValues": {}}}, "reason": "x"},                                    # 比對資料是空的
        {"groups": {"zz_nt_a": {"values": {"days": 12, "limit": 120}, "expectedValues": {"days": 7}}}, "reason": "x"},            # 沒涵蓋每個要改的欄位
    ]
    for body in bad:
        r = client.post("/api/settings-center/batch", json=body, headers=h)
        assert r.status_code == 400, (body, r.text)
        txt = json.dumps(r.json(), ensure_ascii=False)
        for w in ("expectedValues", "undo", "true", "false", "json", "JSON", "key"):
            assert w not in txt, (w, txt)
        assert "請重新整理畫面後再試" in txt, txt
    assert "額度上限" in client.post("/api/settings-center/batch", json=bad[3], headers=h).text            # 缺的欄位用白話名稱，不是欄位代碼


def test_expected_conflict_precheck_is_read_only_and_reports_who_changed_it(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_u5")
    assert R.expected_conflict("zz_nt_b", {"cap": 5}) is None
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 9}, "reason": "改"}, headers=h).status_code == 200
    c = R.expected_conflict("zz_nt_b", {"cap": 5})
    assert isinstance(c, R.SettingConflict) and c.keys == ["cap"] and c.by and R.get("zz_nt_b", "cap") == 9
    with pytest.raises(R.SettingError):
        R.expected_conflict("zz_nt_b", {"nope": 1})


def test_restore_sends_one_restored_message_not_one_per_publish(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_g7")
    make_user(username="nt_g7b", role="superadmin")
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 31}, "reason": "一"}, headers=h).status_code == 200
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 32}, "reason": "二"}, headers=h).status_code == 200
    vs = client.get("/api/settings-center/groups/zz_nt_b/versions", headers=h).json()["versions"]
    first = min(v["version"] for v in vs)
    n0 = len(_notes("nt_g7b"))
    r = client.post("/api/settings-center/groups/zz_nt_b/restore/%d" % first, json={"reason": "改回去"}, headers=h)
    assert r.status_code == 200, r.text
    n = _notes("nt_g7b")
    assert len(n) == n0 + 1
    assert "已復原到第 %d 版" % first in n[-1]["message"] and "復原了" in n[-1]["message"] and R.get("zz_nt_b", "cap") == 31
    pv = len(_notes("nt_g7b"))
    client.post("/api/settings-center/groups/zz_nt_b/restore/%d" % first, json={"preview": True}, headers=h)
    assert len(_notes("nt_g7b")) == pv                                     # 預覽不通知


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
    make_user(username="nt_g8b", role="superadmin")
    with SN.batch():
        R.publish("zz_nt_b", {"cap": 33}, user="nt_g8", reason="設定")
        SN.notify_change("mail", "信件／寄件人", "舊", "新", actor="nt_g8", reason="信件")
    n = _notes("nt_g8b")
    assert _notes("nt_g8") == []
    assert len(n) == 1 and "通知測試乙" in n[0]["message"] and "信件／寄件人" in n[0]["message"] and n[0]["ref_label"].startswith("設定變更")


def test_notify_change_never_raises(monkeypatch):
    monkeypatch.setattr(SN, "_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    SN.notify_change("permission", "x", "a", "b", risk="security")
    SN.emit([None, None])


def test_page_reads_tab_query_and_shows_recipients_line():
    html = open(PAGE, encoding="utf-8").read()
    assert "URLSearchParams(location.search)" in html and "'versions'" in html
    assert 'data-testid="sc-recipients"' in html and "recipientsText()" in html
    assert "redactedForOthers" in html and "不會收到自己操作的通知" in html


# ─────────── h11 審查修正（2026-11-13）：隱私去識別、None 項目、逐人隔離、notApplied、原因不擠掉完整明細 ───────────

def test_security_change_to_all_users_scope_shows_values_and_reason_only_to_other_superadmins(client, make_user, line_calls):
    """h11 M1：external_login 的 impact_scope.roles＝「所有使用者」且 risk＝security。一般使用者只能知道「某某設定已變更、由誰何時操作」，看不到值與原因。"""
    h = _hdr(client, make_user, "nt_p1")
    make_user(username="nt_p1b", role="superadmin")
    make_user(username="nt_p_user", role="viewer")
    make_user(username="nt_p_sales", role="sales")
    f = R.field_defs("external_login")["lock_threshold"]
    assert f.risk == "security" and "所有使用者" in f.impact_scope["roles"]
    cur = R.get("external_login", "lock_threshold")
    new = cur - 1 if cur > 3 else cur + 1
    r = client.post("/api/settings-center/groups/external_login", json={"values": {"lock_threshold": new}, "reason": "機密原因XYZ"}, headers=h)
    assert r.status_code == 200, r.text
    sa = _notes("nt_p1b")[0]["message"]
    assert "→" in sa and "機密原因XYZ" in sa and f.label in sa                # 其他最高管理者：完整
    assert _notes("nt_p1") == []                                           # 操作者本人不收
    for u in ("nt_p_user", "nt_p_sales"):
        n = _notes(u)
        assert len(n) == 1, (u, n)
        m = n[0]["message"]
        assert "設定已變更" in m and f.label in m and _display("nt_p1") in m and "立即生效" in m
        assert "→" not in m and "機密原因XYZ" not in m and "原因" not in m and ("%s → %s" % (cur, new)) not in m


def test_sensitive_group_with_ops_risk_is_also_redacted_for_non_superadmins():
    """sensitive 群組（即使欄位風險是 ops）也去識別；非敏感＋ops 風險的照常完整。"""
    secret = SN.make_item("setting", "G／F", "舊值AAA", "新值BBB", "updated", actor="a", reason="私密原因", sensitive=True)
    plain = SN.make_item("setting", "G／F2", "舊值CCC", "新值DDD", "updated", actor="a", reason="一般原因")
    _l, m_user = SN.compose([secret], {}, full=False)
    assert "舊值AAA" not in m_user and "新值BBB" not in m_user and "私密原因" not in m_user and "設定已變更" in m_user
    _l, m_sa = SN.compose([secret], {}, full=True)
    assert "舊值AAA → 新值BBB" in m_sa and "私密原因" in m_sa
    _l, m_plain = SN.compose([plain], {}, full=False)
    assert "舊值CCC → 新值DDD" in m_plain and "原因" not in m_plain                  # 非敏感：值照給；原因一律只給最高管理者
    mixed = SN.compose([secret, plain], {}, full=False)[1]
    assert "舊值AAA" not in mixed and "舊值CCC → 新值DDD" in mixed and "私密原因" not in mixed


def test_activated_notification_reaches_other_superadmins_in_full(client, make_user, zz_groups):
    _hdr(client, make_user, "nt_p2")
    make_user(username="nt_p2b", role="superadmin")
    out = R.publish("zz_nt_a", {"limit": 250}, user="nt_p2", reason="私密原因QQQ")
    assert out["pending"]
    assert R.materialize_due(now="2099-01-01T00:00:00") >= 1
    sa = [x for x in _notes("nt_p2b") if "已生效" in x["message"]]
    assert sa and "私密原因QQQ" in sa[-1]["message"]                          # 最高管理者看得到（money：值與原因）


def test_item_that_failed_to_build_does_not_delete_the_ledger_notification(client, make_user, zz_groups, monkeypatch):
    """h11 S1：setting_item 失敗（None）時，帳本自己對高風險變更的簡短通知不能被刪（否則誰都沒被通知）。"""
    _hdr(client, make_user, "nt_p3")
    make_user(username="nt_p3b", role="superadmin")
    monkeypatch.setattr(SN, "setting_item", lambda *a, **k: None)
    out = R.publish("zz_nt_a", {"limit": 220}, user="nt_p3", reason="測")
    assert out["pending"]
    assert _notes("nt_p3b") == []                                           # 新通知元件沒發（項目建不出來）
    assert len(_notes("nt_p3b", "config_change")) >= 1                      # 帳本的簡短通知還在


def test_one_recipient_failing_does_not_drop_the_others(client, make_user, zz_groups, monkeypatch):
    """h11 S5：某個收件人的站內通知寫入失敗，其他人照發、LINE 照發。"""
    from helpers import audit
    h = _hdr(client, make_user, "nt_p4")
    make_user(username="nt_p4b", role="superadmin")
    make_user(username="nt_p4c", role="superadmin")
    real = audit._notify_in_txn

    def flaky(conn, user, *a, **k):
        if user == "nt_p4b":
            raise RuntimeError("boom")
        return real(conn, user, *a, **k)

    monkeypatch.setattr(audit, "_notify_in_txn", flaky)
    assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 14}, "reason": "測"}, headers=h).status_code == 200
    assert _notes("nt_p4b") == [] and len(_notes("nt_p4c")) == 1


def test_batch_409_lists_not_applied_groups(client, make_user, zz_groups, monkeypatch):
    h = _hdr(client, make_user, "nt_p5")
    real = R.publish

    def boom_on_b(group, *a, **k):
        if group == "zz_nt_a":
            raise RuntimeError("故意失敗")
        return real(group, *a, **k)

    monkeypatch.setattr(R, "publish", boom_on_b)
    body = {"groups": {"zz_nt_b": {"values": {"cap": 15}}, "zz_nt_a": {"values": {"days": 13}}, "uploads": {"values": {"max_file_mb": 12}}}, "reason": "測"}
    r = client.post("/api/settings-center/batch", json=body, headers=h)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["applied"] == ["zz_nt_b"] and d["failed"] == "zz_nt_a" and d["notApplied"] == ["uploads"]


def test_long_reason_never_cuts_the_full_detail_line():
    its = [SN.make_item("setting", "群組／項目%d" % i, "舊" * 30, "新" * 30, "updated", actor="a", reason="很長的原因" * 40, ref="g") for i in range(11)]
    _l, msg = SN.compose(its, {})
    assert "完整明細：變更紀錄" in msg and len(msg) <= SN._MAX_MSG
    assert msg.index("完整明細：變更紀錄") < msg.index("原因：")


def test_actor_only_system_sends_no_in_app_notification_but_preview_says_so(client, make_user, zz_groups):
    h = _hdr(client, make_user, "nt_p6")
    conn = get_db()
    try:
        others = [r[0] for r in conn.execute("SELECT username FROM users WHERE active=1 AND role='superadmin' AND username<>?", ("nt_p6",)).fetchall()]
        for u in others:
            conn.execute("UPDATE users SET active=0 WHERE username=?", (u,))
        conn.commit()
    finally:
        conn.close()
    try:
        pv = client.post("/api/settings-center/groups/zz_nt_b/preview", json={"values": {"cap": 16}}, headers=h).json()["recipients"]
        assert pv["superadmins"] == [] and pv["others"] == []
        assert client.post("/api/settings-center/groups/zz_nt_b", json={"values": {"cap": 16}, "reason": "測"}, headers=h).status_code == 200
        assert _notes("nt_p6") == []
    finally:
        conn = get_db()
        try:
            for u in others:
                conn.execute("UPDATE users SET active=1 WHERE username=?", (u,))
            conn.commit()
        finally:
            conn.close()


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
    assert got[2] == {"kind": "wait", "text": "已送出，等待期滿後生效，預計 11 月 18 日生效"}
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


def _json_group(name, label):
    R.register_group(name, label, [
        R.SettingDef("doc", "json", [], question="這份清單要放什麼？", label="清單", help="測試用的整份清單。", impact="影響之後使用這份清單的畫面。",
                     risk="money", risk_text="清單改錯會影響金額。", loosen="both",
                     impact_scope={"documents": ["測試單據"], "roles": ["測試角色"], "amounts": "不影響已開出的金額", "reversible": True, "effective": "pending"})],
        help="測試用的整份清單群組。", risk="money")


@pytest.fixture()
def zz_json_groups(zz_groups):
    _json_group("zz_nt_j1", "清單甲")
    _json_group("zz_nt_j2", "清單乙")
    yield
    R._GROUPS.pop("zz_nt_j1", None)
    R._GROUPS.pop("zz_nt_j2", None)
    R.invalidate()


def _writes():
    return _db_rows("SELECT COUNT(*) FROM config_changes")[0][0], _db_rows("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'settings.%'")[0][0]


def test_batch_precheck_refuses_whole_batch_when_a_later_group_has_someone_elses_pending_json(client, make_user, zz_json_groups):
    """S1d 審查 S1：兩個群組、第二個（json）有別人還在等待的申請、未帶 supersede ⇒ 預檢整批 409 pending_exists，**0 筆寫入**
    （以前只比 CAS，前面的群組已寫、後面的才被 publish 擋＝部分套用）。帶 supersede 才放行。"""
    h = _hdr(client, make_user, "nt_pe1")
    make_user(username="nt_pe1_other", role="superadmin")
    R.publish("zz_nt_j1", {"doc": ["別人的申請"]}, user="nt_pe1_other", reason="別人先送")        # 進待生效（loosen both）
    n0, w0 = _writes()
    r = _batch(client, h, {"zz_nt_b": {"values": {"cap": 21}}, "zz_nt_j1": {"values": {"doc": ["我的"]}}}, reason="想一起存")
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "pending_exists", r.text
    assert [(x["group"], x["code"]) for x in d["groups"]] == [("zz_nt_j1", "pending_exists")] and d["groups"][0]["by"]
    assert d["applied"] == [] and d["failed"] is None and d["notApplied"] == ["zz_nt_b", "zz_nt_j1"]
    assert R.get("zz_nt_b", "cap") == 5 and _writes() == (n0, w0)                                # 前面的 zz_nt_b 也沒寫、帳本與設定稽核都沒多（409 的 fail.POST 失敗紀錄是中介層的，不算）
    ok = _batch(client, h, {"zz_nt_b": {"values": {"cap": 21}}, "zz_nt_j1": {"values": {"doc": ["我的"], }, "supersede": True}}, reason="確認取代")
    assert ok.status_code == 200 and R.get("zz_nt_b", "cap") == 21, ok.text


def test_batch_precheck_pending_exists_in_several_groups_uses_the_generic_sentence(client, make_user, zz_json_groups):
    """L1：多群組都是「別人還在等待」⇒ code 仍是 pending_exists，但訊息不能套「已被改動、請重新整理」那句。"""
    h = _hdr(client, make_user, "nt_pe2")
    make_user(username="nt_pe2_other", role="superadmin")
    for g in ("zz_nt_j1", "zz_nt_j2"):
        R.publish(g, {"doc": ["別人"]}, user="nt_pe2_other", reason="別人先送")
    r = _batch(client, h, {"zz_nt_j1": {"values": {"doc": ["我1"]}}, "zz_nt_j2": {"values": {"doc": ["我2"]}}}, reason="一起存")
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "pending_exists" and {x["group"] for x in d["groups"]} == {"zz_nt_j1", "zz_nt_j2"}, r.text
    assert "等待生效" in d["message"] and "重新整理" not in d["message"] and "已被別人改動" not in d["message"], d["message"]
    mine = R.publish("zz_nt_j1", {"doc": ["我1"]}, user="nt_pe2_other", reason="自己覆寫自己的不擋")      # 同一人的申請不算「別人」
    assert mine["superseded"] == 1
    assert _batch(client, h, {"zz_nt_j1": {"values": {"doc": ["x"]}}}, reason="預檢只看別人的").status_code == 409
