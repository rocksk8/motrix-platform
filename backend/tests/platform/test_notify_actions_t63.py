# -*- coding: utf-8 -*-
"""BP-4 S4：額外通知動作（kind `notify_action`、派發器、事件宣告、`user_notice` 信件類型）。

1. 旗標關（預設）＝今天：種類沒登記、派發什麼都不做、內建信件類型與通知偏好原樣（只多 `user_notice` 一項）。
2. 事件：首批 4 個，3 個由這裡宣告（只宣告、不發佈），`custom_module.transitioned` 沿用既有宣告。
3. 驗證器：只收登記的事件、非金額的可篩選欄位、固定目錄的收件人、白名單占位符、節流範圍。
4. 寬嚴比較：新增動作／擴大收件人／加信件／放寬節流／範本新增占位符／放寬條件＝放寬；縮小＝收緊；改字＝中性；看不懂＝放寬。
5. 派發：逐人讀取權限過濾、金額占位符逐收件人遮蔽、節流、人數上限、信件（退訂、主旨前綴）、例外隔離、不連鎖。
"""
import copy

import pytest

from core import definitions as D
from core import events as EV
from helpers import mail_types as MT
from helpers import notification_prefs as NP
from helpers import notify_actions as NA

EVENT = "custom_module.transitioned"


def A(**kw):
    d = {"version": 1, "label": "單據送出通知", "enabled": True, "event": EVENT,
         "when": [{"field": "新狀態", "in": ["已送出"]}], "channels": ["in_app"],
         "recipients": [{"kind": "role", "value": "admin"}],
         "template": {"title": "單據 {單據號} 已送出", "body": "{操作人} 把 {單據號} 從 {原狀態} 改成 {新狀態}"},
         "throttle": {"dedupeMinutes": 10, "maxPerRecipientPerDay": 5}}
    d.update(kw)
    return d


def _msgs(body, key="demo_notice"):
    return " | ".join(p["message"] for p in NA.definition_problems(key, body))


@pytest.fixture(autouse=True)
def _kind_clean():
    yield
    D._EXTRA_KINDS.pop(NA.KIND, None)                                        # noqa: SLF001
    D._VALIDATORS.pop(NA.KIND, None)                                         # noqa: SLF001


# ── 1. 旗標關＝今天 ──────────────────────────────────────────────────────────
def test_flag_off_means_no_kind_and_dispatch_is_a_noop(monkeypatch):
    assert NA.enabled() is False
    assert NA.KIND not in D.kinds()
    assert NA.dispatch(EVENT, {"module": "demo", "recordNo": "D-1", "from": "草稿", "to": "已送出", "action": "submit", "by": "x"}) == 0
    assert NA.resolve_actions(None, EVENT) == []
    assert NA.resolve_actions(None, "no.such") == []


def test_flag_off_dispatch_writes_nothing(client, make_user):
    import db
    make_user(username="na_a1", role="admin")
    conn = db.get_db()
    try:
        before = conn.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"]
        before_audit = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        EV.publish(EVENT, {"module": "demo", "recordNo": "D-2", "from": "a", "to": "b", "action": "x", "by": "na_a1"})
        assert conn.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"] == before
        assert conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"] == before_audit
    finally:
        conn.close()


def test_user_notice_is_the_only_new_mail_type_and_follows_the_house_rules():
    t = MT.get(MAIL_KEY := "user_notice")
    assert t and t.category == "business" and t.group == "none" and t.owner == "core"
    assert "user_notice" in NP.EVENT_KEYS                                    # 個人可在「通知偏好」退訂
    assert MT.subject("user_notice", "x").startswith(MT.SUBJECT_PREFIX + "業務－")
    for k in ("approval_request", "next_tier", "approved", "module_activity", "monthly_report", "system_test_mail"):
        assert MT.get(k) is not None                                         # 內建類型原樣


# ── 2. 事件 ──────────────────────────────────────────────────────────────────
def test_four_first_events_three_declared_here_and_one_existing():
    names = {d.name: d for d in EV.declarations()}
    for n in ("completion_note.attachment_added", "completion_note.state_changed", "case.deadline_near"):
        assert n in names and names[n].fields == NA.EVENTS[n]["fields"], n
    assert set(NA.EVENTS) == {"completion_note.attachment_added", "completion_note.state_changed", "custom_module.transitioned", "case.deadline_near"}
    assert NA.EVENTS[EVENT]["declare"] is False                              # 既有宣告方是 helpers.custom_modules
    from helpers import custom_modules                                        # noqa: F401
    assert tuple(names[EVENT].fields) == NA.EVENTS[EVENT]["fields"]


def test_every_event_is_self_consistent():
    for name, ev in NA.EVENTS.items():
        assert set(ev["ph"].values()) <= set(ev["fields"]), name
        assert set(ev["filterable"]) <= set(ev["ph"]) and not set(ev["filterable"]) & (set(ev["money"]) | set(ev["internal"])), name
        assert ev["case_key"] in ev["fields"] if ev.get("case_key") else ev.get("module_key") in ev["fields"], name
        assert set(ev["sample"]) == set(ev["fields"]), name
        assert not any(c in ev["link"] for c in "<>\"'") and (not ev["link"] or ev["link"].split("?")[0].endswith(".html")), name
    assert all(c["event"] in NA.EVENTS for c in NA.event_catalog())


def test_subscribed_to_every_event():
    for n in NA.EVENTS:
        assert NA.SUBSCRIBER in EV.subscribers(n), n


# ── 3. 驗證器 ────────────────────────────────────────────────────────────────
def test_good_definition_passes():
    assert NA.definition_problems("demo_notice", A()) == []


@pytest.mark.parametrize("mut,frag", [
    (lambda b: b.update(event="no.such"), "不認得的事件"),
    (lambda b: b.update(foo=1), "不認得的設定"),
    (lambda b: b.update(enabled="yes"), "true"),
    (lambda b: b.update(version=2), "版本"),
    (lambda b: b.update(when=[{"field": "操作人", "in": ["x"]}]), "不能用"),
    (lambda b: b.update(when=[{"field": "新狀態", "in": ["a"]}] * 2), "只能出現一次"),
    (lambda b: b.update(when=[{"field": "新狀態", "in": []}]), "1～10"),
    (lambda b: b.update(when=[{"field": f, "in": ["a"]} for f in ("模組", "原狀態", "新狀態", "動作")]), "最多"),
    (lambda b: b.update(channels=["email"]), "站內通知"),
    (lambda b: b.update(channels=["in_app", "sms"]), "站內通知"),
    (lambda b: b.update(recipients=[]), "1～8"),
    (lambda b: b.update(recipients=[{"kind": "role", "value": "admin"}] * 9), "1～8"),
    (lambda b: b.update(recipients=[{"kind": "email", "value": "a@b.com"}]), "收件人類別"),
    (lambda b: b.update(recipients=[{"kind": "role", "value": "boss"}]), "角色必須"),
    (lambda b: b.update(recipients=[{"kind": "group", "value": "none"}]), "群組必須"),
    (lambda b: b.update(recipients=[{"kind": "owner"}]), "沒有"),                    # custom_module 事件沒有案件業務
    (lambda b: b.update(recipients=[{"kind": "user", "value": "ghost_user"}]), "現有的啟用帳號"),
    (lambda b: b.update(recipients=[{"kind": "user", "value": "a@b.com"}]), "現有的啟用帳號"),
    (lambda b: b.update(template={"title": "x", "body": "y", "link": "http://a"}), "title 與 body"),
    (lambda b: b["template"].update(title="看 http://evil.example"), "只能使用"),
    (lambda b: b["template"].update(body="{金額} 元"), "不認得的占位符"),
    (lambda b: b["template"].update(body="已核准 {單據號}"), "官方狀態字樣"),
    (lambda b: b["template"].update(body="<b>{單據號}</b>"), "標記字元"),
    (lambda b: b["template"].update(title="字" * 61), "最多 60"),
    (lambda b: b["throttle"].update(dedupeMinutes=0), "1～1440"),
    (lambda b: b["throttle"].update(maxPerRecipientPerDay=21), "1～20"),
    (lambda b: b["throttle"].update(maxPerRecipientPerDay=True), "1～20"),
    (lambda b: b["throttle"].pop("dedupeMinutes"), "節流"),
])
def test_validator_rejects(mut, frag):
    b = copy.deepcopy(A())
    mut(b)
    assert frag in _msgs(b), (frag, _msgs(b))


def test_bad_keys_are_rejected():
    for k in ("A", "x", "1abc", "has space", "a" * 40, "中文鍵"):
        assert NA.definition_problems(k, A()), k
    assert NA.definition_problems("demo_notice", "not a dict")


def test_money_placeholder_cannot_be_a_condition_or_unknown(monkeypatch):
    ev = copy.deepcopy(NA.EVENTS[EVENT])
    ev["ph"]["金額"] = "from"
    ev["money"] = ("金額",)
    ev["filterable"] = ev["filterable"] + ("金額",)
    monkeypatch.setitem(NA.EVENTS, EVENT, ev)
    assert "不能用" in _msgs(A(when=[{"field": "金額", "in": ["1"]}]))         # 金額欄位不能當條件（命中本身不可洩漏金額）


def test_user_recipient_must_be_an_active_account(client, make_user):
    make_user(username="na_real", role="admin")
    assert NA.definition_problems("demo_notice", A(recipients=[{"kind": "user", "value": "na_real"}])) == []


def test_kind_registers_only_when_enabled(monkeypatch):
    assert NA.ensure_kind() is False and NA.KIND not in D.kinds()
    monkeypatch.setattr(NA, "enabled", lambda conn=None: True)
    assert NA.ensure_kind() is True and NA.KIND in D.kinds()
    assert D.validate(NA.KIND, "demo_notice", A()) == []
    assert D.validate(NA.KIND, "demo_notice", A(event="x"))


def test_kind_gate_is_hidden_when_off_and_open_when_on(monkeypatch):
    assert NA._gate("k") == "hidden"                                         # noqa: SLF001
    monkeypatch.setattr(NA, "enabled", lambda conn=None: True)
    assert NA._gate("k") == "open" and NA.KIND in D.kinds()                  # noqa: SLF001


# ── 4. 寬嚴比較 ──────────────────────────────────────────────────────────────
def _c(old, new):
    return NA.compare(old, new)[0]


def test_compare_new_action_is_loosening_unless_disabled():
    assert _c(None, A()) == "loosen" and _c({}, A()) == "loosen"
    assert _c(None, A(enabled=False)) == "neutral"


@pytest.mark.parametrize("mut", [
    lambda b: b["recipients"].append({"kind": "role", "value": "sales"}),
    lambda b: b.update(recipients=[{"kind": "group", "value": "admins"}]),
    lambda b: b.update(channels=["in_app", "email"]),
    lambda b: b["throttle"].update(dedupeMinutes=5),
    lambda b: b["throttle"].update(maxPerRecipientPerDay=9),
    lambda b: b["template"].update(body="{操作人} 改了 {單據號} {模組}"),
    lambda b: b.update(when=[]),
    lambda b: b.update(when=[{"field": "新狀態", "in": ["已送出", "已核准"]}]),
    lambda b: b.update(event="case.deadline_near"),
    lambda b: b.update(extra_unknown=1),
])
def test_compare_loosening(mut):
    new = copy.deepcopy(A())
    mut(new)
    assert _c(A(), new) == "loosen", NA.compare(A(), new)


@pytest.mark.parametrize("mut", [
    lambda b: b.update(enabled=False),
    lambda b: b["when"].append({"field": "動作", "in": ["submit"]}),
    lambda b: b["throttle"].update(dedupeMinutes=60),
    lambda b: b["throttle"].update(maxPerRecipientPerDay=2),
])
def test_compare_tightening(mut):
    new = copy.deepcopy(A())
    mut(new)
    assert _c(A(), new) == "tighten", NA.compare(A(), new)


def test_compare_text_only_change_is_neutral_and_unreadable_is_loosening():
    new = copy.deepcopy(A())
    new["template"]["title"] = "有單據 {單據號} 送出了"
    new["label"] = "改個名字"
    assert _c(A(), new) == "neutral"
    assert _c(A(), "garbage") == "loosen"
    assert _c(A(), None) == "loosen"


def test_pipeline_knows_the_comparator():
    from routers import def_pipeline as P
    assert P.COMPARATORS[NA.KIND] is not None
    assert P.classify(NA.KIND, A(), A(channels=["in_app", "email"]))[0] == "loosen"


# ── 5. 派發 ──────────────────────────────────────────────────────────────────
PAY = {"module": "demo", "recordNo": "D-7", "from": "草稿", "to": "已送出", "action": "submit", "by": "na_actor"}


@pytest.fixture()
def live(monkeypatch, client, make_user):
    """旗標開、有一個已發布的動作（直接回傳，不走發布管線；管線另有測試）。"""
    make_user(username="na_actor", role="engineer", modules=[])
    for u, r in (("na_admin1", "admin"), ("na_admin2", "admin"), ("na_viewer", "viewer"), ("na_fin", "finance")):
        make_user(username=u, role=r, modules=[] if r == "viewer" else None)
    holder = {"actions": [("demo_notice", A())]}
    monkeypatch.setattr(NA, "enabled", lambda conn=None: True)
    monkeypatch.setattr(NA, "resolve_actions", lambda conn, event: [(k, b) for k, b in holder["actions"] if b["event"] == event])
    return holder


def _notes(user=None):
    import db
    conn = db.get_db()
    try:
        q, p = "SELECT username, type, ref_id, ref_label, message, link FROM notifications WHERE type=?", [NA.NOTIF_TYPE]
        if user:
            q, p = q + " AND username=?", p + [user]
        return [dict(r) for r in conn.execute(q + " ORDER BY id", p).fetchall()]
    finally:
        conn.close()


def test_dispatch_writes_in_app_notifications_for_readers_only(live):
    live["actions"][0][1]["recipients"] = [{"kind": "role", "value": "admin"}, {"kind": "role", "value": "viewer"}]
    assert NA.dispatch(EVENT, PAY) == 2
    got = {n["username"]: n for n in _notes()}
    assert set(got) == {"na_admin1", "na_admin2"}                            # viewer 沒有該模組 ⇒ 丟棄
    n = got["na_admin1"]
    assert n["ref_label"] == "單據 D-7 已送出" and n["message"] == "na_actor 把 D-7 從 草稿 改成 已送出" and n["ref_id"].startswith("demo_notice:D-7")


def test_dropped_count_goes_to_the_summary_audit_without_names(live, client):
    import db
    live["actions"][0][1]["recipients"] = [{"kind": "role", "value": "viewer"}, {"kind": "role", "value": "admin"}]
    NA.dispatch(EVENT, PAY)
    conn = db.get_db()
    try:
        r = conn.execute("SELECT detail FROM audit_log WHERE action='notify_action.dispatch' ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert '"droppedNoAccess": 1' in r["detail"] and '"recipients": 2' in r["detail"] and "na_viewer" not in r["detail"]


def test_when_filters_events(live):
    assert NA.dispatch(EVENT, dict(PAY, to="草稿")) == 0
    assert _notes() == []


def test_resolve_actions_filters_disabled_invalid_other_event_and_other_scope(monkeypatch):
    bodies = {"on_one": A(), "off_one": A(enabled=False), "bad_one": A(event="no.such"), "other_ev": A(event="case.deadline_near", when=[], recipients=[{"kind": "owner"}], template={"title": "單 {單號} 快到期", "body": "{階段} 剩 {剩餘天數} 天"}),
              "wrong_tpl": A(template={"title": "x", "body": "y {金額}"})}
    rows = [{"key": k, "scope": "company", "latestVersion": 1} for k in bodies] + [{"key": "on_one", "scope": "user", "latestVersion": 1}, {"key": "draft_only", "scope": "company", "latestVersion": None}]
    monkeypatch.setattr(NA, "enabled", lambda conn=None: True)
    monkeypatch.setattr(D, "list_definitions", lambda conn, kind: rows)
    monkeypatch.setattr(D, "get", lambda conn, kind, key, scope, version=None: {"body": bodies[key]})
    assert [k for k, _b in NA.resolve_actions(None, EVENT)] == ["on_one"]
    assert [k for k, _b in NA.resolve_actions(None, "case.deadline_near")] == ["other_ev"]
    monkeypatch.setattr(NA, "enabled", lambda conn=None: False)
    assert NA.resolve_actions(None, EVENT) == []


def test_throttle_dedupes_and_caps_per_day(live):
    live["actions"][0][1]["recipients"] = [{"kind": "user", "value": "na_admin1"}]
    assert NA.dispatch(EVENT, PAY) == 1
    assert NA.dispatch(EVENT, PAY) == 0                                      # 同一單據 10 分鐘內不重複
    for i in range(10):
        NA.dispatch(EVENT, dict(PAY, recordNo="D-%d" % (100 + i)))
    assert len(_notes("na_admin1")) == 5                                     # 每天最多 5 則（maxPerRecipientPerDay）


def test_recipient_cap(live, make_user, monkeypatch):
    monkeypatch.setitem(NA.CAPS, "seconds", 1e9)                              # 這題只驗人數上限；時間預算另有測試（慢機器上 25 人可能超過 2 秒）
    for i in range(30):
        make_user(username="na_bulk%02d" % i, role="admin")
    live["actions"][0][1]["recipients"] = [{"kind": "role", "value": "admin"}]
    live["actions"][0][1]["throttle"]["maxPerRecipientPerDay"] = 20
    assert NA.dispatch(EVENT, PAY) == NA.CAPS["recipients"] == 25


def test_money_placeholders_are_masked_per_recipient(live, monkeypatch, make_user):
    make_user(username="na_sa", role="superadmin")
    ev = copy.deepcopy(NA.EVENTS[EVENT])
    ev["ph"]["金額"], ev["money"], ev["fields"] = "amount", ("金額",), ev["fields"] + ("amount",)
    monkeypatch.setitem(NA.EVENTS, EVENT, ev)
    body = A(recipients=[{"kind": "user", "value": "na_admin1"}, {"kind": "user", "value": "na_sa"}],
             template={"title": "單據 {單據號}", "body": "金額 {金額}"})
    live["actions"][0] = ("demo_notice", body)
    NA.dispatch(EVENT, dict(PAY, amount="NT$ 12,000"))
    got = {n["username"]: n["message"] for n in _notes()}
    assert got["na_admin1"] == "金額 （略）"                                  # 作者再大，收件人沒有財務權限就看不到
    assert got["na_sa"] == "金額 NT$ 12,000"


def test_internal_placeholder_is_always_masked(live, monkeypatch):
    ev = copy.deepcopy(NA.EVENTS[EVENT])
    ev["internal"] = ("動作",)
    monkeypatch.setitem(NA.EVENTS, EVENT, ev)
    assert "不認得的占位符" in _msgs(A(template={"title": "x {單據號}", "body": "{動作}"}))
    out = NA._render("{動作}/{單據號}", ev, PAY, {"role": "superadmin", "modules": "[]"})          # noqa: SLF001
    assert out == "（略）/D-7"


def test_failure_in_writing_never_escapes(live, monkeypatch):
    import helpers.audit as AU
    monkeypatch.setattr(AU, "_notify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert NA.dispatch(EVENT, PAY) == 0                                      # 不拋、不影響發佈方


def test_subscriber_failure_is_isolated_via_the_event_bus(live, monkeypatch):
    import helpers.audit as AU
    monkeypatch.setattr(AU, "_notify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert EV.publish(EVENT, PAY) >= 1


def test_no_chain_reentrancy(live, monkeypatch):
    seen = []
    import helpers.audit as AU
    real = AU._notify

    def spy(*a, **k):
        seen.append(NA.dispatch(EVENT, PAY))                                 # 派發中再收到事件 ⇒ 略過
        return real(*a, **k)
    monkeypatch.setattr(AU, "_notify", spy)
    NA.dispatch(EVENT, PAY)
    assert seen and set(seen) == {0}


def test_email_channel_uses_user_notice_respects_mute_and_hourly_cap(live, monkeypatch):
    from helpers import email_notify as EN
    sent = []
    monkeypatch.setattr(EN, "_async_send", lambda to, subject, html: sent.append((to, subject, html)))
    monkeypatch.setattr(EN, "_mail_off", lambda key: False)
    monkeypatch.setattr(EN, "_base_url", lambda: "https://x.example")
    u = {"email": "a@example.com", "notification_muted": None}
    NA._mail_times.clear()
    NA._send_mail(u, "demo_notice", "標題", "內文 <b>x</b>")                 # noqa: SLF001
    assert len(sent) == 1 and sent[0][0] == ["a@example.com"] and sent[0][1].startswith(MT.SUBJECT_PREFIX + "業務－標題")
    assert "&lt;b&gt;" in sent[0][2] and "<b>x</b>" not in sent[0][2]         # 內文逸出
    NA._send_mail(dict(u, notification_muted='["na:demo_notice"]'), "demo_notice", "t", "b")   # noqa: SLF001
    NA._send_mail(dict(u, notification_muted='["user_notice"]'), "demo_notice", "t", "b")      # noqa: SLF001
    NA._send_mail({"email": "", "notification_muted": None}, "demo_notice", "t", "b")           # noqa: SLF001
    assert len(sent) == 1                                                    # 個別退訂、整類退訂、沒有 email 都不寄
    NA._mail_times.clear()
    for _ in range(NA.CAPS["mailsPerHour"] + 5):
        NA._send_mail(u, "demo_notice", "t", "b")                            # noqa: SLF001
    assert len(sent) == 1 + NA.CAPS["mailsPerHour"]
    NA._mail_times.clear()


def test_email_is_off_when_mail_type_is_switched_off(live, monkeypatch):
    from helpers import email_notify as EN
    sent = []
    monkeypatch.setattr(EN, "_async_send", lambda *a: sent.append(a))
    monkeypatch.setattr(EN, "_mail_off", lambda key: key == "user_notice")
    NA._send_mail({"email": "a@example.com", "notification_muted": None}, "demo_notice", "t", "b")   # noqa: SLF001
    assert sent == []


def test_link_comes_from_the_event_not_the_definition(live):
    ev = NA.EVENTS["completion_note.attachment_added"]
    assert NA._link(ev, {"quoteNo": "MQ-1", "noteNo": "CN-1", "slot": "s", "by": "x"}) == "case-management.html?q=MQ-1"       # noqa: SLF001
    assert NA._link(NA.EVENTS[EVENT], PAY) == ""                              # noqa: SLF001
    from helpers.audit import _LINK_RE
    assert _LINK_RE.match("case-management.html?q=MQ-1")
    assert "link" not in NA._TOP                                              # noqa: SLF001  動作定義不能指定連結


# ── 6. 走既有治理管線（發布前預覽、放寬進待核准、收緊立即生效）──────────────────────────
def _gov(monkeypatch, on, governance=False):
    monkeypatch.setattr(NA, "enabled", lambda conn=None: on)
    import routers.def_governance as G
    import routers.def_pipeline as P
    import routers.definitions as DF
    monkeypatch.setattr(G, "enabled", lambda conn=None: governance)
    monkeypatch.setattr(P, "enabled", lambda conn=None: governance)
    monkeypatch.setattr(DF, "_governance_enabled", lambda conn=None: governance)


def _sa(client, make_user, name):
    u, pw = make_user(username=name, role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def test_off_means_hidden_kind_and_no_drafts(client, make_user, monkeypatch):
    hd = _sa(client, make_user, "na_gov0")
    _gov(monkeypatch, False)
    assert NA.KIND not in [k["kind"] if isinstance(k, dict) else k for k in client.get("/api/definition-kinds", headers=hd).json()]
    assert client.put("/api/definitions/notify_action/demo_notice/draft?scope=company", json={"body": A()}, headers=hd).status_code in (400, 404)


def test_governance_makes_a_new_action_pending_and_disabling_immediate(client, make_user, monkeypatch):
    hd = _sa(client, make_user, "na_gov1")
    url = "/api/definitions/notify_action/demo_notice"
    _gov(monkeypatch, True, governance=True)
    assert client.put(url + "/draft?scope=company", json={"body": A()}, headers=hd).status_code == 200
    no_hash = client.post(url + "/publish?scope=company", json={"note": "x"}, headers=hd)
    assert no_hash.status_code == 409 and no_hash.json()["code"] == "preview_required", "額外通知＝資訊揭露面：發布前必須先看過影響預覽"
    im = client.get("/api/def-governance/notify_action/demo_notice/impact?scope=company", headers=hd)
    assert im.status_code == 200 and im.json()["previewHash"], im.text
    r = client.post(url + "/publish?scope=company", json={"note": "x", "preview_hash": im.json()["previewHash"]}, headers=hd).json()
    assert r["pending"] is True and any("新增通知動作" in x for x in r["reasons"]), r            # 放寬：第二位最高管理者核准前不生效
    import db
    conn = db.get_db()
    try:
        assert D.get(conn, NA.KIND, "demo_notice", "company") is None                          # 還沒有已發布版本 ⇒ 派發不會用到它
    finally:
        conn.close()


def test_scope_text_and_lists_know_the_new_kind(client, make_user, monkeypatch):
    from routers import def_governance as G, def_pipeline as P, definitions as DF
    assert NA.KIND in G._SCOPE_TEXT and NA.KIND in P.ACTIVE_KINDS and NA.KIND in DF._PREVIEW_ENFORCED_KINDS      # noqa: SLF001
    monkeypatch.setattr(NA, "enabled", lambda conn=None: False)
    assert NA.KIND in DF._disabled_lazy_kinds()                                                                 # noqa: SLF001


# ── 7. 發佈方的一行（emit）──────────────────────────────────────────────────────
def test_emit_publishes_to_the_bus_and_never_raises(monkeypatch):
    got = []
    EV.subscribe("case.deadline_near", lambda p: got.append(p), "test_emit")
    payload = {"quoteNo": "MQ-1", "stage": "施工", "dueDate": "2026-10-20", "daysLeft": 3, "assignee": "x"}
    assert NA.emit("case.deadline_near", payload) >= 1 and got and got[-1]["stage"] == "施工"
    assert NA.emit("no.such.event", {}) >= 0                                  # 沒宣告的事件：記 log，不丟例外
    monkeypatch.setattr(EV, "publish", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert NA.emit("case.deadline_near", payload) == 0


def test_emit_with_the_flag_off_writes_nothing(client, make_user):
    import db
    make_user(username="na_emit", role="admin")
    conn = db.get_db()
    try:
        n0 = conn.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"]
        NA.emit("completion_note.state_changed", {"noteNo": "CN-1", "quoteNo": "MQ-1", "from": "草稿", "to": "待審核", "by": "na_emit"})
        assert conn.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"] == n0
    finally:
        conn.close()


# ── 8. 試跑預覽（唯讀）────────────────────────────────────────────────────────
def _hd(client, make_user, name, role="superadmin"):
    u, pw = make_user(username=name, role=role)[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def test_preview_route_is_404_when_off_403_for_others_422_when_invalid(client, make_user, monkeypatch):
    sa, adm = _hd(client, make_user, "na_pv_sa"), _hd(client, make_user, "na_pv_adm", "admin")
    url = "/api/notify-actions/demo_notice/preview"
    assert client.get("/api/notify-actions/status", headers=sa).json() == {"enabled": False, "canEdit": False}
    assert client.post(url, json={"template": A()}, headers=sa).status_code == 404
    monkeypatch.setattr(NA, "enabled", lambda conn=None: True)
    assert client.post(url, json={"template": A()}, headers=adm).status_code == 403
    r = client.post(url, json={"template": A(event="no.such")}, headers=sa)
    assert r.status_code == 422 and r.json()["detail"]["problems"]
    assert client.post(url, json={"template": A(), "payload": {"nope": 1}}, headers=sa).status_code == 422
    st = client.get("/api/notify-actions/status", headers=sa).json()
    assert st["enabled"] and st["canEdit"] and {e["event"] for e in st["events"]} == set(NA.EVENTS) and st["caps"]["recipients"] == 25
    assert "events" not in client.get("/api/notify-actions/status", headers=adm).json()


def test_preview_reports_match_recipient_counts_renders_and_classification(client, make_user, monkeypatch):
    sa = _hd(client, make_user, "na_pv_sa2")
    make_user(username="na_pv_a1", role="admin")
    monkeypatch.setattr(NA, "enabled", lambda conn=None: True)
    r = client.post("/api/notify-actions/demo_notice/preview", json={"template": A(recipients=[{"kind": "role", "value": "admin"}, {"kind": "requester"}])}, headers=sa)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["usesSample"] is True and d["matches"] is True                  # 範例是 草稿→已送出，條件是 新狀態∈{已送出} ⇒ 命中
    assert d["classification"]["class"] == "loosen" and any("新增通知動作" in x for x in d["classification"]["reasons"])
    by = {(x["kind"], x["value"]): x["count"] for x in d["recipients"]}
    assert by[("role", "admin")] >= 1 and by[("requester", None)] is None and d["eventDependentRecipients"] == 1
    assert [x["role"] for x in d["renders"]] == list(NA.PREVIEW_ROLES) and "readable" in d and "estimate" in d
    assert "na_pv_a1" not in r.text                                          # 只回人數，不回姓名


def test_preview_with_matching_payload_matches_and_masks_money_per_role(client, make_user, monkeypatch):
    sa = _hd(client, make_user, "na_pv_sa3")
    ev = copy.deepcopy(NA.EVENTS[EVENT])
    ev["ph"]["金額"], ev["money"], ev["fields"] = "amount", ("金額",), ev["fields"] + ("amount",)
    ev["sample"] = dict(ev["sample"], amount="NT$ 5,000")
    monkeypatch.setitem(NA.EVENTS, EVENT, ev)
    monkeypatch.setattr(NA, "enabled", lambda conn=None: True)
    body = A(template={"title": "單據 {單據號}", "body": "金額 {金額}"})
    d = client.post("/api/notify-actions/demo_notice/preview", json={"template": body, "payload": {"新狀態": "x"}}, headers=sa)
    assert d.status_code == 422                                              # payload 的鍵是 payload 欄位名（to），不是占位符名
    d = client.post("/api/notify-actions/demo_notice/preview", json={"template": body, "payload": {"to": "已送出"}}, headers=sa).json()
    assert d["matches"] is True and d["usesSample"] is False
    by_role = {x["role"]: x["body"] for x in d["renders"]}
    assert by_role["superadmin"] == "金額 NT$ 5,000" and by_role["finance"] == "金額 NT$ 5,000"
    assert by_role["admin"] == by_role["sales"] == by_role["viewer"] == "金額 （略）"


def test_preview_is_read_only(client, make_user, monkeypatch):
    import db
    sa = _hd(client, make_user, "na_pv_sa4")
    monkeypatch.setattr(NA, "enabled", lambda conn=None: True)
    sent = []
    from helpers import email_notify as EN
    monkeypatch.setattr(EN, "_async_send", lambda *a: sent.append(a))
    published = []
    EV.subscribe(EVENT, lambda p: published.append(p), "test_pv")
    conn = db.get_db()
    try:
        snap = lambda: [conn.execute("SELECT COUNT(*) c FROM %s" % t).fetchone()["c"] for t in ("notifications", "ui_definitions")]     # noqa: E731
        before = snap()
        r = client.post("/api/notify-actions/demo_notice/preview", json={"template": A(channels=["in_app", "email"])}, headers=sa)
        assert r.status_code == 200
        assert snap() == before and sent == [] and published == []
        last = conn.execute("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()["action"]
        assert last == "notify_action.previewed"                             # 預覽只留一筆稽核
    finally:
        conn.close()


# ── 10. 審查補強（f0）：預算在迴圈內檢查、信件上限留稽核、去重鍵含階段／新狀態、LIKE 萬用字元 ───────────────
def _audits(action):
    import db
    conn = db.get_db()
    try:
        return [r["detail"] for r in conn.execute("SELECT detail FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        conn.close()


def test_time_budget_is_checked_inside_the_recipient_loop(live, monkeypatch):
    live["actions"][0][1]["recipients"] = [{"kind": "role", "value": "admin"}]
    import types
    ticks = iter([0, 0, 0])                                                  # t0、動作層檢查、第一位收件人之前：都在預算內
    monkeypatch.setattr(NA, "time", types.SimpleNamespace(monotonic=lambda: next(ticks, 100.0)))   # 之後一律超時（只換本檔的 time，不碰全域）
    assert NA.dispatch(EVENT, PAY) == 1                                      # 只送出第一位
    d = _audits("notify_action.degraded")
    assert d and '"timeBudgetExceeded": true' in d[-1] and '"notNotified": ' in d[-1] and "na_admin" not in d[-1]


def test_mail_over_the_hourly_cap_is_audited_and_in_app_still_goes_out(live, monkeypatch):
    from helpers import email_notify as EN
    live["actions"][0][1].update(channels=["in_app", "email"], recipients=[{"kind": "role", "value": "admin"}])
    real = NA._user_row
    monkeypatch.setattr(NA, "_user_row", lambda conn, u: dict(real(conn, u) or {}, email=u + "@example.com") if real(conn, u) else None)
    sent = []
    monkeypatch.setattr(EN, "_async_send", lambda *a: sent.append(a))
    monkeypatch.setattr(EN, "_mail_off", lambda key: False)
    NA._mail_times.clear()
    NA._mail_times["demo_notice"] = __import__("collections").deque([__import__("time").monotonic()] * NA.CAPS["mailsPerHour"])
    n = NA.dispatch(EVENT, PAY)
    NA._mail_times.clear()
    assert n >= 2 and sent == []                                             # 站內通知照送、信件一封都沒寄
    d = _audits("notify_action.degraded")
    assert d and '"mailOverHourlyCap": %d' % n in d[-1]


def test_dedupe_key_includes_stage_and_new_status(live, monkeypatch):
    monkeypatch.setattr(NA, "_readable", lambda *a, **k: True)
    tpl = {"title": "單 {單號} 的階段 {階段}", "body": "還剩 {剩餘天數} 天"}
    live["actions"][0] = ("demo_notice", A(event="case.deadline_near", when=[], recipients=[{"kind": "user", "value": "na_admin1"}], template=tpl,
                                           throttle={"dedupeMinutes": 60, "maxPerRecipientPerDay": 20}))
    base = {"quoteNo": "MQ-9", "dueDate": "2026-10-20", "daysLeft": 3, "assignee": "na_admin1"}
    assert NA.dispatch("case.deadline_near", dict(base, stage="施工")) == 1
    assert NA.dispatch("case.deadline_near", dict(base, stage="驗收")) == 1      # 同一案件的另一個階段：另一件事，不被去重吃掉
    assert NA.dispatch("case.deadline_near", dict(base, stage="施工")) == 0      # 同階段：去重
    live["actions"][0] = ("demo_notice", A(event="completion_note.state_changed", when=[], recipients=[{"kind": "user", "value": "na_admin1"}],
                                           template={"title": "完工單 {完工單號}", "body": "{原狀態} 到 {新狀態}"}, throttle={"dedupeMinutes": 60, "maxPerRecipientPerDay": 20}))
    s = {"noteNo": "CN-9", "quoteNo": "MQ-9", "by": "x"}
    assert NA.dispatch("completion_note.state_changed", dict(s, **{"from": "草稿", "to": "待審核"})) == 1
    assert NA.dispatch("completion_note.state_changed", dict(s, **{"from": "待審核", "to": "已核准"})) == 1   # 送審後馬上核准：不同的新狀態


def test_every_event_has_a_dedupe_ref_made_of_declared_fields():
    for name, ev in NA.EVENTS.items():
        assert ev["ref"] and set(ev["ref"]) <= set(ev["fields"]), name


def test_per_day_count_does_not_treat_underscore_as_a_wildcard(live, client):
    import db
    from helpers.audit import _notify
    _notify("na_admin1", NA.NOTIF_TYPE, "naXx1:Q1", "t", "m")                 # 另一個動作（代號只在第 3 個字不同）的通知
    conn = db.get_db()
    try:
        th = {"dedupeMinutes": 10, "maxPerRecipientPerDay": 1}
        assert NA._throttled(conn, "na_admin1", "na_x1", "na_x1:Q2", th) is False
        _notify("na_admin1", NA.NOTIF_TYPE, "na_x1:Q1", "t", "m")
        assert NA._throttled(conn, "na_admin1", "na_x1", "na_x1:Q2", th) is True
    finally:
        conn.close()
