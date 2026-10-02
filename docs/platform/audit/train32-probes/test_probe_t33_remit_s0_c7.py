# -*- coding: utf-8 -*-
"""第 33 班滾動稽核（c7）：31-B S0 匯款款別（wip/t33-remit-s0-a3）獨立探針。斷言＝應該怎樣；印出實測值。不隨產品出貨。"""
import copy
import json

import pytest

import db
from modules.subcontract import remit_kinds as RK
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _login  # noqa: F401

BASE = "/api/definitions/remit_kinds/default"


@pytest.fixture
def W(client, make_user):
    h = {n: _login(client, *make_user(username=n, role=r)) for n, r in (("rk_sa", "superadmin"), ("rk_adm", "admin"), ("rk_sales", "sales"))}
    return client, h


def _body(*codes, **extra):
    ks = [{"code": c, "name": "款" + c, "active": True, "sort": i, "stages": ["accepted"], "note": ""} for i, c in enumerate(codes)]
    return {"name": "匯款款別", "kinds": ks, **extra}


def _pub(c, h, body, note="n"):
    r = c.put(BASE + "/draft", headers=h["rk_sa"], json={"body": body})
    if r.status_code != 200:
        return r
    return c.post(BASE + "/publish", headers=h["rk_sa"], json={"note": note})


def test_removing_or_renaming_a_published_code_is_refused_but_deactivating_is_fine(W):
    c, h = W
    assert _pub(c, h, _body("aa", "bb")).status_code == 200
    r = _pub(c, h, _body("aa"))
    print("remove ->", r.status_code, r.text[:120])
    assert r.status_code == 422
    r = _pub(c, h, _body("aa", "bx"))                                                        # 改代碼＝移除舊的
    print("rename ->", r.status_code)
    assert r.status_code == 422
    b = _body("aa", "bb")
    b["kinds"][1]["active"] = False
    assert _pub(c, h, b).status_code == 200


def test_restore_cannot_bring_back_a_state_that_drops_a_published_code(W):
    """v1＝{aa,bb}；v2＝{aa,bb,cc}；還原 v1 ⇒ cc 被移除（等同繞過『發布後不可移除』）。"""
    c, h = W
    assert _pub(c, h, _body("aa", "bb")).status_code == 200
    assert _pub(c, h, _body("aa", "bb", "cc")).status_code == 200
    r = c.post(BASE + "/restore/1", headers=h["rk_sa"], json={})
    cn = db.get_db()
    cur = RK.current(cn)
    cn.close()
    print("restore v1 ->", r.status_code, r.text[:120], "| current codes:", [k["code"] for k in cur["kinds"]], "v", cur["version"])
    assert r.status_code in (400, 422) and "cc" in [k["code"] for k in cur["kinds"]], "還原讓已發布的代碼 cc 消失"


def test_current_version_is_the_published_one_even_when_a_newer_draft_exists(W):
    c, h = W
    assert _pub(c, h, _body("aa")).status_code == 200
    assert c.put(BASE + "/draft", headers=h["rk_sa"], json={"body": _body("aa", "zz")}).status_code == 200
    cn = db.get_db()
    cur = RK.current(cn)
    cn.close()
    print("current with draft:", cur["version"], [k["code"] for k in cur["kinds"]])
    assert cur["version"] == 1 and [k["code"] for k in cur["kinds"]] == ["aa"]


@pytest.mark.parametrize("mut", [
    lambda b: b["kinds"][0].update(stages=[{"x": 1}]), lambda b: b["kinds"][0].update(stages=[["accepted"]]), lambda b: b["kinds"][0].update(stages="accepted"),
    lambda b: b["kinds"][0].update(stages=["cancelled"]), lambda b: b["kinds"][0].update(stages=["accepted", "accepted"]), lambda b: b["kinds"][0].update(stages=[]),
    lambda b: b["kinds"][0].update(active="yes"), lambda b: b["kinds"][0].update(active=1), lambda b: b["kinds"][0].update(name=" "), lambda b: b["kinds"][0].update(name="一" * 21),
    lambda b: b["kinds"][0].update(code="AA"), lambda b: b["kinds"][0].update(code="a"), lambda b: b["kinds"][0].update(code="a" * 41), lambda b: b["kinds"][0].update(code="a-b"),
    lambda b: b["kinds"][0].update(code=None), lambda b: b["kinds"][0].update(code=["x"]), lambda b: b["kinds"][0].update(sort=True), lambda b: b["kinds"][0].update(sort=1.5),
    lambda b: b["kinds"][0].update(note="x" * 201), lambda b: b["kinds"].append(copy.deepcopy(b["kinds"][0])), lambda b: b["kinds"].append("str"), lambda b: b.update(kinds=[]),
    lambda b: b.update(kinds=None), lambda b: b["kinds"][0].update(active=False),
])
def test_validator_rejects_bad_bodies_with_422_and_never_500(W, mut):
    c, h = W
    b = _body("aa")
    mut(b)
    r = _pub(c, h, b)
    print("%s -> %s" % (json.dumps(b, ensure_ascii=False)[:90], r.status_code))
    assert r.status_code in (400, 422), r.text[:100]


def test_more_than_30_kinds_and_non_object_bodies(W):
    c, h = W
    assert _pub(c, h, _body(*["k%02d" % i for i in range(31)])).status_code == 422
    for bad in (None, [], "x", 5):
        r = c.post(BASE + "/validate", headers=h["rk_sa"], json={"body": bad})
        assert r.status_code == 200 and r.json()["problems"], bad


def test_only_one_key_and_permissions(W):
    c, h = W
    r = c.put("/api/definitions/remit_kinds/other/draft", headers=h["rk_sa"], json={"body": _body("aa")})
    r2 = c.post("/api/definitions/remit_kinds/other/publish", headers=h["rk_sa"], json={})
    print("key=other draft/publish ->", r.status_code, r2.status_code)
    assert r.status_code in (400, 422) or r2.status_code in (400, 404, 422)
    assert _pub(c, h, _body("aa")).status_code == 200
    got = {who: (c.get("/api/remit-kinds", headers=h[who]).status_code, c.get("/api/remit-kinds/definition", headers=h[who]).status_code) for who in h}
    print("perm matrix (list, definition):", got)
    assert got["rk_sa"] == (200, 200) and got["rk_adm"] == (200, 403) and got["rk_sales"] == (403, 403)
    assert c.get("/api/remit-kinds").status_code in (401, 403)
    for who in ("rk_adm", "rk_sales"):
        assert c.put(BASE + "/draft", headers=h[who], json={"body": _body("zz")}).status_code in (401, 403)
        assert c.post(BASE + "/publish", headers=h[who], json={}).status_code in (401, 403)


def test_default_is_served_before_any_publish_and_deactivated_kinds_leave_the_dropdown(W):
    c, h = W
    r = c.get("/api/remit-kinds", headers=h["rk_adm"]).json()
    print("default list:", [(k["code"], k["stages"]) for k in r["kinds"]], "v", r["version"])
    assert [k["code"] for k in r["kinds"]] == ["deposit", "progress", "completion", "acceptance"] and r["version"] == 0
    b = RK.default_body()
    b["kinds"][0]["active"] = False
    assert _pub(c, h, b).status_code == 200
    r = c.get("/api/remit-kinds", headers=h["rk_adm"]).json()
    d = c.get("/api/remit-kinds/definition", headers=h["rk_sa"]).json()
    assert "deposit" not in [k["code"] for k in r["kinds"]] and "deposit" in [k["code"] for k in d["body"]["kinds"]] and d["version"] == 1 and d["isDefault"] is False


def test_kind_allowed_at_matrix():
    ks = RK.default_body()["kinds"]
    ks[1]["active"] = False
    assert RK.kind_allowed_at(ks, "deposit", "confirmed")[0] is True
    assert RK.kind_allowed_at(ks, "deposit", "draft")[0] is False and RK.kind_allowed_at(ks, "deposit", "cancelled")[0] is False
    assert RK.kind_allowed_at(ks, "progress", "accepted")[0] is False          # 停用
    assert RK.kind_allowed_at(ks, "nope", "accepted")[0] is False and RK.kind_allowed_at(ks, None, None)[0] is False
    assert RK.kind_allowed_at([None, "x", {"code": "q"}], "q", "draft")[0] is False
