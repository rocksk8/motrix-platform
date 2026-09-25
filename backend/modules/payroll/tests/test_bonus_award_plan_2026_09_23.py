# -*- coding: utf-8 -*-
"""`BN1` · `GET /api/bonus/awards/plan/{quote_no}`（A-2 `SPEC-BN1-PLAN.md`）。

```
POST /api/bonus/awards 要 allocations[].person_pct = { username: pct }
而那些 username 由 people_for_item() 決定，**六支端點沒有一支吐出它**
⇒ 畫面組不出 request body
```
🔑 這是**契約缺口，不是接線缺口**。

# 🔴 為什麼是新端點而不是前端自己算

資料前端拿得到（案件 API 有 `assignedTo`），**而那是把同一條規則抄到第二個地方**。
```
modules/payroll/bonus.py:141 已標「已知的未來來源 quotations.assigned_user_ids」
⇒ 加它的那天：後端改、JS 不會跟
⇒ 症狀是**少發一個人，而總額對得起來**
```
☠️ **對不起來還有人會查，對得起來沒有人會查。**
📌 A 裁成一句：**規則只有一份。**

# ⚠️ 單位是**基點**（1/10000），而欄位名字叫 `pct`

```
BASIS_POINTS = 10000     pool = base × total_pct // 10000
```
🔑 **50% 要送 `5000`，不是 `50`。**
☠️ 送 `50` 的後果：獎金變成應得的 1/100，**而畫面上它是一個格式正確的金額**
⇒ 沒有人會把它看成錯誤，只會覺得「怎麼這麼少」。

## ☠️ 而驗這個單位**不可以寫成「差 100 倍」**

```
pool 是整數無條件捨去
base=123456    pool(50)=617     pool(5000)=61728    差 28，**不是 100 倍**
base=999999    pool(50)=4999    pool(5000)=499999   差 1
只有 base 是 10000 的倍數時才剛好成立（我 import 產品碼實跑 7 個有 4 個紅）
```
🔑 那種寫法**紅在正確的碼上**，而訊息指向 `split_award()`
⇒ 下一個人最省力的反應是去「修」那個先乘後除，**而那會真的弄壞精度**。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn1_a_negative_total_is_refused、test_bn1_a_total_over_one_hundred_percent_is_refused、test_bn1_an_unresolvable_sales_person_is_refused_not_silently_paid、test_bn1_it_says_whether_a_live_award_already_exists、test_bn1_paying_less_than_the_whole_pool_is_still_allowed、test_bn1_person_shares_over_one_hundred_percent_are_refused、test_bn1_the_people_it_promises_are_the_people_who_actually_get_paid
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import json

import pytest

#: `§160` 風格的路徑（A-2 `SPEC-BN1-PLAN §1`）。⚠️ 改了 **退回給我**。
PLAN = "/api/bonus/awards/plan/%s"

#: `§166`：走到端點才會出現的狀態碼。**404／405／422 都不在裡面**
#: —— 這個 repo 裡「端點不存在」有三種臉。
OK_CODES = (200, 400, 403)

#: `modules/payroll/bonus.py:152`。
NO_ELIGIBLE_PEOPLE = "無可發放對象"

#: 基點。
BP = 10000


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_case(quote_no, net_profit=1000000, sales_person="alice",
               stage_people=None):
    """種一個有精算淨利的案件。`stage_people=None` ⇒ **一個階段負責人都沒有**。

    🔴 `QS1-a` 落地後（`208f0d2`）：`sales_person` 這個來源要靠
    `sales_person_id` 解出真的 `users.username`，`quotations.sales_person`
    那個顯示名欄位不再是 `people_for_item()` 的解析依據。⇒ 這裡**同時**
    查一次 `users`，若 `sales_person` 剛好是一個真實存在的
    `username`，就順手把 `sales_person_id` 也設起來——呼叫端只要傳的是
    一個真帳號（多數呼叫端本來就是靠 `make_user()` 建的），不必額外
    改呼叫方式就能自動接上新行為；傳一個**不存在**的字串（例如驗證
    「解析不出來要被擋」那一題）則刻意保持 `sales_person_id` 是 NULL，
    這正是那一題要的前提。
    """
    import db
    conn = db.get_db()
    try:
        sales_person_id = None
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? AND active = 1",
            (sales_person,)).fetchone()
        if row is not None:
            sales_person_id = int(row["id"])
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, sales_person, sales_person_id,"
            " data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已結案", "測試客戶", "測試案", 0, 0, sales_person,
             sales_person_id,
             json.dumps({"settlement": {"summary": {"netProfit": net_profit}}}),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        if stage_people is not None:
            cols = {r["name"] for r in conn.execute(
                "PRAGMA table_info(case_stages)")}
            assert "assigned_to" in cols, "`case_stages.assigned_to` 不見了。"
            # 🔴 `case_stages` 的 NOT NULL 無預設欄位有**三個**（我實查 PRAGMA）：
            #    `quote_no` / `created_at` / `updated_at`
            # ☠️ 我第一版只給了 `quote_no` ⇒ `IntegrityError`，而 traceback
            #    指向**我的 seed**，長得像資料層問題（〈探針與被測對象糾纏〉）。
            # ⚠️ 補了 `created_at` 還會**再撞一次** `updated_at` ⇒ 兩個一起補。
            conn.execute(
                "INSERT INTO case_stages (quote_no, assigned_to, "
                "created_at, updated_at) VALUES (?,?,?,?)",
                (quote_no, json.dumps(stage_people),
                 "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _seed_item(name, person_source, is_active=1):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bonus_items (name, person_source, sort_order, "
            "is_active, created_by, created_at, updated_at) "
            "VALUES (?,?,0,?,'seed','2026-09-01','2026-09-01')",
            (name, person_source, is_active))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _plan(client, hdr, quote_no):
    """打 `plan`，**先釘狀態碼形狀再看內容**（`§166`）。"""
    r = client.get(PLAN % quote_no, headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`GET %s` 還不存在（回 %s，案件 `%s`）。\n"
            % (PLAN % "{quote_no}", r.status_code, quote_no)
            + "⚠️ **除非你查的是一個不存在的案件** —— `/base` 對找不到的案件\n"
              "   回 404，而 `plan` 會照同一條做 ⇒ 那時 404 是**正確答案**，\n"
              "   要另外寫一支不經過 `_plan()` 的輔助函式。\n"
              "   （本檔每一題都先 `_seed_case()`，所以目前撞不到。）\n"
            + "📌 這個 repo 裡「端點不存在」有**三種臉**：\n"
              "    404  StaticFiles 接走 GET\n"
              "    405  StaticFiles 接走非 GET（它只處理 GET/HEAD）\n"
              "    422  被同 prefix 的 `/{id}` path param 當成整數解析\n"
            + "⚠️ ⇒ `assert status_code != 404` **擋不到後兩種**。\n"
            + "🔴 而 422 這一種對 `plan` 是真實風險：日後有人加\n"
              "   `GET /awards/{award_id}` 並宣告在 `plan` 之前 ⇒\n"
              "   `/awards/plan/MQ-1` 會把 `plan` 當成 `award_id`。\n"
              "   ⇒ **`plan` 必須宣告在任何 `/awards/{award_id}` 之前**，\n"
              "     而那一行要寫成程式碼註解 —— 下一個加端點的人不會讀規格。")
    assert r.status_code in OK_CODES, (
        "`plan` 回 %s，不在 %s 裡：%s"
        % (r.status_code, list(OK_CODES), r.text[:200]))
    return r


def _item_of(payload, item_id):
    for it in payload.get("items") or ():
        if int(it.get("bonus_item_id") or 0) == int(item_id):
            return it
    return None


# ══════════════════════════════════════════════════════════════════════
# ① 權限：與 POST /awards 同一道閘
# ══════════════════════════════════════════════════════════════════════

def test_bn1_a_non_manager_is_refused_not_given_an_empty_list(client,
                                                              make_user):
    """🔴 **非管理者要回 403，不是 200 加一個空清單。**

    ☠️ 回空清單的後果不是「看不到東西」，是**繞過可見性規則的入口被打開了**：
    ```
    visible_lines()  本人只看得到自己那一列
    而 plan 回的是**全案每個人的發放對象名單**
    ```
    ⇒ 閘門要與 `POST /awards` **同一道**（`_is_manager`），不可以更鬆。
    ⚠️ 判準是「有沒有被擋」：401 與 403 都算。
    """
    _seed_case("MQ-BN1-403")
    _u, hdr = _hdr(client, make_user, "bn1_staff", role="user",
                   modules=["bonus"])
    r = client.get(PLAN % "MQ-BN1-403", headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail("端點還不存在（回 %s）—— 這一格量不到權限。" % r.status_code)
    assert r.status_code in (401, 403), (
        "一般員工讀到了發放對象名單（回 %s）：%s\n" % (r.status_code, r.text[:200])
        + "☠️ 那份清單是**全案每個人**，而 `visible_lines()` 那條\n"
          "   「本人只看得到自己那一列」就被這支端點繞過去了。")


# ══════════════════════════════════════════════════════════════════════
# ② 契約：ok=false 的項目要留著
# ══════════════════════════════════════════════════════════════════════

def test_bn1_an_item_with_nobody_is_still_listed_and_says_why(client,
                                                              make_user):
    """🔴 **反向控制：發不出去的項目要留在清單裡，並說出為什麼。**

    ```
    person_source = case_stages.assigned_to，而案件**一個階段負責人都沒有**
    （assigned_to 的 DEFAULT 就是 '[]' ⇒ 空是常態不是例外）
    ⇒ people_for_item() 回 (False, [], NO_ELIGIBLE_PEOPLE)
    ```
    ☠️ 濾掉它的後果，`people_for_item()` 的 docstring 逐字在防：
       「那個項目從來沒出現在任何一張獎金單上 ——
        **而沒有人會發現一個從來不出現的東西**」

    ⚠️ **不要用「把 `person_source` 改成一個不合法的值」做這個反向控制**：
    ```
    POST /items 有 source not in PERSON_SOURCES -> 400（bonus.py:83）
    ⇒ 那條路走不通，只能直接 INSERT 繞過 router
    ⇒ 而那就變成「測試自己準備的輸入繞過生產路徑上的一段」
    ```
    🔑 上面那個做法**全程走產品路徑**，這是它比較好的唯一理由。
    """
    _seed_case("MQ-BN1-EMPTY", stage_people=None)   # 刻意沒有任何階段
    item_id = _seed_item("工程獎金", "case_stages.assigned_to")
    _u, hdr = _hdr(client, make_user, "bn1_mgr1")

    payload = _plan(client, hdr, "MQ-BN1-EMPTY").json()
    it = _item_of(payload, item_id)
    assert it is not None, (
        "「工程獎金」整個不見了。收到的 items：%r\n"
        % (payload.get("items"),)
        + "☠️ 它被濾掉了 ⇒ **沒有人會發現一個從來不出現的東西**。")
    assert it.get("ok") is False, "它應該是 ok=false：%r" % it
    assert it.get("people") == [], "ok=false 而還有人：%r" % it
    assert NO_ELIGIBLE_PEOPLE in (it.get("note") or ""), (
        "它沒有說出為什麼不能發（note=%r）——\n" % it.get("note")
        + "📌 `note` 要**直接用後端回的字串**，前端不重寫文案 ⇒ 規則只有一份。")


def test_bn1_ok_and_people_never_disagree(client, make_user):
    """🔴 **`ok` 與 `people` 必須一致，兩個方向都要。**

    ```
    ok=true  而 people == []   => 畫面出現「可以發放，但沒有人」
    ok=false 而 people != []   => 畫面列出人，而按下產生會被後端擋掉
    ```
    ☠️ 第二種更糟：使用者**看得到名字**，填完比例才被拒絕。
    """
    _seed_case("MQ-BN1-PAIR", sales_person="alice", stage_people=None)
    good = _seed_item("業務獎金", "sales_person")
    bad = _seed_item("工程獎金", "case_stages.assigned_to")
    _u, hdr = _hdr(client, make_user, "bn1_mgr2")

    payload = _plan(client, hdr, "MQ-BN1-PAIR").json()
    seen = 0
    for it in payload.get("items") or ():
        seen += 1
        ok, people = it.get("ok"), it.get("people")
        assert isinstance(people, list), "`people` 不是陣列：%r" % it
        assert bool(ok) == bool(people), (
            "`ok` 與 `people` 對不起來：%r\n" % it
            + "☠️ `ok=true` 而沒有人 ⇒ 畫面說「可以發放，但沒有人」；\n"
              "   `ok=false` 而有人 ⇒ 使用者看得到名字，填完比例才被拒絕。")
    assert seen >= 2, (
        "只看到 %d 個項目，而我種了兩個（%s／%s）。\n" % (seen, good, bad)
        + "⚠️ 少的那個多半是 `ok=false` 被濾掉了。")


def test_bn1_a_deactivated_item_is_not_offered(client, make_user):
    """🔴 **`is_active = 0` 的項目不可以出現。**（與 `create_award` 同一條過濾）

    ```
    create_award 逐字：SELECT * FROM bonus_items WHERE is_active = 1
    ```
    ☠️ 不加的後果是**「先問再做」失效的具體形狀**：
    ```
    畫面列出已停用的項目 -> 使用者填完比例 -> 按下產生
      -> 400「獎金項目不存在或已停用」
    ```
    🔑 **問過了，而答案是錯的** —— 那比不問更糟，因為他相信了它。
    """
    _seed_case("MQ-BN1-OFF", sales_person="alice")
    dead = _seed_item("停用的獎金", "sales_person", is_active=0)
    live = _seed_item("還在用的獎金", "sales_person")
    _u, hdr = _hdr(client, make_user, "bn1_mgr3")

    payload = _plan(client, hdr, "MQ-BN1-OFF").json()
    assert _item_of(payload, live) is not None, (
        "啟用中的項目沒有出現 —— **量測裝置可能撈錯案件**，先看這個。")
    assert _item_of(payload, dead) is None, (
        "已停用的項目出現在清單裡：%r\n" % _item_of(payload, dead)
        + "📌 `create_award` 用的是 `WHERE is_active = 1`，兩邊要同一條。")


# ══════════════════════════════════════════════════════════════════════
# ③ 不變量：plan 說的人，就是實際發到的人
# ══════════════════════════════════════════════════════════════════════

def test_bn1_the_base_comes_from_the_same_place_as_the_base_endpoint(
        client, make_user):
    """🔴 **`plan` 的 `base` 與 `GET /base/{quote_no}` 必須同一個來源。**

    ⚠️ 兩支各算一次而算法漂移的話，**畫面顯示的基數與實際入帳的基數會不同**
       —— 而兩個數字都「看起來合理」。

    ## 🔴 我第一版釘錯欄位了（B 退回，留著這一列）

    ```
    我寫    r2.json().get("amount")
    實際    /base 回 {"quote_no", "ok", "base_amount", "error"}（bonus.py:160）
    ⇒ get("amount") **恆為 None** ⇒ 這一題只有在 plan 的 amount 也是 None 時才綠
    ⇒ 而那正是規格禁止的東西
    ```
    🔑 值得記的不是「拼錯一個鍵」：`SPEC-BN1-PLAN §1` 的範例裡 `plan` 用 `amount`、
      `/base` 用 `base_amount`，**兩邊本來就不同名** ——
      而我把「名字對不起來」寫成了一個叫「來源對不起來」的斷言。

    ⚙️ 改法用**第三點**（B 給的三條路裡的第二條）：兩邊都比對 `base_amount_for()`
      的實算值 ⇒ **兩邊一起漂移時也抓得到**（只比對彼此的話，一起錯就一起綠）。
    """
    from modules.payroll.bonus import base_amount_for

    net = 123456
    _seed_case("MQ-BN1-BASE", net_profit=net, sales_person="alice")
    _u, hdr = _hdr(client, make_user, "bn1_mgr5")

    ok, expected, _err = base_amount_for(
        {"summary": {"netProfit": net}})
    assert ok and expected == net, (
        "`base_amount_for()` 對 netProfit=%d 回 %r ——\n" % (net, (ok, expected))
        + "**量測裝置的第三點自己壞了**，先修這個。")

    plan = _plan(client, hdr, "MQ-BN1-BASE").json()
    r2 = client.get("/api/bonus/base/MQ-BN1-BASE", headers=hdr)
    assert r2.status_code == 200, "既有的 `/base` 端點壞了：%s" % r2.text[:200]

    base = plan.get("base") or {}
    assert isinstance(base, dict), "`base` 應該是一包 {ok, amount, error}：%r" % base
    assert r2.json().get("base_amount") == expected, (
        "`/base` 回的基數 %r ≠ `base_amount_for()` 實算的 %r —— "
        "**既有端點就不對了**，先看它。"
        % (r2.json().get("base_amount"), expected))
    assert base.get("amount") == expected, (
        "`plan` 的基數 %r ≠ `base_amount_for()` 實算的 %r\n"
        % (base.get("amount"), expected)
        + "☠️ 畫面顯示的基數與實際入帳的基數不同，**而兩個都看起來合理**。\n"
        + "📌 `plan` 的鍵是 `base.amount`、`/base` 的鍵是 `base_amount` ——\n"
          "   **兩邊本來就不同名**，這一題比的是值不是名字。")


def test_bn1_the_plan_really_calls_base_amount_for(client, make_user,
                                                   monkeypatch):
    """🔴 **`plan` 要**呼叫** `base_amount_for()`，不是自己算出一個一樣的數字。**

    ## ☠️ 上一題（兩邊相等）**抓不到這件事**，突變證明過

    ```
    突變 P6  把 plan 的 base 改成在端點裡直接讀 settlement.summary.netProfit
    結果    **活下來** —— 因為今天兩邊算出來一樣
    ```
    ⚠️ 而 B 指出一個更糟的版本：突變若改在 `_settlement_of()` 那一層，
       `plan` 與 `/base` **會一起變** ⇒ 連「兩邊相等」都還是綠的。
    🔑 ⇒ 要釘的是**同源**這件事本身，而同源是「**那個函式真的被呼叫到**」，
      不是「兩個數字現在一樣」。

    ## ⚙️ 觀測點：換掉那支函式，看回應會不會跟著變

    給 `base_amount_for` 一個回傳**不可能自然出現**的值（`77`），
    而 `netProfit` 是 `123456` ⇒
    ```
    回 77      => 它真的呼叫了那支函式           ✅
    回 123456  => 它**自己算**，只是今天算出一樣  ☠️
    ```
    📌 這個哨兵值同時是**呼叫次數**的證據：沒被呼叫就取不到 `77`。
    """
    import modules.payroll.api.bonus as rb

    net, sentinel = 123456, 77
    _seed_case("MQ-BN1-SRC", net_profit=net, sales_person="alice")
    _u, hdr = _hdr(client, make_user, "bn1_src")

    calls = []

    def _fake(settlement):
        calls.append(settlement)
        return True, sentinel, None

    monkeypatch.setattr(rb, "base_amount_for", _fake)
    payload = _plan(client, hdr, "MQ-BN1-SRC").json()

    assert calls, (
        "`plan` 一次都沒有呼叫 `base_amount_for()` ——\n"
        + "☠️ 那表示基數是它**自己算**的 ⇒ 有人改算式的那天，\n"
          "   畫面顯示的基數與實際入帳的基數會分岔，**而兩個都看起來合理**。")
    got = (payload.get("base") or {}).get("amount")
    assert got == sentinel, (
        "我把 `base_amount_for()` 換成回 %r，而 `plan` 仍然回 %r（= netProfit）——\n"
        % (sentinel, got)
        + "☠️ 它呼叫了那支函式，**而沒有用它的回傳值**。\n"
        + "⚠️ 這比完全不呼叫更難發現：呼叫次數的斷言會綠。")


def test_bn1_the_remainder_cannot_see_a_total_that_is_too_big():
    """⚙️ **反向控制：`remainder_of()` 抓不到 `total_pct` 超額，別拿它當觀測點。**

    A-2 實跑、我複跑（`base = 123456`）：
    ```
    Σperson_pct 超額（兩人各 100%）
      pool=61728   Σamount=123456   remainder_of = **-61728**   看得見 ✅
    total_pct 超額（20000 ＝ 200%）
      pool=246912（= base×2）  Σamount=246912  remainder_of = **0**  看不見 ❌
    ```
    🔑 而 `split_award()` docstring 的兩條不變量在後者**也都成立**：
    ```
    Σamount <= pool         246912 <= 246912  ✅
    pool - Σamount < 人數    0 < 1             ✅
    ```
    ☠️ **因為 `pool` 本身被撐大了，而不變量拿 `pool` 當基準** ——
       *一個以受污染的值為基準的檢查，永遠不會發現污染。*
    ⇒ 兩種超額要兩個觀測點：
    ```
    Σperson_pct 超額  ->  remainder_of() < 0  可以
    total_pct   超額  ->  **必須拿 base 當基準**（或直接斷言端點回 400）
    ```
    ## 🔴 而盲點有**兩半**，不是一半（A-2 補的）

    ```
    total_pct 超額(20000)   改變 pool -> remainder **0**       看不見
    total_pct 為負(-5000)   改變 pool -> remainder **0**       看不見
    Σperson_pct 超額        **不改 pool** -> remainder -61728  唯一看得見的
    ```
    > **`remainder_of()` 只看得見 `person_pct` 那一側的錯，**
    > **因為那是唯一不改變 `pool` 的那一側。**

    ☠️ 只釘超額那一半的話，**負值那一半更容易被誤以為已經覆蓋了**。

    ## ⚙️ 這一題的**死亡條件**

    ```
    它紅的那天 = 盲點消失了（remainder_of 開始抓得到）
    => **刪掉這一題**，不是改期望值
    ```
    🔑 一個釘住缺陷的 characterization test **必須自帶死亡條件**，
      否則它會反過來**擋住修好它的那個改動** —— 而那時它看起來像一道正當的守門。
      而改期望值是最省力的動作，所以要明著禁止它。
    """
    from modules.payroll.bonus import pool_for, remainder_of, split_award

    base = 123456
    for total in (BP * 2, -5000):
        lines = split_award(base, total, [("a", BP)])
        assert remainder_of(base, total, lines) == 0, (
            "`remainder_of()` 在 `total_pct=%d` 時回了非 0 ——\n" % total
            + "✅ 它現在抓得到了，那是好事 ⇒ **刪掉這一整題**。\n"
            + "❌ **不要改期望值** —— 這一題釘的是一個盲點，\n"
              "   盲點消失了它就沒有存在理由了。")
    assert pool_for(base, BP * 2) > base, (
        "`pool_for(base, 20000)` 沒有超過 `base` —— **前提變了**，\n"
        + "上面整段推理要重做。")
    assert pool_for(base, -5000) < 0, (
        "`pool_for(base, -5000)` 不是負的了 —— **前提變了**。")


@pytest.mark.parametrize("base", [1, 7, 100, 101, 123456, 999999, 87654321])
def test_bn1_the_unit_is_basis_points_in_both_directions(base):
    """🔴 **`10000` 基點 = 全額，`100` 基點 = 1%。**

    🔑 兩條抓的是**相反的兩個方向**：
    ```
    ① 單位被實作成 // 100   => pool_for(base, 10000) 變成 base×100  => ① 紅
    ③ 單位被呼叫端當成百分比 => 100 被當 100% 而實際是 1%           => ③ 紅
    ```
    ⇒ 兩條都**不依賴 `base` 整除**（前提只有 `base >= 1`；
      我掃 `b = 0~2000`，只有 `b = 0` 讓 ③ 不成立）。

    ☠️ **不要寫成 `pool(5000) == pool(50) * 100`** ——
      `pool` 是整數無條件捨去，7 個 base 有 4 個會紅，
      **而紅燈指向 `split_award()`，那支是對的**。
    """
    from modules.payroll.bonus import pool_for

    assert pool_for(base, BP) == base, (
        "`pool_for(%d, 10000)` = %r，應該等於 `base` 本身。\n"
        % (base, pool_for(base, BP))
        + "☠️ 值變成 100 倍 ⇒ 單位被實作成百分比（`// 100`）。")
    assert pool_for(base, 100) == base // 100, (
        "`pool_for(%d, 100)` = %r，應該是 `base // 100`（1%%）。"
        % (base, pool_for(base, 100)))
    assert pool_for(base, 100) != base, (
        "`pool_for(%d, 100)` 等於 `base` ——\n" % base
        + "☠️ `100` 被當成「100%%」了，而它是 **1%**。\n"
        + "🔑 送 `50` 想表達 50%% 的人會拿到應得的 1/100，\n"
          "   **而畫面上那是一個格式正確的金額**。")
