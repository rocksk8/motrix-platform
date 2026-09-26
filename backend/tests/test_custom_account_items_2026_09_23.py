# -*- coding: utf-8 -*-
"""`CA1` · 自訂會計科目（延伸建立 ＋ 停用），`AI1` 併入。

```
POST  /api/account-items            延伸建立（code 由**後端**產生）
PATCH /api/account-items/{code}     只改 is_active
GET   /api/account-items            既有，回應要加自建總數
```

# 🔴 `§7③④` 是核心：**唯二會「用了一陣子之後」才爆的**

```
③ 停用 1111-2 之後再建 -> 下一個是 **1111-4**（停用的仍佔號 ⇒ 取最大不是數筆數）
④ 建到第十個          -> 下一個是 **1111-11**，不是 1111-10
```
☠️ ④ 的成因是**字串比大小**：`"1111-10" < "1111-9"` ⇒ 下一號又算出 10 ⇒ **撞號**。
🔑 而它在**第 10 個自建科目**那天才發作 —— 症狀是「順序怪怪的」，
   **而沒有人會報修一個順序**。

# ⚠️ 同一個坑在**既有程式碼**裡也有一份，而它今天是對的

```
account_items.py:76
    group.sort(key=lambda n: (n.get("level") or 0, n.get("code") or ""))
⇒ 同一層下 `1111-10` 會排在 `1111-2` **前面**
```
📌 它今天是對的 —— **因為一個自訂科目都沒有**。
⇒ ④ 拆成兩題：一題釘**取號**，一題釘**顯示順序**（A-2 建議）。

# ✅ 我替 A-2 補完他標「沒讀完」的那一格

```
account_items_statutory_no_update   BEFORE UPDATE ON account_items
                                    **WHEN OLD.source = 'statutory'**
account_items_referenced_code_no_update   BEFORE UPDATE **OF code**
```
⇒ **兩支都不會擋 custom 的 `is_active` UPDATE**：
   第一支按 `source` 篩、第二支只管 `code` 這一欄。
🔑 ⇒ `§7⑧`（停用 custom）在資料層是通的，**不需要改 TRIGGER**。

# ⚠️ 四項待裁我**沒有**寫題

（延伸可否再延伸／可否延伸範圍代號／停用後既有傳票要不要標／自訂可否改名）
☠️ 替未裁的決定寫題，會把它變成既成事實 —— 而那時它看起來像「規格本來就這樣」。
"""
import pytest

API = "/api/account-items"
ONE = "/api/account-items/%s"

#: `§166`：走到端點才會出現的狀態碼。
OK_CODES = (200, 400, 403)

#: `§1` 實查：`1111` 是 L4、parent `111`、**目前沒有子科目** ⇒ 延伸出來的是 **L5**。
PARENT = "1111"
CHILD_LEVEL = 5


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _reached(r, what):
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`%s` 走不到（回 %s）。\n" % (what, r.status_code)
            + "📌 `§166`：未實作端點在這個 repo 有三種臉 —— 404／405／**422**。")
    assert r.status_code in OK_CODES, (
        "`%s` 回 %s，不在 %s 裡：%s"
        % (what, r.status_code, list(OK_CODES), r.text[:200]))
    return r


def _extend(client, hdr, parent=PARENT, name="零用金－台中"):
    return _reached(
        client.post(API, headers=hdr,
                    json={"parent_code": parent, "name": name}),
        "POST /api/account-items")


def _set_active(client, hdr, code, active):
    return _reached(
        client.patch(ONE % code, headers=hdr, json={"is_active": active}),
        "PATCH /api/account-items/{code}")


def _row(code):
    import db
    conn = db.get_db()
    try:
        r = conn.execute(
            "SELECT * FROM account_items WHERE code = ?", (code,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _find_node(nodes, code):
    """在 `GET` 回應的巢狀 `tree` 裡找某個節點（深度優先）。

    🔴 **我第一版猜錯回應形狀**：以為是扁平的 `items` 清單，
       B 交出來的是巢狀 `tree`（`{"tree": [...], "custom_count": N, …}`）。
       ⇒ 找子項順序**不是重新排序後比對**，是直接讀那個節點的 `children`——
          那才是畫面實際會照著畫的順序，比自己排一次更貼近要驗的事。
    """
    for n in nodes or ():
        if n.get("code") == code:
            return n
        found = _find_node(n.get("children") or (), code)
        if found is not None:
            return found
    return None


def _codes_under(parent=PARENT):
    import db
    conn = db.get_db()
    try:
        return [r["code"] for r in conn.execute(
            "SELECT code FROM account_items WHERE parent_code = ?"
            " ORDER BY code", (parent,))]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ① 建得起來，而且形狀對
# ══════════════════════════════════════════════════════════════════════

def test_ca1_extending_a_code_creates_a_custom_child(client, make_user):
    """🔴 **`§7①`：延伸 `1111` ⇒ `1111-1`，L5，`source='custom'`。**

    ⚠️ **`code` 不由前端送** —— 後端產生（同 `voucher_no` 的理由：前端不發號）。
    ☠️ 讓前端送的話，兩個人同時建會撞號，而**撞號的那一筆會蓋掉另一筆的名字**。
    """
    _u, hdr = _hdr(client, make_user, "ca1_new")
    r = _extend(client, hdr)
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])

    row = _row("%s-1" % PARENT)
    assert row is not None, (
        "`%s-1` 沒有被建出來。`%s` 底下現有：%r"
        % (PARENT, PARENT, _codes_under()))
    assert row["parent_code"] == PARENT, "parent 是 %r" % row["parent_code"]
    assert int(row["level"]) == CHILD_LEVEL, (
        "level 是 %r，而 `%s` 是 L4 ⇒ 延伸出來的應該是 L%d。"
        % (row["level"], PARENT, CHILD_LEVEL))
    assert row["source"] == "custom", (
        "`source` 是 %r —— 自建的必須是 `custom`，\n" % row["source"]
        + "☠️ 標成 `statutory` 的話，那一列會被 TRIGGER 鎖住而**改不掉也停不掉**。")
    assert int(row["is_active"]) == 1, "新建的預設要啟用。"


def test_ca1_three_in_a_row_get_one_two_three(client, make_user):
    """🔴 **`§7②`：連續建三個 ⇒ `-1`／`-2`／`-3`。**"""
    _u, hdr = _hdr(client, make_user, "ca1_seq")
    for _ in range(3):
        assert _extend(client, hdr).status_code == 200
    assert _codes_under() == ["%s-1" % PARENT, "%s-2" % PARENT,
                              "%s-3" % PARENT], _codes_under()


# ══════════════════════════════════════════════════════════════════════
# ② 核心：取號
# ══════════════════════════════════════════════════════════════════════

def test_ca1_a_disabled_code_still_holds_its_number(client, make_user):
    """🔴🔴 **`§7③` 核心：停用 `1111-2` 之後再建 ⇒ 下一個是 `1111-4`。**

    ```
    取最大值 + 1   1111-3 是最大 => 下一個 1111-4   ✅
    數筆數 + 1     停用之後「還有 2 筆」=> 算出 1111-3  ☠️ **撞號**
    ```
    ## 🔴 撞號有**三種下場**，而它們取決於 `INSERT` 的寫法（A-2 更正）

    `account_items.code` 是 **TEXT PRIMARY KEY**（我複查 `PRAGMA` 的 `pk=1`
    ＋ `CREATE TABLE` 原文）⇒
    ```
    INSERT              -> IntegrityError   很吵，會被發現            ✅
    INSERT OR IGNORE    -> **靜默無事發生**  按了「建立」而什麼都沒有  ☠️
    INSERT OR REPLACE   -> **覆蓋**          舊傳票上的科目名變成別的  ☠️☠️
    ```
    🔴 而 repo 裡現成的那一句**就是 `OR IGNORE`**（`db.py:4297`，同一張表、
       欄位幾乎一樣、就在要改的那個檔案裡）⇒ **那是最可能被照抄的一句**。
    🔑 ⇒ 我第一版寫「會覆蓋」是**三種之一**，不是通則。
      這一題釘的應該是「**號碼不可以被重用**」——
      而三種下場**都會讓下面的筆數與名字對不上**，所以一組斷言擋得住全部三種。
    """
    _u, hdr = _hdr(client, make_user, "ca1_hold")
    for i in range(3):
        assert _extend(client, hdr, name="原本的第 %d 個" % (i + 1)).status_code == 200
    assert _set_active(client, hdr, "%s-2" % PARENT, False).status_code == 200
    assert int(_row("%s-2" % PARENT)["is_active"]) == 0, "停用沒有落地。"

    assert _extend(client, hdr, name="新加的").status_code == 200
    got = _codes_under()
    assert "%s-4" % PARENT in got, (
        "停用 `%s-2` 之後再建，拿到的是 %r —— 應該有 `%s-4`。\n"
        % (PARENT, got, PARENT)
        + "☠️ 多半是**數筆數**而不是**取最大值**：停用的那一筆仍然佔號。\n"
        + "🔑 而撞號有三種下場（取決於 `INSERT` 的寫法），"
          "**三種都不會給你一個看得懂的錯誤**。")
    assert len([c for c in got if c.startswith(PARENT + "-")]) == 4, (
        "`%s` 底下有 %d 個自建科目，應該是 4：%r\n"
        % (PARENT, len([c for c in got if c.startswith(PARENT + "-")]), got)
        + "☠️ 少一個 ⇒ `INSERT OR IGNORE`（**靜默無事發生**）"
          "或 `OR REPLACE`（**覆蓋**）。")
    # ⚙️ 而「名字」是分辨 `OR REPLACE` 的那一格：它會把 `-3` 的名字換成新的。
    assert _row("%s-3" % PARENT)["name"] == "原本的第 3 個", (
        "`%s-3` 的名字變成 %r 了 ——\n" % (PARENT, _row("%s-3" % PARENT)["name"])
        + "☠️ 那是 `INSERT OR REPLACE`：新的那一筆**覆蓋掉舊的**，\n"
          "   而它**可能已經被傳票引用過** ⇒ 舊傳票上的科目名稱變成別的東西。")


def test_ca1_the_insert_must_not_paper_over_a_collision():
    """🔴 **取號那一段不可以用 `OR IGNORE`／`OR REPLACE`／`ON CONFLICT DO UPDATE`。**

    ```
    code 是 TEXT PRIMARY KEY（我複查 pk=1）⇒ 撞號的下場**取決於寫法**：
      INSERT              -> UNIQUE constraint failed  很吵，會被發現       ✅
      INSERT OR IGNORE    -> **靜默無事發生**  按了建立而什麼都沒有          ☠️
      INSERT OR REPLACE   -> **覆蓋**          舊傳票上的科目名變成別的東西  ☠️☠️
    ```
    🔴 而 repo 裡現成的那一句**就是 `OR IGNORE`**（`db.py:4297`，載入法定科目用的）
    ⇒ **同一張表、欄位幾乎一樣** ⇒ 那是最可能被照抄的一句。
    🔑 ⇒ 這一題守的是**後果**，不是取號的正確性：
      取號寫錯時，我要它**吵**，不要它安靜。
    ⚠️ 只掃 `routers/account_items.py` —— `db.py` 那一句是**對的**
       （載入 547 筆法定科目時，重跑 migration 不該炸）。
    """
    import pathlib
    import re

    p = (pathlib.Path(__file__).resolve().parents[1]
         / "modules" / "accounting" / "api" / "account_items.py")   # M06 搬遷（2026-09-26）
    assert p.is_file(), "`modules/accounting/api/account_items.py` 不見了 —— **退回給我**。"
    src = p.read_text(encoding="utf-8", errors="replace")

    # ⚙️ 先剝註解與字串外的說明？—— 不剝：SQL **本來就寫在字串裡**。
    #    ⇒ 改成只認「INSERT … INTO account_items」那一段的寫法。
    bad = re.findall(
        r"INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO\s+account_items", src, re.I)
    assert not bad, (
        "`modules/accounting/api/account_items.py` 用了 `INSERT OR %s`：\n" % bad[0]
        + "☠️ `OR IGNORE` ⇒ 使用者按了「建立」而**什麼都沒發生**；\n"
          "   `OR REPLACE` ⇒ **覆蓋掉舊的那一列**，而它可能已被傳票引用。\n"
        + "🔑 取號寫錯時我要它**吵** —— 撞號要炸出來，不要被抹平。\n"
        + "📌 `db.py:4297` 那一句 `OR IGNORE` 是**對的**（載入法定科目、"
          "重跑 migration 不該炸）⇒ 不要照抄到這裡。")
    assert not re.search(r"ON\s+CONFLICT[\s\S]{0,60}DO\s+UPDATE", src, re.I), (
        "用了 `ON CONFLICT … DO UPDATE` —— 那是 `OR REPLACE` 的另一種寫法。")


def test_ca1_the_collision_detector_would_notice_the_bad_shape():
    """⚙️ **正對照：上面那把尺認得出那三種寫法嗎？**

    ☠️ 認不出來的話，上一題是**一句永遠成立的空話** ——
       而它看起來像一道守門。
    """
    import re

    good = 'conn.execute("INSERT INTO account_items (code, level) VALUES (?,?)")'
    for bad in ('INSERT OR IGNORE INTO account_items (code) VALUES (?)',
                'insert or replace into account_items(code) values (?)',
                'INSERT INTO account_items ... ON CONFLICT(code) DO UPDATE SET'):
        hit = re.search(
            r"INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO\s+account_items", bad,
            re.I) or re.search(r"ON\s+CONFLICT[\s\S]{0,60}DO\s+UPDATE", bad,
                               re.I)
        assert hit, "沒認出壞寫法：%r —— **太窄**。" % bad
    assert not re.search(
        r"INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO\s+account_items", good,
        re.I), "乾淨的 INSERT 被判成壞的 —— **太寬**。"


def test_ca1_the_tenth_one_is_followed_by_eleven_not_ten(client, make_user):
    """🔴🔴 **`§7④` 核心：建到第十個 ⇒ 下一個是 `-11`，不是 `-10`。**

    ```
    字串比大小   "1111-10" < "1111-9"  => 最大仍是 -9 => 下一號又算出 **10**
    整數比大小   max(1..10) = 10       => 下一號 **11**   ✅
    ```
    ☠️ 它在**第 10 個自建科目**那天才發作 —— 而那可能是幾個月後。
    🔑 而症狀是「順序怪怪的」與「這個代號怎麼有兩個」，
       **沒有人會把它連到取號那一行**。
    """
    _u, hdr = _hdr(client, make_user, "ca1_ten")
    for i in range(10):
        assert _extend(client, hdr, name="第 %d 個" % (i + 1)).status_code == 200
    got = _codes_under()
    assert "%s-10" % PARENT in got, "前十個就不對：%r" % got

    assert _extend(client, hdr, name="第 11 個").status_code == 200
    after = _codes_under()
    assert "%s-11" % PARENT in after, (
        "建到第十個之後再建，拿到的是 %r\n" % sorted(set(after) - set(got))
        + "☠️ 尾碼用**字串**比大小：`\"%s-10\" < \"%s-9\"` ⇒ 下一號又算出 10。\n"
        % (PARENT, PARENT)
        + "🔑 ⇒ 用**整數**比：`max(int(尾碼))` + 1。")
    assert len([c for c in after if c.startswith(PARENT + "-")]) == 11, (
        "總數是 %d 不是 11 —— **撞號把其中一筆蓋掉了**。"
        % len([c for c in after if c.startswith(PARENT + "-")]))


def test_ca1_extending_a_parent_with_range_siblings_starts_at_one(client,
                                                                  make_user):
    """🔴🔴 **`§7③` 的第二種撞法：`11-12` 是範圍代號，`1111-1` 是延伸代號 ——
    兩者形狀相同（`XXXX-N`）而意義不同，取號不可以把前者算進去。**

    ## 🔴 這不是假設，是實測到的資料形狀（2026-09-23）

    ```
    parent_code='1' 底下既有兩筆**官方範圍代號**：'11-12'／'13-15'
    ⇒ 若「取號」天真地對 parent 底下每一筆子項都做
      code.split('-')[-1] 去抓「既有延伸號」，
      會把 '11-12' 的 '12'、'13-15' 的 '15' 當成延伸號，
      算出 max=15 ⇒ 下一個延伸變成 **'1-16'**，
      而正確答案是 **'1-1'**（一筆自訂延伸都還沒有）。
    ```
    ☠️ 這一族的坑（`§7③④`）在**用了一陣子之後才爆**；這一種更早——
       **第一次**對一個帶有範圍代號子項的節點按「延伸」就會錯，
       而 `PARENT="1111"` 沒有範圍代號子項，測不出這個形狀。
    🔑 兩題（`PARENT` 版與這一題）合起來才擋得住兩種取號寫法：
       「數/解析全部子項」與「只看 `source='custom'` 的子項」。
    """
    _u, hdr = _hdr(client, make_user, "ca1_range_collision")

    # ⚙️ 前置：先證明這個陷阱今天真的存在，不是我編出來的資料。
    before = _codes_under(parent="1")
    assert set(before) >= {"11-12", "13-15"}, (
        "前置不對：`parent_code='1'` 底下沒有既有的範圍代號子項，"
        "這一題撞不到那個陷阱：%r" % before)

    r = _extend(client, hdr, parent="1", name="測試範圍延伸")
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])

    new_codes = [c for c in _codes_under(parent="1")
                if c not in ("11-12", "13-15")]
    assert new_codes == ["1-1"], (
        "延伸 `parent='1'` 拿到 %r，預期只有 `1-1`。\n" % new_codes
        + "☠️ 若拿到的是別的數字（例如 `1-16`）——\n"
          "   取號邏輯把既有的**範圍代號**（`11-12`／`13-15`）的尾碼\n"
          "   誤認成既有的**延伸代號**尾碼去算 max，兩者形狀一樣、意義不同。")
    row = _row("1-1")
    assert row is not None and int(row["level"]) == 2, (
        "`1-1` 的 level 是 %r，`1` 是 L1 ⇒ 延伸出來的應該是 L2。"
        % (row["level"] if row else None))


def test_ca1_the_tree_sorts_ten_after_nine(client, make_user):
    """🔴 **`§7④` 的另一半：畫面上 `-10` 要排在 `-9` **後面**。**

    ```
    account_items.py:76
        group.sort(key=lambda n: (n.get("level") or 0, n.get("code") or ""))
    ⇒ 同一層下 `1111-10` 會排在 `1111-2` **前面**
    ```
    📌 **那一行今天是對的** —— 因為一個自訂科目都沒有。
    ☠️ 它會在第 10 個自建科目那天才錯，而症狀是「順序怪怪的」——
       **沒有人會報修一個順序**，而它會一直錯下去。
    ⚙️ 這一題與取號那一題是**兩個地方**：取號對了而排序沒改，畫面照樣是亂的。
    """
    _u, hdr = _hdr(client, make_user, "ca1_sort")
    for i in range(10):
        assert _extend(client, hdr, name="第 %d 個" % (i + 1)).status_code == 200

    r = _reached(client.get(API, headers=hdr), "GET /api/account-items")
    assert r.status_code == 200, r.text[:200]
    payload = r.json()
    tree = payload.get("tree") if isinstance(payload, dict) else None
    assert tree, "`GET %s` 沒有回 `tree`：現有鍵 %r" % (
        API, sorted(payload) if isinstance(payload, dict) else type(payload))

    node = _find_node(tree, PARENT)
    assert node is not None, "`tree` 裡找不到 `%s` 這個節點。" % PARENT
    order = [c.get("code") for c in node.get("children") or ()]
    assert len(order) == 10, "`%s` 底下只有 %d 個子項：%r" % (
        PARENT, len(order), order)
    assert order.index("%s-10" % PARENT) > order.index("%s-9" % PARENT), (
        "`%s-10` 排在 `%s-9` **前面**：%r\n" % (PARENT, PARENT, order)
        + "☠️ `account_items.py:76` 用 `code` 字串排序 ——\n"
          "   而它**今天是對的**，因為一個自訂科目都沒有。\n"
        + "🔑 ⇒ 排序鍵要把尾碼當**整數**。")


# ══════════════════════════════════════════════════════════════════════
# ③ 要擋的
# ══════════════════════════════════════════════════════════════════════

def test_ca1_extending_a_code_that_does_not_exist_says_which_one(client,
                                                                 make_user):
    """🔴 **`§7⑤`：延伸一個不存在的代號 ⇒ 400，而且說出是哪一個。**

    ⚠️ 只回 400 不夠：使用者一次可能試好幾個，**說不出是哪一個等於要他自己猜**。
    """
    _u, hdr = _hdr(client, make_user, "ca1_ghost")
    r = _extend(client, hdr, parent="9999999")
    assert r.status_code == 400, (
        "延伸一個不存在的代號被接受了（回 %s）：%s" % (r.status_code, r.text[:200]))
    assert "9999999" in r.text, (
        "訊息沒說出是哪一個代號：%s" % r.text[:200])


def test_ca1_extending_a_disabled_code_is_refused(client, make_user):
    """🔴 **`§7⑥`：延伸一個已停用的科目 ⇒ 400。**

    ☠️ 允許的話：一棵**已經停用**的子樹底下長出新科目 ——
       它在下拉選單裡看不到（父層停用了），**而傳票可以引用它**。
    """
    _u, hdr = _hdr(client, make_user, "ca1_dead")
    assert _extend(client, hdr).status_code == 200
    child = "%s-1" % PARENT
    assert _set_active(client, hdr, child, False).status_code == 200

    r = _extend(client, hdr, parent=child)
    assert r.status_code == 400, (
        "在一個**已停用**的科目底下建出了新科目（回 %s）：%s\n"
        % (r.status_code, r.text[:200])
        + "☠️ 它在下拉選單裡看不到（父層停用了），**而傳票可以引用它**。")


def test_ca1_a_statutory_item_cannot_be_disabled_and_says_so_readably(
        client, make_user):
    """🔴 **`§7⑦`：停用法定科目要被拒絕，而訊息要看得懂。**

    ```
    account_items_statutory_no_update  BEFORE UPDATE … WHEN OLD.source = 'statutory'
    ```
    ⚠️ 判準有**兩格**：
    ```
    ① 被擋下來（400／403）
    ② 訊息不可以是 `sqlite3.IntegrityError` 直接冒出來
    ```
    ☠️ 少了 ②：使用者看到一串英文例外，**而那讀起來像系統壞了**，
       他會去報修一個正確的行為。
    """
    _u, hdr = _hdr(client, make_user, "ca1_statutory")
    r = client.patch(ONE % PARENT, headers=hdr, json={"is_active": False})
    if r.status_code in (404, 405, 422):
        pytest.fail("端點還不存在（回 %s）。" % r.status_code)
    assert r.status_code in (400, 403), (
        "法定科目 `%s` 被停用了（回 %s）：%s" % (PARENT, r.status_code, r.text[:200]))
    assert "IntegrityError" not in r.text and "sqlite3" not in r.text, (
        "訊息是資料層的例外直接冒出來：%s\n" % r.text[:200]
        + "☠️ 使用者看到一串英文例外，**那讀起來像系統壞了** ——\n"
          "   他會去報修一個正確的行為。")
    assert int(_row(PARENT)["is_active"]) == 1, (
        "被擋下來了，**而它已經被停用了** —— 拒絕的路徑上不可以留副作用。")


def test_ca1_only_a_superadmin_may_create_or_disable(client, make_user):
    """🔴 **`§7⑨`：非 superadmin ⇒ 403（不是 500）。**

    ⚠️ 會計科目是**全公司共用的基礎資料** ⇒ 與 `POST /api/bonus/items` 同一級。
    ⚙️ 兩個動作都要擋：只擋建立而不擋停用的話，`admin` 停得掉一整棵子樹。
    """
    _u0, owner = _hdr(client, make_user, "ca1_owner")
    assert _extend(client, owner).status_code == 200
    child = "%s-1" % PARENT

    _u1, admin = _hdr(client, make_user, "ca1_admin", role="admin",
                      modules=["accounting"])
    for what, r in (("建立", client.post(API, headers=admin,
                                       json={"parent_code": PARENT,
                                             "name": "偷加的"})),
                    ("停用", client.patch(ONE % child, headers=admin,
                                        json={"is_active": False}))):
        if r.status_code in (404, 405, 422):
            pytest.fail("端點還不存在（回 %s）—— 量不到權限。" % r.status_code)
        assert r.status_code in (401, 403), (
            "`admin` %s得了會計科目（回 %s）：%s"
            % (what, r.status_code, r.text[:200]))
    assert int(_row(child)["is_active"]) == 1, "被擋下來了，而它已經被停用了。"


# ══════════════════════════════════════════════════════════════════════
# ④ `AI1`：停用要真的讓它用不了
# ══════════════════════════════════════════════════════════════════════

def test_ca1_disabling_a_custom_code_makes_it_unusable(client, make_user):
    """🔴🔴 **`§7⑧`（`AI1`）：停用之後 `validate_account_code()` 要說它已停用。**

    📌 **走產品路徑** —— 用 `PATCH` 停用，不是 raw SQL。
    ```
    現況：那兩條「已停用」分支在正式環境**到不了**
          —— 因為沒有任何路徑能把 is_active 設成 0
    ```
    ⇒ 這一題做出來之後，`test_t100_config_complete_2026_09_23.py:249`
      那個 `INSERT … is_active=0` **可以刪掉**：
      🔑 **不是加一題，是讓一題變成不必要** ——
      那一筆 fixture 讓一條到不了的分支看起來是活的。

    ✅ 而資料層是通的（我讀完了 A-2 標「沒讀完」的那兩支 TRIGGER）：
    ```
    account_items_statutory_no_update       WHEN OLD.source = 'statutory'  <= 按 source 篩
    account_items_referenced_code_no_update BEFORE UPDATE **OF code**      <= 只管 code 欄
    ```
    ⇒ **兩支都不擋 custom 的 `is_active` UPDATE** ⇒ 不需要改 TRIGGER。
    """
    _u, hdr = _hdr(client, make_user, "ca1_ai1")
    assert _extend(client, hdr).status_code == 200
    child = "%s-1" % PARENT

    from modules.accounting.api.accounting_export import validate_account_code
    import db

    conn = db.get_db()
    try:
        ok_before = validate_account_code(conn, child)
    finally:
        conn.close()
    assert ok_before[0] if isinstance(ok_before, tuple) else ok_before, (
        "剛建好就說它不能用：%r —— **前置失敗**，不是停用那一段的問題。"
        % (ok_before,))

    assert _set_active(client, hdr, child, False).status_code == 200

    conn = db.get_db()
    try:
        after = validate_account_code(conn, child)
    finally:
        conn.close()
    ok, msg = after if isinstance(after, tuple) else (after, "")
    assert not ok, (
        "停用之後 `validate_account_code()` 仍然說它可以用：%r\n" % (after,)
        + "☠️ 那表示停用**只改了一個欄位而沒有任何人在看它** ——\n"
          "   使用者以為停掉了，而傳票照樣選得到。")
    assert "停用" in str(msg), (
        "訊息說不出是「已停用」：%r\n" % (msg,)
        + "⚠️ 它要與「找不到」分得開 —— **兩者的下一步不同**："
          "一個是去啟用，一個是去新增。")


def test_ca1_re_enabling_makes_it_usable_again_without_reusing_its_number(
        client, make_user):
    """🔴🔴 **`§276` 同族：`PATCH is_active` 雙向都收 ⇒「停用後再啟用」是一個
    可達狀態，而 12 題原本沒有一題走到它。**

    ```
    PATCH /api/account-items/{code} {"is_active": bool}   <= 不是專用的 /disable
    ⇒ 傳 true 把它翻回來，是這支端點自己的形狀允許的
    ```
    ⚙️ 兩件要一起釘（A 裁：補的時候順便決定「重新啟用之後，它原本佔的號
    還在嗎」）：
    ```
    (a) 重新啟用之後 `validate_account_code()` 要說它可以用了
        —— 不是「停用是單向的」，是**啟用要真的把它接回來**
    (b) 號碼**不會被重用**：啟用之後再延伸，拿到的是下一個新號，
        不是把 `1111-2` 這個號碼再發一次給別的科目
        🔑 「停用仍佔號」與「啟用仍佔號」是同一個承諾的兩面 ——
           號碼一旦發出去就不重用，跟這個科目現在是不是能用無關。
    """
    _u, hdr = _hdr(client, make_user, "ca1_reenable")
    for i in range(3):
        assert _extend(client, hdr, name="第 %d 個" % (i + 1)).status_code == 200
    target = "%s-2" % PARENT

    from modules.accounting.api.accounting_export import validate_account_code
    import db

    assert _set_active(client, hdr, target, False).status_code == 200
    conn = db.get_db()
    try:
        disabled = validate_account_code(conn, target)
    finally:
        conn.close()
    ok_disabled = disabled[0] if isinstance(disabled, tuple) else disabled
    assert not ok_disabled, (
        "前置不對：停用之後 `validate_account_code()` 仍說可以用 —— "
        "先看 `test_ca1_disabling_a_custom_code_makes_it_unusable`。")

    assert _set_active(client, hdr, target, True).status_code == 200
    assert int(_row(target)["is_active"]) == 1, "重新啟用沒有落地。"

    conn = db.get_db()
    try:
        reenabled = validate_account_code(conn, target)
    finally:
        conn.close()
    ok, msg = reenabled if isinstance(reenabled, tuple) else (reenabled, "")
    assert ok, (
        "重新啟用之後，`validate_account_code()` 仍然說它不能用：%r\n"
        % (reenabled,)
        + "☠️ **啟用只改了一個欄位而沒有任何人在看它** ——\n"
          "   使用者以為重新開放了，傳票上還是選不到它，\n"
          "   而畫面上『已啟用』看起來一切正常。")

    assert _extend(client, hdr, name="第四個").status_code == 200
    got = _codes_under()
    assert "%s-4" % PARENT in got, (
        "啟用 `%s` 之後再延伸，拿到的是 %r —— 應該有 `%s-4`。\n"
        % (target, got, PARENT)
        + "☠️ 若拿到的是 `%s`（號碼被重用），\n" % target
        + "   兩個不同的科目共用同一個代號，"
          "傳票上的科目名稱會**看是哪一次查詢**而不同。")
    assert len([c for c in got if c.startswith(PARENT + "-")]) == 4, (
        "`%s` 底下有 %d 個自建科目，應該是 4：%r"
        % (PARENT, len([c for c in got if c.startswith(PARENT + "-")]), got))


def test_ca1_the_list_says_how_many_are_custom(client, make_user):
    """🔴 **`§7⑩`：`GET` 的回應要帶自建總數，而它要等於實際筆數。**

    ⚙️ 兩個方向都釘：建之前是 0、建三個之後是 3 ——
    ☠️ 只釘一個方向的話，一個「永遠回 0」或「回全部筆數」的實作也會綠。
    """
    _u, hdr = _hdr(client, make_user, "ca1_count")

    def _count():
        r = _reached(client.get(API, headers=hdr), "GET /api/account-items")
        assert r.status_code == 200, r.text[:200]
        p = r.json()
        for k in ("custom_count", "customCount", "custom_total"):
            if isinstance(p, dict) and k in p:
                return p[k]
        # 🔴 我複查 CA1 時發現：既有回應**已經有** `by_source`
        #    （`routers/account_items.py:138-144`，`{source: 筆數}`），
        #    今天就長 `{"statutory": 547}`。少了 `custom` 那把 key 的話，
        #    `by_source.get("custom", 0)` 天然就是 0 —— 與「一個都還沒建」
        #    分不出來，所以要收在這裡而不是直接判 200。
        by_source = p.get("by_source") if isinstance(p, dict) else None
        if isinstance(by_source, dict):
            return by_source.get("custom", 0)
        pytest.fail(
            "`GET %s` 的回應沒有自建總數（找過 `custom_count`／"
            "`customCount`／`custom_total`／`by_source.custom`）。現有鍵：%s\n"
            % (API, sorted(p) if isinstance(p, dict) else type(p))
            + "📌 `§6`：使用者原話要求「頁面須說明自建總數有多少」。")

    assert _count() == 0, "一個都還沒建，而它說有 %r 個。" % _count()
    for _ in range(3):
        assert _extend(client, hdr).status_code == 200
    assert _count() == 3, (
        "建了三個，而它說有 %r 個 ——\n" % _count()
        + "⚠️ 回全部筆數（含 547 筆法定）的話，這個數字對使用者沒有意義。")


# ══════════════════════════════════════════════════════════════════════
# ⑤ `AC1`：畫面那一半
# ══════════════════════════════════════════════════════════════════════

def test_ca1_the_page_has_both_write_actions():
    """🔴 **`§7⑫`：會計科目頁要有「延伸建立」與「停用／啟用」兩個會送出的動作。**

    📌 那一頁現在**登記在 `AC1` 的唯讀豁免表裡**，理由是「後端只有一支 GET」——
    ⇒ 這一題綠的那天，**那一筆登記要拿掉**（`AC1` 的防腐題會自己抓到）。
    🔑 兩道守門互相咬住：一個說「它現在是唯讀的」，一個說「它應該不是」。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    js = (root / "frontend" / "js" / "account-items.js").read_text(
        encoding="utf-8", errors="replace")

    posts = re.search(r"method\s*:\s*['\"]POST['\"]", js, re.I)
    patches = re.search(r"method\s*:\s*['\"]PATCH['\"]", js, re.I)
    assert posts, (
        "`account-items.js` 沒有 `POST` —— 「延伸建立」還沒接。")
    assert patches, (
        "`account-items.js` 沒有 `PATCH` —— 「停用／啟用」還沒接。\n"
        + "☠️ 只接建立而不接停用的話，使用者建錯一個就**永遠拿不掉它**。")
