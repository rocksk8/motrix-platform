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

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn3_a_deactivated_person_is_not_paid_on_a_new_award、test_bn3_a_manual_item_pays_the_people_it_lists、test_bn3_a_manual_item_with_nobody_is_refused、test_bn3_an_unknown_username_is_refused_and_named
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
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


def test_bn5_no_profit_and_no_settlement_are_two_different_reasons(client,
                                                                   make_user):
    """🔴🔴 **「沒賺錢」與「精算是舊格式」是兩件事 —— 一個沒出路，一個有。**

    ## 🔴 A-2 推翻了他自己的數字，而那個成因正是這一題要釘的

    ```
    ❌ 落檔兩次   「9 筆已結案裡有 1 筆 netProfit <= 0」
    ✅ 逐筆打開   **8 筆全是正的**；差的那筆 netProfit = **None**
                 （summary 是空的 `{}`，而 status=finalized）
    成因  CAST(netProfit AS REAL) > 0 數的，而 **CAST(NULL AS REAL) > 0 是 NULL**
    ```
    🔑 **「沒有值」被讀成了「值是 0 或負數」** —— 而它被落檔兩次都沒有人發現。
    📌 那正是〈null 不等於 0〉，而這一次它發生在**統計查詢**裡。

    ## ⇒ 兩態的下一步完全不同

    ```
    netProfit <= 0   **沒有出路** —— 就是沒賺錢，標「無可分配基數」
    summary 空／缺欄位 **有出路** —— `base_amount_for()` 已經有那句可操作的話：
        「…請重新開啟並儲存一次該案的精算，系統會自動補算淨利後即可發放。」
    ```
    ☠️ 合成一句的話，**有出路的那個人不知道自己有出路** ——
       他會以為那個案子就是不能發，而其實他只要去按一次儲存。
    ⚙️ 而訊息要**用既有那一句**，不可以自己寫一句新的（規則只有一份）。
    """
    from modules.payroll.bonus import LEGACY_SETTLEMENT_MESSAGE

    _seed_case("MQ-BN5-LOSS", 0)
    _seed_case("MQ-BN5-NOSUM", 0)
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE quotations SET data_json = ? WHERE quote_no = ?",
            (json.dumps({"settlement": {"status": "finalized",
                                        "summary": {}}}), "MQ-BN5-NOSUM"))
        conn.commit()
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "bn5_two")
    items = _candidates(client, hdr).json()
    items = items.get("items") if isinstance(items, dict) else items
    by_no = {(x.get("quote_no") or x.get("quoteNo")): x for x in items}

    loss, nosum = by_no.get("MQ-BN5-LOSS"), by_no.get("MQ-BN5-NOSUM")
    assert loss is not None and nosum is not None, (
        "兩種案件至少一種被濾掉了（現有：%r）——\n" % sorted(by_no)
        + "☠️ 濾掉的那一種，使用者只會看到選單裡沒有它。")

    r_loss = str(loss.get("reason") or loss.get("note") or "")
    r_nosum = str(nosum.get("reason") or nosum.get("note") or "")
    assert r_loss and r_nosum, "兩種都要說出原因：%r ／ %r" % (loss, nosum)
    assert r_loss != r_nosum, (
        "「沒賺錢」與「精算是舊格式」用了**同一句話**：%r\n" % r_loss
        + "☠️ 一個**沒有出路**，一個**有出路** ——\n"
          "   合成一句的話，有出路的那個人不知道自己有出路，\n"
          "   他會以為那個案子就是不能發，**而其實他只要去按一次儲存**。")
    assert "重新開啟並儲存" in r_nosum, (
        "「精算是舊格式」那一筆沒有給出路：%r\n" % r_nosum
        + "📌 `base_amount_for()` 已經有那句可操作的話 ——\n"
          "   **用既有那一句，不要自己寫一句新的**（規則只有一份）：\n"
          "   %r" % LEGACY_SETTLEMENT_MESSAGE)


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

def test_bn3_the_existing_sources_do_not_change_behaviour(client, make_user):
    """⚙️ **正對照：既有四個來源不可以因為多了 `manual` 而改變行為。**

    ☠️ 最容易踩的是「把 `people_for_item` 改成先查新表」——
       那會讓既有來源在新表為空時回 `(False, [], …)` ⇒ **全部發不出去**。
    ⚙️ 這一題不碰新表，直接走既有的 `sales_person` 那一條。
    """
    from modules.payroll.bonus import people_for_item

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

#: `BN4` 的白名單（hichan-61 2026-09-24，使用者裁「現在做完；白名單逐檔改」）。
#: 該改的：獎金模組五檔 ＋ 兩支共用 helper 裡**只在註解**提到它的兩檔。
_BN4_TARGETS = (
    "backend/modules/payroll/bonus.py", "backend/modules/payroll/api/bonus.py", "backend/modules/payroll/bonus_pdf.py",
    "frontend/js/bonus.js", "frontend/pages/bonus.html",
    "backend/helpers/edit_log.py", "backend/helpers/tiered_approval.py",
)
#: 🔴 不該改的（釘住「沒動」，一次機械取代會讓這幾格紅）：
#:   `archive.py` 的 `"獎金單":` 是每日 JSON 匯出的**表標籤鍵**（資料格式，不是畫面文字）
#:   `db.py` 是鎖定檔，那 6 處全在 migration 的 docstring／註解（凍住的歷史）
_BN4_UNTOUCHED = {"backend/archive.py": 2, "backend/db.py": 6}
#: 🔴 使用者原話裡的「獎金單」**不改**：那是逐字引用，改了就不是原話了。
#:   ⇒ 這幾處要**數得出來而且不變**：取代時若連原話一起改，這個數字會掉。
#: 2026-09-24：11 → 3。減少的 8 處全部來自被改寫的舊 `frontend/js/bonus.js`（3）與
#: `frontend/pages/bonus.html`（5）——SPEC-BONUS §十一 把頁面整頁換成以案件為中心的新頁面，
#: 舊頁面裡引用使用者原話的註解隨舊頁面一起移除（不是把原話裡的「獎金單」改掉）。
#: `modules/payroll/api/bonus.py` 的 3 處不變。以同一個掃描器比對 master（f57740b）與分支得出。
_BN4_VERBATIM_QUOTES = 3


def _bn4_in_user_quote(src, pos):
    """`pos` 是否落在「使用者原話」的引號裡（可跨行；連續的「…」「…」視為同一段原話）。"""
    op = src.rfind("「", 0, pos)
    if op < 0 or src.rfind("」", 0, pos) > op:
        return False
    first = op
    while True:
        back = src[:first].rstrip()
        if not back.endswith("」"):
            break
        prev = src.rfind("「", 0, len(back) - 1)
        if prev < 0:
            break
        first = prev
    return "原話" in src[max(0, first - 12):first]


def _bn4_scan(root, rel):
    import re
    src = (root / rel).read_text(encoding="utf-8", errors="replace")
    stale, quoted = [], []
    for m in re.finditer(re.escape(OLD_NAME), src):
        where = "%s:%d" % (rel, src[:m.start()].count("\n") + 1)
        (quoted if _bn4_in_user_quote(src, m.start()) else stale).append(where)
    return stale, quoted


def test_bn4_the_user_facing_name_changed_everywhere(client, make_user):
    """🔴 **`BN4`：「獎金單」→「獎金分潤單」，白名單逐檔改。**

    驗收（使用者裁）：**該改的 0 處、不該改的沒動**。
    ```
    該改的     `_BN4_TARGETS` 裡、使用者原話以外的「獎金單」 => 0
    不該改的   ① 使用者原話裡的             => 恰好 `_BN4_VERBATIM_QUOTES` 處
               ② archive.py（資料鍵）／db.py（鎖定檔、凍住的歷史）=> 次數不變
    ```
    ⚠️ `modules/payroll/api/bonus.py` 的稽核訊息寫進 `audit_log` ⇒ **既有紀錄不回頭改**
       （那是改寫稽核紀錄）—— 這一題只看原始碼。
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[4]
    stale, quoted = [], []
    for rel in _BN4_TARGETS:
        assert (root / rel).is_file(), "`%s` 不見了 —— **退回給我**。" % rel
        s_, q_ = _bn4_scan(root, rel)
        stale += s_
        quoted += q_
    assert not stale, (
        "還有 %d 處寫著「%s」：%r\n" % (len(stale), OLD_NAME, stale[:12])
        + "📌 `BN4`：使用者看得到的字與註解都要改成「%s」" % NEW_NAME
        + "（留著舊名，下一個人 grep 只找得到一半）。")
    assert len(quoted) == _BN4_VERBATIM_QUOTES, (
        "使用者原話裡的「%s」有 %d 處，預期 %d：%r\n"
        % (OLD_NAME, len(quoted), _BN4_VERBATIM_QUOTES, quoted)
        + "☠️ 變少 ⇒ 取代把**原話**也改了（那就不是原話了）；"
          "變多 ⇒ 有人新增了引用，確認後更新常數並寫理由。")
    for rel, n in _BN4_UNTOUCHED.items():
        got = (root / rel).read_text(encoding="utf-8").count(OLD_NAME)
        assert got == n, (
            "`%s` 的「%s」從 %d 處變成 %d 處 —— 這一檔**不在白名單**。\n" % (rel, OLD_NAME, n, got)
            + "archive.py 的是 JSON 匯出的表標籤鍵；db.py 是鎖定檔與 migration 歷史。")
