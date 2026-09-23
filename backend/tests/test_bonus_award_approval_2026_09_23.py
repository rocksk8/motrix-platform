# -*- coding: utf-8 -*-
"""`BN8` · 獎金分潤單成為**第九個** doc type（`SPEC-BN8.md`）。

# 現況實查（2026-09-23，`routers/bonus.py`）

```
端點        /items  /items(POST)  /base  /awards/plan  /awards  /awards(POST)
            /awards/{id}/void
            ⇒ **沒有 submit／approve／reject**
狀態        建立時寫 '草稿'，而 UPDATE bonus_awards 全 repo 只有一處
            且只寫 voided_* ⇒ **status 建立之後從來不會改**
doc type    APPROVAL_DOC_TYPES 八個，**沒有 bonus**
```

# ⚠️ 本檔**不寫**的三格 —— 規格沒有宣告路徑，我不自己發

```
⑨⑩ 簽核佇列＋完整性守門  => A 另開了 **`AS3`**（`STATE.md:29076`），不在本檔
⑪  送審後不可改比例      => `§3` 只宣告三支端點，**改的那一支沒有路徑**
⑬  手動標記已發放        => 同上，端點未宣告（`§5c` 只給了三個新欄位名）
⑭  is_paid()             => 規格沒說它住哪一支模組
```
📌 那三格**已回報 A**。〈兩個都對而路不存在〉：裁定落地要問「誰是第一個呼叫者」。

# ⚠️ 套用範圍登記表會再紅一次

`bonus` 進 `APPROVAL_DOC_TYPES` 之後，`test_approval_flow_scope.py` 的
`EXPECTED_SCOPE` 會少一行。**那一行不是我加** —— A 說他會問使用者。
"""
import json
import re

import pytest

AWARDS = "/api/bonus/awards"
FLOW = "/api/settings/approval-flow/%s"

#: `§166`：走到端點才會出現的狀態碼。三種「不存在」的臉是 404／405／422。
OK_CODES = (200, 400, 403)

#: `§1`：獎金分潤單的 doc type 代號。⚠️ 改了**退回給我**。
BONUS_DOC_TYPE = "bonus"

#: `§6①`：標籤。⚠️ 這是 `SPEC-BN8.md §3` 定的字，改了**退回給 A**。
BONUS_LABEL = "獎金分潤單"

#: `§5d`／`§6⑫`：退回要清掉的是**簽核那幾格**。
#:
#: ☠️ **不是「每一格」** —— 「製表」那一格留的是 `created_by`（建檔人，
#:    不是簽核），寫成「每一格」會**紅在一個正確的實作上**（B 2026-09-23 指出，
#:    A-2 的原判準已於 `43297ff` 修正）。
#: 🔑 〈判準的寬窄都會騙人〉的寬那一側：超集（三格）比對象（兩格）寬
#:    ⇒ 它會去指控別人的碼。
#:
#: 🔴 **「製表」與 `JV2` 的「製票」是刻意不同的兩個字，兩個都對**（A-2 複核）：
#: ```
#: 傳票      製單人在會計上就叫「製票」
#: 獎金分潤單 不是傳票 => 叫「製表」
#: ```
#: ⚠️ 若有人要把兩邊統一成同一個字，答案是**刻意不同** ——
#:    統一之後其中一邊會**紅在正確實作上**。
MAKER_SLOT = "製表"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role,
                     modules=modules if modules is not None else ["reports"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ?",
                           (username,)).fetchone()
        assert row is not None, "找不到使用者 %r" % username
        return int(row["id"])
    finally:
        conn.close()


def _ta():
    import helpers.tiered_approval as ta
    return ta


def _seed_award(quote_no, people, **cols):
    """種一張獎金單。`people` 是拿到錢的人。回 `award_id`。

    🔴 `bonus_award_lines.bonus_item_id` 有**外鍵** ⇒ 先種真的 `bonus_items`
       （`BN9` 踩過：直接餵 `1` 會 `FOREIGN KEY constraint failed`，
        而訊息指向資料層，看起來像產品壞了）。
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
        extra_cols = "".join(", %s" % k for k in cols)
        extra_qs = ", ?" * len(cols)
        cur = conn.execute(
            "INSERT INTO bonus_awards (quote_no, base_amount, status,"
            " created_by, created_at, updated_at, voided_at%s)"
            " VALUES (?,?,?,?,?,?,''%s)" % (extra_cols, extra_qs),
            (quote_no, 100000, "草稿", "seed", "2026-09-01", "2026-09-01")
            + tuple(cols.values()))
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


def _act(client, hdr, aid, action, body=None):
    """走 `§3` 宣告的那三條路之一。

    ⚠️ `§166`：端點不存在在這個 repo 有**三種臉** ——
    ```
    404  StaticFiles 接走 GET
    405  StaticFiles 接走非 GET
    422  被同 prefix 的 path param 吃掉
    ```
    ⇒ 三種都要當成「還沒有這支端點」，不要讓它變成一個內容斷言的謎題。
    """
    r = client.post("%s/%s/%s" % (AWARDS, aid, action), json=body or {},
                    headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`POST %s/{id}/%s` 還不存在（回 %s）。\n" % (AWARDS, action,
                                                       r.status_code)
            + "📌 路徑是 `SPEC-BN8.md §3` 宣告的，改了**退回給我**。")
    return r


def _award(client, hdr, aid):
    """從 `GET /awards` 把那一張撈回來。**走 API**，不直接讀資料庫。"""
    r = client.get(AWARDS, headers=hdr)
    assert r.status_code == 200, "讀不到獎金清單：%s" % r.text[:200]
    for a in r.json().get("awards") or []:
        if int(a.get("id") or 0) == int(aid):
            return a
    pytest.fail("清單裡找不到 id=%s 的獎金單。現有：%r"
                % (aid, [a.get("id") for a in r.json().get("awards") or []]))


def _slots(a):
    """把簽核格整理成 `{格名: {"by":…, "at":…}}`；讀不出來回 `None`。

    ## ⚙️ 觀測點在**輸出**，不在欄位（`§6⑫` 逐字）

    > 只驗「某個欄位被清了」的題，**在真相搬家的那天會變成綠的而缺陷還在**。

    🔑 `JV2` 就是這麼壞的：`send_back_voucher` 清了 v99 那六欄而沒碰
      `approval_json`，而斷言釘的是欄位 ⇒ 保護沒了而題目照樣綠。
    ⚠️ 四種鍵名都收；都不是的話**退回給我**，不要改題目。

    ## 🔴 **本檔刻意沒有「攤平欄位」的 fallback**（`JV2` 那一支有）

    ```
    JV2   傳票有 v99 六欄          => _slots() 收攤平與包成一包兩種
    BN8   獎金單**一格都沒有**      => 只收 nested
          （SPEC §1 逐字：簽核鏈是唯一的來源，沒有投影欄位要維護）
    ```
    🔑 **寬容的探針藏起受測物的偏離**（A-2 複核逐字）——
      加了 fallback ⇒ 它同時接受兩種形狀 ⇒ **它就不再偵測形狀了**，
      而那場「該用哪一種形狀」的對話**永遠不會發生**。
    📌 〈探針與被測對象糾纏〉的反面。

    ⚠️ **而代價要付在訊息上**：找到攤平欄位時要說出「我找到的是哪一種」，
       否則那幾題的紅燈會被當成「B 的實作有 bug」去追 ——
       而真正該發生的是一次**關於形狀**的對話。
    """
    nested = (a.get("signatures") or a.get("signoffs")
              or a.get("approvals") or a.get("sign_slots"))
    if not nested:
        # ⚠️ 釘的是**傳票那一種形狀本身**，不是「任何 `_by` 結尾的欄位」。
        #    ```
        #    寬的寫法  re.search(r"_(by|at)$", k) 扣掉 created/updated/voided
        #              => `§5c` 的 paid_manually_at 一落地就**誤觸**
        #    窄的寫法  只認 v99 那幾個名字 ＋ 第 N 層的形狀
        #    ```
        #    🔑 〈判準的寬窄都會騙人〉：這個分支是要說「B 用了傳票的形狀」，
        #      而超集會讓它去指控一個不相干的新欄位。
        flat = sorted(k for k in a
                      if str(k) in ("checked_by", "checked_at",
                                    "manager_by", "manager_at",
                                    "submitted_by", "submitted_at")
                      or re.match(r"^tier\d+_(by|at)$", str(k)))
        if flat:
            pytest.fail(
                "獎金單上找到**攤平的簽核欄位**：%r\n" % flat
                + "而 `SPEC-BN8.md §1` 要的是**只讀 `approval_json`** ——\n"
                  "   獎金單一格投影欄位都沒有，那正是它比傳票乾淨的地方。\n"
                + "🔑 **這不是功能缺陷，是形狀不符** ⇒ **退回問 B**，\n"
                  "   不要替這支探針加 fallback（加了它就不再偵測形狀了）。")
        return None
    if isinstance(nested, dict):
        return nested
    return {s.get("slot"): s for s in nested if isinstance(s, dict)}


def _sign_slots(slots):
    """簽核那幾格 —— **扣掉「製表」**。"""
    return {k: v for k, v in (slots or {}).items() if k != MAKER_SLOT}


def _chain(a):
    """`approval_json` 的鏈。`§1`：`DEFAULT '{}'` ⇒ 沒有鏈只有一種寫法。"""
    raw = a.get("approval_json")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw or "{}")
        except ValueError:
            return {}
    return a.get("approval") or {}


def _tiers_of(a):
    c = _chain(a)
    for k in ("tiers", "layers", "levels"):
        if isinstance(c.get(k), list):
            return c[k]
    return None


def _set_flow(client, hdr, make_user, names):
    """把 `bonus` 的簽核流程設成 `len(names)` 層，每層一個人。回那些帳號。"""
    approvers = []
    for name in names:
        u, _h = _hdr(client, make_user, name)
        approvers.append({"userId": _user_id(u), "username": u,
                          "displayName": u})
    r = client.put(FLOW % BONUS_DOC_TYPE, headers=hdr, json={
        "includeSubmitterManagerTier": False,
        "tiers": [{"approvers": [a]} for a in approvers]})
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`PUT %s` 回 %s —— `bonus` 還不是一個 doc type。\n"
            % (FLOW % BONUS_DOC_TYPE, r.status_code)
            + "📌 先看 `test_bn8_bonus_is_a_declared_doc_type`。")
    assert r.status_code == 200, "存簽核設定失敗：%s %s" % (r.status_code,
                                                          r.text[:200])
    return [a["username"] for a in approvers]


# ══════════════════════════════════════════════════════════════════════
# ① `bonus` 要成為第九個 doc type
# ══════════════════════════════════════════════════════════════════════

def test_bn8_bonus_is_a_declared_doc_type():
    """🔴 **`§6①`：`bonus` 要進 `APPROVAL_DOC_TYPES`，標籤是「獎金分潤單」。**

    ⚙️ 標籤那一格不是裝飾：設定頁上**三個 doc type 都叫 voucher**，
       而它們是三種不同的單據 —— 分不出來的那一天改錯的是**別人的流程**。
    """
    ta = _ta()
    assert BONUS_DOC_TYPE in ta.APPROVAL_DOC_TYPES, (
        "`APPROVAL_DOC_TYPES` 裡沒有 %r，現有 %d 個：%r\n"
        % (BONUS_DOC_TYPE, len(ta.APPROVAL_DOC_TYPES), ta.APPROVAL_DOC_TYPES)
        + "☠️ 不是 doc type ⇒ `resolve_active_flow_setting()` 讀不到它的設定\n"
          "   ⇒ 送審時**建不出鏈**，整條流程沒有起點。")
    label = ta.APPROVAL_DOC_TYPE_LABELS.get(BONUS_DOC_TYPE)
    assert label == BONUS_LABEL, (
        "標籤是 %r，而 `SPEC-BN8.md §3` 定的是 %r。\n" % (label, BONUS_LABEL)
        + "📌 改字**退回給 A** —— 設定頁上看得懂才不會改錯別人的流程。")


def test_bn8_bonus_does_not_join_the_unified_default(client, make_user):
    """🔴 **`§7③`（A 裁）：`bonus` 不進 `DEFAULT_UNIFIED_DOC_TYPES`。**

    ```
    進了   => 獎金單與報價單／出貨單**共用同一條簽核鏈**
              而改那一條的人不會知道自己也改了獎金
    不進   => 自己一條 bonus_approval_flow
    ```
    🔑 依據是**可逆性**：勾一下就合併；而反過來（預設合併之後要拆開）
      **要先有人發現它們被合在一起了**。猜錯的代價不對稱時先做可逆的那一邊。

    ⚙️ **正對照**：`quotation` 必須**在**裡面 —— 否則這一題在
       `DEFAULT_UNIFIED_DOC_TYPES` 被整個清空時也會綠。
    """
    ta = _ta()
    assert "quotation" in ta.DEFAULT_UNIFIED_DOC_TYPES, (
        "正對照壞了：`quotation` 不在 `DEFAULT_UNIFIED_DOC_TYPES` 裡（%r）。\n"
        % sorted(ta.DEFAULT_UNIFIED_DOC_TYPES)
        + "⚠️ **這一題現在量不到東西** —— 集合空掉的話下面那個斷言自動成立。")
    assert BONUS_DOC_TYPE not in ta.DEFAULT_UNIFIED_DOC_TYPES, (
        "%r 被放進 `DEFAULT_UNIFIED_DOC_TYPES` 了：%r\n"
        % (BONUS_DOC_TYPE, sorted(ta.DEFAULT_UNIFIED_DOC_TYPES))
        + "☠️ 獎金單會**預設跟著統一流程走**，而那個方向不可逆 ——\n"
          "   要拆開得先有人發現它們被合在一起了（A `§234` 裁）。")


# ══════════════════════════════════════════════════════════════════════
# ② 送審建鏈：**層數 == 設定的層數**
# ══════════════════════════════════════════════════════════════════════

def test_bn8_submitting_builds_a_chain_as_deep_as_the_setting(client,
                                                              make_user):
    """🔴🔴 **`§6②`：送審之後鏈的層數要等於設定的層數。**

    ## ⚙️ 觀測方式是「**把設定改成三層**再送審」，不是「兩層時能過」

    ```
    只驗兩層 => 寫死兩層 與 讀設定 **結果一模一樣** ⇒ 分不出來
    改成三層 => 寫死的那個實作**立刻露餡**
    ```
    ☠️ 而 A-2 實讀四把 key：現存的**全部都是 2 層或 0 層**
       ⇒ 三層以上的路從來沒有被跑過。
    """
    _u, hdr = _hdr(client, make_user, "bn8_chain")
    _set_flow(client, hdr, make_user, ("bn8_c1", "bn8_c2", "bn8_c3"))
    aid = _seed_award("MQ-BN8-CHAIN", ["someone"])

    r = _act(client, hdr, aid, "submit")
    assert r.status_code in OK_CODES, "送審回 %s：%s" % (r.status_code,
                                                        r.text[:200])
    assert r.status_code == 200, "送審失敗：%s %s" % (r.status_code,
                                                    r.text[:200])

    a = _award(client, hdr, aid)
    tiers = _tiers_of(a)
    assert tiers is not None, (
        "送審之後讀不到簽核鏈。`approval_json` 是 %r，現有鍵：%r\n"
        % (a.get("approval_json"), sorted(a))
        + "📌 `§1`：欄位是 `approval_json TEXT NOT NULL DEFAULT '{}'`，\n"
          "   與 `extra_expense` 完全同形 ⇒ `tiered_approval` 原樣可用。")
    assert len(tiers) == 3, (
        "設定三層，而鏈有 %d 層：%r\n" % (len(tiers), tiers)
        + "☠️ 層數**寫死**了 —— 兩層時它與讀設定的實作長得一模一樣，\n"
          "   而公司把流程改成三層的那一天，第三層的人**永遠等不到**。")


def test_bn8_submitting_moves_it_out_of_draft(client, make_user):
    """🔴 **送審之後狀態要真的變。**（`§2`：草稿 → 待審核）

    ☠️ 這一格是整張票的根：`UPDATE bonus_awards` 全 repo 只有一處
       且只寫 `voided_*` ⇒ **status 建立之後從來不會改**。
    ⚙️ 而這一題與上一題**壞的方式不同**：
    ```
    鏈建對了而 status 沒動 => 畫面上它還是草稿，**沒有人知道它在等簽**
    status 動了而鏈是空的 => 簽核人打開它，**不知道自己是第幾層**
    ```
    """
    _u, hdr = _hdr(client, make_user, "bn8_status")
    _set_flow(client, hdr, make_user, ("bn8_s1",))
    aid = _seed_award("MQ-BN8-STATUS", ["someone"])

    before = _award(client, hdr, aid).get("status")
    assert before == "草稿", "前置不對：種出來的單是 %r 不是草稿。" % before

    assert _act(client, hdr, aid, "submit").status_code == 200
    after = _award(client, hdr, aid).get("status")
    assert after != "草稿", (
        "送審之後狀態還是 %r。\n" % after
        + "☠️ 畫面上它還是草稿 ⇒ **沒有人知道它在等簽核**。")


# ══════════════════════════════════════════════════════════════════════
# ③ 三個不同的人依序簽完
# ══════════════════════════════════════════════════════════════════════

def test_bn8_three_different_people_can_sign_all_the_way(client, make_user):
    """🔴🔴 **`§6③`：三個不同的人依序簽；簽完最後一層 → 已核准。**

    ## ⚙️ 三格正對照照抄 `AS2`（A 批准）

    ```
    ① 三層**走得完**        <= 不是「鏈是三層」——那只證明我把設定抄進去了
    ② 簽核格數 == 1 ＋ 層數  <= 版面**從資料算列數**（製表不算層）
    ③ 第四次要被擋且不是 500 <= `currentTier` 無上限往前加會撞 IndexError
    ```
    ☠️ 少了 ③，一個「無上限往前加」的實作也會讓 ① 綠。
    📌 **三個不同的人**是刻意的 —— 既有那題是 cascade 自簽，
       涵蓋不到「換人」那一段。
    """
    _u, hdr = _hdr(client, make_user, "bn8_walk")
    signers = _set_flow(client, hdr, make_user,
                        ("bn8_w1", "bn8_w2", "bn8_w3"))
    aid = _seed_award("MQ-BN8-WALK", ["someone"])
    assert _act(client, hdr, aid, "submit").status_code == 200, "送審失敗"

    for n, who in enumerate(signers):
        _u2, shdr = _hdr(client, make_user, who)
        ar = _act(client, shdr, aid, "approve")
        assert ar.status_code == 200, (
            "第 %d 層由 %r 簽核失敗：%s %s\n"
            % (n + 1, who, ar.status_code, ar.text[:200])
            + "☠️ 三層以上的推進邏輯**從來沒有被跑過** ——\n"
              "   紅在這裡多半是既有的推進邏輯，不是 `BN8` 的新碼。")

    a = _award(client, hdr, aid)
    assert a.get("status") == "已核准", (
        "簽了三次而狀態是 %r —— 三層沒有走完。" % a.get("status"))

    slots = _slots(a)
    assert slots is not None, (
        "讀不到簽核格（找過四種鍵名）。現有鍵：%r" % sorted(a))
    assert len(slots) == 1 + 3, (
        "設定三層，而簽核格有 %d 格：%r\n" % (len(slots), slots)
        + "☠️ 版面**沒有從資料算列數** —— 第三層的人簽了，\n"
          "   而**紙上沒有他的格子**。\n"
        + "🔑 不變量是「格數 == 1 ＋ 層數」（製表不算層），\n"
          "   不是任何一個字面標籤。")

    extra = _act(client, hdr, aid, "approve")
    assert extra.status_code in (400, 403), (
        "**第四次**簽核回 %s：%s\n" % (extra.status_code, extra.text[:200])
        + "☠️ 500 的話多半是 `currentTier` 無上限往前加 ⇒ `tiers[3]`\n"
          "   撞成 `IndexError` —— 而上面那三次照樣綠。")


# ══════════════════════════════════════════════════════════════════════
# ④ 退回：回草稿 ＋ 清掉簽核那幾格（**而「製表」不清**）
# ══════════════════════════════════════════════════════════════════════

def test_bn8_reject_clears_the_signing_slots_but_not_the_maker(client,
                                                               make_user):
    """🔴🔴 **`§6④`＋`§6⑫`：退回 → 回草稿，簽核那幾格被清掉。**

    ## 🔴 而判準**不可以**寫成「每一格 `by` 都是空的」

    ```
    製表  created_by   <= **建檔人**，不是簽核；退回之後他還是建檔人
    覆核  第 1 層       <= 要清
    主管  第 2 層       <= 要清
    ```
    ☠️ 寫成「每一格」⇒ **紅在一個正確的實作上**（B 2026-09-23 指出）。
    🔑 〈判準的寬窄都會騙人〉的寬那一側：超集比對象寬 ⇒ 它會去指控別人的碼。

    ## ⚙️ 而這一題必須**先真的簽一格下去**

    ```
    只 submit 就 reject => 那幾格本來就是空的 ⇒ 清不清都綠
    ```
    ☠️ `JV2` 今天就是這麼壞的，而它**在一片綠裡看不出來**
       （〈假綠燈〉的「清單為空」那一支）。
    ⇒ 下面先斷言「退回之前它是有值的」：**那一格才是量測基準**。
    """
    _u, hdr = _hdr(client, make_user, "bn8_rej")
    signers = _set_flow(client, hdr, make_user, ("bn8_r1", "bn8_r2"))
    aid = _seed_award("MQ-BN8-REJ", ["someone"])
    assert _act(client, hdr, aid, "submit").status_code == 200, "送審失敗"

    _u2, s1 = _hdr(client, make_user, signers[0])
    assert _act(client, s1, aid, "approve").status_code == 200, "第一層簽核失敗"

    signed = _slots(_award(client, hdr, aid))
    assert signed is not None, "簽完第一層仍讀不到簽核格。"
    assert any((v or {}).get("by") for v in _sign_slots(signed).values()), (
        "簽完第一層而簽核那幾格還是空的：%r\n" % signed
        + "⚠️ **這一題量不到東西了** —— 下面的「退回要清掉簽核」\n"
          "   會變成一個清不清都綠的斷言。先修這裡。")

    r = _act(client, hdr, aid, "reject", {"reason": "比例算錯了"})
    assert r.status_code == 200, "退回失敗：%s %s" % (r.status_code,
                                                     r.text[:200])

    a = _award(client, hdr, aid)
    assert a.get("status") == "草稿", (
        "退回之後狀態是 %r，而 `§5d` 是**回草稿**。\n" % a.get("status")
        + "☠️ 不回草稿的話，被退回的人**改不動它**。")

    after = _slots(a) or {}
    for slot, cell in _sign_slots(after).items():
        assert not ((cell or {}).get("by") or ""), (
            "退回之後「%s」那一格還留著 %r。\n" % (slot, (cell or {}).get("by"))
            + "☠️ 單子上有簽名，**而那個人沒有看過這一版** ——\n"
              "   退回是要改內容的，改完還帶著上一輪的簽名就是冒簽。")

    maker = (after.get(MAKER_SLOT) or {}).get("by")
    assert maker, (
        "退回之後「%s」那一格也被清掉了（%r）。\n" % (MAKER_SLOT, maker)
        + "🔑 它留的是 `created_by`（**建檔人**不是簽核）⇒ 退回不該動它。\n"
        + "⚙️ 少了這一格，一個「全部清光」的實作也會讓上面那個迴圈綠 ——\n"
          "   而那時退回之後**沒人知道這張單是誰建的**。")


# ══════════════════════════════════════════════════════════════════════
# ⑤ 權限：三支端點只有 superadmin，**而可見性不跟著收緊**
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("action", ["submit", "approve", "reject"])
def test_bn8_the_three_endpoints_are_superadmin_only(client, make_user,
                                                     action):
    """🔴 **`§6⑤`：三支端點一律 `require_superadmin=True`。**

    ```
    使用者逐字：「產生獎金分潤單這些也只有最高管理員可見」
    而 _is_manager() 回 role in ("superadmin", **"admin"**)
       —— 那支 docstring 自己標了「未經使用者確認」
    ⇒ 現在確認了。
    ```
    """
    _u, hdr = _hdr(client, make_user, "bn8_perm_%s" % action,
                   role="admin")
    aid = _seed_award("MQ-BN8-PERM-%s" % action, ["someone"])
    r = _act(client, hdr, aid, action, {"reason": "x"})
    assert r.status_code in OK_CODES, (
        "`%s` 回 %s（預期 403）：%s" % (action, r.status_code, r.text[:200]))
    assert r.status_code == 403, (
        "`admin` 打 `%s` 拿到 %s，而 `§6⑤` 是 **403**。\n"
        % (action, r.status_code)
        + "☠️ `admin` 簽得動獎金流程 ⇒ 使用者那句「只有最高管理員」沒有落地。")


def test_bn8_an_employee_still_sees_their_own_award(client, make_user):
    """⚙️ **正對照：`§6⑤` 的另一半 —— `GET /awards` 不可以一起收緊。**

    ☠️ 少了它，一個「整個模組都只給 superadmin」的實作會讓上面三題全綠，
       **而員工看不到自己領多少**。
    🔑 「誰能操作」與「誰能看見」是兩個問題 —— 這個模組**已經分開了**，
      不要合併（A `§234` 明著擋下這個做法）。
    📌 使用者那句話自己就分開了：前半是可見性、後半是操作入口。
    """
    staff, shdr = _hdr(client, make_user, "bn8_staff", role="user")
    aid = _seed_award("MQ-BN8-SEE", [staff])
    r = client.get(AWARDS, headers=shdr)
    assert r.status_code == 200, (
        "一般員工讀不到獎金清單（%s）：%s\n" % (r.status_code, r.text[:200])
        + "☠️ `GET /awards` 被一起收緊了 ⇒ **員工看不到自己領多少**。")
    ids = {int(a.get("id") or 0) for a in r.json().get("awards") or []}
    assert aid in ids, (
        "員工看不到自己有份的那一張（%s）：%r\n" % (aid, ids)
        + "☠️ 同上 —— 他收到一筆錢而**查不到來源**。")


# ══════════════════════════════════════════════════════════════════════
# ⑥ migration：只加欄位，**不 UPDATE 任何一列**
# ══════════════════════════════════════════════════════════════════════

def test_bn8_the_migration_only_adds_a_column(client, make_user):
    """🔴 **`§4`：migration 只 `ALTER TABLE`，不碰既有那一列。**

    ```
    正式 DB  1 筆（id=1, status='草稿', voided_at=''）
    ```
    ⚙️ **不是**去驗「有幾筆」—— 驗那一筆**沒有被動過**。
    而測試 DB 裡沒有那一筆 ⇒ 觀測點只能放在**原始碼**：
    加 `approval_json` 的那段 migration 裡不可以出現 `UPDATE bonus_awards`。

    🔴 而 migration 也不可以呼叫會演進的 helper
       （〈凍住的歷史不要呼叫活的程式碼〉）：
    ```
    ❌ migration 裡呼叫 setting_to_active_tiers() 去補鏈
       => 歷史被回溯改寫，而症狀只出現在「完整降版再升版」那條路上
          —— 那條路就是**全新安裝與災難還原**
    ```

    ⚙️ **正對照**：先確認真的找到了那段 migration。
       找不到而直接說「沒有 UPDATE」是〈我找不到 X〉的第一種壞法。
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "db.py").read_text(encoding="utf-8", errors="replace")

    hits = [m for m in re.finditer(
        r"ALTER TABLE bonus_awards ADD COLUMN\s+approval_json", src)]
    assert hits, (
        "`db.py` 裡找不到「替 `bonus_awards` 加 `approval_json`」的 migration。\n"
        + "📌 `§1` 逐字照抄 `v101`：\n"
          "     PRAGMA table_info 先查 -> ALTER TABLE ... DEFAULT '{}'\n"
        + "⚠️ **這一題的正對照就是它** —— 找不到 migration 就沒有資格\n"
          "   說「它沒有 UPDATE」。")

    # 🔑 取那一段 migration 函式的範圍：從它前面最近的 `def ` 到下一個 `def `。
    start = src.rfind("\ndef ", 0, hits[0].start())
    end = src.find("\ndef ", hits[0].end())
    body = src[start:end if end > 0 else len(src)]

    bad = re.findall(r"UPDATE\s+bonus_awards", body)
    assert not bad, (
        "那段 migration 裡有 %d 處 `UPDATE bonus_awards`。\n" % len(bad)
        + "☠️ 既有那一筆草稿會被回溯改寫 —— 而 `DEFAULT '{}'` 對它\n"
          "   本來就是正確的（沒有鏈 ＝ 還沒送審）。")
    called = re.findall(r"setting_to_active_tiers|resolve_active_flow_setting",
                        body)
    assert not called, (
        "那段 migration 呼叫了 %r。\n" % sorted(set(called))
        + "☠️ 〈凍住的歷史不要呼叫活的程式碼〉：helper 會演進，\n"
          "   而症狀只出現在「完整降版再升版」那條路上 ——\n"
          "   **那條路就是全新安裝與災難還原**。")


# ══════════════════════════════════════════════════════════════════════
# ⑦⑧ 作廢
# ══════════════════════════════════════════════════════════════════════

def test_bn8_an_approved_award_can_still_be_voided(client, make_user):
    """🔴 **`§6⑦`（A 裁）：任何狀態都可以作廢，含已核准。**

    🔑 沿用傳票那一條，理由相同：**不留出路的後果是「開錯了而改不掉」**。
    ⚙️ 而這一題要走到「已核准」才算數 —— 用草稿去作廢驗不到那件事。
    """
    _u, hdr = _hdr(client, make_user, "bn8_void")
    signers = _set_flow(client, hdr, make_user, ("bn8_v1",))
    aid = _seed_award("MQ-BN8-VOID", ["someone"])
    assert _act(client, hdr, aid, "submit").status_code == 200, "送審失敗"
    _u2, s1 = _hdr(client, make_user, signers[0])
    assert _act(client, s1, aid, "approve").status_code == 200, "簽核失敗"
    assert _award(client, hdr, aid).get("status") == "已核准", (
        "前置不對：簽完一層而狀態不是已核准。")

    r = client.post("%s/%s/void" % (AWARDS, aid), headers=hdr,
                    json={"reason": "金額算錯，重開一張"})
    assert r.status_code == 200, (
        "已核准的單作廢回 %s：%s\n" % (r.status_code, r.text[:200])
        + "☠️ 不留出路 ⇒ **一張開錯的已核准獎金單從此沒有出路**。")


def test_bn8_voiding_a_paid_award_is_refused_and_says_how(client, make_user):
    """🔴 **`§6⑧`（A 裁）：已發放的單，作廢要回 400 並講出沖銷。**

    ```
    只寫 voided_at 的後果：**帳上那筆錢還在，而獎金單說它作廢了**
    ⇒ 作廢要開一張沖銷傳票，而沖銷流程**本規格不做**
    ```
    ⚠️ 今天要**自己種** `voucher_no_payment` 才測得到（零寫入端）。
    📌 **而那正是現在寫下來的理由：接線的那一天沒有人會想起這一格。**

    ⚙️ 訊息要講得出出路 —— 一句「不可作廢」讓使用者卡在那裡。
    """
    _u, hdr = _hdr(client, make_user, "bn8_paid")
    aid = _seed_award("MQ-BN8-PAID", ["someone"],
                      voucher_no_payment="V-2026-0001")

    r = client.post("%s/%s/void" % (AWARDS, aid), headers=hdr,
                    json={"reason": "想作廢"})
    assert r.status_code in OK_CODES, (
        "作廢回 %s：%s" % (r.status_code, r.text[:200]))
    assert r.status_code == 400, (
        "已發放的單作廢拿到 %s（預期 400）：%s\n" % (r.status_code,
                                                  r.text[:200])
        + "☠️ 錢已經出去了 —— 只寫一個旗標的話，**帳上那筆錢還在**，\n"
          "   而獎金單說它作廢了。")
    detail = (r.json() or {}).get("detail") or r.text
    assert "沖銷" in detail, (
        "擋下來了，而訊息沒有講出出路：%r\n" % detail[:200]
        + "🔑 一句「不可作廢」讓使用者**卡在那裡** —— 要講「請先開立沖銷傳票」。")
