# -*- coding: utf-8 -*-
"""脊柱 E-b：設定中心**每一條**路由對功能狀態（open／planned／hidden）的行為——路由表驅動。
路由表裡出現本檔 CASES 沒分類的新路由 ⇒ 紅（強迫新增端點時決定它對非 open 群組的行為）；CASES 裡有但路由已不存在 ⇒ 也紅。"""
import pytest

from core import spine
from db import get_db
from helpers import settings_registry as R

SCOPE = {"documents": ["測試單據"], "roles": ["測試角色"], "amounts": "測試用，沒有金額影響", "reversible": True, "effective": "pending"}
P = "/api/settings-center"
OPEN, PLAN, HIDE = "zz_rt_open", "zz_rt_plan", "zz_rt_hide"


def _group(name, presets):
    R.register_group(name, "路由測試" + {OPEN: "開放", PLAN: "規劃", HIDE: "隱藏"}[name], [
        R.SettingDef("limit", "int", 100, min=1, max=1000, question="額度上限要設多少？", label="額度上限", help="單筆核准的額度上限。", impact="影響之後送出的單據。",
                     risk="money", risk_text="額度調高後可核准更大的金額。", requires_pending=True, impact_scope=SCOPE, presets=presets),
        R.SettingDef("note", "int", 7, min=1, max=30, question="提醒要提前幾天？", label="提前提醒", help="到期前幾天提醒。", impact="影響之後的提醒。")],
        help="路由測試用群組。", risk="money", owner="zz_rt")


def _declare(statuses):
    spine.reset()
    feats = []
    for g, st in statuses.items():
        f = {"code": g + "_f", "label": "路由測試功能", "settings": {"group": g}, "status": st}
        if st == "planned":
            f["planned_train"] = "MS2"
        feats.append(f)
    spine.register_manifest({"features": feats}, "zz_rt")
    spine.validate_all()
    R.invalidate()


class Ctx:
    pass


@pytest.fixture
def ctx(client, make_user, monkeypatch):
    snap = spine.snapshot()
    monkeypatch.setattr(spine, "_POST_VALIDATE", [])
    c = Ctx()
    c.client = client
    uname, pw = make_user(username="rt_a", role="superadmin")
    make_user(username="rt_b", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": uname, "password": pw}).json()["token"]
    c.h = {"Authorization": "Bearer " + tok}
    _group(OPEN, {"路由組": 50})
    _group(PLAN, {"路由組": 50, "只開發中組": 40})
    _group(HIDE, {"路由組": 50, "只隱藏組": 30})
    _declare({OPEN: "open", PLAN: "open", HIDE: "open"})
    db = get_db()
    try:
        c.pend = {}
        for g in (OPEN, PLAN, HIDE):                                   # 三個群組各留一筆待生效項，再把兩個翻成非 open
            out = R.publish(g, {"limit": 200}, reason="調高", user="rt_a", conn=db)
            c.pend[g] = out["pending"][0]["id"]
        db.commit()
    finally:
        db.close()
    _declare({OPEN: "open", PLAN: "planned", HIDE: "hidden"})
    yield c
    spine.restore(snap)
    for g in (OPEN, PLAN, HIDE):
        R._GROUPS.pop(g, None)
    R.invalidate()


def _g(c, path, **kw):
    return c.client.get(P + path, headers=c.h, **kw)


def _p(c, path, body):
    return c.client.post(P + path, json=body, headers=c.h)


def _code(r, planned, hidden, kind):
    want = {"planned": planned, "hidden": hidden}[kind]
    assert r.status_code == want, (kind, r.status_code, r.text[:200])


GROUP = {"planned": PLAN, "hidden": HIDE}


def case_list_groups(c, kind):
    groups = {x["group"]: x for x in _g(c, "/groups").json()["groups"]}
    assert OPEN in groups and groups[OPEN]["status"] == "open"
    if kind == "hidden":
        assert HIDE not in groups
    else:
        x = groups[PLAN]
        assert x["status"] == "planned" and x["plannedTrain"] == "MS2" and x["values"] == {} and x["fieldCount"] == 0 and x["lastChange"] is None


def case_get_group(c, kind):
    r = _g(c, "/groups/" + GROUP[kind])
    _code(r, 200, 404, kind)
    if kind == "planned":
        d = r.json()
        assert d["status"] == "planned" and d["plannedTrain"] == "MS2" and d["fields"] == [] and d["values"] == {} and d["history"] == []


def case_save(c, kind):
    _code(_p(c, "/groups/" + GROUP[kind], {"values": {"note": 9}, "reason": "測試"}), 409, 404, kind)


def case_preview(c, kind):
    _code(_p(c, "/groups/%s/preview" % GROUP[kind], {"values": {"note": 9}}), 409, 404, kind)


def case_impact(c, kind):
    _code(_p(c, "/groups/%s/impact" % GROUP[kind], {"field": "note", "value": 9}), 409, 404, kind)


def case_reset(c, kind):
    _code(_p(c, "/groups/%s/reset" % GROUP[kind], {"fields": ["note"], "reason": "測試"}), 409, 404, kind)


def case_restore(c, kind):
    _code(_p(c, "/groups/%s/restore/1" % GROUP[kind], {"reason": "測試"}), 409, 404, kind)


def case_versions(c, kind):
    _code(_g(c, "/groups/%s/versions" % GROUP[kind]), 409, 404, kind)


def case_diff(c, kind):
    _code(_g(c, "/groups/%s/diff" % GROUP[kind]), 409, 404, kind)


def case_pending_list(c, kind):
    items = _g(c, "/pending").json()["pending"]
    assert [x["id"] for x in items if x["group"] == OPEN] == [c.pend[OPEN]]            # open 的照常列出
    assert not [x for x in items if x["group"] in (PLAN, HIDE)]                         # 非 open 的過濾掉（漏網項也不顯示）


def case_approve(c, kind):
    _code(_p(c, "/pending/%d/approve" % c.pend[GROUP[kind]], {}), 409, 404, kind)


def case_cancel(c, kind):
    r = _p(c, "/pending/%d/cancel" % c.pend[GROUP[kind]], {"reason": "收尾"})
    assert r.status_code == 200, (kind, r.status_code, r.text[:200])                     # 收尾用：允許（planned 與 hidden 都可）


def case_public(c, kind):
    r = _g(c, "/public", params={"groups": GROUP[kind]})
    _code(r, 200, 404, kind)
    if kind == "planned":
        assert r.json()["groups"][PLAN] == {"limit": 100, "note": 7}                    # 已儲存的值（＝預設，因為寫入被拒）


def case_profiles(c, kind):
    names = {x["name"] for x in _g(c, "/profiles").json()["profiles"]}
    assert "路由組" in names
    assert "只開發中組" not in names and "只隱藏組" not in names                          # 只涵蓋非 open 群組的預設組不列出


def case_profile_preview(c, kind):
    if kind == "planned":
        r = _g(c, "/profiles/只開發中組/preview")
        assert r.status_code == 200 and r.json()["changes"] == [] and [s["group"] for s in r.json()["skipped"]] == [PLAN]
    else:
        assert _g(c, "/profiles/只隱藏組/preview").status_code == 404                     # 隱藏的不洩漏
    d = _g(c, "/profiles/路由組/preview").json()
    assert [s["group"] for s in d["skipped"]] == [PLAN] and HIDE not in str(d) and "路由測試隱藏" not in str(d)
    assert any(x["group"] == OPEN for x in d["changes"])


def case_profile_apply(c, kind):
    if kind == "planned":
        r = _p(c, "/profiles/只開發中組/apply", {"reason": "測試"})
        assert r.status_code == 200 and r.json()["results"] == {} and [s["group"] for s in r.json()["skipped"]] == [PLAN]
    else:
        assert _p(c, "/profiles/只隱藏組/apply", {"reason": "測試"}).status_code == 404
    r = _p(c, "/profiles/路由組/apply", {"reason": "測試"})
    assert r.status_code == 200 and OPEN in r.json()["results"] and PLAN not in r.json()["results"] and HIDE not in r.json()["results"]
    assert [s["group"] for s in r.json()["skipped"]] == [PLAN] and "路由測試隱藏" not in str(r.json())


CASES = {
    ("GET", P + "/groups"): case_list_groups,
    ("GET", P + "/groups/{group}"): case_get_group,
    ("POST", P + "/groups/{group}"): case_save,
    ("POST", P + "/groups/{group}/preview"): case_preview,
    ("POST", P + "/groups/{group}/impact"): case_impact,
    ("POST", P + "/groups/{group}/reset"): case_reset,
    ("POST", P + "/groups/{group}/restore/{version}"): case_restore,
    ("GET", P + "/groups/{group}/versions"): case_versions,
    ("GET", P + "/groups/{group}/diff"): case_diff,
    ("GET", P + "/pending"): case_pending_list,
    ("POST", P + "/pending/{change_id}/approve"): case_approve,
    ("POST", P + "/pending/{change_id}/cancel"): case_cancel,
    ("GET", P + "/public"): case_public,
    ("GET", P + "/profiles"): case_profiles,
    ("GET", P + "/profiles/{name}/preview"): case_profile_preview,
    ("POST", P + "/profiles/{name}/apply"): case_profile_apply,
}


def _actual_routes(client):
    spec = client.app.openapi()
    return {(m.upper(), p) for p, ops in spec["paths"].items() if p.startswith(P) for m in ops if m in ("get", "post", "put", "patch", "delete")}


def test_every_settings_center_route_is_classified(client):
    """結構化：新增／刪除路由時，這張表要同步（否則新端點可能忘了處理 planned／hidden）。"""
    actual = _actual_routes(client)
    unclassified, stale = sorted(actual - set(CASES)), sorted(set(CASES) - actual)
    assert not unclassified, "設定中心有路由沒分類（要決定它對 planned／hidden 群組的行為，加進 CASES）：%s" % unclassified
    assert not stale, "CASES 裡的路由已不存在：%s" % stale


@pytest.mark.parametrize("kind", ["planned", "hidden"])
def test_routes_behave_per_status(ctx, kind):
    failures = []
    # cancel 與 approve 共用同一筆待生效項：先 approve（拒絕）再 cancel（允許）
    order = sorted(CASES.items(), key=lambda kv: kv[0][1].endswith("/cancel"))
    for key, fn in order:
        try:
            fn(ctx, kind)
        except AssertionError as e:
            failures.append("%s %s：%s" % (key[0], key[1], e))
    assert not failures, "\n".join(failures)


def test_open_group_is_unaffected(ctx):
    d = _g(ctx, "/groups/" + OPEN)
    assert d.status_code == 200 and d.json()["status"] == "open" and d.json()["fields"]
    assert _p(ctx, "/groups/%s/preview" % OPEN, {"values": {"note": 9}}).status_code == 200
    assert _p(ctx, "/groups/" + OPEN, {"values": {"note": 9}, "reason": "測試"}).status_code == 200
