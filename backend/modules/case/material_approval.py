# -*- coding: utf-8 -*-
"""叫料（`caseRecord.materialOrders[]`）的審核狀態機（第 31 班 31-C；設計 docs/platform/plans/MATERIAL-ORDER-APPROVAL-DESIGN.md）。

[單位] case:material_approval    [層] L2（M01）    [穩定度] 新（第 31 班）
**資料**：疊加表 `case_material_approvals`（migration 0004），鍵＝(quote_no, item_id)；**沒有疊加列＝舊單**（不溯及既往：
舊單行為與今天相同；舊單被實質編輯 ⇒ 建一列草稿，要先送審）。
**狀態**（與承攬商派發設計同一組值）：`草稿／待審核／簽核中／已核准／已退回`；另有終態 `已取消`（已核准後取消，admin 以上＋理由）。
**簽核**：重用 `helpers/tiered_approval.py` 既有原語（申請人部門主管→組織鏈→最高管理者；沒設簽核層＝送審即核准；不能自簽——
沿用既有規則）；`approval_json`＝既有格式（requestedBy／requestedByDisplay／requestedAt／tiers／currentTier／history）。
**到貨確認**不簽核：只記日期＋確認人＋時間（同一人可確認）。
所有函式**不 commit**（呼叫端在自己的交易內提交）；失敗一律 raise `MaterialApprovalError(status, 訊息)`，端點轉成 HTTPException。
"""
import hashlib
import json
from datetime import date, datetime

from helpers.dates import normalize_date
from helpers.tiered_approval import (
    APPROVAL_DOC_TYPES, UnresolvedManagerError, active_tiers, check_approve_permission, check_no_tier_self_approval,
    check_reject_permission, current_tier_idx, cascade_self_tiers, register_doc_type, resolve_active_flow_setting,
    setting_to_active_tiers, sign_first_pending,
)

DOC_TYPE = "material_order"
DOC_LABEL = "材料申請"
DOC_PREFIX = "MO"

S_DRAFT, S_PENDING, S_IN_PROGRESS, S_APPROVED, S_RETURNED, S_CANCELLED = "草稿", "待審核", "簽核中", "已核准", "已退回", "已取消"
STATUSES = (S_DRAFT, S_PENDING, S_IN_PROGRESS, S_APPROVED, S_RETURNED, S_CANCELLED)
IN_FLIGHT = (S_PENDING, S_IN_PROGRESS)           # 簽核中：實質欄位不可改
EDITABLE = (S_DRAFT, S_RETURNED)                 # 可以修改並（重新）送審

#: 實質欄位：核准後任何一項變動 ⇒ 回草稿、要重新送審（備註、發票日、到貨欄位不算）
#: 32-S4：quoteItemId／poDocCode／poLine（連報價品項、連採購單）也是實質欄位：核准後改連結 ⇒ 回草稿重送審（overPlanReason 是說明、不算）
SUBSTANTIVE_KEYS = ("itemName", "quantity", "unit", "unitPrice", "totalPrice", "supplierId", "quoteItemId", "poDocCode", "poLine")
_NUMERIC = ("quantity", "unitPrice", "totalPrice", "poLine")

#: 付款只能經匯款申請寫入（paid* 的閘；`material_payment.sync_order_paid` 是唯一寫入點）。匯款切片已落地 ⇒ True
#: （主持裁示：半關的金流控制比沒有更糟，31-C 不能帶著 False 出貨）。守門題兩個值都測。
PAID_VIA_REMITTANCE_ONLY = True

#: 新建的叫料單必須指定供應商（`materialOrders[].supplierId`；設計 §3.4 / Q2）：匯款申請要憑它帶出供應商。舊單不溯及既往（開匯款申請時再選）。
SUPPLIER_REQUIRED_ON_NEW = True

# 簽核單據類型：預設跟統一流程（與額外支出同）。重複登記（模組重載）不報錯。
if DOC_TYPE not in APPROVAL_DOC_TYPES:
    register_doc_type(DOC_TYPE, DOC_LABEL, unified=True)


class MaterialApprovalError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _now():
    return datetime.now().isoformat(timespec="seconds")


def case_row(conn, quote_no: str):
    """案件列（dict；沒有 ⇒ None）：`data_json, customer_name, project_name, sales_person_id, sales_person, assigned_user_ids, deal_tag`。
    成交標籤＝欄位優先、空時退回 `data_json.dealTag`，**逐筆在 Python 解析**（不用 SQL_DEAL_TAG／json_extract：壞的一筆不可讓整個查詢丟例外；§G5 #2）。"""
    r = conn.execute("SELECT data_json, customer_name, project_name, sales_person_id, sales_person, assigned_user_ids, deal_tag"
                     " FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not r:
        return None
    d = dict(r)
    tag = d.get("deal_tag") or ""
    if not tag:
        try:
            dj = json.loads(d.get("data_json") or "{}")
        except (TypeError, ValueError):
            dj = {}
        tag = (dj.get("dealTag") or "") if isinstance(dj, dict) else ""
    d["deal_tag"] = tag
    return d


def _display(user):
    return user.get("display_name") or user["username"]


# ── 雜湊（實質欄位）──────────────────────────────────────────────────

def content_hash(order: dict) -> str:
    """實質欄位的正規化雜湊：數字一律轉 float 再序列化（30000 與 30000.0 相同）、字串去前後空白、缺值＝空。"""
    data = {}
    for k in SUBSTANTIVE_KEYS:
        v = (order or {}).get(k)
        if k in _NUMERIC:
            try:
                data[k] = round(float(v or 0), 4)
            except (TypeError, ValueError):
                data[k] = str(v)
        else:
            data[k] = str(v if v is not None else "").strip()
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def substantive_changed(old: dict, new: dict) -> bool:
    return content_hash(old) != content_hash(new)


# ── 讀 ───────────────────────────────────────────────────────────────

def get(conn, quote_no: str, item_id: str):
    """疊加列（dict）；沒有 ⇒ None（＝舊單）。"""
    r = conn.execute("SELECT * FROM case_material_approvals WHERE quote_no=? AND item_id=?", (quote_no, str(item_id))).fetchone()
    return dict(r) if r else None


def rows_for_case(conn, quote_no: str) -> dict:
    return {r["item_id"]: dict(r) for r in conn.execute("SELECT * FROM case_material_approvals WHERE quote_no=?", (quote_no,))}


def status_of(conn, quote_no: str, item_id: str) -> str:
    """'' ＝ 舊單（沒有疊加列）；其餘為 STATUSES。"""
    r = get(conn, quote_no, item_id)
    return r["status"] if r else ""


def counts_as_approved(status: str) -> bool:
    """舊單與已核准視為『可用』（總帳、物流旗標的閘）。"""
    return status in ("", S_APPROVED)


def cost_state(status: str) -> str:
    """報表成本規則：`excluded`（草稿／已退回／已取消不計）、`pending`（待審核／簽核中：計入並標示）、`counted`（已核准與舊單）。"""
    if status in (S_DRAFT, S_RETURNED, S_CANCELLED):
        return "excluded"
    if status in IN_FLIGHT:
        return "pending"
    return "counted"


# ── 單號 ─────────────────────────────────────────────────────────────

def next_doc_code(conn, today: str = "") -> str:
    """`MO-YYYYMMDD-NNNN`（與 A2 費用單據同一個格式：`{前綴}-{YYYYMMDD}-{NNNN}`；`expense_forms.next_doc_code` 的同型寫法）。
    呼叫端要已持有寫鎖（begin_write），否則兩個人同時開單會撞號（doc_code 另有唯一索引擋底）。"""
    day = (today or date.today().isoformat()).replace("-", "")
    stem = "%s-%s-" % (DOC_PREFIX, day)
    row = conn.execute("SELECT MAX(doc_code) FROM case_material_approvals WHERE doc_code LIKE ? AND LENGTH(doc_code)=?",
                       (stem + "%", len(stem) + 4)).fetchone()
    last = int(row[0][-4:]) if row and row[0] else 0
    return "%s%04d" % (stem, last + 1)


# ── 建立草稿 ─────────────────────────────────────────────────────────

def create_draft(conn, quote_no: str, item_id: str, user: dict, reason: str = ""):
    """替一筆叫料建立疊加列（草稿）。已有列 ⇒ 回既有。新增列與舊單被實質編輯時用。"""
    cur = get(conn, quote_no, item_id)
    if cur:
        return cur
    now = _now()
    code = next_doc_code(conn)
    appr = {"history": [{"at": now, "by": user["username"], "byDisplay": _display(user), "action": "create", "tier": 0, "comment": reason}]}
    conn.execute(
        "INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, approval_json, version, created_by, created_at, updated_at)"
        " VALUES (?,?,?,?,?,1,?,?,?)", (quote_no, str(item_id), code, S_DRAFT, json.dumps(appr, ensure_ascii=False), user["username"], now, now))
    return get(conn, quote_no, item_id)


# ── 送審／核准／退回／撤回／取消 ──────────────────────────────────────

def _save(conn, quote_no, item_id, status, appr, now, **extra):
    sets = ["status=?", "approval_json=?", "updated_at=?"]
    args = [status, json.dumps(appr, ensure_ascii=False), now]
    for k, v in extra.items():
        sets.append("%s=?" % k)
        args.append(v)
    args += [quote_no, str(item_id)]
    conn.execute("UPDATE case_material_approvals SET %s WHERE quote_no=? AND item_id=?" % ", ".join(sets), args)


def _appr(row) -> dict:
    try:
        d = json.loads(row.get("approval_json") or "{}")
    except (TypeError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def submit(conn, quote_no: str, order: dict, user: dict, snapshot: dict = None) -> dict:
    """送審（草稿／已退回 → 待審核；沒設簽核層 ⇒ 直接已核准）。回 `{status, tierCount, firstApprovers, autoApproved}`。
    實質欄位的雜湊在**核准當下**以目前的叫料內容存（`order`＝目前 materialOrders 該列）。"""
    item_id = str(order.get("itemId") or "")
    row = get(conn, quote_no, item_id)
    if row is None:
        raise MaterialApprovalError(404, "這筆材料申請還沒有審核單（請先儲存材料申請清單）")
    if row["status"] not in EDITABLE:
        raise MaterialApprovalError(409, "「%s」狀態不可送審" % row["status"])
    flow = resolve_active_flow_setting(DOC_TYPE)
    try:
        tiers = setting_to_active_tiers(flow, conn, user["username"])
    except UnresolvedManagerError as e:
        raise MaterialApprovalError(400, str(e))
    now = _now()
    appr = _appr(row)
    hist = appr.get("history") or []
    link_snap = {"linkSnapshot": snapshot} if snapshot else {}                      # 32-S4：送審當下的連結／超出計畫判定，簽核人看到的是這份
    if not tiers:
        appr.update(link_snap)
        appr.update({"autoApproved": True, "note": "未設定任何簽核層，送審即視為核准", "requestedBy": user["username"],
                     "requestedByDisplay": _display(user), "requestedAt": now})
        hist.append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "submit", "tier": 0, "comment": "自動核准"})
        appr["history"] = hist
        _save(conn, quote_no, item_id, S_APPROVED, appr, now, submitted_by=user["username"], submitted_at=now, approved_at=now,
              content_hash=content_hash(order))
        return {"status": S_APPROVED, "tierCount": 0, "firstApprovers": [], "autoApproved": True}
    appr = {"requestedBy": user["username"], "requestedByDisplay": _display(user), "requestedAt": now, "tiers": tiers, "currentTier": 0,
            "history": hist + [{"at": now, "by": user["username"], "byDisplay": _display(user), "action": "submit", "tier": 0, "comment": ""}], **link_snap}
    _save(conn, quote_no, item_id, S_PENDING, appr, now, submitted_by=user["username"], submitted_at=now)
    return {"status": S_PENDING, "tierCount": len(tiers), "firstApprovers": [a["username"] for a in (tiers[0].get("approvers") or [])],
            "autoApproved": False}


def approve(conn, quote_no: str, order: dict, user: dict, comment: str = "", cascade: bool = False) -> dict:
    """核准當層；全部層過了才「已核准」並存實質欄位雜湊。回 `{status, currentTier, nextApprovers, requester, done}`。"""
    item_id = str(order.get("itemId") or "")
    row = get(conn, quote_no, item_id)
    if row is None:
        raise MaterialApprovalError(404, "找不到這筆材料申請的審核單")
    if row["status"] not in IN_FLIGHT:
        raise MaterialApprovalError(409, "「%s」狀態不在簽核中" % row["status"])
    appr = _appr(row)
    tiers = active_tiers(appr)
    ct = current_tier_idx(appr)
    if tiers:
        ok, code, msg = check_approve_permission(tiers, ct, user["username"], conn)
        if not ok:
            raise MaterialApprovalError(code, msg)
    else:
        err = check_no_tier_self_approval(conn, appr, user)
        if err:
            raise MaterialApprovalError(403, err)
    now = _now()
    tier_done = sign_first_pending(tiers[ct], user, now, conn=conn) if tiers else True
    cascaded = cascade_self_tiers(tiers, ct, user["username"], now, conn=conn) if (tiers and tier_done and cascade) else []
    appr["tiers"] = tiers
    appr["currentTier"] = (ct + 1 + len(cascaded)) if tier_done else ct
    done = appr["currentTier"] >= len(tiers)
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "approve", "tier": ct, "comment": comment or ""})
    status = S_APPROVED if done else S_IN_PROGRESS
    if done:                                                                         # 明列關鍵字（守門 test_case_summary_purpose：禁止 ** 傳參數）
        _save(conn, quote_no, item_id, status, appr, now, approved_at=now, content_hash=content_hash(order))
    else:
        _save(conn, quote_no, item_id, status, appr, now)
    nxt = [] if done else [a["username"] for a in (tiers[appr["currentTier"]].get("approvers") or [])]
    return {"status": status, "currentTier": appr["currentTier"], "nextApprovers": nxt, "requester": appr.get("requestedBy", ""), "done": done,
            "tierNo": appr["currentTier"] + 1, "totalTiers": len(tiers)}


def reject(conn, quote_no: str, item_id: str, user: dict, reason: str) -> dict:
    """退回（任一層當層簽核人或 superadmin；原因必填）→ 已退回，建單人修改後可重送。"""
    row = get(conn, quote_no, item_id)
    if row is None:
        raise MaterialApprovalError(404, "找不到這筆材料申請的審核單")
    if row["status"] not in IN_FLIGHT:
        raise MaterialApprovalError(409, "「%s」狀態不在簽核中" % row["status"])
    appr = _appr(row)
    tiers = active_tiers(appr)
    ct = current_tier_idx(appr)
    ok, code, msg = check_reject_permission(tiers, ct, user, conn)
    if not ok:
        raise MaterialApprovalError(code, msg)
    text = (reason or "").strip()
    if not text:
        raise MaterialApprovalError(400, "退回要填原因")
    now = _now()
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "reject", "tier": ct, "comment": text})
    appr.update({"rejectedAt": now, "rejectedByDisplay": _display(user), "rejectReason": text})
    _save(conn, quote_no, item_id, S_RETURNED, appr, now)
    return {"status": S_RETURNED, "requester": appr.get("requestedBy", ""), "reason": text}


def withdraw(conn, quote_no: str, item_id: str, user: dict) -> dict:
    """撤回（待審核／簽核中 → 草稿）：建單／送審人本人或 admin 以上。"""
    row = get(conn, quote_no, item_id)
    if row is None:
        raise MaterialApprovalError(404, "找不到這筆材料申請的審核單")
    if row["status"] not in IN_FLIGHT:
        raise MaterialApprovalError(409, "「%s」狀態不可撤回" % row["status"])
    appr = _appr(row)
    if user["username"] != appr.get("requestedBy") and user["role"] not in ("admin", "superadmin"):
        raise MaterialApprovalError(403, "只有送審人本人或管理員可以撤回")
    now = _now()
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "withdraw", "tier": current_tier_idx(appr), "comment": ""})
    for k in ("tiers", "currentTier"):
        appr.pop(k, None)
    _save(conn, quote_no, item_id, S_DRAFT, appr, now)
    return {"status": S_DRAFT}


def cancel(conn, quote_no: str, item_id: str, user: dict, reason: str) -> dict:
    """取消已核准的叫料單：admin 以上＋必填理由（終態「已取消」；成本與總帳不再計入）。
    還有沒作廢的匯款申請 ⇒ 拒絕（先作廢申請；已有付款明細的申請不能作廢 ⇒ 該叫料單不能取消）。"""
    row = get(conn, quote_no, item_id)
    if row is None:
        raise MaterialApprovalError(404, "找不到這筆材料申請的審核單")
    if user["role"] not in ("admin", "superadmin"):
        raise MaterialApprovalError(403, "只有管理員可以取消已核准的材料申請")
    if row["status"] != S_APPROVED:
        raise MaterialApprovalError(409, "只有已核准的材料申請可以取消（目前「%s」）" % row["status"])
    text = (reason or "").strip()
    if not text:
        raise MaterialApprovalError(400, "取消要填原因")
    from modules.case import material_payment as _mp                                  # 延遲 import：material_payment 也 import 本檔
    if _mp.has_live_payments(conn, quote_no, item_id):
        raise MaterialApprovalError(409, "這張材料申請還有匯款申請，請先作廢申請（已有付款明細者不能取消材料申請）")
    now = _now()
    appr = _appr(row)
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "cancel", "tier": 0, "comment": text})
    _save(conn, quote_no, item_id, S_CANCELLED, appr, now, cancel_reason=text, cancelled_by=user["username"], cancelled_at=now)
    return {"status": S_CANCELLED}


# ── 實質欄位被改（由寫入口的閘呼叫）────────────────────────────────────

def on_substantive_change(conn, quote_no: str, item_id: str, user: dict) -> dict:
    """實質欄位變動時的狀態處理。回 `{"allowed": bool, "status": 新狀態, "reason": 原因碼}`：
    - 沒有疊加列（舊單）⇒ 建草稿（要先送審），允許；
    - 草稿／已退回 ⇒ 允許（仍可編輯）；
    - 待審核／簽核中 ⇒ 不允許（請先撤回）；
    - 已核准 ⇒ 回草稿（版本 +1，歷程記一筆），允許（需重新送審）；已取消 ⇒ 不允許。"""
    row = get(conn, quote_no, item_id)
    if row is None:
        create_draft(conn, quote_no, item_id, user, "舊單實質欄位被修改，需先送審")
        return {"allowed": True, "status": S_DRAFT, "reason": "legacy_to_draft"}
    st = row["status"]
    if st in EDITABLE:
        return {"allowed": True, "status": st, "reason": ""}
    if st in IN_FLIGHT:
        return {"allowed": False, "status": st, "reason": "in_approval"}
    if st == S_CANCELLED:
        return {"allowed": False, "status": st, "reason": "cancelled"}
    now = _now()
    appr = _appr(row)
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "edit_after_approval", "tier": 0,
                                           "comment": "核准後實質欄位變更，需重新送審"})
    for k in ("tiers", "currentTier"):
        appr.pop(k, None)
    _save(conn, quote_no, item_id, S_DRAFT, appr, now, version=int(row["version"] or 1) + 1, approved_at="", content_hash="")
    return {"allowed": True, "status": S_DRAFT, "reason": "approved_to_draft"}


# ── 到貨確認（不簽核）────────────────────────────────────────────────

def record_receipt(conn, quote_no: str, item_id: str, received_on, user: dict) -> dict:
    """到貨確認：必填到貨日期（有效日期）；記錄確認人與時間；只有「已核准」的叫料單可以（同一人可確認）。"""
    row = get(conn, quote_no, item_id)
    if row is None or row["status"] != S_APPROVED:
        raise MaterialApprovalError(409, "只有已核准的材料申請才能確認到貨")
    try:
        day = normalize_date(received_on, "到貨日期")
    except Exception as e:                                                       # noqa: BLE001  HTTPException 或 ValueError：統一成 400
        raise MaterialApprovalError(400, getattr(e, "detail", None) or str(e))
    if not day:
        raise MaterialApprovalError(400, "請填到貨日期")
    now = _now()
    conn.execute("UPDATE case_material_approvals SET received_on=?, received_by=?, received_at=?, updated_at=? WHERE quote_no=? AND item_id=?",
                 (day, user["username"], now, now, quote_no, str(item_id)))
    return {"receivedOn": day, "receivedBy": user["username"], "receivedAt": now}


def undo_receipt(conn, quote_no: str, item_id: str, user: dict) -> dict:
    row = get(conn, quote_no, item_id)
    if row is None or not row["received_on"]:
        raise MaterialApprovalError(409, "這筆材料申請沒有到貨確認")
    now = _now()
    conn.execute("UPDATE case_material_approvals SET received_on='', received_by='', received_at='', updated_at=? WHERE quote_no=? AND item_id=?",
                 (now, quote_no, str(item_id)))
    return {"undone": True, "was": {"receivedOn": row["received_on"], "receivedBy": row["received_by"]}}
