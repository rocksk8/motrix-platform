# -*- coding: utf-8 -*-
"""`vouchers` VIEW 改造的**持續守門**（A 派工 `97eda85`，(a) 已撤 => 剩 (e)(c)）。

A 裁定（`fa35113`）：
```
實表   vouchers_all
VIEW   vouchers  AS SELECT * FROM vouchers_all WHERE voided_at = ''
```

---

# ☠️ 這一檔存在的理由：**驗收不是守門**

A 的五項驗收原本只寫在訊息與 `STATE.md` 散文裡：
```
B 交一次輸出  =>  而**交完就沒有東西再看它們**
=> 日後任何一次回歸把 VIEW 弄壞，**不會有任何一題紅**
```
🔑 〈要求寫在訊息裡等於沒下達〉＋〈散文對工具是隱形的〉**同時成立**。

# 🔴 而 `(e)` 擋的是 A 實跑出來的一個**靜默失敗**

```
sqlite 3.53.1，`vouchers` 已經是 VIEW 時：
  CREATE TABLE IF NOT EXISTS vouchers(...)      -> **OK，不報錯**
  之後 sqlite_master name='vouchers'           -> **['view']**
  ⇒ **表沒有被建，零訊息**
另外四種寫法（無 IF NOT EXISTS ／ DROP TABLE ／ 反向建 VIEW）**都會報錯**
```
🔑 **五種裡只有一種是靜默的，而它正好是 `init_db()` 全檔在用的那一種。**
☠️ ⇒ 有人日後加一支 migration 建 `vouchers` 表，會拿到一個成功的回傳、
   一個沒有被建立的表，**而 VIEW 還在那裡** —— 直到有人發現作廢單不見了。

---

# ⚠️ 而「只釘不變量」那一題**不能代替這一檔**

```
test_voucher_voided_filter_…  VIEW 落地那天自動變綠 ✅
⚠️ 而它**分辨不出**「VIEW 做對了」與「helper 寫對了」—— 那是它該有的性質
🔴 ⇒ **那一題變綠 ≠ VIEW 做對了**
```
📌 而「有人記得」不是落點（〈計數器要有落點〉）⇒ 這三題就是那個落點。

# 🔴 而 `(a)`（備份要含 `vouchers_all`）我寫了，**又整段刪掉** —— 它是第二份實作

```
既有 test_system_audit_2026_09_14.py:124
  test_every_table_is_either_backed_up_or_explicitly_excluded
  列舉 SELECT name FROM sqlite_master WHERE **type='table'**
  => vouchers（VIEW）不會被列 ✅ ／ vouchers_all（實表）會被列 => **必須做決定** ✅
  ⚙️ 而它已經有反向控制（test_backup_list_has_no_stale_entries）
既有 :154 test_every_backup_query_actually_runs
  => **直接把每條 SQL 拿去執行**，我那第二題一模一樣而且比它弱（我只跑含 voucher 的）
```
☠️ 而我當時還沒查就先寫了 —— 而我的探針又找錯地方（我找一個叫 `BACKUP_TABLES`
   的常數，它不存在）⇒ **我的題會對著一段寫對的碼報「備份沒有含它」**。
🔑 ⇒ 判準（A `82623c2`）：**要新增一道守門之前，先問「既有的哪一道已經在守同一件事」**，
   而找法不是憑印象，是**去讀那道守門的列舉條件**（這次的關鍵是 `type='table'` 五個字）。

📌 `(b)` demo 笛卡兒積分類同樣由既有守門涵蓋；
   `(d)` 回滾快照可還原 **A 明著說不要出題**（一次性驗收，要動快照與還原流程）。
"""
import sqlite3

import pytest

import db

VIEW = "vouchers"
REAL = "vouchers_all"


@pytest.fixture(scope="module")
def fresh_db(tmp_path_factory):
    """跑完**全部** migration 的一份新資料庫 —— `(c)` 的 migration 重播就是它。

    ⚠️ 用 `db.init_db()` 不自己建表：要驗的正是「那些 migration 一路跑下來的結果」。
    """
    path = tmp_path_factory.mktemp("vview") / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _kinds(conn):
    return {r[0]: r[1] for r in conn.execute(
        "SELECT name, type FROM sqlite_master WHERE name IN (?,?)",
        (VIEW, REAL))}


# ══════════════════════════════════════════════════════════════════════
# (e) sqlite_master：誰是 view、誰是 table
# ══════════════════════════════════════════════════════════════════════

def test_e_vouchers_is_a_view_and_vouchers_all_is_a_table(fresh_db):
    """🔴🔴 `(e)` **`vouchers` 必須是 view，`vouchers_all` 必須是 table。**

    ☠️ 反過來（`vouchers` 變回實表）的症狀**不是錯誤**：
    ```
    所有查詢照跑 => 而它們**開始撈到作廢單** => 金額多算
    ```
    🔑 而它會這樣發生：有人加一支 migration 寫
       `CREATE TABLE IF NOT EXISTS vouchers(...)` —— **那句話不報錯，而表沒被建**。
       （A 實跑過五種寫法，**只有這一種是靜默的**，而它是 `init_db()` 全檔的慣例。）
    📌 ⇒ 這一題釘的是 `sqlite_master.type`，不是「查得到查不到」——
       **兩者都對的時候只有 `type` 分得出誰是誰。**
    """
    kinds = _kinds(fresh_db)
    assert kinds.get(REAL) == "table", (
        "`%s` 在 `sqlite_master` 裡是 %r（預期 `table`）。現況：%r\n"
        % (REAL, kinds.get(REAL), kinds)
        + "☠️ 實表不見了 ⇒ **作廢單查不到** ⇒ 稽核看不到「這一張作廢過」，\n"
          "   而使用者裁的是**作廢重開：原單留著**。")
    assert kinds.get(VIEW) == "view", (
        "`%s` 在 `sqlite_master` 裡是 %r（預期 `view`）。現況：%r\n"
        % (VIEW, kinds.get(VIEW), kinds)
        + "☠️ 它變回實表 ⇒ 所有查詢照跑，**而它們開始撈到作廢單** ⇒ 金額多算。\n"
        + "🔑 最可能的成因是一句**不會報錯**的 "
          "`CREATE TABLE IF NOT EXISTS vouchers(...)`。")


def test_e_the_silent_failure_really_is_silent():
    """⚙️ **儀器自檢：證明 `(e)` 防的那個靜默失敗是真的。**

    ☠️ 少了它，上一題的理由建立在**一段我沒有跑過的描述**上 ——
       而我今晚已經有兩次從「這個機制看起來很脆」推出一個不存在的失敗故事。
    🔑 ⇒ 那個靜默要**跑出來**，不是引用出來。
    ⚙️ 而對照組是「會報錯的那一種」：少了它，這一題證明的只是
       「SQLite 有時候不報錯」，**而不是「這一種寫法特別危險」**。
    """
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE %s (id INTEGER PRIMARY KEY, voided_at TEXT)" % REAL)
    c.execute("CREATE VIEW %s AS SELECT * FROM %s WHERE voided_at = ''"
              % (VIEW, REAL))

    # ☠️ 靜默的那一種
    c.execute("CREATE TABLE IF NOT EXISTS %s (id INTEGER PRIMARY KEY)" % VIEW)
    got = c.execute(
        "SELECT type FROM sqlite_master WHERE name=?", (VIEW,)).fetchone()[0]
    assert got == "view", (
        "`CREATE TABLE IF NOT EXISTS %s` 之後它變成 %r ——\n" % (VIEW, got)
        + "🔑 那表示這一版 SQLite（%s）**不再靜默** ⇒ `(e)` 的理由要重寫，"
          "而那是好消息。" % sqlite3.sqlite_version)

    # ⚙️ 對照組：不帶 IF NOT EXISTS 就會報錯
    with pytest.raises(sqlite3.Error):
        c.execute("CREATE TABLE %s (id INTEGER PRIMARY KEY)" % VIEW)
    c.close()


def test_e_the_view_actually_filters_voided_rows(fresh_db):
    """⚙️ `(e)` 的補強：**`vouchers` 是 view 還不夠，它要真的過濾。**

    ☠️ `CREATE VIEW vouchers AS SELECT * FROM vouchers_all`（**漏掉 WHERE**）
       在 `sqlite_master` 裡一樣是 `view` ⇒ 上面那題照樣綠。
    🔑 〈守門守的對象被搬走〉：型別對了，而決定行為的是 `WHERE`。
    """
    if _kinds(fresh_db).get(VIEW) != "view":
        pytest.skip("`vouchers` 還不是 view —— 見上一題。")
    sql = fresh_db.execute(
        "SELECT sql FROM sqlite_master WHERE name=?", (VIEW,)).fetchone()[0]
    assert "voided_at" in (sql or ""), (
        "VIEW 的定義裡沒有 `voided_at`：\n  %s\n" % sql
        + "☠️ 它是 view 而**沒有過濾** ⇒ 型別對了，"
          "而所有查詢照樣撈得到作廢單。")


# ══════════════════════════════════════════════════════════════════════
# (c) migration 重播
# ══════════════════════════════════════════════════════════════════════

def test_c_a_full_migration_replay_builds_the_view(fresh_db):
    """🔴 `(c)` **全新 db 跑滿全部 migration 之後，VIEW 建得起來而且查得動。**

    ☠️ 這一題防的是〈凍住的歷史不要呼叫活的程式碼〉那一族的鄰居：
    ```
    改既有的 v95（就地改）  => 已升級的機器**不會再跑一次它**
                             => 開發機對、而**全新安裝與災難還原走的是另一條路**
    ```
    🔑 ⇒ 「我這台是對的」證明不了這件事，**要一份從零跑起來的 db**。
    ⚙️ 而這一題不只看它存在，**它要查得動** —— 一個引用了不存在欄位的 VIEW
       在 `sqlite_master` 裡看起來完全正常，**直到有人 SELECT 它**。
    """
    kinds = _kinds(fresh_db)
    assert kinds.get(VIEW) == "view" and kinds.get(REAL) == "table", (
        "全新 db 跑完全部 migration 之後：%r\n" % kinds
        + "⚠️ 預期 `%s`=table、`%s`=view。" % (REAL, VIEW))
    try:
        fresh_db.execute("SELECT COUNT(*) FROM %s" % VIEW).fetchone()
    except sqlite3.Error as e:
        pytest.fail(
            "VIEW 存在而**查不動**：%s\n" % e
            + "☠️ 一個引用了不存在欄位的 VIEW 在 `sqlite_master` 裡看起來完全正常 ——\n"
              "   **直到有人 SELECT 它**，而那會是使用者。")
