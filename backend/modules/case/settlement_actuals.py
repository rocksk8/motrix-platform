# -*- coding: utf-8 -*-
"""完結精算「實際成本」的單一來源（33-A2；規格 docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md）。

純組合：只用 `recognition.material_money_rows`（材料申請）與 `recognition.extra_entries`（採購單連品項的列＋額外支出）——
營運報表、總帳 E11／E12、完結精算讀的是**同一批列**，這裡沒有任何自己的金額規則，三處不會漂。
沖銷規則 A（使用者裁示）：品項有實際採購（已核准採購單連到該品項、或材料申請歸到該品項）⇒ 實際**取代**該品項估計；沒採購 ⇒ 用估計。
口徑：權責、含待審核（標 pending）；材料申請只含已成案／已結案案件（與報表同一條件）。派發、匯款手續費、自訂模組支出不在這裡（第 34 班）。
"""
import json
import logging

from core import registry
from helpers.legal_params import round_half_up
from modules.case import purchase_items as PI
from modules.case import recognition as R

_log = logging.getLogger(__name__)
VOIDED_STATUS = "已作廢"        # 與 api/case_extra_expenses.VOIDED_STATUS 同值（已作廢的額外支出不進任何合計）
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


def manual_actual(saved_item):
    """精算存檔品項的手填實際成本；沒填＝None。語意與今天頁面載入存檔時的 `si.actualTotalCost || oi.actualTotalCost` 相同：
    0、空字串、null 一律視為「沒填」（⇒ 用估計）——0 元實際成本在頁面上本來就無法持久（da A3 S1；歷史相容，不自行改語意；是否算缺陷列第 34 班待裁示）。"""
    v = saved_item.get("actualTotalCost") if isinstance(saved_item, dict) else None
    return _num(v) if v else None


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


def compute(conn, quote_no, *, offsets=None, unadopted=UNADOPTED_IGNORE, settlement=None, freeze=True) -> dict:
    q = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    try:
        data = json.loads((q["data_json"] if q else "") or "{}")
    except (TypeError, ValueError):
        data = {}
    plan = PI.plan_items(data)
    # 舊品項缺 id 或說明：plan_items 不收，但今天的精算頁會把它們的估計算進去 ⇒ 為了歷史逐位相同，以暫時鍵（~序號）納入（da S3）。
    # 它們沒有真正的 id，採購單／材料申請連不到；只出現在 items 並標 unkeyed。
    n_unkeyed = 0
    for idx, it in enumerate(data.get("items") or []):
        if not isinstance(it, dict) or it.get("type") == "header":
            continue
        iid, desc = str(it.get("id") or "").strip(), str(it.get("description") or "").strip()
        if iid and desc:
            continue
        n_unkeyed += 1
        plan.append({"itemId": iid or "~%d" % idx, "description": desc or "（未命名品項）", "brand": str(it.get("brand") or ""), "unit": str(it.get("unit") or ""),
                     "planQty": _num(it.get("qty")), "planUnitCost": _num(it.get("cost")), "unkeyed": True})
    live = {p["itemId"] for p in plan if not p.get("unkeyed")}
    # settlement＝呼叫端給的精算（PUT 完結時用請求本文，尚未寫進資料庫）；沒給就讀資料庫存的
    src = settlement if isinstance(settlement, dict) else data.get("settlement")
    saved = src if isinstance(src, dict) else {}
    saved_items = {str(i.get("id")): i for i in (saved.get("items") or []) if isinstance(i, dict)}
    offs = normalize_offsets(offsets if offsets is not None else saved.get("offsets"))
    off_material = {o["ref"]: o["itemId"] for o in offs if o["kind"] == "material" and o["itemId"] in live}
    off_extra = {o["ref"]: o["itemId"] for o in offs if o["kind"] == "extra" and o["itemId"] in live}

    warnings = [{"code": "item_unkeyed", "ref": "", "message": "報價單有 %d 個品項缺 id 或說明，無法對應採購；以估計計入" % n_unkeyed}] if n_unkeyed else []

    # ── 採購單連品項／額外支出：同一批 extra_entries 列（營運報表、總帳 E11 也讀它）──
    po_by_item, extra_rows = {}, []
    for e in R.extra_entries(conn, "accrual", quote_no=quote_no):
        if e.get("linkedItem") and e.get("itemId") in live:
            po_by_item.setdefault(e["itemId"], []).append({"expenseId": e.get("expenseId"), "docCode": e.get("docCode") or "", "category": e.get("category") or "",
                                                          "amount": _num(e.get("amount")), "pending": bool(e.get("pending"))})
        else:
            extra_rows.append(e)

    # ── 材料申請：連到有效採購單者金額在採購單（略過）；草稿／已退回／已取消不計 ──
    mat_by_item, unassigned_mat = {}, []
    for r in R.material_money_rows(conn, quote_no=quote_no):
        if r["linked"] or r["cost"] == "excluded" or not r["total"]:
            continue
        mo = r["order"]
        rec = {"itemId": r["itemId"], "docCode": "", "name": r["name"], "quantity": r.get("quantity"), "unit": r.get("unit") or "", "status": r["state"], "amount": r["total"], "pending": r["cost"] == "pending", "noPo": r["noPo"]}
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
        row = {"expenseId": e.get("expenseId"), "docCode": e.get("docCode") or "", "category": e.get("category") or "", "description": e.get("description") or "", "amount": _num(e.get("amount")),
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
        manual = manual_actual(s)
        # 三態：新存檔有 adoptSystem（採用／不採用）；品項沒存過＝預設開；舊存檔（品項有存但沒有 adoptSystem 鍵，第 32 班前）＝今天頁面的行為（不採用，歷史相容；da S2）
        adopt = bool(s.get("adoptSystem")) if isinstance(s, dict) and "adoptSystem" in s else (not isinstance(s, dict))
        has = purchased > 0
        if_not = manual if manual is not None else est
        if_adopt = purchased if has else if_not
        if has and adopt:
            actual, source = purchased, "purchase"
        else:
            actual, source = if_not, ("manual" if manual is not None else "estimate")
        if has and not adopt and unadopted == UNADOPTED_ADD:
            not_adopted_total += purchased
        items.append({"itemId": iid, "unkeyed": bool(p.get("unkeyed")), "description": p["description"], "planQty": p["planQty"], "unit": p["unit"],
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
    ex = case_extras(conn, quote_no)
    legacy_save = any(isinstance(i, dict) and "adoptSystem" not in i for i in saved.get("items") or [])
    out = {"quoteNo": quote_no, "basis": "accrual", "finalized": False, "frozen": False,
           "legacySave": legacy_save,          # 存檔品項沒有 adoptSystem（第 32 班前存的）：adopt 以舊行為（不採用）
           "unadoptedMode": unadopted, "items": items,
            "extra": {"onlyAmount": un_ex_total, "rows": extra_all},
            "unassigned": {"materials": unassigned_mat, "extras": unassigned_extra}, "offsets": offs,
            "sources": sources,
            "totals": {"itemActualTotal": item_total, "itemPoUnadopted": not_adopted_total, "extraTotal": un_ex_total,
                       "materialUnassignedTotal": un_mat_total, "purchasedTotal": sum(sources.values()), "pendingTotal": pend},
            "warnings": warnings, "costExtras": ex}
    t_ = out["totals"]
    t_.update(dispatchTotal=ex["dispatch"]["grandTotal"], dispatchReport=ex["dispatch"]["report"], remitFeeTotal=ex["remitFee"]["total"],
              customExpenseTotal=ex["customExpense"]["total"])
    # 與頁面 calcSummary 同一條式：品項＋未採用採購＋額外支出（含未對應材料申請、手續費、自訂模組）＋派發
    t_["totalActualCost"] = (t_["itemActualTotal"] + t_["itemPoUnadopted"] + t_["extraTotal"] + t_["materialUnassignedTotal"] + t_["remitFeeTotal"]
                             + t_["customExpenseTotal"] + t_["dispatchTotal"])
    if freeze and saved.get("status") == "finalized":
        _freeze(out, saved, saved_items)
    return out


def _freeze(out, saved, saved_items):
    """已完結的精算＝凍結快照（規格 §5；da S1）：金額取完結當下存檔的值，不隨之後核准的採購單／材料申請漂移。
    品項金額用存檔的 `actualTotalCost`（沒存的品項保留現算值）。總額用存檔 `summary`：頁面寫的 `extraTotal` 含匯款手續費與自訂模組支出，
    這裡扣掉 `remitFeeTotal`／`customExpenseTotal`（它們不在本端點，第 34 班）才與 `totals.extraTotal`（未對應額外支出）同義；
    `purchasedTotal`（B1 起頁面也存）有就用。現算值留在 `live` 供頁面提示差異。"""
    summ = saved.get("summary") if isinstance(saved.get("summary"), dict) else {}
    out["finalized"], out["frozen"], out["savedSummary"] = True, True, summ
    out["live"] = {"itemActualTotal": out["totals"]["itemActualTotal"], "extraTotal": out["totals"]["extraTotal"], "purchasedTotal": out["totals"]["purchasedTotal"]}
    total = 0.0
    for it in out["items"]:
        s = saved_items.get(it["itemId"])
        v = manual_actual(s)
        if v is not None:
            it["actual"] = {"amount": v, "source": "frozen", "replacedEstimate": False}
        total += it["actual"]["amount"]
    out["totals"]["itemActualTotal"] = _num(summ["itemActualTotal"]) if "itemActualTotal" in summ else total
    if "extraTotal" in summ:
        mat = _num(summ.get("materialUnassignedTotal"))                  # B1 起頁面存；舊完結案沒有這鍵＝當時沒有材料申請併入（0）
        out["totals"]["materialUnassignedTotal"] = mat
        out["totals"]["extraTotal"] = _num(summ["extraTotal"]) - _num(summ.get("remitFeeTotal")) - _num(summ.get("customExpenseTotal")) - mat
    if "purchasedTotal" in summ:
        out["totals"]["purchasedTotal"] = _num(summ["purchasedTotal"])
    for k in ("dispatchTotal", "remitFeeTotal", "customExpenseTotal", "totalActualCost"):          # 頁面存的完結 summary 同名鍵：凍結值
        if k in summ:
            out["totals"][k] = _num(summ[k])


def validate_offsets(conn, quote_no, raw, previous=None):
    """精算 PUT 的 `settlement.offsets` 驗證（33-A4）。回傳錯誤訊息；合法回 None。

    規則：必須是清單；每列 `kind∈{material,extra}`、`ref`、`itemId` 俱全；`itemId` 必須是報價現有品項；同一 (kind, ref) 只能一個去處；
    `ref` 必須存在於**目前**未對應清單（沒歸品項的材料申請／沒連品項的額外支出）。已經存在於上一次存檔、原樣沒改的列放行
    （材料申請事後取消不致卡住舊草稿；計算端本來就會略過失效列）。"""
    if raw in (None, []):
        return None
    if not isinstance(raw, list):
        return "offsets 必須是清單"
    keep = {(o["kind"], o["ref"], o["itemId"]) for o in normalize_offsets(previous)}
    base = compute(conn, quote_no, offsets=[])
    live = {i["itemId"] for i in base["items"] if not i["unkeyed"]}      # 缺 id／說明的舊品項不能當沖銷去處
    refs = {"material": {str(m["itemId"]) for m in base["unassigned"]["materials"]},
            "extra": {str(e["expenseId"]) for e in base["extra"]["rows"]}}
    # base 的 unassigned 在 offsets=[] 時含全部可沖銷的列（extra.rows 含 assignedTo 者，此時皆未歸屬）
    seen = set()
    for n, o in enumerate(raw, 1):
        if not isinstance(o, dict):
            return "offsets 第 %d 列格式錯誤" % n
        kind, ref, iid = str(o.get("kind") or ""), str(o.get("ref") or "").strip(), str(o.get("itemId") or "").strip()
        if kind not in ("material", "extra") or not ref or not iid:
            return "offsets 第 %d 列缺少 kind／ref／itemId，或 kind 不合法" % n
        if (kind, ref) in seen:
            return "offsets 第 %d 列：%s %s 重複，同一筆只能有一個去處" % (n, kind, ref)
        seen.add((kind, ref))
        if (kind, ref, iid) in keep:
            continue
        if iid not in live:
            return "offsets 第 %d 列：品項 %s 不在報價單內" % (n, iid)
        if ref not in refs[kind]:
            return "offsets 第 %d 列：%s %s 不在目前的未對應清單內" % (n, "材料申請" if kind == "material" else "額外支出", ref)
    return None


def case_extras(conn, quote_no) -> dict:
    """精算頁「成本彙總」裡不屬於品項／採購的三類成本（34；之前由頁面各打一支端點加總）——**口徑與頁面現行算法逐位相同**（使用者裁示 A：歷史精算不變）：
    - 承攬商派發：`dispatchGrandTotal`＝承攬商含稅合計＋外包人員（`dispatch.row` 的 grandTotal；排除已取消、草稿、已退回，待審核／簽核中照計，與頁面同）。
      另給 `dispatchReport`＝未稅承攬費＋人員（營運報表／總帳 `recognition.dispatch_entries` 的口徑，供漂移守門；兩者差異＝承攬費的稅）。
      含稅或未稅是使用者的決定，這裡只並列、不切換。
    - 匯款手續費：額外支出的手續費（已登錄付款、未作廢）＋承攬商匯款手續費（`case.remit_fee_total` 提供者；沒有提供者＝0）。
    - 自訂模組支出：`helpers.custom_finance.case_finance` 的支出合計。
    純讀。"""
    grand = report = 0.0
    n = 0
    dispatch_row = registry.single_provider("dispatch.row")
    if dispatch_row is not None:
        try:
            rows = conn.execute("SELECT cd.*, vc.name AS vendor_name FROM contractor_dispatches cd LEFT JOIN vendor_contractors vc ON vc.id = cd.vendor_id"
                                " WHERE cd.quote_no=? AND cd.status != 'cancelled'", (quote_no,)).fetchall()
        except Exception:                                                                                  # noqa: BLE001  承攬商表不在（模組未啟用）
            rows = []
        for r in rows:
            d = dispatch_row(r)
            if (d.get("approvalStatus") or "") in ("草稿", "已退回"):
                continue
            n += 1
            grand += _num(d.get("grandTotal"))
            report += _num(d.get("totalAmount")) + _num(d.get("personnelTotal"))
    try:
        fee_extra = _num(conn.execute("SELECT COALESCE(SUM(remit_fee), 0) AS t FROM case_extra_expenses WHERE quote_no=? AND COALESCE(paid_date,'') != '' AND status != ?",
                                      (quote_no, VOIDED_STATUS)).fetchone()["t"])
    except Exception:                                                                                      # noqa: BLE001
        fee_extra = 0.0
    fee_fn = registry.single_provider("case.remit_fee_total")
    fee_contractor = _num(fee_fn(conn, quote_no)) if fee_fn is not None else 0.0
    custom = 0.0
    try:
        from helpers import custom_finance as CFIN
        custom = _num(CFIN.case_finance(conn, quote_no)["expense"]["total"])
    except Exception:                                                                                      # noqa: BLE001  自訂模組表不在
        _log.warning("custom_finance.case_finance 失敗 ⇒ 自訂模組支出略過", exc_info=True)
    return {"dispatch": {"grandTotal": grand, "report": report, "count": n},
            "remitFee": {"extraExpenses": fee_extra, "contractor": fee_contractor, "total": fee_extra + fee_contractor},
            "customExpense": {"total": custom}}


def check_finalize(conn, quote_no, settlement):
    """完結（PUT status=finalized）時後端用同一來源重算，與頁面送上的 `summary` 比對（D10；33-A5）。回傳差異說明（清單）；沒有差異回 []。
    比對：品項實際成本、品項未採用採購（新規則恆為 0）、額外支出（扣掉頁面加的手續費與自訂模組支出，含未對應材料申請）、採購類總額（頁面有送才比）。
    允許進位誤差：每個品項 ±1 元（兩邊各自逐品項進位）。summary 沒有 `itemActualTotal`（非精算頁的呼叫）⇒ 無從比對，回 []。"""
    summ = settlement.get("summary") if isinstance(settlement, dict) else None
    if not isinstance(summ, dict) or "itemActualTotal" not in summ:
        return []
    d = compute(conn, quote_no, settlement=settlement, freeze=False)
    tol_item = max(1, len(d["items"]))               # 進位誤差只發生在逐品項進位：每品項 ±1 元
    tol = 1                                          # 額外支出／採購類總額是整數金額加總，不該有進位差；留 1 元防浮點
    t = d["totals"]
    mine_extra = t["extraTotal"] + t["materialUnassignedTotal"]
    their_extra = _num(summ.get("extraTotal")) - _num(summ.get("remitFeeTotal")) - _num(summ.get("customExpenseTotal"))
    checks = [("品項實際成本", _num(summ.get("itemActualTotal")), t["itemActualTotal"], tol_item),
              ("品項未採用的採購（新規則不另計）", _num(summ.get("itemPoUnadopted")), 0.0, tol),
              ("額外支出（含未對應材料申請）", their_extra, mine_extra, tol)]
    if "purchasedTotal" in summ:
        checks.append(("採購類總額", _num(summ.get("purchasedTotal")), t["purchasedTotal"], tol))
    return ["%s：頁面 %s、系統重算 %s" % (name, round(a), round(b)) for name, a, b, tl in checks if abs(a - b) > tl]
