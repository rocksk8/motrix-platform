# -*- coding: utf-8 -*-
"""傳票 ⑤ · `account_items` 上的兩支 TRIGGER（被傳票引用的科目不可改 code／不可刪）。

規格：`docs/windows/SPEC-VOUCHER.md §2.5`（施工圖，`5df2f48`）／ migration **v95**。

---

# ✅ A 要我實跑的那一格，我跑了 —— **不是抄他的矩陣**

```
SQLite 3.53.1
裸連線的 PRAGMA foreign_keys 預設值 = 0      <= **預設就是關的**

                              FK=ON              FK=OFF
(1) DELETE 被引用的父列        TRIGGER 擋         **TRIGGER 擋**
(2) UPDATE 被引用的 code       TRIGGER 擋         **TRIGGER 擋**
(3) 未被引用的列改 code        通過               通過        ⚙️ 正對照
(4) 插一筆孤兒子列（純 FK）    FK 擋              **通過**    ⚙️ 開關真的動了
```
🔑 **(4) 才是這張表的重點**：少了它，FK=OFF 可能**根本沒生效**，
   而 (1)(2) 會為了錯的理由綠 —— 那就是〈假綠燈〉。
📌 ⇒ 結論成立：`PRAGMA foreign_keys=OFF` 對 `REFERENCES` 有效、**對 TRIGGER 無效**。

# 🔴 而我量到一件比規格寫的更強的事

```
規格說   db.py:151 的 PRAGMA foreign_keys=ON **包在 try/except: pass 裡**
         db.py:243 的 demo 重置路徑**明著關掉它**
我量到   **裸 sqlite3.connect() 的預設值就是 0**
```
=> 那兩條路不是「兩個例外」——**任何一條沒有走 `db._connect()` 的路，FK 都是關的。**
🔑 => 這兩支 TRIGGER 防的不是兩個特例，是**預設值**。

---

# 🔴 而**弱紅的代價已經兌現了**：`v95` 在我出題前就落地 => 本檔一寫完就全綠

```
出題時預期  紅在 no such table: voucher_lines，B 做完才變綠
實際        **從來沒有紅過** => 我手上沒有證據說這幾題分辨得出對錯
```
⇒ 補跑突變 **14/14**（`scratchpad/mutate_v95_triggers.py`）：拿掉任一支 TRIGGER／
  少 `OF code`／拿掉 `WHEN`／`WHEN` 查錯欄位，**都紅在自己的斷言上**。
☠️ 而突變抓到的是**我自己的**缺陷：兩個正對照擋過頭時丟的是原始 `IntegrityError`，
   我寫的「擋過頭」訊息**永遠不會印** => 排查的人會讀成「測試寫錯了」。已修。
=> 本檔用兩層擋弱紅：
```
(a) 前兩題**完全不碰產品資料庫**（合成 schema）=> 它們現在就該是綠的
    => 它們紅 = **我的前提錯了**，不是 B 沒做
(b) 其餘每一題的第一個斷言各自不同，而 B 落地後我會跑突變逐題確認
```
"""
import sqlite3

import pytest

import db

TABLE = "account_items"
CHILD = "voucher_lines"

#: 施工圖 `§2.5` 逐字的兩支 TRIGGER 名。
#: ⚠️ 名字要換 **退回給我**；而「有兩支、各守一個動作」這件事不可換。
TRIGGERS = (
    "account_items_referenced_code_no_update",
    "account_items_referenced_no_delete",
)


# ══════════════════════════════════════════════════════════════════════
# ⚙️ 獨立正對照 —— 不碰產品碼，**現在就該綠**
# ══════════════════════════════════════════════════════════════════════

_SYN = (
    "CREATE TABLE acct (code TEXT PRIMARY KEY, name TEXT)",
    "CREATE TABLE lines (id INTEGER PRIMARY KEY, account_code TEXT NOT NULL"
    " REFERENCES acct(code))",
    "CREATE TRIGGER syn_no_update BEFORE UPDATE OF code ON acct"
    " WHEN EXISTS (SELECT 1 FROM lines WHERE account_code = OLD.code)"
    " BEGIN SELECT RAISE(ABORT, 'blocked'); END",
)


def _syn_db(fk):
    c = sqlite3.connect(":memory:")
    for s in _SYN:
        c.execute(s)
    c.execute("INSERT INTO acct VALUES ('A','甲')")
    c.execute("INSERT INTO lines VALUES (1,'A')")
    c.commit()
    c.execute("PRAGMA foreign_keys=%s" % fk)
    return c


def test_pragma_fk_off_really_does_not_disable_triggers():
    """⚙️ **這一題現在就該綠。它紅表示我的前提錯了，不是 B 沒做。**

    施工圖 `§2.5` 的理由段建立在一句話上：
    > `PRAGMA foreign_keys=OFF` 關掉的是**外鍵約束**，不是**觸發器**。

    ☠️ 而整個 ⑤ 都靠它 —— 若那句話是錯的，這兩支 TRIGGER 就是多餘的，
       而它們會在日後被**正當地**刪掉。
    🔑 => 那句話要**跑出來**，不是引用出來。
    ⚙️ 而中間那一段（孤兒子列插得進去）是「開關真的動了」的證據：
       少了它，`FK=OFF` 可能根本沒生效，而結論會為了錯的理由成立。
    """
    off = _syn_db("OFF")
    assert off.execute("PRAGMA foreign_keys").fetchone()[0] == 0, (
        "`PRAGMA foreign_keys=OFF` 之後讀回來不是 0 —— **開關沒有動** => "
        "下面的斷言會為了錯的理由綠。")

    off.execute("INSERT INTO lines VALUES (2,'不存在的科目')")
    off.commit()
    assert off.execute("SELECT COUNT(*) FROM lines").fetchone()[0] == 2, (
        "FK=OFF 而孤兒子列插不進去 —— **外鍵仍在強制** => 這一題的對照失效。")

    with pytest.raises(sqlite3.Error) as ei:
        off.execute("UPDATE acct SET code='B' WHERE code='A'")
    assert "blocked" in str(ei.value), (
        "TRIGGER 擋下來了，而訊息是 %r —— 擋它的可能是別的東西。" % str(ei.value))
    off.close()

    on = _syn_db("ON")
    with pytest.raises(sqlite3.Error):
        on.execute("INSERT INTO lines VALUES (2,'不存在的科目')")
    on.close()


def test_a_bare_connection_has_foreign_keys_off_by_default():
    """⚙️ **也該現在就綠**：裸連線的 `PRAGMA foreign_keys` 預設是 `0`。

    📌 施工圖把理由寫成「兩條路會關掉 FK」（`db.py:151` 的 `try/except: pass`、
       `db.py:243` 的 demo 重置）。⚠️ **而實際更強**：
    ```
    任何一條沒有走 db._connect() 的路，FK 本來就是關的
    ```
    🔑 => 這兩支 TRIGGER 防的**不是兩個特例，是預設值** ——
       而那個差別會決定日後有人問「這兩支還需要嗎」時的答案。
    """
    bare = sqlite3.connect(":memory:")
    got = bare.execute("PRAGMA foreign_keys").fetchone()[0]
    bare.close()
    assert got == 0, (
        "裸連線的 `PRAGMA foreign_keys` 是 %r，我量到的是 0。\n" % got
        + "🔑 這一版 SQLite（%s）改了預設值 => **上面那段理由要重寫**，"
          "而那是好消息。" % sqlite3.sqlite_version)


# ══════════════════════════════════════════════════════════════════════
# v95：真資料庫，**而 FK 是關的**
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def fk_off_db(tmp_path):
    """跑完全部 migration 的新資料庫，**而 FK 是關的**。

    ⚠️ 用 `db.init_db()` 不自己建表 —— 要驗的正是「`v95` 做了什麼」。
    🔑 而 FK 刻意關掉：**這一檔要證明的就是「FK 關掉時仍然擋得住」。**
    """
    path = tmp_path / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0, (
        "要求 FK=OFF 而它沒有關 —— **這一檔的前提就不成立**。")
    yield conn
    conn.close()


def _need_v95(conn):
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    missing = {"vouchers", CHILD} - have
    if missing:
        pytest.fail(
            "我在 `sqlite_master` 裡沒有找到 %s。\n" % sorted(missing)
            + "⚠️ 它們**應該**存在 ⇒ 看 `v95`；`v95` 已完成 ⇒ "
              "**那是被刪掉或改名了**。\n"
            + "⚠️ 這是**弱紅** —— 本檔多題會一起紅在這裡，"
              "而它們證明的不是同一件事。\n"
              "=> `v95` 落地後我會跑突變逐題確認它紅在自己的斷言上。")


def _voucher_table(conn):
    """傳票**實表**的名字。

    🔴 `vouchers` 自 2026-09-23 起是**只露出未作廢的 VIEW**，實表叫 `vouchers_all`。
    ☠️ 而我的探針原本 INSERT 進 `vouchers` => VIEW 插不進去
       ⇒ 三題一起紅，**而我的訊息說「v95 還沒有」** —— 它在，只是換了型別。
    🔑 〈探針與被測對象糾纏〉最貴的一種：**紅燈不但指錯對象，還給了一個自信的錯解釋。**
    """
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    if "vouchers_all" in have:
        return "vouchers_all"
    return "vouchers" if "vouchers" in have else None


def _seed(conn, code="1113", referenced=True):
    """種一張傳票（＋一行分錄），讓 `code` 變成**被引用的**。

    ⚠️ 只塞 `NOT NULL` 且沒有 DEFAULT 的欄位 —— 其餘讓 DDL 的 DEFAULT 生效。
       那樣 DDL 加欄位時這裡**不必跟著改**。
    """
    conn.execute(
        "INSERT INTO %s (voucher_no, voucher_date, created_by,"
        " created_at, updated_at) VALUES (?,?,?,?,?)" % _voucher_table(conn),
        ("20260923-001", "2026-09-23", "C", "2026-09-23T00:00:00",
         "2026-09-23T00:00:00"))
    vid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if referenced:
        conn.execute(
            "INSERT INTO %s (voucher_id, line_no, account_code, debit, credit)"
            " VALUES (?,?,?,?,?)" % CHILD, (vid, 1, code, 1000, 0))
    conn.commit()
    return vid


def _custom(conn, code, name="我自己加的科目"):
    conn.execute(
        "INSERT INTO %s (code, name, parent_code, level, source)"
        " VALUES (?,?,?,?, 'custom')" % TABLE, (code, name, "", 4))
    conn.commit()


def test_v95_creates_both_triggers_on_account_items(fk_off_db):
    """🔴 **兩支 TRIGGER 都要在，而且是建在 `account_items` 上。**

    ⚠️ 釘的是「**兩個動作各有一支**」不是「至少有一支」：
    ```
    少一支  => 另一個動作沒人守，**而守住的那一個會讓人以為都守住了**
    ```
    📌 `§54c` 的形狀：**清單要能被數。**
    """
    _need_v95(fk_off_db)
    got = {r[0] for r in fk_off_db.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (TABLE,))}
    for t in TRIGGERS:
        assert t in got, (
            "`%s` 上沒有 `%s`。現有：%s\n" % (TABLE, t, sorted(got))
            + "⚠️ 名字可以換（**退回給我**），而**兩個動作各要有一支**：\n"
              "   改 code ／ 刪列。少一支 => 那個動作沒人守。")


def test_a_referenced_code_cannot_be_updated_even_with_fk_off(fk_off_db):
    """🔴🔴 **被傳票引用的科目，`code` 不可修改 —— FK 關掉時也一樣。**

    ☠️ 失敗的樣子不是報錯，是**安靜地把帳接錯**：
    ```
    voucher_lines.account_code = '1113'      <= 已過帳的傳票指著它
    account_items 把 '1113' 改成 '1114'
    => 那一行分錄從此**指向一個不存在的科目**
    => 而報表 join 不到 => 那筆金額**從科目彙總裡消失**，帳還是平的
    ```
    🔑 「帳還是平的」正是它不會被報修的原因（〈降級之後它還是會動〉）。
    """
    _need_v95(fk_off_db)
    _custom(fk_off_db, "9901", "銀行存款")
    _seed(fk_off_db, "9901")

    with pytest.raises(sqlite3.Error) as ei:
        fk_off_db.execute(
            "UPDATE %s SET code='9902' WHERE code='9901'" % TABLE)
    fk_off_db.rollback()
    assert "引用" in str(ei.value), (
        "擋下來了，而訊息是 %r ——\n" % str(ei.value)
        + "🔑 要說得出**為什麼**不能改（「此科目已被傳票引用」），"
          "否則使用者看到的是一個沒有原因的失敗。")


def test_a_referenced_account_cannot_be_deleted_even_with_fk_off(fk_off_db):
    """🔴🔴 **被傳票引用的科目不可刪除 —— FK 關掉時也一樣。**

    ☠️ 而刪掉比改掉更安靜：**傳票那一行還在，科目那一列不見了。**
    => 報表上那筆金額只是「沒有科目名稱」，看起來像資料沒填完。
    """
    _need_v95(fk_off_db)
    _custom(fk_off_db, "9901", "銀行存款")
    _seed(fk_off_db, "9901")

    with pytest.raises(sqlite3.Error) as ei:
        fk_off_db.execute("DELETE FROM %s WHERE code='9901'" % TABLE)
    fk_off_db.rollback()
    assert "引用" in str(ei.value), (
        "擋下來了，而訊息是 %r —— 要說得出**為什麼**。" % str(ei.value))


def test_an_unreferenced_custom_account_can_still_change_its_code(fk_off_db):
    """⚙️ **正對照：沒被引用的 `custom` 科目，改 code 必須成功。**

    ☠️ 少了它，一支「一律 RAISE(ABORT)」的 TRIGGER 也會讓上面兩題綠 ——
       而症狀是**使用者永遠改不了自己剛建錯的科目代號**。
    🔑 〈降級之後它還是會動〉的鏡像：**擋過頭會讓功能不能用，
       而它看起來像「我們很嚴格」。**
    📌 施工圖 `§2.5` 逐字要求這一格。
    """
    _need_v95(fk_off_db)
    _custom(fk_off_db, "9991")
    _seed(fk_off_db, "9901", referenced=False)

    try:
        fk_off_db.execute(
            "UPDATE %s SET code='9992' WHERE code='9991'" % TABLE)
    except sqlite3.Error as e:
        pytest.fail(
            "沒被引用的 `custom` 科目改 code 被擋下來了：%s\n" % e
            + "☠️ TRIGGER **擋過頭**：使用者永遠改不了自己剛建錯的科目代號。\n"
            + "🔑 我突變過（`WHEN EXISTS` 整段拿掉）確認這一格抓得到 ——\n"
              "   而**沒有這個 try/except 的話，你看到的只會是一行 SQL 錯誤**，\n"
              "   它讀起來像「測試寫錯了」，不像「守門守太寬」。")
    fk_off_db.commit()
    got = fk_off_db.execute(
        "SELECT COUNT(*) FROM %s WHERE code='9992'" % TABLE).fetchone()[0]
    assert got == 1, (
        "沒被引用的 `custom` 科目改 code 沒有生效（改後查到 %d 筆）——\n" % got
        + "☠️ TRIGGER **擋過頭**：使用者永遠改不了自己剛建錯的科目代號。")


def test_renaming_a_referenced_account_must_still_succeed(fk_off_db):
    """⚙️🔴 **正對照：被引用的科目，改「名稱」必須成功。**

    ⚠️ 這一題釘的是 `BEFORE UPDATE **OF code**` 裡的 `OF code`：
    ```
    寫成 BEFORE UPDATE ON account_items（少了 OF code）
    => 被引用的科目**連名字都改不了**
    => 而那支 TRIGGER 在上面兩題底下**完全正常**
    ```
    📌 而它同時是 **④「凍結」那一題存在的理由**：
    ```
    科目名稱改得動  => 已過帳的傳票若從 join 取名字，**印出來就會變**
    => 所以 §六(3) 要 account_name_snapshot
    ```
    ☠️ => 若有人日後把這支 TRIGGER「加強」成連名字都擋，
       **④ 會靜靜變成一題防著不存在問題的測試**（永遠是綠的）。
    """
    _need_v95(fk_off_db)
    _custom(fk_off_db, "9901", "銀行存款")
    _seed(fk_off_db, "9901")

    try:
        fk_off_db.execute(
            "UPDATE %s SET name='銀行存款（台銀）' WHERE code='9901'" % TABLE)
    except sqlite3.Error as e:
        pytest.fail(
            "被引用的科目**改名字**被擋下來了：%s\n" % e
            + "⚠️ TRIGGER 少了 `OF code` => 它守的範圍比規格大。\n"
            + "🔑 而後果在盲側：**改名字本來就該可以**，\n"
              "   而 ④ 那一題（凍結科目名稱）會因此變成防著不存在的問題。\n"
            + "📌 我突變過（`BEFORE UPDATE ON` 不加 `OF code`）確認這一格抓得到 ——\n"
              "   而上面那支 `改 code` 的題**分不出這個突變**，所以這一格不可省。")
    fk_off_db.commit()
    got = fk_off_db.execute(
        "SELECT name FROM %s WHERE code='9901'" % TABLE).fetchone()[0]
    assert got == "銀行存款（台銀）", (
        "被引用的科目改名字被擋了（現在是 %r）——\n" % got
        + "⚠️ TRIGGER 少了 `OF code` => 它守的範圍比規格大。\n"
        + "🔑 而後果在盲側：**改名字本來就該可以**，"
          "而 ④ 那一題（凍結科目名稱）會因此變成防著不存在的問題。")
