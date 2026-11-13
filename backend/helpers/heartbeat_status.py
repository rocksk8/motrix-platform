# -*- coding: utf-8 -*-
"""心跳監控「本身」的健康判斷（2026-11-11；正式機監控壞了兩個多月沒人知道之後補的「看守看守者」）。

[單位] helper:heartbeat_status    [層] L1    [穩定度] 實作
[公開介面] BAD_GRACE_MINUTES, EXT_UNSET_ALERT_HOURS, LEVEL_ERROR, LEVEL_NA, LEVEL_OK, LEVEL_WARN, OK_STALE_HOURS, assess, config_exists, ping_url_set, read_state
[契約題] tests/test_heartbeat_watch_2026_11_11.py
[不變式]
  ① 唯讀：只讀 `heartbeat_job.py` 寫的 `logs/heartbeat_state.json` 與 `heartbeat_config.json`（路徑走 `core.paths`），不寫任何檔、不連網路、不 import app；
     **對外只回 `ping_url` 有沒有設（布林），永遠不回網址本身**（healthchecks.io 的 ping 網址等同密碼）。
  ② 這個檔回答的是「**app 有在跑**的時候，監控自己有沒有問題」：app 活著卻看到 `local_down` 很久＝監控誤判（2026-09-07 的 http/https 事故正是這樣）；
     app 真的掛了，這個檔跑不到——那條路靠 healthchecks.io 的沉默告警（獨立於本機）。兩者互補，不互相取代。
  ③ 狀態檔的寫入頻率沿用 heartbeat_job 的規則（狀態改變／正常每天第一筆／壞的持續每小時一筆）以免增加硬碟寫入 ⇒ `seen_at` 的新鮮度要照這個節奏判斷：
     正常狀態 `OK_STALE_HOURS` 小時內都算新；壞的狀態持續超過 `BAD_GRACE_MINUTES` 分鐘才升級成需要告警（避免一次網路抖動就寄信）。
  ④ 沒有設定檔也沒有狀態檔＝這台機器沒有心跳（開發機）⇒ `LEVEL_NA`，不告警。
  ⑤ `assess()` 永不丟例外；讀不到／壞掉的狀態檔本身就是一種需要看的狀況（WARN）。
"""
import json
import logging
import os
from datetime import datetime

from core import paths as _paths

logger = logging.getLogger(__name__)

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"
LEVEL_NA = "na"

#: 狀態檔在「正常」時每天才重寫一次 ⇒ 超過這麼久沒更新＝排程可能停了（多留 2 小時餘裕）。
OK_STALE_HOURS = 26
#: 壞的狀態（local_down／ext_fail）持續超過這麼久才算「需要告警」。
BAD_GRACE_MINUTES = 90
#: 沒設對外打卡網址（ext_unset）持續超過這麼久才寄信（開發中的機器常常本來就沒設）。
EXT_UNSET_ALERT_HOURS = 24

_READ = object()


def _state_path() -> str:
    return os.path.join(_paths.LOGS_DIR, "heartbeat_state.json")


def read_state():
    """狀態檔內容（dict）；沒有或壞掉 ⇒ None。"""
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def config_exists() -> bool:
    try:
        return os.path.exists(_paths.HEARTBEAT_CONFIG)
    except Exception:
        return False


def ping_url_set() -> bool:
    """`heartbeat_config.json` 的 ping_url 有沒有填（只回有沒有，不回網址）。"""
    try:
        with open(_paths.HEARTBEAT_CONFIG, "r", encoding="utf-8") as f:
            return bool((json.load(f).get("ping_url") or "").strip())
    except Exception:
        return False


def _dt(v):
    try:
        return datetime.fromisoformat(v) if isinstance(v, str) and v else None
    except ValueError:
        return None


def _ago(delta) -> str:
    m = int(max(delta.total_seconds(), 0) // 60)
    if m < 90:
        return "%d 分鐘" % m
    h = m // 60
    return "%d 小時" % h if h < 48 else "%d 天" % (h // 24)


def assess(now: datetime = None, state=_READ) -> dict:
    """回 `{level, alert, status, since, seen_at, scheme, local_ok_at, ext_ok_at, ping_url_set, summary, problems}`。
    `alert`＝要不要寄信（每日檢查用）。`state` 不給就讀檔（測試可直接傳 dict 或 None）。永不丟例外。"""
    now = now or datetime.now()
    out = {"level": LEVEL_NA, "alert": False, "status": "", "since": "", "seen_at": "", "scheme": "", "local_ok_at": "",
           "ext_ok_at": "", "ping_url_set": False, "summary": "", "problems": []}
    try:
        st = read_state() if state is _READ else state
        cfg = config_exists()
        out["ping_url_set"] = ping_url_set()
        if not isinstance(st, dict):
            if not cfg:
                out["summary"] = "這台機器沒有心跳監控（沒有設定檔也沒有狀態檔）"
                return out
            out.update(level=LEVEL_WARN, alert=True, summary="有心跳設定檔，但沒有狀態檔：心跳排程可能從來沒有執行過")
            out["problems"].append(out["summary"])
            return out
        for k in ("status", "since", "seen_at", "scheme", "local_ok_at", "ext_ok_at"):
            out[k] = str(st.get(k) or "")
        status = out["status"]
        seen, since = _dt(out["seen_at"]), _dt(out["since"])
        if seen is None:
            out.update(level=LEVEL_WARN, alert=True, summary="心跳狀態檔讀得到，但 seen_at 缺少或格式不對（舊版心跳腳本？）")
            out["problems"].append(out["summary"])
            return out
        probs = []
        level, alert = LEVEL_OK, False
        if status == "ok":
            if (now - seen).total_seconds() > OK_STALE_HOURS * 3600:
                level, alert = LEVEL_ERROR, True
                probs.append("心跳狀態檔已經 %s 沒有更新（正常應每天更新）：心跳排程可能已停止執行" % _ago(now - seen))
        elif status in ("local_down", "ext_fail"):
            dur = (now - (since or seen)).total_seconds()
            level = LEVEL_WARN
            if dur > BAD_GRACE_MINUTES * 60:
                level, alert = LEVEL_ERROR, True
            if status == "local_down":
                probs.append("心跳檢查本機服務已 %s 判定「沒有回應」，但 app 正在執行：監控本身可能壞了（協定／埠不符？）" % _ago(now - (since or seen)))
            else:
                probs.append("心跳對外回報（healthchecks.io）已 %s 失敗：外部告警目前不可靠（本機對外網路？ping 網址？）" % _ago(now - (since or seen)))
        elif status == "ext_unset":
            level = LEVEL_WARN
            if (now - (since or seen)).total_seconds() > EXT_UNSET_ALERT_HOURS * 3600:
                alert = True
            probs.append("沒有設定對外回報網址（ping_url）：只有本機自查，沒有獨立於本機的告警")
        else:
            level, alert = LEVEL_WARN, True
            probs.append("心跳狀態值不認得：%r" % status)
        # 狀態是 ok 但檔案新鮮度剛好卡在邊界時 level 已在上面處理；其他狀態再補「狀態檔本身是不是也停了」
        if status != "ok" and (now - seen).total_seconds() > max(BAD_GRACE_MINUTES * 60, 2 * 3600):
            level, alert = LEVEL_ERROR, True
            probs.append("心跳狀態檔已 %s 沒有更新：心跳排程可能已停止執行" % _ago(now - seen))
        out.update(level=level, alert=bool(alert), problems=probs)
        out["summary"] = "；".join(probs) if probs else "心跳正常（本機 %s，上次對外回報成功 %s）" % (
            out["scheme"] or "?", out["ext_ok_at"] or "未知")
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("heartbeat_status.assess 失敗：%s", type(exc).__name__)
        out.update(level=LEVEL_WARN, alert=False, summary="讀取心跳狀態時發生錯誤（%s）" % type(exc).__name__)
        out["problems"].append(out["summary"])
        return out
