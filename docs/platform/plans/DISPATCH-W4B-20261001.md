# 派工：W4 收尾（新視窗，主持 bin-1c，2026-10-01）

你是新接手 W4（總帳）收尾的視窗。對主持 `bin-1c` 回報（SendMessage，精簡英文；每則第一行＝視窗名｜worktree｜分支@sha；不接受「進行中」，要給 ETA 或卡點）。使用者回覆繁中。

## 開工
1. 讀 `docs/platform/plans/HANDOFF-W4-20261001.md`（在 origin/wip/w4-g2-5）全文，尤其 §4 的坑。
2. 自己的 worktree：`git worktree add D:\開發測試檔\w4b-<時間> -b wip/w4-g2-5b origin/wip/w4-g2-5`。不動 D:\MOTRIX-PLATFORM 共用樹；不改 `wip/w4-g2-5`（新分支推新名，不強推）。
3. python：`D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe`；pytest 加 `--basetemp=%TEMP%\<唯一名>`，用完刪。

## 全機測試上限
同時最多 2 組全量（-n 2）。目前 hichan-2e、hichan-a3 都會跑。**要跑 pre_train_check 或 accounting 全量前，先 SendMessage 主持排時段。** 單檔／小範圍可直接跑。

## 工作順序（今天這班要收）
| # | 工作 | 判準 |
|---|---|---|
| 1 | 驗 A5 慣例發現（83eb814a）：跑 HANDOFF §4 的四檔指令；逐項查三個風險點（modtest.load_groups 未改、scope_gate 工作樹併入、deploy_insights） | 任何一項有疑慮 → 單獨 `git revert 83eb814a` 並回報；不修補 |
| 2 | G3（C7 稅額，c6201cdc）完整閘門：`pre_train_check.py wip/w4-g2-5b --workers 2`（先排時段） | 全綠；紅燈逐一歸因（本分支 vs 繼承） |
| 3 | G4：LEDGER-ACCEPTANCE.md 補「費用單據情境」一節（對應 test_expense_forms_gl_2026_10_01.py，2196-01，25 項手算） | 文件與測試項目一致 |
| 4 | G5：把 G2 的三個手動突變寫成固定守門題（tests/platform 突變清單），含正向控制 | 還原修改時題目變紅 |
| 5 | 低風險 #2：追回科目 1213 無效 → 整組不開並 notice（bonus_correction.open_vouchers；W2/payroll 檔，先確認無人在改） | 單測＋反向控制 |
| 6 | 低風險 #3：差異頁類別層級原因分桶；最便宜解＝畫面註明只有合計列有分桶，或補 tax／個人外包桶 | 先回報選哪個再做 |

## 規則
- 回報要附：SHA（push 後 `git ls-remote` 核對）、題數（貼 pytest 摘要行）、查過的 vs 推論的分開寫。
- 突變前先 commit；修檔腳本要 assert；e2e 等這次動作的終點。
- 超過 90 分鐘無 commit，主持會追問。
- 完成一項就 push 一次，不累積。
- 使用者若直接對你下新需求：回「我是子視窗，已轉主持 bin-1c」，並逐字轉給 bin-1c，不自行執行。
