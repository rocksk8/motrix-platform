# -*- coding: utf-8 -*-
"""「從採購單帶入」的涵蓋分組（34-M1 UI；唯讀）：一個報價品項一組（額外採購以採購單為單位各一組，N1），內容＝該品項**全部已核准**採購單行的涵蓋快照。

[單位] case:material_coverage_view    [層] L2（M01）    [穩定度] 新（第 34 班）
畫面（case-management-mlink.js）不做金額運算：數量／單位／單價／小計都由這裡（`material_coverage.coverage_snapshot`＝送審檢查用的同一個函式）給，
所以畫面帶入的內容必然通過 `material_submit_check` 的「涵蓋」檢查（`content_not_cover_snapshot`）。已有活的材料申請的品項標 `existing`（要追加走變更申請）。
金額看不到財務檢視者：不給單價／小計（畫面也就不能帶入）。只讀、不寫。"""
from modules.case import material_coverage as MC
from modules.case import purchase_items as PI


def groups(conn, quote_no, show_cost=True) -> list:
    data, rows = PI._case_state(conn, quote_no)
    plan = {p["itemId"]: p for p in PI.plan_items(data)}
    approved = [r for r in rows if (r["kind"] or "") == PI.ORD and (r["status"] or "") == "已核准"]
    qids, extras, summary = [], [], {}
    for r in approved:
        for i, l in enumerate(PI._po_lines(r), 1):
            if not isinstance(l, dict):
                continue
            li = str(l.get("itemId") or "").strip()
            summary[(r["doc_code"], i)] = str(l.get("summary") or "")
            if li:
                if li not in qids:
                    qids.append(li)
            elif r["doc_code"] not in extras:
                extras.append(r["doc_code"])
    pending = {}
    for l in PI.available_po_lines(conn, quote_no, show_cost=False):
        if l["status"] != "已核准":
            key = l["quoteItemId"] or ("po:" + l["poDocCode"])
            pending[key] = pending.get(key, 0) + 1
    out = []
    for qid in qids:
        out.append(_group(conn, quote_no, qid, "", plan, summary, pending.get(qid, 0), show_cost))
    for code in extras:
        out.append(_group(conn, quote_no, "", code, plan, summary, pending.get("po:" + code, 0), show_cost))
    return [g for g in out if g]


def _group(conn, quote_no, qid, code, plan, summary, pending_lines, show_cost):
    cov = MC.coverage_snapshot(conn, quote_no, qid, code)
    lines = cov["poSnapshot"]
    if not lines:
        return None
    first = lines[0]
    hit = MC.item_request_exists(conn, quote_no, qid, po_doc_code=code)
    if hit is None and not qid:                                                    # 額外採購：還沒送審的草稿尚無涵蓋快照，改看列上的採購單連結（同一張採購單不要再帶入第二次）
        hit = _draft_link_hit(conn, quote_no, code)
    p = plan.get(qid)
    g = {"key": ("item:" + qid) if qid else ("po:" + code), "quoteItemId": qid, "poDocCode": first["poDocCode"], "poLine": first["line"],
         "name": (p["description"] if p else "") or summary.get((first["poDocCode"], first["line"]), "") or (qid or code),
         "quantity": cov["quantity"], "unit": cov["unit"], "lineCount": len(lines), "docCodes": sorted({l["poDocCode"] for l in lines}),
         "pendingLines": pending_lines,
         "existing": ({"itemId": hit["itemId"], "docCode": hit["docCode"], "status": hit["status"]} if hit else None)}
    if show_cost:
        g.update(unitPrice=cov["unitPrice"], totalPrice=cov["totalPrice"])
    return g


def _draft_link_hit(conn, quote_no, po_doc_code):
    from modules.case import material_approval as MA
    data, _rows = PI._case_state(conn, quote_no)
    ap = MA.rows_for_case(conn, quote_no)
    for o, status in PI.load_material_orders(conn, quote_no, data):
        if status in MC.LIVE_STATUSES and not str(o.get("quoteItemId") or "").strip() and str(o.get("poDocCode") or "").strip() == po_doc_code:
            iid = str(o.get("itemId"))
            return {"itemId": iid, "docCode": (ap[iid]["doc_code"] if iid in ap else ""), "status": status}
    return None

