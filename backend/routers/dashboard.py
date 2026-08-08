"""Dashboard stats, monthly chart, devices, receivables, GCIS lookup, sales orders, materials."""
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query

from db import get_db
from helpers import _require_user, _warranty_expiry, payment_item_amounts
from routers.dev_crm import _can_access_case

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


GCIS_COMPANY  = "https://data.gcis.nat.gov.tw/od/data/api/236EE382-4942-41A9-BD03-CA0709025E7C"
GCIS_BUSINESS = "https://data.gcis.nat.gov.tw/od/data/api/6BBA2268-1367-4B42-9CCA-BC17499EBE8C"


@router.get("/api/now")
def server_now():
    now = datetime.now()
    return {"year": now.year, "month": now.month, "iso": now.isoformat()}


@router.get("/api/company/tax/{tax_id}")
def lookup_by_tax(tax_id: str):
    if not tax_id.isdigit() or len(tax_id) != 8:
        raise HTTPException(400, "統一編號須為 8 位數字")
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
def search_by_name(q: str = Query(..., min_length=2)):
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
def dashboard_stats(authorization: str = Header(None)):
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    can_finance   = role in ("superadmin", "admin") or "finance" in mods
    can_quotation = role in ("superadmin", "admin", "sales") or "quotation" in mods
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, status, customer_name, project_name, total, quote_date, sales_person,
               net_margin_pct, direct_margin_pct,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') as deal_tag,
               json_extract(data_json,'$.caseRecord')           as case_record_json,
               json_extract(data_json,'$.approval')             as approval_json,
               json_extract(data_json,'$.settlement.summary')   as settlement_summary_json
        FROM quotations ORDER BY id DESC
    """).fetchall()
    cust_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    conn.close()

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
            amounts = payment_item_amounts(total, items)
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
            amounts = payment_item_amounts(total, items)
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

    return {
        "totalQuotes":       total_count,
        "pendingQuotes":     pending_count if can_quotation else 0,
        "waitingForMe":      waiting_for_me_count,
        "sentQuotes":        sent_count,
        "activeCases":       active_count,
        "closedCases":       closed_count,
        "customerCount":     cust_count,
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
def dashboard_monthly(authorization: str = Header(None)):
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    if role not in ("superadmin", "admin") and "finance" not in mods:
        return {"items": []}
    conn = get_db()
    rows = conn.execute("""
        SELECT substr(quote_date, 1, 7) AS month,
               SUM(total)  AS amount,
               COUNT(*)    AS cnt
        FROM quotations
        WHERE quote_date IS NOT NULL AND quote_date != ''
          AND COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
        GROUP BY month
        ORDER BY month ASC
    """).fetchall()

    today = date.today()
    month_list = []
    for i in range(11, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_list.append(f"{y:04d}-{m:02d}")

    data_map = {r["month"]: {"amount": r["amount"] or 0, "count": r["cnt"] or 0} for r in rows}

    items = []
    for mo in month_list:
        d = data_map.get(mo, {"amount": 0, "count": 0})
        label = f"{int(mo[5:7])}月"
        items.append({"month": mo, "label": label, "amount": d["amount"], "count": d["count"]})

    return {"items": items}


# ── Devices ───────────────────────────────────────────────────────────────────

@router.get("/api/devices")
def list_devices(
    customer:      Optional[str] = None,
    search:        Optional[str] = None,
    deal_tag:      Optional[str] = None,
    authorization: str           = Header(None),
):
    _require_user(authorization)
    conn = get_db()
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
    conn.close()

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


# ── Receivables ───────────────────────────────────────────────────────────────

@router.get("/api/receivables")
def list_receivables(status: Optional[str] = None, authorization: str = Header(None)):
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    if role not in ("superadmin", "admin") and "finance" not in mods:
        raise HTTPException(403, "無應收帳款查閱權限")
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, total, quote_date,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')    AS deal_tag,
               json_extract(data_json,'$.caseRecord') AS case_record_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
        ORDER BY quote_date DESC
    """).fetchall()

    items = []
    total_amount = 0
    received_amount = 0

    for row in rows:
        if not row["case_record_json"]:
            continue
        try:
            cr = json.loads(row["case_record_json"])
        except Exception:
            continue
        payment_items = (cr.get("payment") or {}).get("items", [])
        if not payment_items:
            continue

        total = row["total"] or 0
        amounts = payment_item_amounts(total, payment_items)

        for idx, pi in enumerate(payment_items):
            amount = amounts[idx]
            total_amount  += amount
            if pi.get("received"):
                received_amount += amount

            if status == "unreceived" and pi.get("received"):
                continue
            if status == "received" and not pi.get("received"):
                continue

            items.append({
                "quoteNo":      row["quote_no"],
                "customer":     row["customer_name"],
                "dealTag":      row["deal_tag"],
                "quoteDate":    row["quote_date"],
                "idx":          idx,
                "label":        pi.get("type", f"第{idx+1}期"),
                "pct":          pi.get("pct"),
                "amount":       amount,
                "received":     bool(pi.get("received", False)),
                "receivedAt":   pi.get("receivedAt"),
                "receivedBy":   pi.get("receivedBy"),
                "invoiceNo":    pi.get("invoiceNo", ""),
                "actualAmount": pi.get("actualAmount"),
                "feeAmount":    pi.get("feeAmount") or 0,
                "feeNote":      pi.get("feeNote", ""),
                "note":         pi.get("note", ""),
            })

    uninvoiced_count = sum(1 for it in items if not it.get("invoiceNo"))
    fee_total    = sum((it.get("feeAmount") or 0) for it in items if it.get("received"))
    act_rcv_list = [(it.get("actualAmount") if it.get("actualAmount") is not None else it["amount"]) for it in items if it.get("received")]
    actual_received = sum(act_rcv_list)
    return {
        "items":            items,
        "totalAmount":      total_amount,
        "receivedAmount":   received_amount,
        "unreceived":       total_amount - received_amount,
        "uninvoicedCount":  uninvoiced_count,
        "feeTotal":         fee_total,
        "actualReceived":   actual_received,
        "netReceived":      actual_received - fee_total,
    }


# ── Sales Orders & Materials ──────────────────────────────────────────────────

@router.get("/api/sales-orders")
def list_sales_orders(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, total, quote_date, sales_person,
               net_margin_pct,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')         AS deal_tag,
               json_extract(data_json,'$.caseRecord')      AS case_record_json,
               json_extract(data_json,'$.deliveryTerms')   AS delivery_terms,
               json_extract(data_json,'$.deliveryAddress') AS delivery_address
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
        ORDER BY quote_date DESC
    """).fetchall()
    conn.close()

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
            amounts = payment_item_amounts(total, pay_items)
            for i, p in enumerate(pay_items):
                amt = amounts[i]
                if p.get("received"):
                    recv_amount += amt

        stages = cr.get("stages") or []
        progress_pct = 0
        if stages:
            done = sum(1 for s in stages if s.get("done"))
            progress_pct = round(done / len(stages) * 100)

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
            "stagesCount":    len(stages),
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

    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, status, customer_name, total, quote_date, sales_person,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
               json_extract(data_json,'$.validDays') AS valid_days
        FROM quotations
        WHERE status NOT IN ('草稿')
        ORDER BY quote_date DESC
    """).fetchall()
    conn.close()

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
        conn = get_db()
        rows = conn.execute("""
            SELECT id, case_name, customer_name, sales_persons, planners, created_by, updated_at
            FROM dev_cases WHERE is_deleted=0 AND status='洽談中'
        """).fetchall()
        conn.close()
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

    conn = get_db()
    rows = conn.execute("""
        SELECT note_no, quote_no, status, customer_name, project_name, updated_at, data_json
        FROM shipping_notes
        WHERE status IN ('待審核','簽核中')
    """).fetchall()
    conn.close()

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
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')    AS deal_tag,
               json_extract(data_json,'$.caseRecord') AS case_record_json
        FROM quotations
        WHERE json_extract(data_json,'$.caseRecord') IS NOT NULL
        ORDER BY quote_date DESC
    """).fetchall()
    conn.close()

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
