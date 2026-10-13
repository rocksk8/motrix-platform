# U0a 規格與回滾演練規格 — T57 r3（併入 0d U-1～U-7 與 1c 補充）

> 作者 hichan-98（規格與演練規格）；實作：c7（核心遷移＋演練腳本，依本規格）、2b（`strip_internal_cols`＋基準回應鍵集記錄器＋`org_units` 宣告）、5e（MS1d 之後支援審查／測試、模組自有表清單）；執行演練與閘門：5c。**僅文件；人日與日期皆為估計。**
> 依據：`FRAMEWORK-ORG-UNITS-T57.md` §14.9／§14.10（r6）、`EXECUTION-PLAN-T57.md` r9 §2.3、c7 的核心表盤點（10-13，經 1c 轉達）、0d 對 U0 的審查（M1／M2／S2／S3 與 F1～F3）、使用者 10-13 答覆（法人＝混合；U0＝是，盡快）。
> **U0a 的定義**：對使用者看得見的行為完全不變；只做加法（新欄位帶預設值、新表）；不改主鍵、不改約束、不重建既有表、不動 `db._MIGRATIONS`（凍結在 118）。

## 1 範圍與非目標
- **做**：①core 模組 migration（`module_schema_versions.core` 9→10）；②核心表加 `owner_unit_id`；③法律單據加 `legal_entity_id` 快照欄位；④`audit_log`／`notifications` 加 `unit_id`；⑤五張新表；⑥兩張權限表加 `scope_json`；⑦中央 `strip_internal_cols` 與基準回應鍵集檢查（防止 `SELECT *` 外洩）；⑧`org_units` 功能宣告（`planned`）；⑨回滾演練；⑩套用步驟檔 #12 的新預期。
- **不做**：任何過濾、介面、設定、對使用者行為的改變；模組自有表的欄位（歸 U0b／U1／U3）；序列分配器改寫（U2）；`UNIQUE` 索引改為含法人（U2）。

## 2 DDL 清單（c7 10-13 盤點；括號為待定事項）
### 2.1 `owner_unit_id INTEGER NOT NULL DEFAULT 1`（**36 張＝31 交易表＋5 主檔**；0d U-7）
- **交易表（31）**：`quotations`、`case_stages`、`case_stage_visits`、`case_updates`、`case_action_items`、`case_change_requests`、`case_extra_expenses`、`completion_notes`、`shipping_notes`、`contractor_dispatches`、`payment_requests`、`invoice_vouchers`、`contractor_payment_vouchers`、`vouchers_all`（**實體表；`vouchers` 是 VIEW，不加欄**）、`payslips`、`bonus_awards`、`bonus_case_awards`、`projects`、`project_stages`、`project_logs`、`work_logs`、`daily_tasks`、`stock_items`、`stock_batches`、`dev_cases`、`dev_logs`、`tenders`、`tender_hits`、`tender_watches`、`network_plans`、`custom_records`。
- **主檔（5）**：`customers`、`suppliers`、`contractors`、`vendor_contractors`、`parts`。**決定（98）：加欄，預設 `1`，語意＝『全域共用』（`owner_unit_id=1` 的主檔對所有單位可見）；單位專屬主檔屬 U1／U4**。理由：與使用者『主檔預設全域共用』一致、加欄成本低、避免日後重建。
- `audit_log`、`notifications`：`unit_id INTEGER NOT NULL DEFAULT 1`。
### 2.2 `legal_entity_id INTEGER NOT NULL DEFAULT 1`（不可變快照；建立時寫入，不在讀取時推導）
`vouchers_all`、`invoice_vouchers`、`contractor_payment_vouchers`、`payslips`，以及 **`payment_requests`（決定：加）**——請款單印出的抬頭與匯款帳號由法人決定（`helpers/company_identity.py`），快照才能保證日後翻轉法人旗標不改變已發出的請款單。**U0a 只加欄與預設值；寫入快照的程式（建立時依單位解析法人）屬 U1／U2，U0a 期間所有列都是根法人 `1`。**
### 2.3 五張新表（**備份涵蓋，0d U-1；決定：五張新表皆屬設定／組織資料 ⇒ 全部納入每日備份**；`SELECT *` 的備份會帶新欄位——保留，**還原須雙向容忍**（新備份還原到舊程式、舊備份還原到新程式）：五張新表必須加入 `archive._daily_backup_tables`，或明確列入排除清單；守門測試 `test_every_table_is_either_backed_up_or_explicitly_excluded` 與 BK31 的表數計數要同步更新；否則建包前即紅）
| 表 | 欄位（草案） | 備註 |
|---|---|---|
| `org_units` | `id`, `parent_id`, `name`, `code`, `is_legal_entity`（0/1）, `status`, `created_at` | 起始只有根列（id=1，`is_legal_entity=1`，名稱取今天的公司名；**公司名讀不到時的後備名稱＝『本公司』**，0d U-4） |
| `org_unit_closure` | `ancestor`, `descendant`, `depth` | 起始只有 `(1,1,0)`；主鍵 `(ancestor, descendant)` |
| `user_units` | `user_id`, `unit_id`, `is_primary`, `role_binding` | 起始：**所有使用者（含停用帳號）各一列** `(user, 1, 1, NULL)`；筆數＝`SELECT COUNT(*) FROM users`（0d U-4；步驟檔 #12 照此寫） |
| `system_settings_unit` | `unit_id`, `key`, `value_json`, `updated_at` | 起始為空；主鍵 `(unit_id, key)` |
| `seq_by_entity` | `entity_id`, `kind`, `period`, `seq`；主鍵 `(entity_id, kind, period)` | 起始為空；**根法人繼續使用既有序列表** |
### 2.4 權限表
`perm_role_caps`、`perm_user_overrides` 各加 `scope_json TEXT NULL`（空＝全部）。
### 2.5 不在 core migration 的表（由各模組自己的 migration，U0b 之後逐模組）
accounting 34、case 4（`case_material_*`）、payroll 4、lodging 4、recyclebin 1、subcontract 1、permmatrix 5（本批只加上述兩個欄位）。

## 3 遷移機制
1. **位置**：`core` 的模組 migration（`core/migrations.py`；`module_schema_versions` 的 `core` 由 **9 → 10**），**不碰** `db._MIGRATIONS`（`test_v9_baseline` 鎖在 118）。分支上用 `(next)` 佔位，版本號由列車重新指派。
2. **冪等**：每個 `ADD COLUMN` 先查欄位是否存在（**在 `core/migrations.py` 內用本地 PRAGMA helper；`db._col_exists` 在該處不可匯入**，0d U-3），每個 `CREATE TABLE` 用 `IF NOT EXISTS`；重跑不得出錯、不得改資料。**`vouchers`（VIEW）必須排除**；若某表在該安裝不存在（模組缺席或舊安裝、選配表）**跳過並回傳 None（不是丟例外）**並記 log。**`vouchers` VIEW 的 `SELECT *` 會在查詢時展開，因此會自動多出新欄位——凡是讀 `vouchers` 的出口都必須經剝除（§4）並列入基準回應鍵集檢查。**
3. **O(1)**：`ADD COLUMN … DEFAULT` 不重寫整表。**U0a 不建任何 `owner_unit_id` 索引**（0d U-2：建索引是 O(n) 且會改變索引清單）；索引一律留到 U1（屆時要列入步驟檔 #12／演練 D3 的預期）。若有人堅持在 U0a 建索引，必須先在 #12 與 D3 列出並量測建索引耗時。
4. **種子資料**：寫入根單位與閉包列、`user_units`；種子必須在同一交易內且可重跑（`INSERT OR IGNORE`）。
5. **不寫設定、不寫稽核**：部署本身不產生任何 `settings.%`、`definitions.%` 稽核列（套用步驟檔 #15 預期 0 列）。
6. **計數器事實（c7 讀碼）**：只有 `quote_seq`、`payslip_seq`、`custom_record_counters` 是真正的計數表；傳票號（`YYYYMMDD-NNN`）＝對 `vouchers_all` 以 `LIKE` 取 MAX；`PS-YYMM` ＝ `payslip_seq` 加 `MAX(payslips)` 混合；各種 `next_entity_code`、單據代碼家族＝取 MAX 加保留集合。**所以 U2 要做兩件事：每個分配器加『法人條件』，且全域 `UNIQUE` 索引（例如 `voucher_no`）必須納入法人，否則兩個法人會撞號——`seq_by_entity` 單獨不夠。U0a 不動。**

## 4 防外洩（2b）
- `internal_cols` 模組＋單一 JSON middleware＋匯出寫入器（Excel／CSV）＋`archive.py`／`table_digests`：**預設不輸出** `owner_unit_id`、`unit_id`、`legal_entity_id`、`scope_json`；功能開啟（`org_units` 宣告且 `open`）後才輸出給有權限者。
- **基準回應鍵集記錄器**：在 U0a 分支所從出的**父 commit**（`b06d7c92a`／目前 platform `0ea1d7197`）記錄 JSON 鍵集與 **Excel／CSV 表頭**；範圍＝所有含 `SELECT *` 的路由與匯出路徑（約 269／85／11／10 處的實際對外出口）加取樣路由；**U0a 凍結條件＝與基準 diff 為空**；完整約 830 路由金標屬 U0b。
- **正對照**：故意不剝除的端點（測試專用）必須使檢查轉紅，否則檢查本身可能是假綠燈。
- MS1d 不改任何回應鍵，所以基準於 MS1d 前後都有效。

## 5 `org_units` 功能宣告（2b）
`core/features_l1.json` 宣告 `org_units`：`status=planned`。**啟用條件＝『已宣告且 status==open』**（不得直接用 `spine.feature_enabled`，它對未宣告回傳 True）；測試：刪除宣告後範圍過濾（目前恆真）與剝除行為不變。

## 6 套用步驟檔 #12 的新預期（作為 U0a 步驟檔草稿的骨架，98）
- `schema_version`＝118（不變）；`db.CURRENT_VERSION／V9_BASELINE`＝118／118。
- `module_schema_versions`：`core` **9→10**，其餘列與套用前相同。
- `sqlite_master`：**多出** `org_units`、`org_unit_closure`、`user_units`、`system_settings_unit`、`seq_by_entity`（及必要索引）；其他表名、觸發器相同。
- 既有表欄位清單：**只多出** §2.1／2.2／2.4 的欄位，欄位順序與型別其餘不變。
- 資料筆數：全部既有表與套用前相同（或能用 `<t0>` 後的 audit 解釋）；`org_units`＝1 列、`org_unit_closure`＝1 列、`user_units`＝`users` 全部列數（含停用帳號）。
- `vouchers` VIEW 的欄位清單**也會多出**新欄位（在 #12 的欄位比對中分開列）。
- `CORE_VERSION` 依 core CHANGELOG 的 `(next:minor)`（預期 1.134；由列車定）。
- 步驟 3 #15：`settings.%`、`definitions.%`、`feature.%`、`spine.%` 稽核列＝**0**（部署本身不應寫任何設定、定義或功能事件）。
- 回滾段落：『資料庫保留新欄位與新表、不還原；使用者要求還原資料庫才用套用前備份』。

## 7 回滾演練規格（98 寫規格，c7 寫腳本，5c 執行）
**環境**：僅用**正式機資料庫的複本**（VR7 需要資料庫快照）與套件暫存目錄，**不碰正式機**；機器靜默（HOLD 規則：RAM ≥10GB、不與閘門同時）；輸出放 D 槽暫存、用完刪除；每個檢查項輸出『項目、預期、實際、PASS／FAIL、證據路徑』。
| 步驟 | 動作 | 預期（PASS 條件） |
|---|---|---|
| D0 準備 | 取 MS1c 狀態的資料庫複本與 MS1c 程式；建立 U0a 套件 | 複本 `integrity_check`＝ok；`schema_version`＝118；`module_schema_versions.core`＝9 |
| D1 基準擷取 | 在 MS1c 狀態擷取：`sqlite_master`（表／索引／觸發器）、每表欄位清單、各表筆數、`module_schema_versions`、基準回應鍵集（JSON＋Excel／CSV 表頭） | 存成基準檔（只讀） |
| D2 升級 | 對複本套用 U0a（沿用 `apply_update.ps1` 流程，套用前備份） | `::RESULT:: … status=success …`；啟動耗時記錄；`/api/ping` 200；`module_states.json` 全部 loaded |
| D3 結構比對 | 對升級後資料庫與 D1 比對 | 符合 §6：只多出指定表與欄位；`core` 9→10；筆數不變；`integrity_check`＝ok |
| D3b 全新安裝一致性（0d U-5） | 以同一套件做**全新安裝**（`init_db`＋全部 migration），比對其結構與 D2 升級後的正式機複本結構 | **完全相同**（表、欄位、**索引清單**、觸發器、`module_schema_versions`）；種子資料（根單位、閉包、`user_units`）一致 |
| D4 行為等價 | 回應鍵集與基準 diff；匯出表頭 diff | **diff 為空**；**正對照**：啟用測試用不剝除端點 ⇒ 檢查轉紅 |
| D5 冪等重跑 | 對已升級的資料庫再跑一次 core migration | 無錯誤、無資料變動、`core` 仍 10 |
| D6 程式回滾（不還原資料庫） | `rollback_update.ps1 -SnapshotTimestamp <時間戳> -Yes`（**不加任何資料庫參數**）回到 MS1c 程式，資料庫保持 U0a 狀態 | `commit` 回 MS1c；`/api/ping` 200；`module_states.json` 全 loaded；**舊 loader 對 `core=10` 的行為被記錄**（容忍／拒絕／警告）；log 無 Traceback；`module_schema_versions.core` 的處理依結果 |
| D6b 回滾後再記錄基準回應鍵集（0d U-5） | 在 D6 狀態重跑基準回應鍵集記錄器 | 與 D1 基準 diff 為空（舊程式沒有新欄位可洩漏，但仍須確認匯出表頭未變） |
| D7 回滾後功能冒煙 | 在 D6 狀態上做：建立報價單取號、傳票取號、勞報單取號（`quote_seq`／`vouchers_all` MAX／`payslip_seq`）；各主要頁面 GET；一筆寫入與讀回 | 取號成功且不撞號；舊程式忽略新欄位；匯出不含新欄位 |
| D8 若舊 loader 不容忍 | 設計回滾工具在同一動作內把 `core` 還原為 9 並驗證 | 回滾工具改動寫入步驟檔回滾段落；D6／D7 重跑通過 |
| D9 資料庫還原路徑（使用者明確要求才用） | `-IncludeDatabase -ConfirmDatabaseOverwrite` 從套用前備份還原 | 資料庫與 D1 基準逐項相同（diff 為空） |
| D10 再前進 | 回滾後再套用 U0a | 與 D2／D3 相同結果（冪等） |
| D11 驗證工具 | 對 U0a 套件跑 `verify_package`（`--expect-db-version 118`）與 VR7（資料庫快照）；更新欄位清單基準 | 皆通過；**正對照**：缺一欄位的套件必須使檢查轉紅 |
| D12 步驟檔 #12／#15 試跑 | 在 D2 後的複本上**用真正的 `apply_update.ps1` 與步驟檔文字**逐字執行 #12 與 #15 的每個命令 | 輸出與 §6 預期相符；**#15 稽核列＝0**；步驟檔文字無需臨場改寫 |
| D13 報告 | 彙整表＋證據；列出所有 FAIL／警告／未決 | 交 0d；任何 FAIL ⇒ U0a 不凍結 |
**注意**：演練腳本本身要有『自我測試』（對一個故意壞掉的複本必須回報 FAIL），避免腳本假綠。演練需要一個機器時段（預留 10-20／10-21，見計劃書 §3.2）。

## 8 交付與移交
- **≈10-20 交 0d（並行審查）**：核心 migration 檔、表清單（本規格 §2）、演練腳本與其自我測試、基準回應鍵集檔與記錄器、`org_units` 宣告。
- **U0a 凍結條件**：①0d PASS；②演練 D0～D13 全 PASS（含 D6 對舊 loader 行為的實測紀錄）；③回應鍵集 diff＝空且正對照有效；④全 `tests/platform` 與預檢 A1～A8＝0；⑤步驟檔草稿（98）對凍結樹逐項核對。
- **套用**：依步驟檔（正式機 Claude 自動套用，步驟 0～1 全綠才進步驟 2；失敗即停、不自行回滾）；回滾與資料庫還原只由使用者本人決定。

## 9 待決（不阻擋規格；請 1c／c7 確認）
1. 主檔五表預設全域共用（`owner_unit_id=1`）＝本規格決定，是否同意？
2. `payment_requests` 加 `legal_entity_id` 快照（本規格決定：加）是否同意？
3. `user_units` 是否為停用帳號也建列（建議：全部建，便於日後啟用）。
4. `CORE_VERSION` 預期 1.134（`(next:minor)`）由列車定。
5. 模組自有表清單（§2.5）由 5e 確認是否有遺漏，並決定 U0b 的順序。

## 10 r2 增補（0d U-1～U-7 對照）
U-1 備份涵蓋＝§2.3；U-2 不在 U0a 建索引＝§3 第 3 點；U-3 本地 PRAGMA helper／缺表跳過回傳 None＝§3 第 2 點；U-4 `user_units` 全部使用者、根單位後備名、`vouchers` VIEW 多欄＝§2.3／§3／§6；U-5 D3b 全新安裝一致性、D6b 回滾後基準、#15＝0＝§7；U-6 見 ORG-UNITS §14.12（U2 需重建含內嵌 UNIQUE 的表）；U-7 36 張表。0d 已驗證：36 張表皆在 `db.py`（`custom_records` 在 core v2）、VIEW `*` 於查詢時展開、`slip_no`／`voucher_no` 為內嵌 UNIQUE、舊 loader 對 `core=10` 容忍（`run_all` 跳過版本 ≤ 起點）、回滾腳本參數存在。
