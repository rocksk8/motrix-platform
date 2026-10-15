# -*- coding: utf-8 -*-
"""額外通知動作的端點（BP-4 S5 後端；設計 docs/platform/plans/BP4-STORAGE-NOTIFY-DESIGN.md §4.5）。旗標 `builder_notify.enabled`＋`builder_governance.enabled` 任一關閉 ⇒ 全部 404。

- `GET  /api/notify-actions/status`            登入即可 ⇒ `{enabled, canEdit}`；只有最高管理者另外拿到 `events`（事件目錄：占位符、可篩選欄位、可用收件人類別、一鍵建議內容、範例）、`caps` 與 `picker`（收件人挑選器目錄：角色、群組、現有啟用帳號）。
- `POST /api/notify-actions/{key}/preview`      僅最高管理者、唯讀 ⇒ 試跑結果（見 `helpers.notify_actions.preview`）；body `{template: <動作草稿>, payload?: <事件內容>}`；草稿不合法 ⇒ 422。
發布走既有的 `/api/definitions/notify_action/{key}/*`（版本／差異／還原／帳本／發布前預覽雜湊全部沿用）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok
from helpers import notify_actions as NA

router = APIRouter()


@router.get("/api/notify-actions/status")
def notify_actions_status(authorization: str = Header(None)):
    u = _require_user(authorization)
    if not NA.enabled():
        return {"enabled": False, "canEdit": False}
    out = {"enabled": True, "canEdit": u.get("role") == "superadmin"}
    if out["canEdit"]:
        out["events"] = NA.event_catalog()
        out["caps"] = dict(NA.CAPS)
        conn = get_db()
        try:
            out["picker"] = NA.picker_catalog(conn)
        finally:
            conn.close()
    return out


@router.post("/api/notify-actions/{key}/preview")
def notify_actions_preview(key: str, body: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    if not NA.enabled():
        raise HTTPException(404, "未開放")
    b = body if isinstance(body, dict) else {}
    conn = get_db()
    try:
        out = NA.preview(conn, u, key, b.get("template"), b.get("payload"))
    except ValueError as e:
        raise HTTPException(422, {"problems": e.args[0] if e.args and isinstance(e.args[0], list) else [{"path": "", "message": str(e)}]})
    finally:
        conn.close()
    _audit(_tok(authorization), "notify_action.previewed", "notify_action", key, key, {"event": out["event"], "matches": out["matches"]})
    return out
