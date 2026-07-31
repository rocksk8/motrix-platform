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
