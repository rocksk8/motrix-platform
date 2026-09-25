"""規格欠帳八條：E3／N7b／U5c／U8／U9／U10／U11。

（2026-09-25：E3、N7b 屬 M11 標案雷達，已搬到 modules/tender_radar/tests/test_tender_spec_debts_2026_09_22.py）

A 2026-09-22 分流出來的、**規格宣告了而從來沒有人寫**的八條
（我逐條查過沒有現成測試 —— A 原本懷疑 U8/U9 已經在
`test_upgrade_path_2026_09_21.py` 裡，**沒有**）。

## ⚠️ 其中幾條是「綠著到貨」的，那不是假綠燈

既有行為本來就對 ⇒ 這些題是**回歸守門**，不是紅→綠的交付。
📌 而 A 給了判準，我照它逐題寫：
> **綠著到貨的那幾條，要能說出「什麼改動會讓它紅」** ——
> 說得出來就是回歸守門，說不出來就是**防著不存在的問題**。

⇒ 每一支綠著到貨的題，docstring 裡都有一行 **`↩︎ 什麼改動會讓它紅`**。

## 🔴 而 U8 與現行實作是牴觸的，我把它寫成紅的並說明唯一安全的修法

`db.py:597` 的 `_get_version` **刻意**移除了 `try/except: return 0`，
整段論證寫在那支的 docstring 裡：
> 「讀不到就要拒絕，不要猜一個看起來最無害的值：
> `0` 看起來無害，是因為它在唯一到不了的那個情境裡才是對的。」

而 U8 要的是「表不存在 → 回 0」。**實測：現在丟 `OperationalError`。**

☠️ 若用 `try/except sqlite3.OperationalError: return 0` 來滿足 U8，
**同一個 except 會把「資料庫鎖住／檔案損毀」也吞成 0** ⇒ 直接違反 U9，
而 `0` 的意思是「**當成全新資料庫，從第 1 支 migration 從頭跑一遍**」。

🔑 **唯一同時滿足 U8 與 U9 的寫法是「先正面確認表在不在」**
（查 `sqlite_master`），不是用例外去分辨。
⇒ U8b 就是釘這件事的反向控制。

📌 順帶：`db.py:597` 的註解已經寫著「守門見
`test_upgrade_path_2026_09_21.py::test_u5c`」—— **那支測試不存在。**
跟 SL17／SL18 同一個形狀：**一句「已經有人在守」的話，本身不是守門。**
"""
import sqlite3
import sys
from pathlib import Path

import pytest

import db

#: 🔑 **借用 `test_upgrade_path` 的建庫工具，不自己複製一份。**
#: 那支 harness 有 `test_u0` 當量尺（證明它真的產出 v84 的庫）。
#: ⚠️ 複製一份的話，兩份會各自演化，**而 U0 只覆蓋得到它自己那一份**
#: ⇒ 我這邊會在一個沒有人驗過的建庫程序上做結論。
#: ⚠️ 明確把 `tests/` 放進 `sys.path`：pytest 的自動插入發生在**收集**那一刻，
#: 而 `from ... import` 發生在**模組匯入**那一刻 —— 單獨跑這一個檔時順序不保證。
#: 📌 實測過：不加這兩行，`pytest tests/test_spec_debts_2026_09_22.py`
#: 會 `ModuleNotFoundError`，而整個 `tests/` 一起跑時不會。
#: 🔑 **「整批跑得起來」不等於「單獨跑得起來」**，而單獨跑正是除錯時的跑法。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_upgrade_path_2026_09_21 import _build_at_version  # noqa: E402


# ══════════════════════════════════════════════════════════════════════
# U5c · _MIGRATIONS 裡不可以有破壞性的 DDL
# ══════════════════════════════════════════════════════════════════════

def test_u5c_no_migration_makes_a_column_disappear(tmp_path):
    """🔴 U5c：**跑完任何一支 migration 之後，不可以有欄位或表消失。**

    ## 為什麼這一條存在（理由要寫在題目裡，不要只寫在規格裡）

    `_run_migrations` 在「資料庫版本比程式碼新」時**只記 WARNING、不丟例外**
    （A 裁定：丟例外會讓回退**直接起不來**，把「新版有一個 bug」
    變成「什麼都跑不起來」）。

    🔑 **而那個裁決有一個前提**：目前每一支 migration 都**只加不改**
    ⇒ 舊程式碼讀不到的新欄位，它就是不讀，不會壞。
    ⚠️ **那是 migration 的性質，不是這個引擎的性質。**
    哪天有人寫了 `DROP COLUMN`，回退之後舊程式碼會讀一個**已經不存在**的欄位
    ⇒ 那時「只記 log」就從保守變成危險，**而沒有人會回來重新裁決。**

    📌 `db.py:597` 的註解已經寫著「守門見 `test_u5c`」——
    **而這支測試到今天才存在。** 一句「已經有人在守」的話，本身不是守門。

    ## 🔴 我第一版用文字比對，而它同時誤報又漏報

    第一版掃 `DROP COLUMN`／`DROP TABLE`／`RENAME TO` 的字面，結果四紅：

    | | 真相 |
    |---|---|
    | v62 `_m062_case_project_merge` | ⚠️ **誤報**：`DROP TABLE` 只出現在**註解**裡（「刻意不 DROP TABLE」） |
    | v14／v35／v37 | SQLite 的**標準重建表慣用法**（建新表→複製→丟舊表→改名），因為 SQLite 不能 `ALTER TABLE ADD CONSTRAINT` |

    🔑 〈診斷的層級決定覆蓋率〉：**文字比對答的是「有沒有被提到」，不是「有沒有發生」。**
    而它漏報的那一側更重要：一支用 `CREATE TABLE new (少一欄)` ＋ 複製 ＋ 改名
    **弄掉一個欄位**的 migration，字面上一個關鍵字都不會命中。

    ⇒ 判準換成**行為**：從 v0 逐支跑上來，比對每一支前後的 schema，
    **只要有 (表, 欄位) 消失就紅**。重建表只要欄位沒少，它就不破壞回退。
    📌 這樣掃得到全部 89 支，而且是一次 O(n) 的遞增跑法，不是 O(n²)。
    """
    path = tmp_path / "walk.db"
    _build_at_version(path, 0)

    conn = db._connect(str(path))
    losses = []
    try:
        before = _schema_snapshot(conn)
        assert before, "v0 的 schema 是空的 —— 建庫工具沒跑起來，前提不成立"
        for i, fn in enumerate(db._MIGRATIONS, start=1):
            fn(conn)
            after = _schema_snapshot(conn)
            gone = {x for x in before - after if x[0] in ("table", "column")}
            if gone:
                losses.append((i, fn.__name__, sorted(gone)))
            before = after
    finally:
        conn.close()

    assert not losses, (
        "這些 migration 讓欄位或表消失了：\n  "
        + "\n  ".join(f"v{i} {name}：{items}" for i, name, items in losses)
        + "\n\n⇒ 它們讓「資料庫版本比程式碼新時只記 log 不擋路」這個裁決失效："
        "回退之後，舊程式碼會讀到一個已經不存在的欄位。\n"
        "⚠️ 要嘛換寫法（重建表時把欄位補齊），要嘛請 A 重新裁決 "
        "`_run_migrations` 在「版本比程式碼新」時的行為。"
    )


def test_u5c_b_the_walk_really_visits_every_migration(tmp_path):
    """🔴 U5c-b 量尺：**先證明那一趟真的走過每一支，而且看得到變化。**

    ⚠️ 少了這一題，上一題在「建庫工具壞掉」「`_MIGRATIONS` 變成空的」
    「`_schema_snapshot` 回空集合」時都會**安靜地全綠** ——
    而那正是今天反覆出現的空集合假綠燈。

    🔑 這裡驗的是**有東西被加出來**：89 支跑完之後，
    schema 必須比 v0 大很多。**沒有增長就表示那一趟其實什麼都沒跑。**
    """
    path = tmp_path / "walk-yardstick.db"
    _build_at_version(path, 0)
    conn = db._connect(str(path))
    try:
        start = _schema_snapshot(conn)
        touched = 0
        for fn in db._MIGRATIONS:
            snap = _schema_snapshot(conn)
            fn(conn)
            if _schema_snapshot(conn) != snap:
                touched += 1
        end = _schema_snapshot(conn)
    finally:
        conn.close()

    assert len(db._MIGRATIONS) >= 80, (
        f"`_MIGRATIONS` 只有 {len(db._MIGRATIONS)} 支 —— 前提不成立"
    )
    assert len(end) > len(start) + 50, (
        f"跑完 {len(db._MIGRATIONS)} 支之後，schema 從 {len(start)} 項"
        f"變成 {len(end)} 項 —— 增長太少，那一趟大概沒有真的在跑。"
    )
    assert touched >= 20, (
        f"{len(db._MIGRATIONS)} 支裡只有 {touched} 支真的改變了 schema。\n"
        "⇒ 上一題的比對對其餘那些來說是空轉的。"
    )


# ══════════════════════════════════════════════════════════════════════
# U8 / U9 · _get_version 讀不到版本時怎麼辦
# ══════════════════════════════════════════════════════════════════════

def test_u8_a_database_without_the_version_table_is_version_zero(tmp_path):
    """🔴 U8：`schema_version` 表**不存在** → 回 `0`（全新資料庫，正確）。

    **實測現況：丟 `sqlite3.OperationalError: no such table`。**

    ⚠️ 這一條與 `db.py:597` 的 docstring 是牴觸的，而那支的論證是
    「那個情境到不了」（`init_db()` 在第 217 行就建了表，
    `_run_migrations()` 第 522 行才跑）。**論證本身是對的**，
    只是 `_get_version` 現在也被別人直接呼叫（測試、工具腳本）。

    🔴 **唯一安全的修法是先正面確認表在不在**（查 `sqlite_master`），
    **不是** `try/except sqlite3.OperationalError: return 0` ——
    後者會把「鎖住／損毀」也吞成 0（見 U9 與 U8b）。
    """
    path = tmp_path / "no-version-table.db"
    conn = db._connect(str(path))
    try:
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        conn.commit()
        assert not _has_table(conn, "schema_version"), "前提：這個庫沒有那張表"
        assert db._get_version(conn) == 0, (
            "`schema_version` 不存在時應該回 0（全新資料庫）"
        )
    finally:
        conn.close()


def test_u8b_the_zero_must_not_come_from_swallowing_errors(tmp_path):
    """🔴🔴 U8b：**表存在時，讀取失敗不可以被吞成 0。**

    ☠️ 這一題是 U8 的護欄。最省事的 U8 修法是
    `try: ... except sqlite3.OperationalError: return 0`，
    而**同一個 except 會吞掉**「database is locked」「file is not a database」
    「型別錯」—— 那些的正確反應是**拒絕**。

    而 `0` 的意思是「當成全新資料庫，**從第 1 支 migration 從頭跑一遍**」
    ⇒ 在一個其實有資料、只是當下讀不到的庫上做這件事，**比直接崩潰危險得多**。
    🔑 〈讀不到的欄位要拒絕那一筆，不要送空值〉的同一件事，放大到整個資料庫。

    📌 這裡用「表在、但欄位名不是 `version`」製造一個讀取失敗 ——
    那正是 `OperationalError` 的另一種來源，**而它絕對不是「全新資料庫」**。
    """
    path = tmp_path / "corrupt-version-table.db"
    conn = db._connect(str(path))
    try:
        conn.execute("CREATE TABLE schema_version (id INTEGER PRIMARY KEY, "
                     "ver INTEGER)")
        conn.execute("INSERT INTO schema_version (id, ver) VALUES (1, 84)")
        conn.commit()
        assert _has_table(conn, "schema_version"), "前提：表在"
        with pytest.raises(sqlite3.Error):
            db._get_version(conn)
    finally:
        conn.close()


def test_u9_a_locked_or_broken_database_raises_instead_of_reporting_zero(
        tmp_path):
    """🟢 U9：表存在但**讀取失敗** → 拋出，**不可以回 0**。

    🔑 U8 與 U9 是一對，而 **U9 才是那一對的重點**：
    只寫 U8 的話，一個「永遠回 0」的實作會綠。

    📌 這裡用「檔案根本不是資料庫」製造失敗 ——
    `file is not a database` 是 `DatabaseError`，
    而**它跟「全新資料庫」在 except 裡長得一模一樣**。

    ↩︎ 什麼改動會讓它紅：在 `_get_version` 外面補回
       `try/except Exception: return 0`。
    """
    path = tmp_path / "not-a-database.db"
    path.write_bytes("這不是一個 SQLite 檔案，只是一些位元組。".encode() * 40)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        with pytest.raises(sqlite3.DatabaseError):
            db._get_version(conn)
    finally:
        conn.close()


def _has_table(conn, name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone()
    return row is not None


# ══════════════════════════════════════════════════════════════════════
# U10 · 每一支 migration 都要可重複執行
# ══════════════════════════════════════════════════════════════════════

def test_u10_every_migration_can_be_run_twice(tmp_path):
    """🟢 U10：**`_MIGRATIONS` 的每一支連跑兩次，結果相同。**

    ⚠️ **這不等於現有的 `test_u1b`。** 那一題跑的是「整組再跑一次」，
    而第二次跑的時候 `current >= CURRENT_VERSION` ⇒ **它一支都不會再執行**
    🔑 所以 `test_u1b` 證明的是「引擎會跳過」，**不是「每一支自己可重跑」**。
    而 `db.py:668` 的註解寫著「Each function must be idempotent」——
    **那句話到今天為止沒有任何東西在守。**

    📌 做法：建到 v(i-1) 的庫 → 跑第 i 支 → **再跑一次第 i 支**
    → 比對 schema 快照相同、而且第二次不丟例外。

    ↩︎ 什麼改動會讓它紅：任何一支改成無條件 `ALTER TABLE ... ADD COLUMN`
       或 `CREATE TABLE`（少了 `IF NOT EXISTS` / `_col_exists` 檢查）。

    ⚠️ 只抽樣最後 12 支：建庫要跑完前面所有 migration，
    89 支全驗是 O(n²)。**而我把「只驗了尾巴」寫在這裡，不留給別人猜。**
    """
    total = len(db._MIGRATIONS)
    checked = 0
    for i in range(max(1, total - 11), total + 1):
        path = tmp_path / f"v{i}.db"
        _build_at_version(path, i - 1)
        conn = db._connect(str(path))
        try:
            fn = db._MIGRATIONS[i - 1]
            fn(conn)
            before = _schema_snapshot(conn)
            fn(conn)                      # ← 第二次
            after = _schema_snapshot(conn)
        finally:
            conn.close()
        assert before == after, (
            f"v{i} `{fn.__name__}` 跑第二次改變了 schema。\n"
            f"只有第一次有的：{sorted(before - after)}\n"
            f"只有第二次有的：{sorted(after - before)}"
        )
        checked += 1
    assert checked >= 10, f"只驗到 {checked} 支 —— 抽樣範圍算錯了"


def _schema_snapshot(conn):
    """表名＋欄位名的集合。**索引與觸發器也算在內。**"""
    items = set()
    for row in conn.execute(
            "SELECT type, name, tbl_name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%'"):
        items.add((row["type"], row["name"], row["tbl_name"]))
        if row["type"] == "table":
            for col in conn.execute("PRAGMA table_info(%s)" % row["name"]):
                items.add(("column", row["name"], col["name"]))
    return items


# ══════════════════════════════════════════════════════════════════════
# U11 · _run_migrations 要用 db._connect() 取得的連線
# ══════════════════════════════════════════════════════════════════════

def test_u11_a_plain_sqlite_connection_does_not_work(tmp_path):
    """🟢 U11：`_run_migrations` 要吃 **`db._connect()`** 給的連線。

    📌 規格把它寫成一條給測試作者的**慣例**。這一題把它變成一件
    **可觀測的事**：裸的 `sqlite3.connect()` 會壞，而且壞得很早。

    原因是 `_connect()` 設了 `row_factory = sqlite3.Row`，
    而 `_get_version` 讀的是 `row["version"]`
    ⇒ 裸連線回 tuple ⇒ `TypeError`。
    🔑 **這一題的價值是把「請照慣例」變成「不照就會壞」** ——
    一條只寫在文件裡的慣例，跟沒有是一樣的。

    ↩︎ 什麼改動會讓它紅：`_get_version` 改成 `row[0]`
       （那會讓裸連線也能用，而慣例就失去強制力了）。
    """
    path = tmp_path / "plain.db"
    _build_at_version(path, 3)

    plain = sqlite3.connect(str(path))
    try:
        with pytest.raises((TypeError, IndexError)):
            db._get_version(plain)
    finally:
        plain.close()

    proper = db._connect(str(path))
    try:
        assert db._get_version(proper) == 3, (
            "用 `db._connect()` 取得的連線應該讀得出版本 —— 這一題的反向控制"
        )
    finally:
        proper.close()
