# -*- coding: utf-8 -*-
"""需要應收應付（M05）的題：刪掉 modules/arap 時隨模組消失（PLAYBOOK §B-11）。

（2026-09-26 自 tests/test_tax_by_law_2026_09_24.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
營業稅依法規：稅別只有應稅 5%／零稅率／免稅，稅額＝round(銷售額 × 5%)，報價與發票／稅務輸出同一算法。

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
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
from datetime import datetime

import pytest
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


# ── 單一算法 ─────────────────────────────────────────────────────────────────


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


def test_exempt_quote_exports_zero_tax(client):
    """修正前：稅務匯出一律用 5% 從含稅倒推 ⇒ 免稅報價也被拆出稅額。"""
    _quote("MQ-EX", 10000, 10000, {"taxRate": 0}, [_paid(10000)])
    [r] = _invoice_rows("MQ-EX")
    assert (r["amountPretax"], r["taxAmount"], r["amountTotal"]) == (10000, 0, 10000)
    assert r["taxType"] == "exempt"


def test_zero_rated_quote_exports_zero_tax_and_is_labelled_zero(client):
    _quote("MQ-ZR", 10000, 10000, {"taxRate": 0, "taxType": "zero"}, [_paid(10000)])
    [r] = _invoice_rows("MQ-ZR")
    assert (r["taxAmount"], r["taxType"]) == (0, "zero")


def test_taxable_period_uses_sales_times_five_percent(client):
    """分期：該期銷售額＝round(報價未稅 × 期別比例)，稅額＝round(銷售額 × 5%)。"""
    _quote("MQ-TX", 10000, 10500, {"taxRate": 5}, [_paid(3150), _paid(7350, "AB00000002")])
    rows = _invoice_rows("MQ-TX")
    assert [(r["amountPretax"], r["taxAmount"], r["amountTotal"]) for r in rows] == [
        (3000, 150, 3150), (7000, 350, 7350)]


# ── 已開發票：以發票記載的未稅／稅額為準（使用者選 (a)：收款登錄發票時加填）─────

def test_recorded_invoice_amounts_are_the_source_of_truth(client):
    item = _paid(10500)
    item.update({"invoicePretax": 10001, "invoiceTax": 499})
    _quote("MQ-IV", 10000, 10500, {"taxRate": 5}, [item])
    [r] = _invoice_rows("MQ-IV")
    assert (r["amountPretax"], r["taxAmount"], r["amountTotal"]) == (10001, 499, 10500)


def test_recorded_invoice_amounts_win_even_on_a_legacy_rate_quote(client):
    item = _paid(10300)
    item.update({"invoicePretax": 9810, "invoiceTax": 490})
    _quote("MQ-IVL", 10000, 10300, {"taxRate": 3}, [item])
    [r] = _invoice_rows("MQ-IVL")
    assert (r["amountPretax"], r["taxAmount"]) == (9810, 490)
    assert r["taxNote"] == ""                               # 以發票為準 ⇒ 不再需要會計確認


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


def test_new_invoice_request_taxes_the_sales_amount_at_five_percent(client, make_user):
    """依品項：未稅 9,810 ⇒ 稅額 round_half_up(490.5)＝491、含稅 10,301。
    修正前用比例換算＋Python 內建 round（銀行家捨入）⇒ 10,300.5 捨成 10,300、稅額 490。"""
    h = _hdr(client, make_user)
    _items_quote("MQ-V1", {"taxRate": 5})
    v = _new_voucher(client, h, {"quote_no": "MQ-V1", "scope": "items",
                                 "items": [{"itemId": 1, "qty": 1, "amount": 9810}]})
    assert (v["pretaxAmount"], v["taxAmount"], v["amount"]) == (9810, 491, 10301)


def test_new_invoice_request_on_an_exempt_quote_has_no_tax(client, make_user):
    h = _hdr(client, make_user)
    _quote("MQ-V2", 20000, 20000, {"taxRate": 0}, [])
    # 📌 2026-09-25（R2）：免稅報價沒有依據 ⇒ 開票申請要補填（營業稅法 §8）
    v = _new_voucher(client, h, {"quote_no": "MQ-V2", "scope": "amount", "amount": 5000,
                                 "taxBasis": {"code": "8-3"}})
    assert (v["pretaxAmount"], v["taxAmount"], v["amount"]) == (5000, 0, 5000)


def test_new_invoice_request_on_a_legacy_rate_quote_keeps_its_numbers_and_is_flagged(client, make_user):
    h = _hdr(client, make_user)
    _quote("MQ-V3", 10000, 10300, {"taxRate": 3}, [])
    v = _new_voucher(client, h, {"quote_no": "MQ-V3", "scope": "amount", "amount": 10300})
    assert (v["pretaxAmount"], v["taxAmount"], v["amount"]) == (10000, 300, 10300)
    assert v["taxType"] == "legacy" and "非法定稅率，請會計確認" in v["taxNote"]


# ── 報價存檔：只能選法定稅別；舊 1～4% 單再編輯要改選 ─────────────────────────

def _quote_body(no=None, **data):
    d = {"customerName": "客戶", "projectName": "專案", "quoteDate": "2026-09-24", "validDays": 30,
         "items": [], "tot": {"total": 0, "pretax": 0}}
    d.update(data)
    b = {"status": "草稿", "data": d}
    if no:
        b["quote_no"] = no
    return b


# ── 需審核原因與 PDF 標籤：依稅別描述 ──────────────────────────────────────────
