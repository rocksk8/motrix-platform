"""每位使用者的清單排序偏好（報價單列表／案件管理案件清單／案件內單據子清單…）。

list_key 是不透明字串，後端完全不解析內容，範圍規則（要不要帶 quote_no 區分
不同案件的子清單）由前端呼叫端自行決定，見 db.py::_m056_user_list_prefs 的
docstring。每位使用者、每個 list_key 只有一筆設定（PRIMARY KEY(username,
list_key)），純粹是個人化 UI 偏好，不受角色權限限制，任何登入使用者皆可
讀寫自己的設定。
"""
import json
from datetime import datetime
from typing import List

from fastapi import APIRouter, Header
from pydantic import BaseModel

from db import get_db
from helpers import _require_user

router = APIRouter()

_DEFAULT_PREF = {"sortMode": "", "sortDir": "desc", "customOrder": []}


class ListPrefIn(BaseModel):
    sortMode:    str            = ""
    sortDir:     str            = "desc"
    customOrder: List[str]      = []


@router.get("/api/list-prefs/{list_key}")
def get_list_pref(list_key: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT sort_mode, sort_dir, custom_order FROM user_list_prefs WHERE username=? AND list_key=?",
        (user["username"], list_key),
    ).fetchone()
    conn.close()
    if not row:
        return dict(_DEFAULT_PREF)
    return {
        "sortMode":    row["sort_mode"] or "",
        "sortDir":     row["sort_dir"] or "desc",
        "customOrder": json.loads(row["custom_order"] or "[]"),
    }


@router.put("/api/list-prefs/{list_key}")
def set_list_pref(list_key: str, body: ListPrefIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    now = datetime.now().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO user_list_prefs (username, list_key, sort_mode, sort_dir, custom_order, updated_at) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(username, list_key) DO UPDATE SET "
        "sort_mode=excluded.sort_mode, sort_dir=excluded.sort_dir, "
        "custom_order=excluded.custom_order, updated_at=excluded.updated_at",
        (user["username"], list_key, body.sortMode or "", body.sortDir or "desc",
         json.dumps(body.customOrder or [], ensure_ascii=False), now),
    )
    conn.commit()
    conn.close()
    return {"ok": True}
