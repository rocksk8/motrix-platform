# M2 建包與閘門筆記（供 PLAYBOOK §G7 併入）

> 2026-10-13 整合者（b7 視窗）依 M2 列車（train/m2-int-r3～r9）實際遭遇整理。只記作法與證據，不改規則；規則是否採納由主持定。
> 最終凍結頭：`train/m2-int-r9` ＝ `c87079be2343ef5596a14f50bdaaa45810007caf`；部署包 `20261013_004023_c87079be2`。

## 1. 中文路徑的 worktree 建包：主控台要先設 UTF-8

- 症狀：`build_deploy_package.ps1` 一開始報「找不到 git repo … pathspec」，兩個路徑印出來都是亂碼。
- 原因：腳本用 `git rev-parse --show-toplevel` 的輸出和自己的工作目錄比對；git 輸出是 UTF-8，PowerShell 5.1 以主控台碼頁（cp932／cp950）解碼，含中文的目錄名比對不上。ASCII junction 沒用（git 仍回傳真實路徑）。
- 作法（可用）：
  `powershell -NoProfile -ExecutionPolicy Bypass -Command '[Console]::OutputEncoding=[Text.Encoding]::UTF8; $OutputEncoding=[Text.Encoding]::UTF8; & .\backend\tools\build_deploy_package.ps1 -OutDir "<輸出目錄>"'`
  （工作目錄設為該 worktree）。
- 其他 Python 工具（`regen_all.py`、`train_number.py` 等）在預設 cp932 主控台印中文會丟 `UnicodeEncodeError`：加 `PYTHONIOENCODING=utf-8`（或 `-X utf8`）。regen_all 第一次因此中途失敗時沒有寫檔，重跑即可。
- 建議：把 UTF-8 設定寫進腳本開頭，或在 PLAYBOOK §G7.2 的指令範例直接用上面的形式。

## 2. VR7（Step 2.52）需要 `backend\motrix_erp.db`

- 建包的「版本紀錄反方向」守門（`check_version_sync.py`）讀 `<worktree>\backend\motrix_erp.db`（git-ignored）；讀不到是失敗，不跳過。列車用的 worktree 平時沒有這個檔。
- **核可來源**：正式機 `module_versions` 的 `module|version` 配對（唯讀、由正式機 Claude 提供文字），在本機重建成**只含 `module_versions` 一張表**的最小 DB（M2：555 列）。**不可**複製開發庫（自動模式分類器擋為個資；使用者 10-12 裁示不複製）。建包前複製進 worktree、建包後立刻刪除；前後都確認 `git status` 乾淨、HEAD 不變。
- 實際價值：M2 因此抓到真缺口——`傳票 2026-09-25q` 在正式機 DB 有、repo manifest 沒有（9/26 合併 `03331c69e`「VR3 同模組未發版只留一筆」時被併掉）。逐字補回（r6）才過；不要繞過守門、不要從 DB 副本刪那一列。
- 建議：每班出貨前由正式機固定產出這份最小快照（放報告資料夾），列車直接取用，免臨時請求。

## 3. 建包沿用結果的「同一天」規則會在跨午夜時失效

- `build_deploy_package` 只沿用「同一份 tree＋環境、同一天、12 小時內」的綠。M2 r9 的 not_e2e 綠是 10-12 22:46，建包在 10-13 00:16：日期不同 ⇒ 建包自己重跑 not_e2e（約 24 分），e2e 因為是 00:15 才跑的而沿用。
- 影響：跨午夜的班，建包時間 +~25 分，且 `verification.stages.not_e2e` 會是 `ran` 而非 `reused`（步驟檔「預期 stages」要照實寫）。
- 備註：已有人（c7）在處理移除「同一天」條件；採納後此節可刪。

### 3.1 使用者書面授權與殘餘風險（2026-10-13）

- **授權**：2026-10-13 凌晨，使用者原話：「未來跨日一樣能出包，不要再為了跨日浪費時間」。據此建包／modtest 的沿用規則改為「12 小時內、同一份 tree＋環境、兩段嚴格全綠即沿用」，不再要求同一個日曆日（`4666773cd`，M2.1 manifest 2026-10-13c）。
- **殘餘風險（0d 稽核註記）**：依日期（月初／月底／跨日）判斷的測試，可能在 23:50 綠、過午夜後紅；沿用最多可把這種紅藏 12 小時。緩解：12 小時窗口與「整棵 tree 指紋」不變；日期相依的測試應在測試內固定時鐘，或另列午夜後的抽查。


## 4. 視窗之間的訊息：relay loop 被切斷時訊息會被丟棄

- 現象：短時間內連發的多則回報被判為 relay loop，系統回「Do not resend now … NOT delivered」；實際上主持端因此近 1 小時看不到階段回報。
- 作法：階段回報**合併成一則**（第一行＝狀態＋任務＋SHA／時間，其餘 ≤3 行），不要每個動作一則；懷疑被丟時只補送**一則**彙整，不重試迴圈。心跳每 10 分鐘一行即可。

## 5. 閘門偶發（flake）清單——供 known_flakes 檢討（本班未改 known_flakes.json）

單跑皆 3/3 通過；重跑官方 e2e 後綠。證據：同一份 tree 的多次完整 e2e 只有其中一次紅。

| 測試 | 現象 | 疑似原因 |
|---|---|---|
| `tests/test_e2e_dispatch_payslip_block_viewer_2026_10_08.py::test_viewer_without_any_related_module_gets_no_request_and_no_block`（r6，20:42） | `dispatch-slips-<id>` 區塊在 `dpSlips[id].hidden===true` 之後仍被判可見 | 狀態旗標與 DOM 更新之間的時序；斷言沒有等 DOM |
| `modules/analytics/tests/test_e2e_reports_period_select_matches_model_2026_09_25.py::test_every_tab_shows_select_values_equal_to_the_model[年報-year]`（r9，23:02） | `page.locator(".tab").count()` 為 0（要求 ≥5） | 等了 `.period-bar` 就**立刻** `count()`，沒有等 `.tab` 出現；分頁渲染稍慢就紅（`count()` 不會自動等待） |
| `tests/test_e2e_expense_form_a24_2026_10_01.py::test_my_requests_document_buttons`（r9 重跑，23:39；錯誤在 teardown） | `conftest._drain_servers` 10 秒內仍有 1 個請求在處理 | 機器負載（當時有作者視窗在跑指令，可用記憶體 15→11 GB）；不是斷言失敗 |

建議：analytics 那題改成 `expect(page.locator(".tab")).to_have_count(...)` 或先 `wait_for_selector(".tab")`；其餘兩題先觀察，閘門期間保持其他視窗安靜。

## 6. 這班閘門的時間與結果（供步驟檔／RUN-PLAN §6 引用）

- r9 full-lint：2850 過／8 略過（10.5 分）。not_e2e：10640 過／68 略過（官方 28 分，建包內重跑 23.6 分）。e2e：1002 過／3 略過（約 18～20 分）。
- 建包：`verify_package --expect-db-version 118` 0 FAIL；`product_select check` OK；V5：1015 檔中 1010 與樹相同、1 不同（`version_manifest.json`）、4 建包產生檔；`final_drill` 通過；`final_verify` PASS 19／FAIL 0／WARN 2／SKIP 1。
- 路上遇到、已解決的紅燈：r3 `test_vr1_the_manifest_is_not_older…`（最新 commit 日期晚於 manifest）、r4 兩支 e2e 對系統中心導覽收合的舊期待、r5 `test_map` 過期、r6 VR7（傳票 2026-09-25q）、r6 `final_drill` permmatrix 未宣告 `provides.probes`、r7 三項（modules.json 歸屬／api_prefixes、探針回應含字串）、r8 permmatrix CHANGELOG 順序。
- 教訓：新增模組端點（含探針）要一次帶齊 `module.json`、`modules.json`、CHANGELOG（程式改動之後）、`test_map`／`dep_graph` 重產，再進整合；否則每缺一項就是一輪 full-lint。
