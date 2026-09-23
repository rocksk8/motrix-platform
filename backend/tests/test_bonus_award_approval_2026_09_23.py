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

    ⚙️ `status=` 可覆蓋（預設 `"草稿"`）—— `⑬⑭` 要種「已核准」的單才測得到
       `mark-paid` 的正常路徑，而其餘欄位（`voucher_no_payment` 等）走 `**cols`。
    """
    import db
    status = cols.pop("status", "草稿")
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
            (quote_no, 100000, status, "seed", "2026-09-01", "2026-09-01")
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
    """把 `bonus` 的簽核流程設成 `len(names)` 層，每層一個人。

    回 `{username: 該使用者的 headers}` —— **呼叫端要用哪一層簽核，
    直接拿這裡的 headers，不要再叫一次 `_hdr()` 對同一個名字重建帳號**。

    ## 🔴 我第一版回的是 `[username, ...]`，而三個呼叫端都拿它去重建帳號

    ```
    _set_flow() 裡面已經 _hdr(...) 建過這個使用者
    呼叫端又 _hdr(client, make_user, signers[0])
    => make_user() 再 INSERT 一次同一個 username
    => sqlite3.IntegrityError: UNIQUE constraint failed: users.username
    ```
    🔑 B 已用獨立探針驗證過三個場景背後的產品邏輯全部正確 ——
       **紅燈訊息是 SQL 寫的，是我的裝置壞了，不是產品**（同我自己寫的
       那一條：紅燈訊息若是框架／SQL 寫的，通常是探針壞了）。
       改成回傳已經登入好的 headers，呼叫端直接複用即可。
    """
    approvers = []
    headers_by_name = {}
    for name in names:
        u, h = _hdr(client, make_user, name)
        headers_by_name[u] = h
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
    return headers_by_name


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

    for n, (who, shdr) in enumerate(signers.items()):
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

    s1 = signers["bn8_r1"]
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
    s1 = signers["bn8_v1"]
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


# ══════════════════════════════════════════════════════════════════════
# ⑬⑭ 「已發放」的退路：手動標記（`§235`／`SPEC-BN8.md §5c`）
# ══════════════════════════════════════════════════════════════════════
#
# A-2 `6a84536` ＋ A `STATE.md §246` 定案：
# ```
# ⑬ POST /api/bonus/awards/{award_id}/mark-paid
#    superadmin／body {reason} 不可空
#    🔴 不碰 voucher_no_payment（不可偽造傳票號）
#    三個擋：reason 空／已 is_paid／status 非「已核准」
# ⑭ is_paid() 住 helpers/bonus.py（純邏輯，查詢端與端點都要用）
# ```
# 🔴 動工前已查 `void_award`（同檔、同權限級別、同一種「理由不可空」形狀）——
#    `A-2` 與我都標過「沒查」，那一句已落進 B 的派工（`STATE.md §247`）。
#
# ⚙️ **路徑用 `openapi.json` 找**，不釘字串（A 明著要求）：
#    B 若換了路徑，這裡的題不必跟著改，只是找不到時訊息要講清楚
#    「這是還沒實作」不是「探針壞了」。

#: 三條路徑的「動作代號」候選 —— `mark-paid` 是規格定案的名字，
#: 其餘是防止 B 用了慣用的變體（連字號／底線）而讓探針誤判成「沒做」。
MARK_PAID_CANDIDATES = ("mark-paid", "mark_paid", "paid")


def _find_award_action_path(client, candidates):
    """從 `openapi.json` 找 `/awards/{award_id}/<action>` 那一支 POST 路徑。

    找不到就**明著說是規格哪一節定的**，不要讓 404/405/422 變成一個要猜的謎題。
    """
    r = client.get("/openapi.json")
    assert r.status_code == 200, "讀不到 openapi.json：%s" % r.text[:200]
    spec = r.json()
    paths = spec.get("paths") or {}
    for cand in candidates:
        hits = [p for p, methods in paths.items()
                if "/bonus/awards/" in p
                and p.rstrip("/").endswith("/" + cand)
                and "post" in methods]
        if hits:
            assert len(hits) == 1, "找到多支符合的路徑，分不出來打哪一支：%r" % hits
            return hits[0]
    # 🔑 找不到精確匹配時，印出所有含 "paid" 的路徑當線索 —— 不要空手回報。
    near = sorted(p for p in paths if "paid" in p.lower())
    pytest.fail(
        "`openapi.json` 裡找不到 `/awards/{id}/%s` 這一支 POST 端點"
        "（候選名 %r 都沒中）。\n" % (candidates[0], list(candidates))
        + "📌 路徑由 `SPEC-BN8.md §5c` 定案為 `mark-paid`，B 換路徑要回報。\n"
        + ("🔎 含 \"paid\" 的既有路徑：%r（若這是它，退回改本檔的候選清單）"
           % near if near else "🔎 目前沒有任何路徑含 \"paid\"。"))


def _mark_paid_url(path, aid):
    """把 openapi 的樣板路徑（`{award_id}` 或任何名字的 `{...}`）代入實際 id。"""
    return re.sub(r"\{[^}]+\}", str(aid), path)


def test_bn8_mark_paid_endpoint_requires_superadmin(client, make_user):
    """🔴 **`§5c`／`⑬`：手動標記已發放，只有最高管理者。**

    ⚙️ 與三支簽核端點（`§6⑤`）同一條權限級別 —— 錢的事，非管理者不可以碰。
    """
    path = _find_award_action_path(client, MARK_PAID_CANDIDATES)
    _u, hdr = _hdr(client, make_user, "bn8_paid_perm", role="admin")
    aid = _seed_award("MQ-BN8-PAIDPERM", ["someone"], status="已核准")
    r = client.post(_mark_paid_url(path, aid), headers=hdr,
                    json={"reason": "臨時現金"})
    assert r.status_code in OK_CODES, (
        "`mark-paid` 回 %s（預期 403）：%s" % (r.status_code, r.text[:200]))
    assert r.status_code == 403, (
        "`admin` 打 `mark-paid` 拿到 %s，而 `§5c` 是**superadmin 專屬**。\n"
        % r.status_code
        + "☠️ 錢的事一旦非管理者也能標記，「已發放」這個狀態就不可信了。")


def test_bn8_mark_paid_requires_a_non_empty_reason(client, make_user):
    """🔴 **`§5c` 界線②：原因不可為空。**（同 `BN1` person_source 為空不准儲存）

    ☠️ 空字串存得下去 ⇒ 日後沒有人回得出那筆錢為什麼走系統外。
    ⚙️ 前置：單要先是「已核准」，否則會紅在錯誤的那一個擋（狀態，不是原因）。
    """
    path = _find_award_action_path(client, MARK_PAID_CANDIDATES)
    _u, hdr = _hdr(client, make_user, "bn8_paid_reason")
    aid = _seed_award("MQ-BN8-PAIDREASON", ["someone"], status="已核准")
    r = client.post(_mark_paid_url(path, aid), headers=hdr, json={"reason": ""})
    assert r.status_code in OK_CODES, (
        "空原因回 %s（預期 400）：%s" % (r.status_code, r.text[:200]))
    assert r.status_code == 400, (
        "空原因拿到 %s，而 `§5c` 界線②是**必填**。\n" % r.status_code
        + "☠️ 空字串存得下去的話，日後沒有人回得出那筆錢為什麼走系統外。")


def test_bn8_mark_paid_is_refused_before_approval(client, make_user):
    """🔴 **狀態擋：還沒「已核准」的單不可以標記已發放。**

    ⚙️ 前置：`reason` 給好給滿，孤立出**只有狀態不對**這一個變因 ——
       否則紅了分不出是狀態擋還是原因擋。
    """
    path = _find_award_action_path(client, MARK_PAID_CANDIDATES)
    _u, hdr = _hdr(client, make_user, "bn8_paid_status")
    aid = _seed_award("MQ-BN8-PAIDSTATUS", ["someone"])  # 預設「草稿」
    r = client.post(_mark_paid_url(path, aid), headers=hdr,
                    json={"reason": "臨時現金"})
    assert r.status_code in OK_CODES, (
        "草稿狀態下標記已發放回 %s（預期 400）：%s"
        % (r.status_code, r.text[:200]))
    assert r.status_code == 400, (
        "還沒核准的單被標記成已發放，回 %s。\n" % r.status_code
        + "☠️ 錢還沒核定金額就先說發出去了 —— 順序反了。")


def test_bn8_mark_paid_is_refused_when_already_paid_via_the_main_path(
        client, make_user):
    """🔴🔴 **`§5c` 界線③的另一半：已經走主路發放的單，不可以再手動標記。**

    ## ⚙️ 用主路（`voucher_no_payment`）種「已發放」，不是用手動欄位

    ```
    手動欄位（paid_manually_*）今天還不存在 => 種不出「手動已發放」的前置
    voucher_no_payment 今天就有             => 拿它種「已發放」測「已 is_paid」這個擋
    ```
    🔑 這**同時**驗到了 `⑭` 的一半：`is_paid()` **必須認得主路**，
       不是只認自己剛加的那個手動欄位 —— 否則主路發放過的單還能被手動標記，
       一張單就有兩條「已發放」的記錄互相打架。
    """
    path = _find_award_action_path(client, MARK_PAID_CANDIDATES)
    _u, hdr = _hdr(client, make_user, "bn8_paid_twice")
    aid = _seed_award("MQ-BN8-PAIDTWICE", ["someone"], status="已核准",
                      voucher_no_payment="V-2026-0099")
    r = client.post(_mark_paid_url(path, aid), headers=hdr,
                    json={"reason": "臨時現金"})
    assert r.status_code in OK_CODES, (
        "已透過傳票發放的單再標記，回 %s（預期 400）：%s"
        % (r.status_code, r.text[:200]))
    assert r.status_code == 400, (
        "已經走主路發放的單，手動標記還是回 %s。\n" % r.status_code
        + "☠️ 一張單同時有傳票號**又**手動標記 ⇒ 兩條「已發放」互相打架，\n"
          "   而 `is_paid()` 若只認自己的欄位就會漏掉這一格。")

    # ⚙️ 若 `is_paid()` 已存在，順手驗它對這張單本身也回 True ——
    #    這一格失敗代表 `⑭` 沒接上主路，是另一個成因，不要跟上面混在一起。
    try:
        from helpers.bonus import is_paid
    except ImportError:
        pytest.fail("`helpers.bonus` 裡沒有 `is_paid`，先看 `⑭` 那一題。")
    a = _award(client, hdr, aid)
    assert is_paid(a) is True, (
        "`is_paid()` 對一張 `voucher_no_payment` 非空的單回 %r。\n"
        % is_paid(a)
        + "☠️ 主路發放的單被判定成「還沒發放」——\n"
          "   查詢「已發放的單」時這一張會消失（`§5c` 界線③）。")


def test_bn8_marking_paid_succeeds_and_never_fabricates_a_voucher_number(
        client, make_user):
    """🔴🔴 **正常路徑：標記成功，而 `voucher_no_payment` 仍然是空的。**

    ## 🔴 `§5c` 逐字：**不可以偽造一個傳票號**

    ```
    自動回填  voucher_no_payment = 'V-xxxx'   <= 有傳票號，可追
    手動標記  voucher_no_payment = **''**      <= 沒有傳票號，另外記
    ```
    ☠️ 兩條路若寫進同一個欄位而分不出來，手動那條就變成
       一個**繞過帳務的合法入口**（〈降級之後它還是會動〉）。
    ⚙️ 而「記在哪」用 `_award()`（走 `GET /awards`，`list_awards` 是
       `SELECT *` 投影 ⇒ 新欄位一落地就看得到，不必直接讀資料庫）。
    """
    path = _find_award_action_path(client, MARK_PAID_CANDIDATES)
    _u, hdr = _hdr(client, make_user, "bn8_paid_ok")
    aid = _seed_award("MQ-BN8-PAIDOK", ["someone"], status="已核准")

    reason = "客戶現場臨時以現金支付"
    r = client.post(_mark_paid_url(path, aid), headers=hdr,
                    json={"reason": reason})
    assert r.status_code == 200, "標記失敗：%s %s" % (r.status_code,
                                                    r.text[:200])

    a = _award(client, hdr, aid)
    assert not (a.get("voucher_no_payment") or ""), (
        "標記成功之後 `voucher_no_payment` 是 %r。\n"
        % a.get("voucher_no_payment")
        + "☠️ **偽造了一個傳票號** —— 手動標記的這一筆錢從此看起來像有真的\n"
          "   傳票，而查帳的人追不到那張不存在的憑證。")

    by_ = a.get("paid_manually_by")
    at_ = a.get("paid_manually_at")
    stored_reason = a.get("paid_manually_reason")
    assert by_ and at_, (
        "標記成功而讀不到「誰標的／何時」（by=%r, at=%r）。\n" % (by_, at_)
        + "🔑 `§5c` 的設計重點不是「允許」，是「**看得出它走的是退路**」——\n"
          "   沒有這兩格，這筆錢的來源事後查不出來。")
    assert stored_reason == reason, (
        "存下來的原因是 %r，我送的是 %r。\n" % (stored_reason, reason)
        + "☠️ 原因對不上，`§5c` 界線②要求的「事後回得出為什麼」就落空了。")

    from helpers.bonus import is_paid
    assert is_paid(a) is True, (
        "手動標記成功之後，`is_paid()` 對這張單回 %r。\n" % is_paid(a)
        + "☠️ 標記路徑與 `is_paid()` 對不上 —— 查詢「已發放的單」時\n"
          "   **這一張手動標記的會消失**（`§5c` 界線③逐字警告的就是這個）。")


def test_bn8_is_paid_is_false_for_a_genuinely_unpaid_award():
    """⚙️ **正對照：`is_paid()` 對一張真的還沒發放的單要回 `False`。**

    ☠️ 少了它，一個「永遠回 `True`」的實作也會讓上面幾題全綠
       （它們都在驗「已發放時擋下來／記得住」，沒有一題驗「沒發放時不擋」）。
    🔑 純邏輯測試，不碰資料庫 —— 與 `people_for_item`／`split_award` 同一種寫法。
    """
    try:
        from helpers.bonus import is_paid
    except ImportError:
        pytest.fail(
            "`helpers.bonus` 裡沒有 `is_paid`。\n"
            + "📌 `SPEC-BN8.md §5c`／`STATE.md §246`：`is_paid()` 要住在\n"
              "   `helpers/bonus.py`（純邏輯），不要放進 router。")
    unpaid = {"voucher_no_payment": "", "paid_manually_at": ""}
    assert is_paid(unpaid) is False, (
        "一張兩個欄位都是空字串的單，`is_paid()` 回 %r（預期 `False`）。\n"
        % is_paid(unpaid)
        + "☠️ 一個永遠回 `True` 的實作會讓「擋下已發放的單」那幾題全部通過，\n"
          "   而它們一次都沒有驗過「沒發放時不擋」。")
