# -*- coding: utf-8 -*-
"""`BN8` · 獎金分潤單成為**第九個** doc type（`SPEC-BN8.md`）。

# 現況實查（2026-09-23，`modules/payroll/api/bonus.py`）

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

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn8_an_approved_award_can_still_be_voided、test_bn8_mark_paid_endpoint_requires_superadmin、test_bn8_mark_paid_is_refused_before_approval、test_bn8_mark_paid_is_refused_when_already_paid_via_the_main_path、test_bn8_mark_paid_requires_a_non_empty_reason、test_bn8_marking_paid_succeeds_and_never_fabricates_a_voucher_number、test_bn8_reject_clears_the_signing_slots_but_not_the_maker、test_bn8_submitting_builds_a_chain_as_deep_as_the_setting、test_bn8_submitting_moves_it_out_of_draft、test_bn8_the_three_endpoints_are_superadmin_only、test_bn8_three_different_people_can_sign_all_the_way、test_bn8_voiding_a_paid_award_is_refused_and_says_how
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
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
    root = pathlib.Path(__file__).resolve().parents[3]
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


def test_bn8_is_paid_is_false_for_a_genuinely_unpaid_award():
    """⚙️ **正對照：`is_paid()` 對一張真的還沒發放的單要回 `False`。**

    ☠️ 少了它，一個「永遠回 `True`」的實作也會讓上面幾題全綠
       （它們都在驗「已發放時擋下來／記得住」，沒有一題驗「沒發放時不擋」）。
    🔑 純邏輯測試，不碰資料庫 —— 與 `people_for_item`／`split_award` 同一種寫法。
    """
    try:
        from modules.payroll.bonus import is_paid
    except ImportError:
        pytest.fail(
            "`modules.payroll.bonus` 裡沒有 `is_paid`。\n"
            + "📌 `SPEC-BN8.md §5c`／`STATE.md §246`：`is_paid()` 要住在\n"
              "   `modules/payroll/bonus.py`（純邏輯），不要放進 router。")
    unpaid = {"voucher_no_payment": "", "paid_manually_at": ""}
    assert is_paid(unpaid) is False, (
        "一張兩個欄位都是空字串的單，`is_paid()` 回 %r（預期 `False`）。\n"
        % is_paid(unpaid)
        + "☠️ 一個永遠回 `True` 的實作會讓「擋下已發放的單」那幾題全部通過，\n"
          "   而它們一次都沒有驗過「沒發放時不擋」。")
