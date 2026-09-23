# -*- coding: utf-8 -*-
"""`AC1` 第一個實例的**執行期那一半**：三種身分各開一次獎金頁。

```
使用者逐字  「確認前後端跟頁面都有完成才算完整」
靜態題      x-show 的運算式綁對了嗎        <= test_bonus_empty_state_2026_09_23.py
本檔        那個旗標真的從 session 來了嗎   <= **使用者撞到的是這一層**
```
🔑 少了這一半，`AC1` 會變成**它自己要擋的那種東西**：
   `FN1` 那 10 題全綠而使用者撞到空白頁，就是這個缺口。

# 🔴 三種身分（我的讀法，錯了**退回給我**）

```
一般員工 role=user        管理區塊整個看不到
admin                     看得到空狀態三句話，**而沒有新增入口**
superadmin                有新增入口
```
📌 A 寫的是「manager／admin／superadmin」，而 `_is_manager` = superadmin ＋ admin
⇒ **manager 與 admin 在產品裡是同一格** ⇒ 我改成上面這三種真正會分岔的身分。

# ⚠️ 這裡用 Playwright（**本機**瀏覽器），不是 `claude-in-chrome`

D 今天查到 `claude-in-chrome` 是遠端瀏覽器、**可能連不到 `127.0.0.1`**。
本檔比照既有 53 支 e2e，在測試行程內起 uvicorn ＋ 本機 chromium ⇒ 不受影響。
📌 帳號是 `make_user` 建的**測試 fixture 帳號**，不是使用者的密碼。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

#: ⚠️ 我單方面宣告的測試掛鉤。頁面還不存在，選擇器只能由我先定。
#: **要換名字請退回給我改這張表，不要動我的檔。**
#: 🔴 bonus.html 由 **reports** 模組把關 —— sidebar.js:765 那一列的旗標是
#:    cRpt，而 cRpt = has("reports")（sidebar.js:480）。
#: ☠️ 我第一版寫 "bonus" —— 那是**選單項目的 id**，不是模組名 ⇒ 三個帳號
#:    全被 _showNoPermission() 擋在頁面外：admin／superadmin 兩題會紅，
#:    而「一般員工看不到新增入口」那題**變成真空的綠**（它根本沒走到頁面，
#:    畫面整個壞掉也會過）—— 而它是 superadmin 那題的反向控制
#:    ⇒ **兩題一起失效**。B 退回，我複查 sidebar.js 成立。
BONUS_MODULE = "reports"

HOOKS = {
    "empty": '[data-testid="bonus-items-empty"]',
    "create": '[data-testid="bonus-item-create"]',
}

#: 空狀態要說出的三件（同靜態題，不釘字面文案）。
THREE_THINGS = {
    "① 為什麼是空的": ("尚未建立", "還沒有建立", "沒有任何獎金項目", "尚未設定"),
    "② 誰能解決": ("最高管理員", "superadmin", "系統管理員"),
    "③ 去哪裡解決": ("獎金項目", "本頁", "下方"),
}


#: `bonus.html` 在模組關著時顯示的字（`BONUS_MODULE_ENABLED`，B `d03bf7d`）。
SUSPENDED = "暫停使用"


@pytest.fixture(autouse=True)
def _bonus_module_on(monkeypatch):
    """🔴 **本檔每一題都要在「模組開著」的前提下跑。**

    2026-09-23 使用者裁示把獎金模組拉掉（`BONUS_MODULE_ENABLED` 預設關）
    ⇒ `bonus.html` 變成「此模組暫停使用」⇒ 本檔三題全部量不到 `AC1`。

    ## ☠️ 而三題裡只有兩題會紅，第三題**變成真空的綠**

    ```
    admin／superadmin  要「看得到」某個東西 => 模組關著 => 紅（看得見的壞法）
    一般員工           要「看不到」新增入口 => 模組關著 => **必然通過**
    ```
    🔑 而第三題正是 `superadmin` 那題的反向控制 ——
      它無聲地失效之後，「一律不給按鈕」那種實作就沒有人擋得住了。
    ⇒ 所以三題**一起**打開旗標，不是只修紅的那兩支。

    ## ⚠️ 不用 `skip`

    skip 之後「`AC1` 有沒有壞」就沒有人知道了，而模組開回來的那天
    也不會有人記得把它打開 —— 覆蓋率要留著。

    ⚙️ 伺服器是**同行程**起的（`uvicorn.Config(main.app)`），而
    `bonus_module_on()` 每次呼叫才讀模組全域 ⇒ `monkeypatch.setattr`
    對 HTTP 請求那一側同樣生效。
    ⚠️ 環境變數要先清掉：它是另一條開關路徑，留著的話這裡就分不出
    「旗標真的被打開了」與「環境剛好設著」。
    """
    import helpers.bonus as hb

    monkeypatch.delenv("BONUS_MODULE_ENABLED", raising=False)
    monkeypatch.setattr(hb, "BONUS_MODULE_ENABLED", True)
    # 🔑 隔離裝好要**當場驗它生效**（〈探針與被測對象糾纏〉）——
    #    少了這一行，旗標機制換了寫法時，本檔會紅在「三句話不見了」上，
    #    而訊息會把人送去修一個沒壞的畫面。
    assert hb.bonus_module_on(), (
        "打開旗標之後 `bonus_module_on()` 還是關的 —— **開關機制換了寫法**，\n"
        "本檔的前提失效了，先修這裡，不要去看下面那些斷言。")


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


def _open_bonus(live_server, username, password):
    """開獎金頁，回 `(可見文字, 有沒有新增入口, 空狀態區塊數, 頁面例外)`。"""
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        _login(page, live_server, username, password)
        page.goto("%s/pages/bonus.html" % live_server)
        page.wait_for_timeout(2500)
        text = page.locator("body").inner_text()
        create = page.locator(HOOKS["create"]).count()
        empty = page.locator(HOOKS["empty"]).count()
        browser.close()
    # 🔴 前提先亮出來：模組被關著的話，下面每一個斷言量到的都不是 `AC1`。
    #    ☠️ 少了這一行，失敗訊息會是「空狀態沒說出那三句話」——
    #       而真正的原因是頁面根本沒載入獎金模組。
    assert SUSPENDED not in text, (
        "獎金頁顯示「%s」—— **模組是關著的**（`BONUS_MODULE_ENABLED`）。\n"
        % SUSPENDED
        + "⇒ 這一題量到的不是 `AC1`，先看 `_bonus_module_on` 那個 fixture。")
    return text, create, empty, errors


def _assert_three_things(text, who):
    missing = [k for k, words in THREE_THINGS.items()
               if not any(w in text for w in words)]
    assert not missing, (
        "`%s` 打開獎金頁，空狀態沒有說出：%s\n" % (who, "、".join(missing))
        + "畫面上是：\n  %s\n" % text[:300]
        + "📌 三件都要：**為什麼空／誰能解決／去哪裡解決**。")


# ══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
def test_ac1_an_admin_is_told_who_can_fix_it_and_gets_no_button(
        live_server, make_user):
    """🔴 **`admin` 看不到獎金項目區，也沒有新增入口。**（2026-09-24 改判準）

    ## 📌 更正留著：這一題原本要求 admin 看得到獎金項目的空狀態三句話

    原判準（AC1，2026-09-23 清晨）：admin 打開獎金頁，看得到「為什麼空／誰能解決／
    去哪裡解決」三句話，而沒有新增入口。
    ☠️ 之後 `BN2`（獎金項目只有最高管理者可見）與 `BN9`（`is_manager` 收成只有
       superadmin）上線 ⇒ admin 的 `isManager` 為 false ⇒ `loadItems()` 不會打、
       獎金項目整區不顯示 ⇒ 原判準與後來的裁示牴觸，這一題從那時起一直是紅的
       （本輪之前的 `20a11de` 就紅）。
    ✅ 裁定（使用者 2026-09-24 表單原文，hichan-0a 轉達）：「**題對齊 BN9，產品不動**」。
       ⇒ 三句話那一格由 superadmin 那一題承擔（它仍然驗三句話）。
    ⚠️ 「admin 按得到『產生獎金分潤單』，卻不知道為什麼產不出來」那一格
       **本輪不做**，記在 `docs/windows/KNOWN-GAPS.md`（2026-09-24 ③）。

    ⚙️ 觀測點是**看得到的文字**（`inner_text` 不含隱藏元素），不是 DOM 裡有沒有那個節點——
       x-show 只是藏起來，節點還在，數節點會把「藏著」算成「看得到」。
    """
    u, p = make_user(username="e2e_bn_admin", role="admin",
                     modules=[BONUS_MODULE])
    text, create, empty, errors = _open_bonus(live_server, u, p)

    assert not errors, "頁面丟了例外：%s —— 先修這個。" % errors[:3]
    assert "產生獎金分潤單" in text, (
        "量尺：admin 連「產生獎金分潤單」都看不到 —— 頁面沒載入成功，下面的斷言量不到東西。\n"
        "畫面上是：\n  %s" % text[:300])
    for visible_marker in ("尚未建立任何獎金項目", "每個項目綁一個人員來源"):
        assert visible_marker not in text, (
            "`admin` 看得到獎金項目區（畫面上有「%s」）——\n" % visible_marker
            + "BN2／BN9：獎金項目只有最高管理者可見。")
    assert create == 0, (
        "`admin` 看得到新增入口（`%s`，%d 個）——\n" % (HOOKS["create"], create)
        + "☠️ 他按下去會收到 **403**，而這一頁應該在他按下去之前就告訴他。")


@pytest.mark.e2e
def test_ac1_a_superadmin_gets_the_way_out(live_server, make_user):
    """🔴 **`superadmin` 要有新增入口** —— 他是唯一走得完全程的人。

    ⚙️ 這一題是上一題的**反向控制**：少了它，「一律不給按鈕」也會讓上一題綠 ——
       而那樣**沒有人建得了獎金項目**，整個模組永遠是空的。
    """
    u, p = make_user(username="e2e_bn_super", role="superadmin",
                     modules=[BONUS_MODULE])
    text, create, empty, errors = _open_bonus(live_server, u, p)

    assert not errors, "頁面丟了例外：%s" % errors[:3]
    assert empty >= 1, (
        "`superadmin` 也找不到空狀態區塊 —— 先看上一題，成因可能是同一個。")
    _assert_three_things(text, "superadmin")
    assert create >= 1, (
        "`superadmin` **沒有**新增入口（`%s`）——\n" % HOOKS["create"]
        + "畫面上是：\n  %s\n" % text[:300]
        + "☠️ 那表示沒有任何人建得了獎金項目，**整個模組永遠是空的**。\n"
        + "⚙️ 而這一題是上一題的反向控制：\n"
          "   少了它，「一律不給按鈕」也會讓 `admin` 那一題變綠。")


@pytest.mark.e2e
def test_ac1_a_plain_employee_does_not_see_the_management_area(
        live_server, make_user):
    """🔴 **一般員工不該看到管理區塊。**

    ☠️ 獎金是薪資資料。`visible_lines()` 的規則是「本人只看得到自己那一列」——
       而一個列出「誰能發、發給誰」的管理區塊會把那條規則繞過去。
    ⚠️ 判準只看**新增入口**：空狀態那三句話他看不看得到由畫面決定，
       我不釘（他本來就沒有項目可看）。
    """
    u, p = make_user(username="e2e_bn_staff", role="user", modules=[BONUS_MODULE])
    _text, create, _empty, errors = _open_bonus(live_server, u, p)

    assert not errors, "頁面丟了例外：%s" % errors[:3]
    assert create == 0, (
        "一般員工看得到新增獎金項目的入口（`%s`，%d 個）——\n"
        % (HOOKS["create"], create)
        + "☠️ 獎金是薪資資料，而這個入口屬於 superadmin。")
