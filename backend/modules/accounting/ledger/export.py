# -*- coding: utf-8 -*-
"""決算報表匯出（B5）：四大表 Excel（一個表一個工作表）。年度已決算 ⇒ 匯出當時凍結的快照（之後帳怎麼動這份都不變）。
文字一律經 `xl_safe`（防公式注入）；空值寫 None（不寫空字串：openpyxl 會產生非法 inlineStr）。
"""
import io
import json

from openpyxl import Workbook

from helpers.xlsx_out import set_row, xl_style


def year_statements(conn, year):
    """回 `(statements, source)`：年度 closed 且有凍結快照 ⇒ ('frozen')，否則即時計算 ('live')。"""
    from modules.accounting.ledger import closing as _closing
    y = _closing._year(conn, year)
    if y["status"] in ("closed", "locked"):
        row = conn.execute("SELECT payload_json FROM gl_statement_snapshots WHERE kind='year_close' AND fy=? ORDER BY id DESC LIMIT 1", (y["year"],)).fetchone()
        if row:
            return json.loads(row[0]), "frozen"
    return _closing._statements(conn, y), "live"


def _n(v):
    return None if v in ("", None) else v


def statements_workbook(stm, year, source="live", title="財務報表"):
    # 四大表抬頭含公司名 ⇒ 輸出點要經第二道（COMPANY-SETUP-GATE §5；未設定本公司資料 ⇒ 428）
    from helpers.company_identity import company_name
    company = company_name()
    if company:
        title = "%s　%s" % (company, title)
    wb = Workbook()
    f, fill, border, al = xl_style(wb)
    head_font, head_fill = f(bold=True, size=10), fill("F0EEE9")
    num = al("right")

    def sheet(name, rows, header):
        ws = wb.create_sheet(name)
        set_row(ws, 1, ["%s　%s 年度%s" % (title, year, "（決算凍結版）" if source == "frozen" else "（即時，未決算）")], font=f(bold=True, size=12))
        set_row(ws, 3, header, font=head_font, fill=head_fill, border=border())
        for i, r in enumerate(rows, start=4):
            set_row(ws, i, [_n(x) for x in r], font=f(), border=border(), aligns=[al("left")] + [num] * (len(r) - 1))
        ws.column_dimensions["A"].width = 38
        for col in "BCDEFGH":
            ws.column_dimensions[col].width = 16
        return ws

    wb.remove(wb.active)
    bs = stm["balance_sheet"]
    rows = []
    for title_, key in (("流動資產", "current_assets"), ("非流動資產", "noncurrent_assets"), ("流動負債", "current_liabilities"),
                        ("非流動負債", "noncurrent_liabilities"), ("權益", "equity")):
        sec = bs["sections"][key]
        rows.append([title_, None])
        rows += [["　" + i["label"], i["amount"]] for i in sec["items"]]
        rows.append([title_ + "合計", sec["total"]])
    rows += [["資產總計", bs["totals"]["assets"]], ["負債總計", bs["totals"]["liabilities"]], ["權益總計", bs["totals"]["equity"]],
             ["負債及權益總計", bs["totals"]["liabilities_and_equity"]]]
    sheet("資產負債表", rows, ["項目", bs["as_of"]])
    inc = stm["income_statement"]
    sheet("綜合損益表", [[l["label"], l["period"], l["ytd"]] for l in inc["lines"]], ["項目", "本期 %s～%s" % (inc["start"], inc["end"]), "年初至今"])
    eq = stm["equity_statement"]
    cols = [c["key"] for c in eq["columns"]]
    sheet("權益變動表", [[r["label"]] + [r["amounts"].get(k) for k in cols] for r in eq["rows"]], ["項目"] + [c["label"] for c in eq["columns"]])
    cf = stm["cash_flow"]
    rows = []
    for sec in cf["sections"]:
        rows.append([sec["title"], None])
        rows += [["　" + l["label"], l["amount"]] for l in sec["lines"]]
        rows.append([sec["title"] + "淨額", sec["total"]])
    rows += [["本期現金及約當現金淨變動", cf["net_change"]], ["期初現金及約當現金", cf["cash_opening"]], ["期末現金及約當現金", cf["cash_closing"]]]
    sheet("現金流量表", rows, ["項目", "%s～%s" % (cf["start"], cf["end"])])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
