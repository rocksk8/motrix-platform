# -*- coding: utf-8 -*-
"""使用者 2026-09-30（第 27 班）：尚未核可的單據，PDF／預覽一律顯示紅色「未核可・僅供預覽」，已核准的 PDF 不變。

- 每一種會簽核又出 PDF 的單據（報價單、請款單、開票申請、承攬商匯款申請、出貨單、完工單、會計傳票、自訂模組單據）：
  未核准 ⇒ HTML 含 `data-unapproved="1"`＋固定字樣＋紅色行內樣式（列印／下載的 PDF 同一份 HTML）；已核准 ⇒ 沒有。
- 守門（雙向）：每個單據 builder 的原始碼必須呼叫共用元件；新增的 builder 沒登記 ⇒ 紅（登記表 BUILDERS）。
- 版型作者拿掉 banner 積木也擋不掉（核可狀態由程式決定）。
"""
import copy
import os
import re

import pytest

from helpers import doc_template as dt

RED = "#DC2626"


@pytest.fixture()
def company(client):
    from helpers.settings import _set_setting
    _set_setting("company_profile", {"companyName": "測試股份有限公司", "companyNameEn": "Test Co.", "taxId": "12345678",
                                     "phone": "02-1234-5678", "email": "a@b.c", "locations": []})


def _marked(html):
    return 'data-unapproved="1"' in html and dt.UNAPPROVED_TEXT in html and RED in html


def test_component_shape():
    h = dt.unapproved_banner("待審核", "細節 <b>")
    assert _marked(h) and "待審核" in h and "&lt;b&gt;" in h and "print-color-adjust:exact" in h
    assert dt.inject_unapproved(h, "x") == h                                    # 冪等
    out = dt.inject_unapproved('<html><body>\n<div id="root">\n<p>x</p></div></body></html>', "草稿")
    assert out.index("data-unapproved") < out.index("<p>x</p>") and out.count('data-unapproved="1"') == 1


STATUSES = [("草稿", True), ("待審核", True), ("簽核中", True), ("已核准", False)]


@pytest.mark.parametrize("status,red", STATUSES)
def test_invoice_voucher(company, status, red):
    import pdf_gen
    v = {"voucherNo": "IV-1", "status": status, "scope": "amount", "amount": 100, "approval": {"requestedByDisplay": "", "requestedAt": ""},
         "createdBy": "某人", "createdAt": ""}
    assert _marked(pdf_gen._build_invoice_voucher_html(v)) is red


def test_invoice_voucher_template_author_cannot_drop_it(company):
    import pdf_gen
    t = dt.load_default("invoice_voucher")
    t["blocks"] = [b for b in t["blocks"] if b.get("type") not in ("banner", "watermark")]
    v = {"voucherNo": "IV-1", "status": "待審核", "scope": "amount", "amount": 1, "approval": {}, "createdBy": "x", "createdAt": ""}
    assert _marked(pdf_gen._build_invoice_voucher_html(v, template=t))


@pytest.mark.parametrize("status,red", STATUSES)
def test_payment_request(company, status, red):
    import pdf_gen
    assert _marked(pdf_gen._build_payment_request_html({"requestNo": "PR-1", "status": status})) is red


@pytest.mark.parametrize("status,red", STATUSES)
def test_contractor_voucher(company, status, red):
    import pdf_gen
    assert _marked(pdf_gen._build_contractor_voucher_html({"voucherNo": "CV-1", "status": status})) is red


@pytest.mark.parametrize("status,red", STATUSES)
def test_shipping_note(company, status, red):
    import pdf_gen
    assert _marked(pdf_gen._build_shipping_html({"noteNo": "SN-1", "status": status, "items": []})) is red


@pytest.mark.parametrize("status,red", STATUSES)
def test_completion_note(company, status, red):
    from modules.case import completion_pdf as cp
    assert _marked(cp._build_completion_html({"noteNo": "CN-1", "status": status})) is red


@pytest.mark.parametrize("status,red", [("草稿", True), ("待審核", True), ("已拒絕", True), ("已送出", False)])
def test_quotation(company, status, red):
    import pdf_gen
    q = {"quoteNo": "MQ-1"}
    assert _marked(pdf_gen.build_quote_preview_html(q, status, "")) is red


def test_quotation_unsettled_but_sent_is_not_unapproved(company):
    import pdf_gen
    assert not _marked(pdf_gen.build_quote_preview_html({"quoteNo": "MQ-1"}, "已送出", "未成案"))


def test_accounting_voucher_watermark_carries_the_red_banner():
    from modules.accounting import voucher_pdf as vp
    base = {"status": "待審核", "voucher_no": "JV-1"}
    assert _marked(vp.watermark_html(base))
    assert not _marked(vp.watermark_html(dict(base, voided_at="2026-09-30T00:00:00")))                         # 作廢優先：印「已作廢」不是「未核可」


def test_custom_record_unapproved_follows_the_workflow():
    from helpers import custom_modules as CM
    body = {"workflow": {"initial": "draft",
                         "states": [{"key": "draft"}, {"key": "review", "approval": {"on_approved": "approved", "on_rejected": "draft"}},
                                    {"key": "approved"}, {"key": "done", "final": True}],
                         "transitions": [{"key": "a", "from": "draft", "to": "review"}, {"key": "b", "from": "approved", "to": "done"}]}}
    assert [CM._is_unapproved(body, k) for k in ("draft", "review", "approved", "done")] == [True, True, False, False]
    assert CM._is_unapproved({"workflow": {"states": [{"key": "draft"}, {"key": "done"}], "transitions": []}}, "draft") is False   # 沒有簽核的模組不標


def test_custom_record_output_injects_even_with_a_template_without_banner():
    from helpers import custom_modules as CM
    body = {"name": "T", "fields": [], "output": {}}
    view = {"recordNo": "R-1", "status": "review", "statusLabel": "簽核中", "createdBy": "x", "createdAt": "", "approval": {},
            "fields": {}, "unapproved": True}
    import pdf_gen
    from helpers.company_setup import CompanySetupRequired
    try:
        html = CM.render_view(body, view)
    except CompanySetupRequired:
        pytest.skip("需要公司設定（由 e2e 覆蓋）")
    assert _marked(html)
    assert not _marked(CM.render_view(body, dict(view, unapproved=False)))


#: 登記表：每一個「會簽核又出 PDF」的 builder ⇒ 原始碼裡必須用到共用元件。新增的 builder 要加一列（或在 EXEMPT 說明為何不需要）。
BUILDERS = {
    "pdf_gen.py": ["_build_shipping_html", "_build_contractor_voucher_html", "_build_payment_request_html",
                   "_build_invoice_voucher_html", "_build_quote_html"],
    "modules/case/completion_pdf.py": ["_build_completion_html"],
    "modules/accounting/voucher_pdf.py": ["watermark_html"],
    "helpers/custom_modules.py": ["render_view"],
}
#: 沒有簽核流程（不是核可文件）或舊流程已退役，不加警示——寫在這裡是「有人決定過」，不是漏掉
EXEMPT = {
    "pdf_gen.py::_build_payslip_html": "勞報單沒有簽核流程（草稿→已匯出→已簽回→已付款；作廢另有標記）",
    "pdf_gen.py::_build_case_closing_html": "結案報表不是簽核文件（以 deal_tag=已結案、精算完結為前提）",
    "pdf_gen.py::_build_project_execution_report_html": "執行報告不是簽核文件",
    "modules/payroll/bonus_pdf.py::_award_html": "舊獎金分潤單：寫入端點全部 410、前端沒有呼叫者；新流程沒有 PDF",
}
_USES = ("_unapproved_banner(", "unapproved_banner(", "_inject_unapproved(", "inject_unapproved(", "unapproved_status")


def _src_of(rel, fn):
    import ast
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", rel)
    src = open(path, encoding="utf-8").read()
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef) and n.name == fn:
            return ast.get_source_segment(src, n)
    return None


@pytest.mark.parametrize("rel,fn", [(r, f) for r, fs in BUILDERS.items() for f in fs])
def test_every_approvable_builder_uses_the_shared_component(rel, fn):
    seg = _src_of(rel, fn)
    assert seg is not None, "%s 找不到 %s —— 登記表過期或 builder 被改名" % (rel, fn)
    assert any(u in seg for u in _USES), "%s::%s 沒有用未核可警示元件（helpers.doc_template.unapproved_banner／inject_unapproved）" % (rel, fn)


def test_registry_is_not_stale_and_exempt_functions_exist():
    for key in EXEMPT:
        rel, fn = key.split("::")
        assert _src_of(rel, fn) is not None, "豁免清單裡的 %s 不存在 —— 清單過期" % key
        assert not any(u in _src_of(rel, fn) for u in _USES), "%s 已經用了警示元件，請從豁免清單移除" % key
