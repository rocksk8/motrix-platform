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

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_ac1_a_superadmin_gets_the_way_out、test_ac1_an_admin_is_told_who_can_fix_it_and_gets_no_button
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
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
    import modules.payroll.bonus as hb

    monkeypatch.delenv("BONUS_MODULE_ENABLED", raising=False)
    monkeypatch.setattr(hb, "BONUS_MODULE_ENABLED", True)
    # 🔑 隔離裝好要**當場驗它生效**（〈探針與被測對象糾纏〉）——
    #    少了這一行，旗標機制換了寫法時，本檔會紅在「三句話不見了」上，
    #    而訊息會把人送去修一個沒壞的畫面。
    assert hb.bonus_module_on(), (
        "打開旗標之後 `bonus_module_on()` 還是關的 —— **開關機制換了寫法**，\n"
        "本檔的前提失效了，先修這裡，不要去看下面那些斷言。")




def _login(page, base_url, username, password):
    inject_login(page, base_url, username, password)


def _open_bonus(browser, live_server, username, password):
    """開獎金頁，回 `(可見文字, 有沒有新增入口, 空狀態區塊數, 頁面例外)`。`browser` 是 e2e_browser。"""
    errors = []
    page = browser.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    _login(page, live_server, username, password)
    page.goto("%s/pages/bonus.html" % live_server)
    page.wait_for_timeout(2500)
    text = page.locator("body").inner_text()
    create = page.locator(HOOKS["create"]).count()
    empty = page.locator(HOOKS["empty"]).count()
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
def test_ac1_a_plain_employee_does_not_see_the_management_area(
        live_server, make_user, e2e_browser):
    """🔴 **一般員工不該看到管理區塊。**

    ☠️ 獎金是薪資資料。`visible_lines()` 的規則是「本人只看得到自己那一列」——
       而一個列出「誰能發、發給誰」的管理區塊會把那條規則繞過去。
    ⚠️ 判準只看**新增入口**：空狀態那三句話他看不看得到由畫面決定，
       我不釘（他本來就沒有項目可看）。
    """
    u, p = make_user(username="e2e_bn_staff", role="user", modules=[BONUS_MODULE])
    _text, create, _empty, errors = _open_bonus(e2e_browser, live_server, u, p)

    assert not errors, "頁面丟了例外：%s" % errors[:3]
    assert create == 0, (
        "一般員工看得到新增獎金項目的入口（`%s`，%d 個）——\n"
        % (HOOKS["create"], create)
        + "☠️ 獎金是薪資資料，而這個入口屬於 superadmin。")
