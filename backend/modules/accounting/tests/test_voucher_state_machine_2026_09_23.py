# -*- coding: utf-8 -*-
"""傳票 · ① 狀態機 ＋ ② 借貸平衡。

規格來源：**`docs/windows/SPEC-VOUCHER.md`（施工圖，`5df2f48` 落進 repo）**。
⚠️ 有衝突時以施工圖為準 —— 修訂過程在 `SPEC-VOUCHER-HISTORY.md`，**不要照它實作**。

```
草稿 ──送審──▶ 待審核 ──(分層簽核)──▶ 簽核中 ──▶ 已核准 ──過帳──▶ 已過帳
  ▲                                                                │
  └────── 退回（狀態回草稿 ＋ 單號升版 -Rn ＋ 清除簽核）◀───────────┘
                                          ⚠️ 而**已過帳不可退回** ⇒ 只能**作廢重開**
EDITABLE_STATUSES = ("草稿",)
```

---

# 🔁 **我自己釘錯過一次：狀態是五個，不是六個**

```
我原本釘  草稿／待審核／簽核中／已核准／已過帳／**作廢**   ← 六個
施工圖    草稿／待審核／簽核中／已核准／已過帳             ← **五個**（§一「狀態值」逐字）
```
☠️ **那個「作廢」是我自己推的** —— 我從「已過帳不可退回 ⇒ 只能**作廢重開**」
   推出「作廢是一個狀態」，而規格從頭到尾只說它是一個**動作**
   （落在 `voided_at`／`voided_by`／`void_reason`／`supersedes_no` 四個欄位上）。
🔑 〈推翻的證據不會自動支持替代方案〉的近親：
   **一個動作存在，不表示它有一個狀態值。**
⚠️ 而它本來會變成一個**指著正確實作的紅燈** —— B 照施工圖寫五個，我的題判他錯。

📌 而我把那一列留著（〈更正要留著錯的那一列〉），因為**它旁邊有一個真的問題**：
```
作廢之後 status 還是「已過帳」 ⇒ 「已過帳的傳票」這個查詢**包含作廢單**
```
⇒ **那是我報給 A 的問句，不是我自己塞進斷言的要求。**（〈不自己發編號〉）

---

# 🔴 ② 借貸平衡：**過帳時擋，草稿允許不平衡**

```
草稿  允許不平衡  ← 使用者正在打，打到一半本來就不平
過帳  必須平衡    ← 而不平衡要**說得出差額**
```
☠️ 反過來寫（草稿就擋）的症狀是：**使用者打不完第一行就被擋住**。
🔑 那是〈降級之後它還是會動〉的鏡像：**擋太早會讓功能不能用，而它看起來像「很嚴謹」。**
"""
import importlib

import pytest

#: 施工圖 `§一` 的「狀態值」那一行，**逐字**。五個，不是六個。
#: ⚠️ 「作廢」**不在這裡** —— 它是動作，落在 `voided_at`/`voided_by`/`void_reason`。
STATUSES = ("草稿", "待審核", "簽核中", "已核准", "已過帳")
#: 施工圖 `§一`「可編輯 **只有 "草稿"**」／`STATE.md §103e`：選甲之後只有一個值。
EDITABLE = ("草稿",)

_SEAM_MODULES = ("modules.accounting.voucher", "helpers.vouchers", "modules.accounting.api.vouchers")


def _voucher_module():
    for name in _SEAM_MODULES:
        try:
            return name, importlib.import_module(name)
        except Exception:                                  # noqa: BLE001
            continue
    pytest.fail(
        "找不到傳票模組（找過：%s）。\n" % list(_SEAM_MODULES)
        + "⚠️ 名字可以換（**退回給我**），而那個接縫必須存在。")


def _attr(mod, *names):
    for n in names:
        v = getattr(mod, n, None)
        if v is not None:
            return n, v
    return None, None


# ══════════════════════════════════════════════════════════════════════
# ① 狀態機
# ══════════════════════════════════════════════════════════════════════

def test_voucher_statuses_are_exactly_the_five_from_the_spec():
    """🔴 **狀態剛好是施工圖 `§一` 的那五個。**

    ```
    草稿 ／ 待審核 ／ 簽核中 ／ 已核准 ／ 已過帳
    ```
    ⚠️ 我原本釘六個（多一個「作廢」）—— **那是我自己推的，不在規格裡**。
       見檔頭：一個動作存在，不表示它有一個狀態值。
    ⚠️ 釘**集合相等**不是「包含」：
    ```
    少一個  ⇒ 有一條路走不到
    多一個  ⇒ 有人加了一個狀態而沒有人決定它的轉移規則
             ☠️ 而多出來的那個在畫面上會**看起來很正常**
    ```
    📌 那與 `§54c` 的笛卡兒積同形狀：**清單要能被數，而不是「有沒有包含」。**
    """
    where, mod = _voucher_module()
    name, statuses = _attr(mod, "VOUCHER_STATUSES", "STATUSES", "_STATUSES")
    assert statuses is not None, (
        "`%s` 沒有狀態清單（找過 `VOUCHER_STATUSES`／`STATUSES`）——\n" % where
        + "🔑 狀態要有一個**可以被數**的地方，散在 `if/elif` 裡數不出來。")
    assert set(statuses) == set(STATUSES), (
        "狀態是 %s，`§106c` 定版是 %s。\n" % (sorted(set(statuses)), sorted(STATUSES))
        + "⚠️ 多一個 ⇒ 有人加了狀態而沒有人決定它的轉移規則，"
          "**而它在畫面上看起來很正常**。")


def test_only_draft_is_editable():
    """🔴 `§103e`：**`EDITABLE_STATUSES` 只有「草稿」一個值。**

    A 實查五個既有模組的做法：
    ```
    草稿 11 支／待審核 9／簽核中 9／已核准 9／**已駁回 1**
    甲（多數 9–11 支）：退回 ⇒ 狀態回「草稿」＋ 單號升版 ＋ 清除簽核
    ```
    ⇒ 選甲之後**沒有「已駁回」這個狀態** ⇒ 可編輯的只有草稿。
    ☠️ 多一個可編輯狀態的後果很具體：**簽核中的單被改掉，而簽過的人不知道。**
    """
    where, mod = _voucher_module()
    name, editable = _attr(mod, "EDITABLE_STATUSES", "_EDITABLE_STATUSES")
    assert editable is not None, (
        "`%s` 沒有 `EDITABLE_STATUSES` ——\n" % where
        + "🔑 「哪些狀態可以編輯」要有一個地方寫著，"
          "不可以散在每一支 endpoint 的 `if` 裡。")
    assert tuple(editable) == EDITABLE, (
        "`EDITABLE_STATUSES` 是 %r，`§103e` 定版是 %r。\n"
        % (tuple(editable), EDITABLE)
        + "☠️ 多一個的後果：**簽核中的單被改掉，而簽過的人不知道。**")


def test_a_posted_voucher_cannot_be_sent_back():
    """🔴🔴 施工圖 `§一`：**已過帳不可退回 —— 只能作廢重開**（使用者裁示）。

    ```
    已核准 ──退回──▶ 草稿   ✅（＋ 單號升版 -Rn ＋ 清除簽核）
    已過帳 ──退回──▶ ✗      ☠️ 一張已入帳的傳票被退回成草稿
                             ⇒ **帳上那一筆還在，而單據回到可編輯狀態**
    ```
    🔑 而「作廢重開」與「退回」不是同一件事：
    ```
    退回      同一張單，改完再走一次
    作廢重開  **原單留著**（作廢），另開一張 —— 帳上看得到那一次作廢
    ```
    📌 那是會計上的要求，不是 UI 偏好：**已入帳的東西不可以被無痕修改。**

    ⚙️ 而這一題要**兩個方向**：
    ```
    已過帳退回  ⇒ 必須被拒絕
    已核准退回  ⇒ **必須成功**（否則「全部都不准退」也會讓上半綠）
    ```
    """
    where, mod = _voucher_module()
    name, fn = _attr(mod, "can_send_back", "_can_send_back", "can_reject")
    assert fn is not None, (
        "`%s` 沒有「可不可以退回」那一支（找過 `can_send_back`）——\n" % where
        + "⚠️ 名字可以換（**退回給我**），而那個判斷要抽得出來 —— "
          "內嵌在 endpoint 裡的話，**只有走過那條路才驗得到**。")

    # A 2026-09-23 裁定（依據 `quotations.py:4309` ＋ 施工圖 `§一`）：
    # 待審核／簽核中／已核准**都**可退回。⚠️ 施工圖只畫了「已核准 → 草稿」那一條，
    # 中間兩格是**規格沉默處**，B 先做了實作並主動報 A ⇒ 裁定之後才由我釘。
    # 📌 〈不自己發編號〉：我在裁定前刻意沒釘它 —— 釘了就是我替 A 做決定。
    expect = {
        "草稿": False,      # 它已經在草稿了，沒有「退回」這個動作
        "待審核": True,
        "簽核中": True,
        "已核准": True,
        "已過帳": False,    # 🔴 帳已動 ⇒ 只能作廢重開
    }
    assert set(expect) == set(STATUSES), (
        "這一題的期望表與 `STATUSES` 對不上 —— **儀器自己過期了**。\n"
        "⚙️ 少一格 ⇒ 有一個狀態沒有人決定它可不可以退回，"
        "**而漏掉的永遠是沒有人想到的那一個**。")
    got = {s: fn(s) for s in STATUSES}
    assert got == expect, (
        "`can_send_back` 的五格是 %r\n預期 %r\n" % (got, expect)
        + "⚙️ 這是**笛卡兒積**不是兩個抽樣：少了「已核准必須 True」這一格，"
          "`return False` 也會讓下面那個斷言綠，\n"
          "   **而退回是這個流程的正常動作**。")
    assert fn("已過帳") is False, (
        "`已過帳` 可以退回 ——\n"
        "☠️ 一張已入帳的傳票被退回成草稿：**帳上那一筆還在，"
        "而單據回到可編輯狀態。**\n"
        "🔑 使用者裁示：已過帳只能**作廢重開** —— 原單留著，另開一張，"
        "**帳上看得到那一次作廢**。")


# ══════════════════════════════════════════════════════════════════════
# ② 借貸平衡
# ══════════════════════════════════════════════════════════════════════

def _lines(*pairs):
    """`[(借, 貸), …]` → 分錄列。欄位名未定版 ⇒ 用最小的形狀。"""
    return [{"debit": d, "credit": c} for d, c in pairs]


def test_an_unbalanced_draft_is_allowed():
    """🔴 **草稿允許不平衡。**

    ☠️ 反過來寫（草稿就擋）的症狀是：**使用者打不完第一行就被擋住** ——
    ```
    借 1000 / 貸 0   ← 才打了一半，而它本來就不平
    ```
    🔑 那是〈降級之後它還是會動〉的鏡像：
       **擋太早會讓功能不能用，而它看起來像「很嚴謹」。**
    ⚙️ 而它是下一題的正對照：少了它，「永遠擋住」也會讓下一題綠。
    """
    where, mod = _voucher_module()
    name, fn = _attr(mod, "check_balance", "_check_balance", "validate_balance")
    assert fn is not None, (
        "`%s` 沒有借貸平衡檢查（找過 `check_balance`）——\n" % where
        + "⚠️ 名字可以換（**退回給我**）。")
    ok, diff = fn(_lines((1000, 0)), status="草稿")
    assert ok is True, (
        "草稿不平衡（借 1000／貸 0）被擋下來了 ——\n"
        "☠️ 使用者打不完第一行就被擋住。**擋太早會讓功能不能用。**")


def test_posting_an_unbalanced_voucher_is_refused_and_says_the_difference():
    """🔴🔴 **過帳時必須平衡，而不平衡要說得出差額。**

    ```
    借 1000 ／ 貸 900  ⇒ 拒絕，**而訊息要說出差額 100**
    ```
    ☠️ 只說「借貸不平衡」的話，使用者要自己把每一行加一次 ——
    🔑 **而那個數字是檢查它的人手上就有的。**
    📌 〈把錯誤訊息整個拿掉是最省力的變綠方式〉的鄰居：
       **一個不說差額的錯誤訊息，等於要使用者重做一次檢查。**

    ⚙️ 正對照：**平衡的傳票過帳必須成功**（否則「永遠拒絕」也會綠）。
    """
    where, mod = _voucher_module()
    _n, fn = _attr(mod, "check_balance", "_check_balance", "validate_balance")
    if fn is None:
        pytest.fail("沒有借貸平衡檢查 —— 見上一題。")

    ok, diff = fn(_lines((1000, 0), (0, 900)), status="已核准")
    assert ok is False, (
        "借 1000／貸 900 的傳票過帳沒有被擋 ——\n"
        "☠️ 一張不平衡的傳票進了帳，而它之後只能靠人工對帳發現。")
    assert diff == 100, (
        "擋下來了，而差額報 %r，預期 100。\n" % diff
        + "🔑 不說差額的話，使用者要自己把每一行加一次 ——"
          "**而那個數字是檢查它的人手上就有的。**")

    ok2, _d = fn(_lines((1000, 0), (0, 1000)), status="已核准")
    assert ok2 is True, (
        "平衡的傳票（借 1000／貸 1000）過帳被擋 ——\n"
        "⚙️ 這是正對照：少了它，「永遠拒絕」會讓上面那個斷言綠，"
        "**而沒有任何一張傳票過得了帳**。")


def test_an_all_zero_voucher_cannot_be_posted_although_it_balances():
    """🔴 **全 0 的傳票「平衡」而不可過帳** —— 施工圖 `§六①` 逐字是
    `SUM(debit) == SUM(credit)` **且 `> 0`**。

    ```
    借 0 ／ 貸 0   =>  相等 ✅  而金額是 0  =>  **不可過帳**
    ```
    ☠️ 放行的後果是一筆**金額為 0 的分錄**進帳：
    **不報錯、帳是平的、對帳也對得起來** —— 它只是不該存在。
    🔑 而這一格 B 主動指出來了，理由是 `(ok, diff)` 這個回傳**表達不出它**：
    ```
    借 0 ／ 貸 0  =>  (False, 0)
    而 diff 也是 0  =>  `if diff: 擋` 會放行它
    ```
    📌 ⇒ 判準不可以綁在 `diff` 上。這一題釘的是 **`ok`**，不是 `diff`
       —— 〈守門守的對象被搬走〉：兩個值都對，而決定行為的是另一個。
    ⚠️ 我沒有改 B 的簽章，也沒有自己發明「> 0」這個門檻：它在 `§六①` 裡。
    """
    where, mod = _voucher_module()
    _n, fn = _attr(mod, "check_balance", "_check_balance", "validate_balance")
    if fn is None:
        pytest.fail("沒有借貸平衡檢查 —— 見上一題。")

    ok, diff = fn(_lines((0, 0)), status="已核准")
    assert ok is False, (
        "借 0／貸 0 的傳票過得了帳（回傳 ok=%r, diff=%r）——\n" % (ok, diff)
        + "☠️ 一筆金額為 0 的分錄進帳：**不報錯、帳是平的、對帳也對得起來**。\n"
        + "🔑 `§六①` 逐字是「`SUM(debit) == SUM(credit)` **且 > 0**」。")
    assert diff == 0, (
        "全 0 的差額報 %r —— 它**應該**是 0（兩邊相等）。\n" % diff
        + "⚙️ 這一格刻意釘住，是為了說明**為什麼不可以拿 `diff` 當判準**："
          "合法的 0 與非法的 0 在這個欄位上長得一模一樣。")
