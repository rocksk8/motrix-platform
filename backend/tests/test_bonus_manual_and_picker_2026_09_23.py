# -*- coding: utf-8 -*-
"""`BN3`／`BN4`／`BN5`（`docs/windows/SPEC-BN2-BN5.md`）。

# 🔴 `BN5` 的核心：**兩件「不可以被濾掉」的事**

```
① 淨利 ≤ 0 的那一筆        -> **列出來、標原因、不可選**
② 已產過有效獎金單的        -> **標示不是藏起來**
```
☠️ 濾掉的症狀：使用者**只會看到選單裡沒有它**，而他不知道為什麼 ——
   那與「沒有這個案件」長得一模一樣。
📌 與 `BN1` 的「`ok=false` 的項目要回傳不可以濾掉」是**同一條規則**。

# ☠️ 而「已結案」**不在 `status` 欄位裡**

```
quotations.status    只有 已送出 25 ／ 已拒絕 1   <= **沒有「已結案」**
quotations.deal_tag  未成案 11 ／ **已結案 9** ／ 已成案 5 ／ 已提供 1
```
⇒ 照 `status` 寫會查到 **0 筆**，**而那與「沒有可選的案件」長得一模一樣**。

# ⚠️ ② 今天真實資料是 **0 筆** ⇒ 那一格**測不出差別**，必須合成

A-2 實跑：`bonus_awards WHERE voided_at = ''` ⇒ **0 筆**。
⇒ 「已產過的要標示」那一題若靠既有資料，它**對空集合斷言** ⇒ 綠而什麼都沒驗。

# 🔑 `BN3` 的觀測點：**走下游，不要驗中間**

```
❌ 驗 people_for_item("manual", …) 回了幾個人   <= 中間層
✅ 驗那些人**真的進了 bonus_award_lines**        <= 下游，成功後才會被寫入
```
"""
import json

import pytest

ITEMS = "/api/bonus/items"
PICKER = "/api/bonus/awards/candidates"

#: `§4` 實查：母體是 `deal_tag`，**不是 `status`**。
CLOSED_TAG = "已結案"

#: `BN4`：使用者看得到的新名稱。
NEW_NAME = "獎金分潤單"
OLD_NAME = "獎金單"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_case(quote_no, net_profit, settle_status="finalized",
               deal_tag=CLOSED_TAG):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, deal_tag, data_json, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試案", 0, 0, deal_tag,
             json.dumps({"settlement": {"status": settle_status,
                                        "summary": {"netProfit": net_profit}}}),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _seed_award(quote_no, voided=""):
    """替某案件種一張獎金單。`voided=""` ⇒ **有效**。"""
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bonus_awards (quote_no, base_amount, created_by, "
            "created_at, updated_at, voided_at) VALUES (?,?,?,?,?,?)",
            (quote_no, 1000, "seed", "2026-09-01", "2026-09-01", voided))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _candidates(client, hdr):
    r = client.get(PICKER, headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`GET %s` 還不存在（回 %s）。\n" % (PICKER, r.status_code)
            + "📌 `BN5`：下拉**要列什麼**是這一項的全部內容，\n"
              "   不是把 `input` 換成 `select`。\n"
            + "⚠️ 路徑我單方面定的，**要換退回給我**。")
    assert r.status_code in (200, 400, 403), (
        "回 %s：%s" % (r.status_code, r.text[:200]))
    return r


# ══════════════════════════════════════════════════════════════════════
# BN5：兩件不可以被濾掉的事
# ══════════════════════════════════════════════════════════════════════

def test_bn5_the_picker_uses_deal_tag_not_status(client, make_user):
    """🔴 **母體是 `deal_tag = '已結案'`，不是 `status`。**

    ```
    quotations.status   只有 已送出／已拒絕  <= **沒有「已結案」**
    quotations.deal_tag 已結案 9 筆
    ```
    ☠️ 照 `status` 寫會查到 **0 筆** —— **而那與「沒有可選的案件」
       長得一模一樣**：畫面上是一個空的選單，不是一個錯誤。
    ⚙️ 這一題同時種一筆 `deal_tag='已結案'` 與一筆 `deal_tag='已成案'`
       ⇒ 只有前者可以出現。
    """
    _seed_case("MQ-BN5-OK", 500000)
    _seed_case("MQ-BN5-NOTYET", 500000, deal_tag="已成案")
    _u, hdr = _hdr(client, make_user, "bn5_tag")

    got = _candidates(client, hdr).json()
    items = got.get("items") if isinstance(got, dict) else got
    assert items is not None, "回應沒有清單：%r" % got
    nos = {x.get("quote_no") or x.get("quoteNo") for x in items}
    assert "MQ-BN5-OK" in nos, (
        "`deal_tag='已結案'` 的案件沒有出現：%r\n" % sorted(nos)
        + "☠️ 照 `status` 查會得到 **0 筆**，而那與「沒有可選的案件」一樣。")
    assert "MQ-BN5-NOTYET" not in nos, (
        "`deal_tag='已成案'`（還沒結案）的案件也被列出來了：%r" % sorted(nos))


def test_bn5_a_case_with_no_profit_is_listed_but_not_selectable(client,
                                                                make_user):
    """🔴🔴 **淨利 ≤ 0 的案件要**列出來**並標原因，不可以濾掉。**

    ```
    已結案且已精算 9 筆，而淨利 > 0 的只有 **8 筆** ⇒ 有 1 筆淨利 ≤ 0
    ```
    ☠️ 用 `netProfit > 0` 過濾的話，**那一筆會安靜消失** ——
       使用者只會看到「選單裡沒有它」，**而他不知道為什麼**。
    📌 與 `BN1` 的「`ok=false` 的項目要回傳不可以濾掉」是**同一條規則**。
    ⚙️ 三格：**在清單裡** ＋ **標了原因** ＋ **不可選**。
       少了第三格，使用者選得下去而按鈕按不動（或送出才被拒）。
    """
    _seed_case("MQ-BN5-ZERO", 0)
    _seed_case("MQ-BN5-GOOD", 500000)
    _u, hdr = _hdr(client, make_user, "bn5_zero")

    got = _candidates(client, hdr).json()
    items = got.get("items") if isinstance(got, dict) else got
    one = next((x for x in items
                if (x.get("quote_no") or x.get("quoteNo")) == "MQ-BN5-ZERO"),
               None)
    assert one is not None, (
        "淨利 0 的案件**不在清單裡**（現有：%r）——\n"
        % sorted(x.get("quote_no") or x.get("quoteNo") for x in items)
        + "☠️ 它被 `netProfit > 0` 濾掉了 ⇒ 使用者只會看到選單裡沒有它，\n"
          "   **而他不知道為什麼**。")
    assert one.get("selectable") is False, (
        "它在清單裡，而**選得下去**：%r\n" % one
        + "☠️ 選了之後才被拒 ⇒ 使用者做了一件白工。")
    reason = str(one.get("reason") or one.get("note") or "")
    assert reason.strip(), (
        "它不可選，**而沒有說為什麼**：%r\n" % one
        + "📌 `§4`：標「無可分配基數」之類的原因 —— 不可選而沒有理由，\n"
          "   使用者會以為是系統壞了。")


def test_bn5_a_case_with_a_live_award_is_marked_not_hidden(client, make_user):
    """🔴🔴 **已產過**有效**獎金單的案件要**標示**，不是藏起來。**

    ## ⚠️ 這一格今天**測不出差別**，所以我合成

    ```
    A-2 實跑：bonus_awards WHERE voided_at = '' -> **0 筆**
    ⇒ 靠既有資料的話，這一題**對空集合斷言** => 綠而什麼都沒驗
    ```
    ⇒ 本題自己種一張**有效**的與一張**已作廢**的。

    ## 🔑 判斷用 `voided_at = ''`，不是「有沒有紀錄」

    ```
    有紀錄就擋   => **作廢之後再也產不出第二張**
    voided_at='' => 作廢之後可以再產一次  ✅
    ```
    ☠️ 而作廢重開是**正常流程**（`v97` 的部分唯一索引整個是為它設計的）。
    """
    _seed_case("MQ-BN5-LIVE", 500000)
    _seed_case("MQ-BN5-VOIDED", 500000)
    aid = _seed_award("MQ-BN5-LIVE")
    _seed_award("MQ-BN5-VOIDED", voided="2026-09-01T00:00:00")
    _u, hdr = _hdr(client, make_user, "bn5_live")

    got = _candidates(client, hdr).json()
    items = got.get("items") if isinstance(got, dict) else got
    by_no = {(x.get("quote_no") or x.get("quoteNo")): x for x in items}

    live = by_no.get("MQ-BN5-LIVE")
    assert live is not None, (
        "已產過有效獎金單的案件**被藏起來了**（現有：%r）——\n" % sorted(by_no)
        + "☠️ 使用者會以為那個案件不見了，而其實是它已經有一張單。")
    assert live.get("selectable") is False, (
        "它還選得下去：%r —— 送出時會撞部分唯一索引回 409。" % live)
    assert str(aid) in str(live.get("reason") or live.get("note") or ""), (
        "標示裡沒有那張單的 id（%s）：%r\n" % (aid, live)
        + "📌 `§4`：標「已產生（#id）」—— 使用者要能**點過去看**。")

    voided = by_no.get("MQ-BN5-VOIDED")
    assert voided is not None and voided.get("selectable") is not False, (
        "**已作廢**那一張讓案件變成不可選：%r\n" % voided
        + "☠️ 判斷用了「有沒有紀錄」而不是 `voided_at = ''`\n"
          "   ⇒ **作廢之後再也產不出第二張**，而作廢重開是正常流程。")


def test_bn5_the_two_empty_reasons_are_not_merged(client, make_user):
    """🔴 **「沒有可選的案件」與「你沒有權限」不可以合成一句。**

    ```
    沒有已精算的案件  -> 「目前沒有已結案且已完成精算的案件。」
    非管理者          -> 「您沒有產生獎金分潤單的權限。」
    ```
    ☠️ 合成一句的話，**沒有權限的人會去找案件**，而找不到 —— 因為問題不在那裡。
    ⚙️ 兩個狀態並排量一次：非管理者**不可以**拿到 200 空清單。
    """
    _u0, sup = _hdr(client, make_user, "bn5_sup")
    r0 = _candidates(client, sup)
    assert r0.status_code == 200, "最高管理者被擋：%s" % r0.text[:200]

    _u1, staff = _hdr(client, make_user, "bn5_staff", role="user",
                      modules=["reports"])
    r1 = client.get(PICKER, headers=staff)
    assert r1.status_code != 200, (
        "非管理者拿到 200（%s）——\n" % r1.text[:160]
        + "☠️ 「沒有可選的案件」與「你沒有權限」變成同一句話，\n"
          "   **而沒有權限的人會去找案件**。")


# ══════════════════════════════════════════════════════════════════════
# BN3：manual 來源
# ══════════════════════════════════════════════════════════════════════

def test_bn3_a_manual_item_pays_the_people_it_lists(client, make_user):
    """🔴🔴 **`BN3`：`manual` 指定的人要**真的進 `bonus_award_lines`**。**

    ⚙️ 觀測點**走下游**：
    ```
    ❌ 驗 people_for_item("manual", …) 回了幾個人   <= 中間層
    ✅ 驗那些人進了 bonus_award_lines               <= **成功後才會被寫入**
    ```
    📌 它同時解掉一個既有落差：`quotations.owner`／`engineer`
       **兩個欄位不存在** ⇒ 用那兩個來源建的項目**永遠發不出去**；
       `manual` 讓使用者有一條路可以自己指定。
    """
    _seed_case("MQ-BN3-M", 1000000)
    a, _ = _hdr(client, make_user, "bn3_alice")
    b, _ = _hdr(client, make_user, "bn3_bob")
    _u, hdr = _hdr(client, make_user, "bn3_sup")

    r = client.post(ITEMS, headers=hdr, json={
        "name": "特別獎金", "person_source": "manual", "people": [a, b]})
    if r.status_code in (404, 405, 422):
        pytest.fail("`POST %s` 走不到（回 %s）。" % (ITEMS, r.status_code))
    assert r.status_code == 200, (
        "建不了 `manual` 項目：%s %s\n" % (r.status_code, r.text[:200])
        + "📌 `§2`：`people_for_item()` 多一支 `manual`，回同樣的三元組。")
    item_id = (r.json() or {}).get("id")
    assert item_id, "回應沒有 id：%r" % r.json()

    ar = client.post("/api/bonus/awards", headers=hdr, json={
        "quote_no": "MQ-BN3-M",
        "allocations": [{"bonus_item_id": item_id, "total_pct": 1000,
                         "person_pct": {a: 5000, b: 5000}}]})
    assert ar.status_code == 200, (
        "用 `manual` 的人送出獎金單被拒：%s %s" % (ar.status_code, ar.text[:200]))

    import db
    conn = db.get_db()
    try:
        paid = {r_["username"] for r_ in conn.execute(
            "SELECT DISTINCT username FROM bonus_award_lines"
            " WHERE bonus_item_id = ?", (item_id,))}
    finally:
        conn.close()
    assert paid == {a, b}, (
        "`manual` 指定 %r，而實際寫進 `bonus_award_lines` 的是 %r\n"
        % ({a, b}, paid)
        + "☠️ 中間那一層回對了而下游沒寫進去 —— **只驗中間層看不出來**。")


def test_bn3_a_manual_item_with_nobody_is_refused(client, make_user):
    """🔴 **`manual` 而沒有指定任何人 ⇒ 400。**

    ☠️ 允許的話 `people_for_item` 回 `(False, [], "無可發放對象")`
       ⇒ 那個項目**從來不會出現在任何一張獎金單上**，而沒有人會發現。

    ## ⚠️ 這一題**第一版是假綠燈**，我當場抓到

    ```
    PERSON_SOURCES = ['sales_person', 'case_stages.assigned_to']
    ⇒ `manual` **還不在白名單裡** ⇒ 回的是「不支援的人員來源『manual』」
    ⇒ 我只斷言 400 => **綠，而它驗的是另一件事**
    ```
    🔑 〈假綠燈：產品的退路〉—— 一句**合法的拒絕**吃掉了我的斷言。
    ⇒ 加一句：訊息要說得出是「**沒有指定人**」，不是「不支援這個來源」。
    """
    _u, hdr = _hdr(client, make_user, "bn3_empty")
    r = client.post(ITEMS, headers=hdr, json={
        "name": "沒人的項目", "person_source": "manual", "people": []})
    if r.status_code in (404, 405, 422):
        pytest.fail("端點走不到（回 %s）。" % r.status_code)
    assert r.status_code == 400, (
        "`manual` 而沒有指定人被接受了（回 %s）——\n" % r.status_code
        + "☠️ 那個項目**從來不會出現在任何一張獎金單上**。")
    assert "不支援" not in r.text, (
        "它被擋下來了，**而理由是「不支援 `manual` 這個來源」**：%s\n"
        % r.text[:200]
        + "☠️ 那是一句**合法的拒絕**吃掉了我的斷言（〈假綠燈：產品的退路〉）——\n"
          "   這一題要驗的是「`manual` **可用**，而沒指定人要擋」。\n"
        + "🔑 先把 `manual` 加進 `PERSON_SOURCES`，這一題才量得到東西。")


def test_bn3_an_unknown_username_is_refused_and_named(client, make_user):
    """🔴 **指定的帳號不存在／已停用 ⇒ 400，而且說出是哪一個。**

    ```
    ❌ 存 display_name／自由輸入  打錯一個字那個人就領不到，**而畫面上一切正常**
    ✅ 存 username（UNIQUE NOT NULL，且不在可改欄位白名單裡）
    ```
    ⚠️ 只回 400 不夠：使用者一次指定好幾個人，**說不出是哪一個等於要他自己試**。
    """
    a, _ = _hdr(client, make_user, "bn3_real")
    _u, hdr = _hdr(client, make_user, "bn3_ghost_sup")
    r = client.post(ITEMS, headers=hdr, json={
        "name": "有鬼的項目", "person_source": "manual",
        "people": [a, "nobody_here_9912"]})
    if r.status_code in (404, 405, 422):
        pytest.fail("端點走不到（回 %s）。" % r.status_code)
    assert r.status_code == 400, (
        "不存在的帳號被接受了（回 %s）——\n" % r.status_code
        + "☠️ 打錯一個字那個人就領不到，**而畫面上一切正常**。")
    assert "nobody_here_9912" in r.text, (
        "訊息沒說出是哪一個帳號：%s" % r.text[:200])


def test_bn3_the_existing_sources_do_not_change_behaviour(client, make_user):
    """⚙️ **正對照：既有四個來源不可以因為多了 `manual` 而改變行為。**

    ☠️ 最容易踩的是「把 `people_for_item` 改成先查新表」——
       那會讓既有來源在新表為空時回 `(False, [], …)` ⇒ **全部發不出去**。
    ⚙️ 這一題不碰新表，直接走既有的 `sales_person` 那一條。
    """
    from helpers.bonus import people_for_item

    ok, people, note = people_for_item(
        {"person_source": "sales_person"}, {"sales_person": "alice"})
    assert ok and people == ["alice"], (
        "既有的 `sales_person` 來源壞了：%r\n" % ((ok, people, note),)
        + "☠️ 多半是 `people_for_item` 被改成先查 `bonus_item_people`，\n"
          "   而既有來源在那張表裡沒有列 ⇒ **全部發不出去**。")

    ok2, people2, note2 = people_for_item(
        {"person_source": "case_stages.assigned_to"},
        {"stages": [{"assigned_to": '["bob"]'}]})
    assert ok2 and people2 == ["bob"], (
        "既有的 `case_stages.assigned_to` 來源壞了：%r" % ((ok2, people2, note2),))


# ══════════════════════════════════════════════════════════════════════
# BN4：改名
# ══════════════════════════════════════════════════════════════════════

def test_bn4_the_user_facing_name_changed_everywhere(client, make_user):
    """🔴 **`BN4`：使用者看得到的地方要改成「獎金分潤單」。**

    ⚠️ 而 `routers/bonus.py:443` 那一處**寫進 `audit_log`** ⇒
       **既有紀錄不回頭改** —— 這一題只看**原始碼**，不看歷史資料。
    ☠️ 要求歷史資料也變的話，那是**改寫稽核紀錄**。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    targets = [
        root / "backend" / "helpers" / "bonus.py",
        root / "backend" / "routers" / "bonus.py",
        root / "frontend" / "js" / "bonus.js",
        root / "frontend" / "pages" / "bonus.html",
    ]
    stale = []
    for p in targets:
        assert p.is_file(), "`%s` 不見了 —— **退回給我**。" % p.name
        src = p.read_text(encoding="utf-8", errors="replace")
        src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
        for m in re.finditer(re.escape(OLD_NAME), src):
            head = src[max(0, m.start() - 3):m.start()]
            if head.endswith("分潤"):        # 「獎金分潤單」本身
                continue
            stale.append("%s:%d" % (p.name, src[:m.start()].count("\n") + 1))
    assert not stale, (
        "還有 %d 處寫著「%s」：%r\n" % (len(stale), OLD_NAME, stale[:10])
        + "📌 `BN4`：使用者看得到的字要改成「%s」。\n" % NEW_NAME
        + "⚠️ 而 `routers/bonus.py:443` 寫進 `audit_log` ⇒\n"
          "   **既有紀錄不回頭改**（那是改寫稽核紀錄）——\n"
          "   這一題只看原始碼。")
