# -*- coding: utf-8 -*-
"""首頁「我的工作」：依使用者身分彙整「現在輪到我處理什麼」。

[單位] router:dashboard_mine    [層] L1    [穩定度] 實驗
[公開介面] GET /api/dashboard/mine；提供者 `dashboard.mine_groups`：`fn(user: dict) -> list[group]`
[不變式]
  - 「我的」定義＝UX-BUSINESS-PAGES-PROPOSAL §3.1：待我簽核／我送出的單／卡住的單（最高管理者）＋各模組自己交出的分組。
  - 分組由「使用者實際有的模組權限」決定（模組不在、沒權限 ⇒ 那一組不出現，不是 0）；每組各自 try/except，
    壞一組只少那一組（`errors` 記 key），不會讓首頁整塊空白。
  - 待簽核的數字與 `/api/approval-queue/count` 同一個來源（`visible_queue_items` → `mine`），不另算。
  - 每人 30 秒記憶體快取（首頁每次開都會呼叫；簽核動作後前端以 `?fresh=1` 略過）。
  - 提供者回傳的 group 形狀：{key,title,count,href,hrefLabel,items:[{title,sub,href,tone}],kind?,order?}；
    `tone` 只用 ok／warn／crit；`kind`＝work（預設）／money／remind，前端據此分區；缺 key／title 的丟棄。
[契約題] tests/test_dashboard_mine_2026_11_13.py
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, Query

from core import registry
from helpers import _require_user
from routers.approval_queue import visible_queue_items

logger = logging.getLogger(__name__)
router = APIRouter()

_TTL = 30.0
_cache: dict = {}
_lock = threading.Lock()
_TZ = timezone(timedelta(hours=8))
_TONES = ("ok", "warn", "crit")
_MAX_ITEMS = 5          # 每組只列最要緊的幾筆；其餘靠「看全部」進原頁面


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def _now() -> datetime:
    return datetime.now(_TZ).replace(tzinfo=None)


def age_days(requested_at, now=None) -> int:
    """'YYYY-MM-DD HH:MM:SS'／ISO 字串 → 已過幾天（與簽核頁 `_ageDays` 同算法；解析失敗＝0）。"""
    raw = str(requested_at or "").strip()
    if not raw:
        return 0
    try:
        d = datetime.fromisoformat(raw.replace(" ", "T")[:19])
    except ValueError:
        return 0
    return max(0, ((now or _now()) - d).days)


def age_tone(days: int) -> str:
    """與簽核頁 ageTone 同門檻：≥4 天 crit、≥2 天 warn。"""
    return "crit" if days >= 4 else "warn" if days >= 2 else "ok"


def blocker_display(item: dict) -> str:
    """這一筆目前卡在誰（與簽核頁 `blockerOf` 同規則）：當層第一個未簽的人；沒有簽核層 ⇒ 最高管理者。"""
    if item.get("type") != "case_change":
        tiers = item.get("tiers") or []
        cur = item.get("currentTier") or 0
        if tiers and cur < len(tiers):
            for a in (tiers[cur].get("approvers") or []):
                if a.get("status") != "approved":
                    return a.get("displayName") or a.get("username") or "最高管理者"
    return "最高管理者"


def _item_title(it: dict) -> str:
    a = (it.get("customer") or "").strip()
    b = (it.get("projectName") or "").strip()
    return " ".join(x for x in (a, b) if x) or (it.get("quoteNo") or "（未命名）")


def _item_href(it: dict) -> str:
    # 簽核動作一律在簽核頁做（核准／駁回／轉簽、詳情）；從首頁點進去只需要到那一頁
    return "pages/approval-queue.html"


def _stuck_text(it: dict, now) -> str:
    d = age_days(it.get("requestedAt"), now)
    return "卡在：%s，%s" % (blocker_display(it), "今天送達" if d == 0 else "已 %d 天" % d)


def _group(key, title, items, *, count=None, href="", href_label="看全部", kind="work", order=50, empty=""):
    return {"key": key, "title": title, "count": len(items) if count is None else count, "href": href,
            "hrefLabel": href_label, "items": items[:_MAX_ITEMS], "kind": kind, "order": order, "empty": empty}


def _approval_groups(user: dict, now) -> list:
    """待我簽核／我送出的單／卡住的單（最高管理者）。三組都從同一份可見項目算。"""
    items, _deleg = visible_queue_items(user)
    me = user["username"]
    out = []

    mine = sorted((i for i in items if i.get("mine")), key=lambda i: str(i.get("requestedAt") or ""))
    out.append(_group(
        "approvals", "待我簽核",
        [{"title": _item_title(i), "sub": "%s 送來，已 %d 天" % (i.get("requestedByDisplay") or i.get("requestedBy") or "", age_days(i.get("requestedAt"), now)),
          "href": _item_href(i), "tone": age_tone(age_days(i.get("requestedAt"), now))} for i in mine],
        count=len(mine), href="pages/approval-queue.html", href_label="去簽核", order=10,
        empty="目前沒有等你簽的單"))

    sent = [i for i in items if i.get("requestedBy") == me and not i.get("mine")]
    sent.sort(key=lambda i: str(i.get("requestedAt") or ""))
    if sent:
        out.append(_group(
            "submitted", "我送出的單",
            [{"title": _item_title(i), "sub": _stuck_text(i, now), "href": _item_href(i),
              "tone": age_tone(age_days(i.get("requestedAt"), now))} for i in sent],
            href="pages/approval-queue.html", href_label="看進度", order=20))

    if user.get("role") == "superadmin":
        stuck = [i for i in items if not i.get("mine") and age_days(i.get("requestedAt"), now) >= 2]
        stuck.sort(key=lambda i: str(i.get("requestedAt") or ""))
        if stuck:
            out.append(_group(
                "stuck", "卡住的單（2 天以上）",
                [{"title": _item_title(i), "sub": _stuck_text(i, now), "href": _item_href(i),
                  "tone": age_tone(age_days(i.get("requestedAt"), now))} for i in stuck],
                href="pages/approval-queue.html", href_label="去催件", order=30))
    return out


def _clean_group(g, order_default=50):
    """提供者回傳的分組做最低限度的形狀檢查；不合格丟棄（不信任第三方模組的輸出形狀）。"""
    if not isinstance(g, dict) or not g.get("key") or not g.get("title"):
        return None
    items = []
    for it in (g.get("items") or [])[:_MAX_ITEMS]:
        if isinstance(it, dict) and it.get("title"):
            items.append({"title": str(it["title"]), "sub": str(it.get("sub") or ""), "href": str(it.get("href") or ""),
                          "tone": it.get("tone") if it.get("tone") in _TONES else "ok"})
    try:
        count = int(g.get("count", len(items)))
    except (TypeError, ValueError):
        count = len(items)
    kind = g.get("kind") if g.get("kind") in ("work", "money", "remind") else "work"
    try:
        order = int(g.get("order", order_default))
    except (TypeError, ValueError):
        order = order_default
    return {"key": str(g["key"]), "title": str(g["title"]), "count": count, "href": str(g.get("href") or ""),
            "hrefLabel": str(g.get("hrefLabel") or "看全部"), "items": items, "kind": kind, "order": order,
            "empty": str(g.get("empty") or "")}


def build_mine(user: dict) -> dict:
    now = _now()
    groups, errors = [], []
    try:
        groups.extend(_approval_groups(user, now))
    except Exception:                                     # noqa: BLE001
        logger.exception("首頁我的工作：簽核分組失敗")
        errors.append("approvals")
    for name, fn in sorted(registry.providers("dashboard.mine_groups").items()):
        try:
            for g in (fn(user) or []):
                c = _clean_group(g)
                if c:
                    groups.append(c)
        except Exception:                                 # noqa: BLE001
            logger.exception("首頁我的工作：提供者 %s 失敗（這一類不列出）", name)
            errors.append(name)
    groups.sort(key=lambda g: (g["order"], g["key"]))
    # 空白狀態＝每一組都沒事可做（待簽核 0 且其他組都 0 筆）：前端據此顯示「目前沒有待辦」＋兩個去處
    empty = all(g["count"] == 0 for g in groups)
    return {"groups": groups, "empty": empty, "errors": errors, "generatedAt": now.strftime("%Y-%m-%d %H:%M:%S")}


@router.get("/api/dashboard/mine")
def dashboard_mine(fresh: int = Query(0), authorization: str = Header(None)):
    user = _require_user(authorization)
    key = user["username"]
    t = time.monotonic()
    if not fresh:
        with _lock:
            hit = _cache.get(key)
        if hit and t - hit[0] < _TTL:
            return hit[1]
    data = build_mine(user)
    with _lock:
        _cache[key] = (t, data)
    return data
