"""§TD TD1 · **解析器有產出，而 `INSERT` 把它們丟掉了。**

---

# ☠️ 缺陷的形狀

```
parse_list_row()            解析出 tender_method / procurement_type   ✅
tenders 表                  兩個欄位都在                              ✅
tender_radar.py:347-348     在讀它們                                  ✅
email_notify.py:1826-1827   也在讀                                    ✅
_store() 的 INSERT          **八欄，沒有那兩個**                      🔴
```

🔑 **四個地方裡三個是對的，而中間那一行少了兩個名字。**
☠️ 症狀是畫面上 200 筆全部顯示 `—`，
📌 **而那跟「來源本來就沒寫」長得一模一樣** —— 所以沒有人查得出來。

---

# 🔑 A 說這是今天第四次同一個形狀，而那句話值得寫成方法

```
quotations.location_id        欄位在、顯示端在讀、而 SELECT 沒撈
_clean_locations() 的五欄     前端送了、後端收了、而白名單沒放行
tenders 的那兩欄              解析了、欄位在、顯示端在讀、而 INSERT 沒寫
blank_profile 的 patch 目標   patch 生效了、而它打的不是被讀的那一支
```
⇒ **一個「顯示不出來」的欄位，要沿著五段逐段看**：
```
來源 → 解析 → 寫入 → 讀出 → 顯示
```
☠️ **每一段各自都對，而中間有一段沒接上** ——
🔑 而只看兩端（「解析器有產出」＋「顯示端在讀」）會得到「它應該要有」這個結論。

---

# 📌 觀測點：**存進去再讀出來**，不是「`INSERT` 那一行有沒有那兩個字」

⚠️ 釘字面 `"tender_method"` 出現在 `_store()` 裡＝釘實作 ——
🔑 日後改成 `INSERT ... SELECT` 或欄位清單用變數組出來，這一題會紅在一個假的理由上。
⇒ 餵一筆解析結果進 `_store()`，**從資料庫讀回來比對值**。
"""
import pytest


def _ts():
    from helpers import tender_source
    return tender_source


#: 一筆「解析器產出」的樣子。📌 值故意寫得在真實資料裡不會出現。
PARSED = {
    "case_no": "TD1-CASE-001",
    "org": "TD1 測試機關",
    "name": "TD1 測試標案",
    "published_at": "2026-09-20",
    "deadline": "2026-10-20",
    "budget": 1234567,
    "url": "https://example.invalid/td1",
    "tender_method": "公開招標TD1",
    "procurement_type": "財物TD1",
}

#: A 的條文點名的那兩個 —— **它們是這一題的全部內容。**
DROPPED = ("tender_method", "procurement_type")


@pytest.fixture
def clean_tender(client):
    """每一題自己清掉那一筆 —— `INSERT OR IGNORE` 會讓殘留變成假綠燈。

    ☠️ 殘留一筆的話，`INSERT OR IGNORE` **什麼都不做**，
    🔑 而讀回來的是**上一題寫進去的值** ⇒ 題目綠，而這一次根本沒有寫入。
    📌 〈假綠燈〉：**測試間共用的狀態**，今天第二次（前一次是負快取）。
    """
    import db

    def _wipe():
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM tenders WHERE case_no LIKE 'TD1-CASE-%'")
            conn.commit()
        finally:
            conn.close()

    _wipe()
    yield
    _wipe()


def _store_one(item):
    import db
    ts = _ts()
    conn = db.get_db()
    try:
        ts._store(conn, [dict(item)])
        conn.commit()
    finally:
        conn.close()


def _read_back(case_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT * FROM tenders WHERE case_no=?", (case_no,)).fetchone()
    finally:
        conn.close()
    assert row is not None, (
        f"`{case_no}` 根本沒有存進去 ——\n"
        "⇒ 這一題的前提不成立（不是那兩欄的問題，是整筆沒寫）。")
    return dict(row)


# ══════════════════════════════════════════════════════════════════════
# TD1 · 解析出來的要寫得進去
# ══════════════════════════════════════════════════════════════════════

def test_td1_the_parsed_columns_are_actually_written(clean_tender):
    """🔴🔴 TD1：**解析器產出的 `tender_method` 與 `procurement_type` 要進資料庫。**

    ☠️ 少了它們，畫面上 200 筆全部顯示 `—` ——
    🔑 **而那跟「來源本來就沒寫」長得一模一樣**，所以沒有人查得出來。
    📌 觀測的是**讀回來的值**，不是 `INSERT` 那一行的字面 ——
    日後改寫法這一題要照樣有效。
    """
    _store_one(PARSED)
    row = _read_back(PARSED["case_no"])

    lost = {c: (PARSED[c], row.get(c)) for c in DROPPED
            if row.get(c) != PARSED[c]}
    assert not lost, (
        "解析出來了，而這幾欄沒有寫進資料庫：\n"
        + "\n".join(f"  {c}：解析到 {p!r}，資料庫是 {g!r}"
                    for c, (p, g) in sorted(lost.items()))
        + "\n☠️ 畫面上會顯示 `—`，而那跟「來源本來就沒寫」一模一樣。\n"
          "🔑 解析器對、欄位在、顯示端在讀 —— **只有中間那一行沒接上。**")


def test_td1_the_other_columns_did_not_regress(clean_tender):
    """⚙️ 反向控制①：**補那兩欄的時候，原本八欄不可以掉。**

    ☠️ 一個欄位清單改錯順序（`VALUES` 的問號與欄名錯位）會讓
    上一題**照樣綠** —— 只要那兩欄剛好對上。
    🔑 而錯位的症狀是**別的欄位裝了別人的值**，
    📌 例如預算欄裡出現一個日期 —— 而它在列表上只是一個看起來很怪的數字。
    """
    _store_one(PARSED)
    row = _read_back(PARSED["case_no"])

    for col in ("org", "name", "published_at", "deadline", "budget", "url"):
        assert row.get(col) == PARSED[col], (
            f"`{col}` 存成了 {row.get(col)!r}，解析到的是 {PARSED[col]!r}\n"
            "☠️ 欄位清單與 `VALUES` 錯位了 —— 而那兩欄可能剛好還是對的。")


def test_td1_a_missing_parse_result_does_not_write_a_placeholder(clean_tender):
    """⚙️ 反向控制②：**解析不到那兩欄時，存 `NULL` 不是存一個字串。**

    ☠️ 存 `""` 或 `"—"` 的話，`TD2` 的回填就分不出
    「**這一筆沒有**」與「**這一筆還沒補**」——
    🔑 而回填會跳過它們，**永遠**。
    📌 〈null 不等於 0〉：**「沒有值」與「值是空的」在補資料時處置相反。**
    """
    item = dict(PARSED, case_no="TD1-CASE-002")
    item.pop("tender_method")
    item.pop("procurement_type")

    _store_one(item)
    row = _read_back("TD1-CASE-002")

    for col in DROPPED:
        assert row.get(col) is None, (
            f"解析不到 `{col}`，而存進去的是 {row.get(col)!r} 不是 `NULL`\n"
            "☠️ 回填時分不出「這一筆沒有」與「這一筆還沒補」，\n"
            "🔑 而回填會跳過它們，**永遠**。")


def test_td1_the_probe_would_notice_the_columns_being_dropped(clean_tender,
                                                              monkeypatch):
    """📏 量尺：**把那兩欄從寫入路徑拿掉，上面那一題要紅。**

    ⚠️ 這一節是**綠著出生的**（B 已修，`7200bff`）——
    ☠️ 而今天早上 `QL7` 八題全綠而功能零效果，**綠著出生要先證明它有拒絕力**。

    ⚠️ **不改 B 的檔**：餵一筆**解析結果裡那兩欄是 `None`** 的資料，
    再確認讀回來也是 `None` —— 若讀回來仍然是 `PARSED` 的值，
    代表我讀到的是別筆，或 `_store()` 根本沒有在寫這兩欄的值。
    """
    _store_one(PARSED)
    assert _read_back(PARSED["case_no"])["tender_method"] == \
        PARSED["tender_method"], "前提不成立：第一筆就沒寫進去"

    blank = dict(PARSED, case_no="TD1-CASE-003",
                 tender_method=None, procurement_type=None)
    _store_one(blank)
    row = _read_back("TD1-CASE-003")

    for col in DROPPED:
        assert row.get(col) is None, (
            f"我送 `{col}=None`，而資料庫裡是 {row.get(col)!r} ——\n"
            "☠️ 那代表 `_store()` 寫進去的**不是我送的那個值**，\n"
            "🔑 而上面那幾題的綠因此證明不了任何事（它們可能在讀別筆）。")
