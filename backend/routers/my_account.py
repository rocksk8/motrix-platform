"""「我的帳號」頁用的 API（2026-11-13）：個人資料（唯讀）與個人偏好（存伺服器端，換裝置保留）。

只讀寫呼叫者自己的資料；偏好只影響自己看到的畫面，不進報價單／PDF／信件簽名檔。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
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


@router.get("/api/auth/profile")
def get_profile(authorization: str = Header(None)):
    """「我的帳號 → 個人資料」：只回呼叫者自己的資料；全部唯讀（會出現在報價單／PDF／信件上的欄位由管理者維護，這裡沒有寫入端點）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT u.id, u.username, u.display_name, u.role, u.email, u.phone, u.quote_email, dep.name AS department_name "
            "FROM users u LEFT JOIN departments dep ON dep.id = u.department_id WHERE u.id=?", (user["id"],)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "找不到帳號")
    from helpers import quote_email as _qe
    eff = _qe.resolve_for_row(row)
    return {
        "username": row["username"],
        "displayName": row["display_name"] or row["username"],
        "role": row["role"],
        "department": row["department_name"] or "",
        "email": row["email"] or "",
        "phone": row["phone"] or "",
        # 報價用公司信箱：只讀（只有最高管理者能在「使用者管理」設定）。effective＝報價單實際會帶入的信箱
        "quoteEmail": row["quote_email"] or "",
        "quoteEmailEffective": eff["email"],
        "quoteEmailSource": eff["source"],
    }
