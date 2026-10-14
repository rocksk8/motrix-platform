# -*- coding: utf-8 -*-
"""BP-2 R5：標示規則的逐角色正反對照（真的案件提供者＋真的設定層＋真的列權限；寫好未跑，機器空出來後執行）。
角色：superadmin／admin／sales／finance／engineer／viewer。每個角色各是一筆案件的擁有者（所以都讀得到自己的那一筆），
再加一筆別人的案件，用來證明『逐筆權限』與『欄位遮蔽』是兩件獨立的事：
- 逐筆權限：非 admin+ 只看得到自己的案件（看不到的案件在 marks 裡不存在）
- 欄位遮蔽：沒有 quote_money_visible 的角色（engineer／viewer），由成本衍生的規則對他完全不存在；非金額規則照常
- 規則頁 API（config／summary／preview）只給最高管理者；其他角色一律 403
- 位元組層級：遮蔽角色的所有回應都找不到毛利數字、金額欄位名稱、規則代號或提示文字
- 突變正對照：把目錄的權限檢查拿掉 ⇒ 遮蔽角色立刻看得到標示（證明這組題抓得到遮蔽被破壞）
- 預覽的樣本與計數只含預覽者本人可見的欄位值"""
import json

import pytest

import db
from helpers import rule_sets as RS
from helpers import settings_registry as SR

ROLES = [("superadmin", True), ("admin", True), ("sales", True), ("finance", True), ("engineer", False), ("viewer", False)]
LOW = {"id": "low_margin", "name": "低毛利", "enabled": True, "mode": "mark", "on_failure": "degrade_loud",
       "when": {"op": "lt", "field": "netMarginPct", "value": 15}, "mark": {"level": "red", "text": "毛利偏低", "target": "row"}}
DRAFT = {"id": "is_draft", "name": "草稿", "enabled": True, "mode": "mark", "on_failure": "degrade_loud",
         "when": {"op": "eq", "field": "status", "value": "草稿"}, "mark": {"level": "yellow", "text": "尚未送出", "target": "row"}}
FOREIGN = "Q-OTHER"


def _login(client, make_user, name, role):
    u, p = make_user(username=name, role=role)[:2]
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    conn = db.get_db()
    try:
        row = dict(conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone())
    finally:
        conn.close()
    return {"h": {"Authorization": "Bearer " + r.json()["token"]}, "row": row}


def _add_case(quote_no, owner_row, net, status="草稿"):
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, direct_margin_pct, net_margin_pct, sales_person_id, "
                     "sales_person, data_json, updated_at, deal_tag, settle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (quote_no, status, "客戶", "專案" + quote_no, 123456, net + 3, net, owner_row["id"], owner_row["display_name"] or owner_row["username"],
                      "{}", "2026-10-14 10:00:00", "", ""))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    us = {role: _login(client, make_user, "t62m_" + role, role) for role, _ in ROLES}
    for role, _ in ROLES:
        _add_case("Q-" + role, us[role]["row"], net=5.0)                      # 每人一筆自己的低毛利草稿
    _add_case(FOREIGN, us["admin"]["row"], net=7.0)                           # admin 擁有的別筆（非 admin+ 的角色讀不到）
    conn = db.get_db()
    try:
        SR.publish("builder_governance", {"enabled": 1}, reason="t62", user="t62", conn=conn)
        SR.publish("builder_rules", {"enabled": 1}, reason="t62", user="t62", conn=conn)
        conn.commit()
    finally:
        conn.close()
    RS.ensure_registered()                                                    # rule_set 種類懶登記：單獨跑這個檔時沒人先登記它（整套跑只是剛好前面有別的檔登記過）
    sa = us["superadmin"]["h"]
    url = "/api/definitions/rule_set/case"
    assert client.put(url + "/draft", headers=sa, json={"body": {"rules": [LOW, DRAFT]}}).status_code == 200
    pv = client.get("/api/def-governance/rule_set/case/impact", headers=sa).json()["previewHash"]
    assert client.post(url + "/publish", headers=sa, json={"note": "t", "preview_hash": pv}).status_code == 200
    return us


def _all_ids():
    return ",".join(["Q-" + r for r, _ in ROLES] + [FOREIGN])


@pytest.mark.parametrize("role,sees_money", ROLES)
def test_marks_matrix(client, world, role, sees_money):
    r = client.get("/api/rules/marks?entity=case&ids=" + _all_ids(), headers=world[role]["h"])
    assert r.status_code == 200, r.text
    marks = r.json()["marks"]
    reads_all = role in ("superadmin", "admin", "finance")                                       # admin+ 與持 cashier 的財務讀得到全部案件（row_access read_bypass_modules，CM14b）；其餘只讀自己的
    expected_rows = {"Q-" + x for x, _ in ROLES} | {FOREIGN} if reads_all else {"Q-" + role}
    by_rule = {rid: {i for i, ms in marks.items() for m in ms if m["ruleId"] == rid} for rid in ("low_margin", "is_draft")}
    assert by_rule["is_draft"] == expected_rows                                                 # 非金額規則：每筆可讀的案件都有（逐筆權限）
    assert by_rule["low_margin"] == (expected_rows if sees_money else set())                    # 金額規則：只有看得到金額的人
    assert not (set(marks) - expected_rows)                                                      # 讀不到的案件一個字都不會出現


@pytest.mark.parametrize("role,sees_money", [x for x in ROLES if not x[1]])
def test_masked_roles_get_no_trace_of_money_derived_rules(client, world, role, sees_money):
    blobs = []
    for url in ("/api/rules/marks?entity=case&ids=" + _all_ids(), "/api/rules/marks?entity=case&ids=Q-" + role):
        blobs.append(client.get(url, headers=world[role]["h"]).text)
    blobs.append(client.get("/api/rules/config", headers=world[role]["h"]).text)
    blobs.append(client.get("/api/rules/summary?entity=case", headers=world[role]["h"]).text)
    blobs.append(client.post("/api/rules/preview", headers=world[role]["h"], json={"entity": "case", "body": {"rules": [LOW]}}).text)
    text = "\n".join(blobs)
    for needle in ("毛利偏低", "low_margin", "netMarginPct", "營業利益率", "directMarginPct", "5.0", "123456"):
        assert needle not in text, needle


@pytest.mark.parametrize("role,_", [x for x in ROLES if x[0] != "superadmin"])
def test_rules_pages_api_is_superadmin_only(client, world, role, _):
    h = world[role]["h"]
    assert client.get("/api/rules/config", headers=h).status_code == 403
    assert client.get("/api/rules/summary?entity=case", headers=h).status_code == 403
    assert client.post("/api/rules/preview", headers=h, json={"entity": "case", "body": {"rules": []}}).status_code == 403


def test_superadmin_preview_counts_and_samples(client, world):
    sa = world["superadmin"]["h"]
    draft = dict(LOW, when={"op": "lt", "field": "netMarginPct", "value": 6})                  # 5.0 的 6 筆仍中，7.0 的 FOREIGN 不中
    j = client.post("/api/rules/preview", headers=sa, json={"entity": "case", "body": {"rules": [draft]}}).json()
    assert j["available"] is True and j["sampled"] == len(ROLES) + 1
    assert j["published"]["records"] == len(ROLES) + 1 and j["draft"]["records"] == len(ROLES)
    assert (j["added"], j["removed"], j["direction"]) == (0, 1, "loosen")
    assert {s["id"] for s in j["samples"]} == {"Q-" + r for r, _ in ROLES}
    assert all(set(s["values"]) <= {"netMarginPct"} for s in j["samples"])                      # 只帶規則用到的欄位
    assert j["published"]["hits"] == {"low_margin": len(ROLES) + 1, "is_draft": len(ROLES) + 1}


def test_a_money_rule_preview_for_superadmin_contains_the_value_but_only_for_that_field(client, world):
    sa = world["superadmin"]["h"]
    j = client.post("/api/rules/preview", headers=sa, json={"entity": "case", "body": {"rules": [LOW]}}).json()
    assert all(s["values"] == {"netMarginPct": 5.0} or s["values"] == {"netMarginPct": 7.0} for s in j["samples"])
    assert "123456" not in json.dumps(j)                                                        # 規則沒用到的金額欄位（含稅總額）不外帶


def test_mutation_removing_the_permission_check_makes_masked_roles_see_marks(client, world, monkeypatch):
    """突變正對照：目錄的權限檢查改成永遠通過 ⇒ engineer 看得到由毛利衍生的標示。這證明上面的矩陣題在遮蔽被破壞時會紅。"""
    before = client.get("/api/rules/marks?entity=case&ids=Q-engineer", headers=world["engineer"]["h"]).json()["marks"]
    assert not [m for ms in before.values() for m in ms if m["ruleId"] == "low_margin"]
    monkeypatch.setattr("helpers.rule_catalog._has_perm", lambda perm, user: True)
    # 提供者本身也有縱深防禦（沒有金額權限就不給值），所以這裡還要把它拿掉才會真的洩漏
    monkeypatch.setattr("modules.case.rule_provider.quote_money_visible", lambda user: True)
    after = client.get("/api/rules/marks?entity=case&ids=Q-engineer", headers=world["engineer"]["h"]).json()["marks"]
    assert [m for ms in after.values() for m in ms if m["ruleId"] == "low_margin"]


def test_each_defense_layer_alone_still_blocks_the_leak(client, world, monkeypatch):
    """縱深防禦：只拿掉目錄那一層（提供者仍遮蔽），或只拿掉提供者那一層（目錄仍裁剪），engineer 都看不到毛利衍生的標示。"""
    h = world["engineer"]["h"]
    with monkeypatch.context() as m:                                                            # 不用 monkeypatch.undo()：它會連 fixture 的 patch 一起撤掉（client／設定層壞掉 ⇒ 回應沒有 marks）
        m.setattr("helpers.rule_catalog._has_perm", lambda perm, user: True)
        a = client.get("/api/rules/marks?entity=case&ids=Q-engineer", headers=h).json()["marks"]
    assert not [m_ for ms in a.values() for m_ in ms if m_["ruleId"] == "low_margin"]
    with monkeypatch.context() as m:
        m.setattr("modules.case.rule_provider.quote_money_visible", lambda user: True)
        b = client.get("/api/rules/marks?entity=case&ids=Q-engineer", headers=h).json()["marks"]
    assert not [m_ for ms in b.values() for m_ in ms if m_["ruleId"] == "low_margin"]
