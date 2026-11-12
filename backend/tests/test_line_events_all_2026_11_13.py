# -*- coding: utf-8 -*-
"""LINE 全信件接線（2026-11-13；使用者裁示「寄信有的 LINE 都要，但我可以決定誰要發」；獎金、薪資、勞報單維持不開）。

釘住（PM 指定的四條，外加守門）：
① **LINE 有發**：每一支舊寫法 `notify_*`（AST 掃出來逐支跑，不手寫清單）都會推 LINE，且 `module_activity`／CRM 細項／LINE-only 事件各有題；
② **Email 完全不受影響**：同一支函式在「LINE 關／LINE 開」兩種狀態下，Email 的收件人、主旨、內文逐字相同；LINE 推播失敗也不影響 Email；
③ **最高管理者指定的人員有效**：`business`／`business_plus`／`only` 三種模式、指定角色、個人退訂照樣尊重、離職帳號濾掉、壞設定 fail-closed；
④ **獎金／薪資／勞報單永遠不在清單**（含日後新增、登記者是 payroll 的類型）；`system_test_mail`、`line_quota_warning` 技術性排除；
守門：每個已接線的事件都有 LINE 呼叫點（或在白名單寫理由）、沒有事件落在「其他」分組、critical 只有系統告警、額度 90% 保留。
＋「綁定狀況」與「提醒未綁定的人」（只有最高管理者；24 小時內同一人只提醒一次）。對外呼叫一律換掉（不連外）。"""
import ast
import inspect
import os
import re

import pytest

TOKEN = "tok-SECRET-0123456789"


def _uid(n):
    return "U" + ("%032x" % n)


# ── 夾具 ──────────────────────────────────────────────────────────────────────

def _mk(make_user, name, role, email=True, line=True, n=[0]):
    make_user(username=name, role=role)
    from db import get_db
    from helpers import line_notify
    if email:
        c = get_db()
        c.execute("UPDATE users SET email=? WHERE username=?", ("%s@example.com" % name, name))
        c.commit()
        c.close()
    if line:
        n[0] += 1
        line_notify.link_user(name, _uid(0x1000 + n[0]))


@pytest.fixture
def env(client, make_user, monkeypatch):
    """LINE 啟用、不勾選任何事件（各題自己勾）；攔下 LINE `push`（每次推給哪些 userId）與 Email 的所有寄送出口。五位使用者都有 Email＋LINE。"""
    from helpers import line_notify as L, email_notify as EN
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN})
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    for name, role in (("sa", "superadmin"), ("bob", "admin"), ("amy", "sales"), ("carol", "finance"), ("dan", "engineer")):
        _mk(make_user, name, role)
    from db import get_db
    c = get_db()                                                # 啟動時建立的展示帳號等不屬於這組五人：停用，題目才算得出確切人數
    c.execute("UPDATE users SET active=0 WHERE username NOT IN ('sa','bob','amy','carol','dan')")
    c.commit()
    c.close()
    out = {"line": [], "mail": [], "make_user": make_user, "line_fail": False,
           "uid": {n: L._links()[n]["userId"] for n in ("sa", "bob", "amy", "carol", "dan")}}

    def fake_push(ids, text):
        out["line"].append({"to": list(ids), "text": text})
        return L.SEND_TRANSIENT_FAIL if out["line_fail"] else L.SEND_SENT
    monkeypatch.setattr(L, "push", fake_push)
    monkeypatch.setattr("helpers.line_quota.after_push", lambda *a, **k: None)

    class _H:
        def wait(self, *a, **k):
            return "sent"

    def rec(to, subject, html, *a, **k):
        out["mail"].append((sorted(to), subject, html))
        return _H()

    def rec_sync(to, subject, html, *a, **k):
        out["mail"].append((sorted(to), subject, html))
        return EN.SEND_SENT
    monkeypatch.setattr(EN, "_async_send", rec)
    monkeypatch.setattr(EN, "_send", rec_sync)
    monkeypatch.setattr(EN, "_send_raising", rec_sync)
    monkeypatch.setattr(EN, "_send_with_attachments", lambda to, subject, html, att: rec_sync(to, subject, html))
    real_deliver = L.deliver_event
    monkeypatch.setattr(L, "notify_event", lambda ev, **kw: real_deliver(ev, **kw))        # 背景執行緒改同步
    return out


def _targets(env):
    names = {v: k for k, v in env["uid"].items()}
    return sorted(names[u] for p in env["line"] for u in p["to"])


# ── ④ 排除：獎金／薪資／勞報單永遠不在清單 ────────────────────────────────────────

def test_bonus_payslip_payroll_never_wired_even_for_future_types(env, monkeypatch):
    from helpers import line_notify as L, mail_types as mt, line_catalog as cat
    # 真實登記表：沒有任何獎金／薪資類型、也沒有 payroll 登記者的類型被接線
    for t in mt.all_types():
        if t.key.startswith(("bonus_", "payslip_")) or t.owner == "payroll":
            assert not L.is_wired(t.key) and t.key not in L.WIRED_EVENTS, t.key
            assert cat.exclusion_reason(t.key, t), t.key
    # 日後新增的 payroll 類型（假想一個、不照 bonus_/payslip_ 命名）預設也被擋
    reg = dict(mt._REGISTRY)
    reg["payroll_future_thing"] = mt.MailType("payroll_future_thing", "未來的薪資類型", "business", "admins", "", "", "", "payroll")
    monkeypatch.setattr(mt, "_REGISTRY", reg)
    assert "payroll_future_thing" not in L.wired_events() and not L.is_wired("payroll_future_thing")
    with pytest.raises(ValueError):
        L.set_event("payroll_future_thing", True)
    assert L.event_enabled("payroll_future_thing") is False
    assert L.deliver_event("payroll_future_thing", to_group=True, title="t") == "off" and env["line"] == []


@pytest.mark.parametrize("key", ["bonus_submitted", "bonus_payout_ready", "bonus_correction_submitted", "payslip_published",
                                 "system_test_mail", "line_quota_warning", "not_a_real_event"])
def test_excluded_keys_cannot_be_enabled_audienced_or_pushed(env, key):
    from helpers import line_notify as L, line_recipients as lr
    for fn in (lambda: L.set_event(key, True), lambda: L.set_event_roles(key, ["admin"]),
               lambda: L.set_audience(key, "only", [], ["amy"]), lambda: lr.set_muted("amy", key, True)):
        with pytest.raises(ValueError):
            fn()
    assert L.event_enabled(key) is False
    assert L.deliver_event(key, usernames=["amy"], title="t") == "off"
    assert env["line"] == []


def test_settings_page_and_personal_page_never_list_excluded(client, env):
    from helpers.auth import _hash_pw  # noqa: F401
    r = client.post("/api/auth/login", json={"username": "sa", "password": "Test-Pass-123"})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    g = client.get("/api/settings/line-notify", headers=hdr).json()
    keys = {e["key"] for e in g["events"]}
    assert len(keys) > 60 and not [k for k in keys if k.startswith(("bonus_", "payslip_"))]
    assert not {"system_test_mail", "line_quota_warning"} & keys
    assert {"approval_request", "dev_case_unassigned", "crm_case_status", "auth_lockout"} <= keys
    r = client.post("/api/auth/login", json={"username": "amy", "password": "Test-Pass-123"})
    amy = {"Authorization": "Bearer " + r.json()["token"]}
    from helpers import line_notify as L
    for k in ("approval_request", "bonus_submitted"):
        if L.is_wired(k):
            L.set_event(k, True)
    assert [e["key"] for e in client.get("/api/line/prefs", headers=amy).json()["events"]] == ["approval_request"]
    assert client.put("/api/line/prefs/bonus_submitted", json={"enabled": False}, headers=amy).status_code == 404


# ── 分組與優先級 ─────────────────────────────────────────────────────────────

def test_every_wired_event_has_a_group_and_a_valid_priority(env):
    from helpers import line_notify as L, line_catalog as cat
    other = [k for k in L.WIRED_EVENTS if cat.group_of(k) == "其他"]
    assert not other, "這些事件沒有分組（到 helpers/line_catalog.py 的 _GROUP_RULES 補規則）：%s" % other
    assert set(cat.group_of(k) for k in L.WIRED_EVENTS) <= set(cat.GROUP_ORDER)
    groups = [cat.group_of(k) for k in L.WIRED_EVENTS]
    assert groups == sorted(groups, key=cat.GROUP_ORDER.index), "清單依分組順序排（簽核優先）"
    assert cat.GROUP_ORDER.index("報價單與簽核") < cat.GROUP_ORDER.index("業務開發") < cat.GROUP_ORDER.index("系統告警")
    for k in L.WIRED_EVENTS:
        assert L.event_spec(k)["priority"] in ("critical", "normal"), k


def test_priority_critical_only_for_system_alerts_approvals_and_assignees_are_normal(env):
    from helpers import line_notify as L
    crit = {k for k in L.WIRED_EVENTS if L.event_spec(k)["priority"] == "critical"}
    assert crit == {"backup_error", "backup_stale", "heartbeat_stale", "disk_space_low", "cert_expiry", "company_setup_alert", "auth_lockout"}
    for k in ("approval_request", "next_tier", "approved", "returned", "approval_reminder", "shipping_submitted", "dev_case_assigned",
              "dev_case_unassigned", "daily_task_assigned", "crm_case_status", "module_activity"):
        assert L.event_spec(k)["priority"] == "normal", k


def test_line_only_and_sub_events_are_wired_with_labels(env):
    from helpers import line_notify as L, line_catalog as cat
    for k in ("dev_case_unassigned", "dev_case_deadline_changed", "dev_log_directive_reply", "dispatch_file_delete_request"):
        assert L.is_wired(k) and cat.kind_of(k) == "line_only", k
    for k in ("crm_case_created", "crm_case_status", "crm_case_progress", "crm_visit_logged", "crm_log_approved", "crm_case_converted"):
        assert L.is_wired(k) and cat.kind_of(k) == "sub", k
    assert cat.kind_of("approval_request") == "mail"


# ── 守門：每個已接線事件都有 LINE 呼叫點 ───────────────────────────────────────

#: 沒有字面呼叫點的事件 ⇒ 理由（空＝不允許）
_NO_CALL_SITE_OK = {}


def test_every_wired_event_has_a_line_call_site(env):
    from helpers import line_notify as L
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = []
    for root, dirs, files in os.walk(here):
        dirs[:] = [d for d in dirs if d not in ("tests", ".venv", "node_modules", "__pycache__", ".git") and not d.startswith(".")]
        for f in files:
            if f.endswith(".py"):
                src.append(open(os.path.join(root, f), encoding="utf-8", errors="ignore").read())
    src = "\n".join(src)
    pat = re.compile(r'(?:_line_event|send_registered|deliver_event|notify_event|notify_users)\(\s*["\']([a-z_0-9]+)["\']'
                     r'|line_event\s*=\s*["\']([a-z_0-9]+)["\']|["\']([a-z_0-9]+)["\']\s*,\s*title=')
    have = {g for m in pat.findall(src) for g in m if g}
    missing = [k for k in L.WIRED_EVENTS if k not in have and k not in _NO_CALL_SITE_OK]
    assert not missing, "這些已登記的信件類型沒有 LINE 呼叫點（用 send_registered／_line_event，或在 _NO_CALL_SITE_OK 寫理由）：%s" % missing


# ── ①②：每一支舊寫法 notify_* 都推 LINE，Email 逐字不變 ───────────────────────────

def _legacy_functions():
    from helpers import email_notify as EN
    src = inspect.getsource(EN)
    out = []
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef) and n.name.startswith("notify_"):
            seg = ast.get_source_segment(src, n)
            m = re.search(r'_line_event\(\s*"([a-z_0-9]+)"', seg)
            if m:
                out.append((n.name, m.group(1)))
    return out


_LEGACY = _legacy_functions()

#: 這幾支的 LINE 收件人不是呼叫端清單，而是登記群組或另一個來源——測試夾具要先備好
_ARG_OVERRIDES = {
    "problems": [{"path": "C:\\", "free_gb": 1.0, "total_gb": 100.0, "pct_free": 1.0, "mount": "C:\\"}],
    "stale": [{"label": "x", "hours": 30}],
    "state": {},
    "changes": [{"label": "標題", "old": "a", "new": "b"}],
    "reasons": ["尚有未收款項"],
    "tenders": [],
}


def _norm_mails(mails) -> list:
    """信件內文有「寄出時間（到分鐘）」；兩次寄送剛好跨分鐘就會不同（偶發）。比對前把 `YYYY-MM-DD HH:MM` 時間戳換成固定字樣。"""
    import re as _re
    ts = _re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
    out = []
    for m in mails:
        out.append(tuple(ts.sub("<TS>", x) if isinstance(x, str) else x for x in m))
    return out


def _auto_args(fn, dept_id):
    args = {}
    for name, p in inspect.signature(fn).parameters.items():
        ann = p.annotation
        if name in _ARG_OVERRIDES:
            args[name] = _ARG_OVERRIDES[name]
        elif name == "department_id":
            args[name] = dept_id
        elif name in ("supervisor_usernames",):
            continue                                            # 預設 None：走「沒有主管 ⇒ 管理員群組」那條路
        elif name.endswith("usernames") or name == "usernames":
            args[name] = ["amy"]
        elif name.endswith("username") or name in ("sales_person",):
            args[name] = "amy"
        elif p.default is not inspect._empty:
            continue
        elif ann is bool or name.startswith("is_") or name.startswith("also_"):
            args[name] = False
        elif ann is int or name.endswith("_id") or name in ("days_left", "days_overdue", "tier_no", "total_tiers", "version", "days_since_update", "days_elapsed", "threshold_hours"):
            args[name] = 3 if name != "total_tiers" else 5
        elif ann is float:
            args[name] = 1.0
        elif ann is bytes or name.endswith("_bytes"):
            args[name] = b"x"
        elif ann is list:
            args[name] = ["x"]
        else:
            args[name] = "值-%s" % name
    return args


@pytest.fixture
def dept(env):
    from db import get_db
    c = get_db()
    try:
        c.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES ('測試處', 1, '2026-01-01')")
        did = c.execute("SELECT id FROM divisions WHERE name='測試處'").fetchone()["id"]
        uid = c.execute("SELECT id FROM users WHERE username='carol'").fetchone()["id"]
        c.execute("INSERT INTO departments (division_id, name, manager_user_id, created_at) VALUES (?,?,?,'2026-01-01')", (did, "測試部", uid))
        c.commit()
        return c.execute("SELECT id FROM departments WHERE name='測試部'").fetchone()["id"]
    finally:
        c.close()


def test_legacy_function_inventory_is_complete():
    """每支寄信的 `notify_*`（獎金類與 line_quota_warning 除外）都有 `_line_event` 呼叫；漏掉一支這題就紅。"""
    from helpers import email_notify as EN
    src = inspect.getsource(EN)
    funcs = [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name.startswith("notify_")]
    sends = ("_async_send(", "_send(", "_send_raising(", "_send_with_attachments(", "threading.Thread(")
    skip = ("notify_bonus_", "notify_line_quota_warning")
    lacking = [n.name for n in funcs if not n.name.startswith(skip)
               and any(s in ast.get_source_segment(src, n) for s in sends)
               and "_line_event(" not in ast.get_source_segment(src, n) and "send_registered(" not in ast.get_source_segment(src, n)
               and "_send_warranty_expiry" not in ast.get_source_segment(src, n)]
    assert not lacking, "這些舊寫法寄信函式還沒有 LINE 通道：%s" % lacking
    assert len(_LEGACY) >= 50, len(_LEGACY)


@pytest.mark.parametrize("func,event", _LEGACY, ids=[e for _f, e in _LEGACY])
def test_legacy_notify_pushes_line_and_leaves_email_byte_identical(env, dept, func, event):
    from helpers import email_notify as EN, line_notify as L
    fn = getattr(EN, func)
    args = _auto_args(fn, dept)

    def run():
        env["mail"].clear()
        env["line"].clear()
        try:
            fn(**args)
        except Exception as exc:                                # 夾具造不出完整信件資料的函式：兩種狀態必須「一樣地」丟
            return "raised:%s" % type(exc).__name__
        return "ok"

    base_state = run()                                          # LINE 關（事件沒勾選）：Email 基準
    base_mail, base_line = _norm_mails(env["mail"]), list(env["line"])
    assert base_line == [], "事件沒勾選時 LINE 不可以推"
    L.set_event(event, True)
    on_state = run()
    assert on_state == base_state, "LINE 開關不可以改變 Email 路徑的結果（例外型別／是否寄出）"
    assert _norm_mails(env["mail"]) == base_mail, "Email 的收件人、主旨、內文在 LINE 開／關兩種狀態必須逐字相同"
    assert env["line"], "%s 應該推 LINE（%s）" % (func, event)
    # LINE 失敗不影響 Email
    env["line_fail"] = True
    assert run() == base_state and _norm_mails(env["mail"]) == base_mail
    env["line_fail"] = False


def test_legacy_line_is_independent_of_email_recipients_and_mail_off(env):
    """沒有 Email 的人、信件被矩陣關閉：LINE 照發（獨立通道）；個人信件退訂不影響 LINE。"""
    from helpers import email_notify as EN, line_notify as L
    from db import get_db
    c = get_db()
    c.execute("UPDATE users SET email=NULL WHERE username='amy'")
    c.commit()
    c.close()
    L.set_event("shipping_approved", True)
    EN.notify_shipping_approved("S-1", "客戶", "bob", "amy")
    assert env["mail"] == [] and _targets(env) == ["amy"]


def test_legacy_line_content_has_no_amounts_or_free_text(env):
    from helpers import email_notify as EN, line_notify as L
    L.set_event("returned", True)
    L.set_event("daily_task_completed", True)
    EN.notify_returned("MQ-1", "MQ-1-R1", "客戶甲", "備註：金額 NT$ 123,456 要改", "amy")
    EN.notify_daily_task_completed(1, "標題", "2026-11-13", "amy", "艾咪", "報告內容 NT$ 99,999 機密", ["bob"])
    text = " ".join(p["text"] for p in env["line"])
    assert "123,456" not in text and "99,999" not in text and "機密" not in text and "備註" not in text


# ── 預設收件人與「approved 只給申請人」 ────────────────────────────────────────

def test_approved_goes_only_to_requester_by_default(env):
    """PM 裁示：「審核完成」LINE 預設只給申請人（信件仍照舊給申請人＋管理員群組）。"""
    from helpers import email_notify as EN, line_notify as L
    L.set_event("approved", True)
    EN.notify_approved("MQ-1", "客戶", "bob", "amy")
    assert _targets(env) == ["amy"]
    assert any("sa@example.com" in m[0] or "bob@example.com" in m[0] for m in env["mail"]), "信件仍給管理員群組"


def test_approval_request_goes_to_approvers_only(env):
    from helpers import email_notify as EN, line_notify as L
    L.set_event("approval_request", True)
    EN.notify_approval_request("MQ-1", "客戶", ["carol", "dan"])
    assert _targets(env) == ["carol", "dan"]


# ── ③ 最高管理者指定的人：三種模式 ─────────────────────────────────────────────

def _fire_shipping(EN):
    EN.notify_shipping_submitted("S-1", "客戶", ["amy"])             # 事件收件人（業務收件人）＝amy


def test_audience_business_is_default_and_only_the_business_recipients(env):
    from helpers import email_notify as EN, line_notify as L
    L.set_event("shipping_submitted", True)
    _fire_shipping(EN)
    assert _targets(env) == ["amy"]


def test_audience_business_plus_adds_picked_roles_and_people(env):
    from helpers import email_notify as EN, line_notify as L
    L.set_event("shipping_submitted", True)
    L.set_audience("shipping_submitted", "business_plus", ["finance"], ["dan"])
    _fire_shipping(EN)
    assert _targets(env) == ["amy", "carol", "dan"], "業務收件人 amy ＋ 指定角色 finance(carol) ＋ 指定人員 dan"


def test_audience_only_sends_just_to_the_picked(env):
    from helpers import email_notify as EN, line_notify as L
    L.set_event("shipping_submitted", True)
    L.set_audience("shipping_submitted", "only", [], ["dan", "sa"])
    _fire_shipping(EN)
    assert _targets(env) == ["dan", "sa"], "只發給指定的人；業務收件人 amy 不收"
    env["line"].clear()
    L.set_audience("shipping_submitted", "only", ["admin"], [])
    _fire_shipping(EN)
    assert _targets(env) == ["bob"]


def test_picked_individual_who_is_not_a_business_recipient_still_receives_without_email_change(env):
    """指定個人跟 Email 無關：dan 不是信件收件人，LINE 收得到，Email 收件人不變。"""
    from helpers import email_notify as EN, line_notify as L
    L.set_event("shipping_submitted", True)
    L.set_event("shipping_submitted", False)
    _fire_shipping(EN)
    mail_off = list(env["mail"])
    env["mail"].clear()
    L.set_event("shipping_submitted", True)
    L.set_audience("shipping_submitted", "business_plus", [], ["dan"])
    _fire_shipping(EN)
    assert _targets(env) == ["amy", "dan"] and env["mail"] == mail_off and all("dan@example.com" not in m[0] for m in env["mail"])


def test_personal_mute_is_respected_even_for_picked_people(env):
    from helpers import email_notify as EN, line_notify as L, line_recipients as lr
    L.set_event("shipping_submitted", True)
    L.set_audience("shipping_submitted", "business_plus", [], ["dan", "carol"])
    lr.set_muted("dan", "shipping_submitted", True)
    _fire_shipping(EN)
    assert _targets(env) == ["amy", "carol"]


def test_inactive_and_unlinked_picked_people_are_dropped(env):
    from helpers import email_notify as EN, line_notify as L
    from db import get_db
    L.set_event("shipping_submitted", True)
    L.set_audience("shipping_submitted", "only", [], ["dan", "carol", "bob"])
    c = get_db()
    c.execute("UPDATE users SET active=0 WHERE username='dan'")
    c.commit()
    c.close()
    L.unlink_user("carol")
    _fire_shipping(EN)
    assert _targets(env) == ["bob"], "dan 離職、carol 沒綁定"


def test_explicit_picks_are_not_filtered_by_role_allowlist_but_business_recipients_are(env):
    from helpers import email_notify as EN, line_notify as L
    L.set_event("shipping_submitted", True)
    L.set_event_roles("shipping_submitted", ["admin"])             # 業務收件人 amy(sales) 被角色清單擋下
    L.set_audience("shipping_submitted", "business_plus", [], ["dan"])
    _fire_shipping(EN)
    assert _targets(env) == ["dan"], "角色清單只縮業務收件人；管理員明確指定的人不被它擋"


def test_actor_exclusion_applies_only_to_business_recipients(env):
    from helpers import line_notify as L
    L.set_event("module_activity", True)
    L.set_audience("module_activity", "business_plus", [], ["amy"])
    L.deliver_event("module_activity", usernames=["amy", "dan"], title="t", exclude=["amy", "dan"])
    assert _targets(env) == ["amy"], "操作者 dan 被排除；管理員指定的 amy 就算是操作者也收得到"


def test_bad_audience_config_fails_closed_and_never_raises(env, caplog):
    from helpers import line_notify as L
    from helpers.settings import _get_setting, _set_setting
    L.set_event("shipping_submitted", True)
    for bad in ("only", {"mode": "weird"}, {"mode": "only", "users": "dan"}, {"mode": "only", "roles": ["ceo"]}, 7):
        c = _get_setting("line_notify", {})
        c["audiences"] = {"shipping_submitted": bad}
        _set_setting("line_notify", c)
        env["line"].clear()
        assert L.deliver_event("shipping_submitted", usernames=["amy"], title="t") in ("no_recipient",), bad
        assert env["line"] == [], bad


@pytest.mark.parametrize("args", [("weird", [], []), ("only", ["ceo"], []), ("only", [], ["ghost"]), ("only", "admin", []), ("only", [], "dan"),
                                  ("business_plus", [], ["x"] * 201)])
def test_set_audience_validates(env, args):
    from helpers import line_notify as L
    with pytest.raises(ValueError):
        L.set_audience("shipping_submitted", *args)


def test_set_audience_business_removes_entry_and_unchanged_does_not_write(env, monkeypatch):
    from helpers import line_notify as L
    from helpers.settings import _get_setting
    L.set_audience("shipping_submitted", "only", ["admin"], ["dan"])
    assert "shipping_submitted" in (_get_setting("line_notify", {}).get("audiences") or {})
    L.set_audience("shipping_submitted", "business", [], [])
    assert "shipping_submitted" not in (_get_setting("line_notify", {}).get("audiences") or {})
    writes = []
    real = L._set_setting
    monkeypatch.setattr(L, "_set_setting", lambda k, v: (writes.append(k), real(k, v))[1])
    L.set_audience("shipping_submitted", "business", [], [])
    assert writes == []


def test_line_only_event_borrows_recipient_settings_of_its_mail_type(env):
    """`dev_case_unassigned` 沒有自己的信件類型，收件人設定借用 `dev_case_assigned`（超管在「信件與通知收件設定」的覆寫也套用）。"""
    from helpers import line_notify as L, line_catalog as cat
    assert cat.mail_key_of("dev_case_unassigned") == "dev_case_assigned" and cat.mail_key_of("dispatch_file_delete_request") == "dispatch_submitted"
    L.set_event("dev_case_unassigned", True)
    assert L.deliver_event("dev_case_unassigned", usernames=["amy"], title="t") == L.SEND_SENT
    assert _targets(env) == ["amy"] and L.event_spec("dev_case_unassigned")["line_group"] is None


# ── 優先級：額度 90% 保留 ─────────────────────────────────────────────────────

def test_quota_reserve_pauses_normal_but_not_critical(env):
    from helpers import line_notify as L, line_quota
    from helpers.settings import _set_setting
    L.set_event("shipping_submitted", True)
    L.set_event("backup_error", True)
    _set_setting(line_quota.STATE_KEY, {"month": line_quota.month_key(), "used": 95, "limit": 100})
    assert L.deliver_event("shipping_submitted", usernames=["amy"], title="t") == "paused_quota"
    assert L.deliver_event("backup_error", to_group=True, title="t") == L.SEND_SENT, "critical（系統告警）照發"
    _set_setting(line_quota.STATE_KEY, {"month": line_quota.month_key(), "used": 50, "limit": 100})
    assert L.deliver_event("shipping_submitted", usernames=["amy"], title="t") == L.SEND_SENT


# ── module_activity：泛用與 CRM 細項 ──────────────────────────────────────────

def test_module_activity_generic_goes_to_group_and_finance_audience_to_finance(env):
    from helpers import email_notify as EN, line_notify as L
    L.set_event("module_activity", True)
    EN.notify_module_activity("報價單", "申請沖銷", "某人", "MQ-1", "quotations.html", audience="finance", detail="自由文字金額 NT$ 5,000")
    assert _targets(env) == ["carol", "sa"], "財務類只發財務角色＋超管"
    assert "5,000" not in env["line"][0]["text"] and "自由文字" not in env["line"][0]["text"], "LINE 不放 detail"
    env["line"].clear()
    EN.notify_module_activity("業務開發", "新增案件", "某人", "案件甲", "dev-crm.html")
    assert _targets(env) == ["bob", "sa"], "一般＝管理員群組（admin＋superadmin）"


def test_module_activity_with_line_event_goes_to_case_people_only_and_email_unchanged(env):
    from helpers import email_notify as EN, line_notify as L
    EN.notify_module_activity("業務開發", "狀態變更", "某人", "案件甲", "dev-crm.html")
    base_mail = _norm_mails(env["mail"])
    env["mail"].clear()
    L.set_event("crm_case_status", True)
    L.set_event("module_activity", True)
    EN.notify_module_activity("業務開發", "狀態變更", "某人", "案件甲", "dev-crm.html",
                              line_event="crm_case_status", line_usernames=["amy", "dan"], line_exclude=["dan"])
    assert _norm_mails(env["mail"]) == base_mail
    assert _targets(env) == ["amy"], "細項事件只發案件相關人（排除操作者）；泛用的 module_activity 不重複推"
    env["line"].clear()
    EN.notify_module_activity("業務開發", "指派案件", "某人", "案件甲", "dev-crm.html", line_skip=True)
    assert env["line"] == [], "line_skip：已由專屬事件負責，不再推泛用那一則"


def test_crm_defaults_are_all_off(env):
    """PM 裁示：拜訪／進度與其餘 CRM 更新預設都關（勾選才發）。"""
    from helpers import line_notify as L
    sw = L.events_view()
    for k in ("crm_case_created", "crm_case_status", "crm_case_progress", "crm_visit_logged", "crm_log_approved", "crm_case_converted", "module_activity"):
        assert sw[k] is False, k


# ── 設定頁端點 ───────────────────────────────────────────────────────────────

def _hdr(client, name):
    r = client.post("/api/auth/login", json={"username": name, "password": "Test-Pass-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_audience_endpoint_superadmin_only_validates_and_roundtrips(client, env):
    sa, ad = _hdr(client, "sa"), _hdr(client, "bob")
    url = "/api/settings/line-notify/events/shipping_submitted/audience"
    body = {"mode": "business_plus", "roles": ["finance"], "users": ["dan"]}
    assert client.put(url, json=body, headers=ad).status_code == 403
    assert client.put(url, json={"mode": "weird"}, headers=sa).status_code == 400
    assert client.put(url, json={}, headers=sa).status_code == 400
    assert client.put(url, json={"mode": "only", "users": ["ghost"]}, headers=sa).status_code == 400
    assert client.put("/api/settings/line-notify/events/bonus_submitted/audience", json=body, headers=sa).status_code == 404
    assert client.put(url, json=body, headers=sa).status_code == 200
    ev = {e["key"]: e for e in client.get("/api/settings/line-notify", headers=sa).json()["events"]}["shipping_submitted"]
    assert ev["audience"]["mode"] == "business_plus" and ev["audience"]["roles"] == ["finance"]
    assert ev["audience"]["users"] == [{"username": "dan", "display": "dan", "active": True, "linked": True, "muted": False}]
    assert ev["group"] == "出貨單" and ev["priority"] == "normal" and ev["kind"] == "mail"
    from db import get_db
    c = get_db()
    try:
        assert c.execute("SELECT COUNT(*) n FROM audit_log WHERE action='settings.line_notify.audience'").fetchone()["n"] == 1
    finally:
        c.close()


# ── 綁定狀況與提醒 ───────────────────────────────────────────────────────────

@pytest.fixture
def login_ready(env, monkeypatch):
    from helpers import line_notify as L
    monkeypatch.setattr(L, "login_credentials", lambda: ("cid", "sec"))
    monkeypatch.setattr(L, "callback_url", lambda: "https://example.com/api/line/callback")


def test_binding_status_lists_active_people_with_linked_flag_and_no_user_id(client, env, login_ready):
    from db import get_db
    from helpers import line_notify as L
    L.unlink_user("dan")
    c = get_db()
    c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password) "
              "VALUES ('gone','x','離職者','sales','[]',0,'2026-01-01',0)")
    c.commit()
    c.close()
    sa = _hdr(client, "sa")
    r = client.get("/api/settings/line-notify/bindings", headers=sa)
    assert r.status_code == 200
    j = r.json()
    users = {u["username"]: u for u in j["users"]}
    assert "gone" not in users, "只列在職人員"
    assert j["total"] == 5 and j["linked"] == 4 and j["unlinked"] == 1 and j["available"] is True
    assert users["dan"]["linked"] is False and users["amy"]["linked"] is True and users["amy"]["hasEmail"] is True
    assert "userId" not in r.text and "@example.com" not in r.text, "不回 LINE userId、不回 Email 內容"
    assert client.get("/api/settings/line-notify/bindings", headers=_hdr(client, "bob")).status_code == 403
    assert client.get("/api/settings/line-notify/bindings").status_code in (401, 403)


def test_remind_notifies_unlinked_by_email_and_in_app_with_link_and_throttles(client, env, login_ready):
    from db import get_db
    from helpers import line_notify as L
    L.unlink_user("dan")
    L.unlink_user("carol")
    sa = _hdr(client, "sa")
    r = client.post("/api/settings/line-notify/bindings/remind", json={}, headers=sa)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["targets"] == 2 and j["notified"] == 2 and j["emailed"] == 2 and j["skippedRecent"] == []
    mails = {m[0][0]: m for m in env["mail"]}
    assert set(mails) == {"dan@example.com", "carol@example.com"}, "只寄給未綁定的人"
    assert "my-account.html?tab=notify" in mails["dan@example.com"][2] and "LINE" in mails["dan@example.com"][2]
    c = get_db()
    try:
        rows = c.execute("SELECT username, link FROM notifications WHERE type='line_binding_reminder' ORDER BY username").fetchall()
        assert [(r_["username"], r_["link"]) for r_ in rows] == [("carol", "my-account.html?tab=notify"), ("dan", "my-account.html?tab=notify")]
        assert c.execute("SELECT COUNT(*) n FROM audit_log WHERE action='line.binding.remind'").fetchone()["n"] == 1
    finally:
        c.close()
    # 24 小時內同一人只提醒一次
    env["mail"].clear()
    j2 = client.post("/api/settings/line-notify/bindings/remind", json={}, headers=sa).json()
    assert j2["notified"] == 0 and sorted(j2["skippedRecent"]) == ["carol", "dan"] and env["mail"] == []
    # 指定名單：已綁定的人不會被提醒（忽略）
    j3 = client.post("/api/settings/line-notify/bindings/remind", json={"usernames": ["amy", "ghost"]}, headers=sa).json()
    assert j3["targets"] == 0 and sorted(j3["ignored"]) == ["amy", "ghost"] and env["mail"] == []


def test_remind_reports_people_without_email_and_respects_mail_off(client, env, login_ready, monkeypatch):
    from db import get_db
    from helpers import line_notify as L, email_notify as EN
    L.unlink_user("dan")
    L.unlink_user("carol")
    c = get_db()
    c.execute("UPDATE users SET email=NULL WHERE username='dan'")
    c.commit()
    c.close()
    sa = _hdr(client, "sa")
    j = client.post("/api/settings/line-notify/bindings/remind", json={}, headers=sa).json()
    assert j["notified"] == 2 and j["emailed"] == 1 and j["noEmail"] == 1, "沒有 Email 的只發站內通知，如實回報"
    # 公司關閉了「使用者額外通知」信件 ⇒ 只發站內通知
    from helpers import line_binding as lb
    monkeypatch.setattr(lb, "REMIND_MIN_HOURS", 0)
    env["mail"].clear()
    monkeypatch.setattr(EN, "_mail_off", lambda k: True)
    j = client.post("/api/settings/line-notify/bindings/remind", json={}, headers=sa).json()
    assert j["emailOff"] is True and j["emailed"] == 0 and j["notified"] == 2 and env["mail"] == []


def test_remind_requires_superadmin_and_ready_login(client, env, monkeypatch):
    from helpers import line_notify as L
    L.unlink_user("dan")
    assert client.post("/api/settings/line-notify/bindings/remind", json={}, headers=_hdr(client, "bob")).status_code == 403
    monkeypatch.setattr(L, "login_credentials", lambda: ("", ""))
    r = client.post("/api/settings/line-notify/bindings/remind", json={}, headers=_hdr(client, "sa"))
    assert r.status_code == 400 and "LINE" in r.json()["detail"]
    monkeypatch.setattr(L, "login_credentials", lambda: ("cid", "sec"))
    monkeypatch.setattr(L, "callback_url", lambda: "https://x/api/line/callback")
    assert client.post("/api/settings/line-notify/bindings/remind", json={"usernames": "dan"}, headers=_hdr(client, "sa")).status_code == 400


# ── 業務開發（CRM）端到端：指定人員／細項／LINE-only 事件 ─────────────────────────────

def test_crm_assignment_flow_sends_assignee_events_and_leaves_email_alone(client, env, monkeypatch):
    """指派（dev_case_assigned）→ 換人（前任 dev_case_unassigned）→ 只改期限（dev_case_deadline_changed）→ 狀態變更（細項 crm_case_status）。
    LINE-only 事件不增加任何 Email；泛用的 module_activity 不重複推。"""
    from helpers import line_notify as L
    from modules.crm import api as crm
    from db import get_db
    monkeypatch.setattr(crm, "spawn_bg_thread", lambda t, args=(), kwargs=None, **k: t(*args, **(kwargs or {})))
    for k in ("dev_case_assigned", "dev_case_unassigned", "dev_case_deadline_changed", "crm_case_created", "crm_case_status", "module_activity"):
        L.set_event(k, True)
    c = get_db()
    c.execute("UPDATE users SET modules=? WHERE username IN ('amy','dan')", ('["dev_crm"]',))
    c.commit()
    ids = {r["username"]: r["id"] for r in c.execute("SELECT id, username FROM users").fetchall()}
    c.close()
    bob = _hdr(client, "bob")

    r = client.post("/api/dev-cases", json={"case_name": "案件甲", "customer_name": "客戶", "sales_persons": [ids["amy"]], "planners": []}, headers=bob)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert _targets(env) == ["amy"], "新增案件：只發案件相關人（業務 amy）；操作者 bob 與泛用 module_activity 都不推"
    mail_after_create = list(env["mail"])
    assert mail_after_create, "Email 照舊（管理員群組）"

    env["line"].clear()
    r = client.patch("/api/dev-cases/%d/assign" % cid, json={"assignedTo": ids["amy"], "replyDeadline": "2099-12-31"}, headers=bob)
    assert r.status_code == 200, r.text
    assert _targets(env) == ["amy"] and "案件甲" in env["line"][0]["text"], "指派：被指派人收到 dev_case_assigned（只一則；module_activity 被 line_skip）"

    env["line"].clear()
    r = client.patch("/api/dev-cases/%d/assign" % cid, json={"assignedTo": ids["dan"], "replyDeadline": "2099-12-31"}, headers=bob)
    assert r.status_code == 200, r.text
    texts = {u: p["text"] for p in env["line"] for u in p["to"]}
    assert set(texts) == {env["uid"]["amy"], env["uid"]["dan"]}
    assert "不由您負責" in texts[env["uid"]["amy"]] and "不由您負責" not in texts[env["uid"]["dan"]], "前任收到 unassigned、新任收到 assigned"

    env["line"].clear()
    mail_before = len(env["mail"])
    r = client.patch("/api/dev-cases/%d/assign" % cid, json={"assignedTo": ids["dan"], "replyDeadline": "2099-12-30"}, headers=bob)
    assert r.status_code == 200, r.text
    assert _targets(env) == ["dan"] and "回覆期限已調整" in env["line"][0]["text"]
    assert len(env["mail"]) > mail_before, "module_activity 的 Email 照舊會寄（LINE-only 事件不新增、也不取消 Email）"

    env["line"].clear()
    r = client.patch("/api/dev-cases/%d/status" % cid, json={"status": "成案"}, headers=bob)
    assert r.status_code == 200, r.text
    assert _targets(env) == ["amy", "dan"], "狀態變更（細項 crm_case_status）：案件相關人＝業務 amy＋被指派人 dan（建立者 bob 是操作者，排除）"


# ── 個人頁：分組、被指定的人看得到（即使角色不在允許清單）─────────────────────────

def test_personal_prefs_are_grouped_and_include_events_where_i_was_picked(client, env):
    from helpers import line_notify as L, line_recipients as lr
    for k in ("approval_request", "dev_case_unassigned", "shipping_submitted"):
        L.set_event(k, True)
    L.set_event_roles("shipping_submitted", ["admin"])                 # dan(engineer) 角色不在允許清單 → 本來看不到
    v = lr.prefs_view("dan", "engineer")
    assert [e["key"] for e in v] == ["approval_request", "dev_case_unassigned"]
    assert [e["group"] for e in v] == ["報價單與簽核", "業務開發"] and v[1]["kind"] == "line_only"
    L.set_audience("shipping_submitted", "business_plus", [], ["dan"])    # 管理員指定了 dan：他要能在自己的頁面看到並關掉
    assert [e["key"] for e in lr.prefs_view("dan", "engineer")] == ["approval_request", "shipping_submitted", "dev_case_unassigned"]
    lr.set_muted("dan", "shipping_submitted", True, role="engineer")
    assert [e["enabled"] for e in lr.prefs_view("dan", "engineer")] == [True, False, True]


# ══════════════════════════════════════════════════════════════════════════════
# 審查 h8（2026-11-13）：H1 勞報單不可經泛用 module_activity 推到 LINE；外包名冊／承攬商往來紀錄 LINE 不放姓名
# ══════════════════════════════════════════════════════════════════════════════

def test_h1_payslip_module_activity_never_reaches_line_even_when_generic_event_is_on(env):
    """hichan-8 的重現：最高管理者把 module_activity 勾起來，勞報單的建立／刪除／調閱／作廢不可以有任何一則 LINE（含受款人姓名）。"""
    from helpers import line_notify as L, email_notify as EN
    L.set_event("module_activity", True)
    EN.notify_module_activity("勞報單", "建立", "某人", "PS-001（王小明）", "payslips.html")                  # 沒帶 line_skip：模組名稱字樣那一道也要擋
    EN.notify_module_activity("勞報單", "作廢", "某人", "PS-001", "payslips.html", line_skip=True)
    for label in ("獎金分潤", "薪資單", "勞報單（外包）", "Payslip"):
        EN.notify_module_activity(label, "建立", "某人", "X-1（李小華）", "x.html")
    assert env["line"] == [], "勞報單／獎金／薪資類的模組動態不可以推 LINE"
    assert env["mail"], "Email 不受影響（仍照舊寄給管理員）"


def _payroll_call_sites():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modules", "payroll")
    out = []
    for d, _dirs, files in os.walk(root):
        if os.sep + "tests" in d or "__pycache__" in d:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(d, f)
            tree = ast.parse(open(p, encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                    if name == "notify_module_activity":
                        out.append((os.path.relpath(p, root), node.lineno, node))
    return out


def test_h1_every_payroll_module_activity_call_site_passes_line_skip():
    """掃描 modules/payroll 全部 notify_module_activity 呼叫點：一律帶 line_skip=True（日後新增的呼叫點忘了帶就會紅）。"""
    sites = _payroll_call_sites()
    assert sites, "掃不到任何呼叫點——掃描器壞了（勞報單頁面至少有 4 個）"
    bad = []
    for rel, ln, node in sites:
        kw = {k.arg: k.value for k in node.keywords}
        v = kw.get("line_skip")
        if not (isinstance(v, ast.Constant) and v.value is True):
            bad.append("%s:%d" % (rel, ln))
    assert not bad, "payroll 的 notify_module_activity 必須 line_skip=True：" + ", ".join(bad)


def test_contractor_roster_and_vendor_contact_line_has_no_names_but_email_unchanged(env):
    from helpers import line_notify as L, email_notify as EN
    L.set_event("module_activity", True)
    EN.notify_module_activity("外包名冊", "建立", "某人", "張三（泥作）", "contractors.html", detail="身分證 A123456789")
    EN.notify_module_activity("外包名冊", "匯入", "某人", "共 3 筆：張三、李四、王五", "contractors.html")
    EN.notify_module_activity("外包名冊", "停用", "某人", "李四", "contractors.html")
    EN.notify_module_activity("承攬商管理", "新增往來紀錄", "某人", "大成工程｜林經理來電", "vendor-contractors.html")
    assert len(env["line"]) == 4
    for p in env["line"]:
        for secret in ("張三", "李四", "王五", "A123456789", "大成", "林經理", "某人"):
            assert secret not in p["text"], (secret, p["text"])
    assert "外包名冊有一筆新增／異動" in env["line"][0]["text"] and "承攬商往來紀錄有一筆新增" in env["line"][3]["text"]
    assert any("張三" in m[2] for m in env["mail"]) and any("大成工程" in m[2] for m in env["mail"]), "Email 維持原樣（照舊含姓名）"
    # 其他模組不受影響：項目名稱照舊
    env["line"].clear()
    EN.notify_module_activity("客戶管理", "建立", "某人", "甲公司", "customers.html")
    assert "甲公司" in env["line"][0]["text"]
