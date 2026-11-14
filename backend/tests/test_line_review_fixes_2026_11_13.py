"""審查 h8 對 `feat/line-events-all` 的修正（M1／M2／M3／L2～L7）的守門測試。

夾具沿用 `test_line_events_all_2026_11_13`（LINE 啟用、五位使用者、攔截 LINE push 與 Email 寄送）。
"""
import ast
import inspect
import os

import pytest

from core import source_tree

from tests.test_line_events_all_2026_11_13 import _grant_crm, _hdr, _mk, _targets, env, login_ready  # noqa: F401  夾具與小工具共用

_BASE = os.path.join(os.path.dirname(__file__), "..")


def _set_overrides(value):
    from helpers import mail_types as MT
    from helpers.settings import _set_setting
    _set_setting(MT.OVERRIDES_KEY, value)


# ── M1：指定的人要有事件所屬模組的權限 ─────────────────────────────────────────────

def test_m1_designating_someone_without_the_module_is_rejected_and_rechecked_at_send_time(env):
    from helpers import line_notify as L, line_recipients as LR
    key = "voucher_submitted"                                           # 會計（需要 finance／cashier）
    L.set_event(key, True)
    with pytest.raises(ValueError):
        L.set_audience(key, "only", [], ["amy"])                        # 業務沒有會計模組
    L.set_audience(key, "only", [], ["carol"])                          # 財務角色通過
    assert LR.resolve_audience(key, []) == ["carol"]
    from db import get_db
    c = get_db()
    c.execute("UPDATE users SET role='engineer', modules='[]' WHERE username='carol'")      # 事後被拿掉權限
    c.commit()
    c.close()
    assert LR.resolve_audience(key, []) == [], "權限被拿掉的人，發送時自動不發"


def test_m1_role_members_are_also_filtered_by_module_permission(env):
    from helpers import line_notify as L, line_recipients as LR
    key = "voucher_submitted"
    L.set_event(key, True)
    L.set_audience(key, "only", ["finance"], [])
    from db import get_db
    c = get_db()
    c.execute("UPDATE users SET role='finance' WHERE username='amy'")      # amy 也是財務角色，但把模組清空後仍屬 finance 角色 ⇒ 有權限
    c.commit()
    c.close()
    assert sorted(LR.resolve_audience(key, [])) == ["amy", "carol"]
    L.set_audience(key, "only", ["sales"], [])                             # 沒有人是業務角色了；改指定「工程師」角色：沒有會計權限 ⇒ 不發
    L.set_audience(key, "only", ["engineer"], [])
    assert LR.resolve_audience(key, []) == []


def test_m1_generic_events_accept_only_admins_and_unrestricted_events_anyone(env):
    from helpers import line_notify as L
    L.set_event("module_activity", True)
    with pytest.raises(ValueError):
        L.set_audience("module_activity", "business_plus", [], ["amy"])
    L.set_event("user_notice", True)
    L.set_audience("user_notice", "business_plus", [], ["amy"])         # user_notice 不檢查模組


def test_m1_settings_endpoint_lists_needed_modules(client, env, login_ready):
    ev = {e["key"]: e for e in client.get("/api/settings/line-notify", headers=_hdr(client, "sa")).json()["events"]}
    assert ev["voucher_submitted"]["need"] == ["finance", "cashier"] and ev["user_notice"]["need"] == []


# ── M3：LINE-only／細項事件不借用信件類型的收件覆寫 ───────────────────────────────

def test_m3_line_only_event_does_not_borrow_mail_type_override(env):
    from helpers import line_notify as L
    _grant_crm("amy", "dan")
    _set_overrides({"dev_case_assigned": {"mode": "superadmin_only"}, "module_activity": {"mode": "superadmin_only"}})
    L.set_event("dev_case_unassigned", True)
    assert L.deliver_event("dev_case_unassigned", usernames=["amy"], title="t") == L.SEND_SENT
    assert _targets(env) == ["amy"], "前任負責人照收，不被借用的信件覆寫換成超管"
    env["line"].clear()
    L.set_event("crm_case_status", True)
    assert L.deliver_event("crm_case_status", usernames=["dan"], title="t") == L.SEND_SENT
    assert _targets(env) == ["dan"]


def test_m3_mail_events_still_follow_their_own_override(env):
    from helpers import line_notify as L
    _set_overrides({"approval_review_edit": {"mode": "superadmin_only"}})
    L.set_event("approval_review_edit", True)
    L.deliver_event("approval_review_edit", usernames=["amy"], title="t")
    assert _targets(env) == ["sa"], "信件類型的 LINE 與 Email 同一份收件設定"


def test_m3_every_non_mail_event_has_who_text_and_settings_page_shows_it(client, env, login_ready):
    from helpers import line_catalog as cat
    for k in cat.LINE_ONLY_EVENTS:
        assert k in cat.WHO_OF, "每個 LINE-only／細項事件都要說明原本收件人是誰：" + k
        assert "不跟任何 Email 收件設定" in cat.follows_text(k)
    assert "Email 通知的收件設定相同" in cat.follows_text("approval_review_edit")
    ev = {e["key"]: e for e in client.get("/api/settings/line-notify", headers=_hdr(client, "sa")).json()["events"]}
    assert ev["dev_case_unassigned"]["follows"].startswith("原本收件人：") and "前任負責人" in ev["dev_case_unassigned"]["follows"]
    html = source_tree.page_file("notification-settings.html").read_text(encoding="utf-8")
    js = (source_tree.page_file("line-events.html").parent.parent / "static" / "line-events-matrix.js").read_text(encoding="utf-8")
    assert "沿用相近的 Email" not in html and "沿用相近的 Email" not in js     # T86：舊清單移除，事件改由內嵌矩陣顯示


# ── L2／L3／L4／L7 ─────────────────────────────────────────────────────────────

def test_high_volume_events_have_a_15_percent_monthly_cap(env):
    from helpers import line_notify as L
    for k in ("module_activity", "crm_visit_logged", "crm_case_progress", "daily_task_assigned", "daily_task_completed",
              "daily_task_overdue", "daily_task_overdue_manager", "daily_task_edited"):
        assert L.month_cap_percent(k) == 15, k


def _line_event_calls():
    import helpers.email_notify as EN
    tree = ast.parse(inspect.getsource(EN))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_line_event" and n.args and isinstance(n.args[0], ast.Constant):
            yield n.args[0].value, n


def test_daily_task_line_has_fixed_text_only_no_free_text_title(env):
    seen = set()
    for ev, call in _line_event_calls():
        if not (ev.startswith("daily_task_") or ev == "range_task_deadline"):
            continue
        seen.add(ev)
        rows = next((k.value for k in call.keywords if k.arg == "rows"), None)
        names = {x.id for x in ast.walk(rows) if isinstance(x, ast.Name)} if rows is not None else set()
        labels = [c.value for c in ast.walk(rows) if isinstance(c, ast.Constant) and isinstance(c.value, str)] if rows is not None else []
        assert not ({"title", "task_title", "task_name"} & names), "%s 的 LINE 不得放自由文字的工作事項標題" % ev
        assert "工作事項" not in labels, "%s 的 LINE 不得有『工作事項』（標題）欄" % ev
        reason = next((k.value for k in call.keywords if k.arg == "reason"), None)
        rnames = {x.id for x in ast.walk(reason) if isinstance(x, ast.Name)} if reason is not None else set()
        assert reason is not None and not ({"title", "task_title", "task_name"} & rnames), "%s 的 reason 不得帶自由文字" % ev
    assert {"daily_task_assigned", "daily_task_completed", "daily_task_overdue", "daily_task_overdue_manager", "daily_task_edited"} <= seen


def test_scan_events_keyed_by_entity_not_date_and_dated_keys_never_parked(env):
    import helpers.email_notify as EN
    from helpers import line_notify as L
    from helpers.settings import _get_setting
    k = EN._line_entity_key("approval_reminder", "Q-1")
    assert k == "approval_reminder|Q-1"
    L.set_event("approval_reminder", True)
    L.set_event("backup_error", True)
    env["line_fail"] = True
    L.deliver_event("approval_reminder", usernames=["bob"], title="t", dedupe_key=k)
    L.deliver_event("backup_error", usernames=["bob"], title="t", dedupe_key="backup_error|2026-11-13")
    pend = _get_setting(L.PENDING_KEY, {}) or {}
    assert k in pend, "綁定對象的事件暫時失敗要進補發佇列"
    assert not any(x.endswith("|2026-11-13") for x in pend), "每日告警（鑰匙以日期結尾）不進補發佇列"


def test_retry_and_daily_check_share_the_per_key_lock(env):
    from helpers import line_notify as L
    assert L._key_lock("approval_reminder|Q-9") is L._key_lock("approval_reminder|Q-9")
    assert "deliver_event(" in inspect.getsource(L.retry_pending), "補發走 deliver_event（內含 per-key 鎖）"


def test_prefs_view_reads_settings_once(env, monkeypatch):
    from helpers import line_notify as L, line_recipients as LR
    for k in L.WIRED_EVENTS:
        L.set_event(k, True)
    calls = {"n": 0}
    real = LR._get_setting

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(LR, "_get_setting", counting)
    LR.prefs_view("bob", "admin")
    assert calls["n"] <= 6, "prefs_view 不得每個事件各讀一次設定（讀到 %d 次）" % calls["n"]


# ── M2：一次動作只發一則 LINE ───────────────────────────────────────────────────

def test_m2_notify_actions_send_one_line_for_all_recipients_with_lowest_privilege_title(env):
    from helpers import notify_actions as NA, line_notify as L
    L.set_event("user_notice", True)
    ev = {"ph": {"金額": "amt", "單號": "no"}, "money": ("金額",), "internal": ()}      # 實際事件目前沒有金額占位符；用合成事件驗最低權限展開
    body = {"label": "t", "template": {"title": "單 {單號} 金額 {金額}", "body": ""}}
    NA._line_batch(ev, {"amt": 12345, "no": "Q-7"}, body, {}, ["amy", "carol", "dan"])
    assert len(env["line"]) == 1, "三位收件人只發一則"
    assert sorted(_targets(env)) == ["amy", "carol", "dan"] and "12345" not in env["line"][0]["text"] and "Q-7" in env["line"][0]["text"], "金額不得出現在 LINE"


def test_m2_send_mail_no_longer_calls_line_per_recipient():
    from helpers import notify_actions as NA
    assert "_line_event" not in inspect.getsource(NA._send_mail)
    assert "_line_batch(" in inspect.getsource(NA._dispatch)


def _loop_line_calls(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    bad = []
    for loop in (n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp))):
        for c in ast.walk(loop):
            if isinstance(c, ast.Call) and getattr(c.func, "attr", getattr(c.func, "id", "")) in (
                    "_line_event", "deliver_event", "notify_event", "_line_delete_request", "_line_batch"):
                bad.append((getattr(c, "lineno", 0), ast.unparse(c)[:80]))
    return bad


def test_m2_no_line_event_is_called_inside_a_loop_at_the_known_per_recipient_call_sites():
    """M2 守門：一次動作 N 位收件人 ⇒ LINE 只能整批一次。掃 vendor_contractors 與 notify_actions 的 LINE 呼叫點（不得在迴圈裡）。"""
    paths = [os.path.join(_BASE, p) for p in ("modules/subcontract/api/vendor_contractors.py", "helpers/notify_actions.py")]
    found = {os.path.basename(p): _loop_line_calls(p) for p in paths}
    # `_dispatch` 裡的 `_line_batch` 在「每個動作」的外層迴圈（每個動作一則），不在逐收件人迴圈：允許 notify_actions 這一個
    found["notify_actions.py"] = [x for x in found["notify_actions.py"] if "_line_batch" not in x[1]]
    assert all(not v for v in found.values()), found


def test_m2_line_batch_is_outside_the_per_recipient_loop():
    from helpers import notify_actions as NA
    src = inspect.getsource(NA._dispatch).splitlines()
    call = next(i for i, ln in enumerate(src) if "_line_batch(" in ln)
    loop = max(i for i, ln in enumerate(src[:call]) if ln.strip().startswith("for n in names:"))
    assert len(src[call]) - len(src[call].lstrip()) < len(src[loop]) - len(src[loop].lstrip()) + 1, "整批 LINE 必須在逐收件人迴圈之外"


def test_m2_vendor_file_delete_request_sends_one_line_per_action(env):
    from modules.subcontract.api import vendor_contractors as VC
    from helpers import line_notify as L
    L.set_event("dispatch_file_delete_request", True)
    VC._line_delete_request(["bob", "sa"], "承攬商報價單附件刪除申請待簽核", "Q-1", "amy", "需要您簽核")
    assert len(env["line"]) == 1 and sorted(_targets(env)) == ["bob", "sa"]
    VC._line_delete_request([], "x", "Q-1", "amy", "y")
    assert len(env["line"]) == 1, "沒有收件人就不呼叫"


# ── L6：沒有簽核層的附件刪除申請也要有專屬 LINE ─────────────────────────────────

def test_delete_request_without_tiers_goes_to_superadmins_with_dedicated_line(env):
    from modules.subcontract.api import vendor_contractors as VC
    src = inspect.getsource(VC)
    assert "_line_delete_request(first_tier or _superadmin_usernames()" in src, "沒有簽核層時也要有專屬 LINE（發給最高管理者）"
    assert "line_skip=True" in src, "同一個動作的泛用 module_activity LINE 要略過，避免重複"
    assert VC._superadmin_usernames() == ["sa"]


# ── L5：提醒綁定 ───────────────────────────────────────────────────────────────

def test_remind_marks_each_person_as_sent_so_a_midway_failure_does_not_resend(env, login_ready, monkeypatch):
    from helpers import line_binding as LB
    for n in ("zed", "yan", "xia"):
        _mk(env["make_user"], n, "engineer", line=False)
    sent, fail_on = [], {"v": "yan"}
    import helpers.audit as AU
    real = AU._notify

    def flaky(name, *a, **k):
        if name == fail_on["v"]:
            raise RuntimeError("boom")
        sent.append(name)
        return real(name, *a, **k)
    monkeypatch.setattr(AU, "_notify", flaky)
    r1 = LB.remind(["zed", "yan", "xia"])
    assert r1["failed"] == 1 and sorted(sent) == ["xia", "zed"]
    fail_on["v"] = None
    r2 = LB.remind(["zed", "yan", "xia"])
    assert sorted(r2["skippedRecent"]) == ["xia", "zed"] and sent.count("zed") == 1, "已提醒的人不會再發"
    assert "yan" in sent, "失敗的那位下次補發"


def test_remind_runs_one_at_a_time(env, login_ready):
    from helpers import line_binding as LB
    assert hasattr(LB, "_remind_lock") and "with _remind_lock" in inspect.getsource(LB.remind)
