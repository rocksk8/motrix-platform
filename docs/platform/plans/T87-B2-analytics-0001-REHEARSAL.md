# T87 B2：analytics 模組遷移 0001（custom_reports）正式機預演說明

格式照 T86 crm 0005 預演（`20261114-t86-apply.md`「預演紀錄」）。**只在備份副本上做；正式 DB 不寫入。**

## 這支遷移做什麼
- 檔案：`backend/modules/analytics/migrations/0001_custom_reports.py`（單獨一檔、不自己 commit）。
- 新增 2 張表＋2 個索引：`custom_reports`（9 欄，`UNIQUE(username,name)`、`idx_custom_reports_username`）、`custom_report_shares`（5 欄，`UNIQUE(report_id,shared_with)`、`idx_custom_report_shares_user`）。皆帶 `owner_unit_id INTEGER NOT NULL DEFAULT 1`。
- 冪等：`CREATE … IF NOT EXISTS`；只新增，不碰任何既有表；沒有前置表要求；回傳 `None`（完成）。
- 版號：`module_schema_versions` **目前沒有 `analytics` 列（＝0）→ 套用後 `('analytics', 1, <時間>)`**；核心 `schema_version` 與 `core` 版號不變。
- 旗標 `custom_reports.enabled` 出廠 0：套用後功能仍是關的（所有端點 404），不影響使用者。

## 檔案
- 預演腳本：`docs/platform/plans/T87-B2-analytics-0001-REHEARSAL.py`（`check` 以 `mode=ro` 唯讀；`apply`＝SAVEPOINT→`up()`→RELEASE→寫版號，與 `core/migrations.py run_all` 同序；`rollback`＝回滾演練）。
- 用法（於備份副本旁；`<副本>` 是用 SQLite backup API 從正式 DB 以 `mode=ro` 複製出的暫存檔，演練後連 `-wal`／`-shm` 一併刪除）：
  `python -B T87-B2-analytics-0001-REHEARSAL.py <副本>.db <包內>\backend\modules\analytics\migrations\0001_custom_reports.py check|apply|rollback`

## 步驟與預期
1. **預演前 `check`**（唯讀）。預期：`integrity_check=ok`；`module_schema_versions` **沒有 analytics 列**（其他模組列記下來，供前後比對）；兩新表**不存在**、新索引無；記下「既有表數」與 `sqlite_master` 物件數。
2. **`apply`**。預期：印「apply 完成」（本機 dev 庫實測 5 ms；正式機以實際為準）。
3. **預演後 `check`**。預期：`integrity_check=ok`；`analytics` 列＝`('analytics', 1, …)`；`custom_reports` 9 欄、`custom_report_shares` 5 欄，**皆 0 列**；2 個新索引存在；`sqlite_master` 物件數 **+4**（2 表＋2 索引）；既有表數、其他模組版號、核心 `schema_version` **前後相同**；DB 檔案大小幾乎不變。
4. **冪等**：再跑一次 `apply` → 再 `check`。預期：除 `analytics` 的 `applied_at` 時間更新外，其餘輸出與步驟 3 完全相同（兩表仍 0 列、物件數不變、integrity ok）。
5. **回滾演練**：`rollback`（DROP 兩表、`analytics` 版號改 0）→ `check`。預期：`integrity_check=ok`；兩表與兩索引消失；`sqlite_master` 物件數回到步驟 1 的數字；其他列不變。
6. 附註實際數字寫進預演紀錄（前後 `module_schema_versions` 全表、物件數、耗時、DB 大小）。

## 正式套用時的回滾（僅在使用者或 PM 指示後）
- 最輕：把設定 `custom_reports.enabled` 保持關閉（預設即關），資料保留；舊程式碼不讀這兩張表，**只回程式碼不需動資料**。
- 要拆表：停服務 → 還原 `pre_<班次>_manual_<時間戳>.db` 備份（需使用者同意），或照步驟 5 的 DROP＋版號改 0（⚠ 會丟掉使用者存的報表設定，先備份）→ 啟動後核對 `commit`、`/api/ping`、`module_schema_versions.analytics`、`integrity_check`。
- 若遷移途中失敗：啟動器把 analytics 標為未完成、模組下線、版號不前進，其他模組照常；下次啟動再試。

## 本機驗證（作者已做，非正式機預演）
在 dev 庫備份副本上依序跑 check→apply→check→apply→check→rollback→check：全程 `integrity_check=ok`；`analytics` 0→1；新增 2 表 2 索引（物件數 446→452，179 張既有表不變）；第二次 apply 不變；rollback 後回到 446。
