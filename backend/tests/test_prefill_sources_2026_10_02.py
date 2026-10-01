# -*- coding: utf-8 -*-
"""表單「自動帶入」來源登記處（helpers/prefill_sources.py）：註冊內容、定義檢查、伺服器取值、不重算、端點、days_between。

反向控制（突變）見 PR 說明：token 不在登記處 ⇒ 擋；locked＋不可鎖的 token ⇒ 擋；日期差的邊界。"""
import json
from datetime import datetime

import pytest

from helpers import formula as F
from helpers import prefill_sources as PS

NOW = datetime(2026, 10, 2, 14, 30)


def _f(**kw):
    base = {"key": "k", "label": "欄位", "type": "text"}
    base.update(kw)
    return base


def _tok(token, **kw):
    return _f(default={"$": token}, **kw)


# ── 登記內容 ─────────────────────────────────────────────────────────────

def test_registry_order_and_shape():
    assert list(PS.PREFILL_SOURCES) == ["requester", "currentUser", "requesterDept", "requesterManager", "today", "now",
                                        "company", "caseCustomer", "caseProject", "lastUsed"]
    for s in PS.list_sources():
        assert set(s) == {"token", "label", "why", "example", "applies_to", "lockable", "needs_context", "requires_time"}
        assert s["label"] and s["why"] and s["example"] and s["applies_to"]
        assert "resolve" not in s
    by = {s["token"]: s for s in PS.list_sources()}
    assert [t for t, s in by.items() if not s["lockable"]] == ["caseCustomer", "caseProject", "lastUsed"]
    assert [t for t, s in by.items() if s["needs_context"]] == ["caseCustomer", "caseProject"]
    assert [t for t, s in by.items() if s["requires_time"]] == ["now"]


def test_custom_modules_default_tokens_follow_the_registry():
    from helpers import custom_modules as CM
    assert CM.DEFAULT_TOKENS == tuple(PS.PREFILL_SOURCES)


def test_endpoint_lists_exactly_the_registry(client, make_user):
    u, pw = make_user(username="ps_user", role="user")
    assert client.get("/api/platform/prefill-sources").status_code in (401, 403)
    tok = client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]
    r = client.get("/api/platform/prefill-sources", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    assert [x["token"] for x in r.json()] == list(PS.PREFILL_SOURCES)
    assert r.json() == json.loads(json.dumps(PS.list_sources()))


# ── 定義檢查（check_field）──────────────────────────────────────────────

def _ok(field, **kw):
    return PS.check_field(field, path="fields[0]", **kw)


def test_every_registered_token_is_accepted_on_each_applicable_type():
    for token, s in PS.PREFILL_SOURCES.items():
        for ftype, target in s["applies_to"]:
            f = _tok(token, type=ftype, **({"target": target} if target else {}), **({"withTime": True} if s["requires_time"] else {}))
            assert _ok(f, mount_has_case=True) == [], (token, ftype, target)


def test_unknown_token_is_rejected_with_path():
    probs = _ok(_tok("whoever"))
    assert probs and probs[0]["path"] == "fields[0].default" and "只認得" in probs[0]["message"]
    assert _ok(_f(default={"$": 5}))                                   # 非字串 token 也擋
    assert _ok(_f(default={"x": 1})) and _ok(_f(default="今天")) == []     # {"$"} 缺 ⇒ 當成「$ 是空字串」擋；純文字預設值不是 token


def test_token_on_wrong_type_or_target_is_rejected():
    assert _ok(_tok("today", type="text"))
    assert _ok(_tok("requester", type="ref", target="departments"))
    assert _ok(_tok("requesterDept", type="ref", target="users"))
    assert _ok(_tok("company", type="number"))
    assert _ok(_tok("now", type="date")), "now 必須是含時間的日期欄"
    assert _ok(_tok("now", type="date", withTime=True)) == []


def test_locked_with_non_lockable_token_is_rejected_but_lockable_is_fine():
    for token in ("lastUsed", "caseCustomer", "caseProject"):
        probs = _ok(_tok(token, type="text", locked=True), mount_has_case=True)
        assert probs and "不能搭配" in probs[0]["message"], token
    assert _ok(_tok("company", type="text", locked=True)) == []
    assert _ok(_tok("today", type="date", locked=True)) == []
    # 參數優先於欄位上的 locked
    assert _ok(_tok("lastUsed", type="text"), locked=True)
    assert _ok(_tok("lastUsed", type="text", locked=True), locked=False) == []


def test_case_tokens_need_a_case_mount_and_last_used_refuses_personal_data():
    assert _ok(_tok("caseCustomer"), mount_has_case=False)
    assert _ok(_tok("caseCustomer"), mount_has_case=True) == []
    assert _ok(_tok("lastUsed", dataClass="F2"))


def test_custom_module_validation_uses_the_registry():
    from helpers import custom_modules as CM

    def probs(fields):
        body = {"name": "表", "icon": "box", "permission": "custom.ps_form", "numbering": {"prefix": "PS", "date": "YYYYMMDD", "digits": 4},
                "fields": fields,
                "workflow": {"initial": "d", "states": [{"key": "d", "label": "草稿"}, {"key": "x", "label": "完", "final": True}],
                             "transitions": [{"key": "go", "label": "完成", "from": "d", "to": "x"}]}}
        return {p["path"]: p["message"] for p in CM.validate_module(body, "ps_form")}
    good = [{"key": "who", "label": "誰", "type": "ref", "target": "users", "default": {"$": "requesterManager"}},
            {"key": "dept", "label": "部門", "type": "ref", "target": "departments", "default": {"$": "requesterDept"}},
            {"key": "co", "label": "公司", "type": "text", "default": {"$": "company"}}]
    assert probs(good) == {}
    assert "fields[0].default" in probs([dict(good[0], default={"$": "nope"})])
    assert "fields[0].default" in probs([dict(good[0], target="departments")])           # ref 欄位的 token 也要檢查（以前沒檢查）
    assert "fields[2].default" in probs([good[0], good[1], dict(good[2], default={"$": "caseCustomer"})])   # 自訂單據沒有案件脈絡


# ── 取值 ────────────────────────────────────────────────────────────────────

@pytest.fixture
def org(client, make_user):
    """部門「業務部」主管 ps_mgr；ps_emp 與 ps_mgr 都歸業務部；處主管 ps_div。"""
    import db
    make_user(username="ps_emp", role="user")
    make_user(username="ps_mgr", role="user")
    make_user(username="ps_div", role="user")
    c = db.get_db()
    try:
        uid = {r["username"]: r["id"] for r in c.execute("SELECT id, username FROM users")}
        c.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES ('營運處', 0, '2026-10-02')")
        div = c.execute("SELECT id FROM divisions WHERE name='營運處'").fetchone()["id"]
        c.execute("INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) VALUES (?, '業務部', 0, ?, '2026-10-02')",
                  (div, uid["ps_mgr"]))
        dept = c.execute("SELECT id FROM departments WHERE name='業務部'").fetchone()["id"]
        c.execute("UPDATE users SET department_id=? WHERE username IN ('ps_emp','ps_mgr')", (dept,))
        c.execute("UPDATE divisions SET manager_user_id=? WHERE id=?", (uid["ps_div"], div)) if "manager_user_id" in {
            r[1] for r in c.execute("PRAGMA table_info(divisions)")} else None
        c.commit()
    finally:
        c.close()
    return {"dept": dept, "div": div}


def _ctx(conn, username="ps_emp", **kw):
    return PS.make_ctx(conn, {"username": username}, now=NOW, **kw)


def test_today_now_requester_resolve_like_before(client):
    ctx = PS.make_ctx(None, {"username": "alice"}, now=NOW)
    assert PS.resolve_field(_tok("today", type="date"), ctx) == "2026-10-02"
    assert PS.resolve_field(_tok("today", type="date", withTime=True), ctx) == "2026-10-02T14:30"
    assert PS.resolve_field(_tok("now", type="date", withTime=True), ctx) == "2026-10-02T14:30"
    assert PS.resolve_field(_tok("requester", type="ref", target="users"), ctx) == "alice"
    assert PS.resolve_field(_tok("currentUser", type="ref", target="users"), ctx) == "alice"
    assert PS.resolve_field(_f(), ctx) is None and PS.resolve_field(_tok("zzz"), ctx) is None


def test_current_user_and_requester_differ_only_when_a_requester_is_passed(client):
    ctx = PS.make_ctx(None, {"username": "typist"}, requester={"username": "boss"}, now=NOW)
    assert PS.resolve_field(_tok("requester", type="ref", target="users"), ctx) == "boss"
    assert PS.resolve_field(_tok("currentUser", type="ref", target="users"), ctx) == "typist"


def test_department_and_manager_from_org_records(client, org):
    import db
    c = db.get_db()
    try:
        d = _tok("requesterDept", type="ref", target="departments")
        m = _tok("requesterManager", type="ref", target="users")
        assert PS.resolve_field(d, _ctx(c)) == org["dept"]
        assert PS.resolve_field(m, _ctx(c)) == "ps_mgr"                       # 直屬主管＝部門主管
        # 主管本人申請：往上找處主管（沒有處主管 ⇒ 留白，不回自己）
        got = PS.resolve_field(m, _ctx(c, "ps_mgr"))
        assert got in (None, "ps_div") and got != "ps_mgr"
        # 沒有部門／查無此人 ⇒ None，不丟例外
        assert PS.resolve_field(d, _ctx(c, "ps_div")) is None and PS.resolve_field(m, _ctx(c, "ps_div")) is None
        assert PS.resolve_field(m, _ctx(c, "nobody")) is None
        assert PS.resolve_field(m, PS.make_ctx(None, {"username": "ps_emp"})) is None      # 沒有連線 ⇒ 留白
    finally:
        c.close()


def test_company_name_comes_from_settings_and_blank_is_none(client, monkeypatch):
    from helpers import company_identity as CI
    monkeypatch.setattr(CI, "location_identity", lambda *a, **k: {"company_name": " ○○機械 "})
    assert PS.resolve_field(_tok("company"), PS.make_ctx(None, {"username": "u"})) == "○○機械"
    monkeypatch.setattr(CI, "location_identity", lambda *a, **k: {"company_name": ""})
    assert PS.resolve_field(_tok("company"), PS.make_ctx(None, {"username": "u"})) is None
    monkeypatch.setattr(CI, "location_identity", lambda *a, **k: 1 / 0)       # 失敗 ⇒ None，不外拋
    assert PS.resolve_field(_tok("company"), PS.make_ctx(None, {"username": "u"})) is None


def test_case_tokens_only_with_case_context():
    ctx = PS.make_ctx(None, {"username": "u"}, case={"customer": "台灣精密", "project": "新廠自動化"})
    assert PS.resolve_field(_tok("caseCustomer"), ctx) == "台灣精密" and PS.resolve_field(_tok("caseProject"), ctx) == "新廠自動化"
    nocase = PS.make_ctx(None, {"username": "u"})
    assert PS.resolve_field(_tok("caseCustomer"), nocase) is None and PS.resolve_field(_tok("caseProject"), nocase) is None
    assert PS.resolve_field(_tok("caseCustomer"), PS.make_ctx(None, {}, case={"customer": ""})) is None


def test_last_used_hook_privacy_and_option_guard(client):
    import db
    c = db.get_db()
    try:
        calls = []

        def hook(conn, user, key):
            calls.append((user["username"], key))
            return "台北出差"
        ctx = PS.make_ctx(c, {"username": "ps_emp"}, last_value=hook)
        assert PS.resolve_field(_tok("lastUsed", key="trip"), ctx) == "台北出差" and calls == [("ps_emp", "trip")]
        # 個資與銀行類欄位：不呼叫 hook、直接留白
        for bad in (_tok("lastUsed", key="x", dataClass="F2"), _tok("lastUsed", key="bank_account"), _tok("lastUsed", key="id_no"),
                    _tok("lastUsed", key="passbook_image")):
            assert PS.resolve_field(bad, ctx) is None
        assert len(calls) == 1
        # 選項後來被改掉 ⇒ 不帶舊值
        assert PS.resolve_field(_tok("lastUsed", key="trip", type="select", options=["高雄", "台中"]), ctx) is None
        assert PS.resolve_field(_tok("lastUsed", key="trip", type="select", options=["台北出差"]), ctx) == "台北出差"
        # hook 丟例外 ⇒ None
        boom = PS.make_ctx(c, {"username": "ps_emp"}, last_value=lambda *a: 1 / 0)
        assert PS.resolve_field(_tok("lastUsed", key="trip"), boom) is None
        # 沒有 hook、沒有 module_key ⇒ None
        assert PS.resolve_field(_tok("lastUsed", key="trip"), PS.make_ctx(c, {"username": "ps_emp"})) is None
    finally:
        c.close()


# ── fill_defaults：建立解析一次、更新不重算 ────────────────────────────────────

BODY = {"fields": [
    _tok("company", key="co", locked=True),
    _tok("today", key="d", type="date"),
    _tok("requester", key="who", type="ref", target="users"),
    _f(key="plain"),
]}


def test_fill_on_create_fills_empty_keeps_supplied_and_overwrites_locked(monkeypatch):
    from helpers import company_identity as CI
    monkeypatch.setattr(CI, "location_identity", lambda *a, **k: {"company_name": "甲公司"})
    ctx = PS.make_ctx(None, {"username": "alice"}, now=NOW)
    out = PS.fill_defaults(BODY, {"co": "偽造", "who": "bob", "plain": "x"}, ctx)
    assert out == {"co": "甲公司", "d": "2026-10-02", "who": "bob", "plain": "x"}        # 鎖定欄蓋掉前端值；已填的不動
    assert PS.fill_defaults(BODY, {}, ctx)["who"] == "alice"
    src = {"co": "偽造"}
    PS.fill_defaults(BODY, src, ctx)
    assert src == {"co": "偽造"}                                                     # 不改傳入的 dict


def test_update_never_re_resolves_and_locked_keeps_the_stored_value(monkeypatch):
    from helpers import company_identity as CI
    monkeypatch.setattr(CI, "location_identity", lambda *a, **k: {"company_name": "改名後的公司"})
    other = PS.make_ctx(None, {"username": "someone_else"}, now=datetime(2027, 1, 1))
    prior = {"co": "甲公司", "d": "2026-10-02", "who": "alice"}
    out = PS.fill_defaults(BODY, {"co": "偽造", "d": "", "who": "bob"}, other, prior=prior)
    assert out["co"] == "甲公司"                       # locked：以舊值為準，不是新的公司名也不是前端值
    assert out["d"] == "" and out["who"] == "bob"      # 沒鎖的：照送來的，不補 token
    assert PS.fill_defaults(BODY, {}, other, prior=prior).get("d") is None


def test_with_default_tokens_wrapper_keeps_the_old_contract():
    from helpers import custom_modules as CM
    out = CM._with_default_tokens({"fields": [_tok("today", key="d", type="date"), _tok("requester", key="who", type="ref", target="users")]},
                                  {}, {"username": "alice"})
    assert out["who"] == "alice" and len(out["d"]) == 10


def test_custom_record_creation_resolves_once_and_last_used_reads_the_users_previous_record(client, make_user, org):
    """整合：建立單據時 requesterDept／lastUsed 由伺服器換成值；同一個人的下一張單據 lastUsed 帶上一張的內容；別人的不會被帶。"""
    hs = {}
    for n in ("ps_emp", "ps_mgr"):
        hs[n] = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": n, "password": "Test-Pass-123"}).json()["token"]}
    su, spw = make_user(username="ps_super", role="superadmin")
    hsu = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": su, "password": spw}).json()["token"]}
    body = {"name": "出差單", "icon": "box", "permission": "custom.ps_trip", "numbering": {"prefix": "PT", "date": "YYYYMMDD", "digits": 4},
            "fields": [{"key": "dept", "label": "部門", "type": "ref", "target": "departments", "default": {"$": "requesterDept"}},
                       {"key": "dest", "label": "目的地", "type": "text", "default": {"$": "lastUsed"}},
                       {"key": "co", "label": "公司", "type": "text", "default": {"$": "company"}, "required": False}],
            "workflow": {"initial": "d", "states": [{"key": "d", "label": "草稿"}, {"key": "x", "label": "完", "final": True}],
                         "transitions": [{"key": "go", "label": "完成", "from": "d", "to": "x"}]}}
    r = client.put("/api/definitions/custom_module/ps_trip/draft", headers=hsu, json={"body": body})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    assert client.post("/api/definitions/custom_module/ps_trip/publish", headers=hsu, json={}).status_code == 200
    import db
    c = db.get_db()
    for n in ("ps_emp", "ps_mgr"):
        c.execute("UPDATE users SET modules=? WHERE username=?", (json.dumps(["custom.ps_trip"]), n))
    c.commit()
    c.close()

    def new(who, **v):
        r = client.post("/api/custom/ps_trip/records", headers=hs[who], json={"values": v})
        assert r.status_code == 200, r.text
        return r.json()
    a = new("ps_emp", dest="台北")
    assert a["data"]["dept"] == org["dept"] and a["data"]["dest"] == "台北"
    b = new("ps_emp")                                                       # 沒填 ⇒ 帶上一張
    assert b["data"]["dest"] == "台北"
    other = new("ps_mgr")
    assert "dest" not in other["data"] or other["data"]["dest"] in (None, "")
    # 更新不重算：再讀同一張，值不變
    got = client.get("/api/custom/ps_trip/records/%s" % a["record_no"], headers=hs["ps_emp"]).json()
    assert got["data"]["dept"] == org["dept"]


# ── days_between（公式）──────────────────────────────────────────────────────

def _days(a, b):
    return F.evaluate("days_between(a, b)", {"a": a, "b": b})


def test_days_between_is_end_minus_start_exclusive_of_the_start_day():
    assert _days("2026-10-01", "2026-10-01") == 0               # 同一天＝0（要含頭尾請加 1）
    assert _days("2026-10-01", "2026-10-02") == 1
    assert _days("2026-10-02", "2026-10-01") == -1              # 迄早於起＝負數
    assert F.evaluate("days_between(a, b) + 1", {"a": "2026-10-01", "b": "2026-10-03"}) == 3


def test_days_between_month_year_and_leap_boundaries():
    assert _days("2026-01-31", "2026-02-01") == 1
    assert _days("2026-02-28", "2026-03-01") == 1               # 2026 不是閏年
    assert _days("2028-02-28", "2028-03-01") == 2               # 2028 閏年
    assert _days("2026-12-31", "2027-01-01") == 1
    assert _days("2026-09-30", "2026-10-01") == 1
    assert _days("2026-01-01", "2026-12-31") == 364


def test_days_between_ignores_a_time_suffix_and_blank_is_none():
    assert _days("2026-10-01T23:59", "2026-10-02T00:01") == 1       # 只看日期（YYYY-MM-DD 前 10 字）
    assert _days("", "2026-10-02") is None and _days("2026-10-01", None) is None


def test_days_between_bad_input_is_reported_not_crashed():
    for bad in ("2026-13-01", "2026-02-30", "昨天", "20261001"):
        with pytest.raises(F.FormulaError):
            _days(bad, "2026-10-02")
    assert F.check("days_between(a)", ["a", "b"]) and F.check("days_between(a, b, a)", ["a", "b"])      # 參數個數


def test_designer_formula_shapes_pass_check_with_matching_types():
    fields = ["a", "b", "c", "t"]                       # 明細表欄位 t 本身也是可引用的 key（custom_modules 傳入的 keys 含它）
    tables = {"t": ["c"]}
    for expr in ('total(t, "c")', "a + b", "a * b", "a - b", "round_half_up(a * 0.05)", "round_half_up(a * 1.05)",
                 "round_half_up(a - a / 1.05)", "round_half_up(a * 30 / 100)", "days_between(a, b)"):
        assert F.check(expr, fields, tables) == [], expr
