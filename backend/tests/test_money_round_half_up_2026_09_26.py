# -*- coding: utf-8 -*-
"""金額捨入統一四捨五入（X-VAT，2026-09-26；R 稽核修正帶出：開票申請的營業稅用內建 round()）。

內建 `round()` 是銀行家捨入（.5 取偶數：round(1250.5) == 1250）；前端 `Math.round(a * b)` 在浮點乘積
落在 x.4999… 時少 1 元、負數 -1.5 取 -1。共用函式：後端 L1 `helpers.legal_params.round_half_up`
（`helpers.quotations.round_half_up` 轉呼叫它），前端 `static/legal-round.js` 的 `MotrixLegalRound.halfUp`。

每一處修改一題：挑會出現 .5 的金額，改之前會紅（註明舊值）；另有正對照（改前改後都一樣的值，
證明題目本身沒有把「正常的金額」也算錯）。守門：tests/platform/test_legal_amount_rounding_guard.py。
前端題用 node 載入頁面（或 case-management-*.js 分檔）的元件，直接呼叫方法；沒有 node ⇒ skip。
"""
import json
import pathlib
import shutil
import subprocess
from datetime import datetime

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


# ══════════════════════════════════════════════════════════════════════════════
# 共用函式
# ══════════════════════════════════════════════════════════════════════════════

def test_quotations_round_half_up_forwards_to_the_legal_params_service():
    from helpers import legal_params as lp
    from helpers.quotations import round_half_up
    assert round_half_up(1250.5) == 1251 and round_half_up(1250.4) == 1250      # 正對照＋.5
    assert round_half_up(1251, 0.05) == lp.round_half_up(1251, 0.05) == 63      # 62.55
    assert round_half_up(-2.5) == -3, "負數遠離 0（Decimal ROUND_HALF_UP）"


# ══════════════════════════════════════════════════════════════════════════════
# 報價：收款期別金額（helpers/quotations.py::payment_item_amounts）
# ══════════════════════════════════════════════════════════════════════════════

def test_payment_items_by_pct_round_half_up():
    """10,015 × 30% ＝ 3,004.5 ⇒ 3,005（舊：3,004；畫面 Math.round 一直是 3,005 ⇒ 前後端差 1 元）。"""
    from helpers.quotations import payment_item_amounts
    # 第 2 期由 pct 算（L329）；第 1 期＝總額 − 其他期（其他期也由 pct 算，L319）
    assert payment_item_amounts(10015, [{"pct": 70}, {"pct": 30}]) == [7010, 3005]
    # 正對照：沒有 .5 的比例
    assert payment_item_amounts(10000, [{"pct": 70}, {"pct": 30}]) == [7000, 3000]


def test_tax_exempt_item_converts_to_pretax_half_up():
    """沖銷免稅期別：含稅 24 × 未稅 30／含稅 32 ＝ 22.5 ⇒ 23（舊：22）。L331"""
    from helpers.quotations import payment_item_amounts
    assert payment_item_amounts(32, [{"amount": 24, "taxExempt": True}], pretax=30) == [23]
    assert payment_item_amounts(32, [{"amount": 16, "taxExempt": True}], pretax=30) == [15]    # 正對照


# ══════════════════════════════════════════════════════════════════════════════
# 開票申請（routers/invoice_vouchers.py）
# ══════════════════════════════════════════════════════════════════════════════

def _quote(no, pretax, total, data):
    import db
    now = datetime.now().isoformat()
    d = {"quoteNo": no, "caseRecord": {"payment": {"items": []}}}
    d.update(data)
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, "
            "customer_name) VALUES (?,?,?,?,?,?,?,?)",
            (no, "已成案", total, pretax, json.dumps(d, ensure_ascii=False), now, now, "客戶"))
        conn.commit()
    finally:
        conn.close()


def _hdr(client, make_user):
    u, p = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _voucher(client, h, body):
    r = client.post("/api/invoice-vouchers", json=body, headers=h)
    assert r.status_code in (200, 201), r.text
    r = client.get("/api/invoice-vouchers/" + r.json()["voucher_no"], headers=h)
    assert r.status_code == 200, r.text
    v = r.json()
    return v["pretaxAmount"], v["taxAmount"], v["amount"]


_ITEMS = [{"id": 1, "type": "item", "description": "設備", "qty": 10, "unitPrice": 1000, "amount": 10000}]


def test_invoice_by_amount_converts_to_pretax_half_up(client, make_user):
    """應稅報價 未稅 10,004／含稅 10,504（稅 500.2⇒500）：申請 1,313 ⇒ 未稅 1,313×10,004／10,504＝1,250.5
    ⇒ 1,251（舊：1,250）⇒ 稅額 round_half_up(62.55)＝63、含稅 1,314（舊：1,250／63／1,313）。L336"""
    h = _hdr(client, make_user)
    _quote("MQ-VAT-A1", 10004, 10504, {"taxRate": 5, "taxType": "taxable", "items": _ITEMS})
    assert _voucher(client, h, {"quote_no": "MQ-VAT-A1", "scope": "amount", "amount": 1313}) == (1251, 63, 1314)
    # 正對照：換算結果不是 .5
    assert _voucher(client, h, {"quote_no": "MQ-VAT-A1", "scope": "amount", "amount": 1050}) == (1000, 50, 1050)


def test_invoice_by_items_on_a_legacy_quote_grosses_up_half_up(client, make_user):
    """舊 3% 報價（未稅 10,000／含稅 10,300）依品項：未稅 150 ⇒ 含稅 154.5 ⇒ 155（舊：154）。L369"""
    h = _hdr(client, make_user)
    _quote("MQ-VAT-A2", 10000, 10300, {"taxRate": 3, "items": _ITEMS})
    assert _voucher(client, h, {"quote_no": "MQ-VAT-A2", "scope": "items",
                                "items": [{"itemId": 1, "qty": 1, "amount": 150}]}) == (150, 5, 155)
    assert _voucher(client, h, {"quote_no": "MQ-VAT-A2", "scope": "items",
                                "items": [{"itemId": 1, "qty": 1, "amount": 100}]}) == (100, 3, 103)   # 正對照


def test_invoice_snapshot_pretax_and_tax_round_half_up(client, make_user):
    """舊 3% 報價依品項 未稅 82.5：含稅 round_half_up(84.975)＝85；快照未稅 82.5⇒83（舊：82）、
    稅額 85−82.5＝2.5⇒3（舊：2）。L406、L407"""
    h = _hdr(client, make_user)
    _quote("MQ-VAT-A3", 10000, 10300, {"taxRate": 3, "items": _ITEMS})
    assert _voucher(client, h, {"quote_no": "MQ-VAT-A3", "scope": "items",
                                "items": [{"itemId": 1, "qty": 1, "amount": 82.5}]}) == (83, 3, 85)


# ══════════════════════════════════════════════════════════════════════════════
# 請款單（routers/payment_requests.py）
# ══════════════════════════════════════════════════════════════════════════════

def _calc(scope, quote_total, quote_pretax, ratio=None, amount=None, items=None, data_items=None):
    from routers.payment_requests import _calc_scope_amount, RequestItemIn
    data = {"items": data_items or _ITEMS}
    remaining = {"items": [{"itemId": it["id"], "remainingQty": it["qty"]} for it in data["items"]]}
    items_in = [RequestItemIn(**x) for x in items] if items else None
    return _calc_scope_amount(data, remaining, quote_total, quote_pretax, scope, ratio, amount, items_in)[:4]


def test_payment_request_by_ratio_rounds_half_up():
    """含稅 10,015 × 30% ＝ 3,004.5 ⇒ 3,005（舊：3,004）。L258"""
    req, _pre, _tax, pct = _calc("amount", 10015, 9538, ratio=30)
    assert (req, pct) == (3005, 30)
    assert _calc("amount", 10000, 9524, ratio=30)[0] == 3000                         # 正對照


def test_payment_request_ratio_pct_rounds_half_up_to_two_decimals():
    """10 ／ 8,000 ＝ 0.125% ⇒ 0.13（舊：round(0.125, 2)＝0.12）。L261（建立）與 L297（依品項）"""
    assert _calc("amount", 8000, 7619, amount=10)[3] == 0.13
    assert _calc("items", 8000, 8000, items=[{"itemId": 1, "qty": 1, "amount": 10}])[3] == 0.13
    assert _calc("amount", 8000, 7619, amount=12)[3] == 0.15                          # 正對照（0.15%）


def test_payment_request_by_amount_converts_to_pretax_half_up():
    """含稅 1,313 × 10,004／10,504 ＝ 1,250.5 ⇒ 1,251（舊：1,250）。L266"""
    req, pre, tax, _pct = _calc("amount", 10504, 10004, amount=1313)
    assert (req, pre, tax) == (1313, 1251, 62)
    assert _calc("amount", 10504, 10004, amount=10504)[:3] == (10504, 10004, 500)     # 正對照


def test_payment_request_by_items_grosses_up_half_up():
    """未稅 10 × 21,000／20,000 ＝ 10.5 ⇒ 11（舊：10）。L296"""
    req, pre, tax, _pct = _calc("items", 21000, 20000, items=[{"itemId": 1, "qty": 1, "amount": 10}])
    assert (req, pre, tax) == (11, 10, 1)
    assert _calc("items", 21000, 20000, items=[{"itemId": 1, "qty": 1, "amount": 20}])[:3] == (21, 20, 1)


def _pr_body(scope, **kw):
    return dict({"scope": scope, "stage": "deposit"}, **kw)


def test_payment_request_snapshot_rounds_half_up_on_create_and_update(client, make_user):
    """快照的未稅／稅額（L428／L429 建立、L531／L532 更新）。
    - 依金額 34.5（含稅 3,200／未稅 3,000）：未稅 round_half_up(32.34375)＝32、稅額 2.5 ⇒ 3（舊：2）
    - 依品項 82.5：含稅 round_half_up(88.0)＝88、未稅 82.5 ⇒ 83（舊：82）"""
    h = _hdr(client, make_user)
    _quote("MQ-VAT-P1", 3000, 3200, {"items": _ITEMS})
    r = client.post("/api/payment-requests", headers=h,
                    json=_pr_body("amount", quote_no="MQ-VAT-P1", amount=34.5))
    assert r.status_code == 201, r.text
    no = r.json()["request_no"]
    d = client.get("/api/payment-requests/" + no, headers=h).json()
    assert (d["pretaxAmount"], d["taxAmount"]) == (32, 3)
    r = client.post("/api/payment-requests", headers=h,
                    json=_pr_body("items", quote_no="MQ-VAT-P1", items=[{"itemId": 1, "qty": 1, "amount": 82.5}]))
    assert r.status_code == 201, r.text
    d = client.get("/api/payment-requests/" + r.json()["request_no"], headers=h).json()
    assert (d["amount"], d["pretaxAmount"]) == (88, 83)
    # 更新（同一張單改成依品項 82.5、再改回依金額 34.5）
    r = client.put("/api/payment-requests/" + no, headers=h,
                   json=_pr_body("items", items=[{"itemId": 1, "qty": 1, "amount": 82.5}]))
    assert r.status_code == 200, r.text
    d = client.get("/api/payment-requests/" + no, headers=h).json()
    assert (d["amount"], d["pretaxAmount"]) == (88, 83)
    r = client.put("/api/payment-requests/" + no, headers=h, json=_pr_body("amount", amount=34.5))
    assert r.status_code == 200, r.text
    d = client.get("/api/payment-requests/" + no, headers=h).json()
    assert (d["pretaxAmount"], d["taxAmount"]) == (32, 3)


# ══════════════════════════════════════════════════════════════════════════════
# 外包派發稅額（vendor_contractors._dispatch_row／contractor_vouchers 建立匯款申請）
# ══════════════════════════════════════════════════════════════════════════════

def _dispatch(client, h, amount, no):
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "廠商" + no, "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": no, "vendor_id": r.json()["id"], "status": "completed",
            "items_json": [{"description": "施工", "qty": 1, "unit": "式", "unitPrice": amount, "amount": amount}]}
    r = client.post("/api/contractor-dispatches", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_dispatch_tax_rounds_half_up(client, make_user):
    """10,010 × 5% ＝ 500.5 ⇒ 501（舊：500；畫面 Math.round 是 501 ⇒ 前後端差 1 元）。vendor_contractors L137"""
    h = _hdr(client, make_user)
    did = _dispatch(client, h, 10010, "MQ-VAT-D1")
    d = client.get("/api/contractor-dispatches/%s" % did, headers=h).json()
    assert (d["taxAmount"], d["totalWithTax"]) == (501, 10511)
    did2 = _dispatch(client, h, 10000, "MQ-VAT-D2")                                       # 正對照
    assert client.get("/api/contractor-dispatches/%s" % did2, headers=h).json()["taxAmount"] == 500


def test_contractor_voucher_tax_rounds_half_up(client, make_user):
    """同上，匯款申請建立當下凍結的快照。contractor_vouchers L282"""
    h = _hdr(client, make_user)
    did = _dispatch(client, h, 10010, "MQ-VAT-D3")
    r = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": did})
    assert r.status_code == 201, r.text
    v = client.get("/api/contractor-vouchers/" + r.json()["voucher_no"], headers=h).json()
    assert v["snapshot"]["taxAmount"] == 501


# ══════════════════════════════════════════════════════════════════════════════
# 營運報表／首頁／會計匯出（顯示與比對用的整數化）
# ══════════════════════════════════════════════════════════════════════════════

def _insert_dispatch_row(quote_no, total_amount, personnel=None):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, personnel_json, "
            "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "2026-01-01", "amount", "[]", json.dumps(personnel or []), total_amount, "completed",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def test_live_dispatch_total_tax_rounds_half_up(client):
    """精算過期比對用的即時派工含稅：10,010 ⇒ 10,010＋501＝10,511（舊：10,510）。reports L130"""
    import db
    from routers.reports import _live_dispatch_totals_by_quote
    _insert_dispatch_row("MQ-VAT-R1", 10010)
    _insert_dispatch_row("MQ-VAT-R2", 10000)
    conn = db.get_db()
    try:
        t = _live_dispatch_totals_by_quote(conn)
    finally:
        conn.close()
    assert (t["MQ-VAT-R1"], t["MQ-VAT-R2"]) == (10511, 10500)


def test_stale_settlement_compare_rounds_half_up(client):
    """精算快照 dispatchTotal 10,510.5（前端加總外包人員 .5）vs 即時 10,511 ⇒ 一致、不算過期
    （舊：round(10,510.5)＝10,510 ≠ 10,511 ⇒ 誤報過期）。reports L481"""
    import db
    from routers.reports import _collect
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
            "created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-VAT-S1", "已送出", "客戶", "專案", 105000, 100000,
             json.dumps({"dealTag": "已結案", "settlement": {"status": "finalized", "summary": {
                 "dispatchTotal": 10510.5, "netProfit": 1, "netMarginPct": 1.0}}}),
             now, now, "已結案", "2026-01-05"))
        conn.commit()
    finally:
        conn.close()
    _insert_dispatch_row("MQ-VAT-S1", 10010)
    assert _collect("2026-01-01", "2026-12-31")["summary"]["staleSettlementCount"] == 0


def test_achievement_prorata_rounds_half_up(client):
    """過去年度 frac＝1 ⇒ 目標 1,000,000.5 的應達 ⇒ 1,000,001（舊：1,000,000）。reports L605"""
    from routers.reports import _compute_achievement
    ach = _compute_achievement(2020, {"year": 2020, "annual": {"revenue": 1000000.5, "grossProfit": 3000}}, [])
    assert ach["annual"]["revenue"]["prorata"] == 1000001
    assert ach["annual"]["grossProfit"]["prorata"] == 3000                                # 正對照


def test_bank_reconcile_matches_amounts_rounded_half_up(client, make_user):
    """匯款申請含稅 10,500.5 ↔ 銀行 10,501；匯款申請 20,001 ↔ 銀行 20,000.5 ⇒ 兩筆都配對
    （舊：10,500.5⇒10,500、20,000.5⇒20,000，都配不上）。reports L2825（申請金額）、L2830（銀行金額）"""
    import db
    h = _hdr(client, make_user)
    conn = db.get_db()
    try:
        for i, gt in enumerate((10500.5, 20001), 1):
            conn.execute("INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, "
                         "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         ("MQ-VAT-B%d" % i, "2026-01-01", "amount", "[]", 0, "completed", "x", "x"))
            did = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, status, "
                         "snapshot_json, is_paid) VALUES (?,?,?,?,?,0)",
                         ("CV-VAT-%d" % i, did, "MQ-VAT-B%d" % i, "已核准",
                          json.dumps({"grandTotal": gt, "vendorName": "廠商"})))
        conn.commit()
    finally:
        conn.close()
    csv_bytes = "日期,金額,摘要\n2026-01-02,10501,甲\n2026-01-02,20000.5,乙\n2026-01-02,777,正對照\n".encode("utf-8")
    r = client.post("/api/reports/bank-reconcile", headers=h, files={"file": ("b.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    got = {row["amount"]: (row["match"] or {}).get("voucherNo") for row in r.json()["bankRows"]}
    assert got == {10501.0: "CV-VAT-1", 20000.5: "CV-VAT-2", 777.0: None}


def _patch_entries(monkeypatch, contractor=(), material=(), other=()):
    import routers.reports as rp

    def _mk(rows, **extra):
        return lambda *a, **k: [dict({"date": d, "quoteNo": "", "desc": "x", "amount": amt, "taxNote": "",
                                      "provisional": False}, **extra) for d, amt in rows]
    monkeypatch.setattr(rp, "dispatch_entries", _mk(contractor))
    monkeypatch.setattr(rp, "material_entries", _mk(material))
    monkeypatch.setattr(rp, "extra_entries", _mk(other, files=[], pending=False, category="其他"))


def _stock(part_no, cost, created, category="其他"):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO parts (part_no, name, category) VALUES (?,?,?)", (part_no, part_no, category))
        conn.execute("INSERT INTO stock_items (part_no, serial_no, status, batch_no, cost, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?)", (part_no, part_no + "-" + str(cost), "in_stock", "", cost, created, created))
        conn.commit()
    finally:
        conn.close()


def test_expense_report_details_and_monthly_round_half_up(client, monkeypatch):
    """支出結構（reports._collect_expenses）：承攬商 20.5⇒21、叫料 40.5⇒41、料件 30.5⇒31、
    其他 10.5⇒11（舊：20／40／30／10）；月合計 20.5＋40.5＋30.5＋1＝92.5 ⇒ 93（舊：92）。
    reports L3602、L3613、L3645、L3658、L3675～L3677"""
    from routers.reports import _collect_expenses
    _patch_entries(monkeypatch, contractor=[("2019-03-05", 20.5)], material=[("2019-03-06", 40.5)],
                   other=[("2019-03-07", 1)])
    _stock("VAT-P1", 30.5, "2019-03-08T00:00:00")
    ex = _collect_expenses(2019)
    mar = next(m for m in ex["monthly"] if m["month"] == "2019-03")
    assert (mar["contractor"], mar["material"], mar["other"], mar["total"]) == (21, 71, 1, 93)      # 叫料 40.5＋料件 30.5＝71
    assert [d["amount"] for d in ex["details"]["contractor"]] == [21]
    assert sorted(d["amount"] for d in ex["details"]["material"]) == [31, 41]
    _patch_entries(monkeypatch, other=[("2018-04-07", 10.5)])
    ex = _collect_expenses(2018)
    assert [d["amount"] for d in ex["details"]["other"]] == [11]
    assert next(m for m in ex["monthly"] if m["month"] == "2018-04")["other"] == 11
    # 月合計的設備／料件欄（L3675 equipment、L3676 material）：設備 50.5⇒51、叫料 60.5⇒61（舊：50／60）
    _patch_entries(monkeypatch, material=[("2017-05-06", 60.5)])
    _stock("VAT-E1", 50.5, "2017-05-08T00:00:00", category="交換器")
    may = next(m for m in _collect_expenses(2017)["monthly"] if m["month"] == "2017-05")
    assert (may["equipment"], may["material"]) == (51, 61)


def test_accounting_voucher_line_rounds_half_up():
    """傳票匯出的借貸金額：10.5 ⇒ 11（舊：10）、12.5 ⇒ 13（舊：12）。accounting_export L251"""
    from routers.accounting_export import _voucher_line
    ln = _voucher_line("2026-01-01", "c", "s", "1101", "現金", 10.5, 12.5, "", "", "")
    assert (ln["debit"], ln["credit"]) == (11, 13)
    ln = _voucher_line("2026-01-01", "c", "s", "1101", "現金", 11.5, 0, "", "", "")      # 正對照
    assert (ln["debit"], ln["credit"]) == (12, 0)


def test_recognition_flag_amount_rounds_half_up():
    """待補登標註的金額：10.5 ⇒ 11（舊：10）。recognition L339"""
    from helpers.recognition import _flag_item
    assert _flag_item("Q", "c", "d", "x", 10.5, "2026-01-01", True, "extra_no_invoice")["amount"] == 11
    assert _flag_item("Q", "c", "d", "x", None, "2026-01-01", True, "extra_no_invoice")["amount"] is None


def test_extra_expense_total_rounds_half_up_to_cents(client):
    """額外支出小計（元以下兩位）：1 × 0.145 ⇒ 0.15（舊：round(0.145, 2)＝0.14）。
    case_extra_expenses L172（_recalc）、L725（核准變更 _apply_change）"""
    import db
    from routers.case_extra_expenses import ExtraExpenseIn, _recalc, _apply_change
    assert _recalc(ExtraExpenseIn(qty=1, unitCost=0.145)) == 0.15
    assert _recalc(ExtraExpenseIn(qty=3, unitCost=100.1)) == 300.3                         # 正對照
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_extra_expenses (quote_no, description, qty, unit_cost, total_cost) "
                     "VALUES (?,?,?,?,?)", ("MQ-VAT-X1", "x", 1, 1, 1))
        row = conn.execute("SELECT * FROM case_extra_expenses WHERE quote_no='MQ-VAT-X1'").fetchone()
        total = _apply_change(conn, row, {"qty": 1, "unitCost": 0.145, "description": "x"}, "主管",
                              datetime.now().isoformat())
        conn.rollback()
    finally:
        conn.close()
    assert total == 0.15


def test_purchase_suggestion_cost_rounds_half_up_to_cents(client, make_user):
    """採購建議預估金額：單價 0.0625 × 建議量 2 ＝ 0.125 ⇒ 0.13（舊：round(0.125, 2)＝0.12）。inventory L237、L250"""
    u, p = make_user(role="admin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    r = client.post("/api/parts", headers=h, json={"partNo": "VAT-PS1", "name": "料", "category": "其他",
                                                   "safetyStock": 1, "cost": 0.0625})
    assert r.status_code == 201, r.text
    d = client.get("/api/inventory/purchase-suggestions", headers=h).json()
    it = next(x for x in d["items"] if x["part_no"] == "VAT-PS1")
    assert it["suggestedQty"] == 2, it                                                     # 前提
    assert it["estimatedCost"] == 0.13
    assert d["totalEstimatedCost"] == 0.13


# ══════════════════════════════════════════════════════════════════════════════
# 前端（node 載入元件，直接呼叫方法）
# ══════════════════════════════════════════════════════════════════════════════

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="需要 node 才能載入前端元件")

_NODE_HARNESS = r"""
const fs = require('fs'), vm = require('vm')
const [lr, kind, target, factory, body] = process.argv.slice(1)
const noop = () => {}
const ctx = { console, setTimeout, clearTimeout, setInterval, clearInterval, URLSearchParams, Intl,
  window: { addEventListener: noop, innerWidth: 1200, location: { search: '' } },
  document: { addEventListener: noop, querySelector: () => null, getElementById: () => null,
              documentElement: { setAttribute: noop } },
  localStorage: { getItem: () => null, setItem: noop }, location: { search: '', href: '' }, navigator: {},
  fetch: () => new Promise(noop) }
vm.createContext(ctx)
vm.runInContext('var window = globalThis.window;', ctx)
vm.runInContext(fs.readFileSync(lr, 'utf8'), ctx)
vm.runInContext('var MotrixLegalRound = window.MotrixLegalRound;', ctx)
let o
if (kind === 'js') {
  vm.runInContext(fs.readFileSync(target, 'utf8'), ctx, { filename: target })
  o = vm.runInContext(factory + '()', ctx)
} else if (kind === 'page') {
  const html = fs.readFileSync(target, 'utf8')
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1])
    .filter(s => s.includes('function ' + factory + '('))
  if (scripts.length !== 1) throw new Error('找不到元件 ' + factory + '：' + scripts.length)
  vm.runInContext(scripts[0], ctx)
  o = vm.runInContext(factory + '()', ctx)
} else {
  for (const f of target.split('|')) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f })
  o = {}
  for (const p of ctx.window.CM_PARTS) Object.defineProperties(o, Object.getOwnPropertyDescriptors(p()))
}
ctx.__o = o
const out = vm.runInContext('(function (o) {' + body + '})(__o)', ctx)
console.log(JSON.stringify(out))
"""


def _js(kind, target, factory, body):
    r = subprocess.run([NODE, "-e", _NODE_HARNESS, str(FRONTEND / "static" / "legal-round.js"), kind, target,
                        factory, body], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _page(name, factory, body):
    from core import source_tree   # 頁面位置一律經 page_file（C1；列車 train/0926-0415 交會）
    return _js("page", str(source_tree.page_file(name)), factory, body)


def _cm(body):
    parts = sorted((FRONTEND / "js").glob("case-management-*.js"))
    parts.sort(key=lambda p: p.name != "case-management-core.js")
    return _js("cm", "|".join(str(p) for p in parts), "", body)


@needs_node
def test_frontend_quotation_item_amount_and_charity_round_half_up():
    """報價表單：數量 0.7 × 單價 45 ＝ 31.5 ⇒ 32（舊 Math.round(0.7*45)＝31，浮點 31.499…）；
    直接利潤 −150 的公益 1% ＝ −1.5 ⇒ −2（舊 Math.round(−1.5)＝−1）；稅額 9,810 × 5% ⇒ 491（正對照）。"""
    got = _page("quotation-form.html", "quotationForm", """
        const it = { type: 'item', qty: 0.7, unitPrice: 45, cost: 0, unitPriceOverride: true }
        o.q = { items: [it], discount: 0, freight: 0, taxRate: 5 }
        o.calcItem(it)
        const a = it.amount
        o.q = { items: [{ type: 'item', qty: 1, unitPrice: 100, amount: 100, cost: 238 }], discount: 0, freight: 0, taxRate: 5 }
        o.calcTotals()
        const t1 = o.tot
        o.q = { items: [{ type: 'item', qty: 1, unitPrice: 9810, amount: 9810, cost: 0 }], discount: 0, freight: 0, taxRate: 5 }
        o.calcTotals()
        return { a, directProfit: t1.directProfit, charity: t1.charityDonation, tax: o.tot.tax, total: o.tot.total }""")
    assert got == {"a": 32, "directProfit": -150, "charity": -2, "tax": 491, "total": 10301}


@needs_node
def test_frontend_payment_request_form_matches_the_backend():
    """請款單頁：品項 0.7 × 45 ⇒ 32（舊 31）；依金額 3,939 的未稅試算 3,939×10,004／10,504＝3,751.5 ⇒ 3,752
    （舊 3,939／(10,504／10,004) 浮點 3,751.4999… ⇒ 3,751）；比例 30% of 10,015 ⇒ 3,005（正對照）。"""
    got = _page("payment-request-form.html", "paymentRequestForm", """
        o.toggleItem({ itemId: 1, remainingQty: 0.7, unitPrice: 45 })
        const a = o.itemSelections[1].amount
        o.remaining = { quoteTotal: 10504, quotePretax: 10004 }
        o.q.scope = 'amount'; o.ratioInput = 0; o.amountInput = 3939
        const pre = o.currentPretax()
        o.remaining = { quoteTotal: 10015, quotePretax: 9538 }; o.ratioInput = 30
        return { a, pre, ratio: o.ratioToAmount() }""")
    assert got == {"a": 32, "pre": 3752, "ratio": 3005}


@needs_node
def test_frontend_case_finance_matches_the_backend():
    """案件財務（開票申請試算）：品項 0.7 × 45 ⇒ 32（舊 31）；依金額未稅 3,939 ⇒ 3,752（舊 3,751）；
    收款期別 10,015 × 30% ⇒ 3,005（正對照；後端舊值 3,004 見上面的題）。"""
    got = _cm("""
        o.ivItemSelections = {}
        o.ivToggleItem({ itemId: 1, remainingQty: 0.7, unitPrice: 45 })
        o.ivRemaining = { quoteTotal: 10504, quotePretax: 10004 }; o.ivAmountInput = 3939
        o.selected = { total: 10015, pretax: 9538 }
        o.paymentItems = () => [{ pct: 70 }, { pct: 30 }]
        return { a: o.ivItemSelections[1].amount, pre: o.ivAmountPretax(), p2: o.itemAmountWithTax(1) }""")
    assert got == {"a": 32, "pre": 3752, "p2": 3005}


@needs_node
def test_frontend_dispatch_and_extra_expense_match_the_backend():
    """派工品項 0.7 × 45 ⇒ 32（舊 31）；派工稅額 10,010 × 5% ⇒ 501（正對照，後端舊值 500）；
    額外支出 1 × 0.145 ⇒ 0.15（舊 Math.round(14.499…)／100＝0.14）——與後端 _recalc 一致。"""
    got = _cm("""
        o._recalcDispatchTotal = () => {}
        o.dispatchForm = { items: [{ qty: 0.7, unitPrice: 45 }], tax_rate: 0.05 }
        o.onDispatchItemPrice(0)
        const a = o.dispatchForm.items[0].amount
        o.dispatchForm = { items: [{ amount: 10010 }], tax_rate: 0.05 }
        const tax = o._dispatchTaxAmount()
        o.xe = { items: [{ qty: 1, unitCost: 0.145, change: { qty: 1, unitCost: 0.145 } }], msg: '' }
        o.xeRecalc(0); o.xeChangeRecalc(0)
        return { a, tax, x: o.xe.items[0].totalCost, c: o.xe.items[0].change.totalCost }""")
    assert got == {"a": 32, "tax": 501, "x": 0.15, "c": 0.15}


@needs_node
def test_frontend_settlement_rounds_half_up():
    """成本精算：實際 0.7 × 45 ⇒ 32（舊 31）；毛利 −150 的公益 1% ⇒ −2（舊 −1）；管理費 10% of 105 ⇒ 11（正對照）。"""
    got = _page("settlement.html", "settlementPage", """
        const it = { actualQty: 0.7, actualUnitCost: 45, actualCostTaxMode: 'untaxed' }
        o.calcItemCost(it)
        o._origTot = { pretax: 105, total: 110 }
        o.settlement = { items: [] }
        o.xeTotal = 255
        o.dispatchTotal = () => 0
        o.calcSummary()
        return { a: it.actualTotalCost, gross: o.summary.grossProfit, charity: o.summary.charityDonation,
                 admin: o.summary.adminCost }""")
    assert got == {"a": 32, "gross": -150, "charity": -2, "admin": 11}


@needs_node
def test_frontend_material_order_amounts_round_half_up_to_cents():
    """叫料小計（元以下兩位）：1 × 0.145 ⇒ 0.15（舊 Math.round(0.145*100)/100＝0.14，浮點 14.499…）；
    部分付款 0.145 ⇒ 0.15（同上）；2 × 100.1 ⇒ 200.2（正對照）。case-management-exec.js moRecalc／moSave"""
    got = _cm("""
        o.materialOrders = [{ quantity: 1, unitPrice: 0.145, paidStatus: 'paid' }, { quantity: 2, unitPrice: 100.1 }]
        o.moRecalc(0); o.moRecalc(1)
        return [o.materialOrders[0].totalPrice, o.materialOrders[0].paidAmount, o.materialOrders[1].totalPrice]""")
    assert got == [0.15, 0.15, 200.2]


@needs_node
def test_frontend_material_order_save_payload_rounds_half_up_to_cents():
    """送出前的正規化：小計 1 × 0.145 ⇒ 0.15、部分付款 0.145 ⇒ 0.15（舊 0.14／0.14）。moSave"""
    got = _cm("""
        let sent = null
        o.selected = { quote_no: 'Q' }; o.session = { token: 't' }
        o.materialOrders = [{ itemName: '線材', quantity: 1, unitPrice: 0.145, paidStatus: 'partial', paidAmount: 0.145, paidDate: '2026-09-26' }]
        const realFetch = globalThis.fetch
        globalThis.fetch = (url, opt) => { sent = JSON.parse(opt.body); return new Promise(() => {}) }
        o.moSave()
        globalThis.fetch = realFetch
        const m = sent && sent.materialOrders[0]
        return m ? [m.totalPrice, m.paidAmount] : ['no-payload', o.moMsg || '']""")
    assert got == [0.15, 0.15]


@needs_node
def test_frontend_reports_estimated_profit_rounds_half_up():
    """營運報表頁的預估淨利＝未稅 × 淨利率：100 × −1.5% ＝ −1.5 ⇒ −2（舊 Math.round(−1.5)＝−1）；
    10,000 × 12.3% ⇒ 1,230（正對照）。reports.js estGrossProfit"""
    got = _js("js", str(FRONTEND / "js" / "reports.js"), "reportsApp", """
        return [o.estGrossProfit({ pretax: 100, netMarginPct: -1.5 }), o.estGrossProfit({ pretax: 10000, netMarginPct: 12.3 })]""")
    assert got == [-2, 1230]
