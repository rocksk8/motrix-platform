# -*- coding: utf-8 -*-
"""定義文件庫 API（CUSTOMIZATION-SPEC §3.5；§8 建構器／排版器需要的「草稿、驗證、預覽、發布、差異、還原」）。

僅超級管理員。kind：layout／output_template／custom_fields／custom_module；scope：company 或 role:<角色>。
"""
import json

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from db import get_db
from helpers import _require_user, _tok, _audit
from core import definitions as D

router = APIRouter()


# ── 各 kind 的驗證器與程式預設（登記在這裡：L1 的串接點，之後的模組各自登記自己的 kind 細節）──

def _validate_output_template(body, key):
    from helpers import doc_template as dt
    sample = _SAMPLE_VIEWS.get(key)
    view = sample() if sample else None
    return dt.problems(body, view)


def _default_output_template(key):
    from helpers import doc_template as dt
    try:
        return dt.load_default(key)
    except (OSError, ValueError):
        return None


def _validate_custom_fields(body, key):
    from helpers import custom_fields as cf
    return cf.validate_definition(body, key, _CORE_FIELDS.get(key, ()))


D.register_validator("output_template", _validate_output_template)
D.register_default("output_template", _default_output_template)
D.register_validator("custom_fields", _validate_custom_fields)

#: 各內建模組的核心欄位（自訂欄位不可同名）。模組搬遷後改由 module.json 的 P3 描述提供。
_CORE_FIELDS = {
    "invoice_vouchers": ("voucherNo", "quoteNo", "scope", "amount", "pretaxAmount", "taxAmount", "status",
                         "customerName", "customerTaxId", "projectName", "selectedItems", "quoteItems",
                         "approval", "createdBy", "createdAt"),
}


def _invoice_voucher_sample_view():
    import pdf_gen
    return pdf_gen._invoice_voucher_view({
        "voucherNo": "IV-202609-0001", "quoteNo": "Q-202609-0001", "status": "待簽核", "scope": "items",
        "createdAt": "2026-09-25T09:00:00", "customerName": "範例客戶股份有限公司", "customerTaxId": "12345678",
        "projectName": "範例工程", "amount": 10500, "pretaxAmount": 10000, "taxAmount": 500,
        "selectedItems": [{"description": "範例品項", "brand": "品牌", "qty": 2, "unit": "台",
                           "unitPrice": 5000, "amount": 10000}],
        "quoteItems": [], "approval": {"requestedByDisplay": "申請人", "requestedAt": "2026-09-25T09:00:00"},
        "customFields": {}})


#: 用樣本資料預覽輸出（§8.1 ⑤）：key ⇒ 產生樣本視圖的函式
def _payslip_sample_view():
    import pdf_gen
    return pdf_gen._payslip_view({
        "companyName": "範例股份有限公司", "companyTaxId": "12345678", "companyContactInfo": "Tel 02-0000-0000",
        "contractorName": "範例承攬人", "contractorIdNumber": "A123456789", "serviceContent": "範例勞務",
        "serviceStartDate": "2026-09-01", "serviceEndDate": "2026-09-05", "incomeType": "9A", "slipDate": "2026-09-06",
        "slipNo": "PS-202609-0001", "remarks": "範例備註", "grossAmount": 30000, "paymentMethod": "匯款",
        # 法規數字不寫死（test_legal_params_single_source）：樣本只放金額，不放費率
        "calc": {"taxWithheld": 0, "nhiSupplement": 0, "netAmount": 30000},
        "bankCode": "000", "bankName": "範例銀行", "bankBranch": "範例分行", "bankAccountName": "範例承攬人",
        "bankAccountNumber": "0000000000"})


_SAMPLE_VIEWS = {"invoice_voucher": _invoice_voucher_sample_view, "payslip": _payslip_sample_view}


def _err(e: D.DefinitionError, status=400):
    return JSONResponse(status_code=status, content={"detail": str(e), "problems": e.problems})


@router.get("/api/definitions/{kind}")
def list_definitions(kind: str, authorization: str = Header(None)):
    """同一 kind 的所有定義（含只有草稿的）——建構器的模組清單（主持 P8 缺口 #5）。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        return D.list_definitions(conn, kind)
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()


@router.delete("/api/definitions/{kind}/{key}/draft")
def delete_definition_draft(kind: str, key: str, scope: str = Query("company"), authorization: str = Header(None)):
    """刪草稿（已發布的版本不可刪；要回到舊版用 restore）。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        deleted = D.delete_draft(conn, kind, key, scope)
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()
    if not deleted:
        raise HTTPException(404, "沒有草稿")
    _audit(_tok(authorization), "definitions.delete_draft", "ui_definition", "%s/%s/%s" % (kind, key, scope),
           "刪 %s %s（%s）草稿" % (kind, key, scope), {})
    return {"ok": True}


@router.get("/api/definitions/{kind}/{key}")
def get_definition(kind: str, key: str, scope: str = Query("company"), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        return {"draft": D.get(conn, kind, key, scope, 0), "latest": D.get(conn, kind, key, scope),
                "versions": D.versions(conn, kind, key, scope)}
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()


@router.put("/api/definitions/{kind}/{key}/draft")
def save_definition_draft(kind: str, key: str, scope: str = Query("company"), payload: dict = Body(...),
                          authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        d = D.save_draft(conn, kind, key, scope, payload.get("body"), u["username"])
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()
    _audit(_tok(authorization), "definitions.save_draft", "ui_definition", "%s/%s/%s" % (kind, key, scope),
           "存 %s %s（%s）草稿" % (kind, key, scope), {})
    return {"draft": d, "problems": D.validate(kind, key, d["body"])}


@router.post("/api/definitions/{kind}/{key}/validate")
def validate_definition(kind: str, key: str, payload: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    if kind not in D.KINDS:
        raise HTTPException(400, "未知的定義種類")
    return {"problems": D.validate(kind, key, payload.get("body"))}


@router.post("/api/definitions/{kind}/{key}/publish")
def publish_definition(kind: str, key: str, scope: str = Query("company"), payload: dict = Body(default={}),
                       authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        d = D.publish(conn, kind, key, scope, (payload or {}).get("note", ""), u["username"])
    except D.DefinitionError as e:
        return _err(e, 422 if e.problems else 400)
    finally:
        conn.close()
    _audit(_tok(authorization), "definitions.publish", "ui_definition", "%s/%s/%s" % (kind, key, scope),
           "發布 %s %s（%s）第 %d 版" % (kind, key, scope, d["version"]), {"note": d.get("note", "")})
    return d


@router.get("/api/definitions/{kind}/{key}/versions/{version}")
def get_definition_version(kind: str, key: str, version: int, scope: str = Query("company"),
                           authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        d = D.get(conn, kind, key, scope, version)
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()
    if d is None:
        raise HTTPException(404, "沒有這一版")
    return d


@router.get("/api/definitions/{kind}/{key}/diff")
def diff_definition(kind: str, key: str, scope: str = Query("company"), a: str = Query("latest"),
                    b: str = Query("draft"), authorization: str = Header(None)):
    """版本對版本的差異；`latest`＝最新發布、`draft`＝草稿、`default`＝程式預設、數字＝該版。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        def pick(x):
            if x == "draft":
                r = D.get(conn, kind, key, scope, 0)
            elif x == "latest":
                r = D.get(conn, kind, key, scope)
            elif x == "default":
                body, _src = D.resolve(conn, kind, key)
                return body or {}
            else:
                r = D.get(conn, kind, key, scope, int(x))
            return (r or {}).get("body") or {}
        return {"changes": D.diff(pick(a), pick(b))}
    except (D.DefinitionError, ValueError) as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@router.post("/api/definitions/{kind}/{key}/restore/{version}")
def restore_definition(kind: str, key: str, version: int, scope: str = Query("company"),
                       payload: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        d = D.restore(conn, kind, key, scope, version, (payload or {}).get("note", ""), u["username"])
    except D.DefinitionError as e:
        return _err(e, 422 if e.problems else 400)
    finally:
        conn.close()
    _audit(_tok(authorization), "definitions.restore", "ui_definition", "%s/%s/%s" % (kind, key, scope),
           "還原 %s %s（%s）第 %d 版為第 %d 版" % (kind, key, scope, version, d["version"]), {})
    return d


@router.get("/api/definitions/{kind}/{key}/resolve")
def resolve_definition(kind: str, key: str, role: str = Query(None), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        body, source = D.resolve(conn, kind, key, role)
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()
    return {"body": body, "source": source}


@router.post("/api/definitions/output_template/{key}/preview")
def preview_output_template(key: str, payload: dict = Body(...), format: str = Query("html"),
                            authorization: str = Header(None)):
    """用樣本資料預覽輸出（HTML；前端可以直接顯示，也可以另外要 PDF）。版型錯誤回 422 並附問題。"""
    _require_user(authorization, require_superadmin=True)
    from helpers import doc_template as dt
    sample = _SAMPLE_VIEWS.get(key)
    if sample is None:
        raise HTTPException(404, "這個輸出還沒有提供樣本資料預覽")
    body = payload.get("body")
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"detail": "版型必須是 JSON 物件", "problems": [{"path": "", "message": "版型必須是 JSON 物件"}]})
    problems = dt.problems(body, sample())
    if problems:
        return JSONResponse(status_code=422, content={"detail": "版型有問題", "problems": problems})
    import pdf_gen
    builders = {"invoice_voucher": pdf_gen._build_invoice_voucher_html, "payslip": pdf_gen._build_payslip_html}
    html = builders[key](json.loads(json.dumps(sample())), template=body)
    if format == "pdf":
        from fastapi.responses import Response
        return Response(pdf_gen.html_to_pdf_bytes(html), media_type="application/pdf")
    return HTMLResponse(html)
