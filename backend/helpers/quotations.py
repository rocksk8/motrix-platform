"""Quotation hot-path field sync helpers."""
import json
from datetime import datetime

from db import get_db

# Prefer real columns; fall back to data_json for rows not yet re-saved (pre-v6 backward compat).
# IMPORTANT: never use bare `SELECT deal_tag` — always use SQL_DEAL_TAG to correctly read pre-v6 rows.
SQL_DEAL_TAG = "COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')"
SQL_SETTLE_STATUS = (
    "COALESCE(NULLIF(settle_status,''), json_extract(data_json,'$.settlement.status'), '')"
)


def _steps_to_tiers(steps: list) -> list:
    """Convert old single-approver steps list to modern tiers list (no status fields)."""
    return [
        {
            "order": i,
            "approvers": [{
                "userId":      s.get("userId", 0),
                "username":    s.get("username", ""),
                "displayName": s.get("displayName", s.get("username", "")),
            }],
        }
        for i, s in enumerate(steps)
    ]


def payment_item_amounts(total: float, pay_items: list) -> list:
    """Return the effective amount for each payment item, in order.

    Trusts each item's stored `amount` field when present — that's what the
    editing UI (case-management.js) actually saved after the user finished
    adjusting percentages/amounts, and is the source of truth. Only falls back
    to reconstructing from `pct` for legacy rows that predate the `amount`
    field being written, with the first item absorbing whatever rounding
    remainder is left over from the rest (so the sum always equals `total`
    exactly). Every backend spot that lists/reports on payment items
    (dashboard.py receivables, reports.py financial reports/PDF/Excel) must
    use this — duplicating the pct-reconstruction formula in each place is
    what let dashboard/reports drift out of sync with what the edit UI
    actually saved (and with each other, if the copies ever diverge).
    """
    if not pay_items:
        return []
    others = sum(
        p["amount"] if p.get("amount") is not None else round(total * (p.get("pct") or 0) / 100)
        for p in pay_items[1:]
    )
    out = []
    for idx, pi in enumerate(pay_items):
        if pi.get("amount") is not None:
            out.append(pi["amount"])
        elif idx == 0:
            out.append(int(total - others))
        else:
            out.append(round(total * (pi.get("pct") or 0) / 100))
    return out


def quote_won_month_map(conn) -> dict:
    """回傳 {quote_no: 'YYYY-MM'}，該報價單「實際轉為已成案」的月份，用於
    成案趨勢一類報表按月分組（2026-08-24）。

    不能用 quote_date（報價單建立當下手動填的日期）——業務員實際簽下這筆案子
    的時間常常對不上，甚至可能是提前估價填的未來日期，導致同一份報表裡有些
    案件被歸到錯誤的月份，有些甚至因為 quote_date 落在報表的近 N 月範圍之外
    而整筆從趨勢圖上消失（實測發現一筆 quote_date 誤填在未來月份的合約，金額
    達 NT$284 萬，就這樣從「近 12 月成案趨勢」裡憑空消失）。

    真正權威的時間來源是 audit_log 裡 action='deal_tag.change'、
    detail.to='已成案' 的事件時間戳——是每次成案動作當下就寫入、不會被後續
    無關編輯覆蓋的紀錄（同一輪也用這套方法修正過 dashboard 的 dealWonAt
    backfill，見 db.py v59 說明）。取每張報價單最後一次轉為已成案的時間（若
    曾降級又重新成案，以最新一次為準）。查不到 audit 紀錄的舊資料（例如匯入
    時就已經是已成案狀態、從未真的呼叫過 deal-tag API）才 fallback 回
    quote_date。"""
    won_events: dict = {}
    for r in conn.execute(
        "SELECT at, target_id, detail FROM audit_log WHERE action='deal_tag.change' ORDER BY at ASC"
    ).fetchall():
        try:
            detail = json.loads(r["detail"] or "{}")
        except Exception:
            continue
        if detail.get("to") == "已成案":
            won_events[r["target_id"]] = r["at"]

    result = {}
    for r in conn.execute(
        f"SELECT quote_no, quote_date FROM quotations WHERE {SQL_DEAL_TAG} IN ('已成案','已結案')"
    ).fetchall():
        won_at = won_events.get(r["quote_no"]) or r["quote_date"] or ""
        if won_at:
            result[r["quote_no"]] = won_at[:7]
    return result


def quote_hot_fields(q: dict) -> tuple:
    """Return (deal_tag, settle_status) from a quotation data dict."""
    if not isinstance(q, dict):
        return "", ""
    deal_tag = q.get("dealTag") or ""
    settle = q.get("settlement")
    settle_status = settle.get("status") or "" if isinstance(settle, dict) else ""
    return deal_tag, settle_status


def save_quotation_json(
    conn,
    quote_no: str,
    data: dict,
    status: str = None,
    updated_at: str = None,
) -> str:
    """Persist data_json and keep deal_tag / settle_status columns in sync.

    Optionally updates status. Returns the updated_at timestamp used.
    """
    now = updated_at or datetime.now().isoformat()
    deal_tag, settle_status = quote_hot_fields(data)
    if status is not None:
        conn.execute(
            "UPDATE quotations "
            "SET data_json=?, updated_at=?, deal_tag=?, settle_status=?, status=? "
            "WHERE quote_no=?",
            (json.dumps(data, ensure_ascii=False), now, deal_tag, settle_status, status, quote_no),
        )
    else:
        conn.execute(
            "UPDATE quotations "
            "SET data_json=?, updated_at=?, deal_tag=?, settle_status=? "
            "WHERE quote_no=?",
            (json.dumps(data, ensure_ascii=False), now, deal_tag, settle_status, quote_no),
        )
    return now
