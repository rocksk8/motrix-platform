# -*- coding: utf-8 -*-
"""結案報表金額口徑（fix/closing-report-amounts，使用者 2026-11-17；正式機 MQ-202607-045 回報 b／c／d）：
b. 第六節派發金額＝精算口徑（未稅承攬費＋稅額＋外包人員）；只有外包人員的派發單不再印 0；未對應品項獨立一列；合計對得上第三節。
c. 已收金額＝各列實收淨額相加（沒有 actualAmount 的列扣手續費），收款率跟著。
d. 品項稅別註記依實際稅別；原始成本印含稅（讀者自己加得出原始直接毛利）；已完結的精算數字不動。
測試資料取 MQ-202607-045 的形狀（不碰正式庫）。"""
import json
import re

import db
import pdf_gen

NO = "MQ-CLOSE-045"
_STAMP = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d")


def _item(i, desc, total, mode, **kw):
    return dict({"id": str(i), "origDescription": desc, "origBrand": "", "actualTotalCost": total, "actualCostTaxMode": mode,
                 "actualSource": "manual", "adoptSystem": False}, **kw)


def _seed(quote_no=NO, *, items=None, summary_over=None, dispatches=True, with_draft=False):
    items = items if items is not None else [
        _item(1, "硬體A", 79228, "pretax"), _item(2, "硬體B", 116992, "pretax"),
        _item(3, "硬體C", 25323, "pretax"), _item(4, "硬體D", 40516, "pretax"),
        _item(5, "施工", 43000, "taxed_gross"),
        _item(6, "採購品", 30000, "pretax", adoptSystem=True),          # 採用系統採購＝含稅最終金額：不算未稅手填
        _item(7, "人力", 5000, "pretax", actualSource="labor"),         # 人力沒有進項稅：不算
    ]
    summary = {"quotedPretax": 837550, "origTotalCost": 421059, "origDirectProfit": 395438, "origMarginPct": 47.2,
               "origAdminCost": 98860, "origCharity": 8794, "origNetProfit": 287784, "origNetMarginPct": 34.4,
               "itemActualTotal": 347765, "extraTotal": 2731, "dispatchTotal": 40895, "dispatchTax": 1495, "dispatchBasis": "taxed",
               "dispatchAssignedTotal": 34895, "dispatchUnassignedTotal": 6000, "dispatchAbsorbedTotal": 34895,
               "totalActualCost": 356496, "grossProfit": 481054, "grossMarginPct": 57.4, "adminCost": 120264, "charityDonation": 8794,
               "netProfit": 351996, "netMarginPct": 42.0, "profitDiff": 64212}
    summary.update(summary_over or {})
    pay = [{"type": "訂金款", "pct": 50, "amount": 439715, "feeAmount": 15, "received": True, "receivedAt": "2026-07-20"},     # 沒有 actualAmount
           {"type": "交貨款", "pct": 30, "amount": 263828, "feeAmount": 15, "actualAmount": 263813, "received": True, "receivedAt": "2026-08-20"},
           {"type": "尾款", "pct": 20, "amount": 175885, "feeAmount": 15, "actualAmount": 175870, "received": True, "receivedAt": "2026-09-20"}]
    data = {"dealTag": "已結案", "caseRecord": {"payment": {"items": pay}},
            "settlement": {"status": "finalized", "settlementDate": "2026-08-02", "schemaVersion": 2, "items": items, "summary": summary}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, settle_status) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (quote_no, "已送出", "測試客戶", "測試專案", 879428, 837550, json.dumps(data, ensure_ascii=False),
                      "2026-07-01T00:00:00", "2026-07-01T00:00:00", "已結案", "finalized"))
        if dispatches:
            vid = conn.execute("INSERT INTO vendor_contractors (name) VALUES (?)", ("測試廠商",)).lastrowid

            def disp(date, scope, vendor, items_amt, personnel, status="completed", approval="已核准"):
                items_json = json.dumps([{"description": scope, "qty": 1, "unit": "式", "unitPrice": items_amt, "amount": items_amt}] if items_amt else [])
                conn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, total_amount, "
                             "status, approval_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (quote_no, vendor, date, scope, items_json, json.dumps([{"name": "人員", "amount": a} for a in personnel]),
                              items_amt, status, approval, "2026-07-01T00:00:00", "2026-07-01T00:00:00"))
            disp("2026-07-10", "硬體施工", vid, 12000, [])
            disp("2026-07-12", "系統建置", vid, 17900, [])
            disp("2026-07-18", "", None, 0, [3500])                                   # 只有外包人員：total_amount＝0、金額在 personnel_json
            disp("2026-08-29", "專案執行、系統測試", None, 0, [3000, 3000])             # 同上、未對應品項
            if with_draft:
                disp("2026-09-01", "草稿單", vid, 9999, [], status="draft", approval="草稿")
        conn.commit()
    finally:
        conn.close()


def _html(quote_no=NO):
    return _STAMP.sub("<時間>", pdf_gen._build_case_closing_html(pdf_gen._case_closing_report_data(quote_no)))


def _section(html, start, end):
    a = html.index(start)
    return html[a:html.index(end, a)]


# ── b. 第六節派發明細 ────────────────────────────────────────────────────────────────
def test_personnel_only_dispatches_show_their_amounts_not_zero(client):
    _seed()
    sec = _html().split("承攬商／外包派發明細")[1]
    tr = {m.group(1): m.group(0) for m in re.finditer(r"<tr><td>[^<]*</td><td>(\d{4}-\d\d-\d\d)</td>.*?</tr>", sec)}
    assert {"2026-07-10", "2026-07-12", "2026-07-18", "2026-08-29"} <= set(tr)
    last = lambda row: re.findall(r"<td class=\"r\">([^<]*)</td>", row)[-1]                  # noqa: E731  最後一欄＝計入成本
    assert last(tr["2026-07-18"]) == "3,500", tr["2026-07-18"]                                # 只有外包人員：人員 3,500（舊版印 0）
    assert last(tr["2026-08-29"]) == "6,000", tr["2026-08-29"]                                # 兩人各 3,000
    assert last(tr["2026-07-10"]) == "12,600", tr["2026-07-10"]                               # 12,000＋稅 600
    assert last(tr["2026-07-12"]) == "18,795", tr["2026-07-12"]                               # 17,900＋稅 895


def test_section_total_matches_section_three_and_unassigned_is_its_own_line(client):
    _seed()
    html = _html()
    assert "合計（計入成本）</td><td class=\"r\">40,895</td>" in html
    assert "本節合計 40,895 ＝ 第三節「承攬商派發成本」40,895" in html
    assert "其中未對應品項 6,000" in html
    # 第三節：未對應獨立一列＋等式（品項＋額外支出＋未對應＝實際總成本）
    assert "其中：承攬商未對應品項</td><td class=\"r orange\">6,000</td>" in html
    assert "品項實際成本 347,765 ＋ 額外支出 2,731 ＋ 承攬商未對應品項 6,000 ＝ 實際總成本 356,496" in html


def test_mismatch_with_section_three_is_said_out_loud(client):
    _seed(summary_over={"dispatchTotal": 40000})
    assert "⚠ 本節合計 40,895 與第三節「承攬商派發成本」40,000 不同（差 895）" in _html()


def test_draft_dispatches_are_not_listed_or_counted_but_are_mentioned(client):
    _seed(with_draft=True)
    html = _html()
    assert "草稿單" not in html and "9,999" not in html
    assert "另有 1 張草稿／已退回的派發單，精算不計成本，未列出" in html
    assert "合計（計入成本）</td><td class=\"r\">40,895</td>" in html


def test_pretax_basis_finalized_case_counts_fee_plus_personnel_only(client):
    _seed(summary_over={"dispatchBasis": "pretax", "dispatchTotal": 36500, "dispatchTax": 1495})
    html = _html()
    assert "稅額（不計入）" in html
    assert "合計（計入成本）</td><td class=\"r\">39,400</td>" in html          # 12,000＋17,900＋3,500＋6,000（稅額不計）


# ── c. 已收金額與收款率 ──────────────────────────────────────────────────────────────
def test_received_total_deducts_fee_when_actual_amount_is_missing(client):
    _seed()
    data = pdf_gen._case_closing_report_data(NO)
    assert data["receivedTotal"] == 439700 + 263813 + 175870 == 879383        # 舊版 879,398（第 1 期沒扣手續費 15）
    html = _html()
    assert "<span>已收金額</span><span>879,383</span>" in html
    assert "<span>收款率</span><span>99.99%</span>" in html                    # 還差 45 沒收到：不印 100.0%


def test_collection_rate_still_100_when_fully_received(client):
    _seed()
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
        for p in d["caseRecord"]["payment"]["items"]:
            p["feeAmount"], p["actualAmount"] = 0, p["amount"]
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
        conn.commit()
    finally:
        conn.close()
    assert "<span>收款率</span><span>100.0%</span>" in _html()


# ── d. 稅基註記與原始成本 ────────────────────────────────────────────────────────────
def test_item_note_follows_actual_tax_modes_and_warns_about_untaxed_items(client):
    _seed()
    html = _html()
    assert "手填品項依各自稅別計入，其中 4 項（合計 262,059）是未稅金額，沒有加 5% 稅" in html     # 採用系統採購的、人力、含稅自動加總的都不算
    assert "約 13,103（262,059×5%）可能是稅基差，不一定是實際節省" in html
    assert "品項：含 5% 稅（估計＝報價成本×1.05" not in html, "有未稅手填品項時，不可再一律寫『品項：含 5% 稅』"


def test_item_note_unchanged_when_no_untaxed_manual_items(client):
    _seed(items=[_item(1, "硬體A", 10000, "taxed_gross"), _item(2, "舊存檔", 500, None)])          # 沒有稅別欄位＝舊口徑，不判定
    html = _html()
    assert "品項：含 5% 稅（估計＝報價成本×1.05，假設進項稅不可扣抵；採購單／材料申請為含稅最終金額）" in html
    assert "稅基提醒" not in html


def test_original_cost_is_printed_with_tax_so_the_reader_can_add_it_up(client):
    _seed()
    html = _html()
    assert "原始成本（料件，含 5% 稅估計）</td><td class=\"r\">442,112</td>" in html
    assert "報價成本（未稅）421,059 ×1.05" in html
    assert 837550 - 442112 == 395438                                         # 收入 − 印出的成本 ＝ 印出的原始直接毛利


def test_original_cost_row_unchanged_for_legacy_summary(client):
    _seed(summary_over={"origDirectProfit": 837550 - 421059})                # 舊口徑：毛利＝收入 − 未稅成本
    html = _html()
    assert "原始成本（料件）</td><td class=\"r\">421,059</td>" in html and "含 5% 稅估計" not in html


def test_old_case_without_new_keys_has_no_new_rows(client):
    _seed(dispatches=False, summary_over={"dispatchUnassignedTotal": None})
    html = _html()
    assert "承攬商未對應品項" not in html and "承攬商／外包派發明細" not in html


# ── d（精算頁）：只提示、不遷移 ──────────────────────────────────────────────────────
def test_settlement_page_warns_on_untaxed_manual_items_without_changing_calculation():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[2] / "frontend" / "pages" / "settlement.html").read_text(encoding="utf-8")
    i = html.index("stl-taxbasis-warn-")
    block = html[i - 200:i + 700]
    assert "item.actualCostTaxMode === 'pretax' || item.actualCostTaxMode === 'taxed'" in block
    assert "!item.adoptSystem" in block and "actualSource !== 'labor'" in block
    assert "含稅5%（自動加總）" in block
    # 計算沒動：未稅仍是原值、含稅仍是 ÷1.05、自動加總仍是 ×1.05
    assert "item.actualTotalCost = raw\n" in html and "MotrixLegalRound.halfUp(raw / 1.05)" in html and "MotrixLegalRound.halfUp(raw, 1.05)" in html
