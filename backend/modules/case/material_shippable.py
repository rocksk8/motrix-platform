# -*- coding: utf-8 -*-
"""提供者 `material.shippable`（第 33 班 33-S1；契約 docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md §1）：
給 M03 出貨單連動用的「可出貨材料申請」清單——已核准且已確認到貨者。

[單位] case:material_shippable    [層] L2（M01）    [穩定度] 新（第 33 班）
`arrivedQty`（E5）：到貨確認可選填實收數量（`received_qty`）；沒有欄位／沒填＝全數（`quantity`）。本版 S1 先全數；2e 加 `received_qty`
欄位後在 `_arrived` 一處接上即可。唯讀、不 commit。"""
import json

from modules.case import material_approval as MA


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and v not in (float("inf"), float("-inf")) else 0.0


def _arrived(row: dict, applied: float) -> float:
    rq = row.get("received_qty") if isinstance(row, dict) else None            # E5：2e 的選填欄位；沒有＝全數
    return _num(rq) if rq not in (None, "") else applied


def material_shippable(conn, quote_no) -> list:
    q = MA.case_row(conn, quote_no)
    if not q:
        return []
    try:
        data = json.loads(q["data_json"] or "{}") or {}
    except (TypeError, ValueError):
        return []
    orders = {str(o.get("itemId")): o for o in ((data.get("caseRecord") or {}).get("materialOrders") or []) if isinstance(o, dict)}
    out = []
    for item_id, row in MA.rows_for_case(conn, quote_no).items():
        if row.get("status") != MA.S_APPROVED or not row.get("received_on"):
            continue
        o = orders.get(str(item_id))
        if o is None:
            continue
        applied = _num(o.get("quantity"))
        out.append({"materialItemId": str(item_id), "docCode": row.get("doc_code") or "", "name": o.get("itemName") or "", "unit": o.get("unit") or "",
                    "quoteItemId": o.get("quoteItemId") or "", "appliedQty": applied, "arrivedQty": _arrived(row, applied), "status": MA.S_APPROVED})
    out.sort(key=lambda x: x["docCode"])
    return out
