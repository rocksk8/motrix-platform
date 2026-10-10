# -*- coding: utf-8 -*-
"""設定中心（L1；第 54 班 Train A／S0）。群組由程式登錄（helpers/settings_registry），索引頁由登錄自動產生。

- GET  /api/settings-center/groups                 全部群組＋目前值＋最後變更（superadmin）
- GET  /api/settings-center/groups/{group}         單一群組欄位定義＋目前值＋變更明細（superadmin）
- POST /api/settings-center/groups/{group}         儲存（部分欄位即可；`reason` 必填；superadmin）
- GET  /api/settings-center/pending                待生效清單（風險欄位 24 小時後才生效；superadmin）
- POST /api/settings-center/pending/{id}/cancel    撤銷一筆待生效（寫稽核；superadmin）
- GET  /api/settings-center/public?groups=a,b      非敏感群組的目前值（登入即可；敏感群組只有最高管理者能讀）
"""
from fastapi import APIRouter, Body, Header, HTTPException, Request

from helpers import _require_user, _tok, _audit
from helpers import config_ledger as ledger
from helpers import settings_groups  # noqa: F401  登錄群組
from helpers import settings_registry as sr

router = APIRouter()


def _need(group):
    if group not in sr.groups():
        raise HTTPException(404, "沒有這個設定群組：%s" % group)


@router.get("/api/settings-center/groups")
def list_groups(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    out = []
    from db import get_db
    conn = get_db()
    try:
        for g, meta in sr.groups().items():
            last = ledger.history(conn, "setting:%s" % g, g, limit=1)
            out.append({"group": g, "label": meta["label"], "help": meta["help"], "sensitive": meta["sensitive"], "risk": meta["risk"],
                        "values": sr.get_group(g), "fieldCount": len(meta["fields"]),
                        "lastChange": ({"at": last[0]["at"], "actor": last[0]["actor_display"] or last[0]["actor"], "reason": last[0]["reason"]} if last else None)})
    finally:
        conn.close()
    return {"groups": out}


@router.get("/api/settings-center/groups/{group}")
def get_group(group: str, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _need(group)
    from db import get_db
    conn = get_db()
    try:
        hist = ledger.history(conn, "setting:%s" % group, group, limit=50)
    finally:
        conn.close()
    meta = sr.groups()[group]
    return {"group": group, "label": meta["label"], "help": meta["help"], "sensitive": meta["sensitive"], "fields": meta["fields"],
            "values": sr.get_group(group), "history": hist}


@router.post("/api/settings-center/groups/{group}")
def save_group(group: str, request: Request, body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    _need(group)
    values = body.get("values")
    reason = str(body.get("reason") or "").strip()
    if not isinstance(values, dict) or not values:
        raise HTTPException(400, "沒有送出任何要變更的欄位")
    if not reason:
        raise HTTPException(400, "請填寫變更原因")
    try:
        out = sr.publish(group, values, note=reason, user=actor["username"], reason=reason,
                         ip=(request.client.host if request.client else ""), actor=actor)
    except sr.SettingError as e:
        raise HTTPException(400, {"message": str(e), "problems": e.problems})
    except Exception as e:                                   # noqa: BLE001
        from core.definitions import DefinitionConflict, DefinitionError
        if isinstance(e, DefinitionConflict):
            raise HTTPException(409, str(e))
        if isinstance(e, DefinitionError):
            raise HTTPException(400, str(e))
        raise
    return {"ok": True, **out}


@router.get("/api/settings-center/public")
def public_values(groups: str = "", authorization: str = Header(None)):
    user = _require_user(authorization)
    names = [g.strip() for g in groups.split(",") if g.strip()]
    if not names:
        raise HTTPException(400, "請指定 groups")
    meta = sr.groups()
    is_admin = user.get("role") == "superadmin"
    out = {}
    for g in names:
        if g not in meta:
            raise HTTPException(404, "沒有這個設定群組：%s" % g)
        if meta[g]["sensitive"] and not is_admin:
            raise HTTPException(403, "此設定群組需要設定權限：%s" % g)
        out[g] = sr.get_group(g)
    return {"groups": out}


@router.get("/api/settings-center/pending")
def list_pending(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from db import get_db
    conn = get_db()
    try:
        rows = [r for r in ledger.pending(conn, "setting") if r["domain"].startswith("setting:")]
    finally:
        conn.close()
    return {"pending": [{"id": r["id"], "group": r["key"], "field": r["field"], "old": r["old"], "new": r["new"], "reason": r["reason"],
                         "actor": r["actor_display"] or r["actor"], "at": r["at"], "effectiveAt": r["effective_at"]} for r in rows]}


@router.post("/api/settings-center/pending/{change_id}/cancel")
def cancel_pending(change_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    from db import get_db
    conn = get_db()
    try:
        row = conn.execute("SELECT domain, key, field FROM config_changes WHERE id=?", (change_id,)).fetchone()
        if row is None or not row["domain"].startswith("setting:"):
            raise HTTPException(404, "找不到這筆待生效的設定變更")
        reason = str((body or {}).get("reason") or "").strip() or "撤銷待生效"
        if not ledger.cancel(conn, change_id, actor, reason):
            raise HTTPException(409, "這筆變更已不是待生效狀態")
        conn.commit()
    finally:
        conn.close()
    sr.invalidate(row["key"])
    _audit(_tok(authorization), "settings.%s.pending_cancel" % row["key"], "config", str(row["key"]),
           "撤銷待生效：%s（#%d）原因：%s" % (row["field"], change_id, reason))
    return {"ok": True}
