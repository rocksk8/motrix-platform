# -*- coding: utf-8 -*-
"""GET /api/system-hub：系統中心（左：分組、右：細項）的資料——這位使用者看得到的系統入口（第 54 班 P1；core.system_hub）。

- 卡片來源＝L1 `core/system_hub_l1.json` ＋ 已載入模組 module.json 的 `system_cards`；伺服器已依權限過濾（不放寬也不收緊頁面本身的權限）。
- 即時狀態徽章（選用）：`registry.providers("system.hub_badge")[card id](conn, user) -> {"text","tone","count"?}`。
  並行執行、每個 300ms 逾時；逾時、例外、回傳格式不對 ⇒ 該項不顯示徽章（記 log），**不影響其他項、不 500**。提供者必須唯讀。
- 15 秒快取（依使用者＋角色＋模組權限）：換頁回來不重算；徽章最多落後 15 秒。
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait

from fastapi import APIRouter, Header

from core import registry, system_hub as hub
from db import get_db
from helpers import _require_user

router = APIRouter()
logger = logging.getLogger(__name__)

CACHE_SECONDS = 15
BADGE_TIMEOUT = 0.3
_CACHE = {}
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hub-badge")


def _all_cards():
    loaded = registry.loaded()
    cards = hub.load_l1_cards() + hub.module_cards({m.key: m.manifest for m in loaded})
    bad = hub.validate(cards)
    if bad:                                                         # 壞宣告只影響那一筆，不讓整個系統頁掛掉（守門測試會擋進 repo）
        logger.warning("系統中心卡片宣告有問題（已略過有問題的卡片）：%s", "; ".join(bad[:5]))
        bad_ids = {c.get("id") for c in cards if hub.validate([c])}
        cards = [c for c in cards if c.get("id") not in bad_ids]
    return cards


def _run_badge(fn, user):
    conn = get_db()
    try:
        return fn(conn, user)
    finally:
        conn.close()


def _clean_badge(b):
    if not isinstance(b, dict):
        return None
    text, tone = b.get("text"), b.get("tone")
    if not isinstance(text, str) or not text.strip() or tone not in hub.TONES:
        return None
    out = {"text": text.strip()[:40], "tone": tone}
    if isinstance(b.get("count"), int) and not isinstance(b.get("count"), bool):
        out["count"] = b["count"]
    return out


def attach_badges(sections, user, timeout=BADGE_TIMEOUT):
    """替各項補徽章（原地）；回傳 {card id: 失敗原因} 供測試與 log。"""
    providers = registry.providers("system.hub_badge")
    jobs = {}
    for s in sections:
        for it in s["items"]:
            fn = providers.get(it["id"])
            if fn is not None and not it["planned"]:
                jobs[it["id"]] = (it, _POOL.submit(_run_badge, fn, user))
    failures = {}
    if jobs:
        wait([f for _it, f in jobs.values()], timeout=timeout)
    for cid, (it, fut) in jobs.items():
        if not fut.done():
            failures[cid] = "timeout"
            fut.cancel()
            continue
        try:
            it["badge"] = _clean_badge(fut.result())
            if it["badge"] is None:
                failures[cid] = "bad_format"
        except Exception as e:                                      # noqa: BLE001 — 一個提供者壞掉不拖垮整頁
            failures[cid] = "error:%s" % e.__class__.__name__
    for cid, why in failures.items():
        logger.warning("系統中心徽章 %s 略過：%s", cid, why)
    for s in sections:
        s["pending"] = any(it["badge"] and it["badge"]["tone"] == "warn" for it in s["items"])
    return failures


def build_for(user):
    from helpers.auth import effective_modules
    modules = effective_modules(user.get("role"), user.get("modules"))
    sa = user.get("role") == "superadmin"
    cards = hub.visible_cards(_all_cards(), modules, sa)
    sections = hub.build_sections(cards)
    attach_badges(sections, user)
    return {"v": 1, "sections": sections, "total": sum(s["count"] for s in sections)}


@router.get("/api/system-hub")
def system_hub(authorization: str = Header(None)):
    user = _require_user(authorization)
    from helpers.auth import effective_modules
    key = (user.get("id"), user.get("role"), tuple(sorted(effective_modules(user.get("role"), user.get("modules")))))
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    out = build_for(user)
    if len(_CACHE) > 256:
        _CACHE.clear()
    _CACHE[key] = (now, out)
    return out


def clear_cache():
    """測試用。"""
    _CACHE.clear()
