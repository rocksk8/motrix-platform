"""Financial report generation — Excel & PDF (admin+ only)."""
import csv
import io
import json
import logging
import os
import tempfile
import threading
import time
from calendar import monthrange
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote as _url_quote

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from fastapi import APIRouter, Header, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse

from db import get_db
from helpers import (
    _require_user, _tok, _audit, _warranty_expiry, _get_edge_path, _get_setting, _set_setting,
    payment_item_amounts, summarize_payment_items, case_extra_expenses, quote_won_month_map,
    user_has_module, run_edge_pdf,
)
from routers.vendor_contractors import _dispatch_row

_log = logging.getLogger(__name__)

router = APIRouter()

_COMPANY  = "允碩整合集創"

# Per-user export rate limit — keyed by (user_id, fmt) so Excel / PDF are independent
_EXCEL_COOLDOWN = 5   # seconds — fast generation, just prevent double-clicks
_PDF_COOLDOWN   = 30  # seconds — Edge headless is resource-intensive
_export_times: dict = {}
_export_lock = threading.Lock()


def _require_reports_access(u: dict) -> None:
    """營運報表的存取權（2026-09-13 模組權限稽核）。

    在此之前這 11 支端點一律只認 `role in ("superadmin","admin")`，**完全沒有讀
    `reports` 模組**——但 `users.html` 的權限目錄一直提供「營運報表」這個可勾選
    模組，側欄也用 `cRpt || cCash || cFi` 決定要不要顯示營運報表入口。結果是：
    把「營運報表」勾給一個業務，他會看到選單、點進去、然後**每一支 API 都 403**，
    畫面上只有一片載入失敗，沒有任何地方說得出原因。

    這裡讓後端認 `reports` 與 `finance` 兩個模組，跟側欄的顯示條件對齊；作法比照
    同一個財務區的既有先例 `routers/cashier.py::_require_view_access()`
    （admin+ 或 cashier 或 finance）。`cashier` 不放進來：出納的資料在 cashier.py
    自己那幾支端點，這裡是整份營運報表（含稅務匯出、現金部位、客戶歷史）。
    `bank-reconcile` 維持 admin+ 或 cashier 不變——那是對帳「動作」不是報表查閱。
    """
    if (u["role"] not in ("superadmin", "admin")
            and not user_has_module(u, "reports")
            and not user_has_module(u, "finance")):
        raise HTTPException(403, "僅管理員、或具『營運報表』／『應收帳款』模組的使用者可存取報表")


def _check_export_rate(user_id: int, fmt: str) -> None:
    """Raise 429 if this user exported this format within the cooldown window."""
    cooldown = _PDF_COOLDOWN if fmt == "pdf" else _EXCEL_COOLDOWN
    with _export_lock:
        key = (user_id, fmt)
        last = _export_times.get(key, 0.0)
        wait = cooldown - (time.monotonic() - last)
        if wait > 0:
            raise HTTPException(429, f"請等待 {int(wait) + 1} 秒後再次匯出")
        _export_times[key] = time.monotonic()
_COMPANY2 = "統一編號 60575481 ｜ Tel: 04-3610-6566 ｜ info@miactw.com"


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_period(period: str):
    today = date.today()
    if not period:
        period = f"{today.year}-{today.month:02d}"
    # 格式錯誤（如 2026-13、abc、單獨一個 "Q"）過去會讓 date()/int() 拋出未
    # 被局部捕捉的 ValueError，靠 main.py 的全域 handler 兜底變成通用 500——
    # 跟已經修過的 _build_income_expense_scopes() month 參數驗證（見該函式）
    # 是同一種坑，這裡補上對稱的驗證。
    try:
        # Annual: bare 4-digit year
        if period.isdigit() and len(period) == 4:
            yr = int(period)
            d0 = date(yr, 1, 1)
            d1 = date(yr, 12, 31)
            return f"{yr} 年度", d0.isoformat(), d1.isoformat()
        if "Q" in period.upper():
            yr_s, q_s = period.upper().split("-Q")
            yr, q = int(yr_s), int(q_s)
            if q not in (1, 2, 3, 4):
                raise ValueError
            ms = (q - 1) * 3 + 1
            me = ms + 2
            d0 = date(yr, ms, 1)
            d1 = date(yr, me, monthrange(yr, me)[1])
            return f"{yr} 年第 {q} 季", d0.isoformat(), d1.isoformat()
        if len(period) != 7 or period[4] != "-":
            raise ValueError
        yr, mo = int(period[:4]), int(period[5:7])
        d0 = date(yr, mo, 1)
        d1 = date(yr, mo, monthrange(yr, mo)[1])
        return f"{yr} 年 {mo} 月", d0.isoformat(), d1.isoformat()
    except (ValueError, IndexError):
        raise HTTPException(400, f"period 參數格式錯誤（{period}），需為 YYYY、YYYY-MM 或 YYYY-Qn")


def _fmt(n):
    return f"NT$ {int(n or 0):,}"


def _live_dispatch_totals_by_quote(conn) -> dict:
    """回傳 {quote_no: 目前有效（非取消）承攬商派發總成本}，算法比照
    vendor_contractors.py::_dispatch_row() 的 grandTotal（含稅承攬商費用＋
    外包名單人員個別計費），供比對精算快照是否過期使用（見 _collect() 的
    staleSettlementCount）。"""
    rows = conn.execute("""
        SELECT quote_no, total_amount, tax_rate, personnel_json, items_json
        FROM contractor_dispatches WHERE status != 'cancelled'
    """).fetchall()
    totals: dict = {}
    for r in rows:
        amt = float(r["total_amount"] or 0)
        if not amt:
            try:
                items = json.loads(r["items_json"] or "[]")
                amt = sum(float(it.get("amount", 0) or 0) for it in items)
            except Exception:
                amt = 0
        rate = float(r["tax_rate"]) if r["tax_rate"] is not None else 0.05
        total_with_tax = amt + round(amt * rate)
        try:
            personnel = json.loads(r["personnel_json"] or "[]")
        except Exception:
            personnel = []
        personnel_total = sum(float(p.get("amount", 0) or 0) for p in personnel)
        totals[r["quote_no"]] = totals.get(r["quote_no"], 0) + total_with_tax + personnel_total
    return totals


def _build_name_index(user_by_id: dict) -> dict:
    """display_name → user id。**同名的一律不收**（值設成 None）。

    `caseRecord.roles.sales` 存的是顯示名稱字串不是 username，所以要反查。
    同名時硬猜一個等於把 A 的業績算到 B 頭上——寧可退回用名字分組（那至少
    是「兩個同名的人被合成一列」這種看得出來的錯，而不是靜默算錯人）。
    """
    idx: dict = {}
    for uid, info in user_by_id.items():
        name = (info.get("displayName") or "").strip()
        if not name:
            continue
        idx[name] = None if name in idx else uid
    return idx


def _case_sales_owner(cr: dict, row, name_index: dict, user_by_id: dict):
    """一張案件的業績算誰的 → (key, label)。

    2026-09-14 使用者交辦：「營運報表的業務員績效比較讀取案件管理的人員角色，
    業務負責的欄位」。兩者在實務上會不一致——**報價單的 `salesPerson` 是「開單
    的人」，案件管理 `caseRecord.roles.sales` 才是「這個案子歸誰的績效」**。

    優先序：
      1. `caseRecord.roles.sales`（使用者指定的口徑）。它存的是顯示名稱字串，
         能唯一反查到帳號就用 id 當 key（改名後仍歸同一人），反查不到或同名
         就用名字字串當 key——**不要因為反查不到就丟掉這筆歸屬**，那會讓案件
         默默跑到「開單的人」名下，正好是這次要修的問題。
      2. 沒填 `roles.sales` 的案件（含所有舊資料）退回原本的
         `sales_person_id` / `sales_person`。舊案件不回填是刻意的：那個欄位
         當初沒人填，補一個猜測值只會製造假資料。

    ⚠️ **部門彙總仍然依 `sales_person_id`**，沒有跟著改（見 `_row_dept()`）。
    那是另一條線：部門篩選會影響整份報表的取數範圍，改動面遠大於這次交辦，
    而且要先決定「案件的部門是跟著開單者還是跟著業務負責」。已記在 §11。
    """
    owner = ((cr.get("roles") or {}).get("sales") or "").strip() if isinstance(cr, dict) else ""
    if owner:
        uid = name_index.get(owner)
        if uid:
            return ("id", uid), (user_by_id[uid].get("displayName") or owner)
        return ("name", owner), owner

    spid = row["sales_person_id"] if "sales_person_id" in row.keys() else None
    if spid and spid in user_by_id:
        return ("id", spid), (user_by_id[spid].get("displayName")
                              or (row["sales_person"] or "") or "（未指定）")
    label = (row["sales_person"] or "") or "（未指定）"
    return ("name", label), label


def _collect(period_start: str, period_end: str, department_id: Optional[int] = None) -> dict:
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, status, customer_name, project_name,
               total, pretax, quote_date, sales_person, sales_person_id,
               net_margin_pct, direct_margin_pct,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
               json_extract(data_json,'$.caseRecord')                  AS cr_json,
               json_extract(data_json,'$.settlement.summary')          AS settle_json,
               json_extract(data_json,'$.settlement.settlementDate')   AS settle_date,
               json_extract(data_json,'$.settlement.finalizedBy')      AS settle_by,
               COALESCE(NULLIF(settle_status,''), json_extract(data_json,'$.settlement.status'), '') AS settle_status
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
        ORDER BY quote_date DESC
    """).fetchall()
    # sales_person_id -> department_id/department_name/目前顯示名稱，用來把報價單
    # 掛回部門（依部門彙總／department_id 篩選都靠這個對照表，quotations 本身沒有
    # 直接存部門），displayName 則供下方業務員績效/目標達成率用 id 比對、
    # 但顯示「目前」名稱（不受 quotations.sales_person 這個建立當下快照字串
    # 影響，見 case["salesPersonId"] 的說明）。
    user_by_id = {
        r["id"]: {"deptId": r["department_id"], "deptName": r["dept_name"], "displayName": r["display_name"]}
        for r in conn.execute("""
            SELECT u.id, u.department_id, u.display_name, d.name AS dept_name
            FROM users u LEFT JOIN departments d ON d.id = u.department_id
        """).fetchall()
    }
    # 案件實際「成案」的月份（見 helpers/quotations.py::quote_won_month_map()
    # docstring）——優先 quote_date，quote_date 缺漏或誤填未來日期才退回
    # audit_log 實際成案時間戳；monthly_trend() 已經用這個避開「舊案件補登/
    # 業務員手誤填未來日期，被歸錯月份甚至整筆從近N月報表消失」的坑，這裡
    # 一併存進每個 case，讓 _compute_achievement()（年度目標達成率）也能用
    # 同一套邏輯判斷案件算哪一年，不要各自用一半的日期判斷邏輯。
    name_index = _build_name_index(user_by_id)
    won_month = quote_won_month_map(conn)
    live_dispatch_totals = _live_dispatch_totals_by_quote(conn)
    conn.close()

    def _row_dept(row):
        """回傳 (department_id, department_name) 或 (None, '未分類')。"""
        info = user_by_id.get(row["sales_person_id"])
        return (info["deptId"], info["deptName"]) if info else (None, "未分類")

    if department_id:
        rows = [r for r in rows if _row_dept(r)[0] == department_id]
    allowed_quote_nos = {r["quote_no"] for r in rows} if department_id else None

    all_items, period_items, outstanding = [], [], []
    cases_all, cases_period = [], []
    dm: dict = {}   # 依部門彙總（跟下面「依業務員」的 sm 用同樣邏輯，多一層部門分組）

    for row in rows:
        cr = {}
        if row["cr_json"]:
            try: cr = json.loads(row["cr_json"])
            except Exception: pass

        total = row["total"] or 0
        pay   = (cr.get("payment") or {}).get("items", [])
        recv_amt = 0

        if pay:
            amounts = payment_item_amounts(total, pay, row["pretax"])
            for idx, pi in enumerate(pay):
                amt  = amounts[idx]
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
                    recv_amt += (aa if aa is not None else amt)

        settle = {}
        if row["settle_json"]:
            try: settle = json.loads(row["settle_json"])
            except Exception: pass

        qdate = row["quote_date"] or ""
        roles = cr.get("roles") or {}
        owner_key, owner_label = _case_sales_owner(cr, row, name_index, user_by_id)
        row_dept_id, row_dept_name = _row_dept(row)
        case = {
            "quoteNo":        row["quote_no"],
            "customer":       row["customer_name"] or "",
            "project":        row["project_name"]  or "",
            "salesPerson":    row["sales_person"]  or "",
            # sales_person 是建立當下快照的顯示名稱字串（歷史相容），業務員
            # 改名後舊案件仍是舊名字；salesPersonId 才是穩定的 FK，業務員績效
            # /目標達成率比對一律優先用這個 id，避免改名後該業務員的歷史業績
            # 被靜默拆成新舊兩個名字、或直接對不上年度目標設定（見 sm/
            # _compute_achievement() 用法）。
            "salesPersonId":  row["sales_person_id"],
            # 業績歸屬（2026-09-14）：優先案件管理的「業務負責」，見
            # _case_sales_owner()。`salesPerson`／`salesPersonId` 保留原意
            # （開單的人），清單與明細仍顯示那個，只有績效彙總改用這組。
            "ownerKey":       list(owner_key),
            "ownerName":      owner_label,
            "deptId":         row_dept_id,
            "deptName":       row_dept_name,
            "quoteDate":      qdate,
            "wonMonth":       won_month.get(row["quote_no"]) or qdate[:7],
            "dealTag":        row["deal_tag"]      or "",
            "hasPaymentItems": bool(pay),
            "roles":          roles,
            "total":          total,
            "pretax":         row["pretax"] or 0,
            "netMarginPct":   float(row["net_margin_pct"] or 0),
            "receivedAmount": recv_amt,
            "collectionRate": round(recv_amt / total * 100, 1) if total > 0 else 0,
            "settleStatus":   row["settle_status"] or "",
            # Use netMarginPct / netProfit so the comparison with quotation net_margin_pct is apples-to-apples.
            # Fallback to gross fields for legacy settlements saved before netProfit was recorded.
            "actualMarginPct": float(settle.get("netMarginPct") or settle.get("grossMarginPct") or 0) if settle else None,
            "grossProfit":     int(settle.get("netProfit") or settle.get("grossProfit") or 0) if settle else None,
            "settleSummary":   settle if settle else None,
            "settleDate":      row["settle_date"] or "",
            "settleBy":        row["settle_by"]   or "",
            "inPeriod":       period_start <= qdate[:10] <= period_end,
        }
        cases_all.append(case)
        if case["inPeriod"]:
            cases_period.append(case)

    # sales perf — 2026-09-14 起依**案件管理的「業務負責」**歸屬
    # （`caseRecord.roles.sales`），沒填的才退回開單者。解析邏輯集中在
    # `_case_sales_owner()`，年度目標達成率用的是同一組 key——**兩張表一定要
    # 用同一套歸屬**，不然同一個人在「業務員績效」與「目標達成率」會算到不同
    # 案件，而使用者是把這兩張表並排看的。
    sm: dict = {}
    for c in cases_all:
        k, label = tuple(c["ownerKey"]), c["ownerName"]
        sm.setdefault(k, {"salesPerson": label, "cases": 0, "total": 0, "received": 0,
                          "mRevSum": 0.0, "mProfitSum": 0.0,
                          "amRevSum": 0.0, "amProfitSum": 0.0, "amCnt": 0})
        sm[k]["cases"]    += 1
        sm[k]["total"]    += c["total"]
        sm[k]["received"] += c["receivedAmount"]
        sm[k]["mRevSum"]    += c["pretax"]
        sm[k]["mProfitSum"] += c["pretax"] * (c["netMarginPct"] or 0) / 100
        if c["actualMarginPct"] is not None and c["settleStatus"] == "finalized":
            sm[k]["amCnt"]       += 1
            sm[k]["amRevSum"]    += c["pretax"]
            sm[k]["amProfitSum"] += c["pretax"] * c["actualMarginPct"] / 100
    sales = []
    for v in sm.values():
        sales.append({
            "salesPerson":        v["salesPerson"],
            "caseCount":          v["cases"],
            "totalAmount":        v["total"],
            "receivedAmount":     v["received"],
            "collectionRate":     round(v["received"] / v["total"] * 100, 1) if v["total"] > 0 else 0,
            "avgMarginPct":       round(v["mProfitSum"] / v["mRevSum"] * 100, 1) if v["mRevSum"] > 0 else 0,
            "avgActualMarginPct": round(v["amProfitSum"] / v["amRevSum"] * 100, 1) if v["amRevSum"] > 0 else None,
            "settledCount":       v["amCnt"],
        })
    sales.sort(key=lambda x: x["totalAmount"], reverse=True)

    # dept perf（依部門彙總，跟上面「依業務員」同樣算法，多一層部門分組；
    # 查無 sales_person_id 對應部門的案件歸類「未分類」）
    for c in cases_all:
        k = c["deptName"] or "未分類"
        dm.setdefault(k, {"deptId": c["deptId"], "deptName": k, "cases": 0, "total": 0, "received": 0,
                          "mRevSum": 0.0, "mProfitSum": 0.0})
        dm[k]["cases"]    += 1
        dm[k]["total"]    += c["total"]
        dm[k]["received"] += c["receivedAmount"]
        dm[k]["mRevSum"]    += c["pretax"]
        dm[k]["mProfitSum"] += c["pretax"] * (c["netMarginPct"] or 0) / 100
    dept_perf = []
    for v in dm.values():
        dept_perf.append({
            "deptId":         v["deptId"],
            "deptName":       v["deptName"],
            "caseCount":      v["cases"],
            "totalAmount":    v["total"],
            "receivedAmount": v["received"],
            "collectionRate": round(v["received"] / v["total"] * 100, 1) if v["total"] > 0 else 0,
            "avgMarginPct":   round(v["mProfitSum"] / v["mRevSum"] * 100, 1) if v["mRevSum"] > 0 else 0,
        })
    dept_perf.sort(key=lambda x: x["totalAmount"], reverse=True)

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
    if allowed_quote_nos is not None:
        wrows = [r for r in wrows if r["quote_no"] in allowed_quote_nos]
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

    # settle overdue: 已結案但未完成精算的案件
    conn3 = get_db()
    ov_rows = conn3.execute("""
        SELECT quote_no, customer_name, project_name, sales_person, updated_at
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') = '已結案'
          AND COALESCE(NULLIF(settle_status,''), json_extract(data_json,'$.settlement.status'), '') != 'finalized'
        ORDER BY updated_at ASC
    """).fetchall()
    conn3.close()
    if allowed_quote_nos is not None:
        ov_rows = [r for r in ov_rows if r["quote_no"] in allowed_quote_nos]
    settle_overdue = [
        {
            "quoteNo":     r["quote_no"],
            "customer":    r["customer_name"] or "",
            "project":     r["project_name"]  or "",
            "salesPerson": r["sales_person"]  or "",
            "closedAt":    (r["updated_at"]   or "")[:10],
        }
        for r in ov_rows
    ]

    # backlog: 進行中案件的剩餘應收金額
    backlog = sum(c["total"] - c["receivedAmount"] for c in cases_all if c["dealTag"] == "已成案")

    # 精算快照過期：finalized 案件的 dispatchTotal 快照 vs 目前即時計算值不一致，
    # 代表承攬商成本在精算完結後又異動過，這份報表用到的毛利/業務員績效/部門
    # 績效數字可能已經跟實際不符（同一份快照，settlement.html／案件管理財務Tab
    # 各自有逐案件的即時比對banner，這裡只給總數當全域警訊，不逐案列出——
    # 要看是哪幾筆，去對應案件本身的頁面會有詳細比較）。
    stale_settlement_count = 0
    for c in cases_all:
        if c["settleStatus"] != "finalized" or not c["settleSummary"]:
            continue
        frozen = c["settleSummary"].get("dispatchTotal")
        if frozen is None:
            continue
        live = live_dispatch_totals.get(c["quoteNo"], 0)
        if round(live) != round(frozen):
            stale_settlement_count += 1

    # 已成案/已結案但完全沒有收款期別（caseRecord.payment.items 是空的）：這類
    # 案件的合約金額不會計入 totalReceivable/收款率/毛利等任何金額類統計（下面
    # all_items 從頭到尾就沒有這筆案件的資料），但案件數量統計（totalCases 等）
    # 仍然算得到，兩者對不上且完全沒有提示——正常情況下 case-management.js
    # 開案件時會自動帶入預設收款期別，這裡列出的通常是從未被人工打開過的案件。
    cases_without_payment_items = [
        {"quoteNo": c["quoteNo"], "customer": c["customer"], "project": c["project"],
         "salesPerson": c["salesPerson"], "dealTag": c["dealTag"], "total": c["total"]}
        for c in cases_all if not c["hasPaymentItems"]
    ]

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
            "backlog":                int(backlog),
            "settleOverdueCount":     len(settle_overdue),
            "staleSettlementCount":   stale_settlement_count,
            "missingPaymentItemsCount": len(cases_without_payment_items),
        },
        "periodItems":    period_items,
        "outstanding":    outstanding,
        "allItems":       all_items,
        "casesAll":       cases_all,
        "casesPeriod":    cases_period,
        "salesPerf":      sales,
        "deptPerf":       dept_perf,
        "marginCases":    [c for c in cases_all if c["actualMarginPct"] is not None and c["settleStatus"] == "finalized"],
        "warranty":       warr[:30],
        "settleOverdue":  settle_overdue,
        "casesWithoutPaymentItems": cases_without_payment_items,
    }


# ── Achievement computation ───────────────────────────────────────────────────

def _owner_key_of(c: dict) -> tuple:
    """案件的業績歸屬 key。

    `_collect()` 產出的案件一定有 `ownerKey`（見 `_case_sales_owner()`）。
    沒有的情況只有一種：直接拿手組的 dict 呼叫 `_compute_achievement()`
    （單元測試就是這樣用的，它是純函式）。那時退回舊欄位，語意跟改動前相同，
    不要讓一個防禦性的缺欄位把整個人的業績歸成空。
    """
    k = c.get("ownerKey")
    if k:
        return tuple(k)
    spid = c.get("salesPersonId")
    if spid:
        return ("id", spid)
    return ("name", c.get("salesPerson") or "（未指定）")


def _compute_achievement(year: int, targets: dict, cases_all: list) -> dict:
    """Compute YTD metrics vs annual targets for a given year.

    案件歸入哪一年用 c['wonMonth']（_collect() 算好的，見 quote_won_month_map()
    docstring），不是直接看 quoteDate——2026-08-28 修正：這裡原本直接用
    quoteDate 篩選，跟 monthly_trend() 已經修過的邏輯不一致，會讓「補登的舊
    案件」或「quote_date 誤填未來日期」的案子被算進錯的年度目標達成率。"""
    if not targets or targets.get("year") != year:
        return {"year": year, "hasTargets": False}

    ann    = targets.get("annual") or {}
    yr_str = str(year)
    today  = date.today()

    if today.year > year:
        frac = 1.0
    elif today.year < year:
        frac = 0.0
    else:
        yday  = today.timetuple().tm_yday
        total = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
        frac  = round(yday / total, 3)

    ytd          = [c for c in cases_all if (c.get("wonMonth") or c["quoteDate"] or "").startswith(yr_str)]
    ytd_cases    = len(ytd)
    ytd_revenue  = sum(c["total"] for c in ytd)
    ytd_coll     = sum(c["receivedAmount"] for c in ytd)
    ytd_col_rate = round(ytd_coll / ytd_revenue * 100, 1) if ytd_revenue > 0 else 0.0

    fin_ytd    = [c for c in ytd if c["settleStatus"] == "finalized" and c["grossProfit"] is not None]
    ytd_gp     = sum(c["grossProfit"] for c in fin_ytd)
    # Revenue-weighted (by pretax) average margin — a simple mean over case count lets a single
    # small high-margin case skew the YTD figure, especially early in the year with few finalized cases.
    amp_rev  = sum(c["pretax"] for c in fin_ytd if c["actualMarginPct"] is not None)
    amp_prof = sum(c["pretax"] * c["actualMarginPct"] / 100 for c in fin_ytd if c["actualMarginPct"] is not None)
    ytd_margin = round(amp_prof / amp_rev * 100, 1) if amp_rev > 0 else 0.0

    def _rate(actual, target):
        return round(actual / target * 100, 1) if (target and target != 0) else None

    def _pro(target):
        return round(target * frac) if target else 0

    t_rev  = ann.get("revenue")          or 0
    t_cs   = ann.get("newCases")         or 0
    t_colA = ann.get("collectionAmount") or 0
    t_colR = ann.get("collectionRate")   or 0
    t_mgn  = ann.get("avgNetMarginPct")  or 0
    t_gp   = ann.get("grossProfit")      or 0

    # 目標設定（operating_targets.salesperson[]）只存業務員「名字」，
    # quotations.sales_person 卻是建立當下快照的字串——業務員改名後
    # （display_name 可由 admin 編輯，見 auth.py update_user()）舊案件仍是
    # 舊名字，直接拿名字互相比對會讓改名前的業績從目標達成率裡消失。
    # 這裡把目標設定的名字解析成目前對應的 user id，案件比對優先用
    # salesPersonId（穩定 FK，不受改名影響）；查無對應使用者（名字打錯字、
    # 離職刪除帳號等）才退回原本的名字字串比對，不砍歷史涵蓋範圍。
    conn4 = get_db()
    name_to_id = {r["display_name"]: r["id"] for r in conn4.execute("SELECT id, display_name FROM users").fetchall()}
    conn4.close()

    sp_acv = []
    for sp_t in (targets.get("salesperson") or []):
        sn   = sp_t.get("name") or ""
        sp_id = name_to_id.get(sn)
        # 2026-09-14：改用跟「業務員績效」同一套歸屬（`ownerKey`，見
        # `_case_sales_owner()`）。**兩張表必須一致**——使用者是把它們並排看的，
        # 一邊算「案件的業務負責」、另一邊算「開單的人」，同一個人的兩個數字
        # 對不起來而且看不出為什麼。
        # `ownerKey` 是 ("id", uid) 或 ("name", 顯示名稱)，兩種都要比對得到：
        # 目標設定存的是名字，名字解析得到帳號就比 id，否則比名字。
        if sp_id is not None:
            sy_c = [c for c in ytd if _owner_key_of(c) in (("id", sp_id), ("name", sn))]
        else:
            sy_c = [c for c in ytd if _owner_key_of(c) == ("name", sn)]
        sy_r = sum(c["total"] for c in sy_c)
        sp_acv.append({
            "name":          sn,
            "targetRevenue": sp_t.get("revenue") or 0,
            "targetCases":   sp_t.get("cases")   or 0,
            "ytdRevenue":    sy_r,
            "ytdCases":      len(sy_c),
            "revenueRate":   _rate(sy_r, sp_t.get("revenue") or 0),
            "caseRate":      _rate(len(sy_c), sp_t.get("cases") or 0),
        })

    return {
        "year":         year,
        "hasTargets":   True,
        "daysFraction": frac,
        "prorataLabel": f"年度已過 {int(frac * 100)}%，按比例預期進度",
        "annual": {
            "revenue":      {"actual": ytd_revenue, "target": t_rev,  "rate": _rate(ytd_revenue, t_rev),  "prorata": _pro(t_rev)},
            "newCases":     {"actual": ytd_cases,   "target": t_cs,   "rate": _rate(ytd_cases, t_cs),     "prorata": int(_pro(t_cs))},
            "collectionAmt":{"actual": ytd_coll,    "target": t_colA, "rate": _rate(ytd_coll, t_colA),    "prorata": _pro(t_colA)},
            "collectionRate":{"actual":ytd_col_rate,"target": t_colR, "rate": _rate(ytd_col_rate, t_colR),"prorata": None},
            "avgMarginPct": {"actual": ytd_margin,  "target": t_mgn,  "rate": _rate(ytd_margin, t_mgn),   "prorata": None},
            "grossProfit":  {"actual": ytd_gp,      "target": t_gp,   "rate": _rate(ytd_gp, t_gp),        "prorata": _pro(t_gp)},
        },
        "salesperson": sp_acv,
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


# openpyxl 會把「開頭是 =/+/-/@ 的字串」自動當成公式寫入（Cell.value 的
# bind_value() 行為），不是單純字面字串——只要使用者能在客戶名稱/專案名稱/
# 款項備注/發票號碼/承攬商名稱/料件名稱等任一自由文字欄位填入
# `=HYPERLINK(...)` 或舊式 DDE payload，之後任何人匯出本報表 Excel 並在
# Excel 開啟，就可能觸發公式/連結（CWE-1236，CSV/Formula Injection 同類
# 手法對 xlsx 一樣有效）。PDF/HTML 路徑已經用 html.escape() 處理過這類風險
# （見 _build_report_html() 的 esc()），這裡比照同樣的防禦精神，把觸發字元
# 開頭的字串前面補一個單引號讓 openpyxl 存成純文字。
_XL_FORMULA_TRIGGERS = ("=", "+", "-", "@")


def _xl_safe(val):
    if isinstance(val, str) and val[:1] in _XL_FORMULA_TRIGGERS:
        return "'" + val
    return val


def _set_row(ws, row_idx, values, font=None, fill=None, border=None, aligns=None, height=None):
    for ci, val in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=ci, value=_xl_safe(val))
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
        ("合約總案數",          s["totalCases"],          ""),
        ("進行中案件",          s["activeCases"],          ""),
        ("已結案件",            s["closedCases"],          ""),
        ("本期新成案",          s["periodCases"],          ""),
        ("在製訂單 (Backlog)",  _fmt(s["backlog"]),        "進行中案件未收款合計"),
        ("保固到期預警",        s["warrantyAlerts"],       "90天內"),
        ("已結案未精算",        f"{s['settleOverdueCount']} 件", "待補精算" if s["settleOverdueCount"] > 0 else "無"),
    ]
    for label, val, note in case_rows:
        _set_row(ws1, r, [label, val, note, ""],
                 font=mk(size=9),
                 border=BD,
                 aligns=[al("left"), al("right"), al("left"), al("left")],
                 height=18)
        ws1.cell(row=r, column=1).font = mk(bold=True, size=9, color=C_GRAY)
        vc = C_RED if label == "已結案未精算" and s["settleOverdueCount"] > 0 else C_BLUE if label == "在製訂單 (Backlog)" else C_DARK
        ws1.cell(row=r, column=2).font = mk(bold=True, size=12, color=vc)
        r += 1

    # ── Sheet 2: 目標達成率 ──────────────────────────────────────────────────────
    acv      = data.get("achievement") or {}
    acv_year = acv.get("year") or int(gen_at[:4])

    ws_acv = wb.create_sheet("目標達成率")
    ws_acv.sheet_view.showGridLines = False
    ws_acv.column_dimensions["A"].width = 22
    ws_acv.column_dimensions["B"].width = 18
    ws_acv.column_dimensions["C"].width = 18
    ws_acv.column_dimensions["D"].width = 12
    ws_acv.column_dimensions["E"].width = 18
    ws_acv.column_dimensions["F"].width = 14

    ws_acv.merge_cells("A1:F1")
    c = ws_acv["A1"]
    c.value = f"{_COMPANY} — {acv_year} 年度目標達成率"
    c.font  = mk(bold=True, size=14, color=C_WHITE)
    c.fill  = fill("7C3AED")
    c.alignment = al("center")
    ws_acv.row_dimensions[1].height = 32

    ws_acv.merge_cells("A2:F2")
    c = ws_acv["A2"]
    c.value = acv.get("prorataLabel", "尚未設定年度目標") if acv.get("hasTargets") else "尚未設定年度目標"
    c.font  = mk(size=9, color="9CA3AF")
    c.fill  = fill(C_DARK)
    c.alignment = al("center")
    ws_acv.row_dimensions[2].height = 16

    ws_acv.row_dimensions[3].height = 8

    if not acv.get("hasTargets"):
        ws_acv.merge_cells("A4:F4")
        msg = ws_acv["A4"]
        msg.value = "請於系統設定中配置年度目標後，本頁將自動顯示各指標達成率分析。"
        msg.font  = mk(size=10, color=C_GRAY, italic=True)
        msg.alignment = al("center")
    else:
        ann = acv.get("annual", {})

        ws_acv.merge_cells("A4:F4")
        c = ws_acv["A4"]
        c.value = "年度指標達成率"
        c.font  = mk(bold=True, size=10, color=C_WHITE)
        c.fill  = fill("7C3AED")
        c.alignment = al("left")
        ws_acv.row_dimensions[4].height = 20

        _set_row(ws_acv, 5,
                 ["指標", "年度目標", "YTD 實績", "達成率", "按時間比例目標", "狀態"],
                 font=mk(bold=True, size=9, color=C_WHITE),
                 fill=fill("374151"), border=BD,
                 aligns=[al("left"), al("right"), al("right"), al("right"), al("right"), al("center")],
                 height=20)

        def _acv_xl_row(ws, ri, label, val_fn, actual, target, rate, prorata_val):
            pro_s  = val_fn(prorata_val) if prorata_val is not None else "—"
            rate_s = f"{rate:.1f}%" if rate is not None else "—"
            if rate is None:
                rc, st, bg = C_GRAY,   "無目標", C_WHITE
            elif rate >= 95:
                rc, st, bg = C_GREEN,  "達標 ✓", C_LGREEN
            elif rate >= 80:
                rc, st, bg = C_ORANGE, "追趕中", C_LYELLOW
            else:
                rc, st, bg = C_RED,    "落後 ✗", C_LRED
            _set_row(ws, ri, [label, val_fn(target), val_fn(actual), rate_s, pro_s, st],
                     font=mk(size=9), fill=fill(bg), border=BD,
                     aligns=[al("left"), al("right"), al("right"), al("right"), al("right"), al("center")],
                     height=18)
            ws.cell(row=ri, column=4).font = mk(bold=True, size=9, color=rc)
            ws.cell(row=ri, column=6).font = mk(bold=True, size=9, color=rc)

        def _xl_m(n): return _fmt(n)
        def _xl_p(n): return f"{n or 0:.1f}%"
        def _xl_c(n): return f"{int(n or 0)} 件"

        ri      = 6
        rev_d   = ann.get("revenue",       {})
        cas_d   = ann.get("newCases",      {})
        colA_d  = ann.get("collectionAmt", {})
        colR_d  = ann.get("collectionRate",{})
        mgn_d   = ann.get("avgMarginPct",  {})
        gp_d    = ann.get("grossProfit",   {})

        _acv_xl_row(ws_acv, ri,   "年度合約總額", _xl_m, rev_d.get("actual",0),  rev_d.get("target",0),  rev_d.get("rate"),  rev_d.get("prorata"))
        _acv_xl_row(ws_acv, ri+1, "年度新成案數", _xl_c, cas_d.get("actual",0),  cas_d.get("target",0),  cas_d.get("rate"),  cas_d.get("prorata"))
        _acv_xl_row(ws_acv, ri+2, "年度收款金額", _xl_m, colA_d.get("actual",0), colA_d.get("target",0), colA_d.get("rate"), colA_d.get("prorata"))
        _acv_xl_row(ws_acv, ri+3, "收款率",       _xl_p, colR_d.get("actual",0), colR_d.get("target",0), colR_d.get("rate"), None)
        _acv_xl_row(ws_acv, ri+4, "平均淨毛利率", _xl_p, mgn_d.get("actual",0),  mgn_d.get("target",0),  mgn_d.get("rate"),  None)
        _acv_xl_row(ws_acv, ri+5, "年度實際毛利", _xl_m, gp_d.get("actual",0),   gp_d.get("target",0),   gp_d.get("rate"),   gp_d.get("prorata"))
        ri += 7

        sp_acv = acv.get("salesperson") or []
        if sp_acv:
            ws_acv.merge_cells(f"A{ri}:F{ri}")
            c = ws_acv.cell(row=ri, column=1, value="業務員目標達成率")
            c.font  = mk(bold=True, size=10, color=C_WHITE)
            c.fill  = fill(C_BLUE)
            c.alignment = al("left")
            ws_acv.row_dimensions[ri].height = 20
            ri += 1

            _set_row(ws_acv, ri,
                     ["業務員", "配額目標（元）", "YTD 合約（元）", "合約達成率", "案件配額", "案件達成率"],
                     font=mk(bold=True, size=9, color=C_WHITE),
                     fill=fill("374151"), border=BD,
                     aligns=[al("left"), al("right"), al("right"), al("right"), al("right"), al("right")],
                     height=20)
            ri += 1

            for sp in sp_acv:
                rv  = sp.get("revenueRate")
                cs  = sp.get("caseRate")
                rv_c = C_GREEN if (rv is not None and rv >= 95) else C_ORANGE if (rv is not None and rv >= 80) else C_RED if rv is not None else C_GRAY
                cs_c = C_GREEN if (cs is not None and cs >= 95) else C_ORANGE if (cs is not None and cs >= 80) else C_RED if cs is not None else C_GRAY
                bg   = C_LGREEN if (rv is not None and rv >= 95) else C_LYELLOW if (rv is not None and rv >= 80) else C_LRED if rv is not None else C_WHITE
                _set_row(ws_acv, ri,
                         [sp["name"], sp["targetRevenue"], sp["ytdRevenue"],
                          f"{rv:.1f}%" if rv is not None else "—",
                          f"{int(sp['targetCases'] or 0)} 件",
                          f"{cs:.1f}%" if cs is not None else "—"],
                         font=mk(size=9), fill=fill(bg), border=BD,
                         aligns=[al("left"), al("right"), al("right"), al("right"), al("right"), al("right")],
                         height=18)
                for ci in [2, 3]:
                    ws_acv.cell(row=ri, column=ci).number_format = '#,##0'
                ws_acv.cell(row=ri, column=4).font = mk(bold=True, size=9, color=rv_c)
                ws_acv.cell(row=ri, column=6).font = mk(bold=True, size=9, color=cs_c)
                ri += 1

    # ── Sheet 3: 本期收款明細 ────────────────────────────────────────────────
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

    # ── Sheet 4: 未收款清單 ──────────────────────────────────────────────────
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

    # ── Sheet 4b/4c: 當月收支／今年度收支（2026-08-30 重構，取代原本單一
    # 「月支出」sheet）──────────────────────────────────────────────────────
    # 使用者要求月支出要能看到「當月」逐筆支出項（含案件／品項金額），且跟
    # 「當月收入」各自獨立列出，另外「今年度」也要有對應的收入/支出逐筆明細，
    # 不是只有月支出才有明細、收入完全沒有。拆成兩張獨立分頁：「當月收支」
    # （這次報表鎖定的月份）跟「今年度收支」（該月份所屬整年，含既有的年度
    # 月支出趨勢矩陣＋逐筆明細）。
    exp = data.get("expenses") or {"monthly": [], "totals": {}, "details": {}}
    cat_label = {"contractor": "承攬商派發", "equipment": "設備進貨", "material": "料件進貨", "other": "其他支出"}
    income_hdrs = ["案件號", "客戶", "專案名稱", "業務員", "款項類型",
                   "應收金額", "收款日期", "實收金額", "手續費", "實收淨額", "發票號碼"]
    income_cols = [13, 18, 18, 10, 9, 12, 11, 12, 10, 12, 12]
    expense_hdrs = ["日期", "類別", "關聯案件", "說明", "金額", "發票/收據附件"]

    def write_income_table(ws, start_row, items, banner):
        ws.merge_cells(f"A{start_row}:{get_column_letter(len(income_hdrs))}{start_row}")
        c = ws.cell(row=start_row, column=1, value=banner)
        c.font = mk(bold=True, size=11, color=C_WHITE)
        c.fill = fill(C_GREEN)
        c.alignment = al("center")
        ws.row_dimensions[start_row].height = 22
        r = start_row + 1
        _set_row(ws, r, income_hdrs, font=mk(bold=True, size=9, color=C_WHITE),
                 fill=fill("374151"), border=BD, aligns=[al("center")], height=20)
        r += 1
        for item in items:
            aa = item["actualAmount"]
            _set_row(ws, r, [
                item["quoteNo"], item["customer"], item["project"], item["salesPerson"], item["type"],
                item["amount"], item["receivedAt"], aa if aa is not None else item["amount"],
                item["feeAmount"] or None, item["netAmount"], item["invoiceNo"] or "",
            ], font=mk(size=9), fill=fill(C_LGREEN), border=BD,
               aligns=[al("left"), al("left"), al("left"), al("left"), al("center"),
                       al("right"), al("center"), al("right"), al("right"), al("right"), al("left")],
               height=18)
            for ci in (6, 8, 9, 10):
                ws.cell(row=r, column=ci).number_format = '#,##0'
            r += 1
        _set_row(ws, r, ["合計（" + str(len(items)) + " 筆）", "", "", "", "",
                          sum(i["amount"] for i in items), "",
                          sum((i["actualAmount"] if i["actualAmount"] is not None else i["amount"]) for i in items),
                          sum(i["feeAmount"] or 0 for i in items), sum(i["netAmount"] or 0 for i in items), ""],
                 font=mk(bold=True, size=9, color=C_WHITE), fill=fill(C_DARK), border=BD,
                 aligns=[al("left")] + [al("right")] * 10, height=20)
        for ci in (6, 8, 9, 10):
            ws.cell(row=r, column=ci).number_format = '#,##0'
        return r + 2

    def write_expense_table(ws, start_row, items, banner):
        ws.merge_cells(f"A{start_row}:{get_column_letter(len(income_hdrs))}{start_row}")
        c = ws.cell(row=start_row, column=1, value=banner)
        c.font = mk(bold=True, size=11, color=C_WHITE)
        c.fill = fill("7C3AED")
        c.alignment = al("center")
        ws.row_dimensions[start_row].height = 22
        r = start_row + 1
        _set_row(ws, r, expense_hdrs, font=mk(bold=True, size=9, color=C_WHITE),
                 fill=fill("374151"), border=BD, aligns=[al("center")], height=20)
        r += 1
        for it in items:
            file_names = "、".join(f.get("filename", "") for f in (it.get("files") or []))
            _set_row(ws, r, [it.get("date", ""), cat_label.get(it.get("cat"), it.get("cat", "")),
                              it.get("quoteNo", ""), it.get("desc", ""), it.get("amount", 0), file_names],
                     font=mk(size=9), fill=fill(C_LYELLOW), border=BD,
                     aligns=[al("center"), al("center"), al("left"), al("left"), al("right"), al("left")], height=18)
            ws.cell(row=r, column=5).number_format = '#,##0'
            r += 1
        _set_row(ws, r, ["合計（" + str(len(items)) + " 筆）", "", "", "", sum(i.get("amount", 0) for i in items), ""],
                 font=mk(bold=True, size=9, color=C_WHITE), fill=fill(C_DARK), border=BD,
                 aligns=[al("left"), al("left"), al("left"), al("left"), al("right"), al("left")], height=20)
        ws.cell(row=r, column=5).number_format = '#,##0'
        return r + 2

    def write_net_summary(ws, start_row, income_total, expense_total, label):
        _set_row(ws, start_row, [f"{label}收入合計", income_total, f"{label}支出合計", expense_total,
                                  f"{label}淨額", income_total - expense_total],
                 font=mk(bold=True, size=10, color=C_WHITE), fill=fill(C_DARK), border=BD,
                 aligns=[al("left"), al("right"), al("left"), al("right"), al("left"), al("right")], height=22)
        for ci in (2, 4, 6):
            ws.cell(row=start_row, column=ci).number_format = '#,##0'
        ws.cell(row=start_row, column=6).font = mk(
            bold=True, size=10,
            color=(C_GREEN if income_total - expense_total >= 0 else C_RED))
        return start_row + 2

    # ── Sheet 4b: 當月收支 ──────────────────────────────────────────────────
    ws_month = wb.create_sheet("當月收支")
    ws_month.sheet_view.showGridLines = False
    for i, w in enumerate(income_cols, 1):
        ws_month.column_dimensions[get_column_letter(i)].width = w
    month_label = data.get("expenseMonth", "")
    ws_month.merge_cells(f"A1:{get_column_letter(len(income_hdrs))}1")
    c = ws_month["A1"]
    c.value = f"{month_label} 當月收支明細"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill(C_DARK)
    c.alignment = al("center")
    ws_month.row_dimensions[1].height = 26

    month_income_items = data.get("monthIncomeItems") or []
    month_expense_items = data.get("monthExpenseItems") or []
    r_i = write_income_table(ws_month, 3, month_income_items, "當月收入明細")
    r_i = write_expense_table(ws_month, r_i, month_expense_items, "當月支出明細")
    write_net_summary(ws_month, r_i,
                       data.get("monthIncomeTotal", 0), data.get("monthExpenseTotal", 0), "當月")

    # ── Sheet 4b-2: 本季收支（2026-09-10）──────────────────────────────────
    # 只有匯出時帶了 quarter 參數才會有這張表（畫面上期別切在「季報」時前端才送）。
    # 刻意「加一張」而不是「取代當月那張」：當月/本季/今年度三種口徑並存，跟畫面上
    # 三個範圍鈕一致，也不改變既有不帶 quarter 的匯出結果。
    _q = data.get("expenseQuarter")
    if _q:
        ws_q = wb.create_sheet("本季收支")
        ws_q.sheet_view.showGridLines = False
        for i, w in enumerate(income_cols, 1):
            ws_q.column_dimensions[get_column_letter(i)].width = w
        ws_q.merge_cells(f"A1:{get_column_letter(len(income_hdrs))}1")
        c = ws_q["A1"]
        c.value = f"{data.get('expensesYear', '')} 年第 {_q} 季收支明細"
        c.font  = mk(bold=True, size=12, color=C_WHITE)
        c.fill  = fill(C_DARK)
        c.alignment = al("center")
        ws_q.row_dimensions[1].height = 26
        r_q = write_income_table(ws_q, 3, data.get("quarterIncomeItems") or [], "本季收入明細")
        r_q = write_expense_table(ws_q, r_q, data.get("quarterExpenseItems") or [], "本季支出明細")
        write_net_summary(ws_q, r_q,
                          data.get("quarterIncomeTotal", 0), data.get("quarterExpenseTotal", 0), "本季")

    # ── Sheet 4c: 今年度收支 ────────────────────────────────────────────────
    ws_year = wb.create_sheet("今年度收支")
    ws_year.sheet_view.showGridLines = False
    for i, w in enumerate(income_cols, 1):
        ws_year.column_dimensions[get_column_letter(i)].width = w

    ws_year.merge_cells(f"A1:{get_column_letter(len(income_hdrs))}1")
    c = ws_year["A1"]
    c.value = f"{data.get('expensesYear', '')}年度收支總表"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill(C_DARK)
    c.alignment = al("center")
    ws_year.row_dimensions[1].height = 26

    # 年度月支出趨勢矩陣（既有，保留供逐月比較用）
    ws_year.merge_cells(f"A3:{get_column_letter(len(income_hdrs))}3")
    dc = ws_year.cell(row=3, column=1, value="年度月支出結構（逐月比較）")
    dc.font = mk(bold=True, size=11, color=C_WHITE)
    dc.fill = fill("7C3AED")
    dc.alignment = al("center")
    ws_year.row_dimensions[3].height = 22
    matrix_hdrs = ["月份", "承攬商派發", "設備進貨", "料件進貨", "其他支出", "合計"]
    _set_row(ws_year, 4, matrix_hdrs, font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD, aligns=[al("center")], height=20)
    r_i = 5
    for m in exp.get("monthly") or []:
        _set_row(ws_year, r_i,
                 [m["label"], m["contractor"], m["equipment"], m["material"], m["other"], m["total"]],
                 font=mk(size=9), fill=fill(C_WHITE), border=BD,
                 aligns=[al("center")] + [al("right")] * 5, height=18)
        for ci in (2, 3, 4, 5, 6):
            ws_year.cell(row=r_i, column=ci).number_format = '#,##0'
        r_i += 1
    tot = exp.get("totals") or {}
    _set_row(ws_year, r_i,
             ["全年合計", tot.get("contractor", 0), tot.get("equipment", 0),
              tot.get("material", 0), tot.get("other", 0), tot.get("total", 0)],
             font=mk(bold=True, size=9, color=C_WHITE), fill=fill(C_DARK), border=BD,
             aligns=[al("left")] + [al("right")] * 5, height=20)
    for ci in (2, 3, 4, 5, 6):
        ws_year.cell(row=r_i, column=ci).number_format = '#,##0'
    r_i += 2

    year_income_items = data.get("yearIncomeItems") or []
    all_year_expense = []
    for cat, rows_ in (exp.get("details") or {}).items():
        for it in rows_:
            all_year_expense.append({**it, "cat": cat})
    all_year_expense.sort(key=lambda x: x.get("date") or "", reverse=True)

    r_i = write_income_table(ws_year, r_i, year_income_items, "今年度收入明細")
    r_i = write_expense_table(ws_year, r_i, all_year_expense, "今年度支出明細")
    write_net_summary(ws_year, r_i,
                       data.get("yearIncomeTotal", 0), tot.get("total", 0), "今年度")

    # ── Sheet 5: 案件清單 ────────────────────────────────────────────────────
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

    # 依月份區分（2026-08-26）：casesAll 本來就依 quote_date DESC 排序，逐筆掃描、
    # 年月變化時插入一列合併儲存格的月份標題列（含當月案件數/合約金額小計），
    # 不需要另外排序或分組運算。
    r_i = 3
    last_ym = None
    for c_ in data["casesAll"]:
        ym = (c_["quoteDate"] or "")[:7]
        if ym != last_ym:
            ym_label = f"{ym[:4]}年{int(ym[5:7])}月" if ym else "（未填報價日）"
            ws4.merge_cells(f"A{r_i}:{get_column_letter(len(hdrs4))}{r_i}")
            hc = ws4.cell(row=r_i, column=1, value=ym_label)
            hc.font = mk(bold=True, size=9, color=C_GRAY)
            hc.fill = fill(C_LGRAY)
            hc.alignment = al("left")
            ws4.row_dimensions[r_i].height = 18
            r_i += 1
            last_ym = ym
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
        r_i += 1

    # ── Sheet 6: 業務員績效 ──────────────────────────────────────────────────
    ws5 = wb.create_sheet("業務員績效")
    ws5.sheet_view.showGridLines = False
    hdrs5 = ["業務員","案件數","合約總額","已收款","收款率(%)","預估毛利率","實際毛利率","精算件數"]
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

    # ── Sheet 7: 毛利分析 ────────────────────────────────────────────────────
    ws6 = wb.create_sheet("毛利分析")
    ws6.sheet_view.showGridLines = False
    # 原始預估 / 實際精算 完整對照欄位
    hdrs6 = [
        "案件號","客戶","專案名稱","業務員","案件進度","報價稅前",
        # 原始預估
        "原始成本","原始毛利率","原始淨利率","原始預估淨利",
        # 實際精算
        "品項成本","額外支出","實際總成本","真實毛利率","真實淨利率","真實淨利",
        # 差異
        "差異(pp)","差異金額",
        # 精算資訊
        "精算狀態","精算日期","完結人",
    ]
    cols6 = [13,18,18,10,9,13, 13,11,11,13, 13,11,13,11,11,13, 9,13, 9,11,10]
    for i, (h, w) in enumerate(zip(hdrs6, cols6), 1):
        ws6.column_dimensions[get_column_letter(i)].width = w

    ws6.merge_cells(f"A1:{get_column_letter(len(hdrs6))}1")
    c = ws6["A1"]
    c.value = "毛利分析 — 精算利潤對照（已完結案件）"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill("7C3AED")
    c.alignment = al("center")
    ws6.row_dimensions[1].height = 24

    # 群組標頭列 (row 2)
    grp_labels = [
        (1,6,"基本資訊","374151"), (7,10,"原始報價預估","475569"),
        (11,16,"實際成本精算","92400E"), (17,18,"差異","7C3AED"),
        (19,21,"精算資訊","374151"),
    ]
    for sc, ec, lbl, clr in grp_labels:
        if sc == ec:
            ws6.cell(row=2, column=sc).value = lbl
        else:
            ws6.merge_cells(start_row=2, start_column=sc, end_row=2, end_column=ec)
            ws6.cell(row=2, column=sc).value = lbl
        for col in range(sc, ec+1):
            ws6.cell(row=2, column=col).font      = mk(bold=True, size=9, color=C_WHITE)
            ws6.cell(row=2, column=col).fill      = fill(clr)
            ws6.cell(row=2, column=col).alignment = al("center")
    ws6.row_dimensions[2].height = 16

    _set_row(ws6, 3, hdrs6,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)

    for r_i, mc in enumerate(data["marginCases"], 4):
        s   = mc.get("settleSummary") or {}
        net = mc["netMarginPct"] or 0
        act = mc["actualMarginPct"] or 0
        diff    = round(act - net, 1)
        act_gp  = mc["grossProfit"] or 0
        est_gp  = int((mc["pretax"] or 0) * net / 100)
        gp_diff = act_gp - est_gp
        bg = C_LGREEN if diff >= 0 else C_LRED
        orig_cost     = int(s.get("origTotalCost", 0) or 0)
        orig_margin   = float(s.get("origMarginPct", 0) or 0)
        orig_net_pct  = float(s.get("origNetMarginPct", 0) or 0)
        orig_net_prof = int(s.get("origNetProfit", 0) or 0)
        item_cost     = int(s.get("itemActualTotal", 0) or 0)
        extra_cost    = int(s.get("extraTotal", 0) or 0)
        total_cost    = int(s.get("totalActualCost", 0) or 0)
        gross_pct     = float(s.get("grossMarginPct", 0) or 0)
        net_pct       = float(s.get("netMarginPct", 0) or 0)
        net_prof      = int(s.get("netProfit", 0) or 0)
        _set_row(ws6, r_i,
                 [mc["quoteNo"], mc["customer"], mc["project"], mc["salesPerson"],
                  mc["dealTag"], mc["pretax"],
                  orig_cost, f"{orig_margin:.1f}%", f"{orig_net_pct:.1f}%", orig_net_prof,
                  item_cost, extra_cost, total_cost,
                  f"{gross_pct:.1f}%", f"{net_pct:.1f}%", net_prof,
                  f"{'+' if diff >= 0 else ''}{diff:.1f}", gp_diff,
                  mc["settleStatus"] or "", mc.get("settleDate",""), mc.get("settleBy","")],
                 font=mk(size=9), fill=fill(bg), border=BD,
                 aligns=[al("left"),al("left"),al("left"),al("left"),al("center"),
                         al("right"),al("right"),al("right"),al("right"),al("right"),
                         al("right"),al("right"),al("right"),al("right"),al("right"),al("right"),
                         al("right"),al("right"),
                         al("center"),al("center"),al("left")],
                 height=18)
        for col in [6,7,10,11,12,13,16,18]:
            ws6.cell(row=r_i, column=col).number_format = '#,##0'
        ws6.cell(row=r_i, column=18).number_format = '+#,##0;-#,##0;0'
        ws6.cell(row=r_i, column=17).font = mk(bold=True, size=9, color=C_GREEN if diff >= 0 else C_RED)
        ws6.cell(row=r_i, column=15).font = mk(bold=True, size=9, color=C_GREEN if net_pct >= net else C_RED)
        ws6.cell(row=r_i, column=18).font = mk(bold=True, size=9, color=C_GREEN if gp_diff >= 0 else C_RED)

    if data["marginCases"]:
        sr6 = len(data["marginCases"]) + 4
        tot_pretax    = sum(mc["pretax"] or 0 for mc in data["marginCases"])
        tot_orig_cost = sum(int((mc.get("settleSummary") or {}).get("origTotalCost",0) or 0) for mc in data["marginCases"])
        tot_orig_np   = sum(int((mc.get("settleSummary") or {}).get("origNetProfit",0) or 0) for mc in data["marginCases"])
        tot_item      = sum(int((mc.get("settleSummary") or {}).get("itemActualTotal",0) or 0) for mc in data["marginCases"])
        tot_extra     = sum(int((mc.get("settleSummary") or {}).get("extraTotal",0) or 0) for mc in data["marginCases"])
        tot_total     = sum(int((mc.get("settleSummary") or {}).get("totalActualCost",0) or 0) for mc in data["marginCases"])
        tot_net_prof  = sum(int((mc.get("settleSummary") or {}).get("netProfit",0) or 0) for mc in data["marginCases"])
        tot_est       = sum(int((mc["pretax"] or 0) * (mc["netMarginPct"] or 0) / 100) for mc in data["marginCases"])
        tot_act       = sum(mc["grossProfit"] or 0 for mc in data["marginCases"])
        _set_row(ws6, sr6,
                 ["合計","","","","", tot_pretax,
                  tot_orig_cost,"","", tot_orig_np,
                  tot_item, tot_extra, tot_total,"","", tot_net_prof,
                  "", tot_act - tot_est,
                  "","",""],
                 font=mk(bold=True, size=9, color=C_WHITE),
                 fill=fill("111827"), border=BD,
                 aligns=[al("center")] + [al("right")] * 20,
                 height=20)
        for col in [6,7,10,11,12,13,16,18]:
            ws6.cell(row=sr6, column=col).number_format = '#,##0'
        ws6.cell(row=sr6, column=18).number_format = '+#,##0;-#,##0;0'
    else:
        ws6.cell(row=4, column=1).value = "（目前尚無已完成精算之案件）"
        ws6.cell(row=4, column=1).font = mk(size=9, color=C_GRAY, italic=True)

    # ── Sheet 8: 保固到期預警 ────────────────────────────────────────────────
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

    # ── Sheet 8: 已結案未精算 ────────────────────────────────────────────────
    so_list = data.get("settleOverdue") or []
    ws8 = wb.create_sheet("已結案未精算")
    ws8.sheet_view.showGridLines = False

    hdrs8 = ["案件號","客戶","專案名稱","業務員","更新日期（結案參考）"]
    cols8 = [13, 18, 22, 12, 18]
    for i, (h, w) in enumerate(zip(hdrs8, cols8), 1):
        ws8.column_dimensions[get_column_letter(i)].width = w

    ws8.merge_cells(f"A1:{get_column_letter(len(hdrs8))}1")
    c = ws8["A1"]
    c.value = f"已結案未完成精算（共 {len(so_list)} 件）"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill(C_ORANGE)
    c.alignment = al("center")
    ws8.row_dimensions[1].height = 24

    _set_row(ws8, 2, hdrs8,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)

    for r_i, ov in enumerate(so_list, 3):
        _set_row(ws8, r_i,
                 [ov["quoteNo"], ov["customer"], ov["project"],
                  ov["salesPerson"], ov["closedAt"]],
                 font=mk(size=9), fill=fill(C_LYELLOW), border=BD,
                 aligns=[al("left"), al("left"), al("left"), al("left"), al("center")],
                 height=18)

    if not so_list:
        ws8.cell(row=3, column=1).value = "所有已結案件均已完成精算"
        ws8.cell(row=3, column=1).font  = mk(size=9, color=C_GREEN, italic=True)

    # ── Sheet 9: 帳齡分析 ────────────────────────────────────────────────────
    ar = data.get("arAging") or {}
    ar_bands = ar.get("bands") or []
    ar_total = ar.get("total") or {}

    ws9 = wb.create_sheet("帳齡分析")
    ws9.sheet_view.showGridLines = False

    hdrs9 = ["帳齡區間","案件號","客戶","專案名稱","業務員","進度","款項","應收金額","佔比","報價日","超期天數"]
    cols9 = [11, 13, 16, 20, 10, 9, 10, 14, 8, 11, 9]
    for i, (h, w) in enumerate(zip(hdrs9, cols9), 1):
        ws9.column_dimensions[get_column_letter(i)].width = w

    ws9.merge_cells(f"A1:{get_column_letter(len(hdrs9))}1")
    c = ws9["A1"]
    c.value = f"應收帳款帳齡分析（截至 {ar.get('asOf','')}，合計未收 NT$ {ar_total.get('amount',0):,}）"
    c.font  = mk(bold=True, size=12, color=C_WHITE)
    c.fill  = fill(C_RED)
    c.alignment = al("center")
    ws9.row_dimensions[1].height = 24

    _set_row(ws9, 2, hdrs9,
             font=mk(bold=True, size=9, color=C_WHITE),
             fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)

    ar_r = 3
    for band in ar_bands:
        bkey = band.get("key", "")
        bg_band = C_LRED if bkey == "90+" else C_LYELLOW if bkey == "61-90" else C_LBLUE if bkey == "31-60" else C_LGREEN
        for it in band.get("items") or []:
            days = it["daysElapsed"]
            _set_row(ws9, ar_r,
                     [band["label"], it["quoteNo"], it["customer"], it["project"],
                      it["salesPerson"], it["dealTag"], it["type"],
                      it["amount"], f"{it['pct']:.1f}%", it["quoteDate"], days],
                     font=mk(size=9), fill=fill(bg_band), border=BD,
                     aligns=[al("center"), al("left"), al("left"), al("left"),
                             al("left"), al("center"), al("center"),
                             al("right"), al("right"), al("center"), al("right")],
                     height=18)
            ws9.cell(row=ar_r, column=8).number_format = '#,##0'
            days_cell = ws9.cell(row=ar_r, column=11)
            days_cell.font = mk(bold=True, size=9,
                                color=C_RED if days > 90 else C_ORANGE if days > 60 else C_DARK)
            ar_r += 1

    if ar_r == 3:
        ws9.cell(row=3, column=1).value = "目前無未收款應收帳款"
        ws9.cell(row=3, column=1).font  = mk(size=9, color=C_GREEN, italic=True)
    else:
        _set_row(ws9, ar_r,
                 ["合計", "", "", "", "", "", "",
                  ar_total.get("amount", 0), "", "", ""],
                 font=mk(bold=True, size=9, color=C_WHITE),
                 fill=fill(C_DARK), border=BD,
                 aligns=[al("left")] + [al("right")] * 10, height=20)
        ws9.cell(row=ar_r, column=8).number_format = '#,##0'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ── PDF HTML builder ──────────────────────────────────────────────────────────

def _pdf_settle_overdue(so_list: list, tbl_hdr) -> str:
    if not so_list:
        return ""
    import html as _h
    rows = "".join(
        f"<tr><td>{_h.escape(ov['quoteNo'])}</td><td>{_h.escape(ov['customer'])}</td>"
        f"<td>{_h.escape(ov['project'])}</td><td>{_h.escape(ov['salesPerson'])}</td>"
        f"<td class='c'>{_h.escape(ov['closedAt'])}</td></tr>"
        for ov in so_list
    )
    return (
        "<div class='page-break'></div>"
        f"<div class='section-title' style='background:#D97706'>已結案未精算（共 {len(so_list)} 件，待補精算）</div>"
        f"<table><thead>{tbl_hdr('案件號','客戶','專案名稱','業務員','更新日期（結案參考）')}</thead><tbody>{rows}</tbody></table>"
    )


def _pdf_ar_aging(ar: dict, tbl_hdr, fmt) -> str:
    if not ar:
        return ""
    bands     = ar.get("bands") or []
    total_amt = (ar.get("total") or {}).get("amount", 0)
    as_of     = ar.get("asOf", "")
    import html as _h
    rows = ""
    for band in bands:
        for it in band.get("items") or []:
            d = it["daysElapsed"]
            color = "red" if d > 90 else "orange" if d > 60 else ""
            color_style = f' style="color:#DC2626;font-weight:700"' if d > 90 else f' style="color:#D97706"' if d > 60 else ''
            rows += (
                f"<tr><td class='c'>{_h.escape(band['label'])}</td>"
                f"<td>{_h.escape(it['quoteNo'])}</td><td>{_h.escape(it['customer'])}</td>"
                f"<td>{_h.escape(it['project'])}</td><td>{_h.escape(it['salesPerson'])}</td>"
                f"<td class='c'>{_h.escape(it['dealTag'])}</td><td>{_h.escape(it['type'])}</td>"
                f"<td class='r'>NT$ {it['amount']:,}</td>"
                f"<td class='r'>{it['pct']:.1f}%</td>"
                f"<td class='c'>{_h.escape(it['quoteDate'])}</td>"
                f"<td class='r'{color_style}><b>{d} 天</b></td></tr>"
            )
    if not rows:
        return ""
    return (
        "<div class='page-break'></div>"
        f"<div class='section-title' style='background:#DC2626'>應收帳款帳齡分析（截至 {as_of}，合計 NT$ {total_amt:,}）</div>"
        f"<table><thead>{tbl_hdr('帳齡區間','案件號','客戶','專案','業務員','進度','款項','應收金額','佔比','報價日','超期天數')}</thead>"
        f"<tbody>{rows}</tbody>"
        f"<tr class='sum-row'><td colspan='7'>合計</td><td class='r'>NT$ {total_amt:,}</td><td colspan='3'></td></tr>"
        "</table>"
    )


def _build_report_html(data: dict, period_label: str, gen_at: str) -> str:
    s = data["summary"]

    import html as _html_mod
    def esc(v): return _html_mod.escape(str(v or ''))

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
            f"<tr><td>{esc(it['quoteNo'])}</td><td>{esc(it['customer'])}</td>"
            f"<td>{esc(it['project'])}</td><td>{esc(it['salesPerson'])}</td>"
            f"<td class='c'>{esc(it['type'])}</td>"
            f"<td class='r'>NT$ {it['amount']:,}</td>"
            f"<td class='c'>{esc(it['receivedAt'])}</td>"
            f"<td class='r'>NT$ {aa_v:,}</td>"
            "<td class='r fee'>" + (f"NT$ {int(it['feeAmount']):,}" if it['feeAmount'] else "—") + "</td>"
            f"<td class='r net'>NT$ {int(it['netAmount'] if it['netAmount'] is not None else aa_v):,}</td>"
            f"<td>{esc(it['invoiceNo'] or '—')}</td></tr>"
        )

    # outstanding rows
    os_rows = ""
    for it in data["outstanding"]:
        os_rows += (
            f"<tr><td>{esc(it['quoteNo'])}</td><td>{esc(it['customer'])}</td>"
            f"<td>{esc(it['project'])}</td><td>{esc(it['salesPerson'])}</td>"
            f"<td class='c'>{esc(it['dealTag'])}</td><td class='c'>{esc(it['type'])}</td>"
            f"<td class='r red'>NT$ {it['amount']:,}</td>"
            f"<td class='c'>{it['pct']:.1f}%</td></tr>"
        )

    # case rows
    # 依月份區分（2026-08-26）：casesAll 本來就依 quote_date DESC 排序，先掃一輪
    # 算出每個年月的案件數/合約金額小計，第二輪逐筆組字串時遇到年月變化就插入
    # 一列跨欄的月份標題列，比照 Excel「案件清單」sheet 同一套邏輯。
    month_sums: dict = {}
    for c in data["casesAll"]:
        ym = (c["quoteDate"] or "")[:7]
        ms = month_sums.setdefault(ym, {"count": 0, "total": 0})
        ms["count"] += 1
        ms["total"] += c["total"] or 0

    case_rows = ""
    last_ym = None
    for c in data["casesAll"]:
        ym = (c["quoteDate"] or "")[:7]
        if ym != last_ym:
            ym_label = f"{ym[:4]}年{int(ym[5:7])}月" if ym else "（未填報價日）"
            ms = month_sums[ym]
            case_rows += (
                f"<tr class='month-hdr-row'><td colspan='6'>{esc(ym_label)}（{ms['count']} 件）</td>"
                f"<td class='r'>NT$ {ms['total']:,}</td><td colspan='3'></td></tr>"
            )
            last_ym = ym
        am = c["actualMarginPct"]
        diff = round((am or 0) - (c["netMarginPct"] or 0), 1) if am is not None else None
        in_p_cls = ' class="in-period"' if c["inPeriod"] else ""
        case_rows += (
            f"<tr{in_p_cls}><td>{esc(c['quoteNo'])}</td><td>{esc(c['customer'])}</td>"
            f"<td>{esc(c['project'])}</td><td>{esc(c['salesPerson'])}</td>"
            f"<td class='c'>{esc(c['quoteDate'])}</td><td class='c tag'>{esc(c['dealTag'])}</td>"
            f"<td class='r'>NT$ {c['total']:,}</td>"
            f"<td class='r'>{c['netMarginPct']:.1f}%</td>"
            "<td class='r " + ("green" if c["collectionRate"] >= 80 else "orange") + f"'>{c['collectionRate']:.1f}%</td>"
            "<td class='c'>" + ((("▲" if diff >= 0 else "▼") + str(abs(diff)) + "%") if diff is not None else "—") + "</td></tr>"
        )

    # ── 當月收支／今年度收支（2026-08-30 重構，取代原本單一「月支出」區塊）──
    # 使用者要求月支出要看得到「當月」逐筆支出項（含案件／品項金額），且跟
    # 「當月收入」各自獨立列出，並補上「今年度」收入/支出逐筆明細（原本只有
    # 支出有逐筆明細，收入完全沒有）。
    exp = data.get("expenses") or {"monthly": [], "totals": {}, "details": {}}
    exp_cat_label = {"contractor": "承攬商派發", "equipment": "設備進貨", "material": "料件進貨", "other": "其他支出"}
    exp_month_rows = ""
    for m in exp["monthly"]:
        exp_month_rows += (
            f"<tr><td>{esc(m['label'])}</td>"
            f"<td class='r'>NT$ {m['contractor']:,}</td><td class='r'>NT$ {m['equipment']:,}</td>"
            f"<td class='r'>NT$ {m['material']:,}</td><td class='r'>NT$ {m['other']:,}</td>"
            f"<td class='r'><b>NT$ {m['total']:,}</b></td></tr>"
        )

    def income_rows_html(items):
        out = ""
        for it in items:
            aa = it["actualAmount"]
            aa_v = aa if aa is not None else it["amount"]
            out += (
                f"<tr><td>{esc(it['quoteNo'])}</td><td>{esc(it['customer'])}</td>"
                f"<td>{esc(it['project'])}</td><td>{esc(it['salesPerson'])}</td>"
                f"<td class='c'>{esc(it['type'])}</td>"
                f"<td class='r'>NT$ {it['amount']:,}</td>"
                f"<td class='c'>{esc(it['receivedAt'])}</td>"
                f"<td class='r'>NT$ {aa_v:,}</td>"
                "<td class='r fee'>" + (f"NT$ {int(it['feeAmount']):,}" if it['feeAmount'] else "—") + "</td>"
                f"<td class='r net'>NT$ {int(it['netAmount'] if it['netAmount'] is not None else aa_v):,}</td>"
                f"<td>{esc(it['invoiceNo'] or '—')}</td></tr>"
            )
        return out

    def income_sum_row(items):
        return (
            f"<tr class='sum-row'><td colspan='5'>合計（{len(items)} 筆）</td>"
            f"<td class='r'>NT$ {sum(i['amount'] for i in items):,}</td><td></td>"
            f"<td class='r'>NT$ {sum((i['actualAmount'] if i['actualAmount'] is not None else i['amount']) for i in items):,}</td>"
            f"<td class='r'>NT$ {sum(i['feeAmount'] or 0 for i in items):,}</td>"
            f"<td class='r'>NT$ {sum(i['netAmount'] or 0 for i in items):,}</td><td></td></tr>"
        )

    def expense_rows_html(items):
        return "".join(
            f"<tr><td class='c'>{esc(it.get('date',''))}</td><td>{esc(exp_cat_label.get(it.get('cat'), it.get('cat','')))}</td>"
            f"<td>{esc(it.get('quoteNo','') or '—')}</td><td>{esc(it.get('desc',''))}</td>"
            f"<td class='r'>NT$ {it.get('amount',0):,}</td>"
            f"<td>{esc('、'.join(f.get('filename','') for f in (it.get('files') or []))) or '—'}</td></tr>"
            for it in items
        )

    month_income_items  = data.get("monthIncomeItems") or []
    month_expense_items = data.get("monthExpenseItems") or []
    year_income_items   = data.get("yearIncomeItems") or []
    year_expense_items  = []
    for cat, rows in (exp.get("details") or {}).items():
        for it in rows:
            year_expense_items.append({**it, "cat": cat})
    year_expense_items.sort(key=lambda x: x.get("date") or "", reverse=True)

    # ── 本季收支段落（2026-09-10）──────────────────────────────────────────
    # 只有匯出時帶了 quarter 參數才產生，沒帶就是空字串（既有不帶 quarter 的
    # 匯出結果完全不變）。組在 f-string 之外，因為裡面要條件分支。
    quarter_section_html = ""
    _q = data.get("expenseQuarter")
    if _q:
        q_income  = data.get("quarterIncomeItems") or []
        q_expense = data.get("quarterExpenseItems") or []
        q_in_tot  = data.get("quarterIncomeTotal", 0)
        q_ex_tot  = data.get("quarterExpenseTotal", 0)
        q_title   = f'{data.get("expensesYear", "")} 年第 {_q} 季收支明細'
        q_income_html = (
            "<table><thead>"
            + tbl_hdr("案件號", "客戶", "專案", "業務員", "款項", "應收金額", "收款日",
                      "實收金額", "手續費", "實收淨額", "發票號碼")
            + "</thead><tbody>" + income_rows_html(q_income) + income_sum_row(q_income)
            + "</tbody></table>"
        ) if q_income else (
            '<p style="color:#6B7280;font-size:9pt;padding:8px 0;font-style:italic">本季尚無收款紀錄。</p>'
        )
        q_expense_html = (
            "<table><thead>"
            + tbl_hdr("日期", "類別", "關聯案件", "說明", "金額", "發票/收據附件")
            + "</thead><tbody>" + expense_rows_html(q_expense) + "</tbody></table>"
        ) if q_expense else (
            '<p style="color:#6B7280;font-size:9pt;padding:8px 0;font-style:italic">本季尚無支出明細資料。</p>'
        )
        quarter_section_html = f"""
<!-- 本季收支（2026-09-10） -->
<div class="page-break"></div>
<div class="section-title" style="background:#111827">{q_title}</div>
<h3 style="margin:8px 0 8px;font-size:10pt;color:#15803D;border-bottom:1px solid #BBF7D0;padding-bottom:4px">本季收入明細（共 {len(q_income)} 筆）</h3>
{q_income_html}
<h3 style="margin:16px 0 8px;font-size:10pt;color:#7C3AED;border-bottom:1px solid #DDD6FE;padding-bottom:4px">本季支出明細（共 {len(q_expense)} 筆）</h3>
{q_expense_html}
<table style="margin-top:10px"><tbody>
<tr class="sum-row">
  <td>本季收入合計</td><td class="r">NT$ {q_in_tot:,}</td>
  <td>本季支出合計</td><td class="r">NT$ {q_ex_tot:,}</td>
  <td>本季淨額</td><td class="r"><b>NT$ {q_in_tot - q_ex_tot:,}</b></td>
</tr>
</tbody></table>
"""

    # sales rows
    sp_rows = ""
    for sp in data["salesPerf"]:
        am  = sp["avgActualMarginPct"]
        est = sp["avgMarginPct"]
        am_cls = "green" if (am is not None and am >= est) else ("red" if am is not None else "")
        am_str = f"{am:.1f}%" if am is not None else "—"
        sp_rows += (
            f"<tr><td>{esc(sp['salesPerson'])}</td><td class='r'>{sp['caseCount']}</td>"
            f"<td class='r'>NT$ {sp['totalAmount']:,}</td>"
            f"<td class='r'>NT$ {sp['receivedAmount']:,}</td>"
            f"<td class='r'>{sp['collectionRate']:.1f}%</td>"
            f"<td class='r'>{est:.1f}%</td>"
            f"<td class='r {am_cls}'><b>{am_str}</b></td>"
            f"<td class='r'>{sp['settledCount']}</td></tr>"
        )

    # margin analysis rows (summary table)
    mg_rows = ""
    # per-case profit breakdown blocks (利潤分析明細)
    mg_detail_blocks = ""
    for mc in data["marginCases"]:
        net    = mc["netMarginPct"] or 0
        act    = mc["actualMarginPct"] or 0
        diff   = round(act - net, 1)
        est_gp = int((mc["pretax"] or 0) * net / 100)
        act_gp = mc["grossProfit"] or 0
        gp_diff = act_gp - est_gp
        diff_cls = "green" if diff >= 0 else "red"
        act_cls  = "green" if act >= net else "red"
        diff_sign = "+" if diff >= 0 else ""
        gpd_sign  = "+" if gp_diff >= 0 else ""
        mg_rows += (
            f"<tr>"
            f"<td>{esc(mc['quoteNo'])}</td><td>{esc(mc['customer'])}</td>"
            f"<td>{esc(mc['project'])}</td><td>{esc(mc['salesPerson'])}</td>"
            f"<td class='c'>{esc(mc['dealTag'])}</td>"
            f"<td class='r'>{net:.1f}%</td>"
            f"<td class='r'>NT$ {est_gp:,}</td>"
            f"<td class='r {act_cls}'><b>{act:.1f}%</b></td>"
            f"<td class='r'>NT$ {act_gp:,}</td>"
            f"<td class='r {diff_cls}'><b>{diff_sign}{diff:.1f}pp</b></td>"
            f"<td class='r {diff_cls}'><b>{gpd_sign}NT$ {abs(gp_diff):,}</b></td>"
            f"<td class='c'>{esc(mc['settleStatus'] or '—')}</td>"
            f"</tr>"
        )
    if data["marginCases"]:
        tot_est = sum(int((mc["pretax"] or 0) * (mc["netMarginPct"] or 0) / 100) for mc in data["marginCases"])
        tot_act = sum(mc["grossProfit"] or 0 for mc in data["marginCases"])
        tot_diff = tot_act - tot_est
        td_cls = "green" if tot_diff >= 0 else "red"
        td_sign = "+" if tot_diff >= 0 else ""
        mg_rows += (
            f"<tr class='sum-row'>"
            f"<td colspan='6'>合計（{len(data['marginCases'])} 件）</td>"
            f"<td class='r'>NT$ {tot_est:,}</td><td></td>"
            f"<td class='r'>NT$ {tot_act:,}</td><td></td>"
            f"<td class='r'>{td_sign}NT$ {abs(tot_diff):,}</td><td></td>"
            f"</tr>"
        )

    # per-case profit detail blocks for PDF
    for mc in data["marginCases"]:
        # 命名為 ss（settleSummary）而非 s——函式開頭 s = data["summary"] 是整份
        # 報表最後 KPI 區塊要用的彙總資料，Python 沒有迴圈區塊作用域，這個迴圈
        # 跑完後若沿用 s 這個變數名，會把 s 永久覆蓋成最後一筆案件的精算摘要，
        # 導致後面的 KPI 區塊讀 s["totalReceivable"] 直接 KeyError（曾經修過一次
        # 見 2026-08-01c，但那次修的是月報寄信路徑；這裡是 PDF 匯出路徑同一個
        # bug 的另一個發生點，2026-08-25 隨「營運報表匯出PDF」故障回報一併修正）
        ss = mc.get("settleSummary") or {}
        net = mc["netMarginPct"] or 0
        act = mc["actualMarginPct"] or 0
        diff_ppts = round(act - net, 1)
        prof_diff = int(ss.get("profitDiff", 0) or 0)
        diff_clr  = "#15803D" if prof_diff >= 0 else "#DC2626"
        diff_sign = "+" if prof_diff >= 0 else ""
        settle_date = mc.get("settleDate","") or ""
        settle_by   = mc.get("settleBy","")   or ""
        def _fn(v): return f"NT$ {int(v or 0):,}"
        mg_detail_blocks += f"""
<div style="page-break-inside:avoid;margin-bottom:20px;border:1px solid #E5E7EB;border-radius:6px;overflow:hidden">
  <div style="background:#F3F4F6;padding:7px 12px;display:flex;justify-content:space-between;align-items:center">
    <span style="font-weight:700;font-size:10pt">{esc(mc['quoteNo'])}　{esc(mc['customer'])}　{esc(mc['project'])}</span>
    <span style="font-size:9pt;color:#6B7280">{esc(mc['salesPerson'])}{"　精算日："+esc(settle_date) if settle_date else ""}{"　完結人："+esc(settle_by) if settle_by else ""}</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0">
    <table style="width:100%;border-right:1px solid #E5E7EB">
      <thead><tr><th colspan="2" style="background:#F9FAFB;color:#374151;text-align:center;padding:5px;font-size:9pt">原始報價預估</th></tr></thead>
      <tbody>
        <tr><td>報價稅前收入</td><td class="r">{_fn(ss.get("quotedPretax"))}</td></tr>
        <tr><td>原始成本（料件）</td><td class="r">{_fn(ss.get("origTotalCost"))}</td></tr>
        <tr><td class="bold">原始直接毛利</td><td class="r bold">{_fn(ss.get("origDirectProfit"))}</td></tr>
        <tr><td>原始毛利率</td><td class="r">{float(ss.get("origMarginPct") or 0):.1f}%</td></tr>
        <tr class="sub"><td>管銷分攤（10%）</td><td class="r red">− {_fn(ss.get("origAdminCost"))}</td></tr>
        <tr class="sub"><td>公益捐款（1%）</td><td class="r red">− {_fn(ss.get("origCharity"))}</td></tr>
        <tr class="bold-row"><td>原始預估淨利</td><td class="r">{_fn(ss.get("origNetProfit"))}</td></tr>
        <tr><td>原始預估淨利率</td><td class="r">{float(ss.get("origNetMarginPct") or 0):.1f}%</td></tr>
      </tbody>
    </table>
    <table style="width:100%">
      <thead><tr><th colspan="2" style="background:#FFFBEB;color:#92400E;text-align:center;padding:5px;font-size:9pt">實際成本精算</th></tr></thead>
      <tbody>
        <tr><td>報價稅前收入</td><td class="r">{_fn(ss.get("quotedPretax"))}</td></tr>
        <tr><td>品項實際成本</td><td class="r orange">{_fn(ss.get("itemActualTotal"))}</td></tr>
        <tr><td>額外支出</td><td class="r orange">{_fn(ss.get("extraTotal"))}</td></tr>
        <tr class="bold-row"><td>實際總成本</td><td class="r orange bold">{_fn(ss.get("totalActualCost"))}</td></tr>
        <tr><td>真實毛利</td><td class="r {'green' if int(ss.get('grossProfit',0) or 0)>=0 else 'red'}">{_fn(ss.get("grossProfit"))}</td></tr>
        <tr><td>真實毛利率</td><td class="r">{float(ss.get("grossMarginPct") or 0):.1f}%</td></tr>
        <tr class="sub"><td>管銷分攤（10%）</td><td class="r red">− {_fn(ss.get("adminCost"))}</td></tr>
        <tr class="sub"><td>公益捐款（1%）</td><td class="r red">− {_fn(ss.get("charityDonation"))}</td></tr>
        <tr class="bold-row"><td>真實淨利</td><td class="r {'green' if int(ss.get('netProfit',0) or 0)>=0 else 'red'}">{_fn(ss.get("netProfit"))}</td></tr>
        <tr><td>真實淨利率</td><td class="r" style="color:{'#15803D' if float(ss.get('netMarginPct',0) or 0)>=20 else '#B45309' if float(ss.get('netMarginPct',0) or 0)>=0 else '#DC2626'};font-weight:700">{float(ss.get("netMarginPct") or 0):.1f}%</td></tr>
      </tbody>
    </table>
  </div>
  <div style="background:{'#F0FDF4' if prof_diff>=0 else '#FFF1F2'};border-top:1px solid {'#86EFAC' if prof_diff>=0 else '#FECACA'};padding:6px 12px;font-size:9pt;color:{diff_clr};font-weight:600">
    {'真實淨利比原始預估高' if prof_diff>=0 else '真實淨利比原始預估低'} NT$ {abs(prof_diff):,}（{'+' if diff_ppts>=0 else ''}{diff_ppts:.1f} ppts）
  </div>
</div>"""

    # warranty rows
    ww_rows = ""
    for w in data["warranty"]:
        dl = w["daysLeft"]
        cls = "red" if dl < 0 else "orange" if dl <= 30 else ""
        ww_rows += (
            f"<tr><td>{esc(w['quoteNo'])}</td><td>{esc(w['customer'])}</td>"
            f"<td>{esc(w['device'])}</td><td>{esc(w['sn'])}</td>"
            f"<td class='c'>{esc(w['expiry'])}</td>"
            f"<td class='r {cls}'>{dl} 天</td></tr>"
        )

    # ── Pre-compute achievement section for PDF ───────────────────────────────
    _acv  = data.get("achievement") or {}
    _tgts = data.get("targets")     or {}
    _acv_year = _acv.get("year") or int(gen_at[:4])

    def _pdf_acv_card(label, actual_s, target_s, rate, prorata_s=None):
        if rate is None:
            rc, st, bar = "#6B7280", "無目標", 0
        elif rate >= 95:
            rc, st, bar = "#15803D", f"{rate:.1f}% ✓", min(rate, 100)
        elif rate >= 80:
            rc, st, bar = "#D97706", f"{rate:.1f}% △", min(rate, 100)
        else:
            rc, st, bar = "#DC2626", f"{rate:.1f}% ✗", min(rate, 100)
        pro_html = f'<div style="font-size:7pt;color:#6B7280;margin-top:2px">按時 {prorata_s}</div>' if prorata_s else ''
        return (
            f'<div class="acv-card">'
            f'<div class="acv-lbl">{label}</div>'
            f'<div style="display:flex;align-items:baseline;gap:5px;margin-bottom:5px">'
            f'<span style="font-size:12pt;font-weight:700">{actual_s}</span>'
            f'<span style="color:#9CA3AF;font-size:8pt"> / {target_s}</span></div>'
            f'<div style="height:5px;background:#F0F0F0;border-radius:3px;margin-bottom:5px;overflow:hidden">'
            f'<div style="height:100%;width:{bar:.0f}%;background:{rc};border-radius:3px"></div></div>'
            f'<div style="font-weight:700;color:{rc};font-size:10pt">{st}</div>'
            f'{pro_html}</div>'
        )

    if _acv.get("hasTargets"):
        _ann     = _acv.get("annual", {})
        _rev_d   = _ann.get("revenue",       {})
        _cas_d   = _ann.get("newCases",      {})
        _colA_d  = _ann.get("collectionAmt", {})
        _colR_d  = _ann.get("collectionRate",{})
        _mgn_d   = _ann.get("avgMarginPct",  {})
        _gp_d    = _ann.get("grossProfit",   {})

        _acv_cards = (
            _pdf_acv_card("年度合約總額",  fmt(_rev_d.get("actual",0)),  fmt(_rev_d.get("target",0)),  _rev_d.get("rate"),  fmt(_rev_d.get("prorata",0)) if _rev_d.get("prorata") else None)
          + _pdf_acv_card("年度新成案數",  f"{_cas_d.get('actual',0)} 件",  f"{_cas_d.get('target',0)} 件",  _cas_d.get("rate"), f"{_cas_d.get('prorata',0)} 件" if _cas_d.get("prorata") else None)
          + _pdf_acv_card("年度收款金額",  fmt(_colA_d.get("actual",0)), fmt(_colA_d.get("target",0)), _colA_d.get("rate"), fmt(_colA_d.get("prorata",0)) if _colA_d.get("prorata") else None)
          + _pdf_acv_card("收款率目標",    f"{_colR_d.get('actual',0):.1f}%", f"{_colR_d.get('target',0):.0f}%", _colR_d.get("rate"))
          + _pdf_acv_card("平均淨毛利率",  f"{_mgn_d.get('actual',0):.1f}%",  f"{_mgn_d.get('target',0):.0f}%",  _mgn_d.get("rate"))
          + _pdf_acv_card("年度實際毛利",  fmt(_gp_d.get("actual",0)),   fmt(_gp_d.get("target",0)),   _gp_d.get("rate"),   fmt(_gp_d.get("prorata",0)) if _gp_d.get("prorata") else None)
        )

        _sp_rows_html = ""
        for _sp in (_acv.get("salesperson") or []):
            _rv  = _sp.get("revenueRate")
            _rv_c = "#15803D" if (_rv is not None and _rv >= 95) else "#D97706" if (_rv is not None and _rv >= 80) else "#DC2626" if _rv is not None else "#6B7280"
            _rv_s = f"{_rv:.1f}%" if _rv is not None else "—"
            _sp_rows_html += (
                f"<tr><td>{esc(_sp['name'])}</td>"
                f"<td class='r'>NT$ {_sp['targetRevenue']:,}</td>"
                f"<td class='r'>NT$ {_sp['ytdRevenue']:,}</td>"
                f"<td class='r' style='font-weight:700;color:{_rv_c}'>{_rv_s}</td>"
                f"<td class='r'>{int(_sp['targetCases'] or 0)} 件</td>"
                f"<td class='r'>{_sp['ytdCases']} 件</td></tr>"
            )
        _sp_section = (
            f"<div class='section-title' style='background:#2563EB'>業務員目標達成率</div>"
            f"<table><thead><tr><th>業務員</th><th class='r'>配額目標</th><th class='r'>YTD 合約</th>"
            f"<th class='r'>達成率</th><th class='r'>案件配額</th><th class='r'>YTD 案件</th></tr></thead>"
            f"<tbody>{_sp_rows_html}</tbody></table>"
        ) if _sp_rows_html else ""

        acv_html = (
            f"<div class='page-break'></div>"
            f"<div class='section-title' style='background:#7C3AED'>{_acv_year} 年度目標達成率 — {_acv.get('prorataLabel','')}</div>"
            f"<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0'>{_acv_cards}</div>"
            f"{_sp_section}"
        )
    else:
        acv_html = (
            f"<div class='section-title' style='background:#7C3AED'>{_acv_year} 年度目標達成率</div>"
            f"<p style='color:#6B7280;font-size:9pt;padding:8px 0;font-style:italic'>尚未設定 {_acv_year} 年度目標，請於系統設定中配置。</p>"
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
.acv-card{{border:1px solid #E5E7EB;border-radius:6px;padding:10px 12px;background:#FAFAFA}}
.acv-lbl{{font-size:7.5pt;color:#6B7280;margin-bottom:4px}}
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
.month-hdr-row{{background:#F3F4F6!important;font-weight:700;color:#374151}}
.month-hdr-row td{{border:none}}
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
  <div class="kpi"><div class="kpi-label">在製訂單 (Backlog)</div><div class="kpi-val blue">{fmt(s["backlog"])}</div><div class="kpi-sub">進行中案件未收款合計</div></div>
  {'<div class="kpi"><div class="kpi-label">已結案未精算</div><div class="kpi-val red">' + str(s["settleOverdueCount"]) + ' 件</div><div class="kpi-sub">待補精算</div></div>' if s["settleOverdueCount"] > 0 else ""}
</div>

{acv_html}

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

<!-- 當月收支（2026-08-30） -->
<div class="page-break"></div>
<div class="section-title" style="background:#111827">{data.get("expenseMonth","")} 當月收支明細</div>
<h3 style="margin:8px 0 8px;font-size:10pt;color:#15803D;border-bottom:1px solid #BBF7D0;padding-bottom:4px">當月收入明細</h3>
{'<table><thead>' + tbl_hdr("案件號","客戶","專案","業務員","款項","應收金額","收款日","實收金額","手續費","實收淨額","發票號碼") + '</thead><tbody>' + income_rows_html(month_income_items) + income_sum_row(month_income_items) + '</tbody></table>' if month_income_items else '<p style="color:#6B7280;font-size:9pt;padding:8px 0;font-style:italic">當月尚無收款紀錄。</p>'}
<h3 style="margin:16px 0 8px;font-size:10pt;color:#7C3AED;border-bottom:1px solid #DDD6FE;padding-bottom:4px">當月支出明細</h3>
{'<table><thead>' + tbl_hdr("日期","類別","關聯案件","說明","金額","發票/收據附件") + '</thead><tbody>' + expense_rows_html(month_expense_items) + '</tbody></table>' if month_expense_items else '<p style="color:#6B7280;font-size:9pt;padding:8px 0;font-style:italic">當月尚無支出明細資料。</p>'}
<table style="margin-top:10px"><tbody>
<tr class="sum-row">
  <td>當月收入合計</td><td class="r">NT$ {data.get("monthIncomeTotal",0):,}</td>
  <td>當月支出合計</td><td class="r">NT$ {data.get("monthExpenseTotal",0):,}</td>
  <td>當月淨額</td><td class="r"><b>NT$ {data.get("monthIncomeTotal",0) - data.get("monthExpenseTotal",0):,}</b></td>
</tr>
</tbody></table>
{quarter_section_html}
<!-- 今年度收支（2026-08-30） -->
<div class="page-break"></div>
<div class="section-title" style="background:#111827">{data.get("expensesYear","")}年度收支總表</div>
<h3 style="margin:8px 0 8px;font-size:10pt;color:#7C3AED;border-bottom:1px solid #DDD6FE;padding-bottom:4px">年度月支出結構（逐月比較）</h3>
<table>
<thead>{tbl_hdr("月份","承攬商派發","設備進貨","料件進貨","其他支出","合計")}</thead>
<tbody>{exp_month_rows}</tbody>
<tr class="sum-row">
  <td>全年合計</td>
  <td class="r">NT$ {exp["totals"].get("contractor",0):,}</td>
  <td class="r">NT$ {exp["totals"].get("equipment",0):,}</td>
  <td class="r">NT$ {exp["totals"].get("material",0):,}</td>
  <td class="r">NT$ {exp["totals"].get("other",0):,}</td>
  <td class="r">NT$ {exp["totals"].get("total",0):,}</td>
</tr>
</table>
<h3 style="margin:16px 0 8px;font-size:10pt;color:#15803D;border-bottom:1px solid #BBF7D0;padding-bottom:4px">今年度收入明細（共 {len(year_income_items)} 筆）</h3>
{'<table><thead>' + tbl_hdr("案件號","客戶","專案","業務員","款項","應收金額","收款日","實收金額","手續費","實收淨額","發票號碼") + '</thead><tbody>' + income_rows_html(year_income_items) + income_sum_row(year_income_items) + '</tbody></table>' if year_income_items else '<p style="color:#6B7280;font-size:9pt;padding:8px 0;font-style:italic">此年度尚無收款紀錄。</p>'}
<h3 style="margin:16px 0 8px;font-size:10pt;color:#7C3AED;border-bottom:1px solid #DDD6FE;padding-bottom:4px">今年度支出明細（共 {len(year_expense_items)} 筆）</h3>
{'<table><thead>' + tbl_hdr("日期","類別","關聯案件","說明","金額","發票/收據附件") + '</thead><tbody>' + expense_rows_html(year_expense_items) + '</tbody></table>' if year_expense_items else '<p style="color:#6B7280;font-size:9pt;padding:8px 0;font-style:italic">此年度尚無支出明細資料。</p>'}
<table style="margin-top:10px"><tbody>
<tr class="sum-row">
  <td>今年度收入合計</td><td class="r">NT$ {data.get("yearIncomeTotal",0):,}</td>
  <td>今年度支出合計</td><td class="r">NT$ {exp["totals"].get("total",0):,}</td>
  <td>今年度淨額</td><td class="r"><b>NT$ {data.get("yearIncomeTotal",0) - exp["totals"].get("total",0):,}</b></td>
</tr>
</tbody></table>

<!-- 案件清單 -->
<div class="page-break"></div>
<div class="section-title" style="background:#1F2937">案件清單（本期新成案以藍色標示，依月份區分）</div>
<table>
<thead>{tbl_hdr("案件號","客戶","專案","業務員","報價日","進度","合約金額","預估毛利率","收款率","實際毛利率(▲▼)")}</thead>
<tbody>{case_rows}</tbody>
</table>

<!-- 業務員績效 -->
<div class="section-title" style="background:#2563EB">業務員績效</div>
<table>
<thead>{tbl_hdr("業務員","案件數","合約總額","已收款","收款率","預估毛利率(加權)","實際毛利率(精算)","精算件數")}</thead>
<tbody>{sp_rows}</tbody>
</table>

<!-- 毛利分析 -->
<div class="page-break"></div>
<div class="section-title" style="background:#7C3AED">毛利分析（已精算案件，共 {len(data["marginCases"])} 件）</div>
{'<table><thead>' + tbl_hdr("案件號","客戶","專案","業務員","進度","預估毛利率","預估毛利","實際毛利率","實際毛利","差異(pp)","差異金額","精算狀態") + '</thead><tbody>' + mg_rows + '</tbody></table><h3 style="margin:20px 0 10px;font-size:10pt;color:#6D28D9;border-bottom:1px solid #DDD6FE;padding-bottom:4px">各案件利潤分析明細</h3>' + mg_detail_blocks if data["marginCases"] else '<p style="color:#6B7280;font-size:9pt;padding:8px 0;font-style:italic">目前尚無已完成精算之案件。</p>'}

<!-- 保固預警 -->
<div class="page-break"></div>
<div class="section-title" style="background:#D97706">保固到期預警（90 天內）</div>
<table>
<thead>{tbl_hdr("案件號","客戶","設備名稱","序號 SN","到期日","剩餘天數")}</thead>
<tbody>{ww_rows or '<tr><td colspan="6" class="c" style="color:#6B7280;padding:10px">目前 90 天內無保固到期設備</td></tr>'}</tbody>
</table>

<!-- 已結案未精算 -->
{_pdf_settle_overdue(data.get("settleOverdue") or [], tbl_hdr)}

<!-- 帳齡分析 -->
{_pdf_ar_aging(data.get("arAging") or {}, tbl_hdr, fmt)}

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
        run_edge_pdf(
            [edge, "--headless", "--disable-gpu", "--no-sandbox",
             f"--print-to-pdf={tmp_pdf}", "--no-pdf-header-footer",
             "--run-all-compositor-stages-before-draw",
             "file:///" + tmp_html.replace("\\", "/")]
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

def _augment_with_targets(data: dict, d0: str) -> dict:
    year    = int(d0[:4])
    targets = _get_setting("operating_targets") or {}
    data["targets"]     = targets
    data["achievement"] = _compute_achievement(year, targets, data["casesAll"])
    return data


@router.get("/api/reports/financial")
def report_json(
    period: Optional[str] = Query(None),
    department_id: Optional[int] = Query(None),
    authorization: str = Header(None),
):
    u = _require_user(authorization)
    _require_reports_access(u)
    label, d0, d1 = _parse_period(period)
    data = _augment_with_targets(_collect(d0, d1, department_id), d0)
    return {"period": period, "periodLabel": label, "dateStart": d0, "dateEnd": d1, **data}


@router.get("/api/reports/financial/excel")
def report_excel(
    period: Optional[str] = Query(None),
    department_id: Optional[int] = Query(None),
    expense_month: Optional[str] = Query(None),
    quarter: Optional[int] = Query(None),
    authorization: str = Header(None),
):
    u = _require_user(authorization)
    _require_reports_access(u)
    _check_export_rate(u["id"], "excel")
    label, d0, d1 = _parse_period(period)
    data   = _augment_with_targets(_collect(d0, d1, department_id), d0)
    data["arAging"] = _compute_ar_aging()
    # quarter 有帶才會多出「本季收支」工作表／段落（2026-09-10）；不帶時輸出與
    # 先前完全一致。畫面上期別切在「季報」時前端才會送這個參數。
    data.update(_build_income_expense_scopes(
        int(d0[:4]), expense_month or date.today().strftime("%Y-%m"), department_id, quarter
    ))
    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    xlsx   = _build_excel(data, label, gen_at)
    safe   = label.replace(" ", "").replace("年", "Y").replace("月", "M").replace("第", "Q").replace("季", "")
    fname  = f"MOTRIX_營運報表_{safe}.xlsx"
    _audit(_tok(authorization), "reports.export", "reports", "financial",
           f"營運報表 Excel 匯出（{label}）",
           {"format": "excel", "period": period, "departmentId": department_id})
    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_url_quote(fname)}"},
    )


@router.get("/api/reports/financial/pdf")
def report_pdf(
    period: Optional[str] = Query(None),
    department_id: Optional[int] = Query(None),
    expense_month: Optional[str] = Query(None),
    quarter: Optional[int] = Query(None),
    authorization: str = Header(None),
):
    u = _require_user(authorization)
    _require_reports_access(u)
    _check_export_rate(u["id"], "pdf")
    label, d0, d1 = _parse_period(period)
    data   = _augment_with_targets(_collect(d0, d1, department_id), d0)
    data["arAging"] = _compute_ar_aging()
    # quarter 有帶才會多出「本季收支」工作表／段落（2026-09-10）；不帶時輸出與
    # 先前完全一致。畫面上期別切在「季報」時前端才會送這個參數。
    data.update(_build_income_expense_scopes(
        int(d0[:4]), expense_month or date.today().strftime("%Y-%m"), department_id, quarter
    ))
    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        pdf_bytes = _html_to_pdf(_build_report_html(data, label, gen_at))
    except ValueError as e:
        raise HTTPException(500, str(e))
    safe  = label.replace(" ", "").replace("年", "Y").replace("月", "M").replace("第", "Q").replace("季", "")
    fname = f"MOTRIX_營運報表_{safe}.pdf"
    _audit(_tok(authorization), "reports.export", "reports", "financial",
           f"營運報表 PDF 匯出（{label}）",
           {"format": "pdf", "period": period, "departmentId": department_id})
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_url_quote(fname)}"},
    )


# ── AR Aging（應收帳款帳齡分析）────────────────────────────────────────────────

def _compute_ar_aging() -> dict:
    """帳齡計算 — 供 API endpoint 及 Excel/PDF 匯出共用。"""
    today = date.today()
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person,
               total, pretax, quote_date,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
               json_extract(data_json,'$.caseRecord') AS cr_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
        ORDER BY quote_date ASC
    """).fetchall()
    conn.close()

    bands: dict = {"0-30": [], "31-60": [], "61-90": [], "90+": []}

    for row in rows:
        cr = {}
        if row["cr_json"]:
            try:
                cr = json.loads(row["cr_json"])
            except Exception:
                pass

        total = row["total"] or 0
        pay   = (cr.get("payment") or {}).get("items", [])
        if not pay:
            continue

        try:
            anchor = date.fromisoformat((row["quote_date"] or "")[:10])
        except Exception:
            anchor = today

        amounts = payment_item_amounts(total, pay, row["pretax"])

        for idx, pi in enumerate(pay):
            if pi.get("received"):
                continue
            amt  = amounts[idx]
            days = (today - anchor).days

            band = "90+" if days > 90 else "61-90" if days > 60 else "31-60" if days > 30 else "0-30"
            bands[band].append({
                "quoteNo":     row["quote_no"],
                "customer":    row["customer_name"] or "",
                "project":     row["project_name"]  or "",
                "salesPerson": row["sales_person"]  or "",
                "dealTag":     row["deal_tag"]       or "",
                "type":        pi.get("type", f"第{idx+1}期"),
                "pct":         pi.get("pct") or 0,
                "amount":      amt,
                "quoteDate":   row["quote_date"] or "",
                "daysElapsed": days,
            })

    result_bands = []
    for key, label in [("0-30", "0–30 天"), ("31-60", "31–60 天"), ("61-90", "61–90 天"), ("90+", "90+ 天")]:
        items = bands[key]
        result_bands.append({
            "label":  label,
            "key":    key,
            "count":  len(items),
            "amount": sum(i["amount"] for i in items),
            "items":  items,
        })

    return {
        "asOf":  today.isoformat(),
        "note":  "帳齡以案件報價日為基準計算，不含已收款項目",
        "bands": result_bands,
        "total": {
            "count":  sum(b["count"]  for b in result_bands),
            "amount": sum(b["amount"] for b in result_bands),
        },
    }


@router.get("/api/reports/ar-aging")
def get_ar_aging(authorization: str = Header(None)):
    """
    應收帳款帳齡分析：以案件成案日為基準，將未收款項目分為 0-30/31-60/61-90/90+ 天四個區間。
    注意：無顯式到期日時以報價日計算帳齡，為管理用途的近似值。
    """
    u = _require_user(authorization)
    _require_reports_access(u)
    return _compute_ar_aging()


def _compute_cash_position() -> dict:
    """資金水位總覽 — 應收帳齡（既有 _compute_ar_aging）+ 應付（承攬商已核准未匯款）。

    刻意排除兩類、避免誤導：
    ①料件/設備進貨（stock_items.cost）——系統目前沒有對供應商的付款狀態追蹤，
      只有進貨當下的成本快照，無法判斷「已付/未付」，硬納入會虛報應付金額。
    ②payment_requests（請款單）——這是對客戶要款用的 AR 文件（見
      routers/payment_requests.py 檔頭），核准即為最終文件本身，不是一筆新
      產生的應付支出；金額仍算在對應報價單的應收帳齡裡，這裡不重複計入應付，
      否則會把同一筆錢同時算進應收又算進應付。"""
    ar = _compute_ar_aging()
    conn = get_db()
    rows = conn.execute("""
        SELECT v.voucher_no, v.quote_no, v.snapshot_json, v.updated_at, q.customer_name
        FROM contractor_payment_vouchers v
        LEFT JOIN quotations q ON q.quote_no = v.quote_no
        WHERE v.status='已核准' AND v.is_paid=0
        ORDER BY v.updated_at ASC
    """).fetchall()
    conn.close()

    ap_items = []
    for r in rows:
        snap = {}
        try:
            snap = json.loads(r["snapshot_json"] or "{}")
        except Exception:
            pass
        amt = float(snap.get("grandTotal") or 0)
        ap_items.append({
            "voucherNo":  r["voucher_no"],
            "quoteNo":    r["quote_no"] or "",
            "customer":   r["customer_name"] or "",
            "vendorName": snap.get("vendorName") or "",
            "amount":     amt,
            "approvedAt": r["updated_at"] or "",
        })
    ap_total = sum(i["amount"] for i in ap_items)
    ar_total = ar["total"]["amount"]

    return {
        "asOf": date.today().isoformat(),
        "ar": {"bands": ar["bands"], "total": ar_total, "count": ar["total"]["count"]},
        "ap": {"items": ap_items, "total": ap_total, "count": len(ap_items)},
        "net": ar_total - ap_total,
        "note": "應付僅含承攬商匯款申請（已核准未匯款）；料件/設備進貨無付款狀態追蹤、"
                "請款單為對客戶要款文件，兩者均不計入應付，避免虛報或重複計算。",
    }


@router.get("/api/reports/cash-position")
def get_cash_position(authorization: str = Header(None)):
    """
    資金水位總覽：應收帳款帳齡（沿用 ar-aging）+ 應付帳款（承攬商已核准未匯款），
    供管理階層快速掌握目前手上「還欠多少、還要付多少」，取代逐一開報表核對。
    不是逐月現金流預測——系統目前沒有結構化的預計收款/付款日期欄位，見 _compute_cash_position() docstring。
    """
    u = _require_user(authorization)
    _require_reports_access(u)
    return _compute_cash_position()


# ── 稅務匯出（銷項發票清單）──────────────────────────────────────────────────

def _round_half_up(n) -> int:
    """財政部統一發票金額計算慣例是「四捨五入」（.5 一律進位），Python 內建
    `round()` 是「銀行家捨入」（.5 進位到最近偶數）——兩者只在剛好卡在 .5
    邊界時才會差 1 元，但既然這裡的數字要拿去對真實開立的發票金額，就該用
    跟開票軟體一致的規則，不要假設「大部分時候一樣」就夠了。"""
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _collect_tax_invoices(year: Optional[int] = None, month: Optional[int] = None) -> list:
    """收集所有已填發票號碼的收款品項（案件管理財務Tab item.invoiceNo，自由文字，
    使用者開立發票後手動填入）＝銷項發票清單，供記帳士/稅務申報使用。

    未填 invoiceNo 的收款品項（尚未開發票）不列入。金額欄位：item 的 amount 為
    報價單「含稅總價」的一部分（見 payment_item_amounts() docstring），這裡換算
    5% 稅額拆出未稅/稅額/含稅三欄；若日後改用非 5% 稅率，此處需一併調整。

    2026-09-02 修復（反派/國稅局視角複查發現）：taxExempt（已核准稅額沖銷）
    品項過去在這裡被列成「稅額=0、未稅=含稅」，等於把一筆已經開立發票、已經
    對國稅局產生銷項稅額的交易，在申報用文件上回溯性地變成免稅交易——但
    這個迴圈本身已經先過濾掉沒填 invoiceNo 的品項，能走到這裡的一定是「已經
    開立過統一發票」的款項，taxExempt 只是之後才核准的內部應收帳款減讓（公司
    決定不跟客戶收那筆稅額），不會、也不能追溯改變已經開立當下就確定的法定
    稅捐義務。改用 apply_tax_exempt=False 取得「原始開立金額」（不套用沖銷
    折算）永遠照標準 5% 拆稅公式計算，taxExempt 對「客戶還欠多少」（AR帳齡/
    收款率/dashboard）的影響維持不變，只是不再讓它同時改寫稅務匯出的數字。

    2026-09-02 追加：year/month 期別篩選改用 invoiceDate（發票開立日期，
    2026-09-02 新增欄位，選填）而不是 receivedAt（款項收款日）——依加值型及
    非加值型營業稅法，發票該歸入哪個申報期別是看開立日，不是看客戶什麼時候
    把錢匯進來，兩者常常不同月甚至跨期別。缺漏 invoiceDate 的舊資料退回
    receivedAt（維持既有行為，不會讓歷史資料憑空消失）。回傳的 "date" 欄位
    刻意維持 receivedAt 不變——accounting_export.py 的 T100 現金基礎傳票要的
    就是「現金真的進帳」那天，跟這裡的期別篩選是兩個不同問題，不能共用同一
    個日期：新增獨立的 "invoiceDate" 欄位供期別篩選跟稅務匯出 Excel 顯示用。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, total, pretax,
               json_extract(data_json,'$.customerTaxId') AS tax_id,
               json_extract(data_json,'$.caseRecord.payment.items') AS pay_json
        FROM quotations
        WHERE json_extract(data_json,'$.caseRecord.payment.items') IS NOT NULL
    """).fetchall()
    conn.close()

    out = []
    for row in rows:
        try:
            items = json.loads(row["pay_json"] or "[]")
        except Exception:
            items = []
        if not items:
            continue
        amounts = payment_item_amounts(row["total"] or 0, items, row["pretax"], apply_tax_exempt=False)
        for idx, pi in enumerate(items):
            inv_no = (pi.get("invoiceNo") or "").strip()
            if not inv_no:
                continue
            received_at  = pi.get("receivedAt") or ""
            invoice_date = pi.get("invoiceDate") or received_at
            if year and invoice_date[:4] != str(year):
                continue
            if month and invoice_date[5:7] != f"{month:02d}":
                continue
            amt_incl   = amounts[idx]
            tax_amt    = _round_half_up(amt_incl - amt_incl / 1.05)
            amt_pretax = amt_incl - tax_amt
            out.append({
                "invoiceNo":     inv_no,
                "date":          received_at,
                "invoiceDate":   invoice_date,
                "quoteNo":       row["quote_no"],
                "customer":      row["customer_name"] or "",
                "taxId":         row["tax_id"] or "",
                "amountPretax":  amt_pretax,
                "taxAmount":     tax_amt,
                "amountTotal":   amt_incl,
                # 收款進帳的 MOTRIX 銀行帳戶（2026-09-01 新增，供 accounting_export.py
                # 依銀行帳戶分開設定 T100 科目代號用；既有呼叫端如 tax-export 不讀這兩個
                # 新 key，多帶不影響既有行為）
                "bankAccountName": pi.get("bankAccountName") or "",
                "bankAccountCode": pi.get("bankAccountCode") or "",
            })
    out.sort(key=lambda r: (r["invoiceDate"], r["quoteNo"]))
    return out


def _build_tax_export_excel(rows: list, period_label: str, gen_at: str) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "銷項發票清單"
    ws.sheet_view.showGridLines = False
    mk, fill, mk_border, al = _xl_style(wb)
    BD = mk_border()

    widths = [16, 12, 12, 14, 22, 14, 14, 12, 14]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.merge_cells("A1:I1")
    c = ws["A1"]; c.value = f"{_COMPANY} — 銷項發票清單（{period_label}）"
    c.font = mk(bold=True, size=13, color="FFFFFF"); c.fill = fill("111827"); c.alignment = al("center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:I2")
    c = ws["A2"]; c.value = f"產製時間：{gen_at}　僅列出已填發票號碼之收款品項，未開立發票者不列入；" \
                             "期別依發票開立日期歸屬，缺漏開立日期者以收款日期代替"
    c.font = mk(size=9, color="6B7280"); c.alignment = al("center")
    ws.row_dimensions[2].height = 18

    headers = ["發票號碼", "發票開立日期", "收款日期", "案件號", "客戶名稱", "統一編號",
               "金額（未稅）", "稅額", "金額（含稅）"]
    _set_row(ws, 3, headers, font=mk(bold=True, color="FFFFFF"), fill=fill("2563EB"), border=BD, aligns=[al("center")])
    ws.row_dimensions[3].height = 22

    r = 4
    total_pretax = total_tax = total_incl = 0
    body_aligns = [al("center"), al("center"), al("center"), al("center"), al("left"),
                   al("center"), al("right"), al("right"), al("right")]
    for row in rows:
        _set_row(ws, r, [
            row["invoiceNo"], row["invoiceDate"], row["date"], row["quoteNo"], row["customer"], row["taxId"],
            row["amountPretax"], row["taxAmount"], row["amountTotal"],
        ], font=mk(), border=BD, aligns=body_aligns)
        total_pretax += row["amountPretax"]
        total_tax    += row["taxAmount"]
        total_incl   += row["amountTotal"]
        r += 1

    _set_row(ws, r, ["合計", "", "", "", "", "", total_pretax, total_tax, total_incl],
             font=mk(bold=True), fill=fill("F9FAFB"), border=BD, aligns=body_aligns)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/api/reports/tax-export")
def tax_export_excel(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    authorization: str = Header(None),
):
    """銷項發票清單匯出（Excel），供記帳士/營業稅申報使用。不篩選 year 時匯出全部。"""
    u = _require_user(authorization)
    _require_reports_access(u)
    _check_export_rate(u["id"], "excel")
    rows = _collect_tax_invoices(year, month)
    label = "全部區間"
    if year and month:
        label = f"{year}年{month:02d}月"
    elif year:
        label = f"{year}年"
    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    xlsx = _build_tax_export_excel(rows, label, gen_at)
    fname = f"MOTRIX_銷項發票清單_{label}.xlsx"
    _audit(_tok(authorization), "reports.export", "reports", "tax-export",
           f"銷項發票清單匯出（{label}，共 {len(rows)} 筆）",
           {"year": year, "month": month, "count": len(rows)})
    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_url_quote(fname)}"},
    )


# ── 銀行對帳單比對（承攬商匯款申請）───────────────────────────────────────────

_BANK_DATE_ALIASES   = ["交易日期", "日期", "過帳日", "轉帳日期", "交易日", "date", "Date"]
_BANK_AMOUNT_ALIASES = ["金額", "提出金額", "支出金額", "轉出金額", "付款金額", "提款金額",
                         "amount", "Amount", "Debit", "withdrawal"]
_BANK_DESC_ALIASES   = ["摘要", "備註", "說明", "對方戶名", "附言", "memo", "Description", "Memo"]


def _pick_csv_header(fieldnames: list, aliases: list) -> Optional[str]:
    """依常見銀行匯出欄位別名找出對應欄位——各家銀行 CSV 標頭不統一，這裡先精準比對，
    找不到再退而求其次找含該關鍵字的欄位，仍找不到就回傳 None（呼叫端自行決定要不要擋）。"""
    clean = [fn for fn in fieldnames if fn]
    for a in aliases:
        for fn in clean:
            if fn.strip() == a:
                return fn
    for a in aliases:
        for fn in clean:
            if a in fn:
                return fn
    return None


def _parse_bank_csv(raw: bytes) -> list:
    """解析銀行對帳單 CSV。不同銀行匯出的編碼／欄位命名差異很大，這裡採寬鬆偵測：
    依序嘗試常見編碼、依別名清單找日期/金額/摘要欄位，只有金額欄位是必要的。"""
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise HTTPException(400, "CSV 編碼無法辨識，請確認匯出檔案格式（支援 UTF-8 / Big5）")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    date_col = _pick_csv_header(fieldnames, _BANK_DATE_ALIASES)
    amt_col  = _pick_csv_header(fieldnames, _BANK_AMOUNT_ALIASES)
    desc_col = _pick_csv_header(fieldnames, _BANK_DESC_ALIASES)
    if not amt_col:
        raise HTTPException(400, f"CSV 找不到可辨識的金額欄位，偵測到的欄位為：{'、'.join(fieldnames) or '（無）'}")

    rows = []
    for r in reader:
        raw_amt = (r.get(amt_col) or "").replace(",", "").replace("NT$", "").strip()
        if not raw_amt:
            continue
        try:
            amt = abs(float(raw_amt))
        except ValueError:
            continue
        if amt <= 0:
            continue
        rows.append({
            "date":   (r.get(date_col) or "").strip() if date_col else "",
            "amount": amt,
            "desc":   (r.get(desc_col) or "").strip() if desc_col else "",
        })
    return rows


@router.post("/api/reports/bank-reconcile")
async def bank_reconcile(file: UploadFile = File(...), authorization: str = Header(None)):
    """銀行對帳單比對：上傳 CSV，依金額比對目前「已核准未匯款」的承攬商匯款申請。

    只做金額比對（同金額只配對一次，避免一筆申請被重複配對到多筆銀行紀錄），純供人工
    複核用途——回傳配對建議，不會自動標記已匯款，實際標記仍走既有 paid-toggle 端點，
    避免比對誤判（例如剛好同金額但其實是不同筆款項）被誤當正式入帳紀錄。"""
    u = _require_user(authorization)
    if u["role"] not in ("superadmin", "admin") and not user_has_module(u, "cashier"):
        raise HTTPException(403, "僅管理員或出納可查閱")

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(400, "檔案過大（上限 5MB）")
    bank_rows = _parse_bank_csv(raw)

    conn = get_db()
    voucher_rows = conn.execute("""
        SELECT v.voucher_no, v.quote_no, v.snapshot_json, v.updated_at, q.customer_name
        FROM contractor_payment_vouchers v
        LEFT JOIN quotations q ON q.quote_no = v.quote_no
        WHERE v.status='已核准' AND v.is_paid=0
    """).fetchall()
    conn.close()

    vouchers = []
    for r in voucher_rows:
        snap = {}
        try:
            snap = json.loads(r["snapshot_json"] or "{}")
        except Exception:
            pass
        vouchers.append({
            "voucherNo":  r["voucher_no"],
            "quoteNo":    r["quote_no"] or "",
            "customer":   r["customer_name"] or "",
            "vendorName": snap.get("vendorName") or "",
            "amount":     round(float(snap.get("grandTotal") or 0)),
        })

    matched_voucher_nos = set()
    bank_results = []
    for br in bank_rows:
        amt_r = round(br["amount"])
        candidate = next(
            (v for v in vouchers if round(v["amount"]) == amt_r and v["voucherNo"] not in matched_voucher_nos),
            None,
        )
        if candidate:
            matched_voucher_nos.add(candidate["voucherNo"])
        bank_results.append({**br, "match": candidate})

    unmatched_vouchers = [v for v in vouchers if v["voucherNo"] not in matched_voucher_nos]

    _audit(_tok(authorization), "reports.bank_reconcile", "reports", "bank-reconcile",
           f"銀行對帳單比對（上傳 {len(bank_rows)} 筆，配對成功 {len(matched_voucher_nos)} 筆）",
           {"bankRowCount": len(bank_rows), "matchedCount": len(matched_voucher_nos)})
    return {
        "bankRows":           bank_results,
        "matchedCount":       len(matched_voucher_nos),
        "unmatchedBankCount": sum(1 for r in bank_results if not r["match"]),
        "unmatchedVouchers":  unmatched_vouchers,
        "note": "僅依金額比對，且同金額只配對一次，屬建議配對供人工複核；請核對案件號/"
                "承攬商名稱後再手動標記已匯款，系統不會自動標記。",
    }


# ── Customer transaction history ───────────────────────────────────────────────

@router.get("/api/reports/customer-history")
def customer_history(authorization: str = Header(None)):
    """全時期客戶交易歷史彙整：每位客戶的報價/成案/收款聚合視圖。"""
    u = _require_user(authorization)
    _require_reports_access(u)

    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, status, total, pretax, quote_date,
               sales_person, net_margin_pct,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
               json_extract(data_json,'$.caseRecord')   AS cr_json,
               json_extract(data_json,'$.settlement')   AS settle_json
        FROM quotations
        WHERE status NOT IN ('草稿')
        ORDER BY quote_date DESC
    """).fetchall()
    conn.close()

    _WON = ("已成案", "已結案")

    by_cust: dict = {}
    for row in rows:
        cust = (row["customer_name"] or "").strip() or "（未填）"
        if cust not in by_cust:
            by_cust[cust] = {"txns": [], "sp_cnt": {}}

        total = row["total"] or 0
        cr = {}
        if row["cr_json"]:
            try:
                cr = json.loads(row["cr_json"])
            except Exception:
                pass
        pay = (cr.get("payment") or {}).get("items", [])
        collected = 0
        if pay:
            amounts = payment_item_amounts(total, pay, row["pretax"])
            for idx, p in enumerate(pay):
                amt = amounts[idx]
                if p.get("received"):
                    collected += amt

        settle_status = ""
        if row["settle_json"]:
            try:
                settle_status = json.loads(row["settle_json"]).get("status") or ""
            except Exception:
                pass

        deal_tag = row["deal_tag"] or ""
        sp = row["sales_person"] or ""

        by_cust[cust]["txns"].append({
            "quoteNo":      row["quote_no"],
            "status":       row["status"] or "",
            "dealTag":      deal_tag,
            "quoteDate":    (row["quote_date"] or "")[:10],
            "total":        total,
            "collectedAmount": collected,
            "salesPerson":  sp,
            "projectName":  row["project_name"] or "",
            "netMarginPct": row["net_margin_pct"],
            "settleStatus": settle_status,
        })
        if sp:
            by_cust[cust]["sp_cnt"][sp] = by_cust[cust]["sp_cnt"].get(sp, 0) + 1

    customers = []
    for cust, data in by_cust.items():
        txns  = data["txns"]
        won   = [t for t in txns if t["dealTag"] in _WON]
        lost  = [t for t in txns if t["dealTag"] == "未成案"]
        decided = len(won) + len(lost)
        won_amount  = sum(t["total"] for t in won)
        total_coll  = sum(t["collectedAmount"] for t in txns)
        last_act    = max((t["quoteDate"] for t in txns if t["quoteDate"]), default="")
        sc          = data["sp_cnt"]
        main_sp     = max(sc, key=sc.get) if sc else ""

        customers.append({
            "customer":        cust,
            "quoteCount":      len(txns),
            "wonCount":        len(won),
            "lostCount":       len(lost),
            "pendingCount":    len(txns) - len(won) - len(lost),
            "winRate":         round(len(won) / decided * 100, 1) if decided > 0 else None,
            "totalWonAmount":  won_amount,
            "collectedAmount": total_coll,
            "collectionRate":  round(total_coll / won_amount * 100, 1) if won_amount > 0 else 0,
            "lastActivity":    last_act,
            "salesPerson":     main_sp,
            "transactions":    txns,
        })

    customers.sort(key=lambda x: x["totalWonAmount"], reverse=True)
    return {"customers": customers, "total": len(customers)}


# ── Monthly report email scheduler ────────────────────────────────────────────

def _prev_month_str(ref: date = None) -> str:
    """Return 'YYYY-MM' for the month before ref (default: today)."""
    if ref is None:
        ref = date.today()
    return f"{ref.year - 1}-12" if ref.month == 1 else f"{ref.year}-{ref.month - 1:02d}"


def _send_monthly_report_for(period_str: str) -> None:
    """Generate Excel + PDF for period_str ('YYYY-MM') and email to superadmins.

    收款相關 KPI（總應收/已收款/手續費合計/實收淨額）反映「本月實際收款」——
    依款項的 receivedAt 是否落在當月判斷，跟案件本身是何時報價/成案無關。

    2026-09-01 修復：舊版改用 casesPeriod（quote_date 落在當月的案件）過濾
    outstanding/allItems 後才重新計算這幾個 KPI，若當月剛好沒有新報價/成案
    的案件（casesPeriod 空），會把這幾個 KPI 全部歸零——即使當月實際上真的
    收到舊案件的款項也一樣被清空（使用者以小林機械案為例回報 8 月月報「總
    應收/已收/未收/實收/合約總案」全是零，就是這個成因）。改直接沿用
    _collect() 已經依 receivedAt 正確算好的 summary.periodReceived/periodFee/
    periodNet，不用案件簽約時間重新篩一次。未收款清單／合約總案數等「當前
    餘額」類指標則維持不篩選（跟互動版 reports.html 同一份邏輯一致——那些
    本來就是累計快照，不是本期流量，不該隨月份歸零）。"""
    from helpers.email_notify import notify_monthly_report
    try:
        label, d0, d1 = _parse_period(period_str)
        data   = _augment_with_targets(_collect(d0, d1), d0)
        gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")

        mail_data = dict(data)
        mail_data["casesAll"] = data["casesPeriod"]
        mail_data["summary"]  = dict(data["summary"])
        mail_data["summary"].update({
            "totalReceivable": data["summary"]["periodReceived"],
            "totalCollected":  data["summary"]["periodReceived"],
            "totalFee":        data["summary"]["periodFee"],
            "netCollected":    data["summary"]["periodNet"],
        })
        mail_data["salesPerf"]   = [
            s for s in data["salesPerf"]
            if any(c["salesPerson"] == s["salesPerson"] for c in data["casesPeriod"])
        ]
        mail_data["marginCases"] = [c for c in data["casesPeriod"]
                                    if c.get("actualMarginPct") is not None and c.get("settleStatus") == "finalized"]

        # 2026-08-30：月報過去完全沒有帶入《月支出》資料（_build_excel() 只能
        # 拿到空的 fallback），現在一併補上《當月收支》《今年度收支》兩塊——
        # 「當月」直接用這次報告的目標月份 period_str（不是今天的真實月份，
        # 因為補寄舊月份時「今天」跟「這封信在講的月份」不是同一件事），
        # 「今年度」用該月份所屬的整年。
        mail_data.update(_build_income_expense_scopes(int(period_str[:4]), period_str))

        try:
            excel_bytes = _build_excel(mail_data, label, gen_at)
        except Exception as exc:
            _log.warning("月報 Excel 產製失敗（%s）: %s", period_str, exc)
            excel_bytes = None

        try:
            pdf_bytes = _html_to_pdf(_build_report_html(mail_data, label, gen_at))
        except Exception as exc:
            _log.warning("月報 PDF 產製失敗（%s）: %s", period_str, exc)
            pdf_bytes = None

        notify_monthly_report(label, period_str, excel_bytes, pdf_bytes)
        _log.info("月報已寄送：%s（含 %d 件本月案件）", period_str, len(data["casesPeriod"]))
    except Exception as exc:
        _log.warning("_send_monthly_report_for 失敗（%s）: %s", period_str, exc)


def _catchup_monthly_reports() -> None:
    """Process all months from (last_sent + 1) through previous month in order."""
    prev = _prev_month_str()
    last_sent = _get_setting("monthly_report_last_sent") or ""

    if not last_sent:
        # First-ever run — only send previous month (avoid spamming all historical data)
        _send_monthly_report_for(prev)
        _set_setting("monthly_report_last_sent", prev)
        _log.info("月報初次執行，已寄送 %s", prev)
        return

    if last_sent >= prev:
        return  # already up to date

    # Advance month by month
    try:
        yr, mo = map(int, last_sent.split("-"))
    except ValueError:
        _send_monthly_report_for(prev)
        _set_setting("monthly_report_last_sent", prev)
        return

    while True:
        mo += 1
        if mo > 12:
            mo = 1
            yr += 1
        current = f"{yr}-{mo:02d}"
        _send_monthly_report_for(current)
        _set_setting("monthly_report_last_sent", current)
        if current >= prev:
            break

    _log.info("月報補寄完成，最後寄送 %s", prev)


def schedule_monthly_report() -> None:
    """Call once on server startup.
    Immediately runs catch-up for any missed months, then repeats on the 1st
    of each month at 08:00 local time."""

    # Always run catch-up on startup
    threading.Thread(target=_catchup_monthly_reports, daemon=True).start()

    def _next_1st_08() -> float:
        now = datetime.now()
        if now.month == 12:
            nxt = now.replace(year=now.year + 1, month=1, day=1,
                              hour=8, minute=0, second=0, microsecond=0)
        else:
            nxt = now.replace(month=now.month + 1, day=1,
                              hour=8, minute=0, second=0, microsecond=0)
        return max((nxt - now).total_seconds(), 1.0)

    def _monthly_loop():
        # Run catch-up (handles the case where months were skipped during the wait)
        _catchup_monthly_reports()
        t = threading.Timer(_next_1st_08(), _monthly_loop)
        t.daemon = True
        t.start()

    t = threading.Timer(_next_1st_08(), _monthly_loop)
    t.daemon = True
    t.start()
    _log.info("月報排程已啟動，下次寄送時間：%.0f 秒後（每月 1 日 08:00）", _next_1st_08())


# ── Monthly trend endpoint ─────────────────────────────────────────────────────

@router.get("/api/reports/monthly-trend")
def monthly_trend(months: int = 12, authorization: str = Header(None)):
    """近 N 月 MoM 趨勢：新成案件數、合約金額、實收金額、收入加權平均毛利率。"""
    u = _require_user(authorization)
    _require_reports_access(u)

    months = min(max(months, 1), 36)
    today  = date.today()

    month_list = []
    for i in range(months - 1, -1, -1):
        total_m = today.year * 12 + today.month - 1 - i
        py, pm  = total_m // 12, total_m % 12 + 1
        key     = f"{py}-{pm:02d}"
        label   = f"{pm}月" if py == today.year else f"{pm}/{str(py)[2:]}"
        month_list.append({"key": key, "label": label})

    month_map = {
        m["key"]: {"newCases": 0, "revenue": 0, "mRevSum": 0.0, "mProfitSum": 0.0, "collected": 0}
        for m in month_list
    }

    conn = get_db()
    won_month = quote_won_month_map(conn)
    rows = conn.execute("""
        SELECT quote_no, total, pretax, net_margin_pct,
               json_extract(data_json,'$.caseRecord') AS cr_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
    """).fetchall()
    conn.close()

    for row in rows:
        total  = row["total"]  or 0
        pretax = row["pretax"] or 0
        nm     = float(row["net_margin_pct"] or 0)
        # 用 quote_won_month_map 決定的月份（見 helpers/quotations.py 說明：
        # 優先 quote_date，quote_date 缺漏或誤填未來日期才退回 audit_log 成案
        # 時間戳），避免系統上線後補登的舊案件全部灌到補登當下的月份。
        qk     = won_month.get(row["quote_no"], "")

        if qk in month_map:
            month_map[qk]["newCases"]   += 1
            month_map[qk]["revenue"]    += total
            month_map[qk]["mRevSum"]    += pretax
            month_map[qk]["mProfitSum"] += pretax * nm / 100

        cr = {}
        if row["cr_json"]:
            try: cr = json.loads(row["cr_json"])
            except Exception: pass
        pay = (cr.get("payment") or {}).get("items", [])
        if pay:
            amounts = payment_item_amounts(total, pay, pretax)
            for idx, pi in enumerate(pay):
                if not pi.get("received"):
                    continue
                amt = amounts[idx]
                aa  = pi.get("actualAmount")
                rat = (pi.get("receivedAt") or "")[:7]
                if rat in month_map:
                    month_map[rat]["collected"] += int(aa if aa is not None else amt)

    result = []
    for m in month_list:
        md      = month_map[m["key"]]
        rev_sum = md["mRevSum"]
        result.append({
            "key":          m["key"],
            "label":        m["label"],
            "newCases":     md["newCases"],
            "revenue":      md["revenue"],
            "collected":    md["collected"],
            "avgMarginPct": round(md["mProfitSum"] / rev_sum * 100, 1) if rev_sum > 0 else None,
        })
    return result


# ── 月支出金額及明細（2026-08-26）───────────────────────────────────────────
# 分類跟 dashboard.py::dashboard_expenses_monthly()（首頁「近12個月支出結構」
# 圖表）刻意保持一致（承攬商派發／設備進貨／料件進貨／其他支出），但那支是
# 固定近12個月、只算月度加總（供圖表用，無明細）；這裡改成依報表選取的任意
# 年度全年 1~12 月計算，且要保留逐筆明細（供「支出明細」表列查核用）。刻意
# 不重構成共用函式直接複用 dashboard.py 那份——兩邊查詢範圍與回傳形狀差異
# 大（固定近12月 vs 任意年度、無明細 vs 有明細），硬共用只會讓兩邊都變難讀，
# 只共用「設備類 parts.category」名單（下方常數，異動時記得跟 dashboard.py
# 那份一起改）。
_EQUIPMENT_PART_CATEGORIES = {"網通設備", "監控設備", "交換器", "伺服器/工控"}


def _collect_income_items(d0: str, d1: str, department_id: Optional[int] = None) -> list:
    """輕量版收入明細撈取（2026-08-30 新增，供《當月收支》《今年度收支》兩張
    新報表用）：只找「已收款」品項落在 [d0,d1] 區間內的，不像 _collect() 還要
    順便算案件績效／業務員／部門／保固／精算快照過期等一大包——那些跟收支
    報表無關，這裡刻意獨立一支輕量查詢，避免《月支出》報表每次都多跑一次
    昂貴的 _collect()（尤其「今年度」範圍要另外抓一次，跟主報表選取的期間
    未必相同）。欄位形狀比照 _collect() 的 periodItems，供 Excel/PDF 共用同一套
    表格欄位。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person, sales_person_id,
               total, pretax,
               json_extract(data_json,'$.caseRecord') AS cr_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
    """).fetchall()
    dept_by_user = {}
    if department_id:
        dept_by_user = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users").fetchall()}
    conn.close()

    items = []
    for row in rows:
        if department_id and dept_by_user.get(row["sales_person_id"]) != department_id:
            continue
        cr = {}
        if row["cr_json"]:
            try:
                cr = json.loads(row["cr_json"])
            except Exception:
                pass
        pay = (cr.get("payment") or {}).get("items", [])
        if not pay:
            continue
        amounts = payment_item_amounts(row["total"] or 0, pay, row["pretax"])
        for idx, pi in enumerate(pay):
            if not pi.get("received"):
                continue
            rat = (pi.get("receivedAt") or "")[:10]
            if not (d0 <= rat <= d1):
                continue
            amt = amounts[idx]
            aa  = pi.get("actualAmount")
            fee = pi.get("feeAmount") or 0
            # 統一用 actualAmount（實收金額），未填則退回系統試算金額
            gross_amt = aa if aa is not None else amt
            items.append({
                "quoteNo":      row["quote_no"],
                "customer":     row["customer_name"] or "",
                "project":      row["project_name"]  or "",
                "salesPerson":  row["sales_person"]  or "",
                "type":         pi.get("type", f"第{idx+1}期"),
                "amount":       gross_amt,
                "receivedAt":   rat,
                "actualAmount": aa,
                "feeAmount":    fee,
                "netAmount":    gross_amt - fee,
                "invoiceNo":    pi.get("invoiceNo", ""),
            })
    items.sort(key=lambda x: x["receivedAt"], reverse=True)
    return items


def _collect_unreceived_items(d0: str, d1: str, department_id: Optional[int] = None) -> list:
    """當月未收款項（現金流口徑，依 expectedReceiptDate）：篩出 received=false
    且 expectedReceiptDate 落在 [d0,d1] 區間內的款項。缺填日期者跳過，不假造。
    2026-09-09 新增，供《當月收支》報表「當月未收（預計）」使用。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person, sales_person_id,
               total, pretax,
               json_extract(data_json,'$.caseRecord') AS cr_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
    """).fetchall()
    dept_by_user = {}
    if department_id:
        dept_by_user = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users").fetchall()}
    conn.close()

    items = []
    for row in rows:
        if department_id and dept_by_user.get(row["sales_person_id"]) != department_id:
            continue
        cr = {}
        if row["cr_json"]:
            try:
                cr = json.loads(row["cr_json"])
            except Exception:
                pass
        pay = (cr.get("payment") or {}).get("items", [])
        if not pay:
            continue
        amounts = payment_item_amounts(row["total"] or 0, pay, row["pretax"])
        for idx, pi in enumerate(pay):
            if pi.get("received"):  # 跳過已收款項
                continue
            exp_date = (pi.get("expectedReceiptDate") or "")[:10]
            if not exp_date or not (d0 <= exp_date <= d1):  # 缺日期或不在區間內都跳過
                continue
            amt = amounts[idx]
            items.append({
                "quoteNo":       row["quote_no"],
                "customer":      row["customer_name"] or "",
                "project":       row["project_name"]  or "",
                "salesPerson":   row["sales_person"]  or "",
                "type":          pi.get("type", f"第{idx+1}期"),
                "amount":        amt,
                "expectedDate":  exp_date,
                "invoiceNo":     pi.get("invoiceNo", ""),
            })
    items.sort(key=lambda x: x["expectedDate"], reverse=True)
    return items


def _collect_payment_anomalies(department_id: Optional[int] = None) -> list:
    """「會讓錢從報表上無聲消失」的收款資料異常（2026-09-11 新增）。

    **為什麼需要這支**：使用者回報「案件資訊有一筆 2026/09/01 收款，營運報表當月
    收入沒有」。查證後報表的計算邏輯是對的——在 db 副本上把那筆設成
    received=true / receivedAt=2026-09-01，`_collect_income_items()` 與
    `_collect()` 兩支都撈得到。所以問題一定出在**資料的兩個欄位沒有同時到位**，
    而這個系統對這種狀態完全沒有任何提示：

    | 狀況 | 收入報表 | 未收報表 | 使用者看到的 |
    |------|---------|---------|------------|
    | `received=1` 但 `receivedAt` 空 | ❌ 不屬於任何月份 | ❌（已收，不算未收） | 案件裡是綠色「已收款」 |
    | `receivedAt` 有值但 `received=0` | ❌（未收） | ❌ 未收看的是 `expectedReceiptDate` | 案件裡看得到收款日期 |

    兩種都是**兩邊都撈不到**——錢就這樣從所有報表上消失，而且沒有任何錯誤訊息。
    這跟 2026-09-09 修過的「精算未完結的額外支出被月支出漏算」、`_m075` 搬移時
    抓到的「歸月日期少了兩層 fallback」是同一類坑：**資料形狀不完整時靜默丟棄**。

    所以這支不是修 bug，是**把這個狀態變成看得見的**。金額用
    `payment_item_amounts()` 算（不重寫 pct 反推公式，理由見該函式 docstring）。

    刻意**不自動修正**（例如「有日期就當作已收」）：勾不勾已收款是人的判斷，
    系統替使用者決定錢收到了沒有，錯了會比漏算更嚴重。這裡只負責點名。
    """
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person, sales_person_id,
               total, pretax,
               json_extract(data_json,'$.caseRecord') AS cr_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
    """).fetchall()
    dept_by_user = {}
    if department_id:
        dept_by_user = {r["id"]: r["department_id"] for r in conn.execute(
            "SELECT id, department_id FROM users").fetchall()}
    conn.close()

    items = []
    for row in rows:
        if department_id and dept_by_user.get(row["sales_person_id"]) != department_id:
            continue
        cr = {}
        if row["cr_json"]:
            try:
                cr = json.loads(row["cr_json"])
            except Exception:
                pass
        pay = (cr.get("payment") or {}).get("items", [])
        if not pay:
            continue
        amounts = payment_item_amounts(row["total"] or 0, pay, row["pretax"])
        for idx, pi in enumerate(pay):
            rcvd = bool(pi.get("received"))
            rat  = (pi.get("receivedAt") or "")[:10]
            if rcvd and not rat:
                kind, hint = ("received_no_date",
                              "已勾「已收款」但沒填收款日期——這筆不屬於任何月份，"
                              "當月收入與未收款項都撈不到它")
            elif rat and not rcvd:
                kind, hint = ("date_not_received",
                              "填了收款日期但沒勾「已收款」——收入報表不算（未收），"
                              "未收報表也不算（那邊看的是預計收款日）")
            else:
                continue
            aa = pi.get("actualAmount")
            items.append({
                "quoteNo":     row["quote_no"],
                "customer":    row["customer_name"] or "",
                "project":     row["project_name"]  or "",
                "salesPerson": row["sales_person"]  or "",
                "type":        pi.get("type", f"第{idx+1}期"),
                "amount":      aa if aa is not None else amounts[idx],
                "receivedAt":  rat,
                "received":    rcvd,
                "kind":        kind,
                "hint":        hint,
            })
    items.sort(key=lambda x: (x["receivedAt"] or "", x["quoteNo"]), reverse=True)
    return items


@router.get("/api/reports/payment-anomalies")
def report_payment_anomalies(department_id: Optional[int] = Query(None),
                             authorization: str = Header(None)):
    """收款資料異常清單（獨立端點，供「應收帳款」頁與任何需要的地方查用）。
    `/api/reports/expenses-monthly`（收支報表的資料源）也會回同一份，不必多打一次。"""
    u = _require_user(authorization)
    _require_reports_access(u)
    items = _collect_payment_anomalies(department_id)
    return {
        "items": items,
        "total": sum(i["amount"] for i in items),
        "count": len(items),
    }


def _months_expense_slice(expenses: dict, months) -> dict:
    """從 _collect_expenses() 回傳的年度資料裡截出「若干個月份」的支出明細＋合計
    （details 逐筆本來就帶 date，直接篩選即可，不必另外查資料庫）。呼叫端
    要自行確保傳入的 expenses 是這些月份所屬年度算出來的（見呼叫點）。

    2026-09-10：從 _month_expense_slice() 抽出，讓「季」範圍共用同一套截取邏輯，
    不必再寫第二份。刻意維持原本的「月份前綴字串比對」而非日期區間比對——
    details 的 date 欄位長度並非保證是完整 YYYY-MM-DD，改用區間比對會讓只有
    YYYY-MM 的資料被靜默丟掉，行為就不再等價了。"""
    want = set(months)
    flat = []
    for cat, rows_ in (expenses.get("details") or {}).items():
        for it in rows_:
            if (it.get("date") or "")[:7] in want:
                flat.append({**it, "cat": cat})
    flat.sort(key=lambda x: x.get("date") or "", reverse=True)
    return {"items": flat, "total": sum(it["amount"] for it in flat)}


def _month_expense_slice(expenses: dict, month: str) -> dict:
    """單一月份版本（行為與 2026-08-30 起完全一致，現為 _months_expense_slice 的包裝）。"""
    return _months_expense_slice(expenses, [month])


def _quarter_months(year: int, quarter: int) -> list:
    """某年某季涵蓋的三個 YYYY-MM 月份字串。"""
    ms = (quarter - 1) * 3 + 1
    return [f"{year}-{m:02d}" for m in range(ms, ms + 3)]


def _quarter_range(year: int, quarter: int):
    """某年某季的起訖日期（含頭含尾，YYYY-MM-DD）。"""
    ms = (quarter - 1) * 3 + 1
    me = ms + 2
    return f"{year}-{ms:02d}-01", f"{year}-{me:02d}-{monthrange(year, me)[1]:02d}"


def _validate_quarter(quarter):
    """季參數驗證：None（不使用季範圍）或 1-4，其餘一律 400。比照
    _parse_period()／_build_income_expense_scopes() 既有的參數驗證慣例，
    不讓 ValueError 漏到 main.py 全域 handler 變成通用 500。"""
    if quarter is None:
        return None
    try:
        q = int(quarter)
    except (TypeError, ValueError):
        raise HTTPException(400, f"quarter 參數格式錯誤（{quarter}），需為 1-4")
    if q not in (1, 2, 3, 4):
        raise HTTPException(400, f"quarter 參數格式錯誤（{quarter}），需為 1-4")
    return q


def _build_income_expense_scopes(year: int, month: str, department_id: Optional[int] = None,
                                 quarter: Optional[int] = None) -> dict:
    """組出《當月收支》《今年度收支》兩張報表（2026-08-30 新增）要用的資料，
    直接回傳可攤平進 _build_excel()/_build_report_html() 的 data dict 片段，
    避免每個呼叫端（畫面查詢／Excel／PDF／每月結算寄信）各自拼裝一次容易
    漏改。month 跟 year 若剛好不同年（例如瀏覽舊年度報表但「當月」仍是今天
    的真實月份），_month_expense_slice() 需要另外用 month 所屬年度重算一次
    支出資料，見該函式 docstring。"""
    try:
        mo_check = int(month[5:7])
        if len(month) != 7 or month[4] != "-" or not (1 <= mo_check <= 12) or int(month[:4]) <= 0:
            raise ValueError
    except (ValueError, IndexError):
        raise HTTPException(400, f"month 格式錯誤（{month}），需為 YYYY-MM")

    expenses_annual = _collect_expenses(year, department_id)
    if month[:4] == str(year):
        month_slice = _month_expense_slice(expenses_annual, month)
    else:
        month_slice = _month_expense_slice(_collect_expenses(int(month[:4]), department_id), month)

    mo_num = int(month[5:7])
    m0 = f"{month}-01"
    m1 = f"{month}-{monthrange(int(month[:4]), mo_num)[1]:02d}"
    y0 = f"{year}-01-01"
    y1 = f"{year}-12-31"

    month_income = _collect_income_items(m0, m1, department_id)
    year_income  = _collect_income_items(y0, y1, department_id)
    month_unreceived = _collect_unreceived_items(m0, m1, department_id)
    payment_anomalies = _collect_payment_anomalies(department_id)

    # 「季」範圍（2026-09-10）：只有呼叫端明確指定 quarter 時才計算，沒指定就回
    # 空集合——月/年兩套欄位的行為完全不變，既有呼叫端（Excel／PDF／每月結算
    # 寄信）不傳 quarter，多花的成本是零。季一定落在 year 之內，所以直接沿用
    # 上面已經算好的 expenses_annual，不必再查一次資料庫。
    #
    # 註：quarterUnreceived* 目前沒有任何前端讀取（month 版的 monthUnreceived*
    # 同樣是 6bfcafb 留下的未接線欄位——「當月未收」卡片最後接的是 receivables
    # 那邊的成案月份口徑，不是這裡的 expectedReceiptDate 現金流口徑）。刻意仍
    # 補上季版本維持三個範圍欄位對稱：範圍之間行為不一致，正是這次期別 bug 的
    # 同一類根因，之後誰要接現金流口徑時三個範圍都現成可用。
    quarter = _validate_quarter(quarter)
    if quarter:
        q0, q1 = _quarter_range(year, quarter)
        quarter_slice      = _months_expense_slice(expenses_annual, _quarter_months(year, quarter))
        quarter_income     = _collect_income_items(q0, q1, department_id)
        quarter_unreceived = _collect_unreceived_items(q0, q1, department_id)
    else:
        quarter_slice      = {"items": [], "total": 0}
        quarter_income     = []
        quarter_unreceived = []

    return {
        "year":              year,
        "expensesYear":      year,
        "expenses":          expenses_annual,
        "expenseMonth":      month,
        "monthExpenseItems": month_slice["items"],
        "monthExpenseTotal": month_slice["total"],
        "monthIncomeItems":  month_income,
        "monthIncomeTotal":  sum(i["amount"] for i in month_income),
        "monthIncomeNet":    sum(i["netAmount"] or 0 for i in month_income),
        "monthUnreceivedItems": month_unreceived,
        "monthUnreceivedTotal":  sum(i["amount"] for i in month_unreceived),
        "yearIncomeItems":   year_income,
        "yearIncomeTotal":   sum(i["amount"] for i in year_income),
        "yearIncomeNet":     sum(i["netAmount"] or 0 for i in year_income),
        "expenseQuarter":        quarter,
        "quarterExpenseItems":   quarter_slice["items"],
        "quarterExpenseTotal":   quarter_slice["total"],
        "quarterIncomeItems":    quarter_income,
        "quarterIncomeTotal":    sum(i["amount"] for i in quarter_income),
        "quarterIncomeNet":      sum(i["netAmount"] or 0 for i in quarter_income),
        "quarterUnreceivedItems": quarter_unreceived,
        "quarterUnreceivedTotal": sum(i["amount"] for i in quarter_unreceived),
        # 收款資料異常（2026-09-11）：刻意**不分期別**——這些款項正是因為欄位不
        # 完整而不屬於任何月份，用期別去篩等於再篩掉一次，那就又看不見了。
        # 見 _collect_payment_anomalies() docstring。
        "paymentAnomalyItems": payment_anomalies,
        "paymentAnomalyTotal": sum(i["amount"] for i in payment_anomalies),
    }


def _collect_expenses(year: int, department_id: Optional[int] = None) -> dict:
    """回傳該年度 1~12 月的支出結構（承攬商/設備/料件/其他）＋逐筆明細。

    department_id（2026-08-28 新增）：承攬商派發／料件進貨／其他支出三類都只透過
    quote_no 間接連結案件，不像 dashboard.py 的案件列表本身就有 sales_person_id
    可直接篩——這裡改用 quote_no → sales_person_id → department_id 兩段查表比對。
    設備進貨若料號批次沒有掛在任何案件（quote_no 為空，例如尚未出貨的常備庫存
    先行進貨），department_id 篩選開啟時會被排除，因為無法歸屬到任何部門，這點
    與 dashboard.py「案件沒有 sales_person_id 就被篩掉」的既有落差一致。"""
    d0 = f"{year}-01-01"
    d1 = f"{year}-12-31"
    month_list = [f"{year}-{m:02d}" for m in range(1, 13)]
    monthly = {mo: {"contractor": 0.0, "equipment": 0.0, "material": 0.0, "other": 0.0} for mo in month_list}
    details: dict = {"contractor": [], "equipment": [], "material": [], "other": []}

    conn = get_db()

    dept_by_quote: dict = {}
    if department_id:
        dept_by_user = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users").fetchall()}
        dept_by_quote = {
            r["quote_no"]: dept_by_user.get(r["sales_person_id"])
            for r in conn.execute("SELECT quote_no, sales_person_id FROM quotations").fetchall()
        }

    def _quote_in_department(quote_no: str) -> bool:
        if not department_id:
            return True
        return bool(quote_no) and dept_by_quote.get(quote_no) == department_id

    # ── 承攬商派發（含稅承攬商費用＋外包人員個別計費，比照 vendor_contractors._dispatch_row）
    disp_rows = conn.execute("""
        SELECT cd.*, vc.name AS vendor_name
        FROM contractor_dispatches cd LEFT JOIN vendor_contractors vc ON vc.id = cd.vendor_id
        WHERE cd.status != 'cancelled' AND cd.dispatch_date BETWEEN ? AND ?
    """, (d0, d1)).fetchall()
    for r in disp_rows:
        mo = (r["dispatch_date"] or "")[:7]
        if mo not in monthly or not _quote_in_department(r["quote_no"]):
            continue
        amt = _dispatch_row(r)["grandTotal"]
        if not amt:
            continue
        monthly[mo]["contractor"] += amt
        details["contractor"].append({
            "date": r["dispatch_date"] or "", "quoteNo": r["quote_no"] or "",
            "desc": r["vendor_name"] or "（未指定承攬商）", "amount": round(amt),
        })

    # ── 料件 / 設備進貨成本（stock_items.cost，依 parts.category 分桶；同月同料號
    # 同批號合併成一列明細——單一序號逐筆列出對報表而言太瑣碎，見上方常數）
    stock_rows = conn.execute("""
        SELECT substr(s.created_at,1,10) AS created_date, s.cost AS cost, s.part_no AS part_no,
               s.batch_no AS batch_no, s.quote_no AS quote_no, p.name AS part_name, p.category AS category
        FROM stock_items s LEFT JOIN parts p ON p.part_no = s.part_no
        WHERE s.status != 'void' AND substr(s.created_at,1,10) BETWEEN ? AND ?
    """, (d0, d1)).fetchall()
    stock_agg: dict = {}
    for r in stock_rows:
        mo = (r["created_date"] or "")[:7]
        if mo not in monthly or not _quote_in_department(r["quote_no"]):
            continue
        bucket = "equipment" if r["category"] in _EQUIPMENT_PART_CATEGORIES else "material"
        cost = float(r["cost"] or 0)
        monthly[mo][bucket] += cost
        key = (mo, bucket, r["part_no"], r["batch_no"] or "")
        agg = stock_agg.setdefault(key, {
            "date": r["created_date"] or "", "bucket": bucket,
            "name": r["part_name"] or r["part_no"] or "（未知料號）",
            "batchNo": r["batch_no"] or "", "amount": 0.0, "qty": 0,
        })
        agg["amount"] += cost
        agg["qty"]    += 1
    for agg in stock_agg.values():
        label = agg["name"] + (f"（批號 {agg['batchNo']}）" if agg["batchNo"] else "")
        details[agg["bucket"]].append({
            "date": agg["date"], "quoteNo": "",
            "desc": f"{label} × {agg['qty']}", "amount": round(agg["amount"]),
        })

    # ── 其他支出（精算「額外支出」逐筆）─────────────────────────────────────
    # 2026-09-09 修：原本這裡只撈 settlement.status='finalized' 的案件，代表
    # **精算還在草稿階段填的額外支出完全不會出現在月支出裡**。實際作業順序是
    # 支出當下就先填進精算表單、案件全部結束後才做完結，中間可能隔好幾個月，
    # 這段期間當月已經花掉的錢在報表上等於不存在。改成只要填了就算，歸月與
    # pending 旗標的判斷邏輯集中在 helpers.case_extra_expenses()（同一支
    # 也給 dashboard.py 用，兩邊過去各寫一份、連歸月依據都不一樣）。
    # 2026-09-11：改從 case_extra_expenses 表取（migration v75 把資料搬出 data_json）。
    # conn 移到迴圈之後才關——新的 helper 要讀表。
    quote_rows = conn.execute(
        "SELECT DISTINCT e.quote_no AS quote_no, q.customer_name AS customer_name "
        "FROM case_extra_expenses e LEFT JOIN quotations q ON q.quote_no = e.quote_no"
    ).fetchall()
    for r in quote_rows:
        if not _quote_in_department(r["quote_no"]):
            continue
        for ex in case_extra_expenses(conn, r["quote_no"]):
            if ex["month"] not in monthly:
                continue
            monthly[ex["month"]]["other"] += ex["cost"]
            desc = ex["desc"] or ex["category"]
            if ex["docNo"]:
                desc = f"{desc}（單號 {ex['docNo']}）"
            details["other"].append({
                "date": ex["date"], "quoteNo": r["quote_no"] or "",
                "desc": f"{r['customer_name'] or ''}｜{ex['category']}｜{desc}".strip("｜"),
                "amount": round(ex["cost"]),
                "files": ex["files"],
                # 精算尚未完結：金額還可能變動，前端會標示出來，不要讓使用者
                # 誤以為是已定稿的數字
                "pending": ex["pending"],
            })

    conn.close()

    monthly_items = []
    totals = {"contractor": 0, "equipment": 0, "material": 0, "other": 0, "total": 0}
    for mo in month_list:
        e = monthly[mo]
        total = e["contractor"] + e["equipment"] + e["material"] + e["other"]
        item = {
            "month": mo, "label": f"{int(mo[5:7])}月",
            "contractor": round(e["contractor"]), "equipment": round(e["equipment"]),
            "material": round(e["material"]), "other": round(e["other"]),
            "total": round(total),
        }
        monthly_items.append(item)
        for k in ("contractor", "equipment", "material", "other", "total"):
            totals[k] += item[k]

    for cat in details:
        details[cat].sort(key=lambda x: x["date"], reverse=True)

    return {"monthly": monthly_items, "totals": totals, "details": details}


@router.get("/api/reports/expenses-monthly")
def report_expenses_monthly(year: int = Query(None), month: str = Query(None),
                             department_id: Optional[int] = Query(None),
                             quarter: Optional[int] = Query(None),
                             authorization: str = Header(None)):
    """2026-08-30：除了既有的年度月支出矩陣＋全年逐筆明細（供「今年度收支」
    使用）之外，額外帶出「當月」（month，預設今天所屬月份）的收入／支出
    逐筆明細＋合計，以及「今年度」的收入逐筆明細＋合計（原本只有支出有逐筆
    明細，收入沒有），供畫面上「月支出」頁籤拆成《當月收支》《今年度收支》
    兩塊各自獨立顯示。"""
    u = _require_user(authorization)
    _require_reports_access(u)
    today = date.today()
    year  = year or today.year
    month = month or today.strftime("%Y-%m")
    return _build_income_expense_scopes(year, month, department_id, quarter)


def _collect_receivable_items(department_id: Optional[int] = None) -> list:
  """輕量應收／已收／未收收集器（2026-09-09）。迭代全部『已成案』『已結案』報價單，
  從 caseRecord.payment.items[] 逐筆列舉，透過既有 quote_won_month_map() 確定
  成案月份（彌補 quote_date 缺漏或明顯未來日期的防呆），最後回傳攤平的逐筆款項 dict
  list，各筆包含 case 層級（quoteNo/customer/project/salesPerson/dealTag/quoteDate/
  wonMonth）與款項層級欄位（idx/type/pct/amount/received/receivedAt/receivedBy/
  expectedReceiptDate/actualAmount/feeAmount/netAmount/invoiceNo/invoiceDate/
  feeNote/note/taxExempt，完全複用 summarize_payment_items() 回傳形狀）。

  非 Excel/PDF 匯出路徑的單純報表頁面用途，故不含 settlement/contractor/warranty
  等匯出常需但頁面用不到的計算；比照 _collect_income_items() 的輕量設計。

  成案月份分組務必透過 quote_won_month_map() 取得——不能直接用 quote_date。
  _collect() L161/L249 已經驗證過該防呆邏輯。"""
  conn = get_db()

  dept_by_user = {}
  if department_id:
    dept_by_user = {r["id"]: r["department_id"]
                    for r in conn.execute("SELECT id, department_id FROM users").fetchall()}

  won_month = quote_won_month_map(conn)

  all_items = []
  for row in conn.execute(
      """SELECT quote_no, customer_name, project_name, sales_person, sales_person_id,
                total, pretax, quote_date,
                COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
                json_extract(data_json,'$.caseRecord') AS cr_json
         FROM quotations
         WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')
               IN ('已成案','已結案')"""
  ).fetchall():
    if department_id and dept_by_user.get(row["sales_person_id"]) != department_id:
      continue

    try:
      cr = json.loads(row["cr_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
      cr = {}

    pay = (cr.get("payment") or {}).get("items", [])
    if not pay:
      continue

    won = won_month.get(row["quote_no"]) or (row["quote_date"] or "")[:7]
    summary = summarize_payment_items(row["total"] or 0, pay, row["pretax"])

    for item in summary["items"]:
      flat = {
        "quoteNo": row["quote_no"],
        "customer": row["customer_name"],
        "project": row["project_name"],
        "salesPerson": row["sales_person"],
        "dealTag": row["deal_tag"],
        "quoteDate": (row["quote_date"] or "")[:10],
        "wonMonth": won,
      }
      flat.update(item)
      all_items.append(flat)

  conn.close()
  return all_items


def _build_receivables_scopes(year: int, month: str, department_id: Optional[int] = None,
                              quarter: Optional[int] = None) -> dict:
  """應收報表（當月/當年度）。月份格式 YYYY-MM；跟 _build_income_expense_scopes()
  一樣回傳 month* 與 year* 雙套欄位，讓前端能獨立切換「當月/今年度」檢視。

  ⚠️ **2026-09-12 起改用「收款日期」口徑**（已收款看 receivedAt、未收款看
  expectedReceiptDate），不再依成案月份分組（2026-09-09 初版是那樣）。改的原因、
  以及「缺日期者另外回傳 undated* 兩組」的理由，見函式內註解——**那兩組是防止
  錢無聲消失的關鍵，不要順手拿掉**。

  monthReceivableTotal == monthCollectedTotal + monthOutstandingTotal 恆成立（by
  construction），year 版同理。此設計刻意與 _collect() 回傳的 summary.total* 欄位
  不同：那些是全歷史累計「餘額快照」（見 _send_monthly_report_for() L2804-2815
  docstring），這裡是某段期間內「成案案件」的應收／已收／未收「流量」——兩種不同的
  統計口徑並存，不衝突。"""
  try:
    mo_check = int(month[5:7])
    if len(month) != 7 or month[4] != "-" or not (1 <= mo_check <= 12) or int(month[:4]) <= 0:
      raise ValueError
  except (ValueError, IndexError):
    raise HTTPException(400, f"month 格式錯誤（{month}），需為 YYYY-MM")

  all_items = _collect_receivable_items(department_id)

  # 2026-09-12：口徑從「成案月份」改成「收款日期」。
  #
  # **為什麼改**：使用者連續兩次回報「案件裡 9/1 已收款，營運報表的已收款卻是 0」。
  # 查證後資料與計算都沒錯——`MQ-202607-045` 的成案月份是 2026-07，所以那筆 9/1
  # 收的錢一直被算在 **7 月**。分頁標題只寫「已收款」，沒有人看得出它問的其實是
  # 「當月成案的案子收了多少」而不是「當月收到多少錢」，而後者才是看這頁的人要的。
  #
  # 分組欄位刻意兩半各用各的日期：
  #   已收款 → receivedAt（錢實際進來的那天）
  #   未收款 → expectedReceiptDate（預計哪天進來）
  # `receivable == collected + outstanding` 這個恆等式仍然成立（by construction），
  # 只是兩半各自用自己的日期挑出來的。
  #
  # ⚠️ **缺日期的不能就這樣消失**。實測開發機：未收款 7 筆**全部沒填預計收款日**，
  # 直接用日期分組會讓它們從每一個月份都撈不到——正是 §5.12 那個「錢無聲消失」
  # 的坑。所以另外回傳 `undated*` 兩組（不分期別、固定顯示），前端獨立列一區。
  # 刻意**不併進月份合計**，否則同一筆會在每個月被重複計算。
  def _recv_month(i):
    return (i.get("receivedAt") or "")[:7]

  def _due_month(i):
    return (i.get("expectedReceiptDate") or "")[:7]

  collected_all   = [i for i in all_items if i["received"]]
  outstanding_all = [i for i in all_items if not i["received"]]

  undated_collected   = [i for i in collected_all if not _recv_month(i)]
  undated_outstanding = [i for i in outstanding_all if not _due_month(i)]

  month_collected   = [i for i in collected_all if _recv_month(i) == month]
  month_outstanding = [i for i in outstanding_all if _due_month(i) == month]
  month_items       = month_collected + month_outstanding

  year_str = str(year)
  year_collected   = [i for i in collected_all if _recv_month(i)[:4] == year_str]
  year_outstanding = [i for i in outstanding_all if _due_month(i)[:4] == year_str]
  year_items       = year_collected + year_outstanding

  quarter = _validate_quarter(quarter)
  if quarter:
    q_months = set(_quarter_months(year, quarter))
    quarter_collected   = [i for i in collected_all if _recv_month(i) in q_months]
    quarter_outstanding = [i for i in outstanding_all if _due_month(i) in q_months]
  else:
    quarter_collected, quarter_outstanding = [], []
  quarter_items = quarter_collected + quarter_outstanding

  return {
    "receivablesYear":         year,
    "receivablesMonth":        month,
    "monthReceivableItems":    month_items,
    "monthReceivableTotal":    sum(i["amount"] for i in month_items),
    "monthCollectedItems":     month_collected,
    "monthCollectedTotal":     sum(i["amount"] for i in month_collected),
    "monthOutstandingItems":   month_outstanding,
    "monthOutstandingTotal":   sum(i["amount"] for i in month_outstanding),
    "yearReceivableItems":     year_items,
    "yearReceivableTotal":     sum(i["amount"] for i in year_items),
    "yearCollectedItems":      year_collected,
    "yearCollectedTotal":      sum(i["amount"] for i in year_collected),
    "yearOutstandingItems":    year_outstanding,
    "yearOutstandingTotal":    sum(i["amount"] for i in year_outstanding),
    "receivablesQuarter":        quarter,
    "quarterReceivableItems":    quarter_items,
    "quarterReceivableTotal":    sum(i["amount"] for i in quarter_items),
    "quarterCollectedItems":     quarter_collected,
    "quarterCollectedTotal":     sum(i["amount"] for i in quarter_collected),
    "quarterOutstandingItems":   quarter_outstanding,
    "quarterOutstandingTotal":   sum(i["amount"] for i in quarter_outstanding),
    # 缺日期而不屬於任何月份的款項——**不併進上面任何一組合計**，前端獨立顯示。
    # 少了這兩組，改成日期口徑之後這些錢會從每一個月份都消失（見上方說明）。
    "undatedCollectedItems":     undated_collected,
    "undatedCollectedTotal":     sum(i["amount"] for i in undated_collected),
    "undatedOutstandingItems":   undated_outstanding,
    "undatedOutstandingTotal":   sum(i["amount"] for i in undated_outstanding),
  }


@router.get("/api/reports/receivables-monthly")
def report_receivables_monthly(year: int = Query(None), month: str = Query(None),
                                department_id: Optional[int] = Query(None),
                                quarter: Optional[int] = Query(None),
                                authorization: str = Header(None)):
  """2026-09-09：應收明細表（當月/當年度獨立檢視）。供 `reports.html` recv/out
  分頁新增的「當月/今年度」切換鈕使用，取代目前硬卡在頂部 period-bar 的期間邏輯。
  僅 admin+ 可存取。"""
  u = _require_user(authorization)
  _require_reports_access(u)
  today = date.today()
  year  = year or today.year
  month = month or today.strftime("%Y-%m")
  return _build_receivables_scopes(year, month, department_id, quarter)
