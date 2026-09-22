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
    """🔴 **`admin` 看得到那三句話，而**沒有**新增入口。**

    ☠️ 這是 `SPEC-BN1-PLAN §2` 真正要決定的那一格：
    ```
    admin 可以產生獎金單（_is_manager 過）
          **不能新增獎金項目**（require_superadmin 擋）
    ⇒ 公司裡只有 admin 在用的那天，他打開頁面看到空清單，**而他修不好它**
    ```
    ⚠️ 給他按鈕的後果不是「多一個按鈕」：他按下去收到 **403**，
       而這個模組已經確立「**按下去之前就該知道答案**」。
    """
    u, p = make_user(username="e2e_bn_admin", role="admin",
                     modules=["bonus"])
    text, create, empty, errors = _open_bonus(live_server, u, p)

    assert not errors, "頁面丟了例外：%s —— 先修這個。" % errors[:3]
    assert empty >= 1, (
        "`admin` 打開獎金頁，找不到獎金項目的空狀態區塊（`%s`）。\n"
        % HOOKS["empty"]
        + "畫面上是：\n  %s\n" % text[:300]
        + "📌 掛鉤名是我單方面定的，**要換退回給我**。")
    _assert_three_things(text, "admin")
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
                     modules=["bonus"])
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
    u, p = make_user(username="e2e_bn_staff", role="user", modules=["bonus"])
    _text, create, _empty, errors = _open_bonus(live_server, u, p)

    assert not errors, "頁面丟了例外：%s" % errors[:3]
    assert create == 0, (
        "一般員工看得到新增獎金項目的入口（`%s`，%d 個）——\n"
        % (HOOKS["create"], create)
        + "☠️ 獎金是薪資資料，而這個入口屬於 superadmin。")
