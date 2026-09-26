# 稽核：C 的 T 稅額純函式下沉 L1（wip/c-tax-calc）與 M01 下沉第二批（wip/c-m01-sink2-2）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。合回前稽核。
> 對象：`origin/wip/c-tax-calc` `a1d7ba4a`（`c60cd3fa`、`a1d7ba4a`；基底 `cc348186`）；`origin/wip/c-m01-sink2-2` `77b9a672`（疊在 T 上：`7992b9f1`、`77b9a672`）。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。

## 0. 結論

**兩包必修 0、建議 0，觀察 1 項。**

## 1. c-tax-calc（a1d7ba4a）

- **逐字搬移**：D 用 AST 比較基底的 `helpers/quotations.py` 與新的 `helpers/tax_calc.py`：
  - `_invoice_amount`、`invoice_amounts`、`payment_item_amounts`、`quote_tax_type` 四支內容**完全相同**，舊檔已不再定義。
  - `tax_split` 唯一的差別是錯誤訊息的 `%` 改成 `%%`，也就是 C 報的既有 bug 修正（原本丟 TypeError，而不是應有的 ValueError）。
- `tax_calc` 只 import `fastapi.HTTPException` 與 L1 的 `helpers.legal_params.round_half_up`，不依賴 M01。
- D 突變（`test_tax_calc_contract.py`＋4 個稅額相關檔，99 題）：
  - TX1：把 `%%` 改回 `%` ⇒ 紅（`test_behaviour`），所以修正有題目守。
  - TX2：稅額改用內建 `round` ⇒ 紅。

## 2. c-m01-sink2-2（77b9a672）

- `norm_at` 下沉到 `helpers/dates`，`_steps_to_tiers` 下沉到 `helpers/tiered_approval.steps_to_tiers`。舊名在 `helpers/__init__`、`helpers/quotations` 保留為別名，`routers/system.py` 改從 L1 取。`core/registry.py` 只改了版號（1.31）。
- D 突變（`test_m01_sink2_contract.py`，8 題）：
  - SK1：別名改成包一層的複本 ⇒ 紅（`test_old_names_are_aliases_of_the_l1_objects`）。
  - SK2：`norm_at` 不把 `T` 換成空白 ⇒ 紅。
  - SK3：`steps_to_tiers` 的 order 從 1 起算 ⇒ 紅。

## 3. 觀察

- **O-1　與第六班 b-m08-2 可能在 rebase 時交會**：c-tax-calc 改了 `backend/routers/reports.py` 的 import（`helpers.quotations` 改成 `helpers.tax_calc`）；而 b-m08-2 會把這支檔搬到 `modules/analytics/api/reports.py`。後上車的那一包在 rebase 時，要確認新位置的 import 也改成 `helpers.tax_calc`；否則 M08 仍會經由別名依賴 M01（不會壞，但 `l2_import_baseline` 那一條邊會回來）。

## 4. 回覆欄

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| — | 無待回覆項目（O-1 由列車處理） | | ✅ 11:00 |

〔13:24 D 補：O-1 已處理——wip/c-tax-calc-2 c46647c8（rebase 到第六班之後）：`modules/analytics/api/reports.py:27`、`helpers/receivables.py:17` 都改自 `helpers.tax_calc` import；reports 仍經 `helpers` 套件取用 M01 的 `payment_item_amounts`、`quote_won_month_map` 等，所以 l2_import_baseline 那兩條 analytics → M01 的邊是真的；boundaries／tax_calc／changelog／package／G1 快照共 92 passed（-n 4）⇒ **O-1 結案（c46647c8）**〕
