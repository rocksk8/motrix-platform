# -*- coding: utf-8 -*-
"""S3b：信件收件人矩陣的草稿儲存（`/api/settings/mail/batch-preview`／`batch`／`batch-undo`）。

守門：
 ① 原子性：任一列不合法 ⇒ 400、一個都不寫（含行事曆開關）；格式不對的請求本體一律 400
 ② 簽核／系統技術類被關閉：沒帶 confirm_system ⇒ 400 `confirm_system_required`（列出是哪幾列）；預覽標出系統類（確認視窗紅字用）
 ③ 行事曆欄與行事曆設定頁**同一份資料**：批次改行事曆格 ⇒ `google_calendar.events` 變；憑證 refresh_token 不動；「同上」副列不能單獨改
 ④ 防蓋掉別人：expect 缺／過期 ⇒ 400／409 `{code:'conflict', keys, by, at}`，整批不寫
 ⑤ 整批一筆稽核（`settings.mail.batch`）＋一則設定變更通知；預覽不寫、不通知
 ⑥ 復原：寫回套用前、被別人改過 ⇒ 409；單列舊 PUT 與批次同一套規則
斷言打在 API 狀態碼與 system_settings，不打畫面文字。
"""
import json

import pytest

from helpers import mail_types as mt
from helpers import notify_matrix as nm
from helpers.settings import _get_setting, _set_setting

P = "/api/settings/mail"


def _h(client, make_user, name="s3b_sa"):
    u, p = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(autouse=True)
def _clean(client):
    def wipe():
        import db
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM system_settings WHERE key IN ('google_calendar', 'mail_recipient_overrides')")
            conn.execute("DELETE FROM audit_log WHERE action LIKE 'settings.mail.%'")
            conn.commit()
        finally:
            conn.close()
    wipe()
    yield
    wipe()


def _free(cat, confirm):
    for t in mt.all_types():
        if t.category == cat and t.key not in mt.MANAGED_ELSEWHERE and not nm.mail_off_lock_reason(t.key) and nm.mail_off_needs_confirm(t.key) == confirm:
            return t.key
    raise AssertionError("找不到 %s 類型" % cat)


def _primary():
    for t in mt.all_types():
        link = nm.calendar_link_of_mail(t.key)
        if link and link["primary"] and t.key not in mt.MANAGED_ELSEWHERE and not nm.mail_off_lock_reason(t.key):
            return t.key, link["code"]


def _secondary():
    for t in mt.all_types():
        link = nm.calendar_link_of_mail(t.key)
        if link and not link["primary"]:
            return t.key


def _get(client, h):
    r = client.get("/api/mail-types", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _versions(client, h, keys):
    d = _get(client, h)
    by = {x["key"]: x["version"] for x in d["items"]}
    by.update({x["key"]: x["version"] for x in d["calendarOnly"]})
    return {k: by[k] for k in keys}, d["auditMark"]


def _save(client, h, changes, expect=None, **kw):
    ex = expect if expect is not None else _versions(client, h, list(changes))[0]
    return client.post(P + "/batch", headers=h, json={"changes": changes, "expect": ex, **kw})


def _overrides():
    return _get_setting(mt.OVERRIDES_KEY, {}) or {}


def _audits(prefix="settings.mail."):
    import db
    conn = db.get_db()
    try:
        return [r["action"] for r in conn.execute("SELECT action FROM audit_log WHERE action LIKE ? ORDER BY id", (prefix + "%",))]
    finally:
        conn.close()


def test_get_exposes_row_versions_and_audit_mark(client, make_user):
    h = _h(client, make_user)
    d = _get(client, h)
    assert isinstance(d["auditMark"], int)
    assert all(len(x["version"]) == 12 for x in d["items"])
    assert d["calendarOnly"] and all(x["key"].startswith("cal:") and x["version"] for x in d["calendarOnly"])


def test_batch_applies_everything_in_one_save(client, make_user):
    h = _h(client, make_user)
    biz = _free("business", False)
    pk, code = _primary()
    cal_only = _get(client, h)["calendarOnly"][0]
    pk_on = next(x for x in _get(client, h)["items"] if x["key"] == pk)["calendar"]["enabled"]
    r = _save(client, h, {biz: {"mode": "superadmin_only"}, pk: {"calendar": not pk_on}, cal_only["key"]: {"calendar": not cal_only["enabled"]}})
    assert r.status_code == 200, r.text
    assert set(r.json()["changed"]) == {biz, pk, cal_only["key"]}
    assert _overrides()[biz]["mode"] == "superadmin_only"
    from helpers import google_calendar as gc
    sw = gc.event_switches(_get_setting("google_calendar", {}))
    assert sw[cal_only["code"]] is (not cal_only["enabled"]) and sw[code] is (not pk_on)
    assert _audits().count("settings.mail.batch") == 1


def test_one_invalid_row_means_nothing_is_written(client, make_user):
    h = _h(client, make_user)
    biz = _free("business", False)
    cal_only = _get(client, h)["calendarOnly"][0]
    bad = [{biz: {"mode": "superadmin_only"}, "no_such_mail": {"mode": "default"}},
           {biz: {"mode": "superadmin_only"}, cal_only["key"]: {"calendar": "yes"}},
           {biz: {"mode": "custom", "users": ["ghost_user_zz"]}},
           {biz: {"mode": "custom"}},
           {biz: {"mode": "superadmin_only"}, "cal:not_a_code": {"calendar": True}},
           {biz: {"mode": "superadmin_only", "bogus": 1}}]
    before, ov0 = _get_setting("google_calendar", None), dict(_overrides())
    for ch in bad:
        ex = {k: "x" * 12 for k in ch}                       # 驗證在比對版本之前或之後都不能寫入；這裡用真的版本避免被 409 蓋過
        ex.update(_versions(client, h, [k for k in ch if k in (biz, cal_only["key"])])[0])
        r = client.post(P + "/batch", headers=h, json={"changes": ch, "expect": ex})
        assert r.status_code in (400, 404, 409), (ch, r.text)
        assert _overrides() == ov0 and _get_setting("google_calendar", None) == before, ch
    assert _audits() == []


@pytest.mark.parametrize("body", [[], {"changes": {}}, {"changes": {"a": {"mode": "default"}}}, {"changes": {"a": {}}, "expect": {"a": "x"}},
                                   {"changes": {"a": {"mode": "default"}}, "expect": {"b": "x"}}, {"changes": {"a": 1}, "expect": {"a": "x"}},
                                   {"changes": {"a": {"mode": "default"}}, "expect": {"a": "x"}, "extra": 1},
                                   {"changes": {"a": {"mode": "default"}}, "expect": {"a": "x"}, "since_audit": "1"},
                                   {"changes": {"a": {"mode": "default"}}, "expect": {"a": "x"}, "confirm_system": "yes"}])
def test_malformed_bodies_are_400(client, make_user, body):
    h = _h(client, make_user)
    assert client.post(P + "/batch", headers=h, json=body).status_code in (400, 404, 422)


def test_closing_a_confirm_type_needs_confirm_system(client, make_user):
    h = _h(client, make_user)
    key = _free("approval", True)
    r = _save(client, h, {key: {"mailOff": True}})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "confirm_system_required"
    assert [x["key"] for x in r.json()["detail"]["critical"]] == [key]
    assert _overrides().get(key) is None
    assert _save(client, h, {key: {"mailOff": True}}, confirm_system=True).status_code == 200
    assert nm.is_mail_off(key, _overrides())
    # 重新開啟不需要確認
    assert _save(client, h, {key: {"mailOff": False}}).status_code == 200
    assert not nm.is_mail_off(key, _overrides())


def test_preview_marks_system_rows_and_writes_nothing(client, make_user):
    h = _h(client, make_user)
    key = _free("approval", True)
    biz = _free("business", False)
    r = client.post(P + "/batch-preview", headers=h, json={"changes": {key: {"mailOff": True}, biz: {"mode": "superadmin_only"}}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert {x["key"] for x in d["confirmRequired"]} == {key} and d["changed"] == 2
    rows = {x["key"]: x for x in d["rows"]}
    assert rows[key]["mailOff"] == [False, True] and rows[biz]["mode"] == ["default", "superadmin_only"]
    assert _overrides() == {} and _audits() == []
    # 與送出共用同一份驗證：預覽也擋不合法的
    assert client.post(P + "/batch-preview", headers=h, json={"changes": {"no_such_mail": {"mode": "default"}}}).status_code == 404


def test_system_type_rows_are_flagged_system(client, make_user):
    h = _h(client, make_user)
    sys_key = next((t.key for t in mt.all_types() if t.category == "system" and t.key not in mt.MANAGED_ELSEWHERE and not nm.mail_off_lock_reason(t.key)), None)
    if sys_key is None:
        pytest.skip("沒有可關閉的系統類信件")
    r = client.post(P + "/batch-preview", headers=h, json={"changes": {sys_key: {"mailOff": True}}})
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0]
    assert row["system"] is True and [x["key"] for x in r.json()["systemRows"]] == [sys_key]


def test_secondary_calendar_row_cannot_be_set_on_its_own(client, make_user):
    h = _h(client, make_user)
    sec = _secondary()
    r = _save(client, h, {sec: {"calendar": True}})
    assert r.status_code == 400 and _get_setting("google_calendar", None) is None


def test_calendar_switch_is_shared_with_the_google_calendar_page(client, make_user):
    h = _h(client, make_user)
    pk, code = _primary()
    cfg = {"enabled": True, "refresh_token": "keep-me", "events": {}}
    _set_setting("google_calendar", cfg)
    now_on = next(x for x in _get(client, h)["items"] if x["key"] == pk)["calendar"]["enabled"]
    assert _save(client, h, {pk: {"calendar": not now_on}}).status_code == 200
    after = _get_setting("google_calendar", {})
    assert after["refresh_token"] == "keep-me" and after["enabled"] is True
    row = next(x for x in _get(client, h)["items"] if x["key"] == pk)
    from helpers import google_calendar as gc
    assert gc.event_switches(after)[code] is (not now_on) and row["calendar"]["enabled"] is (not now_on)


def test_stale_expect_is_409_and_nothing_is_written(client, make_user):
    h = _h(client, make_user)
    biz = _free("business", False)
    ex, mark = _versions(client, h, [biz])
    assert client.put("/api/mail-types/%s/recipients" % biz, headers=h, json={"mode": "superadmin_only"}).status_code == 200   # 別人先改了
    r = client.post(P + "/batch", headers=h, json={"changes": {biz: {"mode": "default"}}, "expect": ex, "since_audit": mark})
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["code"] == "conflict" and d["keys"][0]["key"] == biz and d["by"]
    assert _overrides()[biz]["mode"] == "superadmin_only"
    assert _audits().count("settings.mail.batch") == 0


def test_undo_restores_and_conflicts_when_changed_since(client, make_user):
    h = _h(client, make_user)
    biz = _free("business", False)
    pk, code = _primary()
    before = {k: x for k, x in ((x["key"], x) for x in _get(client, h)["items"]) if k in (biz, pk)}
    prev = {biz: {"mode": "default", "users": [], "roles": [], "off": False, "cal": None},
            pk: {"mode": "default", "users": [], "roles": [], "off": False, "cal": before[pk]["calendar"]["enabled"]}}
    r = _save(client, h, {biz: {"mode": "superadmin_only"}, pk: {"calendar": not before[pk]["calendar"]["enabled"]}})
    assert r.status_code == 200, r.text
    after, mark = r.json()["after"], r.json()["audit_mark"]
    # 別人在中間改了一列 ⇒ 整批不復原
    assert client.put("/api/mail-types/%s/recipients" % biz, headers=h, json={"mode": "default"}).status_code == 200
    r2 = client.post(P + "/batch-undo", headers=h, json={"states": prev, "expect": after, "since_audit": mark})
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "conflict"
    # 重新套用後復原成功
    r = _save(client, h, {biz: {"mode": "superadmin_only"}, pk: {"calendar": not before[pk]["calendar"]["enabled"]}})
    r3 = client.post(P + "/batch-undo", headers=h, json={"states": prev, "expect": r.json()["after"], "since_audit": r.json()["audit_mark"]})
    assert r3.status_code == 200, r3.text
    assert biz not in _overrides()
    assert _audits().count("settings.mail.batch_undo") == 1
    now = {x["key"]: x for x in _get(client, h)["items"]}
    assert now[pk]["calendar"]["enabled"] == before[pk]["calendar"]["enabled"]


def test_batch_notifies_once_and_preview_does_not(client, make_user, monkeypatch):
    from helpers import settings_notify as SN
    sent = []
    monkeypatch.setattr(SN, "_send", lambda items, verb="", header="": sent.append((verb, [i["label"] for i in items])))
    h = _h(client, make_user)
    biz, biz2 = _free("business", False), None
    for t in mt.all_types():
        if t.category == "business" and t.key != biz and t.key not in mt.MANAGED_ELSEWHERE:
            biz2 = t.key
            break
    client.post(P + "/batch-preview", headers=h, json={"changes": {biz: {"mode": "superadmin_only"}}})
    assert sent == []
    assert _save(client, h, {biz: {"mode": "superadmin_only"}, biz2: {"mode": "superadmin_only"}}).status_code == 200
    assert len(sent) == 1 and len(sent[0][1]) == 2


def test_no_op_batch_writes_nothing_and_leaves_no_audit(client, make_user):
    h = _h(client, make_user)
    biz = _free("business", False)
    r = _save(client, h, {biz: {"mode": "default"}})
    assert r.status_code == 200 and r.json()["changed"] == [] and _audits() == []


def test_endpoints_are_superadmin_only(client, make_user):
    u, p = make_user(username="s3b_plain", role="admin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    for path in ("/batch", "/batch-preview", "/batch-undo"):
        assert client.post(P + path, headers=h, json={"changes": {"a": {"mode": "default"}}}).status_code in (401, 403)
    assert client.post(P + "/batch", json={}).status_code in (401, 403)
