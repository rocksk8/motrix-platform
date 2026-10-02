# -*- coding: utf-8 -*-
"""完結精算「實際成本」的單一來源（33-A2；規格 docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md）。

純組合：只用 `recognition.material_money_rows`（材料申請）與 `recognition.extra_entries`（採購單連品項的列＋額外支出）——
營運報表、總帳 E11／E12、完結精算讀的是**同一批列**，這裡沒有任何自己的金額規則，三處不會漂。
沖銷規則 A（使用者裁示）：品項有實際採購（已核准採購單連到該品項、或材料申請歸到該品項）⇒ 實際**取代**該品項估計；沒採購 ⇒ 用估計。
口徑：權責、含待審核（標 pending）；材料申請只含已成案／已結案案件（與報表同一條件）。派發、匯款手續費、自訂模組支出不在這裡（第 34 班）。
"""
import json

from helpers.legal_params import round_half_up
from modules.case import purchase_items as PI
from modules.case import recognition as R

ESTIMATE_RATE = 1.05            # 精算頁預設實際成本＝報價成本 ×1.05（5%「非扣抵進項稅」假設；與 settlement.html 的預設同一條）
#: 關掉「採用」時採購金額怎麼算（USER-DECISIONS D8）：ignore＝手填取代、採購不另加（建議）；add＝舊行為（採購另加，會與估計重複）。
UNADOPTED_IGNORE, UNADOPTED_ADD = "ignore", "add"


def estimate_amount(qty, cost) -> int:
    return round_half_up((qty or 0) * (cost or 0), ESTIMATE_RATE)


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_offsets(raw) -> list:
    """精算存的 `offsets`（容錯：壞列略過）⇒ `[{kind: material|extra, ref: str, itemId: str}]`；同一 (kind, ref) 只留第一個。"""
    out, seen = [], set()
    for o in raw if isinstance(raw, list) else []:
        if not isinstance(o, dict):
            continue
        kind, ref, iid = str(o.get("kind") or ""), str(o.get("ref") or "").strip(), str(o.get("itemId") or "").strip()
        if kind not in ("material", "extra") or not ref or not iid or (kind, ref) in seen:
            continue
        seen.add((kind, ref))
        out.append({"kind": kind, "ref": ref, "itemId": iid})
    return out


def compute(conn, quote_no, *, offsets=None, unadopted=UNADOPTED_IGNORE) -> dict:
    q = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    try:
        data = json.loads((q["data_json"] if q else "") or "{}")
    except (TypeError, ValueError):
        data = {}
    plan = PI.plan_items(data)
    live = {p["itemId"] for p in plan}
    saved = data.get("settlement") if isinstance(data.get("settlement"), dict) else {}
    saved_items = {str(i.get("id")): i for i in (saved.get("items") or []) if isinstance(i, dict)}
    offs = normalize_offsets(offsets if offsets is not None else saved.get("offsets"))
    off_material = {o["ref"]: o["itemId"] for o in offs if o["kind"] == "material" and o["itemId"] in live}
    off_extra = {o["ref"]: o["itemId"] for o in offs if o["kind"] == "extra" and o["itemId"] in live}

    # ── 採購單連品項／額外支出：同一批 extra_entries 列（營運報表、總帳 E11 也讀它）──
    po_by_item, extra_rows = {}, []
    for e in R.extra_entries(conn, "accrual", quote_no=quote_no):
        if e.get("linkedItem") and e.get("itemId") in live:
            po_by_item.setdefault(e["itemId"], []).append({"expenseId": e.get("expenseId"), "docCode": e.get("docCode") or "", "category": e.get("category") or "",
                                                          "amount": _num(e.get("amount")), "pending": bool(e.get("pending"))})
        else:
            extra_rows.append(e)

    # ── 材料申請：連到有效採購單者金額在採購單（略過）；草稿／已退回／已取消不計 ──
    mat_by_item, unassigned_mat, warnings = {}, [], []
    for r in R.material_money_rows(conn, quote_no=quote_no):
        if r["linked"] or r["cost"] == "excluded" or not r["total"]:
            continue
        mo = r["order"]
        rec = {"itemId": r["itemId"], "docCode": "", "name": r["name"], "status": r["state"], "amount": r["total"], "pending": r["cost"] == "pending", "noPo": r["noPo"]}
        qid = str(mo.get("quoteItemId") or "").strip()
        if qid in live:
            mat_by_item.setdefault(qid, []).append(dict(rec, assignedBy="link"))
        elif str(r["itemId"]) in off_material:
            mat_by_item.setdefault(off_material[str(r["itemId"])], []).append(dict(rec, assignedBy="offset"))
        else:
            unassigned_mat.append(rec)
            if qid:                                                      # 連到的品項已不在報價單內 ⇒ 回到未對應（錢不消失）
                warnings.append({"code": "item_removed", "ref": str(r["itemId"]), "message": "材料申請連到的品項已不在報價單內，列入未對應"})

    # ── 額外支出：整張單歸單一品項（offset）；其餘留在未對應 ──
    extra_by_item, unassigned_extra, extra_all = {}, [], []
    for e in extra_rows:
        row = {"expenseId": e.get("expenseId"), "docCode": e.get("docCode") or "", "category": e.get("category") or "", "amount": _num(e.get("amount")),
               "pending": bool(e.get("pending"))}
        target = off_extra.get(str(e.get("expenseId")))
        extra_all.append(dict(row, assignedTo=target or ""))
        if target:
            extra_by_item.setdefault(target, []).append(row)
        else:
            unassigned_extra.append(row)

    items, item_total, not_adopted_total = [], 0.0, 0.0
    for p in plan:
        iid = p["itemId"]
        po = po_by_item.get(iid, [])
        mats = mat_by_item.get(iid, [])
        exs = extra_by_item.get(iid, [])
        po_amt, mat_amt, ex_amt = sum(x["amount"] for x in po), sum(x["amount"] for x in mats), sum(x["amount"] for x in exs)
        purchased = po_amt + mat_amt + ex_amt
        est = estimate_amount(p["planQty"], p["planUnitCost"])
        s = saved_items.get(iid)
        manual = _num(s.get("actualTotalCost")) if isinstance(s, dict) and s.get("actualTotalCost") not in (None, "") else None
        adopt = bool(s.get("adoptSystem")) if isinstance(s, dict) and "adoptSystem" in s else True        # 三態：沒存過＝預設開
        has = purchased > 0
        if_not = manual if manual is not None else est
        if_adopt = purchased if has else if_not
        if has and adopt:
            actual, source = purchased, "purchase"
        else:
            actual, source = if_not, ("manual" if manual is not None else "estimate")
        if has and not adopt and unadopted == UNADOPTED_ADD:
            not_adopted_total += purchased
        items.append({"itemId": iid, "description": p["description"], "planQty": p["planQty"], "unit": p["unit"],
                      "estimate": {"unitCost": p["planUnitCost"], "amount": est},
                      "po": {"amount": po_amt, "docs": po}, "material": {"amount": mat_amt, "orders": mats}, "extra": {"amount": ex_amt, "docs": exs},
                      "purchased": purchased, "hasPurchase": has, "adopt": adopt,
                      "actual": {"amount": actual, "source": source, "replacedEstimate": bool(has and adopt)},
                      "actualIfAdopted": if_adopt, "actualIfNot": if_not,
                      "purchasedNotAdopted": purchased if (has and not adopt) else 0})
        item_total += actual

    un_mat_total = sum(x["amount"] for x in unassigned_mat)
    un_ex_total = sum(x["amount"] for x in unassigned_extra)
    pend = (sum(d["amount"] for it in items for d in it["po"]["docs"] if d["pending"])
            + sum(m["amount"] for it in items for m in it["material"]["orders"] if m["pending"])
            + sum(m["amount"] for m in unassigned_mat if m["pending"]) + sum(x["amount"] for x in extra_all if x["pending"]))
    sources = {"po": sum(it["po"]["amount"] for it in items), "materialAssigned": sum(it["material"]["amount"] for it in items),
               "materialUnassigned": un_mat_total, "extraAssigned": sum(it["extra"]["amount"] for it in items), "extraUnassigned": un_ex_total}
    return {"quoteNo": quote_no, "basis": "accrual", "unadoptedMode": unadopted, "items": items,
            "extra": {"onlyAmount": un_ex_total, "rows": extra_all},
            "unassigned": {"materials": unassigned_mat, "extras": unassigned_extra}, "offsets": offs,
            "sources": sources,
            "totals": {"itemActualTotal": item_total, "itemPoUnadopted": not_adopted_total, "extraTotal": un_ex_total,
                       "materialUnassignedTotal": un_mat_total, "purchasedTotal": sum(sources.values()), "pendingTotal": pend},
            "warnings": warnings}
