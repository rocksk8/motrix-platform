# -*- coding: utf-8 -*-
"""BP-2 R3：規則集接上治理層（放寬／收緊分類、待核准、預覽雜湊強制、還原）。
- 比較函式：方向由『命中集合變大／變小』決定，不是寫死「調高＝放寬」；每個方向正反各一例；
  **突變控制**：把 lt/gt 的方向互換，分類結果必須翻面（證明測試抓得到方向寫反）
- 無法比較（結構變了、未知運算子、格式壞）＝放寬；第一次發布（新增規則）＝收緊（立即）
- 端到端（真的設定層）：收緊立即生效；放寬回 pending（生效版不變、有 effectiveAt／reasons）；enforce_rule_set 開啟後沒預覽就 409；還原到較窄版本 ⇒ pending"""
import pytest

import db
from routers import def_pipeline as P


def rule(rid="low_margin", when=None, **kw):
    r = {"id": rid, "name": "低毛利", "enabled": True, "mode": "mark", "on_failure": "degrade_loud",
         "when": when or {"op": "lt", "field": "netMarginPct", "value": 15}, "mark": {"level": "red", "text": "毛利偏低", "target": "row"}}
    r.update(kw)
    return r


def b(*rules):
    return {"rules": list(rules)}


def lt(v, op="lt"):
    return rule(when={"op": op, "field": "netMarginPct", "value": v})


def gt(v, op="gt"):
    return rule(when={"op": op, "field": "total", "value": v})


def c(old, new):
    return P.classify("rule_set", old, new)[0]


def test_rule_set_is_an_active_kind():
    assert "rule_set" in P.ACTIVE_KINDS and "rule_set" in P.COMPARATORS


# 『低於 X 就標』：X 調高＝更多標示＝收緊；調低＝放寬。『高於 X 就標』相反。
@pytest.mark.parametrize("old,new,want", [
    (lt(15), lt(20), "tighten"), (lt(15), lt(10), "loosen"), (lt(15), lt(15), "neutral"),
    (gt(100), gt(80), "tighten"), (gt(100), gt(120), "loosen"),
    (lt(15, "lt"), lt(15, "le"), "tighten"), (lt(15, "le"), lt(15, "lt"), "loosen"),
    (gt(100, "gt"), gt(100, "ge"), "tighten"), (gt(100, "ge"), gt(100, "gt"), "loosen"),
])
def test_threshold_direction_is_decided_by_the_operator(old, new, want):
    assert c(b(old), b(new)) == want


def test_between_in_widening_and_narrowing():
    def bt(lo, hi):
        return rule(when={"op": "between", "field": "total", "min": lo, "max": hi})

    def inn(*vs):
        return rule(when={"op": "in", "field": "status", "values": list(vs)})
    assert c(b(bt(10, 20)), b(bt(5, 30))) == "tighten" and c(b(bt(10, 20)), b(bt(12, 18))) == "loosen"
    assert c(b(bt(10, 20)), b(bt(5, 15))) == "loosen"                                           # 一邊擴一邊縮：無法判斷 ⇒ 放寬
    assert c(b(inn("a")), b(inn("a", "b"))) == "tighten" and c(b(inn("a", "b")), b(inn("a"))) == "loosen"


def test_adding_removing_enabling_disabling():
    assert c(b(), b(lt(15))) == "tighten" and c({}, b(lt(15))) == "tighten"                   # 第一次發布＝收緊（立即）
    assert c(b(lt(15)), b()) == "loosen"
    assert c(b(lt(15)), b(dict(lt(15), enabled=False))) == "loosen"
    assert c(b(dict(lt(15), enabled=False)), b(lt(15))) == "tighten"
    assert c(b(dict(lt(15), enabled=False)), b()) == "neutral"                                  # 本來就停用的規則被移除：沒有影響
    assert c(b(dict(lt(15), enabled=False)), b(dict(lt(99), enabled=False))) == "neutral"       # 停用中改條件：沒有影響
    assert c(b(lt(15)), b(dict(lt(15), enabled=False), dict(lt(20), id="other"))) == "loosen"   # 一停用、一新增：有放寬就整體算放寬


def test_level_text_and_name_changes():
    red, yellow = lt(15), dict(lt(15), mark={"level": "yellow", "text": "毛利偏低", "target": "row"})
    assert c(b(red), b(yellow)) == "loosen" and c(b(yellow), b(red)) == "tighten"
    assert c(b(red), b(dict(red, name="改個名"))) == "neutral"                                    # 改名不影響畫面
    assert c(b(red), b(dict(red, mark={"level": "red", "text": "請留意", "target": "row"}))) == "loosen"       # 紅色提示文字改了：意思可能變，視為放寬
    assert c(b(yellow), b(dict(yellow, mark={"level": "yellow", "text": "別的字", "target": "row"}))) == "neutral"   # 非紅色改字：中性
    assert c(b(red), b(dict(red, mark={"level": "red", "text": "毛利偏低", "target": "field", "field": "total"}))) == "loosen"   # 標示位置變了
    assert c(b(red), b(dict(red, surfaces=["form"]))) == "loosen" and c(b(red), b(dict(red, surfaces=["list"]))) == "neutral"


def test_anything_hard_to_compare_counts_as_loosen():
    two = rule(when={"op": "and", "args": [{"op": "lt", "field": "total", "value": 5}, {"op": "gt", "field": "total", "value": 1}]})
    assert c(b(lt(15)), b(two)) == "loosen"                                                     # 結構變了
    assert c(b(two), b(dict(two, when={"op": "or", "args": two["when"]["args"]}))) == "loosen"
    assert c(b(lt(15)), b(rule(when={"op": "eq", "field": "netMarginPct", "value": 3}))) == "loosen"        # 運算子族不同
    assert c(b(lt(15)), b(rule(when={"op": "lt", "field": "total", "value": 99}))) == "loosen"               # 換欄位
    assert c(b(lt(15)), b(dict(lt(15), mode="block"))) == "loosen"
    assert c(b(lt(15)), {"rules": "x"}) == "loosen" and c({"rules": [None]}, b(lt(15))) == "loosen"
    assert c(b(lt(15), lt(16)), b(lt(15))) == "loosen"                                          # 重複代號 ⇒ 格式壞 ⇒ 放寬


def test_mutation_control_swapping_the_direction_flips_the_answers(monkeypatch):
    real = P._num_dir
    assert c(b(lt(15)), b(lt(20))) == "tighten"
    monkeypatch.setattr(P, "_num_dir", lambda op, a, bb: {"wider": "narrower", "narrower": "wider", "same": "same"}[real(op, a, bb)])
    assert c(b(lt(15)), b(lt(20))) == "loosen"                                                  # 方向寫反 ⇒ 結果翻面 ⇒ 上面的參數化題會紅


def test_reasons_name_the_rule():
    cls, reasons = P.classify("rule_set", b(lt(15)), b(lt(10)))
    assert cls == "loosen" and any("低毛利" in r for r in reasons)


# ── 端到端 ─────────────────────────────────────────────────────────────────────
@pytest.fixture()
def sa(client, make_user):
    out = {}
    for n in ("a", "b"):
        u, p = make_user(username="t62g_" + n, role="superadmin")
        out[n] = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    from helpers import settings_registry as SR
    conn = db.get_db()
    try:
        SR.publish("builder_governance", {"enabled": 1}, reason="t62", user="t62", conn=conn)
        SR.publish("builder_rules", {"enabled": 1}, reason="t62", user="t62", conn=conn)
        conn.commit()
    finally:
        conn.close()
    from helpers import rule_sets as RS
    RS.ensure_registered()
    return client, out


URL = "/api/definitions/rule_set/case"


def _pub(c, h, note="n"):
    """規則功能開著時發布一定要帶『看過的預覽』：先取影響預覽的雜湊再發布。"""
    pv = c.get("/api/def-governance/rule_set/case/impact", headers=h)
    assert pv.status_code == 200, pv.text
    return c.post(URL + "/publish", headers=h, json={"note": note, "preview_hash": pv.json()["previewHash"]})


def _save(c, h, *rules):
    r = c.put(URL + "/draft", headers=h, json={"body": b(*rules)})
    assert r.status_code == 200, r.text
    return r.json()


def test_tighten_is_immediate_and_loosen_is_pending(sa):
    c, h = sa
    _save(c, h["a"], lt(15))
    r = _pub(c, h["a"], "初版")
    assert r.status_code == 200 and "pending" not in r.json() and r.json()["version"] == 1       # 第一次發布＝收緊 ⇒ 立即
    _save(c, h["a"], lt(30))
    assert _pub(c, h["a"], "調高").json()["version"] == 2    # 調高門檻＝更多標示＝收緊
    _save(c, h["a"], lt(10))
    j = _pub(c, h["a"], "調低").json()
    assert j["pending"] is True and j["effectiveAt"] and any("低毛利" in x for x in j["reasons"]) and j["status"] == "submitted"
    assert c.get(URL, headers=h["a"]).json()["latest"]["version"] == 2                             # 生效版沒有變
    pend = c.get("/api/def-pipeline/pending", headers=h["b"])
    assert pend.status_code == 200 and "rule_set" in pend.text


def test_restore_to_a_narrower_version_goes_through_the_pipeline(sa):
    c, h = sa
    for v in (lt(15), lt(30)):
        _save(c, h["a"], v)
        assert _pub(c, h["a"]).status_code == 200
    pv = c.get("/api/def-governance/rule_set/case/impact?version=1", headers=h["a"]).json()["previewHash"]
    r = c.post(URL + "/restore/1", headers=h["a"], json={"preview_hash": pv})                                        # v2(<30) → v1(<15)：標示變少＝放寬
    assert r.status_code == 200 and r.json().get("pending") is True


def test_a_seen_preview_is_always_required_while_rules_are_enabled(sa):
    """規則功能開著（builder_rules.enabled＝1）就一律強制預覽——不必另外開 enforce_rule_set（它預設 0）。"""
    c, h = sa
    from helpers import settings_registry as SR
    assert SR.get("builder_governance", "enforce_rule_set") == 0
    _save(c, h["a"], lt(15))
    r = c.post(URL + "/publish", headers=h["a"], json={"note": "n"})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"
    assert _pub(c, h["a"]).status_code == 200


def test_enforce_rule_set_switch_is_an_independent_extra_guard(client, sa):
    c, h = sa
    from helpers import settings_registry as SR
    conn = db.get_db()
    try:
        SR.publish("builder_governance", {"enforce_rule_set": 1}, reason="t62", user="t62", conn=conn)
        conn.commit()
    finally:
        conn.close()
    _save(c, h["a"], lt(15))
    assert c.post(URL + "/publish", headers=h["a"], json={"note": "n"}).status_code == 409
    assert _pub(c, h["a"]).status_code == 200


def test_governance_routes_for_rule_set_are_404_when_rules_are_not_effective(sa, monkeypatch):
    c, h = sa
    assert c.get("/api/def-governance/rule_set/case/ledger", headers=h["a"]).status_code == 200
    monkeypatch.setattr("helpers.rule_sets.enabled", lambda conn=None: False)
    for tail in ("ledger", "impact", "diff"):
        assert c.get("/api/def-governance/rule_set/case/" + tail, headers=h["a"]).status_code == 404       # 種類還登記在記憶體裡也一樣


def test_rules_turned_off_means_the_generic_routes_are_hidden(sa, monkeypatch):
    c, h = sa
    monkeypatch.setattr("helpers.rule_sets.enabled", lambda conn=None: False)
    assert c.get(URL, headers=h["a"]).status_code == 404
