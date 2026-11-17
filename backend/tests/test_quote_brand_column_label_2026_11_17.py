# -*- coding: utf-8 -*-
"""報價單品項表「廠牌 / 型號」欄名可自訂（feat/quote-brand-column-label，使用者裁示 2026-11-17）。

釘住：
1. 欄名存在單據本身（data_json.columnLabels = {item, brand}，只存有改的欄）；空白／與該欄預設相同／非字串＝沒改（鍵不留）；長度上限 20、控制字元去掉；不認得的欄丟掉。
2. PDF 表頭（品名 / 規格說明、廠牌 / 型號）顯示自訂欄名且 HTML 跳脫；沒自訂（含舊單）輸出與預設逐位元相同。
3. 送簽（建單即送審、草稿轉待審核、解鎖編輯重簽）時 approval.reasons 註記「欄名已由「廠牌 / 型號」變更為「○○」」（兩欄各一行）；沒改＝原有行為不動。
4. 編輯紀錄（editHistory）看得到欄名變更。
5. 估價單（共用範本與表單；使用者裁示一起改）比照報價單：可存欄名、PDF 顯示、送簽註記；沒自訂的估價單輸出不變。
"""
import json

import pytest

from helpers import quote_brand_label as BL
from tests._requires import requires_module

DEFAULT = "廠牌 / 型號"
ITEM = "品名 / 規格說明"
NOTE_B = "欄名已由「廠牌 / 型號」變更為「%s」"
NOTE_I = "欄名已由「品名 / 規格說明」變更為「%s」"


# ── 純函式（不需要 M01）──────────────────────────────────────────────────────

def test_normalize_blank_default_and_non_string_mean_unchanged():
    for col, default in (("brand", DEFAULT), ("item", ITEM)):
        for raw in (None, "", "   ", " \t \n ", default, "  " + default.replace(" / ", " /   ") + " ", 123, ["料號"], {"a": 1}):
            assert BL.normalize(col, raw) == "", (col, raw)
    assert BL.normalize("nope", "料號") == "", "不認得的欄代號"
    assert BL.normalize("item", DEFAULT) == DEFAULT, "各欄的預設只對自己那欄算「沒改」"


def test_normalize_trims_collapses_strips_control_and_caps_length():
    assert BL.normalize("brand", "  料號  ") == "料號"
    assert BL.normalize("brand", "料\x00號\u200b") == "料號"
    assert BL.normalize("item", "品  項\n編號") == "品 項 編號"
    assert BL.normalize("item", "甲" * 50) == "甲" * BL.MAX_LEN


def test_invisible_characters_are_visible_escapes_in_source_and_stripped():
    import inspect
    src = inspect.getsource(BL)
    assert not any(ord(c) in (0x200b, 0x200f, 0x2028, 0x2029, 0xfeff) for c in src), "原始碼裡不放看不見的字元，用 \\u 轉義"
    assert BL.normalize("brand", "料" + chr(0x200b) + "號" + chr(0xfeff) + chr(0x2028)) == "料號"


def test_columns_defaults_and_presets():
    assert BL.default_of("brand") == DEFAULT and BL.default_of("item") == ITEM
    assert BL.presets_of("brand") == ("料號", "型號", "規格", DEFAULT)
    assert ITEM in BL.presets_of("item") and "品名" in BL.presets_of("item")


def test_label_of_labels_of_and_change_reasons():
    assert BL.labels_of({}) == {"item": ITEM, "brand": DEFAULT} and BL.change_reasons({}) == []
    q = {"docType": "quote", "columnLabels": {"brand": "料號"}}
    assert BL.label_of(q, "brand") == "料號" and BL.label_of(q, "item") == ITEM
    assert BL.change_reasons(q) == [NOTE_B % "料號"]
    q = {"columnLabels": {"item": "品項", "brand": "規格"}}
    assert BL.change_reasons(q) == [NOTE_I % "品項", NOTE_B % "規格"], "兩欄各一行、順序固定（品名在前）"
    assert BL.change_reasons({"columnLabels": {"brand": DEFAULT, "item": "  "}}) == [], "與預設相同／空白＝沒變更"
    assert BL.change_reasons({"columnLabels": "壞掉"}) == [] and BL.labels_of({"columnLabels": ["x"]})["brand"] == DEFAULT


def test_sanitize_in_place_keeps_only_valid_columns():
    q = {"docType": "quote", "columnLabels": {"brand": "  型號 ", "item": DEFAULT, "zzz": "x"}}
    BL.sanitize(q)
    assert q["columnLabels"] == {"brand": "型號", "item": DEFAULT}, "item 欄的預設是「品名 / 規格說明」，「廠牌 / 型號」對它是自訂值"
    q = {"docType": "quote", "columnLabels": {"brand": DEFAULT, "item": ITEM, "zzz": "x"}}
    BL.sanitize(q)
    assert "columnLabels" not in q, "全部＝預設／不認得 ⇒ 整個鍵移除"
    for dirty in ("", None, 5, ["a"], {}):
        q = {"docType": "quote", "columnLabels": dirty}
        BL.sanitize(q)
        assert "columnLabels" not in q, dirty
    q = {"docType": "quote"}
    BL.sanitize(q)
    assert q == {"docType": "quote"}, "沒這個鍵＝不動（舊單）"


def test_estimate_follows_quote():
    q = {"docType": "estimate", "columnLabels": {"brand": " 料號 ", "item": "品項"}}
    BL.sanitize(q)
    assert q["columnLabels"] == {"brand": "料號", "item": "品項"}
    assert BL.labels_of(q) == {"item": "品項", "brand": "料號"}
    assert BL.change_reasons(q) == [NOTE_I % "品項", NOTE_B % "料號"]
    assert BL.change_reasons({"docType": "estimate"}) == [] and BL.labels_of({"docType": "estimate"}) == {"item": ITEM, "brand": DEFAULT}
    q = {"docType": "estimate", "columnLabels": {"brand": DEFAULT, "item": ""}}
    BL.sanitize(q)
    assert "columnLabels" not in q, "估價單同樣：與預設相同／空白＝沒改"


# ── PDF ─────────────────────────────────────────────────────────────────────

def _html(q):
    import pdf_gen
    tot = {"total": 1050, "pretax": 1000, "tax": 50, "subtotal": 1000}
    q = {"quoteNo": "MQ-202611-001", "customerName": "客", "docType": "quote",
         "items": [{"description": "品", "brand": "Cisco", "qty": 1, "unit": "台", "unitPrice": 1000, "amount": 1000}], **q}
    return pdf_gen._build_quote_html_core(q, tot)


TH_B = '<th style="width:110px">%s</th>'
TH_I = '<th style="width:190px">%s</th>'


def test_pdf_header_shows_custom_labels_and_escapes():
    html = _html({"columnLabels": {"brand": "料號", "item": "品項"}})
    assert TH_B % "料號" in html and TH_I % "品項" in html
    assert TH_B % DEFAULT not in html and TH_I % ITEM not in html
    one = _html({"columnLabels": {"brand": "料號"}})
    assert TH_B % "料號" in one and TH_I % ITEM in one, "只改一欄，另一欄維持預設"
    evil = _html({"columnLabels": {"brand": "<script>alert(1)</script>", "item": '"><img src=x>'}})
    assert "<script>alert(1)</script>" not in evil and "&lt;script&gt;" in evil and "<img src=x>" not in evil


def test_pdf_without_labels_is_byte_identical_to_default():
    base = _html({})
    assert TH_B % DEFAULT in base and TH_I % ITEM in base
    for cl in ({}, {"brand": "", "item": ""}, {"brand": DEFAULT, "item": ITEM}, {"brand": "  "}, "壞掉", None):
        assert _html({"columnLabels": cl}) == base, cl


def test_pdf_estimate_shows_custom_labels_and_unchanged_without():
    html = _html({"docType": "estimate", "columnLabels": {"brand": "料號", "item": "品項"}})
    assert TH_B % "料號" in html and TH_I % "品項" in html and "估價" in html
    base = _html({"docType": "estimate"})
    assert TH_B % DEFAULT in base and TH_I % ITEM in base
    for cl in ({}, {"brand": "", "item": ""}, {"brand": DEFAULT, "item": ITEM}, "壞掉", None):
        assert _html({"docType": "estimate", "columnLabels": cl}) == base, cl


# ── API：存讀、送簽註記、編輯紀錄 ─────────────────────────────────────────────

pytestmark_api = requires_module("case", "本節的題打 M01（案件）的報價單端點")


def _auth(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _data(**over):
    from modules.case.quote_terms import DEFAULT_TERMS
    d = {"customerName": "欄名客戶", "projectName": "欄名案", "salesPerson": "", "quoteDate": "2026-11-17",
         "validDays": 30, "taxRate": 5, "showDiscount": False, "discount": 0,
         "tot": {"total": 1050, "pretax": 1000, "directMarginPct": 0, "netMarginPct": 0},
         "items": [{"description": "品項 A", "brand": "Cisco", "qty": 1, "cost": 700, "margin": 0.35,
                    "unitPrice": 1150, "amount": 1150}],
         "approval": {"status": "pending"}}
    d.update(DEFAULT_TERMS)
    d.update(over)
    return d


def _row(no):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT data_json, status FROM quotations WHERE quote_no=?", (no,)).fetchone()
    finally:
        conn.close()
    return json.loads(r["data_json"]), r["status"]


@pytest.fixture
def hdr(client, make_user):
    from .test_case_extra_expenses_api_2026_09_11 import _set_empty_approval_flow
    _set_empty_approval_flow()
    u, p = make_user(username="bl_sales", role="admin")
    return _auth(client, u, p)


def _create(client, hdr, data, status="草稿"):
    r = client.post("/api/quotations", headers=hdr, json={"status": status, "data": data})
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


@pytest.mark.usefixtures("hdr")
class TestApi:
    pytestmark = pytestmark_api

    def test_save_and_read_back_custom_labels(self, client, hdr):
        no = _create(client, hdr, _data(columnLabels={"brand": "  料號 ", "item": "品項"}))
        assert _row(no)[0]["columnLabels"] == {"brand": "料號", "item": "品項"}
        got = client.get(f"/api/quotations/{no}", headers=hdr).json()
        assert (got.get("data") or got)["columnLabels"] == {"brand": "料號", "item": "品項"}

    def test_default_or_blank_is_not_stored(self, client, hdr):
        for i, v in enumerate(({}, {"brand": "", "item": "   "}, {"brand": DEFAULT, "item": ITEM}, "壞掉", None)):
            no = _create(client, hdr, _data(columnLabels=v, customerName="欄名客戶%d" % i))
            assert "columnLabels" not in _row(no)[0], v

    def test_only_changed_column_is_stored(self, client, hdr):
        no = _create(client, hdr, _data(columnLabels={"brand": DEFAULT, "item": "品項"}))
        assert _row(no)[0]["columnLabels"] == {"item": "品項"}

    def test_long_label_capped_and_unknown_column_dropped(self, client, hdr):
        no = _create(client, hdr, _data(columnLabels={"brand": "<b>" + "乙" * 40, "zzz": "x"}))
        stored = _row(no)[0]["columnLabels"]
        assert set(stored) == {"brand"} and len(stored["brand"]) <= BL.MAX_LEN

    def test_estimate_labels_saved_noted_on_submit_and_tracked_in_history(self, client, hdr):
        no = _create(client, hdr, _data(docType="estimate", columnLabels={"brand": "料號", "item": "品項"}))
        assert no.startswith("ME-"), no
        assert _row(no)[0]["columnLabels"] == {"brand": "料號", "item": "品項"}
        r = client.put(f"/api/quotations/{no}", headers=hdr, json={"status": "待審核", "data": _data(
            quoteNo=no, docType="quote", columnLabels={"brand": "規格", "item": "品項"},
            approval={"status": "pending", "reasons": []})})          # 用戶端把 docType 改成 quote 也騙不了：類型以資料庫為準
        assert r.status_code == 200, r.text
        d = _row(no)[0]
        assert d["docType"] == "estimate" and d["columnLabels"] == {"brand": "規格", "item": "品項"}
        assert d["approval"]["reasons"] == [NOTE_I % "品項", NOTE_B % "規格"], d["approval"]["reasons"]
        fields = {c["field"] for e in d["editHistory"] for c in e.get("changes", [])}
        assert "欄名（廠牌 / 型號）" in fields

    def test_estimate_without_labels_behaves_as_before(self, client, hdr):
        no = _create(client, hdr, _data(docType="estimate", approval={"status": "pending", "reasons": []}), "待審核")
        d = _row(no)[0]
        assert "columnLabels" not in d and d["approval"]["reasons"] == ["標準報價單送出"]

    def test_update_changes_and_clearing_remove_keys_and_edit_history_records_change(self, client, hdr):
        no = _create(client, hdr, _data())
        r = client.put(f"/api/quotations/{no}", headers=hdr, json={"status": "草稿", "data": _data(quoteNo=no, columnLabels={"brand": "規格", "item": "品項"})})
        assert r.status_code == 200, r.text
        d = _row(no)[0]
        assert d["columnLabels"] == {"brand": "規格", "item": "品項"}
        chs = {c["field"]: c for e in d["editHistory"] for c in e.get("changes", []) if c["field"].startswith("欄名")}
        assert chs["欄名（廠牌 / 型號）"]["from"] == "" and chs["欄名（廠牌 / 型號）"]["to"] == "規格", d["editHistory"]
        assert chs["欄名（品名 / 規格說明）"]["to"] == "品項"
        r = client.put(f"/api/quotations/{no}", headers=hdr, json={"status": "草稿", "data": _data(quoteNo=no, columnLabels={"brand": "", "item": ""})})
        assert r.status_code == 200, r.text
        assert "columnLabels" not in _row(no)[0]

    def test_submit_on_create_notes_each_changed_column_separately(self, client, hdr):
        no = _create(client, hdr, _data(columnLabels={"brand": "料號", "item": "品項"},
                                        approval={"status": "pending", "reasons": ["假的"]}), "待審核")
        rs = _row(no)[0]["approval"]["reasons"]
        assert NOTE_I % "品項" in rs and NOTE_B % "料號" in rs and "假的" not in rs
        assert rs.index(NOTE_I % "品項") < rs.index(NOTE_B % "料號")
        assert "標準報價單送出" not in rs, "有特殊條件就不再寫「標準報價單送出」"

    def test_submit_with_only_one_column_changed_notes_only_that_one(self, client, hdr):
        no = _create(client, hdr, _data(columnLabels={"item": "項目"}), "待審核")
        rs = _row(no)[0]["approval"]["reasons"]
        assert rs == [NOTE_I % "項目"], rs

    def test_submit_via_update_notes_label_change_and_keeps_other_reasons(self, client, hdr):
        no = _create(client, hdr, _data())
        r = client.put(f"/api/quotations/{no}", headers=hdr, json={"status": "待審核", "data": _data(
            quoteNo=no, columnLabels={"brand": "型號"}, validDays=60, approval={"status": "pending", "reasons": []})})
        assert r.status_code == 200, r.text
        rs = _row(no)[0]["approval"]["reasons"]
        assert "有效期限 60 天（超過 30 天）" in rs and NOTE_B % "型號" in rs
        assert rs[-1] == NOTE_B % "型號"

    def test_submit_without_label_change_behaves_as_before(self, client, hdr):
        no = _create(client, hdr, _data(approval={"status": "pending", "reasons": ["假的"]}), "待審核")
        assert _row(no)[0]["approval"]["reasons"] == ["標準報價單送出"]
        no2 = _create(client, hdr, _data(columnLabels={"brand": DEFAULT, "item": ITEM}, customerName="另一家"), "待審核")
        assert _row(no2)[0]["approval"]["reasons"] == ["標準報價單送出"]

    def test_forged_label_reason_in_client_reasons_is_replaced(self, client, hdr):
        fake = NOTE_B % "偽造"
        no = _create(client, hdr, _data(approval={"status": "pending", "reasons": [fake]}), "待審核")
        assert fake not in _row(no)[0]["approval"]["reasons"]


# ── 解鎖編輯重簽 ─────────────────────────────────────────────────────────────

class TestUnlockEdit:
    pytestmark = pytestmark_api
    NO = "MQ-BRANDLBL-001"

    def _seed(self, labels=None):
        import db
        data = {"quoteNo": self.NO, "customerName": "解鎖客戶", "projectName": "解鎖案", "docType": "quote",
                "items": [{"id": "i1", "description": "品項", "qty": 1, "price": 100}],
                "approval": {"requestedBy": "bl_req", "requestedByDisplay": "bl_req", "requestedAt": "2026-11-16T09:00:00",
                             "status": "approved", "approvedBy": "bl_sa"}}
        if labels:
            data["columnLabels"] = labels
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM quotations WHERE quote_no=?", (self.NO,))
            conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at, doc_type) "
                         "VALUES (?,?,?,?,?,?,?,?,?)",
                         (self.NO, "已送出", "解鎖客戶", "解鎖案", 100, json.dumps(data, ensure_ascii=False), "2026-11-16", "2026-11-16", "quote"))
            conn.commit()
        finally:
            conn.close()

    def _put(self, client, h, labels):
        d = {"customerName": "解鎖客戶", "projectName": "解鎖案", "items": [{"id": "i1", "description": "品項", "qty": 1, "price": 100}],
             "_isUnlockEdit": True}
        if labels is not None:
            d["columnLabels"] = labels
        return client.put(f"/api/quotations/{self.NO}", headers=h, json={"status": "待審核", "data": d})

    @pytest.fixture
    def sa(self, client, make_user, monkeypatch):
        from modules.case.api import quotations as Q
        monkeypatch.setattr(Q, "spawn_bg_thread", lambda *a, **k: None)
        u, p = make_user(username="bl_sa", role="superadmin", modules=["quotation"])
        make_user(username="bl_req", role="admin", modules=["quotation"])
        make_user(username="bl_a1", role="admin", modules=["quotation"])
        import db
        conn = db.get_db()                       # 簽核鏈要有人可簽（否則解鎖重簽會 400「簽核人未設定」）
        try:
            conn.execute("INSERT OR REPLACE INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                         ("unified_approval_flow", json.dumps({"tiers": [{"approvers": [{"username": "bl_a1", "display_name": "bl_a1"}]}],
                                                               "includeSubmitterManagerTier": False}, ensure_ascii=False),
                          "2026-11-17T00:00:00"))
            conn.commit()
        finally:
            conn.close()
        return _auth(client, u, p)

    def test_unlock_edit_notes_label_changes_for_both_columns(self, client, sa):
        self._seed()
        r = self._put(client, sa, {"brand": "料號", "item": "品項"})
        assert r.status_code == 200, r.text
        rs = _row(self.NO)[0]["approval"]["reasons"]
        assert rs[0].startswith("解鎖後修改") and NOTE_I % "品項" in rs and NOTE_B % "料號" in rs, rs

    def test_unlock_edit_again_after_label_set_still_notes_and_reset_clears(self, client, sa):
        self._seed({"brand": "規格"})
        assert self._put(client, sa, {"brand": "規格"}).status_code == 200
        assert NOTE_B % "規格" in _row(self.NO)[0]["approval"]["reasons"]
        self._seed({"brand": "規格"})
        assert self._put(client, sa, {}).status_code == 200
        d = _row(self.NO)[0]
        assert "columnLabels" not in d and len(d["approval"]["reasons"]) == 1, d["approval"]["reasons"]
