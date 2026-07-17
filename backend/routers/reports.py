"""Financial report generation — Excel & PDF (admin+ only)."""
import io
import json
import os
import subprocess
import tempfile
from calendar import monthrange
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote as _url_quote

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from db import get_db
from helpers import _require_user, _warranty_expiry, _get_edge_path

router = APIRouter()

_COMPANY  = "允碩整合集創"
_COMPANY2 = "統一編號 60575481 ｜ Tel: 04-3602-2818 ｜ info@miactw.com"


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_period(period: str):
    today = date.today()
    if not period:
        period = f"{today.year}-{today.month:02d}"
    if "Q" in period.upper():
        yr, q = period.upper().split("-Q")
        yr, q = int(yr), int(q)
        ms = (q - 1) * 3 + 1
        me = ms + 2
        d0 = date(yr, ms, 1)
        d1 = date(yr, me, monthrange(yr, me)[1])
        return f"{yr} 年第 {q} 季", d0.isoformat(), d1.isoformat()
    yr, mo = int(period[:4]), int(period[5:7])
    d0 = date(yr, mo, 1)
    d1 = date(yr, mo, monthrange(yr, mo)[1])
    return f"{yr} 年 {mo} 月", d0.isoformat(), d1.isoformat()


def _fmt(n):
    return f"NT$ {int(n or 0):,}"


def _collect(period_start: str, period_end: str) -> dict:
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, status, customer_name, project_name,
               total, pretax, quote_date, sales_person,
               net_margin_pct, direct_margin_pct,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
               json_extract(data_json,'$.caseRecord')         AS cr_json,
               json_extract(data_json,'$.settlement.summary') AS settle_json,
               COALESCE(NULLIF(settle_status,''), json_extract(data_json,'$.settlement.status'), '') AS settle_status
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
        ORDER BY quote_date DESC
    """).fetchall()
    conn.close()

    all_items, period_items, outstanding = [], [], []
    cases_all, cases_period = [], []

    for row in rows:
        cr = {}
        if row["cr_json"]:
            try: cr = json.loads(row["cr_json"])
            except Exception: pass

        total = row["total"] or 0
        pay   = (cr.get("payment") or {}).get("items", [])
        recv_amt = 0

        if pay:
            others = sum(round(total * (p.get("pct") or 0) / 100) for p in pay[1:])
            for idx, pi in enumerate(pay):
                amt  = int(total - others) if idx == 0 else round(total * (pi.get("pct") or 0) / 100)
                rcvd = bool(pi.get("received"))
                rat  = (pi.get("receivedAt") or "")[:10]
                aa   = pi.get("actualAmount")
                fee  = pi.get("feeAmount") or 0
                net  = ((aa if aa is not None else amt) - fee) if rcvd else None

                item = {
                    "quoteNo":      row["quote_no"],
                    "customer":     row["customer_name"] or "",
                    "project":      row["project_name"]  or "",
                    "salesPerson":  row["sales_person"]  or "",
                    "quoteDate":    row["quote_date"]    or "",
                    "dealTag":      row["deal_tag"]      or "",
                    "idx":          idx,
                    "type":         pi.get("type", f"第{idx+1}期"),
                    "pct":          pi.get("pct") or 0,
                    "amount":       amt,
                    "received":     rcvd,
                    "receivedAt":   rat,
                    "receivedBy":   pi.get("receivedBy", ""),
                    "actualAmount": aa,
                    "feeAmount":    fee,
                    "netAmount":    net,
                    "invoiceNo":    pi.get("invoiceNo", ""),
                    "feeNote":      pi.get("feeNote", ""),
                    "note":         pi.get("note", ""),
                }
                all_items.append(item)
                if rcvd and period_start <= rat <= period_end:
                    period_items.append(item)
                elif not rcvd:
                    outstanding.append(item)
                if rcvd:
                    recv_amt += amt

        settle = {}
        if row["settle_json"]:
            try: settle = json.loads(row["settle_json"])
            except Exception: pass

        qdate = row["quote_date"] or ""
        roles = cr.get("roles") or {}
        case = {
            "quoteNo":        row["quote_no"],
            "customer":       row["customer_name"] or "",
            "project":        row["project_name"]  or "",
            "salesPerson":    row["sales_person"]  or "",
            "quoteDate":      qdate,
            "dealTag":        row["deal_tag"]      or "",
            "roles":          roles,
            "total":          total,
            "pretax":         row["pretax"] or 0,
            "netMarginPct":   float(row["net_margin_pct"] or 0),
            "receivedAmount": recv_amt,
            "collectionRate": round(recv_amt / total * 100, 1) if total > 0 else 0,
            "settleStatus":   row["settle_status"] or "",
            "actualMarginPct": float(settle.get("grossMarginPct") or 0) if settle else None,
            "grossProfit":     int(settle.get("grossProfit") or 0) if settle else None,
            "inPeriod":       period_start <= qdate[:10] <= period_end,
        }
        cases_all.append(case)
        if case["inPeriod"]:
            cases_period.append(case)

    # sales perf
    sm: dict = {}
    for c in cases_all:
        k = c["salesPerson"] or "（未指定）"
        sm.setdefault(k, {"salesPerson": k, "cases": 0, "total": 0, "received": 0, "mSum": 0, "mCnt": 0, "amSum": 0, "amCnt": 0})
        sm[k]["cases"]    += 1
        sm[k]["total"]    += c["total"]
        sm[k]["received"] += c["receivedAmount"]
        if c["netMarginPct"]:
            sm[k]["mSum"] += c["netMarginPct"]
            sm[k]["mCnt"] += 1
        if c["actualMarginPct"] is not None and c["settleStatus"] == "finalized":
            sm[k]["amSum"] += c["actualMarginPct"]
            sm[k]["amCnt"] += 1
    sales = []
    for v in sm.values():
        sales.append({
            "salesPerson":        v["salesPerson"],
            "caseCount":          v["cases"],
            "totalAmount":        v["total"],
            "receivedAmount":     v["received"],
            "collectionRate":     round(v["received"] / v["total"] * 100, 1) if v["total"] > 0 else 0,
            "avgMarginPct":       round(v["mSum"] / v["mCnt"], 1) if v["mCnt"] > 0 else 0,
            "avgActualMarginPct": round(v["amSum"] / v["amCnt"], 1) if v["amCnt"] > 0 else None,
            "settledCount":       v["amCnt"],
        })
    sales.sort(key=lambda x: x["totalAmount"], reverse=True)

    # warranty
    warr = []
    conn2 = get_db()
    wrows = conn2.execute("""
        SELECT quote_no, customer_name, project_name,
               json_extract(data_json,'$.caseRecord') AS cr_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
          AND json_extract(data_json,'$.caseRecord') IS NOT NULL
    """).fetchall()
    conn2.close()
    for r in wrows:
        try:
            cr2 = json.loads(r["cr_json"])
            for dev in cr2.get("devices") or []:
                exp, dl = _warranty_expiry(dev.get("warrantyStart",""), dev.get("warrantyMonths"))
                if exp and dl <= 90:
                    warr.append({
                        "quoteNo":  r["quote_no"],
                        "customer": r["customer_name"] or "",
                        "project":  r["project_name"] or "",
                        "device":   dev.get("name",""),
                        "sn":       dev.get("sn",""),
                        "mac":      dev.get("mac",""),
                        "expiry":   exp.isoformat(),
                        "daysLeft": dl,
                    })
        except Exception:
            pass
    warr.sort(key=lambda x: x["daysLeft"])

    # totals
    tr   = sum(i["amount"] for i in all_items)
    tc   = sum(i["amount"] for i in all_items if i["received"])
    tfee = sum(i["feeAmount"] for i in all_items if i["received"])
    tact = sum((i["actualAmount"] if i["actualAmount"] is not None else i["amount"]) for i in all_items if i["received"])
    pr   = sum(i["amount"] for i in period_items)
    pfee = sum(i["feeAmount"] for i in period_items)
    pact = sum((i["actualAmount"] if i["actualAmount"] is not None else i["amount"]) for i in period_items)

    _closed  = sum(1 for c in cases_all if c["dealTag"] == "已結案")
    _settled = sum(1 for c in cases_all if c["settleStatus"] == "finalized")
    _act_gp  = sum(c["grossProfit"] for c in cases_all if c["settleStatus"] == "finalized" and c["grossProfit"] is not None)
    return {
        "summary": {
            "totalReceivable":        tr,
            "totalCollected":         tc,
            "totalOutstanding":       tr - tc,
            "totalFee":               tfee,
            "netCollected":           tact - tfee,
            "collectionRate":         round(tc / tr * 100, 1) if tr > 0 else 0,
            "totalCases":             len(cases_all),
            "activeCases":            sum(1 for c in cases_all if c["dealTag"] == "已成案"),
            "closedCases":            _closed,
            "periodCases":            len(cases_period),
            "periodReceived":         pr,
            "periodFee":              pfee,
            "periodNet":              pact - pfee,
            "warrantyAlerts":         len(warr),
            "settledCases":           _settled,
            "totalActualGrossProfit": _act_gp,
            "settleCoverage":         round(_settled / _closed * 100, 1) if _closed > 0 else 0,
        },
        "periodItems":    period_items,
        "outstanding":    outstanding,
        "allItems":       all_items,
        "casesAll":       cases_all,
        "casesPeriod":    cases_period,
        "salesPerf":      sales,
        "marginCases":    [c for c in cases_all if c["actualMarginPct"] is not None],
        "warranty":       warr[:30],
    }


# ── Excel builder ─────────────────────────────────────────────────────────────

def _xl_style(wb):
    """Return reusable style factory."""
    def f(bold=False, size=9, color="000000", wrap=False, italic=False):
        return Font(name="微軟正黑體", bold=bold, size=size, color=color, italic=italic)
    def fill(hex_color):
        return PatternFill("solid", fgColor=hex_color)
    def border():
        s = Side(style="thin", color="D1D5DB")
        return Border(left=s, right=s, top=s, bottom=s)
    def al(h="left", v="center", wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)
    return f, fill, border, al


def _set_row(ws, row_idx, values, font=None, fill=None, border=None, aligns=None, height=None):
    for ci, val in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=ci, value=val)
        if font:   cell.font   = font
        if fill:   cell.fill   = fill
        if border: cell.border = border
        if aligns and ci - 1 < len(aligns):
            cell.alignment = aligns[ci - 1]
        elif aligns and len(aligns) == 1:
            cell.alignment = aligns[0]
    if height:
        ws.row_dimensions[row_idx].height = height


def _build_excel(data: dict, period_label: str, gen_at: str) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    mk, fill, mk_border, al = _xl_style(wb)
    BD = mk_border()

    C_DARK   = "111827"
    C_BLUE   = "2563EB"
    C_GREEN  = "15803D"
    C_RED    = "DC2626"
    C_ORANGE = "D97706"
    C_GRAY   = "6B7280"
    C_LGRAY  = "F9FAFB"
    C_LBLUE  = "EFF6FF"
    C_LGREEN = "F0FDF4"
    C_LRED   = "FEF2F2"
    C_LYELLOW= "FFFBEB"
    C_WHITE  = "FFFFFF"

    s = data["summary"]

    # ── Sheet 1: 執行摘要 ───────────────────────────────────────────────────
    ws1 = wb.create_sheet("執行摘要")
    ws1.sheet_view.showGridLines = False
    ws1.column_dimensions["A"].width = 26
    ws1.column_dimensions["B"].width = 22
    ws1.column_dimensions["C"].width = 26
    ws1.column_dimensions["D"].width = 22

    # banner
    ws1.merge_cells("A1:D1")
    c = ws1["A1"]
    c.value = f"{_COMPANY} — 營運報表"
    c.font  = mk(bold=True, size=16, color=C_WHITE)
    c.fill  = fill(C_DARK)
    c.alignment = al("center")
    ws1.row_dimensions[1].height = 36

    ws1.merge_cells("A2:D2")
    c = ws1["A2"]
    c.value = _COMPANY2
    c.font  = mk(size=9, color="9CA3AF")
    c.fill  = fill(C_DARK)
    c.alignment = al("center")
    ws1.row_dimensions[2].height = 18

    ws1.merge_cells("A3:D3")
    c = ws1["A3"]
    c.value = f"報表期間：{period_label}　　產製時間：{gen_at}"
    c.font  = mk(size=9, color=C_GRAY)
    c.alignment = al("center")
    ws1.row_dimensions[3].height = 20

    # separator row
    ws1.row_dimensions[4].height = 8

    def kpi_block(ws, row, col_a, col_b, title, val, val_color=C_DARK, sub=None):
        ca = ws.cell(row=row, column=col_a, value=title)
        ca.font = mk(size=9, color=C_GRAY)
        ca.fill = fill(C_LGRAY)
        ca.border = BD
        ca.alignment = al("left")
        cv = ws.cell(row=row + 1, column=col_a, value=val)
        cv.font = mk(bold=True, size=14, color=val_color)
        cv.fill = fill(C_LGRAY)
        cv.border = BD
        cv.alignment = al("left")
        if sub is not None:
            cs = ws.cell(row=row + 2, column=col_a, value=sub)
            cs.font = mk(size=8, color=C_GRAY, italic=True)
            cs.fill = fill(C_LGRAY)
            cs.border = BD
            cs.alignment = al("left")

    # ── AR KPIs (2 columns × 3 rows each) ──
    blocks = [
        ("總應收金額",       _fmt(s["totalReceivable"]),          C_DARK,   None),
        ("已收款（帳面）",   _fmt(s["totalCollected"]),           C_GREEN,  f"收款率 {s['collectionRate']}%"),
        ("未收款",           _fmt(s["totalOutstanding"]),         C_RED,    None),
        ("手續費合計",       _fmt(s["totalFee"]),                 C_ORANGE, None),
        ("實收淨額",         _fmt(s["netCollected"]),             C_GREEN,  None),
        ("本期收款",         _fmt(s["periodReceived"]),           C_BLUE,   f"本期淨 {_fmt(s['periodNet'])}"),
        ("精算實際毛利合計", _fmt(s["totalActualGrossProfit"]),   "7C3AED", f"已精算 {s['settledCases']} 件"),
        ("精算覆蓋率",       f"{s['settleCoverage']}%",          "7C3AED", f"已結案 {s['closedCases']} 件中 {s['settledCases']} 件完成"),
    ]
    r = 5
    for i, (title, val, vc, sub) in enumerate(blocks):
        col = 1 if i % 2 == 0 else 3
        if i % 2 == 0 and i > 0:
            r += 4
        kpi_block(ws1, r, col, col + 1, title, val, vc, sub)
        if sub:
            ws1.row_dimensions[r + 2].height = 14
        ws1.row_dimensions[r].height = 16
        ws1.row_dimensions[r + 1].height = 24
    r += 4

    # ── Case KPIs ──
    ws1.merge_cells(f"A{r}:D{r}")
    c = ws1.cell(row=r, column=1, value="案件與業績概況")
    c.font = mk(bold=True, size=10, color=C_WHITE)
    c.fill = fill(C_BLUE)
    c.alignment = al("left")
    ws1.row_dimensions[r].height = 20
    r += 1

    case_rows = [
        ("合約總案數",   s["totalCases"],    ""),
        ("進行中案件",   s["activeCases"],   ""),
        ("已結案件",     s["closedCases"],   ""),
        ("本期新成案",   s["periodCases"],   ""),
        ("保固到期預警", s["warrantyAlerts"], "90天內"),
    ]
    for label, val, note in case_rows:
        _set_row(ws1, r, [label, val, note, ""],
                 font=mk(size=9),
                 border=BD,
                 aligns=[al("left"), al("right"), al("left"), al("left")],
                 height=18)
        ws1.cell(row=r, column=1).font = mk(bold=True, size=9, color=C_GRAY)
        ws1.cell(row=r, column=2).font = mk(bold=True, size=12, color=C_DARK)
        r += 1

    # ── Sheet 2: 本期收款明細 ────────────────────────────────────────────────
    ws2 = wb.create_sheet("本期收款明細")
    ws2.sheet_view.showGridLines = False

    hdrs2 = ["案件號","客戶","專案名稱","業務員","款項類型","應收金額","收款日期",
             "實收金額","手續費","實收淨額","發票號碼","手續費備注","備注"]
    cols2 = [13,18,18,10,9,12,11,12,10,12,12,14,14]
    for i, (h, w) in enumerate(zip(hdrs2, cols2), 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    ws2.merge_cells(f"A1:{get_column_letter(len(hdrs2))}1")
    c = ws2["A1"]
    c.value = f"本期收款明細 — {period_label}"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill(C_GREEN)
    c.alignment = al("center")
    ws2.row_dimensions[1].height = 24

    _set_row(ws2, 2, hdrs2,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)

    for r_i, item in enumerate(data["periodItems"], 3):
        aa  = item["actualAmount"]
        row_vals = [
            item["quoteNo"], item["customer"], item["project"], item["salesPerson"],
            item["type"],
            item["amount"],
            item["receivedAt"],
            aa if aa is not None else item["amount"],
            item["feeAmount"] or None,
            item["netAmount"],
            item["invoiceNo"] or "",
            item["feeNote"] or "",
            item["note"] or "",
        ]
        bg = C_LGREEN
        _set_row(ws2, r_i, row_vals,
                 font=mk(size=9), fill=fill(bg), border=BD,
                 aligns=[al("left"), al("left"), al("left"), al("left"),
                         al("center"), al("right"), al("center"),
                         al("right"), al("right"), al("right"),
                         al("left"), al("left"), al("left")],
                 height=18)
        for ci in [6, 8, 9, 10]:
            cell = ws2.cell(row=r_i, column=ci)
            cell.number_format = '#,##0'
        ws2.cell(row=r_i, column=9).font = mk(size=9, color=C_RED)
        ws2.cell(row=r_i, column=10).font = mk(bold=True, size=9, color=C_GREEN)

    # sum row
    sr = len(data["periodItems"]) + 3
    sum_vals = ["合計", "", "", "", "",
                sum(i["amount"] for i in data["periodItems"]), "",
                sum((i["actualAmount"] if i["actualAmount"] is not None else i["amount"]) for i in data["periodItems"]),
                sum(i["feeAmount"] or 0 for i in data["periodItems"]),
                sum(i["netAmount"] or 0 for i in data["periodItems"]),
                "", "", ""]
    _set_row(ws2, sr, sum_vals,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill(C_DARK), border=BD,
             aligns=[al("left")] + [al("right")] * 12,
             height=20)
    for ci in [6, 8, 9, 10]:
        ws2.cell(row=sr, column=ci).number_format = '#,##0'

    # ── Sheet 3: 未收款清單 ──────────────────────────────────────────────────
    ws3 = wb.create_sheet("未收款清單")
    ws3.sheet_view.showGridLines = False

    hdrs3 = ["案件號","客戶","專案名稱","業務員","案件進度","款項類型","應收金額","比例(%)","報價日期"]
    cols3 = [13,18,18,10,9,9,13,9,12]
    for i, (h, w) in enumerate(zip(hdrs3, cols3), 1):
        ws3.column_dimensions[get_column_letter(i)].width = w

    ws3.merge_cells(f"A1:{get_column_letter(len(hdrs3))}1")
    c = ws3["A1"]
    c.value = f"未收款清單 — 截至 {gen_at[:10]}"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill(C_RED)
    c.alignment = al("center")
    ws3.row_dimensions[1].height = 24

    _set_row(ws3, 2, hdrs3,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)

    for r_i, item in enumerate(data["outstanding"], 3):
        _set_row(ws3, r_i,
                 [item["quoteNo"], item["customer"], item["project"], item["salesPerson"],
                  item["dealTag"], item["type"], item["amount"], item["pct"], item["quoteDate"]],
                 font=mk(size=9), fill=fill(C_LRED), border=BD,
                 aligns=[al("left"), al("left"), al("left"), al("left"),
                         al("center"), al("center"), al("right"), al("right"), al("center")],
                 height=18)
        ws3.cell(row=r_i, column=7).number_format = '#,##0'

    sr3 = len(data["outstanding"]) + 3
    _set_row(ws3, sr3, ["合計未收", "", "", "", "", "",
                         sum(i["amount"] for i in data["outstanding"]),
                         "", ""],
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill(C_DARK), border=BD,
             aligns=[al("left")] + [al("right")] * 8, height=20)
    ws3.cell(row=sr3, column=7).number_format = '#,##0'

    # ── Sheet 4: 案件清單 ────────────────────────────────────────────────────
    ws4 = wb.create_sheet("案件清單")
    ws4.sheet_view.showGridLines = False

    hdrs4 = ["案件號","客戶","專案名稱","業務員","報價日期","案件進度",
             "合約含稅","合約未稅","預估毛利率","已收款","收款率(%)","精算狀態","實際毛利率","實際毛利"]
    cols4 = [13,18,18,10,11,9,13,13,11,13,10,9,11,13]
    for i, (h, w) in enumerate(zip(hdrs4, cols4), 1):
        ws4.column_dimensions[get_column_letter(i)].width = w

    ws4.merge_cells(f"A1:{get_column_letter(len(hdrs4))}1")
    c = ws4["A1"]
    c.value = f"全部案件清單（本期新成案：{len(data['casesPeriod'])} 件）"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill(C_DARK)
    c.alignment = al("center")
    ws4.row_dimensions[1].height = 24

    _set_row(ws4, 2, hdrs4,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)

    for r_i, c_ in enumerate(data["casesAll"], 3):
        in_p = c_["inPeriod"]
        bg   = C_LBLUE if in_p else C_WHITE
        am   = c_["actualMarginPct"]
        row_v = [
            c_["quoteNo"], c_["customer"], c_["project"], c_["salesPerson"],
            c_["quoteDate"], c_["dealTag"],
            c_["total"], c_["pretax"],
            f"{c_['netMarginPct']:.1f}%" if c_["netMarginPct"] else "",
            c_["receivedAmount"],
            f"{c_['collectionRate']:.1f}%",
            c_["settleStatus"] or "未精算",
            f"{am:.1f}%" if am is not None else "",
            c_["grossProfit"] if c_["grossProfit"] is not None else "",
        ]
        _set_row(ws4, r_i, row_v,
                 font=mk(size=9), fill=fill(bg), border=BD,
                 aligns=[al("left"), al("left"), al("left"), al("left"),
                         al("center"), al("center"), al("right"), al("right"),
                         al("right"), al("right"), al("right"),
                         al("center"), al("right"), al("right")],
                 height=18)
        for ci in [7, 8, 10, 14]:
            ws4.cell(row=r_i, column=ci).number_format = '#,##0'
        dt = c_["dealTag"]
        ws4.cell(row=r_i, column=6).font = mk(
            size=9, bold=True,
            color=C_ORANGE if dt == "已成案" else C_GRAY
        )
        if am is not None:
            net = c_["netMarginPct"]
            ws4.cell(row=r_i, column=13).font = mk(
                size=9, bold=True,
                color=C_GREEN if am >= (net or 0) else C_RED
            )

    # ── Sheet 5: 業務員績效 ──────────────────────────────────────────────────
    ws5 = wb.create_sheet("業務員績效")
    ws5.sheet_view.showGridLines = False
    hdrs5 = ["業務員","案件數","合約總額","已收款","收款率(%)","平均預估毛利率","平均實際毛利率","精算件數"]
    cols5 = [16, 9, 16, 16, 11, 14, 14, 9]
    for i, (h, w) in enumerate(zip(hdrs5, cols5), 1):
        ws5.column_dimensions[get_column_letter(i)].width = w

    ws5.merge_cells(f"A1:{get_column_letter(len(hdrs5))}1")
    c = ws5["A1"]
    c.value = "業務員績效一覽"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill(C_BLUE)
    c.alignment = al("center")
    ws5.row_dimensions[1].height = 24

    _set_row(ws5, 2, hdrs5,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)

    for r_i, sp in enumerate(data["salesPerf"], 3):
        bg  = C_LGRAY if r_i % 2 == 0 else C_WHITE
        am  = sp["avgActualMarginPct"]
        est = sp["avgMarginPct"]
        _set_row(ws5, r_i,
                 [sp["salesPerson"], sp["caseCount"], sp["totalAmount"],
                  sp["receivedAmount"], f"{sp['collectionRate']:.1f}%",
                  f"{est:.1f}%",
                  f"{am:.1f}%" if am is not None else "—",
                  sp["settledCount"]],
                 font=mk(size=9), fill=fill(bg), border=BD,
                 aligns=[al("left"), al("right"), al("right"), al("right"),
                         al("right"), al("right"), al("right"), al("right")],
                 height=18)
        for ci in [3, 4]:
            ws5.cell(row=r_i, column=ci).number_format = '#,##0'
        if am is not None:
            ws5.cell(row=r_i, column=7).font = mk(
                size=9, bold=True,
                color=C_GREEN if am >= est else C_RED
            )

    # total row
    sr5 = len(data["salesPerf"]) + 3
    tt5 = sum(x["totalAmount"] for x in data["salesPerf"])
    tr5 = sum(x["receivedAmount"] for x in data["salesPerf"])
    ts5 = sum(x["settledCount"] for x in data["salesPerf"])
    _set_row(ws5, sr5,
             ["合計", sum(x["caseCount"] for x in data["salesPerf"]),
              tt5, tr5,
              f"{round(tr5/tt5*100,1) if tt5 else 0}%", "", "", ts5],
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill(C_DARK), border=BD,
             aligns=[al("left"), al("right"), al("right"), al("right"),
                     al("right"), al("right"), al("right"), al("right")],
             height=20)
    for ci in [3, 4]:
        ws5.cell(row=sr5, column=ci).number_format = '#,##0'

    # ── Sheet 6: 毛利分析 ────────────────────────────────────────────────────
    ws6 = wb.create_sheet("毛利分析")
    ws6.sheet_view.showGridLines = False
    hdrs6 = ["案件號","客戶","專案名稱","業務員","案件進度",
             "報價稅前","預估毛利率","實際毛利率","差異(pp)","實際毛利","精算狀態"]
    cols6 = [13, 18, 18, 10, 9, 13, 11, 11, 9, 13, 9]
    for i, (h, w) in enumerate(zip(hdrs6, cols6), 1):
        ws6.column_dimensions[get_column_letter(i)].width = w

    ws6.merge_cells(f"A1:{get_column_letter(len(hdrs6))}1")
    c = ws6["A1"]
    c.value = "毛利分析（已精算案件）"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill("7C3AED")
    c.alignment = al("center")
    ws6.row_dimensions[1].height = 24

    _set_row(ws6, 2, hdrs6,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)

    for r_i, mc in enumerate(data["marginCases"], 3):
        net = mc["netMarginPct"] or 0
        act = mc["actualMarginPct"] or 0
        diff = round(act - net, 1)
        bg = C_LGREEN if diff >= 0 else C_LRED
        _set_row(ws6, r_i,
                 [mc["quoteNo"], mc["customer"], mc["project"], mc["salesPerson"],
                  mc["dealTag"], mc["pretax"],
                  f"{net:.1f}%", f"{act:.1f}%",
                  f"{'+' if diff >= 0 else ''}{diff:.1f}",
                  mc["grossProfit"] or 0,
                  mc["settleStatus"] or ""],
                 font=mk(size=9), fill=fill(bg), border=BD,
                 aligns=[al("left"), al("left"), al("left"), al("left"), al("center"),
                         al("right"), al("right"), al("right"), al("right"),
                         al("right"), al("center")],
                 height=18)
        ws6.cell(row=r_i, column=6).number_format = '#,##0'
        ws6.cell(row=r_i, column=10).number_format = '#,##0'
        ws6.cell(row=r_i, column=9).font = mk(
            bold=True, size=9, color=C_GREEN if diff >= 0 else C_RED
        )
        ws6.cell(row=r_i, column=8).font = mk(
            bold=True, size=9, color=C_GREEN if act >= net else C_RED
        )

    if not data["marginCases"]:
        ws6.cell(row=3, column=1).value = "（目前尚無已完成精算之案件）"
        ws6.cell(row=3, column=1).font = mk(size=9, color=C_GRAY, italic=True)

    # ── Sheet 7: 保固到期預警 ────────────────────────────────────────────────
    ws7 = wb.create_sheet("保固到期預警")
    ws7.sheet_view.showGridLines = False
    hdrs7 = ["案件號","客戶","專案名稱","設備名稱","序號SN","MAC","到期日","剩餘天數","狀態"]
    cols7 = [13, 18, 18, 16, 16, 16, 11, 10, 8]
    for i, (h, w) in enumerate(zip(hdrs7, cols7), 1):
        ws7.column_dimensions[get_column_letter(i)].width = w

    ws7.merge_cells(f"A1:{get_column_letter(len(hdrs7))}1")
    c = ws7["A1"]
    c.value = f"保固到期預警（90 天內，共 {len(data['warranty'])} 筆）"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill(C_ORANGE)
    c.alignment = al("center")
    ws7.row_dimensions[1].height = 24

    _set_row(ws7, 2, hdrs7,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)

    for r_i, w_ in enumerate(data["warranty"], 3):
        dl = w_["daysLeft"]
        if dl < 0:
            bg, status = C_LRED, "已過期"
        elif dl <= 30:
            bg, status = C_LYELLOW, "30天內"
        else:
            bg, status = C_WHITE, "警示"
        _set_row(ws7, r_i,
                 [w_["quoteNo"], w_["customer"], w_["project"],
                  w_["device"], w_["sn"], w_["mac"],
                  w_["expiry"], dl, status],
                 font=mk(size=9), fill=fill(bg), border=BD,
                 aligns=[al("left"), al("left"), al("left"), al("left"),
                         al("left"), al("left"), al("center"), al("right"), al("center")],
                 height=18)
        status_cell = ws7.cell(row=r_i, column=9)
        status_cell.font = mk(bold=True, size=9,
                               color=C_RED if dl < 0 else C_ORANGE if dl <= 30 else C_GRAY)

    if not data["warranty"]:
        ws7.cell(row=3, column=1).value = "目前 90 天內無保固到期設備"
        ws7.cell(row=3, column=1).font  = mk(size=9, color=C_GREEN, italic=True)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ── PDF HTML builder ──────────────────────────────────────────────────────────

def _build_report_html(data: dict, period_label: str, gen_at: str) -> str:
    s = data["summary"]

    def tbl_hdr(*cols):
        return "<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"

    def fmt(n):
        return f"NT$ {int(n or 0):,}"

    def pct_span(v, target=None):
        if target is None:
            return f'<span class="val">{v:.1f}%</span>'
        color = "green" if v >= target else "red"
        arr = "▲" if v >= target else "▼"
        return f'<span style="color:{color};font-weight:700">{arr} {v:.1f}%</span>'

    # period items rows
    pi_rows = ""
    for it in data["periodItems"]:
        aa  = it["actualAmount"]
        aa_v = aa if aa is not None else it["amount"]
        pi_rows += (
            f"<tr><td>{it['quoteNo']}</td><td>{it['customer']}</td>"
            f"<td>{it['project']}</td><td>{it['salesPerson']}</td>"
            f"<td class='c'>{it['type']}</td>"
            f"<td class='r'>NT$ {it['amount']:,}</td>"
            f"<td class='c'>{it['receivedAt']}</td>"
            f"<td class='r'>NT$ {aa_v:,}</td>"
            "<td class='r fee'>" + (f"NT$ {int(it['feeAmount']):,}" if it['feeAmount'] else "—") + "</td>"
            f"<td class='r net'>NT$ {int(it['netAmount'] or aa_v):,}</td>"
            f"<td>{it['invoiceNo'] or '—'}</td></tr>"
        )

    # outstanding rows
    os_rows = ""
    for it in data["outstanding"]:
        os_rows += (
            f"<tr><td>{it['quoteNo']}</td><td>{it['customer']}</td>"
            f"<td>{it['project']}</td><td>{it['salesPerson']}</td>"
            f"<td class='c'>{it['dealTag']}</td><td class='c'>{it['type']}</td>"
            f"<td class='r red'>NT$ {it['amount']:,}</td>"
            f"<td class='c'>{it['pct']:.1f}%</td></tr>"
        )

    # case rows
    case_rows = ""
    for c in data["casesAll"]:
        am = c["actualMarginPct"]
        diff = round((am or 0) - (c["netMarginPct"] or 0), 1) if am is not None else None
        in_p_cls = ' class="in-period"' if c["inPeriod"] else ""
        case_rows += (
            f"<tr{in_p_cls}><td>{c['quoteNo']}</td><td>{c['customer']}</td>"
            f"<td>{c['project']}</td><td>{c['salesPerson']}</td>"
            f"<td class='c'>{c['quoteDate']}</td><td class='c tag'>{c['dealTag']}</td>"
            f"<td class='r'>NT$ {c['total']:,}</td>"
            f"<td class='r'>{c['netMarginPct']:.1f}%</td>"
            "<td class='r " + ("green" if c["collectionRate"] >= 80 else "orange") + f"'>{c['collectionRate']:.1f}%</td>"
            "<td class='c'>" + ((("▲" if diff >= 0 else "▼") + str(abs(diff)) + "%") if diff is not None else "—") + "</td></tr>"
        )

    # sales rows
    sp_rows = ""
    for sp in data["salesPerf"]:
        am  = sp["avgActualMarginPct"]
        est = sp["avgMarginPct"]
        am_cls = "green" if (am is not None and am >= est) else ("red" if am is not None else "")
        am_str = f"{am:.1f}%" if am is not None else "—"
        sp_rows += (
            f"<tr><td>{sp['salesPerson']}</td><td class='r'>{sp['caseCount']}</td>"
            f"<td class='r'>NT$ {sp['totalAmount']:,}</td>"
            f"<td class='r'>NT$ {sp['receivedAmount']:,}</td>"
            f"<td class='r'>{sp['collectionRate']:.1f}%</td>"
            f"<td class='r'>{est:.1f}%</td>"
            f"<td class='r {am_cls}'><b>{am_str}</b></td>"
            f"<td class='r'>{sp['settledCount']}</td></tr>"
        )

    # warranty rows
    ww_rows = ""
    for w in data["warranty"]:
        dl = w["daysLeft"]
        cls = "red" if dl < 0 else "orange" if dl <= 30 else ""
        ww_rows += (
            f"<tr><td>{w['quoteNo']}</td><td>{w['customer']}</td>"
            f"<td>{w['device']}</td><td>{w['sn']}</td>"
            f"<td class='c'>{w['expiry']}</td>"
            f"<td class='r {cls}'>{dl} 天</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="UTF-8">
<title>營運報表 {period_label}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Microsoft JhengHei','微軟正黑體',sans-serif;font-size:9pt;color:#111;background:#fff}}
@page{{size:A4 landscape;margin:10mm 12mm}}
.page-break{{page-break-before:always}}
h1{{font-size:16pt;color:#fff;background:#111827;padding:10px 16px;margin-bottom:0}}
.sub{{font-size:8pt;color:#9CA3AF;background:#111827;padding:4px 16px 8px}}
.section-title{{font-size:11pt;font-weight:700;color:#fff;padding:6px 10px;margin:14px 0 6px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}}
.kpi{{border:1px solid #E5E7EB;border-radius:6px;padding:10px 14px;background:#F9FAFB}}
.kpi-label{{font-size:7.5pt;color:#6B7280;margin-bottom:3px}}
.kpi-val{{font-size:14pt;font-weight:700}}
.kpi-sub{{font-size:7pt;color:#6B7280;margin-top:2px}}
.green{{color:#15803D}}.red{{color:#DC2626}}.orange{{color:#D97706}}.blue{{color:#2563EB}}
table{{width:100%;border-collapse:collapse;margin:0 0 12px;font-size:8pt}}
th{{background:#374151;color:#fff;padding:5px 7px;text-align:left;font-size:7.5pt;white-space:nowrap}}
td{{padding:4px 7px;border-bottom:1px solid #F0F0F0;vertical-align:middle}}
tr:nth-child(even){{background:#F9FAFB}}
tr:hover{{background:#F0F9FF}}
tr.in-period{{background:#EFF6FF}}
.r{{text-align:right}}.c{{text-align:center}}
.fee{{color:#DC2626}}.net{{color:#15803D;font-weight:700}}.tag{{font-weight:700}}
.sum-row{{background:#111827!important;color:#fff;font-weight:700}}
.sum-row td{{border:none}}
.footer{{font-size:7pt;color:#9CA3AF;text-align:center;margin-top:8px;border-top:1px solid #E5E7EB;padding-top:6px}}
</style></head><body>

<h1>{_COMPANY} 營運報表</h1>
<div class="sub">{_COMPANY2} ｜ 期間：{period_label} ｜ 產製：{gen_at}</div>

<!-- 摘要 -->
<div class="section-title" style="background:#1F2937">執行摘要 (Executive Summary)</div>
<div class="kpi-grid">
  <div class="kpi"><div class="kpi-label">總應收金額</div><div class="kpi-val">{fmt(s["totalReceivable"])}</div></div>
  <div class="kpi"><div class="kpi-label">已收款（帳面）</div><div class="kpi-val green">{fmt(s["totalCollected"])}</div><div class="kpi-sub">收款率 {s["collectionRate"]}%</div></div>
  <div class="kpi"><div class="kpi-label">未收款</div><div class="kpi-val red">{fmt(s["totalOutstanding"])}</div></div>
  <div class="kpi"><div class="kpi-label">手續費合計</div><div class="kpi-val orange">{fmt(s["totalFee"])}</div></div>
  <div class="kpi"><div class="kpi-label">實收淨額</div><div class="kpi-val green">{fmt(s["netCollected"])}</div></div>
  <div class="kpi"><div class="kpi-label">本期新收款</div><div class="kpi-val blue">{fmt(s["periodReceived"])}</div><div class="kpi-sub">淨 {fmt(s["periodNet"])}</div></div>
  <div class="kpi"><div class="kpi-label">合約總案數</div><div class="kpi-val">{s["totalCases"]}</div><div class="kpi-sub">進行中 {s["activeCases"]}　已結案 {s["closedCases"]}</div></div>
  <div class="kpi"><div class="kpi-label">本期新成案</div><div class="kpi-val blue">{s["periodCases"]}</div></div>
  <div class="kpi"><div class="kpi-label">保固到期預警</div><div class="kpi-val orange">{s["warrantyAlerts"]}</div><div class="kpi-sub">90 天內到期</div></div>
  <div class="kpi"><div class="kpi-label">精算實際毛利合計</div><div class="kpi-val" style="color:#7C3AED">{fmt(s["totalActualGrossProfit"])}</div><div class="kpi-sub">已精算 {s["settledCases"]} 件</div></div>
  <div class="kpi"><div class="kpi-label">精算覆蓋率</div><div class="kpi-val" style="color:#7C3AED">{s["settleCoverage"]}%</div><div class="kpi-sub">已結案 {s["closedCases"]} 件中 {s["settledCases"]} 件完成精算</div></div>
</div>

<!-- 本期收款 -->
<div class="page-break"></div>
<div class="section-title" style="background:#15803D">本期收款明細</div>
<table>
<thead>{tbl_hdr("案件號","客戶","專案","業務員","款項","應收金額","收款日","實收金額","手續費","實收淨額","發票號碼")}</thead>
<tbody>{pi_rows}</tbody>
<tr class="sum-row">
  <td colspan="5">合計（{len(data["periodItems"])} 筆）</td>
  <td class="r">NT$ {sum(i["amount"] for i in data["periodItems"]):,}</td>
  <td></td>
  <td class="r">NT$ {sum((i["actualAmount"] if i["actualAmount"] is not None else i["amount"]) for i in data["periodItems"]):,}</td>
  <td class="r">NT$ {sum(i["feeAmount"] or 0 for i in data["periodItems"]):,}</td>
  <td class="r">NT$ {int(s["periodNet"]):,}</td>
  <td></td>
</tr>
</table>

<!-- 未收款 -->
<div class="section-title" style="background:#DC2626">未收款清單（共 {len(data["outstanding"])} 筆）</div>
<table>
<thead>{tbl_hdr("案件號","客戶","專案","業務員","案件進度","款項類型","應收金額","比例")}</thead>
<tbody>{os_rows}</tbody>
<tr class="sum-row">
  <td colspan="6">合計</td>
  <td class="r">NT$ {sum(i["amount"] for i in data["outstanding"]):,}</td><td></td>
</tr>
</table>

<!-- 案件清單 -->
<div class="page-break"></div>
<div class="section-title" style="background:#1F2937">案件清單（本期新成案以藍色標示）</div>
<table>
<thead>{tbl_hdr("案件號","客戶","專案","業務員","報價日","進度","合約金額","預估毛利率","收款率","實際毛利率(▲▼)")}</thead>
<tbody>{case_rows}</tbody>
</table>

<!-- 業務員績效 -->
<div class="section-title" style="background:#2563EB">業務員績效</div>
<table>
<thead>{tbl_hdr("業務員","案件數","合約總額","已收款","收款率","平均預估毛利率","平均實際毛利率","精算件數")}</thead>
<tbody>{sp_rows}</tbody>
</table>

<!-- 保固預警 -->
<div class="page-break"></div>
<div class="section-title" style="background:#D97706">保固到期預警（90 天內）</div>
<table>
<thead>{tbl_hdr("案件號","客戶","設備名稱","序號 SN","到期日","剩餘天數")}</thead>
<tbody>{ww_rows or '<tr><td colspan="6" class="c" style="color:#6B7280;padding:10px">目前 90 天內無保固到期設備</td></tr>'}</tbody>
</table>

<div class="footer">{_COMPANY} — 此報表由 MOTRIX ERP 系統自動產製，僅供內部管理參考 ｜ {gen_at}</div>
</body></html>"""
    return html


def _html_to_pdf(html: str) -> bytes:
    edge = _get_edge_path()
    tmp_html = tmp_pdf = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", encoding="utf-8", delete=False) as f:
            f.write(html)
            tmp_html = f.name
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_pdf = f.name
        subprocess.run(
            [edge, "--headless", "--disable-gpu", "--no-sandbox",
             f"--print-to-pdf={tmp_pdf}", "--no-pdf-header-footer",
             "--run-all-compositor-stages-before-draw",
             "file:///" + tmp_html.replace("\\", "/")],
            timeout=60, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        with open(tmp_pdf, "rb") as f:
            data = f.read()
        if not data:
            raise ValueError("Edge 輸出為空")
        return data
    finally:
        for p in [tmp_html, tmp_pdf]:
            if p:
                try: os.unlink(p)
                except Exception: pass


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/api/reports/financial")
def report_json(
    period: Optional[str] = Query(None),
    authorization: str = Header(None),
):
    u = _require_user(authorization)
    if u["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可存取報表")
    label, d0, d1 = _parse_period(period)
    data = _collect(d0, d1)
    return {"period": period, "periodLabel": label, "dateStart": d0, "dateEnd": d1, **data}


@router.get("/api/reports/financial/excel")
def report_excel(
    period: Optional[str] = Query(None),
    authorization: str = Header(None),
):
    u = _require_user(authorization)
    if u["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可存取報表")
    label, d0, d1 = _parse_period(period)
    data   = _collect(d0, d1)
    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    xlsx   = _build_excel(data, label, gen_at)
    safe   = label.replace(" ", "").replace("年", "Y").replace("月", "M").replace("第", "Q").replace("季", "")
    fname  = f"MOTRIX_營運報表_{safe}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_url_quote(fname)}"},
    )


@router.get("/api/reports/financial/pdf")
def report_pdf(
    period: Optional[str] = Query(None),
    authorization: str = Header(None),
):
    u = _require_user(authorization)
    if u["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可存取報表")
    label, d0, d1 = _parse_period(period)
    data   = _collect(d0, d1)
    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        pdf_bytes = _html_to_pdf(_build_report_html(data, label, gen_at))
    except ValueError as e:
        raise HTTPException(500, str(e))
    safe  = label.replace(" ", "").replace("年", "Y").replace("月", "M").replace("第", "Q").replace("季", "")
    fname = f"MOTRIX_營運報表_{safe}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_url_quote(fname)}"},
    )
