# -*- coding: utf-8 -*-
"""出貨單連動材料申請：case 側提供者 `("material.shippable", "case")`（34-S1；契約 docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md）。

只回「可出貨的材料」：疊加列 `status='已核准'` 且已做到貨確認（`received_on` 非空）。草稿、待審核、簽核中、已退回、已取消一律不回；
變更申請待審期間仍以已核准版本計（N3，變更申請核准前原內容照常有效）。**唯讀**：不寫入、不 commit。供 supply（出貨單）模組經 registry 取用，
supply 不 import 本模組；本模組也不讀 `shipping_notes`（占用量由 supply 的 `shipping.material_shipped` 提供，見 S3）。
"""
from modules.case import material_approval as MA
from modules.case import purchase_items as PI


def _has_received_qty(conn):
    try:
        return any(r[1] == "received_qty" for r in conn.execute("PRAGMA table_info(case_material_approvals)").fetchall())
    except Exception:                                                                        # noqa: BLE001
        return False


def material_shippable(conn, quote_no):
    """⇒ `[{materialItemId, docCode, name, unit, quoteItemId, appliedQty, arrivedQty, status}]`（案件內材料申請順序）。
    `arrivedQty`（E5）：到貨確認時選填的實收數量 `received_qty`；沒填＝全數（`appliedQty`）。沒有該案件或沒有材料申請 ⇒ `[]`。"""
    qn = str(quote_no or "").strip()
    if not qn:
        return []
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()
    if row is None:
        return []
    import json
    try:
        data = json.loads(row["data_json"] or "{}")
    except (TypeError, ValueError):
        return []
    ap = MA.rows_for_case(conn, qn)
    with_qty = _has_received_qty(conn)
    out = []
    for o, status in PI.load_material_orders(conn, qn, data):
        iid = str(o.get("itemId"))
        r = ap.get(iid)
        if status != MA.S_APPROVED or r is None or not str(r.get("received_on") or "").strip():
            continue
        applied = PI._num(o.get("quantity"))
        got = r.get("received_qty") if with_qty else None
        arrived = applied if got in (None, "") else min(PI._num(got), applied)                   # 實收不超過已核准量
        out.append({"materialItemId": iid, "docCode": r.get("doc_code") or "", "name": str(o.get("itemName") or ""), "unit": str(o.get("unit") or ""),
                    "quoteItemId": str(o.get("quoteItemId") or "").strip(), "appliedQty": applied, "arrivedQty": arrived, "status": MA.S_APPROVED})
    return out
