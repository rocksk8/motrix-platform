"""L1／L2 · 啟動時要把「雷達是開的」記進 log。

## 為什麼要記「開著」那一側，而不是「關著」那一側

B 的理由，照抄：

> **忘了設 ⇒ 測不到（吵）；不小心設了而沒人知道 ⇒ 一台以為離線的機器在連外網（安靜）。**

🔑 **兩種錯的可見度差很多，所以記錄要記在安靜的那一側。**
「忘了設」這件事使用者自己會發現（他按了掃描、什麼都沒發生）；
「不小心設了」沒有任何人會發現 —— 沒有畫面、沒有錯誤、沒有人報修，
**而後果是一台交付給客戶、被認為不會對外連線的機器，每天在連政府網站。**

## ⚠️ 斷言「有沒有這一筆」，不是完整字串

訊息的措辭會改（而且**應該**能改 —— 它是要給人看的）。
釘死整句的話，B 改一個字就紅，而那不是缺陷。
⇒ 錨點選 **`MOTRIX_TENDER_RADAR`** 這個名字：它是這個功能的**識別**，
改掉它就代表功能本身變了，那時候這一題**應該**要紅。

## 🔴 這兩題現在是紅的，那是刻意的（七步的②）

`main.py` 還沒有這一行 —— **B 在等這個紅燈**。
⚠️ 我一度以為要等 B 落地才驗，那是把順序記反了（A 指出）。

## ⚠️ 量尺先驗過：這個 harness 看得見既有的啟動 log

沒有 `test_l0` 的話，「B 還沒寫」與「**我的收集器根本收不到任何 log**」
會長得一模一樣，而後者會讓 B 去補一行**其實已經在那裡**的訊息。
🔑 **先證明量尺有刻度，再拿它去量。**
"""
from pathlib import Path

from tests._subproc import run_python

BACKEND = Path(__file__).resolve().parents[3]   # modules/tender_radar/tests → backend
ANCHOR = "MOTRIX_TENDER_RADAR"

# ⚠️ 收集器必須在 `import main` **之前**掛上 —— 那一行 log 是在 import 時發出的。
#    （`archive` 一樣要先塞進 `sys.modules`，理由見 S5：`main.py:22` 是
#    `from archive import ...`，而 `_schedule_daily()` 會真的跑一次備份。）
_SCRIPT = '''
import json, logging, os, sys, tempfile, types

MODE = sys.argv[1]                       # "on" / "off"

os.environ["MOTRIX_DISABLE_SCHEDULERS"] = "1"
if MODE == "on":
    os.environ["MOTRIX_TENDER_RADAR"] = "1"
else:
    os.environ.pop("MOTRIX_TENDER_RADAR", None)

_seen = []


class _Collect(logging.Handler):
    def emit(self, record):
        try:
            _seen.append((record.levelname, record.getMessage()))
        except Exception:
            _seen.append((record.levelname, "<格式化失敗>"))


root = logging.getLogger()
root.addHandler(_Collect())
root.setLevel(logging.DEBUG)

import db
_tmp = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_tmp, "t.db")
db.DEMO_DB_PATH = os.path.join(_tmp, "d.db")


class _Stub(types.ModuleType):
    def __getattr__(self, name):
        return lambda *a, **kw: None


sys.modules["archive"] = _Stub("archive")
import routers.daily_tasks as _dt
_dt.schedule_overdue_check = lambda *a, **kw: None

import main   # noqa: F401

hits = [m for lvl, m in _seen if "MOTRIX_TENDER_RADAR" in m]
# ⚠️ **跨行程的輸出一律 ASCII**（`ensure_ascii` 用預設值 True）。
# 這幾行原本是 `ensure_ascii=False`，而它就是 2026-09-21 那次「三題全紅」的
# 真正引爆點 —— **一個只為了讓失敗訊息好讀的診斷輸出，自己把成功變成了失敗**，
# 而錯誤訊息（UnicodeEncodeError）看起來像被測對象的問題。
# 🔑 傳輸用 ASCII，顯示是讀的人的事。
print("TOTAL=%d" % len(_seen))
print("HITS=%d" % len(hits))
print("SAMPLE=%s" % json.dumps([m for _l, m in _seen[:40]]))
print("HITTEXT=%s" % json.dumps(hits))
'''


def _run(mode, timeout=240):
    proc = run_python(["-c", _SCRIPT, mode], cwd=BACKEND, timeout=timeout)
    assert proc.returncode == 0, (
        f"子行程（{mode}）失敗 returncode={proc.returncode}\n{proc.stderr[-2500:]}"
    )
    out = {}
    for line in proc.stdout.splitlines():
        if "=" in line and line.split("=")[0].isupper():
            k, v = line.split("=", 1)
            out[k] = v
    assert "HITS" in out, f"子行程沒印出 HITS：\n{proc.stdout[-1200:]}"
    return out


def test_l0_the_log_collector_can_actually_see_startup_logs():
    """量尺先驗：這個收集器**收得到** `import main` 期間發出的 log。

    ⚠️ 沒有這一題，L1 紅的時候有兩種可能而它們長得一模一樣：
    ① B 還沒寫那一行（真的）
    ② **我的收集器根本收不到任何東西**（假的）
    而 ② 會讓 B 去補一行**其實已經在那裡**的訊息，然後兩個人一起困惑。
    """
    out = _run("on")
    assert int(out["TOTAL"]) > 0, (
        "`import main` 期間一筆 log 都沒收到 —— 收集器掛得太晚，或 logger 不 propagate。"
        f"\nSAMPLE={out.get('SAMPLE')}"
    )


def test_l1_startup_logs_that_the_radar_is_on():
    """🔴 L1：`MOTRIX_TENDER_RADAR=1` 啟動 → log 裡**要有**提到它的那一筆。

    ⚠️ 這一題現在是**紅**的：`main.py` 還沒有這一行。

    🔑 記錄的是**安靜的那一側**：「不小心設了而沒人知道」不會有任何人報修，
    而它代表一台被認為不會對外連線的機器，每天在連政府網站。
    """
    out = _run("on")
    assert int(out["HITS"]) >= 1, (
        f"雷達被環境變數打開了，而啟動 log 裡沒有任何一筆提到 {ANCHOR}。\n"
        "⇒ 這台機器會在沒有人知道的情況下對外連線，而畫面上看不出任何異常。\n"
        f"（收到 {out['TOTAL']} 筆 log，前 40 筆：{out.get('SAMPLE')}）"
    )


def test_l2_no_such_log_when_the_radar_is_off():
    """L2 對照組：沒設環境變數 → **不可以**有那一筆。

    ⚠️ 沒有這一題，一個「不管開關都印一行」的實作會讓 L1 全綠 ——
    而那筆訊息就完全沒有資訊了：**每一台機器都印，等於沒有一台機器被標記**。
    🔑 一個永遠出現的訊號不是訊號。

    📌 這一題現在**必然綠**（那一行還不存在）。它的判準是
    「什麼改動會讓它紅」＝**有人把那行 log 寫在閘門外面**。
    """
    out = _run("off")
    assert int(out["HITS"]) == 0, (
        f"沒有設 {ANCHOR} 卻還是印了 {out['HITS']} 筆提到它的 log：{out.get('HITTEXT')}\n"
        "⇒ 每一台機器都印的話，這行訊息就標不出「哪一台是測試機」了。"
    )
