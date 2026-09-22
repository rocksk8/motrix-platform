# -*- coding: utf-8 -*-
"""頁面載了 `sidebar.js`，就必須載它依賴的那幾支。

反面思考那一輪找到的（A `§145` 指定的打包前步驟）。

---

# 🔴 怎麼找到的：**先讓瀏覽器真的打開一次新頁面**

```
我對 account-items.html 補了一支 e2e（它是今晚唯一一個沒有任何 e2e 的新頁）
=> page.on("pageerror") 抓到：
     globalSearchStore is not defined
     loading is not defined / results is not defined（同一個元件的後續）
=> 而**科目列照樣渲染** ⇒ 畫面看起來完全正常
```

# 📏 而它不是新缺陷 —— **2 頁**，其中 **1 頁是既有已出貨的**

```
sidebar.js:196  buildGlobalSearch()  x-data="globalSearchStore()"   ← 無條件輸出
sidebar.js:377  通知鈴鐺            x-data="notifStore()"           ← 無條件輸出
兩者都定義在    static/notif.js（:401 / :29）

載 sidebar.js 而**沒載 notif.js** 的頁：**2 頁**
   account-items.html   ← 今晚新增
   cashier.html         ← **既有，已出貨**
```
### ☠️ 而我第一次數成 **4 頁** —— 我自己的判準太寬
```
我用   grep -q "sidebar.js" <檔>        <= 字串出現在**任何地方**就算
實際   receivables.html:16 ／ sales-orders.html:22
       那兩行是**註解**：「`sidebar.js` 找不到掛載點又沒有這個宣告時會 console.error」
⇒ 那兩頁**根本沒有載 sidebar.js** ⇒ 它們沒有這個問題
```
🔑 〈判準的寬窄都會騙人〉：我差一點報「**三頁既有已出貨的**」，
   而實際是**一頁**。⇒ 守門用 `<script src>` 解析，不用字串包含。
☠️ 症狀：**全域搜尋框與通知鈴鐺都是死的**，而頁面其餘部分完全正常
   ⇒ 使用者不會報修「搜尋壞了」，他會以為那個框本來就長那樣。
🔑 **沒有任何一道守門在看它** —— 而 `sidebar.js` 是鎖定檔，
   誰加一個新元件進去，這兩頁就多壞一個。
"""
import re
from pathlib import Path

import pytest

_FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
_PAGES = _FRONTEND / "pages"
_STATIC = _FRONTEND / "static"

#: `sidebar.js` 輸出的標記引用了誰 ⇒ 誰定義它。
#: ⚠️ 這張表**不是我列的**，是下面那題從原始碼算出來的 —— 這裡只放「它住在哪」。
PROVIDERS = {
    "globalSearchStore": "notif.js",
    "notifStore": "notif.js",
}


def _page_scripts(html):
    return set(re.findall(r'<script[^>]+src="[^"]*?/([\w.-]+\.js)"', html))


def _sidebar_factories():
    """`sidebar.js` 輸出的標記裡，`x-data="xxx()"` 引用了哪些工廠函式。"""
    src = (_STATIC / "sidebar.js").read_text(encoding="utf-8")
    return set(re.findall(r'x-data=\\?"([A-Za-z_$][\w$]*)\(\)', src))


def test_the_sidebar_really_emits_those_component_factories():
    """⚙️ **這張依賴表不是我列的** —— 它是從 `sidebar.js` 算出來的。

    ☠️ 手列的依賴表會爛掉：有人在 `sidebar.js` 加一個新元件，
       **而那張表不會跟著長** ⇒ 下一次同樣的缺陷不會被抓到。
    🔑 ⇒ 這一題把「有哪些依賴」變成**量出來的**，而 `PROVIDERS` 只回答
       「它住在哪一支檔」。
    """
    factories = _sidebar_factories()
    assert factories, (
        "`sidebar.js` 裡抓不到任何 `x-data=\"xxx()\"` ——\n"
        + "☠️ **儀器失效** ⇒ 下面那題會為了錯的理由綠。")
    unknown = sorted(factories - set(PROVIDERS))
    assert not unknown, (
        "`sidebar.js` 多了我不知道住在哪的元件：%s\n" % unknown
        + "⇒ 查它定義在哪一支 `static/*.js`，加進 `PROVIDERS`。\n"
        + "🔑 **這一格就是防這張表爛掉的** —— 加新元件時它會紅。")
    stale = sorted(set(PROVIDERS) - factories)
    assert not stale, (
        "`PROVIDERS` 有 %s 已經不在 `sidebar.js` 裡了 —— 把它們拿掉。" % stale)


def test_every_page_with_a_sidebar_loads_what_the_sidebar_needs():
    """🔴 **載了 `sidebar.js` 就必須載 `notif.js`。**

    ```
    現況（守門量的）  **2 頁**缺：account-items（今晚新增）／cashier（**既有已出貨**）
    症狀              全域搜尋框與通知鈴鐺**都是死的**，而頁面其餘部分完全正常
    ```
    ⚠️ 我第一次用 `grep -q` 數成 4 頁 —— 另外兩頁只是在**註解裡提到** `sidebar.js`。
       ⇒ 本題用 `<script src>` 解析，不用字串包含（見檔頭）。
    ☠️ 使用者不會報修「搜尋壞了」—— **他會以為那個框本來就長那樣。**
    🔑 而它是**瀏覽器打開才看得到**的：`pageerror` 有，而畫面沒有任何症狀。
       ⇒ 我今晚所有只讀文字的題，一個都抓不到它。
    """
    need = {PROVIDERS[f] for f in _sidebar_factories()}
    bad = []
    for p in sorted(_PAGES.glob("*.html")):
        scripts = _page_scripts(p.read_text(encoding="utf-8"))
        if "sidebar.js" not in scripts:
            continue
        missing = sorted(need - scripts)
        if missing:
            bad.append("%s 缺 %s" % (p.name, missing))
    assert not bad, (
        "這 %d 頁載了 `sidebar.js` 而沒載它需要的：\n  " % len(bad)
        + "\n  ".join(bad)
        + "\n☠️ 那幾頁的**全域搜尋框與通知鈴鐺是死的** ——\n"
          "   `globalSearchStore is not defined` 丟在 console，\n"
          "   **而畫面其餘部分完全正常** ⇒ 沒有人會報修它。\n"
        + "✅ 在 `sidebar.js` 那一行旁邊加 `<script src=\"../static/notif.js\"></script>`。")


def test_the_scanner_sees_a_page_that_is_missing_one():
    """⚙️ **儀器自檢：合成一頁缺依賴的，必須被抓到。**

    ☠️ 上一題修好之後會變成 0 命中 ⇒ 而 0 可能是
       「大家都載了」，**也可能是我的 `<script>` 解析壞了**。
    ⚙️ 誘餌用合成字串 —— 釘在真實例上的正對照，
       會在那兩頁被修好的那天失效（今晚已經發生過一次）。
    """
    ok_page = ('<script src="../static/notif.js"></script>'
               '<script src="../static/sidebar.js"></script>')
    bad_page = '<script src="../static/sidebar.js"></script>'
    assert _page_scripts(ok_page) == {"notif.js", "sidebar.js"}, (
        "解析器讀不出 `<script src>` —— **儀器壞了**：%r"
        % _page_scripts(ok_page))
    assert _page_scripts(bad_page) == {"sidebar.js"}, (
        "解析器在只有 sidebar 的那一頁上也認出 notif —— **它什麼都會說有**。")
