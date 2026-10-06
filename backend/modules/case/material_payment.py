# -*- coding: utf-8 -*-
"""叫料匯款申請（第 31 班 31-C 匯款切片；設計 docs/platform/plans/MATERIAL-ORDER-APPROVAL-DESIGN.md §3.4）。

[單位] case:material_payment    [層] L2（M01）    [穩定度] 新（第 31 班）
**模型**：每張叫料單（`caseRecord.materialOrders[]`）可開**多張**匯款申請（表 `case_material_payments`，`UNIQUE(quote_no,item_id,seq)`，
單號 `MP-YYYYMMDD-NNNN`）；每張各自走分層簽核（doc type `material_payment`）→ 核准 → 出納（IP-100／IP-102）；出納可對每張申請**分次**登錄付款，
每次一列付款明細（`case_material_payment_lines`）。**叫料單的 `paidStatus／paidAmount／paidDate` 只是明細合計的投影**——
唯一的寫入點是 `sync_order_paid`（G-M1 守門：別處不准寫 paid*）。
**累計上限（跨申請）**：同一叫料單所有「未作廢、未退回」申請（草稿與待審核**鎖額度**）的 `amount_approved` 合計 ≤ 叫料單小計；
超過 ⇒ 409；superadmin 可覆寫（必填理由，留在申請上）。作廢／退回後額度釋出（退回後重送審時重新檢查）。
**付款明細**：每筆實付 `amount`、手續費 `fee`（公司自付，不從受款方扣）；該申請累計實付超過申請金額（多付）⇒ 這一筆 `remit_review='pending'`
（差額待審核，admin 核可或退回＝刪除該筆明細）；少付＝分次付款（申請留在待付款顯示剩餘）。
所有函式**不 commit**（呼叫端在自己的交易內提交）；失敗一律 raise `MaterialPaymentError(status, 訊息)`。
"""
import json
import math
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from helpers.dates import normalize_date
from helpers.auth import has_finance_access  # 第42班：取消／撤回／作廢的財務動作只認財務角色與 superadmin
from helpers.tiered_approval import (
    APPROVAL_DOC_TYPES, UnresolvedManagerError, active_tiers, check_approve_permission, check_no_tier_self_approval,
    check_reject_permission, current_tier_idx, cascade_self_tiers, register_doc_type, resolve_active_flow_setting,
    setting_to_active_tiers, sign_first_pending,
)
from modules.case import material_approval as MA

DOC_TYPE = "material_payment"
DOC_LABEL = "材料申請匯款"
DOC_PREFIX = "MP"
SOURCE_LABEL = "材料申請匯款"
FEE_CATEGORY = "匯款手續費"

S_DRAFT, S_PENDING, S_IN_PROGRESS, S_APPROVED, S_RETURNED, S_VOID = "草稿", "待審核", "簽核中", "已核准", "已退回", "作廢"
IN_FLIGHT = (S_PENDING, S_IN_PROGRESS)
EDITABLE = (S_DRAFT, S_RETURNED)
#: 鎖額度的狀態（退回與作廢釋出）
QUOTA_STATUSES = (S_DRAFT, S_PENDING, S_IN_PROGRESS, S_APPROVED)

REVIEW_PENDING = "pending"
#: 單筆手續費覆核門檻（32 班；只管材料申請匯款，其他請款來源沒有此規則）：超過 ⇒ 該筆付款明細進「差額審核」（與多付同一條覆核路徑）。
FEE_REVIEW_OVER = 500.0
REVIEW_APPROVED = "approved"

if DOC_TYPE not in APPROVAL_DOC_TYPES:
    register_doc_type(DOC_TYPE, DOC_LABEL, unified=True)


class MaterialPaymentError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class RemitForbidden(ValueError):
    """自己登錄的付款不能自己核可／退回差額（呼叫端轉 403）。"""
    status = 403


class BadRemit(ValueError):
    """實付／手續費格式不對（呼叫端轉 400）。"""
    status = 400


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _display(user):
    return user.get("display_name") or user["username"]


def r2(v) -> float:
    """金額（元以下兩位）一律 **half-up**（X-VAT 2026-09-26：前端 `MotrixLegalRound.halfUp`、後端 Decimal；不用 Python `round`——它對二進位浮點 0.145／2.675 會得到 0.14／2.67）。"""
    return float(Decimal(repr(float(v))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _money(v) -> float:
    return r2(v or 0)


# ── 讀 ───────────────────────────────────────────────────────────────

def get(conn, pid):
    try:
        r = conn.execute("SELECT * FROM case_material_payments WHERE id=?", (int(pid),)).fetchone()
    except (TypeError, ValueError):
        return None
    return dict(r) if r else None


def get_by_code(conn, doc_code):
    r = conn.execute("SELECT * FROM case_material_payments WHERE doc_code=?", (doc_code,)).fetchone()
    return dict(r) if r else None


def list_for_order(conn, quote_no, item_id) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM case_material_payments WHERE quote_no=? AND item_id=? ORDER BY seq",
                                          (quote_no, str(item_id)))]


def lines_of(conn, pid) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM case_material_payment_lines WHERE payment_id=? ORDER BY id", (int(pid),))]


def paid_total(conn, pid) -> float:
    r = conn.execute("SELECT COALESCE(SUM(amount),0) FROM case_material_payment_lines WHERE payment_id=?", (int(pid),)).fetchone()
    return _money(r[0])


def remaining_of(conn, pay) -> float:
    """申請的剩餘應付（申請金額 − 累計實付；可為負＝已多付）。"""
    return _money(float(pay["amount_approved"] or 0) - paid_total(conn, pay["id"]))


def committed(conn, quote_no, item_id, exclude_id=None) -> float:
    """這張叫料單已被未作廢、未退回申請鎖住的額度合計。"""
    q = ("SELECT COALESCE(SUM(amount_approved),0) FROM case_material_payments WHERE quote_no=? AND item_id=? AND status IN (%s)"
         % ",".join("?" * len(QUOTA_STATUSES)))
    args = [quote_no, str(item_id), *QUOTA_STATUSES]
    if exclude_id is not None:
        q += " AND id<>?"
        args.append(int(exclude_id))
    return _money(conn.execute(q, args).fetchone()[0])


def order_total(order: dict) -> float:
    return _money((order or {}).get("totalPrice"))


def legacy_paid(conn, quote_no, item_id, order=None):
    """舊單在第一張匯款申請之前已登記的已付金額與日期 ⇒ `(amount, date)`。第一張申請建立時凍結進它的 `snapshot_json`
    （`legacyPaid／legacyPaidDate`），之後 `paid*` 被投影覆寫也不會丟；還沒有任何申請 ⇒ 讀叫料單目前的 paid*。"""
    first = conn.execute("SELECT snapshot_json FROM case_material_payments WHERE quote_no=? AND item_id=? ORDER BY seq LIMIT 1", (quote_no, str(item_id))).fetchone()
    if first is not None:
        try:
            sn = json.loads(first["snapshot_json"] or "{}") or {}
        except (TypeError, ValueError):
            sn = {}
        return _money(sn.get("legacyPaid")), str(sn.get("legacyPaidDate") or "")[:10]
    o = order or {}
    return _money(o.get("paidAmount")), str(o.get("paidDate") or "")[:10]


def paid_so_far(conn, quote_no, item_id, order=None) -> float:
    """這張叫料單已付的總額＝舊單歷史已付＋所有申請的付款明細合計（與 `sync_order_paid` 同一口徑；D7 金額鎖定用，不封頂在小計）。"""
    leg, _d = legacy_paid(conn, quote_no, item_id, order)
    return _money(leg + sum(float(ln["amount"] or 0) for pay in list_for_order(conn, quote_no, item_id) for ln in lines_of(conn, pay["id"])))


def room_for(conn, quote_no, order, exclude_id=None) -> float:
    """還能申請的額度＝叫料單小計 − 舊單歷史已付 − 其他申請已鎖額度。"""
    leg, _d = legacy_paid(conn, quote_no, order.get("itemId"), order)
    return _money(order_total(order) - leg - committed(conn, quote_no, order.get("itemId"), exclude_id))


def quota_summary(conn, quote_no, order) -> dict:
    """`{total, legacyPaid, committed, remaining}`（給畫面「已申請 X／剩餘 Y」）。"""
    leg, _d = legacy_paid(conn, quote_no, order.get("itemId"), order)
    c = committed(conn, quote_no, order.get("itemId"))
    return {"total": order_total(order), "legacyPaid": leg, "committed": c, "remaining": room_for(conn, quote_no, order)}


def next_doc_code(conn, today: str = "") -> str:
    """`MP-YYYYMMDD-NNNN`；呼叫端要已持有寫鎖（begin_write）；doc_code 另有唯一索引擋底。"""
    day = (today or date.today().isoformat()).replace("-", "")
    stem = "%s-%s-" % (DOC_PREFIX, day)
    row = conn.execute("SELECT MAX(doc_code) FROM case_material_payments WHERE doc_code LIKE ? AND LENGTH(doc_code)=?",
                       (stem + "%", len(stem) + 4)).fetchone()
    last = int(row[0][-4:]) if row and row[0] else 0
    return "%s%04d" % (stem, last + 1)


def _appr(row) -> dict:
    try:
        d = json.loads(row.get("approval_json") or "{}")
    except (TypeError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def snapshot_of(row) -> dict:
    try:
        d = json.loads(row.get("snapshot_json") or "{}")
    except (TypeError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


# ── 供應商與收款帳戶 ─────────────────────────────────────────────────

def supplier_brief(conn, supplier_id):
    """⇒ `{id, code, name}`；沒有 ⇒ None。供應商主檔是 L1 表 `suppliers`（db.py）；沒有銀行欄位，帳戶一律填在申請上。"""
    try:
        r = conn.execute("SELECT id, code, name FROM suppliers WHERE id=?", (int(supplier_id),)).fetchone()
    except (TypeError, ValueError):
        return None
    return {"id": r["id"], "code": r["code"] or "", "name": r["name"] or ""} if r else None


def _payee(body: dict) -> dict:
    """收款帳戶（銀行代碼、銀行名稱、戶名、帳號）；全部選填但帳號／戶名要成對——出納付款前看得到才能付。"""
    b = body or {}
    out = {"bankCode": str(b.get("bankCode") or "").strip(), "bankName": str(b.get("bankName") or "").strip(),
           "bankAccountName": str(b.get("bankAccountName") or "").strip(), "bankAccountNumber": str(b.get("bankAccountNumber") or "").strip()}
    return out


def _check_payee(p: dict):
    if not p["bankAccountNumber"] or not p["bankAccountName"]:
        raise MaterialPaymentError(400, "請填收款帳戶的戶名與帳號")


# ── 建立／修改（草稿）────────────────────────────────────────────────

def _check_order_for_payment(conn, quote_no, order):
    if not order:
        raise MaterialPaymentError(404, "找不到這筆材料申請")
    st = MA.status_of(conn, quote_no, order.get("itemId"))
    if not MA.counts_as_approved(st):                       # 舊單（''）不溯及既往，可直接開；其餘要已核准
        raise MaterialPaymentError(409, "材料申請「%s」尚未核准，不能開匯款申請" % (st or "—"))
    if order_total(order) <= 0:
        raise MaterialPaymentError(409, "$0 的材料申請不能開匯款申請")


def _check_cap(conn, quote_no, order, amount, exclude_id, user, reason):
    """跨申請累計上限；超過 ⇒ superadmin＋理由才可覆寫。回要存的 over_cap_reason（沒超過 ''）。"""
    room = room_for(conn, quote_no, order, exclude_id)
    if amount <= room + 0.005:
        return ""
    if user.get("role") == "superadmin" and (reason or "").strip():
        return reason.strip()
    raise MaterialPaymentError(409, "超過這張材料申請的可申請額度（小計 %s，已付／其他申請已佔 %s，剩餘 %s）%s" % (
        format(order_total(order), ",.0f"), format(_money(order_total(order) - room), ",.0f"), format(max(room, 0), ",.0f"),
        "；superadmin 可填理由覆寫" if user.get("role") != "superadmin" else "；請填覆寫理由"))


def _amount(v, label="申請金額"):
    if isinstance(v, bool) or v is None or (isinstance(v, str) and not v.strip()):
        raise MaterialPaymentError(400, "%s格式不正確" % label)
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise MaterialPaymentError(400, "%s格式不正確" % label)
    if not math.isfinite(f) or f <= 0:
        raise MaterialPaymentError(400, "%s必須大於 0" % label)
    return r2(f)


def _has_valid_po_link(conn, quote_no: str, order: dict) -> bool:
    """材料申請目前是否連到**有效**的採購單（`purchase_items._link_check`）。只看 `poDocCode` 有沒有填會讓採購單作廢後的申請
    既不能走採購單請款、又不能匯款（金額已回到材料申請，付款出口卻被關；2e 第 32 包探針）。"""
    if not str((order or {}).get("poDocCode") or "").strip():
        return False
    from modules.case import purchase_items as PI
    _, rows = PI._case_state(conn, quote_no)
    return PI._link_check(order, [r for r in rows if (r["kind"] or "") == PI.ORD])[0]


def create(conn, quote_no: str, order: dict, user: dict, body: dict) -> dict:
    """開一張匯款申請（草稿）。`body`＝{amount?, supplierId?, bankCode, bankName, bankAccountName, bankAccountNumber, overCapReason?}；
    金額不帶＝叫料單剩餘額度。供應商：叫料單上的 `supplierId`，沒有（舊單）就要在 body 給。"""
    _check_order_for_payment(conn, quote_no, order)
    if _has_valid_po_link(conn, quote_no, order):                              # 32-S4（33 修正：只認「有效」連結，連結失效＝採購單作廢／退回後不再卡住匯款）：已對應採購單的材料申請，付款走採購單的請款流程，不能另開匯款申請（避免同一筆錢付兩次）
        raise MaterialPaymentError(409, "這筆材料申請已對應採購單 %s，請走採購單的請款流程，不能另開匯款申請" % str(order.get("poDocCode")).strip())
    item_id = str(order.get("itemId"))
    sid = (body or {}).get("supplierId") or order.get("supplierId")
    sup = supplier_brief(conn, sid) if sid not in (None, "") else None
    if sup is None:
        raise MaterialPaymentError(400, "請選擇供應商（材料申請沒有指定供應商，或指定的供應商不存在）")
    payee = _payee(body)
    _check_payee(payee)
    room = room_for(conn, quote_no, order)
    raw = (body or {}).get("amount")
    amount = room if raw in (None, "") else _amount(raw)
    if amount <= 0:
        raise MaterialPaymentError(409, "這張材料申請已沒有可申請的額度")
    over = _check_cap(conn, quote_no, order, amount, None, user, (body or {}).get("overCapReason"))
    now = _now()
    seq = int(conn.execute("SELECT COALESCE(MAX(seq),0) FROM case_material_payments WHERE quote_no=? AND item_id=?", (quote_no, item_id)).fetchone()[0]) + 1
    leg_amt, leg_date = legacy_paid(conn, quote_no, item_id, order)
    snap = {"legacyPaid": leg_amt, "legacyPaidDate": leg_date, "orderDocCode": (MA.get(conn, quote_no, item_id) or {}).get("doc_code", ""), "itemName": order.get("itemName") or "",
            "quantity": order.get("quantity"), "unit": order.get("unit") or "", "unitPrice": order.get("unitPrice"),
            "totalPrice": order_total(order), "supplierId": sup["id"], "supplierCode": sup["code"], "supplierName": sup["name"], **payee}
    appr = {"history": [{"at": now, "by": user["username"], "byDisplay": _display(user), "action": "create", "tier": 0, "comment": ""}]}
    code = next_doc_code(conn)
    cur = conn.execute(
        "INSERT INTO case_material_payments (doc_code, quote_no, item_id, seq, supplier_id, amount_approved, over_cap_reason, snapshot_json, status,"
        " approval_json, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (code, quote_no, item_id, seq, sup["id"], amount, over, json.dumps(snap, ensure_ascii=False), S_DRAFT,
         json.dumps(appr, ensure_ascii=False), user["username"], now, now))
    return get(conn, cur.lastrowid)


def update_draft(conn, pid, order: dict, user: dict, body: dict) -> dict:
    """修改草稿／已退回的申請（金額、供應商、收款帳戶）；重新檢查額度。其他狀態 ⇒ 409。"""
    row = get(conn, pid)
    if row is None:
        raise MaterialPaymentError(404, "找不到這張匯款申請")
    if row["status"] not in EDITABLE:
        raise MaterialPaymentError(409, "「%s」的匯款申請不可修改" % row["status"])
    snap = snapshot_of(row)
    if "supplierId" in (body or {}) and (body or {}).get("supplierId") not in (None, ""):
        sup = supplier_brief(conn, body["supplierId"])
        if sup is None:
            raise MaterialPaymentError(400, "供應商不存在")
        snap.update({"supplierId": sup["id"], "supplierCode": sup["code"], "supplierName": sup["name"]})
    else:
        sup = {"id": row["supplier_id"]}
    if any(k in (body or {}) for k in ("bankCode", "bankName", "bankAccountName", "bankAccountNumber")):
        merged = {k: (body.get(k) if k in body else snap.get(k, "")) for k in ("bankCode", "bankName", "bankAccountName", "bankAccountNumber")}
        p = _payee(merged)
        _check_payee(p)
        snap.update(p)
    amount = float(row["amount_approved"])
    over = row["over_cap_reason"]
    if "amount" in (body or {}) and body["amount"] not in (None, ""):
        amount = _amount(body["amount"])
        over = _check_cap(conn, row["quote_no"], order, amount, row["id"], user, (body or {}).get("overCapReason"))
    now = _now()
    conn.execute("UPDATE case_material_payments SET supplier_id=?, amount_approved=?, over_cap_reason=?, snapshot_json=?, updated_at=? WHERE id=?",
                 (sup["id"], amount, over, json.dumps(snap, ensure_ascii=False), now, row["id"]))
    return get(conn, row["id"])


# ── 簽核狀態機 ────────────────────────────────────────────────────────

def _save(conn, pid, status, appr, now, **extra):
    sets, args = ["status=?", "approval_json=?", "updated_at=?"], [status, json.dumps(appr, ensure_ascii=False), now]
    for k, v in extra.items():
        sets.append("%s=?" % k)
        args.append(v)
    args.append(int(pid))
    conn.execute("UPDATE case_material_payments SET %s WHERE id=?" % ", ".join(sets), args)


def submit(conn, pid, order: dict, user: dict) -> dict:
    """送審（草稿／已退回 → 待審核；沒設簽核層 ⇒ 直接已核准）。送審時再檢查叫料單狀態與額度（退回期間額度可能已被佔用）。"""
    row = get(conn, pid)
    if row is None:
        raise MaterialPaymentError(404, "找不到這張匯款申請")
    if row["status"] not in EDITABLE:
        raise MaterialPaymentError(409, "「%s」狀態不可送審" % row["status"])
    _check_order_for_payment(conn, row["quote_no"], order)
    if float(row["amount_approved"]) > room_for(conn, row["quote_no"], order, row["id"]) + 0.005 and not row["over_cap_reason"]:
        raise MaterialPaymentError(409, "額度已被其他匯款申請佔用，請調降金額後再送審")
    flow = resolve_active_flow_setting(DOC_TYPE)
    try:
        tiers = setting_to_active_tiers(flow, conn, user["username"])
    except UnresolvedManagerError as e:
        raise MaterialPaymentError(400, str(e))
    now = _now()
    appr = _appr(row)
    hist = appr.get("history") or []
    if not tiers:
        appr.update({"autoApproved": True, "note": "未設定任何簽核層，送審即視為核准", "requestedBy": user["username"],
                     "requestedByDisplay": _display(user), "requestedAt": now})
        hist.append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "submit", "tier": 0, "comment": "自動核准"})
        appr["history"] = hist
        _save(conn, pid, S_APPROVED, appr, now, submitted_by=user["username"], submitted_at=now, approved_at=now)
        return {"status": S_APPROVED, "tierCount": 0, "firstApprovers": [], "autoApproved": True}
    appr = {"requestedBy": user["username"], "requestedByDisplay": _display(user), "requestedAt": now, "tiers": tiers, "currentTier": 0,
            "history": hist + [{"at": now, "by": user["username"], "byDisplay": _display(user), "action": "submit", "tier": 0, "comment": ""}]}
    _save(conn, pid, S_PENDING, appr, now, submitted_by=user["username"], submitted_at=now)
    return {"status": S_PENDING, "tierCount": len(tiers), "firstApprovers": [a["username"] for a in (tiers[0].get("approvers") or [])],
            "autoApproved": False}


def approve(conn, pid, order: dict, user: dict, comment: str = "", cascade: bool = False) -> dict:
    row = get(conn, pid)
    if row is None:
        raise MaterialPaymentError(404, "找不到這張匯款申請")
    if row["status"] not in IN_FLIGHT:
        raise MaterialPaymentError(409, "「%s」狀態不在簽核中" % row["status"])
    appr = _appr(row)
    tiers = active_tiers(appr)
    ct = current_tier_idx(appr)
    if tiers:
        ok, code, msg = check_approve_permission(tiers, ct, user["username"], conn)
        if not ok:
            raise MaterialPaymentError(code, msg)
    else:
        err = check_no_tier_self_approval(conn, appr, user)
        if err:
            raise MaterialPaymentError(403, err)
    now = _now()
    tier_done = sign_first_pending(tiers[ct], user, now, conn=conn) if tiers else True
    cascaded = cascade_self_tiers(tiers, ct, user["username"], now, conn=conn) if (tiers and tier_done and cascade) else []
    appr["tiers"] = tiers
    appr["currentTier"] = (ct + 1 + len(cascaded)) if tier_done else ct
    done = appr["currentTier"] >= len(tiers)
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "approve", "tier": ct, "comment": comment or ""})
    if done:                                                                          # 最後一層：叫料單必須還可用（沒被取消）
        st = MA.status_of(conn, row["quote_no"], row["item_id"])
        if not MA.counts_as_approved(st):
            raise MaterialPaymentError(409, "材料申請已不是核准狀態（%s），這張匯款申請不能核准" % (st or "—"))
    if done:                                                                         # 明列關鍵字（守門 test_case_summary_purpose：禁止 ** 傳參數）
        _save(conn, pid, S_APPROVED, appr, now, approved_at=now)
    else:
        _save(conn, pid, S_IN_PROGRESS, appr, now)
    nxt = [] if done else [a["username"] for a in (tiers[appr["currentTier"]].get("approvers") or [])]
    return {"status": S_APPROVED if done else S_IN_PROGRESS, "currentTier": appr["currentTier"], "nextApprovers": nxt,
            "requester": appr.get("requestedBy", ""), "done": done, "tierNo": appr["currentTier"] + 1, "totalTiers": len(tiers)}


def reject(conn, pid, user: dict, reason: str) -> dict:
    row = get(conn, pid)
    if row is None:
        raise MaterialPaymentError(404, "找不到這張匯款申請")
    if row["status"] not in IN_FLIGHT:
        raise MaterialPaymentError(409, "「%s」狀態不在簽核中" % row["status"])
    appr = _appr(row)
    tiers = active_tiers(appr)
    ct = current_tier_idx(appr)
    ok, code, msg = check_reject_permission(tiers, ct, user, conn)
    if not ok:
        raise MaterialPaymentError(code, msg)
    text = (reason or "").strip()
    if not text:
        raise MaterialPaymentError(400, "退回要填原因")
    now = _now()
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "reject", "tier": ct, "comment": text})
    appr.update({"rejectedAt": now, "rejectedByDisplay": _display(user), "rejectReason": text})
    _save(conn, pid, S_RETURNED, appr, now)
    return {"status": S_RETURNED, "requester": appr.get("requestedBy", ""), "reason": text}


def withdraw(conn, pid, user: dict) -> dict:
    row = get(conn, pid)
    if row is None:
        raise MaterialPaymentError(404, "找不到這張匯款申請")
    if row["status"] not in IN_FLIGHT:
        raise MaterialPaymentError(409, "「%s」狀態不可撤回" % row["status"])
    appr = _appr(row)
    if user["username"] != appr.get("requestedBy") and not has_finance_access(user):          # 第42班
        raise MaterialPaymentError(403, "只有送審人本人或財務角色可以撤回")
    now = _now()
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "withdraw", "tier": current_tier_idx(appr), "comment": ""})
    for k in ("tiers", "currentTier"):
        appr.pop(k, None)
    _save(conn, pid, S_DRAFT, appr, now)
    return {"status": S_DRAFT}


def void(conn, pid, user: dict, reason: str) -> dict:
    """作廢（額度釋出）：草稿／已退回／已核准且**沒有付款明細**的申請；建單人本人（草稿／已退回）或 admin 以上；理由必填。
    已有付款明細 ⇒ 不可作廢（錢已經付了）。審核中請先撤回。"""
    row = get(conn, pid)
    if row is None:
        raise MaterialPaymentError(404, "找不到這張匯款申請")
    if row["status"] in (S_VOID,):
        raise MaterialPaymentError(409, "這張匯款申請已作廢")
    if row["status"] in IN_FLIGHT:
        raise MaterialPaymentError(409, "審核中的匯款申請請先撤回，再作廢")
    if not has_finance_access(user) and not (row["status"] in EDITABLE and user["username"] == row["created_by"]):          # 第42班
        raise MaterialPaymentError(403, "只有建單人（草稿／已退回）或財務角色可以作廢匯款申請")
    if lines_of(conn, pid):
        raise MaterialPaymentError(409, "這張匯款申請已有付款明細，不可作廢")
    text = (reason or "").strip()
    if not text:
        raise MaterialPaymentError(400, "作廢要填原因")
    now = _now()
    appr = _appr(row)
    appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _display(user), "action": "void", "tier": 0, "comment": text})
    _save(conn, pid, S_VOID, appr, now, void_reason=text, voided_by=user["username"], voided_at=now)
    return {"status": S_VOID}


def has_live_payments(conn, quote_no, item_id) -> bool:
    """這張叫料單還有沒作廢的匯款申請？（取消叫料單前的檢查）"""
    return conn.execute("SELECT 1 FROM case_material_payments WHERE quote_no=? AND item_id=? AND status<>? LIMIT 1", (quote_no, str(item_id), S_VOID)).fetchone() is not None


def has_any_payments(conn, quote_no, item_id) -> bool:
    """這張叫料單有沒有任何匯款申請紀錄（含作廢）——有就不可刪除叫料列（紀錄要留）。"""
    return conn.execute("SELECT 1 FROM case_material_payments WHERE quote_no=? AND item_id=? LIMIT 1", (quote_no, str(item_id))).fetchone() is not None


# ── 付款明細（出納）──────────────────────────────────────────────────

def _num(v, label):
    if isinstance(v, bool) or v is None or (isinstance(v, str) and not v.strip()):
        raise BadRemit("%s格式不正確" % label)
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise BadRemit("%s格式不正確" % label)
    if not math.isfinite(f):
        raise BadRemit("%s格式不正確" % label)
    return r2(f)


def parse_line(body, remaining):
    """出納 body ⇒ `{amount, fee, review}`。實付不帶＝剩餘應付；> 0；手續費要勾 hasFee（公司自付）；
    實付超過剩餘（多付）⇒ review='pending'，少付＝分次付款（無審核）。"""
    body = body or {}
    remaining = _money(remaining)
    raw = body.get("actualAmount", body.get("actual_amount"))
    amount = remaining if raw in (None, "") else _num(raw, "實付金額")
    if amount <= 0:
        raise BadRemit("實付金額必須大於 0")
    fee = 0.0
    if body.get("hasFee", body.get("has_fee")):
        fee = _num(body.get("fee", body.get("remit_fee")), "手續費")
        if fee < 0:
            raise BadRemit("手續費不可為負數")
        if fee > amount:
            raise BadRemit("手續費不可超過實付金額")
    over_pay = amount > remaining + 0.005
    return {"amount": amount, "fee": fee, "diff": r2(amount - remaining) if amount > remaining else 0.0,
            "review": REVIEW_PENDING if (over_pay or fee > FEE_REVIEW_OVER) else ""}


def add_line(conn, pid, paid_date, user, body) -> dict:
    """出納登錄一筆付款。申請必須「已核准」；沒有剩餘（已結清）⇒ 409。原子：呼叫端已持有寫鎖。
    寫入後把明細合計投影回叫料單（`sync_order_paid`）。回 `{line, remaining, paid, settled, ...}`。"""
    row = get(conn, pid)
    if row is None:
        raise LookupError("找不到這張匯款申請")
    if row["status"] != S_APPROVED:
        raise ValueError("這張匯款申請還沒核准（%s），不能登錄付款" % row["status"])
    remaining = remaining_of(conn, row)
    if remaining <= 0:
        raise ValueError("這張匯款申請已結清，沒有待付金額")
    ln = parse_line(body, remaining)
    now = _now()
    cur = conn.execute(
        "INSERT INTO case_material_payment_lines (payment_id, paid_at, amount, fee, remit_review, pay_method, pay_account_code, paid_by, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (row["id"], paid_date, ln["amount"], ln["fee"], ln["review"], str((body or {}).get("payMethod") or "").strip(),
         str((body or {}).get("payAccountCode") or "").strip(), user.get("username") or "", now))
    sync_order_paid(conn, row["quote_no"], row["item_id"])
    paid = paid_total(conn, row["id"])
    snap = snapshot_of(row)
    return {"lineId": cur.lastrowid, "quoteNo": row["quote_no"], "itemId": row["item_id"], "docCode": row["doc_code"], "amount": float(row["amount_approved"]),
            "paid": paid, "remaining": _money(float(row["amount_approved"]) - paid), "settled": paid >= float(row["amount_approved"]) - 0.005,
            "actual": ln["amount"], "fee": ln["fee"], "diff": ln["diff"], "remitReview": ln["review"],
            "title": "材料申請｜%s（%s）" % (snap.get("itemName") or "", row["doc_code"]), "payee": snap.get("supplierName") or ""}


def decide_line(conn, line_id, decision, user, note="") -> dict:
    """差額（多付）審核：approve ⇒ 核可；reject ⇒ 刪除這筆明細（回待付款）。登錄付款的人不能自己審。"""
    if decision not in ("approve", "reject"):
        raise BadRemit("decision 必須為 approve 或 reject")
    ln = conn.execute("SELECT * FROM case_material_payment_lines WHERE id=?", (int(line_id),)).fetchone()
    if not ln:
        raise LookupError("找不到這筆付款")
    pay = get(conn, ln["payment_id"])
    if ln["remit_review"] == REVIEW_PENDING and (ln["paid_by"] or "") in (user.get("username") or "\0",):
        raise RemitForbidden("這筆付款是您自己登錄的，差額需由其他財務角色成員或最高管理者審核")
    now = _now()
    who = _display(user)
    if decision == "approve":
        cur = conn.execute("UPDATE case_material_payment_lines SET remit_review=?, remit_review_by=?, remit_review_at=?, remit_review_note=? WHERE id=? AND remit_review=?",
                           (REVIEW_APPROVED, who, now, note, ln["id"], REVIEW_PENDING))
    else:
        cur = conn.execute("DELETE FROM case_material_payment_lines WHERE id=? AND remit_review=?", (ln["id"], REVIEW_PENDING))
    if cur.rowcount == 0:
        raise ValueError("這筆付款不是待審核狀態（可能已被處理）")
    sync_order_paid(conn, pay["quote_no"], pay["item_id"])
    return {"quoteNo": pay["quote_no"], "key": str(ln["id"]), "decision": decision}


def lines_by_order(conn) -> dict:
    """`{(quote_no, item_id): [{id, paid_at, amount, fee, review, payment_id, doc_code, pay_method, pay_account_code}]}`——現金口徑／總帳讀付款明細用。
    表不在（舊庫）⇒ 空。"""
    out = {}
    try:
        rows = conn.execute("SELECT l.*, p.quote_no, p.item_id, p.doc_code FROM case_material_payment_lines l"
                            " JOIN case_material_payments p ON p.id = l.payment_id ORDER BY l.paid_at, l.id").fetchall()
    except Exception:                                                                       # noqa: BLE001
        return {}
    for r in rows:
        out.setdefault((r["quote_no"], r["item_id"]), []).append(
            {"id": r["id"], "paid_at": (r["paid_at"] or "")[:10], "amount": float(r["amount"] or 0), "fee": float(r["fee"] or 0),
             "review": r["remit_review"] or "", "payment_id": r["payment_id"], "doc_code": r["doc_code"],
             "pay_method": r["pay_method"] or "", "pay_account_code": r["pay_account_code"] or ""})
    return out


def legacy_by_order(conn) -> dict:
    """有匯款申請的叫料單的舊單歷史已付 `{(quote_no, item_id): (amount, date)}`（現金口徑：這些叫料單不再讀 JSON 的 paid*）。"""
    out = {}
    try:
        rows = conn.execute("SELECT quote_no, item_id, snapshot_json FROM case_material_payments ORDER BY seq").fetchall()
    except Exception:                                                                       # noqa: BLE001
        return {}
    for r in rows:
        k = (r["quote_no"], r["item_id"])
        if k in out:
            continue
        try:
            sn = json.loads(r["snapshot_json"] or "{}") or {}
        except (TypeError, ValueError):
            sn = {}
        out[k] = (_money(sn.get("legacyPaid")), str(sn.get("legacyPaidDate") or "")[:10])
    return out


# ── 叫料單的 paid* 投影（唯一寫入點）──────────────────────────────────

def sync_order_paid(conn, quote_no, item_id):
    """把這張叫料單所有申請的付款明細合計寫回 `materialOrders[].paidStatus／paidAmount／paidDate`（0＝pending；<小計＝partial；≥小計＝paid；
    日期＝最後付款日）。**G-M1：這是 `modules/case` 裡唯一允許寫 paid* 的函式**；直接改 `quotations.data_json`，不經 `material_guard`
    （閘管的是使用者送來的 body，這是匯款流程自己的投影）。呼叫端已持有寫鎖。叫料單不存在 ⇒ 略過（回 False）。"""
    r = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not r:
        return False
    try:
        data = json.loads(r["data_json"] or "{}") or {}
    except (TypeError, ValueError):
        return False
    orders = (data.get("caseRecord") or {}).get("materialOrders")
    if not isinstance(orders, list):
        return False
    target = next((o for o in orders if isinstance(o, dict) and str(o.get("itemId")) == str(item_id)), None)
    if target is None:
        return False
    lines = [ln for pay in list_for_order(conn, quote_no, item_id) for ln in lines_of(conn, pay["id"])]
    leg_amt, leg_date = legacy_paid(conn, quote_no, item_id, target)               # 舊單歷史已付（第一張申請時凍結）
    tot = order_total(target)
    total_paid = _money(leg_amt + sum(float(ln["amount"] or 0) for ln in lines))
    last = max([(ln["paid_at"] or "")[:10] for ln in lines] + [leg_date])
    if total_paid <= 0:
        target.update({"paidStatus": "pending", "paidAmount": 0, "paidDate": ""})
    else:                                                                            # 多付時 paidAmount 封頂在小計（明細才是事實；閘的驗證要求 ≤ 小計）
        target.update({"paidStatus": "paid" if total_paid >= tot - 0.005 else "partial", "paidAmount": min(total_paid, tot), "paidDate": last})
    conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(data, ensure_ascii=False), quote_no))
    return True
