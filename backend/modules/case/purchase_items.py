# -*- coding: utf-8 -*-
"""請購單／採購單連結案件品項（32-S1；設計 docs/platform/plans/PR-PO-CASE-ITEM-LINK-DESIGN.md §2.1／§2.2／§2.4）。

純函式為主：報價品項的計畫量、單據明細（`lines_json` 的 `itemId`）已用量、剩餘量、超計畫判定。
- 品項＝`quotations.data_json.items[]`（排除 `type=='header'`、沒有 `id` 或說明的列）；計畫量＝`qty`、計畫單位成本＝`cost`。
- 已請購量＝請購單（purchase_req）明細；已採購量＝採購單（purchase_order）明細；只計 `COUNTED_EXTRA_STATUSES`（待審核／簽核中／已核准；
  草稿不佔量——送審時再驗；作廢、已駁回釋放）。
- 不用 json_extract：單案件的單據量級小，在 Python 解析 `lines_json`。
"""
import json

from modules.case.recognition import COUNTED_EXTRA_STATUSES

REQ, ORD = "purchase_req", "purchase_order"


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return n if n == n and n not in (float("inf"), float("-inf")) else 0.0


def plan_items(quotation_data) -> list:
    """報價單 data ⇒ `[{itemId, description, brand, unit, planQty, planUnitCost}]`（保持報價順序）。"""
    out = []
    items = (quotation_data or {}).get("items") if isinstance(quotation_data, dict) else None
    for it in items or []:
        if not isinstance(it, dict) or it.get("type") == "header":
            continue
        iid = str(it.get("id") or "").strip()
        desc = str(it.get("description") or "").strip()
        if not iid or not desc:
            continue
        out.append({"itemId": iid, "description": desc, "brand": str(it.get("brand") or ""), "unit": str(it.get("unit") or ""),
                    "planQty": _num(it.get("qty")), "planUnitCost": _num(it.get("cost"))})
    return out


def usage(rows, *, exclude_id=None) -> dict:
    """單據列（`kind`、`status`、`lines_json`、`id`）⇒ `{itemId: {"requestedQty", "orderedQty"}}`。
    只計 COUNTED 狀態；`exclude_id`＝正在編輯／送審的那一張（不要把自己算進已用量）。"""
    out = {}
    for r in rows:
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        kind = r["kind"] or ""
        if kind not in (REQ, ORD) or (r["status"] or "") not in COUNTED_EXTRA_STATUSES:
            continue
        try:
            lines = json.loads(r["lines_json"] or "[]")
        except (TypeError, ValueError):
            continue
        for l in lines if isinstance(lines, list) else []:
            if not isinstance(l, dict) or not str(l.get("itemId") or "").strip():
                continue
            u = out.setdefault(str(l["itemId"]).strip(), {"requestedQty": 0.0, "orderedQty": 0.0})
            u["requestedQty" if kind == REQ else "orderedQty"] += _num(l.get("qty"))
    return out


def picker(quotation_data, rows, *, show_cost=True, exclude_id=None) -> list:
    """挑選器清單：計畫量、已請購、已採購、剩餘可採購量（＝計畫量−已採購；請購只提示不扣）。
    `show_cost=False`（看不到財務金額）⇒ 不給 `planUnitCost`。"""
    used = usage(rows, exclude_id=exclude_id)
    out = []
    for p in plan_items(quotation_data):
        u = used.get(p["itemId"], {"requestedQty": 0.0, "orderedQty": 0.0})
        row = {k: v for k, v in p.items() if show_cost or k != "planUnitCost"}
        row.update(requestedQty=u["requestedQty"], orderedQty=u["orderedQty"],
                   remainingQty=max(p["planQty"] - u["orderedQty"], 0.0))
        out.append(row)
    return out


def overplan(kind, lines, quotation_data, rows, *, exclude_id=None) -> list:
    """本單明細對累計上限的檢查 ⇒ `[{index, itemId, planQty, usedQty, lineQty, over, reason}]`（只列超出者）。
    採購單：已採購量＋本單同品項各列量 ＞ 計畫量 ⇒ 超出（要有 `overPlanReason`，由呼叫端決定 400）。
    請購單：同樣算，但只作警示（呼叫端不擋；設計 Q3）。品項不在報價內（已刪）⇒ 不算超出（視為額外支出歸類）。"""
    plan = {p["itemId"]: p for p in plan_items(quotation_data)}
    used = usage(rows, exclude_id=exclude_id)
    key = "orderedQty" if kind == ORD else "requestedQty"
    run, out = {}, []
    for i, l in enumerate(lines or []):
        if not isinstance(l, dict):
            continue
        iid = str(l.get("itemId") or "").strip()
        if not iid or iid not in plan:
            continue
        run[iid] = run.get(iid, 0.0) + _num(l.get("qty"))
        total = used.get(iid, {}).get(key, 0.0) + run[iid]
        cap = plan[iid]["planQty"]
        if total > cap + 1e-9:
            out.append({"index": i, "itemId": iid, "planQty": cap, "usedQty": used.get(iid, {}).get(key, 0.0),
                        "lineQty": _num(l.get("qty")), "over": total - cap,
                        "reason": str(l.get("overPlanReason") or "").strip()})
    return out
