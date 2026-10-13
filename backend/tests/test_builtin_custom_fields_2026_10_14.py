# -*- coding: utf-8 -*-
"""T61 S5：內建畫面的自訂欄位（案件資訊先導）——契約題。設計：docs/platform/plans/T61-S5-FIELD-CATALOG-DESIGN.md。

證明的事：
1. 旗標關閉（預設）＝今天：端點回空、寫入不介入（用戶端送的 customFields 不存）、回應沒有 customFields 鍵。
2. 定義驗證：只有文字／日期／單選／勾選；沒有必填／預設值／公式；上限 20；與既有欄位同名擋；已發布欄位不能改型別。
3. 旗標開啟：欄位值經閘門存進 caseRecord.customFields（型別錯 400 指名欄位、未定義的鍵忽略、停用欄位的值保留、
   清掉＝鍵消失）；存檔後用戶端的基準與伺服器一致（連存兩次不會誤判成別人改過 ⇒ 沒有 409）。
4. 客戶輸出（PDF 視圖、版型、客戶預覽）不引用 customFields（附正對照）。
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KEY = "case_info"
DEF = "/api/definitions/custom_fields/" + KEY

TEXT = {"key": "f1", "label": "現場工頭", "type": "text"}
SEL = {"key": "f2", "label": "施工等級", "type": "select", "options": ["A", "B", "C"]}
DATE = {"key": "f3", "label": "進場日", "type": "date"}
CHK = {"key": "f4", "label": "已會勘", "type": "checkbox"}


def _boss(client, make_user, name="cf_boss"):
    u, p = make_user(name, "Lay-Pass-123", role="superadmin")[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _flag(on):
    import db
    from helpers import settings_registry as SR
    conn = db.get_db()
    try:
        SR.publish("builder_custom_fields", {"enabled": on}, reason="測試", user="cf_test", conn=conn)
        conn.commit()
    finally:
        conn.close()
    SR.invalidate("builder_custom_fields")


def _publish_def(client, h, fields):
    r = client.put(DEF + "/draft", headers=h, params={"scope": "company"}, json={"body": {"fields": fields}})
    assert r.status_code == 200 and not r.json().get("problems"), r.text
    r = client.post(DEF + "/publish", headers=h, params={"scope": "company"}, json={"note": "t"})
    assert r.status_code == 200, r.text
    return r.json()


def _validate(client, h, fields, key=KEY):
    r = client.post("/api/definitions/custom_fields/%s/validate" % key, headers=h, json={"body": {"fields": fields}})
    assert r.status_code == 200, r.text
    return r.json()["problems"]


@pytest.fixture
def case(client, make_user):
    """種子庫裡的一張案件（quote_no 'x'）＋超級管理員。"""
    import db
    from tests.platform import _response_keys as RK
    h = _boss(client, make_user)
    conn = db.get_db()
    try:
        RK.seed_every_table(conn)
        qn = conn.execute("SELECT quote_no FROM quotations ORDER BY id LIMIT 1").fetchone()[0]
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()[0] or "{}")
        d.setdefault("caseRecord", {})
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), qn))
        conn.commit()
    finally:
        conn.close()
    return h, qn


def _patch(client, h, qn, seg, base=None):
    return client.patch("/api/quotations/%s/case-record" % qn, headers=h,
                        json={"segments": {"customFields": seg}, "base": {"customFields": base}, "defaults": {}})


def _stored(qn):
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()[0] or "{}")
    finally:
        conn.close()
    return (d.get("caseRecord") or {}).get("customFields", "ABSENT")


# ── 1. 旗標關閉 ────────────────────────────────────────────────────────────
def test_flag_default_off_and_endpoint_is_empty_even_with_a_published_definition(client, make_user):
    from helpers import settings_registry as SR
    assert SR.get("builder_custom_fields", "enabled") is False
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT])
    r = client.get("/api/custom-fields/" + KEY, headers=h)
    assert r.status_code == 200 and r.json() == {"recordType": KEY, "enabled": False, "fields": []}
    assert client.get("/api/custom-fields/" + KEY).status_code == 401
    assert client.get("/api/custom-fields/no_such_type", headers=h).status_code == 404


def test_flag_off_ignores_client_custom_fields_and_response_has_no_such_key(client, make_user, case):
    h, qn = case
    _publish_def(client, h, [TEXT])                       # 有定義但旗標關：不介入
    r = _patch(client, h, qn, {"f1": "王大明"})
    assert r.status_code == 200, r.text
    assert _stored(qn) == "ABSENT"                         # 沒存
    got = client.get("/api/quotations/" + qn, headers=h).json()
    assert "customFields" not in ((got.get("data") or {}).get("caseRecord") or {})


# ── 2. 定義驗證 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("field,needle", [
    ({"key": "n1", "label": "數量", "type": "number"}, "第一版只能用"),
    ({"key": "m1", "label": "金額", "type": "money"}, "第一版只能用"),
    ({"key": "r1", "label": "必填", "type": "text", "required": True}, "不認得的設定"),
    ({"key": "d1", "label": "預設", "type": "text", "default": "x"}, "不認得的設定"),
    ({"key": "c1", "label": "公式", "type": "text", "formula": "1+1"}, "不認得的設定"),
    ({"key": "contract", "label": "撞名", "type": "text"}, "不可以與既有欄位同名"),
    ({"key": "o1", "label": "文字有選項", "type": "text", "options": ["a"]}, "只有單選可以設定選項"),
    ({"key": "l1", "label": "日期有長度", "type": "date", "maxLength": 5}, "只有文字可以設定最大長度"),
    ({"key": "s1", "label": "單選沒選項", "type": "select"}, "選項"),
    ({"key": "p1", "label": "個資", "type": "text", "dataClass": "F2"}, "T1"),
])
def test_definition_validation_rejects(client, make_user, field, needle):
    h = _boss(client, make_user)
    probs = _validate(client, h, [field])
    assert probs and any(needle in p["message"] for p in probs), probs


def test_definition_validation_limits_and_positive_control(client, make_user):
    h = _boss(client, make_user)
    assert _validate(client, h, [TEXT, SEL, DATE, CHK]) == []                                  # 正對照：合法定義沒有問題
    many = [{"key": "g%d" % i, "label": "欄%d" % i, "type": "text"} for i in range(21)]
    assert any("最多 20" in p["message"] for p in _validate(client, h, many))
    dup = [TEXT, {"key": "f9", "label": "現場工頭", "type": "text"}]
    assert any("名稱重複" in p["message"] for p in _validate(client, h, dup))
    # 別的單據類型鍵（沒登記）不套用這組規則（既有行為不變）
    assert _validate(client, h, [{"key": "n1", "label": "數量", "type": "number"}], key="invoice_vouchers") == []


def test_published_field_cannot_change_type(client, make_user):
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT])
    probs = _validate(client, h, [{"key": "f1", "label": "現場工頭", "type": "date"}])
    assert any("不能改型別" in p["message"] for p in probs), probs
    assert _validate(client, h, [dict(TEXT, disabled=True)]) == []                              # 停用沒問題


# ── 3. 旗標開啟：端點、閘門、存檔 ──────────────────────────────────────────
def test_endpoint_lists_published_active_fields_only(client, make_user):
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT, dict(SEL, disabled=True), DATE])
    _flag(True)
    r = client.get("/api/custom-fields/" + KEY, headers=h).json()
    assert r["enabled"] is True and [f["key"] for f in r["fields"]] == ["f1", "f3"]
    assert all("disabled" not in f for f in r["fields"])


def test_case_save_roundtrip_types_unknown_disabled_and_clear(client, make_user, case):
    h, qn = case
    _publish_def(client, h, [TEXT, SEL, DATE, CHK])
    _flag(True)
    good = {"f1": "王大明", "f2": "B", "f3": "2026-10-20", "f4": True}
    assert _patch(client, h, qn, good).status_code == 200
    assert _stored(qn) == good
    got = client.get("/api/quotations/" + qn, headers=h).json()
    assert got["data"]["caseRecord"]["customFields"] == good
    # 型別／選項錯 ⇒ 400 並指名欄位，資料不動
    for bad, who in (({"f2": "Z"}, "施工等級"), ({"f3": "明天"}, "進場日"), ({"f4": "yes"}, "已會勘")):
        r = _patch(client, h, qn, bad, base=good)
        assert r.status_code == 400 and who in r.text, (bad, r.text)
        assert _stored(qn) == good
    # 未定義的鍵忽略（不存）
    r = _patch(client, h, qn, dict(good, zzz="x"), base=good)
    assert r.status_code == 200 and _stored(qn) == good
    # 清掉全部 ⇒ customFields 這個鍵消失（沒有值就不寫鍵）
    assert _patch(client, h, qn, {}, base=good).status_code == 200
    assert _stored(qn) == "ABSENT"


def test_disabled_and_removed_fields_keep_their_value_and_client_changes_are_ignored(client, make_user, case):
    h, qn = case
    _publish_def(client, h, [TEXT, SEL])
    _flag(True)
    assert _patch(client, h, qn, {"f1": "甲", "f2": "A"}).status_code == 200
    _publish_def(client, h, [dict(TEXT, disabled=True), SEL])              # 停用 f1
    cur = {"f1": "甲", "f2": "A"}
    r = _patch(client, h, qn, {"f1": "乙", "f2": "B"}, base=cur)             # 用戶端想改停用欄位
    assert r.status_code == 200
    assert _stored(qn) == {"f1": "甲", "f2": "B"}                           # 停用欄位保留舊值；有效欄位照改
    r = _patch(client, h, qn, {}, base={"f1": "甲", "f2": "B"})               # 清掉有效欄位：停用的仍保留
    assert r.status_code == 200 and _stored(qn) == {"f1": "甲"}


def test_consecutive_saves_do_not_raise_false_conflicts(client, make_user, case):
    """存檔後用戶端的基準（＝它送出的值）必須等於伺服器存的值，否則下一次存檔會被誤判成『已被他人更新』（409）。"""
    h, qn = case
    _publish_def(client, h, [TEXT, SEL, DATE, CHK])
    _flag(True)
    v1 = {"f1": "a", "f2": "A", "f3": "2026-10-20", "f4": True}
    assert _patch(client, h, qn, v1).status_code == 200
    v2 = dict(v1, f1="ab")
    r = _patch(client, h, qn, v2, base=v1)
    assert r.status_code == 200, r.text
    v3 = {k: v for k, v in v2.items() if k != "f4"}
    r = _patch(client, h, qn, v3, base=v2)
    assert r.status_code == 200, r.text
    assert _stored(qn) == v3


def test_legacy_whole_body_save_without_the_key_keeps_the_values(client, make_user, case):
    h, qn = case
    _publish_def(client, h, [TEXT])
    _flag(True)
    assert _patch(client, h, qn, {"f1": "保留我"}).status_code == 200
    cr = client.get("/api/quotations/" + qn, headers=h).json()["data"]["caseRecord"]
    cr.pop("customFields", None)                                             # 舊的整包格式沒有這個鍵
    r = client.patch("/api/quotations/%s/case-record" % qn, headers=h, json={"case_record": cr})
    assert r.status_code == 200, r.text
    assert _stored(qn) == {"f1": "保留我"}


def test_too_large_value_is_refused(client, make_user, case):
    h, qn = case
    _publish_def(client, h, [dict(TEXT, maxLength=2000)])
    _flag(True)
    r = _patch(client, h, qn, {"f1": "字" * 2000})
    assert r.status_code == 200                                              # 單欄 2000 字 ≈ 6 KB，在上限內
    many = [{"key": "g%d" % i, "label": "欄%d" % i, "type": "text", "maxLength": 2000} for i in range(5)]
    _publish_def(client, h, many)
    r = _patch(client, h, qn, {"g%d" % i: "字" * 2000 for i in range(5)}, base={"f1": "字" * 2000})
    assert r.status_code == 400 and "太大" in r.text


# ── 4. 客戶輸出不含自訂欄位 ────────────────────────────────────────────────
_CUSTOMER_FACING = ["pdf_gen.py", "helpers/doc_template.py", "helpers/doc_render.py"]
_TOKEN = re.compile(r"customFields|custom_fields")


def _hits(text):
    return _TOKEN.findall(text)


def test_scanner_positive_control():
    assert _hits("view = {'customFields': {}}") and _hits("x = ''") == []


@pytest.mark.parametrize("rel", _CUSTOMER_FACING)
def test_customer_facing_renderers_do_not_reference_custom_fields(rel):
    p = ROOT / "backend" / rel
    if not p.exists():
        pytest.skip("沒有 " + rel)
    assert _hits(p.read_text(encoding="utf-8")) == [], rel + " 引用了自訂欄位（客戶輸出不得含自訂欄位）"


# ── 5. 供應商（第二個先導畫面）─────────────────────────────────────────────
SUP = "supplier"


def _publish_sup(client, h, fields):
    url = "/api/definitions/custom_fields/" + SUP
    r = client.put(url + "/draft", headers=h, params={"scope": "company"}, json={"body": {"fields": fields}})
    assert r.status_code == 200 and not r.json().get("problems"), r.text
    r = client.post(url + "/publish", headers=h, params={"scope": "company"}, json={"note": "t"})
    assert r.status_code == 200, r.text


def _sup_get(client, h, sid):
    rows = client.get("/api/suppliers", headers=h).json()
    return [r for r in rows if r["id"] == sid][0]


def _sup_put(client, h, sid, data, name="甲供應商"):
    return client.put("/api/suppliers/%d" % sid, headers=h, json={"name": name, "tax_id": "", "phone": "", "data": data})


def test_supplier_flag_off_ignores_custom_fields_on_create_and_update(client, make_user):
    h = _boss(client, make_user)
    _publish_sup(client, h, [TEXT])
    r = client.post("/api/suppliers", headers=h, json={"name": "甲供應商", "data": {"customFields": {"f1": "x"}, "category": "線材"}})
    assert r.status_code == 200 or r.status_code == 201, r.text
    sid = r.json()["id"]
    row = _sup_get(client, h, sid)
    assert "customFields" not in row and row["category"] == "線材"                  # 旗標關：不存；其餘照存
    assert _sup_put(client, h, sid, {"customFields": {"f1": "y"}}).status_code == 200
    assert "customFields" not in _sup_get(client, h, sid)


def test_supplier_custom_fields_roundtrip_errors_preserve_and_clear(client, make_user):
    h = _boss(client, make_user)
    _publish_sup(client, h, [TEXT, SEL, CHK])
    _flag(True)
    r = client.post("/api/suppliers", headers=h, json={"name": "甲供應商", "data": {"customFields": {"f1": "小張", "f2": "B"}}})
    assert r.status_code in (200, 201), r.text
    sid = r.json()["id"]
    assert _sup_get(client, h, sid)["customFields"] == {"f1": "小張", "f2": "B"}
    # 型別／選項錯 ⇒ 400 指名欄位，資料不動
    r = _sup_put(client, h, sid, {"customFields": {"f2": "Z"}})
    assert r.status_code == 400 and "施工等級" in r.text
    assert _sup_get(client, h, sid)["customFields"] == {"f1": "小張", "f2": "B"}
    # 沒有送這個鍵（舊頁面）＝沒有要改 ⇒ 舊值保留
    assert _sup_put(client, h, sid, {"category": "新分類"}).status_code == 200
    got = _sup_get(client, h, sid)
    assert got["customFields"] == {"f1": "小張", "f2": "B"} and got["category"] == "新分類"
    # 送 {} ＝清掉有效欄位的值 ⇒ 鍵消失
    assert _sup_put(client, h, sid, {"customFields": {}}).status_code == 200
    assert "customFields" not in _sup_get(client, h, sid)


def test_supplier_create_with_bad_value_is_a_clear_400_not_a_generic_failure(client, make_user):
    h = _boss(client, make_user)
    _publish_sup(client, h, [CHK])
    _flag(True)
    r = client.post("/api/suppliers", headers=h, json={"name": "乙供應商", "data": {"customFields": {"f4": "yes"}}})
    assert r.status_code == 400 and "已會勘" in r.text
    assert all(x["name"] != "乙供應商" for x in client.get("/api/suppliers", headers=h).json())


def test_supplier_definition_key_is_registered_and_core_names_are_refused(client, make_user):
    h = _boss(client, make_user)
    probs = _validate(client, h, [{"key": "taxId", "label": "統編", "type": "text"}], key=SUP)
    assert any("不可以與既有欄位同名" in p["message"] for p in probs)
    assert _validate(client, h, [TEXT], key=SUP) == []


# ── 6. 客戶輸出真的建出來看（不只掃原始碼）─────────────────────────────────
def test_built_customer_documents_do_not_contain_custom_field_values(client, make_user, case, monkeypatch):
    """把標記字串放進 caseRecord.customFields 與單據頂層 customFields，真的建報價單 PDF（客戶版與內部版）、預覽、專案報告的 HTML：
    標記不得出現。不啟動 Edge：把 `run_edge_pdf` 換成『讀下 HTML 檔、寫一個假 PDF』。
    正對照：同一個標記放在專案名稱時，捕捉到的 HTML 一定看得到它（證明捕捉有效）。"""
    import db
    import pdf_gen
    h, qn = case
    marker, control = "ZZ自訂欄位標記ZZ", "ZZ對照標記ZZ"
    captured = []

    def fake_edge(cmd, *a, **k):
        path = [c for c in cmd if str(c).startswith("--print-to-pdf=")][0].split("=", 1)[1]
        html_path = cmd[-1].replace("file:///", "")
        captured.append(open(html_path, encoding="utf-8").read())
        open(path, "wb").write(b"%PDF-1.4 fake")

    monkeypatch.setattr(pdf_gen, "_get_edge_path", lambda: "edge")
    monkeypatch.setattr(pdf_gen, "run_edge_pdf", fake_edge)

    def set_data(fn):
        conn = db.get_db()
        try:
            d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()[0] or "{}")
            fn(d)
            conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), qn))
            conn.commit()
        finally:
            conn.close()

    def put_marker(d):
        d.setdefault("caseRecord", {})["customFields"] = {"f1": marker}
        d["customFields"] = {"f1": marker}
    set_data(put_marker)
    for path in ("/api/quotations/%s/pdf-download" % qn, "/api/quotations/%s/pdf-download?internal=true" % qn,
                 "/api/quotations/%s/project-report-pdf" % qn, "/api/quotations/%s/closing-report-pdf" % qn):
        client.get(path, headers=h)
    captured.append(pdf_gen.build_quote_preview_html(json.loads(_row_json(qn)), "草稿", "", internal=False))
    captured.append(pdf_gen.build_quote_preview_html(json.loads(_row_json(qn)), "草稿", "", internal=True))
    assert len(captured) >= 4, "沒有捕捉到足夠的 HTML（建構失敗？）：%d" % len(captured)
    assert all(marker not in c for c in captured), "客戶／內部輸出出現了自訂欄位的值"
    # 正對照：捕捉得到單據資料本身
    set_data(lambda d: d.__setitem__("projectName", control))
    captured.clear()
    client.get("/api/quotations/%s/pdf-download" % qn, headers=h)
    captured.append(pdf_gen.build_quote_preview_html(json.loads(_row_json(qn)), "草稿", "", internal=False))
    assert any(control in c for c in captured), "正對照失敗：捕捉的 HTML 看不到單據資料，這題沒有證明力"


def _row_json(qn):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()[0] or "{}"
    finally:
        conn.close()


# ── 7. 其他整份寫入路徑不能繞過閘門（pre-audit MUST-FIX）──────────────────
def _put_quotation(client, h, qn, mutate):
    """讀回整張報價單 ⇒ 改 data ⇒ PUT 回去（報價單表單的整份存檔）。"""
    got = client.get("/api/quotations/" + qn, headers=h).json()
    data = got["data"]
    mutate(data)
    return client.put("/api/quotations/" + qn, headers=h, json={"status": got.get("status") or "草稿", "data": data})


@pytest.mark.parametrize("flag_on", [False, True])
def test_whole_quotation_put_cannot_forge_or_wipe_custom_fields(client, make_user, case, flag_on):
    h, qn = case
    _publish_def(client, h, [TEXT])
    _flag(flag_on)
    if flag_on:
        assert _patch(client, h, qn, {"f1": "真的值"}).status_code == 200
        stored = {"f1": "真的值"}
    else:
        import db
        conn = db.get_db()
        try:                                                                  # 旗標關閉時直接放一個既有的值（例如曾經開過又關掉）
            d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()[0] or "{}")
            d.setdefault("caseRecord", {})["customFields"] = {"f1": "真的值"}
            conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), qn))
            conn.commit()
        finally:
            conn.close()
        stored = {"f1": "真的值"}
    # 偽造：塞一個不合定義的值（型別錯、未定義的鍵、巨大）⇒ 一律無效，仍是資料庫現值
    r = _put_quotation(client, h, qn, lambda d: d["caseRecord"].__setitem__("customFields", {"f1": "偽造", "zzz": "x" * 20000, "f9": 1}))
    assert r.status_code == 200, r.text
    assert _stored(qn) == stored
    # 沒送這個鍵（報價單表單不認得它）⇒ 不會把已存的值洗掉
    r = _put_quotation(client, h, qn, lambda d: d["caseRecord"].pop("customFields", None))
    assert r.status_code == 200, r.text
    assert _stored(qn) == stored


def test_create_quotation_drops_custom_fields_including_copied_cases(client, make_user):
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT])
    _flag(True)
    r = client.post("/api/quotations", headers=h, json={"status": "草稿", "data": {
        "customerName": "新客戶", "projectName": "複製來的案件", "items": [], "caseRecord": {"customFields": {"f1": "不該帶"}, "notes": "n"}}})
    assert r.status_code in (200, 201), r.text
    qn = r.json().get("quote_no") or r.json().get("quoteNo")
    assert qn
    assert _stored(qn) == "ABSENT"
    assert (client.get("/api/quotations/" + qn, headers=h).json()["data"]["caseRecord"]).get("notes") == "n"      # 其他欄位照存


def test_finance_legacy_whole_body_save_neither_writes_custom_fields_nor_gets_403(client, make_user, case):
    """財務角色（不是案件成員）的舊整包格式存檔：只採用款項。資料庫已有 customFields 而 body 沒有（或偽造）⇒ 不應被當成『改了非款項欄位』而 403，
    也不能借這條路寫入自訂欄位。"""
    import db
    boss, qn = case
    _publish_def(client, boss, [TEXT])
    _flag(True)
    assert _patch(client, boss, qn, {"f1": "資料庫的值"}).status_code == 200
    u, p = make_user("cf_fin", "Lay-Pass-123", role="admin", modules=["cashier"])[:2]
    fin = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    cr = client.get("/api/quotations/" + qn, headers=fin).json()["data"]["caseRecord"]
    for variant in ("missing", "forged"):
        body = dict(cr)
        body.pop("customFields", None)
        if variant == "forged":
            body["customFields"] = {"f1": "財務偽造"}
        r = client.patch("/api/quotations/%s/case-record" % qn, headers=fin, json={"case_record": body})
        assert r.status_code != 403 or "款項以外" not in r.text, (variant, r.text)
        assert _stored(qn) == {"f1": "資料庫的值"}, variant
