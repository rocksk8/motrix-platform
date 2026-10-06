# -*- coding: utf-8 -*-
"""報價品項的「已出貨數量」（M01 側；第 43 班，使用者裁示選項 B）：每個報價品項 訂購數量 vs 已出貨（已核准出貨單）／占用中（待審核、簽核中）。

[單位] case:item_shipped    [層] L2（M01）    [穩定度] 新（第 43 班）
來源（**不讀 shipping_notes**，只經 M03 的提供者；提供者不在 ⇒ 該來源視同 0）：
  ① 材料申請出貨：`shipping.material_shipped`（`{材料申請 itemId: {reserved, shipped, notes}}`），經叫料列的 `quoteItemId` 歸到報價品項；
  ② 從報價單帶入的出貨列：`shipping.quote_item_shipped`（`{報價品項 id: {reserved, shipped, notes}}`，列上有 `quoteItemId`）。
兩者在 M03 端已互斥（帶 materialLink 的列不算 ②），這裡直接相加。庫存序號列、標題列、舊單（沒有 `quoteItemId`）一律不歸屬 ⇒ 該品項 `attributed=False`，畫面顯示「—」。
只有數量，沒有任何金額與成本。唯讀、不 commit。
"""
import logging

from core import registry
from modules.case import purchase_items as PI

log = logging.getLogger(__name__)


def material_item_map(conn, quote_no, data) -> dict:
    """`{材料申請 itemId: 報價品項 id}`（只列有連到報價品項的）——出貨單頁把「材料申請連結列」對回報價品項用。"""
    return {str(o.get("itemId")): str(o.get("quoteItemId") or "").strip()
            for o, _st in PI.load_material_orders(conn, quote_no, data) if str(o.get("quoteItemId") or "").strip()}


def shipped_by_item(conn, quote_no, data) -> dict:
    """`{報價品項 id: {"ordered": 報價數量, "unit": 單位, "shipped": 已出貨, "reserved": 占用中, "notes": [單號…], "attributed": 有沒有任何出貨資料可歸屬}}`
    ——報價單的每個有 id 的品項都列（保持報價順序）。`attributed=False`＝這個品項沒有可歸屬的出貨列（可能是舊單或庫存出貨），畫面顯示「—」而不是 0。"""
    plan = PI.plan_items(data)
    out = {p["itemId"]: {"ordered": p["planQty"], "unit": p["unit"], "shipped": 0.0, "reserved": 0.0, "notes": [], "attributed": False} for p in plan}
    if not out:
        return out

    def add(qid, e):
        d = out.get(str(qid))
        if d is None:
            return
        d["shipped"] += float(e.get("shipped") or 0)
        d["reserved"] += float(e.get("reserved") or 0)
        for n in e.get("notes") or []:
            if n not in d["notes"]:
                d["notes"].append(n)
        d["attributed"] = True

    fn = registry.providers("shipping.material_shipped").get("supply")
    if fn is not None:
        try:
            mat_to_item = material_item_map(conn, quote_no, data)
            for mid, e in (fn(conn, quote_no) or {}).items():
                qid = mat_to_item.get(str(mid))
                if qid:
                    add(qid, e)
        except Exception:                                                   # noqa: BLE001
            log.exception("item_shipped: 材料申請出貨提供者失敗（略過這一來源）")
    fn = registry.providers("shipping.quote_item_shipped").get("supply")
    if fn is not None:
        try:
            for qid, e in (fn(conn, quote_no) or {}).items():
                add(qid, e)
        except Exception:                                                   # noqa: BLE001
            log.exception("item_shipped: 報價品項出貨提供者失敗（略過這一來源）")
    return out


def case_totals(items: dict) -> dict:
    """整案小計 `{ordered, shipped, reserved}`：只加總有單位一致意義的數量（單純數字加總；不同單位混合時只是參考）。"""
    return {"ordered": sum(float(v.get("ordered") or 0) for v in items.values()),
            "shipped": sum(v["shipped"] for v in items.values()),
            "reserved": sum(v["reserved"] for v in items.values())}


def case_shipped_summary(conn, quote_no) -> dict:
    """提供者 `case.shipped_summary`（給營運報表匯出）：`{ordered, shipped, reserved}`；案件不存在 ⇒ 全 0。只有數量。"""
    import json
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if row is None:
        return {"ordered": 0.0, "shipped": 0.0, "reserved": 0.0}
    try:
        data = json.loads(row["data_json"] or "{}")
    except (TypeError, ValueError):
        data = {}
    return case_totals(shipped_by_item(conn, quote_no, data))
