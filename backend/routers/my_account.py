"""「我的帳號」頁用的 API（2026-11-13）：個人偏好（存伺服器端，換裝置保留）。

只讀寫呼叫者自己的資料；偏好只影響自己看到的畫面，不進報價單／PDF／信件簽名檔。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from helpers import _audit, _require_user, _tok
from helpers import user_prefs as UP

router = APIRouter()


def _view(user_id):
    prefs = UP.get_all(user_id)
    return {
        "prefs": prefs,
        "defaults": UP.defaults(),
        "options": {k: {"label": s["label"], "choices": [{"value": v, "label": l} for v, l in s["options"]]} for k, s in UP.SCHEMA.items()},
    }


@router.get("/api/auth/preferences")
def get_preferences(authorization: str = Header(None)):
    user = _require_user(authorization)
    return _view(user["id"])


@router.put("/api/auth/preferences")
def put_preferences(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    try:
        UP.set_many(user["id"], body)
    except UP.PrefError as e:
        raise HTTPException(422, str(e))
    _audit(_tok(authorization), "auth.preferences.update", "user", str(user["id"]), "更新個人偏好：" + "、".join(UP.SCHEMA[k]["label"] for k in body))
    return _view(user["id"])
