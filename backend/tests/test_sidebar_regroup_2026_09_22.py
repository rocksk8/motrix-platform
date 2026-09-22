"""§14 MN1–MN5 · 選單重整：三項從「業務」搬到「工作內容」那一組。

使用者 2026-09-22：
> 「業務內的**簽核歷史、簽核佇列、簽核代理人**這三項，移到工作內容，
>   工作內容再選用一個更好的名稱」

---

# 🔑 搬家要驗**兩邊**，而 A 指名的那一半最容易漏

```
新群組有      ← 大家都會驗這一半
舊群組沒有    ← 少了它，「三頁一起消失」也會綠
路由與權限完全沒變 ← 少了它，順手改權限不會被發現
```
☠️ **「三頁一起消失」是一個會讓上半綠、而使用者打不開任何一頁的實作。**

---

# ⚠️ 這個檔的射程：它讀的是 `sidebar.js` 的原始碼

它答的是「**那三項被寫在哪一組底下**」，不是「瀏覽器渲染出來長怎樣」。
📌 擋得住：搬錯組、漏搬、順手改權限條件、忘了改返回連結。
☠️ 擋不住：搬對了而 CSS 讓它看不見、群組收合邏輯壞掉。
🔑 **真正的驗收是目視，而這句話寫在這裡，不寫在豁免表裡。**

---

# 📌 `MN3`（`sidebar.js` 是鎖定檔）要 B 先在 `B.md` 宣告

⚠️ 那是**協定上的動作**，不是這裡的斷言 —— 我驗不到「有沒有人宣告過」。
⇒ 它在覆蓋率守門的 `EXEMPT` 裡，理由欄寫的是「它是怎麼被驗的」。
"""
import re
from pathlib import Path

import pytest

SIDEBAR = (Path(__file__).resolve().parent.parent.parent
           / "frontend" / "static" / "sidebar.js")

#: 要搬的三項（使用者原話的順序）。
MOVED = ("簽核歷史", "簽核佇列", "簽核代理人")

#: 它們的頁面檔名 —— `MN5` 要搜的就是這三個的所有引用點。
MOVED_PAGES = ("approval-history.html", "approval-queue.html",
               "approval-delegates.html")


@pytest.fixture(scope="module")
def sidebar():
    assert SIDEBAR.exists(), f"找不到 {SIDEBAR}"
    return SIDEBAR.read_text(encoding="utf-8")


def _decode_escapes(text):
    r"""只把 `\uXXXX` 還原成字元，**其他一個字都不動**。

    ## ☠️ 我第一版寫的是 `text.encode("utf-8").decode("unicode_escape")`

    那是經典陷阱：`unicode_escape` 按 **latin-1** 解位元組，
    ⇒ 檔案裡**真的中文**（多位元組 UTF-8）會被拆成一堆亂碼。
    🔑 **而症狀是「找不到那一項」** —— 看起來就像那一項不存在，
    📌 於是五題同時紅，而紅的理由跟選單搬家完全無關。

    ⚠️ 我修的是「逃脫序列的中文讀不到」，**而修法把「沒有逃脫的中文」弄壞了**
    ⇒ 〈防護的副作用落在盲側〉：**我看的是我修的那一半。**
    """
    return re.sub(r"\\u([0-9a-fA-F]{4})",
                  lambda m: chr(int(m.group(1), 16)), text)


def _groups(text):
    """`{群組名: 那一組底下的原始碼}`。

    ⚠️ 用 `sec('名字', 條件)` 當分界，而**不是**用行號或字元數 ——
    🔑 那正是 `FX9` 今天換掉的那種判準（〈一個會被註解長度左右的守門，
    量的是排版不是行為〉）。
    """
    marks = [(m.start(), m.group(1))
             for m in re.finditer(r"sec\(\s*'([^']+)'", text)]
    assert marks, "`sidebar.js` 裡找不到任何 `sec('…')` —— 這個檔的結構變了"
    out = {}
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out[name] = text[pos:end]
    return out


def _group_holding(text, label):
    """哪一個群組底下寫著這一項。找不到回 `None`。

    ⚠️ 選單項目的中文可能寫成 `\\uXXXX` 逃脫序列（`簽核佇列` 就是），
    ☠️ 而只比對中文字面的話會**漏掉那一項而不報錯** ——
    🔑 那是〈判準的寬窄都會騙人〉的窄那一側：它會說「沒有人在用它」。
    ⇒ 先把逃脫序列還原再比對。
    """
    for name, body in _groups(_decode_escapes(text)).items():
        if label in body:
            return name
    return None


# ══════════════════════════════════════════════════════════════════════
# MN1 / MN4 · 搬過去，而且舊的那邊不可以還在
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("label", MOVED)
def test_mn1_the_three_items_live_in_the_work_group(sidebar, label):
    """🔴 MN1：三項要在「工作內容」那一組底下（名稱可能已改，見 `MN2`）。

    📌 判準用「**不是『業務』那一組**」而不是「等於某個名字」——
    🔑 因為 `MN2`（改名）**要等使用者裁示**，
    ☠️ 釘死名字的話，使用者一改名這一題就紅在一個與搬家無關的理由上。
    """
    group = _group_holding(sidebar, label)
    assert group is not None, (
        f"`sidebar.js` 裡找不到「{label}」—— 它被刪掉了嗎？")
    assert group != "業務", (
        f"「{label}」還在「業務」那一組底下 —— 使用者要它搬到工作內容那一組。")


@pytest.mark.parametrize("label", MOVED)
def test_mn4_the_three_items_are_gone_from_the_sales_group(sidebar, label):
    """🔴🔴 MN4 反向控制：**「業務」那一組裡不可以還看得到這三項。**

    ☠️ 少了這一半，一個「複製過去而忘了刪掉原本那三行」的實作會綠 ——
    而使用者會在兩個地方各看到一次同樣的東西。
    """
    decoded = _decode_escapes(sidebar)
    sales = _groups(decoded).get("業務", "")
    assert label not in sales, (
        f"「{label}」仍然出現在「業務」那一組裡 —— 搬家只做了一半。")


def test_mn4_the_permission_condition_is_unchanged(sidebar):
    """🔴🔴 MN4 後半：**路由與權限完全沒變。**

    ☠️ A 指名的那一點：**少了這一半，「三頁一起消失」也會綠。**
    🔑 三項目前的顯示條件都是 `cQ`，**搬家不可以順手改它** ——
    📌 改了的話，一批人會忽然看不到簽核佇列，
    而那個症狀離「選單重整」這件事非常遠。
    """
    decoded = _decode_escapes(sidebar)
    for label in MOVED:
        line = next((ln for ln in decoded.splitlines() if label in ln), None)
        assert line is not None, f"找不到「{label}」那一行"
        assert re.search(r"\bcQ\b", line), (
            f"「{label}」的顯示條件不再是 `cQ`：\n  {line.strip()[:140]}\n"
            "☠️ 搬家不可以順手改權限 —— 一批人會忽然看不到它，"
            "而那個症狀離「選單重整」非常遠。")


def test_mn4_the_routes_are_unchanged(sidebar):
    """🔴 MN4 後半：**三頁的路由沒變。**

    ⚠️ 與上一題分開：權限與路由是兩件事，
    ☠️ 而「搬家時順手改了檔名」會讓使用者收到 404，
    🔑 **而書籤與既有的連結全部失效** —— 那比看不到選單更糟。
    """
    for page in MOVED_PAGES:
        assert page in sidebar, (
            f"`sidebar.js` 裡找不到 `{page}` —— 路由被改掉了，"
            "而書籤與既有連結會全部失效。")


# ══════════════════════════════════════════════════════════════════════
# MN5 · 寫死「業務」的返回連結／麵包屑要一起改
# ══════════════════════════════════════════════════════════════════════

def test_mn5_no_page_still_calls_these_three_part_of_sales():
    """🔴 MN5：那三頁裡寫死「業務」的返回連結／麵包屑要一併改。

    🔑 A 指名的判準：**搜三個檔名的所有引用點，不是只改 `sidebar.js`。**
    ☠️ 漏掉的話，使用者從簽核佇列按返回會回到一個已經不存在的分組，
    📌 而那種不一致**不會報錯**，它只是讓人覺得「這個系統有點亂」。
    """
    frontend = Path(__file__).resolve().parent.parent.parent / "frontend"
    offenders = []
    for page in MOVED_PAGES:
        path = frontend / "pages" / page
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "業務" not in line:
                continue
            # 📌 只看麵包屑／返回連結那一類，不看「業務員」「業務負責」這種欄位名。
            if not re.search(r"業務(?!員|負責|開發|人員)", line):
                continue
            # 🔴 B 指出的誤報：`approval-queue.html:1339` 的
            #    `const LABEL = { …, sales: '業務', … }` 是**角色顯示名**，
            #    ☠️ 改它會讓畫面上「業務」這個角色變成別的字 ——
            #    🔑 **而那跟選單搬家毫無關係。**
            # 📌 判準加一條：那一行若在講角色對照表，就不是麵包屑。
            if re.search(r"\b(sales|admin|superadmin|engineer|viewer)\s*:", line):
                continue
            offenders.append(f"{page}:{lineno}  {line.strip()[:80]}")
    assert not offenders, (
        "這幾頁還把自己寫成「業務」底下的：\n  " + "\n  ".join(offenders)
        + "\n⇒ 返回連結／麵包屑要跟著搬家一起改。")


# ══════════════════════════════════════════════════════════════════════
# MN2 · 改名要使用者點頭，這一題只釘「不要自己改」
# ══════════════════════════════════════════════════════════════════════

def test_mn2_the_group_is_renamed_to_the_name_the_user_picked(sidebar):
    """🔴 MN2：那一組改名為 **「我的工作」**。

    使用者原話：「工作內容**再選用一個更好的名稱**」——**選的人是他。**

    ## ⭐ 這一題按照設計走完了一個循環

    我第一版釘的是「**還沒改名**」，而它的失敗訊息寫著
    **「使用者裁示了嗎？裁示了就把名字釘在這裡。」**
    ⇒ 📌 裁示下來了（`我的工作`），⇒ **現在把名字釘進來。**

    🔑 〈守門要驗「有沒有人做過決定」〉：
    **它不是在驗名字對不對，是在驗「有沒有人代替使用者做這個決定」。**
    ☠️ 而舊那一版留在這裡不刪（〈更正要留著錯的那一列〉）：
    **下一個人只看到「釘著我的工作」的話，會以為這個名字一直都是這樣。**

    ## 📌 理由（A 寫的，值得留著）

    搬完之後這一組全部是**「等我處理」或「我做過的」** ——
    **主語是使用者自己，不是模組類型。**
    ☠️ 「工作內容」描述的是**資料**，而簽核佇列不是資料，**是一件要你去做的事。**
    """
    decoded = _decode_escapes(sidebar)
    names = set(_groups(decoded))
    assert "我的工作" in names, (
        f"那一組還不叫「我的工作」，現有分組：{sorted(names)}\n"
        "⇒ 使用者裁示的名字是「我的工作」。")
    assert "工作內容" not in names, (
        f"舊名字「工作內容」還在：{sorted(names)}\n"
        "☠️ 兩個同時存在 ⇒ 改名做了一半，使用者會看到兩個很像的分組。")


# ══════════════════════════════════════════════════════════════════════
# MN6 / MN7 · 搬到了，比搬走了重要
# ══════════════════════════════════════════════════════════════════════
#
# A-2 查了 `sec()`／`ni()` 的實作，後果比原本描述的嚴重：
# ```js
# sec(label, show) { if (show === false) { _curGroup = {…, hidden:true}; return '' } }
#                                          ↑ 不 push 進 _navGroups
# ni(...)          { _curGroup.items.push({…}) }
#                    ↑ push 進一個「不在 _navGroups 裡」的 group
# ```
# ☠️ **整組不會被渲染** —— 不是「掛在看不見的標題底下」，
# **是那三個項目完全消失。**
#
# 🔑 而症狀的形狀是最難被報修的那一種：
# `cQ` 為 true ⇒ 那三頁**不會**進 `_deniedPages` ⇒ **直接打網址仍然打得開**
# ⇒ 使用者遇到的是「**功能還在，但我找不到它**」——
# ☠️ **不會有人報修一個他以為被移除的功能。**


def _section_condition(text, label):
    """`sec('<label>', …)` 的第二個引數（原始字串）。找不到回 `None`。"""
    m = re.search(r"sec\(\s*'" + re.escape(label) + r"'\s*,\s*([^)]*)\)",
                  _decode_escapes(text))
    return m.group(1).strip() if m else None


def test_mn6_the_group_condition_is_the_union_of_its_items(sidebar):
    """🔴🔴 MN6：**分組條件必須是底下每一項條件的聯集。**

    搬進去之後那一組有四項：工作日誌（`cWL`）、每日工作事項（`cDT`）、
    以及搬過來的三項（`cQ`）。
    ⇒ 分組條件要是 **`cWL || cDT || cQ`**。

    ☠️ **不加 `cQ` ＝ 回歸缺陷**：
    一個**有報價單權限、沒有工作日誌／每日工作事項權限**的人
    （**業務人員很可能就是**），搬家後在選單裡**找不到那三項**。
    """
    condition = _section_condition(sidebar, "我的工作")
    assert condition is not None, (
        "找不到 `sec('我的工作', …)` —— 見 `MN2`（改名）。\n"
        "📌 搜尋範圍：`frontend/static/sidebar.js` 全文的 `sec('…', …)`。")
    missing = [name for name in ("cWL", "cDT", "cQ")
               if not re.search(r"\b%s\b" % name, condition)]
    assert not missing, (
        f"「我的工作」的分組條件是 `{condition}`，少了：{'、'.join(missing)}\n"
        "☠️ 少了 `cQ` ⇒ 有報價單權限而沒有工作日誌權限的人（業務很可能就是），"
        "整組看不到 —— 而那三項是他每天要用的。")


def test_mn7_a_quote_only_role_can_still_see_the_three_items(sidebar):
    """🔴🔴 MN7 反向控制：**只有 `cQ` 的角色，那三項要在選單裡看得到。**

    ## 🔑 這一題比 `MN4` 重要：`MN4` 驗的是**搬走**，`MN7` 驗的是**搬到了**

    ☠️ 而「沒搬到」的症狀最難被報修：
    ```
    cQ 為 true ⇒ 那三頁不會進 _deniedPages ⇒ **直接打網址仍然打得開**
    ⇒ 使用者遇到的是「功能還在，但我找不到它」
    ```
    📌 **不會有人報修一個他以為被移除的功能。**

    ## ⚠️ 我驗得到什麼

    這是**結構檢查**：我釘的是「那一組的條件涵蓋 `cQ`，而那三項也在那一組裡」。
    ☠️ 我**驗不到瀏覽器真的渲染出來** —— `sec()`／`ni()` 是 JS，
    🔑 而那兩件合起來仍然不等於「使用者看得到」。
    📌 真正的驗收是目視，而這句話寫在這裡，不寫在豁免表裡。
    """
    condition = _section_condition(sidebar, "我的工作")
    assert condition is not None, "找不到 `sec('我的工作', …)`（見 MN2）"
    assert re.search(r"\bcQ\b", condition), (
        f"「我的工作」的分組條件 `{condition}` 不含 `cQ` ——\n"
        "☠️ 只有報價單權限的人整組看不到，而那三項是他每天要用的。")

    decoded = _decode_escapes(sidebar)
    group = _groups(decoded).get("我的工作", "")
    for label in MOVED:
        assert label in group, (
            f"「{label}」不在「我的工作」那一組裡。\n"
            "🔑 `MN4` 驗的是搬走，這一題驗的是**搬到了** —— 兩半都要。")
