# -*- coding: utf-8 -*-
"""傳票 · **作廢單不可以混進「有效傳票」的查詢裡**。

A 2026-09-23 裁定（`9d9dede`）：
```
維持 5 個狀態，作廢靠 voided_at 過濾
=> 而那個過濾**要有落點**：所有「有效傳票」的查詢走**單一入口**，不是各自寫 WHERE
```

---

# ☠️ 這不是查詢不便，是**會算錯帳**

```
一張已過帳的傳票被作廢 => status 仍然是「已過帳」（✅ 會計上對：
                          作廢是**另一個事件**，不是把過帳收回去）
「本月已過帳的傳票」    => **包含已作廢的那些** => 金額重複計算
```
🔑 而作廢＋重開是使用者裁示的**正常流程**（`§35`）=> **它一定會發生，不是邊緣情境。**
☠️ 而失敗的樣子是一個**偏大的數字**，不是一個錯誤 —— 沒有人會報修它。

# 🔑 根因：`status` 這一個欄位被**兩個問題**共用

```
「這張傳票走到流程的哪裡」  => 已過帳        ✅ 語意正確
「這張傳票現在算不算數」    => **要看 voided_at**
```
=> 問題不在狀態機，**在於「有效性」這個維度沒有落點**。

---

# ⚠️ 本檔**只釘不變量，不釘機制**

A 裁的是「走單一入口」，而入口長什麼樣還沒定版：
```
甲  helper：active_vouchers() / list_vouchers()
乙  SQL VIEW：實表改名 vouchers_all，VIEW 叫 vouchers（WHERE voided_at = ''）
```
=> 本檔對**兩種都測得動**：`vouchers` 是 VIEW 就查它，是實表就找 helper。
🔑 〈守門守的對象被搬走〉：只釘其中一種，換另一種就照樣全綠 ——
   而**釘不變量不是釘實作細節**。
⚠️ 而 A 明著說**現在不要釘「沒走入口就紅」那一題**：入口還不存在
   => 那會是〈防著不存在問題的測試永遠是綠的〉。
"""
import importlib
import sqlite3

import pytest

import db

_HELPER_MODULES = ("modules.accounting.voucher", "helpers.vouchers", "modules.accounting.api.vouchers")
_HELPER_NAMES = ("active_vouchers", "list_vouchers", "query_vouchers",
                 "list_active_vouchers")


@pytest.fixture()
def seeded(tmp_path):
    """兩張**已過帳**的傳票，其中一張已作廢。

    ⚠️ 兩張的 `status` 完全一樣 —— 這一題要分辨的**只有 `voided_at`**。
       若種成不同狀態，一個「只看 status」的實作也會通過。
    """
    path = tmp_path / "motrix_erp.db"
    db.init_db(str(path))
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    if "vouchers" not in have:
        conn.close()
        pytest.fail(
            "我在 `sqlite_master` 裡沒有找到 `vouchers`。\n"
            "⚠️ 它**應該**存在 ⇒ 看 `v95`；`v95` 已完成 ⇒ "
            "**那它是被刪掉或改名了**。")

    target = "vouchers_all" if "vouchers_all" in have else "vouchers"
    for no, voided in (("20260923-001", ""), ("20260923-002", "2026-09-23T01:00:00")):
        conn.execute(
            "INSERT INTO %s (voucher_no, voucher_date, created_by, created_at,"
            " updated_at, status, posted_at, voided_at) "
            "VALUES (?,?,?,?,?, '已過帳', '2026-09-23T00:30:00', ?)" % target,
            (no, "2026-09-23", "C", "2026-09-23T00:00:00",
             "2026-09-23T00:00:00", voided))
    conn.commit()
    yield conn
    conn.close()


def _is_view(conn, name):
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name=?", (name,)).fetchone()
    return row is not None and row[0] == "view"


def _rows_through_the_entry(conn):
    """走「有效傳票」的單一入口，回傳 `(入口說明, 撈到的單號集合)`。

    ⚠️ 兩種機制都試 —— A 還沒定版哪一種。
    """
    if _is_view(conn, "vouchers"):
        got = {r[0] for r in conn.execute(
            "SELECT voucher_no FROM vouchers WHERE status='已過帳'")}
        return "VIEW `vouchers`", got

    for mod_name in _HELPER_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:                                  # noqa: BLE001
            continue
        for fn_name in _HELPER_NAMES:
            fn = getattr(mod, fn_name, None)
            if not callable(fn):
                continue
            for shape in (lambda: fn(conn), lambda: fn(conn, "已過帳"),
                          lambda: fn(conn, status="已過帳")):
                try:
                    out = shape()
                except TypeError:
                    continue
                got = set()
                for r in out or ():
                    if isinstance(r, dict):
                        got.add(r.get("voucher_no"))
                    elif hasattr(r, "keys"):
                        got.add(r["voucher_no"])
                    else:
                        got.add(r)
                return "%s.%s" % (mod_name, fn_name), got
    return None, None


def test_the_active_voucher_query_does_not_return_voided_ones(seeded):
    """🔴🔴 **「查有效的已過帳傳票」撈不到已作廢的那一筆。**

    ```
    20260923-001   已過帳，voided_at = ''              => **要撈到**
    20260923-002   已過帳，voided_at = '…T01:00:00'    => **不可以撈到**
    ```
    ⚙️ 兩張的 `status` 一模一樣 —— 這一題分辨的**只有 `voided_at`**。
       少了第一張，「一律回空」也會讓下半綠，**而那樣沒有任何傳票查得到**。

    📌 而這一題是 A 裁定的**第一半**（走單一入口）的不變量。
    ⚠️ 第二半（「沒走入口就紅」的守門）**現在不釘** —— 入口還不存在，
       釘了就是〈防著不存在問題的測試永遠是綠的〉。
    """
    where, got = _rows_through_the_entry(seeded)
    assert where is not None, (
        "找不到「有效傳票」的單一入口。\n"
        "   找過：`vouchers` 是不是 VIEW ／ %s 裡的 %s\n"
        % (list(_HELPER_MODULES), list(_HELPER_NAMES))
        + "☠️ 目前每一支查詢都要**自己記得**加 `AND voided_at = ''` ——\n"
          "   而忘記的症狀是**金額多算**，沒有錯誤訊息，也沒有人會報修。\n"
          "⚠️ 機制由 A 定版（helper 或 VIEW 都行），"
          "名字要換 **退回給我**，而那個入口必須存在。")

    assert "20260923-002" not in got, (
        "入口（%s）撈到了**已作廢**的 `20260923-002`：%s\n" % (where, sorted(got))
        + "☠️ 「本月已過帳的傳票」會**重複計算**那一筆金額 ——\n"
          "   而作廢＋重開是使用者裁示的正常流程（`§35`），**它一定會發生**。")
    assert "20260923-001" in got, (
        "入口（%s）連**沒作廢**的 `20260923-001` 都撈不到：%s\n" % (where, sorted(got))
        + "⚙️ 這是正對照：少了它，「一律回空」也會讓上面那個斷言綠，"
          "**而那樣沒有任何傳票查得到**。")


def test_the_voided_one_is_still_reachable_somewhere(seeded):
    """⚙️ **正對照：作廢單本身不可以消失。**

    ☠️ 「過濾掉」與「查不到」是兩件事：
    ```
    作廢單要能被查到  => 稽核要看得到「這一張作廢過」
    ```
    🔑 使用者裁示的是**作廢重開**：原單留著，另開一張，
       **帳上看得到那一次作廢** —— 一個查不到作廢單的系統做不到這件事。
    📌 而它同時擋掉一種過得去的做法：**作廢時直接 DELETE**。
    """
    have = {r[0] for r in seeded.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    target = "vouchers_all" if "vouchers_all" in have else "vouchers"
    if _is_view(seeded, "vouchers") and target == "vouchers":
        pytest.fail(
            "`vouchers` 是 VIEW 而沒有 `vouchers_all` —— "
            "**查不到實表就查不到作廢單**。\n"
            "⚠️ 實表的名字要換 **退回給我**。")

    n = seeded.execute(
        "SELECT COUNT(*) FROM %s WHERE voided_at != ''" % target).fetchone()[0]
    assert n == 1, (
        "作廢的那一筆在 `%s` 裡有 %d 筆（預期 1）——\n" % (target, n)
        + "☠️ 作廢單不見了 ⇒ 稽核看不到「這一張作廢過」，"
          "而使用者裁的是**作廢重開**：原單留著。")
