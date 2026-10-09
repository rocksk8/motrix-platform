# 加速方案：把登記／守門類紅燈提前到推送前（第 50 班設計諮詢，唯讀）

> 作者 hichan-05，2026-10-09。資料＝`git log --no-merges` 對 `origin/train/t46-int … t49-int` 各自相對上一班基準：共 55 筆提交，扣掉功能／稽核合入 11 筆、取號 5 筆，剩 **39 筆修正／重產提交**，逐筆讀標題歸成 **約 45 件紅燈事件**（一筆提交可能修好幾個紅，例如 `42a32199f` 同時算 3 類）。
> 因此數字是提交層級的估計，不是 fail_stream 的精確計數（舊班的 fail_stream 已不在）。沒有跑任何重測試。

## 1. 整合期紅燈分類（第 46～49 班）
| # | 類別（守門） | 筆數 | 例 | 誰抓得到 |
|---|---|---|---|---|
| 1 | `(next)` 沉底／重複（A1、`test_version_slots`） | 4（另：t50-pre 預演時 7 個模組各出 2 塊） | t46 `4be81f3c1`、`1a56e9729`；t48 `9514c1cd8`；t47 `83e15057a` | **整合時才出現**（兩支分支各自一塊，合併後 2 塊） |
| 2 | 程式改動晚於版號標題（`test_module_changelog_follows_code`），含「取號後又改程式」 | 7 筆／3 班 | t47 arap 連 3 次（`544b80f43`→`090c77061`）、case `c107fd8fd`；t49 `16bfe0f08` | 作者（只動自己模組）＋整合者（取號後的任何修正） |
| 3 | 登記表／清單類：BEGIN 白名單、approval_flow_scope、bottom_layer global_tests、IP 章節、寫入端點稽核 EXEMPT、EM1／EM3 基準、final_verify 棘輪、規格編號撞名／`spec_impl_modules`、「叫料」字樣、船運分級能力字串 | **15** | t46 `e6a2e6b65`／`709c81071`／`19303f1eb`／`3e73276a2`／`ebe1240fa`；t47 `a78459ca2`；t48 `9c1b067a9`／`42a32199f`；t49 `0b0c7f5df`／`c0d01cd57`／`8c80d1ba0` | **作者**（改動當下就會紅；其中規格編號撞名要在「含 platform 全部測試名」的樹上才看得到 ⇒ 作者基底是 platform 就看得到） |
| 4 | 版本／manifest：`FORM_VERSION`＋LEDGER、使用者可見變更漏 manifest 條目 | 3 | t47 `f6ecbdb20`、`e6bc21ab0`；t48 `42a32199f` | 作者（FORM_VERSION 純函式 0 秒；manifest 只能警告） |
| 5 | golden（案件頁錄製、路由表） | 1（t49 路由表在分支內自行處理） | t46 `f90b2b0d5` | 作者（A6 已能偵測「動了被 golden 涵蓋的頁面卻沒動 golden」） |
| 6 | 測試衛生：收集期 ImportError、裸 `get_db()`、文件死連結 | 3 | t48 `c59a45c50`；t49 `3c0fcfd03`、`35598a24b` | 作者（A8＋`compileall`／收集） |
| 7 | 產生檔過期（dep_graph／UNIT-INDEX／test_map）、取號後重產 | ~10 | t46 6 筆、t48 4 筆 | **只有整合者**（wip 分支依規定不得帶產生檔）⇒ 只能「偵測不修」 |
| 8 | 產品 bug（e2e／功能） | 2 | t46 `ced08e03a`；t48 `22a0de5a2` | 受影響頁的 e2e（test_map 選題），非靜態 |
| — | 不算守門紅：midnight 跨日 TODAY 偶發、e2e 與 not_e2e 並行的 `_drain_servers` 負載偶發 | 2 次 | t47 | 流程規則（不並行、不跨午夜）|

合計約 45 件紅燈事件：**作者推送前抓得到 ≈ 24 筆（類 2 的一半、3、4、5、6）**；**整合期才抓得到 ≈ 19 筆（類 1、2 另一半、7）**；不可靜態化 2 筆。每個閘門紅燈的代價＝failfast 停在第 16～22 分鐘＋整段重跑（t47 實測 3 次重啟、約 2 小時）；推送前檢查 ≤ 60 秒。

## 2. 推送前檢查（作者端，< 60 秒）
新增薄工具 `tools/platform/prepush_check.py`（只重用現成零件，不新寫守門）：
1. `base`＝`merge-base(HEAD, origin/platform)`；`changed = train_preflight.changed_files()`。
2. **靜態 A1～A8**（`train_preflight.static_checks`，秒級）；A0（產生檔）改為反向：分支**動了**產生檔 ⇒ 紅（沿用 `test_branch_does_not_touch_generated_files` 的判斷），不要求重產。
3. **只對動到的模組**跑 `check_module()`（`test_module_changelog_follows_code` 的函式；整支測試 72 秒是因為掃全部模組）；`FORM_VERSION` 用 `verdict()`（純函式）；「叫料」字樣掃變動的 py／html／js；變動的測試檔函式名對 `SPEC` 編號撞名（`_IMPLEMENTED_HEAD`）；動了 `frontend/pages|api/*.py` 卻沒動 `version_manifest.json` ⇒ **警告**（不擋）。
4. **便宜守門檔單進程**（依動到的路徑選，量測秒數見 `preflight_seconds.json`）：必跑 ≈ `version_manifest`(2)＋`v9_baseline`(3)＋`l1_interface_snapshot`(9)＋`begin_only_via_begin_write`(6)＋`approval_flow_scope`(4)＋`approval_queue_covers`(6)＋`version_slots`(3)＋`wording`(2)＋`dep_scan_controls`(0.2)＋`spec_coverage`(14) ≈ 50 秒；`integration_points_registered`(28)、`ship_tier`(53)、`route_table_golden` 只在動到 INTEGRATION-POINTS／提供者碼／api 時才加。超過 `--budget-sec 55` ⇒ 結束碼 3「未完成」，列出被略過的檔（hook 只警告）。
5. **絕對不做**：`train_number assign`、`regen_all`（只允許 `check_only`）、commit／push／checkout、`MOTRIX_TRAIN=1`（`(next)` 佔位在分支上本來就合法）、e2e／瀏覽器、改任何追蹤檔。輸出一頁：紅 → 檔案 → 一行修法。
6. 安裝：`.githooks/pre-push`（追蹤在 repo）呼叫上面的工具；`tools/platform/setup_prepush.py` 設 `core.hooksPath=.githooks`（與 `setup_merge_drivers.py` 同型，每個 clone 做一次，worktree 共用）；紅 ⇒ 擋推送，`--no-verify` 為明載的逃生口（用了要在推送說明寫理由）。每個視窗：開工第一件事跑 `setup_prepush.py --check`。

## 3. 整合分支的背景檢查（每個新 commit，低優先）
- `tools/platform/integ_watch.py`：整合者 worktree 的 `post-commit` hook 以分離行程啟動；**去抖 60 秒**、新 commit 到就取消上一輪；已有 pytest 群組在跑（run-stage／別人）或可用記憶體 < 4 GB ⇒ 直接略過（機器上限 2 組）。
- 內容＝上面第 2～4 步 ＋ **A0 允許開**（整合樹要求產生檔最新，`check_only`）＋ `check_module` 全模組 ＋ 窄版 B（`train_preflight` 預設窄版，≈ 600 worker 秒 ⇒ 單進程低優先約 4～6 分鐘）。結果寫 `tools/platform/full_results/integ_watch/<sha>.json` 與一行狀態檔；紅時才通知整合者（結束碼／狀態檔，不群發）。
- **合併前乾跑**：整合者要併下一支分支前，先 `git merge-tree --write-tree`（不動工作樹）列衝突檔、並指出 add/add（已被舊 squash 帶入的內容）與 `(next)` 重複；t50-pre 這次的 14 個 add/add 與 7 個重複 `(next)` 本可在排序前就知道。
- `merge_drivers.py` 的 changelog 驅動補一條：兩邊都新增 `## (next)` 時**併成一塊**（現在是兩塊並存 ⇒ 類 1 的來源）。
- 不做：自動取號、自動重產、自動 commit、自動推送。整合者看到紅燈才動手。

## 4. 預期效果與限制
- 類 3～6（≈ 22 筆／45）推送前 ≤ 60 秒擋下 ⇒ 它們不再進入整合；類 1、2、7（≈ 19 筆）在整合 commit 後 ≤ 6 分鐘內被背景檢查看到，而不是等 not_e2e 跑到第 16～22 分鐘 failfast。以 t47 為例（3 次階段重啟）預估省 1～1.5 小時／班。
- 限制：推送前檢查綠 ≠ 閘門綠（跨分支才出現的紅、完整 B／e2e 仍由 run-stage 負責）；`pre_train_check.py`（合併進 platform 後跑，約 10 分鐘）保留給「分支準備上月台」時，不併入 hook。
- 實作量：`prepush_check.py` ≈ 150 行（重用現成函式）、兩個 hook 檔、`merge_drivers.py` 一條規則＋測試；建議先做 §2（最大收益），再做 §3 的合併前乾跑與驅動規則。
