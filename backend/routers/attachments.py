# -*- coding: utf-8 -*-
"""L1 附件開檔端點 `GET /api/attachments/open`（附件目錄 P2，設計 proposal-attachments-search-preview §4-3）。

`?type=<source_type>&doc=<單據鍵>&file=<檔案 id>` ⇒ 找認領該 `source_type` 的 `attachments.catalog` 提供者 ⇒ `open()`（擁有模組對那張單據
自己的讀取規則）⇒ 實體檔必須落在允許的根目錄底下（uploads，或提供者宣告的 `ROOTS`，例：勞報單封存目錄）⇒ `FileResponse(octet-stream)`。

- **看不到 ＝ 查無 ＝ 404**（同一句，不回 403，不洩漏「有這個檔但你看不到」）；來源資料壞掉 ⇒ 400（訊息給使用者）。
- 查詢參數不使用 key／token 字樣（FX23a 守門）；不接受簽章 `pt`：這條路一律帶 Authorization，權限在提供者。
- 放 L1：預覽元件在沒有裝「檔案中心」時也要用它。沒有任何提供者認領該 type（模組不在）⇒ 404（安全的方向）。
"""
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse

from db import get_db
from helpers import _require_user
from helpers import uploads as _uploads

logger = logging.getLogger(__name__)
router = APIRouter()

#: 🔒 train 26 關閉（安全審查 W3，2026-09-30）：`opened_upload_file` 只驗「在 uploads 底下且存在」，沒驗該路徑屬於這張單據；
#: 案件紀錄 PATCH 接受前端帶的 files／invoiceFiles 路徑 ⇒ 打開後可借別人的單據讀 uploads 任一檔。目前沒有 UI 呼叫端（P3 才有）。
#: 真正的修補（路徑綁單據：經 `uploads.path_access` 驗證／拒絕前端帶路徑）隨 P3 一起做，做完才把這個常數打開。
#: 關閉時路由照掛、一律 404（與「沒有提供者」同一句），程式與測試保留（測試夾具把它打開）。
ATTACHMENTS_OPEN_ENABLED = False

_NOT_FOUND = "檔案不存在"


def _provider_for(source_type: str):
    from core import registry
    for key, prov in sorted(registry.providers(_uploads.ATTACHMENTS_CATALOG).items()):
        if source_type in (getattr(prov, "CATEGORIES", None) or {}):
            return key, prov
    return None, None


def _roots(prov) -> list:
    roots = [_uploads.UPLOADS_ROOT]
    declared = getattr(prov, "ROOTS", None)
    if callable(declared):
        declared = declared()
    roots += list(declared or [])
    return [os.path.normcase(os.path.realpath(r)) for r in roots if r]


def _inside(full: str, roots: list) -> bool:
    real = os.path.normcase(os.path.realpath(full))
    for r in roots:
        try:
            if os.path.commonpath([real, r]) == r:
                return True
        except ValueError:                                     # 不同磁碟
            continue
    return False


@router.get("/api/attachments/open")
def open_attachment(type: str = Query(...), doc: str = Query(...), file: str = Query(...),
                    authorization: str = Header(None)):
    user = _require_user(authorization)
    if not ATTACHMENTS_OPEN_ENABLED:
        raise HTTPException(404, _NOT_FOUND)
    key, prov = _provider_for(type)
    if prov is None:
        raise HTTPException(404, _NOT_FOUND)
    conn = get_db()
    try:
        try:
            opened = prov.open(conn, user, type, doc, file)
        except _uploads.AttachmentNotVisible:
            raise HTTPException(404, _NOT_FOUND)
        except _uploads.AttachmentSourceError as e:
            raise HTTPException(400, str(e))
        except HTTPException:
            raise
        except Exception:                                      # noqa: BLE001  fail closed：提供者壞掉只會少看到
            logger.exception("attachments.catalog 提供者 %s 開檔失敗（%s／%s／%s）", key, type, doc, file)
            raise HTTPException(404, _NOT_FOUND)
    finally:
        conn.close()
    if opened is None or not _inside(opened.abs_path, _roots(prov)) or not os.path.isfile(opened.abs_path):
        raise HTTPException(404, _NOT_FOUND)
    return FileResponse(opened.abs_path, media_type="application/octet-stream",
                        filename=opened.filename or None, content_disposition_type="inline")
