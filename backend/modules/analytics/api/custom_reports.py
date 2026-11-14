# -*- coding: utf-8 -*-
"""自訂報表的端點（T87 B2-S1b；設計：D:\\Claude-pm\\t87-design\\B2-custom-reports.md §9）。前綴 `/api/custom-reports`。

- `GET  /api/custom-reports/sources`  這位使用者可用的資料來源與欄位（不可見的欄位只標「無權限」與通用原因；不含任何資料值）。
- `POST /api/custom-reports/preview`  本文＝報表定義；回傳最多 50 列＋分組小計／總計。不寫任何東西、不留稽核（預覽不是匯出）。
- `GET  /api/custom-reports`          我的報表（＋分享給我的，設定開啟時）。`POST` 新增（≤30 份、名稱不可重複、定義存檔前完整驗證）。
- `GET|PUT|DELETE /api/custom-reports/{id}`  讀／改（`If-Match` 帶 etag，不符 409）／刪（設定決定進暫存區或直接刪）。非擁有者（含不存在）一律 404 同一句；被分享者只能讀與複製。
- `POST /api/custom-reports/{id}/copy`  複製成自己的一份。
- `POST /api/custom-reports/{id}/export`（Excel）、`/export-pdf`（PDF 姊妹）  只能匯出已儲存的報表；需 `analytics.custom_report.export` 能力＋設定 `export_scope` 放行；
  匯出時重新編譯定義、以**執行者當下**的權限與列範圍重算（A 存、B 匯出，B 看不到的欄位不出現、列不出現）；檔內只有可見欄位的標籤、條件的白話摘要、隱藏欄位**數量**（不寫名稱與值）。

[不變式] ①順序：登入 ⇒ 旗標（`custom_reports.enabled`，關 ⇒ 404、不讀寫表）⇒ 能力 `analytics.custom_report.view`（403）⇒ 來源的模組存取（沒有 ⇒ `/sources` 不列、`/preview` 404）。
    能力不取代模組存取，模組存取也不取代能力：兩者每次請求都查。
    ②所有欄位／列的可見性決定都在 `helpers.report_runner`／`report_catalog`（後端每次請求重算）；本檔只轉換成 HTTP，不做任何權限判斷。
    ③錯誤訊息是固定白話，不回顯使用者輸入的值；未預期的例外只記 log、回固定訊息。
    ④每人每分鐘最多 20 次預覽（行程內滑動視窗；多行程時各自計，只當保險絲）；另有全程式庫同時執行上限 `MAX_CONCURRENT_RUNS`（預覽與匯出共用名額，滿了回 429「請等幾秒後再試」）。
[契約題] backend/tests/platform/test_custom_reports_api_t87.py
"""
import io
import logging
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime

from typing import Optional

import openpyxl
from fastapi import APIRouter, Body, Header, HTTPException, Path
from fastapi.responses import Response
from openpyxl.styles import Alignment, PatternFill
from openpyxl.utils import get_column_letter

from db import get_db
from helpers import _audit, _require_user, _tok, download_name
from helpers.xlsx_out import XLSX_MEDIA, add_pdf_sibling, check_export_rate, export_logged, xl_safe_xlsx, xl_style
from helpers import perm as _perm
from helpers import report_catalog as RC
from helpers import report_policy as RP
from helpers import report_runner as RR
from modules.analytics import report_store as ST

router = APIRouter()
_log = logging.getLogger(__name__)

CAP_VIEW = "analytics.custom_report.view"
CAP_EXPORT = "analytics.custom_report.export"
PREVIEW_PER_MINUTE = 20
_WINDOW_SECONDS = 60.0
MAX_CONCURRENT_RUNS = 4                                   # 全程式庫同時執行的預覽／匯出上限（每個最久占一條連線 8 秒）
_runs = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
_hits = defaultdict(deque)
_hits_lock = threading.Lock()
GENERIC_FAIL = "報表產生失敗，請稍後再試；若持續發生請通知管理員。"
NO_ACCESS_REASON = "您沒有查看這個欄位的權限"


def reset_rate_limit() -> None:
    """測試用：清空限流計數。"""
    with _hits_lock:
        _hits.clear()


def _run_slot():
    """取得一個執行名額（不等待）；滿了就 429 白話說明。呼叫端用 try/finally 歸還。"""
    if not _runs.acquire(blocking=False):
        raise HTTPException(429, {"message": "目前有很多人同時在產生報表，請等幾秒後再試。", "reason": "busy"})


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


def _enum_options(f, conn, user):
    if f.get("enum") is None:
        return None
    try:
        return [[v, lab] for v, lab in RC.enum_options(f, conn, user)]
    except Exception:                                        # noqa: BLE001 — 選項讀不到不影響其他欄位
        _log.warning("custom_reports：欄位 %s 的選項讀取失敗", f.get("id"), exc_info=True)
        return []


def _field_json(f, visible, conn, user):
    d = {"id": f["id"], "label": f["label"], "type": f["type"], "visible": bool(visible)}
    if not visible:
        d["reason"] = NO_ACCESS_REASON                       # 通用原因：不透露是哪一道規則擋的
        return d
    d.update({"select": bool(f.get("select")), "sort": bool(f.get("sort")), "group": bool(f.get("group")),
              "filter": bool(f.get("filter")), "aggregate": list(f.get("aggregate") or ()),
              "ops": list(RC.OPS_BY_TYPE.get(f["type"], ())) if f.get("filter") else [],
              "bucket": list(f.get("bucket") or ()), "isMe": bool(f.get("isMe"))})
    opts = _enum_options(f, conn, user)
    if opts is not None:
        d["options"] = opts
    return d


def _source_json(sid, user, conn):
    s = RC.get_source(sid)
    vis = RC.visible_fields(sid, user)
    return {"id": sid, "label": s["label"], "layouts": ["detail", "summary"],
            "fields": [_field_json(f, vis.get(f["id"], False), conn, user) for f in s["fields"]],
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
    _run_slot()
    try:
        return RR.preview(definition, user)
    except RR.ReportError as e:
        raise _http(e)
    except HTTPException:
        raise
    except Exception:                                        # noqa: BLE001 — 不回顯內部訊息（可能含 SQL 片段）
        _log.exception("custom_reports preview failed")
        raise HTTPException(500, {"message": GENERIC_FAIL})
    finally:
        _runs.release()


# ── 我的報表（CRUD；只讀寫自己的列，路徑與本文都沒有帳號參數） ─────────────────────────

def _store_http(e: "ST.StoreError"):
    detail = {"message": e.message}
    detail.update({k: v for k, v in (e.details or {}).items() if k in ("reason", "count")})
    return HTTPException(e.status, detail)


def _audit_report(authorization, action, label, rid, source_id=None):
    _audit(_tok(authorization), action, "custom_report", str(rid), label, {"source": source_id} if source_id else {})


@router.get("/api/custom-reports")
def list_reports(authorization: str = Header(None)):
    user = _gate(authorization)
    conn = get_db()
    try:
        return {"mine": ST.list_mine(conn, user), "shared": ST.list_shared(conn, user), "sharingEnabled": RP.sharing_enabled(conn),
                "recycleDeleted": RP.recycle_deleted(conn), "max": ST.MAX_PER_USER, "nameMax": ST.NAME_MAX}
    finally:
        conn.close()


@router.post("/api/custom-reports", status_code=201)
def create_report(body: dict = Body(...), authorization: str = Header(None)):
    user = _gate(authorization)
    conn = get_db()
    try:
        if set(body) - {"name", "definition"}:
            raise HTTPException(422, {"message": "報表內容格式不正確。"})
        try:
            out = ST.create(conn, user, body.get("name"), body.get("definition"))
        except ST.StoreError as e:
            raise _store_http(e)
        except RR.ReportError as e:
            raise _http(e)
        except Exception:                                    # noqa: BLE001 — 不回 500 內部訊息
            _log.exception("custom_reports create failed")
            raise HTTPException(500, {"message": "儲存失敗，請稍後再試；若持續發生請通知管理員。"})
        _audit_report(authorization, "custom_reports.create", "新增自訂報表", out["id"], out["sourceId"])
        return out
    finally:
        conn.close()


@router.get("/api/custom-reports/{rid}")
def get_report(rid: int = Path(..., ge=1, le=2**31 - 1), authorization: str = Header(None)):
    user = _gate(authorization)
    conn = get_db()
    try:
        try:
            return ST.get_visible(conn, user, rid)
        except ST.StoreError as e:
            raise _store_http(e)
    finally:
        conn.close()


@router.put("/api/custom-reports/{rid}")
def update_report(rid: int = Path(..., ge=1, le=2**31 - 1), body: dict = Body(...), if_match: Optional[str] = Header(None), authorization: str = Header(None)):
    user = _gate(authorization)
    conn = get_db()
    try:
        try:
            out = ST.update(conn, user, rid, if_match, body)
        except ST.StoreError as e:
            raise _store_http(e)
        except RR.ReportError as e:
            raise _http(e)
        except Exception:                                    # noqa: BLE001
            _log.exception("custom_reports update failed")
            raise HTTPException(500, {"message": "儲存失敗，請稍後再試；若持續發生請通知管理員。"})
        _audit_report(authorization, "custom_reports.update", "修改自訂報表", rid, out["sourceId"])
        return out
    finally:
        conn.close()


@router.delete("/api/custom-reports/{rid}")
def delete_report(rid: int = Path(..., ge=1, le=2**31 - 1), authorization: str = Header(None)):
    user = _gate(authorization)
    conn = get_db()
    try:
        try:
            out = ST.delete(conn, user, rid)
        except ST.StoreError as e:
            raise _store_http(e)
        after = out.pop("after_commit", None)
        _audit_report(authorization, "custom_reports.delete", "刪除自訂報表" + ("（進刪除暫存區）" if out["recycled"] else ""), rid)
        if after:
            after()
        return out
    finally:
        conn.close()


@router.post("/api/custom-reports/{rid}/copy", status_code=201)
def copy_report(rid: int = Path(..., ge=1, le=2**31 - 1), authorization: str = Header(None)):
    user = _gate(authorization)
    conn = get_db()
    try:
        try:
            out = ST.copy_report(conn, user, rid)
        except ST.StoreError as e:
            raise _store_http(e)
        except RR.ReportError as e:
            raise _http(e)
        except Exception:                                    # noqa: BLE001
            _log.exception("custom_reports copy failed")
            raise HTTPException(500, {"message": "複製失敗，請稍後再試；若持續發生請通知管理員。"})
        _audit_report(authorization, "custom_reports.copy", "複製自訂報表", out["id"], out["sourceId"])
        return out
    finally:
        conn.close()



# ── 匯出 Excel（＋PDF 姊妹） ───────────────────────────────────────────────

_FNAME_BAD = re.compile(r'[\/:*?"<>|\x00-\x1f]')


def _build_xlsx(name, source_label, user, res, conds, now) -> bytes:
    """報表分頁（標題／條件／產製者與時間／表頭／資料／小計總計）＋說明分頁（來源、列數、已隱藏欄位數、資料截至）。
    輸出文字只來自可見欄位的標籤、條件的白話、報表名稱與數字；文字一律 `xl_safe_xlsx`，不寫任何公式。"""
    wb = openpyxl.Workbook()
    f = xl_style(wb)[0]
    ws = wb.active
    ws.title = "報表"

    def put(sheet, r, c, v, **kw):
        cell = sheet.cell(row=r, column=c, value=xl_safe_xlsx(v))
        cell.font = f(**kw)
        return cell
    put(ws, 1, 1, "%s　MOTRIX PLATFORM" % name, bold=True, size=12)
    put(ws, 2, 1, "條件：" + ("；".join(conds) if conds else "（無）"), size=9)
    put(ws, 3, 1, "產製者：%s　產製時間：%s" % (user.get("display_name") or user.get("username") or "", now), size=9)
    cols = res["columns"]
    head = PatternFill("solid", fgColor="E5E7EB")
    for ci, c in enumerate(cols, 1):
        cell = put(ws, 5, ci, c["label"], bold=True, size=10)
        cell.fill = head
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    band = PatternFill("solid", fgColor="F3F4F6")
    for ri, row in enumerate(res["rows"], 6):
        strong = row["k"] != "row"
        for ci, (c, v) in enumerate(zip(cols, row["v"]), 1):
            cell = put(ws, ri, ci, v, bold=strong, size=10)
            if strong:
                cell.fill = band
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if c["type"] == "money":
                    cell.number_format = "#,##0"
                elif c["type"] == "percent":
                    cell.number_format = '0.0"%"'
                cell.alignment = Alignment(horizontal="right")
    for ci, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(ci)].width = max(10, min(40, len(c["label"]) * 2 + 4))
    ws.freeze_panes = "A6"
    w2 = wb.create_sheet("說明")
    info = [("資料來源", source_label), ("列數", sum(1 for r in res["rows"] if r["k"] == "row")), ("已隱藏欄位數", res["hiddenCount"]),
            ("資料截至", now)] + [("說明", n) for n in res["notes"]]
    for i, (k, v) in enumerate(info, 1):
        put(w2, i, 1, k, bold=True, size=10)
        put(w2, i, 2, v, size=10)
    w2.column_dimensions["A"].width = 16
    w2.column_dimensions["B"].width = 60
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.post("/api/custom-reports/{rid}/export")
@export_logged("xlsx", "analytics", "custom_report")
def export_report(rid: int = Path(..., ge=1, le=2**31 - 1), authorization: str = Header(None)):
    user = _gate(authorization)
    _perm.require(user, CAP_EXPORT)
    conn = get_db()
    try:
        if not RP.export_allowed(user, conn):
            raise HTTPException(403, {"message": "目前設定不開放匯出自訂報表。", "reason": "export_off"})
        try:
            rep = ST.get_for_run(conn, user, rid)
        except ST.StoreError as e:
            raise _store_http(e)
        _run_slot()
        try:
            plan = RR.compile(rep["definition"], user, "export", conn=conn)       # 匯出時重新驗證；以執行者當下權限重算
            check_export_rate(user["id"], "excel")
            spec = RC.get_source(plan.source_id)
            res = RR.assemble(plan, spec["execute"](plan))
            conds = RR.describe_filters(rep["definition"])
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            data = _build_xlsx(rep["name"], spec["label"], user, res, conds, now)
        except RR.ReportError as e:
            raise _http(e)
        except HTTPException:
            raise
        except Exception:                                    # noqa: BLE001 — 不回顯內部訊息
            _log.exception("custom_reports export failed")
            raise HTTPException(500, {"message": "匯出失敗，請稍後再試；若持續發生請通知管理員。"})
        finally:
            _runs.release()
        if rep["isOwner"]:
            try:
                ST.mark_exported(conn, user, rid)
            except Exception:                                # noqa: BLE001 — 記錄匯出時間失敗不影響已產生的檔案
                _log.warning("custom_reports：記錄 last_exported_at 失敗", exc_info=True)
    finally:
        conn.close()
    fname = "MOTRIX_自訂報表_%s_%s.xlsx" % (_FNAME_BAD.sub("_", rep["name"]), datetime.now().strftime("%Y%m%d"))
    return Response(content=data, media_type=XLSX_MEDIA, headers={"Content-Disposition": download_name.content_disposition(fname)})


add_pdf_sibling(router, "/api/custom-reports/{rid}/export-pdf", export_report, module="analytics", name="custom_report",
                title="自訂報表", method="POST")
