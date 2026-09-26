# 稽核：主持的 final_drill 冒煙改讀模組宣告（wip/h-smoke-probes；擋正式 D7）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。合回前稽核。
> 對象：`origin/wip/h-smoke-probes` `ca02ce66`：共用冒煙清單只放 L1 與還沒搬遷的功能；包內模組打它的 probes 與頁面；有登記但不在包內的明列「不在安裝包」；沒宣告 probes 或 key 沒登記 ⇒ 判不過；守門「共用清單不可以含已搬遷模組的前綴或頁面」。
> ⚠ 依賴 c-probes（crm、subcontract、payroll 的 probes，第八班）：D 在稽核樹把 `ca02ce66` 與 `8c440c47` **本地合併**（不推送；衝突只在產生檔 test_map.json 與 MODULE-GUIDE.md，取 ours）再驗。

## 0. 結論

**必修 0、建議 1。** 主持點名兩點都成立。**兩包必須同班**（主持已註明）。

## 1. 實跑（D 前哨腳本，合併樹 `abc2950d`〔本地〕、git archive、不是部署包）

| 份 | 11 步 | 冒煙 |
|---|---|---|
| 完整產品 | 全過 | **45 項全 200**（L1 共用＋7 個已搬遷模組的 probes 與頁面） |
| core-only（`product_select apply --product core-only`） | 全過 | **共用清單 11 項全 200**；7 個已搬遷模組全列「不在安裝包」 |

⇒ **第 7 次前哨那兩項預期 404（`/pages/bonus.html`、`/api/cashier/payable-queue`）不再出現**；共用清單在「所有模組都不在」時沒有任何非 200，也就沒有其他條目會因某個模組缺席而變成非 200（core-only 是最壞的情況）。

## 2. 守門

- 基準 `test_final_drill_tool.py` 19 passed（-n 4）。
- D 突變 SM1：共用清單塞回 `/api/contractor-dispatches`（M04）⇒ `test_smoke_core_has_no_paths_of_migrated_modules` **紅**。

## 3. 建議

- **S-1　完整產品的報告把「還沒搬遷」寫成「不在安裝包」**：完整產品的 `skipped` 列了 `accounting`、`arap`、`case`、`supply` 四個「模組 … 不在安裝包」；這四個是 modules.json 登記過、但還沒搬進 `modules/` 的功能，**實際在包裡**（仍是 L1 router）。正式 D7 的報告讀者會以為完整產品少了會計、應收應付、案件、採購。建議分成兩種說法：「尚未搬遷（以 L1 形式在包內）」與「不在安裝包（已搬遷、被選配排除）」。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| S-1 | 新增 `migrated_module_keys`（群組含 mod: 單位，與 check_group_keys 同判準）；有 key 未搬遷的寫「尚未搬進 modules/（以 L1 形式在包內，由共用清單涵蓋）」 | wip/h-smoke-probes ba29aa44 | ✅ 14:39 D：快轉確認；突變「一律寫不在安裝包」⇒ `test_smoke_plan_derives_module_checks_from_the_package` 紅 ⇒ **關閉（ba29aa44）** |
