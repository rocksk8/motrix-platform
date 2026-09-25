# -*- coding: utf-8 -*-
"""P8 自訂模組引擎（CUSTOMIZATION-SPEC §1／§3.1／§8.1）：定義驗證、文件式單據、公式、分層簽核（含條件）、通知、事件、輸出、凍結版本。

範本是 D4 驗收的「測試用設備借用單」：欄位含公式與參照、兩層簽核（第二層有條件）、事件通知、輸出。
**不改任何程式碼**：全部透過定義（資料）完成。
"""
import copy
import json
from datetime import date

import pytest

KEY = "equipment_loan"


def loan_definition():
    return {
        "name": "測試用設備借用單", "icon": "box", "permission": "custom.equipment_loan",
        "numbering": {"prefix": "EL", "date": "YYYYMMDD", "digits": 4},
        "fields": [
            {"key": "item", "label": "設備", "type": "text", "required": True},
            {"key": "qty", "label": "數量", "type": "number", "required": True},
            {"key": "unit_value", "label": "單價", "type": "number", "default": 0},
            {"key": "total", "label": "總值", "type": "formula", "formula": "qty * unit_value"},
            {"key": "borrower", "label": "借用人", "type": "ref", "target": "users"},
            {"key": "borrow_date", "label": "借出日", "type": "date"},
            {"key": "return_date", "label": "歸還日", "type": "date"},
            {"key": "days", "label": "天數", "type": "formula", "formula": "days_between(borrow_date, return_date)"},
        ],
        "workflow": {
            "initial": "draft",
            "states": [
                {"key": "draft", "label": "草稿"},
                {"key": "pending", "label": "簽核中", "approval": {
                    "tiers": [{"approvers": [{"username": "cm_mgr"}]},
                              {"approvers": [{"username": "cm_boss"}], "when": "total > 10000"}],
                    "on_approved": "approved", "on_rejected": "rejected"}},
                {"key": "approved", "label": "已核准", "notify": {"requester": True}},
                {"key": "rejected", "label": "已退回", "notify": {"requester": True}},
                {"key": "returned", "label": "已歸還", "final": True},
            ],
            "transitions": [
                {"key": "submit", "label": "送審", "from": "draft", "to": "pending"},
                {"key": "revise", "label": "改回草稿", "from": "rejected", "to": "draft", "requester_only": True},
                {"key": "give_back", "label": "歸還", "from": "approved", "to": "returned"},
            ],
        },
    }


# ── 定義驗證 ─────────────────────────────────────────────────────────────

def test_custom_module_definition_valid_example_has_no_problems():
    from helpers import custom_modules as CM
    assert CM.validate_module(loan_definition(), KEY) == []


def _paths(body):
    from helpers import custom_modules as CM
    return {p["path"]: p["message"] for p in CM.validate_module(body, KEY)}


def test_custom_module_definition_problems_point_at_the_spot():
    b = loan_definition()
    b["numbering"]["prefix"] = "el"
    b["fields"][3]["formula"] = "qty * unit_valeu"
    b["fields"][4]["target"] = "nowhere"
    b["fields"][5]["dataClass"] = "F2"
    b["workflow"]["states"][1]["approval"]["tiers"][1]["when"] = "total >"
    b["workflow"]["transitions"][2]["to"] = "lost"
    got = _paths(b)
    assert "numbering.prefix" in got
    assert got["fields[3].formula"].startswith("第 7 字：引用不到欄位 unit_valeu")
    assert "fields[4].target" in got
    assert "個資" in got["fields[5].dataClass"]                    # 個資分流接上前一律拒絕
    assert "workflow.states[1].approval.tiers[1].when" in got
    assert "workflow.transitions[2].to" in got


def test_custom_module_workflow_orphan_dead_end_and_missing_final():
    b = loan_definition()
    b["workflow"]["states"].append({"key": "limbo", "label": "孤立"})
    got = _paths(b)
    assert any("limbo 從起始狀態走不到" in m for m in got.values())
    b = loan_definition()
    b["workflow"]["transitions"] = [t for t in b["workflow"]["transitions"] if t["key"] != "give_back"]
    got = _paths(b)
    assert any("approved 不是終點卻沒有出路" in m for m in got.values())
    b = loan_definition()
    b["workflow"]["states"][4].pop("final")
    assert any("沒有終點狀態" in m for m in _paths(b).values())
    b = loan_definition()
    b["workflow"]["transitions"].append({"key": "reopen", "label": "重開", "from": "returned", "to": "draft"})
    assert any("終點狀態 returned 不可以再往外轉換" in m for m in _paths(b).values())


def test_custom_module_formula_cycle_is_reported():
    b = loan_definition()
    b["fields"].append({"key": "a", "label": "A", "type": "formula", "formula": "b + 1"})
    b["fields"].append({"key": "b", "label": "B", "type": "formula", "formula": "a + 1"})
    assert "循環引用" in _paths(b)["fields"]


def test_custom_module_output_template_is_validated_against_the_sample():
    b = loan_definition()
    b["output"] = {"template": {"theme": "voucher_standard", "blocks": [{"type": "meta", "fields": [{"label": "x", "path": "fields.ghost"}]}]}}
    got = _paths(b)
    assert any(k.startswith("output.template.blocks[0]") and "fields.ghost" in m for k, m in got.items())


# ── 公式 ────────────────────────────────────────────────────────────────

def test_formula_engine_is_safe_and_reports_positions():
    from helpers import formula as F
    assert F.check("qty * price", ["qty", "price"]) == []
    assert F.check("__import__('os').system('x')")[0]["message"].startswith("不支援")
    assert F.check("a.b")[0]["message"].startswith("不支援的寫法")
    assert F.check("x ** 99999999")[0]["message"].startswith("不支援的運算")
    assert F.check("  zz + 1", ["qty"]) == [{"pos": 2, "message": "引用不到欄位 zz"}]
    assert F.check("qty +" + chr(10) + "1")[0]["message"] == "公式只能一行"
    assert F.check("if(qty > 1, 'if(', 0)", ["qty"]) == []            # 字串裡的 if( 不受影響


def test_formula_engine_null_is_not_zero_and_division_by_zero_is_reported():
    from helpers import formula as F
    assert F.evaluate("qty * 2", {}) is None
    assert F.evaluate("coalesce(qty, 0) * 2", {}) == 0
    assert F.evaluate("if(total > 10000, 'high', 'low')", {"total": 20000}) == "high"
    assert F.evaluate("round(10 / 3, 2)", {}) == 3.33
    assert F.evaluate("days_between(a, b)", {"a": "2026-09-01", "b": "2026-09-25"}) == 24
    with pytest.raises(F.FormulaError, match="除以 0"):
        F.evaluate("1 / qty", {"qty": 0})
    assert F.evaluation_order({"total": "sub + tax", "tax": "sub * 0.05", "sub": "qty * price"}) == ["sub", "tax", "total"]


# ── 整條流程（API）────────────────────────────────────────────────────────

def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


@pytest.fixture()
def loan(client, make_user):
    boss_admin = _login(client, make_user, "cm_super", role="superadmin")
    body = loan_definition()
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=boss_admin, json={"body": body})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=boss_admin, json={}).status_code == 200
    h = {
        "super": boss_admin,
        "req": _login(client, make_user, "cm_req", modules=["custom.equipment_loan"]),
        "mgr": _login(client, make_user, "cm_mgr", modules=[]),
        "boss": _login(client, make_user, "cm_boss", modules=[]),
        "other": _login(client, make_user, "cm_other", modules=[]),
    }
    return client, h


def _new(client, h, **values):
    base = {"item": "投影機", "qty": 2, "unit_value": 3000, "borrower": "cm_req",
            "borrow_date": "2026-09-01", "return_date": "2026-09-08"}
    r = client.post("/api/custom/%s/records" % KEY, headers=h["req"], json={"values": dict(base, **values)})
    assert r.status_code == 200, r.text
    return r.json()


def test_custom_module_record_is_numbered_computed_and_indexed(loan):
    client, h = loan
    a = _new(client, h)
    b = _new(client, h, item="筆電")
    today = date.today().strftime("%Y%m%d")
    assert a["record_no"] == "EL-%s-0001" % today and b["record_no"] == "EL-%s-0002" % today
    assert a["data"]["total"] == 6000 and a["data"]["days"] == 7 and a["status"] == "draft"
    got = client.get("/api/custom/%s/records" % KEY, headers=h["req"], params={"field": "item", "value": "筆電"}).json()
    assert [r["record_no"] for r in got] == [b["record_no"]]


def test_custom_module_bad_values_are_reported_per_field(loan):
    client, h = loan
    r = client.post("/api/custom/%s/records" % KEY, headers=h["req"],
                    json={"values": {"qty": "兩台", "borrower": "nobody", "total": 999999, "ghost": 1}})
    assert r.status_code == 400
    keys = {p["key"] for p in r.json()["problems"]}
    assert keys == {"item", "qty", "borrower"}                     # 必填、型別、參照不到


def test_custom_module_formula_fields_ignore_client_input(loan):
    client, h = loan
    rec = _new(client, h, total=1)
    assert rec["data"]["total"] == 6000 and "total" in rec["dropped"]


def test_custom_module_single_tier_approval_notifies_and_emits_event(loan, monkeypatch):
    client, h = loan
    from core import events
    seen = []
    saved = events.snapshot()
    events.subscribe("custom_module.transitioned", lambda p: seen.append(p), "test:custom_modules")
    try:
        _flow_single_tier(client, h, seen)
    finally:
        events.restore(saved)


def _flow_single_tier(client, h, seen):
    rec = _new(client, h)
    r = client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=h["req"], json={})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert len(r.json()["approval"]["tiers"]) == 1                   # 6000 ≤ 10000 ⇒ 第二層條件不成立
    assert client.post("/api/custom/%s/records/%s/approve" % (KEY, rec["record_no"]), headers=h["boss"], json={}).status_code == 403
    r = client.post("/api/custom/%s/records/%s/approve" % (KEY, rec["record_no"]), headers=h["mgr"], json={})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert [(e["from"], e["to"], e["action"]) for e in seen] == [("draft", "pending", "submit"), ("pending", "approved", "approve")]
    import db
    conn = db.get_db()
    try:
        notes = [dict(x) for x in conn.execute("SELECT username, type FROM notifications WHERE ref_id=?", (rec["record_no"],)).fetchall()]
    finally:
        conn.close()
    assert {"username": "cm_mgr", "type": "approval"} in notes and {"username": "cm_req", "type": "info"} in notes


def test_custom_module_conditional_second_tier_and_order(loan):
    client, h = loan
    rec = _new(client, h, qty=5)                                   # 15000 > 10000 ⇒ 兩層
    no = rec["record_no"]
    r = client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, no), headers=h["req"], json={})
    assert len(r.json()["approval"]["tiers"]) == 2
    assert client.post("/api/custom/%s/records/%s/approve" % (KEY, no), headers=h["boss"], json={}).status_code == 403  # 順序固定
    r = client.post("/api/custom/%s/records/%s/approve" % (KEY, no), headers=h["mgr"], json={})
    assert r.json()["status"] == "pending" and r.json()["approval"]["currentTier"] == 1
    r = client.post("/api/custom/%s/records/%s/approve" % (KEY, no), headers=h["boss"], json={})
    assert r.json()["status"] == "approved"
    r = client.post("/api/custom/%s/records/%s/transitions/give_back" % (KEY, no), headers=h["req"], json={})
    assert r.json()["status"] == "returned"
    assert [x["action"] for x in r.json()["log"]] == ["create", "submit", "approve_tier", "approve", "give_back"]


def test_custom_module_reject_revise_and_content_freeze(loan):
    client, h = loan
    rec = _new(client, h)
    no = rec["record_no"]
    client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, no), headers=h["req"], json={})
    r = client.put("/api/custom/%s/records/%s" % (KEY, no), headers=h["req"], json={"values": {"item": "改", "qty": 1}})
    assert r.status_code == 409                                    # 送出之後內容凍結
    r = client.post("/api/custom/%s/records/%s/transitions/give_back" % (KEY, no), headers=h["req"], json={})
    assert r.status_code == 409                                    # 不在來源狀態
    r = client.post("/api/custom/%s/records/%s/reject" % (KEY, no), headers=h["mgr"], json={"note": "數量不對"})
    assert r.json()["status"] == "rejected"
    assert client.post("/api/custom/%s/records/%s/transitions/revise" % (KEY, no), headers=h["super"], json={}).status_code == 200
    r = client.put("/api/custom/%s/records/%s" % (KEY, no), headers=h["req"], json={"values": {"item": "改", "qty": 1}})
    assert r.status_code == 200 and r.json()["data"]["total"] == 0          # unit_value 沒填 ⇒ 預設 0


def test_custom_module_approval_cannot_be_skipped_by_a_transition(loan):
    """簽核中的狀態，定義裡就算有轉換從它出去，也不能拿來跳過簽核。"""
    client, h = loan
    body = loan_definition()
    body["workflow"]["transitions"].append({"key": "force", "label": "強制", "from": "pending", "to": "approved"})
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h["super"], json={"body": body})
    client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h["super"], json={})
    rec = _new(client, h)
    client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=h["req"], json={})
    r = client.post("/api/custom/%s/records/%s/transitions/force" % (KEY, rec["record_no"]), headers=h["req"], json={})
    assert r.status_code == 409 and "簽核進行中" in r.json()["detail"]


def test_custom_module_record_stays_on_its_definition_version(loan):
    """已建立的單據凍結在當時的定義版本；之後發布的新版不影響它。"""
    client, h = loan
    old = _new(client, h)
    body = loan_definition()
    body["fields"][3]["formula"] = "qty * unit_value * 2"
    body["fields"][0]["label"] = "設備名稱"
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h["super"], json={"body": body})
    client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h["super"], json={})
    new = _new(client, h)
    assert old["def_version"] == 1 and new["def_version"] == 2
    assert new["data"]["total"] == 12000
    r = client.put("/api/custom/%s/records/%s" % (KEY, old["record_no"]), headers=h["req"],
                   json={"values": {"item": "投影機", "qty": 2, "unit_value": 3000}})
    assert r.json()["data"]["total"] == 6000                        # 舊單據仍用第 1 版的公式
    html = client.get("/api/custom/%s/records/%s/output" % (KEY, old["record_no"]), headers=h["req"]).text
    assert "設備名稱" not in html and "設備" in html


def test_custom_module_permissions(loan):
    client, h = loan
    assert client.get("/api/custom/%s/records" % KEY, headers=h["other"]).status_code == 403
    assert client.post("/api/custom/%s/records" % KEY, headers=h["other"], json={"values": {}}).status_code == 403
    rec = _new(client, h)
    assert client.get("/api/custom/%s/records/%s" % (KEY, rec["record_no"]), headers=h["mgr"]).status_code == 403
    client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=h["req"], json={})
    assert client.get("/api/custom/%s/records/%s" % (KEY, rec["record_no"]), headers=h["mgr"]).status_code == 200  # 簽核人看得到
    assert client.post("/api/custom/%s/records/%s/reject" % (KEY, rec["record_no"]), headers=h["other"], json={}).status_code == 403
    assert [m["key"] for m in client.get("/api/custom-modules", headers=h["req"]).json()] == [KEY]
    assert client.get("/api/custom-modules", headers=h["other"]).json() == []
    assert client.get("/api/custom-modules/catalog", headers=h["req"]).status_code == 403


def test_custom_module_output_uses_the_fields(loan):
    client, h = loan
    rec = _new(client, h)
    html = client.get("/api/custom/%s/records/%s/output" % (KEY, rec["record_no"]), headers=h["req"]).text
    assert rec["record_no"] in html and "投影機" in html and "6000" in html and "測試用設備借用單" in html


def test_custom_module_unpublished_module_is_404(client, make_user):
    h = _login(client, make_user, "cm_super2", role="superadmin")
    assert client.get("/api/custom/nothing_here/records", headers=h).status_code == 404


# ── 建構器輔助 ───────────────────────────────────────────────────────────

def test_custom_module_builder_helpers(client, make_user):
    h = _login(client, make_user, "cm_super3", role="superadmin")
    cat = client.get("/api/custom-modules/catalog", headers=h).json()
    assert "formula" in cat["fieldTypes"] and "if" in cat["formulaFunctions"] and "users" in cat["refTargets"]
    r = client.post("/api/custom-modules/formula/check", headers=h, json={"formula": "qty * pirce", "fields": ["qty", "price"]})
    assert r.json()["problems"] == [{"pos": 6, "message": "引用不到欄位 pirce"}]
    r = client.post("/api/custom-modules/numbering/preview", headers=h, json={"numbering": {"prefix": "EL", "date": "YYYYMM", "digits": 3}})
    assert r.json()["example"] == "EL-%s-001" % date.today().strftime("%Y%m")
    assert client.post("/api/custom-modules/numbering/preview", headers=h, json={"numbering": {"prefix": "el"}}).status_code == 422
    r = client.post("/api/custom-modules/%s/output/preview" % KEY, headers=h, json={"body": loan_definition()})
    assert r.status_code == 200 and "EL-20260925-0001" in r.text
    bad = loan_definition()
    bad["output"] = {"template": {"theme": "voucher_standard", "blocks": [{"type": "nope"}]}}
    r = client.post("/api/custom-modules/%s/output/preview" % KEY, headers=h, json={"body": bad})
    assert r.status_code == 422 and r.json()["problems"][0]["path"] == "output.template.blocks[0].type"


def test_custom_module_publish_is_blocked_by_problems(client, make_user):
    h = _login(client, make_user, "cm_super4", role="superadmin")
    bad = loan_definition()
    bad["workflow"]["initial"] = "nowhere"
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": bad})
    r = client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={})
    assert r.status_code == 422 and any(p["path"] == "workflow.initial" for p in r.json()["problems"])


def test_custom_module_tables_are_backed_up_and_cleared_for_demo(client):
    import archive
    import db
    names = archive.backed_up_table_names()
    for t in ("custom_records", "custom_record_log", "custom_record_counters"):
        assert t in names and t in db.DEMO_CLEARED_TABLES
    assert "custom_record_values" in db.DEMO_CLEARED_TABLES          # 索引可由 data_json 重建，不另外匯出
