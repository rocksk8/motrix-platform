# -*- coding: utf-8 -*-
"""匯款款別設定（31-B S0）：定義種類 `remit_kinds`（定義文件庫）、預設四種與派發狀態對應、驗證器、不可移除、下拉 API、版本、開立規則。
反向控制：把『不可移除』檢查換成永遠通過 ⇒ test_rk3 紅；驗證器拿掉 stages 檢查 ⇒ test_rk2 紅（見各題註解）。"""
import copy
import json
import sqlite3

import pytest

from core import definitions as D
from modules.subcontract import remit_kinds as RK

BASE = "/api/definitions/remit_kinds/default"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def hs(client, make_user):
    out = {}
    for name, role in (("rk_sa", "superadmin"), ("rk_admin", "admin"), ("rk_sales", "sales")):
        u, p = make_user(username=name, role=role)[:2]
        out[name] = _login(client, u, p)
    return out


def _body(**kw):
    b = RK.default_body()
    b.update(kw)
    return b


# ── RK1 出貨預設 ───────────────────────────────────────────────────────

def test_rk1_shipped_default_is_the_four_kinds_with_the_confirmed_status_mapping():
    d = RK.default_body()
    by = {k["code"]: k for k in d["kinds"]}
    assert list(by) == ["deposit", "progress", "completion", "acceptance"]
    assert [by[c]["name"] for c in by] == ["訂金款", "進度款", "完工款", "驗收款"]
    assert by["deposit"]["stages"] == ["confirmed", "pending_acceptance", "accepted", "completed"]          # 已確認～完工
    assert by["progress"]["stages"] == ["confirmed", "pending_acceptance", "accepted"]                       # 已確認～已驗收
    assert by["completion"]["stages"] == ["accepted", "completed"] and by["acceptance"]["stages"] == ["accepted", "completed"]
    assert all(k["active"] for k in d["kinds"])
    assert RK.validate_body(d, "default", conn=sqlite3.connect(":memory:")) == []
    assert RK.default_body("other") is None
    d["kinds"][0]["name"] = "改了"                                                                            # 回傳的是新物件
    assert RK.default_body()["kinds"][0]["name"] == "訂金款"


def test_rk1_registered_in_the_definition_store_and_current_is_version_zero_without_a_publish(client):
    import db
    assert RK.KIND in D.kinds() and D.default_for(RK.KIND, "default")["kinds"][0]["code"] == "deposit"
    conn = db.get_db()
    try:
        cur = RK.current(conn)
        assert cur["version"] == 0 and [k["code"] for k in cur["kinds"]] == ["deposit", "progress", "completion", "acceptance"]
    finally:
        conn.close()


# ── RK2 驗證器 ─────────────────────────────────────────────────────────

def _problems(body):
    return RK.validate_body(body, "default", conn=sqlite3.connect(":memory:"))


def test_rk2_validator_rules():
    ok = RK.default_body()
    assert _problems(ok) == []
    assert _problems({"kinds": []})[0]["path"] == "kinds" and _problems("x")[0]["path"] == ""
    assert RK.validate_body(ok, "other") and RK.validate_body(ok, "default") == _problems(ok)

    def mutate(fn):
        b = copy.deepcopy(ok)
        fn(b)
        return _problems(b)
    assert any("代碼" in p["message"] for p in mutate(lambda b: b["kinds"][0].update(code="Bad Code")))
    assert any("重複" in p["message"] for p in mutate(lambda b: b["kinds"][1].update(code="deposit")))
    assert any("名稱" in p["message"] for p in mutate(lambda b: b["kinds"][0].update(name="  ")))
    assert any("名稱" in p["message"] for p in mutate(lambda b: b["kinds"][0].update(name="字" * 21)))
    assert any("active" in p["message"] for p in mutate(lambda b: b["kinds"][0].update(active="yes")))
    assert any("整數" in p["message"] for p in mutate(lambda b: b["kinds"][0].update(sort="1")))
    assert any("派發狀態" in p["message"] for p in mutate(lambda b: b["kinds"][0].update(stages=["accepted", "nope"])))   # 反向控制：拿掉 stages 檢查 ⇒ 紅
    assert any("至少要有一個可開立" in p["message"] for p in mutate(lambda b: b["kinds"][0].update(stages=[])))
    assert any("重複" in p["message"] for p in mutate(lambda b: b["kinds"][0].update(stages=["accepted", "accepted"])))
    assert any("備註" in p["message"] for p in mutate(lambda b: b["kinds"][0].update(note="x" * 201)))
    assert any("至少要有一個啟用" in p["message"] for p in mutate(lambda b: [k.update(active=False) for k in b["kinds"]]))
    # 停用的款別可以沒有階段（不會被用到）
    assert mutate(lambda b: b["kinds"][0].update(active=False, stages=[])) == []
    assert any("最多" in p["message"] for p in mutate(lambda b: b["kinds"].extend({"code": "k%d" % i, "name": "x", "active": True, "sort": 0, "stages": ["accepted"]} for i in range(30))))


# ── RK3 不可移除、只能停用 ─────────────────────────────────────────────

def _mem_conn(published=(), voucher_kinds=None):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE ui_definitions (kind TEXT, key TEXT, status TEXT, body_json TEXT)")
    for body in published:
        c.execute("INSERT INTO ui_definitions VALUES (?,?, 'published', ?)", (RK.KIND, RK.KEY, json.dumps(body, ensure_ascii=False)))
    if voucher_kinds is not None:
        c.execute("CREATE TABLE contractor_payment_vouchers (kind TEXT NOT NULL DEFAULT '')")
        for k in voucher_kinds:
            c.execute("INSERT INTO contractor_payment_vouchers VALUES (?)", (k,))
    return c


def test_rk3_a_published_or_used_kind_cannot_be_removed_only_deactivated():
    extra = {"code": "retention", "name": "保固金", "active": True, "sort": 50, "stages": ["completed"], "note": ""}
    v1 = _body(kinds=RK.default_body()["kinds"] + [extra])
    conn = _mem_conn(published=[v1])
    without = _body()                                                                                          # 拿掉 retention
    probs = RK.validate_body(without, "default", conn=conn)
    assert probs and "不能移除" in probs[0]["message"] and "retention" in probs[0]["message"]
    deactivated = copy.deepcopy(v1)
    deactivated["kinds"][-1].update(active=False)
    assert RK.validate_body(deactivated, "default", conn=conn) == []                                           # 停用可以
    renamed = copy.deepcopy(v1)
    renamed["kinds"][-1]["name"] = "保固款"
    assert RK.validate_body(renamed, "default", conn=conn) == []                                               # 改名可以
    # 已被匯款申請使用（S1 之後的 contractor_payment_vouchers.kind）也不能移除
    used = _mem_conn(published=[], voucher_kinds=["deposit", ""])
    probs = RK.validate_body(_body(kinds=[k for k in RK.default_body()["kinds"] if k["code"] != "deposit"]), "default", conn=used)
    assert probs and "deposit" in probs[0]["message"]
    # 新增（從未發布過）的款別在草稿階段可以拿掉
    assert RK.validate_body(_body(), "default", conn=_mem_conn(published=[RK.default_body()])) == []


def test_rk3_reverse_control_without_the_removal_check_the_removal_goes_through(monkeypatch):
    extra = {"code": "retention", "name": "保固金", "active": True, "sort": 50, "stages": ["completed"], "note": ""}
    conn = _mem_conn(published=[_body(kinds=RK.default_body()["kinds"] + [extra])])
    assert RK.validate_body(_body(), "default", conn=conn)
    monkeypatch.setattr(RK, "_removed_codes", lambda new_codes, conn: set())
    assert RK.validate_body(_body(), "default", conn=conn) == []                                               # 偵測器壞了 ⇒ 就放行（所以上一題是有效的）


# ── RK4 API ────────────────────────────────────────────────────────────

def test_rk4_dropdown_api_permissions_and_content(client, hs):
    assert client.get("/api/remit-kinds").status_code == 401
    assert client.get("/api/remit-kinds", headers=hs["rk_sales"]).status_code == 403
    r = client.get("/api/remit-kinds", headers=hs["rk_admin"])
    assert r.status_code == 200
    d = r.json()
    assert d["version"] == 0 and [k["code"] for k in d["kinds"]] == ["deposit", "progress", "completion", "acceptance"]
    assert d["kinds"][1]["stages"] == ["confirmed", "pending_acceptance", "accepted"]
    assert [s["key"] for s in d["stages"]] == list(RK.STAGES) and d["stages"][4]["label"] == "已驗收"
    assert client.get("/api/remit-kinds/definition", headers=hs["rk_admin"]).status_code == 403                 # 設定讀取僅最高管理者
    full = client.get("/api/remit-kinds/definition", headers=hs["rk_sa"]).json()
    assert full["isDefault"] is True and full["version"] == 0 and len(full["body"]["kinds"]) == 4


def test_rk4_publish_through_the_definition_api_changes_the_dropdown_and_the_version(client, hs):
    sa = hs["rk_sa"]
    b = _body()
    b["kinds"][1].update(active=False)                                                                         # 停用進度款
    b["kinds"].append({"code": "retention", "name": "保固金", "active": True, "sort": 5, "stages": ["completed"], "note": ""})
    assert client.put(BASE + "/draft", json={"body": b}, headers=sa).status_code == 200
    assert client.post(BASE + "/validate", json={"body": b}, headers=sa).json()["problems"] == []
    assert client.post(BASE + "/publish", json={"note": "加保固金、停用進度款"}, headers=sa).status_code in (200, 201)
    d = client.get("/api/remit-kinds", headers=hs["rk_admin"]).json()
    assert d["version"] == 1 and [k["code"] for k in d["kinds"]] == ["retention", "deposit", "completion", "acceptance"]      # 依 sort；進度款已停用不在下拉
    full = client.get("/api/remit-kinds/definition", headers=hs["rk_sa"]).json()
    assert full["isDefault"] is False and any(k["code"] == "progress" and k["active"] is False for k in full["body"]["kinds"])
    # 不能把已發布的 retention 拿掉
    gone = copy.deepcopy(b)
    gone["kinds"] = [k for k in gone["kinds"] if k["code"] != "retention"]
    assert client.put(BASE + "/draft", json={"body": gone}, headers=sa).status_code == 200
    v = client.post(BASE + "/validate", json={"body": gone}, headers=sa).json()["problems"]
    assert v and "retention" in v[0]["message"]
    rr = client.post(BASE + "/publish", json={"note": "拿掉保固金"}, headers=sa)
    assert rr.status_code == 422 and "retention" in rr.json()["problems"][0]["message"]                         # 發布被擋（驗證不通過 ⇒ 422＋problems）
    # 與出貨預設的差異看得到（c7 的 default_for 修正：公司發布後 a=default 仍是出貨預設）
    diff = client.get(BASE + "/diff?a=default&b=latest", headers=sa).json()["changes"]
    assert any("retention" in json.dumps(c, ensure_ascii=False) for c in diff)
    assert client.put(BASE + "/draft", json={"body": b}, headers=hs["rk_admin"]).status_code == 403            # 設定僅最高管理者


# ── RK5 開立規則（派發狀態）─────────────────────────────────────────────

def test_rk5_kind_allowed_at_checks_existence_active_and_dispatch_status():
    kinds = RK.default_body()["kinds"]
    assert RK.kind_allowed_at(kinds, "deposit", "confirmed") == (True, "")
    assert RK.kind_allowed_at(kinds, "progress", "completed")[0] is False                                      # 進度款到已驗收為止
    ok, why = RK.kind_allowed_at(kinds, "completion", "sent")
    assert ok is False and "已送出" in why and "已驗收" in why and "完工款" in why
    assert RK.kind_allowed_at(kinds, "acceptance", "accepted")[0] is True and RK.kind_allowed_at(kinds, "acceptance", "cancelled")[0] is False
    assert RK.kind_allowed_at(kinds, "nope", "accepted")[0] is False
    off = copy.deepcopy(kinds)
    off[0]["active"] = False
    ok, why = RK.kind_allowed_at(off, "deposit", "confirmed")
    assert ok is False and "已停用" in why
    # 公司自己改了階段對應：只影響之後
    custom = copy.deepcopy(kinds)
    custom[2]["stages"] = ["accepted"]
    assert RK.kind_allowed_at(custom, "completion", "completed")[0] is False
