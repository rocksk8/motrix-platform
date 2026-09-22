# -*- coding: utf-8 -*-
"""`DM1` · demo 重置撞上 `v93` 的 TRIGGER。

# ✅ 這個時序我**實跑過**，不是讀碼推的

A 給我這一題時明著標「這一段時序我是讀碼推的不是跑出來的」，並要我把它變成觀測。
實跑（把 `db` 的十個 `DEMO_*` 常數全部改指暫存路徑，**不碰真的 demo 資料**）：

```
第 1 次 reset  ✅ 成功    statutory = **547**   ← 表原本不存在，清空無事
                          ⇒ 接著 init_db() 升到 v94，**把 547 筆載進去**
第 2 次 reset  🔴 IntegrityError:
               「法定會計項目不可刪除：這是經濟部公告的《商業會計項目表》…」
```

🔑 **⇒ 只登一次的測試是綠的，而它證明不了任何事。**
⇒ 本檔的主題題**跑兩次**，第二次才是斷言點。

---

# 🔴 成因（`db.py:227-233`）

```python
tables = [... FROM sqlite_master WHERE type='table' ...]   # **動態取得** ⇒ 必然含 account_items
conn.execute("PRAGMA foreign_keys=OFF")                    # ☠️ **對 TRIGGER 無效**
for t in tables:
    conn.execute(f"DELETE FROM {t}")                       # ⇒ TRIGGER ABORT
```
⚠️ A 收回了它上一則的一格，而那個區別要留著：
```
FK      會被 PRAGMA foreign_keys=OFF 關掉
TRIGGER **不會**
```
🔑 那正是 `DM1` 會發生的原因，**也是那道防護在這條路上仍然有效的原因**
—— 同一個事實的兩面，而它們容易被寫在一起。

# ✅ 修法（斷言對象）

```
account_items 排除在 demo 清除清單外
理由不是「繞過 TRIGGER」，是 **547 筆是系統資料，不是使用者資料**
```
📌 那個理由重要：**如果理由是「繞過 TRIGGER」，下一個人會去改 TRIGGER。**
"""
import sqlite3

import pytest

import db

#: B 要引進的兩份清單。名字要改**退回給我**。
_SYSTEM_SEAMS = ("DEMO_SYSTEM_TABLES", "_DEMO_SYSTEM_TABLES",
                 "DEMO_PRESERVED_TABLES")
_USER_SEAMS = ("DEMO_USER_TABLES", "_DEMO_USER_TABLES", "DEMO_CLEARED_TABLES")

#: 一定是**使用者資料**的幾張表 —— 反向控制用。
_MUST_BE_USER = ("quotations", "customers", "users")


@pytest.fixture
def demo_sandbox(tmp_path, monkeypatch):
    """把 `db` 的每一個 `DEMO_*` 常數改指暫存路徑。

    ⚠️ **非做不可**：`reset_demo_db()` 會 `_wipe_dir()` 那幾個 demo 目錄
       ⇒ 不改指的話，跑這一題會**刪掉真的 demo 附件**。
    🔑 〈探針與被測對象糾纏〉的一個具體形狀：**這一題的受測物會刪檔案。**
    """
    for name in dir(db):
        if name.startswith("DEMO_") and isinstance(getattr(db, name), str):
            monkeypatch.setattr(db, name, str(tmp_path / name.lower()))
    monkeypatch.setattr(db, "DEMO_DB_PATH", str(tmp_path / "demo.db"))
    return tmp_path


def _named(seams):
    for n in seams:
        v = getattr(db, n, None)
        if v is not None:
            return n, set(v)
    return None, None


# ══════════════════════════════════════════════════════════════════════
# 🔴 主題 · 連續重置兩次都要成功
# ══════════════════════════════════════════════════════════════════════

def test_dm1_resetting_the_demo_database_twice_still_works(demo_sandbox):
    """🔴🔴 `DM1`：**demo 重置連跑兩次都要成功。**

    ```
    第 1 次  表還不存在 ⇒ 清空無事 ⇒ init_db() 升到 v94 ⇒ **載入 547 筆**
    第 2 次  有 statutory 列 ⇒ TRIGGER ABORT ⇒ **IntegrityError**
             ⇒ auth.py:377 沒有 try/except ⇒ **demo 登入 500**
    ```
    🔑 **只跑一次是綠的** —— 而那個綠證明不了任何事。
    ⇒ 這一題的斷言點是**第二次**。

    ⚙️ 而我跑**三次**不是兩次：
    ```
    兩次  證明「第二次不爆」
    三次  證明它不是「只有第二次特別」——例如某個一次性的旗標
    ```
    📌 成本一樣（都是幾秒），而第三次排除掉一整類「剛好第二次過」的實作。
    """
    db.reset_demo_db()
    conn = db._connect(db.DEMO_DB_PATH)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM account_items WHERE source='statutory'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n > 0, (
        "第一次 reset 之後 `account_items` 裡沒有 statutory 列（%d）——\n" % n
        + "🔑 **儀器失效**：這一題要驗的衝突需要那些列存在才會發生，"
          "而它們不在 ⇒ 下面跑幾次都會綠。")

    for i in (2, 3):
        try:
            db.reset_demo_db()
        except sqlite3.IntegrityError as exc:
            pytest.fail(
                "第 %d 次 demo 重置失敗：%s\n" % (i, exc)
                + "☠️ `reset_demo_db()` 的清除清單是從 `sqlite_master` "
                  "**動態取得**的 ⇒ 它必然包含 `account_items`，\n"
                  "   而那張表上有 `BEFORE DELETE … WHEN OLD.source='statutory'` 的 TRIGGER。\n"
                "⚠️ `PRAGMA foreign_keys=OFF`（`db.py:230`）**對 TRIGGER 無效** ——\n"
                "   FK 會被關掉，**TRIGGER 不會**。\n"
                "🔑 使用者看到的是：**demo 登入 500**（`auth.py:377` 沒有 try/except）。\n"
                "✅ 修法：把 `account_items` 排除在清除清單外 —— "
                "而理由是**547 筆是系統資料不是使用者資料**，\n"
                "   **不是**「繞過 TRIGGER」。"
                "📌 理由寫錯的話，下一個人會去改 TRIGGER。")


def test_dm1_the_statutory_rows_survive_a_reset(demo_sandbox):
    """⚙️ **正對照：重置之後那 547 筆必須還在。**

    ☠️ 少了它，有一種「過得去而錯」的修法會讓上一題全綠：
    ```
    把 TRIGGER 拿掉／改成不擋 demo 庫
    ⇒ reset 不再爆 ⇒ 上一題綠
    ⇒ **而 demo 庫每次重置都會把 547 筆法定項目刪光**
    ```
    🔑 而症狀是：**demo 環境的科目樹是空的**，而沒有任何東西報錯。
    📌 〈守門要配反向控制〉：**「不爆」與「做對了」是兩件事。**
    """
    db.reset_demo_db()
    conn = db._connect(db.DEMO_DB_PATH)
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM account_items WHERE source='statutory'"
        ).fetchone()[0]
    finally:
        conn.close()

    try:
        db.reset_demo_db()
    except sqlite3.IntegrityError:
        pytest.skip("第二次 reset 還在爆 —— 見上一題，這一題等它綠了才有意義。")

    conn = db._connect(db.DEMO_DB_PATH)
    try:
        after = conn.execute(
            "SELECT COUNT(*) FROM account_items WHERE source='statutory'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert after == before > 0, (
        "重置前 %d 筆、重置後 %d 筆 ——\n" % (before, after)
        + "☠️ 法定項目被 demo 重置刪掉了。**那不是「不爆」，那是刪光了。**\n"
          "🔑 demo 環境的科目樹會是空的，而沒有任何東西報錯。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 笛卡兒積 · 每一張表都要被分類，而兩份清單互斥且窮盡
# ══════════════════════════════════════════════════════════════════════

def test_dm1_every_table_is_classified_as_user_or_system_data(demo_sandbox):
    """🔴 **`sqlite_master` 的每一張表，必須落在「使用者資料」或「系統資料」其中一邊。**

    A-2 原本提的是「新增系統資料表沒登記 ⇒ 紅」。
    ☠️ **而那道守門可以靠「把每一張表都放進排除清單」變綠** ——
       ⇒ demo 從此不再清空任何東西，**而它全綠**。
    ⇒ A 改成笛卡兒積（`§54c` 同形狀）：**兩份清單互斥且窮盡。**
    ```
    少一張  ⇒ 紅（新表沒有人分類）
    多一張  ⇒ 紅（清單裡有不存在的表 ⇒ 它爛掉了）
    兩邊都有 ⇒ 紅
    ```

    ⚙️ 而**窮盡**擋不住「全部歸進系統資料」⇒ 下一題是那個反向控制。
    """
    name_sys, sys_tables = _named(_SYSTEM_SEAMS)
    name_usr, usr_tables = _named(_USER_SEAMS)
    assert sys_tables is not None and usr_tables is not None, (
        "`db` 缺少那兩份清單（找過：%s ／ %s）——\n"
        % (list(_SYSTEM_SEAMS), list(_USER_SEAMS))
        + "🔑 現在的清除清單是從 `sqlite_master` **動態取得**的 ⇒ "
          "**沒有任何地方記錄過『哪些表是系統資料』**。\n"
        "⚠️ 名字可以換（**退回給我**），而那兩份清單必須存在且可以被數。")

    db.reset_demo_db()
    conn = db._connect(db.DEMO_DB_PATH)
    try:
        actual = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")}
    finally:
        conn.close()
    assert actual, "一張表都沒抓到 —— **儀器失效**。"

    both = sorted(sys_tables & usr_tables)
    assert not both, (
        "這些表在兩份清單裡都有：%s\n" % both
        + "☠️ 那表示沒有人真的決定過它屬於哪一邊。")

    unclassified = sorted(actual - sys_tables - usr_tables)
    assert not unclassified, (
        "這些表沒有被分類：%s\n" % unclassified
        + "☠️ 新增一張系統資料表而忘了登記 ⇒ demo 重置會把它清空，\n"
          "   而症狀是**那個功能在 demo 裡是空的**，不是報錯。")

    ghosts = sorted((sys_tables | usr_tables) - actual)
    assert not ghosts, (
        "清單裡有資料庫裡不存在的表：%s\n" % ghosts
        + "🔑 清單爛掉了 —— 它會讓「窮盡」這件事變成一句假話。")


def test_dm1_the_classification_cannot_preserve_everything(demo_sandbox):
    """⚙️ **反向控制：不可以把每一張表都歸成「系統資料」。**

    ☠️ 那是上一題最省力的變綠方式，而它的後果是
    **demo 從此不再清空任何東西** —— 使用者上一次試用留下的資料會一直在。
    🔑 〈守門要配反向控制，否則可以靠把東西全寫進排除清單變綠〉。

    ⚙️ 判準不是「使用者清單要有幾張」，是**幾張一定是使用者資料的表必須在裡面**：
    ```
    quotations／customers／users
    ```
    📌 挑這三張的理由：**它們裝的就是使用者自己輸入的東西**，
       任何把它們歸成「系統資料」的分類都是錯的。
    ⚠️ 而它擋不到「把第四張使用者資料表歸錯」—— 那一格靠上一題的窮盡性。
    """
    _n_sys, sys_tables = _named(_SYSTEM_SEAMS)
    name_usr, usr_tables = _named(_USER_SEAMS)
    if usr_tables is None:
        pytest.fail("找不到使用者資料清單 —— 見上一題。")

    assert usr_tables, (
        "使用者資料清單是**空的** ——\n"
        "☠️ 那表示每一張表都被歸成系統資料 ⇒ **demo 重置不再清空任何東西**。")

    missing = sorted(t for t in _MUST_BE_USER if t not in usr_tables)
    assert not missing, (
        "這些表沒有被歸成使用者資料：%s（清單 `%s`）\n" % (missing, name_usr)
        + "☠️ 它們裝的就是使用者自己輸入的東西 —— "
          "歸成系統資料的話，demo 重置之後**上一個人的資料還在**。")

    assert sys_tables and "account_items" in sys_tables, (
        "`account_items` 不在系統資料清單裡 ——\n"
        "🔑 那 547 筆是經濟部公告的《商業會計項目表》，**不是使用者輸入的**。\n"
        "📌 而這是 `DM1` 的修法本身：理由是「它是系統資料」，"
        "**不是「繞過 TRIGGER」**。")
