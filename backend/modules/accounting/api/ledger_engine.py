# -*- coding: utf-8 -*-
"""總帳：分錄引擎介面（A 階段：只有事件來源狀態與預覽，不產生傳票）。設計：proposal-gl/02-events-engine.md。

`GET /api/ledger/events/preview` 向所有 `gl.events` 提供者收集事件並驗證，回來源狀態、事件數、無效事件與缺席說明；
不寫任何資料。C 階段才加「產生草稿」。
"""
import datetime as _dt

from fastapi import APIRouter, Header, HTTPException

from helpers import _require_user, require_any_module
from modules.accounting.ledger import contract as _contract

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


def _require_engine_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("cashier", "finance"), "總帳")
    return user


@router.get("/events/preview")
def events_preview(start: str, end: str, authorization: str = Header(None)):
    _require_engine_read(authorization)
    try:
        s, e = _dt.date.fromisoformat(start), _dt.date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "日期格式要是 YYYY-MM-DD。")
    if s > e:
        raise HTTPException(400, "起日不可晚於迄日。")
    res = _contract.collect(s.isoformat(), e.isoformat())
    return {"contract_version": _contract.CONTRACT_VERSION, "count": len(res["events"]), "sources": res["sources"],
            "notices": res["notices"], "invalid": res["invalid"][:50], "invalid_count": len(res["invalid"]),
            "events": res["events"][:200]}
