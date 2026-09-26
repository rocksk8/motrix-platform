"""請款單：案件款項明細（quotations.data_json.caseRecord.payment.items[]，本身
不是獨立資料表）之外，另外提供一種可走簽核流程、對內/對客戶要款用的獨立單據。

跟 routers/invoice_vouchers.py 是同一套設計（凍結快照＋依剩餘可請款額度防
超收＋BEGIN IMMEDIATE 防同時超額），scope='amount'（自訂金額，可搭配
ratio_pct 換算）或 scope='items'（自訂品項+數量）。差異只在請款單多了
terms_json（條款，比照報價單「報價條件」四個可自由編輯欄位，建立當下預帶入
該報價單當時的條款內容，之後可自行修改，不回寫報價單）。

簽核流程（system_settings key: unified_approval_flow，與報價單／開票申請
憑據／出貨單共用同一組設定）機制為 tiers 依序簽核；核准即定稿，不像承攬商
匯款申請多一個「已匯款」財務結案節點——請款單本身就是最終文件。

客戶/案件/款項明細於建立當下寫入 snapshot_json 凍結快照，理由同
routers/invoice_vouchers.py：已送出審核的請款單不應該因為之後有人編輯報價單
款項明細而回頭改變內容。
"""
import json
import logging
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Body, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_db, next_entity_code, spawn_bg_thread
from core.txn import begin_write, write_txn
from helpers import (
    _require_user, _tok, _audit, _notify, _purge_notifications,
    notify_module_activity, notify_payment_request_submitted, notify_payment_request_next_tier,
    notify_payment_request_approved, notify_payment_request_returned,
    push_event_for_payment_request,
    active_tiers as _active_tiers, current_tier_idx as _current_tier_idx,
    setting_to_active_tiers as _setting_to_active_tiers,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    cascade_self_tiers, notify_org_chain_notice,
    UnresolvedManagerError, resolve_active_flow_setting,
    guard_case_access, require_any_module,

    can_see_financial, is_document_approver,
)
from pdf_gen import generate_payment_request_pdf_bytes, _generate_payment_request_pdf
from helpers.errors import trace_id
# X-VAT（2026-09-26）：金額一律四捨五入（內建 round() 是銀行家捨入：.5 取偶數）。守門 test_legal_amount_rounding_guard
from helpers.legal_params import round_half_up

router = APIRouter()
logger = logging.getLogger(__name__)

def _guard_voucher(conn, row, user):
    """單據層級守門（2026-09-13 模組權限稽核第四輪）。

    先前 `GET /{request_no}`、PDF 下載與檔案上傳/刪除都只要求登入，而單號是可預測的
    （前綴＋年月＋流水號），等於任何已登入帳號都能把別人案件的單據與金額撈出來。

    兩道：
    1. **案件層**——比照其他每案端點（`guard_case_access`）：案件業務／協作者／
       具案件管理模組／本單簽核人（含代理人）。
    2. **金額層**——`can_see_financial()`（使用者裁示：viewer／engineer 不該看到
       金額）。**本單簽核人例外**：看不到金額就沒辦法判斷該不該簽，擋他等於讓
       簽核流程停擺。
    """
    # 找不到母案件時不要變成 404：單據本身存在、只是母案件被刪或資料異常，
    # 對使用者顯示「報價單不存在」只會更難查。退回模組層級判斷。
    if conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (row["quote_no"],)).fetchone():
        guard_case_access(conn, row["quote_no"], user,
                          allow_module="case_manage", allow_approver=True)
    else:
        require_any_module(user, ('case_manage', 'finance', 'cashier', 'quotation'), "請款單")
    if not can_see_financial(user) and not is_document_approver(row["data_json"], user, conn):
        try:
            conn.close()
        except Exception:
            pass
        raise HTTPException(403, "此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）")


def _visible_rows(rows, user, conn):
    """清單過濾：沒有財務可視權的人，只看得到「自己要簽的那幾張」。

    直接整支 403 會讓非管理員的簽核人連簽核佇列都打不開（他們正是要在那裡看到
    待簽單據）；整批放行又違背「viewer／engineer 不該看到金額」。折衷是過濾。
    """
    if can_see_financial(user):
        return rows
    return [r for r in rows if is_document_approver(r["data_json"], user, conn)]



# ── Models ────────────────────────────────────────────────────────────────────

# 「款項類別」：客戶端請款單 PDF 與整頁編輯介面上手動選擇的業務語意分類
# （2026-08-24），跟 scope（amount/items，決定金額計算方式）並存、互不影響。
PAYMENT_STAGES = {
    "full":       "全額",
    "deposit":    "訂金款",
    "delivery":   "交貨款",
    "acceptance": "驗收款",
    "final":      "尾款",
}

class RequestItemIn(BaseModel):
    itemId: int
    qty:    float
    amount: float

class TermsIn(BaseModel):
    paymentTerms:    Optional[str] = ''
    deliveryTerms:   Optional[str] = ''
    acceptanceTerms: Optional[str] = ''
    warrantyTerms:   Optional[str] = ''

class RequestCreateIn(BaseModel):
    quote_no:  str
    scope:     str                                    # 'amount'（自訂金額）| 'items'（自訂品項+數量）
    stage:     str                                     # 'full'/'deposit'/'delivery'/'acceptance'/'final'，見 PAYMENT_STAGES
    amount:    Optional[float] = None                 # scope='amount' 且未帶 ratio_pct 時必填
    ratio_pct: Optional[float] = None                  # scope='amount' 的輸入捷徑：amount = quoteTotal * ratio_pct/100
    items:     Optional[List[RequestItemIn]] = None    # scope='items' 時必填
    terms:     Optional[TermsIn] = None                # 未帶則沿用報價單目前條款內容（見 _quote_default_terms）

class RequestUpdateIn(BaseModel):
    """整頁編輯介面（payment-request-form.html）用的草稿更新——跟 RequestCreateIn
    同一套欄位語意，差別只在 quote_no 已固定在既有列不可改，故不收這個欄位。"""
    scope:     str
    stage:     str
    amount:    Optional[float] = None
    ratio_pct: Optional[float] = None
    items:     Optional[List[RequestItemIn]] = None
    terms:     Optional[TermsIn] = None


# ── Approval tier helpers（純邏輯部分共用 helpers/tiered_approval.py，見上方 import）──


def _require_admin(user: dict):
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")


def _request_public(row, include_snapshot: bool = True) -> dict:
    d = dict(row)
    snap = json.loads(d.get("snapshot_json") or "{}")
    approval = (json.loads(d.get("data_json") or "{}") or {}).get("approval") or {}
    amount = float(d.get("amount") or 0)
    out = {
        "id":            d["id"],
        "requestNo":     d["request_no"],
        "quoteNo":       d["quote_no"],
        "scope":         d["scope"] or "amount",
        "stage":         d.get("stage") or "",
        "stageLabel":    PAYMENT_STAGES.get(d.get("stage") or "", ""),
        "customerName":  snap.get("customerName", ""),
        "status":        d["status"] or "草稿",
        "amount":        amount,          # 含稅
        "totalAmount":   amount,          # 別名，沿用開票申請憑據既有前端欄位命名習慣
        "pretaxAmount":  snap.get("pretaxAmount", 0),
        "taxAmount":     snap.get("taxAmount", 0),
        "ratioPct":      d.get("ratio_pct") or 0,
        "selectedItems": snap.get("selectedItems") or [],
        "terms":         json.loads(d.get("terms_json") or "{}"),
        "exportCount":   d.get("export_count") or 0,
        "exportLog":     json.loads(d.get("export_log") or "[]"),
        "approval":      approval,
        "createdBy":     d.get("created_by") or "",
        "createdAt":     d.get("created_at") or "",
        "updatedAt":     d.get("updated_at") or "",
    }
    if include_snapshot:
        out["snapshot"] = snap
    return out


def _quote_remaining(conn, quote_no: str, exclude_request_no: Optional[str] = None):
    """這張報價單目前的請款額度使用狀況：合約總額（含稅）、未稅總額、已請款
    金額（含稅，含草稿——草稿就鎖額度，跟 invoice_vouchers 同一套設計避免同時
    建立造成超額），剩餘可請款金額（含稅）、剩餘比例（%），以及每個報價品項
    各自的已請款數量／剩餘數量。查無報價單回傳 None。

    exclude_request_no：整頁編輯介面（payment-request-form.html）編輯既有草稿
    時，該草稿自己已佔用的額度不該被算進「已請款」，否則使用者會看到自己這張
    草稿把自己的剩餘額度吃掉——排除自己之後才是「除了這張草稿以外，還剩多少
    可以請款」，可安全再調整到 remaining + 自己原本的金額。"""
    q = conn.execute("SELECT total, pretax, data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not q:
        return None
    data = json.loads(q["data_json"] or "{}")
    quote_total = float(q["total"] or 0)
    quote_pretax = float(q["pretax"] or 0) or quote_total

    rows = conn.execute(
        "SELECT request_no, amount, snapshot_json FROM payment_requests WHERE quote_no=?", (quote_no,)
    ).fetchall()
    if exclude_request_no:
        rows = [r for r in rows if r["request_no"] != exclude_request_no]
    requested_amount = sum(float(r["amount"] or 0) for r in rows)

    qty_used = {}
    for r in rows:
        snap = json.loads(r["snapshot_json"] or "{}")
        for it in (snap.get("selectedItems") or []):
            iid = it.get("itemId")
            qty_used[iid] = qty_used.get(iid, 0) + float(it.get("qty", 0) or 0)

    items_info = []
    for it in (data.get("items") or []):
        if it.get("type") == "header":
            continue
        iid = it.get("id")
        item_qty = float(it.get("qty", 0) or 0)
        used = qty_used.get(iid, 0)
        items_info.append({
            "itemId":       iid,
            "description":  it.get("description", ""),
            "brand":        it.get("brand", ""),
            "unit":         it.get("unit", ""),
            "unitPrice":    it.get("unitPrice", 0),
            "qty":          item_qty,
            "requestedQty": used,
            "remainingQty": item_qty - used,
        })

    remaining_amount = quote_total - requested_amount
    return {
        "quoteTotal":       quote_total,
        "quotePretax":      quote_pretax,
        "requestedAmount":  requested_amount,
        "remainingAmount":  remaining_amount,
        "remainingRatioPct": (remaining_amount / quote_total * 100) if quote_total > 0 else 0,
        "items":            items_info,
    }


def _quote_default_terms(data: dict) -> dict:
    """建立請款單當下，預帶入該報價單目前的條款內容（比照 quotation-form.html
    的四個「報價條件」欄位）——請款單存自己獨立的一份（terms_json），之後可
    自由修改，不回寫報價單。"""
    return {
        "paymentTerms":    data.get("paymentTerms", "") or "",
        "deliveryTerms":   data.get("deliveryTerms", "") or "",
        "acceptanceTerms": data.get("acceptanceTerms", "") or "",
        "warrantyTerms":   data.get("warrantyTerms", "") or "",
    }


def _calc_scope_amount(data: dict, remaining: dict, quote_total: float, quote_pretax: float,
                        scope: str, ratio_pct_in: Optional[float], amount_in: Optional[float],
                        items_in: Optional[List[RequestItemIn]]):
    """建立／更新請款單共用的金額計算與驗證：回傳
    (request_amount, pretax_amount, tax_amount, ratio_pct, selected_items_snapshot)。
    scope='amount' 用 ratio_pct_in 或 amount_in 換算；scope='items' 依 items_in 逐項核對
    剩餘可請款數量並加總。驗證失敗一律丟 HTTPException，呼叫端不須另外處理錯誤訊息。"""
    if scope == "amount":
        if ratio_pct_in:
            if ratio_pct_in <= 0 or ratio_pct_in > 100:
                raise HTTPException(400, "請款比例需介於 0～100 之間")
            ratio_pct = ratio_pct_in
            request_amount = round_half_up(quote_total * ratio_pct / 100)
        elif amount_in:
            request_amount = amount_in
            ratio_pct = round_half_up(request_amount / quote_total * 100, 100) / 100 if quote_total > 0 else 0
        else:
            raise HTTPException(400, "請輸入請款金額或請款比例")
        if request_amount <= 0:
            raise HTTPException(400, "請款金額需大於 0")
        pretax_amount = round_half_up(request_amount * quote_pretax / quote_total) if quote_total > 0 else request_amount
        selected_items_snapshot = []
    else:
        if not items_in:
            raise HTTPException(400, "請至少選擇一項品項")
        quote_items_by_id = {it.get("id"): it for it in (data.get("items") or []) if it.get("type") != "header"}
        qty_remaining_by_id = {it["itemId"]: it["remainingQty"] for it in remaining["items"]}
        pretax_amount = 0.0
        selected_items_snapshot = []
        for line in items_in:
            src = quote_items_by_id.get(line.itemId)
            if not src:
                raise HTTPException(400, f"找不到品項 id={line.itemId}")
            if line.qty <= 0:
                raise HTTPException(400, f"品項「{src.get('description','')}」數量需大於 0")
            avail = qty_remaining_by_id.get(line.itemId, 0)
            if line.qty > avail + 1e-9:
                raise HTTPException(409, f"品項「{src.get('description','')}」剩餘可請款數量不足（剩餘 {avail:g}）")
            if line.amount <= 0:
                raise HTTPException(400, f"品項「{src.get('description','')}」金額需大於 0")
            pretax_amount += line.amount
            selected_items_snapshot.append({
                "itemId":      line.itemId,
                "description": src.get("description", ""),
                "brand":       src.get("brand", ""),
                "unit":        src.get("unit", ""),
                "unitPrice":   src.get("unitPrice", 0),
                "qty":         line.qty,
                "amount":      line.amount,   # 未稅（比照報價單品項金額慣例）
            })
        request_amount = round_half_up(pretax_amount * quote_total / quote_pretax) if quote_pretax > 0 else pretax_amount
        ratio_pct = round_half_up(request_amount / quote_total * 100, 100) / 100 if quote_total > 0 else 0

    tax_amount = request_amount - pretax_amount
    return request_amount, pretax_amount, tax_amount, ratio_pct, selected_items_snapshot


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/payment-requests")
def list_payment_requests(quote_no: Optional[str] = None, authorization: str = Header(None)):
    # 2026-09-13（模組權限稽核）：帶 quote_no 就是「讀某一張案件的請款單」——
    # `quote_no` 可列舉，先前只要求登入等於任何人都撈得到別人案件的單據與金額。
    # 不帶 quote_no 是跨案件總覽，改為管理員或具相關模組的人才看得到。
    user = _require_user(authorization)
    conn = get_db()
    if quote_no:
        guard_case_access(conn, quote_no, user, allow_module="case_manage")
    else:
        # `quotation` 也要收：簽核佇列（模組 quotation）就是用這支載入待簽的單據
        require_any_module(user, ('case_manage', 'finance', 'cashier', 'quotation'), "請款單")
    if quote_no:
        rows = conn.execute(
            "SELECT * FROM payment_requests WHERE quote_no=? ORDER BY created_at DESC", (quote_no,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM payment_requests ORDER BY created_at DESC LIMIT 200").fetchall()
    rows = _visible_rows(rows, user, conn)
    conn.close()
    return [_request_public(r, include_snapshot=False) for r in rows]


@router.get("/api/payment-requests/remaining")
def get_payment_request_remaining(quote_no: str, exclude: Optional[str] = None, authorization: str = Header(None)):
    """建立/編輯請款單前，前端要顯示「剩餘可請款金額／比例／品項數量」用——必須
    註冊在 /{request_no} 之前，否則 FastAPI 會把 'remaining' 當成 request_no 吃掉。

    exclude：整頁編輯介面編輯既有草稿時傳入該草稿自己的 request_no，排除自己
    已佔用的額度（見 _quote_remaining 說明）。"""
    user = _require_user(authorization)
    conn = get_db()
    guard_case_access(conn, quote_no, user, allow_module="case_manage")
    info = _quote_remaining(conn, quote_no, exclude_request_no=exclude)
    conn.close()
    if info is None:
        raise HTTPException(404, "找不到關聯的報價單")
    return info


@router.get("/api/payment-requests/{request_no}")
def get_payment_request(request_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM payment_requests WHERE request_no=?", (request_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "單據不存在")
    _guard_voucher(conn, row, user)
    conn.close()
    if not row:
        raise HTTPException(404, f"請款單 {request_no} 不存在")
    return _request_public(row)


@router.post("/api/payment-requests", status_code=201)
def create_payment_request(body: RequestCreateIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    if body.scope not in ("amount", "items"):
        raise HTTPException(400, "scope 必須為 amount 或 items")
    if body.stage not in PAYMENT_STAGES:
        raise HTTPException(400, "請選擇請款範圍")

    conn = get_db()
    # BEGIN IMMEDIATE：把「算剩餘可請款額度」跟「寫入新申請」鎖進同一個交易，
    # 避免兩個近乎同時送出的請求都通過超額檢查、合計超過報價單總額。
    with write_txn(conn):   # 拿寫鎖（helpers.quotations.begin_write）；區塊內任何例外 ⇒ rollback＋關連線（不留寫鎖）
        q = conn.execute(
            "SELECT customer_name, project_name, total, pretax, data_json FROM quotations WHERE quote_no=?",
            (body.quote_no,)
        ).fetchone()
        if not q:
            conn.close()
            raise HTTPException(404, "找不到關聯的報價單")
        data = json.loads(q["data_json"] or "{}")
        quote_total  = float(q["total"] or 0)
        quote_pretax = float(q["pretax"] or 0) or quote_total

        customer_id = data.get("customerId")
        customer_tax_id = ""
        if customer_id:
            crow = conn.execute("SELECT tax_id FROM customers WHERE id=?", (customer_id,)).fetchone()
            customer_tax_id = (crow["tax_id"] if crow else "") or ""

        remaining = _quote_remaining(conn, body.quote_no)
        remaining_amount = remaining["remainingAmount"]

        # 報價單品項參考（僅供顯示用，刻意排除 cost/margin/unitPriceOverride 等
        # 內部機密欄位——比照 invoice_vouchers.py 同樣的理由，這份文件可能會給客戶看）。
        quote_items_snapshot = [
            {
                "description": it.get("description", ""),
                "brand":       it.get("brand", ""),
                "qty":         it.get("qty", ""),
                "unit":        it.get("unit", ""),
                "unitPrice":   it.get("unitPrice", 0),
                "amount":      it.get("amount", 0),
                "notes":       it.get("notes", ""),
            }
            for it in (data.get("items") or [])
            if it.get("type") != "header"
        ]

        try:
            request_amount, pretax_amount, tax_amount, ratio_pct, selected_items_snapshot = _calc_scope_amount(
                data, remaining, quote_total, quote_pretax, body.scope, body.ratio_pct, body.amount, body.items
            )
        except HTTPException:
            conn.close()
            raise

        if request_amount > remaining_amount + 1e-6:
            conn.close()
            raise HTTPException(409, f"超過剩餘可請款金額（剩餘 NT$ {remaining_amount:,.0f}）")

        snapshot = {
            "customerName":    q["customer_name"] or "",
            "customerTaxId":   customer_tax_id,
            "projectName":     q["project_name"] or "",
            "quoteItems":      quote_items_snapshot,
            "selectedItems":   selected_items_snapshot,
            "requestedAmount": request_amount,      # 含稅（＝ payment_requests.amount）
            "pretaxAmount":    round_half_up(pretax_amount),
            "taxAmount":       round_half_up(tax_amount),
        }
        terms = body.terms.model_dump() if body.terms else _quote_default_terms(data)

        now = datetime.now().isoformat()
        request_no = next_entity_code(conn, "payment_requests", "PR", code_col="request_no")
        conn.execute(
            "INSERT INTO payment_requests "
            "(request_no, quote_no, scope, stage, amount, ratio_pct, status, terms_json, snapshot_json, data_json, "
            "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (request_no, body.quote_no, body.scope, body.stage, request_amount, ratio_pct,
             "草稿", json.dumps(terms, ensure_ascii=False), json.dumps(snapshot, ensure_ascii=False), "{}",
             user["username"], now, now)
        )
        conn.commit()
        conn.close()
        _audit(_tok(authorization), "payment_request.create", "payment_request", request_no,
               f"{request_no}（{snapshot['customerName']}）")
        notify_module_activity("請款單", "建立", user.get("display_name") or user["username"],
                                f"{request_no}（{snapshot['customerName']}）", "case-management.html")
        return {"request_no": request_no, "created_at": now}


@router.put("/api/payment-requests/{request_no}")
def update_payment_request(request_no: str, body: RequestUpdateIn, authorization: str = Header(None)):
    """整頁編輯介面（payment-request-form.html）用：草稿狀態下可整筆改
    scope/stage/金額或品項/條款，取代原本只能改條款的 /terms 端點。跟建立
    端點共用 _calc_scope_amount 驗證邏輯與防超額檢查，差異只在剩餘額度計算要
    排除自己這張草稿目前已佔用的金額（見 _quote_remaining exclude_request_no）。"""
    user = _require_user(authorization)
    _require_admin(user)
    if body.scope not in ("amount", "items"):
        raise HTTPException(400, "scope 必須為 amount 或 items")
    if body.stage not in PAYMENT_STAGES:
        raise HTTPException(400, "請選擇請款範圍")

    conn = get_db()
    with write_txn(conn):   # 拿寫鎖（helpers.quotations.begin_write）；區塊內任何例外 ⇒ rollback＋關連線（不留寫鎖）
        row = conn.execute(
            "SELECT status, quote_no, terms_json FROM payment_requests WHERE request_no=?", (request_no,)
        ).fetchone()
        if not row:
            conn.close()
            raise HTTPException(404, "請款單不存在")
        if row["status"] != "草稿":
            conn.close()
            raise HTTPException(409, "僅草稿狀態可修改")
        quote_no = row["quote_no"]

        q = conn.execute(
            "SELECT customer_name, project_name, total, pretax, data_json FROM quotations WHERE quote_no=?",
            (quote_no,)
        ).fetchone()
        if not q:
            conn.close()
            raise HTTPException(404, "找不到關聯的報價單")
        data = json.loads(q["data_json"] or "{}")
        quote_total  = float(q["total"] or 0)
        quote_pretax = float(q["pretax"] or 0) or quote_total

        customer_id = data.get("customerId")
        customer_tax_id = ""
        if customer_id:
            crow = conn.execute("SELECT tax_id FROM customers WHERE id=?", (customer_id,)).fetchone()
            customer_tax_id = (crow["tax_id"] if crow else "") or ""

        remaining = _quote_remaining(conn, quote_no, exclude_request_no=request_no)
        remaining_amount = remaining["remainingAmount"]

        quote_items_snapshot = [
            {
                "description": it.get("description", ""),
                "brand":       it.get("brand", ""),
                "qty":         it.get("qty", ""),
                "unit":        it.get("unit", ""),
                "unitPrice":   it.get("unitPrice", 0),
                "amount":      it.get("amount", 0),
                "notes":       it.get("notes", ""),
            }
            for it in (data.get("items") or [])
            if it.get("type") != "header"
        ]

        try:
            request_amount, pretax_amount, tax_amount, ratio_pct, selected_items_snapshot = _calc_scope_amount(
                data, remaining, quote_total, quote_pretax, body.scope, body.ratio_pct, body.amount, body.items
            )
        except HTTPException:
            conn.close()
            raise

        if request_amount > remaining_amount + 1e-6:
            conn.close()
            raise HTTPException(409, f"超過剩餘可請款金額（剩餘 NT$ {remaining_amount:,.0f}）")

        snapshot = {
            "customerName":    q["customer_name"] or "",
            "customerTaxId":   customer_tax_id,
            "projectName":     q["project_name"] or "",
            "quoteItems":      quote_items_snapshot,
            "selectedItems":   selected_items_snapshot,
            "requestedAmount": request_amount,
            "pretaxAmount":    round_half_up(pretax_amount),
            "taxAmount":       round_half_up(tax_amount),
        }
        terms = body.terms.model_dump() if body.terms else json.loads(row["terms_json"] or "{}")

        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE payment_requests SET scope=?, stage=?, amount=?, ratio_pct=?, terms_json=?, "
            "snapshot_json=?, updated_at=? WHERE request_no=?",
            (body.scope, body.stage, request_amount, ratio_pct, json.dumps(terms, ensure_ascii=False),
             json.dumps(snapshot, ensure_ascii=False), now, request_no)
        )
        conn.commit()
        conn.close()
        _audit(_tok(authorization), "payment_request.update", "payment_request", request_no,
               f"{request_no}（{snapshot['customerName']}）")
        return {"ok": True, "amount": request_amount}


@router.delete("/api/payment-requests/{request_no}")
def delete_payment_request(request_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT status FROM payment_requests WHERE request_no=?", (request_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "請款單不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可刪除")
    conn.execute("DELETE FROM payment_requests WHERE request_no=?", (request_no,))
    conn.commit()
    conn.close()
    _purge_notifications(request_no, ['payment_request_approval_request', 'payment_request_approved',
                                       'payment_request_returned', 'approval_reminder'])
    _audit(_tok(authorization), "payment_request.delete", "payment_request", request_no, request_no)
    notify_module_activity("請款單", "刪除", user.get("display_name") or user["username"],
                            request_no, "case-management.html")
    return {"ok": True}


# ── 簽核流程 ──────────────────────────────────────────────────────────────────

@router.post("/api/payment-requests/{request_no}/submit")
def submit_payment_request(request_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT status, data_json, snapshot_json FROM payment_requests WHERE request_no=?", (request_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "請款單不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可送出審核")

    snap  = json.loads(row["snapshot_json"] or "{}")
    cname = snap.get("customerName") or ""
    d     = json.loads(row["data_json"] or "{}")
    now   = datetime.now().isoformat()

    flow_setting = resolve_active_flow_setting("payment_request")
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

    first_tier_usernames = []
    if active_tiers:
        for a in active_tiers[0].get("approvers") or []:
            _notify(a["username"], "payment_request_approval_request", request_no, request_no,
                    f"請款單 {request_no}（{cname}）需要您簽核")
            first_tier_usernames.append(a["username"])

    # 知會（2026-09-15）：整條簽核鏈都只有申請人本人時（他已在組織職權頂端），
    # 最高管理者不再被塞進簽核鏈，改收一則知會通知（仍可隨時以 superadmin 退回）。
    notify_org_chain_notice(conn, active_tiers, user["username"], request_no, request_no,
                            f"請款單 {request_no}（{cname}）由 "
                            f"{user.get('display_name') or user['username']} 依組織職權自行簽核，知會您",
                            type_="payment_request_approval_notice")

    conn.execute(
        "UPDATE payment_requests SET status='待審核', data_json=?, updated_at=? WHERE request_no=?",
        (json.dumps(d, ensure_ascii=False), now, request_no)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "payment_request.submit", "payment_request", request_no,
           f"{request_no}（{cname}）", {"tierCount": len(active_tiers)})
    if active_tiers:
        notify_payment_request_submitted(request_no, cname, first_tier_usernames)
    return {"ok": True, "status": "待審核"}


@router.post("/api/payment-requests/{request_no}/approve")
def approve_payment_request(request_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    # 比照 quotations.py：能否簽核完全由「是否為當層簽核人員」決定，不額外要求
    # 簽核人帳號角色必須是 admin/superadmin。
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, snapshot_json FROM payment_requests WHERE request_no=? AND status IN ('待審核','簽核中')",
        (request_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"請款單 {request_no} 不存在或不在待審核狀態")
    snap  = json.loads(row["snapshot_json"] or "{}")
    cname = snap.get("customerName") or ""
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
        # 同一人連任多層時一次簽完（2026-09-15，見 helpers/tiered_approval.py::
        # plan_self_cascade()）：前端跳確認視窗問過才會帶 cascade=true，
        # 且只吃「剩下未簽核的只有他自己」的連續層，不會替別人做決定。
        cascaded = (cascade_self_tiers(tiers, ct_idx, user["username"], now, conn=conn)
                    if (tier_done and (body or {}).get("cascade")) else [])
        landed = ct_idx + 1 + len(cascaded)
        next_tier_usernames = []
        if tier_done:
            appr["currentTier"] = landed
            all_done = landed >= len(tiers)
            if not all_done:
                for na in tiers[landed].get("approvers") or []:
                    _notify(na["username"], "payment_request_approval_request", request_no, request_no,
                            f"請款單 {request_no}（{cname}）輪到您簽核（第 {landed + 1} 層 / 共 {len(tiers)} 層）")
                    next_tier_usernames.append(na["username"])
                notify_payment_request_next_tier(request_no, cname, landed + 1, len(tiers), next_tier_usernames)
        else:
            all_done = False
        appr["tiers"] = tiers
        _signed_tier_nos = [x + 1 for x in [ct_idx, *cascaded]]
    else:
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")
        _global_flow  = resolve_active_flow_setting("payment_request")
        try:
            _global_tiers = _setting_to_active_tiers(_global_flow, conn, appr.get("requestedBy"))
        except UnresolvedManagerError as e:
            conn.close()
            raise HTTPException(400, str(e))
        if _global_tiers:
            conn.close()
            raise HTTPException(403, "系統已設定簽核流程，此請款單缺少簽核層資料，請重新送審")
        self_block_msg = check_no_tier_self_approval(conn, appr, user)
        if self_block_msg:
            conn.close()
            raise HTTPException(403, self_block_msg)
        all_done = True
        _signed_tier_nos = []

    if all_done:
        appr["approvedBy"]        = user["username"]
        appr["approvedByDisplay"] = user.get("display_name") or user["username"]
        appr["approvedAt"]        = now
        appr["status"]            = "approved"
        d["approval"] = appr
        conn.execute(
            "UPDATE payment_requests SET status='已核准', data_json=?, updated_at=? WHERE request_no=?",
            (json.dumps(d, ensure_ascii=False), now, request_no)
        )
        conn.commit()
        approver_name = appr.get("approvedByDisplay") or user["username"]
        spawn_bg_thread(_generate_payment_request_pdf, args=(request_no, approver_name, '簽核'))
        spawn_bg_thread(push_event_for_payment_request, args=(request_no,))
        requester = appr.get("requestedBy")
        if requester:
            _notify(requester, "payment_request_approved", request_no, request_no,
                    f"請款單 {request_no}（{cname}）已核准")
            notify_payment_request_approved(request_no, cname, approver_name, requester)
    else:
        d["approval"] = appr
        new_status = "簽核中" if (appr.get("currentTier") or 0) > 0 else "待審核"
        conn.execute(
            "UPDATE payment_requests SET status=?, data_json=?, updated_at=? WHERE request_no=?",
            (new_status, json.dumps(d, ensure_ascii=False), now, request_no)
        )
        conn.commit()

    conn.close()
    _audit(_tok(authorization), "payment_request.approve", "payment_request", request_no,
           f"{request_no}（{cname}）", {"allDone": all_done})
    return {"ok": True, "allDone": all_done, "signedTiers": _signed_tier_nos}


@router.post("/api/payment-requests/{request_no}/revoke-approval")
def revoke_payment_request_approval(request_no: str, body: dict = Body(default={}),
                                    authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, snapshot_json, export_count FROM payment_requests WHERE request_no=? AND status='已核准'",
        (request_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"請款單 {request_no} 不存在或不在已核准狀態")
    if (row["export_count"] or 0) > 0:
        conn.close()
        raise HTTPException(409, "此請款單已匯出過，不可撤銷核准")
    snap  = json.loads(row["snapshot_json"] or "{}")
    cname = snap.get("customerName") or ""
    d = json.loads(row["data_json"] or "{}")
    appr = d.get("approval") or {}
    requester = appr.get("requestedBy")
    d.pop("approval", None)
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE payment_requests SET status='草稿', data_json=?, updated_at=? WHERE request_no=?",
        (json.dumps(d, ensure_ascii=False), now, request_no)
    )
    conn.commit()
    conn.close()
    _purge_notifications(request_no, ['payment_request_approval_request', 'approval_reminder'])
    if requester:
        msg = f"請款單 {request_no}（{cname}）核准已被撤銷，請確認後重新送審" + (f"：{note}" if note else "")
        _notify(requester, "payment_request_returned", request_no, request_no, msg)
        notify_payment_request_returned(request_no, cname, note, requester)
    _audit(_tok(authorization), "payment_request.revoke_approval", "payment_request", request_no,
           f"{request_no}（{cname}）", {"note": note})
    return {"ok": True}


@router.post("/api/payment-requests/{request_no}/reject")
def reject_payment_request(request_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    # 比照 quotations.py：退回權限由當層簽核人員判斷，不額外要求 admin 角色
    user = _require_user(authorization)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, snapshot_json FROM payment_requests WHERE request_no=? AND status IN ('待審核','簽核中')",
        (request_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"請款單 {request_no} 不存在或不在待審核狀態")
    snap  = json.loads(row["snapshot_json"] or "{}")
    cname = snap.get("customerName") or ""
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
        "UPDATE payment_requests SET status='草稿', data_json=?, updated_at=? WHERE request_no=?",
        (json.dumps(d, ensure_ascii=False), now, request_no)
    )
    conn.commit()
    conn.close()
    _purge_notifications(request_no, ['payment_request_approval_request', 'approval_reminder'])
    if requester:
        msg = f"請款單 {request_no}（{cname}）已退回，請確認後重新送審" + (f"：{note}" if note else "")
        _notify(requester, "payment_request_returned", request_no, request_no, msg)
        notify_payment_request_returned(request_no, cname, note, requester)
    _audit(_tok(authorization), "payment_request.reject", "payment_request", request_no,
           f"{request_no}（{cname}）", {"note": note})
    return {"ok": True}


# ── PDF / 匯出紀錄 ────────────────────────────────────────────────────────────

@router.get("/api/payment-requests/{request_no}/pdf-download")
def download_payment_request_pdf(request_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT request_no, quote_no, data_json FROM payment_requests WHERE request_no=?", (request_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "單據不存在")
    _guard_voucher(conn, row, user)
    conn.close()
    if not row:
        raise HTTPException(404, "請款單不存在")
    try:
        pdf_bytes = generate_payment_request_pdf_bytes(request_no)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        tid = trace_id()
        logger.exception("payment_request pdf failed trace=%s", tid)
        raise HTTPException(500, f"PDF 產生失敗（代碼 {tid}）")
    encoded = urlquote(f"{request_no}.pdf")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


@router.post("/api/payment-requests/{request_no}/export")
def record_payment_request_export(request_no: str, mode: str = "external", authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT export_count, export_log FROM payment_requests WHERE request_no=?", (request_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"請款單 {request_no} 不存在")
    log   = json.loads(row["export_log"] or "[]")
    count = (row["export_count"] or 0) + 1
    log.append({
        "at": datetime.now().isoformat(), "mode": mode, "user": user["username"],
        "userDisplay": user.get("display_name") or user["username"], "count": count,
    })
    conn.execute("UPDATE payment_requests SET export_count=?, export_log=? WHERE request_no=?",
                 (count, json.dumps(log, ensure_ascii=False), request_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "payment_request.export_pdf", "payment_request", request_no,
           f"{request_no} PDF 匯出（{mode}）by {user['username']}")
    return {"export_count": count, "log": log}


# ── IP-6 `calendar.writeback`：行事曆事件 id 由擁有模組自己回寫（2026-09-25，ROADMAP A11）──────
# L1 `helpers/google_calendar` 建好事件後呼叫這裡，不再直接 UPDATE 本組的表。
# 事件建立是網路請求（慢）⇒ 這裡才拿寫鎖、重讀、只寫入 event id（不整包蓋回別人的修改）。
from core import registry as _registry  # noqa: E402


def _calendar_writeback(key: str, event_id: str, slot: str = "default") -> None:
    from core.txn import write_txn
    conn = get_db()
    try:
        with write_txn(conn):
            r = conn.execute("SELECT data_json FROM payment_requests WHERE request_no=?", (key,)).fetchone()
            if not r:
                return
            d = json.loads(r["data_json"] or "{}")
            d["googleCalendarEventId"] = event_id
            conn.execute("UPDATE payment_requests SET data_json=? WHERE request_no=?",
                         (json.dumps(d, ensure_ascii=False), key))
            conn.commit()
    finally:
        conn.close()


_registry.provide("calendar.writeback", "payment_request", _calendar_writeback)
