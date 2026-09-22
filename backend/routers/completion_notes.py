"""完工單（Completion / Work Completion Note）：CRUD ＋ 分層簽核 ＋ PDF ＋ 客戶驗收回簽。

2026-09-12 交辦：「在案件管理內增加完工單的選項，參考出貨單的形式跟內容建立完工單，
一樣走流程申請完工。」所以整支刻意比照 `routers/shipping_notes.py`——同一套狀態機、
同一套分層簽核（`unified_approval_flow`，文件類型 `completion`）、同一套回簽機制。
一個報價單（quote_no）可對應多張完工單（分階段／分區完工）。

**跟出貨單刻意不同的三件事**

1. **沒有庫存扣減**。出貨單核准時會把序號從 `stock_items` 扣掉（`in_stock` →
   `shipped`），完工單不碰庫存——東西早就在出貨單那一關出掉了，完工單記的是
   「工程做完了」，兩者不是同一件事。跟著抄庫存那段會變成同一批序號被扣兩次。
2. **核准條件是「至少一項完工項目」**，而且項目有 `status`（完成／部分完成／
   未施作）——完工不等於零缺失，未完成的部分靠 `pending_items` 留底。
3. **保固自完工日起算**（`warranty_months`），PDF 上印出保固起訖。刻意**不**自動
   建立保固追蹤紀錄：保固模組有自己的資料來源，偷偷塞一筆會變成兩套來源打架。

欄位設計與理由見 `db.py::_m077_completion_notes()` 的 docstring。
"""
import json
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Body, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_db, next_entity_code
from helpers import (
    _require_user, _tok, _audit, _notify, _purge_notifications,
    notify_module_activity,
    active_tiers as _active_tiers, current_tier_idx as _current_tier_idx,
    setting_to_active_tiers as _setting_to_active_tiers,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    cascade_self_tiers, notify_org_chain_notice,
    UnresolvedManagerError, resolve_active_flow_setting,
    save_document_files, delete_document_file,
    guard_case_access, require_any_module,
)
from pdf_gen import generate_completion_pdf_bytes

router = APIRouter()

# 完工項目的完成狀態。**刻意允許「部分完成」與「未施作」**——完工單如果只能
# 填「完成」，現場就會被迫把沒做完的東西也勾完成，遺留事項那欄就永遠是空的。
ITEM_STATUSES = ("完成", "部分完成", "未施作")

# ── 可自訂標題（2026-09-12 使用者回饋）────────────────────────────────────────
#
# 第一版的用語全部偏工程（施工地點、工程期間、施工說明、承攬商·工程負責人…），
# 但公司除了工程還有專案、零組件販售、系統設定、網路架構、防火牆等業務，那些單子
# 用「施工」講不通。所以：
#
#   1. **預設值改成中性用語**（服務地點／執行期間／完成項目／執行說明…）
#   2. 每一張完工單都可以自己覆寫這些標題（前端另備幾組預設可一鍵套用）
#
# **存在 `data_json.labels` 而不是開新欄位**：這些純粹是列印用的字串，永遠整包
# 讀寫、不會被查詢或彙總，正是 data_json 適合放的東西。（額外支出當初要正規化
# 出來，是因為每一列需要各自的簽核狀態與稽核軌跡，跟這裡不是同一種需求。）
DEFAULT_LABELS = {
    "sectionCustomer": "一、客戶與服務地點",
    "sectionPeriod":   "二、執行期間與保固",
    "sectionItems":    "三、完成項目明細",
    "sectionSummary":  "四、執行說明",
    "sectionTest":     "五、測試與檢驗結果",
    "sectionPending":  "六、待辦與未完成事項",
    "itemColumn":      "項目 / 規格說明",
    "siteLabel":       "服務地點",
    "managerLabel":    "負責人",
    "signOwner":       "客戶驗收 · 簽章",
    "signVendor":      "執行單位 · 負責人",
}
_LABEL_MAX = 40


def merged_labels(raw: dict) -> dict:
    """使用者覆寫值疊在預設值上。空字串視為「沒覆寫」而不是「標題留白」——
    列印時標題整個消失只會讓人以為版面壞了。"""
    out = dict(DEFAULT_LABELS)
    for k, v in (raw or {}).items():
        if k in DEFAULT_LABELS and isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


class CompletionNoteIn(BaseModel):
    quote_no:        str
    site_address:    Optional[str]  = ''
    start_date:      Optional[str]  = ''
    completion_date: Optional[str]  = ''
    site_manager:    Optional[str]  = ''
    recipient:       Optional[str]  = ''
    contact_phone:   Optional[str]  = ''
    customer_name:   Optional[str]  = ''
    project_name:    Optional[str]  = ''
    items:           Optional[list] = []
    work_summary:    Optional[str]  = ''
    test_result:     Optional[str]  = ''
    warranty_months: Optional[int]  = 12
    pending_items:   Optional[str]  = ''
    notes:           Optional[str]  = ''
    # 只接受 DEFAULT_LABELS 裡有的鍵，其餘忽略（見 _validate()）
    labels:          Optional[dict] = None
    # 樂觀鎖（2026-09-14）：載入時拿到的 updated_at，存檔時送回來比對。
    # **選填**——舊前端／其他呼叫端不送就維持原本行為，不會因為這個欄位壞掉。
    expected_updated_at: Optional[str] = None


def _require_admin(user: dict):
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")


def _warranty_range(completion_date: str, months: int) -> tuple:
    """保固起訖。起算日＝完工日，迄日＝完工日 + N 個月（同日、月底溢位往前收）。

    用既有的 `helpers/dates.py::_add_months()`，不要自己再寫一份月份加法——
    2/28、月底、跨年那幾個 edge case 那支已經處理過了。

    ⚠️ `_add_months()` 吃的是 `datetime.date` **物件**、回傳也是物件，不是字串。
    第一版直接把字串丟進去，TypeError 被 `except Exception` 吞掉，結果保固迄日
    永遠是空字串、畫面與 PDF 都只是「沒顯示」而不會報錯——測試才抓出來。所以
    現在只吞 `ValueError`（完工日格式不合法，屬預期情況），型別錯不再靜默。"""
    raw = (completion_date or "").strip()[:10]
    # 月數 0／留空＝這張單不談保固（比照報價單「條件留空就不印」）。此時連起算日
    # 都不該回——回一個「保固 2026-09-10 ～ 2026-09-10」比留白更容易被誤讀。
    if not raw or int(months or 0) <= 0:
        return "", ""
    from datetime import date as _date
    from helpers.dates import _add_months
    try:
        start = _date.fromisoformat(raw)
    except ValueError:
        return raw, ""
    return start.isoformat(), _add_months(start, int(months or 0)).isoformat()


def _note_public(row, include_items: bool = True) -> dict:
    """DB row → camelCase API 形狀（比照 shipping_notes.py::_note_public()，
    案件管理前端吃的是同一種形狀）。"""
    d = dict(row)
    items = json.loads(d.get("items_json") or "[]")
    _dj = json.loads(d.get("data_json") or "{}") or {}
    approval = _dj.get("approval") or {}
    w_start, w_end = _warranty_range(d.get("completion_date") or "", d.get("warranty_months") or 0)
    out = {
        "id":              d["id"],
        "noteNo":          d["note_no"],
        "quoteNo":         d["quote_no"],
        "status":          d["status"] or "草稿",
        "customerName":    d.get("customer_name") or "",
        "projectName":     d.get("project_name") or "",
        "siteAddress":     d.get("site_address") or "",
        "startDate":       d.get("start_date") or "",
        "completionDate":  d.get("completion_date") or "",
        "siteManager":     d.get("site_manager") or "",
        "recipient":       d.get("recipient") or "",
        "contactPhone":    d.get("contact_phone") or "",
        "workSummary":     d.get("work_summary") or "",
        "testResult":      d.get("test_result") or "",
        "warrantyMonths":  d.get("warranty_months") or 0,
        "warrantyStart":   w_start,
        "warrantyEnd":     w_end,
        # 保固留空／填 0 = 完工單上不顯示保固那一列（比照報價單「條件留空就不印」）
        "showWarranty":    bool(d.get("warranty_months") or 0),
        "labels":          merged_labels(_dj.get("labels")),
        "labelOverrides":  _dj.get("labels") or {},
        "pendingItems":    d.get("pending_items") or "",
        "notes":           d.get("notes") or "",
        "itemCount":       len(items),
        # 有沒有沒做完的項目——前端要用這個提醒「這張單有未完成項目」，
        # 不是只看 pending_items 那段文字（那欄很常被留白）
        "unfinishedCount": sum(1 for it in items
                               if it.get("type") != "header" and it.get("status") in ("部分完成", "未施作")),
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


def _validate(body: CompletionNoteIn):
    if body.warranty_months is not None and not (0 <= int(body.warranty_months) <= 600):
        raise HTTPException(400, "保固月數需介於 0～600")
    if body.start_date and body.completion_date and body.start_date > body.completion_date:
        raise HTTPException(400, "完工日期不能早於開工日期")
    for it in (body.items or []):
        if it.get("type") == "header":
            continue
        st = it.get("status")
        if st and st not in ITEM_STATUSES:
            raise HTTPException(400, f"完工狀態必須是：{'／'.join(ITEM_STATUSES)}")
    for k, v in (body.labels or {}).items():
        if k not in DEFAULT_LABELS:
            raise HTTPException(400, f"未知的標題欄位：{k}")
        if not isinstance(v, str) or len(v) > _LABEL_MAX:
            raise HTTPException(400, f"標題「{k}」需為 {_LABEL_MAX} 字以內的文字")


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/completion-notes")
def list_completion_notes(quote_no: Optional[str] = None, authorization: str = Header(None)):
    # 2026-09-13（模組權限稽核）：帶 quote_no 就是「讀某一張案件的完工單」——
    # `quote_no` 可列舉，先前只要求登入等於任何人都撈得到別人案件的單據與金額。
    # 不帶 quote_no 是跨案件總覽，改為管理員或具相關模組的人才看得到。
    user = _require_user(authorization)
    conn = get_db()
    if quote_no:
        guard_case_access(conn, quote_no, user, allow_module="case_manage")
    else:
        # `quotation` 也要收：簽核佇列（模組 quotation）就是用這支載入待簽的單據
        require_any_module(user, ('case_manage', 'quotation'), "完工單")
    try:
        if quote_no:
            rows = conn.execute(
                "SELECT * FROM completion_notes WHERE quote_no=? ORDER BY id DESC", (quote_no,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM completion_notes ORDER BY id DESC LIMIT 200").fetchall()
        return {"items": [_note_public(r, include_items=False) for r in rows]}
    finally:
        conn.close()


@router.get("/api/completion-notes/{note_no}")
def get_completion_note(note_no: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM completion_notes WHERE note_no=?", (note_no,)).fetchone()
        if not row:
            raise HTTPException(404, "完工單不存在")
        return _note_public(row)
    finally:
        conn.close()


@router.post("/api/completion-notes", status_code=201)
def create_completion_note(body: CompletionNoteIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    _validate(body)
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        q = conn.execute(
            "SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (body.quote_no,)
        ).fetchone()
        if not q:
            raise HTTPException(404, "找不到關聯的報價單")
        customer_name = (body.customer_name or '').strip() or (q["customer_name"] or "")
        project_name  = (body.project_name or '').strip() or (q["project_name"] or "")
        note_no = next_entity_code(conn, "completion_notes", "CN", code_col="note_no")
        conn.execute(
            "INSERT INTO completion_notes "
            "(note_no, quote_no, status, customer_name, project_name, site_address, start_date, "
            " completion_date, site_manager, recipient, contact_phone, items_json, work_summary, "
            " test_result, warranty_months, pending_items, notes, data_json, created_by, "
            " created_at, updated_at) "
            "VALUES (?,?,'草稿',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (note_no, body.quote_no, customer_name, project_name, body.site_address or "",
             body.start_date or "", body.completion_date or "", body.site_manager or "",
             body.recipient or "", body.contact_phone or "",
             json.dumps(body.items or [], ensure_ascii=False),
             body.work_summary or "", body.test_result or "",
             int(body.warranty_months or 0), body.pending_items or "", body.notes or "",
             json.dumps({"labels": body.labels or {}}, ensure_ascii=False),
             user["username"], now, now),
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "completion.create", "completion_note", note_no,
           f"{note_no}（{customer_name}）")
    notify_module_activity("完工單", "建立", user.get("display_name") or user["username"],
                           f"{note_no}（{customer_name}）", f"case-management.html?q={body.quote_no}")
    return {"note_no": note_no, "created_at": now}


@router.put("/api/completion-notes/{note_no}")
def update_completion_note(note_no: str, body: CompletionNoteIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    _validate(body)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT status, data_json, updated_at FROM completion_notes WHERE note_no=?",
            (note_no,)).fetchone()
        if not row:
            raise HTTPException(404, "完工單不存在")
        if row["status"] != "草稿":
            raise HTTPException(409, "僅草稿狀態可編輯")
        # 同時編輯保護（2026-09-14 使用者要求）：兩個人同時開同一張完工單時，
        # 後存的人不該把先存的人的內容無聲蓋掉。比照報價單／案件資料既有的作法
        # ——不是鎖，而是「你看到的版本已經過期了，請重新載入」。
        # 進入畫面時的警示由 `edit-presence.js` 負責（那是提早知道，這是最後防線）。
        if (body.expected_updated_at and row["updated_at"]
                and body.expected_updated_at != row["updated_at"]):
            raise HTTPException(409, "完工單已被其他人更新，請重新載入後再存")
        now = datetime.now().isoformat()
        # ⚠️ read-modify-write：data_json 裡除了 labels 還有 approval（被駁回退回草稿
        # 的單子仍留著歷史），整包覆蓋會把它清掉
        dj = json.loads(row["data_json"] or "{}") or {}
        dj["labels"] = body.labels or {}
        conn.execute(
            "UPDATE completion_notes SET customer_name=?, project_name=?, site_address=?, "
            " start_date=?, completion_date=?, site_manager=?, recipient=?, contact_phone=?, "
            " items_json=?, work_summary=?, test_result=?, warranty_months=?, pending_items=?, "
            " notes=?, data_json=?, updated_at=? "
            "WHERE note_no=?",
            (body.customer_name or "", body.project_name or "", body.site_address or "",
             body.start_date or "", body.completion_date or "", body.site_manager or "",
             body.recipient or "", body.contact_phone or "",
             json.dumps(body.items or [], ensure_ascii=False),
             body.work_summary or "", body.test_result or "", int(body.warranty_months or 0),
             body.pending_items or "", body.notes or "",
             json.dumps(dj, ensure_ascii=False), now, note_no),
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "completion.update", "completion_note", note_no, note_no)
    return {"ok": True, "updated_at": now}


@router.delete("/api/completion-notes/{note_no}")
def delete_completion_note(note_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    try:
        row = conn.execute("SELECT status FROM completion_notes WHERE note_no=?", (note_no,)).fetchone()
        if not row:
            raise HTTPException(404, "完工單不存在")
        if row["status"] != "草稿":
            raise HTTPException(409, "僅草稿狀態可刪除")
        conn.execute("DELETE FROM completion_notes WHERE note_no=?", (note_no,))
        conn.commit()
    finally:
        conn.close()
    _purge_notifications(note_no, ['completion_approval_request', 'completion_approved',
                                   'completion_returned'])
    _audit(_tok(authorization), "completion.delete", "completion_note", note_no, note_no)
    notify_module_activity("完工單", "刪除", user.get("display_name") or user["username"],
                           note_no, "case-management.html")
    return {"ok": True}


# ── 簽核流程（比照 shipping_notes.py，語意逐條對齊）──────────────────────────

@router.post("/api/completion-notes/{note_no}/submit")
def submit_completion_note(note_no: str, authorization: str = Header(None)):
    """申請完工。送審前擋兩件事：至少一項完工項目、完工日期必填——完工單沒有
    完工日期，保固起算與工期都無從認定，是這張單存在的意義本身。"""
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT status, data_json, customer_name, items_json, completion_date "
        "FROM completion_notes WHERE note_no=?", (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "完工單不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可送出審核")
    items = json.loads(row["items_json"] or "[]")
    if not any((it.get("description") or "").strip() for it in items if it.get("type") != "header"):
        conn.close()
        raise HTTPException(400, "至少需要一項完工項目說明")
    if not (row["completion_date"] or "").strip():
        conn.close()
        raise HTTPException(400, "請填寫完工日期（保固起算日與工期都以它為準）")

    cname = row["customer_name"] or ""
    d     = json.loads(row["data_json"] or "{}")
    now   = datetime.now().isoformat()

    flow_setting = resolve_active_flow_setting("completion")
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
        for a in active_tiers[0].get("approvers") or []:
            _notify(a["username"], "completion_approval_request", note_no, note_no,
                    f"完工單 {note_no}（{cname}）需要您簽核")

    # 知會（2026-09-15）：整條簽核鏈都只有申請人本人時（他已在組織職權頂端），
    # 最高管理者不再被塞進簽核鏈，改收一則知會通知（仍可隨時以 superadmin 退回）。
    notify_org_chain_notice(conn, active_tiers, user["username"], note_no, note_no,
                            f"完工單 {note_no}（{cname}）由 "
                            f"{user.get('display_name') or user['username']} 依組織職權自行簽核，知會您",
                            type_="completion_approval_notice")

    conn.execute(
        "UPDATE completion_notes SET status='待審核', data_json=?, updated_at=? WHERE note_no=?",
        (json.dumps(d, ensure_ascii=False), now, note_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "completion.submit", "completion_note", note_no,
           f"{note_no}（{cname}）", {"tierCount": len(active_tiers)})
    return {"ok": True, "status": "待審核"}


@router.post("/api/completion-notes/{note_no}/approve")
def approve_completion_note(note_no: str, body: dict = Body(default={}),
                            authorization: str = Header(None)):
    """核准當層。能否簽核純粹由「是否為當層簽核人員」決定，**不額外要求 admin 角色**
    ——簽核設定頁允許把任何角色加進簽核人清單，硬擋 admin 會讓非管理員簽核人卡死
    （出貨單當初漏掉這條、2026-08-22 架構複查才補上，這裡一開始就照做）。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM completion_notes "
        "WHERE note_no=? AND status IN ('待審核','簽核中')", (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"完工單 {note_no} 不存在或不在待審核狀態")
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
        approvers = tiers[ct_idx].get("approvers") or []
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
        if tier_done:
            appr["currentTier"] = landed
            all_done = landed >= len(tiers)
            if not all_done:
                for na in tiers[landed].get("approvers") or []:
                    _notify(na["username"], "completion_approval_request", note_no, note_no,
                            f"完工單 {note_no}（{cname}）輪到您簽核"
                            f"（第 {landed + 1} 層 / 共 {len(tiers)} 層）")
        else:
            all_done = False
        appr["tiers"] = tiers
        _signed_tier_nos = [i + 1 for i in [ct_idx, *cascaded]]
        detail_status = (f"第 {'、'.join(str(x) for x in _signed_tier_nos)} 層 "
                         f"{first_pending.get('displayName', user['username'])} 已簽核")
    else:
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")
        _global_flow = resolve_active_flow_setting("completion")
        try:
            _global_tiers = _setting_to_active_tiers(_global_flow, conn, appr.get("requestedBy"))
        except UnresolvedManagerError as e:
            conn.close()
            raise HTTPException(400, str(e))
        if _global_tiers:
            conn.close()
            raise HTTPException(403, "系統已設定簽核流程，此完工單缺少簽核層資料，請重新送審")
        self_block_msg = check_no_tier_self_approval(conn, appr, user)
        if self_block_msg:
            conn.close()
            raise HTTPException(403, self_block_msg)
        all_done      = True
        _signed_tier_nos = []
        detail_status = "超級管理員簽核"

    if all_done:
        appr["approvedBy"]        = user["username"]
        appr["approvedByDisplay"] = user.get("display_name") or user["username"]
        appr["approvedAt"]        = now
        appr["status"]            = "approved"
        d["approval"] = appr
        conn.execute(
            "UPDATE completion_notes SET status='已核准', data_json=?, updated_at=? WHERE note_no=?",
            (json.dumps(d, ensure_ascii=False), now, note_no))
        conn.commit()
        requester = appr.get("requestedBy")
        if requester:
            _notify(requester, "completion_approved", note_no, note_no,
                    f"完工單 {note_no}（{cname}）已核准")
        notify_module_activity("完工單", "核准",
                               appr.get("approvedByDisplay") or user["username"],
                               f"{note_no}（{cname}）", "case-management.html")
        detail_status = "已核准"
    else:
        d["approval"] = appr
        new_status = "簽核中" if (appr.get("currentTier") or 0) > 0 else "待審核"
        conn.execute(
            "UPDATE completion_notes SET status=?, data_json=?, updated_at=? WHERE note_no=?",
            (new_status, json.dumps(d, ensure_ascii=False), now, note_no))
        conn.commit()

    conn.close()
    _audit(_tok(authorization), "completion.approve", "completion_note", note_no,
           f"{note_no}（{cname}）", {"allDone": all_done, "status": detail_status})
    return {"ok": True, "allDone": all_done, "signedTiers": _signed_tier_nos}


@router.post("/api/completion-notes/{note_no}/reject")
def reject_completion_note(note_no: str, body: dict = Body(default={}),
                           authorization: str = Header(None)):
    """退回草稿。權限由當層簽核人員判斷，不額外要求 admin 角色。"""
    user = _require_user(authorization)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM completion_notes "
        "WHERE note_no=? AND status IN ('待審核','簽核中')", (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"完工單 {note_no} 不存在或不在待審核狀態")
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
        "UPDATE completion_notes SET status='草稿', data_json=?, updated_at=? WHERE note_no=?",
        (json.dumps(d, ensure_ascii=False), now, note_no))
    conn.commit()
    conn.close()
    if requester:
        _notify(requester, "completion_returned", note_no, note_no,
                f"完工單 {note_no}（{cname}）已退回，請確認後重新送審"
                + (f"：{note}" if note else ""))
    _audit(_tok(authorization), "completion.reject", "completion_note", note_no,
           f"{note_no}（{cname}）", {"note": note})
    return {"ok": True}


@router.post("/api/completion-notes/{note_no}/revoke-approval")
def revoke_completion_approval(note_no: str, body: dict = Body(default={}),
                               authorization: str = Header(None)):
    """撤銷已核准的完工單，退回草稿。

    **已回簽（客戶已驗收簽收）的不可撤銷**——客戶都簽了，系統這邊不該再反悔；
    要撤銷請先取消回簽。這條跟出貨單同一個判斷，理由也一樣。

    出貨單撤銷時要歸還庫存序號，完工單沒有那段（完工單不碰庫存，見檔頭說明）。
    """
    user = _require_user(authorization)
    _require_admin(user)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name, is_signed FROM completion_notes "
        "WHERE note_no=? AND status='已核准'", (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"完工單 {note_no} 不存在或不在已核准狀態")
    if row["is_signed"]:
        conn.close()
        raise HTTPException(409, "已回簽（客戶已驗收）的完工單不可撤銷核准，請先取消回簽")
    cname = row["customer_name"] or ""
    d = json.loads(row["data_json"] or "{}")
    requester = (d.get("approval") or {}).get("requestedBy")
    d.pop("approval", None)
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE completion_notes SET status='草稿', data_json=?, updated_at=? WHERE note_no=?",
        (json.dumps(d, ensure_ascii=False), now, note_no))
    conn.commit()
    conn.close()
    if requester:
        _notify(requester, "completion_returned", note_no, note_no,
                f"完工單 {note_no}（{cname}）核准已被撤銷，請確認後重新送審"
                + (f"：{note}" if note else ""))
    _audit(_tok(authorization), "completion.revoke_approval", "completion_note", note_no,
           f"{note_no}（{cname}）", {"note": note})
    return {"ok": True}


# ── PDF / 匯出紀錄 ────────────────────────────────────────────────────────────

@router.get("/api/completion-notes/{note_no}/pdf-download")
def download_completion_pdf(note_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT note_no FROM completion_notes WHERE note_no=?", (note_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "完工單不存在")
    try:
        pdf_bytes = generate_completion_pdf_bytes(note_no)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"PDF 產生失敗：{e}")
    encoded = urlquote(f"{note_no}.pdf")
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"})


@router.post("/api/completion-notes/{note_no}/export")
def record_completion_export(note_no: str, mode: str = "external", authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT export_count, export_log FROM completion_notes WHERE note_no=?", (note_no,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"完工單 {note_no} 不存在")
        log   = json.loads(row["export_log"] or "[]")
        count = (row["export_count"] or 0) + 1
        log.append({"at": datetime.now().isoformat(), "mode": mode, "user": user["username"],
                    "userDisplay": user.get("display_name") or user["username"], "count": count})
        conn.execute("UPDATE completion_notes SET export_count=?, export_log=? WHERE note_no=?",
                     (count, json.dumps(log, ensure_ascii=False), note_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "completion.export_pdf", "completion_note", note_no,
           f"{note_no} PDF 匯出（{mode}）by {user['username']}")
    return {"export_count": count, "log": log}


# ── 客戶驗收回簽 ──────────────────────────────────────────────────────────────

@router.post("/api/completion-notes/{note_no}/signed-toggle")
def toggle_completion_signed(note_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """標記／取消「客戶已驗收簽回」。完工單的回簽比出貨單更關鍵——它是保固起算
    與尾款請款的依據，所以每一次標記與取消都留在 `signed_log` 裡（含操作人與備註）。"""
    user = _require_user(authorization)
    _require_admin(user)
    action = (body or {}).get("action", "")
    note   = (body or {}).get("note", "")
    if action not in ("sign", "unsign"):
        raise HTTPException(400, "action 必須為 sign 或 unsign")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT status, is_signed, signed_log FROM completion_notes WHERE note_no=?", (note_no,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "完工單不存在")
        if row["status"] != "已核准":
            raise HTTPException(409, "僅已核准狀態可標記客戶驗收")
        is_signed = bool(row["is_signed"])
        if action == "sign" and is_signed:
            raise HTTPException(409, "已回簽，無需重複標記")
        if action == "unsign" and not is_signed:
            raise HTTPException(409, "尚未回簽")

        now = datetime.now().isoformat()
        log = json.loads(row["signed_log"] or "[]")
        log.append({"at": now, "user": user["username"], "username": user["username"],
                    "userDisplay": user.get("display_name") or user["username"],
                    "action": "signed" if action == "sign" else "unsigned", "note": note})
        if action == "sign":
            conn.execute(
                "UPDATE completion_notes SET is_signed=1, signed_by=?, signed_at=?, signed_log=?, "
                "updated_at=? WHERE note_no=?",
                (user.get("display_name") or user["username"], now,
                 json.dumps(log, ensure_ascii=False), now, note_no))
        else:
            conn.execute(
                "UPDATE completion_notes SET is_signed=0, signed_by='', signed_at='', signed_log=?, "
                "updated_at=? WHERE note_no=?",
                (json.dumps(log, ensure_ascii=False), now, note_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), f"completion.{action}", "completion_note", note_no, note_no,
           {"note": note})
    notify_module_activity("完工單", "客戶已驗收" if action == "sign" else "取消驗收標記",
                           user.get("display_name") or user["username"], note_no,
                           "case-management.html", detail=note or "")
    return {"ok": True, "is_signed": action == "sign", "signed_log": log}


@router.post("/api/completion-notes/{note_no}/signed-files", status_code=201)
async def upload_completion_signed_files(note_no: str, files: List[UploadFile] = File(...),
                                         authorization: str = Header(None)):
    """驗收簽回附件（客戶簽名的掃描檔、現場照片、測試報告）。

    刻意不限制單據狀態：草稿階段就先存現場照片是常態，強制要「已核准」才能傳
    只會逼人把檔案先丟在別的地方。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT signed_files_json FROM completion_notes WHERE note_no=?",
                           (note_no,)).fetchone()
        if not row:
            raise HTTPException(404, "完工單不存在")
        existing = json.loads(row["signed_files_json"] or "[]")
        new_files = await save_document_files("completion_notes", note_no, files,
                                              user.get("display_name") or user["username"])
        conn.execute("UPDATE completion_notes SET signed_files_json=?, updated_at=? WHERE note_no=?",
                     (json.dumps(existing + new_files, ensure_ascii=False),
                      datetime.now().isoformat(), note_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "completion.upload_signed_files", "completion_note", note_no,
           f"{note_no}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files}


@router.delete("/api/completion-notes/{note_no}/signed-files/{file_id}")
def delete_completion_signed_file(note_no: str, file_id: str, authorization: str = Header(None)):
    """刪除已回簽附件——**限 admin 以上**（2026-09-14 全系統稽核補上）。

    在此之前這支只有 `_require_user()`：**任何登入者都能刪掉任何完工單的回簽
    附件**，沒有角色、模組或擁有者檢查，而且刪除會連實體檔案一起移除、不可
    復原。這是 tests/test_system_audit_2026_09_14.py 的「刪除端點必須檢查權限」
    那一題掃出來的。

    權限標準跟同日新增的動態附件一致（使用者裁示「刪除要 admin+」）：
    抽掉附件是**只改證據、留下單據本身**，這種事留給管理員。
    """
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可刪除回簽附件")
    conn = get_db()
    try:
        row = conn.execute("SELECT signed_files_json FROM completion_notes WHERE note_no=?",
                           (note_no,)).fetchone()
        if not row:
            raise HTTPException(404, "完工單不存在")
        remaining = delete_document_file("completion_notes", note_no,
                                         json.loads(row["signed_files_json"] or "[]"), file_id)
        conn.execute("UPDATE completion_notes SET signed_files_json=?, updated_at=? WHERE note_no=?",
                     (json.dumps(remaining, ensure_ascii=False),
                      datetime.now().isoformat(), note_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "completion.delete_signed_file", "completion_note", note_no, note_no)
    return {"ok": True}
