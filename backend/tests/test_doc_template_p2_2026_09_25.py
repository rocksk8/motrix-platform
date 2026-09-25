# -*- coding: utf-8 -*-
"""P2 輸出引擎版型化（CUSTOMIZATION-SPEC §3.4）：開票申請憑據改為「版型定義＋單據視圖」。

① 逐位元組相同：新版輸出與凍結的舊 builder（tests/_frozen/legacy_invoice_voucher_html.py）在各種情境下完全相同。
② 反向控制：改版型 ⇒ 輸出隨之改變、其他部分不變；未知積木／主題 ⇒ 明確錯誤；驗證器列出引用不到的欄位。
"""
import copy
import json

import pytest

from tests._frozen.legacy_invoice_voucher_html import legacy_build_invoice_voucher_html as legacy


@pytest.fixture()
def company(client):
    from helpers.settings import _set_setting
    _set_setting("company_profile", {"companyName": "測試股份有限公司", "companyNameEn": "Test Co.",
                                     "taxId": "12345678", "phone": "02-1234-5678", "email": "a@b.c",
                                     "locations": [{"id": "L2", "company_name": "分公司 <&>", "phone": "07-1"}]})


_APPROVAL = {"requestedByDisplay": "王小明", "requestedAt": "2026-09-20T10:00:00",
             "steps": [{"label": "主管", "status": "approved", "actorDisplay": "李主管", "at": "2026-09-21T09:00:00"}]}

CASES = {
    "items_preview": {"voucherNo": "IV-202609-001", "status": "待簽核", "scope": "items", "quoteNo": "Q-1",
                      "createdAt": "2026-09-19T08:00:00", "customerName": "客戶 <A&B>", "customerTaxId": "87654321",
                      "projectName": "案件\n第二行", "amount": 10500, "pretaxAmount": 10000, "taxAmount": 500,
                      "selectedItems": [{"description": "交換器 <24 埠>", "brand": "Cisco", "qty": 2, "unit": "台",
                                         "unitPrice": 5000.4, "amount": 10000},
                                        {"description": "線材", "brand": "", "qty": None, "unit": None,
                                         "unitPrice": "壞值", "amount": 0}],
                      "approval": _APPROVAL},
    "amount_final_with_quote_items": {"voucherNo": "IV-2", "status": "已核准", "scope": "amount", "amount": 21000,
                                      "pretaxAmount": 20000, "taxAmount": 1000,
                                      "quoteItems": [{"description": "施工", "brand": "自有", "qty": "1", "unit": "式",
                                                      "unitPrice": 20000, "amount": 20000}],
                                      "approval": {}, "createdBy": "建單人", "createdAt": "2026-09-18"},
    "amount_final_no_quote_items": {"voucherNo": "IV-3", "status": "已核准", "scope": None, "amount": None,
                                    "approval": None},
    "empty": {},
    "status_none_location": {"voucherNo": "IV-4", "status": None, "locationId": "L2", "scope": "amount",
                             "amount": 1.5, "approval": {"requestedByDisplay": "", "requestedAt": ""},
                             "createdBy": "某人", "createdAt": ""},
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_byte_identical_to_the_frozen_builder(company, name):
    import pdf_gen
    v = CASES[name]
    assert pdf_gen._build_invoice_voucher_html(copy.deepcopy(v)) == legacy(copy.deepcopy(v))


def _tpl():
    from helpers import doc_template as dt
    return dt.load_default("invoice_voucher")


def test_changing_a_label_changes_only_that_label(company):
    import pdf_gen
    v = CASES["items_preview"]
    t = _tpl()
    t["blocks"][5]["boxes"][0]["rows"][0]["label"] = "買受人"
    a = pdf_gen._build_invoice_voucher_html(copy.deepcopy(v))
    b = pdf_gen._build_invoice_voucher_html(copy.deepcopy(v), template=t)
    assert "買受人" in b and "買受人" not in a
    assert b.replace("買受人", "客戶名稱") == a


def test_reordering_and_removing_blocks(company):
    import pdf_gen
    v = CASES["amount_final_with_quote_items"]
    base = pdf_gen._build_invoice_voucher_html(copy.deepcopy(v))
    t = _tpl()
    types = [b["type"] for b in t["blocks"]]
    t["blocks"] = [b for b in t["blocks"] if b["type"] != "totals"]
    no_totals = pdf_gen._build_invoice_voucher_html(copy.deepcopy(v), template=t)
    assert "申請開票總額（含稅）" in base and "申請開票總額（含稅）" not in no_totals
    t2 = _tpl()
    i, j = types.index("boxes"), types.index("meta")
    t2["blocks"][i], t2["blocks"][j] = t2["blocks"][j], t2["blocks"][i]
    swapped = pdf_gen._build_invoice_voucher_html(copy.deepcopy(v), template=t2)
    assert swapped != base and swapped.index("一、客戶資訊") < swapped.index("憑據單號：")


def test_unknown_block_and_theme_fail_loudly(company):
    import pdf_gen
    from helpers import doc_template as dt
    t = _tpl()
    t["blocks"].insert(2, {"type": "run_python", "code": "import os"})
    with pytest.raises(dt.TemplateError, match="第 3 塊：未知積木 'run_python'"):
        pdf_gen._build_invoice_voucher_html({}, template=t)
    t = _tpl()
    t["theme"] = "nope"
    with pytest.raises(dt.TemplateError, match="未知主題"):
        pdf_gen._build_invoice_voucher_html({}, template=t)


def test_template_values_are_escaped_not_executed(company):
    """版型裡的文字（例如使用者改的標籤）與欄位值一律跳脫：不能注入 HTML／腳本。"""
    import pdf_gen
    t = _tpl()
    t["blocks"][2]["title"] = "<script>alert(1)</script>"
    html = pdf_gen._build_invoice_voucher_html({"status": "已核准"}, template=t)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_validator_lists_unknown_blocks_and_unreachable_fields():
    import pdf_gen
    from helpers import doc_template as dt
    view = pdf_gen._invoice_voucher_view(CASES["items_preview"])
    assert dt.validate(_tpl(), view) == []                               # 預設版型對真實視圖：全部引用得到
    t = _tpl()
    t["blocks"][3]["fields"].append({"label": "x", "path": "noSuchField"})
    t["blocks"].append({"type": "nope"})
    probs = dt.validate(t, view)
    assert any("noSuchField" in p for p in probs) and any("未知積木 'nope'" in p for p in probs)


def test_default_template_is_plain_data():
    """預設版型是資料：可以 JSON 來回、不含任何可執行內容。"""
    from helpers import doc_template as dt
    t = _tpl()
    assert json.loads(json.dumps(t, ensure_ascii=False)) == t
    assert {b["type"] for b in t["blocks"]} <= set(dt.BLOCKS)


# ── R2 × P2：零稅率／免稅的依據要印出來（主持 2026-09-26 併入 P2）─────────────────

@pytest.mark.parametrize("tax_type,code,note,expect", [
    ("zero", "7-1", "出口報單 AA123", ["零稅率", "營業稅法 §7 ① 外銷貨物", "出口報單 AA123"]),
    ("exempt", "8", "第 15 款 醫療勞務", ["免稅", "營業稅法 §8 第一項", "第 15 款 醫療勞務"]),
])
def test_zero_and_exempt_vouchers_print_their_basis(company, tax_type, code, note, expect):
    import pdf_gen
    from helpers.legal_params import tax_basis_label
    v = dict(copy.deepcopy(CASES["items_preview"]), taxType=tax_type, taxBasis={"code": code, "note": note},
             pretaxAmount=10000, taxAmount=0, amount=10000)
    html = pdf_gen._build_invoice_voucher_html(v)
    assert "稅別依據" in html
    for text in expect + [tax_basis_label({"code": code, "note": note})]:
        assert text in html, text


def test_taxable_voucher_has_no_basis_box(company):
    """應稅（沒有 taxType 或 standard）⇒ 不印依據框；與凍結的舊 builder 逐位元組相同（上面那組參數化題）照樣成立。"""
    import pdf_gen
    for t in (None, "standard"):
        v = dict(copy.deepcopy(CASES["items_preview"]), taxType=t)
        assert "稅別依據" not in pdf_gen._build_invoice_voucher_html(v)


def test_old_snapshot_without_basis_falls_back_to_the_tax_note(company):
    """R2 之前建立的快照沒有 taxBasis，但有 taxNote ⇒ 依據欄印 taxNote（不留白、不猜）。"""
    import pdf_gen
    v = dict(copy.deepcopy(CASES["items_preview"]), taxType="zero", taxNote="零稅率依據：舊單補述")
    assert "零稅率依據：舊單補述" in pdf_gen._build_invoice_voucher_html(v)
