# -*- coding: utf-8 -*-
"""專案毛利% 的表單設定（登入者可讀；只有一個提醒門檻數字，沒有任何金額）。算式在 helpers/profit_rules.py::project_margin。"""
from fastapi import APIRouter, Header

from helpers import _require_user
from helpers import settings_registry as sr

router = APIRouter()


@router.get("/api/project-margin/config")
def get_project_margin_config(authorization: str = Header(None)):
    _require_user(authorization)
    try:
        warn = float(sr.get("project_margin", "warn_pct") or 0)
    except (TypeError, ValueError):
        warn = 0.0
    return {"warnPct": warn}
