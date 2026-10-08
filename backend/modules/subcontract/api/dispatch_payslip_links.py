# -*- coding: utf-8 -*-
"""派發頁的「勞報單」區塊端點（第 46 班 P3；設計 PAYSLIP-APPROVAL-T45.md §6）。資料在 M07：經提供者 `payslip.dispatch_links` 取（M07 不在 ⇒ 明說，不默默略過）。

🔴 Q9：派發頁的使用者不一定是最高管理者 ⇒ 只回**單號、狀態、受領人姓名、開單日期、已作廢旗標**，**沒有金額、扣繳、身分資料、銀行帳號**；
`canOpen`＝呼叫者是最高管理者（頁面據此決定連結可不可點）。新增／解除連結＝最高管理者＋勞報單模組（同勞報單）。
M04 不 import M07：只經 registry 提供者。"""
import json

from fastapi import APIRouter, Body, Header, HTTPException

from core import registry
from db import get_db
from helpers import _audit, _require_user, _tok, guard_case_access, require_any_module

router = APIRouter()
PAYROLL_MISSING = "薪資獎金模組未安裝：派發頁不顯示勞報單"


def _can_open(user) -> bool:
    """勞報單所有端點都是最高管理者（`_require_user(require_superadmin=True, module='payslip')`；最高管理者持有全部模組）⇒ 這裡同一條。"""
    return user.get("role") == "superadmin"


def _dispatch_exists(conn, did) -> bool:
    return conn.execute("SELECT 1 FROM contractor_dispatches WHERE id=?", (did,)).fetchone() is not None


@router.get("/api/contractor-dispatches/{did}/payslip-links")
def list_payslip_links(did: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ("procurement", "case_manage", "contractor_list", "quotation"), "承攬商管理")
    prov = registry.single_provider("payslip.dispatch_links")
    conn = get_db()
    try:
        row = conn.execute("SELECT quote_no FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
        if row is None:
            raise HTTPException(404, "派發紀錄不存在")
        if row["quote_no"] and conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (row["quote_no"],)).fetchone():
            guard_case_access(conn, row["quote_no"], user, allow_module="case_manage")      # 與其他每案端點同一道案件層守門（看不到該案 ⇒ 404）
        if prov is None:
            return {"available": False, "notice": PAYROLL_MISSING, "items": [], "canOpen": False, "canEdit": False}
        items = prov.links_for_dispatch(conn, did)
        by_person, unconfirmed = [], 0
        ids = _personnel_ids(conn.execute("SELECT personnel_json FROM contractor_dispatches WHERE id=?", (did,)).fetchone()["personnel_json"])
        if ids and hasattr(prov, "payslips_for_contractors"):                   # 第 48 班：依「人」顯示該派發人員的已確認勞報單（無金額；舊單名稱推測未確認的只給數字）
            linked = {i["slipNo"] for i in items}
            res = prov.payslips_for_contractors(conn, ids)
            by_person = [x for x in res["items"] if x["slipNo"] not in linked]
            unconfirmed = res["unconfirmedCount"]
    finally:
        conn.close()
    return {"available": True, "notice": "", "items": items, "byPerson": by_person, "unconfirmedCount": unconfirmed,
            "canOpen": _can_open(user), "canEdit": _can_open(user)}


def _guard_edit(user):
    if not _can_open(user):
        raise HTTPException(403, "只有最高管理者（勞報單模組）可以建立或解除勞報單關聯")


@router.post("/api/contractor-dispatches/{did}/payslip-links", status_code=201)
def add_payslip_link(did: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)
    _guard_edit(user)
    slip_no = str((body or {}).get("slipNo") or "").strip()
    if not slip_no:
        raise HTTPException(400, "請帶 slipNo（勞報單單號）")
    prov = registry.single_provider("payslip.dispatch_links")
    if prov is None:
        raise HTTPException(409, PAYROLL_MISSING)
    conn = get_db()
    try:
        if not _dispatch_exists(conn, did):
            raise HTTPException(404, "派發紀錄不存在")
        try:
            res = prov.link(conn, slip_no, did, user, (body or {}).get("note") or "")
        except ValueError as e:
            raise HTTPException(getattr(e, "status", 409), str(e))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "dispatch.payslip_link", "contractor_dispatch", str(did), "派發 #%s 關聯勞報單 %s" % (did, slip_no))
    return {"ok": True, **res}


@router.delete("/api/contractor-dispatches/{did}/payslip-links/{slip_no}")
def remove_payslip_link(did: int, slip_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _guard_edit(user)
    prov = registry.single_provider("payslip.dispatch_links")
    if prov is None:
        raise HTTPException(409, PAYROLL_MISSING)
    conn = get_db()
    try:
        try:
            res = prov.unlink(conn, slip_no, did, user)
        except ValueError as e:
            raise HTTPException(getattr(e, "status", 409), str(e))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "dispatch.payslip_unlink", "contractor_dispatch", str(did), "派發 #%s 解除與勞報單 %s 的關聯" % (did, slip_no))
    return {"ok": True, **res}


def _personnel_ids(raw) -> list:
    """派發 `personnel_json`（[{id, name, amount, note}]）裡的外包名冊人員 id（int、去重、保序）。壞 JSON ⇒ []。"""
    try:
        arr = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    out = []
    for p in arr if isinstance(arr, list) else []:
        try:
            v = int((p or {}).get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if v not in out:
            out.append(v)
    return out


def dispatches_for_person(conn, contractor_id, limit=200) -> list:
    """提供者 `dispatch.by_person`（M04 → M07 勞報單頁；IP-115 暫定）：這位外包名冊人員被排進哪些派發（新到舊）。**不含金額**。"""
    try:
        cid = int(contractor_id)
    except (TypeError, ValueError):
        return []
    out = []
    for r in conn.execute("SELECT d.id, d.doc_code, d.quote_no, d.status, d.dispatch_date, d.personnel_json, v.name AS vendor_name"
                          " FROM contractor_dispatches d LEFT JOIN vendor_contractors v ON v.id = d.vendor_id"
                          " WHERE d.personnel_json LIKE ? ORDER BY d.id DESC", ("%" + str(cid) + "%",)).fetchall():
        if cid in _personnel_ids(r["personnel_json"]):
            out.append({"id": r["id"], "docCode": r["doc_code"] or "", "quoteNo": r["quote_no"] or "", "status": r["status"] or "",
                        "vendorName": r["vendor_name"] or "", "dispatchDate": (r["dispatch_date"] or "")[:10]})
            if len(out) >= limit:
                break
    return out


def dispatch_brief(conn, dispatch_id):
    """提供者 `dispatch.brief`（M04 → M07 勞報單頁）：派發的簡要識別（編號、單號、案件、狀態、廠商名）；查無 ⇒ None。**不含金額**。"""
    r = conn.execute("SELECT d.id, d.doc_code, d.quote_no, d.status, d.dispatch_date, d.personnel_json, v.name AS vendor_name FROM contractor_dispatches d"
                     " LEFT JOIN vendor_contractors v ON v.id = d.vendor_id WHERE d.id=?", (int(dispatch_id),)).fetchone()
    if r is None:
        return None
    return {"id": r["id"], "docCode": r["doc_code"] or "", "quoteNo": r["quote_no"] or "", "status": r["status"] or "", "vendorName": r["vendor_name"] or "",
            "dispatchDate": (r["dispatch_date"] or "")[:10], "personnelIds": _personnel_ids(r["personnel_json"])}
