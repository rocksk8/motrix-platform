# -*- coding: utf-8 -*-
"""S1（設定中心可編輯）後端邏輯測試（單檔、無瀏覽器）。S1-3：`impact_scope` 欄位、橫幅產生、新群組守門。"""
import pytest

from helpers import settings_groups  # noqa: F401  登錄群組
from helpers import settings_registry as R

SCOPE = {"documents": ["已回簽的擇一報價單"], "roles": ["業務", "財務"], "amounts": "已開立的憑據與報價金額可能不一致",
         "reversible": True, "effective": "immediate"}


def _f(**kw):
    base = dict(question="這項要不要開？", label="測試項目", help="測試用的設定項目。", impact="影響測試用的畫面。")
    base.update(kw)
    return R.SettingDef("t_field", base.pop("type", "int"), base.pop("default", 0), **base)


# --- impact_scope 結構驗證 ---------------------------------------------------------------------

def test_impact_scope_is_optional_and_exposed_in_meta():
    assert _f().impact_scope is None and _f().meta()["impactScope"] is None
    f = _f(risk="money", risk_text="金額可能不一致。", impact_scope=SCOPE)
    assert f.meta()["impactScope"] == SCOPE


@pytest.mark.parametrize("bad", [
    {"documents": ["單據"], "roles": ["業務"], "amounts": "金額", "reversible": True},                       # 缺 effective
    dict(SCOPE, extra="x"),                                                                                  # 多餘鍵
    dict(SCOPE, documents="已回簽的擇一報價單"),                                                              # 不是清單
    dict(SCOPE, roles=["sales"]),                                                                            # 不是繁中白話
    dict(SCOPE, amounts="amount"),
    dict(SCOPE, reversible="yes"),
    dict(SCOPE, effective="later"),
    "文字",
])
def test_impact_scope_bad_structure_is_refused_at_definition(bad):
    with pytest.raises(ValueError):
        _f(risk="money", risk_text="金額可能不一致。", impact_scope=bad)


def test_impact_scope_effective_must_match_the_pending_flags():
    with pytest.raises(ValueError):                                   # 宣告 pending 但欄位不是待生效／放寬
        _f(risk="money", risk_text="金額可能不一致。", impact_scope=dict(SCOPE, effective="pending"))
    with pytest.raises(ValueError):                                   # 欄位是放寬，卻宣告立即生效
        _f(risk="money", risk_text="金額可能不一致。", loosen="up", impact_scope=SCOPE)
    assert _f(risk="money", risk_text="金額可能不一致。", loosen="up", impact_scope=dict(SCOPE, effective="pending")).impact_scope["effective"] == "pending"
    assert _f(risk="money", risk_text="金額可能不一致。", requires_pending=True, impact_scope=dict(SCOPE, effective="pending")).impact_scope


# --- 橫幅 --------------------------------------------------------------------------------------

def test_banner_levels_and_conditions():
    amber = _f(risk="money", risk_text="金額可能不一致。", loosen="up", min=0, max=10, impact_scope=dict(SCOPE, effective="pending"))
    b = R.banner_of(amber, 5, days=7)
    assert b["level"] == "amber" and b["fallback"] is False and len(b["lines"]) == 3
    assert "已回簽的擇一報價單" in b["lines"][0] and "業務、財務" in b["lines"][1]
    assert "可以復原" in b["lines"][2] and "7 天確認期間" in b["lines"][2] and "另一位最高管理者核准" in b["lines"][2]
    assert R.banner_of(amber, 0) is None                              # 預設值不顯示
    tighter = _f(risk="money", risk_text="金額可能不一致。", loosen="up", default=5, min=0, max=10, impact_scope=dict(SCOPE, effective="pending"))
    assert R.banner_of(tighter, 2) is None                            # 往收緊方向不顯示
    assert R.banner_of(tighter, 8)["level"] == "amber"                # 往放寬方向才顯示
    sec = _f(risk="security", risk_text="可能讓外人看到資料。", impact_scope=SCOPE)
    assert R.banner_of(sec, 1)["level"] == "red" and "儲存後立即生效" in R.banner_of(sec, 1)["lines"][2]
    irrev = _f(risk="money", risk_text="金額可能不一致。", impact_scope=dict(SCOPE, reversible=False))
    b = R.banner_of(irrev, 1)
    assert b["level"] == "red" and "無法復原" in b["lines"][2]
    assert R.banner_of(_f(risk="ops", impact_scope=None), 1) is None and R.banner_of(_f(risk="none"), 1) is None


def test_banner_without_impact_scope_degrades_to_impact_and_risk_text():
    f = _f(risk="legal", risk_text="縮短後舊紀錄無法找回。", requires_pending=True, impact="超過天數的紀錄會被刪除。")
    b = R.banner_of(f, 1, days=3)
    assert b["fallback"] is True and b["level"] == "red"
    assert b["lines"][0] == "超過天數的紀錄會被刪除。" and "縮短後舊紀錄無法找回" in b["lines"][1] and "3 天" in b["lines"][2]


def test_banner_text_has_no_internal_codes():
    f = _f(risk="security", risk_text="可能讓外人看到資料。", impact_scope=SCOPE)
    text = "".join(R.banner_of(f, 1)["lines"])
    assert "t_field" not in text and "security" not in text and "immediate" not in text


# --- E-f：choices 值域規則 ---------------------------------------------------------------------

def _pick(**kw):
    return R.SettingDef("pick", "int", 1, min=1, max=3, question="選哪一個？", label="選項", help="測試用的選項欄位。", impact="影響測試用的畫面。",
                        choices=[(1, "選項甲", "選甲的影響。"), (2, "選項乙", "選乙的影響。"), (3, "選項丙", "選丙的影響。")], **kw)


def test_choices_are_a_value_domain_not_just_display():
    f = _pick()
    assert [f.check(v) for v in (1, 2, 3)] == ["", "", ""] and f.check(1.0) == ""
    assert f.check(4)                                                # min/max 之外
    g = R.SettingDef("pick2", "int", 1, min=1, max=5, question="選哪一個？", label="選項", help="測試用的選項欄位。", impact="影響測試用的畫面。",
                     choices=[(1, "選項甲", "選甲的影響。"), (3, "選項丙", "選丙的影響。")])
    assert g.check(3) == "" and g.check(2) == "不是可選的選項" and g.check(5) == "不是可選的選項"   # 在範圍內但不是選項
    with pytest.raises(ValueError):                                   # 預設值自己就要是選項
        R.SettingDef("pick3", "int", 2, min=1, max=5, question="選哪一個？", label="選項", help="測試用的選項欄位。", impact="影響測試用的畫面。",
                     choices=[(1, "選項甲", "選甲的影響。"), (3, "選項丙", "選丙的影響。")])
    s = R.SettingDef("mode", "str", "a", question="選哪一個？", label="選項", help="測試用的選項欄位。", impact="影響測試用的畫面。",
                     choices=[("a", "選項甲", "選甲的影響。"), ("b", "選項乙", "選乙的影響。")])
    assert s.check("b") == "" and s.check("zzz") == "不是可選的選項"        # str＋choices 以前會接受任何字串


def test_non_choice_value_is_refused_on_write_and_defaulted_on_read(client, monkeypatch):
    from db import get_db
    R.register_group("zz_s1_choice", "選項測試群組", [_pick()], help="測試用的選項群組。")
    try:
        assert R.validate_values("zz_s1_choice", {"pick": 2}, partial=True) == []
        problems = R.validate_values("zz_s1_choice", {"pick": 9}, partial=True)
        assert problems and problems[0]["path"] == "pick"
        with pytest.raises(R.SettingError):
            R.publish("zz_s1_choice", {"pick": 9}, reason="測試", user="t")
        c = get_db()
        try:
            monkeypatch.setattr(R, "_stored", lambda conn, group: {"pick": 9})          # 庫內被竄改成未知代碼
            assert R._effective(c, "zz_s1_choice")["pick"] == 1                          # 讀取回預設，不丟例外、不放行
        finally:
            c.close()
    finally:
        R._GROUPS.pop("zz_s1_choice", None)
        R.invalidate()


# --- 守門：新群組的高風險欄位必須宣告 impact_scope --------------------------------------------------

def test_new_groups_with_high_risk_fields_declare_impact_scope():
    """E-e 之前登錄的群組暫免（名單固定、不得新增）；之後任何新群組含 money／legal／security 欄位就必須有 `impact_scope`。"""
    missing = []
    for g, meta in R.groups().items():
        for f in meta["fields"]:
            if R.RISK_ORDER.index(f["risk"]) >= R.RISK_ORDER.index("money") and not f["impactScope"] and g not in R.IMPACT_SCOPE_GRANDFATHERED:
                missing.append("%s.%s" % (g, f["key"]))
    assert missing == [], "新登錄的高風險設定缺少 impact_scope：%s" % "、".join(missing)


def test_grandfather_list_is_frozen():
    assert R.IMPACT_SCOPE_GRANDFATHERED == frozenset({"change_control", "retention", "uploads", "system_hub", "completion_note", "quote_alt", "material_order"})

# ===================================================================================================
# S1-4：plan()／preview、impact、reset、欄位畫面資料（API 層）
# ===================================================================================================
import time as _time

from db import get_db as _get_db


def _hdr(client, make_user, name, role="superadmin"):
    username, password = make_user(username=name, role=role)
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _counts(c):
    return (c.execute("SELECT COUNT(*) FROM config_changes").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM ui_definitions WHERE kind=?", (R.KIND,)).fetchone()[0])


def test_preview_classifies_without_writing_and_matches_the_real_save(client, make_user):
    h = _hdr(client, make_user, "s14_a")
    make_user(username="s14_b", role="superadmin")                        # 有第二位最高管理者 ⇒ 放寬需核准
    c = _get_db()
    try:
        before = _counts(c)
        vals = {"local_db_keep_days": 40, "audit_log_keep_days": 400, "cloud_daily_keep_days": 60}   # 延長／縮短（放寬）／同值
        p = client.post("/api/settings-center/groups/retention/preview", json={"values": vals}, headers=h)
        assert p.status_code == 200 and p.json()["ok"] is True
        kinds = {x["field"]: x["kind"] for x in p.json()["fields"]}
        assert kinds == {"local_db_keep_days": "immediate", "audit_log_keep_days": "pending_approval", "cloud_daily_keep_days": "unchanged"}
        assert _counts(c) == before                                        # 預覽什麼都沒寫
        assert p.json()["confirmDays"] == 7 and p.json()["otherSuperadmins"] >= 1
        row = {x["field"]: x for x in p.json()["fields"]}["audit_log_keep_days"]
        assert row["approvalsRequired"] == 1 and row["effectiveAt"] and "核准" in row["effect"] and "7 天" in row["effect"]
        assert row["banner"] and row["banner"]["level"] == "red" and row["banner"]["fallback"] is True      # legal 欄位、尚未宣告 impact_scope ⇒ 降級橫幅
        # 真的儲存：分類逐欄相同（共用同一個分類函式）
        s = client.post("/api/settings-center/groups/retention", json={"values": vals, "reason": "測試"}, headers=h)
        assert s.status_code == 200
        assert {x["field"]: x["kind"] for x in s.json()["classification"]} == kinds
        assert len(s.json()["pending"]) == 1 and s.json()["pending"][0]["approvalsRequired"] == 1
    finally:
        c.close()


def test_preview_with_a_single_superadmin_warns_and_does_not_require_approval(client, make_user):
    c = _get_db()
    try:
        c.execute("UPDATE users SET active=0 WHERE role='superadmin'")
        c.commit()
    finally:
        c.close()
    h = _hdr(client, make_user, "s14_only")
    p = client.post("/api/settings-center/groups/retention/preview", json={"values": {"audit_log_keep_days": 400}}, headers=h).json()
    assert p["fields"][0]["kind"] == "pending" and p["fields"][0]["approvalsRequired"] == 0 and p["warnings"]


def test_preview_reports_validation_problems_and_unknown_fields(client, make_user):
    h = _hdr(client, make_user, "s14_c")
    r = client.post("/api/settings-center/groups/retention/preview", json={"values": {"audit_log_keep_days": 100}}, headers=h)
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["problems"] and r.json()["fields"] == []
    r = client.post("/api/settings-center/groups/retention/preview", json={"values": {"nope": 1}}, headers=h)
    assert r.json()["ok"] is False
    assert client.post("/api/settings-center/groups/retention/preview", json={"values": {}}, headers=h).status_code == 400
    assert client.post("/api/settings-center/groups/zz_nope/preview", json={"values": {"a": 1}}, headers=h).status_code == 404


def test_new_endpoints_are_superadmin_only(client, make_user):
    h = _hdr(client, make_user, "s14_admin", role="admin")
    assert client.post("/api/settings-center/groups/retention/preview", json={"values": {"local_db_keep_days": 40}}, headers=h).status_code == 403
    assert client.post("/api/settings-center/groups/retention/impact", json={"field": "local_db_keep_days", "value": 40}, headers=h).status_code == 403
    assert client.post("/api/settings-center/groups/retention/reset", json={"fields": ["local_db_keep_days"], "reason": "x"}, headers=h).status_code == 403


def test_group_detail_carries_field_views_with_banners_and_plain_values(client, make_user):
    h = _hdr(client, make_user, "s14_d")
    d = client.get("/api/settings-center/groups/system_hub", headers=h).json()
    f = {x["key"]: x for x in d["fields"]}["show_denied"]
    assert f["isDefault"] is True and f["valueText"] == "隱藏（建議）" and f["defaultText"] == "隱藏（建議）" and f["banner"] is None
    assert set(f["choiceBanners"]) == {"0", "1"} and f["choiceBanners"]["0"] is None
    assert f["choiceBanners"]["1"]["level"] == "red" and len(f["choiceBanners"]["1"]["lines"]) >= 2
    r = {x["key"]: x for x in client.get("/api/settings-center/groups/retention", headers=h).json()["fields"]}["audit_log_keep_days"]
    assert r["valueText"] == "1825 天" and r["impactScope"] is None and r["choiceBanners"] is None


def test_reset_returns_fields_to_defaults_through_the_same_controls(client, make_user):
    h = _hdr(client, make_user, "s14_e")
    make_user(username="s14_f", role="superadmin")
    assert client.post("/api/settings-center/groups/retention", json={"values": {"local_db_keep_days": 40, "audit_log_keep_days": 3000}, "reason": "測試"}, headers=h).status_code == 200
    r = client.post("/api/settings-center/groups/retention/reset", json={"fields": ["local_db_keep_days", "audit_log_keep_days"], "reason": "還原預設"}, headers=h)
    assert r.status_code == 200
    kinds = {x["field"]: x["kind"] for x in r.json()["classification"]}
    assert kinds == {"local_db_keep_days": "pending_approval", "audit_log_keep_days": "pending_approval"}   # 兩者回預設都是縮短＝放寬：需另一位最高管理者核准，不立即生效
    assert client.post("/api/settings-center/groups/retention/reset", json={"fields": ["local_db_keep_days"], "reason": ""}, headers=h).status_code == 400
    assert client.post("/api/settings-center/groups/retention/reset", json={"fields": ["nope"], "reason": "x"}, headers=h).status_code == 400
    assert client.post("/api/settings-center/groups/retention/reset", json={"fields": [], "reason": "x"}, headers=h).status_code == 400


# --- 即時影響 ----------------------------------------------------------------------------------------

@pytest.fixture()
def impact_group(client):
    calls = {"n": 0, "mode": "ok"}

    def fn(conn, new):
        calls["n"] += 1
        if calls["mode"] == "boom":
            raise RuntimeError("down")
        if calls["mode"] == "slow":
            _time.sleep(1.0)
        if calls["mode"] == "write":
            conn.execute("INSERT INTO notifications (username, type, message, created_at) VALUES ('x','info','寫入測試','2026-01-01T00:00:00')")
        return {"numbers": {"n": int(new)}, "sentence": "目前有 %d 筆資料會受影響" % int(new)}
    R.register_group("zz_s14_impact", "影響測試群組", [
        R.SettingDef("cap", "int", 1, min=0, max=50, question="上限要設多少？", label="上限", help="測試用的上限。", impact="影響測試用的畫面。", impact_fn=fn)],
        help="測試用的影響群組。")
    R.invalidate()
    R._IMPACT_CACHE.clear()
    yield calls
    R._GROUPS.pop("zz_s14_impact", None)
    R._IMPACT_CACHE.clear()
    R.invalidate()


def test_live_impact_is_cached_read_only_and_fails_soft(client, make_user, impact_group, monkeypatch):
    h = _hdr(client, make_user, "s14_g")
    url = "/api/settings-center/groups/zz_s14_impact/impact"
    r = client.post(url, json={"field": "cap", "value": 7}, headers=h).json()
    assert r["live"]["sentence"] == "目前有 7 筆資料會受影響" and r["static"] == "影響測試用的畫面。"
    client.post(url, json={"field": "cap", "value": 7}, headers=h)
    assert impact_group["n"] == 1                                              # 60 秒快取：同值只算一次
    impact_group["mode"] = "boom"
    r = client.post(url, json={"field": "cap", "value": 8}, headers=h).json()
    assert r["live"] is None and r["static"]                                   # 失敗只回靜態
    impact_group["mode"] = "write"
    r = client.post(url, json={"field": "cap", "value": 9}, headers=h).json()
    assert r["live"] is None                                                   # 唯讀連線：想寫就失敗
    c = _get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM notifications WHERE message='寫入測試'").fetchone()[0] == 0
    finally:
        c.close()
    impact_group["mode"] = "slow"
    monkeypatch.setattr(R, "_IMPACT_TIMEOUT", 0.2)
    t0 = _time.monotonic()
    r = client.post(url, json={"field": "cap", "value": 10}, headers=h).json()
    assert r["live"] is None and _time.monotonic() - t0 < 0.9                  # 逾時不等
    assert client.post(url, json={"field": "cap", "value": 999}, headers=h).json()["live"] is None      # 值不合法 ⇒ 不呼叫
    assert client.post(url, json={"field": "nope", "value": 1}, headers=h).status_code == 404
    r = client.post("/api/settings-center/groups/retention/impact", json={"field": "local_db_keep_days", "value": 40}, headers=h).json()
    assert r["live"] is None and r["static"]                                   # 沒有 impact_fn ⇒ 只有靜態
