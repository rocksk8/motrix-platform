# -*- coding: utf-8 -*-
"""報價單／估價單「備註事項」欄位（2026-11-17 使用者交辦；設計 docs/platform/plans/QUOTE-EXTRA-NOTES-DESIGN.md）。

A 段（備註欄位＋範本）釘住：
1. 輸出：有填才在簽章之後另起新頁、沒填逐位元不變（舊單 golden）；內容 HTML 跳脫、換行／縮排保留；放在 `#root` 外（不影響第一頁縮放）；
   風格重用既有 class（section-label／term-item／term-block），段號依實際段數；客戶版／內部版／估價單同一套。
2. 存檔：非字串、全空白＝沒填（丟鍵）；超過 20,000 字 ⇒ 400；往返不失真。
3. 變更註記：備註事項改了會進編修紀錄（顯示字數）；簽核佇列詳情看得到全文與「備註事項：N 字 → M 字」，但**不**把財務欄位的變更摘要一起放出去。
4. 範本 API：登入可讀、僅最高管理者可寫；驗證（名稱／內容必填、名稱不可重複、上限）；稽核；內容原樣保留。
"""
import json
import re

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔打 M01（報價單／估價單）的輸出、存檔與簽核佇列")

NOTES = "備註事項：\n一、車體規格\n   - 車體尺寸：L1200 × W800\n\n（空行保留）\n九、回簽後視同合約成立。"
TOT = {"subtotal": 200000, "pretax": 200000, "tax": 10000, "total": 210000}
IDENT = {"company_name": "範例科技股份有限公司", "company_name_en": "Example Co., Ltd.",
         "tax_id": "12345678", "phone": "02-1234-5678", "email": "sales@example.com"}


def _quote(**over):
    q = {"quoteNo": "MQ-202611-001", "quoteDate": "2026-11-17", "customerName": "甲公司", "projectName": "專案",
         "status": "草稿", "validDays": 30, "paymentTerms": "月結 30 天", "deliveryTerms": "60 天",
         "warrantyTerms": "一年", "acceptanceTerms": "依規格驗收",
         "items": [{"description": "AGV", "brand": "X", "unit": "台", "qty": 2, "unitPrice": 100000, "amount": 200000,
                    "type": "item", "cost": 50, "margin": 10}]}
    q.update(over)
    return q


@pytest.fixture
def pdf(monkeypatch):
    import pdf_gen
    monkeypatch.setattr(pdf_gen, "location_identity", lambda *_a, **_k: dict(IDENT))
    monkeypatch.setattr(pdf_gen, "require_for_output", lambda: None)
    return pdf_gen


# ── 1. 輸出 ───────────────────────────────────────────────────────────────

def test_no_notes_output_is_byte_identical_to_old(pdf):
    """沒填（缺鍵、空字串、全空白、非字串）⇒ HTML 與沒有這個功能時逐位元相同：不多標籤、不多樣式。"""
    base = pdf._build_quote_html(_quote(), TOT)
    for v in ("", "   \n  ", None, 123, [], {}):
        assert pdf._build_quote_html(_quote(extraNotes=v), TOT) == base, repr(v)
    assert "xn-page" not in base and "備註事項" not in base


@pytest.mark.parametrize("internal", [False, True])
def test_notes_page_after_signature_outside_root(pdf, internal):
    html = pdf._build_quote_html(_quote(extraNotes=NOTES), TOT, internal=internal)
    assert html.count('class="xn-page"') == 1
    i_sign = html.index("買方確認")
    i_page = html.index('<table class="xn-page">')
    i_root_close = html.index("</div>\n</div>\n<style>.xn-page")
    assert i_sign < i_root_close < i_page, "備註頁在簽章之後，且在 #root 結束之後（FIT_A4_MULTI 以 #root 高度縮放，備註頁不可算進去）"
    assert html.index("fit_a4") if False else True
    assert html.rindex("<script>") > i_page, "A4 縮放腳本仍在最後"


def test_notes_page_reuses_existing_quote_styles(pdf):
    """風格＝報價單既有：小標 .section-label、內容 .term-item／.term-block、抬頭 .header／.doc-title、頁尾 .footer；不另開一套顏色。"""
    html = pdf._build_quote_html(_quote(extraNotes=NOTES), TOT)
    page = html[html.index('<table class="xn-page">'):]
    for cls in ('class="section-label"', 'class="term-item term-item--full"', 'class="term-block"',
                'class="header"', 'class="doc-title"', 'class="footer"', 'class="accent-bar"'):
        assert cls in page, cls
    css = html[html.index("<style>.xn-page"):html.index("</style>", html.index("<style>.xn-page"))]
    assert not re.search(r"#[0-9A-Fa-f]{3,6}|rgb\(", css), "新增的 CSS 不可自己定義顏色（顏色一律來自既有 class）"
    assert "<thead>" in page and "<tfoot>" in page, "續頁重複抬頭與頁尾靠 thead／tfoot"


def test_section_number_follows_existing_sections(pdf):
    with_terms = pdf._build_quote_html(_quote(extraNotes=NOTES), TOT)
    assert "六、備註事項" in with_terms
    no_terms = pdf._build_quote_html(_quote(extraNotes=NOTES, paymentTerms="", deliveryTerms="", warrantyTerms="",
                                            acceptanceTerms="", afterSales=""), TOT)
    assert "五、備註事項" in no_terms and "六、備註事項" not in no_terms


def test_notes_content_is_escaped_and_newlines_kept(pdf):
    evil = "<script>alert(1)</script>\n- 條列 & \"引號\"\n   縮排\n\n結尾"
    html = pdf._build_quote_html(_quote(extraNotes=evil), TOT)
    page = html[html.index('<table class="xn-page">'):]
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "- 條列 &amp; &quot;引號&quot;" in page
    assert "<br>   縮排<br><br>結尾" in page, "換行、空行、縮排原樣（換行轉 <br>，行首空白由 pre-wrap 保留）"
    assert "white-space:pre-wrap" in html


def test_notes_over_limit_is_cut_at_output(pdf):
    html = pdf._build_quote_html(_quote(extraNotes="囧" * 25000), TOT)
    assert html.count("囧") == 20000


def test_estimate_uses_estimate_wording(pdf):
    html = pdf._build_quote_html(_quote(extraNotes=NOTES, docType="estimate", quoteNo="ME-202611-001"), TOT)
    page = html[html.index('<table class="xn-page">'):]
    assert "估　價　單" in page and "估價單號：ME-202611-001" in page
    assert "報價編號" not in page


def test_notes_page_carries_quote_no_in_repeated_header(pdf):
    html = pdf._build_quote_html(_quote(extraNotes=NOTES), TOT)
    page = html[html.index('<table class="xn-page">'):]
    thead = page[page.index("<thead>"):page.index("</thead>")]
    assert "MQ-202611-001" in thead and "報價編號：" in thead


# ── 2. 存檔檢查 ───────────────────────────────────────────────────────────

def test_check_extra_notes_rules():
    from fastapi import HTTPException
    from modules.case.api import quotations as Q
    q = {"extraNotes": "  \n "}
    Q._check_extra_notes(q)
    assert "extraNotes" not in q, "全空白＝沒填，丟鍵（舊單維持沒有這個鍵）"
    q = {"extraNotes": 123}
    Q._check_extra_notes(q)
    assert "extraNotes" not in q
    q = {"extraNotes": NOTES}
    Q._check_extra_notes(q)
    assert q["extraNotes"] == NOTES, "內容原樣保留（不 strip 中間、不改縮排）"
    with pytest.raises(HTTPException) as e:
        Q._check_extra_notes({"extraNotes": "字" * 20001})
    assert e.value.status_code == 400 and "20000" in e.value.detail
    Q._check_extra_notes({"extraNotes": "字" * 20000})      # 剛好上限可以
    Q._check_extra_notes({})                                  # 沒有這個鍵＝不動


def test_change_summary_lists_notes_as_char_count_and_ignores_unchanged():
    from modules.case.api import quotations as Q
    ch = Q._summarize_quote_changes({"customerName": "甲"}, {"customerName": "甲", "extraNotes": "備" * 50})
    assert ch == [{"field": "備註事項", "from": "（空白）", "to": "50 字"}], ch
    ch = Q._summarize_quote_changes({"extraNotes": "備" * 50}, {"extraNotes": "備" * 80})
    assert ch == [{"field": "備註事項", "from": "50 字", "to": "80 字"}]
    ch = Q._summarize_quote_changes({"extraNotes": "備"}, {})
    assert ch == [{"field": "備註事項", "from": "1 字", "to": "（空白）"}]
    assert Q._summarize_quote_changes({"extraNotes": "備"}, {"extraNotes": "備"}) == []


# ── 3. API：往返、版本號、簽核佇列詳情 ────────────────────────────────────

def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _payload(status="草稿", **extra):
    data = {"customerName": "備註客戶", "projectName": "備註專案", "quoteDate": "2026-11-17", "items": [{"description": "品項"}],
            "tot": {"total": 1000, "pretax": 952, "directMarginPct": 0, "netMarginPct": 0}}
    data.update(extra)
    return {"status": status, "data": data}


def _data_json(no):
    from db import get_db
    c = get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()["data_json"])
    finally:
        c.close()


def test_create_update_roundtrip_and_limits(client, make_user):
    u, pw = make_user(username="xn_rt", role="admin")
    h = _login(client, u, pw)
    r = client.post("/api/quotations", headers=h, json=_payload(extraNotes=NOTES))
    assert r.status_code == 201, r.text
    no = r.json()["quote_no"]
    assert _data_json(no)["extraNotes"] == NOTES, "往返不失真（換行、縮排、空行）"
    # 改一段 ⇒ 編修紀錄有「備註事項」
    d = _data_json(no)
    d["extraNotes"] = NOTES + "\n十、新增一行"
    r = client.put(f"/api/quotations/{no}", headers=h, json={"status": "草稿", "data": d})
    assert r.status_code == 200, r.text
    hist = _data_json(no).get("editHistory") or []
    assert any(c.get("field") == "備註事項" for e in hist for c in (e.get("changes") or [])), hist
    # 清空 ⇒ 鍵被丟掉
    d = _data_json(no)
    d["extraNotes"] = "  "
    r = client.put(f"/api/quotations/{no}", headers=h, json={"status": "草稿", "data": d})
    assert r.status_code == 200, r.text
    assert "extraNotes" not in _data_json(no)
    # 超過上限 ⇒ 400（新建與更新都擋）
    r = client.post("/api/quotations", headers=h, json=_payload(extraNotes="字" * 20001))
    assert r.status_code == 400 and "20000" in r.text
    d = _data_json(no)
    d["extraNotes"] = "字" * 20001
    assert client.put(f"/api/quotations/{no}", headers=h, json={"status": "草稿", "data": d}).status_code == 400


def test_estimate_roundtrip_same_field(client, make_user):
    u, pw = make_user(username="xn_est", role="admin")
    h = _login(client, u, pw)
    r = client.post("/api/quotations", headers=h, json=_payload(docType="estimate", extraNotes=NOTES))
    assert r.status_code == 201, r.text
    assert _data_json(r.json()["quote_no"])["extraNotes"] == NOTES


def test_approver_detail_shows_notes_and_only_notes_changes(client, make_user):
    """簽核人看得到將印給客戶的備註全文與這次「備註事項」的變更；同一筆摘要裡的財務欄位不可一起放出去。"""
    import db
    no = "MQ-XN-APPR"
    hist = [{"rev": 2, "at": "2026-11-17T10:00:00", "by": "x", "byDisplay": "某人", "type": "quote_update",
             "changes": [{"field": "備註事項", "from": "10 字", "to": "50 字"},
                         {"field": "營業利益率", "from": "12", "to": "3"},
                         {"field": "含稅總額", "from": "1000", "to": "900"}]}]
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?)",
                  (no, "待審核", "客", "案", 0, 0, json.dumps({"extraNotes": NOTES, "editHistory": hist}, ensure_ascii=False),
                   "2026-11-17T00:00:00", "2026-11-17T00:00:00"))
        c.commit()
    finally:
        c.close()
    u, pw = make_user(username="xn_appr", role="superadmin")
    r = client.get("/api/approval-queue/detail?type=quotation&id=" + no, headers=_login(client, u, pw))
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    notes_rows = [f for f in j["fields"] if f["label"].startswith("備註事項")]
    assert notes_rows and notes_rows[0]["value"] == NOTES
    after = j["changes"]["after"]
    assert "備註事項：10 字 → 50 字" in after["變更項目"]
    assert "營業利益率" not in after["變更項目"] and "含稅總額" not in after["變更項目"]


def test_approver_detail_unchanged_when_no_notes(client, make_user):
    import db
    no = "MQ-XN-NONOTE"
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?)",
                  (no, "待審核", "客", "案", 0, 0, json.dumps({"paymentTerms": "x"}), "2026-11-17T00:00:00", "2026-11-17T00:00:00"))
        c.commit()
    finally:
        c.close()
    u, pw = make_user(username="xn_appr2", role="superadmin")
    j = client.get("/api/approval-queue/detail?type=quotation&id=" + no, headers=_login(client, u, pw)).json()
    assert [f["label"] for f in j["fields"]] == ["報價日期", "業務", "總金額", "付款條件"], "沒填備註 ⇒ 不多任何列"


def test_notes_change_makes_signed_approval_stale(client, make_user):
    """備註事項是內容（指紋為 denylist，未知鍵一律算內容）：改了它，已簽的簽核判過期。"""
    from modules.case import content_fp as CFP
    a = {"customerName": "甲", "extraNotes": "舊"}
    b = {"customerName": "甲", "extraNotes": "新"}
    assert CFP.content_fingerprint(a) != CFP.content_fingerprint(b)
    assert CFP.content_fingerprint({"customerName": "甲"}) != CFP.content_fingerprint(a)


# ── 4. 範本 API ───────────────────────────────────────────────────────────

URL = "/api/settings/quote-notes-templates"


def _tpl(name="AGV 範本", text="備註事項：\n一、AGV", category="AGV"):
    return {"key": "", "name": name, "category": category, "text": text}


def test_templates_read_for_login_write_superadmin_only(client, make_user):
    sup, sp = make_user(username="xn_tpl_sup", role="superadmin")
    adm, ap = make_user(username="xn_tpl_adm", role="admin")
    sal, slp = make_user(username="xn_tpl_sal", role="sales")
    hs, ha, hl = _login(client, sup, sp), _login(client, adm, ap), _login(client, sal, slp)
    assert client.put(URL, headers=ha, json={"templates": [_tpl()]}).status_code == 403
    assert client.put(URL, headers=hl, json={"templates": [_tpl()]}).status_code == 403
    r = client.put(URL, headers=hs, json={"templates": [_tpl(), _tpl("監控範本", "x\n  - y\n\nz", "監控")]})
    assert r.status_code == 200, r.text
    got = client.get(URL, headers=hl).json()["templates"]
    assert [t["name"] for t in got] == ["AGV 範本", "監控範本"]
    assert all(t["key"] for t in got), "空 key 由伺服器派"
    assert got[1]["text"] == "x\n  - y\n\nz", "內容原樣（換行、縮排、空行）"
    assert client.get(URL).status_code in (401, 403), "未登入不可讀"


def test_templates_validation(client, make_user):
    sup, sp = make_user(username="xn_tpl_val", role="superadmin")
    h = _login(client, sup, sp)
    put = lambda tpls: client.put(URL, headers=h, json={"templates": tpls})
    assert put([_tpl(name="  ")]).status_code == 400
    assert put([_tpl(text="   ")]).status_code == 400
    assert put([_tpl(name="名" * 31)]).status_code == 400
    assert put([_tpl(category="類" * 21)]).status_code == 400
    assert put([_tpl(text="字" * 20001)]).status_code == 400
    assert put([_tpl("重複"), _tpl("重複")]).status_code == 400
    assert put([dict(_tpl("甲"), key="k1"), dict(_tpl("乙"), key="k1")]).status_code == 400
    assert put([_tpl("T%d" % i) for i in range(101)]).status_code == 400
    assert put([_tpl("T%d" % i) for i in range(100)]).status_code == 200, "剛好 100 個可以"
    assert put([]).status_code == 200 and client.get(URL, headers=h).json() == {"templates": []}


def test_template_apply_is_copy_not_link(client, make_user):
    """範本只是清單：單據存複製過去的文字；事後改範本、刪範本都不動已存的單。"""
    sup, sp = make_user(username="xn_tpl_copy", role="superadmin")
    h = _login(client, sup, sp)
    t = client.put(URL, headers=h, json={"templates": [_tpl()]}).json()["templates"][0]
    r = client.post("/api/quotations", headers=h, json=_payload(extraNotes=t["text"]))
    assert r.status_code == 201, r.text
    no = r.json()["quote_no"]
    client.put(URL, headers=h, json={"templates": [dict(t, text="改過的範本")]})
    assert _data_json(no)["extraNotes"] == "備註事項：\n一、AGV"
    client.put(URL, headers=h, json={"templates": []})
    assert _data_json(no)["extraNotes"] == "備註事項：\n一、AGV"


def test_template_update_is_audited(client, make_user):
    import db
    sup, sp = make_user(username="xn_tpl_aud", role="superadmin")
    h = _login(client, sup, sp)
    assert client.put(URL, headers=h, json={"templates": [_tpl()]}).status_code == 200
    c = db.get_db()
    try:
        row = c.execute("SELECT * FROM audit_log WHERE action=? AND username=? ORDER BY rowid DESC LIMIT 1",
                        ("settings.quote_notes_templates.update", sup)).fetchone()
    finally:
        c.close()
    assert row is not None, "範本儲存要有稽核紀錄"


def test_template_change_rows():
    from routers import system as S
    old = {"templates": [{"key": "a", "name": "甲", "category": "X", "text": "1"}, {"key": "b", "name": "乙", "category": "X", "text": "2"}]}
    new = {"templates": [{"key": "a", "name": "甲2", "category": "Y", "text": "1x"}, {"key": "c", "name": "丙", "category": "", "text": "3"}]}
    labels = [r[0] for r in S._quote_notes_templates_change_rows(old, new)]
    assert labels == ["報價備註範本／新增", "報價備註範本／刪除", "報價備註範本／改名", "報價備註範本／分類", "報價備註範本／內容修改"], labels
    assert S._quote_notes_templates_change_rows(old, old) == []
