# -*- coding: utf-8 -*-
"""匯出範本的端點（BP-3；設計：docs/platform/plans/BP3-EXPORT-FUNNEL-DESIGN-T61.md）。旗標 `builder_exports.enabled` 關閉 ⇒ 除 status 外全部 404。

- `GET  /api/export-templates/{export_id}/status`  登入即可 ⇒ `{enabled, canEdit, label?, formats?, columns?}`；旗標關 ⇒ `{enabled:false, canEdit:false}`；
  只有最高管理者（且旗標開）才拿到欄位目錄與格式（給編輯器）。不是已登記的匯出 ⇒ 404。
- `POST /api/export-templates/{export_id}/preview` 僅最高管理者、唯讀 ⇒ `{user, role, format, columns, rows, omitted, warnings, sample}`；
  不寫任何資料、不計匯出次數、不留 `export.*` 稽核。草稿不合法 ⇒ 422；找不到使用者 ⇒ 404。
發布走既有的 `/api/definitions/export_template/{export_id}/*`（版本／差異／還原／帳本／發布前預覽雜湊全部沿用）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user
from helpers import export_templates as ET

router = APIRouter()


@router.get("/api/export-templates/{export_id}/status")
def export_template_status(export_id: str, authorization: str = Header(None)):
    u = _require_user(authorization)
    reg = ET.registered()
    if export_id not in reg:
        raise HTTPException(404, "沒有這個匯出")
    if not ET.enabled():
        return {"enabled": False, "canEdit": False}
    out = {"enabled": True, "canEdit": u.get("role") == "superadmin"}
    if out["canEdit"]:
        out.update(reg[export_id], exportId=export_id)
    return out


@router.post("/api/export-templates/{export_id}/preview")
def export_template_preview(export_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    if export_id not in ET.registered():
        raise HTTPException(404, "沒有這個匯出")
    if not ET.enabled():
        raise HTTPException(404, "未開放")
    b = body if isinstance(body, dict) else {}
    try:
        n = int(b.get("n") or 20)
    except (TypeError, ValueError):
        raise HTTPException(422, {"problems": [{"path": "n", "message": "n 必須是整數"}]})
    conn = get_db()
    try:
        return ET.preview(conn, u, b.get("template"), export_id, username=b.get("user"),
                          sample="visible" if b.get("sample") == "visible" else "sample", n=n)
    except ValueError as e:
        raise HTTPException(422, {"problems": e.args[0]})
    except LookupError as e:
        raise HTTPException(404, str(e))
    finally:
        conn.close()
