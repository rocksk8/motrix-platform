# -*- coding: utf-8 -*-
"""2026-11-13（T83 fix/estimate-static-labels）：估價單走到的「靜態／登記表」用語不可寫死「報價單」。

接續 `test_estimate_mail_doc_name_2026_11_13.py`（動態信件本文）：這裡管登記表與目錄這一層。
  DYN（依單據類型）：簽核信 footer／預設影響／處理方式、簽核佇列 typeLabel、完工單帶入提示、資源回收筒訊息、
                    業務開發轉建的行事曆文字與通知、PDF 下載檔名。
  NEU（中性「報價單／估價單」）：信件類型名稱、通知偏好、簽核流程設定頁、事件目錄、稽核模組名、業務開發頁彈窗。
  反向：報價單（MQ-）逐字不變——舊字串一個字都不能少、「估價單」一個字都不能出現。
"""
from tests._requires import requires_module  # noqa: E402
import re
from pathlib import Path

import pytest

pytestmark = requires_module("case", "本檔打 M01（案件）的通知與資料（報價單／估價單）")

EST_NO = "ME-202611-001"
QUO_NO = "MQ-202611-001"
NEU = "報價單／估價單"
_ROOT = Path(__file__).resolve().parents[2]


def _est(text):
    assert "估價單" in text and "報價單" not in text, text


def _quo(text):
    assert "報價單" in text and "估價單" not in text, text


@pytest.fixture
def mails(monkeypatch):
    from helpers import email_notify as E
    sent = []
    monkeypatch.setattr(E, "_lookup_emails", lambda *a, **k: ["a@example.com"])
    monkeypatch.setattr(E, "_tpl_fields", lambda *a, **k: {})
    monkeypatch.setattr(E, "_admin_emails", lambda *a, **k: ["a@example.com"])
    monkeypatch.setattr(E, "_async_send", lambda to, subject, html, *a, **k: sent.append((to, subject, html)))
    return sent


# ── A. 簽核信：footer／預設影響／處理方式依單據類型 ─────────────────────────────

def _fire(E, name, lab, no, cust):
    return {
        "approval_request": lambda: E.notify_approval_request(no, cust, ["u"], lab),
        "next_tier": lambda: E.notify_next_tier(no, cust, 2, 3, ["u"], lab),
        "approved": lambda: E.notify_approved(no, cust, "某人", "u", lab),
        "returned": lambda: E.notify_returned(no, "N-R1", cust, "備註", "u", lab),
        "resubmit": lambda: E.notify_resubmit_requester(no, "N", cust, "u", ["某人"], lab),
    }[name]()


@pytest.mark.parametrize("name", ["approval_request", "next_tier", "approved", "returned", "resubmit"])
def test_estimate_approval_mail_has_no_quote_word_outside_customer_text(mails, name):
    from helpers import email_notify as E
    cust = "報價單客戶有限公司"        # 客戶自己的名字含「報價單」：必須原樣保留、不被換字
    _fire(E, name, "估價單", EST_NO, cust)
    html = mails[-1][2]
    assert cust in html, "客戶名稱（使用者輸入）要原樣出現"
    rest = html.replace(cust, "")
    assert "報價單" not in rest, re.findall(r".{12}報價單.{12}", rest)
    assert "估價單" in rest
    assert "／估價單" not in rest and "報價單／" not in rest, "共用名稱要換成實際單據名，不可外露斜線版"


@pytest.mark.parametrize("name", ["approval_request", "next_tier", "approved", "returned", "resubmit"])
def test_quote_approval_mail_stays_quote_only(mails, name):
    from helpers import email_notify as E
    _fire(E, name, "報價單", QUO_NO, "客")
    html = mails[-1][2]
    assert "估價單" not in html and "報價單／" not in html and "／報價單" not in html
    assert re.search(r"信件類型：(修改版)?報價單", html), "footer 仍是「信件類型：（修改版）報價單…」"


def test_quote_registry_defaults_are_the_legacy_strings():
    """報價單：預設影響／處理方式／footer 名稱＝改版前逐字（共用名稱 ⇒ 換回「報價單」）。"""
    from helpers import email_notify as E
    from helpers import mail_types as mt
    t = mt.get("approval_request")
    assert E._concrete(t.impact, "報價單") == "報價單在您簽核之前不會進入下一個流程。"
    assert E._concrete(mt.get("approved").impact, "報價單") == "報價單已核准，可以對外提供。"
    assert E._concrete(mt.get("approval_request").name, "報價單") == "報價單待簽核"
    assert E._concrete(mt.get("approved").name, "報價單") == "報價單簽核完成"
    assert E._concrete(mt.get("approved").impact, "估價單") == "估價單已核准，可以對外提供。"
    # 非共用名稱（出貨單等）兩種單據都不動
    s = mt.get("shipping_submitted")
    assert E._concrete(s.name, "估價單") == s.name == "出貨單待簽核"


def test_build_html_without_quote_no_uses_the_quote_label(mails):
    from helpers import email_notify as E
    html = E._build_html("approval_request", "t", "b", "#000", [], "", "https://h/x.html")
    assert "估價單" not in html and "信件類型：報價單待簽核" in html


# ── B. 簽核佇列 typeLabel ───────────────────────────────────────────────────

def test_approval_queue_type_label_follows_the_doc_no(client, make_user):
    from db import get_db
    from modules.case.api import quotations as Q
    u, pw = make_user(username="est_q", role="admin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    nos = {}
    for dt in ("estimate", None):
        data = {"customerName": "客", "projectName": "案", "quoteDate": "2026-11-13", "items": [{"description": "品"}],
                "tot": {"total": 100, "pretax": 95}}
        if dt:
            data["docType"] = dt
        rr = client.post("/api/quotations", headers=h, json={"status": "草稿", "data": data})
        assert rr.status_code == 201, rr.text
        nos[dt or "quote"] = rr.json()["quote_no"]
    conn = get_db()
    try:
        for n in nos.values():
            conn.execute("UPDATE quotations SET status='待審核' WHERE quote_no=?", (n,))
        conn.commit()
        items = {i["quoteNo"]: i for i in Q.approval_queue_items(conn) if i.get("type") == "quotation"}
    finally:
        conn.close()
    assert items[nos["estimate"]]["typeLabel"] == "估價單"
    assert items[nos["quote"]]["typeLabel"] == "報價單"
    from routers import approval_queue as aq
    assert aq._item_type_label(items[nos["estimate"]]) == "估價單"
    assert aq._item_type_label(items[nos["quote"]]) == "報價單"


# ── C. 完工單帶入提示 ───────────────────────────────────────────────────────

def test_completion_gate_message_label_param_and_legacy_default():
    from modules.case import completion_sync as CS
    assert CS.gate_message("已送出") is None and CS.gate_message("已送出", "估價單") is None
    for status in ("草稿", "簽核中", "待審核", "已取消", "已拒絕", "某個沒見過的狀態"):
        legacy = CS.gate_message(status)
        est = CS.gate_message(status, "估價單")
        if legacy is None:
            assert est is None
            continue
        assert "報價單" in legacy and "估價單" not in legacy, legacy
        assert est == legacy.replace("報價單", "估價單"), (legacy, est)
    # 改版前逐字
    assert CS.gate_message("簽核中") == "報價單還在編輯或簽核中，項目可能還會變，請等報價送出後再帶入"
    assert CS.gate_message("已取消") == "這張報價單已取消或被拒絕，不能帶入項目"
    assert CS.gate_message("怪狀態") == "報價單目前的狀態不能帶入項目"


def test_completion_quote_items_not_found_says_the_right_doc(client, make_user):
    u, pw = make_user(username="est_cn", role="admin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    est = client.get("/api/completion-notes/quote-items", params={"quote_no": "ME-209912-999"}, headers=h)
    quo = client.get("/api/completion-notes/quote-items", params={"quote_no": "MQ-209912-999"}, headers=h)
    assert est.status_code == 404 and quo.status_code == 404
    assert est.json()["detail"] == "找不到可帶入的估價單"
    assert quo.json()["detail"] == "找不到可帶入的報價單", "報價單：逐字不變"


# ── D. 資源回收筒（暫存區）轉接器 ───────────────────────────────────────────────

def test_recycle_adapter_labels_follow_the_doc_no(client):
    from db import get_db
    from modules.case import recycle_adapter as RA
    ad = RA.QuotationAdapter() if hasattr(RA, "QuotationAdapter") else None
    if ad is None:
        cls = [c for c in vars(RA).values() if isinstance(c, type) and getattr(c, "entity_type", "") == "quotation"]
        assert cls, "找不到 quotation 轉接器類別"
        ad = cls[0]()
    assert ad.label == "報價單／估價單／案件"
    conn = get_db()
    try:
        ok, msg = ad.can_delete(conn, "ME-209912-998", {"username": "x"})
        ok2, msg2 = ad.can_delete(conn, "MQ-209912-998", {"username": "x"})
    finally:
        conn.close()
    assert not ok and msg == "估價單 ME-209912-998 不存在"
    assert not ok2 and msg2 == "報價單 MQ-209912-998 不存在", "報價單：逐字不變"
    with pytest.raises(Exception) as e1:
        RA._need_parent(get_db(), "ME-209912-998")
    with pytest.raises(Exception) as e2:
        RA._need_parent(get_db(), "MQ-209912-998")
    _est(str(e1.value))
    _quo(str(e2.value))


# ── E. 行事曆／業務開發轉建 ───────────────────────────────────────────────────

def test_dev_case_converted_calendar_text_follows_type(monkeypatch):
    from db import get_db
    from helpers import google_calendar as G
    conn = get_db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(dev_cases)").fetchall()]
    if not cols:
        conn.close()
        pytest.skip("dev_cases 不在此環境")
    ids = {}
    try:
        for tag, no in (("est", EST_NO), ("quo", QUO_NO)):
            conn.execute("INSERT INTO dev_cases (case_name, customer_name, converted_quote_no, status, created_at, updated_at) "
                         "VALUES (?,?,?,?,?,?)", ("報價單專案{x}", "客{戶}", no, "成案", "2026-11-13", "2026-11-13"))
            ids[tag] = conn.execute("SELECT MAX(id) FROM dev_cases").fetchone()[0]
        conn.commit()
    except Exception as e:      # noqa: BLE001
        conn.close()
        pytest.skip("dev_cases 欄位與測試預期不同：%s" % e)
    conn.close()
    got = {}
    monkeypatch.setattr(G, "event_enabled", lambda *a, **k: True)
    monkeypatch.setattr(G, "_create_event_with_retry", lambda title, desc, *a, **k: got.__setitem__(len(got), (title, desc)) or None)
    G.push_event_for_dev_case_converted(ids["est"])
    G.push_event_for_dev_case_converted(ids["quo"])
    assert len(got) == 2, got
    est = got[0][0] + got[0][1]
    assert "報價單專案{x}" in est and "客{戶}" in est, "案名／客戶名（含大括號）原樣保留、不被模板處理吃掉"
    _est(est.replace("報價單專案{x}", ""))
    quo = got[1][0] + got[1][1]
    assert got[1][0] == "業務開發案件轉建報價單 — 報價單專案{x}（客{戶}）"
    assert got[1][1] == "業務開發案件「報價單專案{x}」已轉建為報價單。\n客戶：客{戶}\n報價單號：" + QUO_NO, "報價單：逐字不變"
    assert "估價單" not in quo


# ── F. PDF 下載檔名 ──────────────────────────────────────────────────────────

def test_download_name_has_estimate_keys_with_settings_entries():
    from helpers import download_name as D
    from helpers import settings_groups as SG
    assert D.DOC_TYPES["estimate"] == "估價單" and D.DOC_TYPES["estimate_version"] == "估價單存檔版本"
    assert D.DOC_TYPES["quotation"] == "報價單" and D.DOC_TYPES["quotation_version"] == "報價單存檔版本"
    assert D.DEFAULTS["label_estimate"] == "估價單" and D.DEFAULTS["label_estimate_version"] == "估價單存檔版本"
    src = Path(SG.__file__).read_text(encoding="utf-8")
    assert 'S("label_estimate"' in src and 'S("label_estimate_version"' in src


def test_download_name_build_uses_the_estimate_label():
    from helpers import download_name as D
    e = D.build("estimate", quote_no=EST_NO, doc_no=EST_NO, ext="pdf", user=None)
    q = D.build("quotation", quote_no=QUO_NO, doc_no=QUO_NO, ext="pdf", user=None)
    ev = D.build("estimate_version", quote_no=EST_NO, doc_no=EST_NO, ext="pdf", user=None)
    assert e.name and q.name and ev.name
    # user=None ⇒ 降級成只有單號的檔名（不變式④）；單號本身就是兩種單據的區別，標籤只在有案件資訊時才出現
    assert EST_NO in e.name and QUO_NO in q.name


def test_pdf_endpoints_pick_the_estimate_download_key():
    src = (_ROOT / "backend" / "modules" / "case" / "api" / "quotations.py").read_text(encoding="utf-8")
    assert '"estimate" if _DT.doc_type_of_no(quote_no) == _DT.ESTIMATE else "quotation"' in src
    assert '"estimate_version" if _DT.doc_type_of_no(quote_no) == _DT.ESTIMATE else "quotation_version"' in src


# ── G. 中性用語（共用名稱）────────────────────────────────────────────────────

def test_shared_names_use_the_neutral_wording():
    from helpers import mail_types as mt
    from helpers import notification_prefs as np_
    from helpers import tiered_approval as ta
    from helpers import google_calendar as G
    from helpers import audit as A
    for key in ("approval_request", "next_tier", "approved", "returned", "resubmit_requester"):
        assert NEU in mt.get(key).name, key
    assert NEU in mt.get("dev_case_relink_request").impact
    groups = dict(np_.EVENT_GROUPS)["簽核流程"]
    names = dict(groups)
    for key in ("approval_request", "next_tier", "approved", "returned", "resubmit_requester"):
        assert NEU in names[key], key
    assert ta.DOC_TYPE_LABELS["quotation"] == NEU if hasattr(ta, "DOC_TYPE_LABELS") else True
    ev = {e[0]: e for e in G.EVENT_TYPES}
    assert NEU in ev["quotation_won"][1] and NEU in ev["dev_case_converted"][1]
    assert A._MODULE_LABELS["quotation"] == NEU


def test_settings_pages_and_dev_crm_page_use_neutral_wording():
    from core.source_tree import page_file
    s = page_file("approval-settings.html").read_text(encoding="utf-8")
    assert re.search(r"quotation:\s+'報價單／估價單'", s)
    d = page_file("dev-crm.html").read_text(encoding="utf-8")
    assert "<h3>轉建報價單／估價單</h3>" in d and "<h3>轉建報價單</h3>" not in d
    assert "MQ-YYYYMM-NNN" not in d, "輸入框提示不寫 MQ 字首（估價單是 ME）"
    assert "系統將開啟報價單／估價單表單" in d


# ── H. 跟進（PM 追加）：LINE 標題／列標籤、業務開發連結的「單號不存在」句 ───────────────────

def _line_capture(monkeypatch):
    from helpers import email_notify as E
    got = []
    monkeypatch.setattr(E, "_line_event", lambda key, **kw: got.append((key, kw)))
    monkeypatch.setattr(E, "_lookup_emails", lambda *a, **k: [])        # 不寄信；只看 LINE 呼叫
    monkeypatch.setattr(E, "_tpl_fields", lambda *a, **k: {})
    return E, got


def _line_text(kw):
    return kw["title"] + "|" + "|".join(k + "=" + str(v) for k, v in kw.get("rows") or [])


@pytest.mark.parametrize("name", ["next_tier", "approved", "returned", "resubmit"])
def test_line_titles_and_row_labels_follow_the_doc_label(monkeypatch, name):
    E, got = _line_capture(monkeypatch)
    cust = "報價單客"
    for lab, no in (("估價單", EST_NO), ("報價單", QUO_NO)):
        got.clear()
        _fire(E, name, lab, no, cust)
        assert got, name
        txt = _line_text(got[-1][1]).replace(cust, "")
        (_est if lab == "估價單" else _quo)(txt)


@pytest.mark.parametrize("name,fn", [
    ("settlement", lambda E, no: E.notify_settlement_finalized(no, "客", "某人")),
    ("change", lambda E, no: E.notify_case_change_requested(no, "客", "案", "摘要", "某人")),
])
def test_line_row_labels_of_number_only_mails_follow_the_prefix(monkeypatch, name, fn):
    E, got = _line_capture(monkeypatch)
    monkeypatch.setattr(E, "_admin_emails", lambda *a, **k: [])
    monkeypatch.setattr(E, "_superadmin_emails", lambda *a, **k: [])
    for no, chk in ((EST_NO, _est), (QUO_NO, _quo)):
        got.clear()
        fn(E, no)
        assert got, name
        chk(_line_text(got[-1][1]).replace(no, ""))


def test_dev_case_link_not_found_sentences_follow_the_number():
    src = (_ROOT / "backend" / "modules" / "crm" / "api.py").read_text(encoding="utf-8")
    assert 'f"{_DT.label_of_no(quote_no)} {quote_no} 不存在，無法連結"' in src
    assert 'f"{_DT.label_of_no(target)} {target} 不存在，無法連結"' in src
    assert 'f"{_DT.label_of_no(target)} {target} 已不存在，無法核准，請申請人取消或重新申請"' in src
    from helpers import doc_type as D
    assert f"{D.label_of_no('ME-209912-1')} ME-209912-1 不存在，無法連結" == "估價單 ME-209912-1 不存在，無法連結"
    assert f"{D.label_of_no('MQ-209912-1')} MQ-209912-1 不存在，無法連結" == "報價單 MQ-209912-1 不存在，無法連結"


# ── PDF 本文四處固有用語（T83 fix/estimate-pdf-labels-t83）─────────────────────

_PDF_BASE = {"quoteNo": "XX-202611-001", "customerName": "客", "projectName": "案", "items": [], "quoteDate": "2026-11-13",
             "tot": {"total": 0, "pretax": 0}, "paymentTerms": "月結30天"}
#: 報價單 → 估價單 的四處固有用語（單號／日期／合計／條件）
_PDF_FOUR = (("報價編號：", "估價單號："), ("報價日期：", "估價日期："), ("四、報價合計", "四、估價合計"), ("五、報價條件", "五、估價條件"))


def _pdf_html(**kw):
    import pdf_gen
    return pdf_gen._build_quote_html(dict(_PDF_BASE, **kw), _PDF_BASE["tot"])


def test_estimate_pdf_has_the_four_estimate_labels():
    est = _pdf_html(docType="estimate")
    for old, new in _PDF_FOUR:
        assert new in est and old not in est, (old, new)


def test_quote_pdf_keeps_the_four_quote_labels():
    quo = _pdf_html()
    for old, new in _PDF_FOUR:
        assert old in quo and new not in quo, (old, new)
    assert _pdf_html(docType="quote") == quo                  # 明寫 quote 與沒帶 docType 逐位元相同


def test_estimate_pdf_differs_from_quote_pdf_only_in_those_places():
    """估價單 HTML 把四處新用語與標題換回報價單 ⇒ 必須與報價單 HTML 逐位元相同（沒有多動別的地方）。"""
    est = _pdf_html(docType="estimate")
    for old, new in _PDF_FOUR:
        est = est.replace(new, old)
    est = est.replace("估　價　單", "報　價　單").replace("估　價　人：", "報　價　人：").replace("估價單", "報價單")
    assert est == _pdf_html()


def test_estimate_pdf_wide_case_watermark_internal_items_maps_back_to_the_quote_pdf():
    """浮水印＋提示句＋內部版＋有品項：估價單把『估價』用語換回報價後必須與報價單逐位元相同（沒有多動別處）。"""
    import pdf_gen
    items = [{"description": "品項一", "qty": 2, "unit": "台", "unitPrice": 500, "cost": 300}]
    wm = dict(show_watermark=True, watermark_text="本案報價未成立　僅供存查備存", show_notice=True,
              notice_text="本案報價未成立，此份文件僅供存查備存使用，請勿對外提供或引用", unapproved_status="草稿", internal=True)
    base = dict(_PDF_BASE, items=items, salesPerson="業務")
    est = pdf_gen._build_quote_html(dict(base, docType="estimate"), base["tot"], **wm)
    quo = pdf_gen._build_quote_html(dict(base), base["tot"], **wm)
    assert "品項一" in est
    for old, new in _PDF_FOUR:
        est = est.replace(new, old)
    est = (est.replace("估　價　單", "報　價　單").replace("估　價　人：", "報　價　人：")
              .replace("本案估價未成立", "本案報價未成立").replace("估價單", "報價單"))
    assert est == quo


def test_estimate_pdf_salesperson_label_and_unsettled_wording_follow_the_type():
    """使用者裁示（T83）：估價單印「估　價　人」、未成案浮水印／提示句寫「本案估價未成立…」；報價單逐位元不變。"""
    import pdf_gen
    wm = dict(show_watermark=True, watermark_text="本案報價未成立　僅供存查備存", show_notice=True,
              notice_text="本案報價未成立，此份文件僅供存查備存使用，請勿對外提供或引用", unapproved_status="草稿")
    est = pdf_gen._build_quote_html(dict(_PDF_BASE, docType="estimate"), _PDF_BASE["tot"], **wm)
    quo = pdf_gen._build_quote_html(dict(_PDF_BASE), _PDF_BASE["tot"], **wm)
    assert "估　價　人：" in est and "報　價　人" not in est and "報價" not in est
    assert "本案估價未成立　僅供存查備存" in est and "本案估價未成立，此份文件僅供存查備存使用" in est
    assert "報　價　人：" in quo and "估　價　人" not in quo and "估價" not in quo
    assert "本案報價未成立　僅供存查備存" in quo and "本案報價未成立，此份文件僅供存查備存使用" in quo
    # 預覽／存檔路徑共用的規則（_quote_watermark_kwargs）經同一支 builder ⇒ 估價單同樣換字
    kw = pdf_gen._quote_watermark_kwargs("草稿", "未成案")
    e2 = pdf_gen._build_quote_html(dict(_PDF_BASE, docType="estimate"), _PDF_BASE["tot"], **kw)
    assert "本案估價未成立" in e2 and "報價" not in e2


def test_label_of_no_in_shipping_pdf_is_escape_safe_so_wrapping_it_changes_nothing():
    """出貨單「關聯○○單」用 esc() 包起來（棘輪不加基線）：固定標籤字串經逸出後必須逐字不變。"""
    from helpers import doc_type as D
    from helpers.doc_template import html_text
    for label in D.LABELS.values():
        assert html_text(label, falsy_empty=True) == label
    import pdf_gen
    base = {"noteNo": "SN-1", "shipDate": "2026-11-13", "items": [], "customerName": "客"}
    assert "關聯報價單：" in pdf_gen._build_shipping_html(dict(base, quoteNo=QUO_NO))
    assert "關聯估價單：" in pdf_gen._build_shipping_html(dict(base, quoteNo=EST_NO))
