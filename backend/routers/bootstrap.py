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

原端點全部保留（相容；也是前端的退路）。守門：tests/test_bootstrap_bundle_2026_11_13.py 逐區段、逐角色比對 bootstrap 與原端點的回應。
"""
import logging

from fastapi import APIRouter, Header, HTTPException

from helpers import _require_user

logger = logging.getLogger(__name__)
router = APIRouter()

#: 區段 → 在「本公司資料未設定」時是否仍可給（＝原端點在 main._COMPANY_SETUP_ALLOWED／_PUBLIC_API_PATHS 內）。
#: 守門：test_bootstrap_bundle::test_setup_gate_allowed_sections_match_main
SETUP_GATE_OK = frozenset({"me", "menu", "branding", "totp"})
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
_SA_ONLY = frozenset({"onlineUsers"})
_ADMIN_UP = frozenset({"totp", "moduleCounts"})


def _handlers():
    """區段 → 原端點的處理函式（呼叫時才 import：避免與各 router 循環匯入）。"""
    from routers import approval_queue, auth, item_reads, platform_menu, system
    return {
        "me": auth.auth_me,
        "menu": platform_menu.platform_menu,
        "branding": auth.system_branding,
        "buildInfo": auth.build_info_endpoint,
        "bonusModuleStatus": system.get_bonus_module_status,
        "moduleAvailability": system.module_availability,
        "approvalCount": approval_queue.get_approval_queue_count,
        "notifications": system.get_my_notifications,
        "moduleCounts": item_reads.module_counts,
        "onlineUsers": system.list_online_users,
        "totp": auth.totp_status,
    }


def sections_for(role, setup_blocked):
    """這個角色在這個閘門狀態下會放進 bootstrap 的區段（有序）。純函式，守門直接用。"""
    out = []
    for name in ORIGINAL_PATH:
        if name in _SA_ONLY and role != "superadmin":
            continue
        if name in _ADMIN_UP and role not in ("superadmin", "admin"):
            continue
        if setup_blocked and name not in SETUP_GATE_OK:
            continue
        out.append(name)
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


@router.get("/api/bootstrap")
def bootstrap(authorization: str = Header(None)):
    """登入後的啟動資料（見模組說明）。回 `{"v": 1, "<區段>": <原端點的回應>, …, "errors": {"<區段>": <狀態碼>}}`。"""
    user = _require_user(authorization)
    try:
        blocked = _setup_blocked()
    except Exception:                                       # noqa: BLE001  閘門判定失敗 ⇒ 當作被擋（只給白名單區段，保守）
        logger.exception("bootstrap: company setup gate failed")
        blocked = True
    from helpers import company_setup as _cs
    handlers = _handlers()
    out = {"v": 1}
    errors = {}
    for name in sections_for(user.get("role"), blocked):
        try:
            out[name] = handlers[name](authorization)
        except HTTPException as e:
            errors[name] = e.status_code
        except _cs.CompanySetupRequired:
            errors[name] = 428
        except Exception:                                   # noqa: BLE001  一個區段壞了不拖垮其他區段；前端對缺的區段退回原端點
            logger.exception("bootstrap section %s failed", name)
            errors[name] = 500
    if blocked:                                             # 閘門擋掉的區段：明講是 428（前端不必退回打原端點——原端點也是 428）
        for name in set(sections_for(user.get("role"), False)) - set(sections_for(user.get("role"), True)):
            errors[name] = 428
    out["errors"] = errors
    return out
