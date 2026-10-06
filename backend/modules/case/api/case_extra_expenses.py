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
from typing import Any, List, Optional

from fastapi import APIRouter, Body, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel

from core.txn import begin_write
from db import get_db
from modules.case import payable_calendar as PC   # 行事曆「付款待辦」（預定付款日；預設關）
from helpers.case_access import deny_case, require_case   # M01-O1：逐案拒絕＝查無（同一個 404）
from helpers import row_access
from helpers.uploads import purge_document_files      # 草稿刪除時一併刪實體檔案（第44班）
from helpers.case_access import case_owner_readable   # AT-M1b：與附件提供者同一支
from helpers.auth import user_has_module, has_finance_access, has_cashier_access
from modules.case.recognition import normalize_date, COUNTED_EXTRA_STATUSES  # `AC2`；後者＝合計與營運報表同一條規則（32-Q6）
from modules.case import expense_forms as EF   # 費用單據（A2）：類型／明細金額／data 合併
from modules.case import purchase_items as PI    # 請購／採購單連結案件品項（32-S1）
from modules.case import expense_notify as XN  # 費用單據的信件（A2-7）；kind='' 一律不寄
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


#: 哨兵路徑段：`/api/quotations/-/extra-expenses/...` ＝ 沒有綁案件的費用單據（欄位 `quote_no` 存空字串）。
#: 這是 case_read_scope.json 裡**唯一**明列的「無案件」例外（MODULE-GUIDE §1.1；使用者 2026-10-01 裁示）。
CASELESS = "-"


def _qn(quote_no: str) -> str:
    return "" if quote_no == CASELESS else quote_no

# 可編輯／可刪除的狀態。送審中或已核准的不給改——改了簽核就失去意義
EDITABLE_STATUSES = ("草稿", "已駁回")
#: 作廢（管理員、已核准未付款）：列保留供稽核／申請人查詢，所有合計／應付／出納／報表／總帳來源一律排除（狀態過濾都是白名單，這個值不在內）
VOIDED_STATUS = "已作廢"
#: 請款流程（2026-09-27）：發票號碼長度上限；附件分類（沒有 kind 的舊附件一律視為 other，不回填猜測）
INVOICE_NO_MAX = 40
FILE_KINDS = ("invoice", "other")
_CLEAR_REMIT = ("remit_actual=NULL, remit_fee=0, remit_review='', remit_review_by='', "
                "remit_review_at='', remit_review_note=''")
_DATE_KEYS = {"invoice_date": "invoiceDate", "paid_date": "paidDate", "invoice_no": "invoiceNo", "planned_pay_date": "plannedPayDate"}

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
    # ── 費用單據（A2，2026-10-01）：kind＝''（舊版案件額外支出，行為不變）或 EF.KINDS；建立後 kind 不可改 ──
    kind:          str = ""
    data:          Optional[Any] = None       # 定義欄位值（物件；與既有值合併，None 值＝刪除該鍵）；型別由 EF 驗，不是 pydantic 422
    lines:         Optional[Any] = None       # 明細列（陣列；金額以後端重算為準）
    departmentId:  Optional[int] = None
    payeeType:     str = ""                   # employee／vendor／''
    payeeName:     str = ""
    payeeBank:     str = ""                   # 手填快照；銀行資料權威來源是 payroll 銀行資料表（A2-3）
    payeeAccount:  str = ""
    # 預定付款日（2026-10-05，case v7）：選填 YYYY-MM-DD；None＝沒送（編輯時保留原值）、''＝清除。不是實際付款日（那是出納登錄的 paidDate）
    plannedPayDate: Optional[str] = None


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
        # 請款流程（2026-09-27，case v1）：發票號碼（選填）；附件每筆的 kind：invoice＝發票、其他（含舊資料沒有 kind 的）＝other
        "invoiceNo":   _col(r, "invoice_no", "") or "",
        # W1（case v2）：出納登錄付款時的實付／手續費／差額審核（沒記錄過 ⇒ 實付＝null、手續費 0）
        "remitActual": _col(r, "remit_actual", None),
        "remitFee":    float(_col(r, "remit_fee", 0) or 0),
        "remitReview": _col(r, "remit_review", "") or "",
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
        # 費用單據（A2；migration 0003）。舊列＝kind ''、其餘空值
        "kind":          _col(r, "kind", "") or "",
        "docCode":       _col(r, "doc_code", "") or "",
        "data":          _jcol(r, "data_json"),
        "lines":         _jlist(r, "lines_json"),
        "defVersion":    int(_col(r, "def_version", 0) or 0),
        "departmentId":  _col(r, "department_id", None),
        "payeeType":     _col(r, "payee_type", "") or "",
        "payeeName":     _col(r, "payee_name", "") or "",
        "payeeBank":     _col(r, "payee_bank", "") or "",
        "payeeAccount":  _col(r, "payee_account", "") or "",
        "payTerms":      _col(r, "pay_terms", "") or "",
        "remitDate":     _col(r, "remit_date", "") or "",
        "plannedPayDate": _col(r, "planned_pay_date", "") or "",
        "payMethod":     _col(r, "pay_method", "") or "",
        "payAccountCode": _col(r, "pay_account_code", "") or "",
        "paidBy":        _col(r, "paid_by", "") or "",
        "pretax":        float(_col(r, "pretax", 0) or 0),
        "tax":           float(_col(r, "tax", 0) or 0),
        "currency":      _col(r, "currency", "TWD") or "TWD",
        "voidReason":    _col(r, "void_reason", "") or "",
        "voidedBy":      _col(r, "voided_by", "") or "",
        "voidedAt":      _col(r, "voided_at", "") or "",
    }


def _col(r, name, default=None):
    """sqlite3.Row 取欄位，欄位不存在時回 default（migration 還沒跑到的保險）。"""
    try:
        return r[name]
    except (IndexError, KeyError):
        return default


def _jlist(r, name) -> list:
    try:
        v = json.loads(_col(r, name) or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _jcol(r, name) -> dict:
    try:
        return json.loads(_col(r, name) or "{}")
    except Exception:
        return {}


def _load(conn, quote_no: str, exp_id: int, user: dict = None):
    row = conn.execute(
        "SELECT * FROM case_extra_expenses WHERE id=? AND quote_no=?", (exp_id, quote_no)
    ).fetchone()
    if not row:
        raise HTTPException(404, "找不到這筆額外支出")
    if quote_no == "" and not _caseless_visible(conn, row, user):     # 無案件：逐列可見規則（看不到＝不存在）；user 沒給 ⇒ 關閉
        raise HTTPException(404, "找不到這筆額外支出")
    return row


def _subj(quote_no: str) -> str:
    return "案件 %s" % quote_no if quote_no else "（無案件）"


def _audit_target(quote_no: str, exp_id) -> tuple:
    """稽核的 (target_type, target_id)：有案件＝沿用原本（quotation／案件單號）；無案件＝額外支出本身（不能把空字串當 target_id）。"""
    return ("quotation", quote_no) if quote_no else ("case_extra_expense", str(exp_id))


def _asum(r) -> dict:
    """稽核 detail 的單據摘要（A2 S2）：類型／單號／金額／明細列數／歸屬部門／收款人類型／付款方式。
    **永遠不放**收款人姓名、銀行、帳號、明細列內容、data（個資與內容留在單據本身，稽核只留「發生了什麼」）。
    例外（既有作法，不變）：稽核標題文字沿用單據說明（費用單據的說明＝第一列摘要，使用者自己填的品項名稱）。舊版列（kind=''）只帶金額。"""
    out = {"totalCost": float(_col(r, "total_cost", 0) or 0)}
    kind = _col(r, "kind", "") or ""
    if kind:
        out.update({"kind": kind, "docCode": _col(r, "doc_code", "") or "", "lineCount": len(_jlist(r, "lines_json")),
                    "departmentId": _col(r, "department_id", None), "payeeType": _col(r, "payee_type", "") or "",
                    "currency": _col(r, "currency", "") or "TWD"})
        if _col(r, "pay_method", ""):
            out["payMethod"] = _col(r, "pay_method", "")
    return out


def _caseless_visible(conn, row, user) -> bool:
    """無案件單據的逐列可見規則（不用 `case_owner_readable`：沒有案件可以查）：建立者本人、本單簽核鏈成員（含代理）、
    admin／superadmin、出納／財務模組。user 為 None ⇒ False（fail closed）。"""
    if not isinstance(user, dict):
        return False
    if has_finance_access(user) or (row["created_by"] or "") == user.get("username"):     # 第42班：admin 直通拿掉（財務角色／superadmin 才全看）
        return True
    return bool(is_document_approver(_col(row, "approval_json", ""), user, conn))


def _amount_viewer(conn, row, user) -> bool:
    """費用單據（kind≠''）的金額誰看得到（使用者 2026-10-01 最終裁示）：申請人（建立者／data.applicant）、本單簽核人（含變更申請的簽核鏈與代理）、
    出納／財務、管理員以上。其他人只看得到狀態（金額、明細、資料、收款人銀行、付款資訊一律遮蔽）。"""
    if not isinstance(user, dict):
        return False
    if has_finance_access(user):                  # 第42班：財務角色／superadmin；申請人、簽核人例外維持
        return True
    me = user.get("username")
    if (row["created_by"] or "") == me or str(_jcol(row, "data_json").get("applicant") or "") == me:
        return True
    return bool(is_document_approver(_col(row, "approval_json", ""), user, conn)
                or is_document_approver(_col(row, "change_approval_json", ""), user, conn))


#: 遮蔽後仍保留的欄位（狀態面）；其餘金額／明細／資料／收款人／付款欄位一律清掉
_MASKED_KEEP = ("id", "kind", "docCode", "status", "expenseDate", "createdBy", "createdByName", "createdAt",
                "updatedAt", "departmentId", "changeStatus", "paidDate", "defVersion", "currency")          # 說明／類別也不留（摘要可能就是內容）


def _mask_row(d: dict) -> dict:
    out = {k: d[k] for k in _MASKED_KEEP if k in d}
    out.update({"masked": True, "totalCost": None, "description": "", "category": "", "lines": [], "lineCount": len(d.get("lines") or []), "data": {}, "files": [],
                "approval": {}, "change": {}, "changeApproval": {}})
    return out


def _caseless_create_allowed(user) -> bool:
    """誰可以開無案件費用單：管理員以上，或持 `expense_forms` 權限（W1 登記的單一權限 key）。"""
    return user.get("role") in ("superadmin", "admin") or user_has_module(user, "expense_forms")


def _guard_case(conn, quote_no: str, user: dict):
    """報價單存在＋擁有者檢查。`quote_no` 可列舉，不擋就是 IDOR。
    准不准只看 L1 `case_owner_readable`（附件提供者用同一支，稽核 D AT-M1b）；這裡只負責說出原因。"""
    if quote_no == "":
        return          # 無案件：沒有報價單可查；逐列可見規則在 `_load`（`_caseless_visible`），建立權限在 create_extra_expense
    q = conn.execute(
        "SELECT sales_person_id, sales_person, assigned_user_ids FROM quotations WHERE quote_no=?",
        (quote_no,)
    ).fetchone()
    if not q:
        deny_case(None, quote_no, user, "not_found")
    if not case_owner_readable(conn, quote_no, user):
        deny_case(None, quote_no, user, "denied")          # M01-O1：看不到＝不存在（同一個 404，audit 記真正原因）


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


def _require_desc(body: ExtraExpenseIn):
    """舊版案件額外支出（kind=''）一定要有品項說明；費用單據由明細摘要衍生，不強制。"""
    if not (body.description or "").strip():
        raise HTTPException(400, "請填寫品項說明")


def _validate(body: ExtraExpenseIn):
    if body.category and body.category not in CATEGORIES:
        raise HTTPException(400, f"類別必須是：{'／'.join(CATEGORIES)}")
    if float(body.qty or 0) < 0 or float(body.unitCost or 0) < 0:
        raise HTTPException(400, "數量與單位成本不能為負")
    EF.check_kind(body.kind)
    if body.payeeType not in ("", "employee", "vendor"):
        raise HTTPException(400, "收款人類型只能是 employee／vendor")
    for _k in ("payeeName", "payeeBank", "payeeAccount"):
        if len(getattr(body, _k) or "") > EF.MAX_TEXT:
            raise HTTPException(400, "%s 太長（上限 %d 字）" % (_k, EF.MAX_TEXT))
    if body.plannedPayDate is not None:
        normalize_date(body.plannedPayDate, "預定付款日")


@router.get("/api/quotations/{quote_no}/extra-expenses")
def list_extra_expenses(quote_no: str, authorization: str = Header(None)):
    """列出一張案件的額外支出，附三個合計。

    權限比照同一份資料的既有端點：只要求登入＋擁有者檢查。`totalPending` 是
    **送審中但仍計入成本**的金額——使用者指定送審中的照樣算進成本，但畫面要提醒
    還沒簽完，所以這裡把它單獨算出來給前端做提示，不是從總額裡扣掉。
    """
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
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
        if quote_no == "":
            rows = [r for r in rows if _caseless_visible(conn, r, user)]       # 無案件：逐列可見規則
        if not can_see_financial(user):
            # 舊版列（kind=''）維持原規則（只看自己的／自己簽的）；費用單據（kind≠''）改「看得到列、金額遮蔽」（見 `_amount_viewer`）
            rows = [r for r in rows
                    if (_col(r, "kind", "") or "")
                    or (r["created_by"] or "") == user["username"]
                    or is_document_approver(_col(r, "approval_json", ""), user, conn)]
        items = []
        for r in rows:
            d = _row_to_dict(r)
            if (d["kind"] or "") and not _amount_viewer(conn, r, user):
                d = _mask_row(d)
            items.append(d)
        # 合計只算看得到金額的列（避免「清單 3 筆、合計卻含別人的金額」）；已作廢的列照列出（稽核／申請人查詢）但不進任何合計
        visible = [i for i in items if not i.get("masked") and i["status"] != VOIDED_STATUS]
        # 32-Q6（使用者裁示 2026-10-02）：合計與營運報表同一條規則——只計 COUNTED_EXTRA_STATUSES（待審核／簽核中／已核准）、
        # 且類型要進金流（kind='' 或 payable）：**請購單、草稿、已駁回不計**。（原本只排除作廢與被遮蔽的列，精算的額外支出因此比報表多。）
        counted = [i for i in visible if i["status"] in COUNTED_EXTRA_STATUSES and EF.is_payable_kind(i["kind"] or "")]
        # 32-S3（Q1）：採購單明細連到案件品項的列＝該品項的**實際成本**，不再算額外支出。
        # 過渡安全：`totalAmount`／`totalPending` 先**維持含連結列**（既有精算頁照舊看到全部金額，不會有錢憑空消失）；
        # 另給 `itemLinkedAmount`（連結列金額）與 `extraOnlyAmount`（＝totalAmount−itemLinkedAmount，真正的額外支出）。
        # 精算頁改版（S5）時改讀 extraOnlyAmount＋品項「系統帶入實際」，兩邊一起切，才不會漏算或重複。
        live = PI.load_live_item_ids(conn, quote_no) if quote_no else set()        # 品項已不在報價內的連結列回到額外支出（錢不消失）
        for i in counted:
            i["linkedAmount"] = PI.linked_split(i.get("lines"), live)[0] if i["kind"] == PI.ORD else 0.0
        total = sum(float(i["totalCost"] or 0) for i in counted)
        pending = sum(float(i["totalCost"] or 0) for i in counted if i["status"] != "已核准")
        item_linked = sum(i["linkedAmount"] for i in counted)
        uncounted = sum(float(i["totalCost"] or 0) for i in visible if i not in counted)      # 資訊：沒有計入的金額（請購單、草稿、已駁回）
        # W1：手續費（公司自付、已登錄付款者）另計，進案件成本（settlement 的 remitFeeTotal）；不併入 totalAmount
        fee_total = sum(float(i["remitFee"] or 0) for i in visible if i["paidDate"])
        return {
            "quoteNo": quote_no,
            "items": items,
            "remitFeeTotal": fee_total,
            "totalAmount": total,
            "totalPending": pending,
            "uncountedAmount": uncounted,
            "itemLinkedAmount": item_linked,
            "extraOnlyAmount": total - item_linked,
            # 對這位使用者遮蔽金額的列數（不含已作廢）：> 0 ⇒ totalAmount 不是完整成本，精算頁據此擋存檔／完結（否則會把殘缺的總額寫進精算）
            "maskedCount": sum(1 for i in items if i.get("masked") and i["status"] != VOIDED_STATUS),
            "pendingCount": sum(1 for i in items if i["status"] not in ("已核准", "草稿", VOIDED_STATUS)),
            "categories": CATEGORIES,
        }
    finally:
        conn.close()


@router.get("/api/quotations/{quote_no}/purchase-items")
def list_purchase_items(quote_no: str, authorization: str = Header(None)):
    """請購單／採購單的「從案件品項帶入」挑選器（32-S1）：報價品項＋計畫量／已請購／已採購／剩餘可採購量。
    權限＝與案件額外支出清單同一條（登入＋案件可見）；看不到財務金額的人不回 `planUnitCost`。無案件（哨兵 `-`）⇒ 400。"""
    quote_no = _qn(quote_no)
    user = _require_user(authorization)
    if quote_no == "":
        raise HTTPException(400, "無案件的單據沒有案件品項可挑")
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        q = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        try:
            data = json.loads((q["data_json"] if q else "") or "{}")
        except (TypeError, ValueError):
            data = {}
        rows = conn.execute("SELECT id, kind, status, lines_json, doc_code FROM case_extra_expenses WHERE quote_no=? AND kind IN (?,?)",
                            (quote_no, PI.REQ, PI.ORD)).fetchall()
        return {"quoteNo": quote_no, "items": PI.picker(data, rows, show_cost=can_see_financial(user),
                                                        extra_ordered=PI.case_extra_ordered(conn, quote_no, data, rows))}
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
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    _validate(body)
    if quote_no == "" and not _caseless_create_allowed(user):
        raise HTTPException(403, "沒有建立無案件費用單據的權限")
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        now = datetime.now().isoformat(timespec="seconds")
        kind = EF.check_kind(body.kind)
        if not kind:
            _require_desc(body)
        if kind:
            begin_write(conn)                                   # 配單號＋寫入要在同一把寫鎖裡
            lines, total = EF.normalize_lines(body.lines)
            data = EF.normalize_data(body.data)
            lines, over_plan = PI.check_lines(conn, quote_no, kind, lines)          # 32-S2：明細連案件品項（沒有 itemId ⇒ 原樣）
            PI.check_from_pr(conn, quote_no, kind, data)
            doc_code = EF.next_doc_code(conn, kind, now[:10])
            desc = (body.description or "").strip() or next((l.get("summary") for l in lines if l.get("summary")), "") or "（%s）" % doc_code
        else:
            lines, total, data, doc_code, over_plan = [], _recalc(body), {}, "", []
            desc = (body.description or "").strip()
        display = user.get("display_name") or user["username"]
        cur = conn.execute(
            "INSERT INTO case_extra_expenses "
            "(quote_no, category, description, qty, unit, unit_cost, total_cost, note, "
            " expense_date, doc_no, files_json, created_by, created_by_name, created_by_inferred, "
            " payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json,"
            " kind, doc_code, data_json, lines_json, department_id, payee_type, payee_name, payee_bank, payee_account, def_version,"
            " planned_pay_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,'草稿','{}',?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, body.category or "其他", desc,
             float(body.qty or 0), (body.unit or "").strip(), float(body.unitCost or 0), total,
             (body.note or "").strip(), (body.expenseDate or "").strip(), (body.docNo or "").strip(),
             user["username"], display,
             (body.payerUsername or "").strip(), (body.payerName or "").strip(),
             now, now, display,
             kind, doc_code, json.dumps(data, ensure_ascii=False), EF.dumps_lines(lines), EF.department_of(data, body.departmentId),
             body.payeeType, (body.payeeName or "").strip(), (body.payeeBank or "").strip(), (body.payeeAccount or "").strip(),
             EF.current_def_version(conn, kind),                 # 建立當下的類型定義版本（送審時再釘一次）
             normalize_date(body.plannedPayDate, "預定付款日")),
        )
        conn.commit()
        exp_id = cur.lastrowid
        _audit(_tok(authorization), "extra_expense.create", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 新增額外支出「{(body.description or '').strip()}」 NT$ {total:,.0f}",
               _asum(conn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone()))
        return {"ok": True, "id": exp_id, "status": "草稿", "totalCost": total, "docCode": doc_code, "kind": kind,
                **({"overPlan": over_plan} if over_plan else {})}
    finally:
        conn.close()


@router.patch("/api/quotations/{quote_no}/extra-expenses/{exp_id}")
def update_extra_expense(quote_no: str, exp_id: int, body: ExtraExpenseIn = Body(...),
                         authorization: str = Header(None)):
    """編輯（僅草稿／已駁回）。會更新「更動日期」與「最後更動人」。"""
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    _validate(body)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
        if row["status"] not in EDITABLE_STATUSES:
            raise HTTPException(409, f"「{row['status']}」狀態不可編輯（僅草稿與已駁回可改）")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以修改這筆額外支出")

        now = datetime.now().isoformat(timespec="seconds")
        row_kind = _col(row, "kind", "") or ""
        if not row_kind:
            _require_desc(body)
        if (body.kind or "") != row_kind and (body.kind or "") != "":
            raise HTTPException(400, "單據類型建立後不可更改")
        if row_kind:
            begin_write(conn)
            lines, total = EF.normalize_lines(body.lines if body.lines is not None else _jlist(row, "lines_json"))
            data = EF.normalize_data(body.data, _jcol(row, "data_json"))       # 與既有值合併：沒送的鍵不會被丟掉
            lines, over_plan = PI.check_lines(conn, quote_no, row_kind, lines, exclude_id=exp_id)      # 32-S2
            PI.check_from_pr(conn, quote_no, row_kind, data)
            desc = (body.description or "").strip() or row["description"]
        else:
            lines, total, data, desc = _jlist(row, "lines_json"), _recalc(body), _jcol(row, "data_json"), (body.description or "").strip()
            over_plan = []
        conn.execute(
            "UPDATE case_extra_expenses SET category=?, description=?, qty=?, unit=?, "
            " unit_cost=?, total_cost=?, note=?, expense_date=?, doc_no=?, "
            " payer_username=?, payer_name=?, updated_at=?, updated_by_name=?, "
            " data_json=?, lines_json=?, department_id=?, payee_type=?, payee_name=?, payee_bank=?, payee_account=?, planned_pay_date=? "
            "WHERE id=? AND quote_no=?",
            (body.category or "其他", desc, float(body.qty or 0),
             (body.unit or "").strip(), float(body.unitCost or 0), total,
             (body.note or "").strip(), (body.expenseDate or "").strip(), (body.docNo or "").strip(),
             (body.payerUsername or "").strip(), (body.payerName or "").strip(),
             now, user.get("display_name") or user["username"],
             json.dumps(data, ensure_ascii=False), EF.dumps_lines(lines),
             EF.department_of(data, body.departmentId) if row_kind else _col(row, "department_id", None),
             body.payeeType if row_kind else (_col(row, "payee_type", "") or ""),
             (body.payeeName or "").strip() if row_kind else (_col(row, "payee_name", "") or ""),
             (body.payeeBank or "").strip() if row_kind else (_col(row, "payee_bank", "") or ""),
             (body.payeeAccount or "").strip() if row_kind else (_col(row, "payee_account", "") or ""),
             normalize_date(body.plannedPayDate, "預定付款日") if body.plannedPayDate is not None else (_col(row, "planned_pay_date", "") or ""),
             exp_id, quote_no),
        )
        conn.commit()
        _audit(_tok(authorization), "extra_expense.update", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 修改額外支出 #{exp_id}「{(body.description or '').strip()}」 NT$ {total:,.0f}",
               {**_asum(conn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone()),
                "before": {"totalCost": float(row["total_cost"] or 0)}})
        return {"ok": True, "totalCost": total, "updatedAt": now, **({"overPlan": over_plan} if over_plan else {})}
    finally:
        conn.close()


# ── 請款頁（我的工作 → 新增請款；2026-09-27 使用者裁示）─────────────────────────────
# 不另建資料：請款＝案件額外支出。這兩支只是給請款頁「挑案件」與「我的請款」用的查詢，
# 可見範圍與額外支出各端點同一支 `case_owner_readable`（看不到的案件不列、也填不了）。

#: 請款頁「挑案件」一次最多列幾筆
PAYREQ_CASES_MAX = 30


def like_literal(s: str) -> str:
    """把使用者輸入變成 LIKE 的字面值（搭配 `ESCAPE '\\'`）：`\\`、`%`、`_` 前面加 `\\`。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/api/extra-expenses/cases")
def payreq_cases(q: str = Query(""), authorization: str = Header(None)):
    """挑案件：看得到（可以填額外支出）的案件，依單號／客戶／專案搜尋，最多 PAYREQ_CASES_MAX 筆。

    先過濾可見、再取前 N 筆（逐列走游標，湊滿就停）——不可以先 LIMIT 再過濾：看得到的案件排在較舊的位置時會整個搜不到。
    關鍵字照字面比對：`%`、`_`、`\\` 跳脫（ESCAPE），輸入 `%` 不會變成「全部」。"""
    user = _require_user(authorization)
    kw = "%" + like_literal((q or "").strip()) + "%"
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT quote_no, customer_name, project_name FROM quotations"
            " WHERE quote_no LIKE ? ESCAPE '\\' OR customer_name LIKE ? ESCAPE '\\' OR project_name LIKE ? ESCAPE '\\'"
            " ORDER BY updated_at DESC", (kw, kw, kw))
        out = []
        for r in rows:
            if case_owner_readable(conn, r["quote_no"], user):
                out.append({"quoteNo": r["quote_no"], "customerName": r["customer_name"] or "",
                            "projectName": r["project_name"] or ""})
                if len(out) >= PAYREQ_CASES_MAX:
                    break
        return out
    finally:
        conn.close()


@router.get("/api/extra-expenses/mine")
def payreq_mine(authorization: str = Header(None)):
    """我的申請：自己填的額外支出（最新 100 筆），帶案件名稱；案件已看不到的不列。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT e.*, q.customer_name AS _cust, q.project_name AS _proj FROM case_extra_expenses e"
            " LEFT JOIN quotations q ON q.quote_no = e.quote_no"
            " WHERE e.created_by = ? ORDER BY e.id DESC LIMIT 100", (user["username"],)).fetchall()
        out = []
        for r in rows:
            if r["quote_no"] and not case_owner_readable(conn, r["quote_no"], user):      # 無案件列＝自己建立的，照列
                continue
            d = _row_to_dict(r)
            d.update({"quoteNo": r["quote_no"], "customerName": r["_cust"] or "", "projectName": r["_proj"] or ""})
            out.append(d)
        return out
    finally:
        conn.close()


@router.patch("/api/quotations/{quote_no}/extra-expenses/{exp_id}/dates")
def set_extra_expense_dates(quote_no: str, exp_id: int, body: dict = Body(...),
                            authorization: str = Header(None)):
    """`AC2`：登錄廠商發票日期／付款日（只改有給的鍵；''＝清除）。**任何狀態都可以登**——

    兩個日期都不影響金額，只決定報表歸哪個月；已核准的支出正是最常事後才拿到發票、
    才付款的那一批，走變更申請會讓財務補登卡在簽核上（hichan-0a 裁示）。
    權限：填寫人本人、admin+，或出納（付款是出納登的）。
    **付款日例外**（稽核 A AB-M1，2026-09-28）：IP-100 之後「付款日空白」＝出納待付款的判準，付款日不再只是歸月——
    本人設或清付款日 ＝ 繞過出納或讓已付的請款重回待付款 ⇒ `paidDate` 只有出納或 admin+ 能設；
    已有付款日的**清除或改日期**只限 admin+，並寫專用稽核動作 `extra_expense.paid_date_override`。
    發票日期、發票號碼照舊（本人可登）。
    付款日只准在已核准之後設定（AB-S8，使用者 2026-09-28 裁示；出納、admin 都一樣）⇒ 未核准 409 並說明。
    """
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    body = body or {}
    changes = {}
    if "invoiceDate" in body:
        changes["invoice_date"] = normalize_date(body.get("invoiceDate"), "發票日期")
    if "paidDate" in body:
        changes["paid_date"] = normalize_date(body.get("paidDate"), "付款日")
    if "plannedPayDate" in body:                                 # 預定付款日（2026-10-05）：已核准後補登／改期也走這裡；''＝清除
        changes["planned_pay_date"] = normalize_date(body.get("plannedPayDate"), "預定付款日")
    if "invoiceNo" in body:                                      # 請款流程：發票號碼（選填；已核准也可以補）
        inv_no = str(body.get("invoiceNo") or "").strip()
        if len(inv_no) > INVOICE_NO_MAX:
            raise HTTPException(400, "發票號碼最長 %d 字" % INVOICE_NO_MAX)
        changes["invoice_no"] = inv_no
    if not changes:
        raise HTTPException(400, "沒有要登錄的日期或發票號碼")
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
        if row["status"] == VOIDED_STATUS:
            raise HTTPException(409, "這筆額外支出已作廢，不能再登錄日期或發票")
        if not (_can_modify(row, user) or has_cashier_access(user)):
            raise HTTPException(403, "只有填寫人本人、管理員或財務角色可以登錄這筆額外支出的日期")
        is_admin = has_cashier_access(user)       # 第42班：付款日只有財務角色／superadmin（admin 直通拿掉）
        old_paid = (_col(row, "paid_date", "") or "")
        if "planned_pay_date" in changes and old_paid:           # 付款後預定日只當歷史保留，不再改（提醒對已付款的列本來就不發）
            raise HTTPException(409, "這筆已登錄付款（%s），預定付款日保留為歷史紀錄，不能再修改" % old_paid[:10])
        override = False
        if "paid_date" in changes:
            if not is_admin:
                raise HTTPException(403, "付款日只有財務角色可以登錄（申請人登錄會繞過出納待付款）")
            if changes["paid_date"] and row["status"] != "已核准":    # AB-S8（使用者裁示）：出納、admin 都一樣
                raise HTTPException(409, "這筆申請還沒核准（目前「%s」），不能登錄付款日；核准後再登錄" % row["status"])
            if old_paid and changes["paid_date"] != old_paid:
                if user.get("role") != "superadmin":                     # 使用者 2026-10-01：推翻／覆寫已付款狀態一律最高管理員（admin 只是主管等級）
                    raise HTTPException(403, "這筆已登錄付款日 %s，清除或更改只限最高管理員" % old_paid)
                override = True
        now = datetime.now().isoformat(timespec="seconds")
        sets = ", ".join("%s=?" % k for k in changes)
        if "paid_date" in changes and not changes["paid_date"]:      # W1：付款日清除 ⇒ 重回待付款，實付／手續費／審核一併清掉
            sets += ", " + _CLEAR_REMIT
        conn.execute("UPDATE case_extra_expenses SET " + sets + ", updated_at=?, updated_by_name=?"
                     " WHERE id=? AND quote_no=?",
                     list(changes.values()) + [now, user.get("display_name") or user["username"], exp_id, quote_no])
        conn.commit()
    finally:
        conn.close()
    if "planned_pay_date" in changes or "paid_date" in changes:     # commit 之後對齊行事曆「付款待辦」（寫鎖已放）
        PC.fire(exp_id)
    label = {"invoice_date": "發票日期", "paid_date": "付款日", "invoice_no": "發票號碼", "planned_pay_date": "預定付款日"}
    _audit(_tok(authorization), "extra_expense.dates", *_audit_target(quote_no, exp_id),
           "%s 額外支出 #%s 登錄%s" % (quote_no, exp_id, "、".join(
               "%s %s" % (label[k], v or "（清除）") for k, v in changes.items())))
    if override:                                          # AB-M1：已付的付款日被清除或更改 ⇒ 另一個查得到的動作
        _audit(_tok(authorization), "extra_expense.paid_date_override", *_audit_target(quote_no, exp_id),
               "%s 額外支出 #%s 付款日 %s → %s（最高管理員更正）" % (quote_no, exp_id, old_paid, changes["paid_date"] or "（清除，重回待付款）"))
    return {"ok": True, "updatedAt": now,
            **{_DATE_KEYS[k]: v for k, v in changes.items()}}


@router.delete("/api/quotations/{quote_no}/extra-expenses/{exp_id}")
def delete_extra_expense(quote_no: str, exp_id: int, authorization: str = Header(None)):
    """刪除（僅草稿／已駁回）。已核准的要移除只能請最高管理員從資料庫處理——
    已經計入成本與報表的數字不該被單方面刪掉。"""
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
        if row["status"] not in EDITABLE_STATUSES:
            raise HTTPException(409, f"「{row['status']}」狀態不可刪除（僅草稿與已駁回可刪）")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以刪除這筆額外支出")
        orphan_files = _files_of(row) + [f for f in (_change_of(row).get("addFiles") or []) if isinstance(f, dict)]
        conn.execute("DELETE FROM case_extra_expenses WHERE id=? AND quote_no=?", (exp_id, quote_no))
        conn.commit()
        purge_document_files(orphan_files)         # 草稿／已駁回的單據一併刪掉它名下的實體檔案（原本會留成孤兒檔）
        _audit(_tok(authorization), "extra_expense.delete", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 刪除額外支出 #{exp_id}「{row['description']}」", _asum(row))
        return {"ok": True}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/void")
def void_extra_expense(quote_no: str, exp_id: int, body: dict = Body(default={}),
                       authorization: str = Header(None)):
    """作廢（僅最高管理員 superadmin；僅「已核准且尚未付款」；理由必填）。列保留（狀態＝已作廢）供稽核與申請人查詢，不計入任何合計／應付／出納／營運報表。

    GL 不另寫反向分錄：E11／E11b 只對 status='已核准' 的列產生，狀態離開後來源事件消失 ⇒ 總帳引擎自動作廢草稿或對已過帳傳票產生反向草稿
    （`ledger/engine.py::_orphans`；有測試）。已付款的列不可直接作廢：付款已是現金事件，請管理員先更正付款日（退回待付款）再作廢。"""
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    if user["role"] != "superadmin":
        raise HTTPException(403, "只有最高管理員可以作廢已核准的額外支出")
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫作廢理由")
    if len(reason) > EF.MAX_TEXT:
        raise HTTPException(400, "作廢理由太長（上限 %d 字）" % EF.MAX_TEXT)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
        if row["status"] == VOIDED_STATUS:
            raise HTTPException(409, "這筆額外支出已作廢")
        if row["status"] != "已核准":
            raise HTTPException(409, "「%s」狀態不可作廢（草稿與已駁回請直接刪除；送審中請先駁回）" % row["status"])
        if (row["paid_date"] or "").strip():
            raise HTTPException(409, "已登錄付款（%s），不可直接作廢：請先由最高管理員更正付款日（退回待付款）再作廢" % row["paid_date"][:10])
        change = _change_of(row)
        now = datetime.now().isoformat(timespec="seconds")
        begin_write(conn)
        cur = conn.execute(
            "UPDATE case_extra_expenses SET status=?, void_reason=?, voided_by=?, voided_at=?, updated_at=?,"
            " change_status='', change_json='{}', change_approval_json='{}'"
            " WHERE id=? AND quote_no=? AND status='已核准' AND COALESCE(paid_date, '')=''",
            (VOIDED_STATUS, reason, user["username"], now, now, exp_id, quote_no))
        if cur.rowcount == 0:                                    # 同時有人付款／作廢 ⇒ 後到的人不覆蓋
            conn.rollback()
            raise HTTPException(409, "這筆額外支出剛被付款或作廢，請重新整理")
        conn.commit()
        PC.fire(exp_id)                                          # 作廢 ⇒ 收回「付款待辦」事件
        if change:
            _discard_pending_files(quote_no, exp_id, change)
        label = "%s（NT$ %s）" % (row["description"] or "額外支出", format(float(row["total_cost"] or 0), ",.0f"))
        requester = _jcol(row, "approval_json").get("requestedBy") or row["created_by"]
        if requester:
            _notify(requester, "extra_expense_voided", str(exp_id), quote_no or "無案件",
                    "%s 的額外支出 %s 已被作廢：%s" % (_subj(quote_no), label, reason))
        _audit(_tok(authorization), "extra_expense.void", *_audit_target(quote_no, exp_id),
               "%s 作廢額外支出 #%s %s：%s" % (quote_no or "無案件", exp_id, label, reason), {"reason": reason, **_asum(row)})
        return {"ok": True, "status": VOIDED_STATUS, "voidedAt": now}
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
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
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
        if _col(row, "kind", "") or "":
            # 送審當下：費用類別驗證（不在啟用清單 ⇒ 400，狀態不變）＋類別代碼／科目快照寫進明細（W4 合約）
            _new_lines = EF.prepare_submit(conn, _jlist(row, "lines_json"))
            begin_write(conn)                                   # 32-S2：累計上限在寫鎖內驗（兩人同時對同一品項送審不會一起通過）
            _new_lines, _over = PI.check_lines(conn, quote_no, row["kind"], _new_lines, exclude_id=exp_id, require_reason=True)
            PI.check_from_pr(conn, quote_no, row["kind"], _jcol(row, "data_json"))
            conn.execute("UPDATE case_extra_expenses SET lines_json=?, def_version=? WHERE id=? AND quote_no=?",
                         (EF.dumps_lines(_new_lines), EF.current_def_version(conn, row["kind"]), exp_id, quote_no))     # 送審當下釘定義版本

        if not tiers:
            conn.execute(
                "UPDATE case_extra_expenses SET status='已核准', updated_at=?, approval_json=? "
                "WHERE id=? AND quote_no=?",
                (now, json.dumps({"autoApproved": True,
                                  "note": "未設定任何簽核層，送審即視為核准"},
                                 ensure_ascii=False), exp_id, quote_no),
            )
            conn.commit()
            _audit(_tok(authorization), "extra_expense.auto_approve", *_audit_target(quote_no, exp_id),
                   f"{quote_no or '無案件'} 額外支出 #{exp_id} {label}：未設定簽核層，直接核准", _asum(row))
            XN.fire("approved", conn, row, requester=user["username"], payable=EF.is_payable_kind(_col(row, "kind", "") or ""))
            PC.fire(exp_id)                                      # 送審即核准 ⇒ 有預定付款日就建「付款待辦」
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
            _notify(a["username"], "extra_expense_approval_request", str(exp_id), quote_no or "無案件",
                    f"{_subj(quote_no)} 的額外支出 {label} 需要您簽核")
        # 知會（2026-09-15）：整條簽核鏈都只有申請人本人時（他已在組織職權頂端），
        # 最高管理者不再被塞進簽核鏈，改收一則知會通知（仍可隨時以 superadmin 退回）。
        notify_org_chain_notice(conn, tiers, user["username"], str(exp_id), quote_no or "無案件",
                                f"{_subj(quote_no)} 的額外支出 {label} 由 "
                                f"{user.get('display_name') or user['username']} 依組織職權自行簽核，知會您",
                                type_="extra_expense_approval_notice")
        XN.fire("submitted", conn, row, approvers=[a["username"] for a in (tiers[0].get("approvers") or [])])
        _audit(_tok(authorization), "extra_expense.submit", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} {label} 送審", {"tierCount": len(tiers), **_asum(row)})
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
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
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
                _notify(a["username"], "extra_expense_approval_request", str(exp_id), quote_no or "無案件",
                        f"{_subj(quote_no)} 的額外支出 {label} 需要您簽核")
            XN.fire("next_tier", conn, row, tier_no=appr["currentTier"] + 1, total_tiers=len(tiers),
                    approvers=[a["username"] for a in (tiers[appr["currentTier"]].get("approvers") or [])])
        else:
            requester = appr.get("requestedBy")
            if requester:
                _notify(requester, "extra_expense_approved", str(exp_id), quote_no or "無案件",
                        f"{_subj(quote_no)} 的額外支出 {label} 已核准")
            XN.fire("approved", conn, row, requester=requester or "", payable=EF.is_payable_kind(_col(row, "kind", "") or ""))
            PC.fire(exp_id)                                      # 最終核准 ⇒ 有預定付款日就建「付款待辦」
            notify_module_activity("案件管理", "額外支出核准", display, f"{quote_no or '無案件'}｜{label}",
                                   f"case-management.html?q={quote_no}")
        _audit(_tok(authorization), "extra_expense.approve", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} {label} 第 {ct + 1} 層核准 → {status}", {"tier": ct + 1, "status": status, **_asum(row)})
        return {"ok": True, "status": status, "currentTier": appr["currentTier"]}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/reject")
def reject_extra_expense(quote_no: str, exp_id: int, body: dict = Body(default={}),
                         authorization: str = Header(None)):
    """駁回 → 回到「已駁回」，填寫人可以改完再送一次。

    刻意不是直接刪掉：駁回通常是「金額或說明要修」，不是「這筆支出不存在」。
    """
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
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
            _notify(requester, "extra_expense_rejected", str(exp_id), quote_no or "無案件",
                    f"{_subj(quote_no)} 的額外支出 {label} 已被駁回"
                    + (f"：{reason}" if reason else ""))
        XN.fire("returned", conn, row, requester=requester or "", reason=reason)
        _audit(_tok(authorization), "extra_expense.reject", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} {label} 被駁回" + (f"：{reason}" if reason else ""), {"reason": reason, **_asum(row)})
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


def _guard_files_editable(row, kind=None):
    """附件是否還能動。已核准就一律擋，訊息要明確指向變更申請這條路——
    只回一句「不可修改」的話，使用者只會以為系統壞了。
    例外（2026-09-27 使用者裁示請款流程）：已核准後**只有「發票」類可以直接補上傳**（留稽核紀錄）；刪除與其他類照舊上鎖。"""
    if row["status"] == VOIDED_STATUS:
        raise HTTPException(409, "這筆額外支出已作廢，附件不可再更動")
    if row["status"] == "已核准" and kind != "invoice":
        raise HTTPException(
            409, "這筆額外支出已核准，附件已上鎖。發票可由填寫人、管理員或出納補上傳；要補其他憑證請按「編輯」提出變更申請，"
                 "新附件會在簽核通過後一併生效")


#: 附件可增刪的狀態（第44班使用者裁示）：草稿／待審核（含簽核中）／已駁回。核准後上鎖（只剩發票補上傳）；作廢保留檔案不可動。
FILES_MUTABLE_STATUSES = ("草稿", "待審核", "簽核中", "已駁回")


def _guard_files_mutation(row, user: dict, kind=None):
    """上傳／刪除附件的權限＋狀態：只有申請人本人或管理員能動；簽核人（非申請人）唯讀。
    狀態規則同 `_guard_files_editable`（核准後只放行發票補上傳，由呼叫端另查出納／填寫人）。"""
    _guard_files_editable(row, kind)
    if row["status"] in FILES_MUTABLE_STATUSES and not _can_modify(row, user):
        raise HTTPException(403, "只有申請人本人或管理員可以新增或刪除附件（簽核人僅能檢視）")


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/files", status_code=201)
async def upload_extra_expense_files(quote_no: str, exp_id: int,
                                     files: List[UploadFile] = File(...),
                                     kind: str = Form("other"),
                                     authorization: str = Header(None)):
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    kind = (kind or "other").strip()
    if kind not in FILE_KINDS:
        raise HTTPException(400, "附件分類只能是 invoice（發票）或 other（其他）")
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
        _guard_files_mutation(row, user, kind)
        after_approval = row["status"] == "已核准"
        # 「或出納」與 PATCH …/dates 同構：上面 _guard_case 先擋 ⇒ 出納也必須看得到這個案件（純出納＝404）。
        # 2026-09-28 00:58 使用者裁示維持現狀（CORE-SPEC 請款流程），不另開出納補發票的路。
        if after_approval and not (_can_modify(row, user) or user_has_module(user, "cashier")):
            raise HTTPException(403, "核准後補發票限填寫人本人、管理員或財務角色")
        new_files = await save_document_files(
            "case_extra_expense", f"{quote_no}_{exp_id}", files,
            user.get("display_name") or user["username"], existing_count=len(_files_of(row)))     # 每張單據最多 10 個（helpers/uploads UPLOAD_LIMITS_BY_SUBFOLDER）
        for f in new_files:
            f["kind"] = kind
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
    if after_approval:                                   # 核准後補發票：另一個稽核動作，查得到是誰、何時補的
        _audit(_tok(authorization), "extra_expense.invoice_after_approval", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} 核准後補上傳發票 {len(new_files)} 個："
               + "、".join(str(f.get("filename") or f.get("id") or "") for f in new_files))
    else:
        _audit(_tok(authorization), "extra_expense.upload_files", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} 上傳 {len(new_files)} 個附件（{'發票' if kind == 'invoice' else '其他'}）")
    return {"ok": True, "added": len(new_files), "files": new_files}


@router.delete("/api/quotations/{quote_no}/extra-expenses/{exp_id}/files/{file_id}")
def delete_extra_expense_file(quote_no: str, exp_id: int, file_id: str,
                              authorization: str = Header(None)):
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
        _guard_files_mutation(row, user)
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
    _audit(_tok(authorization), "extra_expense.delete_file", *_audit_target(quote_no, exp_id),
           f"{quote_no or '無案件'} 額外支出 #{exp_id} 刪除附件")
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


def _proposal_from(body: ExtraExpenseIn, keep_files: list, row=None) -> dict:
    """把送進來的欄位組成提議內容。金額一律後端算（同 `_recalc()` 的理由）。

    費用單據（kind≠''）：明細／data／部門／收款人也進提議（否則已核准後的變更申請會**靜默丟掉**這些欄位）；
    金額＝Σ 明細（後端重算）。舊版列（kind=''）提議不帶這些鍵 ⇒ 套用時不動它們。"""
    extra = {}
    if row is not None and (_col(row, "kind", "") or ""):
        lines, total = EF.normalize_lines(body.lines if body.lines is not None else _jlist(row, "lines_json"))
        data = EF.normalize_data(body.data, _jcol(row, "data_json"))
        extra = {"lines": lines, "data": data, "departmentId": EF.department_of(data, body.departmentId),
                 "payeeType": body.payeeType, "payeeName": (body.payeeName or "").strip(),
                 "payeeBank": (body.payeeBank or "").strip(), "payeeAccount": (body.payeeAccount or "").strip(),
                 "totalFromLines": total}
    return {**extra,
        "category":      body.category or "其他",
        "description":   (body.description or "").strip() or (row["description"] if extra else ""),
        "qty":           float(body.qty or 0),
        "unit":          (body.unit or "").strip(),
        "unitCost":      float(body.unitCost or 0),
        "totalCost":     extra["totalFromLines"] if extra else _recalc(body),
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
    _has_lines = "lines" in change                      # 費用單據的提議才有；舊版提議沒有 ⇒ 不動明細／data／收款人
    if _has_lines:
        clean_lines, total = EF.normalize_lines(change.get("lines"))          # 金額以明細後端重算為準，不信提議裡存的 totalCost
    merged_files = _files_of(row) + (change.get("addFiles") or [])

    appr = _jcol(row, "approval_json")
    appr.setdefault("changeHistory", []).append({
        "at": now, "byDisplay": actor_display,
        "requestedByDisplay": change.get("requestedByDisplay") or "",
        "from": {"description": row["description"], "totalCost": row["total_cost"],
                 "qty": row["qty"], "unitCost": row["unit_cost"],
                 "category": row["category"], "expenseDate": row["expense_date"],
                 "docNo": row["doc_no"], "note": row["note"],
                 "payerName": row["payer_name"],
                 **({"lines": _jlist(row, "lines_json"), "data": _jcol(row, "data_json"),
                     "payeeName": _col(row, "payee_name", ""), "departmentId": _col(row, "department_id", None)}
                    if _has_lines else {})},
        "to":   {"description": change.get("description"), "totalCost": total,
                 "qty": change.get("qty"), "unitCost": change.get("unitCost"),
                 "category": change.get("category"), "expenseDate": change.get("expenseDate"),
                 "docNo": change.get("docNo"), "note": change.get("note"),
                 "payerName": change.get("payerName"),
                 **({"lines": clean_lines, "data": change.get("data"),
                     "payeeName": change.get("payeeName"), "departmentId": change.get("departmentId")}
                    if _has_lines else {})},
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
    if _has_lines:                                      # 費用單據：明細／data／部門／收款人一併覆寫（未知鍵原樣保留）
        conn.execute(
            "UPDATE case_extra_expenses SET lines_json=?, data_json=?, department_id=?, "
            " payee_type=?, payee_name=?, payee_bank=?, payee_account=? WHERE id=? AND quote_no=?",
            (EF.dumps_lines(clean_lines), json.dumps(EF.normalize_data(change.get("data"), {}), ensure_ascii=False),
             change.get("departmentId"), change.get("payeeType") or "", change.get("payeeName") or "",
             change.get("payeeBank") or "", change.get("payeeAccount") or "", exp_id, quote_no))
    # MONEY-FLOWS §9 L11：**已付款**的額外支出經變更申請改了金額 ⇒ 實付與新應付不一致，必須重走出納的差額審核，
    # 不可以讓已付款金額被悄悄改掉（原本不回審核，E11b 用新 total／舊 remit_actual 產生差額行）。
    # 做法＝沿用既有差額審核：`remit_review='pending'`；核可／退回都在出納頁（核可 ⇒ 報表不變、總帳下次執行才出 E11b；
    # 退回 ⇒ 回待付款）。下游效應：營運報表現金口徑標「差額待審核」（`remitPending`）；總帳 E11b 待審核期間不產生。
    _paid = (row["paid_date"] or "") if "paid_date" in row.keys() else ""
    _actual = row["remit_actual"] if "remit_actual" in row.keys() else None
    if _paid and _actual is not None and abs(float(_actual) - total) > 0.005 and abs(float(row["total_cost"] or 0) - total) > 0.005:
        _note = "變更申請改了金額（原應付 %g → %g），實付 %g，請重新審核" % (float(row["total_cost"] or 0), total, float(_actual))
        conn.execute("UPDATE case_extra_expenses SET remit_review='pending', remit_review_by='', remit_review_at='', "
                     "remit_review_note=? WHERE id=? AND quote_no=?", (_note, exp_id, quote_no))
    return total


@router.put("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request")
def upsert_change_request(quote_no: str, exp_id: int, body: ExtraExpenseIn = Body(...),
                          authorization: str = Header(None)):
    """建立／更新變更申請草稿。只有**已核准**的項目才走這條；草稿與已駁回本來就
    可以直接編輯（`update_extra_expense()`），不需要繞一圈。"""
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    _validate(body)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
        if row["status"] != "已核准":
            raise HTTPException(409, f"「{row['status']}」狀態請直接編輯，不需要提變更申請")
        if not (_col(row, "kind", "") or ""):
            _require_desc(body)
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以提出變更申請")
        cs = _col(row, "change_status", "") or ""
        if cs not in CHANGE_EDITABLE:
            raise HTTPException(409, f"已有一筆變更申請在「{cs}」，請先完成或撤銷它")

        # 已駁回後再修改：沿用同一批待核准附件，不要讓使用者重傳一次
        proposal = _proposal_from(body, (_change_of(row).get("addFiles") or []), row)
        if "lines" in proposal:                                 # 32-S2：變更申請的明細同樣驗品項連結（核准後的單據不能繞過）
            proposal["lines"], _ = PI.check_lines(conn, quote_no, row["kind"], proposal["lines"], exclude_id=exp_id)
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "UPDATE case_extra_expenses SET change_status='草稿', change_json=?, "
            "change_approval_json='{}' WHERE id=? AND quote_no=?",
            (json.dumps(proposal, ensure_ascii=False), exp_id, quote_no))
        conn.commit()
        _audit(_tok(authorization), "extra_expense.change_draft", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} 變更申請草稿"
               f"（NT$ {float(row['total_cost'] or 0):,.0f} → NT$ {proposal['totalCost']:,.0f}）")
        return {"ok": True, "changeStatus": "草稿", "totalCost": proposal["totalCost"],
                "updatedAt": now}
    finally:
        conn.close()


@router.delete("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request")
def cancel_change_request(quote_no: str, exp_id: int, authorization: str = Header(None)):
    """撤銷變更申請（草稿或已駁回）。待核准附件的實體檔案一併刪除。
    送審中的要撤銷請先請簽核人駁回——否則簽核人手上的東西會憑空消失。"""
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
        cs = _col(row, "change_status", "") or ""
        if cs not in ("草稿", "已駁回"):
            raise HTTPException(409, f"「{cs or '無'}」狀態的變更申請不可撤銷")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以撤銷變更申請")
        _discard_pending_files(quote_no, exp_id, _change_of(row))
        _clear_change(conn, quote_no, exp_id)
        conn.commit()
        _audit(_tok(authorization), "extra_expense.change_cancel", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} 撤銷變更申請")
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
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
        cs = _col(row, "change_status", "") or ""
        if cs not in ("草稿", "已駁回"):
            raise HTTPException(409, "請先按「編輯」建立變更申請草稿，再上傳附件")
        if not _can_modify(row, user):
            raise HTTPException(403, "只有填寫人本人或管理員可以上傳變更申請附件")
        display = user.get("display_name") or user["username"]
        change = _change_of(row)
        new_files = await save_document_files(
            "case_extra_expense", f"{quote_no}_{exp_id}", files, display,
            existing_count=len(_files_of(row)) + len(change.get("addFiles") or []))               # 核准後會併進正式附件 ⇒ 兩邊合計算
        change["addFiles"] = (change.get("addFiles") or []) + new_files
        conn.execute("UPDATE case_extra_expenses SET change_json=? WHERE id=? AND quote_no=?",
                     (json.dumps(change, ensure_ascii=False), exp_id, quote_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "extra_expense.change_upload_files", *_audit_target(quote_no, exp_id),
           f"{quote_no or '無案件'} 額外支出 #{exp_id} 變更申請上傳 {len(new_files)} 個待核准附件")
    return {"ok": True, "added": len(new_files), "files": new_files}


@router.delete("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/files/{file_id}")
def delete_change_request_file(quote_no: str, exp_id: int, file_id: str,
                               authorization: str = Header(None)):
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
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
    _audit(_tok(authorization), "extra_expense.change_delete_file", *_audit_target(quote_no, exp_id),
           f"{quote_no or '無案件'} 額外支出 #{exp_id} 刪除變更申請待核准附件")
    return {"ok": True}


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/submit")
def submit_change_request(quote_no: str, exp_id: int, authorization: str = Header(None)):
    """送審變更申請。簽核流程沿用同一個文件類型 `extra_expense`（簽核設定頁不必
    多一個分頁——「改一筆已核准的支出」跟「新增一筆支出」該由同一批人把關）。

    沒有設定任何簽核層時直接套用，理由同 `submit_extra_expense()`。"""
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
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
        if "lines" in change:                                   # 費用單據的變更申請：同樣在送審當下驗類別、寫代碼／科目快照
            change["lines"] = EF.prepare_submit(conn, change["lines"])
            begin_write(conn)
            change["lines"], _ = PI.check_lines(conn, quote_no, row["kind"], change["lines"], exclude_id=exp_id, require_reason=True)
            conn.execute("UPDATE case_extra_expenses SET change_json=? WHERE id=? AND quote_no=?",
                         (json.dumps(change, ensure_ascii=False), exp_id, quote_no))
        label = f"{change.get('description')}（NT$ {old_total:,.0f} → NT$ {new_total:,.0f}）"

        if not tiers:
            change["requestedByDisplay"] = display
            total = _apply_change(conn, row, change, display, now)
            conn.commit()
            _audit(_tok(authorization), "extra_expense.change_auto_apply", *_audit_target(quote_no, exp_id),
                   f"{quote_no or '無案件'} 額外支出 #{exp_id} {label}：未設定簽核層，變更直接生效", _asum(row))
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
            _notify(a["username"], "extra_expense_change_request", str(exp_id), quote_no or "無案件",
                    f"{_subj(quote_no)} 的支出申請變更 {label} 需要您簽核")
        _audit(_tok(authorization), "extra_expense.change_submit", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} 變更申請 {label} 送審", {"tierCount": len(tiers), **_asum(row)})
        return {"ok": True, "changeStatus": "待審核", "tierCount": len(tiers)}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/approve")
def approve_change_request(quote_no: str, exp_id: int, body: dict = Body(default={}),
                           authorization: str = Header(None)):
    """核准當層；全部層都過了才真的套用（`_apply_change()`）。在那之前本體的金額
    完全不動——這正是使用者要的「原核准金額不動，核准後才生效」。"""
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
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
                _notify(requester, "extra_expense_change_approved", str(exp_id), quote_no or "無案件",
                        f"{_subj(quote_no)} 的支出申請變更 {label} 已核准並生效")
            notify_module_activity("案件管理", "支出申請變更核准", display, f"{quote_no or '無案件'}｜{label}",
                                   f"case-management.html?q={quote_no}")
            _audit(_tok(authorization), "extra_expense.change_approve", *_audit_target(quote_no, exp_id),
                   f"{quote_no or '無案件'} 額外支出 #{exp_id} 變更 {label} 第 {ct + 1} 層核准 → 已生效", {"tier": ct + 1, "applied": True, **_asum(row)})
            return {"ok": True, "changeStatus": "", "applied": True, "totalCost": applied_total}

        conn.execute(
            "UPDATE case_extra_expenses SET change_status='簽核中', change_approval_json=? "
            "WHERE id=? AND quote_no=?",
            (json.dumps(appr, ensure_ascii=False), exp_id, quote_no))
        conn.commit()
        for a in (tiers[appr["currentTier"]].get("approvers") or []):
            _notify(a["username"], "extra_expense_change_request", str(exp_id), quote_no or "無案件",
                    f"{_subj(quote_no)} 的支出申請變更 {label} 需要您簽核")
        _audit(_tok(authorization), "extra_expense.change_approve", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} 變更 {label} 第 {ct + 1} 層核准 → 簽核中", {"tier": ct + 1, "applied": False, **_asum(row)})
        return {"ok": True, "changeStatus": "簽核中", "currentTier": appr["currentTier"]}
    finally:
        conn.close()


@router.post("/api/quotations/{quote_no}/extra-expenses/{exp_id}/change-request/reject")
def reject_change_request(quote_no: str, exp_id: int, body: dict = Body(default={}),
                          authorization: str = Header(None)):
    """駁回變更申請 → 回到「已駁回」，申請人可以改完再送一次或整個撤銷。
    本體的金額從頭到尾沒被動過，所以駁回不需要回滾任何東西。"""
    quote_no = _qn(quote_no)        # 哨兵路徑段「-」＝無案件（quote_no 欄位存 ''）
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        row = _load(conn, quote_no, exp_id, user)
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
            _notify(requester, "extra_expense_change_rejected", str(exp_id), quote_no or "無案件",
                    f"{_subj(quote_no)} 的支出申請變更 {label} 已被駁回"
                    + (f"：{reason}" if reason else ""))
        _audit(_tok(authorization), "extra_expense.change_reject", *_audit_target(quote_no, exp_id),
               f"{quote_no or '無案件'} 額外支出 #{exp_id} 變更申請 {label} 被駁回" + (f"：{reason}" if reason else ""), {"reason": reason, **_asum(row)})
        return {"ok": True, "changeStatus": "已駁回"}
    finally:
        conn.close()
