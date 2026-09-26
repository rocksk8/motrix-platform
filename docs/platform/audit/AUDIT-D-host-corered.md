# 稽核：主持的 h-corered（core-only 已知紅的兩題改用合成模組）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。合回前稽核。
> 對象：`origin/wip/h-corered-2` `b682b9bf`（只改 `tests/platform/test_case_read_scope.py`、`tests/platform/test_integration_points_registered.py`）。對應 AUDIT-D-B-G1 G-M1 的 4 題之 2。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。

## 0. 結論

**必修 0、建議 0**。兩題「模組在」的正對照改成：`source_tree.BACKEND` 指到暫存樹，裡面放一個帶 `module.json` 的合成模組 `zz_here`，不再綁定真實 L2。

| 驗證 | 結果 |
|---|---|
| 把 D 樹的所有 L2 模組都拿掉（模擬 core-only），跑兩個檔 | **11 passed**（舊版在同一情境紅 2 題，AUDIT-D-B-G1 §2） |
| 突變 CR1：`installed_routes` 把所有 `modules/` 路徑都豁免（在的也豁免） | 紅（2） |
| 突變 CR2：登記表豁免不看模組在不在（X2a） | 紅（`test_absent_module_green_present_module_still_red`） |

## 1. 同時確認的兩包（rebase 改名，D 已審過）

- `h-hist-4` `5e736075`：`git range-diff` 顯示後兩個 commit 與 D 審過的 `1ef54b72`、`9e55dfa1` **完全相同（=）**。前兩個 commit（`f4c14dc5`、`288e3a78`）不在分支上，是因為已經隨第五班合回：origin 上是 `46c29f9f`、`37173e6d`，也有 `_read_history()`。
- `h-u14-2` `1fa732e6`：兩個 commit 與 D 審過的 `6639ea8d`、`48dab2a3` **完全相同（=）**。

## 2. 回覆欄

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| — | 無待回覆項目 | | ✅ 10:30 |
