# -*- coding: utf-8 -*-
"""材料申請的「涵蓋範圍」與變更提案（33-M1 E4／33-M2；規格 docs/platform/plans/MATERIAL-FORCE-PO-AND-SHIPPING-SPEC.md §A.1／§B）。

一個報價品項最多一筆活的材料申請；它涵蓋該品項**所有已核准**採購單行（送審當下的快照 `poSnapshot`）。追加新採購單行＝對原申請提變更申請，
原已核准版本在變更核准前持續有效（N3）。本檔只組「內容」與「差異」，不碰簽核狀態機（d7：`case_material_changes`、原子套用）。
全部唯讀（不寫資料庫）。
"""
import json

from modules.case import purchase_items as PI

#: 占用品項的材料申請狀態（草稿、待審核、簽核中、已核准；已退回／已取消不占）。沒有審核列的舊單不占（不溯及既往，規格 §A.4）。
LIVE_STATUSES = ("草稿", "待審核", "簽核中", "已核准")
#: 變更申請可改動的實質欄位（提案與原版本逐欄比對）
CHANGE_KEYS = ("quantity", "unit", "unitPrice", "totalPrice", "poSnapshot", "notes")
_MONEY = ("unitPrice", "totalPrice")


def snapshot_lines(approval_json):
    """審核列 `approval_json` 裡的涵蓋快照 `poSnapshot`：變更申請核准後在 `snapshot.poSnapshot`（d7 套用時改寫），
    首次送審時由 `material_submit_check` 的結果存在 `linkSnapshot.poSnapshot`；前者優先。"""
    try:
        a = json.loads(approval_json or "{}") if not isinstance(approval_json, dict) else approval_json
    except (TypeError, ValueError):
        return []
    if not isinstance(a, dict):
        return []
    for k in ("snapshot", "linkSnapshot"):
        v = (a.get(k) or {}).get("poSnapshot") if isinstance(a.get(k), dict) else None
        if isinstance(v, list):
            return v
    return []


def _snap_line(po_code, idx, line):
    return {"poDocCode": po_code, "line": idx, "qty": PI._num(line.get("qty")), "unit": str(line.get("unit") or ""), "amount": PI._num(line.get("amount"))}


def approved_po_lines(conn, quote_no, quote_item_id="", po_doc_code=""):
    """已核准採購單行 ⇒ `[{poDocCode, line, qty, unit, amount}]`。
    `quote_item_id` 有值：該報價品項的行。空值＋`po_doc_code`：額外採購（N1）——該張採購單裡沒有品項的行。"""
    _data, rows = PI._case_state(conn, quote_no)
    out = []
    qid = str(quote_item_id or "").strip()
    for r in rows:
        if (r["kind"] or "") != PI.ORD or (r["status"] or "") != "已核准":
            continue
        code = r["doc_code"] or ""
        if not qid and code != po_doc_code:
            continue
        for i, l in enumerate(PI._po_lines(r), 1):
            if not isinstance(l, dict):
                continue
            li = str(l.get("itemId") or "").strip()
            if (qid and li == qid) or (not qid and not li):
                out.append(_snap_line(code, i, l))
    return out


def snapshot_content(lines, plan_qty=None, plan_unit=""):
    """涵蓋行 ⇒ 材料申請內容預設值（規格 §A.1）：金額＝行金額合計（唯讀）；數量＝行數量合計（單位一致時），單位不同＝品項報價量（可往下調）。"""
    units = {str(l["unit"]) for l in lines}
    amount = sum(l["amount"] for l in lines)
    if len(units) == 1:
        qty, unit = sum(l["qty"] for l in lines), next(iter(units))
    else:
        qty, unit = (plan_qty if plan_qty is not None else 0.0), plan_unit
    return {"poSnapshot": lines, "quantity": qty, "unit": unit, "totalPrice": amount, "unitPrice": (amount / qty) if qty else 0.0}


def coverage_snapshot(conn, quote_no, quote_item_id="", po_doc_code="", *, only_untaken=False, exclude_item_id=None):
    """送審當下的涵蓋快照與預設內容。品項已不在報價單 ⇒ 沒有計畫量（數量 0）。
    `only_untaken`：去掉已被其他活的材料申請占用的採購單行（D7 調整單：只涵蓋原申請沒有的行）。"""
    data, _rows = PI._case_state(conn, quote_no)
    plan = {p["itemId"]: p for p in PI.plan_items(data)}
    p = plan.get(str(quote_item_id or "").strip())
    lines = approved_po_lines(conn, quote_no, quote_item_id, po_doc_code)
    if only_untaken:
        taken = taken_lines(conn, quote_no, exclude_item_id=exclude_item_id)
        lines = [l for l in lines if _line_key(l) not in taken]
    return snapshot_content(lines, p["planQty"] if p else None, p["unit"] if p else "")


def adjust_check(conn, quote_no, quote_item_id, adjust_of):
    """D7 調整單（`adjustOf=<原 itemId>`）能不能建立 ⇒ `[{code, message}]`（空＝可以）：原申請必須存在、同品項、**已全額付款**；
    涵蓋範圍只能是**沒被占用**的已核准採購單行（空＝沒有可調整的新採購單行）。"""
    problems = []
    order, _row, _snap = current_version(conn, quote_no, adjust_of)
    if order is None:
        return [{"code": "adjust_target_missing", "message": "找不到要調整的原材料申請"}]
    if str(order.get("quoteItemId") or "").strip() != str(quote_item_id or "").strip():
        problems.append({"code": "adjust_item_mismatch", "message": "調整單必須與原材料申請同一個品項"})
    if not paid_in_full(order):
        problems.append({"code": "adjust_not_paid_in_full", "message": "原材料申請尚未全額付款，請走變更申請（調整單只用於已全額付款、金額不能修改的申請）"})
    if not coverage_snapshot(conn, quote_no, quote_item_id, only_untaken=True, exclude_item_id=None)["poSnapshot"]:
        problems.append({"code": "adjust_no_new_lines", "message": "這個品項沒有尚未被材料申請涵蓋的已核准採購單行"})
    return problems


def paid_in_full(order):
    """材料申請已全額付款（`paidAmount` 是付款明細的唯一投影，見 material_payment.sync_order_paid）：付款 > 0 且 ≥ 小計。"""
    paid, total = PI._num((order or {}).get("paidAmount")), PI._num((order or {}).get("totalPrice"))
    return paid > 0 and paid >= total - 1e-9


def taken_lines(conn, quote_no, *, exclude_item_id=None):
    """被其他**活的**材料申請占用的採購單行 `{(poDocCode, line)}`：涵蓋快照＋舊的單行連結（`poDocCode`／`poLine`）。"""
    from modules.case import material_approval as MA
    data, _rows = PI._case_state(conn, quote_no)
    ap = MA.rows_for_case(conn, quote_no)
    out = set()
    for o, status in PI.load_material_orders(conn, quote_no, data):
        iid = str(o.get("itemId"))
        if iid == str(exclude_item_id or "") or status not in LIVE_STATUSES:
            continue
        for l in (snapshot_lines(ap[iid]["approval_json"]) if iid in ap else []):
            out.add(_line_key(l))
        if str(o.get("poDocCode") or "").strip() and o.get("poLine") not in (None, ""):
            try:
                out.add((str(o["poDocCode"]).strip(), int(o["poLine"])))
            except (TypeError, ValueError):
                pass
    return out


def item_request_exists(conn, quote_no, quote_item_id, *, exclude_item_id=None, po_doc_code="", adjust_of=""):
    """同品項（或同一張額外採購單）已有活的材料申請 ⇒ `{"itemId", "docCode", "status"}`，沒有回 None（`item_request_exists`；取代 S4 的 po_line_taken）。
    `adjust_of`（D7 調整單）：原申請**已全額付款**時，原申請不算占用（調整單另開一筆、不走變更申請）；原申請沒有全額付款 ⇒ 照常算占用（回原申請）。"""
    from modules.case import material_approval as MA
    data, _rows = PI._case_state(conn, quote_no)
    qid = str(quote_item_id or "").strip()
    ap = MA.rows_for_case(conn, quote_no)
    for o, status in PI.load_material_orders(conn, quote_no, data):
        iid = str(o.get("itemId"))
        if iid == str(exclude_item_id or "") or status not in LIVE_STATUSES:
            continue
        if adjust_of and iid == str(adjust_of) and paid_in_full(o):
            continue
        snap = snapshot_lines(ap[iid]["approval_json"]) if iid in ap else None
        if qid:
            if str(o.get("quoteItemId") or "").strip() == qid:
                return {"itemId": iid, "docCode": ap[iid]["doc_code"], "status": status}
        elif not str(o.get("quoteItemId") or "").strip() and po_doc_code and any((s or {}).get("poDocCode") == po_doc_code for s in snap or []):
            return {"itemId": iid, "docCode": ap[iid]["doc_code"], "status": status}
    return None


def current_version(conn, quote_no, item_id):
    """材料申請目前生效的內容（`caseRecord.materialOrders[該列]`）與它的涵蓋快照（審核列 `approval_json.snapshot.poSnapshot`）。"""
    from modules.case import material_approval as MA
    data, _rows = PI._case_state(conn, quote_no)
    order = next((o for o, _st in PI.load_material_orders(conn, quote_no, data) if str(o.get("itemId")) == str(item_id)), None)
    row = MA.get(conn, quote_no, item_id)
    return order, row, (snapshot_lines(row["approval_json"]) if row is not None else [])


def _view(order, snap):
    return {"quantity": PI._num(order.get("quantity")), "unit": str(order.get("unit") or ""), "unitPrice": PI._num(order.get("unitPrice")),
            "totalPrice": PI._num(order.get("totalPrice")), "poSnapshot": snap, "notes": str(order.get("notes") or "")}


def _quantity_limit(cov):
    """涵蓋內容的數量上限：`snapshot_content` 的預設數量（單位一致＝行數量合計；單位不同＝品項報價量）。沒有涵蓋行 ⇒ None（另有 no_coverage）。"""
    return cov["quantity"] if cov.get("poSnapshot") else None


def _line_key(l):
    return (l.get("poDocCode"), l.get("line"))


def change_proposal(conn, quote_no, item_id, proposed=None):
    """材料申請變更提案（33-M2；與 d7 的 `case_material_changes` 對齊）⇒
    `{itemId, before, after, diff:[{field, old, new, money}], uncoveredLines:[…], problems:[{code, message}]}`。
    `before`＝目前生效版本；`after`＝**目前已核准採購單行組成的新快照**（預設內容）再疊上 `proposed` 的欄位（數量可往下調、備註）。
    只算內容與差異，不寫；`problems` 空才可建立變更。數量／涵蓋不得低於已出貨＋占用量由 d7 呼叫出貨提供者檢查（提供者不存在就略過）。"""
    order, row, snap = current_version(conn, quote_no, item_id)
    problems = []
    if order is None or row is None:
        return {"itemId": str(item_id), "before": {}, "after": {}, "diff": [], "uncoveredLines": [], "problems": [{"code": "not_found", "message": "找不到這筆材料申請（舊單沒有變更申請，直接修改即可）"}]}
    from modules.case import material_approval as MA
    if not MA.po_required_for(row):                                       # grandfather／規則上線前的單：維持 31-C「核准後改＝回草稿」，不走變更申請（d7 設計 §5）
        problems.append({"code": "use_direct_edit", "message": "這筆材料申請是規則上線前建立（沒有採購單涵蓋快照），請直接修改後重新送審，不走變更申請"})
    if row["status"] != "已核准":
        problems.append({"code": "not_approved", "message": "只有已核准的材料申請可以提變更申請（草稿或已退回的直接修改後送審）"})
    qid = str(order.get("quoteItemId") or "").strip()
    po_code = next((s["poDocCode"] for s in snap if s.get("poDocCode")), "") if not qid else ""
    fresh = coverage_snapshot(conn, quote_no, qid, po_code)
    before = _view(order, snap)
    if not fresh["poSnapshot"]:
        problems.append({"code": "no_coverage", "message": "這個品項目前沒有已核准的採購單行，無法變更"})
    after = {k: fresh[k] for k in ("quantity", "unit", "unitPrice", "totalPrice", "poSnapshot")}
    after["notes"] = before["notes"]
    for k, v in (proposed or {}).items():
        if k in ("quantity", "notes", "unit"):
            after[k] = v
        else:                                                                 # 金額／單價／涵蓋行的來源是採購單，不能在提案裡手改
            problems.append({"code": "unknown_field", "message": "不能變更欄位 %s（金額與涵蓋範圍由已核准的採購單決定）" % k})
    try:
        after["quantity"] = float(after["quantity"])
    except (TypeError, ValueError):
        problems.append({"code": "bad_quantity", "message": "數量必須是數字"})
    else:
        if after["quantity"] <= 0:
            problems.append({"code": "bad_quantity", "message": "數量必須大於 0"})
        if "quantity" in (proposed or {}):                                    # 數量改了：單價＝金額 ÷ 數量（金額來源在採購單，不讓人手改）
            after["unitPrice"] = round(after["totalPrice"] / after["quantity"], 4) if after["quantity"] else 0.0
    paid = PI._num(order.get("paidAmount"))                               # D7 鎖定：已全額付款不可改金額（走調整單）；付款後新小計不得低於已付
    if paid_in_full(order) and any(abs(PI._num(before[k]) - PI._num(after[k])) > 1e-9 for k in ("quantity", "unitPrice", "totalPrice")):
        problems.append({"code": "paid_in_full", "message": "已全額付款，金額與數量不能修改；要調整請另開一筆材料申請（調整單）"})
    elif paid > 0 and PI._num(after["totalPrice"]) < paid - 1e-9:
        problems.append({"code": "below_paid", "message": "變更後小計低於已付金額 %g" % paid})
    limit = _quantity_limit(fresh)                    # 數量只能往下調（規格 §A.1）：不得超過涵蓋行數量合計（單位不同＝品項報價量）；否則一張變更就能把可出貨量灌大（da）
    if limit is not None and after.get("quantity") is not None and isinstance(after["quantity"], float) and after["quantity"] > limit + 1e-9:
        problems.append({"code": "quantity_exceeds_coverage", "message": "數量 %g 超過已核准採購單行涵蓋的數量 %g（數量只能往下調；要增加請先申請採購單）" % (after["quantity"], limit)})
    dropped = [l for l in snap if _line_key(l) not in {_line_key(x) for x in fresh["poSnapshot"]}]
    if dropped:
        problems.append({"code": "coverage_shrinks", "message": "原本涵蓋的採購單行不再是已核准（%s），請先處理採購單" % "、".join("%s 第 %s 列" % _line_key(l) for l in dropped)})
    uncovered = [l for l in fresh["poSnapshot"] if _line_key(l) not in {_line_key(x) for x in snap}]
    diff = []
    for k in CHANGE_KEYS:
        if before[k] != after[k]:
            diff.append({"field": k, "old": before[k], "new": after[k], "money": k in _MONEY})
    if not diff and not problems:
        problems.append({"code": "no_change", "message": "沒有任何變更（目前已核准的採購單行都已涵蓋，數量與備註也相同）"})
    return {"itemId": str(item_id), "before": before, "after": after, "diff": diff, "uncoveredLines": uncovered, "problems": problems}
