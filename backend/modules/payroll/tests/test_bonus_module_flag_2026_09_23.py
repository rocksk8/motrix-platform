# -*- coding: utf-8 -*-
"""獎金分潤模組總開關 `BONUS_MODULE_ENABLED`（原預設**關**，B `d03bf7d`；2026-09-24 使用者「上傳到正式機就自動啟用」⇒ 翻成預設**開**）。

使用者裁（逐字）：**「如果問題太多先把獎金分潤的模組拉掉，之後有時間
再處理，記得備註」**（2026-09-23）。

```
modules/payroll/bonus.py      BONUS_MODULE_ENABLED = False ＋ bonus_module_on()
routers/system.py     GET /api/system/bonus-module-status（要登入）
sidebar.js            打那支端點，關閉時隱藏 a[href$="bonus.html"]
bonus.html            直開網址顯示「暫停使用」
modules/payroll/api/bonus.py      **零改動** —— 140+ 支既有獎金測試才不會全紅
```

# ☠️ 只測「關掉時不見了」的話，**把整個模組刪掉也會全綠**

〈判準的寬窄都會騙人〉：超集永遠比較好過，而它給你綠燈所以你不會回來
看它。⇒ 本檔**兩個方向都釘**：關掉會消失、**打開會回來**。
🔑 第二個方向才是重點——它守的是「之後有時間再處理」那句話：
**拉掉是暫停，不是刪除**，而刪掉的東西沒有人記得要加回來。

# ⚠️ 我第一版把題釘在錯的載體上（留著這一列）

我假設旗標會寫成 `sidebar.js` 裡的 JS 常數，於是斷言「`sidebar.js` 裡
有 `BONUS_MODULE_ENABLED = false`」。B 的實作把旗標放在**後端**、前端
用端點問——⇒ 我那兩支會**紅在一個正確的實作上**，而訊息會指著他的碼。
🔑 那正是〈守門守的對象被搬走〉：我釘的是實作位置，不是不變量。
⇒ 改成釘**行為**（`bonus_module_on()` 的回傳、端點的回應），
  位置只在「入口沒被刪掉」那幾題裡出現，而那幾題本來就是在講位置。
"""
import pathlib
import re

#: B 定的端點（`routers/system.py`）。⚠️ 它**要登入**，沒進
#: `main.py::_PUBLIC_API_PATHS`。
STATUS_ENDPOINT = "/api/system/bonus-module-status"

#: 停用訊息裡一定要有的最短片段。⚠️ 刻意只取四個字：釘整句話的話，
#: 換一種說法（「此模組暫停使用中」）就會紅在一個正確的實作上。
SUSPENDED = "暫停使用"

#: 獎金入口的識別字（A 明著交代：釘**那一個入口的識別字**，
#: 不要釘「側邊欄有幾個項目」——數量會因為別的改動變動）。
ENTRY_HREF = "bonus.html"
ENTRY_LABEL = "獎金分潤"

#: 與獎金**同一組**（財務）的其他入口。B 自己抓到並修掉的那個 bug：
#: 藏 `.mnav__grp` 祖先會把整個財務下拉面板一起藏掉。
SIBLING_ENTRIES = ("voucher.html", "account-items.html")


def _root():
    return pathlib.Path(__file__).resolve().parents[4]


def _sidebar():
    return (_root() / "frontend" / "static" / "sidebar.js").read_text(
        encoding="utf-8")


def _bonus_page():
    return (_root() / "frontend" / "pages" / "bonus.html").read_text(
        encoding="utf-8")


def _strip_js_comments(src):
    """把 `//` 與 `/* */` 註解拿掉。

    🔴 〈會截斷的指令不可以當事實來源〉第七種：**沒剝註解撿到幽靈**。
    `sidebar.js` 裡關於獎金入口的註解有六行，其中就有 `bonus.html`
    這個字串 ⇒ 不剝註解的話，**把那一行入口刪掉、只留註解**，
    「入口還在」那幾題照樣全綠。
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", src)


def _login(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ══════════════════════════════════════════════════════════════════════
# ① 旗標本身：釘**行為**，不釘字面值
# ══════════════════════════════════════════════════════════════════════


def test_the_bonus_module_is_on_by_default(monkeypatch):
    """🔴 **出貨預設是開的**（2026-09-24 翻面）。

    使用者逐字：「獎金分潤模組上傳到正式機就自動啟用」（SPEC-BONUS §11.7）。
    原本這一題釘「預設關」，理由是舊算法三組各自佔淨利、沒人檢查加總（SPEC-BN21）；
    §十一 改成同一個獎金池分三類，那個理由不成立了。

    ⚙️ 釘 `bonus_module_on()` 的**回傳**，不是釘原始碼字面值（〈守門守的對象被搬走〉）。
    ⚠️ 先把環境變數清掉：這一題問的是「**沒有人動過它的時候**」。
    """
    import modules.payroll.bonus as hb

    monkeypatch.delenv("BONUS_MODULE_ENABLED", raising=False)
    assert hb.bonus_module_on() is True, (
        "`bonus_module_on()` 在沒有任何環境變數時回了假 —— 使用者要「上線就自動啟用」。")


def test_the_bonus_module_can_still_be_turned_off_on_site(monkeypatch):
    """🔴🔴 **反向控制：現場要關得掉**（翻面後對應原本「開得回來」那一題）。

    ```
    ① 環境變數 BONUS_MODULE_ENABLED=0   ⇒ 關（現場關，不用改碼）
    ② 常數改 False 且沒有環境變數        ⇒ 關（改碼重新出貨）
    ③ 常數 False＋環境變數 =1           ⇒ 開（原本那條「現場開」的路仍然通）
    ```
    ⚠️ ① 的判準是 `== "0"`：用真假值判的話 `"0"` 是非空字串，會判成開著。
    """
    import modules.payroll.bonus as hb

    monkeypatch.setenv("BONUS_MODULE_ENABLED", "0")
    assert not hb.bonus_module_on(), "環境變數 `=0` 之後它還是開的 —— 現場關不掉了。"

    monkeypatch.delenv("BONUS_MODULE_ENABLED", raising=False)
    monkeypatch.setattr(hb, "BONUS_MODULE_ENABLED", False)
    assert not hb.bonus_module_on(), "常數改成 False 之後它還是開的。"

    monkeypatch.setenv("BONUS_MODULE_ENABLED", "1")
    assert hb.bonus_module_on(), "常數 False＋環境變數 =1 應該是開的。"


# ══════════════════════════════════════════════════════════════════════
# ② 端點：前端的唯一真相來源
# ══════════════════════════════════════════════════════════════════════


def test_the_status_endpoint_requires_login(client):
    """🔴 **這支端點要登入。**（它沒進 `_PUBLIC_API_PATHS`，B 的設計）

    ⚠️ 判準是「有沒有被擋」：401 與 403 都算。
    """
    r = client.get(STATUS_ENDPOINT)
    assert r.status_code in (401, 403), (
        "沒帶 token 就讀到了模組狀態（回 %s）：%s" % (r.status_code, r.text[:200]))


def test_the_status_endpoint_answers_both_directions(client, make_user,
                                                      monkeypatch):
    """🔴🔴 **端點要照實回答兩個方向**，不是永遠回 `false`。

    ☠️ 一個寫死 `{"enabled": false}` 的端點會讓「關掉時入口不見」那一題
    全綠，而**開回來的那天，前端永遠看不到它開了**。
    🔑 這一題與上面那支 `bonus_module_on()` 的反向控制**不重複**：
    那支驗的是旗標函式，這支驗的是**端點真的去問了那支函式**
    （中間那一段接線斷掉時，只有這一題會紅）。
    """
    import modules.payroll.bonus as hb

    hdr = _login(client, make_user, "bonus_flag_reader")

    monkeypatch.delenv("BONUS_MODULE_ENABLED", raising=False)
    monkeypatch.setattr(hb, "BONUS_MODULE_ENABLED", False)
    off = client.get(STATUS_ENDPOINT, headers=hdr)
    assert off.status_code == 200, "端點壞了：%s %s" % (off.status_code,
                                                     off.text[:200])
    assert off.json().get("enabled") is False, (
        "旗標關著，而端點回 %r —— 前端會照樣顯示入口。" % off.json())

    monkeypatch.setattr(hb, "BONUS_MODULE_ENABLED", True)
    on = client.get(STATUS_ENDPOINT, headers=hdr)
    assert on.json().get("enabled") is True, (
        "旗標打開了，而端點回 %r ——\n" % on.json()
        + "☠️ 那支端點沒有真的去問 `bonus_module_on()`（接線斷了，"
          "或是回應被寫死）⇒ **模組開不回來**。")


# ══════════════════════════════════════════════════════════════════════
# ③ 沒被刪掉（這一半才是重點）
# ══════════════════════════════════════════════════════════════════════


def test_the_sidebar_entry_is_only_hidden_not_deleted():
    """🔴🔴 **側邊欄那一行獎金入口要還在，只是被旗標關著。**

    ☠️ 這一題守的是〈判準的寬窄都會騙人〉裡最貴的那一側：
    ```
    「旗標關 => 入口不見」這個斷言，**把整段程式碼刪掉也會通過**
    ```
    而刪掉之後，「之後有時間再處理」那句話就沒有著力點了——
    🔑 下一個人要重做的不是「把旗標打開」，是**重寫一個入口**，
      而他不會知道原本掛在哪一組、沿用哪一個權限（`cRpt`）。

    ⚙️ 剝掉註解再找（〈沒剝註解撿到幽靈〉）。

    ## 📌 這一題現在是綠的，而它證明的不是「已經做好了」

    它會在**有人把那一行刪掉**的那天第一次變紅——那正是它存在的理由。
    牙齒證明過：把那一行從來源字串裡拿掉（只留註解），這一題會紅。
    """
    src = _strip_js_comments(_sidebar())
    assert ENTRY_HREF in src, (
        "`sidebar.js` 的**程式碼**裡找不到 `%s`（註解不算）——\n" % ENTRY_HREF
        + "☠️ 入口被整段刪掉了。使用者要的是**暫停**，不是移除。")
    assert ENTRY_LABEL in src, (
        "`sidebar.js` 的程式碼裡找不到入口名稱「%s」。" % ENTRY_LABEL)


def test_hiding_the_bonus_entry_does_not_hide_its_neighbours():
    """🔴🔴 **藏過頭：財務那一組的其他入口要還在。**（B 自己抓到的 bug）

    ```
    ☠️ 藏 `a[href$="bonus.html"]` 的 `.mnav__grp` 祖先
       => 那個 div 是整個「財務」下拉面板
       => 出納／傳票／會計科目**一起消失**
    ```
    🔑 而這種壞法**沒有任何東西會說**：使用者只會覺得「財務不見了」，
      而側邊欄的其他組都正常，看起來不像旗標造成的。

    ⚙️ 靜態能釘的是「隱藏那一段的選擇器只挑連結本身」——
    ⚠️ 這確實是在釘實作細節（`closest`／祖先 class），而我找不到更好的：
      真正要驗的是**渲染後的 DOM**，那要 e2e（不在這一檔的射程內）。
    📌 ⇒ 判準寫成「隱藏函式的本體裡不可以出現往上爬的動作」，
      並把兩個相鄰入口的識別字也一起釘住（它們被刪掉時也要紅）。
    """
    src = _sidebar()
    for sibling in SIBLING_ENTRIES:
        assert sibling in src, (
            "`sidebar.js` 裡找不到同一組的入口 `%s` —— 它被一起拿掉了。"
            % sibling)

    m = re.search(r"function\s+_hideBonusEntryIfModuleDisabled\s*\(\)\s*\{",
                  src)
    assert m is not None, (
        "找不到 `_hideBonusEntryIfModuleDisabled()` —— 隱藏邏輯不在了，\n"
        + "或是改了名字（改名的話這一題要跟著改，不要直接刪掉它）。")
    # 🔴 **一定要剝註解**：B 在這個函式裡寫了三行註解解釋「不可以藏
    #    `.mnav__grp` 祖先」——不剝的話，這道守門會亮在**那段解釋**上，
    #    ☠️ 而他最省力的反應是**把解釋刪掉**（`git log` 上看起來只是
    #    整理註解），於是下一個人不知道為什麼不能往上爬，缺陷復發。
    #    🔑 〈防護的副作用落在盲側〉逐字記過這個形狀，而我第一版照樣踩了。
    body = _strip_js_comments(src[m.end():m.end() + 1400])
    for climbing in ("closest(", "parentNode", "parentElement", "mnav__grp"):
        assert climbing not in body, (
            "隱藏獎金入口的那一段裡出現了 `%s` —— **它在往上爬**。\n" % climbing
            + "☠️ 獎金連結的祖先是整個「財務」下拉面板：藏了它，"
              "出納／傳票／會計科目會一起消失。\n"
            + "⚙️ 只藏 `a[href$=\"bonus.html\"]` 本身。")


def test_the_bonus_page_is_not_gutted():
    """🔴 **`bonus.html` 原本的內容要還在，不可以整頁換成一句停用訊息。**

    ☠️ 最省力的實作是「把整頁刪掉、只留一句話」——它讓每一題都綠，
    而**開回來的那天，頁面已經不存在了**。
    🔑 〈防護的副作用落在盲側〉：「內容被刪掉」這一側，在旗標關著的
      期間**看不出來**。

    ⚙️ 三個彼此獨立的證據（任一個單獨都可能被巧合滿足）。
    📌 這一題現在是綠的，牙齒證明過：把頁面換成一句停用訊息，它會紅。

    📌 2026-09-24（SPEC-BONUS §十一）：頁面**依使用者要求整頁重做**成以案件為中心的新版
       （使用者：「上一次開發的內容我無法接受」）。第三個證據原本是「> 20000 字元」，
       新頁面約 1 萬 6 千字元 ⇒ 改成新頁面的結構標記（清單＋明細＋草稿編輯＋發放），
       仍然擋得住「整頁換成一句停用訊息」。
    """
    html = _bonus_page()
    assert "../js/bonus.js" in html, (
        "`bonus.html` 不再載入 `bonus.js` —— 頁面被掏空了。")
    assert "bn-card" in html, (
        "`bonus.html` 裡既有的版面（`bn-card`）不見了 —— 頁面被掏空了。")
    for marker in ("bn-list", "bn-case", 'data-testid="bn-draft"', 'data-testid="bn-mark-paid"'):
        assert marker in html, (
            "`bonus.html` 找不到 `%s` —— 以案件為中心的清單／明細／草稿／發放不在了，\n" % marker
            + "☠️ 像是**整頁被換掉**了。開回來的那天，內容已經不在。")
    assert len(html) > 10000, "`bonus.html` 只剩 %d 個字元 —— 頁面被掏空了。" % len(html)


def test_the_bonus_page_says_it_is_suspended():
    """🔴 **直開 `bonus.html` 網址時，頁面要說得出「暫停使用」。**

    ☠️ 只隱藏側邊欄入口的話，舊書籤、歷史紀錄、別人貼的連結**照樣打得開**。
    🔑 而它顯示的要是一句話，不是空白畫面：**空白與壞掉長得一樣**，
      使用者會來報修一個不是故障的東西。
    """
    html = _bonus_page()
    assert SUSPENDED in html, (
        "`frontend/pages/bonus.html` 裡找不到「%s」。\n" % SUSPENDED
        + "☠️ 藏側邊欄擋不住**直接打網址**（舊書籤／歷史紀錄／別人貼的連結）。")
    assert STATUS_ENDPOINT in html or STATUS_ENDPOINT in _sidebar(), (
        "頁面說得出「%s」，而沒有任何地方問過 `%s` ——\n"
        % (SUSPENDED, STATUS_ENDPOINT)
        + "☠️ 那代表停用訊息是**寫死**的，開不回來。")


def test_the_bonus_api_itself_is_untouched():
    """🔴 **`modules/payroll/api/bonus.py` 不可以讀這個旗標。**

    A 明著交代，理由是可量的：
    ```
    140+ 支既有獎金測試直接打 API
    後端 API 若跟著關 => 那些題全部變紅 => 這一包出不去
    ```
    ⚠️ 而它同時是一條**設計裁示**：這次拉掉的是**入口**，不是資料與行為
      （`SPEC-BN21.md` 留著，資料照樣在，開回來就能用）。
    📌 這一題的措辭要精確：不是「後端不可以有這個旗標」（旗標的家就在
      `modules/payroll/bonus.py`），是**獎金 API 那一支的行為不因旗標改變**。
    """
    src = (_root() / "backend" / "modules" / "payroll" / "api" / "bonus.py").read_text(
        encoding="utf-8")
    assert "BONUS_MODULE_ENABLED" not in src and "bonus_module_on" not in src, (
        "`modules/payroll/api/bonus.py` 讀了模組旗標 ——\n"
        + "☠️ 獎金 API 一跟著關，140+ 支直接打 API 的既有測試會全部變紅。")


# ══════════════════════════════════════════════════════════════════════
# ④ 量測裝置的正對照
# ══════════════════════════════════════════════════════════════════════


def test_the_scanner_itself_can_see_an_entry_that_is_definitely_there():
    """⚙️ **正對照：同一個查法，對一個一定存在的入口要看得見。**

    🔑 〈盤點工具的正對照〉：要先讓「已知的那一個」亮起來，才有資格報
    「那個不見了」。
    ☠️ 少了這一題，`_strip_js_comments()` 若把整個檔案剝成空字串，
      上面「入口還在」那幾題會紅，而訊息會指著別人寫對的程式碼。

    ⚙️ 誘餌挑 `voucher.html`：它與獎金入口在同一個函式、同一種寫法
    （`ni(pg('…'), …)`）——**走的是同一條量測路徑**。
    """
    src = _strip_js_comments(_sidebar())
    assert "voucher.html" in src, (
        "正對照失敗：剝完註解之後連傳票入口都找不到 ——\n"
        + "**壞掉的是這個檔案的掃描方式，不是 `sidebar.js`。**")
    assert len(src) > 10000, (
        "正對照失敗：剝完註解只剩 %d 個字元，剝過頭了。" % len(src))
