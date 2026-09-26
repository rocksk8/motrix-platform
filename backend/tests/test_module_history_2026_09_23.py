# -*- coding: utf-8 -*-
"""`FN4` · 五模組操作歷史（施工圖 `docs/windows/SPEC-HISTORY.md`，`41e1494`）。

三層，**而它們不可合併**：
```
① 執行歷史  答「這個月做了什麼」⇒ 業務查詢，**取消的那筆要消失**
② 逐筆編寫  `<module>_edit_log`，改前 → 改後
③ 全域稽核  `audit_log`，答「這個人做過什麼」⇒ **不可刪，取消的那筆也要留著**
```

---

# 🔴 兩處我複核出入，先寫在這裡（已回報 A）

```
施工圖 §三3.1   「**只有兩張**：傳票與獎金」
而   §六②      「**五張** `*_edit_log` 的欄位形狀必須一致」
⇒ 同一份施工圖裡的兩個數字不一致 —— 後者是前一版的殘留
☠️ 照 `五張` 寫一道守門 ⇒ **它永遠紅**（另外三張不該存在）
```
```
施工圖 §三3.1   「reports.py **有 8 處寫入**」
我實測          `_audit(` **4** ／ `_set_setting` **3** ／ 而第 8 個是
                `:24` 的 **import 那一行**
⇒ 真正的寫入是 **7**，而 8 這個數字把 import 算進去了
```
⚠️ 而那一段施工圖自己警告過：**「下一個人查到那 8 處會以為這個結論也錯了」**
🔑 **結論（reports.py 有寫、而它寫的不是業務單據的逐筆修改）我複核成立** ——
   錯的只有那個數字，而那正是它自己在防的那件事。

---

# ⚠️ 本檔不釘的兩件（施工圖明著劃掉）

```
保留天數    法條起算點是「年度決算辦理終了後」，而**系統沒有記錄那個時點**
            ⇒ 只釘「每列有 retention 欄位」，**不釘天數**
清理排程    **沒有落點** ⇒ 不出題（〈計數器要有落點〉）
```
"""
import json
import re
import sqlite3
from pathlib import Path

import pytest

import db

_BACKEND = Path(__file__).resolve().parent.parent

#: `②` 那一層：**兩張**，不是五張（見檔頭）。
EDIT_LOGS = {
    "voucher_edit_log": "voucher_id",
    "bonus_award_edit_log": "award_id",
}

#: 每一張都要有的欄位（施工圖 `§三3.1` 的 DDL）。
EDIT_LOG_COLUMNS = ("id", "changed_by", "changed_at", "changes_json", "retention")

RETENTION_DOMAIN = ("permanent", "term")


@pytest.fixture(scope="module")
def fresh_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("hist") / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _cols(conn, table):
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]


# ══════════════════════════════════════════════════════════════════════
# ⚙️ 不碰新表的兩題 —— **現在就該綠**
# ══════════════════════════════════════════════════════════════════════

def test_the_unpay_precedent_really_does_both_layers():
    """⚙️ **`①③` 不可合併的正對照是真的** —— 既有前例已經證明它。

    ```
    contractor_vouchers.py  action == "unpay"
      UPDATE … SET is_paid=0, paid_by='', paid_at='', paid_log=? …
      而那個 paid_log 裡 append 的是 {"action": "unpaid", …}
    ```
    🔑 ⇒ **兩層都在，而「消失」只發生在該消失的那一層**：
    ```
    執行歷史（is_paid）  那筆**消失** ⇒ 它不該算進本月金額
    逐筆紀錄（paid_log） 那筆**留著** ⇒ 誰在什麼時候取消的
    ```
    ☠️ 少了這一題，`§四` 那整段（合併會失去什麼）建立在**一段我沒有讀過的描述**上。
    """
    from core import source_tree
    if not source_tree.module_installed("modules/subcontract/"):
        pytest.skip("前例在外包工班（M04），模組不在這個安裝包（PLAYBOOK §B-11）")
    src = (_BACKEND / "modules" / "subcontract" / "api" / "contractor_vouchers.py").read_text(encoding="utf-8")
    assert '"action": "paid" if action == "pay" else "unpaid"' in src, (
        "`contractor_vouchers.py` 不再把 `unpaid` append 進 `paid_log` ——\n"
        + "🔑 那個前例變了 ⇒ **`§四` 那一段的理由要重寫**。")
    assert re.search(r"SET is_paid=0[^\"]*paid_log=\?", src), (
        "`unpay` 不再同時 `SET is_paid=0` 與寫 `paid_log` ——\n"
        + "🔑 兩層分開這件事失去了它的既有前例。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 ② 逐筆編寫紀錄：兩張，同形狀
# ══════════════════════════════════════════════════════════════════════

def test_fn4_both_edit_log_tables_exist(fresh_db):
    """🔴 **兩張 `*_edit_log` 都要在**（傳票已有，獎金還沒有）。

    ⚠️ 施工圖 `§六②` 寫「**五張**」是前一版的殘留 —— `§三3.1` 逐字是
       「**只有兩張**：傳票與獎金」。照五張寫的守門**永遠紅**。
    📌 ⇒ 本檔釘兩張，而清單在 `EDIT_LOGS` 裡**數得出來**（`§54c` 形狀）。
    """
    have = {r[0] for r in fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(set(EDIT_LOGS) - have)
    assert not missing, (
        "我在 `sqlite_master` 裡沒有找到 %s。\n" % missing
        + "⚠️ 它們**應該**存在 ⇒ 看 `FN4` 的 migration；已完成 ⇒ "
          "**那是被刪掉或改名了**。\n"
        + "📌 而 `voucher_edit_log` 已經在（`v95`）⇒ 缺的是獎金那一張。")


def test_fn4_the_two_edit_logs_have_the_same_shape(fresh_db):
    """🔴 **兩張的欄位形狀必須一致** —— 少一欄或多一欄都紅。

    ☠️ 不一致的後果不是報錯，是**查詢寫不通用**：
       日後有人寫一支「查任一模組的編寫歷史」的工具，它會在其中一張上壞掉。
    🔑 而施工圖選「同形狀 ＋ 同命名」而**不是抽成共用函式** ——
       共用函式壞掉 ⇒ 兩個模組同時失效。
    """
    have = {r[0] for r in fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    present = [t for t in EDIT_LOGS if t in have]
    if len(present) < 2:
        pytest.fail("兩張表還沒到齊（現有 %s）—— 見上一題。" % present)

    shapes = {}
    for t, fk in EDIT_LOGS.items():
        cols = _cols(fresh_db, t)
        shapes[t] = sorted(set(cols) - {fk})
    a, b = list(shapes.values())
    assert a == b, (
        "兩張的欄位形狀不一致（已扣掉各自的外鍵欄）：\n"
        + "\n".join("  %-24s %s" % (t, c) for t, c in shapes.items())
        + "\n☠️ 不一致不會報錯 —— 它讓「查任一模組的編寫歷史」那種工具"
          "**在其中一張上壞掉**。")
    for t in EDIT_LOGS:
        cols = set(_cols(fresh_db, t))
        miss = [c for c in EDIT_LOG_COLUMNS if c not in cols]
        assert not miss, (
            "`%s` 缺 %s。現有：%s\n" % (t, miss, sorted(cols))
            + "📌 `retention` 那一欄是 `§五` 的落點："
              "會計師答了之後**改設定值，不改結構**。")


def test_fn4_retention_only_accepts_the_two_values(fresh_db):
    """🔴 **`retention` 的值域只有 `permanent` / `term`。**

    ```
    🟡 A 已裁（未反對即生效）
       「誰**匯出**過」⇒ permanent（資料離開系統的證據）
       「誰**預覽**過」⇒ term（保留期可設）
    ```
    ⚠️ 而本題**不釘天數** —— 法條起算點是「年度決算辦理終了後」，
       **而系統沒有記錄那個時點**（施工圖明著劃掉）。
    ☠️ 值域外的值不會報錯，它只是讓清理排程**跳過那一列** ——
       而那一列會永遠留著，沒有人知道為什麼。
    ⚙️ 正對照：兩個合法值都要收得下（否則「一律拒絕」也會讓上半綠）。
    """
    have = {r[0] for r in fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    t = next((x for x in EDIT_LOGS if x in have), None)
    if t is None:
        pytest.fail("兩張表都不存在 —— 見上一題。")
    if "retention" not in _cols(fresh_db, t):
        pytest.fail("`%s` 還沒有 `retention` 欄 —— 見上一題。" % t)

    fk = EDIT_LOGS[t]
    for ok_value in RETENTION_DOMAIN:
        fresh_db.execute(
            "INSERT INTO %s (%s, changed_by, changed_at, changes_json,"
            " retention) VALUES (1,'C','2026-09-23T00:00:00','[]',?)" % (t, fk),
            (ok_value,))
    fresh_db.rollback()

    with pytest.raises(sqlite3.IntegrityError):
        fresh_db.execute(
            "INSERT INTO %s (%s, changed_by, changed_at, changes_json,"
            " retention) VALUES (1,'C','2026-09-23T00:00:00','[]','forever')"
            % (t, fk))
    fresh_db.rollback()


# ══════════════════════════════════════════════════════════════════════
# 🔴 ⑥① 缺「改前值」要寫入失敗
# ══════════════════════════════════════════════════════════════════════

def test_fn4_a_change_entry_without_the_old_value_is_refused():
    """🔴 **`changes_json` 缺「改前值」⇒ 寫入失敗**（施工圖 `§六①`）。

    ```
    DEFAULT '[]' **擋不住空紀錄** ⇒ 要在**應用層**擋
    ```
    ☠️ 少了改前值的那一列**看起來完全正常** ——
       它有時間、有人、有欄位名，而**回答不出「原本是什麼」**，
       🔑 而那正是逐筆紀錄唯一要回答的問題。
    ⚙️ 正對照：完整的那一筆**必須寫得進去**（否則「一律拒絕」也會讓上半綠）。
    """
    import importlib
    mod = fn = None
    for name in ("helpers.edit_log", "helpers.history", "helpers.audit"):
        try:
            mod = importlib.import_module(name)
        except Exception:                                  # noqa: BLE001
            continue
        for n in ("append_edit_log", "write_edit_log", "_append_edit_log"):
            if callable(getattr(mod, n, None)):
                fn = getattr(mod, n)
                break
        if fn:
            break
    assert fn is not None, (
        "找不到寫逐筆紀錄的那一支（找過 `append_edit_log` / `write_edit_log`）——\n"
        + "⚠️ 名字可以換（**退回給我**），而它必須**抽得出來**：\n"
          "   內嵌在每支 endpoint 裡的話，「缺改前值要失敗」這條規則\n"
          "   **要在每一支各實作一次**，而漏掉的那一支不會有任何訊號。")

    bad = [{"field": "voucher_date", "to": "2026-09-01"}]        # 沒有 from
    with pytest.raises(Exception):
        fn(None, 1, "C", bad)

    good = [{"field": "voucher_date", "from": "2026-08-31", "to": "2026-09-01"}]
    fn(None, 1, "C", good)      # ⚙️ 正對照：完整的必須成功


def test_fn4_execution_history_does_not_get_its_own_table(fresh_db):
    """🔴 **`①` 執行歷史不可以新建一張表。**

    ```
    它答的是「這個月實際發生了什麼」⇒ **資料來源是業務表自己，不是另一份副本**
    ```
    ☠️ 另一份副本 ⇒ 兩份會分岔，**而分岔之後哪一份是真的沒有定義**。
    🔑 而「取消的那筆要消失」正是靠業務表自己的欄位做到的
       （`contractor_vouchers` 的 `is_paid=0`）—— 副本做不到這件事，
       它只會多一列「已取消」。
    """
    have = {r[0] for r in fresh_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    ghosts = sorted(t for t in have
                    if re.search(r"(execution|exec)_(history|log)$", t)
                    or t.endswith("_execution_history"))
    assert not ghosts, (
        "出現了執行歷史的專屬表：%s\n" % ghosts
        + "☠️ 那是**另一份副本** ⇒ 兩份會分岔，而分岔之後哪一份是真的沒有定義。\n"
        + "✅ 施工圖 `§3.3`：沿用 `cashier.py:150 _execution_history()` 的做法"
          "（對業務表做日期範圍查詢）。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 `append_edit_log` 的**第一個呼叫端**（A `§151`：判甲 ⇒ **改判丙**）
# ══════════════════════════════════════════════════════════════════════


def test_fn4_something_actually_calls_append_edit_log():
    """🔴🔴 **`append_edit_log()` 目前沒有任何產品碼在叫它。**

    ```
    $ grep -rn append_edit_log --include=*.py .（排除定義與 tests）
      => **零命中**
    helpers/edit_log.py:88  定義在 ✅
    routers/vouchers.py     **不存在**
    ```
    🔑 〈兩個都對而路不存在〉：規則對、函式對、我的題也對 ——
       **而它不會生效**。`FN4` 的 ② 那一層目前**什麼都不記**。
    ☠️ 而這種缺陷讀規格看不出來：規格說「改過要留痕」，
       函式也真的會留痕，**而沒有人在改的時候叫它**。

    📌 這一題釘的是**呼叫端存在**，下面兩題釘它**叫對了**。
    ⚠️ 我上一題（`visible_lines`）就是驗函式沒驗呼叫，A-2 複核才補上 ——
       同一個形狀，這次先釘。
    """
    # 🔴 **掃工作樹不用 `git grep`**（B 2026-09-23 指出）：
    # ```
    # git grep 只看得到**被追蹤的檔** ⇒ B 的 routers/vouchers.py 當時未 add
    # ⇒ 檔案在、碼是對的、呼叫也真的存在，**而守門照樣紅**
    # ```
    # ⚠️ 而它的方向與〈工作樹≠repo〉記的**相反**：
    # ```
    # 平常  未追蹤檔讓守門**閉嘴**（它看不到違規）
    # 這次  未追蹤檔讓守門**誤報**（它看不到修正）
    # ```
    # ⇒ 掃工作樹（行為的真相），而「有沒有被 add」由下一個斷言分開講。
    import subprocess
    callers = []
    for path in sorted((_BACKEND).rglob("*.py")):
        rel = path.relative_to(_BACKEND).as_posix()
        if rel.startswith("tests/") or rel.endswith("helpers/edit_log.py"):
            continue
        if "rollback_snapshots/" in rel or "deploy_packages/" in rel:
            continue
        if "append_edit_log" in path.read_text(encoding="utf-8", errors="replace"):
            callers.append(rel)
    assert callers, (
        "沒有任何產品碼呼叫 `append_edit_log()`（只有它自己的定義）——\n"
        + "☠️ 那條規則**不會生效**：使用者改了傳票，而沒有任何一列紀錄。\n"
        + "🔑 〈兩個都對而路不存在〉：規則對、函式對，**而路不存在**。\n"
        + "⚠️ 而它讀規格看不出來 —— 規格說「改過要留痕」，函式也真的會留痕。")

    # ⚙️ 而**出貨的是被追蹤的那一份** ⇒ 未追蹤的呼叫端要分開講。
    tracked = subprocess.run(
        ["git", "ls-files", "--", "backend"],
        cwd=str(_BACKEND.parent), capture_output=True, text=True).stdout.split()
    tracked = {f[len("backend/"):] for f in tracked if f.startswith("backend/")}
    untracked = [c for c in callers if c not in tracked]
    assert not untracked, (
        "呼叫端在工作樹上而**沒有被 git 追蹤**：%s\n" % untracked
        + "☠️ 它在這台機器上會動，**而打包出去的那一份沒有它** ——\n"
          "   ⇒ 正式機上使用者改了傳票，一列紀錄都沒有。\n"
        + "🔑 這一格與上一格分開，是因為兩者的處置不同："
          "上面那個要**去寫呼叫**，這個要**`git add`**。")


def test_fn4_an_old_value_of_empty_string_still_counts_as_present():
    """🔴 **改前值是空字串或 `None` 也算「有值」。**

    ☠️ 用真假值判斷的話：
    ```
    if not ch.get("from"):  raise 缺改前值
    => 原本是**空的**那些欄位（summary / departmentCode …）**永遠寫不進去**
    => 而它們正是「從沒填變成有填」那種最該留痕的改動
    ```
    🔑 〈null 不等於 0〉：「沒有這個鍵」與「值是空的」是兩件事。
    📌 而這一題釘的是**不變量不是實作** —— B 用 `"from" in ch`，
       換一種寫法只要行為一樣就過。
    """
    import importlib
    mod = importlib.import_module("helpers.edit_log")
    fn = getattr(mod, "append_edit_log")

    for old in ("", None):
        rows = fn(None, 1, "C",
                  [{"field": "summary", "from": old, "to": "新的摘要"}])
        assert rows and "from" in rows[0], (
            "改前值是 %r 時被當成「缺改前值」——\n" % old
            + "☠️ 原本是空的那些欄位**永遠寫不進去**，"
              "而它們正是最該留痕的那一種（從沒填變成有填）。")

    with pytest.raises(Exception):
        fn(None, 1, "C", [{"field": "summary", "to": "新的摘要"}])


# ══════════════════════════════════════════════════════════════════════
# 🔴 傳票兩支端點的**權限**（A 的交付條件②）
# ══════════════════════════════════════════════════════════════════════

#: `routers/vouchers.py:34` 逐字的模組清單。⚠️ 改了 **退回給我**。
VOUCHER_MODULES = ("cashier", "finance")


#: `(角色, 模組, 該不該過)` —— **兩個方向各自都要有**（`§54c`：清單要能被數）。
VOUCHER_ACCESS = (
    ("superadmin", [],           True,  "superadmin 不受模組限制"),
    ("admin",      [],           False, "🔴 admin **無模組要 403** —— 不可直通"),
    ("admin",      ["cashier"],  True,  "admin 有其中一個模組"),
    ("admin",      ["finance"],  True,  "admin 有另一個模組"),
    ("user",       ["cashier"],  True,  "一般使用者有模組就可以"),
    ("user",       ["reports"],  False, "🔴 有**別的**模組要 403 —— 不是「有任何模組就行」"),
    ("user",       [],           False, "一般使用者無模組"),
)


