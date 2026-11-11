# -*- coding: utf-8 -*-
"""參數化報表範本（T79 候選，客戶需求缺口「自助報表」第一階段）。

使用者**不自訂版面**：範本由程式登記（id、參數、欄位目錄、產出函式），使用者只選條件（日期區間、部門、案件狀態…），
系統套用範本重新查詢產出，可在畫面看或下載 Excel。

不變式：
* **金額不重算**：範本只對 `reports._collect()`／`_collect_receivable_items()` 既有結果做篩選與欄位投影；
  業務員彙總走 `reports._sales_perf_rows()`（與營運報表同一份）。不產生第二套金額定義。
* 參數一律伺服器端驗證：未知參數 400、日期格式與先後、部門須存在、列舉值須在白名單。
* 權限沿用 `reports._require_reports_access`（財務角色，或「營運報表」模組＋money_visible），與營運報表同一道門。
* 母體＝已成案／已結案（`_collect` 的母體）；報價中等狀態需直查 quotations＋逐案權限，列第二批。
* 欄位目錄是宣告式資料（`columns`），日後自訂欄位可直接加進目錄。
* 不靜默截斷：超過 MAX_ROWS 時回 `truncated` 並在 notes 說明；未標日期的款項在有日期條件時被排除，也明說筆數。
"""
import io
import re
from datetime import date, datetime
from typing import Callable, Optional

import openpyxl
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import Response

from db import get_db
from helpers import _require_user, download_name
from helpers.xlsx_out import add_pdf_sibling, check_export_rate, export_logged, set_row, xl_style

from modules.analytics.api import reports as _rp

router = APIRouter()

#: 匯出稽核的區域代號（不是權限 key；與 reports.py 的 _EXPORT_AREA 同值。用變數而非 module="…" 字面值，免得權限目錄守門把它當成後端權限 key）
_EXPORT_AREA = "analytics"

MAX_ROWS = 20000
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEXT_MAX = 40

DEAL_TAGS = (("已成案", "已成案"), ("已結案", "已結案"))
SETTLE_OPTIONS = (("finalized", "已精算"), ("pending", "未精算（含草稿）"))
PAID_OPTIONS = (("received", "已收"), ("unreceived", "未收"))


# ── 參數定義與驗證 ───────────────────────────────────────────────────────────

def _p(key, label, ptype, options=None, hint=""):
    return {"key": key, "label": label, "type": ptype, "options": options, "hint": hint}


P_DATE_FROM = lambda label="起": _p("date_from", label, "date")           # noqa: E731
P_DATE_TO = lambda label="迄": _p("date_to", label, "date")               # noqa: E731
P_DEPT = _p("department_id", "部門", "department")
P_DEAL = _p("deal_tag", "案件狀態", "enum", [list(x) for x in DEAL_TAGS])
P_SETTLE = _p("settle_status", "精算狀態", "enum", [list(x) for x in SETTLE_OPTIONS])
P_SALES = _p("sales_person", "業務（姓名關鍵字）", "text")
P_CUSTOMER = _p("customer", "客戶（名稱關鍵字）", "text")
P_PAID = _p("paid", "收款狀態", "enum", [list(x) for x in PAID_OPTIONS])


def _valid_dept_ids() -> set:
    conn = get_db()
    try:
        return {r[0] for r in conn.execute("SELECT id FROM departments")}
    finally:
        conn.close()


def department_options() -> list:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT d.id, d.name, v.name AS division FROM departments d "
            "LEFT JOIN divisions v ON v.id = d.division_id ORDER BY v.sort_order, d.sort_order, d.id").fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "label": ((r["division"] + " / ") if r["division"] else "") + r["name"]} for r in rows]


def validate_params(tpl: dict, raw: dict) -> dict:
    """raw（query string 的字串字典）→ 正規化參數；空字串視為未設。任何不合法一律 400。"""
    defs = {d["key"]: d for d in tpl["params"]}
    unknown = sorted(k for k in raw if k not in defs)
    if unknown:
        raise HTTPException(400, "此範本不支援的參數：" + "、".join(unknown))
    out: dict = {}
    for key, d in defs.items():
        v = raw.get(key)
        if v is None:
            continue
        v = str(v).strip()
        if v == "":
            continue
        t = d["type"]
        if t == "date":
            try:
                if not _DATE_RE.match(v):
                    raise ValueError
                date.fromisoformat(v)
            except ValueError:
                raise HTTPException(400, f"{d['label']}日期格式錯誤（需為 YYYY-MM-DD）：{v[:20]}")
        elif t == "department":
            try:
                n = int(v)
            except ValueError:
                raise HTTPException(400, "部門參數格式錯誤")
            if n not in _valid_dept_ids():
                raise HTTPException(400, "查無此部門")
            v = n
        elif t == "enum":
            if v not in {o[0] for o in d["options"]}:
                raise HTTPException(400, f"{d['label']}不是有效選項：{v[:20]}")
        elif t == "text":
            if len(v) > TEXT_MAX:
                raise HTTPException(400, f"{d['label']}過長（上限 {TEXT_MAX} 字）")
        out[key] = v
    if out.get("date_from") and out.get("date_to") and out["date_from"] > out["date_to"]:
        raise HTTPException(400, "日期區間的起日不可晚於迄日")
    return out


def _in_range(day: str, p: dict) -> bool:
    """day（YYYY-MM-DD 或空）是否落在 date_from~date_to（皆含）；沒設任何日期條件 ⇒ 一律 True；有條件而 day 空 ⇒ False。"""
    lo, hi = p.get("date_from"), p.get("date_to")
    if not lo and not hi:
        return True
    d = (day or "")[:10]
    if not d:
        return False
    return (not lo or d >= lo) and (not hi or d <= hi)


def _has_text(hay, needle) -> bool:
    return needle.casefold() in (hay or "").casefold()


# ── 案件母體（案件清單、業務員績效共用） ───────────────────────────────────────

def _filtered_cases(p: dict) -> list:
    data = _rp._collect("0000-01-01", "9999-12-31", p.get("department_id"))
    out = []
    for c in data["casesAll"]:
        if p.get("deal_tag") and c["dealTag"] != p["deal_tag"]:
            continue
        if p.get("settle_status") == "finalized" and c["settleStatus"] != "finalized":
            continue
        if p.get("settle_status") == "pending" and c["settleStatus"] == "finalized":
            continue
        if p.get("sales_person") and not _has_text(c["ownerName"], p["sales_person"]):
            continue
        if p.get("customer") and not _has_text(c["customer"], p["customer"]):
            continue
        if not _in_range(c["quoteDate"], p):
            continue
        out.append(c)
    return out


def _settle_text(c) -> str:
    return {"finalized": "已精算", "draft": "精算中"}.get(c["settleStatus"], "未精算")


# ── 範本一：案件清單 ─────────────────────────────────────────────────────────

def _run_case_list(p: dict, u: dict):
    cases = _filtered_cases(p)
    cases.sort(key=lambda c: (c["quoteDate"] or "", c["quoteNo"]), reverse=True)
    rows = [{
        "quoteNo": c["quoteNo"], "customer": c["customer"], "project": c["project"],
        "owner": c["ownerName"], "dept": c["deptName"], "quoteDate": (c["quoteDate"] or "")[:10],
        "dealTag": c["dealTag"], "total": c["total"], "received": c["receivedAmount"],
        "collectionRate": c["collectionRate"], "estMargin": c["netMarginPct"],
        "actualMargin": c["actualMarginPct"], "settle": _settle_text(c),
    } for c in cases]
    total = sum(c["total"] for c in cases)
    recv = sum(c["receivedAmount"] for c in cases)
    summary = [
        {"label": "案件數", "value": len(cases), "type": "count"},
        {"label": "合約總額", "value": total, "type": "money"},
        {"label": "已收款", "value": recv, "type": "money"},
        {"label": "收款率", "value": round(recv / total * 100, 1) if total > 0 else 0, "type": "pct"},
    ]
    notes = ["日期條件依「報價日」。業務欄為案件管理的「業務負責」（沒填才是開單者），與營運報表的業務員績效同一歸屬。"]
    no_pay = sum(1 for c in cases if not c["hasPaymentItems"])
    if no_pay:
        notes.append(f"其中 {no_pay} 件尚未填寫收款期別，合約金額不計入收款率。")
    return rows, summary, notes


# ── 範本二：收款明細 ─────────────────────────────────────────────────────────

def _run_payments(p: dict, u: dict):
    items = _rp._collect_receivable_items(p.get("department_id"))
    rows, undated = [], 0
    for it in items:
        if p.get("deal_tag") and it["dealTag"] != p["deal_tag"]:
            continue
        if p.get("paid") == "received" and not it["received"]:
            continue
        if p.get("paid") == "unreceived" and it["received"]:
            continue
        if p.get("customer") and not _has_text(it["customer"], p["customer"]):
            continue
        day = (it.get("receivedAt") if it["received"] else it.get("expectedReceiptDate")) or ""
        if (p.get("date_from") or p.get("date_to")) and not day[:10]:
            undated += 1
            continue
        if not _in_range(day, p):
            continue
        rows.append({
            "quoteNo": it["quoteNo"], "customer": it["customer"], "project": it["project"],
            "type": it["type"], "amount": it["amount"], "state": "已收" if it["received"] else "未收",
            "receivedAt": (it.get("receivedAt") or "")[:10], "expected": (it.get("expectedReceiptDate") or "")[:10],
            "actual": it["actualAmount"], "fee": it["feeAmount"], "net": it["netAmount"], "invoiceNo": it.get("invoiceNo") or "",
        })
    rows.sort(key=lambda r: (r["receivedAt"] or r["expected"] or "", r["quoteNo"]), reverse=True)
    recv = [r for r in rows if r["state"] == "已收"]
    summary = [
        {"label": "筆數", "value": len(rows), "type": "count"},
        {"label": "應收合計", "value": sum(r["amount"] for r in rows), "type": "money"},
        {"label": "已收（應收口徑）", "value": sum(r["amount"] for r in recv), "type": "money"},
        {"label": "未收", "value": sum(r["amount"] for r in rows if r["state"] == "未收"), "type": "money"},
    ]
    notes = ["日期條件：已收款項依「實收日」，未收款項依「預計收款日」。"]
    if undated:
        notes.append(f"有 {undated} 筆款項沒填對應日期（未收且無預計收款日），因為有日期條件所以未列入；不設日期條件即可看到。")
    return rows, summary, notes


# ── 範本三：業務員績效 ───────────────────────────────────────────────────────

def _run_sales_perf(p: dict, u: dict):
    cases = _filtered_cases(p)
    perf = _rp._sales_perf_rows(cases)
    rows = [{
        "owner": r["salesPerson"], "caseCount": r["caseCount"], "total": r["totalAmount"],
        "received": r["receivedAmount"], "collectionRate": r["collectionRate"],
        "estMargin": r["avgMarginPct"], "actualMargin": r["avgActualMarginPct"], "settled": r["settledCount"],
    } for r in perf]
    total = sum(r["total"] for r in rows)
    recv = sum(r["received"] for r in rows)
    summary = [
        {"label": "業務人數", "value": len(rows), "type": "count"},
        {"label": "案件數", "value": sum(r["caseCount"] for r in rows), "type": "count"},
        {"label": "合約總額", "value": total, "type": "money"},
        {"label": "收款率", "value": round(recv / total * 100, 1) if total > 0 else 0, "type": "pct"},
    ]
    notes = ["日期條件依「報價日」。歸屬與營運報表的業務員績效相同（案件管理的「業務負責」）。實際利益率只含已精算案件。"]
    return rows, summary, notes


def _col(key, label, ctype="text"):
    return {"key": key, "label": label, "type": ctype}


TEMPLATES: dict = {}


def _add_template(tid, title, desc, params, columns, run: Callable):
    TEMPLATES[tid] = {"id": tid, "title": title, "desc": desc, "params": params, "columns": columns, "run": run}


_add_template(
    "case-list", "案件清單", "依報價日、部門、案件狀態、業務、精算狀態、客戶挑出案件，看合約金額與收款。",
    [P_DATE_FROM("報價日 起"), P_DATE_TO("報價日 迄"), P_DEPT, P_DEAL, P_SALES, P_SETTLE, P_CUSTOMER],
    [_col("quoteNo", "案件號"), _col("customer", "客戶"), _col("project", "專案名稱"), _col("owner", "業務"),
     _col("dept", "部門"), _col("quoteDate", "報價日", "date"), _col("dealTag", "案件狀態"),
     _col("total", "合約金額", "money"), _col("received", "已收款", "money"), _col("collectionRate", "收款率", "pct"),
     _col("estMargin", "預估營業利益率", "pct"), _col("actualMargin", "實際營業利益率", "pct"), _col("settle", "精算")],
    _run_case_list)
_add_template(
    "payments", "收款明細", "逐筆款項：依日期區間、已收／未收、部門、客戶挑出，看應收、實收與手續費。",
    [P_DATE_FROM("日期 起"), P_DATE_TO("日期 迄"), P_PAID, P_DEPT, P_DEAL, P_CUSTOMER],
    [_col("quoteNo", "案件號"), _col("customer", "客戶"), _col("project", "專案名稱"), _col("type", "期別"),
     _col("amount", "應收金額", "money"), _col("state", "狀態"), _col("receivedAt", "實收日", "date"),
     _col("expected", "預計收款日", "date"), _col("actual", "實收金額", "money"), _col("fee", "手續費", "money"),
     _col("net", "入帳淨額", "money"), _col("invoiceNo", "發票號碼")],
    _run_payments)
_add_template(
    "sales-perf", "業務員績效", "依報價日、部門、案件狀態、精算狀態彙總每位業務的成案、收款與利益率。",
    [P_DATE_FROM("報價日 起"), P_DATE_TO("報價日 迄"), P_DEPT, P_DEAL, P_SETTLE],
    [_col("owner", "業務"), _col("caseCount", "案件數", "count"), _col("total", "合約金額", "money"),
     _col("received", "已收款", "money"), _col("collectionRate", "收款率", "pct"),
     _col("estMargin", "預估營業利益率", "pct"), _col("actualMargin", "實際營業利益率（已精算）", "pct"),
     _col("settled", "已精算件數", "count")],
    _run_sales_perf)


def _get(tid: str) -> dict:
    tpl = TEMPLATES.get(tid)
    if not tpl:
        raise HTTPException(404, "查無此報表範本")
    return tpl


def _raw_params(request: Request) -> dict:
    return {k: v for k, v in request.query_params.items()}


def _produce(tpl: dict, request: Request, u: dict) -> tuple:
    p = validate_params(tpl, _raw_params(request))
    rows, summary, notes = tpl["run"](p, u)
    truncated = len(rows) > MAX_ROWS
    if truncated:
        rows = rows[:MAX_ROWS]
        notes = notes + [f"結果超過 {MAX_ROWS} 列，只列出前 {MAX_ROWS} 列；請縮小條件。"]
    return u, p, rows, summary, notes, truncated


@router.get("/api/report-templates")
def list_templates(authorization: str = Header(None)):
    u = _require_user(authorization)
    _rp._require_reports_access(u)
    dept = department_options()
    out = []
    for t in TEMPLATES.values():
        params = []
        for d in t["params"]:
            d = dict(d)
            if d["type"] == "department":
                d["options"] = [[o["id"], o["label"]] for o in dept]
            params.append(d)
        out.append({"id": t["id"], "title": t["title"], "desc": t["desc"], "params": params, "columns": t["columns"]})
    return {"templates": out, "maxRows": MAX_ROWS}


@router.get("/api/report-templates/{tid}/run")
def run_template(tid: str, request: Request, authorization: str = Header(None)):
    u = _require_user(authorization)
    _rp._require_reports_access(u)
    tpl = _get(tid)
    _u, p, rows, summary, notes, truncated = _produce(tpl, request, u)
    return {"id": tid, "title": tpl["title"], "params": p, "columns": tpl["columns"], "rows": rows,
            "summary": summary, "notes": notes, "truncated": truncated,
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _fmt_param(tpl: dict, p: dict) -> list:
    out = []
    dept = {o["id"]: o["label"] for o in department_options()}
    for d in tpl["params"]:
        v = p.get(d["key"])
        if v is None:
            shown = "（全部）"
        elif d["type"] == "department":
            shown = dept.get(v, str(v))
        elif d["type"] == "enum":
            shown = dict((o[0], o[1]) for o in d["options"]).get(v, v)
        else:
            shown = v
        out.append((d["label"], shown))
    return out


# 條件在簽名上明列（值不在這裡用）：讓 export_logged 把條件寫進匯出稽核、OpenAPI／路由登記簿也看得到；
# 真正的驗證與「未知參數 400」仍走 validate_params（讀 request.query_params）。
@router.get("/api/report-templates/{tid}/excel")
@export_logged("xlsx", _EXPORT_AREA, "report-template")
def excel_template(tid: str, request: Request, authorization: str = Header(None),
                   date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
                   department_id: Optional[str] = Query(None), deal_tag: Optional[str] = Query(None),
                   settle_status: Optional[str] = Query(None), sales_person: Optional[str] = Query(None),
                   customer: Optional[str] = Query(None), paid: Optional[str] = Query(None)):
    u = _require_user(authorization)
    _rp._require_reports_access(u)
    tpl = _get(tid)
    check_export_rate(u["id"], "excel")
    _u, p, rows, summary, notes, truncated = _produce(tpl, request, u)
    wb = openpyxl.Workbook()
    f = xl_style(wb)[0]
    ws = wb.active
    ws.title = "報表"[:31]
    cols = tpl["columns"]
    set_row(ws, 1, [c["label"] for c in cols], font=f(bold=True, size=10))
    for ri, r in enumerate(rows, 2):
        vals = [r.get(c["key"]) for c in cols]
        set_row(ws, ri, vals, font=f(size=10))
        for ci, c in enumerate(cols, 1):
            if c["type"] == "money":
                ws.cell(row=ri, column=ci).number_format = "#,##0"
            elif c["type"] == "pct":
                ws.cell(row=ri, column=ci).number_format = '0.0"%"'
    for ci, c in enumerate(cols, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = max(10, min(40, len(c["label"]) * 2 + 4))
    ws.freeze_panes = "A2"
    w2 = wb.create_sheet("條件")
    r0 = 1
    set_row(w2, r0, [tpl["title"], "產出時間 " + datetime.now().strftime("%Y-%m-%d %H:%M")], font=f(bold=True, size=11))
    r0 += 2
    set_row(w2, r0, ["條件", "值"], font=f(bold=True, size=10))
    for lbl, val in _fmt_param(tpl, p):
        r0 += 1
        set_row(w2, r0, [lbl, val], font=f(size=10))
    r0 += 2
    set_row(w2, r0, ["彙總", "值"], font=f(bold=True, size=10))
    for s in summary:
        r0 += 1
        set_row(w2, r0, [s["label"], s["value"]], font=f(size=10))
    r0 += 2
    for n in notes:
        set_row(w2, r0, [n], font=f(size=9, italic=True))
        r0 += 1
    w2.column_dimensions["A"].width = 28
    w2.column_dimensions["B"].width = 36
    buf = io.BytesIO()
    wb.save(buf)
    fname = f"MOTRIX_{tpl['title']}_{date.today().isoformat()}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": download_name.content_disposition(fname)},
    )


# 平台規則：每支 xlsx 匯出都有 PDF 姊妹（同處理函式、同權限、同資料），要列印時用
add_pdf_sibling(router, "/api/report-templates/{tid}/pdf", excel_template, module=_EXPORT_AREA, name="report-template",
                title="自選條件報表")
