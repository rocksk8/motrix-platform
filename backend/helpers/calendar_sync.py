# -*- coding: utf-8 -*-
"""日期型行事曆事件的每日對帳（L1；MAIL-CAL 階段 2：保固到期／區間事項結束／專案預計完成）。

[單位] helper:calendar_sync    [層] L1    [穩定度] 實作
[公開介面] MAX_CALLS_PER_RUN, MAX_CONSECUTIVE_FAILURES, is_active, sync_dated_events
[契約題] tests/test_notify_matrix_phase2_2026_10_06.py
[不變式]
  - 事件種類開關（`google_calendar.events[code]`）或行事曆總開關關閉 ⇒ 完全不動作（不讀來源之外的任何東西、不寫對帳表、
    零 Google 流量）。預設關 ⇒ 升級後行為不變。
  - 事件走 t41 同一套邏輯，但用會丟例外的 `google_calendar._upsert_event_strict`／`_delete_event_strict`（key＝來源單號／id）：
    **只有成功才把該項目記進對帳表**；失敗（暫時性 Google／授權問題）保留舊記錄、下次每日檢查重試；連續失敗 3 次本次收手。
  - 對帳表 `system_settings["calsync.<代碼>"]＝{key: [日期, 內容指紋]}`：只在內容有變時才 upsert（每天不重打全部事件），
    來源消失或日期改成已過 ⇒ delete／保留（見下），重新打開開關時與表比對即可補齊關閉期間的差異。
  - 事件內容不放金額（使用者裁示）；呼叫端組好 summary／description。
  - 設計 Q9：日期早於今天 ⇒ 不建。已建的事件若日期不變而過期 ⇒ 保留事件（歷史），只從對帳表移除；
    來源被刪、不再成立、或日期改了 ⇒ 刪舊的（日期改成未來則再建新的）。
  - 每次最多 `MAX_CALLS_PER_RUN` 個項目（每個約 2 次 Google 請求），剩下的留給隔天（第一次打開開關時不會一次灌爆配額）；沒處理的項目不寫進對帳表。
"""
import hashlib
import logging
from datetime import date, datetime

from . import google_calendar as _gc
from .settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

MAX_CALLS_PER_RUN = 100        # 每個項目＝找＋建／改（或找＋刪）約 2 次 Google 請求 ⇒ 一次最多約 200 次請求
MAX_CONSECUTIVE_FAILURES = 3      # 連續失敗（授權壞了、Google 掛了）就收手，不整批打爛
_STATE_PREFIX = "calsync."


def _fingerprint(summary: str, description: str) -> str:
    return hashlib.sha1(f"{summary}\n{description}".encode("utf-8")).hexdigest()[:12]


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def is_active(code: str) -> bool:
    """該事件種類開著、而且行事曆總開關也開著——呼叫端掃描來源資料表**之前**先問，關著就連查詢都不做。"""
    try:
        return bool(_gc.event_enabled(code) and (_gc._cfg() or {}).get("enabled"))
    except Exception:                                    # 讀不到設定 ⇒ 當成不動作
        return False


def sync_dated_events(code: str, current: dict, today=None, max_calls: int = MAX_CALLS_PER_RUN) -> dict:
    """`current`＝來源目前成立的全部項目 {key: (日期, 標題, 說明)}（含已過期的，不含已不成立的）。
    ⇒ {"upserted": n, "deleted": n, "kept": n, "failed": n, "skipped": 原因或 ""}（給測試與 log）。"""
    stats = {"upserted": 0, "deleted": 0, "kept": 0, "failed": 0, "skipped": ""}
    try:
        if not _gc.event_enabled(code):
            stats["skipped"] = "event_off"
            return stats
        if not (_gc._cfg() or {}).get("enabled"):
            stats["skipped"] = "calendar_off"          # 總開關關著：upsert／delete 都不會動，對帳表也不能前進
            return stats
        today = _to_date(today) or date.today()
        state_key = _STATE_PREFIX + code
        old = _get_setting(state_key, {}) or {}
        if not isinstance(old, dict):
            old = {}
        new = {}
        run = {"calls": 0, "fails": 0, "halt": False}

        def _keep_old(k):
            if k in old:
                new[k] = old[k]

        def _try(fn, *args) -> bool:
            """⇒ True＝這個項目的 Google 動作成功。失敗／沒做＝False（呼叫端保留舊記錄、下次重試）。"""
            if run["halt"] or run["calls"] >= max_calls:
                return False
            run["calls"] += 1
            try:
                ok = fn(*args)
            except Exception as exc:                  # 暫時性 Google／授權失敗：不記為已同步
                logger.warning("calendar_sync(%s): %s%r 失敗，下次重試：%s", code, getattr(fn, "__name__", "fn"), args[-1:], exc)
                run["fails"] += 1
                stats["failed"] += 1
                if run["fails"] >= MAX_CONSECUTIVE_FAILURES:
                    run["halt"] = True
                return False
            if ok:
                run["fails"] = 0
            return bool(ok)

        for key, (d, summary, description) in sorted(current.items()):
            d = _to_date(d)
            prev = old.get(key)
            if d is None:
                continue                                  # 沒有日期＝不成立：落到下面的「消失」處理（舊的會被刪）
            if d < today:
                if prev and prev[0] == d.isoformat():
                    stats["kept"] += 1                    # 日期沒變、只是過期：事件留著當歷史，從表移除
                elif prev:
                    if _try(_gc._delete_event_strict, code, key):     # 日期被改成已過：舊的（未來日期）不再有意義
                        stats["deleted"] += 1
                    else:
                        _keep_old(key)
                continue
            fp = _fingerprint(summary, description)
            if prev and prev == [d.isoformat(), fp]:
                new[key] = prev
                continue
            if _try(_gc._upsert_event_strict, code, summary, description, d, key):
                stats["upserted"] += 1
                new[key] = [d.isoformat(), fp]
            else:
                _keep_old(key)

        valid_keys = {k for k, v in current.items() if _to_date(v[0]) is not None}
        for key in old:
            if key in valid_keys:
                continue                                  # 上面已處理
            if _try(_gc._delete_event_strict, code, key):  # 來源消失或不再成立
                stats["deleted"] += 1
            else:
                _keep_old(key)
        if new != old:
            _set_setting(state_key, new)
    except Exception as exc:                              # 對帳失敗不能影響每日檢查的其他工作
        logger.warning("sync_dated_events(%r) failed: %s", code, exc)
        stats["skipped"] = "error"
    return stats
