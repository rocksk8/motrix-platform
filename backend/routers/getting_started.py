"""「開始使用」7 步清單端點（批次「開始使用清單面板」，2026-11-13）。只有最高管理者（每一步都是最高管理者的設定頁）。

GET /api/getting-started                  每步狀態（自動偵測＋人工旗標）、完成度、下一步
PUT /api/getting-started/steps/{step_id}  人工旗標 {action: skip|unskip|done|undone}（done 只限系統看不出來的步驟）
"""
from fastapi import APIRouter, Body, Header, HTTPException

from helpers import _audit, _require_user, _tok
from helpers import getting_started as GS

router = APIRouter()


@router.get("/api/getting-started")
def get_getting_started(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)       # 只限最高管理者（其他人 403）
    return GS.overview()


@router.put("/api/getting-started/steps/{step_id}")
def put_getting_started_step(step_id: str, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    action = (body or {}).get("action")
    try:
        GS.set_step(step_id, action, user["username"])
    except ValueError as e:
        raise HTTPException(400 if step_id in GS.STEP_IDS else 404, str(e))
    _audit(_tok(authorization), "getting_started.step", "getting_started", step_id, "開始使用：%s → %s" % (step_id, action))
    return GS.overview()
