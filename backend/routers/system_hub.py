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
from helpers import settings_groups  # noqa: F401  確保群組已登錄（單一登錄處）
from helpers import settings_registry as sr

router = APIRouter()
logger = logging.getLogger(__name__)

CACHE_SECONDS = 15
RECENT_KEY = "system_hub_recent"                 # 每個帳號的『最近使用』（user_list_prefs 的 customOrder，最多 5 個卡片 id）
RECENT_MAX = 5
BADGE_TIMEOUT = 0.3
_CACHE = {}
_INFLIGHT_LOCK = threading.Lock()   # 『檢查有沒有還在跑 → 開新執行緒』必須是一個不可分割的動作，否則兩個請求會同時開兩條
_INFLIGHT = {}                  # 徽章 id → 還在跑的執行緒（卡住的提供者只擋它自己，不佔共用執行緒池）

# 設定群組 `system_hub`（『沒有權限的項目要不要列出』）登錄在 helpers/settings_groups.py（單一登錄處；載入本檔時已載入）。
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
            box, done = {}, threading.Event()
            t = threading.Thread(target=_run_badge_into, args=(it["id"], fn, user, box, done), daemon=True, name="hub-badge-%s" % it["id"])
            with _INFLIGHT_LOCK:
                prev = _INFLIGHT.get(it["id"])
                if prev is not None and prev.is_alive():            # 上一次還卡著：跳過這個徽章（不再開新執行緒、不影響別的徽章）
                    failures[it["id"]] = "busy"
                    continue
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
    """權限矩陣（L1 `helpers.perm.can(user, cap)`，1d）存在時：回 `can(cap) -> bool`；L1 尚未帶 `helpers.perm`（矩陣上線前）⇒ None ⇒ 退回舊 perm 語意。

    直接用 L1 名稱（不經登錄表提供者——曾經沒人提供 `perm.can`，能力判斷等於默默失效）。
    只有『模組根本不存在』才退回舊語意；模組存在卻匯入失敗 ⇒ **一律拒絕**有 cap 的卡片（fail-closed；舊語意可能顯示矩陣已收回的項目）並大聲記 log。"""
    import importlib.util
    import sys
    if "helpers.perm" not in sys.modules and importlib.util.find_spec("helpers.perm") is None:     # 權限矩陣尚未上線：唯一允許的退回
        return None
    try:
        from helpers import perm
    except Exception:                                            # noqa: BLE001
        logger.exception("系統中心：權限矩陣存在但匯入失敗，有能力鍵的項目一律不顯示")
        return lambda cap: False
    def can(cap):
        try:
            return bool(perm.can(user, cap))
        except Exception:                                        # noqa: BLE001 — 一張卡的判斷壞了只隱藏那張，不拖垮整個系統中心
            logger.exception("系統中心：權限判斷丟出例外，這個項目不顯示")
            return False
    return can


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
    sc = next((c for c in allc if c["id"] == "settings-center"), None)           # 『調整這個設定』的去處也來自註冊表，頁面不寫死名稱與連結
    return {"v": 1, "sections": sections, "total": sum(s["count"] for s in sections), "showDenied": show_denied(),
            "settingsLink": {"title": sc["title"], "href": sc["href"]} if sc and sa else None}


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
