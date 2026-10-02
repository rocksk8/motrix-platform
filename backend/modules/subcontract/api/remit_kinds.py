# -*- coding: utf-8 -*-
"""匯款款別下拉：`GET /api/remit-kinds`（31-B S0）。設定（草稿／發布／版本／差異）走既有定義文件庫 `/api/definitions/remit_kinds/default/…`（最高管理者）；
這支只給「開匯款申請」的人讀啟用中的款別與其可開立的派發狀態（管理員以上，與建立匯款申請的權限一致）。"""
from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _require_user
from modules.subcontract import remit_kinds as RK

router = APIRouter()


@router.get("/api/remit-kinds")
def list_remit_kinds(authorization: str = Header(None)):
    user = _require_user(authorization)
    if user.get("role") not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    conn = get_db()
    try:
        out = RK.active_kinds(conn)
    finally:
        conn.close()
    out["stages"] = [{"key": s, "label": RK.STAGE_LABELS[s]} for s in RK.STAGES]
    return out


@router.get("/api/remit-kinds/definition")
def remit_kinds_definition(authorization: str = Header(None)):
    """設定頁用（最高管理者）：目前生效的完整定義（含停用的款別）與版本；沒發布過 ⇒ 出貨預設（版本 0）。草稿／發布／差異走 `/api/definitions/remit_kinds/default/…`。"""
    user = _require_user(authorization)
    if user.get("role") != "superadmin":
        raise HTTPException(403, "需要最高管理者權限")
    conn = get_db()
    try:
        cur = RK.current(conn)
    finally:
        conn.close()
    return {"version": cur["version"], "isDefault": cur["version"] == 0, "body": {"name": "匯款款別", "kinds": cur["kinds"]},
            "stages": [{"key": s, "label": RK.STAGE_LABELS[s]} for s in RK.STAGES]}
