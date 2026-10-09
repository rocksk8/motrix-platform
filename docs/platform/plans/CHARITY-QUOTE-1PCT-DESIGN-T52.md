# 公益捐款改「報價含稅 1%」＋精算頁可調管銷比率（第 52 班；規格 1 頁）

基準 origin/platform `cab72495d`。使用者裁示：(1) 公益捐款＝報價含稅金額 × 1%，不再以直接毛利為基；(2) 只重算未結案報價單，已結案不動；(3) 精算頁的管銷比率僅最高管理者可調。

## 1 算式（唯一來源 `helpers/profit_rules.py` ＋ `static/profit-rules.js`，黃金向量擴充）
- **含稅金額欄位**：`tot.total`（＝`tot.pretax + tot.tax`，`profit_guard.server_totals` 與 `calcTotals` 同式同進位；四捨五入到元）。精算側用**報價單**的 `tot.total`（報價含稅，不隨實際成本變動），summary 凍結為 `quotedTotal`。
- **新規則（`charityBasis = "total"`）**：`公益捐款 = round_half_up(tot.total × 1%)`；**不設下限 0**（以收入為基，虧損案照扣；total 為 0 ⇒ 0）。營業利益 = 直接毛利 − 管銷分攤 − 公益捐款（管銷算式不變：`max(直接毛利,0) × 比率`）。
- **舊規則**（`charityBasis` 缺＝`direct`）：`max(0, round_half_up(直接毛利 × 1%))`，逐位不變。
- 生效條件＝新口徑 `formulaVer = 2` 且 `charityBasis = "total"`；`formulaVer = 1`（最舊 10% 管銷）一律維持舊公益基。**不新增 formulaVer 3**：現有 20+ 處 `formulaVer === 2` 判斷（標籤、PDF、Excel、獎金）不用動；公益基另用獨立戳記，與管銷口徑互不牽連。
- 簽名：`quote_profit(..., total=None, charity_basis=None)`、`settlement_profit(..., quoted_total=None, charity_basis=None)`、`charity(direct, total=None, basis=None)`；`basis` 缺省＝模式開關（`ACTIVE_CHARITY_BASIS` 與 ver 同為唯一切換點）。

## 2 欄位／設定／戳記
- 設定：`charity_basis_mode`（`direct`｜`total`，預設 `direct`＝程式上線零行為變更）；`charity_migration_done` 標記（沒有標記伺服器一律當 `direct`，比照 `overhead_migration_done`）。API 比照 `/api/overhead/settings` 擴充 `charityBasis`＋`confirm:true`＋標記才可切；稽核。
- 戳記（只由伺服器蓋，用戶端值一律丟棄）：`tot.charityBasis`（`total`；舊口徑不帶）、`tot._legacyCharity`（遷移前的 `charityDonation／totalIndirect／netProfit／netMarginPct`，回滾依據，接 `_legacy`）；精算 summary 增 `charityBasis`、`quotedTotal`；原始側 `origCharityBasis`。
- 已結案（`settle_status=finalized` 或 `deal_tag=已結案`）：存檔、重算、遷移工具都跳過；數字、標籤、PDF 與切換前 bit 相同。

## 3 影響既有數字
- 未結案 `formulaVer 2` 報價單（昨夜已重算者約 35 張）重算時 `charityDonation` 改為含稅 × 1%、`totalIndirect／netProfit／netMarginPct` 連動；公益金幾乎都變大（含稅 1% 通常大於直接毛利 1%：毛利率低於約 100% 者都如此）、營業利益變小；12% 門檻達標件數會下降，報告需列「舊→新達標數」。
- 未結案 `formulaVer 1`（尚未切 v2 者）：不動。已結案：不動。獎金基數＝完結凍結的營業利益 ⇒ 已完結案不變，重新開啟再完結才用新算法。
- 價格（含稅總額、稅額）不變。

## 4 標籤
`公益捐款（報價含稅 1%）`（`charityBasis=total`）；舊基維持 `公益捐款（直接毛利 1%）`（目前舊字樣「公益捐款（1%）」者一併改為此，因舊基確為毛利 1%——**僅標籤補充說明，不動數字**）。範圍：報價單表單、精算頁（含橋接圖、說明文字、虧損下限提示——新基不顯示「虧損案以 0 計」）、案件管理／報表頁、結案 PDF／營運報表 PDF／Excel、獎金明細列（`bonus.py` row_label 增 charityBasis）。依 summary／tot 戳記判斷（標籤與數字永遠同源）。

## 5 精算頁調整管銷比率
現況：精算頁只**顯示**（`ohPct` 取 `_origTot.overheadPct`；後端 `_profit_basis` 讀報價單 `tot.overheadPct`）。新增 `PUT /api/quotations/{no}/overhead-pct`（`require_superadmin`；已結案 ⇒ 409；`parse_pct` 0～100／1 位小數；偏離預設需 `confirm:true`；稽核 `quotation.overhead_pct`）：在同一交易更新 `data_json.overheadPct／tot.overheadPct` 並以 `server_totals／server_profit` 重算 `tot` 利潤欄位（即報價單表單同一機制，不另寫算式）。精算頁：僅 superadmin 顯示輸入框；偏離預設橘色警示＋二次確認；非 superadmin 無輸入框、直呼端點 403。

## 6 遷移與 Runbook
`overhead_migrate.py` 增子指令 `charity report|recalc|rollback|mode`（凍結算式放 `migrations_frozen/t52_charity/recalc.py`，比照 t48）：只重算未結案 `formulaVer 2` 且無 `charityBasis` 者，同交易寫 `_legacyCharity`、標記、模式；已結案以 SHA256 前後相同驗證；`recalc` 自動備份；`rollback` 依 `_legacyCharity` 還原（遷移後已結案／已編輯者不還原並列出）。Runbook `CHARITY-QUOTE-1PCT-CUTOVER-RUNBOOK-T52.md` 仿 OVERHEAD-25PCT 版（備份→報告→使用者核准→單一指令→檢查→回滾）。

## 7 測試計畫
黃金向量（含虧損、total=0、進位邊界、舊基 bit 同）＋node/Python 等值；`profit_guard` 伺服器重算（模式 direct／total、偽造戳記、結案不動）；精算：伺服器重算與頁面同值、完結凍結 `quotedTotal`；overhead-pct 端點（非超管 403、結案 409、偏離需確認、稽核、重算）；遷移工具 subprocess 切換測試（未結案變、結案 SHA 不變、回滾還原）；標籤測試（新舊基各一，PDF／Excel／獎金列）；前端 e2e（超管看得到輸入框並有橘色警示＋二次確認，非超管無輸入框）；單一來源守門更新。`(next)` 區塊每模組一則（case／payroll／analytics）。
