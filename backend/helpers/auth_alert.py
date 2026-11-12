# -*- coding: utf-8 -*-
"""登入鎖定告警（2026-11-12「登入失敗告警」票；外網 go-live 補上的門檻）。

[單位] helper:auth_alert    [層] L1    [穩定度] 實作
[公開介面] DEDUP_EVENT, HOURLY_CAP, WINDOW_SECONDS, flush_summary, on_lockout, reset_for_tests
[契約題] tests/test_auth_lockout_alert_2026_11_12.py
[不變式]
  ① 觸發點只有一個：`routers.auth._rl_fail` 的「達到鎖定」那一刻呼叫 `on_lockout`（不是每次失敗）。內容只有：嘗試過的帳號（最多 5 個、截斷、去控制字元）、
     來源 IP、失敗次數、鎖定到幾點。**絕不放密碼、驗證碼、token。**
  ② 節流（兩層，都在記憶體、同步判斷、不碰資料庫與網路）：
     a. 同一個鎖定範圍（IPv4 原樣／IPv6 /64＝`_rl_key`）在它的鎖定期間只通知一次（`_alerted[key]`＝鎖定結束的 monotonic 時間）。
     b. 全系統每個滾動 `WINDOW_SECONDS`（1 小時）最多 `HOURLY_CAP`（10）則；超過的不各自發送，記進 `_suppressed`，等視窗騰出空位時合併成**一則摘要**
        （件數＋最多 5 個 IP）。⇒ 每小時最多 `HOURLY_CAP`+1 則、每則最多給 N 位收件人，LINE 額度的最壞耗用有上界（額度告警照常，見 ⑤）。
     行程重啟會清空這些記憶體狀態（鎖定本身存在 DB，重啟後仍有效）：最壞情況是重啟後同一個仍在鎖定的 IP 再被鎖一次時多通知一次，可接受；
     尚未送出的摘要隨行程結束而遺失（只是彙總，每一則個別事件在上限內都已即時發出；超過上限的細節仍在稽核與 logger.warning）。
  ③ 通知不能拖慢登入：`on_lockout` 只做記憶體判斷，實際發送一律丟背景執行緒（`_spawn`）；任何例外只記 log，**永不丟給呼叫端**。
  ④ 兩個通道各自發送、各自失敗：`email_notify.send_registered("auth_lockout", to_group=True)` 一次呼叫，裡面
     - LINE（**獨立通道**，2026-11-12 起所有已接線事件皆然）：收件人＝`helpers.event_audience.group_usernames`（T80 收件設定：登記的預設群組＝超級管理員，
       可覆寫成僅超管／指定帳號＋角色；**不要求 Email**）⇒ `line_recipients.filter_usernames`（LINE 角色允許清單＋本人 LINE 勾選）⇒ 已綁定者；
       公司層 LINE 事件開關（預設關，管理員在 LINE 設定頁勾選）與 LINE 啟用／token 同樣適用。背景執行緒，先於信件處理。
     - Email：同一份收件設定，只寄有 Email 且未退訂的人。
     同一個人兩個通道都有就兩邊都發；Email 退訂與 LINE 勾選互不影響。
  ⑤ LINE 額度：走 `line_notify.notify_users → push_async`，推播成功後的 `line_quota.after_push`（用量刷新與 T80 額度告警）照常觸發；本單位不自己計額度。
  ⑥ 已知限制：LINE 公司層事件開關預設關（沿用 T80「預設全關、逐類勾選」）——上線後要有人把「登入失敗鎖定告警」勾起來才會有 LINE；Email 不受此限。
"""
import logging
import re
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DEDUP_EVENT = "auth_lockout"
#: 全系統每個滾動視窗最多發幾則（超過合併成一則摘要）。每則最多給 N 位收件人，所以 LINE 最壞耗用 ≤ (HOURLY_CAP+1)×N／小時
HOURLY_CAP = 10
WINDOW_SECONDS = 3600
_MAX_NAMES = 5
_MAX_SUMMARY_IPS = 5

_lock = threading.Lock()
_alerted = {}          # 鎖定範圍 key -> 鎖定結束的 monotonic 時間（該時間前不再通知）
_sent_at = []          # 最近一個視窗內「已發出」的 monotonic 時間（遞增）
_suppressed = []       # 超過上限而暫存的事件 [{"ip", "key", "names"}]
_timer = None          # 排定的摘要計時器（同時只有一個）


def reset_for_tests() -> None:
    """測試用：清掉所有記憶體狀態（含計時器）。"""
    global _timer
    with _lock:
        _alerted.clear()
        _sent_at.clear()
        _suppressed.clear()
        if _timer is not None:
            _timer.cancel()
        _timer = None


def _clean(s, limit: int = 64) -> str:
    """攻擊者可控的字串（嘗試的帳號名）進通知前：去控制字元（含換行）、截斷。"""
    return re.sub(r"[\x00-\x1f\x7f  \x85]+", " ", str(s or "")).strip()[:limit]


def _spawn(fn, *args) -> threading.Thread:
    """背景執行（daemon）。測試可替換成同步版。"""
    t = threading.Thread(target=fn, args=args, daemon=True, name="auth-alert")
    t.start()
    return t


def _deliver(title: str, rows: list, reason: str) -> None:
    """一次呼叫 `email_notify.send_registered`：Email 與 LINE 在裡面各自獨立發送（LINE 先、背景、不看 Email；信件任何例外都不會讓 LINE 漏發）。
    這裡再包一層 try：任何一邊炸了都只記 log，**永不丟例外**。"""
    try:
        from . import email_notify as _en
        _en.send_registered("auth_lockout", title=title, rows=rows, to_group=True, reason=reason,
                            badge_text="安全告警", badge_color="#DC2626")
    except Exception as exc:  # noqa: BLE001
        logger.warning("登入鎖定告警：發送失敗（%s）", type(exc).__name__)


def _schedule_summary_locked(now: float) -> None:
    """（持有 `_lock`）排定摘要：等視窗最舊的一則過期、騰出空位時送。同時只排一個。"""
    global _timer
    if _timer is not None or not _sent_at:
        return
    delay = max(1.0, _sent_at[0] + WINDOW_SECONDS - now + 1.0)
    _timer = threading.Timer(delay, flush_summary)
    _timer.daemon = True
    _timer.start()


def _prune_locked(now: float) -> None:
    while _sent_at and now - _sent_at[0] >= WINDOW_SECONDS:
        _sent_at.pop(0)
    for k in [k for k, until in _alerted.items() if until <= now]:
        del _alerted[k]


def on_lockout(key: str, ip: str, usernames, fails: int, lock_seconds: int, now: float = None, scope: str = "ip") -> str:
    """登入鎖定的那一刻呼叫。`scope`："ip"（預設，來源 IP 鎖定）或 "account"（單一帳號鎖定：`key` 由呼叫端給，例如 "acct:<帳號>"，只影響標題與欄位文字；去重與每小時上限共用同一套）。回傳處理結果（給測試與 log）：`sent`／`dedup`／`capped`／`error`。**永不丟例外、不阻塞。**"""
    try:
        mono = time.monotonic() if now is None else now
        names = [n for n in dict.fromkeys(_clean(u) for u in (usernames or [])) if n][:_MAX_NAMES]
        with _lock:
            _prune_locked(mono)
            if key in _alerted:                       # 同一範圍鎖定期間只通知一次
                return "dedup"
            _alerted[key] = mono + max(int(lock_seconds), 1)
            if len(_sent_at) >= HOURLY_CAP:           # 全系統上限：先記起來，之後合併成摘要
                _suppressed.append({"ip": _clean(ip, 45), "key": _clean(key, 64), "names": names})
                _schedule_summary_locked(mono)
                logger.warning("登入鎖定告警超過每小時上限（%d）：暫存 %s，稍後合併成摘要", HOURLY_CAP, _clean(ip, 45))
                return "capped"
            _sent_at.append(mono)
        until = datetime.now() + timedelta(seconds=max(int(lock_seconds), 1))
        acct = scope == "account"
        if acct:
            rows = [("帳號", "、".join(names) if names else "（未知）"), ("觸發來源 IP", _clean(ip, 45) or "（未知）")]
        else:
            rows = [("來源 IP", _clean(ip, 45) or "（未知）")]
            if _clean(key, 64) and _clean(key, 64) != _clean(ip, 45):
                rows.append(("鎖定範圍", _clean(key, 64)))
            rows.append(("嘗試的帳號", "、".join(names) if names else "（無／未知）"))
        rows += [("連續失敗", "%d 次" % int(fails)),
                 ("鎖定至", "%s（%d 分鐘）" % (until.strftime("%m/%d %H:%M"), max(int(lock_seconds), 1) // 60))]
        _spawn(_deliver, "帳號因失敗過多被暫時鎖定" if acct else "登入失敗過多，來源已被鎖定", rows,
               ("有帳號連續登入失敗 %d 次，已被暫時鎖定。" if acct else "有來源連續登入失敗 %d 次，已被暫時鎖定。") % int(fails))
        return "sent"
    except Exception as exc:  # noqa: BLE001
        logger.warning("登入鎖定告警處理失敗（不影響登入）：%s", type(exc).__name__)
        return "error"


def flush_summary(now: float = None) -> str:
    """把超過上限而暫存的事件合併成一則摘要送出（計時器到點呼叫；測試也可直接呼叫）。回 `sent`／`empty`／`error`。"""
    global _timer
    try:
        mono = time.monotonic() if now is None else now
        with _lock:
            _timer = None
            _prune_locked(mono)
            if not _suppressed:
                return "empty"
            batch = list(_suppressed)
            _suppressed.clear()
            _sent_at.append(mono)                     # 摘要本身也算一則（視窗有空位才會走到這裡；若仍滿則照樣送——摘要每小時至多一則）
        ips = list(dict.fromkeys(b["ip"] for b in batch if b["ip"]))
        shown = "、".join(ips[:_MAX_SUMMARY_IPS]) + ("…等 %d 個來源" % len(ips) if len(ips) > _MAX_SUMMARY_IPS else "")
        rows = [("期間內另有鎖定", "%d 次" % len(batch)), ("來源 IP", shown or "（未知）")]
        _spawn(_deliver, "登入失敗鎖定摘要（超過每小時上限的合併通知）", rows,
               "過去一小時登入鎖定次數超過上限（%d），其餘合併成這一則。請檢查稽核紀錄的「登入失敗」。" % HOURLY_CAP)
        return "sent"
    except Exception as exc:  # noqa: BLE001
        logger.warning("登入鎖定摘要處理失敗：%s", type(exc).__name__)
        return "error"
