# -*- coding: utf-8 -*-
"""管銷分攤設定端點（第 48 班 S2）：登入者可讀目前口徑與全域預設；只有最高管理者可改（每次稽核）。"""
from fastapi import APIRouter, Body, Header, HTTPException

from helpers import _audit, _require_user, _tok
from helpers.settings import _set_setting
from modules.case import profit_guard as PG

router = APIRouter()


@router.get("/api/overhead/settings")
def get_overhead_settings(authorization: str = Header(None)):
    _require_user(authorization)
    return {"ruleMode": PG.rule_mode(), "defaultPct": PG.default_pct(), "ver": PG.current_ver()}


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
        if body["ruleMode"] != old:
            _set_setting(PG.MODE_KEY, body["ruleMode"])
            detail["ruleMode"] = {"old": old, "new": body["ruleMode"]}
            changes.append("口徑 %s → %s" % (old, body["ruleMode"]))
    if changes:
        _audit(_tok(authorization), "settings.overhead.update", "settings", "overhead", "；".join(changes), detail)
    return {"ok": True, "ruleMode": PG.rule_mode(), "defaultPct": PG.default_pct()}
