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
"""
import re
from pathlib import Path

import pytest

SIDEBAR = (Path(__file__).resolve().parent.parent.parent
           / "frontend" / "static" / "sidebar.js")

#: 出納頁的真正位置 —— 它是 `reports.html` 的一個頁籤，不是一個頁面。
#: `frontend/pages/cashier.html` 是 1,198 bytes 的**轉址存根**（2026-08-31 整併）。
CASHIER_TAB = "reports.html?tab=cashier"


def _decode_escapes(text):
    r"""只把 `\uXXXX` 還原成字元，**其他一個字都不動**。

    ☠️ 不可以用 `text.encode("utf-8").decode("unicode_escape")` ——
    它會把原本就是中文的字元一併拆成 latin-1 再解，整份檔案的中文會變成亂碼，
    而症狀是「找不到那個標籤」，看起來像是那一項不見了。
    """
    return re.sub(r"\\u([0-9a-fA-F]{4})",
                  lambda m: chr(int(m.group(1), 16)), text)


def _split_args(inner):
    """把一串 JS 引數依頂層逗號切開（括號／方括號／引號內的逗號不算）。"""
    out, buf, depth, quote = [], [], 0, None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


def _blank_js_comments(src):
    """把 `//` 與 `/* */` 註解**換成等長的空白**（不是刪掉）。

    🔴 **為什麼需要它**：`sidebar.js` 的註解裡寫了 `sec()`／`ni()`
    （`:600`／`:607`／`:635`／`:776` 四處），而掃描器分不出
    「一個呼叫」與「一段解釋那個呼叫的註解」。
    ☠️ 第一版因此抓到 6 個 0 引數的「呼叫」，`_groups()` 當場 `IndexError`。

    🔑 **同一天第二次**：B 的絆線 `grep` 也被自己寫的註解騙過
    （那裡的解法是 `tokenize` 剝掉 `COMMENT`）。
    📌 共同形狀：**寫得好的註解會讓粗糙的比對產生假陽性**，
       而受害者通常是寫那段註解的人。

    ⚠️ **換成等長空白而不是刪掉**：本檔靠「原始碼位移」排 `sec`／`ni` 的先後，
       刪掉會讓位移左移 ⇒ 分組歸屬錯亂，**而那不會報錯**。
    ⚠️ 引號內的 `//` 不算註解（`'https://…'`）—— 下面逐字元掃就是為了這個。
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
                    out.append(src[i])
                    out.append(src[i + 1])
                    i += 2
                    continue
                out.append(src[i])
                i += 1
            if i < n:
                out.append(src[i])
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        out.append(c)
        i += 1
    blanked = "".join(out)
    assert len(blanked) == len(src), (
        "剝註解之後長度變了（%d → %d）—— 位移會錯位，而分組歸屬會**安靜地**錯。"
        % (len(src), len(blanked)))
    return blanked


def _calls(src, name):
    """掃出所有 `name(...)` 呼叫，回傳 `(起始位移, [引數字串])`。

    ⚠️ **跳過 `function name(...)` 那一個** —— 定義不是呼叫。
    ⚠️ 呼叫端要先過 `_blank_js_comments()` —— 註解裡也寫著 `sec()`／`ni()`。
    📌 用括號配對而不是正則：`ni()` 有跨行的（帶 badge 的那幾個），
       而「一行一個呼叫」這個假設在這個檔裡不成立。
    """
    out = []
    for m in re.finditer(r"\b%s\s*\(" % re.escape(name), src):
        before = src[max(0, m.start() - 12):m.start()]
        if before.rstrip().endswith("function"):
            continue
        i, depth = m.end(), 1
        while i < len(src) and depth:
            c = src[i]
            if c in "'\"":
                q = c
                i += 1
                while i < len(src) and src[i] != q:
                    i += 2 if src[i] == "\\" else 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        out.append((m.start(), _split_args(src[m.end():i - 1])))
    return out


#: JS 字面值／關鍵字 —— 它們不是權限旗標。
_NOT_A_FLAG = frozenset(("true", "false", "null", "undefined"))


def _flags(expr):
    """從一個顯示條件式裡抽出旗標識別字。

    ⚠️ **v1 寫成 `c[A-Z]\\w*`，太窄** —— 它看不見 `sa`（superadmin），
    而「系統」那一組十二項裡有**八項**的條件就是 `sa`。
    ⇒ v2 抓**所有識別字**再扣掉 JS 字面值：寧可多抓一個名字，
      也不要因為它不合我想像的命名慣例就看不見它。

    📌 **而我要更正自己一句話**：我原本判斷「系統那一條漂移是 v1 太窄造成的
    假陽性」，**查了之後是錯的** —— `cSet` 實查只出現在 `:464` 宣告、`:503` 指派、
    `:750` 的 `sec('系統', …)` 三處，**沒有任何 `ni()` 用它**。
    ⇒ v1 與 v2 對那一組給出**同樣的結論**，而那個結論是對的。
    🔑 換句話說：**這次修的是判準的正確性，不是結論。**
       〈推翻的證據不會自動支持替代方案〉的鄰居 ——
       **我先有了「這是假陽性」的假設，然後差一點用它去撤掉一個真發現。**
    """
    names = re.findall(r"\b[A-Za-z_$][A-Za-z0-9_$]*\b", expr or "")
    return set(n for n in names if n not in _NOT_A_FLAG)


@pytest.fixture(scope="module")
def nav():
    """`[(kind, 位移, args)]`，依原始碼順序 —— `sec` 與 `ni` 交錯。"""
    assert SIDEBAR.exists(), "找不到 %s" % SIDEBAR
    raw = _decode_escapes(SIDEBAR.read_text(encoding="utf-8"))
    src = _blank_js_comments(raw)

    # ⚙️ 剝註解的正對照（兩個方向都要，否則「剝過頭」與「沒剝到」都看不出來）：
    assert "sec('財務'" in src, (
        "剝掉註解之後連 `sec('財務'` 都不見了 —— **剝過頭**，"
        "而這個檔的每一題都會因為量不到而綠。")
    assert "sec()/ni() 仍然照舊被呼叫" not in src, (
        "註解沒有被剝掉 —— 掃描器會把註解裡的 `sec()`／`ni()` 當成呼叫，"
        "而它們是 0 引數的，`_groups()` 會 `IndexError`。")

    items = ([("sec", p, a) for p, a in _calls(src, "sec")]
             + [("ni", p, a) for p, a in _calls(src, "ni")])
    items.sort(key=lambda t: t[1])
    assert items, "`sidebar.js` 裡一個 `sec()`／`ni()` 都沒抓到 —— **儀器失效**。"
    return items


def _groups(nav):
    """`{分組標籤: (分組條件, [(項目標籤, href, activeNames, 條件)])}`。"""
    out, cur = {}, None
    for kind, _pos, args in nav:
        if kind == "sec":
            label = args[0].strip("'\" ")
            cond = args[1] if len(args) > 1 else "true"
            cur = (label, cond, [])
            out[label] = cur
        elif cur is not None:
            href = args[0] if args else ""
            label = args[2].strip("'\" ") if len(args) > 2 else ""
            names = args[3] if len(args) > 3 else "[]"
            cond = args[4] if len(args) > 4 else "true"
            cur[2].append((label, href, names, cond))
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
    assert "財務" in groups, (
        "`sidebar.js` 裡沒有 `sec('財務', …)` —— **儀器失效**，不是「沒有財務組」。\n"
        "（抓到的分組：%s）" % sorted(groups))

    _label, _cond, items = groups["財務"]
    labels = [it[0] for it in items]
    assert "出納" in labels, (
        "財務組底下沒有「出納」，現在只有：%s\n" % labels
        + "☠️ 只有 cashier 權限的人，側欄上**沒有任何地方**可以到他被授權的頁。\n"
        "🔑 使用者兩次說「財務底下沒看到別的項目」——他要的就是這一項。\n"
        "📌 做完會是 **2 項不是 5 項**（會計科目／傳票／獎金分潤都還不存在）。")

    cashier = next(it for it in items if it[0] == "出納")
    assert CASHIER_TAB in cashier[1], (
        "「出納」的 href 是 %r，應該指向 `%s`。\n" % (cashier[1], CASHIER_TAB)
        + "☠️ 指向 `cashier.html` 的話那是一頁**轉址存根**（1,198 bytes），\n"
          "   使用者會先落在它上面再被 JS 轉走。")


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
    cond = cashier[0][3]
    assert "cCash" in _flags(cond), (
        "「出納」的顯示條件是 `%s`，裡面沒有 `cCash`。\n" % cond
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
    groups = _groups(nav)
    assert len(groups) >= 5, (
        "只抓到 %d 個分組 —— **儀器失效**，這一題會因為量不到而綠。"
        "（抓到：%s）" % (len(groups), sorted(groups)))

    problems = []
    for label, (_l, cond, items) in groups.items():
        if not items:
            continue
        sec_flags = _flags(cond)
        item_flags = set()
        for it in items:
            item_flags |= _flags(it[3])
        if not item_flags:
            continue                     # 整組都是無條件項目，略過
        missing = item_flags - sec_flags
        extra = sec_flags - item_flags
        if missing:
            problems.append(
                "分組 `%s` 的條件少了 %s ⇒ 只有那個權限的人，"
                "會看到項目掛在一個**不顯示的標題**底下"
                % (label, sorted(missing)))
        if extra:
            problems.append(
                "分組 `%s` 的條件多了 %s ⇒ 有那個權限而沒有任何項目權限的人，"
                "會看到一個**空的分組標題**"
                % (label, sorted(extra)))
    assert not problems, (
        "分組條件與項目條件對不上：\n  " + "\n  ".join(problems)
        + "\n🔑 `sidebar.js:730` 已經寫過這條規則，而它只寫在註解裡。")


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
    assert "sa" in _flags("sa"), (
        "`_flags()` 抓不到 `sa` —— 那正是 v1 太窄的地方（「系統」那一組"
        "十二項裡有八項的條件就是它）。")
    assert _flags("true") == set(), "`_flags()` 把 JS 字面值當成旗標。"
    assert _flags("cRpt || cCash || cFi") == {"cRpt", "cCash", "cFi"}, (
        "`_flags()` 抽不出旗標 —— **量法壞了**，上一題會永遠綠。")
    assert _flags("cWL || cDT") != _flags("cWL || cDT || cQ"), (
        "`_flags()` 對兩個不同的條件式回傳相同結果 —— 它沒有辨識力。")

    groups = _groups(nav)
    _l, cond, items = groups["財務"]
    assert _flags(cond), (
        "`sec('財務', …)` 的條件抽不出任何旗標：%r\n" % cond
        + "🔑 **儀器失效** —— 不是「財務組沒有條件」。")
    assert items, "財務組底下一個項目都沒抓到 —— **儀器失效**。"


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
        + "☠️ `sidebar.js:643` 的 `if (g.items.length === 1)` 會把它渲染成"
          "**純連結**，沒有面板也沒有箭頭 ——\n"
        "🔑 那就是使用者兩次說的「沒看到下拉式選單」。")


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
    """`pg('reports.html?tab=cashier')` → `'reports.html'`（`act()` 看到的那個）。"""
    m = re.search(r"['\"]([^'\"]+)['\"]", href_expr or "")
    if not m:
        return None
    return m.group(1).split("/")[-1].split("?")[0].split("#")[0]


def _active_names(expr):
    return re.findall(r"['\"]([^'\"]+)['\"]", expr or "")


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
            by_active.setdefault(f, []).append((label, _flags(cond)))

    problems = []
    for label, href, _names, cond in items:
        tgt = _target_file(href)
        if not tgt:
            continue
        for other_label, other_flags in by_active.get(tgt, []):
            if other_label == label:
                continue
            if not _flags(cond) <= other_flags:
                problems.append(
                    "「%s」(href→%s, %s) 顯示時，「%s」(%s) 可能是隱藏的 "
                    "⇒ `%s` 會進 `_deniedPages` ⇒ 點下去看到「沒有權限」"
                    % (label, tgt, sorted(_flags(cond)), other_label,
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
            by_active.setdefault(f, {})[label] = frozenset(_flags(cond))

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
