"""開票申請憑據：案件款項明細（quotations.data_json.caseRecord.payment.items[]，
本身不是獨立資料表）匯出給財務單位申請開立發票用的獨立單據。

scope='single' 對應單一 payment_idx；scope='all' 彙整整份收款排程的所有項目。
不要求 received=true 才能申請——2026-08-20 使用者明確要求放寬：部分案件是先開
發票才能收款（開票在前、收款在後），故未勾選已收款的項目也允許建立憑據；
snapshot 裡仍保留 received 旗標，PDF 上會標示「已收款」或「未收款（開票在先）」
供財務辨識目前實際收款狀況。

簽核流程（system_settings key: unified_approval_flow，2026-08-24 起與報價單／
出貨單／請款單共用同一組設定）機制為 tiers 依序簽核；核准即定稿，不像承攬商匯款
申請多一個「已匯款」財務結案節點——開票申請憑據本身就是最終文件。

客戶/案件/款項明細於建立當下寫入 snapshot_json 凍結快照，理由同
routers/contractor_vouchers.py：已送出財務的憑據不應該因為之後有人編輯報價單
款項明細而回頭改變內容。
"""
import json
import logging
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Body, HTTPException, Header, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_db, next_entity_code, spawn_bg_thread
from core.txn import begin_write, write_txn
from helpers import (
    _require_user, _tok, _audit, _notify, _purge_notifications,
    notify_module_activity, notify_invoice_voucher_submitted, notify_invoice_voucher_next_tier,
    notify_invoice_voucher_approved, notify_invoice_voucher_returned,
    push_event_for_invoice_voucher,
    active_tiers as _active_tiers, current_tier_idx as _current_tier_idx,
    setting_to_active_tiers as _setting_to_active_tiers,
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
    cascade_self_tiers, notify_org_chain_notice,
    UnresolvedManagerError, resolve_active_flow_setting,
    save_document_files, delete_document_file,
    guard_case_access, require_any_module,

    can_see_financial, is_document_approver,
)
from pdf_gen import generate_invoice_voucher_pdf_bytes, _generate_invoice_voucher_pdf
from helpers.errors import trace_id
from helpers.quotations import quote_tax_type, tax_split, LEGACY_TAX_NOTE

router = APIRouter()
logger = logging.getLogger(__name__)

def _guard_voucher(conn, row, user):
    """單據層級守門（2026-09-13 模組權限稽核第四輪）。

    先前 `GET /{voucher_no}`、PDF 下載與檔案上傳/刪除都只要求登入，而單號是可預測的
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
        require_any_module(user, ('case_manage', 'finance', 'cashier', 'quotation'), "開票憑證")
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

class InvoiceItemIn(BaseModel):
    itemId: int
    qty:    float
    amount: float

class VoucherCreateIn(BaseModel):
    quote_no: str
    scope:    str                            # 'amount'（自訂金額）| 'items'（自訂品項+數量）
    amount:   Optional[float] = None         # scope='amount' 時必填
    items:    Optional[List[InvoiceItemIn]] = None   # scope='items' 時必填


# ── Approval tier helpers（純邏輯部分共用 helpers/tiered_approval.py，見上方 import）──


def _require_admin(user: dict):
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")


def _voucher_public(row, include_snapshot: bool = True) -> dict:
    d = dict(row)
    snap = json.loads(d.get("snapshot_json") or "{}")
    approval = (json.loads(d.get("data_json") or "{}") or {}).get("approval") or {}
    amount = float(d.get("amount") or 0)
    out = {
        "id":            d["id"],
        "voucherNo":     d["voucher_no"],
        "quoteNo":       d["quote_no"],
        "scope":         d["scope"] or "amount",
        "customerName":  snap.get("customerName", ""),
        "status":        d["status"] or "草稿",
        "amount":        amount,          # 含稅
        "totalAmount":   amount,          # 別名，沿用前端既有欄位名
        "pretaxAmount":  snap.get("pretaxAmount", 0),
        "taxAmount":     snap.get("taxAmount", 0),
        "taxType":       snap.get("taxType", ""),      # AC1 之前建立的快照沒有這兩欄
        "taxNote":       snap.get("taxNote", ""),
        "selectedItems": snap.get("selectedItems") or [],
        "issuedFiles":   json.loads(d.get("issued_files_json") or "[]"),
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


def _quote_remaining(conn, quote_no: str):
    """這張報價單目前的開票申請額度使用狀況：合約總額（含稅）、未稅總額、已申請
    金額（含稅，含草稿——2026-08-20 使用者明確選擇「草稿就鎖額度」避免同時建立
    造成超額）、剩餘可申請金額（含稅），以及每個報價品項各自的已申請數量／剩餘
    數量（供 scope='items' 建立時檢查、也供前端顯示可選數量上限）。查無報價單
    回傳 None。

    quoteTotal（含稅）／quotePretax（未稅）兩者比例就是這張報價單的實際稅率
    （已反映折扣/運費等調整），供 create_invoice_voucher() 換算 scope='items'
    的未稅品項金額為含稅（voucher.amount 這個唯一權威金額欄位一律存含稅，
    才能跟 quoteTotal 直接比較，見下方換算邏輯）。"""
    q = conn.execute("SELECT total, pretax, data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not q:
        return None
    data = json.loads(q["data_json"] or "{}")
    quote_total = float(q["total"] or 0)
    quote_pretax = float(q["pretax"] or 0) or quote_total  # 沒有 pretax 資料時退回等於含稅（稅率視為 0）

    rows = conn.execute(
        "SELECT amount, snapshot_json FROM invoice_vouchers WHERE quote_no=?", (quote_no,)
    ).fetchall()
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

    return {
        "quoteTotal":       quote_total,
        "quotePretax":      quote_pretax,
        "requestedAmount":  requested_amount,
        "remainingAmount":  quote_total - requested_amount,
        "items":            items_info,
    }


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/invoice-vouchers")
def list_invoice_vouchers(quote_no: Optional[str] = None, authorization: str = Header(None)):
    # 2026-09-13（模組權限稽核）：帶 quote_no 就是「讀某一張案件的開票憑證」——
    # `quote_no` 可列舉，先前只要求登入等於任何人都撈得到別人案件的單據與金額。
    # 不帶 quote_no 是跨案件總覽，改為管理員或具相關模組的人才看得到。
    user = _require_user(authorization)
    conn = get_db()
    if quote_no:
        guard_case_access(conn, quote_no, user, allow_module="case_manage")
    else:
        # `quotation` 也要收：簽核佇列（模組 quotation）就是用這支載入待簽的單據
        require_any_module(user, ('case_manage', 'finance', 'cashier', 'quotation'), "開票憑證")
    if quote_no:
        rows = conn.execute(
            "SELECT * FROM invoice_vouchers WHERE quote_no=? ORDER BY created_at DESC", (quote_no,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM invoice_vouchers ORDER BY created_at DESC LIMIT 200").fetchall()
    rows = _visible_rows(rows, user, conn)
    conn.close()
    return [_voucher_public(r, include_snapshot=False) for r in rows]


@router.get("/api/invoice-vouchers/remaining")
def get_invoice_voucher_remaining(quote_no: str, authorization: str = Header(None)):
    """建立開票申請前，前端要顯示「剩餘可申請金額／品項數量」用——必須註冊在
    /{voucher_no} 之前，否則 FastAPI 會把 'remaining' 當成 voucher_no 吃掉。"""
    user = _require_user(authorization)
    conn = get_db()
    guard_case_access(conn, quote_no, user, allow_module="case_manage")
    info = _quote_remaining(conn, quote_no)
    conn.close()
    if info is None:
        raise HTTPException(404, "找不到關聯的報價單")
    return info


@router.get("/api/invoice-vouchers/{voucher_no}")
def get_invoice_voucher(voucher_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM invoice_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "單據不存在")
    _guard_voucher(conn, row, user)
    conn.close()
    if not row:
        raise HTTPException(404, f"憑據 {voucher_no} 不存在")
    return _voucher_public(row)


@router.post("/api/invoice-vouchers", status_code=201)
def create_invoice_voucher(body: VoucherCreateIn, authorization: str = Header(None)):
    """2026-08-20 重新設計：使用者反映很多案件是「先開發票才能收款」，原本只能
    挑一個既有款項期別（scope='single'/'all'）不夠彈性。改為 scope='amount'
    自訂任意金額，或 scope='items' 自訂品項+數量；已申請過的金額/品項數量（含
    草稿，草稿就鎖額度）從 _quote_remaining() 算出的剩餘額度扣除，防止超額/
    重複請款。舊的「同範圍已建立過」防重複檢查也隨之被剩餘額度檢查取代——
    多筆申請本來就可以合法共存，只要總額不超過報價單金額即可。"""
    user = _require_user(authorization)
    _require_admin(user)
    if body.scope not in ("amount", "items"):
        raise HTTPException(400, "scope 必須為 amount 或 items")

    conn = get_db()
    # BEGIN IMMEDIATE：把「算剩餘可申請額度」跟「寫入新申請」鎖進同一個交易，
    # 避免兩個近乎同時送出的請求都通過超額檢查、合計超過報價單總額
    # （這是這輪剩餘額度重新設計要防的核心情境，光靠應用層檢查不夠，需要
    # 資料庫層級把窗口關掉）。
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

        # 報價單品項參考（開立發票要寫的實際品名，不是收款期別）——只帶客戶看得到的欄位，
        # 刻意排除 cost/margin/unitPriceOverride 等內部機密欄位，避免內部成本/毛利
        # 外流到這份要交給財務（甚至可能對外）的開票申請文件上。
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

        # voucher.amount（唯一權威金額欄位，供剩餘額度 SUM() 用）一律存「含稅」，
        # 才能跟 quoteTotal（含稅合約總額）直接比較。兩種 scope 換算方向相反：
        #   scope='amount'：使用者輸入的就是含稅金額（比照款項明細 itemAmountWithTax
        #     的既有慣例），未稅 = 含稅 × quotePretax/quoteTotal
        #   scope='items'：品項金額欄位比照報價單品項本身（unitPrice/amount）是未稅，
        #     未稅加總後要 × quoteTotal/quotePretax 換算成含稅，才能存進 amount 欄位
        selected_items_snapshot = []
        if body.scope == "amount":
            if not body.amount or body.amount <= 0:
                conn.close()
                raise HTTPException(400, "請輸入申請金額")
            request_amount = body.amount
            pretax_amount = round(request_amount * quote_pretax / quote_total) if quote_total > 0 else request_amount
        else:
            if not body.items:
                conn.close()
                raise HTTPException(400, "請至少選擇一項品項")
            quote_items_by_id = {it.get("id"): it for it in (data.get("items") or []) if it.get("type") != "header"}
            qty_remaining_by_id = {it["itemId"]: it["remainingQty"] for it in remaining["items"]}
            pretax_amount = 0.0
            for line in body.items:
                src = quote_items_by_id.get(line.itemId)
                if not src:
                    conn.close()
                    raise HTTPException(400, f"找不到品項 id={line.itemId}")
                if line.qty <= 0:
                    conn.close()
                    raise HTTPException(400, f"品項「{src.get('description','')}」數量需大於 0")
                avail = qty_remaining_by_id.get(line.itemId, 0)
                if line.qty > avail + 1e-9:
                    conn.close()
                    raise HTTPException(409, f"品項「{src.get('description','')}」剩餘可申請數量不足（剩餘 {avail:g}）")
                if line.amount <= 0:
                    conn.close()
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
            request_amount = round(pretax_amount * quote_total / quote_pretax) if quote_pretax > 0 else pretax_amount

        # AC1（2026-09-24 使用者：「會計稅率1~4%取消，直接依法規進行」）：
        #   稅額＝round_half_up(銷售額 × 5%)（零稅率／免稅＝0），與報價、稅務匯出同一算法；
        #   含稅＝銷售額＋稅額（發票三欄自洽；與使用者輸入的申請金額可能差 ±1 元，列交付說明）。
        #   舊 1～4% 報價：數字不改（沿用原本的比例換算），快照標「非法定稅率，請會計確認」。
        #   ⚠️ 只影響**新建立**的開票申請；已建立的快照不回頭改。
        tax_type = quote_tax_type(data)
        tax_note = ""
        if tax_type == "legacy":
            tax_amount = request_amount - pretax_amount
            tax_note = "舊稅率 %s%%（已停用）：%s" % (data.get("taxRate"), LEGACY_TAX_NOTE)
        else:
            pretax_amount, tax_amount = tax_split(pretax_amount, tax_type)
            request_amount = pretax_amount + tax_amount

        if request_amount > remaining_amount + 1e-6:
            conn.close()
            raise HTTPException(409, f"超過剩餘可開票金額（剩餘 NT$ {remaining_amount:,.0f}）")

        snapshot = {
            "customerName":    q["customer_name"] or "",
            "customerTaxId":   customer_tax_id,
            "projectName":     q["project_name"] or "",
            "quoteItems":      quote_items_snapshot,
            "selectedItems":   selected_items_snapshot,
            "requestedAmount": request_amount,      # 含稅（＝ voucher.amount）
            "pretaxAmount":    round(pretax_amount),
            "taxAmount":       round(tax_amount),
            "taxType":         tax_type,
            "taxNote":         tax_note,
        }

        now = datetime.now().isoformat()
        voucher_no = next_entity_code(conn, "invoice_vouchers", "IV", code_col="voucher_no")
        conn.execute(
            "INSERT INTO invoice_vouchers "
            "(voucher_no, quote_no, scope, amount, status, snapshot_json, data_json, "
            "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (voucher_no, body.quote_no, body.scope, request_amount,
             "草稿", json.dumps(snapshot, ensure_ascii=False), "{}", user["username"], now, now)
        )
        conn.commit()
        conn.close()
        _audit(_tok(authorization), "invoice_voucher.create", "invoice_voucher", voucher_no,
               f"{voucher_no}（{snapshot['customerName']}）")
        notify_module_activity("開票申請憑據", "建立", user.get("display_name") or user["username"],
                                f"{voucher_no}（{snapshot['customerName']}）", "case-management.html")
        return {"voucher_no": voucher_no, "created_at": now}


@router.delete("/api/invoice-vouchers/{voucher_no}")
def delete_invoice_voucher(voucher_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT status FROM invoice_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "憑據不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可刪除")
    conn.execute("DELETE FROM invoice_vouchers WHERE voucher_no=?", (voucher_no,))
    conn.commit()
    conn.close()
    _purge_notifications(voucher_no, ['invoice_voucher_approval_request', 'invoice_voucher_approved',
                                       'invoice_voucher_returned', 'approval_reminder'])
    _audit(_tok(authorization), "invoice_voucher.delete", "invoice_voucher", voucher_no, voucher_no)
    notify_module_activity("開票申請憑據", "刪除", user.get("display_name") or user["username"],
                            voucher_no, "case-management.html")
    return {"ok": True}


# ── 簽核流程 ──────────────────────────────────────────────────────────────────

@router.post("/api/invoice-vouchers/{voucher_no}/submit")
def submit_invoice_voucher(voucher_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT status, data_json, snapshot_json FROM invoice_vouchers WHERE voucher_no=?", (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "憑據不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可送出審核")

    snap  = json.loads(row["snapshot_json"] or "{}")
    cname = snap.get("customerName") or ""
    d     = json.loads(row["data_json"] or "{}")
    now   = datetime.now().isoformat()

    flow_setting = resolve_active_flow_setting("invoice_voucher")
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
            _notify(a["username"], "invoice_voucher_approval_request", voucher_no, voucher_no,
                    f"開票申請憑據 {voucher_no}（{cname}）需要您簽核")
            first_tier_usernames.append(a["username"])

    # 知會（2026-09-15）：整條簽核鏈都只有申請人本人時（他已在組織職權頂端），
    # 最高管理者不再被塞進簽核鏈，改收一則知會通知（仍可隨時以 superadmin 退回）。
    notify_org_chain_notice(conn, active_tiers, user["username"], voucher_no, voucher_no,
                            f"開票申請憑據 {voucher_no}（{cname}）由 "
                            f"{user.get('display_name') or user['username']} 依組織職權自行簽核，知會您",
                            type_="invoice_voucher_approval_notice")

    conn.execute(
        "UPDATE invoice_vouchers SET status='待審核', data_json=?, updated_at=? WHERE voucher_no=?",
        (json.dumps(d, ensure_ascii=False), now, voucher_no)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "invoice_voucher.submit", "invoice_voucher", voucher_no,
           f"{voucher_no}（{cname}）", {"tierCount": len(active_tiers)})
    if active_tiers:
        notify_invoice_voucher_submitted(voucher_no, cname, first_tier_usernames)
    return {"ok": True, "status": "待審核"}


@router.post("/api/invoice-vouchers/{voucher_no}/approve")
def approve_invoice_voucher(voucher_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    # 比照 quotations.py：能否簽核完全由「是否為當層簽核人員」決定，不額外要求
    # 簽核人帳號角色必須是 admin/superadmin——簽核設定頁面允許加入任何角色的
    # 使用者當簽核人，這裡若硬性擋 admin 會讓非管理員角色的簽核人永遠卡死無法簽核。
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, snapshot_json FROM invoice_vouchers WHERE voucher_no=? AND status IN ('待審核','簽核中')",
        (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"憑據 {voucher_no} 不存在或不在待審核狀態")
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
                    _notify(na["username"], "invoice_voucher_approval_request", voucher_no, voucher_no,
                            f"開票申請憑據 {voucher_no}（{cname}）輪到您簽核（第 {landed + 1} 層 / 共 {len(tiers)} 層）")
                    next_tier_usernames.append(na["username"])
                notify_invoice_voucher_next_tier(voucher_no, cname, landed + 1, len(tiers), next_tier_usernames)
        else:
            all_done = False
        appr["tiers"] = tiers
        _signed_tier_nos = [x + 1 for x in [ct_idx, *cascaded]]
    else:
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")
        _global_flow  = resolve_active_flow_setting("invoice_voucher")
        try:
            _global_tiers = _setting_to_active_tiers(_global_flow, conn, appr.get("requestedBy"))
        except UnresolvedManagerError as e:
            conn.close()
            raise HTTPException(400, str(e))
        if _global_tiers:
            conn.close()
            raise HTTPException(403, "系統已設定簽核流程，此憑據缺少簽核層資料，請重新送審")
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
            "UPDATE invoice_vouchers SET status='已核准', data_json=?, updated_at=? WHERE voucher_no=?",
            (json.dumps(d, ensure_ascii=False), now, voucher_no)
        )
        conn.commit()
        approver_name = appr.get("approvedByDisplay") or user["username"]
        spawn_bg_thread(_generate_invoice_voucher_pdf, args=(voucher_no, approver_name, '簽核'))
        spawn_bg_thread(push_event_for_invoice_voucher, args=(voucher_no,))
        requester = appr.get("requestedBy")
        if requester:
            _notify(requester, "invoice_voucher_approved", voucher_no, voucher_no,
                    f"開票申請憑據 {voucher_no}（{cname}）已核准")
            notify_invoice_voucher_approved(voucher_no, cname, approver_name, requester)
    else:
        d["approval"] = appr
        new_status = "簽核中" if (appr.get("currentTier") or 0) > 0 else "待審核"
        conn.execute(
            "UPDATE invoice_vouchers SET status=?, data_json=?, updated_at=? WHERE voucher_no=?",
            (new_status, json.dumps(d, ensure_ascii=False), now, voucher_no)
        )
        conn.commit()

    conn.close()
    _audit(_tok(authorization), "invoice_voucher.approve", "invoice_voucher", voucher_no,
           f"{voucher_no}（{cname}）", {"allDone": all_done})
    return {"ok": True, "allDone": all_done, "signedTiers": _signed_tier_nos}


@router.post("/api/invoice-vouchers/{voucher_no}/revoke-approval")
def revoke_invoice_voucher_approval(voucher_no: str, body: dict = Body(default={}),
                                    authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, snapshot_json, export_count FROM invoice_vouchers WHERE voucher_no=? AND status='已核准'",
        (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"憑據 {voucher_no} 不存在或不在已核准狀態")
    if (row["export_count"] or 0) > 0:
        conn.close()
        raise HTTPException(409, "此憑據已匯出過，財務可能已憑此核發票，不可撤銷核准")
    snap  = json.loads(row["snapshot_json"] or "{}")
    cname = snap.get("customerName") or ""
    d = json.loads(row["data_json"] or "{}")
    appr = d.get("approval") or {}
    requester = appr.get("requestedBy")
    d.pop("approval", None)
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE invoice_vouchers SET status='草稿', data_json=?, updated_at=? WHERE voucher_no=?",
        (json.dumps(d, ensure_ascii=False), now, voucher_no)
    )
    conn.commit()
    conn.close()
    _purge_notifications(voucher_no, ['invoice_voucher_approval_request', 'approval_reminder'])
    if requester:
        msg = f"開票申請憑據 {voucher_no}（{cname}）核准已被撤銷，請確認後重新送審" + (f"：{note}" if note else "")
        _notify(requester, "invoice_voucher_returned", voucher_no, voucher_no, msg)
        notify_invoice_voucher_returned(voucher_no, cname, note, requester)
    _audit(_tok(authorization), "invoice_voucher.revoke_approval", "invoice_voucher", voucher_no,
           f"{voucher_no}（{cname}）", {"note": note})
    return {"ok": True}


@router.post("/api/invoice-vouchers/{voucher_no}/reject")
def reject_invoice_voucher(voucher_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    # 比照 quotations.py：退回權限由當層簽核人員判斷，不額外要求 admin 角色
    user = _require_user(authorization)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, snapshot_json FROM invoice_vouchers WHERE voucher_no=? AND status IN ('待審核','簽核中')",
        (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"憑據 {voucher_no} 不存在或不在待審核狀態")
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
        "UPDATE invoice_vouchers SET status='草稿', data_json=?, updated_at=? WHERE voucher_no=?",
        (json.dumps(d, ensure_ascii=False), now, voucher_no)
    )
    conn.commit()
    conn.close()
    _purge_notifications(voucher_no, ['invoice_voucher_approval_request', 'approval_reminder'])
    if requester:
        msg = f"開票申請憑據 {voucher_no}（{cname}）已退回，請確認後重新送審" + (f"：{note}" if note else "")
        _notify(requester, "invoice_voucher_returned", voucher_no, voucher_no, msg)
        notify_invoice_voucher_returned(voucher_no, cname, note, requester)
    _audit(_tok(authorization), "invoice_voucher.reject", "invoice_voucher", voucher_no,
           f"{voucher_no}（{cname}）", {"note": note})
    return {"ok": True}


# ── PDF / 匯出紀錄 ────────────────────────────────────────────────────────────

@router.get("/api/invoice-vouchers/{voucher_no}/pdf-download")
def download_invoice_voucher_pdf(voucher_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT voucher_no, quote_no, data_json FROM invoice_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "單據不存在")
    _guard_voucher(conn, row, user)
    conn.close()
    if not row:
        raise HTTPException(404, "憑據不存在")
    try:
        pdf_bytes = generate_invoice_voucher_pdf_bytes(voucher_no)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        tid = trace_id()
        logger.exception("invoice_voucher pdf failed trace=%s", tid)
        raise HTTPException(500, f"PDF 產生失敗（代碼 {tid}）")
    encoded = urlquote(f"{voucher_no}.pdf")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


@router.post("/api/invoice-vouchers/{voucher_no}/export")
def record_invoice_voucher_export(voucher_no: str, mode: str = "external", authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT export_count, export_log FROM invoice_vouchers WHERE voucher_no=?", (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"憑據 {voucher_no} 不存在")
    log   = json.loads(row["export_log"] or "[]")
    count = (row["export_count"] or 0) + 1
    log.append({
        "at": datetime.now().isoformat(), "mode": mode, "user": user["username"],
        "userDisplay": user.get("display_name") or user["username"], "count": count,
    })
    conn.execute("UPDATE invoice_vouchers SET export_count=?, export_log=? WHERE voucher_no=?",
                 (count, json.dumps(log, ensure_ascii=False), voucher_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "invoice_voucher.export_pdf", "invoice_voucher", voucher_no,
           f"{voucher_no} PDF 匯出（{mode}）by {user['username']}")
    return {"export_count": count, "log": log}


# ── 已開立附件上傳 ────────────────────────────────────────────────────────────

@router.post("/api/invoice-vouchers/{voucher_no}/issued-files", status_code=201)
async def upload_invoice_voucher_issued_files(voucher_no: str, files: List[UploadFile] = File(...),
                                              authorization: str = Header(None)):
    """已開立發票附件上傳（多檔）——任何登入使用者皆可補傳，供未來查詢當初
    實際開立的內容（例如發票影本）。不限制狀態，草稿/簽核中也能先留存。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT issued_files_json, quote_no, data_json FROM invoice_vouchers WHERE voucher_no=?",
        (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "憑據不存在")
    _guard_voucher(conn, row, user)
    existing = json.loads(row["issued_files_json"] or "[]")
    new_files = await save_document_files("invoice_vouchers", voucher_no, files,
                                          user.get("display_name") or user["username"])
    all_files = existing + new_files
    now = datetime.now().isoformat()
    conn.execute("UPDATE invoice_vouchers SET issued_files_json=?, updated_at=? WHERE voucher_no=?",
                 (json.dumps(all_files, ensure_ascii=False), now, voucher_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "invoice_voucher.upload_issued_files", "invoice_voucher", voucher_no,
           f"{voucher_no}（{len(new_files)} 個檔案）")
    return {"ok": True, "added": len(new_files), "files": new_files}


@router.delete("/api/invoice-vouchers/{voucher_no}/issued-files/{file_id}")
def delete_invoice_voucher_issued_file(voucher_no: str, file_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT issued_files_json, quote_no, data_json FROM invoice_vouchers WHERE voucher_no=?",
        (voucher_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "憑據不存在")
    _guard_voucher(conn, row, user)
    existing = json.loads(row["issued_files_json"] or "[]")
    remaining = delete_document_file("invoice_vouchers", voucher_no, existing, file_id)
    now = datetime.now().isoformat()
    conn.execute("UPDATE invoice_vouchers SET issued_files_json=?, updated_at=? WHERE voucher_no=?",
                 (json.dumps(remaining, ensure_ascii=False), now, voucher_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "invoice_voucher.delete_issued_file", "invoice_voucher", voucher_no, voucher_no)
    return {"ok": True}


# ── IP-6 `calendar.writeback`：行事曆事件 id 由擁有模組自己回寫（2026-09-25，ROADMAP A11）──────
# L1 `helpers/google_calendar` 建好事件後呼叫這裡，不再直接 UPDATE 本組的表。
# 事件建立是網路請求（慢）⇒ 這裡才拿寫鎖、重讀、只寫入 event id（不整包蓋回別人的修改）。
from core import registry as _registry  # noqa: E402


def _calendar_writeback(key: str, event_id: str, slot: str = "default") -> None:
    from core.txn import write_txn
    conn = get_db()
    try:
        with write_txn(conn):
            r = conn.execute("SELECT data_json FROM invoice_vouchers WHERE voucher_no=?", (key,)).fetchone()
            if not r:
                return
            d = json.loads(r["data_json"] or "{}")
            d["googleCalendarEventId"] = event_id
            conn.execute("UPDATE invoice_vouchers SET data_json=? WHERE voucher_no=?",
                         (json.dumps(d, ensure_ascii=False), key))
            conn.commit()
    finally:
        conn.close()


_registry.provide("calendar.writeback", "invoice_voucher", _calendar_writeback)
