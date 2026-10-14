# -*- coding: utf-8 -*-
"""BP-2 K01：專案毛利提醒作為種子規則（設計 docs/platform/plans/BP2-K01-SEED-T62.md；旗標 builder_rules.k01_seed 預設關）。
- 等價性：對一大組（門檻、稅前、成本）格子，『今天的判定』（門檻>0 且 專案毛利% 不是 None 且 < 門檻）與『種子規則經規則引擎的判定』逐格相同
  （含 pct 為 None、虧損、剛好等於門檻、門檻 0 ＝停用）；突變正對照：把規則的 lt 改成 le ⇒ 恰好等於門檻那一格會翻面
- 種子規則通過同一份驗證器；停用規則代表『不提醒』；標示位置只有表單（surfaces），列表疊加層不會出現它
- k01_warn_pct：旗標關／規則還沒發布／形狀不對 ⇒ None（沿用設定中心的值）；已發布且啟用 ⇒ 門檻；已發布但停用 ⇒ 0
- 旗標關：config 端點的回應與今天逐位元相同（走設定中心的值）；旗標開且規則已發布 ⇒ 以規則為準
- 種子路由：只寫草稿、不發布；重複匯入 409；旗標關 404"""
import itertools
import json

import pytest

import db
from helpers import profit_rules as PR
from helpers import rule_engine as E
from helpers import rule_grammar as G
from helpers import rule_sets as RS

FIELDS = {"projectMarginPct": {"type": "number"}}


def legacy_warn(warn, pct):
    """今天 quotation-form.html::projectMarginWarn() 的判定。"""
    return float(warn or 0) > 0 and pct is not None and pct < float(warn)


def via_rule(rule, pct):
    out = E.evaluate([rule], [{"id": "x", "values": {"projectMarginPct": pct}}], {"projectMarginPct"}, surface="form")
    return "x" in out["marks"]


GRID = list(itertools.product([0, 15, 20, 20.5, 33.3, 100], [None, 0, 10, 15, 19.9, 20, 20.5, 33.3, 50, -5]))


@pytest.mark.parametrize("warn,pct", GRID)
def test_seed_rule_reproduces_todays_decision(warn, pct):
    assert via_rule(RS.k01_seed_rule(warn), pct) == legacy_warn(warn, pct)


def test_the_equivalence_test_is_sensitive_mutation_control():
    rule = RS.k01_seed_rule(20)
    rule["when"]["op"] = "le"                                                                   # 方向／邊界寫錯
    assert via_rule(rule, 20) is True and legacy_warn(20, 20) is False


def test_pct_none_comes_from_the_real_project_margin_function():
    assert PR.project_margin(0, 5)["pct"] is None and PR.project_margin(None, 5)["pct"] is None
    assert legacy_warn(20, PR.project_margin(0, 5)["pct"]) is False                           # 沒有未稅收入 ⇒ 不提醒
    assert via_rule(RS.k01_seed_rule(20), PR.project_margin(0, 5)["pct"]) is False
    assert via_rule(RS.k01_seed_rule(20), PR.project_margin(100, 90)["pct"]) is True           # 10% < 20%


def test_seed_rule_is_valid_form_only_and_disabled_when_the_threshold_is_zero():
    r = RS.k01_seed_rule(20)
    assert G.validate_rule_set({"rules": [r]}, FIELDS) == [] and r["surfaces"] == ["form"] and r["enabled"] is True
    off = RS.k01_seed_rule(0)
    assert off["enabled"] is False and G.validate_rule_set({"rules": [off]}, FIELDS) == []
    assert RS.k01_seed_rule("bad")["enabled"] is False and RS.k01_seed_rule(None)["enabled"] is False
    assert RS.k01_seed_rule(20.5)["when"]["value"] == 20.5 and RS.k01_seed_rule(20.0)["when"]["value"] == 20


def test_surfaces_validation_and_filtering():
    r = RS.k01_seed_rule(20)
    for bad in ([], ["x"], ["form", "form"], "form", ["list", "form", "list"]):
        assert G.validate_rule_set({"rules": [dict(r, surfaces=bad)]}, FIELDS), bad
    assert G.validate_rule_set({"rules": [dict(r, surfaces=["list", "form"])]}, FIELDS) == []
    rec = [{"id": "x", "values": {"projectMarginPct": 1}}]
    vis = {"projectMarginPct"}
    assert "x" in E.evaluate([r], rec, vis, surface="form")["marks"]
    assert E.evaluate([r], rec, vis, surface="list")["marks"] == {}                             # 列表疊加層（預設 surface）看不到它
    assert E.evaluate([r], rec, vis)["marks"] != {}                                             # 沒指定 surface（預覽／統計）＝全部規則
    plain = {k: v for k, v in r.items() if k != "surfaces"}
    assert "x" in E.evaluate([plain], rec, vis, surface="list")["marks"] and E.evaluate([plain], rec, vis, surface="form")["marks"] == {}   # 沒寫 surfaces ＝ 只在列表


def test_seed_k01_warn_pct_semantics(monkeypatch):
    monkeypatch.setattr(RS, "k01_seed_on", lambda conn=None: True)

    def pub(rules):
        monkeypatch.setattr(RS, "published_rules", lambda conn, entity: rules)
    pub([])
    assert RS.k01_warn_pct(conn=object()) is None                                               # 還沒發布 ⇒ 沿用設定中心
    pub([RS.k01_seed_rule(25)])
    assert RS.k01_warn_pct(conn=object()) == 25.0
    pub([dict(RS.k01_seed_rule(25), enabled=False)])
    assert RS.k01_warn_pct(conn=object()) == 0.0                                                # 規則停用 ⇒ 不提醒
    odd = RS.k01_seed_rule(25)
    odd["when"] = {"op": "gt", "field": "projectMarginPct", "value": 1}
    pub([odd])
    assert RS.k01_warn_pct(conn=object()) is None                                               # 形狀被改成別的 ⇒ 不當門檻
    monkeypatch.setattr(RS, "k01_seed_on", lambda conn=None: False)
    pub([RS.k01_seed_rule(25)])
    assert RS.k01_warn_pct(conn=object()) is None                                               # 種子旗標關 ⇒ 一律 None


def test_seed_k01_warn_pct_never_raises(monkeypatch):
    monkeypatch.setattr(RS, "k01_seed_on", lambda conn=None: True)
    monkeypatch.setattr(RS, "published_rules", lambda conn, entity: (_ for _ in ()).throw(RuntimeError("boom")))
    assert RS.k01_warn_pct(conn=object()) is None


# ── 端點（需要資料庫） ─────────────────────────────────────────────────────────
@pytest.fixture()
def sa(client, make_user):
    u, p = make_user(username="t62k_sa", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _set(group, values):
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish(group, values, reason="t62", user="t62", conn=c)
        c.commit()
    finally:
        c.close()



# 端點在 warnPct 之外多回三個報價送審門檻（approval-thresholds r1/r2，預設＝今天寫死的 30%／30 天／0 元；同一個金額權限閘門，沒有任何金額）。
# 這些測試關心的是 warnPct 怎麼跟著 K01 規則走，所以其餘三個鍵固定成預設值一起比對（預設改了這裡會紅）。
def _cfg(warn):
    return {"warnPct": float(warn), "minItemMarginPct": 30.0, "maxValidDays": 30, "discountReviewAbove": 0}

def test_config_endpoint_flag_off_is_todays_response(client, sa):
    _set("project_margin", {"warn_pct": 18})
    assert client.get("/api/project-margin/config", headers=sa).json() == _cfg(18.0)


def test_seed_route_writes_a_draft_only_and_config_follows_the_published_rule(client, sa):
    _set("project_margin", {"warn_pct": 18})
    for g, v in (("builder_governance", {"enabled": 1}), ("builder_rules", {"enabled": 1, "k01_seed": 1})):
        _set(g, v)
    j = client.post("/api/rules/k01/seed", headers=sa).json()
    assert j["ruleId"] == RS.K01_ID and "草稿" in j["message"]
    assert client.get("/api/project-margin/config", headers=sa).json() == _cfg(18.0)      # 只是草稿：行為不變
    assert client.post("/api/rules/k01/seed", headers=sa).status_code == 409                    # 不重複匯入
    url = "/api/definitions/rule_set/case"
    d = client.get(url, headers=sa).json()["draft"]
    assert [r["id"] for r in d["body"]["rules"]] == [RS.K01_ID] and d["body"]["rules"][0]["when"]["value"] == 18
    pv = client.get("/api/def-governance/rule_set/case/impact", headers=sa).json()["previewHash"]
    assert client.post(url + "/publish", headers=sa, json={"note": "k01", "preview_hash": pv}).status_code == 200
    assert client.get("/api/project-margin/config", headers=sa).json() == _cfg(18.0)      # 種子＝現值 ⇒ 結果相同
    _set("project_margin", {"warn_pct": 40})                                                    # 之後設定中心的數字不再影響
    assert client.get("/api/project-margin/config", headers=sa).json() == _cfg(18.0)
    # 在規則頁調高門檻（收緊 ⇒ 立即生效）
    client.put(url + "/draft", headers=sa, json={"body": {"rules": [RS.k01_seed_rule(30)]}})
    pv = client.get("/api/def-governance/rule_set/case/impact", headers=sa).json()["previewHash"]
    assert client.post(url + "/publish", headers=sa, json={"note": "調高", "preview_hash": pv}).status_code == 200
    assert client.get("/api/project-margin/config", headers=sa).json() == _cfg(30.0)


def test_seed_route_is_hidden_when_the_seed_flag_is_off(client, sa):
    for g, v in (("builder_governance", {"enabled": 1}), ("builder_rules", {"enabled": 1})):
        _set(g, v)
    assert client.post("/api/rules/k01/seed", headers=sa).status_code == 404


def test_seeded_rule_never_shows_on_the_list_overlay(client, sa, monkeypatch):
    from core import registry
    for g, v in (("builder_governance", {"enabled": 1}), ("builder_rules", {"enabled": 1, "k01_seed": 1})):
        _set(g, v)
    url = "/api/definitions/rule_set/case"
    RS.ensure_registered()
    client.put(url + "/draft", headers=sa, json={"body": {"rules": [RS.k01_seed_rule(90)]}})
    pv = client.get("/api/def-governance/rule_set/case/impact", headers=sa).json()["previewHash"]
    assert client.post(url + "/publish", headers=sa, json={"note": "k01", "preview_hash": pv}).status_code == 200
    real = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: dict(real(cap), case=lambda c, u, ids, lim, fields=None: [{"id": "Q", "label": "Q", "values": {"projectMarginPct": 1.0}}]) if cap == "rules.entity" else real(cap))
    assert client.get("/api/rules/marks?entity=case&ids=Q", headers=sa).json()["marks"] == {}                       # 預設 surface=list
    assert client.get("/api/rules/marks?entity=case&ids=Q&surface=form", headers=sa).json()["marks"]               # 表單位置才有
    assert client.get("/api/rules/marks?entity=case&ids=Q&surface=bad", headers=sa).status_code == 400
