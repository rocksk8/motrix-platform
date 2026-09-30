# -*- coding: utf-8 -*-
"""自訂模組的通用 API（P8，CUSTOMIZATION-SPEC §3.1／§8.1）。定義的草稿／發布／差異／還原走 `/api/definitions/custom_module/…`。

- 單據：列表、新增、讀取、修改（只限起始狀態）、轉換、簽核（核准／退回）、輸出（HTML／PDF）。
  權限：超級管理員，或使用者的模組清單裡有該模組的權限 key（預設 `custom.<key>`）；簽核人另外可以讀與簽自己那一層。
- 建構器輔助（僅超級管理員）：欄位型別目錄、參照對象目錄、公式語法檢查（回錯誤位置）、編號預覽、輸出預覽（樣本資料）。
"""
import json
from datetime import date

from typing import List

from fastapi import APIRouter, Body, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from db import get_db
from helpers import _require_user, _tok, _audit
from helpers.tiered_approval import require_reject_reason as _require_reject_reason  # noqa: E402  退回一律要填原因
from helpers import custom_modules as CM
from helpers import custom_builder_support as SUP
from helpers import custom_files as CFILES
from helpers import custom_finance as CFIN
from helpers import custom_def_review as DEFR
from helpers import custom_history as HIST
from helpers import uploads as _uploads
from core import registry as _registry
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
    if not SUP.can_see_menu(d["body"].get("menu"), user):        # menu.visibleTo：直接打 API 也一樣（不只藏選單；404 不洩漏模組存在）
        raise HTTPException(404, "沒有這個模組")
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
    return CM.visible_to(mods, u)


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
        body = _can_use(conn, u, key)["body"]
        if field and field in SUP.hidden_keys(body, u):        # 用看不到的欄位篩選＝可以反推它的值 ⇒ 擋（不洩漏欄位存在，與不存在的欄位同一句）
            raise HTTPException(400, "沒有這個欄位可以篩選：%s" % field)
        rows = CM.list_records(conn, key, status=status, field=field, value=value)
        return SUP.mask_records(rows, body, u)
    finally:
        conn.close()


@router.post("/api/custom/{key}/records")
def create_custom_record(key: str, payload: dict = Body(...), authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        _can_use(conn, u, key)
        d = _can_use(conn, u, key)
        vals, forbidden = SUP.guard_writes(d["body"], payload.get("values"), None, u)
        if forbidden:
            raise HTTPException(403, "有欄位你沒有修改權限：" + "；".join(x["message"] for x in forbidden))
        rec = CM.create_record(conn, key, vals, u)
    except CM.CustomModuleError as e:
        return _err(e)
    finally:
        conn.close()
    _audit(_tok(authorization), "custom.create", "custom_record", rec["record_no"], "建立 %s" % rec["record_no"], {"module": key})
    return SUP.mask_record(rec, u)


@router.post("/api/custom/{key}/compute")
def compute_custom_record(key: str, payload: dict = Body(...), version: int = Query(None), authorization: str = Header(None)):
    """填單時即時算公式與明細列（不存檔；權限同建立單據）。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        _can_use(conn, u, key)
        d = _can_use(conn, u, key)
        return SUP.mask_compute(CM.compute_preview(conn, key, payload.get("values"), version), d["body"], u)
    except CM.CustomModuleError as e:
        return _err(e)
    finally:
        conn.close()


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
        return SUP.mask_record(rec, u)
    finally:
        conn.close()


@router.get("/api/custom/{key}/records/{record_no}/revisions")
def list_custom_record_revisions(key: str, record_no: str, authorization: str = Header(None)):
    """送簽修訂紀錄（-R1、-R2…）：每次送簽一列（誰、何時、用哪一版定義、核可／退回與原因）。與讀單同權限。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        try:
            rec = CM.get_record(conn, key, record_no)
        except CM.CustomModuleError as e:
            return _err(e)
        if not _is_approver(rec, u["username"], conn):
            _can_use(conn, u, key)
        return {"current": {"revision": rec.get("revision") or 0, "displayNo": rec["displayNo"], "status": rec["status"]},
                "revisions": HIST.list_revisions(conn, rec, rec["definition"], u)}
    finally:
        conn.close()


@router.get("/api/custom/{key}/records/{record_no}/revisions/diff")
def diff_custom_record_revisions(key: str, record_no: str, a: str = Query("0"), b: str = Query("current"),
                                 authorization: str = Header(None)):
    """兩個修訂的逐欄位差異（`a`／`b`＝修訂號或 `current`）；看不到的欄位不出現（與讀單同一個遮蔽）。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        try:
            rec = CM.get_record(conn, key, record_no)
        except CM.CustomModuleError as e:
            return _err(e)
        if not _is_approver(rec, u["username"], conn):
            _can_use(conn, u, key)
        for x in (a, b):
            if x != "current" and not x.isdigit():
                raise HTTPException(400, "a／b 要是修訂號或 current")
        try:
            return HIST.diff_revisions(conn, rec, rec["definition"], a, b, u)
        except ValueError as e:
            raise HTTPException(404, str(e))
    finally:
        conn.close()


@router.put("/api/custom/{key}/records/{record_no}")
def update_custom_record(key: str, record_no: str, payload: dict = Body(...), authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        _can_use(conn, u, key)
        cur = CM.get_record(conn, key, record_no)
        vals, forbidden = SUP.guard_writes(cur["definition"], payload.get("values"), cur["data"], u)
        if forbidden:
            raise HTTPException(403, "有欄位你沒有修改權限：" + "；".join(x["message"] for x in forbidden))
        rec = CM.update_record(conn, key, record_no, vals, u)
    except CM.CustomModuleError as e:
        return _err(e)
    finally:
        conn.close()
    _audit(_tok(authorization), "custom.update", "custom_record", record_no, "修改 %s" % record_no, {"module": key})
    return SUP.mask_record(rec, u)


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
    return SUP.mask_record(rec, u)


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
        return SUP.mask_record(rec, u)
    return rec


@router.post("/api/custom/{key}/records/{record_no}/reject")
def reject_custom_record(key: str, record_no: str, payload: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization)
    note = _require_reject_reason((payload or {}).get("note", ""))
    conn = get_db()
    try:
        rec = _decide(conn, u, key, record_no, False, note)
    finally:
        conn.close()
    if isinstance(rec, dict):
        _audit(_tok(authorization), "custom.reject", "custom_record", record_no, "退回 %s" % record_no, {"module": key, "note": note})
        return SUP.mask_record(rec, u)
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
        html = SUP.render_output_for(conn, key, record_no, u)
    finally:
        conn.close()
    if format == "pdf":
        import pdf_gen
        return Response(pdf_gen.html_to_pdf_bytes(html), media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="%s.pdf"' % record_no})
    return HTMLResponse(html)


# ── 附件（file／image 欄位）：先傳後綁單 ─────────────────────────────────────

# L1 沒有 ModuleSpec ⇒ 匯入時登記讀檔權限提供者（IP-104；同 routers/system 的工作日誌照片）
_registry.provide(_uploads.PATH_ACCESS, CFILES.PROVIDER, CFILES.CustomFilesAccess)
# 自訂模組的支出進營運報表（IP-9 expense.entries；名稱 custom_module）
_registry.provide("expense.entries", "custom_module", CFIN.expense_entries)
# 模組定義送審（S4）：簽核佇列的待簽項目與詳情（type custom_module_def）
_registry.provide("approval.queue_items", "custom_module_def", DEFR.queue_items)
_registry.provide("approval.detail", DEFR.QUEUE_TYPE, DEFR.detail)


@router.post("/api/custom/{key}/files/{field}")
async def upload_custom_files(key: str, field: str, files: List[UploadFile] = File(...), authorization: str = Header(None)):
    """上傳附件到暫存（record_id＝0，只有自己讀得到）；存單時才綁到單據。副檔名＝欄位 accept ∩ uploads 白名單。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        d = _can_use(conn, u, key)
        f = next((x for x in d["body"].get("fields", []) if isinstance(x, dict) and x.get("key") == field and x.get("type") in ("file", "image")), None)
        if f is None:
            raise HTTPException(404, "沒有這個附件欄位")
        if not SUP.can_see_field(f, u):
            raise HTTPException(403, "沒有這個欄位的權限")
        ok = CFILES.accepted_exts(f)
        for up in files:
            ext = (up.filename or "").rsplit(".", 1)[-1].lower() if "." in (up.filename or "") else ""
            if ext not in ok:
                raise HTTPException(400, "「%s」不接受 %s 檔（可用：%s）" % (f.get("label") or field, ext or "沒有副檔名", "、".join(sorted(set(e for e in ok if e != "jpeg")))))
        CFILES.purge_stale_staged(conn)
        saved = await _uploads.save_document_files("custom_records", key, files, u["username"])
        out = CFILES.register_staged(conn, key, field, saved, u["username"])
    finally:
        conn.close()
    _audit(_tok(authorization), "custom.file_upload", "custom_record_file", "%s/%s" % (key, field),
           "上傳附件 %d 個到 %s／%s" % (len(out), key, field), {"files": [m["filename"] for m in out]})
    return out


@router.delete("/api/custom/{key}/files/{file_id}")
def delete_staged_custom_file(key: str, file_id: str, authorization: str = Header(None)):
    """刪自己暫存、還沒綁單的檔（已綁單的要改單據內容才會移除；已送出的單據內容凍結 ⇒ 開修訂版）。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        _can_use(conn, u, key)
        if not CFILES.remove_staged(conn, key, file_id, u["username"]):
            raise HTTPException(404, "找不到這個暫存檔（只能刪自己上傳、尚未存進單據的檔）")
    finally:
        conn.close()
    _audit(_tok(authorization), "custom.file_delete_staged", "custom_record_file", file_id, "刪除暫存附件 %s（%s）" % (file_id, key), {})
    return {"ok": True}


# ── 金流：案件成本、待補登、被略過的收入 ─────────────────────────────────────

@router.get("/api/custom-modules/finance/case/{case_no}")
def custom_finance_of_case(case_no: str, authorization: str = Header(None)):
    """某案件在自訂模組裡的入帳金流（案件成本用）。看得到案件底下單據的人才能讀（同 `case_documents_readable`）；
    沒有案件模組／案件不存在／看不到 ⇒ 同一個 404（M01-O1：看不到＝不存在，不洩漏案件是否存在）。沒有查看財務金額權限 ⇒ 403（非逐案判定）。"""
    from helpers import can_see_financial
    from helpers.case_access import case_documents_readable, deny_case
    u = _require_user(authorization)
    if not can_see_financial(u):
        raise HTTPException(403, "沒有查看財務金額的權限")
    conn = get_db()
    try:
        if not case_documents_readable(conn, case_no, u):
            deny_case(conn, case_no, u, "denied")            # 404（訊息同查無）＋audit 真正原因；同時關連線
        return CFIN.case_finance(conn, case_no)
    finally:
        conn.close()


@router.get("/api/custom-modules/finance/summary")
def custom_finance_summary(basis: str = Query("cash"), authorization: str = Header(None)):
    """建構器／管理者對帳用：待補登（缺該口徑日期）與因關聯內建案件而略過的收入。僅超級管理員。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        return {"undated": CFIN.undated_counts(conn, basis), "dupSkipped": CFIN.dup_skipped(conn)}
    finally:
        conn.close()


# ── 模組定義送審（S4）：審核畫面與核可／退回（送審本身走 POST /api/definitions/custom_module/{key}/publish）──

def _def_review_state(username=""):
    conn = get_db()
    try:
        st = DEFR.review_state(conn, username)
        return {"mode": st["mode"], "active": st["active"], "reason": st["reason"],
                "reviewers": [{"username": r["username"], "displayName": r["displayName"]} for r in st["reviewers"]]}
    finally:
        conn.close()


def _review_err(e):
    return JSONResponse({"detail": str(e), "problems": e.problems}, status_code=e.status)


@router.get("/api/custom-modules/{key}/definition/review")
def custom_definition_review(key: str, authorization: str = Header(None)):
    """送審中的那一版（簽核進度、與現行版的差異）＋被退回的歷史。最高管理者、簽核鏈上的人、申請人可讀。"""
    u = _require_user(authorization)
    conn = get_db()
    try:
        return {"reviewEnabled": DEFR.review_state(conn, u["username"])["active"], **DEFR.open_view(conn, key, u)}
    except DEFR.ReviewError as e:
        return _review_err(e)
    finally:
        conn.close()


@router.post("/api/custom-modules/{key}/definition/{version}/approve")
def approve_custom_definition(key: str, version: int, payload: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        out = DEFR.decide(conn, key, version, u, True, (payload or {}).get("note", ""))
    except DEFR.ReviewError as e:
        return _review_err(e)
    finally:
        conn.close()
    _audit(_tok(authorization), "custom_def.approve", "ui_definition", "custom_module/%s" % key, "核可 %s 第 %d 版定義" % (key, version), {"published": out["published"]})
    return out


@router.post("/api/custom-modules/{key}/definition/{version}/reject")
def reject_custom_definition(key: str, version: int, payload: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    try:
        out = DEFR.decide(conn, key, version, u, False, (payload or {}).get("note", ""))
    except DEFR.ReviewError as e:
        return _review_err(e)
    finally:
        conn.close()
    _audit(_tok(authorization), "custom_def.reject", "ui_definition", "custom_module/%s" % key, "退回 %s 第 %d 版定義" % (key, version), {"note": (payload or {}).get("note", "")})
    return out


@router.get("/api/custom-modules/definition-review")
def get_custom_definition_review(authorization: str = Header(None)):
    """目前的「定義送審」狀態（給建構器標頭顯示）：模式（auto／on／off）、有沒有啟用、審核人、沒啟用的原因。"""
    u = _require_user(authorization, require_superadmin=True)
    return _def_review_state(u["username"])


@router.put("/api/custom-modules/definition-review")
def set_custom_definition_review(payload: dict = Body(...), authorization: str = Header(None)):
    """設定「模組審核人」名單與手動覆寫（`mode`：auto 預設＝依名單、on 強制送審、off 強制直接發布）。僅超級管理員；寫稽核。
    名單裡有申請人以外至少一人 ⇒ 送審自動啟用；沒有 ⇒ 發布維持直接發布（稽核記「未經第二人審核」）。"""
    u = _require_user(authorization, require_superadmin=True)
    if "mode" not in payload and "reviewers" not in payload:
        raise HTTPException(400, "要帶 mode 或 reviewers")
    conn = get_db()
    try:
        DEFR.set_review_settings(conn, payload.get("mode"), payload.get("reviewers"))
    except DEFR.ReviewError as e:
        return _review_err(e)
    finally:
        conn.close()
    _audit(_tok(authorization), "custom_def.review_settings", "settings", DEFR.SETTING_KEY,
           "定義送審設定：mode=%s reviewers=%s" % (payload.get("mode"), payload.get("reviewers")), {})
    return _def_review_state(u["username"])


# ── 建構器輔助（僅超級管理員）──────────────────────────────────────────────

@router.get("/api/custom-modules/catalog")
def custom_module_catalog(authorization: str = Header(None)):
    """能力目錄（建構器只能從這裡挑）：欄位型別、公式函式、參照對象、日期格式、輸出積木。"""
    cu = _require_user(authorization, require_superadmin=True)
    from helpers import doc_template as dt
    tpls, tpl_gaps = CM.templates(include_gaps=True)
    return {"fieldTypes": list(CM.FIELD_TYPES), "formulaFunctions": list(FX.FUNCTIONS), "refTargets": CM.ref_targets(),
            "fieldTypeSpecs": CM.field_type_specs(), "fieldElements": CM.FIELD_ELEMENTS, "elementGroups": CM.ELEMENT_GROUPS,
            "financeKinds": list(CM.FINANCE_KINDS), "templates": tpls, "templateGaps": tpl_gaps,
            "tableColumnTypes": list(CM.TABLE_COL_TYPES), "tableFunctions": list(FX.TABLE_FUNCTIONS),
            "numberingDateFormats": [k for k in CM.DATE_FORMATS], "outputBlocks": sorted(dt.BLOCKS),
            "outputBlockSpecs": dt.BLOCK_SPECS, "outputBlockItemSpecs": dt.BLOCK_ITEM_SPECS,
            "outputThemes": sorted(dt.THEMES), "outputFormats": ["html", "pdf"], "fieldFormats": list(dt.FORMATS),
            "approverSources": CM.APPROVER_SOURCES, "dataClasses": ["T1"],
            "roles": list(SUP.VISIBLE_ROLES), "defReview": _def_review_state(cu["username"])}


@router.get("/api/custom-modules/templates/{tkey}")
def custom_module_template(tkey: str, authorization: str = Header(None)):
    """範本的整份定義（新建模組時「從範本開始」用；套用後與範本脫鉤）。僅超級管理員。"""
    _require_user(authorization, require_superadmin=True)
    body = CM.template_body(tkey)
    if body is None:
        raise HTTPException(404, "沒有這個範本（或範本沒通過載入驗證）")
    return {"key": tkey, "body": body}


@router.post("/api/custom-modules/formula/check")
def check_custom_formula(payload: dict = Body(...), authorization: str = Header(None)):
    """公式語法檢查：`{"formula": "qty * price", "fields": ["qty", "price"], "tables": {"lines": ["amt"]}}`
    ⇒ `{"problems": [{"pos", "message"}]}`（`tables`＝明細表 key ⇒ 可加總的數值欄，選填）。"""
    _require_user(authorization, require_superadmin=True)
    fields = payload.get("fields")
    tables = payload.get("tables")
    return {"problems": FX.check(payload.get("formula"), fields if isinstance(fields, list) else None,
                                 tables if isinstance(tables, dict) else None)}


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
    """用樣本資料預覽輸出（建構器 ⑤；即時預覽 BUILDER-UX §3.4）。body＝整份模組定義（草稿，可以是編到一半的）。
    只讀：不寫庫、不存檔。未完成的欄位畫成佔位，清單放在回應標頭 `X-Motrix-Preview-Incomplete`（JSON，ASCII 跳脫）。
    只有連一個欄位都畫不出來、或版型結構錯時才 422；任何半成品都不可以 500。"""
    _require_user(authorization, require_superadmin=True)
    body = payload.get("body")
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"detail": "定義必須是 JSON 物件", "problems": [{"path": "", "message": "定義必須是 JSON 物件"}]})
    try:
        html, incomplete = CM.preview_output(body)
        if format == "pdf":
            import pdf_gen
            resp = Response(pdf_gen.html_to_pdf_bytes(html), media_type="application/pdf")
        else:
            resp = HTMLResponse(html)
    except CM.CustomModuleError as e:
        return JSONResponse(status_code=422, content={"detail": str(e), "problems": e.problems})
    except HTTPException:          # 第二道 428（COMPANY-SETUP-GATE §5）不可以被下面的 except Exception 吞成 500
        raise
    except Exception as e:                                   # noqa: BLE001 — 預覽是唯讀的輔助：半成品草稿不可以讓它 500
        # log 與回應都只帶例外型別＋位置（檔:行:函式）：例外訊息可能含草稿內容，stack 不回給前端
        import logging
        import traceback
        where = " < ".join("%s:%d:%s" % (f.filename.replace("\\", "/").rsplit("/", 1)[-1], f.lineno, f.name)
                           for f in reversed(traceback.extract_tb(e.__traceback__)[-4:]))
        logging.getLogger(__name__).error("輸出預覽失敗（%s）：%s @ %s", key, type(e).__name__, where)
        return JSONResponse(status_code=422, content={"detail": "這份草稿暫時無法預覽", "problems": [{"path": "", "message": "無法產生預覽：%s" % type(e).__name__}]})
    resp.headers["X-Motrix-Preview-Incomplete"] = json.dumps(incomplete[:50])
    return resp
