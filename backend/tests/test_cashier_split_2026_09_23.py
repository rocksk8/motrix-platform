# -*- coding: utf-8 -*-
"""`UI9` · 出納拆回獨立頁面。

使用者裁示：
> 「財務報表歸財務報表，出納、財務、獎金計算、匯出傳票這些都是**獨立功能**，
>   並且有**獨立紀錄**」

---

# 🔴 這一題的真正風險不是「HTML 搬家」

`reports.js` 的 `_loadPayableSnapshot()` 註解逐字（2026-09-xx 寫的）：
> 「應收與應付**必須取自同一個來源**（出納佇列）。這一頁在『資金水位』已經定義過
> 『淨部位（應收 − 應付）』就是這兩個數字相減，快照沿用同一個定義才不會出現
> **兩個都叫『應收』卻不一樣的數字**。
> （**踩過**：一開始應收接的是 `activeOutstandingTotal`——那是應收報表的期別範圍
> 數字，跟出納的應收帳款是兩回事，畫面上會變成**快照說 0、上方 KPI 卡說一百多萬**。）」

☠️ **那個 bug 已經發生過一次，而它長什麼樣寫在碼裡。**
⇒ 拆開之後兩個頁面各自抓資料 ⇒ **最容易發生的事就是其中一邊改用自己手邊現成的彙總值。**

---

# ⚠️ 不要從 git 還原舊檔（`3fc64cf` 刪掉的那兩支）

```
舊 cashier.html   457 行（2026-08-31 之前）
現在的出納面板    270 行（reports.html :2041~:2310）
⇒ **不一樣**
```
✅ 而我量過：**現在的面板與併入當時 byte 級相同（270 行 → 270 行，差異 0 行）**，
`reports.js` 側出納自己的識別字**沒有任何一行被修改過** ——
併入之後被加的全部是**報表側**去用出納資料的程式碼。
⇒ **內容要從現在的 `reports.html`／`reports.js` 抽，不要從 git 還原。**
🔑 舊版只能當「頁面外殼」的參考（`auth-guard`／script 標籤／版面）。
⚠️ **這一段要留著** —— 否則下一個人看到「git 歷史裡有」會直接還原，
   而那會把 `_loadPayableSnapshot` 之前的舊行為一起帶回來。

---

# 📌 檔名沿用 `frontend/pages/cashier.html`（A 已裁）

```
✅ 舊書籤直接活過來，而那個 1,198 bytes 的轉址存根被覆蓋 ⇒ 轉址消失
✅ 出納有自己的檔名 ⇒ `act()`／`_deniedPages` 那一整族問題**自然消失**
   （`UI7` 因此標成「已不需要」，不是「延後」）
☠️ 另取檔名的話：舊書籤會轉到 `reports.html?tab=cashier`，
   **而那個頁籤即將不存在** ⇒ 使用者點舊書籤會進到一個沒有那個頁籤的頁
```
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
CASHIER_HTML = _ROOT / "frontend" / "pages" / "cashier.html"
REPORTS_HTML = _ROOT / "frontend" / "pages" / "reports.html"
REPORTS_JS = _ROOT / "frontend" / "js" / "reports.js"

#: 應收／應付**唯一**的來源。兩個頁面都必須讀它們。
QUEUE_ENDPOINTS = ("/api/cashier/payable-queue", "/api/cashier/receivable-queue")

#: 那個踩過的錯誤來源 —— 報表側的期別範圍數字，**不是**出納的應收帳款。
_WRONG_SOURCE = "activeOutstandingTotal"


def _read(p):
    assert p.exists(), "找不到 %s" % p
    return p.read_text(encoding="utf-8")


def _cashier_js():
    """出納那一側的 JS —— 獨立檔或內嵌都接受，**而必須找得到。**

    ⚠️ 刻意不寫死「一定是 `frontend/js/cashier.js`」：那是實作決定。
       但**找不到任何一份**時要紅，不可以因為量不到而綠。
    """
    cand = [_ROOT / "frontend" / "js" / "cashier.js",
            _ROOT / "frontend" / "static" / "cashier.js"]
    for p in cand:
        if p.exists():
            return p.name, p.read_text(encoding="utf-8")
    html = _read(CASHIER_HTML)
    if "<script" in html and "/api/cashier/" in html:
        return "cashier.html（內嵌 script）", html
    pytest.fail(
        "找不到出納那一側的 JS —— 找過：%s，以及 `cashier.html` 的內嵌 script。\n"
        % [str(p) for p in cand]
        + "🔑 **儀器失效**：下面每一題都會因為量不到而綠。")


# ══════════════════════════════════════════════════════════════════════
# UI9 · 出納是一個真的頁面
# ══════════════════════════════════════════════════════════════════════

def test_ui9_cashier_html_is_a_real_page_not_a_redirect_stub():
    """🔴 `UI9`：**`cashier.html` 要變回一個真的頁面。**

    現況是 1,198 bytes 的轉址存根：
    ```html
    <title>出納 — 已併入營運報表模組</title>
    <script>location.href = 'reports.html?tab=cashier'</script>
    ```
    ☠️ 拆完之後它**必須**被覆蓋 —— 否則舊書籤會轉到一個
    **即將不存在的頁籤**上，而使用者看到的是一個沒有出納的報表頁。

    ⚙️ 兩個方向都要驗：
    ```
    轉址必須消失      ← 否則這一頁永遠到不了
    出納內容必須出現  ← 否則「轉址拿掉了」也會綠，而那是一個空白頁
    ```
    """
    html = _read(CASHIER_HTML)
    assert "reports.html?tab=cashier" not in html, (
        "`cashier.html` 裡還有 `reports.html?tab=cashier` ——\n"
        "☠️ 那個轉址會把使用者送到一個**即將不存在的頁籤**上。")

    markers = [m for m in ("cashierSub", "payable-queue", "receivable-queue")
               if m in html or m in _cashier_js()[1]]
    assert len(markers) >= 2, (
        "`cashier.html` 找不到出納的內容（命中：%s）——\n" % markers
        + "☠️ 「轉址拿掉了」也會讓上一個斷言綠，**而那是一個空白頁**。")


def test_ui9_reports_no_longer_carries_the_cashier_tab():
    """🔴 `UI9`：**`reports.html` 不可以再有出納頁籤。**

    ☠️ 兩邊都留著的話會長出這個：使用者在側欄點「出納」到獨立頁，
    而報表頁裡**還有一個一模一樣的頁籤** ——
    🔑 **兩份畫面、兩條載入路徑，而它們會在不同時間點抓到不同的數字。**
    📌 那正是這一整件事要修掉的東西（「兩個功能共用一頁」）。

    ⚙️ 錨點用**完整屬性**不用子字串：`x-show="activeTab==='cashier'"`。
    ⚠️ 只找 `activeTab==='cashier'` 的話會命中**頁籤按鈕**那一行
    （`:class="{on:activeTab==='cashier'}"`）—— 我第一次量就踩到它，
    結果把 270 行的面板量成 2 行。
    """
    html = _read(REPORTS_HTML)
    panel = 'x-show="activeTab===\'cashier\'"'
    assert panel not in html, (
        "`reports.html` 裡還有出納面板（`%s`）——\n" % panel
        + "☠️ 兩份畫面、兩條載入路徑 ⇒ 它們會在不同時間點抓到不同的數字。")
    assert "showCashierTab()" not in html, (
        "`reports.html` 裡還有出納頁籤按鈕（`showCashierTab()`）——\n"
        "☠️ 面板拿掉而按鈕留著 ⇒ 點下去是一片空白。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 主題 · 兩個頁面必須讀同一組端點
# ══════════════════════════════════════════════════════════════════════

def _assignments_to(src, names):
    """`[(行號, 名稱, 那一行)]` —— `this.<name> = …` 的每一處。

    ⚠️ 字界是**預設要求不是特例**：這個 codebase 的命名慣例
       （單數→複數、名詞→名詞+狀態）讓前綴碰撞變成常態 ——
       `receivable` ⊂ `receivablesData`、`payable` ⊂ `payableSnapLoaded`。
    ☠️ 我實際踩過：用 `receivable` 掃出 8 個 commit，印出來全是 `receivablesData`。
    """
    pat = re.compile(r"\bthis\.(%s)\s*=[^=]" % "|".join(names))
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        m = pat.search(line)
        if m:
            out.append((i, m.group(1), line.strip()))
    return out


def _enclosing_function(src, lineno):
    """往回找最近的函式宣告，回傳 `(名稱, 起始行)`；找不到回 `(None, None)`。"""
    lines = src.splitlines()
    decl = re.compile(r"^\s{2,6}(?:async\s+)?(?:get\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
    for i in range(lineno - 1, -1, -1):
        m = decl.match(lines[i])
        if m:
            return m.group(1), i + 1
    return None, None


def _function_body(src, start_line):
    """從函式宣告那一行起，用大括號配對取出整個函式本體。"""
    lines = src.splitlines()
    depth, out = 0, []
    for i in range(start_line - 1, len(lines)):
        out.append(lines[i])
        depth += lines[i].count("{") - lines[i].count("}")
        if i > start_line - 1 and depth <= 0:
            break
    return "\n".join(out)


@pytest.mark.parametrize("which", ["cashier", "reports"])
def test_ui9_both_sides_read_the_receivable_and_payable_queues(which):
    """🔴🔴 `UI9` 主題：**兩邊的應收／應付都必須來自出納佇列那兩個端點。**

    ```
    reports.html 的「資金水位」 ┐
    cashier.html 的應收／應付   ┘ 讀**同一組端點**（/api/cashier/*-queue）
    ```
    ☠️ 任何一邊改用報表側的彙總值 ⇒ **兩個都叫「應收」而數字不一樣**。
    🔑 而那不是假設 —— `reports.js` 的註解裡寫著它發生過：
       「快照說 0、上方 KPI 卡說一百多萬」。

    ⚙️ 判準是**每一處賦值的來源**，不是「這個檔裡有沒有出現那個網址」：
    ```
    每一個 `this.payable = …`／`this.receivable = …`
    ⇒ 它所在的函式裡必須有 `/api/cashier/*-queue`
    ```
    📌 那擋得住「在別的地方算好再塞進來」，而單純 `grep` 網址擋不住。

    ⚠️ **射程**：掃得到「誰呼叫哪個端點」，**掃不到「算出來的數字對不對」**。
    ⇒ **目視是最終驗收，交付說明不可以把這一格寫成「已驗證」。**（A 已寫進規格）
    """
    if which == "cashier":
        where, src = _cashier_js()
    else:
        where, src = REPORTS_JS.name, _read(REPORTS_JS)

    for ep in QUEUE_ENDPOINTS:
        assert ep in src, (
            "`%s` 裡找不到 `%s` ——\n" % (where, ep)
            + "☠️ 這一側的應收／應付不是來自出納佇列 ⇒ "
              "兩個頁面會對同一個數字給出不同的答案。")

    rows = _assignments_to(src, ("payable", "receivable"))
    assert rows, (
        "`%s` 裡一個 `this.payable =`／`this.receivable =` 都沒抓到 ——\n" % where
        + "🔑 **儀器失效**（〈沒抓到要被解釋成儀器失效，不可以被解釋成乾淨〉）。")

    bad = []
    for lineno, name, text in rows:
        fn, start = _enclosing_function(src, lineno)
        body = _function_body(src, start) if start else ""
        if not any(ep in body for ep in QUEUE_ENDPOINTS):
            bad.append("`%s`:%d 在 `%s()` 裡指派 `this.%s`，"
                       "而那個函式沒有讀出納佇列：%s"
                       % (where, lineno, fn, name, text[:60]))
    assert not bad, (
        "有賦值的來源不是出納佇列：\n  " + "\n  ".join(bad)
        + "\n☠️ 那正是踩過的那一次：應收接到報表側的期別範圍數字（`%s`），\n"
          "   畫面變成「快照說 0、上方 KPI 卡說一百多萬」。" % _WRONG_SOURCE)


def test_ui9_the_reports_snapshot_does_not_use_the_period_aggregate():
    """🔴 反向控制：**報表側不可以改用 `%s` 去填應收。**

    那是踩過的那一個具體錯誤來源 —— 報表的**期別範圍**數字，
    與出納的應收帳款是兩回事。
    ⚠️ 這一題釘的是**那一個字**，而上一題釘的是**結構**（賦值來源）。
    📌 兩個都要：這一題擋得住「換回那個舊來源」，
       上一題擋得住「換成另一個我沒想到的來源」。
    🔑 **只有後者的話，下一次用別的名字就繞過去了；
       只有前者的話，它只守得住一個已知的錯。**
    """ % _WRONG_SOURCE
    src = _read(REPORTS_JS)
    rows = _assignments_to(src, ("payable", "receivable"))
    assert rows, "一個賦值都沒抓到 —— **儀器失效**。"
    bad = [(ln, t) for ln, _n, t in rows if _WRONG_SOURCE in t]
    assert not bad, (
        "應收／應付被接到 `%s`：\n  " % _WRONG_SOURCE
        + "\n  ".join(":%d %s" % b for b in bad)
        + "\n☠️ 那是報表的期別範圍數字，不是出納的應收帳款。\n"
          "🔑 畫面會變成「快照說 0、上方 KPI 卡說一百多萬」（註解裡的原話）。")


def test_ui9_the_snapshot_loader_stays_on_the_reports_side():
    """🔴 `_loadPayableSnapshot()` **留在報表側**（A 已裁）。

    它是**報表的**資金水位在用的，不是出納的東西。
    ☠️ 把它一起搬走 ⇒ 報表的資金水位那一格會顯示 0 或「無權限」，
    🔑 **而 0 比留白更糟：它看起來像「這期沒有任何應付」。**
       （那句話是 `reports.js` 自己的註解寫的。）
    """
    src = _read(REPORTS_JS)
    assert "_loadPayableSnapshot" in src, (
        "`reports.js` 裡找不到 `_loadPayableSnapshot` ——\n"
        "☠️ 它被一起搬走了 ⇒ 報表的資金水位會顯示 0，"
        "而**0 比留白更糟：它看起來像「這期沒有任何應付」**。")


def test_ui9_the_measurement_tools_here_can_actually_fail():
    """⚙️ **正對照** —— 本檔幾個量法自己要分辨得出差異。

    ⚠️ 它與受測物**走同一條量測路徑**（`_assignments_to`／`_enclosing_function`），
    那是刻意的：它分辨的是**「量法壞了」**。
    而各題裡的 `assert rows` 走的是「檔案裡有沒有那個賦值」，
    分辨的是**「檔案是空的／賦值改名了」**。
    📌 **兩個分辨的不是同一件事，刪掉任何一個都會少一種辨識力。**

    🔑 而字界那一條要驗**它實際踩過的那一個**：
    `receivable` 不可以吃進 `receivablesData`。
    """
    sample = "\n".join([
        "    async loadX() {",
        "      this.receivablesData = await r.json()",
        "      this.receivable = await q.json()",
        "    },",
    ])
    hits = _assignments_to(sample, ("payable", "receivable"))
    assert [h[1] for h in hits] == ["receivable"], (
        "`_assignments_to` 抓到 %s —— 它把 `receivablesData` 也算進去了。\n"
        % [h[1] for h in hits]
        + "🔑 這個 codebase 的命名慣例（單數→複數）讓前綴碰撞是**常態**，"
          "字界是預設要求不是特例。")

    fn, start = _enclosing_function(sample, 3)
    assert fn == "loadX", (
        "`_enclosing_function` 回 %r，應該是 `loadX` —— 量法壞了，"
        "而它壞掉的樣子是**每一題都綠**（沒有函式 ⇒ body 為空 ⇒ 不會被列進 bad）。"
        % fn)


# ══════════════════════════════════════════════════════════════════════
# 🔴 使用者重啟後**第一個動作**就是點「出納」——這一節守那條路徑
# ══════════════════════════════════════════════════════════════════════

#: 一個正常內頁必須載入的東西（照 `reports.html` 的 shell）。
_PAGE_SHELL = {
    "auth-guard.js":  "沒有它 ⇒ 未登入也打得開，而資料會被 API 擋成一片 403",
    "alpine-":        "沒有它 ⇒ 所有 x-data／x-show 都不會運作，整頁是死的",
    "sidebar.js":     "沒有它 ⇒ **沒有導覽列**，使用者進去之後出不來",
    "style.css":      "沒有它 ⇒ 版面整個散掉",
}


def test_ui9_the_cashier_page_can_actually_boot():
    """🔴🔴 **使用者重啟後第一個動作就是點「出納」——這一題守那一下。**

    ☠️ 一個「內容抄過去了、而 shell 沒抄」的頁面**通過上面每一題**：
    轉址拿掉了 ✅、出納內容在 ✅、端點在 ✅ ——
    🔑 **而使用者打開它看到的是一片沒有導覽列的死畫面。**

    ⚠️ 最容易漏的是 `data-no-topbar`：現在那個存根的 `<body>` **宣告了它**，
    而它的理由寫在檔案裡：
    > 「這是一頁**轉址頁**⋯沒有 app shell 也不該有頂欄。
    >   🔑 宣告它是為了讓『**刻意沒有**』與『**忘了加**』分得開 ——
    >   `sidebar.js` 找不到掛載點又沒有這個宣告時會 `console.error`。」
    ⇒ **覆蓋那個檔案時若把 `<body data-no-topbar>` 一起留著**，
      `sidebar.js` 會**安靜地**不掛頂欄 —— 那個宣告的作用就是讓它安靜。
    ☠️ **於是最該叫的那一次，它不會叫。**
    📌 〈防護的副作用落在盲側〉：一個為了「分辨刻意與遺忘」而設的宣告，
       在**被複製到不該有它的地方**時，正好關掉了唯一的警報。
    """
    html = _read(CASHIER_HTML)

    missing = [(k, why) for k, why in _PAGE_SHELL.items() if k not in html]
    assert not missing, (
        "`cashier.html` 缺少內頁 shell：\n  "
        + "\n  ".join("`%s` —— %s" % m for m in missing)
        + "\n☠️ 上面每一題都會綠（轉址拿掉了、內容在、端點在），"
          "**而使用者打開它看到的是一片死畫面**。")

    assert "data-no-topbar" not in html, (
        "`cashier.html` 的 `<body>` 還留著 `data-no-topbar` ——\n"
        "☠️ 那是**轉址存根**的宣告，它的作用是讓 `sidebar.js` 找不到掛載點時"
        "**不要 `console.error`**。\n"
        "🔑 留著它 ⇒ 沒有頂欄，而且**沒有任何警告** —— "
        "最該叫的那一次它不會叫。")

    assert "已併入營運報表模組" not in html, (
        "`cashier.html` 的標題還是存根那一個（「已併入營運報表模組」）——\n"
        "☠️ 分頁標題與瀏覽紀錄會說這一頁不存在，而它就在使用者眼前。")


def test_ui9_the_cashier_page_loads_all_five_of_its_own_endpoints():
    """🔴 出納頁要**自己**載得到它需要的全部資料。

    ```
    /api/cashier/payable-queue          應付佇列
    /api/cashier/receivable-queue       應收佇列
    /api/cashier/execution-history      執行歷史
    /api/cashier/export                 匯出
    /api/settings/t100-export-config    銀行帳戶清單（標記付款／收款的下拉）
    ```
    ✅ 我量過：出納面板讀元件狀態 `data`（那包**只有 admin+ 會載入**的）**0 處**
    ⇒ 它不依賴 `reports` 的任何資料，五個端點就是它的全部來源。

    ⚠️ 而 `t100-export-config` 這一份在拆完之後會是**第四份**
    （`reports`／`case-management`／庫存管理／出納）——
    📌 **A 裁定刻意複製，同時發了 `FE1` 排 `NEXT`**：
       不在 `UI9` 裡抽，是因為那會讓這一次的 diff 同時涵蓋「拆頁」與
       「跨四檔重構」，**出事時分不出是哪一件**。
    🔑 而它不是寫成註解放過 —— **一個編號不是註解，是一筆有號碼的欠帳。**
    """
    where, src = _cashier_js()
    need = list(QUEUE_ENDPOINTS) + [
        "/api/cashier/execution-history",
        "/api/cashier/export",
        "/api/settings/t100-export-config",
    ]
    missing = [e for e in need if e not in src]
    assert not missing, (
        "出納那一側（`%s`）沒有載這些端點：\n  " % where + "\n  ".join(missing)
        + "\n☠️ 缺哪一個，畫面上對應的那一塊就是空的 —— "
          "而空的看起來像「這期沒有資料」，不像「沒載到」。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 UI9 補 · **按鈕按下去要有東西可以開**
# ══════════════════════════════════════════════════════════════════════
#
# ☠️ `UI9` 交綠、使用者實看說「ok」之後才發現：**四個 modal 一個都沒搬過去。**
#    五個按鈕（`openPayVoucherModal`／`openInvoiceModal`×2／`openReceiveModal`／
#    `openBankPayModal`）按下去**不會有任何反應**。
#
# 🔑 **而我的題擋不到它，成因值得留著**：
# ```
# 我釘了  轉址消失／內容出現／五個端點／shell 能 boot／側欄指向
# 我沒釘  **按鈕按下去有沒有東西可以開**
# ```
# 我用 div 深度配對量「出納面板」量得很準（270 行，byte 級比對過），
# **而那個準確的邊界正好把 modal 排除在外** —— 它們在 `reports.html` 的另一個區段。
# ⇒ ⇒ **邊界量得越準，越容易漏掉邊界外的東西。** 而 B 照著那個邊界搬，自然就漏了。
#
# 📌 使用者說「出納我看到了，ok」—— **那句話只涵蓋他看到的**，他沒有點那四個按鈕。

#: 「這個 modal 打得開」的兩種寫法。
#: ⚠️ v1 只認 `= true`，而 `invoiceModal` 是**物件**（`{show, item, no}`）
#:    ⇒ v1 只抓到 3 個，實際是 **4 個**。今天第四次判準太窄。
_MODAL_OPEN = re.compile(
    r"this\.(\w*[Mm]odal)\s*=\s*(?:true|\{[^}]*?\bshow\s*:\s*true)")
#: 「這個 modal 有標記」—— 兩種繫結形式都算。
_MODAL_SHOW = re.compile(r'x-show="\s*(\w*[Mm]odal)(?:\.show)?\s*"')


def _modal_sets(html_path, js_src):
    html = _read(html_path)
    return set(_MODAL_OPEN.findall(js_src)), set(_MODAL_SHOW.findall(html))


def _modal_side(which):
    """`(樣板, JS, 標籤)` —— modal 不變量**兩側都要驗**。"""
    if which == "cashier":
        _w, js = _cashier_js()
        return CASHIER_HTML, js, "cashier.html／cashier.js"
    return REPORTS_HTML, _read(REPORTS_JS), "reports.html／reports.js"


@pytest.mark.parametrize("which", ["cashier", "reports"])
def test_ui9_every_modal_the_page_can_open_is_actually_on_the_page(which):
    """🔴🔴 **出納頁打得開的每一個 modal，都要在出納頁上。**

    ```
    cashier.js  會設 payVoucherModal／receiveModal／bankPayModal／invoiceModal
    cashier.html 裡的 modal 標記  ⇒ **0 個**
    ⇒ 標記已匯款／標記已收款／開立發票／銀行對帳比對 —— **四個動作全是死的**
    ```
    ☠️ 而它**不會報錯**：Alpine 設一個沒有人繫結的狀態是合法的，
    使用者按下去只是**什麼都沒發生**。
    🔑 那比「壞掉」難發現 —— **壞掉會有紅字，什麼都沒發生只會讓人再按一次。**

    ⚙️ 這一題是**通用的**（不只出納）：任何頁面，
    `this.xxxModal = true`（或 `= {show:true}`）而畫面上沒有 `x-show="xxxModal"`
    ⇒ 紅。
    📌 它同時是一個**遷移守門**：把功能搬到新頁時，
       「面板搬了而 modal 沒搬」是這一類搬遷最典型的漏法。

    ## ⚠️ v1 只驗出納那一側，而那是**我 20 分鐘前才修過的同一種不對稱**

    ```
    v1  只掃 cashier.html ⇒ 看不到「樣板搬走了而 opener 留在原地」
    實測 reports 那一側現在有 4 個打得開而沒標記
        （bankPay／invoice／payVoucher／receive）
    ```
    🔑 我在**死碼題**上剛修完「只掃一側」這件事，**而這一題有一模一樣的毛病** ——
       **我修了一個實例，沒有修那個類別。**
    📌 〈修作法不要修結果〉：判準是「這個修法會不會讓下一次不可能發生」，
       而我當時答的是「**這一支**不會了」。
    ⚠️ 而 A 以為這一題已經守得到那一側 —— **一個「通用的」標籤會讓人以為它掃了全部。**
    """
    html_path, js, where = _modal_side(which)
    openable, rendered = _modal_sets(html_path, js)
    assert openable, (
        "`%s` 裡一個 `this.*Modal = true` 都沒抓到 ——\n" % where
        + "🔑 **儀器失效**：這一題會因為量不到而綠。")

    missing = sorted(openable - rendered)
    assert not missing, (
        "`%s` 打得開這些 modal，而畫面上**沒有它們的標記**：%s\n"
        % (where, missing)
        + "☠️ 按鈕按下去**什麼都不會發生**，而且不報錯 ——\n"
          "   Alpine 設一個沒有人繫結的狀態是合法的。\n"
        "🔑 那比「壞掉」難發現：壞掉會有紅字，什麼都沒發生只會讓人再按一次。\n"
        "📌 它們現在還在 `reports.html`（註解自己寫著"
        "「出納 Modal 群組⋯**原獨立 cashier.html**」）。")


def test_ui9_reports_has_no_cashier_buttons_left_behind():
    """🔴 另一側：**`reports.html` 不可以還留著出納的按鈕。**

    ⚠️ **而我要更正我自己一句**：我先回報時說那四個 modal 在 `reports.html`
    「是孤兒」。**更精確的實情是**：
    ```
    reports.html 的 modal 標記      ✅ 還在
    reports.js  的 opener 函式      ✅ 還在（四支各 1 處）
    reports.html 的**按鈕**         ❌ 已經沒有（0 處）
    ```
    ⇒ 它們**不是打不開**（JS 路徑完整），只是**沒有東西去叫它**。
    🔑 差別有實質後果：**清掉它們是整理，不是修 bug** ——
       而我原本那句話會讓人以為 `reports` 那邊也壞了。
    📌 〈發現自己上一則有問題不要等下一次被問〉：別人照上一則在排優先序。

    ⚙️ 這一題釘的是**按鈕**那一層（使用者點得到的東西）：
       出納的按鈕不可以出現在報表頁上。
    """
    html = _read(REPORTS_HTML)
    openers = ("openPayVoucherModal", "openReceiveModal",
               "openInvoiceModal", "openBankPayModal")
    left = [o for o in openers if o in html]
    assert not left, (
        "`reports.html` 還有出納的按鈕：%s\n" % left
        + "☠️ 使用者會在報表頁上按到出納的動作 —— 而出納已經是獨立頁面了。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 反向 · **`cashier.js` 定義的東西要有人用**（B 提，而它抓到相反的錯）
# ══════════════════════════════════════════════════════════════════════
#
# B 的掃法是**雙向**的，而只有反向那一邊抓得到這次的缺件：
# ```
# ① 前向  樣板指向的東西 → 在不在 JS      ⇒ **9 個 handler 全過**
# ② 反向  JS 定義的東西 → 樣板有沒有引用  ⇒ 抓到 33 個 orphan
# ```
# 🔑 B 的原話：「我上一次就是只做了這個方向（①），
#    **而它永遠抓不到「handler 在、而它要開的 UI 不在」**。」
#
# 📌 而 B 找到一個**方向相反**的問題：它抽 `reports.js` 的函式區時用
#    **行號區間**當邊界 ⇒ **區間外的漏掉（modal）、區間內不屬於出納的多抄**
#    ⇒ `exportTaxInvoices()` 被抄進 `cashier.js`，而它的按鈕在
#      `reports.html:1823` 的「稅務匯出」區段 —— **它是報表側的。**
# 🔑 與我那次「邊界量得越準越容易漏掉邊界外的東西」是**同一個根因的兩個方向**。

#: 目前允許懸空的函式，**每一筆都要指向一個原因**。
#: ⚠️ 這不是「排除清單」——下面那道反向控制要求：**不再懸空的項目必須從這裡移除**，
#:    否則它會爛掉，而一份爛掉的允許清單與「全部寫進去變綠」是同一件事。
_ALLOWED_DANGLING = {
    "confirmT100Imported": "T100 匯出 UI 還在 reports（FN3）",
    "exportT100Vouchers":  "同上（FN3）",
    "saveT100Config":      "同上（FN3）",
    "toggleT100Config":    "同上（FN3）",
}


def _dangling_functions(html_path=None, js_src=None):
    """一個頁面的 JS 裡**沒有人叫**的公開方法。

    ⚠️ 底線開頭的（`_token`／`_localDateStr`…）不算 —— 那是慣例上的內部工具，
       而它們被呼叫的方式不一定抓得到。
    ⚠️ **呼叫端要認四種接收者**：`this.` / `self.` / `that.` / `vm.`。
    ☠️ v1 只認 `this.` ⇒ 它把 `initCharts()` 報成死碼，**而那支是用
       `self.initCharts()` 在 `requestAnimationFrame` 裡叫的**（`reports.js:1250`）。
    🔑 今天第五次判準太窄，**而這一次的方向最壞：它會讓人去刪一個還在用的函式。**
    """
    if html_path is None:
        html_path = CASHIER_HTML
    if js_src is None:
        _where, js_src = _cashier_js()
    html = _read(html_path)
    defs = set(re.findall(
        r"^\s{4}(?:async\s+)?([a-zA-Z_$][\w$]*)\s*\([^)]*\)\s*\{", js_src, re.M))
    defs -= {"if", "for", "while", "switch", "catch", "function", "return"}
    used = set(re.findall(r"\b([a-zA-Z_$][\w$]*)\s*\(", html))
    used |= set(re.findall(
        r"(?:this|self|that|vm)\.([a-zA-Z_$][\w$]*)\s*\(", js_src))
    return set(d for d in defs if d not in used and not d.startswith("_"))


#: `reports.js` 裡**出納留下的尾巴** —— `UI9` 把樣板搬走了，而 JS 留在原地。
#: 🔑 它是 `cashier.js` 那個「多抄」的**鏡像**：
#:    多抄＝該留的被帶走；這個＝**該走的被留下**。同一次搬遷的兩個方向。
#: ⚠️ 而我原本那道死碼題**只掃 `cashier.js`** ⇒ 它看不到這一側。
#:    ⇒ 現在改成對稱的：**兩支都掃。**
_REPORTS_CASHIER_TAIL = frozenset((
    "canExecuteCashier", "confirmBankPay", "confirmInvoice", "confirmPayVoucher",
    "confirmReceive", "exportCashierHistory", "isDueSoon", "openBankPayModal",
    "openInvoiceModal", "openPayVoucherModal", "openReceiveModal",
    "toggleReceived", "uploadBankCsv",
))


def test_ui9_nothing_was_over_copied_into_the_cashier_page():
    """🔴 **`cashier.js` 不可以有「沒有人叫」的函式**（允許清單以外）。

    ☠️ 現況抓到 `exportTaxInvoices()` —— 它的按鈕在
    `reports.html:1823` 的「**稅務匯出**」區段，**它不是出納的東西**。
    🔑 B 用行號區間抽函式 ⇒ **區間外的漏掉、區間內不屬於出納的多抄**，
       而這一題守的是後者。

    ⚙️ **而死碼的代價不是「多幾行」**：
    ```
    下一個人讀 cashier.js 看到 exportTaxInvoices()
    ⇒ 他會以為出納頁有稅務匯出功能
    ⇒ 而他可能為它加一顆按鈕 —— 一個在錯的頁面上的正確功能
    ```
    📌 那與〈已知的代價 vs 要修的東西〉是同一族：**留著它比刪掉它貴。**
    """
    dangling = _dangling_functions()
    assert dangling, (
        "`cashier.js` 裡一個懸空函式都沒抓到 —— **儀器失效**"
        "（連允許清單裡那幾個都該被抓到）。")

    bad = sorted(dangling - set(_ALLOWED_DANGLING))
    assert not bad, (
        "`cashier.js` 有沒有人叫的函式：%s\n" % bad
        + "☠️ 下一個人讀到它會以為出納頁有那個功能，"
          "而他可能為它加一顆按鈕 —— **一個在錯的頁面上的正確功能**。\n"
        "🔑 目前已知的合理懸空只有這些：\n  "
        + "\n  ".join("%-22s %s" % kv for kv in sorted(_ALLOWED_DANGLING.items())))


def test_ui9_the_dangling_allowlist_does_not_rot():
    """⚙️ **反向控制：允許清單裡不再懸空的項目，必須被移除。**

    ☠️ 少了這一題，`_ALLOWED_DANGLING` 會變成一份**只進不出**的清單 ——
    🔑 而那與〈守門要配反向控制，否則可以靠把東西全寫進排除清單變綠〉
       是同一件事，只是慢一點：**清單不會一次爛掉，它會一筆一筆爛掉。**

    📌 具體會發生的時間點：
    ```
    modal 搬過來 ⇒ 四個 confirm* 不再懸空 ⇒ **這一題紅** ⇒ 有人把它們刪掉
    FN3 做完     ⇒ 四個 T100 不再懸空     ⇒ **這一題紅** ⇒ 同上
    ```
    ⇒ 那正是我們要的：**清單自己會縮短，而不是有人記得去縮它。**
    ⚠️ 而它有一個代價要知道：**B 補完 modal 的那一刻，這一題會紅** ——
       那不是迴歸，是這一題在做它的事。訊息裡講清楚了。
    """
    dangling = _dangling_functions()
    stale = sorted(set(_ALLOWED_DANGLING) - dangling)
    assert not stale, (
        "允許清單裡這些已經**不再懸空**了：%s\n" % stale
        + "⇒ 把它們從 `_ALLOWED_DANGLING` 移除。\n"
        "🔑 這不是迴歸 —— 它表示對應的那件事**做完了**"
        "（modal 搬過來了，或 `FN3` 做完了）。\n"
        "☠️ 不移除的話，這份清單會變成一份只進不出的排除清單。")


def test_ui9_reports_js_has_no_cashier_tail_left_behind():
    """🔴 **對稱的另一側：`reports.js` 不可以留著出納的函式。**

    ```
    cashier.js 那一題  多抄 ＝ **該留的被帶走**（exportTaxInvoices）
    這一題             留尾 ＝ **該走的被留下**
    ⇒ 同一次搬遷的兩個方向，而我原本只掃了其中一支
    ```
    ☠️ 實測 `reports.js` 有 **13 個**沒有人叫的公開方法，**全部是出納的**：
    `openPayVoucherModal`／`confirmReceive`／`uploadBankCsv`／`canExecuteCashier`⋯
    ⇒ 樣板在 `UI9`＋補件時搬走了，而 JS 留在原地。

    🔑 **而它比死碼更糟一點**：那些函式**還會動**。
    ```
    openPayVoucherModal() 在 reports.js 裡仍然會設 this.payVoucherModal = true
    ⇒ 而 reports.html 已經沒有那個 modal 的標記
    ⇒ 哪天有人在報表頁上接一顆按鈕叫它 ⇒ **又是一次「按了沒反應」**
    ```
    📌 〈已知的代價 vs 要修的東西〉：留著它比刪掉它貴。

    ⚠️ **而這一題現在是紅的，它不在 `FN3` 的範圍裡** ——
       它是 `UI9` 那一次搬遷的尾巴。**要不要現在清由 A 排。**
    """
    dangling = _dangling_functions(REPORTS_HTML, _read(REPORTS_JS))
    tail = sorted(dangling & _REPORTS_CASHIER_TAIL)
    assert not tail, (
        "`reports.js` 還留著 %d 個出納的函式（沒有人叫）：\n  " % len(tail)
        + ", ".join(tail)
        + "\n☠️ 它們不只是死碼 —— `open*Modal` 仍然會設那些狀態，"
          "而 `reports.html` 已經沒有對應的標記 ⇒\n"
          "   哪天有人在報表頁接一顆按鈕叫它，**又是一次「按了沒反應」**。\n"
        "📌 這是 `UI9` 那一次搬遷的尾巴，不在 `FN3` 範圍裡。")


def test_ui9_the_tail_list_does_not_rot():
    """⚙️ 反向控制：`_REPORTS_CASHIER_TAIL` 裡**已經不存在**的名字要移除。

    ☠️ 少了它，B 清掉那 13 支之後這份清單還留著 13 個名字 ——
    而下一個人會以為 `reports.js` 裡還有那些東西。
    🔑 與 `_ALLOWED_DANGLING` 那道控制同一個形狀：**清單要自己會縮短。**

    ⚠️ 判準是「這個名字還在不在 `reports.js` 的定義裡」，
       **不是**「它還懸不懸空」—— 那兩件事不一樣：
    ```
    它被刪掉了        ⇒ 這裡要移除 ✅
    它被接上了呼叫端  ⇒ 它不再懸空，**而名字還在** ⇒ 這裡**不該**移除
    ```
    📌 那是刻意的：這份清單記的是「出納留在報表側的東西」，
       而「有人在報表頁上接了它」是一個**更該紅**的狀態，由上一題管。
    """
    js = _read(REPORTS_JS)
    defined = set(re.findall(
        r"^\s{4}(?:async\s+)?([a-zA-Z_$][\w$]*)\s*\([^)]*\)\s*\{", js, re.M))
    stale = sorted(_REPORTS_CASHIER_TAIL - defined)
    assert not stale, (
        "`_REPORTS_CASHIER_TAIL` 裡這些已經不在 `reports.js` 了：%s\n" % stale
        + "⇒ 把它們從那個常數移除。**這不是迴歸 —— 它表示清乾淨了。**")


# ══════════════════════════════════════════════════════════════════════
# 🔴🔴 升級 · **呼叫／定義全面比對**（不只 modal）
# ══════════════════════════════════════════════════════════════════════
#
# ☠️ 使用者實際踩到：出納頁「標記已收款」→ 按確定 →
#    `網路錯誤：this._displayName is not a function`
#
# 🔑 A 的更正逐字：
# > 「我讓你釘的『每一個 `open*Modal` 都要有對應的 modal 本體』**太窄**，
# >   真正該釘的是『**`cashier.js` 裡每一個 `this.X()` 呼叫，
# >   都要在這一頁的 JS 裡定義得到**』——後者涵蓋前者。」
#
# ⚠️ **而那個錯誤訊息一開始就在 A 手上**，它被讀成選單工具的 UI 故障
#    —— **它是畫面上的真實輸出。**
# 📌 第二個缺陷在措辭：一個 `TypeError` 被 `catch` 報成「**網路錯誤**」
#    ⇒ **會讓人去查網路。**（那一條我另外提給 A，不在這一題裡。）


def _blank_js_comments_local(src):
    """把 JS 註解換成等長空白（引號內的 `//` 不算）。

    ☠️ 不剝的話會假陽性：`reports.js:1940` 有一行**註解**寫著
       `// this.$nextTick(() => this._initSubListSortable(...))`
       ⇒ 掃描器把它讀成一個呼叫，而那支函式在 `case-management.js` 裡。
    🔑 今天第三次被註解騙（B 的絆線／我的 sidebar 解析器／這次）。
    """
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            q = c
            out.append(c)
            i += 1
            while i < n and src[i] != q:
                if src[i] == "\\" and i + 1 < n:
                    out.append(src[i]); out.append(src[i + 1]); i += 2; continue
                out.append(src[i]); i += 1
            if i < n:
                out.append(src[i]); i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out.append(" "); i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " "); i += 1
            out.append("  "); i += 2
            continue
        out.append(c); i += 1
    blanked = "".join(out)
    assert len(blanked) == len(src), "剝註解改變了長度 —— 行號會錯位。"
    return blanked


def _calls_and_defs(js_raw):
    """`(被呼叫的, 有定義的)`。

    ⚠️ **定義那一邊刻意寬**：方法／`async` 方法／getter／一般屬性都算。
    🔑 理由是方向 —— 定義漏抓 ⇒ **報出一個不存在的缺口** ⇒ 有人去「補」一支
       已經存在的函式，或更糟，**去刪一個還在用的**。
    📌 今天已經發生過一次（只認 `this.X(` ⇒ 把 `initCharts()` 報成死碼，
       而它是 `self.initCharts()`）。**判準太窄的方向不是對稱的。**

    ⚠️ `$` 開頭的是 Alpine 內建（`$nextTick`／`$watch`／`$refs`…），不是這一頁定義的。
    """
    js = _blank_js_comments_local(js_raw)
    defs = set(re.findall(
        r"^\s{2,6}(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", js, re.M))
    defs |= set(re.findall(r"^\s{2,6}get\s+([A-Za-z_$][\w$]*)\s*\(", js, re.M))
    defs |= set(re.findall(r"^\s{2,6}([A-Za-z_$][\w$]*)\s*:", js, re.M))
    defs -= {"if", "for", "while", "switch", "catch", "function", "return", "else"}
    calls = set(re.findall(
        r"(?:this|self|that|vm)\.([A-Za-z_$][\w$]*)\s*\(", js))
    calls = {c for c in calls if not c.startswith("$")}
    return calls, defs


@pytest.mark.parametrize("which", ["cashier", "reports"])
def test_every_method_called_on_the_page_is_defined_on_the_page(which):
    """🔴🔴 **`this.X()` 呼叫得到的每一支，都要在這一頁的 JS 裡定義得到。**

    ☠️ 使用者實際踩到的那一次：
    ```
    confirmReceive() 呼叫 this._displayName() 填 receivedBy
    而 cashier.js **沒有** _displayName（reports.js 有）
    ⇒ TypeError ⇒ 被 catch 抓走 ⇒ 印成「**網路錯誤**」
    ⇒ 使用者按確定，什麼都沒存，而畫面說是網路問題
    ```
    🔑 **這一題涵蓋那道 modal 題**：`open*Modal` 缺本體只是它的一個特例，
       而這一次缺的是一支**工具函式**，modal 那一題完全看不到它。
    📌 A 的更正：「我讓你釘的太窄了」—— 而更窄的那一版**已經全綠**，
       ⇒ 〈判準的寬窄都會騙人〉：**一道綠燈守門不代表那一類問題不存在。**

    ⚙️ 兩側都驗（`cashier` 與 `reports`）—— 今天第三次修同一種不對稱，
       **而前兩次我只修了實例。**
    """
    if which == "cashier":
        where, raw = _cashier_js()
    else:
        where, raw = REPORTS_JS.name, _read(REPORTS_JS)

    calls, defs = _calls_and_defs(raw)
    assert calls and defs, (
        "`%s`：呼叫 %d 個、定義 %d 個 —— **儀器失效**，"
        "這一題會因為量不到而綠。" % (where, len(calls), len(defs)))

    missing = sorted(calls - defs)
    assert not missing, (
        "`%s` 呼叫了這些，而它們**沒有定義在這一頁的 JS 裡**：%s\n" % (where, missing)
        + "☠️ 按下去會丟 `TypeError`，而它被 `catch` 抓走之後"
          "**印成「網路錯誤」** ⇒ 使用者以為是網路問題。\n"
        "🔑 那比「按了沒反應」更糟：**它給了一個錯誤的方向。**")


def test_the_call_scanner_is_not_fooled_by_comments_or_alpine():
    """⚙️ **正對照** —— 這個掃描器的兩個已知陷阱各驗一次。

    ```
    ① 註解裡的呼叫      reports.js:1940 有一行註解寫著
                        `// this.$nextTick(() => this._initSubListSortable(...))`
                        ⇒ 不剝註解 ⇒ 報出一個假缺口
    ② Alpine 內建       $nextTick／$watch 不是這一頁定義的 ⇒ 不該被當成缺口
    ```
    🔑 兩個都會讓這一題**報出不存在的問題**，而那個方向的代價是
       **有人去「補」一支不需要的函式**。
    ⚠️ 而它與受測物**走同一條量測路徑**（`_calls_and_defs`）——
       它分辨的是「量法壞了」；上面那個 `assert calls and defs`
       分辨的是「檔案空了」。**兩個不是同一件事。**
    """
    sample = "\n".join([
        "    async loadX() {",
        "      // this.$nextTick(() => this._neverDefined())",
        "      this.$watch('a', () => {})",
        "      this._realOne()",
        "    },",
        "    _realOne() { return 1 },",
    ])
    calls, defs = _calls_and_defs(sample)
    assert "_neverDefined" not in calls, (
        "掃描器把**註解裡**的呼叫算進去了 —— 它會報出一個假缺口。")
    assert "$watch" not in calls, (
        "掃描器把 Alpine 內建 `$watch` 算成這一頁該定義的東西。")
    assert "_realOne" in calls and "_realOne" in defs, (
        "掃描器連一個正常的呼叫／定義都認不出來 —— **量法壞了**。")
