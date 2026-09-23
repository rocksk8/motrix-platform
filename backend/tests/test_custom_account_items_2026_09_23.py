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
    ☠️ 撞號的後果不是報錯：新的那一筆會**覆蓋掉**已停用的那一筆，
       而那一筆**可能已經被傳票引用過** ⇒ 舊傳票上的科目名稱**變成別的東西**。
    🔑 停用不是刪除 —— **號碼要跟著留著**。
    """
    _u, hdr = _hdr(client, make_user, "ca1_hold")
    for _ in range(3):
        assert _extend(client, hdr).status_code == 200
    assert _set_active(client, hdr, "%s-2" % PARENT, False).status_code == 200
    assert int(_row("%s-2" % PARENT)["is_active"]) == 0, "停用沒有落地。"

    assert _extend(client, hdr).status_code == 200
    got = _codes_under()
    assert "%s-4" % PARENT in got, (
        "停用 `%s-2` 之後再建，拿到的是 %r —— 應該有 `%s-4`。\n"
        % (PARENT, got, PARENT)
        + "☠️ 多半是**數筆數**而不是**取最大值**：停用的那一筆仍然佔號。\n"
        + "🔑 撞號不會報錯 —— 新的那一筆會覆蓋掉已停用的，\n"
          "   而它**可能已經被傳票引用過** ⇒ 舊傳票上的科目名稱變成別的東西。")
    assert len([c for c in got if c.startswith(PARENT + "-")]) == 4


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
    items = payload.get("items") if isinstance(payload, dict) else payload
    assert items, "`GET %s` 沒有回清單：%r" % (API, payload)

    order = [x.get("code") for x in items
             if str(x.get("code") or "").startswith(PARENT + "-")]
    assert len(order) == 10, "清單裡只有 %d 個自建科目：%r" % (len(order), order)
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

    from routers.accounting_export import validate_account_code
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
        pytest.fail(
            "`GET %s` 的回應沒有自建總數（找過 `custom_count`／"
            "`customCount`／`custom_total`）。現有鍵：%s\n"
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
