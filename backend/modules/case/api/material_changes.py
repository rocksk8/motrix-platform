# -*- coding: utf-8 -*-
"""材料申請「變更申請」端點（33-M2b）與簽核佇列提供者（`approval.queue_items`／`approval.detail`）。

狀態機與原子套用在 `modules/case/material_change.py`（M2a）；本檔只做 HTTP：權限、讀寫、稽核、通知。設計 docs/platform/plans/MATERIAL-CHANGE-REQUEST-DESIGN.md。
權限（同材料申請審核）：建立／修改／送審／撤回＝案件擁有者規則（`require_case`）＋財務檢視權；核准／退回＝**當層簽核人**（不另做案件守門，回應不含金額）。
金額欄位（單價、小計、涵蓋行金額）看不到財務檢視者不給（L1 規則）。所有寫入先 commit 再通知（`_notify` 自己開連線）；套用失敗整個交易回滾。
"""
import json

from fastapi import APIRouter, Body, Header, HTTPException

from core.txn import begin_write
from db import get_db
from helpers import _notify, _require_user
from helpers.approval_queue import approval_raw_of as _approval_raw_of, tier_fields as _queue_tier_fields
from helpers.case_access import require_case
from helpers.financial_mask import money_visible
from modules.case import material_approval as MA
from modules.case import material_change as MC
from modules.case import material_notify as MN

router = APIRouter()

_BASE = "/api/quotations/{quote_no}/material-orders/{item_id}"
_CHG = "/api/quotations/{quote_no}/material-changes/{change_id}"


def _http(e: MC.MaterialChangeError) -> HTTPException:
    return HTTPException(e.status, e.message)


def _load_case(conn, quote_no: str):
    q = MA.case_row(conn, quote_no)
    if not q:
        raise HTTPException(404, "報價單 %s 不存在" % quote_no)
    return q


def _order_name(q, item_id) -> str:
    try:
        for o in (((json.loads(q["data_json"] or "{}") or {}).get("caseRecord") or {}).get("materialOrders") or []):
            if isinstance(o, dict) and str(o.get("itemId")) == str(item_id):
                return str(o.get("itemName") or "")
    except (TypeError, ValueError):
        pass
    return ""


def _info(ch, q):
    return {"docCode": ch["doc_code"], "quoteNo": ch["quote_no"], "itemName": _order_name(q, ch["item_id"])}


_MONEY_KEYS = ("unitPrice", "totalPrice", "amount")


def _mask(v, money: bool):
    """看不到財務檢視者：金額欄位（單價、小計、涵蓋行的 amount）一律拿掉——遞迴到巢狀的涵蓋行與差異裡的新舊值（da：poSnapshot 的行金額曾漏出）。"""
    if money:
        return v
    if isinstance(v, dict):
        return {k: _mask(x, False) for k, x in v.items() if k not in _MONEY_KEYS}
    if isinstance(v, list):
        return [_mask(x, False) for x in v]
    return v


def _mask_diff(diff, money: bool):
    """差異：金額欄位（money=true）整項遮成 hidden；其餘項（含 poSnapshot 的新舊涵蓋行）去掉行金額。"""
    if money:
        return diff
    return [{"field": d["field"], "old": None, "new": None, "money": True, "hidden": True} if d.get("money")
            else {**d, "old": _mask(d.get("old"), False), "new": _mask(d.get("new"), False)} for d in diff or []]


def _view(ch, money: bool) -> dict:
    appr = MC._j(ch["approval_json"], {})
    tiers = appr.get("tiers") or []
    ct = appr.get("currentTier") or 0
    cur = [a.get("displayName") or a.get("username") for a in (tiers[ct].get("approvers") or [])] if tiers and ct < len(tiers) else []
    diff = _mask_diff(MC._j(ch["diff_json"], []), money)
    prop = _mask(MC._j(ch["proposal_json"], {}), money)
    base = _mask(MC._j(ch["base_json"], {}), money)
    return {"id": ch["id"], "docCode": ch["doc_code"], "quoteNo": ch["quote_no"], "itemId": ch["item_id"], "status": ch["status"], "baseVersion": ch["base_version"],
            "reason": ch["reason"], "diff": diff, "proposal": prop, "base": base, "createdBy": ch["created_by"], "createdAt": ch["created_at"],
            "submittedAt": ch["submitted_at"], "approvedAt": ch["approved_at"], "appliedAt": ch["applied_at"],
            "requestedBy": appr.get("requestedByDisplay") or appr.get("requestedBy") or "", "tierCount": len(tiers), "currentTier": ct, "currentApprovers": cur,
            "rejectReason": appr.get("rejectReason") if ch["status"] == MC.S_RETURNED else ""}


def _change_for(conn, quote_no, change_id):
    ch = MC.get(conn, change_id)
    if ch is None or ch["quote_no"] != quote_no:
        raise HTTPException(404, "找不到這張變更申請")
    return ch


# ── 讀 ──────────────────────────────────────────────────────────────

@router.get("/api/quotations/{quote_no}/material-changes")
def list_case_changes(quote_no: str, authorization: str = Header(None)):
    """這個案件所有材料申請的變更申請（新到舊；案件頁的變更申請面板用）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        money = money_visible(user)
        return {"quoteNo": quote_no, "changes": [_view(c, money) | {"itemName": _order_name(q, c["item_id"])} for c in MC.list_for_case(conn, quote_no)]}
    finally:
        conn.close()


@router.get("/api/quotations/{quote_no}/material-orders/{item_id}/changes")             # 字面路徑：case_read_scope 的掃描只認字串常數
def list_changes(quote_no: str, item_id: str, authorization: str = Header(None)):
    """這筆材料申請的變更申請（新到舊）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        money = money_visible(user)
        return {"quoteNo": quote_no, "itemId": item_id, "changes": [_view(c, money) for c in MC.list_for_item(conn, quote_no, item_id)]}
    finally:
        conn.close()


@router.get("/api/quotations/{quote_no}/material-orders/{item_id}/change-proposal")
def preview_proposal(quote_no: str, item_id: str, quantity: float = None, notes: str = None, authorization: str = Header(None)):
    """變更提案預覽（唯讀；內容由案件側 `change_proposal` 組成）：`{before, after, diff, uncoveredLines, problems}`。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        proposed = {k: v for k, v in (("quantity", quantity), ("notes", notes)) if v is not None}
        try:
            cp = MC.proposal(conn, quote_no, item_id, proposed)
        except MC.MaterialChangeError as e:
            raise _http(e)
        money = money_visible(user)
        if not money:
            cp = {**cp, "before": _mask(cp.get("before"), False), "after": _mask(cp.get("after"), False), "diff": _mask_diff(cp.get("diff"), False),
                  "uncoveredLines": _mask(cp.get("uncoveredLines"), False),
                  "problems": [{**p, "message": "變更後小計低於已付金額"} if p.get("code") == "below_paid" else p for p in cp.get("problems") or []]}      # 訊息帶已付金額數字：非財務者只留文字
        return cp
    finally:
        conn.close()


# ── 寫 ──────────────────────────────────────────────────────────────

def _notify_after(event, info, res, reason=""):
    """寫入已 commit 之後：站內通知＋信件（附帶動作，不可讓簽核失敗）。"""
    try:
        if event in ("submitted", "next_tier"):
            users = res.get("firstApprovers") if event == "submitted" else res.get("nextApprovers")
            for u in users or []:
                _notify(u, "material_change_approval_request", info["docCode"], info["quoteNo"], "材料申請變更 %s（%s）需要您簽核" % (info["docCode"], info["itemName"]))
            MN.fire_change(event, info, approvers=users, tier_no=res.get("tierNo", 0), total_tiers=res.get("totalTiers", 0))
        elif event == "approved":
            if res.get("requester"):
                _notify(res["requester"], "material_change_approved", info["docCode"], info["quoteNo"], "材料申請變更 %s（%s）已核准並套用" % (info["docCode"], info["itemName"]))
            MN.fire_change("approved", info, requester=res.get("requester") or "")
        elif event == "returned":
            if res.get("requester"):
                _notify(res["requester"], "material_change_returned", info["docCode"], info["quoteNo"],
                        "材料申請變更 %s（%s）已被退回：%s" % (info["docCode"], info["itemName"], reason))
            MN.fire_change("returned", info, requester=res.get("requester") or "", reason=reason)
    except Exception:                                                              # noqa: BLE001
        pass


def _guard_write(user, q, quote_no):
    require_case(user, q, quote_no)
    if not money_visible(user):
        raise HTTPException(403, "此帳號沒有財務檢視權限，不可操作材料申請變更")
    if (q["deal_tag"] or "") == "已結案":
        raise HTTPException(400, "已結案案件無法變更材料申請")


@router.post(_BASE + "/changes")
def create_change(quote_no: str, item_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """建立變更申請（草稿）。body：`{reason（必填）, quantity?, notes?}`——內容（金額、涵蓋採購單行）由已核准的採購單決定，不能手改。"""
    user = _require_user(authorization)
    body = body or {}
    proposed = {k: body[k] for k in ("quantity", "notes") if k in body}
    unknown = [k for k in body if k not in ("reason", "quantity", "notes")]
    if unknown:
        raise HTTPException(400, "不能變更欄位 %s（金額與涵蓋範圍由已核准的採購單決定）" % "、".join(unknown))
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        _guard_write(user, q, quote_no)
        try:
            cp = MC.proposal(conn, quote_no, item_id, proposed)
            ch = MC.create(conn, quote_no, item_id, user, cp, body.get("reason") or "")
        except MC.MaterialChangeError as e:
            raise _http(e)
        conn.commit()
        view = _view(MC.get(conn, ch["id"]), True)
        warnings = ch.get("warnings") or []
    finally:
        conn.close()
    return {"ok": True, "change": view, "warnings": warnings}


@router.post(_CHG + "/revise")
def revise_change(quote_no: str, change_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    """改變更申請內容（草稿／已退回／已撤回；改完回草稿）。body 同建立。"""
    user = _require_user(authorization)
    body = body or {}
    proposed = {k: body[k] for k in ("quantity", "notes") if k in body}
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        _guard_write(user, q, quote_no)
        ch = _change_for(conn, quote_no, change_id)
        try:
            cp = MC.proposal(conn, quote_no, ch["item_id"], proposed)
            out = MC.revise(conn, change_id, user, cp, body.get("reason") or "")
        except MC.MaterialChangeError as e:
            raise _http(e)
        conn.commit()
        view = _view(MC.get(conn, change_id), True)
        warnings = out.get("warnings") or []
    finally:
        conn.close()
    return {"ok": True, "change": view, "warnings": warnings}


@router.post(_CHG + "/submit")
def submit_change(quote_no: str, change_id: int, authorization: str = Header(None)):
    """送審（沒設簽核層 ⇒ 直接核准並套用）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        _guard_write(user, q, quote_no)
        ch = _change_for(conn, quote_no, change_id)
        try:
            res = MC.submit(conn, change_id, user)
        except MC.MaterialChangeError as e:
            raise _http(e)
        conn.commit()
        info = _info(ch, q)
    finally:
        conn.close()
    if res["autoApproved"]:
        _notify_after("approved", info, {"requester": user["username"]})
    else:
        _notify_after("submitted", info, res)
    return {"ok": True, "status": res["status"], "docCode": info["docCode"], "tierCount": res["tierCount"], "autoApproved": res["autoApproved"], "applied": res["applied"]}


@router.post(_CHG + "/approve")
def approve_change(quote_no: str, change_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    """核准當層；最後一層過了 ⇒ 同一個交易內套用到材料申請。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        ch = _change_for(conn, quote_no, change_id)
        try:
            res = MC.approve(conn, change_id, user, comment=(body or {}).get("comment") or "", cascade=bool((body or {}).get("cascade")))
        except MC.MaterialChangeError as e:
            raise _http(e)
        conn.commit()
        info = _info(ch, q)
    finally:
        conn.close()
    _notify_after("approved" if res["done"] else "next_tier", info, res)
    return {"ok": True, "status": res["status"], "currentTier": res["currentTier"], "applied": res["applied"]}


@router.post(_CHG + "/reject")
def reject_change(quote_no: str, change_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    """退回（原因必填）；原材料申請完全不動。"""
    user = _require_user(authorization)
    reason = ((body or {}).get("reason") or "").strip()
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        ch = _change_for(conn, quote_no, change_id)
        try:
            res = MC.reject(conn, change_id, user, reason)
        except MC.MaterialChangeError as e:
            raise _http(e)
        conn.commit()
        info = _info(ch, q)
    finally:
        conn.close()
    _notify_after("returned", info, res, reason=reason)
    return {"ok": True, "status": res["status"]}


@router.post(_CHG + "/withdraw")
def withdraw_change(quote_no: str, change_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        begin_write(conn)
        q = _load_case(conn, quote_no)
        require_case(user, q, quote_no)
        _change_for(conn, quote_no, change_id)
        try:
            res = MC.withdraw(conn, change_id, user)
        except MC.MaterialChangeError as e:
            raise _http(e)
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "status": res["status"]}


# ── 簽核佇列提供者（IP-10 `approval.queue_items`／IP-93 `approval.detail`）─────────────────────────────

def queue_items(conn) -> list:
    """待簽核的材料申請變更（待審核／簽核中）。自帶 `typeLabel／openUrl／approveUrl／rejectUrl／rejectField`；佇列上的單號＝變更單號（`doc_code`）。"""
    out = []
    rows = conn.execute("SELECT c.*, q.customer_name, q.data_json FROM case_material_changes c LEFT JOIN quotations q ON q.quote_no = c.quote_no"
                        " WHERE c.status IN ('待審核','簽核中') ORDER BY c.id DESC").fetchall()
    for r in rows:
        raw = _approval_raw_of(r["approval_json"], "material_change", r["doc_code"])          # 字面值：佇列覆蓋守門（check_approval_queue_coverage）掃提供者源碼找它
        if raw is None:
            continue
        f = _queue_tier_fields(raw)
        prop = MC._j(r["proposal_json"], {})
        base = MC._j(r["base_json"], {})
        name = _order_name(r, r["item_id"])
        base_url = "/api/quotations/%s/material-changes/%d" % (r["quote_no"], r["id"])
        out.append({
            "type": "material_change", "typeLabel": MC.DOC_LABEL, "docCode": r["doc_code"], "quoteNo": r["doc_code"],
            "customer": r["customer_name"] or "", "projectName": "%s（原 %s → 變更後 %s）" % (name, base.get("quantity", ""), prop.get("quantity", "")),
            "total": prop.get("totalPrice") or 0, "quoteDate": (f["requestedAt"] or "")[:10], "salesPerson": "", "requestedBy": f["requestedBy"],
            "requestedByDisplay": f["requestedByDisplay"], "requestedAt": f["requestedAt"], "isEditApproval": False, "reasons": [],
            "tiers": f["tiers"], "currentTier": f["currentTier"], "tierCount": f["tierCount"], "currentApprovers": f["currentApprovers"], "tags": [],
            "linkedQuoteNo": r["quote_no"], "openUrl": "case-management.html?q=%s" % r["quote_no"],
            "approveUrl": base_url + "/approve", "rejectUrl": base_url + "/reject", "rejectField": "reason",
        })
    return out


def _fmt_qty(v):
    return ("%s" % (int(v) if float(v or 0).is_integer() else v)) if v not in (None, "") else "—"


def detail(conn, doc_no):
    """`approval.detail`（name＝material_change）：簽核人看的詳情（差異表）。金額欄位由 L1 依財務檢視權遮蔽（標籤 單價／小計）。"""
    r = conn.execute("SELECT * FROM case_material_changes WHERE doc_code=?", (doc_no,)).fetchone()
    if not r:
        raise HTTPException(404, "材料申請變更不存在")
    q = conn.execute("SELECT data_json, customer_name FROM quotations WHERE quote_no=?", (r["quote_no"],)).fetchone()
    name = _order_name(q, r["item_id"]) if q else ""
    prop, base = MC._j(r["proposal_json"], {}), MC._j(r["base_json"], {})
    unit_b, unit_p = base.get("unit") or "", prop.get("unit") or ""

    def lines(v):
        return "、".join("%s #%s" % (x.get("poDocCode"), x.get("line")) for x in v or []) or "—"
    fields = [{"label": "變更單號", "value": r["doc_code"]}, {"label": "案件", "value": r["quote_no"]}, {"label": "品名", "value": name or "—"},
              {"label": "變更原因", "value": r["reason"] or "—"},
              {"label": "數量", "value": "%s %s → %s %s" % (_fmt_qty(base.get("quantity")), unit_b, _fmt_qty(prop.get("quantity")), unit_p)},
              {"label": "單價", "value": "%s → %s" % (format(float(base.get("unitPrice") or 0), ",.0f"), format(float(prop.get("unitPrice") or 0), ",.0f"))},
              {"label": "小計", "value": "%s → %s" % (format(float(base.get("totalPrice") or 0), ",.0f"), format(float(prop.get("totalPrice") or 0), ",.0f"))},
              {"label": "涵蓋採購單行", "value": "%s → %s" % (lines(base.get("poSnapshot")), lines(prop.get("poSnapshot")))},
              {"label": "備註", "value": "%s → %s" % (base.get("notes") or "—", prop.get("notes") or "—")},
              {"label": "說明", "value": "核准前原材料申請內容照常有效；核准後才切換為變更後的內容。"}]
    return {"quoteNo": r["quote_no"], "approvalRaw": r["approval_json"], "title": "材料申請變更 %s" % r["doc_code"], "fields": fields, "items": [], "files": []}
