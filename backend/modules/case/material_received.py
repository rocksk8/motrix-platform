# -*- coding: utf-8 -*-
"""IP-119（暫定號，列車定號）`material.received_list`：已確認到貨的材料申請清單（M01 案件 → M03 入庫對帳表；一條龍 P2a）。

[單位] case:material_received    [層] L2    [穩定度] 實驗
[公開介面] received_items
[不變式] **唯讀**：不寫入、不 commit；只回已核准且已做到貨確認（`received_on` 非空）的材料申請（同 `material.shippable` 的條件）；
         **沒有任何金額欄位**（只有品名、單位、數量、單號、日期、確認人）；供 supply 經 registry 取用，supply 不 import 本模組。
         不做案件可見性檢查——呼叫端（入庫對帳表）本身限管理員。
"""
import json

from modules.case import material_approval as MA
from modules.case import purchase_items as PI


def received_items(conn, since="", limit=200) -> list:
    """⇒ `[{quoteNo, itemId, docCode, name, unit, appliedQty, receivedOn, receivedBy}]`（到貨日新到舊）。`since`（YYYY-MM-DD）只回該日（含）之後到貨的。"""
    sql = ("SELECT quote_no, item_id, doc_code, received_on, received_by FROM case_material_approvals"
           " WHERE status=? AND received_on<>''" + (" AND received_on>=?" if since else "") + " ORDER BY received_on DESC, rowid DESC LIMIT ?")
    args = [MA.S_APPROVED] + ([str(since)] if since else []) + [int(limit)]
    rows = conn.execute(sql, args).fetchall()
    by_case = {}
    for r in rows:
        by_case.setdefault(r["quote_no"], []).append(r)
    names = {}
    for qn in by_case:
        q = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()
        try:
            data = json.loads((q["data_json"] if q else "") or "{}") or {}
        except (TypeError, ValueError):
            data = {}
        for o, _st in PI.load_material_orders(conn, qn, data):
            names[(qn, str(o.get("itemId")))] = o
    out = []
    for r in rows:
        o = names.get((r["quote_no"], str(r["item_id"]))) or {}
        out.append({"quoteNo": r["quote_no"], "itemId": str(r["item_id"]), "docCode": r["doc_code"] or "", "name": str(o.get("itemName") or ""), "unit": str(o.get("unit") or ""),
                    "appliedQty": PI._num(o.get("quantity")), "receivedOn": r["received_on"], "receivedBy": r["received_by"] or ""})
    return out
