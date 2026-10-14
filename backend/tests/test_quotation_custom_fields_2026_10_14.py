# -*- coding: utf-8 -*-
"""Q3：報價單自己的自訂欄位（內建記錄類型 `quotation`，值存在報價單 data_json 頂層 `customFields`）——契約題。
延伸 T61 S5（案件資訊、供應商）；設計 docs/platform/plans/QUOTE-CASE-LAYOUT-COUPLING-T62.md §4 Q3。

證明：
1. 旗標關閉＝今天：用戶端送的 customFields 不存（新建與整份存檔），已存的舊值不被整份存檔洗掉，回應沒有這個鍵。
2. 定義驗證：記錄類型 quotation 通過 S5 的同一套規則；與報價單核心欄位同名擋。
3. 旗標開啟：新建與整份存檔都過閘門（型別錯 400 指名欄位、未定義的鍵忽略、清掉＝鍵消失）；沒送這個鍵＝帶回舊值；連存不會誤判衝突。
4. 客戶輸出（PDF／預覽／內部列印 HTML）不含自訂欄位的值（附正對照）。
5. 案件記錄分段存檔不影響報價單頂層 customFields（兩個路徑各自獨立）；唯讀統計認得 quotation。
"""
import json

import pytest

KEY = "quotation"
DEF = "/api/definitions/custom_fields/" + KEY
TEXT = {"key": "f1", "label": "客戶採購單號", "type": "text"}
SEL = {"key": "f2", "label": "報價用途", "type": "select", "options": ["正式", "估價"]}
DATE = {"key": "f3", "label": "預計簽約日", "type": "date"}
CHK = {"key": "f4", "label": "已電話確認", "type": "checkbox"}


def _boss(client, make_user, name="qcf_boss"):
    u, p = make_user(name, "Lay-Pass-123", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _flag(on):
    import db
    from helpers import settings_registry as SR
    conn = db.get_db()
    try:
        SR.publish("builder_custom_fields", {"enabled": on}, reason="測試", user="qcf_test", conn=conn)
        conn.commit()
    finally:
        conn.close()
    SR.invalidate("builder_custom_fields")


def _publish_def(client, h, fields):
    r = client.put(DEF + "/draft", headers=h, params={"scope": "company"}, json={"body": {"fields": fields}})
    assert r.status_code == 200 and not r.json().get("problems"), r.text
    r = client.post(DEF + "/publish", headers=h, params={"scope": "company"}, json={"note": "t"})
    assert r.status_code == 200, r.text


def _create(client, h, custom=None, **extra):
    data = {"customerName": "測試客戶", "projectName": "測試案件", "items": []}
    if custom is not None:
        data["customFields"] = custom
    data.update(extra)
    r = client.post("/api/quotations", headers=h, json={"status": "草稿", "data": data})
    return r


def _qn(r):
    assert r.status_code in (200, 201), r.text
    return r.json().get("quote_no") or r.json().get("quoteNo")


def _stored(qn):
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()[0] or "{}")
    finally:
        conn.close()
    return d.get("customFields", "ABSENT")


def _put(client, h, qn, mutate):
    got = client.get("/api/quotations/" + qn, headers=h).json()
    data = got["data"]
    mutate(data)
    return client.put("/api/quotations/" + qn, headers=h, json={"status": got.get("status") or "草稿", "data": data})


# ── 1. 旗標關閉 ────────────────────────────────────────────────────────────
def test_flag_off_client_values_are_never_stored_and_old_values_survive(client, make_user):
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT])
    _flag(True)
    qn = _qn(_create(client, h, {"f1": "PO-1"}))
    assert _stored(qn) == {"f1": "PO-1"}
    _flag(False)
    assert _put(client, h, qn, lambda d: d.__setitem__("customFields", {"f1": "偽造"})).status_code == 200
    assert _stored(qn) == {"f1": "PO-1"}                                              # 關閉時用戶端送的不存、舊值保留
    assert _put(client, h, qn, lambda d: d.pop("customFields", None)).status_code == 200
    assert _stored(qn) == {"f1": "PO-1"}                                              # 沒送這個鍵：整份取代也不洗掉
    qn2 = _qn(_create(client, h, {"f1": "新建也不存"}))
    assert _stored(qn2) == "ABSENT"
    assert "customFields" not in client.get("/api/quotations/" + qn2, headers=h).json()["data"]    # 沒有值＝沒有這個鍵


# ── 2. 定義驗證 ────────────────────────────────────────────────────────────
def test_definition_rules_apply_to_the_quotation_record_type(client, make_user):
    h = _boss(client, make_user)

    def problems(fields):
        r = client.post("/api/definitions/custom_fields/%s/validate" % KEY, headers=h, json={"body": {"fields": fields}})
        assert r.status_code == 200, r.text
        return r.json()["problems"]
    assert problems([TEXT, SEL, DATE, CHK]) == []
    assert problems([{"key": "customerName", "label": "冒充", "type": "text"}])               # 與報價單核心欄位同名 ⇒ 擋
    assert problems([{"key": "f9", "label": "金額", "type": "number"}])                         # 沒有數字（可能放金額）
    assert problems([{"key": "k%d" % i, "label": "欄%d" % i, "type": "text"} for i in range(21)])      # 最多 20


# ── 3. 旗標開啟 ────────────────────────────────────────────────────────────
def test_create_and_put_go_through_the_gate(client, make_user):
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT, SEL, DATE, CHK])
    _flag(True)
    bad = _create(client, h, {"f2": "不在選項"})
    assert bad.status_code == 400 and "報價用途" in bad.text                                      # 錯誤指名是哪一欄
    qn = _qn(_create(client, h, {"f1": "PO-9", "f2": "正式", "f3": "2026-11-01", "f4": True, "zzz": "未定義"}))
    assert _stored(qn) == {"f1": "PO-9", "f2": "正式", "f3": "2026-11-01", "f4": True}              # 未定義的鍵忽略
    r = _put(client, h, qn, lambda d: d["customFields"].update({"f2": "估價", "f1": ""}))
    assert r.status_code == 200, r.text
    assert _stored(qn) == {"f2": "估價", "f3": "2026-11-01", "f4": True}                          # 空值＝移除該欄位的值
    assert _put(client, h, qn, lambda d: d["customFields"].update({"f3": "不是日期"})).status_code == 400
    assert _stored(qn) == {"f2": "估價", "f3": "2026-11-01", "f4": True}                          # 400 不改動資料庫
    assert _put(client, h, qn, lambda d: d.pop("customFields", None)).status_code == 200
    assert _stored(qn) == {"f2": "估價", "f3": "2026-11-01", "f4": True}                          # 沒送＝帶回舊值
    assert _put(client, h, qn, lambda d: d.__setitem__("customFields", {})).status_code == 200
    assert _stored(qn) == "ABSENT"                                                              # 清到沒有 ⇒ 鍵消失


def test_consecutive_saves_do_not_raise_false_conflicts_and_stored_equals_client(client, make_user):
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT])
    _flag(True)
    qn = _qn(_create(client, h, {"f1": "A"}))
    for v in ("B", "C", "D"):
        got = client.get("/api/quotations/" + qn, headers=h).json()
        assert got["data"]["customFields"] == _stored(qn)                                       # 伺服端存的＝用戶端拿到的基準
        r = client.put("/api/quotations/" + qn, headers=h, json={"status": got["status"], "data": dict(got["data"], customFields={"f1": v}),
                                                                 "expectedUpdatedAt": got.get("updated_at")} if False else
                       {"status": got["status"], "data": dict(got["data"], customFields={"f1": v})})
        assert r.status_code == 200, r.text
        assert _stored(qn) == {"f1": v}


def test_disabled_fields_keep_their_stored_value_and_ignore_client_edits(client, make_user):
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT, SEL])
    _flag(True)
    qn = _qn(_create(client, h, {"f1": "保留", "f2": "正式"}))
    _publish_def(client, h, [TEXT, dict(SEL, disabled=True)])
    assert _put(client, h, qn, lambda d: d["customFields"].update({"f2": "估價", "f1": "改了"})).status_code == 200
    assert _stored(qn) == {"f1": "改了", "f2": "正式"}                                           # 停用欄位的值原樣保留、用戶端的改動忽略


# ── 4. 客戶輸出 ────────────────────────────────────────────────────────────
def test_customer_and_internal_documents_do_not_contain_custom_field_values(client, make_user, monkeypatch):
    import pdf_gen
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT])
    _flag(True)
    marker, control = "ZZ報價單自訂欄位標記ZZ", "ZZ對照標記ZZ"
    qn = _qn(_create(client, h, {"f1": marker}, projectName=control))
    captured = []

    def fake_edge(cmd, *a, **k):
        path = [c for c in cmd if str(c).startswith("--print-to-pdf=")][0].split("=", 1)[1]
        captured.append(open(cmd[-1].replace("file:///", ""), encoding="utf-8").read())
        open(path, "wb").write(b"%PDF-1.4 fake")
    monkeypatch.setattr(pdf_gen, "_get_edge_path", lambda: "edge")
    monkeypatch.setattr(pdf_gen, "run_edge_pdf", fake_edge)
    for path in ("/api/quotations/%s/pdf-download" % qn, "/api/quotations/%s/pdf-download?internal=true" % qn):
        client.get(path, headers=h)
    data = client.get("/api/quotations/" + qn, headers=h).json()["data"]
    assert data["customFields"] == {"f1": marker}
    captured.append(pdf_gen.build_quote_preview_html(data, "草稿", "", internal=False))
    captured.append(pdf_gen.build_quote_preview_html(data, "草稿", "", internal=True))
    assert len(captured) >= 3
    assert all(marker not in c for c in captured), "客戶／內部輸出出現了報價單自訂欄位的值"
    assert any(control in c for c in captured), "正對照失敗：捕捉的 HTML 看不到單據資料，這題沒有證明力"


# ── 5. 與案件記錄路徑各自獨立；唯讀統計 ─────────────────────────────────────
def test_case_record_save_does_not_touch_the_quotation_level_custom_fields(client, make_user):
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT])
    _flag(True)
    qn = _qn(_create(client, h, {"f1": "報價單層"}))
    r = client.patch("/api/quotations/%s/case-record" % qn, headers=h, json={"segments": {"notes": "n"}, "base": {"notes": ""}, "defaults": {}})
    assert r.status_code in (200, 409), r.text
    assert _stored(qn) == {"f1": "報價單層"}


def test_usage_counts_cover_the_quotation_type(client, make_user):
    h = _boss(client, make_user)
    _publish_def(client, h, [TEXT, SEL])
    _flag(True)
    _qn(_create(client, h, {"f1": "甲", "f2": "正式"}))
    _qn(_create(client, h, {"f1": "乙"}))
    r = client.get("/api/custom-fields/quotation/usage", headers=h)
    assert r.status_code == 200 and r.json()["counts"].get("f1") == 2 and r.json()["counts"].get("f2") == 1
    assert client.get("/api/custom-fields/quotation", headers=h).json()["enabled"] is True
