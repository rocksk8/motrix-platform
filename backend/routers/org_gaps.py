"""組織設定缺口檢查端點（批次 5a，2026-11-13）：只讀。

簽核設定頁頂、使用者管理頁頂與新增後、系統總覽首頁都讀這一支。只有最高管理者與管理員看得到（會列出人名與部門名）。
"""
from fastapi import APIRouter, Header, HTTPException

from helpers import _require_user
from helpers import org_gaps as OG

router = APIRouter()


@router.get("/api/org/gaps")
def get_org_gaps(authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "只有管理者可以查看組織設定檢查")
    return OG.check()
