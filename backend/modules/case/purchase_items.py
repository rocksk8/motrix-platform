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
#: 採購單明細帶入請購單的連結鍵（第 44 班）：`prDocCode`＝來源請購單單號、`prLine`＝請購單明細列序（1 起算）、`prQty`＝伺服器寫入的請購量快照
PR_KEYS = ("prDocCode", "prLine", "prQty")
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
    lines = _check_pr_links(conn, quote_no, kind, lines, exclude_id=exclude_id)           # 第 44 班：採購單明細連請購單（沒有 prDocCode ⇒ 原樣）
    if kind == REQ and exclude_id is not None:
        guard_claimed_pr_edit(conn, quote_no, exclude_id, lines)                           # 已被採購單引用的請購單明細不能被改掉
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


def _pr_rows(conn, quote_no):
    return conn.execute("SELECT id, kind, status, lines_json, doc_code FROM case_extra_expenses WHERE quote_no=? AND kind IN (?,?)",
                        (quote_no, REQ, ORD)).fetchall()


def pr_claims(rows, *, exclude_id=None) -> dict:
    """已被採購單認領的請購單明細量 ⇒ `{(請購單單號, 列序): 數量}`；只計 `COUNTED_EXTRA_STATUSES` 的採購單（草稿不佔量；作廢、駁回釋放）。"""
    out = {}
    for r in rows:
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if (r["kind"] or "") != ORD or (r["status"] or "") not in COUNTED_EXTRA_STATUSES:
            continue
        for l in _po_lines(r):
            if not isinstance(l, dict) or not str(l.get("prDocCode") or "").strip():
                continue
            try:
                n = int(l.get("prLine"))
            except (TypeError, ValueError):
                continue
            key = (str(l["prDocCode"]).strip(), n)
            out[key] = out.get(key, 0.0) + _num(l.get("qty"))
    return out


def check_pr_claims(conn, quote_no, kind, lines, *, exclude_id=None):
    """採購單明細（帶 `prDocCode`）對請購單明細的累計認領檢查（不改明細）；不合法 ⇒ HTTPException(400)。
    - 只有掛在案件底下的採購單可以連請購單；來源必須是**同案件、已核准**的請購單；`prLine` 必須在該請購單明細範圍內；`qty` 必須是大於 0 的數字。
    - 累計：其他計入狀態的採購單已認領量＋本單同一請購明細各列量 ≤ 請購明細數量（部分採購可以，分次採購累計不超過）。
    沒有任何 `prDocCode` ⇒ 什麼都不做。呼叫端在寫鎖內呼叫（兩人同時認領同一列不會一起通過）。"""
    linked = [(i, l) for i, l in enumerate(lines or []) if isinstance(l, dict) and str(l.get("prDocCode") or "").strip()]
    if not linked:
        return
    if kind != ORD or not (quote_no or ""):
        raise _bad("只有掛在案件底下的採購單，明細才能連到請購單")
    rows = _pr_rows(conn, quote_no)
    prs = {(r["doc_code"] or ""): r for r in rows if (r["kind"] or "") == REQ}
    claimed = pr_claims(rows, exclude_id=exclude_id)
    run = {}
    for i, l in linked:
        code = str(l["prDocCode"]).strip()
        pr = prs.get(code)
        if pr is None:
            raise _bad("第 %d 列連到的請購單 %s 不存在或不屬於這個案件" % (i + 1, code[:30]))
        if (pr["status"] or "") != "已核准":
            raise _bad("第 %d 列連到的請購單 %s 還沒有核准（目前：%s）" % (i + 1, code[:30], pr["status"]))
        try:
            n = int(l.get("prLine"))
        except (TypeError, ValueError):
            n = 0
        plines = _po_lines(pr)
        if not 1 <= n <= len(plines) or not isinstance(plines[n - 1], dict):
            raise _bad("第 %d 列連到的請購單 %s 明細列序不正確" % (i + 1, code[:30]))
        qty = l.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) or not qty > 0:
            raise _bad("第 %d 列連到請購單，數量必須是大於 0 的數字" % (i + 1))
        cap = _num(plines[n - 1].get("qty"))
        key = (code, n)
        run[key] = run.get(key, 0.0) + float(qty)
        if claimed.get(key, 0.0) + run[key] > cap + 1e-9:
            raise _bad("第 %d 列：請購單 %s 第 %d 項請購 %g、其他採購單已採購 %g、本單 %g，超過請購量（剩餘 %g）"
                       % (i + 1, code[:30], n, cap, claimed.get(key, 0.0), run[key], max(cap - claimed.get(key, 0.0), 0.0)))


def _check_pr_links(conn, quote_no, kind, lines, *, exclude_id=None):
    """寫入前處理明細的請購單連結 ⇒ 新的明細列。沒有任何 `prDocCode` ⇒ 只拿掉殘留的保留鍵、其餘原樣（與沒有這個功能時相同）。
    請購量快照 `prQty` 由伺服器依請購單寫入（前端送的不採用）。"""
    has = any(isinstance(l, dict) and str(l.get("prDocCode") or "").strip() for l in lines)
    for l in lines:
        if isinstance(l, dict) and not str(l.get("prDocCode") or "").strip():
            for k in PR_KEYS:
                l.pop(k, None)
    if not has:
        return lines
    check_pr_claims(conn, quote_no, kind, lines, exclude_id=exclude_id)
    prs = {(r["doc_code"] or ""): r for r in _pr_rows(conn, quote_no) if (r["kind"] or "") == REQ}
    for l in lines:
        if isinstance(l, dict) and str(l.get("prDocCode") or "").strip():
            l["prDocCode"] = str(l["prDocCode"]).strip()
            l["prLine"] = int(l["prLine"])
            l["prQty"] = _num(_po_lines(prs[l["prDocCode"]])[l["prLine"] - 1].get("qty"))
    return lines


def stamp_from_pr(data, lines):
    """採購單 `data.fromPr`（來源請購單單號清單）與 `data.pr_no`（顯示用文字）依明細的 `prDocCode` 同步（就地改 data）。
    明細有連請購單 ⇒ 兩者都由明細決定；明細沒有連請購單 ⇒ 不動（`pr_no` 仍可手填）。修正「定義叫 pr_no、驗證卻讀 fromPr」的名稱不一致。"""
    codes = []
    for l in lines or []:
        c = str(l.get("prDocCode") or "").strip() if isinstance(l, dict) else ""
        if c and c not in codes:
            codes.append(c)
    if isinstance(data, dict):
        if codes:
            data["fromPr"] = codes
            data["pr_no"] = "、".join(codes)
        elif isinstance(data.get("fromPr"), list):
            data.pop("fromPr", None)
    return data


def guard_claimed_pr_edit(conn, quote_no, exp_id, new_lines):
    """請購單（已核准後的變更申請）：被採購單認領的明細不能被刪除、改成別的品名、或把數量改到低於已認領量 ⇒ 409。
    以列序認領，所以已認領的列必須留在原位。沒有被認領 ⇒ 什麼都不做。"""
    from fastapi import HTTPException
    rows = _pr_rows(conn, quote_no)
    me = next((r for r in rows if r["id"] == exp_id and (r["kind"] or "") == REQ), None)
    if me is None:
        return
    code = me["doc_code"] or ""
    claimed = {n: q for (c, n), q in pr_claims(rows).items() if c == code}
    if not claimed:
        return
    old = _po_lines(me)
    nl_all = new_lines or []
    for n, q in sorted(claimed.items()):
        nl = nl_all[n - 1] if 0 < n <= len(nl_all) and isinstance(nl_all[n - 1], dict) else None
        ol = old[n - 1] if 0 < n <= len(old) and isinstance(old[n - 1], dict) else {}
        if nl is None or str(nl.get("summary") or "") != str(ol.get("summary") or "") or _num(nl.get("qty")) + 1e-9 < q:
            raise HTTPException(409, "請購單 %s 第 %d 項已被採購單引用（已採購 %g），不能刪除、改品名或把數量改到低於已採購量；請先處理那張採購單" % (code, n, q))


def claimed_by(conn, quote_no, doc_code) -> list:
    """引用這張請購單的採購單（計入狀態）⇒ `[{docCode, status}]`；供作廢前檢查與顯示。"""
    out = []
    for r in _pr_rows(conn, quote_no):
        if (r["kind"] or "") != ORD or (r["status"] or "") not in COUNTED_EXTRA_STATUSES:
            continue
        if any(isinstance(l, dict) and str(l.get("prDocCode") or "").strip() == doc_code for l in _po_lines(r)):
            out.append({"docCode": r["doc_code"] or "", "status": r["status"]})
    return out


def pr_lines_view(conn, quote_no, *, viewer_ok, show_cost) -> list:
    """「從請購單帶入」挑選器的資料：同案件已核准的請購單 ⇒ `[{docCode, title, reqDate, lines:[{prLine, summary, category, unit, qty, claimed, remaining, itemId, unitCost?}]}]`。
    `viewer_ok(row)`＝這位使用者看不看得到這張請購單的明細（被遮蔽的不列）；`show_cost`＝看得到財務金額才回 `unitCost`（沒有 ⇒ 不帶價格）。只有數量與單價，不回總額以外的金額。"""
    rows = conn.execute("SELECT * FROM case_extra_expenses WHERE quote_no=? AND kind=? AND status='已核准' ORDER BY id", (quote_no, REQ)).fetchall()
    claimed = pr_claims(_pr_rows(conn, quote_no))
    out = []
    for r in rows:
        if not viewer_ok(r):
            continue
        code = r["doc_code"] or ""
        lines = []
        for n, l in enumerate(_po_lines(r), 1):
            if not isinstance(l, dict):
                continue
            qty = _num(l.get("qty"))
            got = claimed.get((code, n), 0.0)
            e = {"prLine": n, "summary": str(l.get("summary") or ""), "category": str(l.get("category") or ""), "unit": str(l.get("unit") or ""),
                 "qty": qty, "claimed": got, "remaining": max(qty - got, 0.0), "itemId": str(l.get("itemId") or "").strip()}
            if show_cost:
                e["unitCost"] = _num(l.get("unitCost"))
            lines.append(e)
        out.append({"docCode": code, "title": r["description"] or "", "reqDate": r["expense_date"] or "", "lines": lines})
    return out


def check_from_pr(conn, quote_no, kind, data):
    """採購單的 `data.fromPr`（來源請購單單號）⇒ 必須是同案件、已核准的請購單；只有採購單可以帶；不合法 ⇒ 400。沒帶 ⇒ 不檢查。"""
    fp = (data or {}).get("fromPr")
    if fp in (None, "", []):
        return
    if kind != ORD or not (quote_no or ""):
        raise _bad("只有掛在案件底下的採購單可以指定來源請購單")
    if not isinstance(fp, (str, list)) or (isinstance(fp, list) and (len(fp) > 50 or not all(isinstance(x, str) for x in fp))):
        raise _bad("來源請購單格式不正確")
    for pr in ([fp] if isinstance(fp, str) else fp):          # 第 44 班：單一單號（舊）或單號清單（可混合多張請購單）
        row = conn.execute("SELECT kind, status FROM case_extra_expenses WHERE doc_code=? AND quote_no=?", (str(pr), quote_no)).fetchone()
        if not row or row["kind"] != REQ:
            raise _bad("來源請購單 %s 不存在、不是請購單，或不屬於這個案件" % str(pr)[:30])
        if row["status"] != "已核准":
            raise _bad("來源請購單 %s 還沒有核准（目前：%s）" % (str(pr)[:30], row["status"]))


# ── 叫料連結（S4a；規格 docs/platform/plans/MATERIAL-ORDER-LINK-SPEC.md §2／§3）────────────────────────

NO_PO_TEXT = "該材料申請未申請採購單"
STALE_PO_TEXT = "（原連結採購單已失效）"


def _po_lines(row):
    try:
        v = json.loads(row["lines_json"] or "[]")
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def has_paid_history(order) -> bool:
    """材料申請自己已有付款紀錄（舊「登記已付」或 31-C 匯款明細的投影：已付金額 > 0／狀態不是 pending）。"""
    o = order or {}
    return _num(o.get("paidAmount")) > 0 or str(o.get("paidStatus") or "pending") != "pending"


def _link_check(order, po_rows):
    """`poDocCode` 的有效性 ⇒ `(ok, reason)`；沒有 `poDocCode` ⇒ `(False, "no_link")`。
    已有付款紀錄的材料申請**不視為連結**（`has_payment`）：它付出去的錢已經記在材料申請上（現金口徑看得到），
    若事後再連到採購單就會被「連到採購單＝金額由採購單負責」略過、已付的錢從現金報表消失（c7 預審）。"""
    code = str((order or {}).get("poDocCode") or "").strip()
    if not code:
        return False, "no_link"
    if has_paid_history(order):
        return False, "has_payment"
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


def material_submit_check(conn, quote_no, order, *, exclude_item_id=None, po_required=False) -> dict:
    """叫料單**送審**時的連結檢查（接縫：由 31-C 的送審路徑呼叫；規格 §4）⇒ `{"problems": [{code, message}], "snapshot": {...}}`。
    - `quoteItemId` 必須是報價單現有品項（`bad_quote_item`）。
    - `poDocCode` 必須是有效連結（`bad_link`，訊息帶原因）。
    - 累計上限（與採購單同一口徑，`usage`＋叫料貢獻）：連報價品項且**沒有有效採購單連結**時，已訂量＋本單數量 ＞ 計畫量 ⇒ 超出；
      超出必須有 `overPlanReason`（`over_plan_reason_required`，Q2）。連到有效採購單者與採購單是同一筆採購，採購單那邊已驗，這裡不重複。
    - `snapshot`：送審當下的判定結果（`linkState`／`linkReason`／`overPlanQty`／`overPlanReason`），寫進 `approval_json` 讓簽核人看到的是送審當下的狀態。
    純讀、不寫。`exclude_item_id`＝正在送審的叫料列（不把自己算進已用量）。"""
    from modules.case import material_approval as MA
    problems = []
    order = order or {}
    data, rows = _case_state(conn, quote_no)
    po_rows = [r for r in rows if (r["kind"] or "") == ORD]
    plan = {p["itemId"]: p for p in plan_items(data)}
    qid = str(order.get("quoteItemId") or "").strip()
    if qid and qid not in plan:
        problems.append({"code": "bad_quote_item", "message": "材料申請連到的品項不在這張報價單內（可能已被刪除），請重新選擇"})
    link_ok, link_reason = _link_check(order, po_rows)
    if po_required:                                                                         # 33-M1（E1／E2）：必須連到「已核准」的採購單（待審核／簽核中不算）；用字照 MATERIAL-REQUEST-WORDING
        code = str(order.get("poDocCode") or "").strip()
        po = next((r for r in po_rows if (r["doc_code"] or "") == code), None) if code else None
        if not code:
            problems.append({"code": "po_required", "message": "需先申請請購單，再申請採購單；採購單通過後，才能對應這筆材料申請。"})
        elif po is None or (po["status"] or "") not in ("草稿", "待審核", "簽核中", "已核准"):
            problems.append({"code": "po_required", "message": "對應的採購單已退回（或作廢），請重新申請採購單。"})
        elif (po["status"] or "") != "已核准":
            problems.append({"code": "po_required", "message": "採購單尚未通過，通過後才能對應這筆材料申請。"})
        elif not link_ok and link_reason != "has_payment":
            problems.append({"code": "po_required", "message": "材料申請連到的採購單無效（%s）：必須是同案件、已核准的採購單" % link_reason})
    if str(order.get("poDocCode") or "").strip() and not link_ok and not (po_required and any(p["code"] == "po_required" for p in problems)):
        problems.append({"code": "bad_link", "message": ("這筆材料申請已有付款紀錄，不可對應採購單" if link_reason == "has_payment"
                                                         else "材料申請連到的採購單無效（%s）：必須是同案件、待審核／簽核中／已核准的採購單" % link_reason)})
    over, reason = 0.0, str(order.get("overPlanReason") or "").strip()
    others = [(o, st) for o, st in load_material_orders(conn, quote_no, data) if str(o.get("itemId")) != str(exclude_item_id or order.get("itemId"))]
    if link_ok and order.get("poLine") not in (None, ""):                                  # 一個採購單行只能對應一筆「活的」材料申請（草稿／已退回／已取消不占）
        key = (str(order.get("poDocCode")).strip(), int(order.get("poLine")))
        for o, st in others:
            if MA.cost_state(st) != "excluded" and _link_check(o, po_rows)[0] and o.get("poLine") not in (None, "")                     and (str(o.get("poDocCode")).strip(), int(o.get("poLine"))) == key:
                problems.append({"code": "po_line_taken", "message": "採購單 %s 第 %d 列已對應另一筆材料申請（%s）" % (key[0], key[1], o.get("itemName") or o.get("itemId"))})
                break
    if qid in plan and not link_ok:
        used = usage(rows, extra_ordered=material_ordered(others, po_rows)).get(qid, {"orderedQty": 0.0})["orderedQty"]
        over = max(used + _num(order.get("quantity")) - plan[qid]["planQty"], 0.0)
        if over > 1e-9 and not reason:
            problems.append({"code": "over_plan_reason_required",
                             "message": "材料申請超出報價計畫量 %g（計畫 %g、已訂 %g），請填寫超出原因後再送審" % (over, plan[qid]["planQty"], used)})
    state = material_link_status(order, po_rows)
    snap = {"linkState": state["state"], "linkReason": state["reason"], "overPlanQty": over if over > 1e-9 else 0,
            "overPlanReason": reason if over > 1e-9 else ""}
    if po_required:                                                                         # 33-M1 E4／34-M2：一品項一筆＋涵蓋快照（送審當下該品項所有已核准採購單行）；追加走變更申請，原申請已全額付款者走調整單（adjustOf）
        from modules.case import material_coverage as MC
        adjust_of = str(order.get("adjustOf") or "").strip()
        item_id = str(exclude_item_id or order.get("itemId") or "")
        po_code = str(order.get("poDocCode") or "").strip() if not qid else ""
        if adjust_of:
            problems.extend(MC.adjust_check(conn, quote_no, qid, adjust_of))
        else:
            hit = MC.item_request_exists(conn, quote_no, qid, exclude_item_id=item_id, po_doc_code=po_code)
            if hit:
                problems.append({"code": "item_request_exists", "message": "這個品項已經有一筆材料申請（單號 %s），要追加請走變更申請。" % (hit["docCode"] or hit["itemId"])})
        cov = MC.coverage_snapshot(conn, quote_no, qid, po_code, only_untaken=bool(adjust_of), exclude_item_id=item_id)
        if not cov["poSnapshot"] and not any(p["code"] in ("po_required", "adjust_no_new_lines") for p in problems):
            problems.append({"code": "no_coverage", "message": "這個品項目前沒有可涵蓋的已核准採購單行，請先申請採購單。"})
        if cov["poSnapshot"]:                                                                # N2：申請涵蓋該品項**所有**已核准採購單行——金額＝行金額合計、數量只能往下調；否則申請量小於涵蓋量（可出貨量失真）
            if abs(_num(order.get("totalPrice")) - cov["totalPrice"]) > 0.5 or _num(order.get("quantity")) > cov["quantity"] + 1e-9:
                problems.append({"code": "content_not_cover_snapshot",
                                 "message": "材料申請的內容要涵蓋該品項全部已核准的採購單行（%d 行：數量 %g、小計 %g），目前是數量 %g、小計 %g；請以涵蓋全部採購單行的內容送審（數量可往下調，金額不可改）。"
                                            % (len(cov["poSnapshot"]), cov["quantity"], cov["totalPrice"], _num(order.get("quantity")), _num(order.get("totalPrice")))})
        snap["poSnapshot"] = cov["poSnapshot"]
        if adjust_of:
            snap["adjustOf"] = adjust_of
    return {"problems": problems, "snapshot": snap}


def link_validator(conn, quote_no, order):
    """`material_guard.LINK_VALIDATOR` 的實作（儲存時的連結檢查；送審時另有 `material_submit_check`）⇒ 無效時回訊息，有效回 None。
    只驗「有填的連結鍵」：`quoteItemId` 要在報價單品項內；`poDocCode`／`poLine` 要是有效採購單連結；`poLine` 必須是正整數。"""
    order = order or {}
    data, rows = _case_state(conn, quote_no)
    qid = str(order.get("quoteItemId") or "").strip()
    if qid and qid not in {p["itemId"] for p in plan_items(data)}:
        return "材料申請連到的品項不在這張報價單內，請重新選擇"
    pl = order.get("poLine")
    if pl not in (None, ""):
        try:
            ok = int(pl) >= 1 and float(pl) == int(pl)
        except (TypeError, ValueError):
            ok = False
        if not ok:
            return "採購單列序必須是正整數"
    if str(order.get("poDocCode") or "").strip():
        ok, reason = _link_check(order, [r for r in rows if (r["kind"] or "") == ORD])
        if not ok and reason != "has_payment":      # 已有付款紀錄＝金額歸屬規則（不是連結無效）；「新增連結」已在 PATCH 擋下，這裡不再擋既有連結的存回
            return "連到的採購單無效（%s）：必須是同案件、待審核／簽核中／已核准的採購單" % reason
    elif pl not in (None, ""):
        return "填了採購單列序就必須指定採購單"
    return None


def queue_tags(conn, quote_no, order, cache=None) -> list:
    """簽核佇列卡片的小標註（L1 `tags[]`；接縫：材料申請的佇列提供者呼叫）⇒ 「未申請採購單」才有一個 warn 標註，其餘 []。
    正在簽核的單一定有審核列（非舊單），所以 `legacy=False`；$0 仍免標。"""
    if cache is not None and quote_no in cache:                                  # 佇列一次呼叫內同案件只查一次（紅點熱路徑，c7 預審）
        po_rows = cache[quote_no]
    else:
        po_rows = [r for r in _case_state(conn, quote_no)[1] if (r["kind"] or "") == ORD]
        if cache is not None:
            cache[quote_no] = po_rows
    st = material_link_status(order, po_rows, legacy=False)
    return [{"text": st["text"], "tone": "warn"}] if st["state"] == "none" else []


def material_detail_fields(order, po_rows, *, snapshot=None, legacy=False) -> list:
    """核准詳情（`approval.detail` 的 `fields[]`）要追加的兩欄：「採購單連結」「超出計畫」（接縫：d7 的 material_approvals.detail 呼叫）。"""
    st = material_link_status(order, po_rows, legacy=legacy)
    link = "已連採購單 %s" % order.get("poDocCode") if st["state"] == "linked" else (st["text"] or "不適用")
    over = (snapshot or {}).get("overPlanQty") or 0
    return [{"label": "採購單連結", "value": link},
            {"label": "超出計畫", "value": ("超出 %g（%s）" % (over, (snapshot or {}).get("overPlanReason") or "未填原因")) if over else "—"}]


def available_po_lines(conn, quote_no, *, show_cost=True) -> list:
    """「從採購單帶入」清單：該案件待審核／簽核中／已核准的採購單明細列，**尚未被有效連結的叫料用掉**者。
    `[{poDocCode, poLine, summary, qty, unit, vendor, quoteItemId, status, unitCost?, amount?}]`；金額看不到財務檢視者不給。"""
    data, rows = _case_state(conn, quote_no)
    po_rows = [r for r in rows if (r["kind"] or "") == ORD and (r["status"] or "") in COUNTED_EXTRA_STATUSES]
    taken = set()
    for o, st in load_material_orders(conn, quote_no, data):
        from modules.case import material_approval as MA
        if MA.cost_state(st) == "excluded":
            continue
        if _link_check(o, po_rows)[0] and o.get("poLine") not in (None, ""):
            try:
                taken.add((str(o["poDocCode"]).strip(), int(o["poLine"])))
            except (TypeError, ValueError):
                pass
    vendors = {r["doc_code"]: r["vendor"] for r in conn.execute("SELECT doc_code, data_json AS vendor FROM case_extra_expenses WHERE quote_no=? AND kind=?", (quote_no, ORD))}
    out = []
    for r in po_rows:
        try:
            vendor = (json.loads(vendors.get(r["doc_code"]) or "{}") or {}).get("vendor") or ""
        except (TypeError, ValueError):
            vendor = ""
        for i, l in enumerate(_po_lines(r), 1):
            if not isinstance(l, dict) or (r["doc_code"], i) in taken:
                continue
            item = {"poDocCode": r["doc_code"], "poLine": i, "summary": str(l.get("summary") or ""), "qty": _num(l.get("qty")),
                    "unit": str(l.get("unit") or ""), "vendor": vendor, "quoteItemId": str(l.get("itemId") or ""), "status": r["status"]}
            if show_cost:
                item.update(unitCost=_num(l.get("unitCost")), amount=_num(l.get("amount")))
            out.append(item)
    return out
