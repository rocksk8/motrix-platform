# 交接：hichan-05（整合者）第 46 班收尾＋第 47 班整合進度（2026-10-08 夜）

> 給接手的視窗（或 /clear 後的我）。**所有 SHA 先用 `git fetch; git rev-parse` 複核再信。**本檔只在 `wip/t47-handoff-05`（docs-only，從 `origin/train/t47-int` 開），**不要併進 `train/t47-int`**：建包沿用的指紋＝整棵 tracked tree，多一個 commit 就讓已跑的 run-stage 紀錄失效。

## 1. 現況（以 git 複核）

| 項目 | 值 |
|---|---|
| 正式機 | 第 46 班 `e6a2e6b6532fe61f5108d1c1f670be53feff44f7`（10-08 16:35 自動套用成功）；`origin/platform`＝`570c54fa1`（基準 commit）；tag `prod/e6a2e6b6` |
| 整合分支 | `origin/train/t47-int`＝**`8ca68a3b4`**（我的 L1 合併 `1ca650200` ＋ ab 稽核 S1–S4 跟進 `8ca68a3b4`） |
| 我的分支 | `wip/t47-paydate-l1`＝`12ca427ff`（L1 本體；**不含** S1–S4，那些只在 train/t47-int） |
| 我的 worktree（保留） | `D:\開發測試檔\t47-paydate`（本地分支 `integ/t47-l1`＝train/t47-int 的複本，追到 `8ca68a3b4`）。其餘我建的 worktree／drill 目錄／暫存都已清掉（t46-int、t47-preflight-tool、MOTRIX-FINAL-DRILL-t46/t46b）。 |

`train/t47-int` 已合入（各為 squash 一個 commit，依序）：`wip/t47-audit-fixes-r2`、`wip/t47-payslip-dispatch-e2e`、`wip/t47-po-vendor-bank`、`wip/t47-template-fix`、`wip/t47-build-optimization`、`wip/t47-train-preflight`（＋一個 preflight 守門修正 commit）、`wip/t47-full-account-strict`，再加我的 `wip/t47-paydate-l1`（L1 `helpers/payable_due_core.py`＋案件／承攬商匯款薄接線＋逾期提醒＋財務站內通知＋行事曆來源開關）與 ab 稽核 S1–S4 修正。

**尚未合入**：`wip/t47-users-list-privacy`（b5；`GET /api/users` 對非管理員遮敏感欄位；**最後合**）、b5 另有一個小 commit 要加；ab／b5 對 L1 與 R2 的獨立稽核結果由主持（node-d8）通知；`wip/t48-*`（paydate-design、paydate-gap、r2-step2）是**下一班**，不要混進第 47 班。

## 2. 剩餘整合步驟（依序；主持會給確切順序，這裡是我理解的計畫）

1. `git fetch`；在自己的 worktree 從 `origin/train/t47-int` 開本地分支；**最後**才 squash 合 `wip/t47-users-list-privacy`（衝突多半在 CHANGELOG `(next)` 區塊與 `docs/quick/changelog.md`：**每個模組只留一個 `## (next)`、一定在最上面**）。
2. 取號**最後**：`python tools/platform/train_number.py assign`（先 `--dry-run`），`--check` 要 exit 0；取號後**一定要重產**：`python tools/platform/regen_all.py`（dep_graph／UNIT-INDEX／test_map；L1 變動時另跑 `python backend/tests/platform/_l1_interface.py --update --pending`，取號後 core 版號會換成實際數字，快照要對）。
3. **預檢**（不要 commit 進列車）：`git fetch origin wip/t47-train-preflight`，把 `tools/platform/train_preflight.py`（`build_preflight.py` 已是 tracked）與 `backend/tests/platform/test_train_preflight_t47.py` **以未追蹤檔複製進整合 worktree**，`python tools/platform/train_preflight.py --static-only --base origin/platform --no-impacted`（＋需要時窄版 B 層守門檔單進程），跑完**刪掉複製的檔**並確認 `git status --porcelain --ignored` 沒有新東西。預檢綠 ≠ 閘門綠，但它在第 46 班就抓到過 BEGIN 白名單、IP 登記缺口等。
4. 正式閘門（**官方 run-stage，記錄才算數**）：`python backend/tools/build_test_reuse.py run-stage --stage not_e2e --workers 4`，再 `--stage e2e --workers 2`；環境 `MOTRIX_TRAIN=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1`，Python 用 `D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe`。起跑前查可用記憶體 ≥ 4 GB 與沒有別的 pytest。紅了就看 fail_stream（見 §4）。**凍結**：最後一個 commit 之後不再動（任何 commit 都讓兩段紀錄失效，要整套重跑）。
5. 建包：`build_deploy_package.ps1 -Product full`（需 `backend\motrix_erp.db`；用主持／使用者複製的開發庫，**用 PowerShell 萬用字元路徑複製，不手打中文路徑**；建完**刪掉該 db 複本**，包內不得有 `*.db`）。**PowerShell 5.1 在中文 worktree 路徑下，包裝腳本要先設 `[Console]::OutputEncoding = UTF8`，路徑用環境變數傳，不要寫在 ps1 內。**
6. 驗包：`verify_package.py <包> --expect-db-version 118`（明寫；本班 schema 沿用 118，**先核對新 migration 編號**：第 46 班後正式機 core 8、case 8、subcontract 6、payroll 4、`schema_version` 118；第 47 班若有新模組 migration 要列出來寫進步驟檔）；`product_select.py check --pkg <包>`；V5：包內每檔與 `git ls-tree` 的 blob 比對（只允許換行差異、4 個建包產生檔、以及 `version_manifest.json` 被建包重新序列化並補 `"time": null`——語意相同）。
7. 演練：`python tools/platform/final_drill.py --package <包> --drill-root <D:\開發測試檔\MOTRIX-FINAL-DRILL-xxx> --report <scratchpad 路徑>`（**報告一定要寫到 repo 外**，否則弄髒工作樹）；11 步要全過，冒煙含各模組探針。
8. 步驟檔：從 `docs/platform/prod-tasks/20261008-train46-apply.md` 改（同樣的**自動套用**＋**套用前備份並驗證（路徑／大小／integrity_check／schema／payslips 筆數）**＋**失敗不自行回滾**規則；驗收清單要含 **L1 新行為**：財務收到承攬商匯款／叫料匯款的到期、逾期**站內提醒**與**行事曆「付款待辦」事件**在正式機是新的；站內收件人不受信件收件人覆寫影響；第一次上線會為已寄過信的提醒各補一則站內通知；差額審核決定回應多 `paymentId`）。步驟 3 的「新功能靜態存在」**只查實際部署的程式檔**（`apply_update` 不部署 `docs\platform`）。
9. 發布：`python backend/tools/delivery.py publish --pkg <包目錄> --root "<G:\我的雲端硬碟\MOTRIX-交付>" --private-key D:\MOTRIX-KEYS\delivery\delivery_signing_key.pem`（**只傳路徑，絕不讀金鑰內容**）；之後把 `<包名>`、`package.sha256` 的 SHA256、行數／檔案數填進步驟檔，放雲端 `MOTRIX-交付\給正式機Claude_第四十七班更新步驟.md`（用 `ls` 的檔名做 `${src/四十六/四十七}` 取名，避免手打異體字），通知主持；**主持／使用者同意自動套用**，正式機 Claude（「開發機聯繫」通道）驗證步驟 0～1 全綠才套用。
10. 套用後：寫基準 commit（`backend/tests/_prod_baseline.py` BASELINE、`docs/platform/RUN-PLAN.md` §6、`docs/platform/prod-tasks/<日期>-train47-apply.md`；**docs-only，從 gated commit 開 `chore/t47-baseline`**，不推）＋`push_t47_baseline.sh`（照 `C:\Users\hichan\push_t46_baseline.sh` 改常數）給使用者用 `!` 跑；清掉自己建的 worktree／drill／暫存（精確路徑，不用萬用字元刪共用目錄）。

## 3. 這班 L1（paydate-l1）要點與風險（寫驗收／上線備註用）
- 新 L1 單位 `helpers/payable_due_core.py`（`soon`／`today`／`overdue` 日期規則、guard、寄送迴圈、站內通知、行事曆對齊 `sync_event`＋`sync_lock`）；M01（案件額外支出＋叫料匯款）、M04（承攬商匯款，`daily.check` 提供者 `subcontract_payable_due`）薄接線；M05 出納端點在 commit 之後呼叫提供者 `planned_changed`／`contractor_voucher.planned_changed`（IP-114，暫定號，列車定號）。
- **正式機新行為**：財務（財務角色＋superadmin）會收到到期／逾期的**站內通知**；承攬商匯款與叫料匯款也會建**行事曆「付款待辦」**（事件種類預設關，開關在 L1）；逾期信（預定日後第 1 個工作日一封，不週提）。通知／事件不含金額、受款人、廠商名、付款條件。
- 風險：信件類型 `payable_due_overdue` 由 M01 登記，沒有 M01 時寄信 fail-closed（只給 superadmin）；首次上線每筆已寄過信的提醒會補一則站內通知；沒有改任何角色的金額可視或選單。

## 4. 本班學到的坑（照這些做可省數小時）
- **埋住的 `## (next)`**：文字合併可能把 `(next)` 區塊擠到有版號的標題下面；`train_number assign` 只看最上面一塊，`--check` 也會說 OK，但 `test_version_slots` 在列車模式紅。每次合併後檢查每個模組 CHANGELOG（含 core）的 `(next)` 是否唯一且在最上面。manifest 的 `"version": "next"` 條目要在陣列最前面、日期時間用 `date`。
- **run-stage 的 failfast**：官方 `run-stage` 固定 `MOTRIX_FAILFAST=1`＋failfast 外掛，覆寫你的環境變數；紅的詳情不在標準輸出，在 `D:\MOTRIX-PLATFORM\tools\platform\fail_stream\<run-id>.jsonl`（`type=fail` 有 `nodeid`／`summary`／`longrepr`；用 `python -X utf8`）。自己直接跑 pytest 也行（看全部紅），但**沒有沿用紀錄**，建包會整套重跑（約 2 小時），所以最終一定要官方 run-stage。
- **指紋＝整棵 tracked tree**（`git ls-tree -r HEAD`，只扣 `tools/platform/known_flakes.json`）＋環境：任何 commit（含只改 golden／文件）都讓紀錄失效；**不要手動 `record-stage` 蓋章**（主持已明確禁止）。
- **合併後才紅的登記類**（預檢會先抓）：IP 登記表缺 `## IP-NNN` 節、`bottom_layer.json` global_tests、`test_approval_flow_scope` 的 `EXPECTED_SCOPE`／`FULL_SCOPE_BODY`、`test_begin_only_via_begin_write` 白名單（先拿鎖、單次 commit、try/finally 關連線者可登記；要寫具體理由）、golden（案件頁黃金錄製）、單位卡格式（只認 `[單位][層][穩定度][公開介面][不變式][契約題][注意]`，說明文字要移到空行之後，且 `[公開介面]` 要等於快照名稱）、wip 分支**不可帶產生檔**（`test_branch_does_not_touch_generated_files`）。
- **瀏覽器 e2e 的 15 秒逾時**在記憶體吃緊時會偶發紅：單獨重跑通過就整段重跑；不登記偶發、不改逾時。
- **記憶體**：使用者桌面 App 的 renderer 可吃 12 GB；跑重的前先查可用記憶體（≥ 4 GB）；背景 watcher 若被系統因記憶體壓力殺掉，**不要自己重開**，手動查 `gate_status` 檔。
- **背景 shell 要有完成通知**（`run_in_background`），不要讓回合默默結束（第 46 班我在 e2e 重跑後閒置了近 3 小時沒人發現）；watcher 迴圈最長 58 分鐘會自己結束，結束不代表測試結束，要再讀狀態檔。`sleep` 單獨一行會被擋，等待用 `until`／有上限的迴圈。
- **刪除只用精確路徑**（`rm -rf` 任何含萬用字元的共用暫存路徑會被擋；也曾有別的視窗誤刪我的 basetemp）；pytest basetemp 用 `%TEMP%\pt_05_<用途>`，用完刪。
- **中文路徑**：Python／PowerShell heredoc 裡手打 `開發測試檔` 在 Windows 下會變亂碼；Python 要用 `cd` 後相對路徑或 `git -C`；Write／Edit 工具用路徑時從工具輸出複製。**Python 字串裡的 Windows 路徑要用 raw string**（`\b`、`\a`、`\0` 會被吞成控制字元，第 46 班步驟檔 #9 因此壞過一次）。
- **權限分類器**：一次 Bash 內嵌 Python 改測試檔被擋過（無理由）；改用 Edit 工具即可，不要繞過。
- 指令衛生：`cd` 後用 `;` 接 git 會被擋 → 一律 `git -C <絕對路徑>` 或整串 `&&`；`git add` 目錄＝`-A`；共用 index 不碰；`D:\MOTRIX-PLATFORM` 是共用樹，**不寫**（本地 `platform` 由 push 腳本最後 `merge --ff-only`）。

## 5. 等待中／未決
- b5 的 `wip/t47-users-list-privacy` ＋一個小 commit；ab／b5 對 L1 與 R2 的獨立稽核回報；主持會給**確切合併順序**，到時才取號、才跑閘門。
- 使用者待辦（來自第 46 班）：跑 `push_t46_baseline.sh`（若 `origin/platform` 已是 `570c54fa1` 表示已跑過）、驗收項 a～j。
