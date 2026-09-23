# -*- coding: utf-8 -*-
"""`EM12` · 存摺／身分證影本上傳失敗被吞掉，畫面看起來一切正常。

A-2 掃出 **兩處逐字同構**（個資，優先）：
```
contractors.html:666        PUT /contractors/{id}/id-card       身分證正反面＋存摺
vendor-contractors.html:779 PUT /vendor-contractors/{id}/passbook  存摺
形狀：save() 先 POST/PUT 廠商本體（有驗 r.ok），
      接著打第二支上傳個資影本的 PUT —— **完全沒接回應**，
      然後不管成敗一律 showModal=false ＋ load()。
```
☠️ 使用者上傳銀行存摺／身分證影本（個資），畫面顯示成功關掉、清單刷新，
   而那張影本**根本沒有存進去** —— 他不會知道要重傳，直到有一天真的要用
   那份資料時才發現是空的。

# ✅ B 已修 `vendor-contractors.html`（`b349ee7`），`contractors.html` 另外派工中

⇒ 本檔兩支頁面都要有題（它們是複製碼，只測一支會全綠）：
```
vendor-contractors  已修  ⇒ 這裡的題**今天應該是綠的**（鎖住修好的狀態）
contractors          未修  ⇒ 這裡的題**今天應該是紅的**（等修）
```

# ⚙️ 觀測點與做法

```
不釘「fetch 被呼叫了幾次」—— 那量不到使用者看到了什麼
釘  失敗時：視窗還開著（showModal===true）
           ＋ 錯誤訊息**看得見**（不是只有狀態有值 —— `§219` 的教訓：
             狀態對了，而顯示它的容器條件與它互斥，使用者一樣看不到）
    正對照：成功時視窗要關（showModal===false）
```
🔑 用 Playwright 直接呼叫 Alpine 元件的 `save()`（照抄
`test_e2e_copy_to_new_2026_09_10.py::copyToNew()` 那個做法），繞過檔案
選取 UI —— 影本內容本身不是這一題要驗的，**回應被怎麼處理才是**。

# ⚠️ 我沒有釘「清單不刷新」

A 的規格寫「(a) 清單不刷新」，而 B 已經出貨的 `vendor-contractors.html`
在失敗分支裡**仍然呼叫了 `this.load()`**（見該檔 `save()`，`pr.ok` 為假
時的分支）。第一支 PUT（廠商本體）已經成功、資料真的變了，重新整理清單
反映那個事實不算錯 —— 而模態視窗沒有關、錯誤訊息看得見，已經達成「使用者
不會誤以為存摺存進去了」這個目的。⇒ 這裡不對「清單有沒有刷新」下判斷，
只釘「視窗有沒有關」與「訊息看不看得見」。**若這不是 A 要的，請回覆改題。**
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


#: 兩支複製碼，逐字同構。`route_glob` 只框住**第二支**（個資影本）PUT，
#: 不可以連第一支（廠商本體）都攔到，否則 `targetId` 永遠拿不到，
#: 那樣紅的是我的前置，不是受測的那個 PUT。
PAGES = [
    pytest.param(
        "contractors.html", "**/api/contractors/*/id-card",
        {"name": "EM12 承攬商"},
        id="contractors(未修-應為紅)"),
    pytest.param(
        "vendor-contractors.html", "**/api/vendor-contractors/*/passbook",
        {"name": "EM12 廠商"},
        id="vendor-contractors(已修-應為綠)"),
]


def _run_save(page, live_server, username, password, page_file, form,
             fail_route):
    """開頁、（可選）攔截個資影本那支 PUT、直接呼叫 `save()`。

    ⚠️ 用 `page.evaluate` 直接改元件狀態＋呼叫 `save()`，不點檔案選取器
       ——照抄 `test_e2e_copy_to_new` 的做法：影本內容不是這一題要驗的。
    """
    _login(page, live_server, username, password)
    if fail_route is not None:
        page.route(fail_route,
                  lambda route: route.fulfill(
                      status=500, content_type="application/json",
                      body='{"detail":"磁碟空間不足"}'))
    page.goto(f"{live_server}/pages/{page_file}")
    page.wait_for_function(
        "() => document.querySelector('[x-data]') "
        "&& Alpine.$data(document.querySelector('[x-data]')).init !== undefined",
        timeout=15000)

    result = page.evaluate(
        """async (form) => {
            const c = Alpine.$data(document.querySelector('[x-data]'))
            c.form = form
            c.bankPassbookPreview = 'data:image/png;base64,AAAA'
            c.showModal = true
            c.editId = null
            await c.save()
            return { showModal: c.showModal, errMsg: c.errMsg }
        }""", form)
    return result


@pytest.mark.e2e
@pytest.mark.parametrize("page_file, route_glob, form", PAGES)
def test_em12_a_failed_pii_upload_keeps_the_modal_open_and_visible(
        live_server, make_user, page_file, route_glob, form):
    """🔴 **個資影本那支 PUT 失敗 ⇒ 視窗不關，錯誤訊息看得見。**

    ```
    contractors.html         今天應該是紅的（未修：完全不接回應）
    vendor-contractors.html  今天應該是綠的（B 已修 b349ee7）
    ```
    """
    username, password = make_user(username="em12_" + page_file.split(".")[0],
                                   role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            result = _run_save(page, live_server, username, password,
                              page_file, form, route_glob)

            assert result["showModal"] is True, (
                "%s：個資影本上傳失敗，而視窗關掉了（showModal=%r）。\n"
                % (page_file, result["showModal"])
                + "☠️ 使用者看到「存好了」的樣子，實際上那份個資影本\n"
                  "   （銀行存摺／身分證）**沒有存進去**。")

            assert (result.get("errMsg") or "").strip(), (
                "%s：視窗沒關，而 `errMsg` 是空的 —— 使用者看到一個\n"
                "什麼都沒說的視窗，不知道剛剛發生了什麼。" % page_file)

            # 🔑 `§219`：狀態有值不等於看得見 —— 錯誤訊息所在的 DOM
            #    可能被包在一個「出錯時剛好也會隱藏」的容器裡。實際渲染
            #    出來看一次，不要只信 Alpine 元件內部狀態。
            err_locator = page.locator('[x-show="errMsg"]')
            assert err_locator.count() > 0, (
                "%s：頁面上找不到 `x-show=\"errMsg\"` 這個容器 ——\n"
                "改了實作方式的話，退回給我改觀測點。" % page_file)
            assert err_locator.first.is_visible(), (
                "%s：`errMsg` 有值，而它的容器在畫面上**看不見** ——\n"
                % page_file
                + "☠️ 狀態對了，顯示它的容器條件卻與它互斥（`§219` 同一種病：\n"
                  "   使用者一個字都看不到，比看到一句假話更難查）。")
        finally:
            browser.close()


@pytest.mark.e2e
@pytest.mark.parametrize("page_file, route_glob, form", PAGES)
def test_em12_a_successful_pii_upload_still_closes_the_modal(
        live_server, make_user, page_file, route_glob, form):
    """⚙️ **正對照：個資影本上傳成功時，視窗要關。**

    ☠️ 少了它，一個「不管成敗一律不關視窗」的實作也會讓上一題綠，
       而那時**每一次正常存檔使用者都要多按一次關閉**。
    """
    username, password = make_user(
        username="em12ok_" + page_file.split(".")[0], role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            result = _run_save(page, live_server, username, password,
                              page_file, form, fail_route=None)
            assert result["showModal"] is False, (
                "%s：個資影本上傳**成功**，而視窗還開著（showModal=%r）——\n"
                % (page_file, result["showModal"])
                + "☠️ 正常存檔的話，使用者每次都要多按一次「取消」才能關掉。")
        finally:
            browser.close()
