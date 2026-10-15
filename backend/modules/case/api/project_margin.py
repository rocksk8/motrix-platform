# -*- coding: utf-8 -*-
"""專案毛利% 的表單設定（只有看得到報價成本與毛利的人可讀；內容只有一個提醒門檻數字，沒有任何金額）。算式在 helpers/profit_rules.py::project_margin。"""
from fastapi import APIRouter, Header, HTTPException

from helpers import _require_user
from helpers import settings_registry as sr
from helpers.financial_mask import quote_money_visible
from helpers import profit_warning as _pw

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
    from modules.case.quote_terms import min_item_margin_pct         # 單項毛利率送審門檻（設定 quote_approval.min_item_margin_pct，預設 30＝今天）；表單的 checkApproval 與伺服器同源
    from modules.case.quote_terms import discount_review_above, max_valid_days      # 送審門檻（設定 quote_approval.*）：表單的 checkApproval 與伺服端重算同源
    return {"warnPct": warn, "minItemMarginPct": min_item_margin_pct(), "maxValidDays": max_valid_days(), "discountReviewAbove": discount_review_above(),
            "defaultValidDays": _pw.default_valid_days()}          # 新報價單預設有效天數（設定 quote_defaults.valid_days，預設 30＝今天）


@router.get("/api/profit-warning/config")
def get_profit_warning_config(authorization: str = Header(None)):
    """各畫面利潤顏色的門檻（設定 profit_warning.*；預設＝各畫面今天寫死的數字；讀不到／不合法 ⇒ 整組回今天的數字）。
    登入者都回 200：看不到毛利的人回今天的預設數字（門檻不是機密、不含任何毛利；他們畫面上也沒有毛利數字可上色），避免頁面主控台出現 403。純顯示，不阻擋任何動作。"""
    user = _require_user(authorization)
    if not quote_money_visible(user):
        return dict(_pw.DEFAULTS)
    return _pw.bands()
