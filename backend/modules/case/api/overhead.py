# -*- coding: utf-8 -*-
"""管銷分攤設定端點（第 48 班 S2）：登入者可讀目前口徑與全域預設；只有最高管理者可改（每次稽核）。"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from db import get_db
from helpers import _audit, _require_user, _tok
from helpers.settings import _set_setting
from modules.case import profit_guard as PG

router = APIRouter()


@router.get("/api/overhead/settings")
def get_overhead_settings(authorization: str = Header(None)):
    _require_user(authorization)
    return {"ruleMode": PG.rule_mode(), "defaultPct": PG.default_pct(), "ver": PG.current_ver(), "migrationDone": PG.migration_done()}


@router.put("/api/overhead/settings")
def put_overhead_settings(body: dict = Body(...), authorization: str = Header(None)):
    """全域預設比率與口徑開關（回滾用）。只有最高管理者；只影響『之後新建』的報價單與口徑開關，不回改既有單。"""
    _require_user(authorization, require_superadmin=True)
    changes, detail = [], {}
    if "defaultPct" in body:
        try:
            new = PG.parse_pct(body["defaultPct"])
        except ValueError as e:
            raise HTTPException(422, str(e))
        old = PG.default_pct()
        if new != old:
            _set_setting(PG.DEFAULT_KEY, new)
            detail["defaultPct"] = {"old": old, "new": new}
            changes.append("預設比率 %s%% → %s%%" % (old, new))
    if "ruleMode" in body:
        if body["ruleMode"] not in PG.MODES:
            raise HTTPException(422, "ruleMode 只能是 legacy 或 v2")
        old = PG.rule_mode()
        if body["ruleMode"] == "v2" and old != "v2":                 # 切到新口徑：要明確確認，且既有報價單的遷移必須已完成（防止新舊口徑的單混在一起）
            if body.get("confirm") is not True:
                raise HTTPException(422, "切換到新口徑會改變所有未精算報價單的營業利益與獎金基數，請帶 confirm=true 明確確認")
            if not PG.migration_done():
                raise HTTPException(409, "既有報價單尚未完成遷移（tools/overhead_migrate.py recalc --apply 會寫入完成標記），不能切換到新口徑")
        if body["ruleMode"] != old:
            if body["ruleMode"] == "legacy":                          # 退回舊口徑：遷移完成標記一併移除（legacy 期間存檔的單是舊口徑；再切 v2 前必須重新跑 recalc）
                _c = get_db()
                try:
                    _c.execute("DELETE FROM system_settings WHERE key=?", (PG.MIGRATION_KEY,))
                    _c.commit()
                finally:
                    _c.close()
                detail["migrationMarker"] = "removed"
            _set_setting(PG.MODE_KEY, body["ruleMode"])
            detail["ruleMode"] = {"old": old, "new": body["ruleMode"]}
            changes.append("口徑 %s → %s" % (old, body["ruleMode"]))
    if changes:
        _audit(_tok(authorization), "settings.overhead.update", "settings", "overhead", "；".join(changes), detail)
    return {"ok": True, "ruleMode": PG.rule_mode(), "defaultPct": PG.default_pct()}
