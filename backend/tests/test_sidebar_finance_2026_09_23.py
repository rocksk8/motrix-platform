# -*- coding: utf-8 -*-
"""`UI6` · 財務組加「出納」入口 ＋ 側欄分組條件的通用不變量。

使用者兩次說「營運報表我還是沒看到下拉式選單」。A 實查之後的界定（`§61`）：
```
grep children|submenu|collapse|accordion  在 sidebar.js ⇒ **0 處**
⇒ 這個側欄**沒有下拉機制**，每組都是「分組標題 ＋ 平鋪項目」
⇒ 使用者要的是「財務底下有好幾項」，不是要展開收合
```
📌 而今天做完財務底下會是 **2 項不是 5 項**（會計科目／傳票／獎金分潤都還不存在）。

---

# ⚠️ 這個檔的射程：它讀的是 `sidebar.js` 的**原始碼**

答的是「哪一項被寫在哪一組底下、條件寫了什麼」，不是「瀏覽器渲染出來長怎樣」。
📌 擋得住：漏加、加錯組、條件寫錯、分組條件與項目條件漂移。
☠️ 擋不住：寫對了而 CSS 讓它看不見。**真正的驗收是目視，而這句話寫在這裡。**

⚠️ `sidebar.js` 是**鎖定檔** ⇒ B 動它之前要在 `B.md` 宣告。
   那是協定動作，我驗不到，所以這裡只寫這一句。

---

# 🔴 `_deniedPages` 那一題不在這個檔裡，它在等 A 裁

`act()`（`:106`）與 `_deniedPages`（`:778`）**都只認檔名**
（`file = path.split('/').pop()`，而 query string 不在 `pathname` 裡）
⇒ `reports.html?tab=cashier` 的 `file` 就是 `reports.html`。

```
只有 cashier 權限（cCash=T, cRpt=F, cFi=F）：
  營運報表 show=cRpt||cFi = False ⇒ 隱藏 ⇒ _deniedPages += ['reports.html', ...]
  出納     show=cCash     = True  ⇒ 顯示，href=reports.html?tab=cashier
  點下去 ⇒ file='reports.html' ∈ _deniedPages ⇒ **_showNoPermission()**
☠️ 他被鎖在他唯一被授權的那一頁外面
```
🔑 底層不變量：**兩個 `ni()` 的 href 解析到同一個檔名時，它們的 `show` 條件必須相同。**
⇒ 而那與 `§46b`（每一項的 show 要與它的 href 對得上）**直接牴觸** ——
   已送 A，甲／乙／丙三條路由 A 裁，**我不自己選**。

---

# ✅ `UI9` 之後：上面那一整段的**問題本身消失了**（上面照原樣留著）

使用者裁示「出納是**獨立功能**」⇒ 出納拆回 `cashier.html`
⇒ **兩個項目不再指向同一個檔名** ⇒ 鎖門、「出納永遠不會亮」、`§46b`
   **三個症狀一起消失**（`UI7` 因此是「已不需要」，不是「延後」）。

🔑 而這一段要留著，因為它是這個檔幾道守門**為什麼存在**的理由 ——
   ⚠️ 問題消失了**不等於守門可以拿掉**：下一次有人再讓兩個項目指向同一個檔名時，
   那幾道守門仍然是唯一會紅的東西。
📌 〈守門被拿掉≠規則被解除〉的鄰居：**規則的理由暫時沒有觸發，不表示規則失效了。**

⚠️ 連帶：`UI9` 之後 `cashier.html` 由「出納」那一項擁有
⇒ **「營運報表」的 `activeNames` 要把它拿掉**（`UI6` 當時是要留著的）。
   本檔 `..._never_claimed_by_items_with_different_conditions` 會自動逼出這件事：
   兩項條件不同（`cCash` vs `cRpt||cCash||cFi`）而同時宣告同一個檔名 ⇒ 紅。
"""

import pytest


#: 🔴 `UI9` 之後出納是**一個獨立頁面**，沿用舊檔名。
#: ```
#: UI6 當時  reports.html?tab=cashier   ← 出納是 reports 的一個頁籤
#: UI9 之後  cashier.html               ← 使用者裁示「出納是獨立功能」
#: ```
#: ⚠️ v1 那一列留著，因為它解釋了本檔幾道守門**為什麼存在**：
#: 兩個項目指向同一個檔名時，`act()` 與 `_deniedPages` 只認檔名 ⇒ 會鎖門。
#: ✅ 而 `UI9` 讓出納有自己的檔名 ⇒ **那一族問題自然消失**
#:    （`UI7` 因此標成「已不需要」，不是「延後」）。
#: 🔑 那是〈診斷的層級決定覆蓋率〉的實例：**我報準了三個症狀，
#:    而它們是同一個根因（兩個功能共用一頁）的三個出口。**
CASHIER_TARGET = "cashier.html"


def _perm_set(perm):
    """宣告的 perm ⇒ 權限集合（C4；原本是從 JS 條件式抽旗標名稱的 `_flags()`）。
    "superadmin" ⇒ {"sa"}（沿用舊旗標名）；"any" ⇒ 空集合（同舊的 `true`）；清單 ⇒ 那些模組 key。"""
    if perm == "superadmin":
        return {"sa"}
    if perm == "any":
        return set()
    return set(perm or [])


@pytest.fixture(scope="module")
def nav():
    """C4：選單宣告（tests/_menu_decl.py；依渲染順序）。原本是 sidebar.js 原始碼的 `sec()`／`ni()` 呼叫。"""
    from tests._menu_decl import declared_items
    items = declared_items()
    assert any(it["group_label"] == "財務" for it in items), "宣告裡沒有「財務」組 —— **儀器失效**。"
    return items


def _groups(nav):
    """`{分組標籤: (分組標籤, None, [(項目標籤, href, activeNames, 權限集合)])}`。
    C4：群組沒有自己的條件了（群組顯示＝底下至少一項可見，core.menu）⇒ 第二欄恆為 None。"""
    out = {}
    for it in nav:
        g = out.setdefault(it["group_label"], (it["group_label"], None, []))
        g[2].append((it["label"], it["href"], list(it["active"] or [it["href"]]), _perm_set(it["perm"])))
    return out


# ══════════════════════════════════════════════════════════════════════
# UI6 · 財務底下要有「出納」
# ══════════════════════════════════════════════════════════════════════

def test_ui6_finance_has_a_cashier_entry(nav):
    """🔴 `UI6`：**財務組底下要有「出納」，而它要連到出納實際在的地方。**

    ```
    出納的內容   在 reports.html 的一個頁籤裡（2026-08-31 整併）
    cashier.html 是 1,198 bytes 的**轉址存根**，不是頁面
    ⇒ 入口要指向 reports.html?tab=cashier
    ```
    ☠️ 指向 `cashier.html` 的話，使用者會先落在存根上再被 JS 轉走 ——
    🔑 **而那一跳在慢速連線上看得見，且它讓網址列出現一個不存在的頁。**

    ⚠️ 而 `§46b` 那個權限缺陷是這一題的**主體**（見下一題）：
    只有 cashier 權限的人，現在側欄上**沒有任何地方**可以到他被授權的頁。
    """
    groups = _groups(nav)
    assert "財務" in groups, "宣告裡沒有「財務」組 —— **儀器失效**（抓到的分組：%s）" % sorted(groups)
    _label, _cond, items = groups["財務"]
    labels = [it[0] for it in items]
    assert "出納" in labels, (
        "財務組底下沒有「出納」，現在只有：%s\n" % labels
        + "☠️ 只有 cashier 權限的人，選單上**沒有任何地方**可以到他被授權的頁。")
    cashier = next(it for it in items if it[0] == "出納")
    assert cashier[1] == CASHIER_TARGET, "「出納」的 href 是 %r，應該是 `%s`。" % (cashier[1], CASHIER_TARGET)


def test_ui6_the_cashier_entry_is_shown_to_cashiers(nav):
    """🔴 `§46b`：**「出納」的顯示條件要是出納權限，不是報表權限。**

    ☠️ 現況（`:717`）：`營運報表` 的 `show` 是 `cRpt || cCash || cFi`，而 href 是
    `reports.html` ⇒ **只有 cashier 權限的人**看得到一個叫「營運報表」的項目，
    點進去是報表頁，而他真正被授權的出納**沒有任何入口**。

    ⚠️ 這一題只釘「出納那一項的條件包含 `cCash`」。
    🔴 **「營運報表那一項要不要拿掉 `cCash`」不在這裡** —— 拿掉會踩到
    `_deniedPages` 的檔名碰撞（見本檔檔頭），**那條路由 A 裁**。
    """
    _label, _cond, items = _groups(nav)["財務"]
    cashier = [it for it in items if it[0] == "出納"]
    assert cashier, "財務組底下沒有「出納」—— 見上一題。"
    assert "cashier" in cashier[0][3], (
        "「出納」的權限是 %s，裡面沒有 `cashier`（原旗標 `cCash`）。\n" % sorted(cashier[0][3])
        + "☠️ 有出納權限的人看不到出納入口 —— 這一題整個沒有意義了。")


# ══════════════════════════════════════════════════════════════════════
# 通用不變量 · 分組條件必須是底下每一項條件的**聯集**
# ══════════════════════════════════════════════════════════════════════

def test_every_section_condition_is_the_union_of_its_items(nav):
    """🔴 **`sec()` 的條件必須是底下每一項條件的聯集。**（通用，不只財務）

    `sidebar.js:730` 已經為「我的工作」那一組寫過這條理由：
    > 「顯示條件加上 `cQ`：三項的條件是 `cQ`，而**分組的條件必須是底下每一項
    >   條件的聯集** —— 漏掉的話，一個只有 `cQ` 沒有 `cWL`／`cDT` 的人
    >   會看到三個項目掛在一個不顯示的標題底下。」

    ⚠️ **而那條理由當時只寫在註解裡** ⇒〈散文對工具是隱形的〉。這一題是它的可執行形式。

    ```
    分組少了某個旗標  ⇒ 項目掛在一個不顯示的標題底下（註解描述的那一種）
    分組多了某個旗標  ⇒ 有人看到一個**空的**分組標題
    ```
    ☠️ 兩個方向都不會報錯，而**兩個都是使用者看得到的東西**。

    ⚙️ 而這一題**現在就該是綠的** —— 它是變更偵測，不是今天抓到了什麼。
       🔑 它真正的價值在 `UI6` 加「出納」那一刻：
       忘了把 `cCash` 併進 `sec('財務')` 的話，它當場紅。
    """
    # 〔C4 更正：原本比對 `sec('組', 條件)` 與底下 `ni()` 條件的旗標集合。C4 起群組沒有自己的條件——
    #   群組顯示＝底下至少一項可見（core.menu.build 與 sidebar.js buildSidebar 同一條規則）⇒ 改驗行為：
    #   對每一個單一權限，渲染出的每一組都至少有一項（不會有空標題），而每一個看得到的項目它的組都在（不會掛在不顯示的標題下）〕
    from core import loader
    from core import menu as M
    from core import pages as Pg
    mans = {k: v[0] for k, v in Pg.read_manifests(loader.MODULES_DIR).items()}
    l1, mi = M.load_l1(), M.module_items(mans)
    groups = _groups(nav)
    assert len(groups) >= 5, "只抓到 %d 個分組 —— **儀器失效**。（抓到：%s）" % (len(groups), sorted(groups))
    keys = sorted({k for it in nav if isinstance(it["perm"], list) for k in it["perm"]})
    problems = []
    for k in keys:
        built = M.build(l1, mi, [k], False)
        empty = [g["label"] for g in built if not g["items"]]
        if empty:
            problems.append("只有 %s 權限 ⇒ 空的分組標題 %s" % (k, empty))
        want = {it["group_label"] for it in nav if isinstance(it["perm"], list) and k in it["perm"]}
        missing = want - {g["label"] for g in built}
        if missing:
            problems.append("只有 %s 權限 ⇒ 看得到的項目所在的組 %s 沒有出現" % (k, sorted(missing)))
    assert not problems, "分組顯示與項目顯示對不上：\n  " + "\n  ".join(problems)


def test_the_section_union_check_can_actually_fail(nav):
    """⚙️ **上一題的正對照**：證明那個比較真的分辨得出差異。

    ☠️ 少了它，一個「旗標一個都抽不出來」的 `_flags()`（例如正則寫錯）
    會讓上一題**永遠綠** —— 而那與「全部都對」長得一模一樣。
    🔑 〈沒抓到要被解釋成儀器失效，不可以被解釋成乾淨〉。

    ⚠️ 這一題與上一題**走同一條量測路徑**（都用 `_flags()`）—— 那是刻意的：
    它分辨的是「量法壞了」。而上面 `len(groups) >= 5` 那個斷言走的是
    `_calls()`／`_groups()`，分辨的是「解析器抓不到東西」。
    📌 **兩個分辨的不是同一件事，刪掉任何一個都會少一種辨識力。**
    """
    assert _perm_set("superadmin") == {"sa"}, "`_perm_set()` 抓不到最高管理者"
    assert _perm_set("any") == set(), "`_perm_set()` 把「任何人」當成權限"
    assert _perm_set(["reports", "finance"]) == {"reports", "finance"}, "`_perm_set()` 抽不出權限 —— **量法壞了**"
    assert _perm_set(["work_log"]) != _perm_set(["work_log", "quotation"]), "`_perm_set()` 沒有辨識力"
    _l, _cond, items = _groups(nav)["財務"]
    assert items, "財務組底下一個項目都沒抓到 —— **儀器失效**。"
    assert any(it[3] for it in items), "財務組的項目一個權限都抽不出來 —— **儀器失效**。"


# ══════════════════════════════════════════════════════════════════════
# 使用者真正說的那件事 · 「沒看到下拉式選單」的成因
# ══════════════════════════════════════════════════════════════════════

def test_ui6_finance_has_enough_items_to_render_a_dropdown(nav):
    """🔴 **使用者說「營運報表我還是沒看到下拉式選單」—— 成因在這一行。**

    ```js
    :643  if (g.items.length === 1) {
              // 退化成純連結（mnav__top），**沒有面板、沒有箭頭**
    ```
    ⇒ 財務只有 **1 項** ⇒ 它被渲染成一個純連結，而其他分組都 ≥2 項 ⇒ 有下拉。
    🔑 **不是使用者記錯，也不是「這個側欄沒有下拉機制」** ——
       下拉機制存在（`mnav__grp`／`mnav__panel`／`:663` 的箭頭 SVG），
       **而財務這一組走了那個退化分支。**

    ⚠️ A 一開始查 `grep children|submenu|collapse|accordion` 得到 0 處，據此
    對使用者說「這個側欄沒有下拉機制」—— **錯的，是 B 擋下來的**。
    🔑 成因：查的是**英文框架的慣用字**，而這個 codebase 用 `mnav__grp`／`mnav__panel`，
       **註解還是中文**。〈判準的寬窄都會騙人〉：太窄 ⇒ 假陰性 ⇒ **而你會拿它去否定別人**。

    📌 ⇒ 加上「出納」之後自動變 2 項，下拉**自動出現**，`UI6` 的範圍一個字都不用改。
    ⚙️ 而這一題釘的是**那個門檻**，不是「有沒有出納」：日後有人把財務縮回一項，
       使用者會再一次看不到下拉，而**沒有東西會紅**。

    ## ⚠️ 射程：它數的是**原始碼裡的項數**，不是**某個人看到的項數**

    B 用 node 實跑出來的：
    ```
    只有報表權限  財務 = 1 項 ⇒ **純連結，沒有下拉**
    有出納權限    財務 = 2 項 ⇒ 下拉面板
    ```
    ⇒ **「財務現在有下拉了」只對有出納權限的人成立。**
    🔑 而使用者是 `superadmin`，他會看到下拉、他會滿意 ——
       **那不等於這件事對他的員工成立。**

    📌 **這裡刻意不寫成斷言**：一個只有一種權限的人看到一項，那是**正確行為**，
       不是缺陷。⇒ 它是一句要寫進交付說明的話，不是一個不變量。
    ⚠️ 而那句話的通用形式（A 已升 `§6`，對一個**要賣的**產品特別重要）：
       **交付說明裡任何「現在會顯示／現在可以」的句子，
         都要問一次：這句話在哪一組權限下不成立？**
    """
    _l, _c, items = _groups(nav)["財務"]
    assert len(items) >= 2, (
        "財務組底下只有 %d 項：%s\n" % (len(items), [it[0] for it in items])
        + "☠️ renderMainNav 的 `if (g.items.length === 1)` 會把它渲染成**純連結**，沒有面板也沒有箭頭。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 兩條「鎖門」不變量（A 裁甲之後，它們是 UI6 能不能安全落地的條件）
# ══════════════════════════════════════════════════════════════════════
#
# 機制（`sidebar.js`）：
# ```
# :614  ni() 的 show 為 false ⇒ _deniedPages += activeNames
# :778  _deniedPages.indexOf(file) >= 0 ⇒ _showNoPermission()
# :79   file = path.split('/').pop()      ← **query string 不在 pathname 裡**
# ```
# 🔑 A 指名的根因：`:596-603` 那段註解說「刻意不另外維護一份頁面→模組對照表，
#    因為它會漂移」——**而那個機制的前提是「一個檔名一組權限」**。
#    出納與營運報表共用 `reports.html`，**那個前提第一次不成立。**
#    ⇒ 不是實作疏忽，是**一個既有設計的邊界被跨過了**。


def _target_file(href_expr):
    """宣告的 href ⇒ 檔名（去掉路徑、query、hash）。"""
    return (href_expr or "").split("/")[-1].split("?")[0].split("#")[0] or None


def _active_names(expr):
    """C4：宣告裡 active 已經是清單。"""
    return list(expr or [])


def _all_items(nav):
    out = []
    for _label, (_l, _c, items) in _groups(nav).items():
        out.extend(items)
    return out


def test_a_visible_item_never_points_at_a_page_someone_else_denied(nav):
    """🔴🔴 **顯示中的項目，不可以指向一個會被 `_deniedPages` 擋下的檔名。**

    ```
    X 被隱藏 ⇒ X 的 activeNames 進 _deniedPages
    Y 顯示中 ⇒ 而 Y 的 href 指向同一個檔名
    ⇒ 使用者點 Y ⇒ **_showNoPermission()**，在他被授權的那一頁上
    ```
    ☠️ 這正是 `§46b` 若照原規格修會發生的事（A 已裁甲，改走另一條）：
    ```
    只有 cashier 權限：營運報表 show=cRpt||cFi ⇒ 隱藏 ⇒ reports.html 進黑名單
                       出納     show=cCash    ⇒ 顯示 ⇒ href 指向 reports.html
                       ⇒ **他被鎖在他唯一被授權的那一頁外面**
    ```
    🔑 不變量（布林是「旗標的 OR」）：
    **Y 顯示 ⇒ X 也顯示**，也就是 `flags(Y) ⊆ flags(X)`。

    ⚠️ 它擋不到的：條件裡有 `&&` 或 `!` 的項目（這個檔現在全是 `||`）。
       ⇒ 出現第一個 `&&` 的那天這一題要重寫，**而它不會自己告訴你** ——
       所以下面那個 `_flags()` 的正對照要留著。
    """
    items = _all_items(nav)
    assert items, "一個項目都沒抓到 —— **儀器失效**。"

    by_active = {}
    for label, _href, names, cond in items:
        for f in _active_names(names):
            by_active.setdefault(f, []).append((label, cond))

    problems = []
    for label, href, _names, cond in items:
        tgt = _target_file(href)
        if not tgt:
            continue
        for other_label, other_flags in by_active.get(tgt, []):
            if other_label == label:
                continue
            if not cond <= other_flags:
                problems.append(
                    "「%s」(href→%s, %s) 顯示時，「%s」(%s) 可能是隱藏的 "
                    "⇒ `%s` 會進 `_deniedPages` ⇒ 點下去看到「沒有權限」"
                    % (label, tgt, sorted(cond), other_label,
                       sorted(other_flags), tgt))
    assert not problems, (
        "有顯示中的項目會指向一個被列入黑名單的檔名：\n  "
        + "\n  ".join(problems)
        + "\n🔑 `sidebar.js:614`＋`:778`：隱藏項目的 `activeNames` 會變成黑名單，"
          "而 `file` 只認檔名（`:79`，query 不在 pathname 裡）。")


def test_a_page_name_is_never_claimed_by_items_with_different_conditions(nav):
    """🔴 **同一個檔名不可以出現在兩個條件不同的項目的 `activeNames` 裡。**

    ```
    X 隱藏 ⇒ F 進 _deniedPages
    Y 顯示 ⇒ 而 Y 也宣告 F 是它的頁
    ⇒ 一個「透過 Y 被授權」的人，打開 F 會看到「沒有權限」
    ```
    📌 具體案例：`cashier.html`（舊書籤）同時被「營運報表」與「出納」宣告時。
    ⇒ A 裁定「營運報表的 `activeNames` 要留著 `cashier.html`」（舊書籤要能用）
    ⇒ **所以「出納」那一項不可以再宣告它** —— 否則只有報表權限的人
      打開舊書籤會被擋，而他其實看得到營運報表。

    ⚠️ 而「出納」因此**永遠不會被標成 active**：
    `act()` 只認檔名，使用者在 `reports.html?tab=cashier` 上時 `file` 是
    `reports.html` ⇒ 亮的是「營運報表」。
    🔑 **那是 `act()` 的必然結果，不是 bug**，A 已裁定列為已知限制（`UI7` 才解）。
    ⇒ 所以這裡**不寫一個永遠紅的斷言**去要求它會亮。
    """
    by_active = {}
    for label, _href, names, cond in _all_items(nav):
        for f in _active_names(names):
            by_active.setdefault(f, {})[label] = frozenset(cond)

    problems = []
    for f, owners in sorted(by_active.items()):
        if len(set(owners.values())) > 1:
            problems.append(
                "`%s` 被這些條件不同的項目同時宣告：%s"
                % (f, ", ".join("%s=%s" % (k, sorted(v))
                                for k, v in sorted(owners.items()))))
    assert not problems, (
        "同一個檔名被條件不同的項目宣告：\n  " + "\n  ".join(problems)
        + "\n🔑 隱藏的那一個會把它丟進 `_deniedPages`（`:614`），"
          "而顯示的那一個的使用者因此被擋在門外（`:778`）。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 UI10 · `§46b` 現在可以修了 —— **因為當初不修的那個理由消失了**
# ══════════════════════════════════════════════════════════════════════

def test_ui10_the_reports_item_is_not_shown_to_cashier_only_users(nav):
    """🔴🔴 `UI10`：**只有出納權限的人，側欄上不可以有「營運報表」。**

    ## 這一題的重點是「**為什麼現在可以了**」

    ```
    §65 當時裁「不修 §46b」，理由是：
        兩項**同檔名**（都指向 reports.html）⇒ 把 cCash 拿掉會讓
        只有出納權限的人被 _deniedPages 鎖在他唯一被授權的那一頁外面
    UI9 之後：出納的 href 是 cashier.html ⇒ **不再共用檔名**
        ⇒ **那個理由整個消失** ⇒ 裁示要重新看一次
    ```
    🔑 **而它不會自己發出聲音** —— 是 B 回報「拆完只消失兩個症狀不是三個」才被看見。
    📌 進 `§6`：**一個裁示的理由消失時，那個裁示要重新看一次。**

    ## ☠️ 而現況不只是「看到不該看的名字」，**是一個死連結**

    ```
    只有 cashier 權限：營運報表 show = cRpt || cCash || cFi = **True**（靠 cCash）
    ⇒ 他看得到「營運報表」，點進去 ⇒ reports.html
    ⇒ 而那一頁的內容是 admin+ 才載入的 ⇒ **點進去是空的**（B 實測）
    ```

    ## ⚙️ 而我自己推演過它安全（不是照收）
    ```
    改成 cRpt || cFi 之後，只有 cashier 的人：
      營運報表 隱藏 ⇒ _deniedPages += ['reports.html']
      出納     顯示 ⇒ href cashier.html、activeNames ['cashier.html']
      他點出納 ⇒ file = 'cashier.html' ⇒ **不在 _deniedPages** ⇒ 正常
    ```
    ✅ 而本檔那兩道鎖門守門會繼續驗這件事 —— **它們不是靠這一段推演，是靠斷言。**
    """
    _l, _c, items = _groups(nav)["財務"]
    rpt = [it for it in items if it[0] == "營運報表"]
    assert rpt, "財務組底下沒有「營運報表」—— **儀器失效**。"

    flags = rpt[0][3]
    assert "cashier" not in flags, (
        "「營運報表」的顯示條件是 `%s`（旗標 %s），裡面還有 `cCash` ——\n"
        % (rpt[0][3], sorted(flags))
        + "☠️ 只有出納權限的人會看到「營運報表」，而**點進去是空的**"
          "（那一頁的內容 admin+ 才載入）——那不是「看到不該看的名字」，"
          "**是一個死連結**。\n"
        "🔑 `§65` 當初不修的理由（兩項同檔名會鎖門）在 `UI9` 之後**已經消失**。")

    assert "reports" in flags, (
        "「營運報表」的條件裡沒有 `cRpt`（%s）——\n" % sorted(flags)
        + "⚙️ 這是**正對照**：少了它，一個「把條件整個清空」的實作"
          "會讓上面那個斷言綠，而**有報表權限的人也看不到報表了**。")


def test_ui10_the_cashier_item_still_reaches_its_own_page(nav):
    """⚙️ `UI10` 的另一半：**收窄之後，只有出納權限的人仍然到得了出納頁。**

    ☠️ 這一題是 `§65` 當初擋下來的那個災難的守門：
    ```
    若出納的 href 還指向 reports.html（UI9 之前）
    ⇒ 營運報表收窄成 cRpt||cFi ⇒ 它隱藏 ⇒ reports.html 進 _deniedPages
    ⇒ 而出納顯示、指向同一個檔名 ⇒ **點下去「沒有權限」**
    ```
    🔑 現在它安全，**而安全的原因是「出納有自己的檔名」，不是「有人記得」。**
    ⇒ 這一題把那個原因**釘住**：出納的 href 必須**不是** `reports.html`。
    📌 本檔 `..._never_points_at_a_page_someone_else_denied` 是通用版，
       而這一題是它在**這一組權限**上的具體案例 —— 兩個都留著。
    """
    _l, _c, items = _groups(nav)["財務"]
    cash = [it for it in items if it[0] == "出納"]
    assert cash, "財務組底下沒有「出納」—— **儀器失效**。"

    label, href, names, cond = cash[0]
    tgt = _target_file(href)
    assert tgt and tgt != "reports.html", (
        "「出納」的 href 解析到 `%s` ——\n" % tgt
        + "☠️ 與「營運報表」同檔名 ⇒ 後者收窄成 `cRpt||cFi` 之後，"
          "只有出納權限的人會被 `_deniedPages` 擋在門外。")
    assert "cashier" in cond, (
        "「出納」的條件是 `%s`，沒有 `cCash` —— 有出納權限的人看不到它。" % cond)
    assert tgt in _active_names(names), (
        "「出納」的 `activeNames` 是 %s，裡面沒有 `%s` ——\n"
        % (_active_names(names), tgt)
        + "🔑 它現在有自己的檔名了，**應該宣告它** ——"
          "`UI6` 當時寫成 `[]` 是因為那時宣告會造成鎖門，而那個理由已經消失。")
