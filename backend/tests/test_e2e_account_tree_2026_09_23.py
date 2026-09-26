# -*- coding: utf-8 -*-
"""瀏覽器端對端：**會計科目樹頁面真的載得起來**。

反面思考那一輪找到的（A `§145` 指定的打包前步驟）：

```
FN1 我出了 10 題、B 全綠、我還跑了突變 13/13
而那 10 題**全部只讀文字**（HTML／JS 當字串 grep、DB 當資料查）
⇒ **沒有任何一題載入過那個頁面**
```

# 🔴 而這不是假想的缺口 —— **它已經發生過一次**

```
B 寫 localStorage.getItem('token')（全站其他 8 支都是 motrix_session）
=> getItem 回 null => 送出 `Bearer ` => **401** => 頁面一片空白
=> 而我那 10 題**全部是綠的**，包括我特地補的「HTTP 層」那一題
   （它自己帶 token 打 API => 200 => **證明的是端點，不是頁面**）
=> ⇒ 是**使用者**撞到的
```
🔑 〈證據的適用範圍〉：**綠燈是真的，而它證明的是另一件事。**

# ⚙️ 而靜態那一層我另外量過，它是乾淨的

```
node --check frontend/js/account-items.js        OK
Alpine 綁定的識別字全部解析得到               未解析 **0** 個
⚙️ 正對照（合成突變）：綁一個不存在的屬性／呼叫不存在的方法 ⇒ **都抓得到**
```
📌 ⇒ 缺的不是「再多一道靜態檢查」，**缺的是有人把它跑起來** ——
   而 `init()` 裡的 401 這種錯，靜態分析**結構上看不到**。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')




def _login(page, base_url, username, password):
    inject_login(page, base_url, username, password)


@pytest.mark.e2e
def test_the_account_tree_page_actually_renders_rows(live_server, make_user, e2e_browser):
    """🔴 **開起來要看得到科目** —— 而且不可以有 401 或 console 錯誤。

    ⚙️ 三個觀測點，各自擋不同的失敗：
    ```
    ① 網路層  任何一個 4xx/5xx  => **401 那次就是這一格抓得到的**
    ② console 任何 pageerror    => init() 裡丟例外 => 畫面空白而沒有訊息
    ③ 畫面    真的有科目列       => 前兩格都過而清單是空的（樹建壞了）
    ```
    🔑 ③ 不可省：`loadError || '載入中…'` 那個退路會讓**空白畫面看起來像正常**。
    """
    username, password = make_user(username="e2e_acct", role="superadmin")
    bad_responses, page_errors = [], []

    browser = e2e_browser
    page = browser.new_page()
    page.on("response", lambda r: bad_responses.append(
        (r.status, r.url)) if r.status >= 400 else None)
    page.on("pageerror", lambda e: page_errors.append(str(e)))

    _login(page, live_server, username, password)
    bad_responses.clear()          # 只看科目樹那一頁的請求
    page.goto(f"{live_server}/pages/account-items.html")
    page.wait_for_timeout(2500)

    rows = page.locator(".ai-row")
    count = rows.count()
    body = page.locator("body").inner_text()[:200]

    assert not bad_responses, (
        "開科目樹頁時有請求失敗：%s\n" % bad_responses[:4]
        + "☠️ **401 那一次就是這一格** —— 頁面一片空白，"
          "而所有只讀文字的測試都是綠的。")
    assert not page_errors, (
        "頁面丟了例外：%s\n" % page_errors[:3]
        + "☠️ `init()` 裡丟例外 ⇒ 畫面空白**而沒有任何訊息**。")
    assert count > 0, (
        "頁面載起來了、沒有錯誤，**而一列科目都沒有**。畫面上是：\n  %s\n" % body
        + "☠️ `loadError || '載入中…'` 那個退路會讓空白畫面**看起來像正常**。\n"
        + "⚠️ 若 `.ai-row` 這個 class 換了名字 **退回給我**。")


@pytest.mark.e2e
def test_the_statutory_lock_is_visible_on_the_page(live_server, make_user, e2e_browser):
    """🔴 **法定科目的「唯讀」要在畫面上真的看得到。**

    ☠️ 我的 `FN1②` 是**讀 HTML 字串**找 `x-show` 綁定 ——
       它證明「那段標記寫對了」，**證明不了它會顯示出來**：
    ```
    綁定寫對了 而 row.source 沒有從 API 回來 => x-show 永遠 false
    => **一個鎖都不會顯示**，而我的靜態題全綠
    ```
    🔑 〈缺欄位≠缺訊號〉的反面：**標記在、資料不在，畫面上什麼都沒有。**
    """
    username, password = make_user(username="e2e_acct2", role="superadmin")
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/account-items.html")
    page.wait_for_timeout(2500)
    locks = page.locator(".ai-lock").count()
    rows = page.locator(".ai-row").count()

    assert rows > 0, "一列科目都沒有 —— 見上一題。"
    assert locks > 0, (
        "畫面上 %d 列科目，而**一個「🔒 唯讀」都沒有顯示**。\n" % rows
        + "☠️ 法定的 547 筆都是 `source='statutory'` ⇒ 它們**全部**該顯示鎖。\n"
        + "🔑 最可能的成因是 `row.source` 沒有從 API 回來 ——\n"
          "   而那樣「綁定寫對了」與「鎖顯示得出來」是兩件事，\n"
          "   **我的靜態題只證明得了前者**。")
