# -*- coding: utf-8 -*-
"""出貨單連動材料申請（第 33 班 33-S1；契約 docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md）。

[單位] supply:material_link    [層] L2（M03）    [穩定度] 新（第 33 班）
出貨單明細列可帶選填 `materialLink: {materialItemId, docCode, qty}`（單一連結；`items_json` 內、加性；舊單沒有此鍵＝行為完全不變）。
- **不跨模組**：M03 不 import M01。可出貨量由 case 的提供者 `material.shippable` 給（已核准＋已到貨確認的材料申請與到貨量）；
  已占用／已出貨量由本模組的提供者 `shipping.material_shipped` 給（`reserved`＝待審核／簽核中，`shipped`＝已核准；草稿與已退回不計）。
- 檢查（出貨單**送審**與**核准**各一次，後者防競態）：同一筆材料申請所有活的連結數量合計 ≤ `arrivedQty`，否則 `ship_exceeds_arrived`；
  連到不存在／未核准／未到貨／已取消的材料申請 ⇒ `ship_link_invalid`；M01 不在 ⇒ `ship_link_module_off`；同列帶庫存序號 ⇒ `ship_link_serial_exclusive`。
- E6（不擋）：`unlinked_warnings`＝該案件已到料且還有剩餘可出貨量、而這張單沒有連結的品項（送審前顯示警示）。
全部函式唯讀、不 commit。
"""
import json
import math

from core import registry

RESERVED_STATUSES = ("待審核", "簽核中")
SHIPPED_STATUSES = ("已核准",)
_EPS = 1e-9


class LinkError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _items(items_json):
    try:
        v = json.loads(items_json) if isinstance(items_json, str) else (items_json or [])
    except (TypeError, ValueError):
        return []
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def parse_link(it):
    """一列的 `materialLink` ⇒ `(materialItemId, docCode, qty)`；沒有 ⇒ None；形狀不對 ⇒ LinkError。"""
    lk = it.get("materialLink")
    if lk is None:
        return None
    if not isinstance(lk, dict):
        raise LinkError("ship_link_invalid", "材料申請連結的格式不正確")
    mid, doc, qty = lk.get("materialItemId"), lk.get("docCode"), _num(lk.get("qty"))
    if not isinstance(mid, str) or not mid.strip() or not isinstance(doc, str) or qty is None or qty <= 0:
        raise LinkError("ship_link_invalid", "材料申請連結需有 materialItemId、docCode 與大於 0 的數量")
    return mid, doc, qty


def links_of(items) -> list:
    """`[(列序, 列, (materialItemId, docCode, qty))]`；同列帶庫存序號 ⇒ LinkError。"""
    out = []
    for i, it in enumerate(items):
        lk = parse_link(it)
        if lk is None:
            continue
        if (it.get("part_no") or "").strip() and it.get("serials"):
            raise LinkError("ship_link_serial_exclusive", "第 %d 列同時帶庫存序號與材料申請連結：庫存出貨與材料申請出貨請分成不同列" % (i + 1))
        out.append((i, it, lk))
    return out


def material_shipped(conn, quote_no, exclude_note_no=None) -> dict:
    """提供者 `shipping.material_shipped`：`{materialItemId: {"reserved": 數量, "shipped": 數量, "notes": [單號…]}}`。"""
    out = {}
    rows = conn.execute("SELECT note_no, status, items_json FROM shipping_notes WHERE quote_no=? AND status IN (?,?,?)",
                        (quote_no, *RESERVED_STATUSES, *SHIPPED_STATUSES)).fetchall()
    for r in rows:
        if exclude_note_no and r["note_no"] == exclude_note_no:
            continue
        for it in _items(r["items_json"]):
            try:
                lk = parse_link(it)
            except LinkError:
                continue                                  # 壞掉的一列只跳過那一列
            if lk is None:
                continue
            e = out.setdefault(lk[0], {"reserved": 0.0, "shipped": 0.0, "notes": []})
            e["shipped" if r["status"] in SHIPPED_STATUSES else "reserved"] += lk[2]
            if r["note_no"] not in e["notes"]:
                e["notes"].append(r["note_no"])
    return out


def _shippable(conn, quote_no):
    fn = registry.single_provider("material.shippable")
    if fn is None:
        return None
    return {x["materialItemId"]: x for x in (fn(conn, quote_no) or []) if isinstance(x, dict) and x.get("materialItemId")}


def _fmt(x):
    return ("%g" % x)


def check_note(conn, note_no, quote_no, items_json) -> None:
    """送審／核准前的檢查；有問題 raise LinkError。沒有任何 materialLink ⇒ 什麼都不做（舊單行為不變）。"""
    links = links_of(_items(items_json))
    if not links:
        return
    ship = _shippable(conn, quote_no)
    if ship is None:
        raise LinkError("ship_link_module_off", "材料申請模組未啟用，無法連結材料申請出貨")
    used = material_shipped(conn, quote_no, exclude_note_no=note_no)
    mine = {}
    for _i, _it, (mid, doc, qty) in links:
        mine[mid] = mine.get(mid, 0.0) + qty
        s = ship.get(mid)
        if s is None or s.get("docCode") != doc:
            raise LinkError("ship_link_invalid", "材料申請 %s 未核准、未確認到貨、已取消或不存在，不能連結出貨" % doc)
    for mid, qty in mine.items():
        s, u = ship[mid], used.get(mid, {"reserved": 0.0, "shipped": 0.0})
        arrived = _num(s.get("arrivedQty")) or 0.0
        if u["reserved"] + u["shipped"] + qty > arrived + _EPS:
            raise LinkError("ship_exceeds_arrived", "「%s」出貨數量超過已到料：已到料 %s、其他出貨單已占用／已出貨 %s、本單 %s"
                            % (s.get("name") or s.get("docCode"), _fmt(arrived), _fmt(u["reserved"] + u["shipped"]), _fmt(qty)))


def unlinked_warnings(conn, note_no, quote_no, items_json) -> list:
    """E6：已到料且有剩餘可出貨量、而本單沒有連結的品項（不擋）。`[{materialItemId, docCode, name, remaining}]`。"""
    ship = _shippable(conn, quote_no)
    if not ship:
        return []
    try:
        linked = {lk[0] for _i, _it, lk in links_of(_items(items_json))}
    except LinkError:
        linked = set()
    used = material_shipped(conn, quote_no, exclude_note_no=note_no)
    out = []
    for mid, s in ship.items():
        if mid in linked:
            continue
        u = used.get(mid, {"reserved": 0.0, "shipped": 0.0})
        rem = (_num(s.get("arrivedQty")) or 0.0) - u["reserved"] - u["shipped"]
        if rem > _EPS:
            out.append({"materialItemId": mid, "docCode": s.get("docCode", ""), "name": s.get("name", ""), "remaining": rem})
    return out
