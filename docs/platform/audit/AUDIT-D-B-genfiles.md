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

## 回覆（B，19:39，wip/b-genfiles-2 11937d60）

| # | 回覆 | commit |
|---|---|---|
| GF-M1 | 修正：`modtest --train`（預設 --base origin/platform）自動設 MOTRIX_TRAIN=1，跑①差異題②tests/platform（-rs）；`train_judge`：兩段 exit 0，且「是否最新」三題收集得到、沒有因 MOTRIX_TRAIN 被 skip，否則 exit 1。PLAYBOOK §G4 第 4 步①②改用它。題：judge 四種情況、run_train 行為；突變（不設旗標／不判 skip）紅。**實跑**：重產後 `modtest --train` ⇒ ①1208 過 ②1181 過、三題有跑、exit 0 | 159533f0 |
| GF-M2 | 修正：題「還沒 git add 的新測試檔要在現場算的 test_map 裡」；突變（load_map 預設讀檔）紅 | 159533f0 |
| 觀察（髒樹重產） | 改用結構修法取代「拒絕」：提交用／--check 用的 test_map 只看已追蹤的檔（`build(include_untracked=False)`），只有 modtest 現場選題含未追蹤的新檔。緣由：第一次實跑 --train 時，GF-M2 的題在 -n 4 下暫時建檔，同時跑的 --check 判過期（tests/platform 1 紅）——拒絕重產擋不到這一型。題：提交用 build 不含未追蹤、現場含；突變紅 | 11937d60 |


## 3. 複核：wip/b-genfiles-2 11937d60（159533f0＋11937d60；D 19:44）

| 主持的問題 | D 的驗證 | 結果 |
|---|---|---|
| `--train` 一定跑那三題、skip 就判紅 | `run_train`：設 `MOTRIX_TRAIN=1` ⇒ 差異題 ⇒ tests/platform（`-rs`）⇒ 三題 collect-only；`train_judge` 遇到「三題 skip」或「收集不到」⇒ 紅。突變 GFa「不設旗標」、GFb「不判 skip」、GFd「不檢查收集」 | 3/3 紅 ⇒ **GF-M1 關閉** |
| 現場產生有題守 | 突變 GFc「現場改回讀檔」 | 紅（`test_live_map_sees_an_untracked_new_test`）⇒ **GF-M2 關閉** |
| 「提交的 test_map 只看已追蹤檔」能不能取代 D 建議的「髒樹拒絕重產」 | 讀 diff：`tracked_files(include_untracked=False)` 是提交與 `--check` 的預設，只有 modtest 現場選題才傳 True；新題 `test_committed_test_map_ignores_untracked_files` 守住。D 另在 11937d60 放未追蹤的 `backend/tests/*.py` 與 `backend/helpers/*.py`，跑 `dep_scan.py --check` ⇒ 都 rc=0（dep_graph 不受未追蹤檔影響） | **站得住**：它從結構上讓未追蹤檔進不了提交的檔，比「髒樹就拒絕」更根本；B 實跑時發現的問題（題目在 -n 4 下暫時建檔，讓同時跑的 --check 判過期）也一併解掉 |

**GF2-M1（必修，新）　本分支刪掉了既有的 B-S4 守門題**
- 合併基底 `9bb0fb90` 有 `test_env_and_load_guards.py::test_rerun_keeps_history_and_gate_reports_earlier_reds`（57e2f3ee 加的：同一個 commit 保留歷次紀錄、閘門顯示紅過幾次），11937d60 沒有。D 對本分支改到的測試檔逐一比對 `def test_*`，只少了這一題。
- 產品邏輯 `write_last_full` 的 history 仍在，只是守它的題不見了。推測是解衝突時，新題取代了同一段而把它蓋掉。
- 修法：把那一題原樣還回來。

**觀察 GF-O3**：「忘了 `--train`」和原本「忘了 `MOTRIX_TRAIN=1`」是同一類問題，只是入口從一個環境變數收斂成一個旗標，比較不容易忘；PLAYBOOK §G4 第 4 步已寫明用 `--train`。若要讓它由工具保證，可以讓列車長的固定腳本只呼叫 `--train`。不擋。
