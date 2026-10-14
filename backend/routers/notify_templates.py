# -*- coding: utf-8 -*-
"""通知用語範本的端點（S-X3；設計 docs/platform/plans/S-X3-NOTIFY-WORDING-DESIGN-T62.md）。旗標 `builder_notify.enabled` 關閉 ⇒ 預覽 404、status 回未開放。

- `GET  /api/notify-templates/{event}/status`  登入即可 ⇒ `{enabled, canEdit}`；只有最高管理者（且旗標開）才拿到欄位清單、預設字與占位符（給編輯器）。不是已登記的事件 ⇒ 404。
- `POST /api/notify-templates/{event}/preview` 僅最高管理者、唯讀 ⇒ `{rows:[{field,label,current,draft,draftNonFinance?}], warnings}`；不寫任何資料。草稿不合法 ⇒ 422。
發布走既有的 `/api/definitions/notify_template/{event}/*`（版本／差異／還原／帳本／發布前預覽雜湊全部沿用）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user
from helpers import notify_templates as NT

router = APIRouter()


@router.get("/api/notify-templates/{event}/status")
def notify_template_status(event: str, authorization: str = Header(None)):
    u = _require_user(authorization)
    ev = NT.EVENTS.get(event)
    if ev is None:
        raise HTTPException(404, "沒有這個通知事件")
    if not NT.enabled():
        return {"enabled": False, "canEdit": False}
    out = {"enabled": True, "canEdit": u.get("role") == "superadmin"}
    if out["canEdit"]:
        out.update(event=event, label=ev["label"], sample=ev["sample"],
                   fields=[{"field": p, "label": s["label"], "default": s["default"], "limit": s["limit"],
                            "placeholders": list(s["placeholders"])} for p, s in ev["fields"].items()])
    return out


@router.post("/api/notify-templates/{event}/preview")
def notify_template_preview(event: str, body: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    if event not in NT.EVENTS:
        raise HTTPException(404, "沒有這個通知事件")
    if not NT.enabled():
        raise HTTPException(404, "未開放")
    b = body if isinstance(body, dict) else {}
    conn = get_db()
    try:
        return NT.preview(conn, u, b.get("template"), event)
    except ValueError as e:
        raise HTTPException(422, {"problems": e.args[0]})
    finally:
        conn.close()
