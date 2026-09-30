# -*- coding: utf-8 -*-
"""使用者 2026-10-01：未核可單據的警示「太淡、第 2 頁以後幾乎沒有」⇒ 每一個列印頁都要有、而且一眼看得出來。

機制（helpers.doc_template.unapproved_overlay，報價單與所有單據共用；舊的灰色 `.wm`／`.wm-overlay` 在未核可時隱藏）：
  ① `position:fixed` 大斜角紅色浮水印（≥96px、粗體、opacity≈.2；Chromium 列印每頁重畫）
  ② `@page` 邊界框：每頁頂端整條紅底白字「未核可預覽稿 – 不可作為正式文件」＋頁尾「單號 ｜ 未核可・僅供預覽 ｜ 第 N 頁」
  ③ body 背景平鋪斜字（連續長頁的螢幕預覽／fixed 失效時的後備）
驗證：真的用 Edge 印一份 3 頁以上的未核可報價單 PDF，**逐頁**檢查標示文字與紅色繪製；已核准的 PDF 一個紅色標示都沒有；
拿掉任一個元素，對應的逐頁檢查必須紅（突變）。有 pypdfium2 時另驗每頁紅色像素佔比並輸出第 1～3 頁的畫面（沒有就略過那一段，文字／繪製檢查照跑）。"""
import io
import os
import re

import pytest

from helpers import doc_template as dt

DOC_NO = "MQ-202610-002"
RED_RE = re.compile(rb"0\.77\d* 0\.15\d* 0\.15\d* (?:rg|RG)")          # #C62828 ＝ (198,40,40)


@pytest.fixture()
def company(client):
    from helpers.settings import _set_setting
    _set_setting("company_profile", {"companyName": "測試股份有限公司", "companyNameEn": "Test Co.", "taxId": "12345678",
                                     "phone": "02-1234-5678", "email": "a@b.c", "locations": []})


def _long_quote():
    items = [{"id": i, "type": "item", "description": "設備 %d 規格說明文字" % i, "qty": 1, "unitPrice": 1000 * i, "amount": 1000 * i}
             for i in range(1, 61)]
    return {"quoteNo": DOC_NO, "customerName": "測試客戶", "projectName": "測試案", "items": items}


def _pdf(html):
    import pdf_gen
    return pdf_gen.html_to_pdf_bytes(html)


def _pages(pdf):
    from pypdf import PdfReader
    out = []
    for pg in PdfReader(io.BytesIO(pdf)).pages:
        text = pg.extract_text() or ""
        out.append({"text": text, "reds": len(RED_RE.findall(pg.get_contents().get_data()))})
    return out


def _marks_ok(page):
    """一頁上的標示是否齊全：頁首紅條字、頁尾單號、浮水印／頁尾／頁首的「未核可」至少 3 處、有紅色繪製。"""
    t = page["text"]
    return ("不可作為正式文件" in t and DOC_NO in t and t.count("未核可") >= 3 and page["reds"] >= 2)


def test_every_printed_page_of_an_unapproved_quotation_is_marked(company):
    import pdf_gen
    html = pdf_gen.build_quote_preview_html(_long_quote(), "待審核", "洽談中")
    pages = _pages(_pdf(html))
    assert len(pages) >= 3, "測試資料要夠長（≥3 頁）才驗得到「第 2 頁以後」：只有 %d 頁" % len(pages)
    bad = [i + 1 for i, p in enumerate(pages) if not _marks_ok(p)]
    assert not bad, "這些頁的未核可標示不齊全：%s" % bad
    for i, p in enumerate(pages):
        assert "第 %d 頁" % (i + 1) in re.sub(r"\s+", " ", p["text"]), "第 %d 頁的頁尾頁碼不對" % (i + 1)


def test_approved_quotation_has_no_marks_at_all(company):
    import pdf_gen
    html = pdf_gen.build_quote_preview_html(_long_quote(), "已送出", "洽談中")
    assert "data-unapproved" not in html and "uw-wm" not in html
    pages = _pages(_pdf(html))
    assert len(pages) >= 3
    for p in pages:
        assert "未核可" not in p["text"] and p["reds"] == 0


@pytest.mark.parametrize("mutation,needle", [
    ("remove_watermark", "未核可"),          # 拿掉 fixed 浮水印 ⇒ 每頁「未核可」少一處
    ("remove_margin_boxes", "不可作為正式文件"),   # 拿掉 @page 邊界框 ⇒ 頁首／頁尾消失
])
def test_mutations_make_the_per_page_check_red(company, mutation, needle):
    """反向控制：檢查本身有辨識力——拿掉機制的任一塊，逐頁檢查就要紅。"""
    import pdf_gen
    html = pdf_gen.build_quote_preview_html(_long_quote(), "待審核", "洽談中")
    if mutation == "remove_watermark":
        mutated = re.sub(r'<div class="uw-wm" data-unapproved-wm="1">.*?</div>', "", html, flags=re.S)
    else:
        mutated = re.sub(r"@page\{margin-top:12mm.*?\}\}\n", "", html, flags=re.S)
    assert mutated != html, "突變沒有生效 ⇒ 這一題沒有驗到東西"
    pages = _pages(_pdf(mutated))
    assert any(not _marks_ok(p) for p in pages), "拿掉 %s 之後逐頁檢查還是綠的 ⇒ 檢查沒有辨識力" % mutation


def test_pixel_coverage_and_page_screenshots(company):
    pdfium = pytest.importorskip("pypdfium2")
    import pdf_gen
    import tempfile
    html = pdf_gen.build_quote_preview_html(_long_quote(), "待審核", "洽談中")
    doc = pdfium.PdfDocument(_pdf(html))
    assert len(doc) >= 3
    outdir = os.path.join(tempfile.gettempdir(), "w1-shots-wm")
    os.makedirs(outdir, exist_ok=True)
    for i in range(len(doc)):
        img = doc[i].render(scale=1.0).to_pil().convert("RGB")
        px = img.getdata()
        red = sum(1 for r, g, b in px if r > 170 and g < 120 and b < 120 and r - g > 60)
        assert red / float(len(px)) > 0.012, "第 %d 頁的紅色像素只有 %.2f%%（太淡）" % (i + 1, 100.0 * red / len(px))
        if i < 3:
            img.save(os.path.join(outdir, "quotation-unapproved-page%d.png" % (i + 1)))


def test_every_document_type_gets_the_shared_overlay(company):
    """其他單據也走同一個元件（不是各自一套灰色浮水印）：HTML 含 fixed 浮水印、@page 邊界框、舊浮水印隱藏規則。"""
    import pdf_gen
    from modules.case import completion_pdf as cp
    from modules.accounting import voucher_pdf as vp
    samples = {
        "shipping": pdf_gen._build_shipping_html({"noteNo": "SN-1", "status": "待審核", "items": []}),
        "contractor": pdf_gen._build_contractor_voucher_html({"voucherNo": "CV-1", "status": "待審核"}),
        "payment": pdf_gen._build_payment_request_html({"requestNo": "PR-1", "status": "待審核"}),
        "completion": cp._build_completion_html({"noteNo": "CN-1", "status": "待審核"}),
        "invoice": pdf_gen._build_invoice_voucher_html({"voucherNo": "IV-1", "status": "待審核", "scope": "amount", "amount": 1, "approval": {},
                                                        "createdBy": "x", "createdAt": ""}),
        "voucher": vp.watermark_html({"status": "待審核", "voucher_no": "JV-1"}),
    }
    for name, html in samples.items():
        assert 'data-unapproved-wm="1"' in html, name
        assert "@top-center" in html and ".wm,.wm-overlay{display:none!important}" in html, name
    assert "SN-1" in samples["shipping"] and "CV-1" in samples["contractor"] and "PR-1" in samples["payment"]
    approved = pdf_gen._build_shipping_html({"noteNo": "SN-1", "status": "已核准", "items": []})
    assert "uw-wm" not in approved and "data-unapproved" not in approved


def test_overlay_constants_meet_the_user_spec():
    css = dt.unapproved_overlay(DOC_NO)
    assert dt.UNAPPROVED_RED == "#C62828"
    m = re.search(r"font:900 (\d+)px", css)
    assert m and int(m.group(1)) >= 96                                     # 字級 ≥96px、粗體
    assert re.search(r"opacity:\.(1[89]|2[0-2]?)", css)                    # 不透明度 ≈0.18～0.22
    assert "position:fixed" in css
    assert dt.UNAPPROVED_HEADER_TEXT == "未核可預覽稿 – 不可作為正式文件"
