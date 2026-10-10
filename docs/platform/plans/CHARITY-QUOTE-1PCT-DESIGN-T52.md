# 公益捐款改「報價含稅 1%」＋精算頁可調管銷比率（第 52 班；規格 1 頁）

基準 origin/platform `cab72495d`。使用者裁示：(1) 公益捐款＝報價含稅金額 × 1%，不再以直接毛利為基；(2) 只重算未結案報價單，已結案不動；(3) 精算頁的管銷比率僅最高管理者可調。

## 1 算式（唯一來源 `helpers/profit_rules.py` ＋ `static/profit-rules.js`，黃金向量擴充）
- **含稅金額欄位**：`tot.total`（＝`tot.pretax + tot.tax`，`profit_guard.server_totals` 與 `calcTotals` 同式同進位；四捨五入到元）。精算側用**報價單**的 `tot.total`（報價含稅，不隨實際成本變動），summary 凍結為 `quotedTotal`。
- **新規則（`charityBasis = "total"`）**：`公益捐款 = max(0, round_half_up(tot.total × 1%))`；**不看直接毛利、虧損案照扣**（以收入為基）；下限 0 **只設在含稅金額上**（負的含稅金額不可變成收入；total 為 0 ⇒ 0）。營業利益 = 直接毛利 − 管銷分攤 − 公益捐款（管銷算式不變：`max(直接毛利,0) × 比率`）。
- **舊規則**（`charityBasis` 缺＝`direct`）：`max(0, round_half_up(直接毛利 × 1%))`，逐位不變。
- 生效條件＝新口徑 `formulaVer = 2` 且 `charityBasis = "total"`；`formulaVer = 1`（最舊 10% 管銷）一律維持舊公益基。**不新增 formulaVer 3**：現有 20+ 處 `formulaVer === 2` 判斷（標籤、PDF、Excel、獎金）不用動；公益基另用獨立戳記，與管銷口徑互不牽連。
- 簽名（`ACTIVE_CHARITY_BASIS` 預設 `direct`；伺服器一律明確傳入，不依賴預設）：`quote_profit(..., total=None, charity_basis=None)`、`settlement_profit(..., quoted_total=None, charity_basis=None)`、`charity(direct, total=None, basis=None)`；`basis` 缺省＝模式開關（`ACTIVE_CHARITY_BASIS` 與 ver 同為唯一切換點）。

## 2 欄位／設定／戳記
- 設定：`charity_basis_mode`（`direct`｜`total`，預設 `direct`＝程式上線零行為變更）；`charity_migration_done` 標記。**有效基數＝total 的條件**：`overhead_rule_mode=v2` 且 `overhead_migration_done` 且 `charity_migration_done` 且 mode=total，缺一就當 `direct`（失效安全）。API：`/api/overhead/settings` 擴充 `charityMode`（切 total 需 `confirm:true` 且上述前三項俱備，否則 409）；切回 direct 刪標記；**管銷退回 legacy 時公益基數強制退回 direct 並刪標記**；皆稽核。
- 戳記（只由伺服器蓋，用戶端值一律丟棄）：`tot.charityBasis`（`prepare()` 先清掉用戶端的、再依目前有效基數重蓋；舊基不帶）、`tot._legacyCharity`（遷移前的 `charityDonation／totalIndirect／netProfit／netMarginPct`，回滾依據；列入 `STAMP_KEYS`，表單重存沿用資料庫現值）；精算 summary 增 `charityBasis`（實際側＝**目前模式**，由 `fill_downstream` 蓋）、`origCharityBasis`（原始側＝**報價單自己的戳記**，與實際側分開標示，`original_side` 蓋），`quotedTotal` 沿用既有欄位；用戶端送的這三個值一律丟棄。完結比對 `charityDonation` 容差在 total 基數下改為**逐位相同**（與實際成本無關）。
- 已結案（`settle_status=finalized` 或 `deal_tag=已結案`）：存檔、重算、遷移工具都跳過；數字、標籤、PDF 與切換前 bit 相同。

## 3 影響既有數字
- 未結案 `formulaVer 2` 報價單（昨夜已重算者約 35 張）重算時 `charityDonation` 改為含稅 × 1%，`totalIndirect／netProfit／netMarginPct` 連動。**方向**：含稅額 ≥ 稅前 ≥ 直接毛利（成本與進項稅為非負時）⇒ `total×1% ≥ direct×1%` 恆成立 ⇒ 公益金只增不減、營業利益只減不增（增量約 1% × (含稅額 − 直接毛利)，約 0.6～1% 的含稅額）；12% 門檻達標件數會下降，`charity_migrate.py report` 列「達標件數 舊→新」。
- 未結案 `formulaVer 1`（尚未切 v2 者）：不動。已結案：不動。獎金基數＝完結凍結的營業利益 ⇒ 已完結案不變，重新開啟再完結才用新算法。
- 價格（含稅總額、稅額）不變。

## 4 標籤
`公益捐款（報價含稅 1%）`（`charityBasis=total`）；舊基維持 `公益捐款（直接毛利 1%）`（目前舊字樣「公益捐款（1%）」者一併改為此，因舊基確為毛利 1%——**僅標籤補充說明，不動數字**）。範圍：報價單表單、精算頁（含橋接圖、說明文字、虧損下限提示——新基不顯示「虧損案以 0 計」）、案件管理／報表頁、結案 PDF／營運報表 PDF／Excel、獎金明細列（`bonus.py` row_label 增 charityBasis）。依 summary／tot 戳記判斷（標籤與數字永遠同源）。

## 5 精算頁調整管銷比率
現況：精算頁只**顯示**（`ohPct` 取 `_origTot.overheadPct`；後端 `_profit_basis` 讀報價單 `tot.overheadPct`）。新增 `PUT /api/quotations/{no}/overhead-pct`（`require_superadmin`；已精算／結案、`tot.formulaVer≠2`、`overhead_rule_mode=legacy` ⇒ 409；`parse_pct` 0～100／1 位小數；偏離預設需 `confirm:true`；稽核沿用既有動作 `quotation.overhead_pct_change`）：在**同一個 `BEGIN IMMEDIATE`** 內更新 `data_json.overheadPct／tot.overheadPct`、`net_margin_pct` 欄位與 **`updated_at`**，並以 `server_profit` 重算 `tot` 利潤欄位（同表單機制，不另寫算式；公益基數用**該單自己的戳記**，不看目前模式）。**開著舊表單的人**：`PUT /api/quotations/{no}` 的樂觀鎖（`_expectedUpdatedAt`）檢查提前到 `profit_guard.prepare()` 之前，故得到 409『已被其他人更新』，而不是因比率 ≠ 現值被當成改比率而吃 403。精算頁：僅 superadmin 顯示輸入框；偏離預設橘色警示＋二次確認；非 superadmin 無輸入框、直呼端點 403。

## 6 遷移與 Runbook
新獨立工具 `backend/tools/charity_migrate.py`（`report|recalc|rollback|mode`；不動 `overhead_migrate.py`）＋凍結算式 `migrations_frozen/t52_charity/recalc.py`（只用標準庫）：只重算未結案 `formulaVer 2` 且無 `charityBasis` 者；管銷分攤沿用存值；**營業利益與率照線上雙精度路徑**（`net_f = float(direct) − float(totalIndirect)`，率＝`round_half_up(net_f/pretax×100, 10)/10`，與 t48/t50b 同）；同交易寫 `_legacyCharity`、`charity_legacy_snapshot`、標記、模式；前置：overhead v2＋標記，否則拒絕；已結案以 SHA256 前後相同驗證；`recalc` 自動備份；`rollback` 依 `_legacyCharity`／快照還原（遷移後已結案／已編輯者不還原並列出，並還原 t48 的 `_recalc`），成功後模式設回 direct 並刪標記。Runbook `CHARITY-QUOTE-1PCT-CUTOVER-RUNBOOK-T52.md` 仿 OVERHEAD-25PCT 版（備份→報告→使用者核准→單一指令→檢查→回滾）。

## 7 測試計畫
黃金向量（含虧損、total=0、進位邊界、舊基 bit 同）＋node/Python 等值；`profit_guard` 伺服器重算（模式 direct／total、偽造戳記、結案不動）；精算：伺服器重算與頁面同值、完結凍結 `quotedTotal`；overhead-pct 端點（非超管 403、結案 409、偏離需確認、稽核、重算）；遷移工具 subprocess 切換測試（未結案變、結案 SHA 不變、回滾還原）；標籤測試（新舊基各一，PDF／Excel／獎金列）；前端 e2e（超管看得到輸入框並有橘色警示＋二次確認，非超管無輸入框）；單一來源守門更新。`(next)` 區塊每模組一則（case／payroll／analytics）。
