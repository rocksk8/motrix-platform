# -*- coding: utf-8 -*-
"""模組建構器的輸出預覽（BUILDER-UX §3.4；A）：`POST /api/custom-modules/{key}/output/preview`。

① 同一筆樣本資料：預覽與正式匯出（單據輸出）的 HTML 完全一致——走同一個 renderer、同一份版型。
② 預覽跟著正式樣板走：改正式樣板（`default_template`），預覽立刻跟著變（不是另一份複本）。
③ 只讀：呼叫前後每一張表的列數不變（含半成品、PDF）。
④ 只給有建構器權限的人（超級管理員）：有模組使用權也不行（403），沒登入 401。
⑤ 邊拖邊看：編到一半的草稿照畫，未完成的欄位畫成「〈名稱〉尚未完成」並列在回應標頭；
   只有連一個欄位都畫不出來才 422；任何半成品都不可以 500。
"""
import copy
import json

import pytest

KEY = "bo_preview_mod"
INCOMPLETE = "X-Motrix-Preview-Incomplete"


def _definition(output=None):
    body = {
        "name": "輸出預覽測試", "icon": "box", "permission": "custom.%s" % KEY,
        "numbering": {"prefix": "OP", "date": "", "digits": 3},
        "fields": [
            {"key": "item", "label": "設備", "type": "text", "required": True},
            {"key": "qty", "label": "數量", "type": "number", "required": True},
            {"key": "price", "label": "單價", "type": "number"},
            {"key": "total", "label": "總值", "type": "formula", "formula": "qty * price"},
            {"key": "kind", "label": "類別", "type": "select", "options": ["甲", "乙"]},
            {"key": "urgent", "label": "急件", "type": "checkbox"},
            {"key": "day", "label": "日期", "type": "date"},
        ],
        "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                     "transitions": [{"key": "finish", "label": "完成", "from": "draft", "to": "done"}]},
    }
    if output is not None:
        body["output"] = {"template": output}
    return body


def _custom_template():
    return {"key": "bo_tpl", "version": 1, "theme": "voucher_standard", "title": {"path": "recordNo", "suffix": ""},
            "blocks": [{"type": "section_title", "text": "借用 {item}（{kind}）"},
                       {"type": "meta", "fields": [{"label": "數量", "path": "fields.qty"}, {"label": "總值", "path": "fields.total"},
                                                   {"label": "日期", "path": "fields.day", "format": "date10"}]}]}


def _h(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Preview-Pass-123", role=role, modules=modules)[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _preview(client, h, body, **params):
    return client.post("/api/custom-modules/%s/output/preview" % KEY, headers=h, params=params, json={"body": body})


def _incomplete(r):
    return json.loads(r.headers[INCOMPLETE])


def _row_counts():
    import db
    conn = db.get_db()
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {n: conn.execute('SELECT COUNT(*) FROM "%s"' % n).fetchone()[0] for n in names}
    finally:
        conn.close()


@pytest.mark.parametrize("output", [None, _custom_template()], ids=["default_template", "custom_template"])
def test_preview_equals_the_real_export_for_the_same_sample(client, make_user, output):
    """①：把樣本值當成真的單據建出來（編號／狀態／建立者／時間對齊樣本），正式匯出的 HTML 與預覽逐字相同。"""
    from helpers import custom_modules as CM
    sa = _h(client, make_user, "bo_sa", role="superadmin")
    body = _definition(output)
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=sa, json={"body": body}).status_code == 200
    r = client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=sa, json={})
    assert r.status_code == 200, r.text
    sample = CM.sample_values(body)
    inputs = {k: v for k, v in sample.items() if k != "total"}
    r = client.post("/api/custom/%s/records" % KEY, headers=sa, json={"values": inputs})
    assert r.status_code == 200, r.text
    rec_no = r.json()["record_no"]
    import db
    conn = db.get_db()
    try:                                  # 建立者／時間是單據才有的，對齊成樣本的（其餘全部來自真的單據）
        conn.execute("UPDATE custom_records SET created_by='範例使用者', created_at='2026-09-25T09:00:00' WHERE record_no=?", (rec_no,))
        conn.commit()
    finally:
        conn.close()
    real = client.get("/api/custom/%s/records/%s/output" % (KEY, rec_no), headers=sa)
    prev = _preview(client, sa, body)
    assert real.status_code == 200 and prev.status_code == 200, (real.text[:300], prev.text[:300])
    assert rec_no == "OP-001" and "OP-001" in prev.text
    assert prev.text == real.text
    assert _incomplete(prev) == []


def test_preview_follows_the_official_template(client, make_user, monkeypatch):
    """②：正式樣板（default_template）一改，預覽立刻跟著變——預覽沒有自己的一份。"""
    from helpers import custom_modules as CM
    sa = _h(client, make_user, "bo_sa2", role="superadmin")
    before = _preview(client, sa, _definition()).text
    orig = CM.default_template

    def changed(body):
        t = orig(body)
        t["blocks"].insert(1, {"type": "section_title", "text": "正式樣板改過了"})
        return t
    monkeypatch.setattr(CM, "default_template", changed)
    after = _preview(client, sa, _definition()).text
    assert "正式樣板改過了" not in before and "正式樣板改過了" in after


def test_preview_writes_nothing(client, make_user, monkeypatch):
    """③：完整草稿、半成品、PDF 各打一次，每一張表的列數都不變。"""
    import pdf_gen
    monkeypatch.setattr(pdf_gen, "html_to_pdf_bytes", lambda html: b"%PDF-1.4 fake")
    sa = _h(client, make_user, "bo_sa3", role="superadmin")
    half = _definition()
    half["fields"].append({"key": "memo", "label": "備註", "type": "formula", "formula": ""})
    before = _row_counts()
    assert _preview(client, sa, _definition()).status_code == 200
    assert _preview(client, sa, half).status_code == 200
    assert _preview(client, sa, _definition(), format="pdf").status_code == 200
    assert _preview(client, sa, {"fields": []}).status_code == 422
    after = _row_counts()
    # 最後那次故意送 {"fields": []} 得 422 ⇒ 歷史紀錄的失敗鉤子（helpers.audit._audit_failure，使用者要求失敗可搜尋）
    # 記了一筆 `fail.POST`：那是「被擋下的請求」的紀錄，不是預覽寫了東西。排除 fail.* 列再比對，
    # 並斷言恰好就是這一次 422 產生了一筆（鉤子有動作，而不是被藏起來）。
    import db as _db
    _c = _db.get_db()
    try:
        fails = [dict(r) for r in _c.execute("SELECT action, status_code, target_label FROM audit_log WHERE action LIKE 'fail.%'")]
    finally:
        _c.close()
    assert len(fails) == 1 and fails[0]["status_code"] == 422 and fails[0]["target_label"].endswith("/output/preview"), fails
    after["audit_log"] -= len(fails)
    # user_request_log＝main.py 中介層替每個請求記的操作軌跡（任何端點都有、去重），不是本端點寫的；
    # 排除它，但要求多出來的軌跡只有這支預覽的路徑
    trail = (before.pop("user_request_log", 0), after.pop("user_request_log", 0))
    assert {k: (before.get(k), v) for k, v in after.items() if before.get(k) != v} == {}
    import db
    conn = db.get_db()
    try:
        paths = {r[0] for r in conn.execute("SELECT path FROM user_request_log ORDER BY id DESC LIMIT ?", (trail[1] - trail[0],))}
    finally:
        conn.close()
    assert paths <= {"/api/custom-modules/%s/output/preview" % KEY}, paths


def test_preview_is_only_for_builders(client, make_user):
    """④：有這個模組的使用權限也不能預覽（建構器僅超級管理員）；沒登入 401。"""
    user = _h(client, make_user, "bo_user", modules=["custom.%s" % KEY])
    assert _preview(client, user, _definition()).status_code == 403
    assert client.post("/api/custom-modules/%s/output/preview" % KEY, json={"body": _definition()}).status_code == 401


def _with(extra):
    d = _definition()
    d["fields"].append(extra)
    return d


HALF_DONE = {
    "沒有key": ({"label": "備註", "type": "text"}, "備註", None),
    "公式空白": ({"key": "memo", "label": "折扣", "type": "formula", "formula": ""}, "折扣", "memo"),
    "公式參照不存在的欄位": ({"key": "memo", "label": "折扣", "type": "formula", "formula": "qty * nope"}, "折扣", "memo"),
    "選單沒有選項": ({"key": "memo", "label": "等級", "type": "select", "options": []}, "等級", "memo"),
    "公式型別不合": ({"key": "memo", "label": "折扣", "type": "formula", "formula": "item * 2"}, "折扣", "memo"),
    "型別不認得": ({"key": "memo", "label": "簽名", "type": "signature"}, "簽名", "memo"),
    "沒有名稱也沒有key": ({"type": "number"}, "第 8 個欄位", None),
    "key重複": ({"key": "qty", "label": "數量2", "type": "number"}, "數量2", None),
    "不是物件": ("oops", "第 8 個欄位", None),
}


@pytest.mark.parametrize("name", list(HALF_DONE))
def test_half_done_draft_is_drawn_with_a_placeholder(client, make_user, name):
    """⑤：每一種半成品都照畫（200）：其他欄位照常、未完成的那一欄是佔位，並列在未完成清單。"""
    extra, label, field = HALF_DONE[name]
    sa = _h(client, make_user, "bo_sa5", role="superadmin")
    r = _preview(client, sa, _with(extra))
    assert r.status_code == 200, r.text[:500]
    assert "〈%s〉尚未完成" % label in r.text and "設備" in r.text and "範例文字" in r.text
    got = _incomplete(r)
    assert [(g["path"], g["label"], g.get("field")) for g in got] == [("fields[7]", label, field)], got
    assert got[0]["message"]


def test_formula_depending_on_an_unfinished_field_is_also_a_placeholder(client, make_user):
    sa = _h(client, make_user, "bo_sa6", role="superadmin")
    d = _definition()
    d["fields"][2] = {"key": "price", "label": "單價", "type": "select", "options": []}   # 未完成 ⇒ total 也算不出來
    r = _preview(client, sa, d)
    assert r.status_code == 200 and "〈單價〉尚未完成" in r.text and "〈總值〉尚未完成" in r.text
    assert [g["path"] for g in _incomplete(r)] == ["fields[2]", "fields[3]"]


def test_template_referring_to_a_removed_field_still_draws(client, make_user):
    """拖掉一個版型有引用的欄位：照畫、那一格空白，並在清單說明版型引用不到。"""
    sa = _h(client, make_user, "bo_sa7", role="superadmin")
    d = _definition(_custom_template())
    d["fields"] = [f for f in d["fields"] if f["key"] != "day"]
    r = _preview(client, sa, d)
    assert r.status_code == 200 and "借用 範例文字（甲）" in r.text
    assert any(g["path"].startswith("output.template.blocks[1]") and "fields.day" in g["message"] for g in _incomplete(r))


@pytest.mark.parametrize("body,why", [
    ({"name": "x", "fields": []}, "還沒有可以預覽的欄位"),
    ({"name": "x"}, "還沒有可以預覽的欄位"),
    ({"name": "x", "fields": [{"label": "甲"}, {"key": "b", "type": "formula"}]}, "所有欄位都尚未完成"),
], ids=["空欄位", "沒有欄位", "全部未完成"])
def test_nothing_drawable_is_422_with_a_reason(client, make_user, body, why):
    sa = _h(client, make_user, "bo_sa8", role="superadmin")
    r = _preview(client, sa, body)
    assert r.status_code == 422 and r.json()["detail"] == why and r.json()["problems"], r.text


@pytest.mark.parametrize("mutate", [
    lambda d: d.__setitem__("fields", {"a": 1}),
    lambda d: d.__setitem__("workflow", "nope"),
    lambda d: d["workflow"].__setitem__("states", ["x", None]),
    lambda d: d.__setitem__("numbering", "OP"),
    lambda d: d.__setitem__("numbering", {"prefix": "op", "digits": 99}),
    lambda d: d.__setitem__("name", 123),
    lambda d: d.__setitem__("output", "nope"),
    lambda d: d.__setitem__("output", {"template": "nope"}),
    lambda d: d.__setitem__("output", {"template": {"theme": "voucher_standard", "blocks": [{"type": "nope"}]}}),
    lambda d: d["fields"].__setitem__(3, {"key": "total", "label": "總值", "type": "formula", "formula": "total + 1"}),
    lambda d: d["fields"].__setitem__(1, {"key": "qty", "label": {"x": 1}, "type": "number"}),
    lambda d: d["fields"].__setitem__(4, {"key": "kind", "label": "類別", "type": "select", "options": "甲乙"}),
], ids=["fields非陣列", "workflow非物件", "狀態非物件", "編號非物件", "編號不合規", "名稱非文字", "output非物件",
        "版型非物件", "未知積木", "公式自我引用", "名稱非文字欄", "選項非陣列"])
def test_no_half_done_draft_makes_it_500(client, make_user, mutate):
    sa = _h(client, make_user, "bo_sa9", role="superadmin")
    d = copy.deepcopy(_definition())
    mutate(d)
    r = _preview(client, sa, d)
    assert r.status_code in (200, 422), (r.status_code, r.text[:300])
    if r.status_code == 422:            # 要是處理過的 422（說得出原因），不是最後那道兜底接住的例外
        assert r.json()["problems"] and r.json()["detail"] != "這份草稿暫時無法預覽", r.text


def test_last_resort_turns_an_unexpected_error_into_422(client, make_user, monkeypatch, caplog):
    """兜底：預覽裡任何沒料到的例外都回 422（不是 500）；上一題確保一般半成品不會走到這裡。
    log 與回應都不帶草稿內容（例外訊息可能含欄位值）、回應不帶 stack；log 要記得到型別與位置才查得了。"""
    import logging
    from helpers import custom_modules as CM
    secret = "機密草稿內容-7Q"

    def boom(body):
        raise RuntimeError("壞在 %s" % body["fields"][0]["label"])
    monkeypatch.setattr(CM, "preview_output", boom)
    sa = _h(client, make_user, "bo_sa10", role="superadmin")
    d = _definition()
    d["fields"][0]["label"] = secret
    with caplog.at_level(logging.ERROR):
        r = _preview(client, sa, d)
    assert r.status_code == 422 and r.json()["detail"] == "這份草稿暫時無法預覽"
    assert secret not in r.text and "Traceback" not in r.text and ".py" not in r.text, r.text
    logged = "\n".join(rec.getMessage() + (rec.exc_text or "") + str(rec.exc_info or "") for rec in caplog.records)
    assert "RuntimeError" in logged and "boom" in logged, logged
    assert secret not in logged, logged
