# -*- coding: utf-8 -*-
"""W3 #2 再查（同形狀的 sink）：引號跳脫的單一來源 `helpers.doc_template.esc_quotes`／`attr_esc`；
各 builder 的區域 `esc()`、單據抬頭／頁尾（公司名稱、英文名、統編、電話、email）、圖片 `src`（存摺、身分證）都要擋 `"><img …onerror=…>` 這一類。
另：JSON 的 Infinity／NaN 進 colspan／count ⇒ `TemplateError`（不是 OverflowError 500）。

🔑 逐位元組相同的舊測試（tests/_frozen/legacy_*）只在「資料含引號」時才會與新輸出不同——本檔的 payload 才含引號；既有案例資料沒有引號，所以不必調整。"""
import json

import pytest

from helpers import doc_template as dt

PAYLOAD = '"><img src=x onerror=alert(1)>\'"'


def _clean(html):
    """沒有任何一個 sink 讓 payload 變成真的標籤／屬性。"""
    assert "<img src=x" not in html, "payload 成了真的 <img> 標籤"
    assert 'onerror=alert(1)>' not in html.replace("&quot;", '"') or "&lt;img" in html


@pytest.fixture()
def company(client):
    from helpers.settings import _set_setting
    _set_setting("company_profile", {"companyName": "測試股份有限公司", "companyNameEn": "Test Co.", "taxId": "12345678",
                                     "phone": "02-1234-5678", "email": "a@b.c", "locations": [],
                                     "bank_name": "測試銀行", "bank_account_name": "測試股份有限公司", "bank_account_number": "0001234567"})


def test_single_source_helpers():
    assert dt.esc_quotes('a"b\'c') == "a&quot;b&#x27;c"
    assert dt.attr_esc(PAYLOAD) == "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;&#x27;&quot;"
    assert dt.attr_esc(None) == "" and dt.attr_esc(5) == "5"
    assert dt._esc("a\n\"b") == "a<br>&quot;b"


def test_identity_head_and_foot_escape_every_field(company):
    import pdf_gen
    ident = {k: PAYLOAD for k in ("company_name", "company_name_en", "tax_id", "phone", "email")}
    _clean(pdf_gen._identity_head(ident))
    _clean(pdf_gen._identity_foot(ident))
    _clean(pdf_gen._identity_foot_short(ident))


@pytest.mark.parametrize("build,fields", [
    ("_build_shipping_html", {"noteNo": PAYLOAD, "status": "草稿", "items": [], "customerName": PAYLOAD, "projectName": PAYLOAD,
                              "recipient": PAYLOAD, "deliveryAddress": PAYLOAD, "notes": PAYLOAD}),
    ("_build_contractor_voucher_html", {"voucherNo": PAYLOAD, "status": "草稿", "vendorName": PAYLOAD, "projectName": PAYLOAD,
                                        "bankPassbookImage": PAYLOAD, "bankAccountName": PAYLOAD}),
    ("_build_payment_request_html", {"requestNo": PAYLOAD, "status": "草稿", "customerName": PAYLOAD, "projectName": PAYLOAD}),
])
def test_builders_escape_quotes_in_every_value(company, build, fields):
    import pdf_gen
    _clean(getattr(pdf_gen, build)(dict(fields)))


def test_completion_builder(company):
    from modules.case import completion_pdf as cp
    _clean(cp._build_completion_html({"noteNo": PAYLOAD, "status": "草稿", "customerName": PAYLOAD, "projectName": PAYLOAD,
                                      "siteAddress": PAYLOAD, "workSummary": PAYLOAD}))


def test_payslip_image_sources_are_attribute_escaped():
    import pdf_gen
    html = pdf_gen._payslip_passbook_html({"_bank_passbook": 'x" onerror="alert(1)'})
    assert '" onerror="' not in html and "&quot; onerror=&quot;" in html
    assert pdf_gen._payslip_esc(PAYLOAD).count('"') == 0


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), json.loads("Infinity"), json.loads("-Infinity"), json.loads("NaN")])
def test_non_finite_numbers_are_template_errors(bad):
    with pytest.raises(dt.TemplateError):
        dt.render_blocks([{"type": "watermark", "text": "T", "small": "s", "count": bad}], {}, {})
    with pytest.raises(dt.TemplateError):
        dt.render_blocks([{"type": "kv_table", "rows": [{"cells": [{"text": "v", "colspan": bad}]}]}], {}, {})
    tpl = {"theme": "voucher_standard", "blocks": [{"type": "watermark", "text": "T", "small": "s", "count": bad}]}
    assert any("count" in p["message"] for p in dt.problems(tpl))
