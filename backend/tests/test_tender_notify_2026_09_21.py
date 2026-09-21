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
from pathlib import Path

import pytest

from tests._subproc import run_python
from tests._timefreeze import freeze_slot


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
    freeze_slot(monkeypatch, ts, 18)
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


def test_s4_second_trigger_same_slot_makes_no_external_request(client, monkeypatch):
    """§3 S4：同一天排程觸發兩次 → `fetch_raw` 計數器 == 1。

    沿用第 4 輪 9c 的形狀；節流由 `tender_source` 自己判，排程不必重複判。
    ## 🔴 2026-09-21 §3j：這一條原本宣稱的是「**每日**一次」，而那個上限被拆掉了

    使用者裁示「我要可調整」⇒ 抓取改成一天多個時段（預設 9,12,15,18）。
    ⚠️ **斷言的數字沒有變**（連續呼叫兩次仍然只該抓一次），
    **而它宣稱的東西變了** —— 從「今天抓過就不再抓」變成「**這個時段**抓過就不再抓」。

    ☠️ 而如果只改描述不加時間控制，它會變成**偶爾紅的綠燈**：
    測試若剛好在 8:59 跑第一次、9:00 跑第二次（或 11:59/12:00、14:59/15:00、
    17:59/18:00）⇒ 跨時段 ⇒ 抓兩次 ⇒ 紅。
    🔴 **一天四個這種邊界，而且全部落在上班時間。**
    🔑 **那比紅燈貴**：紅燈會被修，偶爾紅的綠燈會被重跑一次然後忘掉。

    ⇒ 所以把時間釘住。`now_dt()` 由 §3j 的 B 提供（形狀比照 `today()`），
    **在它出現之前這一題是紅的，那是刻意的。**

    """
    freeze_slot(monkeypatch, ts)      # 兩次呼叫必須落在同一個時段裡
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
    proc = run_python(["-c", _S5_SCRIPT], cwd=backend, timeout=180)
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
# N1～N14 · 通知
# ══════════════════════════════════════════════════════════════════════
#
# 🔴 觀測點有三層。我停在第一層、A 指出第二層、我查出第三層：
#
#   ① `notify_tender_found` 被呼叫          ← 我原本驗這個。**假綠燈**
#   ② `email_notify._async_send` 被呼叫     ← A 的裁決。**仍然不夠**
#   ③ `_async_send` 被呼叫**而且收件人非空** ← 真正「有人收得到」
#
# ⚠️ 為什麼 ② 不夠（`email_notify.py:185`，我讀過那幾行）：
#       def _async_send(to_addrs, subject, html):
#           threading.Thread(target=_send, args=(to_addrs, subject, html)).start()
#   **它不檢查 `to_addrs` 是不是空的。** 空清單的檢查在 `_send` 裡：
#       if not to_addrs:
#           logger.warning("email skipped — recipient list empty; ...")
#           return
#   ⇒ 收件人是空的時候 `_async_send` 照樣被呼叫、執行緒照樣開，
#     那條執行緒寫一行 log 就結束。**觀測點停在 ② 仍然會綠。**
#
# 🔑 **每一次把觀測點往下游移一步，都要再問一次
#    「這一步之後還有沒有東西會讓它安靜地不發生」。**


@pytest.fixture()
def admin_with_email(client):
    """種一個**有 email 的 admin** —— 否則「有沒有寄信」根本不可觀測。

    ⚠️ `conftest.make_user` 的 INSERT 沒有 email 那一欄（`conftest.py:323`），
    而 `_admin_emails()` 的條件是
    `role IN ('admin','superadmin') AND email IS NOT NULL AND email != ''`
    ⇒ **預設情況下收件人清單永遠是空的**，一封信都寄不出去，
    而我原本的 N1 仍然是綠的。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, email, "
            "modules, active, created_at, must_change_password, notification_muted) "
            "VALUES (?,?,?,?,?,?,1,?,0,?)",
            ("tender_boss", "x", "標案收件人", "superadmin",
             "boss@example.invalid", "[]", "2026-01-01T00:00:00", "[]"),
        )
        conn.commit()
    finally:
        conn.close()
    # 🔴 同時種一筆搜尋條件 —— **不種的話 `tender_hits` 永遠是空的**。
    #
    # 我實測（用完即刪的探針）：
    #     沒有 watch → tenders=5, tender_hits=0, notified=0，**但照樣寄出「5 筆新標案」**
    #     有 watch   → tenders=5, tender_hits=5, notified=5
    # ⇒ N9／N12／N15 斷言的是 `tender_hits.notified_at`，
    #   而沒有 watch 時那張表是空的 ⇒ `assert notified == 0` 是
    #   **空集合上的真，什麼都沒驗到**。
    # 🔑 這是〈假綠燈〉裡「清單為空的斷言」那一條，我自己踩了。
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO tender_watches (name, keywords, enabled) VALUES (?,?,1)",
            ("監視系統", "監視"))
        conn.commit()
    finally:
        conn.close()
    return "boss@example.invalid"


DELIVERY = "_send_raising"


def _sent(monkeypatch):
    """把 `email_notify._send_raising` 換成記錄器 —— **唯一的觀測點**。

    §3 裁決：三支 `notify_tender_*` 全部改走 `_send_raising`（同步、五種失敗
    情況全部 `raise`），取代射後不理的 `_async_send`。

    ⚠️ 我一度想「兩條都攔」以免 B 改到一半打不到。**B 說得對：不要。**
    兩個觀測點的話，「**哪一支走哪一條**」本身就會變成下一個坑 ——
    一支忘了改就會安靜地走舊路，而測試照樣綠。**單一觀測點會讓那件事紅。**
    """
    _need(en, DELIVERY)
    calls = []
    monkeypatch.setattr(
        en, DELIVERY,
        lambda to_addrs, subject, html: calls.append((to_addrs, subject, html)))
    return calls


def _sending_fails(monkeypatch, message="SMTP 掛了"):
    """讓**真正的投遞**失敗。"""
    _need(en, DELIVERY)

    def _boom(*a, **kw):
        raise RuntimeError(message)

    monkeypatch.setattr(en, DELIVERY, _boom)


def _notified_count():
    import db
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) c FROM tender_hits "
            "WHERE notified_at IS NOT NULL AND notified_at != ''").fetchone()["c"]
    finally:
        conn.close()


def _allow_rerun_today(monkeypatch):
    """讓同一天可以再掃一次（繞開每日一次的上限，只在測試裡）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tender_fetch_log")
        conn.commit()
    finally:
        conn.close()
    # 📌 不 patch `_already_fetched_today`：上面那個 DELETE 已經讓它回 False。
    # ⚠️ 它即將改名（§3j）⇒ 留著會在改名當天變 AttributeError。
    # 🔑 前提是抓取側標記仍存放在 `tender_fetch_log`；搬走的話這幾題會紅，而那是對的。


def _assert_mails(calls, n):
    """斷言「真的寄了 n 封」—— 次數**而且**每一封收件人非空。"""
    assert len(calls) == n, f"應該寄 {n} 封，實際 {len(calls)} 封"
    for k, (to_addrs, subject, _html) in enumerate(calls):
        assert to_addrs, (
            f"第 {k + 1} 封的收件人是空的 —— `_async_send` 被呼叫了，但 `_send` "
            f"只會寫一行 log 就 return，沒有人收得到。subject={subject!r}"
        )


def _seed_log(rows):
    """把 `tender_fetch_log` 塞到已知狀態（§3 明文，C 審單第五項）。

    ⚠️ 那張表**不進 JSON 備份**（我第 4 輪的裁決），還原後／CI 空庫上是空的。
    靠「它剛好是空的」驗到的是別的東西。
    """
    import db
    conn = db.get_db()
    try:
        for r in rows:
            conn.execute(
                "INSERT INTO tender_fetch_log (fetched_at, recognised, dropped, error) "
                "VALUES (?,?,?,?)",
                (r["fetched_at"], r["recognised"], r["dropped"], r["error"]))
        conn.commit()
    finally:
        conn.close()


def _five_hit_page():
    """真實 fixture（5 筆）—— 沿用第 4 輪的樣本，不手寫。"""
    from tests.test_tender_match_2026_09_21 import REAL
    return REAL


def _set_first_scan_at(value):
    """寫入 `tender_radar_first_scan_at`。

    ⚠️ **用 `helpers/settings.py::_set_setting`，不要自己寫 SQL**（B 抓到、A 複驗、
    我自己也查過 `db.py:323`）：`system_settings` 的欄位是
    `(key, value_json, updated_at)` 不是 `value`；而且 `_get_setting` 會
    `json.loads(row["value_json"])`，**裸字串會丟例外並靜默回 default**。
    ⇒ **改對欄位名還不夠**，那支函式就是為這件事存在的接縫。
    """
    from helpers.settings import _set_setting
    _set_setting("tender_radar_first_scan_at", value)


#: 預設凍在 18 點 —— 它同時是預設抓取時段與預設寄信時段（`9,12,15,18` / `18`）。
#: ⚠️ 凍在 9 點的話會抓但不寄，而這個檔大半在驗「有沒有寄」。
DEFAULT_TEST_HOUR = 18


def _run(monkeypatch, page=None, error=None, enabled=True,
         hour=DEFAULT_TEST_HOUR):
    """跑一次排程掃描，`fetch_raw` 換成固定回應。

    ## 🔴 2026-09-21 §3j：**一定要把時間凍住**

    抓取與寄信都改成「按時段」之後，`run_scheduled_scan()` 在非時段時**什麼都不做**
    ⇒ 這個檔的題目會在一天的大部分時間紅，而紅的訊息是
    「應該寄 1 封，實際 0 封」—— **看起來像通知功能壞了。**

    🔑 這不是「加個保險」，是**這些題目的前提從「每天一次」變成「在某個時段」**。
    ⚠️ 凍在 `_run` 裡而不是逐題凍：**逐題凍就是下一個漏掉的人的成因。**
    """
    freeze_slot(monkeypatch, ts, hour)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", enabled)
    _spy(monkeypatch, ts, "fetch_raw", result=(page, error))
    # 🔴 `fetch_detail` 也要換掉，否則 `parse_list(REAL)` 解出來的**真實網址**
    # 會被拿去 `urlopen` —— 真的連到政府採購網（NETGUARD 會在收尾時紅）。
    # ⚠️ 換在這裡而不是逐題換：只有一題記得換，正是這個洞當初的成因。
    if not hasattr(ts.fetch_detail, "_is_test_stub"):
        _stub = lambda url, *a, **kw: (None, "測試不抓詳細頁")   # noqa: E731
        _stub._is_test_stub = True
        monkeypatch.setattr(ts, "fetch_detail", _stub)
    _need(ts, "run_scheduled_scan")()


def test_n1_one_email_per_day_not_per_tender(client, admin_with_email, monkeypatch):
    """§3 N1：命中 5 筆 → **真的寄出 1 封**（不是 5 封）。"""
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())
    _assert_mails(mails, 1)


def test_n2_no_hits_means_no_email(client, admin_with_email, monkeypatch):
    """§3 N2：命中 0 筆 → 0 封。「今天沒標案」不是異常，不該打擾任何人。"""
    from tests.test_tender_match_2026_09_21 import HTML_EMPTY_RESULTS
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=HTML_EMPTY_RESULTS)
    assert len(mails) == 0, f"零命中不該寄信，實際 {len(mails)} 封"


def test_n3_fetch_failure_sends_one_email(client, admin_with_email, monkeypatch):
    """§3 N3：抓取失敗 → 1 封（§T.6：**雷達瞎了要有人知道**）。"""
    _seed_log([])
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=None, error="timeout after 15s")
    _assert_mails(mails, 1)


def test_n4_seven_days_of_failure_sends_only_one(client, admin_with_email, monkeypatch):
    """§3 N4：連續 7 天失敗 → **總共 1 封**（邊緣觸發）。

    ⚠️ **站台掛一週不可以變成七封信** —— 狼來了的告警等於沒有告警。
    """
    _seed_log([{"fetched_at": "2026-09-%02dT09:00:00" % d, "recognised": None,
                "dropped": 0, "error": "timeout"} for d in range(14, 21)])
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=None, error="timeout after 15s")
    assert len(mails) == 0, (
        f"已經連續失敗好幾天，今天不該再寄，實際 {len(mails)} 封 —— 那是準位觸發"
    )


def test_n5_fail_recover_fail_sends_again(client, admin_with_email, monkeypatch):
    """§3 N5：失敗 → 恢復 → 又失敗 → **要再寄一次**。

    ⚠️⚠️ **沒有這題，「這輩子只發一次」的實作會完整通過** —— 而它在第二次
    真的壞掉時是**啞的**。
    🔑 跟去重要驗兩個方向是同一件事：**該發的有發、該停的有停。**
    """
    _seed_log([
        {"fetched_at": "2026-09-18T09:00:00", "recognised": None, "dropped": 0,
         "error": "timeout"},
        {"fetched_at": "2026-09-19T09:00:00", "recognised": 1, "dropped": 0,
         "error": ""},
    ])
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=None, error="timeout again")
    _assert_mails(mails, 1)


def test_n6_suspected_redesign_is_a_different_event(
    client, admin_with_email, monkeypatch
):
    """§3 N6：`suspect_redesign` 為真 → 1 封，且**與 N3 不同的事件 key**。

    ⚠️ 兩者處置相反：**改版要改解析器、掛掉只要等它好**。
    共用一個 key 的話，使用者關掉其中一個就同時關掉另一個。
    """
    from tests.test_tender_match_2026_09_21 import HTML_MOSTLY_DROPPED
    _seed_log([])
    changed = _spy(monkeypatch, en, NOTIFY_CHANGED)
    failed = _spy(monkeypatch, en, NOTIFY_FAILED)
    _run(monkeypatch, page=HTML_MOSTLY_DROPPED)
    assert len(changed) == 1, f"疑似改版要通知一次，實際 {len(changed)} 次"
    assert len(failed) == 0, "疑似改版不可以走「抓不到」那個事件 key —— 處置不同"


@pytest.mark.parametrize("key", [EVENT_FOUND, EVENT_FAILED, EVENT_CHANGED])
def test_n6b_event_keys_are_registered(client, key):
    """三個事件 key 都要登記進 `EVENT_KEYS`。

    📌 既有守門 `test_notification_prefs_coverage.py` 掃的是 `email_notify.py` 的
    **呼叫端**，所以三支獨立函式漏登記會紅；**一支函式帶 key 參數則掃不出來**。
    """
    assert key in np.EVENT_KEYS, (
        "事件 key `%s` 沒有登記進 notification_prefs.EVENT_KEYS" % key
    )


def test_n7_quiet_period_sends_nothing(client, admin_with_email, monkeypatch):
    """§3 N7：首次成功掃描起 **7 天內**，即使有命中 → 0 封。

    ⚠️ 起算點是**第一次成功掃描**不是「開關被打開」—— 常數翻開的時間無法查證，
    而**無法查證的起算點在正式機上完全不存在**。
    """
    import datetime as dt
    _set_first_scan_at("2026-09-21T09:00:00")
    _need(ts, "today")
    monkeypatch.setattr(ts, "today", lambda: dt.date(2026, 9, 24))
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())
    assert len(mails) == 0, f"純記錄模式 7 天內不該寄，實際 {len(mails)} 封"


def test_n8_day_eight_sends(client, admin_with_email, monkeypatch):
    """§3 N8：第 8 天有命中 → 1 封。

    ⚠️ N7 的對照組：沒有這題，一個「永遠不寄」的實作會讓 N7 全綠。
    """
    import datetime as dt
    _set_first_scan_at("2026-09-21T09:00:00")
    monkeypatch.setattr(ts, "today", lambda: dt.date(2026, 9, 29))
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())
    _assert_mails(mails, 1)


def test_n9_already_notified_tender_not_in_later_emails(
    client, admin_with_email, monkeypatch
):
    """§3 N9：同一標案已通知過 → **不出現在後續的信裡**。"""
    import db
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())
    _assert_mails(mails, 1)
    first_html = mails[0][2]

    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tender_fetch_log")
        conn.commit()
    finally:
        conn.close()
    # 📌 同上：DELETE 已經讓真實的那支回 False，不需要 patch。

    _run(monkeypatch, page=_five_hit_page())
    if len(mails) > 1:
        assert mails[1][2] != first_html, (
            "第二封信的內容跟第一封一模一樣 —— 已通知過的標案又被寄了一次"
        )


def test_n10_no_enabled_recipient_means_no_send(client, admin_with_email, monkeypatch):
    """§3 N10：一個收件人都沒啟用 → `_async_send` 0 次。

    ⚠️ **要 patch 的是 `email_notify._pref_enabled`，不是
    `notification_prefs.is_enabled`**（A 裁決，我複驗過）：`email_notify.py:14` 是
    `from .notification_prefs import is_enabled as _pref_enabled` —— **一份副本**。
    **這是「patch 目標要走模組」的第六個實例，而且這次在既有碼裡。**

    ⚠️ 原本 §3 寫「驗沒有寫死的信箱字串」是**結構測試**（A 自己在 8b 禁止的），
    而且擋不住 `"admin" + "@" + "x.com"`。這一題驗行為。
    """
    _need(en, "_pref_enabled")
    mails = _sent(monkeypatch)
    monkeypatch.setattr(en, "_pref_enabled", lambda muted_json, event_key: False)
    _run(monkeypatch, page=_five_hit_page())
    assert len(mails) == 0, (
        f"一個收件人都沒啟用，卻呼叫了 {len(mails)} 次 _async_send"
    )


def test_n11_email_payload_carries_attribution(client, admin_with_email, monkeypatch):
    """§3 N11：信件內容含**資料出處標示**（§T.5 #6，授權條款要求）。

    ⚠️ 觀測點是**傳給 `_async_send` 的參數**，不是投遞結果。
    """
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())
    _assert_mails(mails, 1)
    body = mails[0][1] + mails[0][2]
    assert "政府電子採購網" in body or "web.pcc.gov.tw" in body, (
        "信件沒有資料出處標示（授權條款要求）。實際主旨=%r" % (mails[0][1],)
    )


def test_n12_send_failure_must_not_mark_as_notified(
    client, admin_with_email, monkeypatch
):
    """§3 N12：**寄信丟例外時，已通知標記不可以被設定**。

    ⚠️ 在寄信**之前**設定的話，那批標案**永遠不會再出現在任何一封信裡**，
    而且不會有任何錯誤訊息。**又一個「安靜地少做一件事」。**

    📌 N15 是它的下一層：這題只管「呼叫端丟例外時不標記」，
    而 N15 管「**投遞真的沒成功**時不標記」—— 後者才是 A 追鏈時抓到的那個洞。
    """
    _sending_fails(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())      # 不可以把例外往外丟
    assert _notified_count() == 0, (
        "寄信失敗了，卻有 %d 筆被標記成已通知 —— 那批標案永遠不會再出現在"
        "任何一封信裡，而且不會有錯誤訊息" % _notified_count()
    )


def test_n13_restart_during_outage_does_not_resend(
    client, admin_with_email, monkeypatch
):
    """§3 N13：**異常期間重啟服務，不可以重發**。

    🔑 **與 N5 是一對**：該發的有發（N5）、**不該重發的沒重發**（N13）。
    ⚠️ 「重啟」在測試裡的意義是「行程內狀態沒了」，所以這題只留資料庫裡的事實。
    **邊緣觸發的狀態必須是持久的**，存在行程記憶體裡的話每次重啟都會重寄。
    """
    _seed_log([{"fetched_at": "2026-09-20T09:00:00", "recognised": None,
                "dropped": 0, "error": "timeout"}])
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=None, error="still down")
    assert len(mails) == 0, (
        f"異常期間重啟不該重發，實際 {len(mails)} 封 —— "
        "邊緣觸發的狀態必須存在資料庫裡，不是行程記憶體裡"
    )


def test_n14_first_email_announces_the_quiet_period(
    client, admin_with_email, monkeypatch
):
    """§3 N14：**第 1 天那封信必須寫明接下來 7 天是純記錄模式**（A 新增）。

    ⚠️ 寄一封然後安靜一週，**從收件人的角度跟「壞掉了」完全一樣** ——
    而這條線的全部價值就是「不會漏掉標案」，讓收件人懷疑它壞了等於毀掉它。
    """
    import datetime as dt
    _set_first_scan_at("2026-09-21T09:00:00")
    monkeypatch.setattr(ts, "today", lambda: dt.date(2026, 9, 21))
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())
    _assert_mails(mails, 1)
    body = mails[0][1] + mails[0][2]
    assert "7" in body and ("純記錄" in body or "不會再寄" in body), (
        "第 1 天那封信沒有說明接下來 7 天不會再寄信 —— 收件人會以為它壞了。"
        "實際主旨=%r" % (mails[0][1],)
    )


def test_n14b_quiet_period_notice_only_in_the_first_email(
    client, admin_with_email, monkeypatch
):
    """§3 N14b：那句話**只能出現在「純記錄期開始」的那一封**（B 提，A 採用）。

    ⚠️ 每封都寫的話，**第 8 天恢復之後的信也會說「接下來 7 天不會再寄信」——
    而那是錯的**，收件人會**第二次**以為它壞掉了。

    🔑 B 那個判斷條件值得單獨記：
    觸發條件是「**這一封寄出去之後就要進入靜默**」，**不是「現在在靜默期」** ——
    因為**靜默期裡根本不寄信，所以後者永遠不會觸發**。
    ⇒ **一個永遠為假的條件寫起來完全合理，而且不會有任何紅燈。**

    ⚠️ 這題是「斷言某個字串不存在」，本身很弱（信是空的也會過），
    所以先用 `_assert_mails` 釘住「**這確實是一封寄得出去的真信**」再驗它沒那句話。
    """
    import datetime as dt
    _set_first_scan_at("2026-09-21T09:00:00")
    monkeypatch.setattr(ts, "today", lambda: dt.date(2026, 9, 29))   # 第 8 天
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())

    _assert_mails(mails, 1)          # 先證明這是一封真的信，不是空的
    body = mails[0][1] + mails[0][2]
    assert "純記錄" not in body and "不會再寄" not in body, (
        "第 8 天（靜默期已結束）那封信仍然寫著「接下來不會再寄信」—— "
        "那是錯的，收件人會第二次以為它壞了。"
        "實際主旨=%r" % (mails[0][1],)
    )


def test_n15_real_send_failure_does_not_mark_and_retries_next_time(
    client, admin_with_email, monkeypatch
):
    """§3 N15：**寄信真的失敗時不標記，而且那批標案要出現在下一次的信裡**。

    ⚠️⚠️ 這是 A 追端到端鏈時抓到的缺陷，而它正是
    「**每一次把觀測點往下游移一步，都要再問一次『這一步之後還有沒有東西會讓它
    安靜地不發生』**」的直接應用：

    `_async_send`（`email_notify.py:185`）是**射後不理** —— 只開一條執行緒，
    而 `_send` 裡有**五個安靜的 return**（功能未啟用／非正式機被擋／收件人空／
    SMTP 未設定／SMTP 例外），**一個都傳不回呼叫端**。
    ⇒ `_mark_hits_notified()` 在這五種情況下**照樣執行**，
    **標案被標記成「已通知」而信根本沒出去，且永遠不會再出現在任何一封信裡。**

    🔴 **這直接打破這條線的承諾「不會漏掉標案」，而最可能的觸發是
    「SMTP 還沒設定」—— 也就是使用者第一次啟用的那一天。**

    ⚠️ N12 攔不住它：N12 驗的是「`notify_tender_found` 有沒有丟例外」，
    而失敗發生在**那之後**的背景執行緒裡。**名字承諾兩層，觀測點只蓋住一層。**
    """
    # 第一次：投遞真的失敗
    _sending_fails(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())      # 不可以把例外往外丟
    assert _notified_count() == 0, (
        "投遞失敗了，卻有 %d 筆被標記成已通知 —— "
        "那批標案永遠不會再出現在任何一封信裡" % _notified_count()
    )

    # 第二次：投遞正常 → 那批標案要真的出現在這一封裡
    _allow_rerun_today(monkeypatch)
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())
    _assert_mails(mails, 1)
    assert _notified_count() > 0, (
        "第二次投遞成功了，卻一筆都沒被標記 —— 下一次還會再寄一遍同樣的標案"
    )
    body = mails[0][1] + mails[0][2]
    assert "TYGH115152" in body or "監視" in body, (
        "第一次沒寄成功的標案沒有出現在第二封信裡 —— 它們被漏掉了。"
        "實際主旨=%r" % (mails[0][1],)
    )


def test_n16_smtp_not_configured_does_not_mark(client, admin_with_email, monkeypatch):
    """§3 N16：**SMTP 未設定時同 N15**（不標記、下次再寄）。

    ⚠️ 這不是錯誤是「還沒設定」，但**結果一樣不可以標記** ——
    而且它是**使用者第一次啟用那一天最可能發生的情況**。

    🔑 這題刻意**走真正的程式路徑**（讓 `_cfg()` 回一份沒有帳密的設定），
    不是把投遞函式整支換掉 —— 換掉的話驗到的是我自己造的例外，
    **而不是「SMTP 沒設定時系統真的會拒絕寄出」**。
    """
    _need(en, "_cfg")
    monkeypatch.setattr(en, "_cfg", lambda: {"enabled": True, "smtp_host": "x",
                                             "smtp_port": 587, "smtp_user": "",
                                             "smtp_password": ""})
    if hasattr(en, "_smtp_send_blocked"):
        monkeypatch.setattr(en, "_smtp_send_blocked", lambda subject: False)

    _run(monkeypatch, page=_five_hit_page())      # 不可以把例外往外丟
    assert _notified_count() == 0, (
        "SMTP 沒設定、信根本沒出去，卻有 %d 筆被標記成已通知 —— "
        "使用者第一次啟用那天就會靜默漏掉一批標案" % _notified_count()
    )


def test_n15b_failed_alert_does_not_consume_the_edge(
    client, admin_with_email, monkeypatch
):
    """§3 N15b：**抓取失敗的告警寄不出去時，「已告警」的邊緣狀態不可以被消耗掉**。

    ⚠️⚠️ **這個比 N15 嚴重一級**（視窗 B 抓到）：

        第 1 天  抓取失敗 → 寫 tender_fetch_log（recognised=NULL）
                 previous["failed"] 還是 False ⇒ 寄「抓不到」的告警
                 投遞失敗（五種安靜 return 之一）⇒ **信沒出去**
        第 2 天  previous["failed"] 現在是 True ⇒ **不再寄**

    ⇒ **邊緣被消耗掉了，而信根本沒出去。雷達從此瞎著，而沒有任何人會知道** ——
      因為邊緣觸發**保證了它不會再試**。

    > **N15 是「漏掉幾筆標案」；這一題是漏掉「雷達壞了」這件事本身。**

    🔑 邊緣觸發的狀態**必須在投遞成功之後才推進**，不是在決定要寄的時候。
    """
    _seed_log([])

    # 第 1 天：抓取失敗，而且告警也寄不出去
    _sending_fails(monkeypatch)
    _run(monkeypatch, page=None, error="timeout day1")

    # 第 2 天：仍然抓取失敗，但這次投遞正常 —— **必須再寄一次**
    _allow_rerun_today(monkeypatch)
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=None, error="timeout day2")

    _assert_mails(mails, 1)
    # 這一封必須是「抓不到」那一類，不是「找到標案」
    subject = mails[0][1]
    assert "標案雷達" in subject or "抓" in subject or "失敗" in subject, (
        "第 2 天寄出的不是抓取失敗的告警？實際主旨=%r" % (subject,)
    )


def _remove_all_watches():
    """把搜尋條件清空 —— N17／N17b 要的是「使用者還沒設定任何條件」那個狀態。

    ⚠️ `admin_with_email` 預設會種一筆（否則 `tender_hits` 永遠是空的，
    見〈給彙整〉29）。這兩題要的正好是相反的前提，所以明確清掉。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tender_watches")
        conn.commit()
    finally:
        conn.close()


def _watch_count():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) c FROM tender_watches").fetchone()["c"]
    finally:
        conn.close()


def test_n17_no_watches_means_no_found_email(client, admin_with_email, monkeypatch):
    """§3 N17：**一列 `tender_watches` 都沒有時，不可以寄「找到標案」的信**。

    ⚠️ 這是我實測到的：沒有任何搜尋條件時，系統仍然寄出「5 筆新標案」——
    **使用者還沒設定關鍵字之前，就會收到全部標案的通知。**

    理由在 SPEC 自己身上（§T.4）：「**沒有排除詞，這功能會在第三天就被使用者關掉**」
    —— 而「**一條件都沒有**」比「沒有排除詞」更吵。

    📌 這一題刻意挑**純記錄期之後**的日子，讓「第 1 天的公告信」不會混進來 ——
    否則 0 封與 1 封的差別會說不清是哪一種信。
    """
    import datetime as dt
    _remove_all_watches()
    assert _watch_count() == 0, "前提沒成立：搜尋條件沒有被清掉"
    _set_first_scan_at("2026-09-21T09:00:00")
    monkeypatch.setattr(ts, "today", lambda: dt.date(2026, 9, 29))   # 第 8 天
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())
    assert len(mails) == 0, (
        "一列搜尋條件都沒有，卻寄了 %d 封「找到標案」的信 —— "
        "使用者還沒設定關鍵字就收到全部標案，那會讓他第三天就把功能關掉。"
        "實際主旨=%r" % (len(mails), mails[0][1] if mails else None)
    )


def test_n17b_first_email_tells_user_to_configure_watches(
    client, admin_with_email, monkeypatch
):
    """§3 N17b：一條件都沒有時，**第 1 天那封要寫明「你還沒設定任何搜尋條件」**。

    ⚠️ **只做 N17 會變成「安靜的無事發生」** —— 雷達裝好了、開著、而永遠不寄信，
    從使用者的角度跟「壞掉了」完全一樣。
    🔑 **把「不做事」變成「說一句話」，成本是一行，省掉的是一次
    「這功能是不是壞了」的懷疑。**

    ⚠️ 這題也是否定式斷言的反面：N17 驗「不寄」，**而不寄本身可能只是壞掉**。
    這一題就是 N17 的對照組 —— **證明系統在該說話的時候有說話。**
    """
    import datetime as dt
    _remove_all_watches()
    assert _watch_count() == 0, "前提沒成立：搜尋條件沒有被清掉"
    _set_first_scan_at("2026-09-21T09:00:00")
    monkeypatch.setattr(ts, "today", lambda: dt.date(2026, 9, 21))   # 第 1 天
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())

    _assert_mails(mails, 1)          # 先證明這是一封寄得出去的真信
    body = mails[0][1] + mails[0][2]
    # ⚠️ 不可以只驗「關鍵字」或「搜尋條件」這兩個詞：**N14 的純記錄期公告裡本來就有
    # 「請到畫面上確認關鍵字是否準確」** —— 我第一版就是這樣寫的，於是它
    # **在 B 還沒實作 N17b 的情況下就綠了**（實測：那封普通的「5 筆新標案」
    # 同時含「搜尋條件／關鍵字／純記錄／不會再寄」四個詞）。
    # 🔑 **兩封信共用的詞分不出兩封信。** 要挑只有這一封會說的話。
    assert "還沒設定" in body or "尚未設定" in body, (
        "第 1 天那封信沒有說「你還沒設定任何搜尋條件」—— "
        "他會看到一個裝好了卻永遠不寄信的雷達。實際主旨=%r" % (mails[0][1],)
    )


def test_n17c_configured_user_is_not_told_to_configure(
    client, admin_with_email, monkeypatch
):
    """N17b 的反向對照：**已經設定過條件的人，不可以被叫去設定條件**。

    ⚠️ 沒有這一題，一個「每封信都寫『你還沒設定任何搜尋條件』」的實作會讓
    N17b 全綠 —— 而那對已經設好條件的使用者是錯的訊息，
    **他會以為自己的設定不見了**。

    🔑 跟 N14／N14b 是同一組形狀：**一句話只能出現在它為真的那一封。**
    """
    import datetime as dt
    assert _watch_count() >= 1, "前提沒成立：這題要的是「已經有搜尋條件」"
    _set_first_scan_at("2026-09-21T09:00:00")
    monkeypatch.setattr(ts, "today", lambda: dt.date(2026, 9, 21))
    mails = _sent(monkeypatch)
    _run(monkeypatch, page=_five_hit_page())
    _assert_mails(mails, 1)
    body = mails[0][1] + mails[0][2]
    assert "還沒設定" not in body and "尚未設定" not in body, (
        "使用者已經設定過搜尋條件，信裡卻說他「還沒設定」—— "
        "他會以為自己的設定不見了。實際主旨=%r" % (mails[0][1],)
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
