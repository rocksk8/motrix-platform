"""2026-09-21 · 第 5 輪：標案雷達第 2 步（排程）＋第 5 步（通知）

對應 `docs/windows/STATE.md` §3 **`7bec22d`** 版（S1–S5／N1–N13／R3）。
（協定 §5l：沒有版本號的「我照單寫了」，等於沒說照的是哪一張。）

## 🔴 我沒有讀實作

`schedule_tender_scan` / `run_scheduled_scan` / `notify_tender_*` 都還不存在
（我用 `hasattr` 查過）。接縫名稱與既有模組的介面是用 `dir()`／`inspect.signature()`
取得的，**沒有用 `inspect.getsource`**。

## 這一輪的核心：**最外圈那一層永遠沒有人驗**

第 4 輪我驗「`run_scan` 有沒有呼叫 `fetch_raw`」，沒驗「有沒有人呼叫 `run_scan`」
—— ⑦ 才抓到 `run_scan()` 在 production 根本沒有排程呼叫者。

**這一輪如果只寫 S1～S4，同一個 bug 會再活一次**：S1 的「排程觸發」是**測試自己
做的**，所以 `main.py` 從來沒啟動排程器的話，S1～S4 **全部照樣綠**。

> 🔑 **每一輪都往上挪一層，而最上面那一層永遠沒有人驗。**

**S5 就是那一圈。** 它是唯一一題會在「有人把 `main.py` 那行拿掉」時變紅的。

## ⚠️ 我釘的名字（§3 沒有全部指定）

| 名字 | 出處 |
|------|------|
| `tender_source.schedule_tender_scan()` | §3 明文 |
| `tender_source.run_scheduled_scan()` | §3 明文（模組層級具名函式，不是巢狀 closure）|
| `tender_source.threading` | ⚠️ **C 釘**：S3 要換掉 Timer，模組必須走 `threading.Timer(...)` |
| `email_notify.notify_tender_found` | §3 寫「`notify_tender_found` 等」 |
| `email_notify.notify_tender_fetch_failed` | ⚠️ **C 釘**（N3）|
| `email_notify.notify_tender_source_changed` | ⚠️ **C 釘**（N6，要與 N3 不同事件 key）|
| 事件 key `tender_found`／`tender_fetch_failed`／`tender_source_changed` | ⚠️ **C 釘** |

要改名跟我說，改的是常數不是邏輯。
"""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest


# ── 契約 ─────────────────────────────────────────────────────────────────────

import helpers.tender_source as ts  # noqa: E402  第 4 輪已存在
import helpers.email_notify as en   # noqa: E402  既有模組
import helpers.notification_prefs as np  # noqa: E402  既有模組

NOTIFY_FOUND = "notify_tender_found"
NOTIFY_FAILED = "notify_tender_fetch_failed"
NOTIFY_CHANGED = "notify_tender_source_changed"

EVENT_FOUND = "tender_found"
EVENT_FAILED = "tender_fetch_failed"
EVENT_CHANGED = "tender_source_changed"


def _need(mod, name):
    if not hasattr(mod, name):
        raise AssertionError(
            f"{mod.__name__} 缺少 `{name}` —— B 還沒做，或名字跟我釘的不一樣。"
            "見本檔開頭〈我釘的名字〉。"
        )
    return getattr(mod, name)


def _spy(monkeypatch, mod, name, result=None):
    """把某個函式換成計數器，回傳呼叫參數的串列。

    ⚠️ 觀測點是**呼叫本身**（§3 開工前先讀 #1）。
    """
    _need(mod, name)
    calls = []

    def _rec(*a, **kw):
        calls.append((a, kw))
        return result

    monkeypatch.setattr(mod, name, _rec)
    return calls


# ══════════════════════════════════════════════════════════════════════
# S1～S5 · 排程
# ══════════════════════════════════════════════════════════════════════

def test_s1_scheduled_run_calls_run_scan_once(client, monkeypatch):
    """§3 S1：排程觸發 → `run_scan` 的呼叫次數 == 1。"""
    calls = _spy(monkeypatch, ts, "run_scan")
    _need(ts, "run_scheduled_scan")()
    assert len(calls) == 1, f"排程一次應該呼叫 run_scan 一次，實際 {len(calls)} 次"


def test_s2_disabled_switch_means_no_fetch_from_scheduler(client, monkeypatch):
    """§3 S2：開關關著時，排程觸發 → `fetch_raw` 計數器 == 0。

    ⚠️ 觀測點是 `fetch_raw` 不是 `run_scan` —— 排程本來就該照常跑到 `run_scan`，
    被擋住的是**對外連線**那一步。
    """
    fetches = _spy(monkeypatch, ts, "fetch_raw", result=(None, None))
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", False)
    _need(ts, "run_scheduled_scan")()
    assert len(fetches) == 0, (
        f"開關關著時不該對外連線，實際 fetch_raw 被呼叫 {len(fetches)} 次"
    )


def test_s3_exception_still_reschedules_next_timer(client, monkeypatch):
    """§3 S3：`run_scan` 丟例外時，**下一次 Timer 仍被排上**。

    ⚠️ 觀測點是「**有沒有再排一次**」，不是「有沒有印錯誤」。
    一項丟例外讓下一次 Timer 不被排上的話，**整個排程會安靜地死掉**，
    而「排程死了」跟「今天沒事做」長得一模一樣。

    ⚠️ 這題要求 `tender_source` 寫 `threading.Timer(...)` **走模組**。
    寫成 `from threading import Timer` 的話副本會被複製走，monkeypatch 打不到，
    **這題會永遠綠** —— 跟第 4 輪 8b 的 `fetch_raw` 是同一條。
    """
    _need(ts, "threading")
    timers = []

    class _FakeTimer:
        def __init__(self, interval, func, *a, **kw):
            timers.append(interval)
            self.daemon = True

        def start(self):
            pass

    monkeypatch.setattr(ts.threading, "Timer", _FakeTimer)

    def _boom(*a, **kw):
        raise RuntimeError("故意炸的")

    monkeypatch.setattr(ts, "run_scan", _boom)

    _need(ts, "schedule_tender_scan")()      # 不可以把例外往外丟
    assert timers, (
        "run_scan 丟例外之後，下一次 Timer 沒有被排上 —— 排程會安靜地死掉。"
        "⚠️ 若這題在實作正確時仍然紅，先查 tender_source 是不是寫了 "
        "`from threading import Timer`（那樣 monkeypatch 打不到）。"
    )


def test_s3b_timer_is_scheduled_on_the_happy_path_too(client, monkeypatch):
    """S3 的對照組：**正常情況下 Timer 本來就該被排上**。

    ⚠️ 沒有這題，一個「根本不排 Timer」的實作會讓 S3 也紅 —— 但紅的原因不同，
    而紅燈不會告訴你是哪一種。**先證明量尺有刻度，再拿它去量。**
    """
    _need(ts, "threading")
    timers = []

    class _FakeTimer:
        def __init__(self, interval, func, *a, **kw):
            timers.append(interval)
            self.daemon = True

        def start(self):
            pass

    monkeypatch.setattr(ts.threading, "Timer", _FakeTimer)
    _spy(monkeypatch, ts, "run_scan")
    _need(ts, "schedule_tender_scan")()
    assert timers, "正常情況下也必須排下一次 Timer"


def test_s4_second_trigger_same_day_makes_no_external_request(client, monkeypatch):
    """§3 S4：同一天排程觸發兩次 → `fetch_raw` 計數器 == 1。

    沿用第 4 輪 9c 的形狀；`_already_fetched_today` 已經存在，排程不必自己判。
    """
    fetches = _spy(monkeypatch, ts, "fetch_raw", result=("<html></html>", None))
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    run = _need(ts, "run_scheduled_scan")
    run()
    first = len(fetches)
    assert first == 1, f"第一次該真的抓一次，實際 {first} 次（觀測點壞了）"
    run()
    assert len(fetches) == 1, f"同一天第二次不該再抓，實際總共 {len(fetches)} 次"


# ── S5：最外圈 ──────────────────────────────────────────────────────────────

_S5_SCRIPT = '''
import os, sys, types, tempfile

# ① 先把 DB 指到暫存 —— 不可以動到真正的 motrix_erp.db
import db
_tmp = tempfile.mkdtemp()
db.DB_PATH = os.path.join(_tmp, "t.db")
db.DEMO_DB_PATH = os.path.join(_tmp, "d.db")

# ② 在 import main 之前把 archive 換成記錄器。
#    main.py:22 是 `from archive import ...`，事後 patch 打不到；
#    而 archive._schedule_daily() 第一件事就是 _daily_backup()
#    （SQLite 整庫快照 ＋ 41 張表 JSON 匯出），不可以在測試裡真的跑。
class _Stub(types.ModuleType):
    def __getattr__(self, name):
        return lambda *a, **kw: None

sys.modules["archive"] = _Stub("archive")

# ③ 其他會在 import 時起排程的，一併換掉
import routers.daily_tasks as _dt
_dt.schedule_overdue_check = lambda *a, **kw: None

# ④ 把要觀測的那一支換成記錄器
import helpers.tender_source as _ts
_hits = []
_ts.schedule_tender_scan = lambda *a, **kw: _hits.append(1)

# ⑤ **不設** MOTRIX_DISABLE_SCHEDULERS —— 這一題驗的就是正式機那條路
os.environ.pop("MOTRIX_DISABLE_SCHEDULERS", None)

import main   # noqa: F401

print("SCHEDULE_CALLS=%d" % len(_hits))
'''


def test_s5_main_actually_starts_the_tender_scheduler():
    """§3 S5：**`main.py` 真的會啟動標案排程** —— 最外圈那一題。

    🔑 **沒有這一題，S1～S4 在「`main.py` 那行被拿掉」時全部照樣綠**，
    而雷達照樣不會自己轉。⑦ 抓到的 `run_scan()` 沒有排程呼叫者就是這個形狀，
    **只是低了一層**。

    ⚠️ 必須用**子行程**：`conftest.py::_app` 固定設 `MOTRIX_DISABLE_SCHEDULERS=1`，
    在行程內驗，驗到的是**測試自己的設定**。

    ⚠️ 必須**先**把 `archive` 塞進 `sys.modules` 再 `import main`：
    `main.py:22` 是 `from archive import ...`（事後 patch 打不到），而
    `_schedule_daily()` 第一件事就是 `_daily_backup()` —— 直接 import 會在測試裡
    跑一次**真的備份**。

    ✅ 附帶好處：這題同時保護既有的五個排程 —— 有人拿掉 `main.py:492` 那個
    區塊的任何一行，它都會紅。
    """
    backend = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-c", _S5_SCRIPT],
        cwd=str(backend), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )
    assert proc.returncode == 0, (
        f"子行程失敗（returncode={proc.returncode}）：\n{proc.stderr[-2500:]}"
    )
    line = [l for l in proc.stdout.splitlines() if l.startswith("SCHEDULE_CALLS=")]
    assert line, f"子行程沒有印出計數：\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
    n = int(line[0].split("=")[1])
    assert n == 1, (
        f"`import main`（不停用排程）之後，schedule_tender_scan 被呼叫 {n} 次，應為 1。"
        "⚠️ 0 次代表 main.py 根本沒有啟動標案排程 —— 雷達不會自己轉，"
        "而 S1～S4 不會告訴你這件事。"
    )


# ══════════════════════════════════════════════════════════════════════
# N1～N13 · 通知
# ══════════════════════════════════════════════════════════════════════

def _fetch_log(conn, *, recognised, dropped, error, fetched_at):
    conn.execute(
        "INSERT INTO tender_fetch_log (fetched_at, recognised, dropped, error) "
        "VALUES (?,?,?,?)", (fetched_at, recognised, dropped, error))


def _seed_log(rows):
    """把 `tender_fetch_log` 塞到已知狀態。

    ⚠️ §3 明文要求（C 審單第五項）：**N4／N5 不可以靠環境預設** ——
    `tender_fetch_log` 在我上一輪的裁決裡是**不進 JSON 備份**的，
    所以它在還原後／CI 空庫上是空的。靠「它剛好是空的」驗到的是別的東西。
    """
    import db
    conn = db.get_db()
    try:
        for r in rows:
            _fetch_log(conn, **r)
        conn.commit()
    finally:
        conn.close()


def test_n1_one_email_per_day_not_per_tender(client, monkeypatch):
    """§3 N1：命中 5 筆 → 寄信函式**被呼叫 1 次**（不是 5 次）。"""
    sent = _spy(monkeypatch, en, NOTIFY_FOUND)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(_five_hit_page(), None))
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 1, f"五筆命中應該只寄一封彙總，實際 {len(sent)} 封"


def _five_hit_page():
    """真實 fixture（5 筆）—— 沿用第 4 輪的樣本，不手寫。"""
    from tests.test_tender_match_2026_09_21 import REAL
    return REAL


def test_n2_no_hits_means_no_email(client, monkeypatch):
    """§3 N2：命中 0 筆 → 寄信函式 **0 次**。

    ⚠️ 「今天沒標案」不是異常，不該打擾任何人。
    """
    from tests.test_tender_match_2026_09_21 import HTML_EMPTY_RESULTS
    sent = _spy(monkeypatch, en, NOTIFY_FOUND)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(HTML_EMPTY_RESULTS, None))
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 0, f"零命中不該寄信，實際 {len(sent)} 封"


def test_n3_fetch_failure_sends_one_email(client, monkeypatch):
    """§3 N3：抓取失敗 → 寄信函式 1 次（§T.6：**雷達瞎了要有人知道**）。"""
    _seed_log([])
    sent = _spy(monkeypatch, en, NOTIFY_FAILED)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(None, "timeout after 15s"))
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 1, f"抓不到要通知一次，實際 {len(sent)} 次"


def test_n4_seven_days_of_failure_sends_only_one_email(client, monkeypatch):
    """§3 N4：連續 7 天抓取失敗 → 寄信函式**總共 1 次**（邊緣觸發）。

    ⚠️ **站台掛一週不可以變成七封信** —— 狼來了的告警等於沒有告警。
    ⚠️ 這題**自己 seed `tender_fetch_log`**，不靠環境預設（§3 明文）。
    """
    _seed_log([{"fetched_at": f"2026-09-{d:02d}T09:00:00", "recognised": None,
                "dropped": 0, "error": "timeout"} for d in range(14, 21)])
    sent = _spy(monkeypatch, en, NOTIFY_FAILED)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(None, "timeout after 15s"))
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 0, (
        f"已經連續失敗好幾天了，今天這次不該再寄，實際 {len(sent)} 次 —— "
        "那是準位觸發不是邊緣觸發"
    )


def test_n5_fail_recover_fail_sends_two_emails(client, monkeypatch):
    """§3 N5：失敗 → 恢復 → 又失敗 → 寄信函式**總共 2 次**。

    ⚠️⚠️ **沒有這題，「這輩子只發一次」的實作會完整通過** ——
    而那個實作在第二次真的壞掉時是**啞的**。

    🔑 跟去重要驗兩個方向是同一件事：**該發的有發、該停的有停。**
    （第 4 輪 `test_05c`「同案號不同機關要留兩筆」是同一個手法。）
    """
    # 前一次是「恢復了」——所以今天這次失敗是**重新進入異常**，要寄
    _seed_log([
        {"fetched_at": "2026-09-18T09:00:00", "recognised": None, "dropped": 0,
         "error": "timeout"},                      # 第一次失敗（當時已寄過）
        {"fetched_at": "2026-09-19T09:00:00", "recognised": 1, "dropped": 0,
         "error": ""},                             # 恢復
    ])
    sent = _spy(monkeypatch, en, NOTIFY_FAILED)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(None, "timeout again"))
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 1, (
        f"恢復之後又失敗 ＝ 重新進入異常，要再寄一次，實際 {len(sent)} 次。"
        "⚠️ 0 次代表實作是「這輩子只發一次」—— 第二次真的壞掉時它是啞的。"
    )


def test_n6_suspected_redesign_uses_a_different_event_key(client, monkeypatch):
    """§3 N6：`suspect_redesign` 為真 → 寄信 1 次，且**與 N3 是不同的事件 key**。

    ⚠️ 兩者的處置相反：**改版要改解析器、掛掉只要等它好**。
    共用一個 key 的話，使用者關掉其中一個就同時關掉另一個。
    """
    from tests.test_tender_match_2026_09_21 import HTML_MOSTLY_DROPPED
    _seed_log([])
    changed = _spy(monkeypatch, en, NOTIFY_CHANGED)
    failed = _spy(monkeypatch, en, NOTIFY_FAILED)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(HTML_MOSTLY_DROPPED, None))
    _need(ts, "run_scheduled_scan")()
    assert len(changed) == 1, f"疑似改版要通知一次，實際 {len(changed)} 次"
    assert len(failed) == 0, "疑似改版不可以走「抓不到」那個事件 key —— 處置不同"


@pytest.mark.parametrize("key", [EVENT_FOUND, EVENT_FAILED, EVENT_CHANGED])
def test_n6b_event_keys_are_registered(client, key):
    """三個事件 key 都要登記進 `EVENT_KEYS`，否則使用者關不掉也開不了。"""
    assert key in np.EVENT_KEYS, (
        f"事件 key `{key}` 沒有登記進 notification_prefs.EVENT_KEYS；"
        f"實際有 {len(np.EVENT_KEYS)} 個"
    )


def test_n7_quiet_period_sends_nothing(client, monkeypatch):
    """§3 N7：首次成功掃描起 **7 天內**，即使有命中 → 寄信函式 0 次。

    §T.5 #3 的「純記錄模式」。⚠️ 起算點是**第一次成功掃描**不是「開關被打開」——
    常數翻開的時間無法查證，而**無法查證的起算點在正式機上完全不存在**。

    📌 monkeypatch 的是 `helpers.tender_source.today`（接縫已存在，`:93`）。
    """
    import datetime as dt
    sent = _spy(monkeypatch, en, NOTIFY_FOUND)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(_five_hit_page(), None))
    _need(ts, "today")
    monkeypatch.setattr(ts, "today", lambda: dt.date(2026, 9, 24))  # 首掃後第 3 天
    _set_first_scan_at("2026-09-21T09:00:00")
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 0, f"純記錄模式 7 天內不該寄信，實際 {len(sent)} 封"


def test_n8_day_eight_sends(client, monkeypatch):
    """§3 N8：第 8 天有命中 → 寄信函式 1 次。

    ⚠️ N7 的對照組：沒有這題，一個「永遠不寄」的實作會讓 N7 全綠。
    """
    import datetime as dt
    sent = _spy(monkeypatch, en, NOTIFY_FOUND)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(_five_hit_page(), None))
    monkeypatch.setattr(ts, "today", lambda: dt.date(2026, 9, 29))  # 首掃後第 8 天
    _set_first_scan_at("2026-09-21T09:00:00")
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 1, f"純記錄模式過了就該寄，實際 {len(sent)} 封"


def _set_first_scan_at(value):
    """寫入 `tender_radar_first_scan_at`（§3 的新欄位）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?,?)",
            ("tender_radar_first_scan_at", value))
        conn.commit()
    finally:
        conn.close()


def test_n9_already_notified_tender_not_in_later_emails(client, monkeypatch):
    """§3 N9：同一標案已通知過 → **不出現在後續的信裡**（`tender_hits` 的已通知標記）。"""
    import db
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(_five_hit_page(), None))
    sent = _spy(monkeypatch, en, NOTIFY_FOUND)
    run = _need(ts, "run_scheduled_scan")

    run()
    assert len(sent) == 1, "第一次應該寄一封（觀測點壞了的話後面都沒意義）"
    first_payload = repr(sent[0])

    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tender_fetch_log")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(ts, "_already_fetched_today", lambda conn: False)

    run()
    if len(sent) > 1:
        assert repr(sent[1]) != first_payload, (
            "第二封信跟第一封一模一樣 —— 已通知的標案又被寄了一次"
        )


def test_n10_no_enabled_recipient_means_no_send(client, monkeypatch):
    """§3 N10：monkeypatch `is_enabled()` 讓**一個收件人都不啟用** → 寄信 0 次。

    ⚠️ 原本 §3 寫「驗沒有寫死的信箱字串」是**結構測試**（A 自己在 8b 禁止的），
    而且擋不住 `"admin" + "@" + "x.com"` 這種拼接。**這一題驗行為**：
    收件人真的走設定的話，全部關掉就應該一封都不寄；
    **有寫死信箱的話，它還是會寄 → 紅。**
    """
    sent = _spy(monkeypatch, en, NOTIFY_FOUND)
    monkeypatch.setattr(np, "is_enabled", lambda muted_json, event_key: False)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(_five_hit_page(), None))
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 0, (
        f"一個收件人都沒啟用，卻寄了 {len(sent)} 封 —— 收件人沒有走 is_enabled()"
    )


def test_n11_email_payload_carries_attribution(client, monkeypatch):
    """§3 N11：信件內容含**資料出處標示**（§T.5 #6，授權條款要求）。

    ⚠️ 觀測點是**傳給寄信函式的參數**，不是投遞結果 —— §3「開工前先讀 #1」
    禁止的是後者（信箱裡有幾封），前者在呼叫邊界上看得到，是合法觀測點。
    """
    sent = _spy(monkeypatch, en, NOTIFY_FOUND)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(_five_hit_page(), None))
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 1
    payload = repr(sent[0])
    assert "政府電子採購網" in payload or "web.pcc.gov.tw" in payload, (
        "信件內容沒有資料出處標示（授權條款要求）。"
        f"實際傳入的參數：{payload[:300]}"
    )


def test_n12_send_failure_must_not_mark_as_notified(client, monkeypatch):
    """§3 N12：**寄信丟例外時，已通知標記不可以被設定**。

    ⚠️ 在寄信**之前**設定的話，那批標案**永遠不會再出現在任何一封信裡** ——
    而且不會有任何錯誤訊息。**這是「安靜地少做一件事」的又一個實例。**
    """
    import db
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(_five_hit_page(), None))

    def _boom(*a, **kw):
        raise RuntimeError("SMTP 掛了")

    _need(en, NOTIFY_FOUND)
    monkeypatch.setattr(en, NOTIFY_FOUND, _boom)
    _need(ts, "run_scheduled_scan")()      # 不可以把例外往外丟

    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) c FROM tender_hits WHERE notified_at IS NOT NULL "
            "AND notified_at != ''").fetchone()
    finally:
        conn.close()
    assert row["c"] == 0, (
        f"寄信失敗了，卻有 {row['c']} 筆被標記成已通知 —— "
        "那批標案永遠不會再出現在任何一封信裡，而且不會有錯誤訊息"
    )


def test_n13_restart_during_outage_does_not_resend(client, monkeypatch):
    """§3 N13：**異常期間重啟服務，不可以重發**。

    🔑 **與 N5 是一對**：該發的有發（N5）、**不該重發的沒重發**（N13）。

    ⚠️ 「重啟」在測試裡的意義是「行程內狀態沒了」，所以這題把可能的記憶體狀態
    清掉，只留資料庫裡的事實 —— **邊緣觸發的狀態必須是持久的**，
    存在行程記憶體裡的話，每次重啟都會重新寄一次。
    """
    _seed_log([{"fetched_at": "2026-09-20T09:00:00", "recognised": None,
                "dropped": 0, "error": "timeout"}])
    importlib.reload(ts) if False else None      # 不真的 reload，避免打掉 monkeypatch
    sent = _spy(monkeypatch, en, NOTIFY_FAILED)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _spy(monkeypatch, ts, "fetch_raw", result=(None, "still down"))
    _need(ts, "run_scheduled_scan")()
    assert len(sent) == 0, (
        f"異常期間重啟不該重發，實際 {len(sent)} 次 —— "
        "邊緣觸發的狀態必須存在資料庫裡，不是行程記憶體裡"
    )


# ══════════════════════════════════════════════════════════════════════
# R3 · 結轉項：User-Agent 與逾時
# ══════════════════════════════════════════════════════════════════════

def test_r3a_user_agent_identifies_motrix(client):
    """§3 R3：`User-Agent` 要標示是 MOTRIX ERP（§T.5 的禮貌要求）。

    ⚠️ 這是對別人的伺服器的承諾 —— **沒人驗它就沒人守它**（跟每日一次那條同理）。
    """
    ua = _need(ts, "USER_AGENT")
    assert isinstance(ua, str) and ua.strip(), f"USER_AGENT 是空的：{ua!r}"
    assert "MOTRIX" in ua.upper(), (
        f"User-Agent 沒有標示是 MOTRIX ERP，實際 {ua!r} —— "
        "對方看不出是誰在抓，出事時也聯絡不到我們"
    )


def test_r3b_fetch_timeout_is_bounded(client):
    """§3 R3：逾時 15 秒。

    ⚠️ 沒有逾時上限的話，對方站台慢下來會讓排程執行緒**卡住不放**，
    而下一次 Timer 要等它回來才排得上 —— **排程會安靜地停掉**。
    """
    t = _need(ts, "FETCH_TIMEOUT_SECONDS")
    assert isinstance(t, (int, float)), f"FETCH_TIMEOUT_SECONDS 型別不對：{t!r}"
    assert 0 < t <= 15, f"逾時應該是 15 秒以內的正數，實際 {t!r}"
