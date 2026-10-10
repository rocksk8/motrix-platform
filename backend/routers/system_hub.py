# -*- coding: utf-8 -*-
"""GET /api/system-hub：系統中心（左：分組、右：細項）的資料——這位使用者看得到的系統入口（第 54 班 P1；core.system_hub）。

- 卡片來源＝L1 `core/system_hub_l1.json` ＋ 已載入模組 module.json 的 `system_cards`；伺服器已依權限過濾（不放寬也不收緊頁面本身的權限）。
- 即時狀態徽章（選用）：`registry.providers("system.hub_badge")[card id](conn, user) -> {"text","tone","count"?}`。
  並行執行、每個 300ms 逾時；逾時、例外、回傳格式不對 ⇒ 該項不顯示徽章（記 log），**不影響其他項、不 500**。提供者必須唯讀。
- 15 秒快取（依使用者＋角色＋模組權限）：換頁回來不重算；徽章最多落後 15 秒。
"""
import json
import logging
import threading
import time

from fastapi import APIRouter, Header

from core import registry, system_hub as hub
from db import get_db
from helpers import _require_user
from helpers import settings_registry as sr
from helpers.settings_registry import SettingDef as S

router = APIRouter()
logger = logging.getLogger(__name__)

CACHE_SECONDS = 15
RECENT_KEY = "system_hub_recent"                 # 每個帳號的『最近使用』（user_list_prefs 的 customOrder，最多 5 個卡片 id）
RECENT_MAX = 5
BADGE_TIMEOUT = 0.3
_CACHE = {}
_INFLIGHT = {}                  # 徽章 id → 還在跑的執行緒（卡住的提供者只擋它自己，不佔共用執行緒池）

# 『沒有權限的項目要不要列出來』是一個『放寬可見度』的設定：走設定登錄表（版本、影響說明、稽核同交易、放寬要確認期間與第二人核准），不自己寫設定鍵。
sr.register_group(
    "system_hub", "系統中心",
    [
        S("show_denied", "int", 0, min=0, max=1, risk="security", loosen="up", recommended=0,
          question="系統中心要不要列出『你沒有權限使用』的項目？", label="沒有權限的項目",
          help="預設隱藏：每個人只看到自己能用的項目。也可以改成顯示為灰色，並說明為什麼不能用。",
          impact="只影響系統中心的畫面，不會改變任何人實際能使用的功能。改成『顯示為灰色』時，沒有權限的人會看到有哪些管理項目的名稱，但點不進去。",
          risk_text="顯示後，沒有權限的人也能知道系統裡有哪些管理功能（例如備份、權限、稽核）；若不希望外人知道，請維持隱藏。",
          choices=[(0, "隱藏（建議）", "每個人只看到自己能用的項目；沒有權限的人完全看不到其他項目。"),
                   (1, "顯示為灰色並說明原因", "沒有權限的人會看到項目名稱與『需要什麼權限』，但點不進去。")]),
    ],
    sensitive=True, risk="security",
    help="系統中心的顯示方式。",
)


def _all_cards():
    loaded = registry.loaded()
    cards = hub.load_l1_cards() + hub.module_cards({m.key: m.manifest for m in loaded})
    bad = hub.validate(cards)
    if bad:                                                         # 壞宣告只影響那一筆，不讓整個系統頁掛掉（守門測試會擋進 repo）
        logger.warning("系統中心卡片宣告有問題（已略過有問題的卡片）：%s", "; ".join(bad[:5]))
        bad_ids = {c.get("id") for c in cards if hub.validate([c])}
        cards = [c for c in cards if c.get("id") not in bad_ids]
    return cards


def _run_badge_into(cid, fn, user, box, done):
    try:
        box["value"] = _run_badge(fn, user)
    except Exception as e:                                          # noqa: BLE001
        box["error"] = e
    finally:
        done.set()


def _run_badge(fn, user):
    conn = get_db()
    try:
        conn.execute("PRAGMA query_only = ON")        # 徽章提供者必須唯讀：這條連線寫入一律失敗（IP-HUB1；測試以會寫入的提供者驗證）
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
    jobs, failures = {}, {}
    for s in sections:
        for it in s["items"]:
            fn = providers.get(it["id"])
            if fn is None or it["planned"] or it.get("denied"):
                continue
            prev = _INFLIGHT.get(it["id"])
            if prev is not None and prev.is_alive():                # 上一次還卡著：跳過這個徽章（不再開新執行緒、不影響別的徽章）
                failures[it["id"]] = "busy"
                continue
            box, done = {}, threading.Event()
            t = threading.Thread(target=_run_badge_into, args=(it["id"], fn, user, box, done), daemon=True, name="hub-badge-%s" % it["id"])
            _INFLIGHT[it["id"]] = t
            t.start()
            jobs[it["id"]] = (it, box, done)
    deadline = time.monotonic() + timeout
    for cid, (it, box, done) in jobs.items():
        if not done.wait(max(0.0, deadline - time.monotonic())):
            failures[cid] = "timeout"
            continue
        if "error" in box:                                          # 一個提供者壞掉不拖垮整頁
            failures[cid] = "error:%s" % box["error"].__class__.__name__
            continue
        it["badge"] = _clean_badge(box.get("value"))
        if it["badge"] is None:
            failures[cid] = "bad_format"
    for cid, why in failures.items():
        logger.warning("系統中心徽章 %s 略過：%s", cid, why)
    for s in sections:
        s["pending"] = any(it["badge"] and it["badge"]["tone"] == "warn" for it in s["items"])
    return failures


def _capability_checker(user):
    """權限矩陣（`perm.can` 提供者，1d）存在時：回 `can(cap) -> bool`；不在或沒有 cap 的卡片 ⇒ None／退回舊 perm 語意。"""
    fn = registry.single_provider("perm.can")
    if fn is None:
        return None
    return lambda cap: bool(fn(user, cap))


def show_denied():
    return sr.get("system_hub", "show_denied") == 1             # 讀取時依待生效狀態判斷（放寬要等確認期間）


def _module_labels():
    try:
        from helpers.module_registry import MODULES
        return {m[0]: m[1] for m in MODULES}
    except Exception:                                            # noqa: BLE001 — 取不到名稱只影響原因文字
        return {}


def build_for(user):
    from helpers.auth import effective_modules
    modules = effective_modules(user.get("role"), user.get("modules"))
    sa = user.get("role") == "superadmin"
    allc = _all_cards()
    can = _capability_checker(user)
    cards = hub.visible_cards(allc, modules, sa, can)
    shown = {c["id"] for c in cards}
    denied = [c for c in allc if c["id"] not in shown] if show_denied() else []
    sections = hub.build_sections(cards, denied, _module_labels())
    attach_badges(sections, user)
    return {"v": 1, "sections": sections, "total": sum(s["count"] for s in sections), "showDenied": show_denied()}


def recent_for(user, sections):
    """這個帳號的最近使用（卡片 id，新→舊，最多 5 個）；只留現在還看得到、能開的（權限或模組變動後自動消失）。"""
    openable = {it["id"] for s in sections for it in s["items"] if not it.get("denied")}
    conn = get_db()
    try:
        row = conn.execute("SELECT custom_order FROM user_list_prefs WHERE username=? AND list_key=?", (user["username"], RECENT_KEY)).fetchone()
    finally:
        conn.close()
    try:
        ids = json.loads(row["custom_order"] or "[]") if row else []
    except (TypeError, ValueError):
        ids = []
    out = []
    for i in ids:
        if isinstance(i, str) and i in openable and i not in out:
            out.append(i)
    return out[:RECENT_MAX]


@router.get("/api/system-hub")
def system_hub(authorization: str = Header(None)):
    user = _require_user(authorization)
    from helpers.auth import effective_modules
    key = (user.get("id"), user.get("role"), tuple(sorted(effective_modules(user.get("role"), user.get("modules")))), show_denied())
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < CACHE_SECONDS:
        out = hit[1]
    else:
        out = build_for(user)
        if len(_CACHE) > 256:
            _CACHE.clear()
        _CACHE[key] = (now, out)
    return dict(out, recent=recent_for(user, out["sections"]))      # 最近使用不進快取：點過馬上看得到


def clear_cache():
    """清掉快取（權限矩陣／代理／設定異動時由 `perm.changed` 通知；也給測試用）。"""
    _CACHE.clear()


# 權限矩陣（1d）在任何授權／代理／狀態異動時呼叫所有 `perm.changed` 提供者：系統中心的快取立刻失效，不等 15 秒（多行程時最壞仍是 15 秒）
registry.provide("perm.changed", "system_hub", lambda: clear_cache())
