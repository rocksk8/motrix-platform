# -*- coding: utf-8 -*-
"""`JV7` 的**核心不變量**，只有瀏覽器量得到（A `§164`）。

```
帶入 -> 使用者改過 -> **重新整理／換頁籤回來 -> 不可以被蓋回去**
```
🔑 使用者逐字：「也可以手動填寫或修改摘要」。
☠️ 最容易寫錯的實作是「**切頁籤時重新帶入**」——
   它看起來像功能正常（點哪個頁籤就帶哪個，很合理），
   而使用者打完字去看一眼附件清單、切回來，**他打的字沒了**。

# 🔴 為什麼這一題不能寫成靜態檢查

```
靜態能看到  「有沒有呼叫帶入函式」
靜態看不到  「呼叫的時候使用者改過沒有」
```
⇒ 那個條件在**執行期**才存在 ⇒ 只有真的打字、真的切頁籤才量得到。
📌 同一個道理讓 `FN1` 那 10 題全綠而使用者撞到空白頁
   （`test_e2e_account_tree_2026_09_23.py` 的開頭記著那件事）。

# ⚙️ 反向控制（B 交件後由我在第 ⑤ 步跑，不是這裡）

```
把「切頁籤重新帶入」故意接回去 => 下面那一題**必須紅**
紅不起來 => 我這一題在量別的東西
```

---

# ⚠️ `HOOKS` 是我**單方面宣告**的測試掛鉤

頁面還不存在，所以選擇器只能由我先定。
**要換名字請退回給我改這張表，不要動我的檔。**
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

#: ⚠️ 我單方面宣告的掛鉤。改名**退回給我**。
HOOKS = {
    "tabs": '[data-testid="summary-source-tabs"]',
    "tab": '[data-testid="summary-source-tab"]',
    "item": '[data-testid="summary-source-item"]',
    "summary": 'input[x-model="l.summary"]',
}

#: `§159b` 的兩個頁籤。
TABS = ("案件", "已上傳檔案")

#: 使用者手打的那一段——`§164` 說「事由」**沒有來源可以帶**，一定要手打。
TYPED = "工資"


@pytest.fixture()
def live_server(client):
    """比照 `test_e2e_account_tree_2026_09_23.py` 的同名 fixture。"""
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
        yield "http://127.0.0.1:%d" % port
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _login(page, base_url, username, password):
    page.goto("%s/pages/login.html" % base_url)
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)


def _seed_case(quote_no="MQ-202608-009", customer="京城凱悅"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, data_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "已結案", customer, "測試案", 1000, 952, "{}",
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _need(page, selector, what):
    """看不到就**明著說是哪一個掛鉤不見了**，不要讓 timeout 變成謎題。"""
    loc = page.locator(selector)
    if loc.count() == 0:
        body = page.locator("body").inner_text()[:300]
        pytest.fail(
            "頁面上找不到%s（`%s`）。\n" % (what, selector)
            + "📌 掛鉤名是我在 `HOOKS` 裡單方面定的，**要換退回給我**。\n"
            + "畫面上是：\n  %s" % body)
    return loc


@pytest.mark.e2e
def test_jv7_an_edited_summary_survives_a_tab_switch(live_server, make_user):
    """🔴 **改過的摘要，切頁籤回來不可以被蓋回去。**（`§164` 的不變量）

    ```
    ① 頁籤「案件」 -> 點一筆     => 摘要被帶入
    ② 使用者在後面**自己打字**   => §164：「事由」沒有來源，一定要手打
    ③ 切到「已上傳檔案」再切回來
    ④ 摘要**仍然是 ② 打完的那個值**
    ```
    ☠️ 寫錯的樣子：切頁籤時重新帶入 ⇒ ② 打的字沒了，
       **而畫面上一切正常** —— 使用者只會覺得「我剛剛好像打過」。
    """
    username, password = make_user(username="e2e_jv7", role="superadmin",
                                   modules=["cashier"])
    _seed_case()
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        _login(page, live_server, username, password)
        page.goto("%s/pages/voucher.html" % live_server)
        page.wait_for_timeout(2000)

        _need(page, HOOKS["tabs"], "摘要來源的分頁選單")
        tab_case = _need(page,
                         '%s:has-text("案件")' % HOOKS["tab"], "「案件」頁籤")
        tab_file = _need(page,
                         '%s:has-text("已上傳檔案")' % HOOKS["tab"],
                         "「已上傳檔案」頁籤")

        tab_case.first.click()
        page.wait_for_timeout(500)
        _need(page, HOOKS["item"], "案件來源的清單").first.click()
        page.wait_for_timeout(300)

        box = _need(page, HOOKS["summary"], "分錄行的摘要欄").first
        brought_in = box.input_value()

        # ② 使用者自己續打（`§164`：事由沒有來源可以帶）
        box.click()
        box.fill(brought_in + TYPED)
        edited = box.input_value()

        # ③ 切走再切回來
        tab_file.first.click()
        page.wait_for_timeout(300)
        tab_case.first.click()
        page.wait_for_timeout(500)

        after = box.input_value()
        browser.close()

    assert not page_errors, (
        "頁面丟了例外：%s\n" % page_errors[:3]
        + "⚠️ 先修這個 —— 例外之後量到的值不算數。")
    assert brought_in.strip(), (
        "點了案件來源而摘要欄**是空的** ——\n"
        + "☠️ 頁籤點得動、清單列得出來，**而帶入那一步沒接上**。")
    assert TYPED in edited, (
        "我打完字之後讀回來是 %r，裡面沒有我打的 %r ——\n" % (edited, TYPED)
        + "☠️ 摘要欄**打不動**（`§164`：帶入後不可以把欄位鎖起來）。")
    assert after == edited, (
        "切頁籤回來之後摘要被蓋掉了：\n"
        "  我打完是  %r\n"
        "  切回來變  %r\n" % (edited, after)
        + "☠️ 那是「**切頁籤時重新帶入**」—— 它看起來像功能正常，\n"
          "   而使用者去看一眼附件清單再切回來，**他打的字沒了**。\n"
        + "🔑 `§164`：帶入是**起點不是終點**。")


@pytest.mark.e2e
def test_jv7_an_edited_summary_survives_a_reload(live_server, make_user):
    """🔴 **改過的摘要，存檔後重新整理不可以被蓋回去。**

    ⚠️ 與上一題是**兩種不同的失效**，不可以只做一個：
    ```
    切頁籤被蓋  => 帶入函式綁在頁籤切換上（前端的事）
    重整被蓋    => 存的是**來源 id**、開啟時再組一次（後端也有份）
    ```
    ☠️ 後者更難發現：使用者改完、存檔、關掉；**下次打開才變回來** ——
       中間隔了幾天，他不會把兩件事連起來。
    """
    username, password = make_user(username="e2e_jv7b", role="superadmin",
                                   modules=["cashier"])
    _seed_case(quote_no="MQ-202608-010", customer="向量圓專")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        _login(page, live_server, username, password)
        page.goto("%s/pages/voucher.html" % live_server)
        page.wait_for_timeout(2000)

        _need(page, HOOKS["tabs"], "摘要來源的分頁選單")
        _need(page, '%s:has-text("案件")' % HOOKS["tab"],
              "「案件」頁籤").first.click()
        page.wait_for_timeout(500)
        _need(page, HOOKS["item"], "案件來源的清單").first.click()
        page.wait_for_timeout(300)

        box = _need(page, HOOKS["summary"], "分錄行的摘要欄").first
        box.fill(box.input_value() + TYPED)
        edited = box.input_value()

        save = page.locator('button:has-text("儲存")')
        if save.count() == 0:
            browser.close()
            pytest.fail("頁面上找不到「儲存」—— 摘要改了**存不下去**。")
        save.first.click()
        page.wait_for_timeout(1200)

        page.reload()
        page.wait_for_timeout(2000)
        after = _need(page, HOOKS["summary"], "分錄行的摘要欄").first.input_value()
        browser.close()

    assert after == edited, (
        "重新整理之後摘要變回帶入時的樣子：\n"
        "  存檔前  %r\n"
        "  重整後  %r\n" % (edited, after)
        + "☠️ 存的是**來源 id**、開啟時再組一次 ⇒ 使用者改的東西沒有被存下來。\n"
        + "🔑 `§164`：帶入只是**省打字**，最終值是使用者打的那個。")
