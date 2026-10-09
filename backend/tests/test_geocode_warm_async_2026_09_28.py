"""第十五班緊急修補 B54：`schedule_geocode_warm()` 不可以同步跑第一輪。

正式機套用 8b04d99d 失敗、自動回滾：`main.py` 模組層呼叫 `geo.schedule_geocode_warm()`，
原本在呼叫當下同步跑完第一輪 `warm_geocode_cache()` ⇒ `import main` 被卡住 ⇒ 83 秒內 port 666 沒在聽。
B50 之後查無不再讓迴圈停下，333 筆待辦 × Nominatim 每秒 1 次 ⇒ 啟動被卡數分鐘。
☠️ 演練與 conftest 都設 `MOTRIX_DISABLE_SCHEDULERS=1` ⇒ 那一行從來沒在測試裡跑過。

守門：①呼叫立即返回，第一輪不在呼叫者的執行緒裡跑（反向控制：改回同步 ⇒ 紅）
      ②第一輪確實會在背景跑，跑完（含丟例外）照樣排下一輪
"""
import threading
import time

import pytest

from helpers import geo


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
    monkeypatch.setattr(geo.threading, "Timer", _RecordingTimer)
    return _RecordingTimer.made


@pytest.mark.timing
def test_schedule_returns_immediately_and_does_not_run_the_round_inline(timers, monkeypatch):
    """① 第一輪很慢（替身睡 3 秒）時，`schedule_geocode_warm()` 仍立即返回、呼叫者的執行緒裡沒有跑任何一輪。"""
    calls = []

    def slow_round():
        calls.append(threading.current_thread().name)
        time.sleep(3)
        return {}

    monkeypatch.setattr(geo, "warm_geocode_cache", slow_round)
    t0 = time.monotonic()
    geo.schedule_geocode_warm()
    elapsed = time.monotonic() - t0
    assert calls == [], "第一輪在呼叫者的執行緒裡同步跑了 ⇒ import main 會被卡住（正式機 8b04d99d 回滾的原因）"
    assert elapsed < 1.0, f"schedule_geocode_warm() 花了 {elapsed:.1f} 秒才返回"
    assert len(timers) == 1 and timers[0].started and timers[0].daemon, \
        "第一輪要排進一個已啟動的 daemon Timer（daemon：關機不等它）"
    assert timers[0].interval == geo._GEOCODE_WARM_FIRST_DELAY_SECONDS
    assert timers[0].interval < geo.GEOCODE_WARM_INTERVAL_SECONDS, "第一輪是短延遲，不是等一整個週期"


def test_first_round_runs_in_background_and_reschedules(timers, monkeypatch):
    """② 排進去的那一個跑起來＝跑一輪，然後以週期排下一輪（同一支工作）。"""
    calls = []
    monkeypatch.setattr(geo, "warm_geocode_cache", lambda: calls.append(1) or {})
    geo.schedule_geocode_warm()
    first = timers[0]
    first.function()
    assert calls == [1], "排進去的第一個 Timer 沒有跑定位"
    assert len(timers) == 2
    nxt = timers[1]
    assert nxt.started and nxt.daemon
    assert nxt.interval == geo.GEOCODE_WARM_INTERVAL_SECONDS
    assert nxt.function is first.function, "下一輪要排同一支工作（每輪結束再排下一輪）"
    nxt.function()
    assert calls == [1, 1] and len(timers) == 3


def test_round_raising_still_reschedules(timers, monkeypatch):
    """② 一輪丟例外 ⇒ 照樣排下一輪（重排在 finally；排程死了跟今天沒事做長得一樣）。"""
    def boom():
        raise RuntimeError("模擬一輪失敗")

    monkeypatch.setattr(geo, "warm_geocode_cache", boom)
    geo.schedule_geocode_warm()
    timers[0].function()                 # 不可以把例外往外丟（Timer 執行緒裡丟出去＝排程停了）
    assert len(timers) == 2 and timers[1].started
    assert timers[1].interval == geo.GEOCODE_WARM_INTERVAL_SECONDS


def test_real_thread_first_round_runs_while_caller_is_free(monkeypatch):
    """① ② 用真的 threading.Timer：呼叫立即返回，第一輪在另一個執行緒跑起來。"""
    started = threading.Event()
    release = threading.Event()
    made = []
    real_timer = threading.Timer

    class _TrackedTimer(real_timer):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            made.append(self)

    def blocking_round():
        started.set()
        release.wait(10)
        return {}

    monkeypatch.setattr(geo.threading, "Timer", _TrackedTimer)
    monkeypatch.setattr(geo, "_GEOCODE_WARM_FIRST_DELAY_SECONDS", 0)
    monkeypatch.setattr(geo, "warm_geocode_cache", blocking_round)
    try:
        t0 = time.monotonic()
        geo.schedule_geocode_warm()
        assert time.monotonic() - t0 < 1.0, "呼叫者被第一輪卡住"
        assert started.wait(5), "第一輪沒有在背景跑起來"
        assert made[0].daemon
    finally:
        release.set()
        deadline = time.monotonic() + 5
        while len(made) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        for t in made:
            t.cancel()                   # 下一輪（週期）的 Timer 不留下來
    assert len(made) == 2, "第一輪跑完沒有排下一輪"


# ── 整合：main.py 的排程區塊本身（主持追加：預熱第一輪期間 import main 在 N 秒內完成）──────────────
#
# ⚠️ 不是真的 `import main`：排程開著的 import main 會同步跑整庫備份、週備份（碰真實磁碟／雲端路徑），
#    測試不可以做。這裡改成**逐字執行 main.py 裡那個 `if MOTRIX_DISABLE_SCHEDULERS` 區塊的 AST**
#    （正式機 import main 時跑的就是這一段）：備份兩支換成空函式、每日檢查換成空函式，
#    定位走真的 `warm_geocode_cache()`＋真的 geocode 路徑，只把 Nominatim 換成「每次慢 0.5 秒、查無」。
#    區塊裡多出不認得的呼叫 ⇒ NameError 紅（逼人回來看這一題）。

from tests.test_geocode_warm_2026_09_22 import backlog  # noqa: E402,F401  （6 筆「待定位機關0～5」）
from tests.test_geocode_warm_misses_2026_09_28 import EMPTY, _fake_urlopen, real_path  # noqa: E402,F401

#: 區塊要在幾秒內跑完。同步版本：6 筆 × 至少 0.5 秒 ⇒ ≥ 3 秒。
_BLOCK_DEADLINE_SECONDS = 2.0


def _scheduler_block():
    import ast
    from pathlib import Path
    src = (Path(geo.__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.If) and "MOTRIX_DISABLE_SCHEDULERS" in ast.dump(node.test):
            return compile(ast.Module(body=node.body, type_ignores=[]), "main.py<scheduler block>", "exec")
    pytest.fail("main.py 裡找不到 `if MOTRIX_DISABLE_SCHEDULERS` 區塊 ⇒ 這一題切不出東西，不可以放行")


@pytest.mark.timing
def test_main_scheduler_block_returns_while_first_warm_round_is_slow(client, backlog, real_path, monkeypatch):
    from helpers import daily_checks

    asked = []
    slow = _fake_urlopen(monkeypatch, lambda a: (time.sleep(0.5), EMPTY)[1])
    made = []
    real_timer = threading.Timer

    class _TrackedTimer(real_timer):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            made.append(self)

    monkeypatch.setattr(geo.threading, "Timer", _TrackedTimer)
    monkeypatch.setattr(geo, "_GEOCODE_WARM_FIRST_DELAY_SECONDS", 0)
    monkeypatch.setattr(daily_checks, "schedule_daily_checks", lambda: asked.append("daily_checks"))
    noop = lambda: None  # noqa: E731
    ns = {"_ensure_archive_dirs": noop, "_schedule_daily": noop, "_schedule_weekly": noop,
          "geo_core": geo, "logger": geo.logger}
    code = _scheduler_block()
    try:
        t0 = time.monotonic()
        exec(code, ns)
        elapsed = time.monotonic() - t0
        assert asked == ["daily_checks"], "區塊結構變了（每日檢查沒被呼叫）⇒ 這一題可能沒切到正確的區塊"
        assert elapsed < _BLOCK_DEADLINE_SECONDS, (
            f"main.py 排程區塊花了 {elapsed:.1f} 秒 ⇒ import main 會被第一輪定位卡住"
            "（正式機 8b04d99d：83 秒內 port 沒在聽 ⇒ 自動回滾）")
        # 第一輪確實在背景跑：等它跑完、排出下一輪（跑完才結束，否則背景執行緒會寫進下一題的庫）
        deadline = time.monotonic() + 60
        while len(made) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(made) >= 2, "第一輪沒有在背景跑完並排下一輪"
        assert slow, "背景第一輪沒有查任何地址"
    finally:
        for t in made:
            t.cancel()


# ── 整合：真的 `import main`（子行程、排程開著）────────────────────────────────
#
# 形狀照 modules/tender_radar/tests/test_tender_notify_2026_09_21.py 的 S5：DB 指到暫存、archive 整支換成空殼
# （不可以真的備份）、每日檢查換掉、**不設** MOTRIX_DISABLE_SCHEDULERS。第一輪預熱換成「睡 _SLOW 秒」並把首輪延遲設 0
# ⇒ 同步版本 import main 至少多 _SLOW 秒。

_SLOW = 60

_IMPORT_MAIN_SCRIPT = '''
import os, sys, types, tempfile, time, threading
import db
_tmp = tempfile.mkdtemp()
import atexit as _ax, shutil as _sh; _ax.register(_sh.rmtree, _tmp, True)   # 2026-09-30 寫入量：結束時刪暫存目錄（原本每跑一次留一個含 1.3MB 庫的目錄）
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

class _Stub(types.ModuleType):
    def __getattr__(self, name):
        return lambda *a, **kw: None

sys.modules["archive"] = _Stub("archive")
import helpers.daily_checks as _dck
_dck.schedule_daily_checks = lambda *a, **kw: None

from helpers import geo
started = threading.Event()
def _slow_round():
    started.set()
    time.sleep(%d)
    return {}
geo.warm_geocode_cache = _slow_round
geo._GEOCODE_WARM_FIRST_DELAY_SECONDS = 0
os.environ.pop("MOTRIX_DISABLE_SCHEDULERS", None)

t0 = time.monotonic()
import main  # noqa: F401
print("IMPORT_SECONDS=%%.2f" %% (time.monotonic() - t0))
print("WARM_STARTED=%%d" %% int(started.wait(10)))
sys.stdout.flush()
os._exit(0)
''' % _SLOW


def _tree_credentials_state():
    """AB-S1：子行程不可以動這棵樹的首次安裝帳密檔（開發機自己的那一份）與載入狀態檔。回 {檔名: mtime 或 None}。"""
    import os
    from pathlib import Path
    backend = Path(__file__).resolve().parents[1]
    names = (".initial_admin_credentials.txt", ".initial_demo_credentials.txt", "logs/module_states.json")
    return {n: (os.path.getmtime(backend / n) if (backend / n).exists() else None) for n in names}


@pytest.mark.timing
def test_import_main_finishes_while_first_warm_round_is_slow():
    """主持追加：預熱第一輪很慢（睡 60 秒）時，真的 `import main` 仍在 60 秒內完成，而第一輪確實在背景起跑。"""
    from pathlib import Path
    from tests._subproc import run_python
    backend = Path(__file__).resolve().parents[1]
    before = _tree_credentials_state()
    proc = run_python(["-c", _IMPORT_MAIN_SCRIPT], cwd=backend, timeout=_SLOW * 3)
    assert _tree_credentials_state() == before, "子行程改動了這棵樹的首次安裝帳密檔或載入狀態檔（AB-S1）"
    assert proc.returncode == 0, f"子行程失敗（returncode={proc.returncode}）：\n{proc.stderr[-2500:]}"
    vals = dict(l.split("=", 1) for l in proc.stdout.splitlines() if "=" in l and l.split("=", 1)[0].isupper())
    assert "IMPORT_SECONDS" in vals, f"子行程沒有印出耗時：\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
    secs = float(vals["IMPORT_SECONDS"])
    assert secs < _SLOW, (f"import main 花了 {secs:.1f} 秒 ≥ 第一輪預熱的 {_SLOW} 秒 ⇒ 啟動在等預熱"
                          "（正式機 8b04d99d：83 秒內 port 沒在聽 ⇒ 自動回滾）")
    assert vals.get("WARM_STARTED") == "1", "import main 之後第一輪預熱沒有在背景起跑"
