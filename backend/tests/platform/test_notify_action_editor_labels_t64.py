# -*- coding: utf-8 -*-
"""T64 BP-4 S5 複審補強：白話值（條件／通知文字）、清單的待核准狀態、停用前的草稿警告、事件說明、帳號顯示名稱。

接著 test_notify_action_editor_t64.py（共用 node 假 DOM 夾具）；後端的白話值另在最下面以單元測試驗證。
"""
import pytest

from helpers import notify_actions as NA
from tests.platform.test_notify_action_editor_t64 import (PICKER, PREVIEW_LOOSEN, _EV, _SETUP, _catalog, _run, _status)

pytestmark = pytest.mark.skipif(__import__("shutil").which("node") is None, reason="沒有 node")

@pytest.fixture(autouse=True)
def _kind_clean():
    """本檔有題會讓種類登記（`preview` 會 ensure_kind）：結束時撤掉，不污染別的測試的種類清單。"""
    yield
    from core import definitions as D
    D._EXTRA_KINDS.pop(NA.KIND, None)                                        # noqa: SLF001
    D._VALIDATORS.pop(NA.KIND, None)                                         # noqa: SLF001


_SLOT_EV = "completion_note.attachment_added"
_MOD_EV = "custom_module.transitioned"
_TIGHT = dict(PREVIEW_LOOSEN, classification={"class": "tighten", "reasons": []})


def test_condition_values_for_closed_sets_are_checkboxes_with_plain_labels():
    pick_field = "change(R().all(n => n.tag === 'select')[1], '附件種類'); E._render(); "
    r = _run({"status": _status(), "run": _SETUP + "E._startNew(); change(byRole('event')[0], '%s'); click('add-cond'); " % _SLOT_EV + pick_field +
              "return [byRole('choices').length, allText(), E._state.f.when[0]]"})
    n, text, cond = r["v"]
    assert n == 1 and "簽回檔" in text and "signed" not in text
    assert cond["picked"] == [] and cond["values"] == ""
    run = (_SETUP + "E._startNew(); change(byRole('event')[0], '%s'); click('add-cond'); " % _SLOT_EV + pick_field +
           "const box = R().all(n => n.attrs['data-choice'] === 'signed')[0]; (box.handlers.change || []).forEach(f => f({ target: { checked: true } })); "
           "const f = E._state.f; f.label = 'x'; return [E._toBody(f).when, allText()]")
    r = _run({"status": _status(), "run": run})
    assert r["v"][0] == [{"field": "附件種類", "in": ["signed"]}] and "signed" not in r["v"][1], "存的是內部值，畫面仍是白話"


def _pick(field):
    return ("E._startNew(); change(byRole('event')[0], '%s'); click('add-cond'); change(R().all(n => n.tag === 'select')[1], '%s'); E._render(); " % (_MOD_EV, field))


def test_custom_module_values_use_module_state_and_action_names():
    text = _run({"status": _status(), "run": _SETUP + _pick("動作") + "return allText()"})["v"]
    for want in ("送出", "核准", "退回", "自動核准"):
        assert want in text, want
    for raw in ("submit", "approve", "auto_approve", "reject"):
        assert raw not in text, raw
    text = _run({"status": _status(), "run": _SETUP + _pick("模組") + "return allText()"})["v"]
    assert "示範模組" in text and "demo" not in text
    text = _run({"status": _status(), "run": _SETUP + _pick("新狀態") + "return allText()"})["v"]
    assert "草稿中" in text and "已送出" in text and "submitted" not in text


def test_free_text_condition_keeps_a_text_box_and_has_no_broken_example():
    run = (_SETUP + "E._startNew(); change(byRole('event')[0], 'case.deadline_near'); click('add-cond'); change(R().all(n => n.tag === 'select')[1], '階段'); E._render(); "
           "return [byRole('choices').length, R().all(n => n.tag === 'input' && n.attrs.placeholder === '值（多個用頓號分隔）').length, allText()]")
    r = _run({"status": _status(), "run": run})
    assert r["v"][0] == 0 and r["v"][1] == 1 and "例如：" not in r["v"][2] and "是「" not in r["v"][2]


def test_event_hint_is_plain_and_dev_speak_never_reaches_the_screen():
    assert all("desc" not in e and e["hint"] for e in NA.event_catalog())
    for ev in NA.EVENTS:
        text = _run({"status": _status(), "run": _SETUP + "E._startNew(); change(byRole('event')[0], '%s'); click('suggest'); return allText()" % ev})["v"]
        for dev in ("payload", "slot", "既有事件", "發佈者", "代號", "JSON", "scan"):
            assert dev not in text, (ev, dev)
        assert NA.EVENTS[ev]["hint"] in text


def test_catalogue_visible_strings_have_no_raw_codes():
    bad = ("payload", "slot", "in_app", "requester", "owner", "role:", "group:", "superadmin", "custom_module", "completion_note", "發佈者", "既有事件")
    visible = []
    for e in _catalog():
        visible += [e["label"], e["hint"], e["suggest"]["label"], e["suggest"]["title"], e["suggest"]["body"]] + e["placeholders"] + e["filterable"]
        for lab in e["labels"].values():
            visible += list(lab.values())
    for p in PICKER["roles"] + PICKER["groups"] + PICKER["people"]:
        visible.append(p["label"])
    for t in visible:
        for b in bad:
            assert b not in t, (t, b)


def _pend(key, approvals=0, need=1, ready=False, eff=""):
    return {"id": 7, "kind": "notify_action", "key": key, "scope": "company", "version": 2, "state": "pending", "by": "x", "at": "2026-10-15T09:00:00",
            "reason": "", "effectiveAt": eff, "approvals": approvals, "approvalsRequired": need, "ready": ready}


def _live(label="甲", event=_EV):
    return {"version": 1, "label": label, "enabled": True, "event": event, "when": [], "channels": ["in_app"], "recipients": [{"kind": "owner"}],
            "template": {"title": "完工單 {完工單號}", "body": "{原狀態} 到 {新狀態}"}, "throttle": {"dedupeMinutes": 60, "maxPerRecipientPerDay": 5}}


def test_list_shows_pending_status_honestly_in_the_three_stages():
    defs = {k: {"draft": None, "latest": {"body": _live(k)}} for k in ("na_a", "na_b", "na_c", "na_d")}
    pend = [_pend("na_a", 0, 1), _pend("na_b", 1, 1, False, "2026-10-20T09:00:00"), _pend("na_c", 1, 1, True),
            {"kind": "layout", "key": "na_d", "state": "pending", "approvals": 0, "approvalsRequired": 1, "ready": False}]
    r = _run({"status": _status(), "list": [{"key": k} for k in defs], "defs": defs, "pending": pend,
              "run": _SETUP + "await E._loadList(); return [byRole('item').map(n => n.textContent), byRole('pending').map(n => n.textContent)]"})
    items, pending = r["v"]
    assert len(items) == 4 and len(pending) == 3, "只列這個種類的待核准（別種定義的不算）"
    joined = "\n".join(pending)
    assert "待第二位最高管理者核准" in joined and "核准前不會生效" in joined
    assert "確認期間結束" in joined and "2026-10-20 09:00" in joined
    assert "可以套用" in joined and "版本與還原" in joined
    for raw in ("na_a", "pending", "approvalsRequired"):
        assert raw not in joined, raw


def test_list_still_loads_when_the_pending_route_is_unavailable():
    defs = {"na_a": {"draft": None, "latest": {"body": _live("甲")}}}
    r = _run({"status": _status(), "list": [{"key": "na_a"}], "defs": defs, "pendingStatus": 404,
              "run": _SETUP + "await E._loadList(); return [byRole('item').length, byRole('pending').length, byRole('pending-error').map(n => n.textContent)]"})
    assert r["v"][:2] == [1, 0]
    assert len(r["v"][2]) == 1 and "無法讀取待核准狀態" in r["v"][2][0], "讀不到時不可以看起來像『沒有待核准』"
    ok = _run({"status": _status(), "list": [{"key": "na_a"}], "defs": defs, "run": _SETUP + "await E._loadList(); return byRole('pending-error').length"})
    assert ok["v"] == 0


def test_two_pending_changes_for_one_action_both_show_and_other_scopes_do_not():
    defs = {"na_a": {"draft": None, "latest": {"body": _live("甲")}}}
    other = dict(_pend("na_a", 0, 1), scope="user")
    r = _run({"status": _status(), "list": [{"key": "na_a"}], "defs": defs, "pending": [_pend("na_a", 0, 1), _pend("na_a", 1, 1, True), other],
              "run": _SETUP + "await E._loadList(); return byRole('pending').map(n => n.textContent)"})
    assert len(r["v"]) == 2 and any("待第二位" in t for t in r["v"]) and any("可以套用" in t for t in r["v"])


def test_disable_with_an_unpublished_draft_asks_twice_and_does_not_overwrite_silently():
    defs = {"na_live": {"draft": {"body": _live("改到一半的草稿"), "etag": "e5"}, "latest": {"body": _live("已發布版本")}}}
    run = (_SETUP + "await E._loadList(); click('disable'); const first = [E._state.msg, byRole('disable')[0].textContent]; "
           "await new Promise(r => setTimeout(r, 30)); return first")
    r = _run({"status": _status(), "preview": _TIGHT, "list": [{"key": "na_live"}], "defs": defs, "run": run})
    msg, label = r["v"]
    assert "尚未發布的修改" in msg and "丟掉" in msg and label == "確認停用" and "再按一次這顆按鈕" in msg and "再按一次「再按一次" not in msg
    assert not any(c.startswith("PUT ") for c in r["calls"]), "第一次按不可以改草稿"
    run2 = _SETUP + "await E._loadList(); click('disable'); click('disable'); await new Promise(r => setTimeout(r, 80)); return 1"
    r = _run({"status": _status(), "preview": _TIGHT, "list": [{"key": "na_live"}], "defs": defs, "publish": {}, "run": run2})
    assert r["bodies"]["PUT /api/definitions/notify_action/na_live/draft"]["body"]["enabled"] is False
    assert "POST /api/definitions/notify_action/na_live/publish" in r["calls"]


def test_disable_without_a_draft_is_one_click():
    defs = {"na_live": {"draft": None, "latest": {"body": _live("甲")}}}
    r = _run({"status": _status(), "preview": _TIGHT, "list": [{"key": "na_live"}], "defs": defs, "publish": {},
              "run": _SETUP + "await E._loadList(); click('disable'); await new Promise(r => setTimeout(r, 80)); return 1"})
    assert "POST /api/definitions/notify_action/na_live/publish" in r["calls"]


# ── 後端：白話值與帳號顯示名稱 ───────────────────────────────────────────────────────
def test_event_labels_static_sets_and_render_uses_plain_values():
    lab = NA.event_labels(None, _SLOT_EV)
    assert lab["labels"]["附件種類"] == {"signed": "簽回檔"} and lab["choices"]["附件種類"] == ["signed"]
    st = NA.event_labels(None, "completion_note.state_changed")
    assert st["choices"]["新狀態"] == list(NA.COMPLETION_STATES)
    assert NA.event_labels(None, "case.deadline_near") == {"labels": {}, "choices": {}}
    ev = NA.EVENTS[_SLOT_EV]
    out = NA._render("{操作人} 上傳了{附件種類}", ev, {"noteNo": "N", "quoteNo": "Q", "slot": "signed", "by": "王"}, {"role": "admin", "modules": "[]"}, lab["labels"])     # noqa: SLF001
    assert out == "王 上傳了簽回檔"
    assert NA._render("{附件種類}", ev, {"slot": "unknown_x"}, {"role": "admin", "modules": "[]"}, lab["labels"]) == "unknown_x"                                      # noqa: SLF001  沒有白話名稱 ⇒ 原值


def test_custom_module_labels_come_from_the_published_definitions_and_scope_to_the_event_module(monkeypatch):
    from helpers import custom_modules as CM
    mods = [{"key": "m_a", "version": 1, "name": "報修單"}, {"key": "m_b", "version": 1, "name": "請購單"}]
    bodies = {"m_a": {"workflow": {"states": [{"key": "draft", "label": "草稿中"}, {"key": "done", "label": "已結束"}], "transitions": [{"key": "finish", "label": "結案"}]}},
              "m_b": {"workflow": {"states": [{"key": "draft", "label": "擬稿"}], "transitions": [{"key": "send", "label": "送出"}]}}}
    monkeypatch.setattr(CM, "published_modules", lambda conn: mods)
    monkeypatch.setattr(CM, "_load_def", lambda conn, key, ver: {"body": bodies[key]})
    u = NA.event_labels(object(), _MOD_EV)
    assert u["labels"]["模組"] == {"m_a": "報修單", "m_b": "請購單"} and u["choices"]["模組"] == ["m_a", "m_b"]
    assert u["labels"]["新狀態"]["draft"] == "草稿中／擬稿", "不同模組同一個狀態代號、名稱不同 ⇒ 並列，不猜"
    assert u["labels"]["動作"]["finish"] == "結案" and u["labels"]["動作"]["approve"] == "核准"
    one = NA.event_labels(object(), _MOD_EV, {"module": "m_b"})
    assert one["labels"]["新狀態"] == {"draft": "擬稿"} and one["labels"]["模組"] == {"m_b": "請購單"} and "choices" in one and "模組" not in one["choices"]


def test_event_labels_never_raise_and_fall_back_to_nothing(monkeypatch):
    from helpers import custom_modules as CM
    monkeypatch.setattr(CM, "published_modules", lambda conn: (_ for _ in ()).throw(RuntimeError("db down")))
    assert NA.event_labels(object(), _MOD_EV) == {"labels": {}, "choices": {}}


def test_preview_conditions_show_plain_values(client, make_user, monkeypatch):
    import db
    monkeypatch.setattr(NA, "enabled", lambda conn=None: True)
    body = {"version": 1, "label": "甲", "enabled": True, "event": _SLOT_EV, "when": [{"field": "附件種類", "in": ["signed"]}], "channels": ["in_app"],
            "recipients": [{"kind": "role", "value": "admin"}], "template": {"title": "完工單 {完工單號}", "body": "{操作人} 上傳了{附件種類}"},
            "throttle": {"dedupeMinutes": 60, "maxPerRecipientPerDay": 5}}
    conn = db.get_db()
    try:
        d = NA.preview(conn, {"username": "x", "role": "superadmin"}, "na_pv_lab", body)
    finally:
        conn.close()
    assert d["conditions"] == [{"field": "附件種類", "value": "簽回檔", "in": ["簽回檔"], "ok": True}]
    assert all("簽回檔" in r["body"] and "signed" not in r["body"] for r in d["renders"])


def test_picker_never_shows_a_username_for_unnamed_accounts(client, make_user):
    import db
    make_user(username="someone@example.com", role="admin")
    make_user(username="named_user", role="admin")
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name='' WHERE username='someone@example.com'")
        conn.execute("UPDATE users SET display_name='王小明' WHERE username='named_user'")
        conn.commit()
        users = NA.picker_catalog(conn)["users"]
    finally:
        conn.close()
    by = {u["username"]: u["displayName"] for u in users}
    assert by["named_user"] == "王小明"
    assert by["someone@example.com"].startswith("未設定名稱的帳號") and "@" not in by["someone@example.com"] and "someone" not in by["someone@example.com"]
