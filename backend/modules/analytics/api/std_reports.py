# -*- coding: utf-8 -*-
"""T87 B1「標準報表」後端：營收、毛利、應收帳齡、案件進度、業務漏斗五張報表，共用一組篩選條件與同一套 Excel／PDF 匯出。

設計：D:\\Claude-pm\\t87-design\\B1-reports.md；線上格式：B1-api-contract.md（與前端 h10 對齊）。

不變式：
* **金額不重算**：營收、毛利取 `reports._collect()`／`_collect_income_items`／`case.recognition`；帳齡取
  `reports._ar_aging_core`（`_compute_ar_aging` 的實作，加可選篩選，預設輸出不變）；報價漏斗分類取
  `dashboard.classify_quote_funnel`（首頁漏斗同一份）。本檔只做篩選與欄位投影、加權平均與計數。
* **閘門**：營收、毛利、帳齡＝`reports._require_reports_access`（不改）；案件進度、業務漏斗是**新閘門**（PM 2026-11-14 裁示）——
  不需要「營運報表」模組，只看呼叫者本來就有權限的案件（row_access `case`／`dev_case`）；案件進度不含任何金額；
  漏斗預估金額依 `can_see_financial`，沒有權限時是 `null`（Excel 直接不輸出金額欄）。
* **看不到≠零**：`null`＝看不到；`0`＝真的零；`{"state": "unfilled"|"unsettled"}`＝沒填／未精算。
* **遮罩在後端**：沒有權限的金額，後端不回值。
* 條件一律伺服器端驗證：未知、重複、不適用的參數 400；日期格式與先後、業務與部門須存在。
* 不靜默截斷：超過 `MAX_ROWS` 回 `truncated` 並寫入 notes。
"""
import io
import json
from datetime import date, datetime
from typing import Optional

import openpyxl
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import Response

from db import get_db
from helpers import _require_user, can_see_financial, download_name, row_access, user_has_module
from helpers.auth import has_finance_access
from helpers.recognition_basis import BASIS_NOTES, DEFAULT_BASIS, normalize_basis
from helpers.xlsx_out import add_pdf_sibling, check_export_rate, export_logged, set_row, xl_style

from modules.analytics.api import dashboard as _db
from modules.analytics.api import reports as _rp
from modules.analytics.api import report_templates as _rt

router = APIRouter()

#: 匯出稽核的區域代號（不是權限 key；與 reports.py／report_templates.py 同值）
_EXPORT_AREA = "analytics"

MAX_ROWS = 20000
TEXT_MAX = 40
MAX_MONTHS = 60                      # 逐月走勢最多幾個月（超過 ⇒ 400，請縮小期間）
_CHUNK = 500                         # SQL IN (...) 一次最多幾個案號

_COMMON = ("date_from", "date_to", "sales_id", "customer", "department_id")

#: 報表目錄（順序即畫面頁籤順序）
REPORTS = {
    "revenue": {"title": "營收", "needs_money": True, "params": _COMMON + ("basis",),
                "desc": "本期營收與逐月走勢，並依業務彙總；可切換現金口徑或權責口徑。"},
    "gross-margin": {"title": "毛利", "needs_money": True, "params": _COMMON,
                     "desc": "各案件的預估與實際營業利益率、毛利金額；尚未精算的案件不列入實際利益率。"},
    "ar-aging": {"title": "應收帳齡", "needs_money": True, "params": ("sales_id", "customer", "department_id"),
                 "desc": "尚未收款的款項，依報價日起算的經過天數分區間列示。"},
    "case-progress": {"title": "案件進度", "needs_money": False, "params": _COMMON,
                      "desc": "各案件的階段完成情形、下一個階段與預定完成日。"},
    "sales-funnel": {"title": "業務漏斗", "needs_money": False, "params": _COMMON,
                     "desc": "商機各狀態的件數與預估金額，以及報價單轉成案的情形。"},
}

_PARAM_LABEL = {"date_from": "起日", "date_to": "迄日", "sales_id": "業務", "customer": "客戶",
                "department_id": "部門", "basis": "收入口徑"}
_STATE_TEXT = {"unfilled": "未填", "unsettled": "未精算"}
_DEV_STATUS_ORDER = ("洽談中", "成案", "未成案", "暫擱置")


# ── 閘門 ─────────────────────────────────────────────────────────────────────

def _mods(u: dict) -> list:
    raw = u.get("modules")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            raw = []
    return list(raw or [])


def _can_case(u: dict) -> bool:
    """案件進度的入口：最高管理者／管理員、財務角色，或持有案件管理、報價單模組者（逐案仍受 row_access 限制）。"""
    return (u.get("role") in ("superadmin", "admin") or has_finance_access(u)
            or user_has_module(u, "case_manage") or user_has_module(u, "quotation"))


def _can_dev(u: dict) -> bool:
    """商機：與業務開發模組同一條規則（管理員，或持有 dev_crm 模組）。"""
    return u.get("role") in ("superadmin", "admin") or user_has_module(u, "dev_crm")


def _can_quote(u: dict) -> bool:
    """報價漏斗：與首頁漏斗同一條規則。"""
    return u.get("role") in ("superadmin", "admin", "sales") or "quotation" in _mods(u)


def _enforce(rid: str, u: dict) -> None:
    """通過 ⇒ 無回傳；不能開 ⇒ 403（訊息說明原因）。"""
    if REPORTS[rid]["needs_money"]:
        _rp._require_reports_access(u)
        return
    if rid == "case-progress":
        if not _can_case(u):
            raise HTTPException(403, "您的帳號沒有案件管理或報價單模組權限，無法查看案件進度")
        return
    if not (_can_dev(u) or _can_quote(u)):
        raise HTTPException(403, "您的帳號沒有業務開發或報價單模組權限，無法查看業務漏斗")


def _availability(u: dict) -> dict:
    out = {}
    for rid in REPORTS:
        try:
            _enforce(rid, u)
            out[rid] = (True, "")
        except HTTPException as e:
            out[rid] = (False, str(e.detail))
    return out


# ── 條件驗證 ─────────────────────────────────────────────────────────────────

def _valid_user_ids() -> set:
    conn = get_db()
    try:
        return {r[0] for r in conn.execute("SELECT id FROM users")}
    finally:
        conn.close()


def _validate(rid: str, request: Request) -> dict:
    """query string ⇒ 正規化條件。未知、重複、這張報表不適用的條件一律 400；空字串視為未設。"""
    raw = _rt._raw_params(request)                          # 重複 ⇒ 400
    allowed = REPORTS[rid]["params"]
    bad = sorted(k for k in raw if k not in allowed)
    if bad:
        known = sorted(k for k in bad if k in _PARAM_LABEL)
        unknown = sorted(k for k in bad if k not in _PARAM_LABEL)
        if unknown:
            raise HTTPException(400, "不支援的條件：" + "、".join(unknown))
        raise HTTPException(400, "「%s」不適用這張報表的條件：%s" % (REPORTS[rid]["title"], "、".join(known)))
    out: dict = {}
    for key in allowed:
        v = raw.get(key)
        if v is None:
            continue
        v = str(v).strip()
        if v == "":
            continue
        if key in ("date_from", "date_to"):
            try:
                if not _rt._DATE_RE.match(v):
                    raise ValueError
                date.fromisoformat(v)
            except ValueError:
                raise HTTPException(400, f"{_PARAM_LABEL[key]}日期格式錯誤（需為 YYYY-MM-DD）：{v[:20]}")
        elif key in ("sales_id", "department_id"):
            try:
                n = int(v)
            except ValueError:
                raise HTTPException(400, f"{_PARAM_LABEL[key]}條件格式錯誤")
            if key == "department_id":
                if n not in _rt._valid_dept_ids():
                    raise HTTPException(400, "查無此部門")
            elif n not in _valid_user_ids():
                raise HTTPException(400, "查無此業務")
            v = n
        elif key == "customer":
            if len(v) > TEXT_MAX:
                raise HTTPException(400, f"客戶條件過長（上限 {TEXT_MAX} 字）")
        elif key == "basis":
            v = normalize_basis(v)
        out[key] = v
    if out.get("date_from") and out.get("date_to") and out["date_from"] > out["date_to"]:
        raise HTTPException(400, "日期區間的起日不可晚於迄日")
    return out


# ── 小工具 ───────────────────────────────────────────────────────────────────

def _kpi(key, label, value, ctype, note=""):
    return {"key": key, "label": label, "value": value, "type": ctype, "note": note}


def _col(key, label, ctype="text"):
    return {"key": key, "label": label, "type": ctype}


def _table(key, title, columns, rows, note=""):
    return {"key": key, "title": title, "note": note, "columns": columns, "rows": rows}


def _badge(v, tone):
    return {"v": v, "tone": tone}


def _state(name):
    return {"state": name}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _text_has(hay, needle) -> bool:
    return needle.casefold() in (hay or "").casefold()


def _in_months(month: str, p: dict) -> bool:
    """月份（YYYY-MM）是否落在條件的起迄月份內（以月為單位；沒設條件 ⇒ True）。"""
    lo, hi = (p.get("date_from") or "")[:7], (p.get("date_to") or "")[:7]
    if not month:
        return not (lo or hi)
    return (not lo or month >= lo) and (not hi or month <= hi)


def _weighted_pct(pairs) -> Optional[float]:
    """[(基數, 百分比)] ⇒ 以基數加權的百分比（與營運報表利益率同定義）；基數合計 ≤ 0 ⇒ None。"""
    base = sum(w for w, _x in pairs)
    if base <= 0:
        return None
    return round(sum(w * x / 100 for w, x in pairs) / base * 100, 1)


def _finish(rid: str, p: dict, kpis, tables, notes, money_masked=False, **extra) -> dict:
    truncated = False
    for t in tables:
        if len(t["rows"]) > MAX_ROWS:
            t["rows"] = t["rows"][:MAX_ROWS]
            truncated = True
    notes = list(notes)
    if truncated:
        notes.append(f"結果超過 {MAX_ROWS} 列，只列出前 {MAX_ROWS} 列；請縮小條件。")
    out = {"id": rid, "title": REPORTS[rid]["title"], "params": p, "kpis": kpis, "tables": tables,
           "notes": notes, "moneyMasked": bool(money_masked), "truncated": truncated, "generatedAt": _now_text()}
    out.update(extra)
    return out


def _cases_for(p: dict, data: Optional[dict] = None) -> list:
    """營收、毛利的案件母體：`_collect()` 的 casesAll（已成案／已結案），再依業務（業務負責歸屬的帳號 id）與客戶篩選；
    部門交給 `_collect`（跟著業務負責歸屬）。`data` 給了就沿用（呼叫端還要用 allItems，不重複掃一次）。"""
    data = data or _rp._collect("0000-01-01", "9999-12-31", p.get("department_id"))
    out = []
    for c in data["casesAll"]:
        if p.get("sales_id") and list(c["ownerKey"]) != ["id", p["sales_id"]]:
            continue
        if p.get("customer") and not _text_has(c["customer"], p["customer"]):
            continue
        out.append(c)
    return out


# ── 營收 ─────────────────────────────────────────────────────────────────────

def _months_between(d_from: str, d_to: str) -> list:
    y, m = int(d_from[:4]), int(d_from[5:7])
    ye, me = int(d_to[:4]), int(d_to[5:7])
    out = []
    while (y, m) <= (ye, me):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _effective_range(p: dict) -> tuple:
    """營收的有效期間：沒給日期 ⇒ 近 12 個月（與逐月走勢同一個預設）。"""
    d_to = p.get("date_to") or date.today().isoformat()
    d_from = p.get("date_from")
    if not d_from:
        total = int(d_to[:4]) * 12 + int(d_to[5:7]) - 1 - 11
        d_from = f"{total // 12}-{total % 12 + 1:02d}-01"
    if len(_months_between(d_from, d_to)) > MAX_MONTHS:
        raise HTTPException(400, f"期間過長：逐月走勢最多 {MAX_MONTHS} 個月，請縮小期間")
    return d_from[:10], d_to[:10]


def _build_revenue(p: dict, u: dict) -> dict:
    basis = p.get("basis") or DEFAULT_BASIS
    d0, d1 = _effective_range(p)
    eff = {"date_from": d0, "date_to": d1}
    months = _months_between(d0, d1)
    collected = _rp._collect("0000-01-01", "9999-12-31", p.get("department_id"))
    cases = _cases_for(p, collected)
    cmap = {c["quoteNo"]: c for c in cases}
    filtered = bool(p.get("sales_id") or p.get("customer"))
    rec = _rp._recognition()
    cash_ok = _rp._registry.single_provider("receivables.income_items") is not None
    notes = [BASIS_NOTES[basis]]

    def items_for(which: str):
        """⇒ 逐筆收入（已依條件篩選）或 None（這個口徑沒有資料來源）。案件收入以 `_collect` 的案件母體過濾；
        自訂模組的收入沒有「業務負責」歸屬，有業務或客戶條件時無法歸屬 ⇒ 不列入（notes 明說）。"""
        if which == "cash" and not cash_ok:
            return None
        if which == "accrual" and rec is None:
            return None
        conn = get_db()
        try:
            if which == "cash":
                base = _rp._collect_income_items(d0, d1, None)
            else:
                base = rec.accrual_income_items(conn, d0, d1, None)
            base = [i for i in base if i["quoteNo"] in cmap]
            custom = [] if filtered else _rp._custom_income(conn, d0, d1, which, p.get("department_id"))
        finally:
            conn.close()
        return base + custom

    cash_items, accr_items = items_for("cash"), items_for("accrual")
    if cash_items is None:
        notes.append(_rp.RECEIVABLES_MISSING)
    if accr_items is None:
        notes.append(_rp.CASE_RECOGNITION_MISSING)
    if filtered:
        notes.append("自訂模組的收入沒有「業務負責」與客戶歸屬，有業務或客戶條件時不列入。")
    notes.append(f"期間 {d0} 至 {d1}" + ("" if p.get("date_from") or p.get("date_to") else "（未指定期間，預設為近 12 個月）")
                 + "；合約金額與案件數依成案月（以月為單位）。")

    def by_month(items):
        if items is None:
            return None
        acc = {m: 0 for m in months}
        for i in items:
            k = (i.get("receivedAt") or "")[:7]
            if k in acc:
                acc[k] += i["amount"]
        return acc

    cash_m, accr_m = by_month(cash_items), by_month(accr_items)
    series = []
    for m in months:
        yy, mm = int(m[:4]), int(m[5:7])
        series.append({"key": m, "label": f"{mm}月" if yy == date.today().year else f"{mm}/{str(yy)[2:]}",
                       "cash": None if cash_m is None else cash_m[m],
                       "accrual": None if accr_m is None else accr_m[m]})

    sel = cash_items if basis == "cash" else accr_items
    in_period = [c for c in cases if _in_months(c["wonMonth"], eff)]
    contract = sum(c["total"] for c in in_period)
    nos = {c["quoteNo"] for c in in_period}
    pay_items = [i for i in collected["allItems"] if i["quoteNo"] in nos]
    tr = sum(i["amount"] for i in pay_items)
    tc = sum(i["amount"] for i in pay_items if i["received"])
    revenue_total = None if sel is None else sum(i["amount"] for i in sel)
    kpis = [
        _kpi("revenue", "本期營收", revenue_total, "money",
             "" if sel is not None else "這個口徑沒有資料來源，不是 0 元"),
        _kpi("contract", "合約金額", contract, "money", "期間內成案的案件"),
        _kpi("collectionRate", "收款率", round(tc / tr * 100, 1) if tr > 0 else None, "pct",
             "已收款項 ÷ 應收款項" if tr > 0 else "期間內成案的案件尚無應收款項"),
        _kpi("caseCount", "案件數", len(in_period), "count"),
    ]

    # 依業務彙總：案件數與合約金額＝期間內成案的案件；營收＝所選口徑的逐筆收入歸到案件的業務負責人
    agg: dict = {}

    def slot(key, label):
        return agg.setdefault(key, {"owner": label, "cases": 0, "contract": 0, "revenue": 0})

    for c in in_period:
        s = slot(tuple(c["ownerKey"]), c["ownerName"])
        s["cases"] += 1
        s["contract"] += c["total"]
    for i in (sel or []):
        c = cmap.get(i["quoteNo"])
        s = slot(tuple(c["ownerKey"]), c["ownerName"]) if c else slot(("custom",), "（非案件收入）")
        s["revenue"] += i["amount"]
    total_rev = sum(s["revenue"] for s in agg.values())
    rows = []
    for s in sorted(agg.values(), key=lambda x: (-x["revenue"], x["owner"])):
        rows.append({"owner": s["owner"], "cases": s["cases"], "contract": s["contract"], "revenue": s["revenue"],
                     "share": round(s["revenue"] / total_rev * 100, 1) if total_rev > 0 else None})
    tables = [_table("bySales", "依業務彙總",
                     [_col("owner", "業務"), _col("cases", "案件數", "count"), _col("contract", "合約金額", "money"),
                      _col("revenue", "營收", "money"), _col("share", "占比", "pct")], rows)]
    p_out = dict(p)
    p_out["basis"] = basis
    return _finish("revenue", p_out, kpis, tables, notes, series=series)


# ── 毛利 ─────────────────────────────────────────────────────────────────────

def _build_gross_margin(p: dict, u: dict) -> dict:
    cases = [c for c in _cases_for(p) if _in_months(c["wonMonth"], p)]
    cases.sort(key=lambda c: (c["quoteDate"] or "", c["quoteNo"]), reverse=True)
    settled = [c for c in cases if c["settleStatus"] == "finalized" and c["actualMarginPct"] is not None]
    est = _weighted_pct([(c["pretax"], c["netMarginPct"] or 0) for c in cases])
    est_s = _weighted_pct([(c["pretax"], c["netMarginPct"] or 0) for c in settled])
    act = _weighted_pct([(c["pretax"], c["actualMarginPct"]) for c in settled])
    gap = None if (act is None or est_s is None) else round(act - est_s, 1)
    kpis = [
        _kpi("estMargin", "預估營業利益率", est, "pct", "成案案件，依報價單試算，以金額加權" if cases else "尚無符合條件的案件"),
        _kpi("actMargin", "實際營業利益率", act if act is not None else _state("unsettled"), "pct",
             f"僅計已精算 {len(settled)} 件，以金額加權"),
        _kpi("settledCount", "已精算件數", len(settled), "count", f"共 {len(cases)} 件案件"),
        _kpi("gap", "實際與預估差距（百分點）", gap if gap is not None else _state("unsettled"), "pct",
             "百分點；僅比較已精算的案件"),
    ]
    rows = []
    for c in cases:
        has = c["settleStatus"] == "finalized" and c["actualMarginPct"] is not None
        tone = {"finalized": ("已精算", "ok"), "draft": ("精算中", "info")}.get(c["settleStatus"], ("未精算", "neutral"))
        rows.append({
            "quoteNo": c["quoteNo"], "customer": c["customer"], "project": c["project"], "owner": c["ownerName"],
            "dept": c["deptName"], "total": c["total"], "estMargin": c["netMarginPct"],
            "actMargin": c["actualMarginPct"] if has else _state("unsettled"),
            "grossProfit": c["grossProfit"] if (has and c["grossProfit"] is not None) else _state("unsettled"),
            "settle": _badge(*tone),
        })
    notes = ["期間依案件成案月（以月為單位），與營運報表的成案趨勢同一份歸月規則。",
             "預估與實際利益率分開列示，皆為營業利益口徑；尚未精算的案件，實際利益率顯示「未精算」，不計為 0，也不納入平均。",
             f"平均以報價未稅金額加權；實際利益率僅計已精算 {len(settled)} 件。",
             "業務與部門為案件管理的「業務負責」歸屬（未填寫時為開單者）。"]
    if any(c["actualIsGross"] for c in settled):
        notes.append("部分舊精算的實際欄位是毛利，不是營業利益。")
    tables = [_table("cases", "案件獲利明細",
                     [_col("quoteNo", "案件號"), _col("customer", "客戶"), _col("project", "專案名稱"), _col("owner", "業務"),
                      _col("dept", "部門"), _col("total", "合約金額", "money"), _col("estMargin", "預估營業利益率", "pct"),
                      _col("actMargin", "實際營業利益率", "pct"), _col("grossProfit", "毛利金額", "money"),
                      _col("settle", "精算", "badge")], rows)]
    return _finish("gross-margin", p, kpis, tables, notes)


# ── 應收帳齡 ─────────────────────────────────────────────────────────────────

def _build_ar_aging(p: dict, u: dict) -> dict:
    ar = _rp._ar_aging_core(p.get("sales_id"), p.get("customer"), p.get("department_id"), with_owner=True)
    kpis = [_kpi("total", "未收合計", ar["total"]["amount"], "money", f"{ar['total']['count']} 筆")]
    rows = []
    for b in ar["bands"]:
        kpis.append(_kpi(str(b["key"]), b["label"], b["amount"], "money", f"{b['count']} 筆"))
        for i in b["items"]:
            rows.append({"quoteNo": i["quoteNo"], "customer": i["customer"], "owner": i["owner"], "stage": i["type"],
                         "amount": i["amount"], "quoteDate": (i["quoteDate"] or "")[:10], "days": i["daysElapsed"],
                         "band": b["label"]})
    rows.sort(key=lambda r: (-r["days"], r["quoteNo"]))
    notes = ["帳齡依報價日計算：以報價日為起算日，扣除已收款的款項；沒有應收到期日欄位，屬管理用途的近似值。",
             f"以今日（{ar['asOf']}）為基準，所以不適用期間條件。",
             "區間切點可在設定中心調整；區間名稱依目前設定顯示。",
             "沒有收款期別的案件不在本表內。"]
    tables = [_table("items", "未收款項明細",
                     [_col("quoteNo", "案件號"), _col("customer", "客戶"), _col("owner", "業務"), _col("stage", "期別"),
                      _col("amount", "未收金額", "money"), _col("quoteDate", "報價日", "date"),
                      _col("days", "經過天數", "days"), _col("band", "帳齡區間")], rows)]
    return _finish("ar-aging", p, kpis, tables, notes)


# ── 案件進度 ─────────────────────────────────────────────────────────────────

def _build_case_progress(p: dict, u: dict) -> dict:
    today = date.today().isoformat()
    conn = get_db()
    try:
        frag, fparams = row_access.filter_sql("case", u, scope="read")      # 與案件清單同一個可見範圍
        qrows = conn.execute(
            "SELECT quote_no, customer_name, project_name, quote_date, sales_person, sales_person_id, deal_tag, data_json "
            "FROM quotations WHERE 1=1" + frag + " ORDER BY quote_date DESC, quote_no DESC", fparams).fetchall()
        user_by_id, name_index = _rp._load_user_index(conn)
        cases, undated = [], 0
        dated = bool(p.get("date_from") or p.get("date_to"))
        for r in qrows:
            cr_all = _data(r)
            tag = r["deal_tag"] or cr_all.get("dealTag") or ""
            if tag not in ("已成案", "已結案"):
                continue
            if p.get("customer") and not _text_has(r["customer_name"], p["customer"]):
                continue
            cr = cr_all.get("caseRecord") if isinstance(cr_all.get("caseRecord"), dict) else {}
            key, label = _rp._case_sales_owner(cr, r, name_index, user_by_id)
            if p.get("sales_id") and not (key[0] == "id" and key[1] == p["sales_id"]):
                continue
            if p.get("department_id") and _rp._case_dept(cr, r, name_index, user_by_id)[0] != p["department_id"]:
                continue
            qd = (r["quote_date"] or "")[:10]
            if dated and not qd:
                undated += 1
                continue
            if not _rt._in_range(qd, p):
                continue
            cases.append({"quoteNo": r["quote_no"], "customer": r["customer_name"] or "", "project": r["project_name"] or "",
                          "owner": label})
        stages: dict = {}
        nos = [c["quoteNo"] for c in cases]
        for i in range(0, len(nos), _CHUNK):
            part = nos[i:i + _CHUNK]
            for s in conn.execute(
                    "SELECT quote_no, label, sort_order, done, due_date FROM case_stages WHERE quote_no IN (%s) "
                    "ORDER BY quote_no, sort_order, id" % ",".join("?" * len(part)), part):
                stages.setdefault(s["quote_no"], []).append(s)
    finally:
        conn.close()

    rows = []
    n_active = n_done = n_overdue_stages = n_unsched = 0
    for c in cases:
        sts = stages.get(c["quoteNo"], [])
        total = len(sts)
        done = sum(1 for s in sts if s["done"])
        undone = [s for s in sts if not s["done"]]
        overdue = [s for s in undone if (s["due_date"] or "") and (s["due_date"] or "")[:10] < today]
        n_overdue_stages += len(overdue)
        nxt = undone[0] if undone else None
        over_days = None
        if overdue:
            oldest = min((s["due_date"] or "")[:10] for s in overdue)
            over_days = (date.fromisoformat(today) - date.fromisoformat(oldest)).days
        if total == 0:
            status, n_unsched = _badge("未排定", "neutral"), n_unsched + 1
        elif not undone:
            status, n_done = _badge("已完工", "ok"), n_done + 1
        elif overdue:
            status, n_active = _badge("已逾預定日", "warn"), n_active + 1
        else:
            status, n_active = _badge("進行中", "info"), n_active + 1
        rows.append({
            "quoteNo": c["quoteNo"], "customer": c["customer"], "project": c["project"], "owner": c["owner"],
            "stagesDone": done, "stagesTotal": total,
            "progressPct": round(done / total * 100) if total else None,
            "nextStage": (nxt["label"] if nxt else ""), "nextDue": ((nxt["due_date"] or "")[:10] or None) if nxt else None,
            "overdueDays": over_days, "status": status,
        })
    kpis = [_kpi("active", "進行中", n_active, "count", "含已逾預定日的案件"), _kpi("done", "已完工", n_done, "count"),
            _kpi("overdueStages", "已逾預定日階段", n_overdue_stages, "count", "未完成且預定日早於今日的階段數"),
            _kpi("unscheduled", "未排定", n_unsched, "count", "尚未建立任何階段，不計為 0% 進度")]
    notes = ["日期條件依「案件報價日」；只列您有權限查看的案件，本報表不含金額。",
             "已逾預定日：案件有未完成的階段，預定日早於今日；逾期天數以最早的一個階段計算。",
             "下一階段為依排序第一個尚未完成的階段。沒有階段的案件顯示「未排定」，不當作 0% 進度。"]
    if undated:
        notes.append(f"有 {undated} 件案件沒有報價日，因為有日期條件所以未列入；不設日期條件即會列入。")
    tables = [_table("cases", "案件進度明細",
                     [_col("quoteNo", "案件號"), _col("customer", "客戶"), _col("project", "專案名稱"), _col("owner", "業務"),
                      _col("stagesDone", "已完成階段", "count"), _col("stagesTotal", "階段總數", "count"),
                      _col("progressPct", "完成度", "pct"), _col("nextStage", "下一階段"), _col("nextDue", "預定完成日", "date"),
                      _col("overdueDays", "已逾預定日", "days"), _col("status", "狀態", "badge")], rows)]
    return _finish("case-progress", p, kpis, tables, notes)


def _data(row) -> dict:
    """quotations 列的 data_json ⇒ dict；缺或壞 ⇒ {}（壞的一筆不影響其他筆）。"""
    try:
        v = json.loads(row["data_json"] or "{}")
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


# ── 業務漏斗 ─────────────────────────────────────────────────────────────────

def _id_list(raw) -> list:
    try:
        v = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [x for x in v if isinstance(x, int)] if isinstance(v, list) else []


def _build_sales_funnel(p: dict, u: dict) -> dict:
    money_ok = bool(can_see_financial(u))
    can_dev, can_quote = _can_dev(u), _can_quote(u)
    notes = []
    conn = get_db()
    try:
        dept_of = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users")}
        names = {r["id"]: (r["display_name"] or r["username"] or "") for r in
                 conn.execute("SELECT id, display_name, username FROM users")}
        dev_rows, quote_rows = [], []
        last_log: dict = {}
        if can_dev:
            for r in conn.execute("SELECT * FROM dev_cases WHERE is_deleted = 0 ORDER BY id DESC").fetchall():
                if not row_access.visible("dev_case", u, r):
                    continue
                owners = ([r["assigned_to"]] if r["assigned_to"] else []) + _id_list(r["sales_persons"])
                owners = list(dict.fromkeys(owners or ([r["created_by"]] if r["created_by"] else [])))
                if p.get("sales_id") and p["sales_id"] not in owners:
                    continue
                if p.get("department_id") and p["department_id"] not in {dept_of.get(o) for o in owners}:
                    continue
                if p.get("customer") and not _text_has(r["customer_name"], p["customer"]):
                    continue
                if not _rt._in_range((r["created_at"] or "")[:10], p):
                    continue
                dev_rows.append((r, owners))
            ids = [r["id"] for r, _o in dev_rows]
            for i in range(0, len(ids), _CHUNK):
                part = ids[i:i + _CHUNK]
                for l in conn.execute(
                        "SELECT case_id, MAX(log_date) AS d FROM dev_logs WHERE needs_approval = 0 AND case_id IN (%s) GROUP BY case_id"
                        % ",".join("?" * len(part)), part):
                    last_log[l["case_id"]] = (l["d"] or "")[:10] or None
        if can_quote:
            frag, fparams = row_access.filter_sql("case", u, scope="read")
            user_by_id, name_index = _rp._load_user_index(conn)
            for r in conn.execute("SELECT quote_no, status, customer_name, quote_date, sales_person, sales_person_id, "
                                  "deal_tag, data_json FROM quotations WHERE status NOT IN ('草稿')" + frag, fparams).fetchall():
                if p.get("customer") and not _text_has(r["customer_name"], p["customer"]):
                    continue
                if not _rt._in_range((r["quote_date"] or "")[:10], p):
                    continue
                qd = _data(r)
                cr = qd.get("caseRecord") if isinstance(qd.get("caseRecord"), dict) else {}
                # 業務與部門與案件進度同一個歸屬規則（案件管理的「業務負責」，沒填則回到開單者）
                if p.get("sales_id"):
                    key, _lbl = _rp._case_sales_owner(cr, r, name_index, user_by_id)
                    if not (key[0] == "id" and key[1] == p["sales_id"]):
                        continue
                if p.get("department_id") and _rp._case_dept(cr, r, name_index, user_by_id)[0] != p["department_id"]:
                    continue
                tag = r["deal_tag"] or qd.get("dealTag") or ""
                quote_rows.append(_db.classify_quote_funnel(r["status"], tag))
    finally:
        conn.close()

    # 商機漏斗：預估金額只加總有填的，未填另列；沒有金額權限 ⇒ null（件數照給）
    by: dict = {s: {"status": s, "count": 0, "amount": 0, "missing": 0} for s in _DEV_STATUS_ORDER}
    for r, _o in dev_rows:
        s = by.setdefault(r["status"] or "", {"status": r["status"] or "", "count": 0, "amount": 0, "missing": 0})
        s["count"] += 1
        amt = r["expected_amount"]
        if amt is None:
            s["missing"] += 1
        else:
            s["amount"] += int(amt)
    dev = [{"status": v["status"], "count": v["count"], "amount": v["amount"] if money_ok else None,
            "missing": v["missing"] if money_ok else None} for v in by.values() if v["status"] in _DEV_STATUS_ORDER or v["count"]] if can_dev else []
    won, lost = by["成案"]["count"], by["未成案"]["count"]
    dev_rate = round(won / (won + lost) * 100, 1) if (won + lost) else None
    q = None
    if can_quote:
        q = {"submitted": len(quote_rows), "pending": quote_rows.count("pending"),
             "won": quote_rows.count("won"), "lost": quote_rows.count("lost")}
    q_rate = round(q["won"] / (q["won"] + q["lost"]) * 100, 1) if (q and (q["won"] + q["lost"])) else None
    open_n, open_missing = by["洽談中"]["count"], by["洽談中"]["missing"]
    if not can_dev or not money_ok:                          # 沒有商機權限或沒有金額權限 ⇒ 看不到，不是 0 元
        pipeline = None
    elif open_n and open_missing == open_n:
        pipeline = _state("unfilled")
    else:
        pipeline = by["洽談中"]["amount"]
    kpis = [
        _kpi("pipelineAmount", "洽談中預估金額", pipeline, "money",
             "" if not (can_dev and money_ok) else "尚未填寫預估金額" if pipeline == _state("unfilled")
             else f"另有 {open_missing} 件未填" if open_missing else ""),
        _kpi("devWinRate", "商機成案率", dev_rate, "pct", "成案 ÷（成案＋未成案），不含洽談中與暫擱置"),
        _kpi("quoteWinRate", "報價成案率", q_rate, "pct", "成案 ÷（成案＋未成案），不含草稿與待回覆"),
        _kpi("quotePending", "待回覆報價", q["pending"] if q else None, "count", "已送出、尚無成案標記"),
    ]
    open_rows = []
    for r, owners in dev_rows:
        if r["status"] != "洽談中":
            continue
        amt = r["expected_amount"]
        open_rows.append({
            "caseName": r["case_name"] or "", "customer": r["customer_name"] or "",
            "owner": "、".join(names.get(o, "") for o in owners if names.get(o)),
            "amount": (None if not money_ok else (_state("unfilled") if amt is None else int(amt))),
            "expectedCloseDate": (r["expected_close_date"] or "")[:10] or None, "lastLogDate": last_log.get(r["id"]),
        })
    open_rows.sort(key=lambda x: (x["expectedCloseDate"] is None, x["expectedCloseDate"] or "", x["caseName"]))
    notes += ["商機的日期條件依建立日，業務為被指派人與業務人員（未指派時為建立者），部門為這些人員所屬的部門；報價的日期條件依報價日。",
              "只列您有權限查看的商機與案件。"]
    if can_dev and money_ok:
        notes.insert(1, "預估金額只加總有填寫的商機，未填寫的另列件數，不當作 0 元。")
    if not can_dev:
        notes.append("您的帳號沒有業務開發模組權限，商機部分不顯示。")
    if not can_quote:
        notes.append("您的帳號沒有報價單模組權限，報價部分不顯示。")
    if can_dev and not money_ok:
        notes.append("您的帳號沒有金額檢視權限，預估金額不顯示。")
    tables = [_table("openCases", "洽談中商機",
                     [_col("caseName", "商機名稱"), _col("customer", "客戶"), _col("owner", "負責業務"),
                      _col("amount", "預估金額", "money"), _col("expectedCloseDate", "預計成交日", "date"),
                      _col("lastLogDate", "最近跟進日", "date")], open_rows)] if can_dev else []
    return _finish("sales-funnel", p, kpis, tables, notes, money_masked=bool(can_dev and not money_ok),
                   funnel={"dev": dev, "quote": q})


_BUILDERS = {"revenue": _build_revenue, "gross-margin": _build_gross_margin, "ar-aging": _build_ar_aging,
             "case-progress": _build_case_progress, "sales-funnel": _build_sales_funnel}


def _get_id(rid: str) -> str:
    if rid not in REPORTS:
        raise HTTPException(404, "查無此標準報表")
    return rid


def _produce(rid: str, request: Request, u: dict) -> dict:
    _get_id(rid)
    _enforce(rid, u)
    p = _validate(rid, request)
    return _BUILDERS[rid](p, u)


# ── 目錄與資料端點 ───────────────────────────────────────────────────────────

def _sales_options(u: dict) -> list:
    """業務下拉：呼叫者看得到的案件與商機上出現的業務；管理員、財務與報表模組持有者另加全部在職人員。
    已停用者仍列出（active:false）：舊案件的歸屬不能憑空消失。"""
    broad = (u.get("role") in ("superadmin", "admin") or has_finance_access(u) or user_has_module(u, "reports"))
    conn = get_db()
    try:
        ids = {u["id"]}
        frag, fparams = row_access.filter_sql("case", u, scope="read")
        ids |= {r[0] for r in conn.execute(
            "SELECT DISTINCT sales_person_id FROM quotations WHERE sales_person_id IS NOT NULL" + frag, fparams)}
        if _can_dev(u):
            for r in conn.execute("SELECT * FROM dev_cases WHERE is_deleted = 0").fetchall():
                if row_access.visible("dev_case", u, r):
                    ids |= {x for x in ([r["assigned_to"]] + _id_list(r["sales_persons"])) if x}
        out = []
        for r in conn.execute("SELECT id, display_name, username, active FROM users ORDER BY id").fetchall():
            if r["id"] in ids or (broad and r["active"]):
                out.append({"id": r["id"], "label": r["display_name"] or r["username"] or str(r["id"]),
                            "active": bool(r["active"])})
        return out
    finally:
        conn.close()


@router.get("/api/std-reports")
def std_report_catalog(authorization: str = Header(None)):
    u = _require_user(authorization)
    avail = _availability(u)
    reports = [{"id": rid, "title": m["title"], "desc": m["desc"], "params": list(m["params"]),
                "needsMoney": m["needs_money"], "available": avail[rid][0], "reason": avail[rid][1]}
               for rid, m in REPORTS.items()]
    return {"reports": reports if any(a[0] for a in avail.values()) else [],
            "salesOptions": _sales_options(u) if any(a[0] for a in avail.values()) else [],
            "departmentOptions": _rt.department_options(), "maxRows": MAX_ROWS}


@router.get("/api/std-reports/{rid}")
def std_report_data(rid: str, request: Request, authorization: str = Header(None)):
    u = _require_user(authorization)
    return _produce(rid, request, u)


# ── Excel／PDF ───────────────────────────────────────────────────────────────

def _cell(v):
    if isinstance(v, dict):
        if "state" in v:
            return _STATE_TEXT.get(v["state"], "")
        if "v" in v:
            return v["v"]
    return v


def _fmt_params(rid: str, p: dict) -> list:
    dept = {o["id"]: o["label"] for o in _rt.department_options()}
    out = []
    for key in REPORTS[rid]["params"]:
        v = p.get(key)
        if v is None:
            shown = "（全部）"
        elif key == "department_id":
            shown = dept.get(v, str(v))
        elif key == "sales_id":
            shown = next((o["label"] for o in _sales_all() if o["id"] == v), str(v))
        elif key == "basis":
            shown = "權責口徑" if v == "accrual" else "現金口徑"
        else:
            shown = v
        out.append((_PARAM_LABEL[key], shown))
    return out


def _sales_all() -> list:
    conn = get_db()
    try:
        return [{"id": r["id"], "label": r["display_name"] or r["username"] or str(r["id"])}
                for r in conn.execute("SELECT id, display_name, username FROM users")]
    finally:
        conn.close()


def _put_table(wb, f, title, cols, rows, first=False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = (title or "報表")[:31]
    set_row(ws, 1, [c["label"] for c in cols], font=f(bold=True, size=10))
    for ri, r in enumerate(rows, 2):
        set_row(ws, ri, [_cell(r.get(c["key"])) for c in cols], font=f(size=10))
        for ci, c in enumerate(cols, 1):
            if c["type"] == "money":
                ws.cell(row=ri, column=ci).number_format = "#,##0"
            elif c["type"] == "pct":
                ws.cell(row=ri, column=ci).number_format = '0.0"%"'
    for ci, c in enumerate(cols, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = max(10, min(40, len(c["label"]) * 2 + 4))
    ws.freeze_panes = "A2"
    return ws


def _drop_money(cols, rows):
    keep = [c for c in cols if c["type"] != "money"]
    return keep, rows


def _build_xlsx(rid: str, data: dict) -> bytes:
    wb = openpyxl.Workbook()
    f = xl_style(wb)[0]
    masked = bool(data.get("moneyMasked"))
    first = True
    extra_notes = []
    if rid == "revenue":
        cols = [_col("label", "月份"), _col("cash", "現金口徑營收", "money"), _col("accrual", "權責口徑營收", "money")]
        _put_table(wb, f, "逐月走勢", cols, [{"label": s["key"], "cash": s["cash"], "accrual": s["accrual"]}
                                                for s in data["series"]], first=first)
        first = False
    if rid == "sales-funnel":
        fn = data["funnel"]
        if fn["dev"] or any(t["key"] == "openCases" for t in data["tables"]):
            cols = [_col("status", "狀態"), _col("count", "件數", "count"), _col("amount", "預估金額", "money"),
                    _col("missing", "未填件數", "count")]
            if masked:                                       # 未填件數也是金額欄位的資訊，一併不輸出
                cols = [c for c in cols if c["type"] != "money" and c["key"] != "missing"]
            _put_table(wb, f, "商機漏斗", cols, fn["dev"], first=first)
            first = False
        if fn["quote"]:
            cols = [_col("k", "項目"), _col("v", "件數", "count")]
            q = fn["quote"]
            _put_table(wb, f, "報價漏斗", cols, [{"k": "已送出", "v": q["submitted"]}, {"k": "待回覆", "v": q["pending"]},
                                              {"k": "成案", "v": q["won"]}, {"k": "未成案", "v": q["lost"]}], first=first)
            first = False
    for t in data["tables"]:
        cols = t["columns"]
        if masked:
            cols, _ = _drop_money(cols, [])
        _put_table(wb, f, t["title"], cols, t["rows"], first=first)
        first = False
    if first:                                                # 沒有任何資料表（例如漏斗兩段都無權限）仍要有一張工作表
        wb.active.title = "報表"
    if masked:
        extra_notes.append("您的帳號沒有金額檢視權限，金額欄位未輸出。")
    w2 = wb.create_sheet("條件")
    set_row(w2, 1, [data["title"], "產出時間 " + data["generatedAt"]], font=f(bold=True, size=11))
    r0 = 3
    set_row(w2, r0, ["條件", "值"], font=f(bold=True, size=10))
    for lbl, val in _fmt_params(rid, data["params"]):
        r0 += 1
        set_row(w2, r0, [lbl, val], font=f(size=10))
    r0 += 2
    set_row(w2, r0, ["彙總", "值"], font=f(bold=True, size=10))
    for k in data["kpis"]:
        if masked and k["type"] == "money":
            continue
        r0 += 1
        set_row(w2, r0, [k["label"], _cell(k["value"]), k.get("note") or ""], font=f(size=10))
    r0 += 2
    for n in list(data["notes"]) + extra_notes:
        set_row(w2, r0, [n], font=f(size=9, italic=True))
        r0 += 1
    w2.column_dimensions["A"].width = 28
    w2.column_dimensions["B"].width = 36
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# 條件在簽名上明列（值不在這裡用）：讓 export_logged 把條件寫進匯出稽核、OpenAPI／路由登記簿也看得到；
# 真正的驗證與「未知參數 400」走 _validate（讀 request.query_params）。
@router.get("/api/std-reports/{rid}/excel")
@export_logged("xlsx", _EXPORT_AREA, "std-report")
def excel_std_report(rid: str, request: Request, authorization: str = Header(None),
                     date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
                     sales_id: Optional[str] = Query(None), customer: Optional[str] = Query(None),
                     department_id: Optional[str] = Query(None), basis: Optional[str] = Query(None)):
    u = _require_user(authorization)
    _get_id(rid)
    _enforce(rid, u)
    _validate(rid, request)                                  # 先驗條件：不合法的請求不消耗匯出冷卻
    check_export_rate(u["id"], "excel")
    data = _produce(rid, request, u)
    fname = f"MOTRIX_標準報表_{REPORTS[rid]['title']}_{date.today().isoformat()}.xlsx"
    return Response(
        content=_build_xlsx(rid, data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": download_name.content_disposition(fname)},
    )


# 平台規則：每支 xlsx 匯出都有 PDF 姊妹（同處理函式、同權限、同資料）
add_pdf_sibling(router, "/api/std-reports/{rid}/pdf", excel_std_report, module=_EXPORT_AREA, name="std-report",
                title="標準報表")
