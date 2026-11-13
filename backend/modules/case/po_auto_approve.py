# -*- coding: utf-8 -*-
"""一條龍 D6=B（旗標 `onepipe.po_skip_resign`，預設關、放寬類）：叫料（材料申請）連到「已核准的採購單行」且內容沒超出採購單 ⇒ 送審即視為核准，不再走簽核層。

道理：採購單已經由簽核人核准過「向誰買、買多少、多少錢」，叫料只是把同一筆貨領進案件；內容沒超出採購單就不必再簽一次。
只有同時符合下列條件才免簽，任何一項不符 ⇒ 回空字串，照原本的簽核流程走：
1. 旗標開啟（預設關；開啟需第二位最高管理者核准）。
2. 叫料連到同案件、狀態是「已核准」的採購單（`poDocCode`）；有填列序（`poLine`）就只看那一行，否則看該採購單中同品項的行（沒有品項時看沒有品項的行）。
3. 叫料還沒有付款紀錄；本筆加上「同一採購單、涵蓋到同一行」的其他有效叫料（草稿／已退回／已取消不計），數量不大於採購單行數量合計、小計不大於採購單行金額合計（容許 0.5 元進位誤差）——
   所以沒填列序、多筆叫料對到同一行時，是累計比較，不會每筆各自免簽而合計超出採購單。
4. 供應商 fail-closed：採購單（從供應商主檔挑的）與叫料**兩邊都有**供應商編號、且相同；任何一邊沒有（含手動輸入廠商的採購單）或不同 ⇒ 不免簽。
已在簽核中的單不追溯；到貨確認仍照原本的流程。旗標關 ⇒ 永遠回空字串（與目前位元組相同）。永不丟例外。
"""
import json

from modules.case import purchase_items as PI

NOTE = "連到已核准的採購單 %s，內容沒有超出採購單，免再簽核"


def _int_id(v):
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 and (not isinstance(v, float) or v == n) else None


def _covered_lines(po, order):
    """叫料對到採購單的哪幾行 ⇒ `[(行序, line dict)]`；對不上 ⇒ []。"""
    lines = PI._po_lines(po)
    qi = str(order.get("quoteItemId") or "").strip()
    pl = order.get("poLine")
    if pl not in (None, ""):
        idx = _int_id(pl)
        if idx is None or idx > len(lines) or not isinstance(lines[idx - 1], dict):
            return []
        li = str(lines[idx - 1].get("itemId") or "").strip()
        if li and qi and li != qi:
            return []
        return [(idx, lines[idx - 1])]
    out = []
    for i, l in enumerate(lines, 1):
        if isinstance(l, dict) and str(l.get("itemId") or "").strip() == qi:
            out.append((i, l))
    return out


def _same_supplier(po, order) -> bool:
    """fail-closed：採購單與叫料**兩邊都有**供應商編號、且相同才算（任何一邊缺、手動輸入廠商、編號不同 ⇒ False）。"""
    order_sid = _int_id(order.get("supplierId"))
    try:
        d = json.loads(po["data_json"] or "{}") or {}
    except (TypeError, ValueError):
        d = {}
    po_sid = _int_id(d.get("supplierId")) if isinstance(d, dict) else None
    return order_sid is not None and po_sid is not None and order_sid == po_sid


def auto_approve_note(conn, quote_no, order) -> str:
    """可免再簽 ⇒ 回顯示用說明文字；否則 ""（呼叫端照原本流程送簽核）。"""
    try:
        from helpers.onepipe_flags import flag_on
        if not flag_on("po_skip_resign", conn=conn):
            return ""
        order = order or {}
        code = str(order.get("poDocCode") or "").strip()
        if not code or PI.has_paid_history(order):
            return ""
        po = conn.execute("SELECT kind, status, lines_json, doc_code, data_json FROM case_extra_expenses WHERE quote_no=? AND doc_code=?",
                          (quote_no, code)).fetchone()
        if po is None or (po["kind"] or "") != PI.ORD or (po["status"] or "") != "已核准":
            return ""
        covered = _covered_lines(po, order)
        if not covered:
            return ""
        mine = {i for i, _l in covered}
        amount = sum(PI._num(l.get("amount")) for _i, l in covered)
        qty = sum(PI._num(l.get("qty")) for _i, l in covered)
        used_qty, used_amt = PI._num(order.get("quantity")), PI._num(order.get("totalPrice"))
        data, _rows = PI._case_state(conn, quote_no)
        from modules.case import material_approval as MA
        me = str(order.get("itemId") or "")
        for o, st in PI.load_material_orders(conn, quote_no, data):
            if str(o.get("itemId") or "") == me or MA.cost_state(st) == "excluded" or str(o.get("poDocCode") or "").strip() != code:
                continue
            if mine & {i for i, _l in _covered_lines(po, o)}:                       # 其他有效叫料也涵蓋到同一行 ⇒ 累計
                used_qty += PI._num(o.get("quantity"))
                used_amt += PI._num(o.get("totalPrice"))
        if amount <= 0 or used_amt > amount + 0.5 or used_qty > qty + 1e-9:
            return ""
        if not _same_supplier(po, order):
            return ""
        return NOTE % code
    except Exception:                                                           # noqa: BLE001  判斷失敗＝不免簽（照原本流程）
        return ""
