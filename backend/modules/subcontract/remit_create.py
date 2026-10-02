# -*- coding: utf-8 -*-
"""匯款分期申請的建立與試算（31-B S2）：款別驗證（款別存在且啟用、派發狀態允許）＋前期彙整＋金額規則（`remit_split.plan`）＋快照。

[單位] m04:remit_create    [層] L2（M04 subcontract）    [穩定度] 實驗（31-B 逐切片補齊）
[公開介面] RemitCreateError, kinded_context, kinded_snapshot, previous_periods
[不變式] 本檔不寫資料庫、不 commit；呼叫端（`api/contractor_vouchers.py` 建立與試算端點）在 BEGIN IMMEDIATE 內呼叫，所以『讀前期 → 算 → 寫入』是同一個交易。
  試算與建立走同一支 `kinded_context`，畫面預覽與實際建立不會算出不同的數字。
規則（設計 §3b／§4）：舊式整筆申請（kind=''）與分期申請（kind<>''）在同一派發**互斥**；分期的前期只看未作廢的；
個人點工（不含稅）預設只掛最後一期（D5 預設，待使用者確認）；完工款／驗收款在前期未結（未付款）時只警示不擋（預設）。
"""
import json
from decimal import Decimal

from helpers.legal_params import round_half_up
from modules.subcontract import remit_kinds as RK
from modules.subcontract import remit_split as RS


class RemitCreateError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def previous_periods(conn, dispatch_id):
    """同一派發未作廢的分期申請（依建立順序）⇒ `[{"id","voucher_no","kind","seq","pretax","tax","ratio","is_paid"}]`。"""
    out = []
    for r in conn.execute("SELECT id, voucher_no, kind, seq, ratio, pretax_amount, snapshot_json, is_paid FROM contractor_payment_vouchers "
                          "WHERE dispatch_id=? AND kind<>'' AND voided_at='' ORDER BY id", (dispatch_id,)).fetchall():
        try:
            snap = json.loads(r[6] or "{}") or {}
        except (TypeError, ValueError):
            snap = {}
        pre = r[5] if r[5] is not None else snap.get("totalAmount")
        out.append({"id": r[0], "voucher_no": r[1], "kind": r[2], "seq": r[3], "ratio": r[4], "pretax": pre, "tax": snap.get("taxAmount", 0), "is_paid": bool(r[7])})
    return out


def _dispatch_total(dispatch):
    items = json.loads(dispatch["items_json"] or "[]")
    total = float(dispatch["total_amount"] or 0)
    if not total and items:
        total = sum(float(it.get("amount", 0) or 0) for it in items)
    return total


def _whole_yuan(total):
    """派發金額（REAL 欄，可能帶角分）⇒ 整數元，四捨五入（half-up，不經浮點）；回 (整數元, 是否有進位／捨去)。"""
    d = Decimal(str(total))
    whole = int(round_half_up(d, Decimal(1)))
    return whole, d != whole


def void_blocker(conn, row):
    """分期申請能不能作廢（LIFO，設計 §4）。`row`＝申請列（要有 voucher_no／dispatch_id／kind／is_paid／voided_at）⇒ 不能時回訊息（字串），可以回 None。
    只有該派發「最新一張未作廢」的分期申請可作廢：最後一期的稅額補差在建立當下凍結，作廢中間一期會讓合計失準。"""
    if not row["kind"]:
        return "舊式整筆申請不能作廢（草稿請刪除；已核准請先撤銷核准）"
    if row["voided_at"]:
        return "這張申請已經作廢"
    if row["is_paid"]:
        return "這張申請已標記匯款，請先撤銷付款再作廢"
    later = [r[0] for r in conn.execute(
        "SELECT voucher_no FROM contractor_payment_vouchers WHERE dispatch_id=? AND kind<>'' AND voided_at='' AND id>(SELECT id FROM contractor_payment_vouchers WHERE voucher_no=?) ORDER BY id",
        (row["dispatch_id"], row["voucher_no"])).fetchall()]
    if later:
        return "只能從最新一期往前作廢（後進先出）：請先作廢後面的 %s" % "、".join(later)
    return None


def kinded_context(conn, dispatch, kind_code, ratio_percent=None, amount=None):
    """⇒ `{"kind", "kinds_version", "previous", "plan", "seq", "mode", "ratio", "total", "rate", "warnings"}`；不合法 ⇒ RemitCreateError(狀態碼, 訊息)。"""
    if not kind_code:
        raise RemitCreateError(400, "請選擇款別")
    if (ratio_percent is None) == (amount is None):
        raise RemitCreateError(400, "請擇一輸入：比例（ratio_percent）或固定金額（amount）")
    cur = RK.current(conn)
    kind = next((k for k in cur["kinds"] if isinstance(k, dict) and k.get("code") == kind_code), None)
    if kind is None:
        raise RemitCreateError(400, "沒有這個款別（%s）" % kind_code)
    ok, why = RK.kind_allowed_at(cur["kinds"], kind_code, dispatch["status"])
    if not ok:
        raise RemitCreateError(409, why)
    legacy = conn.execute("SELECT voucher_no FROM contractor_payment_vouchers WHERE dispatch_id=? AND kind='' AND voided_at=''", (dispatch["id"],)).fetchone()
    if legacy:
        raise RemitCreateError(409, "此派發已用整筆方式產生匯款申請（%s），不能再改用分期；請先處理該申請" % legacy[0])
    prev = previous_periods(conn, dispatch["id"])
    total, rounded = _whole_yuan(_dispatch_total(dispatch))
    rate = float(dispatch["tax_rate"]) if "tax_rate" in dispatch.keys() and dispatch["tax_rate"] is not None else 0.05
    if amount is not None:
        mode, value = "amount", amount
    else:
        mode, value = "ratio", Decimal(str(ratio_percent)) / Decimal(100)
    try:
        plan = RS.plan(total, rate, [{"pretax": p["pretax"], "tax": p["tax"], "ratio": p["ratio"]} for p in prev], mode, value)
    except RS.RemitSplitError as e:
        raise RemitCreateError(400, str(e))
    warnings = list(plan["warnings"])
    if rounded:
        warnings.append("派發金額 %s 元含角分，分期以四捨五入後的整數元 %d 元計算，待會計確認" % (dispatch["total_amount"], total))
    if kind_code in ("completion", "acceptance") and any(not p["is_paid"] for p in prev):
        warnings.append("前面還有 %d 期尚未付款（%s）；仍可開立，請確認付款順序" % (
            sum(1 for p in prev if not p["is_paid"]), "、".join(p["voucher_no"] for p in prev if not p["is_paid"])))
    seq = 1 + max([p["seq"] for p in prev if p["kind"] == kind_code] or [0])
    # 同款別的序號要避開已作廢的（作廢的不佔唯一性，但序號不回頭重用，畫面上才不會有兩張『第 1 期』）
    row = conn.execute("SELECT COALESCE(MAX(seq),0) FROM contractor_payment_vouchers WHERE dispatch_id=? AND kind=?", (dispatch["id"], kind_code)).fetchone()
    seq = max(seq, int(row[0]) + 1)
    return {"kind": kind, "kinds_version": cur["version"], "previous": prev, "plan": plan, "seq": seq, "mode": mode,
            "ratio": float(value) if mode == "ratio" else None, "total": int(total), "rate": rate, "warnings": warnings}


def kinded_snapshot(base, ctx, personnel, personnel_total):
    """把整筆版快照 `base` 改成本期：金額換成本期稅前／稅額，個人點工只掛最後一期，並記下款別資訊。回新 dict。"""
    p = ctx["plan"]
    snap = dict(base)
    pre, tax = p["pretax"], p["tax"]
    keep_personnel = p["is_last"]
    snap.update({
        "totalAmount": pre, "taxRate": ctx["rate"], "taxAmount": tax, "totalWithTax": pre + tax,
        "personnel": personnel if keep_personnel else [], "personnelTotal": personnel_total if keep_personnel else 0,
        "dispatchTotal": ctx["total"], "kind": ctx["kind"]["code"], "kindName": ctx["kind"]["name"], "seq": ctx["seq"],
        "isLastPeriod": bool(p["is_last"]), "makeUp": p["make_up"], "dispatchTotalTax": p["total_tax"],
    })
    snap["grandTotal"] = snap["totalWithTax"] + snap["personnelTotal"]
    return snap
