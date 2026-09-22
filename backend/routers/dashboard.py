"""Dashboard stats, monthly chart, devices, receivables, GCIS lookup, sales orders, materials."""
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query

from db import db_conn, get_db
from helpers import (_require_user, _warranty_expiry, payment_item_amounts, norm_at,
                     case_extra_expenses, user_has_module, can_see_financial,
                     require_any_module, _get_setting, _set_setting)
from routers.dev_crm import _can_access_case
from routers.vendor_contractors import _dispatch_row

router = APIRouter()
logger = logging.getLogger(__name__)

_GCIS_UA = "Mozilla/5.0 (compatible; MOTRIX-ERP/1.0)"

# ── GCIS helpers ──────────────────────────────────────────────────────────────

_GCIS_OK   = "ok"
_GCIS_NONE = "not_found"
_GCIS_ERR  = "network_error"

def _gcis_get(url: str) -> tuple:
    """Returns (data_list, status) where status is _GCIS_OK / _GCIS_NONE / _GCIS_ERR."""
    try:
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": _GCIS_UA}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            if not raw or not raw.strip():
                return [], _GCIS_NONE
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, list) and data:
                return data, _GCIS_OK
            return [], _GCIS_NONE
    except Exception as exc:
        logger.warning("GCIS lookup failed: %s %s", type(exc).__name__, exc)
        return [], _GCIS_ERR


def _normalize(d: dict) -> dict:
    return {
        "name":   d.get("Company_Name")          or d.get("Business_Name")   or "",
        "taxId":  d.get("Business_Accounting_NO") or "",
        "status": d.get("Company_Status")         or d.get("Business_Status") or "",
    }


#: 每天最多讓使用者查幾次公司資料。**可以從設定改。**
#:
#: ## 🔴 理由不是安全，是**我們是別人服務的用戶**
#: 那是政府開放資料的 API，額度算在**我們的 IP** 上。
#: ☠️ 一個寫壞的前端迴圈就能把當天的額度用完，
#: 而畫面上只會是「**查不到這個統編**」—— 🔑 跟「這家公司真的不存在」
#: 長得一模一樣，而使用者會去改他手上那張紙。
#: 📌 與 OSM 圖磚被擋是同一族：**被對方擋下來的樣子，是我們的資料看起來不見了。**
#:
#: ⚠️ **一次呼叫最多送出兩個請求**（公司行號查不到時會再查商業登記）
#: ⇒ 對 GCIS 的實際上限是這個數字的兩倍。**這裡數的是「使用者查了幾次」**，
#: 因為那才是**可以從畫面理解**的單位，而倍率寫在這裡。
GCIS_DAILY_LIMIT_SETTING = "gcis_daily_limit"
GCIS_DAILY_LIMIT_DEFAULT = 300
#: 今天用掉幾次。**存 DB 不存記憶體** —— `autostart.bat` 是無限迴圈，
#: 存記憶體的話上限實際上會變成「每次重啟最多 N」。
GCIS_USAGE_SETTING = "gcis_daily_usage"


def _gcis_daily_limit() -> int:
    """今天的上限。讀不出數字就用預設值。

    ⚠️ **不可以因為設定壞掉就變成無限** —— 那會讓「設定打錯字」
    與「刻意關掉上限」變成同一件事，而前者沒有人會發現。
    """
    raw = _get_setting(GCIS_DAILY_LIMIT_SETTING, GCIS_DAILY_LIMIT_DEFAULT)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("gcis_daily_limit 不是數字（%r），改用預設 %d",
                       raw, GCIS_DAILY_LIMIT_DEFAULT)
        return GCIS_DAILY_LIMIT_DEFAULT
    return value if value >= 0 else GCIS_DAILY_LIMIT_DEFAULT


def _gcis_take_quota() -> None:
    """用掉一次額度；超過就 429。

    📌 **跨呼叫累計並存 DB**：寫成函式裡的變數的話，語意會變成
    「每次呼叫最多 N」，而那**在一天只呼叫一次的時候恰好相等**
    —— 🔑 那是巧合不是設計（今天已經在背景暖快取那邊踩過同一個）。
    """
    today = date.today().isoformat()
    state = _get_setting(GCIS_USAGE_SETTING, {}) or {}
    if not isinstance(state, dict) or state.get("date") != today:
        # 跨日歸零。
        state = {"date": today, "used": 0}
    used = int(state.get("used", 0) or 0)
    limit = _gcis_daily_limit()
    if used >= limit:
        # ⚠️ 訊息要說得出**是額度不是查無資料** ——
        # 兩者在畫面上都是「查不到」，而處置完全不同。
        raise HTTPException(
            429,
            f"今天的公司資料查詢次數已達上限（{limit} 次）。"
            "這個上限是為了保護我們對政府開放資料平台的用量，"
            "明天會自動恢復；需要調整請在系統設定修改 gcis_daily_limit。")
    state["used"] = used + 1
    _set_setting(GCIS_USAGE_SETTING, state)


GCIS_COMPANY  = "https://data.gcis.nat.gov.tw/od/data/api/236EE382-4942-41A9-BD03-CA0709025E7C"
GCIS_BUSINESS = "https://data.gcis.nat.gov.tw/od/data/api/6BBA2268-1367-4B42-9CCA-BC17499EBE8C"


@router.get("/api/now")
def server_now():
    now = datetime.now()
    return {"year": now.year, "month": now.month, "iso": now.isoformat()}


@router.get("/api/company/tax/{tax_id}")
def lookup_by_tax(tax_id: str, authorization: str = Header(None)):
    """統編查公司。**需要登入。**

    ## 🔴 為什麼這一支自己要檢查，而不是靠 middleware
    原本它**連 `authorization` 參數都沒有** ⇒ 完全靠 `main.py` 的
    middleware，而那一層是一張**豁免清單**（`_PUBLIC_API_PATHS`，13 條）。
    ☠️ 把一條路徑加進那張清單是**兩行**的改動，**而再多一條不會有人注意**
    ⇒ 那一刻這支端點就對全世界開放了，而**沒有任何訊號**。
    🔑 一道只有一層、而第二層明著不覆蓋的防線 —— 今天已經為
    `_smtp_send_blocked()` 記過同一件事。
    """
    _require_user(authorization)
    if not tax_id.isdigit() or len(tax_id) != 8:
        raise HTTPException(400, "統一編號須為 8 位數字")
    # ⚠️ **格式檢查在前、扣額度在後**：一個打錯的統編不該吃掉額度，
    # 而它本來就不會送出任何請求。
    _gcis_take_quota()
    flt = urllib.parse.quote(f"Business_Accounting_NO eq {tax_id}")
    data, st = _gcis_get(f"{GCIS_COMPANY}?$format=json&$filter={flt}&$skip=0&$top=1")
    if not data:
        data, st2 = _gcis_get(f"{GCIS_BUSINESS}?$format=json&$filter={flt}&$skip=0&$top=1")
        if st == _GCIS_ERR or st2 == _GCIS_ERR:
            st = _GCIS_ERR
    if not data:
        if st == _GCIS_ERR:
            raise HTTPException(503, "政府資料庫暫時無法連線，請確認伺服器網路或稍後再試")
        raise HTTPException(404, "查無此統一編號")
    return _normalize(data[0])


@router.get("/api/company/search")
def search_by_name(q: str = Query(..., min_length=2),
                   authorization: str = Header(None)):
    """公司名稱模糊查詢。**需要登入 ＋ 吃每日額度**（理由見 `lookup_by_tax`）。"""
    _require_user(authorization)
    _gcis_take_quota()
    q_safe = q.replace("'", "''")
    flt_c  = urllib.parse.quote(f"Company_Name like '%{q_safe}%'", safe='')
    data, st = _gcis_get(f"{GCIS_COMPANY}?$format=json&$filter={flt_c}&$skip=0&$top=15")
    if not data:
        flt_b = urllib.parse.quote(f"Business_Name like '%{q_safe}%'", safe='')
        data, st = _gcis_get(f"{GCIS_BUSINESS}?$format=json&$filter={flt_b}&$skip=0&$top=15")
    if st == _GCIS_ERR and not data:
        raise HTTPException(503, "政府資料庫暫時無法連線，請確認伺服器網路或稍後再試")
    return [_normalize(d) for d in data]


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/api/dashboard/stats")
def dashboard_stats(department_id: Optional[int] = Query(None), authorization: str = Header(None)):
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    can_finance   = role in ("superadmin", "admin") or "finance" in mods
    can_quotation = role in ("superadmin", "admin", "sales") or "quotation" in mods
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT quote_no, status, customer_name, project_name, total, pretax, quote_date, sales_person,
                   sales_person_id,
                   net_margin_pct, direct_margin_pct,
                   COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') as deal_tag,
                   json_extract(data_json,'$.caseRecord')           as case_record_json,
                   json_extract(data_json,'$.approval')             as approval_json,
                   json_extract(data_json,'$.settlement.summary')   as settlement_summary_json
            FROM quotations ORDER BY id DESC
        """).fetchall()
        cust_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        if department_id:
            dept_by_user = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users").fetchall()}
            rows = [r for r in rows if r["sales_person_id"] and dept_by_user.get(r["sales_person_id"]) == department_id]

    today = date.today()
    total_count   = len(rows)
    pending_count = sum(1 for r in rows if r["status"] == "待審核")
    sent_count    = sum(1 for r in rows if r["status"] == "已送出")
    active_count  = sum(1 for r in rows if r["deal_tag"] == "已成案")
    closed_count  = sum(1 for r in rows if r["deal_tag"] == "已結案")

    my_username = u["username"]
    waiting_for_me_count = 0
    pending_list = []
    for r in rows:
        try:
            appr = json.loads(r["approval_json"] or "{}")
        except Exception:
            appr = {}

        if r["status"] in ("待審核", "簽核中") and can_quotation:
            tiers   = appr.get("tiers") or []
            cur_idx = appr.get("currentTier") or 0
            if 0 <= cur_idx < len(tiers):
                tier_approvers = tiers[cur_idx].get("approvers") or []
                if any(a.get("username") == my_username and a.get("status") != "approved"
                       for a in tier_approvers):
                    waiting_for_me_count += 1

        if r["status"] != "待審核":
            continue
        pending_list.append({
            "quoteNo":     r["quote_no"],
            "customer":    r["customer_name"] or "",
            "total":       r["total"] or 0,
            "requestedBy": appr.get("requestedByDisplay") or appr.get("requestedBy") or "",
            "reasons":     appr.get("reasons") or [],
            "quoteDate":   r["quote_date"] or "",
            "salesPerson": r["sales_person"] or "",
        })

    payment_items = []
    for r in rows:
        if r["deal_tag"] not in ("已成案", "已結案") or not r["case_record_json"]:
            continue
        try:
            cr    = json.loads(r["case_record_json"])
            items = (cr.get("payment") or {}).get("items") or []
            total = r["total"] or 0
            amounts = payment_item_amounts(total, items, r["pretax"])
            for i, p in enumerate(items):
                if p.get("received"):
                    continue
                amount = amounts[i]
                payment_items.append({
                    "quoteNo":  r["quote_no"],
                    "customer": r["customer_name"] or "",
                    "label":    p.get("type", ""),
                    "pct":      p.get("pct", 0),
                    "amount":   amount,
                })
        except Exception:
            pass

    warranty_warnings = []
    for r in rows:
        if not r["case_record_json"]:
            continue
        try:
            cr = json.loads(r["case_record_json"])
            for dev in (cr.get("devices") or []):
                exp, days_left = _warranty_expiry(dev.get("warrantyStart", ""), dev.get("warrantyMonths"))
                if exp is None:
                    continue
                if days_left <= 90:
                    warranty_warnings.append({
                        "name":       dev.get("name", ""),
                        "sn":         dev.get("sn", ""),
                        "customer":   r["customer_name"] or "",
                        "quoteNo":    r["quote_no"],
                        "expiryDate": exp.isoformat(),
                        "daysLeft":   days_left,
                    })
        except Exception:
            pass
    warranty_warnings.sort(key=lambda x: x["daysLeft"])

    margin_rows = []
    for r in rows:
        if r["status"] not in ("已送出",) and r["deal_tag"] not in ("已成案", "已結案"):
            continue
        mg = r["net_margin_pct"]
        if mg is None:
            continue
        cust  = r["customer_name"] or ""
        proj  = r["project_name"] or r["quote_no"]
        label = f"{cust[:6]}\n{proj[:8]}" if cust else proj[:12]
        margin_rows.append({"label": label, "margin": float(mg), "quoteNo": r["quote_no"]})
    margin_rows.sort(key=lambda x: x["margin"], reverse=True)
    margin_top5 = margin_rows[:5]

    # ── Settlement margin comparison ──────────────────────────────────────────
    margin_comparison = []
    for r in rows:
        if r["deal_tag"] not in ("已成案", "已結案"):
            continue
        if not r["settlement_summary_json"]:
            continue
        try:
            s          = json.loads(r["settlement_summary_json"])
            actual_pct = s.get("grossMarginPct")
            if actual_pct is None:
                continue
            cust  = r["customer_name"] or ""
            proj  = r["project_name"]  or ""
            label = cust[:8] if cust else (proj[:8] if proj else r["quote_no"])
            margin_comparison.append({
                "quoteNo":            r["quote_no"],
                "customer":           cust,
                "projectName":        proj,
                "label":              label,
                "estimatedMarginPct": round(float(r["net_margin_pct"] or 0), 1),
                "actualMarginPct":    round(float(actual_pct), 1),
                "quotedPretax":       s.get("quotedPretax") or 0,
                "grossProfit":        s.get("grossProfit")  or 0,
                "profitDiff":         s.get("profitDiff")   or 0,
            })
        except Exception:
            pass
    margin_comparison.sort(key=lambda x: x["actualMarginPct"], reverse=True)

    settled_summary: dict = {}
    if margin_comparison:
        total_q = sum(x["quotedPretax"] for x in margin_comparison)
        total_p = sum(x["grossProfit"]  for x in margin_comparison)
        settled_summary = {
            "count":              len(margin_comparison),
            "totalQuotedPretax":  int(total_q),
            "totalGrossProfit":   int(total_p),
            "avgActualMarginPct": round(total_p / total_q * 100, 1) if total_q > 0 else 0,
        }

    dev_total = dev_expired = dev_soon = dev_ok = dev_none = 0
    for r in rows:
        if not r["case_record_json"]:
            continue
        try:
            cr = json.loads(r["case_record_json"])
            for dev in (cr.get("devices") or []):
                dev_total += 1
                exp, dl = _warranty_expiry(dev.get("warrantyStart", ""), dev.get("warrantyMonths"))
                if exp is None:    dev_none    += 1
                elif dl < 0:       dev_expired += 1
                elif dl <= 30:     dev_soon    += 1
                else:              dev_ok      += 1
        except Exception:
            pass

    recv_total = recv_received = recv_fee = recv_actual = 0
    for r in rows:
        if r["deal_tag"] not in ("已成案", "已結案") or not r["case_record_json"]:
            continue
        try:
            cr    = json.loads(r["case_record_json"])
            items = (cr.get("payment") or {}).get("items") or []
            total = r["total"] or 0
            if not items:
                continue
            amounts = payment_item_amounts(total, items, r["pretax"])
            for i, p in enumerate(items):
                amt = amounts[i]
                recv_total += amt
                if p.get("received"):
                    recv_received += amt
                    recv_fee      += p.get("feeAmount") or 0
                    act_amt        = p.get("actualAmount")
                    recv_actual   += act_amt if act_amt is not None else amt
        except Exception:
            pass

    # ── Project summary（案件/專案管理延伸，2026-08-22）：依狀態分組計數，可依部門篩選 ──
    with db_conn() as proj_conn:
        proj_sql  = "SELECT status FROM projects"
        proj_args = ()
        if department_id:
            proj_sql  += " WHERE department_id=?"
            proj_args  = (department_id,)
        proj_rows = proj_conn.execute(proj_sql, proj_args).fetchall()
    project_summary = {}
    for pr in proj_rows:
        project_summary[pr["status"]] = project_summary.get(pr["status"], 0) + 1

    return {
        "totalQuotes":       total_count,
        "pendingQuotes":     pending_count if can_quotation else 0,
        "waitingForMe":      waiting_for_me_count,
        "sentQuotes":        sent_count,
        "activeCases":       active_count,
        "closedCases":       closed_count,
        "customerCount":     cust_count,
        "projectSummary":    project_summary,
        "pendingList":       pending_list       if can_quotation else [],
        "paymentItems":      payment_items[:10] if can_finance   else [],
        "warrantyWarnings":  warranty_warnings[:5],
        "marginTop5":        margin_top5                    if can_finance else [],
        "marginComparison":  margin_comparison[:8]          if can_finance else [],
        "settledSummary":    settled_summary                if can_finance else {},
        "deviceSummary": {
            "total":   dev_total,
            "expired": dev_expired,
            "soon":    dev_soon,
            "ok":      dev_ok,
            "none":    dev_none,
        },
        "receivableSummary": {
            "total":       recv_total                        if can_finance else 0,
            "received":    recv_received                     if can_finance else 0,
            "unreceived":  (recv_total - recv_received)      if can_finance else 0,
            "feeTotal":    recv_fee                          if can_finance else 0,
            "netReceived": (recv_actual - recv_fee)          if can_finance else 0,
        },
    }


@router.get("/api/dashboard/monthly")
def dashboard_monthly(department_id: Optional[int] = Query(None), authorization: str = Header(None)):
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    if role not in ("superadmin", "admin") and "finance" not in mods:
        return {"items": []}
    with db_conn() as conn:
        # 部門篩選邏輯（2026-09-09 新增）
        dept_by_user = {}
        if department_id:
            dept_by_user = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users").fetchall()}
        # 依實際收款進度與時間分組（2026-08-24，第二輪修正）：使用者指出「銷售收入
        # 趨勢」該反映真正收到錢的月份，不是案件成交（dealTag 轉為已成案，第一輪
        # 用 dealWonAt 修正的邏輯）的月份——業務簽單跟財務實際收款常常不同月份，
        # 同一張報價單也常分好幾期款項陸續收款，理當各自算進實際收到的那個月。
        # 改用 caseRecord.payment.items[]（案件管理頁「款項明細」，每期有
        # received/receivedAt/actualAmount）逐筆展開，只計入 received=true 的款項，
        # 依 receivedAt 分組；金額優先用使用者填的 actualAmount（實收金額，含稅／
        # 可能因手續費打折等因素跟應收金額不同），未填則退回 payment_item_amounts()
        # 換算出的應收金額。跟「應收款狀態」圓環（本檔案上方 recv_received 那段）
        # 共用同一套換算邏輯，避免兩處分開實作、算出不一致的數字。
        rows = conn.execute(
            "SELECT total, pretax, sales_person_id, data_json FROM quotations WHERE "
            "COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')"
        ).fetchall()

        monthly_amount, monthly_count, monthly_fee = {}, {}, {}
        for r in rows:
            # 部門篩選
            if department_id and dept_by_user.get(r["sales_person_id"]) != department_id:
                continue
            try:
                data = json.loads(r["data_json"] or "{}")
            except Exception:
                continue
            pay_items = ((data.get("caseRecord") or {}).get("payment") or {}).get("items") or []
            if not pay_items:
                continue
            amounts = payment_item_amounts(r["total"] or 0, pay_items, r["pretax"])
            for i, p in enumerate(pay_items):
                if not p.get("received"):
                    continue
                mo = (p.get("receivedAt") or "")[:7]
                if not mo:
                    continue
                act_amt = p.get("actualAmount")
                amt = act_amt if act_amt is not None else amounts[i]
                monthly_amount[mo] = monthly_amount.get(mo, 0) + amt
                monthly_count[mo]  = monthly_count.get(mo, 0) + 1
                monthly_fee[mo]    = monthly_fee.get(mo, 0) + (p.get("feeAmount") or 0)

        today = date.today()
        month_list = []
        for i in range(11, -1, -1):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            month_list.append(f"{y:04d}-{m:02d}")

        items = []
        for mo in month_list:
            label = f"{int(mo[5:7])}月"
            gross = monthly_amount.get(mo, 0)
            fee   = monthly_fee.get(mo, 0)
            items.append({
                "month": mo, "label": label,
                "amount": gross,
                "count":  monthly_count.get(mo, 0),
                # 手續費/扣款＋淨收（首頁「當月實收」圓餅圖用，2026-08-25）：跟
                # amount 共用同一組 receivedAt 篩選過的款項明細，保證兩者加總對得
                # 起來，不是兩套各自平行的計算。
                "fee": fee,
                "net": gross - fee,
            })

        return {"items": items}


# 設備類 parts.category（進貨成本歸「設備」；線材配件／其他／無法對應 part_no 一律歸「料件」）
_EQUIPMENT_PART_CATEGORIES = {"網通設備", "監控設備", "交換器", "伺服器/工控"}


@router.get("/api/dashboard/expenses-monthly")
def dashboard_expenses_monthly(department_id: Optional[int] = Query(None), authorization: str = Header(None)):
    """近 12 個月支出結構：承攬商派發（比照 vendor_contractors._dispatch_row 的
    grandTotal＝含稅承攬商費用＋外包人員個別計費）／料件與設備進貨成本（stock_items.cost，
    依 parts.category 分桶）／其他支出（已精算完結案件的 settlement.extraItems，依
    editHistory 最後一筆 settlement_finalized 的時間歸月）。"""
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    if role not in ("superadmin", "admin") and "finance" not in mods:
        return {"items": [], "otherBreakdown": {}}

    with db_conn() as conn:
        # 部門篩選邏輯（2026-09-09 新增）
        dept_by_quote = {}
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

        today = date.today()
        month_list = []
        for i in range(11, -1, -1):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            month_list.append(f"{y:04d}-{m:02d}")
        month_set = set(month_list)

        expenses = {mo: {"contractor": 0.0, "equipment": 0.0, "material": 0.0, "other": 0.0} for mo in month_list}
        other_breakdown = {mo: {} for mo in month_list}

    with db_conn() as conn:

        # ── 承攬商派發 ───────────────────────────────────────────────────────────
        disp_rows = conn.execute(
            "SELECT * FROM contractor_dispatches WHERE status != 'cancelled'"
        ).fetchall()
        for r in disp_rows:
            mo = (r["dispatch_date"] or "")[:7]
            if mo not in expenses or not _quote_in_department(r["quote_no"]):
                continue
            expenses[mo]["contractor"] += _dispatch_row(r)["grandTotal"]

        # ── 料件 / 設備進貨成本 ──────────────────────────────────────────────────
        stock_rows = conn.execute("""
            SELECT s.created_at AS created_at, s.cost AS cost, s.quote_no, p.category AS category
            FROM stock_items s LEFT JOIN parts p ON p.part_no = s.part_no
            WHERE s.status != 'void'
        """).fetchall()
        for r in stock_rows:
            mo = (r["created_at"] or "")[:7]
            if mo not in expenses or not _quote_in_department(r["quote_no"]):
                continue
            bucket = "equipment" if r["category"] in _EQUIPMENT_PART_CATEGORIES else "material"
            expenses[mo][bucket] += float(r["cost"] or 0)

        # ── 其他支出（精算「額外支出」逐筆）─────────────────────────────────────
        # 2026-09-09 修：這裡原本有兩個問題，(a) 只撈 settlement.status='finalized'
        # 的案件，草稿階段填的額外支出完全不算；(b) 一律用精算完結時間歸月，連
        # reports.py 2026-09-02 已經改用 expenseDate（憑證日期）的修正都沒同步過來，
        # 所以首頁「本月支出」跟營運報表的同一個數字本來就對不起來。兩處統一改用
        # helpers.case_extra_expenses()。
        # 2026-09-11：額外支出搬到 case_extra_expenses 表（migration v75），改成直接
        # 從那張表取有資料的案件，不再掃 data_json 的 json_extract。conn 也因此必須
        # 撐到迴圈結束才關——新的 helper 要讀表。
        quote_rows = conn.execute(
            "SELECT DISTINCT quote_no FROM case_extra_expenses"
        ).fetchall()
        for r in quote_rows:
            if not _quote_in_department(r["quote_no"]):
                continue
            for ex in case_extra_expenses(conn, r["quote_no"]):
                if ex["month"] not in expenses:
                    continue
                expenses[ex["month"]]["other"] += ex["cost"]
                other_breakdown[ex["month"]][ex["category"]] = (
                    other_breakdown[ex["month"]].get(ex["category"], 0) + ex["cost"]
                )

    items = []
    for mo in month_list:
        e = expenses[mo]
        total = e["contractor"] + e["equipment"] + e["material"] + e["other"]
        items.append({
            "month":      mo,
            "label":      f"{int(mo[5:7])}月",
            "contractor": round(e["contractor"]),
            "equipment":  round(e["equipment"]),
            "material":   round(e["material"]),
            "other":      round(e["other"]),
            "total":      round(total),
        })

    return {
        "items": items,
        "otherBreakdown": {mo: {k: round(v) for k, v in cats.items()} for mo, cats in other_breakdown.items()},
    }


# ── Devices ───────────────────────────────────────────────────────────────────

@router.get("/api/devices")
def list_devices(
    customer:      Optional[str] = None,
    search:        Optional[str] = None,
    deal_tag:      Optional[str] = None,
    authorization: str           = Header(None),
):
    user = _require_user(authorization)
    require_any_module(user, ('equipment', 'case_manage'), "設備登載／保固")
    with db_conn() as conn:
        sql = """
            SELECT quote_no, customer_name, project_name,
                   COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')    as deal_tag,
                   json_extract(data_json,'$.caseRecord') as case_record_json
            FROM quotations
            WHERE json_extract(data_json,'$.caseRecord') IS NOT NULL
        """
        params = []
        if deal_tag:
            sql += " AND COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')=?"
            params.append(deal_tag)
        rows = conn.execute(sql, params).fetchall()

    today   = date.today()
    devices = []
    for row in rows:
        if not row["case_record_json"]:
            continue
        try:
            cr = json.loads(row["case_record_json"])
            for dev in (cr.get("devices") or []):
                exp, days_left = _warranty_expiry(dev.get("warrantyStart", ""), dev.get("warrantyMonths"))
                expiry_date    = exp.isoformat() if exp else None

                d = {k: v for k, v in dev.items() if not k.startswith("_")}
                d.update({
                    "quoteNo":     row["quote_no"],
                    "customer":    row["customer_name"] or "",
                    "projectName": row["project_name"] or "",
                    "dealTag":     row["deal_tag"] or "",
                    "expiryDate":  expiry_date,
                    "daysLeft":    days_left,
                })

                if customer and customer.lower() not in d["customer"].lower():
                    continue
                if search:
                    sq = search.lower()
                    if not any(sq in str(d.get(f) or "").lower()
                               for f in ("name", "sn", "mac", "customer", "location", "quoteNo")):
                        continue

                devices.append(d)
        except Exception:
            pass

    def _sort(d):
        dl = d.get("daysLeft")
        if dl is None:  return (3, "")
        if dl < 0:      return (0, f"{dl:06d}")
        if dl <= 30:    return (1, f"{dl:06d}")
        if dl <= 90:    return (2, f"{dl:06d}")
        return (3, d.get("customer", ""))

    devices.sort(key=_sort)
    return {"items": devices, "total": len(devices)}


# ── Sales Orders & Materials ──────────────────────────────────────────────────

@router.get("/api/sales-orders")
def list_sales_orders(authorization: str = Header(None)):
    """已成案／已結案案件清單（含金額與毛利率）。

    2026-09-13（模組權限稽核）：原本只要求登入。這支回的是全公司成案金額與
    **毛利率**，而它的頁面 `sales-orders.html` 在 2026-08-31（`87e16cb`）就已退役
    ——端點卻留著沒有任何模組檢查，等於任何登入者（含 viewer、automation 服務
    帳號）都撈得到。依使用者裁示補上兩道：①`finance` 模組或 admin+（比照
    `cashier.py::_require_view_access()`，`finance` 這個模組的標籤本來就是
    「應收帳款／銷售訂單」）②財務金額可視（viewer／engineer 不該看到金額）。
    """
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin") and not user_has_module(user, "finance"):
        raise HTTPException(403, "僅管理員或具『應收帳款／銷售訂單』模組的使用者可查閱")
    if not can_see_financial(user):
        raise HTTPException(403, "此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）")
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT quote_no, customer_name, project_name, total, pretax, quote_date, sales_person,
                   net_margin_pct,
                   COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')         AS deal_tag,
                   json_extract(data_json,'$.caseRecord')      AS case_record_json,
                   json_extract(data_json,'$.deliveryTerms')   AS delivery_terms,
                   json_extract(data_json,'$.deliveryAddress') AS delivery_address,
                   (SELECT COUNT(*) FROM case_stages cs WHERE cs.quote_no = quotations.quote_no)
                       AS stages_count,
                   (SELECT COUNT(*) FROM case_stages cs WHERE cs.quote_no = quotations.quote_no AND cs.done=1)
                       AS stages_done
            FROM quotations
            WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
            ORDER BY quote_date DESC
        """).fetchall()

    items = []
    for r in rows:
        cr = {}
        if r["case_record_json"]:
            try: cr = json.loads(r["case_record_json"])
            except Exception: pass

        pay_items = (cr.get("payment") or {}).get("items", [])
        total = r["total"] or 0
        recv_amount = 0
        if pay_items:
            amounts = payment_item_amounts(total, pay_items, r["pretax"])
            for i, p in enumerate(pay_items):
                amt = amounts[i]
                if p.get("received"):
                    recv_amount += amt

        # Phase 5（2026-08-23）：progress_pct/stagesCount 改用 case_stages 表的 SQL
        # 聚合子查詢（見上面 SELECT），取代解析 caseRecord.stages JSON 陣列——
        # payment.items 仍需要整包 caseRecord JSON（跟 stages 無關，不在這次範圍）。
        stages_count = r["stages_count"] or 0
        progress_pct = round(r["stages_done"] / stages_count * 100) if stages_count else 0

        items.append({
            "quoteNo":        r["quote_no"],
            "customer":       r["customer_name"] or "",
            "projectName":    r["project_name"] or "",
            "dealTag":        r["deal_tag"] or "",
            "total":          total,
            "receivedAmount": recv_amount,
            "quoteDate":      r["quote_date"] or "",
            "salesPerson":    r["sales_person"] or "",
            "netMarginPct":   r["net_margin_pct"],
            "deliveryTerms":  r["delivery_terms"] or "",
            "progressPct":    progress_pct,
            "stagesCount":    stages_count,
        })
    return {"items": items, "total": len(items)}


@router.get("/api/dashboard/funnel")
def dashboard_funnel(authorization: str = Header(None)):
    """銷售漏斗：Win Rate + 待追蹤報價（已送出>14天未回應 / 有效期快到期）"""
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    can_quotation = role in ("superadmin", "admin", "sales") or "quotation" in mods

    if not can_quotation:
        return {"funnel": {}, "followUpQuotes": [], "expiringQuotes": []}

    with db_conn() as conn:
        rows = conn.execute("""
            SELECT quote_no, status, customer_name, total, quote_date, sales_person,
                   COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
                   json_extract(data_json,'$.validDays') AS valid_days
            FROM quotations
            WHERE status NOT IN ('草稿')
            ORDER BY quote_date DESC
        """).fetchall()

    today = date.today()
    total_submitted = 0
    won_count = 0
    lost_count = 0
    pending_response = 0
    follow_up_quotes = []
    expiring_quotes = []
    seen_expiring = set()

    for r in rows:
        deal_tag = r["deal_tag"] or ""
        status   = r["status"]
        total_submitted += 1

        if deal_tag in ("已成案", "已結案"):
            won_count += 1
        elif deal_tag == "未成案":
            lost_count += 1
        elif status == "已送出" and not deal_tag:
            pending_response += 1
            qdate_str = (r["quote_date"] or "")[:10]
            try:
                qdate = date.fromisoformat(qdate_str)
                days_since = (today - qdate).days
            except Exception:
                days_since = 0
            try:
                valid_days = int(r["valid_days"] or 30)
            except Exception:
                valid_days = 30
            valid_days_left = valid_days - days_since

            if days_since >= 14:
                follow_up_quotes.append({
                    "quoteNo":       r["quote_no"],
                    "customer":      r["customer_name"] or "",
                    "total":         r["total"] or 0,
                    "salesPerson":   r["sales_person"] or "",
                    "quoteDate":     r["quote_date"] or "",
                    "daysSinceSent": days_since,
                    "validDaysLeft": valid_days_left,
                })
            if 0 < valid_days_left <= 3 and r["quote_no"] not in seen_expiring:
                seen_expiring.add(r["quote_no"])
                expiring_quotes.append({
                    "quoteNo":      r["quote_no"],
                    "customer":     r["customer_name"] or "",
                    "total":        r["total"] or 0,
                    "salesPerson":  r["sales_person"] or "",
                    "quoteDate":    r["quote_date"] or "",
                    "validDaysLeft": valid_days_left,
                })

    decided  = won_count + lost_count
    win_rate = round(won_count / decided * 100, 1) if decided > 0 else None

    follow_up_quotes.sort(key=lambda x: x["daysSinceSent"], reverse=True)
    expiring_quotes.sort(key=lambda x: x["validDaysLeft"])

    return {
        "funnel": {
            "totalSubmitted":  total_submitted,
            "won":             won_count,
            "lost":            lost_count,
            "pendingResponse": pending_response,
            "winRate":         win_rate,
        },
        "followUpQuotes": follow_up_quotes[:10],
        "expiringQuotes": expiring_quotes[:5],
    }


@router.get("/api/dashboard/ops-alerts")
def dashboard_ops_alerts(authorization: str = Header(None)):
    """業務開發案件停滯（洽談中 30 天無新開發記錄，門檻同 helpers.email_notify.notify_dev_case_stale
    的既有定義）+ 出貨單卡簽核（待審核/簽核中超過 5 天未動）提醒。"""
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    is_admin    = role in ("superadmin", "admin")
    can_dev_crm = is_admin or "dev_crm" in mods

    today = date.today()

    # 門檻／篩選條件（is_deleted=0、status='洽談中'、updated_at 起算 30 天）與
    # dev_crm.py 既有的 _check_dev_case_stale()（每日排程通知）完全一致，避免儀表板
    # 顯示的件數跟通知系統對「停滯」的認定兜不起來。
    dev_stale = []
    if can_dev_crm:
        with db_conn() as conn:
            rows = conn.execute("""
                SELECT id, case_name, customer_name, sales_persons, planners, created_by, updated_at
                FROM dev_cases WHERE is_deleted=0 AND status='洽談中'
            """).fetchall()
        for r in rows:
            if not _can_access_case(u, r):
                continue
            try:
                updated    = datetime.strptime(r["updated_at"], "%Y-%m-%d %H:%M:%S")
                days_since = (datetime.now() - updated).days
            except (ValueError, TypeError):
                continue
            if days_since >= 30:
                dev_stale.append({
                    "id":           r["id"],
                    "caseName":     r["case_name"] or "",
                    "customerName": r["customer_name"] or "",
                    "lastActivity": r["updated_at"],
                    "daysSince":    days_since,
                })
        dev_stale.sort(key=lambda x: x["daysSince"], reverse=True)

    with db_conn() as conn:
        rows = conn.execute("""
            SELECT note_no, quote_no, status, customer_name, project_name, updated_at, data_json
            FROM shipping_notes
            WHERE status IN ('待審核','簽核中')
        """).fetchall()

    my_username = u["username"]
    shipping_waiting_for_me = 0
    shipping_stuck = []
    for r in rows:
        try:
            d = json.loads(r["data_json"] or "{}")
        except Exception:
            d = {}
        appr    = d.get("approval") or {}
        tiers   = appr.get("tiers") or []
        cur_idx = appr.get("currentTier") or 0
        if 0 <= cur_idx < len(tiers):
            approvers = tiers[cur_idx].get("approvers") or []
            if any(a.get("username") == my_username and a.get("status") != "approved"
                   for a in approvers):
                shipping_waiting_for_me += 1

        upd = (r["updated_at"] or "")[:10]
        try:
            days_since = (today - date.fromisoformat(upd)).days if upd else 0
        except Exception:
            days_since = 0
        if days_since >= 5:
            shipping_stuck.append({
                "noteNo":       r["note_no"],
                "quoteNo":      r["quote_no"] or "",
                "status":       r["status"],
                "customerName": r["customer_name"] or "",
                "projectName":  r["project_name"] or "",
                "daysSince":    days_since,
            })
    shipping_stuck.sort(key=lambda x: x["daysSince"], reverse=True)

    return {
        "devStale":             dev_stale[:10],
        "shippingWaitingForMe": shipping_waiting_for_me,
        "shippingStuck":        shipping_stuck[:10] if is_admin else [],
    }


@router.get("/api/materials-summary")
def list_materials_summary(
    status:        Optional[str] = None,
    customer:      Optional[str] = None,
    authorization: str           = Header(None),
):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage'), "供應商／料號／採購")
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT quote_no, customer_name,
                   COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')    AS deal_tag,
                   json_extract(data_json,'$.caseRecord') AS case_record_json
            FROM quotations
            WHERE json_extract(data_json,'$.caseRecord') IS NOT NULL
            ORDER BY quote_date DESC
        """).fetchall()

    items = []
    for r in rows:
        if not r["case_record_json"]:
            continue
        try:
            cr = json.loads(r["case_record_json"])
        except Exception:
            continue
        for mat in (cr.get("materials") or []):
            s = "arrived" if mat.get("arrived") else ("ordered" if mat.get("ordered") else "pending")
            if status and s != status:
                continue
            if customer and customer.lower() not in (r["customer_name"] or "").lower():
                continue
            items.append({
                "quoteNo":  r["quote_no"],
                "customer": r["customer_name"] or "",
                "dealTag":  r["deal_tag"] or "",
                "matId":    mat.get("id"),
                "name":     mat.get("name", ""),
                "model":    mat.get("model", ""),
                "qty":      mat.get("qty", 1),
                "unit":     mat.get("unit", "台"),
                "ordered":  bool(mat.get("ordered")),
                "arrived":  bool(mat.get("arrived")),
                "status":   s,
                "note":     mat.get("note", ""),
            })
    return {"items": items, "total": len(items)}


# ── Activity feed ─────────────────────────────────────────────────────────────
# 只列入「內容真的有變動」的動作，PDF 匯出/解鎖編輯這類操作性動作不算，避免洗版。

_QUOTE_ACTION_LABELS = {
    "quotation.create":       "新增報價單",
    "quotation.update":       "編輯報價單內容",
    "quotation.recall":       "撤回報價單",
    "deal_tag.change":        "案件進度異動",
    "case.update":            "更新案件執行記錄",
    "quotation.approve":      "審核通過",
    "quotation.return":       "退回修改",
    "quotation.reject_final": "最終駁回",
    "payment.mark":           "登記收款",
    "quotation.settlement":   "完成成本精算",
}
_DEV_CASE_ACTION_LABELS = {
    "dev_case.create":  "新增業務開發案件",
    "dev_case.status":  "案件狀態異動",
    "dev_case.convert": "轉換為報價單",
}
_SHIPPING_ACTION_LABELS = {
    "shipping.create":  "新增出貨單",
    "shipping.submit":  "出貨單送審",
    "shipping.approve": "出貨單核准",
    "shipping.reject":  "出貨單退回",
    "shipping.update":  "編輯出貨單",
}
_STOCK_STATUS_LABELS = {
    "in_stock":  "入庫／回存",
    "shipped":   "已出貨",
    "installed": "已安裝",
    "void":      "已作廢",
}


def _trunc(s: str, n: int = 50) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


@router.get("/api/dashboard/activity-feed")
def dashboard_activity_feed(limit: int = Query(30, ge=1, le=100),
                             department_id: Optional[int] = Query(None),
                             authorization: str = Header(None)):
    """彙整業務開發／報價單／案件留言／出貨單／工作日誌／進出物料的最新動態，依時間新到舊合併排序。
    department_id 篩選目前只套用在「案件留言板」這個區塊——這是唯一有直接
    sales_person_id 可查的區塊，其餘來源（工作日誌、業務開發記錄等）的作者
    跟部門的對應關係定義不明確，這輪先不強行套用，避免篩選邏輯做錯。"""
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    is_admin      = role in ("superadmin", "admin")
    can_quotation = role in ("superadmin", "admin", "sales") or "quotation" in mods
    can_dev_crm   = is_admin or "dev_crm" in mods

    with db_conn() as conn:
        items = []

        def _visible_to_sales(row) -> bool:
            """比照 §3.4 報價列表過濾規則：sales_person_id=自己id OR
            （尚未回填 sales_person_id 的舊資料）sales_person(顯示名稱文字)=自己"""
            if is_admin:
                return True
            return row["sales_person_id"] == u["id"] or (
                row["sales_person_id"] is None and row["sales_person"] == u["display_name"]
            )

        dept_by_user = {}
        if department_id:
            dept_by_user = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users").fetchall()}

        def _in_department(row) -> bool:
            if not department_id:
                return True
            return bool(row["sales_person_id"]) and dept_by_user.get(row["sales_person_id"]) == department_id

        # 1. 案件留言板 comments（quote_no 範圍比照報價單可視權限）
        if can_quotation:
            rows = conn.execute("""
                SELECT cu.id, cu.quote_no, cu.author, cu.content, cu.created_at,
                       q.customer_name, q.sales_person_id, q.sales_person, du.display_name
                FROM case_updates cu
                LEFT JOIN quotations q ON q.quote_no = cu.quote_no
                LEFT JOIN users du ON du.username = cu.author
                ORDER BY cu.created_at DESC LIMIT 40
            """).fetchall()
            for r in rows:
                if not _visible_to_sales(r) or not _in_department(r):
                    continue
                items.append({
                    "id": f"cu_{r['id']}", "source": "comment", "moduleLabel": "案件留言板",
                    "actor": r["display_name"] or r["author"], "actionLabel": "新增留言",
                    "itemLabel": r["customer_name"] or r["quote_no"] or "", "detail": _trunc(r["content"]),
                    "link": f"case-management.html?q={r['quote_no']}", "at": norm_at(r["created_at"]),
                })

        # 2. 工作日誌（非 admin 只看自己的，比照 §3.4 編輯/刪除權限的既有精神）
        wl_rows = conn.execute("""
            SELECT w.id, w.log_date, w.content, w.created_at, u.id AS uid, u.display_name, u.username
            FROM work_logs w LEFT JOIN users u ON u.id = w.user_id
            ORDER BY w.created_at DESC LIMIT 40
        """).fetchall()
        for r in wl_rows:
            if not is_admin and r["uid"] != u["id"]:
                continue
            items.append({
                "id": f"wl_{r['id']}", "source": "work_log", "moduleLabel": "工作日誌",
                "actor": r["display_name"] or r["username"] or "", "actionLabel": "新增工作日誌",
                "itemLabel": r["log_date"] or "", "detail": _trunc(r["content"]),
                "link": "work-log.html", "at": norm_at(r["created_at"]),
            })

        # 3. 業務開發：開發記錄 + 案件建立／狀態異動／轉換（沿用 dev_crm._can_access_case 逐筆過濾）
        if can_dev_crm:
            dc_map = {r["id"]: r for r in conn.execute(
                "SELECT id, case_name, customer_name, sales_persons, planners, created_by "
                "FROM dev_cases WHERE is_deleted=0"
            ).fetchall()}

            dl_rows = conn.execute("""
                SELECT dl.id, dl.case_id, dl.log_date, dl.channel, dl.content, dl.created_at,
                       lu.display_name AS log_display, lu.username AS log_username
                FROM dev_logs dl LEFT JOIN users lu ON lu.id = dl.log_by
                WHERE dl.needs_approval=0
                ORDER BY dl.created_at DESC LIMIT 40
            """).fetchall()
            for r in dl_rows:
                dc = dc_map.get(r["case_id"])
                if not dc or not _can_access_case(u, dc):
                    continue
                items.append({
                    "id": f"dl_{r['id']}", "source": "dev_log", "moduleLabel": "業務開發",
                    "actor": r["log_display"] or r["log_username"] or "",
                    "actionLabel": f"新增開發記錄（{r['channel']}）" if r["channel"] else "新增開發記錄",
                    "itemLabel": dc["case_name"] or dc["customer_name"] or "",
                    "detail": _trunc(r["content"]), "link": "dev-crm.html", "at": norm_at(r["created_at"]),
                })

            ph = ",".join("?" * len(_DEV_CASE_ACTION_LABELS))
            al_rows = conn.execute(f"""
                SELECT id, at, username, display_name, action, target_id, target_label
                FROM audit_log WHERE target_type='dev_case' AND action IN ({ph})
                ORDER BY at DESC LIMIT 40
            """, list(_DEV_CASE_ACTION_LABELS.keys())).fetchall()
            for r in al_rows:
                try:
                    case_id = int(r["target_id"])
                except (TypeError, ValueError):
                    continue
                dc = dc_map.get(case_id)
                if not dc or not _can_access_case(u, dc):
                    continue
                items.append({
                    "id": f"al_{r['id']}", "source": "dev_case", "moduleLabel": "業務開發",
                    "actor": r["display_name"] or r["username"] or "",
                    "actionLabel": _DEV_CASE_ACTION_LABELS.get(r["action"], r["action"]),
                    "itemLabel": r["target_label"] or dc["case_name"] or "",
                    "detail": "", "link": "dev-crm.html", "at": norm_at(r["at"]),
                })

        # 4. 報價單狀態／內容異動（非 admin 只看自己名下的報價單，比照 §3.4 報價列表過濾規則）
        if can_quotation:
            ph = ",".join("?" * len(_QUOTE_ACTION_LABELS))
            rows = conn.execute(f"""
                SELECT a.id, a.at, a.username, a.display_name, a.action, a.target_id AS quote_no,
                       a.target_label, q.sales_person_id, q.sales_person
                FROM audit_log a LEFT JOIN quotations q ON q.quote_no = a.target_id
                WHERE a.target_type='quotation' AND a.action IN ({ph})
                ORDER BY a.at DESC LIMIT 40
            """, list(_QUOTE_ACTION_LABELS.keys())).fetchall()
            for r in rows:
                if not _visible_to_sales(r):
                    continue
                items.append({
                    "id": f"qa_{r['id']}", "source": "quotation", "moduleLabel": "報價單",
                    "actor": r["display_name"] or r["username"] or "",
                    "actionLabel": _QUOTE_ACTION_LABELS.get(r["action"], r["action"]),
                    "itemLabel": r["target_label"] or r["quote_no"] or "",
                    "detail": "", "link": f"quotation-form.html?id={r['quote_no']}", "at": norm_at(r["at"]),
                })

        # 5. 出貨單（案件管理子頁面，quote_no 歸屬比照報價單可視權限）
        if can_quotation:
            ph = ",".join("?" * len(_SHIPPING_ACTION_LABELS))
            rows = conn.execute(f"""
                SELECT a.id, a.at, a.username, a.display_name, a.action, a.target_id AS note_no,
                       a.target_label, sn.quote_no, q.sales_person_id, q.sales_person
                FROM audit_log a
                LEFT JOIN shipping_notes sn ON sn.note_no = a.target_id
                LEFT JOIN quotations q ON q.quote_no = sn.quote_no
                WHERE a.target_type='shipping_note' AND a.action IN ({ph})
                ORDER BY a.at DESC LIMIT 40
            """, list(_SHIPPING_ACTION_LABELS.keys())).fetchall()
            for r in rows:
                if not _visible_to_sales(r):
                    continue
                link = f"case-management.html?q={r['quote_no']}" if r["quote_no"] else "case-management.html"
                items.append({
                    "id": f"sa_{r['id']}", "source": "shipping", "moduleLabel": "出貨單",
                    "actor": r["display_name"] or r["username"] or "",
                    "actionLabel": _SHIPPING_ACTION_LABELS.get(r["action"], r["action"]),
                    "itemLabel": r["target_label"] or r["note_no"] or "",
                    "detail": "", "link": link, "at": norm_at(r["at"]),
                })

        # 6. 進出物料（序號級庫存異動）
        #
        # 2026-09-15 使用者要求「沒有權限的使用者，最近的變動只能看到自己的」。
        # 這一段原本對**所有登入者全開**（原註解：「比照 /api/devices・
        # /api/materials-summary 開放給所有已登入使用者」）——但那兩支回的是「有哪些
        # 料號、還剩幾個」，這裡回的是「**誰**把哪一個序號用到哪一個案子」，那是人的
        # 行為軌跡，不是庫存數字。上面五個來源每一個都有逐筆過濾，只有這一段沒有，
        # 結果是一個只有 dashboard 模組的檢視者，在首頁就能看到全公司的料件流向。
        #
        # 有庫存／設備模組的人看全部（那本來就是他們的工作範圍），其他人只看自己動過
        # 的；自己沒動過就一筆都不會出現。
        # consumed_by/created_by 存的就是操作者顯示名稱字串（見 inventory.py），非 user id，不需再 join users
        can_inventory = is_admin or "inventory" in mods or "equipment" in mods
        st_rows = conn.execute("""
            SELECT id, part_no, serial_no, status, quote_no, updated_at, consumed_by, created_by
            FROM stock_items ORDER BY updated_at DESC LIMIT 40
        """).fetchall()
        for r in st_rows:
            if not can_inventory:
                # 比對顯示名稱是這張表唯一可用的歸屬依據（沒有 user id 欄位）。
                # 名稱為空的紀錄一律不給——無法證明是自己的，就不是自己的。
                actor = r["consumed_by"] or r["created_by"] or ""
                if not actor or actor != u["display_name"]:
                    continue
            items.append({
                "id": f"st_{r['id']}", "source": "stock", "moduleLabel": "進出物料",
                "actor": r["consumed_by"] or r["created_by"] or "",
                "actionLabel": _STOCK_STATUS_LABELS.get(r["status"], r["status"] or ""),
                "itemLabel": f"{r['part_no']} / {r['serial_no']}",
                "detail": "", "link": "inventory.html", "at": norm_at(r["updated_at"]),
            })

    items.sort(key=lambda x: x["at"], reverse=True)
    return {"items": items[:limit], "total": len(items)}
