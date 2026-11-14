# -*- coding: utf-8 -*-
"""自訂報表的端點（T87 B2-S1b；設計：D:\\Claude-pm\\t87-design\\B2-custom-reports.md §9）。前綴 `/api/custom-reports`。

- `GET  /api/custom-reports/sources`  這位使用者可用的資料來源與欄位（不可見的欄位只標「無權限」與通用原因；不含任何資料值）。
- `POST /api/custom-reports/preview`  本文＝報表定義；回傳最多 50 列＋分組小計／總計。不寫任何東西、不留稽核（預覽不是匯出）。

[不變式] ①順序：登入 ⇒ 旗標（`custom_reports.enabled`，關 ⇒ 404、不讀寫表）⇒ 能力 `analytics.custom_report.view`（403）⇒ 來源的模組存取（沒有 ⇒ `/sources` 不列、`/preview` 404）。
    能力不取代模組存取，模組存取也不取代能力：兩者每次請求都查。
    ②所有欄位／列的可見性決定都在 `helpers.report_runner`／`report_catalog`（後端每次請求重算）；本檔只轉換成 HTTP，不做任何權限判斷。
    ③錯誤訊息是固定白話，不回顯使用者輸入的值；未預期的例外只記 log、回固定訊息。
    ④每人每分鐘最多 20 次預覽（行程內滑動視窗；多行程時各自計，只當保險絲）。
[契約題] backend/tests/platform/test_custom_reports_api_t87.py
"""
import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user
from helpers import perm as _perm
from helpers import report_catalog as RC
from helpers import report_policy as RP
from helpers import report_runner as RR

router = APIRouter()
_log = logging.getLogger(__name__)

CAP_VIEW = "analytics.custom_report.view"
PREVIEW_PER_MINUTE = 20
_WINDOW_SECONDS = 60.0
_hits = defaultdict(deque)
_hits_lock = threading.Lock()
NO_ACCESS_REASON = "您沒有查看這個欄位的權限"


def reset_rate_limit() -> None:
    """測試用：清空限流計數。"""
    with _hits_lock:
        _hits.clear()


def _check_rate(user_id) -> None:
    now = time.monotonic()
    with _hits_lock:
        q = _hits[user_id]
        while q and now - q[0] >= _WINDOW_SECONDS:
            q.popleft()
        if len(q) >= PREVIEW_PER_MINUTE:
            wait = int(_WINDOW_SECONDS - (now - q[0])) + 1
            raise HTTPException(429, {"message": "預覽太頻繁，請 %d 秒後再試" % wait, "reason": "rate_limited"})
        q.append(now)


def _gate(authorization):
    user = _require_user(authorization)
    conn = get_db()
    try:
        on = RP.enabled(conn)
    finally:
        conn.close()
    if not on:
        raise HTTPException(404, "未開放")
    _perm.require(user, CAP_VIEW)
    return user


def _http(e: "RR.ReportError"):
    detail = {"message": e.message}
    detail.update({k: v for k, v in (e.details or {}).items() if k in ("reason", "fields", "action")})
    return HTTPException(e.status, detail)


def _enum_options(f, conn):
    en = f.get("enum")
    if en is None:
        return None
    try:
        opts = en(conn) if callable(en) else en
        return [[v, lab] for v, lab in opts]
    except Exception:                                        # noqa: BLE001 — 選項讀不到不影響其他欄位
        _log.warning("custom_reports：欄位 %s 的選項讀取失敗", f.get("id"), exc_info=True)
        return []


def _field_json(f, visible, conn):
    d = {"id": f["id"], "label": f["label"], "type": f["type"], "visible": bool(visible)}
    if not visible:
        d["reason"] = NO_ACCESS_REASON                       # 通用原因：不透露是哪一道規則擋的
        return d
    d.update({"select": bool(f.get("select")), "sort": bool(f.get("sort")), "group": bool(f.get("group")),
              "filter": bool(f.get("filter")), "aggregate": list(f.get("aggregate") or ()),
              "ops": list(RC.OPS_BY_TYPE.get(f["type"], ())) if f.get("filter") else [],
              "bucket": list(f.get("bucket") or ()), "isMe": bool(f.get("isMe"))})
    opts = _enum_options(f, conn)
    if opts is not None:
        d["options"] = opts
    return d


def _source_json(sid, user, conn):
    s = RC.get_source(sid)
    vis = RC.visible_fields(sid, user)
    return {"id": sid, "label": s["label"], "layouts": ["detail", "summary"],
            "fields": [_field_json(f, vis.get(f["id"], False), conn) for f in s["fields"]],
            "defaults": s.get("defaults") or {}, "defaultFilters": list(s.get("defaultFilters") or ())}


@router.get("/api/custom-reports/sources")
def list_sources(authorization: str = Header(None)):
    user = _gate(authorization)
    conn = get_db()
    try:
        return {"sources": [_source_json(sid, user, conn) for sid in RC.sources_for(user)],
                "limits": {"previewRows": RR.PREVIEW_ROWS, "columns": RR.MAX_COLUMNS, "filters": RR.MAX_FILTERS,
                           "groupBy": RR.MAX_GROUPS, "aggregates": RR.MAX_AGGS, "sort": RR.MAX_SORTS},
                "canExport": bool(_perm.can(user, "analytics.custom_report.export") and RP.export_allowed(user, conn))}
    finally:
        conn.close()


@router.post("/api/custom-reports/preview")
def preview(definition=Body(...), authorization: str = Header(None)):
    user = _gate(authorization)
    _check_rate(user["id"])
    try:
        return RR.preview(definition, user)
    except RR.ReportError as e:
        raise _http(e)
    except HTTPException:
        raise
    except Exception:                                        # noqa: BLE001 — 不回顯內部訊息（可能含 SQL 片段）
        _log.exception("custom_reports preview failed")
        raise HTTPException(500, {"message": "報表產生失敗，請稍後再試；若持續發生請通知管理員。"})
