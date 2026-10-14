# -*- coding: utf-8 -*-
"""G-A：報價單／請款單／完工單 PDF 的頁尾與浮水印文字（BP-3 R4 延伸；只能從預設清單挑，沒有頁首、沒有自由文字）。

①三個匯出已登記（pdf-only、decorOnly、caps＝頁尾＋浮水印）  ②驗證：只准預設文字、不收頁首  ③旗標關／沒有範本 ⇒ builder 回傳同一個字串（逐位元相同）
④有範本 ⇒ 文字逸出、插在 <body> 後；程式產生的橫幅與抬頭不動  ⑤治理：新增或改變文字＝放寬  ⑥頁面宣告 motrix-export-id（每頁一個）
"""
import re
from pathlib import Path

import pytest

import pdf_gen
from core import source_tree
import modules.case.completion_pdf as CP
from helpers import export_templates as ET

ROOT = Path(__file__).resolve().parents[3]
IDS = [pdf_gen.QUOTE_PDF_EXPORT, pdf_gen.PAYMENT_REQUEST_PDF_EXPORT, CP.COMPLETION_PDF_EXPORT]


def _tpl(**parts):
    body = {"version": 1, "format": "pdf"}
    body.update({k: {"text": v} for k, v in parts.items()})
    return body


@pytest.mark.parametrize("eid", IDS)
def test_exports_are_registered_decor_only_with_footer_and_watermark(eid):
    reg = ET.registered()[eid]
    assert reg["formats"] == ["pdf"] and reg["decorOnly"] is True and reg["columns"] == [] and reg["sheets"] == []
    assert reg["caps"] == {"pdf": ["footer", "watermark"]}


@pytest.mark.parametrize("eid", IDS)
def test_validation_only_presets_and_no_header(eid):
    assert ET.definition_problems(eid, _tpl(footer="機密", watermark="草稿")) == []
    assert {p["path"] for p in ET.definition_problems(eid, _tpl(header="機密"))} == {"header"}
    assert {p["path"] for p in ET.definition_problems(eid, _tpl(footer="自己寫的"))} == {"footer.text"}
    assert {p["path"] for p in ET.definition_problems(eid, _tpl(watermark="已核准"))} == {"watermark.text"}, "官方字樣與非預設文字都擋"
    assert ET.definition_problems(eid, {"version": 1, "format": "pdf"}), "至少設定一項"


@pytest.mark.parametrize("eid", IDS)
def test_off_returns_the_same_string_object(eid, monkeypatch):
    monkeypatch.setattr(ET, "resolve", lambda e, conn=None: None)
    html = "<!doctype html><html><body>內容 <b>x</b></body></html>"
    assert ET.decorate_pdf(eid, html) is html


@pytest.mark.parametrize("eid", IDS)
def test_published_template_adds_escaped_text_right_after_body(eid, monkeypatch):
    monkeypatch.setattr(ET, "resolve", lambda e, conn=None: _tpl(footer="機密", watermark="僅供參考") if e == eid else None)
    html = "<!doctype html><html><body class=\"x\">內容</body></html>"
    out = ET.decorate_pdf(eid, html)
    assert out != html and "機密" in out and "僅供參考" in out and "內容" in out
    assert re.search(r'<body class="x"><style>', out), "插在 <body> 之後"
    assert "<script" not in out.lower()


def test_builders_route_through_decorate_pdf_with_their_own_export_ids(monkeypatch):
    calls = []
    monkeypatch.setattr(ET, "decorate_pdf", lambda eid, html, conn=None: calls.append(eid) or html + "<!--decorated-->")
    monkeypatch.setattr(pdf_gen, "_build_quote_html_core", lambda *a, **k: "Q")
    monkeypatch.setattr(pdf_gen, "_build_payment_request_html_core", lambda *a, **k: "P")
    monkeypatch.setattr(CP, "_build_completion_html_core", lambda *a, **k: "C")
    assert pdf_gen._build_quote_html({}, {}, internal=True, show_watermark=True) == "Q<!--decorated-->"
    assert pdf_gen._build_payment_request_html({}) == "P<!--decorated-->"
    assert CP._build_completion_html({}) == "C<!--decorated-->"
    assert calls == IDS


def test_quote_wrapper_keeps_the_original_signature_and_defaults():
    import inspect
    a = inspect.signature(pdf_gen._build_quote_html)
    b = inspect.signature(pdf_gen._build_quote_html_core)
    assert [(p.name, p.default) for p in a.parameters.values()] == [(p.name, p.default) for p in b.parameters.values()]


def test_comparator_new_or_changed_text_is_loosen_and_removal_is_tighten():
    from routers.def_pipeline import classify
    eid = IDS[0]
    a, b = _tpl(footer="機密"), _tpl(footer="機密", watermark="草稿")
    assert classify("export_template", {}, a)[0] == "loosen"
    assert classify("export_template", a, b)[0] == "loosen"
    assert classify("export_template", a, _tpl(footer="內部資料"))[0] == "loosen"
    assert classify("export_template", b, a)[0] == "tighten"
    assert classify("export_template", a, a)[0] == "neutral" and eid


@pytest.mark.parametrize("page,eid", [("quotations.html", IDS[0]), ("payment-request.html", IDS[1]), ("completion-note-form.html", IDS[2])])
def test_pages_declare_exactly_one_export_id(page, eid):
    src = source_tree.page_file(page).read_text(encoding="utf-8")
    metas = re.findall(r'<meta name="motrix-export-id" content="([^"]+)"', src)
    assert metas == [eid], "每頁只能宣告一個匯出代號（編輯器一次只處理一個）"
