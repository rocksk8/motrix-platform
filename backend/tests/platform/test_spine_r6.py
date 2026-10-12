# -*- coding: utf-8 -*-
"""脊柱 E-b r6：kind 功能狀態閘門＋受管 kind 登錄、共用健康徽章、SettingDef loosen="both"、group_stamp、surface_status。"""
import os

import pytest

from core import definitions as D
from core import spine
from db import get_db
from helpers import settings_registry as R

SCOPE = {"documents": ["測試單據"], "roles": ["測試角色"], "amounts": "測試用，沒有金額影響", "reversible": True, "effective": "pending"}


@pytest.fixture
def sp(monkeypatch):
    snap = spine.snapshot()
    spine.reset()
    monkeypatch.setattr(spine, "_POST_VALIDATE", [])
    monkeypatch.setattr(spine, "_KIND_GATES", dict(spine._KIND_GATES))
    monkeypatch.setattr(spine, "_MANAGED", dict(spine._MANAGED))
    monkeypatch.setattr(spine, "_HEALTH", {})
    yield spine
    spine.restore(snap)
    for g in [g for g in R._GROUPS if g.startswith("zz_r6")]:
        R._GROUPS.pop(g, None)
    R.invalidate()


def _hdr(client, make_user, name):
    username, password = make_user(username=name, role="superadmin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": "Bearer " + tok}


# ── (a) kind 閘門與受管 kind ──────────────────────────────────────────────────────────

def test_kind_gate_registry_contract(sp):
    f = lambda key: "open"                                                   # noqa: E731
    spine.register_kind_gate("zz_r6_kind", f)
    spine.register_kind_gate("zz_r6_kind", f)                                # 同一函式重複登記 OK
    with pytest.raises(ValueError):
        spine.register_kind_gate("zz_r6_kind", lambda key: "open")           # 不同函式搶同一個 kind
    for bad in ("Bad-Kind", "", None):
        with pytest.raises(ValueError):
            spine.register_kind_gate(bad, f)
    assert spine.has_kind_gate("zz_r6_kind") and not spine.has_kind_gate("zz_r6_other")
    assert spine.kind_info("zz_r6_other", "x") == {"status": "open", "plannedTrain": None}      # 沒登記 ⇒ open


def test_kind_gate_normalises_results_and_fails_closed(sp):
    table = {"a": "open", "b": "planned", "c": {"status": "planned", "plannedTrain": "MS4"}, "d": {"status": "hidden", "plannedTrain": "MS9"},
             "e": "weird", "f": {"status": "nope"}, "g": 5}

    def gate(key):
        if key == "boom":
            raise RuntimeError("gate down")
        return table[key]
    spine.register_kind_gate("zz_r6_kind", gate)
    got = {k: spine.kind_info("zz_r6_kind", k) for k in list(table) + ["boom"]}
    assert got["a"] == {"status": "open", "plannedTrain": None}
    assert got["b"] == {"status": "planned", "plannedTrain": None}
    assert got["c"] == {"status": "planned", "plannedTrain": "MS4"}
    assert got["d"] == {"status": "hidden", "plannedTrain": None}                        # plannedTrain 只在 planned 時有值
    assert all(got[k]["status"] == "hidden" for k in ("e", "f", "g", "boom"))             # 不合法的回傳或丟例外 ⇒ hidden（fail-closed）


def test_managed_kind_registry(sp):
    spine.register_managed_kind("zz_r6_kind", "請到專用入口調整。")
    spine.register_managed_kind("zz_r6_kind", "請到專用入口調整。")
    assert spine.managed_message("zz_r6_kind") == "請到專用入口調整。" and spine.managed_message("zz_r6_nothing") is None
    with pytest.raises(ValueError):
        spine.register_managed_kind("zz_r6_kind", "另一句")
    for bad in (("Bad", "x"), ("zz_r6_k2", ""), ("zz_r6_k3", None)):
        with pytest.raises(ValueError):
            spine.register_managed_kind(*bad)
    assert spine.managed_message("setting_group")                                         # 設定登錄表登記了 setting_group


@pytest.fixture
def gated_kind(client, make_user, sp, monkeypatch):
    """一個全新的定義 kind，三個 key 各有一個已發布版本；閘門＋受管 kind 皆由 spine 登錄（證明路由不再寫死 setting_group）。"""
    monkeypatch.setattr(D, "_EXTRA_KINDS", dict(D._EXTRA_KINDS))
    monkeypatch.setattr(D, "_VALIDATORS", dict(D._VALIDATORS))
    D.register_kind("zz_r6_kind", label="路由測試", validator=lambda body, key: [])
    c = get_db()
    try:
        for k in ("zz_r6_open", "zz_r6_plan", "zz_r6_hide"):
            D.publish_direct(c, "zz_r6_kind", k, "company", {"x": 1}, "測試", "t")
        c.commit()
    finally:
        c.close()
    status = {"zz_r6_open": "open", "zz_r6_plan": {"status": "planned", "plannedTrain": "MS3"}, "zz_r6_hide": "hidden"}
    spine.register_kind_gate("zz_r6_kind", lambda key: status.get(key, "open"))
    return _hdr(client, make_user, "r6_a")


def test_generic_routes_follow_a_registered_kind_gate(client, gated_kind):
    h = gated_kind
    rows = {r["key"]: r for r in client.get("/api/definitions/zz_r6_kind", headers=h).json()}
    assert "zz_r6_hide" not in rows and rows["zz_r6_open"].get("latestVersion")
    assert rows["zz_r6_plan"] == {"key": "zz_r6_plan", "scope": "company", "status": "planned", "plannedTrain": "MS3"}
    for path, planned, hidden in (("", 409, 404), ("/default", 409, 404), ("/versions/1", 409, 404), ("/diff", 409, 404), ("/resolve", 409, 404)):
        assert client.get("/api/definitions/zz_r6_kind/zz_r6_plan" + path, headers=h).status_code == planned, path
        assert client.get("/api/definitions/zz_r6_kind/zz_r6_hide" + path, headers=h).status_code == hidden, path
        assert client.get("/api/definitions/zz_r6_kind/zz_r6_open" + path, headers=h).status_code in (200, 400, 404), path     # open 不被閘門擋（其他狀態碼來自該路由本身）
    assert client.post("/api/definitions/zz_r6_kind/zz_r6_hide/validate", json={"body": {}}, headers=h).status_code == 404
    assert client.post("/api/definitions/zz_r6_kind/zz_r6_plan/validate", json={"body": {}}, headers=h).status_code == 409
    # 沒有登記閘門的 kind（內建）不受影響
    assert isinstance(client.get("/api/definitions/layout", headers=h).json(), list)


def test_registered_managed_kind_refuses_generic_writes_and_hides_hidden_keys(client, gated_kind):
    h = gated_kind
    # 還沒登記受管：通用寫入照舊可用（閘門只管可見性）
    assert client.put("/api/definitions/zz_r6_kind/zz_r6_open/draft", json={"body": {"x": 2}}, headers=h).status_code == 200
    spine.register_managed_kind("zz_r6_kind", "請到專用入口調整。")
    for call in (lambda k: client.put("/api/definitions/zz_r6_kind/%s/draft" % k, json={"body": {"x": 3}}, headers=h),
                 lambda k: client.post("/api/definitions/zz_r6_kind/%s/publish" % k, json={}, headers=h),
                 lambda k: client.post("/api/definitions/zz_r6_kind/%s/restore/1" % k, json={}, headers=h),
                 lambda k: client.delete("/api/definitions/zz_r6_kind/%s/draft" % k, headers=h)):
        r = call("zz_r6_open")
        assert r.status_code == 409 and "專用入口" in r.json()["detail"]
        assert call("zz_r6_hide").status_code == 404                                        # hidden 不洩漏存在


def test_gate_that_raises_hides_the_key(client, gated_kind, sp):
    h = gated_kind

    def broken(key):
        raise RuntimeError("down")
    spine._KIND_GATES["zz_r6_kind"] = broken
    assert client.get("/api/definitions/zz_r6_kind/zz_r6_open", headers=h).status_code == 404
    assert client.get("/api/definitions/zz_r6_kind", headers=h).json() == []


# ── (b) 共用健康徽章 ─────────────────────────────────────────────────────────────────

def test_health_badge_merges_sources_by_severity(sp):
    assert spine.health_badge() == {"text": "功能登錄正常", "tone": "ok"}
    spine.register_health_source("zz_r6_rules", lambda: {"text": "2 條規則已降級", "tone": "warn", "count": 2})
    spine.register_health_source("zz_r6_quiet", lambda: None)
    assert spine.health_badge() == {"text": "2 條規則已降級", "tone": "warn", "count": 2}
    spine.register_health_source("zz_r6_info", lambda: {"text": "有 1 項提醒", "tone": "info"})
    b = spine.health_badge()
    assert b["tone"] == "warn" and b["text"] == "2 條規則已降級・有 1 項提醒" and b["count"] == 2        # 色調取最嚴重、文字依嚴重度排序
    spine.register_manifest({"features": [{"code": "zz_r6_p", "label": "規劃中的", "status": "planned", "planned_train": "MS2"}]}, "zz_r6o")
    spine.validate_all()
    assert spine.health_badge()["text"] == "2 條規則已降級・開發中 1 項・有 1 項提醒"              # warn＞plan＞info
    spine.register_manifest({"features": [{"code": "zz_r6_bad", "label": "壞的", "mail": ["zz_r6_nomail"]}]}, "zz_r6o2")
    spine.validate_all()
    b = spine.health_badge()
    assert b["tone"] == "bad" and b["text"].startswith("1 項功能登錄未通過驗證") and b["count"] == 3  # 失敗在最前面；count＝1＋2


def test_health_badge_skips_broken_sources_and_truncates(sp):
    def boom():
        raise RuntimeError("down")
    spine.register_health_source("zz_r6_boom", boom)
    spine.register_health_source("zz_r6_bad_fmt", lambda: {"text": "x", "tone": "purple"})
    spine.register_health_source("zz_r6_not_dict", lambda: "oops")
    spine.register_health_source("zz_r6_empty", lambda: {"text": "  ", "tone": "warn"})
    assert spine.health_badge() == {"text": "功能登錄正常", "tone": "ok"}                     # 全部略過、不丟例外
    spine.register_health_source("zz_r6_long", lambda: {"text": "很" * 60, "tone": "warn"})
    assert len(spine.health_badge()["text"]) == 40
    with pytest.raises(ValueError):
        spine.register_health_source("zz_r6_long", lambda: None)                               # 同名不同函式


def test_hub_badge_provider_uses_the_merged_badge(sp):
    from routers import settings_center as SC
    spine.register_health_source("zz_r6_src", lambda: {"text": "規則降級 1 條", "tone": "warn", "count": 1})
    assert SC._hub_badge(None, None) == spine.health_badge() == {"text": "規則降級 1 條", "tone": "warn", "count": 1}


# ── (c) loosen="both" ───────────────────────────────────────────────────────────────

def _f(**kw):
    base = dict(question="這項要設多少？", label="測試項目", help="測試用的設定項目。", impact="影響測試用的畫面。", min=0, max=10)
    base.update(kw)
    return R.SettingDef("n", base.pop("type", "int"), base.pop("default", 5), **base)


def test_loosen_both_is_accepted_only_on_numbers_and_flags_any_direction_in_banners():
    f = _f(risk="money", risk_text="金額可能不一致。", loosen="both", impact_scope=SCOPE)
    assert f.loosen == "both"
    with pytest.raises(ValueError):
        _f(type="str", default="a", loosen="both")
    with pytest.raises(ValueError):
        _f(loosen="sideways")
    up, down = R.banner_of(f, 8, days=7), R.banner_of(f, 2, days=7)
    assert up and down and up["level"] == down["level"] == "amber" and "另一位最高管理者核准" in up["lines"][2]
    assert R.banner_of(f, 5) is None                                                         # 預設值不顯示
    assert R.banner_of(_f(risk="ops", loosen="both"), 8) is None                              # 風險低於 money 不顯示


def test_loosen_both_routes_every_numeric_change_through_the_loosening_flow(client, make_user):
    make_user(username="r6_a", role="superadmin")
    make_user(username="r6_b", role="superadmin")
    R.register_group("zz_r6_g", "放寬測試群組", [_f(risk="money", risk_text="金額可能不一致。", loosen="both", impact_scope=SCOPE)], help="測試用的群組。", risk="money", owner="zz_r6")
    R.invalidate()
    c = get_db()
    try:
        kinds = {v: R.plan("zz_r6_g", {"n": v}, user="r6_a", conn=c)["fields"][0]["kind"] for v in (8, 2, 5)}
        assert kinds == {8: "pending_approval", 2: "pending_approval", 5: "unchanged"}       # 調高、調低都要核准；不變就不變
        out = R.publish("zz_r6_g", {"n": 2}, reason="測試", user="r6_a", conn=c)
        assert out["changed"] is False and out["pending"][0]["approvalsRequired"] == 1
        assert R.get("zz_r6_g", "n", conn=c) == 5
    finally:
        c.close()


# ── (d) group_stamp ─────────────────────────────────────────────────────────────────

def test_group_stamp_changes_exactly_when_the_effective_value_could_change(client, make_user, sp):
    make_user(username="r6_s1", role="superadmin")
    make_user(username="r6_s2", role="superadmin")
    R.register_group("zz_r6_s", "戳記測試群組", [
        _f(risk="money", risk_text="金額可能不一致。", requires_pending=True, impact_scope=SCOPE),
        R.SettingDef("m", "int", 1, min=0, max=9, question="這項要設多少？", label="另一項", help="測試用的設定項目。", impact="影響測試用的畫面。")],
        help="測試用的群組。", risk="money", owner="zz_r6")
    R.invalidate()
    c = get_db()
    try:
        s0 = R.group_stamp("zz_r6_s", conn=c)
        assert R.group_stamp("zz_r6_s", conn=c) == s0                                          # 什麼都沒變 ⇒ 相同
        R.publish("zz_r6_s", {"m": 3}, reason="測試", user="r6_s1", conn=c)
        s1 = R.group_stamp("zz_r6_s", conn=c)
        assert s1 != s0                                                                        # 新版本
        R.publish("zz_r6_s", {"n": 9}, reason="測試", user="r6_s1", conn=c)                    # 待生效項
        s2 = R.group_stamp("zz_r6_s", conn=c)
        assert s2 != s1 and R.group_stamp("zz_r6_s", conn=c) == s2
        spine.register_manifest({"features": [{"code": "zz_r6_sf", "label": "戳記功能", "status": "planned", "planned_train": "MS2", "settings": {"group": "zz_r6_s"}}]}, "zz_r6")
        spine.validate_all()
        s3 = R.group_stamp("zz_r6_s", conn=c)
        assert s3 != s2 and s3.startswith("planned|")                                          # 功能狀態翻轉（待生效項此時不生效）
        old = os.environ.get("MOTRIX_SETTINGS_DEFAULTS_ONLY")
        os.environ["MOTRIX_SETTINGS_DEFAULTS_ONLY"] = "1"
        try:
            assert R.group_stamp("zz_r6_s", conn=c) != s3                                      # 緊急逃生口
        finally:
            if old is None:
                os.environ.pop("MOTRIX_SETTINGS_DEFAULTS_ONLY", None)
            else:
                os.environ["MOTRIX_SETTINGS_DEFAULTS_ONLY"] = old
    finally:
        c.close()


def test_group_stamp_never_raises_and_never_repeats_when_it_cannot_tell():
    a, b = R.group_stamp("zz_r6_no_such_group"), R.group_stamp("zz_r6_no_such_group")
    assert a.startswith("unknown:") and b.startswith("unknown:") and a != b                    # 讀不到 ⇒ 每次不同，下游不會快取住未知狀態


# ── (e) surface_status ──────────────────────────────────────────────────────────────

def _feat(code, surfaces, **kw):
    d = {"code": code, "label": "測試功能", "catalog": {"surfaces": surfaces, "fields": []}}
    d.update(kw)
    return d


def test_surface_status_takes_the_strictest_declaring_feature(sp):
    spine.register_manifest({"features": [
        _feat("zz_r6_f1", ["module:zz.open_s", "module:zz.shared"]),
        _feat("zz_r6_f2", ["module:zz.plan_s", "module:zz.shared"], status="planned", planned_train="MS3"),
        _feat("zz_r6_f3", ["module:zz.hide_s"], status="hidden"),
        _feat("zz_r6_f4", ["module:zz.failed_s"], mail=["zz_r6_nomail"])]}, "zz_r6o")
    assert spine.surface_status("module:zz.plan_s") == "open"                                  # validate_all 之前 ⇒ open
    spine.validate_all()
    got = {s: spine.surface_status("module:zz." + s) for s in ("open_s", "plan_s", "hide_s", "failed_s", "shared", "nobody")}
    assert got == {"open_s": "open", "plan_s": "planned", "hide_s": "hidden", "failed_s": "hidden", "shared": "planned", "nobody": "open"}
