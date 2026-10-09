# -*- coding: utf-8 -*-
"""勞報單 ⇄ 承攬派發的雙向連結（第 46 班；設計 PAYSLIP-APPROVAL-T45.md §6）。

[單位] payroll:payslip_links    [層] L2（M07）    [穩定度] 實作
[公開介面] 提供者 `payslip.dispatch_links`（IP 號待列車取號）：`links_for_dispatch(conn, dispatch_id)`、`links_for_payslip(conn, slip_no)`、
          `link(conn, slip_no, dispatch_id, user, note="")`、`unlink(conn, slip_no, dispatch_id, user)`（皆不 commit）
[資料] 表 `payslip_dispatch_links`（payroll migration 4）：一派發對多勞報單、一勞報單對多派發；唯一鍵 (slip_no, dispatch_id)。
       匯款單 `personnel[].payslipNo` 保留（相容），連結表是較上游的事實；兩者互不依賴。
[🔴 可見範圍（使用者 Q9）] 提供者只回**單號、狀態、受領人姓名、開單日期、已作廢旗標**；**不回金額、扣繳、身分資料、銀行帳號**
       （派發頁的使用者不一定是最高管理者）。是否能點進勞報單由頁面依角色決定。
[規則] 解除連結只允許勞報單尚未付款（已付款含經匯款單付款者不可解除）；勞報單作廢 ⇒ 連結保留並標已作廢；勞報單被退回、派發取消 ⇒ 連結不動。
"""
import json
from datetime import datetime


class LinkError(ValueError):
    """連結被拒：`status`＝HTTP 狀態碼（呼叫端轉 HTTPException）。"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _public(r) -> dict:
    return {"slipNo": r["slip_no"], "dispatchId": r["dispatch_id"], "status": r["status"] or "", "contractorName": r["contractor_name"] or "",
            "slipDate": (r["slip_date"] or "")[:10], "voided": (r["status"] or "") == "已作廢", "note": r["note"] or "",
            "linkedBy": r["created_by"] or "", "linkedAt": (r["created_at"] or "")[:19]}


_SELECT = ("SELECT l.slip_no, l.dispatch_id, l.note, l.created_by, l.created_at, p.status, p.contractor_name, p.slip_date"
           " FROM payslip_dispatch_links l JOIN payslips p ON p.slip_no = l.slip_no")


def links_for_dispatch(conn, dispatch_id) -> list:
    return [_public(r) for r in conn.execute(_SELECT + " WHERE l.dispatch_id=? ORDER BY l.id", (int(dispatch_id),)).fetchall()]


def links_for_payslip(conn, slip_no) -> list:
    return [_public(r) for r in conn.execute(_SELECT + " WHERE l.slip_no=? ORDER BY l.id", (str(slip_no),)).fetchall()]


def payslips_for_contractors(conn, contractor_ids, dispatch_ids=None) -> dict:
    """第 48 班：這些外包名冊人員的勞報單，**只限連到 `dispatch_ids`（呼叫端傳「同一案件的派發」）的**——不跨案揭露某人的全部勞報單。
    只看權威的 `contractor_id`（名稱推測存在 `contractor_guess_id`，不列、只回張數）。欄位：單號、狀態、受領人、開單日、已作廢旗標——
    **不含金額、扣繳、身分、銀行**。"""
    ids = [int(x) for x in contractor_ids if str(x).lstrip("-").isdigit()][:200]
    dids = [int(x) for x in (dispatch_ids or []) if str(x).lstrip("-").isdigit()][:500]
    if not ids:
        return {"items": [], "unconfirmedCount": 0}
    q = ",".join("?" * len(ids))
    guess = conn.execute("SELECT COUNT(*) FROM payslips WHERE contractor_guess_id IN (%s) AND contractor_id IS NULL" % q, ids).fetchone()[0]
    items = []
    if dids:
        qd = ",".join("?" * len(dids))
        rows = conn.execute("SELECT DISTINCT p.id, p.slip_no, p.status, p.contractor_name, p.slip_date FROM payslips p"
                            " JOIN payslip_dispatch_links l ON l.slip_no = p.slip_no"
                            " WHERE p.contractor_id IN (%s) AND l.dispatch_id IN (%s) ORDER BY p.id DESC" % (q, qd), ids + dids).fetchall()
        items = [{"slipNo": r["slip_no"], "status": r["status"] or "", "contractorName": r["contractor_name"] or "",
                  "slipDate": (r["slip_date"] or "")[:10], "voided": (r["status"] or "") == "已作廢"} for r in rows]
    return {"items": items, "unconfirmedCount": guess}


def link(conn, slip_no, dispatch_id, user, note="") -> dict:
    """建立連結（已存在 ⇒ 409）。勞報單不存在 ⇒ 404；已作廢 ⇒ 409（不能把作廢單接到派發）。不 commit。"""
    slip_no = str(slip_no or "").strip()
    row = conn.execute("SELECT status FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
    if row is None:
        raise LinkError(404, "找不到此勞報單")
    if row["status"] == "已作廢":
        raise LinkError(409, "已作廢的勞報單不能關聯派發")
    now = datetime.now().isoformat(timespec="seconds")
    try:
        conn.execute("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, note, created_by, created_at) VALUES (?,?,?,?,?)",
                     (slip_no, int(dispatch_id), str(note or "").strip()[:200], user.get("username") or "", now))
    except Exception as exc:                                        # noqa: BLE001 — 唯一鍵衝突
        if "UNIQUE" in str(exc).upper():
            raise LinkError(409, "這張勞報單已關聯此派發")
        raise
    return {"slipNo": slip_no, "dispatchId": int(dispatch_id)}


def unlink(conn, slip_no, dispatch_id, user) -> dict:
    """解除連結：只允許勞報單尚未付款（含經匯款單付款者）。連結不存在 ⇒ 404。不 commit。"""
    slip_no = str(slip_no or "").strip()
    row = conn.execute("SELECT p.status, p.data_json FROM payslip_dispatch_links l JOIN payslips p ON p.slip_no=l.slip_no"
                       " WHERE l.slip_no=? AND l.dispatch_id=?", (slip_no, int(dispatch_id))).fetchone()
    if row is None:
        raise LinkError(404, "找不到這筆關聯")
    try:
        via = (json.loads(row["data_json"] or "{}") or {}).get("paid_via_remit")
    except (TypeError, ValueError):
        via = None
    if row["status"] == "已付款" or via:
        raise LinkError(409, "這張勞報單已付款，不可解除與派發的關聯")
    conn.execute("DELETE FROM payslip_dispatch_links WHERE slip_no=? AND dispatch_id=?", (slip_no, int(dispatch_id)))
    return {"slipNo": slip_no, "dispatchId": int(dispatch_id)}


class _Links:
    """提供者 `payslip.dispatch_links`（M07 → M04 派發頁）。"""
    links_for_dispatch = staticmethod(links_for_dispatch)
    links_for_payslip = staticmethod(links_for_payslip)
    payslips_for_contractors = staticmethod(payslips_for_contractors)
    link = staticmethod(link)
    unlink = staticmethod(unlink)
