"""B54-S2（D 稽核第十五班緊急包；2026-09-28 A）：archive 的每日／週備份與 `_ensure_archive_dirs` 不可以在啟動路徑上同步跑。

原本 `main.py` 同步呼叫 `_ensure_archive_dirs()`、`_schedule_daily()`（第一件事就是整庫快照＋JSON 匯出＋月備份＋鏡像）、
`_schedule_weekly()`，全部碰雲端存檔路徑 ⇒ 主持實測 import main 被卡 16～24 秒；雲端硬碟掛著但卡住時，會重演 8b04d99d
「好的包因 port 沒在聽而被自動回滾」。形狀照 geo／tender（B54）：立即返回、第一輪在背景 Timer、重排在 finally。

守門：①兩支排程呼叫立即返回，第一輪不在呼叫者的執行緒裡跑　②第一輪確實在背景跑（每日：先確認目錄再備份），
      跑完或丟例外都照樣排下一輪　③真的 `import main`（子行程、排程全開、所有排程工作都換成「睡 N 秒」、
      含確認雲端目錄卡住）⇒ import 在時限內完成（反向控制：改回同步 ⇒ ≥ N 秒而紅）
"""
import time

import pytest

import archive


class _RecordingTimer:
    """替身 `threading.Timer`：只記下排了什麼，不啟動（決定性，不留執行緒）。"""

    def __init__(self, interval, function, *args, **kwargs):
        self.interval = interval
        self.function = function
        self.daemon = False
        self.started = False
        _RecordingTimer.made.append(self)

    def start(self):
        self.started = True


@pytest.fixture
def timers(monkeypatch):
    _RecordingTimer.made = []
    monkeypatch.setattr(archive.threading, "Timer", _RecordingTimer)
    return _RecordingTimer.made


@pytest.fixture
def calls(monkeypatch):
    got = []
    monkeypatch.setattr(archive, "_ensure_archive_dirs", lambda: got.append("ensure"))
    monkeypatch.setattr(archive, "_daily_backup", lambda: got.append("daily"))
    monkeypatch.setattr(archive, "_cleanup_sessions", lambda: got.append("sessions"))
    monkeypatch.setattr(archive, "_weekly_backup", lambda: got.append("weekly"))
    return got


def test_daily_returns_immediately_and_runs_nothing_inline(timers, calls):
    t0 = time.monotonic()
    archive._schedule_daily()
    assert time.monotonic() - t0 < 1.0
    assert calls == [], "每日第一輪在呼叫者的執行緒裡同步跑了 ⇒ import main 會被雲端存檔路徑拖住"
    assert len(timers) == 1 and timers[0].started and timers[0].daemon
    assert timers[0].interval == archive._DAILY_FIRST_DELAY_SECONDS < archive._DAILY_INTERVAL_SECONDS


def test_daily_first_round_ensures_dirs_then_backs_up_and_reschedules(timers, calls):
    archive._schedule_daily()
    timers[0].function()
    assert calls == ["ensure", "daily", "sessions"], "第一輪：先確認雲端目錄（提早告警）再備份"
    assert len(timers) == 2 and timers[1].started and timers[1].daemon
    assert timers[1].interval == archive._DAILY_INTERVAL_SECONDS
    timers[1].function()
    assert calls[3:] == ["daily", "sessions"], "之後每輪只備份（不再每 2 小時確認一次目錄）"
    assert len(timers) == 3 and timers[2].function is timers[1].function


def test_daily_round_raising_still_reschedules(timers, monkeypatch):
    """重排在 finally：一輪丟例外（含確認目錄丟例外）⇒ 照樣排下一輪（原本丟一次就靜默死亡）。"""
    monkeypatch.setattr(archive, "_ensure_archive_dirs", lambda: 1 / 0)
    monkeypatch.setattr(archive, "_daily_backup", lambda: 1 / 0)
    archive._schedule_daily()
    timers[0].function()                     # 不可以把例外往外丟（Timer 執行緒裡丟出去＝排程停了）
    assert len(timers) == 2 and timers[1].interval == archive._DAILY_INTERVAL_SECONDS


def test_weekly_returns_immediately_then_runs_in_background_and_reschedules(timers, calls, monkeypatch):
    archive._schedule_weekly()
    assert calls == [] and len(timers) == 1 and timers[0].daemon
    assert timers[0].interval == archive._WEEKLY_FIRST_DELAY_SECONDS < archive._WEEKLY_INTERVAL_SECONDS
    timers[0].function()
    assert calls == ["weekly"] and timers[1].interval == archive._WEEKLY_INTERVAL_SECONDS
    monkeypatch.setattr(archive, "_weekly_backup", lambda: 1 / 0)
    timers[1].function()
    assert len(timers) == 3, "週備份丟例外 ⇒ 照樣排下一輪"


def test_main_no_longer_calls_ensure_archive_dirs_on_the_startup_path():
    import ast
    from pathlib import Path
    src = (Path(archive.__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
    called = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
              and getattr(n.func, "id", None) == "_ensure_archive_dirs"]
    assert not called, "main.py 仍同步呼叫 _ensure_archive_dirs()（雲端碟卡住時拖住 import main）"


# ── 整合：真的 `import main`（子行程、排程全開、所有排程工作都慢）──────────────────────
#
# 形狀照 tests/test_geocode_warm_async_2026_09_28.py 的整合題，但 archive 是**真的**（B54 那題整支換成空殼，
# 所以 archive 的同步呼叫從來沒被量過）：只把會碰雲端存檔路徑的工作換成「睡 _SLOW 秒」，首輪延遲設 0 讓背景真的起跑；
# cloud_archive_enabled 固定 False（保險：子行程沒有 conftest 的隔離，任何漏網的寫入都不可以碰到雲端碟）。

_SLOW = 45

_IMPORT_MAIN_SCRIPT = '''
import os, sys, tempfile, time, threading
import db
_tmp = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_tmp, "t.db")
db.DEMO_DB_PATH = os.path.join(_tmp, "d.db")
# 首次安裝帳密檔導到暫存（子行程沒有 conftest 的隔離；不導的話 init_default_admin 會寫進這棵樹，稽核 D AB-S1）
import helpers.auth as _auth, helpers.startup as _startup
_auth._CREDENTIALS_FILE = os.path.join(_tmp, "initial_admin_credentials.txt")
_startup._DEMO_CREDENTIALS_FILE = os.path.join(_tmp, "initial_demo_credentials.txt")
# 第二十班交會（B55 S2）：main 在排程閘門內寫 logs/module_states.json（core.paths.LOGS_DIR，呼叫時讀）⇒ 一併導到暫存
import core.paths as _core_paths
_core_paths.LOGS_DIR = os.path.join(_tmp, "logs")
os.makedirs(_core_paths.LOGS_DIR, exist_ok=True)

import archive
archive.cloud_archive_enabled = lambda: False
started = {}
def _slow(name):
    def f(*a, **kw):
        started[name] = True
        time.sleep(%(slow)d)
    return f
archive._ensure_archive_dirs = _slow("ensure")      # 雲端路徑在但卡住
archive._daily_backup = _slow("daily")
archive._weekly_backup = _slow("weekly")
archive._DAILY_FIRST_DELAY_SECONDS = 0
archive._WEEKLY_FIRST_DELAY_SECONDS = 0

import helpers.daily_checks as _dck
_dck.run_once = _slow("daily_checks")
from helpers import geo
geo.warm_geocode_cache = _slow("geo")
geo._GEOCODE_WARM_FIRST_DELAY_SECONDS = 0
os.environ.pop("MOTRIX_DISABLE_SCHEDULERS", None)

t0 = time.monotonic()
import main  # noqa: F401
print("IMPORT_SECONDS=%%.2f" %% (time.monotonic() - t0))
deadline = time.monotonic() + 15
while len(started) < 4 and time.monotonic() < deadline:
    time.sleep(0.1)
print("STARTED=" + ",".join(sorted(started)))
sys.stdout.flush()
os._exit(0)
''' % {"slow": _SLOW}


def _tree_credentials_state():
    """AB-S1：子行程不可以動這棵樹的首次安裝帳密檔（開發機自己的那一份）與載入狀態檔。回 {檔名: mtime 或 None}。"""
    import os
    from pathlib import Path
    backend = Path(__file__).resolve().parents[1]
    names = (".initial_admin_credentials.txt", ".initial_demo_credentials.txt", "logs/module_states.json")
    return {n: (os.path.getmtime(backend / n) if (backend / n).exists() else None) for n in names}


def test_import_main_finishes_while_every_scheduler_is_slow():
    """主持指定：所有排程都慢（含雲端路徑在但卡住）時 import main 仍在時限內完成；而各排程的第一輪確實在背景起跑。
    反向控制＝舊碼：`_ensure_archive_dirs()`／`_schedule_daily()` 同步 ⇒ import ≥ 2×_SLOW 秒而紅（突變測過）。"""
    from pathlib import Path
    from tests._subproc import run_python
    backend = Path(__file__).resolve().parents[1]
    before = _tree_credentials_state()
    proc = run_python(["-c", _IMPORT_MAIN_SCRIPT], cwd=backend, timeout=_SLOW * 5)
    assert _tree_credentials_state() == before, "子行程改動了這棵樹的首次安裝帳密檔或載入狀態檔（AB-S1）"
    assert proc.returncode == 0, f"子行程失敗（returncode={proc.returncode}）：\n{proc.stderr[-2500:]}"
    vals = dict(l.split("=", 1) for l in proc.stdout.splitlines() if "=" in l and l.split("=", 1)[0].isupper())
    assert "IMPORT_SECONDS" in vals, f"子行程沒有印出耗時：\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
    secs = float(vals["IMPORT_SECONDS"])
    assert secs < _SLOW, (f"import main 花了 {secs:.1f} 秒 ≥ 排程工作的 {_SLOW} 秒 ⇒ 啟動在等排程"
                          "（套用後健康檢查有時限 ⇒ 好的包會被自動回滾）")
    started = set(filter(None, vals.get("STARTED", "").split(",")))
    assert {"ensure", "weekly", "geo", "daily_checks"} <= started, f"背景第一輪沒有起跑：{sorted(started)}"
