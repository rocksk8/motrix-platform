# 第 46 班：V9 基準 116 → 118（發行備註）

分支 `wip/t46-baseline-118`。把 V9 維護期新增的 migration v117（`_m117_payslip_void`）、v118（`_m118_payslip_signed_paid`）同號同內容追進 `db._MIGRATIONS`；`CURRENT_VERSION`＝`V9_BASELINE`＝118（`core/upgrade.py` 的字面值同步）。

## 為什麼
V9 原版已到 118。平台基準停在 116 ⇒ V9 程式碰過的庫（schema 118）會被平台 `init_db` 以 `SchemaNewerThanBaseline` 拒絕（演練 6b 紅）。成因與查法見 `docs/platform/FINAL-DRILL-REPORT.md` 與演練第 3b 步。

## 🔴 回退限制（必讀）
- 套用後第一次啟動會把正式庫 `schema_version` 寫成 **118**（不可逆）。
- **只回退程式碼無效**：回到基準 116 的舊版本，`init_db` 會因庫是 118 而**拒絕啟動**。
- 回退步驟必須是「**還原套用前的資料庫備份** ＋ 回退程式碼」，不是只換程式。步驟檔的回退段要寫明；套用前備份（`db_backups` 當日 `.done`）必須確認存在。
- 勞報單 10 個欄位（voided_*、void_reason、signed_*、payment_date、voucher_no、paid_*）由 base v117／v118 與 payroll 模組 migration 0001 **雙方冪等**建立（先看欄位在不在）；0001 變成 no-op，**不可刪除**（`module_schema_versions` 歷史）。

## 附帶變更（額外 L1 範圍）
`core/upgrade.py::verify_conversion`：`schema_version` 不再因「轉換本來就把版本補到基準」被判為『既有資料被改寫』，改為正向檢查「轉換後版本＝`V9_BASELINE`」。其他表的改寫偵測不變（突變題 `test_t46_exemption_does_not_hide_other_rewrites`）。

## 驗證
單元：`test_v9_baseline`、`test_core_upgrade`、`test_upgrade_drill`；演練 `final_drill`（3b、4a～4d、5、6a～6c）；全量閘門見分支最終回報。
