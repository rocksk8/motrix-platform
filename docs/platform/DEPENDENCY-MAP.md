# MOTRIX 相依盤點與模組分組提案（初版）

> 產出：視窗 A｜2026-09-25｜分支 `platform`
> 來源：`tools/platform/dep_scan.py` → `docs/platform/dep_graph.json`（本文所有數字皆可重跑重現）
> 性質：唯讀盤點＋提案；未改任何產品碼。分組是**提案**，不是既定結構。

## 0. 結論

1. **L2 模組 12 個＋L1 共用核心**。各組擁有的表可切乾淨：104 張表中，被兩個以上組的 router 直接寫入的只有 **4 張**（`audit_log`、`dev_cases`、`stock_items`、`vouchers_all`），另有 2 張 L1 表被 M12 直寫（§4）。
2. 真正卡住拆分的是 **跨組 import 20 條**（依 import 敘述計，§3 #1–22 扣除組內與合法的 L2→L1），不是資料表。其中 **4 條是逆向（L1／helper → L2 router）**，一定要先切：
   - `pdf_gen.py:3544,3566` → `routers/completion_notes`
   - `routers/item_reads.py:30-32` → `dev_crm`／`quotations`／`system`
   - `helpers/recognition.py:219` → `routers/vendor_contractors`
   - `helpers/bonus_vouchers.py:16-17` → `routers/accounting_export`、`routers/vouchers`
3. 有兩支 helper 以「共用」之名實際寫入多個領域的表，應拆成事件訂閱：`helpers/google_calendar.py`（寫 5 個領域的表）、`helpers/case_stage_tasks.py`（案件寫每日任務）。
4. `helpers/quotations.py` 同時放了 **L1 能力**（`begin_write`／`write_txn` 交易鎖，`:567`、`:612`）跟**案件領域邏輯**（稅額、請款項、案件權限），被 16 支 router 引用。它要先拆成兩半，否則所有模組都會經由它依賴「案件」。
5. 前端：`case-management.html` 呼叫 8 組、`approval-queue.html` 呼叫 6 組，是兩個整合頁；它們應改成依賴 L1 的「案件關聯資料」與「簽核匣」註冊介面，而不是直接呼叫各模組。

## 1. 掃描方法與可信度

| 項目 | 作法 | 已知缺口 |
|---|---|---|
| import | `ast.parse`，含函式內延遲 import；`from helpers import _audit` 經 `helpers/__init__.py` 再匯出解析到子模組 | 依模組層級：import 了就算相依，不看實際呼叫的函式 ⇒ `*_transitive` 是**上界** |
| 資料表 | 字串常數（含 f-string、`+` 串接）掃大寫 SQL；表名白名單＝所有 `CREATE TABLE/VIEW` 字串常數（排除 docstring／註解） | `dynamic_sql=true` 的 14 個單位有 `FROM {tbl}`／`SET %s`，表可能漏列；以字串參數傳表名的另列 `tables_named`（方向不明） |
| 前端 | 頁面與 `js/` 的 `/api/...` 字串，代入 `const API='/api'` 類基底常數後，逐段比對 router 路由 | `approval-queue.html` 1 條註解字串未配對；`receivables.html`／`sales-orders.html`／`contractor-voucher-approval-settings.html` 無 fetch（佔位頁） |
| 正對照 | 9 條（含 1 條反向控制）；失敗 ⇒ exit 2 且不寫檔 | 3 種突變（拔再匯出解析／拔基底常數代入／CREATE 規則改寬）皆轉紅 |

正對照的第一次執行就抓到一個真缺陷：30 個頁面用 `` `${API}/quotations` `` 寫法，未代入常數前 `quotations.html` 對不到任何 router。

## 2. 分組提案

縮寫：R＝router、H＝helper、C＝backend 頂層模組、P＝前端頁面。

| # | 模組 | 成員 | 對外端點前綴 | 擁有的表 |
|---|---|---|---|---|
| L1 | 共用核心 | R: auth, system, modules, module_versions, licensing, list_prefs, item_reads, uploads, search, org_structure, approval_delegates；H: auth, audit, settings, email_notify, notification_prefs, tiered_approval, errors, dates, build_info, module_registry, licensing, startup, uploads, company_identity, edit_log, financial_mask, case_roles, geo；C: db, main, archive, backup_job, heartbeat_job, cloud_storage, photos, trail, pdf_gen（引擎部分） | /api/auth, /api/users, /api/system, /api/settings, /api/audit-log, /api/notifications, /api/modules, /api/module-versions, /api/license, /api/list-prefs, /api/reads, /api/uploads, /api/photo-token, /api/search, /api/org, /api/approval-delegates, /api/work-logs, /api/edit-presence, /api/online-users, /api/user-activity, /api/build-info, /api/ping | users, sessions, login_rate_limit, webauthn_credentials, audit_log, notifications, system_settings, departments, divisions, approval_delegates, item_reads, user_list_prefs, edit_presence, work_logs, module_versions, user_request_log, user_activity_daily, schema_version, geocode_cache, geocode_usage |
| M01 | 案件 | R: quotations, case_action_items, case_extra_expenses, material_orders, completion_notes；H: quotations（領域半）, case_stage_tasks, quote_terms, recognition；P: quotations, quotation-form, case-management(+js/case-management-*), case-stage-board, approval-history, completion-note-form, settlement | /api/quotations, /api/next-quote-no, /api/case-batch, /api/case-changes, /api/approval-queue*, /api/approval-history*, /api/completion-notes | quotations, quote_seq, case_stages, case_stage_visits, case_updates, case_change_requests, case_action_items, case_extra_expenses, completion_notes |
| M02 | 客戶與業務開發 | R: customers, dev_crm；P: customers, customer-log, dev-crm | /api/customers, /api/dev-cases, /api/dev-logs, /api/dev-crm | customers, dev_cases, dev_logs |
| M03 | 採購・庫存・出貨 | R: suppliers, parts, inventory, shipping_notes；H: procurement；P: suppliers, supplier-log, parts, inventory, shipping-export-history | /api/suppliers, /api/parts, /api/inventory, /api/shipping-notes | suppliers, parts, stock_items, stock_batches, purchase_suggestion_status, shipping_notes |
| M04 | 外包工班 | R: contractors, vendor_contractors, contractor_vouchers；P: contractors, vendor-contractors | /api/contractors, /api/vendor-contractors, /api/contractor-dispatches, /api/contractor-vouchers | contractors, vendor_contractors, contractor_dispatches, contractor_payment_vouchers |
| M05 | 應收應付 | R: invoice_vouchers, payment_requests, cashier；P: payment-request-form, cashier, receivables(佔位) | /api/invoice-vouchers, /api/payment-requests, /api/cashier | invoice_vouchers, payment_requests |
| M06 | 會計 | R: vouchers, account_items, accounting_export；H: voucher, voucher_pdf, voucher_attachments, voucher_template；P: voucher, account-items | /api/vouchers, /api/account-items, /api/reports(T100 匯出部分) | vouchers_all(+VIEW vouchers), voucher_lines, voucher_attachments, voucher_edit_log, voucher_templates, voucher_template_versions, account_items, t100_export_confirmations |
| M07 | 薪資獎金 | R: payslips, bonus；H: bonus, bonus_case, bonus_pdf, bonus_vouchers；P: payslips, payslip-form, bonus | /api/payslips, /api/next-slip-no, /api/tax-rules, /api/bonus | payslips, payslip_seq, bonus_*（12 張） |
| M08 | 分析 | R: reports, dashboard, map_points；P: index, reports, map, devices, warranty, procurement | /api/reports, /api/dashboard, /api/map, /api/devices, /api/sales-orders, /api/materials-summary, /api/company, /api/now | —（全部唯讀；router 直接寫入 0 張） |
| M09 | 選型知識庫 | R: switch/monitor/access/gateway/netarch/env/automation_guide；C: *_guide_seed.py；P: 7 個 *-guide, selection-db-overview | /api/{switch,monitor,access,gateway,netarch,env,automation}-guide | 26 張 *_categories/_fit/_products/_scenarios、env_guide_*、netarch_* |
| M10 | 網路規劃 | R: network_plans, network_plans_quick；C: network_plan_export, network_plan_topology；P: network-plans, network-plan-form, topology-quick | /api/network-plans, /api/network-plans-quick, /api/quotations/{}/network-plan* | network_plans |
| M11 | 標案雷達 | R: tender_radar；H: tender_source, tender_match；P: tender-radar | /api/tender-radar | tenders, tender_hits, tender_watches, tender_fetch_log |
| M12 | 每日任務 | R: daily_tasks；P: daily-tasks | /api/daily-tasks | daily_tasks, daily_task_completions, daily_task_edit_log |

**獨立性**：M09 零跨組 import，唯一牽連是種子資料由 `db.py` 寫入（26 張表），需隨模組搬走；M11 只被 L1 反向引用（§3 #26，模組開關與排程），這條切掉後可直接切出；M10 依賴 M01（`helpers/quotations`、`/api/quotations/{}/network-plan*` 路由掛在案件前綴下）與 M03（`network-plan-form.html` 查料件）。

**分組依據**：表的寫入者（§4）優先，其次 router 間 import。M08 三支 router 全唯讀、橫跨所有組，合為一組並改走讀取連接器。

**未歸屬（疑似廢棄）**：`projects`、`project_stages`、`project_logs` 只剩 `db.py` 建表與 `photos.py`／`archive.py` 字串引用；`bonus_templates`、`bonus_template_versions`、`voucher_templates`、`voucher_template_versions` 只有 `db.py` 引用，沒有 router 寫入。拆分前需確認是否要帶走。

## 3. 跨組相依（router／helper 層 import）

標記：**下沉**＝移到 L1；**連接器**＝擁有方提供公開介面（函式契約或內部 API），呼叫方只依賴介面；**切斷**＝呼叫方自己實作或移回擁有方，拆掉這條邊。

| # | 來源 → 目標 | 位置 | 引用內容 | 處置 |
|---|---|---|---|---|
| 1 | L1 `pdf_gen` → M01 completion_notes | `pdf_gen.py:3544`, `:3566` | `_warranty_range`, `merged_labels` | **切斷**（逆向）：完工單 PDF 樣板搬回 M01，L1 只保留 PDF 引擎 |
| 2 | L1 item_reads → M02 dev_crm | `routers/item_reads.py:30` | `_can_access_case` | **下沉**：案件可見性規則 → L1 權限 |
| 3 | L1 item_reads → M01 quotations | `routers/item_reads.py:31` | `_visible_case_filter_sql` | **下沉**（同上，與 #2 合併成一個資料列權限介面） |
| 4 | L1 item_reads → L1 system | `routers/item_reads.py:32` | `_MODULE_ACTION_PREFIXES` 等常數 | L1 內部；移到 `helpers/module_registry` |
| 5 | L1 search → M02 dev_crm | `routers/search.py:10` | `_can_access_case` | **下沉**（同 #2） |
| 6 | M08 dashboard → M02 dev_crm | `routers/dashboard.py:15` | `_can_access_case` | **下沉**（同 #2） |
| 7 | H recognition(M01) → M04 vendor_contractors | `helpers/recognition.py:219` | `_dispatch_row` | **連接器**（逆向：helper 依賴 router）：M04 公開「派工單列序列化」 |
| 8 | M08 reports → M04 vendor_contractors | `routers/reports.py:29` | `_dispatch_row` | **連接器**（同 #7） |
| 9 | M06 vouchers → M04 vendor_contractors | `routers/vouchers.py:37` | `_dispatch_row` | **連接器**（同 #7） |
| 10 | M06 accounting_export → M08 reports | `routers/accounting_export.py:76` | `_xl_style`, `_set_row`, `_check_export_rate` | **下沉**：Excel 樣式＋匯出速率 → L1 輸出 |
| 11 | 同上 | 同上 | `_collect_tax_invoices` | **連接器**：銷項發票資料屬 M05，reports 只是目前的放置處 |
| 12 | 同上 | 同上 | `_COMPANY` | **下沉**：寫死公司名 → L1 `company_identity`（`network_plan_export.py:19` 另有一份） |
| 13 | M05 cashier → M08 reports | `routers/cashier.py:30` | `_check_export_rate`, `_xl_style`, `_set_row` | **下沉**（同 #10） |
| 14 | 同上 | 同上 | `_collect_income_items` | **連接器**：收入資料屬 M05，應由 M05 提供、M08 讀 |
| 15 | M06 accounting_export → M04 contractor_vouchers | `routers/accounting_export.py:77` | `_voucher_public` | **連接器** |
| 16 | M05 cashier → M04 contractor_vouchers | `routers/cashier.py:29` | `_voucher_public` | **連接器** |
| 17 | M06 accounting_export → M03 parts | `routers/accounting_export.py:78` | `PART_CATEGORIES` | **下沉**：代碼表 → L1 字典（或資料表） |
| 18 | M07 bonus → M06 accounting_export | `routers/bonus.py:1885` | `_t100_config` | **連接器**：M06 公開「會計設定」 |
| 19 | H bonus_vouchers(M07) → M06 | `helpers/bonus_vouchers.py:16-17` | `validate_account_code`, `insert_draft_voucher`, `_line_sources`, `_amount_lines` | **連接器**（逆向：helper 依賴 router）：M06 公開「建立傳票草稿」 |
| 20 | M01 quotations → M06 vouchers | `routers/quotations.py:2257` | `vouchers_by_case` | **連接器**：L1 定義「案件關聯資料提供者」註冊介面，各模組註冊；M01 聚合時不 import |
| 21 | M01 quotations → M04 vendor_contractors | `routers/quotations.py:2258` | `list_dispatches` | **連接器**（同 #20） |
| 22 | M01 quotations → M03 shipping_notes | `routers/quotations.py:2259` | `list_shipping_notes` | **連接器**（同 #20） |
| 23 | M01 quotations → L1 item_reads | `routers/quotations.py:941`, `:983` | `unread_keys` | 合法（L2 → L1）；改從 L1 helper 匯入，不經 router |
| 24 | M08 map_points → L1 system | `routers/map_points.py:775` | `_migrated_locations` | 合法（L2 → L1）；私有函式應公開到 `company_identity` |
| 25 | M08 dashboard → M08 reports | `routers/dashboard.py:515` | `_collect_expenses` | 組內 |

| 26 | L1 system → M11 helper tender_source | `routers/system.py:676`；`main.py:26`（`:572` 排程、`:603` `radar_on()`） | 模組開關、啟動排程 | **下沉**：L1 模組註冊介面提供 `on()`／`schedule()`，main 迭代註冊表，不指名模組 |
| 27 | L1 system → M07 helper bonus | `routers/system.py:722` | `bonus_module_on()` | **下沉**（同 #26） |
| 28 | L1 system → M01 helper quotations／quote_terms／case_roles | `routers/system.py:20`, `:1286`, `:2445` | `_steps_to_tiers`、`DEFAULT_TERMS`、角色常數 | `_steps_to_tiers` **下沉**到簽核；`DEFAULT_TERMS`、案件角色設定端點 **切斷**：移到 M01 自己的設定端點 |

組內（不需處理）：`quotations→completion_notes/case_extra_expenses`（`:2260-2261`）、`vendor_contractors→contractors`（`:15`）、`vouchers→accounting_export`（`:32`）、`system→auth`（`:1377`）。

### 3.1 helper 層的跨領域寫入

| helper | 位置 | 寫入 | 處置 |
|---|---|---|---|
| `helpers/google_calendar.py` | `:250` invoice_vouchers、`:279` payment_requests、`:313` shipping_notes、`:349` quotations、`:427`/`:446` case_stages | 回寫各單據的行事曆 event id | **連接器**：L1 行事曆只回傳 event id，由各擁有模組自己回寫；或改成事件訂閱 |
| `helpers/case_stage_tasks.py` | `:39` `sync_daily_task_for_case_stage`（由 `routers/quotations.py:3374` 呼叫） | daily_tasks, daily_task_completions | **連接器**：M12 公開「由外部來源建立／同步任務」；M01 發事件 |
| `helpers/quotations.py` | 被 16 支 router 引用 | quotations | **拆**：`begin_write`(`:567`)／`write_txn`(`:612`)／`_safe_close`(`:44`) 下沉 L1；其餘（稅額、請款、`guard_case_access` `:77`）留 M01 並公開成連接器 |

## 4. 跨組共用的表

| 表 | 寫入者（router 直接） | 位置 | 處置 |
|---|---|---|---|
| `audit_log` | L1 auth、M02 dev_crm | `routers/auth.py:440`、`routers/dev_crm.py:1125` | **下沉**：一律走 `helpers/audit._audit`（`:92`），禁止直寫 |
| `dev_cases` | M02 dev_crm、M01 quotations | `routers/quotations.py:2433`（轉案回滾） | **連接器**：M02 公開「轉案／取消轉案」 |
| `stock_items` | M03 inventory、shipping_notes；M01 quotations | `routers/quotations.py:2486`, `:2497`；`routers/shipping_notes.py:453`, `:521` | **連接器**：M03 公開「保留／釋放／扣庫存」，M01 不直寫 |
| `vouchers_all` | M06 vouchers；M01 quotations；M07（經 `helpers/bonus_vouchers`） | `routers/quotations.py:6593` | **連接器**：M06 公開「更新傳票簽核狀態」（與 #19 同一個介面組） |
| `system_settings` | L1 settings；M12 daily_tasks | `routers/daily_tasks.py:1153`, `:1354` | **下沉**：改用 `helpers/settings` 的刪除介面 |
| `user_request_log` | L1 main；M12 daily_tasks | `routers/daily_tasks.py:1981`（過期清理） | **切斷**：清理移回 L1 排程 |

經 helper 遞移寫入（上界）另見 `dep_graph.json` 各 router 的 `tables_w_transitive`；`audit_log`／`notifications`／`system_settings` 被 36～40 支 router 經 L1 helper 寫入，屬預期中的 L1 表。

## 5. 應下沉到 L1 的能力清單

| 能力 | 目前位置 | 備註 |
|---|---|---|
| DB 連線／交易 | `db.py:182` `get_db`；`db.py:422` `init_db`；`helpers/quotations.py:567` `begin_write`、`:612` `write_txn`、`:44` `_safe_close` | 交易鎖目前住在案件 helper |
| 背景執行緒 | `db.py:157` `spawn_bg_thread` | |
| Schema／migration | `db.py`（5,746 行，建全部 104 張表＋選型種子資料） | 需拆成「L1 核心表」＋「各模組自帶 migration」；種子寫入目前落在 core:db |
| 認證／身分 | `helpers/auth.py:202` `_require_user`、`:234` `_tok`、`:72-93` 密碼雜湊、`routers/auth.py` | |
| 模組授權 | `helpers/auth.py:135` `user_has_module`、`:146` `require_any_module`；`helpers/module_registry.py`；`helpers/licensing.py` | 模組開關本身就是平台化基礎 |
| 資料列權限（案件可見性） | `routers/dev_crm.py:100` `_can_access_case`、`routers/quotations.py:251` `_visible_case_filter_sql`、`helpers/quotations.py:77` `guard_case_access` | 三處各自實作；被 L1 search/item_reads 反向依賴 |
| 財務遮罩 | `helpers/auth.py:181` `can_see_financial`、`helpers/financial_mask.py`、`routers/quotations.py:6174` `_mask_money` | 後者散在 router |
| 稽核／通知 | `helpers/audit.py:92` `_audit`、`:11` `_notify` | |
| Email | `helpers/email_notify.py:172` `_send`、`:293` `_async_send`、`:63` `_build_html` | |
| 通知偏好 | `helpers/notification_prefs.py` | |
| 設定 | `helpers/settings.py:11` `_get_setting`、`:28` `_set_setting` | |
| 簽核 | `helpers/tiered_approval.py`（`:54` 單據類型清單、`:88` `resolve_active_flow_setting`、`:235` `resolve_tier_approvers`、`:354` `check_approve_permission`）；`routers/approval_delegates.py` | `APPROVAL_DOC_TYPES` 寫死各模組單據 ⇒ 要改成模組註冊 |
| 簽核匣／歷史 | `routers/quotations.py`（`/api/approval-queue`, `/api/approval-history`） | 放在 M01；前端 `approval-queue.html` 跨 6 組 |
| 編輯紀錄 | `helpers/edit_log.py`（表名以參數傳入） | |
| 輸出：PDF | `pdf_gen.py`（引擎＋各單據樣板混在一起，`:29-107`）；`helpers/voucher_pdf.py`, `helpers/bonus_pdf.py` | 引擎下沉，樣板回各模組 |
| 輸出：Excel | `routers/reports.py:683` `_xl_style`、`:714` `_set_row`、`:71` `_check_export_rate` | 目前住在分析 router |
| 公司識別 | `helpers/company_identity.py:171` `snapshot_for`；寫死的 `_COMPANY`：`routers/reports.py:41`、`network_plan_export.py:19` | |
| 上傳／附件 | `helpers/uploads.py:34`、`helpers/voucher_attachments.py`、`photos.py`、`routers/uploads.py` | |
| 行事曆 | `helpers/google_calendar.py` | 先去掉跨領域寫入（§3.1） |
| 地理編碼 | `helpers/geo.py`（geocode_cache/usage） | |
| 組織 | `routers/org_structure.py`；`helpers/tiered_approval.py:113-213` 部門／事業處主管解析 | |
| 已讀／清單偏好／搜尋／編輯中 | `routers/item_reads.py:247`、`routers/list_prefs.py`、`routers/search.py`、`/api/edit-presence`(system) | |
| 錯誤追蹤 | `helpers/errors.py:21` `trace_id` | |
| 備份／封存 | `archive.py`（`:1356` `_backup_quotation` 是案件專屬）、`backup_job.py`、`cloud_storage.py`、`trail.py` | |
| 前端殼 | `frontend/static/auth-guard.js`, `sidebar.js`, `notif.js`（57 頁共用）、`ui.js`, `list-sort.js`, `record-link.js`, `edit-presence.js`, `approval-cascade.js` | |

## 6. 建議順序

1. 先切逆向相依：§0-2 的 4 條＋§3 #26–28（L1 指名 L2 helper），否則 L1 無法單獨成立。
2. 拆 `helpers/quotations.py`（交易鎖下沉）與權限三處合一（§5「資料列權限」）——這兩件解掉 §3 的 #2–6 與 16 支 router 對 M01 的間接依賴。
3. 定義兩個 L1 註冊介面：「案件關聯資料提供者」（解 #20–22）、「簽核單據類型」（解 `APPROVAL_DOC_TYPES` 寫死）。
4. 其餘連接器（#7–9、#11、#14–19、§4）依模組拆分順序逐一處理。M09 可直接先切出做為第一條端到端細線；M11 在 #26 解掉後跟進。

## 附：重跑

```
python tools/platform/dep_scan.py           # 重建 dep_graph.json
python tools/platform/dep_scan.py --check   # 只跑正對照
```
