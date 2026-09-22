"""§3w · 簽核逾期提醒改成 1／3／5／10／15／20…，並刪掉一句文案。

> **使用者原話**：「匯款申請簽核逾期提醒這個，第三天、第五天、再來第十天以五為
> 基準重新寄信，信件內容這段刪掉『目前已同步通知系統管理員協助處理』。」

---

# 🔴 現況（A 查出、我逐行複核過）

```
routers/daily_tasks.py:1786-1791
if   days_elapsed >= 5:  _fire(True,  f"5d.{today_str}")   ← dedup 鍵含日期
elif days_elapsed >= 3:  _fire(True,  "3d")
else:                    _fire(False, "1d")
```

☠️ **第 5 天之後每天一封**：dedup 鍵裡有 `today_str` ⇒ 每天都是新鍵。
⇒ 一筆卡 20 個工作日的單子**現在會寄 18 封**。

📌 而 `approval_reminder` 這條線**在今天之前完全沒有測試**（我 grep 過 `tests/`）。

---

# ⚠️ 階梯邏輯現在埋在迴圈裡的 closure，測不到

`_fire` 是 `_check_approval_reminders` 裡的巢狀函式，判斷式是三個 `if`。
⇒ 我釘一個**具名純函式**當接縫 —— 那是這個 repo 自己的教訓
（〈決定邏輯抽純函式才測得到「換一種設定」〉）。

## 📌 我釘的名字

| | |
|---|---|
| `reminder_stage(days)` | → `"d1"`／`"d3"`／`"d5"`／`"d10"`… 或 **`None`（不寄）** |
| `reminder_stages_at_or_below(days)` | 跨越多階時，**要一併標記成已寄**的那幾階（WA6） |
| `reminder_dedup_key(stage)` | ⚠️ **只吃 stage，不吃日期** —— 見 WA3 |

🔑 **`reminder_dedup_key` 的簽名本身就是那道防線**：
不收日期參數 ⇒ 「每天一個新鍵」**在結構上不可能**，
而不是靠「記得不要把 `today_str` 串進去」。
📌 〈修作法不要修結果〉。
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import routers.daily_tasks as dt  # noqa: E402
from helpers import email_notify  # noqa: E402

#: 使用者要的階梯：1、3、5，之後**以五為基準**。
LADDER = (1, 3, 5, 10, 15, 20, 25, 30)

#: 一定不可以寄的天數。⚠️ 6/7/8/9 是這一節的核心 ——
#: **現行「每天寄」的實作在第 10 天也確實寄了**，所以只驗 LADDER 會全綠。
SILENT = (2, 4, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18, 19)


def _need(name):
    got = getattr(dt, name, None)
    assert got is not None, (
        f"`routers/daily_tasks.py` 缺少 `{name}` —— 見本檔開頭〈我釘的名字〉"
    )
    return got


# ══════════════════════════════════════════════════════════════════════
# WA1 / WA2 · 階梯本身
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("days", LADDER)
def test_wa1_the_ladder_fires_on_the_chosen_days(days):
    """🔴 WA1：只在 {1, 3, 5, 10, 15, 20, …} 寄。"""
    stage = _need("reminder_stage")(days)
    assert stage == f"d{days}", (
        f"第 {days} 個工作日應該回 `d{days}`，實際 {stage!r}"
    )


@pytest.mark.parametrize("days", SILENT)
def test_wa2_no_mail_on_any_other_day(days):
    """🔴🔴 WA2 反向控制：**第 6／7／8／9 天一封都不寄。**

    ☠️ 沒有這一題，**現行的「每天寄」實作會讓 WA1 全綠** ——
    它在第 10 天也確實寄了（因為它每天都寄）。
    🔑 〈判準的寬窄都會騙人〉：「該寄的那幾天有寄」是一個**超集**永遠滿足的條件。

    📌 名單裡刻意包含 **2 與 4**（第一階與第二階之間），以及 **11–14、16–19**
    —— 只驗 6–9 的話，一個「第 10 天之後恢復每天寄」的實作會綠。
    """
    stage = _need("reminder_stage")(days)
    assert stage is None, (
        f"第 {days} 個工作日不該寄信，而它回了 {stage!r}\n"
        "⇒ 一筆卡 20 個工作日的單子現在會寄 18 封。"
    )


def test_wa1b_day_zero_and_negative_are_silent():
    """🔴 WA1b：第 0 天與負數不寄。

    📌 現行程式碼在 `days_elapsed < 1` 就 `continue`，
    而那個判斷在**呼叫端**。⚠️ 抽成純函式之後，
    **如果純函式自己不管這一段，那道防線就搬到了一個沒有人看的地方** ——
    〈守門守的對象被搬走〉。
    """
    stage_fn = _need("reminder_stage")
    for days in (0, -1, -100):
        assert stage_fn(days) is None, f"{days} 應該不寄，實際 {stage_fn(days)!r}"


# ══════════════════════════════════════════════════════════════════════
# WA3 · dedup 鍵不可以含日期
# ══════════════════════════════════════════════════════════════════════

def test_wa3_the_dedup_key_does_not_depend_on_the_date(monkeypatch):
    """🔴 WA3：dedup 鍵**不可以再含 `today_str`**。

    ☠️ 現行是 `f"5d.{today_str}"` ⇒ **每天都是新鍵 ⇒ 每天一封**。
    🔑 而這一題的真正防線是**那支函式的簽名**：`reminder_dedup_key(stage)`
    **不收日期** ⇒ 「每天一個新鍵」在結構上不可能。
    📌 〈修作法不要修結果〉：不是靠記得不要串日期進去。

    ⚠️ 而簽名擋不住「函式裡自己去拿今天」⇒ 所以也驗**換一天結果相同**。
    """
    key_fn = _need("reminder_dedup_key")

    import inspect
    params = list(inspect.signature(key_fn).parameters)
    assert len(params) == 1, (
        f"`reminder_dedup_key` 的參數是 {params} —— 應該只有 stage 一個。\n"
        "⇒ 多一個日期參數，「每天一個新鍵」就又變成可能了。"
    )

    class _Monday(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 21)

    class _Tuesday(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 22)

    monkeypatch.setattr(dt, "_date", _Monday)
    first = key_fn("d5")
    monkeypatch.setattr(dt, "_date", _Tuesday)
    second = key_fn("d5")

    assert first == second, (
        f"同一階在兩天算出不同的鍵：{first!r} vs {second!r}\n"
        "⇒ 那支函式自己去拿了今天的日期。"
    )
    assert "2026" not in first and "09" not in first, (
        f"鍵裡有日期的痕跡：{first!r}"
    )


# ══════════════════════════════════════════════════════════════════════
# WA6 · 跨越多階只寄最高的，而低的要一併標記
# ══════════════════════════════════════════════════════════════════════

def test_wa6_crossing_several_thresholds_marks_the_lower_ones_too():
    """🔴🔴 WA6：第 2 天停機到第 12 天 ⇒ **只寄 `d10`**，
    而 `d1`／`d3`／`d5` **要一併標記成已寄**。

    ☠️ 不標記的話，**下一次排程會把它們補一遍** ——
    使用者會在同一天收到 `d1`、`d3`、`d5`、`d10` 四封，
    🔑 而那正是這一節要消滅的東西（一次寄太多封）。

    📌 所以這裡有兩個問題，要兩個答案：
    **「這次寄哪一封」**（`reminder_stage`）與
    **「要把哪幾階記成已寄」**（`reminder_stages_at_or_below`）。
    ⚠️ 用同一個答案回答兩個問題的話，其中一個一定會錯。
    """
    at_or_below = _need("reminder_stages_at_or_below")

    assert _need("reminder_stage")(12) == "d10", "第 12 天最高的那一階是 d10"
    stages = list(at_or_below(12))
    assert stages == ["d1", "d3", "d5", "d10"], (
        f"第 12 天要標記的階段應該是 d1/d3/d5/d10，實際 {stages}\n"
        "⇒ 漏標的那幾階，下一次排程會補寄。"
    )

    assert list(at_or_below(1)) == ["d1"]
    assert list(at_or_below(4)) == ["d1", "d3"], (
        "第 4 天還沒到 d5，不可以把 d5 也標記掉 —— "
        "那會讓第 5 天那封永遠不寄。"
    )
    assert list(at_or_below(0)) == [], "第 0 天不該標記任何階段"


# ══════════════════════════════════════════════════════════════════════
# WA4 / WA5 / WA7 · 端到端（真的跑那支排程）
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def pending_quote(client):
    """一張卡在簽核中的報價單。**排程是從這裡撈資料的。**"""
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM quotations WHERE quote_no LIKE 'WA-%'")
        conn.execute(
            "INSERT INTO quotations (quote_no, customer_name, project_name, "
            "status, data_json, created_at) VALUES (?,?,?,?,?,?)",
            ("WA-0001", "階梯測試客戶", "階梯測試專案", "待審核",
             json.dumps({"approval": {"requestedAt": "2026-09-01T00:00:00"}},
                        ensure_ascii=False),
             "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return "WA-0001"


@pytest.fixture()
def mails(monkeypatch):
    """攔下寄信，只記參數。

    ⚠️ 換的是 `routers.daily_tasks.notify_approval_reminder`（**模組裡的那份
    副本**，`daily_tasks.py:28` 是 `from ... import`）——
    換 `email_notify` 那一份打不到它。**今天反覆遇到的同一條。**
    📌 順帶避開它原本會開的那條 `threading.Thread`。
    """
    calls = []
    monkeypatch.setattr(dt, "notify_approval_reminder",
                        lambda *a, **kw: calls.append((a, kw)))
    return calls


def _run_at_day(monkeypatch, days, on=(2026, 9, 22)):
    """讓排程看到「已經過了 N 個工作日」，**而且是在指定的日曆日跑的**。

    ## 🔴 `on` 這個參數是後來補的，而少了它這幾題全是假綠

    ⚠️ 第一版兩次都跑在同一個日曆日。而現行缺陷是
    **「第 5 天之後每天一封」** —— dedup 鍵是 `f"5d.{today_str}"`
    ⇒ **同一天再跑一次，鍵一模一樣，本來就不會重複寄。**

    ☠️ 所以 WA4／WA7 的「第二次跑不可以再寄」**綠了**，
    而它證明的是「同一天不重複」—— **現行實作已經做到的那件事**。
    🔑 〈證據的適用範圍〉：綠燈是真的，**而它證明的不是我以為的那件事**。
    ⇒ 兩次之間要**換一天**，那個缺陷才會現形。

    📌 換 `_workdays_elapsed`（模組裡的副本）而不是算真的日期 ——
    工作日計算有它自己的已知限制（不排除國定假日），而那不是這一節要驗的。
    """
    class _Today(date):
        @classmethod
        def today(cls):
            return cls(*on)

    monkeypatch.setattr(dt, "_workdays_elapsed", lambda *a, **kw: days)
    monkeypatch.setattr(dt, "_date", _Today)
    dt._check_approval_reminders()


def test_wa4_the_same_stage_does_not_fire_twice(
        client, pending_quote, mails, monkeypatch):
    """🔴 WA4 反向控制：**同一階段第二次跑不可以再寄。**

    📌 這一題與 WA3 的差別：WA3 驗**鍵的形狀**，這一題驗
    **那個鍵真的被拿去查了**。
    🔑 〈證據的適用範圍〉：鍵對了不等於有人用它。
    """
    _run_at_day(monkeypatch, 10, on=(2026, 9, 22))
    first = len(mails)
    assert first == 1, f"第 10 天應該寄 1 封，實際 {first} 封"

    # 🔴 **換一天再跑**：同一天再跑一次的話，現行的 `5d.{today_str}` 鍵
    #    本來就不會重複寄 ⇒ 那樣這一題是假綠的（見 `_run_at_day` 的說明）。
    _run_at_day(monkeypatch, 10, on=(2026, 9, 23))
    assert len(mails) == first, (
        f"隔一天再跑（仍在 d10 這一階）又寄了 {len(mails) - first} 封。"
        "⇒ dedup 鍵裡還有日期，所以每天都是新鍵、每天一封。"
    )


def test_wa5_a_skipped_threshold_is_caught_up(
        client, pending_quote, mails, monkeypatch):
    """🔴 WA5：**跨越門檻要補寄** —— 第 4 天跳到第 6 天 ⇒ 第 5 天那封要補。

    📌 成因不是假想：**週末與停機**。排程沒跑的那幾天，門檻會被跳過。
    ⚠️ 而「第 6 天不寄」（WA2）與「第 6 天要補寄 d5」**看起來矛盾，其實不是**：
    🔑 **第 6 天不產生新的一封，但它要把欠的那一封補掉。**
    """
    _run_at_day(monkeypatch, 4)
    assert len(mails) == 1, (
        f"第 4 天應該只寄過 d1／d3 裡的一封（依序補），實際 {len(mails)} 封"
    )

    before = len(mails)
    _run_at_day(monkeypatch, 6)
    assert len(mails) == before + 1, (
        f"第 4 天跳到第 6 天，應該補寄 d5 那一封，"
        f"而信數從 {before} 變成 {len(mails)}"
    )


def test_wa7_a_long_outage_still_sends_exactly_one(
        client, pending_quote, mails, monkeypatch):
    """🔴🔴 WA7 反向控制：第 2 天停機到第 12 天 ⇒ **信數剛好 1**，
    而信裡的天數是 **12**。

    ☠️ 少了這一題，一個「把欠的每一階都補寄」的實作會讓 WA5 綠 ——
    而使用者會在同一天收到 **四封**（d1／d3／d5／d10）。
    🔑 **「補掉欠的」與「補寄欠的」只差一個字，而收件匣裡差四封。**

    📌 並且驗**天數是 12 不是 10**：信裡要說實際等了幾天，
    ⚠️ 而不是那一階的門檻值 —— 後者會讓使用者以為單子只卡了 10 天。
    """
    _run_at_day(monkeypatch, 12, on=(2026, 9, 22))

    assert len(mails) == 1, (
        f"第 2 天停機到第 12 天，應該只寄 1 封（d10），實際 {len(mails)} 封：\n"
        + "\n".join(str(m[0][:4]) for m in mails[:5])
    )
    args = mails[0][0]
    assert 12 in args, (
        f"信裡的天數應該是實際等待的 12，而參數是 {args[:4]}\n"
        "⇒ 用門檻值（10）的話，使用者會以為單子只卡了 10 天。"
    )

    before = len(mails)
    _run_at_day(monkeypatch, 12, on=(2026, 9, 23))
    assert len(mails) == before, (
        "隔一天再跑（仍在 d10 這一階）又寄了信 —— "
        "⇒ 要嘛 dedup 鍵裡還有日期，要嘛低階段沒有被一併標記成已寄（WA6）。"
    )


# ══════════════════════════════════════════════════════════════════════
# WB · 刪掉那一句，而不要順手刪掉別的
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def captured_mail(monkeypatch):
    """攔 `email_notify._async_send`，拿到真正組出來的 HTML。"""
    box = []
    monkeypatch.setattr(email_notify, "_async_send",
                        lambda to, subject, html: box.append(
                            {"to": to, "subject": subject, "html": html}))
    monkeypatch.setattr(email_notify, "_lookup_emails",
                        lambda users, kind: ["approver@example.com"])
    monkeypatch.setattr(email_notify, "_superadmin_emails",
                        lambda kind: ["boss@example.com"])
    return box


def test_wb1_the_sentence_is_gone_from_the_body(captured_mail):
    """🔴 WB1：**刪掉「目前已同步通知系統管理員協助處理。」**

    📌 觀測點是**真正組出來的 HTML**，不是原始碼文字 ——
    🔑 文字比對答的是「有沒有被寫出來」，而這一題問的是
    **「使用者會不會讀到它」**。
    """
    email_notify.notify_approval_reminder(
        "匯款申請", "WB-0001", "測試", 10, ["approver"], True)
    assert captured_mail, "一封都沒寄出 —— 前提不成立"
    html = captured_mail[0]["html"]
    assert "目前已同步通知系統管理員協助處理" not in html, (
        "那句話還在信裡 —— 使用者明確要求刪掉它。"
    )


def test_wb2_the_also_superadmin_parameter_is_still_there():
    """🔴 WB2：**`also_superadmin` 這個參數本身不要一起刪。**

    ☠️ 它決定的是**三件事**，而要刪的只有第一件：

    | | 位置 |
    |---|---|
    | 1 email 文案 | `email_notify.py:621` ← **這次要刪的** |
    | 2 email 收件人 | `email_notify.py:604` `_superadmin_emails(...)` |
    | 3 站內通知收件人 | `daily_tasks.py:1781` `notify_targets` |

    📌 A 原本只看到第 3 項，實查之後更正。
    🔑 **若只針對第 3 項寫守門，第 2 項被順手刪掉時照樣全綠。**
    ⇒ 兩項都有題（WB3a／WB3b）。
    """
    import inspect
    params = inspect.signature(email_notify.notify_approval_reminder).parameters
    assert "also_superadmin" in params, (
        "`also_superadmin` 參數被刪掉了 —— 那個參數還決定兩種收件人。"
    )


def test_wb3_superadmin_stays_in_the_email_recipients(captured_mail):
    """🔴 WB3：`also_superadmin=True` 時 superadmin 仍在 **email 收件人**裡。

    ⚠️ **這是 A 原本沒看到的那一項。**
    📌 函式名刻意是 `wb3` 不是 `wb3a` —— 規格宣告的是 `WB3`，
    而覆蓋率守門認的是**函式名裡的那個編號**：
    ⚠️ 命名成 `wb3a` 的話，`WB3` 會被判定成「規格宣告了而沒有人寫」。
    🔑 今天第二次踩到它（SO5／SO6 那次是參數化）——
    **同一道守門，同一個成因，而我兩次都是用最自然的命名習慣。**
    """
    email_notify.notify_approval_reminder(
        "匯款申請", "WB-0002", "測試", 10, ["approver"], True)
    assert captured_mail, "一封都沒寄出 —— 前提不成立"
    assert "boss@example.com" in captured_mail[0]["to"], (
        f"superadmin 不在收件人裡：{captured_mail[0]['to']}"
    )


def test_wb3b_superadmin_is_left_out_when_the_flag_is_false(captured_mail):
    """🔴 WB3b 反向控制：`also_superadmin=False` 時 superadmin **不在**收件人裡。

    ☠️ 少了這一題，一個「**一律加上 superadmin**」的實作會讓 WB3a 綠 ——
    而那正是原本的設計要避免的：**只通知 superadmin，不是全部 admin**，
    🔑 而「一律加」會讓第 1 天那封也灌進管理員的收件匣。
    """
    email_notify.notify_approval_reminder(
        "匯款申請", "WB-0003", "測試", 1, ["approver"], False)
    assert captured_mail, "一封都沒寄出 —— 前提不成立"
    assert "boss@example.com" not in captured_mail[0]["to"], (
        f"`also_superadmin=False` 而 superadmin 仍在收件人裡："
        f"{captured_mail[0]['to']}"
    )


def test_wb5_the_badge_tiers_are_left_alone(captured_mail):
    """🟢 WB5：badge 的 `>= 5` 分級**保持不動** —— 10／15／20 都落在那一檔。

    📌 A 裁：badge 那句「已通知管理員」**留著**。
    使用者只說刪**內文**那一句；badge 是**狀態標示**（這封也寄給了管理員），
    不是安撫語。**要一起刪是另一個裁示，A 不替他決定。**

    ⚠️ 這一題存在的理由是**防止順手改** —— 改階梯的時候
    最自然的動作是「把 badge 也改成 1/3/5/10/15」，
    🔑 而那會讓「急件」這個字消失在第 10 天的信裡。

    ↩︎ 什麼改動會讓它紅：把 `days_elapsed >= 5` 那個分支改成 `== 5`。
    """
    for days, expect in ((10, "急件"), (15, "急件"), (3, "已通知管理員")):
        captured_mail.clear()
        email_notify.notify_approval_reminder(
            "匯款申請", f"WB-{days}", "測試", days, ["approver"], True)
        assert captured_mail, f"第 {days} 天一封都沒寄出"
        html = captured_mail[0]["html"]
        assert expect in html, (
            f"第 {days} 個工作日的 badge 裡沒有「{expect}」——\n"
            "⇒ badge 的分級被順手改掉了（A 裁定它保持不動）。"
        )


def test_wb4_the_docstring_no_longer_says_only_one_three_five():
    """🟡 WB4：`notify_approval_reminder` 的 docstring 要改成 1/3/5/10/15…。

    ⚠️ **文字比對，弱的** —— 而它防的是今晚反覆出現的那一族：
    🔑 **一句「成因已經變掉的解釋」** 會讓下一個人照它做決定。
    📌 現在寫著「卡在簽核柱列超過**工作日 1/3/5 天時**由排程呼叫」，
    而改完之後那句話會是錯的。
    """
    import inspect
    doc = inspect.getdoc(email_notify.notify_approval_reminder) or ""
    assert "1/3/5 天" not in doc, (
        "docstring 還寫著「工作日 1/3/5 天時」——\n"
        "⇒ 階梯改成 1/3/5/10/15… 之後那句話是錯的，"
        "而下一個人會照它做決定。"
    )
