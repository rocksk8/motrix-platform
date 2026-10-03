# -*- coding: utf-8 -*-
"""35c 結案報表 PDF 的承攬商稅額說明（使用者裁示）：新完結案（summary.dispatchBasis＝'pretax'）在「承攬商派發成本」下加**一行**
「承攬商：未稅 X／稅額 Y（進項稅額，不計成本）」；舊完結案（沒有標記）印出來與改版前逐字相同。這是 repo 第一份結案報表 PDF 文字測試。"""
import json
import re

import db

PRETAX_NOTE = "承攬商：未稅 12,000／稅額 500（進項稅額，不計成本）"
_STAMP = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d")


def _make(quote_no, summary):
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已結案",
            "editHistory": [{"type": "settlement_finalized", "at": "2026-10-03T00:00:00"}],
            "settlement": {"status": "finalized", "items": [], "summary": summary},
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, settle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 105000, 100000, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已結案", "finalized"))
        conn.commit()
    finally:
        conn.close()


def _html(quote_no):
    import pdf_gen
    return _STAMP.sub("<時間>", pdf_gen._build_case_closing_html(pdf_gen._case_closing_report_data(quote_no)))


BASE = {"quotedPretax": 100000, "itemActualTotal": 50000, "extraTotal": 0, "dispatchTotal": 12000, "totalActualCost": 62000,
        "grossProfit": 38000, "grossMarginPct": 38.0, "adminCost": 10000, "charityDonation": 380, "netProfit": 27620, "netMarginPct": 27.6}


def test_new_finalized_case_prints_one_tax_info_line_under_the_dispatch_cost(client):
    _make("MQ-PDFTAX-NEW", dict(BASE, dispatchBasis="pretax", dispatchTax=500, dispatchGrandTotal=12500))
    html = _html("MQ-PDFTAX-NEW")
    assert html.count(PRETAX_NOTE) == 1, "新完結案的結案報表少了（或重複了）承攬商稅額說明"
    assert html.index("承攬商派發成本") < html.index(PRETAX_NOTE) < html.index("實際總成本"), "說明要在『承攬商派發成本』與『實際總成本』之間"


def test_old_finalized_case_prints_exactly_as_before(client):
    _make("MQ-PDFTAX-OLD", dict(BASE, dispatchTotal=12500, totalActualCost=62500))               # 沒有 dispatchBasis ＝ 舊口徑（含稅）
    _make("MQ-PDFTAX-OLD2", dict(BASE, dispatchTotal=12500, totalActualCost=62500, dispatchBasis="pretax", dispatchTax=500))
    old = _html("MQ-PDFTAX-OLD")
    assert "進項稅額" not in old and "承攬商：未稅" not in old
    # 同一份數字：有標記的版本拿掉那一個區塊之後，與沒有標記的版本逐字相同 ⇒ 只多了那一行、其餘一個位元組都沒動
    new = _html("MQ-PDFTAX-OLD2")
    block = "\n      " + re.search(r"<tr>[^\n]*承攬商：未稅[^\n]*</tr>", new).group(0)
    assert new.replace(block, "").replace("MQ-PDFTAX-OLD2", "MQ-PDFTAX-OLD") == old, "舊完結案的輸出與『新版拿掉說明行』不同"
