"""Quotation hot-path field sync helpers."""
import json
import re
from datetime import date, datetime

from fastapi import HTTPException

from db import get_db

# Prefer real columns; fall back to data_json for rows not yet re-saved (pre-v6 backward compat).
# IMPORTANT: never use bare `SELECT deal_tag` — always use SQL_DEAL_TAG to correctly read pre-v6 rows.
SQL_DEAL_TAG = "COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')"
SQL_SETTLE_STATUS = (
    "COALESCE(NULLIF(settle_status,''), json_extract(data_json,'$.settlement.status'), '')"
)


def norm_at(s: str) -> str:
    """統一時間格式（部分表用 'YYYY-MM-DDTHH:MM:SS[.ffffff]'，部分用空白分隔且無
    微秒），確保跨來源合併排序正確。2026-08-28：抽成共用函式——原本 dashboard.py
    的活動動態（首頁）跟 quotations.py::list_case_updates()（案件管理「動態」Tab）
    是同一種「合併多張表、依 created_at 字串排序」的動態牆邏輯，前者已經套用這個
    正規化，後者原本只對其中一個來源（audit_log）做了同樣的處理、其餘四個來源
    （case_updates／work_logs／daily_task_completions／dev_logs）維持各自原始格式
    直接排序——dev_logs 存的是空白分隔格式，跟其餘多數來源的 'T' 分隔格式排序時
    永遠排在同一天其他來源之前（ASCII 空白 0x20 < 'T' 0x54），不管實際時間點是
    幾點，導致同一天有業務開發記錄時動態牆順序會錯亂。兩處統一改呼叫這支共用
    函式，不要再各自處理一部分來源就以為排序沒問題。"""
    return (s or "").replace("T", " ")[:19]


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


def payment_item_amounts(total: float, pay_items: list, pretax: float = None,
                          apply_tax_exempt: bool = True) -> list:
    """Return the effective **receivable** amount for each payment item, in order.

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

    2026-08-28: an item with `taxExempt=True` (approved tax write-off, see
    routers/quotations.py::approve_payment_writeoff()) is only actually
    receivable at its untaxed value — the customer no longer owes the tax
    portion. approve_payment_writeoff() only ever sets the taxExempt flag and
    never touches the stored `amount` itself, so without this the raw
    (still tax-inclusive) `amount` silently kept flowing into every
    backend-wide rollup that calls this shared helper (reports.py, AR aging,
    dashboard.py receivables) even after a write-off was approved — case-
    management.js already got this right client-side via itemAmountPretax(),
    this brings the shared backend helper in line with it. Conversion mirrors
    the frontend formula exactly (item's share of the quote's untaxed/taxed
    ratio, not a flat 5% assumption): pretax_amount = amount * pretax / total.
    Callers that don't have `pretax` handy yet keep the old (unexempted)
    behavior for taxExempt items rather than guessing — better to under-fix
    a rarely-hit call site than divide by an unknown ratio.

    apply_tax_exempt=False（2026-09-02 新增）：回傳「原始開立金額」，不套用
    上述沖銷折算。這行為上是刻意分岔的兩個問題——「客戶現在還欠多少錢」
    （AR/收款/dashboard 要的答案，taxExempt 後金額變小）跟「這筆款項當初
    實際開立的統一發票金額是多少」（稅務匯出/T100 傳票要的答案，taxExempt
    是核准沖銷之後才發生的內部應收帳款減讓，不會、也不能追溯改變已經對
    國稅局申報過的銷項稅額）完全是两回事，把稅額沖銷後的「應收金額」直接
    當成「已開立發票金額=0 稅額」拿去做稅務申報用途，會讓已開立、已產生
    法定稅捐義務的發票在申報文件上憑空消失（見 routers/reports.py::
    _collect_tax_invoices() 呼叫點的說明）。"""
    if not pay_items:
        return []
    others = sum(
        p["amount"] if p.get("amount") is not None else round(total * (p.get("pct") or 0) / 100)
        for p in pay_items[1:]
    )
    out = []
    for idx, pi in enumerate(pay_items):
        if pi.get("amount") is not None:
            amt = pi["amount"]
        elif idx == 0:
            amt = int(total - others)
        else:
            amt = round(total * (pi.get("pct") or 0) / 100)
        if apply_tax_exempt and pi.get("taxExempt") and pretax and total:
            amt = round(amt * pretax / total)
        out.append(amt)
    return out


_INVOICE_NO_RE = re.compile(r"^[A-Z]{2}\d{8}$")


def validate_invoice_no(conn, invoice_no: str, exclude_quote_no: str = None, exclude_idx: int = None) -> None:
    """統一發票號碼格式檢查（2 碼英文字軌＋8 碼流水號，如 AB12345678）＋重複
    偵測（同一組號碼已經填在別的案件/期別上）——2026-09-02 稽核發現這個欄位
    過去完全是自由文字，格式錯誤或複製貼上打錯號碼、甚至真的重複開立，系統
    都不會有任何提示，而重複發票號碼正是國稅局查核時最先抓的稽核紅旗。
    空字串（尚未開立）視為合法，直接放行。exclude_quote_no/exclude_idx 供
    「修改自己這筆」時排除自己，不要跟自己比對出假警報。"""
    inv = (invoice_no or "").strip()
    if not inv:
        return
    if not _INVOICE_NO_RE.match(inv.upper()):
        raise HTTPException(
            400, f"發票號碼格式錯誤（{invoice_no}），需為 2 碼英文字軌＋8 碼數字，例如 AB12345678"
        )
    rows = conn.execute(
        "SELECT quote_no, json_extract(data_json,'$.caseRecord.payment.items') AS pay_json "
        "FROM quotations WHERE json_extract(data_json,'$.caseRecord.payment.items') IS NOT NULL"
    ).fetchall()
    for r in rows:
        try:
            items = json.loads(r["pay_json"] or "[]")
        except Exception:
            continue
        for i, it in enumerate(items):
            if (it.get("invoiceNo") or "").strip().upper() != inv.upper():
                continue
            if r["quote_no"] == exclude_quote_no and i == exclude_idx:
                continue
            raise HTTPException(
                400, f"發票號碼 {invoice_no} 已用於案件 {r['quote_no']} 第{i + 1}期款項，請確認是否重複或填錯"
            )


def quote_won_month_map(conn) -> dict:
    """回傳 {quote_no: 'YYYY-MM'}，該報價單應歸入成案趨勢報表的月份
    （2026-08-24 建立，2026-08-25 修正優先順序）。

    優先用 quote_date（報價單自己的日期欄位）。2026-08-24 那版原本反過來優先
    用 audit_log 裡 action='deal_tag.change'、detail.to='已成案' 的事件時間戳，
    理由是它「每次成案動作當下就寫入、不會被後續編輯覆蓋」；但實測上線後發現
    大量舊案件是系統上線後才補登（quote_date 填的是案件本身真正的日期，例如
    2026-01/02，但補登這個動作、也就是 deal_tag 第一次被設成已成案的那個
    audit 事件，發生在補登當下的 2026-07/08），導致這些舊案件全部被錯誤歸到
    補登月份，「近 12 月成案趨勢」變成看起來業績集中爆量在系統剛上線的
    七、八月——這正是本函式原本要避免的同一種失真，只是換了個方向發生。

    因此改成：quote_date 只要不是「未來日期」（不晚於今天）就直接採用；只有
    quote_date 缺漏，或明顯異常（業務員手誤填成未來月份，例如曾實測發現一筆
    達 NT$284 萬的合約 quote_date 誤填在未來月份，導致整筆從報表的近 N 月
    範圍消失）時，才 fallback 回 audit_log 的成案時間戳。"""
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

    today_str = date.today().isoformat()
    result = {}
    for r in conn.execute(
        f"SELECT quote_no, quote_date FROM quotations WHERE {SQL_DEAL_TAG} IN ('已成案','已結案')"
    ).fetchall():
        qdate = r["quote_date"] or ""
        if qdate and qdate <= today_str:
            chosen = qdate
        else:
            chosen = won_events.get(r["quote_no"]) or qdate
        if chosen:
            result[r["quote_no"]] = chosen[:7]
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
