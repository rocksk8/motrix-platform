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


def usage(rows, *, exclude_id=None, extra_ordered=None) -> dict:
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
    for iid, q in (extra_ordered or {}).items():                    # 叫料的貢獻（沒有連到採購單的叫料列；見 material_ordered）
        u = out.setdefault(iid, {"requestedQty": 0.0, "orderedQty": 0.0})
        u["orderedQty"] += _num(q)
    return out


def live_item_ids(quotation_data) -> set:
    """報價單**現在**還有的品項 id（品項被刪／改版後不在了 ⇒ 連到它的列視為一般額外支出，錢不會消失；設計 §2.4）。"""
    return {p["itemId"] for p in plan_items(quotation_data)}


def load_live_item_ids(conn, quote_no) -> set:
    """讀報價單的現有品項 id；查無報價單 ⇒ 空集合（全部視為額外支出）。"""
    q = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    try:
        data = json.loads((q["data_json"] if q else "") or "{}")
    except (TypeError, ValueError):
        data = {}
    return live_item_ids(data)


def linked_split(lines, live=None):
    """明細列 ⇒ `(連到品項的金額合計, {itemId: 金額})`；金額＝列上 `amount`（`normalize_lines` 已重算）。沒有 `itemId` 的列不算。
    `live`（現有品項 id 集合）給了 ⇒ 連到已不存在品項的列也不算（回到額外支出）；沒給 ⇒ 不過濾（寫入時的檢查用）。"""
    per = {}
    for l in lines if isinstance(lines, list) else []:
        if isinstance(l, dict) and str(l.get("itemId") or "").strip():
            iid = str(l["itemId"]).strip()
            if live is not None and iid not in live:
                continue
            per[iid] = per.get(iid, 0.0) + _num(l.get("amount"))
    return sum(per.values()), per


def item_actuals(rows, *, exclude_id=None, live=None) -> dict:
    """`{itemId: 已認列的品項實際成本}`：只計 COUNTED 狀態的**採購單**連結列（請購單永遠不計成本）。"""
    out = {}
    for r in rows:
        if (r["kind"] or "") != ORD or (r["status"] or "") not in COUNTED_EXTRA_STATUSES:
            continue
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        try:
            lines = json.loads(r["lines_json"] or "[]")
        except (TypeError, ValueError):
            continue
        for iid, amt in linked_split(lines, live)[1].items():
            out[iid] = out.get(iid, 0.0) + amt
    return out


def picker(quotation_data, rows, *, show_cost=True, exclude_id=None, extra_ordered=None) -> list:
    """挑選器清單：計畫量、已請購、已採購、剩餘可採購量（＝計畫量−已採購；請購只提示不扣）。
    `show_cost=False`（看不到財務金額）⇒ 不給 `planUnitCost`。"""
    used = usage(rows, exclude_id=exclude_id, extra_ordered=extra_ordered)
    actual = item_actuals(rows, exclude_id=exclude_id)
    out = []
    for p in plan_items(quotation_data):
        u = used.get(p["itemId"], {"requestedQty": 0.0, "orderedQty": 0.0})
        row = {k: v for k, v in p.items() if show_cost or k != "planUnitCost"}
        row.update(requestedQty=u["requestedQty"], orderedQty=u["orderedQty"],
                   remainingQty=max(p["planQty"] - u["orderedQty"], 0.0))
        if show_cost:                                               # 金額：看不到財務金額的人不給
            row["actualAmount"] = actual.get(p["itemId"], 0.0)
        out.append(row)
    return out


def overplan(kind, lines, quotation_data, rows, *, exclude_id=None, extra_ordered=None) -> list:
    """本單明細對累計上限的檢查 ⇒ `[{index, itemId, planQty, usedQty, lineQty, over, reason}]`（只列超出者）。
    採購單：已採購量＋本單同品項各列量 ＞ 計畫量 ⇒ 超出（要有 `overPlanReason`，由呼叫端決定 400）。
    請購單：同樣算，但只作警示（呼叫端不擋；設計 Q3）。品項不在報價內（已刪）⇒ 不算超出（視為額外支出歸類）。"""
    plan = {p["itemId"]: p for p in plan_items(quotation_data)}
    used = usage(rows, exclude_id=exclude_id, extra_ordered=extra_ordered)
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


# ── 寫入時的驗證（S2）：明細列的 itemId 與累計上限 ─────────────────────────────

LINK_KEYS = ("itemId", "itemQtyPlan", "itemCostPlan", "overPlanReason", "overPlanQty")
MAX_REASON = 500


def _bad(msg):
    from fastapi import HTTPException
    return HTTPException(400, msg)


def _case_state(conn, quote_no):
    """案件的報價資料與其請購／採購單列（讀；呼叫端在寫鎖內時就是一致的快照）。"""
    q = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    try:
        data = json.loads((q["data_json"] if q else "") or "{}")
    except (TypeError, ValueError):
        data = {}
    rows = conn.execute("SELECT id, kind, status, lines_json, doc_code FROM case_extra_expenses WHERE quote_no=? AND kind IN (?,?)",
                        (quote_no, REQ, ORD)).fetchall()
    return data, rows


def case_extra_ordered(conn, quote_no, data, rows) -> dict:
    """叫料對已訂量的貢獻（報價單匯入扣量／上限檢查與採購單挑選器同一口徑）；沒有叫料 ⇒ {}。"""
    return material_ordered(load_material_orders(conn, quote_no, data), [r for r in rows if (r["kind"] or "") == ORD])


def check_lines(conn, quote_no, kind, lines, *, exclude_id=None, require_reason=False):
    """寫入前處理明細的品項連結 ⇒ `(新的明細列, 超計畫警示清單)`；不合法 ⇒ HTTPException(400)。
    - 沒有任何 `itemId` ⇒ 原樣回傳（只拿掉保留鍵；**與沒有這個功能時完全相同**）。
    - 有 `itemId`：只准「有案件的請購單／採購單」；品項必須在報價內；`qty` 必須是大於 0 的數字。
    - 計畫量／計畫成本快照由伺服器依報價寫入（前端送的不採用）；`overPlanQty` 是伺服器算的超出量。
    - 超計畫：`overPlanReason` 只在超出時保留；`require_reason`（送審）且是採購單 ⇒ 超出的列沒有原因 ⇒ 400（Q2）。請購單只警示（Q3）。"""
    lines = [dict(l) if isinstance(l, dict) else l for l in (lines or [])]
    linked = [l for l in lines if isinstance(l, dict) and str(l.get("itemId") or "").strip()]
    for l in lines:
        if isinstance(l, dict) and not str(l.get("itemId") or "").strip():
            for k in LINK_KEYS:
                l.pop(k, None)
    if not linked:
        return lines, []
    if not (quote_no or "") or kind not in (REQ, ORD):
        raise _bad("只有掛在案件底下的請購單／採購單，明細才能連到案件品項")
    data, rows = _case_state(conn, quote_no)
    plan = {p["itemId"]: p for p in plan_items(data)}
    for i, l in enumerate(lines, 1):
        if not isinstance(l, dict) or not str(l.get("itemId") or "").strip():
            continue
        iid = str(l["itemId"]).strip()
        if iid not in plan:
            raise _bad("第 %d 列連到的品項不在這張報價單內（可能已被刪除），請重新選擇" % i)
        qty = l.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) or not qty > 0:
            raise _bad("第 %d 列連到案件品項，數量必須是大於 0 的數字" % i)
        l["itemId"] = iid
        l["itemQtyPlan"], l["itemCostPlan"] = plan[iid]["planQty"], plan[iid]["planUnitCost"]
        reason = str(l.get("overPlanReason") or "").strip()
        if len(reason) > MAX_REASON:
            raise _bad("第 %d 列的超出原因太長（上限 %d 字）" % (i, MAX_REASON))
        l["overPlanReason"] = reason
        l.pop("overPlanQty", None)
    over = overplan(kind, lines, data, rows, exclude_id=exclude_id, extra_ordered=case_extra_ordered(conn, quote_no, data, rows))
    over_idx = {o["index"]: o for o in over}
    warnings = []
    for i, l in enumerate(lines):
        if not isinstance(l, dict) or not str(l.get("itemId") or "").strip():
            continue
        o = over_idx.get(i)
        if o is None:
            l.pop("overPlanReason", None)
            continue
        l["overPlanQty"] = o["over"]
        warnings.append({"line": i + 1, "itemId": o["itemId"], "over": o["over"], "planQty": o["planQty"], "usedQty": o["usedQty"],
                         "reason": l["overPlanReason"]})
        if require_reason and kind == ORD and not l["overPlanReason"]:
            raise _bad("第 %d 列超出報價計畫量 %g（計畫 %g、已採購 %g），請填寫超出原因後再送審"
                       % (i + 1, o["over"], o["planQty"], o["usedQty"]))
    return lines, warnings


def check_from_pr(conn, quote_no, kind, data):
    """採購單的 `data.fromPr`（來源請購單單號）⇒ 必須是同案件、已核准的請購單；只有採購單可以帶；不合法 ⇒ 400。沒帶 ⇒ 不檢查。"""
    pr = (data or {}).get("fromPr")
    if pr in (None, ""):
        return
    if kind != ORD or not (quote_no or ""):
        raise _bad("只有掛在案件底下的採購單可以指定來源請購單")
    row = conn.execute("SELECT kind, status FROM case_extra_expenses WHERE doc_code=? AND quote_no=?", (str(pr), quote_no)).fetchone()
    if not row or row["kind"] != REQ:
        raise _bad("來源請購單 %s 不存在、不是請購單，或不屬於這個案件" % str(pr)[:30])
    if row["status"] != "已核准":
        raise _bad("來源請購單 %s 還沒有核准（目前：%s）" % (str(pr)[:30], row["status"]))


# ── 叫料連結（S4a；規格 docs/platform/plans/MATERIAL-ORDER-LINK-SPEC.md §2／§3）────────────────────────

NO_PO_TEXT = "該叫料未申請採購單"
STALE_PO_TEXT = "（原連結採購單已失效）"


def _po_lines(row):
    try:
        v = json.loads(row["lines_json"] or "[]")
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def _link_check(order, po_rows):
    """`poDocCode` 的有效性 ⇒ `(ok, reason)`；沒有 `poDocCode` ⇒ `(False, "no_link")`。"""
    code = str((order or {}).get("poDocCode") or "").strip()
    if not code:
        return False, "no_link"
    po = next((r for r in po_rows if (r["doc_code"] or "") == code), None)
    if po is None or (po["kind"] or "") != ORD:
        return False, "po_missing"
    if (po["status"] or "") not in COUNTED_EXTRA_STATUSES:
        return False, "po_inactive"
    pl = order.get("poLine")
    if pl not in (None, ""):
        lines = _po_lines(po)
        try:
            idx = int(pl)
        except (TypeError, ValueError):
            idx = 0
        if not 1 <= idx <= len(lines):
            return False, "bad_line"
        li = str((lines[idx - 1] or {}).get("itemId") or "").strip() if isinstance(lines[idx - 1], dict) else ""
        qi = str(order.get("quoteItemId") or "").strip()
        if li and qi and li != qi:
            return False, "item_mismatch"
    return True, "ok"


def material_link_status(order, po_rows, *, legacy=False) -> dict:
    """叫料列 ⇒ 與採購單的連結狀態（**唯一判定函式**：列表、審核頁、佇列、報表備註都讀它）。
    回 `{"state": "linked"|"none"|"exempt", "reason": 機器可讀原因, "stale": bool, "text": 顯示文字}`。
    - `exempt`：金額為 0 的叫料（客供料／庫存領用）；舊單（`legacy=True`，沒有疊加審核列）——裁示 1／2：不標註。
    - `linked`：`poDocCode` 指到同案件、類型為採購單、狀態屬待審核／簽核中／已核准的單，且 `poLine`（若有）在明細範圍內；
      採購單那一列有 `itemId` 而叫料有 `quoteItemId` ⇒ 兩者必須相同。
    - `none`：其餘（沒有 `poDocCode`；連到的單不存在／草稿／已駁回／已作廢／不是採購單；列序或品項對不上）；
      原本有連結但已失效 ⇒ `stale=True`（文字多註「原連結採購單已失效」）。
    `po_rows`：該案件 case_extra_expenses 的列（要有 `doc_code`、`kind`、`status`、`lines_json`）。純函式。"""
    order = order or {}
    if legacy:
        return {"state": "exempt", "reason": "legacy", "stale": False, "text": ""}
    try:
        total = float(order.get("totalPrice") or 0)
    except (TypeError, ValueError):
        total = 0.0
    if total == 0:
        return {"state": "exempt", "reason": "zero_amount", "stale": False, "text": ""}
    ok, reason = _link_check(order, po_rows)
    if ok:
        return {"state": "linked", "reason": "ok", "stale": False, "text": ""}
    if reason == "no_link":
        return {"state": "none", "reason": reason, "stale": False, "text": NO_PO_TEXT}
    return {"state": "none", "reason": reason, "stale": True, "text": NO_PO_TEXT + STALE_PO_TEXT}


def load_material_orders(conn, quote_no, quotation_data):
    """案件的叫料列（`caseRecord.materialOrders`）＋各列的審核狀態（疊加表；沒有列＝舊單 ''）⇒ `[(order, status)]`。"""
    from modules.case import material_approval as MA
    cr = (quotation_data or {}).get("caseRecord") if isinstance(quotation_data, dict) else None
    orders = (cr or {}).get("materialOrders") if isinstance(cr, dict) else None
    ap = MA.rows_for_case(conn, quote_no)
    out = []
    for o in orders if isinstance(orders, list) else []:
        if isinstance(o, dict):
            out.append((o, (ap.get(str(o.get("itemId"))) or {}).get("status", "")))
    return out


def material_ordered(orders_with_status, po_rows) -> dict:
    """`{報價品項 id: 已訂量}`（叫料的貢獻）：叫料列帶 `quoteItemId`、審核狀態不是草稿／已退回／已取消（舊單與已核准、待審核、簽核中都計），
    且**沒有有效連結採購單**（連結者與那張採購單是同一筆採購，已由採購單明細計入，只算一次）。"""
    from modules.case import material_approval as MA
    out = {}
    for o, status in orders_with_status:
        qid = str(o.get("quoteItemId") or "").strip()
        if not qid or MA.cost_state(status) == "excluded":
            continue
        if _link_check(o, po_rows)[0]:
            continue
        out[qid] = out.get(qid, 0.0) + _num(o.get("quantity"))
    return out
