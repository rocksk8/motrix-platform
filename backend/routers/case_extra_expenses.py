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

- 一律先過 `row_access.require("case", …)`：`quote_no` 可列舉，不擋就是 IDOR
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
from typing import List

from fastapi import APIRouter, Body, File, Header, HTTPException, UploadFile
from pydantic import BaseModel

from db import get_db
from helpers import row_access
from helpers.case_access import case_owner_readable   # AT-M1b：與附件提供者同一支
from helpers.auth import user_has_module
from helpers.recognition import normalize_date  # `AC2`
# X-VAT（2026-09-26）：金額一律四捨五入（內建 round() 是銀行家捨入：.5 取偶數）
from helpers.legal_params import round_half_up
from helpers import (
    _require_user, _tok, _audit, _notify,
    can_see_financial, is_document_approver,
    notify_module_activity,
    active_tiers as _active_tiers, current_tier_idx as _current_tier_idx,
    setting_to_active_tiers as _setting_to_active_tiers,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    notify_org_chain_notice,
    UnresolvedManagerError, resolve_active_flow_setting,
    save_document_files, delete_document_file,
)
from helpers.tiered_approval import cascade_self_tiers, sign_first_pending  # noqa: E402（helpers/__init__ 鎖定，直接取）

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
        # `AC2`：廠商發票日期／付款日（''＝未登錄）；權責口徑依發票日、現金口徑依付款日
        "invoiceDate": _col(r, "invoice_date", "") or "",
        "paidDate":    _col(r, "paid_date", "") or "",
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
        # 變更申請（DB v76）——已核准之後的編輯走這條，核准才生效，見本檔末段
        "changeStatus":   _col(r, "change_status", ""),
        "change":         _jcol(r, "change_json"),
        "changeApproval": _jcol(r, "change_approval_json"),
    }


def _col(r, name, default=None):
    """sqlite3.Row 取欄位，欄位不存在時回 default（migration 還沒跑到的保險）。"""
    try:
        return r[name]
    except (IndexError, KeyError):
        return default


def _jcol(r, name) -> dict:
    try:
        return json.loads(_col(r, name) or "{}")
    except Exception:
        return {}


def _load(conn, quote_no: str, exp_id: int):
    row = conn.execute(
        "SELECT * FROM case_extra_expenses WHERE id=? AND quote_no=?", (exp_id, quote_no)
    ).fetchone()
    if not row:
        raise HTTPException(404, "找不到這筆額外支出")
    return row


def _guard_case(conn, quote_no: str, user: dict):
    """報價單存在＋擁有者檢查。`quote_no` 可列舉，不擋就是 IDOR。
    准不准只看 L1 `case_owner_readable`（附件提供者用同一支，稽核 D AT-M1b）；這裡只負責說出原因。"""
    q = conn.execute(
        "SELECT sales_person_id, sales_person, assigned_user_ids FROM quotations WHERE quote_no=?",
        (quote_no,)
    ).fetchone()
    if not q:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    if not case_owner_readable(conn, quote_no, user):
        row_access.require("case", user, q)
        raise HTTPException(403, "無權限存取這筆資料")


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
    return round_half_up(qty * unit_cost, 100) / 100   # 元以下兩位（分）四捨五入


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
        # 2026-09-13（模組權限稽核）：額外支出是成本金額，套用與精算相同的
        # 「財務金額可視」規則（使用者裁示：viewer／engineer 不該看到）。
        # **兩個例外**，否則這個功能的兩種主角會被自己的權限鎖死：
        #   ①自己填的那幾筆——現場花錢的人本來就該看得到自己報的帳
        #   ②這張單的簽核人——看不到金額就沒辦法判斷該不該簽
        # 合計同步只算看得到的那幾筆，避免「清單 3 筆、合計卻是 8 筆的金額」
        # 這種更難解釋的畫面。
        if not can_see_financial(user):
            rows = [r for r in rows
                    if (r["created_by"] or "") == user["username"]
                    or is_document_approver(_col(r, "approval_json", ""), user, conn)]
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


@router.patch("/api/quotations/{quote_no}/extra-expenses/{exp_id}/dates")
def set_extra_expense_dates(quote_no: str, exp_id: int, body: dict = Body(...),
                            authorization: str = Header(None)):
    """`AC2`：登錄廠商發票日期／付款日（只改有給的鍵；''＝清除）。**任何狀態都可以登**——

    兩個日期都不影響金額，只決定報表歸哪個月；已核准的支出正是最常事後才拿到發票、
    才付款的那一批，走變更申請會讓財務補登卡在簽核上（hichan-0a 裁示）。
    權限：填寫人本人、admin+，或出納（付款是出納登的）。
    """
    user = _require_user(authorization)
    body = body or {}
    changes = {}
    if "invoiceDate" in body:
        changes["invoice_date"] = normalize_date(body.get("invoiceDate"), "發票日期")
    if "paidDate" in body:
        changes["paid_date"] = normalize_date(body.get("paidDate"), "付款日")
    if not changes:
        raise HTTPException(400, "沒有要登錄的日期")
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        if not (_can_modify(row, user) or user_has_module(user, "cashier")):
            raise HTTPException(403, "只有填寫人本人、管理員或出納可以登錄這筆額外支出的日期")
        now = datetime.now().isoformat(timespec="seconds")
        sets = ", ".join("%s=?" % k for k in changes)
        conn.execute("UPDATE case_extra_expenses SET " + sets + ", updated_at=?, updated_by_name=?"
                     " WHERE id=? AND quote_no=?",
                     list(changes.values()) + [now, user.get("display_name") or user["username"], exp_id, quote_no])
        conn.commit()
    finally:
        conn.close()
    label = {"invoice_date": "發票日期", "paid_date": "付款日"}
    _audit(_tok(authorization), "extra_expense.dates", "quotation", quote_no,
           "%s 額外支出 #%s 登錄%s" % (quote_no, exp_id, "、".join(
               "%s %s" % (label[k], v or "（清除）") for k, v in changes.items())))
    return {"ok": True, "updatedAt": now,
            **{("invoiceDate" if k == "invoice_date" else "paidDate"): v for k, v in changes.items()}}


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
        # 知會（2026-09-15）：整條簽核鏈都只有申請人本人時（他已在組織職權頂端），
        # 最高管理者不再被塞進簽核鏈，改收一則知會通知（仍可隨時以 superadmin 退回）。
        notify_org_chain_notice(conn, tiers, user["username"], str(exp_id), quote_no,
                                f"案件 {quote_no} 的額外支出 {label} 由 "
                                f"{user.get('display_name') or user['username']} 依組織職權自行簽核，知會您",
                                type_="extra_expense_approval_notice")
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
        # ⚠️ 2026-09-15 修正兩件事：
        # ① `check_approve_permission()` 的回傳值原本**整個被丟掉**（其他 router 都是
        #    `ok, code, msg = ...` 再 raise），等於這支端點的當層簽核人檢查形同虛設，
        #    任何過得了 _guard_case() 的人都簽得掉任何一層。
        # ② `check_no_tier_self_approval()` 原本無條件套用，但它是「沒有簽核層設定」
        #    時的 fallback 規則（其他 router 都只在 no-tier 分支呼叫）。有簽核層時
        #    照樣擋，會讓 2026-09-15 起組織流程算出「申請人本人就是該層主管」的
        #    自簽層永遠簽不掉。
        if tiers:
            ok, status_code, err_msg = check_approve_permission(tiers, ct, user["username"], conn)
            if not ok:
                raise HTTPException(status_code, err_msg)
        else:
            err = check_no_tier_self_approval(conn, appr, user)
            if err:
                raise HTTPException(403, err)

        now = datetime.now().isoformat(timespec="seconds")
        display = user.get("display_name") or user["username"]
        # 2026-09-25 使用者裁示：同層每一位都要依序簽完才過層（與共用規則、獎金分潤一致）。
        # ☠️ 原本寫法只寫 approvedAt、不寫 status，且第一位一簽就換層 ⇒ 同層第二位以後永遠沒機會簽，
        #    而讀 status 的地方把已簽的格子一律當成未簽。
        tier_done = sign_first_pending(tiers[ct], user, now, conn=conn) if tiers else True
        # 同一人連任多層時一次簽完（2026-09-15）：前端確認過才會帶 cascade=true；
        # 只吃「剩下未簽的全是他（或他代理的人）」的連續層，不替同層的別人簽。
        cascaded = (cascade_self_tiers(tiers, ct, user["username"], now, conn=conn)
                    if (tiers and tier_done and (body or {}).get("cascade")) else [])

        appr["tiers"] = tiers
        appr["currentTier"] = (ct + 1 + len(cascaded)) if tier_done else ct
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
        # 2026-09-24：回傳值原本被丟掉（approve 側 09-15 已修同型），任何過得了
        # _guard_case() 的人都駁回得了任何一層。
        ok, status_code, err_msg = check_reject_permission(tiers, ct, user, conn)
        if not ok:
            raise HTTPException(status_code, err_msg)

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


# ── 發票／收據附件 ────────────────────────────────────────────────────────────
#
# 取代舊的 `/api/quotations/{no}/settlement/extra/{idx}/files`——那組是用**陣列索引**
# 定位的，額外支出一旦新增/刪除/重排，索引就會指到別筆去。改成用資料列的 id，
# 這也是把資料正規化出來的好處之一。
#
# ⚠️ **2026-09-11 行為變更（使用者交辦）**：已核准之後**附件一併上鎖**，不能再上傳
# 或刪除。原本刻意開放（「補傳憑證是會計常態」）的設計被推翻了——理由是核准當下
# 簽核人看到的憑證，跟事後被換掉的憑證不是同一份，等於簽核簽了個會變的東西。
# 要在核准後補憑證，改走下面的「變更申請」：新檔案先存成待核准附件，簽核通過的
# 那一刻才併進正式附件清單（`_apply_change()`）。

def _files_of(row) -> list:
    try:
        return json.loads(row["files_json"] or "[]")
    except Exception:
        return []


def _guard_files_editable(row):
    """附件是否還能動。已核准就一律擋，訊息要明確指向變更申請這條路——
    只回一句「不可修改」的話，使用者只會以為系統壞了。"""
    if row["status"] == "已核准":
        raise HTTPException(
            409, "這筆額外支出已核准，附件已上鎖。要補憑證請按「編輯」提出變更申請，"
                 "新附件會在簽核通過後一併生效")


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/files", status_code=201)
async def upload_extra_expense_files(quote_no: str, exp_id: int,
                                     files: List[UploadFile] = File(...),
                                     authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        _guard_files_editable(row)
        new_files = await save_document_files(
            "case_extra_expense", f"{quote_no}_{exp_id}", files,
            user.get("display_name") or user["username"])
        merged = _files_of(row) + new_files
        conn.execute(
            "UPDATE case_extra_expenses SET files_json=?, updated_at=?, updated_by_name=? "
            "WHERE id=? AND quote_no=?",
            (json.dumps(merged, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds"),
             user.get("display_name") or user["username"], exp_id, quote_no),
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "extra_expense.upload_files", "quotation", quote_no,
           f"{quote_no} 額外支出 #{exp_id} 上傳 {len(new_files)} 個附件")
    return {"ok": True, "added": len(new_files), "files": new_files}


@router.delete("/api/quotations/{quote_no}/extra-expenses/{exp_id}/files/{file_id}")
def delete_extra_expense_file(quote_no: str, exp_id: int, file_id: str,
                              authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        _guard_files_editable(row)
        remaining = delete_document_file(
            "case_extra_expense", f"{quote_no}_{exp_id}", _files_of(row), file_id)
        conn.execute(
            "UPDATE case_extra_expenses SET files_json=?, updated_at=?, updated_by_name=? "
            "WHERE id=? AND quote_no=?",
            (json.dumps(remaining, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds"),
             user.get("display_name") or user["username"], exp_id, quote_no),
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "extra_expense.delete_file", "quotation", quote_no,
           f"{quote_no} 額外支出 #{exp_id} 刪除附件")
    return {"ok": True}


# ── 變更申請：已核准之後的編輯 ────────────────────────────────────────────────
#
# 使用者交辦（2026-09-11 第二輪）：「額外支出上傳照片功能已核准要上鎖，增加編輯
# 按鈕，編輯需要審核。」並明確指定**原核准金額不動，核准後才生效**。
#
# 所以這裡刻意**不是**「把狀態退回草稿再改」——那樣做的話，人一按編輯，報表上的
# 成本當場就變了，簽核變成事後追認。改成：提議的新內容存在 `change_json`，本體
# 的 `status`／金額完全不動，簽核通過的那一刻才由 `_apply_change()` 覆蓋回去。
#
# **狀態機**（`change_status`，跟本體的 `status` 是兩條獨立的線）
#
#     （無）──存草稿──▶ 草稿 ──submit──▶ 待審核 ──▶ 簽核中 ──approve──▶ 套用並清空
#                        ▲                              │
#                        └────── 已駁回 ◀────reject──────┘
#
# 附件：新檔案在草稿階段就實際落地（存在同一個文件資料夾），但只記在
# `change_json.addFiles`，**不進 `files_json`**，所以核准前不會出現在正式附件清單、
# 也不會被結案報表撈到。撤銷或駁回後撤銷時，實體檔案一併刪掉，不留孤兒檔。
#
# 刻意**不支援**「刪除已核准的既有附件」：已經被簽核人看過、已計入成本的憑證不該
# 被單方面移除，語意跟「已核准的項目不可刪除」一致（要移除請找最高管理員）。

CHANGE_EDITABLE = ("", "草稿", "已駁回")


def _change_of(row) -> dict:
    return _jcol(row, "change_json")


def _proposal_from(body: ExtraExpenseIn, keep_files: list) -> dict:
    """把送進來的欄位組成提議內容。金額一律後端算（同 `_recalc()` 的理由）。"""
    return {
        "category":      body.category or "其他",
        "description":   (body.description or "").strip(),
        "qty":           float(body.qty or 0),
        "unit":          (body.unit or "").strip(),
        "unitCost":      float(body.unitCost or 0),
        "totalCost":     _recalc(body),
        "note":          (body.note or "").strip(),
        "expenseDate":   (body.expenseDate or "").strip(),
        "docNo":         (body.docNo or "").strip(),
        "payerUsername": (body.payerUsername or "").strip(),
        "payerName":     (body.payerName or "").strip(),
        "addFiles":      keep_files,
    }


def _clear_change(conn, quote_no: str, exp_id: int):
    conn.execute(
        "UPDATE case_extra_expenses SET change_status='', change_json='{}', "
        "change_approval_json='{}' WHERE id=? AND quote_no=?", (exp_id, quote_no))


def _discard_pending_files(quote_no: str, exp_id: int, change: dict):
    """撤銷／駁回後撤銷時刪掉待核准附件的實體檔案。失敗不擋流程——留一個孤兒檔
    比讓使用者撤銷不掉好。"""
    files = change.get("addFiles") or []
    for f in list(files):
        try:
            delete_document_file("case_extra_expense", f"{quote_no}_{exp_id}", files, f.get("id"))
        except Exception:
            pass


def _apply_change(conn, row, change: dict, actor_display: str, now: str) -> float:
    """把核准通過的提議內容覆蓋回本體，並把待核准附件併進正式附件清單。

    原核准紀錄留在 `approval_json`，這次變更的前後值 append 進
    `approval_json.changeHistory`——查帳要看的是「這筆從多少改成多少、誰核准的」，
    把 approval_json 整個換掉就查不到了。"""
    exp_id, quote_no = row["id"], row["quote_no"]
    total = round_half_up(max(0.0, float(change.get("qty") or 0)) *
                          max(0.0, float(change.get("unitCost") or 0)), 100) / 100
    merged_files = _files_of(row) + (change.get("addFiles") or [])

    appr = _jcol(row, "approval_json")
    appr.setdefault("changeHistory", []).append({
        "at": now, "byDisplay": actor_display,
        "requestedByDisplay": change.get("requestedByDisplay") or "",
        "from": {"description": row["description"], "totalCost": row["total_cost"],
                 "qty": row["qty"], "unitCost": row["unit_cost"],
                 "category": row["category"], "expenseDate": row["expense_date"],
                 "docNo": row["doc_no"], "note": row["note"],
                 "payerName": row["payer_name"]},
        "to":   {"description": change.get("description"), "totalCost": total,
                 "qty": change.get("qty"), "unitCost": change.get("unitCost"),
                 "category": change.get("category"), "expenseDate": change.get("expenseDate"),
                 "docNo": change.get("docNo"), "note": change.get("note"),
                 "payerName": change.get("payerName")},
        "addedFiles": [f.get("filename") for f in (change.get("addFiles") or [])],
    })

    conn.execute(
        "UPDATE case_extra_expenses SET category=?, description=?, qty=?, unit=?, "
        " unit_cost=?, total_cost=?, note=?, expense_date=?, doc_no=?, "
        " payer_username=?, payer_name=?, files_json=?, updated_at=?, updated_by_name=?, "
        " approval_json=?, change_status='', change_json='{}', change_approval_json='{}' "
        "WHERE id=? AND quote_no=?",
        (change.get("category") or "其他", change.get("description") or "",
         float(change.get("qty") or 0), change.get("unit") or "",
         float(change.get("unitCost") or 0), total, change.get("note") or "",
         change.get("expenseDate") or "", change.get("docNo") or "",
         change.get("payerUsername") or "", change.get("payerName") or "",
         json.dumps(merged_files, ensure_ascii=False), now, actor_display,
         json.dumps(appr, ensure_ascii=False), exp_id, quote_no),
    )
    return total


@router.put("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request")
def upsert_change_request(quote_no: str, exp_id: int, body: ExtraExpenseIn = Body(...),
                          authorization: str = Header(None)):
    """建立／更新變更申請草稿。只有**已核准**的項目才走這條；草稿與已駁回本來就
    可以直接編輯（`update_extra_expense()`），不需要繞一圈。"""
    user = _require_user(authorization)
    _validate(body)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        if row["status"] != "已核准":
            raise HTTPException(409, f"「{row['status']}」狀態請直接編輯，不需要提變更申請")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以提出變更申請")
        cs = _col(row, "change_status", "") or ""
        if cs not in CHANGE_EDITABLE:
            raise HTTPException(409, f"已有一筆變更申請在「{cs}」，請先完成或撤銷它")

        # 已駁回後再修改：沿用同一批待核准附件，不要讓使用者重傳一次
        proposal = _proposal_from(body, (_change_of(row).get("addFiles") or []))
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "UPDATE case_extra_expenses SET change_status='草稿', change_json=?, "
            "change_approval_json='{}' WHERE id=? AND quote_no=?",
            (json.dumps(proposal, ensure_ascii=False), exp_id, quote_no))
        conn.commit()
        _audit(_tok(authorization), "extra_expense.change_draft", "quotation", quote_no,
               f"{quote_no} 額外支出 #{exp_id} 變更申請草稿"
               f"（NT$ {float(row['total_cost'] or 0):,.0f} → NT$ {proposal['totalCost']:,.0f}）")
        return {"ok": True, "changeStatus": "草稿", "totalCost": proposal["totalCost"],
                "updatedAt": now}
    finally:
        conn.close()


@router.delete("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request")
def cancel_change_request(quote_no: str, exp_id: int, authorization: str = Header(None)):
    """撤銷變更申請（草稿或已駁回）。待核准附件的實體檔案一併刪除。
    送審中的要撤銷請先請簽核人駁回——否則簽核人手上的東西會憑空消失。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        cs = _col(row, "change_status", "") or ""
        if cs not in ("草稿", "已駁回"):
            raise HTTPException(409, f"「{cs or '無'}」狀態的變更申請不可撤銷")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以撤銷變更申請")
        _discard_pending_files(quote_no, exp_id, _change_of(row))
        _clear_change(conn, quote_no, exp_id)
        conn.commit()
        _audit(_tok(authorization), "extra_expense.change_cancel", "quotation", quote_no,
               f"{quote_no} 額外支出 #{exp_id} 撤銷變更申請")
        return {"ok": True}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/files",
             status_code=201)
async def upload_change_request_files(quote_no: str, exp_id: int,
                                      files: List[UploadFile] = File(...),
                                      authorization: str = Header(None)):
    """待核准附件：檔案實際落地，但只記在 `change_json.addFiles`，核准後才併進
    `files_json`。核准前任何讀取端（案件財務、結案報表 PDF）都看不到它。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        cs = _col(row, "change_status", "") or ""
        if cs not in ("草稿", "已駁回"):
            raise HTTPException(409, "請先按「編輯」建立變更申請草稿，再上傳附件")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以上傳變更申請附件")
        display = user.get("display_name") or user["username"]
        new_files = await save_document_files(
            "case_extra_expense", f"{quote_no}_{exp_id}", files, display)
        change = _change_of(row)
        change["addFiles"] = (change.get("addFiles") or []) + new_files
        conn.execute("UPDATE case_extra_expenses SET change_json=? WHERE id=? AND quote_no=?",
                     (json.dumps(change, ensure_ascii=False), exp_id, quote_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "extra_expense.change_upload_files", "quotation", quote_no,
           f"{quote_no} 額外支出 #{exp_id} 變更申請上傳 {len(new_files)} 個待核准附件")
    return {"ok": True, "added": len(new_files), "files": new_files}


@router.delete("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/files/{file_id}")
def delete_change_request_file(quote_no: str, exp_id: int, file_id: str,
                               authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        cs = _col(row, "change_status", "") or ""
        if cs not in ("草稿", "已駁回"):
            raise HTTPException(409, "送審中的變更申請不可增刪附件")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以刪除變更申請附件")
        change = _change_of(row)
        change["addFiles"] = delete_document_file(
            "case_extra_expense", f"{quote_no}_{exp_id}", change.get("addFiles") or [], file_id)
        conn.execute("UPDATE case_extra_expenses SET change_json=? WHERE id=? AND quote_no=?",
                     (json.dumps(change, ensure_ascii=False), exp_id, quote_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "extra_expense.change_delete_file", "quotation", quote_no,
           f"{quote_no} 額外支出 #{exp_id} 刪除變更申請待核准附件")
    return {"ok": True}


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/submit")
def submit_change_request(quote_no: str, exp_id: int, authorization: str = Header(None)):
    """送審變更申請。簽核流程沿用同一個文件類型 `extra_expense`（簽核設定頁不必
    多一個分頁——「改一筆已核准的支出」跟「新增一筆支出」該由同一批人把關）。

    沒有設定任何簽核層時直接套用，理由同 `submit_extra_expense()`。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        cs = _col(row, "change_status", "") or ""
        if cs not in ("草稿", "已駁回"):
            raise HTTPException(409, f"「{cs or '無'}」狀態的變更申請不可送審")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以送審變更申請")
        change = _change_of(row)
        if not (change.get("description") or "").strip():
            raise HTTPException(400, "變更申請缺少品項說明，請重新編輯")

        flow_setting = resolve_active_flow_setting("extra_expense")
        try:
            tiers = _setting_to_active_tiers(flow_setting, conn, user["username"])
        except UnresolvedManagerError as e:
            raise HTTPException(400, str(e))

        now = datetime.now().isoformat(timespec="seconds")
        display = user.get("display_name") or user["username"]
        old_total = float(row["total_cost"] or 0)
        new_total = float(change.get("totalCost") or 0)
        label = f"{change.get('description')}（NT$ {old_total:,.0f} → NT$ {new_total:,.0f}）"

        if not tiers:
            change["requestedByDisplay"] = display
            total = _apply_change(conn, row, change, display, now)
            conn.commit()
            _audit(_tok(authorization), "extra_expense.change_auto_apply", "quotation", quote_no,
                   f"{quote_no} 額外支出 #{exp_id} {label}：未設定簽核層，變更直接生效")
            return {"ok": True, "changeStatus": "", "applied": True,
                    "autoApproved": True, "totalCost": total}

        approval = {
            "requestedBy":        user["username"],
            "requestedByDisplay": display,
            "requestedAt":        now,
            "tiers":              tiers,
            "currentTier":        0,
        }
        conn.execute(
            "UPDATE case_extra_expenses SET change_status='待審核', change_approval_json=? "
            "WHERE id=? AND quote_no=?",
            (json.dumps(approval, ensure_ascii=False), exp_id, quote_no))
        conn.commit()

        for a in (tiers[0].get("approvers") or []):
            _notify(a["username"], "extra_expense_change_request", str(exp_id), quote_no,
                    f"案件 {quote_no} 的額外支出變更申請 {label} 需要您簽核")
        _audit(_tok(authorization), "extra_expense.change_submit", "quotation", quote_no,
               f"{quote_no} 額外支出 #{exp_id} 變更申請 {label} 送審", {"tierCount": len(tiers)})
        return {"ok": True, "changeStatus": "待審核", "tierCount": len(tiers)}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/approve")
def approve_change_request(quote_no: str, exp_id: int, body: dict = Body(default={}),
                           authorization: str = Header(None)):
    """核准當層；全部層都過了才真的套用（`_apply_change()`）。在那之前本體的金額
    完全不動——這正是使用者要的「原核准金額不動，核准後才生效」。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        cs = _col(row, "change_status", "") or ""
        if cs not in ("待審核", "簽核中"):
            raise HTTPException(409, f"「{cs or '無'}」狀態的變更申請不在簽核中")

        appr = _jcol(row, "change_approval_json")
        tiers = _active_tiers(appr)
        ct = _current_tier_idx(appr)
        # ⚠️ 2026-09-15 修正兩件事：
        # ① `check_approve_permission()` 的回傳值原本**整個被丟掉**（其他 router 都是
        #    `ok, code, msg = ...` 再 raise），等於這支端點的當層簽核人檢查形同虛設，
        #    任何過得了 _guard_case() 的人都簽得掉任何一層。
        # ② `check_no_tier_self_approval()` 原本無條件套用，但它是「沒有簽核層設定」
        #    時的 fallback 規則（其他 router 都只在 no-tier 分支呼叫）。有簽核層時
        #    照樣擋，會讓 2026-09-15 起組織流程算出「申請人本人就是該層主管」的
        #    自簽層永遠簽不掉。
        if tiers:
            ok, status_code, err_msg = check_approve_permission(tiers, ct, user["username"], conn)
            if not ok:
                raise HTTPException(status_code, err_msg)
        else:
            err = check_no_tier_self_approval(conn, appr, user)
            if err:
                raise HTTPException(403, err)

        now = datetime.now().isoformat(timespec="seconds")
        display = user.get("display_name") or user["username"]
        # 2026-09-25 使用者裁示：同層每一位都要依序簽完才過層（與共用規則、獎金分潤一致）。
        # ☠️ 原本寫法只寫 approvedAt、不寫 status，且第一位一簽就換層 ⇒ 同層第二位以後永遠沒機會簽，
        #    而讀 status 的地方把已簽的格子一律當成未簽。
        tier_done = sign_first_pending(tiers[ct], user, now, conn=conn) if tiers else True
        # 同一人連任多層時一次簽完（2026-09-15）：前端確認過才會帶 cascade=true；
        # 只吃「剩下未簽的全是他（或他代理的人）」的連續層，不替同層的別人簽。
        cascaded = (cascade_self_tiers(tiers, ct, user["username"], now, conn=conn)
                    if (tiers and tier_done and (body or {}).get("cascade")) else [])

        appr["tiers"] = tiers
        appr["currentTier"] = (ct + 1 + len(cascaded)) if tier_done else ct
        done = appr["currentTier"] >= len(tiers)
        appr.setdefault("history", []).append(
            {"at": now, "by": user["username"], "byDisplay": display,
             "action": "approve", "tier": ct, "comment": (body or {}).get("comment") or ""})

        change = _change_of(row)
        old_total = float(row["total_cost"] or 0)
        new_total = float(change.get("totalCost") or 0)
        label = f"{change.get('description')}（NT$ {old_total:,.0f} → NT$ {new_total:,.0f}）"

        if done:
            # requestedByDisplay 要在 _apply_change() 的稽核軌跡裡留下，先塞回 change
            change["requestedByDisplay"] = appr.get("requestedByDisplay") or ""
            applied_total = _apply_change(conn, row, change, display, now)
            conn.commit()
            requester = appr.get("requestedBy")
            if requester:
                _notify(requester, "extra_expense_change_approved", str(exp_id), quote_no,
                        f"案件 {quote_no} 的額外支出變更 {label} 已核准並生效")
            notify_module_activity("案件管理", "額外支出變更核准", display, f"{quote_no}｜{label}",
                                   f"case-management.html?q={quote_no}")
            _audit(_tok(authorization), "extra_expense.change_approve", "quotation", quote_no,
                   f"{quote_no} 額外支出 #{exp_id} 變更 {label} 第 {ct + 1} 層核准 → 已生效")
            return {"ok": True, "changeStatus": "", "applied": True, "totalCost": applied_total}

        conn.execute(
            "UPDATE case_extra_expenses SET change_status='簽核中', change_approval_json=? "
            "WHERE id=? AND quote_no=?",
            (json.dumps(appr, ensure_ascii=False), exp_id, quote_no))
        conn.commit()
        for a in (tiers[appr["currentTier"]].get("approvers") or []):
            _notify(a["username"], "extra_expense_change_request", str(exp_id), quote_no,
                    f"案件 {quote_no} 的額外支出變更申請 {label} 需要您簽核")
        _audit(_tok(authorization), "extra_expense.change_approve", "quotation", quote_no,
               f"{quote_no} 額外支出 #{exp_id} 變更 {label} 第 {ct + 1} 層核准 → 簽核中")
        return {"ok": True, "changeStatus": "簽核中", "currentTier": appr["currentTier"]}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/reject")
def reject_change_request(quote_no: str, exp_id: int, body: dict = Body(default={}),
                          authorization: str = Header(None)):
    """駁回變更申請 → 回到「已駁回」，申請人可以改完再送一次或整個撤銷。
    本體的金額從頭到尾沒被動過，所以駁回不需要回滾任何東西。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id)
        cs = _col(row, "change_status", "") or ""
        if cs not in ("待審核", "簽核中"):
            raise HTTPException(409, f"「{cs or '無'}」狀態的變更申請不在簽核中")

        appr = _jcol(row, "change_approval_json")
        tiers = _active_tiers(appr)
        ct = _current_tier_idx(appr)
        # 2026-09-24：回傳值原本被丟掉（approve 側 09-15 已修同型），任何過得了
        # _guard_case() 的人都駁回得了任何一層。
        ok, status_code, err_msg = check_reject_permission(tiers, ct, user, conn)
        if not ok:
            raise HTTPException(status_code, err_msg)

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
            "UPDATE case_extra_expenses SET change_status='已駁回', change_approval_json=? "
            "WHERE id=? AND quote_no=?",
            (json.dumps(appr, ensure_ascii=False), exp_id, quote_no))
        conn.commit()

        change = _change_of(row)
        label = f"{change.get('description')}（NT$ {float(change.get('totalCost') or 0):,.0f}）"
        requester = appr.get("requestedBy")
        if requester:
            _notify(requester, "extra_expense_change_rejected", str(exp_id), quote_no,
                    f"案件 {quote_no} 的額外支出變更申請 {label} 已被駁回"
                    + (f"：{reason}" if reason else ""))
        _audit(_tok(authorization), "extra_expense.change_reject", "quotation", quote_no,
               f"{quote_no} 額外支出 #{exp_id} 變更申請 {label} 被駁回" + (f"：{reason}" if reason else ""))
        return {"ok": True, "changeStatus": "已駁回"}
    finally:
        conn.close()
