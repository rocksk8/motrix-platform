# -*- coding: utf-8 -*-
"""叫料審核端點（31-C S2）：送審／核准／退回／撤回／取消／到貨確認，以及簽核佇列的提供者（`approval.queue_items`／`approval.detail`）。

設計：docs/platform/plans/MATERIAL-ORDER-APPROVAL-DESIGN.md。狀態機在 `modules/case/material_approval.py`（疊加表
`case_material_approvals`）；本檔只做 HTTP：權限、讀寫 `data_json` 裡的叫料列、稽核、通知。

權限（沿用派發的授權預設）：
- 送審／撤回／到貨確認：案件擁有者規則（業務、協作者、admin 以上；`require_case`）。送審另需財務檢視權（看不到金額的人送不出對的東西，CM13）。
- 核准／退回：**當層簽核人**（`check_approve_permission`／`check_reject_permission`；簽核人不一定是案件成員，不另做案件守門——
  回應不含任何金額或內容）。
- 取消已核准：admin 以上＋必填理由。
所有寫入都先 commit 再通知（`_notify` 自己開連線寫入，不能在持有寫鎖時呼叫）。
"""
import json

from fastapi import APIRouter, Body, Header, HTTPException

from core.txn import begin_write
from db import get_db
from helpers import _audit, _notify, _require_user, _tok, notify_org_chain_notice
from helpers.approval_queue import approval_raw_of as _approval_raw_of, tier_fields as _queue_tier_fields
from modules.case import purchase_items as _PI
from helpers.case_access import require_case
from helpers.financial_mask import money_visible
from modules.case import material_approval as MA
from modules.case import material_notify as MN

router = APIRouter()

_BASE = "/api/quotations/{quote_no}/material-orders/{item_id}"


def _http(e: MA.MaterialApprovalError) -> HTTPException:
    return HTTPException(e.status, e.message)


def _load_case(conn, quote_no: str):
    q = MA.case_row(conn, quote_no)
    if not q:
        raise HTTPException(404, "報價單 %s 不存在" % quote_no)
    return q


def _orders(q) -> list:
    try:
        data = json.loads(q["data_json"] or "{}") or {}
    except (TypeError, ValueError):
        return []
    return [o for o in ((data.get("caseRecord") or {}).get("materialOrders") or []) if isinstance(o, dict)]


def _order(q, item_id: str) -> dict:
    for o in _orders(q):
        if str(o.get("itemId")) == str(item_id):
            return o
    raise HTTPException(404, "找不到這筆叫料（請先儲存叫料清單）")


def _info(row, q, order, quote_no):
    return {"docCode": row["doc_code"], "quoteNo": quote_no, "itemName": (order or {}).get("itemName") or ""}


def _summary(row) -> dict:
    if not row:
        return {"status": "", "legacy": True}
    try:
        appr = json.loads(row["approval_json"] or "{}")
    except (TypeError, ValueError):
        appr = {}
    tiers = appr.get("tiers") or []
    ct = appr.get("currentTier") or 0
    cur = [a.get("displayName") or a.get("username") for a in (tiers[ct].get("approvers") or [])] if tiers and ct < len(tiers) else []
    return {"status": row["status"], "legacy": False, "docCode": row["doc_code"], "version": row["version"],
            "requestedBy": appr.get("requestedByDisplay") or appr.get("requestedBy") or "", "tierCount": len(tiers), "currentTier": ct,
            "currentApprovers": cur, "rejectReason": appr.get("rejectReason") if row["status"] == MA.S_RETURNED else "",
            "receivedOn": row["received_on"], "receivedBy": row["received_by"], "receivedAt": row["received_at"],
            "cancelReason": row["cancel_reason"] if row["status"] == MA.S_CANCELLED else ""}


# ── 讀 ───────────────────────────────────────────────────────────────

@router.get("/api/quotations/{quote_no}/material-order-approvals")
def get_approvals(quote_no: str, authorization: str = Header(None)):
    """這個案件每一筆叫料的審核摘要 `{approvals: {itemId: 摘要}}`（沒有疊加列＝舊單 `{status:'', legacy:true}`）。不含金額。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        rows = MA.rows_for_case(conn, quote_no)
        return {"quoteNo": quote_no, "approvals": {str(o.get("itemId")): _summary(rows.get(str(o.get("itemId")))) for o in _orders(q)}}
    finally:
        conn.close()


# ── 寫 ───────────────────────────────────────────────────────────────

def _notify_after(event, info, res, requester_display="", reason=""):
    """寫入已 commit 之後：站內通知＋信件（附帶動作，不可讓簽核失敗）。"""
    try:
        if event == "submitted":
            for u in res.get("firstApprovers") or []:
                _notify(u, "material_order_approval_request", info["docCode"], info["quoteNo"], "叫料單 %s（%s）需要您簽核" % (info["docCode"], info["itemName"]))
            MN.fire("submitted", info, approvers=res.get("firstApprovers"))
        elif event == "next_tier":
            for u in res.get("nextApprovers") or []:
                _notify(u, "material_order_approval_request", info["docCode"], info["quoteNo"], "叫料單 %s（%s）需要您簽核" % (info["docCode"], info["itemName"]))
            MN.fire("next_tier", info, approvers=res.get("nextApprovers"), tier_no=res.get("tierNo", 0), total_tiers=res.get("totalTiers", 0))
        elif event == "approved":
            if res.get("requester"):
                _notify(res["requester"], "material_order_approved", info["docCode"], info["quoteNo"], "叫料單 %s（%s）已核准" % (info["docCode"], info["itemName"]))
            MN.fire("approved", info, requester=res.get("requester") or "")
        elif event == "returned":
            if res.get("requester"):
                _notify(res["requester"], "material_order_returned", info["docCode"], info["quoteNo"],
                        "叫料單 %s（%s）已被退回：%s" % (info["docCode"], info["itemName"], reason))
            MN.fire("returned", info, requester=res.get("requester") or "", reason=reason)
    except Exception:                                                              # noqa: BLE001
        pass


@router.post(_BASE + "/submit")
def submit(quote_no: str, item_id: str, authorization: str = Header(None)):
    """送審（草稿／已退回 → 待審核；沒設簽核層 ⇒ 直接已核准）。第一次送審時若這筆叫料還沒有審核單（舊單或剛存的新單），自動建立。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        if not money_visible(user):
            raise HTTPException(403, "此帳號沒有財務檢視權限，不可送審叫料")
        if (q["deal_tag"] or "") == "已結案":
            raise HTTPException(400, "已結案案件無法送審叫料")
        order = _order(q, item_id)
        if MA.get(conn, quote_no, item_id) is None:
            MA.create_draft(conn, quote_no, item_id, user, "送審時建立（舊單）")
        try:
            res = MA.submit(conn, quote_no, order, user)
        except MA.MaterialApprovalError as e:
            raise _http(e)
        row = MA.get(conn, quote_no, item_id)
        conn.commit()
        info = _info(row, q, order, quote_no)
    finally:
        conn.close()
    _audit(_tok(authorization), "material_orders.submit" if not res["autoApproved"] else "material_orders.auto_approve", "quotation", quote_no,
           "叫料單 %s（%s）%s" % (info["docCode"], info["itemName"], "送審" if not res["autoApproved"] else "未設定簽核層，直接核准"),
           {"docCode": info["docCode"], "tierCount": res["tierCount"], "status": res["status"]})
    if res["autoApproved"]:
        _notify_after("approved", info, {"requester": user["username"]})
    else:
        _notify_after("submitted", info, res)
        try:
            conn2 = get_db()
            try:
                row2 = MA.get(conn2, quote_no, item_id)
                tiers = (json.loads(row2["approval_json"] or "{}").get("tiers") or [])
                notify_org_chain_notice(conn2, tiers, user["username"], info["docCode"], quote_no,
                                        "叫料單 %s（%s）由 %s 依組織職權自行簽核，知會您" % (info["docCode"], info["itemName"], user.get("display_name") or user["username"]),
                                        type_="material_order_approval_notice")
            finally:
                conn2.close()
        except Exception:                                                          # noqa: BLE001 — 知會是附帶動作
            pass
    return {"ok": True, "status": res["status"], "docCode": info["docCode"], "tierCount": res["tierCount"], "autoApproved": res["autoApproved"]}


@router.post(_BASE + "/approve")
def approve(quote_no: str, item_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """核准當層；全部層都過了才「已核准」。能不能簽由「是否為當層簽核人」決定（不另要求 admin／案件成員）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        order = _order(q, item_id)
        try:
            res = MA.approve(conn, quote_no, order, user, comment=(body or {}).get("comment") or "", cascade=bool((body or {}).get("cascade")))
        except MA.MaterialApprovalError as e:
            raise _http(e)
        row = MA.get(conn, quote_no, item_id)
        conn.commit()
        info = _info(row, q, order, quote_no)
    finally:
        conn.close()
    _audit(_tok(authorization), "material_orders.approve", "quotation", quote_no,
           "叫料單 %s（%s）核准 → %s" % (info["docCode"], info["itemName"], res["status"]), {"docCode": info["docCode"], "status": res["status"], "tier": res["currentTier"]})
    _notify_after("approved" if res["done"] else "next_tier", info, res)
    return {"ok": True, "status": res["status"], "currentTier": res["currentTier"]}


@router.post(_BASE + "/reject")
def reject(quote_no: str, item_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """退回（原因必填）→ 已退回，建單人修改後可重送。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        order = _order(q, item_id)
        try:
            res = MA.reject(conn, quote_no, item_id, user, (body or {}).get("reason"))
        except MA.MaterialApprovalError as e:
            raise _http(e)
        row = MA.get(conn, quote_no, item_id)
        conn.commit()
        info = _info(row, q, order, quote_no)
    finally:
        conn.close()
    _audit(_tok(authorization), "material_orders.reject", "quotation", quote_no,
           "叫料單 %s（%s）被退回：%s" % (info["docCode"], info["itemName"], res["reason"]), {"docCode": info["docCode"], "reason": res["reason"]})
    _notify_after("returned", info, res, reason=res["reason"])
    return {"ok": True, "status": res["status"]}


@router.post(_BASE + "/withdraw")
def withdraw(quote_no: str, item_id: str, authorization: str = Header(None)):
    """撤回待審核／簽核中的叫料單（回草稿）：送審人本人或 admin 以上。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        order = _order(q, item_id)
        try:
            MA.withdraw(conn, quote_no, item_id, user)
        except MA.MaterialApprovalError as e:
            raise _http(e)
        row = MA.get(conn, quote_no, item_id)
        conn.commit()
        info = _info(row, q, order, quote_no)
    finally:
        conn.close()
    _audit(_tok(authorization), "material_orders.withdraw", "quotation", quote_no, "叫料單 %s（%s）撤回" % (info["docCode"], info["itemName"]), {"docCode": info["docCode"]})
    return {"ok": True, "status": MA.S_DRAFT}


@router.post(_BASE + "/cancel")
def cancel(quote_no: str, item_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """取消已核准的叫料單：admin 以上＋必填理由（終態「已取消」）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        order = _order(q, item_id)
        try:
            MA.cancel(conn, quote_no, item_id, user, (body or {}).get("reason"))
        except MA.MaterialApprovalError as e:
            raise _http(e)
        row = MA.get(conn, quote_no, item_id)
        conn.commit()
        info = _info(row, q, order, quote_no)
    finally:
        conn.close()
    _audit(_tok(authorization), "material_orders.cancel", "quotation", quote_no,
           "叫料單 %s（%s）取消：%s" % (info["docCode"], info["itemName"], row["cancel_reason"]), {"docCode": info["docCode"], "reason": row["cancel_reason"]})
    return {"ok": True, "status": MA.S_CANCELLED}


@router.post(_BASE + "/receive")
def receive(quote_no: str, item_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """到貨確認（不簽核）：必填到貨日期；記錄確認人與時間；只有已核准的叫料單。同一人可確認。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        order = _order(q, item_id)
        try:
            res = MA.record_receipt(conn, quote_no, item_id, (body or {}).get("receivedOn"), user)
        except MA.MaterialApprovalError as e:
            raise _http(e)
        row = MA.get(conn, quote_no, item_id)
        conn.commit()
        info = _info(row, q, order, quote_no)
    finally:
        conn.close()
    _audit(_tok(authorization), "material_orders.receive", "quotation", quote_no,
           "叫料單 %s（%s）確認到貨：%s" % (info["docCode"], info["itemName"], res["receivedOn"]), {"docCode": info["docCode"], "receivedOn": res["receivedOn"]})
    return {"ok": True, **res}


@router.delete(_BASE + "/receive")
def receive_undo(quote_no: str, item_id: str, authorization: str = Header(None)):
    """撤銷到貨確認（留稽核）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        order = _order(q, item_id)
        try:
            res = MA.undo_receipt(conn, quote_no, item_id, user)
        except MA.MaterialApprovalError as e:
            raise _http(e)
        row = MA.get(conn, quote_no, item_id)
        conn.commit()
        info = _info(row, q, order, quote_no)
    finally:
        conn.close()
    _audit(_tok(authorization), "material_orders.receive_undo", "quotation", quote_no,
           "叫料單 %s（%s）撤銷到貨確認（原 %s／%s）" % (info["docCode"], info["itemName"], res["was"]["receivedOn"], res["was"]["receivedBy"]), {"docCode": info["docCode"]})
    return {"ok": True}


# ── 簽核佇列提供者（IP-10 `approval.queue_items`／IP-93 `approval.detail`）─────────────────────────────

def queue_items(conn) -> list:
    """待簽核的叫料單（待審核／簽核中）。新單據類型自帶 `typeLabel／openUrl／approveUrl／rejectUrl／rejectField`（A2-0 #2），佇列頁不必改。
    佇列上的「單號」＝叫料單號（`doc_code`，全域唯一）；詳情也以它查。"""
    out = []
    rows = conn.execute("SELECT a.*, q.customer_name, q.project_name, q.data_json FROM case_material_approvals a"
                        " LEFT JOIN quotations q ON q.quote_no = a.quote_no WHERE a.status IN ('待審核','簽核中') ORDER BY a.rowid DESC").fetchall()
    for r in rows:
        raw = _approval_raw_of(r["approval_json"], "material_order", r["doc_code"])
        if raw is None:
            continue
        f = _queue_tier_fields(raw)
        order = {}
        try:
            for o in (((json.loads(r["data_json"] or "{}") or {}).get("caseRecord") or {}).get("materialOrders") or []):
                if isinstance(o, dict) and str(o.get("itemId")) == r["item_id"]:
                    order = o
                    break
        except (TypeError, ValueError):
            pass
        base = "/api/quotations/%s/material-orders/%s" % (r["quote_no"], r["item_id"])
        out.append({
            "type": "material_order", "typeLabel": MA.DOC_LABEL, "docCode": r["doc_code"], "quoteNo": r["doc_code"],
            "customer": r["customer_name"] or "", "projectName": order.get("itemName") or "", "total": order.get("totalPrice") or 0,
            "quoteDate": (f["requestedAt"] or "")[:10], "salesPerson": "", "requestedBy": f["requestedBy"],
            "requestedByDisplay": f["requestedByDisplay"], "requestedAt": f["requestedAt"], "isEditApproval": False, "reasons": [],
            "tiers": f["tiers"], "currentTier": f["currentTier"], "tierCount": f["tierCount"], "currentApprovers": f["currentApprovers"],
            "tags": _PI.queue_tags(conn, r["quote_no"], order),            # 32-S4d：「該材料申請未申請採購單」小標註（L1 tags[]）
            "linkedQuoteNo": r["quote_no"], "openUrl": "case-management.html?q=%s" % r["quote_no"],
            "approveUrl": base + "/approve", "rejectUrl": base + "/reject", "rejectField": "reason",
        })
    return out


def detail(conn, doc_no):
    """`approval.detail`（name＝material_order）：簽核人看的詳情。`doc_no`＝叫料單號。金額欄位由 L1 依財務檢視權遮蔽（標籤 單價／小計）。"""
    r = conn.execute("SELECT * FROM case_material_approvals WHERE doc_code=?", (doc_no,)).fetchone()
    if not r:
        raise HTTPException(404, "叫料單不存在")
    q = conn.execute("SELECT data_json, customer_name, project_name FROM quotations WHERE quote_no=?", (r["quote_no"],)).fetchone()
    order = {}
    if q:
        try:
            for o in (((json.loads(q["data_json"] or "{}") or {}).get("caseRecord") or {}).get("materialOrders") or []):
                if isinstance(o, dict) and str(o.get("itemId")) == r["item_id"]:
                    order = o
                    break
        except (TypeError, ValueError):
            pass
    fields = [{"label": "單號", "value": r["doc_code"]}, {"label": "案件", "value": r["quote_no"]},
              {"label": "品名", "value": order.get("itemName") or "—"},
              {"label": "數量", "value": ("%s %s" % (order.get("quantity", ""), order.get("unit") or "")).strip() or "—"},
              {"label": "單價", "value": format(float(order.get("unitPrice") or 0), ",.0f")},
              {"label": "小計", "value": format(float(order.get("totalPrice") or 0), ",.0f")},
              {"label": "備註", "value": order.get("notes") or "—"}, {"label": "版本", "value": str(r["version"])}]
    return {"quoteNo": r["quote_no"], "approvalRaw": r["approval_json"], "title": "叫料 %s" % r["doc_code"], "fields": fields, "items": [], "files": []}
