# -*- coding: utf-8 -*-
"""`AR1` · `archive.backed_up_table_names()` —— **讓沒有人需要知道它內部長什麼樣**。

```
_daily_backup_tables()  回 **{中文檔名: SQL}**
```
☠️ 而那個形狀**本身在誘導人取錯一層**：鍵是人看得懂的中文，
   所以 `"voucher_attachments" in set(listed)` 看起來很自然 —— **而它永遠是 False**。

# 🔴 這不是「有人不小心」，是**同一天三個人踩同一個坑**

```
既有稽核題（test_system_audit_2026_09_14.py:52-54）  從**值**用 FROM (\\w+) 抽  ✅
我 2026-09-23 寫 JV3 的備份題                        取**鍵**                  ☠️
A-2 稍早量 BG1 曝險                                  取**鍵**                  ☠️
  ⇒ 而他是在**讀了我的回報幾分鐘之後**踩的
```
🔑 ⇒ 「提醒」這一層不夠。要的是一個**讓人不必知道內部形狀**的介面。

# ⚠️ 而我原本的防呆**對這個錯誤是盲的**

```
assert len(listed) > 30      <= 我加來防「空清單」的
而 len(dict) 也是 59         <= **前置照樣過**
```
☠️ 它驗的是「**有沒有東西**」，而錯的是「**那些東西是什麼**」——
   **而它失效時看起來是「我有防呆」，比沒有防呆更容易被信任。**
⇒ 前置要作用在**已經解讀過的值**上，不是原始容器上。
"""
import re

import pytest

#: 名字長什麼樣才算「表名」：SQLite 識別字，**不是中文標籤**。
_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

#: 一定在裡面的幾張（隨便挑的老表，用來擋「回空集合」）。
_MUST_HAVE = ("quotations", "customers", "users")


def _archive():
    import archive
    return archive


def test_ar1_the_helper_exists_and_says_what_it_returns():
    """🔴 **`archive.backed_up_table_names()` 要存在。**

    📌 它存在的理由不是「方便」，是**`_daily_backup_tables()` 的形狀會騙人**
       ⇒ 每一個呼叫端都要自己記得「表名在值裡、要用 `FROM (\\w+)` 抽」，
       而**同一天有三個人沒記得**。
    """
    fn = getattr(_archive(), "backed_up_table_names", None)
    assert callable(fn), (
        "`archive.backed_up_table_names()` 還不存在。\n"
        + "📌 `§191`：`_daily_backup_tables()` 回 `{中文檔名: SQL}`，\n"
          "   而表名在**值**裡 ⇒ `in set(...)` 取到的是中文鍵，**永遠是 False**。\n"
        + "🔑 這一支的用途是**讓沒有人需要知道它內部長什麼樣**。")


def test_ar1_it_returns_table_names_not_chinese_labels():
    """🔴🔴 **反向控制：回的必須是表名，不是那個 dict 本身。**

    ```
    回 {中文檔名: SQL}  => set() 之後是「報價單」「客戶」…  ☠️ **這一題要紅**
    回 表名集合          => quotations／customers／…        ✅
    ```
    ⚙️ 判準不是「長度對不對」—— 兩者的長度**一模一樣**（都是 59）。
    🔑 ⇒ 要驗的是**內容的形狀**：SQLite 識別字，不是中文。
    ☠️ 而這正是那個 dict 誘導人犯的錯：**數字全都對，只是東西不對**。
    """
    fn = getattr(_archive(), "backed_up_table_names", None)
    if not callable(fn):
        pytest.fail(
            "`backed_up_table_names()` 還不存在 —— 這一題在等它。\n"
            + "⚠️ 刻意 **fail 不 skip**：skip 的話它會**永久略過**而沒有人發現\n"
              "   （`GC6` 那個形狀）—— 一個從來不跑的驗收條件等於沒有。")

    names = list(fn())
    assert names, "回了空的 —— **尺量不到東西**，下面的斷言不算數。"

    bad = [n for n in names if not _TABLE_NAME.match(str(n))]
    assert not bad, (
        "回傳裡有 %d 個不是表名的東西：%r\n" % (len(bad), bad[:6])
        + "☠️ 那是 `_daily_backup_tables()` 的**鍵**（中文檔名）——\n"
          "   它與表名集合**長度一模一樣**，所以長度斷言擋不到。\n"
        + "🔑 這一支要回的是**表名**。")

    for t in _MUST_HAVE:
        assert t in set(names), (
            "`%s` 不在備份的表清單裡（共 %d 張）——\n" % (t, len(names))
            + "⚠️ 那張表很老，它不在的話多半是**這一支抽錯了**，不是備份漏了。")


def test_ar1_it_agrees_with_the_sql_it_came_from():
    """🔴 **同源：它回的必須與 `_daily_backup_tables()` 的 SQL 對得起來。**

    ⚙️ 兩邊各算一次而漂移的話，**這一支會給出一個看起來很權威的錯答案** ——
       而它存在的目的正是「讓人不必自己抽」⇒ 抽錯了沒有人會發現。
    🔑 ⇒ 這一題釘的是**同源**，不是「兩個數字現在一樣」。
    """
    mod = _archive()
    fn = getattr(mod, "backed_up_table_names", None)
    if not callable(fn):
        pytest.fail(
            "`backed_up_table_names()` 還不存在 —— 這一題在等它。\n"
            + "⚠️ 刻意 **fail 不 skip**（見第二題的說明）。")

    queries = mod._daily_backup_tables()
    from_sql = {t for sql in queries.values()
                for t in re.findall(r"FROM\s+(\w+)", sql)}
    assert len(from_sql) > 30, (
        "從 SQL 只抽到 %d 張表 —— **對照那一側自己壞了**。" % len(from_sql))

    got = set(fn())
    assert got == from_sql, (
        "兩邊對不起來：\n"
        "  只在 `backed_up_table_names()` 裡：%s\n"
        "  只在 SQL 裡：%s\n" % (sorted(got - from_sql), sorted(from_sql - got))
        + "☠️ 這一支存在的目的是「讓人不必自己抽」⇒ **抽錯了沒有人會發現**。")


def test_ar1_every_backed_up_table_really_exists(client):
    """⚙️ **正對照：清單上的每一張表都要真的在資料庫裡。**

    ☠️ 少了它，一個回「一串看起來像表名的字串」的實作也會過上面兩題 ——
       而備份那一支會在跑的時候才炸（`no such table`），**在半夜**。
    ⚠️ 用 `client` fixture ⇒ 量的是**測試那個已經 migrate 過的 DB**，
       不是開發機的（`conftest` 把 `db.DB_PATH` 指到 tmp）。
    """
    mod = _archive()
    fn = getattr(mod, "backed_up_table_names", None)
    if not callable(fn):
        pytest.fail(
            "`backed_up_table_names()` 還不存在 —— 這一題在等它。\n"
            + "⚠️ 刻意 **fail 不 skip**（見第二題的說明）。")

    import db
    conn = db.get_db()
    try:
        real = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    finally:
        conn.close()

    assert len(real) > 50, "資料庫只有 %d 張表 —— **對照那一側壞了**。" % len(real)
    missing = sorted(set(fn()) - real)
    assert not missing, (
        "備份清單上有 %d 張表在資料庫裡不存在：%r\n" % (len(missing), missing)
        + "☠️ 備份會在跑的時候才炸（`no such table`），**而那是在半夜**。")
