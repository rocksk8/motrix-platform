"""§3v · 背景自動把地址定位完（VB1–VB7、VC1–VC2）。

> **使用者裁示：背景自動定位，不要他按按鈕。**

---

# ☠️ 這一節的風險跟前面幾節不同

**一個會自己跑的背景迴圈，失控的樣子就是被 Nominatim 封 IP。**
🔑 而今晚圖磚那件**已經演過一次**：
**對方回 HTTP 200 而內容是拒絕，我們的錯誤處理完全沒觸發。**

⇒ 五道防線，**每一道都不是可選的**（VB1–VB5），
而最重要的一道是「**怎麼知道它在跑**」（VB6）。

---

# ⚠️⚠️ 我驗不到「它真的在跑」—— 這句是 A 的原話，逐字留著

> **`MOTRIX_DISABLE_SCHEDULERS=1` ⇒ 開發機上背景排程不會跑。**
> **你釘得到的是「排程有被註冊」＋「那支函式單獨呼叫時行為正確」，**
> **而那兩件合起來不等於「它真的在跑」。**

`tests/conftest.py:52` 把那個環境變數設成 `1`，`main.py:533` 據此整批略過。
⇒ **這個檔裡沒有任何一題能證明那個迴圈在正式機上真的會被觸發。**
📌 那要由 A 在正式機上看 VB6 的「最後一次執行時間」會不會動 ——
🔑 **而那正是 VB6 存在的理由：一個背景工作「沒有在跑」與「跑了但什麼都沒做」
在畫面上一模一樣。**

---

# 📌 我釘的名字（B 要用這幾個）

| | |
|---|---|
| `geo.GEOCODE_WARM_DAILY_LIMIT` | 每日上限（整數） |
| `geo.warm_geocode_cache()` | 跑一趟。**可以單獨呼叫**（測試與排程共用同一支） |
| `geo.warm_status()` | `{lastRunAt, processed, succeeded, stoppedBecause}` |
| `stoppedBecause` | `no_backlog` / `daily_limit` / `geo_off` / `failures` **四種要分得開** |
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import geo  # noqa: E402

#: 🔴 **兩個頁面都要看。**
#:
#: 我第一版只看 `tender-radar.html`，而那句「按幾次就會全部出現」在
#: **`map.html:109`** ⇒ **VC1 綠了，而它什麼都沒驗到。**
#: 🔑 今天第四次同一種錯（U5c 掃到註解／R10b 錨到呼叫端／UA1b 只 grep 了
#: 一個實例）：**判準的「範圍」挑錯，跟判準本身寫錯一樣會給你綠燈。**
#: 📌 而這一次是 A 的回報救了我 —— 他說「現在寫的是那句」，
#: 而我的測試說「沒有」。**兩個說法對不起來的時候，先去查不要先相信自己。**
_PAGES_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "pages"
UI_PAGES = ("map.html", "tender-radar.html")


def _ui_text():
    """兩個頁面的內容合起來，並先證明它們讀得到。"""
    chunks = []
    for name in UI_PAGES:
        p = _PAGES_DIR / name
        assert p.exists(), f"找不到 {p}"
        body = p.read_text(encoding="utf-8")
        assert len(body) > 3000, f"{name} 只有 {len(body)} 字元 —— 讀錯檔了？"
        chunks.append(body)
    # ⚠️ 用 `chr(10)` 不寫跳脫字元：我剛才用 bash heredoc 改這個檔，
    #    而 `"\n"` 被吃成了**一個真的換行**，把這支函式整個弄壞。
    # 🔑 那是〈Bash heredoc 會吃掉跳脫字元〉第八次 ——
    #    **規則是「改檔一律走 Edit／Write」，而我為了省一次工具呼叫破了它。**
    return chr(10).join(chunks)


def _need(name):
    """取一個我釘的名字，沒有就指名說它缺了什麼。"""
    got = getattr(geo, name, None)
    assert got is not None, (
        f"`helpers/geo.py` 缺少 `{name}` —— 見本檔開頭〈我釘的名字〉"
    )
    return got


@pytest.fixture()
def backlog(client):
    """塞一批**還沒定位過**的地址進去，並清空快取與今日計數。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM geocode_cache")
        conn.execute("DELETE FROM tenders")
        for i in range(6):
            conn.execute(
                "INSERT INTO tenders (case_no, name, org, location, fetched_at)"
                " VALUES (?,?,?,?,?)",
                (f"W-{i:03d}", f"背景定位測試 {i}", f"待定位機關{i}",
                 None, "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return 6


@pytest.fixture()
def counting_lookup(monkeypatch):
    """把實際的查詢換成計數器，**而節流那一層保留**。

    ⚠️ 換掉 `_throttle` 的話 VB1 就驗不到了；
    換掉整支 `locate_cached` 的話，VB1／VB2 會驗到我自己的假貨。
    🔑 **假貨要保留被測的那個維度。**
    """
    calls = []
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})

    def _fake(address, **_kw):
        calls.append(address)
        return ((24.0 + len(calls) * 0.01, 120.0), geo.PRECISION_STREET)

    monkeypatch.setattr(geo, "_locate_google", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_locate_nominatim", _fake)
    return calls


# ══════════════════════════════════════════════════════════════════════
# VB1 · 沿用現有的節流
# ══════════════════════════════════════════════════════════════════════

def test_vb1_the_warmer_goes_through_the_existing_throttle(
        client, backlog, counting_lookup, monkeypatch):
    """🔴 VB1：**沿用現有的 `_throttle()`（1.1 秒），不可以另開一條不受節流的路徑。**

    ☠️ 另開一條的話，這個迴圈會用**最快的速度**連打 Nominatim ——
    而那正是被封 IP 的標準做法。
    🔑 而被封之後的樣子今晚已經看過：**地圖上沒有點、`geoEnabled` 仍然是 true**
    ⇒ 看起來像使用者地址填錯。

    📌 觀測點是 `_throttle` 被呼叫的次數 —— 我把它換成**只記帳不睡覺**的版本，
    ⚠️ 不是「量它睡了多久」（那會讓這一題跑六秒，而且在慢機器上會飄）。
    """
    ticks = []
    monkeypatch.setattr(geo, "_throttle", lambda: ticks.append(1))
    monkeypatch.setattr(geo, "GEOCODE_WARM_DAILY_LIMIT", 3)

    _need("warm_geocode_cache")()

    assert counting_lookup, "一個查詢都沒發 —— 這一題的前提不成立"
    assert len(ticks) >= len(counting_lookup) - 1, (
        f"查了 {len(counting_lookup)} 次，而 `_throttle()` 只被呼叫 "
        f"{len(ticks)} 次 ⇒ **有一條路繞過了節流。**"
    )


# ══════════════════════════════════════════════════════════════════════
# VB2 · 每日上限要跨呼叫累計
# ══════════════════════════════════════════════════════════════════════

def test_vb2_the_daily_limit_accumulates_across_calls(
        client, backlog, counting_lookup, monkeypatch):
    """🔴🔴 VB2：**每日上限要跨呼叫累計並存進 DB**，不可以是行程內變數。

    ## ☠️ 這正是今晚 SL10 踩過的那個

    `fetched = 0` 寫在函式裡 ⇒ 實際語意變成「**每次呼叫最多 N**」。
    一天呼叫一次的時候兩者**恰好相等** —— 🔑 **那是巧合不是設計**。
    而改成一天跑四次之後，上限會**靜默變成 4N**：
    **功能照跑、畫面正常，只是對外負載變四倍，而沒有任何測試會紅。**

    📌 所以這一題**呼叫兩次**：兩次加起來不可以超過上限。
    ⚠️ 只呼叫一次的話，「每次 N」與「每天 N」**完全分不出來**。
    """
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "GEOCODE_WARM_DAILY_LIMIT", 2)
    warm = _need("warm_geocode_cache")

    warm()
    first = len(counting_lookup)
    warm()
    total = len(counting_lookup)

    assert first <= 2, f"第一次就查了 {first} 次，上限是 2"
    assert total <= 2, (
        f"兩次呼叫總共查了 {total} 次，而每日上限是 2。\n"
        "⇒ 那個計數是**行程內變數**或**每次呼叫歸零**，"
        "不是跨呼叫累計的每日上限。\n"
        "📌 一天跑一次時兩者恰好相等 —— 而那是巧合不是設計。"
    )
    assert _need("warm_status")().get("stoppedBecause") == "daily_limit", (
        f"上限用完了，而狀態說的是 "
        f"{_need('warm_status')().get('stoppedBecause')!r}"
    )


# ══════════════════════════════════════════════════════════════════════
# VB3 · geo_on() 關著時一次都不發
# ══════════════════════════════════════════════════════════════════════

def test_vb3_nothing_is_sent_while_geo_is_off(
        client, backlog, counting_lookup, monkeypatch):
    """🔴 VB3：`geo_on()` 關著時**一次都不發**（不是「發了失敗」）。

    ⚠️ 「發了失敗」與「沒發」在畫面上一樣（都沒有新座標），
    而代價差一個逾時 × 每一筆待辦。
    🔑 跟 T10、P15 是同一個形狀：**壞掉的時候最慢。**
    """
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", False)
    monkeypatch.delenv("MOTRIX_GEO", raising=False)

    _need("warm_geocode_cache")()

    assert counting_lookup == [], (
        f"地理查詢關著，而它仍然查了 {len(counting_lookup)} 次："
        f"{counting_lookup[:3]}"
    )
    assert _need("warm_status")().get("stoppedBecause") == "geo_off", (
        f"停下來的理由要說得出是「沒開地理查詢」，實際 "
        f"{_need('warm_status')().get('stoppedBecause')!r}"
    )


# ══════════════════════════════════════════════════════════════════════
# VB4 · 連續失敗要停，而判準不可以只看例外
# ══════════════════════════════════════════════════════════════════════

def test_vb4_a_refusal_that_arrives_as_a_normal_response_still_counts(
        client, backlog, monkeypatch):
    """🔴🔴 VB4：**連續失敗要停，而「失敗」不可以只認例外。**

    ## ☠️ 今晚圖磚那件已經演過一次

    **對方回 HTTP 200，而內容是拒絕** ⇒ 我們的 `except` 完全沒觸發
    ⇒ 迴圈會**若無其事地繼續打**，直到 IP 被封。

    📌 所以這一題的假貨**不丟例外**：它每次都正常回傳、只是**解析不出座標**。
    ⚠️ 一個「只在 `except` 裡累計失敗」的實作，會在這一題上**永遠不停**。

    🔑 判準是**連續**不是**累計**：中間成功一次就該歸零
    （反向控制在 VB4b）。
    """
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})
    monkeypatch.setattr(geo, "GEOCODE_WARM_DAILY_LIMIT", 100)

    tries = []

    def _refused(address, **_kw):
        tries.append(address)
        return None                     # 正常回傳，只是沒有座標

    monkeypatch.setattr(geo, "_locate_google", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_locate_nominatim", _refused)

    _need("warm_geocode_cache")()

    assert tries, "一次都沒試 —— 前提不成立"
    assert len(tries) <= 4, (
        f"連續失敗 {len(tries)} 次還在繼續打。\n"
        "☠️ 那個假貨**沒有丟例外** —— 它每次都正常回傳，只是解析不出座標。\n"
        "⇒ 只在 `except` 裡累計失敗的實作，在這條路上永遠不會停。"
    )
    assert _need("warm_status")().get("stoppedBecause") == "failures", (
        f"停下來的理由要說得出是「連續失敗」，實際 "
        f"{_need('warm_status')().get('stoppedBecause')!r}"
    )


def test_vb4b_a_success_in_between_resets_the_failure_streak(
        client, backlog, monkeypatch):
    """🔴 VB4b 反向控制：**中間成功一次，連續失敗要歸零。**

    ☠️ 少了這一題，一個「**累計**失敗達 3 次就停」的實作會讓 VB4 綠 ——
    而那會在**正常運作**時停下來：待辦裡本來就有查不到的地址
    （§3o 實測：門牌一律查不到）⇒ **跑三筆就永久停住**，
    🔑 而症狀是「背景好像沒在跑」，跟「它根本沒被排程」一模一樣。
    """
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})
    monkeypatch.setattr(geo, "GEOCODE_WARM_DAILY_LIMIT", 100)

    tries = []

    def _alternating(address, **_kw):
        tries.append(address)
        if len(tries) % 2:
            return None                              # 失敗
        return ((24.0, 120.0), geo.PRECISION_STREET)  # 成功

    monkeypatch.setattr(geo, "_locate_google", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_locate_nominatim", _alternating)

    _need("warm_geocode_cache")()

    assert len(tries) >= 5, (
        f"一成功一失敗交替時只跑了 {len(tries)} 次就停了（待辦有 6 筆）。\n"
        "⇒ 那是**累計**失敗不是**連續**失敗。\n"
        "☠️ 待辦裡本來就有查不到的地址（門牌一律查不到），"
        "累計判準會讓它在正常運作時永久停住。"
    )


# ══════════════════════════════════════════════════════════════════════
# VB5 / VB6 / VB7 · 停的理由要分得開，而且看得見
# ══════════════════════════════════════════════════════════════════════

def test_vb5_an_empty_backlog_is_not_the_same_as_a_used_up_limit(
        client, counting_lookup, monkeypatch):
    """🔴 VB5：**沒有待辦時不可以空轉**，而「沒有待辦」與「上限用完」要分開。

    ☠️ **兩者都會讓它停下來，而處置完全不同**：
    | 停的理由 | 使用者（或 A）要做的事 |
    |---|---|
    | `no_backlog` | 什麼都不用做，**這是好消息** |
    | `daily_limit` | 明天會繼續，**或者把上限調高** |

    🔑 合成一個「已停止」的話，**好消息與欠帳長得一樣**。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tenders")
        conn.execute("DELETE FROM geocode_cache")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "GEOCODE_WARM_DAILY_LIMIT", 100)

    _need("warm_geocode_cache")()

    assert counting_lookup == [], (
        f"沒有待辦而它仍然查了 {len(counting_lookup)} 次 —— 那是空轉。"
    )
    assert _need("warm_status")().get("stoppedBecause") == "no_backlog", (
        f"沒有待辦時的理由要是 `no_backlog`，實際 "
        f"{_need('warm_status')().get('stoppedBecause')!r}"
    )


def test_vb6_the_status_says_enough_to_tell_the_two_silences_apart(
        client, backlog, counting_lookup, monkeypatch):
    """🔴🔴 VB6：狀態要有**最後執行時間／這次處理幾筆／成功幾筆／為什麼停**。

    ## ☠️ 理由：**「沒有在跑」與「跑了但什麼都沒做」在畫面上一模一樣**

    📌 那是今晚整晚的主題，而**這次它會發生在一個沒有人盯著的迴圈上**。
    🔑 四個欄位各自回答一個問題：
    **有沒有跑**（時間）／**做了多少**（處理數）／**有沒有用**（成功數）／
    **為什麼停**（理由）。少任何一個，都有一種沉默分不出來。
    """
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "GEOCODE_WARM_DAILY_LIMIT", 3)

    _need("warm_geocode_cache")()
    status = _need("warm_status")()

    for field in ("lastRunAt", "processed", "succeeded", "stoppedBecause"):
        assert field in status, (
            f"狀態裡沒有 `{field}`：{status}\n"
            "⇒ 四個欄位各自回答一個問題，少一個就有一種沉默分不出來。"
        )
    assert status["lastRunAt"], "跑過了而 `lastRunAt` 是空的"
    assert status["processed"] >= 1, (
        f"處理了 {len(counting_lookup)} 筆，而 `processed` 是 "
        f"{status['processed']!r}"
    )
    assert status["succeeded"] <= status["processed"], (
        f"成功數比處理數還大：{status}"
    )


def test_vb7_the_status_does_not_keep_stale_numbers(
        client, backlog, counting_lookup, monkeypatch):
    """🔴🔴 VB7 反向控制：**待辦清空之後，狀態不可以停在上一次的舊數字。**

    ☠️ 少了這一題，一個「**只在有做事時才更新狀態**」的實作會讓 VB6 全綠 ——
    而畫面上永遠寫著「上次處理 3 筆、成功 3 筆」，
    🔑 **那是一個看起來很健康的畫面，而那個迴圈可能已經停了三天。**
    📌 〈計數器要有落點〉的鄰居：**一個不會歸零的數字，跟一個正確的數字
    在畫面上長得一樣。**
    """
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "GEOCODE_WARM_DAILY_LIMIT", 100)
    warm, status = _need("warm_geocode_cache"), _need("warm_status")

    warm()
    first = status()
    assert first.get("processed", 0) >= 1, f"前提不成立：第一趟沒做事 {first}"

    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tenders")
        conn.commit()
    finally:
        conn.close()

    warm()
    second = status()
    assert second.get("stoppedBecause") == "no_backlog", (
        f"待辦清空之後，理由應該是 `no_backlog`，實際 "
        f"{second.get('stoppedBecause')!r}"
    )
    assert second.get("processed") == 0, (
        f"待辦清空之後 `processed` 還是 {second.get('processed')!r}"
        f"（上一趟是 {first.get('processed')!r}）——\n"
        "⇒ 那個數字沒有歸零，畫面會永遠寫著上一次的成績。"
    )


# ══════════════════════════════════════════════════════════════════════
# 排程有沒有被註冊（⚠️ 而那不等於它在跑）
# ══════════════════════════════════════════════════════════════════════

def test_vb8_the_warmer_is_registered_with_the_other_schedulers():
    """🟡 VB8：那支背景工作要**被掛進 `main.py` 的排程區塊**。

    ## ⚠️⚠️ 這一題**證明不了它在跑**，A 的原話逐字留著

    > **`MOTRIX_DISABLE_SCHEDULERS=1` ⇒ 開發機上背景排程不會跑。**
    > **你釘得到的是「排程有被註冊」＋「那支函式單獨呼叫時行為正確」，**
    > **而那兩件合起來不等於「它真的在跑」。**

    `tests/conftest.py:52` 設了那個變數、`main.py:533` 據此整批略過。
    ⇒ 🔑 **這是文字比對，而且它守的是「有沒有被寫進那個區塊」。**
    📌 真正的證據是正式機上 VB6 的 `lastRunAt` 會不會動 —— **那要 A 去看。**
    """
    text = (Path(__file__).resolve().parent.parent / "main.py").read_text(
        encoding="utf-8")
    i = text.find('if os.getenv("MOTRIX_DISABLE_SCHEDULERS") != "1":')
    assert i >= 0, "`main.py` 的排程區塊找不到了 —— 這個檔的結構變了"
    block = text[i:i + 1200]
    assert "warm" in block and "geo" in block.lower(), (
        "排程區塊裡沒有背景定位：\n" + block[:300] + "\n"
        "⇒ 那支函式寫好了而沒有人叫它 —— 〈兩個都對而路不存在〉。"
    )


# ══════════════════════════════════════════════════════════════════════
# VC · 畫面那句話要跟著改
# ══════════════════════════════════════════════════════════════════════

def test_vc1_the_page_no_longer_tells_the_user_to_press_a_button():
    """🔴 VC1：文案不可以再說「**按幾次就會全部出現**」。

    ☠️ 背景做完之後，「按幾次」**不再是使用者要做的事**
    ⇒ 🔑 **那會變成一句「成因已經變掉的解釋」** ——
    它不會報錯、不會壞，**它只是把使用者送去做一件沒有用的事**。
    📌 B 今晚才剛修掉一句同樣的東西（「詳細頁每天有抓取上限」那句，
    在改用機關名稱定位之後就不是主要成因了）。

    ⚠️ 文字比對，弱的。它擋得住「**忘了改**」，擋不住「改成另一句錯的」。
    """
    text = _ui_text()
    assert "按幾次" not in text, (
        "畫面上還寫著「按幾次就會全部出現」——\n"
        "⇒ 背景自動定位之後那不再是使用者要做的事，"
        "而那句話會把他送去做一件沒有用的事。"
    )


def test_vc2_the_page_can_say_which_kind_of_stopped_it_is():
    """🔴 VC2：背景停掉時，畫面要說得出**是哪一種**。

    ☠️ 三種都會讓數字不動，而處置完全不同：
    `geo_off`（去打開地理查詢）／`daily_limit`（明天會繼續）／
    `failures`（**對方可能封我們了，要看 log**）。

    📌 我釘的是「**畫面讀得到那個理由**」（`stoppedBecause` 出現在頁面裡），
    ⚠️ **不是「它顯示得對」** —— 後者要目視。
    🔑 一道守門要說得出它守不到什麼。
    """
    text = _ui_text()
    assert "stoppedBecause" in text, (
        "畫面完全沒有讀 `stoppedBecause` ——\n"
        "⇒ 三種停止原因在畫面上會變成同一件事（數字不動），"
        "而處置完全不同。"
    )
