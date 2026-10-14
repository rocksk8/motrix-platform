# -*- coding: utf-8 -*-
"""匯出範本的端點（BP-3；設計：docs/platform/plans/BP3-EXPORT-FUNNEL-DESIGN-T61.md）。旗標 `builder_exports.enabled` 關閉 ⇒ 預覽 404、status 回未開放（`/api/exports/client-log` 不受旗標管：它是補稽核與冷卻的缺口，不是新功能）。

- `GET  /api/export-templates/{export_id}/status`  登入即可 ⇒ `{enabled, canEdit, label?, formats?, columns?}`；旗標關 ⇒ `{enabled:false, canEdit:false}`；
  只有最高管理者（且旗標開）才拿到欄位目錄與格式（給編輯器）。不是已登記的匯出 ⇒ 404。
- `POST /api/export-templates/{export_id}/preview` 僅最高管理者、唯讀 ⇒ `{user, role, format, columns, rows, omitted, warnings, sample}`；
  不寫任何資料、不計匯出次數、不留 `export.*` 稽核。草稿不合法 ⇒ 422；找不到使用者 ⇒ 404。
發布走既有的 `/api/definitions/export_template/{export_id}/*`（版本／差異／還原／帳本／發布前預覽雜湊全部沿用）。
- `POST /api/exports/client-log {name, rows}`（登入即可）：瀏覽器端產檔的匯出（客戶、料號、供應商三頁的 SheetJS）先呼叫這支，**寫一筆 `export.xlsx` 稽核並套用匯出冷卻**
  （與伺服端 Excel 匯出同一個 5 秒冷卻）。名稱只能是白名單；rows 是 0～200000 的整數。冷卻中 ⇒ 429（前端不產檔）。
  這是『自報』的紀錄（伺服器無法證明檔案真的產生），但補上了這三頁原本沒有稽核、沒有冷卻的缺口（使用者規則 2026-09-30：每一次匯出都要留紀錄）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok
from helpers.xlsx_out import check_export_rate, summarize_filters
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


#: 瀏覽器端產檔的匯出名稱白名單（名稱 → 稽核用的模組標籤）
CLIENT_EXPORTS = {"customers": "crm", "parts": "parts", "suppliers": "supply"}


@router.post("/api/exports/client-log")
def client_export_log(body: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization)
    b = body if isinstance(body, dict) else {}
    name = b.get("name")
    if name not in CLIENT_EXPORTS:
        raise HTTPException(422, "不認得的匯出名稱")
    rows = b.get("rows")
    if isinstance(rows, bool) or not isinstance(rows, int) or not 0 <= rows <= 200000:
        raise HTTPException(422, "rows 必須是 0～200000 的整數")
    check_export_rate(u["id"], "xlsx")                       # 冷卻中 ⇒ 429（與伺服端 Excel 匯出共用同一個冷卻）
    _audit(_tok(authorization), "export.xlsx", "export", name, name,
           {"module": CLIENT_EXPORTS[name], "format": "xlsx", "filters": summarize_filters({}), "rows": rows, "client": True})
    return {"ok": True}

