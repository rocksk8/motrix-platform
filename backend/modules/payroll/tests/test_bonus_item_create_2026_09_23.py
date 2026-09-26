# -*- coding: utf-8 -*-
"""`POST /api/bonus/items` —— **空狀態唯一的出路，而它現在一打就 500。**

B 2026-09-23 找到，我複查成立（`modules/payroll/api/bonus.py:103`／`:119`）：
```
_require_user(authorization, require_superadmin=True)   <= **回傳值丟掉了**
…
_user_name(user)                                        <= `user` 從來沒被綁過
⇒ NameError -> 500
```

# ☠️ 為什麼整個 repo 沒有一條路徑碰得到它

```
$ grep -rn "api/bonus/items" backend/tests/
（0 筆）
```
種獎金項目的測試（含我的 `BN1`）一律直接 `INSERT INTO bonus_items` ——
**那個選擇本身沒問題**（種資料本來就該快），而它的副作用是
**這支端點在整個 repo 裡沒有任何一條路徑會執行到**。

# 🔑 而它撞的正是 `SPEC-BN1-PLAN §2` 花一整節設計的那個空狀態

```
bonus_items  正式庫 0 列 ／ demo 庫 0 列
產品碼裡 INSERT INTO bonus_items **只有這一處**
⇒ 每一個新客戶的第一天，獎金頁必定是空的
⇒ 空狀態說的唯一出路是「superadmin 到本頁新增獎金項目」
⇒ **而那扇門是壞的**
```
📌 規格花一整節設計空狀態的文案，而通往它的門一打就 500。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_a_half_filled_item_is_refused_with_a_reason、test_a_superadmin_can_actually_create_a_bonus_item、test_an_admin_cannot_create_bonus_items、test_the_creator_is_recorded_as_the_person_who_pressed_the_button
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import pytest

ITEMS = "/api/bonus/items"

#: `§166`：走到端點才會出現的狀態碼。**500 不在裡面** —— 它不是「被擋」。
OK_CODES = (200, 400, 403)

#: `modules/payroll/bonus.py` 的 `PERSON_SOURCES` 之一（`_case_people` 拿得到的那個）。
GOOD_SOURCE = "sales_person"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _post(client, hdr, **body):
    r = client.post(ITEMS, json=body, headers=hdr)
    if r.status_code >= 500:
        pytest.fail(
            "`POST %s` 回 **%s**：%s\n" % (ITEMS, r.status_code, r.text[:200])
            + "☠️ 它是空狀態**唯一的出路** —— 新客戶第一天按下「新增獎金項目」\n"
              "   看到的就是這個。\n"
            + "🔑 `modules/payroll/api/bonus.py:103` 把 `_require_user()` 的回傳值丟掉了，\n"
              "   而 `:119` 的 `_user_name(user)` 要用它 ⇒ `NameError`。")
    if r.status_code in (404, 405, 422):
        pytest.fail("`POST %s` 走不到（回 %s）。" % (ITEMS, r.status_code))
    assert r.status_code in OK_CODES, (
        "回 %s，不在 %s 裡：%s" % (r.status_code, list(OK_CODES), r.text[:200]))
    return r


def _items():
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_items ORDER BY id")]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════

#: 掃描範圍：`core.source_tree.router_files()`＋`logic_files()`＋`main.py`（見 `_scan_files()`）。
#: 〔主持派工 wip/b-scan-modules：原本寫死 `backend/routers`、`backend/helpers`——bonus.py 搬進
#:   `modules/payroll/api/` 之後，這一題**自己的對象**與全部模組端點都不在範圍，而 scanned>40 照過〕

#: 今天的基準。⚠️ 修好 `create_bonus_item` 之後它要變 **0**。
_UNBOUND_BASELINE = ("bonus.py", "create_bonus_item")


def _own_scope(fn):
    """只走這個 `def` 自己的節點，**不進巢狀 `def`／`lambda`／`class`**。

    🔑 那一步就是 A-2 的 3 → 1：另外 2 處是**巢狀閉包**讀外層綁好的 `user`。
    """
    import ast
    for node in fn.body:
        stack = [node]
        while stack:
            n = stack.pop()
            yield n
            for child in ast.iter_child_nodes(n):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.Lambda, ast.ClassDef)):
                    continue
                stack.append(child)


def _unbound_user(src):
    """回 `[(函式名, 行號)]` —— 頂層 `def` 讀了 `user` 而沒有在同一個 `def` 裡綁它。"""
    import ast
    out = []
    for fn in ast.parse(src).body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = fn.args
        bound = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
        for extra in (a.vararg, a.kwarg):
            if extra:
                bound.add(extra.arg)
        loaded = False
        for n in _own_scope(fn):
            if isinstance(n, ast.Name):
                if isinstance(n.ctx, ast.Store):
                    bound.add(n.id)
                elif isinstance(n.ctx, ast.Load) and n.id == "user":
                    loaded = True
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                bound.update(n.names)
        if loaded and "user" not in bound:
            out.append((fn.name, fn.lineno))
    return out


def test_the_unbound_user_detector_is_neither_too_wide_nor_too_narrow():
    """⚙️ **正對照：這把尺要做到 A-2 第三版的精度。**

    ```
    第一版 正則（寬）   **37** 處 —— 把 `def _is_manager(user)` 這種「user 是參數」全算進去
    第二版 AST         **3** 處 —— 排除參數表
    第三版 逐一打開看   **1** 處 —— 另 2 處是**巢狀閉包**，外層 def 有綁 user
    ```
    ☠️ 做不到第三版精度的話，它會**每天報 37 個假的** ——
       而一道每天誤報的守門，最省力的處置是把它關掉。
    """
    wrong = "def f(a):\n    return _name(user)\n"
    assert _unbound_user(wrong) == [("f", 1)], (
        "讀了一個沒綁過的 `user` 而尺沒看到：%r —— **太窄**。"
        % (_unbound_user(wrong),))

    as_param = "def _is_manager(user):\n    return user.role\n"
    assert _unbound_user(as_param) == [], (
        "`user` 是**參數**而被算成缺陷：%r —— **太寬**（第一版那 37 個）。"
        % (_unbound_user(as_param),))

    assigned = "def g(h):\n    user = _require(h)\n    return _name(user)\n"
    assert _unbound_user(assigned) == [], (
        "`user` 在同一個 def 裡綁過了而被算成缺陷：%r" % (_unbound_user(assigned),))

    closure = ("def outer(h):\n"
               "    user = _require(h)\n"
               "    def inner():\n"
               "        return _name(user)\n"
               "    return inner\n")
    assert _unbound_user(closure) == [], (
        "**巢狀閉包**讀外層綁好的 `user` 被算成缺陷：%r\n"
        % (_unbound_user(closure),)
        + "⚠️ 那是 A-2 第二版多出來的那 2 個。")


def _scan_files():
    from core import source_tree
    return (list(source_tree.router_files()) + list(source_tree.logic_files())
            + [source_tree.BACKEND / "main.py"])


def test_the_scan_covers_the_file_it_was_written_for():
    """⚙️ **正對照：它自己的對象（payroll 的 bonus.py）必須在掃描集合裡**（〈守門守的對象被搬走〉）。

    ☠️ `scanned > 40` 不是正對照：對象搬走之後檔數照樣過 40。
    📌 本檔在 `modules/payroll/tests/` ⇒ 跑得到這一題時 payroll 一定在。"""
    from core import source_tree
    rels = {source_tree.rel(p) for p in _scan_files()}
    assert "modules/payroll/api/bonus.py" in rels, (
        "bonus.py 不在掃描範圍 —— 這道守門守的對象被搬走了：%s" % sorted(r for r in rels if "bonus" in r))
    assert any(r.startswith("modules/") and r != "modules/payroll/api/bonus.py" for r in rels), \
        "其他模組的端點／邏輯檔一個都沒掃到"


def test_no_endpoint_uses_a_user_it_never_bound():
    """🔴 **頂層 `def` 讀 `user`，就必須在同一個 `def` 裡綁它。**

    ## 成因鏈（下一個人要知道為什麼有這道守門）

    ```
    A-2 報 token 外洩
      -> B 把 _tok(authorization) 換成 _user_name(user)
      -> **而這一支原本就沒有 `user = `**
         （它只呼叫 _require_user() 當檢查，不取回傳值）
    ⇒ **同一個修法在 8 處是對的，在第 9 處變成 NameError**
    ```
    🔑 ⇒ 要守的不是「這一行」，是**「一個對的修法會在某一處變成錯的」這件事**。
    ☠️ 而 `NameError` 只在**那條路真的被走到**時才炸 ——
       拒絕路徑先擋的話，它可以躺很久。

    ⚠️ **射程**：只認頂層 `def`、只認 `user` 這個名字、不進巢狀作用域。
       ⇒ 抓不到「巢狀 def 讀一個外層也沒綁的 `user`」。
    """
    from core import source_tree
    files = _scan_files()

    scanned = 0
    bad = []
    for p in files:
        if not p.is_file():
            continue
        scanned += 1
        for name, line in _unbound_user(
                p.read_text(encoding="utf-8", errors="replace")):
            bad.append("%s:%d  def %s" % (source_tree.rel(p), line, name))

    assert scanned > 40, (
        "只掃到 %d 個檔 —— **尺量不到東西**，下面的斷言會無條件通過。" % scanned)
    assert not bad, (
        "有 %d 個端點用了一個從來沒綁過的 `user`：\n" % len(bad)
        + "".join("    %s\n" % b for b in bad)
        + "🔑 修法是 `user = _require_user(...)`，**不是** `_user_name(None)` ——\n"
          "   後者會讓 500 消失而**稽核欄位變成空的**。\n"
        + "📌 基準（2026-09-23）：`%s` 的 `%s` 一處，其餘 0。"
        % _UNBOUND_BASELINE)


def test_this_file_is_the_only_path_that_exercises_the_endpoint():
    """⚙️ **為什麼這一支要存在：它是唯一走過那支端點的路。**

    ```
    種獎金項目的測試（含 BN1）一律直接 INSERT INTO bonus_items
    ⇒ 快，而**那支端點沒有任何一條路徑會執行到**
    ```
    🔑 這一題釘的是**本檔自己**：它必須真的打 HTTP，不可以哪天被改成
      直接 INSERT（那會讓上面每一題都還是綠的，而門又壞了沒有人知道）。
    ⚠️ 它是對**本檔原始碼**的檢查 —— 不掃別的檔，因為別的檔直接種資料是對的。

    ## 🔴 第一版我用字串比對，而它紅在自己的散文上（留著這一列）

    ```
    我寫   "INSERT INTO bonus_items" not in 原始碼
    而本檔的 docstring 裡就有這句話（在解釋為什麼別的檔那樣寫是對的）
    ⇒ 守門紅了，而**沒有任何一行程式碼在做那件事**
    ```
    ☠️ 那個誤報最省力的反應是**把那段解釋刪掉** ——
       〈防護的副作用落在盲側〉：加守門要問「它誤報時對方最省力的反應是什麼」。
    ⇒ 改成先用 `tokenize` 把字串與註解抹掉再比對。
    """
    import io
    import pathlib
    import tokenize

    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    code = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.STRING, tokenize.COMMENT):
            continue
        code.append(tok.string)
    code = " ".join(code)

    assert "INSERT" not in code.upper(), (
        "本檔的**程式碼**裡出現了 `INSERT` ——\n"
        + "☠️ 直接種資料會讓上面每一題都還是綠的，"
          "**而那扇門又壞了沒有人知道**。\n"
        + "🔑 **該做什麼**：若你是為了別的目的需要先有資料，\n"
          "   把那一題搬到別的檔（`_seed_item()` 直接 INSERT 在那裡是對的）——\n"
          "   **不要在本檔 INSERT，也不要刪掉這一題**。\n"
        + "📌 判準：測「這支端點對不對」⇒ 走 API（本檔）；\n"
          "   測「別的東西，需要先有資料」⇒ 直接 INSERT（別的檔）。")
    # ⚙️ 正對照：抹掉字串之後，`client.post` 這個**識別字鏈**要還在
    #    —— 抹過頭的話上面那句會無條件通過。
    assert "client . post" in code, (
        "抹掉字串與註解之後找不到 `client.post` ——\n"
        + "☠️ **量測裝置抹過頭了**：上面那句 `INSERT not in` 會無條件通過。")
    assert src.count("client.post(ITEMS") >= 1, (
        "本檔沒有任何一處真的打 `POST %s` ——\n" % ITEMS
        + "🔑 這一支存在的唯一理由就是走那條路。")
