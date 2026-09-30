# -*- coding: utf-8 -*-
"""整個行程的假時鐘（pytest plugin；邊界日矩陣 boundary_days.py 用）：`pytest -p fake_clock`，環境變數 MOTRIX_FAKE_NOW=YYYY-MM-DDTHH:MM:SS。

做法＝**平移**：行程起算時，真實時間與 MOTRIX_FAKE_NOW 差 delta；之後
`datetime.date.today()`／`datetime.datetime.now()／today()／utcnow()`、`time.time()`、`time.localtime()／gmtime()／ctime()／strftime()` 的預設值
都是「真實時間 ＋ delta」——時鐘照常往前走（等待逾時、鎖年齡、排程計時不會卡住），只是從另一天開始。
23:59:30 起跑的題會在跑的途中真的跨午夜，這正是要的。

## 限制（誠實寫在這裡，紅燈要人看，不是自動判定產品有 bug）
- 只換**本行程**的 Python 層：SQLite 的 `datetime('now')`、子行程（伺服器行程、PowerShell）、檔案 mtime 仍是真實時間。
  用檔案 mtime 對「今天」的題在這裡可能假紅——對照 boundary_days 的 control（真實時鐘）那一輪判斷。
- `datetime.datetime`／`datetime.date` 被換成子類別：在本 plugin 載入**之前**就 `from datetime import date` 的模組拿到原類別（不平移）。
  所以一定要用 `-p fake_clock`（pytest 最早載入的 plugin）。
- 不驅動 `time.monotonic()`／`perf_counter()`（逾時計算不受影響）。
"""
import datetime as _dt
import os
import time as _time

ENV = "MOTRIX_FAKE_NOW"
_REAL_DATE, _REAL_DATETIME = _dt.date, _dt.datetime
_REAL_TIME, _REAL_LOCALTIME, _REAL_GMTIME = _time.time, _time.localtime, _time.gmtime
DELTA = 0.0           # 秒；install() 設定


def parse(raw):
    """'YYYY-MM-DDTHH:MM:SS'（也收 'YYYY-MM-DD HH:MM:SS'、'YYYY-MM-DD'＝當天 12:00）⇒ datetime；不合法 ⇒ ValueError。"""
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return _REAL_DATETIME.strptime(raw, fmt)
        except ValueError:
            pass
    try:
        return _REAL_DATETIME.strptime(raw, "%Y-%m-%d").replace(hour=12)
    except ValueError:
        raise ValueError("%s=%r 不是 YYYY-MM-DDTHH:MM:SS" % (ENV, raw)) from None


def delta_to(target, real_now=None):
    """要平移多少秒才會讓 real_now 變成 target（本地時間）。"""
    real_now = real_now or _REAL_DATETIME.now()
    return (target - real_now).total_seconds()


class FakeDatetime(_REAL_DATETIME):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(_REAL_TIME() + DELTA, tz)

    @classmethod
    def today(cls):
        return cls.now()

    @classmethod
    def utcnow(cls):
        return cls.fromtimestamp(_REAL_TIME() + DELTA, _dt.timezone.utc).replace(tzinfo=None)


class FakeDate(_REAL_DATE):
    @classmethod
    def today(cls):
        return cls.fromtimestamp(_REAL_TIME() + DELTA)


def _fake_time():
    return _REAL_TIME() + DELTA


def _fake_localtime(secs=None):
    return _REAL_LOCALTIME(_fake_time() if secs is None else secs)


def _fake_gmtime(secs=None):
    return _REAL_GMTIME(_fake_time() if secs is None else secs)


def install(target):
    """把本行程的時鐘平移到 target 起算。回傳 delta 秒。重複呼叫以最新的 target 為準。"""
    global DELTA
    DELTA = delta_to(target)
    _dt.datetime, _dt.date = FakeDatetime, FakeDate
    _time.time, _time.localtime, _time.gmtime = _fake_time, _fake_localtime, _fake_gmtime
    return DELTA


def uninstall():
    global DELTA
    DELTA = 0.0
    _dt.datetime, _dt.date = _REAL_DATETIME, _REAL_DATE
    _time.time, _time.localtime, _time.gmtime = _REAL_TIME, _REAL_LOCALTIME, _REAL_GMTIME


def pytest_configure(config):
    raw = os.environ.get(ENV)
    if raw:
        install(parse(raw))             # 不合法 ⇒ ValueError ⇒ pytest 整輪不開跑（不靜默退回真實時間）
        config._fake_clock_banner = "fake_clock：%s（平移 %+.0f 秒）" % (raw, DELTA)


def pytest_report_header(config):
    return getattr(config, "_fake_clock_banner", None)


def pytest_unconfigure(config):
    if getattr(config, "_fake_clock_banner", None):
        uninstall()
