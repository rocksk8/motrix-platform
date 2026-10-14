# -*- coding: utf-8 -*-
"""定義文件庫 API（CUSTOMIZATION-SPEC §3.5；§8 建構器／排版器需要的「草稿、驗證、預覽、發布、差異、還原」）。

`/api/definitions/…` 僅超級管理員。kind：layout／output_template／custom_fields／custom_module；scope：company 或 role:<角色>。
例外：`GET /api/layout/{module}`（P9 執行時套用，§3.10）任何登入者可讀**自己角色**的版面（唯讀、只有 layout）。
"""
import json
import re

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from db import get_db
from helpers import _require_user, _tok, _audit
from core import definitions as D
from core import spine as _spine
from helpers import expense_types as _expense_types  # noqa: F401  匯入即登記 expense_type 定義種類（A2-2）

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


# ── layout（P9 排版器；CUSTOMIZATION-SPEC §3.9「排版守門」、§3.10 套用）──────────────
#: 版面定義的 key＝`module:<模組 key>`；body＝`{"ops": [排版操作…]}`（core.customization.OP_KEYS）。
LAYOUT_KEY = re.compile(r"^module:([a-z][a-z0-9_]{0,39})$")


def _layout_module(key):
    m = LAYOUT_KEY.match(key or "")
    return m.group(1) if m else None


def _validate_layout(body, key):
    """P5 layout 驗證器：只能動 `catalog.layout_points(模組)` 裡的點（經 `catalog.check_layout`）。
    問題的 path 以 body 為根（`ops[3].target`），給排版器標回畫面。"""
    from core import catalog, registry
    mod = _layout_module(key)
    if mod is None:
        return [{"path": "", "message": "版面的 key 必須是 module:<模組 key>：%r" % key}]
    out = [{"path": k, "message": "不認得的鍵（版面只有 ops）"} for k in body if k != "ops"]
    if "ops" not in body:
        return out + [{"path": "ops", "message": "缺 ops（排版操作清單）"}]
    if not registry.is_loaded(mod):
        return out + [{"path": "", "message": "模組 %s 未載入（停用、未授權或不存在）⇒ 沒有可排版的點" % mod}]
    probs = out + [{"path": "ops" + p["path"], "message": p["message"]} for p in catalog.check_layout(mod, body["ops"])]
    from helpers import menu_builder as MB                  # BP-1：關著時不接受側欄改名／換群組
    if isinstance(body["ops"], list) and not MB.enabled():
        probs += [{"path": "ops[%d]" % i, "message": MB.OFF_REASON} for i, op in enumerate(body["ops"]) if MB.is_builder_op(op)]
    return probs


def _default_layout(key):
    """程式預設＝不做任何操作（模組 module.json 登記的原樣）。模組未載入 ⇒ 沒有預設。"""
    from core import registry
    mod = _layout_module(key)
    return {"ops": []} if mod and registry.is_loaded(mod) else None


D.register_validator("layout", _validate_layout)
D.register_default("layout", _default_layout)

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


#: 第二人審核只涵蓋「自訂模組定義（company 範圍）」——它會新增頁面、資料表與金流串接。
#: 版面／輸出版型／自訂欄位 是超級管理員直接發布（不審核）；**每一條直接發布的路徑都寫稽核
#: `definitions.publish_unreviewed`**（同一個動作名，稽核一次篩得到）。W3 #3：不准有沒留痕的直接發布。
_UNREVIEWED_KIND_REASON = "此類定義不走第二人審核（只有自訂模組定義有審核流程）"


#: 受管 kind（S1-1，2026-10-13）：只能經擁有它的 L1 入口寫入——雙人核准、待生效、變更明細都在那個入口裡。
#: 通用的 草稿／發布／還原／刪草稿 端點對它們一律 409；GET（清單、單版、差異、解析）不受影響。
#: 之前 `setting_group` 沒有這道門：任一最高管理者可直接 PUT draft ＋ POST publish，繞過 `settings_registry.publish()`
#: 的 放寬→待生效→第二位最高管理者核准，也不寫 `config_changes`（只留 `definitions.publish_unreviewed`）。
_MANAGED_KINDS = {
    "setting_group": "設定要到「系統 > 設定中心」調整：放寬類的變更需要第二位最高管理者核准，並會留下變更明細；這裡不提供直接修改。",
}


def _group_status(kind, key):
    """kind 有登記功能狀態閘門（`spine.register_kind_gate`：`setting_group`、日後的 `alert_rule`…）⇒ 該 key 的狀態（open｜planned｜hidden）；
    沒有登記閘門 ⇒ open。閘門函式壞掉 ⇒ hidden（fail-closed）。"""
    return _spine.kind_status(kind, key)


def _managed_message(kind):
    """受管 kind 的白話訊息：先看本檔的內建（`setting_group` 不依賴任何 import 順序），再看 `spine.register_managed_kind` 登記的。"""
    return _MANAGED_KINDS.get(kind) or _spine.managed_message(kind)


_PLANNED_MSG = "這項功能還在開發中，尚未開放調整。"


def _group_gate(kind, key):
    """設定群組的任何『指名某個群組』的通用路由（讀取、驗證）：hidden ⇒ 404（連 superadmin 也不顯示）、planned ⇒ 409（只有名稱與狀態可見，細節不給）。"""
    st = _group_status(kind, key)
    if st == "hidden":
        raise HTTPException(404, "沒有這個定義")
    if st == "planned":
        raise HTTPException(409, _PLANNED_MSG)


def _managed_guard(kind, authorization=None, key="", verb=""):
    """受管 kind 的通用寫入一律 409（hidden 群組 ⇒ 404，不洩漏存在）；並留稽核 `definitions.managed_refused`（只記 kind／key／動作，不記內容）——繞過設定中心的嘗試要看得到。"""
    msg = _managed_message(kind)
    if msg:
        try:
            _audit(_tok(authorization), "definitions.managed_refused", "ui_definition", "%s/%s" % (kind, key),
                   "拒絕經通用定義介面%s %s %s（受管類型，請到設定中心）" % (verb, kind, key), {})
        except Exception:                                                  # noqa: BLE001  稽核寫不進去也要擋下
            pass
        if _group_status(kind, key) == "hidden":
            raise HTTPException(404, "沒有這個定義")
        raise HTTPException(409, msg)


def _audit_unreviewed(authorization, kind, key, scope, version, reason, verb="發布"):
    _audit(_tok(authorization), "definitions.publish_unreviewed", "ui_definition", "%s/%s/%s" % (kind, key, scope),
           "%s %s %s（%s）第 %d 版：未經第二人審核（%s）" % (verb, kind, key, scope, version, reason), {})


def _custom_module_scope_guard(kind, scope):
    """自訂模組定義只有 company 範圍：引擎只讀 company（`custom_modules.published_modules`），其他範圍不會生效，
    也不該有一條不過審核的寫入路徑（W3 #3）。"""
    if kind == "custom_module" and scope != "company":
        raise HTTPException(400, "自訂模組定義只有 company 範圍")


def _err(e: D.DefinitionError, status=400):
    if isinstance(e, D.DefinitionConflict):
        status = 409
    content = {"detail": str(e), "problems": e.problems}
    if isinstance(e, D.DraftConflict):                                  # K-2：前端據 code 顯示「別人剛改過」，current 帶最後存的人與時間
        content["code"] = "draft_conflict"
        content["current"] = e.current
    return JSONResponse(status_code=status, content=content)


@router.get("/api/definition-kinds")
def list_definition_kinds(authorization: str = Header(None)):
    """定義種類清單（內建＋模組登記的）——編輯畫面用；只有超級管理員。"""
    _require_user(authorization, require_superadmin=True)
    return {"kinds": D.kinds_meta()}


@router.get("/api/expense-types")
def list_expense_types(authorization: str = Header(None)):
    """費用單據類型清單（已啟用；任何登入者——新增表單的下拉用）。定義的編輯走 `/api/definitions/expense_type`（超級管理員）。"""
    _require_user(authorization)
    from helpers import expense_types as ET
    conn = get_db()
    try:
        return ET.list_types(conn)
    finally:
        conn.close()


@router.get("/api/expense-types/{code}")
def get_expense_type(code: str, version: int = Query(None, ge=0), authorization: str = Header(None)):
    """類型定義（預設＝目前生效版；`version`＝單據釘住的版本，0＝程式預設）。任何登入者（表單要依定義渲染）。"""
    _require_user(authorization)
    from helpers import expense_types as ET
    conn = get_db()
    try:
        t = ET.get_type(conn, code, version)
    finally:
        conn.close()
    if t is None:
        raise HTTPException(404, "查無這個單據類型")
    return {"code": t["code"], "defVersion": t["version"], "definition": t["body"]}


@router.get("/api/definitions/{kind}")
def list_definitions(kind: str, authorization: str = Header(None)):
    """同一 kind 的所有定義（含只有草稿的）——建構器的模組清單（主持 P8 缺口 #5）。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        rows = D.list_definitions(conn, kind)
        if not _spine.has_kind_gate(kind):
            return rows
        out = []                                                           # 有功能狀態閘門的 kind：hidden 不列；planned 只留名稱與狀態
        for r in rows:
            info = _spine.kind_info(kind, r["key"])
            if info["status"] == "hidden":
                continue
            if info["status"] == "planned":
                out.append({"key": r["key"], "scope": r.get("scope", "company"), "status": "planned", "plannedTrain": info["plannedTrain"]})
                continue
            out.append(r)
        return out
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()


@router.delete("/api/definitions/{kind}/{key}/draft")
def delete_definition_draft(kind: str, key: str, scope: str = Query("company"), authorization: str = Header(None)):
    """刪草稿（已發布的版本不可刪；要回到舊版用 restore）。"""
    _require_user(authorization, require_superadmin=True)
    _managed_guard(kind, authorization, key, "刪草稿")
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


@router.delete("/api/definitions/custom_module/{key}")
def delete_custom_module(key: str, with_records: bool = Query(False), authorization: str = Header(None)):
    """刪整個自訂模組（所有版本＋草稿）。有單據 ⇒ 409（帶單據數）；`with_records=1` 才連單據一起刪（已入帳的一律拒絕）。"""
    from helpers import custom_module_delete as MD
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        r = MD.delete_module(conn, key, with_records)
    except MD.ModuleDeleteError as e:
        return JSONResponse(status_code=e.status, content={"detail": str(e), "records": e.records})
    finally:
        conn.close()
    _audit(_tok(authorization), "definitions.delete_module", "ui_definition", "custom_module/%s/company" % key,
           "刪自訂模組 %s（%d 個版本、%d 筆單據）" % (key, r["versions"], r["records"]), r)
    return dict(r, ok=True)


@router.get("/api/definitions/{kind}/{key}")
def get_definition(kind: str, key: str, scope: str = Query("company"), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _group_gate(kind, key)
    conn = get_db()
    try:
        return {"draft": D.get(conn, kind, key, scope, 0), "latest": D.get(conn, kind, key, scope),
                "versions": D.versions(conn, kind, key, scope)}
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()


@router.get("/api/definitions/{kind}/{key}/default")
def get_definition_default(kind: str, key: str, authorization: str = Header(None)):
    """程式出貨預設（v0；不看資料庫）。沒有預設 ⇒ `{"body": null}`。D14／D15：複製出貨範本到草稿、與出貨範本逐項比較。"""
    _require_user(authorization, require_superadmin=True)
    _group_gate(kind, key)
    if kind not in D.kinds():
        raise HTTPException(400, "未知的定義種類")
    return {"body": D.default_for(kind, key)}


@router.put("/api/definitions/{kind}/{key}/draft")
def save_definition_draft(kind: str, key: str, scope: str = Query("company"), payload: dict = Body(...),
                          authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    _managed_guard(kind, authorization, key, "存草稿")
    _custom_module_scope_guard(kind, scope)
    base_etag = payload.get("base_etag")                                # K-2：缺 ⇒ 舊前端，照舊後寫者勝（稽核標 unguarded，盤點還有誰沒帶）
    force = payload.get("force") is True
    conn = get_db()
    try:
        d = D.save_draft(conn, kind, key, scope, payload.get("body"), u["username"], base_etag=base_etag, force=force)
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()
    target = "%s/%s/%s" % (kind, key, scope)
    if d.get("overridden"):
        _audit(_tok(authorization), "definitions.save_draft_override", "ui_definition", target,
               "用我的覆蓋 %s %s（%s）草稿（原草稿 %s 於 %s）" % (kind, key, scope, d["overridden"]["created_by"], d["overridden"]["created_at"]),
               {"overridden": d["overridden"]})
    else:
        extra = {"unguarded": True} if base_etag is None else {}
        _ad = payload.get("adopted")                                     # D14／D15：採用出貨範本的項目（路徑；寫稽核，最多 200 項）
        if isinstance(_ad, list) and _ad:
            extra["adopted_from_default"] = [str(x)[:200] for x in _ad[:200]]
        _audit(_tok(authorization), "definitions.save_draft", "ui_definition", target,
               "存 %s %s（%s）草稿%s" % (kind, key, scope, "（採用出貨範本 %d 項）" % len(extra["adopted_from_default"]) if "adopted_from_default" in extra else ""), extra)
    return {"draft": d, "etag": d.get("etag", ""), "problems": D.validate(kind, key, d["body"])}


@router.post("/api/definitions/{kind}/{key}/validate")
def validate_definition(kind: str, key: str, payload: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _group_gate(kind, key)
    if kind not in D.kinds():
        raise HTTPException(400, "未知的定義種類")
    return {"problems": D.validate(kind, key, payload.get("body"))}


# ── T60 S1：伺服端強制「發布要先看過同一份草稿的預覽」（D4：沒有後門）；旗標 builder_governance.enabled（與 def_governance.enabled 同一個設定） ──
#: 已經會在發布時帶 `preview_hash` 的編輯器所對應的 kind（旗標開啟時才強制）。
#: 排版器（layout）與選單建構器（發布走 layout）尚未送雜湊 ⇒ 還不在名單；它們接上之後再加進來（見 T60 計畫 S1）。
_PREVIEW_ENFORCED_KINDS = ("expense_type", "remit_kinds", "custom_module", "export_template")


def _preview_gate(conn, kind, key, scope, user, preview_hash):
    """發布前的把關。⇒ None（放行）或 `(code, 白話訊息)`。
    旗標關、kind 不在名單、目前沒有草稿（後面的發布自己會說『沒有草稿』）⇒ 放行（與今天逐字相同）。
    旗標開且在名單：必須帶 `preview_hash`＝目前草稿戳，而且這位使用者真的『看過』（稽核裡有他對這個戳的預覽紀錄）；沒有例外。"""
    if kind not in _PREVIEW_ENFORCED_KINDS or not _governance_enabled(conn):
        return None
    draft = D.get(conn, kind, key, scope, 0)
    if draft is None:
        return None
    cur = draft.get("etag", "")
    if not preview_hash:
        return ("preview_required", "發布前必須先看過影響預覽")
    if preview_hash != cur:
        return ("preview_stale", "草稿在你看過預覽之後又被改了，請重新預覽")
    seen = conn.execute("SELECT 1 FROM audit_log WHERE action='definitions.previewed' AND target_id=? AND username=? "
                        "AND detail LIKE ? LIMIT 1", ("%s/%s/%s" % (kind, key, scope), user, '%"previewHash": "' + cur + '"%')).fetchone()
    if not seen:
        return ("preview_required", "發布前必須先看過影響預覽")
    return None



def _governance_enabled(conn=None) -> bool:
    try:
        from helpers import settings_registry as R
        return int(R.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                                  # noqa: BLE001  讀不到一律當關
        return False


@router.post("/api/definitions/{kind}/{key}/publish")
def publish_definition(kind: str, key: str, scope: str = Query("company"), payload: dict = Body(default={}),
                       authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    _managed_guard(kind, authorization, key, "發布")
    _custom_module_scope_guard(kind, scope)
    base_etag = (payload or {}).get("base_etag")                        # K-2：選填；缺＝照舊
    if base_etag is not None and not isinstance(base_etag, str):
        raise HTTPException(400, "base_etag 必須是字串")
    conn = get_db()
    try:
        _pv = (payload or {}).get("preview_hash")                       # T60 S1：旗標開啟時，名單內的 kind 必須帶看過的預覽雜湊（關＝放行）
        _gate = _preview_gate(conn, kind, key, scope, u["username"], _pv if isinstance(_pv, str) else None)
        if _gate:
            return JSONResponse({"detail": _gate[1], "code": _gate[0]}, status_code=409)
        from routers import def_pipeline as _pl                          # T60 S2：旗標開、名單內的 kind ⇒ 放寬先待核准、收緊立即（其餘 ⇒ None，照舊）
        _piped = _pl.handle_publish(conn, kind, key, scope, u, (payload or {}).get("note", ""), base_etag, authorization)
        if _piped is not None:
            return _piped
        if kind == "custom_module" and scope == "company":
            # 方案 B：掛載點頁籤數上限（要連線，所以不在 validate_module 裡）——發布／送審之前擋下
            from helpers import custom_modules as _cm
            _dr = D.get(conn, kind, key, scope, 0)
            if base_etag is not None and _dr is not None and _dr.get("etag") != base_etag:       # K-2：送審／發布的是「我看到的那份草稿」（先擋＝快速失敗；真正的比對在 D.publish／D.submit_draft 的寫鎖內）
                return _err(D.DraftConflict("這份草稿在你載入之後被別人改過，未發布",
                                            {"etag": _dr.get("etag", ""), "created_by": _dr.get("created_by", ""), "created_at": _dr.get("created_at", "")}))
            _cap = _cm.mount_cap_problems(conn, key, (_dr or {}).get("body") or {}) if _dr else []
            if _cap:
                return JSONResponse({"detail": "這個掛載點的頁籤數已達上限", "problems": _cap}, status_code=422)
            # S4：審核開啟且有簽核層 ⇒ 送審（回 pending）；否則與過去一樣直接發布
            from helpers import custom_def_review as _defr
            try:
                r = _defr.submit(conn, key, u, (payload or {}).get("note", ""), base_etag=base_etag)
            except _defr.ReviewError as e:
                return JSONResponse({"detail": str(e), "problems": e.problems}, status_code=e.status)
            if r["pending"]:
                _audit(_tok(authorization), "definitions.submit", "ui_definition", "%s/%s/%s" % (kind, key, scope),
                       "送審 %s 第 %d 版" % (key, r["version"]), {"note": (payload or {}).get("note", "")})
                return dict(r["definition"], pending=True)
            d = r["definition"]
            if r.get("unreviewed"):                      # 直接發布而沒有第二人審核 ⇒ 稽核明記（主持裁示 2026-09-30）
                _audit(_tok(authorization), "definitions.publish_unreviewed", "ui_definition", "%s/%s/%s" % (kind, key, scope),
                       "發布 %s 第 %d 版：未經第二人審核（%s）" % (key, d["version"], r.get("reason", "")), {"note": d.get("note", "")})
        else:
            d = D.publish(conn, kind, key, scope, (payload or {}).get("note", ""), u["username"], base_etag=base_etag)
            _audit_unreviewed(authorization, kind, key, scope, d["version"], _UNREVIEWED_KIND_REASON)
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
    _group_gate(kind, key)
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
    _group_gate(kind, key)
    conn = get_db()
    try:
        def pick(x):
            if x == "draft":
                r = D.get(conn, kind, key, scope, 0)
            elif x == "latest":
                r = D.get(conn, kind, key, scope)
            elif x == "default":
                return D.default_for(kind, key) or {}                      # 程式出貨預設（v0），不是目前生效的公司版
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
    _managed_guard(kind, authorization, key, "還原")
    _custom_module_scope_guard(kind, scope)
    conn = get_db()
    unreviewed_reason = _UNREVIEWED_KIND_REASON
    try:
        from routers import def_pipeline as _pl                          # T60 S2：還原到較寬鬆的版本 ⇒ 待核准（其餘 ⇒ None，照舊）
        _piped = _pl.handle_restore(conn, kind, key, scope, version, u, (payload or {}).get("note", ""), authorization)
        if _piped is not None:
            return _piped
        if kind == "custom_module" and scope == "company":
            from helpers import custom_def_review as _defr
            _st = _defr.review_state(conn, u["username"])
            unreviewed_reason = _st["reason"]
            if _st["active"]:          # S4：審核啟用時，還原＝把舊版放回草稿（再走送審），不直接發布
                try:
                    r = _defr.restore_to_draft(conn, key, version, u)
                except _defr.ReviewError as e:
                    return JSONResponse({"detail": str(e), "problems": e.problems}, status_code=e.status)
                _audit(_tok(authorization), "definitions.restore_to_draft", "ui_definition", "%s/%s/%s" % (kind, key, scope),
                       "把 %s 第 %d 版放回草稿" % (key, version), {})
                return r
        d = D.restore(conn, kind, key, scope, version, (payload or {}).get("note", ""), u["username"])
        _audit_unreviewed(authorization, kind, key, scope, d["version"], unreviewed_reason, verb="還原")
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
    _group_gate(kind, key)
    conn = get_db()
    try:
        body, source = D.resolve(conn, kind, key, role)
    except D.DefinitionError as e:
        return _err(e)
    finally:
        conn.close()
    return {"body": body, "source": source}


@router.get("/api/layout/{module_key}")
def effective_layout(module_key: str, role: str = Query(None), authorization: str = Header(None)):
    """P9 執行時套用（CUSTOMIZATION-SPEC §3.10）：目前使用者角色的版面＝`resolve(layout, module:<key>, 角色)`
    （角色 ＞ 公司 ＞ 程式預設），連同這個模組的可自訂點（`catalog.layout_points`，前端據此算出畫面）。

    - 任何登入者可讀**自己角色**的版面；`?role=` 只給超級管理員（排版器的「以某角色預覽」）。
    - 已發布的操作逐一再過 `check_layout`：之後模組拿掉了某個點 ⇒ 那一筆**不套用**並列在 `dropped`
      （讀不懂的拒絕那一筆，不讓整頁壞掉，也不悄悄略過）。
    - 讀定義失敗 ⇒ 程式預設＋`error`（覆寫層出錯不可以讓頁面打不開）。"""
    import logging
    from core import catalog, registry
    u = _require_user(authorization)
    if role is not None and u["role"] != "superadmin":
        raise HTTPException(403, "只有超級管理員可以預覽其他角色的版面")
    if not re.match(r"^[a-z][a-z0-9_]{0,39}$", module_key or "") or not registry.is_loaded(module_key):
        raise HTTPException(404, "模組未載入")
    who = role if role is not None else u["role"]
    conn = get_db()
    try:
        eff = catalog.effective_layout_ops(conn, module_key, who)   # resolve＋check_layout 唯一一份（C4：選單共用）
    finally:
        conn.close()
    ops, dropped = eff["ops"], eff["dropped"]
    if u["role"] != "superadmin":
        # T60 S0（hichan-04 稽核）：側欄操作（含改名文字與使用者看不到的目標 id）只有 /api/platform/menu 在用（那邊已依權限過濾並遮蔽）；
        # 頁面引擎不需要它們 ⇒ 對非最高管理者拿掉，免得從這裡讀到看不到的項目。
        def _is_sidebar(o):
            t = (o or {}).get("target") if isinstance(o, dict) else None
            return isinstance(t, str) and t.endswith("/sidebar")
        ops = [o for o in ops if not _is_sidebar(o)]
        dropped = [d for d in dropped if not _is_sidebar((d or {}).get("op") if isinstance(d, dict) else None)]
    return {"module": module_key, "role": who, "source": eff["source"], "ops": ops, "dropped": dropped,
            "error": eff["error"], "points": catalog.layout_points(module_key)}


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
