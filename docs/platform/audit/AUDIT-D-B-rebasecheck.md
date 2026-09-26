# 稽核：B 的 `modtest --rebase-check` 不再叫各線跑全量（wip/b-rebasecheck；合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`origin/wip/b-rebasecheck` `e0137ddc`：`need_full` 改名為 `high_impact`；影響大時只建議差異題（`suggest`，永遠不帶 `--full`、不含 fixture 層檔）；本分支自己動到 fixture 層時，差異題照跑，閘門過了回 3；PLAYBOOK 表格 ②、MODULE-GUIDE 更正。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。

## 0. 結論

- **必修 1 項**：R-M1，PLAYBOOK §C-11 還寫著舊規則。
- 建議 1 項。程式行為符合主持 §G3 的裁示，基準 28 passed，D 突變 3 項中 2 項紅。

## 1. 驗證

| 項目 | 結果 |
|---|---|
| 基準：`test_modtest_rebase_check.py`＋`test_modtest_rebase_bookkeeping.py` | 28 passed |
| RB2：本分支動到 fixture 層、閘門過了回 0（原本應回 3） | 紅（`test_own_fixture_layer_change_runs_the_diff_and_does_not_ask_for_full`） |
| RB3：兩邊改同一個程式檔不算影響大 | 紅（8） |
| RB1：`suggest_command` 不排除 fixture 層檔 | **存活**（見 R-S1） |
| 其他工具或文件有沒有依賴舊的 `need_full`／exit 3 語意 | `git grep`：tools、backend 沒有其他使用者；文件只有 PLAYBOOK §C-11 與表格 ② |

## 2. 發現

### 必修

**R-M1　PLAYBOOK §C-11 仍寫「重跑全量」，與新行為互相矛盾**
- `docs/platform/PLAYBOOK.md:70`（§C-11）寫的是：「例外：差異裡有 fixture 層，或有程式碼衝突 ⇒ **重跑全量**」。這一包只改了表格 ②（`:187`）與 MODULE-GUIDE，§C-11 本文沒有更正。
- 為什麼是必修：這一包要解決的問題，正是「照 §C-11 的字面各自跑全量，同時 3 組，超過 §C-13」（modtest 的 docstring 寫明 C 踩過）。工具改了，但權威文件的條文還叫人跑全量；照條文做的人，會把同一件事再做一次（MEMORY〈要求寫在訊息裡等於沒下達〉）。
- 修法：§C-11 的「例外」那一句照格式劃掉並加〔更正〕，改成「影響大 ⇒ 差異題擴大到衝突檔＋tests/platform＋改到頁面的 e2e，全量交給列車（§G3），月台註明」。

### 建議

- **R-S1　「fixture 層檔不放進 `--files`」只在「別人改 fixture」的情境有題**：`test_rebase_check_never_tells_a_line_to_run_the_full_suite` 的 fixture 檔只在帶進來的那一側，不在 `after_green` 或 `overlap` 裡，所以 RB1 拿掉排除條件照樣綠（在這個情境下，突變沒有改到任何東西）。建議補「本分支在全量之後又改了 fixture 層」或「兩邊都改了 fixture 層」的情境，斷言 `suggest` 不含它。後果不大：modtest 現在不會因為 conftest 而拒絕縮小。

## 3. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| R-M1 | | | |
| R-S1 | | | |
