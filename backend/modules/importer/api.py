# -*- coding: utf-8 -*-
"""匯入精靈 API（T85）：範本下載、檔案解析。**兩支都不寫任何業務資料表**；解析結果交回頁面，頁面再把列送到既有的 import-rows 端點。

- `GET /api/importer/status`            唯讀探針（登入即可；固定回 `{"ok": true}`）。
- `GET /api/importer/templates/{kind}`  範本 .xlsx（kind＝customers／parts／users）。
- `POST /api/importer/parse`            multipart：`kind`＋`file`；回 `{rows, warnings, unusedColumns, …}`，不存檔、不留暫存。
權限：客戶／料號與既有的 import-rows 相同（模組權限）；員工＝只有最高管理者。設定 `import_wizard.enabled` 關閉時，範本與解析都回 404（探針照常）。
"""
import hashlib
import logging
import threading

from fastapi import APIRouter, File, Form, Header, HTTPException, Response, UploadFile

from helpers import _audit, _require_user, _tok, download_name, require_any_module
from helpers import xlsx_guard as XG
from modules.importer import parser as P

logger = logging.getLogger(__name__)
router = APIRouter()

# 同時解析的檔案數上限（解析吃 CPU／記憶體：不讓多人同時丟大檔把機器拖慢）
_PARSE_SLOTS = threading.BoundedSemaphore(2)

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_OFF = "匯入精靈目前沒有開放（請最高管理者到「設定中心 → 匯入精靈」開啟）。"


def _setting(field, default):
    try:
        from helpers import settings_groups, settings_registry as SR      # noqa: F401  確保群組已登錄
        return SR.get("import_wizard", field)
    except Exception:                                                     # noqa: BLE001 — 設定層任何問題都不能讓精靈亂開
        return default


def _enabled() -> bool:
    return _setting("enabled", 0) in (1, True)


def _check_access(user, kind):
    if kind not in P.KINDS:
        raise HTTPException(404, "沒有這種匯入對象")
    if not _enabled():
        raise HTTPException(404, _OFF)
    if kind == "users":
        if user.get("role") != "superadmin":
            raise HTTPException(403, "員工匯入只有最高管理者可以使用")
    elif kind == "customers":
        require_any_module(user, ("customer", "case_manage", "dev_crm", "procurement"), "客戶管理")
    else:
        require_any_module(user, ("procurement", "case_manage", "inventory"), "供應商／料號／採購")


@router.get("/api/importer/status")
def importer_status(authorization: str = Header(None)):
    """唯讀探針：固定 `{"ok": true}`（probe 規則：回應值不得出現字串）。"""
    _require_user(authorization)
    return {"ok": True}


@router.get("/api/importer/templates/{kind}")
def importer_template(kind: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _check_access(user, kind)
    data = P.build_template(kind)
    name = "MOTRIX_匯入範本_%s.xlsx" % P.KIND_NAMES[kind]
    return Response(content=data, media_type=_XLSX, headers={
        "Content-Disposition": download_name.content_disposition(name),
        "Cache-Control": "no-store"})


@router.post("/api/importer/parse")
def importer_parse(response: Response, kind: str = Form(...), file: UploadFile = File(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    _check_access(user, kind)
    limit = int(_setting("max_file_mb", 5) or 5) << 20
    data = file.file.read(limit + 1)
    if not _PARSE_SLOTS.acquire(timeout=5):
        raise HTTPException(429, "目前有其他人正在匯入檔案，請稍等幾秒再試")
    try:
        res = P.parse_file(data, file.filename or "", kind, max_bytes=limit)
    except XG.XlsxBusy as e:
        raise HTTPException(429, str(e))
    except P.ParseError as e:
        raise HTTPException(400, str(e))
    except Exception as exc:                                              # noqa: BLE001 — 訊息不帶例外內容
        logger.error("importer parse failed kind=%s type=%s", kind, type(exc).__name__)
        raise HTTPException(400, "這個檔案讀不出來，請確認是依範本填的 .xlsx 或 .csv")
    finally:
        _PARSE_SLOTS.release()
    response.headers["Cache-Control"] = "no-store"
    # 稽核只記「誰、什麼對象、哪個檔（雜湊）、幾列」，不放任何儲存格內容
    _audit(_tok(authorization), "import.parse", "import", kind, P.KIND_NAMES[kind],
           {"kind": kind, "file": (file.filename or "")[:120], "sha256": hashlib.sha256(data).hexdigest()[:16],
            "rows": res["rowCount"], "warnings": len(res["warnings"])})
    return res
