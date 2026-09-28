# -*- coding: utf-8 -*-
"""附近旅宿的端點（前綴 `/api/lodging`，權限 key `lodging`）。

只 import core／helpers／db（L1）與本模組；不 import 其他 L2。
旅宿資料只在 `POST /refresh`（最高管理者、開關開著、速率允許）時連線；查詢只查本機快照
（地址定位經 L1 geo，見 api_records.py 檔頭）。
"""
from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
# 走模組：測試要換得掉 source.fetch_raw／source._now
from modules.lodging import attribution as lodging_attr
from modules.lodging import source as lodging_source

router = APIRouter()


def _require_lodging(authorization: str) -> dict:
    user = _require_user(authorization)
    require_any_module(user, ("lodging",), "附近旅宿")   # 字面值：test_module_keys_consistency 掃它
    return user


@router.get("/api/lodging/status")
def lodging_status(authorization: str = Header(None)):
    """資料狀態（純讀、無副作用；也是演練 probe）。"""
    user = _require_lodging(authorization)
    conn = get_db()
    try:
        cat = lodging_source.catalog_state(conn)
    finally:
        conn.close()
    st = lodging_source.fetch_state()
    nxt = lodging_source.next_allowed_at(st, lodging_source._now())
    return {
        "fetchEnabled": lodging_source.fetch_on(),
        "canRefresh": user.get("role") == "superadmin",
        "count": cat["count"],
        "datasetUpdatedAt": cat["dataset_updated_at"],
        "stale": cat["stale"],
        "staleDays": lodging_source.STALE_DAYS,
        "lastSuccessAt": st.get("last_success_at") or "",
        "lastFailureAt": st.get("last_failure_at") or "",
        "lastError": st.get("last_error") or "",
        "nextAllowedAt": nxt.isoformat(timespec="seconds") if nxt else "",
        "attribution": lodging_attr.attribution_text([cat["dataset_updated_at"]]) if cat["count"] else "",
    }


@router.post("/api/lodging/refresh")
def lodging_refresh(authorization: str = Header(None)):
    """下載觀光署資料並整批替換快照（最高管理者；唯一的對外連線）。"""
    user = _require_lodging(authorization)
    if user.get("role") != "superadmin":
        raise HTTPException(403, "只有最高管理者可以更新旅宿資料")
    result = lodging_source.refresh()
    _audit(_tok(authorization), "lodging_refresh", "lodging", "", "旅宿資料更新",
           {k: result.get(k) for k in ("ok", "reason", "count", "dataset_updated_at")})
    return result
