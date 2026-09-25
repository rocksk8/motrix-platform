# -*- coding: utf-8 -*-
"""P4／P5（CUSTOMIZATION-SPEC §3.5／§3.6）：定義文件庫、模組 migration 執行器、自訂欄位命名空間、定義 API。

⚙️ 反向控制：每一條「不准」都有一題證明它真的擋（發布前驗證、已發布不可改、還原不改歷史、
自訂欄位不可與核心欄位同名、未定義的鍵被丟掉並回報、非超級管理員被拒）。
"""
import json
import sqlite3

import pytest


# ── 共用：一個只有 module_schema_versions＋ui_definitions 的空庫 ───────────────────

@pytest.fixture()
def defs_conn(tmp_path):
    from core import migrations
    conn = sqlite3.connect(str(tmp_path / "defs.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE module_schema_versions (module TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0, "
                 "applied_at TEXT NOT NULL DEFAULT '')")
    migrations._core_v1_ui_definitions(conn)
    yield conn
    conn.close()


@pytest.fixture()
def fresh_registry(monkeypatch):
    """模組 migration 登記表換成空的（不影響真的 core 登記）。"""
    from core import migrations
    monkeypatch.setattr(migrations, "_REGISTRY", {})
    return migrations


# ── 模組 migration 執行器（CORE-SPEC §6）──────────────────────────────────────

def _versions_table(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "m.db"))
    conn.execute("CREATE TABLE module_schema_versions (module TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0, "
                 "applied_at TEXT NOT NULL DEFAULT '')")
    return conn


def test_module_migrations_run_in_order_record_version_and_are_not_rerun(fresh_registry, tmp_path):
    m = fresh_registry
    ran = []
    m.register("demo_mod", 1, lambda c: ran.append(1) or c.execute("CREATE TABLE IF NOT EXISTS demo_t (id INTEGER)"))
    m.register("demo_mod", 2, lambda c: ran.append(2) or c.execute("ALTER TABLE demo_t ADD COLUMN note TEXT"))
    conn = _versions_table(tmp_path)
    assert m.run_all(conn) == {"demo_mod": (0, 2)}
    assert ran == [1, 2] and m.current_version(conn, "demo_mod") == 2
    assert m.run_all(conn) == {} and ran == [1, 2]                     # 已到最新 ⇒ 不重跑


def test_module_migrations_failure_stops_at_the_previous_version_and_resumes(fresh_registry, tmp_path):
    m = fresh_registry
    state = {"fail": True}

    def v2(c):
        if state["fail"]:
            raise RuntimeError("第二支壞了")
        c.execute("CREATE TABLE IF NOT EXISTS demo_v2 (id INTEGER)")
    m.register("demo_mod", 1, lambda c: c.execute("CREATE TABLE IF NOT EXISTS demo_v1 (id INTEGER)"))
    m.register("demo_mod", 2, v2)
    conn = _versions_table(tmp_path)
    with pytest.raises(RuntimeError):
        m.run_all(conn)
    assert m.current_version(conn, "demo_mod") == 1                     # 停在上一版，不假裝成功
    state["fail"] = False
    assert m.run_all(conn) == {"demo_mod": (1, 2)}                      # 修好後從失敗那支接著跑


def test_module_migrations_versions_must_be_contiguous_from_one(fresh_registry, tmp_path):
    m = fresh_registry
    m.register("demo_mod", 1, lambda c: None)
    m.register("demo_mod", 3, lambda c: None)
    with pytest.raises(ValueError, match="連續"):
        m.run_all(_versions_table(tmp_path))


def test_module_migrations_same_version_cannot_be_two_functions(fresh_registry):
    m = fresh_registry
    m.register("demo_mod", 1, lambda c: None)
    with pytest.raises(ValueError):
        m.register("demo_mod", 1, lambda c: None)


def test_module_migrations_core_table_is_created_by_init_db(client):
    """init_db 之後：core 的第一支 migration 已跑、版本記在 module_schema_versions。"""
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT version FROM module_schema_versions WHERE module='core'").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='ui_definitions'").fetchone()[0] == 1
    finally:
        conn.close()


# ── 定義文件庫 ───────────────────────────────────────────────────────────────

def test_definitions_draft_publish_versions_and_restore_never_rewrite_history(defs_conn, monkeypatch):
    from core import definitions as D
    # 本題驗儲存語意（與 kind 無關）；P9 起 layout 有真的驗證器（key 要 module:<模組>）⇒ 這裡拿掉
    monkeypatch.delitem(D._VALIDATORS, "layout", raising=False)
    D.save_draft(defs_conn, "layout", "quotations.list", "company", {"columns": ["a"]}, "boss")
    assert D.get(defs_conn, "layout", "quotations.list", "company") is None      # 草稿不是發布版
    v1 = D.publish(defs_conn, "layout", "quotations.list", "company", "第一版", "boss")
    assert v1["version"] == 1 and v1["status"] == "published" and v1["published_by"] == "boss"
    assert D.get(defs_conn, "layout", "quotations.list", "company", 0) is None   # 發布後草稿刪掉
    D.save_draft(defs_conn, "layout", "quotations.list", "company", {"columns": ["a", "b"]}, "boss")
    assert D.get(defs_conn, "layout", "quotations.list", "company", 1)["body"] == {"columns": ["a"]}  # 已發布的不被草稿改
    D.publish(defs_conn, "layout", "quotations.list", "company", "", "boss")
    v3 = D.restore(defs_conn, "layout", "quotations.list", "company", 1, "", "boss")
    assert v3["version"] == 3 and v3["body"] == {"columns": ["a"]} and "還原自第 1 版" in v3["note"]
    assert [r["version"] for r in D.versions(defs_conn, "layout", "quotations.list", "company")] == [3, 2, 1]
    assert D.get(defs_conn, "layout", "quotations.list", "company", 2)["body"] == {"columns": ["a", "b"]}


def test_restore_says_when_an_older_draft_is_still_pending(defs_conn, monkeypatch):
    """C-O1：還原不動草稿；回應的 draftPending 告訴畫面「還有一份未發布的草稿，發布會蓋掉這次還原」。"""
    from core import definitions as D
    monkeypatch.delitem(D._VALIDATORS, "layout", raising=False)   # 驗儲存語意；P9 的 layout 驗證器要 module:<模組>
    D.save_draft(defs_conn, "layout", "k", "company", {"columns": ["a"]})
    D.publish(defs_conn, "layout", "k", "company")
    D.save_draft(defs_conn, "layout", "k", "company", {"columns": ["a", "b"]})
    D.publish(defs_conn, "layout", "k", "company")
    assert D.restore(defs_conn, "layout", "k", "company", 1)["draftPending"] is False
    D.save_draft(defs_conn, "layout", "k", "company", {"columns": ["zz"]})
    assert D.restore(defs_conn, "layout", "k", "company", 2)["draftPending"] is True
    assert D.get(defs_conn, "layout", "k", "company", 0)["body"] == {"columns": ["zz"]}     # 草稿本身不動


def test_definitions_publish_without_a_draft_is_refused(defs_conn):
    from core import definitions as D
    with pytest.raises(D.DefinitionError, match="沒有草稿"):
        D.publish(defs_conn, "layout", "x", "company")


def test_definitions_validator_blocks_publish_and_returns_positions(defs_conn, monkeypatch):
    from core import definitions as D
    monkeypatch.setitem(D._VALIDATORS, "layout",
                        lambda body, key: [{"path": "columns[1]", "message": "未知欄位"}] if "zz" in body.get("columns", []) else [])
    D.save_draft(defs_conn, "layout", "k", "company", {"columns": ["a", "zz"]})
    with pytest.raises(D.DefinitionError) as e:
        D.publish(defs_conn, "layout", "k", "company")
    assert e.value.problems == [{"path": "columns[1]", "message": "未知欄位"}]
    assert D.versions(defs_conn, "layout", "k", "company")[0]["status"] == "draft"   # 沒發布，草稿還在


def test_definitions_restore_is_validated_against_the_current_environment(defs_conn, monkeypatch):
    """舊版可能引用已經不存在的東西 ⇒ 還原前也要過驗證器。"""
    from core import definitions as D
    monkeypatch.delitem(D._VALIDATORS, "layout", raising=False)   # 驗儲存語意；P9 的 layout 驗證器要 module:<模組>
    D.save_draft(defs_conn, "layout", "k", "company", {"columns": ["old"]})
    D.publish(defs_conn, "layout", "k", "company")
    monkeypatch.setitem(D._VALIDATORS, "layout", lambda body, key: [{"path": "columns[0]", "message": "欄位已刪除"}])
    with pytest.raises(D.DefinitionError) as e:
        D.restore(defs_conn, "layout", "k", "company", 1)
    assert e.value.problems and len(D.versions(defs_conn, "layout", "k", "company")) == 1


def test_definitions_resolve_order_role_then_company_then_default(defs_conn, monkeypatch):
    from core import definitions as D
    monkeypatch.delitem(D._VALIDATORS, "layout", raising=False)   # 驗儲存語意；P9 的 layout 驗證器要 module:<模組>
    monkeypatch.setitem(D._DEFAULTS, "layout", lambda key: {"from": "default"})
    assert D.resolve(defs_conn, "layout", "k", "sales") == ({"from": "default"}, "default")
    D.save_draft(defs_conn, "layout", "k", "company", {"from": "company"})
    D.publish(defs_conn, "layout", "k", "company")
    assert D.resolve(defs_conn, "layout", "k", "sales") == ({"from": "company"}, "company v1")
    D.save_draft(defs_conn, "layout", "k", "role:sales", {"from": "role"})
    D.publish(defs_conn, "layout", "k", "role:sales")
    assert D.resolve(defs_conn, "layout", "k", "sales") == ({"from": "role"}, "role:sales v1")
    assert D.resolve(defs_conn, "layout", "k", "admin")[1] == "company v1"          # 別的角色不套
    monkeypatch.delitem(D._DEFAULTS, "layout")
    assert D.resolve(defs_conn, "layout", "other", None) == (None, "none")


@pytest.mark.parametrize("kind,key,scope", [("nope", "k", "company"), ("layout", "Bad Key", "company"),
                                            ("layout", "k", "user:bob"), ("layout", "", "company")])
def test_definitions_reject_unknown_kind_bad_key_and_bad_scope(defs_conn, kind, key, scope):
    from core import definitions as D
    with pytest.raises(D.DefinitionError):
        D.save_draft(defs_conn, kind, key, scope, {})


def test_definitions_diff_reports_paths(defs_conn):
    from core import definitions as D
    a = {"blocks": [{"type": "meta", "title": "A"}, {"type": "x"}], "theme": "t"}
    b = {"blocks": [{"type": "meta", "title": "B"}], "theme": "t", "extra": 1}
    assert D.diff(a, b) == [
        {"op": "change", "path": "blocks[0].title", "old": "A", "new": "B"},
        {"op": "remove", "path": "blocks[1]", "old": {"type": "x"}},
        {"op": "add", "path": "extra", "new": 1},
    ]
    assert D.diff(a, a) == []


def test_definitions_are_in_the_daily_json_and_cleared_for_demo():
    """資料分類 T1：跟著每日 JSON 匯出；demo 清空的表清單也有它。"""
    import archive
    import db
    assert "ui_definitions" in db.DEMO_CLEARED_TABLES
    assert "ui_definitions" in archive.backed_up_table_names()


# ── 自訂欄位（P4）───────────────────────────────────────────────────────────

def test_custom_fields_definition_problems_carry_positions():
    from helpers import custom_fields as cf
    body = {"fields": [
        {"key": "Bad", "label": "x", "type": "text"},
        {"key": "po_no", "label": "採購單號", "type": "text"},
        {"key": "po_no", "label": "重複", "type": "text"},
        {"key": "amount", "label": "撞核心", "type": "number"},
        {"key": "grade", "label": "等級", "type": "select", "options": []},
        {"key": "due", "label": "", "type": "date", "default": "不是日期"},
        {"key": "idno", "label": "身分證", "type": "text", "dataClass": "F9"},
        {"key": "kind", "label": "型別", "type": "blob"},
    ]}
    got = {(p["path"], p["message"].split("：")[0]) for p in cf.validate_definition(body, "invoice_vouchers", ("amount",))}
    assert ("fields[0].key", "key 只能用小寫英文、數字與底線，英文開頭，最長 40 字") in got
    assert ("fields[2].key", "key 重複") in got
    assert ("fields[3].key", "不可以與核心欄位同名") in got
    assert ("fields[4].options", "下拉選單必須有至少一個選項") in got
    assert ("fields[5].label", "必須有顯示名稱") in got
    assert ("fields[5].default", "預設值與型別不符") in got
    assert ("fields[6].dataClass", "資料分類只能是 T1 或 F2") in got
    assert any(p == "fields[7].type" for p, _m in got)
    assert cf.validate_definition({"fields": [{"key": "po_no", "label": "採購單號", "type": "text"}]}) == []
    assert cf.validate_definition({}) == [{"path": "fields", "message": "fields 必須是清單"}]


def test_custom_fields_clean_coerces_reports_and_drops():
    from helpers import custom_fields as cf
    definition = {"fields": [
        {"key": "po_no", "label": "採購單號", "type": "text", "required": True},
        {"key": "qty", "label": "數量", "type": "number"},
        {"key": "due", "label": "到期日", "type": "date"},
        {"key": "grade", "label": "等級", "type": "select", "options": ["A", "B"], "default": "A"},
        {"key": "urgent", "label": "急件", "type": "checkbox"},
    ]}
    out, errors, dropped = cf.clean({"po_no": "PO-1", "qty": "3", "due": "2026-10-01T00:00:00",
                                     "urgent": False, "ghost": "x"}, definition)
    assert out == {"po_no": "PO-1", "qty": 3, "due": "2026-10-01", "grade": "A", "urgent": False}
    assert errors == [] and dropped == ["ghost"]                     # 未定義的鍵：丟掉並回報，不默默保留
    out, errors, _d = cf.clean({"qty": "三", "grade": "C", "urgent": "yes"}, definition)
    keys = {e["key"] for e in errors}
    assert keys == {"po_no", "qty", "grade", "urgent"}                # 必填沒填、型別不符都指出是哪一欄
    assert "po_no" not in out and "qty" not in out


def test_custom_fields_empty_value_is_not_zero_or_false():
    """null 不等於 0：沒填就是沒填，不寫成 0 或 False。"""
    from helpers import custom_fields as cf
    definition = {"fields": [{"key": "qty", "label": "數量", "type": "number"},
                             {"key": "ok", "label": "OK", "type": "checkbox"}]}
    assert cf.clean({"qty": "", "ok": None}, definition) == ({}, [], [])
    assert cf.clean({"qty": 0, "ok": False}, definition)[0] == {"qty": 0, "ok": False}


# ── 定義 API（僅超級管理員）─────────────────────────────────────────────────

def _headers(client, make_user, name, role):
    u, p = make_user(name, "Defs-Pass-123", role=role)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_definitions_api_lifecycle_for_superadmin(client, make_user):
    h = _headers(client, make_user, "defs_boss", "superadmin")
    base = "/api/definitions/custom_fields/invoice_vouchers"
    body = {"fields": [{"key": "po_no", "label": "採購單號", "type": "text"}]}
    r = client.put(base + "/draft", headers=h, json={"body": body})
    assert r.status_code == 200 and r.json()["problems"] == []
    r = client.post(base + "/publish", headers=h, json={"note": "加採購單號"})
    assert r.status_code == 200 and r.json()["version"] == 1
    client.put(base + "/draft", headers=h, json={"body": {"fields": body["fields"] + [
        {"key": "qty", "label": "數量", "type": "number"}]}})
    ch = client.get(base + "/diff", headers=h, params={"a": "latest", "b": "draft"}).json()["changes"]
    assert ch == [{"op": "add", "path": "fields[1]", "new": {"key": "qty", "label": "數量", "type": "number"}}]
    client.post(base + "/publish", headers=h, json={})
    r = client.post(base + "/restore/1", headers=h, json={})
    assert r.status_code == 200 and r.json()["version"] == 3 and r.json()["body"] == body
    got = client.get(base, headers=h).json()
    assert [v["version"] for v in got["versions"]] == [3, 2, 1] and got["draft"] is None
    assert client.get(base + "/resolve", headers=h).json()["source"] == "company v3"
    assert client.get(base + "/versions/9", headers=h).status_code == 404


def test_definitions_api_publish_with_problems_is_422_and_keeps_the_draft(client, make_user):
    h = _headers(client, make_user, "defs_boss2", "superadmin")
    base = "/api/definitions/custom_fields/invoice_vouchers"
    client.put(base + "/draft", headers=h, json={"body": {"fields": [{"key": "amount", "label": "撞核心", "type": "number"}]}})
    r = client.post(base + "/publish", headers=h, json={})
    assert r.status_code == 422 and r.json()["problems"][0]["path"] == "fields[0].key"
    assert client.get(base, headers=h).json()["draft"] is not None


@pytest.mark.parametrize("role", ["admin", "user"])
def test_definitions_api_refuses_non_superadmin(client, make_user, role):
    h = _headers(client, make_user, "defs_%s" % role, role)
    assert client.get("/api/definitions/layout/x", headers=h).status_code == 403
    assert client.put("/api/definitions/layout/x/draft", headers=h, json={"body": {}}).status_code == 403


def test_definitions_api_unknown_kind_is_400(client, make_user):
    h = _headers(client, make_user, "defs_boss3", "superadmin")
    assert client.put("/api/definitions/nope/x/draft", headers=h, json={"body": {}}).status_code == 400


# ── 輸出版型覆寫（P2 × P5）──────────────────────────────────────────────────

def test_output_template_validation_points_at_the_block(client, make_user):
    h = _headers(client, make_user, "defs_boss4", "superadmin")
    r = client.post("/api/definitions/output_template/invoice_voucher/validate", headers=h,
                    json={"body": {"theme": "voucher_standard", "blocks": [{"type": "meta", "fields": []}, {"type": "nope"}]}})
    assert r.status_code == 200 and {"path": "blocks[1].type", "message": r.json()["problems"][0]["message"]} == r.json()["problems"][0]


def test_output_template_preview_renders_sample_and_rejects_bad_templates(client, make_user):
    from helpers import doc_template as dt
    h = _headers(client, make_user, "defs_boss5", "superadmin")
    url = "/api/definitions/output_template/invoice_voucher/preview"
    r = client.post(url, headers=h, json={"body": dt.load_default("invoice_voucher")})
    assert r.status_code == 200 and "IV-202609-0001" in r.text and "範例客戶股份有限公司" in r.text
    r = client.post(url, headers=h, json={"body": {"theme": "voucher_standard", "blocks": [{"type": "nope"}]}})
    assert r.status_code == 422 and r.json()["problems"][0]["path"] == "blocks[0].type"
    assert client.post(url, headers=h, json={"body": ["not", "a", "dict"]}).status_code == 422
    assert client.post("/api/definitions/output_template/unknown_doc/preview", headers=h, json={"body": {}}).status_code == 404


def _publish_voucher_template(title_suffix):
    import db
    from core import definitions as D
    from helpers import doc_template as dt
    body = dt.load_default("invoice_voucher")
    body["blocks"][2]["title"] += title_suffix                   # identity_header 的標題（一定會印出來）
    conn = db.get_db()
    try:
        D.save_draft(conn, "output_template", "invoice_voucher", "company", body, "boss")
        return D.publish(conn, "output_template", "invoice_voucher", "company", "", "boss")
    finally:
        conn.close()


def test_invoice_voucher_output_uses_the_published_company_override(client):
    """沒有覆寫 ⇒ 預設（與改版前逐位元組相同，另有凍結題守）；公司發布覆寫版 ⇒ 用它；單據凍結的版本 ⇒ 用那一版。"""
    import pdf_gen
    from routers.definitions import _invoice_voucher_sample_view  # noqa: F401 — 樣本視圖的來源單據
    v = {"voucherNo": "IV-P5-1", "quoteNo": "Q-1", "status": "待簽核", "scope": "items", "createdAt": "2026-09-25T09:00:00",
         "customerName": "客戶", "customerTaxId": "12345678", "projectName": "工程", "amount": 105, "pretaxAmount": 100,
         "taxAmount": 5, "selectedItems": [], "quoteItems": [], "approval": {}, "customFields": {}}
    base = pdf_gen._build_invoice_voucher_html(dict(v))
    first = _publish_voucher_template("（覆寫一）")
    over = pdf_gen._build_invoice_voucher_html(dict(v))
    assert over != base and "開票申請憑據（覆寫一）" in over
    _publish_voucher_template("（覆寫二）")
    frozen = pdf_gen._build_invoice_voucher_html(dict(v, outputTemplate={"scope": "company", "version": first["version"]}))
    assert frozen == over                                           # 凍結在第一版：之後的發布不影響它
    assert pdf_gen._build_invoice_voucher_html(dict(v)) != over      # 沒凍結的用最新發布版


def test_invoice_voucher_output_falls_back_to_default_when_the_store_breaks(client, monkeypatch, caplog):
    """覆寫層出錯不可以讓單據印不出來：讀定義失敗 ⇒ 程式預設＋WARNING。"""
    import logging
    import pdf_gen
    from core import definitions as D
    v = {"voucherNo": "IV-P5-2", "quoteNo": "Q-1", "status": "待簽核", "scope": "items", "createdAt": "2026-09-25T09:00:00",
         "customerName": "客戶", "amount": 0, "selectedItems": [], "quoteItems": [], "approval": {}}
    base = pdf_gen._build_invoice_voucher_html(dict(v))
    _publish_voucher_template("（覆寫）")

    def _boom(*a, **k):
        raise sqlite3.OperationalError("no such table: ui_definitions")
    monkeypatch.setattr(D, "get", _boom)
    with caplog.at_level(logging.WARNING, logger=pdf_gen.logger.name):
        assert pdf_gen._build_invoice_voucher_html(dict(v)) == base
    assert "讀輸出版型覆寫失敗" in caplog.text
