"""授權狀態端點（2026-09-21，細線 1 第 2 步）。

`GET /api/license/status` —— 這台機器裝了誰的授權、到什麼時候、開了哪些模組。

**本輪只要求登入即可讀**（收權限是第 3 步）。

模組叫 `licensing` 不是 `license`：`license` 是 Python 內建名稱，
`from routers import ... license` 會在 `main.py` 的命名空間裡把它蓋掉。
**端點路徑仍是 `/api/license/status`**——對外介面用一般人看得懂的字。
"""
from fastapi import APIRouter, Header

from helpers import _require_user
from helpers.licensing import verify_license

router = APIRouter()


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
    return verify_license()
