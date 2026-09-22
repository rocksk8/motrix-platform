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


def _shared_scan(mod):
    """`(a-2)` 的共用母體。⚠️ 名字還沒定，四種都試 —— 定了**退回給我**。"""
    for name in ("scan_shared", "scan_injected", "shared_scan", "scan_static"):
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn()
    pytest.fail(
        "`check_double_init.py` 還沒有共用母體的掃描（`(a-2)` 未做）。\n"
        + "📌 `§174`：**兩個集合，不要合成一個**\n"
          "    排除清單 := 被 >1 頁 script-link 的 js（實算 7 檔，**要算不要手列**）\n"
          "    共用母體 := `sidebar.js` 裡的 2 個 `x-data` ＋ `x-init` **宣告**\n"
        + "⚠️ 函式叫什麼由你決定（我試 `scan_shared`／`scan_injected`／\n"
          "   `shared_scan`／`scan_static`）—— 用別的名字**退回給我**。\n"
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

def test_al1_the_shared_files_have_no_guard_today():
    """⚙️ **`(a-2)` 那個對照組成立的前提，要自己量不要問工具。**

    ```
    今天七支共用檔的 `_initDone` 命中數 = **0**
    ⇒ 把它們從 blob 排掉，「待修 51／已修 2」必須一個數字都不動
    ```
    ⚠️ 而這個前提**有保存期限**：`(c)` 一開跑，或有人去修那兩個 store，
       它就不再成立 ⇒ 那時這一題會紅，**而那是正確的紅**，
       它在說「行為保持的窗口關了」。
    🔑 我不去問工具，因為工具正是受測物。
    """
    hits = {}
    for name in SHARED_FILES:
        p = ROOT / "frontend" / "static" / name
        if not p.is_file():
            continue
        n = p.read_text(encoding="utf-8", errors="replace").count("_initDone")
        if n:
            hits[name] = n
    assert not hits, (
        "共用檔裡已經有 `_initDone` 了：%s\n" % hits
        + "📌 那表示 `(a-2)` 的**行為保持窗口關了** ——\n"
          "   `guarded = \"_initDone\" in blob` 會讓引用它的頁面全部翻成「已修」。\n"
        + "⚠️ 若這是 `(a-2)` **做完之後**的狀態（判準已經不看 blob 了），\n"
          "   **退回給我**把這一題換成「排除清單有沒有生效」。")


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
    ⚠️ 而 `已修 == 2` 這一格**會在 `(c)` 開跑的第一天紅**，那時要把它
       改成「只增不減」。📌 現在釘死值是刻意的：`(a-2)` 與 `(c)` 之間
       它是唯一擋得住「判定變寬」的東西。
    """
    mod = _tool()
    rows = mod.scan()
    guarded = [r for r in rows if r["guarded"]]

    assert len(rows) == PAGE_POPULATION, (
        "頁面母體是 %d，`§174` 實算是 %d。\n" % (len(rows), PAGE_POPULATION)
        + "⚠️ 多了：有人新增了會跑兩遍的頁（更新 `PAGE_POPULATION`）。\n"
        + "☠️ 少了：多半是排除清單把**頁面自己的 js** 也排掉了 ——\n"
          "   `case-management.html` 的守衛就寫在它自己的 js 裡。")
    assert len(guarded) == ALREADY_GUARDED, (
        "報「已修」%d 頁（%s），`(a-2)` 之前是 %d 頁。\n"
        % (len(guarded), [r["page"] for r in guarded], ALREADY_GUARDED)
        + "☠️ **變多了 = 判定又變寬了**，不是修好了 ——\n"
          "   多半是共用檔沒有被排出 blob（`_initDone` 一寫就全翻）。\n"
        + "✅ 若是 `(c)` 真的在逐頁加守衛，**退回給我**把這一格改成只增不減。")


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
    mutated, n = re.subn(r'\s+x-init="init\(\)"', "", src, count=1)
    assert n == 1, (
        "在 `%s` 裡找不到可以拿掉的 `x-init=\"init()\"` ——\n" % DECL_FILE
        + "⚠️ 宣告被改寫了，這個正對照要重做，**退回給我**。")

    fake_static = tmp_path / "static"
    fake_static.mkdir()
    (fake_static / "sidebar.js").write_text(mutated, encoding="utf-8")

    hook = None
    for name in ("STATIC_GLOB", "SHARED_GLOB", "DECL_GLOB"):
        if hasattr(mod, name):
            hook = name
            break
    if hook is None:
        pytest.fail(
            "共用母體的掃描範圍沒有可替換的鉤子。\n"
            + "📌 我需要一個模組層常數（`STATIC_GLOB`／`SHARED_GLOB`／`DECL_GLOB`\n"
              "   其中一個）才能餵一份改過的 `sidebar.js` 進去。\n"
            + "⚠️ 沒有它，這個正對照只能對真檔做 —— 而那要改產品碼，我不做。\n"
            + "🔑 沒有正對照的話，共用母體那一題**回 2 與回 2 而其實壞掉**分不出來。")

    monkeypatch.setattr(mod, hook, str(fake_static / "*.js"))
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
