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
import logging
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Body, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel, model_validator

from db import get_db, next_entity_code, spawn_bg_thread
from core.txn import begin_write, write_txn
from core import registry as _registry
from helpers import (
    _require_user, _tok, _audit, _notify, _get_setting, _set_setting, _purge_notifications,
    notify_module_activity, notify_contractor_voucher_submitted, notify_contractor_voucher_next_tier,
    notify_contractor_voucher_approved, notify_contractor_voucher_returned,
    active_tiers as _active_tiers, current_tier_idx as _current_tier_idx,
    setting_to_active_tiers as _setting_to_active_tiers,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    cascade_self_tiers, notify_org_chain_notice,
    UnresolvedManagerError, resolve_active_flow_setting, user_has_module,
    guard_case_access, require_any_module,

    can_see_financial, is_document_approver,
)
from pdf_gen import generate_contractor_voucher_pdf_bytes, _generate_contractor_voucher_pdf
from helpers.errors import trace_id
# X-VAT（2026-09-26）：金額一律四捨五入（內建 round() 是銀行家捨入：.5 取偶數）
from helpers.legal_params import round_half_up

router = APIRouter()
logger = logging.getLogger(__name__)

def _guard_voucher(conn, row, user):
    """單據層級守門（2026-09-13 模組權限稽核第四輪）。

    先前 `GET /{voucher_no}`、PDF 下載與檔案上傳/刪除都只要求登入，而單號是可預測的
    （前綴＋年月＋流水號），等於任何已登入帳號都能把別人案件的單據與金額撈出來。

    兩道：
    1. **案件層**——比照其他每案端點（`guard_case_access`）：案件業務／協作者／
       具案件管理模組／本單簽核人（含代理人）。
    2. **金額層**——`can_see_financial()`（使用者裁示：viewer／engineer 不該看到
       金額）。**本單簽核人例外**：看不到金額就沒辦法判斷該不該簽，擋他等於讓
       簽核流程停擺。
    """
    # 找不到母案件時不要變成 404：單據本身存在、只是母案件被刪或資料異常，
    # 對使用者顯示「報價單不存在」只會更難查。退回模組層級判斷。
    if conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (row["quote_no"],)).fetchone():
        guard_case_access(conn, row["quote_no"], user,
                          allow_module="case_manage", allow_approver=True)
    else:
        require_any_module(user, ('case_manage', 'finance', 'cashier', 'quotation'), "承攬商付款")
    if not can_see_financial(user) and not is_document_approver(row["data_json"], user, conn):
        try:
            conn.close()
        except Exception:
            pass
        raise HTTPException(403, "此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）")


def _visible_rows(rows, user, conn):
    """清單過濾：沒有財務可視權的人，只看得到「自己要簽的那幾張」。

    直接整支 403 會讓非管理員的簽核人連簽核佇列都打不開（他們正是要在那裡看到
    待簽單據）；整批放行又違背「viewer／engineer 不該看到金額」。折衷是過濾。
    """
    if can_see_financial(user):
        return rows
    return [r for r in rows if is_document_approver(r["data_json"], user, conn)]



# ── Models ────────────────────────────────────────────────────────────────────

class VoucherCreateIn(BaseModel):
    dispatch_id: int
    payable_date: Optional[str] = None


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
    """一張承攬商匯款申請的對外形狀。IP-14 `contractor_voucher.public`（M05 出納、M06 會計匯出）也用這一支。"""
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
        # MOTRIX 自己付款用的銀行帳戶（標記已匯款當下選的，不是上面 snapshot
        # 裡承攬商的收款帳戶，兩者是完全不同的概念，見 db.py::_m071_paid_bank_account）
        "paidBankAccountName": d.get("paid_bank_account_name") or "",
        "paidBankAccountCode": d.get("paid_bank_account_code") or "",
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


# ── 銀行帳戶預設值（2026-09-02 新增，見 accounting_export.py 檔頭「標記已付款/
#    已收款時的銀行帳戶預設值」說明）────────────────────────────────────────────

@router.get("/api/contractor-vouchers/last-paid-bank-account")
def get_last_paid_bank_account(vendor_id: Optional[int] = None, authorization: str = Header(None)):
    """查這個承攬商上一次「標記已匯款」用的銀行帳戶，供標記 Modal 開啟時預帶值。
    純讀取，找不到（vendor_id 未提供、或這個承攬商從沒被標記過已匯款、或舊資料
    沒填帳戶）一律回傳空字串，由前端接著退回系統預設帳戶。"""
    _require_user(authorization)
    if not vendor_id:
        return {"name": "", "acctCode": ""}
    conn = get_db()
    row = conn.execute(
        "SELECT paid_bank_account_name, paid_bank_account_code FROM contractor_payment_vouchers "
        "WHERE vendor_id=? AND is_paid=1 AND paid_bank_account_code != '' "
        "ORDER BY paid_at DESC LIMIT 1",
        (vendor_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {"name": "", "acctCode": ""}
    return {"name": row["paid_bank_account_name"], "acctCode": row["paid_bank_account_code"]}


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/contractor-vouchers")
def list_contractor_vouchers(quote_no: Optional[str] = None, authorization: str = Header(None)):
    # 2026-09-13（模組權限稽核）：帶 quote_no 就是「讀某一張案件的承攬商付款」——
    # `quote_no` 可列舉，先前只要求登入等於任何人都撈得到別人案件的單據與金額。
    # 不帶 quote_no 是跨案件總覽，改為管理員或具相關模組的人才看得到。
    user = _require_user(authorization)
    conn = get_db()
    if quote_no:
        guard_case_access(conn, quote_no, user, allow_module="case_manage")
    else:
        # `quotation` 也要收：簽核佇列（模組 quotation）就是用這支載入待簽的單據
        require_any_module(user, ('case_manage', 'finance', 'cashier', 'quotation'), "承攬商付款")
    if quote_no:
        rows = conn.execute(
            "SELECT * FROM contractor_payment_vouchers WHERE quote_no=? ORDER BY created_at DESC",
            (quote_no,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM contractor_payment_vouchers ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    rows = _visible_rows(rows, user, conn)
    conn.close()
    return [_voucher_public(r, include_snapshot=False) for r in rows]


@router.get("/api/contractor-vouchers/{voucher_no}")
def get_contractor_voucher(voucher_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"申請 {voucher_no} 不存在")
    _guard_voucher(conn, row, user)
    conn.close()
    return _voucher_public(row)


@router.post("/api/contractor-vouchers", status_code=201)
def create_contractor_voucher(body: VoucherCreateIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    # BEGIN IMMEDIATE：把「查詢是否已有申請」跟「寫入新申請」鎖進同一個交易，
    # 避免兩個近乎同時送出的請求都通過重複檢查、對同一筆派發各自建立一張申請
    # （dispatch_id UNIQUE 仍是最後防線，但這裡先在應用層就把窗口關掉）。
    with write_txn(conn):   # 拿寫鎖（helpers.quotations.begin_write）；區塊內任何例外 ⇒ rollback＋關連線（不留寫鎖）
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
            "SELECT voucher_no, quote_no, data_json FROM contractor_payment_vouchers WHERE dispatch_id=?", (body.dispatch_id,)
        ).fetchone()
        if existing:
            conn.close()
            raise HTTPException(409, f"此派發已產生匯款申請（{existing['voucher_no']}）")

        # 2026-08-31：使用者要求產生匯款申請當下就能直接填/改應付款日期，不用先
        # 跳去編輯派發紀錄。有帶就順便寫回派發本身（維持派發跟申請快照的日期
        # 一致），沒帶就沿用派發既有的 payable_date（可能是空的，也沒關係）。
        payable_date = dispatch["payable_date"] if "payable_date" in dispatch.keys() else ""
        if body.payable_date:
            try:
                date.fromisoformat(body.payable_date)
            except ValueError:
                conn.close()
                raise HTTPException(400, f"應付款日期格式錯誤（{body.payable_date}），需為 YYYY-MM-DD")
            payable_date = body.payable_date
            conn.execute(
                "UPDATE contractor_dispatches SET payable_date=? WHERE id=?", (payable_date, body.dispatch_id)
            )

        keys = dispatch.keys()
        items = json.loads(dispatch["items_json"] or "[]")
        personnel = json.loads(dispatch["personnel_json"] or "[]") if "personnel_json" in keys else []
        personnel_total = sum(float(p.get("amount", 0) or 0) for p in personnel)
        total = float(dispatch["total_amount"] or 0)
        if not total and items:
            total = sum(float(it.get("amount", 0) or 0) for it in items)
        tax_rate = float(dispatch["tax_rate"]) if "tax_rate" in keys and dispatch["tax_rate"] is not None else 0.05
        tax_amount = round_half_up(total, tax_rate)
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
            "payableDate":       payable_date or "",
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

    # 知會（2026-09-15）：整條簽核鏈都只有申請人本人時（他已在組織職權頂端），
    # 最高管理者不再被塞進簽核鏈，改收一則知會通知（仍可隨時以 superadmin 退回）。
    notify_org_chain_notice(conn, active_tiers, user["username"], voucher_no, voucher_no,
                            f"承攬商匯款申請 {voucher_no}（{vname}）由 "
                            f"{user.get('display_name') or user['username']} 依組織職權自行簽核，知會您",
                            type_="contractor_voucher_approval_notice")

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
        # 同一人連任多層時一次簽完（2026-09-15，見 helpers/tiered_approval.py::
        # plan_self_cascade()）：前端跳確認視窗問過才會帶 cascade=true，
        # 且只吃「剩下未簽核的只有他自己」的連續層，不會替別人做決定。
        cascaded = (cascade_self_tiers(tiers, ct_idx, user["username"], now, conn=conn)
                    if (tier_done and (body or {}).get("cascade")) else [])
        landed = ct_idx + 1 + len(cascaded)
        next_tier_usernames = []
        if tier_done:
            appr["currentTier"] = landed
            all_done = landed >= len(tiers)
            if not all_done:
                for na in tiers[landed].get("approvers") or []:
                    _notify(na["username"], "contractor_voucher_approval_request", voucher_no, voucher_no,
                            f"承攬商匯款申請 {voucher_no}（{vname}）輪到您簽核（第 {landed + 1} 層 / 共 {len(tiers)} 層）")
                    next_tier_usernames.append(na["username"])
                notify_contractor_voucher_next_tier(voucher_no, vname, landed + 1, len(tiers), next_tier_usernames)
        else:
            all_done = False
        appr["tiers"] = tiers
        _signed_tier_nos = [x + 1 for x in [ct_idx, *cascaded]]
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
        _signed_tier_nos = []

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
    return {"ok": True, "allDone": all_done, "signedTiers": _signed_tier_nos}


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
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT voucher_no, quote_no, data_json FROM contractor_payment_vouchers WHERE voucher_no=?",
                        (voucher_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "單據不存在")
    _guard_voucher(conn, row, user)
    conn.close()
    if not row:
        raise HTTPException(404, "申請不存在")
    try:
        pdf_bytes = generate_contractor_voucher_pdf_bytes(voucher_no)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        tid = trace_id()
        logger.exception("contractor_voucher pdf failed trace=%s", tid)
        raise HTTPException(500, f"PDF 產生失敗（代碼 {tid}）")
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
    # 2026-08-31（財務/出納權限分工）：標記已匯款是出納的執行動作，不是財務
    # 核准，額外放行具備 cashier 模組的使用者（不需要完整 admin 權限）——跟
    # 這個檔案其餘建立/送審/撤銷等「財務」動作的 _require_admin() 分開判斷，
    # 不能把 _require_admin() 本身改鬆，那些動作仍然只限 admin+。
    if user["role"] not in ("superadmin", "admin") and not user_has_module(user, "cashier"):
        raise HTTPException(403, "需要管理員或出納權限")
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
        bank_name = (body or {}).get("bank_account_name") or (body or {}).get("bankAccountName") or ""
        bank_code = (body or {}).get("bank_account_code") or (body or {}).get("bankAccountCode") or ""
        conn.execute(
            "UPDATE contractor_payment_vouchers SET is_paid=1, paid_by=?, paid_at=?, paid_log=?, "
            "paid_bank_account_name=?, paid_bank_account_code=?, updated_at=? WHERE voucher_no=?",
            (user.get("display_name") or user["username"], paid_at_value,
             json.dumps(log, ensure_ascii=False), bank_name, bank_code, now, voucher_no)
        )
    else:
        conn.execute(
            "UPDATE contractor_payment_vouchers SET is_paid=0, paid_by='', paid_at='', paid_log=?, "
            "paid_bank_account_name='', paid_bank_account_code='', updated_at=? WHERE voucher_no=?",
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
    """🔴 `AS4`（2026-09-23）：**這支端點已經沒有 UI 入口。**

    `system_settings` 的 `contractor_voucher_approval_flow` 這把 key 與
    `GET/PUT /api/settings/approval-flow/contractor_voucher`（簽核設定頁，
    `contractor_voucher` 設成獨立設定時）**共用同一把**。舊頁
    `contractor-voucher-approval-settings.html` 已改成導向新頁，側欄入口
    也拿掉了 —— **不要以為這支沒人用而改它的行為或拿掉它**：既有測試與
    可能存在的舊書籤／腳本還打得到它，而它讀寫的仍然是簽核設定頁在用的
    那把 key。要改「承攬商匯款申請」的簽核流程，請走簽核設定頁，不要
    從這裡改。
    """
    _require_user(authorization)
    return _get_setting("contractor_voucher_approval_flow", {"tiers": []}) or {"tiers": []}


@router.put("/api/contractor-vouchers/settings/approval-flow")
def set_contractor_voucher_approval_flow(body: ApprovalFlowSettings, authorization: str = Header(None)):
    """同上：**這支端點已經沒有 UI 入口**，寫的是簽核設定頁共用的那把 key。"""
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


# IP-14：M05 出納（待付、執行歷史）與 M06 會計匯出讀付款憑據時的序列化（原本直接 import `_voucher_public`）
_registry.provide("contractor_voucher.public", "subcontract", _voucher_public)
