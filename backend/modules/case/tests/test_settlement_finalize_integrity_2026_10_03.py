# -*- coding: utf-8 -*-
"""35c F1（AUDIT-0C S7；使用者裁示 D10「後端重算，超出進位誤差就拒絕完結」）：完結時後端用同一個 compute() 重算**全部**會被下游讀的欄位，
不只品項／額外支出／採購類三塊——承攬商、手續費、自訂支出、總成本、毛利、管理費、公益金、淨利、毛利率都要對得上，否則 409、不存檔。

背景：營運報表毛利直接讀 settlement.netProfit／grossProfit（reports.py:401-402），獎金與結案 PDF 讀同一份 summary；
S7 探針（財務檢視帳號直接 PUT）送 dispatchTotal=0、totalActualCost=4550、netProfit=888888 ⇒ 舊程式 200 並凍結。
紅燈探針先 commit（舊程式上這些偽造案例都是 200）；舊完結案不重驗（只在「非完結 → 完結」轉換時比對，與 33-A5 相同）。
"""
import json

import pytest

import db
from modules.case import settlement_actuals as SA
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get
from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch

URL = "/api/quotations/%s/settlement" % NO
QUOTED_PRETAX = 100000


def _set_tot():
    """報價的 tot（頁面 quotedPretax 的來源）；沒有它頁面的 quotedPretax＝0、利潤線全是負的，探針就沒有意義。"""
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": QUOTED_PRETAX, "total": 105000}
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()


def page_payload(c, h, **over):
    """逐字照精算頁 calcSummary 的算法，用後端單一來源的數字組出完結 payload（含承攬商、手續費、自訂、利潤線、口徑標記）。"""
    d = _get(c, h)
    t = d["totals"]
    items = [{"id": i["itemId"], "adoptSystem": True, "actualTotalCost": i["actual"]["amount"]} for i in d["items"]]
    extra_total = t["extraTotal"] + t["materialUnassignedTotal"] + t["remitFeeTotal"] + t["customExpenseTotal"]
    total = t["itemActualTotal"] + 0 + extra_total + t["dispatchTotal"]
    gross = QUOTED_PRETAX - total
    admin = SA.round_half_up(QUOTED_PRETAX, 0.10)
    charity = SA.round_half_up(gross, 0.01)
    net = gross - admin - charity
    summ = {"quotedPretax": QUOTED_PRETAX, "quotedTotal": 105000, "itemActualTotal": t["itemActualTotal"], "itemPoUnadopted": 0, "extraTotal": extra_total,
            "dispatchTotal": t["dispatchTotal"], "totalActualCost": total, "remitFeeTotal": t["remitFeeTotal"], "customExpenseTotal": t["customExpenseTotal"],
            "purchasedTotal": t["purchasedTotal"], "materialUnassignedTotal": t["materialUnassignedTotal"],
            "dispatchTax": t["dispatchTax"], "dispatchGrandTotal": t["dispatchGrandTotal"], "dispatchBasis": "pretax",
            "grossProfit": gross, "grossMarginPct": round(gross / QUOTED_PRETAX * 100, 1), "adminCost": admin, "charityDonation": charity,
            "netProfit": net, "netMarginPct": round(net / QUOTED_PRETAX * 100, 1)}
    summ.update(over)
    return {"status": "finalized", "items": items, "summary": summ, "offsets": []}


def _status():
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        return (d.get("settlement") or {}).get("status")
    finally:
        cn.close()


def _put(c, h, st):
    return c.put(URL, json={"settlement": st}, headers=h)


@pytest.fixture
def case(W):
    c, h = W
    _set_tot()
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _dispatch(10000, 2000)                                        # 承攬商未稅 10000（稅 500）＋人員 2000 ⇒ 計入 12000
    return c, h


def test_the_honest_page_payload_finalizes(case):
    c, h = case
    r = _put(c, h, page_payload(c, h))
    assert r.status_code == 200, r.text
    assert _status() == "finalized"


def test_s7_probe_forged_dispatch_total_and_net_profit_are_rejected(case):
    """0c S7 原樣：dispatchTotal=0、totalActualCost 偽造、netProfit=888888（其餘維持頁面算出的值，所以舊的三塊比對全過）。"""
    c, h = case
    honest = page_payload(c, h)
    forged = page_payload(c, h, dispatchTotal=0, totalActualCost=honest["summary"]["totalActualCost"] - 12000, netProfit=888888)
    r = _put(c, h, forged)
    assert r.status_code == 409, "偽造的完結 summary 被接受了：%s %s" % (r.status_code, r.text[:200])
    assert _status() is None, "被拒絕的完結不可以有任何存檔"


@pytest.mark.parametrize("field,value", [
    ("dispatchTotal", 0), ("dispatchTotal", 99999),
    ("totalActualCost", 1), ("grossProfit", 1), ("adminCost", 1), ("charityDonation", 99999), ("netProfit", 888888),
])
def test_every_field_downstream_reads_is_verified_one_at_a_time(case, field, value):
    c, h = case
    r = _put(c, h, page_payload(c, h, **{field: value}))
    assert r.status_code == 409, (field, r.status_code, r.text[:160])
    assert field in r.text or {"dispatchTotal": "承攬商", "totalActualCost": "總成本", "grossProfit": "毛利", "adminCost": "管理費",
                               "charityDonation": "公益", "netProfit": "淨利"}[field] in r.text, r.text[:240]
    assert _status() is None


def test_forged_margin_percentages_are_rejected(case):
    c, h = case
    assert _put(c, h, page_payload(c, h, grossMarginPct=99.9)).status_code == 409
    assert _put(c, h, page_payload(c, h, netMarginPct=99.9)).status_code == 409


def test_remit_fee_and_custom_expense_are_verified_too(case):
    """手續費／自訂支出：偽造它們同時調整 extraTotal 與總成本（讓舊的『額外支出』那一塊還對得上）也要被抓到。"""
    c, h = case
    p = page_payload(c, h)
    s = p["summary"]
    s["remitFeeTotal"] += 5000
    s["extraTotal"] += 5000
    s["totalActualCost"] += 5000
    assert _put(c, h, p).status_code == 409
    p = page_payload(c, h)
    s = p["summary"]
    s["customExpenseTotal"] += 3000
    s["extraTotal"] += 3000
    s["totalActualCost"] += 3000
    assert _put(c, h, p).status_code == 409


def test_a_summary_missing_the_downstream_fields_cannot_bypass_the_check_the_server_fills_them_in(case):
    """省略欄位也繞不過：沒送的下游欄位不是偽造所以不拒絕，但存檔前由伺服器用重算值補齊（含口徑標記）⇒ 存下來的一定是完整且正確的。"""
    c, h = case
    honest = page_payload(c, h)["summary"]
    p = page_payload(c, h)
    for k in ("dispatchTotal", "netProfit", "totalActualCost", "grossProfit", "adminCost", "charityDonation", "grossMarginPct", "netMarginPct", "quotedPretax", "dispatchBasis"):
        p["summary"].pop(k, None)
    r = _put(c, h, p)
    assert r.status_code == 200, r.text[:300]
    cn = db.get_db()
    try:
        saved = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]["summary"]
    finally:
        cn.close()
    for k in ("dispatchTotal", "netProfit", "totalActualCost", "grossProfit", "adminCost", "charityDonation", "quotedPretax"):
        assert abs(saved[k] - honest[k]) <= 3, (k, saved[k], honest[k])           # 伺服器重算值（進位誤差內）
    assert saved["dispatchBasis"] == "pretax"


def test_a_partial_forgery_is_still_rejected_even_if_other_fields_are_omitted(case):
    c, h = case
    p = page_payload(c, h, netProfit=888888)
    for k in ("dispatchTotal", "totalActualCost"):
        p["summary"].pop(k, None)
    assert _put(c, h, p).status_code == 409 and _status() is None


def test_a_stale_cached_page_without_the_basis_marker_is_asked_to_refresh(case):
    """35c 之前的頁面送的 dispatchTotal 是含稅 12,500 且沒有 dispatchBasis：對不上新口徑 ⇒ 409，訊息要叫人重新整理。"""
    c, h = case
    old_page = page_payload(c, h, dispatchTotal=12500, totalActualCost=page_payload(c, h)["summary"]["totalActualCost"] + 500)
    del old_page["summary"]["dispatchBasis"]
    r = _put(c, h, old_page)
    assert r.status_code == 409 and "重新整理" in r.json()["detail"]


def test_rounding_tolerance_still_allows_small_differences(case):
    c, h = case
    p = page_payload(c, h)
    s = p["summary"]
    s["charityDonation"] += 1
    s["netProfit"] -= 1
    r = _put(c, h, p)
    assert r.status_code == 200, r.text[:300]


def test_non_settlement_page_callers_without_item_totals_are_not_checked(W):
    """summary 沒有 itemActualTotal（非精算頁的呼叫，例如備註存檔）⇒ 無從比對，維持 33-A5 的行為（不擋）。"""
    c, h = W
    r = _put(c, h, {"status": "finalized", "items": [], "summary": {"netProfit": 5}})
    assert r.status_code == 200


def test_old_finalized_cases_are_never_revalidated_on_read(case):
    """已完結（含偽造／舊口徑）的存檔：讀取（GET settlement-actuals）照常回凍結值，不重驗、不改寫。"""
    c, h = case
    from modules.case.tests.test_settlement_actuals_2026_10_03 import _put_settlement
    _put_settlement({"status": "finalized", "items": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 0, "totalActualCost": 4550, "netProfit": 888888}})
    d = _get(c, h)
    assert d["frozen"] is True and d["totals"]["dispatchTotal"] == 0 and d["savedSummary"]["netProfit"] == 888888
