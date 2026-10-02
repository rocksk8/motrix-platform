# 主持（bin-1c）交接 2026-10-03 夜（使用者 /clear 前）

> 新對話先讀本檔，再讀 `docs/platform/plans/TRAIN31-BACKLOG.md`（最底下最新）、`USER-DECISIONS-TRAIN33.md`（a3 分支 `wip/t33-remit-kinds-design-a3`）、各視窗 `HANDOFF-*-20261003.md`。以上皆在 `origin/host/quick-memory-pointer`（除另註）。記憶：`C:\Users\hichan\.claude\projects\C--Users-hichan\memory\`（MEMORY.md 索引 → `project_motrix_next_version_handoff.md`）。

## 1. 正式機現況
- **第 32 班 `52033606` 已上線**（20:31，成功無回滾）；基準已改 `52033606`（`wip/train-33-int1`、tag `prod/52033606`）。舊包 `745f3c2d` 因 c7 稽核 M-1（出納差額審核表 fee／paidAt 被行內註解吞掉）**作廢**。
- 待辦（正式機 Claude）：**2026-10-03 00:00 每日備份之後補查第 30／31／32 班步驟 3 #11**（派發新欄位可還原、勞報單個資備份含完整帳號、`case_material_payments` 一般份不含收款帳號個資份含）。結果在 `G:\我的雲端硬碟\MOTRIX-交付\正式機回報\`。
- 正式機 Claude（peer 名「Train 29 正式機部署和備份補查」，Remote Control，不回報已讀）的 auto-mode 分類器會擋 `apply_update.ps1`（Production Deploy）；需使用者在正式機視窗明說「套用」，或使用者本人加允許規則（我與它都不能替他加）。
- 已發布請款類型：公司只發布過 `purchase_req`（v1–v4，10-01 22:38～22:44，現行 v4，1 張單據釘 v2）；使用者裁示 v4 只是試做 ⇒ 第 33 班做「複製出貨範本到草稿」。

## 2. 使用者授權與規則（不可忘）
- 常設授權（2026-10-02 晚）：**驗證完整通過的更新包直接送正式機套用，不用等使用者確認**。條件全成立才套：作者以外的稽核無 must-fix、演練 PASS、探針 CLEAN、包完整性 PASS、正式機暫存驗證與步驟 0 全過；任一沒過 ⇒ 不套用、回報。套用前先暫存驗證；失敗只用步驟 4 程式回滾（不碰 DB 回滾）。涉及權限／金額可見度／口徑變更仍先問使用者（選單，一題一決定）。
- 不碰簽章私鑰內容（只用路徑 `D:\MOTRIX-KEYS\delivery\delivery_signing_key.pem` 呼叫 `delivery.py publish`）；不繞過分類器；不替別的視窗放行被擋的動作。
- 溝通：繁體中文、結論先行、簡短；重要裁示用 AskUserQuestion；時間用 `date`。

## 3. 第 33 班（尚未發車；預計 33A 約 10/9、33B 約 10/14–15，估計）
**範圍（使用者裁示）**：33A＝材料申請強制採購單（M1／M3）＋精算頁重做（沖銷規則 A；A1→A2→A4→A3→B1→B2）＋31-B 匯款款別（款別可由公司調整；S0–S5）＋工具鏈無視窗；33B＝變更申請 M2、出貨單連動 S1–S3、K-2 並行戳、設計器兩處預設開（D12）、請購類型範本重發（D14 複製出貨範本到草稿、D15 逐項採用）、建包優化（author_gate、step 3 影子）。**財務其餘（固定資產 C6、401、總帳開帳）停止不做。** 建構器分頁掛載已完成（「我的工作」第 30 班）。
**已裁示（全部）**：D1 無人硬拆（舊單維持）；D2 款別隨**派發狀態**、公司可調、預設四種（訂金：已確認～完工；進度款：已確認～已驗收；完工款／驗收款：已驗收或完工）；D3 比例或固定金額；D4 逐期算、最後一期補到與整筆一致；D5 個人點工只掛最後一期；D6 手續費門檻 500；D7 全額付款舊材料申請不能改金額＋新額不低於已付（A＋B，調整另開調整單）；D8 手填實際取代、採購金額不另加（只警示）；D9 未對應支出只警示；D10 後端重算超過進位誤差拒絕完結；D11 發票可事後補（無發票日不產生應付認列分錄）；D12 設計器兩處都預設開（可切回；須先完成真滑鼠拖放人工驗證）；D13 待審核計入並標示、完結只警示；D14 purchase_req v4 試做 ⇒ 複製出貨範本到草稿；D15 逐項採用；E1 只能從已核准採購單明細帶入；E2 採購單須已核准；E3 有對應採購單的材料申請不再開匯款申請；**E4 一品項一筆材料申請、追加走變更申請重簽**；E5 到貨整筆、可選填實收數量；E6 出貨單不強制連結（有已到料且有剩餘量卻沒連時送審前警示）；N1 額外採購以採購單為單位各一筆；N2 自動涵蓋該品項所有已核准採購單行；N3 變更待審期間原內容照常有效。S-1 舊派發編輯維持舊單；強制採購單（材料申請必須有已通過採購單才能送審）。
**未問（有預設）**：無；本班題目已全答。
**整合樹**：`wip/train-33-int1`（基準 `52033606` 提交 `faf36bb8` 之上，已併 a3 的 31-B S0＋S1；**滾動整合**：各片到齊就併、每日跑階段）。

## 4. 視窗與分支（sha 以 `git ls-remote` 為準；各視窗交接檔有細節）
- **2e**（案件模組：材料申請連結、精算、強制採購單、出貨規格）：`wip/t32-settlement-2e`/`wip/t33-settlement-2e`（A1–A4 進行中）、規格 `wip/t32-material-link-spec-2e`（MATERIAL-FORCE-PO-AND-SHIPPING-SPEC rev.2、SETTLEMENT-ACTUALS-SPEC）、`wip/t33-material-link-fix-2e`（有效連結排除，與 d7 `wip/t33-link-guard-d7`）。交接：`HANDOFF-2e-20261003.md`。
- **d7**（建包優化、31-C 守門檔）：`wip/t33-nowindow-d7`（預設無視窗）、`wip/t33-dict-comment-d7`（字典鍵註解吞鍵守門）、`wip/build-opt2-d7`（failfast／stage reuse／step 3 影子）、`wip/t33-m1-d7`（強制採購單守門側）。交接：`HANDOFF-D7-20261003.md`。
- **a3**（請款類型、author_gate、演練、31-B）：`wip/t33-remit-s2-a3`（S0→S1→S2）、`wip/t33-author-gate-a3`（含 guard_patterns.json）、`drill/train32`。author_gate 真實回放窗口**取消，改日再排**。交接：`HANDOFF-A3-20261003.md`。
- **c7**（設計器、稽核）：`wip/t33-diff-default-c7`（default_for）、`wip/t33-k2-c7`、`audit/train32-c7`；稽核改**滾動**（作者每推一片就審）。交接：`HANDOFF-C7-20261003.md`。
- **視窗 E（31-B）／F（出貨單）**：使用者尚未開；開了讀 `NEW-WINDOW-ONBOARDING-TRAIN33.md`；a3 要寫 31-B 交接。

## 5. 流程與教訓（這班血淚）
- 整合 5～7 輪才全綠：每輪露出作者沒跑的守門（e2e marker、登記表、changelog 順序、字級 vh、金額往返、spec owner map、表單版本、權限目錄顯示名…）。**對策**：作者推最終 sha 前跑 `author_gate`（a3，`AUTHOR-GATE-USAGE.md`），含整個 `tests/platform`＋樣式守門；階段結果綁樹，cherry-pick 會使它失效 ⇒ 修正批次合併後再跑。
- 階段流程：`python backend/tools/build_test_reuse.py run-stage --stage not_e2e|e2e`（`.venv312`，共用樹 `D:\MOTRIX-PLATFORM` 乾淨且不得被寫），綠後 `build_deploy_package.ps1 -Product full`（約 25 秒，重用）→ `delivery.py publish --pkg ... --root "G:\我的雲端硬碟\MOTRIX-交付" --private-key <路徑>` → 套用步驟檔（仿 `prod-tasks/20261002-train32-apply.md`）→ 通知正式機暫存驗證 → 稽核／演練／探針 → 「可以套用」。
- 取號順序：先 `_l1_interface.py --update --pending`，再 `train_number.py assign --base origin/platform`，再 `dep_scan.py`／`test_map.py`／`unit_index.py`；合併後檢查 UU。
- 彈視窗：根因是分離行程啟動下子行程會開主控台；`nowindow.py`（a3）＋d7 的 conftest 安裝；第 33 班發版後根治。
- 我的 cron 會在 /clear 後消失：需重建「第33班主持巡檢」（每小時）與「主持定期檢討」（每 3 小時 :23）與「每三天建包優化檢查」。

## 6. 立即待辦（新對話第一件事）
1. 讀各視窗交接檔、`git ls-remote` 核對 sha，更新 TRAIN31-BACKLOG。
2. 10-03 00:00 備份後確認正式機 #11 補查結果（讀回報資料夾）。
3. 提醒使用者：D 槽舊目錄待手刪（見記憶 project_motrix_pending_cleanup）；視窗 E／F 是否開；正式機 Claude 權限規則是否要加。
4. 恢復第 33 班開發：重新派工（照各視窗交接檔）；滾動整合到 `wip/train-33-int1`。
