# -*- coding: utf-8 -*-
"""`QL24` · 據點「單據抬頭與匯款帳號」那一區，一律預設展開。

使用者裁定：「一律預設展開」。

# 🔴 現況（實查，`company-profile-settings.html`，`grep` 字串比行號可靠）

```js
// _toRow() 結尾：
row._open = this.LOC_IDENTITY_FIELDS.some(k => row[k])
```

```
已填過的  -> 展開   （已經知道它在哪的人，看得到）
沒填過的  -> 收起   （**正在找它的人，看不到**）
```
⇒ 使用者反映「沒有對應的地方設定各據點的抬頭、統編、匯款帳號」——
   而**欄位一直都在**（`QL11`／`QL12` 就做完了），是**入口看不見**。
📌 〈缺欄位≠缺訊號〉的 UI 版：功能存在，而使用者的描述是對的。

# ⚙️ 觀測點：`_toRow()` 回傳的 `_open`，不是 markup

```
☠️ 釘 `x-show="loc._open"` 這個字串存不存在，證明不了預設值是什麼
   —— 那是 Alpine 的**執行期狀態**，不是靜態字串（〈假綠燈〉的一種）。
⇒ 用 Playwright 直接呼叫 `_toRow()`（照抄 `test_e2e_copy_to_new` 直接
   呼叫元件方法的做法），驗它回傳的物件，不掃原始碼字串。
```

# ⚠️ 對照組要留，且要與核心題分開驗證

`_open` 從 `some(...)` 改成字面 `true` 之後，①②兩題都會綠——分不出
「改對了」與「改成常數把摺疊拿掉了」。⇒ ③（手動收起來仍然要能收）
是那個對照組，**單獨跑一次確認它今天是綠的**：一個「一律預設展開」的
正確實作，不等於「拿掉可以收起來這件事」，這是兩個不同的需求。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port


@pytest.fixture()
def live_server(client):
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1",
                            port=free_safe_port(), log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("uvicorn 測試伺服器在時限內沒有啟動")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _login(page, base_url, username, password):
    page.goto(f"{base_url}/pages/login.html")
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)


@pytest.mark.e2e
def test_ql24_an_empty_location_is_open_by_default(live_server, make_user):
    """🔴 **核心：一個欄位都沒填的據點，`_toRow()` 回傳 `_open === true`。**

    ☠️ 這是使用者實際踩到的那一格 —— 正在找抬頭設定入口的人，
       看到的是一個收起來的摺疊區，會以為那裡沒有東西可以設。
    """
    username, password = make_user(username="ql24_empty", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/company-profile-settings.html")
            page.wait_for_function(
                "() => document.querySelector('[x-data]') "
                "&& typeof Alpine.$data(document.querySelector('[x-data]'))"
                "._toRow === 'function'",
                timeout=15000)

            is_open = page.evaluate(
                """() => {
                    const c = Alpine.$data(document.querySelector('[x-data]'))
                    const row = c._toRow({ name: '', address: '' })
                    return row._open
                }""")
            assert is_open is True, (
                "一個欄位都沒填的據點，`_toRow()` 回傳 `_open=%r`（預期 `True`）。\n"
                % is_open
                + "☠️ 正在找抬頭設定入口的人，看到的是一個收起來的摺疊區，\n"
                  "   會以為系統裡沒有這個功能。")
        finally:
            browser.close()


@pytest.mark.e2e
def test_ql24_a_filled_location_stays_open_by_default(live_server, make_user):
    """⚙️ **正對照：已經填過的據點，預設展開的行為不可以被改壞。**

    ☠️ 少了它，一個「一律收起（`_open: false` 字面值）」的實作也可能被誤判
       成部分修好 —— 這一題確保「已填的仍然展開」這個既有正確行為沒有跟著壞掉。
    """
    username, password = make_user(username="ql24_filled", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/company-profile-settings.html")
            page.wait_for_function(
                "() => document.querySelector('[x-data]') "
                "&& typeof Alpine.$data(document.querySelector('[x-data]'))"
                "._toRow === 'function'",
                timeout=15000)

            is_open = page.evaluate(
                """() => {
                    const c = Alpine.$data(document.querySelector('[x-data]'))
                    const row = c._toRow({
                        name: '台北分公司', address: 'x',
                        company_name: 'QL24 已填過的公司名'
                    })
                    return row._open
                }""")
            assert is_open is True, (
                "已經填過抬頭的據點，`_toRow()` 回傳 `_open=%r`（預期 `True`）。"
                % is_open)
        finally:
            browser.close()


@pytest.mark.e2e
def test_ql24_manually_collapsing_it_still_works(live_server, make_user):
    """🔴 **反向控制：手動收起來仍然要能收 —— 不是把摺疊整個拿掉。**

    ## ⚠️ 這是一個必須單獨跑的對照組

    `_open` 從 `some(...)` 改成字面 `true` 之後，上面兩題**都會綠**——
    綠燈分不出「改對了」與「改成常數而把摺疊拿掉了」。
    這一題走**真實的畫面互動**（點擊摺疊標題、看 `x-show` 容器的實際
    可見性），而不是再讀一次 `_open` 的初始值，才擋得住「拿掉摺疊」
    這種改法。
    """
    username, password = make_user(username="ql24_collapse", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            with page.expect_response(
                    lambda r: "/api/settings/company-profile" in r.url
                    and r.request.method == "GET"):
                page.goto(f"{live_server}/pages/company-profile-settings.html")
            page.wait_for_function(
                "() => document.querySelector('[x-data]') "
                "&& typeof Alpine.$data(document.querySelector('[x-data]'))"
                "._toRow === 'function'",
                timeout=15000)
            # 🔴 2026-09-24 更正（hichan-8d 讀碼）：`expect_response` 等到的是「回應抵達」，
            #    而 `init()` 還要 `await r.json()` 之後才寫 `this.locations` ——
            #    在這個空檔覆寫 `locations` 會被蓋回去（全量時偶發紅、逾時在找標題）。
            #    ⇒ 等 `init()` 真的把回應寫進去：`cfg` 初始沒有 `locations` 鍵，
            #      與 `this.locations` 在**同一段同步程式**裡被寫入（`{...this.cfg, ...data}`）
            #      ⇒ `cfg.locations !== undefined` 成立時 `this.locations` 已經是伺服器的值。
            #    不用固定秒數。
            page.wait_for_function(
                "() => Alpine.$data(document.querySelector('[x-data]')).cfg.locations !== undefined",
                timeout=15000)

            # 🔴 **前一版在這裡有一個真正的 race**：`init()` 是 `async`，
            #    先 fetch 再賦值 `this.locations`。若我在那個 fetch 完成
            #    之前就覆寫 `c.locations`，`init()` 稍後回應抵達時會把
            #    我塞的資料**蓋回伺服器的舊值**——`x-data` 已就緒不等於
            #    非同步 `init()` 已跑完。這不是產品的競態，是我的探針沒等
            #    到位（症狀是「找不到元素」，看起來像元素沒渲染出來）。
            #    ⇒ 用 `expect_response` 等那一次 `GET` 真的回來，
            #      再覆寫 `locations` 才安全。

            # 🔴 **不透過 `_toRow()` 的預設值進場** —— 核心題今天是紅的
            #    （空據點算出 `_open=False`），若這裡也靠 `_toRow()` 給
            #    初始值，這一題會**連坐失敗**在同一個成因上，而它要驗的
            #    是另一件事（手動摺疊機制本身還動不動）。
            #    ⇒ 直接把 `_open` 設成 `true`，繞過那個還沒修好的計算。
            page.evaluate(
                """() => {
                    const c = Alpine.$data(document.querySelector('[x-data]'))
                    const row = c._toRow({ name: 'QL24 收合測試', address: '' })
                    row._open = true
                    c.locations = [row]
                }""")
            # ⚠️ 固定 `wait_for_timeout` 量到過一次假的「找不到元素」——
            #    `x-for` 換陣列之後的 DOM 更新沒有保證在某個毫秒數內完成。
            #    改成等到那個文字標題真的出現，不要用猜的時間。
            page.wait_for_selector("text=這個據點的單據抬頭與匯款帳號",
                                   timeout=10000)

            body = page.locator('[x-show="loc._open"]').first
            toggle = page.locator("text=這個據點的單據抬頭與匯款帳號").first

            assert body.is_visible(), (
                "把 `_open` 直接設成 `true` 之後，抬頭／帳號那一區**仍然沒有展開**——\n"
                "☠️ 這代表 `x-show=\"loc._open\"` 這個綁定本身壞了，\n"
                "   與『預設值算得對不對』是兩件不同的事，先看這一格。")

            toggle.click()
            page.wait_for_timeout(200)
            assert not body.is_visible(), (
                "點了摺疊標題之後，抬頭／帳號那一區**仍然看得見** ——\n"
                + "☠️ 若 `_open` 被改成字面 `true` 而不是 `some(...)` 算出來的值，\n"
                  "   使用者會永遠收不起這一區。")

            toggle.click()
            page.wait_for_timeout(200)
            assert body.is_visible(), (
                "再點一次收起來的標題，那一區卻**沒有重新展開** ——\n"
                "☠️ 摺疊互動本身壞了，不是預設值的問題。")
        finally:
            browser.close()
