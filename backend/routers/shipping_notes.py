"""出貨單（Shipping/Delivery Note）：CRUD + 獨立簽核流程 + PDF + 回簽歷程。

案件管理的子項目，一個報價單（quote_no）可對應多張出貨單（分批出貨）。
簽核流程（system_settings key: unified_approval_flow，2026-08-24 起與報價單／
開票申請憑據／請款單共用同一組設定）機制比照報價單簽核（tiers 依序簽核）但故意
簡化：無改版號的退回機制。
"""
import json
import threading
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Body, HTTPException, Header, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_db, next_entity_code, spawn_bg_thread
from helpers import (
    _require_user, _tok, _audit, _notify, _purge_notifications,
    notify_module_activity, notify_shipping_submitted, notify_shipping_next_tier,
    notify_shipping_approved, notify_shipping_returned,
    push_event_for_shipping_note,
    active_tiers as _active_tiers, current_tier_idx as _current_tier_idx,
    setting_to_active_tiers as _setting_to_active_tiers,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    UnresolvedManagerError, resolve_active_flow_setting,
    save_document_files, delete_document_file,
)
from pdf_gen import generate_shipping_pdf_bytes, _generate_shipping_pdf

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class ShippingNoteIn(BaseModel):
    quote_no:         str
    ship_date:        Optional[str]  = ''
    customer_name:    Optional[str]  = ''
    project_name:     Optional[str]  = ''
    recipient:        Optional[str]  = ''
    delivery_address: Optional[str]  = ''
    items:            Optional[list] = []
    notes:            Optional[str]  = ''


# ── Approval tier helpers（純邏輯部分共用 helpers/tiered_approval.py，見上方 import）──

def _require_admin(user: dict):
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")


def _note_public(row, include_items: bool = True) -> dict:
    """Map DB row → camelCase API shape (mirrors vendor_contractors.py's _dispatch_row,
    the closest precedent consumed by this same case-management.js file)."""
    d = dict(row)
    items = json.loads(d.get("items_json") or "[]")
    approval = (json.loads(d.get("data_json") or "{}") or {}).get("approval") or {}
    out = {
        "id":              d["id"],
        "noteNo":          d["note_no"],
        "quoteNo":         d["quote_no"],
        "status":          d["status"] or "草稿",
        "shipDate":        d.get("ship_date") or "",
        "customerName":    d.get("customer_name") or "",
        "projectName":     d.get("project_name") or "",
        "recipient":       d.get("recipient") or "",
        "deliveryAddress": d.get("delivery_address") or "",
        "notes":           d.get("notes") or "",
        "itemCount":       len(items),
        "isSigned":        bool(d.get("is_signed")),
        "signedBy":        d.get("signed_by") or "",
        "signedAt":        d.get("signed_at") or "",
        "signedLog":       json.loads(d.get("signed_log") or "[]"),
        "signedFiles":     json.loads(d.get("signed_files_json") or "[]"),
        "exportCount":     d.get("export_count") or 0,
        "exportLog":       json.loads(d.get("export_log") or "[]"),
        "approval":        approval,
        "createdBy":       d.get("created_by") or "",
        "createdAt":       d.get("created_at") or "",
        "updatedAt":       d.get("updated_at") or "",
    }
    if include_items:
        out["items"] = items
    return out


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/shipping-notes")
def list_shipping_notes(quote_no: Optional[str] = None, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    if quote_no:
        rows = conn.execute(
            "SELECT * FROM shipping_notes WHERE quote_no=? ORDER BY created_at DESC",
            (quote_no,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM shipping_notes ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    conn.close()
    return [_note_public(r, include_items=False) for r in rows]


@router.get("/api/shipping-notes/export-history")
def list_shipping_export_history(
    q: Optional[str] = None,
    year: Optional[str] = None,
    month: Optional[str] = None,
    authorization: str = Header(None),
):
    """出貨單歷史紀錄：把所有出貨單各自的 export_log（既有欄位，record_shipping_export()
    每次匯出時寫入）攤平成「一次匯出＝一筆」事件列表，供專屬歷史頁面搜尋/年月篩選。"""
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    rows = conn.execute(
        "SELECT note_no, quote_no, customer_name, project_name, ship_date, export_log "
        "FROM shipping_notes WHERE export_count > 0"
    ).fetchall()
    conn.close()

    kw = (q or "").strip().lower()
    events = []
    for row in rows:
        note_no, quote_no = row["note_no"], row["quote_no"]
        customer_name = row["customer_name"] or ""
        project_name = row["project_name"] or ""
        if kw and kw not in note_no.lower() and kw not in customer_name.lower() \
                and kw not in project_name.lower() and kw not in (quote_no or "").lower():
            continue
        log = json.loads(row["export_log"] or "[]")
        for entry in log:
            at = entry.get("at", "")
            if year and not at.startswith(f"{year}-"):
                continue
            if month and not at.startswith(f"{year or at[:4]}-{month.zfill(2)}"):
                continue
            events.append({
                "noteNo": note_no,
                "quoteNo": quote_no,
                "customerName": customer_name,
                "projectName": project_name,
                "shipDate": row["ship_date"] or "",
                "exportedAt": at,
                "mode": entry.get("mode", "external"),
                "exportedBy": entry.get("userDisplay") or entry.get("user") or "",
                "count": entry.get("count", 0),
            })
    events.sort(key=lambda e: e["exportedAt"], reverse=True)
    return events


@router.get("/api/shipping-notes/{note_no}")
def get_shipping_note(note_no: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"出貨單 {note_no} 不存在")
    return _note_public(row, include_items=True)


@router.post("/api/shipping-notes", status_code=201)
def create_shipping_note(body: ShippingNoteIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    now  = datetime.now().isoformat()
    conn = get_db()
    q = conn.execute(
        "SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (body.quote_no,)
    ).fetchone()
    if not q:
        conn.close()
        raise HTTPException(404, "找不到關聯的報價單")
    customer_name = (body.customer_name or '').strip() or (q["customer_name"] or "")
    project_name  = (body.project_name or '').strip() or (q["project_name"] or "")
    note_no = next_entity_code(conn, "shipping_notes", "DN", code_col="note_no")
    conn.execute(
        "INSERT INTO shipping_notes "
        "(note_no, quote_no, status, ship_date, customer_name, project_name, recipient, "
        "delivery_address, items_json, notes, data_json, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (note_no, body.quote_no, "草稿", body.ship_date or "", customer_name, project_name,
         body.recipient or "", body.delivery_address or "",
         json.dumps(body.items or [], ensure_ascii=False), body.notes or "", "{}",
         user["username"], now, now)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.create", "shipping_note", note_no, f"{note_no}（{customer_name}）")
    notify_module_activity("出貨單", "建立", user.get("display_name") or user["username"],
                            f"{note_no}（{customer_name}）", "shipping-notes.html")
    return {"note_no": note_no, "created_at": now}


@router.put("/api/shipping-notes/{note_no}")
def update_shipping_note(note_no: str, body: ShippingNoteIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT status FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可編輯")
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE shipping_notes SET ship_date=?, customer_name=?, project_name=?, recipient=?, "
        "delivery_address=?, items_json=?, notes=?, updated_at=? WHERE note_no=?",
        (body.ship_date or "", body.customer_name or "", body.project_name or "", body.recipient or "",
         body.delivery_address or "", json.dumps(body.items or [], ensure_ascii=False),
         body.notes or "", now, note_no)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.update", "shipping_note", note_no, note_no)
    return {"ok": True, "updated_at": now}


@router.delete("/api/shipping-notes/{note_no}")
def delete_shipping_note(note_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT status FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可刪除")
    conn.execute("DELETE FROM shipping_notes WHERE note_no=?", (note_no,))
    conn.commit()
    conn.close()
    _purge_notifications(note_no, ['shipping_approval_request', 'shipping_approved',
                                    'shipping_returned'])
    _audit(_tok(authorization), "shipping.delete", "shipping_note", note_no, note_no)
    notify_module_activity("出貨單", "刪除", user.get("display_name") or user["username"],
                            note_no, "shipping-notes.html")
    return {"ok": True}


# ── 簽核流程 ──────────────────────────────────────────────────────────────────

@router.post("/api/shipping-notes/{note_no}/submit")
def submit_shipping_note(note_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT status, data_json, customer_name, items_json FROM shipping_notes WHERE note_no=?",
        (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可送出審核")
    items = json.loads(row["items_json"] or "[]")
    if not any((it.get("description") or "").strip() for it in items if it.get("type") != "header"):
        conn.close()
        raise HTTPException(400, "至少需要一項品項說明")

    cname = row["customer_name"] or ""
    d     = json.loads(row["data_json"] or "{}")
    now   = datetime.now().isoformat()

    flow_setting = resolve_active_flow_setting("shipping")
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

    if active_tiers:
        first_tier_usernames = []
        for a in active_tiers[0].get("approvers") or []:
            _notify(a["username"], "shipping_approval_request", note_no, note_no,
                    f"出貨單 {note_no}（{cname}）需要您簽核")
            first_tier_usernames.append(a["username"])

    conn.execute(
        "UPDATE shipping_notes SET status='待審核', data_json=?, updated_at=? WHERE note_no=?",
        (json.dumps(d, ensure_ascii=False), now, note_no)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.submit", "shipping_note", note_no, f"{note_no}（{cname}）",
           {"tierCount": len(active_tiers)})
    if active_tiers:
        notify_shipping_submitted(note_no, cname, first_tier_usernames)
    return {"ok": True, "status": "待審核"}


@router.post("/api/shipping-notes/{note_no}/approve")
def approve_shipping_note(note_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    # 比照 quotations.py：能否簽核完全由「是否為當層簽核人員」決定，不額外要求
    # 簽核人帳號角色必須是 admin/superadmin——簽核設定頁面允許加入任何角色的
    # 使用者當簽核人，這裡若硬性擋 admin 會讓非管理員角色的簽核人永遠卡死無法簽核
    # （2026-08-22 架構複查發現此檔案先前漏套用這個修正，這裡補上）。
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name, items_json, quote_no FROM shipping_notes "
        "WHERE note_no=? AND status IN ('待審核','簽核中')",
        (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"出貨單 {note_no} 不存在或不在待審核狀態")
    cname = row["customer_name"] or ""
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
                    _notify(na["username"], "shipping_approval_request", note_no, note_no,
                            f"出貨單 {note_no}（{cname}）輪到您簽核（第 {ct_idx + 2} 層 / 共 {len(tiers)} 層）")
                    next_tier_usernames.append(na["username"])
                notify_shipping_next_tier(note_no, cname, ct_idx + 2, len(tiers), next_tier_usernames)
        else:
            all_done = False

        appr["tiers"] = tiers
        detail_status = f"第 {ct_idx + 1} 層 {first_pending.get('displayName', user['username'])} 已簽核"
    else:
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")
        _global_flow  = resolve_active_flow_setting("shipping")
        try:
            _global_tiers = _setting_to_active_tiers(_global_flow, conn, appr.get("requestedBy"))
        except UnresolvedManagerError as e:
            conn.close()
            raise HTTPException(400, str(e))
        if _global_tiers:
            conn.close()
            raise HTTPException(403, "系統已設定簽核流程，此出貨單缺少簽核層資料，請重新送審")
        # 申請人不得自行審核（2026-08-22 架構複查發現此檔案先前完全沒有這道檢查，
        # 這裡補上，比照 quotations.py／contractor_vouchers.py／invoice_vouchers.py）
        self_block_msg = check_no_tier_self_approval(conn, appr, user)
        if self_block_msg:
            conn.close()
            raise HTTPException(403, self_block_msg)
        all_done      = True
        detail_status = "超級管理員簽核"

    if all_done:
        # 庫存扣減：品項若引用 part_no/serials，核准即視為「確認出貨」。全部序號都還在庫才放行，
        # 否則整張核准中止（不寫入任何狀態變更），避免出現「已核准但庫存沒扣到」的半吊子狀態。
        items = json.loads(row["items_json"] or "[]")
        stock_ids, missing, seen = [], [], set()
        for it in items:
            pn   = (it.get("part_no") or "").strip()
            sers = it.get("serials") or []
            if not pn or not sers:
                continue
            for sn in sers:
                if (pn, sn) in seen:
                    missing.append(f"{pn} / {sn}（同一張出貨單重複引用）")
                    continue
                seen.add((pn, sn))
                srow = conn.execute(
                    "SELECT id, status FROM stock_items WHERE part_no=? AND serial_no=?", (pn, sn)
                ).fetchone()
                if not srow or srow["status"] != "in_stock":
                    missing.append(f"{pn} / {sn}")
                else:
                    stock_ids.append(srow["id"])
        if missing:
            conn.close()
            raise HTTPException(409, "以下序號已不在庫（可能已被其他出貨單或設備登載使用），無法核准："
                                      + "、".join(missing))

        appr["approvedBy"]        = user["username"]
        appr["approvedByDisplay"] = user.get("display_name") or user["username"]
        appr["approvedAt"]        = now
        appr["status"]            = "approved"
        d["approval"] = appr
        conn.execute(
            "UPDATE shipping_notes SET status='已核准', data_json=?, updated_at=? WHERE note_no=?",
            (json.dumps(d, ensure_ascii=False), now, note_no)
        )
        actor = user.get("display_name") or user["username"]
        for sid in stock_ids:
            conn.execute("""
                UPDATE stock_items
                SET status='shipped', shipping_note_no=?, quote_no=?, consumed_at=?, consumed_by=?, updated_at=?
                WHERE id=?
            """, (note_no, row["quote_no"], now, actor, now, sid))
        conn.commit()
        approver_name = appr.get("approvedByDisplay") or user["username"]
        spawn_bg_thread(_generate_shipping_pdf, args=(note_no, approver_name, '簽核'))
        spawn_bg_thread(push_event_for_shipping_note, args=(note_no,))
        requester = appr.get("requestedBy")
        if requester:
            _notify(requester, "shipping_approved", note_no, note_no, f"出貨單 {note_no}（{cname}）已核准")
            notify_shipping_approved(note_no, cname, approver_name, requester)
        detail_status = "已核准"
    else:
        d["approval"] = appr
        new_status = "簽核中" if (appr.get("currentTier") or 0) > 0 else "待審核"
        conn.execute(
            "UPDATE shipping_notes SET status=?, data_json=?, updated_at=? WHERE note_no=?",
            (new_status, json.dumps(d, ensure_ascii=False), now, note_no)
        )
        conn.commit()

    conn.close()
    _audit(_tok(authorization), "shipping.approve", "shipping_note", note_no, f"{note_no}（{cname}）",
           {"allDone": all_done, "status": detail_status})
    return {"ok": True, "allDone": all_done}


@router.post("/api/shipping-notes/{note_no}/revoke-approval")
def revoke_shipping_note_approval(note_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """撤銷已核准的出貨單，退回草稿並自動歸還已扣的庫存序號。

    出貨單核准後原本沒有任何撤銷機制——庫存要改回可出貨狀態只能靠庫存管理頁
    手動「歸還庫存」，但那個動作只改 stock_items，完全不會回頭同步這張出貨單
    本身：出貨單會永遠停在「已核准」、品項列表也不會變，庫存卻已經在別處顯示
    可再出貨，兩邊資料一旦分岔就沒有機制發現。這支端點把「撤銷核准」變成一個
    正式流程：狀態退回草稿（可重新編輯品項後再送審）、approval 資料清空、且
    核准當下扣的庫存序號一併自動歸還 in_stock，兩邊同一個動作內一起同步。

    已回簽（客戶確認收貨）的出貨單不可撤銷——客戶已經簽收確認，不應該再讓
    系統這邊反悔；要撤銷須先在案件管理頁取消回簽。
    """
    user = _require_user(authorization)
    _require_admin(user)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name, is_signed FROM shipping_notes WHERE note_no=? AND status='已核准'",
        (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"出貨單 {note_no} 不存在或不在已核准狀態")
    if row["is_signed"]:
        conn.close()
        raise HTTPException(409, "已回簽（客戶確認收貨）的出貨單不可撤銷核准，請先取消回簽")
    cname = row["customer_name"] or ""
    d = json.loads(row["data_json"] or "{}")
    appr = d.get("approval") or {}
    requester = appr.get("requestedBy")
    d.pop("approval", None)
    now = datetime.now().isoformat()

    returned_rows = conn.execute(
        "SELECT id FROM stock_items WHERE shipping_note_no=? AND status='shipped'", (note_no,)
    ).fetchall()
    for r in returned_rows:
        conn.execute("""
            UPDATE stock_items
            SET status='in_stock', shipping_note_no='', quote_no='', case_device_id='',
                consumed_at='', consumed_by='', updated_at=?
            WHERE id=?
        """, (now, r["id"]))

    conn.execute(
        "UPDATE shipping_notes SET status='草稿', data_json=?, updated_at=? WHERE note_no=?",
        (json.dumps(d, ensure_ascii=False), now, note_no)
    )
    conn.commit()
    conn.close()
    if requester:
        msg = f"出貨單 {note_no}（{cname}）核准已被撤銷，請確認後重新送審" + (f"：{note}" if note else "")
        _notify(requester, "shipping_returned", note_no, note_no, msg)
        notify_shipping_returned(note_no, cname, note, requester)
    _audit(_tok(authorization), "shipping.revoke_approval", "shipping_note", note_no, f"{note_no}（{cname}）",
           {"note": note, "stockReturned": len(returned_rows)})
    return {"ok": True, "stockReturned": len(returned_rows)}


@router.post("/api/shipping-notes/{note_no}/reject")
def reject_shipping_note(note_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    # 比照 quotations.py：退回權限由當層簽核人員判斷，不額外要求 admin 角色
    # （2026-08-22 架構複查發現此檔案先前漏套用這個修正，這裡補上）
    user = _require_user(authorization)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM shipping_notes WHERE note_no=? AND status IN ('待審核','簽核中')",
        (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"出貨單 {note_no} 不存在或不在待審核狀態")
    cname = row["customer_name"] or ""
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
        "UPDATE shipping_notes SET status='草稿', data_json=?, updated_at=? WHERE note_no=?",
        (json.dumps(d, ensure_ascii=False), now, note_no)
    )
    conn.commit()
    conn.close()
    if requester:
        msg = f"出貨單 {note_no}（{cname}）已退回，請確認後重新送審" + (f"：{note}" if note else "")
        _notify(requester, "shipping_returned", note_no, note_no, msg)
        notify_shipping_returned(note_no, cname, note, requester)
    _audit(_tok(authorization), "shipping.reject", "shipping_note", note_no, f"{note_no}（{cname}）", {"note": note})
    return {"ok": True}


# ── PDF / 匯出紀錄 ────────────────────────────────────────────────────────────

@router.get("/api/shipping-notes/{note_no}/pdf-download")
def download_shipping_pdf(note_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT note_no FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "出貨單不存在")
    try:
        pdf_bytes = generate_shipping_pdf_bytes(note_no)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"PDF 產生失敗：{e}")
    encoded = urlquote(f"{note_no}.pdf")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


@router.post("/api/shipping-notes/{note_no}/export")
def record_shipping_export(note_no: str, mode: str = "external", authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT export_count, export_log FROM shipping_notes WHERE note_no=?", (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"出貨單 {note_no} 不存在")
    log   = json.loads(row["export_log"] or "[]")
    count = (row["export_count"] or 0) + 1
    log.append({
        "at": datetime.now().isoformat(),
        "mode": mode,
        "user": user["username"],
        "userDisplay": user.get("display_name") or user["username"],
        "count": count,
    })
    conn.execute("UPDATE shipping_notes SET export_count=?, export_log=? WHERE note_no=?",
                 (count, json.dumps(log, ensure_ascii=False), note_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.export_pdf", "shipping_note", note_no,
           f"{note_no} PDF 匯出（{mode}）by {user['username']}")
    return {"export_count": count, "log": log}


# ── 已回簽 toggle ─────────────────────────────────────────────────────────────

@router.post("/api/shipping-notes/{note_no}/signed-toggle")
def toggle_signed(note_no: str, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    action = (body or {}).get("action", "")
    note   = (body or {}).get("note", "")
    if action not in ("sign", "unsign"):
        raise HTTPException(400, "action 必須為 sign 或 unsign")
    conn = get_db()
    row = conn.execute(
        "SELECT status, is_signed, signed_log FROM shipping_notes WHERE note_no=?", (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    if row["status"] != "已核准":
        conn.close()
        raise HTTPException(409, "僅已核准狀態可標記回簽")
    is_signed = bool(row["is_signed"])
    if action == "sign" and is_signed:
        conn.close()
        raise HTTPException(409, "已回簽，無需重複標記")
    if action == "unsign" and not is_signed:
        conn.close()
        raise HTTPException(409, "尚未回簽")

    now = datetime.now().isoformat()
    log = json.loads(row["signed_log"] or "[]")
    log.append({
        "at":          now,
        "user":        user["username"],
        "username":    user["username"],
        "userDisplay": user.get("display_name") or user["username"],
        "action":      "signed" if action == "sign" else "unsigned",
        "note":        note,
    })
    if action == "sign":
        conn.execute(
            "UPDATE shipping_notes SET is_signed=1, signed_by=?, signed_at=?, signed_log=?, updated_at=? "
            "WHERE note_no=?",
            (user.get("display_name") or user["username"], now, json.dumps(log, ensure_ascii=False), now, note_no)
        )
    else:
        conn.execute(
            "UPDATE shipping_notes SET is_signed=0, signed_by='', signed_at='', signed_log=?, updated_at=? "
            "WHERE note_no=?",
            (json.dumps(log, ensure_ascii=False), now, note_no)
        )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), f"shipping.{action}", "shipping_note", note_no, note_no, {"note": note})
    notify_module_activity("出貨單", "已回簽" if action == "sign" else "取消回簽",
                            user.get("display_name") or user["username"], note_no, "shipping-notes.html",
                            detail=note or "")
    return {"ok": True, "is_signed": action == "sign", "signed_log": log}


@router.post("/api/shipping-notes/{note_no}/signed-files", status_code=201)
async def upload_shipping_signed_files(note_no: str, files: List[UploadFile] = File(...),
                                       authorization: str = Header(None)):
    """回簽附件上傳（多檔）——任何登入使用者皆可補傳，未來要查證『當初到底簽了
    什麼』直接在這裡看得到。不限制單據狀態，草稿階段也能先留存客戶提供的
    參考資料，不強制一定要 already 已核准才能傳。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT signed_files_json FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    existing = json.loads(row["signed_files_json"] or "[]")
    new_files = await save_document_files("shipping_notes", note_no, files, user.get("display_name") or user["username"])
    all_files = existing + new_files
    now = datetime.now().isoformat()
    conn.execute("UPDATE shipping_notes SET signed_files_json=?, updated_at=? WHERE note_no=?",
                 (json.dumps(all_files, ensure_ascii=False), now, note_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.upload_signed_files", "shipping_note", note_no,
           f"{note_no}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files}


@router.delete("/api/shipping-notes/{note_no}/signed-files/{file_id}")
def delete_shipping_signed_file(note_no: str, file_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT signed_files_json FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    existing = json.loads(row["signed_files_json"] or "[]")
    remaining = delete_document_file("shipping_notes", note_no, existing, file_id)
    now = datetime.now().isoformat()
    conn.execute("UPDATE shipping_notes SET signed_files_json=?, updated_at=? WHERE note_no=?",
                 (json.dumps(remaining, ensure_ascii=False), now, note_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.delete_signed_file", "shipping_note", note_no, note_no)
    return {"ok": True}
