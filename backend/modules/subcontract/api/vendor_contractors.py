"""承攬商管理 (vendor contractors) + 案件派發 CRUD + 回推報價單品項."""
import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Body, File, HTTPException, Header, UploadFile
from pydantic import BaseModel, Field, ConfigDict

from db import get_db, next_entity_code
from helpers.gl_status import gl_posted_warning
from helpers import (_require_user, _tok, _audit, _notify, notify_module_activity, require_any_module,
                     check_approve_permission, resolve_active_flow_setting, UnresolvedManagerError,
                     setting_to_active_tiers)
from core.txn import begin_write, write_txn
from core import registry as _registry
from helpers.uploads import save_document_files, delete_document_file
from helpers.dates import normalize_date  # `AC2`（L1）
# X-VAT（2026-09-26）：金額一律四捨五入（內建 round() 是銀行家捨入：.5 取偶數）
from helpers.legal_params import round_half_up
from modules.subcontract.api.contractors import _stamp_passbook
from helpers.auth import has_finance_access, finance_duty_person  # 第42班（Q5）；R2 D5 縫

router = APIRouter()


def _require_admin(user: dict):
    """比照 shipping_notes.py／contractor_vouchers.py 同名 helper（2026-08-24
    安全審查修正）：派發資料的金額/稅率等欄位後續會被凍結進正式的承攬商匯款憑證
    快照，建立/修改不該只要求登入，之前完全沒有角色門檻，任何登入使用者都能
    竄改。查詢類端點（list/get）維持唯讀不擋，跟其他模組一致。"""
    if user["role"] not in ("superadmin", "admin") and not finance_duty_person(user):          # 第42班：財務角色可改派發金額／發票日（Q5），所以也要過這道門
        raise HTTPException(403, "需要管理員權限")


def _require_finance(user: dict):
    """第42班（Q5）：派發的發票日、發票附件與「含金額欄位的修改」屬財務（發票日決定應付認列、金額會凍結進匯款憑證）；
    派發建立／狀態／驗收仍是一般管理（`_require_admin`）。"""
    if not has_finance_access(user):
        raise HTTPException(403, "需要財務角色權限")


def _amounts(lst) -> list:
    out = []
    for it in lst or []:
        try:
            out.append(float((it or {}).get("amount", 0) or 0))
        except (TypeError, ValueError, AttributeError):
            out.append(None)
    return out


_STATUS_LABELS = {
    "draft": "草稿",
    "sent": "已送出",
    "confirmed": "已確認",
    "pending_acceptance": "待驗收",
    "accepted": "已驗收",
    "completed": "完工",
    "cancelled": "已取消",
}


# ── Pydantic models ──────────────────────────────────────────────────────────

class VendorContractorIn(BaseModel):
    name: str
    tax_id: Optional[str] = ''
    contact_name: Optional[str] = ''
    phone: Optional[str] = ''
    email: Optional[str] = ''
    address: Optional[str] = ''
    data: Optional[dict] = {}


class DispatchIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    quote_no: str
    vendor_id: Optional[int] = None
    dispatch_date: Optional[str] = ''
    scope: Optional[str] = ''
    items_json: Optional[list] = []
    personnel_json: Optional[list] = []
    tax_rate: Optional[float] = 0.05
    status: Optional[str] = None      # 31-A：建立忽略、編輯只能等於現值（狀態只經操作按鈕改）
    notes: Optional[str] = ''
    invoice_no: Optional[str] = ''
    payable_date: Optional[str] = ''
    # `AC2`：廠商發票日期（''＝未登錄；權責口徑依它歸月）。None＝沒帶這個鍵 ⇒ PUT 保留原值
    #   （其他頁面的 PUT 沒送這一鍵時不可以把已登錄的發票日清掉）
    invoice_date: Optional[str] = None
    # 樂觀鎖（選填，見 update_dispatch）——比照 customers.py 等的
    # expectedUpdatedAt 慣例
    expected_updated_at: Optional[str] = Field(None, alias="expectedUpdatedAt")


# ── Helpers ──────────────────────────────────────────────────────────────────

from modules.subcontract import bank_mask as _bm  # noqa: E402
from modules.subcontract import dispatch_flow as _flow  # noqa: E402
from modules.subcontract import recycle_adapter as _rb_adapter  # noqa: E402  第53班 P1：刪除暫存區 adapter
from helpers import recycle_bin  # noqa: E402
from core.txn import begin_write as _begin_write  # noqa: E402


def _vendor_row(row, user=None) -> dict:
    """user＝檢視者；帳號遮蔽規則見 modules/subcontract/bank_mask.py（沒帶 user ⇒ 一律遮蔽，fail closed）。"""
    d = {}
    try:
        d = json.loads(row["data_json"] or "{}")
    except Exception:
        pass
    # 存簿影本（base64）不進一般列表/詳情回應，避免拖垮輕量 API；只回傳有無上傳的旗標，
    # 實際影像走專屬的 GET/PUT .../passbook 端點（比照 contractors.py 的 has_passbook 慣例）
    has_passbook = bool(d.pop("bankPassbookImage", None))
    keys = row.keys() if hasattr(row, 'keys') else []
    _bm.mask_record(user, d)
    return {
        "id": row["id"],
        "code": (row["code"] if "code" in keys else "") or "",
        "name": row["name"],
        "taxId": row["tax_id"] or "",
        "contactName": row["contact_name"] or "",
        "phone": row["phone"] or "",
        "email": row["email"] or "",
        "address": row["address"] or "",
        "active": bool(row["active"]),
        "createdAt": row["created_at"] or "",
        "updatedAt": row["updated_at"] or "",
        "hasPassbook": has_passbook,
        **d
    }


def _legacy_modified_at(row) -> str:
    """舊單（approval_status=''）被實質修改過 ⇒ 最後修改時間；沒有 ⇒ ''。"""
    try:
        if "approval_json" not in row.keys() or (row["approval_status"] or "") != "":
            return ""
        m = json.loads(row["approval_json"] or "{}")
        lm = m.get("legacyModified") if isinstance(m, dict) else None
        return str(lm.get("at") or "") if isinstance(lm, dict) else ""
    except (ValueError, TypeError, KeyError):
        return ""


def _dispatch_row(row) -> dict:
    items = []
    try:
        items = json.loads(row["items_json"] or "[]")
    except Exception:
        pass
    keys = row.keys()
    personnel = []
    if "personnel_json" in keys:
        try:
            personnel = json.loads(row["personnel_json"] or "[]")
        except Exception:
            pass
    files = []
    if "files_json" in keys:
        try:
            files = json.loads(row["files_json"] or "[]")
        except Exception:
            pass
    invoice_files = []
    if "invoice_files_json" in keys:
        try:
            invoice_files = json.loads(row["invoice_files_json"] or "[]")
        except Exception:
            pass
    personnel_total = sum(float(p.get("amount", 0) or 0) for p in personnel)
    total = float(row["total_amount"] or 0)
    if not total and items:
        total = sum(float(it.get("amount", 0) or 0) for it in items)
    tax_rate = float(row["tax_rate"]) if "tax_rate" in keys and row["tax_rate"] is not None else 0.05
    tax_amount = round_half_up(total, tax_rate)
    total_with_tax = total + tax_amount
    return {
        "id": row["id"],
        "quoteNo": row["quote_no"],
        "vendorId": row["vendor_id"],
        "vendorName": (row["vendor_name"] if "vendor_name" in keys else "") or "",
        "dispatchDate": row["dispatch_date"] or "",
        "scope": row["scope"] or "",
        "items": items,
        "totalAmount": total,
        "taxRate": tax_rate,
        "taxAmount": tax_amount,
        "totalWithTax": total_with_tax,
        "personnel": personnel,
        "personnelTotal": personnel_total,
        "files": files,
        # 承攬商本身（含稅）+ 外包名單人員（不計稅，屬個人薪資性質），供財務/精算加總引用
        "grandTotal": total_with_tax + personnel_total,
        "status": row["status"] or "draft",
        "statusLabel": _STATUS_LABELS.get(row["status"] or "draft", row["status"] or ""),
        "notes": row["notes"] or "",
        "invoiceNo": (row["invoice_no"] if "invoice_no" in keys else "") or "",
        "payableDate": (row["payable_date"] if "payable_date" in keys else "") or "",
        "invoiceDate": (row["invoice_date"] if "invoice_date" in keys else "") or "",
        "invoiceFiles": invoice_files,
        "createdBy": row["created_by"] or "",
        "createdAt": row["created_at"] or "",
        "updatedAt": row["updated_at"] or "",
        "acceptedAt": (row["accepted_at"] if "accepted_at" in keys else "") or "",
        "acceptedBy": (row["accepted_by"] if "accepted_by" in keys else "") or "",
        # 31-A 派發審核（只新增鍵；契約 IP-1 只准加不准改）：兩段審核狀態、單號、舊單旗標、合併後的人話狀態
        "approvalStatus": (row["approval_status"] if "approval_status" in keys else "") or "",
        "completionStatus": (row["completion_status"] if "completion_status" in keys else "") or "",
        "docCode": (row["doc_code"] if "doc_code" in keys else "") or "",
        "legacy": _flow.is_legacy(row),
        "legacyModified": _legacy_modified_at(row) != "",
        "legacyModifiedAt": _legacy_modified_at(row),
        "displayStatus": _flow.display_status(row),
        "submittedBy": (row["submitted_by"] if "submitted_by" in keys else "") or "",
        "submittedAt": (row["submitted_at"] if "submitted_at" in keys else "") or "",
        "approvedAt": (row["approved_at"] if "approved_at" in keys else "") or "",
        "completionRequestedBy": (row["completion_requested_by"] if "completion_requested_by" in keys else "") or "",
        "completionRequestedAt": (row["completion_requested_at"] if "completion_requested_at" in keys else "") or "",
        "completionApprovedAt": (row["completion_approved_at"] if "completion_approved_at" in keys else "") or "",
        "cancelReason": (row["cancel_reason"] if "cancel_reason" in keys else "") or "",
    }


# ── 連接器 dispatch.row（docs/platform/INTEGRATION-POINTS.md IP-1，契約版本 1）──────────
# 派工單列 → 公開形狀（含 grandTotal＝含稅承攬商費用＋外包人員）。別組不再 import 本檔的
# 私有函式，改用 `core.registry.single_provider("dispatch.row")`；M04 不在時對方拿到 None，
# 自行退化成「沒有派工資訊」。欄位只准加不准改名／刪除（改了要升契約版本）。


# ── 承攬商 CRUD ───────────────────────────────────────────────────────────────

@router.get("/api/vendor-contractors")
def list_vendor_contractors(
    q: Optional[str] = None,
    active_only: bool = True,
    authorization: str = Header(None)
):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        return []
    conn = get_db()
    sql = ("SELECT id, code, name, tax_id, contact_name, phone, email, address, "
           "data_json, active, created_at, updated_at FROM vendor_contractors")
    params = []
    clauses = []
    if active_only:
        clauses.append("active=1")
    if q:
        clauses.append("(name LIKE ? OR tax_id LIKE ? OR phone LIKE ? OR contact_name LIKE ? OR code LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY name"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_vendor_row(r, user) for r in rows]


@router.get("/api/vendor-contractors/selectable")
def list_vendors_selectable(authorization: str = Header(None)):
    """輕量列表供案件管理下拉選單使用（所有登入者皆可讀）。"""
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, contact_name, phone FROM vendor_contractors WHERE active=1 ORDER BY name"
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "name": r["name"],
             "contactName": r["contact_name"] or "", "phone": r["phone"] or ""} for r in rows]


@router.get("/api/vendor-contractors/{vid}")
def get_vendor_contractor(vid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    conn = get_db()
    row = conn.execute("SELECT * FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "找不到此承攬商")
    return _vendor_row(row, user)


@router.post("/api/vendor-contractors", status_code=201)
def create_vendor_contractor(body: VendorContractorIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    now = datetime.now().isoformat()
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO vendor_contractors "
        "(name, tax_id, contact_name, phone, email, address, data_json, active, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,1,?,?)",
        (body.name.strip(), body.tax_id or '', body.contact_name or '',
         body.phone or '', body.email or '', body.address or '',
         json.dumps(body.data or {}, ensure_ascii=False), now, now)
    )
    vid = cur.lastrowid
    conn.commit()
    code = next_entity_code(conn, 'vendor_contractors', 'V')
    conn.execute("UPDATE vendor_contractors SET code=? WHERE id=?", (code, vid))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.create', 'vendor_contractor', str(vid), body.name)
    notify_module_activity("承攬商管理", "建立", user.get("display_name") or user["username"],
                            body.name, "vendor-contractors.html")
    return {"id": vid, "code": code, "created_at": now}


@router.put("/api/vendor-contractors/{vid}")
def update_vendor_contractor(vid: int, body: VendorContractorIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    now = datetime.now().isoformat()
    conn = get_db()
    existing = conn.execute("SELECT data_json FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    # Merge: preserve existing visits unless caller explicitly provides them
    existing_data = {}
    try:
        existing_data = json.loads(existing["data_json"] or "{}")
    except Exception:
        pass
    new_data = body.data or {}
    # 呼叫端（如 Excel 匯入）若未帶這些 key，一律從既有資料保留，避免被覆蓋清空——
    # 銀行帳戶/存簿是後補欄位，舊的呼叫端（匯入）本來就不知道要帶
    _preserve_keys = (
        "visits", "bankPassbookImage",
        "bankCode", "bankName", "bankBranch", "bankAccountName", "bankAccountNumber",
    )
    # 遮蔽值原樣送回（編輯表單載入的是 ****1234）⇒ 保留原帳號，不可覆蓋成遮蔽字串
    if _bm.is_masked_value(new_data.get("bankAccountNumber")):
        new_data = {**new_data, "bankAccountNumber": existing_data.get("bankAccountNumber", "")}
    for key in _preserve_keys:
        if key not in new_data:
            default = [] if key == "visits" else ""
            new_data = {**new_data, key: existing_data.get(key, default)}
    conn.execute(
        "UPDATE vendor_contractors SET name=?, tax_id=?, contact_name=?, phone=?, email=?, address=?, data_json=?, updated_at=? WHERE id=?",
        (body.name.strip(), body.tax_id or '', body.contact_name or '',
         body.phone or '', body.email or '', body.address or '',
         json.dumps(new_data, ensure_ascii=False), now, vid)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.update', 'vendor_contractor', str(vid), body.name)
    return {"ok": True, "updated_at": now}


# ── 個資蒐集告知（CUSTOMIZATION-SPEC §9.3，2026-09-26 擴大到承攬商）──────────────────────
# 承攬商的聯絡人姓名、電話、Email、地址與帳戶可能是自然人（個人工作室／聯絡窗口）⇒ 告知對象是聯絡人。
# 紀錄存在 L1 設定鍵 `privacy_notice_acks`（`vendor_contractor:<id>`），伺服器蓋時間與人員，已記錄的不覆蓋。

@router.get("/api/vendor-contractors/{vid}/privacy-notice")
def get_vendor_privacy_ack(vid: int, authorization: str = Header(None)):
    from helpers import privacy_notice as _pn
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    return {"ack": _pn.get_ack("vendor_contractor", vid)}


@router.post("/api/vendor-contractors/{vid}/privacy-notice/ack")
def ack_vendor_privacy_notice(vid: int, authorization: str = Header(None)):
    """記錄「已告知當事人」：時間與人員由伺服器決定；已記錄的不覆蓋。"""
    from helpers import privacy_notice as _pn
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    conn = get_db()
    row = conn.execute("SELECT name, contact_name FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "找不到此承攬商")
    rec, created = _pn.record_purpose_ack("vendor_contractor", vid, user, "contact")
    if created:
        _audit(_tok(authorization), 'vendor.privacy_notice_ack', 'vendor_contractor', str(vid),
               row["name"], {"noticeHash": rec.get("noticeHash")})
    return {"ack": rec, "created": created}


@router.patch("/api/vendor-contractors/{vid}/active")
def toggle_vendor_active(vid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    conn = get_db()
    row = conn.execute("SELECT active, name FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    new_active = 0 if row["active"] else 1
    conn.execute("UPDATE vendor_contractors SET active=?, updated_at=? WHERE id=?",
                 (new_active, datetime.now().isoformat(), vid))
    conn.commit()
    conn.close()
    action = 'vendor.activate' if new_active else 'vendor.deactivate'
    _audit(_tok(authorization), action, 'vendor_contractor', str(vid), row["name"])
    notify_module_activity("承攬商管理", "啟用" if new_active else "停用",
                            user.get("display_name") or user["username"], row["name"], "vendor-contractors.html")
    return {"active": bool(new_active)}


@router.get("/api/vendor-contractors/{vid}/passbook")
def get_vendor_passbook(vid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    conn = get_db()
    row = conn.execute("SELECT data_json FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "承攬商不存在")
    try:
        data = json.loads(row["data_json"] or "{}")
    except Exception:
        data = {}
    if not _bm.can_see_full(user):         # 存簿影像上印著完整帳號 ⇒ 只有最高管理者
        return {"bank_passbook": "", "masked": bool(data.get("bankPassbookImage"))}
    return {"bank_passbook": data.get("bankPassbookImage", "")}


@router.put("/api/vendor-contractors/{vid}/passbook")
def upload_vendor_passbook(vid: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    passbook = body.get("bank_passbook", "")
    if passbook and not passbook.startswith("data:image/"):
        raise HTTPException(400, "無效的圖片格式，需為 data URI")
    if passbook:
        try: passbook = _stamp_passbook(passbook)
        except Exception: pass
    conn = get_db()
    existing = conn.execute("SELECT data_json, name FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    try:
        data = json.loads(existing["data_json"] or "{}")
    except Exception:
        data = {}
    data["bankPassbookImage"] = passbook
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE vendor_contractors SET data_json=?, updated_at=? WHERE id=?",
        (json.dumps(data, ensure_ascii=False), now, vid)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.passbook.update', 'vendor_contractor', str(vid), existing["name"])
    return {"ok": True, "updated_at": now}


@router.delete("/api/vendor-contractors/{vid}")
def delete_vendor_contractor(vid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    conn = get_db()
    row = conn.execute("SELECT name FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    cnt = conn.execute(
        "SELECT COUNT(*) FROM contractor_dispatches WHERE vendor_id=?", (vid,)
    ).fetchone()[0]
    if cnt > 0:
        conn.close()
        raise HTTPException(409, f"此承攬商有 {cnt} 筆派發紀錄，無法刪除，請改為停用")
    vname = row["name"]
    conn.execute("DELETE FROM vendor_contractors WHERE id=?", (vid,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.delete', 'vendor_contractor', str(vid), vname)
    notify_module_activity("承攬商管理", "刪除", user.get("display_name") or user["username"],
                            vname, "vendor-contractors.html")
    return {"ok": True}


@router.patch("/api/vendor-contractors/{vid}/visits")
def update_vendor_visits(vid: int, body: dict, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    conn = get_db()
    row = conn.execute(
        "SELECT name, data_json, updated_at FROM vendor_contractors WHERE id=?", (vid,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    expected = body.get("expectedUpdatedAt")
    if expected and row["updated_at"] and expected != row["updated_at"]:
        conn.close()
        raise HTTPException(409, "資料已被其他人更新，請重新載入後再存")
    d = json.loads(row["data_json"] or "{}")
    d["visits"] = body.get("visits", [])
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE vendor_contractors SET data_json=?, updated_at=? WHERE id=?",
        (json.dumps(d, ensure_ascii=False), now, vid)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.visit.update', 'vendor_contractor', str(vid),
           f"{row['name']}（{len(d['visits'])} 筆往來紀錄）")
    _latest_visit = d["visits"][-1] if d["visits"] else {}
    notify_module_activity("承攬商管理", "新增往來紀錄", user.get("display_name") or user["username"],
                            f"{row['name']}{('（' + _latest_visit['date'] + '）') if _latest_visit.get('date') else ''}",
                            "vendor-contractors.html", detail=_latest_visit.get("note", ""))
    return {"ok": True, "count": len(d["visits"]), "updated_at": now}


# ── 派發 CRUD ─────────────────────────────────────────────────────────────────

@router.get("/api/contractor-dispatches")
def list_dispatches(quote_no: Optional[str] = None, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list', 'quotation'), "承攬商管理")
    conn = get_db()
    if quote_no:
        rows = conn.execute(
            "SELECT d.*, v.name AS vendor_name FROM contractor_dispatches d "
            "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id "
            "WHERE d.quote_no=? ORDER BY d.created_at DESC",
            (quote_no,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT d.*, v.name AS vendor_name FROM contractor_dispatches d "
            "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id "
            "ORDER BY d.created_at DESC LIMIT 200"
        ).fetchall()
    out = _attach_delete_requests(conn, [_dispatch_row(r) for r in rows])
    conn.close()
    return out


@router.get("/api/contractor-dispatches/{did}")
def get_dispatch(did: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list', 'quotation'), "承攬商管理")
    conn = get_db()
    row = conn.execute(
        "SELECT d.*, v.name AS vendor_name FROM contractor_dispatches d "
        "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id WHERE d.id=?",
        (did,)
    ).fetchone()
    out = _attach_delete_requests(conn, [_dispatch_row(row)]) if row else None
    conn.close()
    if not row:
        raise HTTPException(404, "派發紀錄不存在")
    return out[0]


@router.post("/api/contractor-dispatches", status_code=201)
def create_dispatch(body: DispatchIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    _require_admin(user)
    now = datetime.now().isoformat()
    items = body.items_json or []
    personnel = body.personnel_json or []
    if not body.vendor_id and not personnel:
        raise HTTPException(400, "請至少選擇承攬商或外包名單人員其中一項")
    total = sum(float(it.get("amount", 0) or 0) for it in items)
    conn = get_db()
    vendor_name = ""
    if body.vendor_id:
        vrow = conn.execute("SELECT name FROM vendor_contractors WHERE id=?", (body.vendor_id,)).fetchone()
        if not vrow:
            conn.close()
            raise HTTPException(404, "承攬商不存在")
        vendor_name = vrow["name"]
    # 31-A：新建的派發一律是「草稿＋審核狀態 草稿」，body 帶的 status 一律忽略（狀態只能由操作按鈕經 dispatch_flow.set_status 改）；單號 DP- 在寫鎖內取號
    _begin_write(conn)
    doc_code = _flow.next_dispatch_code(conn)
    cur = conn.execute(
        "INSERT INTO contractor_dispatches "
        "(quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, total_amount, tax_rate, status, notes, invoice_no, payable_date, invoice_date, created_by, created_at, updated_at,"
        " approval_status, doc_code) "
        "VALUES (?,?,?,?,?,?,?,?,'draft',?,?,?,?,?,?,?,?,?)",
        (body.quote_no, body.vendor_id, body.dispatch_date or '',
         body.scope or '', json.dumps(items, ensure_ascii=False),
         json.dumps(personnel, ensure_ascii=False), total,
         body.tax_rate if body.tax_rate is not None else 0.05,
         body.notes or '', body.invoice_no or '',
         body.payable_date or '', normalize_date(body.invoice_date, "發票日期"),
         user["username"], now, now, _flow.DRAFT, doc_code)
    )
    did = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.dispatch.create', 'contractor_dispatch', str(did),
           f"{body.quote_no}")
    dispatch_label = f"{body.quote_no}" + (f"（{vendor_name}）" if vendor_name else "（外包人員點工）")
    notify_module_activity("承攬商派發", "建立", user.get("display_name") or user["username"],
                            dispatch_label, "vendor-contractors.html", detail=body.scope or "")
    return {"id": did, "created_at": now, "total_amount": total, "status": "draft", "approvalStatus": _flow.DRAFT, "docCode": doc_code}


@router.put("/api/contractor-dispatches/{did}")
def update_dispatch(did: int, body: DispatchIn, authorization: str = Header(None)):
    """2026-08-28 補上守門：已產生匯款申請的派發不可再編輯金額相關欄位——
    delete_dispatch() 原本就有這個檢查（避免刪除已被匯款申請引用的紀錄），但
    editing 路徑（這支 PUT）完全沒有對應防護，派發的 total_amount/items_json/
    personnel_json 在匯款申請核准、甚至財務已標記「已匯款」之後仍可被悄悄改掉，
    讓 contractor_payment_vouchers.snapshot_json 記錄的金額（財務實際依此匯款）
    跟派發紀錄的即時金額（案件管理承攬商Tab／資金水位／月支出報表都讀這個）
    對不上，且完全沒有任何比對或警示機制——比精算快照過期更嚴重，因為牽涉的是
    已經送出去、甚至已經執行的財務文件。修法比照 delete_dispatch() 同一套判斷：
    偵測到已有對應的匯款申請就直接 409 擋下，要改請先撤銷/處理該申請。"""
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    _require_admin(user)
    now = datetime.now().isoformat()
    items = body.items_json or []
    personnel = body.personnel_json or []
    if not body.vendor_id and not personnel:
        raise HTTPException(400, "請至少選擇承攬商或外包名單人員其中一項")
    total = sum(float(it.get("amount", 0) or 0) for it in items)
    conn = get_db()
    existing = conn.execute("SELECT * FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "派發紀錄不存在")
    if not has_finance_access(user):          # 第42班（Q5）：含金額欄位（品項／人員金額、稅率）與發票日的修改 ⇒ 財務角色；其餘欄位（承攬商、範圍、備註…）維持一般管理
        def _jl(v):
            try:
                return json.loads(v or "[]")
            except Exception:
                return []
        _new_inv = body.invoice_date
        if (_amounts(items) != _amounts(_jl(existing["items_json"]))
                or _amounts(personnel) != _amounts(_jl(existing["personnel_json"]))
                or float(body.tax_rate if body.tax_rate is not None else 0.05) != float(existing["tax_rate"] if existing["tax_rate"] is not None else 0.05)
                or (_new_inv is not None and (_new_inv or "") != (existing["invoice_date"] or ""))):
            conn.close()
            raise HTTPException(403, "修改派發的金額、稅率或發票日需要財務角色")
    # 31-A：狀態不能經由編輯改（只有操作按鈕走 dispatch_flow.set_status）；送審中（任一段）整筆不可編輯
    if body.status and body.status != (existing["status"] or "draft"):
        conn.close()
        raise HTTPException(400, "不能在編輯時改狀態：請使用派發卡片上的操作按鈕（送審、確認驗收、申請完工、取消…）")
    if (existing["approval_status"] in (_flow.PENDING, _flow.IN_PROGRESS)) or (existing["completion_status"] in (_flow.PENDING, _flow.IN_PROGRESS)):
        conn.close()
        raise HTTPException(409, "這筆派發正在審核中，不能編輯（請先撤回或等審核結果）")
    voucher = conn.execute(
        "SELECT voucher_no FROM contractor_payment_vouchers WHERE dispatch_id=? AND voided_at=''", (did,)
    ).fetchone()
    if voucher:
        conn.close()
        raise HTTPException(409, f"此派發已產生匯款申請（{voucher['voucher_no']}），請先撤銷/處理該申請後再編輯")
    if body.expected_updated_at and existing["updated_at"] and body.expected_updated_at != existing["updated_at"]:
        conn.close()
        raise HTTPException(409, "派發紀錄已被其他人更新，請重新載入後再存")
    if body.vendor_id and not conn.execute("SELECT id FROM vendor_contractors WHERE id=?", (body.vendor_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    # 實質欄位（承攬商、品項、人員、稅率）有變：已核准的與舊單都要重新送審（審核狀態回「草稿」、清掉核准紀錄）；沒變的欄位（備註、日期、發票）照舊可改
    new_rate = body.tax_rate if body.tax_rate is not None else 0.05
    changed = _flow.substantive_hash(existing["vendor_id"], existing["items_json"], existing["personnel_json"], existing["tax_rate"]) !=         _flow.substantive_hash(body.vendor_id, items, personnel, new_rate)
    # 使用者裁示（第 32 班 S-1）：只有「已核准」的派發實質編輯後回草稿重新送審；**舊單（approval_status=''）維持舊單**——
    # 不重設、成本與總帳不掉，改為寫稽核列並在畫面警示「舊單已修改」（approval_json 記修改人與時間）。
    reset = changed and existing["approval_status"] == _flow.APPROVED
    legacy_modified = changed and existing["approval_status"] == ""
    old_total = float(existing["total_amount"] or 0)
    conn.execute(
        "UPDATE contractor_dispatches SET vendor_id=?, dispatch_date=?, scope=?, items_json=?, "
        "personnel_json=?, total_amount=?, tax_rate=?, notes=?, invoice_no=?, payable_date=?, invoice_date=?, updated_at=? WHERE id=?",
        (body.vendor_id, body.dispatch_date or '', body.scope or '',
         json.dumps(items, ensure_ascii=False),
         json.dumps(personnel, ensure_ascii=False), total,
         new_rate, body.notes or '', body.invoice_no or '',
         body.payable_date or '',
         existing["invoice_date"] if body.invoice_date is None else normalize_date(body.invoice_date, "發票日期"),
         now, did)
    )
    if reset:
        _begin_write(conn)
        code = existing["doc_code"] or _flow.next_dispatch_code(conn)
        conn.execute("UPDATE contractor_dispatches SET approval_status=?, approval_json='{}', approved_hash='', approved_at='', doc_code=? WHERE id=?",
                     (_flow.DRAFT, code, did))
    if legacy_modified:
        try:
            marker = json.loads(existing["approval_json"] or "{}")
        except ValueError:
            marker = {}
        if not isinstance(marker, dict):
            marker = {}
        prev = marker.get("legacyModified") if isinstance(marker.get("legacyModified"), dict) else {}
        marker["legacyModified"] = {"at": now, "by": user["username"], "count": int(prev.get("count") or 0) + 1,
                                    "firstAt": prev.get("firstAt") or now}
        conn.execute("UPDATE contractor_dispatches SET approval_json=? WHERE id=?", (json.dumps(marker, ensure_ascii=False), did))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.dispatch.update', 'contractor_dispatch', str(did), body.quote_no)
    if legacy_modified:                                           # 舊單被實質修改：獨立一筆稽核（前後金額），不重設審核狀態
        _audit(_tok(authorization), 'vendor.dispatch.legacy_edit', 'contractor_dispatch', str(did), body.quote_no,
               {"docCode": existing["doc_code"] or "", "totalBefore": old_total, "totalAfter": total})
    return {"ok": True, "updated_at": now, "total_amount": total, "needsResubmit": bool(reset),
            **({"legacyModified": True} if legacy_modified else {})}


@router.delete("/api/contractor-dispatches/{did}")
def delete_dispatch(did: int, authorization: str = Header(None)):
    """刪除派發＝送進刪除暫存區（30 天內最高管理者可還原，含附件與勞報單連結）。規則不變：審核中／已核准／已有匯款申請不可刪
    （已核准的只有最高管理者能走暫存區的『刪除已核可』入口，`/api/recycle-bin/delete-approved`）。
    暫存區模組不在 ⇒ 照舊刪資料列（附件留在原處）並在回應 notice 與稽核明說。"""
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    conn = get_db()
    try:
        _begin_write(conn)
        row = conn.execute("SELECT quote_no FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
        if not row:
            raise HTTPException(404, "派發紀錄不存在")
        notice = ""
        try:
            res = recycle_bin.delete(conn, _rb_adapter.ET_DISPATCH, did, user)
        except recycle_bin.BinError as e:
            conn.rollback()
            raise HTTPException(409, str(e))
        if res is None:                                                      # 暫存區模組不在：照舊刪（不刪附件）並明說
            ad = _rb_adapter.DispatchBinAdapter()
            ok, why = ad.can_delete(conn, did, user)
            if not ok:
                raise HTTPException(409, why)
            ad.delete_in_tx(conn, did)
            notice = "刪除暫存區未啟用：此派發已永久刪除，無法還原"
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'vendor.dispatch.delete', 'contractor_dispatch', str(did), row["quote_no"],
           {"bin": True, "binId": res["bin_id"], "purgeAfter": res["purge_after"]} if res else {"bin": False, "notice": notice})
    notify_module_activity("承攬商派發", "刪除", user.get("display_name") or user["username"],
                            row["quote_no"], "vendor-contractors.html")
    out = {"ok": True, "binned": bool(res)}
    if res:
        out.update(binId=res["bin_id"], purgeAfter=res["purge_after"])
    else:
        out["notice"] = notice
    return out


# ── 承攬商報價附件 ────────────────────────────────────────────────────────────

@router.post("/api/contractor-dispatches/{did}/files", status_code=201)
async def upload_dispatch_files(did: int, files: List[UploadFile] = File(...),
                                authorization: str = Header(None)):
    """承攬商報價/估價文件上傳（2026-08-25 新增，多檔，admin+，比照
    quotations.py::upload_material_files 的存法）——存承攬商提供的原始報價
    文件本身，跟 items_json 拆解後的品項明細是分開的兩件事。"""
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    _require_admin(user)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT quote_no, files_json FROM contractor_dispatches WHERE id=?", (did,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "派發紀錄不存在")
        try:
            existing = json.loads(row["files_json"] or "[]")
        except Exception:
            existing = []
        new_files = await save_document_files("contractor_dispatches", str(did), files,
                                              user.get("display_name") or user["username"])
        existing.extend(new_files)
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE contractor_dispatches SET files_json=?, updated_at=? WHERE id=?",
            (json.dumps(existing, ensure_ascii=False), now, did)
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "vendor.dispatch.upload_files", "contractor_dispatch", str(did),
           f"{row['quote_no']}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files, "updated_at": now}


def _load_quote_files(conn, did):
    row = conn.execute("SELECT quote_no, files_json FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
    if not row:
        raise HTTPException(404, "派發紀錄不存在")
    try:
        files = json.loads(row["files_json"] or "[]")
    except Exception:
        files = []
    return row, files


def _save_quote_files(conn, did, files):
    now = datetime.now().isoformat()
    conn.execute("UPDATE contractor_dispatches SET files_json=?, updated_at=? WHERE id=?",
                 (json.dumps(files, ensure_ascii=False), now, did))
    return now


def _quote_file(files, file_id):
    f = next((x for x in files if x.get("id") == file_id), None)
    if not f:
        raise HTTPException(404, "找不到指定的檔案")
    return f


def _open_delete_request(conn, did, fid):
    return conn.execute("SELECT * FROM dispatch_file_delete_requests WHERE dispatch_id=? AND file_id=? AND status='待審核'"
                        " ORDER BY id DESC LIMIT 1", (did, fid)).fetchone()


def _request_view(r):
    """申請列 ⇒ 檔案上顯示用的 deleteRequest（簽核鏈解析不了 ⇒ 空鏈，不丟例外；佇列那邊另外擋壞資料）。"""
    try:
        a = json.loads(r["approval_json"] or "{}")
        a = a if isinstance(a, dict) else {}
    except (TypeError, ValueError):
        a = {}
    return {"requestedBy": r["requested_by"], "requestedByDisplay": a.get("requestedByDisplay") or r["requested_by"],
            "requestedAt": r["requested_at"], "reason": r["reason"], "tiers": a.get("tiers") or [],
            "currentTier": a.get("currentTier") or 0}


def _attach_delete_requests(conn, dispatches):
    """派工單的附件加上 `deleteRequest`（有待審的刪除申請才有；畫面標「刪除待審」）。"""
    ids = [d["id"] for d in dispatches if d.get("files")]
    if not ids:
        return dispatches
    reqs = {}
    for r in conn.execute("SELECT * FROM dispatch_file_delete_requests WHERE status='待審核' AND dispatch_id IN (%s)"
                          " ORDER BY id" % ",".join("?" * len(ids)), ids).fetchall():
        reqs[(r["dispatch_id"], r["file_id"])] = r
    for d in dispatches:
        for f in d.get("files") or []:
            r = reqs.get((d["id"], f.get("id")))
            if r is not None:
                f["deleteRequest"] = _request_view(r)
    return dispatches


@router.delete("/api/contractor-dispatches/{did}/files/{file_id}")
def delete_dispatch_file(did: int, file_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """承攬商報價單附件刪除＝**申請刪除，要審核**（N1，2026-09-30 使用者裁示；簽核走案件既有簽核層級＝報價單的流程設定，預設統一流程）。

    - 核可前檔案保留，檔案上標 `deleteRequest`（畫面標「刪除待審」）；核可（走完全部簽核層）才真的刪檔；退回＝結案這份申請、檔案照舊。
    - 沒有簽核層（或申請人的部門主管解析不出來）：申請人是最高管理者 ⇒ 直接刪；其他人 ⇒ 由最高管理者核可。
    - 同一個檔案已有待審的刪除申請 ⇒ 409；申請人、原因、時間存在 `dispatch_file_delete_requests`＋稽核。"""
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    _require_admin(user)
    reason = str((body or {}).get("reason") or "").strip()
    conn = get_db()
    try:
        row, files = _load_quote_files(conn, did)
        f = _quote_file(files, file_id)
        if _open_delete_request(conn, did, file_id) is not None:
            raise HTTPException(409, "這個檔案已有待審核的刪除申請")
        try:
            tiers = setting_to_active_tiers(resolve_active_flow_setting("quotation"), conn, user["username"])
        except UnresolvedManagerError:
            tiers = []          # 申請人沒有歸屬部門／主管解析不出來 ⇒ 不卡死，由最高管理者核可
        now = datetime.now().isoformat()
        if not tiers and user["role"] == "superadmin":
            updated = delete_document_file("contractor_dispatches", str(did), files, file_id)
            now = _save_quote_files(conn, did, updated)
            conn.commit()
            deleted = True
        else:
            appr = {"requestedBy": user["username"], "requestedByDisplay": user.get("display_name") or user["username"],
                    "requestedAt": now, "tiers": tiers, "currentTier": 0}
            conn.execute(
                "INSERT INTO dispatch_file_delete_requests (dispatch_id, file_id, quote_no, filename, reason, status, approval_json,"
                " requested_by, requested_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (did, file_id, row["quote_no"] or "", f.get("filename") or "", reason, "待審核",
                 json.dumps(appr, ensure_ascii=False), user["username"], now))
            conn.commit()
            deleted = False
    finally:
        conn.close()
    if deleted:
        _audit(_tok(authorization), "vendor.dispatch.delete_file", "contractor_dispatch", str(did), row["quote_no"])
        return {"ok": True, "deleted": True, "updated_at": now}
    _audit(_tok(authorization), "vendor.dispatch.delete_file_request", "contractor_dispatch", str(did),
           "%s 報價單附件「%s」申請刪除：%s" % (row["quote_no"], f.get("filename", ""), reason))
    for a in (tiers[0].get("approvers") or []) if tiers else []:
        _notify(a["username"], "dispatch_file_delete_request", str(did), row["quote_no"],
                "承攬商報價單附件「%s」（案件 %s）申請刪除，需要您審核" % (f.get("filename", ""), row["quote_no"]))
    if not tiers:
        notify_module_activity("承攬商報價單", "申請刪除附件（待最高管理者審核）", user.get("display_name") or user["username"],
                               row["quote_no"], "case-management.html", detail=f.get("filename", ""))
    return {"ok": True, "deleted": False, "pending": True, "updated_at": now}


def _can_decide_delete(conn, req, user):
    """⇒ (ok, status, msg)。有簽核層：當層排序最前的未簽人（或其有效代理人）；沒有簽核層：只有最高管理者。
    申請人不能核可／退回自己的刪除申請（稽核 M4；「沒簽核層、最高管理者自己申請」是直接刪、不會有申請，故無例外）。"""
    if (req.get("requestedBy") or "") == user["username"]:
        return False, 403, "不能審核自己送出的刪除申請"
    tiers = req.get("tiers") or []
    if tiers:
        return check_approve_permission(tiers, req.get("currentTier") or 0, user["username"], conn=conn)
    if user["role"] != "superadmin":
        return False, 403, "沒有設定簽核層，僅最高管理者可審核刪除申請"
    return True, None, None


@router.post("/api/contractor-dispatches/{did}/files/{file_id}/delete-approve")
def approve_dispatch_file_delete(did: int, file_id: str, authorization: str = Header(None)):
    """核可刪除：簽完當層 → 下一層；全部簽完才真的刪檔。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        r = _open_delete_request(conn, did, file_id)
        if r is None:
            raise HTTPException(409, "這個檔案沒有待審核的刪除申請")
        req = _request_view(r)
        ok, code, msg = _can_decide_delete(conn, req, user)
        if not ok:
            raise HTTPException(code, msg)
        tiers = req["tiers"]
        done = True
        if tiers:
            ct = req["currentTier"]
            approvers = tiers[ct].get("approvers") or []
            nxt = next((a for a in approvers if a.get("status") != "approved"), None)
            if nxt is None:
                raise HTTPException(409, "此層所有簽核人員已完成")
            nxt["status"] = "approved"
            nxt["approvedAt"] = datetime.now().isoformat()
            done = False
            if all(a.get("status") == "approved" for a in approvers):
                req["currentTier"] = ct + 1
                done = req["currentTier"] >= len(tiers)
        now = datetime.now().isoformat()
        if done:
            row, files = _load_quote_files(conn, did)
            if any(x.get("id") == file_id for x in files):
                files = delete_document_file("contractor_dispatches", str(did), files, file_id)
                now = _save_quote_files(conn, did, files)
            conn.execute("UPDATE dispatch_file_delete_requests SET status='已核可', decided_by=?, decided_at=? WHERE id=?",
                         (user["username"], now, r["id"]))
        else:
            appr = json.loads(r["approval_json"] or "{}")
            appr["tiers"], appr["currentTier"] = tiers, req["currentTier"]
            conn.execute("UPDATE dispatch_file_delete_requests SET approval_json=? WHERE id=?",
                         (json.dumps(appr, ensure_ascii=False), r["id"]))
        conn.commit()
        quote_no, filename = r["quote_no"], r["filename"]
    finally:
        conn.close()
    if done:
        _audit(_tok(authorization), "vendor.dispatch.delete_file", "contractor_dispatch", str(did),
               "%s 報價單附件「%s」刪除已核可（申請人 %s）" % (quote_no, filename, req["requestedBy"]))
    else:
        _audit(_tok(authorization), "vendor.dispatch.delete_file_approve", "contractor_dispatch", str(did),
               "%s 報價單附件「%s」刪除申請簽核一層" % (quote_no, filename))
        for na in (tiers[req["currentTier"]].get("approvers") or []) if req["currentTier"] < len(tiers) else []:
            _notify(na["username"], "dispatch_file_delete_request", str(did), quote_no,
                    "承攬商報價單附件「%s」（案件 %s）刪除申請輪到您審核" % (filename, quote_no))
    return {"ok": True, "deleted": done, "allDone": done, "updated_at": now}


@router.post("/api/contractor-dispatches/{did}/files/{file_id}/delete-reject")
def reject_dispatch_file_delete(did: int, file_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """退回刪除申請：檔案照舊保留、結案這份申請（原因寫稽核，並通知申請人）。"""
    user = _require_user(authorization)
    note = str((body or {}).get("note") or "").strip()
    conn = get_db()
    try:
        r = _open_delete_request(conn, did, file_id)
        if r is None:
            raise HTTPException(409, "這個檔案沒有待審核的刪除申請")
        ok, code, msg = _can_decide_delete(conn, _request_view(r), user)
        if not ok:
            raise HTTPException(code, msg)
        now = datetime.now().isoformat()
        conn.execute("UPDATE dispatch_file_delete_requests SET status='已退回', decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                     (user["username"], now, note, r["id"]))
        conn.commit()
        quote_no, filename, requester = r["quote_no"], r["filename"], r["requested_by"]
    finally:
        conn.close()
    _audit(_tok(authorization), "vendor.dispatch.delete_file_reject", "contractor_dispatch", str(did),
           "%s 報價單附件「%s」刪除申請被退回：%s" % (quote_no, filename, note))
    _notify(requester, "dispatch_file_delete_rejected", str(did), quote_no,
            "承攬商報價單附件「%s」的刪除申請被退回（檔案保留）%s" % (filename, "：" + note if note else ""))
    return {"ok": True, "updated_at": datetime.now().isoformat()}


# ── 簽核佇列：承攬商報價單附件刪除申請（IP-10 `approval.queue_items`，type＝`dispatch_file_delete`）──
# 一個待審的刪除申請＝佇列的一張卡；單號（項目的 quoteNo 欄）＝「派工id:檔案id」，掛的案件在 linkedQuoteNo。
# 核可／退回打 `POST /api/contractor-dispatches/{派工id}/files/{檔案id}/delete-approve|delete-reject`（佇列頁依 type 組網址）。

def delete_queue_items(conn) -> list:
    """`approval.queue_items`：待審核的承攬商報價單附件刪除申請。簽核鏈壞掉的那一筆跳過（`approval_raw_of` 記 ERROR）。"""
    from helpers import approval_queue as _aq
    items = []
    for r in conn.execute("SELECT * FROM dispatch_file_delete_requests WHERE status='待審核' ORDER BY id DESC").fetchall():
        raw = _aq.approval_raw_of(r["approval_json"], "dispatch_file_delete", "%s:%s" % (r["dispatch_id"], r["file_id"]))
        if raw is None:
            continue
        fld = _aq.tier_fields(raw)
        items.append(_aq.base_item(
            "dispatch_file_delete", "%s:%s" % (r["dispatch_id"], r["file_id"]), fld,
            projectName="報價單附件「%s」申請刪除" % (r["filename"] or ""),
            quoteDate=(r["requested_at"] or "")[:10], linkedQuoteNo=r["quote_no"],
            dispatchId=r["dispatch_id"], fileId=r["file_id"], filename=r["filename"] or "", reason=r["reason"] or ""))
    return items


def delete_queue_detail(conn, doc_id):
    """`approval.detail`（dispatch_file_delete）：id＝「派工id:檔案id」；權限、案件抬頭在 L1。"""
    did, _, fid = str(doc_id).partition(":")
    r = conn.execute("SELECT * FROM dispatch_file_delete_requests WHERE CAST(dispatch_id AS TEXT)=? AND file_id=? AND status='待審核'"
                     " ORDER BY id DESC LIMIT 1", (did, fid)).fetchone()
    if r is None:
        return None
    from helpers import approval_queue as _aq
    files = []
    d = conn.execute("SELECT files_json FROM contractor_dispatches WHERE id=?", (r["dispatch_id"],)).fetchone()
    if d is not None:
        try:
            files = [x for x in _aq.file_entries(d["files_json"]) if x.get("id") == fid]
        except Exception:                                                            # noqa: BLE001
            files = []
    return {"quoteNo": r["quote_no"], "title": "報價單附件刪除申請",
            "approvalRaw": json.dumps({"tiers": _aq.tier_fields(r["approval_json"])["tiers"], "requestedBy": r["requested_by"]},
                                      ensure_ascii=False),
            "fields": [{"label": "附件", "value": r["filename"] or "—"},
                       {"label": "刪除原因", "value": r["reason"] or "—"},
                       {"label": "申請人", "value": r["requested_by"] or "—"},
                       {"label": "申請時間", "value": (r["requested_at"] or "—")[:16].replace("T", " ")}],
            "items": [], "files": files}


# ── 廠商發票附件 ──────────────────────────────────────────────────────────────

@router.post("/api/contractor-dispatches/{did}/invoice-files", status_code=201)
async def upload_dispatch_invoice_files(did: int, files: List[UploadFile] = File(...),
                                        authorization: str = Header(None)):
    """廠商發票上傳（2026-08-30 新增，多檔，admin+）——跟既有 files_json（承攬商
    報價/估價文件）、invoice_no（純文字發票號碼）是不同欄位，各自獨立存放，
    避免混用。存入 invoice_files_json，會在產生匯款申請當下一併凍結進
    snapshot_json（見 contractor_vouchers.py::create_contractor_voucher）。"""
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    _require_finance(user)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT quote_no, invoice_files_json FROM contractor_dispatches WHERE id=?", (did,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "派發紀錄不存在")
        try:
            existing = json.loads(row["invoice_files_json"] or "[]")
        except Exception:
            existing = []
        new_files = await save_document_files("contractor_dispatch_invoices", str(did), files,
                                              user.get("display_name") or user["username"])
        existing.extend(new_files)
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE contractor_dispatches SET invoice_files_json=?, updated_at=? WHERE id=?",
            (json.dumps(existing, ensure_ascii=False), now, did)
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "vendor.dispatch.upload_invoice_files", "contractor_dispatch", str(did),
           f"{row['quote_no']}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files, "updated_at": now}


@router.delete("/api/contractor-dispatches/{did}/invoice-files/{file_id}")
def delete_dispatch_invoice_file(did: int, file_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    _require_finance(user)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT quote_no, invoice_files_json FROM contractor_dispatches WHERE id=?", (did,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "派發紀錄不存在")
        try:
            existing = json.loads(row["invoice_files_json"] or "[]")
        except Exception:
            existing = []
        updated = delete_document_file("contractor_dispatch_invoices", str(did), existing, file_id)
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE contractor_dispatches SET invoice_files_json=?, updated_at=? WHERE id=?",
            (json.dumps(updated, ensure_ascii=False), now, did)
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "vendor.dispatch.delete_invoice_file", "contractor_dispatch", str(did), row["quote_no"])
    return {"ok": True, "updated_at": now}


@router.patch("/api/contractor-dispatches/{did}/invoice-date")
def set_dispatch_invoice_date(did: int, body: dict = Body(...), authorization: str = Header(None)):
    """`AC2`：登錄廠商發票日期（''＝清除）。**產生匯款申請之後也可以登**——

    廠商發票通常是請款時才拿到，而 PUT 在有匯款申請後整筆 409（保護金額）；
    發票日期不影響任何金額，只決定權責口徑歸哪個月，比照發票附件端點不擋。
    """
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    _require_finance(user)
    inv = normalize_date((body or {}).get("invoiceDate"), "發票日期")
    conn = get_db()
    try:
        row = conn.execute("SELECT quote_no, invoice_date FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
        if not row:
            raise HTTPException(404, "派發紀錄不存在")
        if inv and conn.execute("SELECT 1 FROM contractor_payment_vouchers WHERE dispatch_id=? AND kind<>'' AND voided_at=''", (did,)).fetchone():
            raise HTTPException(409, "這張派發已改用分期匯款申請：發票請登在各期的匯款申請上（總帳逐張認列，派發層不再認列）")
        now = datetime.now().isoformat()
        # MONEY-FLOWS §9 L3：發票日進 E04 雜湊；已入帳的 E04 會在下次引擎執行時 drift（沖轉草稿＋新草稿）。
        # 下游效應：營運報表權責口徑立即換月；總帳要手動執行才反映。這裡只提示、不擋（註解：發票日刻意不擋）。
        gl_warn = gl_posted_warning(conn, "contractor_dispatch", str(did)) if inv != (row["invoice_date"] or "") else None
        conn.execute("UPDATE contractor_dispatches SET invoice_date=?, updated_at=? WHERE id=?", (inv, now, did))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "vendor.dispatch.invoice_date", "contractor_dispatch", str(did),
           "%s 發票日期：%s → %s" % (row["quote_no"], row["invoice_date"] or "（未登錄）", inv or "（未登錄）"))
    return {"ok": True, "invoiceDate": inv, "updated_at": now,
            **({"glWarning": gl_warn.replace("此筆", "此筆（派工單 %s／%s）" % (did, row["quote_no"]), 1)} if gl_warn else {})}


# ── 驗收流程節點 ──────────────────────────────────────────────────────────────

_ACCEPT_ALLOWED_FROM = {
    "pending_acceptance": ("draft", "sent", "confirmed"),
    "accepted": ("pending_acceptance",),
}

@router.patch("/api/contractor-dispatches/{did}/accept")
def accept_dispatch(did: int, body: dict, authorization: str = Header(None)):
    """驗收流程節點：
    action=pending_acceptance — 標記待驗收（admin+，來源：draft/sent/confirmed）
    action=accepted          — 確認驗收（admin+，來源：pending_acceptance），記錄驗收人與時間
    """
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    action = body.get("action", "")
    if action not in _ACCEPT_ALLOWED_FROM:
        raise HTTPException(400, "不支援的驗收操作：請使用派工列上的「待驗收」或「確認驗收」按鈕。")
    return dispatch_status_audited(did, action, user, authorization, reason="", legacy_action=True)


def dispatch_status_audited(did, target, user, authorization, *, reason="", legacy_action=False):
    """所有「改作業狀態」的端點共用：讀列 → `dispatch_flow.set_status`（唯一寫入口）→ commit → 稽核／通知。"""
    conn = get_db()
    try:
        _begin_write(conn)
        row = conn.execute("SELECT * FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
        if not row:
            raise HTTPException(404, "派發紀錄不存在")
        if legacy_action:
            cur = row["status"] or "draft"
            if cur not in _ACCEPT_ALLOWED_FROM[target]:       # 沿用既有訊息（/accept 的來源狀態限制）
                allowed_labels = "、".join(_STATUS_LABELS.get(x, x) for x in _ACCEPT_ALLOWED_FROM[target])
                raise HTTPException(409, f"目前狀態「{_STATUS_LABELS.get(cur, cur)}」無法執行此操作（需為：{allowed_labels}）")
        try:
            res = _flow.set_status(conn, row, target, user, reason=reason)
        except _flow.FlowError as e:
            raise HTTPException(e.status_code, str(e))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), f'vendor.dispatch.{target}', 'contractor_dispatch', str(did), row["quote_no"],
           {"from": res["prev"], "to": res["new"], "reason": reason, "note": res["note"], "docCode": row["doc_code"] or "",
            **({"closedStages": [c["stage"] for c in res["closed"]]} if res.get("closed") else {})})
    for c in res.get("closed") or []:                              # 通知送審人：派發已取消、審核已關閉（不放金額）
        if c["requestedBy"]:
            _notify(c["requestedBy"], "dispatch_returned", str(did), row["quote_no"],
                    "派發 %s 已取消，%s已關閉" % (row["doc_code"] or ("#%s" % did), "完工審核" if c["stage"] == "completion" else "派發審核"))
    notify_module_activity("承攬商派發", _STATUS_LABELS.get(target, target),
                            user.get("display_name") or user["username"], row["quote_no"], "vendor-contractors.html")
    return {"ok": True, "status": target, "updated_at": datetime.now().isoformat()}


@router.post("/api/contractor-dispatches/{did}/status")
def set_dispatch_status(did: int, body: dict, authorization: str = Header(None)):
    """卡片上的操作按鈕（已送出／已確認／取消…；待驗收與確認驗收也可走這裡）。`completed` 不能由這裡設定（只有完工審核通過）。
    取消已核准或已進入驗收的派發要 `reason`；已有匯款申請者只有最高管理者。"""
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    target = str((body or {}).get("target") or "")
    if target not in _flow.STATUSES:
        raise HTTPException(400, "不認得的狀態")
    return dispatch_status_audited(did, target, user, authorization, reason=str((body or {}).get("reason") or ""))


# ── 回推報價單品項 ────────────────────────────────────────────────────────────

@router.post("/api/contractor-dispatches/{did}/import-to-quote")
def import_dispatch_to_quote(did: int, authorization: str = Header(None)):
    """將派發報價品項以「外包成本」方式附加至報價單的品項清單。
    僅限報價單為草稿（status='草稿'）狀態；已送出需先在報價單頁面解鎖。"""
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'contractor_list'), "承攬商管理")
    conn = get_db()
    # Load dispatch
    drow = conn.execute(
        "SELECT d.*, v.name AS vendor_name FROM contractor_dispatches d "
        "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id WHERE d.id=?",
        (did,)
    ).fetchone()
    if not drow:
        conn.close()
        raise HTTPException(404, "派發紀錄不存在")
    # 報價單的格式與寫入歸 M01（IP-17 `quotation.append_items`）：本模組只交出中性的品項，
    # M01 在同一筆交易內（本函式已拿寫鎖）讀單、檢查草稿、換成報價品項並存檔。M01 不在 ⇒ 409 明說。
    append = _registry.single_provider("quotation.append_items")
    if append is None:
        conn.close()
        raise HTTPException(409, QUOTE_IMPORT_UNAVAILABLE)
    with write_txn(conn):   # lost update；區塊內任何例外 ⇒ rollback＋關連線（不留寫鎖）
        vendor_name = drow["vendor_name"] or (f"承攬商#{drow['vendor_id']}" if drow["vendor_id"] else "外包人員（點工）")
        dispatch_items = []
        try:
            dispatch_items = json.loads(drow["items_json"] or "[]")
        except Exception:
            pass
        # cost＝承攬單價（外包成本）；毛利與售價由 M01 依報價單規則處理
        items = [{"description": it.get("description", ""),
                  "qty": float(it.get("qty", 1) or 1),
                  "unit": it.get("unit", "式"),
                  "cost": float(it.get("unitPrice", 0) or 0),
                  "note": it.get("note", "")} for it in dispatch_items]
        now = datetime.now().isoformat()
        append(conn, drow["quote_no"], f"外包承攬 — {vendor_name}", items, now)
        conn.commit()
        conn.close()
        _audit(_tok(authorization), 'vendor.dispatch.import', 'contractor_dispatch', str(did),
               f"匯入 {len(dispatch_items)} 品項至 {drow['quote_no']}")
        notify_module_activity("承攬商派發", "匯入報價單品項", user.get("display_name") or user["username"],
                                f"{vendor_name} → {drow['quote_no']}", "vendor-contractors.html")
        return {"ok": True, "imported": len(dispatch_items), "updated_at": now}


#: IP-17 對方不在時的說明
QUOTE_IMPORT_UNAVAILABLE = "案件模組未安裝：無法把派工品項匯入報價單"


def list_dispatches_for_case(quote_no: str, authorization: str) -> list:
    """IP-15 `dispatch.list_for_case`：M01 案件整包的承攬派工段；授權與權限判斷與 `list_dispatches` 同一份。"""
    return list_dispatches(quote_no=quote_no, authorization=authorization)


#: 成本檢視放行的模組：財務、出納（傳票要列承攬商支出）＋原本就看得到派工清單的三個（主持裁示 2026-09-26 19:09：
#: 不同意「403 就不列」——會計會悄悄少列支出）
COST_VIEW_MODULES = ("finance", "cashier", "procurement", "case_manage", "contractor_list")


def dispatch_cost_view(d: dict) -> dict:
    """`_dispatch_row` 的結果 ⇒ 成本檢視（純函式）。**白名單**：金額、日期、案件、廠商名稱、派工描述（scope）、發票號、
    品項描述＋金額、外包人數。〔scope、invoiceNo 主持裁示加入（會計資料、不是個資；不加 ⇒ 傳票摘要靜默縮減）〕
    不回外包人員姓名與 personnel、不回其他派工細節（notes、files、狀態、建立者、驗收者…）。
    金額與 `dispatch.row` 同一份算法（grandTotal＝含稅承攬商費用＋外包人員）。"""
    personnel = d.get("personnel") or []
    return {
        "id": d["id"],
        "quoteNo": d.get("quoteNo") or "",
        "vendorName": d.get("vendorName") or "",
        "scope": d.get("scope") or "",
        "invoiceNo": d.get("invoiceNo") or "",
        "dispatchDate": d.get("dispatchDate") or "",
        "invoiceDate": d.get("invoiceDate") or "",
        "payableDate": d.get("payableDate") or "",
        "amount": d.get("grandTotal") or 0,
        "approvalPending": (d.get("approvalStatus") or "") in (_flow.PENDING, _flow.IN_PROGRESS),     # 31-A：待審核仍計入、但標示
        "totalWithTax": d.get("totalWithTax") or 0,
        "personnelTotal": d.get("personnelTotal") or 0,
        "personnelCount": sum(1 for p in personnel if str((p or {}).get("name") or "").strip()),
        "items": [{"description": str(it.get("description") or "").strip(), "amount": it.get("amount") or 0}
                  for it in (d.get("items") or []) if isinstance(it, dict) and str(it.get("description") or "").strip()],
    }


def dispatch_cost_for_case(quote_no: str, authorization: str) -> list:
    """IP-15 追加 `dispatch.cost_for_case`（契約版本 1）：一個案件的派工**成本檢視**（M06 傳票摘要的承攬商支出來源）。
    權限：COST_VIEW_MODULES 任一（最高管理者一律可）；否則 403。回 `[dispatch_cost_view(...)]`，依 id 排序。
    只新增：`dispatch.list_for_case` 的回應與權限不動。"""
    user = _require_user(authorization)
    require_any_module(user, COST_VIEW_MODULES, "承攬商派工成本")
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT d.*, v.name AS vendor_name FROM contractor_dispatches d "
            "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id "
            "WHERE d.quote_no=? ORDER BY d.id", (quote_no,)).fetchall()
    finally:
        conn.close()
    # 31-A（使用者裁示一條報表規則，所有成本檢視一致）：已取消、草稿、已退回不計；待審核／簽核中計入並標示；已核准與舊單（''）照舊
    return [dispatch_cost_view(d) for d in (_dispatch_row(r) for r in rows)
            if (d.get("status") or "") != "cancelled" and (d.get("approvalStatus") or "") not in (_flow.DRAFT, _flow.RETURNED)]
