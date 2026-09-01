"""Quotation CRUD, approval workflow, deal-tag, export endpoints."""
import json
import logging
import os
import shutil
import sqlite3
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote as urlquote

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body, HTTPException, Header, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_db, spawn_bg_thread
from helpers import (
    _require_user, _tok, _audit, _notify, _purge_notifications,
    quote_hot_fields, save_quotation_json, _steps_to_tiers, SQL_DEAL_TAG, SQL_SETTLE_STATUS,
    notify_approval_request, notify_next_tier, notify_approved,
    notify_returned, notify_resubmit_requester, notify_settlement_finalized,
    notify_module_activity, push_event_for_quotation_won, push_event_for_important_comment,
    push_event_for_case_stage_due, push_event_delete_for_case_stage,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    resolve_tier_approvers, UnresolvedManagerError, resolve_active_flow_setting,
    save_document_files, delete_document_file,
    notify_case_close_blocked, notify_case_change_requested,
    norm_at, active_delegators_for, user_has_module,
)
import helpers.uploads as _uploads_mod
from helpers.uploads import _effective_subfolder
from archive import _backup_quotation
from pdf_gen import (
    _generate_quotation_pdf, generate_pdf_bytes,
    _generate_case_closing_pdf, generate_case_closing_pdf_bytes,
    generate_project_execution_report_pdf_bytes,
)

router = APIRouter()


# ── Approval tier helpers ─────────────────────────────────────────────────────

import re as _re

def _next_revision_no(quote_no: str) -> str:
    """MQ-202501-001 → MQ-202501-001-R1; MQ-202501-001-R2 → MQ-202501-001-R3"""
    m = _re.match(r'^(MQ-\d{6}-\d{3})(?:-R(\d+))?$', quote_no)
    if not m:
        return quote_no + '-R1'
    base = m.group(1)
    rev  = int(m.group(2) or '0') + 1
    return f'{base}-R{rev}'


def _setting_to_active_tiers(setting: dict, conn, requester_username: str = None) -> list:
    """Convert settings format (tiers or old steps) → list of active tier dicts with status fields.
    Kept as quotations.py's own copy (not the shared helpers/tiered_approval.py version) because of
    the legacy `steps` back-compat above — but the department/division/submitter-manager resolution
    logic is shared via resolve_tier_approvers(), not reimplemented here, so both copies stay in sync
    on that behavior. 系統內建「申請人部門主管自動簽核」層（2026-08-22i）跟共用版一致，預設插入。

    ⚠️ 2026-08-28 修正（跟 helpers/tiered_approval.py::setting_to_active_tiers() 同步）：
    過濾條件改成看「展開後」的解析結果，不是設定裡原始的 approver 項目數——後者
    對 department_manager/division_manager 一定恆真，若解析到的主管剛好就是申請人
    自己（resolve_tier_approvers() 會靜默排除以避免自簽），先前會留下一個
    approvers:[] 的空層卡死流程（任何人都無法通過該層）。"""
    tiers = list(setting.get("tiers") or [])
    if not tiers:
        tiers = _steps_to_tiers(setting.get("steps") or [])
    if setting.get("includeSubmitterManagerTier", True):
        tiers = [{"approvers": [{"sourceType": "submitter_manager"}]}] + tiers
    result = []
    for t in tiers:
        if not (t.get("approvers") or []):
            continue
        resolved = resolve_tier_approvers(conn, t, requester_username)
        if resolved:
            result.append({"order": len(result), "approvers": resolved})
    return result


def _active_tiers(appr: dict) -> list:
    """Read tiers from active approval object (backward-compat: old steps → single-approver tiers).
    NOTE: parallel backward-compat logic exists in system.py _normalize_flow() for the
    settings read path — keep both in sync when modifying tiers structure."""
    tiers = appr.get("tiers") or []
    if tiers:
        return tiers
    steps = appr.get("steps") or []
    return [
        {
            "order": i,
            "approvers": [{
                "userId":      s.get("userId"),
                "username":    s["username"],
                "displayName": s.get("displayName", s["username"]),
                "status":      s.get("status", "pending"),
                "approvedAt":  s.get("approvedAt"),
            }],
        }
        for i, s in enumerate(steps)
    ]


def _current_tier_idx(appr: dict) -> int:
    ct = appr.get("currentTier")
    if ct is None:
        ct = appr.get("currentStep", 0)
    return ct


def _visible_case_filter_sql(user: dict, prefix: str = "") -> tuple:
    """回傳 (sql_fragment, params)：非 admin/superadmin 只能看自己名下業務歸屬的案件，
    或被 assigned_user_ids 勾選分配的案件（2026-08-27 起，接上原本只存欄位、沒實際
    拿來過濾可見性的 assigned_user_ids——見 quotations.py::update_case_assigned_users()
    /case-management.html 成員分配 UI）。json_each() 是 SQLite JSON1 擴充函式，
    daily_tasks.py 的 json_each(assigned_to) 已在用同一招。prefix 是 SQL 別名前綴
    （例如 stage_board() JOIN case_stages 後用 'q.'），unaliased 查詢留空字串即可。"""
    return (
        f" AND ({prefix}sales_person_id=? OR ({prefix}sales_person_id IS NULL AND {prefix}sales_person=?)"
        f" OR EXISTS (SELECT 1 FROM json_each({prefix}assigned_user_ids) WHERE value=?))",
        [user["id"], user["display_name"], user["id"]],
    )


def _check_quotation_owner(row, user: dict) -> None:
    """單筆存取（get/update/delete）比照 list_quotations() 既有的擁有者規則
    （304-306 行）：非 admin/superadmin 只能存取自己名下的報價單，quote_no
    格式可預測（MQ-YYYYMM-NNN），沒有這道檢查會讓任何登入使用者用猜/列舉
    quote_no 看到甚至刪掉別的業務的報價單，繞過清單頁刻意做的隱藏
    （2026-08-24 安全審查修正，IDOR）。2026-08-27：補上 assigned_user_ids
    判斷，跟 list_quotations() 的可見性規則保持一致。"""
    if user["role"] in ("superadmin", "admin"):
        return
    sp_id   = row["sales_person_id"] if "sales_person_id" in row.keys() else None
    sp_name = row["sales_person"] if "sales_person" in row.keys() else None
    owns = (sp_id == user["id"]) or (sp_id is None and sp_name == user["display_name"])
    if not owns and "assigned_user_ids" in row.keys():
        assigned = json.loads(row["assigned_user_ids"] or "[]")
        owns = user["id"] in assigned
    if not owns:
        raise HTTPException(403, "無權限存取其他業務的報價單")


# ── Case semi-unlock / change-request helpers (2026-08-26) ────────────────────
# 已結案案件解鎖後的「半解鎖」機制：deal_tag='已結案' 時，quotations 表
# case_semi_unlocked 欄位若為 0，_gate_case_edit() 涵蓋的端點一律 403；若為 1，
# 這些端點不直接套用變更，而是寫入 case_change_requests 一筆 pending 記錄、
# 背景寄信通知最高管理員，回傳 pending 回應給前端；等 superadmin 於簽核佇列
# 核准後才由 _apply_case_change_request() 真正套用。涵蓋範圍與設計取捨（哪些
# 端點刻意不支援排隊、一律直接 403）見 db.py _m061_case_semi_unlock() docstring。

def _check_case_gate(conn, quote_no: str) -> bool:
    """已結案且未半解鎖 → 403；已結案且已半解鎖 → True（呼叫端應改走
    _create_case_change_request() 排隊，不要直接套用變更）；案件未結案 →
    False（照常繼續，不受任何限制）。"""
    row = conn.execute(
        "SELECT deal_tag, case_semi_unlocked FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    if (row["deal_tag"] or "") != "已結案":
        return False
    if not row["case_semi_unlocked"]:
        raise HTTPException(403, "案件已結案並鎖定，請先解鎖（半解鎖）後再操作")
    return True


def _create_case_change_request(conn, quote_no: str, user: dict, authorization: str,
                                action_type: str, summary: str, payload: dict,
                                staged_files: list = None) -> int:
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO case_change_requests "
        "(quote_no, action_type, summary, payload_json, staged_files_json, status, "
        " requested_by, requested_by_display, requested_at) "
        "VALUES (?,?,?,?,?,'pending',?,?,?)",
        (quote_no, action_type, summary, json.dumps(payload, ensure_ascii=False),
         json.dumps(staged_files or [], ensure_ascii=False),
         user["username"], user.get("display_name") or user["username"], now),
    )
    conn.commit()
    change_id = cur.lastrowid
    requester_display = user.get("display_name") or user["username"]
    spawn_bg_thread(_notify_case_change_requested_bg, args=(quote_no, summary, requester_display))
    _audit(_tok(authorization), "case.change_requested", "quotation", quote_no,
           f"{quote_no}（待審核 #{change_id}：{summary}）")
    return change_id


def _gate_case_edit(conn, quote_no: str, user: dict, authorization: str, action_type: str,
                    summary: str, payload: dict, staged_files: list = None):
    """簡化版：payload 已完整（不需要事後補 staged_files，例如 case_record_update／
    payment_mark 這種純 JSON body 的異動），一次做完「檢查 + 建立待審核記錄」。
    回傳 (gated, change_id)——gated=True 時呼叫端應立即回傳 pending 回應，不要
    再執行實際變更；gated=False 時比照原本邏輯繼續。需要先建立記錄取得 id
    才能存放暫存檔案的上傳類端點，改用 _check_case_gate() +
    _create_case_change_request() 兩段式呼叫（見 upload_material_files() 等）。

    case_record_update 特別處理（2026-08-26 自我審查發現的合併去重）：
    `update_case_record()` 是每次欄位編輯 1.5 秒防抖自動存檔都會呼叫的端點，
    半解鎖期間若每次都新建一筆待審核記錄，編輯個幾分鐘就會在佇列裡疊出幾十筆
    近乎重複的記錄（且各自是「當下那一刻」的完整 caseRecord 快照）；更嚴重的
    是若 superadmin 沒有嚴格照時間先後核准，核准較舊的一筆會用當時的舊快照
    整包蓋掉已經核准過的較新內容，等於資料倒退。修法：同一張案件若已有一筆
    `pending` 的 case_record_update，後續存檔直接更新那一筆的內容/時間戳，
    不新建、不重複寄信——核准時永遠拿到最新一次編輯的完整內容，佇列裡也只會
    看到一筆。"""
    if not _check_case_gate(conn, quote_no):
        return False, None
    if action_type == "case_record_update":
        existing = conn.execute(
            "SELECT id FROM case_change_requests WHERE quote_no=? AND action_type=? AND status='pending'",
            (quote_no, action_type),
        ).fetchone()
        if existing:
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE case_change_requests SET summary=?, payload_json=?, requested_by=?, "
                "requested_by_display=?, requested_at=? WHERE id=?",
                (summary, json.dumps(payload, ensure_ascii=False), user["username"],
                 user.get("display_name") or user["username"], now, existing["id"]),
            )
            conn.commit()
            return True, existing["id"]
    change_id = _create_case_change_request(conn, quote_no, user, authorization,
                                             action_type, summary, payload, staged_files)
    return True, change_id


def _notify_case_change_requested_bg(quote_no: str, summary: str, requester_display: str) -> None:
    conn = get_db()
    row = conn.execute(
        "SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    conn.close()
    notify_case_change_requested(
        quote_no, row["customer_name"] or "" if row else "",
        row["project_name"] or "" if row else "", summary, requester_display,
    )


def _deny_if_case_locked_unsupported(conn, quote_no: str, authorization: str = None) -> None:
    """給不支援排隊審核的細項端點（案件執行階段的新增/編輯/刪除/排序/加入
    負責人/移除負責人/前置階段/新增拜訪/編輯拜訪/刪除拜訪共 10 支，加上款項
    稅額沖銷申請/撤銷/核准 3 支，合計 13 支）用：已結案案件
    一律 403，不論是否半解鎖都不例外（設計取捨見 db.py migration docstring —
    需要修正時請透過已支援排隊審核的案件資料整體編輯/款項標記收款/附件上傳
    端點處理，或聯繫最高管理員直接校正）。

    2026-08-28：這道 403 牆原本被擋下時完全不留紀錄，之後要評估「是否該擴大
    半解鎖排隊審核的涵蓋範圍」時沒有任何實際使用頻率數據可看——這裡補上一筆
    audit_log（action='case.locked_edit_denied'），純記錄用途，不影響回應內容，
    之後累積一段時間就能看出這道限制實際被撞到的頻率，用數據而非猜測決定
    要不要擴大範圍。"""
    row = conn.execute("SELECT deal_tag FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    if (row["deal_tag"] or "") == "已結案":
        if authorization:
            _audit(_tok(authorization), "case.locked_edit_denied", "quotation", quote_no,
                   f"{quote_no} 已結案，此操作不支援排隊審核，直接擋下")
        raise HTTPException(
            403,
            "案件已結案並鎖定，此操作不支援於已結案案件（如需修正請透過案件資料整體編輯，"
            "或聯繫最高管理員）",
        )


def _exclude_requester(tiers: list, requester: str) -> list:
    """Drop the requester from tier approver lists — a submitter must never end up
    required to approve their own quotation. Tiers left with no approvers after
    removal are dropped entirely so the flow skips straight past them."""
    if not requester:
        return tiers
    result = []
    for t in tiers:
        approvers = [a for a in (t.get("approvers") or []) if a.get("username") != requester]
        if approvers:
            result.append({**t, "approvers": approvers})
    return result


def _build_approval_tiers_and_notify(q: dict, appr: dict, quote_no: str, is_new_submission: bool) -> dict:
    """Attach approval tiers built from global settings (requester excluded) if not
    already present on `appr`, then send approval-request notifications for a
    first-time submission. Shared by create_quotation() (direct create+submit, no
    draft step) and update_quotation() (draft → 待審核) so both submission paths
    build tiers and notify identically."""
    if not appr.get("tiers") and not appr.get("steps"):
        flow_setting = resolve_active_flow_setting("quotation")
        requester_uname = appr.get("requestedBy") or ""
        _tconn = get_db()
        try:
            active_tiers = _setting_to_active_tiers(flow_setting, _tconn, requester_uname)
        finally:
            _tconn.close()
        _before_ct = len(active_tiers)
        active_tiers = _exclude_requester(active_tiers, requester_uname)
        if len(active_tiers) != _before_ct:
            logger.warning("approval tiers self-excluded — quote=%r requester=%r before=%d after=%d",
                           quote_no, requester_uname, _before_ct, len(active_tiers))
        logger.warning("approval tiers load — quote=%r is_new=%r flow_tiers=%d active_tiers=%d",
                       quote_no, is_new_submission, len(flow_setting.get("tiers") or []), len(active_tiers))
        if active_tiers:
            appr["tiers"]       = active_tiers
            appr["currentTier"] = 0
    else:
        logger.warning("approval tiers already present — quote=%r tiers_count=%d",
                       quote_no, len(appr.get("tiers") or appr.get("steps") or []))
    q["approval"] = appr
    if is_new_submission:
        tiers        = _active_tiers(appr)
        cname        = q.get("customerName") or ""
        is_revision  = bool(q.get("returnInfo"))
        if appr.get("isEditApproval"):
            label = "（解鎖改版）"
        elif is_revision:
            label = "（退回改版）"
        else:
            label = ""
        requester = appr.get("requestedBy") or ""

        ct_idx       = appr.get("currentTier", 0)
        _appr_names  = []   # usernames — for email lookup
        _appr_labels = []   # display names — for requester confirmation copy
        if tiers and ct_idx < len(tiers):
            pending = [a for a in (tiers[ct_idx].get("approvers") or [])
                       if a.get("status") != "approved"]
            if ct_idx == 0:
                msg = f"報價單 {quote_no}{label}（{cname}）需要您簽核"
                for a in pending:
                    _notify(a["username"], "approval_request", quote_no, quote_no, msg)
                    _appr_names.append(a["username"])
                    _appr_labels.append(a.get("displayName") or a["username"])
                notify_approval_request(quote_no, cname, _appr_names)
            else:
                msg = (f"報價單 {quote_no}{label}（{cname}）"
                       f"輪到您簽核（第 {ct_idx + 1} 層 / 共 {len(tiers)} 層）")
                for a in pending:
                    _notify(a["username"], "approval_request", quote_no, quote_no, msg)
                    _appr_names.append(a["username"])
                    _appr_labels.append(a.get("displayName") or a["username"])
                notify_next_tier(quote_no, cname, ct_idx + 1, len(tiers), _appr_names)
        elif not tiers:
            msg = f"報價單 {quote_no}{label}（{cname}）需要您簽核"
            _conn = get_db()
            admins = _conn.execute(
                "SELECT username FROM users WHERE role='superadmin' AND active=1"
            ).fetchall()
            _conn.close()
            for adm in admins:
                if adm["username"] != requester:
                    _notify(adm["username"], "approval_request", quote_no, quote_no, msg)
                    _appr_names.append(adm["username"])
                    _appr_labels.append(adm["username"])
            notify_approval_request(quote_no, cname, _appr_names)

        # If this is a resubmission after rejection, also send confirmation to requester
        if is_revision and requester:
            orig_no = (q.get("returnInfo") or {}).get("originalQuoteNo") or quote_no
            notify_resubmit_requester(quote_no, orig_no, cname, requester, _appr_labels)

    return appr


# ── Models ────────────────────────────────────────────────────────────────────

class QuotationIn(BaseModel):
    quote_no:   Optional[str] = None
    status:     Optional[str] = "草稿"
    data:       dict
    created_by: Optional[str] = None


class QuotationStatusUpdate(BaseModel):
    status: str


class QuotationDealTagUpdate(BaseModel):
    deal_tag:  Optional[str]  = ''
    log_entry: Optional[dict] = None


class CaseRecordUpdate(BaseModel):
    case_record: dict = {}


class WriteOffRequestIn(BaseModel):
    reason: Optional[str] = ''


class WriteOffApproveIn(BaseModel):
    approve: bool
    reject_reason: Optional[str] = ''


class ApprovalActionBody(BaseModel):
    approvedByDisplay: Optional[str] = None
    note:              Optional[str]  = None


# ── Quotation sequence ────────────────────────────────────────────────────────

def _peek_next_no(conn, month: str) -> str:
    """Compute next available quote number without reserving it in quote_seq.
    Reservation only happens on actual INSERT (create_quotation)."""
    row_max = conn.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(quote_no, 11, 3) AS INTEGER)), 0) AS mx "
        "FROM quotations WHERE quote_no GLOB ? AND LENGTH(quote_no) = 13",
        (f"MQ-{month}-???",)
    ).fetchone()
    db_max = row_max["mx"] if row_max else 0

    row = conn.execute("SELECT seq FROM quote_seq WHERE month=?", (month,)).fetchone()
    next_seq = max(row["seq"] if row else 0, db_max) + 1

    while conn.execute(
        "SELECT 1 FROM quotations WHERE quote_no=?", (f"MQ-{month}-{next_seq:03d}",)
    ).fetchone():
        next_seq += 1

    return f"MQ-{month}-{next_seq:03d}"


@router.get("/api/next-quote-no")
def next_quote_no(authorization: str = Header(None)):
    """Peek-only: returns the next available number without reserving it.
    The number is not guaranteed until the quotation is actually saved."""
    _require_user(authorization)
    month = datetime.now().strftime("%Y%m")
    conn  = get_db()
    conn.execute(
        "INSERT INTO quote_seq (month, seq) VALUES (?, 0) ON CONFLICT(month) DO NOTHING",
        (month,)
    )
    conn.commit()
    result = _peek_next_no(conn, month)
    conn.close()
    return {"quote_no": result}


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/quotations")
def list_quotations(
    status:   Optional[str] = None,
    customer: Optional[str] = None,
    month:    Optional[str] = None,
    deal_tag: Optional[str] = None,
    limit:    int = 100,
    offset:   int = 0,
    authorization: str = Header(None),
):
    user   = _require_user(authorization)
    conn   = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    select_cols = (
        "id, quote_no, status, customer_name, project_name, total, pretax, "
        "direct_margin_pct, net_margin_pct, sales_person, quote_date, valid_days, "
        f"{SQL_DEAL_TAG} as deal_tag, "
        "created_at, updated_at, "
        "COALESCE(json_array_length(json_extract(data_json, '$.editHistory')), 0) as edit_count, "
        "json_extract(data_json, '$.editHistory') as edit_history_json, "
        f"{SQL_SETTLE_STATUS} as settle_status, "
        # Phase 5（2026-08-23）：改查 case_stages 表取代解析 caseRecord.stages JSON——
        # 正規化橋樑（3a/3b/v52）已保證這張表對每個有執行進度的案件都是權威、完整的
        # 來源，相關子查詢直接在 SQL 層取出第一個未完成階段的 label，不用整包 JSON
        # 撈出來在 Python 裡逐列解析、迴圈找。
        "(SELECT label FROM case_stages WHERE quote_no=quotations.quote_no AND done=0 "
        " ORDER BY sort_order LIMIT 1) as current_stage, "
        # 案件清單卡片進度徽章用（視覺化改版，2026-08-24）：階段總數／完成數／逾期數。
        "(SELECT COUNT(*) FROM case_stages WHERE quote_no=quotations.quote_no) as stage_total, "
        "(SELECT COUNT(*) FROM case_stages WHERE quote_no=quotations.quote_no AND done=1) as stage_done, "
        "(SELECT COUNT(*) FROM case_stages WHERE quote_no=quotations.quote_no AND done=0 "
        " AND due_date != '' AND due_date < ?) as stage_overdue"
    )
    # select_params 只服務上面 SELECT 子句裡的相關子查詢（stage_overdue 的 today），跟
    # where_sql 的 params 分開放——SELECT 子句在 SQL 字串裡排在 WHERE 之前，它的 ? 佔位
    # 符必須排在 params 前面；但下面的 COUNT 查詢是另一支獨立 SQL，沒有這個子查詢，不吃
    # select_params，兩者共用一個 list 會讓 COUNT 查詢的 ? 數量對不上而 500。
    select_params = [today]
    # where_sql 獨立累積，不再用字串搜尋從完整 SQL 裡「切」出 WHERE 片段——上面
    # SELECT 子句裡的相關子查詢自己就帶了 " AND"/" ORDER BY"，字串搜尋版的作法
    # 會切到子查詢內部而不是真正的外層 WHERE，導致 COUNT 查詢直接用了不存在的欄位
    # 名稱（2026-08-23 Phase 5 上線後、下一次改動時發現並修正的 bug，過程中造成
    # /api/quotations 短暫 500）。
    where_sql = ""
    params = []
    if user["role"] not in ("superadmin", "admin"):
        frag, fparams = _visible_case_filter_sql(user)
        where_sql += frag
        params.extend(fparams)
    if status:
        where_sql += " AND status=?"; params.append(status)
    if customer:
        where_sql += " AND customer_name LIKE ?"; params.append(f"%{customer}%")
    if month:
        where_sql += " AND quote_no LIKE ?"; params.append(f"MQ-{month}%")
    if deal_tag:
        tags = [t.strip() for t in deal_tag.split(",")]
        where_sql += f" AND {SQL_DEAL_TAG} IN (" + ",".join("?" * len(tags)) + ")"
        params.extend(tags)
    sql = f"SELECT {select_cols} FROM quotations WHERE 1=1{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?"
    rows  = conn.execute(sql, select_params + params + [limit, offset]).fetchall()
    count = conn.execute(
        "SELECT COUNT(*) FROM quotations WHERE 1=1" + where_sql, params
    ).fetchone()[0]
    conn.close()
    items = []
    for r in rows:
        row = dict(r)
        eh_json     = row.pop("edit_history_json", None)
        edit_last = None
        if eh_json:
            try:
                history = json.loads(eh_json)
                if history and isinstance(history, list):
                    last = history[-1]
                    edit_last = {
                        "rev":       last.get("rev"),
                        "at":        last.get("at", ""),
                        "byDisplay": last.get("byDisplay") or last.get("by", ""),
                        "type":      last.get("type", ""),
                    }
            except Exception:
                pass
        row["edit_last"] = edit_last
        items.append(row)
    return {"total": count, "items": items}


@router.get("/api/quotations/stage-board")
def stage_board(department_id: Optional[int] = None, authorization: str = Header(None)):
    """攤平所有已成案案件的執行進度階段（quotations.data_json.caseRecord.stages），
    每個「案件×階段」回傳一筆，供跨案看板/時間軸使用（案件跨案視覺化，2026-08-23）。
    查詢邏輯比照 daily_tasks.py::_check_case_stage_deadline() 的既有查詢，唯讀，
    不觸發任何通知。另外回傳 caseLifecycle（依 quoteNo）供跨案時間軸畫出「業務開發→
    報價單成立→案件成立」前置歷程（2026-08-23e）——不重複塞進每個 stage item，
    跟 items 平行回傳一份。

    department_id（2026-08-28 新增）：比照 dashboard.py 既有慣例，依案件負責業務員
    （q.sales_person_id）所屬部門篩選——沒有回填 sales_person_id 的舊案件會被篩掉，
    這點跟 dashboard.py 的既有落差一致，非本次新增的缺陷。"""
    user = _require_user(authorization)
    conn = get_db()
    dn_map = {
        r["username"]: (r["display_name"] or r["username"])
        for r in conn.execute("SELECT username, display_name FROM users").fetchall()
    }
    # Phase 5（2026-08-23）：改成直接 JOIN case_stages 表，取代撈整包 caseRecord.stages
    # JSON 再用 Python 迴圈攤平——正規化橋樑（3a/3b/v52）已保證這張表對每個有執行進度
    # 的案件都是權威、完整的來源。JOIN 天生就是「每個案件 x 每個階段」一列，跟原本
    # Python 攤平的結果結構完全對等；只有真的有 case_stages 列的案件才會出現，跟原本
    # `json_extract(...) IS NOT NULL` 的篩選語意一致。
    sql = (
        f"SELECT q.quote_no, q.customer_name, q.project_name, q.sales_person, q.sales_person_id, "
        f"q.created_at, cs.id AS stage_id, cs.label, cs.start_date, cs.due_date, cs.done_at, cs.done, "
        f"cs.depends_on, cs.assigned_to, "
        # 跨案時間軸區間顯示用（2026-08-24）：階段的「前往日期」記錄範圍——這是
        # 施工類階段實際會累積多筆日期的地方，用最早～最晚前往日期當作長條的
        # 起訖區間，比單一個完成日期更能呈現真實施作期間。
        f"(SELECT MIN(visit_date) FROM case_stage_visits WHERE stage_id=cs.id AND visit_date != '') AS visit_start, "
        f"(SELECT MAX(visit_date) FROM case_stage_visits WHERE stage_id=cs.id AND visit_date != '') AS visit_end "
        f"FROM quotations q JOIN case_stages cs ON cs.quote_no = q.quote_no "
        f"WHERE {SQL_DEAL_TAG} = '已成案'"
    )
    params = []
    if user["role"] not in ("superadmin", "admin"):
        frag, fparams = _visible_case_filter_sql(user, prefix="q.")
        sql += frag
        params.extend(fparams)
    sql += " ORDER BY q.quote_no, cs.sort_order"
    rows = conn.execute(sql, params).fetchall()

    if department_id:
        dept_by_user = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users").fetchall()}
        rows = [r for r in rows if r["sales_person_id"] and dept_by_user.get(r["sales_person_id"]) == department_id]

    dev_map = {
        r["converted_quote_no"]: {
            "devStart": (r["created_at"] or "")[:10] or None,
            "devEnd":   (r["updated_at"] or "")[:10] or None,
        }
        for r in conn.execute(
            "SELECT converted_quote_no, created_at, updated_at FROM dev_cases "
            "WHERE converted_quote_no IS NOT NULL AND converted_quote_no != ''"
        ).fetchall()
    }
    case_started_map = {
        r["quote_no"]: r["became_case_at"][:10]
        for r in conn.execute(
            "SELECT target_id AS quote_no, MIN(at) AS became_case_at FROM audit_log "
            "WHERE action='deal_tag.change' AND json_extract(detail,'$.to')='已成案' "
            "GROUP BY target_id"
        ).fetchall()
    }
    conn.close()

    case_lifecycle = {}
    for row in rows:
        qno = row["quote_no"]
        dev = dev_map.get(qno) or {}
        case_lifecycle[qno] = {
            "devStart":       dev.get("devStart"),
            "devEnd":         dev.get("devEnd"),
            "quoteCreatedAt": (row["created_at"] or "")[:10] or None,
            "caseStartedAt":  case_started_map.get(qno),
        }

    today = datetime.now().strftime("%Y-%m-%d")
    items = []
    for row in rows:
        due = row["due_date"] or ""
        done = bool(row["done"])
        overdue = (not done) and bool(due) and due < today
        assigned = [u for u in json.loads(row["assigned_to"] or "[]") if u]
        items.append({
            "quoteNo":       row["quote_no"],
            "customerName":  row["customer_name"] or "",
            "projectName":   row["project_name"] or "",
            "salesPerson":   row["sales_person"] or "",
            "stageId":       row["stage_id"],
            "stageLabel":    row["label"] or "（未命名階段）",
            "startDate":     row["start_date"] or "",
            "dueDate":       due,
            "doneAt":        row["done_at"] or "",
            "visitStart":    row["visit_start"] or "",
            "visitEnd":      row["visit_end"] or "",
            "done":          done,
            "overdue":       overdue,
            "dependsOn":     json.loads(row["depends_on"] or "[]"),
            "assignedTo":    assigned,
            "assignedNames": [dn_map.get(u, u) for u in assigned],
        })
    return {"items": items, "caseLifecycle": case_lifecycle}


@router.post("/api/quotations/case-activity")
def case_activity(body: dict = Body(...), authorization: str = Header(None)):
    """Return latest case_updates/work_logs/daily_task_completions activity time per quote_no
    (for案件管理 list's「有新動態」unread indicator; these three sources don't touch quotations.updated_at)."""
    user = _require_user(authorization)
    quote_nos = [q for q in (body.get("quote_nos") or []) if q]
    if not quote_nos:
        return {}
    conn = get_db()
    try:
        if user["role"] not in ("superadmin", "admin"):
            ph = ",".join("?" * len(quote_nos))
            frag, fparams = _visible_case_filter_sql(user)
            allowed = conn.execute(
                f"SELECT quote_no FROM quotations WHERE quote_no IN ({ph}){frag}",
                quote_nos + fparams,
            ).fetchall()
            quote_nos = [r["quote_no"] for r in allowed]
            if not quote_nos:
                return {}
        ph = ",".join("?" * len(quote_nos))
        rows = conn.execute(
            f"""
            SELECT quote_no, MAX(ts) as latest FROM (
                SELECT quote_no, created_at as ts FROM case_updates WHERE quote_no IN ({ph})
                UNION ALL
                SELECT case_no as quote_no, created_at as ts FROM work_logs WHERE case_no IN ({ph})
                UNION ALL
                SELECT dt.case_no as quote_no, dtc.completed_at as ts
                FROM daily_task_completions dtc JOIN daily_tasks dt ON dt.id = dtc.task_id
                WHERE dt.case_no IN ({ph}) AND dtc.completed_at != ''
            )
            GROUP BY quote_no
            """,
            quote_nos + quote_nos + quote_nos,
        ).fetchall()
        return {r["quote_no"]: r["latest"] for r in rows}
    finally:
        conn.close()


@router.get("/api/quotations/{quote_no}")
def get_quotation(quote_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT * FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    _check_quotation_owner(row, user)
    result = dict(row)
    result["data"] = json.loads(result.pop("data_json", "{}"))
    result["data"]["status"] = result["status"]   # DB column is authoritative
    result["signed_log"] = json.loads(result.get("signed_log") or "[]")
    result["signed_files"] = json.loads(result.pop("signed_files_json", None) or "[]")
    result["assigned_user_ids"] = json.loads(result.get("assigned_user_ids") or "[]")
    return result


@router.patch("/api/quotations/{quote_no}/assigned-users")
def update_case_assigned_users(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """案件成員分配（2026-08-26 專案管理併入案件管理，取代原
    PATCH /api/projects/{id}/assigned-users），比照原端點僅 admin+ 可設定。"""
    user = _require_user(authorization)
    if user['role'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "僅管理員可設定成員分配")
    user_ids = [int(uid) for uid in (body.get('user_ids') or []) if uid]
    conn = get_db()
    row = conn.execute("SELECT quote_no FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "案件不存在")
    conn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?",
                 (json.dumps(user_ids, ensure_ascii=False), quote_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'case.assign', 'quotation', quote_no, f"分配 {len(user_ids)} 位成員")
    notify_module_activity("案件管理", "設定成員分配", user.get("display_name") or user["username"],
                            f"{quote_no}（{len(user_ids)} 位成員）", "case-management.html")
    return {"ok": True}


@router.post("/api/quotations/{quote_no}/signed-toggle")
def toggle_quotation_signed(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """報價單客戶回簽（2026-08-24 新增，比照 shipping_notes.py 既有的
    signed-toggle 端點邏輯，唯一差別是報價單的終態是「已送出」而非
    出貨單／開票申請憑據的「已核准」）。"""
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    action = (body or {}).get("action", "")
    note   = (body or {}).get("note", "")
    if action not in ("sign", "unsign"):
        raise HTTPException(400, "action 必須為 sign 或 unsign")
    conn = get_db()
    row = conn.execute(
        "SELECT status, is_signed, signed_log FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "報價單不存在")
    if row["status"] != "已送出":
        conn.close()
        raise HTTPException(409, "僅已送出狀態可標記回簽")
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
        "username":    user["username"],
        "userDisplay": user.get("display_name") or user["username"],
        "action":      "signed" if action == "sign" else "unsigned",
        "note":        note,
    })
    if action == "sign":
        conn.execute(
            "UPDATE quotations SET is_signed=1, signed_by=?, signed_at=?, signed_log=?, updated_at=? "
            "WHERE quote_no=?",
            (user.get("display_name") or user["username"], now, json.dumps(log, ensure_ascii=False), now, quote_no)
        )
    else:
        conn.execute(
            "UPDATE quotations SET is_signed=0, signed_by='', signed_at='', signed_log=?, updated_at=? "
            "WHERE quote_no=?",
            (json.dumps(log, ensure_ascii=False), now, quote_no)
        )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), f"quotation.{action}", "quotation", quote_no, quote_no, {"note": note})
    notify_module_activity("報價單", "已回簽" if action == "sign" else "取消回簽",
                            user.get("display_name") or user["username"], quote_no, "quotation-form.html",
                            detail=note or "")
    return {"ok": True, "is_signed": action == "sign", "signed_log": log}


@router.post("/api/quotations/{quote_no}/signed-files", status_code=201)
async def upload_quotation_signed_files(quote_no: str, files: List[UploadFile] = File(...),
                                        authorization: str = Header(None)):
    """報價單回簽附件上傳（多檔）——任何登入使用者皆可補傳。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT signed_files_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "報價單不存在")
    existing = json.loads(row["signed_files_json"] or "[]")
    new_files = await save_document_files("quotations", quote_no, files, user.get("display_name") or user["username"])
    all_files = existing + new_files
    now = datetime.now().isoformat()
    conn.execute("UPDATE quotations SET signed_files_json=?, updated_at=? WHERE quote_no=?",
                 (json.dumps(all_files, ensure_ascii=False), now, quote_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "quotation.upload_signed_files", "quotation", quote_no,
           f"{quote_no}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files}


@router.delete("/api/quotations/{quote_no}/signed-files/{file_id}")
def delete_quotation_signed_file(quote_no: str, file_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT signed_files_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "報價單不存在")
    existing = json.loads(row["signed_files_json"] or "[]")
    remaining = delete_document_file("quotations", quote_no, existing, file_id)
    now = datetime.now().isoformat()
    conn.execute("UPDATE quotations SET signed_files_json=?, updated_at=? WHERE quote_no=?",
                 (json.dumps(remaining, ensure_ascii=False), now, quote_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "quotation.delete_signed_file", "quotation", quote_no, quote_no)
    return {"ok": True}


@router.post("/api/quotations", status_code=201)
def create_quotation(body: QuotationIn, authorization: str = Header(None)):
    q   = body.data
    now = datetime.now().isoformat()
    month = datetime.now().strftime("%Y%m")
    tot  = q.get("tot", {})
    deal_tag, settle_status = quote_hot_fields(q)
    conn = get_db()

    sp_name = (q.get("salesPerson") or "").strip()
    sp_row = conn.execute(
        "SELECT id FROM users WHERE display_name=? AND active=1 LIMIT 1", (sp_name,)
    ).fetchone() if sp_name else None
    sp_id = sp_row["id"] if sp_row else None

    # Ensure quote_seq row exists for peek helper
    conn.execute(
        "INSERT INTO quote_seq (month, seq) VALUES (?, 0) ON CONFLICT(month) DO NOTHING",
        (month,)
    )

    # Use provisional number from client if provided; otherwise auto-assign
    qno = body.quote_no or q.get("quoteNo") or _peek_next_no(conn, month)

    def _do_insert(no: str):
        q["quoteNo"] = no
        conn.execute("""
            INSERT INTO quotations
              (quote_no, status, customer_name, project_name,
               total, pretax, direct_margin_pct, net_margin_pct,
               sales_person, sales_person_id, quote_date, valid_days, data_json,
               created_at, updated_at, created_by, deal_tag, settle_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            no, body.status,
            q.get("customerName"), q.get("projectName"),
            tot.get("total", 0), tot.get("pretax", 0),
            tot.get("directMarginPct", 0), tot.get("netMarginPct", 0),
            q.get("salesPerson"), sp_id, q.get("quoteDate"), q.get("validDays", 30),
            json.dumps(q, ensure_ascii=False),
            now, now, body.created_by, deal_tag, settle_status,
        ))

    try:
        _do_insert(qno)
    except sqlite3.IntegrityError:
        # Provisional number taken (concurrent save); auto-assign next available
        qno = _peek_next_no(conn, month)
        try:
            _do_insert(qno)
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(409, "報價單號衝突，請重試")

    # Reserve in quote_seq so future peeks don't repeat this number
    seq_no = int(qno.split("-")[-1]) if qno.count("-") == 2 else 0
    if seq_no:
        conn.execute(
            "INSERT INTO quote_seq (month, seq) VALUES (?, ?) "
            "ON CONFLICT(month) DO UPDATE SET seq=MAX(seq, excluded.seq)",
            (month, seq_no)
        )
    # caseRecord.stages 正規化 Phase 3a（2026-08-23）：新建報價單也可能挾帶
    # caseRecord.stages（例如複製既有案件、或 quotation-form.html 自己的
    # ensureCaseRecord() 產生的階段），同一 conn 內、commit 前一併同步進新表，
    # 邏輯與 update_quotation()/update_case_record() 完全一致。
    cr = q.get("caseRecord")
    if isinstance(cr, dict) and isinstance(cr.get("stages"), list):
        _sync_json_stages_to_table(conn, qno, cr["stages"])
        # 3b 收尾追加修正（2026-08-23）：合併後有些階段可能拿到新的真實 id，立刻
        # 寫回 data_json，前端下一次讀到的 id 才會跟 case_stages 表一致。
        _sync_stages_to_json(conn, qno, updated_at=now)
    conn.commit()
    conn.close()

    # Direct create+submit (new record sent straight to 待審核 with no draft step first)
    # never goes through update_quotation()'s PUT path, so it needs the same tier-building
    # + notification logic run here once the final quote_no is known. Must run AFTER the
    # INSERT above is committed and its connection closed: _build_approval_tiers_and_notify()
    # calls _notify(), which opens its own separate connection to write+commit — doing that
    # while this function's own `conn` still held an uncommitted write transaction open
    # self-deadlocked SQLite's single writer (each connection blocks the other until
    # busy_timeout, silently dropping the notification) during pre-deploy testing.
    if body.status == "待審核":
        appr = q.get("approval") or {}
        try:
            appr = _build_approval_tiers_and_notify(q, appr, qno, is_new_submission=True)
        except UnresolvedManagerError as e:
            raise HTTPException(400, str(e))
        _conn2 = get_db()
        # 3b 收尾追加修正（2026-08-23）：不能直接 json.dumps(q, ...) 整包覆寫——
        # q.caseRecord.stages 仍是 client 送來的原始（可能已作廢）id，上面已經把
        # 正確版本同步進 data_json 了。改成讀回目前資料庫現有的 data_json，只patch
        # approval 這個欄位，其餘（含剛修正好的 caseRecord.stages）維持不動。
        _row2 = _conn2.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qno,)).fetchone()
        _data2 = json.loads(_row2["data_json"] or "{}") if _row2 else dict(q)
        _data2["approval"] = appr
        _conn2.execute(
            "UPDATE quotations SET data_json=? WHERE quote_no=?",
            (json.dumps(_data2, ensure_ascii=False), qno)
        )
        _conn2.commit()
        _conn2.close()

    spawn_bg_thread(_backup_quotation, args=(qno,))
    _audit(_tok(authorization), 'quotation.create', 'quotation', qno, f"{qno}（{q.get('customerName','')}）")
    notify_module_activity("報價單", "建立", body.created_by or "",
                            f"{qno}（{q.get('customerName','')}）", "quotations.html")
    return {"quote_no": qno, "created_at": now}


@router.put("/api/quotations/{quote_no}")
def update_quotation(quote_no: str, body: QuotationIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    q   = body.data
    now = datetime.now().isoformat()

    # consume unlock-edit flag before any processing
    is_unlock_edit = bool(q.pop("_isUnlockEdit", False))
    expected_updated_at = q.pop("_expectedUpdatedAt", None)

    new_status = body.status or q.get("status", "草稿")

    # ── Unlock-edit → append history + force approval flow ────────────────────
    edit_rev = None
    if is_unlock_edit:
        editor = _require_user(authorization)
        if editor["role"] != "superadmin":
            raise HTTPException(403, "解鎖編輯需要超級管理員權限")
        history = q.get("editHistory") or []
        if not isinstance(history, list):
            history = []
        edit_rev = len(history) + 1
        history.append({
            "rev":       edit_rev,
            "at":        now,
            "by":        editor["username"],
            "byDisplay": editor["display_name"] or editor["username"],
            "type":      "quote_edit",
        })
        q["editHistory"] = history
        # Force re-approval regardless of current status
        new_status = "待審核"
        q["approval"] = {
            "requestedBy":        editor["username"],
            "requestedByDisplay": editor["display_name"] or editor["username"],
            "requestedAt":        now,
            "isEditApproval":     True,
            "status":             "pending",
            "reasons":            [f"解鎖後修改（v{edit_rev}），需重新簽核"],
        }

    # ── 待審核：build approval tiers from settings ─────────────────────────────
    if new_status == "待審核":
        appr = q.get("approval") or {}
        if is_unlock_edit:
            is_new_submission = True
        else:
            # Frontend pre-sets requestedAt before sending, so we cannot rely on
            # appr.get("requestedAt") to detect first-time submissions.
            # Instead, compare against the status currently stored in the DB.
            _chk = get_db()
            _old = _chk.execute(
                "SELECT status FROM quotations WHERE quote_no=?", (quote_no,)
            ).fetchone()
            _chk.close()
            _old_status = (_old["status"] if _old else "草稿")
            is_new_submission = _old_status not in ("待審核", "簽核中")
        try:
            appr = _build_approval_tiers_and_notify(q, appr, quote_no, is_new_submission)
        except UnresolvedManagerError as e:
            raise HTTPException(400, str(e))

    tot = q.get("tot", {})

    conn = get_db()

    sp_name = (q.get("salesPerson") or "").strip()
    sp_row = conn.execute(
        "SELECT id FROM users WHERE display_name=? AND active=1 LIMIT 1", (sp_name,)
    ).fetchone() if sp_name else None
    sp_id = sp_row["id"] if sp_row else None

    existing = conn.execute(
        "SELECT id, status, deal_tag, settle_status, updated_at, sales_person_id, sales_person "
        "FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    try:
        _check_quotation_owner(existing, user)
    except HTTPException:
        conn.close()
        raise
    if existing["status"] == "已拒絕":
        conn.close()
        raise HTTPException(403, "已拒絕結案的報價單不可修改")
    # 樂觀鎖（選填）：草稿階段沒有狀態鎖保護，兩人同時編輯同一張草稿會後寫覆蓋
    # 前寫且完全沒有提示。自動存檔（autoSave）跟手動存檔共用這支端點，衝突時
    # 一律回 409，讓呼叫端自行決定要不要提示使用者或重新載入。
    if expected_updated_at and existing["updated_at"] and expected_updated_at != existing["updated_at"]:
        conn.close()
        raise HTTPException(409, "報價單已被其他人更新，請重新載入後再存")
    _LOCKED = ("待審核", "簽核中", "已送出", "已成案", "已結案")
    if existing["status"] in _LOCKED and not is_unlock_edit:
        conn.close()
        raise HTTPException(403, f"報價單狀態為「{existing['status']}」，請透過正式流程操作或解鎖後修改")
    # dealTag／settlement.status 只能透過各自的專用端點（PATCH /deal-tag、
    # PATCH /settlement）異動，兩邊都有完整的狀態機檢查（已成案需先簽核完成、
    # 已成案降級需 admin+、已結案不可逆轉等）。這支端點是編輯報價單「內容」用
    # 的通用存檔，client 送來的 body 完全可能挾帶跟現況不同的 dealTag/
    # settlement.status（不論是前端沒清乾淨的舊資料、還是刻意構造的請求），
    # 若不在這裡攔截，等於讓這支端點繞過另外兩支端點的所有規則。一律強制沿用
    # 資料庫現有值，忽略 client 送來的異動。
    deal_tag, settle_status = existing["deal_tag"] or "", existing["settle_status"] or ""
    q["dealTag"] = deal_tag
    if isinstance(q.get("settlement"), dict):
        q["settlement"]["status"] = settle_status
    conn.execute("""
        UPDATE quotations SET
          status=?, customer_name=?, project_name=?,
          total=?, pretax=?, direct_margin_pct=?, net_margin_pct=?,
          sales_person=?, sales_person_id=?, quote_date=?, valid_days=?,
          data_json=?, updated_at=?, deal_tag=?, settle_status=?
        WHERE quote_no=?
    """, (
        new_status,
        q.get("customerName"), q.get("projectName"),
        tot.get("total", 0), tot.get("pretax", 0),
        tot.get("directMarginPct", 0), tot.get("netMarginPct", 0),
        q.get("salesPerson"), sp_id, q.get("quoteDate"), q.get("validDays", 30),
        json.dumps(q, ensure_ascii=False), now, deal_tag, settle_status,
        quote_no,
    ))
    # caseRecord.stages 正規化 Phase 3a（2026-08-23）：quotation-form.html::apiSave()
    # 走的是這支整包存檔端點，跟 update_case_record() 是完全分開的路徑，一樣可能
    # 挾帶 caseRecord.stages（例如它自己那份較舊、欄位不全的 ensureCaseRecord()
    # 產生的階段）。邏輯與 update_case_record() 完全比照：送了 stages 就整批同步
    # 回 case_stages/case_stage_visits，沒送這個 key 才維持表內現有值不動。
    cr = q.get("caseRecord")
    if isinstance(cr, dict) and isinstance(cr.get("stages"), list):
        _sync_json_stages_to_table(conn, quote_no, cr["stages"])
        # 3b 收尾追加修正（2026-08-23）：合併後有些階段可能拿到新的真實 id，立刻
        # 寫回 data_json，前端下一次讀到的 id 才會跟 case_stages 表一致。updated_at
        # 沿用上面 UPDATE 已經用掉的同一個 now，不產生第二個時間戳，樂觀鎖不受影響。
        _sync_stages_to_json(conn, quote_no, updated_at=now)
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_quotation, args=(quote_no,))
    if is_unlock_edit:
        _audit(_tok(authorization), 'quotation.unlock_edit', 'quotation', quote_no,
               f"{quote_no}（{q.get('customerName','')}）", {"rev": edit_rev, "pendingApproval": True})
        # save PDF snapshot of this revision (includes editor name in filename)
        editor_display = (q.get("editHistory") or [{}])[-1].get("byDisplay", "")
        spawn_bg_thread(_generate_quotation_pdf, args=(quote_no, editor_display, '修改'))
    else:
        appr = q.get("approval") or {}
        extra = {}
        if appr.get("delegateSubmitter"):
            extra["delegateSubmitter"] = appr["delegateSubmitter"]
        if appr.get("delegateNote"):
            extra["delegateNote"] = appr["delegateNote"]
        _audit(_tok(authorization), 'quotation.update', 'quotation', quote_no,
               f"{quote_no}（{q.get('customerName','')}）", extra or None)
    return {"quote_no": quote_no, "updated_at": now, "status": new_status}


_STATUS_PATCH_WHITELIST = {"草稿", "待審核", "已送出", "已取消", "已拒絕"}

@router.patch("/api/quotations/{quote_no}/status")
def update_status(quote_no: str, body: QuotationStatusUpdate, authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅超級管理員可直接變更報價單狀態")
    if body.status not in _STATUS_PATCH_WHITELIST:
        raise HTTPException(400, f"不支援的狀態值：{body.status}")
    conn = get_db()
    row = conn.execute(
        "SELECT customer_name, status, data_json FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    # Block bypass: cannot force 已送出 while approval tiers are still pending
    if body.status == "已送出" and row["status"] in ("待審核", "簽核中"):
        _d    = json.loads(row["data_json"] or "{}")
        _appr = _d.get("approval") or {}
        _tiers = _active_tiers(_appr)
        if _tiers:
            _ct = _current_tier_idx(_appr)
            if _ct < len(_tiers):
                conn.close()
                raise HTTPException(
                    403,
                    f"此報價單尚有 {len(_tiers) - _ct} 層待完成的簽核，"
                    "請透過正式簽核流程完成審核，不可直接強制送出"
                )
    cname = row['customer_name'] or ''
    conn.execute("UPDATE quotations SET status=?, updated_at=? WHERE quote_no=?",
                 (body.status, datetime.now().isoformat(), quote_no))
    conn.commit()
    conn.close()
    action_map = {'待審核': 'quotation.submit', '已送出': 'quotation.approve'}
    action = action_map.get(body.status, 'quotation.status_change')
    _audit(_tok(authorization), action, 'quotation', quote_no, f"{quote_no}（{cname}）", {'status': body.status})
    notify_module_activity("報價單", f"狀態變更為「{body.status}」", user.get("display_name") or user["username"],
                            f"{quote_no}（{cname}）", "quotations.html")
    if body.status == '已送出':
        try:
            actor_u = _require_user(authorization)
            actor_name = actor_u.get("display_name") or actor_u.get("username") or ""
        except Exception:
            actor_name = ""
        spawn_bg_thread(_generate_quotation_pdf, args=(quote_no, actor_name, '已簽核'))
    return {"ok": True}


@router.post("/api/quotations/{quote_no}/recall")
def recall_quotation(quote_no: str, authorization: str = Header(None)):
    """申請人將「待審核」或「簽核中」的報價單收回草稿，清除簽核進度。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT status, data_json, customer_name FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    if row["status"] not in ("待審核", "簽核中"):
        conn.close()
        raise HTTPException(400, f"只有「待審核」或「簽核中」的報價單可以收回（目前狀態：{row['status']}）")
    q = json.loads(row["data_json"])
    appr = q.get("approval") or {}
    if appr.get("requestedBy") != user["username"]:
        conn.close()
        raise HTTPException(403, "只有原送審申請人可以收回報價單")
    cname = row["customer_name"] or q.get("customerName") or ""
    q.pop("approval", None)
    q["status"] = "草稿"
    now = datetime.now().isoformat()
    deal_tag, settle_status = quote_hot_fields(q)
    conn.execute(
        "UPDATE quotations SET status='草稿', data_json=?, updated_at=?, deal_tag=?, settle_status=? "
        "WHERE quote_no=?",
        (json.dumps(q, ensure_ascii=False), now, deal_tag, settle_status, quote_no),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "quotation.recall", "quotation", quote_no,
           f"{quote_no}（{cname}）已由申請人收回草稿")
    notify_module_activity("報價單", "收回草稿", user.get("display_name") or user["username"],
                            f"{quote_no}（{cname}）", "quotations.html")
    return {"quote_no": quote_no, "status": "草稿"}


def _case_close_block_reasons(conn, quote_no: str, d: dict):
    """完結案三項前置條件檢查（2026-08-25 使用者提出，見 QUICK.md §11 🔴最優先
    那一列）。回傳 (reasons, pending_usernames)：reasons 非空時應擋下完結案；
    pending_usernames 是③相關單據簽核人（①②沒有對應的「簽核人」概念，維持
    空清單，通知只會落到最高管理員，見 notify_case_close_blocked() docstring）。"""
    reasons = []
    pending_usernames: list = []

    # ① 執行管理進度 100%（沒有任何階段視為「無需檢查」，不算未達成）
    stage_row = conn.execute(
        "SELECT COUNT(*) total, SUM(CASE WHEN done=1 THEN 1 ELSE 0 END) done "
        "FROM case_stages WHERE quote_no=?", (quote_no,)
    ).fetchone()
    total = stage_row["total"] or 0
    done  = stage_row["done"] or 0
    if total > 0 and done < total:
        reasons.append(f"執行管理進度尚未 100%（{done}/{total}）")

    # ② 款項明細全部收齊（沒有任何期別視為「無需檢查」）
    items = ((d.get("caseRecord") or {}).get("payment") or {}).get("items") or []
    unpaid = [it for it in items if not it.get("received")]
    if unpaid:
        reasons.append(f"款項明細尚有 {len(unpaid)} 期未收齊")

    # ③ 相關單據簽核流程全部完成（報價單本身＋承攬商匯款申請／開票申請憑據／
    # 出貨單／請款單，四種 tiers 簽核機制皆不可處於待審核/簽核中）
    doc_checks = [
        ("報價單",       "quotations"),
        ("承攬商匯款申請", "contractor_payment_vouchers"),
        ("開票申請憑據",   "invoice_vouchers"),
        ("出貨單",       "shipping_notes"),
        ("請款單",       "payment_requests"),
    ]
    for label, table in doc_checks:
        rows = conn.execute(
            f"SELECT json_extract(data_json,'$.approval') ap FROM {table} "
            f"WHERE quote_no=? AND status IN ('待審核','簽核中')",
            (quote_no,)
        ).fetchall()
        if rows:
            reasons.append(f"{label}尚有 {len(rows)} 筆簽核中")
            for r in rows:
                try:
                    appr = json.loads(r["ap"] or "{}")
                except Exception:
                    appr = {}
                tiers = _active_tiers(appr)
                ct = _current_tier_idx(appr)
                if tiers and ct < len(tiers):
                    for a in (tiers[ct].get("approvers") or []):
                        if a.get("status") != "approved" and a.get("username"):
                            pending_usernames.append(a["username"])
    return reasons, list(dict.fromkeys(pending_usernames))


@router.patch("/api/quotations/{quote_no}/deal-tag")
def update_deal_tag(quote_no: str, body: QuotationDealTagUpdate, authorization: str = Header(None)):
    user = _require_user(authorization)
    # 未成案 / 已成案 限管理員以上
    if body.deal_tag in ("未成案", "已成案") and user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可標記「未成案」或「已成案」")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name, project_name, status FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    cname = row['customer_name'] or ''
    pname = row['project_name'] or ''
    d = json.loads(row["data_json"] or "{}")
    old_tag = d.get("dealTag", "")
    # 已成案 需先完成簽核（報價單狀態為「已送出」）
    if body.deal_tag == "已成案" and row["status"] != "已送出":
        conn.close()
        raise HTTPException(400, "報價單需完成簽核（狀態為「已送出」）才能標記為「已成案」")
    # 已結案只能從「已成案」進入（§5.2 狀態圖：已結案僅案件管理「完結案」，
    # 不可從未提供/已提供/未成案直接跳過去），避免繞過已成案那一步的簽核前置
    if body.deal_tag == "已結案" and old_tag != "已成案":
        conn.close()
        raise HTTPException(400, "案件須先標記為「已成案」才能結案")
    # 完結案防呆（2026-08-25 使用者提出、2026-08-26 施作）：①執行管理進度100%
    # ②款項明細全部收齊③相關單據（報價單/承攬商匯款申請/開票申請憑據/出貨單/
    # 請款單）簽核流程全部完成，三項須同時達成才能完結案；任一未達成直接 400
    # 擋下，並通知尚未完成該項的簽核人＋最高管理員（見 _case_close_block_reasons()）。
    if body.deal_tag == "已結案":
        reasons, pending_usernames = _case_close_block_reasons(conn, quote_no, d)
        if reasons:
            conn.close()
            spawn_bg_thread(notify_case_close_blocked, args=(quote_no, cname, pname, reasons, pending_usernames))
            _audit(_tok(authorization), 'case.close_blocked', 'quotation', quote_no,
                   f"{quote_no}（{cname}）完結案被擋下", {"reasons": reasons})
            raise HTTPException(400, "尚有前置條件未達成，無法完結案：" + "；".join(reasons))
    # 已成案 → 降級 限管理員以上
    if old_tag == "已成案" and body.deal_tag != "已成案" and user["role"] not in ("superadmin", "admin"):
        conn.close()
        raise HTTPException(403, "已成案狀態只有管理員以上才可降級")
    # 已結案不可逆轉（僅 superadmin 可例外覆寫）
    if old_tag == "已結案" and user["role"] != "superadmin":
        conn.close()
        raise HTTPException(403, "案件已結案，僅超級管理員可變更案件進度")
    d["dealTag"] = body.deal_tag or ''
    if body.log_entry:
        if "statusLog" not in d or not isinstance(d["statusLog"], list):
            d["statusLog"] = []
        d["statusLog"].append(body.log_entry)
    save_quotation_json(conn, quote_no, d)
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'deal_tag.change', 'quotation', quote_no,
           f"{quote_no}（{cname}）", {'from': old_tag, 'to': body.deal_tag})
    notify_module_activity("報價單", f"案件進度變更為「{body.deal_tag}」", user.get("display_name") or user["username"],
                            f"{quote_no}（{cname}）", "quotations.html")
    if body.deal_tag == '已成案' and old_tag != '已成案':
        spawn_bg_thread(push_event_for_quotation_won, args=(quote_no,))
    if body.deal_tag == '已結案':
        try:
            actor_u = _require_user(authorization)
            actor_name = actor_u.get("display_name") or actor_u.get("username") or ""
        except Exception:
            actor_name = ""
        spawn_bg_thread(_generate_quotation_pdf, args=(quote_no, actor_name, '結案'))
        spawn_bg_thread(_generate_case_closing_pdf, args=(quote_no, actor_name, '結案報表'))
    return {"ok": True}


@router.delete("/api/quotations/{quote_no}")
def delete_quotation(quote_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT customer_name, status, sales_person_id, sales_person FROM quotations WHERE quote_no=?",
        (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    try:
        _check_quotation_owner(row, user)
    except HTTPException:
        conn.close()
        raise
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(403, f"只有草稿狀態的報價單可以刪除（目前狀態：{row['status']}）")
    cname = row['customer_name'] or ''
    conn.execute("DELETE FROM quotations WHERE quote_no=?", (quote_no,))
    # dev_cases 跟 quotations 之間沒有 FK——刪除前先找出所有轉建連結指到這張單的
    # 業務開發案件，清空連結並退回「洽談中」，避免懸空參照（converted_quote_no
    # 指向一張已經不存在的報價單）
    orphaned = conn.execute(
        "SELECT id, case_name FROM dev_cases WHERE converted_quote_no=?", (quote_no,)
    ).fetchall()
    if orphaned:
        conn.execute(
            "UPDATE dev_cases SET converted_quote_no='', status='洽談中', updated_at=? "
            "WHERE converted_quote_no=?",
            (datetime.now().isoformat(), quote_no),
        )
    conn.commit()
    conn.close()
    _purge_notifications(quote_no, ['approval_request', 'approval_returned',
                                     'approval_rejected', 'case_stage_deadline', 'approval_reminder'])
    _audit(_tok(authorization), 'quotation.delete', 'quotation', quote_no, f"{quote_no}（{cname}）")
    for c in orphaned:
        _audit(_tok(authorization), 'dev_case.unlink_deleted_quote', 'dev_case', str(c['id']),
               f"{c['case_name']}：連結的報價單 {quote_no} 已刪除，自動解除連結")
    notify_module_activity("報價單", "刪除", user.get("display_name") or user["username"],
                            f"{quote_no}（{cname}）", "quotations.html")
    return {"ok": True}


def _sync_device_stock(conn, quote_no: str, old_devices: list, new_devices: list, user: dict) -> list:
    """設備登載 devices[] 的序號若對應到庫存序號，隨案件資料整包存檔一併同步扣/還庫存。

    devices[] 沒有獨立端點（addDevice/removeDevice/onMaterialArrived/syncMaterialsToDevices 四處
    都是純前端陣列操作，見 case-management.js），所以在這裡對新舊陣列做序號 diff，而不是新增專屬
    端點——現有設備多半沒有對應庫存來源，序號在 stock_items 裡完全找不到就略過，不擋存檔。與出貨單
    核准（Phase B）是各自獨立的扣庫存來源，並非要求先出貨才能登載。

    但序號如果「有」對應到 stock_items、只是狀態不是 in_stock（例如已經被出貨單核准扣成
    shipped、或已經被別的案件登載成 installed）——這不是「這序號沒有庫存來源」，而是這序號已經
    被別處認領了。這種情況不能比照「完全找不到」一樣悄悄放過，否則案件記錄顯示已登載、庫存系統
    卻卡在別的狀態，兩邊會無聲分岔且沒有人知道。這裡不擋存檔（維持原本「不擋」的設計），但會把
    這些衝突收集起來回傳給呼叫端，由 API 回應告知前端。

    回傳：衝突清單 [{sn, deviceId, stockStatus}]。
    """
    now   = datetime.now().isoformat()
    actor = user.get("display_name") or user["username"]
    old_by_id = {d.get("id"): d for d in old_devices if d.get("id") is not None}
    new_by_id = {d.get("id"): d for d in new_devices if d.get("id") is not None}
    conflicts = []

    for did, dev in new_by_id.items():
        sn = (dev.get("sn") or "").strip()
        old_sn = (old_by_id.get(did) or {}).get("sn", "").strip() if old_by_id.get(did) else ""
        if not sn or sn == old_sn:
            continue
        srow = conn.execute(
            "SELECT id, status FROM stock_items WHERE serial_no=? ORDER BY id LIMIT 1", (sn,)
        ).fetchone()
        if not srow:
            continue  # 序號不在庫存系統裡追蹤，維持原本不擋存檔的行為
        if srow["status"] != "in_stock":
            conflicts.append({"sn": sn, "deviceId": str(did), "stockStatus": srow["status"]})
            continue
        conn.execute("""
            UPDATE stock_items
            SET status='installed', quote_no=?, case_device_id=?, consumed_at=?, consumed_by=?, updated_at=?
            WHERE id=?
        """, (quote_no, str(did), now, actor, now, srow["id"]))

    for did, old_dev in old_by_id.items():
        old_sn = (old_dev.get("sn") or "").strip()
        new_sn = (new_by_id.get(did) or {}).get("sn", "").strip() if new_by_id.get(did) else ""
        if not old_sn or old_sn == new_sn:
            continue
        conn.execute("""
            UPDATE stock_items
            SET status='in_stock', quote_no='', case_device_id='', consumed_at='', consumed_by='', updated_at=?
            WHERE serial_no=? AND status='installed' AND case_device_id=?
        """, (now, old_sn, str(did)))

    return conflicts


@router.post("/api/quotations/{quote_no}/case-unlock")
def unlock_case(quote_no: str, authorization: str = Header(None)):
    """已結案案件解鎖為「半解鎖」狀態（2026-08-26）：任何登入使用者皆可觸發
    （2026-08-26 使用者透過 AskUserQuestion 確認，比照既有附件上傳「任何人皆
    可傳」的最寬鬆權限慣例），解鎖本身立即生效、不需審核；半解鎖期間的每一筆
    變更/上傳才需要 superadmin 審核（見 _gate_case_edit()／_check_case_gate()）。
    只對 deal_tag='已結案' 的案件有意義，其他狀態呼叫這支端點沒有實質作用。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT deal_tag, customer_name, project_name FROM quotations WHERE quote_no=?",
                       (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    if (row["deal_tag"] or "") != "已結案":
        conn.close()
        raise HTTPException(400, "只有已結案的案件才需要解鎖")
    now = datetime.now().isoformat()
    display = user.get("display_name") or user["username"]
    conn.execute(
        "UPDATE quotations SET case_semi_unlocked=1, case_semi_unlocked_by=?, case_semi_unlocked_at=? "
        "WHERE quote_no=?",
        (display, now, quote_no),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "case.semi_unlock", "quotation", quote_no,
           f"{quote_no}（{row['customer_name'] or ''}）解鎖為半解鎖狀態")
    notify_module_activity("案件管理", "解鎖為半解鎖狀態", display,
                            f"{quote_no}（{row['customer_name'] or ''}）", "case-management.html")
    spawn_bg_thread(_notify_case_unlocked_bg, args=(quote_no, row["customer_name"] or "",
                                                    row["project_name"] or "", display))
    return {"ok": True, "caseSemiUnlocked": True, "caseSemiUnlockedBy": display, "caseSemiUnlockedAt": now}


def _notify_case_unlocked_bg(quote_no: str, customer: str, project: str, unlocked_by_display: str) -> None:
    notify_case_change_requested(
        quote_no, customer, project,
        f"案件已由 {unlocked_by_display} 解鎖為半解鎖狀態，之後的變更/上傳將陸續送審",
        unlocked_by_display,
    )


@router.post("/api/quotations/{quote_no}/case-lock")
def lock_case(quote_no: str, authorization: str = Header(None)):
    """將半解鎖案件重新上鎖（2026-08-26），權限比照解鎖——任何登入使用者皆可
    觸發。重新上鎖不會影響既有的 pending 待審核記錄（case_change_requests 仍
    保留，superadmin 之後還是能在簽核佇列核准/拒絕；核准時 _apply_case_change_
    request() 不檢查當下是否半解鎖，避免上鎖動作意外卡住既有審核流程）。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT deal_tag, customer_name FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    conn.execute(
        "UPDATE quotations SET case_semi_unlocked=0, case_semi_unlocked_by='', case_semi_unlocked_at='' "
        "WHERE quote_no=?",
        (quote_no,),
    )
    conn.commit()
    conn.close()
    display = user.get("display_name") or user["username"]
    _audit(_tok(authorization), "case.semi_lock", "quotation", quote_no,
           f"{quote_no}（{row['customer_name'] or ''}）重新上鎖")
    notify_module_activity("案件管理", "重新上鎖", display,
                            f"{quote_no}（{row['customer_name'] or ''}）", "case-management.html")
    return {"ok": True, "caseSemiUnlocked": False}


@router.patch("/api/quotations/{quote_no}/case-record")
def update_case_record(quote_no: str, body: CaseRecordUpdate, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT id, customer_name, project_name, data_json, updated_at FROM quotations WHERE quote_no=?",
        (quote_no,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    # Optimistic lock: client may send expectedUpdatedAt to avoid silent overwrite
    expected = (body.case_record or {}).pop("_expectedUpdatedAt", None) if isinstance(body.case_record, dict) else None
    if expected and row["updated_at"] and expected != row["updated_at"]:
        conn.close()
        raise HTTPException(409, "案件資料已被其他人更新，請重新載入後再存")
    label = f"{quote_no}（{row['customer_name'] or ''}{'／' if row['project_name'] else ''}{row['project_name'] or ''}）"
    data = json.loads(row["data_json"] or "{}")

    # 2026-08-31（安全稽核發現）：這支整包存檔端點原本完全沒有角色檢查——
    # 案件管理頁面的款項明細（勾選已收款／填實收金額／手續費）就是走這支，
    # 不是走有 admin+ 門檻的 mark_payment（PATCH .../payment/{idx}，只有
    # receivables.html 在用），任何登入使用者都能在案件管理頁面直接改動
    # 金流狀態。這支端點同時承載材料/合約條款/角色等其他任何登入使用者都
    # 該能編輯的欄位，不能整支端點都要求 admin+；改成只在真的偵測到
    # received/actualAmount/feeAmount 這幾個金流欄位有變動時才擋，偵測到就
    # 整筆拒絕（不寫入任何欄位），不做「只還原金流欄位、其餘正常存檔」的
    # 靜默處理——使用者已確認採「拒絕整筆」，避免使用者不知情下被悄悄改回
    # 舊值。比對用 item["id"]（新增/編輯款項期別時前端固定會帶，見
    # case-management.js::addPaymentItem()）配對新舊品項，不能用陣列索引位置
    # 比對——sales/engineer 本來就能自行新增/刪除/調整款項期別（跟「標記
    # 已收款」是完全不同的動作），若用位置比對，光是筆數改變（新增一期
    # 款項）就會被整支擋下，變成非 admin/出納完全不能編輯款項明細，不是
    # 這次要的效果。新增的品項若一開始就帶 received=true 仍視為違規擋下。
    if user["role"] not in ("superadmin", "admin") and not user_has_module(user, "cashier"):
        old_items = ((data.get("caseRecord") or {}).get("payment") or {}).get("items") or []
        new_items = ((body.case_record or {}).get("payment") or {}).get("items") or []
        old_by_id = {it.get("id"): it for it in old_items if it.get("id") is not None}
        payment_changed = False
        for new_it in new_items:
            old_it = old_by_id.get(new_it.get("id"))
            if old_it is None:
                if new_it.get("received"):
                    payment_changed = True
                    break
                continue
            if any(old_it.get(f) != new_it.get(f) for f in ("received", "actualAmount", "feeAmount")):
                payment_changed = True
                break
        if payment_changed:
            conn.close()
            raise HTTPException(403, "款項收款狀態需由管理員或出納標記")

    gated, change_id = _gate_case_edit(
        conn, quote_no, user, authorization, "case_record_update",
        f"{label} 更新案件記錄（材料/款項/角色/合約等）", {"case_record": body.case_record or {}},
    )
    if gated:
        conn.close()
        return {"ok": True, "pending": True, "changeRequestId": change_id,
                "message": "案件已結案並處於半解鎖狀態，此變更已送出，待最高管理員審核通過後才會套用"}
    old_devices = (data.get("caseRecord") or {}).get("devices") or []
    new_devices = (body.case_record or {}).get("devices") or []
    # caseRecord.stages 正規化（2026-08-23，3a 新增／3b 上線後修正；2026-08-24 停用
    # 整包 stages 同步）：case-management.js 的階段操作（label/done/日期/負責人/
    # 前置階段/前往記錄）已全部改走 Phase 2 的 granular 端點即時寫入，且每個 granular
    # 端點寫完都會呼叫 `_sync_stages_to_json()` 把結果同步回 data_json——這條整包
    # 存檔路徑（`saveCaseRecord()`）現在只用來存 materials/payment/contract/roles 等
    # 其他欄位。過去這裡會信任 client 送來的 `stages` 陣列並整批覆寫回 case_stages，
    # 原意是怕忽略掉這個欄位會讓伺服器值變舊，但反而造成真正的資料損毀：使用者
    # 用 granular 端點剛存好的日期／負責人，一旦頁面上任何其他欄位（材料、付款…）
    # 觸發這條 1.5 秒防抖的整包存檔，就會被瀏覽器記憶體裡「這次載入當下」的舊
    # `stages` 快照蓋回空值（2026-08-24 案件執行看板日期消失回報，追出的根因）。
    # 一律改成忽略 client 送來的 `stages`，永遠保留伺服器現有值——因為 granular
    # 端點已經確保 data_json.caseRecord.stages 隨時是最新的，不需要也不該再讓這條
    # 路徑覆寫。
    new_case_record = body.case_record or {}
    new_case_record["stages"] = (data.get("caseRecord") or {}).get("stages") or []
    data["caseRecord"] = new_case_record
    stock_conflicts = []
    if new_devices != old_devices:
        stock_conflicts = _sync_device_stock(conn, quote_no, old_devices, new_devices, user)
    now = save_quotation_json(conn, quote_no, data)
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_quotation, args=(quote_no,))
    _audit(_tok(authorization), 'case.update', 'quotation', quote_no, label)
    return {"ok": True, "updated_at": now, "stockConflicts": stock_conflicts}


# ── Case change request approve/reject (2026-08-26) ────────────────────────────

def _cleanup_staged_files(staged_files: list) -> None:
    """拒絕核准時清掉暫存檔案（含空資料夾），套用時搬移失敗或找不到檔案都
    靜默略過——不能因為殘留的暫存檔清不掉就讓審核動作整個失敗。"""
    for f in staged_files or []:
        try:
            full = os.path.join(_uploads_mod.UPLOADS_ROOT, f["path"])
            if os.path.isfile(full):
                os.remove(full)
            d = os.path.dirname(full)
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except Exception:
            pass


def _move_staged_files(staged_files: list, subfolder: str, doc_no: str) -> list:
    """核准套用上傳類變更時，把暫存於 uploads/_pending_case_changes/{change_id}/
    的檔案搬進正式路徑（跟 helpers/uploads.py::save_document_files() 存檔時
    產生的路徑格式一致），回傳更新過 path 的 metadata 陣列。"""
    eff_subfolder = _effective_subfolder(subfolder)
    dest_dir = os.path.join(_uploads_mod.UPLOADS_ROOT, eff_subfolder, doc_no)
    os.makedirs(dest_dir, exist_ok=True)
    moved = []
    src_dirs = set()
    for f in staged_files or []:
        src = os.path.join(_uploads_mod.UPLOADS_ROOT, f["path"])
        src_dirs.add(os.path.dirname(src))
        ext = os.path.splitext(f["path"])[1]
        fname = uuid.uuid4().hex[:16] + ext
        dest_rel = f"{eff_subfolder}/{doc_no}/{fname}"
        dest_full = os.path.join(_uploads_mod.UPLOADS_ROOT, dest_rel)
        if os.path.isfile(src):
            shutil.move(src, dest_full)
        new_meta = dict(f)
        new_meta["path"] = dest_rel
        moved.append(new_meta)
    for d in src_dirs:
        try:
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except Exception:
            pass
    return moved


def _apply_case_change_request(conn, req, approver: dict, authorization: str) -> dict:
    """superadmin 核准後真正套用一筆 case_change_requests。呼叫端負責在成功
    回傳後把該筆記錄標記 approved 並 commit；這裡只處理「套用效果」本身，
    邏輯分別對應 8 個「暫存待審」端點原本會做的事（見各端點 docstring）。
    找不到對應報價單或索引超出範圍時 raise HTTPException，呼叫端會讓整個
    審核動作失敗（不會標記 approved），避免留下「已核准但沒套用」的不一致。
    回傳 dict 供呼叫端附加到 API 回應（目前只有 case_record_update 可能帶
    stockConflicts——即時存檔路徑 update_case_record() 會把這個資訊回傳給
    當下操作的使用者看，這裡改成 superadmin 事後核准套用，同樣不能讓衝突
    悄悄消失，至少寫進 audit_log detail 並回傳給呼叫端）。"""
    quote_no    = req["quote_no"]
    action_type = req["action_type"]
    payload     = json.loads(req["payload_json"] or "{}")
    staged_files = json.loads(req["staged_files_json"] or "[]")
    row = conn.execute(
        "SELECT customer_name, project_name, data_json FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    label = f"{quote_no}（{row['customer_name'] or ''}）"
    data = json.loads(row["data_json"] or "{}")
    cr = data.setdefault("caseRecord", {})
    result: dict = {}

    if action_type == "case_record_update":
        old_devices = cr.get("devices") or []
        new_case_record = payload.get("case_record") or {}
        new_devices = new_case_record.get("devices") or []
        new_case_record["stages"] = cr.get("stages") or []
        data["caseRecord"] = new_case_record
        stock_conflicts = []
        if new_devices != old_devices:
            stock_conflicts = _sync_device_stock(conn, quote_no, old_devices, new_devices, approver)
        save_quotation_json(conn, quote_no, data)
        if stock_conflicts:
            result["stockConflicts"] = stock_conflicts
        _audit(_tok(authorization), 'case.update', 'quotation', quote_no, f"{label}（半解鎖審核通過套用）",
               {"stockConflicts": stock_conflicts} if stock_conflicts else None)

    elif action_type == "payment_mark":
        idx = payload["idx"]
        body = payload["body"] or {}
        pits = cr.setdefault("payment", {}).setdefault("items", [])
        if idx < 0 or idx >= len(pits):
            raise HTTPException(400, "款項索引超出範圍")
        if "received" in body:
            is_rcv = bool(body["received"])
            pits[idx]["received"]   = is_rcv
            pits[idx]["receivedAt"] = body.get("receivedAt", "") if is_rcv else ""
            pits[idx]["receivedBy"] = body.get("receivedBy", "") if is_rcv else ""
            if is_rcv:
                pits[idx]["actualAmount"] = body.get("actualAmount")
                pits[idx]["feeAmount"]    = body.get("feeAmount") or 0
                pits[idx]["feeNote"]      = body.get("feeNote", "")
                pits[idx]["note"]         = body.get("note", "")
                # 收款進了 MOTRIX 自己哪個銀行帳戶（選填，2026-09-01 新增，供 T100
                # 傳票匯出依銀行帳戶分開設定科目代號用；跟其他欄位一樣直接存
                # data_json，不需要 migration，見 db.py::_m071_paid_bank_account docstring）
                pits[idx]["bankAccountName"] = body.get("bankAccountName", "")
                pits[idx]["bankAccountCode"] = body.get("bankAccountCode", "")
            else:
                for k in ("actualAmount", "feeAmount", "feeNote", "note", "bankAccountName", "bankAccountCode"):
                    pits[idx].pop(k, None)
        if "invoiceNo" in body:
            pits[idx]["invoiceNo"] = body["invoiceNo"]
        save_quotation_json(conn, quote_no, data)
        _audit(_tok(authorization), 'payment.mark', 'quotation', quote_no, f"{label}（半解鎖審核通過套用）")

    elif action_type in ("payment_invoice_upload", "material_file_upload", "material_invoice_upload"):
        idx = payload["idx"]
        if action_type == "payment_invoice_upload":
            arr, field, subfolder = cr.setdefault("payment", {}).setdefault("items", []), "invoiceFiles", "quotation_payment_items"
        elif action_type == "material_file_upload":
            arr, field, subfolder = cr.setdefault("materials", []), "files", "quotation_materials"
        else:
            arr, field, subfolder = cr.setdefault("materials", []), "invoiceFiles", "quotation_materials_invoices"
        if idx < 0 or idx >= len(arr):
            raise HTTPException(400, "索引超出範圍")
        moved = _move_staged_files(staged_files, subfolder, f"{quote_no}_{idx}")
        arr[idx].setdefault(field, [])
        arr[idx][field].extend(moved)
        save_quotation_json(conn, quote_no, data)
        _audit(_tok(authorization), f'{action_type}.approved', 'quotation', quote_no,
               f"{label}（半解鎖審核通過套用，{len(moved)} 個檔案）")

    elif action_type in ("payment_invoice_delete", "material_file_delete", "material_invoice_delete"):
        idx = payload["idx"]
        file_id = payload["file_id"]
        if action_type == "payment_invoice_delete":
            arr, field, subfolder = cr.setdefault("payment", {}).setdefault("items", []), "invoiceFiles", "quotation_payment_items"
        elif action_type == "material_file_delete":
            arr, field, subfolder = cr.setdefault("materials", []), "files", "quotation_materials"
        else:
            arr, field, subfolder = cr.setdefault("materials", []), "invoiceFiles", "quotation_materials_invoices"
        if idx < 0 or idx >= len(arr):
            raise HTTPException(400, "索引超出範圍")
        existing = arr[idx].get(field) or []
        arr[idx][field] = delete_document_file(subfolder, f"{quote_no}_{idx}", existing, file_id)
        save_quotation_json(conn, quote_no, data)
        _audit(_tok(authorization), f'{action_type}.approved', 'quotation', quote_no,
               f"{label}（半解鎖審核通過套用）")

    else:
        raise HTTPException(500, f"未知的變更類型：{action_type}")

    return result


@router.get("/api/case-changes/{change_id}")
def get_case_change_request(change_id: int, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM case_change_requests WHERE id=?", (change_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "找不到此筆變更申請")
    return dict(row)


@router.post("/api/case-changes/{change_id}/approve")
def approve_case_change(change_id: int, authorization: str = Header(None)):
    """已結案案件半解鎖期間的變更/上傳，僅最高管理者可核准（比照已結案案件本身
    的解鎖/降級規則）。核准成功才標記 approved 並 commit——_apply_case_change_
    request() 內任何 HTTPException 都會讓這支端點直接回傳錯誤、不落資料庫，
    避免「顯示已核准但其實沒套用」的不一致狀態。"""
    user = _require_user(authorization)
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理者可審核已結案案件的變更申請")
    conn = get_db()
    req = conn.execute("SELECT * FROM case_change_requests WHERE id=?", (change_id,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "找不到此筆變更申請")
    if req["status"] != "pending":
        conn.close()
        raise HTTPException(409, f"此筆變更申請已經是「{req['status']}」狀態")
    self_msg = check_no_tier_self_approval(conn, {"requestedBy": req["requested_by"]}, user)
    if self_msg:
        conn.close()
        raise HTTPException(403, self_msg)
    try:
        apply_result = _apply_case_change_request(conn, req, user, authorization)
    except HTTPException:
        conn.close()
        raise
    now = datetime.now().isoformat()
    approver_display = user.get("display_name") or user["username"]
    conn.execute("UPDATE case_change_requests SET status='approved', decided_by=?, decided_at=? WHERE id=?",
                 (approver_display, now, change_id))
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_quotation, args=(req["quote_no"],))
    _notify(req["requested_by"], "case_change_decided", req["quote_no"], req["quote_no"],
            f"您對已結案案件 {req['quote_no']} 提出的變更「{req['summary']}」已由 {approver_display} 核准套用")
    return {"ok": True, "status": "approved", **(apply_result or {})}


@router.post("/api/case-changes/{change_id}/reject")
def reject_case_change(change_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理者可審核已結案案件的變更申請")
    conn = get_db()
    req = conn.execute("SELECT * FROM case_change_requests WHERE id=?", (change_id,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "找不到此筆變更申請")
    if req["status"] != "pending":
        conn.close()
        raise HTTPException(409, f"此筆變更申請已經是「{req['status']}」狀態")
    self_msg = check_no_tier_self_approval(conn, {"requestedBy": req["requested_by"]}, user)
    if self_msg:
        conn.close()
        raise HTTPException(403, self_msg)
    reason = (body or {}).get("reason") or ""
    _cleanup_staged_files(json.loads(req["staged_files_json"] or "[]"))
    now = datetime.now().isoformat()
    approver_display = user.get("display_name") or user["username"]
    conn.execute(
        "UPDATE case_change_requests SET status='rejected', decided_by=?, decided_at=?, reject_reason=? WHERE id=?",
        (approver_display, now, reason, change_id),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "case.change_rejected", "quotation", req["quote_no"],
           f"{req['quote_no']}（拒絕變更 #{change_id}：{req['summary']}）", {"reason": reason})
    _notify(req["requested_by"], "case_change_decided", req["quote_no"], req["quote_no"],
            f"您對已結案案件 {req['quote_no']} 提出的變更「{req['summary']}」已由 {approver_display} 拒絕"
            + (f"（原因：{reason}）" if reason else ""))
    return {"ok": True, "status": "rejected"}


def _serialize_stage(conn, sr) -> dict:
    visit_rows = conn.execute(
        "SELECT id, visit_date, visit_people, note FROM case_stage_visits "
        "WHERE stage_id=? ORDER BY id",
        (sr["id"],),
    ).fetchall()
    return {
        "id":         sr["id"],
        "label":      sr["label"],
        "sortOrder":  sr["sort_order"],
        "done":       bool(sr["done"]),
        "doneAt":     sr["done_at"],
        "startDate":  sr["start_date"],
        "dueDate":    sr["due_date"],
        "assignedTo": json.loads(sr["assigned_to"] or "[]"),
        "dependsOn":  json.loads(sr["depends_on"] or "[]"),
        "visits": [
            {"id": v["id"], "visitDate": v["visit_date"], "visitPeople": v["visit_people"], "note": v["note"]}
            for v in visit_rows
        ],
    }


def _get_stage_row(conn, quote_no: str, stage_id: int):
    """查一個階段，順便確認它真的屬於這個 quote_no（避免猜 id 跨案件竄改）。查無資料回傳 None。"""
    return conn.execute(
        "SELECT * FROM case_stages WHERE id=? AND quote_no=?", (stage_id, quote_no)
    ).fetchone()


def _sync_stages_to_json(conn, quote_no: str, updated_at: str = None) -> str | None:
    """Phase 3a（2026-08-23）：把 case_stages/case_stage_visits 目前的內容重建回
    quotations.data_json.caseRecord.stages，讓 JSON 在前端還沒切換到新端點的過渡期
    間持續保持最新——list_quotations()/stage_board()/dashboard.py/daily_tasks.py
    這四個既有讀取點完全不用改就能繼續正常運作。掛在 Phase 2 那 10 個變更端點的
    commit 之後呼叫。只動 caseRecord.stages 這個欄位，caseRecord 其他 key（
    payment/devices/materials/roles）與 quotations 其他欄位維持原樣不動。
    3b 收尾追加修正（2026-08-23）：`_sync_json_stages_to_table()` 合併完可能產生
    新的真實 id，呼叫端（`update_case_record`/`create_quotation`/`update_quotation`）
    在那之後也會呼叫這裡把新 id 立刻寫回 `data_json`。可選傳入 `updated_at`
    沿用呼叫端已經算好的同一個時間戳記，避免同一次請求裡把 `updated_at` 又悄悄
    往後推一次、讓回傳給前端的樂觀鎖時間戳跟資料庫實際值對不上。回傳實際寫入的
    時間戳（查無此單則回傳 None）。"""
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        return None
    data = json.loads(row["data_json"] or "{}")
    stage_rows = conn.execute(
        "SELECT * FROM case_stages WHERE quote_no=? ORDER BY sort_order, id", (quote_no,)
    ).fetchall()
    stages_json = []
    for sr in stage_rows:
        visit_rows = conn.execute(
            "SELECT visit_date, visit_people, note FROM case_stage_visits WHERE stage_id=? ORDER BY id",
            (sr["id"],),
        ).fetchall()
        stages_json.append({
            "id":         sr["id"],
            "label":      sr["label"],
            "done":       bool(sr["done"]),
            "doneAt":     sr["done_at"],
            "startDate":  sr["start_date"],
            "dueDate":    sr["due_date"],
            "assignedTo": json.loads(sr["assigned_to"] or "[]"),
            "dependsOn":  json.loads(sr["depends_on"] or "[]"),
            "visits": [
                {"visitDate": v["visit_date"], "visitPeople": v["visit_people"], "note": v["note"]}
                for v in visit_rows
            ],
        })
    data.setdefault("caseRecord", {})["stages"] = stages_json
    result_ts = save_quotation_json(conn, quote_no, data, updated_at=updated_at)
    conn.commit()
    return result_ts


def _sync_json_stages_to_table(conn, quote_no: str, stages_from_json: list) -> None:
    """Phase 3a（2026-08-23）反向同步，**3b 上線後複查發現嚴重回歸並於同日修正**：
    原始版本每次都整批 DELETE quote_no 底下全部 case_stages 再重新 INSERT，
    `id` 是 AUTOINCREMENT，每次重建一定拿到全新的 id，跟 db.py 的 Phase 1
    backfill migration（一次性、當時還沒有任何前端會引用這些 id）邏輯相同沒問題；
    但 3b 上線後 `case-management.js` 的階段操作全部直接用 `st.id` 打 granular
    端點（`PUT .../stages/{id}` 等），而 `saveCaseRecord()` 仍然是**整包**送出
    `caseRecord`（含 `stages`，即使這次只改了 materials/payment 等無關欄位）—
    一旦這個整包存檔把 `stages` 傳進來，舊版邏輯就會把使用者手上還在用的
    `st.id` 全部作廢換成新 id，且沒有把新 id 回寫進 `data_json`，導致使用者
    緊接著點任何一個階段操作都會 404。已用 scratch DB 重現：`create_quotation`
    建立階段後緊接著 `GET` 看到的還是舊 id、`update_case_record` 存一次無關的
    `materials` 就讓原本能用的 `st.id` 直接消失。

    修正為**id-preserving 差異合併**：傳入陣列裡 `id` 已存在於這個 quote_no
    現有 `case_stages` 的，原地 UPDATE（id 不變，`dependsOn`/`visits` 刻意不動——
    3b 之後這兩塊只透過各自的專用端點異動，整包存檔送來的可能是還沒更新的舊值，
    覆寫反而有清空風險）；不存在的視為新階段才 INSERT 並依舊邏輯 remap
    `dependsOn`／建立 `visits`；現有列若這次陣列裡完全沒出現，視為使用者刪除，
    整批重建的語意維持不變一併 DELETE（`ON DELETE CASCADE` 清掉其 visits）。
    呼叫端記得**接著呼叫 `_sync_stages_to_json()`** 把這次可能新產生的真實 id
    立刻寫回 `data_json`，前端下一次讀到的就是跟表一致的 id，不會停留在舊值。
    呼叫端負責 commit，這裡不 commit。"""
    existing_ids = {r["id"] for r in conn.execute(
        "SELECT id FROM case_stages WHERE quote_no=?", (quote_no,)
    ).fetchall()}
    now = datetime.now().isoformat()
    id_map = {}
    new_stages = []
    seen_ids = set()

    for idx, st in enumerate(stages_from_json):
        old_id = st.get("id")
        if old_id in existing_ids:
            conn.execute("""
                UPDATE case_stages SET
                    label=?, sort_order=?, done=?, done_at=?, start_date=?, due_date=?,
                    assigned_to=?, updated_at=?
                WHERE id=?
            """, (
                st.get("label") or "", idx,
                1 if st.get("done") else 0, st.get("doneAt") or "",
                st.get("startDate") or "", st.get("dueDate") or "",
                json.dumps(st.get("assignedTo") or [], ensure_ascii=False),
                now, old_id,
            ))
            final_id = old_id
        else:
            cur = conn.execute("""
                INSERT INTO case_stages
                    (quote_no, label, sort_order, done, done_at, start_date, due_date,
                     assigned_to, depends_on, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                quote_no, st.get("label") or "", idx,
                1 if st.get("done") else 0, st.get("doneAt") or "",
                st.get("startDate") or "", st.get("dueDate") or "",
                json.dumps(st.get("assignedTo") or [], ensure_ascii=False),
                "[]", now, now,
            ))
            final_id = cur.lastrowid
            new_stages.append((final_id, st))
        if old_id is not None:
            id_map[old_id] = final_id
        seen_ids.add(final_id)

    for gone_id in existing_ids - seen_ids:
        conn.execute("DELETE FROM case_stages WHERE id=?", (gone_id,))

    for final_id, st in new_stages:
        remapped = [id_map[d] for d in (st.get("dependsOn") or []) if d in id_map]
        if remapped:
            conn.execute("UPDATE case_stages SET depends_on=? WHERE id=?",
                         (json.dumps(remapped, ensure_ascii=False), final_id))
        for v in (st.get("visits") or []):
            conn.execute("""
                INSERT INTO case_stage_visits (stage_id, visit_date, visit_people, note, created_at)
                VALUES (?,?,?,?,?)
            """, (final_id, v.get("visitDate") or "", int(v.get("visitPeople") or 0), v.get("note") or "", now))


def _would_create_cycle(conn, quote_no: str, stage_id: int, candidate_id: int) -> bool:
    """DFS 防環檢查，邏輯照搬 case-management.js 的 wouldCreateCycle()：若讓 stage_id
    依賴 candidate_id，順著 dependsOn 追下去會不會繞回 stage_id 自己。範圍限定在同一
    quote_no 底下的 case_stages。"""
    if stage_id == candidate_id:
        return True
    rows = conn.execute("SELECT id, depends_on FROM case_stages WHERE quote_no=?", (quote_no,)).fetchall()
    depends_map = {r["id"]: json.loads(r["depends_on"] or "[]") for r in rows}
    seen = set()

    def dfs(cur_id):
        if cur_id == stage_id:
            return True
        if cur_id in seen:
            return False
        seen.add(cur_id)
        return any(dfs(d) for d in depends_map.get(cur_id, []))

    return dfs(candidate_id)


@router.get("/api/quotations/{quote_no}/stages")
def list_case_stages_normalized(quote_no: str, authorization: str = Header(None)):
    """caseRecord.stages 正規化第一階段的驗證端點（2026-08-23）——查 case_stages/
    case_stage_visits。第二階段（CRUD 端點）新增後，這個端點仍然是唯讀查詢，尚未接
    進任何現有頁面/流程；`caseRecord.stages` JSON 欄位仍是唯一的讀寫來源，前端還沒
    有任何頁面呼叫這一系列新端點。"""
    _require_user(authorization)
    conn = get_db()
    stage_rows = conn.execute(
        "SELECT * FROM case_stages WHERE quote_no=? ORDER BY sort_order, id",
        (quote_no,),
    ).fetchall()
    stages = [_serialize_stage(conn, sr) for sr in stage_rows]
    conn.close()
    return {"items": stages}


@router.post("/api/quotations/{quote_no}/stages", status_code=201)
def create_case_stage(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """新增階段，對應 case-management.js::addStage()。第二階段 CRUD 端點，尚未接進
    任何前端頁面（2026-08-23）。"""
    _require_user(authorization)
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    max_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) m FROM case_stages WHERE quote_no=?", (quote_no,)
    ).fetchone()["m"]
    now = datetime.now().isoformat()
    cur = conn.execute("""
        INSERT INTO case_stages
            (quote_no, label, sort_order, done, done_at, start_date, due_date,
             assigned_to, depends_on, created_at, updated_at)
        VALUES (?,?,?,0,'','','','[]','[]',?,?)
    """, (quote_no, body.get("label") or "", max_order + 1, now, now))
    new_id = cur.lastrowid
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, new_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    return result


@router.put("/api/quotations/{quote_no}/stages/{stage_id}")
def update_case_stage(quote_no: str, stage_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """局部更新階段欄位（label/done/doneAt/startDate/dueDate），對應 case-management.html
    的 x-model 直接綁定欄位＋renderGantt() 的 on_date_change。不加任何自動邏輯（例如
    done=true 不自動填 doneAt）——維持跟現有前端行為一致，各欄位互相獨立。第二階段
    CRUD 端點，尚未接進任何前端頁面（2026-08-23）。"""
    _require_user(authorization)
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    updates = {}
    if "label" in body:     updates["label"]      = body.get("label") or ""
    if "done" in body:      updates["done"]       = 1 if body.get("done") else 0
    if "doneAt" in body:    updates["done_at"]    = body.get("doneAt") or ""
    if "startDate" in body: updates["start_date"] = body.get("startDate") or ""
    if "dueDate" in body:   updates["due_date"]   = body.get("dueDate") or ""
    if updates:
        updates["updated_at"] = datetime.now().isoformat()
        sql = "UPDATE case_stages SET " + ", ".join(f"{k}=?" for k in updates) + " WHERE id=?"
        conn.execute(sql, list(updates.values()) + [stage_id])
        conn.commit()
        _sync_stages_to_json(conn, quote_no)
        if "due_date" in updates:
            spawn_bg_thread(push_event_for_case_stage_due, args=(stage_id,))
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    return result


@router.delete("/api/quotations/{quote_no}/stages/{stage_id}")
def delete_case_stage(quote_no: str, stage_id: int, authorization: str = Header(None)):
    """刪除階段，同時清掉同案件其他階段 dependsOn 裡對它的參照，對應
    case-management.js::removeStage()。第二階段 CRUD 端點，尚未接進任何前端頁面
    （2026-08-23）。"""
    _require_user(authorization)
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    calendar_event_id = sr["google_calendar_event_id"] or ""
    conn.execute("DELETE FROM case_stages WHERE id=?", (stage_id,))
    siblings = conn.execute("SELECT id, depends_on FROM case_stages WHERE quote_no=?", (quote_no,)).fetchall()
    for s in siblings:
        depends = json.loads(s["depends_on"] or "[]")
        if stage_id in depends:
            depends = [d for d in depends if d != stage_id]
            conn.execute("UPDATE case_stages SET depends_on=? WHERE id=?",
                         (json.dumps(depends, ensure_ascii=False), s["id"]))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    conn.close()
    if calendar_event_id:
        spawn_bg_thread(push_event_delete_for_case_stage, args=(calendar_event_id,))
    return {"ok": True}


@router.patch("/api/quotations/{quote_no}/stages/reorder")
def reorder_case_stages(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """依 orderedIds 陣列順序重寫 sort_order，對應拖曳重排（dragOver/dragEnd）的最終
    結果。第二階段 CRUD 端點，尚未接進任何前端頁面（2026-08-23）。"""
    _require_user(authorization)
    ordered_ids = body.get("orderedIds") or []
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    valid_ids = {r["id"] for r in conn.execute(
        "SELECT id FROM case_stages WHERE quote_no=?", (quote_no,)
    ).fetchall()}
    now = datetime.now().isoformat()
    for idx, sid in enumerate(ordered_ids):
        if sid in valid_ids:
            conn.execute("UPDATE case_stages SET sort_order=?, updated_at=? WHERE id=? AND quote_no=?",
                         (idx, now, sid, quote_no))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    conn.close()
    return {"ok": True}


@router.post("/api/quotations/{quote_no}/stages/{stage_id}/assignees")
def add_stage_assignee(quote_no: str, stage_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """加入負責人，對應 case-management.js::addStageAssignee()。第二階段 CRUD 端點，
    尚未接進任何前端頁面（2026-08-23）。"""
    _require_user(authorization)
    username = body.get("username")
    if not username:
        raise HTTPException(400, "請提供 username")
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    assigned = json.loads(sr["assigned_to"] or "[]")
    if username not in assigned:
        assigned.append(username)
        conn.execute("UPDATE case_stages SET assigned_to=?, updated_at=? WHERE id=?",
                     (json.dumps(assigned, ensure_ascii=False), datetime.now().isoformat(), stage_id))
        conn.commit()
        _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    return result


@router.delete("/api/quotations/{quote_no}/stages/{stage_id}/assignees/{username}")
def remove_stage_assignee(quote_no: str, stage_id: int, username: str, authorization: str = Header(None)):
    """移除負責人，對應 case-management.js::removeStageAssignee()。第二階段 CRUD 端
    點，尚未接進任何前端頁面（2026-08-23）。"""
    _require_user(authorization)
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    assigned = [u for u in json.loads(sr["assigned_to"] or "[]") if u != username]
    conn.execute("UPDATE case_stages SET assigned_to=?, updated_at=? WHERE id=?",
                 (json.dumps(assigned, ensure_ascii=False), datetime.now().isoformat(), stage_id))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    return result


@router.post("/api/quotations/{quote_no}/stages/{stage_id}/depends-on/{candidate_id}")
def toggle_stage_dependency(quote_no: str, stage_id: int, candidate_id: int, authorization: str = Header(None)):
    """切換依賴關係：已存在就移除，不存在就先做防環檢查（DFS，邏輯照搬
    wouldCreateCycle()）再加入。對應 case-management.js::toggleStageDependency()。
    第二階段 CRUD 端點，尚未接進任何前端頁面（2026-08-23）。"""
    _require_user(authorization)
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    if not _get_stage_row(conn, quote_no, candidate_id):
        conn.close(); raise HTTPException(404, "前置階段不存在")
    depends = json.loads(sr["depends_on"] or "[]")
    if candidate_id in depends:
        depends = [d for d in depends if d != candidate_id]
    else:
        if _would_create_cycle(conn, quote_no, stage_id, candidate_id):
            conn.close()
            raise HTTPException(400, "這樣設定會讓階段之間互相循環依賴，請重新選擇前置階段")
        depends.append(candidate_id)
    conn.execute("UPDATE case_stages SET depends_on=?, updated_at=? WHERE id=?",
                 (json.dumps(depends, ensure_ascii=False), datetime.now().isoformat(), stage_id))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    return result


@router.post("/api/quotations/{quote_no}/stages/{stage_id}/visits", status_code=201)
def add_stage_visit(quote_no: str, stage_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """新增拜訪紀錄，對應 case-management.js::addVisit()。第二階段 CRUD 端點，尚未
    接進任何前端頁面（2026-08-23）。"""
    _require_user(authorization)
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO case_stage_visits (stage_id, visit_date, visit_people, note, created_at)
        VALUES (?,?,?,?,?)
    """, (stage_id, body.get("visitDate") or "", int(body.get("visitPeople") or 0), body.get("note") or "", now))
    conn.execute("UPDATE case_stages SET updated_at=? WHERE id=?", (now, stage_id))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    return result


@router.put("/api/quotations/{quote_no}/stages/{stage_id}/visits/{visit_id}")
def update_stage_visit(quote_no: str, stage_id: int, visit_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """局部更新拜訪紀錄欄位，對應 v.visitDate/v.visitPeople/v.note 的 x-model 綁定。
    第二階段 CRUD 端點，尚未接進任何前端頁面（2026-08-23）。"""
    _require_user(authorization)
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    vr = conn.execute("SELECT id FROM case_stage_visits WHERE id=? AND stage_id=?", (visit_id, stage_id)).fetchone()
    if not vr:
        conn.close(); raise HTTPException(404, "拜訪紀錄不存在")
    fields = {}
    if "visitDate" in body:   fields["visit_date"]   = body.get("visitDate") or ""
    if "visitPeople" in body: fields["visit_people"] = int(body.get("visitPeople") or 0)
    if "note" in body:        fields["note"]         = body.get("note") or ""
    if fields:
        sql = "UPDATE case_stage_visits SET " + ", ".join(f"{k}=?" for k in fields) + " WHERE id=?"
        conn.execute(sql, list(fields.values()) + [visit_id])
        conn.execute("UPDATE case_stages SET updated_at=? WHERE id=?", (datetime.now().isoformat(), stage_id))
        conn.commit()
        _sync_stages_to_json(conn, quote_no)
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    return result


@router.delete("/api/quotations/{quote_no}/stages/{stage_id}/visits/{visit_id}")
def delete_stage_visit(quote_no: str, stage_id: int, visit_id: int, authorization: str = Header(None)):
    """刪除拜訪紀錄，對應 case-management.js::removeVisit()。第二階段 CRUD 端點，
    尚未接進任何前端頁面（2026-08-23）。"""
    _require_user(authorization)
    conn = get_db()
    _deny_if_case_locked_unsupported(conn, quote_no, authorization)
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    vr = conn.execute("SELECT id FROM case_stage_visits WHERE id=? AND stage_id=?", (visit_id, stage_id)).fetchone()
    if not vr:
        conn.close(); raise HTTPException(404, "拜訪紀錄不存在")
    conn.execute("DELETE FROM case_stage_visits WHERE id=?", (visit_id,))
    conn.execute("UPDATE case_stages SET updated_at=? WHERE id=?", (datetime.now().isoformat(), stage_id))
    conn.commit()
    _sync_stages_to_json(conn, quote_no)
    conn.close()
    return {"ok": True}


@router.post("/api/quotations/{quote_no}/export")
def record_export(quote_no: str, mode: str = "external", authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT export_count, export_log FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    log   = json.loads(row["export_log"] or "[]")
    count = (row["export_count"] or 0) + 1
    log.append({
        "at": datetime.now().isoformat(),
        "mode": mode,
        "user": user["username"],
        "userDisplay": user.get("display_name") or user["username"],
        "count": count,
    })
    conn.execute("UPDATE quotations SET export_count=?, export_log=? WHERE quote_no=?",
                 (count, json.dumps(log, ensure_ascii=False), quote_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'quotation.export_pdf', 'quotation', quote_no,
           f"{quote_no} PDF 匯出（{mode}）by {user['username']}")
    return {"export_count": count, "log": log}


# ── Payment ───────────────────────────────────────────────────────────────────

@router.patch("/api/quotations/{no}/payment/{idx}")
def mark_payment(no: str, idx: int, body: dict, authorization: str = Header(None)):
    """2026-08-31（安全稽核發現）：標記款項收款/取消收款是本檔案裡少數完全沒有
    角色門檻的金流寫入端點——任何登入使用者（含 viewer）原本都能標記任意案件
    的任意期款項為已收款、任意填實收金額/手續費。比照同檔案 request_payment_
    writeoff()/cancel_payment_writeoff() 同款 admin+ 門檻補上。純改 invoiceNo
    （登錄發票號碼，不影響金額/收款狀態）維持原本任何登入使用者皆可，跟其他
    模組「發票號碼」這類單純登錄用途的欄位一致寬鬆。"""
    user = _require_user(authorization)
    touches_receipt = "received" in body or "actualAmount" in body or "feeAmount" in body
    if touches_receipt and user["role"] not in ("superadmin", "admin") and not user_has_module(user, "cashier"):
        raise HTTPException(403, "僅管理員或出納可標記收款狀態")
    conn = get_db()
    try:
        row = conn.execute("SELECT data_json, updated_at FROM quotations WHERE quote_no=?", (no,)).fetchone()
        if not row:
            raise HTTPException(404, "報價單不存在")
        expected_ua = body.pop("_expectedUpdatedAt", None)
        if expected_ua and row["updated_at"] != expected_ua:
            raise HTTPException(409, "報價單已被其他人修改，請重新載入後再操作")
        data = json.loads(row["data_json"] or "{}")
        cr   = data.setdefault("caseRecord", {})
        pay  = cr.setdefault("payment", {})
        pits = pay.setdefault("items", [])
        if idx < 0 or idx >= len(pits):
            raise HTTPException(400, "款項索引超出範圍")
        gated, change_id = _gate_case_edit(
            conn, no, user, authorization, "payment_mark",
            f"{no} 第{idx+1}期款項標記（{'收款' if body.get('received') else '取消收款'}）",
            {"idx": idx, "body": dict(body)},
        )
        if gated:
            return {"ok": True, "pending": True, "changeRequestId": change_id,
                    "message": "案件已結案並處於半解鎖狀態，此變更已送出，待最高管理員審核通過後才會套用"}
        if "received" in body:
            is_rcv = bool(body["received"])
            pits[idx]["received"]   = is_rcv
            pits[idx]["receivedAt"] = body.get("receivedAt", "") if is_rcv else ""
            pits[idx]["receivedBy"] = body.get("receivedBy", "") if is_rcv else ""
            if is_rcv:
                pits[idx]["actualAmount"] = body.get("actualAmount")
                pits[idx]["feeAmount"]    = body.get("feeAmount") or 0
                pits[idx]["feeNote"]      = body.get("feeNote", "")
                pits[idx]["note"]         = body.get("note", "")
                # 收款進了 MOTRIX 自己哪個銀行帳戶（選填，2026-09-01 新增，供 T100
                # 傳票匯出依銀行帳戶分開設定科目代號用；跟其他欄位一樣直接存
                # data_json，不需要 migration，見 db.py::_m071_paid_bank_account docstring）
                pits[idx]["bankAccountName"] = body.get("bankAccountName", "")
                pits[idx]["bankAccountCode"] = body.get("bankAccountCode", "")
            else:
                for k in ("actualAmount", "feeAmount", "feeNote", "note", "bankAccountName", "bankAccountCode"):
                    pits[idx].pop(k, None)
        if "invoiceNo" in body:
            pits[idx]["invoiceNo"] = body["invoiceNo"]
        now = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    spawn_bg_thread(_backup_quotation, args=(no,))
    label = pits[idx].get('label', f'第{idx+1}期')
    fee   = pits[idx].get("feeAmount") or 0
    action_detail = (
        f'標記收款（手續費 {fee:,}）' if body.get('received') and fee
        else ('標記收款' if body.get('received') else '取消收款')
    )
    _audit(_tok(authorization), 'payment.mark', 'quotation', no, f"{no} {label}（{action_detail}）")
    notify_module_activity("報價單", action_detail, user.get("display_name") or user["username"],
                            f"{no} {label}", "quotations.html")
    return {"ok": True, "updated_at": now}


def _load_payment_item(conn, no, idx):
    row = conn.execute("SELECT data_json, updated_at FROM quotations WHERE quote_no=?", (no,)).fetchone()
    if not row:
        raise HTTPException(404, "報價單不存在")
    data = json.loads(row["data_json"] or "{}")
    cr   = data.setdefault("caseRecord", {})
    pay  = cr.setdefault("payment", {})
    pits = pay.setdefault("items", [])
    if idx < 0 or idx >= len(pits):
        raise HTTPException(400, "款項索引超出範圍")
    return data, pits


@router.post("/api/quotations/{no}/payment/{idx}/invoice-files", status_code=201)
async def upload_payment_item_invoice_files(no: str, idx: int, files: List[UploadFile] = File(...),
                                            authorization: str = Header(None)):
    """款項明細逐期發票掃描檔上傳（2026-08-24 新增，多檔，任何登入使用者皆可
    傳）——跟報價單本身的「客戶回簽」附件是兩回事：那個是整張報價單送出後
    客戶簽回的證明，這裡是每一期款項（訂金款/進度款/驗收款等）各自對應的
    發票影本，比照 mark_payment() 既有的 invoiceNo 文字欄位所在位置，只是
    多存實際檔案。存放路徑跟報價單本身的回簽附件分開（quotation_payment_items
    子資料夾），避免混淆。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        data, pits = _load_payment_item(conn, no, idx)
        label = pits[idx].get('label', f'第{idx+1}期')
        if _check_case_gate(conn, no):
            change_id = _create_case_change_request(
                conn, no, user, authorization, "payment_invoice_upload",
                f"{no} {label} 上傳發票附件（{len(files)} 個檔案）", {"idx": idx},
            )
            new_files = await save_document_files(f"_pending_case_changes/{change_id}", f"{no}_{idx}", files,
                                                  user.get("display_name") or user["username"])
            conn.execute("UPDATE case_change_requests SET staged_files_json=? WHERE id=?",
                         (json.dumps(new_files, ensure_ascii=False), change_id))
            conn.commit()
            return {"ok": True, "pending": True, "changeRequestId": change_id,
                    "message": "案件已結案並處於半解鎖狀態，此上傳已送出，待最高管理員審核通過後才會套用"}
        new_files = await save_document_files("quotation_payment_items", f"{no}_{idx}", files,
                                              user.get("display_name") or user["username"])
        pits[idx].setdefault("invoiceFiles", [])
        pits[idx]["invoiceFiles"].extend(new_files)
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "payment.upload_invoice_files", "quotation", no,
           f"{no} {label}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files, "updated_at": saved_at}


@router.delete("/api/quotations/{no}/payment/{idx}/invoice-files/{file_id}")
def delete_payment_item_invoice_file(no: str, idx: int, file_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        data, pits = _load_payment_item(conn, no, idx)
        if _check_case_gate(conn, no):
            label = pits[idx].get('label', f'第{idx+1}期')
            change_id = _create_case_change_request(
                conn, no, user, authorization, "payment_invoice_delete",
                f"{no} {label} 刪除發票附件", {"idx": idx, "file_id": file_id},
            )
            return {"ok": True, "pending": True, "changeRequestId": change_id,
                    "message": "案件已結案並處於半解鎖狀態，此刪除已送出，待最高管理員審核通過後才會套用"}
        existing = pits[idx].get("invoiceFiles") or []
        pits[idx]["invoiceFiles"] = delete_document_file("quotation_payment_items", f"{no}_{idx}", existing, file_id)
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "payment.delete_invoice_file", "quotation", no, no)
    return {"ok": True, "updated_at": saved_at}


def _load_material_item(conn, no, idx):
    """比照 _load_payment_item()，定位叫料管控清單（cr.caseRecord.materials[]，
    跟出貨單 shipping_notes 是完全不同的資料，這裡是報價單 JSON 裡的料件
    到料追蹤）裡的一筆。"""
    row = conn.execute("SELECT data_json, updated_at FROM quotations WHERE quote_no=?", (no,)).fetchone()
    if not row:
        raise HTTPException(404, "報價單不存在")
    data = json.loads(row["data_json"] or "{}")
    cr   = data.setdefault("caseRecord", {})
    mats = cr.setdefault("materials", [])
    if idx < 0 or idx >= len(mats):
        raise HTTPException(400, "料件索引超出範圍")
    return data, mats


@router.post("/api/quotations/{no}/materials/{idx}/files", status_code=201)
async def upload_material_files(no: str, idx: int, files: List[UploadFile] = File(...),
                                authorization: str = Header(None)):
    """叫料管控單筆料件附件上傳（2026-08-24 新增，多檔，任何登入使用者皆可
    傳）——例如到貨憑證、包裝清單，供部分出貨是跟料件一起出的情境留存證明。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        data, mats = _load_material_item(conn, no, idx)
        name = mats[idx].get("name") or f"第{idx+1}項"
        if _check_case_gate(conn, no):
            change_id = _create_case_change_request(
                conn, no, user, authorization, "material_file_upload",
                f"{no} {name} 上傳附件（{len(files)} 個檔案）", {"idx": idx},
            )
            new_files = await save_document_files(f"_pending_case_changes/{change_id}", f"{no}_{idx}", files,
                                                  user.get("display_name") or user["username"])
            conn.execute("UPDATE case_change_requests SET staged_files_json=? WHERE id=?",
                         (json.dumps(new_files, ensure_ascii=False), change_id))
            conn.commit()
            return {"ok": True, "pending": True, "changeRequestId": change_id,
                    "message": "案件已結案並處於半解鎖狀態，此上傳已送出，待最高管理員審核通過後才會套用"}
        new_files = await save_document_files("quotation_materials", f"{no}_{idx}", files,
                                              user.get("display_name") or user["username"])
        mats[idx].setdefault("files", [])
        mats[idx]["files"].extend(new_files)
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "material.upload_files", "quotation", no,
           f"{no} {name}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files, "updated_at": saved_at}


@router.delete("/api/quotations/{no}/materials/{idx}/files/{file_id}")
def delete_material_file(no: str, idx: int, file_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        data, mats = _load_material_item(conn, no, idx)
        if _check_case_gate(conn, no):
            name = mats[idx].get("name") or f"第{idx+1}項"
            change_id = _create_case_change_request(
                conn, no, user, authorization, "material_file_delete",
                f"{no} {name} 刪除附件", {"idx": idx, "file_id": file_id},
            )
            return {"ok": True, "pending": True, "changeRequestId": change_id,
                    "message": "案件已結案並處於半解鎖狀態，此刪除已送出，待最高管理員審核通過後才會套用"}
        existing = mats[idx].get("files") or []
        mats[idx]["files"] = delete_document_file("quotation_materials", f"{no}_{idx}", existing, file_id)
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "material.delete_file", "quotation", no, no)
    return {"ok": True, "updated_at": saved_at}


@router.post("/api/quotations/{no}/materials/{idx}/invoice-files", status_code=201)
async def upload_material_invoice_files(no: str, idx: int, files: List[UploadFile] = File(...),
                                        authorization: str = Header(None)):
    """叫料管控單筆料件的發票附件上傳（2026-08-25 新增，獨立於既有的到貨憑證/
    包裝清單附件——存在 mats[idx]['invoiceFiles']，跟 mats[idx]['files']
    是兩個各自獨立的清單，比照款項收款項目 item.invoiceFiles 的既有慣例，
    只是那邊掛在款項而這裡掛在叫料料件）。任何登入使用者皆可傳，多檔。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        data, mats = _load_material_item(conn, no, idx)
        name = mats[idx].get("name") or f"第{idx+1}項"
        if _check_case_gate(conn, no):
            change_id = _create_case_change_request(
                conn, no, user, authorization, "material_invoice_upload",
                f"{no} {name} 上傳發票附件（{len(files)} 個檔案）", {"idx": idx},
            )
            new_files = await save_document_files(f"_pending_case_changes/{change_id}", f"{no}_{idx}", files,
                                                  user.get("display_name") or user["username"])
            conn.execute("UPDATE case_change_requests SET staged_files_json=? WHERE id=?",
                         (json.dumps(new_files, ensure_ascii=False), change_id))
            conn.commit()
            return {"ok": True, "pending": True, "changeRequestId": change_id,
                    "message": "案件已結案並處於半解鎖狀態，此上傳已送出，待最高管理員審核通過後才會套用"}
        new_files = await save_document_files("quotation_materials_invoices", f"{no}_{idx}", files,
                                              user.get("display_name") or user["username"])
        mats[idx].setdefault("invoiceFiles", [])
        mats[idx]["invoiceFiles"].extend(new_files)
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "material.upload_invoice_files", "quotation", no,
           f"{no} {name}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files, "updated_at": saved_at}


@router.delete("/api/quotations/{no}/materials/{idx}/invoice-files/{file_id}")
def delete_material_invoice_file(no: str, idx: int, file_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        data, mats = _load_material_item(conn, no, idx)
        if _check_case_gate(conn, no):
            name = mats[idx].get("name") or f"第{idx+1}項"
            change_id = _create_case_change_request(
                conn, no, user, authorization, "material_invoice_delete",
                f"{no} {name} 刪除發票附件", {"idx": idx, "file_id": file_id},
            )
            return {"ok": True, "pending": True, "changeRequestId": change_id,
                    "message": "案件已結案並處於半解鎖狀態，此刪除已送出，待最高管理員審核通過後才會套用"}
        existing = mats[idx].get("invoiceFiles") or []
        mats[idx]["invoiceFiles"] = delete_document_file("quotation_materials_invoices", f"{no}_{idx}", existing, file_id)
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "material.delete_invoice_file", "quotation", no, no)
    return {"ok": True, "updated_at": saved_at}


@router.post("/api/quotations/{no}/payment/{idx}/request-writeoff")
def request_payment_writeoff(no: str, idx: int, body: WriteOffRequestIn, authorization: str = Header(None)):
    """admin+ 申請將該筆收款的稅額沖銷（歸零），需 superadmin 審核。"""
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員可申請沖銷")
    conn = get_db()
    try:
        _deny_if_case_locked_unsupported(conn, no, authorization)
        data, pits = _load_payment_item(conn, no, idx)
        item = pits[idx]
        if item.get("writeOffStatus") == "pending":
            raise HTTPException(409, "此筆款項已有待審核的沖銷申請")
        if item.get("taxExempt"):
            raise HTTPException(409, "此筆款項已完成沖銷")
        requester_display = user.get("display_name") or user["username"]
        now = datetime.now().isoformat()
        item["writeOffStatus"]      = "pending"
        item["writeOffReason"]      = body.reason or ''
        item["writeOffRequestedBy"] = requester_display
        item["writeOffRequestedAt"] = now
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    spawn_bg_thread(_backup_quotation, args=(no,))
    label = item.get('label', f'第{idx+1}期')
    _audit(_tok(authorization), 'payment.writeoff_request', 'quotation', no, f"{no} {label} 申請沖銷")
    notify_module_activity("報價單", "申請沖銷", requester_display, f"{no} {label}", "quotations.html")
    return {"ok": True, "updated_at": saved_at}


@router.post("/api/quotations/{no}/payment/{idx}/cancel-writeoff")
def cancel_payment_writeoff(no: str, idx: int, authorization: str = Header(None)):
    """申請人本人或 superadmin 取消待審核的沖銷申請。"""
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員可取消沖銷申請")
    conn = get_db()
    try:
        _deny_if_case_locked_unsupported(conn, no, authorization)
        data, pits = _load_payment_item(conn, no, idx)
        item = pits[idx]
        if item.get("writeOffStatus") != "pending":
            raise HTTPException(409, "此筆款項無待審核的沖銷申請")
        requester_display = user.get("display_name") or user["username"]
        if user["role"] != "superadmin" and item.get("writeOffRequestedBy") != requester_display:
            raise HTTPException(403, "只能取消自己發出的沖銷申請")
        for k in ("writeOffStatus", "writeOffReason", "writeOffRequestedBy", "writeOffRequestedAt"):
            item.pop(k, None)
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    spawn_bg_thread(_backup_quotation, args=(no,))
    label = item.get('label', f'第{idx+1}期')
    _audit(_tok(authorization), 'payment.writeoff_cancel', 'quotation', no, f"{no} {label} 取消沖銷申請")
    notify_module_activity("報價單", "取消沖銷申請", requester_display, f"{no} {label}", "quotations.html")
    return {"ok": True, "updated_at": saved_at}


@router.post("/api/quotations/{no}/payment/{idx}/approve-writeoff")
def approve_payment_writeoff(no: str, idx: int, body: WriteOffApproveIn, authorization: str = Header(None)):
    """superadmin 審核沖銷申請 — approve=True 生效（稅額歸零）；False 駁回。"""
    user = _require_user(authorization)
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理者可審核沖銷申請")
    conn = get_db()
    try:
        _deny_if_case_locked_unsupported(conn, no, authorization)
        data, pits = _load_payment_item(conn, no, idx)
        item = pits[idx]
        if item.get("writeOffStatus") != "pending":
            raise HTTPException(409, "此筆款項無待審核的沖銷申請")
        approver_display = user.get("display_name") or user["username"]
        now = datetime.now().isoformat()
        if body.approve:
            item["writeOffStatus"]    = "approved"
            item["writeOffApprovedBy"] = approver_display
            item["writeOffApprovedAt"] = now
            item["taxExempt"] = True
            action_detail = "核准沖銷"
        else:
            item["writeOffStatus"]       = "rejected"
            item["writeOffRejectReason"] = body.reject_reason or ''
            item["writeOffApprovedBy"]   = approver_display
            item["writeOffApprovedAt"]   = now
            action_detail = "駁回沖銷申請"
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    spawn_bg_thread(_backup_quotation, args=(no,))
    label = item.get('label', f'第{idx+1}期')
    _audit(_tok(authorization), 'payment.writeoff_approve' if body.approve else 'payment.writeoff_reject',
           'quotation', no, f"{no} {label}（{action_detail}）")
    notify_module_activity("報價單", action_detail, approver_display, f"{no} {label}", "quotations.html")
    return {"ok": True, "updated_at": saved_at, "approved": body.approve}


# ── Settlement ────────────────────────────────────────────────────────────────

class SettlementIn(BaseModel):
    settlement: dict


@router.get("/api/quotations/{quote_no}/settlement")
def get_settlement(quote_no: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    data = json.loads(row["data_json"] or "{}")
    return {"settlement": data.get("settlement", None), "items": data.get("items", []),
            "tot": data.get("tot", {}), "customerName": data.get("customerName", ""),
            "projectName": data.get("projectName", "")}


@router.put("/api/quotations/{quote_no}/settlement")
def update_settlement(quote_no: str, body: SettlementIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    now  = datetime.now().isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    data = json.loads(row["data_json"] or "{}")
    existing_settlement = data.get("settlement") or {}
    if existing_settlement.get("status") == "finalized" and user["role"] != "superadmin":
        conn.close()
        raise HTTPException(403, "精算已完結，僅超級管理員可重新修改")
    data["settlement"] = body.settlement

    # append edit history entry for settlement saves
    is_finalized = body.settlement.get("status") == "finalized"
    history = data.get("editHistory") or []
    if not isinstance(history, list):
        history = []
    settle_rev = len(history) + 1
    history.append({
        "rev":       settle_rev,
        "at":        now,
        "by":        user["username"],
        "byDisplay": user["display_name"] or user["username"],
        "type":      "settlement_finalized" if is_finalized else "settlement_draft",
    })
    data["editHistory"] = history

    now = save_quotation_json(conn, quote_no, data, updated_at=now)
    conn.commit()
    conn.close()
    cname = row["customer_name"] or ""
    spawn_bg_thread(_backup_quotation, args=(quote_no,))
    _audit(_tok(authorization), 'quotation.settlement', 'quotation', quote_no,
           f"{quote_no}（{cname}）成本精算{'完結' if is_finalized else '更新'}",
           {"rev": settle_rev})
    if is_finalized:
        notify_settlement_finalized(
            quote_no, cname,
            user.get("display_name") or user["username"],
        )
    return {"ok": True, "updated_at": now}


def _load_settlement_extra_item(conn, no, idx):
    """比照 _load_payment_item()，定位精算頁「額外支出」清單（data.settlement.
    extraItems[]）裡的一筆，供發票/收據附件上傳/刪除使用。"""
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()
    if not row:
        raise HTTPException(404, "報價單不存在")
    data  = json.loads(row["data_json"] or "{}")
    stl   = data.setdefault("settlement", {})
    items = stl.setdefault("extraItems", [])
    if idx < 0 or idx >= len(items):
        raise HTTPException(400, "額外支出項目索引超出範圍")
    if stl.get("status") == "finalized":
        raise HTTPException(403, "精算已完結，僅超級管理員可重新修改")
    return data, items


@router.post("/api/quotations/{no}/settlement/extra/{idx}/files", status_code=201)
async def upload_settlement_extra_files(no: str, idx: int, files: List[UploadFile] = File(...),
                                        authorization: str = Header(None)):
    """精算「額外支出」單筆項目的發票/收據附件上傳（多檔，任何登入使用者皆可
    傳；精算已完結時一律擋下，與 update_settlement() 的完結後鎖定規則一致，
    但這裡不比照該端點放寬 superadmin 例外——附件是佐證用途，完結後若真的
    要補件，走 reopenDraft() 重新開啟精算即可）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        data, items = _load_settlement_extra_item(conn, no, idx)
        new_files = await save_document_files("quotation_settlement_extra", f"{no}_{idx}", files,
                                              user.get("display_name") or user["username"])
        items[idx].setdefault("files", [])
        items[idx]["files"].extend(new_files)
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "settlement.upload_extra_files", "quotation", no,
           f"{no}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files, "updated_at": saved_at}


@router.delete("/api/quotations/{no}/settlement/extra/{idx}/files/{file_id}")
def delete_settlement_extra_file(no: str, idx: int, file_id: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    try:
        data, items = _load_settlement_extra_item(conn, no, idx)
        existing = items[idx].get("files") or []
        items[idx]["files"] = delete_document_file("quotation_settlement_extra", f"{no}_{idx}", existing, file_id)
        saved_at = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "settlement.delete_extra_file", "quotation", no, no)
    return {"ok": True, "updated_at": saved_at}


# ── Approval queue ────────────────────────────────────────────────────────────

def _queue_tier_fields(approval_json_raw: str) -> dict:
    """三種文件類型（報價單／承攬商匯款申請／開票申請憑據）的 approval 欄位
    形狀完全相同（tiers/currentTier，見 §5.3／§5.9），可共用同一段換算邏輯。"""
    try:
        appr = json.loads(approval_json_raw or "{}")
    except Exception:
        appr = {}
    tiers  = _active_tiers(appr)
    ct_idx = _current_tier_idx(appr)
    cur_tier_approvers = tiers[ct_idx].get("approvers") or [] if tiers and ct_idx < len(tiers) else []
    return {
        "appr":               appr,
        "requestedBy":        appr.get("requestedBy") or "",
        "requestedByDisplay": appr.get("requestedByDisplay") or appr.get("requestedBy") or "",
        "requestedAt":        appr.get("requestedAt") or "",
        "tiers":              tiers,
        "currentTier":        ct_idx,
        "tierCount":          len(tiers),
        "currentApprovers":   cur_tier_approvers,
    }


@router.get("/api/approval-queue")
def get_approval_queue(authorization: str = Header(None)):
    """2026-08-21 起合併三種待簽核文件類型：報價單、承攬商匯款申請、開票申請
    憑據；2026-08-24 補上出貨單（§5.8 的舊功能，統一佇列蓋上去時漏掉）與請款單
    （新增單據類型，見 routers/payment_requests.py）。刻意
    沿用報價單既有的欄位名稱（quoteNo/customer/projectName/total/quoteDate/
    salesPerson）承載各類型的資料，讓既有前端列表渲染邏輯幾乎不用改，只多一個
    `type` 欄位供前端分流動作按鈕與連結（見 approval-queue.html）。承攬商匯款
    申請／開票申請憑據／出貨單都沒有「拒絕結案」這種永久終止端點（只有報價單
    有），前端會依 type 隱藏該按鈕。2026-08-26 補上 type='case_change'（已結案
    案件半解鎖期間的變更/上傳待審核，見 case_change_requests 表）——這類項目不是
    真正的多層 tiers 簽核，是單層「任一 superadmin 皆可審核」，approve/reject
    走獨立端點 POST /api/case-changes/{id}/approve|reject，不是既有的
    quotation 簽核端點，前端需依 type 分流。

    2026-08-28：額外回傳 myDelegatedFor（目前使用者正在代理誰的簽核權限，見
    approval_delegates 表／active_delegators_for()）——check_approve_permission()
    後端早就支援代理人真的能完成簽核動作，但這個佇列列表／canApprove() 前端
    判斷原本只比對 currentApprovers 的 username 是否等於自己，代理人登入後完全
    看不到任何項目被標成「輪到我」、核准/退回按鈕也不會出現，等於代理人設定了
    也沒用（除非剛好知道確切單號直接開頁面）。前端 canApprove()/myPendingCount
    要一併比對這份清單。"""
    user = _require_user(authorization)
    conn = get_db()
    my_delegated_for = sorted(active_delegators_for(conn, user["username"]))
    items = []

    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, total, quote_date, sales_person,
               json_extract(data_json,'$.approval') as approval_json
        FROM quotations
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    for r in rows:
        f = _queue_tier_fields(r["approval_json"])
        items.append({
            "type":                "quotation",
            "quoteNo":             r["quote_no"],
            "customer":            r["customer_name"] or "",
            "projectName":         r["project_name"] or "",
            "total":               r["total"] or 0,
            "quoteDate":           r["quote_date"] or "",
            "salesPerson":         r["sales_person"] or "",
            "requestedBy":         f["requestedBy"],
            "requestedByDisplay":  f["requestedByDisplay"],
            "requestedAt":         f["requestedAt"],
            "isEditApproval":      f["appr"].get("isEditApproval", False),
            "reasons":             f["appr"].get("reasons") or [],
            "tiers":               f["tiers"],
            "currentTier":         f["currentTier"],
            "tierCount":           f["tierCount"],
            "currentApprovers":    f["currentApprovers"],
        })

    cv_rows = conn.execute("""
        SELECT voucher_no, quote_no, snapshot_json, created_at,
               json_extract(data_json,'$.approval') as approval_json
        FROM contractor_payment_vouchers
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    for r in cv_rows:
        f = _queue_tier_fields(r["approval_json"])
        try:
            snap = json.loads(r["snapshot_json"] or "{}")
        except Exception:
            snap = {}
        items.append({
            "type":                "contractor_voucher",
            "quoteNo":             r["voucher_no"],
            "customer":            snap.get("vendorName") or "外包人員點工",
            "projectName":         f"關聯案件 {r['quote_no']}",
            "total":               snap.get("grandTotal", 0),
            "quoteDate":           (r["created_at"] or "")[:10],
            "salesPerson":         "",
            "requestedBy":         f["requestedBy"],
            "requestedByDisplay":  f["requestedByDisplay"],
            "requestedAt":         f["requestedAt"],
            "isEditApproval":      False,
            "reasons":             [],
            "tiers":               f["tiers"],
            "currentTier":         f["currentTier"],
            "tierCount":           f["tierCount"],
            "currentApprovers":    f["currentApprovers"],
            "linkedQuoteNo":       r["quote_no"],
            # 2026-08-30：使用者要求簽核佇列連同申請單本身都要顯示應付款日期／
            # 匯款帳戶／存簿圖檔／廠商發票，這裡直接從凍結快照帶出，不用簽核人員
            # 另外點開案件管理才看得到匯款要用的資訊。
            "payableDate":         snap.get("payableDate") or "",
            "bankName":            snap.get("bankName") or "",
            "bankBranch":          snap.get("bankBranch") or "",
            "bankAccountName":     snap.get("bankAccountName") or "",
            "bankAccountNumber":   snap.get("bankAccountNumber") or "",
            "bankPassbookImage":   snap.get("bankPassbookImage") or "",
            "invoiceFiles":        snap.get("invoiceFiles") or [],
        })

    iv_rows = conn.execute("""
        SELECT voucher_no, quote_no, amount, snapshot_json, created_at,
               json_extract(data_json,'$.approval') as approval_json
        FROM invoice_vouchers
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    for r in iv_rows:
        f = _queue_tier_fields(r["approval_json"])
        try:
            snap = json.loads(r["snapshot_json"] or "{}")
        except Exception:
            snap = {}
        items.append({
            "type":                "invoice_voucher",
            "quoteNo":             r["voucher_no"],
            "customer":            snap.get("customerName") or "",
            "projectName":         snap.get("projectName") or f"關聯案件 {r['quote_no']}",
            "total":               r["amount"] or 0,
            "quoteDate":           (r["created_at"] or "")[:10],
            "salesPerson":         "",
            "requestedBy":         f["requestedBy"],
            "requestedByDisplay":  f["requestedByDisplay"],
            "requestedAt":         f["requestedAt"],
            "isEditApproval":      False,
            "reasons":             [],
            "tiers":               f["tiers"],
            "currentTier":         f["currentTier"],
            "tierCount":           f["tierCount"],
            "currentApprovers":    f["currentApprovers"],
            "linkedQuoteNo":       r["quote_no"],
        })

    sn_rows = conn.execute("""
        SELECT note_no, quote_no, customer_name, project_name, items_json, ship_date, created_at,
               json_extract(data_json,'$.approval') as approval_json
        FROM shipping_notes
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    for r in sn_rows:
        f = _queue_tier_fields(r["approval_json"])
        try:
            item_count = len(json.loads(r["items_json"] or "[]"))
        except Exception:
            item_count = 0
        items.append({
            "type":                "shipping_note",
            "quoteNo":             r["note_no"],
            "customer":            r["customer_name"] or "",
            "projectName":         r["project_name"] or "",
            "total":               item_count,
            "quoteDate":           r["ship_date"] or (r["created_at"] or "")[:10],
            "salesPerson":         "",
            "requestedBy":         f["requestedBy"],
            "requestedByDisplay":  f["requestedByDisplay"],
            "requestedAt":         f["requestedAt"],
            "isEditApproval":      False,
            "reasons":             [],
            "tiers":               f["tiers"],
            "currentTier":         f["currentTier"],
            "tierCount":           f["tierCount"],
            "currentApprovers":    f["currentApprovers"],
            "linkedQuoteNo":       r["quote_no"],
        })

    pr_rows = conn.execute("""
        SELECT request_no, quote_no, amount, snapshot_json, created_at,
               json_extract(data_json,'$.approval') as approval_json
        FROM payment_requests
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    for r in pr_rows:
        f = _queue_tier_fields(r["approval_json"])
        try:
            snap = json.loads(r["snapshot_json"] or "{}")
        except Exception:
            snap = {}
        items.append({
            "type":                "payment_request",
            "quoteNo":             r["request_no"],
            "customer":            snap.get("customerName") or "",
            "projectName":         snap.get("projectName") or f"關聯案件 {r['quote_no']}",
            "total":               r["amount"] or 0,
            "quoteDate":           (r["created_at"] or "")[:10],
            "salesPerson":         "",
            "requestedBy":         f["requestedBy"],
            "requestedByDisplay":  f["requestedByDisplay"],
            "requestedAt":         f["requestedAt"],
            "isEditApproval":      False,
            "reasons":             [],
            "tiers":               f["tiers"],
            "currentTier":         f["currentTier"],
            "tierCount":           f["tierCount"],
            "currentApprovers":    f["currentApprovers"],
            "linkedQuoteNo":       r["quote_no"],
        })

    ccr_rows = conn.execute("""
        SELECT id, quote_no, action_type, summary, requested_by, requested_by_display, requested_at
        FROM case_change_requests
        WHERE status='pending'
        ORDER BY id DESC
    """).fetchall()
    for r in ccr_rows:
        cust = conn.execute(
            "SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (r["quote_no"],)
        ).fetchone()
        items.append({
            # 刻意留空 tiers（跟既有「無 tiers 設定時任一 superadmin 皆可簽核」
            # 的 fallback 語意共用同一套前端 canApprove() 判斷——不是真正的多層
            # 循序簽核，是單層「任一 superadmin」，用空 tiers 借用既有邏輯最簡單，
            # 不需要另外構造「這層有 N 個 approvers 但誰簽都算數」的新語意。
            "type":                "case_change",
            "quoteNo":             f"{r['quote_no']}-CCR{r['id']}",
            "customer":            (cust["customer_name"] if cust else "") or "",
            "projectName":         r["summary"] or "",
            "total":               0,
            "quoteDate":           (r["requested_at"] or "")[:10],
            "salesPerson":         "",
            "requestedBy":         r["requested_by"] or "",
            "requestedByDisplay":  r["requested_by_display"] or r["requested_by"] or "",
            "requestedAt":         r["requested_at"] or "",
            "isEditApproval":      False,
            "reasons":             [],
            "tiers":               [],
            "currentTier":         0,
            "tierCount":           0,
            "currentApprovers":    [],
            "linkedQuoteNo":       r["quote_no"],
            "changeRequestId":     r["id"],
            "actionType":          r["action_type"],
        })

    conn.close()

    groups: dict = defaultdict(list)
    for item in items:
        groups[item["requestedBy"]].append(item)

    queue = []
    for username, group_items in groups.items():
        group_items.sort(key=lambda x: x["requestedAt"])
        queue.append({
            "requestedBy":        username,
            "requestedByDisplay": group_items[0]["requestedByDisplay"] if group_items else username,
            "count":              len(group_items),
            "items":              group_items,
        })
    queue.sort(key=lambda g: g["items"][0]["requestedAt"] if g["items"] else "")

    return {"queue": queue, "total": len(items), "myDelegatedFor": my_delegated_for}


@router.get("/api/approval-queue/count")
def get_approval_queue_count(authorization: str = Header(None)):
    """輕量端點：回傳目前輪到當前用戶簽核的項目數量（報價單＋承攬商匯款申請＋
    開票申請憑據＋出貨單，2026-08-21 起合併前三者、2026-08-24 補上出貨單）。
    每一頁 topbar 都會呼叫這支（static/notif.js），刻意維持跟原本一樣的輕量
    寫法（只挑 approval_json 一欄），不要拖累全站每頁的載入速度。

    2026-08-28：一併算進「我目前代理誰」（見 get_approval_queue() 同一則
    2026-08-28 說明），否則代理人這段期間看到的側邊欄角標數字仍然是 0，
    跟佇列頁面本身修好後的狀態矛盾。"""
    u = _require_user(authorization)
    my_username = u["username"]
    conn = get_db()
    my_delegated_for = active_delegators_for(conn, my_username)
    my_usernames = {my_username} | my_delegated_for
    approval_jsons = [r[0] for r in conn.execute(
        "SELECT json_extract(data_json,'$.approval') FROM quotations WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT json_extract(data_json,'$.approval') FROM contractor_payment_vouchers "
        "WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT json_extract(data_json,'$.approval') FROM invoice_vouchers WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT json_extract(data_json,'$.approval') FROM shipping_notes WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT json_extract(data_json,'$.approval') FROM payment_requests WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    # 已結案案件半解鎖變更（2026-08-26）：單層審核，任一 superadmin 皆算「輪到我」，
    # 不像其他文件類型需要比對 tiers 當層 approver username，直接另外加總。
    ccr_count = 0
    if u["role"] == "superadmin":
        ccr_count = conn.execute(
            "SELECT COUNT(*) c FROM case_change_requests WHERE status='pending'"
        ).fetchone()["c"]
    conn.close()
    count = ccr_count
    for approval_json in approval_jsons:
        try:
            appr    = json.loads(approval_json or "{}")
            tiers   = _active_tiers(appr)
            ct_idx  = _current_tier_idx(appr)
            if tiers and ct_idx < len(tiers):
                approvers = tiers[ct_idx].get("approvers") or []
                if any(a.get("username") in my_usernames and a.get("status") != "approved"
                       for a in approvers):
                    count += 1
        except Exception:
            pass
    return {"count": count}


@router.post("/api/quotations/{quote_no}/approve")
def approve_quotation(quote_no: str, body: ApprovalActionBody, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM quotations WHERE quote_no=? AND status IN ('待審核','簽核中')",
        (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在或不在待審核狀態")
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
        my_entry = first_pending

        my_entry["status"]     = "approved"
        my_entry["approvedAt"] = now

        tier_done = all(a.get("status") == "approved" for a in approvers)
        if tier_done:
            appr["currentTier"] = ct_idx + 1
            all_done = (ct_idx + 1) >= len(tiers)
            if not all_done:
                next_tier = tiers[ct_idx + 1]
                _next_names = []
                for na in next_tier.get("approvers") or []:
                    _notify(na["username"], "approval_request", quote_no, quote_no,
                            f"報價單 {quote_no}（{cname}）輪到您簽核（第 {ct_idx + 2} 層 / 共 {len(tiers)} 層）")
                    _next_names.append(na["username"])
                notify_next_tier(quote_no, cname, ct_idx + 2, len(tiers), _next_names)
        else:
            all_done = False

        # write back tiers
        appr["tiers"] = tiers
        appr.pop("steps", None)
        appr.pop("currentStep", None)
        detail_status = f"第 {ct_idx + 1} 層 {my_entry.get('displayName', user['username'])} 已簽核"
    else:
        # no tiers on this quotation — check global settings first
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")
        # If global approval_flow has tiers configured, block the no-tier fallback.
        # This prevents a quotation submitted before flow was set (tiers missing)
        # from being approved without going through the flow.
        _global_flow   = resolve_active_flow_setting("quotation")
        try:
            _global_tiers = _setting_to_active_tiers(_global_flow, conn, appr.get("requestedBy"))
        except UnresolvedManagerError as e:
            conn.close()
            raise HTTPException(400, str(e))
        if _global_tiers:
            conn.close()
            raise HTTPException(
                403,
                "系統已設定簽核流程，此報價單缺少簽核層資料。"
                "請請申請人收回並重新送審，以套用最新簽核設定"
            )
        self_block_msg = check_no_tier_self_approval(conn, appr, user)
        if self_block_msg:
            conn.close()
            raise HTTPException(403, self_block_msg)
        all_done      = True
        detail_status = "超級管理員簽核"

    if all_done:
        appr["approvedBy"]        = user["username"]
        appr["approvedByDisplay"] = body.approvedByDisplay or user.get("display_name") or user["username"]
        appr["approvedAt"]        = now
        appr["status"]            = "approved"
        d["approval"] = appr
        save_quotation_json(conn, quote_no, d, status="已送出", updated_at=now)
        approver_name = appr.get("approvedByDisplay") or user.get("display_name") or user.get("username") or ""
        spawn_bg_thread(_generate_quotation_pdf, args=(quote_no, approver_name, '簽核'))
        notify_approved(quote_no, cname, approver_name, appr.get("requestedBy") or "")
        detail_status = "已送出"
    else:
        d["approval"] = appr
        # 若 tier 已推進（至少一層完成但未全部通過）→ 顯示「簽核中」
        new_status = "簽核中" if (appr.get("currentTier") or 0) > 0 else None
        save_quotation_json(conn, quote_no, d, status=new_status, updated_at=now)

    conn.commit()
    conn.close()
    _audit(_tok(authorization), "quotation.approve", "quotation", quote_no,
           f"{quote_no}（{cname}）", {"allDone": all_done, "status": detail_status})
    return {"ok": True, "allDone": all_done}


@router.post("/api/quotations/{quote_no}/reject")
def reject_quotation(quote_no: str, body: ApprovalActionBody, authorization: str = Header(None)):
    """退回修改：清除簽核、單號升版（-Rn）、狀態回草稿，申請人可重新編輯後再送審。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM quotations WHERE quote_no=? AND status IN ('待審核','簽核中')",
        (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在或不在待審核狀態")
    cname = row["customer_name"] or ""
    d     = json.loads(row["data_json"] or "{}")
    appr  = d.get("approval") or {}
    tiers = _active_tiers(appr)

    ct_idx = _current_tier_idx(appr)
    ok, status_code, err_msg = check_reject_permission(tiers, ct_idx, user, conn=conn)
    if not ok:
        conn.close()
        raise HTTPException(status_code, err_msg)

    new_no = _next_revision_no(quote_no)
    note   = body.note or ""
    now    = datetime.now().isoformat()

    # Append to statusLog
    if not isinstance(d.get("statusLog"), list):
        d["statusLog"] = []
    _from_status = d.get("status") or "待審核"
    d["statusLog"].append({
        "at":   now,
        "user": user.get("display_name") or user["username"],
        "from": _from_status,
        "to":   f"草稿（退回，改為 {new_no}）",
        "note": note,
    })
    # Snapshot items/summary for submitter reference after return
    d["returnInfo"] = {
        "returnedBy":        user["username"],
        "returnedByDisplay": user.get("display_name") or user["username"],
        "returnedAt":        now,
        "note":              note,
        "originalQuoteNo":   quote_no,
        "previousItems": [
            {
                "type":        i.get("type", "item"),
                "description": i.get("description", ""),
                "brand":       i.get("brand", ""),
                "qty":         i.get("qty", 0),
                "unit":        i.get("unit", ""),
                "unitPrice":   i.get("unitPrice", 0),
            }
            for i in (d.get("items") or [])
            if i.get("description", "").strip() or i.get("type") == "header"
        ],
    }
    # Update quoteNo and status in data_json too
    d["quoteNo"] = new_no
    d["status"]  = "草稿"
    d.pop("approval", None)

    conn.execute(
        "UPDATE quotations SET quote_no=?, status='草稿', data_json=?, updated_at=? WHERE quote_no=?",
        (new_no, json.dumps(d, ensure_ascii=False), now, quote_no)
    )
    conn.commit()

    requester = appr.get("requestedBy")
    if requester:
        _notify(requester, "approval_returned", new_no, new_no,
                f"報價單 {new_no}（原 {quote_no}，{cname}）已退回修改，請確認後重新送審")
        notify_returned(quote_no, new_no, cname, note, requester)
    conn.close()
    _audit(_tok(authorization), "quotation.return", "quotation", new_no,
           f"{new_no}（原 {quote_no}，{cname}）", {"note": note, "previous_no": quote_no})
    return {"ok": True, "new_quote_no": new_no}


@router.post("/api/quotations/{quote_no}/reject-final")
def reject_final_quotation(quote_no: str, body: ApprovalActionBody, authorization: str = Header(None)):
    """拒絕結案：永久鎖定，不可再修改或送審。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM quotations WHERE quote_no=? AND status IN ('待審核','簽核中')",
        (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在或不在待審核狀態")
    cname = row["customer_name"] or ""
    d     = json.loads(row["data_json"] or "{}")
    appr  = d.get("approval") or {}
    tiers = _active_tiers(appr)

    if tiers:
        ct_idx    = _current_tier_idx(appr)
        tier      = tiers[ct_idx] if ct_idx < len(tiers) else {}
        approvers = tier.get("approvers") or []
        is_in_tier = any(a["username"] == user["username"] for a in approvers)
        if not is_in_tier and user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "無拒絕權限（非當層簽核人員）")
    else:
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")

    note = body.note or ""
    now  = datetime.now().isoformat()
    d["rejection"] = {
        "rejectedBy":        user["username"],
        "rejectedByDisplay": user.get("display_name") or user["username"],
        "rejectedAt":        now,
        "note":              note,
    }
    if not isinstance(d.get("statusLog"), list):
        d["statusLog"] = []
    d["statusLog"].append({
        "at":   now,
        "user": user.get("display_name") or user["username"],
        "from": "待審核",
        "to":   "已拒絕",
        "note": note,
    })

    save_quotation_json(conn, quote_no, d, status="已拒絕", updated_at=now)
    conn.commit()

    requester = appr.get("requestedBy")
    if requester:
        suffix = f"：{note}" if note else ""
        _notify(requester, "approval_rejected", quote_no, quote_no,
                f"報價單 {quote_no}（{cname}）已被拒絕結案{suffix}")
    conn.close()
    _audit(_tok(authorization), "quotation.reject_final", "quotation", quote_no,
           f"{quote_no}（{cname}）", {"note": note})
    return {"ok": True}


# ── Case updates (activity feed / comment board) ─────────────────────────────

@router.get("/api/quotations/{quote_no}/updates")
def list_case_updates(quote_no: str, authorization: str = Header(None)):
    """Return merged activity feed: manual comments + work_logs + daily_task completions
    + dev_logs + dev_case_status. 2026-08-28: every source's created_at is normalized via
    norm_at() before the final string-sort — the five source tables store timestamps in
    different formats (some 'T'-separated with microseconds, dev_logs space-separated
    without), and ASCII ' ' < 'T' meant dev_log entries always sorted as "older" than any
    same-day entry from the other sources regardless of actual time. See norm_at() docstring."""
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT quote_no FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "報價單不存在")
    user = _require_user(authorization)

    dn_map = {r["username"]: (r["display_name"] or r["username"])
              for r in conn.execute("SELECT username, display_name FROM users").fetchall()}
    results = []

    # 1. Manual comments
    for c in conn.execute(
        "SELECT id, author, content, type, created_at FROM case_updates "
        "WHERE quote_no=? ORDER BY created_at DESC", (quote_no,)
    ).fetchall():
        results.append({
            "id": c["id"],
            "source": "comment",
            "author": c["author"],
            "authorDisplay": dn_map.get(c["author"], c["author"]),
            "content": c["content"],
            "created_at": norm_at(c["created_at"]),
            "canDelete": (user["username"] == c["author"]
                          or user["role"] in ("superadmin", "admin")),
            "important": c["type"] == "important",
        })

    # 2. Work logs tagged with this case
    for w in conn.execute(
        "SELECT w.id, w.log_date, w.content, w.hours, w.created_at, w.photos, w.contact_type, "
        "u.username, u.display_name "
        "FROM work_logs w LEFT JOIN users u ON u.id=w.user_id "
        "WHERE w.case_no=?", (quote_no,)
    ).fetchall():
        results.append({
            "id": f"wl_{w['id']}",
            "workLogId": w["id"],
            "source": "work_log",
            "author": w["username"] or "",
            "authorDisplay": w["display_name"] or w["username"] or "未知",
            "content": w["content"],
            "logDate": w["log_date"],
            "hours": w["hours"],
            "contactType": w["contact_type"] or "",
            "created_at": norm_at(w["created_at"]),
            "photos": json.loads(w["photos"] or "[]"),
            "canDelete": False,
        })

    # 3. Daily task completions for tasks linked to this case
    for dt in conn.execute(
        "SELECT t.id AS task_id, t.title, t.task_date, "
        "c.username, c.report, c.completed_at, c.occurrence_date "
        "FROM daily_tasks t "
        "JOIN daily_task_completions c ON c.task_id=t.id "
        "WHERE t.case_no=? AND c.completed=1 AND t.is_deleted=0", (quote_no,)
    ).fetchall():
        results.append({
            "id": f"dt_{dt['task_id']}_{dt['username']}_{dt['occurrence_date']}",
            "source": "daily_task",
            "author": dt["username"],
            "authorDisplay": dn_map.get(dt["username"], dt["username"]),
            "content": dt["report"] or f"完成工作事項：{dt['title']}",
            "taskTitle": dt["title"],
            "occurrenceDate": dt["occurrence_date"],
            "created_at": norm_at(dt["completed_at"] or ""),
            "canDelete": False,
        })

    # 4. Dev-CRM 開發記錄 + 案件狀態變更（業務開發轉建此報價單時才有）
    dev_case = conn.execute(
        "SELECT id FROM dev_cases WHERE converted_quote_no=? AND is_deleted=0", (quote_no,)
    ).fetchone()
    if dev_case:
        case_id = dev_case["id"]
        for dl in conn.execute(
            "SELECT dl.id, dl.log_date, dl.channel, dl.content, dl.next_action, dl.created_at, "
            "lu.username AS log_username, lu.display_name AS log_display, "
            "cu.username AS created_username, cu.display_name AS created_display "
            "FROM dev_logs dl "
            "LEFT JOIN users lu ON lu.id = dl.log_by "
            "LEFT JOIN users cu ON cu.id = dl.created_by "
            "WHERE dl.case_id=? AND dl.needs_approval=0", (case_id,)
        ).fetchall():
            content = dl["content"] or ""
            if dl["next_action"]:
                content += f"\n→ 下一步：{dl['next_action']}"
            results.append({
                "id": f"dcl_{dl['id']}",
                "source": "dev_log",
                "author": dl["log_username"] or dl["created_username"] or "",
                "authorDisplay": dl["log_display"] or dl["log_username"]
                                 or dl["created_display"] or dl["created_username"] or "未知",
                "content": content,
                "channel": dl["channel"] or "",
                "logDate": dl["log_date"],
                "created_at": norm_at(dl["created_at"]),
                "canDelete": False,
            })
        for al in conn.execute(
            "SELECT id, username, display_name, target_label, at FROM audit_log "
            "WHERE target_type='dev_case' AND target_id=? AND action='dev_case.status'",
            (str(case_id),)
        ).fetchall():
            results.append({
                "id": f"dcs_{al['id']}",
                "source": "dev_case_status",
                "author": al["username"] or "",
                "authorDisplay": al["display_name"] or al["username"] or "未知",
                "content": al["target_label"] or "",
                "created_at": norm_at(al["at"]),
                "canDelete": False,
            })

    conn.close()
    results.sort(key=lambda x: (x.get("created_at") or ""), reverse=True)
    return results


@router.post("/api/quotations/{quote_no}/updates", status_code=201)
def post_case_update(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    content = (body.get("content") or "").strip()
    important = bool(body.get("important"))
    if not content:
        raise HTTPException(400, "內容不得為空")
    conn = get_db()
    qrow = conn.execute(
        "SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not qrow:
        conn.close()
        raise HTTPException(404, "報價單不存在")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    update_type = "important" if important else "comment"
    cur = conn.execute(
        "INSERT INTO case_updates (quote_no, author, content, type, created_at) "
        "VALUES (?,?,?,?,?)",
        (quote_no, user["username"], content, update_type, now),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    dn_row = None
    try:
        c2 = get_db()
        dn_row = c2.execute("SELECT display_name FROM users WHERE username=?",
                            (user["username"],)).fetchone()
        c2.close()
    except Exception:
        pass
    author_display = (dn_row["display_name"] if dn_row else None) or user["username"]
    case_label = quote_no
    if qrow["customer_name"] or qrow["project_name"]:
        case_label = f"{quote_no}（{qrow['customer_name'] or ''}{'／' if qrow['customer_name'] and qrow['project_name'] else ''}{qrow['project_name'] or ''}）"
    notify_module_activity("案件留言板", "新增留言", author_display, case_label,
                            "case-management.html", detail=content)
    if important:
        spawn_bg_thread(push_event_for_important_comment, args=(new_id, quote_no, content, author_display))
    return {
        "id": new_id,
        "source": "comment",
        "author": user["username"],
        "authorDisplay": author_display,
        "content": content,
        "created_at": now,
        "canDelete": True,
        "important": important,
    }


@router.delete("/api/quotations/{quote_no}/updates/{uid}")
def delete_case_update(quote_no: str, uid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT id, author FROM case_updates WHERE id=? AND quote_no=?", (uid, quote_no)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "留言不存在")
    if user["role"] not in ("superadmin", "admin") and user["username"] != row["author"]:
        conn.close()
        raise HTTPException(403, "只能刪除自己的留言")
    conn.execute("DELETE FROM case_updates WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    notify_module_activity("案件留言板", "刪除留言", user.get("display_name") or user["username"],
                            quote_no, "case-management.html")
    return {"ok": True}


@router.get("/api/quotations/{quote_no}/pdf-download")
def download_quotation_pdf(quote_no: str, internal: bool = False, authorization: str = Header(None)):
    """後端 Edge Headless 產生 PDF 並直接下載（internal=true 含成本），避免 macOS/瀏覽器列印頁首干擾。"""
    _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT quote_no FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "報價單不存在")
    try:
        pdf_bytes = generate_pdf_bytes(quote_no, internal=internal)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"PDF 產生失敗：{e}")
    mode_label = "內部版" if internal else "對外版"
    _audit(_tok(authorization), "quotation.export_pdf", "quotation", quote_no,
           f"{quote_no} {mode_label} PDF 下載", {"mode": "internal" if internal else "external", "via": "server"})
    fname = f"{quote_no}_內部.pdf" if internal else f"{quote_no}.pdf"
    encoded = urlquote(fname)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


@router.get("/api/quotations/{quote_no}/closing-report-pdf")
def download_case_closing_report_pdf(quote_no: str, authorization: str = Header(None)):
    """案件結案報表 PDF（含財務數據／支出／收入／收款／執行進度／損益分析），
    僅限已結案案件；含成本與毛利等內部機密資訊，不對外提供。"""
    _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag "
        "FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "報價單不存在")
    if row["deal_tag"] != "已結案":
        raise HTTPException(400, "案件尚未結案，無結案報表可供下載")
    try:
        pdf_bytes = generate_case_closing_pdf_bytes(quote_no)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"結案報表 PDF 產生失敗：{e}")
    _audit(_tok(authorization), "quotation.export_closing_report", "quotation", quote_no,
           f"{quote_no} 結案報表 PDF 下載", {"via": "server"})
    fname = f"{quote_no}_結案報表.pdf"
    encoded = urlquote(fname)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


@router.get("/api/quotations/{quote_no}/project-report-pdf")
def download_project_execution_report_pdf(quote_no: str, authorization: str = Header(None)):
    """專案執行報告 PDF（執行進度／叫料管控／代辦事項／工作日誌／動態彙整，
    2026-08-26 專案管理併入案件管理），任何案件狀態下皆可下載，不像結案報表
    限已結案案件。"""
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "報價單不存在")
    try:
        pdf_bytes = generate_project_execution_report_pdf_bytes(quote_no)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"專案執行報告 PDF 產生失敗：{e}")
    _audit(_tok(authorization), "quotation.export_project_report", "quotation", quote_no,
           f"{quote_no} 專案執行報告 PDF 下載", {"via": "server"})
    fname = f"{quote_no}_專案執行報告.pdf"
    encoded = urlquote(fname)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )
