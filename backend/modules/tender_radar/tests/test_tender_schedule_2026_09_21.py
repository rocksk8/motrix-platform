"""§3j · **抓取與寄信頻率都可調**（使用者 2026-09-21 兩句裁示）。

> 「**我要可調整**」（他在畫面上讀到 `dailyLimitNote`「每日一次為硬上限，不可調整」）
> 「**信的頻率可調**」

```
抓取時段   預設 9,12,15,18     可改成 9,15 或只填 10
寄信時段   預設 18             可改成 9,18（一天兩封）／9,12,15,18／空（不寄）
```

🔑 **同一個機制、兩份設定。** 而「一天一封」變成**那份設定的一個值**，不是寫死的規則。

## ☠️ 這一輪最危險的不是新功能，是**三條既有測試會變成偶爾紅的綠燈**

D 的推演（我複核過，正確）：`S4`／`D13`／第 4 輪 `9c` 三條的斷言是
「呼叫兩次 → 只抓一次」，**改成時段語意之後那個斷言仍然成立** ⇒ 題目不會紅。
**但三條都沒有控制時間**：若剛好在 **8:59 跑第一次、9:00 跑第二次**
（或 11:59/12:00、14:59/15:00、17:59/18:00）⇒ 跨時段 ⇒ 抓兩次 ⇒ **紅**。

🔴 **一天有 4 個這種邊界，而它們全部落在上班時間。**
⇒ 失敗率低、無法重現、**而且看起來像真的有 bug**。
🔑 **那比紅燈貴**：紅燈會被修，偶爾紅的綠燈會被重跑一次然後忘掉。

⚠️ **所以 SL9 釘的是「時間來源換得掉」這個接縫**，不是改描述。
📌 B 要抽的**不是新東西**：`tender_source.py:161` 的 `today()` docstring 自己就寫著
「**存在的理由是讓測試換得掉**」—— 這個模組早就接受這個模式了，**缺的是時段層級**。
（`today()` 只給日期；時段需要小時 ⇒ 要嘛擴充它、要嘛新增 `now_dt()`。）

## 📌 我釘的名字（§3j 沒有全部指定，B 若要改請先講）

| 名字 | 形狀 |
|---|---|
| `tender_source.now_dt()` | 模組層的 `datetime` 來源（比照 `today()`）|
| `tender_source.current_slot()` | 現在屬於哪個抓取時段，回小時（`int`）或 `None` |
| 設定鍵 `tender_radar_scan_hours` | 抓取時段，逗號分隔，預設 `"9,12,15,18"` |
| 設定鍵 `tender_radar_notify_hours` | 寄信時段，逗號分隔，預設 `"18"`，**允許空字串＝不寄** |
| 設定鍵 `tender_radar_notify_last_slot` | 「這個時段寄過沒」單鍵 ＋ `>=` 比較（SL7）|

⚠️ 舊的單數鍵 `tender_radar_scan_hour`（第 6 輪 D12～D14）會被複數版取代 ——
**那是一個既有設定的語意變更，不是新增**，B 要決定既有值怎麼遷移。

## ⚠️ 這個檔**不涵蓋**的 SL（照實列，免得被當成驗過了）

| | 為什麼驗不到 |
|---|---|
| **SL11** `scan_hour()` docstring 寫錯 | **沒有任何測試能驗註解**。靠 A 結案時看 |
| **SL12** 前端 99／105 行是 UI 結構不是文案 | 「每天…自動掃描一次」那個句型與單選下拉都不成立，**要使用者目視** |
| **SL14** 「失敗也算用掉額度」的**理由**要改寫 | 同 SL11，註解驗不到 |
| **SL15** — | 規格裡沒有這一條（A 的清單跳號）|

🔑 **列出「我沒驗什麼」比列出「我驗了什麼」重要** ——
沒被列出來的那幾條會混在綠燈裡，看起來像被涵蓋了。
"""
import json

import pytest

import modules.tender_radar.source as ts
from helpers.settings import _get_setting, _set_setting

SCAN_HOURS_KEY = "tender_radar_scan_hours"
NOTIFY_HOURS_KEY = "tender_radar_notify_hours"
NOTIFY_MARK_KEY = "tender_radar_notify_last_slot"
#: 第 6 輪的**單數**舊鍵 —— 同一個設定的舊語意，正式機可能有值（SL17／SL18）
OLD_SCAN_HOUR_KEY = "tender_radar_scan_hour"

DEFAULT_SCAN_HOURS = "9,12,15,18"
DEFAULT_NOTIFY_HOURS = "18"


def _need(name):
    if not hasattr(ts, name):
        raise AssertionError(
            f"helpers/tender_source.py 缺少 `{name}` —— B 還沒做，或名字跟我釘的不一樣。"
            "見本檔開頭〈我釘的名字〉。"
        )
    return getattr(ts, name)


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _real_list_page():
    from modules.tender_radar.tests.test_tender_match_2026_09_21 import REAL
    return REAL


def _page_batch(n):
    """把真實樣本的**機關名**加一個批次尾碼，做出「這一批是新的」的頁面。

    ## 🔴 為什麼需要這個（B 讀出來的，我驗過原始碼）

        tender_source.py:565  INSERT OR IGNORE INTO tenders      UNIQUE (org, case_no)
        tender_source.py:582  INSERT OR IGNORE INTO tender_hits  UNIQUE (watch_id, tender_id)

    ⇒ **同一份頁面掃第二次，`new_hits` 就是 0。**
    我第一版讓四個時段都餵同一頁，於是「抓 4 寄 4」要求的行為
    **正是 SL16 要擋的那個行為**（沒有新命中也寄）。
    ☠️ **三題不可能同時綠 —— 而那不是我佈置寫錯，是規格本身有矛盾**
    （SL3「封數 == 設定的時段數」與 SL16「沒有新命中就不寄」只在
    「每個時段都剛好有新命中」時相容）。正確的統一規則是
    **封數 ==「有新命中的寄信時段」數**。

    ⚠️ 手術對象選**機關名**而不是案號：UNIQUE 是 `(org, case_no)`，
    改哪一個都行，而機關名改完仍然含中文、仍然不像日期
    ⇒ 不會撞到 `parse_list` 的形狀驗證（第 4 輪條件 6c 三道）。
    """
    from modules.tender_radar.tests.test_tender_match_2026_09_21 import (
        REAL, _get_cell, _rebuild, _split_results, _set_cell, COL_ORG,
    )
    _m, _header, data = _split_results(REAL)
    rows = [_set_cell(r, COL_ORG, _get_cell(r, COL_ORG) + f"第{n}批") for r in data]
    page = _rebuild(REAL, rows)
    assert page != REAL, "手術沒有改到任何東西 —— 樣本結構變了"
    return page


def _spy_fetch(monkeypatch, vary=False):
    """把 `fetch_raw` 換成計數器。⚠️ 觀測點是**呼叫次數**（SL1／SL2 明文）。

    `vary=True` ⇒ 每一次回**不同批**的頁面，讓每個時段真的出現新命中。
    """
    calls = []
    page = _real_list_page()

    def _rec(*a, **kw):
        calls.append(a)
        return (_page_batch(len(calls)) if vary else page, None)

    monkeypatch.setattr(ts, "fetch_raw", _rec)
    return calls


def _spy_mail(monkeypatch):
    """唯一的寄信觀測點 —— 沿用第 5 輪查出來的那一層（`_send_raising`）。

    ⚠️ **不可以觀測 `notify_tender_found` 被呼叫**（第 5 輪的假綠燈），
    也**不可以只觀測 `_async_send`**（它不檢查收件人是不是空的，
    空清單時執行緒照樣開、寫一行 log 就結束）。

    ## ⚠️ 而這個 patch 本身有一個無法避免的缺口，寫在這裡免得被當成有蓋到

    換掉 `_send_raising` ⇒ **它的本體在本檔一次都沒有被執行過。**
    ⇒ **本檔不涵蓋 `_send_raising` 內部，以及它下游的任何東西。**
    📌 這不是疏忽（測試不能真的寄信），但它的後果是具體的：
    今天那個 `email_notify.py:1494` 的 `NameError` 若發生在那一層，
    **這一整批題目會全綠。**
    🔑 **下一個人看到這裡有十幾題，會以為「寄信這條路被蓋住了」** ——
    蓋住的是「有沒有走到寄信」，不是「寄信本身會不會炸」。
    （那一層由 `test_backup_stale_alert_2026_09_21.py` 另外處理。）
    """
    import helpers.email_notify as en
    _ = _need  # 讓讀的人知道下面那個 hasattr 是刻意的
    assert hasattr(en, "_send_raising"), (
        "helpers/email_notify.py 缺少 `_send_raising` —— 第 5 輪定案的觀測點"
    )
    calls = []
    monkeypatch.setattr(
        en, "_send_raising",
        lambda to_addrs, subject, html: calls.append((to_addrs, subject, html)))
    return calls


def _at_time(monkeypatch, hour):
    """把**時間來源**換掉 —— 不是把 `current_slot()` 換掉。

    ## 🔴 為什麼不 patch `current_slot()`（我第一版就是那樣寫的）

    `current_slot()` 內部要讀 `tender_radar_scan_hours` 設定。
    ⇒ **我 patch 掉它，就把「有沒有查設定」這件事一起 patch 掉了。**
    SL6（設定 `9,15`）與 SL16（設定 `""`）於是都沒有真的走到設定判斷那一段，
    而它們**各自假設了那段判斷發生在不同的地方** —— 我自己寫得不一致。

    🔑 這是今天那一族（**觀測手段與被測對象共用一段程式碼**）的第五個實例，
    而這一次是我自己造的：T4 的 `_pid_alive`／我的診斷 `print`／
    `geocode` 的快取／M4 的總開關位置／這一個。

    ⇒ 換掉最底層那個會碰系統時鐘的東西（`now_dt()`），
    讓 `current_slot()` 自己去讀設定、自己去推導。
    """
    from datetime import datetime

    fixed = datetime.combine(ts.today(), datetime.min.time()).replace(hour=hour)
    monkeypatch.setattr(ts, "now_dt", lambda: fixed)


@pytest.fixture()
def radar_ready(client, monkeypatch):
    """有 email 的 admin ＋ 一筆搜尋條件 ＋ 總開關打開。

    ⚠️ 缺 watch 的話 `tender_hits` 永遠是空的，而「有沒有寄信」就不可觀測 ——
    第 5 輪那個假綠燈正是這樣產生的（〈給彙整〉29）。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, email, "
            "modules, active, created_at, must_change_password, notification_muted) "
            "VALUES (?,?,?,?,?,?,1,?,0,?)",
            ("sl_boss", "x", "收件人", "superadmin", "boss@example.invalid",
             "[]", "2026-01-01T00:00:00", "[]"))
        conn.execute(
            "INSERT INTO tender_watches (name, keywords, enabled) VALUES (?,?,1)",
            ("監視系統", '["監視"]'))
        conn.commit()
    finally:
        conn.close()
    # 🔴 **`fetch_detail` 一定要一起換掉，而且是在 fixture 裡換不是逐題換。**
    # `_spy_fetch` 只換了 `fetch_raw`（清單頁），而 `parse_list(REAL)` 解出來的
    # `url` 是**真的網址** ⇒ `run_scan` → `_fetch_details` → `fetch_detail`
    # → `urlopen` → **真的對政府採購網連出去**（B 量到單一題 5 次）。
    # ⚠️ 逐題加正是「只有 SL10 記得加」的成因 —— 這裡換一次，全檔都蓋到。
    monkeypatch.setattr(
        ts, "fetch_detail", lambda url, *a, **kw: (None, "測試不抓詳細頁"))
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    _set_setting(SCAN_HOURS_KEY, DEFAULT_SCAN_HOURS)
    _set_setting(NOTIFY_HOURS_KEY, DEFAULT_NOTIFY_HOURS)
    return "boss@example.invalid"


# ══════════════════════════════════════════════════════════════════════
# SL1／SL2 · 抓取按時段節流
# ══════════════════════════════════════════════════════════════════════

def test_sl1_same_slot_twice_fetches_once(radar_ready, monkeypatch):
    """SL1：**同一個時段內觸發兩次 → `fetch_raw` 只被呼叫 1 次。**"""
    calls = _spy_fetch(monkeypatch)
    _spy_mail(monkeypatch)
    _at_time(monkeypatch, 9)
    run = _need("run_scheduled_scan")
    run()
    run()
    assert len(calls) == 1, f"同一個時段抓了 {len(calls)} 次"


def test_sl2_different_slots_fetch_twice(radar_ready, monkeypatch):
    """🔴 SL2：**9 點一次、12 點一次 → `fetch_raw` 被呼叫 2 次。**

    ⚠️ **SL1／SL2 必須分開** —— 只有 SL1 的話，
    一個「**永遠只抓一次**」的實作會全綠，而那就是現在的行為（每日一次）。
    🔑 SL1 驗的是節流有沒有生效，SL2 驗的是**它有沒有在該放行的時候放行**。
    """
    calls = _spy_fetch(monkeypatch)
    _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")
    _at_time(monkeypatch, 9)
    run()
    _at_time(monkeypatch, 12)
    run()
    assert len(calls) == 2, (
        f"跨時段只抓了 {len(calls)} 次 —— 節流還是「每天一次」的語意"
    )


def test_sl6_two_configured_slots_mean_two_fetches(radar_ready, monkeypatch):
    """SL6：時段設定改成 `9,15` → **一天只抓 2 次**（12 與 18 不抓）。"""
    _set_setting(SCAN_HOURS_KEY, "9,15")
    calls = _spy_fetch(monkeypatch)
    _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")
    for hour in (9, 12, 15, 18):
        _at_time(monkeypatch, hour)
        run()
    assert len(calls) == 2, (
        f"設定只有兩個時段，卻抓了 {len(calls)} 次 —— 設定沒有被讀到"
    )


# ══════════════════════════════════════════════════════════════════════
# SL9 · 時間來源換得掉（這一輪最貴的一題）
# ══════════════════════════════════════════════════════════════════════

def test_sl9_the_time_source_is_a_module_attribute():
    """🔴 SL9：`current_slot()` 與 `now_dt()` 必須是**模組層屬性**。

    ⚠️ B 沒抽出這個接縫的話，**我不是拿到紅燈，是寫不出測試** ——
    那是 D 指出 A 原本寫法的問題：「對 B 的實作要求」沒有斷言形式。

    📌 而這不是新模式：`tender_source.py:161` 的 `today()` 就是同一件事，
    docstring 寫著「存在的理由是讓測試換得掉」，`_already_fetched_today()` 已經走它。
    🔴 **沒走的是 `_seconds_until_next_run()`（915）—— 它直接 `datetime.now()`，
    patch 不到。** 那一支也要改走同一個來源。
    """
    assert callable(_need("current_slot"))
    assert callable(_need("now_dt")), (
        "`today()` 只給日期，而時段判定需要小時 —— 要有一個給得出時刻的來源"
    )


def test_sl9b_patching_the_slot_changes_the_behaviour(radar_ready, monkeypatch):
    """🔴 SL9 的斷言形式：**換掉時段來源之後，同一組呼叫的行為要改變。**

    這一題與 SL1／SL2 的機制相同，**但它問的是另一件事**：
    SL1／SL2 問「節流對不對」，**這一題問「那個接縫真的被用上了嗎」**。
    ⚠️ 一個內部偷偷用 `datetime.now()` 的實作會讓 SL1／SL2 **在多數時刻是綠的**，
    而它正是那 4 個邊界上偶爾紅的來源。
    🔑 **「算得對」與「被接上」是兩個問題**（今天第三次）。
    """
    calls = _spy_fetch(monkeypatch)
    _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")
    _at_time(monkeypatch, 9)
    run()
    run()
    same_slot = len(calls)
    _at_time(monkeypatch, 15)
    run()
    assert same_slot == 1 and len(calls) == 2, (
        f"同一時段跑兩次得到 {same_slot} 次抓取、換時段之後累計 {len(calls)} 次；"
        "應為 1 與 2。⇒ 節流沒有讀 `current_slot()`，它自己去問了系統時間。"
    )


# ══════════════════════════════════════════════════════════════════════
# SL3／SL4／SL16 · 寄信次數 == 設定的寄信時段數
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("notify_hours,expected", [
    ("18", 1),                  # 抓 4 寄 1 —— 使用者先前選的那個
    ("9,12,15,18", 4),          # 抓 4 寄 4 —— 每抓完就寄
    ("", 0),                    # 🔴 抓 4 寄 0 —— **可調整包含「調成不寄」**
])
def test_sl3_mail_count_equals_configured_notify_slots(
        radar_ready, monkeypatch, notify_hours, expected):
    """🔴🔴 SL3：**寄出的封數 == 設定的寄信時段數**，不是寫死的 1。

    🔑 本輪最重要的一題：**抓取與通知解耦**。

    📌 **`""`（寄 0 封）那一組是重點** —— 一個把寄信寫成無條件的實作
    會在前兩組綠、在這一組紅。**可調整包含「調成不寄」**，
    而那是最容易被實作漏掉的一個值（因為它看起來像「沒設定」）。

    ⚠️ **範圍（D 修正 A）**：這一題擋得掉「一天四封信」，
    **擋不掉「只寄最後一次抓到的」** —— 那是 SL5 的事。**它是不完備，不是無效。**

    🔴 **而它也擋不掉「每個寄信時段無條件寄一封」**（B 指出）：
    這裡每個時段都有新命中，所以兩種實作都會給出同樣的封數。
    ⇒ **鑑別那一個壞法的是 `SL3b` 與 `SL16`**，不是這一題。
    **三題要一起看，單獨一題都不完備。**
    """
    _set_setting(NOTIFY_HOURS_KEY, notify_hours)
    # ⚠️ `vary=True` 是必要的，不是講究：同一頁掃第二次 `new_hits` 是 0
    # （`INSERT OR IGNORE` ＋ UNIQUE），那時「抓 4 寄 4」要求的行為
    # **正是 SL16 要擋的那個**。見 `_page_batch` 的說明。
    _spy_fetch(monkeypatch, vary=True)
    mails = _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")
    for hour in (9, 12, 15, 18):
        _at_time(monkeypatch, hour)
        run()
    assert len(mails) == expected, (
        f"寄信時段設定成 {notify_hours!r}（{expected} 個時段），"
        f"實際寄了 {len(mails)} 封"
    )
    for to_addrs, _subject, _html in mails:
        assert to_addrs, (
            "收件人清單是空的 —— `_send` 會寫一行 log 就 return，"
            "而那看起來跟「寄出去了」一模一樣"
        )


def test_sl3b_only_slots_with_new_hits_send_a_mail(radar_ready, monkeypatch):
    """🔴🔴 SL3b：寄信時段有四個，而**只有兩個時段有新命中 ⇒ 只寄 2 封**。

    ## 🔑 這一題才是有鑑別力的那一題

    SL3 的每個時段都有新命中，所以「**每個時段無條件寄**」與
    「**有新命中才寄**」兩種實作**給出一樣的封數** ⇒ SL3 分不出它們。
    ⚠️ 而那兩種實作的差別，使用者會在「今天沒有新標案」那一天看到：
    一種安靜，另一種寄四封空信。

    📌 **統一的規則是「封數 ==『有新命中的寄信時段』數」** ——
    SL3 那句「封數 == 設定的時段數」是它的**特例**，
    而 §3j 原文把特例寫成了規則，於是與 SL16 互相排斥。
    （B 讀 `INSERT OR IGNORE` ＋ UNIQUE 推出來的，我驗過原始碼。）
    """
    _set_setting(NOTIFY_HOURS_KEY, "9,12,15,18")
    calls = []
    page_new = _page_batch(1)

    def _rec(*a, **kw):
        calls.append(a)
        # 第 1、3 次給新的一批；第 2、4 次給**重複的**（⇒ 沒有新命中）
        return (_page_batch(len(calls)) if len(calls) in (1, 3) else page_new, None)

    monkeypatch.setattr(ts, "fetch_raw", _rec)
    mails = _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")
    for hour in (9, 12, 15, 18):
        _at_time(monkeypatch, hour)
        run()

    assert len(calls) == 4, f"四個時段應該抓四次，實際 {len(calls)}"
    assert len(mails) == 2, (
        f"只有兩個時段出現新命中，卻寄了 {len(mails)} 封。\n"
        "⇒ 寄信寫成「每個寄信時段無條件寄一封」了。"
        "那在沒有新標案的那一天會寄四封空信，而收件人會學會忽略它們。"
    )


def test_sl19_notify_slot_is_independent_of_scan_slot(radar_ready, monkeypatch):
    """🔴 SL19：**抓取時段與寄信時段完全不重疊時，仍然要寄。**

    ```
    scan_hours   = "9"     ← 9 點抓
    notify_hours = "18"    ← 18 點寄
    現在是 18 點           ← 不抓，但**要寄**
    ```

    ## 🔑 這一題釘的是「判斷時段的入口必須獨立」（B 推出來的）

    `current_slot()` 內部讀的是 **`scan_hours`** ⇒ 18 點時它回 `None`。
    ⚠️ **寄信那一段若也問 `current_slot()`，就永遠拿不到小時** ——
    而後果**不會在預設設定下出現**（預設抓 9,12,15,18、寄 18，兩者重疊），
    ☠️ **要等到有人設「抓 9,15／寄 9,12,15,18」那天才爆。**

    ⇒ **抓取問 `current_slot()`，寄信問 `now_dt().hour`。**
    **兩個設定是獨立的，所以判斷時段的入口也必須是獨立的。**

    📌 這一題在原本的 14 題裡**一個都驗不到** —— 因為那 14 題的
    `scan_hours` 與 `notify_hours` 不是相同就是其中一個為空。
    🔑 **兩個獨立的設定，要有一題讓它們真的不一樣。**
    """
    _set_setting(SCAN_HOURS_KEY, "9")
    _set_setting(NOTIFY_HOURS_KEY, "18")
    calls = _spy_fetch(monkeypatch, vary=True)
    mails = _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")

    _at_time(monkeypatch, 9)        # 抓取時段：抓，但不是寄信時段
    run()
    assert len(calls) == 1, f"9 點是抓取時段，卻抓了 {len(calls)} 次"
    assert len(mails) == 0, "9 點不是寄信時段"

    _at_time(monkeypatch, 18)       # 寄信時段：不抓，但要寄
    run()
    assert len(calls) == 1, (
        f"18 點不在 scan_hours 裡，卻又抓了一次（累計 {len(calls)}）"
    )
    assert len(mails) == 1, (
        "18 點是寄信時段、而且 9 點抓到的命中還沒通知過，卻一封都沒寄。\n"
        "⇒ 寄信那一段八成在問 `current_slot()`，而它讀的是 `scan_hours`，"
        "18 點不在裡面 ⇒ 永遠拿不到小時。**兩個設定要有兩個入口。**"
    )


def test_sl16_no_new_hits_means_no_mail(radar_ready, monkeypatch):
    """🔴 SL16：**寄信時段到了而沒有新命中 → 不寄**（不是寄一封空的）。

    📌 這一題同時把 B 擔心的「**抓 0 寄 4**」那個組合關掉了：
    沒抓就沒有新命中 ⇒ 沒有東西可寄 ⇒ 排程觸發四次、四次都不寄。**合法且無害。**

    🔑 而 B 提這件事的方式值得記：
    **「我不主張做什麼，只是它應該是一個有人做過的決定，不是一個沒人想到的組合。」**
    ⚠️ **這一題本來就該存在，只是在「一天一封」的世界裡沒有人想到要問。**
    """
    _set_setting(SCAN_HOURS_KEY, "")            # 完全不抓
    _set_setting(NOTIFY_HOURS_KEY, "9,12,15,18")
    calls = _spy_fetch(monkeypatch)
    mails = _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")
    for hour in (9, 12, 15, 18):
        _at_time(monkeypatch, hour)
        run()
    assert len(calls) == 0, f"抓取時段是空的，卻抓了 {len(calls)} 次"
    assert len(mails) == 0, (
        f"沒有任何新命中，卻寄了 {len(mails)} 封 —— 那是一封空信。"
        "收件人會學會忽略它，然後真的有東西的那一封也一起被忽略。"
    )


def test_sl4_data_lands_even_outside_the_notify_slots(radar_ready, monkeypatch):
    """🔴 SL4：非寄信時段抓到新標案 → **資料要進資料庫**（當下不寄）。

    ⚠️ **斷言的重心刻意放在「資料有進去」**（D 指出）——
    「當下不寄」那一半**已經被 SL3 涵蓋**（SL3 綠 ⇒ 非寄信時段必然沒寄），
    重心不移的話 SL4 就只是 SL3 的子集。

    🔑 這一題保護的是使用者真正在乎的那件事：
    **標案要立刻出現在畫面上，不必等那封信。**
    """
    _set_setting(NOTIFY_HOURS_KEY, "18")
    _spy_fetch(monkeypatch)
    mails = _spy_mail(monkeypatch)
    _at_time(monkeypatch, 9)                    # 抓取時段，但不是寄信時段
    _need("run_scheduled_scan")()

    import db
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT COUNT(*) c FROM tenders").fetchone()["c"]
        hits = conn.execute("SELECT COUNT(*) c FROM tender_hits").fetchone()["c"]
    finally:
        conn.close()
    assert rows > 0, "9 點抓到的標案沒有進資料庫 —— 使用者要等到 18 點才看得到"
    assert hits > 0, "命中紀錄沒有進資料庫"
    assert len(mails) == 0, "9 點不是寄信時段（這一半 SL3 也蓋得到）"


# ══════════════════════════════════════════════════════════════════════
# SL5／SL7 · 每封只含新的；通知標記與抓取標記分開
# ══════════════════════════════════════════════════════════════════════

def test_sl5_each_mail_only_contains_hits_new_since_the_last_one(
        radar_ready, monkeypatch):
    """🔴 SL5：**每一封只含「上一封之後新發現的」，而且不重複。**

    ✅ 這一題便宜：`tender_hits.notified_at` 已經存在、與抓取分離（`test_n9` 驗過）
    ⇒ **不管寄幾封，「不重複」自動成立。這一題釘的是「它有沒有真的被用上」。**

    🔴 **而它不是「讓 SL3 變得有效」，是「補 SL3 的盲區」**（D 修正 A）：
    「每次抓取都寄信」那個實作會讓 **SL3 紅**（4 次抓取 → 4 封 ≠ 1），
    所以 SL3 自己站得住。SL5 補的是「只寄最後一次抓到的」那個 SL3 抓不到的壞法。
    ⚠️ **兩條都要留，而理由要寫對** —— 否則下一個人會把它們合併成一條。
    """
    _set_setting(NOTIFY_HOURS_KEY, "9,18")
    _spy_fetch(monkeypatch, vary=True)
    mails = _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")

    _at_time(monkeypatch, 9)
    run()
    assert len(mails) == 1, f"9 點應該寄一封，實際 {len(mails)}"
    first_html = mails[0][2]

    _at_time(monkeypatch, 18)
    run()
    assert len(mails) == 2, (
        f"18 點應該再寄一封，實際共 {len(mails)} 封 —— "
        "第二個寄信時段沒有寄，或第一封之後的標記寫錯了"
    )
    second_html = mails[1][2]

    import re

    def _batches(html):
        """信裡出現了哪幾批。

        ## 🔴 我第一版釘的是**案號**，而信裡根本沒有案號

        `notify_tender_found()` 組的列是
        `name` ／ `機關 {org}　地點 {location}` ／ `預算 … 截止 …`
        —— **沒有 `case_no`**。
        ⇒ 我的 regex 永遠回空集合 ⇒ `not repeated` **永遠成立**。

        🔑 **斷言寫對、觀測點指向一個信裡不存在的東西** —— 今天第五次同一族。
        ✅ 而這一次是**我自己加的前提斷言**（`assert _case_nos(first_html)`）抓到的，
        不是別人指出來的。**那道前提就是為了這件事加的。**

        ⇒ 改釘 `_page_batch(n)` 放進**機關名**的尾碼：那是我控制的、
        而且它確實會被渲染進信裡。
        """
        return set(re.findall(r"第(\d+)批", html or ""))

    _case_nos = _batches      # 下面沿用同一個名字

    # 🔴 **先證明第二封裡真的有東西**（B 抓到的空集合假綠燈）：
    # 第二封是空的時候，交集必然是空集合 ⇒ 下面那個斷言**必然綠**。
    # 🔑 「沒有重複」與「第二封根本沒有東西」不可以長得一樣。
    assert _case_nos(first_html), (
        "**第一封**信裡一個案號都沒有 —— 兩邊都空的時候交集也是空的，"
        "下面那個斷言一樣會空過去。"
    )
    assert _case_nos(second_html), (
        f"第二封信裡一個案號都沒有 —— 下面「不重複」那個斷言會空過去。\n"
        f"第二封內容前 300 字：{(second_html or '')[:300]!r}"
    )
    repeated = _case_nos(first_html) & _case_nos(second_html)
    assert not repeated, (
        f"這幾筆在兩封信裡都出現了：{sorted(repeated)}\n"
        "⇒ `tender_hits.notified_at` 沒有被用上。收件人會開始忽略重複的信，"
        "而真的有新東西的那一封也一起被忽略。"
    )


def test_sl7_clearing_the_fetch_log_does_not_resend_the_mail(
        radar_ready, monkeypatch):
    """🔴 SL7：**通知的標記與抓取的標記分開** —— 清掉抓取紀錄不可以讓信重寄。

    ## 🔑 這個理由是可查證的，不只是「語意上該分開」

    | 表 | 在每日 JSON 備份裡嗎 | 出處 |
    |---|---|---|
    | `system_settings` | ✅ 在 | `archive.py:1098` |
    | `tender_hits`（per-hit）| ✅ 在 | `archive.py:1150` |
    | `tender_fetch_log`（抓取側）| 🔴 **不在** | 三張 tender 表只登記 watches／tenders／hits |

    ☠️ **`tender_fetch_log` 還原之後是空的** ⇒ 把「寄過沒」放在那裡，
    **每一次災難還原都會重寄一次當天的彙總信。**
    📌 **⇒ 存在 `system_settings`，單鍵 ＋ `>=` 比較**（形狀比照 `daily_tasks`
    的 `dt_overdue_last_check` 與 `reports` 的 `monthly_report_last_sent` ——
    四種實作裡唯一被用過兩次的）。
    """
    _set_setting(NOTIFY_HOURS_KEY, "18")
    _spy_fetch(monkeypatch)
    mails = _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")

    _at_time(monkeypatch, 18)
    run()
    assert len(mails) == 1, f"18 點應該寄一封，實際 {len(mails)}"

    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tender_fetch_log")     # 模擬災難還原
        conn.commit()
    finally:
        conn.close()

    run()
    assert len(mails) == 1, (
        f"清掉 `tender_fetch_log` 之後又寄了一封（共 {len(mails)} 封）—— "
        "通知的標記放在抓取那一側了。而那張表不進每日備份，"
        "所以**每一次災難還原都會重寄當天的彙總信**。"
    )
    assert _get_setting(NOTIFY_MARK_KEY) is not None, (
        f"找不到通知側的標記 `{NOTIFY_MARK_KEY}` —— 見本檔開頭〈我釘的名字〉"
    )


# ══════════════════════════════════════════════════════════════════════
# SL10 · DETAIL_DAILY_LIMIT 的名字說謊
# ══════════════════════════════════════════════════════════════════════

def test_sl10_the_detail_limit_is_shared_across_slots(radar_ready, monkeypatch):
    """🔴 SL10：`DETAIL_DAILY_LIMIT` 要是**每天共用**，不是每個時段各一份。

    ## 🔴 現在的名字是說謊的（D 查出來，我複核過原始碼）

        def _fetch_details(conn, tender_ids):       # tender_source.py:431
            fetched = 0                              # ← 區域變數，每次呼叫重置
            if fetched >= DETAIL_DAILY_LIMIT: break

    🔑 **它現在是「每次呼叫最多 20 筆」。** 一天呼叫一次，
    兩者**恰好相等 —— 那是巧合，不是設計。**
    ⇒ 改成一天四個時段之後，實際上限**靜默變成 80**。

    ⚠️ **那正是「降級之後它還是會動」**：功能照跑、畫面正常，
    只是對政府網站的負載變四倍，**而沒有任何測試會紅**。

    📌 **嚴重度有一個緩解**（D 找到）：`_fetch_details` 的 SQL 是
    `WHERE t.location IS NULL OR t.location = ''` ⇒ 抓過的下次不會再進來
    ⇒ 除非一天新增 80 筆以上命中標案，實際不會真的變成 80。
    **但那是「不容易觸發」，不是「不會發生」。**

    ⇒ 要跨呼叫累計，這一題驗的是**第 4 個時段拿不到額度**。
    """
    monkeypatch.setattr(ts, "DETAIL_DAILY_LIMIT", 2)
    _set_setting(NOTIFY_HOURS_KEY, "")
    _spy_fetch(monkeypatch)
    _spy_mail(monkeypatch)

    detail_calls = []

    def _detail(url, *a, **kw):
        detail_calls.append(url)
        return (None, "測試不抓真的詳細頁")

    monkeypatch.setattr(ts, "fetch_detail", _detail)
    monkeypatch.setattr(ts, "DETAIL_INTERVAL_SECONDS", 0)

    run = _need("run_scheduled_scan")
    for hour in (9, 12, 15, 18):
        _at_time(monkeypatch, hour)
        run()

    # 🔴 **下界與上界都要**（A／D 稽核指出）：只有 `<= 2` 的話，
    # 一個「**根本不呼叫 `_fetch_details`**」的實作會讓 `0 <= 2` 成立 ⇒ 綠。
    # 🔑 **那一題就分不出「上限正確共用」與「根本沒抓」。**
    # 📌 我在別的檔做對過（`test_d3` 是 `assert len(calls) >= 2, "前提不成立"`），
    #    這裡沒做 —— 而 D 的普查也漏掉它，**因為那份普查用 `assert X == N` 的 regex，
    #    而這一行是 `<=`**。兩個人、兩種工具、同一種盲點：
    #    **判準的形狀決定了你看得見什麼。**
    assert len(detail_calls) >= 1, (
        "四個時段一次詳細頁都沒抓 —— 這一題的前提不成立（上限根本驗不到）。\n"
        "⇒ 先確認命中的標案真的有 `location IS NULL`，以及 `fetch_detail` 有被走到。"
    )
    assert len(detail_calls) <= 2, (
        f"每日上限設成 2，而四個時段一共抓了 {len(detail_calls)} 次詳細頁。\n"
        "⇒ `fetched` 是區域變數，每次呼叫重置 ⇒ 上限實際變成「每時段 2」。"
        "一天四個時段就是四倍負載，而沒有任何畫面會顯示這件事。"
    )


# ══════════════════════════════════════════════════════════════════════
# SL13 · 那句寫給使用者看的話
# ══════════════════════════════════════════════════════════════════════

def test_sl13_the_api_no_longer_claims_the_limit_is_unchangeable(client, make_user):
    """🔴 SL13：API 不可以再回「**每日一次為硬上限，不可調整**」。

    ⚠️ 那是 `routers/tender_radar.py:313` 的 `dailyLimitNote`，**前端會顯示**。

    ## 🔑 這一題的來歷是今天最貴的一課

    那個字串是 A 三小時前就標成「要改」的 SL13 ——
    ☠️ **而那三小時裡它一直掛在畫面上，是使用者自己讀到的，
    然後裁示「我要可調整」。**

    📌 **標成「要改」不等於「已經不會被看到」。**
    **在它被改掉之前，它仍然在對使用者說話。**

    🔴 而 D 指出 A 漏了一半：**規格沒有要求任何測試去斷言那個字串 ⇒ 改不改都綠。**
    ⇒ 所以有這一題。它驗的是 **API 欄位**（驗得到），不是前端文案（驗不到）。

    ## 🔴🔴 而這一題的第一版**打錯了端點，所以是空綠的**（我自己抓到）

    我只查了 `/api/tender-radar/status`，而那個字串在
    **`/api/tender-radar/schedule`**（`dailyLimitNote`，`tender_radar.py:319`）。
    ⇒ 第一跑它就綠了，**而我差點把那個綠當成「已經改好了」回報給 A**。

    🔑 **斷言寫對、而觀測點指向別的地方** —— 今天第四次同一族
    （`notify_tender_found` 太上游／`tender_hits` 空表／`.get()` 對不存在的鍵）。

    ⇒ 所以現在**掃過所有 GET 端點**，不指名一個。
    ⚠️ 那不只是保險：這個字串**本來就可能被搬到別的端點**，
    而「搬走」與「刪掉」在單一端點的斷言下長得一模一樣。
    """
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    hdr = {"Authorization": "Bearer " + r.json()["token"]}

    paths = ("/api/tender-radar/status", "/api/tender-radar/schedule",
             "/api/tender-radar/watches", "/api/tender-radar/tenders")
    found = {}
    for path in paths:
        resp = client.get(path, headers=hdr)
        if resp.status_code != 200:
            continue
        blob = json.dumps(resp.json(), ensure_ascii=False)
        for phrase in ("每日一次", "不可調整"):
            if phrase in blob:
                found.setdefault(path, []).append(phrase)
    assert not found, (
        f"這些端點還在回那句話：{found}\n"
        "⇒ 使用者會在畫面上讀到它，然後以為這個設定改不了 —— "
        "而他今天就是這樣讀到的，然後裁示「我要可調整」。"
    )


# ══════════════════════════════════════════════════════════════════════
# SL20～SL23 · 🔴 **升級當下那一刻** —— 14 題全部沒有覆蓋到的那條路
# ══════════════════════════════════════════════════════════════════════
#
# D 稽核發現 `radar_ready`（上面那個 fixture）**每次都先 `_set_setting`**
# ⇒ **原本 14 題全部在「已設定、已有狀態」的前提下跑。**
#
# 🔴 而 A 複驗出更硬的事實：
#
#     db.py 的 `_seed_setting` 是 `ON CONFLICT(key) DO NOTHING`
#     grep tender_radar_scan_hours backend/db.py  →  0 命中（根本沒被 seed）
#
# ⇒ **正式機升到 v88 之後那兩個 key 不存在**，
# 「沒設過 → 走預設」是它**第一次跑排程時唯一會走的那一條路** —— 而它一題都沒有。
#
# ⚠️ **不可以用 `_set_setting(key, "")` 代替「沒設過」**：
# 空字串是「**不要寄**」（SL16 已經在測），**跟「沒設過」是兩件不同的事**。
# 🔑 那正是 `null` 不等於 `0`：判斷要用「**key 在不在**」，不可以用真假值。


@pytest.fixture()
def radar_bare(client, monkeypatch):
    """跟 `radar_ready` 一樣，但**把那兩個設定鍵整個刪掉** —— 升級當下的樣子。

    ⚠️ 這個 fixture 存在的理由就是 `radar_ready` 做不到的那件事。
    把它們合併成「`radar_ready(preset=False)`」會讓**預設值那一側繼續是隱形的**。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, email, "
            "modules, active, created_at, must_change_password, notification_muted) "
            "VALUES (?,?,?,?,?,?,1,?,0,?)",
            ("sl_bare", "x", "收件人", "superadmin", "bare@example.invalid",
             "[]", "2026-01-01T00:00:00", "[]"))
        conn.execute(
            "INSERT INTO tender_watches (name, keywords, enabled) VALUES (?,?,1)",
            ("監視系統", '["監視"]'))
        for key in (SCAN_HOURS_KEY, NOTIFY_HOURS_KEY, OLD_SCAN_HOUR_KEY,
                    NOTIFY_MARK_KEY):
            conn.execute("DELETE FROM system_settings WHERE key=?", (key,))
        conn.commit()
    finally:
        conn.close()
    # 🔴 **`fetch_detail` 一定要一起換掉，而且是在 fixture 裡換不是逐題換。**
    # `_spy_fetch` 只換了 `fetch_raw`（清單頁），而 `parse_list(REAL)` 解出來的
    # `url` 是**真的網址** ⇒ `run_scan` → `_fetch_details` → `fetch_detail`
    # → `urlopen` → **真的對政府採購網連出去**（B 量到單一題 5 次）。
    # ⚠️ 逐題加正是「只有 SL10 記得加」的成因 —— 這裡換一次，全檔都蓋到。
    monkeypatch.setattr(
        ts, "fetch_detail", lambda url, *a, **kw: (None, "測試不抓詳細頁"))
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    return "bare@example.invalid"


def _settings_has(key):
    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM system_settings WHERE key=?", (key,)).fetchone()
    finally:
        conn.close()
    return row is not None


def test_sl20_defaults_apply_when_nothing_has_ever_been_configured(
        radar_bare, monkeypatch):
    """🔴🔴 SL20：**那兩個 key 完全不存在時，抓取與寄信都要走預設。**

    這是正式機升級之後**第一次跑排程**唯一會走的那一條路，
    而原本 14 題**一題都沒有覆蓋到它**。

    ⚠️ 前提先驗：如果 key 其實存在，這一題就只是 SL1 的重複。
    """
    assert not _settings_has(SCAN_HOURS_KEY), "前提不成立：那個 key 存在"
    assert not _settings_has(NOTIFY_HOURS_KEY), "前提不成立：那個 key 存在"

    calls = _spy_fetch(monkeypatch, vary=True)
    mails = _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")

    _at_time(monkeypatch, 9)        # 9 在預設的 9,12,15,18 裡
    run()
    assert len(calls) == 1, (
        f"什麼都沒設定時 9 點沒有抓（{len(calls)} 次）—— "
        "預設值沒有生效。⇒ 正式機升級之後雷達完全不會動，而畫面上看不出來。"
    )

    _at_time(monkeypatch, 10)       # 10 不在預設裡
    run()
    assert len(calls) == 1, (
        f"10 點不在預設時段裡，卻抓了（累計 {len(calls)} 次）—— "
        "預設值被當成「不限時段」了"
    )

    _at_time(monkeypatch, 18)       # 18 是預設的寄信時段
    run()
    assert len(mails) == 1, (
        f"什麼都沒設定時 18 點沒有寄（{len(mails)} 封）—— 寄信的預設值沒有生效"
    )


def test_sl18_falls_back_to_the_old_singular_key(radar_bare, monkeypatch):
    """SL18：新鍵不存在、**舊的單數鍵有值** → 當成單元素清單。

    📌 **我第一版把這一題編成 `SL21`，而規格裡它叫 `SL18`。**
    ⚠️ 內容一字不差，**只有編號對不上** ⇒ 規格覆蓋率守門會說「SL18 沒有人寫」，
    而它其實寫了。🔑 **「寫了」與「找得到」是兩件事**，
    而追蹤覆蓋率的東西只看得到後者。

    第 6 輪的 `tender_radar_scan_hour`（單數、`0-23`）是**同一個設定的舊語意**，
    而正式機可能有值。A 裁定 (乙)：**讀新鍵，沒有就把舊值當成 `[舊值]`。**
    """
    _set_setting(OLD_SCAN_HOUR_KEY, 8)
    calls = _spy_fetch(monkeypatch, vary=True)
    _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")

    _at_time(monkeypatch, 8)
    run()
    assert len(calls) == 1, (
        f"舊鍵是 8 而 8 點沒有抓（{len(calls)} 次）—— 那條 fallback 沒有生效。\n"
        "⇒ 升級之後使用者原本設的時間被忽略了，而他不會收到任何訊息。"
    )

    _at_time(monkeypatch, 9)        # 預設裡有 9，但舊鍵說只有 8
    run()
    assert len(calls) == 1, (
        f"舊鍵只說 8 點，9 點卻也抓了（累計 {len(calls)}）—— "
        "fallback 變成「舊值 ＋ 預設」了"
    )


def test_sl17_an_empty_new_key_must_not_fall_back_to_the_old_one(
        radar_bare, monkeypatch):
    """🔴🔴 SL17：**新鍵存在而值是空清單 ⇒ 用新鍵，不可以退回舊值。**

    📌 同上：我第一版編成 `SL22`，規格裡它是 `SL17`。

    ## ☠️ 這個坑在這個 codebase 裡有前科

        quotations.py:1379   new_status = body.status or q.get(...)
                             # status 預設是 truthy 的 "草稿" ⇒ 右邊是死碼

    ⇒ fallback 若寫成 `新值 or 舊值`，而使用者把寄信時段設成**空**
    （＝不要寄，SL16 已經在測的那個合法設定）⇒ **空清單是 falsy ⇒ 退回舊值
    ⇒ 它又開始寄了。**

    🔑 **判準是「鍵存在嗎」，不是「值是不是真的」。**
    ⚠️ 而使用者會怎麼發現？**他不會。** 他以為關掉了，而信照常寄。
    """
    _set_setting(OLD_SCAN_HOUR_KEY, 8)
    _set_setting(SCAN_HOURS_KEY, "")          # 明確設成空 —— 不是沒設過
    calls = _spy_fetch(monkeypatch, vary=True)
    _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")

    for hour in (8, 9, 12, 15, 18):
        _at_time(monkeypatch, hour)
        run()
    assert len(calls) == 0, (
        f"抓取時段被明確設成空，卻抓了 {len(calls)} 次 —— "
        "`新值 or 舊值` 讓空清單退回了舊鍵的 8。\n"
        "⇒ 使用者以為關掉了，而它照跑。判準要用「鍵在不在」不是真假值。"
    )


def test_sl23_the_first_run_after_an_upgrade_does_not_double_fetch(
        radar_bare, monkeypatch):
    """🔴 SL23：**升級當下「新標記還不存在」，不可以被誤判成「沒抓過」而多抓一輪。**

    ## 兩個方向都要防（A 與 D 各推出一個）

    **方向 A —— 升級當天完全不抓**：新碼若只比對「最後一筆的小時 == 當前時段」
    而**不比日期** ⇒ **昨天 9 點那筆會讓今天 9 點被跳過**。
    **方向 B —— 升級當天多抓一輪**：新碼若改查一個**新的標記**
    （而不是 `tender_fetch_log`）⇒ 那個標記升級當下不存在 ⇒ 誤判成沒抓過。

    📌 方向 B 有具體對象：B 的詳細頁上限實作把 `"YYYY-MM-DD:N"` 存進
    `system_settings` —— **那正是一個升級當下不存在的新標記。**

    ⚠️ 這一題與 SL20 是**同一個洞的兩面**：SL20 是設定側（沒設過 → 走預設），
    這一題是狀態側（新標記不存在 → 誤判沒抓過）。
    **兩者都只在「升級當下那一刻」發生。**
    """
    import db
    from datetime import timedelta

    # 昨天這個時段抓過一次 —— 那是升級前留下的列
    conn = db.get_db()
    try:
        yesterday = (ts.today() - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO tender_fetch_log (fetched_at, recognised) VALUES (?,1)",
            (f"{yesterday}T09:00:00",))
        conn.commit()
    finally:
        conn.close()

    calls = _spy_fetch(monkeypatch, vary=True)
    _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")

    _at_time(monkeypatch, 9)
    run()
    assert len(calls) == 1, (
        f"昨天 9 點那筆讓今天 9 點被跳過了（抓了 {len(calls)} 次）—— "
        "時段比對沒有比日期。**升級當天雷達完全不會動。**"
    )
    run()
    assert len(calls) == 1, (
        f"同一個時段內第二次又抓了（累計 {len(calls)}）—— "
        "節流改查了一個升級當下還不存在的新標記，於是誤判成沒抓過"
    )


# ══════════════════════════════════════════════════════════════════════
# SL24～SL27 · 使用者裁示：**不設硬上限，但 > 12 個時段要確認**
# ══════════════════════════════════════════════════════════════════════
#
# 🔑 **這條裁示會存在，是因為我沒有替使用者假設一個上限並把它釘死。**
# 我問的是「要不要有上限」，而他的答案**兩個選項都不是**。
# ⚠️ 如果我當時自己假設一個（例如「最多 24」）並寫成測試，
# **那一題會是綠的，而這個答案永遠不會出現。**
#
# 🔴 門檻與判定放**後端**（A 裁定）：**我只寫後端測試** ——
# 警告若只活在前端，這條裁示**沒有任何一題驗得到**。
#
# ⚠️ 這條跟「值不合法」是**兩條路**，不可以合併：
#   `"9,25,15"` 不合法      → **422**，擋
#   13 個時段（合法但頻繁） → **409**，確認
# 🔑 後端**不拒絕** ⇒ 仍然不是硬上限，使用者按了確認就一定存得進去。

CONFIRM_FLAG = "confirmHighFrequency"


def _schedule_put(client, hdr, **body):
    return client.put("/api/tender-radar/schedule", headers=hdr, json=body)


def test_sl24_twelve_slots_save_without_a_warning(client, make_user):
    """SL24：**12 個時段（門檻本身）直接存得進去，不要確認。**

    ⚠️ 邊界的**安全側**要有題：只測 13 的話，一個「>= 12 就擋」的實作會全綠，
    而那會讓門檻悄悄變成 11。
    """
    hdr = _auth(client, make_user)
    threshold = _need("HIGH_FREQUENCY_SLOT_THRESHOLD")
    hours = ",".join(str(h) for h in range(threshold))
    r = _schedule_put(client, hdr, scanHours=hours)
    assert r.status_code == 200, (
        f"{threshold} 個時段（門檻本身）應該直接存得進去，實際 {r.status_code}："
        f"{r.text[:300]}"
    )
    assert _get_setting(SCAN_HOURS_KEY), "回了 200 而設定沒被改"


def test_sl25_more_than_twelve_slots_needs_confirmation(client, make_user):
    """🔴 SL25：**超過門檻而沒帶確認旗標 → 409，而且設定真的沒被改。**

    🔴 **一定要斷言「設定沒被改」，不可以只斷言狀態碼** ——
    **「回了 409 但其實已經存進去了」是這一類最常見的壞法**，
    而只看狀態碼**看不到**它。
    ⚠️ 那也正是〈降級之後它還是會動〉：使用者看到「需要確認」，按了取消，
    **而它已經生效了。**
    """
    hdr = _auth(client, make_user)
    threshold = _need("HIGH_FREQUENCY_SLOT_THRESHOLD")
    _set_setting(SCAN_HOURS_KEY, DEFAULT_SCAN_HOURS)
    hours = ",".join(str(h) for h in range(threshold + 1))

    r = _schedule_put(client, hdr, scanHours=hours)
    assert r.status_code == 409, (
        f"{threshold + 1} 個時段沒帶確認旗標，應該回 409（需要確認），"
        f"實際 {r.status_code}：{r.text[:300]}"
    )
    assert _get_setting(SCAN_HOURS_KEY) == DEFAULT_SCAN_HOURS, (
        f"回了 409，而設定已經被改成 {_get_setting(SCAN_HOURS_KEY)!r} —— "
        "使用者按取消，它卻已經生效了"
    )


def test_sl26_confirmed_high_frequency_is_accepted(client, make_user):
    """SL26：**帶了確認旗標就一定存得進去** —— 這是「不設硬上限」的那一半。

    ⚠️ 沒有這一題，一個「超過門檻一律擋」的實作會讓 SL25 全綠 ——
    **而那就變成硬上限了，正好跟使用者的裁示相反。**
    """
    hdr = _auth(client, make_user)
    threshold = _need("HIGH_FREQUENCY_SLOT_THRESHOLD")
    hours = ",".join(str(h) for h in range(threshold + 1))
    r = _schedule_put(client, hdr, scanHours=hours,
                      **{CONFIRM_FLAG: True})
    assert r.status_code == 200, (
        f"帶了確認旗標還是被擋（{r.status_code}）：{r.text[:300]}\n"
        "⇒ 那變成硬上限了，而使用者明確裁示不要硬上限"
    )
    stored = _get_setting(SCAN_HOURS_KEY)
    assert stored and len(str(stored).split(",")) == threshold + 1, (
        f"回了 200 而存進去的是 {stored!r}"
    )


def test_sl27_an_invalid_hour_is_rejected_not_merely_confirmed(client, make_user):
    """🔴 SL27：**`"9,25,15"` 是不合法，不是「頻繁」** —— 要 422 不是 409。

    🔑 兩條路的差別是**能不能靠按確認通過**：
    不合法的值按幾次確認都不該存得進去。
    ⚠️ 合併成一條的話，使用者會看到「時段太多，要確認嗎？」——
    **而真正的問題是 25 不是一個小時。** 那句話會把他導向完全錯誤的方向。
    """
    hdr = _auth(client, make_user)
    _set_setting(SCAN_HOURS_KEY, DEFAULT_SCAN_HOURS)
    r = _schedule_put(client, hdr, scanHours="9,25,15")
    assert r.status_code == 422, (
        f"`9,25,15` 含不合法的小時，應該 422，實際 {r.status_code}：{r.text[:300]}"
    )
    assert _get_setting(SCAN_HOURS_KEY) == DEFAULT_SCAN_HOURS, "422 而設定被改了"

    r = _schedule_put(client, hdr, scanHours="9,25,15", **{CONFIRM_FLAG: True})
    assert r.status_code == 422, (
        f"帶了確認旗標就讓不合法的值過了（{r.status_code}）—— "
        "確認是給「合法但頻繁」用的，不是給「值錯了」用的"
    )


def test_sl28_duplicate_slots_do_not_multiply_the_fetches(radar_ready, monkeypatch):
    """SL28：`9,9,9,9` **不可以在 9 點抓四次**。

    ⚠️ 使用者可以自己打字，而重複值是打字最容易產生的東西。
    🔑 而它的後果落在對外的那一側：**對政府網站的請求變四倍**，
    而畫面上只會顯示「已設定 4 個時段」—— 看起來完全正常。
    """
    _set_setting(SCAN_HOURS_KEY, "9,9,9,9")
    calls = _spy_fetch(monkeypatch, vary=True)
    _spy_mail(monkeypatch)
    run = _need("run_scheduled_scan")
    _at_time(monkeypatch, 9)
    for _ in range(4):
        run()
    assert len(calls) == 1, (
        f"時段設成 `9,9,9,9`，而 9 點抓了 {len(calls)} 次 —— "
        "重複值沒有去重，對政府網站的請求變四倍而畫面上看不出來"
    )
