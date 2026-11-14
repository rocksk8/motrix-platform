# -*- coding: utf-8 -*-
"""GET /api/bootstrap：登入後每頁都要打的那一串「啟動請求」合成一支（2026-11-13，「外網載入效能」第二階段）。

## 為什麼
外網每個請求約 1 s。登入後每一頁載入都會各自打 auth/me、platform/menu、modules/availability、bonus-module-status、build-info、
approval-queue/count、notifications/mine、reads/module-counts、system/branding、online-users、totp/status……（首頁暖載入 22 支 API）。
合成一支 ⇒ 少 10 支請求，且瀑布少一層（頁面不必等 auth-guard 的 auth/me 回來才發別的）。

## 鐵則：**不可以回傳比原端點更多的資料**
每個區段都是**直接呼叫原端點的處理函式**（同一份程式、同一個權限檢查、同一個 `authorization`），所以區段內容與原端點逐欄相同，
權限判斷也不是另寫一份。差別只在「要不要放進來」，而放與不放都只會**變少**：
- 角色限定：`onlineUsers` 只有最高管理者；`totp`、`moduleCounts` 只有最高管理者／管理員（前端本來就只對這些角色發）。
- 本公司資料未設定（COMPANY-SETUP-GATE）：原端點除白名單外一律 428 ⇒ 這裡只放白名單內的區段（`me`、`menu`、`branding`、`totp`），
  其餘區段不給、`errors` 記 428。**否則 bootstrap 會變成繞過閘門的後門。**
- 原端點丟 HTTPException（401／403／404…）或閘門例外 ⇒ 該區段不給、`errors[區段]` 記狀態碼；不整包失敗。
- 授權閘門（402）、必須先改密碼（403）：本端點不在豁免／白名單 ⇒ 與其他 `/api` 一樣被擋；前端收到非 200 就退回各自打原端點（舊行為）。

## 頁面專屬區段（T86 #10，`?page=case`）
案件管理頁首屏本來自己再打 8 支「登入即可讀」的小請求（onepipe 旗標、版面與規則設定群組、利潤門檻、可選使用者、公司公開資料、清單排序偏好、
兩支承攬商下拉），清單載入共 19 支 API。`GET /api/bootstrap?page=case` 在全站區段之外再多放這 8 段（`PAGE_SECTIONS["case"]`）：
規矩與上面完全相同——直接呼叫原端點的處理函式（帶固定的路徑參數／查詢值）、同一份權限檢查、失敗只記 `errors`、閘門時一律 428；
沒帶 `page` 或不認得的值＝與今天逐位元相同（不報錯、不多給）。
另有一個「衍生區段」`financeView`（`DERIVED_SECTIONS`，沒有原端點）：只回呼叫者自己的一個布林 `{"financialView": …}`＝`helpers.auth.can_see_financial`
的答案，讓案件頁依後端同一條規則（含財務旗標 `finance_via_effective` 開啟時的職責角色／個人扣項）決定要不要發 `finance-summary`；不含任何資料列。前端只在案件管理頁才登記這些路徑（static/auth-guard.js），其他頁照舊直接 fetch。

原端點全部保留（相容；也是前端的退路）。守門：tests/test_bootstrap_bundle_2026_11_13.py 逐區段、逐角色比對 bootstrap 與原端點的回應。
"""
import contextvars
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Header, HTTPException, Response

from helpers import _require_user

logger = logging.getLogger(__name__)
router = APIRouter()

#: 區段 → 在「本公司資料未設定」時是否仍可給（＝原端點在 main._COMPANY_SETUP_ALLOWED／_PUBLIC_API_PATHS 內）。
#: 守門：test_bootstrap_bundle::test_setup_gate_allowed_sections_match_main
SETUP_GATE_OK = frozenset({"me", "menu", "branding", "totp"})
#: 案件頁讀「版面/自訂欄位/規則…」那一支的群組清單（＝ case-management.html 傳給 MotrixPublicFlags.read 的順序；守門：test_bootstrap_page_case 比對前端字串）
CASE_BUILDER_GROUPS = ("builder_layout", "builder_custom_fields", "builder_rules", "builder_slots", "builder_status_display", "builder_stage_templates", "ui_format")
#: 「沒有原端點」的衍生區段（只回呼叫者自己的一個布林）：路徑欄放這個標記；守門表（原端點逐欄比對、前端路徑表）一律略過它。
DERIVED_PATH = "(derived)"
DERIVED_SECTIONS = frozenset({"financeView"})
#: 區段 → 原端點路徑（守門與文件用）
ORIGINAL_PATH = {
    "me": "/api/auth/me",
    "menu": "/api/platform/menu",
    "branding": "/api/system/branding",
    "buildInfo": "/api/build-info",
    "bonusModuleStatus": "/api/system/bonus-module-status",
    "moduleAvailability": "/api/system/modules/availability",
    "approvalCount": "/api/approval-queue/count",
    "notifications": "/api/notifications/mine",
    "moduleCounts": "/api/reads/module-counts",
    "onlineUsers": "/api/online-users",
    "totp": "/api/auth/totp/status",
}
#: 頁面專屬區段（只在 `?page=<鍵>` 時才放）：頁面鍵 → {區段: 原端點路徑（含固定的查詢值）}。守門：test_bootstrap_page_case_2026_11_14.py
PAGE_SECTIONS = {
    "case": {
        "onepipeFlags": "/api/settings-center/public?groups=onepipe",
        "builderGroups": "/api/settings-center/public?groups=" + ",".join(CASE_BUILDER_GROUPS),
        "profitWarning": "/api/profit-warning/config",
        "usersSelectable": "/api/users/selectable",
        "companyProfilePublic": "/api/settings/company-profile/public",
        "listPrefCase": "/api/list-prefs/case_list",
        "vendorsSelectable": "/api/vendor-contractors/selectable",
        "contractorsSelectable": "/api/contractors/selectable",
        "financeView": DERIVED_PATH,
    },
}
_SA_ONLY = frozenset({"onlineUsers"})
_ADMIN_UP = frozenset({"totp", "moduleCounts"})


#: 各區段並行跑（B1）：區段彼此獨立、都只讀；序列跑 11 段實測 ≈ 250～280 ms，並行 ≈ 最慢那一段。
#: 專用執行緒池（不佔 FastAPI 的請求執行緒池，免得巢狀等待互卡）；每個區段在 `copy_context()` 的複本裡跑，
#: ⇒ demo 模式旗標（get_db 導向 demo 庫）與診斷用的請求脈絡都照樣帶進去。
_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="bootstrap")

#: `build_info`（B1）：每次請求都 `git rev-parse` 一次（開發機）／讀檔，實測 90～240 ms，是 bootstrap 最慢的一段。
#: 內容只在重新啟動（commit）或套用更新（disk_commit／stale）時才會變 ⇒ 快取 `_BUILD_INFO_TTL_S` 秒。
#: ⚠️ **不能「行程內永遠快取」**：`stale`＝磁碟上的版本比執行中的新，正是套用更新**不重啟**時才會變的欄位。
#: 代價：套用更新後最多晚這麼久才在畫面上看到「要重新啟動」。原端點 `/api/build-info` 不快取、照舊即時。
_BUILD_INFO_TTL_S = 60.0
_bi_lock = threading.Lock()
_bi_cache = {"at": 0.0, "value": None}


def _build_info_cached(authorization=None):
    _require_user(authorization)
    now = time.monotonic()
    with _bi_lock:
        if _bi_cache["value"] is not None and now - _bi_cache["at"] < _BUILD_INFO_TTL_S:
            return _bi_cache["value"]
    from helpers.build_info import build_info
    v = build_info()
    with _bi_lock:
        _bi_cache["at"], _bi_cache["value"] = now, v
    return v


def _handlers():
    """區段 → 原端點的處理函式（呼叫時才 import：避免與各 router 循環匯入）。"""
    from routers import approval_queue, auth, item_reads, platform_menu, system
    return {
        "me": auth.auth_me,
        "menu": platform_menu.platform_menu,
        "branding": auth.system_branding,
        "buildInfo": _build_info_cached,
        "bonusModuleStatus": system.get_bonus_module_status,
        "moduleAvailability": system.module_availability,
        "approvalCount": approval_queue.get_approval_queue_count,
        "notifications": system.get_my_notifications,
        "moduleCounts": item_reads.module_counts,
        "onlineUsers": system.list_online_users,
        "totp": auth.totp_status,
    }


def _finance_view(authorization=None):
    """`{"financialView": bool}`＝**這個人**看不看得到案件財務金額：直接呼叫 `helpers.auth.can_see_financial`（後端各財務端點用的同一支，
    旗標 `finance_via_effective` 的 off／shadow／on 全部照它）。前端據此決定要不要發 `finance-summary`，免得旗標開啟時前端只看角色而與後端不一致。
    只回呼叫者自己的權限，沒有任何資料列。"""
    from helpers.auth import can_see_financial
    return {"financialView": bool(can_see_financial(_require_user(authorization)))}


def _page_handlers(page):
    """頁面專屬區段 → 處理函式（路徑參數／固定查詢值用 partial 先綁，呼叫時仍只帶 authorization）。"""
    from functools import partial
    from modules.case.api import project_margin
    from modules.subcontract.api import contractors, vendor_contractors
    from routers import auth, list_prefs, settings_center, system
    if page != "case":
        return {}
    return {
        "onepipeFlags": partial(settings_center.public_values, "onepipe"),
        "builderGroups": partial(settings_center.public_values, ",".join(CASE_BUILDER_GROUPS)),
        "profitWarning": project_margin.get_profit_warning_config,
        "usersSelectable": auth.users_selectable,
        "companyProfilePublic": system.get_company_profile_public,
        "listPrefCase": partial(list_prefs.get_list_pref, "case_list"),
        "vendorsSelectable": vendor_contractors.list_vendors_selectable,
        "contractorsSelectable": contractors.list_contractors_selectable,
        "financeView": _finance_view,
    }


def sections_for(role, setup_blocked, page=None):
    """這個角色在這個閘門狀態下會放進 bootstrap 的區段（有序）。純函式，守門直接用。`page` 不認得 ⇒ 只有全站區段。"""
    out = []
    for name in ORIGINAL_PATH:
        if name in _SA_ONLY and role != "superadmin":
            continue
        if name in _ADMIN_UP and role not in ("superadmin", "admin"):
            continue
        if setup_blocked and name not in SETUP_GATE_OK:
            continue
        out.append(name)
    if not setup_blocked:                                    # 頁面專屬區段都不在閘門白名單內：閘門時一個都不給
        out.extend(PAGE_SECTIONS.get(page, {}))
    return out


def _setup_blocked():
    from db import get_db
    from helpers import company_setup as _cs
    conn = get_db()
    try:
        kind, _st = _cs.gate(conn)
        conn.commit()
    finally:
        conn.close()
    return kind == _cs.GATE_REQUIRED


def _run_section(name, fn, authorization, path=None):
    """在複製的 context 裡跑一個區段（由執行緒池呼叫）。回 `(ok, 值或狀態碼)`。"""
    from db import set_request_ctx
    from helpers import company_setup as _cs
    # B3：診斷用的「是哪支端點」要記原端點的路徑，不是 /api/bootstrap（例如區段內的 403 稽核）
    set_request_ctx("GET", ("/api/bootstrap" if path == DERIVED_PATH else (path or ORIGINAL_PATH[name])).split("?")[0])
    try:
        return True, fn(authorization)
    except HTTPException as e:
        return False, e.status_code
    except _cs.CompanySetupRequired:
        return False, 428
    except Exception:                                       # noqa: BLE001  一個區段壞了不拖垮其他區段；前端對缺的區段退回原端點
        logger.exception("bootstrap section %s failed", name)
        return False, 500


@router.get("/api/bootstrap")
def bootstrap(response: Response, page: str = "", authorization: str = Header(None)):
    """登入後的啟動資料（見模組說明）。回 `{"v": 1, "<區段>": <原端點的回應>, …, "errors": {"<區段>": <狀態碼>}}`。"""
    response.headers["Cache-Control"] = "no-store"          # B4：每人不同、最大的 JSON、每頁都打
    user = _require_user(authorization)
    try:
        blocked = _setup_blocked()
    except Exception:                                       # noqa: BLE001  閘門判定失敗 ⇒ 當作被擋（只給白名單區段，保守）
        logger.exception("bootstrap: company setup gate failed")
        blocked = True
    page = page if page in PAGE_SECTIONS else None           # 不認得的頁面鍵＝沒帶（不報錯、不多給）
    handlers = {**_handlers(), **_page_handlers(page)}
    names = sections_for(user.get("role"), blocked, page)
    paths = {**ORIGINAL_PATH, **PAGE_SECTIONS.get(page, {})}
    futs = [(n, _POOL.submit(contextvars.copy_context().run, _run_section, n, handlers[n], authorization, paths[n])) for n in names]
    out = {"v": 1}
    errors = {}
    for name, fut in futs:                                  # 依 sections_for 的順序收（回應的鍵序固定）
        ok, val = fut.result()
        if ok:
            out[name] = val
        else:
            errors[name] = val
    if blocked:                                             # 閘門擋掉的區段：明講是 428（前端不必退回打原端點——原端點也是 428）
        for name in set(sections_for(user.get("role"), False, page)) - set(sections_for(user.get("role"), True, page)):
            errors[name] = 428
    out["errors"] = errors
    return out
