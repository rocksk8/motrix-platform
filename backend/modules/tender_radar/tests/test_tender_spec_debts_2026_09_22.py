"""（自 tests/test_spec_debts_2026_09_22.py 拆出，2026-09-25）規格欠帳 E3／N7b：M11 標案雷達的兩條。

原檔其餘（U5c／U8／U9／U10／U11）是 DB migration，留在 tests/。
"""
import pytest

from modules.tender_radar import source as ts

# ══════════════════════════════════════════════════════════════════════
# E3 · radar_on() 的環境變數
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("value,expected", [
    (None,    False),   # 沒設
    ("1",     True),    # 唯一會開的值
    ("0",     False),   # ⚠️ 非空字串，用真假值判會變成開著
    ("true",  False),   # 同上
    ("True",  False),
    ("yes",   False),
    ("",      False),
])
def test_e3_the_radar_env_var_is_compared_to_the_string_one(
        monkeypatch, value, expected):
    """🟢 E3：`radar_on()` 的判準是 `== "1"`，**不是真假值**。

    ☠️ `"0"` 與 `"true"` 都是**非空字串** ⇒ 用 `if os.getenv(...)` 判的話
    兩個都會把雷達打開，而使用者寫 `MOTRIX_TENDER_RADAR=0` 的意思**明明是關**。
    🔑 那是〈null 不等於 0〉的同一族：**「有值」與「值代表開」是兩件事。**

    ↩︎ 什麼改動會讓它紅：把 `os.getenv("MOTRIX_TENDER_RADAR") == "1"`
       改成 `bool(os.getenv("MOTRIX_TENDER_RADAR"))` 或 `!= "0"`。

    ⚠️ 同時釘住 `TENDER_RADAR_ENABLED` 這個模組全域是 `or` 的另一邊
    （見下一題）—— 這裡先把它固定成 `False`，否則量到的是它而不是環境變數。
    """
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", False)
    if value is None:
        monkeypatch.delenv("MOTRIX_TENDER_RADAR", raising=False)
    else:
        monkeypatch.setenv("MOTRIX_TENDER_RADAR", value)
    assert ts.radar_on() is expected, (
        f"`MOTRIX_TENDER_RADAR={value!r}` ⇒ `radar_on()` 應該是 {expected}"
    )


def test_e3b_the_module_switch_still_wins_when_the_env_var_is_absent(
        monkeypatch):
    """🟢 E3b 反向控制：**環境變數沒設時，模組全域仍然是有效的開關。**

    ⚠️ 少了這一題，一個「**只看環境變數**」的實作會讓 E3 全綠 ——
    而既有的 18 處 `monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)`
    會全部失效，**那是十八題安靜地不再測到它們以為在測的東西**。

    ↩︎ 什麼改動會讓它紅：把 `TENDER_RADAR_ENABLED or os.getenv(...)`
       改成只剩 `os.getenv(...)`。
    """
    monkeypatch.delenv("MOTRIX_TENDER_RADAR", raising=False)
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    assert ts.radar_on() is True, "模組全域開著、環境變數沒設 ⇒ 應該是開的"


# ══════════════════════════════════════════════════════════════════════
# N7b · 靜默期擋的是「找到標案」，不是「純記錄期開始的公告」
# ══════════════════════════════════════════════════════════════════════

def test_n7b_the_quiet_period_does_not_swallow_its_own_announcement():
    """🟢 N7b：**第 0 天（首次成功掃描當天）不算靜默期。**

    ☠️ 天真實作是 `if 在靜默期: return` ⇒ **第 1 天那封公告被自己擋掉**，
    而 N14（「公告要說接下來 7 天不寄信」）就沒有載體了。
    🔑 而那個紅燈會指錯地方：**N7 會是綠的**（確實 0 封），只有 N14 紅
    ⇒ 看起來像「公告漏寫了」，實際是「**那封信根本不存在**」。

    📌 現行實作用 `0 < days <= QUIET_PERIOD_DAYS` 把第 0 天讓出來，
    而呼叫端是 `quiet = _in_quiet_period()` **先判斷、再**
    `_remember_first_scan()` —— 顛倒的話，首次掃描會把起算點設成今天，
    然後立刻掉進自己剛設的靜默期。

    ↩︎ 什麼改動會讓它紅：`0 < days` 改成 `0 <= days`（或 `days >= 0`）。
    """
    assert ts._in_quiet_period.__module__, "前提：這支函式存在"
    for days, quiet in ((None, False), (0, False), (1, True),
                        (7, True), (8, False), (99, False)):
        got = _quiet_with_days(days)
        assert got is quiet, (
            f"距首次掃描 {days} 天 ⇒ 靜默期應該是 {quiet}，實際 {got}\n"
            "⇒ 第 0 天是公告那一封的日子，**不可以被自己的靜默期擋掉**；"
            "第 8 天要恢復。"
        )


def _quiet_with_days(days):
    """把 `_days_since_first_scan` 換掉，直接問 `_in_quiet_period` 的判斷。

    ⚠️ 換的是**天數來源**，不是 `_in_quiet_period` 本身 ——
    換後者的話就變成在驗我自己設的值。
    """
    saved = ts._days_since_first_scan
    try:
        ts._days_since_first_scan = lambda: days
        return ts._in_quiet_period()
    finally:
        ts._days_since_first_scan = saved


def test_n7b_b_the_order_of_check_and_record_is_pinned():
    """🟢 N7b-b：**先判斷靜默期，再記錄首次掃描時間。**

    ⚠️ 上一題只驗了「第 0 天不算靜默期」，**驗不到順序** ——
    而順序顛倒時，第 0 天的 `days` 會從 `None` 變成 `0`，
    看起來仍然「不是靜默期」…… 直到有人把第 0 天也算進去為止。
    🔑 兩個獨立的錯，各自單獨都還能活；**合起來那封信就不見了**。

    📌 觀測點是**原始碼的順序**，這是我今天唯一一次用文字比對 ——
    ⚠️ 而文字比對答的是「有沒有被寫出來」不是「有沒有被執行」。
    這一題的價值只在「有人搬動它時會留下痕跡」，我不宣稱它更強。

    ↩︎ 什麼改動會讓它紅：把 `_remember_first_scan(...)` 搬到
       `quiet = _in_quiet_period()` 之前。
    """
    import inspect
    src = inspect.getsource(ts)
    check = src.find("quiet = _in_quiet_period()")
    record = src.find("_remember_first_scan(_now_iso())")
    assert check >= 0 and record >= 0, (
        f"找不到那兩行（check={check}, record={record}）—— 有人改名了？"
    )
    assert check < record, (
        "`_remember_first_scan()` 跑在 `_in_quiet_period()` 之前。\n"
        "⇒ 首次成功掃描會把起算點設成今天，然後立刻掉進自己剛設的靜默期，"
        "而「首次啟用」那一封永遠寄不出去。"
    )
