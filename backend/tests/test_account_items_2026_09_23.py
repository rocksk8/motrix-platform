# -*- coding: utf-8 -*-
"""`v93`／`v94` · 會計項目表（科目樹）建表與載入。

來源：《商業會計項目表》112 年度版（經濟部商業司，商業會計法第 27 條）。
`docs/reference/` 有 PDF 與它的 `.sha256`。

---

# ⚠️ 第一個紅是**弱的**，而這一節的存在就是為了那件事

```
表還不存在 ⇒ 每一題都紅在 `no such table: account_items`
⇒ 那是**對的紅**，而它**分不出「表不存在」與「表存在但欄位／TRIGGER 錯」**
☠️ ⇒ 「表建起來了」會讓每一題**一起**變綠，而它們證明的不是同一件事
```
⇒ **B 實作完之後要用突變逐題確認它紅在自己的斷言上**（A 指定四個）：
```
⚙️ 拿掉 TRIGGER     ⇒ 紅在 TRIGGER 那題，不是紅在「表不存在」
⚙️ 某個欄位改名     ⇒ 紅
⚙️ 載入筆數少一筆   ⇒ 紅
⚙️ 正對照：custom 的 UPDATE **必須成功** ← 少了它，「全部都擋住」也會綠
```

---

# 📌 三個數字我自己對靜態檔量過（不是照收）

```
總筆數      547   （`count` 欄與 `len(items)` 一致）
層級分佈    L1=8 ／ L2=20 ／ L3=94 ／ L4=425   合計 547
parent 孤兒 0
```
⚠️ **一級是 8 個不是 9 個** —— `§69` 原本寫 9（從「1–9」的編號推的），
`§93a` 實查更正：**`9` 不存在**。
🔑 那一條 A 記進 `§6`：**把一個「看起來像常識」的數字寫成正對照，比寫成註記更危險**
   —— 它會讓守門**為錯的理由紅**，而排查的人會去修那個沒壞的東西。

# 🔴 `parent_code` **不可以靠前綴**，而證據是活的

```
111       parent = 11-12      ← "111".startswith("11-12") 為 False
211       parent = 21-22
723-724   parent = 71-72
```
📌 我另外量到**範圍代號共 13 個**（A-2 當初粗估 2，而它明著標了那是粗估、
   沒有拿去支撐任何設計決定）。
"""
import json
import re
import sqlite3
from pathlib import Path

import pytest

import db

_BACKEND = Path(__file__).resolve().parent.parent
STATIC_JSON = _BACKEND / "data" / "account_items_112.json"

TABLE = "account_items"
#: 實查靜態檔得到的定版數字。
TOTAL = 547
BY_LEVEL = {1: 8, 2: 20, 3: 94, 4: 425}
#: `parent_code` 不靠前綴的三筆活證據（`§93d`）。
NON_PREFIX_PARENTS = (("111", "11-12"), ("211", "21-22"), ("723-724", "71-72"))


@pytest.fixture(scope="module")
def fresh_db(tmp_path_factory):
    """跑完**全部** migration 的一份新資料庫。

    ⚠️ 用 `db.init_db()` 而不是自己建表 —— 這一檔要驗的正是
       「`v93`／`v94` 這兩支 migration 做了什麼」，**自己建表等於驗我自己寫的東西**。
    """
    path = tmp_path_factory.mktemp("acct") / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _static_items():
    assert STATIC_JSON.exists(), "找不到靜態檔 %s" % STATIC_JSON
    data = json.loads(STATIC_JSON.read_text(encoding="utf-8"))
    return data, data["items"]


# ══════════════════════════════════════════════════════════════════════
# 靜態檔自身（不依賴 migration，所以它**不會**跟著「表不存在」一起紅）
# ══════════════════════════════════════════════════════════════════════

def test_v94_the_static_file_agrees_with_itself():
    """⚙️ **先驗輸入**：靜態檔的 `count` 與實際筆數、層級分佈要一致。

    🔑 這一題刻意**不碰資料庫** —— 它是整組題的**輸入正對照**：
    ```
    它綠 ＋ 別的紅  ⇒ 問題在 migration
    它紅            ⇒ 問題在輸入，**而其餘每一題的紅都不可信**
    ```
    📌 〈沒抓到要被解釋成儀器失效〉的上游版：**先確定餵進去的東西是對的。**
    """
    data, items = _static_items()
    assert data["count"] == len(items) == TOTAL, (
        "靜態檔說 %s 筆、實際 %s 筆、定版 %s 筆 —— 三者不一致。"
        % (data["count"], len(items), TOTAL))

    by_level = {}
    for it in items:
        by_level[it["level"]] = by_level.get(it["level"], 0) + 1
    assert by_level == BY_LEVEL, (
        "層級分佈是 %s，定版是 %s。\n" % (dict(sorted(by_level.items())), BY_LEVEL)
        + "⚠️ **一級是 8 個不是 9 個** —— `9` 不存在（`§93a` 實查更正）。")

    codes = {it["code"] for it in items}
    orphans = sorted(it["code"] for it in items
                     if it["parent_code"] and it["parent_code"] not in codes)
    assert not orphans, (
        "這些項目的 `parent_code` 指向一個不存在的代號：%s\n" % orphans[:10]
        + "☠️ 建樹時它們會變成孤兒，而畫面上**只是少了幾個節點**。")


def test_v94_parent_code_cannot_be_derived_from_the_prefix():
    """🔴 **`parent_code` 不可以靠前綴推**（`§69②`／`§93d`）。

    ```
    111       parent = 11-12   ← "111".startswith("11-12") 為 False
    211       parent = 21-22
    723-724   parent = 71-72
    ```
    ☠️ 用前綴建樹的話這三支（以及它們底下的整個子樹）**接不起來**，
    🔑 而症狀是**畫面上少了幾個分支**，不是報錯。

    ⚙️ 這一題同時是那個欄位的**存在理由**：
       日後有人看到「代號長度 ＝ 層級」想把 `parent_code` 拿掉時，它會紅。
    """
    _data, items = _static_items()
    by_code = {it["code"]: it for it in items}
    for code, parent in NON_PREFIX_PARENTS:
        assert code in by_code, "靜態檔裡找不到 `%s` —— **儀器失效**。" % code
        actual = by_code[code]["parent_code"]
        assert actual == parent, (
            "`%s` 的 parent 是 %r，預期 %r。" % (code, actual, parent))
        assert not code.startswith(parent), (
            "`%s` **可以**用前綴從 `%s` 推出來 —— 這三筆活證據挑錯了。\n"
            % (code, parent)
            + "🔑 這一題要釘的是「前綴推不出來」，"
              "挑一組推得出來的等於什麼都沒驗。")


# ══════════════════════════════════════════════════════════════════════
# v93 · 建表 ＋ TRIGGER
# ══════════════════════════════════════════════════════════════════════

def test_v93_the_table_exists_with_its_columns(fresh_db):
    """🔴 `v93`：**`account_items` 表要建起來，而且欄位齊。**

    ⚠️ 這一題是其餘每一題的**前提**。它紅的時候，
       下面那些紅**不可信**（它們全部紅在「表不存在」）。
    📌 所以它刻意只驗結構，不驗內容 —— **讓「前提不成立」與「內容錯」分得開。**
    """
    row = fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (TABLE,)).fetchone()
    assert row, (
        "`%s` 表不存在 —— `v93` 還沒做。\n" % TABLE
        + "⚠️ 本檔其餘的紅在這一題綠之前**都不可信**：它們全部紅在同一個原因。")

    cols = {r["name"] for r in fresh_db.execute("PRAGMA table_info(%s)" % TABLE)}
    need = {"code", "level", "name", "parent_code", "source"}
    missing = sorted(need - cols)
    assert not missing, (
        "`%s` 缺欄位：%s（現有：%s）\n" % (TABLE, missing, sorted(cols))
        + "🔑 `source` 是 `§69(a)` 的核心：**單表 ＋ source 欄位**，不要兩張表 ——\n"
          "   兩張表會讓每個引用點都要 union，而**漏掉 union 的那一處會安靜地少一半資料**。")


@pytest.mark.parametrize("op", ["update", "delete"])
def test_v93_statutory_rows_are_protected_at_the_data_layer(fresh_db, op):
    """🔴🔴 `v93`：**法定項目改不動、刪不掉**（TRIGGER ＋ `RAISE(ABORT)`）。

    🔑 為什麼不能只靠應用層 —— 那是〈散文對工具是隱形的〉的**資料版**：
    ```
    應用層只在「有人走那條路徑」時生效
    而 migration／修復腳本／直接連 db **都繞得過**
    ```
    ⚠️ 本專案用過 TRIGGER（`db.py:3926`），**而 `RAISE(ABORT)` 沒有前例**
       ⇒ `§69(b)` 明著要求**實測**，不可以只讀碼。

    ⚙️ 正對照在下一題：**`custom` 的同一個操作必須成功。**
    """
    row = fresh_db.execute(
        "SELECT code FROM %s WHERE source='statutory' LIMIT 1" % TABLE).fetchone()
    assert row, (
        "找不到任何 `source='statutory'` 的列 —— **儀器失效**，"
        "這一題會因為量不到而綠。")
    code = row["code"]

    sql = ("UPDATE %s SET name='改過了' WHERE code=?" % TABLE if op == "update"
           else "DELETE FROM %s WHERE code=?" % TABLE)
    with pytest.raises(sqlite3.IntegrityError) as exc:
        fresh_db.execute(sql, (code,))
        fresh_db.commit()
    assert "法定" in str(exc.value) or "statutory" in str(exc.value).lower(), (
        "擋下來了，而訊息看不出原因：%s\n" % exc.value
        + "🔑 `RAISE(ABORT, …)` 的那句話是使用者唯一會看到的東西。")


@pytest.mark.parametrize("op", ["update", "delete"])
def test_v93_custom_rows_are_still_editable(fresh_db, op):
    """⚙️ **正對照：`custom` 的同一個操作必須成功。**

    ☠️ 少了它，一個「**全部都擋住**」的 TRIGGER 會讓上一題全綠 ——
    🔑 而那會讓使用者**連自己加的科目都改不動**，
       而 `§69①` 的依據正是法條允許「商業得視實際需要增減其會計項目」。
    📌 〈守門要配反向控制〉：**擋住太多與擋不住，在上一題裡長得一樣。**
    """
    fresh_db.execute(
        "INSERT INTO %s (code, level, name, parent_code, source) "
        "VALUES ('C999', 1, '測試用自訂科目', NULL, 'custom')" % TABLE)
    fresh_db.commit()
    try:
        if op == "update":
            fresh_db.execute(
                "UPDATE %s SET name='改過了' WHERE code='C999'" % TABLE)
            fresh_db.commit()
            got = fresh_db.execute(
                "SELECT name FROM %s WHERE code='C999'" % TABLE).fetchone()
            assert got and got["name"] == "改過了", (
                "`custom` 的 UPDATE 沒有生效 ——\n"
                "☠️ TRIGGER 擋過頭了：使用者連自己加的科目都改不動。")
        else:
            fresh_db.execute("DELETE FROM %s WHERE code='C999'" % TABLE)
            fresh_db.commit()
            got = fresh_db.execute(
                "SELECT code FROM %s WHERE code='C999'" % TABLE).fetchone()
            assert got is None, (
                "`custom` 的 DELETE 沒有生效 —— TRIGGER 擋過頭了。")
    finally:
        fresh_db.execute("DELETE FROM %s WHERE code='C999'" % TABLE)
        fresh_db.commit()


# ══════════════════════════════════════════════════════════════════════
# v94 · 載入 547 筆
# ══════════════════════════════════════════════════════════════════════

def test_v94_all_statutory_rows_are_loaded(fresh_db):
    """🔴 `v94`：**547 筆全部載進去，而且層級分佈對得上。**

    ⚙️ 只驗總數的話，「載了 547 筆**同一層**的東西」也會綠 ——
    🔑 所以連**分佈**一起釘（`8 / 20 / 94 / 425`）。
    📌 那是〈判準的寬窄都會騙人〉的預防：**一個總數是一個很寬的判準。**
    """
    n = fresh_db.execute(
        "SELECT COUNT(*) c FROM %s WHERE source='statutory'" % TABLE).fetchone()["c"]
    assert n == TOTAL, (
        "載入 %d 筆，靜態檔有 %d 筆。\n" % (n, TOTAL)
        + "⚠️ 少一筆也要紅：那一筆可能正好是某個子樹的根。")

    got = {}
    for r in fresh_db.execute(
            "SELECT level, COUNT(*) c FROM %s WHERE source='statutory' "
            "GROUP BY level" % TABLE):
        got[r["level"]] = r["c"]
    assert got == BY_LEVEL, (
        "層級分佈是 %s，預期 %s。\n" % (dict(sorted(got.items())), BY_LEVEL)
        + "🔑 總數對而分佈錯 ⇒ 解析把某一層歸錯了，**而總數看起來很正常**。")


def test_v94_every_parent_resolves_inside_the_table(fresh_db):
    """🔴 `v94`：**每一筆的 `parent_code` 都要在表裡找得到。**

    ☠️ 孤兒的症狀是**畫面上少了一整個分支**，不是報錯。
    ⚙️ 而這一題與靜態檔那一題**是兩件事**：
    ```
    靜態檔那題  輸入本身完整嗎
    這一題      **載進去之後**還完整嗎（有沒有在載的過程中掉了）
    ```
    🔑 兩個都綠才表示「輸入對 **且** 載對了」。
    """
    orphans = [r["code"] for r in fresh_db.execute(
        "SELECT a.code FROM %s a WHERE a.parent_code IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM %s b WHERE b.code = a.parent_code)"
        % (TABLE, TABLE))]
    assert not orphans, (
        "這些列的 `parent_code` 在表裡找不到：%s\n" % orphans[:10]
        + "☠️ 它們與它們底下的整個子樹在畫面上**直接消失**，而不會報錯。")


def test_v94_the_migration_does_not_call_the_parser():
    """🔴 `§69(c)`：**載資料那支 migration 不可以呼叫 PDF 解析器。**

    ```
    📌 〈凍住的歷史不要呼叫活的程式碼〉：migration 是凍結的歷史，解析器會演進
    ⇒ 日後解析器改了，那支 migration 產生的東西就跟當初不一樣
    ⇒ ☠️ **而症狀只出現在「全新安裝」與「災難還原」那條路上**
    ```
    ⚙️ 判準是**那一支函式的本體**，不是整個 `db.py` ——
       `db.py` 別處提到解析器是允許的。
    ⚠️ 而它要剝掉註解：解釋「為什麼不呼叫解析器」的註解裡**會寫出那個名字**。
       🔑 今天第五次同一件事（B 的絆線 ×2／我的 `sec()/ni()`／`reports.js:1940`／這次）。
    """
    src = (_BACKEND / "db.py").read_text(encoding="utf-8")
    lines = src.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if re.match(r"\s*def _m094_", l)), None)
    assert start is not None, (
        "`db.py` 裡找不到 `_m094_…` —— `v94` 還沒做。")

    depth, body = 0, []
    for i in range(start, len(lines)):
        body.append(lines[i])
        if i > start and re.match(r"\s*def \w+", lines[i]):
            body.pop()
            break
    text = "\n".join(body)
    code_only = "\n".join(
        re.sub(r"#.*$", "", l) for l in text.splitlines())
    code_only = re.sub(r'"""[\s\S]*?"""', "", code_only)

    for bad in ("parse_account_items", "pdfplumber", "fitz", "PyMuPDF"):
        assert bad not in code_only, (
            "`_m094` 的本體裡出現 `%s` ——\n" % bad
            + "☠️ migration 是**凍結的歷史**，而解析器會演進 ⇒\n"
              "   日後解析器改了，這支 migration 產生的東西就跟當初不一樣，\n"
              "   **而症狀只出現在「全新安裝」與「災難還原」那條路上**。\n"
            "✅ 它只能讀 `data/account_items_112.json` 那個不再變動的檔。")

    assert "account_items_112.json" in code_only, (
        "`_m094` 的本體裡沒有讀那個靜態檔 ——\n"
        "⚙️ 這是正對照：少了它，「什麼都不做」的 `_m094` 也會讓上面全綠。")
