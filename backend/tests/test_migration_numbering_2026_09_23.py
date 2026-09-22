# -*- coding: utf-8 -*-
"""`MG1` · migration 版本號一致性守門。

# 🔴 為什麼現在需要它（A `§69b`，有時效）

```
既有守門只有  len(_MIGRATIONS) >= 80        ← 一個**下界**
而現在兩條線一起跑，兩邊都要從 v93 開始加 migration
⇒ **兩個視窗各加一支 `_m093`**
⇒ len 變 94、CURRENT_VERSION 被改成 94、下界照樣過 ⇒ **測試全綠**
⇒ 它在**第一次啟動**時才爆（v93 跑兩次／v94 從來不跑，看實作而定）
```
☠️ 下界型的守門對「重號」完全沒有辨識力 —— 它只答「夠不夠多」。
🔑 〈判準的寬窄都會騙人〉：`>=` 是超集檢查，**它給你綠燈所以你不會回來看它**。

# ⚠️ 這條規則在這個 repo 裡已經有**第二份實作**

`backend/tools/verify_package.py:219 _db_version_facts()` 用**解析原始碼**的方式
算同樣三個數字（給打包擋關用）。本檔用 **import 模組**的方式算。
```
兩份實作、兩條路徑、同一條規則 ⇒ **而沒有任何東西要求它們一致**
```
⇒ 所以本檔**不只驗 db.py，也驗那兩份算出來的東西相同**。
📌 今天在 `geo.py` 的 TTL 上遇過同一個形狀（`:1157` 的 `>=` 與 `:1184` 的 `<`），
   而那一次的分岔只出現在一個點上。這裡的分岔會出現在
   **「有人改了 `_MIGRATIONS` 的排版」**那一天：正則看不見了、回傳 0，
   而打包擋關會安靜地說「三源一致 ✅」。
"""
import importlib.util
from pathlib import Path

import pytest

import db

_BACKEND = Path(__file__).resolve().parent.parent
_DB_PY = _BACKEND / "db.py"
_VERIFY_PY = _BACKEND / "tools" / "verify_package.py"

#: `_mNNN_...` 的編號前綴。
_PREFIX = __import__("re").compile(r"^_m(\d+)_")


def _numbers():
    """`[(位置(1起), 函式名, 編號或 None)]`。"""
    out = []
    for i, fn in enumerate(db._MIGRATIONS, start=1):
        name = getattr(fn, "__name__", repr(fn))
        m = _PREFIX.match(name)
        out.append((i, name, int(m.group(1)) if m else None))
    return out


def test_mg1_the_three_sources_agree():
    """🔴🔴 `MG1`①：**`CURRENT_VERSION` == `len(_MIGRATIONS)` == 最後一支的編號。**

    三個**互相獨立**的來源。只看 `CURRENT_VERSION` 證明不了什麼 ——
    🔑 **那是一個整數，改它不需要真的加一支 migration**
    （〈守門守的對象被搬走〉）。

    ```
    CURRENT_VERSION 大於實際支數  ⇒ 啟動時「該跑的 migration 沒跑」，
                                    而 schema_version 已經被寫成新的 ⇒ **永遠補不回來**
    CURRENT_VERSION 小於實際支數  ⇒ 最後幾支永遠不會被執行，
                                    而**沒有任何症狀**直到有人用到那些欄位
    ```
    """
    rows = _numbers()
    assert rows, "`_MIGRATIONS` 是空的 —— **儀器失效**，不是「沒有 migration」。"
    last_pos, last_name, last_num = rows[-1]
    facts = (db.CURRENT_VERSION, len(db._MIGRATIONS), last_num)
    assert len(set(facts)) == 1, (
        "三源不一致：`CURRENT_VERSION`=%s／`len(_MIGRATIONS)`=%s／"
        "最後一支 `%s`=%s\n" % (facts[0], facts[1], last_name, facts[2])
        + "☠️ 大於實際支數 ⇒ 該跑的沒跑，而 `schema_version` 已被寫成新的"
          "⇒ **永遠補不回來**。\n"
          "☠️ 小於 ⇒ 最後幾支永遠不會被執行，而**沒有任何症狀**"
          "直到有人用到那些欄位。")


def test_mg1_every_prefix_is_unique():
    """🔴🔴 `MG1`②：**`_mNNN` 前綴不可重號。**

    ☠️ **這是現在最會發生的那一種**：兩條線一起跑，兩個視窗各加一支 `_m093`。
    ```
    git 不會衝突（兩個人加在不同位置／不同段落）
    len(_MIGRATIONS) 變 94、CURRENT_VERSION 改成 94 ⇒ 既有下界守門照樣過
    ⇒ **兩支都會被執行，而它們都宣稱自己是 v93**
    ```
    🔑 而症狀出現在**第一次啟動**，不在任何一個人的測試裡。
    """
    rows = _numbers()
    seen, dups = {}, []
    for pos, name, num in rows:
        if num is None:
            continue
        if num in seen:
            dups.append("_m%03d 重號：位置 %d `%s` 與 位置 %d `%s`"
                        % (num, seen[num][0], seen[num][1], pos, name))
        else:
            seen[num] = (pos, name)
    assert not dups, (
        "`_MIGRATIONS` 有重號：\n  " + "\n  ".join(dups) + "\n"
        + "☠️ 兩個人同時加一支同號 migration，**git 不會衝突**，"
          "而既有的 `len >= 80` 下界守門也不會紅。\n"
        "🔑 症狀出現在第一次啟動，不在任何一個人的測試裡。")

    bad = [(pos, name) for pos, name, num in rows if num is None]
    assert not bad, (
        "有 migration 的函式名不是 `_mNNN_` 開頭：%s\n"
        % ["%d:%s" % b for b in bad]
        + "🔑 名字是三個獨立來源之一 —— 它不合形狀時，"
          "上面那些檢查**對它沒有辨識力**（它會被安靜地略過）。")


def test_mg1_the_prefixes_are_contiguous_and_in_order():
    """🔴 `MG1`③：**前綴連續、無跳號，而且與它在清單裡的位置相同。**

    ```
    跳號   _m094 存在而 _m093 不存在 ⇒ len 與最後一支的編號對不上，
           而**若有人同時把 CURRENT_VERSION 改成 94**，上面①那題會綠
    亂序   _m050 排在 _m060 後面 ⇒ 執行順序與編號不一致，
           而 migration 之間有相依時它會壞在一個很難追的地方
    ```
    🔑 **位置 == 編號**比「唯一 ＋ 連續」更強（它同時擋住亂序），
       而我把三個分開寫是為了**訊息說得出是哪一種**。
    """
    rows = _numbers()
    off = [(pos, name, num) for pos, name, num in rows
           if num is not None and num != pos]
    assert not off, (
        "前綴與它在 `_MIGRATIONS` 裡的位置對不上：\n  "
        + "\n  ".join("位置 %d 是 `%s`（編號 %d）" % r for r in off[:10])
        + ("\n  …共 %d 筆" % len(off) if len(off) > 10 else "")
        + "\n☠️ 跳號 ⇒ 最後一支的編號與 `len` 對不上；"
          "亂序 ⇒ 執行順序與編號不一致，而 migration 之間有相依時"
          "它會壞在一個很難追的地方。")


def test_mg1_the_packaging_gate_reads_the_same_numbers():
    """🔴🔴 `MG1`④：**打包擋關那一份實作，要算出同樣的三個數字。**

    ```
    本檔            import db ⇒ 讀**物件**
    verify_package  正則解析 db.py 原始碼 ⇒ 讀**文字**
    ⇒ 同一條規則、兩份實作，而沒有任何東西要求它們一致
    ```
    ☠️ 分岔的樣子：有人改了 `_MIGRATIONS` 的排版（例如一行寫兩支、
    或把項目換成 `functools.partial(...)`）⇒ 那個正則**看不見了**
    ⇒ `count` 回 0、`last` 回 `None`
    ⇒ 而 `verify_package` 的「三源一致」檢查會拿 0 去比，**安靜地放行**。
    🔑 打包擋關失效的樣子是**「它說一切正常」**，不是「它壞了」。

    📌 今天在 `geo.py` 的 TTL 上遇過同一個形狀（兩個獨立的比較式）——
       那一次的分岔只出現在一個時間點上，這一次會出現在**改排版**那一天。
    """
    assert _VERIFY_PY.exists(), "找不到 %s —— 前提不成立。" % _VERIFY_PY
    spec = importlib.util.spec_from_file_location("_vp_mg1", _VERIFY_PY)
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)

    facts = vp._db_version_facts(str(_DB_PY))
    rows = _numbers()
    mine = {"current": db.CURRENT_VERSION,
            "count": len(db._MIGRATIONS),
            "last_num": rows[-1][2]}

    diff = [(k, facts.get(k), mine[k]) for k in sorted(mine)
            if facts.get(k) != mine[k]]
    assert not diff, (
        "打包擋關算出來的與 import 算出來的不一致：\n  "
        + "\n  ".join("%s：verify_package=%r／import=%r" % d for d in diff)
        + "\n☠️ `verify_package` 的正則看不見的東西會回 `0`／`None`，"
          "而它的「三源一致」檢查會拿那個值去比 ⇒ **安靜地放行**。\n"
        "🔑 打包擋關失效的樣子是「它說一切正常」，不是「它壞了」。\n"
        "📌 接縫：`verify_package.py:219 _db_version_facts()`。")


def test_mg1_the_numbering_checks_can_actually_fail():
    """⚙️ **正對照** —— 證明上面那些比較真的分辨得出差異。

    ☠️ 少了它，一個「`_numbers()` 永遠回空清單」的世界裡，
    `..._unique` 與 `..._contiguous` 都會**永遠綠**
    （`dups` 空、`off` 空），而那與「編號全對」長得一模一樣。
    🔑 〈沒抓到要被解釋成儀器失效，不可以被解釋成乾淨〉。

    ⚠️ 這一題與受測物**走同一條量測路徑**（都用 `_PREFIX`／`_numbers()`）——
    那是刻意的：它分辨的是**「量法壞了」**。
    而 `..._three_sources_agree` 裡的 `assert rows` 走的是
    `db._MIGRATIONS` 本身，分辨的是**「清單是空的」**。
    📌 **兩個分辨的不是同一件事，刪掉任何一個都會少一種辨識力。**
    """
    rows = _numbers()
    assert len(rows) >= 80, (
        "只抓到 %d 支 migration —— **儀器失效**（既有守門的下界是 80）。"
        % len(rows))
    assert all(n is not None for _p, _n, n in rows), (
        "有 migration 抽不出編號 —— `_PREFIX` 這個量法對它沒有辨識力。")

    assert _PREFIX.match("_m093_foo"), "`_PREFIX` 抓不到一個正常的名字。"
    assert not _PREFIX.match("m093_foo"), "`_PREFIX` 太寬（少了底線也算）。"
    assert int(_PREFIX.match("_m007_bar").group(1)) == 7, (
        "`_PREFIX` 把 `007` 解成 %s —— 前導零沒被吃掉。"
        % _PREFIX.match("_m007_bar").group(1))
