# 稽核：主持的 h-probes（tender_radar／daily_tasks／netplan 宣告 provides.probes）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。合回前稽核（第七班）。
> 對象：`origin/wip/h-probes` `d56c5fc6`：三個 module.json 加 `provides.probes`（daily_tasks `/api/daily-tasks`；netplan `/api/network-plans`；tender_radar `/api/tender-radar/watches`、`/api/tender-radar/tenders`），各升修正版號（1.0.2、1.0.3、1.3.1）並寫 CHANGELOG。

## 0. 結論

**必修 0、建議 0、觀察 1。** 三點都成立。

## 1. ① probe 是純讀（實跑）

- **靜態**：四個 handler（`list_daily_tasks`、`list_network_plans`、`list_watches`、`list_tenders`）以及 daily_tasks 列表呼叫的 `_enrich`、`_occurrences_in_month`、`_occurrences_on_date`、`_range_occurrence_on_date`、`_range_occurrences_in_month`、`_user_filter_sql`，都沒有 INSERT、UPDATE、DELETE FROM、commit、write_txn。每週、區間任務的「當天那一次」是在記憶體裡算出來的，不寫進庫。
- **動態**（暫時探針，在 D 樹跑完即刪）：
  - 先造資料：一次、每週、區間三種每日任務，以及一筆網路規劃書，全部回 201。
  - 以超級管理員打每一支 probe，打之前、打之後，對**每一張表**比對列數與全部內容的雜湊。
  - 另外打 `/api/daily-tasks?date=今天`、`?month=本月`。

| 打的端點 | 狀態碼 | 有變動的表 |
|---|---|---|
| 對照組 `/api/system/version` | 200 | 無 |
| `/api/daily-tasks` | 200 | 只有 `user_request_log` |
| `/api/daily-tasks?date=…`、`?month=…` | 200 | 無 |
| `/api/network-plans` | 200 | 只有 `user_request_log` |
| `/api/tender-radar/watches`、`/tenders` | 200 | 只有 `user_request_log` |

- `user_request_log` 是 `main.py:_record_request_trail` 中介層的**操作軌跡**：任何登入後的請求都會記，同一路徑在去重秒數內只記一次，`trail.should_skip` 的路徑（例如 `/api/system/version`）不記。所以這不是 probe 的副作用：同一條路徑第二次打（帶 date、month）就沒再記。**`/api/daily-tasks` 讀的時候沒有產生當天的任務**（`daily_tasks` 表的列數與雜湊都沒變）。

## 2. ② 在自己的前綴底下

- daily_tasks：`/api/daily-tasks` 在它的 `api_prefixes`；netplan：`/api/network-plans` 在它的 `api_prefixes`（另一個前綴是 `/api/network-plans-quick`）；tender_radar：兩支都在 `/api/tender-radar` 底下。
- 既有守門 `test_product_drill_probes.py` 驗得到：D 突變 PB1（netplan 的 probe 改成 `/api/quotations`，出了前綴）與 PB2（daily_tasks 的 probe 改成不存在的路由）都紅。

## 3. ③ 版號與 CHANGELOG

- `test_module_changelog_follows_code`、`test_module_package_files`、`test_changelog_sections`、`test_product_drill_probes`，共 45 passed。
- D 突變 PB3（tender_radar 的版號退回 1.3.0）⇒ `test_module_package_files::test_every_module_has_its_package_files`（G2：module.json 的 version＝CHANGELOG 最上面的版號）**紅**。
  - 更正：D 第一次跑 PB3 時，選題只放了 changelog_follows_code 與 product_drill_probes，突變存活；原因是那兩題不管版號是否一致（G2 在另一檔）。這是 D 選題的錯，不是守門漏掉。

## 4. 觀察

- **O-1　C 的 `test_probe_side_effects` 要排除操作軌跡**：probe 會在 `user_request_log` 留一列，這是中介層的正常行為。比對「打之前、打之後」時，要嘛排除這張表，要嘛像 D 這樣用一支 `should_skip` 的端點當對照組；否則每一支 probe 都會被判成有副作用。

## 5. 回覆欄

| # | 回覆 | commit | D 確認 |
|---|---|---|---|
| — | 無待回覆項目 | d56c5fc6 | ✅ 12:48 **通過（d56c5fc6）** |
