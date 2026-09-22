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
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
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


def test_ac1_the_page_creates_bonus_items_through_the_real_endpoint():
    """🔴 **那個寫入動作要打 `POST /api/bonus/items`。**

    ⚠️ 只驗「有寫入呼叫」不夠：一個只會 `POST /api/bonus/awards`
       （產生獎金單）的頁面也會過上一題，**而空狀態仍然無解** ——
       沒有項目就產不出單。
    """
    _html, js = _src()
    assert "/api/bonus/items" in js, (
        "`bonus.js` 沒有任何地方打 `/api/bonus/items` ——\n"
        + "☠️ 空狀態的**唯一出路**沒有接上：沒有項目就產不出獎金單。")


# ══════════════════════════════════════════════════════════════════════
# ② 空狀態要說出三件
# ══════════════════════════════════════════════════════════════════════

def test_ac1_the_empty_state_says_why_who_and_where():
    """🔴 **空狀態不可以只畫一個空盒子。**

    ```
    ① 為什麼是空的   ② 誰能解決   ③ 去哪裡解決
    ```
    ☠️ 少了 ②，`admin` 會在那一頁停住：他有權產生獎金單、**而沒有東西可以發**，
       畫面又沒告訴他要去找誰。
    ⚠️ 我**不釘字面文案**（那是 A 的事，不是我的）—— 每一件給幾個可接受的說法。
    """
    html, js = _src()
    text = _blank_html_comments(html) + "\n" + js

    missing = [k for k, words in THREE_THINGS.items()
               if not any(w in text for w in words)]
    assert not missing, (
        "獎金項目的空狀態沒有說出：%s\n" % "、".join(missing)
        + "📌 三件都要：**為什麼空／誰能解決／去哪裡解決**。\n"
        + "⚠️ 文案我不釘死，可接受的說法在 `THREE_THINGS`；\n"
          "   都不合用的話**退回給我**改那張表，不要改頁面去遷就它。")


def test_ac1_the_existing_award_empty_state_is_not_mistaken_for_this_one():
    """⚙️ **反向控制：頁面上已經有一個空狀態，而它講的是別的事。**

    ```
    bonus.html:99  <div class="bn-empty" x-show="!awards.length">
                   管理者看到空的 ＝ 還沒有人產生過獎金單
                   一般同仁看到空的 ＝ 目前沒有發給您的獎金
    ```
    ☠️ 上面那一題若只找「空」這個字，**現有的這一段就會讓它變綠** ——
       而「獎金項目」的空狀態根本還沒做。
    🔑 ⇒ 這一題釘住兩者是**兩個不同的區塊**：要有一個講「項目」的。
    """
    html, _js = _src()
    text = _blank_html_comments(html)
    assert "!awards.length" in text, (
        "找不到既有的獎金單空狀態（`!awards.length`）——\n"
        + "⚠️ 它被改寫了，這個反向控制要重做，**退回給我**。")

    # 🔴 我第一版寫 `re.search(r"(items|項目)", text)` ⇒ **綠了，而它匹配到的是
    #    CSS 的 `align-items`**（bonus.html:17/25/31）。判準比目標寬 ⇒ 假綠燈。
    #    ⇒ 收窄成「**Alpine 綁定運算式裡**的 items」，CSS 進不來。
    assert re.search(r'x-(?:show|if|for)="[^"]*\bitems\b', text), (
        "頁面上沒有任何綁到「獎金項目」清單的 Alpine 區塊 ——\n"
        + "☠️ 兩個空狀態講的是**不同的事**：\n"
          "    沒有獎金單  = 還沒有人產生過（可以自己去產生）\n"
          "    沒有獎金項目 = **產不出來**（而且只有 superadmin 修得了）")


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
