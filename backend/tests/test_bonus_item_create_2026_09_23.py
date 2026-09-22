# -*- coding: utf-8 -*-
"""`POST /api/bonus/items` —— **空狀態唯一的出路，而它現在一打就 500。**

B 2026-09-23 找到，我複查成立（`routers/bonus.py:103`／`:119`）：
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
import pytest

ITEMS = "/api/bonus/items"

#: `§166`：走到端點才會出現的狀態碼。**500 不在裡面** —— 它不是「被擋」。
OK_CODES = (200, 400, 403)

#: `helpers/bonus.py` 的 `PERSON_SOURCES` 之一（`_case_people` 拿得到的那個）。
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
            + "🔑 `routers/bonus.py:103` 把 `_require_user()` 的回傳值丟掉了，\n"
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

def test_a_superadmin_can_actually_create_a_bonus_item(client, make_user):
    """🔴 **最高管理員按下「新增獎金項目」要真的建得起來。**

    ⚙️ 觀測點挑的是 `bonus_items` 那一列（**成功後才會被寫入**的下游），
       不是回應 —— 回應是它自己說的話。
    """
    u, hdr = _hdr(client, make_user, "bi_super")
    before = len(_items())

    _post(client, hdr, name="業務獎金", person_source=GOOD_SOURCE)

    rows = _items()
    assert len(rows) == before + 1, (
        "回應沒有報錯，而 `bonus_items` 沒有多一列（%d -> %d）。\n"
        % (before, len(rows))
        + "☠️ 「建立成功」是一句話，而畫面重整之後那個項目不在。")
    assert rows[-1]["name"] == "業務獎金"
    assert rows[-1]["person_source"] == GOOD_SOURCE
    assert rows[-1]["is_active"] == 1, "新建的項目預設要是啟用的。"


def test_the_creator_is_recorded_as_the_person_who_pressed_the_button(
        client, make_user):
    """🔴 **`created_by` 要是**按下去的那個人**。**

    ⚙️ 這一格是刻意挑的：`routers/bonus.py:119` 的 `_user_name(user)`
       **正是那個 `NameError` 所在的那一行** ——
    ```
    _require_user(…) 的回傳值丟掉  =>  user 未綁  =>  NameError
    ```
    ☠️ 而「修好它」有兩種寫法，只有一種是對的：
    ```
    ✅ user = _require_user(…)        => created_by 是真的人
    ❌ _user_name(None) / 寫死 ''     => **500 消失了，而稽核欄位是空的**
    ```
    🔑 釘 `created_by` 才分得出這兩種；只釘「回 200」分不出來。
    """
    u, hdr = _hdr(client, make_user, "bi_super2")
    _post(client, hdr, name="工程獎金", person_source=GOOD_SOURCE)

    row = _items()[-1]
    assert (row["created_by"] or "").strip(), (
        "`created_by` 是空的：%r\n" % row
        + "☠️ 500 消失了，而**稽核欄位是空的** —— 那是另一種修錯。")
    assert u in row["created_by"], (
        "`created_by` = %r，而按下去的人是 %r。\n" % (row["created_by"], u)
        + "⚠️ 若你們存的是顯示名稱而不是帳號，**退回給我**改這一題。")


def test_an_admin_cannot_create_bonus_items(client, make_user):
    """🔴 **`admin` 建不了項目** —— 而這正是空狀態要說的那件事。

    ```
    POST /api/bonus/items   require_superadmin=True   <= 只有 superadmin
    POST /api/bonus/awards  _is_manager               <= superadmin ＋ admin
    ```
    ☠️ ⇒ 公司裡只有 `admin` 在用的那天，他打開獎金頁看到空清單，
       **而他修不好它** ⇒ 空狀態必須說出「誰能解決」。
    ⚠️ 判準是「有沒有被擋」：401 與 403 都算。

    ## 🔴 而這一題**今天就是綠的**，那正是它的危險

    ```
    _require_user(…, require_superadmin=True)  先擋  -> 403
    _user_name(user)                           在它後面 -> NameError 根本跑不到
    ⇒ 權限題全綠，**而這支端點 100% 不可用**
    ```
    🔑 〈假綠燈〉的一個形狀：**正確的拒絕路徑遮住了壞掉的成功路徑**。
      403 是真的、`_require_user` 是對的 —— 而只驗 403 會讓人以為這支端點沒問題。
    ⇒ 所以上面那兩題（superadmin 建得成、`created_by` 是誰）**不可以省**。
    """
    _u, hdr = _hdr(client, make_user, "bi_admin", role="admin",
                   modules=["bonus"])
    before = len(_items())
    r = client.post(ITEMS, json={"name": "偷加的", "person_source": GOOD_SOURCE},
                    headers=hdr)
    if r.status_code >= 500:
        pytest.fail("回 %s —— 這一格量不到權限（先修 `NameError`）。" % r.status_code)
    assert r.status_code in (401, 403), (
        "`admin` 建得出獎金項目（回 %s）：%s" % (r.status_code, r.text[:200]))
    assert len(_items()) == before, (
        "被擋下來了，**而資料已經寫進去了** —— 拒絕的路徑上不可以留副作用。")


@pytest.mark.parametrize("body,why", [
    ({"person_source": GOOD_SOURCE}, "沒有名稱"),
    ({"name": "沒來源的項目"}, "沒有人員來源"),
    ({"name": "亂來的", "person_source": "quotations.owner"},
     "人員來源不在白名單（`owner` 欄位在 `quotations` 裡根本不存在）"),
])
def test_a_half_filled_item_is_refused_with_a_reason(client, make_user,
                                                     body, why):
    """🔴 **半填的項目要被擋，而且說得出是哪一格。**（%s）

    ☠️ 沒有人員來源的項目**永遠算不出發放對象** ⇒ 它會
       「從來沒有出現在任何一張獎金單上」——
       而〈沒有人會發現一個從來不出現的東西〉。
    ⚠️ 資料層的 `NOT NULL` 擋不住**空字串**，所以這一關是必要的另一半。

    ## 🔴 ⚠️ **這三題在端點壞掉的時候也是綠的**

    ```
    三種半填驗證都在 `_user_name(user)` 那一行**之前** return
    ⇒ NameError 根本跑不到 ⇒ 它們證明不了「這支端點可用」
    ```
    🔑 加上 403 那一題，**一支 100% 不可用的端點可以有 6 綠**。
    ⇒ 會從紅轉綠的只有「superadmin 建得成」與「`created_by` 是誰」那兩題。
    """
    # ⚠️ 固定名字是安全的：`client` 是 function-scoped，每一個參數化案例
    #    拿到的是**自己的一份資料庫**。
    _u, hdr = _hdr(client, make_user, "bi_bad")
    before = len(_items())
    r = client.post(ITEMS, json=body, headers=hdr)
    if r.status_code >= 500:
        pytest.fail("回 %s —— 這一格量不到驗證（先修 `NameError`）。" % r.status_code)
    assert r.status_code == 400, (
        "%s 的項目被接受了（回 %s）：%s" % (why, r.status_code, r.text[:200]))
    assert len(_items()) == before, "被擋下來了，而資料已經寫進去了。"


# ══════════════════════════════════════════════════════════════════════
# ④ 守門：同一個修法在 8 處是對的，在第 9 處變成 NameError
# ══════════════════════════════════════════════════════════════════════

#: 掃描範圍。
#: 📌 **依據**：A-2 只掃了 `routers/`（他自己標的射程）。我把 `helpers/` 與
#:    `main.py` 一起量過 —— **兩者今天都是 0** ⇒ 納進來零誤報、零成本，
#:    而它們同樣可能出現「只呼叫 `_require_user()` 當檢查、不取回傳值」的寫法。
_SCAN_DIRS = ("backend/routers", "backend/helpers")
_SCAN_FILES = ("backend/main.py",)

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
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    files = []
    for d in _SCAN_DIRS:
        files += sorted((root / d).glob("*.py"))
    files += [root / f for f in _SCAN_FILES]

    scanned = 0
    bad = []
    for p in files:
        if not p.is_file():
            continue
        scanned += 1
        for name, line in _unbound_user(
                p.read_text(encoding="utf-8", errors="replace")):
            bad.append("%s:%d  def %s" % (p.name, line, name))

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
          "**而那扇門又壞了沒有人知道**。")
    # ⚙️ 正對照：抹掉字串之後，`client.post` 這個**識別字鏈**要還在
    #    —— 抹過頭的話上面那句會無條件通過。
    assert "client . post" in code, (
        "抹掉字串與註解之後找不到 `client.post` ——\n"
        + "☠️ **量測裝置抹過頭了**：上面那句 `INSERT not in` 會無條件通過。")
    assert src.count("client.post(ITEMS") >= 1, (
        "本檔沒有任何一處真的打 `POST %s` ——\n" % ITEMS
        + "🔑 這一支存在的唯一理由就是走那條路。")
