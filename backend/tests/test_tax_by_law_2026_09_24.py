# -*- coding: utf-8 -*-
"""營業稅依法規：稅別只有應稅 5%／零稅率／免稅，稅額＝round(銷售額 × 5%)，報價與發票／稅務輸出同一算法。

使用者（2026-09-24）逐字：「算了會計稅率1~4%取消，直接依法規進行，用現金折讓就好」。
權威：HANDOFF「🔴 AC1 更正」。

```
營業稅法 §14 I（逐字）：「…分別按第七條或第十條規定計算其銷項稅額，
  尾數不滿通用貨幣一元者，按四捨五入計算」
§7 零稅率、§8 免稅 —— 兩者稅額都是 0，但申報上分開
```

## 舊資料（hichan-0a 代裁）
- 舊的 1～4% 報價**不改數字**；稅務匯出該筆標「非法定稅率，請會計確認」。
- 沒有 `taxType` 的舊報價：稅率 0 ⇒ 免稅（照原本的選項標籤），其餘 ⇒ 應稅；不做 migration。
- 已開發票（開票申請已核准）⇒ 以那張單記載的稅額為準。
"""
import json
from datetime import datetime

import pytest


# ── 單一算法 ─────────────────────────────────────────────────────────────────

def test_taxable_tax_is_five_percent_of_sales_rounded_half_up():
    from helpers.quotations import tax_split
    assert tax_split(9810, "taxable") == (9810, 491)      # 490.5 ⇒ 491（四捨五入，不是銀行家捨入）
    assert tax_split(10000, "taxable") == (10000, 500)
    assert tax_split(1, "taxable") == (1, 0)


@pytest.mark.parametrize("tax_type", ["zero", "exempt"])
def test_zero_rated_and_exempt_have_no_tax(tax_type):
    from helpers.quotations import tax_split
    assert tax_split(10000, tax_type) == (10000, 0)


@pytest.mark.parametrize("data,want", [
    ({}, "taxable"),
    ({"taxRate": 5}, "taxable"),
    ({"taxRate": 0}, "exempt"),                             # 舊的「0%（免稅）」
    ({"taxRate": 0, "taxType": "zero"}, "zero"),
    ({"taxRate": 5, "taxType": "taxable"}, "taxable"),
    ({"taxRate": 3}, "legacy"),                             # 已停用的 1～4%
    ({"taxRate": 0, "taxType": "bogus"}, "exempt"),         # 認不得的 taxType ⇒ 退回依稅率
], ids=["empty", "5", "0", "zero", "taxable", "legacy3", "bogus"])
def test_quote_tax_type_reading_rule(data, want):
    from helpers.quotations import quote_tax_type
    assert quote_tax_type(data) == want


# ── 稅務匯出（銷項發票清單）────────────────────────────────────────────────────

def _quote(no, pretax, total, extra, pay_items, status="已成案"):
    import db
    data = {"quoteNo": no, "caseRecord": {"payment": {"items": pay_items}}}
    data.update(extra)
    now = datetime.now().isoformat()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, "
            "customer_name) VALUES (?,?,?,?,?,?,?,?)",
            (no, status, total, pretax, json.dumps(data, ensure_ascii=False), now, now, "客戶"))
        conn.commit()
    finally:
        conn.close()


def _invoice_rows(no):
    from helpers.receivables import collect_tax_invoices as _collect_tax_invoices
    return [r for r in _collect_tax_invoices() if r["quoteNo"] == no]


def _paid(amount, inv="AB12345678"):
    return {"amount": amount, "invoiceNo": inv, "invoiceDate": "2026-09-10", "receivedAt": "2026-09-10"}


# ── 已開發票：以發票記載的未稅／稅額為準（使用者選 (a)：收款登錄發票時加填）─────


@pytest.mark.parametrize("item,ok", [
    ({}, True),
    ({"invoicePretax": 10000, "invoiceTax": 500}, True),
    ({"invoicePretax": "", "invoiceTax": ""}, True),          # 兩欄都空＝沒填
    ({"invoicePretax": 10000}, False),                       # 只填一欄 ⇒ 拒存
    ({"invoiceTax": 500}, False),
    ({"invoicePretax": 10000, "invoiceTax": -1}, False),
    ({"invoicePretax": 10000.5, "invoiceTax": 500}, False),  # 新台幣元，不可有小數
    ({"invoicePretax": 9000, "invoiceTax": 450}, True),      # 合計 ≠ 該期金額：只提示、不擋
], ids=["none", "both", "both-empty", "pretax-only", "tax-only", "negative", "decimal", "mismatch"])
def test_invoice_amounts_validation(item, ok):
    from fastapi import HTTPException
    from helpers.quotations import validate_invoice_amounts
    it = {"amount": 10500, "invoiceNo": "AB12345678"}
    it.update(item)
    if ok:
        validate_invoice_amounts(it)
    else:
        with pytest.raises(HTTPException) as e:
            validate_invoice_amounts(it)
        assert e.value.status_code == 400


# ── 存檔路徑：收款登錄與案件整包存檔都要擋「只填一欄」──────────────────────

def _hdr(client, make_user, username="root", role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _stored_item(no, idx=0):
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
    finally:
        conn.close()
    return d["caseRecord"]["payment"]["items"][idx]


def test_marking_a_payment_with_only_one_invoice_amount_is_refused(client, make_user):
    h = _hdr(client, make_user)
    _quote("MQ-MP", 10000, 10500, {"taxRate": 5}, [{"id": "p1", "amount": 10500}])
    r = client.patch("/api/quotations/MQ-MP/payment/0",
                     json={"itemId": "p1", "invoiceNo": "AB12345678", "invoicePretax": 10000}, headers=h)
    assert r.status_code == 400, r.text
    assert "invoicePretax" not in _stored_item("MQ-MP")


def test_marking_a_payment_with_both_invoice_amounts_is_stored(client, make_user):
    h = _hdr(client, make_user)
    _quote("MQ-MP2", 10000, 10500, {"taxRate": 5}, [{"id": "p1", "amount": 10500}])
    r = client.patch("/api/quotations/MQ-MP2/payment/0",
                     json={"itemId": "p1", "invoiceNo": "AB12345679", "invoicePretax": 10000,
                           "invoiceTax": 500}, headers=h)
    assert r.status_code == 200, r.text
    it = _stored_item("MQ-MP2")
    assert (it["invoicePretax"], it["invoiceTax"]) == (10000, 500)


def test_saving_the_case_record_with_only_one_invoice_amount_is_refused(client, make_user):
    h = _hdr(client, make_user)
    _quote("MQ-CR", 10000, 10500, {"taxRate": 5}, [{"id": "p1", "amount": 10500}])
    cr = {"payment": {"items": [{"id": "p1", "amount": 10500, "invoiceNo": "AB12345670",
                                 "invoiceTax": 500}]}}
    r = client.patch("/api/quotations/MQ-CR/case-record", json={"case_record": cr}, headers=h)
    assert r.status_code == 400, r.text


# ── 開票申請（只影響新建立的；已建立的快照不動）──────────────────────────────

def _items_quote(no, extra):
    items = [{"id": 1, "type": "item", "description": "設備", "qty": 1, "unitPrice": 9810, "amount": 9810},
             {"id": 2, "type": "item", "description": "施工", "qty": 1, "unitPrice": 10190, "amount": 10190}]
    extra = dict(extra, items=items)
    _quote(no, 20000, 21000, extra, [])


def _new_voucher(client, h, body):
    r = client.post("/api/invoice-vouchers", json=body, headers=h)
    assert r.status_code in (200, 201), r.text
    r = client.get("/api/invoice-vouchers/" + r.json()["voucher_no"], headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ── 報價存檔：只能選法定稅別；舊 1～4% 單再編輯要改選 ─────────────────────────

def _quote_body(no=None, **data):
    d = {"customerName": "客戶", "projectName": "專案", "quoteDate": "2026-09-24", "validDays": 30,
         "items": [], "tot": {"total": 0, "pretax": 0}}
    d.update(data)
    b = {"status": "草稿", "data": d}
    if no:
        b["quote_no"] = no
    return b


@pytest.mark.parametrize("data,ok", [
    ({"taxRate": 5, "taxType": "taxable"}, True),
    ({"taxRate": 0, "taxType": "zero"}, True),
    ({"taxRate": 0, "taxType": "exempt"}, True),
    ({"taxRate": 5}, True),                                    # 沒送 taxType：依稅率讀
    ({"taxRate": 3}, False),                                   # 已停用
    ({"taxRate": 0, "taxType": "taxable"}, False),             # 稅別與稅率不一致
    ({"taxRate": 5, "taxType": "exempt"}, False),
    ({"taxRate": 5, "taxType": "bogus"}, False),
], ids=["taxable", "zero", "exempt", "rate-only", "legacy3", "mismatch-a", "mismatch-b", "bogus"])
def test_creating_a_quote_accepts_only_legal_tax_types(client, make_user, data, ok):
    h = _hdr(client, make_user)
    r = client.post("/api/quotations", json=_quote_body(**data), headers=h)
    assert (r.status_code == 201) == ok, r.text
    if not ok:
        assert r.status_code == 400


def test_saving_an_old_legacy_rate_quote_requires_a_legal_tax_type(client, make_user):
    h = _hdr(client, make_user)
    _quote("MQ-OLD3", 10000, 10300, {"taxRate": 3, "customerName": "客戶"}, [], status="草稿")
    r = client.put("/api/quotations/MQ-OLD3", json=_quote_body("MQ-OLD3", taxRate=3), headers=h)
    assert r.status_code == 400, r.text
    assert "法定稅別" in r.json()["detail"]
    r = client.put("/api/quotations/MQ-OLD3", json=_quote_body("MQ-OLD3", taxRate=5, taxType="taxable"),
                   headers=h)
    assert r.status_code == 200, r.text


# ── 需審核原因與 PDF 標籤：依稅別描述 ──────────────────────────────────────────

@pytest.mark.parametrize("data,want", [
    ({"taxRate": 0, "taxType": "zero"}, "稅別為零稅率（非應稅 5%）"),
    ({"taxRate": 0, "taxType": "exempt"}, "稅別為免稅（非應稅 5%）"),
    ({"taxRate": 0}, "稅別為免稅（非應稅 5%）"),                     # 舊的 0%＝免稅
    ({"taxRate": 3}, "調整營業稅額為 3%（標準 5%）"),                  # 舊單：原文字不變
], ids=["zero", "exempt", "old-0", "legacy3"])
def test_approval_reason_names_the_tax_type(data, want):
    from helpers.quote_terms import compute_approval_reasons
    assert want in compute_approval_reasons(dict(data, items=[]), [], "")


def test_taxable_quote_has_no_tax_reason():
    from helpers.quote_terms import compute_approval_reasons
    rs = compute_approval_reasons({"taxRate": 5, "taxType": "taxable", "items": []}, [], "")
    assert not [r for r in rs if "稅" in r], rs


@pytest.mark.parametrize("data,label", [
    ({"taxRate": 5, "taxType": "taxable"}, "營業稅 5%"),
    ({"taxRate": 0, "taxType": "zero"}, "營業稅（零稅率）"),
    ({"taxRate": 0, "taxType": "exempt"}, "免稅"),
    ({"taxRate": 3}, "營業稅 3%"),
], ids=["taxable", "zero", "exempt", "legacy3"])
def test_quote_pdf_labels_the_tax_line_by_type(data, label):
    from pdf_gen import _build_quote_html
    q = dict(data, quoteNo="MQ-PDF", items=[], customerName="客")
    html = _build_quote_html(q, {"subtotal": 100, "pretax": 100, "tax": 0, "total": 100})
    assert ">%s<" % label in html, label
