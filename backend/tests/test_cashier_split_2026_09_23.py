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
