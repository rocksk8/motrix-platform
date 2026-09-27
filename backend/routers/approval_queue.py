"""「待我簽核」佇列（L1；主持裁示 2026-09-27：自 M01 搬進共用層，不列例外）。

路徑不變、前端不改：`GET /api/approval-queue`、`/count`、`/detail`、`POST /api/approval-queue/reassign`。
這裡只做彙整、可見性過濾、分組、角標計數、每案權限、案件抬頭與金額遮蔽；單據一律由擁有模組經串接點供應：
- `approval.queue_items`（IP-10）：待簽項目。M01（報價單、已結案變更、額外支出、額外支出變更、完工單）只是其中一個提供者。
- `approval.detail`（IP-93）：一筆的詳情。
- `approval.reassign`（IP-94）：轉簽時簽核鏈的讀寫。
案件資料（抬頭、項目缺的客戶／名稱）經 `case.summary`（IP-96）取；M01 不在 ⇒ 抬頭只有單號，其他模組的單照常列出。
形狀與共用邏輯見 `helpers/approval_queue.py`。
"""
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from core import registry
from core.txn import begin_write
from db import get_db
from helpers import _require_user, _tok, _audit, _notify, active_delegators_for, can_see_financial
from helpers.approval_queue import ApprovalUnreadable, active_tiers, current_tier_idx
from helpers.case_access import SYSTEM, guard_case_access, is_document_approver

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 彙整 ──────────────────────────────────────────────────────────────────────

def _queue_visible_to(user: dict, item: dict, delegated_for) -> bool:
    """這一筆待簽核文件該不該讓這個人看到（2026-09-15 使用者要求）。

    「簽核佇列除了管理員以上都只能看到自己的簽核佇列卡在哪邊」。所以非 admin 的
    可見範圍是兩種，其餘一律看不到：

    1. **自己送審的**——他要知道自己的單子卡在哪一關、卡在誰身上
    2. **簽核鏈裡有自己的**（含代理他人時的被代理人）——比對的是**所有層**而不是
       只有當前層：只比當前層的話，下一關才輪到的人看不到即將輪到自己的單，
       已經簽過的人也看不到後面卡住了，兩種都會讓人誤以為「沒我的事」

    為什麼過濾放在這裡、而且只有一份：單據類型由各模組提供，每種各寫一段 WHERE 條件的話，
    下一次新增類型時漏掉的那一種就是全開的——而「漏了會外洩」的規則必須是預設安全。
    集中成一條規則、套在組裝好的 items 上，新類型自動被蓋到。

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


def _case_names(conn, quote_nos) -> dict:
    """quote_no → case.summary 列（L1 以 `SYSTEM` 取；呼叫端已做完自己的權限判斷）。M01 不在 ⇒ {}。"""
    summary = registry.single_provider("case.summary")
    qs = sorted({q for q in quote_nos if q})
    if summary is None or not qs:
        return {}
    return {r["quote_no"]: r for r in summary(conn, SYSTEM, qs)}


def _queue_provider_items(conn) -> list:
    """IP-10 `approval.queue_items`：各單據模組提供自己的待簽項目。提供者壞掉只少那一類（記 exception）；
    模組不在 ⇒ 那一類不列。項目沒給 `customer`／`projectName` 而有 `linkedQuoteNo` ⇒ 這裡經 `case.summary` 補案件的
    客戶與名稱（M01 不在 ⇒ 空字串）。"""
    out = []
    for name, fn in sorted(registry.providers("approval.queue_items").items()):
        try:
            out.extend(fn(conn) or [])
        except Exception:                                    # noqa: BLE001
            logger.exception("待簽核佇列：提供者 %s 失敗（這一類不列出）", name)
    names = _case_names(conn, [it.get("linkedQuoteNo") for it in out
                               if it.get("linkedQuoteNo") and ("customer" not in it or "projectName" not in it)])
    for it in out:
        q = names.get(it.get("linkedQuoteNo"))
        it.setdefault("customer", (q["customer_name"] if q else "") or "")
        it.setdefault("projectName", (q["project_name"] if q else "") or "")
    return out


def _reassign_types() -> list:
    """可以轉簽的單據類型＝有 `approval.reassign` 提供者的（模組不在 ⇒ 不給轉簽，前端不顯示按鈕）。"""
    return sorted(registry.providers("approval.reassign"))


def _counts_for_me(item: dict, my_usernames: set, my_username: str, is_sa: bool) -> bool:
    """角標：這一筆是否「輪到我」。與佇列頁 `canApprove()` 一致：有簽核層 ⇒ 當層未簽的人裡有我（含代理）；
    沒有簽核層 ⇒ 任一 superadmin、自己送的不算（2026-09-15 修正：原本整批跳過，佇列列得出來而角標是 0；
    自己送的若算進來會變成按不下去的紅點）。"""
    tiers = item.get("tiers") or []
    if tiers:
        ct = item.get("currentTier") or 0
        if ct < len(tiers):
            return any(a.get("username") in my_usernames and a.get("status") != "approved"
                       for a in (tiers[ct].get("approvers") or []))
        return False
    return is_sa and (item.get("requestedBy") or "") != my_username


@router.get("/api/approval-queue")
def get_approval_queue(authorization: str = Header(None)):
    """待我簽核佇列：各模組提供的項目（IP-10）→ 可見性過濾 → 依送審人分組。

    欄位沿用報價單的名稱（quoteNo/customer/projectName/total/quoteDate/salesPerson）承載各類型資料，
    `type` 供前端分流動作按鈕與連結（見 approval-queue.html）。

    `myDelegatedFor`（2026-08-28）：目前使用者正在代理誰的簽核權限——前端 canApprove()/myPendingCount
    要一併比對，否則代理人看不到任何「輪到我」。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        my_delegated_for = sorted(active_delegators_for(conn, user["username"]))
        items = _queue_provider_items(conn)
    finally:
        conn.close()

    # 權限過濾（2026-09-15）：過濾在分組**之前**——分組之後才過濾會留下「某某人 0 件」的空群組。
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

    return {"queue": queue, "total": len(items), "myDelegatedFor": my_delegated_for,
            "reassignTypes": _reassign_types()}


@router.get("/api/approval-queue/count")
def get_approval_queue_count(authorization: str = Header(None)):
    """topbar 角標：輪到我簽核的項目數（含「我目前代理誰」，2026-08-28）。與佇列列表同一份來源
    （`_queue_provider_items`），兩邊才對得起來。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        my_usernames = {u["username"]} | set(active_delegators_for(conn, u["username"]))
        items = _queue_provider_items(conn)
    finally:
        conn.close()
    is_sa = u["role"] == "superadmin"
    return {"count": sum(1 for it in items if _counts_for_me(it, my_usernames, u["username"], is_sa))}
