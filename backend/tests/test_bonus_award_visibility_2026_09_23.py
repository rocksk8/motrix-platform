# -*- coding: utf-8 -*-
"""`BN9` · 非最高管理者只看得到**自己有份**的獎金分潤單。

使用者逐字：
```
「非最高管理者只能看見自己可領到錢的獎金分潤單，其餘選項都看不到，
  產生獎金分潤單這些也只有最高管理員可見」
```

# ✅ 「與自己無關的單完全不出現」**已經實作了**（`bonus.py:307-310`）

```
🔴 差的是 `_is_manager(user)` 現在回 role in ("superadmin", **"admin"**)
⇒ `admin` 落在「管理者」那一側 ⇒ 他看得到**全部人的**獎金
```

# ⚠️ 而 `admin` 是**變成一般使用者**，不是看不到獎金頁

```
❌ 擋掉 admin        => 他有份的那一筆**他自己也看不到**
✅ admin 變一般使用者 => 看得到**自己那一列**，看不到別人的
```
🔑 兩者在「非管理者看不到別人的單」這一句上**長得一樣**，
  而只有正對照分得出來 —— 所以本檔兩個方向都釘。

# ⚠️ 不要弄壞既有那一條判斷

```
bonus.html:158  <div x-show="canManageItems">   <= 這才是入口的條件
bonus.js  :121  this.canManageItems = !!d.can_edit
```
⇒ `_is_manager` 收緊之後，**那個入口不可以跟著消失** —— 它問的是另一件事。

🔴 **而我第一版把這一行寫成「入口看 `can_edit`」，那是錯的**：
`can_edit` 是**後端回傳的欄位名**，畫面上那個旗標已經改名叫
`canManageItems`（`bonus.js:45` 逐字：「`can_edit` 那個名字說不出
edit 什麼」）—— 所以本檔反向控制第一次是**紅在我的判準上**。
"""
import pytest

AWARDS = "/api/bonus/awards"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_award(quote_no, people):
    """種一張獎金單，`people` 是拿到錢的人。回 `award_id`。

    ## 🔴 `bonus_award_lines.bonus_item_id` 有**外鍵**指向 `bonus_items`

    我第一版直接餵 `1`／`2` ⇒ `FOREIGN KEY constraint failed`
    ⇒ **兩題本來應該是綠的基準線也紅了**，而訊息指向資料層。
    🔑 今天第 N 次同一個形狀：**我的前置撞到資料層的守門**
      （先前是 `account_items` 的法定 TRIGGER、`voucher_lines` 的科目外鍵）。
    ⇒ 先種一個真的 `bonus_items` 列再用它的 id。
    """
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bonus_items (name, person_source, sort_order,"
            " is_active, created_by, created_at, updated_at)"
            " VALUES ('業務獎金','sales_person',0,1,'seed',"
            "'2026-09-01','2026-09-01')")
        item_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO bonus_awards (quote_no, base_amount, created_by,"
            " created_at, updated_at, voided_at) VALUES (?,?,?,?,?,'')",
            (quote_no, 100000, "seed", "2026-09-01", "2026-09-01"))
        aid = cur.lastrowid
        for who in people:
            conn.execute(
                "INSERT INTO bonus_award_lines (award_id, bonus_item_id,"
                " item_name_snapshot, username, person_source_snapshot,"
                " total_pct, person_pct, amount)"
                " VALUES (?,?,?,?,?,1000,10000,?)",
                (aid, item_id, "業務獎金", who, "sales_person", 10000))
        conn.commit()
        return aid
    finally:
        conn.close()


def _ids(payload):
    return {int(a.get("id")) for a in (payload or {}).get("awards") or []}


# ══════════════════════════════════════════════════════════════════════

def test_bn9_an_admin_only_sees_awards_they_are_paid_from(client, make_user):
    """🔴🔴 **`admin` 只看得到自己有份的那些。**

    ```
    _is_manager(user)  現在回 role in ("superadmin", **"admin"**)
    ⇒ admin 落在「管理者」那一側 ⇒ 他看得到**全部人的**獎金
    ```
    ☠️ 獎金是**薪酬**：一個 `admin` 看得到全公司每個人領多少，
       而使用者逐字說的是「**非最高管理者**只能看見自己可領到錢的」。
    ⚙️ 兩張單：一張他有份、一張他沒份 ⇒ 只有前者可以出現。
    """
    admin, ahdr = _hdr(client, make_user, "bn9_admin", role="admin",
                       modules=["reports"])
    mine = _seed_award("MQ-BN9-MINE", [admin, "someone_else"])
    theirs = _seed_award("MQ-BN9-THEIRS", ["alice", "bob"])

    r = client.get(AWARDS, headers=ahdr)
    assert r.status_code == 200, "admin 讀不到獎金清單：%s" % r.text[:200]
    got = _ids(r.json())
    assert mine in got, (
        "`admin` 看不到**自己有份**的那一張（%s）：%r\n" % (mine, got)
        + "☠️ 他收到一筆錢而**查不到來源** —— 那是把他整個擋掉了，\n"
          "   而使用者要的是「只看見自己可領到錢的」。")
    assert theirs not in got, (
        "`admin` 看得到**與自己無關**的那一張（%s）：%r\n" % (theirs, got)
        + "☠️ 獎金是**薪酬** —— 他看得到全公司每個人領多少。\n"
        + "🔑 `_is_manager()` 現在把 `admin` 算進管理者那一側，\n"
          "   而使用者逐字說的是「**非最高管理者**只能看見自己可領到錢的」。")


def test_bn9_a_superadmin_still_sees_everything(client, make_user):
    """⚙️ **正對照：最高管理者要看得到全部。**

    ☠️ 少了它，一個「一律只給自己那一列」的實作也會讓上一題綠 ——
       而那時**沒有人看得到全公司的獎金**，發放本身就做不了。
    """
    _u, hdr = _hdr(client, make_user, "bn9_super")
    a = _seed_award("MQ-BN9-A", ["alice"])
    b = _seed_award("MQ-BN9-B", ["bob"])
    r = client.get(AWARDS, headers=hdr)
    assert r.status_code == 200, r.text[:200]
    got = _ids(r.json())
    assert {a, b} <= got, (
        "最高管理者看不到全部（%r，期望含 %r）——\n" % (got, {a, b})
        + "☠️ 那時沒有人看得到全公司的獎金，**發放本身就做不了**。")


def test_bn9_a_plain_employee_sees_only_their_own_award(client, make_user):
    """🔴 **一般員工也是同一條規則 —— 而它今天就該是對的。**

    ⚙️ 這一題是 `admin` 那一題的**基準線**：
    ```
    它今天綠  => 「只看自己有份的」這條路**本來就走得通**
                ⇒ admin 那一題紅的是 `_is_manager` 的歸屬，不是這條路
    它今天紅  => **先修這裡** —— admin 那一題量不到東西
    ```
    🔑 兩題紅的原因不同，而**訊息會長得很像** ⇒ 先看這一題的顏色。
    """
    staff, shdr = _hdr(client, make_user, "bn9_staff", role="user",
                       modules=["reports"])
    mine = _seed_award("MQ-BN9-S1", [staff])
    theirs = _seed_award("MQ-BN9-S2", ["carol"])

    r = client.get(AWARDS, headers=shdr)
    assert r.status_code == 200, "一般員工讀不到獎金清單：%s" % r.text[:200]
    got = _ids(r.json())
    assert mine in got and theirs not in got, (
        "一般員工看到的是 %r（自己的 %s／別人的 %s）——\n" % (got, mine, theirs)
        + "⚠️ **這一題是基準線**：它紅的話，`admin` 那一題量不到東西。")


def test_bn9_the_amounts_of_other_people_stay_hidden(client, make_user):
    """🔴 **看得到那張單，而**只看得到自己那一列**。**

    ```
    bonus.py 的 docstring 逐字：
      「非管理者也看得到**單**（否則他不知道自己那一筆屬於哪一案），
        而他只看得到**自己那一列**金額。」
    ```
    ☠️ 少了這一格：`admin` 看得到自己有份的那張單，
       **而那張單上有同事的金額** —— 那與「看得到全部」只差一步。
    """
    admin, ahdr = _hdr(client, make_user, "bn9_amt", role="admin",
                       modules=["reports"])
    _seed_award("MQ-BN9-MIX", [admin, "colleague_x"])

    r = client.get(AWARDS, headers=ahdr)
    assert r.status_code == 200, r.text[:200]
    blob = r.text
    assert admin in blob, "連自己那一列都看不到：%s" % blob[:200]
    assert "colleague_x" not in blob, (
        "同一張單上**同事的那一列也回來了**：%s\n" % blob[:300]
        + "☠️ 那與「看得到全部」只差一步 —— `visible_lines()` 沒有生效。")


def test_bn9_the_items_entry_still_uses_can_manage_items(client, make_user):
    """⚙️ **反向控制：`_is_manager` 收緊之後，那個入口不可以跟著消失。**

    ```
    bonus.html:158  <div x-show="canManageItems">   <= 入口的條件
    ```
    🔑 `canManageItems` 問的是「**我能不能維護獎金項目**」（superadmin），
      `isManager` 問的是「**我看得到誰的獎金**」—— **兩件事**。
    ☠️ 把入口改成看 `isManager` 的話，`admin` 變一般使用者的那一刻，
       **一個本來就不該給他的入口**會以「順便」的方式消失 ——
       看起來沒事，而下一次有人要放寬 `isManager` 時會**連帶打開那個入口**。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    html = (root / "frontend" / "pages" / "bonus.html").read_text(
        encoding="utf-8", errors="replace")
    html = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), html,
                  flags=re.S)

    # 🔴 **我第一版找錯字了**：畫面上的旗標叫 `canManageItems`
    #    （`bonus.js:121  this.canManageItems = !!d.can_edit`），
    #    而 `can_edit` 這三個字在 `bonus.html` 裡**只出現在註解裡**
    #    ⇒ 我把註解抹掉之後就找不到它 ⇒ 這一題紅在**我的判準**上。
    # 🔑 而那個改名是**刻意的**（`bonus.js:45` 逐字：「`can_edit` 那個名字
    #    說不出 edit 什麼」）⇒ 釘後端的欄位名是釘錯了層，
    #    要釘的是**畫面上那個旗標**。
    m = re.search(r'x-(?:show|if)="([^"]*canManageItems[^"]*)"', html)
    assert m, (
        "`bonus.html` 上沒有任何綁到 `canManageItems` 的顯示條件 ——\n"
        + "☠️ 獎金項目的入口被改成看別的東西了。\n"
        + "🔑 `canManageItems`（能不能維護項目，來自後端 `can_edit`）與\n"
          "   `isManager`（看得到誰的獎金）是**兩件事** ——\n"
          "   混在一起之後，放寬其中一個會**連帶打開另一個**。")
    assert "isManager" not in m.group(1), (
        "那個入口的條件裡**同時**綁了 `isManager`：%r\n" % m.group(1)
        + "☠️ `_is_manager` 收緊（`admin` 變一般使用者）的那一刻，\n"
          "   這個入口會以「順便」的方式跟著改變 —— 看起來沒事，\n"
          "   **而下一次有人放寬 `isManager` 時會連帶打開它**。")
