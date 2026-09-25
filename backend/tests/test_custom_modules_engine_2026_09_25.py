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
        notes = [dict(x) for x in conn.execute("SELECT username, type FROM notifications WHERE ref_id=?", ("custom:%s:%s" % (KEY, rec["record_no"]),)).fetchall()]
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
    assert [a["status"] for t in r.json()["approval"]["tiers"] for a in t["approvers"]] == ["approved", "approved"]
    html = client.get("/api/custom/%s/records/%s/output" % (KEY, no), headers=h["req"]).text
    assert html.count("✓ 已簽核") == 2                              # 核准後的輸出印得出兩層簽核
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
    import db
    conn = db.get_db()
    try:
        asks = conn.execute("SELECT COUNT(*) FROM notifications WHERE ref_id=? AND username='cm_mgr' AND type='approval'",
                            ("custom:%s:%s" % (KEY, no),)).fetchone()[0]
    finally:
        conn.close()
    assert asks == 1                                               # 退回之後不會再叫簽核人「待您簽核」
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


def test_custom_module_index_can_be_rebuilt_from_the_records(loan):
    """索引表不進每日 JSON 匯出（備份守門的排除理由）⇒ 必須真的能從單據重建，查詢結果與重建前相同。"""
    client, h = loan
    _new(client, h, item="筆電")
    _new(client, h, item="投影機")
    before = client.get("/api/custom/%s/records" % KEY, headers=h["req"], params={"field": "item", "value": "筆電"}).json()
    import db
    from helpers import custom_modules as CM
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM custom_record_values")
        conn.commit()
        assert client.get("/api/custom/%s/records" % KEY, headers=h["req"], params={"field": "item", "value": "筆電"}).json() == []
        assert CM.rebuild_index(conn) == 2
    finally:
        conn.close()
    after = client.get("/api/custom/%s/records" % KEY, headers=h["req"], params={"field": "item", "value": "筆電"}).json()
    assert after == before and len(after) == 1


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


# ── 權限：在網站上授權自訂模組（D4「不改程式碼」；主持前端缺口 #1）──────────────

def _user_id(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def test_custom_module_permission_can_be_granted_on_the_users_page(client, make_user):
    """發布前 `custom.equipment_loan` 是不認得的 key（400）；發布後權限目錄列得出來、使用者管理頁授權得進去，
    被授權的人就能用那個模組——全程走 API，不寫 DB。"""
    boss = _login(client, make_user, "cm_grant_super", role="superadmin")
    staff = _login(client, make_user, "cm_grant_staff", role="user", modules=[])
    uid = _user_id("cm_grant_staff")
    r = client.put("/api/users/%d" % uid, headers=boss, json={"modules": ["custom.equipment_loan"]})
    assert r.status_code == 400 and "custom.equipment_loan" in r.json()["detail"]
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=boss, json={"body": loan_definition()})
    client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=boss, json={})
    cat = client.get("/api/modules/catalog", headers=boss).json()["modules"]
    assert {"key": "custom.equipment_loan", "label": "測試用設備借用單", "group": "自訂模組"} in cat
    assert client.get("/api/custom/%s/records" % KEY, headers=staff).status_code == 403
    assert client.put("/api/users/%d" % uid, headers=boss, json={"modules": ["custom.equipment_loan"]}).status_code == 200
    assert client.get("/api/custom/%s/records" % KEY, headers=staff).status_code == 200
    assert [m["key"] for m in client.get("/api/custom-modules", headers=staff).json()] == [KEY]


def test_custom_module_permission_source_failure_refuses_new_grants(client, make_user, monkeypatch):
    """動態來源壞掉 ⇒ 那些 key 當成不認得、擋下新授權（不放行）；固定目錄照常。"""
    from helpers import module_registry as MR
    boss = _login(client, make_user, "cm_grant_super2", role="superadmin")
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=boss, json={"body": loan_definition()})
    client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=boss, json={})

    def _boom():
        raise RuntimeError("定義表讀不到")
    monkeypatch.setattr(MR, "_KEY_SOURCES", [_boom])
    make_user("cm_grant_staff2", "Custom-Pass-123", role="user", modules=[])
    r = client.put("/api/users/%d" % _user_id("cm_grant_staff2"), headers=boss, json={"modules": ["custom.equipment_loan"]})
    assert r.status_code == 400
    keys = [m["key"] for m in client.get("/api/modules/catalog", headers=boss).json()["modules"]]
    assert "dashboard" in keys and "custom.equipment_loan" not in keys


def test_custom_module_old_record_comes_with_its_own_definition(loan):
    """主持前端缺口 #2：看舊單據時，標籤與按鈕要用那一版的定義（讀取單據時帶回 `definition`；meta 支援 `?version=`）。"""
    client, h = loan
    old = _new(client, h)
    body = loan_definition()
    body["fields"][0]["label"] = "設備名稱（第 2 版）"
    body["workflow"]["transitions"][0]["label"] = "送出審核"
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h["super"], json={"body": body})
    client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h["super"], json={})
    got = client.get("/api/custom/%s/records/%s" % (KEY, old["record_no"]), headers=h["req"]).json()
    assert got["def_version"] == 1
    assert got["definition"]["fields"][0]["label"] == "設備"
    assert got["definition"]["workflow"]["transitions"][0]["label"] == "送審"
    assert client.get("/api/custom/%s/meta" % KEY, headers=h["req"]).json()["definition"]["fields"][0]["label"] == "設備名稱（第 2 版）"
    m1 = client.get("/api/custom/%s/meta" % KEY, headers=h["req"], params={"version": 1}).json()
    assert m1["version"] == 1 and m1["definition"]["fields"][0]["label"] == "設備"
    assert client.get("/api/custom/%s/meta" % KEY, headers=h["req"], params={"version": 9}).status_code == 404



# ── 「待我簽核」佇列（IP-10 `approval.queue_items`；主持前端缺口 #3）─────────────────

def _queue(client, h):
    return [it for g in client.get("/api/approval-queue", headers=h).json()["queue"] for it in g["items"]]


def test_custom_module_records_show_up_in_the_approval_queue(loan):
    client, h = loan
    rec = _new(client, h)
    no = rec["record_no"]
    before = client.get("/api/approval-queue/count", headers=h["mgr"]).json()["count"]
    client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, no), headers=h["req"], json={})
    mine = [it for it in _queue(client, h["mgr"]) if it["type"] == "custom_record"]
    assert [(it["quoteNo"], it["moduleKey"], it["moduleName"], it["statusLabel"]) for it in mine] ==         [(no, KEY, "測試用設備借用單", "簽核中")]
    assert mine[0]["currentApprovers"][0]["username"] == "cm_mgr" and mine[0]["requestedBy"] == "cm_req"
    assert client.get("/api/approval-queue/count", headers=h["mgr"]).json()["count"] == before + 1
    assert not [it for it in _queue(client, h["other"]) if it["type"] == "custom_record"]     # 不在簽核鏈裡的人看不到
    client.post("/api/custom/%s/records/%s/approve" % (KEY, no), headers=h["mgr"], json={})
    assert not [it for it in _queue(client, h["mgr"]) if it["type"] == "custom_record"]       # 簽完就消失
    assert client.get("/api/approval-queue/count", headers=h["mgr"]).json()["count"] == before


def test_custom_module_queue_provider_failure_does_not_break_the_queue(loan, monkeypatch):
    """反向控制：提供者丟例外 ⇒ 佇列與角標照常 200，只少自訂模組那一類。"""
    client, h = loan
    from core import registry
    def _boom(conn):
        raise RuntimeError("自訂模組讀不到")
    monkeypatch.setitem(registry._LEGACY_PROVIDERS, ("approval.queue_items", "custom_modules"), _boom)
    assert client.get("/api/approval-queue", headers=h["mgr"]).status_code == 200
    assert client.get("/api/approval-queue/count", headers=h["mgr"]).status_code == 200


def test_custom_module_notifications_carry_the_module_in_ref_id(loan):
    """通知的 ref_id＝`custom:<模組>:<單號>`：前端據此開對的頁（單號本身不帶模組）。"""
    client, h = loan
    rec = _new(client, h)
    client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=h["req"], json={})
    import db
    conn = db.get_db()
    try:
        refs = {r[0] for r in conn.execute("SELECT ref_id FROM notifications WHERE username='cm_mgr'").fetchall()}
    finally:
        conn.close()
    assert "custom:%s:%s" % (KEY, rec["record_no"]) in refs


# ── 主持前端缺口 #4～#7 ─────────────────────────────────────────────────────

def test_custom_module_catalog_has_block_specs_themes_formats_and_approver_sources(client, make_user):
    from helpers import doc_template as dt
    h = _login(client, make_user, "cm_cat_super", role="superadmin")
    cat = client.get("/api/custom-modules/catalog", headers=h).json()
    assert set(cat["outputBlockSpecs"]) == set(dt.BLOCKS)                 # 每個積木都有參數規格
    assert cat["outputBlockSpecs"]["items_table"]["params"]["columns"]["type"] == "list:column"
    assert "column" in cat["outputBlockItemSpecs"] and "voucher_standard" in cat["outputThemes"]
    assert cat["outputFormats"] == ["html", "pdf"] and cat["fieldFormats"] == list(dt.FORMATS)
    assert {s["sourceType"] for s in cat["approverSources"]} == {"", "department_manager", "division_manager", "submitter_manager"}


def test_doc_template_specs_match_the_engine():
    """規格與引擎一致：規格列出的每個格式引擎都認得；積木清單兩邊相同（規格是給建構器的，不能多也不能少）。"""
    from helpers import doc_template as dt
    assert set(dt.BLOCK_SPECS) == set(dt.BLOCKS)
    for how in dt.FORMATS:
        dt._fmt("2026-09-25T00:00:00" if how == "date10" else 1, how)
    with pytest.raises(dt.TemplateError):
        dt._fmt("x", "no_such_format")
    for spec in dt.BLOCK_SPECS.values():
        for p in spec["params"].values():
            kind = p["type"].split(":", 1)
            assert kind[0] in ("text", "int", "bool", "path", "cond", "list", "blocks")
            if kind[0] == "list" and kind[1] != "text":
                assert kind[1] in dt.BLOCK_ITEM_SPECS


def test_definitions_can_be_listed_with_drafts_and_a_draft_can_be_deleted(client, make_user):
    h = _login(client, make_user, "cm_list_super", role="superadmin")
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": loan_definition()})
    client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={})
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": loan_definition()})
    client.put("/api/definitions/custom_module/draft_only/draft", headers=h, json={"body": {"name": "只有草稿"}})
    rows = {r["key"]: r for r in client.get("/api/definitions/custom_module", headers=h).json()}
    assert rows[KEY]["latestVersion"] == 1 and rows[KEY]["hasDraft"] is True
    assert rows["draft_only"]["latestVersion"] is None and rows["draft_only"]["hasDraft"] is True
    assert client.delete("/api/definitions/custom_module/%s/draft" % KEY, headers=h).status_code == 200
    assert client.delete("/api/definitions/custom_module/%s/draft" % KEY, headers=h).status_code == 404
    got = client.get("/api/definitions/custom_module/%s" % KEY, headers=h).json()
    assert got["draft"] is None and [v["version"] for v in got["versions"]] == [1]   # 已發布的不受影響
    assert client.get("/api/definitions/nope", headers=h).status_code == 400
    staff = _login(client, make_user, "cm_list_staff", role="admin")
    assert client.get("/api/definitions/custom_module", headers=staff).status_code == 403


def test_custom_module_ref_options(loan):
    client, h = loan
    got = client.get("/api/custom/%s/ref-options/borrower" % KEY, headers=h["req"], params={"q": "cm_re"}).json()
    assert {"value": "cm_req", "label": got[0]["label"]} in got and all("cm_re" in o["value"] or "cm_re" in o["label"] for o in got)
    assert client.get("/api/custom/%s/ref-options/item" % KEY, headers=h["req"]).status_code == 404   # 不是參照欄
    assert client.get("/api/custom/%s/ref-options/borrower" % KEY, headers=h["other"]).status_code == 403
    rec = _new(client, h, item="相機")
    import db
    from helpers import custom_modules as CM
    conn = db.get_db()
    try:
        opts = CM.ref_options(conn, "custom:%s" % KEY, rec["record_no"][-4:])
    finally:
        conn.close()
    assert opts[0]["value"] == rec["record_no"] and "相機" in opts[0]["label"]


def test_custom_module_output_preview_can_be_pdf(client, make_user, monkeypatch):
    """PDF 預覽（主持缺口 #7）：同一份 HTML 交給 pdf_gen.html_to_pdf_bytes（Edge 在測試裡換掉）。"""
    import pdf_gen
    seen = []
    monkeypatch.setattr(pdf_gen, "html_to_pdf_bytes", lambda html: seen.append(html) or b"%PDF-1.4 fake")
    h = _login(client, make_user, "cm_pdf_super", role="superadmin")
    r = client.post("/api/custom-modules/%s/output/preview" % KEY, headers=h, params={"format": "pdf"},
                    json={"body": loan_definition()})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert "EL-20260925-0001" in seen[0]
    from helpers import doc_template as dt
    r = client.post("/api/definitions/output_template/invoice_voucher/preview", headers=h, params={"format": "pdf"},
                    json={"body": dt.load_default("invoice_voucher")})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and "IV-202609-0001" in seen[1]



# ── 簽核條件 fail-safe（稽核 D 事前提示，2026-09-26）──────────────────────────

def test_custom_module_tier_condition_that_cannot_be_evaluated_still_requires_signing(loan):
    """條件算出空值（引用的欄位沒填）⇒ 那一層照簽，不是跳過；回應說明原因。"""
    client, h = loan
    rec = _new(client, h, unit_value=None)                          # total＝qty×unit_value；unit_value 預設 0 ⇒ 改用空值
    import db
    conn = db.get_db()
    try:                                                            # 直接把 total 變成空值（模擬引用到沒填的欄位）
        d = json.loads(conn.execute("SELECT data_json FROM custom_records WHERE record_no=?", (rec["record_no"],)).fetchone()[0])
        d["total"] = None
        conn.execute("UPDATE custom_records SET data_json=? WHERE record_no=?", (json.dumps(d), rec["record_no"]))
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=h["req"], json={})
    assert r.status_code == 200
    assert len(r.json()["approval"]["tiers"]) == 2                  # 第二層（total > 10000）算不出來 ⇒ 照簽
    assert any("算不出來" in n for n in r.json()["notices"])


def test_custom_module_tier_condition_runtime_error_is_not_a_500(loan):
    """條件公式在執行時出錯（除以 0）⇒ 不回 500；那一層照簽並說明。"""
    client, h = loan
    body = loan_definition()
    body["workflow"]["states"][1]["approval"]["tiers"][1]["when"] = "total / (qty - 2) > 1"   # 樣本 qty＝1 算得出來；qty＝2 才除以 0
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h["super"], json={"body": body})
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h["super"], json={}).status_code == 200
    rec = _new(client, h, qty=2)
    r = client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=h["req"], json={})
    assert r.status_code == 200 and len(r.json()["approval"]["tiers"]) == 2
    assert any("無法計算" in n for n in r.json()["notices"])


def test_custom_module_tier_condition_false_still_skips(loan):
    """正對照：條件明確不成立（False）⇒ 照舊跳過那一層。"""
    client, h = loan
    rec = _new(client, h)                                           # 6000 ≤ 10000
    r = client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=h["req"], json={})
    assert len(r.json()["approval"]["tiers"]) == 1


# ── 稽核 D（AUDIT-D-C-P4P5P8）C-M3／C-M5／C-S1～S5 ──────────────────────────

def _auto_loop_definition():
    """兩個簽核狀態、條件都不成立、on_approved 互相指向。"""
    b = loan_definition()
    b["workflow"]["states"] = [
        {"key": "draft", "label": "草稿"},
        {"key": "p1", "label": "一", "approval": {"tiers": [{"approvers": [{"username": "cm_mgr"}], "when": "qty > 999"}],
                                                   "on_approved": "p2", "on_rejected": "done"}},
        {"key": "p2", "label": "二", "approval": {"tiers": [{"approvers": [{"username": "cm_mgr"}], "when": "qty > 999"}],
                                                   "on_approved": "p1", "on_rejected": "done"}},
        {"key": "done", "label": "結束", "final": True},
    ]
    b["workflow"]["transitions"] = [{"key": "submit", "label": "送審", "from": "draft", "to": "p1"}]
    return b


def test_auto_approve_cycle_is_refused_at_publish():
    """C-M3（發布時）：簽核狀態的 on_approved 互相指向 ⇒ 發布前就擋下並指出位置。"""
    got = _paths(_auto_loop_definition())
    assert any(k.endswith(".approval.on_approved") and "循環" in m for k, m in got.items())


def test_auto_approve_cycle_at_runtime_is_a_clear_409_not_500(loan, monkeypatch):
    """C-M3（執行時）：繞過發布驗證（例：舊版定義）也要回明確錯誤，不是 RecursionError；單據維持草稿。"""
    client, h = loan
    import db
    from core import definitions as D
    monkeypatch.setitem(D._VALIDATORS, "custom_module", lambda body, key: [])
    conn = db.get_db()
    try:
        D.save_draft(conn, "custom_module", KEY, "company", _auto_loop_definition(), "x")
        D.publish(conn, "custom_module", KEY, "company")
    finally:
        conn.close()
    rec = _new(client, h)
    r = client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=h["req"], json={})
    assert r.status_code == 409 and "循環" in r.json()["detail"]
    assert client.get("/api/custom/%s/records/%s" % (KEY, rec["record_no"]), headers=h["req"]).json()["status"] == "draft"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "NaN", "1e999"])
def test_number_field_refuses_nan_and_infinity(loan, bad):
    """C-M5：非有限的數字在寫入前擋下（400、指出欄位），資料庫沒有這一筆。"""
    client, h = loan
    r = client.post("/api/custom/%s/records" % KEY, headers=h["req"], json={"values": {"item": "x", "qty": bad}})
    assert r.status_code == 400 and any(p["key"] == "qty" for p in r.json()["problems"])
    assert client.get("/api/custom/%s/records" % KEY, headers=h["req"]).json() == []


def test_nan_that_slips_past_coerce_is_refused_at_write(loan, monkeypatch):
    """C-M5 第二道防線：就算欄位轉換漏放了 NaN（例：之後新增的型別），寫入時也擋下（400），資料庫沒有這一筆。"""
    client, h = loan
    from helpers import custom_modules as cm
    real = cm.clean_values
    monkeypatch.setattr(cm, "clean_values", lambda conn, body, values: (lambda r: ({**r[0], "qty": float("nan")}, r[1], r[2]))(real(conn, body, values)))
    r = client.post("/api/custom/%s/records" % KEY, headers=h["req"], json={"values": {"item": "x", "qty": 1}})
    assert r.status_code == 400 and any(p["key"] == "qty" for p in r.json()["problems"])
    monkeypatch.setattr(cm, "clean_values", real)
    assert client.get("/api/custom/%s/records" % KEY, headers=h["req"]).json() == []


def test_existing_nan_data_can_still_be_read(loan):
    """C-M5：修正前已經寫進去的 NaN 資料，讀單與列表都不可以 500（非有限值讀出為空值）。"""
    client, h = loan
    rec = _new(client, h)
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE custom_records SET data_json=? WHERE record_no=?",
                     ('{"item": "舊", "qty": NaN, "total": Infinity}', rec["record_no"]))
        conn.commit()
    finally:
        conn.close()
    one = client.get("/api/custom/%s/records/%s" % (KEY, rec["record_no"]), headers=h["req"])
    assert one.status_code == 200 and one.json()["data"]["qty"] is None and one.json()["data"]["total"] is None
    assert client.get("/api/custom/%s/records" % KEY, headers=h["req"]).status_code == 200


def test_type_errors_in_conditions_are_caught_at_publish():
    """C-S1：`item > 5`（item 是文字）語法沒錯、執行才錯 ⇒ 用樣本資料試算，發布時就指出位置。"""
    b = loan_definition()
    b["workflow"]["states"][1]["approval"]["tiers"][1]["when"] = "item > 5"
    assert "試算失敗" in _paths(b)["workflow.states[1].approval.tiers[1].when"]


def test_initial_state_cannot_have_an_approval():
    """C-S3：起始狀態掛簽核永遠不會展開 ⇒ 發布時擋下。"""
    b = loan_definition()
    b["workflow"]["states"][0]["approval"] = copy.deepcopy(b["workflow"]["states"][1]["approval"])
    assert "起始狀態不可以掛簽核" in _paths(b)["workflow.states[0].approval"]


def test_permission_cannot_be_a_builtin_key_or_shared(client, make_user):
    """C-S4：不可以用內建模組的 key；不可以與另一個已發布的自訂模組共用。"""
    b = loan_definition()
    b["permission"] = "cashier"
    assert "內建模組" in _paths(b)["permission"]
    h = _login(client, make_user, "cm_perm_super", role="superadmin")
    client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": loan_definition()})
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200
    client.put("/api/definitions/custom_module/other_loan/draft", headers=h, json={"body": loan_definition()})
    r = client.post("/api/definitions/custom_module/other_loan/publish", headers=h, json={})
    assert r.status_code == 422 and any(p["path"] == "permission" and "已被自訂模組" in p["message"] for p in r.json()["problems"])


def test_delegate_can_read_the_record_they_can_sign(loan, monkeypatch):
    """C-S2：簽核代理人可以簽，也要讀得到單據與輸出（沒有模組權限也一樣）；不是代理人照樣 403。"""
    client, h = loan
    rec = _new(client, h)
    client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=h["req"], json={})
    from helpers import tiered_approval as ta
    assert client.get("/api/custom/%s/records/%s" % (KEY, rec["record_no"]), headers=h["other"]).status_code == 403
    monkeypatch.setattr(ta, "active_delegators_for", lambda conn, u, today=None: {"cm_mgr"} if u == "cm_other" else set())
    assert client.get("/api/custom/%s/records/%s" % (KEY, rec["record_no"]), headers=h["other"]).status_code == 200
    assert client.get("/api/custom/%s/records/%s/output" % (KEY, rec["record_no"]), headers=h["other"]).status_code == 200


def test_publish_and_restore_take_the_write_lock(monkeypatch):
    """C-S5：發布／還原讀草稿之前先拿寫鎖（begin_write）。"""
    import sqlite3
    import core.txn as txn
    from core import definitions as D, migrations
    calls = []
    real = txn.begin_write
    monkeypatch.setattr(txn, "begin_write", lambda conn: calls.append(1) or real(conn))
    monkeypatch.delitem(D._VALIDATORS, "layout", raising=False)   # 驗儲存語意；P9 的 layout 驗證器要 module:<模組>
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE module_schema_versions (module TEXT PRIMARY KEY, version INTEGER, applied_at TEXT)")
    migrations._core_v1_ui_definitions(conn)
    D.save_draft(conn, "layout", "k", "company", {"a": 1})
    D.publish(conn, "layout", "k", "company")
    D.restore(conn, "layout", "k", "company", 1)
    assert len(calls) == 2
    conn.close()


# ── U14（使用者 2026-09-26 裁示）：草稿只有建立者與超級管理員可以修改、送出 ─────────

def test_draft_can_only_be_changed_by_its_creator_or_a_superadmin(loan, make_user, client):
    c, h = loan
    other = _login(client, make_user, "cm_same_perm", modules=["custom.equipment_loan"])     # 同一個模組權限
    rec = _new(c, h)
    no = rec["record_no"]
    url = "/api/custom/%s/records/%s" % (KEY, no)
    got = c.get(url, headers=other)
    assert got.status_code == 200 and got.json()["canEdit"] is False                      # 同權限的人：看得到、不能改
    assert c.put(url, headers=other, json={"values": {"item": "改", "qty": 1}}).status_code == 403
    assert c.post(url + "/transitions/submit", headers=other, json={}).status_code == 403
    assert c.get(url, headers=h["req"]).json()["canEdit"] is True                        # 正對照：建立者
    assert c.put(url, headers=h["req"], json={"values": {"item": "改", "qty": 1}}).status_code == 200
    assert c.get(url, headers=h["super"]).json()["canEdit"] is True                      # 超級管理員
    assert c.post(url + "/transitions/submit", headers=h["super"], json={}).status_code == 200
    assert c.get(url, headers=h["req"]).json()["canEdit"] is False                       # 送出之後誰都不能改內容


@pytest.mark.parametrize("expr,want", [
    ("round(2.5)", 3), ("round(3.5)", 4), ("round(-2.5)", -3),      # 不是銀行家捨入（2.5 ⇒ 2）
    ("round(738.5)", 739),                                          # 補充保費同一類（AUDIT-D-R1-R3 D-1）
    ("round(1.005, 2)", 1.01),                                      # 浮點 1.00499… 不可以變 1.0
    ("round(10 / 3, 2)", 3.33), ("round(1234, -2)", 1200),
])
def test_formula_round_is_half_up(expr, want):
    """C-M4：公式的 round＝四捨五入，與法規金額用同一支 L1 函式（helpers.legal_params.round_half_up）。"""
    from helpers import formula as F
    got = F.evaluate(expr, {})
    assert got == want and type(got) is type(want), (expr, got)
