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
from core import registry
from core.txn import begin_write, write_txn
from helpers.dates import normalize_date
from helpers.auth import has_finance_access, has_cashier_access  # noqa: E402  第42班：財務／出納只認「財務」角色與 superadmin
from helpers.gl_status import gl_posted_warning
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

    can_see_financial, is_document_approver, push_event_for_module,
)
from helpers.tiered_approval import require_reject_reason  # noqa: E402  退回一律要填原因
from pdf_gen import generate_contractor_voucher_pdf_bytes, _generate_contractor_voucher_pdf
from modules.subcontract import bank_mask as _bm
from helpers.errors import trace_id
# X-VAT（2026-09-26）：金額一律四捨五入（內建 round() 是銀行家捨入：.5 取偶數）
from helpers.legal_params import round_half_up
from modules.subcontract import remit as _remit
from modules.subcontract import remit_create as _rc

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
    #: 預定付款日（t45；選填；出納之後也能改）。與 payable_date（合約應付款日）是兩件事，不互相預填
    planned_pay_date: Optional[str] = None
    #: 31-B：分期（款別）申請。`kind` 不給＝舊式整筆申請（行為不變）；給了就要擇一填 `ratio_percent`（例 30＝30%）或 `amount`（本期稅前整數元）
    kind: Optional[str] = None
    ratio_percent: Optional[float] = None
    amount: Optional[int] = None


class VoucherPreviewIn(BaseModel):
    dispatch_id: int
    kind: Optional[str] = None
    ratio_percent: Optional[float] = None
    amount: Optional[int] = None


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
    # 2026-10-05（第42班）：憑證建立／送審／作廢等財務動作 ⇒ 僅「財務」角色與 superadmin（admin 直通拿掉）
    if not has_finance_access(user):
        raise HTTPException(403, "需要財務角色權限")


def _paid_between(start: str, end: str) -> list:
    """IP-14 `contractor_voucher.paid_between`：已付款（`is_paid=1`）且 `paid_at` 落在 `[start, end]`（YYYY-MM-DD，含頭尾兩天）
    的承攬商匯款申請，依 `paid_at` 排序；形狀＝`_voucher_public(row, include_snapshot=False)`。
    M06 會計匯出（T100 付款傳票）用它，不再自己讀 `contractor_payment_vouchers`（2026-09-26 主持派工，A 的 M06 搬遷前置）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM contractor_payment_vouchers WHERE is_paid=1 AND paid_at BETWEEN ? AND ? ORDER BY paid_at",
            (start + "T00:00:00", end + "T23:59:59")).fetchall()
        return [_voucher_public(r, include_snapshot=False) for r in rows]
    finally:
        conn.close()


def set_planned_pay_date(conn, voucher_no, value, user) -> dict:
    """IP-14 `contractor_voucher.set_planned`（t45）：出納端點改預定付款日（`value` 已正規化；''＝清除）。不 commit。
    只認「還在出納待付款清單上」的那一張（已核准、未付款、未作廢）；查無／不在清單 ⇒ LookupError；已匯款 ⇒ ValueError（409，預定日保留為歷史）。"""
    r = conn.execute("SELECT voucher_no, quote_no, status, is_paid, voided_at, planned_pay_date, created_by FROM contractor_payment_vouchers WHERE voucher_no=?",
                     (voucher_no,)).fetchone()
    if r is None or r["status"] != "已核准" or (r["voided_at"] or ""):
        raise LookupError("找不到這張匯款申請")
    if r["is_paid"]:
        raise ValueError("這張匯款申請已匯款，預定付款日保留為歷史紀錄，不能再修改")
    cur = conn.execute("UPDATE contractor_payment_vouchers SET planned_pay_date=?, updated_at=? WHERE voucher_no=? AND is_paid=0",
                       (value, datetime.now().isoformat(timespec="seconds"), voucher_no))
    if cur.rowcount == 0:                                   # 兩位出納同時操作：後到的看到已匯款
        raise ValueError("這張匯款申請已匯款，預定付款日保留為歷史紀錄，不能再修改")
    return {"plannedPayDate": value, "old": (r["planned_pay_date"] or "")[:10], "quoteNo": r["quote_no"] or "",
            "applicant": r["created_by"] or "", "docCode": voucher_no, "link": "case-management.html"}


def _voucher_public(row, include_snapshot: bool = True, viewer=None) -> dict:
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
        # 31-B：款別／分期（舊式整筆申請＝空字串／0／None）
        "kind":          d.get("kind") or "",
        "kindName":      d.get("kind_name") or "",
        "seq":           d.get("seq") or 0,
        "ratio":         d.get("ratio"),
        "pretaxAmount":  d.get("pretax_amount"),
        "invNo":         d.get("inv_no") or "",
        "invDate":       d.get("inv_date") or "",
        "voidedAt":      d.get("voided_at") or "",
        "voidReason":    d.get("void_reason") or "",
        "payableDate":   snap.get("payableDate", ""),
        "plannedPayDate": (d.get("planned_pay_date") or "")[:10],     # 預定付款日（t45；可編輯；''＝沒填）
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
        **_remit.remit_fields(d),   # W1：應付／實付／差額／手續費／差額審核狀態
        "exportCount":   d.get("export_count") or 0,
        "exportLog":     json.loads(d.get("export_log") or "[]"),
        "approval":      approval,
        "createdBy":     d.get("created_by") or "",
        "createdAt":     d.get("created_at") or "",
        "updatedAt":     d.get("updated_at") or "",
    }
    if include_snapshot:
        out["snapshot"] = snap
    # 帳號遮蔽（使用者裁示 2026-10-01）：viewer 不是最高管理者（含沒帶 viewer 的提供者呼叫）⇒ ****末四碼、存簿影本拿掉
    if not _bm.can_see_full(viewer):
        _bm.mask_record(viewer, out)
        if include_snapshot:
            out["snapshot"] = _mask_snapshot(snap)
    return out


def _mask_snapshot(snap: dict) -> dict:
    s = dict(snap)
    _bm.mask_record(None, s)
    s["personnel"] = [_bm.mask_record(None, dict(p)) if isinstance(p, dict) else p for p in (s.get("personnel") or [])]
    return s


# ── 銀行帳戶預設值（2026-09-02 新增，見 accounting_export.py 檔頭「標記已付款/
#    已收款時的銀行帳戶預設值」說明）────────────────────────────────────────────

@router.get("/api/contractor-vouchers/remit-fee-total")
def get_remit_fee_total(quote_no: str, authorization: str = Header(None)):
    """W1：這個案件已匯款的承攬商匯款手續費合計（公司自付，進案件成本；成本精算頁 remitFeeTotal 用）。
    權限＝案件層守門（同匯款申請清單）＋財務金額可視。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        guard_case_access(conn, quote_no, user, allow_module="case_manage")
        if not can_see_financial(user):
            raise HTTPException(403, "沒有查看財務金額的權限")
        return {"quoteNo": quote_no, "feeTotal": _remit.fee_total_for_case(conn, quote_no)}
    finally:
        conn.close()


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
    return [_voucher_public(r, include_snapshot=False, viewer=user) for r in rows]


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
    return _voucher_public(row, viewer=user)


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
        if not body.kind and dispatch["status"] not in ("accepted", "completed"):          # 分期申請（kind）的狀態規則在款別設定（kinded_context）
            conn.close()
            raise HTTPException(409, "僅「已驗收」或「完工」狀態的派發可產生匯款申請")
        if (dispatch["approval_status"] or "") not in ("", "已核准"):        # 31-A：派發審核未核准不得請款（舊單 '' 照舊）
            conn.close()
            raise HTTPException(409, "派發尚未核准（審核狀態：%s），不能產生匯款申請" % dispatch["approval_status"])
        existing = conn.execute(
            "SELECT voucher_no, quote_no, data_json, kind FROM contractor_payment_vouchers WHERE dispatch_id=? AND voided_at=''", (body.dispatch_id,)
        ).fetchone()
        if existing and not body.kind:
            conn.close()
            if existing["kind"]:
                raise HTTPException(409, f"此派發已改用分期（款別）方式產生匯款申請（{existing['voucher_no']}），請選擇款別再開立")
            raise HTTPException(409, f"此派發已產生匯款申請（{existing['voucher_no']}）")
        kctx = None
        if body.kind:                                           # 31-B：分期申請——款別／狀態／金額規則全在 remit_create（與試算同一支）
            try:
                kctx = _rc.kinded_context(conn, dispatch, body.kind, body.ratio_percent, body.amount)
            except _rc.RemitCreateError as e:
                conn.close()
                raise HTTPException(e.status, e.message)

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

        try:                                                    # 預定付款日（t45，選填）：與上面的合約應付款日分開，不預填、不寫回派發
            planned_pay_date = normalize_date(body.planned_pay_date, "預定付款日")
        except HTTPException:
            conn.close()
            raise

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
        if kctx is None:
            conn.execute(
                "INSERT INTO contractor_payment_vouchers "
                "(voucher_no, dispatch_id, quote_no, vendor_id, status, snapshot_json, data_json, "
                "created_by, created_at, updated_at, planned_pay_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (voucher_no, body.dispatch_id, dispatch["quote_no"], dispatch["vendor_id"], "草稿",
                 json.dumps(snapshot, ensure_ascii=False), "{}", user["username"], now, now, planned_pay_date)
            )
            label = ""
        else:
            snapshot = _rc.kinded_snapshot(snapshot, kctx, personnel_snapshot, personnel_total)
            conn.execute(
                "INSERT INTO contractor_payment_vouchers "
                "(voucher_no, dispatch_id, quote_no, vendor_id, status, snapshot_json, data_json, created_by, created_at, updated_at, "
                "kind, kind_name, kinds_version, seq, ratio, pretax_amount, planned_pay_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (voucher_no, body.dispatch_id, dispatch["quote_no"], dispatch["vendor_id"], "草稿",
                 json.dumps(snapshot, ensure_ascii=False), "{}", user["username"], now, now,
                 kctx["kind"]["code"], kctx["kind"]["name"], kctx["kinds_version"], kctx["seq"], kctx["ratio"], kctx["plan"]["pretax"],
                 planned_pay_date)
            )
            label = "　%s 第 %d 期 稅前 %d" % (kctx["kind"]["name"], kctx["seq"], kctx["plan"]["pretax"])
        conn.commit()
        conn.close()
        _audit(_tok(authorization), "contractor_voucher.create", "contractor_payment_voucher", voucher_no,
               f"{voucher_no}（{snapshot['vendorName'] or '外包人員點工'}）{label}")
        notify_module_activity("承攬商匯款申請", "建立", user.get("display_name") or user["username"],
                                f"{voucher_no}（{snapshot['vendorName']}）{label}", "case-management.html", audience="finance")
        out = {"voucher_no": voucher_no, "created_at": now}
        if kctx is not None:
            out.update(kind=kctx["kind"]["code"], kindName=kctx["kind"]["name"], seq=kctx["seq"], plan=kctx["plan"], warnings=kctx["warnings"])
        return out


@router.post("/api/contractor-vouchers/preview")
def preview_contractor_voucher(body: VoucherPreviewIn, authorization: str = Header(None)):
    """31-B：分期申請的試算（不寫任何東西）——與建立同一支 `remit_create.kinded_context`，所以畫面預覽的數字就是建立時會存的數字。
    回本期稅前／稅額／是否最後一期／補差／剩餘額度／前期清單／警示。"""
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    try:
        dispatch = conn.execute("SELECT * FROM contractor_dispatches WHERE id=?", (body.dispatch_id,)).fetchone()
        if not dispatch:
            raise HTTPException(404, "找不到對應的承攬商派發紀錄")
        if (dispatch["approval_status"] or "") not in ("", "已核准"):
            raise HTTPException(409, "派發尚未核准（審核狀態：%s），不能產生匯款申請" % dispatch["approval_status"])
        try:
            ctx = _rc.kinded_context(conn, dispatch, body.kind, body.ratio_percent, body.amount)
        except _rc.RemitCreateError as e:
            raise HTTPException(e.status, e.message)
    finally:
        conn.close()
    return {"kind": ctx["kind"]["code"], "kindName": ctx["kind"]["name"], "kindsVersion": ctx["kinds_version"], "seq": ctx["seq"], "mode": ctx["mode"],
            "plan": ctx["plan"], "dispatchTotal": ctx["total"], "taxRate": ctx["rate"], "warnings": ctx["warnings"],
            "previous": [{"voucherNo": p["voucher_no"], "kind": p["kind"], "seq": p["seq"], "pretax": p["pretax"], "tax": p["tax"], "isPaid": p["is_paid"]} for p in ctx["previous"]]}


@router.delete("/api/contractor-vouchers/{voucher_no}")
def delete_contractor_voucher(voucher_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    with write_txn(conn):                                                   # 檢查與刪除在同一把寫鎖內（否則檢查後有人新增一期，就刪到中間期）
        row = conn.execute("SELECT status, voucher_no, dispatch_id, kind, is_paid, voided_at FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(404, "申請不存在")
        if row["status"] != "草稿":
            conn.close()
            raise HTTPException(409, "僅草稿狀態可刪除" + ("（已送審的分期申請請用「作廢」）" if row["kind"] else ""))
        if row["kind"]:                                                     # 分期草稿也守 LIFO：刪中間一期會讓已凍結的補差失準
            why = _rc.void_blocker(conn, row)
            if why:
                conn.close()
                raise HTTPException(409, why)
        conn.execute("DELETE FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,))
        conn.commit()
        conn.close()
    _purge_notifications(voucher_no, ['contractor_voucher_approval_request', 'contractor_voucher_approved',
                                       'contractor_voucher_returned', 'approval_reminder'])
    _audit(_tok(authorization), "contractor_voucher.delete", "contractor_payment_voucher", voucher_no, voucher_no)
    notify_module_activity("承攬商匯款申請", "刪除", user.get("display_name") or user["username"],
                            voucher_no, "case-management.html", audience="finance")
    return {"ok": True}


@router.patch("/api/contractor-vouchers/{voucher_no}/invoice")
def set_voucher_invoice(voucher_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """31-B S4：登錄分期申請自己的發票（號碼＋日期；''＝清除）。D11：發票可事後補——沒有發票日就不產生該期的應付認列分錄（E04）。
    只給分期申請（舊式整筆的發票在派發上，走 `PATCH /api/contractor-dispatches/{id}/invoice-date`）；作廢的不能登。
    不影響金額；已入帳的 E04 發票日被改 ⇒ 回提示（總帳下次執行時沖轉重開，不在這裡擋）。"""
    user = _require_user(authorization)
    _require_admin(user)
    inv_no = str((body or {}).get("invNo") or "").strip()
    if len(inv_no) > 40:
        raise HTTPException(400, "發票號碼太長（上限 40 字）")
    inv_date = normalize_date((body or {}).get("invDate"), "發票日期")
    conn = get_db()
    try:
        row = conn.execute("SELECT voucher_no, kind, voided_at, inv_no, inv_date FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
        if not row:
            raise HTTPException(404, "申請不存在")
        if not row["kind"]:
            raise HTTPException(409, "舊式整筆申請的發票登在派發上（派發的「發票日期」），不在這裡登")
        if row["voided_at"]:
            raise HTTPException(409, "這張申請已作廢，不能登錄發票")
        now = datetime.now().isoformat()
        changed = (inv_no, inv_date) != (row["inv_no"] or "", row["inv_date"] or "")
        gl_warn = gl_posted_warning(conn, "contractor_voucher_invoice", voucher_no) if changed else None
        conn.execute("UPDATE contractor_payment_vouchers SET inv_no=?, inv_date=?, updated_at=? WHERE voucher_no=?", (inv_no, inv_date, now, voucher_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "contractor_voucher.invoice", "contractor_payment_voucher", voucher_no,
           "%s 發票：%s %s → %s %s" % (voucher_no, row["inv_no"] or "（無號碼）", row["inv_date"] or "（未登錄）", inv_no or "（無號碼）", inv_date or "（未登錄）"))
    return {"ok": True, "invNo": inv_no, "invDate": inv_date, "updated_at": now, **({"glWarning": gl_warn} if gl_warn else {})}


class VoucherVoidIn(BaseModel):
    reason: str = ""


@router.post("/api/contractor-vouchers/{voucher_no}/void")
def void_contractor_voucher(voucher_no: str, body: VoucherVoidIn, authorization: str = Header(None)):
    """31-B S2b：分期匯款申請作廢（admin＋；填原因；已付款先撤銷付款；後進先出）。作廢的不佔累計額度、不進待付款／簽核佇列，序號不回頭重用。"""
    user = _require_user(authorization)
    _require_admin(user)
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫作廢原因")
    if len(reason) > 500:
        raise HTTPException(400, "作廢原因太長（上限 500 字）")
    conn = get_db()
    with write_txn(conn):
        row = conn.execute("SELECT voucher_no, dispatch_id, kind, is_paid, voided_at, status FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(404, "申請不存在")
        why = _rc.void_blocker(conn, row)
        if why:
            conn.close()
            raise HTTPException(409, why)
        now = datetime.now().isoformat()
        conn.execute("UPDATE contractor_payment_vouchers SET status='已作廢', voided_at=?, voided_by=?, void_reason=?, updated_at=? WHERE voucher_no=?",
                     (now, user["username"], reason, now, voucher_no))
        conn.commit()
        conn.close()
    _purge_notifications(voucher_no, ['contractor_voucher_approval_request', 'contractor_voucher_approved',
                                       'contractor_voucher_returned', 'approval_reminder'])
    _audit(_tok(authorization), "contractor_voucher.void", "contractor_payment_voucher", voucher_no, "%s（原狀態 %s）原因：%s" % (voucher_no, row["status"], reason))
    notify_module_activity("承攬商匯款申請", "作廢", user.get("display_name") or user["username"], voucher_no, "case-management.html", audience="finance")
    return {"ok": True, "voidedAt": now}


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
    note = require_reject_reason(note, conn=conn)
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
    note = require_reject_reason(note, conn=conn)

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
    row = conn.execute("SELECT voucher_no, quote_no, data_json, voided_at FROM contractor_payment_vouchers WHERE voucher_no=?",
                        (voucher_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "單據不存在")
    _guard_voucher(conn, row, user)
    conn.close()
    if not row:
        raise HTTPException(404, "申請不存在")
    if row["voided_at"]:                                                    # 作廢的申請不能再當匯款依據印出去
        raise HTTPException(409, "這張申請已作廢，不提供 PDF")
    try:
        pdf_bytes = generate_contractor_voucher_pdf_bytes(voucher_no, mask_bank=not _bm.can_see_full(user))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(503, str(e))
    except HTTPException:          # 第二道 428（COMPANY-SETUP-GATE §5）不可以被下面的 except Exception 吞成 500
        raise
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


# ── 個人外包人員 ↔ 勞報單（R12，使用者 2026-09-30 裁示 (b)；IP-105 `payslip.remit`）──────────────────────
# 匯款單快照的 personnel[] 每位個人可帶 payslipNo（additive，不需 migration）：匯款金額必須等於該勞報單實付、勞報單已簽回、受款人相符。
# `system_settings.remit_require_payslip`＝"1" ⇒ 標記已匯款時**每位個人都必須**已關聯（預設關閉，畫面補上關聯入口後由最高管理者開啟）；
# 已帶 payslipNo 的一律驗證，與設定無關。匯款標記成功 ⇒ 連結的勞報單一併記為已付款（同一個交易）；取消匯款 ⇒ 一併退回。

def _personnel_link_errors(conn, snapshot_json, require_all):
    """⇒ (錯誤訊息清單, 已驗證可標記付款的勞報單號清單)。純讀。"""
    try:
        snap = json.loads(snapshot_json or "{}") or {}
    except (TypeError, ValueError):
        snap = {}
    people = [p for p in (snap.get("personnel") or []) if str((p or {}).get("name") or "").strip()]
    errs, ok = [], []
    provider = registry.single_provider("payslip.remit")
    for p in people:
        name, no = str(p.get("name") or ""), str(p.get("payslipNo") or "").strip()
        if not no:
            if require_all:
                errs.append("%s 尚未關聯勞報單（個人外包匯款前必須先關聯勞報單）" % name)
            continue
        if provider is None:
            errs.append("%s：薪資獎金模組未安裝，無法驗證勞報單 %s" % (name, no))
            continue
        c = provider.check(conn, no)
        if c is None:
            errs.append("%s：查無勞報單 %s" % (name, no))
        elif c["status"] not in ("已核准", "已匯出", "已簽回"):             # 第46班 Q13：與「已核准即可付款」一致，不再要求已簽回
            errs.append("%s：勞報單 %s 狀態是「%s」，須為已核准、已匯出或已簽回%s" % (name, no, c["status"], "（已由匯款單 %s 付款）" % c["paidViaRemit"] if c["paidViaRemit"] else ""))
        elif p.get("id") and c["contractorId"] and int(p["id"]) != int(c["contractorId"]):
            errs.append("%s：勞報單 %s 的受款人是 %s，不符" % (name, no, c["contractorName"]))
        elif abs(float(p.get("amount") or 0) - c["net"]) > 0.005:          # 金額比對（到分），不做進位
            errs.append("%s：匯款金額 %g 必須等於勞報單 %s 的實付 %g" % (name, float(p.get("amount") or 0), no, c["net"]))
        else:
            ok.append(no)
    return errs, ok


def _require_payslip_on():
    """`system_settings.remit_require_payslip`：預設開啟（使用者規則：個人外包匯款前必須關聯勞報單）；"0"＝緊急關閉開關（僅最高管理者、有稽核紀錄）。"""
    return str(_get_setting("remit_require_payslip", "1")) != "0"


@router.get("/api/contractor-vouchers/settings/remit-require-payslip")
def get_remit_require_payslip(authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    return {"enabled": _require_payslip_on()}


@router.put("/api/contractor-vouchers/settings/remit-require-payslip")
def set_remit_require_payslip(body: dict = Body(...), authorization: str = Header(None)):
    """緊急開關：關閉＝個人外包匯款不強制關聯勞報單（已關聯者仍照樣驗證）。只有最高管理者，寫稽核。"""
    user = _require_user(authorization)
    if user["role"] != "superadmin":
        raise HTTPException(403, "只有最高管理者可以更動")
    on = bool((body or {}).get("enabled"))
    _set_setting("remit_require_payslip", "1" if on else "0")
    _audit(_tok(authorization), "contractor_voucher.remit_require_payslip", "system_settings", "remit_require_payslip", "remit_require_payslip",
           {"enabled": on, "reason": str((body or {}).get("reason") or "")[:200]})
    return {"enabled": on}


@router.get("/api/contractor-vouchers/{voucher_no}/personnel-links")
def get_personnel_links(voucher_no: str, authorization: str = Header(None)):
    """匯款單的個人外包人員與勞報單關聯現況（出納頁挑選用）：每人的匯款金額、已關聯勞報單、可挑選的勞報單、這一行現在能不能匯款。"""
    user = _require_user(authorization)
    if not has_cashier_access(user):
        raise HTTPException(403, "需要財務角色（出納）權限")
    conn = get_db()
    try:
        row = conn.execute("SELECT snapshot_json FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
        if not row:
            raise HTTPException(404, "申請不存在")
        snap = json.loads(row["snapshot_json"] or "{}")
        prov = registry.single_provider("payslip.remit")
        lines = []
        for p in snap.get("personnel") or []:
            if not str((p or {}).get("name") or "").strip():
                continue
            one = json.dumps({"personnel": [p]}, ensure_ascii=False)
            errs, _ok = _personnel_link_errors(conn, one, _require_payslip_on())
            cands = prov.candidates(conn, p["id"]) if (prov is not None and p.get("id")) else []
            lines.append({"id": p.get("id"), "name": p.get("name"), "amount": float(p.get("amount") or 0),
                          "payslipNo": p.get("payslipNo") or "", "candidates": cands, "error": "；".join(errs), "ok": not errs})
        return {"required": _require_payslip_on(), "providerAvailable": prov is not None, "lines": lines,
                "canPay": all(l["ok"] for l in lines)}
    finally:
        conn.close()


class PersonnelLinkIn(BaseModel):
    personId: Optional[int] = None
    personName: Optional[str] = ""
    payslipNo: str = ""


@router.post("/api/contractor-vouchers/{voucher_no}/personnel-link")
def link_personnel_payslip(voucher_no: str, body: PersonnelLinkIn, authorization: str = Header(None)):
    """把匯款單裡的一位個人外包人員關聯到勞報單（payslipNo 給空字串＝解除）。只限尚未匯款的匯款單；關聯時即驗證（已簽回、受款人、金額）。"""
    user = _require_user(authorization)
    if not has_cashier_access(user):
        raise HTTPException(403, "需要財務角色（出納）權限")
    conn = get_db()
    try:
        row = conn.execute("SELECT is_paid, snapshot_json FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
        if not row:
            raise HTTPException(404, "申請不存在")
        if row["is_paid"]:
            raise HTTPException(409, "已匯款的申請不能更動勞報單關聯（請先取消已匯款）")
        snap = json.loads(row["snapshot_json"] or "{}")
        target = None
        for p in snap.get("personnel") or []:
            if (body.personId and p.get("id") == body.personId) or (not body.personId and body.personName and p.get("name") == body.personName):
                target = p
                break
        if target is None:
            raise HTTPException(404, "匯款單裡找不到這位外包人員")
        no = (body.payslipNo or "").strip()
        if no:
            target["payslipNo"] = no
            errs, _ok = _personnel_link_errors(conn, json.dumps({"personnel": [target]}, ensure_ascii=False), False)
            if errs:
                raise HTTPException(409, "；".join(errs))
        else:
            target.pop("payslipNo", None)
        conn.execute("UPDATE contractor_payment_vouchers SET snapshot_json=?, updated_at=? WHERE voucher_no=?",
                     (json.dumps(snap, ensure_ascii=False), datetime.now().isoformat(), voucher_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "contractor_voucher.personnel_link", "contractor_payment_voucher", voucher_no, voucher_no,
           {"person": target.get("name"), "payslipNo": no})
    return {"ok": True, "person": target.get("name"), "payslipNo": no}


# ── 財務已匯款 toggle ─────────────────────────────────────────────────────────

def _payout_calendar_args(voucher_no, snapshot_json, paid_at, rm, who):
    """行事曆「包商撥款」事件的內容（push_event_for_module 的參數）。"""
    try:
        snap = json.loads(snapshot_json or "{}") or {}
    except (TypeError, ValueError):
        snap = {}
    vname = snap.get("vendorName") or "外包人員點工"
    payable = _remit._payable(snapshot_json)
    desc = (f"承攬商匯款申請 {voucher_no} 已標記匯款。\n廠商：{vname}\n應付：NT$ {payable:,.0f}"
            f"\n實付：NT$ {float(rm['actual'] or 0):,.0f}\n手續費：NT$ {float(rm['fee'] or 0):,.0f}"
            f"\n匯款日期：{paid_at}\n標記人：{who}")
    return ("contractor_payout", f"包商匯款 — {voucher_no}（{vname}）", desc, paid_at or None)


@router.post("/api/contractor-vouchers/{voucher_no}/paid-toggle")
def toggle_paid(voucher_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """標記已匯款**必須**帶 paid_at（YYYY-MM-DD，實際匯款日期，不一定等於操作
    當下的系統時間——財務常常是先在銀行完成匯款，之後才回系統標記）；不帶 ⇒ 400
    （2026-09-30 W1：原本不帶退回今天）。paid_log 裡的 "at"／updated_at 仍然是「這次操作
    本身發生的系統時間」，跟 paid_at（匯款發生的日期）是兩個不同概念，不要
    混用。"""
    user = _require_user(authorization)
    # 2026-08-31（財務/出納權限分工）：標記已匯款是出納的執行動作，不是財務
    # 核准，額外放行具備 cashier 模組的使用者（不需要完整 admin 權限）——跟
    # 這個檔案其餘建立/送審/撤銷等「財務」動作的 _require_admin() 分開判斷，
    # 不能把 _require_admin() 本身改鬆，那些動作仍然只限 admin+。
    if not has_cashier_access(user):
        raise HTTPException(403, "需要財務角色（出納）權限")
    action = (body or {}).get("action", "")
    note   = (body or {}).get("note", "")
    if action not in ("pay", "unpay"):
        raise HTTPException(400, "action 必須為 pay 或 unpay")
    paid_at_value = ""
    if action == "pay":
        # W1（2026-09-30 使用者裁示）：匯款日期必填——不再默認今天（先在銀行匯完、隔天才回系統標記是常態，默認今天會記錯日期）
        raw_paid_at = (body or {}).get("paid_at") or ""
        if not raw_paid_at:
            raise HTTPException(400, "請填寫匯款日期（paid_at，YYYY-MM-DD）")
        try:
            date.fromisoformat(raw_paid_at)
        except ValueError:
            raise HTTPException(400, f"匯款日期格式錯誤（{raw_paid_at}），需為 YYYY-MM-DD")
        paid_at_value = raw_paid_at
    conn = get_db()
    row = conn.execute(
        "SELECT status, is_paid, paid_log, snapshot_json FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "申請不存在")
    rm = None
    if action == "pay":
        # W1：實付金額／手續費（公司自付、不參與比對）；實付≠應付 ⇒ 差額待審核
        try:
            rm = _remit.parse_remit(body, _remit._payable(row["snapshot_json"]))
        except ValueError as e:
            conn.close()
            raise HTTPException(400, str(e))
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
    linked_slips = []
    if action == "pay":
        errs, linked_slips = _personnel_link_errors(conn, row["snapshot_json"], _require_payslip_on())
        if errs:
            conn.close()
            raise HTTPException(409, "不能標記已匯款：" + "；".join(errs))

    now = datetime.now().isoformat()
    log = json.loads(row["paid_log"] or "[]")
    log.append({
        "at": now, "username": user["username"], "userDisplay": user.get("display_name") or user["username"],
        "action": "paid" if action == "pay" else "unpaid", "note": note,
        **({"paidAt": paid_at_value, "actual": rm["actual"], "fee": rm["fee"], "diff": rm["diff"]} if action == "pay" else {}),
    })
    if action == "pay":
        bank_name = (body or {}).get("bank_account_name") or (body or {}).get("bankAccountName") or ""
        bank_code = (body or {}).get("bank_account_code") or (body or {}).get("bankAccountCode") or ""
        conn.execute(
            "UPDATE contractor_payment_vouchers SET is_paid=1, paid_by=?, paid_at=?, paid_log=?, "
            "paid_bank_account_name=?, paid_bank_account_code=?, updated_at=?, "
            "remit_actual=?, remit_fee=?, remit_review=?, remit_review_by='', remit_review_at='', remit_review_note='' "
            "WHERE voucher_no=?",
            (user.get("display_name") or user["username"], paid_at_value,
             json.dumps(log, ensure_ascii=False), bank_name, bank_code, now,
             rm["actual"], rm["fee"], rm["review"], voucher_no)
        )
        if linked_slips:                                   # R12：連結的勞報單一併記為已付款（同一個交易）
            # ⚠ 跨模組寫入連結（M04 → M07）：這裡改的是**薪資模組的資料**（payslips：status／payment_date／paid_by／data_json.paid_via_remit），
            #   經 IP-105 `payslip.remit`，與本匯款單同一個連線、同一次 commit；反向在下面 unpay 的 unmark_paid。
            #   登記：docs/platform/MONEY-FLOWS.md §9 列 W-1；守門：accounting/tests/test_ledger_r12_remit_payslip_2026_09_30.py。
            registry.single_provider("payslip.remit").mark_paid(conn, linked_slips, voucher_no, paid_at_value,
                                                                user.get("display_name") or user["username"])
    else:
        # MONEY-FLOWS §9 L3：取消已匯款 ⇒ 已入帳的 E05 來源消失（orphan）：下次引擎執行時產生反向草稿（日期＝今天）。
        # 下游效應：營運報表現金支出立即消失；總帳要手動執行才反映；已結帳期間則要手工沖轉。只提示、不擋。
        gl_warn = gl_posted_warning(conn, "contractor_voucher", voucher_no)
        conn.execute(
            "UPDATE contractor_payment_vouchers SET is_paid=0, paid_by='', paid_at='', paid_log=?, "
            "paid_bank_account_name='', paid_bank_account_code='', updated_at=?, " + _remit.CLEAR_SQL + " WHERE voucher_no=?",
            (json.dumps(log, ensure_ascii=False), now, voucher_no)
        )
        prov = registry.single_provider("payslip.remit")
        if prov is not None:                               # R12：由這張匯款單付款的勞報單一併退回已簽回
            # ⚠ 跨模組寫入連結（M04 → M07）：同上（MONEY-FLOWS §9 W-1）；只退回 data_json.paid_via_remit＝本匯款單號的勞報單。
            prov.unmark_paid(conn, voucher_no)
    conn.commit()
    conn.close()
    _audit(_tok(authorization), f"contractor_voucher.{action}", "contractor_payment_voucher", voucher_no,
           voucher_no, {"note": note, **({"paidAt": paid_at_value, "actual": rm["actual"], "fee": rm["fee"],
                                          "diff": rm["diff"], "review": rm["review"]} if action == "pay" else {})})
    who = user.get("display_name") or user["username"]
    if action == "pay" and rm["review"]:
        notify_module_activity("承攬商匯款申請", "匯款差額待審核", who, voucher_no, "cashier.html",
                               detail="實付與應付不符（差額 %+g），請財務角色到出納頁核可或退回。%s" % (rm["diff"], note or ""), audience="finance")
    else:
        notify_module_activity("承攬商匯款申請", "已匯款" if action == "pay" else "取消已匯款", who, voucher_no,
                               "case-management.html", detail=note or "", audience="finance")
    if action == "pay":
        # 行事曆「包商撥款」（2026-09-30，預設關；開關在 L1 判斷）：以匯款日期建立；取消匯款不刪事件
        spawn_bg_thread(push_event_for_module, args=_payout_calendar_args(
            voucher_no, row["snapshot_json"], paid_at_value, rm, who))
    return {"ok": True, "is_paid": action == "pay", "paid_log": log,
            **({"remitReview": rm["review"], "diff": rm["diff"], "actual": rm["actual"], "fee": rm["fee"]} if action == "pay" else {}),
            **({"glWarning": gl_warn.replace("此筆", "此筆（匯款單 %s）" % voucher_no, 1)} if action != "pay" and gl_warn else {})}


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


# ── 待我簽核與轉簽（M01-PLAN §3-7，2026-09-26）：本模組提供自己的待簽項目與簽核鏈讀寫，M01 佇列只彙整 ──
from helpers import approval_queue as _aq  # noqa: E402

#: `approval.reassign`：簽核鏈在 contractor_payment_vouchers.data_json.$.approval
REASSIGN = _aq.DataJsonApproval("contractor_payment_vouchers", "voucher_no")


def queue_items(conn) -> list:
    """`approval.queue_items`：待審核／簽核中的承攬商匯款申請（`type`＝`contractor_voucher`）。"""
    rows = conn.execute("""
        SELECT voucher_no, quote_no, snapshot_json, created_at,
               data_json
        FROM contractor_payment_vouchers
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    out = []
    for r in rows:
        raw = _aq.approval_json_of(r["data_json"], "contractor_voucher", r["voucher_no"])   # 壞一筆只跳過那一筆（c-queue-json）
        if raw is None:
            continue
        f = _aq.tier_fields(raw)
        try:
            snap = json.loads(r["snapshot_json"] or "{}")
        except Exception:
            snap = {}
        out.append(_aq.base_item(
            "contractor_voucher", r["voucher_no"], f,
            customer=snap.get("vendorName") or "外包人員點工",
            projectName=f"關聯案件 {r['quote_no']}",
            total=snap.get("grandTotal", 0),
            quoteDate=(r["created_at"] or "")[:10],
            linkedQuoteNo=r["quote_no"],
            # 2026-08-30：使用者要求簽核佇列連同申請單本身都要顯示應付款日期／匯款帳戶／存簿圖檔／廠商發票，
            # 直接從凍結快照帶出，不用簽核人員另外點開案件管理才看得到匯款要用的資訊。
            payableDate=snap.get("payableDate") or "",
            bankName=snap.get("bankName") or "",
            bankBranch=snap.get("bankBranch") or "",
            bankAccountName=snap.get("bankAccountName") or "",
            bankAccountNumber=snap.get("bankAccountNumber") or "",
            bankPassbookImage=snap.get("bankPassbookImage") or "",
            # CT1（2026-09-24 使用者裁示 D2）：外包人員各自的匯款帳戶——來源是建立申請時凍結的 personnel 快照，
            # 與上面承攬商那段同一份可見性。
            personnelBanks=[
                {"name": p.get("name") or "", "bankCode": p.get("bankCode") or "",
                 "bankName": p.get("bankName") or "", "bankBranch": p.get("bankBranch") or "",
                 "bankAccountName": p.get("bankAccountName") or "",
                 "bankAccountNumber": p.get("bankAccountNumber") or ""}
                for p in (snap.get("personnel") or []) if isinstance(p, dict)
            ],
            invoiceFiles=snap.get("invoiceFiles") or [],
        ))
    return out


def queue_detail(conn, doc_no):
    """`approval.detail`（contractor_voucher）：簽核佇列詳情的單據內容；權限、案件抬頭、金額遮蔽在 M01。"""
    r = conn.execute("SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (doc_no,)).fetchone()
    return _aq.snapshot_doc_detail(r) if r else None
