# -*- coding: utf-8 -*-
"""自訂模組的通用 API（P8，CUSTOMIZATION-SPEC §3.1／§8.1）。定義的草稿／發布／差異／還原走 `/api/definitions/custom_module/…`。

- 單據：列表、新增、讀取、修改（只限起始狀態）、轉換、簽核（核准／退回）、輸出（HTML／PDF）。
  權限：超級管理員，或使用者的模組清單裡有該模組的權限 key（預設 `custom.<key>`）；簽核人另外可以讀與簽自己那一層。
- 建構器輔助（僅超級管理員）：欄位型別目錄、參照對象目錄、公式語法檢查（回錯誤位置）、編號預覽、輸出預覽（樣本資料）。
"""
import json
from datetime import date

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from db import get_db
from helpers import _require_user, _tok, _audit
from helpers import custom_modules as CM
from helpers import formula as FX
from core import definitions as D

router = APIRouter()

def _validate_custom_module(body, key):
    problems = CM.validate_module(body, key)
    perm = (body or {}).get("permission") if isinstance(body, dict) else None
    if perm:
        # 稽核 D C-S4：兩個自訂模組共用同一個權限 key ⇒ 授權一個等於授權兩個、權限畫面只顯示其中一個名稱
        conn = get_db()
        try:
            other = [m["key"] for m in CM.published_modules(conn) if m["permission"] == perm and m["key"] != key]
        except Exception:                                    # noqa: BLE001 — 表還沒建（全新安裝）
            other = []
        finally:
            conn.close()
        if other:
            problems.append({"path": "permission", "message": "權限 key %s 已被自訂模組 %s 使用" % (perm, "、".join(other))})
    return problems


D.register_validator("custom_module", _validate_custom_module)


def _err(e: CM.CustomModuleError):
    return JSONResponse(status_code=e.status, content={"detail": str(e), "problems": e.problems})


def _can_use(conn, user, key) -> dict:
    """回該模組已發布的定義；沒有權限 ⇒ 403。"""
    try:
        d = CM._load_def(conn, key)
    except CM.CustomModuleError as e:
        raise HTTPException(e.status, str(e))
    if user["role"] == "superadmin":
        return d
    mods = json.loads(user.get("modules") or "[]")
    if CM.permission_of(key, d["body"]) not in mods:
        raise HTTPException(403, "沒有「%s」的權限" % d["body"].get("name", key))
    return d


def _is_approver(rec, username, conn=None) -> bool:
    """簽核鏈裡的人，或是簽核鏈裡某人目前有效的簽核代理人（稽核 D C-S2：代理人能簽卻讀不到單）。"""
    names = {a.get("username") for t in (rec.get("approval") or {}).get("tiers", []) for a in t.get("approvers", [])}
    if username in names:
        return True
    if conn is not None and names:
        from helpers.tiered_approval import active_delegators_for
        return bool(names & set(active_delegators_for(conn, username)))
    return False


# ── 使用者端 ────────────────────────────────────────────────────────────

@router.get("/api/custom-modules")
def list_custom_modules(authorization: str = Header(None)):
    """已發布、而且這位使用者看得到的自訂模組（側欄選單用）。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        mods = CM.published_modules(conn)
    finally:
        conn.close()
    if u["role"] == "superadmin":
        return mods
    mine = set(json.loads(u.get("modules") or "[]"))
    return [m for m in mods if m["permission"] in mine]


@router.get("/api/custom/{key}/meta")
def custom_module_meta(key: str, version: int = Query(None), authorization: str = Header(None)):
    """表單與列表要的定義：預設最新發布版；`?version=N` ⇒ 那一版（看舊單據時用；單據讀取本身也帶 `definition`）。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        d = _can_use(conn, u, key)
        if version is not None and version != d["version"]:
            try:
                d = CM._load_def(conn, key, version)
            except CM.CustomModuleError as e:
                return _err(e)
    finally:
        conn.close()
    return {"key": key, "version": d["version"], "definition": d["body"]}


@router.get("/api/custom/{key}/records")
def list_custom_records(key: str, status: str = Query(None), field: str = Query(None), value: str = Query(None),
                        authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        _can_use(conn, u, key)
        return CM.list_records(conn, key, status=status, field=field, value=value)
    finally:
        conn.close()


@router.post("/api/custom/{key}/records")
def create_custom_record(key: str, payload: dict = Body(...), authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        _can_use(conn, u, key)
        rec = CM.create_record(conn, key, payload.get("values"), u)
    except CM.CustomModuleError as e:
        return _err(e)
    finally:
        conn.close()
    _audit(_tok(authorization), "custom.create", "custom_record", rec["record_no"], "建立 %s" % rec["record_no"], {"module": key})
    return rec


@router.get("/api/custom/{key}/records/{record_no}")
def get_custom_record(key: str, record_no: str, authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        try:
            rec = CM.get_record(conn, key, record_no)
        except CM.CustomModuleError as e:
            return _err(e)
        if not _is_approver(rec, u["username"], conn):
            _can_use(conn, u, key)
        # U14：前端依這個欄位決定要不要顯示「修改」「送出」（後端另外擋 403）
        rec["canEdit"] = CM.can_edit_draft(rec, rec["definition"], u)
        return rec
    finally:
        conn.close()


@router.put("/api/custom/{key}/records/{record_no}")
def update_custom_record(key: str, record_no: str, payload: dict = Body(...), authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        _can_use(conn, u, key)
        rec = CM.update_record(conn, key, record_no, payload.get("values"), u)
    except CM.CustomModuleError as e:
        return _err(e)
    finally:
        conn.close()
    _audit(_tok(authorization), "custom.update", "custom_record", record_no, "修改 %s" % record_no, {"module": key})
    return rec


@router.post("/api/custom/{key}/records/{record_no}/transitions/{tkey}")
def transition_custom_record(key: str, record_no: str, tkey: str, payload: dict = Body(default={}),
                             authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        _can_use(conn, u, key)
        rec = CM.transition(conn, key, record_no, tkey, u, (payload or {}).get("note", ""))
    except CM.CustomModuleError as e:
        return _err(e)
    finally:
        conn.close()
    _audit(_tok(authorization), "custom.transition", "custom_record", record_no, "%s：%s" % (record_no, tkey), {"module": key})
    return rec


def _decide(conn, u, key, record_no, approve, note):
    try:
        return CM.decide(conn, key, record_no, u, approve, note)
    except CM.CustomModuleError as e:
        return _err(e)


@router.post("/api/custom/{key}/records/{record_no}/approve")
def approve_custom_record(key: str, record_no: str, payload: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization)
    note = (payload or {}).get("note", "")
    conn = get_db()
    try:
        rec = _decide(conn, u, key, record_no, True, note)
    finally:
        conn.close()
    if isinstance(rec, dict):
        _audit(_tok(authorization), "custom.approve", "custom_record", record_no, "核准 %s" % record_no, {"module": key, "note": note})
    return rec


@router.post("/api/custom/{key}/records/{record_no}/reject")
def reject_custom_record(key: str, record_no: str, payload: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization)
    note = (payload or {}).get("note", "")
    conn = get_db()
    try:
        rec = _decide(conn, u, key, record_no, False, note)
    finally:
        conn.close()
    if isinstance(rec, dict):
        _audit(_tok(authorization), "custom.reject", "custom_record", record_no, "退回 %s" % record_no, {"module": key, "note": note})
    return rec


@router.get("/api/custom/{key}/records/{record_no}/output")
def output_custom_record(key: str, record_no: str, format: str = Query("html"), authorization: str = Header(None)):
    """單據輸出：用單據凍結的那一版定義的版型。`format=pdf` ⇒ PDF。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        try:
            rec = CM.get_record(conn, key, record_no)
        except CM.CustomModuleError as e:
            return _err(e)
        if not _is_approver(rec, u["username"], conn):
            _can_use(conn, u, key)
        html = CM.render_output(conn, key, record_no)
    finally:
        conn.close()
    if format == "pdf":
        import pdf_gen
        return Response(pdf_gen.html_to_pdf_bytes(html), media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="%s.pdf"' % record_no})
    return HTMLResponse(html)


# ── 建構器輔助（僅超級管理員）──────────────────────────────────────────────

@router.get("/api/custom-modules/catalog")
def custom_module_catalog(authorization: str = Header(None)):
    """能力目錄（建構器只能從這裡挑）：欄位型別、公式函式、參照對象、日期格式、輸出積木。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import doc_template as dt
    return {"fieldTypes": list(CM.FIELD_TYPES), "formulaFunctions": list(FX.FUNCTIONS), "refTargets": CM.ref_targets(),
            "numberingDateFormats": [k for k in CM.DATE_FORMATS], "outputBlocks": sorted(dt.BLOCKS),
            "outputBlockSpecs": dt.BLOCK_SPECS, "outputBlockItemSpecs": dt.BLOCK_ITEM_SPECS,
            "outputThemes": sorted(dt.THEMES), "outputFormats": ["html", "pdf"], "fieldFormats": list(dt.FORMATS),
            "approverSources": CM.APPROVER_SOURCES, "dataClasses": ["T1"]}


@router.post("/api/custom-modules/formula/check")
def check_custom_formula(payload: dict = Body(...), authorization: str = Header(None)):
    """公式語法檢查：`{"formula": "qty * price", "fields": ["qty", "price"]}` ⇒ `{"problems": [{"pos", "message"}]}`。"""
    _require_user(authorization, require_superadmin=True)
    fields = payload.get("fields")
    return {"problems": FX.check(payload.get("formula"), fields if isinstance(fields, list) else None)}


@router.post("/api/custom-modules/numbering/preview")
def preview_custom_numbering(payload: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    n = payload.get("numbering") or {}
    problems = CM._validate_numbering(n)
    if problems:
        return JSONResponse(status_code=422, content={"detail": "編號規則有問題", "problems": problems})
    return {"example": CM.format_number(n, date.today(), 1)}


@router.get("/api/custom/{key}/ref-options/{field}")
def custom_ref_options(key: str, field: str, q: str = Query(""), limit: int = Query(50), authorization: str = Header(None)):
    """參照欄的選項 `[{value, label}]`（主持 P8 缺口 #6）。有該自訂模組權限的人才能查；`q` 以標籤或值模糊比對。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        d = _can_use(conn, u, key)
        f = next((x for x in d["body"].get("fields", []) if x.get("key") == field and x.get("type") == "ref"), None)
        if f is None:
            raise HTTPException(404, "沒有這個參照欄位")
        # 被參照的那一方也要有讀取權限（否則有 A 模組權限的人，可以經 A 的參照欄讀到 B 模組或客戶的清單）
        target = f["target"]
        if target.startswith("custom:"):
            _can_use(conn, u, target[len("custom:"):])                 # 沒有權限 ⇒ 403；模組未發布 ⇒ 404
        else:
            need = CM.ref_target_modules(target)
            if need and u["role"] != "superadmin":
                from helpers import require_any_module
                require_any_module(u, need, "參照對象")               # 沒有任一權限 ⇒ 403
        return CM.ref_options(conn, target, q, max(1, min(int(limit), 200)))
    finally:
        conn.close()


@router.post("/api/custom-modules/{key}/output/preview")
def preview_custom_output(key: str, payload: dict = Body(...), format: str = Query("html"),
                          authorization: str = Header(None)):
    """用樣本資料預覽輸出（建構器 ⑤）。body＝整份模組定義（草稿）。"""
    _require_user(authorization, require_superadmin=True)
    body = payload.get("body")
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"detail": "定義必須是 JSON 物件", "problems": [{"path": "", "message": "定義必須是 JSON 物件"}]})
    problems = [p for p in CM.validate_module(body, key) if p["path"].startswith(("output", "numbering")) or p["path"] == "fields"]
    if problems:
        return JSONResponse(status_code=422, content={"detail": "定義有問題", "problems": problems})
    html = CM.render_view(body, CM.sample_view(body))
    if format == "pdf":
        import pdf_gen
        return Response(pdf_gen.html_to_pdf_bytes(html), media_type="application/pdf")
    return HTMLResponse(html)
