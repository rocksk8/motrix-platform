"""授權狀態端點（2026-09-21，細線 1 第 2 步）。

`GET /api/license/status` —— 這台機器裝了誰的授權、到什麼時候、開了哪些模組。

**本輪只要求登入即可讀**（收權限是第 3 步）。

模組叫 `licensing` 不是 `license`：`license` 是 Python 內建名稱，
`from routers import ... license` 會在 `main.py` 的命名空間裡把它蓋掉。
**端點路徑仍是 `/api/license/status`**——對外介面用一般人看得懂的字。
"""
import hashlib
import json
import logging
import time

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from core import registry as _registry
from db import get_db, is_demo_mode

from helpers import _audit, _require_user, _tok
from helpers import license_manager as _mgr
from helpers import licensing as _lic
from helpers.licensing import verify_license

logger = logging.getLogger(__name__)

router = APIRouter()

#: 指紋讀不到時，多久之內不再重試（`machine_fingerprint()` 失敗不快取，每次都會跑 PowerShell／CIM 查詢；
#: 狀態端點被前端反覆呼叫時不可以每次都打硬體查詢——K 審 S6）。
_FP_RETRY_SECONDS = 300
_FP_FAIL_UNTIL = 0.0


def _machine_or_none():
    global _FP_FAIL_UNTIL
    if time.monotonic() < _FP_FAIL_UNTIL:
        return None
    try:
        return _lic.machine_fingerprint()
    except Exception:  # noqa: BLE001 — 狀態端點必須永遠讀得到
        _FP_FAIL_UNTIL = time.monotonic() + _FP_RETRY_SECONDS
        return None


@router.get("/api/license/status")
def license_status(authorization: str = Header(None)):
    """回 LicenseStatus 七個欄位。**沒裝金鑰不是錯誤，是客戶第一次開機的樣子。**

    所以這裡永遠回 200，沒金鑰時回 `{valid: false, reason: "missing", ...}`：
    - 402 是第 3 步用來擋業務 API 的，不是這一支的事
    - status 端點本身必須永遠讀得到，否則現場沒授權時連原因都查不出來

    `verify_license()` 不帶參數 → 它自己去讀 `helpers.licensing.LICENSE_PATH`，
    而且**每次呼叫都重讀**（第 6 步的到期提醒要能每天重新判定 `days_left`）。
    """
    _require_user(authorization)
    status = verify_license()
    # 在 LicenseStatus 八個欄位之外另外帶（2026-11-11，T80；前端「授權無法使用」頁與橫幅用，既有欄位不動）：
    #   machine    本機指紋——被擋（機器不符）時簽發方要拿它重簽；不是祕密。讀不到 ⇒ None
    #   emergency  緊急放行通行證的狀態：沒有通行證檔 ⇒ None；有 ⇒ {present, active, why, until, note, pass_id, env}
    #   gate       授權閘門是否開著；blocked ＝ 這個狀態會不會擋業務 API（不含通行證；永久授權過期＝不擋）
    #   modules_unlicensed  這次開機時因為授權沒過而「沒載入」的模組 key。載入器只在啟動時決定一次：
    #              通行證／新金鑰放上去之後，業務 API 立刻恢復，但這些模組要**重啟服務**才會載入（K 審 M1）
    unlicensed = [m["key"] for m in _registry.module_states() if m.get("state") == _registry.STATE_UNLICENSED]
    em = _lic.emergency_status(status)
    if em and em.get("active") and not _lic.LICENSE_GATE_ENABLED:
        # 閘門關著＝沒有東西在擋、通行證不會被讀：不可以回 active（K 審 N2；狀態欄位語意）
        em = dict(em, active=False, why="gate_off")
    return dict(status, machine=_machine_or_none(), emergency=em,
                gate=bool(_lic.LICENSE_GATE_ENABLED), blocked=_lic.license_blocks_request(status),
                modules_unlicensed=unlicensed)


# ── 授權頁：檢視與匯入（T83）────────────────────────────────────────────────────
#
# 兩條端點都在 `licensing.LICENSE_EXEMPT_PATHS`（授權失效時唯一能救回系統的動作就是匯入新授權）。
# 豁免只跳過授權閘門；這裡自己要求：已登入 ＋ 最高管理者 ＋ 非示範帳號。
# 驗章／機器綁定／到期一律在 `helpers.licensing`（`license_manager.run_import` 只呼叫它）。

# JSON 外殼＋逸出字元的餘裕；授權檔本身的上限是 `license_manager.MAX_UPLOAD_BYTES`
_MAX_BODY_BYTES = _mgr.MAX_UPLOAD_BYTES * 2 + 1024


def _superadmin_not_demo(authorization):
    """已登入的最高管理者、且不是示範帳號。示範帳號（role 也是 superadmin）操作的是隔離的示範庫，
    但**授權檔是整台機器共用的**——不擋的話，示範帳號就能換掉正式機的授權。"""
    if is_demo_mode() or (authorization or "").startswith("Bearer DEMO_"):
        raise HTTPException(403, _mgr.REJECT_MESSAGES["demo"])
    user = _require_user(authorization)
    if user.get("role") != "superadmin":
        raise HTTPException(403, "只有最高管理者可以查看或更換授權。")
    return user


def _fail(result, **extra):
    body = {k: v for k, v in result.items() if k not in ("http", "file_id")}
    body["detail"] = result.get("message", "")
    body.update(extra)
    return JSONResponse(status_code=result.get("http", 400), content=body)


@router.get("/api/license/overview")
def license_overview(authorization: str = Header(None)):
    """授權頁要的白話資料：客戶、到期日、可用功能、綁定的電腦、提醒、備份數、最近的匯入紀錄。只有最高管理者。"""
    _superadmin_not_demo(authorization)
    data = _mgr.describe_current(_machine_or_none)
    conn = get_db()
    try:
        data["recent"] = _mgr.recent_activity(conn)
    except Exception:  # noqa: BLE001 — 稽核表讀不到不該讓授權頁整個打不開
        data["recent"] = []
    finally:
        conn.close()
    return data


async def _read_json_body_capped(request: Request):
    """讀請求本文，**讀到上限就停**（不先整包讀進記憶體）。回 `(dict 或 None, 是否過大)`。"""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
        return None, True
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_BODY_BYTES:
            return None, True
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks) or b"{}")
    except ValueError:
        return None, False
    return (body if isinstance(body, dict) else None), False


def _audit_import(token, result, *, apply, file_id):
    """匯入紀錄（稽核表）：成功＝`license.import`；失敗＝`license.import_rejected`（含預覽被拒）。
    預覽成功、要求確認（needs_confirm）不寫（沒有任何狀態變動，也不是失敗）。**不寫授權內容，只寫檔案編號與驗證後的客戶／到期日。**"""
    lic = result.get("license") or {}
    # 稽核表寫入失敗時（`_audit` 依全站慣例吞例外）至少還有伺服器 log 留痕；log 不含授權內容。
    if result.get("applied"):
        logger.warning("授權匯入成功：客戶 %s、到期日 %s、檔案編號 %s、備份 %s", lic.get("customer"), lic.get("expires"), file_id, result.get("backup"))
    elif result.get("reason") not in ("preview", "needs_confirm"):
        logger.warning("授權匯入被拒（%s）：apply=%s、檔案編號 %s", result.get("reason"), apply, file_id)
    base = {"apply": bool(apply), "file_id": file_id,
            "customer": lic.get("customer"), "expires": lic.get("expires")}
    if result.get("applied"):
        _audit(token, "license.import", "settings", "license", lic.get("customer") or "", dict(
            base, kind=lic.get("kind"), backup=result.get("backup"), restart_needed=result.get("restart_needed"),
            warnings=len(result.get("warnings") or [])))
    elif result.get("reason") not in ("preview", "needs_confirm"):
        _audit(token, "license.import_rejected", "settings", "license", "", dict(base, reason=result.get("reason")))


@router.post("/api/license/import")
async def license_import(request: Request, authorization: str = Header(None)):
    """預覽或匯入授權檔。本文 JSON：`{"content": "<授權檔內容>", "apply": false|true, "confirm": false|true}`。

    `apply` 省略／false ⇒ 只驗證並回預覽（不寫任何東西）；`apply: true` ⇒ 驗證通過才換（備份舊檔、原子寫入、換後複驗）；
    新授權與目前的有差異（`warnings`）時，要帶 `confirm: true` 才會換（否則 409）。
    失敗一律回白話 `message`（也放在 `detail`），`reason` 是給程式判斷的代碼。只有最高管理者；有大小上限、頻率限制、稽核紀錄。"""
    await run_in_threadpool(_superadmin_not_demo, authorization)
    token = _tok(authorization)
    allowed, retry_after, first = _mgr.rate_allow()
    if not allowed:
        res = {"ok": False, "applied": False, "reason": "rate_limited", "http": 429,
               "message": _mgr.REJECT_MESSAGES["rate_limited"]}
        if first:        # 這個視窗只寫第一筆稽核：被灌的時候不要連稽核表一起灌爆
            await run_in_threadpool(_audit_import, token, res, apply=None, file_id=None)
        r = _fail(res, retryAfter=retry_after)
        r.headers["Retry-After"] = str(retry_after)
        return r

    body, too_big = await _read_json_body_capped(request)
    if too_big:
        res = {"ok": False, "applied": False, "reason": "too_big", "http": 413, "message": _mgr.REJECT_MESSAGES["too_big"]}
        await run_in_threadpool(_audit_import, token, res, apply=None, file_id=None)
        return _fail(res)
    if body is None or not isinstance(body.get("content"), str):
        res = {"ok": False, "applied": False, "reason": "malformed", "http": 400, "message": _mgr.REJECT_MESSAGES["malformed"]}
        await run_in_threadpool(_audit_import, token, res, apply=None, file_id=None)
        return _fail(res)

    apply, confirm = body.get("apply") is True, body.get("confirm") is True

    def _go():
        res = _mgr.run_import(body["content"], apply=apply, confirm=confirm, machine_fn=_machine_or_none)
        text, _why = _mgr.normalize_upload(body["content"])
        fid = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else None
        _audit_import(token, res, apply=apply, file_id=fid)
        return res

    res = await run_in_threadpool(_go)
    if res.get("ok"):
        return {k: v for k, v in res.items() if k != "http"}
    return _fail(res)
