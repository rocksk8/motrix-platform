# -*- coding: utf-8 -*-
"""LINE 本月訊息額度的常駐監控與門檻告警（2026-11-12；PM 裁示 D3／D4／D5／D6）。

[單位] helper:line_quota    [層] L1    [穩定度] 實作
[公開介面] CACHE_SECONDS, DEFAULT_THRESHOLDS, MAX_THRESHOLDS, RESERVE_PERCENT, STATE_KEY, after_push, cached_percent, check_and_alert, evaluate, month_key, normalize_thresholds, refresh, reserve_paused, snapshot, thresholds
[契約題] tests/test_line_quota_2026_11_12.py
[不變式]
  ① 用量**一律以 LINE 回的 `totalUsage` 為準**（`line_notify.quota()`：兩支唯讀 GET，不耗額度）；本機不自己計數（會跟 LINE 漂移，LINE 控制台手動發送也耗額度）。
  ② 取得用量的觸發點只有三個，**沒有常駐輪詢**（LINE API 呼叫與硬碟寫入都要省）：
     設定頁載入（`snapshot`，5 分鐘內用快取）／推播成功後（`after_push`，去抖動：距上次刷新不足 `CACHE_SECONDS` 就排一個延後執行，同時只排一個）／每日 08:00 備援（`system_checks._check_line_quota`）。
  ③ 快取的「何時刷新過」放行程記憶體；持久狀態 `system_settings.line_quota_state` 只在 **月份／用量／上限／已警示門檻** 有變時才寫（不是每次刷新都寫）。
  ④ 告警：用量百分比跨過任一門檻 ⇒ 寄一封 `line_quota_warning` 給最高管理者。**同一門檻同一個月只寄一次**（`alerted`）；一次跨過多個門檻只寄一封（講最高那個），
     而且**這次跨過的所有門檻**都記為已警示；**等寄送結果才記**（`notify_line_quota_warning` 回 False＝沒寄成、不記、下次重試）。
     寄信那一段在 `_lock` 裡（推播後的背景執行緒與每日備援可能同時跑，不可雙寄）。
  ⑤ 換月重置：狀態的 `month` ≠ 當月 ⇒ 清 `alerted`（同月內回落見 ⑪）。用量降到門檻下只更新狀態，不寄信。
     門檻被改：`alerted` 只留仍在新門檻清單內的；新增且目前已超過的門檻，下一次評估補寄一次。
  ⑥ 沒有上限（`limit is None`，無限方案）或讀不到用量（沒 token／LINE 連不上）⇒ 不告警；`snapshot` 回 `ok=False`＋原因，永不丟例外。
  ⑦ 門檻存 `line_notify.quota_thresholds`（百分比整數，1～`MAX_THRESHOLDS` 個，各 1～100，不重複，存成遞增）；缺省／壞值 ⇒ `DEFAULT_THRESHOLDS`。
  ⑧ 100% 時 LINE 回 429（`line_notify` 歸為 transient_fail）：本單位只告警，**不**自動停推播（PM 裁示 D6）。
  ⑨ 狀態的「讀→改→寫」只由 `_state_lock`（短鎖，**不包網路呼叫與寄信**）保護：設定頁的 `refresh` 與告警的記旗標不會互相蓋掉（K 審 F1）；
     鎖序固定 `_lock`（評估＋寄信）→ `_state_lock`，`refresh` 只拿 `_state_lock`，不會死鎖，也不會被寄信等待堵住。
  ⑩ LINE 回的用量／上限欄位缺失或型別不對＝讀不到（`ok=False`），不補 0、不當無上限（K 審 F2；`line_notify.quota` 與 `refresh` 兩處都擋）。
  ⑪ 同月內用量變小：只清掉「已回落到門檻以下再多 `_HYSTERESIS_POINTS` 個百分點」的已警示門檻（LINE 統計有延遲，小幅回落不算新週期；K 審 F3）；換月清空。
  ⑫ 告警與備援檢查只在「LINE 已啟用且本機允許對外發送」時進行（與 `line_notify.push` 同條件）；設定頁的用量條不受影響（有 token 就能看）。
     讀取失敗會被負快取 `_FAIL_CACHE_SECONDS` 秒（設定頁自動載入不會一直重打；手動「重新整理」會略過快取）。
"""
import logging
import threading
from datetime import datetime

from .settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

STATE_KEY = "line_quota_state"
DEFAULT_THRESHOLDS = (80, 100)
MAX_THRESHOLDS = 5
#: 用量快取秒數；推播後去抖動也用它（距上次刷新不足這麼久就延後到滿 5 分鐘再刷新）
CACHE_SECONDS = 300
#: 推播成功後至少等這麼久才讀用量（LINE 的 consumption 統計有些許延遲）
_SETTLE_SECONDS = 5
#: 同月內用量回落：已警示門檻要降到「門檻 − 這麼多個百分點」以下才算回落、才清掉（遲滯）
_HYSTERESIS_POINTS = 5
#: 讀取失敗（LINE 連不上、欄位缺失）的負快取秒數
_FAIL_CACHE_SECONDS = 60

def _fp() -> str:
    """目前 channel access token 的指紋（只用來比對「快取是不是用同一個 token 讀的」；不含也不外露 token）。"""
    try:
        import hashlib
        from . import line_notify as _ln
        tk = str(_ln._cfg().get("channel_access_token") or "")
        return hashlib.sha256(tk.encode("utf-8")).hexdigest()[:16] if tk else ""
    except Exception:  # noqa: BLE001
        return ""


_lock = threading.Lock()          # 評估＋寄信＋記旗標（避免雙寄）
_state_lock = threading.Lock()    # 狀態的讀→改→寫（短鎖；不包網路呼叫與寄信）
_mem_lock = threading.Lock()
_mem = {"checked_at": None, "failed_at": None, "error": "", "fp": None}       # 行程內：最近一次「成功讀到 LINE 用量」／「讀取失敗」的時間；fp＝當時用的 token 指紋
_pending = False


def month_key(now: datetime = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m")


def normalize_thresholds(v) -> list:
    """驗證並整理門檻：`[int…]`，1～MAX 個，各 1～100，不重複 ⇒ 遞增 list。不合法 ⇒ `ValueError`。布林不算整數。"""
    bad = ValueError("額度告警門檻必須是 1～%d 個 1～100 的整數百分比（不可重複）" % MAX_THRESHOLDS)
    if not isinstance(v, (list, tuple)) or not (1 <= len(v) <= MAX_THRESHOLDS):
        raise bad
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, int) or not (1 <= x <= 100):
            raise bad
        out.append(x)
    if len(set(out)) != len(out):
        raise bad
    return sorted(out)


def thresholds() -> list:
    """目前生效的門檻（缺省或壞值 ⇒ 預設）。"""
    c = _get_setting("line_notify", {}) or {}
    try:
        return normalize_thresholds(c.get("quota_thresholds")) if isinstance(c, dict) and "quota_thresholds" in c else list(DEFAULT_THRESHOLDS)
    except ValueError:
        return list(DEFAULT_THRESHOLDS)


def _state() -> dict:
    v = _get_setting(STATE_KEY, {}) or {}
    return v if isinstance(v, dict) else {}


def _int_or_none(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def evaluate(used, limit, ths, alerted) -> dict:
    """純函式。`crossed`＝目前已達的門檻；`new`＝其中還沒警示過的；`percent`＝用量百分比（無上限／讀不到 ⇒ None，不告警）。
    用整數比較（`used*100 >= t*limit`），不受浮點誤差影響。"""
    used, limit = _int_or_none(used), _int_or_none(limit)
    if used is None or not limit:
        return {"percent": None, "crossed": [], "new": []}
    crossed = [t for t in sorted(ths) if used * 100 >= t * limit]
    done = set(alerted or [])
    return {"percent": used * 100.0 / limit, "crossed": crossed, "new": [t for t in crossed if t not in done]}


def _level(percent, ths) -> str:
    if percent is None:
        return "unknown"
    ths = sorted(ths)
    if ths and percent >= ths[-1]:
        return "alert"
    if ths and percent >= ths[0]:
        return "warn"
    return "ok"


def _view(st: dict, ths: list, ok: bool = True, error: str = "") -> dict:
    limit = _int_or_none(st.get("limit"))
    used = _int_or_none(st.get("used"))
    ev = evaluate(used, limit, ths, st.get("alerted"))
    return {"ok": ok, "error": error, "month": str(st.get("month") or ""), "used": used, "limit": limit, "unlimited": ok and used is not None and limit is None,
            "percent": ev["percent"], "level": ("unlimited" if (ok and used is not None and limit is None) else _level(ev["percent"], ths)),
            "thresholds": list(ths), "alerted": [t for t in (st.get("alerted") or []) if t in ths], "checked_at": str(st.get("checked_at") or "")}


def refresh(now: datetime = None) -> dict:
    """向 LINE 讀本月用量並更新狀態；回 `snapshot` 同形狀的 view。讀不到（沒 token／連不上）⇒ `ok=False`＋原因，狀態不動。永不丟例外。"""
    now = now or datetime.now()
    ths = thresholds()
    try:
        from . import line_notify as _ln
        fp = _fp()                                        # 讀之前先取指紋：讀的途中換 token ⇒ 這次結果不算新 token 的快取
        q = _ln.quota()                                   # 網路呼叫在任何鎖之外
        used = _int_or_none(q.get("used")) if q.get("ok") else None
        limit = _int_or_none(q.get("limit")) if (q.get("ok") and q.get("limit") is not None) else None
        if not q.get("ok") or used is None or (q.get("limit") is not None and limit is None):
            err = str(q.get("error") or "LINE 回傳的用量資料不完整")      # 欄位缺失／型別不對＝讀不到（K 審 F2：不補 0）
            with _mem_lock:
                _mem["failed_at"], _mem["error"], _mem["fp"] = now, err, fp
            return _view(_state(), ths, ok=False, error=err)
        month = month_key(now)
        with _state_lock:                                 # 讀→改→寫：與 check_and_alert 記旗標互斥（K 審 F1）
            prev = _state()
            alerted = [t for t in (prev.get("alerted") or []) if isinstance(t, int) and t in ths]
            if prev.get("month") != month:
                alerted = []                              # 換月：新週期
            elif limit:
                # 同月內百分比回落（LINE 重置／升級方案放大上限／統計延遲）：只清「已降到門檻 − 遲滯」以下的，小幅回落不算新週期（K 審 F3）
                alerted = [t for t in alerted if used * 100 >= (t - _HYSTERESIS_POINTS) * limit]
            new = {"month": month, "used": used, "limit": limit, "type": str(q.get("type") or ""), "alerted": alerted,
                   "checked_at": now.isoformat(timespec="seconds")}
            with _mem_lock:
                _mem["checked_at"], _mem["failed_at"], _mem["error"], _mem["fp"] = now, None, "", fp
            cmp_keys = ("month", "used", "limit", "type", "alerted")
            if any(prev.get(k) != new[k] for k in cmp_keys):
                _set_setting(STATE_KEY, new)              # 只有內容變了才寫；checked_at 只在寫入時順便更新（新鮮度看記憶體）
                return _view(new, ths)
            return _view({**prev, "checked_at": new["checked_at"]}, ths)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 額度刷新失敗：%s", type(exc).__name__)
        return _view(_state(), ths, ok=False, error="讀取用量時發生錯誤（%s）" % type(exc).__name__)


def snapshot(max_age: int = CACHE_SECONDS, now: datetime = None, force: bool = False) -> dict:
    """設定頁用：5 分鐘內（`max_age`）用快取，過期才打 LINE。永不丟例外。"""
    now = now or datetime.now()
    try:
        with _mem_lock:
            at, failed_at, err, fp = _mem["checked_at"], _mem["failed_at"], _mem["error"], _mem["fp"]
        if fp != _fp():
            at = failed_at = None                         # token 換了／剛設好：舊的成功與失敗快取都作廢（閘門 e2e 紅燈根因：負快取不認 token）
        st = _state()
        if not force and at is not None and st.get("month") == month_key(now) and 0 <= (now - at).total_seconds() < max_age:
            return _view(st, thresholds())
        if not force and failed_at is not None and 0 <= (now - failed_at).total_seconds() < _FAIL_CACHE_SECONDS:
            return _view(st, thresholds(), ok=False, error=err)          # 剛失敗過：負快取（K 審 F5）
        return refresh(now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 額度 snapshot 失敗：%s", type(exc).__name__)
        return _view({}, list(DEFAULT_THRESHOLDS), ok=False, error="讀取用量時發生錯誤（%s）" % type(exc).__name__)


def check_and_alert(now: datetime = None, max_age: int = CACHE_SECONDS, force: bool = False) -> dict:
    """讀用量（快取內就不重打）→ 跨過尚未警示的門檻就寄信 → 寄成功才記。回 `{alerted: bool, new: [...], view}`。永不丟例外。"""
    now = now or datetime.now()
    out = {"alerted": False, "new": [], "view": None}
    try:
        if not _active():
            return out                                    # LINE 沒啟用／本機不允許對外發送：不連 LINE、不寄信（K 審 F4）
        with _lock:
            v = snapshot(max_age, now, force)
            out["view"] = v
            if not v["ok"] or v["limit"] is None:
                return out
            st = _state()
            ths = v["thresholds"]
            ev = evaluate(v["used"], v["limit"], ths, st.get("alerted"))
            out["new"] = ev["new"]
            if not ev["new"]:
                return out
            from .email_notify import notify_line_quota_warning
            may_mark = notify_line_quota_warning(v["used"], v["limit"], max(ev["new"]), ths, v["month"])
            if may_mark is False:                         # 沒收件人／暫時失敗：不記，下次（推播後／明天 08:00）重試
                logger.warning("LINE 額度告警沒有寄出（已達 %s%%），下次重試", max(ev["new"]))
                return out
            with _state_lock:                             # 重讀再寫：不蓋掉同時間 refresh 寫的用量（K 審 F1）
                st = _state()
                st["alerted"] = sorted(set(st.get("alerted") or []) | set(ev["crossed"]))      # 這次跨過的所有門檻都記
                _set_setting(STATE_KEY, st)
            out["alerted"] = True
            logger.error("LINE 本月額度已達 %.0f%%（%s / %s），已通知最高管理者", ev["percent"], v["used"], v["limit"])
            return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE check_and_alert 失敗：%s", type(exc).__name__)
        return out


def _run_after_push() -> None:
    global _pending
    try:
        check_and_alert(force=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 推播後額度檢查失敗：%s", type(exc).__name__)
    finally:
        with _mem_lock:
            _pending = False


def _active() -> bool:
    """LINE 已啟用（有 token）且本機允許對外發送（同 `line_notify.push` 的條件；開發機標記會擋）。永不丟例外。"""
    try:
        from . import line_notify as _ln
        if not _ln.enabled():
            return False
        try:
            from .email_notify import email_send_policy
            allowed, _why = email_send_policy()
        except Exception:  # noqa: BLE001
            return True       # 讀不到政策＝維持預設（與 line_notify._machine_may_send 同理）
        return bool(allowed)
    except Exception:  # noqa: BLE001
        return False


#: 額度保留（使用者 2026-11-12 裁示）：本月用量達這個百分比後，非 critical 的事件暫停推播（critical 照發）。
RESERVE_PERCENT = 90


def cached_percent(now: datetime = None):
    """本月用量百分比，**只讀持久狀態、不連 LINE**（額度保留判斷用；狀態由推播後刷新／設定頁／每日 08:00 備援更新）。
    狀態不是本月、沒有上限（無限方案）、讀不到 ⇒ None（＝不暫停）。永不丟例外。"""
    try:
        now = now or datetime.now()
        st = _state()
        if st.get("month") != month_key(now):
            return None
        return evaluate(st.get("used"), st.get("limit"), [], None)["percent"]
    except Exception:  # noqa: BLE001
        return None


def reserve_paused(now: datetime = None) -> bool:
    """用量已達 `RESERVE_PERCENT` ⇒ True（呼叫端對非 critical 事件暫停推播）。讀不到用量 ⇒ False（不因為讀不到就擋）。"""
    p = cached_percent(now)
    return p is not None and p >= RESERVE_PERCENT


def after_push(now: datetime = None) -> None:
    """推播成功後呼叫：背景、去抖動、永不丟例外。距上次刷新不足 `CACHE_SECONDS` ⇒ 排到滿 5 分鐘（至少等 `_SETTLE_SECONDS`）；同時只排一個。"""
    global _pending
    try:
        now = now or datetime.now()
        if not _active():
            return
        with _mem_lock:
            if _pending:
                return
            at = _mem["checked_at"] if _mem["fp"] == _fp() else None
            age = (now - at).total_seconds() if at is not None else CACHE_SECONDS
            delay = max(float(_SETTLE_SECONDS), CACHE_SECONDS - max(age, 0.0))
            _pending = True
        t = threading.Timer(delay, _run_after_push)
        t.daemon = True
        t.name = "line-quota"
        t.start()
    except Exception as exc:  # noqa: BLE001
        with _mem_lock:
            _pending = False
        logger.warning("LINE after_push 排程失敗：%s", type(exc).__name__)
