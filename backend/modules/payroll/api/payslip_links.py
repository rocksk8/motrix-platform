# -*- coding: utf-8 -*-
"""勞報單頁的「來源派發」連結端點（第 46 班 P3；設計 PAYSLIP-APPROVAL-T45.md §6）。全部 superadmin＋`payslip` 模組（同勞報單其他端點）。
派發資料在 M04：經提供者 `dispatch.brief` 取（M04 不在 ⇒ 連結仍可讀，派發欄位空白並說明；不能新增連結）。"""
from fastapi import APIRouter, Body, Header, HTTPException

from core import registry
from db import get_db
from helpers import _audit, _require_user, _tok
from modules.payroll import payslip_links as PL

router = APIRouter()
DISPATCH_MISSING = "外包工班模組未安裝：看不到派發資料，也不能新增派發關聯"


def _brief(conn, dispatch_id):
    fn = registry.single_provider("dispatch.brief")
    return fn(conn, dispatch_id) if fn is not None else None


@router.get("/api/payslips/{slip_no}/dispatch-links")
def list_links(slip_no: str, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module="payslip")
    conn = get_db()
    try:
        if conn.execute("SELECT 1 FROM payslips WHERE slip_no=?", (slip_no,)).fetchone() is None:
            raise HTTPException(404, "找不到此勞報單")
        items = PL.links_for_payslip(conn, slip_no)
        have = registry.single_provider("dispatch.brief") is not None
        for it in items:
            b = _brief(conn, it["dispatchId"]) if have else None
            it["dispatch"] = b or {"id": it["dispatchId"], "docCode": "", "quoteNo": "", "status": "", "vendorName": ""}
    finally:
        conn.close()
    return {"items": items, "notice": "" if have else DISPATCH_MISSING}


@router.post("/api/payslips/{slip_no}/dispatch-links", status_code=201)
def add_link(slip_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module="payslip")
    try:
        did = int((body or {}).get("dispatchId"))
    except (TypeError, ValueError):
        raise HTTPException(400, "請帶 dispatchId（派發編號）")
    conn = get_db()
    try:
        if registry.single_provider("dispatch.brief") is None:
            raise HTTPException(409, DISPATCH_MISSING)
        if _brief(conn, did) is None:
            raise HTTPException(404, "查無此派發")
        try:
            res = PL.link(conn, slip_no, did, user, (body or {}).get("note") or "")
        except PL.LinkError as e:
            raise HTTPException(e.status, str(e))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "payslip.dispatch_link", "payslip", slip_no, "%s 關聯派發 #%s" % (slip_no, did))
    return {"ok": True, **res}


@router.delete("/api/payslips/{slip_no}/dispatch-links/{dispatch_id}")
def remove_link(slip_no: str, dispatch_id: int, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module="payslip")
    conn = get_db()
    try:
        try:
            res = PL.unlink(conn, slip_no, dispatch_id, user)
        except PL.LinkError as e:
            raise HTTPException(e.status, str(e))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "payslip.dispatch_unlink", "payslip", slip_no, "%s 解除與派發 #%s 的關聯" % (slip_no, dispatch_id))
    return {"ok": True, **res}


@router.get("/api/payslip-person-dispatches")
def person_dispatches(contractor_id: int, authorization: str = Header(None)):
    """第 48 班：這位外包名冊人員被排進哪些派發（勞報單表單勾選用）。最高管理者＋勞報單模組；**不含金額**。"""
    user = _require_user(authorization, require_superadmin=True, module="payslip")
    fn = registry.single_provider("dispatch.by_person")
    if fn is None:
        return {"items": [], "notice": DISPATCH_MISSING}
    conn = get_db()
    try:
        items = fn(conn, contractor_id, user=user)
        # 第 51 班：這位人員是否已經有『未作廢的勞報單』連到該派發（勞報單頁預設只勾還沒連過的）。資料在 M07 自己的表，不經提供者。
        linked = {r[0] for r in conn.execute(
            "SELECT DISTINCT l.dispatch_id FROM payslip_dispatch_links l JOIN payslips p ON p.slip_no = l.slip_no"
            " WHERE p.contractor_id = ? AND p.status != '已作廢'", (int(contractor_id),)).fetchall()}
        for it in items:
            it["linkedForThisPerson"] = it["id"] in linked
    finally:
        conn.close()
    return {"items": items, "notice": ""}


@router.get("/api/payslip-person-dispatches/by-dispatch")
def person_dispatch_roster(dispatch_id: int, authorization: str = Header(None)):
    """第 51 班：從派發頁『新增勞報單』（?dispatchId=）進來時，預填受領人用——該派發名單裡的外包名冊人員（id、姓名）。
    最高管理者＋勞報單模組；不含金額、身分證、銀行資料。派發不存在或沒有名單人員 ⇒ 空清單。"""
    _require_user(authorization, require_superadmin=True, module="payslip")
    fn = registry.single_provider("dispatch.brief")
    if fn is None:
        return {"persons": [], "notice": DISPATCH_MISSING}
    conn = get_db()
    try:
        b = fn(conn, dispatch_id)
        ids = [int(x) for x in ((b or {}).get("personnelIds") or [])][:50]
        persons = []
        if ids:
            q = ",".join("?" * len(ids))
            by_id = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM contractors WHERE id IN (%s)" % q, ids).fetchall()}
            persons = [{"id": i, "name": by_id[i]} for i in ids if i in by_id]
    finally:
        conn.close()
    return {"persons": persons, "notice": ""}


@router.post("/api/payslips/{slip_no}/confirm-contractor")
def confirm_contractor(slip_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """第 48 班：確認舊勞報單「靠姓名推測」的外包名冊對應——把 `contractor_guess_id`（或 body.contractorId 指定的人）升格成權威的 `contractor_id`。
    只有最高管理者＋勞報單模組。已簽回／已付款／已作廢的單不給確認（升格會改變已入帳分錄的對象鍵）。單一條件式 UPDATE（競態安全）；稽核。"""
    user = _require_user(authorization, require_superadmin=True, module="payslip")
    new_id = (body or {}).get("contractorId")
    conn = get_db()
    try:
        row = conn.execute("SELECT contractor_id, contractor_guess_id, status FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到此勞報單")
        if row["contractor_guess_id"] is None or row["contractor_id"] is not None:
            raise HTTPException(409, "這張勞報單沒有待確認的受領人對應")
        if (row["status"] or "") in ("已簽回", "已付款", "已作廢"):
            raise HTTPException(409, "已簽回／已付款／已作廢的勞報單不能確認對應（會改變已入帳分錄的對象）")
        cid = row["contractor_guess_id"]
        if new_id not in (None, ""):
            try:
                cid = int(new_id)
            except (TypeError, ValueError):
                raise HTTPException(400, "contractorId 格式不正確")
            if conn.execute("SELECT 1 FROM contractors WHERE id=?", (cid,)).fetchone() is None:
                raise HTTPException(404, "外包名冊沒有這位人員")
        cur = conn.execute("UPDATE payslips SET contractor_id=?, contractor_guess_id=NULL WHERE slip_no=? AND contractor_id IS NULL"
                           " AND contractor_guess_id IS NOT NULL AND status NOT IN ('已簽回','已付款','已作廢')", (cid, slip_no))
        if cur.rowcount != 1:
            raise HTTPException(409, "勞報單剛被改變，請重新整理後再試")
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "payslip.confirm_contractor", "payslip", slip_no, "%s 確認受領人對應（名冊 #%s）" % (slip_no, cid))
    return {"ok": True, "contractorId": cid}
