# -*- coding: utf-8 -*-
"""叫料匯款申請端點（31-C 匯款切片）：建立／修改／送審／核准／退回／撤回／作廢，以及簽核佇列的提供者與供應商選單。

設計：docs/platform/plans/MATERIAL-ORDER-APPROVAL-DESIGN.md §3.4。狀態機與額度在 `modules/case/material_payment.py`；本檔只做 HTTP：
權限、讀叫料列、稽核、通知。付款（出納）走既有 IP-100／IP-102（`material_payment_cashier.py`），不在這裡。

權限：建立／修改／送審／撤回／作廢＝案件擁有者規則（`require_case`）＋ 能編輯叫料（admin 以上或 `project_manage`，且有財務檢視權）；
核准／退回＝當層簽核人（不另做案件守門，回應不含金額與帳戶）。**收款帳戶不進回應與佇列詳情**（只回遮罩）。
所有寫入都先 commit 再通知（`_notify` 自己開連線寫入，不能在持有寫鎖時呼叫）。
"""
import json

from fastapi import APIRouter, Body, Header, HTTPException

from core.txn import begin_write
from db import get_db
from helpers import _audit, _notify, _require_user, _tok, notify_org_chain_notice
from helpers.approval_queue import approval_raw_of as _approval_raw_of, tier_fields as _queue_tier_fields
from helpers.case_access import require_case
from helpers.financial_mask import money_visible
from modules.case import material_guard as MG
from modules.case import material_notify as MN
from modules.case import material_payment as MP
from modules.case.quotations import SQL_DEAL_TAG

router = APIRouter()


def _http(e: MP.MaterialPaymentError) -> HTTPException:
    return HTTPException(e.status, e.message)


def _load_case(conn, quote_no: str):
    q = conn.execute("SELECT data_json, customer_name, project_name, sales_person_id, sales_person, assigned_user_ids, %s AS deal_tag"
                     " FROM quotations WHERE quote_no=?" % SQL_DEAL_TAG, (quote_no,)).fetchone()
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
    raise HTTPException(404, "找不到這筆叫料")


def _need_edit(user):
    if not money_visible(user):
        raise HTTPException(403, "此帳號沒有財務檢視權限，不可操作叫料匯款申請")
    if not MG.can_edit_orders(user):
        raise HTTPException(403, "只有管理員或專案經理可以操作叫料匯款申請")


def _mask(n) -> str:
    n = str(n or "")
    return "" if not n else ("****" + n[-4:] if len(n) > 4 else "****")


def _public(conn, row) -> dict:
    """申請的對外形狀：收款帳戶只回遮罩；含付款明細與累計。"""
    sn = MP.snapshot_of(row)
    try:
        appr = json.loads(row.get("approval_json") or "{}")
    except (TypeError, ValueError):
        appr = {}
    tiers = appr.get("tiers") or []
    ct = appr.get("currentTier") or 0
    cur = [a.get("displayName") or a.get("username") for a in (tiers[ct].get("approvers") or [])] if tiers and ct < len(tiers) else []
    lines = MP.lines_of(conn, row["id"])
    paid = round(sum(float(x["amount"] or 0) for x in lines), 2)
    return {"id": row["id"], "docCode": row["doc_code"], "quoteNo": row["quote_no"], "itemId": row["item_id"], "seq": row["seq"], "status": row["status"],
            "amount": float(row["amount_approved"] or 0), "paid": paid, "remaining": round(float(row["amount_approved"] or 0) - paid, 2),
            "supplierId": row["supplier_id"], "supplierName": sn.get("supplierName") or "", "supplierCode": sn.get("supplierCode") or "",
            "payee": {"bankCode": sn.get("bankCode") or "", "bankName": sn.get("bankName") or "", "bankAccountName": sn.get("bankAccountName") or "",
                      "bankAccountNumber": _mask(sn.get("bankAccountNumber"))},
            "overCapReason": row["over_cap_reason"] or "", "createdBy": row["created_by"], "createdAt": row["created_at"], "approvedAt": row["approved_at"],
            "requestedBy": appr.get("requestedByDisplay") or appr.get("requestedBy") or "", "tierCount": len(tiers), "currentTier": ct, "currentApprovers": cur,
            "rejectReason": appr.get("rejectReason") if row["status"] == MP.S_RETURNED else "", "voidReason": row["void_reason"] if row["status"] == MP.S_VOID else "",
            "lines": [{"id": x["id"], "paidAt": x["paid_at"], "amount": float(x["amount"] or 0), "fee": float(x["fee"] or 0), "review": x["remit_review"] or ""} for x in lines]}


def _info(row, q, quote_no):
    sn = MP.snapshot_of(row)
    return {"docCode": row["doc_code"], "quoteNo": quote_no, "itemName": sn.get("itemName") or ""}


# ── 讀 ───────────────────────────────────────────────────────────────

@router.get("/api/quotations/{quote_no}/material-payments")
def list_payments(quote_no: str, authorization: str = Header(None)):
    """這個案件所有叫料的匯款申請與額度 `{orders: {itemId: {quota, payments[]}}}`。收款帳戶只回遮罩。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        if not money_visible(user):
            return {"quoteNo": quote_no, "moneyMasked": True, "orders": {}}
        out = {}
        for o in _orders(q):
            iid = str(o.get("itemId"))
            out[iid] = {"quota": MP.quota_summary(conn, quote_no, o), "payments": [_public(conn, p) for p in MP.list_for_order(conn, quote_no, iid)]}
        return {"quoteNo": quote_no, "moneyMasked": False, "orders": out}
    finally:
        conn.close()


@router.get("/api/material-suppliers")
def supplier_picker(authorization: str = Header(None)):
    """供應商選單（只回 id／code／name；`GET /api/suppliers` 對非 admin 回空，不放寬它）。需能編輯叫料（admin 以上或專案經理）。"""
    user = _require_user(authorization)
    if not MG.can_edit_orders(user):
        raise HTTPException(403, "只有管理員或專案經理可以選擇供應商")
    conn = get_db()
    try:
        return {"suppliers": [{"id": r["id"], "code": r["code"] or "", "name": r["name"] or ""}
                              for r in conn.execute("SELECT id, code, name FROM suppliers ORDER BY name, id").fetchall()]}
    finally:
        conn.close()


# ── 寫 ───────────────────────────────────────────────────────────────

def _notify_after(event, info, res, reason=""):
    try:
        if event == "submitted":
            for u in res.get("firstApprovers") or []:
                _notify(u, "material_payment_approval_request", info["docCode"], info["quoteNo"], "叫料匯款申請 %s 需要您簽核" % info["docCode"])
            MN.fire_payment("submitted", info, approvers=res.get("firstApprovers"))
        elif event == "next_tier":
            for u in res.get("nextApprovers") or []:
                _notify(u, "material_payment_approval_request", info["docCode"], info["quoteNo"], "叫料匯款申請 %s 需要您簽核" % info["docCode"])
            MN.fire_payment("next_tier", info, approvers=res.get("nextApprovers"), tier_no=res.get("tierNo", 0), total_tiers=res.get("totalTiers", 0))
        elif event == "approved":
            if res.get("requester"):
                _notify(res["requester"], "material_payment_approved", info["docCode"], info["quoteNo"], "叫料匯款申請 %s 已核准，已交給出納" % info["docCode"])
            MN.fire_payment("approved", info, requester=res.get("requester") or "")
        elif event == "returned":
            if res.get("requester"):
                _notify(res["requester"], "material_payment_returned", info["docCode"], info["quoteNo"], "叫料匯款申請 %s 已被退回：%s" % (info["docCode"], reason))
            MN.fire_payment("returned", info, requester=res.get("requester") or "", reason=reason)
    except Exception:                                                              # noqa: BLE001
        pass


@router.post("/api/quotations/{quote_no}/material-orders/{item_id}/payments")
def create_payment(quote_no: str, item_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """開一張匯款申請（草稿）。金額不帶＝剩餘額度；超過額度 ⇒ 409（superadmin 可帶 `overCapReason` 覆寫）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        _need_edit(user)
        order = _order(q, item_id)
        try:
            row = MP.create(conn, quote_no, order, user, body or {})
        except MP.MaterialPaymentError as e:
            raise _http(e)
        conn.commit()
        res = _public(conn, row)
    finally:
        conn.close()
    _audit(_tok(authorization), "material_payment.create", "quotation", quote_no,
           "叫料匯款申請 %s（%s）建立（第 %d 張）" % (res["docCode"], order.get("itemName") or "", res["seq"]),
           {"docCode": res["docCode"], "seq": res["seq"], "overCap": bool(res["overCapReason"])})
    return {"ok": True, "payment": res}


def _row_and_case(conn, pid):
    row = MP.get(conn, pid)
    if row is None:
        raise HTTPException(404, "找不到這張匯款申請")
    q = _load_case(conn, row["quote_no"])
    return row, q


@router.patch("/api/material-payments/{pid}")
def update_payment(pid: int, body: dict = Body(default={}), authorization: str = Header(None)):
    """修改草稿／已退回的申請（金額、供應商、收款帳戶）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        row, q = _row_and_case(conn, pid)
        require_case(user, q, row["quote_no"])
        _need_edit(user)
        order = _order(q, row["item_id"])
        try:
            new = MP.update_draft(conn, pid, order, user, body or {})
        except MP.MaterialPaymentError as e:
            raise _http(e)
        conn.commit()
        res = _public(conn, new)
    finally:
        conn.close()
    _audit(_tok(authorization), "material_payment.update", "quotation", row["quote_no"], "叫料匯款申請 %s 修改" % res["docCode"], {"docCode": res["docCode"]})
    return {"ok": True, "payment": res}


@router.post("/api/material-payments/{pid}/submit")
def submit_payment(pid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        row, q = _row_and_case(conn, pid)
        require_case(user, q, row["quote_no"])
        _need_edit(user)
        order = _order(q, row["item_id"])
        try:
            res = MP.submit(conn, pid, order, user)
        except MP.MaterialPaymentError as e:
            raise _http(e)
        row = MP.get(conn, pid)
        conn.commit()
        info = _info(row, q, row["quote_no"])
    finally:
        conn.close()
    _audit(_tok(authorization), "material_payment.submit" if not res["autoApproved"] else "material_payment.auto_approve", "quotation", row["quote_no"],
           "叫料匯款申請 %s %s" % (info["docCode"], "送審" if not res["autoApproved"] else "未設定簽核層，直接核准"),
           {"docCode": info["docCode"], "tierCount": res["tierCount"], "status": res["status"]})
    if res["autoApproved"]:
        _notify_after("approved", info, {"requester": user["username"]})
    else:
        _notify_after("submitted", info, res)
        try:
            conn2 = get_db()
            try:
                tiers = (json.loads(MP.get(conn2, pid)["approval_json"] or "{}").get("tiers") or [])
                notify_org_chain_notice(conn2, tiers, user["username"], info["docCode"], row["quote_no"],
                                        "叫料匯款申請 %s 由 %s 依組織職權自行簽核，知會您" % (info["docCode"], user.get("display_name") or user["username"]),
                                        type_="material_payment_approval_notice")
            finally:
                conn2.close()
        except Exception:                                                          # noqa: BLE001
            pass
    return {"ok": True, "status": res["status"], "docCode": info["docCode"], "tierCount": res["tierCount"], "autoApproved": res["autoApproved"]}


@router.post("/api/material-payments/{pid}/approve")
def approve_payment(pid: int, body: dict = Body(default={}), authorization: str = Header(None)):
    """核准當層；全部層過了才「已核准」（交給出納）。能不能簽由是否為當層簽核人決定。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        row, q = _row_and_case(conn, pid)
        order = _order(q, row["item_id"])
        try:
            res = MP.approve(conn, pid, order, user, comment=(body or {}).get("comment") or "", cascade=bool((body or {}).get("cascade")))
        except MP.MaterialPaymentError as e:
            raise _http(e)
        row = MP.get(conn, pid)
        conn.commit()
        info = _info(row, q, row["quote_no"])
    finally:
        conn.close()
    _audit(_tok(authorization), "material_payment.approve", "quotation", row["quote_no"], "叫料匯款申請 %s 核准 → %s" % (info["docCode"], res["status"]),
           {"docCode": info["docCode"], "status": res["status"], "tier": res["currentTier"]})
    _notify_after("approved" if res["done"] else "next_tier", info, res)
    return {"ok": True, "status": res["status"], "currentTier": res["currentTier"]}


@router.post("/api/material-payments/{pid}/reject")
def reject_payment(pid: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        row, q = _row_and_case(conn, pid)
        try:
            res = MP.reject(conn, pid, user, (body or {}).get("reason"))
        except MP.MaterialPaymentError as e:
            raise _http(e)
        row = MP.get(conn, pid)
        conn.commit()
        info = _info(row, q, row["quote_no"])
    finally:
        conn.close()
    _audit(_tok(authorization), "material_payment.reject", "quotation", row["quote_no"], "叫料匯款申請 %s 被退回：%s" % (info["docCode"], res["reason"]),
           {"docCode": info["docCode"], "reason": res["reason"]})
    _notify_after("returned", info, res, reason=res["reason"])
    return {"ok": True, "status": res["status"]}


@router.post("/api/material-payments/{pid}/withdraw")
def withdraw_payment(pid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        row, q = _row_and_case(conn, pid)
        require_case(user, q, row["quote_no"])
        try:
            MP.withdraw(conn, pid, user)
        except MP.MaterialPaymentError as e:
            raise _http(e)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "material_payment.withdraw", "quotation", row["quote_no"], "叫料匯款申請 %s 撤回" % row["doc_code"], {"docCode": row["doc_code"]})
    return {"ok": True, "status": MP.S_DRAFT}


@router.post("/api/material-payments/{pid}/void")
def void_payment(pid: int, body: dict = Body(default={}), authorization: str = Header(None)):
    """作廢（額度釋出）：沒有付款明細的草稿／已退回／已核准申請；理由必填。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        row, q = _row_and_case(conn, pid)
        require_case(user, q, row["quote_no"])
        try:
            MP.void(conn, pid, user, (body or {}).get("reason"))
        except MP.MaterialPaymentError as e:
            raise _http(e)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "material_payment.void", "quotation", row["quote_no"], "叫料匯款申請 %s 作廢：%s" % (row["doc_code"], (body or {}).get("reason") or ""),
           {"docCode": row["doc_code"]})
    return {"ok": True, "status": MP.S_VOID}


# ── 簽核佇列提供者（IP-10 `approval.queue_items`／IP-93 `approval.detail`）────────────────────────────

def queue_items(conn) -> list:
    """待簽核的叫料匯款申請（待審核／簽核中）。自帶 `typeLabel／openUrl／approveUrl／rejectUrl／rejectField`；佇列上的「單號」＝匯款申請單號。
    **收款帳戶不進佇列**。"""
    out = []
    for r in conn.execute("SELECT p.*, q.customer_name, q.project_name FROM case_material_payments p LEFT JOIN quotations q ON q.quote_no = p.quote_no"
                          " WHERE p.status IN ('待審核','簽核中') ORDER BY p.id DESC").fetchall():
        raw = _approval_raw_of(r["approval_json"], MP.DOC_TYPE, r["doc_code"])
        if raw is None:
            continue
        f = _queue_tier_fields(raw)
        sn = MP.snapshot_of(dict(r))
        base = "/api/material-payments/%d" % r["id"]
        out.append({
            "type": MP.DOC_TYPE, "typeLabel": MP.DOC_LABEL, "docCode": r["doc_code"], "quoteNo": r["doc_code"],
            "customer": r["customer_name"] or "", "projectName": sn.get("itemName") or "", "total": float(r["amount_approved"] or 0),
            "quoteDate": (f["requestedAt"] or "")[:10], "salesPerson": "", "requestedBy": f["requestedBy"],
            "requestedByDisplay": f["requestedByDisplay"], "requestedAt": f["requestedAt"], "isEditApproval": False, "reasons": [],
            "tiers": f["tiers"], "currentTier": f["currentTier"], "tierCount": f["tierCount"], "currentApprovers": f["currentApprovers"],
            "linkedQuoteNo": r["quote_no"], "openUrl": "case-management.html?q=%s" % r["quote_no"],
            "approveUrl": base + "/approve", "rejectUrl": base + "/reject", "rejectField": "reason",
        })
    return out


def detail(conn, doc_no):
    """`approval.detail`（name＝material_payment）：簽核人看的詳情（單號、案件、品名、供應商、申請金額、第幾張、已付累計）。帳戶不放（只放遮罩的末四碼）。"""
    r = conn.execute("SELECT * FROM case_material_payments WHERE doc_code=?", (doc_no,)).fetchone()
    if not r:
        raise HTTPException(404, "匯款申請不存在")
    row = dict(r)
    sn = MP.snapshot_of(row)
    fields = [{"label": "單號", "value": row["doc_code"]}, {"label": "案件", "value": row["quote_no"]}, {"label": "品名", "value": sn.get("itemName") or "—"},
              {"label": "供應商", "value": sn.get("supplierName") or "—"}, {"label": "第幾張申請", "value": str(row["seq"])},
              {"label": "叫料單小計", "value": format(float(sn.get("totalPrice") or 0), ",.0f")},
              {"label": "本次申請金額", "value": format(float(row["amount_approved"] or 0), ",.0f")},
              {"label": "收款帳號", "value": _mask(sn.get("bankAccountNumber")) or "—"}]
    if row["over_cap_reason"]:
        fields.append({"label": "超額覆寫理由", "value": row["over_cap_reason"]})
    return {"quoteNo": row["quote_no"], "approvalRaw": row["approval_json"], "title": "叫料匯款 %s" % row["doc_code"], "fields": fields, "items": [], "files": []}
