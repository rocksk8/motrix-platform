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
