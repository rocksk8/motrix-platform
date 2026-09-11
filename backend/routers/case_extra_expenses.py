"""案件額外支出（`case_extra_expenses` 表）——CRUD ＋ 送審（2026-09-11）。

使用者交辦的額外支出改版第二段，規格與六個設計問題的答案見
`MOTRIX-ERP-QUICK.md` §5.10。第一段（migration v75）已經把資料從
`quotations.data_json` 的 `settlement.extraItems[]` 搬進獨立資料表。

**這一支取代的是什麼**：先前額外支出只能在精算頁那張表編輯，沒有任何送審機制，
存檔就生效；填寫人欄位因為前端取錯 session 路徑，實測 7 筆既有資料 0 筆有值。

**狀態機**

    草稿 ──submit──▶ 待審核 ──(分層簽核)──▶ 簽核中 ──▶ 已核准
      ▲                                                │
      └──────────── 已駁回 ◀──reject────────────────────┘
    （已駁回可以再編輯、再送審；已核准要改只能請最高管理員處理）

**權限**（跟這個專案既有的作法一致）

- 一律先過 `_check_quotation_owner()`：`quote_no` 可列舉，不擋就是 IDOR
- 建立：任何看得到這張案件的人都可以填（實際花錢的人通常不是管理員）
- 編輯／刪除／送審：**填寫人本人或 admin+**（別人填的不該被隨手改掉）
- 核准／駁回：純粹依「是否為當層簽核人員」判斷，**不額外要求 admin 角色**
  ——比照 `quotations.py`／`invoice_vouchers.py`，簽核設定頁允許把任何角色加進
  簽核人清單，這裡硬擋 admin 會讓非管理員簽核人永遠卡死

**已結案案件照樣可以編**（使用者指定的第 5 點），所以刻意不呼叫
`_deny_if_case_locked_unsupported()`。

**通知**：v1 只發站內通知（`_notify`）與模組動態（`notify_module_activity`），
不另外做這個類型專屬的 email 樣板——四種現有單據各有一組 `notify_xxx_submitted`
之類的函式，額外支出要不要走到那個程度可以之後看實際使用頻率再決定。
"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel

from db import get_db
from helpers import (
    _require_user, _tok, _audit, _notify, _check_quotation_owner,
    notify_module_activity,
    active_tiers as _active_tiers, current_tier_idx as _current_tier_idx,
    setting_to_active_tiers as _setting_to_active_tiers,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    UnresolvedManagerError, resolve_active_flow_setting,
)

router = APIRouter()

# 可編輯／可刪除的狀態。送審中或已核准的不給改——改了簽核就失去意義
EDITABLE_STATUSES = ("草稿", "已駁回")

CATEGORIES = ["工時", "材料", "差旅", "運費", "安裝", "外包", "其他"]


class ExtraExpenseIn(BaseModel):
    """建立／編輯用。填寫人與時間戳一律由後端決定，不吃前端傳的值。"""
    category:    str = "其他"
    description: str = ""
    qty:         float = 1
    unit:        str = ""
    unitCost:    float = 0
    note:        str = ""
    expenseDate: str = ""
    docNo:       str = ""
    # 支出人：使用者指定「可選可自由文字」。從清單選時兩個都有值，
    # 自由文字時只有 payerName——所以統計時要以 payerName 為顯示、
    # payerUsername 有值才做得了「某人代墊多少」這類彙總
    payerUsername: str = ""
    payerName:     str = ""


def _row_to_dict(r) -> dict:
    try:
        files = json.loads(r["files_json"] or "[]")
    except Exception:
        files = []
    try:
        approval = json.loads(r["approval_json"] or "{}")
    except Exception:
        approval = {}
    return {
        "id":          r["id"],
        "category":    r["category"],
        "description": r["description"],
        "qty":         r["qty"],
        "unit":        r["unit"],
        "unitCost":    r["unit_cost"],
        "totalCost":   r["total_cost"],
        "note":        r["note"],
        "expenseDate": r["expense_date"],
        "docNo":       r["doc_no"],
        "files":       files,
        "createdBy":       r["created_by"],
        "createdByName":   r["created_by_name"],
        # 既有資料的填寫人是推定回填的，不是真的知道是誰——畫面要標「（推定）」，
        # 不要讓人把推定值當成事實（見 db.py::_m075 docstring）
        "createdByInferred": bool(r["created_by_inferred"]),
        "payerUsername": r["payer_username"],
        "payerName":     r["payer_name"],
        "createdAt":     r["created_at"],
        "updatedAt":     r["updated_at"],
        "updatedByName": r["updated_by_name"],
        "status":        r["status"],
        "approval":      approval,
    }


def _load(conn, quote_no: str, exp_id: int):
    row = conn.execute(
        "SELECT * FROM case_extra_expenses WHERE id=? AND quote_no=?", (exp_id, quote_no)
    ).fetchone()
    if not row:
        raise HTTPException(404, "找不到這筆額外支出")
    return row


def _guard_case(conn, quote_no: str, user: dict):
    """報價單存在＋擁有者檢查。`quote_no` 可列舉，不擋就是 IDOR。"""
    q = conn.execute(
        "SELECT sales_person_id, sales_person, assigned_user_ids FROM quotations WHERE quote_no=?",
        (quote_no,)
    ).fetchone()
    if not q:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    _check_quotation_owner(q, user)


def _can_modify(row, user: dict) -> bool:
    """填寫人本人或 admin+ 才能改。別人填的支出不該被隨手改掉。"""
    if user["role"] in ("superadmin", "admin"):
        return True
    return bool(row["created_by"]) and row["created_by"] == user["username"]


def _recalc(body: ExtraExpenseIn) -> float:
    """小計一律後端算。前端也會算一份給即時顯示，但不吃它傳的值——
    比照叫料端點的作法，金額欄位不接受客戶端計算結果。"""
    qty = max(0.0, float(body.qty or 0))
    unit_cost = max(0.0, float(body.unitCost or 0))
    return round(qty * unit_cost, 2)


def _validate(body: ExtraExpenseIn):
    if body.category and body.category not in CATEGORIES:
        raise HTTPException(400, f"類別必須是：{'／'.join(CATEGORIES)}")
    if float(body.qty or 0) < 0 or float(body.unitCost or 0) < 0:
        raise HTTPException(400, "數量與單位成本不能為負")
    if not (body.description or "").strip():
        raise HTTPException(400, "請填寫品項說明")


@router.get("/api/quotations/{quote_no}/extra-expenses")
def list_extra_expenses(quote_no: str, authorization: str = Header(None)):
    """列出一張案件的額外支出，附三個合計。

    權限比照同一份資料的既有端點：只要求登入＋擁有者檢查。`totalPending` 是
    **送審中但仍計入成本**的金額——使用者指定送審中的照樣算進成本，但畫面要提醒
    還沒簽完，所以這裡把它單獨算出來給前端做提示，不是從總額裡扣掉。
    """
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        rows = conn.execute(
            "SELECT * FROM case_extra_expenses WHERE quote_no=? ORDER BY id", (quote_no,)
        ).fetchall()
        items = [_row_to_dict(r) for r in rows]
        total = sum(float(i["totalCost"] or 0) for i in items)
        pending = sum(float(i["totalCost"] or 0) for i in items if i["status"] != "已核准")
        return {
            "quoteNo": quote_no,
            "items": items,
            "totalAmount": total,
            "totalPending": pending,
            "pendingCount": sum(1 for i in items if i["status"] not in ("已核准", "草稿")),
            "categories": CATEGORIES,
        }
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses", status_code=201)
def create_extra_expense(quote_no: str, body: ExtraExpenseIn = Body(...),
                         authorization: str = Header(None)):
    """新增一筆（草稿）。填寫人與填寫日期由後端帶入，不吃前端傳的值。

    ⚠️ 這裡是整個改版的起點之一：舊的精算表單把填寫人交給前端填，而前端取的是
    一個不存在的 session 路徑，結果實測 7 筆既有資料 0 筆有值。所以現在改成
    後端決定——前端傳什麼都不採用。
    """
    user = _require_user(authorization)
    _validate(body)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        now = datetime.now().isoformat(timespec="seconds")
        total = _recalc(body)
        display = user.get("display_name") or user["username"]
        cur = conn.execute(
            "INSERT INTO case_extra_expenses "
            "(quote_no, category, description, qty, unit, unit_cost, total_cost, note, "
            " expense_date, doc_no, files_json, created_by, created_by_name, created_by_inferred, "
            " payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,'草稿','{}')",
            (quote_no, body.category or "其他", (body.description or "").strip(),
             float(body.qty or 0), (body.unit or "").strip(), float(body.unitCost or 0), total,
             (body.note or "").strip(), (body.expenseDate or "").strip(), (body.docNo or "").strip(),
             user["username"], display,
             (body.payerUsername or "").strip(), (body.payerName or "").strip(),
             now, now, display),
        )
        conn.commit()
        exp_id = cur.lastrowid
        _audit(_tok(authorization), "extra_expense.create", "quotation", quote_no,
               f"{quote_no} 新增額外支出「{(body.description or '').strip()}」 NT$ {total:,.0f}")
        return {"ok": True, "id": exp_id, "status": "草稿", "totalCost": total}
    finally:
        conn.close()


@router.patch("/api/quotations/{quote_no}/extra-expenses/{exp_id}")
def update_extra_expense(quote_no: str, exp_id: int, body: ExtraExpenseIn = Body(...),
                         authorization: str = Header(None)):
    """編輯（僅草稿／已駁回）。會更新「更動日期」與「最後更動人」。"""
    user = _require_user(authorization)
    _validate(body)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        if row["status"] not in EDITABLE_STATUSES:
            raise HTTPException(409, f"「{row['status']}」狀態不可編輯（僅草稿與已駁回可改）")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以修改這筆額外支出")

        now = datetime.now().isoformat(timespec="seconds")
        total = _recalc(body)
        conn.execute(
            "UPDATE case_extra_expenses SET category=?, description=?, qty=?, unit=?, "
            " unit_cost=?, total_cost=?, note=?, expense_date=?, doc_no=?, "
            " payer_username=?, payer_name=?, updated_at=?, updated_by_name=? "
            "WHERE id=? AND quote_no=?",
            (body.category or "其他", (body.description or "").strip(), float(body.qty or 0),
             (body.unit or "").strip(), float(body.unitCost or 0), total,
             (body.note or "").strip(), (body.expenseDate or "").strip(), (body.docNo or "").strip(),
             (body.payerUsername or "").strip(), (body.payerName or "").strip(),
             now, user.get("display_name") or user["username"], exp_id, quote_no),
        )
        conn.commit()
        _audit(_tok(authorization), "extra_expense.update", "quotation", quote_no,
               f"{quote_no} 修改額外支出 #{exp_id}「{(body.description or '').strip()}」 NT$ {total:,.0f}")
        return {"ok": True, "totalCost": total, "updatedAt": now}
    finally:
        conn.close()


@router.delete("/api/quotations/{quote_no}/extra-expenses/{exp_id}")
def delete_extra_expense(quote_no: str, exp_id: int, authorization: str = Header(None)):
    """刪除（僅草稿／已駁回）。已核准的要移除只能請最高管理員從資料庫處理——
    已經計入成本與報表的數字不該被單方面刪掉。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        if row["status"] not in EDITABLE_STATUSES:
            raise HTTPException(409, f"「{row['status']}」狀態不可刪除（僅草稿與已駁回可刪）")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以刪除這筆額外支出")
        conn.execute("DELETE FROM case_extra_expenses WHERE id=? AND quote_no=?", (exp_id, quote_no))
        conn.commit()
        _audit(_tok(authorization), "extra_expense.delete", "quotation", quote_no,
               f"{quote_no} 刪除額外支出 #{exp_id}「{row['description']}」")
        return {"ok": True}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/submit")
def submit_extra_expense(quote_no: str, exp_id: int, authorization: str = Header(None)):
    """送審。走 `helpers/tiered_approval.py` 的分層簽核，跟其他五種單據同一套。

    使用者要的是「共用分層簽核並可獨立設定」——`extra_expense` 已列進
    `APPROVAL_DOC_TYPES` 且預設在 `DEFAULT_UNIFIED_DOC_TYPES` 裡，所以預設跟著
    統一流程走；要獨立的話在簽核設定頁把它從套用範圍取消勾選即可。

    **沒有設定任何簽核層時直接視為已核准**：這個專案的簽核設定是選配的，
    若因為沒設定就把單據永久卡在「待審核」，等於新功能一上線就把所有人擋住。
    """
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        if row["status"] not in EDITABLE_STATUSES:
            raise HTTPException(409, f"「{row['status']}」狀態不可送審")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以送審這筆額外支出")

        flow_setting = resolve_active_flow_setting("extra_expense")
        try:
            tiers = _setting_to_active_tiers(flow_setting, conn, user["username"])
        except UnresolvedManagerError as e:
            raise HTTPException(400, str(e))

        now = datetime.now().isoformat(timespec="seconds")
        label = f"{row['description']}（NT$ {float(row['total_cost'] or 0):,.0f}）"

        if not tiers:
            conn.execute(
                "UPDATE case_extra_expenses SET status='已核准', updated_at=?, approval_json=? "
                "WHERE id=? AND quote_no=?",
                (now, json.dumps({"autoApproved": True,
                                  "note": "未設定任何簽核層，送審即視為核准"},
                                 ensure_ascii=False), exp_id, quote_no),
            )
            conn.commit()
            _audit(_tok(authorization), "extra_expense.auto_approve", "quotation", quote_no,
                   f"{quote_no} 額外支出 #{exp_id} {label}：未設定簽核層，直接核准")
            return {"ok": True, "status": "已核准", "autoApproved": True}

        approval = {
            "requestedBy":        user["username"],
            "requestedByDisplay": user.get("display_name") or user["username"],
            "requestedAt":        now,
            "tiers":              tiers,
            "currentTier":        0,
        }
        conn.execute(
            "UPDATE case_extra_expenses SET status='待審核', updated_at=?, approval_json=? "
            "WHERE id=? AND quote_no=?",
            (now, json.dumps(approval, ensure_ascii=False), exp_id, quote_no),
        )
        conn.commit()

        for a in (tiers[0].get("approvers") or []):
            _notify(a["username"], "extra_expense_approval_request", str(exp_id), quote_no,
                    f"案件 {quote_no} 的額外支出 {label} 需要您簽核")
        _audit(_tok(authorization), "extra_expense.submit", "quotation", quote_no,
               f"{quote_no} 額外支出 #{exp_id} {label} 送審", {"tierCount": len(tiers)})
        return {"ok": True, "status": "待審核", "tierCount": len(tiers)}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/approve")
def approve_extra_expense(quote_no: str, exp_id: int, body: dict = Body(default={}),
                          authorization: str = Header(None)):
    """核准當層。全部層都過了才變「已核准」。

    能不能簽核完全由「是否為當層簽核人員」決定，不額外要求 admin 角色
    ——比照 `quotations.py`／`invoice_vouchers.py`，簽核設定頁允許把任何角色
    加進簽核人清單，這裡硬擋 admin 會讓非管理員簽核人永遠卡死。
    """
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        if row["status"] not in ("待審核", "簽核中"):
            raise HTTPException(409, f"「{row['status']}」狀態不在簽核中")

        appr = json.loads(row["approval_json"] or "{}")
        tiers = _active_tiers(appr)
        ct = _current_tier_idx(appr)
        err = check_no_tier_self_approval(conn, appr, user)
        if err:
            raise HTTPException(403, err)
        check_approve_permission(tiers, ct, user["username"], conn)

        now = datetime.now().isoformat(timespec="seconds")
        display = user.get("display_name") or user["username"]
        for a in (tiers[ct].get("approvers") or []):
            if a.get("username") == user["username"] or not a.get("approvedAt"):
                a["approvedAt"] = now
                a["approvedByDisplay"] = display
                break

        # 這一層是否已滿足（沿用既有單據的「當層任一人簽即通過」語意）
        appr["tiers"] = tiers
        appr["currentTier"] = ct + 1
        done = appr["currentTier"] >= len(tiers)
        status = "已核准" if done else "簽核中"
        appr.setdefault("history", []).append(
            {"at": now, "by": user["username"], "byDisplay": display,
             "action": "approve", "tier": ct, "comment": (body or {}).get("comment") or ""})

        conn.execute(
            "UPDATE case_extra_expenses SET status=?, updated_at=?, approval_json=? "
            "WHERE id=? AND quote_no=?",
            (status, now, json.dumps(appr, ensure_ascii=False), exp_id, quote_no),
        )
        conn.commit()

        label = f"{row['description']}（NT$ {float(row['total_cost'] or 0):,.0f}）"
        if not done:
            for a in (tiers[appr["currentTier"]].get("approvers") or []):
                _notify(a["username"], "extra_expense_approval_request", str(exp_id), quote_no,
                        f"案件 {quote_no} 的額外支出 {label} 需要您簽核")
        else:
            requester = appr.get("requestedBy")
            if requester:
                _notify(requester, "extra_expense_approved", str(exp_id), quote_no,
                        f"案件 {quote_no} 的額外支出 {label} 已核准")
            notify_module_activity("案件管理", "額外支出核准", display, f"{quote_no}｜{label}",
                                   f"case-management.html?q={quote_no}")
        _audit(_tok(authorization), "extra_expense.approve", "quotation", quote_no,
               f"{quote_no} 額外支出 #{exp_id} {label} 第 {ct + 1} 層核准 → {status}")
        return {"ok": True, "status": status, "currentTier": appr["currentTier"]}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/reject")
def reject_extra_expense(quote_no: str, exp_id: int, body: dict = Body(default={}),
                         authorization: str = Header(None)):
    """駁回 → 回到「已駁回」，填寫人可以改完再送一次。

    刻意不是直接刪掉：駁回通常是「金額或說明要修」，不是「這筆支出不存在」。
    """
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        if row["status"] not in ("待審核", "簽核中"):
            raise HTTPException(409, f"「{row['status']}」狀態不在簽核中")

        appr = json.loads(row["approval_json"] or "{}")
        tiers = _active_tiers(appr)
        ct = _current_tier_idx(appr)
        check_reject_permission(tiers, ct, user, conn)

        now = datetime.now().isoformat(timespec="seconds")
        display = user.get("display_name") or user["username"]
        reason = ((body or {}).get("reason") or "").strip()
        appr.setdefault("history", []).append(
            {"at": now, "by": user["username"], "byDisplay": display,
             "action": "reject", "tier": ct, "comment": reason})
        appr["rejectedAt"] = now
        appr["rejectedByDisplay"] = display
        appr["rejectReason"] = reason

        conn.execute(
            "UPDATE case_extra_expenses SET status='已駁回', updated_at=?, approval_json=? "
            "WHERE id=? AND quote_no=?",
            (now, json.dumps(appr, ensure_ascii=False), exp_id, quote_no),
        )
        conn.commit()

        label = f"{row['description']}（NT$ {float(row['total_cost'] or 0):,.0f}）"
        requester = appr.get("requestedBy")
        if requester:
            _notify(requester, "extra_expense_rejected", str(exp_id), quote_no,
                    f"案件 {quote_no} 的額外支出 {label} 已被駁回"
                    + (f"：{reason}" if reason else ""))
        _audit(_tok(authorization), "extra_expense.reject", "quotation", quote_no,
               f"{quote_no} 額外支出 #{exp_id} {label} 被駁回" + (f"：{reason}" if reason else ""))
        return {"ok": True, "status": "已駁回"}
    finally:
        conn.close()
