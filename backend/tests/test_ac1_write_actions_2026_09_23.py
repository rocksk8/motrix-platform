# -*- coding: utf-8 -*-
"""`AC1` 通用版 · **宣稱有畫面的功能，那一頁要有「會送出的動作」。**

```
使用者逐字（§159b (8)）  「確認前後端跟頁面都有完成才算完整」
⇒ 「完整」= 後端 ＋ 前端 ＋ 頁面，三者都完成
```
☠️ 2026-09-23 一天內踩過三次「**後端 ＋ 唯讀骨架 ＝ 回報完成**」
（傳票、獎金，以及那句「請先作廢重開」）。

# 🔴 判準：**數「會送出的那一個動作」，不數 `<button>`**

```
method: 'POST|PUT|PATCH|DELETE'   <= 會送出
<button>重新整理</button>          <= 不會
```
☠️ 數按鈕的話，一個只有「重新整理」「匯出」的唯讀頁也會過。

# ☠️ 而共用 js **一定要排掉**，否則每一頁都「有寫入」

```
sidebar.js／notif.js／auth-guard.js … 被 >1 頁 script-link（實算 7 支）
而它們自己有 POST ⇒ 不排掉的話 **61 頁全部通過**
```
🔑 那是 `AL1` `(a-2)` 那個引信的同族：**一份共用檔會讓整批翻綠**。
⚠️ 而排除清單要**算出來**（被 >1 頁引用），不可以手列 —— 手列會腐爛。

# ⚙️ 唯讀頁要能**明著登記**，而登記要付代價

`AC1` 條文逐字：「⚙️ 反向控制：**唯讀頁要能明著登記成唯讀**，
否則靠『全部登記』變綠」。
⇒ 本檔的兩道反向控制：
```
① 登記表裡的頁面若**真的有寫入呼叫** => 紅（登記過期了）
② 每一筆登記都要有**理由**，而且不可以是罐頭句
```
"""
import collections
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGES_DIR = ROOT / "frontend" / "pages"

#: 「會送出的那一個動作」。
WRITE_RE = re.compile(r"method\s*:\s*['\"](POST|PUT|PATCH|DELETE)['\"]", re.I)

#: 頁面自己 `<script src>` 進來的專案 js。
_SRC_RE = re.compile(r'<script[^>]+src="([^"]+\.js)"')

#: 🔴 **唯讀頁的豁免登記表**（2026-09-23 實算，共 8 頁）。
#:
#: ⚠️ 每一筆都要寫**為什麼它沒有寫入動作**，而不是「它就是唯讀」。
#: ☠️ 這張表是 `AC1` 唯一的逃生門 ⇒ 它變長就是這道守門在失效。
READ_ONLY_PAGES = {
    "account-items.html":
        "會計科目樹：後端 `routers/account_items.py` **只有一支 GET**，"
        "沒有任何寫入端點 ⇒ 頁面唯讀與後端一致。"
        "⚠️ 而 `v96` 已經加了 `is_active`（停用而非刪除）而**沒有端點也沒有 UI** "
        "⇒ 使用者目前停不掉任何科目。已回報 A，**不在本檔的射程內**。",
    "approval-history.html": "簽核歷程：純查詢，動作在簽核佇列那一頁。",
    "map.html": "地圖：只讀座標與標記，沒有可寫的東西。",
    # 🔴 **這一筆是這道守門抓到的第一個東西 —— 抓到的是我自己。**
    #    我第一版寫「線上統計：純報表。」（9 字）⇒ `len(why) >= 12` 直接紅。
    #    ☠️ 而那句話是**重述結論**，不是理由：下一個人看不出它有沒有過期。
    "online-stats.html":
        "線上統計：只讀 `/api/online-users`、`/api/user-activity`、"
        "`/api/user-activity/trail` 三支查詢端點，"
        "**沒有任何對應的寫入端點** ⇒ 頁面唯讀與後端一致。",
    "receivables.html": "應收帳款：純報表，沖銷動作在出納那一頁。",
    "sales-orders.html": "銷貨單清單：純查詢，建立與修改在報價單那一邊。",
    "selection-db-overview.html": "選型資料庫總覽：純查詢，維護在各分類頁。",
    "shipping-export-history.html": "出貨匯出歷程：純查詢，匯出動作在出貨單那一頁。",
}

#: ⚠️ 罐頭理由 —— 登記表最容易腐爛的形狀是「理由等於重述結論」。
_EMPTY_REASONS = ("唯讀", "唯讀頁", "沒有寫入", "不需要", "純顯示", "N/A", "")


def _pages():
    return sorted(PAGES_DIR.glob("*.html"))


def _linked(page):
    out = []
    html = page.read_text(encoding="utf-8", errors="replace")
    for m in _SRC_RE.finditer(html):
        s = m.group(1)
        if "vendor" in s or s.startswith("http"):
            continue
        cand = (page.parent / s).resolve()
        if cand.exists():
            out.append(cand)
    return out


def _shared_js():
    """被**超過一頁** script-link 的 js。**算出來，不手列。**"""
    cnt = collections.Counter()
    for p in _pages():
        for j in _linked(p):
            cnt[j] += 1
    return {j for j, n in cnt.items() if n > 1}


def _own_blob(page, shared):
    """這一頁自己的 HTML ＋ **只屬於它的** js。"""
    parts = [page.read_text(encoding="utf-8", errors="replace")]
    for j in _linked(page):
        if j in shared:
            continue
        parts.append(j.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _writes(page, shared):
    return bool(WRITE_RE.search(_own_blob(page, shared)))


# ══════════════════════════════════════════════════════════════════════
# ⓪ 量具
# ══════════════════════════════════════════════════════════════════════

def test_ac1_the_write_detector_can_tell_a_read_only_page_apart():
    """⚙️ **判準自檢：分得出「會送出」與「只是有按鈕」。**

    📌 `AC1` 條文逐字：**判準不可以只數 `<button>`**。
    ☠️ 數按鈕的話，一個只有「重新整理」「匯出」的唯讀頁也會過。
    """
    read_only = "const r = await fetch('/api/x', { headers: h })"
    assert not WRITE_RE.search(read_only), "唯讀的 fetch 被判成寫入 —— 太寬。"

    for snippet in ("fetch(u, { method: 'POST', body: b })",
                    'fetch(u, {method:"PUT"})',
                    "fetch(u, { method: 'delete' })"):
        assert WRITE_RE.search(snippet), "沒認出寫入：%r —— 太窄。" % snippet

    buttons = "<button>重新整理</button><button>匯出 Excel</button>"
    assert not WRITE_RE.search(buttons), "按鈕被算成寫入動作 —— 太寬。"


def test_ac1_shared_js_is_excluded_and_it_matters():
    """⚙️ **共用 js 要排掉，而且那個排除是有作用的。**

    ```
    不排掉  sidebar.js 自己有 POST ⇒ **每一頁都「有寫入」** ⇒ 這道守門整個失效
    ```
    🔑 那是 `AL1` `(a-2)` 那個引信的同族：**一份共用檔會讓整批翻綠**。
    ⚙️ 這一題同時證明兩件：
    ```
    ① 共用清單**算得出來**（被 >1 頁引用），不是手列的
    ② 那些共用檔裡**真的有寫入呼叫** ⇒ 不排掉的話這道守門會失效
    ```
    ☠️ 少了 ②，一個「排除清單是空的」的實作也會過 ① ——
       而那時排不排除沒有差別，**這一題會變成一句空話**。
    """
    shared = _shared_js()
    assert shared, "共用 js 一支都沒算到 —— **尺量不到東西**。"
    assert len(shared) >= 3, (
        "只算到 %d 支共用 js：%s —— 太少了，多半是 `<script src>` 沒解析到。"
        % (len(shared), sorted(x.name for x in shared)))

    writers = [x.name for x in shared
               if WRITE_RE.search(x.read_text(encoding="utf-8",
                                              errors="replace"))]
    assert writers, (
        "沒有任何一支共用 js 含寫入呼叫（共 %d 支：%s）——\n"
        % (len(shared), sorted(x.name for x in shared))
        + "☠️ 那表示「排除共用檔」這個動作**現在沒有作用** ⇒\n"
          "   這一題與下面那道守門都會變成空話。\n"
        + "⚠️ 若共用檔真的都變唯讀了，**退回給我**：那時這一題要改成別的形狀。")


# ══════════════════════════════════════════════════════════════════════
# ① 本體
# ══════════════════════════════════════════════════════════════════════

def test_ac1_every_page_either_writes_something_or_is_registered():
    """🔴 **每一頁要嘛有「會送出的動作」，要嘛明著登記成唯讀。**

    ☠️ 這道守門擋的是**唯讀骨架被當成完成的功能** ——
       2026-09-23 一天踩三次（傳票、獎金、那句「請先作廢重開」）。
    ⚠️ 它擋不到的那一側：**介面有了而流程是錯的** —— 那只有使用者打開才知道。
    """
    shared = _shared_js()
    pages = _pages()
    assert len(pages) > 40, (
        "只掃到 %d 頁 —— **尺量不到東西**，這一題不算數。" % len(pages))

    orphans = [p.name for p in pages
               if not _writes(p, shared) and p.name not in READ_ONLY_PAGES]
    assert not orphans, (
        "有 %d 頁沒有任何「會送出的動作」，而它們**沒有登記成唯讀**：\n"
        % len(orphans)
        + "".join("    %s\n" % n for n in orphans)
        + "🔑 兩條路：**接上那個動作**，或**在 `READ_ONLY_PAGES` 裡寫下為什麼**。\n"
        + "⚠️ 登記要寫**理由**，不是寫「唯讀」——\n"
          "   理由等於重述結論的話，下一個人看不出它是不是過期了。")


def test_ac1_a_registered_page_that_started_writing_must_be_unregistered():
    """🔴 **登記表的防腐：登記過的頁面若真的有寫入呼叫 ⇒ 紅。**

    ☠️ 沒有這一題的話，登記表是**只進不出**的 ——
       而一張只進不出的豁免清單，最後會把整個守門吃掉。
    🔑 `AC1` 條文逐字要的就是這一格：「否則靠**全部登記**變綠」。
    """
    shared = _shared_js()
    by_name = {p.name: p for p in _pages()}

    gone = [n for n in READ_ONLY_PAGES if n not in by_name]
    assert not gone, (
        "登記表上有 %d 頁已經不存在了：%r\n" % (len(gone), gone)
        + "⚠️ 頁面被刪或改名 ⇒ 那一筆登記要跟著拿掉，否則它會一直躺在那裡。")

    stale = [n for n in READ_ONLY_PAGES if _writes(by_name[n], shared)]
    assert not stale, (
        "這 %d 頁登記成唯讀，**而它們已經有寫入呼叫了**：%r\n"
        % (len(stale), stale)
        + "🔑 把它們從 `READ_ONLY_PAGES` 拿掉 —— 登記表只進不出的話，\n"
          "   最後它會把整個守門吃掉。")


def test_ac1_every_exemption_gives_a_real_reason():
    """⚙️ **反向控制：登記要付代價 —— 每一筆都要有說得出口的理由。**

    ☠️ 最省力的繞過方式是把每一頁都丟進登記表，而**那不會被任何斷言擋到**
       —— 除非登記本身有成本。
    ⇒ 這一題要求：理由不可以是罐頭句、不可以只是重述結論，
      而且要**指出那個動作在哪裡**（或為什麼根本沒有那個動作）。
    """
    assert READ_ONLY_PAGES, "登記表是空的 —— 那也要是一個明著的決定。"
    for name, why in sorted(READ_ONLY_PAGES.items()):
        why = (why or "").strip()
        assert why not in _EMPTY_REASONS, (
            "`%s` 的登記理由是罐頭句（%r）——\n" % (name, why)
            + "🔑 要寫的是**為什麼它沒有寫入動作**，不是「它是唯讀的」。")
        assert len(why) >= 12, (
            "`%s` 的登記理由太短（%r）——\n" % (name, why)
            + "⚠️ 下一個人要靠它判斷這筆登記有沒有過期。")

    assert len(READ_ONLY_PAGES) <= 12, (
        "登記表已經有 %d 筆（2026-09-23 實算是 8）——\n" % len(READ_ONLY_PAGES)
        + "☠️ 它變長就是這道守門在失效。\n"
        + "⚠️ 若真的有那麼多唯讀頁，**退回給我**：那時要改的是這個上限，\n"
          "   而那應該是一個明著的決定，不是順手加一筆。")
