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

#: 我釘的接縫。名字要換 **退回給我**，不要自己改題。
_ROUTER_MODULES = ("routers.account_items", "routers.accounts",
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
    non_range = [i for i in broken if "-" not in i["parent_code"]]
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
    ☠️ 而前綴法的失敗方式最安靜：**掛不上的那些會變成第一層**，
       畫面上看起來只是「樹有點亂」，不是一個錯誤。
    🔑 我量到 **232 筆**會這樣（547 筆中）—— 那不是幾個例外。

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
    html = page.read_text(encoding="utf-8")
    js = ""
    cand = _FRONTEND / "js" / (page.stem + ".js")
    if cand.exists():
        js = cand.read_text(encoding="utf-8")
    src = html + "\n" + js
    missing = [s for s in SOURCES if s not in src]
    assert not missing, (
        "`%s` 認不出 %s。\n" % (page.name, missing)
        + "☠️ 少了 `system_default` 的後果最安靜：**一個使用者從來沒建過的項目"
          "出現在「我的自訂」裡，而他不敢刪。**")


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

    # 「唯讀」的判斷必須**綁在 source 上**，不是整頁一律唯讀。
    guarded = re.search(
        r"statutory[^\n]{0,120}(disabled|readonly|唯讀|不可)", src) or re.search(
        r"(disabled|readonly|唯讀|不可)[^\n]{0,120}statutory", src)
    assert guarded, (
        "`%s` 裡「不可編輯」沒有與 `statutory` 綁在同一個判斷上 ——\n" % page.name
        + "☠️ 那通常表示**整頁一律唯讀** ⇒ 使用者連自己加的科目都改不動，\n"
          "   而 ② 那一題照樣綠（它分不出擋過頭）。\n"
        + "⚠️ 我只看「兩者是否出現在同一段判斷附近」——"
          "判斷方式是你的自由，**撞到就退回給我**。")


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
