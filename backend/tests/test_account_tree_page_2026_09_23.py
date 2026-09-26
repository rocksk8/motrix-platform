# -*- coding: utf-8 -*-
"""`FN1` · 會計科目樹**頁面**（`v93`/`v94` 的資料層早就好了，而使用者看不到）。

A 派工 `a751377`，依據使用者原話：
> 「會計科目的頁面我還沒看到，但沒關係，你先處理剩餘的」

🔑 A 的讀法我收：**「沒關係」不代表它不重要，代表他在讓路** —— 而傳票已經做完了。

---

# ⚠️ 弱紅聲明：**頁面與 API 都還不存在**

```
frontend/pages/     沒有任何 account／科目 的頁面
routers/            沒有任何 account_items 的端點
```
⇒ 本檔多題會紅在同一個地方。⚠️ 而**前兩題不碰產品碼**（只讀靜態資料集），
   它們**現在就該綠** —— 它們紅表示我的前提錯了，不是 B 沒做。
⇒ B 落地後我會跑突變逐題確認它紅在自己的斷言上。

# 🔴 而 ① 的成因**不只是範圍代號** —— B 量出來、我複核相符

```
A 給的   「二級是範圍代號 => 前綴法會把 1268 掛錯」
B 量到   232/547（42%）前綴壞掉 = **父是範圍 201 ＋ 另一種成因 31**
```
```
範圍代號 13 個，而**只有 4 個在 L2，9 個在 L3**
  L2  11-12 13-15 21-22 71-72
  L3  123-124 126-127 149-155 157-158 219-220 413-423 515-516 611-613 723-724
⇒ 只在 level 2 處理範圍代號的實作，**會漏掉九個**
```
```
那 31 筆與範圍代號無關：
  27 筆  1401…1468  父 139      <= 139 是真的存在的 L3 代號，而子代編號是 14xx
   3 筆  561/581/591  父 51
   1 筆  3220        父 321     <= ☠️ **L4 跑完 3211…3219 之後進位成 3220**
```
🔑 ⇒ **「子代號以父代號為前綴」這個不變量，在這份資料裡根本不成立** ——
   不是「範圍代號的例外」，**四級編號自己會進位跨出父的前綴**。
📌 ⇒ 本檔**不釘任何形式的前綴關係**（B 的建議，而理由是上面那一段）：
   釘了就是一個**永遠紅**的題。釘的是「每一筆的 `parent_code` 都查得到」。
⚠️ 而層級分佈（L1=8／L2=20／L3=94／L4=425）**已經有題**
   （`test_account_items_2026_09_23.py::test_v94_...`）⇒ 這裡不重寫第二份。

⚙️ 而 B 排除了「這是解析器的 bug」：PDF 第 2 欄 20 個代號 == JSON `level==2` 20 個，
   差異只有 `12` vs `11-12`。`561 勞務成本` 掛在 `51 銷貨成本` 底下
   **是官方表自己的形狀** —— 語意上讀起來怪，而我們照抄，不擅自改結構。
"""
import importlib
import json
import re
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_FRONTEND = _BACKEND.parent / "frontend"
STATIC_JSON = _BACKEND / "data" / "account_items_112.json"

TABLE = "account_items"
SOURCES = ("statutory", "system_default", "custom")

#: 官方表裡**本來就沒有子節點**的二級（合計列）。實跑量到的，不是推的。
#: ⚠️ A 建議「每個二級都必須有子節點」—— 而那條規則會**紅在正確的實作上**。
EMPTY_L2 = ["86", "88"]

#: 我釘的接縫。名字要換 **退回給我**，不要自己改題。
_ROUTER_MODULES = ("modules.accounting.api.account_items", "routers.accounts",
                   "routers.account_tree")
#: 頁面檔名候選。
_PAGE_NAMES = ("account-items.html", "accounts.html", "account-tree.html",
               "chart-of-accounts.html")


def _items():
    data = json.loads(STATIC_JSON.read_text(encoding="utf-8"))
    return data["items"]


# ══════════════════════════════════════════════════════════════════════
# ⚙️ 不碰產品碼的兩題 —— **現在就該綠**
# ══════════════════════════════════════════════════════════════════════

def test_the_prefix_shortcut_really_is_wrong_on_the_real_data():
    """⚙️ **證明「不可以靠前綴」是真的，而且規模很大。**

    ☠️ 少了它，下面那題的理由建立在**一個我沒有跑過的描述**上。
    ```
    1268  parent = 126-127     "1268".startswith("126-127") => False
    6111  parent = 611-613
    111   parent = 11-12
    ```
    ⚙️ 而對照組是「**多數筆確實符合前綴**」—— 那正是這個捷徑會被寫出來的原因：
       隨手抽幾筆看都是對的。
    """
    items = _items()
    by = {i["code"]: i for i in items}
    assert by.get("1268", {}).get("parent_code") == "126-127", (
        "`1268` 的 parent 是 %r，我量到的是 '126-127' ——\n"
        % by.get("1268", {}).get("parent_code")
        + "🔑 靜態檔換過了 ⇒ **A 指定的那個正對照要重選**。")

    broken = [(i["code"], i["parent_code"]) for i in items
              if i.get("parent_code") and not i["code"].startswith(i["parent_code"])]
    assert len(broken) > 200, (
        "前綴法掛錯的只有 %d 筆（我量到 232）——\n" % len(broken)
        + "🔑 靜態檔換過了 ⇒ 這一題與下一題的理由都要重算。")

    ok_prefix = [i for i in items
                 if i.get("parent_code") and i["code"].startswith(i["parent_code"])]
    assert ok_prefix, (
        "**一筆符合前綴的都沒有** ——\n"
        "⚙️ 那樣的話前綴法會立刻壞得很明顯，而它不會被寫出來。\n"
        "🔑 這個對照組存在的理由正是：**多數筆是對的，所以捷徑看起來能用。**")

    # 🔴 而「範圍代號」這個成因**不完整**（B 量出來、我複核相符）：
    #    232 = 父是範圍 201 ＋ **另一種成因 31**
    # ☠️ 少了下面這一格，有人把範圍代號處理掉之後會以為前綴法可以用了。
    # ⚠️ `broken` 是 `(code, parent_code)` 的 tuple 不是 dict ——
    #    我第一版當成 dict 索引 ⇒ `TypeError` ⇒ **這個對照組整個不跑**，
    #    而它的訊息會是 Python 的，不是我寫的（〈紅燈說不出話〉）。
    non_range = [(c, p) for c, p in broken if "-" not in p]
    assert len(non_range) >= 30, (
        "與範圍代號無關的前綴例外只有 %d 筆（我與 B 都量到 31）——\n" % len(non_range)
        + "🔑 靜態檔換過了 ⇒ 「前綴法不可用」的理由要重算。")
    by_code = {i["code"]: i for i in items}
    assert by_code.get("3220", {}).get("parent_code") == "321", (
        "`3220` 的 parent 是 %r，我量到的是 '321' ——\n"
        % by_code.get("3220", {}).get("parent_code")
        + "☠️ 那一筆是整份資料裡最刺的一個：**L4 跑完 3211…3219 之後進位成 3220**\n"
          "   ⇒ `\"3220\".startswith(\"321\")` 為 False，而它的父確實是 `321`。\n"
        + "🔑 ⇒ 「子代號以父代號為前綴」**不是一個可以修補的規則，它根本不成立**。")

    ranges = [i["code"] for i in items if "-" in i["code"]]
    lv = sorted({i["level"] for i in items if "-" in i["code"]})
    assert lv == [2, 3], (
        "範圍代號出現在層級 %r（我與 B 都量到 L2 四個、L3 九個）——\n" % lv
        + "⚠️ **只在 level 2 處理範圍代號的實作會漏掉九個**，"
          "而這一格就是在守那句話。（共 %d 個）" % len(ranges))


def test_the_level_invariant_holds_on_the_real_data_and_catches_every_prefix_error():
    """⚙️🔑 **`parent.level == level - 1` —— 一條完美判別的不變量。**

    A 實跑、我複驗（547 筆）：
    ```
    套在真實資料（parent_code）    => 違反 **0** 筆
    套在前綴法建出來的樹           => 抓到 **232** 筆  <= **全部**
    ```
    🔑 ⇒ **它一次擋掉全部，而且在正確實作上是乾淨的零。**
    📌 比「`1268` 的父必須是 `126-127`」強：那一題只釘**一個例子**，
       而這一條釘的是**結構**。⚠️ 而兩個都留著 ——
       **不變量擋全部，具名例子讓紅燈訊息看得懂。**

    ⚙️ 而這一題同時是那條不變量的**儀器自檢**：
       它在真實資料上零違反（否則它擋不了任何實作），
       在前綴法上抓到全部（否則它沒有鑑別力）。
    """
    items = _items()
    by = {i["code"]: i for i in items}

    bad = [(i["code"], i["parent_code"]) for i in items
           if i.get("parent_code")
           and by.get(i["parent_code"], {}).get("level") != i["level"] - 1]
    assert not bad, (
        "真實資料上就有 %d 筆違反 `parent.level == level - 1`：%s\n"
        % (len(bad), bad[:6])
        + "🔑 那樣這條不變量**擋不了任何實作** —— 它會在正確的樹上也紅。")

    roots = [i for i in items if not i.get("parent_code")]
    assert roots and all(i["level"] == 1 for i in roots), (
        "沒有 parent 的那些不全是 level 1：%s\n"
        % sorted({i["level"] for i in roots})
        + "⚠️ 那樣「level 1 沒有 parent」這一半就不成立。")

    # ⚙️ 鑑別力：套在**前綴法**建出來的樹上，它必須抓到全部 232 筆。
    codes = set(by)

    def prefix_parent(code):
        for n in range(len(code) - 1, 0, -1):
            if code[:n] in codes:
                return code[:n]
        return None

    caught = notfound = 0
    for i in items:
        if not i.get("parent_code"):
            continue
        g = prefix_parent(i["code"])
        if g is None:
            notfound += 1
        elif by[g]["level"] != i["level"] - 1:
            caught += 1
    assert caught > 200, (
        "這條不變量在前綴法的樹上只抓到 %d 筆（預期 232）——\n" % caught
        + "🔑 它的鑑別力不夠 ⇒ 一個用前綴法的實作可能照樣綠。")
    assert notfound == 0, (
        "前綴法有 %d 筆**找不到父**（我與 A-2 都量到 0）——\n" % notfound
        + "🔑 那個 0 正是「它結構上不可能報錯」的證據：\n"
          "   前綴法**永遠退得到一個存在的較短前綴**（最短退到一級 1–9）。\n"
        + "☠️ 靜態檔換過了 ⇒ 那個「全部靜默」的結論要重算。")


def test_every_parent_code_points_at_an_existing_row():
    """⚙️ **也該現在就綠**：每一個 `parent_code` 都指向存在的科目。

    📌 那是 ④（新增自訂科目 parent 必須存在）的**前提**：
       若法定資料自己就有孤兒，那道檢查一開就會擋住既有資料。
    """
    items = _items()
    codes = {i["code"] for i in items}
    orphan = sorted(i["code"] for i in items
                    if i.get("parent_code") and i["parent_code"] not in codes)
    assert not orphan, (
        "有 %d 筆的 parent 不存在：%s\n" % (len(orphan), orphan[:8])
        + "☠️ 那樣 ④ 的檢查一開就會擋住**既有的法定資料**。")


# ══════════════════════════════════════════════════════════════════════
# ① 四層樹要從 parent_code 建
# ══════════════════════════════════════════════════════════════════════

def _router():
    for name in _ROUTER_MODULES:
        try:
            return name, importlib.import_module(name)
        except Exception:                                  # noqa: BLE001
            continue
    pytest.fail(
        "找不到會計科目的 router（找過：%s）。\n" % list(_ROUTER_MODULES)
        + "⚠️ 這是**弱紅**：本檔多題會紅在同一句話上。\n"
          "   名字可以換（**退回給我**），而那個端點必須存在 ——\n"
          "   `v93`/`v94` 的 547 筆現在**沒有任何一條路**送得到畫面上。")


def _page():
    for name in _PAGE_NAMES:
        p = _FRONTEND / "pages" / name
        if p.exists():
            return p
    pytest.fail(
        "找不到會計科目的頁面（找過：%s）。\n" % list(_PAGE_NAMES)
        + "⚠️ 這是**弱紅**。名字可以換（**退回給我**）。")


def test_fn1_the_tree_is_built_from_parent_code_not_from_the_code_prefix():
    """🔴🔴 `FN1①` **四層樹從 `parent_code` 建，不可以靠代號前綴推。**

    ```
    1268  parent = 126-127     ← 前綴法：**掛不上任何父節點**
    ```
    ☠️ 而前綴法的失敗方式**比我第一版寫的糟得多**：

    ```
    我第一版寫的  「掛不上的那些會變成第一層，畫面上只是樹有點亂」  ← **錯的**
    實際量到      掛到**存在但錯誤**的父  232
                  **找不到父**            **0**
    ```
    🔑 **沒有一筆會報錯。樹建得出來、每一筆都有父、而 42% 掛在錯的地方。**
    📌 成因：前綴法**永遠退得到一個存在的較短前綴**（最短退到一級 `1`–`9`）
       ⇒ 它**結構上不可能報「找不到父」**。
    ```
    111 現金及約當現金   真實父 = 11-12（流動資產）
                         前綴法 => 掛到 **1（資產）**   ← **少了一整層**
    ⇒ 「流動資產」那一層會是空的
    ⇒ ☠️ **報表小計錯，而畫面上每一個數字都正常**
    ```
    ⚠️ 我把錯的那一版留著（〈更正要留著錯的那一列〉）——
       兩個版本都說「很安靜」，**而它們的處置不同**：
       「變成第一層」看得出來（樹的形狀怪），**「掛到錯的父」看不出來**。

    ⚙️ 正對照要用**實際資料**不是合成的：`1268` 的父必須是 `126-127`
       —— 合成的資料我可以挑一個剛好前綴對的，那樣兩種實作都會綠。
    """
    where, mod = _router()
    name, fn = None, None
    for n in ("build_tree", "account_tree", "_build_tree", "list_tree"):
        if callable(getattr(mod, n, None)):
            name, fn = n, getattr(mod, n)
            break
    assert fn is not None, (
        "`%s` 沒有建樹的那一支（找過 `build_tree` / `account_tree` …）——\n" % where
        + "⚠️ 名字可以換（**退回給我**），而它要抽得出來："
          "**內嵌在 endpoint 裡的話，只有走過那條路才驗得到。**")

    items = _items()
    tree = fn(items)
    parent_of = {}

    def walk(nodes, parent):
        for nd in nodes or ():
            code = nd["code"] if isinstance(nd, dict) else nd.code
            parent_of[code] = parent
            kids = (nd.get("children") if isinstance(nd, dict)
                    else getattr(nd, "children", None))
            walk(kids, code)

    walk(tree, None)
    assert parent_of.get("1268") == "126-127", (
        "`1268` 掛在 %r 底下，而它的 `parent_code` 是 `126-127`。\n"
        % parent_of.get("1268")
        + "☠️ 那是**前綴法**的症狀：`\"1268\".startswith(\"126-127\")` 為 False\n"
          "   ⇒ 它掛不上任何父節點 ⇒ **變成第一層** ⇒ 畫面上只是「樹有點亂」。\n"
        + "🔑 我量到 232 筆會這樣（547 筆中），不是幾個例外。")
    assert len(parent_of) == len(items), (
        "樹裡有 %d 個節點，資料有 %d 筆 —— **有節點掉了**。\n"
        % (len(parent_of), len(items))
        + "☠️ 掉的那些不會報錯，它們只是**不在畫面上**。")

    # 🔑🔑 結構不變量：**一次擋掉全部 232 筆**，而具名例子只擋一筆。
    by = {i["code"]: i for i in items}
    wrong_level = [(c, p) for c, p in parent_of.items()
                   if p is not None and by[p]["level"] != by[c]["level"] - 1]
    assert not wrong_level, (
        "有 %d 個節點掛在**層級不對**的父底下，前 6 個：%s\n"
        % (len(wrong_level), wrong_level[:6])
        + "🔑 不變量是 `parent.level == level - 1` —— "
          "它在真實資料上是**乾淨的零**，在前綴法的樹上抓到 **232** 筆。\n"
        + "☠️ 而它的長相是**吃掉一整層**：`111 現金及約當現金` 的真實父是\n"
          "   `11-12 流動資產`，前綴法把它掛到 `1 資產`\n"
          "   ⇒ **「流動資產」那一層是空的，而小計會錯、畫面上每個數字都正常。**")

    # ⚙️ A 建議「每個二級節點都必須有子節點」（空層＝被跳過的證據）。
    # 🔴 **而那條規則是錯的，我實跑查出來的**：
    # ```
    # L2 沒有子節點的：**2 個**  86 本期稅後淨利(淨損) ／ 88 本期綜合損益總額
    # （L3 也有 3 個：218 / 811 / 831）
    # ```
    # ⇒ 它們是官方表裡的**合計列**，本來就沒有子項
    #   ⇒ 照 A 的原話寫，會**紅在一個正確的實作上**。
    # 📌 ⇒ 改成釘**已知集合**：多出來才紅（一整層被吃掉會多出很多個）。
    has_child = {p for p in parent_of.values() if p is not None}
    empty_l2 = sorted(c for c in parent_of
                      if by[c]["level"] == 2 and c not in has_child)
    assert empty_l2 == EMPTY_L2, (
        "沒有子節點的二級節點是 %s，已知的是 %s。\n" % (empty_l2, EMPTY_L2)
        + "☠️ **多出來的那些就是「有一層被吃掉」的證據** —— "
          "它們的子節點被掛到更上面去了。\n"
        + "⚠️ 少了的話請先看是不是靜態檔換了：`86`/`88` 是官方表的**合計列**，"
          "本來就沒有子項。")


# ══════════════════════════════════════════════════════════════════════
# ②③ 法定不可編輯，而三態要分得出來
# ══════════════════════════════════════════════════════════════════════

def test_fn1_the_page_says_statutory_rows_cannot_be_edited():
    """🔴 `FN1②` **法定科目在畫面上就不可編輯 —— 不是等資料庫擋。**

    ```
    現況（資料層已經擋了）  使用者按下「編輯」=> 存檔 => **500／RAISE(ABORT) 那句話**
    ```
    ☠️ 那是〈降級之後它還是會動〉的鄰居：**能用，而很差** ——
       使用者打完整張表單才被告知他從一開始就不能改。
    🔑 這一題釘的**不是資料層**（`v93` 的兩支 TRIGGER 已經驗過了），
       是「**畫面有沒有把它講出來**」。

    ⚠️ 而我不釘版面細節（按鈕長怎樣、什麼顏色）—— 那是 B 的自由。
       ⇒ 釘的是：**頁面裡認得出 `statutory` 這個狀態，而且對它有不同的處置。**
    """
    page = _page()
    html = page.read_text(encoding="utf-8")
    js = ""
    for cand in (_FRONTEND / "js" / (page.stem + ".js"),):
        if cand.exists():
            js = cand.read_text(encoding="utf-8")
    src = html + "\n" + js

    assert "statutory" in src, (
        "`%s` 整支檔沒有出現 `statutory` ——\n" % page.name
        + "☠️ 畫面分不出法定與自訂 ⇒ 使用者按下編輯才被資料庫擋，\n"
          "   而他看到的是 `RAISE(ABORT)` 那句話。")
    assert re.search(r"statutory", src) and re.search(
        r"disabled|readonly|不可(修改|編輯)|唯讀", src), (
        "`%s` 認得 `statutory`，而沒有任何「不可編輯」的表達"
        "（找過 `disabled` / `readonly` / 唯讀 / 不可修改）——\n" % page.name
        + "⚠️ 用什麼方式表達是你的自由，而**它必須在按下去之前就說出來**。")


def test_fn1_all_three_sources_are_distinguishable_on_the_page():
    """🔴 `FN1③` **三態要分得出來：`statutory` / `system_default` / `custom`。**

    ☠️ 把 `system_default` 併進 `custom` 的後果（`db.py:4190` 逐字）：
    ```
    使用者日後**找不到是誰建的** ——
    一個他從來沒建過的項目出現在「我的自訂」裡，**而他不敢刪**
    ```
    📌 `§54c` 的形狀：三個都要在，而不是「有 statutory 就好」。
    """
    page = _page()
    cand = _FRONTEND / "js" / (page.stem + ".js")
    assert cand.exists(), (
        "找不到 `%s` —— 三態的判斷要在**行為那一層**。\n" % cand.name
        + "⚠️ 檔名要換 **退回給我**。")
    js = cand.read_text(encoding="utf-8")

    # 🔴 **只看 JS，不看 HTML** —— 我第一版看 `html + js`，而那是假綠燈：
    # ```
    # 突變：把 JS 裡的 system_default 改掉 => 我的題**照樣綠**
    # 成因：HTML 裡還有 `.ai-tag.system_default{...}` —— 那只是一個 **CSS class**
    #       ⇒ JS 不再產生那個值的話，那條樣式是**死的**
    # ```
    # 🔑 〈判準的寬窄都會騙人〉：**超集永遠比較好過** ——
    #    「這個字出現在這兩個檔的任何地方」是一個太寬的判準。
    missing = [s for s in SOURCES if s not in js]
    assert not missing, (
        "`%s` 認不出 %s。\n" % (cand.name, missing)
        + "☠️ 少了 `system_default` 的後果最安靜：**一個使用者從來沒建過的項目"
          "出現在「我的自訂」裡，而他不敢刪。**")

    # ⚙️ 而三個要**被列在一起**（一份數得出來的清單），不是散在三個地方。
    flat = re.sub(r"\s+", " ", js)
    together = any(
        all(s in flat[m:m + 160] for s in SOURCES)
        for m in range(0, len(flat), 40))
    assert together, (
        "`%s` 三個 source 都在，而**沒有出現在同一份清單裡**。\n" % cand.name
        + "📌 `§54c` 的形狀：清單要能被數 —— 散在三個 `if` 裡的話，"
          "**加第四種狀態時不會有任何訊號**。")


def test_fn1_custom_rows_must_still_be_editable_on_the_page():
    """⚙️ `FN1③` 的**反向控制：`custom` 那一列在畫面上必須可以改。**

    ☠️ 少了它，一個「全部唯讀」的頁面也會讓 ② 綠 ——
       而症狀是**使用者連自己加的科目都改不動**。
    🔑 而法條正是允許「商業得視實際需要增減其會計項目」（`db.py:4176` 引）。
    📌 這一題與 ② 是同一個軸的兩端，而**只有「擋不住」那一端會被報修**。
    """
    page = _page()
    html = page.read_text(encoding="utf-8")
    js = ""
    cand = _FRONTEND / "js" / (page.stem + ".js")
    if cand.exists():
        js = cand.read_text(encoding="utf-8")
    src = html + "\n" + js

    # 🔴 **我改過兩次，兩次都是 B 指出來的，而第二次的理由比第一次深**
    # ```
    # v1  statutory[^\n]{0,120}(唯讀|不可…)    => **跨不了行** => 假陽性
    #     （B 的綁定寫在 x-show，唯讀兩個字在下一行）
    # v2  壓掉換行再看鄰近度                    => 排版無關了，**而**
    #     🔑 B：「我沒有改行為，只改了排版」
    #     ⇒ 它驗的是「這兩個詞排在附近」，**不是「有沒有綁在一起」**
    #     ☠️ 一個把 `statutory` 寫進同一行**註解**的實作照樣會過
    # ```
    # ⇒ v3 釘**結構**：要有一個**屬性綁定運算式**同時提到 `source` 與 `statutory`。
    #   ⚙️ 而先把 HTML 註解剝掉 —— B 的元素上面就有一段寫著同樣字眼的註解。
    no_comment = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    exprs = [m.group(3) for m in re.finditer(
        r"""(x-show|x-if|x-bind|:class|:disabled|v-if|v-show|:readonly)"""
        r"""\s*=\s*(["'])((?:(?!\2).)*)\2""", no_comment)]
    exprs = [e for e in exprs if "source" in e and "statutory" in e]
    assert exprs, (
        "`%s` 裡沒有任何**綁定運算式**同時提到 `source` 與 `statutory`。\n"
        % page.name
        + "☠️ 那通常表示**整頁一律唯讀**（條件被寫死）⇒ 使用者連自己加的\n"
          "   科目都改不動，而 ② 那一題照樣綠（它分不出擋過頭）。\n"
        + "⚠️ 我釘的是**結構不是排版**：要有一個 `x-show` / `:class` / `v-if` …\n"
          "   的值裡同時出現 `source` 與 `statutory`。\n"
          "   ⚙️ HTML 註解已剝掉 —— 寫在註解裡不算。\n"
        + "📌 用別的機制（例如在 JS 算好一個 `row.locked`）**退回給我**，"
          "我把那個形狀加進來。")


# ══════════════════════════════════════════════════════════════════════
# ④⑤ 新增與停用
# ══════════════════════════════════════════════════════════════════════

def test_fn1_creating_a_custom_item_requires_an_existing_parent():
    """🔴 `FN1④` **新增自訂科目時，`parent_code` 必須指向存在的科目。**

    ☠️ 放行的後果不是報錯，是**那一筆從樹上消失**：
    ```
    parent_code = '9999'（不存在）=> 建樹時掛不上任何節點
    => 使用者建好了、清單查得到、**而樹上看不到它**
    ```
    🔑 而他會再建一次。
    ⚙️ 正對照：`parent_code` 指向存在的科目**必須成功**。
    """
    import sqlite3
    import tempfile

    import db
    where, mod = _router()
    fn = None
    for n in ("validate_parent", "check_parent", "_validate_parent"):
        if callable(getattr(mod, n, None)):
            fn = getattr(mod, n)
            break
    assert fn is not None, (
        "`%s` 沒有 parent 檢查（找過 `validate_parent` / `check_parent`）——\n"
        % where
        + "⚠️ 名字可以換（**退回給我**），而那個判斷要抽得出來：\n"
          "   內嵌在 endpoint 裡的話，**只有走過那條路才驗得到**。\n"
        + "📌 我釘的形狀：`validate_parent(conn, parent_code) -> (ok, err)`；\n"
          "   `err` 是**給使用者看的字串**，而它要說出是哪一個代號找不到。")

    path = Path(tempfile.mkdtemp(prefix="motrix-C-fn1p-")) / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        bad = fn(conn, "9999")
        good = fn(conn, "126-127")
    except TypeError as e:
        pytest.fail(
            "`%s` 的 parent 檢查我叫不動：%s\n" % (where, e)
            + "⚠️ **壞的可能是我的呼叫方式，不是產品** —— "
              "我照 `validate_parent(conn, parent_code)` 叫。簽名改了**退回給我**。")
    finally:
        conn.close()

    ok_bad = bad[0] if isinstance(bad, tuple) else bad
    err_bad = bad[1] if isinstance(bad, tuple) else ""
    ok_good = good[0] if isinstance(good, tuple) else good

    assert not ok_bad, (
        "`parent_code='9999'`（不存在）**通過了**檢查 ——\n"
        + "☠️ 那一筆建好了、清單查得到，**而樹上看不到它**（掛不上任何節點）\n"
          "   ⇒ 使用者會再建一次。")
    assert "9999" in str(err_bad), (
        "擋下來了，而訊息裡沒有 `9999`：%r\n" % (err_bad,)
        + "🔑 要說出**是哪一個代號找不到** —— 與借貸平衡的「說出差額」同一族。")
    assert ok_good, (
        "`parent_code='126-127'`（**存在**，法定二級）被擋下來了 ——\n"
        + "⚙️ 這是正對照：少了它，「一律拒絕」也會讓上面兩個斷言綠，\n"
          "   **而那樣使用者一個自訂科目都建不了**。\n"
        + "⚠️ 而我刻意挑一個**範圍代號**當正對照："
          "若實作用前綴驗 parent，它會在這裡紅。")


def _auth(client, make_user, role="superadmin"):
    username, password = make_user(role=role)
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_fn1_the_endpoint_answers_over_http(client, make_user):
    """🔴 **`GET /api/account-items` 要在 HTTP 那一層真的回得出來。**

    ☠️ B 2026-09-23 **明著說**他沒走過這一層：
    > 「`build_tree` / `validate_parent` / 序列化 ✅ 實跑；
    >   `GET /api/account-items` 的 **HTTP 層**（登入 → 帶 token → 200）❌ 沒跑過。
    >   我用對照組確認 auth 樣式與 `map_points.py` 逐字相同，
    >   **而那是推論不是量測**。」

    🔑 〈證據的適用範圍〉：函式跑得動 ≠ 端點回得出來。中間還有
       **路由註冊／auth 依賴／序列化**三層，而它們各自都壞過。
    ⚙️ 而它同時是**登入這件事本身**的對照：`401` 與 `200` 要分得出來 ——
       少了那一格，一個「誰都可以拿」的端點也會讓這一題綠。
    """
    hdr = _auth(client, make_user)
    r = client.get("/api/account-items", headers=hdr)
    assert r.status_code == 200, (
        "`GET /api/account-items` 回 %s。\n%s\n" % (r.status_code, r.text[:300])
        + "☠️ 函式層全綠而端點回不出來 —— 中間還有路由註冊／auth 依賴／序列化。")

    body = r.json()
    rows = body.get("items") or body.get("rows") or body.get("tree") or body
    assert rows, (
        "端點回 200 而內容是空的：%r\n" % (str(body)[:200],)
        + "☠️ **空的 200 與正確的 200 在狀態碼上長得一樣。**")

    # ⚙️ 反向控制：不帶 token 一定要被擋。
    anon = client.get("/api/account-items")
    assert anon.status_code in (401, 403), (
        "不帶 token 也回 %s ——\n" % anon.status_code
        + "⚙️ 這是正對照：少了它，一個**誰都可以拿**的端點會讓上面那一題綠，\n"
          "   而會計科目表是內部資料。")


def test_fn1_disabling_is_possible_without_deleting():
    """🔴 `FN1⑤` **要能「停用」而不是只能刪除 —— 而現在沒有那個欄位。**

    ```
    db.py:4184 account_items 的欄位：code / level / name / name_en /
                                    parent_code / source
    => **沒有任何 is_active／disabled／停用 的欄位**
    ```
    ⚠️ 而 `db.py:4191` 的註解逐字寫著 `system_default` 「**可停用**、可改指向」
       ⇒ 那個意圖存在，**而承載它的欄位不存在**。
    ☠️ 少了它，使用者面對一個用不到的科目只有兩條路：
    ```
    留著   => 下拉選單愈來愈長，而他每次都要略過它
    刪掉   => 已被傳票引用的刪不掉（v95 的 TRIGGER），**而沒被引用的刪掉就沒了**
    ```
    📌 而「刪掉就沒了」在會計上是不可接受的：**歷史單據的科目要留著**。
    """
    import sqlite3
    import tempfile

    import db
    path = Path(tempfile.mkdtemp(prefix="motrix-C-fn1-")) / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % TABLE)}
    conn.close()

    flag = [c for c in cols
            if c in ("is_active", "active", "disabled", "is_disabled",
                     "enabled", "is_enabled")]
    assert flag, (
        "`%s` 沒有任何停用旗標。現有欄位：%s\n" % (TABLE, sorted(cols))
        + "⚠️ 而 `db.py` 的註解逐字寫著 `system_default` 「**可停用**」——\n"
          "   **意圖在，而承載它的欄位不在。**\n"
        + "🔑 名字可以換（**退回給我**），而它要是一個**可以被查詢**的欄位：\n"
          "   放在 JSON 裡的話，「只列出還在用的科目」那個查詢寫不出來。")
