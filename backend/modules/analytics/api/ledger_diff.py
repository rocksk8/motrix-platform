# -*- coding: utf-8 -*-
"""『與總帳差異』（MONEY-FLOWS §9 L4，主持 2026-09-30）：逐月、逐類別，營運報表 vs 總帳已過帳金額，差額＋原因分桶。**唯讀**。

`GET /api/reports/ledger-diff?year=&basis=cash|accrual`。營運報表那邊直接用報表自己的收集函式（同一份數字）；總帳那邊經提供者
`ledger.month_totals`（accounting；L2 不互相 import）。總帳模組不在 ⇒ `available:false` 並說明，不是 0。

**原因分桶**（對「報表 − 總帳已過帳」差額的貢獻，可正可負；算不出來的歸 `residual`，並在 `notes` 列出已知的口徑差異）：
- `unposted`＝總帳引擎草稿（未過帳）——報表已計、總帳尚未過帳（差額為正）
- `tax`＝現金口徑報表含稅、總帳不含稅（收入差＝已過帳銷項稅額；支出差＝已過帳進項稅額）；權責口徑為 0
- `manual`＝手工傳票已過帳的收入／費用——總帳有、報表沒有（差額為負）
- `bonus`＝獎金模組傳票已過帳的費用（報表的『其他』已含獎金發放；這裡列出讓差額可對）
- `residual`＝其餘（時點／口徑：差額待審核、送審中額外支出、權責含草稿派工、進貨採購日 vs 出貨成本、報廢…，見 MONEY-FLOWS §9.3 L4）
另附 `pendingEvents`（drift／orphan／blocked 事件數，來源已變動待處理）。"""
from datetime import date

from fastapi import APIRouter, Header, HTTPException, Query

from core import registry as _registry
from helpers import _require_user
from helpers.financial_mask import money_visible
from helpers.recognition_basis import DEFAULT_BASIS, normalize_basis
from modules.analytics.api import reports as R

router = APIRouter()

_CATS = ("contractor", "equipment", "material", "other")
_CAT_LABEL = {"contractor": "承攬商", "equipment": "設備", "material": "料件", "other": "其他"}
#: 總帳傳票來源（`vouchers_all.origin`，引擎＝`gl:<事件碼>`）⇒ 報表支出類別；沒列的一律歸「其他」（E06 勞報單、E07 獎金、E11 額外支出…）
_ORIGIN_CAT = {"gl:E04": "contractor", "gl:E05": "contractor", "gl:E05b": "contractor", "gl:E10": "material", "gl:E12": "material",
               "gl:E12b": "material", "gl:E08": "equipment"}
NOTES = [
    "報表與總帳本來就有口徑差異：差額待審核（報表現金已用實付、總帳核可後才入帳）、額外支出送審中（報表計入、總帳要已核准）、"
    "權責口徑含草稿派工（總帳要驗收＋發票日）、進貨以採購日計費用（總帳進貨為存貨，費用在出貨成本）、進貨報廢（報表少、總帳存貨不減）。",
    "尚未接總帳的來源不會出現在總帳欄：自訂模組金額欄（E20／E21 排程中）等；見 MONEY-FLOWS §2。",
    "差額原因分桶只算在每月的收入／支出合計；類別（承攬商／設備／料件／其他）只有報表、總帳、差額，沒有分桶："
    "例如承攬商類別的差額含稅額（進項稅）與個人外包（總帳歸『其他』），要對照合計的原因說明，不能把類別差額當成單一原因。",
    "總帳引擎只能手動執行：來源剛改過、尚未執行引擎時，報表已變而總帳還沒變（『未入帳草稿』與『待處理事件』會顯示）。",
]


def _month_income(basis, y, m):
    a = "%04d-%02d-01" % (y, m)
    b = "%04d-%02d-31" % (y, m)
    if basis == "accrual":
        rec = R._recognition()
        if rec is None:
            return 0, "權責收入：案件管理模組不在，沒有資料來源"
        conn = R.get_db()
        try:
            items = rec.accrual_income_items(conn, a, b, None)
        finally:
            conn.close()
    else:
        items = R._collect_income_items(a, b, None)
    return round(sum(float(i.get("amount") or 0) for i in items)), ""


def build(year, basis):
    basis = normalize_basis(basis)
    prov = _registry.providers("ledger.month_totals").get("accounting")
    if prov:
        conn = R.get_db()
        try:
            gl = prov(conn, year)
        finally:
            conn.close()
    else:
        gl = {"available": False, "notice": "會計模組未安裝，沒有總帳可比對"}
    exp = {x["month"]: x for x in R._collect_expenses(year, None, basis)["monthly"]}          # 報表的 monthly 是清單（每月一筆）
    rows, income_notice = [], ""
    totals = {"income": {"report": 0, "gl": 0}, "expense": {"report": 0, "gl": 0}}
    for m in range(1, 13):
        mo = "%04d-%02d" % (year, m)
        inc, n = _month_income(basis, year, m)
        income_notice = income_notice or n
        rep_exp = {c: round(float((exp.get(mo) or {}).get(c) or 0)) for c in _CATS}
        row = {"month": mo, "income": {"report": inc}, "expense": {"report": sum(rep_exp.values()), "categories": {
            c: {"label": _CAT_LABEL[c], "report": rep_exp[c]} for c in _CATS}}}
        if gl.get("available"):
            g = (gl["months"].get(mo) or {})
            z = {"revenue": 0, "expense": 0, "tax_out": 0, "tax_in": 0}
            ep, eu, bo, mp = (g.get("engine_posted") or z), (g.get("engine_unposted") or z), (g.get("bonus_posted") or z), (g.get("manual_posted") or z)
            gl_rev = ep["revenue"] + bo["revenue"] + mp["revenue"]
            gl_exp = ep["expense"] + bo["expense"] + mp["expense"]
            cash = basis == "cash"
            i_b = {"unposted": eu["revenue"], "tax": ep["tax_out"] if cash else 0, "manual": -mp["revenue"], "bonus": -bo["revenue"]}
            e_b = {"unposted": eu["expense"], "tax": ep["tax_in"] if cash else 0, "manual": -mp["expense"], "bonus": -bo["expense"]}
            row["income"].update({"gl": gl_rev, "diff": inc - gl_rev, "buckets": dict(i_b, residual=inc - gl_rev - sum(i_b.values()))})
            row["expense"].update({"gl": gl_exp, "diff": row["expense"]["report"] - gl_exp,
                                   "buckets": dict(e_b, residual=row["expense"]["report"] - gl_exp - sum(e_b.values()))})
            by_cat = {c: 0 for c in _CATS}
            for origin, amt in (g.get("by_origin_posted") or {}).items():
                by_cat[_ORIGIN_CAT.get(origin, "other")] += int(amt)
            for c in _CATS:
                row["expense"]["categories"][c].update({"gl": by_cat[c], "diff": rep_exp[c] - by_cat[c]})
            row["pendingEvents"] = (gl.get("events") or {}).get(mo) or {"drift": 0, "orphan": 0, "blocked": 0}
            totals["income"]["gl"] += gl_rev
            totals["expense"]["gl"] += gl_exp
        totals["income"]["report"] += inc
        totals["expense"]["report"] += row["expense"]["report"]
        rows.append(row)
    for k in ("income", "expense"):
        totals[k]["diff"] = totals[k]["report"] - totals[k]["gl"] if gl.get("available") else None
    return {"year": year, "basis": basis, "glAvailable": bool(gl.get("available")), "glNotice": gl.get("notice", ""),
            "incomeNotice": income_notice, "months": rows, "totals": totals, "notes": NOTES}


@router.get("/api/reports/ledger-diff")
def report_ledger_diff(year: int = Query(None), basis: str = Query(None), authorization: str = Header(None)):
    u = _require_user(authorization)
    R._require_reports_access(u)
    if not money_visible(u):
        raise HTTPException(403, "此帳號沒有財務檢視權限")
    year = year or date.today().year
    if not (1990 <= year <= 2200):
        raise HTTPException(400, "year 超出範圍")
    return build(year, basis or DEFAULT_BASIS)
