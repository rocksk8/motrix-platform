"""承攬商匯款申請：已驗收或已完工的承攬商派發（1:1）匯出給財務單位辦理匯款的申請。
2026-08-20 使用者實測後放寬：原本僅「完工」可申請，改為「已驗收」或「完工」皆可，
因為實務上派發常停在已驗收就要請款，不一定會再手動切到完工狀態。

獨立簽核流程（system_settings key: contractor_voucher_approval_flow），機制比照
出貨單（routers/shipping_notes.py）的 tiers 依序簽核，但「已核准」之後多一個
「已匯款」財務結案標記（is_paid，獨立於 status，比照出貨單「已核准」跟「已回簽」
是兩個獨立狀態的做法）。

承攬商/銀行帳戶/派發品項於建立當下寫入 snapshot_json 凍結快照——之後
vendor_contractors 或 contractor_dispatches 本身異動不會回頭改到已產生的申請。
"""
import json
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Body, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel, model_validator

from db import get_db, next_entity_code, spawn_bg_thread
from helpers import (
    _require_user, _tok, _audit, _notify, _get_setting, _set_setting, _purge_notifications,
    notify_module_activity, notify_contractor_voucher_submitted, notify_contractor_voucher_next_tier,
    notify_contractor_voucher_approved, notify_contractor_voucher_returned,
    active_tiers as _active_tiers, current_tier_idx as _current_tier_idx,
    setting_to_active_tiers as _setting_to_active_tiers,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    UnresolvedManagerError, resolve_active_flow_setting,
)
from pdf_gen import generate_contractor_voucher_pdf_bytes, _generate_contractor_voucher_pdf

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class VoucherCreateIn(BaseModel):
    dispatch_id: int


class ApprovalFlowApprover(BaseModel):
    sourceType:   Optional[str] = None
    departmentId: Optional[int] = None
    divisionId:   Optional[int] = None
    userId:       Optional[int] = None
    username:     Optional[str] = None
    displayName:  Optional[str] = None

    @model_validator(mode="after")
    def _check_shape(self):
        if self.sourceType == "department_manager":
            if not self.departmentId:
                raise ValueError("department_manager 簽核層需要指定 departmentId")
        elif self.sourceType == "division_manager":
            if not self.divisionId:
                raise ValueError("division_manager 簽核層需要指定 divisionId")
        elif not (self.userId and self.username):
            raise ValueError("手動指定的簽核人需要 userId／username")
        return self

class ApprovalFlowTier(BaseModel):
    order:     int = 0
    approvers: List[ApprovalFlowApprover] = []

class ApprovalFlowSettings(BaseModel):
    tiers: List[ApprovalFlowTier] = []
    includeSubmitterManagerTier: bool = True


# ── Approval tier helpers（純邏輯部分共用 helpers/tiered_approval.py，見上方 import）──

def _require_admin(user: dict):
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")


def _voucher_public(row, include_snapshot: bool = True) -> dict:
    d = dict(row)
    snap = json.loads(d.get("snapshot_json") or "{}")
    approval = (json.loads(d.get("data_json") or "{}") or {}).get("approval") or {}
    out = {
        "id":            d["id"],
        "voucherNo":     d["voucher_no"],
        "dispatchId":    d["dispatch_id"],
        "quoteNo":       d["quote_no"],
        "vendorId":      d.get("vendor_id"),
        "vendorName":    snap.get("vendorName", ""),
        "status":        d["status"] or "草稿",
        "grandTotal":    snap.get("grandTotal", 0),
        "payableDate":   snap.get("payableDate", ""),
        "bankAccountName":   snap.get("bankAccountName", ""),
        "bankAccountNumber": snap.get("bankAccountNumber", ""),
        "bankPassbookImage": snap.get("bankPassbookImage", ""),
        "invoiceFiles":  snap.get("invoiceFiles", []),
        "isPaid":        bool(d.get("is_paid")),
        "paidBy":        d.get("paid_by") or "",
        "paidAt":        d.get("paid_at") or "",
        "paidLog":       json.loads(d.get("paid_log") or "[]"),
        "exportCount":   d.get("export_count") or 0,
        "exportLog":     json.loads(d.get("export_log") or "[]"),
        "approval":      approval,
        "createdBy":     d.get("created_by") or "",
        "createdAt":     d.get("created_at") or "",
        "updatedAt":     d.get("updated_at") or "",
    }
    if include_snapshot:
        out["snapshot"] = snap
    return out


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/contractor-vouchers")
def list_contractor_vouchers(quote_no: Optional[str] = None, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    if quote_no:
        rows = conn.execute(
            "SELECT * FROM contractor_payment_vouchers WHERE quote_no=? ORDER BY created_at DESC",
            (quote_no,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM contractor_payment_vouchers ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    conn.close()
    return [_voucher_public(r, include_snapshot=False) for r in rows]


@router.get("/api/contractor-vouchers/{voucher_no}")
def get_contractor_voucher(voucher_no: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"申請 {voucher_no} 不存在")
    return _voucher_public(row)


@router.post("/api/contractor-vouchers", status_code=201)
def create_contractor_voucher(body: VoucherCreateIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    # BEGIN IMMEDIATE：把「查詢是否已有申請」跟「寫入新申請」鎖進同一個交易，
    # 避免兩個近乎同時送出的請求都通過重複檢查、對同一筆派發各自建立一張申請
    # （dispatch_id UNIQUE 仍是最後防線，但這裡先在應用層就把窗口關掉）。
    conn.execute("BEGIN IMMEDIATE")
    dispatch = conn.execute(
        "SELECT d.*, v.name AS vendor_name, v.tax_id AS vendor_tax_id, v.data_json AS vendor_data_json "
        "FROM contractor_dispatches d LEFT JOIN vendor_contractors v ON v.id=d.vendor_id WHERE d.id=?",
        (body.dispatch_id,)
    ).fetchone()
    if not dispatch:
        conn.close()
        raise HTTPException(404, "找不到對應的承攬商派發紀錄")
    if dispatch["status"] not in ("accepted", "completed"):
        conn.close()
        raise HTTPException(409, "僅「已驗收」或「完工」狀態的派發可產生匯款申請")
    existing = conn.execute(
        "SELECT voucher_no FROM contractor_payment_vouchers WHERE dispatch_id=?", (body.dispatch_id,)
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(409, f"此派發已產生匯款申請（{existing['voucher_no']}）")

    keys = dispatch.keys()
    items = json.loads(dispatch["items_json"] or "[]")
    personnel = json.loads(dispatch["personnel_json"] or "[]") if "personnel_json" in keys else []
    personnel_total = sum(float(p.get("amount", 0) or 0) for p in personnel)
    total = float(dispatch["total_amount"] or 0)
    if not total and items:
        total = sum(float(it.get("amount", 0) or 0) for it in items)
    tax_rate = float(dispatch["tax_rate"]) if "tax_rate" in keys and dispatch["tax_rate"] is not None else 0.05
    tax_amount = round(total * tax_rate)
    total_with_tax = total + tax_amount

    # 外包名單人員（personnel_json）本身只快照 id/name/amount/note，不含銀行帳戶——
    # 這裡在「建立申請當下」另外去外包名冊（contractors 表）撈一次目前的銀行帳戶／
    # 存簿影本，跟承攬商本身的銀行資訊一樣寫進 snapshot_json 凍結，之後 contractors
    # 表異動不會回頭改變已產生的申請。查無資料（例如人員已被刪除）就留空，不擋建立。
    personnel_ids = [p["id"] for p in personnel if p.get("id")]
    personnel_bank = {}
    if personnel_ids:
        ph = ",".join("?" * len(personnel_ids))
        for prow in conn.execute(
            f"SELECT id, bank_code, bank_name, bank_branch, bank_account_name, bank_account_number, "
            f"bank_passbook_image FROM contractors WHERE id IN ({ph})", personnel_ids
        ).fetchall():
            personnel_bank[prow["id"]] = dict(prow)
    personnel_snapshot = []
    for p in personnel:
        pb = personnel_bank.get(p.get("id"), {})
        personnel_snapshot.append({
            **p,
            "bankCode":          pb.get("bank_code", ""),
            "bankName":          pb.get("bank_name", ""),
            "bankBranch":        pb.get("bank_branch", ""),
            "bankAccountName":   pb.get("bank_account_name", ""),
            "bankAccountNumber": pb.get("bank_account_number", ""),
            "bankPassbookImage": pb.get("bank_passbook_image", ""),
        })

    vendor_data = json.loads(dispatch["vendor_data_json"] or "{}") if dispatch["vendor_data_json"] else {}
    snapshot = {
        "vendorName":        dispatch["vendor_name"] or "",
        "vendorTaxId":       dispatch["vendor_tax_id"] or "",
        "bankCode":          vendor_data.get("bankCode", ""),
        "bankName":          vendor_data.get("bankName", ""),
        "bankBranch":        vendor_data.get("bankBranch", ""),
        "bankAccountName":   vendor_data.get("bankAccountName", ""),
        "bankAccountNumber": vendor_data.get("bankAccountNumber", ""),
        "bankPassbookImage": vendor_data.get("bankPassbookImage", ""),
        "invoiceNo":         (dispatch["invoice_no"] if "invoice_no" in keys else "") or "",
        "payableDate":       (dispatch["payable_date"] if "payable_date" in keys else "") or "",
        "invoiceFiles":      json.loads(dispatch["invoice_files_json"] or "[]") if "invoice_files_json" in keys else [],
        "dispatchDate":      dispatch["dispatch_date"] or "",
        "scope":             dispatch["scope"] or "",
        "items":             items,
        "personnel":         personnel_snapshot,
        "totalAmount":       total,
        "taxRate":           tax_rate,
        "taxAmount":         tax_amount,
        "totalWithTax":      total_with_tax,
        "personnelTotal":    personnel_total,
        "grandTotal":        total_with_tax + personnel_total,
    }

    now = datetime.now().isoformat()
    voucher_no = next_entity_code(conn, "contractor_payment_vouchers", "PV", code_col="voucher_no")
    conn.execute(
        "INSERT INTO contractor_payment_vouchers "
        "(voucher_no, dispatch_id, quote_no, vendor_id, status, snapshot_json, data_json, "
        "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (voucher_no, body.dispatch_id, dispatch["quote_no"], dispatch["vendor_id"], "草稿",
         json.dumps(snapshot, ensure_ascii=False), "{}", user["username"], now, now)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "contractor_voucher.create", "contractor_payment_voucher", voucher_no,
           f"{voucher_no}（{snapshot['vendorName'] or '外包人員點工'}）")
    notify_module_activity("承攬商匯款申請", "建立", user.get("display_name") or user["username"],
                            f"{voucher_no}（{snapshot['vendorName']}）", "case-management.html")
    return {"voucher_no": voucher_no, "created_at": now}


@router.delete("/api/contractor-vouchers/{voucher_no}")
def delete_contractor_voucher(voucher_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT status FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "申請不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可刪除")
    conn.execute("DELETE FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,))
    conn.commit()
    conn.close()
    _purge_notifications(voucher_no, ['contractor_voucher_approval_request', 'contractor_voucher_approved',
                                       'contractor_voucher_returned', 'approval_reminder'])
    _audit(_tok(authorization), "contractor_voucher.delete", "contractor_payment_voucher", voucher_no, voucher_no)
    notify_module_activity("承攬商匯款申請", "刪除", user.get("display_name") or user["username"],
                            voucher_no, "case-management.html")
    return {"ok": True}


# ── 簽核流程 ──────────────────────────────────────────────────────────────────

@router.post("/api/contractor-vouchers/{voucher_no}/submit")
def submit_contractor_voucher(voucher_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT status, data_json, snapshot_json FROM contractor_payment_vouchers WHERE voucher_no=?",
        (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "申請不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可送出審核")

    snap  = json.loads(row["snapshot_json"] or "{}")
    vname = snap.get("vendorName") or "外包人員點工"
    d     = json.loads(row["data_json"] or "{}")
    now   = datetime.now().isoformat()

    flow_setting = resolve_active_flow_setting("contractor_voucher")
    try:
        active_tiers = _setting_to_active_tiers(flow_setting, conn, user["username"])
    except UnresolvedManagerError as e:
        conn.close()
        raise HTTPException(400, str(e))
    d["approval"] = {
        "requestedBy":        user["username"],
        "requestedByDisplay": user.get("display_name") or user["username"],
        "requestedAt":        now,
        "tiers":              active_tiers,
        "currentTier":        0,
    }

    first_tier_usernames = []
    if active_tiers:
        for a in active_tiers[0].get("approvers") or []:
            _notify(a["username"], "contractor_voucher_approval_request", voucher_no, voucher_no,
                    f"承攬商匯款申請 {voucher_no}（{vname}）需要您簽核")
            first_tier_usernames.append(a["username"])

    conn.execute(
        "UPDATE contractor_payment_vouchers SET status='待審核', data_json=?, updated_at=? WHERE voucher_no=?",
        (json.dumps(d, ensure_ascii=False), now, voucher_no)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "contractor_voucher.submit", "contractor_payment_voucher", voucher_no,
           f"{voucher_no}（{vname}）", {"tierCount": len(active_tiers)})
    if active_tiers:
        notify_contractor_voucher_submitted(voucher_no, vname, first_tier_usernames)
    return {"ok": True, "status": "待審核"}


@router.post("/api/contractor-vouchers/{voucher_no}/approve")
def approve_contractor_voucher(voucher_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    # 比照 quotations.py：能否簽核完全由「是否為當層簽核人員」決定，不額外要求
    # 簽核人帳號角色必須是 admin/superadmin——簽核設定頁面允許加入任何角色的
    # 使用者當簽核人，這裡若硬性擋 admin 會讓非管理員角色的簽核人永遠卡死無法簽核。
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, snapshot_json FROM contractor_payment_vouchers "
        "WHERE voucher_no=? AND status IN ('待審核','簽核中')",
        (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"申請 {voucher_no} 不存在或不在待審核狀態")
    snap  = json.loads(row["snapshot_json"] or "{}")
    vname = snap.get("vendorName") or "外包人員點工"
    d     = json.loads(row["data_json"] or "{}")
    appr  = d.get("approval") or {}
    tiers = _active_tiers(appr)
    now   = datetime.now().isoformat()

    if tiers:
        ct_idx = _current_tier_idx(appr)
        ok, status_code, err_msg = check_approve_permission(tiers, ct_idx, user["username"], conn=conn)
        if not ok:
            conn.close()
            raise HTTPException(status_code, err_msg)
        tier      = tiers[ct_idx]
        approvers = tier.get("approvers") or []
        first_pending = next((a for a in approvers if a.get("status") != "approved"), None)

        first_pending["status"]     = "approved"
        first_pending["approvedAt"] = now

        tier_done = all(a.get("status") == "approved" for a in approvers)
        next_tier_usernames = []
        if tier_done:
            appr["currentTier"] = ct_idx + 1
            all_done = (ct_idx + 1) >= len(tiers)
            if not all_done:
                for na in tiers[ct_idx + 1].get("approvers") or []:
                    _notify(na["username"], "contractor_voucher_approval_request", voucher_no, voucher_no,
                            f"承攬商匯款申請 {voucher_no}（{vname}）輪到您簽核（第 {ct_idx + 2} 層 / 共 {len(tiers)} 層）")
                    next_tier_usernames.append(na["username"])
                notify_contractor_voucher_next_tier(voucher_no, vname, ct_idx + 2, len(tiers), next_tier_usernames)
        else:
            all_done = False
        appr["tiers"] = tiers
    else:
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")
        _global_flow  = resolve_active_flow_setting("contractor_voucher")
        try:
            _global_tiers = _setting_to_active_tiers(_global_flow, conn, appr.get("requestedBy"))
        except UnresolvedManagerError as e:
            conn.close()
            raise HTTPException(400, str(e))
        if _global_tiers:
            conn.close()
            raise HTTPException(403, "系統已設定簽核流程，此申請缺少簽核層資料，請重新送審")
        self_block_msg = check_no_tier_self_approval(conn, appr, user)
        if self_block_msg:
            conn.close()
            raise HTTPException(403, self_block_msg)
        all_done = True

    if all_done:
        appr["approvedBy"]        = user["username"]
        appr["approvedByDisplay"] = user.get("display_name") or user["username"]
        appr["approvedAt"]        = now
        appr["status"]            = "approved"
        d["approval"] = appr
        conn.execute(
            "UPDATE contractor_payment_vouchers SET status='已核准', data_json=?, updated_at=? WHERE voucher_no=?",
            (json.dumps(d, ensure_ascii=False), now, voucher_no)
        )
        conn.commit()
        approver_name = appr.get("approvedByDisplay") or user["username"]
        spawn_bg_thread(_generate_contractor_voucher_pdf, args=(voucher_no, approver_name, '簽核'))
        requester = appr.get("requestedBy")
        if requester:
            _notify(requester, "contractor_voucher_approved", voucher_no, voucher_no,
                    f"承攬商匯款申請 {voucher_no}（{vname}）已核准")
            notify_contractor_voucher_approved(voucher_no, vname, approver_name, requester)
    else:
        d["approval"] = appr
        new_status = "簽核中" if (appr.get("currentTier") or 0) > 0 else "待審核"
        conn.execute(
            "UPDATE contractor_payment_vouchers SET status=?, data_json=?, updated_at=? WHERE voucher_no=?",
            (new_status, json.dumps(d, ensure_ascii=False), now, voucher_no)
        )
        conn.commit()

    conn.close()
    _audit(_tok(authorization), "contractor_voucher.approve", "contractor_payment_voucher", voucher_no,
           f"{voucher_no}（{vname}）", {"allDone": all_done})
    return {"ok": True, "allDone": all_done}


@router.post("/api/contractor-vouchers/{voucher_no}/revoke-approval")
def revoke_contractor_voucher_approval(voucher_no: str, body: dict = Body(default={}),
                                       authorization: str = Header(None)):
    """撤銷已核准的申請，退回草稿。已匯款（財務已確認撥款）的申請不可撤銷——
    比照出貨單「已回簽不可撤銷」的規則，錢已經實際匯出就不應該讓系統這邊反悔。"""
    user = _require_user(authorization)
    _require_admin(user)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, snapshot_json, is_paid FROM contractor_payment_vouchers "
        "WHERE voucher_no=? AND status='已核准'",
        (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"申請 {voucher_no} 不存在或不在已核准狀態")
    if row["is_paid"]:
        conn.close()
        raise HTTPException(409, "已匯款的申請不可撤銷核准")
    snap  = json.loads(row["snapshot_json"] or "{}")
    vname = snap.get("vendorName") or "外包人員點工"
    d = json.loads(row["data_json"] or "{}")
    appr = d.get("approval") or {}
    requester = appr.get("requestedBy")
    d.pop("approval", None)
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE contractor_payment_vouchers SET status='草稿', data_json=?, updated_at=? WHERE voucher_no=?",
        (json.dumps(d, ensure_ascii=False), now, voucher_no)
    )
    conn.commit()
    conn.close()
    _purge_notifications(voucher_no, ['contractor_voucher_approval_request', 'approval_reminder'])
    if requester:
        msg = f"承攬商匯款申請 {voucher_no}（{vname}）核准已被撤銷，請確認後重新送審" + (f"：{note}" if note else "")
        _notify(requester, "contractor_voucher_returned", voucher_no, voucher_no, msg)
        notify_contractor_voucher_returned(voucher_no, vname, note, requester)
    _audit(_tok(authorization), "contractor_voucher.revoke_approval", "contractor_payment_voucher", voucher_no,
           f"{voucher_no}（{vname}）", {"note": note})
    return {"ok": True}


@router.post("/api/contractor-vouchers/{voucher_no}/reject")
def reject_contractor_voucher(voucher_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    # 比照 quotations.py：退回權限由當層簽核人員判斷，不額外要求 admin 角色
    user = _require_user(authorization)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, snapshot_json FROM contractor_payment_vouchers "
        "WHERE voucher_no=? AND status IN ('待審核','簽核中')",
        (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"申請 {voucher_no} 不存在或不在待審核狀態")
    snap  = json.loads(row["snapshot_json"] or "{}")
    vname = snap.get("vendorName") or "外包人員點工"
    d     = json.loads(row["data_json"] or "{}")
    appr  = d.get("approval") or {}
    tiers = _active_tiers(appr)

    ct_idx = _current_tier_idx(appr)
    ok, status_code, err_msg = check_reject_permission(tiers, ct_idx, user, conn=conn)
    if not ok:
        conn.close()
        raise HTTPException(status_code, err_msg)

    now       = datetime.now().isoformat()
    requester = appr.get("requestedBy")
    d.pop("approval", None)
    conn.execute(
        "UPDATE contractor_payment_vouchers SET status='草稿', data_json=?, updated_at=? WHERE voucher_no=?",
        (json.dumps(d, ensure_ascii=False), now, voucher_no)
    )
    conn.commit()
    conn.close()
    _purge_notifications(voucher_no, ['contractor_voucher_approval_request', 'approval_reminder'])
    if requester:
        msg = f"承攬商匯款申請 {voucher_no}（{vname}）已退回，請確認後重新送審" + (f"：{note}" if note else "")
        _notify(requester, "contractor_voucher_returned", voucher_no, voucher_no, msg)
        notify_contractor_voucher_returned(voucher_no, vname, note, requester)
    _audit(_tok(authorization), "contractor_voucher.reject", "contractor_payment_voucher", voucher_no,
           f"{voucher_no}（{vname}）", {"note": note})
    return {"ok": True}


# ── PDF / 匯出紀錄 ────────────────────────────────────────────────────────────

@router.get("/api/contractor-vouchers/{voucher_no}/pdf-download")
def download_contractor_voucher_pdf(voucher_no: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT voucher_no FROM contractor_payment_vouchers WHERE voucher_no=?",
                        (voucher_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "申請不存在")
    try:
        pdf_bytes = generate_contractor_voucher_pdf_bytes(voucher_no)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"PDF 產生失敗：{e}")
    encoded = urlquote(f"{voucher_no}.pdf")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


@router.post("/api/contractor-vouchers/{voucher_no}/export")
def record_contractor_voucher_export(voucher_no: str, mode: str = "external", authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT export_count, export_log FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"申請 {voucher_no} 不存在")
    log   = json.loads(row["export_log"] or "[]")
    count = (row["export_count"] or 0) + 1
    log.append({
        "at": datetime.now().isoformat(), "mode": mode, "user": user["username"],
        "userDisplay": user.get("display_name") or user["username"], "count": count,
    })
    conn.execute("UPDATE contractor_payment_vouchers SET export_count=?, export_log=? WHERE voucher_no=?",
                 (count, json.dumps(log, ensure_ascii=False), voucher_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "contractor_voucher.export_pdf", "contractor_payment_voucher", voucher_no,
           f"{voucher_no} PDF 匯出（{mode}）by {user['username']}")
    return {"export_count": count, "log": log}


# ── 財務已匯款 toggle ─────────────────────────────────────────────────────────

@router.post("/api/contractor-vouchers/{voucher_no}/paid-toggle")
def toggle_paid(voucher_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """標記已匯款時可帶入 paid_at（YYYY-MM-DD，實際匯款日期，不一定等於操作
    當下的系統時間——財務常常是先在銀行完成匯款，之後才回系統標記）；不帶
    就沿用舊行為，退回今天。paid_log 裡的 "at"／updated_at 仍然是「這次操作
    本身發生的系統時間」，跟 paid_at（匯款發生的日期）是兩個不同概念，不要
    混用。"""
    user = _require_user(authorization)
    _require_admin(user)
    action = (body or {}).get("action", "")
    note   = (body or {}).get("note", "")
    if action not in ("pay", "unpay"):
        raise HTTPException(400, "action 必須為 pay 或 unpay")
    paid_at_value = date.today().isoformat()
    if action == "pay":
        raw_paid_at = (body or {}).get("paid_at") or ""
        if raw_paid_at:
            try:
                date.fromisoformat(raw_paid_at)
            except ValueError:
                raise HTTPException(400, f"匯款日期格式錯誤（{raw_paid_at}），需為 YYYY-MM-DD")
            paid_at_value = raw_paid_at
    conn = get_db()
    row = conn.execute(
        "SELECT status, is_paid, paid_log FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "申請不存在")
    if row["status"] != "已核准":
        conn.close()
        raise HTTPException(409, "僅已核准狀態可標記已匯款")
    is_paid = bool(row["is_paid"])
    if action == "pay" and is_paid:
        conn.close()
        raise HTTPException(409, "已匯款，無需重複標記")
    if action == "unpay" and not is_paid:
        conn.close()
        raise HTTPException(409, "尚未標記匯款")

    now = datetime.now().isoformat()
    log = json.loads(row["paid_log"] or "[]")
    log.append({
        "at": now, "username": user["username"], "userDisplay": user.get("display_name") or user["username"],
        "action": "paid" if action == "pay" else "unpaid", "note": note,
        **({"paidAt": paid_at_value} if action == "pay" else {}),
    })
    if action == "pay":
        conn.execute(
            "UPDATE contractor_payment_vouchers SET is_paid=1, paid_by=?, paid_at=?, paid_log=?, updated_at=? "
            "WHERE voucher_no=?",
            (user.get("display_name") or user["username"], paid_at_value,
             json.dumps(log, ensure_ascii=False), now, voucher_no)
        )
    else:
        conn.execute(
            "UPDATE contractor_payment_vouchers SET is_paid=0, paid_by='', paid_at='', paid_log=?, updated_at=? "
            "WHERE voucher_no=?",
            (json.dumps(log, ensure_ascii=False), now, voucher_no)
        )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), f"contractor_voucher.{action}", "contractor_payment_voucher", voucher_no,
           voucher_no, {"note": note, **({"paidAt": paid_at_value} if action == "pay" else {})})
    notify_module_activity("承攬商匯款申請", "已匯款" if action == "pay" else "取消已匯款",
                            user.get("display_name") or user["username"], voucher_no, "case-management.html",
                            detail=note or "")
    return {"ok": True, "is_paid": action == "pay", "paid_log": log}


# ── 簽核設定（獨立於報價單／出貨單）────────────────────────────────────────────

@router.get("/api/contractor-vouchers/settings/approval-flow")
def get_contractor_voucher_approval_flow(authorization: str = Header(None)):
    _require_user(authorization)
    return _get_setting("contractor_voucher_approval_flow", {"tiers": []}) or {"tiers": []}


@router.put("/api/contractor-vouchers/settings/approval-flow")
def set_contractor_voucher_approval_flow(body: ApprovalFlowSettings, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    total_approvers = sum(len(t.approvers) for t in body.tiers)
    value = {
        "tiers": [t.model_dump() for t in body.tiers],
        "includeSubmitterManagerTier": body.includeSubmitterManagerTier,
    }
    _set_setting("contractor_voucher_approval_flow", value)
    _audit(_tok(authorization), "settings.contractor_voucher_approval_flow.update", "settings",
           "contractor_voucher_approval_flow", "承攬商匯款申請簽核流程設定",
           {"tierCount": len(body.tiers), "approverCount": total_approvers,
            "includeSubmitterManagerTier": body.includeSubmitterManagerTier})
    return {"ok": True}
