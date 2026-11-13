"""System: approval-flow settings, notifications, audit log, work logs."""
import threading
import inspect
import json
import logging
import math
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Body, UploadFile, File, Depends, Request
from helpers import idempotency as _idem   # T80c：外勤手機弱訊號重送（選填 Idempotency-Key）
from pydantic import BaseModel, model_validator

from db import get_db, CURRENT_VERSION, _MIGRATIONS
from helpers.auth import has_finance_access, has_cashier_access  # noqa: E402  第42班：財務／出納只認「財務」角色與 superadmin
from helpers import (
    _require_user, _tok, _audit, _get_setting, _set_setting, _get_edge_path,
    _filter_live_notifications, notify_module_activity, APPROVAL_DOC_TYPES, DEFAULT_UNIFIED_DOC_TYPES,
    APPROVAL_DOC_TYPE_LABELS, require_any_module, doc_types_meta)
from helpers.tiered_approval import steps_to_tiers as _steps_to_tiers   # M01-PLAN §3-2：L1
from helpers.uploads import _check_upload_magic
from helpers.errors import trace_id
from photos import _process_project_photo, _photo_root
from helpers.image_guard import ImageRejected, run_decode
from core.txn import write_txn
import trail

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────

class ApprovalFlowApprover(BaseModel):
    # 手動挑人（既有格式）：userId/username/displayName 三個都要有
    # 部門主管自動簽核（2026-08-22g）：sourceType='department_manager' + departmentId
    # 處主管自動簽核（2026-08-22h）：sourceType='division_manager' + divisionId
    # 實際簽核人在送審當下即時解析（見 helpers/tiered_approval.py::resolve_tier_approvers）
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
    # 系統內建「申請人部門主管自動簽核」層開關（2026-08-22i），預設 True——
    # 送審時會在 tiers 最前面自動插入這一層，管理員在設定頁關掉才會存 False。
    # 這一層永遠不會出現在 tiers 陣列裡（只由 helpers/tiered_approval.py 合成），
    # 這裡刻意不接受前端在 tiers 裡塞 sourceType='submitter_manager' 的項目。
    includeSubmitterManagerTier: bool = True


class _SalespersonTarget(BaseModel):
    name:    str   = ''
    revenue: float = 0
    cases:   int   = 0

class _AnnualTarget(BaseModel):
    revenue:         float = 0
    newCases:        int   = 0
    collectionAmount: float = 0
    collectionRate:  float = 0
    avgNetMarginPct: float = 0
    grossProfit:     float = 0

class OperatingTargetsBody(BaseModel):
    year:        int
    annual:      _AnnualTarget          = _AnnualTarget()
    salesperson: List[_SalespersonTarget] = []


def _normalize_flow(raw: dict) -> dict:
    """Convert old {steps:[]} format to new {tiers:[]} format (settings read path).
    NOTE: _active_tiers() in quotations.py handles the active-approval read path separately
    because it must preserve existing status/approvedAt fields.

    Uses key presence ("tiers" in raw), not truthiness (raw.get("tiers")) — a legitimately
    saved empty tier list ([]) is falsy in Python and would otherwise be misrouted through
    the legacy steps-conversion path below (2026-08-28, defensive hardening)."""
    if "tiers" in raw:
        return raw
    return {"tiers": _steps_to_tiers(raw.get("steps") or [])}


# ── Approval flow settings ────────────────────────────────────────────────────

@router.get("/api/settings/approval-flow")
def get_approval_flow_settings(authorization: str = Header(None)):
    """統一簽核設定（2026-08-24 起）：本設定預設套用於報價單／開票申請憑據／出貨單／
    請款單四種單據，取代原本各自獨立的 approval_flow / invoice_voucher_approval_flow /
    shipping_approval_flow 三組設定——舊三組不再讀取，正式機上線後需重新設定一次。

    2026-08-28 起「預設套用」變成可設定：見下方 approval_flow_scope 相關端點，
    管理員可把任一文件類型從這裡切出去、改走自己獨立的 {doc_type}_approval_flow——
    這把 unified_approval_flow key 本身的讀寫方式完全沒變，只是「誰在用它」
    多了一層可設定的間接層。"""
    _require_user(authorization)
    raw = _get_setting("unified_approval_flow", {"tiers": []}) or {}
    return _normalize_flow(raw)


@router.put("/api/settings/approval-flow")
def set_approval_flow_settings(body: ApprovalFlowSettings, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    total_approvers = sum(len(t.approvers) for t in body.tiers)
    value = {
        "tiers": [t.model_dump() for t in body.tiers],
        "includeSubmitterManagerTier": body.includeSubmitterManagerTier,
    }
    _set_setting("unified_approval_flow", value)
    _audit(_tok(authorization), "settings.unified_approval_flow.update", "settings", "unified_approval_flow",
           "統一簽核流程設定（報價單／開票申請憑據／出貨單／請款單）",
           {"tierCount": len(body.tiers), "approverCount": total_approvers,
            "includeSubmitterManagerTier": body.includeSubmitterManagerTier})
    return {"ok": True}


# ── 簽核流程套用範圍（2026-08-28）：五種文件類型可各自勾選要不要走統一流程 ────────
#
# 「編輯」跟「套用」是兩件事，刻意分開：
#   - 編輯：unified_approval_flow／{doc_type}_approval_flow 六把 key 各自永遠可直接
#     讀寫（見下面 get/set_approval_flow_for_doc_type()），跟 scope 設定無關。
#   - 套用：scope 只決定各 router 送審/無簽核層 fallback 那兩處「當下該讀哪把 key」
#     （helpers/tiered_approval.py::approval_flow_setting_key()），本身不影響任何
#     一把 key 的實際內容。
# 這樣「切換」永遠不會弄丟另一邊的既有設定，勾來勾去也不會互相覆蓋。

def _validated_scope(body) -> dict:
    """PUT scope 永遠代表「完整覆蓋」：鍵必須**剛好等於**目前登記的全部單據類型、值必須是布林。
    （原本是固定欄位的 pydantic 模型＋import-time 斷言；單據類型改成可登記後，同一個決定改成在收到請求時查登記表。
    缺欄／多欄／非布林 ⇒ 422，與舊行為一致：殘缺 body 不會被靜默補預設值。）"""
    if not isinstance(body, dict):
        raise HTTPException(422, "套用範圍必須是物件")
    missing = [dt for dt in APPROVAL_DOC_TYPES if dt not in body]
    extra = [k for k in body if k not in APPROVAL_DOC_TYPES]
    if missing or extra:
        raise HTTPException(422, "套用範圍的欄位要與目前的單據類型完全一致（缺：%s／多：%s）"
                            % ("、".join(missing) or "無", "、".join(map(str, extra)) or "無"))
    bad = [dt for dt in APPROVAL_DOC_TYPES if not isinstance(body[dt], bool)]
    if bad:
        raise HTTPException(422, "套用範圍的值必須是布林：%s" % "、".join(bad))
    return {dt: body[dt] for dt in APPROVAL_DOC_TYPES}


@router.get("/api/settings/approval-doc-types")
def get_approval_doc_types(authorization: str = Header(None)):
    """簽核單據類型清單（內建＋模組登記的）——簽核設定頁用。"""
    _require_user(authorization)
    return {"docTypes": doc_types_meta()}


@router.get("/api/settings/approval-flow-scope")
def get_approval_flow_scope(authorization: str = Header(None)):
    _require_user(authorization)
    raw = _get_setting("approval_flow_scope", {}) or {}
    return {dt: raw.get(dt, dt in DEFAULT_UNIFIED_DOC_TYPES) for dt in APPROVAL_DOC_TYPES}


@router.put("/api/settings/approval-flow-scope")
def set_approval_flow_scope(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    new_scope = _validated_scope(body)
    old_scope  = _get_setting("approval_flow_scope", {}) or {}
    unified_flow = _get_setting("unified_approval_flow", {"tiers": []}) or {"tiers": []}
    seeded = []
    for dt, is_unified in new_scope.items():
        was_unified = old_scope.get(dt, dt in DEFAULT_UNIFIED_DOC_TYPES)
        if was_unified and not is_unified:
            # 剛從統一流程勾掉、改成獨立設定：把目前統一流程的內容複製一份當起點，
            # 避免行為在切換的當下突然改變（使用者 2026-08-28 討論時選定的預設）。
            #
            # ⚠️ 只在該類型自己的 key 目前是空的（從沒設定過，或這輪之前從沒獨立過）
            # 時才複製——2026-08-28 code review 抓到：若不加這個判斷，反覆切換
            # 統一/獨立（例如透過 contractor_vouchers.py 仍保留的專屬設定頁面先手動
            # 設定好一份 tiers，之後切成統一、再切回獨立）會讓這裡無條件覆蓋，
            # 悄悄洗掉先前已經設定好的獨立內容。
            existing = _get_setting(f"{dt}_approval_flow", {"tiers": []}) or {"tiers": []}
            if not (existing.get("tiers") or []):
                _set_setting(f"{dt}_approval_flow", unified_flow)
                seeded.append(dt)
    _set_setting("approval_flow_scope", new_scope)
    _audit(_tok(authorization), "settings.approval_flow_scope.update", "settings", "approval_flow_scope",
           "簽核流程套用範圍設定", {"scope": new_scope, "seededFromUnified": seeded})
    return {"ok": True, "seededFromUnified": seeded}


@router.get("/api/settings/approval-flow/{doc_type}")
def get_approval_flow_for_doc_type(doc_type: str, authorization: str = Header(None)):
    """獨立設定專用：不管 scope 目前怎麼設，永遠直接讀該文件類型自己的
    {doc_type}_approval_flow key（跟 unified_approval_flow 分開存放）。"""
    _require_user(authorization)
    if doc_type not in APPROVAL_DOC_TYPES:
        raise HTTPException(404, f"不支援的文件類型：{doc_type}")
    raw = _get_setting(f"{doc_type}_approval_flow", {"tiers": []}) or {}
    return _normalize_flow(raw)


@router.put("/api/settings/approval-flow/{doc_type}")
def set_approval_flow_for_doc_type(doc_type: str, body: ApprovalFlowSettings, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    if doc_type not in APPROVAL_DOC_TYPES:
        raise HTTPException(404, f"不支援的文件類型：{doc_type}")
    total_approvers = sum(len(t.approvers) for t in body.tiers)
    value = {
        "tiers": [t.model_dump() for t in body.tiers],
        "includeSubmitterManagerTier": body.includeSubmitterManagerTier,
    }
    key = f"{doc_type}_approval_flow"
    _set_setting(key, value)
    label = APPROVAL_DOC_TYPE_LABELS.get(doc_type, doc_type)
    _audit(_tok(authorization), f"settings.{key}.update", "settings", key,
           f"{label}獨立簽核流程設定",
           {"tierCount": len(body.tiers), "approverCount": total_approvers,
            "includeSubmitterManagerTier": body.includeSubmitterManagerTier})
    return {"ok": True}


# ── Operating targets ─────────────────────────────────────────────────────────

@router.get("/api/settings/operating-targets")
def get_operating_targets(authorization: str = Header(None)):
    u = _require_user(authorization)
    if not has_finance_access(u):                 # 第42班：年度營運目標含營收／毛利目標 ＝ 財務金額
        raise HTTPException(403, "僅財務角色可查閱年度目標")
    return _get_setting("operating_targets") or {}


@router.put("/api/settings/operating-targets")
def put_operating_targets(body: OperatingTargetsBody, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    try:
        old = _get_setting("operating_targets") or {}    # §15：存檔後要通知「誰改了什麼、舊→新」，所以寫入前先記下目前值；讀不到不能害儲存失敗
    except Exception:                                    # noqa: BLE001
        old = None
        logger.warning("年度營運目標：讀不到舊值，這次儲存不發通知", exc_info=True)
    new = body.model_dump()
    _set_setting("operating_targets", new)
    _audit(_tok(authorization), "settings.operating_targets.update", "settings",
           "operating_targets", f"{body.year} 年度目標",
           {"year": body.year, "changedBy": user.get("display_name") or user["username"]})
    _notify_operating_targets_changed(old, new, user["username"])
    return {"ok": True}


_TARGET_ANNUAL_LABELS = (("revenue", "營收目標", "元"), ("newCases", "新成案數", "件"), ("collectionAmount", "收款金額", "元"),
                         ("collectionRate", "收款率", "%"), ("avgNetMarginPct", "平均營業利益率", "%"), ("grossProfit", "毛利目標", "元"))


def _target_num(v, unit):
    try:
        v = float(v or 0)
        if not math.isfinite(v):
            v = 0.0
    except (TypeError, ValueError):
        v = 0.0
    return ("{:,.0f}" if v == int(v) else "{:,.2f}").format(v) + (" " + unit if unit == "元" else unit)


def _notify_operating_targets_changed(old, new, actor):
    """SPEC §15-3：年度營運目標維持立即生效，**存檔後**發通知（最高管理者全部＋財務；一次存檔多欄合併成一則）。
    整份覆蓋、一次只存一年：年度不同＝換了一年的目標，舊年度的數字不拿來逐欄比，只告知年度換了。永不丟例外。"""
    try:
        if old is None:                                                # 寫入前讀不到舊值 ⇒ 不知道改了什麼，不發
            return
        from helpers import settings_notify as SN
        old = old if isinstance(old, dict) else {}
        oy, ny = old.get("year"), new.get("year")
        same_year = oy == ny
        oa = (old.get("annual") or {}) if same_year else {}
        na = new.get("annual") or {}
        rows = []
        if not same_year:
            rows.append(("年度營運目標／目標年度", ("%s 年度" % oy) if oy else "（尚未設定）", "%s 年度" % ny))
        for k, lb, unit in _TARGET_ANNUAL_LABELS:
            if (oa.get(k) or 0) != (na.get(k) or 0) or (not same_year and (na.get(k) or 0) != 0):
                rows.append(("年度營運目標／%s" % lb, _target_num(oa.get(k), unit), _target_num(na.get(k), unit)))
        osp = [(x.get("name"), x.get("revenue"), x.get("cases")) for x in (old.get("salesperson") or [])]
        nsp = [(x.get("name"), x.get("revenue"), x.get("cases")) for x in (new.get("salesperson") or [])]
        if not same_year:
            if osp or nsp:                                             # 換年度：只告知人數（顯示舊年度實際人數），不逐人比
                rows.append(("年度營運目標／業務員配額", "%d 位" % len(osp), "%d 位" % len(nsp)))
        elif osp != nsp:
            n_o, n_n = "%d 位" % len(osp), "%d 位" % len(nsp)
            rows.append(("年度營運目標／業務員配額", n_o, n_n if len(osp) != len(nsp) else n_n + "（內容已調整）"))
        if not rows:
            return
        with SN.batch():
            for label, o, n in rows:
                SN.notify_change("ops_target", label, o, n, actor=actor, risk="ops", roles=("財務",), link="reports.html")
    except Exception:                                                  # noqa: BLE001
        logger.warning("年度營運目標變更通知失敗（設定已存好）", exc_info=True)


# ── Monthly report recipients（2026-08-27，取代原本寫死只寄 superadmin 的規則）────

class MonthlyReportRecipientsBody(BaseModel):
    userIds: List[int] = []


@router.get("/api/settings/monthly-report-recipients")
def get_monthly_report_recipients(authorization: str = Header(None)):
    _require_user(authorization)
    return _get_setting("monthly_report_recipients") or {"userIds": []}


@router.put("/api/settings/monthly-report-recipients")
def put_monthly_report_recipients(body: MonthlyReportRecipientsBody, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    _set_setting("monthly_report_recipients", body.model_dump())
    _audit(_tok(authorization), "settings.monthly_report_recipients.update", "settings",
           "monthly_report_recipients", f"{len(body.userIds)} 位收件人",
           {"userIds": body.userIds, "changedBy": user.get("display_name") or user["username"]})
    return {"ok": True}


# ── Notifications ─────────────────────────────────────────────────────────────

@router.get("/api/notifications/mine")
def get_my_notifications(authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, type, ref_id, ref_label, message, is_read, created_at, link "
        "FROM notifications WHERE username=? ORDER BY created_at DESC LIMIT 50",
        (user["username"],)
    ).fetchall()
    rows = _filter_live_notifications(conn, rows)
    conn.close()
    items = [dict(r) for r in rows]
    unread = sum(1 for i in items if not i["is_read"])
    return {"items": items, "unread": unread}


@router.patch("/api/notifications/{notif_id}/read")
def mark_notification_read(notif_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET is_read=1 WHERE id=? AND username=?",
        (notif_id, user["username"])
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.patch("/api/notifications/read-all")
def mark_all_notifications_read(authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET is_read=1 WHERE username=?",
        (user["username"],)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Audit log ─────────────────────────────────────────────────────────────────

# 2026-09-24（B7）：兩張表移到 `helpers/module_registry.py`（唯一來源），名稱保留給既有呼叫端。
from helpers.module_registry import BADGE_PREFIXES as _MODULE_ACTION_PREFIXES  # noqa: E402
from helpers.module_registry import refuse_unknown_new_keys  # noqa: E402
from helpers.module_registry import BADGE_EXCLUDE as _MODULE_EXCLUDE_ACTIONS  # noqa: E402
from helpers.audit import _MODULE_LABELS as _AUDIT_MODULE_LABELS  # noqa: E402
from helpers.audit import _FAIL_REASON_LABELS as _AUDIT_FAIL_LABELS  # noqa: E402


def _audit_counts_since(since_ts: str) -> str:
    """module-counts 的 `since`（ISO 字串）不可早於今天往前 `_AUDIT_COUNTS_MAX_DAYS` 天（更早的一律當作那一天）。"""
    from datetime import datetime, timedelta
    floor = (datetime.now() - timedelta(days=_AUDIT_COUNTS_MAX_DAYS)).isoformat()
    return since_ts if since_ts >= floor else floor


@router.post("/api/audit-log/module-counts")
def audit_module_counts(body: dict = Body(...), authorization: str = Header(None)):
    """Return per-module count of audit_log entries after given timestamps, excluding the caller's own actions."""
    user = _require_user(authorization)
    # 安全審查 W3（2026-09-30）：這支直接數 audit_log，原本只要求登入 ⇒ 與歷史紀錄頁同一個權限（模組 audit_log）。
    # 舊端點，前端已改用 /api/reads/module-counts，沒有活的呼叫端。
    require_any_module(user, ["audit_log"], "操作紀錄")
    modules_since = (body.get("modules") or {}) if isinstance(body, dict) else {}
    if not isinstance(modules_since, dict) or not modules_since:
        return {}
    for _k, _ts in modules_since.items():                      # 非字串（數字、物件…）原本進 SQL 參數 ⇒ 500
        if _ts is not None and not isinstance(_ts, str):
            raise HTTPException(400, "since 時間必須是字串（ISO 格式）")
    conn = get_db()
    result = {}
    try:
        for mod_key, since_ts in modules_since.items():
            prefixes = _MODULE_ACTION_PREFIXES.get(mod_key)
            if not prefixes or not since_ts:
                result[mod_key] = 0
                continue
            # 前綴比對改「範圍」（action >= 前綴 AND action < 前綴+1）：LIKE 前綴在預設大小寫不敏感下用不到索引（百萬列 11 秒）
            conds = " OR ".join("(action >= ? AND action < ?)" for _ in prefixes)
            params = [x for p in prefixes for x in (p, p[:-1] + chr(ord(p[-1]) + 1))]
            since_ts = _audit_counts_since(since_ts)                # 最多往前 90 天：避免無界掃描
            params += [since_ts, user["username"]]
            excl = _MODULE_EXCLUDE_ACTIONS.get(mod_key, ())
            if excl:
                excl_ph = ", ".join("?" for _ in excl)
                sql = (f"SELECT COUNT(*) FROM audit_log "
                       f"WHERE ({conds}) AND at > ? AND username != ? "
                       f"AND action NOT IN ({excl_ph})")
                params = params + list(excl)
            else:
                sql = (f"SELECT COUNT(*) FROM audit_log "
                       f"WHERE ({conds}) AND at > ? AND username != ?")
            count = conn.execute(sql, params).fetchone()[0]
            result[mod_key] = count
    finally:
        conn.close()
    return result


#: 安全審查 W3 #5（2026-09-30）：歷史紀錄搜尋的輸入上限與成本上限
_AUDIT_TEXT_MAX = 100          # 每個文字篩選值最多 100 字（超過截斷，不報錯）
_AUDIT_OFFSET_MAX = 10000      # 舊的 offset 分頁最多跳 1 萬列（＝總數上限）；更深請用 before_id（keyset）
_AUDIT_COUNT_CAP = 10000       # 「總數」最多數到 1 萬（超過回 10000＋totalCapped），不對全表 COUNT(*)
_AUDIT_TREE_DEFAULT_DAYS = 90  # 分層樹沒給日期 ⇒ 預設看近 90 天（百萬列時無日期的 GROUP BY 要 10 秒以上）
_AUDIT_TREE_MAX_DAYS = 366     # 分層樹的時間窗最長 366 天；超過就截成最近 366 天並在回應標 clamped
_AUDIT_COUNTS_MAX_DAYS = 90    # module-counts 的 since 最多往前 90 天


def _like_escape(s: str) -> str:
    """LIKE 的跳脫：使用者輸入的 %、_、反斜線當字面值（否則 `q=%%%%…` 會變成全表掃描的萬用字元炸彈）。搭配 ESCAPE 子句。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


#: 稽核標籤（簽核二擇一 S6）：標籤 → 只會出現在哪個 action。寫入端是 `modules/case/api/quotations.py`（approve 選維持＝informed；review-edit 自改自簽＝self_edit_sign），
#: detail 內的字面是 `"tag": "<標籤>"`；字面約定由 case 模組測試鎖住。routers 不 import 模組，所以常數放這裡。
_AUDIT_TAGS = {"informed": "quotation.approve", "self_edit_sign": "quotation.review_edit"}


def _audit_filters(module, case_no, ref_no, user_q, action, date_from, date_to, result, q, tag=None):
    """歷史紀錄的共用篩選（列表、樹、失敗摘要同一套）。除 q（相容舊版的關鍵字）外都走索引：精確／前綴，不用 %x%。
    文字值一律截到 `_AUDIT_TEXT_MAX`；LIKE 的萬用字元一律跳脫（安全審查 W3 #5）。"""
    mx = _AUDIT_TEXT_MAX
    module, case_no, ref_no, user_q, action, q = [
        (v[:mx] if isinstance(v, str) else v) for v in (module, case_no, ref_no, user_q, action, q)]
    date_from, date_to = [(v[:32] if isinstance(v, str) else v) for v in (date_from, date_to)]
    where, params = [], []
    if module:
        where.append("module=?");        params.append("" if module == "other" else module)
    if case_no:
        where.append("case_no=?");       params.append(case_no.strip())
    if ref_no:
        where.append("ref_no=?");        params.append(ref_no.strip())
    if user_q:
        u = user_q.strip()
        where.append("(username=? OR display_name=? OR username LIKE ? ESCAPE '\\' OR display_name LIKE ? ESCAPE '\\')")
        params.extend([u, u, _like_escape(u) + "%", _like_escape(u) + "%"])
    if action:
        where.append("action=?");        params.append(action)
    if date_from:
        where.append("at>=?");           params.append(date_from)
    if date_to:
        where.append("at<?");            params.append(date_to + "T99" if len(date_to) == 10 else date_to)
    if result in ("ok", "fail"):
        where.append("result=?");        params.append(result)
    if tag:                                    # S6：稽核標籤（知情核准／自改自簽）＝固定 action（走索引）＋ detail 的 "tag" 字面比對；不認得的標籤 ⇒ 400，不靜默忽略
        t = str(tag)[:mx]
        if t not in _AUDIT_TAGS:
            raise HTTPException(400, "tag 只能是 " + "／".join(_AUDIT_TAGS))
        where.append("action=?");              params.append(_AUDIT_TAGS[t])
        where.append("detail LIKE ? ESCAPE '\\'");  params.append("%" + _like_escape('"tag": "%s"' % t) + "%")
    if q:
        like = "%" + _like_escape(q) + "%"
        where.append("(target_label LIKE ? ESCAPE '\\' OR username LIKE ? ESCAPE '\\'"
                     " OR display_name LIKE ? ESCAPE '\\' OR target_id LIKE ? ESCAPE '\\')")
        params.extend([like, like, like, like])
    return where, params


def _require_audit_view(authorization):
    # 2026-09-14 使用者裁示：這頁原本沒有對應的模組 key，只能靠角色寫死（`admin` 以上）。
    # 建了 key（`audit_log`）後跟其他模組一樣可逐帳號勾選；列表、樹、失敗摘要同一個權限。
    user = _require_user(authorization)
    require_any_module(user, ["audit_log"], "操作紀錄")
    return user


@router.get("/api/audit-log")
def list_audit_log(
    limit:  int = 100,
    offset: int = 0,
    action: str = None,
    q:      str = None,
    module: str = None,
    case_no: str = None,
    ref_no: str = None,
    user:   str = None,
    date_from: str = None,
    date_to: str = None,
    result: str = None,
    before_id: int = None,
    tag: str = None,
    authorization: str = Header(None),
):
    """使用者 2026-09-30：「人員的紀錄或是操作紀錄可以分層依模組、案件等搜尋，或是紀錄中有失敗能快速查詢」。
    分頁：`before_id`（keyset，走索引，深頁不掃描）；舊的 `offset` 仍可用。`limit` 上限 200。"""
    _require_audit_view(authorization)
    limit = max(1, min(int(limit), 200))
    conn = get_db()
    try:
        where, params = _audit_filters(module, case_no, ref_no, user, action, date_from, date_to, result, q, tag)
        cond = ("WHERE " + " AND ".join(where)) if where else ""
        # 總數只數到 _AUDIT_COUNT_CAP（帶索引的篩選很快；無篩選時不對百萬列做 COUNT(*)）
        total = conn.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM audit_log {cond} LIMIT {_AUDIT_COUNT_CAP})", params).fetchone()[0]
        w2, p2 = list(where), list(params)
        if before_id:
            w2.append("id<?");           p2.append(int(before_id))
        cond2 = ("WHERE " + " AND ".join(w2)) if w2 else ""
        rows = conn.execute(
            f"SELECT * FROM audit_log {cond2} ORDER BY id DESC LIMIT ? OFFSET ?",
            p2 + [limit, 0 if before_id else max(0, min(int(offset), _AUDIT_OFFSET_MAX))]
        ).fetchall()
    finally:
        conn.close()
    items = [dict(r) for r in rows]
    for it in items:
        it["module_label"] = _AUDIT_MODULE_LABELS.get(it.get("module") or "", it.get("module") or "其他")
        it["reason_label"] = _AUDIT_FAIL_LABELS.get(it.get("reason_code") or "", "")
    return {"total": total, "totalCapped": total >= _AUDIT_COUNT_CAP, "items": items,
            "next_before_id": items[-1]["id"] if len(items) == limit else None}


def _audit_tree_window(date_from, date_to):
    """分層樹的時間窗（YYYY-MM-DD，含頭尾）：沒給日期 ⇒ 近 `_AUDIT_TREE_DEFAULT_DAYS` 天；日期格式錯 ⇒ 400；
    跨度超過 `_AUDIT_TREE_MAX_DAYS` ⇒ 只取最近那段並 `clamped: true`（畫面據此提示「已縮到上限」）。"""
    from datetime import date, timedelta
    def _d(v, name):
        try:
            return date.fromisoformat((v or "")[:10])
        except ValueError:
            raise HTTPException(400, "%s 格式錯誤，需為 YYYY-MM-DD" % name)
    end = _d(date_to, "date_to") if date_to else date.today()
    start = _d(date_from, "date_from") if date_from else end - timedelta(days=_AUDIT_TREE_DEFAULT_DAYS)
    if start > end:
        raise HTTPException(400, "date_from 不可晚於 date_to")
    clamped = (end - start).days > _AUDIT_TREE_MAX_DAYS
    if clamped:
        start = end - timedelta(days=_AUDIT_TREE_MAX_DAYS)
    return {"from": start.isoformat(), "to": end.isoformat(), "defaultDays": _AUDIT_TREE_DEFAULT_DAYS,
            "maxDays": _AUDIT_TREE_MAX_DAYS, "clamped": clamped, "defaulted": not (date_from or date_to)}


@router.get("/api/audit-log/tree")
def audit_log_tree(
    level: str = "module",
    module: str = None,
    case_no: str = None,
    ref_no: str = None,
    user:   str = None,
    action: str = None,
    date_from: str = None,
    date_to: str = None,
    result: str = None,
    tag: str = None,
    authorization: str = Header(None),
):
    """分層下鑽：module（模組）→ case（案件，需 module）→ ref（單據，需 module／case_no）。每層回
    `[{key, label, count, failCount, lastAt}]`；事件層用 `GET /api/audit-log` 帶同一組篩選。"""
    _require_audit_view(authorization)
    col = {"module": "module", "case": "case_no", "ref": "ref_no"}.get(level)
    if col is None:
        raise HTTPException(400, "level 只能是 module／case／ref")
    window = _audit_tree_window(date_from, date_to)
    conn = get_db()
    try:
        where, params = _audit_filters(module, case_no, ref_no, user, action, window["from"], window["to"], result, None, tag)
        # 加一個 **id 範圍**收窄掃描：`at` 條件單獨會讓 SQLite 走 idx_audit_at 再逐列回表（100 萬列 1.7～4.7 秒）。
        # id 上下界各一次索引查詢取得：窗內每一列的 id 必定落在 [MIN(id where at>=起), MAX(id where at<迄)] 之內（與資料是否依時間遞增無關），
        # `at` 條件仍保留 ⇒ 結果恆正確；稽核列依寫入順序遞增（正式機如此）時掃描量就是窗內那一段，不是全表。
        lo = conn.execute("SELECT MIN(id) FROM audit_log WHERE at >= ?", (window["from"],)).fetchone()[0]
        hi = conn.execute("SELECT MAX(id) FROM audit_log WHERE at < ?", (window["to"] + "T99",)).fetchone()[0]
        if lo is None or hi is None or lo > hi:
            return {"level": level, "items": [], "window": window}
        where += ["id>=?", "id<=?"]
        params += [lo, hi]
        cond = ("WHERE " + " AND ".join(where)) if where else ""
        rows = conn.execute(
            f"SELECT {col} AS k, COUNT(*) AS n, SUM(result='fail') AS f, MAX(id) AS last_id "
            f"FROM audit_log {cond} GROUP BY {col} ORDER BY MAX(id) DESC LIMIT 500", params).fetchall()
        last_at = {r["last_id"]: (conn.execute("SELECT at FROM audit_log WHERE id=?", (r["last_id"],)).fetchone() or [None])[0]
                   for r in rows}
    finally:
        conn.close()
    out = []
    for r in rows:
        k = r["k"] or ""
        label = (_AUDIT_MODULE_LABELS.get(k, k) if level == "module" else k) or "其他"
        out.append({"key": k or ("other" if level == "module" else ""), "label": label, "count": r["n"],
                    "failCount": r["f"] or 0, "lastAt": last_at.get(r["last_id"])})
    return {"level": level, "items": out, "window": window}


@router.get("/api/audit-log/failures/summary")
def audit_log_failure_summary(date_from: str = None, date_to: str = None, authorization: str = Header(None)):
    """失敗紀錄摘要：總數＋原因碼／模組／人員前 10。"""
    _require_audit_view(authorization)
    conn = get_db()
    try:
        where, params = _audit_filters(None, None, None, None, None, date_from, date_to, "fail", None)
        cond = "WHERE " + " AND ".join(where)

        def top(col, n=10):
            return conn.execute(
                f"SELECT {col} AS k, COUNT(*) AS n FROM audit_log {cond} GROUP BY {col} ORDER BY n DESC LIMIT {n}",
                params).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM audit_log {cond}", params).fetchone()[0]
        reasons, mods, users = top("reason_code"), top("module"), top("username")
    finally:
        conn.close()
    return {
        "total": total,
        "byReason": [{"key": r["k"], "label": _AUDIT_FAIL_LABELS.get(r["k"], r["k"] or "其他"), "count": r["n"]} for r in reasons],
        "byModule": [{"key": r["k"] or "other", "label": _AUDIT_MODULE_LABELS.get(r["k"], r["k"]) or "其他", "count": r["n"]} for r in mods],
        "byUser": [{"key": r["k"], "label": r["k"] or "（未登入）", "count": r["n"]} for r in users],
    }


# ── Work Logs ─────────────────────────────────────────────────────────────────

@router.get("/api/work-logs")
def list_work_logs(
    date:     Optional[str] = None,
    month:    Optional[str] = None,
    user_id:  Optional[int] = None,
    case_no:  Optional[str] = None,
    authorization: str = Header(None),
):
    user = _require_user(authorization)
    require_any_module(user, ('work_log', 'case_manage'), "工作日誌")
    conn = get_db()
    sql = """
        SELECT w.id, w.log_date, w.user_id, w.content, w.hours, w.created_at,
               w.case_no, w.photos, w.contact_type, u.display_name, u.username
        FROM work_logs w
        LEFT JOIN users u ON u.id = w.user_id
        WHERE 1=1
    """
    params = []
    if date:
        sql += " AND w.log_date = ?"
        params.append(date)
    elif month:
        sql += " AND w.log_date LIKE ?"
        params.append(month + "-%")
    if user_id:
        sql += " AND w.user_id = ?"
        params.append(user_id)
    if case_no:
        sql += " AND w.case_no = ?"
        params.append(case_no)
    sql += " ORDER BY w.log_date DESC, w.id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["photos"] = json.loads(d.get("photos") or "[]")
        result.append(d)
    return result


def _worklog_case_on() -> bool:
    """onepipe P0b 旗標：工作日誌可選案件。預設關；任何讀取錯誤 ⇒ 當作關（關＝與今天逐位元相同）。"""
    from helpers import onepipe_flags                  # 以模組引用（測試以 monkeypatch `helpers.onepipe_flags.flag_on` 換掉）
    return onepipe_flags.flag_on("worklog_case")       # 讀不到／群組沒登錄 ⇒ 關


def _worklog_case_guard(case_no: str, user: dict) -> None:
    """旗標開時，日誌要掛的案件必須是「這個人看得到該案動態」的案件（`guard_case_access`，與 `GET /api/quotations/{no}/updates` 同一條規則）。
    看不到＝不存在：一律 404、稽核另記真正原因（M01-O1）。"""
    from helpers.case_access import guard_case_access
    conn = get_db()
    try:
        guard_case_access(conn, case_no, user, allow_module="case_manage")
    finally:
        conn.close()                                   # 拒絕時 guard 已關過一次，再關一次無害


@router.get("/api/work-logs/case-options")
def work_log_case_options(q: str = "", authorization: str = Header(None)):
    """P0b：工作日誌「關聯案件」選單的資料（只有案號／客戶／案名；進行中的案件、這個人看得到動態的才列；最多 30 筆，`q` 搜尋）。
    旗標 `onepipe.worklog_case` 關（預設）⇒ 404，與這支路由不存在時逐字相同。"""
    user = _require_user(authorization)
    require_any_module(user, ('work_log', 'case_manage'), "工作日誌")
    if not _worklog_case_on():
        raise HTTPException(404, "Not Found")
    from helpers.case_access import attachable_cases
    conn = get_db()
    try:
        return {"items": attachable_cases(conn, user, (q or "")[:60])}
    finally:
        conn.close()


def _work_log_fields(conn, body: dict, keys) -> dict:
    """工作日誌欄位的型別與範圍檢查（W1c 稽核）：原本 `float("abc")`、`.strip()` 打在非字串、不存在的 user_id 都是 500 或寫進壞資料；
    現在一律 422。只檢查 `keys` 裡且有帶的欄位；回傳正規化後的值（日期 YYYY-MM-DD、時數 float、user_id int、文字去頭尾空白）。"""
    from helpers.dates import normalize_date
    out = {}
    if "log_date" in keys and "log_date" in body:
        v = body["log_date"]
        if not isinstance(v, str) or not v.strip():
            raise HTTPException(422, "日期格式不正確，需為 YYYY-MM-DD")
        out["log_date"] = normalize_date(v, "日期")
    if "user_id" in keys and "user_id" in body:
        v = body["user_id"]
        if isinstance(v, bool) or not isinstance(v, (int, str)) or not str(v).strip().lstrip("-").isdigit():
            raise HTTPException(422, "人員格式不正確")
        v = int(v)
        if conn.execute("SELECT 1 FROM users WHERE id=?", (v,)).fetchone() is None:
            raise HTTPException(422, "找不到這位人員")
        out["user_id"] = v
    if "content" in keys and "content" in body:
        v = body["content"]
        if not isinstance(v, str) or not v.strip():
            raise HTTPException(422, "請填寫工作內容")
        out["content"] = v.strip()
    if "hours" in keys and "hours" in body:
        v = body["hours"]
        try:
            h = float(v) if not isinstance(v, bool) and isinstance(v, (int, float, str)) else None
        except ValueError:
            h = None
        if h is None or h != h or h in (float("inf"), float("-inf")) or h < 0 or h > 1000:
            raise HTTPException(422, "時數必須是 0～1000 的數字")
        out["hours"] = h
    for k in ("case_no", "contact_type"):
        if k in keys and k in body:
            v = body[k]
            if v is not None and not isinstance(v, str):
                raise HTTPException(422, "%s 必須是文字" % k)
            out[k] = (v or "").strip()
    return out


@router.post("/api/work-logs")
def create_work_log(body: dict = Body(...), authorization: str = Header(None), idempotency_key: str = Header(None)):
    """建立工作日誌（選填標頭 `Idempotency-Key`：弱訊號重送不重複建立，見 helpers/idempotency.py；沒帶＝行為不變）。"""
    u = _require_user(authorization)
    key = _idem.parse_key(idempotency_key)
    return _idem.run_sync(u["username"], key, "POST work_log", _idem.request_hash(body),
                          lambda: _create_work_log_impl(body, authorization, u))


def _create_work_log_impl(body, authorization, u):
    require_any_module(u, ('work_log', 'case_manage'), "工作日誌")      # 第49班 W1c-P5：與 GET 同一把（原本寫入只要登入）
    _ct = body.get("content")
    if not body.get("log_date") or not body.get("user_id") or not (_ct.strip() if isinstance(_ct, str) else _ct):
        raise HTTPException(400, "請填寫日期、記錄對象與工作內容。")
    _c = get_db()
    try:
        _f = _work_log_fields(_c, body, ("log_date", "user_id", "content", "hours", "case_no", "contact_type"))
    finally:
        _c.close()
    log_date, user_id, content = _f["log_date"], _f["user_id"], _f["content"]
    if user_id != u["id"] and u["role"] != "superadmin":              # 第 52 班（使用者裁示）：建立時也只有最高管理者能指定別人為記錄對象（同值＝自己 OK；與 PUT 的『不得改記錄對象』對稱）
        raise HTTPException(403, "只有最高管理者可以替其他人建立工作日誌")
    hours    = _f.get("hours", 8.0)
    case_no  = _f.get("case_no", "")
    contact_type = _f.get("contact_type", "")
    if case_no and _worklog_case_on():                  # P0b：旗標開 ⇒ 只能掛自己看得到動態的案件（關＝今天的行為，不檢查）
        _worklog_case_guard(case_no, u)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO work_logs (log_date, user_id, content, hours, created_at, created_by, case_no, contact_type) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (log_date, user_id, content, hours, now, u["id"], case_no, contact_type)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    notify_module_activity("工作日誌", "建立", u.get("display_name") or u["username"],
                            log_date, "work-log.html", detail=content)
    _audit(_tok(authorization), 'work_log.create', 'work_log', str(new_id), log_date)
    return {"id": new_id, "ok": True}


@router.put("/api/work-logs/{wid}")
def update_work_log(wid: int, body: dict = Body(...), authorization: str = Header(None)):
    u = _require_user(authorization)
    require_any_module(u, ('work_log', 'case_manage'), "工作日誌")      # 第49班 W1c-P5
    conn = get_db()
    row = conn.execute("SELECT * FROM work_logs WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到日誌")
    if u["role"] not in ("superadmin", "admin") and u["id"] != row["user_id"]:
        conn.close()
        raise HTTPException(403, "只能修改自己的工作日誌")
    sets, params = [], []
    try:
        _f = _work_log_fields(conn, body, ("log_date", "user_id", "content", "hours", "case_no", "contact_type"))
    except HTTPException:
        conn.close()
        raise
    if _f.get("case_no") and _f["case_no"] != (row["case_no"] or "") and _worklog_case_on():
        conn.close()                                                    # P0b：改掛到別的案件才檢查（清空、原樣不動都不擋）；旗標關＝今天的行為
        _worklog_case_guard(_f["case_no"], u)
        conn = get_db()
    if "user_id" in _f and _f["user_id"] != row["user_id"] and u["role"] != "superadmin":
        conn.close()                                                    # 第49班 W1c-P5：記錄對象只有最高管理者能改（本人／管理員不能把日誌轉給別人）
        raise HTTPException(403, "只有最高管理者可以更改工作日誌的人員")
    for field in ("log_date", "user_id", "content", "hours", "case_no", "contact_type"):
        if field in _f:
            sets.append(f"{field}=?")
            params.append(_f[field])
    if not sets:
        conn.close()
        return {"ok": True}
    params.append(wid)
    conn.execute(f"UPDATE work_logs SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'work_log.update', 'work_log', str(wid), str(wid), {'fields': [s.split('=')[0] for s in sets]})
    return {"ok": True}


@router.delete("/api/work-logs/{wid}")
def delete_work_log(wid: int, authorization: str = Header(None)):
    u = _require_user(authorization)
    require_any_module(u, ('work_log', 'case_manage'), "工作日誌")      # 第49班 W1c-P5
    conn = get_db()
    row = conn.execute("SELECT user_id FROM work_logs WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到日誌")
    if u["role"] not in ("superadmin", "admin") and u["id"] != row["user_id"]:
        conn.close()
        raise HTTPException(403, "只能刪除自己的工作日誌")
    conn.execute("DELETE FROM work_logs WHERE id=?", (wid,))
    conn.commit()
    conn.close()
    notify_module_activity("工作日誌", "刪除", u.get("display_name") or u["username"],
                            str(wid), "work-log.html")
    _audit(_tok(authorization), 'work_log.delete', 'work_log', str(wid), str(wid))
    return {"ok": True}


# ── Work Log Photos（2026-08-26 專案管理併入案件管理：案件動態的工作日誌
#    補上照片能力，處理邏輯/儲存位置整段沿用 routers/projects.py 既有的
#    upload_project_photos()/delete_project_photo()（含 GPS/浮水印處理與
#    demo 帳號隔離，經同一支 _photo_root() 判斷），子資料夾用 worklog_{id}
#    區分，不需要另外新增 demo 專用目錄或清空清單項目）───────────────────────

@router.post("/api/work-logs/{wid}/photos", status_code=201)
async def upload_work_log_photos(
    wid: int,
    files: List[UploadFile] = File(...),
    authorization: str = Header(None),
    idempotency_key: str = Header(None),
):
    """工作日誌補照片（選填標頭 `Idempotency-Key`：同一把 key 重送 ⇒ 重播第一次的回應，不再存檔；見 helpers/idempotency.py）。"""
    user = _require_user(authorization)
    key = _idem.parse_key(idempotency_key)
    return await _idem.run(
        user["username"], key, f"POST work_log_photos:{wid}",
        _idem.request_hash([(f.filename, f.size) for f in (files or [])]),
        lambda: _upload_work_log_photos_impl(wid, files, authorization, user), 201)


async def _upload_work_log_photos_impl(wid, files, authorization, user):
    require_any_module(user, ('work_log', 'case_manage'), "工作日誌")
    conn = get_db()
    row = conn.execute("SELECT * FROM work_logs WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "找不到日誌")
    if user["role"] not in ("superadmin", "admin") and user["id"] != row["user_id"]:
        conn.close(); raise HTTPException(403, "只能替自己的工作日誌上傳照片")

    today = datetime.now().strftime("%Y-%m-%d")
    base_dir, url_prefix = _photo_root()
    save_dir = os.path.join(base_dir, f"worklog_{wid}", today)
    os.makedirs(save_dir, exist_ok=True)

    new_photos = []
    written = []
    try:
        for upload in files:
            raw_bytes = await upload.read()
            ext   = os.path.splitext(upload.filename or 'photo.jpg')[1] or '.jpg'
            # 白名單＝前端（case-management.html 的 accept＝jpeg/png/pdf）本來就送得出去的東西＋手機常見格式（heic/heif/webp/gif）
            if ext.lower() not in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.pdf'):
                raise HTTPException(400, f"不支援的檔案格式：{upload.filename}（僅支援 jpg/png/gif/webp/heic/pdf）")
            _check_upload_magic(upload.filename or 'photo.jpg', ext, raw_bytes, "work_log_photos", user['username'])
            try:
                processed, gps_str, wm_str = await run_decode(_process_project_photo, raw_bytes, user['display_name'])
            except ImageRejected as e:
                raise HTTPException(e.status, f"{e.user_message}（{upload.filename}）")
            fname = uuid.uuid4().hex[:14] + ext.lower()
            written.append(os.path.join(save_dir, fname))
            with open(written[-1], 'wb') as f:
                f.write(processed)
            new_photos.append({
                "id":          uuid.uuid4().hex[:8],
                "filename":    fname,
                "path":        f"{url_prefix}/worklog_{wid}/{today}/{fname}",
                "gps":         gps_str,
                "watermark":   wm_str,
                "uploaded_by": user['display_name'],
                "uploaded_at": datetime.now().isoformat(),
            })
        # 慢動作（解碼、寫檔）都做完了，現在才拿寫鎖、重讀目前的 photos、只加上這一批：
        # 兩個請求同時往同一筆日誌上傳時，各自讀到上傳前的 photos 再整包寫回，後寫的會蓋掉先寫的 ⇒ 先寫那一批的檔就成了孤兒（沒有紀錄指向）；
        # 日誌在上傳途中被刪掉（UPDATE 影響 0 列）、或這裡任何資料庫錯誤，也走下面同一個回收。
        with write_txn(conn):
            cur_row = conn.execute("SELECT photos FROM work_logs WHERE id=?", (wid,)).fetchone()
            if not cur_row:
                raise HTTPException(404, "找不到日誌")
            all_photos = json.loads(cur_row["photos"] or "[]") + new_photos
            conn.execute("UPDATE work_logs SET photos=? WHERE id=?",
                         (json.dumps(all_photos, ensure_ascii=False), wid))
            conn.commit()
    except BaseException:
        # 整批要嘛全收要嘛全不收：任何一張失敗（400／503／斷線）⇒ 這次已寫到磁碟的檔案刪掉，免得留下孤兒、客戶端重試又重複一份
        for _p in written:
            try:
                os.remove(_p)
            except OSError:
                pass
        conn.close()
        raise

    conn.close()
    notify_module_activity("工作日誌", "上傳照片", user['display_name'],
                            f"日誌 #{wid}（{len(new_photos)} 張）", "work-log.html")
    _audit(_tok(authorization), 'work_log.photo_upload', 'work_log', str(wid), str(wid), {'added': len(new_photos)})
    return {"ok": True, "added": len(new_photos), "photos": new_photos}


@router.delete("/api/work-logs/{wid}/photos/{photo_id}")
def delete_work_log_photo(wid: int, photo_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('work_log', 'case_manage'), "工作日誌")
    conn = get_db()
    row  = conn.execute("SELECT * FROM work_logs WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "找不到日誌")
    if user["role"] not in ("superadmin", "admin") and user["id"] != row["user_id"]:
        conn.close(); raise HTTPException(403, "只能刪除自己工作日誌的照片")
    # lost update：拿寫鎖之後才重讀、只濾掉這一張（讀到寫之間別人剛上傳的照片不會被整份寫回蓋掉）；
    # 實體檔在 commit 之後才刪（資料庫寫失敗時不會留下「紀錄還在、檔案已不見」）
    with write_txn(conn):
        cur_row = conn.execute("SELECT photos FROM work_logs WHERE id=?", (wid,)).fetchone()
        if not cur_row:
            raise HTTPException(404, "找不到日誌")
        photos = json.loads(cur_row["photos"] or "[]")
        photo  = next((p for p in photos if p.get('id') == photo_id), None)
        if not photo:
            raise HTTPException(404, "照片不存在")
        photos = [p for p in photos if p.get('id') != photo_id]
        conn.execute("UPDATE work_logs SET photos=? WHERE id=?",
                     (json.dumps(photos, ensure_ascii=False), wid))
        conn.commit()
    conn.close()
    try:
        base_dir, _url_prefix = _photo_root()
        fp = os.path.join(base_dir, '..', photo['path'])
        if os.path.isfile(fp):
            os.remove(fp)
    except Exception:
        pass
    notify_module_activity("工作日誌", "刪除照片", user.get("display_name") or user["username"],
                            f"日誌 #{wid}", "work-log.html")
    _audit(_tok(authorization), 'work_log.photo_delete', 'work_log', str(wid), str(wid), {'photoId': photo_id})
    return {"ok": True}


class _WorkLogPhotoAccess:
    """`uploads.path_access`（IP-104，2026-09-30 P0）：`projects/…`（demo：`_demo_projects/…`）＝工作日誌照片
    （含 2026-08-26 從專案日誌搬過來的舊路徑）。擁有單據＝`photos` 列出這個路徑的那筆 `work_logs`；讀取規則＝
    `GET /api/work-logs`（`work_log` 或 `case_manage` 模組；superadmin 直通），或該日誌掛的案件的動態看得到
    （案件動態端點把掛在案件上的工作日誌連照片一起列出，規則 `case_documents_readable`）。沒有任何一筆列出 ⇒ False。"""
    FOLDERS = ("projects",)

    @staticmethod
    def readable(conn, folder, rest, user):
        from helpers.auth import user_has_module
        from helpers.case_access import case_documents_readable
        from helpers.uploads import upload_owner
        by_module = user.get("role") == "superadmin" or any(user_has_module(user, k) for k in ('work_log', 'case_manage'))
        want = (folder, tuple(rest))
        tail = "/".join(rest)
        like = "%" + tail.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        for r in conn.execute("SELECT case_no, photos FROM work_logs WHERE photos LIKE ? ESCAPE '\\'", (like,)):
            try:
                photos = json.loads(r["photos"] or "[]") or []
            except (TypeError, ValueError):
                continue
            if not any(isinstance(p, dict) and upload_owner(p.get("path") or "") == want for p in photos):
                continue
            if by_module or (r["case_no"] and case_documents_readable(conn, r["case_no"], user)):
                return True
        return False


from core import registry as _registry  # noqa: E402
_registry.provide("uploads.path_access", "work_log", _WorkLogPhotoAccess)


class _WorkLogCatalog:
    """`attachments.catalog`（契約 v1，2026-09-30 P2）：工作日誌照片（`work_logs.photos`）。`doc_no`＝日誌 id。
    權限＝`_WorkLogPhotoAccess` 同一支（`work_log`／`case_manage` 模組 ∨ 日誌掛的案件動態看得到）。"""
    CATEGORIES = {
        "work_log_photo": {"label": "工作日誌照片", "doc": "工作日誌", "module": "工作日誌"},
    }

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        from helpers.uploads import AttachmentNotVisible, AttachmentSourceError, opened_upload_file, pick_file, upload_owner
        if source_type != "work_log_photo":
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        if not str(doc_no).isdigit():
            return None
        row = conn.execute("SELECT case_no, photos FROM work_logs WHERE id = ?", (int(doc_no),)).fetchone()
        if row is None:
            return None
        try:
            photos = json.loads(row["photos"] or "[]") or []
        except (TypeError, ValueError):
            raise AttachmentSourceError("工作日誌「%s」的照片資料格式不正確。" % doc_no)
        entry = pick_file(photos, file_id)
        if entry is None:
            return None
        from helpers.uploads import upload_path_key
        if upload_path_key(entry, "projects", depth=3) != "worklog_%d" % int(doc_no):
            return None                                          # 路徑不在這則日誌自己的資料夾 ⇒ 當作沒有這個檔（W3）
        owner = upload_owner(entry.get("path") or "")
        if owner is None or not _WorkLogPhotoAccess.readable(conn, owner[0], owner[1], user):
            raise AttachmentNotVisible()
        return opened_upload_file(entry)

    # ── 搜尋（附件目錄 P3）：權限＝open() 同一支 `_WorkLogPhotoAccess.readable`，路徑綁日誌（同 open()）；
    #    只取檔案 metadata——照片的 GPS／浮水印欄位不進搜尋項目 ──
    @staticmethod
    def _collect(conn, user, crit):
        import mimetypes
        from helpers import attachment_search as S
        from helpers.uploads import upload_owner, upload_path_key
        sql, args = "SELECT id, case_no, photos FROM work_logs WHERE photos LIKE ?", ["%\"path\"%"]
        if crit["quote_no"]:
            sql += " AND case_no = ?"
            args.append(crit["quote_no"])
        rows = conn.execute(sql, args).fetchall()
        names = S.case_names(conn, {r["case_no"] for r in rows if r["case_no"]})
        ok, items = {}, []
        for r in rows:
            try:
                photos = json.loads(r["photos"] or "[]") or []
            except (TypeError, ValueError):
                continue
            cust, proj = names.get(r["case_no"], ("", ""))
            for p in photos:
                if not isinstance(p, dict) or upload_path_key(p, "projects", depth=3) != "worklog_%d" % int(r["id"]):
                    continue                                     # 與 open() 同一道：路徑不在這則日誌的資料夾 ⇒ 不列
                owner = upload_owner(p.get("path") or "")
                if owner is None:
                    continue
                if owner not in ok:
                    ok[owner] = bool(_WorkLogPhotoAccess.readable(conn, owner[0], owner[1], user))
                if not ok[owner]:
                    continue
                f = {"id": p.get("id"), "filename": p.get("filename"), "size": p.get("size") or 0,
                     "mime": mimetypes.guess_type(str(p.get("filename") or ""))[0] or "",
                     "uploadedBy": p.get("uploaded_by"), "uploadedAt": p.get("uploaded_at")}
                items.append(S.make_item("work_log_photo", r["id"], "工作日誌 #%s" % r["id"], f, quote_no=r["case_no"] or "",
                                         customer=cust, project=proj, link="work-log.html"))
        return items

    @staticmethod
    def search(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.finish(_WorkLogCatalog._collect(conn, user, c), c)

    @staticmethod
    def count(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.count_by_type(_WorkLogCatalog._collect(conn, user, c), c)


_registry.provide("attachments.catalog", "work_log", _WorkLogCatalog)


# ── 執行時的開關（2026-09-22 §8 FX1a）─────────────────────────────────────────

#: 這台機器上「會不會對外連線」的兩個總開關。
#:
#: 🔴 **只列白名單裡的名字，不要把整個環境變數倒出來** ——
#: `os.environ` 裡有 SMTP 密碼、雲端金鑰、資料庫路徑。
#: ☠️ 一個「把環境變數印出來除錯」的端點，是外洩的標準形狀。
#:
#: 每一筆：`name`（環境變數名）／`on`（**這個行程實際判定的結果**）／
#: `present`（那個變數在不在）／`raw`（**只在白名單裡才回**，它們是 "0"/"1"）。
#: L2 模組的開關（例：MOTRIX_TENDER_RADAR）由 `core.registry.runtime_switches()` 提供，
#: 模組沒裝就不列——這裡只放 L1 自己的。
_RUNTIME_SWITCHES = (
    ("MOTRIX_GEO", "地址定位（連 OpenStreetMap）"),
    ("MOTRIX_DISABLE_SCHEDULERS", "停用所有背景排程（測試用）"),
)


#: 這個行程是什麼時候起來的。**模組匯入的那一刻 ≒ 行程啟動。**
#: ⚠️ 它的用途是分辨「開關沒生效」與「**行程根本沒重啟**」——
#: ☠️ 部署之後那兩件在畫面上一模一樣，而處置完全不同
#: （一個要改 `autostart.bat`，一個要去重跑排程工作）。
_PROCESS_STARTED_AT = datetime.now().isoformat(timespec="seconds")


@router.get("/api/system/runtime-switches")
def get_runtime_switches(authorization: str = Header(None)):
    """**這個行程實際拿到哪些開關。**

    ## 🔴 判準：它回答的是「行程拿到什麼」，不是「檔案裡寫了什麼」
    ☠️ `autostart.bat` 的兩個 `set` 在 `:loop` **標籤之前**
    ⇒ **部署之後不重跑排程工作的話，跑的還是舊環境變數的那個行程**，
    而「重跑排程」那一步在 88 份部署紀錄裡出現次數是 **0**。
    🔑 DEPLOY.md 自己寫著它的失敗長什麼樣：
    「推送成功、服務正常、畫面正常，**就是雷達不掃、地圖上沒有點**。」
    📌 〈計數器要有落點〉：一個只寫在文件裡而沒有任何東西在驗它發生過的步驟
    **等於不存在**。

    ⇒ 所以這裡讀的是 `os.environ`（透過各模組自己的 `*_on()`），
    **不是讀 `autostart.bat`**。讀檔案只會告訴你「應該要是什麼」。

    ## ⚠️ 限 superadmin
    它說得出這台機器會不會對外連線。**不是機密，而它也不是需要公開的東西** ——
    📌 公開白名單今天才因為「再多一條不會有人注意」被釘過（YD1b），
    所以這一支**不進那張清單**。
    """
    _require_user(authorization, require_superadmin=True, module='settings')
    from helpers import geo as _geo
    from core import registry as _registry

    # ⚠️ **`on` 走各模組自己的 `*_on()`，不要在這裡重寫一次判斷式。**
    # 重寫的話，這個端點會回報「我以為的規則」而不是「它們實際用的規則」——
    # 🔑 而那正是這個端點存在的理由（〈守門守的對象被搬走〉）。
    mod_switches = _registry.runtime_switches()
    resolved = {
        "MOTRIX_GEO": _geo.geo_on(),
        "MOTRIX_DISABLE_SCHEDULERS": os.getenv("MOTRIX_DISABLE_SCHEDULERS") == "1",
    }
    resolved.update({s.env: s.is_on() for s in mod_switches})
    switch_list = [(s.env, s.label) for s in mod_switches] + list(_RUNTIME_SWITCHES)
    return {
        # 🔑 **行程資訊**：沒有它的話，「開關沒生效」與「行程根本沒重啟」分不開。
        "pid": os.getpid(),
        "startedAt": _PROCESS_STARTED_AT,
        "switches": [
            {"name": name, "label": label,
             "present": os.getenv(name) is not None,
             "raw": os.getenv(name),
             "on": resolved.get(name, False)}
            for name, label in switch_list
        ],
    }

# ── CORE-SPEC §9c 模組選配：狀態、管理者啟停（2026-09-25）──────────────────────
#
# 狀態由 L0 載入器在**這次啟動**時決定（core.registry.module_states）：
#   loaded 啟用／disabled 管理者停用／unlicensed 未授權／failed 載入失敗（附原因）
#   優先順序：不在包內（沒有資料夾，不會列出）＞ 未授權 ＞ 管理者停用。
# 🔴 管理者啟停**重啟後生效**（2026-09-25 裁示：不做動態卸載路由）。所以每一列分開回
#    「目前狀態」（這個行程實際的樣子）與「重啟後」（依目前設定），兩者不同 ⇒ pendingRestart。
# ⚠️ 這裡不提供重啟：重啟正式機是部署／運維的動作，由使用者決定（同一裁示）。

_MODULE_STATE_LABELS = {"loaded": "啟用", "disabled": "停用", "unlicensed": "未授權", "failed": "載入失敗"}


#: STATES-PLATFORM P-SW-03：授權在執行中變了（到期、換金鑰）——模組層級只在啟動時判斷，這裡標出來。
LICENSE_CHANGED_NOTE = "授權變更於重啟後生效"


def _license_now(st):
    """現在（這個請求當下）重新判一次模組授權；回 (ok, reason)。讀金鑰失敗 ⇒ None（不猜）。"""
    from helpers import licensing as _lic
    try:
        return _lic.module_license_check({"key": st["key"], "license_key": st.get("license_key")})
    except Exception:                                            # noqa: BLE001
        return None


def _module_rows():
    from core import registry as _registry
    from helpers import module_switches as _ms
    configured = set(_ms.configured_disabled())
    rows = []
    for st in _registry.module_states():
        lic_now = _license_now(st) if st["state"] != "failed" else None
        licensed_now = None if lic_now is None else bool(lic_now[0])
        after = st["state"]
        if st["state"] == "unlicensed" and licensed_now:
            after = "loaded"                                  # 授權補上了：重啟後依管理者開關
        if st["state"] in ("loaded", "disabled") or after == "loaded":
            after = "disabled" if st["key"] in configured else "loaded"
        if licensed_now is False:
            after = "unlicensed"                              # 授權沒了：重啟後不載入
        license_changed = licensed_now is not None and (
            licensed_now != (st["state"] != "unlicensed"))
        rows.append({**st, "stateLabel": _MODULE_STATE_LABELS[st["state"]],
                     "afterRestart": after, "afterRestartLabel": _MODULE_STATE_LABELS[after],
                     "pendingRestart": after != st["state"],
                     "licenseChanged": license_changed,
                     "licenseNote": ((LICENSE_CHANGED_NOTE + "：" + (lic_now[1] or "目前授權包含此模組"))
                                     if license_changed else ""),
                     "canToggle": st["state"] in ("loaded", "disabled")})
    return rows


@router.get("/api/system/modules")
def list_system_modules(authorization: str = Header(None)):
    """模組管理頁：每個模組的目前狀態、原因、重啟後狀態。限 superadmin。"""
    _require_user(authorization, require_superadmin=True, module='settings')
    from core import registry as _registry
    return {"pid": os.getpid(), "startedAt": _PROCESS_STARTED_AT, "modules": _module_rows(),
            # P-SW-05：這次啟動的停用清單從哪裡來（db／no_db／cache／unreadable）＋給管理者看的說明
            "disabledList": _registry.disabled_list() or {"source": "", "message": ""}}


class _ModuleToggleIn(BaseModel):
    enabled: bool


@router.put("/api/system/modules/{key}")
def toggle_system_module(key: str, body: _ModuleToggleIn, authorization: str = Header(None)):
    """superadmin 啟用／停用一個模組（寫 system_settings.modules_disabled）。**重啟後生效**，資料不動。

    未授權或載入失敗的模組不可切換——那不是管理者開關能解決的事（400 並說明原因）。"""
    _require_user(authorization, require_superadmin=True, module='settings')
    rows = {r["key"]: r for r in _module_rows()}
    if key not in rows:
        raise HTTPException(404, "找不到模組：%s（不在這個安裝包裡）" % key)
    if not rows[key]["canToggle"]:
        raise HTTPException(400, "模組 %s 目前是「%s」：%s——管理者開關無法處理" %
                            (key, rows[key]["stateLabel"], rows[key]["reason"] or ""))
    from helpers import module_switches as _ms
    _ms.set_enabled(key, body.enabled)
    _audit(_tok(authorization), "system.module.enable" if body.enabled else "system.module.disable",
           "settings", key, "%s模組 %s（重啟後生效）" % ("啟用" if body.enabled else "停用", key))
    row = {r["key"]: r for r in _module_rows()}[key]
    return {"ok": True, "module": row, "restartRequired": row["pendingRestart"]}


@router.get("/api/system/modules/availability")
def module_availability(authorization: str = Header(None)):
    """選單與頁面提示用（任何登入者）：`{key: {"state", "label", "name"}}`，這次啟動的模組狀態。
    不在這份清單裡的 key ＝不在這個安裝包（STATES-PLATFORM P-FE-02）。**不回原因**——原因只給
    superadmin 的 `/api/system/modules`。取代 2026-09-25 的 `/unavailable-pages`（只列未載入的頁面，
    不在安裝包的模組因此永遠不會被藏）。"""
    _require_user(authorization)
    from core import registry as _registry
    return {st["key"]: {"state": st["state"], "label": _MODULE_STATE_LABELS[st["state"]], "name": st["name"]}
            for st in _registry.module_states()}


@router.get("/api/system/modules/unavailable-pages")
def unavailable_module_pages(authorization: str = Header(None)):
    """⚠ 相容用（CORE 1.2 的端點；同一主版號內不刪）：這次啟動沒有載入的模組的頁面。
    側欄已改用 `/availability`——這份清單列不出「不在安裝包」的模組（P-FE-02），新程式不要用。"""
    _require_user(authorization)
    from core import registry as _registry
    return {"pages": sorted({p for st in _registry.module_states() if st["state"] != "loaded"
                             for p in st["pages"]})}


@router.get("/api/system/bonus-module-status")
def get_bonus_module_status(authorization: str = Header(None)):
    """獎金分潤模組現在開著沒（`BONUS_MODULE_ENABLED`；2026-09-24 起出貨預設開，
    使用者「上傳到正式機就自動啟用」；現場可用環境變數 =0 關）。
    📌 下面「為什麼要有這一支」寫的是當初預設關的理由（舊算法），新設計（SPEC-BONUS §十一）
       已改成同一個獎金池；這一支仍然是側欄與頁面「該不該顯示」的唯一來源。

    ## 🔴 為什麼要有這一支：前端旗標要後端給，不能寫死在 JS 裡

    獎金池的算法目前有一個會算錯錢的缺陷（`SPEC-BN21.md`：三組各自獨立
    算「佔淨利的比例」，沒有任何地方檢查加起來是多少），在改成「三組
    共同分攤同一個池」之前，側邊欄要隱藏這個入口、`bonus.html` 直接
    開網址也要顯示「暫停使用」——兩處都要問同一個地方，不要各自寫一份
    判斷式（那正是〈守門守的對象被搬走〉的成因：兩份各自維護，其中一份
    改了，另一份沒有人記得跟著改）。

    ## ⚠️ 只要求登入，不要求特定模組

    這不是機密（不透露會不會對外連線那種等級），任何登入者都要能問到
    「這個入口該不該出現」，不然一般使用者連側邊欄都建不對。
    """
    _require_user(authorization)
    # IP-16 `bonus.module_status`（M07 → L1）：不 import M07（DEPENDENCY-MAP #27）。
    # M07 不在 ⇒ 關（入口隱藏、頁面顯示暫停），並說明原因——與「模組沒載入」同一個結果
    from core import registry as _registry
    status = _registry.single_provider("bonus.module_status")
    if status is None:
        return {"enabled": False, "notice": BONUS_MODULE_ABSENT}
    return {"enabled": bool(status())}


#: IP-16 對方不在時的說明
BONUS_MODULE_ABSENT = "薪資獎金模組未安裝：獎金分潤不提供"


# ── Company profile（甲方設定，勞報單使用）────────────────────────────────────

class CompanyProfile(BaseModel):
    name:                str = ''
    tax_id:              str = ''
    contact_info:        str = ''
    bank_name:           str = ''  # 收款帳戶資訊（2026-08-24 新增，供請款單 PDF 顯示）
    bank_branch:         str = ''
    bank_account_name:   str = ''
    bank_account_number: str = ''
    # 辦公室地址（2026-09-21 §3l）。用途是**算標案離我們多遠**，
    # 所以它跟抬頭／統編不同：沒填的後果不是 PDF 少一行，是整個距離功能不會動。
    # ⇒ 沒填時地圖端點會明白回報 `officeMissing`，不是安靜地不顯示距離。
    address: str = ''
    # Google Maps 金鑰（可選）。**免金鑰的底圖與距離不需要它**，
    # 它只開啟「附近公司」那一塊；空字串 ⇒ 那一塊**不存在**（不是壞掉的按鈕）。
    # ⚠️ 它會被送到前端——那是 Maps JS API 的正常用法，不是洩漏。
    #    但**不可以寫進任何 log**：log 會被打包、被寄出、被放進備份，
    #    而那些地方沒有人在管金鑰。兩者的保存期限完全不同。
    google_maps_api_key: str = ''
    # 第十五班 ②(b)：地圖（瀏覽器）用金鑰——**與上面那把分開**（使用者裁示）。它會出現在瀏覽器載入
    # Maps JavaScript API 的網址上 ⇒ 由使用者在 Google Cloud 限定 HTTP referrer＋只開 Maps JavaScript API。
    # 有填 ⇒ 地圖改用 Google 底圖（geo.google_basemap()）；設定頁同樣遮蔽顯示。
    google_maps_browser_key: str = ''
    # 第十五班 ②(b)：Google Cloud Console 建的「地圖 ID」（Map ID）。AdvancedMarkerElement 需要它。
    # ⚠️ 不是秘密（會出現在前端），不遮蔽。官方示範用的 map ID 只准在測試／開發，正式路徑不預設（守門題 test_demo_map_id_never_appears_in_product_code）。
    google_maps_map_id: str = ''
    # 手動座標（2026-09-22 §3o A2／A10）。填了就**跳過所有查詢**，
    # 精度是 exact、來源是 manual。
    # 🔑 它存在的理由：圖資認不得台灣的門牌，而使用者知道自己在哪裡。
    # ⚠️ 兩個欄位是 Optional 而不是預設 0.0——
    #    **0.0 是幾內亞灣上的一個點，不是「沒有填」。**
    office_lat: Optional[float] = None
    office_lon: Optional[float] = None
    # 多據點（2026-09-22 §5 BR）。**這是唯一真相**，
    # 而上面那三個欄位（address／office_lat／office_lon）改成由 `locations[0]` 導出。
    # 🔑 留著它們是為了**相容**（`map_points.py` 還在讀），不是為了再編輯一次 ——
    # ☠️ 兩個地方都能編輯同一件事，是這一整天在修的那一族缺陷。
    #
    # 每一筆：`id`（後端配發）／`name`（必填、不可重複）／`address`（必填）／
    # `lat`／`lon`（選填）／銀行四欄（選填，**留空＝沿用主要據點**）。
    locations: Optional[list] = None
    # 本公司資料設定閘門（COMPANY-SETUP-GATE §3.2）：設定頁「確認本公司資料」才帶 true；一般存檔不帶 ⇒ 不寫確認紀錄。不存進 company_profile
    confirmIdentity: Optional[bool] = None
    # R3（個資法 §8 I）：個資蒐集告知文字；空白 ⇒ 列印時用範本（helpers/privacy_notice.py）
    privacy_notice: str = ''
    # 2026-09-26：其他蒐集個資的表單各自的告知文字（聯絡人／使用者帳號）；空白 ⇒ 該用途的範本
    privacy_notice_contact: str = ''
    privacy_notice_user: str = ''
    # 2026-09-27 H10：公司層級的英文名稱、電話、email（company_identity 的第三層本來就讀這三個鍵，
    # 只是這個模型沒有它們 ⇒ PUT 會被 Pydantic 靜默丟掉，設定頁改不到）。空白 ⇒ 電話／email 仍後備讀「聯絡方式」。
    company_name_en: str = ''
    phone: str = ''
    email: str = ''
    # 2026-11-13「報價用公司信箱」：公司對外信箱。使用者沒有自己的報價用信箱時，報價單／PDF／信件 Reply-To 用它（helpers/quote_email.py）。空白＝不設。
    external_email: str = ''


# 🔴 **既有安裝讀得到新欄位，靠的是這裡，不是 `db.py` 的 seed。**
# `_seed_setting` 是 `ON CONFLICT(key) DO NOTHING` ⇒ 對已經存在的那一列
# **一個字都不會改**。新增欄位時只改 seed 的話，新機正常、舊機沒有那個欄位，
# 而開發時手邊兩種都有、注意力只會落在會動的那一台。
# 📌 銀行那四欄 2026-08-24 就走過這條路。
_COMPANY_PROFILE_DEFAULT = {
    "name": "", "tax_id": "", "contact_info": "",
    "bank_name": "", "bank_branch": "", "bank_account_name": "", "bank_account_number": "",
    "address": "", "google_maps_api_key": "", "google_maps_browser_key": "", "google_maps_map_id": "",
    "office_lat": None, "office_lon": None,
    "locations": [],
    "privacy_notice": "",       # R3 個資蒐集告知（空白＝用範本，helpers/privacy_notice.py）
    "privacy_notice_contact": "",   # 聯絡人用（客戶／供應商／承攬商），空白＝範本
    "privacy_notice_user": "",      # 使用者帳號用，空白＝範本
    "company_name_en": "", "phone": "", "email": "",   # 2026-09-27 H10（品牌區塊一起編輯）
    "external_email": "",       # 2026-11-13 公司對外信箱（報價用；helpers/quote_email.py）
}

#: 設定頁編輯的鍵 ⇒ 同一欄在 company_profile 裡、解析順序排在它前面的別名（helpers.company_identity._PROFILE_ALIASES）。
#: 別名已經存在（例：升級時回填的 `company_name`）⇒ 存檔時一起改成同一個值，否則設定頁改了、單據與登入頁照舊。
_PROFILE_EDIT_SHADOWS = {
    "name": ("companyName", "company_name"),
    "company_name_en": ("companyNameEn",),
    "tax_id": ("taxId",),
}

#: 據點可以自己帶的銀行欄位。**留空＝沿用主要據點。**
#:
#: ⚠️ **這一輪只留位置，不接到 PDF**（那是 §7 白標化 WL1）——
#: 接上去之前要先回答「一張報價單屬於哪個據點」，而那個欄位還不存在。
#: 🔑 **而結構現在就要留**：§5 定稿之後再改就有正式機資料了，
#: 那一改是 migration 不是編輯。
_LOCATION_BANK_FIELDS = ("bank_name", "bank_branch",
                         "bank_account_name", "bank_account_number")

#: 據點自己的抬頭。**每一欄留空 = 沿用主要據點的同一欄**（§9 QL5），
#: 所以「沒填」與「填空字串」在這裡是同一件事，不必分。
#:
#: 🔴 這幾個欄位先前**收了但沒有存** —— `_clean_locations()` 只留 id/name/
#: address/座標 ＋ 四個銀行欄位，而 `pdf_gen.location_identity()` 讀的正是這幾個。
#: ☠️ 症狀是「設定頁存檔成功，而分公司的單據還是印總公司抬頭」：
#: 🔑 沒有任何錯誤訊息，因為沒有人做錯事 —— 前端送了、後端收了、後端沒存。
_LOCATION_IDENTITY_FIELDS = ("company_name", "company_name_en",
                             "tax_id", "phone", "email")

#: 下一個要配發的據點流水號存在哪。**存在自己的設定鍵裡，不在 `company_profile` 裡。**
#:
#: 🔴 **它不可以從「現有據點的最大 id」推算** ——
#: 那正是 BR5 在擋的：刪掉 `loc_2` 之後最大值變回 1，
#: ⇒ ☠️ 下一個新據點又拿到 `loc_2`，**而它指向的是另一家分公司**。
#: 🔑 一個「從現況推算」的計數器，在現況縮小時會倒退 ——
#: 📌〈計數器要有落點〉：落點要是一個**只增不減**的地方，不是資料本身。
#:
#: 🔴 **不可以重用已刪除的 id**：某個地方存著「這個案子歸據點 3」，
#: 而據點 3 被刪掉、新的台北分公司拿到同一個 3
#: ⇒ ☠️ **那筆歸屬悄悄換了對象，而畫面上完全正常。**
#: 🔑〈降級之後它還是會動〉：資料看起來完整，只是指錯了人。
_LOCATION_SEQ_KEY = "_location_seq"

#: 據點 id 允許的形狀。
#:
#: 🔑 理由是**可讀性**，不是安全：那個字串會被寫進 `quotations.location_id`、
#: 會出現在稽核紀錄、**會被人用眼睛比對**。
#: ☠️ 一個含空白或標點的 id，出問題的那天會很難講清楚是哪一筆。
#:
#: ⚠️ **只驗新寫入，不追溯既有值**（見 `_clean_locations`）——
#: 一個回溯驗證會讓「手動改過設定表」的人連存檔都存不了，
#: 而那是一個**他無法從錯誤訊息推回去**的狀態。
LOCATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _location_seq_floor():
    from helpers.settings import _get_setting
    try:
        return int(_get_setting(_LOCATION_SEQ_KEY, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _save_location_seq(value):
    from helpers.settings import _set_setting
    _set_setting(_LOCATION_SEQ_KEY, int(value))


def _location_reference_counts(ids):
    """這些據點各被幾張單據綁著。回 `{id: 張數}`，只回**大於 0** 的。

    🔑 現在只有 `quotations.location_id` 一個引用點。
    ⚠️ 日後多一張表綁據點時**要一起加進來** ——
    ☠️ 漏掉的那一張表，它的單據會在使用者刪據點時安靜地換掉發票抬頭，
       而 `QL11` 的守門會說「沒有人在用它」。
    """
    ids = [i for i in ids if i]
    if not ids:
        return {}
    conn = get_db()
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            "SELECT location_id, COUNT(*) AS c FROM quotations "
            "WHERE location_id IN (%s) GROUP BY location_id" % placeholders,
            ids).fetchall()
    finally:
        conn.close()
    return {r["location_id"]: int(r["c"]) for r in rows if r["c"]}


def _guard_removed_locations(new_list, previous):
    """🔴🔴 QL11：**被引用的據點不可以刪掉。**

    ⚠️ **不可以「刪了就自動退回主要據點」** ——
    ☠️ 那會讓一批單據在**沒有人知道的情況下**換了發票抬頭，
    🔑 而那種事不會報錯，它只會印在寄給客戶的紙上。

    📌 判準是 **`id` 還在不在**，不是「這一筆有沒有變」（`QL12`）：
    `id` 還在、`name` 變了 ⇒ 那是**改名，不是刪除**。
    ☠️ 否則使用者改一個分公司的名字會被擋下來，而錯誤訊息會說
       「有 N 張單據在用它」—— **那句話是對的，而它回答的不是使用者正在做的那件事。**
    """
    before = {str(x.get("id") or "") for x in (previous or []) if x.get("id")}
    after = {str(x.get("id") or "") for x in (new_list or []) if x.get("id")}
    removed = sorted(before - after)
    if not removed:
        return
    counts = _location_reference_counts(removed)
    if not counts:
        return          # QL12 反向控制：沒有人引用 ⇒ 刪得掉
    names = {str(x.get("id")): (x.get("name") or x.get("id"))
             for x in (previous or [])}
    detail = "、".join(
        "「%s」有 %d 張報價單" % (names.get(k, k), n)
        for k, n in sorted(counts.items()))
    raise HTTPException(
        422,
        "這些據點還被單據引用，不能刪除：%s。"
        "請先把那些單據改綁到別的據點，或保留這個據點。"
        "（刪掉的話，那批單據會在沒有人發現的情況下換掉發票抬頭與匯款帳號。）"
        % detail)


def _clean_locations(raw, previous):
    """把送進來的 `locations` 驗過、配發 id、補座標。回新的清單。

    ## 🔴 名稱必填且不可重複
    理由不是整潔：距離欄位要寫「離**台北分公司** 3.2 km」——
    ☠️ 兩個同名的據點會讓那句話沒有意義，而空名稱會寫出「離 3.2 km」。

    ## 📌 id 的配發規則
    ① 送進來有 `id` 而且是既有的 ⇒ 沿用
    ② 沒有 id 但**名字**對得上既有的一筆 ⇒ 沿用那一筆的 id
       （名稱不可重複 ⇒ 名字是一個合法的鍵；前端不送 id 時才用得到）
    ③ 其餘 ⇒ **配一個新的流水號**，而流水號**只增不減**。

    ## ⚠️ 留空與空字串是兩件事
    銀行欄位沒送 ⇒ **整個鍵不存在**（語意是「沿用主要據點」）；
    ☠️ 塞一個空字串進去的話，讀起來變成「這個據點沒有帳號」。
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise HTTPException(422, "locations 必須是一個陣列")

    prev_by_id = {str(l.get("id")): l for l in (previous or [])
                  if isinstance(l, dict) and l.get("id")}
    prev_by_name = {str(l.get("name") or "").strip(): l for l in (previous or [])
                    if isinstance(l, dict)}
    # 🔴 **只增不減**：從設定裡讀，而不是從現有據點推算。
    # ⚠️ 從現況推算的話，刪掉最後一筆之後計數器會倒退，
    # ⇒ 下一個新據點拿到剛被刪掉的那個 id。
    # 📌 同時也吃現有據點的最大值 —— 那是為了**既有安裝**：
    # 它們的 `locations` 是讀取時補出來的（`loc_1`），而計數器還沒存在過。
    seq = _location_seq_floor()
    for loc in (previous or []):
        if isinstance(loc, dict):
            ident = str(loc.get("id") or "")
            if ident.startswith("loc_") and ident[4:].isdigit():
                seq = max(seq, int(ident[4:]))

    out, seen_names = [], set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise HTTPException(422, f"locations[{idx}] 不是一個物件")
        name = str(item.get("name") or "").strip()
        address = str(item.get("address") or "").strip()
        if not name:
            raise HTTPException(422, f"第 {idx + 1} 個據點沒有名稱 —— "
                                     "距離欄位要寫「離○○ 3.2 km」，沒有名稱那句話就沒有主詞")
        if not address:
            raise HTTPException(422, f"據點「{name}」沒有地址")
        if name in seen_names:
            raise HTTPException(
                422, f"據點名稱重複：「{name}」。"
                     "兩個同名的據點會讓「離○○多遠」那句話沒有意義")
        seen_names.add(name)

        # 📌 **送進來的 id 就沿用**（不限於既有的那幾個）：
        # 報價單等下游資料會存「我屬於據點 X」⇒ 🔑 **id 是一個對外的識別碼**，
        # 而呼叫端（匯入、還原、測試治具）需要能指定它。
        # ⚠️ 而「**不重用已刪除的 id**」那條仍然成立：自動配號走的是
        # 只增不減的計數器，而下面那一行讓外來的 `loc_N` 也把它頂上去。
        ident = str(item.get("id") or "").strip()
        # 🔴 **只驗這一次新出現的 id。**
        # 既有的 id（`prev_by_id` 裡那些）原樣放行 ——
        # ☠️ 回溯驗證會讓一個手動改過設定表的人連存檔都存不了。
        if ident and ident not in prev_by_id and not LOCATION_ID_RE.match(ident):
            # 📌 訊息要講出**允許的型式**：只說「不合法」的話，
            # 下一個人知道它錯了而不知道要改成什麼。
            raise HTTPException(
                422,
                f"據點 id「{ident}」的格式不合：只允許英數字、底線與連字號，"
                "長度 1~32（例如 `loc_1`、`taipei-branch`）。"
                "這個值會被寫進單據與稽核紀錄，要能用眼睛比對。")
        if not ident:
            keep = prev_by_name.get(name)
            ident = str(keep.get("id")) if keep and keep.get("id") else ""
        if ident.startswith("loc_") and ident[4:].isdigit():
            # ☠️ 外來的 `loc_7` 不把計數器頂上去的話，
            # 之後自動配號可能配出同一個 `loc_7` —— **而它指向另一家分公司。**
            seq = max(seq, int(ident[4:]))
            _save_location_seq(seq)
        if not ident:
            seq += 1
            ident = f"loc_{seq}"
            _save_location_seq(seq)
        if any(l["id"] == ident for l in out):
            raise HTTPException(
                422, f"據點 id 重複：「{ident}」。"
                     "下游資料靠 id 指認據點，重複的話會指錯對象")

        clean = {"id": ident, "name": name, "address": address}
        lat, lon = item.get("lat"), item.get("lon")
        # ⚠️ **只填一個 ⇒ 當成沒填**（同 `_manual_coord` 的理由）：
        # 一個只有緯度的座標不是「一半的位置」，它是赤道上的一個錯誤位置。
        try:
            clean["lat"] = float(lat) if lat is not None and lat != "" else None
            clean["lon"] = float(lon) if lon is not None and lon != "" else None
        except (TypeError, ValueError):
            raise HTTPException(422, f"據點「{name}」的座標必須是數字")
        if clean["lat"] is None or clean["lon"] is None:
            clean["lat"] = clean["lon"] = None
        # 🔴 D 稽核 SST-M1：座標要記**來源**——手填的才是人工座標；存檔時自動定位填的照它的來源。
        # 🔑 來源由後端推導，不信前端送來的 coord_source：設定頁把存著的座標載進輸入框、存檔時原樣送回，
        #    「送回來的值」分不出是使用者打的還是上次自動填的 ⇒ 看它跟上次存的是不是同一組。
        if clean["lat"] is not None:
            prev = prev_by_id.get(ident) or {}
            same = (prev.get("lat") is not None and prev.get("lon") is not None
                    and abs(float(prev["lat"]) - clean["lat"]) < 1e-9
                    and abs(float(prev["lon"]) - clean["lon"]) < 1e-9)
            if not same:
                clean["coord_source"] = "manual"          # 新填或改過 ⇒ 使用者輸入
            elif prev.get("coord_source"):
                clean["coord_source"] = prev["coord_source"]
                if prev.get("coord_precision"):
                    clean["coord_precision"] = prev["coord_precision"]
            # 同一組、上次也沒有來源（既有資料）⇒ 不寫 coord_source（來源未知；處置見 geo._locate_locations）
        for field in _LOCATION_BANK_FIELDS + _LOCATION_IDENTITY_FIELDS:
            value = str(item.get(field) or "").strip()
            if value:
                clean[field] = value      # ← 沒填就**整個鍵不存在**
        out.append(clean)
    return out


def _fill_location_coords(locations):
    """把沒有座標的據點查一次，**把結果存進 `company_profile`**。

    ## 🔴 為什麼要存起來，而不是每次讀的時候查
    `geocode_cache` 因為隱私**已經被排除出每日備份**（§3t）
    ⇒ ☠️ **還原之後那張表是空的**。
    🔑 若據點座標只活在快取裡，災難還原之後每個據點都要重新定位 ——
    **而那需要對外連線，而還原的當下不一定有網路。**
    ⇒ 座標要跟著 `company_profile` 一起被備份。

    ⚠️ 查不到就留 `None`（不是 `0`），由地圖那一側回報 `locationsUnlocated`。
    """
    # 🔴 D 稽核 SST-M1（Google SST §6.2／§6.3）：
    # ① 底圖不是 Google ⇒ 在 `geo.without_google_content()` 裡查（只用免費來源，不問 Google）；
    # ② **Google 來源的座標不寫進 profile**——profile 永久保存、進每日備份，而 Google 經緯度最多快取 30 天
    #    （SST §6.3.1），`purge_expired_google_cache` 清不到這裡；Google 底圖時地圖直接讀 geocode_cache（受 30 天清除）；
    # ③ 寫入時一併記 coord_source／coord_precision，讀的一側（geo._locate_locations）只把 manual 當人工座標。
    import contextlib
    from helpers import geo
    scope = contextlib.nullcontext() if geo.google_basemap() else geo.without_google_content()
    with scope:
        for loc in locations or []:
            if loc.get("lat") is not None and loc.get("lon") is not None:
                continue
            found = geo.locate_cached(loc.get("address") or "")
            if found and found.coord and found.source != geo.SOURCE_GOOGLE:
                loc["lat"], loc["lon"] = found.coord[0], found.coord[1]
                loc["coord_source"] = found.source
                if found.precision:
                    loc["coord_precision"] = found.precision
    return locations


#: 遮蔽用的符號，以及末端露幾碼。
#:
#: 📌 具名常數的理由不是排版：`_looks_masked()` 要認得出自己遮的東西，
#: 而兩邊各寫一個字面值時，改一邊就會讓 UA3c 的安全網**安靜地失效**。
MASK_CHAR = "\u2022"
MASK_TAIL = 4


def _mask_secret(value) -> str:
    """把一個憑證遮成 `••••••••ab12`。**空值回空值。**

    ## 🔴 空的不可以遮成「看起來已經設定了」
    ☠️ 一律回一串 `••••••••` 的話，「**已經設定**」與「**還沒設定**」
    在畫面上會變成同一個樣子 ——
    🔑 那正好把「使用者找不到欄位」的問題原封不動搬到另一個位置：
    **他以為填過了，而「附近廠商」一直沒有出現。**

    ## ⚠️ 太短的金鑰整串遮掉
    `text[-4:]` 對一個 3 碼的值會回**整個值** ⇒ 遮蔽等於沒遮。
    這裡不會發生（Google 金鑰 39 碼），**而「不會發生」不是不處理的理由**：
    下一個用這個函式的欄位可能是四位數的 PIN。

    ## 📌 遮蔽長度刻意**不等於**原長度
    回傳 `MASK_CHAR * 8` 是固定的 ⇒ **看不出金鑰有多長**。
    長度本身是資訊（39 碼是 Google、32 碼是別家）。
    """
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= MASK_TAIL:
        return MASK_CHAR * 8
    return MASK_CHAR * 8 + text[-MASK_TAIL:]


def _looks_masked(value) -> bool:
    """這個值是不是我們自己遮出來的那一串。

    ⚠️ 判準是「含有 `MASK_CHAR`」。Google 的金鑰是
    `[A-Za-z0-9_-]` ⇒ 真金鑰**不可能**含有 `•`。
    📌 而萬一誤判，後果是**那次沒有更新金鑰**（保守），
    不是「金鑰被清掉」——🔑 **誤判要往安全的方向倒。**
    """
    return MASK_CHAR in str(value or "")


#: 哪些欄位在回傳時要遮起來。
#: 🔑 具名清單而不是 if：下一個憑證欄位（TGOS AppID…）加進來時，
#: **加在這裡就同時得到遮蔽與 UA3c 的安全網**，不會只做到一半。
_MASKED_FIELDS = ("google_maps_api_key", "google_maps_browser_key")


def _migrated_locations(profile):
    """既有安裝：`locations` 不存在而 `address` 非空 ⇒ 造一筆「總公司」。

    ## ⚠️ 空地址**不要**造一筆空的據點（BR3b）
    ☠️ 一筆「有名字沒地址」的據點會在地圖上變成「**定位不到的據點**」，
    🔑 **而那與「使用者真的填錯了地址」長得一模一樣**
    ⇒ 📌 新裝的機器會在第一天就看到一個「總公司定位不到」的警告，
    **而他什麼都還沒填。**

    ⚠️ **這是讀取時的補值，不是 migration** —— 它不改資料庫。
    🔑 真正寫進去的時機是下一次存檔（那時 `locations` 會被當成唯一真相）。
    📌 這樣做的理由與 `_COMPANY_PROFILE_DEFAULT` 同一條：
    `_seed_setting` 是 `DO NOTHING`，**對既有的那一列一個字都不會改**。
    """
    existing = profile.get("locations")
    if isinstance(existing, list) and existing:
        return existing
    address = str(profile.get("address") or "").strip()
    if not address:
        return []
    return [{"id": "loc_1", "name": "總公司", "address": address,
             "lat": profile.get("office_lat"), "lon": profile.get("office_lon")}]


#: 公開子集（`GET /api/settings/company-profile/public`，任何登入者可讀）——**白名單**：欄位只增不自動：profile 之後新增的鍵預設是私有的。
#: 內容＝目前所有非設定頁的畫面真的用到的東西（案件／核准／報價單的據點名稱、傳票抬頭、勞報單預填公司名稱／統編／聯絡方式）。
#: 不含：匯款帳號四欄、地址／電話／email、座標、金鑰、告知文字、據點自己的銀行與抬頭欄位。單據列印在伺服器端組（pdf_gen／company_identity），不經這個端點。
_PUBLIC_PROFILE_FIELDS = ("name", "tax_id", "contact_info")
_PUBLIC_LOCATION_FIELDS = ("id", "name")

#: 設定中心「登入與密碼」群組的開關：1 ＝ 完整公司資料只有最高管理者讀得到（其他人 403，請改用 /public）。預設 1（2026-11-13 使用者裁示：公司資料完整版預設只限最高管理者）；0 ＝ 登入即可讀（放寬，須第二位最高管理者核准）。
_FULL_READ_GROUP, _FULL_READ_FIELD = "account_security", "company_profile_full_read_superadmin_only"


def _full_read_superadmin_only() -> bool:
    """讀不到設定 ⇒ 當作開（只影響非最高管理者：他們改用 /public，不會壞）。"""
    try:
        from helpers import settings_registry as _sr
        return bool(int(_sr.get(_FULL_READ_GROUP, _FULL_READ_FIELD)))
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("公司資料讀取限制：讀不到設定，保守地只讓最高管理者讀完整內容", exc_info=True)
        return True


@router.get("/api/settings/company-profile/public")
def get_company_profile_public(authorization: str = Header(None)):
    """任何登入者可讀的公司資料子集（白名單）：名稱、統編、聯絡方式、據點（只有 id 與名稱）。"""
    _require_user(authorization)
    profile = {**_COMPANY_PROFILE_DEFAULT, **(_get_setting("company_profile", {}) or {})}
    out = {k: str(profile.get(k) or "") for k in _PUBLIC_PROFILE_FIELDS}
    out["locations"] = [{k: l.get(k, "") for k in _PUBLIC_LOCATION_FIELDS}
                        for l in _migrated_locations(profile) if isinstance(l, dict) and l.get("id")]
    return out


@router.get("/api/settings/company-profile")
def get_company_profile(authorization: str = Header(None)):
    me = _require_user(authorization)
    if me.get("role") != "superadmin" and _full_read_superadmin_only():
        raise HTTPException(403, "完整的公司資料只有最高管理者可以查看。")
    # 既有安裝的 DB 值可能是新增銀行欄位前存的舊 shape，缺的鍵補上空字串，
    # 前端才不用每個欄位都自己防 undefined。
    profile = {**_COMPANY_PROFILE_DEFAULT,
               **(_get_setting("company_profile", {}) or {})}
    # 🔴 **金鑰不明文回傳。** 那是一個**付費憑證**，而這個畫面會被截圖、
    # 被投影、被肩後看見，而且 superadmin 不只一個人。
    # 📌 末四碼留著 —— 使用者要分得出「我填的是哪一把」。
    for field in _MASKED_FIELDS:
        profile[field] = _mask_secret(profile.get(field))
    profile["locations"] = _migrated_locations(profile)
    return profile


def _check_office_coord(body: "CompanyProfile") -> None:
    """手動座標的範圍檢查。超出範圍 ⇒ 422。

    ⚠️ **緯度 ±90、經度 ±180 是地球的範圍，不是台灣的。**
    刻意不收窄到台灣：使用者哪天要標一個國外的案子，
    而**一個「為了你好」而擋住合法輸入的驗證，會被繞過去**。
    """
    pairs = (("office_lat", 90.0), ("office_lon", 180.0))
    for field, limit in pairs:
        if field not in body.model_fields_set:
            continue
        value = getattr(body, field)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{field} 必須是數字")
        if not -limit <= number <= limit:
            raise HTTPException(
                422, f"{field} 超出範圍（{-limit:g} ~ {limit:g}）：{number}")


#: 稽核要記**前後值**的欄位（金錢／身分類），而值要遮成末四碼。
#:
#: 🔑 兩件事同時成立才有用：**只記「變了」回答不了「從什麼改成什麼」，
#: 而記全碼會讓 `audit_log` 變成一張帳號清單**（它會被匯出、被截圖）。
_AUDIT_MASKED_VALUE_FIELDS = ("bank_account_number", "tax_id")

#: 稽核**連末四碼都不記**的欄位。
#:
#: ☠️ 它跟銀行帳號**不是同一類**：
#: 匯款帳號本來就印在寄給客戶的請款單上 ⇒ 不是秘密；
#: **Google 金鑰是一個付費憑證 ⇒ 撿到就能刷我們的帳。**
#: 🔑 而一個「一律遮成末四碼」的實作會讓帳號那一題全綠，**同時洩漏這一把**。
#: 📌〈判準的寬窄都會騙人〉：一個統一的規則對其中一類來說太寬。
_AUDIT_NEVER_VALUE_FIELDS = ("google_maps_api_key", "google_maps_browser_key")


def _audit_tail(value) -> str:
    """遮成 `…1234`。太短就整個遮掉。"""
    text = str(value or "")
    if not text:
        return ""
    return ("…" + text[-4:]) if len(text) > 4 else "…"


def _profile_audit_detail(before, after, sent_keys):
    """這一次改了哪些欄位，以及該留下什麼值。

    ## 🔑 判準：事後要能回答「**是誰、在什麼時候、把帳號從什麼改成什麼**」
    ☠️ 原本記的是**公司名**（`value.get("name","")`，而且進的是 `target_label`
    不是 `detail`）—— **它回答不了那個問題，而它看起來像有稽核。**
    📌 `_audit()` 有一個 `detail: dict` 參數，**而呼叫端從來沒有傳過它**
    ⇒ `audit_log` 歷來的 `detail` 全是 `{}`。
    ⚠️〈缺欄位≠缺訊號〉的反面：**欄位在，只是從來沒有人往裡面放東西。**

    ⚠️ 只列**真的變了**的：一份把沒改的也列進去的清單，等於沒有清單。
    """
    changed, values = [], {}
    for key in sent_keys:
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        changed.append(key)
        if key in _AUDIT_NEVER_VALUE_FIELDS:
            # 🔴 不記值 —— **但一定要記它變過**，
            # 否則換金鑰這件事完全無跡可循。
            continue
        if key in _AUDIT_MASKED_VALUE_FIELDS:
            values[key] = {"from": _audit_tail(old), "to": _audit_tail(new)}
        elif key == "locations":
            # 📌 據點是一整個陣列 ⇒ 只記「幾筆、名字是什麼」，
            # 不把整包（含銀行欄位）倒進稽核。
            values[key] = {
                "from": [str(l.get("name") or "") for l in (old or [])
                         if isinstance(l, dict)],
                "to": [str(l.get("name") or "") for l in (new or [])
                       if isinstance(l, dict)],
            }
        elif isinstance(new, (str, int, float, bool)) or new is None:
            values[key] = {"from": old, "to": new}
    return {"changed": changed, "values": values}


def _ui_is_wizard(request) -> bool:
    """公司設定精靈（company-setup-wizard.html）的請求帶 `X-Motrix-Ui: wizard`：只用來讓稽核看得出「是精靈存的還是設定頁存的」，不影響任何判斷。
    ⚠️ 用 `Request` 讀、不宣告成 `Header(...)` 參數：宣告了會進 OpenAPI，路由表 golden（route_table_golden.json）要跟著重錄；這個標記不是 API 契約。"""
    return str(request.headers.get("X-Motrix-Ui") or "").strip().lower() == "wizard"


@router.put("/api/settings/company-profile")
def set_company_profile(body: CompanyProfile, request: Request, authorization: str = Header(None)):
    """部分更新：**這次沒送的欄位保留現值。**

    🔴 原本是 `body.model_dump()` 整筆覆蓋，而 `CompanyProfile` 每個欄位都有
    `= ''` 預設 ⇒ **任何沒送齊欄位的呼叫端，會把沒送的欄位清成空字串**，
    而且**不會報錯**。畫面上是「欄位都在、只是空的」——
    跟「新裝的機器還沒填」長得一模一樣。
    ⚠️ 具體情境不是假想：一個在部署**之前**就開著的分頁（跑的是舊 JS，
    不知道有 `address`），存一次檔就把 address 清掉了。

    ## ⚠️ 這裡不能用 `key in body`

    收的是 **Pydantic 模型不是 dict** ⇒ Pydantic 會先把沒送的欄位填成 `''`，
    進到這裡時「沒送」與「送了空字串」**已經被壓成同一個值**。
    （`routers/tender_radar.py` 那邊收的是 `dict = Body(...)`，所以那邊
    `key in body` 成立——**兩邊不一樣，抄過來會失效而且安靜。**）

    ⇒ 用 `model_fields_set`（這次請求真的送了哪幾個），形狀照 `suppliers.py:106`。
    📌 那裡的註解 2026 年就寫著同一件事：「不知道有這個欄位的舊前端，
    不應該因為存了一次供應商就把它清掉。」**全庫只有那一處在用它。**

    🔑 而「明確送空字串」必須真的清掉（不可以寫成「空字串一律忽略」），
    否則使用者**永遠刪不掉**填錯的銀行帳號。
    **「沒送」與「送了空字串」是兩件事。**
    """
    # 🔴 SA1：**只有 superadmin**，不接受「持有 settings 模組」。
    #
    # ⚠️ `require_superadmin=True` 這個參數名**說的不是它做的事** ——
    # 它真正的意思是「superadmin **或** 持有那個模組的人」。
    # ☠️ 而它之所以到今天才被看見，**就是因為那個名字讀起來已經像是關緊了。**
    #
    # 實際後果：`automation` 是 `role=viewer` 而 `modules` 含 `settings`
    # ⇒ **它改得動匯款帳號** —— 而那個號碼就印在寄給客戶的請款單上。
    # 📌 不傳 `module` ⇒ 只剩 superadmin 那一條路。
    me = _require_user(authorization, require_superadmin=True)
    # 🔴 **先驗證，再寫入。** 「回了錯誤碼」與「沒有存進去」是兩件事——
    # 一邊驗一邊寫的話，使用者會看到 422 而值已經生效了。
    _check_office_coord(body)
    cur = {**_COMPANY_PROFILE_DEFAULT,
           **(_get_setting("company_profile", {}) or {})}
    sent = body.model_dump(include=body.model_fields_set)
    # 2026-11-13 公司對外信箱：格式不對 ⇒ 422（先驗再寫）；網域只做提醒（回 emailHint），不擋存檔
    _email_hint = ""
    if "external_email" in sent:
        from helpers import quote_email as _qe
        sent["external_email"] = str(sent["external_email"] or "").strip()
        if sent["external_email"] and not _qe.valid(sent["external_email"]):
            raise HTTPException(422, "公司對外信箱的格式不正確（例：service@your-company.com）")
        _email_hint = _qe.domain_hint(sent["external_email"], (cur.get("email") or ""))
    # 🔴 **收到遮蔽字 ⇒ 視為沒送。**
    #
    # ☠️ 遮蔽帶出來的缺陷，而它**完全安靜**：設定頁最自然的寫法是
    # 「載入時填進輸入框、存檔時整包送出」⇒ 那串 `••••••••ab12`
    # 會被寫回設定，**把真金鑰蓋掉**。
    # 而症狀是：使用者改了**銀行帳號**存檔 ⇒ 幾天後「附近廠商」變成未啟用
    # ⇒ 🔑 **沒有人會把那兩件事連起來。**
    #
    # 📌 為什麼是後端擋而不是「前端不要送」：
    # **前端會回歸**（換一個人寫、複製貼上另一頁的存檔函式），
    # 而這個缺陷**不會有任何錯誤訊息**。
    # ⚠️ 與「空字串＝明確清除」不衝突：**遮蔽字不是空字串**。
    for field in _MASKED_FIELDS:
        if field in sent and _looks_masked(sent[field]):
            sent.pop(field)
    if "locations" in sent:
        # 🔴 **驗證與配發 id 在寫入之前**（同 `_check_office_coord` 的理由：
        # 「回了錯誤碼」與「沒有存進去」是兩件事）。
        locations = _clean_locations(sent["locations"], cur.get("locations"))
        # 🔴 QL11：**擋在寫入之前**（同 `_clean_locations` 的理由：
        # 「回了錯誤碼」與「沒有存進去」是兩件事）。
        # ⚠️ 也排在 `_fill_location_coords()` 之前 —— 那一支會對外查地址，
        #    而一個注定要被擋下來的請求不該先去打 Nominatim。
        _guard_removed_locations(locations, cur.get("locations"))
        _fill_location_coords(locations)
        sent["locations"] = locations
        # 🔴 **舊欄位由 `locations[0]` 導出，在這裡寫入。**
        # ⚠️ 不讓前端兩邊各寫一次 —— 那就是「兩個地方都能編輯同一件事」。
        # 📌 空清單 ⇒ 三個欄位清空（那是合法狀態：還沒設定）。
        primary = locations[0] if locations else None
        sent["address"] = primary["address"] if primary else ""
        sent["office_lat"] = primary.get("lat") if primary else None
        sent["office_lon"] = primary.get("lon") if primary else None
    for edited, shadows in _PROFILE_EDIT_SHADOWS.items():
        if edited in sent:
            for alias in shadows:
                if alias in cur:
                    sent[alias] = sent[edited]
    confirm_identity = bool(sent.pop("confirmIdentity", None))
    value = {**cur, **sent}
    if not confirm_identity:
        _guard_reconfirm(cur, value)
    if confirm_identity:
        # 🔴 確認前先驗（同「先驗證，再寫入」）：被拒 ⇒ 422、什麼都不存
        from helpers import company_setup as _cs
        missing = _cs.required_problems(value)
        if missing:
            raise HTTPException(422, "必要欄位未完成：" + "、".join(missing))
        if _cs.is_developer_identity(value) and _cs.signed_file_state(value) != "valid":
            raise HTTPException(422, "這是 MOTRIX 開發者的公司資料，請改成貴公司的名稱與統一編號")
    _set_setting("company_profile", value)
    # 🔴 SA2：稽核要記**哪些欄位變了**，金錢／身分欄位連前後值（遮成末四碼）。
    # ⚠️ `target_label` 仍然放公司名（那是「這筆紀錄講的是哪個對象」），
    # 而**真正回答「改了什麼」的是 `detail`** —— 那個參數在這裡從來沒被傳過。
    _detail = _profile_audit_detail(cur, value, sent.keys())
    if _ui_is_wizard(request):
        _detail["ui"] = "wizard"
    _audit(_tok(authorization), "settings.company_profile.update", "settings",
           "company_profile", value.get("name", ""),
           detail=_detail)
    if confirm_identity:
        from helpers import company_setup as _cs
        from db import get_db as _gdb
        conn = _gdb()
        try:
            try:
                rec = _cs.confirm(conn, me.get("username", ""))
            except _cs.ConfirmRefused as e:          # 上面已先驗；這裡只剩安裝識別檔寫不進去
                raise HTTPException(422, str(e))
            conn.commit()
        finally:
            conn.close()
        _cs.reset_cache()
        _audit(_tok(authorization), "settings.company_identity.confirm", "settings", "company_profile",
               value.get("name", ""),
               detail=dict({"fields_hash": rec["fields_hash"], "via": rec["via"]}, **({"ui": "wizard"} if _ui_is_wizard(request) else {})))
        return {"ok": True, "confirmed": True}
    return {"ok": True, "emailHint": _email_hint} if _email_hint else {"ok": True}


RECONFIRM_CODE = "company_setup_reconfirm"


def _guard_reconfirm(cur: dict, value: dict) -> None:
    """D CG5-S1：已確認的安裝，一般「儲存」若會改動必要欄位（名稱／統編／電話或 email）⇒ 確認紀錄立即失效、
    全公司 428。⇒ 不存，回 409 `company_setup_reconfirm`，設定頁改成「儲存並確認」（同一個請求帶 confirmIdentity）。
    只在「現在的確認紀錄對得上現在的欄位」時才擋（本來就未確認 ⇒ 照常存）。判定出錯 ⇒ 不擋（不因閘門故障擋存檔）。"""
    from helpers import company_setup as _cs
    from db import get_db as _gdb
    try:
        conn = _gdb()
        try:
            rec = _cs._get(conn, _cs.CONFIRMATION_SETTING)
        finally:
            conn.close()
        old_hash = _cs.fields_hash(cur)
        blocks = (isinstance(rec, dict) and rec.get("fields_hash") == old_hash
                  and _cs.fields_hash(value) != old_hash)
    except Exception:  # noqa: BLE001
        logger.exception("company_setup: 重新確認判定失敗（不擋存檔）")
        return
    if blocks:
        raise HTTPException(409, {"code": RECONFIRM_CODE,
                                  "message": "這次修改了本公司必要欄位（公司名稱／統一編號／電話或 email）。"
                                             "儲存後其他人會暫停使用系統直到重新確認 ⇒ 請勾選確認後按「儲存並確認本公司資料」"})


@router.get("/api/settings/company-setup/status")
def company_setup_status(authorization: str = Header(None)):
    """本公司資料設定狀態（所有登入者可讀；只回判定結果與缺漏欄位名，不回任何公司資料值）。
    configured: null ＝判定失敗（Q7＝C：一般功能照常、含本公司資料的輸出暫停）。"""
    user = _require_user(authorization)
    from helpers import company_setup as _cs
    from db import get_db as _gdb
    conn = _gdb()
    try:
        kind, st = _cs.gate(conn)
        conn.commit()
    finally:
        conn.close()
    can_fix = user.get("role") == "superadmin"
    if kind == _cs.GATE_UNDETERMINED:
        return {"configured": None, "reason": _cs.STATUS_ERROR, "canFix": can_fix, "message": _cs.MSG_UNDETERMINED}
    grace = (st or {}).get("grace")
    out = {"configured": bool(st.get("configured")), "reason": st.get("reason"), "via": st.get("via"),
           "missing": st.get("missing") or [], "developer": bool(st.get("developer")) if can_fix else None,
           "grace": {"until": grace.get("until")} if grace else None, "canFix": can_fix,
           "settingsUrl": _cs.SETTINGS_URL}
    if can_fix:
        # CG-S5：只有一位最高管理者 ⇒ 設定頁建議再設一位（唯一的人不在時只剩本機暫時放行）
        conn = _gdb()
        try:
            from helpers import config_ledger as _cl
            out["superadminCount"] = len(_cl.real_superadmins(conn))      # 展示帳號不算（建議再設一位真人最高管理者）
        finally:
            conn.close()
    return out


# ── Quotation default payment terms ───────────────────────────────────────────

# 2026-09-24（N13）：內容搬到 modules/case/quote_terms.py::DEFAULT_TERMS（唯一來源）。
# 2026-09-26（M01-PLAN §3-8 CA-O4）：那是 M01 的檔 ⇒ 改經 M01 提供者 `case.default_terms`，L1 不 import M01。
#: M01 不在時條款端點的說明（§B-4：說出原因，不回空白條款）
QUOTE_TERMS_UNAVAILABLE = "案件模組未安裝：報價單預設條款不提供"


def _quote_default_terms():
    """M01 的五欄預設條款（dict 複本）；M01 不在 ⇒ None。"""
    from core import registry as _registry
    prov = _registry.single_provider("case.default_terms")
    return prov() if prov is not None else None


class PaymentTermsBody(BaseModel):
    text: str = ''


@router.get("/api/settings/payment-terms")
def get_default_payment_terms(authorization: str = Header(None)):
    _require_user(authorization)
    terms = _quote_default_terms()
    return {"text": _get_setting("default_payment_terms", terms["paymentTerms"] if terms else "")}


@router.put("/api/settings/payment-terms")
def set_default_payment_terms(body: PaymentTermsBody, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    try:
        terms = _quote_default_terms()
        old = _get_setting("default_payment_terms", terms["paymentTerms"] if terms else "")   # §15：寫入前記下目前值（與 GET 同一個預設來源）；讀不到不能害儲存失敗
    except Exception:                                                                          # noqa: BLE001
        old = None
        logger.warning("預設付款條件：讀不到舊值，這次儲存不發通知", exc_info=True)
    _set_setting("default_payment_terms", body.text)
    _audit(_tok(authorization), "settings.payment_terms.update", "settings",
           "default_payment_terms", "報價單預設付款條件")
    _notify_quote_terms_changed([("報價單預設付款條件", old or "（空白）", body.text or "（空白）")] if old is not None and (old or "") != (body.text or "") else [], user["username"])
    return {"ok": True}


def _notify_quote_terms_changed(rows, actor):
    """SPEC §15-3：報價條款（條款組、預設付款條件）維持立即生效，**存檔後**發通知（最高管理者全部＋業務；多列合併成一則）。
    `rows`＝[(label, 舊白話值, 新白話值)]，空 ⇒ 不發。永不丟例外。"""
    try:
        if not rows:
            return
        from helpers import settings_notify as SN
        with SN.batch():
            for label, o, n in rows:
                SN.notify_change("quote_terms", label, o, n, actor=actor, risk="ops", roles=("業務",), link="quotation-form.html")
    except Exception:                                                  # noqa: BLE001
        logger.warning("報價條款變更通知失敗（設定已存好）", exc_info=True)


def _quote_terms_change_rows(old, new):
    """條款組整組覆寫前後比對（以 key 對應）⇒ 通知列：新增／刪除／改名／內容修改／預設組改變。"""
    olds = {p.get("key"): p for p in (old.get("presets") or []) if isinstance(p, dict)}
    news = {p.get("key"): p for p in (new.get("presets") or []) if isinstance(p, dict)}
    q = lambda names: "".join("「%s」" % n for n in names)
    rows = []
    added = [news[k].get("name") for k in news if k not in olds]
    gone = [olds[k].get("name") for k in olds if k not in news]
    if added:
        rows.append(("報價條款組／新增", "（無）", q(added)))
    if gone:
        rows.append(("報價條款組／刪除", q(gone), "（已刪除）"))
    for k in news:
        if k in olds and olds[k].get("name") != news[k].get("name"):
            rows.append(("報價條款組／改名", q([olds[k].get("name")]), q([news[k].get("name")])))
    edited = []
    for k in news:
        if k in olds:
            fields = [f for f in _TERMS_FIELDS if (olds[k].get(f) or "") != (news[k].get(f) or "")]
            if fields:
                edited.append("「%s」" % news[k].get("name"))
    if edited:
        rows.append(("報價條款組／內容修改", "（舊內容）", "".join(edited)))
    nm = lambda d, key: next((p.get("name") for p in (d.get("presets") or []) if p.get("key") == key), "（無）")
    if (old.get("defaultKey") or "") != (new.get("defaultKey") or ""):
        rows.append(("報價條款組／預設條款組", q([nm(old, old.get("defaultKey"))]), q([nm(new, new.get("defaultKey"))])))
    return rows


# ── Edge path setting ─────────────────────────────────────────────────────────

@router.get("/api/settings/edge-path")
def get_edge_path_setting(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    configured = (_get_setting("edge_path") or "").strip()
    try:
        resolved = _get_edge_path()
    except RuntimeError:
        resolved = ""
    return {"configured": configured, "resolved": resolved}


@router.patch("/api/settings/edge-path")
def set_edge_path_setting(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    path = (body.get("path") or "").strip()
    if path and not os.path.exists(path):
        raise HTTPException(400, f"路徑不存在：{path}")
    _set_setting("edge_path", path)
    _audit(_tok(authorization), "settings.edge_path.update", "settings", "edge_path",
           path or "（清空，使用自動偵測）")
    notify_module_activity("系統設定", "變更 Edge 路徑", actor.get("display_name") or actor["username"],
                            path or "（清空，使用自動偵測）", "notification-settings.html")
    return {"ok": True}


# ── PDF base path setting ─────────────────────────────────────────────────────

@router.get("/api/settings/pdf-base-path")
def get_pdf_base_path_setting(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from pdf_gen import _PDF_BASE_DEFAULT, _get_pdf_base
    configured = (_get_setting("pdf_base_path") or "").strip()
    return {"configured": configured, "resolved": _get_pdf_base(), "default": _PDF_BASE_DEFAULT}


@router.patch("/api/settings/pdf-base-path")
def set_pdf_base_path_setting(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    path = (body.get("path") or "").strip()
    if path and not os.path.isdir(path):
        raise HTTPException(400, f"目錄不存在：{path}")
    _set_setting("pdf_base_path", path)
    _audit(_tok(authorization), "settings.pdf_base_path.update", "settings", "pdf_base_path",
           path or "（清空，使用預設路徑）")
    notify_module_activity("系統設定", "變更 PDF 存檔路徑", actor.get("display_name") or actor["username"],
                            path or "（清空，使用預設路徑）", "notification-settings.html")
    return {"ok": True}


# ── WebAuthn RP ID / Origin settings ──────────────────────────────────────────
# 2026-09-10（f8198e9）從環境變數改成這裡的 system_settings 可動態設定。
# 這兩個值填錯的代價特別高，所以下面的驗證不是形式主義：
#   - RP ID 必須是「純網域名稱」（不含 scheme／port／路徑）
#   - Origin 必須是完整來源（scheme://host[:port]）
#   - Origin 的 host 必須等於 RP ID，或是它的子網域
# 任何一條不成立，瀏覽器只會丟一句沒有上下文的 "invalid domain"／
# SecurityError，看起來像前端壞掉——而這正是 f8198e9 這次改動想消滅的症狀。
# 與其讓使用者在瀏覽器主控台猜，不如在存檔當下就擋掉並說清楚哪裡不對。

def _require_passkey_enabled() -> None:
    """Passkey 總開關守門——**轉呼叫** `routers/auth.py` 的同名函式。

    刻意不在這裡複製那三行：開關只能有一個判斷點，兩份遲早會分岔（其中一邊
    被改成 403、或忘了跟著恢復）。函式內 import 是為了避開 router 之間的
    模組層相依。開關本身在 `helpers/auth.py::PASSKEY_ENABLED`。
    """
    from routers.auth import _require_passkey_enabled as _guard
    _guard()


def _validate_webauthn_pair(rp_id: str, origin: str) -> None:
    """RP ID／Origin 的格式與相依關係檢查，不合規直接 400。"""
    import ipaddress as _ipaddress
    import re as _re
    from urllib.parse import urlparse as _urlparse

    if _re.search(r"[:/]", rp_id):
        raise HTTPException(400, f"RP ID 只能是網域名稱本身，不要含 http(s):// 或連接埠（收到：{rp_id}）")
    if not _re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*", rp_id):
        raise HTTPException(400, f"RP ID 不是合法的網域名稱（收到：{rp_id}）")

    # IP 位址不能當 RP ID。W3C WebAuthn 規格要求 RP ID 是「可註冊網域後綴」，
    # IP 位址不具備這個性質，Chrome/Edge/Safari 一律直接拒絕註冊。
    # 這一條特別容易踩到：這台正式機平常就是用 172.16.10.177:666 存取，
    # 很自然會想直接把 IP 填進去——填了會存得進資料庫、前端 Passkey 按鈕
    # 也會亮起來（configured=true），但實際點下去只會拿到一句沒有上下文的
    # SecurityError，看起來像功能壞掉。必須先有內部 DNS 名稱指向這台機器。
    try:
        _ipaddress.ip_address(rp_id)
    except ValueError:
        pass  # 不是 IP，正常情況
    else:
        raise HTTPException(
            400,
            f"RP ID 不能是 IP 位址（收到：{rp_id}）。WebAuthn 規格要求 RP ID 是可註冊的網域"
            f"後綴，瀏覽器會直接拒絕 IP。請先在內部 DNS 建一個指向這台主機的名稱"
            f"（例如 motrix.example.local），再用該名稱設定。"
        )

    parsed = _urlparse(origin)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise HTTPException(400, f"Origin 必須是完整來源，例如 https://motrix.example.local:666（收到：{origin}）")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise HTTPException(400, f"Origin 不可包含路徑或查詢字串（收到：{origin}）")

    host = parsed.hostname.lower()
    rp = rp_id.lower()
    if host != rp and not host.endswith("." + rp):
        raise HTTPException(
            400,
            f"Origin 的主機（{host}）必須等於 RP ID（{rp}）或是它的子網域，"
            f"否則瀏覽器會拒絕註冊 Passkey。"
        )
    # localhost 是 WebAuthn 規格唯一允許走 http 的例外；其餘一律要 https，
    # 否則瀏覽器同樣直接拒絕（這台正式機本來就已經是 HTTPS，見 §1）。
    if parsed.scheme == "http" and host != "localhost":
        raise HTTPException(400, "除了 localhost 之外，Origin 必須是 https://（瀏覽器規格要求）")


@router.get("/api/settings/webauthn-config", dependencies=[Depends(_require_passkey_enabled)])
def get_webauthn_config(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        cred_count = conn.execute("SELECT COUNT(*) AS c FROM webauthn_credentials").fetchone()["c"]
    finally:
        conn.close()
    return {
        "rp_id": _get_setting("webauthn_rp_id") or "",
        "origin": _get_setting("webauthn_origin") or "",
        # 讓設定頁能提醒「改了會讓現有 N 張 Passkey 失效」——見下方 PATCH 的說明
        "credentialCount": cred_count,
    }


@router.patch("/api/settings/webauthn-config", dependencies=[Depends(_require_passkey_enabled)])
def set_webauthn_config(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    rp_id = (body.get("rp_id") or "").strip()
    origin = (body.get("origin") or "").strip()
    if (rp_id and not origin) or (origin and not rp_id):
        raise HTTPException(400, "RP ID 與 Origin 必須同時設定或同時清空")
    if rp_id:
        _validate_webauthn_pair(rp_id, origin)

    # 既有 Passkey 是被瀏覽器綁在「註冊當下那個 RP ID」上的，改動 RP ID 之後
    # 那些憑證會在下次登入時直接失效，而且**無法救回**（綁定在瀏覽器端，不在
    # 我們手上）。這裡不擋（第一次設定本來就必須能寫入，superadmin 也有權決定），
    # 但把受影響的張數與人數回傳、寫進稽核，讓「使用者突然說 Passkey 不能用了」
    # 這種回報有跡可循。
    #
    # 2026-09-11（DB v74）：`webauthn_credentials` 補上 rp_id 欄位之後，這裡從
    # 「回報全表張數」改成**精準計算真正會失效的那幾張**。原本的作法在只有一種
    # RP ID 時剛好等於正確答案，但只要出現過兩種以上就會高估——而且說不出是誰的。
    previous_rp = _get_setting("webauthn_rp_id") or ""
    invalidated = 0
    affected_users = 0
    if previous_rp and previous_rp != rp_id:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c, COUNT(DISTINCT user_id) AS u "
                "FROM webauthn_credentials WHERE rp_id != '' AND rp_id != ?",
                (rp_id,)
            ).fetchone()
            invalidated = row["c"]
            affected_users = row["u"]
        finally:
            conn.close()

    _set_setting("webauthn_rp_id", rp_id)
    _set_setting("webauthn_origin", origin)
    detail = f"rp_id={rp_id}, origin={origin}" if rp_id else "（清空）"
    if invalidated:
        detail += (f"；RP ID 由 {previous_rp} 變更為 {rp_id or '（清空）'}，"
                   f"{affected_users} 位使用者的 {invalidated} 張 Passkey 失效（無法復原，須重新註冊）")
    _audit(_tok(authorization), "settings.webauthn_config.update", "settings", "webauthn", detail)
    notify_module_activity("系統設定", "變更 WebAuthn 設定", actor.get("display_name") or actor["username"],
                            f"rp_id={rp_id}" if rp_id else "（清空）", "notification-settings.html")
    return {"ok": True, "invalidatedCredentials": invalidated, "affectedUsers": affected_users}


# ── Google 額度治理（§16 GB）────────────────────────────────────────────────
#
# 使用者 2026-09-22：「你做一個真實計算器，並讓最高管理者可以依據現在 google 的
# 免費額度去調整，當準備到達上限額度自動寄信並將附近客戶跟查找功能先回歸免費，
# 待月週期結束開放」
#
# 🔑 只有最高管理者改得動（`GB6`，比照 `SA1`）：這幾個欄位決定的是**錢**。
# ⚠️ 反向控制那一題用的是 `role=viewer` ＋ `modules` 含 `settings` ——
#    那正是 §10 查出來的那個真實帳號形狀，所以這裡**不可以**用 `module=` 放行。


class GoogleQuotaBody(BaseModel):
    # 🔴 每一格都可以不送（`Optional` ＋ `None`）：這支端點是**合併**不是覆蓋。
    # ☠️ 整包覆蓋的教訓見 `BK3`：一個沒有人送出的值會被静静打回預設，
    #    而存檔成功、沒有錯誤。
    sku_quotas:         Optional[dict] = None
    monthly_free_quota: Optional[int] = None
    price_per_1000:     Optional[float] = None
    warn_pct:           Optional[int] = None
    hard_pct:           Optional[int] = None
    cycle_start_day:    Optional[int] = None


@router.get("/api/settings/google-quota")
def get_google_quota_setting(authorization: str = Header(None)):
    """設定值 ＋ 真實計算器的數字（`GB5`）。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import geo
    return {
        "settings": geo.quota_settings(),
        "status": geo.quota_status(),
        "calculator": geo.quota_calculator(),
        # 📌 SKU 清單給畫面用。**額度是 per-SKU 而且不 pool** ——
        #    一個「Google 還剩多少」的欄位在 2025-03-01 之後沒有意義。
        "skus": [
            {"key": geo.USAGE_SKU_GEOCODING, "label": "地址定位（Geocoding）"},
            {"key": geo.USAGE_SKU_PLACES_TEXT,
             "label": "附近商家搜尋（Places Text Search，尚未啟用）"},
            {"key": geo.USAGE_SKU_PLACE_DETAILS,
             "label": "商家詳細資料（Place Details，尚未啟用）"},
            {"key": geo.USAGE_SKU_DYNAMIC_MAPS,
             "label": "地圖載入（Dynamic Maps；以開地圖次數近似，實際以 Google Cloud Console 為準）"},
        ],
    }


@router.put("/api/settings/google-quota")
def set_google_quota_setting(body: GoogleQuotaBody,
                             authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    from helpers import geo

    sent = {k: v for k, v in body.model_dump().items()
            if k in body.model_fields_set}
    if not sent:
        raise HTTPException(400, "沒有送出任何要變更的欄位")

    # ⚠️ 留空（`None`）與填 0 是**兩件事**（`GB7`）：
    #    留空 ＝ 不管制；填 0 ＝ 一次都不准查。
    # ☠️ 所以額度欄位**不做「沒填就當 0」的正規化** —— `None` 要原樣存下去。
    for key in ("warn_pct", "hard_pct"):
        if key in sent and sent[key] is not None:
            if not 1 <= int(sent[key]) <= 100:
                raise HTTPException(400, f"{key} 需介於 1～100 之間")
    if "cycle_start_day" in sent and sent["cycle_start_day"] is not None:
        # 上限 28：29~31 在二月不存在，而那種設定會讓某些月份整個月沒有起算日。
        if not 1 <= int(sent["cycle_start_day"]) <= 28:
            raise HTTPException(400, "cycle_start_day 需介於 1～28 之間"
                                     "（29 以後的日子二月沒有）")
    for key in ("monthly_free_quota",):
        if key in sent and sent[key] is not None and int(sent[key]) < 0:
            raise HTTPException(400, f"{key} 不可以是負數")
    if "sku_quotas" in sent and sent["sku_quotas"] is not None:
        for sku, value in (sent["sku_quotas"] or {}).items():
            if value is None:
                continue            # 該 SKU 不管制
            if not isinstance(value, int) or value < 0:
                raise HTTPException(400, f"SKU `{sku}` 的額度要是非負整數或留空")

    value = {**geo.quota_settings(), **sent}
    _set_setting(geo.QUOTA_SETTING, value)

    # 📌 稽核只記「改了哪幾項」與新值。這裡沒有祕密（額度與百分比不是憑證），
    #    所以值可以留；金鑰本身在另一支端點，那裡連末四碼都不記。
    _audit(_tok(authorization), "settings.google_quota.update", "settings",
           "google_quota",
           "；".join("%s=%s" % (k, sent[k]) for k in sorted(sent)))
    return {"ok": True, "status": geo.quota_status()}


# ── 儲存位置（CORE-SPEC 裁示表「儲存位置可設定」，2026-09-28）────────────────────
# 三個位置（雲端存檔根目錄、個資資料夾、更新交付資料夾）由最高管理者設定；留空＝照原本自動判斷。
# 解析一律在 helpers.storage_locations（這裡只做讀寫與驗證）。本機上傳檔目錄不開放（改位置＝搬資料）。

class StorageLocationsBody(BaseModel):
    """三個鍵都要送（空字串＝自動）；多送或少送 ⇒ 422（寬鬆驗證會靜默丟掉欄位）。"""
    model_config = {"extra": "forbid"}
    archive_root: str
    pii_root: str
    delivery_root: str


class StorageCreateBody(BaseModel):
    model_config = {"extra": "forbid"}
    kind: str
    path: str


@router.get("/api/settings/storage-locations")
def get_storage_locations(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from helpers import storage_locations as SL
    try:
        return {"values": SL.configured(), "status": SL.status(), "labels": SL.LABELS}
    except SL.Unreadable as e:
        raise HTTPException(503, str(e))


@router.put("/api/settings/storage-locations")
def set_storage_locations(body: StorageLocationsBody, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from helpers import storage_locations as SL
    values = {k: getattr(body, k).strip() for k in SL.KINDS}
    problems = SL.validate(values)
    if problems:
        raise HTTPException(400, {"message": "儲存位置沒有通過檢查，未儲存", "problems": problems})
    try:
        before = SL.configured()
    except SL.Unreadable as e:                           # 讀不到現在的設定就不寫（稽核無法記「從什麼改成什麼」）
        raise HTTPException(503, str(e))
    SL.save(values)                                      # 一律寫主庫（demo 模式也不寫到 demo 庫）
    changed = {k: {"from": before.get(k, ""), "to": values[k]} for k in SL.KINDS if before.get(k, "") != values[k]}
    _audit(_tok(authorization), "settings.storage_locations.update", "settings", SL.SETTING_KEY,
           "儲存位置變更：" + ("；".join("%s %s → %s" % (SL.LABELS[k], v["from"] or "（自動）", v["to"] or "（自動）")
                                     for k, v in changed.items()) or "（沒有變更）"))
    return {"values": SL.configured(), "status": SL.status()}


@router.post("/api/settings/storage-locations/create")
def create_storage_location(body: StorageCreateBody, authorization: str = Header(None)):
    """最高管理者明確建立資料夾（背景程式永不自動建）：只建最後一層。畫面同時提醒到雲端硬碟確認共用權限。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import storage_locations as SL
    if body.kind not in SL.KINDS:
        raise HTTPException(400, "不認得的儲存位置：%s" % body.kind)
    try:
        made = SL.create(body.kind, body.path)
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))
    _audit(_tok(authorization), "settings.storage_locations.create", "settings", SL.SETTING_KEY,
           "建立%s資料夾：%s（共用權限請到雲端硬碟確認）" % (SL.LABELS[body.kind], made))
    return {"ok": True, "path": made,
            "notice": "已建立。請到雲端硬碟確認這個資料夾的共用權限（新資料夾會繼承上一層的分享設定）。"}


# ── Backup retention settings ─────────────────────────────────────────────────
# 2026-09-01：本機/雲端備份保留天數原本寫死在 archive.py（見該檔 _BACKUP_RETENTION_
# DEFAULT 註解），使用者要求可調整避免雲端空間被逐年累積的每日/週備份塞爆，改成
# 存進 system_settings.backup_retention，這裡提供 API 讀寫（無對應前端頁面，
# 比照 edge-path／pdf-base-path 這類低頻技術設定的既有慣例，透過 API 直接調整）。

class BackupRetentionBody(BaseModel):
    local_db_keep_days:    Optional[int] = None
    cloud_daily_keep_days: Optional[int] = None
    cloud_weekly_keep_days: Optional[int] = None
    audit_log_keep_days:   Optional[int] = None
    # 2026-09-14 新增的兩個。
    cloud_monthly_keep_days: Optional[int] = None    # 0 = 永久保留（使用者裁示的預設政策）
    local_pre_update_keep:   Optional[int] = None    # 份數，不是天數


@router.get("/api/settings/backup-retention")
def get_backup_retention_setting(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from archive import _backup_retention
    return _backup_retention()


@router.patch("/api/settings/backup-retention")
def set_backup_retention_setting(body: BackupRetentionBody, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    from archive import _backup_retention

    # 🔴🔴 BK3（2026-09-22）：這裡原本是 `body.model_dump()` —— **整包覆蓋**。
    #
    # 那兩個 2026-09-14 才加的欄位有 Pydantic 預設值，而設定頁只送原本四個
    # ⇒ 使用者用 curl 把 `cloud_monthly_keep_days` 設成 1825，
    #   下一個人在設定頁按一次「儲存」，它就**静静變回 0**。
    # 🔑 今天無害，因為 0 剛好就是預設值 —— 而那正是它沒有被發現的原因。
    # ☠️ 〈降級之後它還是會動〉：存檔成功、沒有錯誤，而一個設定被重設了。
    #
    # ⇒ 改成**合併**：只有這次真的送出來的鍵才會蓋掉舊值。
    # 📌 用 `model_fields_set` 不是「值不是 None 就算送了」——
    #    ☠️ 後者的話，一個明確送 `null` 的 client 會被當成沒送，
    #    而那兩件事在語意上不同（〈null 不等於 0〉的同一族）。
    sent = {k: v for k, v in body.model_dump().items()
            if k in body.model_fields_set}
    if not sent:
        raise HTTPException(400, "沒有送出任何要變更的欄位")
    value = {**_backup_retention(), **sent}
    # 三種欄位語意不同，不能再像原本那樣一律套「1～3650 天」：
    #   *_keep_days      天數，至少 1 天
    #   cloud_monthly_*  天數，但 0 有特殊意義＝永久保留（預設政策）
    #   local_pre_update_keep 是「份數」不是天數，上限用 100 份就夠荒謬了
    # ⚠️ 驗證跑在**合併後的完整字典**上，不是只跑在送來的那幾個鍵上：
    # 一個舊的、當時合法而現在超出範圍的值，不應該因為這次沒被送出就溜過去。
    for label, days in value.items():
        if days is None:
            raise HTTPException(400, f"{label} 不可以是空值")
        if label == "local_pre_update_keep":
            if days < 0 or days > 100:
                raise HTTPException(400, f"{label} 需介於 0～100 份之間（0 = 不清理）")
        elif label == "cloud_monthly_keep_days":
            if days < 0 or days > 3650:
                raise HTTPException(400, f"{label} 需介於 0～3650 天之間（0 = 永久保留）")
        elif days < 1 or days > 3650:
            raise HTTPException(400, f"{label} 需介於 1～3650 天之間")
    # 第54班：稽核紀錄是法遵證據，新設定不得低於 365 天（只檢查這次送來的值；舊值不因別的欄位被改而擋住）
    if "audit_log_keep_days" in sent and sent["audit_log_keep_days"] < 365:
        raise HTTPException(400, "audit_log_keep_days 不可低於 365 天（稽核紀錄屬法遵證據）")
    from helpers import settings_groups as _sg, settings_registry as _sr      # noqa: F401
    try:
        _res = _sr.publish("retention", sent, note="備份保留設定（舊端點）", user=actor["username"], reason="變更備份保留設定", actor=actor)
    except _sr.SettingError as e:
        raise HTTPException(400, str(e) + "：" + "；".join(p["message"] for p in e.problems))
    # 稽核由 publish() 在同一交易內寫（立即生效＝settings.retention.update／待生效＝settings.retention.pending）；這裡不再另寫，避免同一次變更兩列
    notify_module_activity("系統設定", "變更備份保留天數", actor.get("display_name") or actor["username"],
                            f"每日{value['cloud_daily_keep_days']}天／週{value['cloud_weekly_keep_days']}天",
                            "notification-settings.html")
    # 縮短保存期限（會更早刪除資料）屬放寬：不立即生效，須另一位最高管理者核准並等確認期間（走設定中心的待生效清單）
    return {"ok": True, "pending": _res.get("pending", []), "warnings": _res.get("warnings", [])}


# ── 報價條款組（2026-09-14 使用者交辦）────────────────────────────────────────
#
# 使用者裁示：「報價單可以增加付款條件的選項，名稱也可以自定義，例如純購料，
# 他有自己的付款條件、驗收標準、保固條件，可由報價人手動點選方塊做切換，
# 只有最高管理者可以點選設為預設付款條件的功能跟建立，像是完工單內單據用語
# 這樣的選項」。
#
# 形狀：`system_settings.quote_terms_presets = {presets: [...], defaultKey: "..."}`
# 每一組 = {key, name, paymentTerms, deliveryTerms, acceptanceTerms,
#           warrantyTerms, afterSales}
#
# **報價單存的是文字不是 key**（前端切換時把五段文字複製進 data_json）：
# 已經開出去的報價單長什麼樣就是什麼樣，不能因為有人事後改了條款組內容
# 或把那組刪掉，就讓歷史單據的條款跟著變。這跟同日做的「單據原始版本存檔」
# 是同一個判準。`termsPresetKey` 只當「這張單是從哪一組起手的」的線索，
# 用來做「與該組不同」的比對提示，不是資料來源。
#
# 讀取端點**不限 superadmin**——報價人要用它切換；寫入才限 superadmin。

_TERMS_FIELDS = ("paymentTerms", "deliveryTerms", "acceptanceTerms",
                 "warrantyTerms", "afterSales")


class QuoteTermsPreset(BaseModel):
    key:             str = ""
    name:            str
    paymentTerms:    str = ""
    deliveryTerms:   str = ""
    acceptanceTerms: str = ""
    warrantyTerms:   str = ""
    afterSales:      str = ""


class QuoteTermsPresetsBody(BaseModel):
    presets:    List[QuoteTermsPreset]
    defaultKey: str = ""


def _quote_terms_presets() -> dict:
    """目前設定；沒設定過時回傳空清單（前端會退回預設條款 DEFAULT_TERMS）。

    **不在這裡自動種一組預設**：「沒有任何設定時」的內容只有一份，兩份一旦分岔
    沒有任何地方會報錯。沒設定＝維持改動前的行為。
    📌 2026-09-24（N13，使用者裁示「預設條款搬到後端當唯一來源」）：那一份原本是
    前端 `quotation-form.html` 的常數，現在的唯一來源是
    **`modules/case/quote_terms.py::DEFAULT_TERMS`**，前端經 `GET /api/settings/quote-terms-defaults`
    取得；送審時後端也用它重算「報價條件已修改」。
    """
    raw = _get_setting("quote_terms_presets", {}) or {}
    if not isinstance(raw, dict):
        return {"presets": [], "defaultKey": ""}
    presets = raw.get("presets")
    if not isinstance(presets, list):
        presets = []
    return {"presets": presets, "defaultKey": raw.get("defaultKey") or ""}


@router.get("/api/settings/quote-terms-defaults")
def get_quote_terms_defaults(authorization: str = Header(None)):
    """系統內建的五欄預設條款（唯一來源 modules/case/quote_terms.py，N13）。
    與條款組同級：公司對外條款，登入即可讀。付款條件的「目前預設」另見 /api/settings/payment-terms。"""
    _require_user(authorization)
    terms = _quote_default_terms()
    if terms is None:
        raise HTTPException(404, QUOTE_TERMS_UNAVAILABLE)
    try:
        from helpers import clause_titles as _CT
        titles = _CT.active_titles()                              # S-Q2：旗標關／沒有已發布範本 ⇒ None ⇒ 不多任何鍵
    except Exception:                                              # noqa: BLE001
        titles = None
    if titles:
        terms = dict(terms)
        terms["titles"] = titles
    return terms


@router.get("/api/settings/quote-terms-presets")
def get_quote_terms_presets(authorization: str = Header(None)):
    """報價人要靠它切換條款組，所以只要求登入（內容不是機密，是公司對外條款）。"""
    _require_user(authorization)
    return _quote_terms_presets()


# ── 估價單自己的條款（2026-11-13，使用者：「報價單有獨立條款，估價單也要」）──────────────────────────────
# 報價單的條款組（system_settings.quote_terms_presets）與預設付款條件（default_payment_terms）**逐位元不變**；
# 估價單另有一組：`estimate_terms_presets`（同形：{presets, defaultKey}）與 `estimate_default_payment_terms`。
# 升級時由 case migration 0011 把「目前報價單的值」複製成估價單的初始值（既有行為不變），之後兩邊各自改。
# 五欄預設文字（DEFAULT_TERMS，沒有任何設定時的內建文字）兩邊共用同一份內建值——它不是設定，沒有各自改的入口。
# 上面報價單的 PUT 沒動（留給 S5 通知那條線）；清洗邏輯另寫在 `_clean_terms_presets`，之後要合併再收斂。

def _estimate_terms_presets() -> dict:
    raw = _get_setting("estimate_terms_presets", {}) or {}
    if not isinstance(raw, dict):
        return {"presets": [], "defaultKey": ""}
    presets = raw.get("presets")
    if not isinstance(presets, list):
        presets = []
    return {"presets": presets, "defaultKey": raw.get("defaultKey") or ""}


def _clean_terms_presets(body: "QuoteTermsPresetsBody"):
    """整組覆寫的驗證與清洗（與報價單那支同規則）⇒ (cleaned, default_key)。"""
    if len(body.presets) > 30:
        raise HTTPException(400, "條款組最多 30 組")
    seen, cleaned = set(), []
    for p in body.presets:
        name = (p.name or "").strip()
        if not name:
            raise HTTPException(400, "條款組名稱不可空白")
        if len(name) > 30:
            raise HTTPException(400, f"條款組名稱過長（{name[:10]}…），上限 30 字")
        key = (p.key or "").strip() or uuid.uuid4().hex[:8]
        if key in seen:
            raise HTTPException(400, f"條款組 key 重複：{key}")
        seen.add(key)
        item = {"key": key, "name": name}
        for f in _TERMS_FIELDS:
            v = getattr(p, f) or ""
            if len(v) > 5000:
                raise HTTPException(400, f"「{name}」的{f}內容過長（上限 5000 字）")
            item[f] = v
        cleaned.append(item)
    default_key = (body.defaultKey or "").strip()
    if default_key and default_key not in seen:
        default_key = ""                                           # 預設那組被刪 ⇒ 落到第一組（同報價單）
    if not default_key and cleaned:
        default_key = cleaned[0]["key"]
    return cleaned, default_key


@router.get("/api/settings/estimate-terms-presets")
def get_estimate_terms_presets(authorization: str = Header(None)):
    """估價單的條款組（登入即可讀；內容是公司對外條款）。"""
    _require_user(authorization)
    return _estimate_terms_presets()


@router.put("/api/settings/estimate-terms-presets")
def set_estimate_terms_presets(body: QuoteTermsPresetsBody, authorization: str = Header(None)):
    """估價單條款組整組覆寫（最高管理者）。只動 `estimate_terms_presets`，報價單的條款組不受影響。"""
    actor = _require_user(authorization, require_superadmin=True)
    cleaned, default_key = _clean_terms_presets(body)
    value = {"presets": cleaned, "defaultKey": default_key}
    _set_setting("estimate_terms_presets", value)
    default_name = next((p["name"] for p in cleaned if p["key"] == default_key), "（無）")
    _audit(_tok(authorization), "settings.estimate_terms_presets.update", "settings",
           "estimate_terms_presets", f"估價條款組共 {len(cleaned)} 組，預設為「{default_name}」")
    notify_module_activity("系統設定", "變更估價條款組", actor.get("display_name") or actor["username"],
                            f"{len(cleaned)} 組，預設「{default_name}」", "quotation-form.html")
    return value


@router.get("/api/settings/estimate-payment-terms")
def get_estimate_default_payment_terms(authorization: str = Header(None)):
    _require_user(authorization)
    terms = _quote_default_terms()
    return {"text": _get_setting("estimate_default_payment_terms", terms["paymentTerms"] if terms else "")}


@router.put("/api/settings/estimate-payment-terms")
def set_estimate_default_payment_terms(body: PaymentTermsBody, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _set_setting("estimate_default_payment_terms", body.text)
    _audit(_tok(authorization), "settings.estimate_payment_terms.update", "settings",
           "estimate_default_payment_terms", "估價單預設付款條件")
    return {"ok": True}


@router.put("/api/settings/quote-terms-presets")
def set_quote_terms_presets(body: QuoteTermsPresetsBody, authorization: str = Header(None)):
    """整組覆寫（建立／改名／改內容／刪除／設預設都走這一支）。

    整組覆寫而不是逐筆 CRUD：這份設定最多十來組、只有 superadmin 會動、
    而且前端本來就是把整份清單抓下來編輯。逐筆 CRUD 要多三支端點與一組
    併發處理，換不到任何東西。
    """
    actor = _require_user(authorization, require_superadmin=True)

    if len(body.presets) > 30:
        raise HTTPException(400, "條款組最多 30 組")

    seen, cleaned = set(), []
    for p in body.presets:
        name = (p.name or "").strip()
        if not name:
            raise HTTPException(400, "條款組名稱不可空白")
        if len(name) > 30:
            raise HTTPException(400, f"條款組名稱過長（{name[:10]}…），上限 30 字")
        key = (p.key or "").strip() or uuid.uuid4().hex[:8]
        if key in seen:
            raise HTTPException(400, f"條款組 key 重複：{key}")
        seen.add(key)
        item = {"key": key, "name": name}
        for f in _TERMS_FIELDS:
            v = getattr(p, f) or ""
            if len(v) > 5000:
                raise HTTPException(400, f"「{name}」的{f}內容過長（上限 5000 字）")
            item[f] = v
        cleaned.append(item)

    default_key = (body.defaultKey or "").strip()
    if default_key and default_key not in seen:
        # 刪掉了被設為預設的那一組 → 靜默落到第一組，而不是留一個指向不存在
        # 的 key（那會讓新報價單完全拿不到預設條款，而且看不出為什麼）
        default_key = ""
    if not default_key and cleaned:
        default_key = cleaned[0]["key"]

    value = {"presets": cleaned, "defaultKey": default_key}
    try:
        old_value = _quote_terms_presets()                          # §15：寫入前記下目前值，存檔後通知「誰改了什麼」；讀不到不能害儲存失敗
    except Exception:                                               # noqa: BLE001
        old_value = None
        logger.warning("報價條款組：讀不到舊值，這次儲存不發通知", exc_info=True)
    _set_setting("quote_terms_presets", value)
    default_name = next((p["name"] for p in cleaned if p["key"] == default_key), "（無）")
    _audit(_tok(authorization), "settings.quote_terms_presets.update", "settings",
           "quote_terms_presets",
           f"報價條款組共 {len(cleaned)} 組，預設為「{default_name}」")
    # 使用者裁示（2026-11-13）：條款組變更只發「設定變更通知」一則（誰改了什麼、舊→新）；原本的 notify_module_activity
    # （「系統設定：變更報價條款組」email＋群組 LINE module_activity）拿掉，不再並存發兩則。
    if old_value is not None:
        _notify_quote_terms_changed(_quote_terms_change_rows(old_value, value), actor["username"])
    return value


# ── Cloud backup storage target（2026-09-07，架構地圖 §6.4）────────────────────
# 選擇備份要寫去哪裡：本機掛載的雲端硬碟磁碟機（預設，沿用 archive.py 既有邏輯，
# 已知磁碟機代號會漂移）或 S3 相容物件儲存（AWS S3／Backblaze B2 等，見
# cloud_storage.py）。**憑證一律不存這裡**——走 boto3 標準憑證鏈（環境變數／
# ~/.aws/credentials／instance profile），這裡只存 bucket/endpoint/region/prefix
# 2026-09-11 更正：這段原本寫「這類非機密設定值，無對應前端頁面（比照
# edge-path/pdf-base-path 等技術設定慣例，透過 API 直接調整）」——**那不是慣例，
# 是還沒做**。把「還沒做」寫成「慣例」之後，四支設定端點就這樣一直沒有入口，
# 直到打包新增的入口檢查（check_endpoint_entrypoints.py）把它們掃出來。
# 現在四支都有畫面了：company-profile-settings.html 的「系統技術設定」區塊
# （備份保留天數／PDF 存檔根目錄／Edge 路徑／雲端備份目標），superadmin 限定，
# e2e 見 tests/test_e2e_system_settings_ui_2026_09_11.py。

class CloudBackupS3Body(BaseModel):
    bucket: str = ""
    endpoint_url: str = ""
    region: str = "us-east-1"
    prefix: str = "motrix-erp-backups/"


class CloudBackupTargetBody(BaseModel):
    backend: str
    s3: CloudBackupS3Body = CloudBackupS3Body()


@router.get("/api/settings/cloud-backup-target")
def get_cloud_backup_target_setting(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from cloud_storage import cloud_backup_target
    return cloud_backup_target()


@router.get("/api/settings/pii-archive-status")
def get_pii_archive_status(authorization: str = Header(None)):
    """F2 個資存檔（勞報單）雲端資料夾現況——給設定頁「雲端備份」區塊顯示（2026-09-25）。

    `live` 是現在實查的結果；`last` 是排程最後一次記下的狀態（`system_settings.pii_archive_state`）。
    """
    _require_user(authorization, require_superadmin=True)
    import archive
    return {"live": archive.pii_archive_status(),
            "last": _get_setting(archive._PII_STATE_KEY, {}) or {}}


@router.put("/api/settings/cloud-backup-target")
def set_cloud_backup_target_setting(body: CloudBackupTargetBody, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    if body.backend not in ("local_drive", "s3"):
        raise HTTPException(400, "備份目標請選「本機磁碟機」或「S3 相容物件儲存」。")
    if body.backend == "s3" and not body.s3.bucket:
        raise HTTPException(400, "選擇 s3 時 bucket 為必填")
    value = {"backend": body.backend, "s3": body.s3.model_dump()}
    _set_setting("cloud_backup_target", value)
    import cloud_storage
    cloud_storage.reset_s3_client_cache()
    cloud_storage.reset_s3_available_cache()
    _audit(_tok(authorization), "settings.cloud_backup_target.update", "settings", "cloud_backup_target",
           f"備份目標改為 {body.backend}" + (f"（bucket={body.s3.bucket}）" if body.backend == "s3" else ""))
    notify_module_activity("系統設定", "變更雲端備份目標", actor.get("display_name") or actor["username"],
                            body.backend, "notification-settings.html")
    return {"ok": True}


# ── Email notification settings ───────────────────────────────────────────────

_EMAIL_DEFAULTS = {
    "enabled":       False,
    "smtp_host":     "smtp.gmail.com",
    "smtp_port":     587,
    "smtp_user":     "",
    "smtp_password": "",
    "from_name":     "MOTRIX 專案管理系統",
    "base_url":      "",  # 2026-11-13：新安裝不預填內部位址（畫面預填目前網址）；已儲存的值不動。舊預設見 email_notify._LEGACY_DEFAULT_BASE_URL
    "dev_mode":      False,  # 開發機測試模式：寄出信件標題加註「【開發機測試】」，
                             # 存在本機 DB，不隨部署流程移動到正式機（2026-08-26）
}

_MASKED = "••••••••"


@router.get("/api/settings/email-notify")
def get_email_notify(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    cfg = _get_setting("email_notify", {}) or {}
    _p = _get_setting(_EMAIL_WIZARD_PROOF, {}) or {}
    if _p and not _wizard_fresh(_p):                # 過期的測試證明（內含候選密碼）順手清掉
        _set_setting(_EMAIL_WIZARD_PROOF, {})
    safe = {**_EMAIL_DEFAULTS, **cfg}
    safe.pop("admin_emails", None)
    safe["smtp_password"] = _MASKED if cfg.get("smtp_password") else ""
    # Show which admin/superadmin users will receive admin notifications
    from helpers.email_notify import _admin_emails
    safe["admin_email_preview"] = _admin_emails("system_test_mail")
    return safe


@router.put("/api/settings/email-notify")
def set_email_notify(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    current = _get_setting("email_notify", {}) or {}
    incoming = {k: body[k] for k in _EMAIL_DEFAULTS if k in body}
    data = {**_EMAIL_DEFAULTS, **current, **incoming}      # 沒帶的欄位維持原值（不是重設成預設；舊頁面照常運作）
    from helpers import email_setup as _es
    bad = _es.validate_config(data)                  # 批次 3：存之前先檢查格式，白話回報（不是存了之後才在寄信時出錯）
    if bad:
        raise HTTPException(422, bad)
    for k in ("smtp_user", "smtp_host", "base_url", "from_name"):
        if isinstance(data.get(k), str):
            data[k] = data[k].strip()
    if data.get("smtp_password") in ("", _MASKED):
        data["smtp_password"] = current.get("smtp_password", "")
    try:
        new_port, old_port = int(data.get("smtp_port") or 0), int(current.get("smtp_port") or 0)
    except (TypeError, ValueError):
        new_port, old_port = 0, 0
    if new_port != old_port and new_port not in _WIZARD_PORTS:       # 和精靈同一條：寄信埠只准 25／465／587／2525（沒改埠的舊設定照常可存）
        raise HTTPException(422, "寄信埠只能是 25、465、587 或 2525；請向信箱或網域代管廠商確認。")
    # 由「未啟用」改成「啟用」＝一定要有這份設定剛剛測試成功的證明（24 小時內、帳密與主機埠完全相同）；精靈與舊頁面都一樣，伺服器端把關
    if data.get("enabled") and not current.get("enabled") and not _wizard_proof_matches(
            data.get("smtp_host"), data.get("smtp_port"), data.get("smtp_user"), data.get("smtp_password")):
        raise HTTPException(422, "要啟用 Email 通知，請先用上方的「設定公司寄信帳號」寄一封測試信並確認收到；這份設定尚無測試成功。")
    _set_setting("email_notify", data)
    _audit(_tok(authorization), "settings.email_notify.update", "settings",
           "email_notify", "Email 通知設定")
    return {"ok": True}


# ── Google 行事曆設定（2026-08-21，push only Phase 1）─────────────────────────

_GCAL_DEFAULTS = {
    "enabled":       False,
    "client_id":     "",
    "client_secret": "",
    "calendar_id":   "primary",
    "refresh_token": "",
}


@router.get("/api/settings/google-calendar")
def get_google_calendar(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    cfg = _get_setting("google_calendar", {}) or {}
    safe = {**_GCAL_DEFAULTS, **cfg}
    safe["client_secret"] = _MASKED if cfg.get("client_secret") else ""
    safe["connected"] = bool(cfg.get("refresh_token"))
    safe.pop("refresh_token", None)
    # 提示管理員授權時要用哪個 Gmail 帳號（跟寄信用的 SMTP 帳號同一組）
    email_cfg = _get_setting("email_notify", {}) or {}
    safe["smtp_user_hint"] = email_cfg.get("smtp_user", "")
    # 事件種類開關（2026-09-30）：回有效值（缺項＝預設）＋目錄
    from helpers.google_calendar import event_switches, event_types
    safe["events"] = event_switches(cfg)
    safe["eventTypes"] = event_types()
    return safe


def _gcal_event_changes(body: dict, current: dict):
    """驗 body["events"]（{代碼: bool}，只收已知代碼）⇒ (新的 events dict 或 None, [(代碼, 舊, 新)])。不合法 ⇒ 400。"""
    from helpers.google_calendar import EVENT_CODES, event_switches
    if "events" not in body:
        return None, []
    ev = body["events"]
    if not isinstance(ev, dict):
        raise HTTPException(400, "events 必須是 {事件代碼: true/false}")
    bad = [k for k in ev if k not in EVENT_CODES]
    if bad:
        raise HTTPException(400, "未知的事件種類：%s" % "、".join(sorted(map(str, bad))))
    if any(not isinstance(v, bool) for v in ev.values()):
        raise HTTPException(400, "事件開關的值必須是 true 或 false")
    before = event_switches(current)
    stored = dict(current.get("events") if isinstance(current.get("events"), dict) else {})
    stored.update(ev)
    changes = [(c, before[c], ev[c]) for c in EVENT_CODES if c in ev and ev[c] != before[c]]
    return stored, changes


@router.put("/api/settings/google-calendar")
def set_google_calendar(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    current = _get_setting("google_calendar", {}) or {}
    new_events, changes = _gcal_event_changes(body, current)
    data = {k: body[k] for k in _GCAL_DEFAULTS if k in body}
    data = {**_GCAL_DEFAULTS, **current, **data}
    if data.get("client_secret") in ("", _MASKED):
        data["client_secret"] = current.get("client_secret", "")
    # refresh_token 只由一次性授權腳本寫入，這個端點絕不清空/覆蓋它
    data["refresh_token"] = current.get("refresh_token", "")
    if new_events is not None:
        data["events"] = new_events
    _set_setting("google_calendar", data)
    tok = _tok(authorization)
    _audit(tok, "settings.google_calendar.update", "settings",
           "google_calendar", "Google 行事曆設定")
    # 每個事件種類開關的變更各記一筆（誰、哪一種、由什麼改成什麼）
    from helpers.google_calendar import event_types
    labels = {t["code"]: t["label"] for t in event_types()}
    for code, old, new in changes:
        _audit(tok, "settings.google_calendar.event_toggle", "settings", "google_calendar." + code,
               "行事曆事件「%s」%s" % (labels[code], "開啟" if new else "關閉"), {"event": code, "from": old, "to": new})
    return {"ok": True, "changed": [c for c, _o, _n in changes]}


@router.post("/api/settings/google-calendar/test")
def test_google_calendar(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from helpers.google_calendar import create_test_event
    try:
        event_id = create_test_event()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        tid = trace_id()
        logger.exception("google_calendar test event failed trace=%s", tid)
        raise HTTPException(500, f"建立測試事件失敗（代碼 {tid}）")
    _audit(_tok(authorization), 'settings.google_calendar.test', 'settings', 'google_calendar', '測試事件', {'eventId': event_id})
    return {"ok": True, "event_id": event_id}


# ── LINE 通知設定（2026-11-11；channel access token 照 SMTP 密碼慣例：GET 遮罩、PUT 遮罩值＝保留）──────────

# public_base_url（Tunnel 公開網域，LINE Login callback 用）與 include_links（訊息是否帶連結）是**兩個獨立開關**：
# 有公開網域不代表訊息帶連結（PM 裁示）。include_links 預設關，且要有 public_base_url 才能開。
_LINE_DEFAULTS = {"enabled": False, "channel_access_token": "", "public_base_url": "", "include_links": False,
                  "login_channel_id": "", "login_channel_secret": "", "quota_thresholds": [80, 100]}


@router.get("/api/settings/line-notify")
def get_line_notify(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln
    cfg = _get_setting("line_notify", {}) or {}
    if not isinstance(cfg, dict):          # 手改壞的設定值不能讓設定頁 500
        cfg = {}
    safe = {**_LINE_DEFAULTS, **{k: cfg[k] for k in _LINE_DEFAULTS if k in cfg}}
    safe["channel_access_token"] = _ln.mask(cfg.get("channel_access_token"))
    safe["login_channel_secret"] = _ln.mask(cfg.get("login_channel_secret"))
    safe["callback_url"] = _ln.callback_url()       # 要貼進 LINE Login channel 的 Callback URL；沒有對外網址 ⇒ ""
    # 「同時發 LINE」的信件類型開關（只列已接線的類型；預設全關）
    from helpers import mail_types as _mt
    sw = _ln.events_view()
    roles = _ln.event_roles_view()
    from helpers import line_recipients as _lr, line_quota as _lq, line_catalog as _cat
    safe["quota_thresholds"] = _lq.thresholds()
    safe["role_choices"] = _lr.role_choices()
    # roles＝該類型允許哪些角色收 LINE；null＝所有角色（缺省，沿用現行行為）
    # group／kind／priority＝設定頁分組與標籤；audience＝管理員指定的「誰要發」（mode／roles／users；users 附顯示名、是否已綁定 LINE、是否自行退訂）
    aud = _ln.audience_view()
    names = _line_user_names({u for a in aud.values() for u in a["users"]})
    safe["event_groups"] = list(_cat.GROUP_ORDER)
    u30 = _ln.usage_daily_view(30)          # 按日計數（LINE 事件矩陣票）：近 30 天每個事件推出幾則；資料未滿 30 天 ⇒ complete=False、accumulated_days＝已累積幾天
    safe["usage30"] = {k: u30[k] for k in ("days", "accumulated_days", "complete", "total")}
    safe["audit_mark"] = _audit_mark()               # 草稿儲存的衝突說明用：載入當下的稽核紀錄編號（見 `/events/batch` 的 `since_audit`）
    _cfg_ln = _ln._cfg()
    rc = _lr.potential_counts(_ln.WIRED_EVENTS)      # 每個事件目前可能收到的人數（在職、已綁定、輪得到、沒退訂）；exact＝只發給指定時才精確，其餘是上限
    safe["events"] = [{"key": k, "name": _cat.name_of(k), "enabled": sw[k], "roles": roles[k], "group": _cat.group_of(k),
                       "kind": _cat.kind_of(k), "priority": _ln.event_spec(k)["priority"], "need": list(_cat.modules_needed(k)), "follows": _cat.follows_text(k),
                       "sent30": u30["by_event"].get(k, 0), "recipient_count": rc[k]["n"], "recipient_exact": rc[k]["exact"], "version": _ln._state_token(_cfg_ln, k),
                       "audience": {**aud[k], "users": [_line_user_row(u, names, k) for u in aud[k]["users"]]}} for k in _ln.WIRED_EVENTS]
    return safe


def _line_user_names(usernames) -> dict:
    """{username: (顯示名, 是否在職)}（給設定頁指定清單顯示用；查不到的帳號不在結果裡）。"""
    names = [u for u in usernames if isinstance(u, str)]
    out = {}
    if not names:
        return out
    conn = get_db()
    try:
        for i in range(0, len(names), 400):
            chunk = names[i:i + 400]
            for r in conn.execute("SELECT username, display_name, active FROM users WHERE username IN (%s)" % ",".join("?" * len(chunk)), chunk).fetchall():
                out[r["username"]] = (r["display_name"] or r["username"], bool(r["active"]))
    finally:
        conn.close()
    return out


def _line_user_row(username: str, names: dict, event_key: str) -> dict:
    from helpers import line_notify as _ln, line_recipients as _lr
    disp, active = names.get(username, (username, False))
    return {"username": username, "display": disp, "active": active, "linked": _ln.is_linked(username),
            "muted": _lr.is_muted(username, event_key)}


@router.put("/api/settings/line-notify/events/{key}/audience")
def set_line_notify_event_audience(key: str, body: dict = Body(...), authorization: str = Header(None)):
    """設定某種 LINE 通知「誰要發」：`mode`＝`business`（照原本的收件人，預設）／`business_plus`（另外加上指定的角色與人員）／`only`（只發給指定的角色與人員）；
    `roles`＝角色清單、`users`＝帳號清單。只接受已接線的事件。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln
    if not _ln.is_wired(key):
        raise HTTPException(404, "這種通知尚未支援 LINE：%s" % key)
    b = body or {}
    if "mode" not in b:
        raise HTTPException(400, "缺少 mode（business／business_plus／only）")
    try:
        _ln.set_audience(key, b["mode"], b.get("roles"), b.get("users"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(_tok(authorization), "settings.line_notify.audience", "settings", key,
           "LINE 通知誰要發：%s → %s（角色 %s；人員 %s）" % (key, b["mode"], "、".join(b.get("roles") or []) or "無", "、".join(b.get("users") or []) or "無"))
    return {"ok": True, "key": key, "audience": _ln.audience_view()[key]}


@router.put("/api/settings/line-notify/events/{key}/roles")
def set_line_notify_event_roles(key: str, body: dict = Body(...), authorization: str = Header(None)):
    """設定某種 LINE 通知「允許哪些角色收」。`roles: null`＝所有角色；`roles: []`＝沒有任何角色。只接受已接線的類型與合法角色。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln
    if key not in _ln.WIRED_EVENTS:
        raise HTTPException(404, "這種通知尚未支援 LINE：%s" % key)
    if "roles" not in (body or {}):
        raise HTTPException(400, "缺少 roles（角色清單，或 null＝所有角色）")
    roles = body["roles"]
    try:
        _ln.set_event_roles(key, roles)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(_tok(authorization), "settings.line_notify.event_roles", "settings", key, "LINE 通知可收角色：%s → %s" % (key, "所有角色" if roles is None else ("、".join(roles) or "（無）")))
    return {"ok": True, "key": key, "roles": roles}


@router.get("/api/settings/line-notify/quota")
def get_line_notify_quota(refresh: bool = False, authorization: str = Header(None)):
    """本月 LINE 訊息用量（設定頁常駐用量條）。5 分鐘內用快取；`refresh=true` 強制重讀。讀不到＝`ok:false`＋原因（不丟錯）。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import line_quota as _lq
    return _lq.snapshot(force=bool(refresh))


@router.put("/api/settings/line-notify/events/{key}")
def set_line_notify_event(key: str, body: dict = Body(...), authorization: str = Header(None)):
    """勾選／取消某種信件「同時發 LINE」。只接受已接線的類型；enabled 必須是布林。
    從關切到開、而且還沒有指定收件對象時，伺服器套用預設「只發給我」（操作者本人；LINE 事件矩陣票）：回應 `audience_defaulted: true`。"""
    actor = _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln
    if key not in _ln.WIRED_EVENTS:
        raise HTTPException(404, "這種通知尚未支援 LINE：%s" % key)
    on = (body or {}).get("enabled")
    if not isinstance(on, bool):
        raise HTTPException(400, "enabled 必須是 true 或 false")
    defaulted = _ln.set_event(key, on, default_user=actor["username"])
    _audit(_tok(authorization), "settings.line_notify.event", "settings", key,
           "LINE 通知事件開關：%s → %s%s" % (key, "開" if on else "關", "（收件對象預設：只發給操作者本人）" if defaulted else ""))
    return {"ok": True, "key": key, "enabled": on, "audience_defaulted": defaulted}


_BATCH_FIELDS = {"keys", "enabled", "audience", "roles", "confirm_critical"}


_CHANGES_FIELDS = {"changes", "confirm_critical", "expect", "since_audit"}


def _parse_line_changes_body(b: dict, need_expect: bool = False) -> dict:
    """草稿儲存的請求本體：`{changes: {事件key: {enabled?, audience?, roles?}}, expect?: {key: version}, since_audit?, confirm_critical?}`。嚴格解析 ⇒ 400。"""
    extra = sorted(set(b) - _CHANGES_FIELDS)
    if extra:
        raise HTTPException(400, "草稿儲存不認得的欄位：%s（可用：%s）" % ("、".join(str(x) for x in extra[:5]), "、".join(sorted(_CHANGES_FIELDS))))
    if not isinstance(b.get("changes"), dict):
        raise HTTPException(400, "changes 必須是 {事件代碼: {enabled／audience／roles}}")
    if "confirm_critical" in b and b["confirm_critical"] is not None and not isinstance(b["confirm_critical"], bool):
        raise HTTPException(400, "confirm_critical 必須是 true 或 false")
    since = b.get("since_audit", 0)
    if isinstance(since, bool) or not isinstance(since, int):
        raise HTTPException(400, "since_audit 必須是整數")
    ex = b.get("expect")
    if ex is not None and (not isinstance(ex, dict) or not all(isinstance(v, str) for v in ex.values())):
        raise HTTPException(400, "expect 必須是 {事件代碼: 字串}")
    if need_expect:                                                          # 儲存草稿一定要帶載入時的 version，否則會悄悄蓋掉別人的修改
        if ex is None:
            raise HTTPException(400, "草稿儲存必須帶 expect（{事件代碼: 載入時的 version}），否則會覆蓋其他人的修改")
        missing = [k for k in b["changes"] if k not in ex]
        if missing:
            raise HTTPException(400, "expect 缺少這些事件的 version：%s" % "、".join(str(x) for x in missing[:5]))
    return {"changes": b["changes"], "expect": ex, "since_audit": since, "confirm_critical": b.get("confirm_critical") is True}


def _parse_line_batch_body(body) -> tuple:
    """批次請求本體的嚴格解析（批次與預覽共用）⇒ `(keys, kw)`；格式不對 ⇒ 400。`kw` 含 enabled／audience／confirm_critical／roles（沒帶就不放）。"""
    from helpers import line_notify as _ln
    b = body if isinstance(body, dict) else {}
    extra = sorted(set(b) - _BATCH_FIELDS)
    if extra:
        raise HTTPException(400, "不認得的欄位：%s（可用：%s）" % ("、".join(str(x) for x in extra[:5]), "、".join(sorted(_BATCH_FIELDS))))
    raw = b.get("keys")
    if not isinstance(raw, list) or len(raw) > 10 * _ln.BATCH_MAX_KEYS or not all(isinstance(k, str) for k in raw):
        raise HTTPException(400, "keys 必須是事件代碼的清單（1～%d 個）" % _ln.BATCH_MAX_KEYS)
    keys = list(dict.fromkeys(raw))
    for fld in ("enabled", "confirm_critical"):
        if fld in b and b[fld] is not None and not isinstance(b[fld], bool):
            raise HTTPException(400, "%s 必須是 true 或 false" % fld)
    if "audience" in b and not isinstance(b["audience"], dict):
        raise HTTPException(400, "audience 必須是 {mode, roles, users}")
    kw = {"enabled": b.get("enabled"), "audience": b.get("audience"), "confirm_critical": b.get("confirm_critical") is True}
    if "roles" in b:                                  # 沒帶 ≠ 帶 null（移除角色篩選）
        kw["roles"] = b["roles"]
    return keys, kw


@router.post("/api/settings/line-notify/events/batch-preview")
def preview_line_notify_events_batch(body: dict = Body(...), authorization: str = Header(None)):
    """批次預覽（不寫入、不記稽核）：同 `/events/batch` 的輸入與驗證，回每個事件套用前後的開關、可能收件人數、每月則數估算（`recipient_count` 的來源見 `line_recipients.potential_counts`）。
    給確認視窗顯示「預估每月 X → Y 則」。人數是上限；沒有歷史推播量的事件 `est_after` 為 null（無法估算）。"""
    actor = _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln, line_catalog as _cat
    try:
        if isinstance(body, dict) and "changes" in body:                       # 草稿儲存前的預覽：每個事件各自的改動
            res = _ln.preview_events_changes(_parse_line_changes_body(body)["changes"], default_user=actor["username"])
        else:
            keys, kw = _parse_line_batch_body(body)
            kw.pop("confirm_critical", None)
            res = (_ln.preview_events_batch(keys, enabled=kw["enabled"], audience=kw["audience"], roles=kw["roles"], default_user=actor["username"]) if "roles" in kw
                   else _ln.preview_events_batch(keys, enabled=kw["enabled"], audience=kw["audience"], default_user=actor["username"]))        # roles 沒帶 ≠ 帶 null；不用 ** 傳參
    except ValueError as e:
        raise HTTPException(400, str(e))
    for r in res["events"]:
        r["name"] = _cat.name_of(r["key"])
    return {"ok": True, **res}


@router.post("/api/settings/line-notify/events/batch")
def set_line_notify_events_batch(body: dict = Body(...), authorization: str = Header(None)):
    """一次改多個 LINE 通知事件（LINE 事件矩陣票）：開關 `enabled`、誰要發 `audience`（`{mode, roles, users}`）、角色篩選 `roles`
    （**沒帶＝不動；帶 null＝移除篩選（所有角色）；帶清單＝只收這些角色**）。`keys` 1～100 個（去重）。

    **全部成功或全部不改**：任何一項不合法 ⇒ 400、一個都不改；成功時整批只寫一次設定、只記**一筆**稽核。
    關閉「重要」系統告警的事件必須帶 `confirm_critical: true`，否則 400（`code: confirm_critical_required`、`critical`＝需要確認的事件）。
    事件從關切到開、而且沒有帶 `audience` 也還沒有指定對象時，套用預設「只發給我」（操作者本人）。"""
    actor = _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln, line_catalog as _cat
    b = body if isinstance(body, dict) else {}
    if "changes" in b:                                                        # 草稿儲存：每個事件各自的改動，一次寫入、一筆稽核；`expect` 防蓋掉別人的修改
        return _save_line_changes(b, actor, authorization)
    keys, kw = _parse_line_batch_body(body)
    try:
        res = (_ln.set_events_batch(keys, enabled=kw["enabled"], audience=kw["audience"], roles=kw["roles"], confirm_critical=kw["confirm_critical"], default_user=actor["username"]) if "roles" in kw
               else _ln.set_events_batch(keys, enabled=kw["enabled"], audience=kw["audience"], confirm_critical=kw["confirm_critical"], default_user=actor["username"]))
    except _ln.CriticalConfirmRequired as e:
        raise HTTPException(400, {"code": "confirm_critical_required", "message": str(e), "critical": [{"key": k, "name": _cat.name_of(k)} for k in e.keys]})
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(_tok(authorization), "settings.line_notify.batch", "settings", "", "LINE 通知批次設定：%d 個事件（變更 %d）" % (len(keys), len(res["changed"])),
           {"keys": keys, "enabled": kw["enabled"], "audience": kw["audience"], "roles": b.get("roles", "（不動）"), "changed": res["changed"],
            "audience_defaulted": res["defaulted"], "critical_off": res["critical_off"]})
    return {"ok": True, **res, "audit_mark": _audit_mark()}


def _save_line_changes(b: dict, actor: dict, authorization) -> dict:
    from helpers import line_notify as _ln, line_catalog as _cat
    p = _parse_line_changes_body(b, need_expect=True)
    try:
        res = _ln.set_events_changes(p["changes"], confirm_critical=p["confirm_critical"], default_user=actor["username"], expect=p["expect"])
    except _ln.CriticalConfirmRequired as e:
        raise HTTPException(400, {"code": "confirm_critical_required", "message": str(e), "critical": [{"key": k, "name": _cat.name_of(k)} for k in e.keys]})
    except _ln.BatchConflict as e:
        who = _line_conflict_who(e.keys, p["since_audit"])
        raise HTTPException(409, {"code": "conflict", "message": "這些事件在您載入頁面之後又被改過，為了不覆蓋其他人的修改，系統拒絕儲存。",
                                  "keys": [{"key": k, "name": _cat.name_of(k)} for k in e.keys], **who})
    except ValueError as e:
        raise HTTPException(400, str(e))
    if res["changed"]:                                                       # 沒有實質變動 ⇒ 沒寫設定，也不留稽核雜訊
        _audit(_tok(authorization), "settings.line_notify.batch", "settings", "", "LINE 通知儲存草稿：%d 個事件（變更 %d）" % (len(p["changes"]), len(res["changed"])),
               {"changes": p["changes"], "changed": res["changed"], "audience_defaulted": res["defaulted"], "critical_off": res["critical_off"]})
    return {"ok": True, **res, "audit_mark": _audit_mark()}


def _audit_mark() -> int:
    """目前稽核紀錄的最大編號（給「復原這一批」找「套用之後是誰改的」用；查不到 ⇒ 0）。"""
    conn = get_db()
    try:
        r = conn.execute("SELECT MAX(id) m FROM audit_log").fetchone()
        return int(r["m"] or 0)
    except Exception:                                    # noqa: BLE001
        return 0
    finally:
        conn.close()


def _line_conflict_who(keys, since_id: int) -> dict:
    """套用之後、誰在何時改過這些事件 ⇒ {"by", "at", "keys"}（找不到明確的人 ⇒ by／at 為空字串；只給提示用，不影響是否拒絕）。"""
    by, at = "", ""
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, at, username, display_name, action, target_id, detail FROM audit_log WHERE id>? AND action LIKE 'settings.line_notify%' ORDER BY id DESC LIMIT 200",
                            (int(since_id or 0),)).fetchall()
        want = set(keys)
        for r in rows:
            touched = {r["target_id"] or ""}                                     # 精確比對事件代碼（不用子字串：approved 不會誤中 next_tier_approved）
            try:
                d = json.loads(r["detail"] or "{}")
            except ValueError:
                d = {}
            if isinstance(d, dict):
                for f in ("keys",):
                    if isinstance(d.get(f), list):
                        touched |= {x for x in d[f] if isinstance(x, str)}
                for f in ("changes", "states"):
                    if isinstance(d.get(f), dict):
                        touched |= {x for x in d[f] if isinstance(x, str)}
            if touched & want:
                by, at = (r["display_name"] or r["username"] or ""), (r["at"] or "")
                break
    except Exception:                                    # noqa: BLE001
        pass
    finally:
        conn.close()
    return {"by": by, "at": at}


@router.post("/api/settings/line-notify/events/batch-undo")
def undo_line_notify_events_batch(body: dict = Body(...), authorization: str = Header(None)):
    """「復原這一批」：把一次批次設定寫回套用前的狀態（`states`），前提是這些事件從套用到現在都沒被別人改過（`expect`＝套用回應裡的 `after`）。
    任何一個被改過 ⇒ 409 `{code:'conflict', keys, by, at}`、整批不復原；成功只寫一次設定、只記一筆稽核（`settings.line_notify.batch_undo`）。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln, line_catalog as _cat
    b = body if isinstance(body, dict) else {}
    extra = sorted(set(b) - {"states", "expect", "since_audit"})
    if extra:
        raise HTTPException(400, "不認得的欄位：%s" % "、".join(str(x) for x in extra[:5]))
    since = b.get("since_audit", 0)
    if isinstance(since, bool) or not isinstance(since, int):
        raise HTTPException(400, "since_audit 必須是整數")
    try:
        res = _ln.restore_events_batch(b.get("states"), b.get("expect"))
    except _ln.BatchConflict as e:
        who = _line_conflict_who(e.keys, since)
        raise HTTPException(409, {"code": "conflict", "message": "這些事件在您套用之後又被改過，為了不覆蓋其他人的修改，系統拒絕整批復原。",
                                  "keys": [{"key": k, "name": _cat.name_of(k)} for k in e.keys], **who})
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(_tok(authorization), "settings.line_notify.batch_undo", "settings", "", "LINE 通知批次復原：%d 個事件" % len(res["restored"]),
           {"keys": res["restored"], "states": b.get("states")})
    return {"ok": True, **res, "audit_mark": _audit_mark()}


@router.put("/api/settings/line-notify")
def set_line_notify(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln
    if "include_links" in body and not isinstance(body["include_links"], bool):
        raise HTTPException(400, "include_links 必須是 true／false")      # 不把 "false" 字串當 true
    if "quota_thresholds" in body:
        from helpers import line_quota as _lq
        try:
            body = {**body, "quota_thresholds": _lq.normalize_thresholds(body["quota_thresholds"])}
        except ValueError as e:
            raise HTTPException(400, str(e))
    with _ln.settings_lock():            # 讀改寫要在鎖內：否則會把同時間 set_event 寫的事件開關用舊值蓋回去（K 審 L1）
        current = _get_setting("line_notify", {}) or {}
        if not isinstance(current, dict):
            current = {}
        data = {**current, **{k: body[k] for k in _LINE_DEFAULTS if k in body}}
        data = {**_LINE_DEFAULTS, **data}
        data["enabled"] = bool(data.get("enabled"))
        tok = body.get("channel_access_token") if "channel_access_token" in body else None
        if tok is None or tok == _MASKED:
            data["channel_access_token"] = current.get("channel_access_token", "")
        else:
            t = str(tok).strip()          # 空字串＝清除 token
            if t and not _ln.valid_token(t):
                # 格式不合會讓送出時的例外訊息帶出整串 token（K 審 S2）⇒ 一律在這裡擋下
                raise HTTPException(400, "channel access token 格式不正確：只能是英數與 + / = . _ -，長度 20～512，請從 LINE Developers 重新複製")
            data["channel_access_token"] = t
        data["include_links"] = data.get("include_links") is True
        # LINE Login channel（綁定用）：ID 是純數字、secret 是 32 位十六進位；secret 同 token 慣例（遮罩值／未帶＝保留，空字串＝清除）
        lid = str(data.get("login_channel_id") or "").strip()
        if lid and not _ln.valid_login_id(lid):
            raise HTTPException(400, "LINE Login 的 Channel ID 格式不正確（應為純數字，請從 LINE Developers 的 Basic settings 複製）")
        data["login_channel_id"] = lid
        sec = body.get("login_channel_secret") if "login_channel_secret" in body else None
        if sec is None or sec == _MASKED:
            data["login_channel_secret"] = current.get("login_channel_secret", "")
        else:
            s = str(sec).strip()
            if s and not _ln.valid_login_secret(s):
                raise HTTPException(400, "LINE Login 的 Channel secret 格式不正確（應為 32 位英數字，請從 LINE Developers 重新複製）")
            data["login_channel_secret"] = s
        try:
            data["public_base_url"] = _ln.normalize_public_base(data.get("public_base_url"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if data["enabled"] and not data["channel_access_token"]:
            raise HTTPException(400, "啟用 LINE 通知前請先填寫 channel access token")
        if data["include_links"] and not data["public_base_url"]:
            raise HTTPException(400, "訊息要帶連結，必須先設定對外網址（public_base_url）")
        _set_setting("line_notify", data)
    # 稽核只記「啟用與否／token 有無被更換」，不記 token 本身；對外網址與連結開關影響對外曝露面，照實記
    _audit(_tok(authorization), "settings.line_notify.update", "settings", "line_notify", "LINE 通知設定",
           {"enabled": data["enabled"], "tokenChanged": data["channel_access_token"] != current.get("channel_access_token", ""),
            "publicBaseUrl": data["public_base_url"], "includeLinks": data["include_links"],
            "loginChannelId": data["login_channel_id"], "quotaThresholds": data.get("quota_thresholds"),
            "loginSecretChanged": data["login_channel_secret"] != current.get("login_channel_secret", "")})
    return {"ok": True}


@router.post("/api/settings/line-notify/verify")
def verify_line_notify(authorization: str = Header(None)):
    """用已存的 token 呼叫 LINE（GET /v2/bot/info＋本月額度），確認 token 有效；不發任何訊息。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln
    res = _ln.verify_token()
    _audit(_tok(authorization), "settings.line_notify.verify", "settings", "line_notify", "驗證 LINE token", {"ok": res.get("ok", False)})
    if not res.get("ok"):
        raise HTTPException(400, res.get("error") or "驗證失敗")
    return {"ok": True, "name": res.get("name", ""), "basicId": res.get("basicId", ""), "quota": _ln.quota()}


# ── LINE 綁定（使用者自己綁：電腦發起、手機授權；2026-11-11）──────────────────────────────────────────────
# 流程與不變式見 helpers/line_login.py。⚠️ `/api/line/callback` 是 Cloudflare Tunnel **唯一**對外的路徑（ingress 精確比對
# `^/api/line/callback$`，改路徑要同步改正式機設定並重啟）；它在 main._PUBLIC_API_PATHS（LINE 導回來時沒有 session），
# 自己用 state 驗證，且**不回任何 ERP 資料**。

_LINE_CALLBACK_PAGES = {
    "linked": (200, "綁定完成", "已完成綁定，可以關閉這個頁面。之後您勾選的通知會送到這個 LINE。"),
    "denied": (400, "已取消", "您已取消綁定。需要時請回到電腦重新操作。"),
    "expired": (400, "已逾時", "綁定要求已逾時，請回到電腦重新按「綁定 LINE」。"),
    "session_ended": (400, "無法綁定", "電腦端已登出或帳號狀態已改變，請重新登入後再綁定。"),
    "invalid": (400, "連結無效", "這個綁定連結無效或已使用過，請回到電腦重新按「綁定 LINE」。"),
    "failed": (400, "綁定失敗", "綁定沒有成功，請回到電腦重新操作；若持續失敗請通知管理員。"),
    "rate": (429, "請稍後再試", "目前要求太多，請稍後再試。"),
}


def _line_callback_page(kind: str):
    from fastapi.responses import HTMLResponse
    status, title, msg = _LINE_CALLBACK_PAGES.get(kind, _LINE_CALLBACK_PAGES["failed"])
    html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"robots\" content=\"noindex\">"
            "<title>%s</title><style>body{font-family:sans-serif;margin:0;padding:32px 20px;text-align:center;color:#222}"
            "h1{font-size:20px}p{font-size:15px;line-height:1.6}</style></head><body><h1>%s</h1><p>%s</p></body></html>") % (title, title, msg)
    # 固定頁面、不帶任何使用者或 ERP 資料；網址上的 code／state 不可外流到別的網站（no-referrer）、不可被快取
    return HTMLResponse(html, status_code=status, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})


@router.get("/api/line/callback")
def line_login_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """LINE Login 導回。**未登入可打**（main._PUBLIC_API_PATHS）：不信任這個請求本身，只信 state（單次、綁發起人的登入 session）。"""
    from helpers import line_login as _ll
    result, token, username = _ll.complete(code, state, error)         # 總量保護在 complete() 裡、state 銷毀之後（K 審 N1）
    if username:
        _audit(token, "line.binding.callback", "line_binding", username, "LINE 綁定回調", {"result": result})
    return _line_callback_page(result)


@router.get("/api/line/binding")
def get_line_binding(authorization: str = Header(None)):
    """自己的綁定狀態；`available`＝管理員已設好 LINE Login 與對外網址（沒設好時前端不顯示綁定按鈕）。"""
    user = _require_user(authorization)
    from helpers import line_notify as _ln
    cid, sec = _ln.login_credentials()
    v = _ln.binding_view(user["username"])
    v["available"] = bool(cid and sec and _ln.callback_url())
    return v


@router.get("/api/line/prefs")
def get_line_prefs(authorization: str = Header(None)):
    """我要收哪些 LINE 通知：只列「公司已勾選、且我的角色被允許」的類型（預設全收，可自行退訂）。`linked`＝我有沒有綁定 LINE。"""
    user = _require_user(authorization)
    from helpers import line_notify as _ln, line_recipients as _lr
    return {"linked": _ln.is_linked(user["username"]), "events": _lr.prefs_view(user["username"], user.get("role"))}


@router.put("/api/line/prefs/{key}")
def set_line_pref(key: str, body: dict = Body(...), authorization: str = Header(None)):
    """本人退訂／恢復某類 LINE 通知（`enabled: true`＝要收）。只能改自己；類型要已接線、且我的角色被允許。"""
    user = _require_user(authorization)
    from helpers import line_notify as _ln, line_recipients as _lr
    on = (body or {}).get("enabled")
    if not isinstance(on, bool):
        raise HTTPException(400, "enabled 必須是 true 或 false")
    if key not in _ln.WIRED_EVENTS:
        raise HTTPException(404, "這種通知尚未支援 LINE：%s" % key)
    try:
        _lr.set_muted(user["username"], key, not on, role=user.get("role"))
    except ValueError as e:
        raise HTTPException(403, str(e))
    _audit(_tok(authorization), "line.prefs.update", "line_prefs", user["username"], "LINE 通知個人設定：%s → %s" % (key, "收" if on else "不收"))
    return {"ok": True, "key": key, "enabled": on}


@router.post("/api/line/binding/start")
def start_line_binding(authorization: str = Header(None)):
    """發起綁定：回一個 QR（內容是 LINE 授權網址）給電腦顯示，手機掃碼授權。state 綁定目前這個登入 session，10 分鐘內單次有效。"""
    user = _require_user(authorization)
    from helpers import line_login as _ll
    try:
        res = _ll.start(user["username"], _tok(authorization))
    except ValueError as e:
        raise HTTPException(400, str(e))
    import base64
    import io
    import qrcode
    buf = io.BytesIO()
    qrcode.make(res["authorizeUrl"]).save(buf, format="PNG")
    _audit(_tok(authorization), "line.binding.start", "line_binding", user["username"], "發起 LINE 綁定")
    return {"authorizeUrl": res["authorizeUrl"], "expiresIn": res["expiresIn"],
            "qrCodePng": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")}


@router.delete("/api/line/binding")
def unlink_own_line(authorization: str = Header(None)):
    user = _require_user(authorization)
    from helpers import line_notify as _ln
    done = _ln.unlink_user(user["username"])
    if done:
        _audit(_tok(authorization), "line.binding.unlink", "line_binding", user["username"], "解除 LINE 綁定")
    return {"ok": True, "unlinked": done}


@router.delete("/api/line/binding/{username}")
def unlink_line_of(username: str, authorization: str = Header(None)):
    """最高管理者替別人解除綁定（例如手機換號、同仁離職）。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import line_notify as _ln
    done = _ln.unlink_user(username)
    if done:
        _audit(_tok(authorization), "line.binding.unlink", "line_binding", username, "最高管理者解除 LINE 綁定")
    return {"ok": True, "unlinked": done}


@router.get("/api/settings/line-notify/bindings")
def get_line_bindings(authorization: str = Header(None)):
    """LINE「綁定狀況」：在職人員誰已綁定、誰還沒（只有最高管理者；不含 LINE userId）。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import line_binding as _lb
    return _lb.status()


@router.post("/api/settings/line-notify/bindings/remind")
def remind_line_bindings(body: dict = Body(default={}), authorization: str = Header(None)):
    """「提醒未綁定的人」：用站內通知＋Email 寄綁定說明（附「修改密碼」頁連結）。`usernames` 省略＝所有未綁定的在職人員；
    同一個人 24 小時內只提醒一次。LINE 登入還沒設好 ⇒ 400。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import line_binding as _lb
    names = (body or {}).get("usernames")
    try:
        res = _lb.remind(names)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _audit(_tok(authorization), "line.binding.remind", "line_binding", "", "提醒未綁定 LINE 的同仁：站內通知 %d 人、Email %d 人、略過（24 小時內已提醒）%d 人"
           % (res["notified"], res["emailed"], len(res["skippedRecent"])), {"notified": res["notified"], "emailed": res["emailed"]})
    return {"ok": True, **res}


@router.post("/api/settings/email-notify/test")
def test_email_notify(authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    if not _wizard_rate_ok(user["id"]):               # 舊的「寄測試信」也走同一個頻率限制（不然可繞過精靈的限制反覆探測）
        raise HTTPException(429, "測試信寄得太頻繁了（每個帳號 10 分鐘內最多 5 次）。請稍等幾分鐘再試。")
    from helpers.email_notify import _send_raising, _admin_emails, _build_html, _base_url
    from helpers import mail_types as _mt
    to = _admin_emails("system_test_mail")
    if not to:
        raise HTTPException(400, "找不到可發送對象：請確認「信件與通知收件設定」的測試信收件人，並為其帳號填寫 Email")
    html = _build_html("system_test_mail", "測試信", "測試", "#2563EB",
                       [("觸發者", user.get('display_name') or user['username'])], "", _base_url(),
                       intro="本信為寄信設定測試。")
    try:
        _send_raising(to, _mt.subject("system_test_mail", "寄信設定測試"), html)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        tid = trace_id()
        logger.exception("email_notify test failed trace=%s", tid)
        raise HTTPException(502, f"寄信失敗：連不上寄信伺服器。請檢查寄信主機、埠號、帳號與應用程式密碼是否正確（錯誤代碼 {tid}，聯絡系統管理者時請提供）")
    _audit(_tok(authorization), 'settings.email_notify.test', 'settings', 'email_notify', '測試郵件', {'recipients': len(to)})
    return {"ok": True, "sent_to": to}


# ── 寄信帳號精靈（批次 3，2026-11-13）──────────────────────────────────────────
# 流程：①選信箱服務 ②貼信箱與密碼 ③寄測試信給「目前登入的人」，按「我收到了」才啟用。
# 不變式：測試信成功之前不會啟用；啟用只認「剛剛測試成功的那一份設定」（指紋比對，設定改過就要重測）；密碼不進稽核、不進回應。

_EMAIL_WIZARD_PROOF = "email_setup_test_proof"      # {fp, fp_full, base_fp, at, to, host, port, user}：最近一次精靈測試信成功的證明；**不存密碼**，只存帶金鑰的 HMAC 指紋
_WIZARD_PROOF_HOURS = 24
_WIZARD_HMAC_KEY = "email_setup_hmac_secret"         # 測試證明的簽章金鑰（隨機、存系統設定；名稱含 secret ⇒ 每日備份匯出一律遮蔽）
_WIZARD_HITS_KEY = "email_setup_test_hits"          # {user_id: [時間…]}：test-me 的頻率限制（存資料庫，重啟不歸零）
_WIZARD_TEST_LIMIT, _WIZARD_TEST_WINDOW_MIN = 5, 10  # 每個帳號 10 分鐘最多寄 5 次測試信
_WIZARD_PORTS = (25, 465, 587, 2525)                # 寄信埠只准這四個（內網主機仍允許：客戶可能自己架信件伺服器；回應只說成敗與白話分類，不回原始錯誤）


def _wizard_fresh(proof) -> bool:
    try:
        return datetime.now() - datetime.fromisoformat((proof or {}).get("at", "")) < timedelta(hours=_WIZARD_PROOF_HOURS)
    except (TypeError, ValueError):
        return False


def _wiz_hmac(*parts) -> str:
    """帶金鑰的指紋（HMAC-SHA256）：證明裡不存密碼，也不存密碼的純雜湊（純雜湊可離線猜）；金鑰是隨機產生、存系統設定、備份匯出遮蔽。"""
    import hashlib
    import hmac
    key = _get_setting(_WIZARD_HMAC_KEY, "") or ""
    try:
        keyb = bytes.fromhex(key) if isinstance(key, str) and len(key) == 64 else b""
    except ValueError:
        keyb = b""
    if not keyb:                                    # 沒有、或被改成不能用的值（例如從備份匯出的「[已遮蔽]」還原）⇒ 重生一把；舊證明因此失效，是安全的方向
        key = secrets.token_hex(32)
        _set_setting(_WIZARD_HMAC_KEY, key)
        keyb = bytes.fromhex(key)
    return hmac.new(keyb, "\x1f".join(str(x) for x in parts).encode("utf-8"), hashlib.sha256).hexdigest()


def _port_int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _wiz_creds_fp(host, port, user, pw) -> str:
    return _wiz_hmac("creds", host or "", _port_int(port), user or "", pw or "")


def _wiz_full_fp(cand) -> str:
    return _wiz_hmac("full", cand.get("smtp_host", ""), _port_int(cand.get("smtp_port")), cand.get("smtp_user", ""), cand.get("smtp_password", ""),
                     cand.get("from_name", ""), cand.get("base_url", ""))


def _wizard_proof_matches(host, port, user, pw) -> bool:
    proof = _get_setting(_EMAIL_WIZARD_PROOF, {}) or {}
    return bool(proof) and _wizard_fresh(proof) and proof.get("fp") == _wiz_creds_fp(host, port, user, pw)


def _live_fp(cfg) -> str:
    """正在使用的設定（含是否啟用）的指紋：測試之後設定被別處改過 ⇒ 啟用前要重測。"""
    return _wiz_hmac("live", cfg.get("smtp_host", ""), _port_int(cfg.get("smtp_port")), cfg.get("smtp_user", ""), cfg.get("smtp_password", ""),
                     1 if cfg.get("enabled") else 0)


_WIZARD_RATE_LOCK = threading.Lock()


def _wizard_rate_ok(user_id) -> bool:
    with _WIZARD_RATE_LOCK:                            # 讀－改－寫要不可分割：同一帳號同時送出多個請求也不能超過上限
        return _wizard_rate_ok_locked(user_id)


def _wizard_rate_ok_locked(user_id) -> bool:
    now = datetime.now()
    hits = _get_setting(_WIZARD_HITS_KEY, {}) or {}
    mine = []
    for s in hits.get(str(user_id), []):
        try:
            if now - datetime.fromisoformat(s) < timedelta(minutes=_WIZARD_TEST_WINDOW_MIN):
                mine.append(s)
        except (TypeError, ValueError):
            pass
    if len(mine) >= _WIZARD_TEST_LIMIT:
        return False
    mine.append(now.isoformat(timespec="seconds"))
    hits[str(user_id)] = mine
    _set_setting(_WIZARD_HITS_KEY, hits)
    return True


@router.get("/api/settings/email-notify/providers")
def email_notify_providers(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from helpers import email_setup as _es
    return {"providers": _es.provider_list()}


class EmailWizardIn(BaseModel):
    provider: str = "gmail"
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    from_name: str = ""
    base_url: str = ""
    recipient: str = ""          # 登入的人沒有 Email 時，在這一步補填（同時存回他的帳號）


def _wizard_error(status: int, detail: str, extra=None, **more):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content={"detail": detail, **(extra or {}), **more})


def _wizard_candidate(body, current):
    """把精靈送來的內容整理成「候選設定」並檢查（test-me 與 activate 共用同一份，兩邊算出的指紋才會一致）。回 (provider, cand)。"""
    from helpers import email_setup as _es
    prov = _es.provider_by_key(body.provider)
    if not prov:
        raise HTTPException(422, "請先選擇信箱服務。")
    pw = body.smtp_password
    if pw in ("", _MASKED):
        pw = current.get("smtp_password", "")
    pw = _es.normalize_password(body.provider, pw)
    host = (body.smtp_host or prov["host"]).strip()
    port = int(body.smtp_port or prov["port"])
    bad = _es.validate_config({"smtp_user": body.smtp_user, "smtp_host": host, "smtp_port": port,
                               "base_url": body.base_url, "from_name": body.from_name})
    if bad:
        raise HTTPException(422, bad)
    if not host:
        raise HTTPException(422, "請填寄信主機（向信箱或網域代管廠商詢問）。")
    if not body.smtp_user.strip():
        raise HTTPException(422, "請填寄件人信箱。")
    if not pw:
        raise HTTPException(422, "請填密碼（%s）。" % prov["passwordLabel"])
    if port not in _WIZARD_PORTS:
        raise HTTPException(422, "寄信埠只能是 25、465、587 或 2525；請向信箱或網域代管廠商確認。")
    cand = {"smtp_user": body.smtp_user.strip(), "smtp_password": pw, "smtp_host": host, "smtp_port": port}
    cand["from_name"] = body.from_name.strip() or current.get("from_name") or _EMAIL_DEFAULTS["from_name"]
    cand["base_url"] = body.base_url.strip() or current.get("base_url") or ""
    return prov, cand


@router.post("/api/settings/email-notify/wizard/test-me")
def email_notify_wizard_test_me(body: EmailWizardIn, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    from helpers import email_setup as _es
    from helpers.email_notify import _send_raising, _build_html, _base_url
    from helpers import mail_types as _mt
    current = _get_setting("email_notify", {}) or {}
    prov, cand = _wizard_candidate(body, current)
    host, port = cand["smtp_host"], cand["smtp_port"]
    # 收件人＝目前登入的人；他沒有 Email ⇒ 這一步補填並存回帳號
    conn = get_db()
    try:
        row = conn.execute("SELECT email FROM users WHERE id=?", (user["id"],)).fetchone()
        to_addr = (row["email"] if row else "") or ""
        if not to_addr.strip():
            rec = (body.recipient or "").strip()
            if not rec:
                return _wizard_error(400, "您的帳號尚無 Email，請在下方填上 Email，測試信才寄得到。", needEmail=True)
            if not _es.valid_email(rec):
                raise HTTPException(422, "Email 格式不對，請檢查後再填一次。")
            conn.execute("UPDATE users SET email=? WHERE id=?", (rec, user["id"]))
            conn.commit()
            to_addr = rec
    finally:
        conn.close()
    # 候選設定只放在記憶體裡測試，**不存進系統設定**：測試失敗時，正在使用的設定一個字都不會變；測試成功＋按「我收到了」才寫入
    full = {**_EMAIL_DEFAULTS, **current, **cand}
    if not _wizard_rate_ok(user["id"]):
        return _wizard_error(429, "測試信寄得太頻繁了（每個帳號 10 分鐘內最多 5 次）。請稍等幾分鐘再試。", category="rate_limited")
    html = _build_html("system_test_mail", "測試信", "測試", "#2563EB",
                       [("觸發者", user.get("display_name") or user["username"])], "", _base_url(),
                       intro="本信為寄信設定測試。收到這封信，代表寄信帳號設定成功。")
    try:
        _send_raising([to_addr], _mt.subject("system_test_mail", "寄信設定測試"), html, ignore_enabled=True, cfg=full)
    except RuntimeError as e:                       # 「這台機器不寄真實信件」等：訊息本身就是白話
        return _wizard_error(400, str(e), category="blocked")
    except Exception as e:                          # noqa: BLE001
        _set_setting(_EMAIL_WIZARD_PROOF, {})       # 重測失敗 ⇒ 先前的測試證明作廢
        tid = trace_id()
        logger.exception("email_notify wizard test failed trace=%s", tid)
        c = _es.classify_error(e, host, body.provider)
        extra = {"category": c["category"], "title": c["title"], "hint": c["hint"], "traceId": tid}
        if c["ticketKind"]:
            prof = _get_setting("company_profile", {})
            company = (prof.get("name", "") if isinstance(prof, dict) else "") or ""
            extra["ticket"] = _es.build_ticket(c["ticketKind"], user=cand["smtp_user"], host=host, port=port,
                                               company=company, requester=user.get("display_name") or user["username"])
        return _wizard_error(502, c["title"] + "。" + c["hint"], extra)
    # 證明不存密碼：只存帶金鑰的 HMAC 指紋＋非機密的主機／埠／帳號與時間（24 小時內有效；沒用到的在讀設定時清掉）
    _set_setting(_EMAIL_WIZARD_PROOF, {"fp": _wiz_creds_fp(host, port, cand["smtp_user"], cand["smtp_password"]), "fp_full": _wiz_full_fp(cand),
                                       "base_fp": _live_fp(current), "at": datetime.now().isoformat(timespec="seconds"), "to": to_addr,
                                       "host": host, "port": port, "user": cand["smtp_user"]})
    _audit(_tok(authorization), "settings.email_notify.wizard_test", "settings", "email_notify", "寄信精靈測試信",
           {"provider": body.provider, "host": host, "port": port})
    return {"ok": True, "sent_to": to_addr}


@router.post("/api/settings/email-notify/wizard/activate")
def email_notify_wizard_activate(body: EmailWizardIn = None, authorization: str = Header(None)):
    """按「我收到了」：畫面把整份候選設定再送一次；伺服器重算 HMAC，**相符且 24 小時內**才寫進正式設定並啟用（密碼只在這個請求裡出現，不存在證明裡）。"""
    _require_user(authorization, require_superadmin=True)
    cfg = _get_setting("email_notify", {}) or {}
    proof = _get_setting(_EMAIL_WIZARD_PROOF, {}) or {}
    if body is None or not proof or not _wizard_fresh(proof):
        raise HTTPException(400, "請先寄測試信並確認收到：目前的寄信設定尚無測試成功。")
    _prov, cand = _wizard_candidate(body, cfg)
    if proof.get("fp_full") != _wiz_full_fp(cand):
        raise HTTPException(400, "請先寄測試信並確認收到：目前的寄信設定尚無測試成功。")
    if proof.get("base_fp") != _live_fp(cfg):
        raise HTTPException(400, "寄信設定在測試之後被改過，請重新寄一次測試信。")
    _set_setting("email_notify", {**_EMAIL_DEFAULTS, **cfg, **cand, "enabled": True})      # 測試成功的候選設定，到這一步才寫進正式設定
    _set_setting(_EMAIL_WIZARD_PROOF, {})                                                    # 證明只能用一次
    _audit(_tok(authorization), "settings.email_notify.wizard_activate", "settings", "email_notify", "寄信精靈啟用 Email 通知")
    return {"ok": True, "enabled": True}


# ── Custom roles ───────────────────────────────────────────────────────────────

_VALID_BASE_ROLES = {"superadmin", "admin", "sales", "engineer", "viewer", "finance"}


@router.get("/api/settings/custom-roles")
def get_custom_roles(authorization: str = Header(None)):
    _require_user(authorization)
    return {"items": _get_setting("custom_roles", []) or []}


@router.post("/api/settings/custom-roles", status_code=201)
def create_custom_role(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "角色名稱不得為空")
    base_role = body.get("baseRole", "viewer")
    if base_role not in _VALID_BASE_ROLES:
        raise HTTPException(400, "無效的基礎角色")
    refuse_unknown_new_keys(body.get("modules", []))
    roles = _get_setting("custom_roles", []) or []
    if any(r["name"] == name for r in roles):
        raise HTTPException(409, "角色名稱已存在")
    new_role = {
        "id":       secrets.token_hex(4),
        "name":     name,
        "baseRole": base_role,
        "modules":  body.get("modules", []),
    }
    roles.append(new_role)
    _set_setting("custom_roles", roles)
    _audit(_tok(authorization), "settings.custom_role.create", "settings", new_role["id"], name)
    notify_module_activity("系統設定", "建立自訂角色", actor.get("display_name") or actor["username"],
                            name, "users.html")
    return new_role


@router.put("/api/settings/custom-roles/{rid}")
def update_custom_role(rid: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    roles = _get_setting("custom_roles", []) or []
    idx = next((i for i, r in enumerate(roles) if r["id"] == rid), None)
    if idx is None:
        raise HTTPException(404, "找不到此自訂角色")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "角色名稱不得為空")
    base_role = body.get("baseRole", "viewer")
    if base_role not in _VALID_BASE_ROLES:
        raise HTTPException(400, "無效的基礎角色")
    if any(r["name"] == name and r["id"] != rid for r in roles):
        raise HTTPException(409, "角色名稱已存在")
    roles[idx]["name"]     = name
    roles[idx]["baseRole"] = base_role
    refuse_unknown_new_keys(body.get("modules", []), roles[idx].get("modules") or [])
    roles[idx]["modules"]  = body.get("modules", [])
    _set_setting("custom_roles", roles)
    _audit(_tok(authorization), "settings.custom_role.update", "settings", rid, name)
    return roles[idx]


@router.delete("/api/settings/custom-roles/{rid}", status_code=204)
def delete_custom_role(rid: str, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    roles = _get_setting("custom_roles", []) or []
    new_roles = [r for r in roles if r["id"] != rid]
    if len(new_roles) == len(roles):
        raise HTTPException(404, "找不到此自訂角色")
    _set_setting("custom_roles", new_roles)
    _audit(_tok(authorization), "settings.custom_role.delete", "settings", rid, rid)
    notify_module_activity("系統設定", "刪除自訂角色", actor.get("display_name") or actor["username"],
                            rid, "users.html")


# ── Role Labels ────────────────────────────────────────────────────────────────

_DEFAULT_ROLE_LABELS = {
    "superadmin": "最高管理者",
    "admin":      "管理員",
    "sales":      "業務",
    "engineer":   "工程師",
    "finance":    "財務",
    "viewer":     "檢視者",
}


@router.get("/api/system/heartbeat")
def get_heartbeat_status(authorization: str = Header(None)):
    """心跳監控「本身」的狀態（唯讀；僅最高管理者）：狀態、開始時間、本機協定、上次對外打卡成功、有沒有設對外網址（只回布林）。
    判斷邏輯在 helpers/heartbeat_status.assess（只讀 logs/heartbeat_state.json；不回 ping 網址）。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import heartbeat_status as _hs
    return _hs.assess()


@router.get("/api/system/schema-status")
def get_schema_status(authorization: str = Header(None)):
    """唯讀 schema/migration 診斷資訊：目前版本、目標版本、完整 migration 清單。
    不提供任何觸發/操作動作——migration 已在伺服器啟動時自動套用，「重新對現有
    db 跑一次」永遠是 no-op，沒有診斷價值；真正有意義的乾跑驗證在部署階段
    （見 backend/tools/apply_update.ps1），不是活著的伺服器本身。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT version, applied_at FROM schema_version WHERE id=1").fetchone()
    conn.close()
    current = row["version"] if row else 0
    applied_at = row["applied_at"] if row else ""
    migrations = [
        {
            "version": i,
            "name": fn.__name__,
            "description": inspect.getdoc(fn) or "",
            "applied": i <= current,
        }
        for i, fn in enumerate(_MIGRATIONS, start=1)
    ]
    return {
        "currentVersion": current,
        "targetVersion": CURRENT_VERSION,
        "upToDate": current >= CURRENT_VERSION,
        "lastAppliedAt": applied_at,
        "migrations": migrations,
    }


@router.get("/api/settings/role-labels")
def get_role_labels(authorization: str = Header(None)):
    _require_user(authorization)
    stored = _get_setting("role_labels") or {}
    return {**_DEFAULT_ROLE_LABELS, **stored}


class RoleLabelsBody(BaseModel):
    superadmin: str = "最高管理者"
    admin:      str = "管理員"
    sales:      str = "業務"
    engineer:   str = "工程師"
    viewer:     str = "檢視者"


@router.put("/api/settings/role-labels")
def put_role_labels(body: RoleLabelsBody, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    labels = {k: v.strip() for k, v in body.dict().items()}
    for k, v in labels.items():
        if not v:
            raise HTTPException(422, f"角色名稱不可空白：{k}")
    _set_setting("role_labels", labels)
    _audit(_tok(authorization), "settings.role_labels.update", "settings",
           "role_labels", json.dumps(labels, ensure_ascii=False))
    return labels


# ── WebAuthn config status (public, no auth) ──────────────────────────────────

@router.get("/api/system/webauthn-config-status")
def get_webauthn_config_status():
    """Public endpoint: check whether WebAuthn RP ID and Origin are configured.
    Used by login.html and change-password.html to show/hide Passkey buttons.

    2026-09-16：功能總開關關閉時回 `configured:false, enabled:false`。
    這支**不回 404**——三個前端頁面都靠它決定要不要畫出 Passkey 區塊，回 200
    才能同時關掉按鈕（`configured`）與整張卡片（`enabled`）。

    停用時 `configured` 一併壓成 false 是刻意的：前端若是舊版（部署不同步、
    或瀏覽器吃到快取的 HTML），它只認得 `configured`，壓成 false 才能保證
    按鈕不會冒出來——按下去也只會拿到 404。
    """
    from helpers import auth as _auth_helpers
    if not _auth_helpers.PASSKEY_ENABLED:
        return {"configured": False, "enabled": False}
    rp_id = _get_setting("webauthn_rp_id") or ""
    origin = _get_setting("webauthn_origin") or ""
    configured = bool(rp_id.strip() and origin.strip())
    return {"configured": configured, "enabled": True}


# ── 在線成員與在線時數（2026-09-14，DB v79）─────────────────────────────────
#
# 使用者要求：「右上角可顯示在線成員跟數量，並且後台統計每個成員（含管理員、
# 最高管理者）在線上的時間，這些數據只有最高管理者看得到」。
#
# 兩支端點都限 superadmin：在線名單本身就是「誰在不在」的行蹤資訊，時數更是。
# 累加寫在 `main.py::auth_middleware`（沿用既有的 last_active 節流點），這裡只讀。

_ONLINE_WINDOW_SECONDS = 300   # 與 main.py 的 last_active 節流同步：最久 5 分鐘寫一次


@router.get("/api/online-users")
def list_online_users(authorization: str = Header(None)):
    """目前在線的成員與人數（限最高管理者）。

    「在線」＝該帳號任一 session 的 `last_active` 在 5 分鐘內。用 sessions 而不是
    另做心跳：心跳會讓每個閒置分頁固定打伺服器，而 `last_active` 本來就在更新。

    ⚠️ 時間精度的取捨：`last_active` 每 5 分鐘才寫一次（main.py 的節流），所以剛
    登入的人最慢 5 分鐘後才會出現在名單上、離開的人最多晚 5 分鐘才消失。要更即時
    就得縮短節流（每次請求都寫），那是用資料庫寫入量換秒級精度，目前不划算。
    """
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT u.id, u.username, u.display_name, u.role, "
            "       MAX(s.last_active) AS last_active, COUNT(*) AS session_count "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE u.active=1 AND s.last_active IS NOT NULL AND s.last_active != '' "
            "GROUP BY u.id ORDER BY last_active DESC"
        ).fetchall()
    finally:
        conn.close()

    now = datetime.now()
    online = []
    for r in rows:
        try:
            secs = (now - datetime.fromisoformat(r["last_active"])).total_seconds()
        except Exception:
            continue
        if secs <= _ONLINE_WINDOW_SECONDS:
            online.append({
                "userId": r["id"],
                "username": r["username"],
                "displayName": r["display_name"] or r["username"],
                "role": r["role"],
                "lastActive": r["last_active"],
                "secondsAgo": int(secs),
                "sessionCount": r["session_count"],
            })
    return {"count": len(online), "windowSeconds": _ONLINE_WINDOW_SECONDS, "users": online}


@router.get("/api/user-activity")
def user_activity_stats(start: Optional[str] = None, end: Optional[str] = None,
                        authorization: str = Header(None)):
    """每位成員的在線時數統計（限最高管理者）。

    `start`／`end` 是 `YYYY-MM-DD`（含），預設當月。回傳每人合計與逐日明細。

    **統計的是「活躍時間」不是「登入時長」**：開著分頁去開會不會被算進去（沒有
    請求就沒有累加），見 `main.py::_record_user_activity` 的說明。這一點寫在回傳
    的 `note` 欄位裡，前端直接顯示，免得有人拿它當出勤紀錄。
    """
    _require_user(authorization, require_superadmin=True)
    today = datetime.now()
    start = (start or today.strftime("%Y-%m-01"))[:10]
    end = (end or today.strftime("%Y-%m-%d"))[:10]

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT a.user_id, a.day, a.active_seconds, u.username, u.display_name, u.role "
            "FROM user_activity_daily a JOIN users u ON u.id = a.user_id "
            "WHERE a.day >= ? AND a.day <= ? "
            "ORDER BY a.day",
            (start, end),
        ).fetchall()
        # 2026-09-15：軌跡的成員篩選要能選到**每一個**使用者，所以名單走 users 表
        # 而不是上面那批有時數的人——沒有活躍時數但有操作紀錄（或這段期間請假）的
        # 人，本來就選不到，而那常常正是想查的人。停用帳號一併列出：離職前做了
        # 什麼是最需要查的。
        members = [{
            "userId": r["id"],
            "username": r["username"],
            "displayName": r["display_name"] or r["username"],
            "role": r["role"],
            "active": bool(r["active"]),
        } for r in conn.execute(
            "SELECT id, username, display_name, role, active FROM users "
            "ORDER BY active DESC, display_name, username"
        ).fetchall()]
    finally:
        conn.close()

    by_user = {}
    for r in rows:
        u = by_user.setdefault(r["user_id"], {
            "userId": r["user_id"],
            "username": r["username"],
            "displayName": r["display_name"] or r["username"],
            "role": r["role"],
            "totalSeconds": 0,
            "days": {},
        })
        u["totalSeconds"] += r["active_seconds"] or 0
        u["days"][r["day"]] = (u["days"].get(r["day"]) or 0) + (r["active_seconds"] or 0)

    items = sorted(by_user.values(), key=lambda x: x["totalSeconds"], reverse=True)
    return {
        "start": start,
        "end": end,
        "items": items,
        "members": members,
        "note": "統計的是有實際操作的「活躍時間」，不是分頁開著的時間；每 5 分鐘累計一次。",
    }


_METHOD_LABELS = {"GET": "檢視", "POST": "新增／執行", "PUT": "修改",
                  "PATCH": "修改", "DELETE": "刪除"}

# 同一個人、同一句說明、這個秒數內相鄰的紀錄，回傳時併成一列（帶 `repeat` 次數）。
# 寫入端從 2026-09-15 起就收斂了，這道是給**已經存在的舊資料**用的：軌跡保留 90
# 天，不併的話接下來三個月每開一張案件都還是六列一模一樣的字。
_TRAIL_MERGE_SECONDS = 60


@router.get("/api/user-activity/trail")
def user_activity_trail(user: Optional[str] = None, start: Optional[str] = None,
                        end: Optional[str] = None, limit: int = 200,
                        before_id: Optional[int] = None,
                        authorization: str = Header(None)):
    """逐條操作軌跡（限最高管理者）——誰、什麼時候、在哪一頁、做了什麼。

    2026-09-14 使用者要求「在線時數統計，同步能看使用者點了什麼看了什麼，逐條紀錄」；
    2026-09-15 追加「用更直覺的語言，而且要能篩選每個使用者」。

    參數：`user`（帳號，不給就是全部人）、`start`／`end`（`YYYY-MM-DD`，含）、
    `limit`（上限 500）、`before_id`（往前翻頁，傳上一頁最後一筆的 id）。

    每一筆的 `summary` 是一句人話（「送審出貨單 #7」），`kind` 是檢視／變更／
    刪除／簽核／匯出，`resultLabel` 把 HTTP 狀態碼翻成「成功」「沒有權限（被
    擋下）」。翻譯規則在 `trail.py`，原則是**不猜**：對不到就原樣顯示路徑。
    `path` 仍然照原樣回傳——畫面上可以開起來對照，出事時要查的是原始事實。
    """
    _require_user(authorization, require_superadmin=True)
    limit = max(1, min(int(limit or 200), 500))

    sql = ("SELECT r.id, r.at, r.method, r.path, r.page, r.status, "
           "       u.username, u.display_name, u.role "
           "FROM user_request_log r JOIN users u ON u.id = r.user_id WHERE 1=1")
    params: list = []
    if user:
        sql += " AND u.username = ?"
        params.append(user)
    if start:
        sql += " AND r.at >= ?"
        params.append(start[:10] + "T00:00:00")
    if end:
        sql += " AND r.at <= ?"
        params.append(end[:10] + "T23:59:59")
    if before_id:
        sql += " AND r.id < ?"
        params.append(int(before_id))
    sql += " ORDER BY r.id DESC LIMIT ?"
    params.append(limit)

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    # 翻頁游標取**原始**最後一筆的 id：下面會藏掉雜訊、併掉重複，顯示的列數比
    # 撈出來的少，拿併完的清單算游標會讓「載入更早的紀錄」跳過還沒看過的資料。
    next_before_id = rows[-1]["id"] if len(rows) == limit else None

    items = []
    for r in rows:
        # 寫入端（main.py）從 2026-09-15 起就不記這些了，但 90 天內的舊資料還在。
        if trail.should_skip(r["path"]):
            continue
        d = trail.describe(r["method"], r["path"])
        prev = items[-1] if items else None
        # 時間比對的基準固定是群組裡**最新**那一筆（prev["at"] 不改寫）：若改成每次
        # 跟前一筆比，每 59 秒發生一次的相同動作會一路串下去併成一列，把「這個人
        # 十分鐘內開了同一張案件十次」這件事藏起來。
        if (prev and prev["username"] == r["username"] and prev["summary"] == d["summary"]
                and _within(prev["at"], r["at"], _TRAIL_MERGE_SECONDS)):
            prev["repeat"] += 1
            continue
        items.append({
            "id": r["id"],
            "at": r["at"],
            "username": r["username"],
            "displayName": r["display_name"] or r["username"],
            "role": r["role"],
            "method": r["method"],
            "methodLabel": _METHOD_LABELS.get(r["method"], r["method"]),
            "path": r["path"],
            "summary": d["summary"],
            "kind": d["kind"],
            "kindLabel": d["kindLabel"],
            "module": d["module"],
            "label": d["module"],         # 舊欄位名，保留給既有呼叫端
            "page": r["page"],
            "pageLabel": trail.page_label(r["page"]),
            "status": r["status"],
            "resultLabel": trail.status_label(r["status"]),
            "ok": trail.status_ok(r["status"]),
            "repeat": 1,
        })
    return {
        "items": items,
        "nextBeforeId": next_before_id,
        "note": "只記人的操作：輪詢、心跳、下拉選單與欄位偏好這類頁面自動發出的請求不記；"
                "一次操作連帶送出的多個請求計為一次。",
    }


def _within(later_iso: str, earlier_iso: str, seconds: int) -> bool:
    """兩個時間戳是不是差在 `seconds` 以內（解析失敗就當成不是，寧可多列一行）。"""
    try:
        return abs((datetime.fromisoformat(later_iso)
                    - datetime.fromisoformat(earlier_iso)).total_seconds()) <= seconds
    except Exception:
        return False


# ── 同時編輯警示（2026-09-14，DB v81）───────────────────────────────────────
#
# 第一道防線（存檔時比對 updated_at 回 409）早就存在；這裡補的是「一進去就知道
# 有人在編」，讓人來得及先喊一聲，而不是打完字才發現白做。
#
# 任何登入者都可以回報與查詢——這不是敏感資料，而且**擋住查詢反而讓功能失效**：
# 看不到別人在編，就等於沒有警示。

_PRESENCE_TTL = 90          # 秒：超過沒心跳就視為離開（前端每 30 秒送一次）


class EditPresenceIn(BaseModel):
    doc_type: str
    doc_id: str


def _active_presence(conn, doc_type: str, doc_id: str, exclude_user_id: int = None):
    cutoff = (datetime.now() - timedelta(seconds=_PRESENCE_TTL)).isoformat()
    rows = conn.execute(
        "SELECT user_id, username, display_name, started_at, last_seen_at "
        "FROM edit_presence WHERE doc_type=? AND doc_id=? AND last_seen_at >= ? "
        "ORDER BY started_at",
        (doc_type, doc_id, cutoff),
    ).fetchall()
    return [{
        "userId": r["user_id"],
        "username": r["username"],
        "displayName": r["display_name"] or r["username"],
        "startedAt": r["started_at"],
        "lastSeenAt": r["last_seen_at"],
    } for r in rows if not exclude_user_id or r["user_id"] != exclude_user_id]


@router.post("/api/edit-presence")
def edit_presence_heartbeat(body: EditPresenceIn, authorization: str = Header(None)):
    """回報「我正在編這份文件」，並取回目前還有誰在編（不含自己）。

    前端每 30 秒送一次（`edit-presence.js`），超過 `_PRESENCE_TTL`(90s) 沒更新就
    視為離開——**不依賴「關頁面時要記得通知伺服器」**，那種事件在當機、斷網、
    直接關電腦時一定收不到。`DELETE` 只是讓正常離開更即時，不是正確性的依賴。
    """
    user = _require_user(authorization)
    doc_type = (body.doc_type or "").strip()[:40]
    doc_id = (body.doc_id or "").strip()[:80]
    if not doc_type or not doc_id:
        raise HTTPException(400, "缺少 doc_type / doc_id")

    now = datetime.now().isoformat()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO edit_presence (doc_type, doc_id, user_id, username, display_name, "
            "started_at, last_seen_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(doc_type, doc_id, user_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
            (doc_type, doc_id, user["id"], user["username"],
             user["display_name"] or user["username"], now, now),
        )
        conn.commit()
        others = _active_presence(conn, doc_type, doc_id, exclude_user_id=user["id"])
    finally:
        conn.close()
    return {"docType": doc_type, "docId": doc_id, "others": others, "ttlSeconds": _PRESENCE_TTL}


@router.delete("/api/edit-presence")
def edit_presence_release(body: EditPresenceIn, authorization: str = Header(None)):
    """離開編輯畫面時主動釋放（讓其他人更快看到警示消失）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM edit_presence WHERE doc_type=? AND doc_id=? AND user_id=?",
            ((body.doc_type or "").strip()[:40], (body.doc_id or "").strip()[:80], user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.get("/api/system/case-roles-unmapped")
def case_roles_unmapped(authorization: str = Header(None)):
    """案件角色還沒對應到帳號的清單（CM3，2026-09-24 使用者裁示「查不到或同名的不猜、列出清單」）。

    升級轉換（db.py::_m116_case_roles_username）只轉「顯示名稱剛好對到一個帳號」的；其餘保留原字串，
    在這裡列出，由 superadmin 到案件頁重新選一次。唯讀；顯示在「使用者管理」頁。
    """
    from helpers.case_roles import ROLE_KEYS, ROLE_LABELS
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        counts = {}
        for u in conn.execute("SELECT display_name FROM users").fetchall():
            name = (u["display_name"] or "").strip()
            if name:
                counts[name] = counts.get(name, 0) + 1
        rows = conn.execute(
            "SELECT quote_no, customer_name, project_name, data_json FROM quotations "
            "WHERE json_type(data_json, '$.caseRecord.roles') = 'object' ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    items = []
    for r in rows:
        try:
            roles = (json.loads(r["data_json"] or "{}").get("caseRecord") or {}).get("roles") or {}
        except (TypeError, ValueError):
            continue
        for key in ROLE_KEYS:
            v = roles.get(key) if isinstance(roles, dict) else None
            if not isinstance(v, str) or not v.strip():
                continue
            n = counts.get(v.strip(), 0)
            reason = ("查無此名稱的帳號" if n == 0 else
                      "同名 %d 個帳號，無法判斷是哪一位" % n if n > 1 else
                      "尚未轉換（對得到唯一帳號，到案件頁重新選一次即可）")
            items.append({"quoteNo": r["quote_no"], "customer": r["customer_name"] or "",
                          "project": r["project_name"] or "", "role": key, "roleLabel": ROLE_LABELS[key],
                          "value": v, "reason": reason})
    return {"items": items}


@router.get("/api/settings/reminder-send-failures")
def get_reminder_send_failures(authorization: str = Header(None)):
    """簽核提醒**永久寄不出去**的那幾筆。

    2026-09-26：自 routers/daily_tasks.py 移來（簽核催辦已下沉 L1 helpers/system_checks.py；
    留在每日任務模組的話，停用每日任務會讓這個落點一起消失）。

    ## 🔴 這個端點存在的理由，比「多一個 API」深一層
    YA5 要求失敗要有落點，而 A 的原話是：
    > ⚠️ **落點要看得到** —— ☠️ 只寫進 log 的話就是把這一條原封不動換了個位置。

    📌 那正是這一整節在修的形狀：**一個沒有人看得到的事實等於沒有發生過。**
    ⇒ 一筆紀錄回答的是「**哪一張單子、哪一階、為什麼、試了幾次**」，
    而那四個合起來才足以讓人去處置它（通常是去幫那個人填 email）。

    ⚠️ 限 superadmin：它列得出單號與簽核流程的狀態。
    """
    _require_user(authorization, require_superadmin=True, module='settings')
    # 最新的排前面 —— 使用者要看的是「現在還卡著什麼」。
    from helpers.system_checks import reminder_send_failures
    return {"items": list(reversed(reminder_send_failures()))}


# ══ 品牌圖檔（2026-09-27 H10；使用者：「公司名稱、公司LOGO這些都要能在設定中上傳跟修改」）════════════════
#
# 驗證、存放、預設回退都在 L1 `helpers.branding`；這裡只接 HTTP、權限與 audit。
# 讀取端點公開（登入頁還沒有 session；favicon 由瀏覽器直接抓），列在 main._PUBLIC_API_PATHS。
# 快取：網址帶的 `?v=` 等於目前版本 ⇒ 一年 immutable；沒帶或不相符 ⇒ no-cache＋ETag（每次重新驗證，換圖後下一次載入就是新的）。

@router.get("/api/system/branding/{kind}")
def get_branding_asset(kind: str, v: str = None, if_none_match: str = Header(None)):
    from fastapi.responses import FileResponse, Response
    from helpers import branding
    if kind not in branding.KINDS:
        raise HTTPException(404, "查無此圖檔")
    path, version = branding.asset_file(kind)
    etag = '"%s"' % version
    if v and v == version:
        cache = "public, max-age=31536000, immutable"
    else:
        cache = "no-cache"
    headers = {"Cache-Control": cache, "ETag": etag}
    if if_none_match and etag in [t.strip() for t in if_none_match.split(",")]:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type="image/png", headers=headers)


def _branding_state_out() -> dict:
    from helpers import branding
    state = _get_setting(branding.SETTING_KEY, {}) or {}
    urls = branding.asset_urls()
    out = {}
    for kind, spec in branding.KINDS.items():
        entry = state.get(kind) if isinstance(state, dict) else None
        custom = branding.asset_version(kind) is not None
        out[kind] = {"label": spec["label"], "custom": custom, "url": urls[kind],
                     "updatedAt": (entry or {}).get("updatedAt", "") if custom else "",
                     "by": (entry or {}).get("by", "") if custom else ""}
    return out


def _branding_refuse_demo() -> None:
    """展示帳號不可以改正式安裝的品牌（權限另由各端點的 `_require_user(..., require_superadmin=True)` 檢查）。"""
    from db import is_demo_mode
    if is_demo_mode():
        raise HTTPException(403, "展示帳號不可以更換品牌圖檔")


@router.get("/api/settings/branding")
def get_branding_settings(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from helpers import branding
    return {"assets": _branding_state_out(),
            "limits": {"maxBytes": branding.MAX_UPLOAD_BYTES, "maxSide": branding.MAX_SIDE,
                       "formats": list(branding.ALLOWED_FORMATS)}}


@router.put("/api/settings/branding/{kind}")
async def upload_branding_asset(kind: str, request: Request, file: UploadFile = File(...), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)   # 只有 superadmin（不接受持有 settings 模組）
    _branding_refuse_demo()
    from helpers import branding
    if kind not in branding.KINDS:
        raise HTTPException(404, "查無此圖檔種類")
    data = await file.read(branding.MAX_UPLOAD_BYTES + 1)
    try:
        saved = branding.save_asset(kind, data, by=user.get("username", ""))
    except branding.BrandingRejected as e:
        raise HTTPException(400, str(e))
    _audit(_tok(authorization), branding.AUDIT_ACTION, "settings", "branding",
           branding.KINDS[kind]["label"],
           dict({"kind": kind, "op": "upload", "v": saved["v"], "bytes": saved["bytes"]}, **({"ui": "wizard"} if _ui_is_wizard(request) else {})))
    return {"ok": True, "kind": kind, "v": saved["v"], "assets": _branding_state_out()}


@router.delete("/api/settings/branding/{kind}")
def reset_branding_asset(kind: str, request: Request, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _branding_refuse_demo()
    from helpers import branding
    if kind not in branding.KINDS:
        raise HTTPException(404, "查無此圖檔種類")
    had = branding.reset_asset(kind)
    _audit(_tok(authorization), branding.AUDIT_ACTION, "settings", "branding",
           branding.KINDS[kind]["label"],
           dict({"kind": kind, "op": "reset", "hadCustom": had}, **({"ui": "wizard"} if _ui_is_wizard(request) else {})))
    return {"ok": True, "kind": kind, "assets": _branding_state_out()}
