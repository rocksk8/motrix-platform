# -*- coding: utf-8 -*-
"""`BN2` · 「獎金項目只有最高管理者可見」（使用者逐字）。

```
實查 routers/bonus.py:93   list_bonus_items 只 `_require_user(authorization)`
⇒ **任何登入者都看得到**
```
🔑 **寫已經擋住了**（`POST /items` 是 `require_superadmin=True`），
  **讀沒有** —— 而那是兩道不同的閘。
☠️ 獎金項目上有「誰有資格領這一類獎金」的規則（`person_source`）——
   那是薪酬結構，不是設定值。

# 🔴 而「403」與「回一個空清單」是兩件事

```
403      畫面說「你沒有權限看這個」
空清單    畫面說「**沒有資料**」  <= **那是另一句話，而且是假的**
```
⇒ 前端要據此說出不同的話 ⇒ 這一檔有一題專門釘那個差別。
"""
import pytest

ITEMS = "/api/bonus/items"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_item(name="業務獎金", person_source="sales_person"):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bonus_items (name, person_source, sort_order, "
            "is_active, created_by, created_at, updated_at) "
            "VALUES (?,?,0,1,'seed','2026-09-01','2026-09-01')",
            (name, person_source))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_bn2_a_plain_employee_cannot_list_bonus_items(client, make_user):
    """🔴 **非 superadmin 打 `GET /api/bonus/items` ⇒ 403。**

    ⚠️ 判準問「**它錯了回 403 還是 200 空清單**」，不問端點名字像不像。
    ☠️ 回 200 空清單的話，畫面說的是「沒有資料」—— **那是另一句話而且是假的**。
    ⚙️ `admin` 也要擋：使用者說的是「**最高**管理者」，而 `admin` 不是。
    """
    _seed_item()
    for role in ("user", "admin"):
        _u, hdr = _hdr(client, make_user, "bn2_%s" % role, role=role,
                       modules=["reports"])
        r = client.get(ITEMS, headers=hdr)
        if r.status_code in (404, 405, 422):
            pytest.fail("端點不見了（回 %s）—— **退回給我**。" % r.status_code)
        assert r.status_code in (401, 403), (
            "`%s` 看得到獎金項目（回 %s）：%s\n"
            % (role, r.status_code, r.text[:200])
            + "☠️ 獎金項目上有「誰有資格領這一類獎金」的規則"
              "（`person_source`）—— 那是**薪酬結構**。\n"
            + "🔑 寫已經擋住了（`POST /items` 是 `require_superadmin`），"
              "**讀沒有** —— 那是兩道不同的閘。")


def test_bn2_a_superadmin_still_gets_the_items(client, make_user):
    """⚙️ **正對照：最高管理者要拿得到。**

    ☠️ 少了它，一個「一律 403」的實作也會讓上一題綠 ——
       而那樣**沒有人看得到獎金項目**，整個模組用不了。
    """
    item_id = _seed_item(name="工程獎金", person_source="case_stages.assigned_to")
    _u, hdr = _hdr(client, make_user, "bn2_super")
    r = client.get(ITEMS, headers=hdr)
    assert r.status_code == 200, (
        "最高管理者被擋掉了（回 %s）：%s" % (r.status_code, r.text[:200]))
    got = (r.json() or {}).get("items") or []
    assert any(int(x.get("id") or 0) == item_id for x in got), (
        "最高管理者讀不到剛種的項目：%r\n" % got
        + "⚠️ 擋過頭了，上面那一題就不算數。")


def test_bn2_the_refusal_is_told_apart_from_an_empty_list(client, make_user):
    """🔴 **「被擋」與「沒有資料」要分得出來。**

    ```
    403 ＋ 一句話  => 畫面說「你沒有權限看這個」
    200 ＋ []      => 畫面說「**沒有資料**」  <= 另一句話，**而且是假的**
    ```
    ☠️ 混在一起的後果不是看不到東西，是**使用者被告知了一件不是真的事** ——
       他會去問「為什麼獎金項目不見了」，而其實是他不該看到。
    ⚙️ 這一題把兩種狀態**並排量一次**：
    ```
    沒有項目 ＋ superadmin  => 200 而 items 是空的   （真的沒有資料）
    有項目   ＋ 一般員工    => **不是 200**           （被擋）
    ```
    🔑 兩者若都是「200 ＋ 空清單」，前端就沒有東西可以分辨。
    """
    _u0, sup = _hdr(client, make_user, "bn2_empty_sup")
    r0 = client.get(ITEMS, headers=sup)
    assert r0.status_code == 200, "最高管理者被擋：%s" % r0.text[:200]
    assert ((r0.json() or {}).get("items") or []) == [], (
        "前置不對：還沒種項目而清單非空。")

    _seed_item(name="有東西了")
    _u1, staff = _hdr(client, make_user, "bn2_empty_staff", role="user",
                      modules=["reports"])
    r1 = client.get(ITEMS, headers=staff)
    assert r1.status_code != 200, (
        "「真的沒有資料」與「不給你看」**回的是同一個東西**（都是 200）——\n"
        + "☠️ 前端沒有任何依據說出不同的話 ⇒ 它只能說「沒有資料」，\n"
          "   而那是假的。")
