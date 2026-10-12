# -*- coding: utf-8 -*-
"""設定中心（L1；第 54 班 Train A／S0）。群組由程式登錄（helpers/settings_registry），索引頁由登錄自動產生。

- GET  /api/settings-center/groups                 全部群組＋目前值＋最後變更（superadmin）
- GET  /api/settings-center/groups/{group}         單一群組欄位定義＋目前值＋變更明細（superadmin）
- POST /api/settings-center/groups/{group}         儲存（部分欄位即可；`reason` 必填；superadmin）；回應附 `classification`（逐欄 立即／待生效／需核准）
- POST /api/settings-center/groups/{group}/preview 預覽（dry-run，不寫入）：逐欄分類、效果句、橫幅、驗證問題（S1-4）
- POST /api/settings-center/groups/{group}/impact  即時影響（唯讀、1.5 秒逾時、快取 60 秒；失敗只回靜態說明）（S1-4）
- GET  /api/settings-center/groups/{group}/versions 已發布的版本清單（S1-5；比較／還原用，白話）
- GET  /api/settings-center/groups/{group}/diff?a=&b= 兩版（版本號｜current｜default）之間的白話差異（S1-5）
- POST /api/settings-center/groups/{group}/restore/{version} 還原到某一版（`preview:true` 只預覽；否則 `reason` 必填；先撤銷該群組舊的待生效項，再走 publish，所以放寬者仍待生效／核准）（S1-5）
- POST /api/settings-center/groups/{group}/reset   把指定欄位改回程式預設（走同一條 publish 管制，放寬者仍待生效／核准；`reason` 必填）（S1-4）
- GET  /api/settings-center/pending                待生效清單（風險欄位經「變更確認期間」才生效，含已核准／需要票數；superadmin）
- POST /api/settings-center/pending/{id}/cancel    撤銷一筆待生效（寫稽核；superadmin）
- POST /api/settings-center/pending/{id}/approve   雙人核准的一票（放寬安全／風險設定需要另一位最高管理者核准；superadmin）
- GET  /api/settings-center/profiles               預設組清單；GET …/profiles/{name}/preview 預覽會改什麼；POST …/profiles/{name}/apply 套用（superadmin）
- GET  /api/settings-center/public?groups=a,b      非敏感群組的目前值（登入即可；敏感群組只有最高管理者能讀）
"""
from fastapi import APIRouter, Body, Header, HTTPException, Request

from helpers import _require_user
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
    values = sr.get_group(group)
    return {"group": group, "label": meta["label"], "help": meta["help"], "sensitive": meta["sensitive"],
            "fields": sr.field_views(group, values), "values": values, "history": hist}


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
    return _do_publish(group, values, reason, request, actor)


def _do_publish(group, values, reason, request, actor):
    """儲存／重置共用：先算分類（與 publish 共用 `_split`，寫入前的狀態才準）、再 publish。"""
    try:
        cls = sr.plan(group, values, user=actor["username"])["fields"]
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
    return {"ok": True, **out, "classification": cls}


@router.post("/api/settings-center/groups/{group}/preview")
def preview_group(group: str, body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    _need(group)
    values = body.get("values")
    if not isinstance(values, dict) or not values:
        raise HTTPException(400, "沒有送出任何要變更的欄位")
    return sr.plan(group, values, user=actor["username"])


@router.post("/api/settings-center/groups/{group}/impact")
def impact_group(group: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _need(group)
    field = body.get("field")
    if field not in {f["key"] for f in sr.groups()[group]["fields"]}:
        raise HTTPException(404, "沒有這個設定欄位")
    return sr.live_impact(group, field, body.get("value"))


@router.post("/api/settings-center/groups/{group}/reset")
def reset_group(group: str, request: Request, body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    _need(group)
    reason = str(body.get("reason") or "").strip()
    fields = body.get("fields")
    known = {f["key"]: f["default"] for f in sr.groups()[group]["fields"]}
    if not isinstance(fields, list) or not fields or any(k not in known for k in fields):
        raise HTTPException(400, "請指定要還原預設的欄位")
    if not reason:
        raise HTTPException(400, "請填寫變更原因")
    return _do_publish(group, {k: known[k] for k in dict.fromkeys(fields)}, reason, request, actor)


def _values_of(conn, group, which):
    """which：版本號｜`current`（目前已生效的值）｜`default`（程式預設）。回完整值（缺的欄位補預設）或 None（沒有這一版）。"""
    from core import definitions as D
    defaults = {f["key"]: f["default"] for f in sr.groups()[group]["fields"]}
    if which == "default":
        return defaults
    if which == "current":
        return sr.get_group(group, conn=conn)
    try:
        n = int(which)
    except (TypeError, ValueError):
        raise HTTPException(400, "版本要填數字、current 或 default")
    row = D.get(conn, sr.KIND, group, sr.SCOPE, n)
    if row is None or row.get("status") != "published" or n <= 0:
        return None
    vals = (row.get("body") or {}).get("values") or {}
    return {**defaults, **{k: v for k, v in vals.items() if k in defaults}}


@router.get("/api/settings-center/groups/{group}/versions")
def group_versions(group: str, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _need(group)
    from core import definitions as D
    from db import get_db
    conn = get_db()
    try:
        vs = [v for v in D.versions(conn, sr.KIND, group, sr.SCOPE) if v.get("status") == "published" and v["version"] > 0]
    finally:
        conn.close()
    return {"versions": [{"version": v["version"], "note": v.get("note") or "", "by": v.get("published_by") or v.get("created_by") or "",
                          "at": v.get("published_at") or v.get("created_at") or ""} for v in vs],
            "latest": vs[0]["version"] if vs else None}


@router.get("/api/settings-center/groups/{group}/diff")
def group_diff(group: str, a: str = "default", b: str = "current", authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _need(group)
    from db import get_db
    conn = get_db()
    try:
        va, vb = _values_of(conn, group, a), _values_of(conn, group, b)
    finally:
        conn.close()
    if va is None or vb is None:
        raise HTTPException(404, "沒有這一版")
    g = sr.field_defs(group)
    return {"a": a, "b": b, "changes": [{"field": k, "label": g[k].label, "oldText": sr.show_value(g[k], va[k]), "newText": sr.show_value(g[k], vb[k])}
                                         for k in g if va[k] != vb[k]]}


@router.post("/api/settings-center/groups/{group}/restore/{version}")
def restore_group(group: str, version: int, request: Request, body: dict = Body(default={}), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    _need(group)
    from core.txn import begin_write
    from db import get_db
    conn = get_db()
    began = False
    try:
        vals = _values_of(conn, group, str(version))
        if vals is None:
            raise HTTPException(404, "沒有這一版（只能還原已發布的版本）")
        if (body or {}).get("preview"):
            return sr.plan(group, vals, user=actor["username"], conn=conn)
        reason = str((body or {}).get("reason") or "").strip()
        if not reason:
            raise HTTPException(400, "請填寫還原原因")
        cls = sr.plan(group, vals, user=actor["username"], conn=conn)
        if not cls["ok"]:
            raise HTTPException(400, {"message": "第 %d 版的內容超出目前允許的範圍或版本邊界，無法還原" % version, "problems": cls["problems"]})
        began = begin_write(conn)
        ledger.audit_event(conn, actor, "settings.%s.restore" % group, group, "還原到第 %d 版。原因：%s" % (version, reason))   # 與還原同一個交易（publish 內 commit）
        out = ledger.restore_version(conn, "setting:%s" % group, group, version, actor["username"], reason)
        conn.commit()                                              # publish 在「沒有變更」時不 commit：撤銷舊待生效項與稽核要靠這裡落盤
    except sr.SettingError as e:
        if began and conn.in_transaction:
            conn.rollback()
        raise HTTPException(400, {"message": str(e), "problems": e.problems})
    except Exception:
        if began and conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    sr.invalidate(group)
    return {"ok": True, **(out or {}), "classification": cls["fields"]}


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
    meta = sr.groups()
    out = []
    for r in rows:
        f = sr.field_defs(r["key"]).get(r["field"]) if r["key"] in meta else None
        out.append({"id": r["id"], "group": r["key"], "groupLabel": meta[r["key"]]["label"] if r["key"] in meta else r["key"],
                    "field": r["field"], "label": f.label if f else r["field"],
                    "old": r["old"], "new": r["new"],
                    "oldText": sr.show_value(f, r["old"]) if f else str(r["old"]), "newText": sr.show_value(f, r["new"]) if f else str(r["new"]),
                    "reason": r["reason"], "actor": r["actor_display"] or r["actor"], "actorUser": r["actor"], "at": r["at"], "effectiveAt": r["effective_at"],
                    "approvals": list(r.get("approvals") or []), "required": int(r.get("approvals_required") or 0)})
    return {"pending": out}


@router.post("/api/settings-center/pending/{change_id}/cancel")
def cancel_pending(change_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    from core.txn import begin_write
    from db import get_db
    conn = get_db()
    began = False
    try:
        began = begin_write(conn)                         # 先拿寫鎖再讀狀態：兩人同時按不會雙重處理
        row = conn.execute("SELECT domain, key, field FROM config_changes WHERE id=?", (change_id,)).fetchone()
        if row is None or not row["domain"].startswith("setting:"):
            raise HTTPException(404, "找不到這筆待生效的設定變更")
        reason = str((body or {}).get("reason") or "").strip() or "撤銷待生效"
        if not ledger.cancel(conn, change_id, actor, reason):
            raise HTTPException(409, "這筆變更已不是待生效狀態")
        ledger.audit_event(conn, actor, "settings.%s.pending_cancel" % row["key"], row["key"],
                           "撤銷待生效：%s（#%d）原因：%s" % (row["field"], change_id, reason))   # 同交易：變更與稽核一起成功
        conn.commit()
    except Exception:
        if began and conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    sr.invalidate(row["key"])
    return {"ok": True}


@router.post("/api/settings-center/pending/{change_id}/approve")
def approve_pending(change_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    from core.txn import begin_write
    from db import get_db
    conn = get_db()
    began = False
    try:
        began = begin_write(conn)
        row = conn.execute("SELECT domain, key, field FROM config_changes WHERE id=?", (change_id,)).fetchone()
        if row is None or not row["domain"].startswith("setting:"):
            raise HTTPException(404, "找不到這筆待生效的設定變更")
        reason = str((body or {}).get("reason") or "").strip() or "同意放寬"
        out = ledger.approve(conn, change_id, actor, reason)
        if not out["ok"]:
            raise HTTPException(409, out["why"])
        ledger.audit_event(conn, actor, "settings.%s.approve" % row["key"], row["key"],
                           "核准待生效變更：%s（#%d）%d／%d" % (row["field"], change_id, out["approvals"], out["required"]))
        conn.commit()
    except Exception:
        if began and conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    sr.invalidate(row["key"])
    return {"ok": True, "approvals": out["approvals"], "required": out["required"]}


@router.get("/api/settings-center/profiles")
def list_profiles(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    return {"profiles": [{"name": n, "fieldCount": c} for n, c in sr.profiles().items()]}


@router.get("/api/settings-center/profiles/{name}/preview")
def preview_profile(name: str, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    if name not in sr.profiles():
        raise HTTPException(404, "沒有這個預設組")
    return {"name": name, "changes": sr.profile_preview(name)}


@router.post("/api/settings-center/profiles/{name}/apply")
def apply_profile(name: str, request: Request, body: dict = Body(default={}), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    reason = str((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫套用原因")
    if name not in sr.profiles():
        raise HTTPException(404, "沒有這個預設組")
    try:
        out = sr.apply_profile(name, reason=reason, user=actor["username"], ip=(request.client.host if request.client else ""), actor=actor)
    except sr.SettingError as e:
        raise HTTPException(400, {"message": str(e), "problems": e.problems})
    return {"ok": True, "results": out}
