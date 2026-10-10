# -*- coding: utf-8 -*-
"""刪除暫存區 API：**只有最高管理者**（列表、詳情（遮罩）、還原、永久刪除、『刪除已核可』入口、隔離目錄設定）。
一般使用者看不到入口、直接打也是 403；他們刪單據後只看到『已刪除』（單據端點由擁有模組呼叫 `helpers.recycle_bin.delete`）。
每個寫入端點都寫稽核：recyclebin.restore／restore_failed／purge_manual／delete_approved／settings。
"""
import os

from fastapi import APIRouter, Body, Header, HTTPException, Query

from core import paths as _paths
from core.txn import write_txn
from db import get_db
from helpers import _audit, _require_user, _tok
from helpers import recycle_bin as RB
from helpers.audit import _notify
from helpers.settings import _set_setting
from modules.recyclebin import quarantine as Q
from modules.recyclebin import service as S

router = APIRouter()

PURGE_CONFIRM = "永久刪除"


def _require_sa(authorization):
    return _require_user(authorization, require_superadmin=True)


def _http(e: RB.BinError) -> HTTPException:
    msg = str(e)
    code = 404 if msg.startswith("not_found") else 413 if msg.startswith("too_large") else 409
    return HTTPException(code, msg.split(": ", 1)[1] if ": " in msg[:20] else msg)


def _notify_superadmins(conn, actor, type_, ref, label, message, extra_users=()):
    for u in dict.fromkeys(list(S.superadmins(conn)) + [x for x in extra_users if x]):
        if u != actor:
            _notify(u, type_, str(ref), label, message, "recycle-bin.html")


@router.get("/api/recycle-bin")
def list_bin(status: str = "in_bin", entity_type: str = "", q: str = "", page: int = 1, size: int = 50, authorization: str = Header(None)):
    _require_sa(authorization)
    conn = get_db()
    try:
        return S.list_items(conn, status, entity_type, q.strip(), page, size)
    finally:
        conn.close()


@router.get("/api/recycle-bin/status")
def bin_status(authorization: str = Header(None)):
    _require_sa(authorization)
    conn = get_db()
    try:
        return S.status(conn)
    finally:
        conn.close()


@router.get("/api/recycle-bin/impact")
def bin_impact(entity_type: str = Query(...), entity_id: str = Query(...), authorization: str = Header(None)):
    """『刪除已核可』前的影響清單（已付款／已入獎金／已回簽…）；adapter 決定內容。"""
    _require_sa(authorization)
    ad = RB.get_adapter(entity_type)
    if ad is None:
        raise HTTPException(404, "沒有這種單據的暫存區 adapter")
    conn = get_db()
    try:
        ok, why = ad.can_delete_approved(conn, entity_id, {"role": "superadmin"})
        return {"entityType": entity_type, "entityId": entity_id, "supported": bool(ok), "reason": "" if ok else why, "impact": ad.impact(conn, entity_id)}
    finally:
        conn.close()


@router.get("/api/recycle-bin/{bin_id}")
def bin_detail(bin_id: int, authorization: str = Header(None)):
    _require_sa(authorization)
    conn = get_db()
    try:
        return S.detail(conn, bin_id)
    except RB.BinError as e:
        raise _http(e)
    finally:
        conn.close()


@router.post("/api/recycle-bin/{bin_id}/restore")
def bin_restore(bin_id: int, authorization: str = Header(None)):
    user = _require_sa(authorization)
    conn = get_db()
    try:
        try:
            res = S.restore(conn, bin_id, user, audit=lambda c, x: S.audit_tx(
                c, user, "recyclebin.restore", "recycle_bin", str(bin_id), "%s %s" % (x["entityType"], x["entityId"]),
                {"entity_type": x["entityType"], "entity_id": x["entityId"], "renumbered": x["renumbered"], "notes": x["notes"]}))
        except RB.BinError as e:
            _audit(_tok(authorization), "recyclebin.restore_failed", "recycle_bin", str(bin_id), str(e)[:200], {"error": str(e)[:500]})
            raise _http(e)
        deleter = conn.execute("SELECT deleted_by FROM recycle_bin WHERE id=?", (bin_id,)).fetchone()
        _notify_superadmins(conn, user["username"], "recyclebin_restore", bin_id, res["label"],
                            "%s 已從暫存區還原：%s" % (user.get("display_name") or user["username"], res["label"]), [deleter["deleted_by"] if deleter else ""])
        return res
    finally:
        conn.close()


@router.delete("/api/recycle-bin/{bin_id}")
def bin_purge(bin_id: int, confirm: str = Query(""), authorization: str = Header(None)):
    """永久刪除一筆（附件與快照都刪，不能復原）。要帶 `confirm=永久刪除`（前端二次確認後送）。"""
    user = _require_sa(authorization)
    if confirm != PURGE_CONFIRM:
        raise HTTPException(422, "永久刪除需要二次確認（confirm=%s）" % PURGE_CONFIRM)
    conn = get_db()
    try:
        try:
            res = S.purge(conn, bin_id, by=user["username"], audit=lambda c, x: S.audit_tx(
                c, user, "recyclebin.purge_manual", "recycle_bin", str(bin_id), "%s %s" % (x["entityType"], x["entityId"]),
                {"entity_type": x["entityType"], "entity_id": x["entityId"], "deleted_at": x["deletedAt"]}))
        except RB.BinError as e:
            _audit(_tok(authorization), "recyclebin.purge_failed", "recycle_bin", str(bin_id), str(e)[:200], {"error": str(e)[:500]})
            raise _http(e)
        _notify_superadmins(conn, user["username"], "recyclebin_purge", bin_id, res["label"],
                            "%s 已永久刪除暫存區項目：%s" % (user.get("display_name") or user["username"], res["label"]))
        return {"ok": True, "id": bin_id}
    finally:
        conn.close()


@router.post("/api/recycle-bin/delete-approved")
def bin_delete_approved(body: dict = Body(...), authorization: str = Header(None)):
    """superadmin 專用『刪除已核可』：進暫存區（可還原），不是硬刪。要 `confirm:true` 且 `confirm_text` 等於單據編號（二次確認）。
    哪些單據／狀態可以走這個入口由各 adapter 的 `can_delete_approved` 決定（P0 沒有任何 adapter ⇒ 一律 404）。"""
    user = _require_sa(authorization)
    et, eid = body.get("entity_type"), body.get("entity_id")
    et, eid = (et if isinstance(et, str) else ""), (eid if isinstance(eid, str) else str(eid) if isinstance(eid, int) and not isinstance(eid, bool) else "")
    ctext = body.get("confirm_text")
    if body.get("confirm") is not True or not isinstance(ctext, str) or ctext != eid or not eid:
        raise HTTPException(422, "需要二次確認：confirm=true 並輸入單據編號（confirm_text）")
    if RB.get_adapter(et) is None:
        raise HTTPException(404, "沒有這種單據的暫存區 adapter")
    rsn = body.get("reason")
    rsn = rsn.strip() if isinstance(rsn, str) else ""
    if not rsn:
        raise HTTPException(422, "刪除已核可的單據必須填寫原因（reason）")
    conn = get_db()
    try:
        res = None
        try:
            with write_txn(conn):               # 讀快照前先拿寫鎖；區塊內任何例外 ⇒ rollback 並關連線
                res = S.delete(conn, et, eid, user, rsn, approved=True)
                S.audit_tx(conn, user, "recyclebin.delete_approved", et, eid, "%s %s" % (et, eid),   # 稽核與刪除同一個交易
                           {"bin_id": res["bin_id"], "purge_after": res["purge_after"], "children": len(res["children"]), "reason": rsn[:200]})
                conn.commit()
        except BaseException as e:
            if res is not None and callable(res.get("rollback_files")):
                res["rollback_files"]()         # 資料列已隨交易 rollback；附件搬回原處
            if isinstance(e, RB.BinError):
                raise _http(e)
            raise
        res.pop("rollback_files", None)
        post = res.pop("after_commit", None)
        if post:
            post()                                          # commit 之後：擁有模組的後續動作（行事曆同步等），錯誤只記 log
        _notify_superadmins(conn, user["username"], "recyclebin_delete_approved", res["bin_id"], "%s %s" % (et, eid),
                            "%s 把已核可的單據 %s %s 送進了暫存區（30 天內可還原）" % (user.get("display_name") or user["username"], et, eid))
        return res
    finally:
        conn.close()


@router.put("/api/recycle-bin/settings")
def bin_settings(body: dict = Body(...), authorization: str = Header(None)):
    """隔離目錄：空字串＝預設（安裝根目錄下的「資源回收筒」）；否則必須是樹外的絕對路徑（上一層存在，最後一層會建）。
    暫存區還有項目時不准改（會讓隔離檔失聯）。"""
    user = _require_sa(authorization)
    d = str(body.get("dir") or "").strip()
    conn = get_db()
    try:
        live = conn.execute("SELECT COUNT(*) FROM recycle_bin WHERE restore_status IN (?,?)", S.LIVE).fetchone()[0]
        if live:
            raise HTTPException(409, "暫存區還有 %d 筆項目，請先還原或清除後再改隔離目錄" % live)
        if d:
            why = Q.location_problem(d)
            if not why:
                up = os.path.normcase(os.path.realpath(_paths.UPLOADS_ROOT))      # uploads 底下也不行（會被檔案服務／雲端鏡像碰到）；測試把 UPLOADS_ROOT 換掉時也要擋
                nd = os.path.normcase(os.path.realpath(d))
                if nd == up or nd.startswith(up + os.sep):
                    why = "隔離目錄不可在 uploads 底下"
            if why:
                raise HTTPException(422, why)
            if not os.path.isdir(d):
                if not os.path.isdir(os.path.dirname(d)):
                    raise HTTPException(422, "上一層資料夾不存在")
                os.mkdir(d)
        old = Q.root_dir()
        _set_setting(Q.SETTING_DIR, d)
        _audit(_tok(authorization), "recyclebin.settings", "recycle_bin", "dir", "隔離目錄", {"old": old, "new": Q.root_dir()})
        return {"ok": True, "dir": Q.root_dir(), "by": user["username"]}
    finally:
        conn.close()
