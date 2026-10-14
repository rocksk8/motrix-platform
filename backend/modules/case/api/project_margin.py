# -*- coding: utf-8 -*-
"""專案毛利% 的表單設定（只有看得到報價成本與毛利的人可讀；內容只有一個提醒門檻數字，沒有任何金額）。算式在 helpers/profit_rules.py::project_margin。"""
from fastapi import APIRouter, Header, HTTPException

from helpers import _require_user
from helpers import settings_registry as sr
from helpers.financial_mask import quote_money_visible

router = APIRouter()


@router.get("/api/project-margin/config")
def get_project_margin_config(authorization: str = Header(None)):
    user = _require_user(authorization)
    if not quote_money_visible(user):                  # 最小揭露：只有看得到報價成本與毛利的人會用到這個門檻
        raise HTTPException(403, "你沒有查看報價成本與毛利的權限")
    try:
        warn = float(sr.get("project_margin", "warn_pct") or 0)
    except (TypeError, ValueError):
        warn = 0.0
    try:                                                # BP-2 K01 種子：旗標 builder_rules.k01_seed 開、且種子規則已發布 ⇒ 門檻以規則為準；否則維持上面的設定值（今天的行為）
        from helpers import rule_sets as _rs
        seeded = _rs.k01_warn_pct()
        if seeded is not None:
            warn = seeded
    except Exception:                                   # noqa: BLE001  規則讀不到不可影響報價單
        pass
    return {"warnPct": warn}
