"""§4 YA · 寄成功才記「已通知」（以簽核逾期提醒為第一個對象）。

> **檢核報告 §1**：47 支 `notify_*` 裡只有 3 支能回報寄送失敗，
> **而那 3 支正是之前修過的標案雷達** —— 其餘 15 處是
> 「**先寫已通知標記、再射後不理**」，含今天剛改的 §3w。

---

# ☠️ 真正的傷害不是「信掉了」，是「系統以為寄過了」

```
那 15 處    信掉了 ⇒ 標記已寫入 ⇒ **永遠不補**        ← 這一條
其餘 29     信掉了就是掉了，不會被記成成功            ← 壞掉會被發現
```

🔑 〈降級之後它還是會動〉：**壞掉會被報修，而「以為成功」不會。**

---

# 🔴 觀測點：`system_settings` 裡那個 dedup 鍵，**不是 `_send()` 的回傳值**

A 明講（YA9）：
> **觀測點不可以是 `_send()` 的回傳值。**

而理由比「照規矩」深一層：`_send()` **回傳 `None` 不論成敗**
（`helpers/email_notify.py:151` —— 五個安靜 `return` ＋
`except Exception: logger.warning`）
⇒ **它的回傳值裡沒有任何資訊。**
📌 而 `_async_send` 把它丟進 `threading.Thread`
⇒ **呼叫端連那個 `None` 都拿不到。**

🔑 所以唯一有意義的觀測點是**下游那個持久化的事實**：
**那個 dedup 鍵到底有沒有被寫進 `system_settings`。**

---

# ⚠️⚠️ 這個檔的設定順序是安全性事項，不是整潔問題

`email_notify._smtp_send_blocked()` 是 **2026-08-27 的硬性防呆** ——
它存在的理由是：**開發機啟動 dev server 時，簽核逾期催辦的排程
真的對同仁寄出過真實催辦信，而且發生過兩次**
（第一次加了軟性提醒，不夠）。

⇒ 這個檔要走到 SMTP 那一層，就必須繞過那道閘。**順序是硬性的：**
1. **先**把 `smtplib.SMTP` 換成假的
2. **再**繞過 `_smtp_send_blocked`
3. **而且要斷言假的真的裝上了**（`test_ya0_*`）

☠️ 反過來的話，一次 `monkeypatch` 失效就是一封真的信寄給同事。
⚠️ 而 `conftest` 的 NETGUARD **攔不到這一條** —— 它只攔
`urllib.request.urlopen`（那個限制是我自己寫在 NETGUARD 的 docstring 裡的）。

---

# 📌 我釘的名字

| | |
|---|---|
| `daily_tasks.reminder_send_failures()` | 永久性失敗的**落點**（YA8） |

🔑 只釘這一個 —— 其餘全部釘**行為**（標記在不在、下一次會不會重試）。
📌 〈計數器要有落點〉：「要記錄失敗原因」先指出**記在哪張表**，
否則那句要求永遠不會被違反，**也永遠不會被滿足**。
"""
import json
import smtplib
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import routers.daily_tasks as dt  # noqa: E402
from helpers import email_notify  # noqa: E402
from helpers.settings import _get_setting  # noqa: E402

DOC_NO = "YA-0001"
REQUESTED_AT = "2026-09-01T00:00:00"


class _FakeSMTP:
    """假的 SMTP。**預設成功**，`mode="transient"` 時連線就失敗。"""

    sent = []
    mode = "ok"
    connections = 0

    def __init__(self, host, port, timeout=None):
        type(self).connections += 1
        if type(self).mode == "transient":
            raise smtplib.SMTPConnectError(421, "測試：暫時性失敗")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self, *a, **kw):
        return None

    def starttls(self, *a, **kw):
        return None

    def login(self, *a, **kw):
        return None

    def send_message(self, msg, *a, **kw):
        type(self).sent.append(msg)

    def sendmail(self, *a, **kw):
        type(self).sent.append(a)

    def quit(self):
        return None


@pytest.fixture()
def smtp(monkeypatch):
    """🔴 **先換 transport，再開閘。順序是安全性事項（見檔頭）。**"""
    _FakeSMTP.sent = []
    _FakeSMTP.mode = "ok"
    _FakeSMTP.connections = 0

    # ① transport 先換掉 —— 這一行沒生效的話，下面那一行會讓真信寄出去
    monkeypatch.setattr(email_notify.smtplib, "SMTP", _FakeSMTP)
    # ② 才繞過硬擋
    monkeypatch.setattr(email_notify, "_PRODUCTION_INSTALL", True)
    # ③ 設定要「啟用」，否則 `_send` 第一個 return 就走掉了
    # ⚠️ 鍵名是從 `_send()` **讀出來的**（`email_notify.py:161-165`），
    #    不是憑印象寫的 —— 我第一版猜成 `host`／`user`／`password`，
    #    而實際是 `smtp_host`／`smtp_user`／`smtp_password`
    #    ⇒ `_send()` 在「SMTP credentials not configured」那個 return 就走掉了，
    #      而 YA0 的斷言把它抓出來了（連線次數 0）。
    # 🔑 今天第五次「用回想代替查」，而這一次**是我自己的量尺擋住的**。
    monkeypatch.setattr(email_notify, "_cfg", lambda: {
        "enabled": True,
        "smtp_host": "smtp.test.invalid", "smtp_port": 587,
        "smtp_user": "test@test.invalid", "smtp_password": "x",
        "from_name": "MOTRIX 測試", "dev_mode": False,
    })
    monkeypatch.setattr(email_notify, "_lookup_emails",
                        lambda users, kind: ["approver@test.invalid"])
    monkeypatch.setattr(email_notify, "_superadmin_emails",
                        lambda kind: ["boss@test.invalid"])
    return _FakeSMTP


@pytest.fixture()
def pending_quote(client):
    """一張卡在簽核中的報價單，並清掉它可能留下的 dedup 鍵。"""
    import db
    from helpers.settings import _set_setting
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM quotations WHERE quote_no LIKE 'YA-%'")
        conn.execute(
            "INSERT INTO quotations (quote_no, customer_name, project_name, "
            "status, data_json, created_at) VALUES (?,?,?,?,?,?)",
            (DOC_NO, "YA 測試客戶", "YA 測試專案", "待審核",
             json.dumps({"approval": {"requestedAt": REQUESTED_AT}},
                        ensure_ascii=False), REQUESTED_AT))
        for row in conn.execute(
                "SELECT key FROM system_settings WHERE key LIKE ?",
                (f"approval_notif.quotations.{DOC_NO}.%",)).fetchall():
            _set_setting(row["key"], None)
        conn.commit()
    finally:
        conn.close()
    return DOC_NO


def _markers():
    """那張單子所有「已通知」的鍵。**這是唯一的觀測點。**"""
    import db
    conn = db.get_db()
    try:
        return {r["key"] for r in conn.execute(
            "SELECT key FROM system_settings WHERE key LIKE ? "
            "AND value_json IS NOT NULL AND value_json <> 'null'",
            (f"approval_notif.quotations.{DOC_NO}.%",)).fetchall()}
    finally:
        conn.close()


def _run(monkeypatch, days, on=(2026, 9, 22)):
    class _Today(date):
        @classmethod
        def today(cls):
            return cls(*on)

    monkeypatch.setattr(dt, "_workdays_elapsed", lambda *a, **kw: days)
    monkeypatch.setattr(dt, "_date", _Today)
    dt._check_approval_reminders()


# ══════════════════════════════════════════════════════════════════════
# YA0 · 量尺：假的 SMTP 真的裝上了（**這一題是安全閘**）
# ══════════════════════════════════════════════════════════════════════

def test_ya0_the_fake_transport_is_really_in_place(smtp):
    """🔴🔴 YA0：**證明 `smtplib.SMTP` 真的被換掉了。**

    ☠️ 這不是整潔問題。這個檔繞過了 `_smtp_send_blocked()` ——
    而那道閘存在的理由是**開發機真的對同仁寄出過兩次真實催辦信**。
    ⇒ 如果 `monkeypatch` 沒有生效而閘又被繞過，**下一題就會寄真信**。

    🔑 而 `conftest` 的 NETGUARD 攔不到它（只攔 `urllib.request.urlopen`）
    ⇒ **沒有第二道防線**，所以這一題必須存在。
    """
    assert email_notify.smtplib.SMTP is _FakeSMTP, (
        "`smtplib.SMTP` 沒有被換成假的，而 `_smtp_send_blocked` 已經被繞過 ——\n"
        "☠️ 這個狀態下寄出去的是真信。**立刻停下來。**"
    )
    email_notify._send(["x@test.invalid"], "量尺", "<p>x</p>")
    assert _FakeSMTP.connections == 1, (
        f"假的 SMTP 沒有被用到（連線次數 {_FakeSMTP.connections}）——\n"
        "⇒ 那表示 `_send()` 在到達 SMTP 之前就被某個 return 擋掉了，"
        "而下面那幾題會**空綠**。"
    )


# ══════════════════════════════════════════════════════════════════════
# YA1 / YA6 · 寄失敗 ⇒ 不可以標記已通知
# ══════════════════════════════════════════════════════════════════════

def test_ya1_a_failed_send_does_not_mark_it_as_notified(
        client, pending_quote, smtp, monkeypatch):
    """🔴🔴 YA1：**SMTP 失敗時，「已通知」不可以被寫入。**

    ☠️ 現況：`_fire()` 先 `_set_setting(g, today_str)` **才**開執行緒寄信
    ⇒ 信掉了而標記留著 ⇒ **那張單子永遠不會再被提醒**。
    🔑 而它的症狀是**沒有症狀**：畫面正常、log 裡有一行 warning，
    **而沒有人在看那一行**。

    📌 觀測點是 `system_settings` 裡那個鍵，**不是 `_send()` 的回傳值**
    —— 後者不論成敗都是 `None`（見檔頭）。
    """
    smtp.mode = "transient"
    assert not _markers(), "前提不成立：一開始就有標記"

    _run(monkeypatch, 3)

    assert smtp.connections >= 1, (
        "一次都沒有嘗試連 SMTP —— 這一題的前提不成立"
    )
    assert not _markers(), (
        f"SMTP 失敗，而「已通知」被寫進去了：{sorted(_markers())}\n"
        "☠️ 那張單子從此不會再被提醒，而畫面上完全正常。"
    )


def test_ya6_after_a_failure_the_next_run_tries_again(
        client, pending_quote, smtp, monkeypatch):
    """🔴🔴 YA6：失敗之後，**下一次排程要再試一次**。

    ☠️ 少了這一題，一個「失敗就不標記，而也不再嘗試」的實作會讓 YA1 綠 ——
    🔑 **「沒有留下錯的紀錄」與「事情被做完」是兩件事。**
    """
    smtp.mode = "transient"
    _run(monkeypatch, 3)
    first = smtp.connections
    assert first >= 1, "前提不成立"

    _run(monkeypatch, 3, on=(2026, 9, 23))
    assert smtp.connections > first, (
        f"失敗之後下一次排程沒有再試（連線次數停在 {first}）——\n"
        "⇒ 沒有標記成功，也沒有重試 ⇒ 那封信永遠不會出去。"
    )


# ══════════════════════════════════════════════════════════════════════
# YA2 / YA7 · 寄成功 ⇒ 要標記，而且不再重寄
# ══════════════════════════════════════════════════════════════════════

def test_ya7_a_successful_send_marks_it_and_does_not_repeat(
        client, pending_quote, smtp, monkeypatch):
    """🔴 YA7：**SMTP 成功 ⇒ 標記寫入，而下一次不再寄。**

    📌 這是 YA1 的反向控制：只驗「失敗不標記」的話，
    一個「**永遠不標記**」的實作會綠 —— 而那會讓使用者每天收到同一封。
    🔑 〈判準的寬窄都會騙人〉：**兩個方向都要有人守。**

    ⚠️ 而它還釘住一件比較深的事：**排程返回時，標記的狀態必須已經是最終的。**
    ☠️ 現況是 `threading.Thread(...)` 射後不理 ⇒ **排程返回時結果還沒發生**
    ⇒ **那個設計在結構上不可能知道成敗。**
    🔑 所以這一題不只要求「標記對」，它要求**寄送是同步的**（或者等到它有結果）。
    """
    smtp.mode = "ok"
    _run(monkeypatch, 3)

    assert smtp.sent, "一封都沒寄出 —— 前提不成立"
    marks = _markers()
    assert marks, (
        "SMTP 成功了，而「已通知」沒有被寫入 ——\n"
        "⇒ 下一次排程會再寄一封同樣的信。\n"
        "⚠️ 也可能是寄送還在背景執行緒裡：**那表示排程返回時結果還沒發生**，"
        "而那個設計在結構上不可能知道成敗。"
    )

    before = len(smtp.sent)
    _run(monkeypatch, 3, on=(2026, 9, 23))
    assert len(smtp.sent) == before, (
        f"隔一天又寄了 {len(smtp.sent) - before} 封（仍在 d3 這一階）"
    )


# ══════════════════════════════════════════════════════════════════════
# YA4 / YA8 · 永久性失敗與暫時性失敗要分開
# ══════════════════════════════════════════════════════════════════════

def test_ya8_a_permanent_failure_is_marked_and_recorded(
        client, pending_quote, smtp, monkeypatch):
    """🔴🔴 YA8：**收件人為空（永久性）⇒ 標記寫入 ＋ 失敗落點有一筆，
    而且下一次不重試。**

    ## ☠️ 不分開的後果（A 的 YA4，它不在檢核報告裡）

    ```
    transient   SMTP 連不上、逾時、5xx        ⇒ 不標記，明天再試
    permanent   收件人清單為空、SMTP 未設定    ⇒ 標記 ＋ 記錄失敗原因
    ```

    ☠️ 不分開的話：**那個人沒填 email ⇒ 排程每天重試到天荒地老**，
    🔑 **而「每天重試」與「已經修好了」在 log 上長得一模一樣。**

    📌 而「要記錄失敗原因」必須指出**記在哪** ——
    〈計數器要有落點〉：沒有落點的要求**永遠不會被違反，也永遠不會被滿足**。
    ⇒ 我釘 `reminder_send_failures()`。
    """
    monkeypatch.setattr(email_notify, "_lookup_emails", lambda u, k: [])
    monkeypatch.setattr(email_notify, "_superadmin_emails", lambda k: [])

    _run(monkeypatch, 3)

    assert _markers(), (
        "收件人是空的（永久性失敗），而「已通知」沒有被寫入 ——\n"
        "☠️ 那會讓排程每天重試到天荒地老，"
        "而「每天重試」與「已經修好了」在 log 上長得一模一樣。"
    )

    query = getattr(dt, "reminder_send_failures", None)
    assert callable(query), (
        "`routers/daily_tasks.py` 缺少 `reminder_send_failures()` ——\n"
        "📌 「要記錄失敗原因」必須指出記在哪，否則那句要求"
        "**永遠不會被違反，也永遠不會被滿足**。"
    )
    records = list(query())
    assert records, (
        "永久性失敗沒有留下任何紀錄 —— 那張單子的提醒從此靜默消失，"
        "而沒有人知道它為什麼不寄了。"
    )
    blob = json.dumps(records, ensure_ascii=False, default=str)
    assert DOC_NO in blob, (
        f"失敗紀錄裡找不到單號 {DOC_NO}：{blob[:240]}\n"
        "⇒ 一筆說不出「是哪一張單子」的失敗紀錄，沒有人能處置它。"
    )


def test_ya8b_a_transient_failure_is_not_recorded_as_permanent(
        client, pending_quote, smtp, monkeypatch):
    """🔴🔴 YA8b 反向控制：**暫時性失敗不可以被記成永久性。**

    ☠️ 少了這一題，一個「**任何失敗都標記＋記錄**」的實作會讓 YA8 綠 ——
    而那正是 YA1 要防的東西（SMTP 抖一下 ⇒ 那張單子永遠不再提醒）。
    🔑 **YA8 與 YA1 的判準只差「失敗的性質」這一個維度**，
    而一個不看性質的實作會同時滿足其中一個、破壞另一個。
    """
    smtp.mode = "transient"
    _run(monkeypatch, 3)

    assert not _markers(), (
        "暫時性失敗被標記成已通知了 —— 見 YA1"
    )
    query = getattr(dt, "reminder_send_failures", None)
    if not callable(query):
        pytest.skip("`reminder_send_failures()` 還不存在（YA8 會紅）")
    blob = json.dumps(list(query()), ensure_ascii=False, default=str)
    assert DOC_NO not in blob, (
        f"暫時性失敗被記進永久性失敗的落點裡：{blob[:240]}\n"
        "⇒ 那張單子會被當成「已經處理過的失敗」，而它其實只是網路抖了一下。"
    )


# ══════════════════════════════════════════════════════════════════════
# YA10 · 🔴 機器層級的問題不是 permanent，是 skipped（B 的裁決）
# ══════════════════════════════════════════════════════════════════════

def test_ya10_a_machine_level_problem_does_not_mark_anything(
        client, pending_quote, smtp, monkeypatch):
    """🔴🔴 YA10：**SMTP 未啟用（機器層級）⇒ 標記不可以被寫入，而且下次再試。**

    ## 📌 這一條與 A 的 YA4 字面不同，而 B 的版本是對的

    A 的 YA4 把「SMTP 未設定」列在 `permanent`。**B 當場改成 `skipped`**，
    理由是**壞掉的東西不是同一個**：

    | | 壞的是 | 修好之後 |
    |---|---|---|
    | 收件人沒有 email | **這一封** | 那個人當時就該被通知，補寄沒有意義 ⇒ `permanent` |
    | SMTP 未設定／未啟用／開發機硬擋 | **整台機器** | **每一封都該補寄** ⇒ `skipped` |

    ☠️ 把機器層級的問題記成 `permanent` 的後果：
    **一個設定沒填，造成 N 筆單子被永久標記成「已通知」** ——
    🔑 而管理員把 SMTP 設好之後，**那些信永遠不會出去，且沒有人知道**。
    📌 而「每天重試」在這一側幾乎沒有成本：`_send()` 在碰到網路之前就返回了。

    ## 🔑 這一題與 YA8 是一對，而它們的判準只差「壞的是哪一層」

    YA8：收件人為空 ⇒ **要**標記。
    這一題：SMTP 未啟用 ⇒ **不可以**標記。
    ⚠️ 一個不分層級的實作會同時滿足其中一個、破壞另一個 ——
    **而兩題都在這個檔裡，所以它跑不掉。**
    """
    monkeypatch.setattr(email_notify, "_cfg", lambda: {"enabled": False})
    assert not _markers(), "前提不成立：一開始就有標記"

    _run(monkeypatch, 3)

    assert smtp.connections == 0, (
        f"SMTP 未啟用，而它仍然嘗試連線 {smtp.connections} 次 —— "
        "那表示 `enabled` 那道判斷沒有生效，這一題的前提不成立"
    )
    assert not _markers(), (
        f"SMTP 未啟用（機器層級），而「已通知」被寫進去了：{sorted(_markers())}\n"
        "☠️ 一個設定沒填，造成 N 筆單子被永久標記成已通知 ——\n"
        "而管理員把 SMTP 設好之後，那些信永遠不會出去，且沒有人知道。"
    )

    query = getattr(dt, "reminder_send_failures", None)
    if callable(query):
        blob = json.dumps(list(query()), ensure_ascii=False, default=str)
        assert DOC_NO not in blob, (
            f"機器層級的問題被記進永久性失敗的落點裡：{blob[:240]}\n"
            "⇒ 那會讓它看起來像「已經處置過的失敗」。"
        )


def test_ya10b_the_next_run_retries_after_a_skip(
        client, pending_quote, smtp, monkeypatch):
    """🔴 YA10b 反向控制：**`skipped` 之後，下一次排程要再試。**

    ☠️ 少了這一題，一個「`skipped` 就不標記、而也不再嘗試」的實作會讓
    YA10 綠 —— 而 SMTP 設好之後那些信**仍然不會出去**。
    🔑 跟 YA6 同一句：**「沒有留下錯的紀錄」與「事情被做完」是兩件事。**
    """
    monkeypatch.setattr(email_notify, "_cfg", lambda: {"enabled": False})
    _run(monkeypatch, 3)
    assert not _markers(), "前提不成立（見 YA10）"

    # 設定修好了 —— 下一次排程要把那封信寄出去
    monkeypatch.setattr(email_notify, "_cfg", lambda: {
        "enabled": True,
        "smtp_host": "smtp.test.invalid", "smtp_port": 587,
        "smtp_user": "test@test.invalid", "smtp_password": "x",
        "from_name": "MOTRIX 測試", "dev_mode": False,
    })
    _run(monkeypatch, 3, on=(2026, 9, 23))

    assert smtp.sent, (
        "SMTP 設定修好之後，那封被 skip 掉的信沒有補寄 ——\n"
        "⇒ 使用者把設定填好了，而系統再也不提那件事。"
    )
    assert _markers(), "補寄成功了而標記沒有寫入（見 YA7）"
