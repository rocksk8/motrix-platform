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
import re
import threading
import warnings
import time
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port

#: ⚠️ 我單方面宣告的掛鉤。改名**退回給我**。
HOOKS = {
    # 📌 2026-09-25（使用者裁定拿掉「摘要來源」頁籤區，收進分錄下方的帶入來源區塊；0a 派 bf 改題，斷言不刪）：
    #    tabs ⇒ 帶入來源區塊；item ⇒ 區塊裡的案件；「切頁籤」⇒「換到另一行、再點回有來源的這一行」
    #    （點回有來源的行會把右欄換成它的來源——新版裡最像「切頁籤」、也最可能被寫成重新帶入的那一步）。
    "tabs": '[data-testid="src-block"]',
    "item": '[data-testid="src-case"]',
    # 🔴 `JV12` 把這個欄位從 `<input>` 換成 `<textarea>`（讓高度隨文字
    #    調整），選擇器不綁標籤名，改綁的元件型別再換一次也不必回來改。
    "summary": '[x-model="l.summary"]',
    # 🔴 `JV8`（使用者 `§201`）把編輯畫面改成**要明著要**：
    #    `voucher.html:175  <div class="vc-sheet" x-show="editing">`
    #    `voucher.js  :31   editing: false`
    #    ⇒ 直接 `goto voucher.html` 之後摘要欄**在 DOM 裡而看不見**。
    # ⚙️ 這兩個不是我宣告的掛鉤，是 B 已經出貨的（`voucher.html:141`）。
    "new": '[data-testid="voucher-new"]',
    "row": '.vc-row',
}

#: `§159b` 的兩個頁籤。
TABS = ("案件", "已上傳檔案")

#: 使用者手打的那一段——`§164` 說「事由」**沒有來源可以帶**，一定要手打。
TYPED = "工資"




def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


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
    """看不到就**明著說是哪一個掛鉤不見了**，不要讓 timeout 變成謎題。

    ## 🔴 **原本只數 `count()` —— 而 `x-show` 的元素留在 DOM 裡**

    ```
    JV8 把 `.vc-sheet` 包成 x-show="editing"，editing 進頁是 false
    ⇒ count() 照樣過，紅在後面的 .click() 逾時 30s
    ⇒ 錯誤訊息長得像「頁面沒渲染」，其實是「元素在但看不見」
    ```
    ☠️ 這是我自己的觀測裝置把**契約改變**譯成了**頁面壞掉**，
       而兩種的處置完全相反（一個改測試、一個去追缺陷）。
    ⇒ 在 DOM 裡而不可見要**當場講出來**，不要留給 `.click()` 去逾時。
    """
    loc = page.locator(selector)
    if loc.count() == 0:
        body = page.locator("body").inner_text()[:300]
        pytest.fail(
            "頁面上找不到%s（`%s`）。\n" % (what, selector)
            + "📌 掛鉤名是我在 `HOOKS` 裡單方面定的，**要換退回給我**。\n"
            + "畫面上是：\n  %s" % body)
    if not loc.first.is_visible():
        pytest.fail(
            "%s（`%s`）**在 DOM 裡而看不見**。\n" % (what, selector)
            + "🔑 `x-show` 的元素不會被拿掉 ⇒ 數 `count()` 沒用。\n"
            + "📌 最常見的原因：進編輯畫面的那一步沒做（`JV8`：\n"
              "   要先按「＋新增傳票」或從清單點開一張）。")
    return loc


# ── 等待（PERF #6，2026-09-25：固定 sleep 換成等可觀測事件）────────────────────────
VC = "Alpine.$data(document.body)"


def _soft_wait(page, js, timeout=10000):
    """等到條件成立或逾時，**不丟例外**——判決留給後面原本那句有說明的斷言
    （直接等會把「帶入沒接上」這種失敗變成一句看不懂的 Timeout）。"""
    try:
        page.wait_for_function(js, timeout=timeout)
        return True
    except Exception:
        # 逾時照樣放行，但要看得到：條件寫錯時它只會默默拖滿逾時（第一版就是這樣，18s 變 42s）
        warnings.warn("soft wait timed out (%dms): %s" % (timeout, js[:120]))
        return False


def _ready(page):
    """頁面可以開始操作（原本固定等 2 秒）：「新增傳票」可見＋科目選單與摘要來源都載完。"""
    page.wait_for_selector(HOOKS["new"], state="visible", timeout=15000)
    page.wait_for_function("() => window.Alpine && %s && %s._accountsLoaded && !%s.sourcesLoading"
                           " && Object.keys(%s.sources || {}).length > 0" % (VC, VC, VC, VC), timeout=15000)


def _items_shown(page):
    """點頁籤之後，來源清單渲染出來（原本固定等 0.5 秒）。"""
    _soft_wait(page, "() => [...document.querySelectorAll('%s')].some(e => e.offsetParent !== null)"
               % HOOKS["item"].replace("'", "\\'"))


def _brought_in(page):
    """點一筆來源之後，摘要欄被帶入（原本固定等 0.3 秒）。applySource() 是同步的，等的是畫面更新。"""
    _soft_wait(page, "() => [...document.querySelectorAll('[x-model=\"l.summary\"]')]"
               ".some(e => e.value.trim())", timeout=5000)


def _saved(page, do):
    """存檔整個做完（原本固定等 1.2 秒）：最後一步是重讀清單 GET /api/vouchers ⇒ 等它回來＋busy 解除。"""
    with page.expect_response(lambda r: r.request.method == "GET" and urlparse(r.url).path == "/api/vouchers",
                              timeout=15000):
        do()
    page.wait_for_function("() => !%s.busy" % VC, timeout=15000)
    page.evaluate("() => new Promise(r => Alpine.nextTick(r))")


def _opened(page, do):
    """從清單點開一張：等**這一次點開**的終點——開單序號（`_openSeq`）完成並渲染（<body data-voucher-open-seq>）。
    〔O9-2：原本等「任一個 GET /api/vouchers/{id} 回來」＋一次 nextTick。重整後網址帶 ?id=，頁面自己也在開同一張
      （深連結）⇒ 等到的可能是深連結那一趟，點開的那一趟還在路上，下一步的可見性檢查就早了（時間線實測：兩趟 GET 交錯、
      失敗當下只回來一趟）。改等本次點擊的序號，不等某一趟請求（〈e2e 等待的終點〉）〕"""
    do()
    target = page.evaluate("() => %s._openSeq" % VC)
    page.wait_for_function("(n) => Number(document.body.getAttribute('data-voucher-open-seq') || 0) >= n",
                           arg=target, timeout=15000)


def _open_editor(page):
    """進編輯畫面 —— `JV8` 之後這一步是**必要的**。

    使用者 `§201` 逐字：「傳票應該是新增傳票後才出現傳票的頁面」
    ⇒ 直接 `goto` 之後沒有編輯畫面可以點。
    ⚙️ 這**不是繞過什麼** —— 它就是使用者真正走的那一步。
    """
    _need(page, HOOKS["new"], "「＋新增傳票」按鈕").first.click()
    _soft_wait(page, "() => [...document.querySelectorAll('[x-model=\"l.summary\"]')]"
               ".some(e => e.offsetParent !== null)")
    _need(page, HOOKS["summary"], "分錄行的摘要欄")


@pytest.mark.e2e
def test_jv7_an_edited_summary_survives_a_tab_switch(live_server, make_user, e2e_browser):
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

    browser = e2e_browser
    page = browser.new_page()
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    _login(page, live_server, username, password)
    page.goto("%s/pages/voucher.html" % live_server)
    _ready(page)
    # 🔴 `JV8` 之後這一步不可略（使用者 `§201`）。
    _open_editor(page)

    _need(page, HOOKS["tabs"], "帶入來源區塊")
    lines = _need(page, HOOKS["summary"], "分錄行的摘要欄")
    lines.first.click()
    _items_shown(page)
    _need(page, HOOKS["item"], "案件來源的清單").first.click()
    _brought_in(page)

    box = _need(page, HOOKS["summary"], "分錄行的摘要欄").first
    brought_in = box.input_value()

    # ② 使用者自己續打（`§164`：事由沒有來源可以帶）
    box.click()
    box.fill(brought_in + TYPED)
    edited = box.input_value()

    # ③ 切走再切回來
    # ⚠️ 這兩個固定等待**保留**（PERF #6 的 N 類）：要證明的是「切頁籤**不會**重新帶入」，
    #    「沒有發生」沒有事件可以等 ⇒ 給錯誤寫法（若有的非同步重新帶入）一段時間發生。
    #    新版：換到第 2 行，再點回有來源的第 1 行（右欄會換成它的來源）。
    if lines.count() < 2:
        page.click('button:has-text("新增一行")')
    lines.nth(1).click()
    page.wait_for_timeout(300)
    lines.first.click()
    page.wait_for_timeout(500)

    after = box.input_value()

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
def test_jv7_an_edited_summary_survives_a_reload(live_server, make_user, e2e_browser):
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

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto("%s/pages/voucher.html" % live_server)
    _ready(page)
    # 🔴 `JV8` 之後這一步不可略（使用者 `§201`）。
    _open_editor(page)

    _need(page, HOOKS["tabs"], "帶入來源區塊")
    _need(page, HOOKS["summary"], "分錄行的摘要欄").first.click()
    _items_shown(page)
    _need(page, HOOKS["item"], "案件來源的清單").first.click()
    _brought_in(page)

    box = _need(page, HOOKS["summary"], "分錄行的摘要欄").first
    box.fill(box.input_value() + TYPED)
    edited = box.input_value()

    # 🔴 存檔前一定要有**會計科目** —— B 退回的那一格。
    #    db.py:4735 `account_code TEXT NOT NULL REFERENCES account_items(code)`
    #    ⇒ 空字串或不存在的代號會撞 FOREIGN KEY；B 已把它翻成 400
    #      「第 1 行還沒有選會計科目」。
    # ☠️ 我第一版點完來源就按儲存，**一個科目都沒填** ⇒ 這一題紅在
    #    「存不下去」而不是「摘要被蓋回去」—— 紅的理由不是我要驗的那一件。
    code = page.locator('input[x-model="l.account_code"]')
    if code.count() == 0:
        browser.close()
        pytest.fail(
            "找不到會計科目的輸入框（`input[x-model=\"l.account_code\"]`）"
            "—— **退回給我**改這個觀測點。")
    code.first.fill("1113")

    save = page.locator('button:has-text("儲存")')
    if save.count() == 0:
        browser.close()
        pytest.fail("頁面上找不到「儲存」—— 摘要改了**存不下去**。")
    _saved(page, lambda: save.first.click())

    page.reload()
    _ready(page)
    # 🔴 `JV8`：重整之後 `editing` 又回到 false
    #    ⇒ 要**從左側清單點開刚存的那張**才看得到摘要。
    # ⚙️ 而這比舊寫法**更貼近這一題要驗的事**：
    #    docstring 逐字寫的就是「使用者改完、存檔、關掉；
    #    **下次打開才變回來**」—— 而「下次打開」就是點清單。
    # ⚠️ 不能改按「＋新增傳票」：那是**另一張空的**，
    #    摘要欄會是空字串 ⇒ 這一題會紅得像「被蓋回去」，
    #    而那是**我量錯了**，不是產品錯了。
    row = _need(page, HOOKS["row"], "左側傳票清單的列").first
    _opened(page, lambda: row.click())
    after = _need(page, HOOKS["summary"], "分錄行的摘要欄").first.input_value()

    assert after == edited, (
        "重新整理之後摘要變回帶入時的樣子：\n"
        "  存檔前  %r\n"
        "  重整後  %r\n" % (edited, after)
        + "☠️ 存的是**來源 id**、開啟時再組一次 ⇒ 使用者改的東西沒有被存下來。\n"
        + "🔑 `§164`：帶入只是**省打字**，最終值是使用者打的那個。")


#: 深連結那一張的 GET 回應延後——.json() 慢 1.5 秒（放行由時間，但斷言等的是「它被讀到」，不靠時間差）
_SLOW_FIRST_OPEN = """
(function () {
  var real = Response.prototype.json, done = false
  Response.prototype.json = function () {
    var self = this
    if (!done && /\\/api\\/vouchers\\/\\d+$/.test(new URL(self.url).pathname)) {
      done = true
      return new Promise(function (res) { setTimeout(res, 1500) })
        .then(function () { window.__staleRead = true; return real.call(self) })
    }
    return real.call(self)
  }
})()
"""


@pytest.mark.e2e
def test_o92_late_deep_link_response_does_not_replace_the_clicked_voucher(live_server, make_user, e2e_browser, client):
    """O9-2 產品競態：網址帶 ?id=A（深連結正在開 A、回應慢），使用者從清單點開 B ⇒ 畫面是 B；A 晚到的回應要丟掉。
    突變：open() 拿掉序號檢查 ⇒ 畫面被換回 A ⇒ 紅。"""
    username, password = make_user(username="e2e_o92", role="superadmin", modules=["cashier"])
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    line = [{"account_code": "1113", "summary": "x", "debit": 100, "credit": 0},
            {"account_code": "2171", "summary": "x", "debit": 0, "credit": 100}]
    a = client.post("/api/vouchers", headers=h, json={"summary": "O92-A", "lines": line}).json()
    b = client.post("/api/vouchers", headers=h, json={"summary": "O92-B", "lines": line}).json()
    ida, idb = a.get("id"), b.get("id")
    assert ida and idb and ida != idb, (a, b)
    page = e2e_browser.new_page()
    _login(page, live_server, username, password)
    page.add_init_script(_SLOW_FIRST_OPEN)
    page.goto("%s/pages/voucher.html?id=%d" % (live_server, ida))
    _ready(page)
    row_b = page.locator(HOOKS["row"]).filter(has_text=b.get("voucher_no") or "O92-B").first
    _opened(page, lambda: row_b.click())
    assert page.evaluate("() => %s.id" % VC) == idb, "點開的是 B"
    page.wait_for_function("window.__staleRead === true", timeout=15000)     # 深連結 A 的回應被讀到了
    page.evaluate("() => new Promise(r => setTimeout(() => setTimeout(r, 0), 0))")
    assert page.evaluate("() => %s.id" % VC) == idb, "A 晚到的回應把畫面換回 A（沒有丟掉過期回應）"
    assert page.evaluate("() => %s.note" % VC) == "O92-B"

