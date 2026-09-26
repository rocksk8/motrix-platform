# 稽核：B 的產生檔由列車唯一提交（wip/b-genfiles d78a7c94；含 durations 5c223419）（D，2026-09-26 18:55）

> 完整稽核（改變閘門與選題的基礎）。稽核者 D 沒有寫過任何受稽核的程式碼。
> 內容：
> - 分支不動 UNIT-INDEX、dep_graph、test_map，新題 `test_branch_does_not_touch_generated_files` 在分支上擋。
> - 「是否最新」三題（dep_graph、test_map、UNIT-INDEX）改成只在 `MOTRIX_TRAIN=1` 時跑。
> - modtest 預設現場產生 test_map 與 dep_graph（`--use-files` 才讀檔）。
> - `test_map.py` 改列「已追蹤＋未追蹤但沒被 .gitignore 排除」的檔。
> - durations 那一個 commit 已在 `AUDIT-D-B-modtest-durations.md` 審過。

## 0. 結論

- **必修 2、觀察 2**。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 不開 `MOTRIX_TRAIN`：generated_maps＋unit_cards＋env_and_load_guards | 80 過、3 skip，`-rs` 印出原因「產生檔只由列車提交…」 |
| `MOTRIX_TRAIN=1` | 三題真的執行：1 紅（本分支新增題 ⇒ test_map 與現況不同，符合預期），分支守門改為 skip |
| **D1b 選題**：放一支**尚未 add** 的新題（複製 `test_case_access_l1`），`--files backend/helpers/case_access.py --dry-run` | 現場產生：L1 **2 檔／34 題**（選到新題）；`--use-files`：L1 1 檔／17 題（漏掉）⇒ 現場產生比讀檔準 |
| 現場產生的代價 | 同一次 dry-run：53 秒 vs 15 秒，每次 modtest 多約 38 秒 |
| 突變 GF1：分支檢查恆回空清單 | 紅（`test_rc_branch_check_sees_a_touched_generated_file`） |
| 突變 GF2：modtest 改回優先讀檔 | **存活**（51 過）⇒ GF-M2 |

## 2. 發現

### 必修

**GF-M1　`MOTRIX_TRAIN=1` 忘了開不會被發現（主持重點②）**
- 沒有任何工具會設或檢查 `MOTRIX_TRAIN`：`git grep` 在 tools 與 conftest 都是 0 處。「三題必須是 passed、不可以是 skipped」只寫在 PLAYBOOK §G4 第 3 步的散文裡（〈散文對工具是隱形的〉）。
- 後果：列車忘了開，三題 skip，整輪照綠，過期的產生檔被提交進 origin，而分支已經不驗，所以之後也沒有人會發現。
- 修法（擇一）：
  - (a) 列車用的指令（modtest `--full`，或列車長的固定步驟腳本）自己設 `MOTRIX_TRAIN=1`。
  - (b) conftest：basetemp 以 `-full` 結尾，或 `MOTRIX_PYTEST_EXCLUSIVE=1` 時，這三題若是 skip ⇒ 在收尾時變紅並說明。
  - 兩者都要有反向控制。

**GF-M2　「modtest 現場產生」沒有題守（主持重點③）**
- 分支不再提交產生檔之後，選題準不準全靠 modtest 現場產生；D 實測也證實讀檔會漏掉新題。
- 但突變 GF2（改回優先讀檔）照綠：之後有人為了省那 38 秒改回讀檔，選題就會靜默漏題。
- 修法：補一題，在合成樹或 monkeypatch 下，`load_map()`／`load_graph()` 預設不讀檔，並驗證選得到未提交的新題檔。

### 觀察

- **GF-O1（主持重點①：分支閘門會不會漏掉真正的過期）**：分支上 skip 的只有「檔案內容是否最新」三題。真正的錯仍在分支上擋得到：`test_modules_json_has_no_ownership_errors`、`test_dep_graph_has_no_tree_specific_fields`、產生器本身能不能跑（modtest 現場產生，失敗會明說並退回讀檔）。所以分支會漏的只剩「產生檔內容過期」，而那本來就改由列車負責，前提是 GF-M1 修好。
- **GF-O2**：`test_map.py` 改列未追蹤的檔之後，**在共用樹或髒樹上重產並提交**，會把別人未 add 的檔寫進 test_map.json。列車固定在乾淨的 worktree 重產；建議在 PLAYBOOK 第 3 步寫明，或讓 `test_map.py` 寫檔時遇到未追蹤檔就拒絕（只有現場選題用時才納入）。
