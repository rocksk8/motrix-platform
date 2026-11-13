# -*- coding: utf-8 -*-
"""一條龍 P1'：案件「物料流程」時間軸的資料組裝（唯讀；旗標 onepipe.timeline）。

[不變式]
- **沒有任何金額欄位**：只回狀態、單號、日期、數量。看不看得到金額與這個畫面無關，所以不需要逐人遮罩，也不可能漏。
- 只顯示今天算得出來的格子：材料申請、採購、到貨、入庫（部分）、出貨、設備、保固；算不出來的標「尚未提供」，不編。
- 其他模組的資料只經串接點：入庫格 `stock.case_summary`（IP-117，M03）、出貨格 `shipping.list_for_case`（IP-18，M03）；
  M03 不在 ⇒ 兩格整格隱藏；M03 在但讀取出錯 ⇒ 該格顯示「暫時讀不到」（不隱藏，免得被誤認沒有倉儲）；出貨單無權限 ⇒ 該段整段不回傳。
- 格子狀態四種：`inprogress` 進行中、`done` 完成、`skipped` 略過、`na` 不適用或尚未提供（P1' 還算不出「略過（直送）」，所以目前不會出現 skipped）。
- 案件可見性由呼叫端先檢查（`require_case`）；本檔不寫入、不 commit。
"""
import calendar
import json
from datetime import date
from urllib.parse import quote as _urlquote

from fastapi import HTTPException

from core import registry as _registry
from helpers import onepipe_flags

STATES = ("inprogress", "done", "skipped", "na")
_KIND_LABEL = {"purchase_req": "請購單", "purchase_order": "採購單"}
_VOIDED = "已作廢"
_NEXT = {  # 各格「下一步」要開的頁（只帶案號；開了就是現有頁面）
    "call": ("去送材料申請", "case-management.html?q={q}&tab=exec&sub=materials"),
    "purchase": ("開請購單", "payment-request.html?case={q}&type=purchase_req"),
    "arrive": ("去確認到貨", "case-management.html?q={q}&tab=fin"),
    "ship": ("去開出貨單", "case-management.html?q={q}&tab=shipping"),
    "device": ("去登載設備", "case-management.html?q={q}&tab=exec"),
    "warranty": ("去填保固起始日", "case-management.html?q={q}&tab=exec"),
}


def _cell(key, label, state, summary, items=None, **extra):
    c = {"key": key, "label": label, "state": state, "summary": summary, "items": items or []}
    c.update(extra)
    return c


def _json(s, default):
    try:
        v = json.loads(s) if isinstance(s, str) and s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


def _add_months(d, m):
    y, mo = divmod(d.month - 1 + m, 12)
    y, mo = d.year + y, mo + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def _partial(received_qty, applied):
    """只到部分（已到數量有值、且小於申請數量）⇒ `{"partial": True, "receivedQty", "appliedQty"}`；沒填（舊的確認到貨）或已到齊 ⇒ `{}`。"""
    try:
        got, want = float(received_qty), float(applied)
    except (TypeError, ValueError):
        return {}
    if got < want - 1e-9:
        return {"partial": True, "receivedQty": int(got) if got.is_integer() else got, "appliedQty": int(want) if want.is_integer() else want}
    return {}


def _call_and_arrive(conn, quote_no, data):
    names = {str(o.get("itemId")): o.get("itemName", "") for o in ((data.get("caseRecord") or {}).get("materialOrders") or []) if isinstance(o, dict)}
    wiz = onepipe_flags.flag_on("receive_wizard", conn)                                    # 一條龍 P2b：已到數量（分批累計）旗標開才讀、才顯示
    qtys = {str(o.get("itemId")): o.get("quantity") for o in ((data.get("caseRecord") or {}).get("materialOrders") or []) if isinstance(o, dict)}
    rows = conn.execute("SELECT item_id, doc_code, status, received_on" + (", received_qty" if wiz else "")
                        + " FROM case_material_approvals WHERE quote_no=? AND status<>'已作廢' ORDER BY doc_code, item_id", (quote_no,)).fetchall()
    items = [{"docCode": r["doc_code"] or "", "name": names.get(str(r["item_id"]), ""), "status": r["status"] or "", "receivedOn": r["received_on"] or ""} for r in rows]
    partial = {id(i): (_partial(r["received_qty"], qtys.get(str(r["item_id"]))) if wiz else {}) for i, r in zip(items, rows)}
    if not items:
        return _cell("call", "材料申請", "na", "尚無材料申請單"), _cell("arrive", "到貨", "na", "尚無材料申請單")
    approved = [i for i in items if i["status"] == "已核准"]
    call = _cell("call", "材料申請", "done" if len(approved) == len(items) else "inprogress",
                 "%d 張材料申請單，%d 張已核准" % (len(items), len(approved)), items)
    if not approved:
        return call, _cell("arrive", "到貨", "na", "材料申請單核准後才會有到貨")
    got = [i for i in approved if i["receivedOn"] and not partial[id(i)]]
    part = [i for i in approved if i["receivedOn"] and partial[id(i)]]
    arrive = _cell("arrive", "到貨", "done" if len(got) == len(approved) else "inprogress",
                   "%d 張已核准的材料申請單，%d 張已到貨" % (len(approved), len(got)) + ("；%d 張只到部分" % len(part) if part else ""),
                   [{"docCode": i["docCode"], "name": i["name"], "arrived": bool(i["receivedOn"]) and not partial[id(i)], "receivedOn": i["receivedOn"],
                     **({"receivedQty": partial[id(i)]["receivedQty"], "appliedQty": partial[id(i)]["appliedQty"]} if partial[id(i)] else {})} for i in approved])
    return call, arrive


def _purchase(conn, quote_no):
    rows = conn.execute("SELECT kind, doc_code, status, expense_date FROM case_extra_expenses WHERE quote_no=? AND kind IN ('purchase_req','purchase_order') AND status<>? ORDER BY id",
                        (quote_no, _VOIDED)).fetchall()
    items = [{"kind": r["kind"], "kindLabel": _KIND_LABEL.get(r["kind"], ""), "docCode": r["doc_code"] or "", "status": r["status"] or "", "date": r["expense_date"] or ""} for r in rows]
    if not items:
        return _cell("purchase", "採購", "na", "尚無請購單或採購單")
    pos = [i for i in items if i["kind"] == "purchase_order"]
    done = bool(pos) and all(i["status"] == "已核准" for i in pos)
    return _cell("purchase", "採購", "done" if done else "inprogress", "%d 張請購單、%d 張採購單" % (len(items) - len(pos), len(pos)), items)


def _stock(conn, quote_no, user):
    """入庫格單一規則（提案 §2.2）：M03 不在 ⇒ None（整格隱藏）；在但出錯 ⇒「暫時讀不到」；在 ⇒ 只顯示已安裝／已出貨台數，其餘標「第 2 階段後提供」。"""
    fn = _registry.single_provider("stock.case_summary")
    if fn is None:
        return None
    try:
        s = fn(conn, quote_no, user)
    except HTTPException as e:
        if e.status_code in (401, 403):                              # 沒有檢視庫存的權限 ⇒ 這一格只說「無權限檢視」，不回任何數量
            return _cell("stock", "入庫", "na", "無權限檢視", forbidden=True)
        return _cell("stock", "入庫", "na", "庫存暫時讀不到", unavailable=True)
    except Exception:                                                # noqa: BLE001 — 供應端壞了只影響這一格
        return _cell("stock", "入庫", "na", "庫存暫時讀不到", unavailable=True)
    ins, shp = int(s.get("installed") or 0), int(s.get("shipped") or 0)
    if "receivedInStock" in s:                                       # 一條龍 P2a（旗標 onepipe.receive_ledger 開）：入庫格完整（提案 §2.2 ④）
        rec, direct = int(s.get("receivedInStock") or 0), int(s.get("directBatches") or 0)
        if not (ins or shp or rec or direct):
            return _cell("stock", "入庫", "na", "目前沒有這個案件的入庫紀錄")
        text = "已入庫尚未認領 %d 台、已安裝 %d 台、已出貨 %d 台" % (rec, ins, shp) + ("；%d 批直送客戶現場" % direct if direct else "")
        return _cell("stock", "入庫", "inprogress", text,
                     [{"partNo": p.get("partNo", ""), "inStock": int(p.get("inStock") or 0), "installed": int(p.get("installed") or 0), "shipped": int(p.get("shipped") or 0)}
                      for p in (s.get("parts") or [])])
    if not (ins or shp):
        return _cell("stock", "入庫", "na", "目前沒有這個案件的序號；已入庫但尚未認領的，第 2 階段後提供")
    return _cell("stock", "入庫", "inprogress", "已安裝 %d 台、已出貨 %d 台；已入庫但尚未被這個案件認領的，第 2 階段後提供" % (ins, shp),
                 [{"partNo": p.get("partNo", ""), "installed": int(p.get("installed") or 0), "shipped": int(p.get("shipped") or 0)} for p in (s.get("parts") or [])])


def _ship(quote_no, authorization):
    fn = _registry.single_provider("shipping.list_for_case")
    if fn is None:
        return None
    try:
        notes = fn(quote_no, authorization)
    except HTTPException as e:
        if e.status_code in (401, 403, 404):                         # 無權限 ⇒ 該段整段不回傳（不洩漏有沒有出貨單）
            return None
        return _cell("ship", "出貨", "na", "出貨單暫時讀不到", unavailable=True)
    except Exception:                                                # noqa: BLE001
        return _cell("ship", "出貨", "na", "出貨單暫時讀不到", unavailable=True)
    items = [{"noteNo": n.get("noteNo", ""), "status": n.get("status", ""), "shipDate": n.get("shipDate", ""), "signed": bool(n.get("isSigned"))} for n in (notes or [])]
    if not items:
        return _cell("ship", "出貨", "na", "尚無出貨單")
    ok = [i for i in items if i["status"] == "已核准"]
    return _cell("ship", "出貨", "done" if len(ok) == len(items) else "inprogress", "%d 張出貨單，%d 張已核准" % (len(items), len(ok)), items)


def _device_and_warranty(data):
    devs = [d for d in ((data.get("caseRecord") or {}).get("devices") or []) if isinstance(d, dict)]
    if not devs:
        return _cell("device", "設備", "na", "尚無登載設備"), _cell("warranty", "保固", "na", "登載設備後才有保固")
    with_sn = sum(1 for d in devs if str(d.get("sn") or "").strip())
    device = _cell("device", "設備", "inprogress", "已登載 %d 台設備，其中 %d 台有序號" % (len(devs), with_sn))
    ends, missing = [], 0
    for d in devs:
        ws = str(d.get("warrantyStart") or "")[:10]
        try:
            ends.append(_add_months(date.fromisoformat(ws), int(d.get("warrantyMonths") or 12)))
        except (ValueError, TypeError):
            missing += 1
    if not ends:
        return device, _cell("warranty", "保固", "na", "設備尚未填保固起始日")
    first = min(ends)
    left = (first - date.today()).days
    text = "最早 %s 到期（%s）" % (first.isoformat(), ("還有 %d 天" % left) if left >= 0 else "已過期")
    if missing:
        text += "；另有 %d 台沒填保固起始日" % missing
    return device, _cell("warranty", "保固", "inprogress" if left >= 0 else "done", text, earliestEnd=first.isoformat())


def build(conn, user, quote_no, q_row, authorization=None) -> dict:
    data = _json(q_row["data_json"], {})
    call, arrive = _call_and_arrive(conn, quote_no, data)
    purchase = _purchase(conn, quote_no)
    stock = _stock(conn, quote_no, user)
    ship = _ship(quote_no, authorization)
    device, warranty = _device_and_warranty(data)
    cells = [c for c in (call, purchase, arrive, stock, ship, device, warranty) if c is not None]
    qn = _urlquote(quote_no, safe="")
    for c in cells:
        if c["key"] in _NEXT:
            c["href"] = _NEXT[c["key"]][1].format(q=qn)
    nxt = next((c for c in cells if c["state"] == "inprogress" and c["key"] in _NEXT), None)
    if nxt is None:
        done_idx = max((i for i, c in enumerate(cells) if c["state"] == "done"), default=-1)
        nxt = next((c for c in cells[done_idx + 1:] if c["state"] == "na" and c["key"] in _NEXT and not c.get("unavailable")), None)
    return {"quoteNo": quote_no, "cells": cells, "stockPresent": stock is not None, "shipPresent": ship is not None,
            "next": ({"key": nxt["key"], "label": _NEXT[nxt["key"]][0], "href": nxt["href"]} if nxt else None)}
