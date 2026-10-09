# 公益捐款改「報價含稅 1%」切換 Runbook（第 52 班；給步驟檔用）

作者：ab。範圍：把未精算報價單的公益捐款從「直接毛利 × 1%（虧損 0）」切到「報價含稅金額 × 1%」。程式隨列車上線時 **公益基數預設 `direct`＝新行為關**（`charity_basis_mode` 缺鍵），上線本身不改任何數字；本 Runbook 才是切換。
設計與算式：`CHARITY-QUOTE-1PCT-DESIGN-T52.md`。工具：`backend/tools/charity_migrate.py`（凍結算式 `backend/migrations_frozen/t52_charity/recalc.py`）。

## 0. 前置
- 程式版本已含第 52 班（`GET /api/overhead/settings` 回應有 `charityBasis:"direct"`、`charityMigrationDone:false`）。
- **管銷口徑已完成 48b 切換**（`overhead_rule_mode=v2` 且 `overhead_migration_done` 標記存在）。工具在前置不符時拒絕（結束碼 2）。
- 全程在**系統停用／無人編輯**的時段（工具交易內已重檢查已精算／結案，但仍以停機為準）。
- 記下基準：未精算且 `formulaVer=2` 件數；已精算／已結案件數與**這些單 `data_json` 的 SHA256 清單**（存檔，切換後逐張比對）。

## 1. 備份（必做）
關服務→複製 `motrix_erp.db` → `<備份資料夾>\motrix_erp.db.pre_charity_<yyyymmdd_hhmmss>`；驗證：大小相同、`PRAGMA integrity_check=ok`、`python tools/charity_migrate.py --db <備份檔> mode` 印 `charity_basis_mode = direct`。`recalc --apply` 另會在庫旁自動做 `<庫>.pre_charity_<時間>.bak`。

## 2. 影響報告（唯讀，在庫的複本上跑）
```
python tools/charity_migrate.py --db <庫複本> report --top 10 --csv <報告資料夾>\charity_plan.csv
```
輸出：筆數 `{"recalc":N,"skip_settled":…,"skip_done":…,"skip_not_v2":…,"skip_nodata":…}`；『公益捐款合計 舊→新』『營業利益合計 舊→新』；**『營業利益率 ≥ 12% 的達標件數（重算件）舊→新』**；變動最大前 10 筆；`skip_not_v2`（未結案卻還不是新管銷口徑，不在本次範圍）單號；資料不足單號與原因。
解讀：新基公益金＝含稅 × 1%，幾乎所有案件都比「直接毛利 × 1%」大，營業利益變小、達標件數可能下降——**使用者看過再決定**。價格、稅額、管銷分攤都不變；已精算／已結案不動；獎金基數＝完結凍結的營業利益 ⇒ 已完結案獎金不變，重新開啟再完結才用新算法。

## 3. 使用者核准閘門
使用者明確回覆「核准切換」（含是否接受略過件與達標數變化）才進第 4 節。沒有核准 ⇒ 維持 direct，零影響。

## 4. 切換（單一指令、單一交易）
```
python tools/charity_migrate.py --db <正式庫> recalc --apply --set-total
```
先自動備份；`BEGIN IMMEDIATE` 後才規劃、逐張重讀並再檢查已精算／結案；同一交易寫：重算件的 `tot.charityDonation/totalIndirect/netProfit/netMarginPct` ＋ `tot.charityBasis="total"` ＋ `tot._legacyCharity`（舊值，回滾依據）＋ `tot._recalc` 註記＋欄位 `net_margin_pct`、伺服器端舊值快照 `charity_legacy_snapshot`、完成標記 `charity_migration_done`、模式 `charity_basis_mode=total`。
輸出：`已重算 N 張（期間已精算而略過 M 張）；公益基數模式已設 total`。非 0 結束碼或錯誤 ⇒ 不重試、不自行回滾，先把服務啟動回來並回報（資料庫未被改變）。

## 5. 切換後檢查
1. `charity_migrate.py --db <庫> mode` ⇒ `total`；`GET /api/overhead/settings` ⇒ `charityBasis=total, charityMigrationDone=true`。
2. N 與第 2 節 `recalc` 件數一致；M 應為 0，非 0 要說明。
3. **已精算／已結案單 `data_json` SHA256 與第 0 節清單逐張相同**（不同 ⇒ 立即停下列出單號，不處置）。
4. 抽查 3 張未精算單：`tot.charityDonation = round(tot.total × 1%)`、`tot.totalIndirect = adminCost + charityDonation`、`tot.charityBasis = "total"`、營業利益率與報告 CSV 該列一致、價格不變；報價單頁標籤「公益捐款（報價含稅 1%）」。
5. 新建一張報價單：公益＝含稅 × 1%（含虧損案）；開一張已結案舊單：標籤「公益捐款（直接毛利 1%）」、數字與切換前相同。
6. 任一未精算單走精算頁：公益金＝報價含稅 × 1%；超管可見「調整管銷比率」輸入框（非超管看不到）。

## 6. 回滾（使用者決定）
- 暫停新基：`python tools/charity_migrate.py --db <庫> mode direct --apply`（同 `PUT /api/overhead/settings charityMode=direct`）會**刪除完成標記**；之後再切 total 必須重新 `recalc --apply --set-total`。已寫入的單據數字不回改。
- 工具回滾（優先）：`rollback` 先看報告（可還原／因『遷移後已完結·已編輯·已退回舊基』不還原的清單），確認後 `--apply`：依 `_legacyCharity`／伺服器快照還原未動過的單，模式設回 `direct`、刪標記。**先回滾公益、再回滾管銷**（管銷回滾遇到公益已改過的單會視為已編輯而不還原）。
- 還原 DB 備份：關服務、覆蓋 `motrix_erp.db`、啟動、確認 `mode`＝`direct`；會丟掉切換後所有新資料。
- 程式碼回滾：舊程式不認得 `charityBasis`，會把新基單當舊基重算——程式回滾前必須先做工具回滾。
- 管銷口徑退回 legacy 時公益基數一併失效，**三條路徑一致**：`PUT /api/overhead/settings ruleMode=legacy`、離線 `overhead_migrate.py mode legacy --apply`、離線 `overhead_migrate.py rollback --apply`（有還原時）都會在同一交易把 `charity_basis_mode` 設回 `direct` 並刪 `charity_migration_done` 標記。
- **順序**：先 `charity_migrate.py rollback`、再 `overhead_migrate.py rollback`（反向）。管銷口徑每次重新 `recalc`（含回滾後重做）之後，**必須重跑** `charity_migrate.py recalc --apply --set-total` 才會重新啟用公益新基；在那之前重遷移的單是未戴戳記的直接毛利基，伺服器因無公益標記一律當 direct。

## 7. 使用者驗收清單
1. 報價單／精算／案件頁／報表／結案 PDF 的公益列：新基「公益捐款（報價含稅 1%）」，舊案「公益捐款（直接毛利 1%）」。
2. 虧損案公益金照扣（新基不再有「虧損案以 0 計」提示）。
3. 精算頁最高管理者可調管銷比率（偏離預設橘色警示＋二次確認＋稽核）；一般管理員看不到輸入框；已完結不可調。
4. 已精算／已結案數字、PDF 與切換前相同；獎金基數＝完結凍結值。
