# -*- coding: utf-8 -*-
"""MAIL-CAL 階段 1：信件 × 行事曆通知矩陣（使用者裁示 2026-10-05；設計 docs/platform/plans/MAIL-CAL-MERGE-DESIGN.md）。

守門（設計 §5.2 的三條＋裁示的規則）：
 ① 矩陣完整性：每個登記的信件 key 都有列；每個 `EVENT_TYPES` 代碼不是配對就是僅行事曆；`EVENT_LINKS` 兩端都存在
 ② 停用格理由：沒有行事曆事件的信件 key 一律有原因文字；特例表與鎖定表不可指向不存在的 key
 ③ 預設不變：沒有任何設定時，信件不關、收件人照登記、每個行事曆代碼的開關＝升級前的預設
行為：信件「關」只寫既有的 mail_recipient_overrides（零遷移）、關了真的沒有收件人、原收件設定保留、
      簽核／系統類要確認、鎖住的資安類關不掉（寄信端也忽略設定檔裡的 off）、舊呼叫端不會動到開關、
      行事曆格與 Google 行事曆設定頁同一份儲存。
斷言打在伺服器（API 狀態碼＋設定值＋寄信端收件人），不打畫面文字。
"""
import pytest

from helpers import mail_types as mt
from helpers import notify_matrix as nm
from helpers.settings import _get_setting, _set_setting

#: 升級前（第 41 班基準）每個行事曆代碼的預設開關——寫死成字面值，之後有人改預設會在這裡紅
CAL_DEFAULTS_BASELINE = {
    "invoice_voucher": True, "payment_request": True, "shipping_note": True, "quotation_won": True, "stage_due": True,
    "stage_done": True, "important_comment": True, "case_update": False, "dev_case_converted": True, "dev_case_stale": True,
    "dev_case_update": False, "contractor_payout": False, "expense_payout": False, "receipt_logged": False, "receivable_due": False,
    "payable_due": False,                       # 第42班（t42-planned-pay-date）新增，預設關
    "warranty_expiry": False, "range_task_due": False, "project_end": False,                  # 階段 2（預設關）
}


def _h(client, make_user, name="nm_sa", role="superadmin"):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    _email(u)
    return {"Authorization": "Bearer " + r.json()["token"]}


def _email(username):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET email=? WHERE username=?", (username + "@example.test", username))
        conn.commit()
    finally:
        conn.close()


def _matrix(client, h):
    r = client.get("/api/mail-types", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _row(d, key):
    return next(x for x in d["items"] if x["key"] == key)


def _put(client, h, key, body):
    return client.put("/api/mail-types/%s/recipients" % key, headers=h, json=body)


def _group(key):
    from helpers import email_notify as en
    return en._group_emails(key)


def _lookup(key, usernames):
    from helpers import email_notify as en
    return en._lookup_emails(usernames, key)


# ── ① 矩陣完整性 ──────────────────────────────────────────────────────

def test_matrix_has_a_row_for_every_registered_mail_key_and_every_calendar_code(client, make_user):
    from helpers import google_calendar as gc
    d = _matrix(client, _h(client, make_user))
    assert {x["key"] for x in d["items"]} == set(mt.keys()), "矩陣列與信件登記表不一致"
    only = {c["code"] for c in d["calendarOnly"]}
    linked = {x["calendar"]["code"] for x in d["items"] if x["calendar"]["code"]}
    assert only | linked == set(gc.EVENT_CODES) and not (only & linked), "每個行事曆代碼要不是配對、就是僅行事曆（且不重複）"
    for code, link in nm.EVENT_LINKS.items():
        assert code in gc.EVENT_CODES, "EVENT_LINKS 的行事曆代碼不存在：%s" % code
        for k in (link["mail"], *link["also"]):
            assert mt.get(k) is not None, "EVENT_LINKS 的信件 key 不存在：%s" % k
    assert sum(1 for x in d["items"] if x["calendar"]["code"] and x["calendar"]["primary"]) == len(nm.EVENT_LINKS), "每個配對只有一個主列"


# ── ② 停用格理由 ──────────────────────────────────────────────────────

def test_every_mail_key_without_a_calendar_event_has_a_disabled_reason(client, make_user):
    d = _matrix(client, _h(client, make_user))
    for x in d["items"]:
        c = x["calendar"]
        assert bool(c["code"]) != bool(c["disabledReason"]), "%s：行事曆格不是『可勾』就要有停用原因" % x["key"]
    optional_module_keys = {"tender_found"}                    # 模組（標案雷達）登記的類型：該模組不在安裝包時沒有這個 key，特例表容許它缺席
    for k in list(nm.CALENDAR_DISABLED_SPECIAL) + list(nm.MAIL_OFF_LOCKED):
        assert mt.get(k) is not None or k in optional_module_keys, "特例／鎖定表指向不存在的信件 key：%s" % k
    for k in nm.MAIL_OFF_LOCKED:
        assert nm.mail_off_lock_reason(k) and mt.get(k).category == "system", k
    assert {c["code"] for c in d["calendarOnly"]} == {"quotation_won", "stage_done", "important_comment", "case_update", "dev_case_converted",
                                                       "dev_case_update", "contractor_payout", "receipt_logged", "receivable_due"}


# ── ③ 預設不變 ────────────────────────────────────────────────────────

def test_defaults_are_unchanged_with_no_settings(client, make_user):
    from helpers import google_calendar as gc
    h = _h(client, make_user)
    assert not (_get_setting(mt.OVERRIDES_KEY, {}) or {}) and not (_get_setting("google_calendar", {}) or {}).get("events")
    d = _matrix(client, h)
    assert all(x["mailOff"] is False and x["override"]["mode"] == "default" for x in d["items"])
    assert gc.event_switches({}) == CAL_DEFAULTS_BASELINE
    on = {x["calendar"]["code"]: x["calendar"]["enabled"] for x in d["items"] if x["calendar"]["code"]}
    on.update({c["code"]: c["enabled"] for c in d["calendarOnly"]})
    assert on == CAL_DEFAULTS_BASELINE
    assert "nm_sa@example.test" in _group("settlement_finalized")           # 收件人照登記（管理員＋超管）


# ── 信件格 ────────────────────────────────────────────────────────────

def test_mail_off_stops_recipients_keeps_the_recipient_setting_and_only_touches_the_existing_store(client, make_user):
    h = _h(client, make_user)
    key = "settlement_finalized"
    r = _put(client, h, key, {"mode": "custom", "users": ["nm_sa"], "roles": ["admin"]})
    assert r.status_code == 200
    assert "nm_sa@example.test" in _group(key)
    r = _put(client, h, key, {"mode": "custom", "users": ["nm_sa"], "roles": ["admin"], "mailOff": True})      # 業務類：不需確認
    assert r.status_code == 200 and r.json()["mailOff"] is True
    assert _group(key) == [] and _lookup(key, ["nm_sa"]) == [], "關閉後不該有任何收件人（群組與事件收件人都是）"
    assert _get_setting(mt.OVERRIDES_KEY)[key] == {"mode": "custom", "users": ["nm_sa"], "roles": ["admin"], "off": True}
    row = _row(_matrix(client, h), key)
    assert row["mailOff"] is True and row["noRecipient"] is False, "公司刻意關閉不算『沒有人收到』"
    r = _put(client, h, key, {"mode": "custom", "users": ["nm_sa"], "roles": ["admin"], "mailOff": False})
    assert r.status_code == 200 and r.json()["mailOff"] is False
    assert _get_setting(mt.OVERRIDES_KEY)[key] == {"mode": "custom", "users": ["nm_sa"], "roles": ["admin"]}, "重新開啟後原收件設定還在、沒有殘留 off"
    assert "nm_sa@example.test" in _group(key)
    r = _put(client, h, key, {"mode": "default", "mailOff": False})
    assert key not in (_get_setting(mt.OVERRIDES_KEY) or {}), "預設＋沒關 ⇒ 不留任何設定（與升級前位元相同）"


def test_old_clients_that_omit_mailoff_do_not_touch_the_switch(client, make_user):
    h = _h(client, make_user)
    key = "settlement_finalized"
    assert _put(client, h, key, {"mode": "default", "mailOff": True}).status_code == 200
    assert _put(client, h, key, {"mode": "superadmin_only"}).status_code == 200                     # 舊頁／舊腳本：只改收件模式
    assert _get_setting(mt.OVERRIDES_KEY)[key]["off"] is True and _group(key) == []
    assert _put(client, h, key, {"mode": "default", "mailOff": "yes"}).status_code == 400           # 型別驗證


def test_turning_off_approval_and_system_mail_needs_confirmation(client, make_user):
    h = _h(client, make_user)
    for key in ("payment_request_submitted", "geo_quota_warning"):                                    # 簽核類、（非鎖定的）系統類
        assert mt.get(key).category in nm.MAIL_OFF_CONFIRM_CATEGORIES and not nm.mail_off_lock_reason(key)
        r = _put(client, h, key, {"mode": "default", "mailOff": True})
        assert r.status_code == 409 and "confirm" in r.json()["detail"], (key, r.status_code, r.text)
        assert key not in (_get_setting(mt.OVERRIDES_KEY) or {}), "沒確認不可寫入"
        r = _put(client, h, key, {"mode": "default", "mailOff": True, "confirm": True})
        assert r.status_code == 200, (key, r.text)
        assert _get_setting(mt.OVERRIDES_KEY)[key]["off"] is True
    assert _lookup("payment_request_submitted", ["nm_sa"]) == []
    assert _put(client, h, "payment_request_submitted", {"mode": "default", "mailOff": False}).status_code == 200      # 重新開啟不需確認
    assert _lookup("payment_request_submitted", ["nm_sa"]) == ["nm_sa@example.test"]


def test_security_critical_mail_cannot_be_turned_off_and_the_sender_ignores_a_forced_off(client, make_user):
    h = _h(client, make_user)
    for key in nm.MAIL_OFF_LOCKED:
        r = _put(client, h, key, {"mode": "default", "mailOff": True, "confirm": True})
        assert r.status_code == 400 and nm.MAIL_OFF_LOCKED[key] in r.json()["detail"], (key, r.status_code, r.text)
        row = _row(_matrix(client, h), key)
        assert row["mailOffLockReason"] == nm.MAIL_OFF_LOCKED[key] and row["mailOff"] is False
    assert not (set(nm.MAIL_OFF_LOCKED) & set(_get_setting(mt.OVERRIDES_KEY) or {})), "被拒絕的關閉不可以寫入任何設定"
    _set_setting(mt.OVERRIDES_KEY, {"backup_error": {"mode": "default", "users": [], "roles": [], "off": True}})      # 設定檔被硬改（或舊版殘留）
    assert nm.is_mail_off("backup_error", _get_setting(mt.OVERRIDES_KEY)) is False
    assert "nm_sa@example.test" in _group("backup_error"), "寄信端要忽略鎖定類型的 off（雙保險）"
    assert _row(_matrix(client, h), "backup_error")["mailOff"] is False


def test_mail_off_removes_the_type_from_the_receivable_list_and_skips_the_last_superadmin_check(client, make_user):
    from routers import mail_settings as ms
    h = _h(client, make_user)
    u2, p2 = make_user(username="nm_u2", role="admin")
    key = "settlement_finalized"
    t, o = mt.get(key), {}
    assert ms.receivable(t, o, "nm_u2", "admin") is True
    _put(client, h, key, {"mode": "default", "mailOff": True})
    o = _get_setting(mt.OVERRIDES_KEY)
    assert ms.receivable(t, o, "nm_u2", "admin") is False and ms.receivable(t, o, "nm_sa", "superadmin") is False
    items = client.get("/api/mail-types/receivable?user_id=%d" % _uid("nm_u2"), headers=h).json()["items"]
    assert next(x for x in items if x["key"] == key)["receivable"] is False


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


# ── 行事曆格 ──────────────────────────────────────────────────────────

def test_calendar_cell_is_the_same_store_as_the_google_calendar_settings_page(client, make_user):
    h = _h(client, make_user)
    d = _matrix(client, h)
    assert _row(d, "case_stage_deadline")["calendar"]["enabled"] is True
    assert _row(d, "case_stage_deadline_manager")["calendar"] == {**_row(d, "case_stage_deadline")["calendar"], "primary": False}, "副列與主列同一個行事曆事件"
    r = client.put("/api/settings/google-calendar", headers=h, json={"events": {"stage_due": False, "receipt_logged": True}})      # 矩陣行事曆格呼叫的就是這支
    assert r.status_code == 200 and sorted(r.json()["changed"]) == ["receipt_logged", "stage_due"]
    d = _matrix(client, h)
    assert _row(d, "case_stage_deadline")["calendar"]["enabled"] is False and _row(d, "case_stage_deadline_manager")["calendar"]["enabled"] is False
    assert next(c for c in d["calendarOnly"] if c["code"] == "receipt_logged")["enabled"] is True
    old = client.get("/api/settings/google-calendar", headers=h).json()["events"]                  # 舊頁看到同樣的值
    assert old["stage_due"] is False and old["receipt_logged"] is True
    assert d["calendarStatus"] == {"enabled": False, "connected": False}                            # 總開關與授權沒動


def test_matrix_endpoints_are_superadmin_only(client, make_user):
    h = _h(client, make_user, "nm_admin", "admin")
    assert client.get("/api/mail-types", headers=h).status_code in (401, 403)
    assert _put(client, h, "settlement_finalized", {"mode": "default", "mailOff": True}).status_code in (401, 403)


def test_mail_off_is_honored_on_finance_audience_and_superadmin_only_paths(client, make_user):
    """第42班財務受眾（finance_recipient_emails／_finance_audience_emails／_only_superadmins）也要尊重矩陣的「信件關」；鎖定類型不受影響。"""
    from helpers import email_notify as en
    h = _h(client, make_user)
    fu, fp = make_user(username="nm_fin", role="finance")
    _email(fu)
    key = "module_activity"
    assert nm.mail_off_lock_reason(key) == ""
    assert set(en._finance_audience_emails(key)) == {"nm_sa@example.test", "nm_fin@example.test"}, "基準：財務＋超管"
    assert en.finance_recipient_emails(key) and en._only_superadmins(key)
    r = _put(client, h, key, {"mode": "default", "mailOff": True, "confirm": True})
    assert r.status_code == 200 and r.json()["mailOff"] is True, r.text
    assert en._finance_audience_emails(key) == [], "財務受眾：關了就沒有收件人"
    assert en.finance_recipient_emails(key) == []
    assert en._only_superadmins(key) == []
    assert en._group_emails(key) == []
    _put(client, h, key, {"mode": "superadmin_only", "mailOff": True, "confirm": True})
    assert en._finance_audience_emails(key) == [] and en._only_superadmins(key) == [], "superadmin_only 覆寫也不能繞過關閉"
    _put(client, h, key, {"mode": "default", "mailOff": False})
    assert en._finance_audience_emails(key), "重新開啟後恢復"
    # 鎖定類型：設定檔硬塞 off 也照寄（超管與財務漏斗都一樣）
    _set_setting(mt.OVERRIDES_KEY, {"backup_error": {"mode": "default", "users": [], "roles": [], "off": True}})
    assert "nm_sa@example.test" in en._only_superadmins("backup_error")
    assert "nm_fin@example.test" in en.finance_recipient_emails("backup_error")


def test_mail_off_is_honored_on_manager_event_and_monthly_report_paths(client, make_user, monkeypatch):
    """審查補強：_with_event_recipients／_department_manager_emails／月報收件人原本不經 _mail_off 漏斗；任何覆寫模式下關了都沒有收件人。
    有正對照（沒關時真的回信箱）；部門主管路徑另外量「關了就不查資料庫」，因為 _with_event_recipients 也會擋，單看回傳值分不出這層守門在不在。"""
    import db
    from helpers import email_notify as en
    h = _h(client, make_user)
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='nm_sa'").fetchone()["id"]
        cur = conn.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES ('nm_div', 0, '2026-10-06')")
        cur = conn.execute("INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) VALUES (?, 'nm_dept', 0, ?, '2026-10-06')",
                           (cur.lastrowid, uid))
        dept = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    calls = []
    real_get_db = db.get_db
    monkeypatch.setattr(db, "get_db", lambda *a, **k: (calls.append(1), real_get_db(*a, **k))[1])
    for key in ("case_stage_deadline_manager", "daily_task_overdue_manager"):
        assert nm.mail_off_lock_reason(key) == ""
        assert en._department_manager_emails(dept, key) == ["nm_sa@example.test"], "正對照：沒關時主管收得到"
        for body in ({"mode": "default"}, {"mode": "custom", "users": ["nm_sa"], "roles": ["admin"]}, {"mode": "superadmin_only"}):
            r = _put(client, h, key, dict(body, mailOff=True, confirm=True))
            assert r.status_code == 200 and r.json()["mailOff"] is True, (key, body, r.text)
            assert en._with_event_recipients(["x@example.test"], key) == [], (key, body)
            assert en._lookup_emails(["nm_sa"], key) == [], (key, body)
            calls.clear()
            assert en._department_manager_emails(dept, key) == [], (key, body)
            assert calls == [], "關了就不該去查部門主管（守門要在查詢之前）"
        r = _put(client, h, key, {"mode": "custom", "users": ["nm_sa"], "roles": [], "mailOff": False})
        assert "nm_sa@example.test" in en._with_event_recipients([], key), "重新開啟後恢復"
        assert "nm_sa@example.test" in en._department_manager_emails(dept, key)
    # 月報不能經矩陣 API 關（PUT 400，收件人另頁維護）；但設定檔裡若有 off（硬改／舊殘留）寄信端仍要照辦
    _set_setting("monthly_report_recipients", {"userIds": [uid]})
    _set_setting(mt.OVERRIDES_KEY, {})
    assert en._monthly_report_recipient_emails() == ["nm_sa@example.test"], "正對照：沒關時收得到"
    _set_setting(mt.OVERRIDES_KEY, {"monthly_report": {"mode": "default", "users": [], "roles": [], "off": True}})
    assert en._monthly_report_recipient_emails() == []
    # 鎖定類型：硬塞 off 仍照常（_with_event_recipients 也一樣）
    _set_setting(mt.OVERRIDES_KEY, {"backup_error": {"mode": "default", "users": [], "roles": [], "off": True}})
    assert en._with_event_recipients(["x@example.test"], "backup_error") == ["x@example.test"]
