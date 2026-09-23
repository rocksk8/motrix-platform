"""Quotation CRUD, approval workflow, deal-tag, export endpoints."""
import json
import logging
import math
import re
import os
import shutil
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote as urlquote

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Form, HTTPException, Header, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field

from db import get_db, spawn_bg_thread
from helpers import (
    _require_user, _tok, _audit, _notify, _purge_notifications, _check_quotation_owner,
    quote_hot_fields, save_quotation_json, _steps_to_tiers, SQL_DEAL_TAG, SQL_SETTLE_STATUS,
    notify_approval_request, notify_next_tier, notify_approved,
    notify_returned, notify_resubmit_requester, notify_settlement_finalized,
    notify_module_activity, push_event_for_quotation_won, push_event_for_important_comment,
    push_event_for_case_stage_due, push_event_delete_for_case_stage,
    push_event_for_case_stage_done,
    sync_daily_task_for_case_stage, delete_daily_task_for_case_stage,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    resolve_tier_approvers, UnresolvedManagerError, resolve_active_flow_setting,
    submitter_manager_tiers, cascade_self_tiers, notify_org_chain_notice,
    save_document_files, delete_document_file,
    notify_case_close_blocked, notify_case_change_requested,
    norm_at, active_delegators_for, user_has_module, can_see_financial,
    validate_invoice_no,
    summarize_payment_items,
)
from helpers.company_identity import snapshot_for, SNAPSHOT_KEY
import helpers.uploads as _uploads_mod
from helpers.uploads import _effective_subfolder
from helpers.errors import trace_id
from archive import _backup_quotation
from pdf_gen import (
    _generate_quotation_pdf, generate_pdf_bytes, _get_pdf_base,
    _generate_case_closing_pdf, generate_case_closing_pdf_bytes,
    generate_project_execution_report_pdf_bytes,
)

router = APIRouter()


# ── Approval tier helpers ─────────────────────────────────────────────────────

import re as _re

# ── 編輯紀錄（2026-09-14 使用者要求：「如果有編修，需保留原始單據跟編輯紀錄
#    在系統」）────────────────────────────────────────────────────────────────
#
# 現況的落差：`editHistory` 原本只有兩個地方會寫——①解鎖編輯（superadmin 改
# 已送出／已結案的單）②精算存檔。**一般編輯完全沒有紀錄**：草稿階段改了幾次、
# 誰改的、改了什麼，系統裡查不到任何東西。而且既有的兩處也只記 who/when/type，
# 不記「改了什麼」，事後只知道「這張單被改過 7 次」。
#
# 這裡補上①一般編輯也寫紀錄②紀錄帶欄位層級的變更摘要。
# 沿用 data_json 裡的 editHistory 陣列（既有慣例），不開新表——這份紀錄永遠
# 隨著單據一起讀、一起備份，沒有跨單查詢的需求。

# (JSON 路徑, 顯示名稱)；路徑用 "." 分隔，支援巢狀
_TRACKED_QUOTE_FIELDS = [
    ("customerName",      "客戶名稱"),
    ("projectName",       "專案名稱"),
    ("quoteDate",         "報價日期"),
    ("validDays",         "有效天數"),
    ("salesPerson",       "業務"),
    ("tot.total",         "含稅總額"),
    ("tot.pretax",        "未稅金額"),
    ("tot.directMarginPct", "直接毛利率"),
    ("tot.netMarginPct",  "淨利率"),
    ("notes",             "備註"),
    ("contract.deliveryAddress", "交貨地址"),
    ("contract.deliveryTerms",   "交貨條件"),
    ("contract.contactPerson",   "聯絡人"),
    ("contract.contactPhone",    "聯絡電話"),
    ("caseRecord.roles.sales",    "案件業務負責"),
    ("caseRecord.roles.executor", "案件執行負責"),
]

# 比對整包內容時要忽略的鍵：它們本身就是「紀錄」或每次存檔都會變動的欄位，
# 拿來比對會讓每一次存檔都被判定成「有變更」。
_DIFF_IGNORE_KEYS = {"editHistory", "docVersions", "approval", "updatedAt", "_expectedUpdatedAt"}


def _dig(data, path: str):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _fmt_change_value(v) -> str:
    """把值壓成一行可讀的字串。長內容截斷——這份紀錄是給人看「改了哪裡」的
    索引，不是完整快照（完整快照是同一批做的 PDF 版本存檔）。"""
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return f"（{len(v)} 項）" if isinstance(v, list) else "（內容）"
    text = str(v)
    return text if len(text) <= 60 else text[:57] + "…"


def _summarize_quote_changes(old: dict, new: dict) -> list:
    """回傳 [{field, from, to}]；沒有任何可辨識的變更時回傳 []。

    追蹤清單外的欄位變動不會被逐一列出（那會變成把整份 data_json 抄進紀錄裡），
    但**也不會被靜默忽略**：整包比對後若確實有差異，補一筆「其他內容」，
    至少查得到「這個時間點有人動過這張單」。
    """
    changes = []
    for path, label in _TRACKED_QUOTE_FIELDS:
        o, n = _dig(old, path), _dig(new, path)
        if o == n:
            continue
        changes.append({"field": label,
                        "from": _fmt_change_value(o),
                        "to":   _fmt_change_value(n)})

    o_items = old.get("items") if isinstance(old.get("items"), list) else []
    n_items = new.get("items") if isinstance(new.get("items"), list) else []
    if o_items != n_items:
        changes.append({"field": "報價項目",
                        "from": f"{len(o_items)} 項",
                        "to":   f"{len(n_items)} 項"})

    if not changes:
        stripped_old = {k: v for k, v in old.items() if k not in _DIFF_IGNORE_KEYS}
        stripped_new = {k: v for k, v in new.items() if k not in _DIFF_IGNORE_KEYS}
        if stripped_old != stripped_new:
            changes.append({"field": "其他內容", "from": "", "to": ""})
    return changes


def _append_edit_history(q: dict, user: dict, now: str, entry_type: str,
                         changes: list = None) -> int:
    """追加一筆編輯紀錄，回傳 rev。就地改 q（呼叫端負責存檔）。"""
    history = q.get("editHistory")
    if not isinstance(history, list):
        history = []
    rev = len(history) + 1
    entry = {
        "rev":       rev,
        "at":        now,
        "by":        user["username"],
        "byDisplay": user.get("display_name") or user["username"],
        "type":      entry_type,
    }
    if changes:
        entry["changes"] = changes
    history.append(entry)
    q["editHistory"] = history
    return rev


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
    approvers:[] 的空層卡死流程（任何人都無法通過該層）。

    ⚠️ 2026-09-15：內建那一層改成展開申請人的**組織鏈**（部門主管 →（本人身兼
    部門主管時再加）處主管），跟共用版 submitter_manager_tiers() 同一支實作。"""
    tiers = list(setting.get("tiers") or [])
    if not tiers:
        tiers = _steps_to_tiers(setting.get("steps") or [])
    result = []
    if setting.get("includeSubmitterManagerTier", True):
        for approvers in submitter_manager_tiers(conn, requester_username):
            result.append({"order": len(result), "approvers": approvers})
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


# `_check_quotation_owner()` 於 2026-09-10 抽到 helpers/quotations.py（見該處
# docstring）——叫料 API 是第三個呼叫點，且新增時漏了這道檢查。本檔案改為
# 從 helpers 引用，行為完全不變。


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


def _require_financial_view(user: dict) -> None:
    """案件財務金額的檢視權（2026-09-13 使用者裁示：viewer／engineer 不該看到）。

    規則與前端 `case-management.js::canSeeFinancial()` 逐字相同，見
    `helpers/auth.py::can_see_financial()`——這裡不自己寫判斷式，避免兩邊漂移。
    """
    if not can_see_financial(user):
        raise HTTPException(403, "此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）")


def _safe_close(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _is_case_approver(data_json: str, user: dict, conn) -> bool:
    """這個人是否出現在這張單的簽核名單裡（任何一層）或本人就是送審申請人。

    含「目前有效的簽核代理人」——代理人在簽核路徑上處處被視同本人
    （`check_approve_permission()` 等），檢視權限沒有理由是例外。
    """
    try:
        appr = (json.loads(data_json or "{}") or {}).get("approval") or {}
    except Exception:
        return False
    names = {a["username"] for tier in (_active_tiers(appr) or [])
             for a in (tier.get("approvers") or []) if a.get("username")}
    if appr.get("requestedBy"):
        names.add(appr["requestedBy"])
    if user["username"] in names:
        return True
    try:
        return bool(set(active_delegators_for(conn, user["username"])) & names)
    except Exception:
        return False


def _guard_case(conn, quote_no: str, user: dict, *, allow_approver: bool = False,
                allow_module: str = None, skip_if_semi_unlocked: bool = False):
    """取單＋擁有者檢查，給所有「用 quote_no 直接操作單一案件」的端點共用。

    2026-09-13（模組權限稽核第二輪）：`quote_no` 是可列舉的（`MQ-YYYYMM-NNN`），
    沒有這道檢查就是 IDOR——2026-08-24 修過報價單本體、2026-09-10 修過叫料、
    2026-09-11 額外支出上線時就內建，但**案件階段／拜訪紀錄／更新紀錄／案件
    鎖定／附件上傳刪除／匯出紀錄／三支 PDF 一直沒有**，任何已登入帳號都能讀寫
    別人的案件。這支把那批補齊，規則與既有端點完全一致（admin+ 直通，否則必須
    是該案業務或 `assigned_user_ids` 裡的協作者）。

    `allow_approver=True`：簽核路徑上的人（含代理人）也放行。給報價單 PDF 下載用
    ——簽核人要看得到單據才簽得下去，而他通常既不是業務也不在協作者名單裡。

    `allow_module="case_manage"`：**案件執行面**（階段、拜訪紀錄、動態更新、叫料
    附件、案件鎖定、匯出紀錄、兩支案件報表 PDF）額外放行具該模組的人。

    ⚠️ **為什麼執行面不用純擁有者規則**——2026-09-13 實測開發機資料庫：26 張報價單
    裡 `assigned_user_ids` 有值的是 **0 張**，也就是「指派協作者」這個機制實務上
    從來沒被使用過。純擁有者規則下，`engineer` 角色（永遠不會是 sales_person）
    對**全部 26 張案件的存取權都是 0**——現場工程師會完全無法開啟任何案件的執行
    進度與拜訪紀錄。金額面（精算、應收應付、發票檔案）維持純擁有者規則不放寬。
    等哪天「指派協作者」真的被落實，就可以把這條 `case_manage` 放行拿掉，回到
    純擁有者規則；那一天之前，拿掉等於停掉工程師的案件管理。
    """
    q = conn.execute(
        "SELECT sales_person_id, sales_person, assigned_user_ids, data_json, "
        "deal_tag, case_semi_unlocked FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not q:
        # 擋下來時由這裡負責關連線：呼叫端清一色是「conn = get_db() → 一連串操作
        # → conn.close()」的直線寫法，沒有 try/finally，守門若直接往外丟例外，
        # 那條連線要等 GC 才會被回收。集中在這裡處理，28 個呼叫端就不必各自包一層。
        _safe_close(conn)
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    # 2026-09-13（使用者裁示）：**已結案且半解鎖**的案件上，誰都可以改動——因為
    # 半解鎖期間的每一筆變更/上傳都會排進待審核、由 superadmin 決定要不要套用
    # （`_gate_case_edit()`／`_check_case_gate()`）。把關在審核，不在入口。
    # 只有這個狀態例外：未結案的案件沒有那道審核，維持擁有者規則。
    if (skip_if_semi_unlocked and (q["deal_tag"] or "") == "已結案"
            and q["case_semi_unlocked"]):
        return q
    try:
        _check_quotation_owner(q, user)
    except HTTPException:
        allowed = (
            (allow_module and user_has_module(user, allow_module))
            or (allow_approver and _is_case_approver(q["data_json"], user, conn))
        )
        if not allowed:
            _safe_close(conn)
            raise
    return q


def _deny_if_case_locked_unsupported(conn, quote_no: str, authorization: str = None,
                                     op: str = "") -> None:
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
    要不要擴大範圍。

    2026-09-11：補上 `op` 操作標籤。先前只記單號，查得出「這道牆被撞了幾次」，
    查不出「該優先開放哪幾支」——而後者才是當初要收集數據來決定的事。13 個
    呼叫點各自傳入自己的標籤（例如「案件階段-新增」「稅額沖銷-核准」），
    detail 格式為 `{單號} 已結案，此操作不支援排隊審核，直接擋下｜操作：{標籤}`。
    前綴保持不變，舊紀錄仍可一起統計，只是沒有標籤那一段。"""
    row = conn.execute("SELECT deal_tag FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    if (row["deal_tag"] or "") == "已結案":
        if authorization:
            # 前綴刻意保持原樣，讓 2026-08-28 起累積的舊紀錄仍可一起統計；
            # 操作標籤接在後面，用「｜操作：」分隔，之後要分組只要 split 一次
            detail = f"{quote_no} 已結案，此操作不支援排隊審核，直接擋下"
            if op:
                detail += f"｜操作：{op}"
            _audit(_tok(authorization), "case.locked_edit_denied", "quotation", quote_no, detail)
        raise HTTPException(
            403,
            "案件已結案並鎖定，此操作不支援於已結案案件（如需修正請透過案件資料整體編輯，"
            "或聯繫最高管理員）",
        )


def _exclude_requester(tiers: list, requester: str) -> list:
    """Drop the requester from tier approver lists — a submitter must never end up
    required to approve their own quotation. Tiers left with no approvers after
    removal are dropped entirely so the flow skips straight past them.

    ⚠️ 2026-09-15 例外：標了 `selfApproval` 的項目**不剔除**。那是組織流程算出來
    「這一關本來就歸他管」的層（他自己是部門/處主管，見 tiered_approval.py::
    resolve_submitter_org_chain()），使用者裁示這種情況要由本人具名簽核、最高
    管理者只做知會。這裡剔除掉的話那一層會整層消失，等於關卡無聲蒸發。
    手動挑人挑到申請人本人的層仍然照舊剔除。"""
    if not requester:
        return tiers
    result = []
    for t in tiers:
        approvers = [a for a in (t.get("approvers") or [])
                     if a.get("username") != requester or a.get("selfApproval")]
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

        # 知會（2026-09-15）：整條簽核鏈都只有申請人本人時（他已是組織職權頂端，
        # 例如處主管解鎖改版自己的報價單），最高管理者不再被塞進簽核鏈當簽核人，
        # 改成收一則知會通知——他仍可隨時以 superadmin 身分退回。
        if tiers and requester:
            _nconn = get_db()
            try:
                notify_org_chain_notice(
                    _nconn, tiers, requester, quote_no, quote_no,
                    f"報價單 {quote_no}{label}（{cname}）由 "
                    f"{appr.get('requestedByDisplay') or requester} 依組織職權自行簽核，知會您")
            finally:
                _nconn.close()

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
    # 這張單屬於哪一個據點（2026-09-22 §9 QL4）。
    # ⚠️ 沒送 ⇒ 落在**主要據點**；送了 ⇒ 用送的那個。
    # ☠️ 只做前半的話（寫死主要據點、不看送進來的值），
    # **分公司就永遠開不出自己的單** —— 而那正是使用者要這個功能的原因。
    # 📌 兩種鍵名都收：前端送 `locationId`，而 DB 欄位叫 `location_id`。
    location_id: Optional[str] = Field(None, alias="locationId")

    model_config = {"populate_by_name": True}


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
    # 同一個人連續當好幾層簽核人時，前端跳確認視窗問過之後帶 cascade=true，
    # 後端一次把那幾層一起簽掉（2026-09-15，見 helpers/tiered_approval.py::
    # plan_self_cascade()）。預設 false：沒問過就不會替使用者多簽。
    cascade:           Optional[bool] = False


# ── Quotation sequence ────────────────────────────────────────────────────────

# 正式單號格式：MQ-YYYYMM-NNN（月份 6 碼、序號 3 碼）。用來擋掉 client 送來的
# 佔位字串／半成品號碼，見 create_quotation()。
_QUOTE_NO_RE = re.compile(r"^MQ-\d{6}-\d{3}$")


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


@router.get("/api/quotations/last-received-bank-account")
def get_last_received_bank_account(customerName: Optional[str] = None, authorization: str = Header(None)):
    """查這個客戶上一次「標記已收款」用的銀行帳戶，供出納分頁標記收款 Modal
    開啟時預帶值。見 accounting_export.py 檔頭「標記已付款/已收款時的銀行帳戶
    預設值」說明。⚠️ 必須在 GET /api/quotations/{quote_no} 之前註冊，否則
    "last-received-bank-account" 會被當成 quote_no 吃掉。

    案件沒有正規化的客戶 id（customerId 只在報價單建立時從客戶下拉挑選才會
    有值，很多舊案件是純打字輸入客戶名稱），這裡直接用 quotations 熱路徑欄位
    customer_name 比對——跟其他所有「依客戶彙總」的既有邏輯（如 §7 帳齡分析／
    客戶歷史）用的是同一個欄位，口徑一致。全表掃描 data_json 找收款品項，比照
    reports.py::_collect_tax_invoices() 同一套既有做法，這個資料量級可接受。"""
    _require_user(authorization)
    if not customerName:
        return {"name": "", "acctCode": ""}
    conn = get_db()
    rows = conn.execute(
        "SELECT data_json FROM quotations WHERE customer_name=?", (customerName,)
    ).fetchall()
    conn.close()
    best_at, best_name, best_code = "", "", ""
    for row in rows:
        try:
            data = json.loads(row["data_json"] or "{}")
        except Exception:
            continue
        items = ((data.get("caseRecord") or {}).get("payment") or {}).get("items") or []
        for it in items:
            code = it.get("bankAccountCode") or ""
            if not (it.get("received") and code):
                continue
            at = it.get("receivedAt") or ""
            if at > best_at:
                best_at, best_name, best_code = at, it.get("bankAccountName") or "", code
    return {"name": best_name, "acctCode": best_code}


# ⚠️ 這支必須定義在 @router.get("/api/quotations/{quote_no}") **之前**——
# FastAPI 依定義順序比對，排在後面的話 GET /api/quotations/gate-matrix 會先
# 命中 {quote_no} 這條、被當成一個叫 gate-matrix 的單號而回 404（看起來就像
# 端點沒生效）。上面的 stage-board / last-received-bank-account 也是同樣理由
# 排在這裡。
@router.get("/api/quotations/gate-matrix")
def gate_matrix(authorization: str = Header(None)):
    """已成案／已結案案件的「完結案五關卡」一次攤平回傳，供案件管理的關卡矩陣使用
    （案件管理視覺化改版，2026-09-14，見 docs/module-viz-mockup.html §02）。

    五個關卡的判定**完全來自 _case_close_gates()**，跟 update_deal_tag() 擋下完結案
    用的是同一份程式碼——矩陣說「5/5 可結案」就等於「現在按下去不會被 400 擋掉」。
    這件事是這支端點存在的唯一理由：那五個條件散在五個頁籤裡，跨案件比較等於開五次。

    順便帶上階段到期資訊（逾期數／下一個到期日），這樣矩陣右側那兩欄不必再打一次
    /api/quotations/stage-board。權限篩選比照該端點，沿用 _visible_case_filter_sql()。

    唯讀，不觸發任何通知。**效能**：每件案件約 15 次 SQLite 查詢（六張單據表各兩次
    ＋階段＋額外支出兩次），開發機 26 件實測整支約 40ms；本機 SQLite 讀取是微秒級，
    真正會痛的是前端把 500 筆整包拉回去篩（見 QUICK.md §12 第八輪的檢索骨架那段），
    不是這裡。案件量長到數百件以上時再考慮改成 GROUP BY 批次預取。
    """
    user = _require_user(authorization)
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    sql = (
        f"SELECT quote_no, customer_name, project_name, sales_person, total, "
        f"data_json, {SQL_DEAL_TAG} as deal_tag "
        f"FROM quotations WHERE {SQL_DEAL_TAG} IN ('已成案', '已結案')"
    )
    params: list = []
    if user["role"] not in ("superadmin", "admin"):
        frag, fparams = _visible_case_filter_sql(user)
        sql += frag
        params.extend(fparams)
    sql += " ORDER BY quote_no DESC"
    rows = conn.execute(sql, params).fetchall()

    items = []
    for r in rows:
        try:
            d = json.loads(r["data_json"] or "{}")
        except Exception:
            d = {}
        gates = _case_close_gates(conn, r["quote_no"], d)
        blocked = [g for g in gates if g["state"] == "blocked"]

        # 階段到期：逾期數與下一個未完成階段的到期日。用同一次查詢取回，
        # 呼叫端就不必為了右邊兩欄再打一次 stage-board。
        st = conn.execute(
            "SELECT "
            "  SUM(CASE WHEN done=0 AND due_date != '' AND due_date < ? THEN 1 ELSE 0 END) overdue, "
            "  MIN(CASE WHEN done=0 AND due_date != '' THEN due_date END) next_due "
            "FROM case_stages WHERE quote_no=?",
            (today, r["quote_no"])
        ).fetchone()
        next_due = st["next_due"] or None
        next_label = None
        if next_due:
            nxt = conn.execute(
                "SELECT label FROM case_stages WHERE quote_no=? AND done=0 AND due_date=? "
                "ORDER BY sort_order LIMIT 1", (r["quote_no"], next_due)
            ).fetchone()
            next_label = (nxt["label"] if nxt else "") or ""

        items.append({
            "quoteNo":      r["quote_no"],
            "customerName": r["customer_name"] or "",
            "projectName":  r["project_name"] or "",
            "salesPerson":  r["sales_person"] or "",
            "total":        r["total"] or 0,
            "dealTag":      r["deal_tag"] or "",
            "gates":        gates,
            # readyCount 刻意只數 ok，不把 na 算進去：na 是「這件案子沒有這一關」，
            # 併進去會讓一件什麼都沒建的空案件顯示成 5/5，那是最危險的誤導。
            # canClose 才是「按下去不會被擋」的那個判斷（＝沒有任何 blocked）。
            "readyCount":   sum(1 for g in gates if g["state"] == "ok"),
            "naCount":      sum(1 for g in gates if g["state"] == "na"),
            "blockedCount": len(blocked),
            "canClose":     not blocked,
            "blockedLabels": [g["label"] for g in blocked],
            "stageOverdue": st["overdue"] or 0,
            "nextDue":      next_due,
            "nextDueLabel": next_label,
        })
    conn.close()
    return {"items": items, "today": today}


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
    # QL13：前端用 `locationId`，DB 欄位叫 `location_id`。
    # 兩個都回：舊的呼叫端不會因此壞掉，而新的表單讀得到它。
    result["locationId"] = result.get("location_id") or ""
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
    _guard_case(conn, quote_no, user, allow_module="case_manage")
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
    _guard_case(conn, quote_no, user)
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
    _guard_case(conn, quote_no, user)
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
    # 2026-09-10 稽核發現：本檔 45 支寫入端點裡，只有這一支沒有 _require_user()，
    # 而且「誰建立的」是讀 body.created_by（client 送什麼就存什麼／通知什麼），
    # 跟 customers.py／shipping_notes.py 一律從 session 取的慣例不一致。
    # middleware 已保證有有效 session，所以缺的不是登入檢查而是「拿到真正的身分」
    # ——沒有它，建立者與活動通知的操作者都可以被任意冒名。
    # body.created_by 欄位保留不刪（前端仍會送），但一律以 session 為準。
    user = _require_user(authorization)
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
    # 2026-09-10：client 送來的單號一律要通過格式驗證才採用，否則視同沒送、由後端派號。
    # 前端曾經在取不到號時送出佔位字串（`copyToNew()` 的 `MQ-YYYYMM-???`、舊版
    # `saveDraft()` 的寫死 001），`MQ-202609-???` 這種字串不會跟任何既有單號衝突，
    # 所以 INSERT 會成功，接著下面解析序號的 int() 就炸成未捕捉的 ValueError → 500，
    # 使用者只看到「儲存失敗」，複製的內容也救不回來（模板在頁面載入時就清掉了）。
    # 前端那兩處已分別修掉，但「後端才是單號的權威」這件事要在這裡守住——
    # 不管哪個 client、哪個版本送什麼過來，格式不對就由後端自己派。
    _client_no = (body.quote_no or q.get("quoteNo") or "").strip()
    if _client_no and not _QUOTE_NO_RE.match(_client_no):
        logger.warning("create_quotation 收到格式不合的單號 %r，改由後端派號", _client_no)
        _client_no = ""
    qno = _client_no or _peek_next_no(conn, month)

    # `QL25`（依據使用者 2026-09-23 裁示）入口①：直接建立即送審（沒有草稿
    # 步驟），離開草稿那一刻＝這裡。草稿階段仍跟著設定走，只有真的要
    # 送審才凍結——`body.status` 停在「草稿」的路不寫快照。判準用
    # `!= "草稿"`（不是只認字面「待審核」）：同入口②③的理由，這支也
    # 收得到 client 直接送非「待審核」的非草稿狀態。
    if body.status != "草稿":
        q[SNAPSHOT_KEY] = snapshot_for((body.location_id or "").strip())

    def _do_insert(no: str):
        q["quoteNo"] = no
        conn.execute("""
            INSERT INTO quotations
              (quote_no, status, customer_name, project_name,
               total, pretax, direct_margin_pct, net_margin_pct,
               sales_person, sales_person_id, quote_date, valid_days, data_json,
               created_at, updated_at, created_by, deal_tag, settle_status,
               location_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            no, body.status,
            q.get("customerName"), q.get("projectName"),
            tot.get("total", 0), tot.get("pretax", 0),
            tot.get("directMarginPct", 0), tot.get("netMarginPct", 0),
            q.get("salesPerson"), sp_id, q.get("quoteDate"), q.get("validDays", 30),
            json.dumps(q, ensure_ascii=False),
            now, now, user["username"], deal_tag, settle_status,
            # 沒送 ⇒ 留空，由 DB 的 trigger 補成當下的主要據點。
            # 🔑 **不在這裡查一次主要據點**：那會變成「兩個地方各自決定
            # 什麼是預設」，而 trigger 那一份管得到所有寫入路徑。
            (body.location_id or "").strip() or None,
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

    # Reserve in quote_seq so future peeks don't repeat this number.
    # 這裡的 qno 已經過 _QUOTE_NO_RE 驗證（或由 _peek_next_no 產生），序號一定是
    # 三位數字；仍用 try 兜底，因為「解析單號」不值得讓整支建立端點掛掉。
    try:
        seq_no = int(qno.split("-")[-1]) if qno.count("-") == 2 else 0
    except ValueError:
        logger.warning("create_quotation 無法從 %r 解析序號，略過 quote_seq 更新", qno)
        seq_no = 0
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
        except Exception as e:
            # 2026-09-10：這裡原本只捕捉 UnresolvedManagerError 轉成 400 就直接拋，
            # 但上面的 INSERT 早就 commit 了——使用者看到「送出審核失敗」，資料庫卻
            # 留下一張 status='待審核'、完全沒有簽核層級的孤兒單：它會出現在清單裡、
            # 永遠簽不掉，而使用者以為沒建成、再按一次就又多一張（單號還會往後跳）。
            # 已用可控實驗重現（申請人未歸屬部門時送審）。
            #
            # 建不出簽核流程就不該留下這張單：補償性刪除剛剛建立的那筆再往外拋。
            # 刪除範圍嚴格限定在本次請求剛 INSERT 的 qno，不會動到任何既有資料。
            try:
                _cleanup = get_db()
                _cleanup.execute("DELETE FROM quotations WHERE quote_no=?", (qno,))
                _cleanup.execute("DELETE FROM case_stages WHERE quote_no=?", (qno,))
                # 序號也要跟著收回，否則送審失敗幾次之後，第一張成功的單會變成
                # MQ-YYYYMM-003 之類的，使用者會問「001、002 跑去哪了」。
                # 不是單純把 seq 減一（併發下會踩到別人剛拿的號），而是依**實際還
                # 留在資料庫裡的報價單**重算——自我修復，而且最壞情況只是跟同時
                # 進行中的另一筆撞號，那條路徑本來就有 IntegrityError 重試。
                _cleanup.execute(
                    "UPDATE quote_seq SET seq = ("
                    "  SELECT COALESCE(MAX(CAST(SUBSTR(quote_no, 11, 3) AS INTEGER)), 0)"
                    "  FROM quotations WHERE quote_no GLOB ? AND LENGTH(quote_no) = 13"
                    ") WHERE month = ?",
                    (f"MQ-{month}-???", month)
                )
                _cleanup.commit()
                _cleanup.close()
                logger.warning("create_quotation 送審失敗，已回收剛建立的 %s：%s", qno, e)
            except Exception:
                # 連回收都失敗才是真的留下孤兒，這種情況要看得到
                logger.exception("create_quotation 送審失敗且回收 %s 也失敗", qno)
            # `EM3` 已知例外（04749f0）：外層 `except Exception as e` 讓 AST
            # 掃描把這行歸進「要改成 trace_id」的 18 處之一，但實際執行到
            # 這裡時，上面的 `isinstance` 已經把 e 鎖定成 UnresolvedManagerError
            # ——str(e) 拿到的保證是我們自己寫的訊息（同 B 組那 17 處），不是
            # 未過濾的例外內容。包成 opaque 代碼只會讓一個使用者讀得懂、可
            # 行動的錯誤（例如「找不到 X 的主管」）變得看不懂，沒有降低任何
            # 洩漏風險，所以刻意不改。EM3 的驗收清單已把這一行登記為具名例外。
            if isinstance(e, UnresolvedManagerError):
                raise HTTPException(400, str(e))
            raise
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
    # 建立當下自動備存一份 PDF（2026-09-14 使用者要求：「產生當下自動備存一個」）。
    # 原本只有簽核／已簽核／結案／解鎖編輯四個事件會存 PDF，**建立當下沒有**——
    # 也就是「原始單據」這一份從來沒被留下來過，之後任何一次修改都無從比對。
    # 檔名帶到秒、且 _record_doc_version() 會把它記進 data_json.docVersions[]，
    # 所以這一份存下去之後不會被任何後續版本覆蓋。
    spawn_bg_thread(_generate_quotation_pdf,
                    args=(qno, user.get("display_name") or user["username"], '建立'))
    _audit(_tok(authorization), 'quotation.create', 'quotation', qno, f"{qno}（{q.get('customerName','')}）")
    notify_module_activity("報價單", "建立", user.get("display_name") or user["username"],
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
        # data_json 是 2026-09-14 加進來的：一般編輯要寫「改了什麼」的變更摘要，
        # 需要拿得到存檔前的內容（見 _summarize_quote_changes()）。
        # location_id：`QL25` 算「離開草稿」的有效據點要用（見下方 COALESCE
        # 同一條規則：沒送 locationId 就沿用既有欄位值）。
        "SELECT id, status, deal_tag, settle_status, updated_at, sales_person_id, "
        "sales_person, data_json, location_id "
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

    # 一般編輯的編輯紀錄（2026-09-14）——解鎖編輯那條路徑上面已經記過了，
    # 這裡只補「不是解鎖編輯」的一般存檔。
    # **沒有任何可辨識變更時不寫**：這支端點同時被自動存檔（autoSave）與手動
    # 存檔呼叫，每次 autoSave 都寫一筆會讓紀錄被無意義的條目淹沒，反而查不到
    # 真正的修改。_summarize_quote_changes() 找不到追蹤欄位的差異時還會做一次
    # 整包比對，所以「有改但改到追蹤清單外的欄位」仍然會留下一筆「其他內容」，
    # 不會被靜默略過。
    if not is_unlock_edit:
        try:
            _old_data = json.loads(existing["data_json"] or "{}")
        except (ValueError, TypeError):
            _old_data = {}
        _changes = _summarize_quote_changes(_old_data, q)
        if _changes:
            _append_edit_history(q, user, now, "quote_update", _changes)

    # `QL25`（依據使用者 2026-09-23 裁示）入口②：PUT 送審（含解鎖編輯強制
    # 重簽）。判準是**離開草稿這個轉換**（同入口③的理由：client 端理論上
    # 送得出非「待審核」的 new_status，不能只認字面值），不是「只寫一次」：
    # 解鎖重簽再次進到這裡一樣會覆蓋，用的是當下的據點設定。有效據點的
    # 解法同下方 UPDATE 的 `COALESCE(?, location_id)`：沒送 `locationId`
    # 就沿用既有欄位值，不可以在快照這裡退回主要據點——那會與實際存進
    # `location_id` 欄位的值不一致。
    if existing["status"] == "草稿" and new_status != "草稿":
        _eff_location_id = ((body.location_id or "").strip()
                            or (existing["location_id"] or ""))
        q[SNAPSHOT_KEY] = snapshot_for(_eff_location_id)
    elif new_status == "草稿":
        q.pop(SNAPSHOT_KEY, None)

    conn.execute("""
        UPDATE quotations SET
          status=?, customer_name=?, project_name=?,
          total=?, pretax=?, direct_margin_pct=?, net_margin_pct=?,
          sales_person=?, sales_person_id=?, quote_date=?, valid_days=?,
          data_json=?, updated_at=?, deal_tag=?, settle_status=?,
          location_id=COALESCE(?, location_id)
        WHERE quote_no=?
    """, (
        new_status,
        q.get("customerName"), q.get("projectName"),
        tot.get("total", 0), tot.get("pretax", 0),
        tot.get("directMarginPct", 0), tot.get("netMarginPct", 0),
        q.get("salesPerson"), sp_id, q.get("quoteDate"), q.get("validDays", 30),
        json.dumps(q, ensure_ascii=False), now, deal_tag, settle_status,
        # QL13：沒送 `locationId` 時傳 `None` => `COALESCE` 保持原值。
        # 一個只改了金額的 PUT 不應該把這張單的據點清掉 —— 那會讓它的抬頭
        # 與匯款帳號安靜地退回主要據點，而沒有任何地方會報錯。
        (body.location_id or "").strip() or None,
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
        "SELECT customer_name, status, data_json, location_id "
        "FROM quotations WHERE quote_no=?", (quote_no,)
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
    # `QL25`（依據使用者 2026-09-23 裁示）入口③：superadmin 直接改狀態，
    # 不叫 submit、不經過 save_quotation_json()，是一句獨立的
    # `UPDATE quotations SET status=?`——規格逐字點名這是最容易漏的入口。
    # 🔴 判準是**離開草稿這個轉換**，不是「目的地剛好是待審核」——這支
    # 端點的白名單容許 superadmin 直接從「草稿」跳到「已送出」（繞過分層
    # 簽核），那樣也要凍結，不能因為沒有經過「待審核」就漏掉。
    # ⚠️ 這支的白名單也含「草稿」：superadmin 也可能直接把狀態**改回**
    # 草稿（`_STATUS_PATCH_WHITELIST` 裡就有），那是規格 §4 列的兩條回
    # 草稿路徑（recall／reject）之外**第三條沒有被列出來的路**——同一條
    # 原則（「任何把 status 寫成草稿的地方都要清快照」）套在這裡：離開
    # 草稿覆蓋，回到草稿清掉；待審核／簽核中之間互轉（已經離開過草稿）
    # 不重新凍結，維持離開草稿那一刻凍住的值。
    _leaving_draft = row["status"] == "草稿" and body.status != "草稿"
    _entering_draft = body.status == "草稿"
    if _leaving_draft or _entering_draft:
        try:
            _sd = json.loads(row["data_json"] or "{}")
        except (TypeError, ValueError):
            _sd = {}
        if _leaving_draft:
            _sd[SNAPSHOT_KEY] = snapshot_for(row["location_id"] or "")
        else:
            _sd.pop(SNAPSHOT_KEY, None)
        conn.execute(
            "UPDATE quotations SET status=?, data_json=?, updated_at=? WHERE quote_no=?",
            (body.status, json.dumps(_sd, ensure_ascii=False),
             datetime.now().isoformat(), quote_no))
    else:
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
    # `QL25`（依據使用者 2026-09-23 裁示）：回到草稿要清掉據點快照——
    # 草稿階段仍跟著設定即時走，快照還在的話，收回之後、還沒再送審之前
    # 這段時間會印出舊抬頭（而那與「凍結生效中」長得一樣，沒有人會報修）。
    q.pop(SNAPSHOT_KEY, None)
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


# ── 完結案五關卡（2026-09-14 重構）──────────────────────────────────────
# 原本只有 _case_close_block_reasons() 回傳一串字串，夠用來擋結案，但畫不出
# 「哪一關過了、過到什麼程度」的矩陣（案件管理視覺化改版，見
# docs/module-viz-mockup.html §02）。
#
# **刻意不另外寫一份給矩陣用的判定**：那五個條件是整套系統裡最容易悄悄漂移的
# 東西（③的清單就漏過一次「完工單」，見下方註解），兩份實作遲早會對不上，
# 而且對不上的症狀是「矩陣說可以結案、按下去被 400 擋掉」這種最難查的那種。
# 所以改成：_case_close_gates() 是唯一的判定，_case_close_block_reasons()
# 從它的結果推出 reasons，對既有呼叫端（update_deal_tag）的行為完全不變。
#
# 關卡狀態三種：
#   ok      已達成
#   blocked 未達成 → 會擋下完結案
#   na      不適用（沒有階段／沒有款項／沒有精算資料的舊案件）。
#           **na 不是 blocked**——舊案件不該因為一個後來才有的欄位而永遠結不了案，
#           這是①②④原本就有的語意，矩陣上必須畫成空心灰而不是紅燈。

_CLOSE_DOC_TABLES = [
    ("報價單",         "quotations"),
    ("承攬商匯款申請",  "contractor_payment_vouchers"),
    ("開票申請憑據",    "invoice_vouchers"),
    ("出貨單",         "shipping_notes"),
    ("請款單",         "payment_requests"),
    # 2026-09-13：補上「完工單」——它是 DB v77（2026-09-12）才有的模組，當初這份
    # 清單沒有跟著加，等於完工單還在簽核中也結得了案。
    ("完工單",         "completion_notes"),
]


def _case_close_gates(conn, quote_no: str, d: dict) -> list:
    """完結案前置條件，回傳五個關卡的結構化狀態（順序＝結案檢查順序）。

    每個關卡：{key, label, state, value, ratio, reason, pendingUsernames}
      value  給人看的短字串（「7/9」「3/5 期」「已完結」）
      ratio  0..1，畫進度條用；na 時為 None
      reason state=='blocked' 時的擋下理由，直接就是原本 reasons 的那一句
    """
    gates = []

    # ① 執行管理進度 100%（沒有任何階段視為「無需檢查」，不算未達成）
    row = conn.execute(
        "SELECT COUNT(*) total, SUM(CASE WHEN done=1 THEN 1 ELSE 0 END) done "
        "FROM case_stages WHERE quote_no=?", (quote_no,)
    ).fetchone()
    total = row["total"] or 0
    done = row["done"] or 0
    if total == 0:
        gates.append({"key": "progress", "label": "進度", "state": "na",
                      "value": "無階段", "ratio": None, "reason": None,
                      "pendingUsernames": []})
    else:
        blocked = done < total
        gates.append({
            "key": "progress", "label": "進度",
            "state": "blocked" if blocked else "ok",
            "value": f"{done}/{total}", "ratio": done / total,
            "reason": f"執行管理進度尚未 100%（{done}/{total}）" if blocked else None,
            "pendingUsernames": [],
        })

    # ② 款項明細全部收齊（沒有任何期別視為「無需檢查」）
    items = ((d.get("caseRecord") or {}).get("payment") or {}).get("items") or []
    if not items:
        gates.append({"key": "payment", "label": "收款", "state": "na",
                      "value": "無款項", "ratio": None, "reason": None,
                      "pendingUsernames": []})
    else:
        unpaid = [it for it in items if not it.get("received")]
        recv = len(items) - len(unpaid)
        gates.append({
            "key": "payment", "label": "收款",
            "state": "blocked" if unpaid else "ok",
            "value": f"{recv}/{len(items)} 期", "ratio": recv / len(items),
            "reason": f"款項明細尚有 {len(unpaid)} 期未收齊" if unpaid else None,
            "pendingUsernames": [],
        })

    # ③ 相關單據簽核流程全部完成（五種 tiers 簽核機制皆不可處於待審核/簽核中）
    doc_total = 0
    doc_pending = 0
    doc_reasons = []
    pending_usernames: list = []
    for label, table in _CLOSE_DOC_TABLES:
        try:
            tot = conn.execute(
                f"SELECT COUNT(*) c FROM {table} WHERE quote_no=?", (quote_no,)
            ).fetchone()["c"]
            rows = conn.execute(
                f"SELECT json_extract(data_json,'$.approval') ap FROM {table} "
                f"WHERE quote_no=? AND status IN ('待審核','簽核中')",
                (quote_no,)
            ).fetchall()
        except Exception:
            continue           # 該模組的表還不存在（migration 尚未跑到）
        doc_total += tot
        if rows:
            doc_pending += len(rows)
            doc_reasons.append(f"{label}尚有 {len(rows)} 筆簽核中")
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
    if doc_total == 0:
        gates.append({"key": "documents", "label": "單據", "state": "na",
                      "value": "無單據", "ratio": None, "reason": None,
                      "pendingUsernames": []})
    else:
        signed = doc_total - doc_pending
        gates.append({
            "key": "documents", "label": "單據",
            "state": "blocked" if doc_pending else "ok",
            "value": f"{signed}/{doc_total}", "ratio": signed / doc_total,
            # reason 保留逐表拆開的原句（「出貨單尚有 2 筆簽核中」），
            # 合成一句會讓使用者不知道要去哪個模組找
            "reason": "；".join(doc_reasons) if doc_reasons else None,
            "pendingUsernames": list(dict.fromkeys(pending_usernames)),
        })

    # ④ 成本精算必須已完結（2026-09-13 使用者裁示）。結案之後案件就鎖定了，
    # 精算還停在草稿等於把一張永遠算不完的帳鎖進去。判斷沿用既有熱路徑欄位口徑
    # （data_json.settlement.status），完全沒有精算資料的案件視為「無需檢查」。
    settlement = (d.get("settlement") or {})
    if not settlement:
        gates.append({"key": "settlement", "label": "精算", "state": "na",
                      "value": "未建", "ratio": None, "reason": None,
                      "pendingUsernames": []})
    else:
        finalized = (settlement.get("status") or "") == "finalized"
        gates.append({
            "key": "settlement", "label": "精算",
            "state": "ok" if finalized else "blocked",
            "value": "已完結" if finalized else "草稿",
            "ratio": 1.0 if finalized else 0.5,
            "reason": None if finalized else "成本精算尚未完結",
            "pendingUsernames": [],
        })

    # ⑤ 額外支出不可停在送審中（2026-09-13 一併補上）：那是還沒定案的成本，
    # 結案後才核准會讓已結案案件的成本事後改變。
    try:
        xe_total = conn.execute(
            "SELECT COUNT(*) c FROM case_extra_expenses WHERE quote_no=?", (quote_no,)
        ).fetchone()["c"]
        xe_pending = conn.execute(
            "SELECT COUNT(*) c FROM case_extra_expenses WHERE quote_no=? AND status='待審核'",
            (quote_no,)
        ).fetchone()["c"]
    except Exception:
        xe_total = xe_pending = None    # 舊環境還沒有這張表（DB v75 之前）
    if xe_total is None or xe_total == 0:
        gates.append({"key": "extraExpense", "label": "變更", "state": "na",
                      "value": "無", "ratio": None, "reason": None,
                      "pendingUsernames": []})
    else:
        gates.append({
            "key": "extraExpense", "label": "變更",
            "state": "blocked" if xe_pending else "ok",
            "value": f"{xe_pending} 送審" if xe_pending else "無送審中",
            "ratio": 0.0 if xe_pending else 1.0,
            "reason": f"額外支出尚有 {xe_pending} 筆送審中" if xe_pending else None,
            "pendingUsernames": [],
        })

    return gates


def _case_close_block_reasons(conn, quote_no: str, d: dict):
    """完結案前置條件檢查（2026-08-25 使用者提出，見 QUICK.md §11）。
    回傳 (reasons, pending_usernames)：reasons 非空時應擋下完結案；
    pending_usernames 是③相關單據簽核人（①②④⑤沒有對應的「簽核人」概念，
    維持空清單，通知只會落到最高管理員，見 notify_case_close_blocked() docstring）。

    2026-09-14：判定本體搬到 _case_close_gates()，這裡只做投影。
    ③的 reason 在關卡裡是用「；」把逐表的句子接起來的，這裡拆回獨立項目，
    維持原本「每個模組一句」的 reasons 形狀。

    ⚠️ **唯一的行為差異是 reasons 的排列順序**（內容與 pending_usernames
    逐字相同，已用 git HEAD 的舊實作對開發機 26 件案件全部比對過）：
    舊版是 ①進度 ②收款 ④精算 ⑤額外支出 ③單據——③被擠到最後是當初插入
    ④⑤ 時的副作用，不是刻意的；新版照文件編號排成 ①②③④⑤，跟關卡矩陣的
    欄位順序一致，使用者看到的擋下訊息與矩陣才會是同一個讀法。"""
    gates = _case_close_gates(conn, quote_no, d)
    reasons = []
    pending_usernames: list = []
    for g in gates:
        if g["state"] != "blocked":
            continue
        reasons.extend((g["reason"] or "").split("；"))
        pending_usernames.extend(g["pendingUsernames"])
    return [r for r in reasons if r], list(dict.fromkeys(pending_usernames))


@router.patch("/api/quotations/{quote_no}/deal-tag")
def update_deal_tag(quote_no: str, body: QuotationDealTagUpdate, authorization: str = Header(None)):
    user = _require_user(authorization)
    # 未成案 / 已成案 限管理員以上
    if body.deal_tag in ("未成案", "已成案") and user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可標記「未成案」或「已成案」")
    # 2026-09-13（使用者裁示）：**完結案只有最高管理者能按**。
    # 結案是這套系統裡最不可逆的動作——案件從此鎖定、只能走半解鎖＋逐筆審核才能
    # 再動，還會啟動保固追蹤期。原本 admin 就能按（跟「已成案」同一層），與
    # 「已結案只有 superadmin 能降級」的既有規則不對稱：一般管理員按得下去、
    # 卻沒有人能把它按回來（只有 superadmin 可以）。統一成兩邊都是 superadmin。
    if body.deal_tag == "已結案" and user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理者可完結案件")
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
    """已結案案件解鎖為「半解鎖」狀態（2026-08-26）。解鎖本身立即生效、不需審核；
    半解鎖期間的每一筆變更/上傳才需要 superadmin 審核（見 _gate_case_edit()／
    _check_case_gate()）。只對 deal_tag='已結案' 的案件有意義。

    **權限：任何登入使用者皆可觸發**——2026-08-26 使用者裁示，2026-09-13 模組權限
    稽核時再次確認：「誰都可以改動，但都需要審核」。把關點在審核，不在入口。

    這是這波權限收斂裡**刻意保留的例外**。2026-09-13 曾一度把它一起收成擁有者
    規則（跟其他每案端點一致），複查時發現那推翻了使用者已經裁示過的設計，已還原。
    對應地，半解鎖期間的附件上傳/刪除也用 `_guard_case(..., skip_if_semi_unlocked=True)`
    對這個狀態放行——**未結案**的案件沒有那道審核，仍維持擁有者規則。"""
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
    """將半解鎖案件重新上鎖（2026-08-26），權限比照解鎖——任何登入使用者皆可觸發
    （見 unlock_case() 的說明）。重新上鎖不會影響既有的 pending 待審核記錄（case_change_requests 仍
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

    # 2026-09-02（反派/國稅局視角複查發現）：這支整包存檔端點是案件管理財務
    # Tab 填發票號碼的實際主要路徑（mark_payment() 的 invoiceNo 驗證只涵蓋
    # receivables.html 出納快速登錄那條路，這裡才是大多數人真正在用的地方），
    # 過去完全沒有走到格式/重複驗證，等於前面加的防呆對最常用的入口沒有生效。
    # 用 item id 比對排除自己這筆（見 validate_invoice_no() docstring 說明
    # 為什麼不能用陣列位置）。
    new_items_for_inv = ((body.case_record or {}).get("payment") or {}).get("items") or []
    old_items_for_inv = ((data.get("caseRecord") or {}).get("payment") or {}).get("items") or []
    old_inv_by_id = {it.get("id"): it.get("invoiceNo") for it in old_items_for_inv if it.get("id") is not None}
    for new_it in new_items_for_inv:
        new_inv = new_it.get("invoiceNo")
        if new_it.get("id") is not None and old_inv_by_id.get(new_it.get("id")) == new_inv:
            continue  # 未變動，不必重新驗證
        validate_invoice_no(conn, new_inv, exclude_quote_no=quote_no, exclude_item_id=new_it.get("id"))

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


def _apply_case_change_request(conn, req, approver: dict, authorization: str,
                                deferred_audits: list) -> dict:
    """superadmin 核准後真正套用一筆 case_change_requests。呼叫端負責在成功
    回傳後把該筆記錄標記 approved 並 commit；這裡只處理「套用效果」本身，

    ⚠️ **這裡不可以直接呼叫 `_audit()`／`_notify()`**（2026-09-15 修復）。
    使用者回報「簽核佇列按下簽核後系統卡死十幾秒」，實測是 **32.8 秒**：

        save_quotation_json(conn, ...)   # 只 execute、不 commit → conn 持有寫鎖
        _audit(...)                      # get_db() 另開一條連線寫入 → 撞自己的鎖

    SQLite 同時只允許一個 writer，而 `db.py::_connect()` 是 `connect(timeout=30)`，
    所以第二條連線會等到逾時；更糟的是 `_audit()` 的 `except` 會把逾時例外吞掉，
    **稽核紀錄同時被靜默丟掉**——畫面顯示核准成功，事後卻查不到是誰核准的。

    這跟 2026-09-10 `create_quotation` 踩過的是同一個坑（見該函式註解）。
    改成把要寫的稽核項目 append 進 `deferred_audits`，由呼叫端在 commit 之後
    統一寫出。`_sync_device_stock()` 沿用傳進去的同一條 `conn`，不受影響。

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
        deferred_audits.append(('case.update', 'quotation', quote_no,
                                f"{label}（半解鎖審核通過套用）",
                                {"stockConflicts": stock_conflicts} if stock_conflicts else None))

    elif action_type == "payment_mark":
        idx = payload["idx"]
        body = payload["body"] or {}
        pits = cr.setdefault("payment", {}).setdefault("items", [])
        if idx < 0 or idx >= len(pits):
            raise HTTPException(400, "款項索引超出範圍")
        # 2026-09-24：驗證與套用改走 mark_payment() 同一組函式。修正前排進佇列的
        # 壞資料（已收無日期、金額非數字）在這裡擋下，不落地；收款人記提出申請的人。
        _validate_receipt_body(body)
        _apply_payment_mark(pits, idx, body,
                            req["requested_by_display"] or req["requested_by"] or "")
        if "invoiceNo" in body:
            validate_invoice_no(conn, body["invoiceNo"], exclude_quote_no=quote_no, exclude_idx=idx)
            pits[idx]["invoiceNo"] = body["invoiceNo"]
        if "invoiceDate" in body:
            pits[idx]["invoiceDate"] = body["invoiceDate"]
        save_quotation_json(conn, quote_no, data)
        deferred_audits.append(('payment.mark', 'quotation', quote_no,
                                f"{label}（半解鎖審核通過套用）", None))

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
        deferred_audits.append((f'{action_type}.approved', 'quotation', quote_no,
                                f"{label}（半解鎖審核通過套用，{len(moved)} 個檔案）", None))

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
        deferred_audits.append((f'{action_type}.approved', 'quotation', quote_no,
                                f"{label}（半解鎖審核通過套用）", None))

    else:
        raise HTTPException(500, f"未知的變更類型：{action_type}")

    return result


@router.get("/api/case-changes/{change_id}")
def get_case_change_request(change_id: int, authorization: str = Header(None)):
    """半解鎖期間某一筆待審核變更的完整內容。

    2026-09-13（模組權限稽核，解鎖流程複查）：`change_id` 是**小整數流水號**，比
    `quote_no` 更好猜，而回傳的是 `SELECT *`——payload 裡是那張案件的完整變更內容
    （案件資訊快照、款項金額等）。先前只要求登入，等於把「已結案案件的變更內容」
    開給任何人一個一個試。改成比照案件本身的規則：走 `_guard_case()`，另外放行
    **提出這筆申請的人**（他本來就看得到自己送出的東西）。核准/駁回維持僅
    superadmin，不受影響。
    """
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM case_change_requests WHERE id=?", (change_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到此筆變更申請")
    if (row["requested_by"] or "") != user["username"]:
        _guard_case(conn, row["quote_no"], user, allow_module="case_manage")
    conn.close()
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
    # 稽核延後到 commit 之後才寫（2026-09-15）——見
    # `_apply_case_change_request()` docstring：在這條 conn 還握著寫鎖時
    # 另開連線寫 audit_log，會撞上 SQLite 單一 writer 等滿 30 秒 busy_timeout，
    # 而且例外被 `_audit()` 吞掉，稽核紀錄直接消失。實測 32.8 秒。
    deferred_audits: list = []
    try:
        apply_result = _apply_case_change_request(conn, req, user, authorization,
                                                  deferred_audits)
    except HTTPException:
        conn.close()
        raise
    now = datetime.now().isoformat()
    approver_display = user.get("display_name") or user["username"]
    conn.execute("UPDATE case_change_requests SET status='approved', decided_by=?, decided_at=? WHERE id=?",
                 (approver_display, now, change_id))
    conn.commit()
    conn.close()
    # 到這裡寫鎖已經放掉，`_audit()` 自己那條連線才進得去
    for action, target_type, target_id, target_label, detail in deferred_audits:
        _audit(_tok(authorization), action, target_type, target_id, target_label, detail)
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
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    stage_rows = conn.execute(
        "SELECT * FROM case_stages WHERE quote_no=? ORDER BY sort_order, id",
        (quote_no,),
    ).fetchall()
    stages = [_serialize_stage(conn, sr) for sr in stage_rows]
    conn.close()
    return {"items": stages}


@router.post("/api/quotations/{quote_no}/stages", status_code=201)
def create_case_stage(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """新增階段，對應 case-management.js::addStage()。第二階段 CRUD 端點，2026-08-23
    Phase 3b/4 起已由 case-management.js／quotation-form.html 實際呼叫（見 2026-09-07
    docstring 更正紀錄，本行原誤留 Phase 2 剛新增時「尚未接進」的舊字樣）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-新增")
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
    CRUD 端點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-編輯")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    updates = {}
    if "label" in body:     updates["label"]      = body.get("label") or ""
    if "done" in body:      updates["done"]       = 1 if body.get("done") else 0
    if "doneAt" in body:    updates["done_at"]    = body.get("doneAt") or ""
    if "startDate" in body: updates["start_date"] = body.get("startDate") or ""
    if "dueDate" in body:   updates["due_date"]   = body.get("dueDate") or ""
    was_done = bool(sr["done"])
    if updates:
        updates["updated_at"] = datetime.now().isoformat()
        sql = "UPDATE case_stages SET " + ", ".join(f"{k}=?" for k in updates) + " WHERE id=?"
        conn.execute(sql, list(updates.values()) + [stage_id])
        conn.commit()
        _sync_stages_to_json(conn, quote_no)
        if "due_date" in updates:
            spawn_bg_thread(push_event_for_case_stage_due, args=(stage_id,))
        # 勾選/取消勾選完成 → 兩張行事曆都要同步（2026-09-11 交辦第 3 項）。
        # `done_at` 單獨被改（已勾選的情況下改完成日期）也要重推，否則行事曆上
        # 留的是舊日期。兩支都是 fire-and-forget，失敗只記 log，不擋勾選本身。
        done_changed = ("done" in updates and bool(updates["done"]) != was_done)
        if done_changed or ("done_at" in updates and bool(updates.get("done", was_done))):
            actor_name = user.get("display_name") or user["username"]
            spawn_bg_thread(push_event_for_case_stage_done, args=(stage_id,))
            spawn_bg_thread(sync_daily_task_for_case_stage,
                            args=(stage_id, user["username"], actor_name))
    sr = _get_stage_row(conn, quote_no, stage_id)
    result = _serialize_stage(conn, sr)
    conn.close()
    return result


@router.delete("/api/quotations/{quote_no}/stages/{stage_id}")
def delete_case_stage(quote_no: str, stage_id: int, authorization: str = Header(None)):
    """刪除階段，同時清掉同案件其他階段 dependsOn 裡對它的參照，對應
    case-management.js::removeStage()。第二階段 CRUD 端點，已由前端實際呼叫
    （見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-刪除")
    sr = _get_stage_row(conn, quote_no, stage_id)
    if not sr:
        conn.close(); raise HTTPException(404, "階段不存在")
    calendar_event_id = sr["google_calendar_event_id"] or ""
    # 完成日事件與月曆鏡射也要一起收掉，否則階段刪了行事曆上還留著（DB v76）
    done_event_id = (sr["google_calendar_done_event_id"] or "") if "google_calendar_done_event_id" in sr.keys() else ""
    stage_task_id = (sr["daily_task_id"] or 0) if "daily_task_id" in sr.keys() else 0
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
    if done_event_id:
        spawn_bg_thread(push_event_delete_for_case_stage, args=(done_event_id,))
    if stage_task_id:
        spawn_bg_thread(delete_daily_task_for_case_stage, args=(stage_task_id,))
    return {"ok": True}


@router.patch("/api/quotations/{quote_no}/stages/reorder")
def reorder_case_stages(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """依 orderedIds 陣列順序重寫 sort_order，對應拖曳重排（dragOver/dragEnd）的最終
    結果。第二階段 CRUD 端點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    ordered_ids = body.get("orderedIds") or []
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-排序")
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
    已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    username = body.get("username")
    if not username:
        raise HTTPException(400, "請提供 username")
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-加入負責人")
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
    點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-移除負責人")
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
    第二階段 CRUD 端點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="案件階段-前置階段")
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
    """新增拜訪紀錄，對應 case-management.js::addVisit()。第二階段 CRUD 端點，
    已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="拜訪紀錄-新增")
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
    第二階段 CRUD 端點，已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="拜訪紀錄-編輯")
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
    已由前端實際呼叫（見 create_case_stage() docstring）。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    _deny_if_case_locked_unsupported(conn, quote_no, authorization, op="拜訪紀錄-刪除")
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
    _guard_case(conn, quote_no, user, allow_module="case_manage")
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

def _is_amount(v) -> bool:
    """非負、有限的數字。bool 是 int 的子類別，要另外排除。"""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v >= 0)


def _validate_receipt_body(body: dict) -> None:
    """標記收款的內容驗證（2026-09-24）。只在 received=true 時檢查。

    修正前照收：已收無日期 ⇒ 不屬於任何月份，所有收入報表漏算；
    actualAmount／feeAmount 存進 "" 或 "abc" ⇒ 報表以 `aa - fee` 加總時型別錯誤。

    - receivedAt：必填、合法 YYYY-MM-DD（未來日期不擋）
    - actualAmount：不帶／null＝以應收金額計（既有語意）；其餘必須是非負數字。
      刻意不把 "" 當 null——那會把「清空」變成「以應收計」，屬於金額語意
    - feeAmount：""／null 維持視為 0；其餘必須是非負數字
    """
    if not body.get("received"):
        return
    rat = body.get("receivedAt")
    ok_date = isinstance(rat, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", rat) is not None
    if ok_date:
        try:
            datetime.strptime(rat, "%Y-%m-%d")
        except ValueError:
            ok_date = False
    if not ok_date:
        raise HTTPException(400, "已收款必須填入收款日期（YYYY-MM-DD）")
    aa = body.get("actualAmount")
    if aa is not None and not _is_amount(aa):
        raise HTTPException(400, "實收金額必須是不小於 0 的數字")
    fee = body.get("feeAmount")
    if fee not in (None, "") and not _is_amount(fee):
        raise HTTPException(400, "手續費必須是不小於 0 的數字")


def _apply_payment_mark(pits: list, idx: int, body: dict, received_by: str) -> None:
    """把一次「標記收款／取消收款」套到 pits[idx]。mark_payment() 與半解鎖審核
    通過後的重播共用（原本兩處各寫一份）。呼叫前要先 _validate_receipt_body()。"""
    if "received" not in body:
        return
    is_rcv = bool(body["received"])
    pits[idx]["received"]   = is_rcv
    pits[idx]["receivedAt"] = body.get("receivedAt", "") if is_rcv else ""
    pits[idx]["receivedBy"] = received_by if is_rcv else ""
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
        # 2026-09-24：先驗再送審——不合法的內容不可以先排進審核佇列。
        _validate_receipt_body(body)
        # 收款人一律由伺服器記（不吃 body 傳的值）；半解鎖時一併寫進 payload，
        # 重播端改用 case_change_requests.requested_by_display，兩邊是同一個人。
        received_by = user.get("display_name") or user["username"]
        if "received" in body:
            body["receivedBy"] = received_by
        if "invoiceNo" in body:
            validate_invoice_no(conn, body["invoiceNo"], exclude_quote_no=no, exclude_idx=idx)
        gated, change_id = _gate_case_edit(
            conn, no, user, authorization, "payment_mark",
            f"{no} 第{idx+1}期款項標記（{'收款' if body.get('received') else '取消收款'}）",
            {"idx": idx, "body": dict(body)},
        )
        if gated:
            return {"ok": True, "pending": True, "changeRequestId": change_id,
                    "message": "案件已結案並處於半解鎖狀態，此變更已送出，待最高管理員審核通過後才會套用"}
        _apply_payment_mark(pits, idx, body, received_by)
        if "invoiceNo" in body:
            pits[idx]["invoiceNo"] = body["invoiceNo"]
        if "invoiceDate" in body:
            # 統一發票「開立日期」（2026-09-02 新增，跟 invoiceNo 同一格填寫，選填）
            # ——法定上決定這張發票屬於哪個申報期別的日期，跟 receivedAt（款項實際
            # 入帳日）是兩件事：稅務匯出（reports.py::_collect_tax_invoices()）的
            # 期別篩選改用這個欄位，缺漏才退回 receivedAt；T100 現金基礎傳票
            # （accounting_export.py）刻意仍用 receivedAt 當傳票日期（現金基礎會計
            # 要跟銀行實際入帳日一致，不能改用開立日期，否則傳票日期會跟銀行對帳
            # 單對不上）。直接存 data_json，不需要 migration。
            pits[idx]["invoiceDate"] = body["invoiceDate"]
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
    _guard_case(conn, no, user, allow_module="case_manage", skip_if_semi_unlocked=True)
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
    _guard_case(conn, no, user, allow_module="case_manage", skip_if_semi_unlocked=True)
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
    _guard_case(conn, no, user, allow_module="case_manage", skip_if_semi_unlocked=True)
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
    _guard_case(conn, no, user, allow_module="case_manage", skip_if_semi_unlocked=True)
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
    _guard_case(conn, no, user, allow_module="case_manage", skip_if_semi_unlocked=True)
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
    _guard_case(conn, no, user, allow_module="case_manage", skip_if_semi_unlocked=True)
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
        _deny_if_case_locked_unsupported(conn, no, authorization, op="稅額沖銷-申請")
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
        _deny_if_case_locked_unsupported(conn, no, authorization, op="稅額沖銷-撤銷")
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
        _deny_if_case_locked_unsupported(conn, no, authorization, op="稅額沖銷-核准")
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
    # 2026-09-13（模組權限稽核）：原本只要求登入。`quote_no` 可列舉
    # （MQ-YYYYMM-NNN），等於任何已登入帳號都能讀到**任何**案件的成本、毛利
    # 與精算明細——跟 2026-08-24 修掉的報價單 IDOR 是同一種洞，只是漏在這支。
    # 改用跟同一批資料既有端點一致的擁有者規則（admin+ 直通、否則必須是
    # 該案業務或被指派的協作者），見 helpers/quotations.py::_check_quotation_owner。
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, sales_person_id, sales_person, assigned_user_ids "
        "FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    _check_quotation_owner(row, user)
    _require_financial_view(user)
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
        "SELECT data_json, customer_name, sales_person_id, sales_person, assigned_user_ids "
        "FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    # 2026-09-13（模組權限稽核）：這支原本只要求登入——任何已登入帳號（含 viewer
    # 與 automation 服務帳號）都能覆寫**任何**案件的成本精算，只有 finalized 之後
    # 才收斂成「僅 superadmin」。這是全系統唯一一個「寫入」層級的缺口，補上與
    # GET 相同的擁有者檢查。
    try:
        _check_quotation_owner(row, user)
        _require_financial_view(user)
    except HTTPException:
        conn.close()
        raise
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


# ── 案件財務總覽（應收應付，2026-09-09）────────────────────────────────────────

@router.get("/api/quotations/{quote_no}/finance-summary")
def get_finance_summary(quote_no: str, authorization: str = Header(None)):
    """案件管理－財務 Tab「應收應付總覽」用：把一個案件的錢一次算完回傳。

    這些數字原本散在四個地方，從來沒有一個畫面把它們並排看過：應收在
    `data_json.caseRecord.payment.items[]`（案件資訊 Tab 的款項明細）、應付在
    `contractor_payment_vouchers`（承攬商 Tab）、開票申請在 `invoice_vouchers`、
    請款單在 `payment_requests`（各自的子清單）。

    **刻意不做的事**：
    - `invoice_vouchers`／`payment_requests` 只回唯讀清單，**不併進應收合計**。
      它們是「開票／要款」流程文件，金額範圍（scope='amount'|'items'）跟收款
      排程的期別不是一對一對應，合併會變成同一筆錢被算兩次。
    - 精算「額外支出」（`settlement.extraItems[]`）只回小計供參考，**不計入
      應付**。這個清單沒有已付/未付狀態欄位，硬把它當應付等於憑空發明一個
      系統從來沒追蹤過的狀態。
    - 權限比照同一批資料的既有端點（`get_settlement()`／
      `list_contractor_vouchers()`／`list_invoice_vouchers()`）。這裡不另外加
      `financial_view` 檢查——同一份資料透過上述既有端點本來就拿得到，只擋這一支
      會是假的安全感；`financial_view` 是**顯示偏好**（前端 `canSeeFinancial()`），
      不是權限邊界。
      2026-09-13（模組權限稽核）：`get_settlement()` 那支補上了擁有者檢查，這支
      跟著補——「比照既有端點」指的是同一套擁有者規則，不是「都不擋」。
    """
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT total, pretax, data_json, sales_person_id, sales_person, assigned_user_ids "
        "FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    try:
        _check_quotation_owner(row, user)
        _require_financial_view(user)
    except HTTPException:
        conn.close()
        raise

    data  = json.loads(row["data_json"] or "{}")
    total = float(row["total"] or 0)
    pay_items = ((data.get("caseRecord") or {}).get("payment") or {}).get("items") or []
    receivable = summarize_payment_items(total, pay_items, row["pretax"])

    # ── 應付：承攬商匯款申請 ──────────────────────────────────────────────
    # 「已核准未匯款」才是真正該付而未付的錢；還在簽核流程裡的只回筆數當提醒，
    # 不計入未付合計（金額還可能被退回或改動）。is_paid 跟 status 是兩個獨立
    # 狀態（見 db.py::_m045_contractor_payment_vouchers），不要用 status 推論
    # 有沒有付款。
    approved_unpaid = approved_paid = pending_total = 0
    pending_count = 0
    vouchers = []
    for v in conn.execute(
        "SELECT * FROM contractor_payment_vouchers WHERE quote_no=? ORDER BY created_at DESC",
        (quote_no,),
    ).fetchall():
        snap   = json.loads(v["snapshot_json"] or "{}")
        amount = float(snap.get("grandTotal") or 0)
        status = v["status"] or "草稿"
        paid   = bool(v["is_paid"])
        if status == "已核准" and paid:
            approved_paid += amount
        elif status == "已核准":
            approved_unpaid += amount
        else:
            pending_total += amount
            pending_count += 1
        vouchers.append({
            "voucherNo":   v["voucher_no"],
            "vendorName":  snap.get("vendorName", ""),
            "status":      status,
            "grandTotal":  amount,
            "payableDate": snap.get("payableDate", ""),
            "isPaid":      paid,
            "paidAt":      v["paid_at"] or "",
            "createdAt":   v["created_at"] or "",
        })

    # ── 關聯文件（唯讀清單，不併入合計，理由見 docstring）──────────────────
    invoice_vouchers = [{
        "voucherNo": r["voucher_no"],
        "status":    r["status"] or "草稿",
        "amount":    float(r["amount"] or 0),
        "createdAt": r["created_at"] or "",
    } for r in conn.execute(
        "SELECT voucher_no, status, amount, created_at FROM invoice_vouchers "
        "WHERE quote_no=? ORDER BY created_at DESC", (quote_no,)
    ).fetchall()]

    payment_requests = [{
        "requestNo": r["request_no"],
        "status":    r["status"] or "草稿",
        "stage":     r["stage"] or "",
        "amount":    float(r["amount"] or 0),
        "createdAt": r["created_at"] or "",
    } for r in conn.execute(
        "SELECT request_no, status, stage, amount, created_at FROM payment_requests "
        "WHERE quote_no=? ORDER BY created_at DESC", (quote_no,)
    ).fetchall()]

    settlement = data.get("settlement") or {}
    # 額外支出完整明細，包括發票文件與填寫人：案件財務總覽要展示這些，讓使用者
    # 知道是誰何時填的、有沒有上傳發票、憑證單號是什麼。
    #
    # 2026-09-11：改讀 `case_extra_expenses` 表（DB v75 把資料從
    # `settlement.extraItems` 搬出來了）。**不能再讀 data_json 那份**——它現在只是
    # 搬移前的唯讀備份、不會再更新，讀它會讓財務總覽停在搬移當下的舊數字。
    # 多回 `status` 與 `pending`：送審中的金額照樣計入（使用者指定），但畫面要
    # 標示出來，不然看數字的人不知道它還可能因駁回而改變。
    extras = [{
        "id":          r["id"],
        "category":    r["category"] or "",
        "description": r["description"] or "",
        "docNo":       r["doc_no"] or "",
        "totalCost":   float(r["total_cost"] or 0),
        "expenseDate": r["expense_date"] or "",
        "qty":         r["qty"],
        "unit":        r["unit"] or "",
        "unitCost":    float(r["unit_cost"] or 0),
        "note":        r["note"] or "",
        "createdBy":   r["created_by_name"] or "",
        "createdByInferred": bool(r["created_by_inferred"]),
        "payerName":   r["payer_name"] or "",
        "status":      r["status"],
        "pending":     r["status"] != "已核准",
        "files":       json.loads(r["files_json"] or "[]"),
    } for r in conn.execute(
        "SELECT * FROM case_extra_expenses WHERE quote_no=? ORDER BY id", (quote_no,)
    ).fetchall()]
    # 2026-09-11：conn 從這裡才關——額外支出改讀 case_extra_expenses 表之後，
    # 上面那段列表推導需要連線，原本在它之前就 close() 會變成 use-after-close
    conn.close()

    return {
        "quoteNo":    quote_no,
        "receivable": receivable,
        "payable": {
            "approvedUnpaidTotal": approved_unpaid,
            "approvedPaidTotal":   approved_paid,
            "pendingTotal":        pending_total,
            "pendingCount":        pending_count,
            "vouchers":            vouchers,
        },
        "relatedDocuments": {
            "invoiceVouchers": invoice_vouchers,
            "paymentRequests": payment_requests,
        },
        "settlementExtras": {
            "total": sum(e["totalCost"] for e in extras),
            "items": extras,
        },
    }


# ── 精算額外支出的附件端點已移除（2026-09-11）────────────────────────────────
#
# 原本這裡有 `_load_settlement_extra_item()` ＋ `/settlement/extra/{idx}/files`
# 上傳與刪除兩支端點。額外支出搬到 `case_extra_expenses` 表（DB v75）之後，
# 對應端點改在 `routers/case_extra_expenses.py`，並且**改用資料列 id 定位而不是
# 陣列索引**——舊版用 idx，額外支出一旦新增/刪除/重排，索引就會指到別筆去。
# 附件實體檔案的分類也從 "quotation_settlement_extra" 改成 "case_extra_expense"。


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


def _queue_visible_to(user: dict, item: dict, delegated_for) -> bool:
    """這一筆待簽核文件該不該讓這個人看到（2026-09-15 使用者要求）。

    「簽核佇列除了管理員以上都只能看到自己的簽核佇列卡在哪邊」。所以非 admin 的
    可見範圍是兩種，其餘一律看不到：

    1. **自己送審的**——他要知道自己的單子卡在哪一關、卡在誰身上
    2. **簽核鏈裡有自己的**（含代理他人時的被代理人）——比對的是**所有層**而不是
       只有當前層：只比當前層的話，下一關才輪到的人看不到即將輪到自己的單，
       已經簽過的人也看不到後面卡住了，兩種都會讓人誤以為「沒我的事」

    為什麼過濾放在這裡、而且只有一份：這支端點一路長到 8 種單據類型，每種各寫一
    段 WHERE 條件的話，下一次新增類型時漏掉的那一種就是全開的——而「漏了會外洩」
    的規則必須是預設安全。集中成一條規則、套在組裝好的 items 上，新類型自動被蓋到。

    `tiers` 為空的類型（case_change 是「任一 superadmin 皆可審核」的單層設計）對
    非 admin 只會落在第 1 條，這是對的：他不可能是它的簽核人。
    """
    if (user.get("role") or "") in ("superadmin", "admin"):
        return True
    mine = {user.get("username") or ""} | set(delegated_for or [])
    if item.get("requestedBy") in mine:
        return True
    for tier in item.get("tiers") or []:
        for ap in (tier.get("approvers") or []):
            if (ap.get("username") or "") in mine:
                return True
    return False


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

    # 會計傳票（`AS3`，`docs/windows/STATE.md` §236）：`vouchers.py:486` 送審、
    # `APPROVAL_DOC_TYPES` 第八個就是 voucher（`AS2` 已落地），而這支端點原本
    # 一直沒有它 —— 送審端點對、簽核端點對，而沒有人知道有單在等。
    # ⚠️ 跟其餘七種不一樣：`approval_json` 是 `vouchers_all` 自己的**欄位**，
    #    不是 `data_json.$.approval`（傳票沒有 `data_json`），所以是直接
    #    `SELECT approval_json`，不必 `json_extract`。
    # ⚠️ 傳票不掛在任何案件底下（一般分類帳憑證，不是報價流程的附屬文件），
    #    `customer`／`projectName` 沒有東西可填，跟 `case_change` 一樣留空/留摘要。
    v_rows = conn.execute("""
        SELECT id, voucher_no, voucher_date, summary, submitted_by, submitted_at,
               approval_json,
               COALESCE((SELECT SUM(debit) FROM voucher_lines
                         WHERE voucher_id = vouchers_all.id), 0) as total_debit
        FROM vouchers_all
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    for r in v_rows:
        f = _queue_tier_fields(r["approval_json"])
        # 🔑 `submit_voucher()` 沒有設定過流程時 `tiers` 是空的，approval_json
        #    仍然嵌著 requestedBy 三欄（`AS3` 一併補上）——但舊資料（這支上線
        #    之前就送審的傳票）沒有，這裡退回讀 `submitted_by`／`submitted_at`
        #    兩欄，不讓舊單在佇列上掛名空白。
        requested_by = f["requestedBy"] or r["submitted_by"] or ""
        items.append({
            "type":                "voucher",
            "quoteNo":             r["voucher_no"],
            "customer":            "",
            "projectName":         r["summary"] or "",
            "total":               r["total_debit"] or 0,
            "quoteDate":           r["voucher_date"] or "",
            "salesPerson":         "",
            "requestedBy":         requested_by,
            "requestedByDisplay":  f["requestedByDisplay"] or requested_by,
            "requestedAt":         f["requestedAt"] or r["submitted_at"] or "",
            "isEditApproval":      False,
            "reasons":             [],
            "tiers":               f["tiers"],
            "currentTier":         f["currentTier"],
            "tierCount":           f["tierCount"],
            "currentApprovers":    f["currentApprovers"],
            # 🔴 `apiBase(item)` 對其他型別是接 `item.quoteNo`（那些端點的路徑
            #    參數吃的是人看的單號），但 `/api/vouchers/{voucher_id}/...`
            #    吃的是**數字 id**——兩者是不同的識別碼，這裡兩個都給，
            #    前端用哪一個視型別而定（見 approval-queue.html `itemPathId()`）。
            "voucherId":           r["id"],
        })

    # 獎金分潤單（`BN8`）：跟傳票同一種形狀——approval_json 是
    # bonus_awards 自己的欄位，不是 data_json.$.approval。獎金分潤單也
    # 不掛在任何案件底下（`quote_no` 是關聯案件，不是佇列要導向的對象），
    # customer/projectName 留空/留關聯案件字串，跟 voucher 一致。
    # ⚠️ 沒有 submitted_by/at 這種獨立欄位（`SPEC-BN8.md §1`：一格投影
    # 欄位都沒有）——requestedBy 直接用 created_by/created_at，不必像
    # 傳票那樣在 JSON 裡另外嵌一份再退回欄位。
    ba_rows = conn.execute("""
        SELECT id, quote_no, base_amount, created_by, created_at, approval_json
        FROM bonus_awards
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    for r in ba_rows:
        f = _queue_tier_fields(r["approval_json"])
        items.append({
            "type":                "bonus_award",
            "quoteNo":             "獎金-%s" % r["id"],
            "customer":            "",
            "projectName":         "關聯案件 %s" % (r["quote_no"] or ""),
            "total":               r["base_amount"] or 0,
            "quoteDate":           (r["created_at"] or "")[:10],
            "salesPerson":         "",
            "requestedBy":         r["created_by"] or "",
            "requestedByDisplay":  r["created_by"] or "",
            "requestedAt":         r["created_at"] or "",
            "isEditApproval":      False,
            "reasons":             [],
            "tiers":               f["tiers"],
            "currentTier":         f["currentTier"],
            "tierCount":           f["tierCount"],
            "currentApprovers":    f["currentApprovers"],
            "linkedQuoteNo":       r["quote_no"],
            # 🔴 與 voucher 同一個道理：`/api/bonus/awards/{award_id}/...`
            #    吃數字 id，不是人看的單號（這裡連人看的單號都沒有）。
            "awardId":             r["id"],
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

    # 案件額外支出（2026-09-11）：跟其他五種單據一樣進統一佇列，否則送審之後
    # 簽核人不會在任何地方看到它，只能靠站內通知——那是「送審了但沒人知道要簽」
    # 的典型來源。tiers 用真實的分層資料（不像 case_change 借用空 tiers 的捷徑），
    # 因為這個類型走的就是正規的 tiered_approval。
    xe_rows = conn.execute("""
        SELECT e.id, e.quote_no, e.description, e.total_cost, e.approval_json,
               q.customer_name, q.project_name
        FROM case_extra_expenses e
        LEFT JOIN quotations q ON q.quote_no = e.quote_no
        WHERE e.status IN ('待審核','簽核中')
        ORDER BY e.id DESC
    """).fetchall()
    for r in xe_rows:
        f = _queue_tier_fields(r["approval_json"])
        items.append({
            "type":                "extra_expense",
            "quoteNo":             f"{r['quote_no']}-XE{r['id']}",
            "customer":            r["customer_name"] or "",
            "projectName":         r["description"] or "",
            "total":               r["total_cost"] or 0,
            "quoteDate":           (f["requestedAt"] or "")[:10],
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
            "extraExpenseId":      r["id"],
        })

    # 完工單（2026-09-12）：跟出貨單同一種形狀，簽核狀態在 data_json.$.approval。
    # 佇列上刻意把「未完成項目數」放進 projectName 一起顯示——完工單常常不是每一
    # 項都 100% 完成，簽核人要先知道自己簽的是不是一張帶缺失的完工單。
    cn_rows = conn.execute("""
        SELECT note_no, quote_no, customer_name, project_name, completion_date, created_at,
               items_json, json_extract(data_json,'$.approval') as approval_json
        FROM completion_notes
        WHERE status IN ('待審核','簽核中')
        ORDER BY id DESC
    """).fetchall()
    for r in cn_rows:
        f = _queue_tier_fields(r["approval_json"])
        try:
            cn_items = json.loads(r["items_json"] or "[]")
        except Exception:
            cn_items = []
        real_items = [it for it in cn_items if it.get("type") != "header"]
        unfinished = sum(1 for it in real_items if it.get("status") in ("部分完成", "未施作"))
        label = r["project_name"] or ""
        if unfinished:
            label = f"{label}（{unfinished} 項未完成）"
        items.append({
            "type":                "completion_note",
            "quoteNo":             r["note_no"],
            "customer":            r["customer_name"] or "",
            "projectName":         label,
            "total":               len(real_items),
            "quoteDate":           r["completion_date"] or (r["created_at"] or "")[:10],
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
            "unfinishedCount":     unfinished,
        })

    # 額外支出「變更申請」（2026-09-11 第二輪，DB v76）：已核准之後的編輯要簽核，
    # 簽核狀態在 change_approval_json 這一欄，跟本體的 approval_json 是兩條獨立的
    # 線（本體維持「已核准」不動，見 case_extra_expenses.py 末段）。**一定要獨立
    # 列進佇列**——借用上面那個 extra_expense 類型的話，簽核人按下核准會打到本體
    # 的 /approve，那支看到 status 已經是「已核准」就 409，變更永遠簽不掉。
    xec_rows = conn.execute("""
        SELECT e.id, e.quote_no, e.description, e.total_cost, e.change_json,
               e.change_approval_json, q.customer_name, q.project_name
        FROM case_extra_expenses e
        LEFT JOIN quotations q ON q.quote_no = e.quote_no
        WHERE e.change_status IN ('待審核','簽核中')
        ORDER BY e.id DESC
    """).fetchall()
    for r in xec_rows:
        f = _queue_tier_fields(r["change_approval_json"])
        try:
            chg = json.loads(r["change_json"] or "{}")
        except Exception:
            chg = {}
        items.append({
            "type":                "extra_expense_change",
            "quoteNo":             f"{r['quote_no']}-XE{r['id']}改",
            "customer":            r["customer_name"] or "",
            # 佇列上一眼就要看得出「改什麼、從多少變多少」，只放新說明的話簽核人
            # 得自己去案件裡翻舊值
            "projectName":         f"{chg.get('description') or r['description'] or ''}"
                                   f"（原 NT$ {float(r['total_cost'] or 0):,.0f}）",
            "total":               chg.get("totalCost") or 0,
            "quoteDate":           (f["requestedAt"] or "")[:10],
            "salesPerson":         "",
            "requestedBy":         f["requestedBy"],
            "requestedByDisplay":  f["requestedByDisplay"],
            "requestedAt":         f["requestedAt"],
            "isEditApproval":      True,
            "reasons":             [],
            "tiers":               f["tiers"],
            "currentTier":         f["currentTier"],
            "tierCount":           f["tierCount"],
            "currentApprovers":    f["currentApprovers"],
            "linkedQuoteNo":       r["quote_no"],
            "extraExpenseId":      r["id"],
            "previousTotal":       r["total_cost"] or 0,
            "pendingFileCount":    len(chg.get("addFiles") or []),
        })

    conn.close()

    # 權限過濾（2026-09-15）：管理員以上看全部，其他人只看自己送審的與簽核鏈裡
    # 有自己的。過濾在分組**之前**——分組之後才過濾會留下空的群組，畫面上會出現
    # 「某某人 0 件」這種列。
    items = [it for it in items if _queue_visible_to(user, it, my_delegated_for)]

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
    # 完工單（2026-09-12）：角標數字要跟佇列列表一致，漏掉就會變成「列得出來但
    # topbar 是 0」——兩邊矛盾比兩邊都沒有更難查
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT json_extract(data_json,'$.approval') FROM completion_notes WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT json_extract(data_json,'$.approval') FROM payment_requests WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    # 會計傳票（`AS3`）：跟案件額外支出一樣，approval_json 是 vouchers_all
    # 自己的欄位（沒有 data_json），直接取欄位。角標數字要跟佇列列表一致，
    # 漏掉就是「列得出來但 topbar 是 0」——兩邊矛盾比兩邊都沒有更難查。
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT approval_json FROM vouchers_all WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    # 獎金分潤單（`BN8`）：跟傳票同一種形狀，approval_json 是 bonus_awards
    # 自己的欄位。submit_award() 有嵌 requestedBy，沒有鏈時「自己送的
    # 不算」判準才成立。
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT approval_json FROM bonus_awards WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    # 案件額外支出（2026-09-11）：這張表的簽核狀態存在獨立欄位 approval_json，
    # 不是 data_json 裡的 $.approval，所以直接取欄位；下面那段逐筆比對當層
    # approver 的邏輯完全共用，不必另外寫一份。
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT approval_json FROM case_extra_expenses WHERE status IN ('待審核','簽核中')"
    ).fetchall()]
    # 額外支出變更申請（2026-09-11，DB v76）：另一欄、另一輪簽核，角標要一起算，
    # 否則佇列頁列得出來但 topbar 數字是 0（兩邊矛盾比兩邊都沒有更難查）
    approval_jsons += [r[0] for r in conn.execute(
        "SELECT change_approval_json FROM case_extra_expenses "
        "WHERE change_status IN ('待審核','簽核中')"
    ).fetchall()]
    # 已結案案件半解鎖變更（2026-08-26）：單層審核，任一 superadmin 皆算「輪到我」，
    # 不像其他文件類型需要比對 tiers 當層 approver username，直接另外加總。
    ccr_count = 0
    if u["role"] == "superadmin":
        # 2026-09-15 修正：原本是 `WHERE status='pending'` 全部算進來，**沒有排除
        # 自己送的**。自己送的自己簽不掉（`check_no_tier_self_approval()` 會擋，
        # 佇列頁的 `canApprove()` 也回 false），所以那會變成一個**永遠清不掉的
        # 紅點**——使用者看到角標有數字、點進佇列卻沒有待我簽核的項目。
        ccr_count = conn.execute(
            "SELECT COUNT(*) c FROM case_change_requests "
            "WHERE status='pending' AND COALESCE(requested_by,'') != ?",
            (my_username,)
        ).fetchone()["c"]
    conn.close()
    count = ccr_count
    is_sa = u["role"] == "superadmin"
    for approval_json in approval_jsons:
        try:
            appr    = json.loads(approval_json or "{}")
            tiers   = _active_tiers(appr)
            ct_idx  = _current_tier_idx(appr)
            if tiers:
                if ct_idx < len(tiers):
                    approvers = tiers[ct_idx].get("approvers") or []
                    if any(a.get("username") in my_usernames and a.get("status") != "approved"
                           for a in approvers):
                        count += 1
            elif is_sa and (appr.get("requestedBy") or "") != my_username:
                # 2026-09-15 修正：**沒有簽核層設定**的單據原本被整批跳過
                # （原碼是 `if tiers and ct_idx < len(tiers)`）。
                # 沒有 tiers 時的規則是「任一 superadmin 皆可簽核」——
                # `approve_quotation()` 的 no-tier 分支就是這樣走的
                # （`detail_status = "超級管理員簽核"`），佇列頁的 `canApprove()`
                # 也是這樣判（`// No tiers: superadmin, not self`）。
                # 漏掉的結果是**佇列列得出來、topbar 卻是 0**，正是使用者回報的
                # 「需要我簽核但簽核佇列未顯示」。
                #
                # ⚠️ 這裡刻意跟前端 `canApprove()` 一致：自己送的一律不算。
                # 後端 `check_no_tier_self_approval()` 另有「唯一在職 superadmin
                # 可自簽」的逃生條款，但前端不會給按鈕，角標跟著後端算反而會
                # 製造一個按不下去的紅點。
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
        cascaded = []
        if tier_done:
            # 同一人連任多層時一次簽完（2026-09-15）：前端確認過才會帶 cascade，
            # 且只吃「剩下未簽的只有他自己」的連續層，不會替別人做決定。
            if body.cascade:
                cascaded = cascade_self_tiers(tiers, ct_idx, user["username"], now, conn=conn)
            landed = ct_idx + 1 + len(cascaded)
            appr["currentTier"] = landed
            all_done = landed >= len(tiers)
            if not all_done:
                next_tier = tiers[landed]
                _next_names = []
                for na in next_tier.get("approvers") or []:
                    _notify(na["username"], "approval_request", quote_no, quote_no,
                            f"報價單 {quote_no}（{cname}）輪到您簽核（第 {landed + 1} 層 / 共 {len(tiers)} 層）")
                    _next_names.append(na["username"])
                notify_next_tier(quote_no, cname, landed + 1, len(tiers), _next_names)
        else:
            all_done = False

        # write back tiers
        appr["tiers"] = tiers
        appr.pop("steps", None)
        appr.pop("currentStep", None)
        _signed_tier_nos = [i + 1 for i in [ct_idx, *cascaded]]
        detail_status = (f"第 {'、'.join(str(n) for n in _signed_tier_nos)} 層 "
                         f"{my_entry.get('displayName', user['username'])} 已簽核")
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
        _signed_tier_nos = []

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
    return {"ok": True, "allDone": all_done, "signedTiers": _signed_tier_nos}


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
    # `QL25`（依據使用者 2026-09-23 裁示）：退回也是回草稿的一條路，
    # 同 recall_quotation() 清掉據點快照——理由一樣：草稿階段要跟著
    # 設定即時走，不是印退回當下凍結的那份舊抬頭。
    d.pop(SNAPSHOT_KEY, None)

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
    # 2026-09-13：這支原本呼叫了兩次 _require_user()（開頭一次不取回傳值、
    # 下面再一次取 user），合併成一次。
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    row = conn.execute("SELECT quote_no FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "報價單不存在")

    dn_map = {r["username"]: (r["display_name"] or r["username"])
              for r in conn.execute("SELECT username, display_name FROM users").fetchall()}
    results = []

    # 1. Manual comments
    for c in conn.execute(
        "SELECT id, author, content, type, created_at, files_json FROM case_updates "
        "WHERE quote_no=? ORDER BY created_at DESC", (quote_no,)
    ).fetchall():
        try:
            c_files = json.loads(c["files_json"] or "[]")
        except Exception:
            c_files = []
        results.append({
            "id": c["id"],
            "source": "comment",
            "files": c_files,
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
async def post_case_update(quote_no: str,
                           content: str = Form(""),
                           important: str = Form(""),
                           files: List[UploadFile] = File(default=[]),
                           authorization: str = Header(None)):
    """案件動態留言（2026-09-14 起可附照片／檔案）。

    **改成 multipart 而不是另開一支補傳端點**（使用者裁示）：一次請求送出，
    不會出現「文字存了、檔案失敗」這種半完成狀態——留言板的那一則已經貼出去
    了，附件卻沒上去，使用者只能再貼一則說「補圖」。

    `important` 走 Form 會是字串，"true"/"1"/"on" 都當真；沿用瀏覽器 FormData
    的慣例，不要求前端自己轉。

    照片會壓上「上傳者 · 日期時間 · GPS」浮水印（使用者裁示），PDF 不動，
    見 helpers/uploads.py::save_document_files() 的 watermark_by。
    """
    user = _require_user(authorization)
    content = (content or "").strip()
    important = str(important).strip().lower() in ("1", "true", "on", "yes")
    # 附件自己就是內容——只傳圖不打字是合理的用法，不該被「內容不得為空」擋下
    if not content and not files:
        raise HTTPException(400, "請輸入內容或至少上傳一個檔案")
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    qrow = conn.execute(
        "SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not qrow:
        conn.close()
        raise HTTPException(404, "報價單不存在")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    update_type = "important" if important else "comment"
    saved_files = []
    if files:
        # 存檔在 INSERT 之前：檔案存失敗（格式/大小）就整批擋下，不會留下
        # 一則沒有附件的留言讓使用者以為傳成功了
        saved_files = await save_document_files(
            "case_updates", quote_no, files,
            user.get("display_name") or user["username"],
            watermark_by=user.get("display_name") or user["username"],
        )
    cur = conn.execute(
        "INSERT INTO case_updates (quote_no, author, content, type, created_at, files_json) "
        "VALUES (?,?,?,?,?,?)",
        (quote_no, user["username"], content, update_type, now,
         json.dumps(saved_files, ensure_ascii=False)),
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
        "files": saved_files,
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
        "SELECT id, author, files_json FROM case_updates WHERE id=? AND quote_no=?", (uid, quote_no)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "留言不存在")
    if user["role"] not in ("superadmin", "admin") and user["username"] != row["author"]:
        conn.close()
        raise HTTPException(403, "只能刪除自己的留言")
    # 留言刪掉，它的附件也要從磁碟上清掉——否則 uploads/ 會留下永遠沒人引用的
    # 孤兒檔案，而且 archive.py::_mirror_uploads() 只增不減，會一路跟著進雲端備份
    try:
        for f in json.loads(row["files_json"] or "[]"):
            full = os.path.join(_uploads_mod.UPLOADS_ROOT, f.get("path", ""))
            if f.get("path") and os.path.isfile(full):
                os.remove(full)
    except Exception:
        pass
    conn.execute("DELETE FROM case_updates WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    notify_module_activity("案件留言板", "刪除留言", user.get("display_name") or user["username"],
                            quote_no, "case-management.html")
    return {"ok": True}


@router.delete("/api/quotations/{quote_no}/updates/{uid}/files/{file_id}")
def delete_case_update_file(quote_no: str, uid: int, file_id: str,
                            authorization: str = Header(None)):
    """刪除動態留言的單一附件——**限 admin 以上**（2026-09-14 使用者裁示）。

    跟「刪整則留言」的權限刻意不同：整則留言發文者自己就能收回（那是撤回自己
    說過的話），但單獨抽掉一張附件是**只改證據、留下文字**，等於事後修改已經
    被別人看過的內容。這種事留給管理員。
    """
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可刪除附件")
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_module="case_manage")
    row = conn.execute(
        "SELECT id, files_json FROM case_updates WHERE id=? AND quote_no=?", (uid, quote_no)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "留言不存在")
    existing = json.loads(row["files_json"] or "[]")
    remaining = delete_document_file("case_updates", quote_no, existing, file_id)
    conn.execute("UPDATE case_updates SET files_json=? WHERE id=?",
                 (json.dumps(remaining, ensure_ascii=False), uid))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "case_update.delete_file", "quotation", quote_no,
           f"{quote_no} 留言 #{uid} 刪除附件")
    return {"ok": True, "files": remaining}


@router.get("/api/quotations/{quote_no}/pdf-download")
def download_quotation_pdf(quote_no: str, internal: bool = False, authorization: str = Header(None)):
    """後端 Edge Headless 產生 PDF 並直接下載（internal=true 含成本），避免 macOS/瀏覽器列印頁首干擾。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_approver=True)
    # 🔑 QL10：把 `location_id` 一起取出來 —— 列印的稽核要記得下這一次用了哪個據點。
    row  = conn.execute(
        "SELECT quote_no, location_id FROM quotations WHERE quote_no=?",
        (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "報價單不存在")
    try:
        pdf_bytes = generate_pdf_bytes(quote_no, internal=internal)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        tid = trace_id()
        logger.exception("quotation pdf failed trace=%s", tid)
        raise HTTPException(500, f"PDF 產生失敗（代碼 {tid}）")
    mode_label = "內部版" if internal else "對外版"
    # 🔴🔴 QL10：**讀即時值不做快照**（A 裁定）—— 匯款帳號要回答的是
    #    「**現在**該匯到哪」，舊單據印出舊帳號的話，對方會照著匯到一個
    #    已經關掉的帳戶。
    # ☠️ **而那個選擇有代價：改一次據點設定，所有歷史 PDF 重印時都會變。**
    # 🔑 代價不假裝不存在，它變成**可追查**：這一行記下這次列印用的是哪一個
    #    據點、以及當下那組值的抬頭與帳號。
    # 📌 少了它，客戶拿著兩張同號不同帳號的單子來問，
    #    **我們答不出哪一張是哪一天印的。**
    _loc_id = (row["location_id"] or "") if "location_id" in row.keys() else ""
    try:
        from pdf_gen import location_identity
        _ident = location_identity(_loc_id or None)
    except Exception:       # noqa: BLE001 —— 稽核不可以讓下載失敗
        _ident = {}
    _audit(_tok(authorization), "quotation.export_pdf", "quotation", quote_no,
           f"{quote_no} {mode_label} PDF 下載"
           + (f"（據點 {_loc_id}）" if _loc_id else "（據點：主要據點）"),
           {"mode": "internal" if internal else "external", "via": "server",
            "locationId": _loc_id or None,
            # ⚠️ 只記抬頭與帳號**末四碼** —— 完整帳號不進稽核紀錄。
            #    要答的是「這張印的是哪一組」，不是「帳號是多少」。
            "companyName": _ident.get("company_name") or None,
            "bankAccountLast4": (_ident.get("bank_account_number") or "")[-4:] or None})
    fname = f"{quote_no}_內部.pdf" if internal else f"{quote_no}.pdf"
    encoded = urlquote(fname)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


# ── 單據版本與編輯紀錄查詢（2026-09-14）──────────────────────────────────────

@router.get("/api/quotations/{quote_no}/versions")
def list_quotation_versions(quote_no: str, authorization: str = Header(None)):
    """這張單有哪幾份存檔版本、被誰在什麼時候改過什麼。

    回傳兩條時間軸：
      `versions` — 每次自動備存的 PDF（建立／修改／簽核／已簽核／結案）。
                   `available` 標示實體檔案現在還在不在（PDF 存檔目錄是
                   superadmin 可設定的路徑，可能被搬動或改設定）。
      `history`  — `editHistory`：誰在什麼時候改了哪些欄位。

    刻意分成兩條而不是合併：PDF 是**完整快照**（可以拿去對帳、給客戶看），
    編輯紀錄是**欄位層級索引**（查得到改了什麼，但不是一份文件）。硬合成一條
    會讓人以為每一筆編輯紀錄背後都有對應的 PDF，那不成立——一般編輯不產 PDF。
    """
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_approver=True)
    row = conn.execute(
        "SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "報價單不存在")

    data = json.loads(row["data_json"] or "{}")
    base = _get_pdf_base()

    versions = []
    for v in (data.get("docVersions") or []):
        if not isinstance(v, dict):
            continue
        rel = str(v.get("file") or "")
        full = _resolve_archived_pdf(base, rel)
        versions.append({
            "seq":       v.get("seq"),
            "at":        v.get("at", ""),
            "event":     v.get("event", ""),
            "by":        v.get("by", ""),
            "size":      v.get("size", 0),
            "filename":  os.path.basename(rel),
            "available": bool(full and os.path.isfile(full)),
        })

    history = [h for h in (data.get("editHistory") or []) if isinstance(h, dict)]
    return {"quote_no": quote_no, "versions": versions, "history": history}


def _resolve_archived_pdf(base: str, rel: str):
    """把 docVersions 存的相對路徑解析成絕對路徑，越界就回 None。

    這些值是系統自己寫的、不是使用者輸入，但存檔路徑可被 superadmin 設定成
    網路碟，而且這個值會經過 data_json（備份、還原、手動修過的資料都可能經手）
    ——照 routers/uploads.py `_resolve_upload_path()` 的既有慣例一律驗界。
    """
    if not rel:
        return None
    try:
        root = os.path.realpath(base)
        full = os.path.realpath(os.path.join(root, rel.lstrip("/\\")))
        if os.path.commonpath([full, root]) != root:
            return None
        return full
    except (ValueError, OSError):
        return None


@router.get("/api/quotations/{quote_no}/versions/{seq}/download")
def download_quotation_version(quote_no: str, seq: int, authorization: str = Header(None)):
    """下載某一個已存檔的版本（原始 PDF 檔案本身，不是重新產生）。

    **一定要回存檔的那個檔案、不能重新產生**——重新產生拿到的是「現在的內容」，
    那正好是這個功能要避免的事：要查的是「當時送出去的那一份長什麼樣」。
    """
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_approver=True)
    row = conn.execute(
        "SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "報價單不存在")

    data = json.loads(row["data_json"] or "{}")
    target = next((v for v in (data.get("docVersions") or [])
                   if isinstance(v, dict) and v.get("seq") == seq), None)
    if not target:
        raise HTTPException(404, "找不到這個版本")

    full = _resolve_archived_pdf(_get_pdf_base(), str(target.get("file") or ""))
    if not full or not os.path.isfile(full):
        raise HTTPException(
            404, "這個版本的存檔檔案已不存在（PDF 存檔目錄可能被搬移或清理過）")

    with open(full, "rb") as f:
        content = f.read()
    _audit(_tok(authorization), "quotation.download_version", "quotation", quote_no,
           f"{quote_no} 下載存檔版本 #{seq}（{target.get('event','')}）",
           {"seq": seq, "file": target.get("file")})
    fname = os.path.basename(full)
    encoded = urlquote(fname)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


@router.get("/api/quotations/{quote_no}/closing-report-pdf")
def download_case_closing_report_pdf(quote_no: str, authorization: str = Header(None)):
    """案件結案報表 PDF（含財務數據／支出／收入／收款／執行進度／損益分析），
    僅限已結案案件；含成本與毛利等內部機密資訊，不對外提供。"""
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_approver=True, allow_module="case_manage")
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
        tid = trace_id()
        logger.exception("quotation case-closing pdf failed trace=%s", tid)
        raise HTTPException(500, f"結案報表 PDF 產生失敗（代碼 {tid}）")
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
    user = _require_user(authorization)
    conn = get_db()
    _guard_case(conn, quote_no, user, allow_approver=True, allow_module="case_manage")
    row = conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "報價單不存在")
    try:
        pdf_bytes = generate_project_execution_report_pdf_bytes(quote_no)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        tid = trace_id()
        logger.exception("quotation project-execution-report pdf failed trace=%s", tid)
        raise HTTPException(500, f"專案執行報告 PDF 產生失敗（代碼 {tid}）")
    _audit(_tok(authorization), "quotation.export_project_report", "quotation", quote_no,
           f"{quote_no} 專案執行報告 PDF 下載", {"via": "server"})
    fname = f"{quote_no}_專案執行報告.pdf"
    encoded = urlquote(fname)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


# ── 簽核佇列的送審詳情（2026-09-14）──────────────────────────────────────────
#
# 使用者要求：「簽核佇列內的送審資料要詳細，例如夾帶檔案，要顯示哪個案件什麼內容，
# 如果是檔案可顯示預覽，編修後的結果」。
#
# 佇列清單維持原樣（八種單據共用同一組欄位，前端渲染邏輯不用動）；詳情另開一支
# **依 type 分流**的端點。不把這些塞進清單的理由：清單一次可能上百筆，每筆都去讀
# items_json／files_json／payload_json 會讓開啟簽核佇列變慢，而使用者一次只看一筆。

def _tagged_file_entries(raw, tag) -> list:
    """`AT1`：`_file_entries()` 的結果幫每一筆加一個來源前綴。

    ⚠️ 不新加一個 `source` 鍵——前端的檔案卡片只顯示 `f.name`（
    `approval-queue.html:812`），加鍵而不改前端範本的話，來源標記進了
    API 回應卻沒有人看得到。直接把標記寫進 `name` 本身，前端 0 行也
    看得到「哪一筆是哪一段的憑證」。
    """
    out = _file_entries(raw)
    for f in out:
        f["name"] = "【%s】%s" % (tag, f.get("name") or "")
    return out


def _file_entries(raw) -> list:
    """把各表存的檔案 JSON 正規化成前端可預覽的格式。

    各模組的檔案結構不完全一樣（有的 `filename` 有的 `name`，路徑鍵也不同），
    這裡統一成 `{name, path, kind}`；`kind` 讓前端決定是直接內嵌預覽（圖片）、
    開新分頁（PDF）還是只給下載連結。
    """
    try:
        arr = json.loads(raw or "[]")
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for f in arr:
        if not isinstance(f, dict):
            continue
        name = f.get("filename") or f.get("name") or ""
        path = f.get("path") or f.get("filePath") or ""
        if not path:
            continue
        low = (name or path).lower()
        kind = ("image" if low.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
                else "pdf" if low.endswith(".pdf") else "file")
        out.append({"id": f.get("id") or path, "name": name or path.split("/")[-1],
                    "path": path, "kind": kind,
                    "uploadedBy": f.get("uploadedBy") or f.get("by") or "",
                    "uploadedAt": f.get("uploadedAt") or f.get("at") or ""})
    return out


def _case_header(conn, quote_no: str) -> dict:
    row = conn.execute(
        "SELECT quote_no, customer_name, project_name, " + SQL_DEAL_TAG + " AS deal_tag "
        "FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        return {"quoteNo": quote_no, "customerName": "", "projectName": "", "dealTag": ""}
    return {"quoteNo": row["quote_no"], "customerName": row["customer_name"] or "",
            "projectName": row["project_name"] or "", "dealTag": row["deal_tag"] or ""}


# ── 已結案變更申請的可讀摘要（2026-09-14 使用者交辦）────────────────────────
#
# 原本這裡是 `{"after": payload, "before": None}`——把 `payload_json` 整包丟給前端，
# 而前端對物件值是 `JSON.stringify()`，所以簽核畫面上直接出現一大段
# `{"stages":[...],"payment":{"items":[{...}]}}`，裡面混著 `writeOffRequestedAt`、
# `invoiceFiles[].path` 這種內部欄位。**審核者根本無法從中判斷要不要核准。**
#
# ⚠️ 而且不只是難讀——是**會誤導**：`approve_case_change()` 對
# `case_record_update` 的第一件事就是 `new_case_record["stages"] = cr.get("stages")`，
# 也就是 **payload 裡的 stages 根本不會被套用**（階段有自己的專屬端點）。
# 把它印在「核准後會套用的內容」底下，等於告訴審核者一件不會發生的事。
# 所以下面的攤平**刻意不收 stages**。

_CASE_SCALAR_LABELS = {
    "contract.deliveryAddress": "合約·交貨地址",
    "contract.deliveryTerms":   "合約·交貨條件",
    "contract.contactPerson":   "合約·聯絡人",
    "contract.contactPhone":    "合約·聯絡電話",
    "contract.contractNote":    "合約·備註",
    "roles.filler":             "角色·填表人",
    "roles.sales":              "角色·業務負責",
    "roles.executor":           "角色·執行負責",
    "projectTimeline.startDate": "專案期間·起日",
    "projectTimeline.endDate":   "專案期間·迄日",
    "projectTimeline.status":    "專案期間·狀態",
    "notes":                    "備註",
    "warrantyNote":             "保固說明",
}

# 值本身是代碼而不是給人看的字的欄位，要另外翻（2026-09-14 使用者回報：
# 摘要裡出現「專案期間·狀態 on_track」）。**只翻已知的值**，遇到沒見過的
# 原樣顯示——硬猜一個中文會讓人以為系統認得它。
_CASE_VALUE_LABELS = {
    "projectTimeline.status": {
        "on_track":  "進行中",
        "at_risk":   "有風險",
        "delayed":   "已延遲",
        "done":      "已完成",
        "completed": "已完成",
    },
}

# 款項每一期要攤平出來比對的欄位（只挑審核時真的需要看的，
# writeOff*／invoiceFiles 這類內部欄位不收）
_PAYMENT_ITEM_LABELS = {
    "type":         "類型",
    "amount":       "金額",
    "pct":          "比例(%)",
    "received":     "已收款",
    "receivedAt":   "收款日期",
    "invoiceNo":    "發票號碼",
    "invoiceDate":  "發票日期",
    "actualAmount": "實收金額",
    "feeAmount":    "手續費",
    "note":         "備註",
}


def _dig_path(d, path):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _flatten_case_record(cr: dict) -> dict:
    """把 caseRecord 攤平成「可讀標籤 → 純量值」，供逐欄比對。

    刻意只收審核時真的要看的東西：合約、角色、專案期間、備註，以及款項每一期
    的金額與收款狀態。`stages` 不收（核准時會被現有值覆蓋，見上方說明），
    `materials`／`devices` 只收筆數（逐項展開會比 raw JSON 還長，而真正要核的是
    「有沒有變動」——真要看細節請開案件頁）。
    """
    out = {}
    if not isinstance(cr, dict):
        return out

    for path, label in _CASE_SCALAR_LABELS.items():
        v = _dig_path(cr, path)
        if v in (None, ""):
            continue
        vmap = _CASE_VALUE_LABELS.get(path)
        out[label] = vmap.get(v, v) if vmap else v

    items = ((cr.get("payment") or {}).get("items")
             if isinstance(cr.get("payment"), dict) else None)
    if isinstance(items, list):
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            for k, lbl in _PAYMENT_ITEM_LABELS.items():
                v = it.get(k)
                if v in (None, ""):
                    continue
                if k == "received":
                    v = "是" if v else "否"
                out[f"款項 #{i + 1}·{lbl}"] = v

    for key, label in (("materials", "叫料項目數"), ("devices", "設備登載數")):
        arr = cr.get(key)
        if isinstance(arr, list):
            out[label] = len(arr)
    return out


def _diff_flat(before: dict, after: dict):
    """回傳 (before_shown, after_shown)：只留有差異的欄位，兩邊 key 對齊。"""
    keys = sorted(set(before) | set(after))
    b, a = {}, {}
    for k in keys:
        ov, nv = before.get(k), after.get(k)
        if ov == nv:
            continue
        b[k] = "—" if ov in (None, "") else ov
        a[k] = "—" if nv in (None, "") else nv
    return b, a


def _idx_label(payload: dict, noun: str) -> str:
    idx = payload.get("idx")
    return f"{noun} #{idx + 1}" if isinstance(idx, int) and idx >= 0 else noun


def _summarize_case_change(action_type: str, payload: dict, cr: dict,
                           staged_files: list) -> dict:
    """把一筆已結案變更申請整理成簽核人看得懂的 before/after。

    回傳的形狀跟額外支出那條路徑一致（`{label, before, after}`），所以前端
    approval-queue.html 的渲染完全不用改。
    """
    if action_type == "case_record_update":
        new_cr = (payload.get("case_record") or {}) if isinstance(payload, dict) else {}
        before, after = _diff_flat(_flatten_case_record(cr), _flatten_case_record(new_cr))
        if not after:
            return {"label": "核准後會套用的內容",
                    "before": None,
                    "after": {"（無可辨識的欄位變動）":
                              "申請內容與目前案件資料相同，或變動落在不列入比對的欄位"
                              "（案件執行階段由專屬流程處理，不會透過這張申請套用）"}}
        return {"label": "核准後會套用的內容（僅列出有變動的欄位）",
                "before": before, "after": after}

    if action_type == "payment_mark":
        body = (payload.get("body") or {}) if isinstance(payload, dict) else {}
        idx = payload.get("idx")
        items = ((cr.get("payment") or {}).get("items")
                 if isinstance(cr.get("payment"), dict) else []) or []
        cur = items[idx] if isinstance(idx, int) and 0 <= idx < len(items) else {}
        before, after = {}, {}
        for k, lbl in _PAYMENT_ITEM_LABELS.items():
            if k not in body:
                continue
            ov, nv = cur.get(k), body.get(k)
            if k == "received":
                ov = "是" if ov else "否"
                nv = "是" if nv else "否"
            before[lbl] = "—" if ov in (None, "") else ov
            after[lbl] = "—" if nv in (None, "") else nv
        return {"label": f"核准後會套用的內容（{_idx_label(payload, '款項')}）",
                "before": before or None, "after": after or {"（無欄位變動）": "—"}}

    if action_type in ("payment_invoice_upload", "material_file_upload",
                       "material_invoice_upload"):
        noun = {"payment_invoice_upload": "款項",
                "material_file_upload": "叫料項目",
                "material_invoice_upload": "叫料項目"}[action_type]
        what = "發票附件" if "invoice" in action_type else "附件"
        return {"label": "核准後會套用的內容",
                "before": None,
                "after": {"動作": f"於 {_idx_label(payload, noun)} 新增{what}",
                          "檔案數": len(staged_files or []),
                          "檔案": "、".join(
                              (f.get("filename") or "") for f in (staged_files or [])) or "—"}}

    if action_type in ("payment_invoice_delete", "material_file_delete",
                       "material_invoice_delete"):
        noun = "款項" if action_type == "payment_invoice_delete" else "叫料項目"
        what = "發票附件" if "invoice" in action_type else "附件"
        field = ("invoiceFiles" if "invoice" in action_type else "files")
        idx = payload.get("idx")
        arr = (((cr.get("payment") or {}).get("items") or [])
               if action_type == "payment_invoice_delete" else (cr.get("materials") or []))
        name = "—"
        if isinstance(idx, int) and 0 <= idx < len(arr):
            for f in (arr[idx].get(field) or []):
                if f.get("id") == payload.get("file_id"):
                    name = f.get("filename") or f.get("id") or "—"
                    break
        return {"label": "核准後會套用的內容",
                "before": {"目前附件": name},
                "after": {"動作": f"刪除 {_idx_label(payload, noun)} 的{what}",
                          "檔案": name}}

    # 未知類型：不要再倒 raw JSON，至少講清楚這是什麼
    return {"label": "核准後會套用的內容",
            "before": None,
            "after": {"變更類型": action_type,
                      "說明": "這個變更類型還沒有可讀摘要，請開啟案件頁確認後再核准"}}


def _guard_queue_detail(conn, user: dict, quote_no: str, approval_raw=None) -> None:
    """簽核佇列詳情的存取守門（2026-09-14 自動安全掃描後補上）。

    這支端點原本只要求登入——理由是「跟佇列清單一致」。**那個理由站不住腳**：清單
    只有單號／客戶／金額摘要，詳情卻回傳完整內容（明細、附件路徑、變更 payload、
    匯款帳戶），而 `id` 是可預測的單號或小整數。這正是同日模組權限稽核花了一整輪
    收掉的那種 IDOR，不該在新端點上又開一次。

    放行順序（先寬後嚴，因為簽核人往往不是案件的人）：
    1. **這張單據自己的簽核人**（含代理人）——他本來就該看得到要簽的東西，
       而他通常既不是該案業務也不在協作者名單裡
    2. 其餘走一般的每案規則 `_guard_case()`（admin+／該案業務／協作者／案件管理模組），
       案件本身的簽核人也在裡面（allow_approver）
    """
    if approval_raw and _is_case_approver(approval_raw, user, conn):
        return
    _guard_case(conn, quote_no, user, allow_module="case_manage", allow_approver=True)


def _can_see_queue_money(conn, user: dict, approval_raw=None) -> bool:
    """能不能看到這筆的金額。

    規則與憑證流一致（見 `routers/contractor_vouchers.py::_guard_voucher`）：
    `can_see_financial()` 或**本單簽核人**。簽核人例外是必要的——看不到金額就沒辦法
    判斷該不該簽，擋他等於讓簽核流程停擺。
    """
    if can_see_financial(user):
        return True
    return bool(approval_raw and _is_case_approver(approval_raw, user, conn))


_MONEY_LABELS = {"金額", "單價", "小計", "總金額", "存簿封面"}


def _mask_money(out: dict) -> None:
    """沒有財務檢視權時，把金額欄位換成說明字串而不是直接拿掉。

    直接拿掉會讓畫面看起來像「這張單沒有金額」——那比看不到更容易誤判。
    """
    out["fields"] = [
        f if f["label"] not in _MONEY_LABELS
        else {"label": f["label"], "value": "（無財務檢視權限）"}
        for f in out.get("fields") or []
    ]
    masked_items = []
    for it in out.get("items") or []:
        if isinstance(it, dict):
            it = {k: v for k, v in it.items()
                  if k not in ("amount", "subtotal", "unitPrice", "unit_cost", "price", "total")}
        masked_items.append(it)
    out["items"] = masked_items
    out["moneyMasked"] = True


@router.get("/api/approval-queue/detail")
def approval_queue_detail(type: str, id: str, authorization: str = Header(None)):
    """一筆待簽核項目的完整內容：屬於哪個案件、送審了什麼、夾帶哪些檔案、改了什麼。

    權限比照佇列清單本身（登入即可）——**刻意一致**：看得到清單卻點不開內容，
    簽核人就得跑去各模組頁面翻，等於這個佇列白做。真正的動作權限（核准/退回）
    仍由各自的端點把關。
    """
    user = _require_user(authorization)
    conn = get_db()
    try:
        out = {"type": type, "id": id, "title": id, "fields": [], "items": [],
               "files": [], "changes": None, "case": None}
        approval_raw = None

        if type == "completion_note":
            r = conn.execute("SELECT * FROM completion_notes WHERE note_no=?", (id,)).fetchone()
            if not r:
                raise HTTPException(404, "完工單不存在")
            approval_raw = r["data_json"]
            _guard_queue_detail(conn, user, r["quote_no"], approval_raw)
            out["case"] = _case_header(conn, r["quote_no"])
            out["title"] = "完工單 " + r["note_no"]
            out["fields"] = [
                {"label": "服務地點", "value": r["site_address"] or "—"},
                {"label": "執行期間", "value": (r["start_date"] or "—") + " ~ " + (r["completion_date"] or "—")},
                {"label": "負責人", "value": r["site_manager"] or "—"},
                {"label": "客戶驗收人", "value": r["recipient"] or "—"},
                {"label": "保固月數", "value": str(r["warranty_months"] or 0)},
                {"label": "執行說明", "value": r["work_summary"] or "—"},
                {"label": "測試與檢驗", "value": r["test_result"] or "—"},
                {"label": "遺留事項", "value": r["pending_items"] or "—"},
            ]
            try:
                out["items"] = json.loads(r["items_json"] or "[]")
            except Exception:
                out["items"] = []
            out["files"] = _file_entries(r["signed_files_json"])

        elif type == "extra_expense":
            r = conn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (id,)).fetchone()
            if not r:
                raise HTTPException(404, "額外支出不存在")
            approval_raw = r["approval_json"]
            _guard_queue_detail(conn, user, r["quote_no"], approval_raw)
            out["case"] = _case_header(conn, r["quote_no"])
            out["title"] = "額外支出 #" + str(r["id"])
            out["fields"] = [
                {"label": "類別", "value": r["category"] or "—"},
                {"label": "項目", "value": r["description"] or "—"},
                {"label": "數量", "value": (str(r["qty"]) + " " + (r["unit"] or "")).strip()},
                {"label": "單價", "value": format(r["unit_cost"] or 0, ",.0f")},
                {"label": "小計", "value": format(r["total_cost"] or 0, ",.0f")},
                {"label": "支出日期", "value": r["expense_date"] or "—"},
                {"label": "單據號碼", "value": r["doc_no"] or "—"},
                {"label": "支出人", "value": r["payer_name"] or "—"},
                {"label": "填寫人", "value": r["created_by_name"] or "—"},
                {"label": "備註", "value": r["note"] or "—"},
            ]
            out["files"] = _file_entries(r["files_json"])
            # 「編修後的結果」：已核准的額外支出要改內容必須走變更申請，
            # change_json 裡就是改完會變成什麼樣子——簽核人要看的正是這個對照。
            if (r["change_status"] or "") not in ("", "none"):
                try:
                    chg = json.loads(r["change_json"] or "{}")
                except Exception:
                    chg = {}
                if chg:
                    out["changes"] = {
                        "label": "變更申請（核准後會套用的內容）",
                        "before": {"項目": r["description"], "數量": r["qty"],
                                   "單價": r["unit_cost"], "小計": r["total_cost"],
                                   "備註": r["note"]},
                        "after": {"項目": chg.get("description"), "數量": chg.get("qty"),
                                  "單價": chg.get("unit_cost"), "小計": chg.get("total_cost"),
                                  "備註": chg.get("note")},
                        "files": _file_entries(json.dumps(chg.get("files") or [])),
                    }

        elif type == "case_change":
            r = conn.execute("SELECT * FROM case_change_requests WHERE id=?", (id,)).fetchone()
            if not r:
                raise HTTPException(404, "變更申請不存在")
            # 已結案案件的變更申請是單層「任一 superadmin 審核」，沒有 tiers 可比對，
            # 所以只走一般每案規則；申請人本人也看得到自己送出的東西。
            if (r["requested_by"] or "") != user["username"]:
                _guard_queue_detail(conn, user, r["quote_no"], None)
            out["case"] = _case_header(conn, r["quote_no"])
            out["title"] = "已結案案件變更 #" + str(r["id"])
            out["fields"] = [
                {"label": "變更類型", "value": r["action_type"] or "—"},
                {"label": "摘要", "value": r["summary"] or "—"},
                {"label": "申請人", "value": r["requested_by_display"] or r["requested_by"] or "—"},
                {"label": "申請時間", "value": r["requested_at"] or "—"},
            ]
            # 半解鎖期間上傳的檔案是「暫存」的——核准後才會真的掛進案件，
            # 所以簽核人必須在這裡就看得到，不然他是在盲簽。
            out["files"] = _file_entries(r["staged_files_json"])
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except Exception:
                payload = {}
            # 2026-09-14：原本是 `{"after": payload}`——整包 payload_json 丟給前端，
            # 畫面上直接變成一大段 raw JSON（見 _summarize_case_change() 說明）。
            _cr_now = {}
            try:
                _q = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?",
                                   (r["quote_no"],)).fetchone()
                if _q:
                    _cr_now = (json.loads(_q["data_json"] or "{}") or {}).get("caseRecord") or {}
            except Exception:
                _cr_now = {}
            try:
                _staged = json.loads(r["staged_files_json"] or "[]")
            except Exception:
                _staged = []
            out["changes"] = _summarize_case_change(
                r["action_type"] or "", payload, _cr_now, _staged)

        elif type in ("invoice_voucher", "payment_request", "contractor_voucher"):
            table, key = {
                "invoice_voucher":    ("invoice_vouchers", "voucher_no"),
                "payment_request":    ("payment_requests", "request_no"),
                "contractor_voucher": ("contractor_payment_vouchers", "voucher_no"),
            }[type]
            r = conn.execute("SELECT * FROM " + table + " WHERE " + key + "=?", (id,)).fetchone()
            if not r:
                raise HTTPException(404, "單據不存在")
            keys = r.keys()
            approval_raw = r["data_json"] if "data_json" in keys else None
            _guard_queue_detail(conn, user, r["quote_no"], approval_raw)
            out["case"] = _case_header(conn, r["quote_no"])
            try:
                snap = json.loads(r["snapshot_json"] or "{}")
            except Exception:
                snap = {}
            amount = r["amount"] if "amount" in keys and r["amount"] is not None else (snap.get("grandTotal") or 0)
            out["fields"] = [
                {"label": "金額", "value": format(amount or 0, ",.0f")},
                {"label": "範圍", "value": (r["scope"] if "scope" in keys else "") or "—"},
                {"label": "建立者", "value": r["created_by"] or "—"},
                {"label": "建立時間", "value": r["created_at"] or "—"},
            ]
            if "stage" in keys and r["stage"]:
                out["fields"].append({"label": "請款範圍", "value": r["stage"]})
            if snap.get("vendorName"):
                out["fields"].insert(0, {"label": "承攬商", "value": snap["vendorName"]})
            out["items"] = snap.get("items") or []
            files = []
            if "issued_files_json" in keys:
                files += _file_entries(r["issued_files_json"])
            files += _file_entries(json.dumps(snap.get("invoiceFiles") or []))
            passbook = snap.get("bankPassbookImage") or ""
            # 只接受 data:image/ ——這個欄位是建立單據時由前端送進來的字串，
            # 若混進 `javascript:` 之類的 scheme，簽核人點下去就是在本站原點執行腳本
            # （2026-09-14 自動安全掃描 finding #2；前端也擋一次，兩邊都擋）
            if isinstance(passbook, str) and passbook.lower().startswith("data:image/"):
                files.append({"id": "passbook", "name": "存簿封面", "kind": "image",
                              "path": "", "dataUrl": passbook,
                              "uploadedBy": "", "uploadedAt": ""})
            out["files"] = files

        elif type == "shipping_note":
            r = conn.execute("SELECT * FROM shipping_notes WHERE note_no=?", (id,)).fetchone()
            if not r:
                raise HTTPException(404, "出貨單不存在")
            approval_raw = r["data_json"]
            _guard_queue_detail(conn, user, r["quote_no"], approval_raw)
            out["case"] = _case_header(conn, r["quote_no"])
            out["title"] = "出貨單 " + r["note_no"]
            out["fields"] = [
                {"label": "出貨日期", "value": r["ship_date"] or "—"},
                {"label": "收件人", "value": r["recipient"] or "—"},
                {"label": "送貨地址", "value": r["delivery_address"] or "—"},
                {"label": "備註", "value": r["notes"] or "—"},
            ]
            try:
                out["items"] = json.loads(r["items_json"] or "[]")
            except Exception:
                out["items"] = []
            out["files"] = _file_entries(r["signed_files_json"])

        elif type == "quotation":
            r = conn.execute(
                "SELECT quote_no, customer_name, project_name, total, quote_date, sales_person, "
                "data_json, signed_files_json FROM quotations WHERE quote_no=?", (id,)).fetchone()
            if not r:
                raise HTTPException(404, "報價單不存在")
            approval_raw = r["data_json"]
            _guard_queue_detail(conn, user, r["quote_no"], approval_raw)
            out["case"] = _case_header(conn, r["quote_no"])
            out["title"] = "報價單 " + r["quote_no"]
            try:
                d = json.loads(r["data_json"] or "{}")
            except Exception:
                d = {}
            out["fields"] = [
                {"label": "報價日期", "value": r["quote_date"] or "—"},
                {"label": "業務", "value": r["sales_person"] or "—"},
                {"label": "總金額", "value": format(r["total"] or 0, ",.0f")},
                {"label": "付款條件", "value": d.get("paymentTerms") or "—"},
            ]
            out["items"] = d.get("items") or []
            # 🔴 `AT1`：原本只讀 `signed_files_json`——那是**客戶回簽檔**，
            #    待審核階段必然是空的。送件人上傳的附件在 `caseRecord`
            #    裡三處，這支端點從來沒讀過：materials[i].files／
            #    materials[i].invoiceFiles／payment.items[i].invoiceFiles。
            #    ☠️ 而這不只是送件人看不到自己上傳的東西——**簽核人也看
            #    不到**，等於在沒看到憑證的情況下按核准，畫面上又沒有任何
            #    跡象說「有附件但沒顯示」。
            # ⚠️ 修的是讀取端，不碰任何寫入權限——「已核准的額外支出附件
            #    已上鎖」那句話在別的端點，這裡完全不會動到。
            # ⚠️ 檔案不存在時 _file_entries() 本身就不會讓整支端點掛掉
            #    （json 解析失敗回空清單），同 JV5／SP1 的既有做法。
            files = list(_file_entries(r["signed_files_json"]))
            cr = d.get("caseRecord") or {}
            for i, m in enumerate(cr.get("materials") or [], 1):
                if not isinstance(m, dict):
                    continue
                files += _tagged_file_entries(
                    json.dumps(m.get("files") or []), "材料 %d" % i)
                files += _tagged_file_entries(
                    json.dumps(m.get("invoiceFiles") or []), "材料 %d 發票" % i)
            pay_items = (cr.get("payment") or {}).get("items") or []
            for i, p in enumerate(pay_items, 1):
                if not isinstance(p, dict):
                    continue
                files += _tagged_file_entries(
                    json.dumps(p.get("invoiceFiles") or []), "請款 %d" % i)
            out["files"] = files
            # 解鎖編輯後的再簽核：簽核人要知道「這次改了什麼」才簽得下去
            hist = d.get("editHistory") or []
            if isinstance(hist, list) and hist:
                last = hist[-1] if isinstance(hist[-1], dict) else {}
                out["changes"] = {
                    "label": "最近一次編修（第 " + str(last.get("rev", "?")) + " 版）",
                    "after": {"編修人": last.get("byDisplay") or last.get("by"),
                              "時間": last.get("at"), "類型": last.get("type")},
                    "before": None,
                }
        else:
            raise HTTPException(400, "不支援的類型：" + str(type))

        # 金額遮蔽：規則與憑證流一致（見 _can_see_queue_money）
        if not _can_see_queue_money(conn, user, approval_raw):
            _mask_money(out)
            out["files"] = [f for f in out["files"] if f.get("id") != "passbook"]

        return out
    finally:
        conn.close()


# ── 轉簽（2026-09-14 使用者要求）────────────────────────────────────────────
#
# 「簽核代理人，增加最高權限人可以轉簽簽核佇列的內容，要註明原因跟註記這筆簽核」。
#
# 與既有「簽核代理人」（`approval_delegates`）的分工：
#   - 代理人是**事前、長期**的授權（某人請假期間由某人代簽，範圍是那個人的全部簽核）
#   - 轉簽是**事後、單筆**的處置（這一張卡住了，改由另一個人簽）
# 兩者都需要——只有代理人的話，臨時卡單只能等；只有轉簽的話，請假期間每張都要人工轉。
#
# **原因是必填**：轉簽等於把一筆待辦從 A 身上拿走塞給 B，沒有理由就是無從追究的
# 權限變更。原因會寫進單據的 approval.reassignLog、audit_log，並顯示在簽核佇列詳情
# 與簽核歷史裡——三個地方都看得到同一句話。

class ReassignIn(BaseModel):
    type: str
    id: str
    to_username: str
    reason: str
    from_username: Optional[str] = None


_REASSIGN_TABLES = {
    "quotation":          ("quotations", "quote_no"),
    "contractor_voucher": ("contractor_payment_vouchers", "voucher_no"),
    "invoice_voucher":    ("invoice_vouchers", "voucher_no"),
    "payment_request":    ("payment_requests", "request_no"),
    "shipping_note":      ("shipping_notes", "note_no"),
    "completion_note":    ("completion_notes", "note_no"),
    # `JV35`：傳票的簽核存在 `vouchers_all.approval_json`（不是 data_json.approval）
    # ⇒ 讀寫走傳票自己的解析，見 `reassign_approval()` 裡 `is_voucher` 那兩段。
    "voucher":            ("vouchers_all", "voucher_no"),
}


@router.post("/api/approval-queue/reassign")
def reassign_approval(body: ReassignIn, authorization: str = Header(None)):
    """把某一筆待簽核轉給別人（限最高管理者）。

    只動**當層尚未簽核**的那個人：已經簽過的不能被換掉（那會讓簽核紀錄失真），
    後面幾層也不動（那是簽核流程設定的事，不是單筆處置）。

    `extra_expense`／`case_change` 不支援：前者的簽核名單存在自己的欄位、後者是
    單層「任一 superadmin 皆可」本來就不會卡在特定人身上。要支援得各自處理，
    等真的有需求再說——**現在硬做只會多兩條沒人走過的路徑**。
    """
    user = _require_user(authorization, require_superadmin=True)
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫轉簽原因")
    if body.type not in _REASSIGN_TABLES:
        raise HTTPException(400, "此類型不支援轉簽：" + str(body.type))
    to_username = (body.to_username or "").strip()
    if not to_username:
        raise HTTPException(400, "請選擇要轉給誰")

    table, key = _REASSIGN_TABLES[body.type]
    conn = get_db()
    try:
        target = conn.execute(
            "SELECT username, display_name FROM users WHERE username=? AND active=1",
            (to_username,)).fetchone()
        if not target:
            raise HTTPException(404, "找不到該使用者或帳號已停用")

        is_voucher = body.type == "voucher"
        if is_voucher:
            # 📌 `quote_no` 欄位傳票沒有 ⇒ 以單號代入（通知的 ref_label 用它）。
            #    作廢的傳票不算（它的狀態欄可能還停在簽核中）。
            row = conn.execute(
                "SELECT voucher_no AS doc_no, voucher_no AS quote_no, status, approval_json"
                " FROM vouchers_all WHERE voucher_no=? AND COALESCE(voided_at, '')=''",
                (body.id,)).fetchone()
        else:
            row = conn.execute(
                "SELECT " + key + " AS doc_no, quote_no, status, data_json FROM " + table +
                " WHERE " + key + "=?", (body.id,)).fetchone()
        if not row:
            raise HTTPException(404, "單據不存在")
        if (row["status"] or "") not in ("待審核", "簽核中"):
            raise HTTPException(409, "只有待審核／簽核中的單據可以轉簽（目前：" + (row["status"] or "") + "）")

        if is_voucher:
            # 🔴 讀不出來要擋（fail-closed，同 `routers/vouchers.py::_appr_of`），
            #    不可以吞成空鏈——那與「沒有設定流程」一模一樣。
            # 📌 就地 import：本段之外的 import 區不動（並行派工的檔案分界）。
            from helpers.voucher import parse_approval_json, VoucherChainUnreadable
            try:
                appr = parse_approval_json(dict(row))
            except VoucherChainUnreadable:
                raise HTTPException(400, "這張傳票的簽核資料格式不正確，無法轉簽。")
            data = None
        else:
            data = json.loads(row["data_json"] or "{}")
            appr = data.get("approval") or {}
        tiers = _active_tiers(appr)
        if not tiers:
            raise HTTPException(400, "這張單沒有分層簽核資料，無法轉簽")
        ct = _current_tier_idx(appr)
        if ct >= len(tiers):
            raise HTTPException(400, "所有層級都已完成簽核")

        approvers = tiers[ct].get("approvers") or []
        # 指定 from 就換那個人，否則換「當層第一個還沒簽的人」——後者是實務上的
        # 「這張卡在誰身上」，也是佇列畫面顯示的那個人。
        idx = None
        for i, a in enumerate(approvers):
            if a.get("status") == "approved":
                continue
            if body.from_username and a.get("username") != body.from_username:
                continue
            idx = i
            break
        if idx is None:
            raise HTTPException(400, "當層沒有可轉簽的待簽核人員")

        old = approvers[idx]
        if old.get("username") == to_username:
            raise HTTPException(400, "轉簽對象與原簽核人相同")

        now = datetime.now().isoformat()
        actor = user.get("display_name") or user["username"]
        approvers[idx] = {
            **old,
            "username": target["username"],
            "displayName": target["display_name"] or target["username"],
            "status": old.get("status") or "pending",
            # 註記留在這一筆簽核上：簽核佇列詳情與 PDF 都讀得到，不必回頭翻 audit
            "reassignedFrom": old.get("username"),
            "reassignedFromDisplay": old.get("displayName") or old.get("username"),
            "reassignedBy": actor,
            "reassignedAt": now,
            "reassignReason": reason,
        }
        tiers[ct]["approvers"] = approvers
        log = appr.get("reassignLog")
        if not isinstance(log, list):
            log = []
        log.append({"at": now, "by": actor, "tier": ct + 1,
                    "from": old.get("username"), "fromDisplay": old.get("displayName") or old.get("username"),
                    "to": target["username"], "toDisplay": target["display_name"] or target["username"],
                    "reason": reason})
        appr["reassignLog"] = log
        appr["tiers"] = tiers

        if is_voucher:
            conn.execute("UPDATE vouchers_all SET approval_json=?, updated_at=? WHERE voucher_no=?",
                         (json.dumps(appr, ensure_ascii=False), now, body.id))
        elif table == "quotations":
            data["approval"] = appr
            save_quotation_json(conn, row["doc_no"], data)
        else:
            data["approval"] = appr
            conn.execute("UPDATE " + table + " SET data_json=?, updated_at=? WHERE " + key + "=?",
                         (json.dumps(data, ensure_ascii=False), now, body.id))
        conn.commit()
    finally:
        conn.close()

    _audit(_tok(authorization), "approval.reassign", body.type, body.id,
           body.id + "：" + (old.get("displayName") or old.get("username") or "") + " → "
           + (target["display_name"] or target["username"]),
           {"from": old.get("username"), "to": to_username, "reason": reason,
            "tier": ct + 1, "docType": body.type})
    # 被轉到的人要知道自己多了一張要簽的單，否則這張會靜靜卡在他的佇列裡
    _notify(to_username, "approval_request", body.id, row["quote_no"] or body.id,
            actor + " 將「" + body.id + "」的簽核轉給你（原因：" + reason + "）")

    return {"ok": True, "to": to_username,
            "toDisplay": target["display_name"] or target["username"],
            "reason": reason, "tier": ct + 1}


@router.get("/api/approval-history")
def approval_history(month: Optional[str] = None, q: Optional[str] = None,
                     scope: str = "mine", actor: Optional[str] = None,
                     limit: int = 200, offset: int = 0,
                     authorization: str = Header(None)):
    """簽核歷史：回頭看每個月簽核了哪些內容，可搜尋案件與內容（2026-09-14）。

    **建在既有的 `audit_log` 上，不另外開表**——簽核動作本來就每一筆都寫了 audit
    （動作、單號、含客戶名的標籤、備註），再開一張表等於同一件事記兩次，而兩份紀錄
    遲早會對不起來。缺的只是一支查得動的端點。

    `scope`：
      - `mine`（預設）任何人都能看**自己**簽過什麼
      - `all` 限 admin+：整間公司的簽核歷史

    `q` 同時比對單號、標籤（含客戶名）、備註內容與簽核人，這樣「搜尋案件」與
    「搜尋簽核內容」是同一個輸入框——使用者不必先想清楚自己要搜哪一種。
    """
    user = _require_user(authorization)
    if scope == "all" and user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可查看全公司的簽核歷史")
    limit = max(1, min(int(limit or 200), 500))
    offset = max(0, int(offset or 0))

    sql = ("SELECT at, username, display_name, action, target_type, target_id, target_label, detail "
           "FROM audit_log WHERE (action LIKE '%.approve' OR action LIKE '%.reject' "
           "OR action LIKE '%.reject_final' OR action = 'approval.reassign')")
    params: list = []
    if scope != "all":
        sql += " AND username = ?"
        params.append(user["username"])
    elif actor:
        sql += " AND username = ?"
        params.append(actor)
    if month:
        # 格式守門：`int(month[5:7])` 直接吃使用者輸入的話，`?month=2026` 之類的
        # 亂打會是 500（ValueError 冒到框架外），那是伺服器錯誤的顏色，但錯的是請求
        if not re.match(r"^\d{4}-\d{2}$", month[:7]):
            raise HTTPException(400, "month 格式須為 YYYY-MM")
        y, m = int(month[:4]), int(month[5:7])
        if not 1 <= m <= 12:
            raise HTTPException(400, "month 格式須為 YYYY-MM")
        sql += " AND at >= ? AND at < ?"
        params.append(month[:7] + "-01T00:00:00")
        params.append(("%04d-%02d-01T00:00:00" % (y + 1, 1)) if m == 12
                      else ("%04d-%02d-01T00:00:00" % (y, m + 1)))
    if q:
        like = "%" + q.strip() + "%"
        sql += (" AND (target_id LIKE ? OR target_label LIKE ? OR detail LIKE ? "
                "OR username LIKE ? OR display_name LIKE ?)")
        params += [like] * 5
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        # 每月統計：套用除了 `month` 與分頁以外的同一組條件——月份籤是導覽用的，
        # 帶著搜尋字串時它要回答的是「我搜的這個東西出現在哪幾個月」，所以 `q`
        # 要一起套；`month` 本身當然不能套，不然點下去只會剩自己那一格。
        msql = ("SELECT substr(at,1,7) AS ym, COUNT(*) AS c FROM audit_log "
                "WHERE (action LIKE '%.approve' OR action LIKE '%.reject' "
                "OR action LIKE '%.reject_final' OR action = 'approval.reassign')")
        mparams: list = []
        if scope != "all":
            msql += " AND username = ?"
            mparams.append(user["username"])
        elif actor:
            msql += " AND username = ?"
            mparams.append(actor)
        if q:
            msql += (" AND (target_id LIKE ? OR target_label LIKE ? OR detail LIKE ? "
                     "OR username LIKE ? OR display_name LIKE ?)")
            mparams += ["%" + q.strip() + "%"] * 5
        msql += " GROUP BY ym ORDER BY ym DESC LIMIT 24"
        months = [{"month": r["ym"], "count": r["c"]} for r in conn.execute(msql, mparams).fetchall()]
    finally:
        conn.close()

    ACTION_LABELS = {"approve": "核准", "reject": "退回", "reject_final": "拒絕結案",
                     "reassign": "轉簽"}
    items = []
    for r in rows:
        act = (r["action"] or "").split(".")[-1]
        try:
            detail = json.loads(r["detail"] or "{}")
        except Exception:
            detail = {}
        items.append({
            "at": r["at"],
            "username": r["username"],
            "displayName": r["display_name"] or r["username"],
            "action": act,
            "actionLabel": ACTION_LABELS.get(act, act),
            "docType": r["target_type"] or "",
            "docNo": r["target_id"] or "",
            "label": r["target_label"] or "",
            "note": detail.get("note") or detail.get("reason") or "",
            "detail": detail,
        })
    return {"items": items, "months": months, "scope": scope,
            "hasMore": len(items) == limit}
