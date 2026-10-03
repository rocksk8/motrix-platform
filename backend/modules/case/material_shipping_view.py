# -*- coding: utf-8 -*-
"""材料申請的出貨連動（34-S3，M01 側）：從 M03 的提供者取「已出貨／占用中」數量與出貨單號，給材料申請頁三格數字與取消阻擋用。

[單位] case:material_shipping_view    [層] L2（M01）    [穩定度] 新（第 34 班）
**不讀 shipping_notes**，只經提供者：`shipping.material_shipped`（M03；`{itemId: {reserved, shipped, notes}}`）。提供者不在 ⇒ 視同 0（沒有出貨資料）；
提供者丟例外 ⇒ 取消申請 fail closed（不能確認就不取消），摘要則安靜略過出貨欄。唯讀、不 commit。
"""
import logging

from core import registry

log = logging.getLogger(__name__)


def shipped_map(conn, quote_no) -> dict:
    fn = registry.providers("shipping.material_shipped").get("supply")
    if fn is None:
        return {}
    return fn(conn, quote_no) or {}


def summary_extra(conn, quote_no) -> dict:
    """`{itemId: {appliedQty, arrivedQty, reserved, shipped, notes}}`——已到料的與有出貨連動的材料申請；其餘不列。出貨提供者出錯 ⇒ 只回申請／到貨。"""
    out = {}
    try:
        from modules.case import material_shippable as MS
        for x in MS.material_shippable(conn, quote_no):
            out[x["materialItemId"]] = {"appliedQty": x["appliedQty"], "arrivedQty": x["arrivedQty"], "reserved": 0.0, "shipped": 0.0, "notes": []}
    except Exception:                                                              # noqa: BLE001
        log.exception("material_shipping_view: shippable 讀取失敗（略過）")
    try:
        for iid, e in shipped_map(conn, quote_no).items():
            d = out.setdefault(str(iid), {"appliedQty": None, "arrivedQty": None, "reserved": 0.0, "shipped": 0.0, "notes": []})
            d["reserved"], d["shipped"], d["notes"] = float(e.get("reserved") or 0), float(e.get("shipped") or 0), list(e.get("notes") or [])
    except Exception:                                                              # noqa: BLE001
        log.exception("material_shipping_view: 出貨提供者失敗（略過出貨欄）")
    return out


def cancel_blocker(conn, quote_no, item_id):
    """取消材料申請前：有活的出貨連結（占用或已出貨）⇒ 回訊息（含出貨單號）；沒有 ⇒ None。提供者出錯 ⇒ 回訊息（fail closed）。"""
    try:
        e = shipped_map(conn, quote_no).get(str(item_id))
    except Exception:                                                              # noqa: BLE001
        log.exception("material_shipping_view: 取消前檢查出貨連動失敗")
        return "暫時無法確認這筆材料申請有沒有出貨單連動，請稍後再試"
    if e and (float(e.get("reserved") or 0) + float(e.get("shipped") or 0)) > 1e-9:
        return "這筆材料申請已有出貨單連動（%s；已出貨 %g、占用中 %g），請先處理那些出貨單再取消" % (
            "、".join(e.get("notes") or []) or "—", float(e.get("shipped") or 0), float(e.get("reserved") or 0))
    return None
