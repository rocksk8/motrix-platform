# -*- coding: utf-8 -*-
"""`AC1` 的第一個實例 · 獎金頁的**空狀態與兩級權限**（`SPEC-BN1-PLAN §2`）。

```
使用者逐字（§159b (8)）  「確認前後端跟頁面都有完成才算完整」
⇒ 「完整」= 後端 ＋ 前端 ＋ 頁面，**三者都完成**
```

# 🔴 為什麼空狀態是這一頁的主畫面，不是邊緣情境

```
bonus_items  正式庫 **0 列** ／ demo 庫 **0 列**
產品碼裡 INSERT INTO bonus_items **只有一處**（POST /api/bonus/items）
⇒ **每一個新客戶的第一天，獎金頁必定是空的**
```
📌 ⇒ 空狀態是**每個客戶看到的第一個畫面**。

# ☠️ 而真正要決定的是 `admin` 那一格 —— 他走不完

```
POST /api/bonus/items   require_superadmin=True   <= **只有 superadmin**
POST /api/bonus/awards  _is_manager               <= superadmin ＋ admin
```
⇒ 公司裡只有 `admin` 在用的那天，他打開頁面看到空清單，**而他修不好它**。
🔴 ⇒ 空狀態必須說出**三件**，不可以只畫一個空盒子：
```
① 為什麼是空的   「尚未建立任何獎金項目」
② 誰能解決       「請最高管理員（superadmin）到本頁『獎金項目』區塊新增」
③ 目前的我行不行  superadmin -> 直接給新增按鈕；admin -> **沒有按鈕**
```

# ⚠️ 這一支只證明「標記寫對了」，證明不了它會顯示出來

```
靜態  x-show 的運算式綁對了嗎        <= 本檔
執行  那個旗標真的從 session 來了嗎   <= e2e（三種身分各開一次）
```
🔑 〈缺欄位≠缺訊號〉的反面：**標記在、資料不在，畫面上什麼都沒有** ——
   `FN1` 那 10 題全綠而使用者撞到空白頁，就是這個。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_ac1_the_empty_state_says_why_who_and_where、test_ac1_the_existing_award_empty_state_is_not_mistaken_for_this_one、test_ac1_the_page_creates_bonus_items_through_the_real_endpoint
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
PAGE = ROOT / "frontend" / "pages" / "bonus.html"
JS = ROOT / "frontend" / "js" / "bonus.js"

#: 寫入型呼叫（`AC1` 的判準不是數 `<button>`，是數**會送出的那個動作**）。
WRITE_RE = re.compile(
    r"method\s*:\s*['\"](POST|PUT|PATCH|DELETE)['\"]", re.I)

#: 空狀態要說的三件事，各給幾個可接受的說法（**不釘字面文案**）。
THREE_THINGS = {
    "① 為什麼是空的": ("尚未建立", "還沒有建立", "沒有任何獎金項目", "尚未設定"),
    "② 誰能解決": ("最高管理員", "superadmin", "系統管理員"),
    "③ 去哪裡解決": ("獎金項目", "本頁", "下方"),
}


def _src():
    for p in (PAGE, JS):
        if not p.is_file():
            pytest.fail("`%s` 不見了 —— **退回給我**。"
                        % p.relative_to(ROOT).as_posix())
    return (PAGE.read_text(encoding="utf-8", errors="replace"),
            JS.read_text(encoding="utf-8", errors="replace"))


def _blank_html_comments(html):
    """把 `<!-- … -->` 換成等長空白（**保留行號**）。

    🔑 不這樣做的話，一段「解釋為什麼這裡沒有按鈕」的註解會讓守門變綠 ——
      而〈散文對工具是隱形的〉的反面同樣成立：**散文也會讓工具說謊**。
    """
    return re.sub(r"<!--.*?-->",
                  lambda m: " " * len(m.group(0)), html, flags=re.S)


# ══════════════════════════════════════════════════════════════════════
# ⓪ 量具
# ══════════════════════════════════════════════════════════════════════

def test_ac1_the_write_detector_can_tell_a_read_only_page_apart():
    """⚙️ **正對照：「有沒有寫入呼叫」這把尺分得出兩種頁嗎？**

    📌 `AC1` 的判準逐字：**不可以只數 `<button>`，要數「會送出的那一個動作」**。
    ☠️ 數按鈕的話，一個只有「重新整理」「匯出」按鈕的唯讀頁也會過。
    """
    read_only = "const r = await fetch('/api/bonus/awards', { headers: h })"
    assert not WRITE_RE.search(read_only), (
        "唯讀的 `fetch` 被判成寫入 —— **太寬**：%r" % read_only)

    writes = ("await fetch('/api/bonus/items', "
              "{ method: 'POST', headers: h, body: b })")
    assert WRITE_RE.search(writes), (
        "帶 `method: 'POST'` 的 `fetch` 沒被認出來 —— **太窄**：%r" % writes)

    lower = "fetch(u, { method: \"delete\" })"
    assert WRITE_RE.search(lower), "小寫的 method 沒被認出來：%r" % lower


def test_ac1_html_comments_do_not_count_as_page_content():
    """⚙️ **正對照：註解裡的字不算數。**

    ☠️ 一段「這裡刻意沒有新增按鈕，因為…」的註解會讓
       「頁面上找得到新增按鈕」那種守門**變綠** ——
       而畫面上一個按鈕都沒有。
    """
    html = '<!-- 新增獎金項目（尚未實作） -->\n<div>其他</div>'
    blanked = _blank_html_comments(html)
    assert "新增獎金項目" not in blanked, "註解沒被抹掉：%r" % blanked
    assert "其他" in blanked, "抹過頭了，把真的內容也吃掉：%r" % blanked
    assert blanked.count("\n") == html.count("\n"), "行號沒有被保留。"


# ══════════════════════════════════════════════════════════════════════
# ① `AC1` 本體：宣稱有畫面 ⇒ 要有會送出的動作
# ══════════════════════════════════════════════════════════════════════

def test_ac1_the_bonus_page_can_actually_write_something():
    """🔴 **獎金頁要有一個「會送出」的動作。**（`AC1` 條文）

    ```
    現況（實查）  frontend/js/bonus.js 只有一處 fetch：
                  GET /api/bonus/awards            <= **整頁唯讀**
    而 SPEC-BN1-PLAN §2 要的是：superadmin 在本頁**新增獎金項目**
    ```
    ☠️ 這正是我今天已經踩過兩次的那件事：**後端 ＋ 唯讀骨架 ＝ 回報完成**。
    ⚠️ `AC1` 的反向控制是「**唯讀頁要能明著登記成唯讀**」——
       那份登記表屬於 `AC1` 的通用守門，不在本檔；
       獎金頁**不是**唯讀頁（規格明著要它能新增），所以這裡不給豁免。
    """
    _html, js = _src()
    hits = WRITE_RE.findall(js)
    assert hits, (
        "`frontend/js/bonus.js` 裡沒有任何寫入型呼叫（只有 GET）——\n"
        + "☠️ 那是**唯讀骨架**，不是完成的功能。\n"
        + "📌 `SPEC-BN1-PLAN §2`：superadmin 要能在本頁新增獎金項目。\n"
        + "🔑 判準不是數 `<button>`，是數**會送出的那一個動作**。")


def test_ac1_scanner_positive_control_a_merged_empty_state_is_caught():
    """⚙️ **正對照：兩個空狀態若真的被合併成同一個判斷式，上面那道檢查
    要抓得到——用合成的假 HTML，不是真的產品碼。**

    ☠️ 這一題自己就抓到一次假陽性：第一版誘餌用 camelCase
    `awardsAndItemsBothEmpty()`，而主檢查當時是區分大小寫的
    `"items" not in award_expr`——`"Items"`（大寫）比對不到，誘餌反而
    會被誤判成「沒有合併」。已經改成 `.lower()` 比對，這裡同步修正。
    """
    fake_html = (
        '<section class="bn-sec" x-show="loaded">'
        '<div class="bn-empty" x-show="awardsAndItemsBothEmpty()"></div>'
        '</section>'
        '<section class="bn-sec" x-show="isManager && itemsLoaded">'
        '<div class="bn-blank" x-show="!items.length"></div>'
        '</section>'
    )
    m = re.search(
        r'<section class="bn-sec" x-show="loaded">(.*?)(?=<section|$)',
        fake_html, re.S)
    award_block = m.group(1)
    expr_m = re.search(r'class="bn-(?:empty|blank)"[^>]*\bx-show="([^"]+)"',
                       award_block)
    assert "items" in expr_m.group(1).lower(), (
        "誘餌本身沒有含 `items`，設計錯了，不是掃描器的問題。")
    # 這裡故意不再包一層 assert-not-in，直接示範：真的合併時，
    # `"items" not in award_expr.lower()` 這條斷言會是 False（也就是會紅）。


# ══════════════════════════════════════════════════════════════════════
# ③ 兩級權限：admin 走不完
# ══════════════════════════════════════════════════════════════════════

def test_ac1_the_create_control_is_gated_on_superadmin_not_on_manager():
    """🔴 **新增項目的入口要看 `superadmin`，不是看 `isManager`。**

    ```
    isManager   = superadmin ＋ admin      <= 產生獎金單的閘
    require_superadmin                      <= 新增項目的閘
    ```
    ☠️ 用 `isManager` 擋的後果：`admin` 看得到按鈕、按下去收到 **403**
       ⇒ 而這個模組已經確立「**按下去之前就該知道答案**」
         （`GET /base` docstring 逐字）。
    ⚠️ 旗標叫什麼由 B 決定 —— 我只釘「那段運算式裡出現 superadmin 這個概念」。
    """
    html, js = _src()
    text = _blank_html_comments(html) + "\n" + js

    assert re.search(r"superadmin|isSuper|canManageItems", text), (
        "頁面與 `bonus.js` 裡找不到任何 superadmin 的判斷 ——\n"
        + "☠️ 新增項目的入口若用 `isManager` 擋，`admin` 會**看得到按鈕、"
          "按下去收到 403**。\n"
        + "📌 `isManager` 是**產生獎金單**那一道閘，不是新增項目那一道。")


def test_ac1_the_page_knows_who_is_looking():
    """🔴 **頁面要拿得到自己的角色，否則上一題的閘門做不出來。**

    ```
    session  localStorage['motrix_session'] 有 role（notif.js:53 在用）
    而 bonus.js 目前只從 /api/bonus/awards 拿到 is_manager
    ⇒ **分不出 superadmin 與 admin**
    ```
    ⚠️ 兩條路都可以，我不釘機制：
    ```
    ① 前端讀 session 的 role
    ② 後端在某支端點多回一個「可不可以新增項目」的旗標（**比較好**：規則只有一份）
    ```
    🔑 ② 比較好的理由與 `plan` 存在的理由是同一個：
      把 `require_superadmin` 抄到 JS 就是**規則有兩份**。
    """
    _html, js = _src()
    # 🔴 我第一版把 `motrix_session` 放進這個 or ⇒ **綠了** ——
    #    而 `bonus.js` 讀 session 是為了**拿 token**，與「我是誰」無關。
    #    判準比目標寬 ⇒ 假綠燈。⇒ 只收「角色」這個概念的字。
    assert re.search(r"\brole\b|can_manage|canManage|is_super|isSuper", js), (
        "`bonus.js` 沒有任何地方拿得到「我是誰」——\n"
        + "☠️ 那表示上一題的閘門**做不出來**："
          "頁面只知道 `is_manager`，分不出 superadmin 與 admin。\n"
        + "📌 建議走後端多回一個旗標（規則只有一份），而機制由你決定。")
