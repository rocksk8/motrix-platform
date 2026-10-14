# -*- coding: utf-8 -*-
"""BP-2 R1：欄位目錄轉接層、規則集定義種類、設定群組。
- 目錄：付款衍生旗標進不來（附正對照）；金額／內部欄位必須帶權限；逐角色可見集合（sales 看得到金額、engineer／viewer 看不到）
- 提供者：沒有提供者 ⇒ None；提供者多給的欄位會被裁掉（縱深防禦）；筆數上限
- 懶登記：匯入 helpers.rule_sets 不登記 `rule_set`（旗標關時 /api/definition-kinds 與今天相同）；ensure_registered 之後驗證器生效
- 設定：builder_rules.enabled 預設 0；builder_governance.enforce_rule_set 是 loosen=down、建議值 1
- TEMP stub 的移除提醒：S5 欄位目錄（helpers/builtin_fields.py）一出現，這裡就會失敗，要求改接 S5 並移除 stub"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from core import definitions as D
from core import registry
from helpers import rule_catalog as C
from helpers import rule_sets as RS

BACKEND = Path(__file__).resolve().parents[1]


def u(role):
    return {"id": 1, "username": "t_" + role, "role": role}


# ── 目錄 ───────────────────────────────────────────────────────────────────────
def test_stub_catalog_is_well_formed_and_marked_temp():
    ids = C.all_fields("case")
    assert {"netMarginPct", "total", "status"} <= set(ids)
    assert C.stub_in_use() is True
    assert ids["netMarginPct"]["money"] and ids["netMarginPct"]["internal"] and ids["netMarginPct"]["perm"] == "quote_money"
    assert C.all_fields("nope") == {}


def test_temp_stub_is_removed_once_s5_lands():
    """S5 欄位目錄（wip/t61-s5-impl-r4，owner 3c）合併後 helpers/builtin_fields.py 會出現。
    出現時這題會失敗＝提醒：請把 rule_catalog._catalog_for 改接 S5 的目錄、刪除 _TEMP_STUB 與本題（並與 3c 對齊欄位代號）。"""
    assert importlib.util.find_spec("helpers.builtin_fields") is None, \
        "S5 已合併：請移除 rule_catalog._TEMP_STUB，改由 S5 目錄提供內建欄位，再刪除這個提醒測試"


def test_payment_derived_fields_cannot_enter_the_catalog_positive_control():
    bad = [C._f("overdueReceivable", "逾期應收", "bool")]
    with pytest.raises(ValueError):
        C._check_catalog("case", bad)
    with pytest.raises(ValueError):
        C._check_catalog("case", [dict(C._f("x_flag", "旗標", "bool"), derived_from_payment=True)])
    C._check_catalog("case", [C._f("x_flag", "旗標", "bool")])                      # 對照：沒有衍生標記的正常欄位通過


def test_money_fields_must_carry_a_permission():
    with pytest.raises(ValueError):
        C._check_catalog("case", [C._f("cost", "成本", "number", money=True)])
    C._check_catalog("case", [C._f("memo", "內部備註", "text", internal=True)])          # internal 單獨成立：能讀到紀錄的人才看得到（S5 自訂欄位）
    with pytest.raises(ValueError):
        C._check_catalog("case", [C._f("a", "A", "number"), C._f("a", "B", "number")])      # 代號重複
    with pytest.raises(ValueError):
        C._check_catalog("case", [C._f("a", "A", "weird")])


def test_every_catalog_entry_in_every_entity_passes_the_static_rules():
    for e in C.ENTITIES:
        C._check_catalog(e, C._catalog_for(e))
        for f in C._catalog_for(e):
            assert f["id"] not in C._PAYMENT_DERIVED and not f.get("derived_from_payment")


@pytest.mark.parametrize("role,sees_money", [("superadmin", True), ("admin", True), ("sales", True), ("engineer", False), ("viewer", False)])
def test_visible_fields_follow_the_viewers_money_permission(role, sees_money, monkeypatch):
    monkeypatch.setattr("helpers.auth.finance_duty_person", lambda user: False)
    vis = C.visible_ids("case", u(role))
    assert ("netMarginPct" in vis) is sees_money and ("total" in vis) is sees_money
    assert "status" in vis                                                          # 非金額欄位人人看得到
    assert {f["id"] for f in C.rule_fields("case", u(role))} == set(vis)             # 編輯器下拉只列看得到的欄位


def test_rule_fields_carry_the_allowed_operators():
    f = next(x for x in C.rule_fields("case", u("superadmin")) if x["id"] == "netMarginPct")
    assert f["type"] == "number" and "lt" in f["ops"] and "between" in f["ops"] and f["unit"] == "%"


# ── 提供者與裁剪 ───────────────────────────────────────────────────────────────
def test_no_provider_means_none(monkeypatch):
    monkeypatch.setattr(registry, "providers", lambda cap: {})
    assert C.load_records("case", u("superadmin"), None) is None


def test_provider_values_are_trimmed_to_the_viewers_visible_fields(monkeypatch):
    monkeypatch.setattr("helpers.auth.finance_duty_person", lambda user: False)
    seen = {}

    def provider(conn, user, ids, limit, fields=None):
        seen.update(ids=ids, limit=limit, fields=fields)
        return [{"id": "Q1", "label": "甲案", "values": {"netMarginPct": 3, "total": 100, "status": "草稿", "secretColumn": 1}}] * 3
    monkeypatch.setattr(registry, "providers", lambda cap: {"case": provider} if cap == "rules.entity" else {})
    rows = C.load_records("case", u("engineer"), None, ids=["Q1"], limit=99999)
    assert seen == {"ids": ["Q1"], "limit": 1000, "fields": None} and len(rows) == 3
    C.load_records("case", u("engineer"), None, fields={"status", "total"})
    assert seen["fields"] == frozenset({"status", "total"})                            # 呼叫端需要的欄位集合原樣傳給提供者
    assert rows[0]["values"] == {"status": "草稿"}                                    # 成本／總額／未登錄欄位都被裁掉
    assert C.load_records("case", u("sales"), None)[0]["values"] == {"netMarginPct": 3, "total": 100, "status": "草稿"}


def test_provider_garbage_rows_are_dropped(monkeypatch):
    monkeypatch.setattr(registry, "providers", lambda cap: {"case": lambda *a: [None, {"id": 1}, {"values": {}}, {"id": 2, "values": {"status": "x"}}]})
    assert [r["id"] for r in C.load_records("case", u("superadmin"), None)] == [2]


# ── 規則集定義種類 ─────────────────────────────────────────────────────────────
def test_importing_rule_sets_does_not_register_the_kind():
    """旗標關時 /api/definition-kinds 要與今天相同 ⇒ 匯入不得登記（在乾淨的子行程驗證）。"""
    code = "import helpers.rule_sets as r; from core import definitions as D; print('rule_set' in D.kinds())"
    out = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); %s" % (str(BACKEND), code)],
                         capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=str(BACKEND))
    assert out.stdout.strip() == "False", out.stderr


def test_ensure_registered_enables_the_validator_and_default(monkeypatch):
    RS.ensure_registered()
    RS.ensure_registered()                                                           # 可重複呼叫
    assert RS.KIND in D.kinds()
    assert D.validate(RS.KIND, "case", {"rules": []}) == []
    assert D.validate(RS.KIND, "nope", {"rules": []})                                # 未知主題
    bad = {"rules": [{"id": "x1", "name": "n", "when": {"op": "lt", "field": "nope", "value": 1}, "mark": {"level": "red", "text": "t"}}]}
    assert D.validate(RS.KIND, "case", bad)
    assert D.default_for(RS.KIND, "case") == {"rules": []}


def test_gate_is_hidden_when_the_flag_is_off(monkeypatch):
    monkeypatch.setattr(RS, "enabled", lambda conn=None: False)
    assert RS._gate("case") == "hidden"
    monkeypatch.setattr(RS, "enabled", lambda conn=None: True)
    assert RS._gate("case") == "open"


def test_published_rules_degrades_to_empty(client, monkeypatch):
    import db
    RS.ensure_registered()
    conn = db.get_db()
    try:
        assert RS.published_rules(conn, "case") == []
        monkeypatch.setattr(RS.D, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert RS.published_rules(conn, "case") == []                                # 讀不到 ⇒ 沒有規則，不丟例外
    finally:
        conn.close()


# ── 設定 ───────────────────────────────────────────────────────────────────────
def test_settings_defaults_and_loosen_direction(client):
    from helpers import settings_registry as SR
    assert SR.get("builder_rules", "enabled") == 0
    assert SR.get("builder_governance", "enforce_rule_set") == 0
    f = SR._g("builder_governance")["fields"]["enforce_rule_set"]
    assert f.loosen == "down" and f.recommended == 1


def test_catalog_s5_custom_fields_enter_as_internal_cf_ids_and_disabled_ones_are_absent(monkeypatch):
    import types
    fake = types.ModuleType("helpers.builtin_fields")
    fake.public_fields = lambda rt, conn=None: [{"key": "site", "label": "工地", "type": "text"}, {"key": "lvl", "label": "等級", "type": "select", "options": ["A", "B"]},
                                                 {"key": "ok", "label": "已確認", "type": "checkbox"}, {"key": "d", "label": "日期", "type": "date"}] if rt == "case_info" else []
    monkeypatch.setitem(sys.modules, "helpers.builtin_fields", fake)
    f = C.all_fields("case")
    assert {k: f[k]["type"] for k in ("cf_site", "cf_lvl", "cf_ok", "cf_d")} == {"cf_site": "text", "cf_lvl": "enum", "cf_ok": "bool", "cf_d": "date"}
    assert all(f[k]["internal"] and f[k]["perm"] is None and not f[k]["money"] for k in ("cf_site", "cf_lvl"))
    assert f["cf_lvl"]["options"] == ["A", "B"]
    fake.public_fields = lambda rt, conn=None: []                                      # 欄位被停用 ⇒ 目錄裡沒有 ⇒ 引用它的已發布規則不評估（不當成故障）
    assert "cf_site" not in C.all_fields("case")
