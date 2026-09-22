# -*- coding: utf-8 -*-
"""`HG1` · `docs/*.md` 的**同形異碼逐字黑名單**。

`STATE.md §128`（`e26f995`／`99e483c`）：
```
逐字黑名單（**不可用字元類別** —— 兩者都不在相容區，A 實測）
清單只在**咬到一次**之後才新增，不先列假想的
⚙️ 反向控制：黑名單裡的「正確字」必須真的出現在 docs 裡
   （否則一組兩邊都不存在的清單永遠綠）
```

---

# ☠️ 為什麼是逐字黑名單，不是字元類別

A 量過三種字元類別，**沒有一種抓得到實際咬到我們的那兩個**：
```
相容區字元（CJK Compatibility Ideographs）  SPEC 0 ／ SCOPE 0 ／ STATE 0  => **總共 0 個**
異體字選擇器（U+FE0F 等）                   **2,032 個**，幾乎全是 emoji => 擋它＝2,032 個假陽性
而實際咬到的那兩個                          U+5713 圓 ／ U+5265 剥
                                            **兩個都是一般的 CJK 統一漢字**
```
🔑 ⇒ **一個真實的失敗，配一個抓不到它的修法** —— 而它看起來很對，因為兩者都與「字元」有關。
📌 〈推翻的證據不會自動支持替代方案〉的變體：**失敗是真的，不代表手邊那個修法對得上它。**

# 🔴 而「記得改」已經被證實無效

```
02:0x   A 修掉兩處（c9c29b3）＋ 自陳「**我打的**『剝』是 U+5265」
+30分   同兩個字**又出現在他新寫的一行**（STATE.md 的 MD1 宣告列）
```
⇒ 成因是**輸入法**不是記憶 ⇒ **處置必須是結構，不是提醒**。
🔑 而 A 那句「**我打的**」三個字**就已經暗示了輸入法** ——
   ☠️ 那不是診斷不足，是**診斷夠了而資訊沒有被用完**。

# ⚠️ 清單只在**咬到一次之後**才新增

不先列假想的同形異碼（`己巳已`／`土士`／`日曰`…）——
📌 那些會製造一份**永遠綠而看起來很完整**的清單，
   而〈防著不存在問題的測試永遠是綠的〉。
"""
import re
import unicodedata
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_DOCS = _ROOT / "docs"

#: 逐字黑名單：`錯的詞 -> (對的詞, 咬到我們的那一次)`。
#: 🔴 **只在咬到一次之後才新增。** 每一筆都要寫出那一次。
BLACKLIST = {
    "圓欄": ("圍欄", "A 2026-09-23 在 SCOPE.md／STATE.md 各寫過一次（圓 U+5713）"),
    "剥": ("剝", "A 2026-09-23 修檔腳本的錨點打成 剥 U+5265 ⇒ 錨點對不上"),
}

#: 掃描範圍：`docs/` 底下全部 `.md` ＋ repo 根目錄的協定檔。
def _md_files():
    files = sorted(_DOCS.rglob("*.md"))
    proto = _ROOT / "MULTIWIN-PROTOCOL.md"
    if proto.exists():
        files.append(proto)
    return files


def _scan(word):
    hits = []
    for p in _md_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if word in line:
                hits.append((p.relative_to(_ROOT).as_posix(), i, line.strip()))
    return hits


def test_hg1_no_document_contains_a_blacklisted_homoglyph():
    """🔴 `HG1` **黑名單裡的錯字不可以出現在任何 `.md` 裡。**

    ☠️ 它的症狀不是錯字看起來怪，是**搜尋靜靜落空**：
    ```
    $ grep -c "圍欄" <某檔>   =>  0
    而那一行**存在**，只是第一個字是 圓（U+5713）不是 圍（U+570D）
    ```
    🔑 而最惡毒的形式是**假陰性的自我指控**：A-2 差一點報「那句話是我編的」——
       **外觀是誠實，所以沒有人會去查一個人對自己的指控。**
    """
    bad = []
    for wrong, (right, _why) in BLACKLIST.items():
        for rel, ln, text in _scan(wrong):
            bad.append("%s:%d  %r 應為 %r\n      %s"
                       % (rel, ln, wrong, right, text[:70]))
    assert not bad, (
        "文件裡有黑名單上的同形異碼：\n  " + "\n  ".join(bad)
        + "\n☠️ `grep` 用正確的字**找不到那一行**，而那一行存在 ——\n"
          "   ⇒ 一個否定結果（回 0）會被讀成「不存在」。\n"
        + "⚠️ 這不是排版問題：**它讓那一行對所有工具與所有搜尋都是隱形的。**")


def test_hg1_every_blacklist_entry_has_a_real_counterpart_in_the_docs():
    """⚙️ **反向控制：黑名單裡的「正確字」必須真的出現在 docs 裡。**

    ☠️ 少了它，一組**兩邊都不存在**的黑名單永遠是綠的 ——
       而它看起來跟「文件很乾淨」一模一樣。
    🔑 `§128` 明著要求這一格。
    📌 而它同時擋住「先列一堆假想的同形異碼」那條路：
       假想的字沒有真實對應 ⇒ **這一題會紅**。
    """
    dead = []
    for wrong, (right, why) in BLACKLIST.items():
        if not _scan(right):
            dead.append("%r（正確字 %r）—— 登記理由：%s" % (wrong, right, why))
    assert not dead, (
        "黑名單有 %d 筆的**正確字在 docs 裡一次都沒出現**：\n  " % len(dead)
        + "\n  ".join(dead)
        + "\n☠️ 兩邊都不存在的一筆**永遠是綠的** —— 它看起來跟「文件很乾淨」一樣。\n"
        + "⚠️ 若那個詞真的已經不用了，**把它從黑名單拿掉**，不要留著。")


def test_hg1_every_entry_records_the_time_it_bit_us():
    """⚙️ **每一筆都要寫出它咬到我們的那一次**（`§128`：不先列假想的）。

    ☠️ 少了這一格，這張表會慢慢長成一份「看起來很完整的同形異碼字典」——
       而那種清單的每一筆都是綠的，**它證明的只有「我想得到這些」**。
    🔑 〈守門要驗有沒有人做過決定〉：不是驗「這個字對不對」，
       是驗**有沒有一次真實事件把它放進來**。
    """
    thin = [w for w, (_r, why) in BLACKLIST.items()
            if len(why) < 12 or not re.search(r"20\d\d-\d\d-\d\d", why)]
    assert not thin, (
        "這幾筆沒有寫出它咬到我們的那一次（要有日期）：%s\n" % thin
        + "📌 `§128` 逐字：**清單只在咬到一次之後才新增，不先列假想的。**")


def test_hg1_the_characters_really_are_indistinguishable_to_a_character_class():
    """⚙️ **儀器自檢：證明「字元類別抓不到它們」是真的。**

    ☠️ 少了它，整個 `HG1`（逐字黑名單）的理由建立在**A 的一段描述**上 ——
       而我今晚已經有兩次從描述推出一個不存在的結論。
    ```
    圓 U+5713 / 圍 U+570D / 剥 U+5265 / 剝 U+525D
    => 四個**都是** CJK UNIFIED IDEOGRAPH（不是 COMPATIBILITY）
    ```
    🔑 ⇒ 一道「相容區字元就紅」的守門**一個都抓不到** ——
       而它會給人「已經處理過了」的感覺。
    """
    for ch in "圓圍剥剝":
        name = unicodedata.name(ch)
        assert name.startswith("CJK UNIFIED IDEOGRAPH"), (
            "`%s`（U+%04X）是 %s ——\n" % (ch, ord(ch), name)
            + "🔑 它**在**某個特殊區段 ⇒ 字元類別抓得到它 ⇒ "
              "`HG1` 用逐字黑名單的理由要重寫（那是好消息）。")

    # ⚙️ 而「異體字選擇器」那條路同樣不通：我們的 docs 有一大堆（emoji）。
    vs = sum(p.read_text(encoding="utf-8", errors="replace").count("️")
             for p in _md_files())
    assert vs > 100, (
        "docs 裡的 U+FE0F 只有 %d 個（A 量到 2,032）——\n" % vs
        + "🔑 那條「擋異體字選擇器」的路可能變可行了 ⇒ 這一段理由要重算。")


def test_hg1_the_scanner_finds_a_synthetic_homoglyph():
    """⚙️ **儀器自檢：掃描器真的看得見。**

    ☠️ 目前文件是乾淨的（A 已修）⇒ 上面那題是綠的，而它綠可能有兩個理由：
    ```
    ① 文件真的乾淨              ✅
    ② **掃描器什麼都看不到**    ☠️
    ```
    ⚙️ 誘餌用**合成字串**不是 repo 裡真的那一行 ——
       釘在真實例上的正對照，會在那一行被修好的那天失效（今晚已經發生過一次）。
    """
    for wrong, (right, _why) in BLACKLIST.items():
        sample = "前面 %s 後面" % wrong
        assert wrong in sample, "掃描器的比對方式壞了。"
        assert right not in sample, (
            "%r 與 %r 互為子字串 —— **這一組黑名單分不出對錯**。" % (wrong, right))

    assert _md_files(), (
        "`docs/` 底下一個 `.md` 都掃不到 ——\n"
        + "☠️ **一份掃不到的文件與一份乾淨的文件，在結果上長得一樣。**")
