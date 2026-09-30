# -*- coding: utf-8 -*-
"""建構器第三輪 S1（2026-09-30）：新欄位型別、明細表（table）、`total/avg/count`、`round_half_up`、金流性質驗證。

- 新型別只給自訂模組（`MODULE_TYPES`）；P4 內建單據的 customFields 仍是原本 5 種（反向控制）。
- 明細表：逐列逐欄 `_coerce`、列內公式、整列空白丟掉、列數限制、索引只記列數。
- `round` 與 `round_half_up` 都是四捨五入（.5 進位）：12,562.5 → 12,563（營業稅規定；Python 內建 round 會給 12,562）。
"""
import copy

import pytest

from helpers import custom_fields as CF
from helpers import custom_modules as CM
from helpers import formula as FX


# ── 新型別 ───────────────────────────────────────────────────────────────

def test_module_types_extend_but_p4_types_do_not():
    assert set(CF.EXT_TYPES) <= set(CF.MODULE_TYPES) and set(CF.TYPES) <= set(CF.MODULE_TYPES)
    assert "table" in CM.FIELD_TYPES and "textarea" in CM.FIELD_TYPES
    # 反向控制：P4 內建單據的自訂欄位不接受新型別
    probs = CF.validate_definition({"fields": [{"key": "a", "label": "A", "type": "textarea"}]})
    assert probs and "未知型別" in probs[0]["message"]
    assert CF.validate_definition({"fields": [{"key": "a", "label": "A", "type": "textarea"}]}, types=CF.MODULE_TYPES) == []


@pytest.mark.parametrize("f,raw,ok,val", [
    ({"type": "textarea"}, "第一行\n第二行", True, "第一行\n第二行"),
    ({"type": "text", "maxLength": 3}, "abcd", False, None),
    ({"type": "text", "maxLength": 3}, "abc", True, "abc"),
    ({"type": "number", "min": 0, "max": 10}, 11, False, None),
    ({"type": "number", "min": 0, "max": 10}, "7", True, 7),
    ({"type": "date", "withTime": True}, "2026-09-30 09:05", True, "2026-09-30T09:05"),
    ({"type": "date", "withTime": True}, "2026-09-30 25:00", False, None),
    ({"type": "date"}, "2026-09-30T09:05", True, "2026-09-30"),
    ({"type": "radio", "options": ["甲", "乙"]}, "乙", True, "乙"),
    ({"type": "radio", "options": ["甲", "乙"]}, "丙", False, None),
    ({"type": "radio", "options": ["甲"], "allowOther": True}, " 其他原因 ", True, "其他原因"),
    ({"type": "select", "options": ["式"], "allowOther": True}, "坪", True, "坪"),
    ({"type": "checkboxes", "options": ["a", "b", "c"]}, ["a", "c", "a"], True, ["a", "c"]),
    ({"type": "checkboxes", "options": ["a", "b"]}, ["a", "z"], False, None),
    ({"type": "multiselect", "options": ["a", "b"], "minSelect": 2}, ["a"], False, None),
    ({"type": "multiselect", "options": ["a", "b"], "maxSelect": 1}, ["a", "b"], False, None),
    ({"type": "multiselect", "options": ["a", "b"]}, [], True, None),
    ({"type": "daterange"}, {"from": "2026-09-01", "to": "2026-09-05"}, True, {"from": "2026-09-01", "to": "2026-09-05"}),
    ({"type": "daterange"}, {"from": "2026-09-05", "to": "2026-09-01"}, False, None),
    ({"type": "daterange"}, {"from": "2026-09-05"}, False, None),
    ({"type": "daterange", "withTime": True}, {"from": "2026-09-01 09:00", "to": "2026-09-01 18:00"}, True,
     {"from": "2026-09-01T09:00", "to": "2026-09-01T18:00"}),
])
def test_coerce_new_types(f, raw, ok, val):
    got_ok, got, _msg = CF._coerce(f, raw)
    assert got_ok is ok
    if ok:
        assert got == val


def test_option_types_require_unique_nonempty_options():
    for t in CF.OPTION_TYPES:
        assert CF.validate_definition({"fields": [{"key": "a", "label": "A", "type": t}]}, types=CF.MODULE_TYPES)
        assert CF.validate_definition({"fields": [{"key": "a", "label": "A", "type": t, "options": ["x", "x"]}]},
                                      types=CF.MODULE_TYPES)
        assert CF.validate_definition({"fields": [{"key": "a", "label": "A", "type": t, "options": ["x", "y"]}]},
                                      types=CF.MODULE_TYPES) == []


# ── 公式：round_half_up、total／avg／count ───────────────────────────────

def test_round_and_round_half_up_are_half_up_not_bankers():
    assert FX.evaluate("round_half_up(x)", {"x": 12562.5}) == 12563
    assert FX.evaluate("round(x)", {"x": 12562.5}) == 12563            # 既有 round 也是四捨五入（不是銀行家捨入）
    assert round(12562.5) == 12562                                     # 對照：Python 內建會給 12562
    assert FX.evaluate("round_half_up(x, 2)", {"x": 1.005}) == 1.01    # 浮點陷阱：1.005 也要進位
    assert FX.evaluate("round_half_up(x * 0.05)", {"x": 251250}) == 12563   # 251,250 × 5% = 12,562.5


def test_table_functions_and_empty_semantics():
    v = {"t": [{"a": 2, "b": 3}, {"a": None, "b": 5}, {"a": 4}]}
    assert FX.evaluate('total(t, "a")', v) == 6
    assert FX.evaluate('avg(t, "b")', v) == 4
    assert FX.evaluate("count(t)", v) == 3
    assert FX.evaluate('total(t, "zz")', v) == 0                        # 全空 ⇒ 0
    assert FX.evaluate('avg(t, "zz")', v) is None                       # 平均沒有數字 ⇒ 空值（不是 0）
    assert FX.evaluate('total(t, "a")', {}) == 0 and FX.evaluate("count(t)", {}) == 0
    with pytest.raises(FX.FormulaError):
        FX.evaluate('total(t, "a")', {"t": [{"a": "abc"}]})


def test_table_function_checks():
    tables = {"t": ["a"]}
    assert FX.check('total(t, "a")', ["t"], tables) == []
    assert FX.check('total(t, "q")', ["t"], tables)                     # 不是可加總欄
    assert FX.check('total(x, "a")', ["t", "x"], tables)                # x 不是明細表
    assert FX.check("t + 1", ["t"], tables)                             # 明細表不能直接運算
    assert FX.check("total(t)", ["t"], tables) and FX.check('count(t, "a")', ["t"], tables)
    assert FX.check("total(t, a)", ["t", "a"], tables)                  # 欄 key 必須是字串
    assert FX.references('total(t, "a") + x') == {"t", "x"}             # 依賴表與 x（計算順序用）


# ── 明細表 ───────────────────────────────────────────────────────────────

def _table(**kw):
    t = {"key": "lines", "label": "明細", "type": "table", "columns": [
        {"key": "name", "label": "品名", "type": "text", "required": True},
        {"key": "qty", "label": "數量", "type": "number", "min": 0},
        {"key": "price", "label": "單價", "type": "number", "min": 0},
        {"key": "amt", "label": "金額", "type": "formula", "formula": "qty * price"}]}
    t.update(kw)
    return t


def _module(tax="應稅"):
    return {"name": "報價測試", "permission": "custom.qt", "numbering": {"prefix": "QT", "date": "YYYYMMDD", "digits": 4},
            "fields": [
                {"key": "tax", "label": "稅別", "type": "radio", "options": ["應稅", "免稅"]},
                _table(),
                {"key": "sub", "label": "小計", "type": "formula", "formula": 'total(lines, "amt")'},
                {"key": "vat", "label": "稅額", "type": "formula", "formula": 'if(tax == "應稅", round_half_up(sub * 0.05), 0)'},
                {"key": "grand", "label": "合計", "type": "formula", "formula": "sub + vat"},
                {"key": "inv", "label": "發票日", "type": "date"},
                {"key": "case_no", "label": "關聯案件", "type": "text"}],
            "workflow": {"initial": "draft", "states": [
                {"key": "draft", "label": "草稿"},
                {"key": "pending", "label": "簽核中", "approval": {"tiers": [{"approvers": [{"username": "x"}]}],
                                                                  "on_approved": "done", "on_rejected": "draft"}},
                {"key": "done", "label": "完成", "final": True}],
                "transitions": [{"key": "go", "label": "送審", "from": "draft", "to": "pending"}]}}


def test_module_with_table_validates():
    assert CM.validate_module(_module(), "qt") == []


def test_table_definition_problems_point_at_the_spot():
    b = _module()
    b["fields"][1]["columns"][3]["formula"] = "qty * nope"
    b["fields"][1]["columns"].append({"key": "qty", "label": "重複", "type": "number"})
    b["fields"][1]["columns"].append({"key": "sub_t", "label": "巢狀", "type": "table"})
    b["fields"][1]["maxRows"] = 999
    got = {p["path"]: p["message"] for p in CM.validate_module(b, "qt")}
    assert "fields[1].columns[3].formula" in got and "fields[1].columns[4].key" in got
    assert "fields[1].columns[5].type" in got and "fields[1].maxRows" in got
    b = _module()
    b["fields"][2]["formula"] = 'total(lines, "name")'                   # name 不是數值欄
    assert any(p["path"] == "fields[2].formula" for p in CM.validate_module(b, "qt"))
    b = _module()
    b["fields"][1]["columns"] = []
    assert any(p["path"] == "fields[1].columns" for p in CM.validate_module(b, "qt"))


def test_table_values_row_formulas_totals_and_tax_boundary():
    body = _module()
    vals, errs, dropped = CM.clean_values(None, body, {
        "tax": "應稅",
        "lines": [{"name": "A", "qty": 5, "price": 50250}, {"name": "", "qty": None, "price": ""}]})
    assert errs == [] and dropped == []
    assert vals["lines"] == [{"name": "A", "qty": 5, "price": 50250, "amt": 251250}]      # 整列空白的丟掉
    assert vals["sub"] == 251250 and vals["vat"] == 12563 and vals["grand"] == 263813     # 12,562.5 → 12,563
    vals2, _e, _d = CM.clean_values(None, body, {"tax": "免稅", "lines": [{"name": "A", "qty": 1, "price": 100}]})
    assert vals2["vat"] == 0 and vals2["grand"] == 100


def test_table_errors_carry_row_paths_and_limits():
    body = _module()
    _v, errs, _d = CM.clean_values(None, body, {"lines": [{"name": "A", "qty": -1, "price": 5}]})
    assert any(e["key"] == "lines[0].qty" and "不可小於" in e["message"] for e in errs)
    _v, errs, _d = CM.clean_values(None, body, {"lines": [{"qty": 1, "price": 5}]})     # 必填的品名沒填（該列不是空白）
    assert any(e["key"] == "lines[0].name" and "必填" in e["message"] for e in errs)
    _v, errs, _d = CM.clean_values(None, body, {"lines": "abc"})
    assert any(e["key"] == "lines" for e in errs)
    b2 = copy.deepcopy(body)
    b2["fields"][1].update(maxRows=2, minRows=1)
    _v, errs, _d = CM.clean_values(None, b2, {"lines": [{"name": str(i)} for i in range(3)]})
    assert any("最多 2 列" in e["message"] for e in errs)
    _v, errs, _d = CM.clean_values(None, b2, {"lines": []})
    assert any("至少 1 列" in e["message"] for e in errs)
    # 沒填明細、小計為 0（total 全空 ⇒ 0）；稅額 0
    b3 = copy.deepcopy(body)
    b3["fields"][1].pop("minRows", None)
    v, errs, _d = CM.clean_values(None, b3, {"tax": "應稅"})
    assert errs == [] and v["sub"] == 0 and v["vat"] == 0


def test_table_sample_values_and_index_counts_rows(client):
    body = _module()
    s = CM.sample_values(body)
    assert isinstance(s["lines"], list) and s["lines"] and "amt" in s["lines"][0] and s["sub"] == s["lines"][0]["amt"]
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO custom_records (module_key, record_no, def_version, status, data_json, approval_json, "
                     "created_by, created_at, updated_by, updated_at) VALUES ('qt','QT-1',1,'draft','{}','{}','u','2026-01-01','u','2026-01-01')")
        rid = conn.execute("SELECT id FROM custom_records WHERE record_no='QT-1'").fetchone()[0]
        CM._write_index(conn, rid, "qt", {"lines": [{"name": "a"}, {"name": "b"}], "tax": "應稅"})
        row = conn.execute("SELECT value_text, value_num FROM custom_record_values WHERE record_id=? AND field='lines'", (rid,)).fetchone()
        assert (row[0], row[1]) == ("2 筆", 2)                               # 只記列數，不把整份 JSON 塞進索引
        conn.rollback()
    finally:
        conn.close()


# ── 金流性質（附錄 B）驗證 ────────────────────────────────────────────────

def test_finance_validation():
    b = _module()
    b["fields"][4]["finance"] = {"kind": "income", "dateField": "inv", "caseField": "case_no"}     # 合計＝收入
    assert CM.validate_module(b, "qt") == []                                                     # 簽核 on_approved 推導出入帳狀態
    for bad, path in (
        ({"kind": "revenue"}, "fields[4].finance.kind"),
        ({"kind": "income", "dateField": "nope"}, "fields[4].finance.dateField"),
        ({"kind": "income", "dateField": "tax"}, "fields[4].finance.dateField"),              # 不是 date
        ({"kind": "income", "caseField": "inv"}, "fields[4].finance.caseField"),              # 不是 text／ref
    ):
        b2 = _module()
        b2["fields"][4]["finance"] = bad
        assert any(p["path"] == path for p in CM.validate_module(b2, "qt")), bad
    b3 = _module()
    b3["fields"][0]["finance"] = {"kind": "expense"}                                            # radio 不能設金流
    assert any(p["path"] == "fields[0].finance" for p in CM.validate_module(b3, "qt"))
    # 沒有簽核 ⇒ 沒有可推導的入帳狀態 ⇒ 要指定，否則擋發布
    b4 = _module()
    b4["fields"][4]["finance"] = {"kind": "expense"}
    b4["workflow"]["states"] = [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}]
    b4["workflow"]["transitions"] = [{"key": "go", "label": "完成", "from": "draft", "to": "done"}]
    assert any(p["path"] == "finance.postStates" for p in CM.validate_module(b4, "qt"))
    b4["finance"] = {"postStates": ["done"]}
    assert CM.validate_module(b4, "qt") == []
    b4["finance"] = {"postStates": ["nowhere"]}
    assert any(p["path"] == "finance.postStates" for p in CM.validate_module(b4, "qt"))
    # kind: none／缺 ⇒ 不計、不需要入帳狀態（反向控制）
    b5 = _module()
    b5["fields"][4]["finance"] = {"kind": "none"}
    assert CM.validate_module(b5, "qt") == []


# ── 目錄、範本、預設值 token、不可重複（API）────────────────────────────────

def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_catalog_lists_elements_specs_and_templates(client, make_user):
    sup = _login(client, make_user, "b3_sup", role="superadmin")
    cat = client.get("/api/custom-modules/catalog", headers=sup).json()
    types = set(cat["fieldTypes"])
    assert {"textarea", "radio", "checkboxes", "multiselect", "daterange", "table"} <= types
    assert {e["type"] for e in cat["fieldElements"]} <= types                      # 元件只准用目錄裡的型別
    assert {g["id"] for g in cat["elementGroups"]} >= {e["group"] for e in cat["fieldElements"]}
    assert set(cat["fieldTypeSpecs"]) == types                                     # 每個型別都有屬性規格
    assert all(a["kind"] in ("text", "int", "number", "bool", "options", "columns", "exts")
               for s in cat["fieldTypeSpecs"].values() for a in s["attrs"])
    assert "total" in cat["tableFunctions"] and "round_half_up" in cat["formulaFunctions"]
    assert cat["financeKinds"] == ["income", "expense"]
    q = next(t for t in cat["templates"] if t["key"] == "quotation")
    assert q["name"] == "報價單" and "table" in q["requires"]
    body = client.get("/api/custom-modules/templates/quotation", headers=sup).json()["body"]
    assert any(f["type"] == "table" for f in body["fields"])
    assert client.get("/api/custom-modules/templates/nope", headers=sup).status_code == 404
    other = _login(client, make_user, "b3_user", modules=[])
    assert client.get("/api/custom-modules/templates/quotation", headers=other).status_code == 403


def test_templates_with_problems_are_not_listed_but_reported(tmp_path, monkeypatch):
    import json as _j
    (tmp_path / "ok.json").write_text(_j.dumps(_j.load(open(CM._TEMPLATE_DIR + "/quotation.json", encoding="utf-8")), ensure_ascii=False),
                                      encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    bad_type = {"key": "badtype", "name": "x", "body": {"name": "x", "fields": [{"key": "a", "label": "A", "type": "hologram"}]}}
    (tmp_path / "badtype.json").write_text(_j.dumps(bad_type), encoding="utf-8")
    bad_flow = _j.load(open(CM._TEMPLATE_DIR + "/quotation.json", encoding="utf-8"))
    bad_flow["key"] = "badflow"
    bad_flow["body"]["workflow"]["initial"] = "nowhere"
    (tmp_path / "badflow.json").write_text(_j.dumps(bad_flow, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(CM, "_TEMPLATE_DIR", str(tmp_path))
    listed, gaps = CM.templates(include_gaps=True)
    assert [t["key"] for t in listed] == ["quotation"]
    assert {g["key"] for g in gaps} == {"broken.json", "badtype", "badflow"} and all(g["reason"] for g in gaps)
    assert CM.template_body("badtype") is None and CM.template_body("quotation") is not None


def test_quotation_template_end_to_end_tokens_tax_and_finance_fields(client, make_user):
    sup = _login(client, make_user, "b3_sup2", role="superadmin")
    body = client.get("/api/custom-modules/templates/quotation", headers=sup).json()["body"]
    body["permission"] = "custom.b3q"
    r = client.put("/api/definitions/custom_module/b3q/draft", headers=sup, json={"body": body})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    assert client.post("/api/definitions/custom_module/b3q/publish", headers=sup, json={}).status_code == 200
    r = client.post("/api/custom/b3q/records", headers=sup, json={"values": {
        "cust": "客戶甲", "lines": [{"name": "線材", "qty": 5, "unit": "坪", "price": 50250}]}})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["sub"] == 251250 and d["vat"] == 12563 and d["grand"] == 263813        # 251,250 × 5% = 12,562.5 → 12,563
    assert d["lines"][0]["unit"] == "坪" and d["lines"][0]["amt"] == 251250        # 單位可自打
    assert d["tax"] == "應稅5%"                                                     # 固定預設
    import datetime
    assert d["qdate"] == datetime.date.today().isoformat() and d["sales"] == "b3_sup2"   # token：填單當下、申請人（伺服器決定）
    # 前端送來的值優先於 token（有填就不覆蓋）
    r2 = client.post("/api/custom/b3q/records", headers=sup, json={"values": {
        "cust": "乙", "qdate": "2026-01-02", "lines": [{"name": "x", "qty": 1, "price": 10}], "tax": "免稅"}})
    assert r2.json()["data"]["qdate"] == "2026-01-02" and r2.json()["data"]["vat"] == 0
    # 必填的明細沒填 ⇒ 400 並指出
    r3 = client.post("/api/custom/b3q/records", headers=sup, json={"values": {"cust": "丙"}})
    assert r3.status_code == 400


def test_default_token_only_on_matching_types():
    b = _module()
    b["fields"][0]["default"] = {"$": "today"}                       # radio 不能用 today
    assert any(p["path"] == "fields[0].default" for p in CM.validate_module(b, "qt"))
    b = _module()
    b["fields"][5]["default"] = {"$": "now"}                         # date 沒有 withTime 不能用 now
    assert any(p["path"] == "fields[5].default" for p in CM.validate_module(b, "qt"))
    b["fields"][5].update(withTime=True)
    assert CM.validate_module(b, "qt") == []
    b["fields"][5]["default"] = {"$": "tomorrow"}
    assert any(p["path"] == "fields[5].default" for p in CM.validate_module(b, "qt"))


def test_unique_field_blocks_duplicates_on_create_and_update(client, make_user):
    sup = _login(client, make_user, "b3_sup3", role="superadmin")
    body = {"name": "唯一測試", "permission": "custom.b3u", "numbering": {"prefix": "UQ", "date": "YYYYMMDD", "digits": 4},
            "fields": [{"key": "code", "label": "代碼", "type": "text", "required": True, "unique": True}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "go", "label": "完成", "from": "draft", "to": "done"}]}}
    assert client.put("/api/definitions/custom_module/b3u/draft", headers=sup, json={"body": body}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/b3u/publish", headers=sup, json={}).status_code == 200
    a = client.post("/api/custom/b3u/records", headers=sup, json={"values": {"code": "X1"}})
    assert a.status_code == 200
    dup = client.post("/api/custom/b3u/records", headers=sup, json={"values": {"code": "X1"}})
    assert dup.status_code == 400 and "已有其他單據" in dup.text
    b = client.post("/api/custom/b3u/records", headers=sup, json={"values": {"code": "X2"}})
    no = b.json()["record_no"]
    up = client.put("/api/custom/b3u/records/%s" % no, headers=sup, json={"values": {"code": "X1"}})
    assert up.status_code == 400
    ok = client.put("/api/custom/b3u/records/%s" % no, headers=sup, json={"values": {"code": "X2"}})     # 自己不算重複
    assert ok.status_code == 200
