# -*- coding: utf-8 -*-
"""35c 稅基 B（使用者 2026-10-03：「承攬商的部分稅金也跟正式做同步，避免有 5% 金額爭議」）：精算的承攬商成本＝未稅承攬費＋外包人員
（營運報表權責口徑／總帳 E04 同一口徑）；承攬商稅額是進項稅額（總帳記 1268 資產），不是成本，只作資訊並列。

對帳依據：docs/platform/audit/AUDIT-0C-settlement-recon.md S2（未稅 10000、稅率 5%、外包人員 2000：精算舊 17050／報表 16550／總帳成本 14550）。
舊完結案（summary 沒有 dispatchBasis）不改寫、不重驗，「過期」比對跟含稅現算值比；新完結案帶 dispatchBasis='pretax'，跟未稅現算值比。
獎金（payroll/bonus.py）原樣帶出存檔的 summary：新完結案的淨利基數會因此高於舊口徑（＝承攬商稅額×0.99），舊完結案不變——這裡釘住，不動獎金程式。
"""
import json

import pytest

import db
from modules.case import recognition as R
from modules.case import settlement_actuals as SA
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get, _put_settlement

NOW = "2026-10-03T00:00:00"


def _dispatch(total=10000, personnel=2000, rate=0.05, status="accepted", invoice_date="2026-10-02", approval="", quote_no=None):
    cn = db.get_db()
    try:
        row = cn.execute("SELECT id FROM vendor_contractors WHERE name='稅基測試承攬商'").fetchone()
        if not row:
            cn.execute("INSERT INTO vendor_contractors (name, tax_id, created_at, updated_at) VALUES ('稅基測試承攬商','87650001',?,?)", (NOW, NOW))
            row = cn.execute("SELECT id FROM vendor_contractors WHERE name='稅基測試承攬商'").fetchone()
        cur = cn.execute(
            "INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, tax_rate, personnel_json, status, approval_status,"
            " invoice_no, invoice_date, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no or NO, row["id"], "2026-10-01", "amount", "[]", total, rate, json.dumps([{"name": "甲", "amount": personnel}] if personnel else []), status, approval,
             "ZZ00000001", invoice_date, NOW, NOW))
        cn.commit()
        return cur.lastrowid
    finally:
        cn.close()


def test_dispatch_cost_is_pretax_plus_personnel_and_the_tax_is_information_only(W):
    """0c S2：未稅 10000、5%、人員 2000 ⇒ 計入成本 12000（不是 12500）；稅額 500、含稅合計 12500 並列為資訊；恆等式成立。"""
    c, h = W
    base = _get(c, h)["totals"]["totalActualCost"]
    _dispatch(10000, 2000)
    d = _get(c, h)
    t = d["totals"]
    assert t["dispatchTotal"] == 12000 and t["dispatchReport"] == 12000 and t["dispatchBasis"] == "pretax"
    assert t["dispatchTax"] == 500 and t["dispatchGrandTotal"] == 12500
    assert t["dispatchGrandTotal"] == t["dispatchTotal"] + t["dispatchTax"]
    assert t["totalActualCost"] - base == 12000                                  # 稅 500 不進總成本（舊口徑會是 +12500）
    assert d["costExtras"]["dispatch"]["grandTotal"] == 12500 and d["costExtras"]["dispatch"]["report"] == 12000 and d["costExtras"]["dispatch"]["tax"] == 500


def test_dispatch_cost_equals_recognition_accrual_and_gl_e04_pretax(W):
    """對帳恆等式：精算 dispatchTotal ＝ Σ recognition.dispatch_entries(accrual) ＝ 總帳 E04 專案成本借方（未稅）＋ 外包人員；E04 進項稅額 ＝ dispatchTax。"""
    c, h = W
    did = _dispatch(10000, 2000)
    t = _get(c, h)["totals"]
    cn = db.get_db()
    try:
        rec = sum(e["amount"] for e in R.dispatch_entries(cn, "accrual") if e["quoteNo"] == NO)
    finally:
        cn.close()
    assert t["dispatchTotal"] == rec == 12000
    from modules.subcontract import gl_events as G
    ev = [e for e in G.gl_events("2026-10-01", "2026-10-31")["events"] if e["event_code"] == "E04" and e["source_key"] == str(did)]
    assert len(ev) == 1
    lines = {(l["role"], l["side"]): l["amount"] for l in ev[0]["lines"]}
    assert lines[("COST_PROJECT", "D")] == 10000 == t["dispatchTotal"] - 2000        # 總帳成本＝未稅承攬費（人員 2000 在付款／勞報單時點入帳，非稅基問題）
    assert lines[("INPUT_TAX", "D")] == 500 == t["dispatchTax"]                      # 稅額在總帳是進項稅額（資產），不是成本
    assert lines[("AP", "C")] == 10500


def test_rows_excluded_by_the_report_rules_are_excluded_here_too(W):
    c, h = W
    _dispatch(10000, 0)
    _dispatch(5000, 0, status="cancelled")
    _dispatch(3000, 0, approval="草稿")
    _dispatch(4000, 0, approval="已退回")
    _dispatch(1000, 0, approval="待審核")
    t = _get(c, h)["totals"]
    assert t["dispatchTotal"] == 10000 + 1000 and t["dispatchTax"] == 500 + 50 and t["dispatchGrandTotal"] == 11550


def test_a_draft_follows_the_new_basis_live_while_the_frozen_values_stay_as_stored(W):
    """非凍結（草稿）即時照新口徑；已完結的存檔值一個位元都不改，口徑標記照存檔（舊案沒有標記＝含稅 'taxed'）。"""
    c, h = W
    _dispatch(10000, 2000)
    assert _get(c, h)["totals"]["dispatchTotal"] == 12000                          # 草稿（沒有存檔）＝新口徑
    old = {"status": "finalized", "items": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 12501}}
    _put_settlement(old)
    d = _get(c, h)
    t = d["totals"]
    assert t["dispatchTotal"] == 12500 and t["totalActualCost"] == 12501 and t["dispatchBasis"] == "taxed"      # 凍結值照存檔；舊案＝含稅口徑
    assert d["live"]["dispatchTotal"] == 12000 and d["live"]["dispatchGrandTotal"] == 12500 and d["live"]["dispatchTax"] == 500   # 現算值另放，供「過期」比對
    new = {"status": "finalized", "items": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12000, "totalActualCost": 12001, "dispatchBasis": "pretax"}}
    _put_settlement(new)
    t2 = _get(c, h)["totals"]
    assert t2["dispatchTotal"] == 12000 and t2["totalActualCost"] == 12001 and t2["dispatchBasis"] == "pretax"


def test_the_stale_basis_pairing_helper_never_mixes_bases(W):
    """『過期』比對的口徑配對（三處共用同一規則）：沒有標記 ⇒ 與含稅比；pretax ⇒ 與未稅比。"""
    _dispatch(10000, 2000)
    cn = db.get_db()
    try:
        gross = SA.case_extras(cn, NO)["dispatch"]
    finally:
        cn.close()
    assert gross["grandTotal"] == 12500 and gross["report"] == 12000 and gross["tax"] == 500


# ── 獎金：原樣帶出存檔的 summary（不重算）——新完結案的淨利基數較高，舊完結案不變 ──────────────────

def test_bonus_uses_the_stored_finalized_summary_so_old_cases_are_unchanged():
    from modules.payroll import bonus as B
    old = {"status": "finalized", "summary": {"dispatchTotal": 12500, "totalActualCost": 17050, "netProfit": 50000}}      # 舊口徑（含稅）
    new = {"status": "finalized", "summary": {"dispatchTotal": 12000, "totalActualCost": 16550, "netProfit": 50495, "dispatchBasis": "pretax"}}
    assert B.settlement_fields(old)["dispatchTotal"] == 12500 and B.settlement_fields(old)["netProfit"] == 50000
    assert B.settlement_fields(new)["dispatchTotal"] == 12000 and B.settlement_fields(new)["netProfit"] == 50495
    # base_amount_for ⇒ (可用?, 基數, 原因)：基數＝存檔淨利；新口徑多 495＝承攬商稅額 500×0.99（公益金 1%）
    assert B.base_amount_for(old)[:2] == (True, 50000) and B.base_amount_for(new)[:2] == (True, 50495)
