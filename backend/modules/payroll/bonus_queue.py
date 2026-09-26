"""M07 的「待我簽核」項目（`approval.queue_items`，M01-PLAN §3-7，2026-09-26）：獎金分潤單與以案件為中心的獎金分潤。
M01 佇列只彙整；本檔不讀 M01 的案件表——`customer`／`projectName` 不給，由 M01 依 `linkedQuoteNo` 補。"""
import json

from helpers import approval_queue as _aq


def queue_items(conn) -> list:
    out = []
    # 獎金分潤單（`BN8`）：approval_json 是 bonus_awards 自己的欄位；沒有 submitted_by/at（SPEC-BN8 §1）⇒ 用 created_by/at。
    for r in conn.execute("""
        SELECT id, quote_no, base_amount, created_by, created_at, approval_json
        FROM bonus_awards
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall():
        f = _aq.tier_fields(r["approval_json"])
        out.append(_aq.base_item(
            "bonus_award", "獎金-%s" % r["id"], f,
            customer="",
            projectName="關聯案件 %s" % (r["quote_no"] or ""),
            total=r["base_amount"] or 0,
            quoteDate=(r["created_at"] or "")[:10],
            requestedBy=r["created_by"] or "",
            requestedByDisplay=r["created_by"] or "",
            requestedAt=r["created_at"] or "",
            linkedQuoteNo=r["quote_no"],
            # 🔴 `/api/bonus/awards/{award_id}/...` 吃數字 id
            awardId=r["id"],
        ))
    # 以案件為中心的獎金分潤（SPEC-BONUS §十一）：端點吃案件單號；金額不放進佇列（待發放前只有最高管理者看得到，W1）。
    for r in conn.execute("""
        SELECT quote_no, created_by, created_at, approval_json
        FROM bonus_case_awards
        WHERE status = '待審核'
        ORDER BY id DESC
    """).fetchall():
        f = _aq.tier_fields(r["approval_json"])
        try:
            req = (json.loads(r["approval_json"] or "{}") or {}).get("requestedBy") or r["created_by"]
        except (TypeError, ValueError):
            req = r["created_by"]
        out.append(_aq.base_item(
            "bonus_case_award", r["quote_no"], f,
            total=0,
            quoteDate=(r["created_at"] or "")[:10],
            requestedBy=req or "",
            requestedByDisplay=req or "",
            requestedAt=r["created_at"] or "",
            linkedQuoteNo=r["quote_no"],
        ))
    return out
