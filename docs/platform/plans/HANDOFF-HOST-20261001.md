# 主持交接（2026-10-01，使用者下令停工）

## 正式機現況
- 正式機跑 **0bb4834e（第二十八班）**，2026-10-01 05:58 由正式機 Claude 自行套用成功，12 項檢查全過。BASELINE=0bb4834e，tag `prod/0bb4834e`。
- 待確認：月備份告警（2026-10 快照檢核不合格）預期於次日 00:00 每日備份後自癒；看 `backup_alerts` 有無新告警。
- 正式機 Claude（Remote Control「正式機套用檢查與工具檔案更新」）已有三條允許規則可自行套用；每班仍需使用者明確放行。

## 停工時進行中的線：請款單（A2）＝第二十九班（全量）
使用者裁示（全在 `docs/platform/plans/NIGHT-20260930-PLAN.md`，分支 `wip/host-plan-decisions`）：演進「新增請款」（案件額外支出）加類型支線（請購 PR／採購 PO／差旅 TE／零用金 PC）；單號 `XX-YYYYMMDD-NNNN`；簽核 部門主管→最高管理者；收款人＝員工（銀行帳號來自 `user_bank_accounts`）；有稅額欄拆進項稅、否則含稅全額；採購單由出納填匯款日與付款條件；零用金只做支付單；國外差旅先只支援新台幣；金額只對申請人／簽核人／財務出納可見；發票重複警示不阻擋；申請人欄預設鎖本人（超管可改）；費用類別獨立清單對應會計科目；案件成本計入不重複輸入；日後可不綁案件。
- 設計文件：`docs/platform/plans/expense-a2/`（plan-expense-a2.md＝總計畫與底層預留表 §6；proposal-expense-forms.md；payment-request-facts.md；w2-expense-slices-design.md；expense-forms-design-ae.md；GL-BASE-HOOKS.md；ledger-crosscheck.md）。
- 整合分支組裝：`origin/wip/train-29-assembly`（已合 W4 G1、W1 A2-0、W2 A2、W3 bank-profile；已取號、重產產生檔；156 題守門測試綠；**尚未跑整合 pre_train_check、未建包**）。
- 各視窗分支與交接：見各自 `HANDOFF-W{1,2,3,4}-20261001.md`（同目錄）。
- 合併順序：W4 G1 → W1 A2-0 → W2 A2 → W4 g2-5 → W3 bank → dept-dim → map-zoom → dates → W1 表單畫面（A2-2/A2-4/A2-7）最後。
- 預估：各片完成約 12～16 小時＋預檢 15 分＋全量建包 40 分＋稽核演練 2 小時＋套用（約 16～20 小時）。關鍵路徑＝W1 表單畫面。
- 驗收：四種單據各一條 e2e（送出→簽核→出納付款→總帳分錄→營運報表列）＋截圖。

## 出包流程（不變）
合併 → `train_number.py assign --base origin/platform` → 重產 UNIT-INDEX／dep_graph（`PYTHONUTF8=1 python tools/platform/dep_scan.py`）／test_map → **先跑整合樹 pre_train_check** → ff platform → 凍結 → `build_deploy_package.ps1`（約 40 分，log 是 UTF-16，完成看 `deploy_packages` 新資料夾）→ `delivery.py publish`（簽章，金鑰路徑 D:\MOTRIX-KEYS\delivery\delivery_signing_key.pem）→ 解凍 → W4 稽核、W3 演練 → 步驟檔（仿 `prod-tasks/20261001-train28-apply.md`）→ 雲端副本 → 正式機 Claude。

## 未排入第二十九班、待排
去識別化 prodroot（`wip/w3-prodroot-2`）、時鐘守門（`wip/clock-gates-2` 596f9ae0）、預檢工具（`wip/pre-train-check` 1fdc8ad9）、檔案中心 P3（`wip/w1-attach-p3`）、既有外包人員銀行資料遮罩（contractors／vendor_contractors；需使用者決定）、總帳開帳（等會計師試算表）、獎金追回處理方式（現掛 1213 並標「待確認」）、401 媒體檔與公式 113–115（U3／U4）、固定資產 C6（`wip/w4-gl-c6`）、舊額外支出附件路徑改精確比對（W2 已修於 A2 分支）、與總帳差異頁類別層級原因分桶。

## 使用者待辦
MQ-202610-001／002 報價日期手改 10/01；Google Cloud 地圖樣式隱藏景點；舊待辦（MQ-202607-045、hmac.key 備份、D 槽舊目錄）。
