# -*- coding: utf-8 -*-
"""BP-2 R2：標示型規則 API（旗標預設關；逐角色遮蔽正反對照；預覽只讀）。
- 旗標關（預設）：四條路由全部 404（先驗身分：沒登入 ⇒ 401）；`/api/definition-kinds` 不含 rule_set；通用定義路由對 rule_set 是『未知種類』
- 旗標開（真的設定層）：config 只列本人看得到的欄位；marks 逐角色遮蔽（成本衍生標示只給有金額權限者）；
  遮蔽角色的回應位元組裡沒有來源欄位的值或規則痕跡（正對照：把遮蔽拿掉，測試必須紅）
- 預覽：新增／取消筆數、樣本只含可見欄位、不寫任何資料（資料庫列數前後相同）、沒有資料來源 ⇒ available=false、壞草稿 ⇒ 422
- 故障：評估器壞掉 ⇒ marks 仍回 200（降級），稽核只記一次"""
import json

import pytest

import db
from core import registry
from helpers import rule_sets as RS
from routers import rules as R

ENT = "case"
RECORDS = [
    {"id": "Q1", "label": "甲案", "values": {"netMarginPct": 5, "total": 1000, "status": "草稿"}},
    {"id": "Q2", "label": "乙案", "values": {"netMarginPct": 40, "total": 2000, "status": "已成交"}},
    {"id": "Q3", "label": "丙案", "values": {"netMarginPct": 8, "total": 3000, "status": "草稿"}},
]
LOW_MARGIN = {"id": "low_margin", "name": "低毛利", "enabled": True, "mode": "mark", "on_failure": "degrade_loud",
              "when": {"op": "lt", "field": "netMarginPct", "value": 15}, "mark": {"level": "red", "text": "毛利偏低", "target": "row"}}
DRAFTS = {"id": "is_draft", "name": "草稿", "enabled": True, "mode": "mark", "on_failure": "degrade_loud",
          "when": {"op": "eq", "field": "status", "value": "草稿"}, "mark": {"level": "yellow", "text": "尚未送出", "target": "row"}}
ROLES = [("superadmin", True), ("admin", True), ("sales", True), ("finance", True), ("engineer", False), ("viewer", False)]


def provider(conn, user, ids, limit):
    rows = [r for r in RECORDS if ids is None or r["id"] in ids]
    return [dict(r, values=dict(r["values"])) for r in rows][:limit]


@pytest.fixture()
def src(monkeypatch):
    real = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: dict(real(cap), **({ENT: provider} if cap == "rules.entity" else {})))


@pytest.fixture()
def users(client, make_user):
    out = {}
    for role, _ in ROLES:
        u, p = make_user(username="t62r_" + role, role=role)
        r = client.post("/api/auth/login", json={"username": u, "password": p})
        assert r.status_code == 200, r.text
        out[role] = {"Authorization": "Bearer " + r.json()["token"]}
    return out


def _turn_flag_on():
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish("builder_governance", {"enabled": 1}, reason="t62", user="t62", conn=c)        # 規則靠治理層：兩個都要開
        SR.publish("builder_rules", {"enabled": 1}, reason="t62", user="t62", conn=c)
        c.commit()
    finally:
        c.close()


def _publish_rules(client, h, rules):
    url = "/api/definitions/rule_set/" + ENT
    assert client.put(url + "/draft", headers=h, json={"body": {"rules": rules}}).status_code == 200
    r = client.post(url + "/publish", headers=h, json={"note": "t"})
    assert r.status_code == 200, r.text


def _count_rows():
    c = db.get_db()
    try:
        return tuple(c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("ui_definitions", "audit_log", "config_changes"))
    finally:
        c.close()


# ── 旗標關 ─────────────────────────────────────────────────────────────────────
def test_flag_off_everything_is_404_but_auth_comes_first(client, users):
    sa = users["superadmin"]
    for method, url, kw in (("get", "/api/rules/config", {}), ("get", "/api/rules/summary?entity=case", {}),
                            ("post", "/api/rules/preview", {"json": {"entity": ENT, "body": {"rules": []}}}),
                            ("get", "/api/rules/marks?entity=case&ids=Q1", {})):
        assert getattr(client, method)(url, headers=sa, **kw).status_code == 404, url
        assert getattr(client, method)(url, headers=users["viewer"], **kw).status_code in (403, 404), url
        assert getattr(client, method)(url, **kw).status_code == 401, url                    # 未登入 ⇒ 401（與其他路由一致）


def test_flag_off_leaves_the_kind_unregistered(client, users):
    kinds = [k["kind"] for k in client.get("/api/definition-kinds", headers=users["superadmin"]).json()["kinds"]]
    if "rule_set" in kinds:                                                                    # 同一行程裡別的測試可能已登記過；此時旗標關著，通用路由必須 404
        assert client.get("/api/definitions/rule_set/case", headers=users["superadmin"]).status_code == 404


# ── 旗標開 ─────────────────────────────────────────────────────────────────────
def test_config_lists_only_fields_the_caller_can_see(client, users, src):
    _turn_flag_on()
    cfg = client.get("/api/rules/config", headers=users["superadmin"]).json()
    ent = next(e for e in cfg["entities"] if e["key"] == ENT)
    assert ent["sourceAvailable"] is True and {"netMarginPct", "total", "status"} <= {f["id"] for f in ent["fields"]}
    assert cfg["modes"] == ["mark"] and cfg["onFailure"] == ["degrade_loud"] and cfg["limits"]["nodes"] == 200
    assert client.get("/api/rules/config", headers=users["admin"]).status_code == 403          # 規則頁只給最高管理者


@pytest.mark.parametrize("role,sees_money", ROLES)
def test_marks_role_matrix_masking_wins(client, users, src, role, sees_money):
    _turn_flag_on()
    _publish_rules(client, users["superadmin"], [LOW_MARGIN, DRAFTS])
    r = client.get("/api/rules/marks?entity=case&ids=Q1,Q2,Q3", headers=users[role])
    assert r.status_code == 200, r.text
    marks = r.json()["marks"]
    ids_by_rule = {rid: sorted(i for i, ms in marks.items() for m in ms if m["ruleId"] == rid) for rid in ("low_margin", "is_draft")}
    assert ids_by_rule["is_draft"] == ["Q1", "Q3"]                                             # 非金額規則：人人一樣
    if sees_money:
        assert ids_by_rule["low_margin"] == ["Q1", "Q3"]
    else:
        assert ids_by_rule["low_margin"] == []                                                 # 成本衍生標示：看不到毛利的人完全不會有
        blob = json.dumps(r.json(), ensure_ascii=False)
        assert "毛利偏低" not in blob and "low_margin" not in blob and "netMarginPct" not in blob


def test_masked_viewer_cannot_infer_margin_from_the_response(client, users, src):
    """兩筆毛利差很多的紀錄，對無金額權限者的回應結構逐位元相同（沒有「紅／不紅」可推）。"""
    _turn_flag_on()
    _publish_rules(client, users["superadmin"], [LOW_MARGIN])
    a = client.get("/api/rules/marks?entity=case&ids=Q1", headers=users["engineer"]).json()
    b = client.get("/api/rules/marks?entity=case&ids=Q2", headers=users["engineer"]).json()
    assert a == b == {"entity": ENT, "marks": {}, "degraded": False}
    # 正對照：有權限者在這兩筆上確實看得到差異
    assert client.get("/api/rules/marks?entity=case&ids=Q1", headers=users["sales"]).json()["marks"] != \
        client.get("/api/rules/marks?entity=case&ids=Q2", headers=users["sales"]).json()["marks"]


def test_masking_positive_control_removing_the_money_permission_check_turns_the_matrix_red(client, users, src, monkeypatch):
    """突變：讓目錄把金額欄位對所有人開放 ⇒ engineer 看得到成本衍生標示 ⇒ 上面的矩陣題必須紅。這裡直接證明突變真的會改變結果。"""
    _turn_flag_on()
    _publish_rules(client, users["superadmin"], [LOW_MARGIN])
    monkeypatch.setattr("helpers.rule_catalog._has_perm", lambda perm, user: True)
    marks = client.get("/api/rules/marks?entity=case&ids=Q1", headers=users["engineer"]).json()["marks"]
    assert marks, "突變後 engineer 應該看得到標示（證明矩陣題在遮蔽被拿掉時會紅）"


def test_marks_unknown_entity_and_no_ids_and_no_rules(client, users, src):
    _turn_flag_on()
    assert client.get("/api/rules/marks?entity=nope&ids=Q1", headers=users["sales"]).status_code == 404
    assert client.get("/api/rules/marks?entity=case&ids=", headers=users["sales"]).json()["marks"] == {}
    assert client.get("/api/rules/marks?entity=case&ids=Q1", headers=users["sales"]).json()["marks"] == {}     # 還沒有任何已發布規則


def test_marks_without_a_data_source_is_empty_not_an_error(client, users, monkeypatch):
    _turn_flag_on()
    _publish_rules(client, users["superadmin"], [LOW_MARGIN])
    monkeypatch.setattr(registry, "providers", lambda cap: {})
    assert client.get("/api/rules/marks?entity=case&ids=Q1", headers=users["sales"]).json() == {"entity": ENT, "marks": {}, "degraded": False}


# ── 預覽 ───────────────────────────────────────────────────────────────────────
def test_preview_counts_added_removed_and_is_read_only(client, users, src):
    _turn_flag_on()
    _publish_rules(client, users["superadmin"], [LOW_MARGIN])                                  # 已發布：毛利 < 15 ⇒ Q1、Q3
    draft = dict(LOW_MARGIN, when={"op": "lt", "field": "netMarginPct", "value": 6})           # 草稿：< 6 ⇒ 只剩 Q1（放寬）
    before = _count_rows()
    r = client.post("/api/rules/preview", headers=users["superadmin"], json={"entity": ENT, "body": {"rules": [draft]}})
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["added"], j["removed"]) == (0, 1) and j["published"]["records"] == 2 and j["draft"]["records"] == 1
    assert j["direction"] == "loosen" and j["reasons"] and j["sampled"] == 3
    assert [s["id"] for s in j["samples"]] == ["Q1"] and j["samples"][0]["isNew"] is False
    assert j["samples"][0]["values"] == {"netMarginPct": 5}                                    # 只帶規則用到、且看得到的欄位
    assert _count_rows() == before                                                             # 唯讀：沒有任何寫入
    tighter = client.post("/api/rules/preview", headers=users["superadmin"], json={"entity": ENT, "body": {"rules": [dict(LOW_MARGIN, when={"op": "lt", "field": "netMarginPct", "value": 50})]}}).json()
    assert (tighter["added"], tighter["removed"], tighter["direction"]) == (1, 0, "tighten")


def test_preview_uses_the_saved_draft_when_no_body_is_given(client, users, src):
    _turn_flag_on()
    h = users["superadmin"]
    url = "/api/definitions/rule_set/" + ENT
    assert client.post("/api/rules/preview", headers=h, json={"entity": ENT}).status_code == 400          # 沒草稿也沒內容
    client.put(url + "/draft", headers=h, json={"body": {"rules": [LOW_MARGIN]}})
    assert client.post("/api/rules/preview", headers=h, json={"entity": ENT}).json()["added"] == 2


def test_preview_rejects_bad_drafts_and_unknown_entities(client, users, src):
    _turn_flag_on()
    h = users["superadmin"]
    bad = dict(LOW_MARGIN, when={"op": "lt", "field": "nope", "value": 1})
    r = client.post("/api/rules/preview", headers=h, json={"entity": ENT, "body": {"rules": [bad]}})
    assert r.status_code == 422 and r.json()["detail"]["problems"]
    assert client.post("/api/rules/preview", headers=h, json={"entity": "nope", "body": {"rules": []}}).status_code == 404
    assert client.post("/api/rules/preview", headers=users["admin"], json={"entity": ENT, "body": {"rules": []}}).status_code == 403


def test_preview_without_a_data_source_says_so(client, users, monkeypatch):
    _turn_flag_on()
    monkeypatch.setattr(registry, "providers", lambda cap: {})
    j = client.post("/api/rules/preview", headers=users["superadmin"], json={"entity": ENT, "body": {"rules": [LOW_MARGIN]}}).json()
    assert j["available"] is False and "資料來源" in j["message"]


def test_summary_reports_live_hits(client, users, src):
    _turn_flag_on()
    _publish_rules(client, users["superadmin"], [LOW_MARGIN, DRAFTS])
    j = client.get("/api/rules/summary?entity=case", headers=users["superadmin"]).json()
    assert j["available"] is True and j["hits"] == {"low_margin": 2, "is_draft": 2} and j["version"] >= 1 and j["sampled"] == 3


# ── 故障 ───────────────────────────────────────────────────────────────────────
def test_evaluator_failure_degrades_loudly_but_never_breaks_the_page(client, users, src, monkeypatch):
    _turn_flag_on()
    _publish_rules(client, users["superadmin"], [LOW_MARGIN])
    R._DEGRADE_LOGGED.clear()
    monkeypatch.setattr("helpers.rule_engine._tri", lambda n, v: (_ for _ in ()).throw(RuntimeError("boom")))
    for _ in range(3):
        r = client.get("/api/rules/marks?entity=case&ids=Q1", headers=users["sales"])
        assert r.status_code == 200 and r.json()["marks"] == {} and r.json()["degraded"] is True
        assert "degradedRules" not in r.json()                                                 # 一般使用者只知道有降級，不給規則 id
    sa = client.get("/api/rules/marks?entity=case&ids=Q1", headers=users["superadmin"]).json()
    assert sa["degradedRules"] == [{"ruleId": "low_margin", "reason": "error"}]
    c = db.get_db()
    try:
        n = c.execute("SELECT COUNT(*) FROM audit_log WHERE action='rules.degraded'").fetchone()[0]
    finally:
        c.close()
    assert n == 1                                                                              # 5 分鐘內同一規則同一版只記一筆
