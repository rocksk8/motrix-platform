"""備份停擺告警：**那封信從來沒有真的被組出來過。**

## ☠️ 一個 `NameError` 活到今天，因為有三層各自獨立的東西在遮它

```
helpers/email_notify.py    沒有 import datetime，而 :1494 用了 datetime.now()
routers/daily_tasks.py     裸的 threading.Thread ⇒ 例外死在執行緒裡，外層 except 捕不到
routers/daily_tasks.py     _set_setting(guard_key, today) 寫在寄信**之前** ⇒ 失敗也不重試
tests/（三支既有測試）      全部把 notify_backup_stale 整個 monkeypatch 掉
                            ⇒ **函式本體一次都沒有被執行過**
```

🔑 **四層裡沒有一層是錯的**：patch 掉外部發信是對的、背景執行緒是對的、
守門旗標是對的。**是它們疊起來讓一個必然的崩潰變成完全安靜的。**

⚠️ 而那三支既有測試驗的是「**有沒有被呼叫**」—— 那是**對的觀測點**，
它們沒有寫錯。缺的是**另一種題**：本體跑不跑得起來。
🔑 **「這個函式有沒有被呼叫」與「它被呼叫之後會發生什麼」是兩種題目，
而一個模組可以只有前者。**

## 🔴 而「從來沒備份過」會寄成功，「備份過但停了」會炸

```python
email_notify.py:1490   if ts is None:   rows.append((label, "查無任何成功紀錄"))   ← 不碰 datetime
email_notify.py:1494   else:            hours = int((datetime.now() - ts)...)      ← NameError
```

⇒ **用 `ts=None` 寫的測試必然綠，而它擋不到任何東西。**
（今天第 N 次：**前提沒佈置好的斷言，跟沒有斷言一樣。**）

☠️ 而這兩條路對應的現實是反過來的：
「從來沒備份過」多半是新安裝；**「備份過但停了」才是那封信真正要救的情境。**

## ⚠️ 觀測點：`_async_send` 不是 `_send_raising`

視窗 B 提的形狀用 `_send_raising`，**而 `notify_backup_stale` 走的是 `_async_send`**
（`email_notify.py:1524`）。照那個形狀寫的話，**修好 import 之後這一題還是紅**，
而訊息會說「告警信沒有送出」——把人導去查發信設定。
🔑 我實測過才改（`ts=None` 那一輪 `_send_raising` 的計數是 0）。
"""
from datetime import datetime, timedelta

import pytest

import helpers.email_notify as en

STALE_LABEL = "本機 SQLite 快照"
GUARD_KEY = "backup_stale_last_notified"


def _capture(monkeypatch):
    """收件人固定、發信換成記錄器。回 `(sent, )`。

    ⚠️ `_admin_emails` 要一起換掉：它會去查資料庫，而這幾題不需要資料庫，
    **而且「沒有 admin 有 email」會讓函式在第 1486 行就 return** ——
    那時本體根本沒跑到，這一題就白寫了。
    """
    sent = []
    monkeypatch.setattr(en, "_admin_emails", lambda *a, **k: ["x@example.invalid"])
    monkeypatch.setattr(en, "_async_send",
                        lambda to, subject, html: sent.append((to, subject, html)))
    return sent


def test_backup_stale_alert_runs_for_a_real_timestamp(monkeypatch):
    """🔴 **`notify_backup_stale()` 的本體要跑得起來** —— 帶一個真的 `datetime`。

    這一題刻意**不**斷言「檔案裡有沒有 `from datetime import datetime`」：
    那是文字比對，**下次換一個名字漏掉就又沒有人知道了**。
    ⇒ 釘的是**行為**：函式跑完、信組得出來、而且走到了會用 `datetime` 的那一支。
    """
    sent = _capture(monkeypatch)
    last_ok = datetime.now() - timedelta(hours=50)
    en.notify_backup_stale([(STALE_LABEL, last_ok)], 36)

    assert sent, (
        "告警信沒有組出來。\n"
        "⇒ 若是 `NameError: name 'datetime' is not defined`，"
        "那就是 `helpers/email_notify.py` 沒有 import 它，而 :1494 用了 `datetime.now()`。"
    )
    to, subject, html = sent[0]
    assert to, "收件人是空的 —— 那封信不會到任何人手上"
    assert "36" in subject, f"主旨沒帶門檻小時數：{subject!r}"


def test_the_body_really_went_down_the_timestamp_branch(monkeypatch):
    """🔴 **證明它走的是有 `datetime` 的那一支**，不是被繞過去了。

    ⚠️ 沒有這一題，一個「把 `else` 整段刪掉」的修法會讓上一題全綠 ——
    而那會讓「備份過但停了」這個**最重要的情境**顯示成「查無任何成功紀錄」。
    🔑 **修好與繞過在「有沒有丟例外」上長得一模一樣。**
    """
    sent = _capture(monkeypatch)
    last_ok = datetime.now() - timedelta(hours=50)
    en.notify_backup_stale([(STALE_LABEL, last_ok)], 36)
    assert sent, "前提不成立：信沒組出來（見上一題）"
    html = sent[0][2]

    assert last_ok.strftime("%Y-%m-%d %H:%M") in html, (
        "信裡沒有那個時間戳 —— 它沒有走到 `else` 那一支。\n"
        f"（期待 {last_ok.strftime('%Y-%m-%d %H:%M')!r}）"
    )
    assert "查無任何成功紀錄" not in html, (
        "有最後成功時間，信裡卻寫「查無任何成功紀錄」—— 走錯分支了"
    )


def test_the_never_backed_up_branch_is_the_one_that_hid_the_bug(monkeypatch):
    """對照組：`ts=None` 那一支**現在就是綠的**，而那正是問題所在。

    📌 這一題**現在必然綠**，留著是因為它說明了**為什麼那個 bug 活得下來**：
    只要測試資料用 `None`，就永遠碰不到 `datetime`。

    🔑 **判準不是「它現在紅不紅」，是「什麼改動會讓它紅」** ——
    有人把兩條分支合併成一條，它會紅。
    """
    sent = _capture(monkeypatch)
    en.notify_backup_stale([(STALE_LABEL, None)], 36)
    assert sent, "「從未備份過」這條路連信都沒組出來"
    assert "查無任何成功紀錄" in sent[0][2]


def test_mixed_stale_list_does_not_lose_the_never_row(monkeypatch):
    """兩條線一起壞（一條從未成功、一條停了）⇒ **兩列都要在信裡**。

    ⚠️ 這是真實情境：`_check_backup_freshness` 分本機與雲端兩條線各自判斷，
    而它們的失效原因不同 —— 只顯示其中一條會讓人去查錯的地方。
    """
    sent = _capture(monkeypatch)
    last_ok = datetime.now() - timedelta(hours=50)
    en.notify_backup_stale(
        [("本機 SQLite 快照", last_ok), ("雲端每日 JSON", None)], 36)
    assert sent, "前提不成立"
    html = sent[0][2]
    assert "本機 SQLite 快照" in html and "雲端每日 JSON" in html, (
        "兩條線只有一條出現在信裡"
    )
    assert "查無任何成功紀錄" in html and last_ok.strftime("%H:%M") in html, (
        "兩種狀態沒有同時呈現"
    )


# ══════════════════════════════════════════════════════════════════════
# 排程那一側：守門旗標與背景執行緒
# ══════════════════════════════════════════════════════════════════════

def _stale_now(monkeypatch, dt):
    """讓 `_check_backup_freshness()` 認定「備份停了」。

    ## 🔴 我第一版 patch 的是一個**不存在**的名字，而它靜默成功了

    我猜了 `_last_backup_ok`，而真正的接縫是 **`_latest_audit_at(conn, keys)`**
    （`daily_tasks.py:1442`）。⚠️ 而讓這件事無聲無息的是我自己加的
    **`raising=False`** —— 它把「**我 patch 錯對象**」變成「**patch 成功了**」。

    後果：`stale` 是空的 ⇒ 函式在 1478 行就 `return` ⇒ 守門旗標那一題
    **必然綠**，而它什麼都沒驗到。
    🔑 **`raising=False` 是為了「這個屬性可能還不存在」而設計的，
    而它同時也吞掉了「這個屬性根本不叫這個名字」。**
    ⇒ 只有在**真的預期屬性不存在**時才用它；其餘一律讓它爆。
    """
    monkeypatch.setattr(
        dt, "_latest_audit_at",
        lambda conn, keys: datetime.now() - timedelta(hours=99))
    # 雲端那條線在這台機器上不預期存在 —— 讓它只看本機那條，形狀才單純
    import archive as _archive
    monkeypatch.setattr(_archive, "cloud_archive_enabled", lambda: False)


def test_the_daily_guard_is_not_burned_when_the_alert_fails(client, monkeypatch):
    """🔴 **通知失敗時，不可以把「今天寄過了」的旗標記下去。**

    ```python
    routers/daily_tasks.py:1484   _set_setting(guard_key, today)   ← 先寫旗標
    routers/daily_tasks.py:1486   threading.Thread(...).start()    ← 才寄信
    ```

    ⇒ **一次失敗吃掉一整天的重試。** 而這次失敗的是一個**必然**的 `NameError`
    ⇒ 不是「今天沒寄到」，是**永遠不會寄到**。

    🔑 這與第 5 輪的 N15 是同一個形狀：
    **「不要重複寄」與「失敗了要能再試」是兩件事，而同一個旗標同時擔了兩個責任。**
    ⇒ 旗標要在**送出成功之後**才寫。
    """
    import routers.daily_tasks as dt
    from helpers.settings import _get_setting, _set_setting

    _set_setting(GUARD_KEY, "")
    _stale_now(monkeypatch, dt)

    def _boom(*a, **k):
        raise NameError("name 'datetime' is not defined")

    monkeypatch.setattr(dt, "notify_backup_stale", _boom)
    # 讓通知同步跑，否則例外死在背景執行緒裡（那正是下一題要講的）
    monkeypatch.setattr(dt.threading, "Thread",
                        lambda target, args=(), kwargs=None, daemon=None:
                        type("T", (), {"start": lambda s: target(*args)})())

    dt._check_backup_freshness()

    assert not _get_setting(GUARD_KEY), (
        f"通知失敗了，而「今天寄過了」的旗標已經被寫成 {_get_setting(GUARD_KEY)!r}。\n"
        "⇒ 今天不會再試 —— 而這次的失敗是必然的，所以是**永遠**不會寄到。"
    )


def test_a_failing_alert_is_not_completely_silent(client, monkeypatch, caplog):
    """🔴 **通知在背景執行緒裡炸掉，不可以一點痕跡都不留。**

    ```python
    routers/daily_tasks.py:1486   threading.Thread(target=notify_backup_stale, ...)
    routers/daily_tasks.py:1494   except Exception as exc:  _logger.warning(...)
    ```
    ⚠️ 那個 `except` 只包得到「**啟動執行緒**」這個動作，
    **包不到執行緒裡面發生的事** —— 例外在子執行緒裡被 Python 印掉或吞掉，
    而 `_logger` 上什麼都沒有。

    ☠️ **這就是為什麼那個 `NameError` 活到今天**：它每天都在發生，
    **而沒有任何一個地方留下過一個字。**

    🔑 〈防護的副作用落在盲側〉：背景執行緒讓「備份告警」不會拖慢排程，
    **代價是「備份告警自己壞了」變成不可觀測的** ——
    而那正是最需要被觀測的那一種失敗。
    """
    import routers.daily_tasks as dt
    from helpers.settings import _set_setting

    _set_setting(GUARD_KEY, "")
    _stale_now(monkeypatch, dt)
    monkeypatch.setattr(
        dt, "notify_backup_stale",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("寄信炸了")))

    with caplog.at_level(0):
        dt._check_backup_freshness()
        # 給背景執行緒一點時間（若實作仍是裸執行緒）
        import time as _t
        _t.sleep(0.3)

    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "寄信炸了" in blob or "backup" in blob.lower(), (
        "備份告警在背景執行緒裡炸掉，而記錄上一個字都沒有。\n"
        "⇒ 那個 `except Exception` 只包得到「啟動執行緒」，包不到執行緒裡面。\n"
        f"（收到 {len(caplog.records)} 筆 log）"
    )
