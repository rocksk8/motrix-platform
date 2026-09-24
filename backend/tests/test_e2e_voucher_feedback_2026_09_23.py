# -*- coding: utf-8 -*-
"""`AC2` · **會寫入的動作，畫面上要看得到回饋。**（A `§186`）

```
判準   按下之後**畫面上出現一段成功訊息**
       **不是** `actionMsg` 這個變數有沒有被設定
觀測點 **渲染之後畫面上的文字**
```

# ☠️ 為什麼判準要訂在「畫面上」而不是「變數被設定」

B 用瀏覽器探針找到的（`§186`）：
```
三條成功路徑都是「設定 actionMsg -> 重讀這張單」
而 open() 第一件事是 _clearMsg()
⇒ **按下儲存，畫面什麼都不說**
```
🔑 `actionMsg` **有**被設定 —— 只是隨即被清掉。
⇒ 一個驗「變數被設定了」的題**會是綠的**，而使用者看到的是一個沒有回應的按鈕。
☠️ 而那時後端全綠、我那七題也全綠：**每一層都對，而使用者按下去沒反應**。

# ⚙️ 這一題的反向控制長在它自己身上

```
按之前  畫面上**不可以**已經有成功訊息
按之後  要有
```
⇒ 少了前半，一段**常駐**的文字（例如頁面說明）就能讓它永遠綠。
📌 而它擋不到的那一側（`§186` 也寫了）：**訊息出現了而內容是錯的** ——
   「N 個欄位有異動」而 `changed` 含分錄的逐行異動 ⇒ 數字對而名詞錯。
   那一格靠人看，不在本檔。

# ⚠️ 兩個會讓人誤判的陷阱（B 實測）

```
① <template x-for> 留在 DOM 裡，渲染的 <tr> 插在它後面
   ⇒ tr:nth-child(1) **永遠不存在** ⇒ Timeout，而症狀像「頁面沒渲染」
   ⇒ 用 locator(...).nth(i)，不要用 nth-child
② 傳票的動作鈕用 x-show（**元素一直在 DOM 裡**）
   ⇒ 驗「看不看得到」要用 is_visible()，不是 count()
```
📌 `voucher.html` 由 **`cashier`** 模組把關（`sidebar.js:753` 的旗標是 `cCash`，
   `:476` `cCash = has('cashier')`）—— 拿錯模組名的症狀是**被擋在頁面外**，
   而它看起來像權限設計正確地生效了。
"""
import threading
from urllib.parse import urlparse
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._ports import free_safe_port

#: `voucher.html` 的把關模組（實查 `sidebar.js:753`／`:476`）。
VOUCHER_MODULE = "cashier"

#: B 加的掛鉤。
HOOKS = {
    "new": '[data-testid="voucher-new"]',
    "save": '[data-testid="voucher-save"]',
    "submit": '[data-testid="voucher-submit"]',
    "approve": '[data-testid="voucher-approve"]',
    "post": '[data-testid="voucher-post"]',
    "status": '[data-testid="voucher-status"]',
}

#: 成功訊息那一塊（`voucher.html:294-295`：`<template x-if="actionMsg">`）。
OK_MSG = ".vc-ok"
ERR_MSG = ".vc-err"




def _login(page, base_url, username, password):
    page.goto("%s/pages/login.html" % base_url)
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)


# ── 等待（PERF #6，2026-09-25：固定 sleep 換成等可觀測事件）────────────────────────
VC = "Alpine.$data(document.body)"


def _ready(page):
    """頁面可以開始操作：「新增傳票」看得到＋科目選單載完（原本固定等 2 秒）。"""
    page.wait_for_selector(HOOKS["new"], state="visible", timeout=15000)
    page.wait_for_function("() => window.Alpine && %s && %s._accountsLoaded" % (VC, VC), timeout=15000)


def _editor_open(page):
    """按「新增」之後，第一列的科目欄出現（原本固定等 0.8 秒）。"""
    page.locator("table tbody tr").nth(0).locator("input[x-model='l.account_code']").wait_for(
        state="visible", timeout=10000)


def _settled(page, do):
    """做一個寫入動作並等它**整個**做完（原本固定等 2～2.5 秒）。

    可觀測的終點：busy 由 true 回到 false。save()／_act() 都在**第一個 await 之前**同步設 busy=true，
    在 finally 才解除——而 finally 在 `await open(...)`＋`await loadList()` **之後** ⇒ busy 一解除，
    重讀與清單都已經做完；失敗（非 2xx、例外）也一樣走 finally，不會卡住。
    ⚠️ 不可以改成「等成功訊息出現」：這一檔要抓的正是「訊息被隨後的重讀清掉」，等出現會在清掉之前放行（假綠）。
    ☠️ 2026-09-25 更正留著：第一版等的是「GET /api/vouchers 回來」。建包序列跑時送審那一題在那裡逾時 15s
       （單跑綠）——動作的終點是 finally，不是某一趟請求；逾時的時候也說不出卡在哪。改等 busy，
       逾時就把當下狀態與這段期間的 /api/vouchers 請求印出來。"""
    seen = []

    def _rec(r):
        if "/api/vouchers" in r.url:
            seen.append("%s %s %s" % (r.request.method, r.status, urlparse(r.url).path))
    page.on("response", _rec)
    try:
        do()
        try:
            page.wait_for_function("() => { const d = %s; return d && !d.busy }" % VC, timeout=30000)
        except Exception:
            state = page.evaluate("() => { const d = %s; return {busy: d.busy, id: d.id, msg: d.actionMsg, err: d.actionErr} }" % VC)
            raise AssertionError("動作 30 秒內沒有做完（busy 沒有解除）：%r；期間的 /api/vouchers 回應：%r" % (state, seen))
        page.evaluate("() => new Promise(r => Alpine.nextTick(r))")
    finally:
        page.remove_listener("response", _rec)


def _error_shown(page):
    """前端擋下、不送請求的失敗（例如沒有分錄）：等錯誤訊息渲染出來（原本固定等 2 秒）。"""
    page.wait_for_function(
        "() => [...document.querySelectorAll('%s')].some(e => e.offsetParent !== null && e.innerText.trim())" % ERR_MSG,
        timeout=10000)


def _visible_text(page, selector):
    """畫面上**看得到的**那段文字（看不到就回空字串）。

    ⚠️ 不用 `count()`：`x-show` 的元素**一直在 DOM 裡**（B 實測）。
    """
    loc = page.locator(selector)
    for i in range(loc.count()):
        one = loc.nth(i)
        if one.is_visible():
            t = (one.inner_text() or "").strip()
            if t:
                return t
    return ""


def _fill_first_line(page, code="1113", debit="1000"):
    """填第一行分錄。

    ⚠️ **不要用 `tr:nth-child(1)`** —— `<template x-for>` 留在 DOM 裡，
       渲染出來的 `<tr>` 插在它後面 ⇒ 「既是 `tr` 又是第 1 個 child」不存在
       ⇒ `Timeout 30000ms`，而症狀讀起來像「頁面沒渲染」。
    """
    rows = page.locator("table tbody tr")
    assert rows.count() >= 2, (
        "分錄列少於兩列（%d）—— 先看頁面有沒有渲染出來。" % rows.count())
    r0 = rows.nth(0)
    ins = r0.locator("input")
    assert ins.count() >= 2, "第一列的輸入框少於兩個（%d）。" % ins.count()
    # 📌 更正留著（2026-09-24，`JV34`）：原本是 `ins.nth(1).fill(debit)`——第 2 個 input
    #    其實是**科目名稱**，不是借方 ⇒ 這一題一直把 "1000" 填進名稱欄、借方是空的。
    #    `JV34①` 把名稱欄改成唯讀之後這個錯位才浮出來（fill 逾時）。改用 x-model 指名。
    r0.locator("input[x-model='l.account_code']").fill(code)
    r0.locator("input[x-model='l.debit']").fill(debit)


@pytest.mark.e2e
def test_ac2_pressing_save_says_something_on_screen(live_server, make_user, e2e_browser):
    """🔴 **按下儲存之後，畫面上要出現一段成功訊息。**

    ⚙️ 前後各量一次 —— **那就是這一題的反向控制**：
    ```
    按之前  畫面上不可以已經有成功訊息（否則一段常駐文字就能讓它永遠綠）
    按之後  要有
    ```
    ☠️ 而現在的失敗方式很具體：`actionMsg` 被設定了，
       然後 `open()` 的 `_clearMsg()` 把它清掉 ⇒ **畫面什麼都不說**。
    🔑 使用者看到的是一個**沒有回應的按鈕** —— 他會再按一次。
    """
    u, p = make_user(username="e2e_ac2_save", role="superadmin",
                     modules=[VOUCHER_MODULE])
    errors = []

    browser = e2e_browser
    page = browser.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, live_server, u, p)
    page.goto("%s/pages/voucher.html" % live_server)
    _ready(page)

    new_btn = page.locator(HOOKS["new"])
    assert new_btn.count() and new_btn.first.is_visible(), (
        "找不到「新增傳票」（`%s`）。畫面上是：\n  %s"
        % (HOOKS["new"], page.locator("body").inner_text()[:300]))
    new_btn.first.click()
    _editor_open(page)
    _fill_first_line(page)

    before = _visible_text(page, OK_MSG)
    save = page.locator(HOOKS["save"])
    assert save.count() and save.first.is_visible(), (
        "找不到「儲存」（`%s`）。" % HOOKS["save"])
    _settled(page, lambda: save.first.click())

    after = _visible_text(page, OK_MSG)
    err = _visible_text(page, ERR_MSG)

    assert not errors, "頁面丟了例外：%s —— 先修這個。" % errors[:3]
    assert not err, (
        "儲存失敗，畫面上的錯誤是：%r\n" % err
        + "⚠️ 這一題要量的是**成功**那條路 —— 先讓儲存成功。")
    assert before == "", (
        "**還沒按儲存，畫面上就已經有成功訊息了**：%r\n" % before
        + "☠️ 那表示 `%s` 上有一段常駐文字 ⇒ 這一題會永遠綠。\n" % OK_MSG
        + "⚠️ 觀測點選錯了，**退回給我**。")
    assert after, (
        "按下儲存之後，畫面上**什麼都沒說**。\n"
        + "☠️ `actionMsg` **有**被設定 —— 而 `open()` 的 `_clearMsg()`\n"
          "   隨即把它清掉 ⇒ 使用者看到一個**沒有回應的按鈕**，他會再按一次。\n"
        + "🔑 判準是**畫面上出現訊息**，不是變數有沒有被設定。")


@pytest.mark.e2e
def test_ac2_submitting_also_says_something_on_screen(live_server, make_user, e2e_browser):
    """🔴 **送審也要有回饋** —— `AC2` 的範圍是**每一個會寫入的動作**。

    ⚙️ 這一題是上一題的**第二個樣本**，而它不是重複：
    ```
    儲存  走 PUT     -> open() 重讀
    送審  走 /submit -> open() 重讀
    ```
    ⇒ 兩條路各自設定訊息、各自被同一個 `_clearMsg()` 清掉
      ⇒ **修好其中一條不代表另一條也好了**。
    ☠️ 而送審之後狀態會變，畫面**看起來有反應**（狀態欄變了）——
       所以「有沒有訊息」這一格更容易被當成不重要。
    """
    u, p = make_user(username="e2e_ac2_submit", role="superadmin",
                     modules=[VOUCHER_MODULE])
    errors = []

    browser = e2e_browser
    page = browser.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, live_server, u, p)
    page.goto("%s/pages/voucher.html" % live_server)
    _ready(page)

    page.locator(HOOKS["new"]).first.click()
    _editor_open(page)
    _fill_first_line(page)
    _settled(page, lambda: page.locator(HOOKS["save"]).first.click())

    submit = page.locator(HOOKS["submit"])
    if not (submit.count() and submit.first.is_visible()):
        browser.close()
        pytest.fail(
            "存好之後看不到「送審」（`%s`）——\n" % HOOKS["submit"]
            + "⚠️ 按鈕用 `x-show` ⇒ 它在 DOM 裡而看不到，"
              "我用的是 `is_visible()`。")
    before = _visible_text(page, OK_MSG)
    _settled(page, lambda: submit.first.click())

    after = _visible_text(page, OK_MSG)
    status = _visible_text(page, HOOKS["status"])

    assert not errors, "頁面丟了例外：%s" % errors[:3]
    assert status and "草稿" not in status, (
        "送審之後狀態還是 %r —— 先看後端那一條路。" % status)
    assert after and after != before, (
        "送審之後畫面上沒有新的訊息（按之前 %r，按之後 %r）。\n"
        % (before, after)
        + "☠️ 狀態欄變了，**所以畫面看起來有反應** ——\n"
          "   而使用者不知道那一步成功了還是只是畫面自己動了一下。\n"
        + "🔑 `AC2` 的範圍是**每一個會寫入的動作**，不是只有儲存。")


@pytest.mark.e2e
def test_ac2_the_message_is_not_wiped_by_the_reload_that_follows(
        live_server, make_user, e2e_browser):
    """⚙️ **反向控制：訊息要撐過那一次重讀。**

    ```
    設定 actionMsg -> await open(id) -> open() 第一件事是 _clearMsg()
    ```
    ⇒ 修法有兩種，而只有一種是對的：
    ```
    ✅ 重讀完之後**再**設定訊息（或讓 _clearMsg() 不碰成功訊息）
    ❌ 把 _clearMsg() 整個拿掉 => **上一次的錯誤訊息會留在畫面上**
       ⇒ 使用者修好之後仍然看到那句紅字
    ```
    ⚙️ 這一題同時量兩件：**成功訊息還在** ＋ **錯誤訊息不在**。
    🔑 少了後半，「把 `_clearMsg()` 拿掉」這個最省力的修法會讓上面兩題都綠。
    """
    u, p = make_user(username="e2e_ac2_wipe", role="superadmin",
                     modules=[VOUCHER_MODULE])

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto("%s/pages/voucher.html" % live_server)
    _ready(page)

    # ① 先製造一次**失敗**：同一行借貸都填（前端當場擋下、不送出）
    # 📌 更正留著（2026-09-25，PERF #6 換等待時實測）：原本是「不填分錄直接存」——
    #    空白草稿現在是可以存的 ⇒ 第一次其實**成功**、從來沒有錯誤訊息 ⇒ 下面「上一次的
    #    錯誤訊息不可以留著」那一半永遠是空的（反向控制是死的），固定等 2 秒把它蓋住了。
    page.locator(HOOKS["new"]).first.click()
    _editor_open(page)
    r0 = page.locator("table tbody tr").nth(0)
    r0.locator("input[x-model='l.account_code']").fill("1113")
    r0.locator("input[x-model='l.debit']").fill("500")
    r0.locator("input[x-model='l.credit']").fill("500")
    page.locator(HOOKS["save"]).first.click()
    _error_shown(page)
    first_err = _visible_text(page, ERR_MSG)
    assert first_err, "第一次應該失敗並顯示錯誤——前提不成立，下面的反向控制就是空的"

    # ② 再把它填好存成功
    r0.locator("input[x-model='l.credit']").fill("")
    _fill_first_line(page)
    _settled(page, lambda: page.locator(HOOKS["save"]).first.click())

    ok = _visible_text(page, OK_MSG)
    err = _visible_text(page, ERR_MSG)

    assert ok, (
        "存成功之後畫面上沒有成功訊息 —— 見上面那兩題，成因是同一個。")
    assert not err, (
        "存成功了，**而上一次的錯誤訊息還留在畫面上**：%r\n" % err
        + "☠️ 那是「把 `_clearMsg()` 整個拿掉」的樣子：\n"
          "   使用者修好之後仍然看到那句紅字，**他會以為還沒好**。\n"
        + "🔑 正確的修法是**重讀完之後再設定訊息**，不是不清。\n"
        + "📌 第一次的錯誤訊息是 %r（它應該在第二次之後消失）。" % first_err)
