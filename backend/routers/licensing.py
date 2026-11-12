"""授權狀態端點（2026-09-21，細線 1 第 2 步）。

`GET /api/license/status` —— 這台機器裝了誰的授權、到什麼時候、開了哪些模組。

**本輪只要求登入即可讀**（收權限是第 3 步）。

模組叫 `licensing` 不是 `license`：`license` 是 Python 內建名稱，
`from routers import ... license` 會在 `main.py` 的命名空間裡把它蓋掉。
**端點路徑仍是 `/api/license/status`**——對外介面用一般人看得懂的字。
"""
import time

from fastapi import APIRouter, Header

from core import registry as _registry

from helpers import _require_user
from helpers import licensing as _lic
from helpers.licensing import verify_license

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
