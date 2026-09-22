# -*- coding: utf-8 -*-
"""`BK32` ＋ `BK31` · 備份的**張數**要說得出來、而且要說對。

A 派工 `cf8ebad`：
```
BK32  `_daily_backup_tables()` 的 docstring 寫死張數而它已經過期 => 不可再寫死
BK31  彙總檔要記「**那一天的程式期望幾張表**」
      成因：41／46／52 三個版本並存，產物自己分不出「故障」與「程式改了」
      D 差點把 09-10~09-14 報成事故，救它的是 `git log -S`
```

---

# 📏 我自己量的（A 說 41 vs 46／52，而我量到**兩個數字都錯**）

```
docstring 裡的「N 張」   ['76', '41']
len(_daily_backup_tables())   **52**
資料庫實際表數（跑完全部 migration）   **94**
```
🔑 ⇒ **不是一個數字過期，是兩個** —— 而它們過期的方向一樣：**都變小了**。
📌 那正是這一族的性質：**張數只會增加，而寫死的數字只會往下偏** ——
   ⇒ ⇒ 每一次新增資料表都讓它更錯一點，**而沒有任何一步會紅**。

# ☠️ `BK31` 要解的是一個**產物自己分不出來**的問題

```
彙總.json 有 41 筆      => 是「今天有 11 張沒備到」還是「那一天的程式就只有 41 張」？
```
⇒ **產物裡沒有那個答案** ⇒ 只能去翻 `git log -S`。
🔑 而 D 差一點把 09-10~09-14 報成事故 —— **救它的不是守門，是一個人想到去翻 git**。
📌 〈計數器要有落點〉：**判斷「少了幾張」需要一個對照值，而那個值不在產物裡。**
"""
import json
import re
from pathlib import Path

import pytest

import archive
import db

_BACKEND = Path(__file__).resolve().parent.parent

#: 彙總檔裡記「當天程式期望幾張表」的鍵。名字要換 **退回給我**。
EXPECTED_KEYS = ("expected_tables", "expectedTables", "table_count",
                 "expected_table_count")


def _queries():
    return archive._daily_backup_tables()


# ══════════════════════════════════════════════════════════════════════
# BK32：docstring 不可以寫死張數
# ══════════════════════════════════════════════════════════════════════

def test_bk32_the_docstring_states_no_stale_table_count():
    """🔴 `BK32` **docstring 裡的「N 張」不可以與事實不符。**

    ```
    現況  docstring: 76 張（整庫）／41 張（本函式）
          實際:      **94** 張（整庫）／**52** 張（本函式）
    ```
    ☠️ 兩個都過期，而**方向一樣：都變小了** ——
       每新增一張資料表就讓它更錯一點，**而沒有任何一步會紅**。
    🔑 ⇒ 它不是一個「順手更新一下」的數字，它是一個**會自己腐爛**的數字
       ⇒ **正確的處置是不要寫死它**（A 裁），而不是再改對一次。

    ⚙️ 而本題容許它留著 —— 只要它是對的：
       那樣「改成算出來的」與「改對一次」都過得了，而**過期的版本過不了**。
    """
    doc = archive._daily_backup_tables.__doc__ or ""
    claimed = [int(n) for n in re.findall(r"(\d+)\s*張", doc)]
    if not claimed:
        return                                   # ✅ 不寫死＝最乾淨的通過方式

    n_dict = len(_queries())
    n_tables = _db_table_count()
    bad = [n for n in claimed if n not in (n_dict, n_tables)]
    assert not bad, (
        "`_daily_backup_tables()` 的 docstring 寫了 %s 張，而實際是"
        " **%d**（本函式）／**%d**（整庫）。\n" % (bad, n_dict, n_tables)
        + "☠️ 寫死的張數**只會往下偏** —— 每新增一張表就更錯一點，"
          "而沒有任何一步會紅。\n"
        + "✅ 最乾淨的處置是**不要寫死它**（把數字拿掉，或改成執行時算）。\n"
          "⚠️ 改對一次也會過 —— **而它明天又會錯**。")


def _db_table_count(_cache={}):
    if "n" not in _cache:
        import sqlite3
        import tempfile
        p = Path(tempfile.mkdtemp(prefix="motrix-C-bk32-")) / "x.db"
        db.init_db(str(p))
        conn = sqlite3.connect(str(p))
        _cache["n"] = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        conn.close()
    return _cache["n"]


def test_bk32_the_count_is_available_at_runtime():
    """⚙️ **「算出來的數字」要真的算得出來** —— `len()` 拿得到。

    ☠️ 少了這一格，「把數字從 docstring 拿掉」就只是**把資訊刪掉**，
       而不是把它換成一個活的來源。
    🔑 〈量它不等於修它〉的鏡像：**刪掉一個錯的量測不等於得到一個對的量測。**
    """
    n = len(_queries())
    assert n > 40, (
        "`_daily_backup_tables()` 只有 %d 筆 —— 我量到 52。\n" % n
        + "⚠️ 少了一大截 ⇒ 先看是不是有人把清單截短了。")
    assert all(isinstance(v, str) and v.strip().upper().startswith("SELECT")
               for v in _queries().values()) or _non_select(), (
        "有值不是 SELECT 字串 —— 那樣「張數」這個量測本身就不成立。")


def _non_select():
    bad = [k for k, v in _queries().items()
           if not (isinstance(v, str) and v.strip().upper().startswith("SELECT"))]
    if bad:
        pytest.fail(
            "這幾筆的值不是 SELECT：%s\n" % bad
            + "⚠️ 那樣 `len()` 數到的就不是「幾張表」。")
    return True


# ══════════════════════════════════════════════════════════════════════
# BK31：彙總檔要記「那一天的程式期望幾張表」
# ══════════════════════════════════════════════════════════════════════

def test_bk31_the_daily_summary_records_how_many_tables_were_expected():
    """🔴🔴 `BK31` **彙總檔要記下「當天的程式期望幾張表」。**

    ```
    彙總.json 有 41 筆
    => 是「今天有 11 張沒備到」，還是「那一天的程式就只有 41 張」？
    => **產物裡沒有那個答案**
    ```
    ☠️ 而它的代價已經發生過：D 差一點把 09-10~09-14 報成事故 ——
       **救它的不是守門，是一個人想到去翻 `git log -S`。**
    🔑 〈計數器要有落點〉：判斷「少了幾張」需要一個**對照值**，而那個值不在產物裡。
    📌 ⇒ 那個數字要**寫進彙總檔**，不是寫進文件也不是靠 git 考古。

    ⚠️ 名字可以換（**退回給我**）：我找 %s。
    """ % (list(EXPECTED_KEYS),)
    fn = getattr(archive, "_daily_backup_summary_header", None)
    if callable(fn):
        header = fn()
    else:
        header = _header_from_source()

    got = [k for k in EXPECTED_KEYS if k in header]
    assert got, (
        "彙總檔的欄位裡沒有「當天期望幾張表」（找過 %s）。\n" % list(EXPECTED_KEYS)
        + "現有欄位：%s\n" % sorted(header)
        + "☠️ 少了它，一份 41 筆的彙總檔**分不出**「今天少備了 11 張」與\n"
          "   「那一天的程式就只有 41 張」—— 而那個差別是「事故」與「正常」。\n"
        + "⚠️ 名字可以換（**退回給我**），而它必須**在產物裡**：\n"
          "   寫進文件或靠 `git log -S` 考古都不算 —— 還原現場沒有 git。")

    assert header[got[0]] == len(_queries()), (
        "彙總檔記的期望張數是 %r，而 `_daily_backup_tables()` 有 %d 筆。\n"
        % (header[got[0]], len(_queries()))
        + "☠️ 兩個數字**必須同源** —— 不同源的話它會變成第三個會腐爛的數字。")


def _header_from_source():
    """從 `_daily_backup()` 組 summary 的那一行取出固定欄位。

    ⚠️ 這是**退而求其次**的量法：正規的做法是 B 提供一支回 header 的函式。
    ☠️ 而它讀的是原始碼字面 ⇒ 換一種寫法它就看不見了
       ⇒ **它只能證明「有」，不能證明「沒有」**（〈否定句比肯定句危險〉）。
    """
    src = (_BACKEND / "archive.py").read_text(encoding="utf-8")
    m = re.search(r'summary:\s*dict\s*=\s*\{([^}]*)\}', src)
    if not m:
        pytest.fail(
            "在 `archive.py` 裡找不到 `summary: dict = {...}` 那一行 ——\n"
            + "⚠️ 寫法變了 ⇒ **請 B 提供一支回彙總檔固定欄位的函式**，"
              "我把這個字面量法換掉。")
    out = {}
    for km in re.finditer(r'"([^"]+)"\s*:', m.group(1)):
        out[km.group(1)] = None
    return out


def test_bk31_the_expected_count_and_the_actual_rows_are_two_different_things():
    """⚙️ **正對照：期望張數與「每張表幾筆」不可以是同一個欄位。**

    ☠️ 少了它，一個把 `len(summary)` 當成期望值的實作也會讓上一題綠 ——
       而那樣它**永遠等於實際張數**，`BK31` 要回答的問題就消失了：
    ```
    期望 41 ／ 實際 41  =>  看起來一切正常
    而實際是「今天有 11 張失敗，所以只寫進去 41 筆」
    ```
    🔑 **一個總是等於被量測值的對照組，不是對照組。**
    """
    fn = getattr(archive, "_daily_backup_summary_header", None)
    header = fn() if callable(fn) else _header_from_source()
    got = [k for k in EXPECTED_KEYS if k in header]
    if not got:
        pytest.fail("彙總檔還沒有期望張數 —— 見上一題。")

    src = (_BACKEND / "archive.py").read_text(encoding="utf-8")
    m = re.search(r'summary:\s*dict\s*=\s*\{([^}]*)\}', src)
    block = m.group(1) if m else ""
    assert not re.search(r'len\s*\(\s*summary\s*\)', block), (
        "期望張數是用 `len(summary)` 算的 ——\n"
        + "☠️ 那樣它**永遠等於實際寫進去的筆數** ⇒ 期望 41／實際 41 看起來正常，\n"
          "   而實際是「今天有 11 張失敗」。\n"
        + "✅ 它要來自 `len(_daily_backup_tables())`（**當天的程式期望幾張**），"
          "不是來自結果。")
