"""瀏覽器層級：沒有某個模組的人，手打網址也開不了那一頁（2026-09-13）。

在此之前前端**沒有任何頁面層守門**——`auth-guard.js` 只驗 session。沒有某個模組
的人在側欄看不到入口，但手打網址照樣進得去；這一輪後端補上模組檢查之後，症狀會
變成「頁面開得起來、資料一片 403」，看起來像壞掉而不是像沒權限。

守門刻意**沿用側欄自己的顯示條件**（`sidebar.js::ni()` 判定不顯示時把該頁記進
`_deniedPages`），不另外維護一份頁面→模組對照表——那份表一旦跟顯示條件漂移，
就會變成這次盤點抓到的那類錯配。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._ports import free_safe_port




def _login(page, base_url, username, password):
    page.goto(f"{base_url}/pages/login.html")
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=10000)


#: 一個只有 `dashboard`＋`quotation` 的帳號，**導覽列裡一個都不該出現**的字。
#:
#: 🔑 **分組名與項目名都列**，理由見 `test_admin_without_module_…` 裡那一段：
#: 漏權限時，一個只剩一項的分組會渲染成**那一項的名字**，
#: ☠️ 只釘分組名的話，那次漏權限**結構上抓不到**。
#:
#: 📌 來源：`frontend/static/sidebar.js` 的 `sec()`／`ni()`（2026-09-22 讀取）。
#: ⚠️ 而一份**字串打錯的**禁列永遠是綠的 ——
#: ⇒ 所以 `test_superadmin_still_sees_everything` 反過來斷言**這裡每一個字
#:    superadmin 都看得到**。那是這份清單的正對照，兩題必須成對。
_FORBIDDEN_WITHOUT_MODULES = (
    # 廠商與採購
    "廠商與採購", "客戶管理", "供應商管理", "承攬商管理",
    "料號主檔", "庫存管理", "採購管理",
    # 設備
    "設備", "設備登載", "保固追蹤", "網路架構規劃書",
    # 勞務管理
    "勞務管理", "外包名冊", "勞報單",
    # 選型資料庫
    "選型資料庫", "場域選型導覽", "網路架構選型導覽", "交換器選型導覽",
    "監控系統選型導覽", "門禁系統選型導覽", "閘道器與控制器選型導覽",
    "自動化系統選型導覽",
    # 財務（單項分組 ⇒ 平常渲染成項目名）
    "營運報表",
)


def _nav_vocabulary(page):
    """導覽列上**所有**看得到的字：分組名（`.mnav__top`）＋ 項目名（`.mnav__item`）。

    ## ☠️ 為什麼不能只看 `.mnav__top`（A-2 2026-09-22 抓到的假綠燈）

    `sidebar.js:620-623`：**單項分組直接渲染成 `.mnav__top`（那一項的名字），
    多項分組才渲染成分組名 ＋ 面板裡的 `.mnav__item`。**
    ```
    舊寫法   names 只取 .mnav__top
    ⇒ 「廠商與採購」哪天真的漏權限顯示，而它當時**只剩一項**
      ⇒ 渲染成項目名、不在 .mnav__top 裡 ⇒ **assert not in 通過** ⇒ 🔴 假綠燈
    ```
    ⚠️ 而**這一包正好製造了一個單項分組**（財務／營運報表）⇒ 那顆地雷是活的。

    ## 🔴 而修法有一個反直覺的坑，我實測過（2026-09-22 18:55）

    `.mnav__panel` 的隱藏方式是 **`visibility: hidden`**（`style.css:480`），
    不是 `display: none`。而這兩者對 `innerText` 的行為**相反**：
    ```
    實測（Playwright + set_content，最小樣本）
      visibility:hidden  → all_inner_texts()   = ['', '']        ← **抓不到**
                           all_text_contents() = ['報價單','客戶'] ← 抓得到
      display:none       → all_inner_texts()   = ['被 display-none 的']  ← **抓得到**
                           （不被渲染 ⇒ innerText 退回 textContent）
    ```
    🔑 ⇒ **面板裡的 `.mnav__item` 必須用 `all_text_contents()`**；
    用 `all_inner_texts()` 的話會拿到一串空字串，
    ☠️ 而那會讓 `not in` **永遠成立** —— 換一個更嚴的寫法，得到一個更弱的守門。

    📌 ⇒ 兩層都用 `text_content`：它與 hover 狀態無關，
    問的是「**這個帳號的導覽列裡有沒有這個字**」，而那正是這幾題要問的。
    """
    tops = page.locator(".mnav .mnav__top").all_text_contents()
    items = page.locator(".mnav .mnav__item").all_text_contents()
    return [t.strip() for t in (tops + items) if t and t.strip()]


@pytest.mark.e2e
def test_page_without_module_shows_no_permission(live_server, make_user, e2e_browser):
    """沒有「供應商／料號／採購」模組的工程師手打 parts.html → 顯示沒有權限。

    **刻意不導轉**：`index.html` 自己也有一道守門（非 admin 且沒有 finance／
    quotation 模組就導去 case-management.html），導轉會做出無限迴圈——只有
    「儀表板」模組的檢視者會在兩頁之間一直跳。這一題實測時就是這樣才發現的。
    """
    u, p = make_user(username="pg_eng", role="engineer",
                     modules=["dashboard", "case_manage"])
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/parts.html")
    page.wait_for_selector("#no-module-notice", timeout=10000)
    # 頁面內容要真的被換掉，不是只疊一個提示上去
    assert page.locator(".toolbar").count() == 0, "料號頁的內容還在"


@pytest.mark.e2e
def test_page_with_module_is_not_redirected(live_server, make_user, e2e_browser):
    """反向控制：有那個模組的人留在頁面上。

    少了這一題，上面那題有可能只是因為「每個人都被導回首頁」而綠。
    """
    u, p = make_user(username="pg_proc", role="engineer",
                     modules=["dashboard", "procurement"])
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/parts.html")
    # 2026-09-14：側欄退役（display:none），改等上方導覽列的分組標題
    page.wait_for_selector(".mnav .mnav__top", timeout=10000)
    page.wait_for_timeout(300)   # 給守門一個真的會動作的機會
    assert page.url.endswith("parts.html"), f"有模組卻被導走了：{page.url}"
    assert page.locator("#no-module-notice").count() == 0, "有模組卻被擋"


# ── 2026-09-14：取消 admin 直通之後，管理員也依模組顯示 ────────────────────────
#
# 使用者裁示：「管理者一樣依據有開權限的內容去顯示，沒開的就不顯示，**包含模組
# 名稱**」。後端那半由 test_module_no_admin_bypass_2026_09_14.py 守著；這裡守的是
# 畫面——而且刻意驗「分組名稱」而不是只驗項目，因為「包含模組名稱」是裁示裡
# 特別點出來的那一句。

@pytest.mark.e2e
def test_admin_without_module_loses_both_item_and_group_name(live_server, make_user, e2e_browser):
    """只有報價模組的管理員：上方導覽不該出現「財務」這個分組名稱。

    改動前 admin 直通所有模組判斷，這個帳號會看到完整的導覽列。
    """
    u, p = make_user(username="nav_adm_min", role="admin",
                     modules=["dashboard", "quotation"])
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.wait_for_selector(".mnav .mnav__top", timeout=10000)
    names = _nav_vocabulary(page)
    # ⚙️ **正對照：這個帳號自己的兩個模組必須看得到。**
    #
    # 🔴 舊版斷言的是 `"業務" in names`，而 2026-09-22 實測那個帳號的
    #    導覽詞彙是：
    #    `['儀表板', '報價單', '我的工作', '簽核佇列', '簽核代理人', '簽核歷史']`
    #    ⇒ **「業務」不在裡面** —— 因為它底下只剩「報價單」一項，
    #      而單項分組渲染成**那一項的名字**（`sidebar.js:620-623`）。
    # ☠️ ⇒ 舊版釘的是**分組名**，而分組名會隨「底下剩幾項」變動 ——
    #    那個數字由**這個帳號有哪些模組**決定，**正是這一題在改的變數**。
    # 🔑 ⇒ 改釘**項目名**：`dashboard` ⇒ 儀表板、`quotation` ⇒ 報價單。
    #    它們與分組怎麼渲染無關。
    # ⚠️ **而這一條不可以省**（A-2 明著不背書「只刪掉它」）：
    #    整題只剩 `not in` 的話，**導覽列整個空掉也會綠**。
    for must in ("儀表板", "報價單"):
        assert must in names, (
            f"這個帳號有那個模組，而導覽列裡找不到「{must}」：{names}\n"
            "☠️ 少了這一條，導覽列整個空掉也會讓下面的 `not in` 全過。")
    # 🔴 **只釘分組名是抓不到漏權限的**（2026-09-22，A-2 指出 ＋ C 實測）
    #
    # ```
    # 「廠商與採購」哪天真的漏出來，而它當時只剩一項
    #   ⇒ 渲染成**那一項的名字**（客戶管理／供應商管理／…）
    #   ⇒ 分組名根本不會出現 ⇒ `assert "廠商與採購" not in names` **通過**
    # ```
    # ☠️ 而那正是這一題要抓的那件事 —— **它是一個結構上抓不到目標的判準。**
    # 🔑 ⇒ 連**項目名**一起釘：漏出來的東西無論渲染成哪一層，都會被抓到。
    leaked = sorted(n for n in _FORBIDDEN_WITHOUT_MODULES if n in names)
    assert not leaked, (
        f"沒有那些模組，而導覽列裡出現了：{leaked}\n"
        f"  完整詞彙：{names}\n"
        "☠️ 漏權限顯示 ⇒ 使用者點進去才發現沒有權限，"
        "而他會以為是系統壞了。")


@pytest.mark.e2e
def test_admin_with_module_still_sees_the_group(live_server, make_user, e2e_browser):
    """反向控制。少了這一題，上面那題可以靠「導覽列整個壞掉／空的」變綠。"""
    u, p = make_user(username="nav_adm_fin", role="admin",
                     modules=["dashboard", "quotation", "reports"])
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.wait_for_selector(".mnav .mnav__top", timeout=10000)
    names = _nav_vocabulary(page)
    # 🔑 用兩層詞彙之後，這一條**不再依賴「財務底下只有一項」**：
    #    哪天有人往財務加第二項 ⇒ 營運報表改渲染成 `.mnav__item`，
    #    而 `_nav_vocabulary()` 照樣找得到它 ⇒ **這一題不會紅在一個假的理由上**。
    assert "營運報表" in names, f"有 reports 模組卻看不到營運報表：{names}"


@pytest.mark.e2e
def test_superadmin_still_sees_everything(live_server, make_user, e2e_browser):
    """「超級管理者預設全開」——一個模組都沒勾也要看得到完整導覽。"""
    u, p = make_user(username="nav_sa", role="superadmin", modules=[])
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, p)
    page.wait_for_selector(".mnav .mnav__top", timeout=10000)
    names = _nav_vocabulary(page)
    for expect in ("業務", "案件", "營運報表", "廠商與採購", "選型資料庫", "系統"):
        assert expect in names, f"superadmin 看不到「{expect}」：{names}"

    # 📏 **這是 `_FORBIDDEN_WITHOUT_MODULES` 的正對照，兩題必須成對。**
    #
    # ☠️ 那份清單全部是 `not in` 斷言 ——
    # **一個打錯字的字串，`not in` 永遠成立** ⇒ 那一格會安靜地永遠綠。
    # 🔑 而 superadmin 看得到全部 ⇒ **每一個字都必須在這裡出現得到**。
    # 📌 ⇒ 哪天有人改了選單文案（例如「料號主檔」改名），
    #    紅的是**這一題**，訊息直接說出是哪一個字對不上，
    #    而不是讓禁列裡那一條安靜失效。
    missing = sorted(n for n in _FORBIDDEN_WITHOUT_MODULES
                     if n not in names)
    assert not missing, (
        f"`_FORBIDDEN_WITHOUT_MODULES` 裡這些字 superadmin 也看不到："
        f"{missing}\n"
        f"  superadmin 的完整詞彙：{names}\n"
        "☠️ 那代表那幾個字**根本不存在於導覽列**（改名了？打錯了？）——\n"
        "🔑 而它們在另一題裡是 `not in` 斷言 ⇒ **永遠成立 ⇒ 永遠綠**。")
