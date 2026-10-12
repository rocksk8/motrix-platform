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
