# -*- coding: utf-8 -*-
"""34：精算端點把承攬商派發、匯款手續費、自訂模組支出也算進來（`costExtras`／`totals.dispatchTotal` 等）。
口徑與頁面現行算法逐位相同（使用者裁示 A）：派發＝含稅承攬費＋人員；同時輸出未稅的 `dispatchReport`（營運報表口徑），差異＝承攬費的稅，由本檔鎖定。"""
import json

import db
from modules.case import recognition as R
from modules.case import settlement_actuals as SA
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _submit  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import EST_A, EST_B, _get


def _sql(sql, args=()):
    cn = db.get_db()
    try:
        cn.execute(sql, args)
        cn.commit()
    finally:
        cn.close()


def _qa(sql, args=()):
    cn = db.get_db()
    try:
        return cn.execute(sql, args).fetchall()
    finally:
        cn.close()


def _q1(sql, args=()):
    cn = db.get_db()
    try:
        return cn.execute(sql, args).fetchone()
    finally:
        cn.close()


def _dispatch(total, status="confirmed", approval="", personnel=None, tax_rate=0.05):
    cn = db.get_db()
    try:
        cn.execute("INSERT INTO vendor_contractors (name, created_at, updated_at) VALUES ('測試承攬商','2026-10-03','2026-10-03')") if not cn.execute(
            "SELECT 1 FROM vendor_contractors WHERE name='測試承攬商'").fetchone() else None
        vid = cn.execute("SELECT id FROM vendor_contractors WHERE name='測試承攬商'").fetchone()["id"]
        cn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, tax_rate, personnel_json, status, approval_status,"
                   " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (NO, vid, "2026-10-03", "amount", "[]", total, tax_rate, json.dumps(personnel or []), status, approval, "2026-10-03T00:00:00", "2026-10-03T00:00:00"))
        cn.commit()
    finally:
        cn.close()


def _page_dispatch_total(c, h):
    """舊頁 loadDispatches()＋dispatchTotal() 的逐字翻譯：打 /api/contractor-dispatches，排除已取消與草稿／已退回，加總 grandTotal。"""
    r = c.get("/api/contractor-dispatches?quote_no=%s" % NO, headers=h)
    assert r.status_code == 200, r.text
    return sum(float(d.get("grandTotal") or 0) for d in r.json() if d["status"] != "cancelled" and (d.get("approvalStatus") or "") not in ("草稿", "已退回"))


def test_dispatch_total_equals_the_old_page_rule_and_report_is_the_pretax_basis(W):
    c, h = W
    _dispatch(10000)                                                              # 含稅 10500
    _dispatch(2000, personnel=[{"name": "甲", "amount": 700}])                    # 含稅 2100＋人員 700 ＝ 2800
    _dispatch(5000, status="cancelled")                                           # 已取消：不計
    _dispatch(3000, approval="草稿")                                              # 草稿：不計
    _dispatch(4000, approval="已退回")                                            # 已退回：不計
    _dispatch(1000, approval="待審核")                                            # 待審核：照計（31-A）→ 1050
    d = _get(c, h)
    ex = d["costExtras"]["dispatch"]
    assert ex["grandTotal"] == _page_dispatch_total(c, h) == 10500 + 2800 + 1050
    assert ex["count"] == 3
    assert ex["report"] == 10000 + 2700 + 1000                                    # 未稅承攬費＋人員
    cn = db.get_db()
    try:
        rep = sum(e["amount"] for e in R.dispatch_entries(cn, "accrual") if e["quoteNo"] == NO)
    finally:
        cn.close()
    assert ex["report"] == rep                                                    # 漂移守門：dispatchReport＝營運報表／總帳的派發口徑
    assert ex["grandTotal"] - ex["report"] == 10000 * 0.05 + 2000 * 0.05 + 1000 * 0.05   # 兩個口徑的差異正好是承攬費的 5% 稅
    # 35c 稅基 B（使用者 2026-10-03）：精算計入成本的 dispatchTotal ＝ 未稅＋人員（＝報表／總帳口徑 report）；含稅合計與稅額並列為資訊
    t = d["totals"]
    assert t["dispatchTotal"] == ex["report"] == t["dispatchReport"] and t["dispatchBasis"] == "pretax"
    assert t["dispatchGrandTotal"] == ex["grandTotal"] and t["dispatchTax"] == ex["tax"] == 10000 * 0.05 + 2000 * 0.05 + 1000 * 0.05
    assert t["dispatchGrandTotal"] == t["dispatchTotal"] + t["dispatchTax"]                # 恆等式：含稅 ＝ 計入成本 ＋ 稅額


def test_no_dispatches_is_zero_and_other_cases_do_not_leak(W):
    c, h = W
    cn = db.get_db()
    cn.execute("INSERT INTO vendor_contractors (name, created_at, updated_at) VALUES ('另一家','2026-10-03','2026-10-03')")
    vid = cn.execute("SELECT id FROM vendor_contractors WHERE name='另一家'").fetchone()["id"]
    cn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
               ("MQ-PL-2", vid, "2026-10-03", "amount", "[]", 9999, "confirmed", "2026-10-03T00:00:00", "2026-10-03T00:00:00"))
    cn.commit()
    cn.close()
    ex = _get(c, h)["costExtras"]["dispatch"]
    assert (ex["grandTotal"], ex["report"], ex["count"]) == (0, 0, 0)


def test_remit_fees_equal_the_old_pages_two_sources(W):
    c, h = W
    _dispatch(100)
    _dispatch(100)
    did, did2 = [r["id"] for r in _qa("SELECT id FROM contractor_dispatches WHERE quote_no=? ORDER BY id", (NO,))]
    ex1 = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=700)]).json()
    assert _submit(c, h, ex1["id"]).status_code == 200
    _sql("UPDATE case_extra_expenses SET remit_fee=15, paid_date='2026-10-03' WHERE id=?", (ex1["id"],))
    ex2 = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=300)]).json()
    assert _submit(c, h, ex2["id"]).status_code == 200
    _sql("UPDATE case_extra_expenses SET remit_fee=99 WHERE id=?", (ex2["id"],))                  # 沒登錄付款日：手續費不算
    ex3 = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=200)]).json()
    assert _submit(c, h, ex3["id"]).status_code == 200
    _sql("UPDATE case_extra_expenses SET remit_fee=55, paid_date='2026-10-03', status='已作廢' WHERE id=?", (ex3["id"],))   # 已作廢：不進任何合計
    _sql("INSERT INTO contractor_payment_vouchers(voucher_no, dispatch_id, quote_no, status, snapshot_json, is_paid, paid_at, remit_fee) VALUES (?,?,?,?,?,?,?,?)",
         ("V-1", did, NO, "已核可", "{}", 1, "2026-10-03", 30))
    _sql("INSERT INTO contractor_payment_vouchers(voucher_no, dispatch_id, quote_no, status, snapshot_json, is_paid, paid_at, remit_fee) VALUES (?,?,?,?,?,?,?,?)",
         ("V-2", did2, NO, "已核可", "{}", 0, "", 77))                                               # 未匯款：不算
    page_extra = c.get("/api/quotations/%s/extra-expenses" % NO, headers=h).json()["remitFeeTotal"]
    page_voucher = c.get("/api/contractor-vouchers/remit-fee-total?quote_no=%s" % NO, headers=h).json()["feeTotal"]
    f = _get(c, h)["costExtras"]["remitFee"]
    assert (f["extraExpenses"], f["contractor"], f["total"]) == (page_extra, page_voucher, page_extra + page_voucher) == (15, 30, 45)


def test_custom_module_expense_and_total_actual_cost_follow_the_pages_formula(W, monkeypatch):
    c, h = W
    from helpers import custom_finance as CFIN
    monkeypatch.setattr(CFIN, "case_finance", lambda conn, no: {"expense": {"total": 123, "items": []}, "income": {"total": 0, "items": [], "skippedTotal": 0}})
    _dispatch(1000)                                                               # 含稅 1050
    ex = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=700)]).json()
    assert _submit(c, h, ex["id"]).status_code == 200
    d = _get(c, h)
    t = d["totals"]
    assert t["customExpenseTotal"] == 123 and d["costExtras"]["customExpense"]["total"] == 123
    # 舊頁 calcSummary：totalActualCost ＝ itemActualTotal ＋ itemPoUnadopted ＋ extraTotal（額外支出＋手續費＋自訂）＋ dispatchTotal
    from modules.case.tests.test_settlement_actuals_2026_10_03 import _order, _put_materials
    _put_materials([_order("X", 1, 250)], {"X": "已核准"})                          # 未對應材料申請併入額外支出（頁面 extraTotal 的一部分）
    _sql("UPDATE quotations SET deal_tag='已成案' WHERE quote_no=?", (NO,))          # 材料申請只計已成案案件
    d = _get(c, h)
    t = d["totals"]
    assert t["materialUnassignedTotal"] == 250
    assert t["totalActualCost"] == (EST_A + EST_B) + 0 + (700 + 250 + t["remitFeeTotal"] + 123) + 1000        # 35c：承攬商以未稅 1000 計入（含稅 1050 的稅 50 不計成本）
    assert t["extraTotal"] == 700                                                 # extraTotal 仍只是額外支出（鍵名與舊語意不變）


def test_frozen_settlement_keeps_the_saved_cost_extras(W):
    c, h = W
    from modules.case.tests.test_settlement_actuals_2026_10_03 import _put_settlement
    _dispatch(1000)
    _put_settlement({"status": "finalized", "items": [], "summary": {"itemActualTotal": 5, "extraTotal": 7, "dispatchTotal": 999, "remitFeeTotal": 3, "customExpenseTotal": 2,
                                                                      "totalActualCost": 1111}})
    t = _get(c, h)["totals"]
    assert (t["dispatchTotal"], t["remitFeeTotal"], t["customExpenseTotal"], t["totalActualCost"]) == (999, 3, 2, 1111)      # 完結後不隨派發漂移
    assert _get(c, h)["costExtras"]["dispatch"]["grandTotal"] == 1050                                                          # 現算值另放 costExtras
