# -*- coding: utf-8 -*-
"""`FN5` 重心一 · **「科目代號已設定」這個判準漏了兩格**。

施工圖 `docs/windows/SPEC-T100-CONFIG.md`（`c14df60`）。

---

# ☠️ 現存的假綠燈（A-2 找到，A 複驗，我複驗成立）

```javascript
frontend/js/cashier.js:615-621（逐字）
  coreFilled = salesRevenueAccount && outputTaxAccount && contractorExpenseAccount
  hasBank    = bankAccounts.length > 0 && every(b => b.name && b.acctCode)
  return !!(coreFilled && hasBank)
```
```
☠️ inventoryExpenseAccounts **不在判準裡**
⇒ 料件分類的科目一個都沒設，畫面照樣顯示「**✓ 科目代號已設定**」
⇒ 而 accounting_export.py:263 `cfg["inventoryExpenseAccounts"].get(category, "")`
⇒ ⇒ **匯出那幾列的科目代號是空的，而畫面說設定完整**
```
🔑 它不是「少驗一個欄位」，是**一個主動說謊的綠勾** ——
   使用者看到 ✓ 之後**不會再去看那一段**。

# 📏 而 `PART_CATEGORIES` 有幾個，施工圖 `§八` 標為未查 —— 我量了：**6**

```
網通設備 ／ 監控設備 ／ 交換器 ／ 伺服器/工控 ／ 線材配件 ／ 其他
```
⚠️ 它是 `[{name, prefix}]` **不是**一串字串 ⇒ 鍵取 `c["name"]`。
📌 而數字寫在這裡**不是判準** —— 判準是「涵蓋 `PART_CATEGORIES` 全部的鍵」，
   加一個分類時它自己會跟上（〈釘不變量不是釘字面值〉）。

# ⚠️ 本檔不碰施工圖 `§五` 那一格（未決）

> 「只能選葉節點」不成立：**合計列也是葉節點**（`86`／`88`），而資料上分不出。
⇒ 本檔**不釘任何層級限制**。A-2 明著寫「不要自己發明合計列偵測 ——
  那會是一個猜，而猜錯時它靜默地擋住正確的選擇」。
"""
import json
import re
import sqlite3
from pathlib import Path

import pytest

import db

_BACKEND = Path(__file__).resolve().parent.parent
_FRONTEND = _BACKEND.parent / "frontend"
CASHIER_JS = _FRONTEND / "js" / "cashier.js"

#: `_DEFAULT_T100_CONFIG` 裡**必須進完整性判準**的欄位（施工圖 `§四`）。
#: ⚠️ `departmentCode`（選填）與 `voucherCategory`（有預設）**不在**判準裡是對的。
REQUIRED = ("salesRevenueAccount", "outputTaxAccount", "contractorExpenseAccount",
            "bankAccounts", "defaultBankAccountCode", "inventoryExpenseAccounts")


def _part_categories():
    from helpers.part_catalog import PART_CATEGORIES
    return [c["name"] for c in PART_CATEGORIES]


def _complete_fn():
    """`t100ConfigComplete` 那個 getter 的原始碼。"""
    src = CASHIER_JS.read_text(encoding="utf-8")
    m = re.search(r"get\s+t100ConfigComplete\s*\(\)\s*\{(.*?)\n    \}", src, re.S)
    assert m, (
        "`cashier.js` 裡找不到 `get t100ConfigComplete()` ——\n"
        + "⚠️ 它**應該**存在 ⇒ 看 `FN5`；`FN5` 已完成 ⇒ "
          "**那它被改名或搬走了**（名字換了**退回給我**）。")
    return m.group(1)


# ══════════════════════════════════════════════════════════════════════
# ⚙️ 不碰前端的兩題 —— **現在就該綠**
# ══════════════════════════════════════════════════════════════════════

def test_the_export_really_reads_the_inventory_accounts():
    """⚙️ **證明「漏掉它會讓匯出出空值」是真的** —— 這是重心一的理由。

    ```
    accounting_export.py:263
      expense_code = (cfg["inventoryExpenseAccounts"] or {}).get(category, "")
    ```
    ☠️ 少了這一題，重心一建立在**一段我沒有讀過的描述**上。
    🔑 而 `.get(category, "")` 那個 `""` 正是「不報錯」的來源：
       **查不到就給空字串** ⇒ 匯出照樣產生，只是那一欄是空的。
    """
    src = (_BACKEND / "routers" / "accounting_export.py").read_text(encoding="utf-8")
    assert re.search(
        r'inventoryExpenseAccounts.*?\)\s*\.get\(\s*category', src, re.S), (
        "`accounting_export.py` 沒有用 `inventoryExpenseAccounts` 查 category ——\n"
        + "🔑 那條路變了 ⇒ **重心一的理由要重寫**（那是好消息）。")
    assert '.get(category, "")' in src, (
        "`.get(category, \"\")` 不見了 ——\n"
        + "⚙️ 那個空字串預設正是「不報錯」的來源；"
          "若它改成會丟例外，這個缺陷就從**靜默**變成**看得見**。")


def test_the_part_categories_list_is_a_list_of_dicts_with_name():
    """⚙️ **`PART_CATEGORIES` 的形狀** —— 施工圖 `§八` 把它標為未查。

    ```
    PART_CATEGORIES = [{"name": "網通設備", "prefix": "NET"}, …]   **6 個**
    ```
    ⚠️ 它**不是**一串字串 ⇒ `inventoryExpenseAccounts` 的鍵要取 `c["name"]`。
    ☠️ 取錯的話（例如直接 `set(PART_CATEGORIES)`）會 `TypeError: unhashable`，
       而那個紅會指向**測試寫錯了**，不是指向設定。
    📌 而我**不釘 6 這個數字** —— 判準是「涵蓋全部的鍵」，加分類時它自己跟上。
    """
    from helpers.part_catalog import PART_CATEGORIES
    assert PART_CATEGORIES and all(
        isinstance(c, dict) and c.get("name") for c in PART_CATEGORIES), (
        "`PART_CATEGORIES` 的形狀變了：%r\n" % (PART_CATEGORIES[:2],)
        + "🔑 `inventoryExpenseAccounts` 的鍵取不出來 ⇒ 下面那題的判準要重寫。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 重心一：判準要涵蓋六個欄位
# ══════════════════════════════════════════════════════════════════════

def test_fn5_the_completeness_check_looks_at_the_inventory_accounts():
    """🔴🔴 **`t100ConfigComplete` 必須看 `inventoryExpenseAccounts`。**

    ☠️ 現況：料件分類的科目一個都沒設，畫面顯示「**✓ 科目代號已設定**」
       ⇒ 而匯出那幾列的科目代號是空的。
    🔑 一個**主動說謊的綠勾**比沒有綠勾更糟：使用者看到 ✓ 之後**不會再去看那一段**。
    """
    body = _complete_fn()
    assert "inventoryExpenseAccounts" in body, (
        "`t100ConfigComplete` 的判準裡沒有 `inventoryExpenseAccounts`：\n"
        + body.strip()[:300]
        + "\n☠️ ⇒ 六個料件分類一個都沒設，畫面照樣顯示「✓ 科目代號已設定」，\n"
          "   而 `accounting_export.py` 匯出那幾列的科目代號是**空的**。")


def test_fn5_the_completeness_check_looks_at_the_default_bank_account():
    """🔴 **`defaultBankAccountCode` 也要進判準**（施工圖 `§四`）。

    ```
    它是「找不到上次用哪個」時的**退路**（accounting_export.py:85 註解）
    ⇒ 它沒設 ⇒ 那個退路不存在 ⇒ **而畫面說設定完整**
    ```
    ⚠️ 而施工圖同時標了它的代價：**現有設定會從「完整」變「不完整」** ——
       📌 而它本來就不完整，那不是一個迴歸。
    """
    body = _complete_fn()
    assert "defaultBankAccountCode" in body, (
        "`t100ConfigComplete` 的判準裡沒有 `defaultBankAccountCode`：\n"
        + body.strip()[:300]
        + "\n☠️ 那個退路沒設 ⇒ 標記付款時找不到預設帳戶，**而畫面說設定完整**。")


def test_fn5_the_default_bank_code_must_be_one_of_the_listed_accounts():
    """🔴 **`defaultBankAccountCode` 必須在 `bankAccounts` 清單裡。**

    ☠️ 只驗「有填」的話，一個**指向已刪帳戶**的預設值照樣算完整 ——
       而它的症狀是標記付款時**挑不到任何帳戶**，沒有錯誤訊息。
    🔑 〈缺欄位≠缺訊號〉的鏡像：**欄位有值，而那個值指不到東西。**
    """
    body = _complete_fn()
    assert re.search(
        r"bankAccounts[^\n]{0,160}(some|find|includes|indexOf)"
        r"|(some|find|includes|indexOf)[^\n]{0,160}defaultBankAccountCode",
        re.sub(r"\s+", " ", body)), (
        "判準沒有檢查 `defaultBankAccountCode` **在不在** `bankAccounts` 裡：\n"
        + body.strip()[:300]
        + "\n☠️ 一個指向已刪帳戶的預設值照樣算完整 ——\n"
          "   症狀是標記付款時挑不到任何帳戶，**而沒有錯誤訊息**。\n"
        + "⚠️ 我看的是「有沒有做包含性檢查」；用別的寫法**退回給我**。")


def test_fn5_missing_one_part_category_must_show_incomplete():
    """⚙️🔴 **反向控制：只缺一個料件分類 ⇒ 必須顯示不完整。**

    ☠️ 少了這一格，一個「`inventoryExpenseAccounts` 非空就算數」的實作也會綠 ——
    ```
    六個分類設了一個 => 畫面說完整 => 而另外五個分類的匯出仍然是空的
    ```
    🔑 判準是**涵蓋全部的鍵**，不是「有填東西」。
    📌 而它要綁 `PART_CATEGORIES` 不是綁數字 6：加一個分類時，
       設定就該立刻變成「不完整」—— **而綁數字的話它會安靜地繼續說完整**。
    """
    body = _complete_fn()
    flat = re.sub(r"\s+", " ", body)
    assert re.search(r"PART_CATEGORIES|partCategories|categories", flat), (
        "判準沒有引用料件分類清單：\n" + body.strip()[:300]
        + "\n☠️ 那表示它只檢查「有沒有填東西」⇒ 六個分類設了一個也算完整，\n"
          "   而另外五個分類的匯出仍然是空的。\n"
        + "⚠️ 清單要從後端來（`/api/parts/categories`）——\n"
          "   **在前端再寫一份分類名稱就是第二份實作**，而兩份一定會分岔。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 代號必須存在於科目樹
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def fresh_db(tmp_path):
    path = tmp_path / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_fn5_a_code_that_is_not_in_the_account_tree_is_refused(fresh_db):
    """🔴🔴 **設定值必須存在於 `account_items.code`，不存在 ⇒ 拒絕儲存。**

    ```
    打錯的代號**不會報錯** —— T100 匯出照樣產生，
    到會計師匯入 T100 那一刻才發現，**而那時傳票已經開出去了**
    ```
    ⚠️ 而**不擋**「非 statutory」（A-2 裁）：使用者自訂的科目也可能是正確的對應。
    ⚠️ 而**要擋**「已停用」的（`is_active=0`）：停用的科目不該被新設定引用。
    🔑 而已經設定好的**不因停用而失效** —— 要明著顯示「這個科目已停用」並要求重選：
       ☠️ 靜默失效的症狀是「匯出的科目代號突然變空」，**而沒有人會知道為什麼**。

    ⚙️ 三個正對照都要：法定的可選／自訂的**也**可選／停用的**不**可選。
    """
    import importlib
    mod = None
    for name in ("modules.accounting.api.accounting_export", "helpers.t100_config"):
        try:
            mod = importlib.import_module(name)
            break
        except Exception:                                  # noqa: BLE001
            continue
    assert mod is not None, "找不到 T100 設定模組。"

    fn = None
    for n in ("validate_account_code", "_validate_account_code",
              "check_config_codes", "_check_codes"):
        if callable(getattr(mod, n, None)):
            fn = getattr(mod, n)
            break
    assert fn is not None, (
        "`%s` 沒有代號檢查（找過 `validate_account_code` …）——\n" % mod.__name__
        + "⚠️ 名字可以換（**退回給我**）。我釘的形狀：\n"
          "   `validate_account_code(conn, code) -> (ok, err)`；"
          "`err` 要說出**是哪一個代號**、以及它是「不存在」還是「已停用」。")

    fresh_db.execute(
        "INSERT INTO account_items (code, name, parent_code, level, source,"
        " is_active) VALUES ('9901','自訂可用','',4,'custom',1)")
    fresh_db.execute(
        "INSERT INTO account_items (code, name, parent_code, level, source,"
        " is_active) VALUES ('9902','自訂停用','',4,'custom',0)")
    fresh_db.commit()

    ok_bad, err_bad = _pair(fn(fresh_db, "9999"))
    assert not ok_bad, "不存在的代號 `9999` 通過了 —— 打錯的代號不會報錯。"
    assert "9999" in str(err_bad), (
        "擋下來了，而訊息裡沒有 `9999`：%r\n" % (err_bad,)
        + "🔑 要說出**是哪一個代號**。")

    ok_off, err_off = _pair(fn(fresh_db, "9902"))
    assert not ok_off, (
        "已停用的 `9902` 通過了 —— **停用的科目不該被新設定引用**（A-2 裁）。")
    assert "停用" in str(err_off), (
        "擋下來了，而訊息沒說它是**已停用**（回的是 %r）——\n" % (err_off,)
        + "☠️ 「不存在」與「已停用」的處置不同：前者要改代號，"
          "後者要嘛啟用它、要嘛換一個。")

    for code, why in (("1113", "法定"), ("9901", "自訂（**不可以擋**）")):
        ok, err = _pair(fn(fresh_db, code))
        assert ok, (
            "`%s`（%s）被擋下來了：%r\n" % (code, why, err)
            + "⚙️ 正對照：少了它，「一律拒絕」也會讓上面那些斷言綠，\n"
              "   **而那樣一個代號都設不了**。\n"
            + "⚠️ 非 `statutory` 的**不可以擋**（A-2 裁）："
              "使用者自訂的科目也可能是正確的對應。")


def _pair(out):
    if isinstance(out, tuple) and len(out) == 2:
        return out
    return bool(out), ""


# ══════════════════════════════════════════════════════════════════════
# 🔴 重心二：可發現性（A 2026-09-23 重新定義）
# ══════════════════════════════════════════════════════════════════════

CASHIER_HTML = _FRONTEND / "pages" / "cashier.html"


def test_fn5_the_warning_says_where_to_go():
    """🔴 **「尚未設定完整」要帶路徑** —— 現在它沒說去哪設。

    ```
    cashier.html:570（逐字）  '⚠ 科目代號尚未設定完整'
    而入口在同一頁的 :600     「展開科目代號設定」按鈕
    ```
    ☠️ 使用者看得到警告，**而不知道下一步** —— 那正是他撞到的那件事。
    🔑 與 `RAISE(ABORT)` 那一條同源：**那句話是使用者唯一看得到的東西**，
       而「看得到」不等於「知道下一步」。

    📌 而**不要新建設定頁**（A 裁）：它已經存在（`cashier.js:458 saveT100Config`
       ＋ `cashier.html:754` 儲存鈕）—— 再做一個就是第二份實作。
    ⇒ 這一題釘的是**那句話裡有沒有指路**，不是「有沒有設定頁」。
    """
    html = CASHIER_HTML.read_text(encoding="utf-8")
    m = re.search(r"['\"]⚠[^'\"]*尚未設定完整[^'\"]*['\"]", html)
    assert m, (
        "`cashier.html` 裡找不到「尚未設定完整」那句話 ——\n"
        + "⚠️ 它**應該**存在 ⇒ 看 `FN5`；`FN5` 已完成 ⇒ **那句話被改寫了**"
          "（改寫**退回給我**，我把 pattern 跟上）。")
    text = m.group(0)
    assert re.search(r"展開|設定面板|下方|點.*設定|→|⇒", text), (
        "警告只說了問題，沒說去哪解決：%s\n" % text
        + "☠️ 使用者看得到警告而**不知道下一步** —— 那正是他撞到的那件事。\n"
        + "✅ 要指到**已經存在的那個入口**（同一頁的「展開科目代號設定」），\n"
          "   ⚠️ 而**不要新建一個設定頁** —— 再做一個就是第二份實作。")


def test_fn5_the_config_panel_is_not_shown_to_everyone():
    """🔴 **那個面板不可以只靠 `:disabled` 擋** —— 非 superadmin 不該看到代號。

    ```
    現況（我實查 cashier.html）
      :675  <div x-show="t100ConfigOpen">          <= **與角色無關**
      :745  <input :disabled="_role()!=='superadmin'">  <= 只擋「改」
      :69x  <span x-show="_role()!=='superadmin'">（僅 superadmin 可修改，你目前只能檢視）</span>
    ```
    ⚠️ 那是一個**明著的決定**（「你目前只能檢視」），不是疏忽 ——
       而施工圖 `§六` 逐字要求 **superadmin，不放寬**。
    🔑 ⇒ 這一題問的是：**「可檢視」與「可修改」誰裁的？**
       `disabled` 只擋得住畫面上的輸入 —— 值仍然在 DOM 裡、在 API 回應裡。
    📌 ⇒ 若「可檢視」是刻意的，**把它寫進施工圖**，這一題跟著改成釘那個決定；
       在那之前它釘 `§六` 的原話。

    ⚠️ 我**沒有**驗 API 那一層（`GET /api/settings/t100-export-config` 的權限）——
       那是下一格，而它比畫面重要。
    """
    html = CASHIER_HTML.read_text(encoding="utf-8")
    # 🔴 **我第一版寫 `t100ConfigOpen"` —— 要求屬性值剛好是它**（B 抓到）：
    #    B 加上角色條件之後是 `x-show="t100ConfigOpen && _role()==='superadmin'"`
    #    ⇒ `assert m` 先倒 ⇒ 訊息說「那個面板被改寫了」，**而它在，只是條件變長了**。
    # ☠️ 又是「錯的話聽起來像量出來的」：我的判準太窄，而它去否定一個正確的修正。
    m = re.search(r'<div x-show="t100ConfigOpen[^"]*"[^>]*>', html)
    assert m, (
        "找不到 `x-show=\"t100ConfigOpen…\"` 那個面板 ——\n"
        + "⚠️ 它**應該**存在 ⇒ 看 `FN5`；已完成 ⇒ **那個面板被改寫了**。")
    assert "_role()" in m.group(0) or "superadmin" in m.group(0), (
        "設定面板的顯示條件只有 `t100ConfigOpen`，**與角色無關**：\n"
        + "   " + m.group(0)[:100]
        + "\n⚠️ 畫面上只有 `:disabled` 擋「改」——而值仍然在 DOM 與 API 回應裡。\n"
        + "📌 施工圖 `§六` 逐字：**superadmin，不放寬** ——"
          "「科目代號設錯的後果落在會計師那一端，而他不在這個系統裡」。\n"
        + "🔑 若「非 superadmin 可檢視」是刻意的決定，**請 A 寫進施工圖**，"
          "我把這一題改成釘那個決定。")
