# -*- coding: utf-8 -*-
"""32-S5 追補：結算輸出（結案精算 PDF、獎金分潤 PDF 的精算明細、營運報表）的分項加總＝實際總成本——
`itemPoUnadopted`（連到品項、尚未按「採用」的採購單金額）必須有地方顯示；沒有這個鍵／為 0 的歷史精算輸出逐字不變。"""
import json
import re

import pytest

import db

NO = "MQ-EXP-1"
SUMMARY = {"quotedPretax": 21000, "quotedTotal": 22050, "itemActualTotal": 11025, "extraTotal": 700, "dispatchTotal": 300,
           "totalActualCost": 11025 + 700 + 300, "grossProfit": 8975, "grossMarginPct": 42.7, "adminCost": 2100, "charityDonation": 90,
           "netProfit": 6785, "netMarginPct": 32.3, "origTotalCost": 10000, "origNetProfit": 7000, "origNetMarginPct": 33.0,
           "origMarginPct": 40.0, "origItemTotal": 21000, "origDirectProfit": 11000, "origAdminCost": 2100, "origCharity": 110}
UNADOPTED = 12000


def _money_after(html, label):
    m = re.search(re.escape(label) + r"</td><td[^>]*>\s*(?:NT\$\s*)?(?:−\s*)?([\d,]+)", html)
    assert m, label
    return int(m.group(1).replace(",", ""))


def _seed_case(summary):
    c = db.get_db()
    try:
        data = {"items": [], "settlement": {"status": "finalized", "summary": summary, "items": [], "extraItems": []}, "caseRecord": {"payment": {"items": []}}}
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 22050, 21000, json.dumps(data), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "已結案"))
        c.commit()
    finally:
        c.close()


def _closing_html():
    import pdf_gen
    return pdf_gen._build_case_closing_html(pdf_gen._case_closing_report_data(NO))


def test_closing_pdf_breakdown_sums_to_total_with_unadopted_po(client):
    s = dict(SUMMARY, itemPoUnadopted=UNADOPTED, totalActualCost=SUMMARY["totalActualCost"] + UNADOPTED)
    _seed_case(s)
    h = _closing_html()
    parts = [_money_after(h, l) for l in ("品項實際成本", "採購單（品項尚未採用）", "額外支出", "承攬商派發成本")]
    assert parts[1] == UNADOPTED and sum(parts) == _money_after(h, "實際總成本") == s["totalActualCost"]


def test_closing_pdf_is_identical_for_history_with_or_without_the_new_key(client):
    _seed_case(dict(SUMMARY))
    old = _closing_html()
    assert "採購單（品項尚未採用）" not in old
    parts = [_money_after(old, l) for l in ("品項實際成本", "額外支出", "承攬商派發成本")]
    assert sum(parts) == _money_after(old, "實際總成本")
    c = db.get_db()
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?",
              (json.dumps({"items": [], "settlement": {"status": "finalized", "summary": dict(SUMMARY, itemPoUnadopted=0), "items": [], "extraItems": []},
                           "caseRecord": {"payment": {"items": []}}}), NO))
    c.commit()
    c.close()
    assert _closing_html() == old                                           # 鍵是 0 ⇒ 逐字相同


def test_bonus_pdf_settlement_table_gets_an_extra_row_only_when_unadopted(client):
    from modules.payroll import bonus_pdf as BP
    base = BP._settlement_rows_html({"summary": dict(SUMMARY)})
    assert base.count("<tr>") == 11 and "採購單" not in base                 # 規格的 11 列不變
    with_po = BP._settlement_rows_html({"summary": dict(SUMMARY, itemPoUnadopted=UNADOPTED, totalActualCost=SUMMARY["totalActualCost"] + UNADOPTED)})
    assert with_po.count("<tr>") == 12 and "採購單（品項尚未採用）" in with_po
    assert BP._settlement_rows_html({"summary": dict(SUMMARY, itemPoUnadopted=0)}) == base          # 0 ⇒ 逐字不變
    parts = [_money_after(with_po, l) for l in ("品項實際成本", "採購單（品項尚未採用）", "額外支出", "承攬商派發成本")]
    assert sum(parts) == _money_after(with_po, "實際總成本")


def _report(summary, finalized_at="2026-09-30"):
    import io
    from datetime import datetime
    from modules.analytics.api.reports import _augment_with_targets, _build_excel, _build_report_html, _collect, _parse_period
    c = db.get_db()
    data_json = {"dealTag": "已結案", "items": [], "caseRecord": {"payment": {"items": []}},
                 "settlement": {"status": "finalized", "finalizedAt": finalized_at, "summary": summary, "items": [], "extraItems": []}}
    c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
              " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 22050, 21000, json.dumps(data_json), "2026-01-01T00:00:00", "2026-09-30T00:00:00", "已結案", "2026-06-01"))
    c.commit()
    c.close()
    label, d0, d1 = _parse_period("2026")
    data = _augment_with_targets(_collect(d0, d1, None), d0)
    assert any(m["quoteNo"] == NO for m in data["marginCases"]), "測試資料要出現在毛利案件裡"
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    return _build_report_html(data, label, gen), _build_excel(data, label, gen)


def _excel_rows(xlsx_bytes):
    """所有含該案號的列（案件會出現在多張工作表）。"""
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    out = [list(row) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) if row and NO in [str(x) for x in row if x is not None]]
    assert out, "Excel 找不到案件 %s" % NO
    return out


def test_operating_report_html_row_and_excel_columns_add_up_with_unadopted_po(client):
    s = dict(SUMMARY, itemPoUnadopted=UNADOPTED, totalActualCost=SUMMARY["totalActualCost"] + UNADOPTED)
    html, xlsx = _report(s)
    if "實際成本精算" in html:                                                # HTML 的精算區塊（有些版面只在單案報表）
        assert "採購單（品項尚未採用）" in html
    rows = [[x for x in r if isinstance(x, (int, float))] for r in _excel_rows(xlsx)]
    assert any(11025 + UNADOPTED in n and 700 in n and s["totalActualCost"] in n for n in rows), rows      # 品項欄含未採用金額；與額外支出相加＝實際總成本（派發 300 另含）
    assert (11025 + UNADOPTED) + 700 + 300 == s["totalActualCost"]


def test_operating_report_history_row_is_unchanged(client):
    html, xlsx = _report(dict(SUMMARY))
    rows = [[x for x in r if isinstance(x, (int, float))] for r in _excel_rows(xlsx)]
    assert any(11025 in n and 700 in n and SUMMARY["totalActualCost"] in n for n in rows), rows
    assert "採購單（品項尚未採用）" not in html
