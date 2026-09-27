# -*- coding: utf-8 -*-
"""`JV2` · 傳票**送審 → 簽核 → 過帳／退回／作廢**（A `§160` 路徑定案）。

```
POST /api/vouchers/{id}/submit      送審
POST /api/vouchers/{id}/approve     簽核通過
POST /api/vouchers/{id}/send-back   退回（**會升版成 -Rn**）
POST /api/vouchers/{id}/post        過帳
POST /api/vouchers/{id}/void        作廢
```
📌 退回叫 `/send-back` 不叫 `/reject`：**傳票退回會升版**，
   與既有那幾張單的「駁回」語意不同 —— 同名會讓人以為行為一樣。

---

# 🔴 一律走 `client`，**不准直接叫 helper**

A-2 實查：**8 支傳票測試有 7 支打 0 個 API** —— 直接叫 `helpers/voucher.py`
繞過 router ⇒ **規則全綠而沒有一條路走得到**。
🔑 〈兩個都對而路不存在〉：本檔每一題都從 HTTP 進去。

# 🔴 而簽核三格的時間戳，**欄位不存在**（B 讀使用者原話後指出）

使用者原話逐字有「**你還問過我審核日期等**」。而我實測 `vouchers_all` 19 個欄位：
```
時間戳只有  posted_at ／ voided_at ／ created_at ／ updated_at
沒有        送審、覆核、主管 各自的時間
簽核紀錄表  也沒有（只有 audit_log 與 approval_delegates，都不是）
```
📌 `SPEC-VOUCHER §106c` 明著寫三格簽名位**從簽核紀錄取，不可以從 `status` 欄推**
⇒ 本檔釘的是**不變量**：三格**各自**要有自己的人與時間，而且**從 API 讀得到**。
⚠️ 用欄位還是用一張簽核紀錄表**由 B 決定** —— 我不釘機制。
☠️ 而缺了它的症狀很具體：**單子印出來，三個簽名格有名字而沒有日期** ——
   而那正是使用者當初問的那件事。
"""
import re
from datetime import date

import pytest

#: `SPEC-VOUCHER §一` 的狀態機。
STATUSES = ("草稿", "待審核", "簽核中", "已核准", "已過帳")

#: `§160` 定案的五條路徑。⚠️ 改了 **退回給我**。
ACTIONS = ("submit", "approve", "send-back", "post", "void")

#: 三格簽名位（`§106c`）⇒ 每一格要有**人**與**時間**。
#:
#: 🔴 **格名對應**（B `_m099_voucher_signatures`，`vouchers_all` 的欄位）：
#: ```
#: 製票  created_by / created_at      <= 本來就有，**不另開第四組**
#: 覆核  checked_by / checked_at      <= 簽核第 1 層
#: 主管  manager_by / manager_at      <= 簽核第 2 層
#: ```
#: ⚠️ 另有 `submitted_by / submitted_at`＝**送審**（製票人自己按的），
#:    它不是三格簽名位之一 —— 版面上那三格印的是上面那三組。
#: 📌 我原本用中文格名去查（`sigs["覆核"]`），而 B 的鍵是英文 ⇒ 那一題紅在
#:    一個正確的實作上。A `§167` 判給我改：**釘的是不變量，欄位名是實作細節**。
SLOT_FIELDS = {
    "製票": ("created_by", "created_at"),
    "覆核": ("checked_by", "checked_at"),
    "主管": ("manager_by", "manager_at"),
}
SIGN_SLOTS = tuple(SLOT_FIELDS)

#: 🔴 **退回要清的只有簽核那幾格** —— `製票` 不算。
#:
#: ```
#: 製票  created_by  <= **建檔人**，不是簽核；退回之後他還是建檔人
#: 覆核  checked_by  <= 要清
#: 主管  manager_by  <= 要清
#: ```
#: ⚠️ 寫成「每一格 `by` 都是空的」會**紅在一個正確的實作上**：
#:    `製票` 那一格留的是 `created_by`，而它本來就不該被清。
#: 🔑 這是〈判準的寬窮都會騙人〉的寬那一側：
#:    超集（三格）比對象（兩格）寬 ⇒ 它會去指控別人的碼。
CLEARED_ON_SEND_BACK = ("覆核", "主管")

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _create(client, hdr, **kw):
    """建一張草稿。**走 API**，不直接寫資料庫。"""
    body = {"summary": "JV2", "lines": _LINES}
    body.update(kw)
    r = client.post("/api/vouchers", json=body, headers=hdr)
    if r.status_code in (404, 405):
        pytest.fail(
            "`POST /api/vouchers` 還不存在（回 %s）—— 這是 `JV1` 的紅，"
            "**本檔每一題都靠它**。" % r.status_code)
    assert r.status_code in (200, 201), (
        "建立草稿失敗：%s %s" % (r.status_code, r.text[:160]))
    j = r.json()
    return j.get("id") or j.get("voucher_id"), j


def _act(client, hdr, vid, action, body=None):
    """走 `§160` 定案的那五條路之一。**不再試探別的路徑**。"""
    r = client.post("/api/vouchers/%s/%s" % (vid, action),
                    json=body or {}, headers=hdr)
    if r.status_code in (404, 405):
        pytest.fail(
            "`POST /api/vouchers/{id}/%s` 還不存在（回 %s）。\n"
            % (action, r.status_code)
            + "⚠️ 路徑是 `§160` 定案的，改了 **退回給我**。")
    return r


def _get(client, hdr, vid):
    r = client.get("/api/vouchers/%s" % vid, headers=hdr)
    assert r.status_code == 200, "讀不回來：%s %s" % (r.status_code, r.text[:160])
    return r.json()


def _slots(v):
    """把三格簽核整理成 `{中文格名: {"by":…, "at":…}}`。

    兩種形狀都收：
    ```
    ① 攤平在傳票上   checked_by / checked_at …   <= B 走的這一種
    ② 包成一包       signatures / signoffs / approvals / sign_slots
    ```
    ⚠️ 用別的欄位名**退回給我**改 `SLOT_FIELDS`，不要改題目。
    """
    nested = (v.get("signatures") or v.get("signoffs")
              or v.get("approvals") or v.get("sign_slots"))
    if nested:
        if isinstance(nested, dict):
            return nested
        return {s.get("slot"): s for s in nested if isinstance(s, dict)}

    out = {}
    for slot, (by_k, at_k) in SLOT_FIELDS.items():
        if by_k in v or at_k in v:
            out[slot] = {"by": v.get(by_k), "at": v.get(at_k)}
    return out or None


def _slot_time(sigs, slot):
    """某一格的時間戳；**還沒簽**就回 `None`。

    🔴 六個欄位是 `TEXT NOT NULL DEFAULT ''` ⇒ **沒簽的那一格是空字串不是 NULL**。
    ```
    不正規化 => t1 = ''  ->  '' == ''  ->  ③ 無聲通過
    ```
    🔑 〈null 不等於 0〉在這裡的形狀是反的：這張表的「沒有值」就是 `''`，
       所以要把 `''` 收斂成 `None`，而**不是**用 `is None` 去分辨它們。
    """
    if not sigs:
        return None
    one = sigs.get(slot) if isinstance(sigs, dict) else next(
        (s for s in sigs if s.get("slot") == slot), None)
    if one is None:
        return None
    for k in ("at", "signed_at", "time"):
        if k in one:
            v = one[k]
            return None if v in ("", None) else v
    return None


# ══════════════════════════════════════════════════════════════════════
# ① 送審 → 簽核 → 過帳：狀態要真的往前走
# ══════════════════════════════════════════════════════════════════════

def test_jv2_submit_moves_a_draft_out_of_draft(client, make_user):
    """🔴 **送審之後它不再是草稿。**

    ⚠️ 觀測點是**再 GET 一次讀回來的 `status`**，不是送審那一支的回應：
    ```
    回應說「已送審」  => 那是一句話
    GET 讀回「待審核」 => **它真的落地了**
    ```
    ☠️ 只驗回應的話，一支「回 200 而什麼都沒改」的端點也會綠 ——
       而症狀是**使用者按了送審，單子還在草稿匣裡**。
    """
    _u, hdr = _hdr(client, make_user, "jv2_submit")
    vid, _ = _create(client, hdr)
    assert _get(client, hdr, vid)["status"] == "草稿", "新建的不是草稿。"

    r = _act(client, hdr, vid, "submit")
    assert r.status_code == 200, "送審失敗：%s %s" % (r.status_code, r.text[:160])

    after = _get(client, hdr, vid)["status"]
    assert after != "草稿", (
        "送審回 200，而 GET 讀回來仍然是「草稿」——\n"
        + "☠️ 使用者按了送審，**單子還在草稿匣裡**。")
    assert after in STATUSES, (
        "送審之後的狀態是 %r，而它不在 `§一` 的五個值裡：%s\n"
        % (after, list(STATUSES))
        + "🔑 多一個狀態 ⇒ 有人加了一個值而沒有人決定它的轉移規則。")


def test_jv2_a_draft_cannot_be_posted_directly(client, make_user):
    """🔴 **草稿不可以直接過帳** —— 必須先走完簽核（`§六②`）。

    ☠️ 少了這道擋：**一個人可以自己開單、自己過帳，中間沒有第二個人看過** ——
       而那正是簽核流程存在的理由。
    🔑 而它不會報錯：帳是平的、單號也對，**只是沒有人覆核過**。
    ⚙️ 而拒絕的理由要說得出是**狀態**不是別的（例如不平衡）——
       否則使用者會去改分錄，而問題不在那裡。
    """
    _u, hdr = _hdr(client, make_user, "jv2_direct")
    vid, _ = _create(client, hdr)

    r = _act(client, hdr, vid, "post")
    assert r.status_code >= 400, (
        "**草稿直接過帳成功了**（回 %s）——\n" % r.status_code
        + "☠️ 一個人可以自己開單、自己過帳，**中間沒有第二個人看過**。")
    assert re.search(r"草稿|已核准|狀態|簽核", r.text), (
        "擋下來了，而訊息沒說是**狀態**的問題：%s\n" % r.text[:200]
        + "☠️ 使用者會去改分錄 —— **而問題不在那裡**。")
    assert _get(client, hdr, vid)["status"] == "草稿", (
        "被擋下來了，而狀態已經被改掉了 ——\n"
        + "🔑 拒絕的路徑上不可以留下副作用。")


# ══════════════════════════════════════════════════════════════════════
# ② 退回：狀態回草稿 ＋ **單號升版**
# ══════════════════════════════════════════════════════════════════════

def test_jv2_send_back_returns_to_draft_and_bumps_the_revision(client,
                                                               make_user):
    """🔴🔴 **退回 ⇒ 回草稿 ＋ 單號升版 `-Rn` ＋ 清除簽核**（`§106c`）。

    📌 它叫 `/send-back` 不叫 `/reject`，**因為它會升版** ——
       與既有那幾張單的「駁回」語意不同，同名會讓人以為行為一樣。

    ⚙️ 三格都要，而**升版那一格最容易漏**：
    ```
    狀態回草稿    漏了 => 退回之後改不動
    單號升版      漏了 => **兩個版本共用一個單號** ⇒ 對不出改了什麼
    清除簽核      漏了 => 改完之後**還帶著上一版的簽名** ⇒ 簽的人沒看過新的內容
    ```
    ☠️ 第三格最安靜：單子上有簽名，而那個人沒有看過這一版。
    """
    _u, hdr = _hdr(client, make_user, "jv2_back")
    vid, created = _create(client, hdr)
    no0 = created.get("voucher_no") or created.get("voucherNo")

    assert _act(client, hdr, vid, "submit").status_code == 200

    # 🔴 **一定要先真的簽一格下去，否則第三格的斷言是空的。**
    #
    # ```
    # 只 submit 就 send-back => 覆核那一格本來就是 ''
    #                        => `assert not by` 清不清都會綠
    # ```
    # ☠️ 我第一版就是這樣，而它**在一片綠裡看不出來** ——
    #    〈假綠燈：斷言驗到自己設的值〉的「清單為空」那一支。
    # 🔑 所以下面先斷言「退回之前它是有值的」：**那一格才是量測基準**。
    assert _act(client, hdr, vid, "approve").status_code == 200
    signed = _slots(_get(client, hdr, vid)) or {}
    assert (signed.get("覆核") or {}).get("by"), (
        "簽核之後「覆核」那一格還是空的：%r\n" % signed
        + "⚠️ **這一題量不到東西了** —— 下面的「退回要清掉簽核」\n"
          "   會變成一個清不清都綠的斷言。先修這裡。")

    r = _act(client, hdr, vid, "send-back", {"reason": "科目挑錯了"})
    assert r.status_code == 200, "退回失敗：%s %s" % (r.status_code, r.text[:160])

    after = _get(client, hdr, vid)
    assert after["status"] == "草稿", (
        "退回之後狀態是 %r，而 `§106c` 是**回草稿**。\n" % after["status"]
        + "☠️ 不回草稿的話，被退回的人**改不動它**。")

    no1 = after.get("voucher_no")
    assert no1 != no0, (
        "退回前後單號都是 %r —— **沒有升版**。\n" % no0
        + "☠️ 兩個版本共用一個單號 ⇒ **對不出這一次改了什麼**，\n"
          "   而 `UNIQUE INDEX` 擋不住（它不報錯）。")
    assert re.search(r"-R\d+$", no1 or ""), (
        "升版之後的單號是 %r，而 `§一` 的形狀是 `…-Rn`。\n" % no1
        + "🔑 格式不對 ⇒ 下一次退回會變 `-R1-R1`（`quotations` 那一支的症狀）。")

    # 🔴 **第三格：清除簽核** —— docstring 寫了三格，
    #    而我原本**只斷言了兩格** ⇒ 第三格從來沒被驗過。
    # ☠️ 那是〈散文對工具是隱形的〉的另一種載體：
    #    意圖寫在 docstring 裡，**而紅綠不看 docstring**。
    sigs = _slots(after) or {}
    for slot in CLEARED_ON_SEND_BACK:
        cell = sigs.get(slot) or {}
        assert not (cell.get("by") or ""), (
            "退回之後「%s」那一格還留著 %r。\n" % (slot, cell.get("by"))
            + "☠️ 單子上有簽名，**而那個人沒有看過這一版** ——\n"
              "   退回是要改內容的，改完還帶著上一版的簽名就是冒簽。")

    # ⚙️ **反向控制：`製票` 那一格不可以被清掉。**
    #    少了它，一個「三格全清」的實作也會讓上面那個迴圈綠 ——
    #    而那時**退回之後沒人知道這張單是誰建的**。
    maker = (sigs.get("製票") or {}).get("by")
    assert maker, (
        "退回之後「製票」那一格也被清掉了（%r）。\n" % maker
        + "🔑 `created_by` 是**建檔人**不是簽核 ⇒ 退回不該動它。")


# ══════════════════════════════════════════════════════════════════════
# ③ 作廢：已過帳不可退回，只能作廢重開
# ══════════════════════════════════════════════════════════════════════

def test_jv2_a_posted_voucher_can_only_be_voided_not_sent_back(client,
                                                               make_user):
    """🔴 **已過帳不可退回 —— 只能作廢重開**（使用者裁示）。

    ```
    已過帳 ──退回──▶ ✗   ☠️ 帳上那一筆還在，而單據回到可編輯狀態
    已過帳 ──作廢──▶ ✅   原單留著，另開一張 —— **帳上看得到那一次作廢**
    ```
    ⚙️ 而這一題要走完整條路（草稿→送審→簽核→過帳），**全部走 API** ——
       直接改資料庫把狀態設成「已過帳」的話，驗到的不是這條路。
    """
    _u, hdr = _hdr(client, make_user, "jv2_void")
    vid, _ = _create(client, hdr)

    assert _act(client, hdr, vid, "submit").status_code == 200
    ap = _act(client, hdr, vid, "approve")
    assert ap.status_code == 200, "簽核失敗：%s %s" % (ap.status_code, ap.text[:160])
    st = _get(client, hdr, vid)["status"]
    if st != "已核准":
        # 分層簽核可能要簽不只一次 —— 再簽到底。
        for _ in range(4):
            if _get(client, hdr, vid)["status"] == "已核准":
                break
            _act(client, hdr, vid, "approve")
    assert _get(client, hdr, vid)["status"] == "已核准", (
        "簽核走不到「已核准」（現在是 %r）—— 後面兩格量不到。"
        % _get(client, hdr, vid)["status"])

    assert _act(client, hdr, vid, "post").status_code == 200, "過帳失敗。"
    assert _get(client, hdr, vid)["status"] == "已過帳"

    back = _act(client, hdr, vid, "send-back", {"reason": "想改"})
    assert back.status_code >= 400, (
        "**已過帳的傳票退回成功了**（回 %s）——\n" % back.status_code
        + "☠️ 帳上那一筆還在，而單據回到可編輯狀態。")

    v = _act(client, hdr, vid, "void", {"reason": "開錯了"})
    assert v.status_code == 200, (
        "已過帳的傳票**作廢不了**：%s %s\n" % (v.status_code, v.text[:160])
        + "⚙️ 這是正對照：少了它，「已過帳什麼都不准做」也會讓上面那格綠，\n"
          "   **而開錯的那一張從此沒有出路**。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 ④ 簽核三格各自要有時間戳（B 指出的欄位缺口）
# ══════════════════════════════════════════════════════════════════════

def test_jv2_each_signature_slot_has_its_own_person_and_timestamp(client,
                                                                  make_user):
    """🔴🔴 **製票／覆核／主管三格，各自要有「誰」與「什麼時候」。**

    使用者原話逐字：「**你還問過我審核日期等**」。
    而我實測 `vouchers_all` 的 19 個欄位，時間戳只有：
    ```
    posted_at ／ voided_at ／ created_at ／ updated_at
    ⇒ **送審、覆核、主管各自的時間都沒有**
    ⇒ 簽核紀錄表也沒有（只有 audit_log 與 approval_delegates，都不是）
    ```
    ☠️ 缺了它的症狀很具體：**單子印出來，三個簽名格有名字而沒有日期。**
    📌 `§106c` 明著寫三格**從簽核紀錄取，不可以從 `status` 欄推** ——
       ⇒ 本題釘**不變量**（三格各有人與時間、而且 API 讀得到），
         **用欄位還是用一張紀錄表由 B 決定**，我不釘機制。

    ⚙️ 而「時間」要是**各自的** —— 三格共用 `updated_at` 不算。

    ## 🔴 而我第一版的斷言（「三格時間不可以完全相同」）**會誤報**

    ```
    我的理由  共用一個時間 => 覆核與主管看起來同一秒簽的
    A 的反駁  小公司常常**同一個人連按兩次** => **真的會同一秒**
    ⇒ 我那個斷言會**紅在一個正確的實作上**
    ```
    🔑 **理由成立而斷言錯** —— 改成釘**欄位獨立**不是釘**值不相同**：
    ```
    ① 簽覆核 → GET → 記下覆核的時間戳 t1
    ② 簽主管 → GET
    ③ 覆核的時間戳**仍然是 t1**（沒被主管那一步改掉）
    ```
    ⇒ 它證明的正是我要的那件事（各有自己的欄位、不是共用 `updated_at`），
      **而同一秒簽兩格照樣綠**。
    📌 簽核是**兩層**（覆核第 1、主管第 2；製票是建立者不算層）——
       `§161` 裁定**不接**既有 `approval_settings`（那是承攬商匯款單那一套，
       接上去會讓層數變可設定，而使用者要的是固定三格）。
    """
    _u, hdr = _hdr(client, make_user, "jv2_sign")
    vid, _ = _create(client, hdr)
    assert _act(client, hdr, vid, "submit").status_code == 200

    # ① 第一層（覆核）
    assert _act(client, hdr, vid, "approve").status_code == 200
    t1 = _slot_time(_slots(_get(client, hdr, vid)), "覆核")
    assert t1 is not None, (
        "簽完第一層之後，`checked_at` 仍然是空的。\n"
        + "⚠️ 這一句擋的是**下面那一題的假綠燈** —— 欄位是 `NOT NULL DEFAULT ''`，\n"
          "   沒簽的那一格是**空字串**，`'' == ''` 會讓 ③ 無聲通過。")

    # ② 第二層（主管）
    assert _act(client, hdr, vid, "approve").status_code == 200
    v = _get(client, hdr, vid)

    # ③ 🔴 覆核那一格的時間**不可以被第二步改掉**
    t1_after = _slot_time(_slots(v), "覆核")
    assert t1_after == t1, (
        "簽了主管之後，**覆核那一格的時間也跟著變了**（%r → %r）。\n"
        % (t1, t1_after)
        + "☠️ 那表示兩格**共用同一個欄位**（多半是 `updated_at`）\n"
          "   ⇒ 版面上兩個簽名格永遠印同一個日期。\n"
        + "🔑 而它不會報錯 —— **兩格都有日期，只是那個日期不是各自簽的時間**。")

    sigs = _slots(v)
    assert sigs, (
        "讀回來的傳票裡沒有簽核三格（找過 `signatures` / `signoffs` / "
        "`approvals` / `sign_slots`）。現有鍵：%s\n" % sorted(v)
        + "☠️ 版面上那三格印不出來 —— 而使用者問過「**審核日期**」。\n"
        + "⚠️ 鍵名可以換（**退回給我**），而三格要有**各自的人與時間**。")

    times = []
    for slot in SIGN_SLOTS:
        one = sigs.get(slot) if isinstance(sigs, dict) else next(
            (s for s in sigs if s.get("slot") == slot), None)
        assert one, (
            "簽核三格裡沒有「%s」。現有：%r\n" % (slot, sigs)
            + "📌 `§106c`：製票＝`created_by`／覆核＝第一層簽核人／"
              "主管＝最後一層簽核人。")
        who = one.get("by") or one.get("username") or one.get("user")
        at = one.get("at") or one.get("signed_at") or one.get("time")
        assert who, "「%s」那一格沒有人：%r" % (slot, one)
        assert at, (
            "「%s」那一格沒有**時間**：%r\n" % (slot, one)
            + "☠️ 單子印出來，那一格有名字而**沒有日期** ——\n"
              "   而使用者原話逐字問過「你還問過我審核日期等」。")
        times.append(at)

    # ⚠️ 這裡**故意不再斷言**「三格時間不可以完全相同」——
    #    同一個人連按兩次真的會同一秒，那一版會紅在正確的實作上（`§161`）。
    #    要的是欄位獨立，已經由上面的 ③ 釘住了。


def test_jv2_the_slot_time_check_can_actually_tell_a_shared_field_apart():
    """⚙️ **正對照：上面的 ③ 真的分辨得出「兩格共用一個欄位」嗎？**

    ③ 的斷言是「簽完主管之後，覆核的時間**沒變**」。
    它綠可能是兩件事：
    ```
    ✅ 覆核有自己的欄位     => 本來就不會變
    ☠️ 我的 `_slot_time` 壞了 => 兩次都回 None，`None == None` 照樣綠
    ```
    ⇒ 這一題**走同一條量測路徑**（`_slot_time`），餵一份「共用 `updated_at`」
      的假回應，要求它**看得出差別**。看不出來 ⇒ ③ 的綠燈不算數。
    """
    # 共用欄位的實作長這樣：兩格都指向同一個 `updated_at`
    # ⚠️ 用**攤平**的形狀（B 走的那一種），不是包起來的那一種 ——
    #    正對照走的路徑要與受測物同一條，否則量法壞掉時它照樣綠。
    def snapshot(updated_at):
        return {"created_by": "a", "created_at": updated_at,
                "checked_by": "b", "checked_at": updated_at,
                "manager_by": "c", "manager_at": updated_at}

    before = snapshot("2026-09-23 10:00:00")
    after = snapshot("2026-09-23 10:05:00")   # 主管簽了 => 共用欄位被改掉

    t1 = _slot_time(_slots(before), "覆核")
    t1_after = _slot_time(_slots(after), "覆核")

    assert t1 == "2026-09-23 10:00:00", "量測裝置自己壞了：%r" % (t1,)
    assert t1_after != t1, (
        "餵了一份**明知道是共用欄位**的假回應，③ 的比較卻看不出差別 ——\n"
        + "☠️ 那表示 ③ 就算綠了也**什麼都沒證明**（多半兩邊都回 `None`）。\n"
        + "🔑 先修 `_slot_time`，再去看 ③ 的顏色。")


# ══════════════════════════════════════════════════════════════════════
# ⚙️ 每一條路都要走過 HTTP（A-2：8 支有 7 支打 0 API）
# ══════════════════════════════════════════════════════════════════════

def test_jv2_this_file_never_calls_the_helper_directly():
    """⚙️ **本檔自己不可以繞過 router。**

    A-2 實查：**8 支傳票測試有 7 支打 0 個 API** ——
    直接叫 `helpers/voucher.py` ⇒ 規則全綠而**沒有一條路走得到**。
    🔑 ⇒ 這一題釘的是**我自己**：本檔不可以 `from modules.accounting.voucher import …`。
    ⚠️ 而它擋不住「別的檔那樣做」—— 那是另一題，不在 `JV2` 範圍。
    """
    from pathlib import Path
    src = Path(__file__).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    bad = re.findall(r"^\s*(?:from|import)\s+helpers\.voucher\b", code, re.M)
    assert not bad, (
        "本檔直接 import 了 `modules.accounting.voucher`：%s\n" % bad
        + "☠️ 那條路繞過 router ⇒ **規則全綠而沒有一條路走得到**。")
