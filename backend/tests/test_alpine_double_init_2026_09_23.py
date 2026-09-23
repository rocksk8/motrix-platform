# -*- coding: utf-8 -*-
"""`AL1` · Alpine `init()` 跑兩遍 —— **把既有的掃描工具接進 pytest**（A `§174` (b)）。

```
<body x-data="foo()" x-init="init()">
      ^^^^^^^^^^^^^^ Alpine 3 看到物件有 init() 就會自己叫一次
                     ^^^^^^^^^^^^^^^ 這一句再叫一次  => **跑兩遍，完全沒有警告**
```
後果不只是 API 發兩次：**第二次的回應晚一步抵達，會把使用者這段期間改過的
欄位用伺服器上的舊值無聲蓋回去**（2026-09-11 踩過兩次，記在工具 docstring）。

# 🔴 這一題釘的不是缺陷，是**那支工具沒有人在跑**

```
backend/tools/check_double_init.py   2026-09-11 就存在
它說的數字                            53 頁（與另外兩把獨立的尺一致）
grep backend/tests/ 找呼叫端          **0**
而它自己在這台機器上                   UnicodeEncodeError: cp932 編不了 emoji
                                     => **印到一半就死**
```
🔑 〈兩個都對而路不存在〉：**工具有、決定有、清單有，而沒有人在跑它。**

# 🔴 `(a-2)`：現在的判準有一個**未來式的引信**

```
check_double_init.py:68  guarded = "_initDone" in blob
             :57  blob = 頁面 HTML ＋ 它 <script src> 進來的**全部 js**
而 auth-guard.js ／ notif.js ／ sidebar.js **三個都是全部母體頁都引用**
⇒ _initDone 寫進這三個任何一個 ⇒ 53 頁**一次全翻成「已修」**
☠️ 而要修的那兩個 store 就在 notif.js 裡 ⇒ **修法本身就是引信**
```
📌 **今天還沒被點燃**：七支共用檔的 `_initDone` 命中數全部是 0
  ⇒ 報表現在是誠實的 ⇒ **`(a-2)` 的窗口就是現在**。

# ☠️ 宣告點 ≠ 定義點（A-2 攔下的，條文差點寫錯）

```
宣告點（x-data + x-init，**掃描器唯一找得到的東西**）
  sidebar.js  **2 個**  :196 globalSearchStore() ／ :377 notifStore()
  notif.js    **0 個**   auth-guard.js  **0 個**
定義點（函式本體，_initDone 要寫進去的地方）
  notif.js:29 function notifStore() ／ notif.js:401 function globalSearchStore()
```
🔑 **`sidebar.js` 同時在兩個集合裡**（污染別人的 blob ＋ 自己有宣告），
  而 `notif.js` **只在排除集合**。記這個例子比記規則好用。
"""
import importlib.util
import io
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "backend" / "tools" / "check_double_init.py"

#: `§174` 實算。⚠️ **算出來的，不要手列** —— 這裡只拿來當對照，不當判準。
SHARED_FILES = ("auth-guard.js", "notif.js", "sidebar.js", "edit-presence.js",
                "approval-cascade.js", "list-sort.js", "gov-lookup.js")

#: `§174` 的四個「行為保持」數字。⚠️ `(a-2)` 做完**一個都不可以變**。
PAGE_POPULATION = 53
SHARED_POPULATION = 2
ALREADY_GUARDED = 2

#: 共用母體的**宣告點**在這裡（不是 `notif.js`）。
DECL_FILE = "frontend/static/sidebar.js"

#: 定義點 —— `_initDone` 要寫進去的地方。
DEF_FILE = "frontend/static/notif.js"
DEF_STORES = ("notifStore", "globalSearchStore")


def _tool():
    """按路徑載入那支工具。

    ⚠️ 明著關掉 bytecode：共用工作目錄，別人會看到 `backend/tools/__pycache__`。
    """
    if not TOOL.is_file():
        pytest.fail("`backend/tools/check_double_init.py` 不見了 —— 它是受測物。")
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("_al1_tool", TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


#: `(a-2)` 的兩個名字。
#:
#: 🔴 **更正留著**：A `§176` 先裁 `SHARED_GLOB`，而 B 已經實作成 **`STATIC_GLOB`**
#: （`= frontend/static/*.js`，不是只有 `sidebar.js`）。我照**實作**走 ——
#: 照裁定寫的話，這一題會紅在一支已經做對的碼上。
#: ⚠️ 而 `STATIC_GLOB` **只是正對照的可替換範圍，不是排除清單本身**：
#:    排除清單是 `shared_js()` **算出來的**（被 >1 頁 script-link），不可寫死。
SHARED_SCAN = "scan_shared"
SHARED_HOOK = "STATIC_GLOB"


def _shared_scan(mod):
    """`(a-2)` 的共用母體。"""
    fn = getattr(mod, SHARED_SCAN, None)
    if callable(fn):
        return fn()
    pytest.fail(
        "`check_double_init.py` 還沒有 `%s()`（`(a-2)` 未做）。\n" % SHARED_SCAN
        + "📌 `§174`：**兩個集合，不要合成一個**\n"
          "    排除清單 := 被 >1 頁 script-link 的 js（實算 7 檔，**要算不要手列**）\n"
          "    共用母體 := `sidebar.js` 裡的 2 個 `x-data` ＋ `x-init` **宣告**\n"
        + "☠️ 不要寫成「掃 `notif.js` 的兩個 store」——那裡的宣告數是 **0**，\n"
          "   `53 + 2 = 55` 會永遠湊不出來，而人會開始懷疑 regex 壞了。")


# ══════════════════════════════════════════════════════════════════════
# ⓪ 先證明尺量得到東西
# ══════════════════════════════════════════════════════════════════════

def test_al1_the_scanner_actually_finds_pages():
    """⚙️ **掃不到東西的話，主斷言會因為空集合而變綠。**

    🔑 〈假綠燈：清單為空的斷言〉——`all(… for … in [])` 是 `True`。
    """
    rows = _tool().scan()
    assert rows, (
        "`scan()` 一列都沒回 ——\n"
        + "☠️ 那會讓「每一頁都有守衛」那一題**無條件通過**。\n"
        + "⚠️ 多半是 `PAGES_GLOB` 指到了不存在的目錄。")
    for k in ("page", "guarded", "editable", "risk"):
        assert k in rows[0], (
            "`scan()` 回的列少了 `%s` 欄：%r —— 形狀改了，**退回給我**。"
            % (k, rows[0]))


def test_al1_the_scanner_would_notice_a_missing_guard(tmp_path, monkeypatch):
    """⚙️ **正對照：拿掉守衛，這把尺看得出來嗎？**（A 指定）

    **走受測物那條量測路徑**（真的呼叫 `scan()`），而輸入是**我合成的**
    —— 🔑 釘在真缺陷上的正對照會在缺陷修好那天失效。
    """
    mod = _tool()
    head = '<body x-data="demoPage()" x-init="init()">\n<script>\n'
    (tmp_path / "al1_guarded.html").write_text(
        head + "function demoPage(){return{_initDone:false,init(){}}}\n"
        "</script></body>", encoding="utf-8")
    (tmp_path / "al1_bare.html").write_text(
        head + "function demoPage(){return{init(){}}}\n"
        "</script></body>", encoding="utf-8")

    monkeypatch.setattr(mod, "PAGES_GLOB", str(tmp_path / "*.html"))
    rows = {r["page"]: r for r in mod.scan()}

    assert set(rows) == {"al1_guarded.html", "al1_bare.html"}, (
        "合成的兩頁沒有被完整掃到：%s" % sorted(rows))
    assert rows["al1_guarded.html"]["guarded"] is True, (
        "有 `_initDone` 的那一頁被判成**未修** ——\n"
        + "☠️ 這把尺會把修好的頁面一直報成待修（假陽性）。")
    assert rows["al1_bare.html"]["guarded"] is False, (
        "**沒有 `_initDone` 的那一頁被判成已修** ——\n"
        + "☠️ 尺亮不起來，主斷言就算全綠也什麼都沒證明。")


def test_al1_the_scanner_survives_an_ascii_only_console():
    """🔴 **`(a-1)`：那支工具在 cp932 主控台上不可以死。**

    ```
    UnicodeEncodeError: 'cp932' codec can't encode character '\\U0001f534'
    ```
    ☠️ 症狀不是「報錯」，是**印到一半就死** —— 前面幾行印出來了，
       看起來像跑完了，而**待修清單那一段沒印**。
    🔑 〈Windows 查驗陷阱〉：這台機器上的失敗常常長成「少了一段輸出」。
    📌 而它違反的正是我們自己的規則：**診斷輸出一律 ASCII**。
    """
    mod = _tool()
    sink = io.TextIOWrapper(io.BytesIO(), encoding="cp932", errors="strict")
    old_out, old_argv = sys.stdout, sys.argv
    try:
        sys.stdout, sys.argv = sink, ["check_double_init.py"]
        mod.main()
    except UnicodeEncodeError as e:
        sys.stdout = old_out
        pytest.fail(
            "在 cp932 主控台上炸了：%s\n" % e
            + "☠️ 它會**印到一半就死** —— 待修清單印不出來，\n"
              "   而前面幾行看起來完全正常。\n"
            + "🔑 修法是把 `LABEL` 那幾個 emoji 換成 ASCII（`[HIGH]`／`[OK]`…），\n"
              "   **不是**叫大家改主控台編碼。")
    finally:
        sys.stdout, sys.argv = old_out, old_argv


# ══════════════════════════════════════════════════════════════════════
# ① `(a-2)`：兩個集合，不要合成一個
# ══════════════════════════════════════════════════════════════════════

def test_al1_excluding_the_shared_files_actually_changes_the_answer():
    """⚙️ **排除清單要**真的生效** —— 舊判準與新判準的差額量得出來。**

    ## 🔴 這一題**換過一次**，而換的理由要留著

    ```
    舊版  斷言「七支共用檔的 `_initDone` 命中數 = 0」
          —— 那是 `(a-2)` 行為保持窗口的**前提**，我自己標了它有保存期限
    而 (c) 一開跑，守衛**就寫在 notif.js 裡** => 那個前提不再成立 => 它紅了
    ```
    🔑 **那是正確的紅**：它在說「窗口關了」。
    ⇒ 而窗口關了之後，該釘的不再是前提，是**排除本身有沒有作用**。

    ## ⚙️ 新的觀測點：舊判準會多算幾頁

    ```
    舊判準  guarded = "_initDone" in （頁面 ＋ **所有** linked js）
    新判準  只看這一頁自己的 js
    差額 = 舊判準會把幾頁**誤判成已修**
    ```
    ☠️ 差額是 0 的時候有兩種可能，而它們差很多：
    ```
    ① 共用檔裡沒有 `_initDone`  => 排不排除**沒差** => 這一題證明不了任何事
    ② 每一頁本來就都修好了      => 排除有沒有作用**這一題看不出來**
    ```
    ⇒ 所以這一題**同時**斷言：共用檔裡**有**守衛（前提成立）
      ＋ 每一頁自己也**有**守衛（新判準通過）。
    🔑 兩者一起，差額 0 才是「排除生效且每一頁都真的修了」。
    """
    shared_has = {}
    for name in SHARED_FILES:
        p = ROOT / "frontend" / "static" / name
        if p.is_file() and "_initDone" in p.read_text(
                encoding="utf-8", errors="replace"):
            shared_has[name] = True
    assert shared_has, (
        "七支共用檔裡**一個 `_initDone` 都沒有** ——\n"
        + "☠️ 那表示「排除共用檔」這個動作**現在沒有作用** ⇒\n"
          "   這一題與那道守門都證明不了任何事。\n"
        + "⚠️ 若 `(c)` 還沒做，這一題**本來就該紅**（它在等那件事）。")

    mod = _tool()
    fn = getattr(mod, "_guarded_if_shared_counted", None)
    assert callable(fn), (
        "工具沒有 `_guarded_if_shared_counted()` ——\n"
        + "📌 它是「舊判準下會算出幾頁已修」的量法，\n"
          "   而我要用它與新判準相減。**換了名字退回給我**。")

    rows = mod.scan()
    new_guarded = sum(1 for r in rows if r["guarded"])
    old_guarded = fn()
    assert old_guarded >= new_guarded, (
        "舊判準算出的已修（%d）比新判準（%d）**還少** —— 量法反了。"
        % (old_guarded, new_guarded))
    assert old_guarded - new_guarded == 0, (
        "舊判準會多把 %d 頁算成「已修」（舊 %d ／ 新 %d）——\n"
        % (old_guarded - new_guarded, old_guarded, new_guarded)
        + "☠️ 那幾頁**一行守衛都沒有**，而共用檔裡的 `_initDone`\n"
          "   讓它們看起來修好了。\n"
        + "🔑 差額非 0 = 有人新增了一頁而忘了加守衛。")


def test_al1_the_exclusion_still_works_on_an_unguarded_page(tmp_path,
                                                            monkeypatch):
    """⚙️ **正對照：用合成的「沒守衛的頁」證明排除仍然有作用。**

    ## 🔴 為什麼需要這一題：`(c)` 做完之後，前一題變成量不到東西

    ```
    (c) 之前  51 頁未修 => 不排除共用檔 => 那 51 頁全翻 => 差額 51  ✅ 量得到
    (c) 之後  **53 頁全部已修** => 排不排除**結果一樣** => 差額恆為 0
    ```
    ☠️ ⇒ 前一題（舊新判準相減）現在只剩**未來的回歸價值**
       （有人新增一頁忘了加守衛時它會非 0），
       **它證明不了「排除今天有作用」** —— 因為今天沒有任何一頁靠它。
    🔑 我實際跑過那個突變（把 `shared_js()` 變成空集合）⇒ **13 題全綠**
      ⇒ `A4` 在 `(c)` 之後**仍然是等價突變**，只是理由換了一個。

    ## ⇒ 用合成輸入把那個能力留住

    ```
    兩頁都 <script src> 同一支 fake_shared.js（=> 它是「共用檔」）
    那支 js 裡有 _initDone，而**兩頁自己都沒有**
    ⇒ 有排除：兩頁都「未修」 ／ 沒排除：兩頁都「已修」
    ```
    """
    mod = _tool()
    pages = tmp_path / "pages"
    pages.mkdir()
    shared_js = pages / "al1_fake_shared.js"
    shared_js.write_text(
        "function noop(){ const _initDone = false; return _initDone }\n",
        encoding="utf-8")
    for n in ("al1_p1.html", "al1_p2.html"):
        (pages / n).write_text(
            '<body x-data="demoPage()" x-init="init()">\n'
            '<script src="al1_fake_shared.js"></script>\n'
            "<script>function demoPage(){return{init(){}}}</script>\n"
            "</body>", encoding="utf-8")

    monkeypatch.setattr(mod, "PAGES_GLOB", str(pages / "*.html"))
    rows = mod.scan()
    assert len(rows) == 2, "合成的兩頁沒有被完整掃到：%r" % rows

    guarded = [r["page"] for r in rows if r["guarded"]]
    assert not guarded, (
        "兩頁自己**一行守衛都沒有**，而它們被判成已修：%r\n" % guarded
        + "☠️ `_initDone` 只寫在那支**共用** js 裡 ——\n"
          "   排除沒有生效 ⇒ 一份共用檔會讓整批翻綠（`§174c` 的引信）。")


def test_al1_the_two_populations_are_disjoint_and_named():
    """🔴 **`(a-2)`：兩個母體互斥，而聯集要列得出名字。**（`§174` ①）

    ```
    頁面母體  frontend/pages/*.html 裡有 x-data ＋ x-init="init()" 的頁
    共用母體  sidebar.js 裡的 2 個宣告
    ```
    ☠️ 合成一個算的話會多出 5 個**永遠修不好的待修**（那 5 支共用檔
       一個 `init()` store 都沒有）⇒ 而那正是會被人用
       「全部寫進排除清單」解決掉的形狀。
    🔑 **列名字不列數字**：數字對得上而名字錯了，是兩個桶互相抵銷。
    """
    mod = _tool()
    pages = {r["page"] for r in mod.scan()}
    shared = _shared_scan(mod)

    names = set()
    for row in shared:
        if isinstance(row, dict):
            names.add(row.get("store") or row.get("name") or row.get("page"))
        else:
            names.add(str(row))
    assert None not in names, (
        "共用母體的列說不出自己是誰：%r\n" % (shared,)
        + "⚠️ 每一列要有 `store`／`name`／`page` 其中一個 —— **退回給我**。")

    assert not (pages & names), (
        "兩個母體重疊了：%s\n" % sorted(pages & names)
        + "☠️ 同一個東西被算兩次 ⇒ 總量對得上而**修好一個會掉兩個**。")
    assert len(names) == SHARED_POPULATION, (
        "共用母體有 %d 個（%s），`§174` 實算是 %d。\n"
        % (len(names), sorted(names), SHARED_POPULATION)
        + "☠️ 掃到 **0** 個多半是去掃了 `%s` —— 那裡的**宣告**數是 0，\n"
          "   宣告在 `%s`。\n" % (DEF_FILE, DECL_FILE)
        + "⚠️ 多出來的表示又有人用注入的方式加了一個。")


def test_al1_the_a2_rewrite_is_behaviour_preserving():
    """🔴 **`(a-2)` 的驗收是「行為保持」，不是總量。**（`§174`）

    ```
    修改前  頁面母體 53 ／ 共用母體 2 ／ 報「已修」2
    做完後  **這三個數字不可以變** —— 它只改判定的歸屬，不改事實
    ☠️ 「已修」變多了 = 判定又變寬了，**不是修好了**
    ```
    ## 🔴 而 `已修 == 2` 那一格**到期了，我改成只增不減**

    ```
    (a-2) 與 (c) 之間  釘死 2  <= 唯一擋得住「判定變寬」的東西
    (c) 做完之後       已修 **53** => 釘死值紅了，**而那是正確的紅**
    ```
    ⇒ 改成 `>= ALREADY_GUARDED`：**只增不減**。
    ☠️ 它擋不到的那一側要講明白：**只增不減擋不住「判定又變寬」** ——
       `(a-2)` 之後那件事由
       `test_al1_excluding_the_shared_files_actually_changes_the_answer`
       與 `..._wrong_file_does_not_turn_it_green` 兩題接手。
    🔑 一個數字從「釘死」放寬成「只增不減」時，**要說出原本是誰在擋那一側**。
    """
    mod = _tool()
    rows = mod.scan()
    guarded = [r for r in rows if r["guarded"]]

    assert len(rows) == PAGE_POPULATION, (
        "頁面母體是 %d，`§174` 實算是 %d。\n" % (len(rows), PAGE_POPULATION)
        + "⚠️ 多了：有人新增了會跑兩遍的頁（更新 `PAGE_POPULATION`）。\n"
        + "☠️ 少了：多半是排除清單把**頁面自己的 js** 也排掉了 ——\n"
          "   `case-management.html` 的守衛就寫在它自己的 js 裡。")
    assert len(guarded) >= ALREADY_GUARDED, (
        "報「已修」%d 頁（%s），而 `(a-2)` 當時已經有 %d 頁 ——\n"
        % (len(guarded), [r["page"] for r in guarded], ALREADY_GUARDED)
        + "☠️ **變少了**：有人把已經加好的守衛拿掉了。")


#: `STATIC_GLOB` 現在是 `frontend/**/*.js`（遞迴、排除 `vendor`）⇒ 我的替身
#: 也要**兩個目錄都放**，否則替身比受測物窄，而窄的替身會讓題目變弱。
_FAKE_DIRS = ("static", "js")


def _fake_frontend(tmp_path, edits=None):
    """複製 `frontend/static/*.js` ＋ `frontend/js/*.js`，可順手改其中幾個檔。

    回傳可以直接餵給 `STATIC_GLOB` 的 pattern（`<tmp>/**/*.js`）。

    ⚠️ **整個範圍都要複製**：`scan_shared()` 數宣告、`_def_body()` 找定義，
       兩者掃同一個 `STATIC_GLOB` ⇒ 只放宣告檔的話定義會找不到，
       而那時 `guarded` 會全部變 `False` —— **看起來像缺陷，其實是我的裝置不全**。
    🔴 **更正留著**：我第一版只複製 `frontend/static`（當時 `STATIC_GLOB`
       就是那個目錄）。B 之後把範圍改成 `frontend/**`，理由是排除集合
       （`shared_js()` 從實際 `<script src>` 算）涵蓋兩個目錄，而共用母體只吃一個
       ⇒ **從 `frontend/js` 注入的宣告排除得到、而數不到**。
       ⇒ 我的替身跟著改，否則這幾題只驗得到其中一個目錄。
    """
    root = tmp_path / "fe"
    for d in _FAKE_DIRS:
        src_dir = ROOT / "frontend" / d
        out = root / d
        out.mkdir(parents=True)
        for p in sorted(src_dir.glob("*.js")):
            text = p.read_text(encoding="utf-8", errors="replace")
            if edits and p.name in edits:
                text = edits[p.name](text)
            (out / p.name).write_text(text, encoding="utf-8")
    return root


def test_al1_the_shared_population_is_computed_not_hardcoded(
        tmp_path, monkeypatch):
    """⚙️ **正對照：共用母體是「算出來的」，不是寫死 `sidebar.js` 的。**（B 補的缺口）

    ☠️ 我原本只驗「拿掉一個宣告 ⇒ 2 變 1」——
       **一個寫死「掃 `sidebar.js`」的實作也會過那一題**。
    ```
    把宣告加進 auth-guard.js（**不是** sidebar.js）  =>  共用母體 2 -> 3
    ```
    🔑 加進**別的檔**才分得出「掃全部共用檔」與「掃 sidebar.js」。
    """
    mod = _tool()
    if not hasattr(mod, SHARED_HOOK):
        pytest.fail("`%s` 不存在 —— `(a-2)` 未做。" % SHARED_HOOK)

    def add_decl(text):
        return (text + '\n// 合成宣告（測試用）\n'
                '// <div x-data="globalSearchStore()" x-init="init()"></div>\n')

    fake = _fake_frontend(tmp_path, {"auth-guard.js": add_decl})
    monkeypatch.setattr(mod, SHARED_HOOK, str(fake / "**" / "*.js"))
    rows = mod.scan_shared()

    assert len(rows) == SHARED_POPULATION + 1, (
        "把一個宣告加進 `auth-guard.js` 之後共用母體是 %d，應該是 %d。\n"
        % (len(rows), SHARED_POPULATION + 1)
        + "☠️ 數字沒動 ⇒ 掃描範圍**寫死在 `sidebar.js`** 了，\n"
          "   而條文要的是「凡共用檔都算」—— 下一個把宣告寫進別的共用檔的人\n"
          "   會得到一個看起來正常的 0。")
    assert any(r.get("where") == "auth-guard.js" for r in rows), (
        "新增的那一列沒有指出它在 `auth-guard.js`：%r\n" % (rows,)
        + "⚠️ `where` 是宣告點，`(c)` 的人要靠它才知道去哪裡看。")


def test_al1_a_declaration_in_the_other_js_folder_is_counted_too(
        tmp_path, monkeypatch):
    """⚙️ **正對照：共用母體要涵蓋 `frontend/js`，不是只有 `frontend/static`。**

    ```
    排除集合 shared_js()   從**實際 <script src>** 算 ⇒ 兩個目錄都涵蓋
    共用母體 舊 scan_shared() 只吃 frontend/static/*.js
    ⇒ 從 frontend/js 注入的宣告：**排除得到，而數不到**
    ```
    ☠️ 那是 `AL1` 原本那個缺陷**換一個目錄重演** ——
       兩邊都是**靠一份寫死的範圍在決定誰被看見**。
    ✅ 今天 `frontend/js` 的注入型宣告實算 **0**，所以現況不受影響
       ⇒ 這一題釘的是**範圍**，不是今天的數字。
    🔑 而「今天是 0」正是它需要合成輸入的理由：沒有真實案例可以當誘餌。
    """
    mod = _tool()
    if not hasattr(mod, SHARED_HOOK):
        pytest.fail("`%s` 不存在 —— `(a-2)` 未做。" % SHARED_HOOK)

    target = "voucher.js"
    assert (ROOT / "frontend" / "js" / target).is_file(), (
        "`frontend/js/%s` 不見了 —— 換一個檔當載體，**退回給我**。" % target)

    def add_decl(text):
        return (text + '\n// 合成宣告（測試用，放在 frontend/js 而不是 static）\n'
                '// <div x-data="globalSearchStore()" x-init="init()"></div>\n')

    fake = _fake_frontend(tmp_path, {target: add_decl})
    monkeypatch.setattr(mod, SHARED_HOOK, str(fake / "**" / "*.js"))
    rows = mod.scan_shared()

    assert len(rows) == SHARED_POPULATION + 1, (
        "宣告放在 `frontend/js/%s` 之後共用母體是 %d，應該是 %d。\n"
        % (target, len(rows), SHARED_POPULATION + 1)
        + "☠️ 掃描範圍只吃 `frontend/static` ⇒ 從 `frontend/js` 注入的宣告\n"
          "   **排除得到、而數不到** —— 那是 `AL1` 換一個目錄重演。")
    assert any(r.get("where") == target for r in rows), (
        "新增的那一列沒有指出它在 `%s`：%r" % (target, rows))


def test_al1_writing_the_guard_into_the_wrong_file_does_not_turn_it_green(
        tmp_path, monkeypatch):
    """🔴 **把 `_initDone` 寫進宣告檔（`sidebar.js`）不可以翻綠。**（`§174c` 的引信）

    ```
    舊寫法 guarded = "_initDone" in blob（含 sidebar.js 全文）
    ⇒ **改錯檔也會翻綠** —— 而兩個數字都對，事情沒做完
    ```
    ⚙️ 而這一格單獨看**分不出「擋住了」與「我的尺壞掉」**
       ⇒ 配一個反向：寫進**定義檔** `notif.js` 的 `notifStore()`
         ⇒ **只有它**要翻綠。
    🔑 這個配對是 B 跑出來的，收成常駐題的理由是「改錯檔」會一直發生。
    """
    mod = _tool()
    if not hasattr(mod, SHARED_HOOK):
        pytest.fail("`%s` 不存在 —— `(a-2)` 未做。" % SHARED_HOOK)

    # ① 寫進**宣告檔** —— 不可以翻綠
    wrong = _fake_frontend(tmp_path / "a", {
        "sidebar.js": lambda t: t + "\nconst _initDone = false  // 寫錯檔\n"})

    # 🔴 **這一題到期過一次，而我沒有預見它**（`AL1 (c)` 之後）
    #
    # 舊寫法：`assert not flipped`（斷言那個集合**為空**）
    # 而 `(c)` 做完之後兩個 store **本來就是綠的** ⇒ `flipped` 恆非空
    # ⇒ 它紅了，而紅的不是缺陷。
    #
    # 🔑 〈假綠燈〉的鄰居：**斷言某個集合為空的題，
    #    會在那個集合「合法地」變非空的那天失效。**
    # ☠️ 而我為 ①② 都寫了保存期限，**唯獨這一題沒有** ——
    #    三題是同一件事造成的，我只看到其中兩題。
    # ⇒ 改成**比較前後**：寫錯檔不可以讓「已修」的數量**變多**。
    base_green = len([r for r in mod.scan_shared() if r.get("guarded")])
    monkeypatch.setattr(mod, SHARED_HOOK, str(wrong / "**" / "*.js"))
    after_wrong = len([r for r in mod.scan_shared() if r.get("guarded")])
    assert after_wrong <= base_green, (
        "`_initDone` 寫進**宣告檔** `sidebar.js` 之後，已修從 %d 變成 %d ——\n"
        % (base_green, after_wrong)
        + "☠️ 那是 `§174c` 的引信：`guarded` 在讀宣告檔全文 ⇒ **改錯檔也算修好**。\n"
        + "🔑 `guarded` 要讀**定義點**（`defined_in` 那個檔的函式本體）。")

    # ② 反向：寫進**定義檔** —— 只有那一個要翻綠
    #
    # ⚠️ `(c)` 之後 `notif.js` 裡**兩個 store 都已經有守衛** ⇒ 直接加會全綠，
    #    那證明不了「只有被改的那一個會翻」。
    # ⇒ 先把整檔的 `_initDone` **拿掉**，再只加回 `notifStore()` 那一個。
    # ☠️ 換掉的名字**不可以含 `_initDone`**：工具查的是子字串，
    #    我第一版寫 `_initDoneREMOVED` ⇒ 它**仍然含有** `_initDone` ⇒ 兩個都還是綠的。
    #    🔑 又一次「判準是子字串比對」的坑，而這次踩的是我自己的替換。
    def _only_notif_store(t):
        t = t.replace("_initDone", "_guardWasHere")
        return t.replace(
            "function notifStore() {",
            "function notifStore() {\n  const _initDone = false", 1)

    right = _fake_frontend(tmp_path / "b", {"notif.js": _only_notif_store})
    monkeypatch.setattr(mod, SHARED_HOOK, str(right / "**" / "*.js"))
    rows2 = mod.scan_shared()
    green = {r.get("store") for r in rows2 if r.get("guarded")}
    assert green, (
        "`_initDone` 寫進**定義檔** `notif.js` 的 `notifStore()` 也沒有翻綠 ——\n"
        + "☠️ 那表示上面那一格的「沒翻綠」**證明不了任何事**："
          "可能是尺整個壞掉。\n"
        + "⚠️ 先修尺，再去看上面那一題的顏色。")
    assert green == {"notifStore()"}, (
        "翻綠的是 %s，而我只改了 `notifStore()` 的本體。\n" % sorted(green)
        + "☠️ 多翻的那些表示 `_def_body()` 切太長，把隔壁函式算進來了。")


def test_al1_removing_one_declaration_moves_only_the_shared_bucket(
        tmp_path, monkeypatch):
    """⚙️ **正對照：兩個桶各自會動，而且不互相牽動。**（`§174` ②）

    ```
    拿掉 sidebar.js:196 的 x-init
      => 共用母體 2 -> 1
      => 頁面母體 **仍然是 53**
    ```
    ☠️ 兩個桶若共用同一條判定，這一格會同時看到兩邊都變 ——
       而那表示「互斥」只是數字上的巧合。
    """
    mod = _tool()
    real = ROOT / DECL_FILE
    assert real.is_file(), "`%s` 不見了 —— **退回給我**。" % DECL_FILE

    src = real.read_text(encoding="utf-8", errors="replace")
    _mutated, n = re.subn(r'\s+x-init="init\(\)"', "", src, count=1)
    assert n == 1, (
        "在 `%s` 裡找不到可以拿掉的 `x-init=\"init()\"` ——\n" % DECL_FILE
        + "⚠️ 宣告被改寫了，這個正對照要重做，**退回給我**。")

    fake_static = _fake_frontend(tmp_path, {
        "sidebar.js": lambda t: re.subn(
            r'\s+x-init="init\(\)"', "", t, count=1)[0]})

    if not hasattr(mod, SHARED_HOOK):
        pytest.fail(
            "共用母體的掃描範圍沒有 `%s` 這個可替換的常數。\n" % SHARED_HOOK
            + "📌 有它我才能餵一份改過的 `sidebar.js` 進去做正對照。\n"
            + "⚠️ 沒有它，這個正對照只能對真檔做 —— 而那要改產品碼，我不做。\n"
            + "🔑 沒有正對照的話，共用母體那一題**回 2 與回 2 而其實壞掉**分不出來。\n"
            + "⚠️ 而 `%s` **只是正對照的可替換範圍，不是排除清單本身** ——\n"
              "   排除清單仍然要**算出來**（被 >1 頁 script-link 的 js），\n"
              "   不要因為有了這個常數就改成寫死。" % SHARED_HOOK)

    monkeypatch.setattr(mod, SHARED_HOOK, str(fake_static / "**" / "*.js"))
    shrunk = _shared_scan(mod)
    pages_after = mod.scan()

    assert len(shrunk) == SHARED_POPULATION - 1, (
        "拿掉一個宣告之後共用母體是 %d，應該是 %d。\n"
        % (len(shrunk), SHARED_POPULATION - 1)
        + "☠️ 它不會動 ⇒ 那個數字**不是從檔案算出來的**（多半寫死了）。")
    assert len(pages_after) == PAGE_POPULATION, (
        "動了共用檔，**頁面母體也跟著變了**（%d -> %d）。\n"
        % (PAGE_POPULATION, len(pages_after))
        + "☠️ 兩個桶共用同一條判定 ⇒ 「互斥」只是數字上的巧合。")


# ══════════════════════════════════════════════════════════════════════
# ② `(c)`：逐頁加守衛
# ══════════════════════════════════════════════════════════════════════

def test_al1_every_page_that_double_inits_has_a_guard():
    """🔴 **`(c)`：每一頁都要有 `_initDone`。**

    ```
    _initDone: false,
    async init() { if (this._initDone) return; this._initDone = true; … }
    ```
    ☠️ 沒修的後果**不是**「多打一次 API」那麼輕：第二次載入的回應晚一步抵達
       ⇒ **把使用者這段期間改過的欄位用舊值蓋回去** ⇒ 而畫面上什麼都沒發生。
    📌 判定**整個交給那支工具** —— 我不另外寫一把尺：
       兩把尺會分岔，而分岔的那天沒有人知道要信哪一把。
    """
    rows = _tool().scan()
    todo = [r for r in rows if not r["guarded"]]
    assert not todo, (
        "還有 %d 頁會跑兩遍（共 %d 頁）：\n" % (len(todo), len(rows))
        + "".join("    risk=%d  %-44s x-model=%d\n"
                  % (r["risk"], r["page"], r["editable"]) for r in todo[:15])
        + ("    …另外 %d 頁\n" % (len(todo) - 15) if len(todo) > 15 else "")
        + "📌 `risk` 只是「使用者可編輯面積」的**粗略代理** ——\n"
          "   拿來決定先後就好，**不要當成「低風險就不用修」**。\n"
        + "🔑 逐頁清單：`cd backend && python tools/check_double_init.py --todo`")


def test_al1_the_two_injected_stores_are_guarded_too():
    """🔴 **`(c)`：`sidebar.js` 注入的兩個 store 也要有守衛。**

    🔑 它們**不在任何 HTML 裡** ⇒ `PAGES_GLOB` 掃不到，
      而它們是注入的 ⇒ **每一頁都中**。53 頁是「某些頁」，這 2 個是「所有頁」。

    後果（我 05:43 實測）：
    ```
    globalSearchStore.init()  只讀 localStorage       => 跑兩次無害
    notifStore.init()         Promise.all 六支 fetch  => **每次開頁 12 個請求不是 6**
                              全部是 this.x = …       => 資料不會疊
    ```
    ⚠️ 而 `notif.js:94-100` 那一格我說不出它是安全的：
       `check -> await fetch -> set sessionStorage` 中間有 await，兩次 init 併發
       ⇒ **簽核橫幅可能疊兩個**。📌 我**沒有重現過**，只是讀出這個形狀。
    ⚠️ 守衛寫在 `%s`（**定義點**），不必碰 `%s`。
    """ % (DEF_FILE, DECL_FILE)
    p = ROOT / DEF_FILE
    assert p.is_file(), "`%s` 不見了 —— **退回給我**。" % DEF_FILE
    src = p.read_text(encoding="utf-8", errors="replace")

    for name in DEF_STORES:
        body = _function_body(src, name)
        assert body is not None, (
            "在 `%s` 裡找不到 `function %s()` —— **退回給我**。" % (DEF_FILE, name))
        assert "init(" in body, (
            "`%s()` 裡沒有 `init(` —— **量測裝置切錯範圍了**，\n" % name
            + "不要拿這個結果去判斷產品。")
        assert "_initDone" in body, (
            "`%s()` 沒有 `_initDone` 守衛。\n" % name
            + "☠️ 它是 `%s` **注入**的 ⇒ **每一頁都跑兩遍**，\n" % DECL_FILE
            + "   而 53 頁那份清單裡**沒有它**（工具只掃 `frontend/pages/*.html`）。")


def _function_body(src, name):
    """`function name() { … }` 到下一個頂層 `function` 為止。

    ⚠️ 行首比對的**近似**切法，不是 JS 解析器 ——
       上面那句 `assert "init(" in body` 就是在驗它沒有切歪。
    """
    m = re.search(r"^function\s+%s\s*\(" % re.escape(name), src, re.M)
    if not m:
        return None
    rest = src[m.end():]
    nxt = re.search(r"^function\s+\w+\s*\(", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def test_al1_my_function_slicer_does_not_run_past_the_next_function():
    """⚙️ **正對照：切函式本體的那把尺會不會切太長？**

    ☠️ 切太長 ⇒ 把**隔壁函式**的 `_initDone` 算進來 ⇒
       一個沒有守衛的 store 被判成有守衛（**假綠燈**）。
    🔑 〈探針與被測對象糾纏〉：這一格壞掉時紅燈會指向產品，而壞的是我的尺。
    """
    fake = ("function alpha() {\n  return { init() {} }\n}\n"
            "function beta() {\n  return { _initDone: false, init() {} }\n}\n")
    a = _function_body(fake, "alpha")
    assert a is not None and "_initDone" not in a, (
        "`alpha()` 的本體裡看到了 `beta()` 的 `_initDone`：%r\n" % a
        + "☠️ 尺切太長 ⇒ 沒有守衛的 store 會被判成有守衛。")
    b = _function_body(fake, "beta")
    assert b is not None and "_initDone" in b, (
        "`beta()` 裡找不到它自己的 `_initDone`：%r\n" % b
        + "☠️ 尺切太短 ⇒ 會去指控一個修好的檔。")
