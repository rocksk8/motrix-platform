# 平台化前置規劃：共用接點、版型、功能地圖、模組檢查清單、自訂前置（2026-09-24）

> **量測基準**：§1-§4 以 HEAD `1eaa5d3e673cc9df8feea56e6992f8c33953a0d7` 為準；**§5 以 `73099719184e53c8fa951ff3cc9e41e15329e49a` 為準**（第三版，2026-09-24 依使用者定調「平台化是獨立的功能」改寫）。
> 第一版的基準是 `f7145be`（commit `755c281`）。第二版把 §1-§4 引用到、而在兩版之間有變動的檔案，逐一用 difflib 做行號對照後改寫；有變動的內容（字級修正）另外重讀。§5 在新基準上重新讀碼。
> 讀取方式：用 `git ls-tree` 加逐檔 `git show` 匯出唯讀快照（不用 `git archive`，因為 `export-ignore` 會漏掉 tests 與 docs/windows）。讀取當下工作樹有 dirty 檔（`db.py`、`routers/vouchers.py`、`voucher.html` 等），不影響以 HEAD 為準的行號。行號會隨時間過期（見 `MULTIWIN-PROTOCOL.md §5w`）。
> 延伸自 `docs/PLATFORM-CUSTOMIZATION-INVENTORY.md`（基準 `5c44d58`，以下簡稱「盤點」），不重做盤點的內容。盤點引用的行號在本版已經位移，例如 `vouchers_all.custom_fields` 由盤點寫的 :5205 移到 `db.py:5265`。
> 硬約束：**以額外引用疊加，不直接修改既有模組**（盤點第 1-3 行）。
> 撰寫：session `cbd8dcd8`，受 hichan-0a 派工，全程唯讀。

---

## 1. 共用接點登錄表

**用途**：新功能要做的事如果下表已經有，就一律走表上的接點，不另寫一份。
**欄位說明**：「守門」是會讓全量回歸變紅的測試；「—」表示沒有任何測試在守。

### 1.1 權限與模組 key

| 項目 | 內容 |
|---|---|
| 在哪 | `require_any_module(user, keys, label)` 定義在 `backend/helpers/auth.py:154`：只有 superadmin 直通（:176），admin 也必須持有對應 key，否則回 403「權限不足：需要「label」模組」（:180）。<br>輔助函式：`user_has_module` :141、`_require_user(..., module=None)` :205。<br>**沒有 `require_module` 這個函式。** |
| 怎麼用 | 單 key：`routers/tender_radar.py:42` `require_any_module(user, ("tender_radar",), "標案雷達")`。<br>多 key：`routers/contractor_vouchers.py:62`，值取「該 API 所有消費頁面所屬模組的聯集」（`auth.py:170-174`）。<br>backend 非測試碼共 105 行呼叫（grep `require_any_module(`，已扣掉定義）。 |
| key 散在哪 | ① `helpers/auth.py:22` `_SUPERADMIN_MODULES`<br>② `frontend/pages/users.html:718` `ROLE_MODULES`、:792 `allModules`（權限目錄）<br>③ `frontend/static/sidebar.js:470-510` `computeFlags`、:556 `_FILE_MODULE`（只給徽章已讀用，:1078）、:1044 起 `_MOD_BADGES`<br>④ `routers/system.py:349-370` `_MODULE_ACTION_PREFIXES`（稽核徽章用）<br>⑤ `trail.py:62` `MODULE_LABELS`<br>⑥ `static/notif.js:128` `modBadge`<br>⑦ 各 router 自己的常數，例如 `routers/vouchers.py:69` `_VOUCHER_MODULES`<br>⑧ `db.py` v84 的一次性回填樣板（約 :3760-3775）<br>**`helpers/licensing.py` 沒有自己的 key 清單**：它只把授權檔的 `modules` 原樣往下傳（:117、:380）。 |
| 守門 | `tests/test_module_keys_consistency_2026_09_13.py`：<br>後端用到的 key 必須在目錄內（:119）；側欄 key 必須在目錄內（:130）；目錄內不可有死 key（:138）；角色樣板（:149）；superadmin 樣板前後端一致（:157）；頁面呼叫的 API 必須接受該頁的模組（:222）；側欄承諾必須和後端一致（:264）。<br>頁面層：`tests/test_e2e_page_module_guard_2026_09_13.py`（清單寫死在 :65 `_FORBIDDEN_WITHOUT_MODULES`）。 |
| 不走的後果 | 模組勾選只剩「側欄顯示開關」的作用，手打網址或直接打 API 都擋不住。2026-09-13 之前 35 個模組中有 16 個後端沒有檢查（`auth.py:166-168`）。<br>最危險的是**擋錯人**：頁面呼叫一支不接受該頁模組的 API，使用者看到一片 403（`auth.py:176-180`）。 |

### 1.2 簽核引擎

| 項目 | 內容 |
|---|---|
| 在哪 | `backend/helpers/tiered_approval.py` 是純邏輯，不碰 FastAPI、沒有副作用（:1-19）。<br>單據類型寫死三處：`APPROVAL_DOC_TYPES` :54-56、`DEFAULT_UNIFIED_DOC_TYPES` :62、`APPROVAL_DOC_TYPE_LABELS` :64。<br>選流程：`approval_flow_setting_key` :79，回傳 `unified_approval_flow` 或 `{doc_type}_approval_flow`；`resolve_active_flow_setting` :88。<br>展開關卡：`setting_to_active_tiers` :296。<br>權限檢查：`check_approve_permission` :354、`check_reject_permission` :436、`check_no_tier_self_approval` :456。<br>連簽：`plan_self_cascade` :385、`cascade_self_tiers` :421。<br>代理人：`active_delegators_for` :339，查 `approval_delegates` 表。 |
| 怎麼用 | 送審：`routers/case_extra_expenses.py:336` `resolve_active_flow_setting("extra_expense")`。<br>核准：`:417` `check_approve_permission(...)`。<br>其他呼叫點：`routers/completion_notes.py:397`、`:456`；`routers/bonus.py:1171-1175`。<br>設定頁：`frontend/pages/approval-settings.html:448` `docTypeOrder`、:475-484 `flowSettingKeys`；端點在 `routers/system.py:231-242`，不在 `APPROVAL_DOC_TYPES` 內的類型回 404（:236-237）。 |
| 例外 | `routers/quotations.py:178` 保留了報價單自己的一份副本。<br>簽核佇列 `get_approval_queue`（`quotations.py:3784`）每種單據各寫一段 SQL（約 :3841-4187）。 |
| 守門 | **沒有專屬測試檔**，都是間接覆蓋：<br>`test_approval_flow_scope.py`（:17、未知類型要拒 :248）<br>`test_approval_delegates_2026_08_28.py`（:66-170）<br>`test_org_chain_approval_2026_09_15.py`（:104-330）<br>`test_approval_settings_unify_2026_09_23.py`（:97-336）<br>`test_queue_and_feed_scoping_2026_09_15.py:158`（佇列過濾必須涵蓋每一種單據）<br>另有 `tools/check_approval_queue_coverage.py`，但**沒有任何測試或打包腳本呼叫它**。 |
| 不走的後果 | 代理人、主管鏈、自簽連簽、禁止自簽這些規則都要自己重寫一份，而報價單那份副本已經證明副本會漂移。 |
| ⚠ 發現 | `bonus` 在 `APPROVAL_DOC_TYPES` 內，送審時讀 `bonus_approval_flow`（`bonus.py:1171`）；但 `approval-settings.html:448` 的 `docTypeOrder` 沒有 bonus。**設定頁設不到獎金的簽核流程。**本文不處理，列為待確認。 |

### 1.3 公司身分與抬頭

| 項目 | 內容 |
|---|---|
| 在哪 | `backend/helpers/company_identity.py`：<br>`location_identity(location_id)` :82：逐欄落空，順序是這筆據點 → 主要據點 → company_profile → 預設（:100-106）。<br>`snapshot_for` :171：凍結抬頭五欄 `_SNAPSHOT_FIELDS`（:163）到 `data_json["locationIdentity"]`（:168），銀行欄位不凍結。<br>`apply_snapshot` :220。 |
| 怎麼用 | 兩步寫法：`apply_snapshot(location_identity(_location_of(x)), x)`（`pdf_gen.py:109`、:1041）。<br>送出時寫入快照：`routers/quotations.py:1255`、:1541、:1651。<br>`identity_for()` 目前沒有呼叫者（只出現在註解，:226、:240）。 |
| 守門 | `tests/test_quote_location_2026_09_22.py`（:249、:287、:371）<br>`tests/test_quote_location_snapshot_2026_09_23.py`（:166、:220）<br>`tests/_pdf_identity.py:37`（BUILDERS 列出 9 支 builder） |
| 不走的後果 | 抬頭寫死或自己查，多據點時會全部印成總公司，**而且測試照樣全綠**（`company_identity.py:117-120`）。送出後不凍結的話，改了據點資料，舊單據的抬頭也會跟著變。 |

### 1.4 PDF 渲染

| 項目 | 內容 |
|---|---|
| 在哪 | `helpers/startup.py:57-58` `EDGE_PDF_SEMAPHORE = BoundedSemaphore(3)`。<br>`run_edge_pdf(cmd)` :75：拿 semaphore、限時；逾時不 raise，由呼叫端的「0 byte 就 raise」回報錯誤（:78-81）。<br>抬頭與頁尾：`pdf_gen.py:522` `_identity_head`、:538 `_identity_foot`、:549 `_identity_foot_short`，**是私有函式，放在 pdf_gen，不在 helper**。<br>9 支 `_build_*_html`（`pdf_gen.py`）：:96 quote、:567 payslip、:1033 shipping、:1393 contractor_voucher、:1751 invoice_voucher、:2059 payment_request、:2559 case_closing、:3071 project_execution_report、:3264 completion。 |
| 怎麼用 | 共同流程：組 HTML → tempfile → 組 Edge 參數 → `run_edge_pdf` → 檢查 0 byte。這套流程複製了 18 處：pdf_gen 15 處、`helpers/voucher_pdf.py:396`（`bonus_pdf.py:36` 重用它）、`network_plan_export.py:406`、`routers/reports.py:2288`。**18 處都有經過 `run_edge_pdf`。**<br>浮水印有三套：`_build_quote_html(show_watermark, watermark_text, ...)`（`pdf_gen.py:96-99`）、`voucher_pdf.watermark_html`（:172）、`bonus_pdf.award_watermark_html`（:60）。<br>歸檔：`archive._pdf_archive_dirs()`（:1116-1131）寫死 6 類，完工單與薪資單不在其中。 |
| 守門 | `tests/test_pdf_concurrency_2026_09_07.py:70`：只擋「自己用 subprocess 啟動 Edge」。<br>`tests/test_pdf_archive_mirror_2026_09_07.py:22`：驗 6 類歸檔。 |
| 不走的後果 | 繞過 semaphore 會讓 Edge 並發失控。沒有 0 byte 檢查的話，逾時會變成「成功回一份空 PDF」。 |

### 1.5 通知

| 項目 | 內容 |
|---|---|
| 在哪 | 站內通知 `_notify(username, type_, ref_id, ref_label, message)`：`helpers/audit.py:11`，**全 backend 唯一一處 `INSERT INTO notifications`**。表建在 `db.py:530`。<br>`notify_org_chain_notice` :27；來源已刪除的通知會被隱藏（:49-72）。<br>Email：`helpers/email_notify.py`，`_admin_emails(event_key)` :114、`_send` :172、`_async_send` :293，`notify_*` 從 :348 起共 44 支以上。<br>靜音設定：`helpers/notification_prefs.py:17` `EVENT_GROUPS`、:93 `EVENT_KEYS`、:96 `is_enabled`，是 opt-out 制。<br>前端 `static/notif.js:29` `notifStore` 輪詢 `/api/notifications/mine`（:94）。 |
| 怎麼用 | `routers/case_extra_expenses.py:373` 呼叫 `_notify(...)`。 |
| 守門 | `tests/test_notification_prefs_coverage.py:33`：掃 `_admin_emails` 和 `_superadmin_emails` 的**字面值**引數，必須都在 `EVENT_KEYS` 內。只驗單向（:47）。<br>如果 event key 以變數傳入，這支測試掃不到（`email_notify.py:1756-1761`）。 |
| 不走的後果 | 自己寫 INSERT 會繞過來源刪除過濾，產生點了是 404 的通知；新的 email 事件沒有登記的話，使用者無法靜音。 |

### 1.6 稽核

| 項目 | 內容 |
|---|---|
| 在哪 | 使用者動作：`_audit(token, action, target_type, target_id, target_label, detail)`，`helpers/audit.py:92`，寫 `audit_log`（:112），**例外全部吞掉**（:123）。<br>系統動作：`_system_audit(action, target_label, detail)`，`archive.py:387`，以 `username="system"` 寫入（:392-400）。<br>改前改後紀錄：`helpers/edit_log.py:88` `append_edit_log(...)`；缺改前值時丟 `MissingOldValue` 且不寫入。<br>操作軌跡：`main.py:231-265` 中介層寫 `user_request_log`，規則在 `trail.py`。 |
| 怎麼用 | `routers/access_guide.py:47` 呼叫 `_audit`；`archive.py:1028` 呼叫 `_system_audit`；`routers/bonus.py:1299` 呼叫 `append_edit_log`。 |
| 守門 | 🔴 **沒有任何測試守「寫入端點要呼叫 `_audit`」**。<br>`test_system_audit_2026_09_14.py` 掃的是「有沒有呼叫守門函式」（:647，regex :602），不是有沒有寫稽核。<br>`test_write_lock_deadlock_guard_2026_09_15.py:154`：持有寫入鎖時不可跨連線寫入，`_audit` 就在跨連線寫入者清單內（:45）。 |
| 不走的後果 | 稽核頁與模組徽章看不到這個模組的動作；**而且不會有任何紅燈。** |

### 1.7 附件與上傳路徑

| 項目 | 內容 |
|---|---|
| 在哪 | `helpers/uploads.py:41` `save_document_files(subfolder, doc_no, files, uploaded_by, watermark_by='')`。<br>檢查項目：副檔名白名單 jpg/jpeg/png/pdf（:22、:70）、單檔 20MB（:23、:73）、空檔（:75）；檔名改成 uuid（:85）；展示帳號導到 `_demo_uploads`（:31-38）。<br>讀取端防路徑穿越：`routers/uploads.py:24-30` `_resolve_upload_path`（commonpath）。<br>傳票附件另一套：`helpers/voucher_attachments.py:175-186`。<br>根目錄算了三份：`helpers/uploads.py:20`、`routers/uploads.py:19`、`photos.py:10`。 |
| 怎麼用 | `routers/quotations.py:1175`、`completion_notes.py:741`、`invoice_vouchers.py:743`、`case_extra_expenses.py:569`。 |
| 守門 | `tests/test_core.py:340-356`（穿越）<br>`tests/test_signed_upload_files.py:118`（副檔名）<br>`tests/test_upload_demo_isolation.py:64` |
| 不走的後果 | 自寫的上傳會漏掉展示帳號隔離，展示帳號的檔案寫進正式目錄。 |
| ⚠ 缺口 | `save_document_files` 直接 `os.path.join(UPLOADS_ROOT, subfolder, doc_no)`（:63），**沒有檢查 `doc_no` 是否穿越目錄**。平台層呼叫前要自己先驗 `doc_no`。 |

### 1.8 單號產生

| 項目 | 內容 |
|---|---|
| 在哪 | 共用：`db.py:5486` `next_entity_code(conn, table, prefix, code_col="code")`，做法是 MAX+1，遇到已存在的號就用迴圈跳過。<br>各自一套的有四支：報價 `_peek_next_no`＋`quote_seq`（`routers/quotations.py:658`，撞號重試一次後回 409，:1281-1290）；薪資 `payslips.py:112`；傳票 `helpers/voucher.py:296`（不加鎖，靠 UNIQUE 擋，:312-317）；料號 `parts.py:26`。 |
| 怎麼用 | 共用函式有 10 個呼叫點，例如 `routers/shipping_notes.py:197`、`completion_notes.py:269`、`payment_requests.py:433`。 |
| 守門 | 各單號欄位都有 UNIQUE（例如 `db.py:426`、:1478）。<br>`tests/test_api_integration.py:827`（料號競態回 409）。<br>**`next_entity_code` 的併發撞號沒有專屬測試。** |
| 不走的後果 | 又多一套編號規則。新單據一律用 `next_entity_code`＋UNIQUE，並且接住 IntegrityError。**目前除了報價單，其他呼叫點都沒有撞號重試。** |

### 1.9 每日 JSON 備份登記

| 項目 | 內容 |
|---|---|
| 在哪 | `archive.py:1506` `_daily_backup_tables()`，格式是 `{中文檔名: SELECT}`。<br>`backed_up_table_names()` :1738 只抽 FROM 後那一張表，JOIN 的表抓不到。<br>`system_settings` 已經在備份內（:1583-1587），而且會挖掉祕密欄位。 |
| 守門 | `tests/test_system_audit_2026_09_14.py`：<br>`:127` 每張表要不是有備份，就是明確排除；排除清單 `_NOT_IN_JSON_BACKUP` 在 :72，值必須寫理由。<br>`:157` 每句 SELECT 都要跑得起來；`:265` 欄位覆蓋；`:466` 不可含憑證；`:533` 不可含 base64 影像。 |
| 不走的後果 | 新表不進每日備份，**要到還原那天才會發現**。v93、v95、v97 連續漏了三次（`db.py:48-53`）。 |

### 1.10 展示模式資料分類

| 項目 | 內容 |
|---|---|
| 在哪 | `db.py:342` `DEMO_CLEARED_TABLES`（整張清）；`db.py:334` `DEMO_FILTERED_CLEARS`（部分清）。兩份清單必須互斥而且窮盡（:313-319）。<br>VIEW 不能列進去，要列實表（:386-389）。<br>`reset_demo_db()` 在 :233。<br>`system_settings` 屬於整張清（:364）。 |
| 守門 | `tests/test_demo_reset_2026_09_23.py:223` `test_dm1_every_table_is_classified_as_user_or_system_data`；反向控制在 :274。 |
| 不走的後果 | 展示重置清不掉新表，**下一個客戶會看到上一個客戶的資料**（`db.py:52-53`）。 |

### 1.11 version_manifest

| 項目 | 內容 |
|---|---|
| 在哪 | `backend/version_manifest.json` 是一個 JSON 陣列，每筆有 `module/version/date/time/content`。<br>啟動時 `_sync_module_versions`（`helpers/startup.py:449`，由 `main.py:612` 呼叫）把它同步進 DB。<br>`/api/system/version` 讀它（`routers/auth.py:290-301`）。 |
| 守門 | `tests/test_version_manifest_2026_09_22.py`：manifest 不可舊於最新 commit（:78）；每個模組一筆（:168）；只存在 DB 的列會被抓（:365）。<br>打包時 `tools/check_version_sync.py`（`build_deploy_package.ps1:338`）。 |
| 不走的後果 | 「版本紀錄」頁看不到新模組；manifest 落後於 commit 時，:78 會紅。 |

### 1.12 選單登記

| 項目 | 內容 |
|---|---|
| 在哪 | `frontend/static/sidebar.js`：`computeFlags` :470-510、`_FILE_MODULE` :556、`_navGroups` :613、`ni()` :616、`sec()` :632、`renderMainNav` :641、`buildSidebar` :685 起。<br>頁面層禁入：`_deniedPages`（:608、:618、:841）由 `ni()` 的顯示條件推出，命中時呼叫 `_showNoPermission`（:936）。<br>`static/auth-guard.js` **只驗 session，不驗模組**（:22-57）。 |
| 守門 | 有 9 支測試用 regex 讀 sidebar.js，包括：<br>`test_module_keys_consistency`（:62、:204、:245）<br>`test_sidebar_finance_2026_09_23`：分組條件必須是子項條件的聯集（:334）；顯示中的項目不可指向被拒的頁（:500）；同一檔名不可被條件不同的項目宣告（:550）<br>`test_sidebar_regroup_2026_09_22`（:39）<br>`test_page_script_deps_2026_09_23`：載了 sidebar.js 就必須載 notif.js（:92）<br>`test_bonus_module_flag`、`test_approval_settings_orphan_entry`、`test_jv4_voucher_page_under_cashier`、`test_session_update_policy`、`test_alpine_double_init` |
| 不走的後果 | 頁面沒有入口；或者有入口但 `_deniedPages` 沒有涵蓋，手打網址就能進去（只剩後端守門）。 |

### 1.13 db.py migration 規則

| 項目 | 內容 |
|---|---|
| 在哪 | `schema_version` 單列表（`db.py:418-422`）、`CURRENT_VERSION = 109`（:128）、`_MIGRATIONS`（:5371-5481）、`_run_migrations`（:839）。<br>規則寫在 `db.py:40-58`。**新增 migration 三步**：① 寫冪等的 `_mNNN_xxx`；② 加進 `_MIGRATIONS`，只能往後接；③ `CURRENT_VERSION` 加一。**新表另外兩步**：④ 展示分類（1.10）；⑤ JSON 備份（1.9）。<br>漏了 ③ 完全不會有症狀（:54-58）。 |
| 範例 | 建表：`_m108_bonus_item_people`（:4351）。加欄位：`_m105`（:4534），先用 `_col_exists`（:762）檢查。 |
| 守門 | `tests/test_migration_numbering_2026_09_23.py`：三個來源一致（:54）、前綴不重複（:81）、連號（:116）。<br>`tests/test_spec_debts_2026_09_22.py`：欄位不可消失（:190）、每支可以重跑兩次（:387）。<br>`tests/test_upgrade_path_2026_09_21.py:336`：migration 不可呼叫會演進的 helper（凍結的歷史不可呼叫活的程式碼，相關註解在 `db.py:4043`、:4284-4290）。 |
| 附註 | `backend/db_migration_plan.md` 不是規則文件，而是 v70/v71 的功能規劃（檔頭 :3-17 自己註明）。 |

---

## 2. 版型規範

**前提**：`frontend/css/style.css` 共 1670 行，**沒有表單類，也沒有被頁面使用的清單＋明細分割類**。61 頁中有 59 頁自帶 `<style>`（只有 `receivables.html`、`sales-orders.html` 沒有）。因此下面「照這頁做」挑的是**最接近共用類的現存頁**，不是理想樣板。

| 類別 | 共用定義（style.css） | 照這頁做 | 注意 |
|---|---|---|---|
| 設計變數 | `:root` :37-137。<br>品牌紅 `--accent` :60；`--success/warning/danger*` :63-79；`--topbar-h:104px` :96；`--radius` :97-98；`--shadow*` :99-101；v4 字級與間距 :118-133。<br>根字級 `html{font-size:15px}` :204 | — | 不要把 `--v4-body` 套到 `.data-table` 上（:114-116）。新顏色一律寫成變數，不要寫死 hex。 |
| 頁面骨架 | `.topbar` :215、`.main` :437、`.mnav` :454、`.page-header` :509。<br>**新頁建議用 `.pg / .pg__eyebrow / __t / __s / __a`**（:542-585） | `warranty.html`（`.pg*` 在 :94-98） | 25 頁自己定義 `.page-main` 取代 `.main`，不要再增加。 |
| 清單＋明細 | 共用類只有 `.main--queue`（:1448）和 `.queue-view-container`（:1459），**沒有任何頁面使用** | `payslips.html`：共用 `.panel`＋`.data-table`（:102-104），配本頁的 `.detail-pane`（:34）。`customers.html` 同一模式（:118、:344） | 兩頁都各自重寫了 `.data-table`（payslips :20-25、customers :58-70）。**平台層應該把 detail-pane 收成共用類再開始用。** |
| Modal | `.modal-overlay` :1477、`.modal-box` :1485（max-height `calc(calc(100dvh / var(--fz,1)) - 2rem)`，:1490）、`.modal-head/body/foot` :1493-1504。手機版在 :1375-1387 | `customers.html`：modal 放在 body 直下（:476、:529） | `account-items.html` 只用共用類（:167-186），但它的 modal 包在 `<main>` 裡（:60-61）。依 :139-144 的註解，深色模式下 fixed 定位可能跑版（未實測）。 |
| 表單元件 | **沒有共用類** | `customers.html`：`.form-grid/-2/-3/.form-group/.form-label/.form-input`（:99-116），用法見 :619-751 | 這是 15 頁以上複製的寫法，但仍屬本頁自訂。 |
| 狀態徽章 | `.badge` :917＋修飾類 `--draft/pending/signing/approved/sent/done/danger/rejected/warning/running/settled/lost/active/repair`（:928-946）。<br>視覺化燈號 `.vm-*`（:1537-1557）：品牌紅不參與狀態色（:1513-1532） | `quotations.html`（:287，對照表在 :649-660，沒有本地重寫） | 主要動作和危險動作靠形狀區分，不靠顏色（:55-57）。 |
| 空狀態 | `.empty / __icon / __text`（:1190-1196） | `warranty.html:147` | payslips、customers 用自訂的 `.empty-state`，不要照做。 |
| 按鈕 | `.btn` :954、`-primary` :973、`-ghost` :976、`-danger` :979、`-sm` :985、`-approve/-reject` :989-998、`.btn-icon` :1003 | `quotations.html` | — |
| 深色模式 | 只用 `:root[data-theme="dark"]`，做法是對 `body > *` 做 invert＋hue-rotate，排除 chrome 元素（:170-172）；圖片再反轉一次（:197-200） | `customers.html`：topbar、overlay、main、detail-pane、modal 都放在 body 直下（:181-189、:344、:476、:529） | **守門**：`tests/test_dark_mode_chrome_structure_2026_09_13.py`：chrome 元素必須在 body 直下（:79）；頁面不得自訂深色色盤（:129）。 |
| 字級 zoom | `static/sidebar.js:62-73`：`FZ_STEPS` 0.85/1/1.15/1.3，設定 `document.documentElement.style.zoom`，並同時設 CSS 變數 `--fz`（:73）；`motrixSetZoom` :117-120 同樣兩者都設 | `payslips.html:34`（`.detail-pane` 高度寫成 `calc(calc(100vh / var(--fz,1)) - var(--topbar-h))`） | ✅ **已修正**（commit `218d810`，2026-09-24）：根元素 zoom 會把 vh/dvh 一起放大，因此 49 檔 103 處改寫成 `calc(Nvh / var(--fz,1))`；`.mnav__panel` 加上 max-height 與內部捲動（`style.css:483-484`）。<br>🔴 **新頁規則**：以視窗高度限高的元素一律寫成 `calc(Nvh / var(--fz,1))`，不可以寫裸的 `Nvh`。<br>⚠ 守門只有 e2e `tests/test_e2e_font_zoom_fits_viewport_2026_09_24.py`（:116、:139、:157），**只量指定頁，沒有靜態掃描**，所以新頁寫裸 `vh` 不會紅。<br>⚠ `quotation-form.html`、`case-management.html`、`cashier.html` 尚未改寫（commit `218d810` 訊息註明等 hichan-8d 合回後補）。 |
| 斷點 | 1200（:1252）、1100（:502）、1023（:1421）、768–1023（:1260）、767（:1307、:1430、:1466、:1666）、479（:1401） | — | 新頁只用這組寬度，不要新增斷點。 |

**頁面引入慣例**（以 `customers.html` 為例）：第 5 行放同步深色腳本 → favicon（:7）→ `auth-guard.js`（:9）→ 需要時載入共用工具 → Alpine（:11）→ `style.css`（:13）→ 本頁 `<style>` → body 尾端 `notif.js`（:1307）→ `sidebar.js`（:1308）。
**守門**：`test_page_script_deps_2026_09_23.py:92`（有 sidebar 就必須有 notif）；`test_ac1_write_actions_2026_09_23.py:208`（頁面要不是有寫入動作，就要登記進 `READ_ONLY_PAGES` :77）。

**共用前端元件**：
- `list-sort.js`：清單排序與拖曳，存在 `/api/list-prefs`（:37 `applyListSort`）
- `edit-presence.js`：同時編輯警示（:184 `MotrixPresence`）
- `approval-cascade.js`：同一人連續多層簽核時一次確認（:65 `MotrixApproval`）
- `gov-lookup.js`：依公司名稱查政府登記資料（:25 `MotrixGovLookup`）

---

## 3. 既有功能地圖

### 3.1 掛載

`backend/main.py:28` 一次 import 所有 router，`:617-662` 逐一 `include_router`。
- 只有 `dev_crm` 在 include 時加 `prefix="/api"`（:632）。
- `account_items`、`bonus`、`vouchers` 在 APIRouter 上自帶 prefix（`account_items.py:41`、`bonus.py:46`、`vouchers.py:59`）。
- 其他 router 的完整路徑直接寫在 decorator 上。

### 3.2 模組一行摘要（router｜主要表｜前端頁｜權限）

- **quotations**：報價、案件 caseRecord、階段、收款、結算、簽核佇列｜quotations、case_stages、case_change_requests｜quotation-form、quotations、`js/case-management.js`、approval-queue｜多數端點沒有模組檢查；收款寫入要 `cashier`（:2209、:3084）
- **material_orders**：叫料，寫在 `caseRecord.materialOrders`，沒有獨立表（:14）｜—｜case-management｜`project_manage`（:94）
- **case_extra_expenses**：案件額外支出｜同名表｜case-management｜admin 或案件擁有者（:155）
- **shipping_notes**：出貨單、扣庫存｜shipping_notes｜case-management、shipping-export-history｜`case_manage`/`quotation`（:107）
- **completion_notes**：完工單｜同名表｜completion-note-form｜`case_manage`/`quotation`（:227）
- **payment_requests**：請款單｜同名表｜payment-request-form｜`case_manage`/`finance`/`cashier`/`quotation`（:68）
- **invoice_vouchers**：發票開立簽核單｜同名表｜case-management｜同上四個 key（:69）
- **contractor_vouchers**：承攬商匯款申請｜contractor_payment_vouchers｜case-management、cashier｜同上四個 key（:62）
- **vendor_contractors**：承攬商與派工｜vendor_contractors、contractor_dispatches｜vendor-contractors、settlement｜`procurement`/`case_manage`/`contractor_list`（:171）
- **contractors / payslips**：點工人員與勞務報酬單｜contractors、payslips｜contractors、payslips、payslip-form｜`contractor_list`；`payslip`＋superadmin（`payslips.py:139`）
- **cashier**：應收與應付佇列，沒有自己的表｜cashier（`receivables.html:11` 轉址過來）｜`cashier`/`finance`（:37-38）
- **reports**：財報、帳齡、現金、稅務，沒有自己的表｜reports｜`reports`/`finance`（:59-60）
- **vouchers**：會計傳票｜vouchers_all、voucher_lines、voucher_attachments｜voucher｜`cashier`/`finance`（:69-73）
- **account_items / accounting_export**：會計科目／T100 匯出｜account_items｜account-items｜只檢查登入（:149）／admin（:205）
- **bonus**：獎金分潤｜bonus_*｜bonus｜`_is_manager`（:50），不走模組 key
- **inventory / parts / suppliers / customers**：庫存、料號、供應商、客戶｜stock_*、parts、suppliers、customers｜同名頁｜`inventory.py:52`、`parts.py:75`、`suppliers.py:36`、`customers.py:29`
- **dev_crm**：業務開發｜dev_cases、dev_logs｜dev-crm｜`dev_crm`（:88-93）
- **dashboard / daily_tasks**：首頁與設備；每日工作｜只讀別人的表；daily_tasks｜index、devices、warranty、daily-tasks｜`dashboard.py:624`、`daily_tasks.py:308`
- **system / auth / org_structure / approval_delegates**：設定、稽核、登入、組織、代理人
- **network_plans(_quick)**：網路規劃書｜network_plans｜network-plans、network-plan-form、topology-quick｜`netplan*`（:39）
- **7 支選型導覽**（env/netarch/switch/monitor/access/gateway/automation_guide）：各自的 *_categories/scenarios/products 表｜`<x>_guide`/`<x>_guide_edit`（例如 `access_guide.py:22`）
- **tender_radar / map_points**：標案雷達與地圖｜tender_*｜`tender_radar`（:42）
- **module_versions / search / list_prefs / uploads / licensing**：輔助功能

### 3.3 模組串接（主幹：業務開發 → 報價 → 案件 → 單據 → 財務）

```
dev_crm ──轉換──▶ quotations（data_json；caseRecord 在 data_json 裡）
                    │
   ┌────────────────┼──────────────┬──────────────┬──────────────┐
   ▼                ▼              ▼              ▼              ▼
shipping_notes  completion_notes  payment_requests invoice_vouchers material_orders
 (扣 stock_items)  (讀報價)        (讀額度)          (讀額度)          (寫 caseRecord)
   │
   ▼
cashier（讀 caseRecord.payment）◀── contractor_vouchers ◀── vendor_contractors（派工）
reports／bonus／dashboard／accounting_export／vouchers：讀上面全部
```

| 串接 | 證據 |
|---|---|
| 業務開發 → 報價 | `dev_crm.py:556` `mark_converted` 讀 quotations。報價刪除時回頭清除 `dev_cases.converted_quote_no`（`quotations.py:2027`） |
| 業務開發 → 客戶 | `dev_crm.py:183` 直接 UPDATE `customers.data_json` |
| 報價 → 案件 | caseRecord 存在 `quotations.data_json`，由 `update_case_record` 呼叫 `save_quotation_json` 寫入（`quotations.py:2272`；`helpers/quotations.py:427-452`） |
| 案件 → 庫存 | `_sync_device_stock` UPDATE `stock_items`（`quotations.py:2080`、:2091） |
| 出貨 → 報價／庫存 | 讀報價：`shipping_notes.py:190`。核准時 UPDATE `stock_items` 為 shipped（:453），撤回時還原（:521） |
| 完工 → 報價 | `completion_notes.py:263` |
| 請款／開票 → 報價 | 額度計算：`payment_requests.py:183`、`invoice_vouchers.py:153` |
| 案件財務總覽 | `quotations.py:3619-3693`：讀四張別的模組的單據表 |
| 出納 → 案件收款 | `cashier.py:53-62` 讀 `$.caseRecord` 的 payment.items；寫回走 `PATCH /api/quotations/{no}/payment/{idx}`（`quotations.py:3074`，由 `cashier.js:308` 呼叫） |
| 派工 → 匯款 | `contractor_vouchers.py:240` 讀派工，:268 直接 UPDATE `contractor_dispatches.payable_date` |
| 派工 → 報價 | `vendor_contractors.py:768-839`：import-to-quote，把品項 append 到 `data_json.items` 後寫回 |
| 傳票 ← 各單據 | `vouchers.py:463-480`（派工、額外支出）、:529（報價）；附件取自 `helpers/voucher_attachments.py:109`、:140、:297-303 |
| 獎金 ← 結算 | `bonus.py:443` 讀 `$.settlement`；:663 讀候選案件 |
| 報表 ← 全部 | `reports.py:198-210`、:2504、:2563-2595、:3571-3629 |
| 案件階段 → 每日工作 | `helpers/case_stage_tasks.py:59`、:104 寫 daily_tasks |

### 3.4 模組化的耦合點（平台化要知道，不要跟著做）

- **直接寫別的模組的表**：`shipping_notes.py:453` 和 `quotations.py:2080` 寫 stock_items；`contractor_vouchers.py:268` 寫 dispatches；`dev_crm.py:183` 寫 customers；`quotations.py:2027` 寫 dev_cases。
- **依賴 caseRecord 的 JSON 形狀，沒有存取層**：`cashier.py:62`、`reports.py:210`、`bonus.py:443`、`dashboard.py:939-965`。
- **router 之間 import 私有函式**：`accounting_export.py:76-77`（從 reports、contractor_vouchers 取）、`cashier.py:29-30`、`vouchers.py:32`。
- **兩個叫料欄位並存**：`caseRecord.materialOrders`（`material_orders.py:134`）和 `caseRecord.materials`（`dashboard.py:939-965`）。

---

## 4. 新增一個模組的檢查清單

以「新 router＋新頁＋新表」為例。每一步後面寫的是**漏做時會紅在哪一支測試**；寫「—」的，表示漏做了也不會紅。

| # | 動作 | 檔案 | 漏做時紅在哪 |
|---|---|---|---|
| 1 | 寫 migration `_mNNN_xxx`，冪等、只新增 | `db.py`（規則在 :40-58） | `test_spec_debts:387`（重跑兩次）、`:190`（欄位不可消失）、`test_upgrade_path:336` |
| 2 | 加進 `_MIGRATIONS`，`CURRENT_VERSION` 加一 | `db.py:5371-5481`、:128 | `test_migration_numbering:54/81/116`。⚠ 漏了 `CURRENT_VERSION` 在執行期完全沒有症狀 |
| 3 | 新表做展示分類 | `db.py:342` 或 :334 | `test_demo_reset:223` |
| 4 | 新表登記 JSON 備份，或寫理由排除 | `archive.py:1506`，或 `test_system_audit:72` | `test_system_audit:127`、`:157`、`:265` |
| 5 | router 檔加進 import 和 include | `main.py:28`、:617-662 | `test_router_registration:46`、:73 |
| 6 | 每支端點都呼叫守門函式（`_?require_?\w*` 或 `_guard_\w*`） | 新 router | `test_system_audit:647`。公開端點要同時登記 `_PUBLIC_ROUTES`（:605）和 `main.py:99-114` 的 `_PUBLIC_API_PATHS`（兩份不同源） |
| 7 | DELETE 端點要檢查角色或擁有者（只有 `_require_user` 不算） | 新 router | `test_system_audit:695` |
| 8 | 模組 key 三處一起補：目錄、側欄、後端 | `users.html:792`（必要時也改 :718）、`sidebar.js`、router | `test_module_keys_consistency:119/130/138/222/264` |
| 9 | 側欄項目與分組條件 | `sidebar.js:613-685` | `test_sidebar_finance:334/500/550`；e2e 清單 `test_e2e_page_module_guard:65` 要手動補（漏了不會紅） |
| 10 | 頁面載入 notif.js＋sidebar.js | 新頁 | `test_page_script_deps:92` |
| 11 | 頁面要有寫入動作，或登記唯讀 | 新頁，或 `test_ac1_write_actions:77` | `test_ac1_write_actions:208` |
| 12 | chrome 與 modal 放在 body 直下；不自訂深色色盤 | 新頁 | `test_dark_mode_chrome_structure:79/129` |
| 12b | 以視窗高度限高的元素寫成 `calc(Nvh / var(--fz,1))` | 新頁 | —（e2e 只量指定頁，見 §2 字級列） |
| 13 | 例外原文不放進 detail；GET 不收憑證 | 新 router | `test_exception_detail_leak:378`、`test_no_credentials_in_query:414` |
| 14 | 持有寫入鎖時不可跨連線寫入（`_audit` 也算） | 新 router | `test_write_lock_deadlock_guard:154` |
| 15 | email 事件登記 | `notification_prefs.py:17` | `test_notification_prefs_coverage:33`（只認字面值） |
| 16 | 有簽核的話：加 doc type、進佇列、進設定頁 | `tiered_approval.py:54/64`、`quotations.py:3784`、`approval-settings.html:448` | `test_approval_flow_scope:248`、`test_queue_and_feed_scoping:158`；**設定頁有沒有這個類型沒有測試守**（bonus 已經是反例） |
| 17 | version_manifest 加一筆 | `version_manifest.json` | `test_version_manifest:78/168` |
| 18 | 寫入動作呼叫 `_audit` | 新 router | — |
| 19 | 有背景排程的話放進閘門 | `main.py:552-576` | — |
| 20 | 新 API 要有前端入口 | — | 只在打包時由 `tools/check_endpoint_entrypoints.py`（`build_deploy_package.ps1:418`）檢查；找不到檔案時只印 SKIP |

**覆蓋率守門**：**不存在**。`backend/pytest.ini:1-5` 沒有 `--cov` 也沒有 `fail_under`，repo 內找不到 `.coveragerc`。`conftest.py:759` 只強制要求 `--basetemp`。

---

## 5. 模組化與自訂前置（延伸盤點 §3-§5）

> **本節的行號基準是 `7309971`**（§1-§4 仍以 `1eaa5d3` 為準）。兩版之間 `quotations.py`、`sidebar.js`、`pdf_gen.py` 等檔案的行號有位移，本節一律使用新號。

### 5.0 界線（定案）

**兩條使用者裁示（皆為 2026-09-24，經 hichan-0a 轉達）：**
- **N7**：「附加登記允許、改行為逐點問」。
- **定調（B1／B2 的回答）**：「平台化是獨立的功能，讓未來可獨立不寫代碼也能帶入相關功能」。

⇒ 平台層是一個**獨立的模組**。它有自己的單據、表單、輸出，**不把欄位塞進既有單據**。對既有模組只做兩件事：
1. **唯讀引用**既有資料（§5.7）。
2. 做 **A 類登記**。

**A 類「附加登記」＝允許**：在既有登記表的尾端加一列，不改動任何既有列，也不改變任何既有邏輯。

| 登記表 | 位置 | 加一列時守的測試 |
|---|---|---|
| router 掛載 | `main.py:28`（import）、:617-662（include） | `test_router_registration:46/73` |
| migration | `db.py` 新增 `_mNNN`＋`_MIGRATIONS`（:5371-5481）＋`CURRENT_VERSION`（:128） | `test_migration_numbering:54/81/116` |
| 展示分類 | `db.py:342`（或 :334） | `test_demo_reset:223` |
| JSON 備份 | `archive.py:1506` | `test_system_audit:127` |
| 權限目錄 | `users.html:792`（角色樣板在 :718） | `test_module_keys_consistency` |
| 選單靜態項目 | `sidebar.js` `buildSidebar`（:685 起）的 `ni()` 項目 | `test_sidebar_finance:334/500/550` |
| 版本紀錄 | `version_manifest.json` | `test_version_manifest:78/168` |
| 簽核單據類型 | `tiered_approval.py:54`、:64；`approval-settings.html:448` | `test_approval_flow_scope:248` |
| email 事件 | `notification_prefs.py:17` | `test_notification_prefs_coverage:33` |

**灰色地帶的判定規則**（本文提出，不是裁示）：

| 動作 | 類別 |
|---|---|
| 在 tuple／list／dict 常數加一項 | A |
| `CURRENT_VERSION` 加一（新增 migration 的機械步驟） | A |
| 用新 migration 建新表 | A |
| 在既有函式或 if 鏈裡加一個分支 | B |
| 對既有表 `ALTER` 加欄位 | B |
| 修改既有列的值 | B |

**B 類「改既有行為」＝逐點問**：每一點都列在 §5.10 待問清單。

### 5.1 示範主線：平台上新建一種自訂單據

**範例**：「現場勘查單」，doc type 為 `pf_site_survey`。
- 欄位：客戶（引用）、關聯報價單（引用）、勘查日期、現場聯絡人、備註。
- 流程：定義 → 填寫 → 存檔 → 讀回 → PDF，可選擇送審。

| 步驟 | 做法 | 用到的既有接點 | 類別 |
|---|---|---|---|
| ① 定義 | 在 `platform.doc_types`、`platform.fields.pf_site_survey` 寫入定義（§5.2） | `helpers/settings.py:11/28` | 不需登記 |
| ② 填寫 | 平台自己的通用表單頁，依欄位定義渲染（`frontend/pages/platform-doc.html`，新檔） | 版型照 §2 | A（新頁＋選單入口，見 §5.10 B6） |
| ③ 引用 | 在「客戶」欄位選一位客戶、在「報價單」欄位選一張單，把指定欄位帶進來（§5.7） | 既有 GET 端點與權限函式 | 純引用 |
| ④ 存檔 | `POST/PUT /api/platform/docs/{docType}`，寫入新表 `pf_documents`（§5.3） | `next_entity_code`（`db.py:5486`）、`_audit`（`helpers/audit.py:92`） | A（新 router、新表） |
| ⑤ 讀回 | `GET /api/platform/docs/{docType}/{id}`，依單據上凍結的樣板版本顯示（§5.4） | — | A |
| ⑥ 輸出 | 平台自己的 PDF（§5.6） | `run_edge_pdf`（`startup.py:75`）、`company_identity` | 純引用 |
| ⑦ 送審（可選） | 用簽核引擎展開關卡，項目併進現有簽核佇列（§5.5） | `tiered_approval`；佇列 | 引擎＝純引用；佇列＝**B5（已同意）** |

**驗收（先寫題，題要先紅）**：定義一個欄位 → 填寫 → 存檔 → 重新讀回的值相同 → PDF 內含該值 → 改定義之後，舊單仍依舊版顯示。
這條主線要釘住的是「寫入 → 讀回 → 輸出」三段，**不可以出現「有 schema、零寫入點」**（前例：`vouchers_all.custom_fields`，`db.py:5265`）。

### 5.2 定義登錄（doc_types／fields／menus）

**第一階段存在 `system_settings`，使用 `platform.` 命名空間。**
- 這張表已經在每日 JSON 備份裡（`archive.py:1583-1587`），展示重置時也會整張清（`db.py:364`）。
- 讀寫接點已經存在：`helpers/settings.py:11/28`。前例是條款組 `quote_terms_presets`（`routers/system.py:1672-1723`）。
- 因此定義本身不需要任何登記。

| key | 形狀（草案） |
|---|---|
| `platform.doc_types` | `{"pf_<snake>": {label, moduleKey, numberPrefix, templateId, approval: bool}}`；docType 一律以 `pf_` 開頭，確保不會和既有的 `APPROVAL_DOC_TYPES` 撞名 |
| `platform.fields.<docType>` | `[{key, label, type:"text\|number\|date\|select\|bool\|ref", ref?:{source, pick:[…]}, options?, required?, order, section, showOnPdf}]`；`type:"ref"` 的規則見 §5.7 |
| `platform.menus` | 本期不用：選單只有一個靜態「自訂功能」入口（B6 定案），入口頁從 `platform.doc_types` 列出所有自訂單據 |

**升級條件**：定義數量或查詢需求超過單一 JSON 值能承受時，改成實表 `pf_doc_types`、`pf_fields`。改實表時要做第 4 節的 1-4 步，都是 A 類。

### 5.3 自訂單據的資料存放

- **新表 `pf_documents`**：`id, doc_type, doc_no UNIQUE, status, data_json, approval_json, template_id, template_version, location_id, created_by, created_at, updated_at`。
  - 做法是新 migration 建新表，並登記展示分類（屬於使用者資料，整張清）與 JSON 備份，都是 A 類。
  - `approval_json` 單獨一欄，比照 `vouchers_all`、`bonus_awards`（佇列就是從這一欄讀的，見 `quotations.py:4409-4415`）。
- **欄位值**：放在 `data_json.fields = {<key>: value}`。系統保留鍵只有 `platformTemplate`、`refs`、`locationIdentity` 三個，欄位 key 不可以用這三個名稱。
  - 盤點當初設計的 `customFields` 命名空間，是給「延伸既有單據」用的；依定調，本期不做，保留名稱不用。
- **驗證**：存檔時比對凍結的欄位定義，未知的 key 一律**拒絕**，不可以靜默丟掉。前例是 `voucher_template.validate_template_body` 在存檔當下驗證（`helpers/voucher_template.py:100`）。
- **單號**：`next_entity_code(conn, "pf_documents", prefix, "doc_no")`（`db.py:5486`），並接住 IntegrityError 重試。
- **狀態鎖**：送審後拒絕修改，比照報價的 `_LOCKED`（`quotations.py:1500`）。
- **同時編輯**：比照報價的 `_expectedUpdatedAt`，版本不符時回 409（`quotations.py:1497-1499`）。

### 5.4 樣板版本化與凍結

- **表結構前例**：兩表制，`<x>_templates` 管穩定的 id，`<x>_template_versions` 管歷史，每次編輯新增一列、不覆蓋（`db.py:5170-5180` 傳票、`db.py:5041` 獎金）。
- **凍結前例**：`company_identity.snapshot_for` 在送出當下寫入快照，之後不重查（`company_identity.py:163-186`）。
- **第一階段存法**：`platform.templates.<docType> = {currentVersion, versions:[{version, fields, output, createdAt, createdBy}]}`，只能 append。
- **凍結時機**：
  - 單據**建立時**，在 `pf_documents.template_id/template_version` 記下當時的版本。
  - **送審時**，把該版的欄位定義快照到 `data_json.platformTemplate`。
  - 送審端點是平台自己的，所以**不需要 B 類**。
- **舊單顯示**：永遠依自己的快照。這也補上盤點提過的缺口：報價的 `FORM_VERSION` 只有顯示、沒有存下來。

### 5.5 簽核

- **平台單據直接使用引擎**（純引用）：
  - 取流程：`resolve_active_flow_setting("pf_<x>")`（`tiered_approval.py:88`）。
  - 展開關卡：`setting_to_active_tiers`（:296）。
  - 權限：`check_approve_permission`（:354）、`check_reject_permission`（:436）。
  - 代理：`active_delegators_for`（:339）。
- **新 doc type 要登記**：加進 `APPROVAL_DOC_TYPES`、`APPROVAL_DOC_TYPE_LABELS`（`tiered_approval.py:54/64`），以及 `approval-settings.html:448` 的 `docTypeOrder`，屬於 A 類。
  - ⚠ 三處都要加。§1.2 已經有反例：`bonus` 只加了後端，結果設定頁設不到。
- **條件簽核**：
  - 平台單據：`platform.approval_rules.<docType> = [{when:{field, op, value}, flowKey}]`，在平台自己的送審端點裡先選好流程，再交給引擎。屬於 A 類，引擎本體不改。
  - 既有單據：維持待問（**B4**）。
- **併進現有簽核佇列（B5，使用者已同意「併進現有簽核佇列」）**：要改的地方如下。

| # | 位置 | 改法 | 約束 |
|---|---|---|---|
| B5-a | `routers/quotations.py:3903` `get_approval_queue` | 加一段讀取 `pf_documents`（`status IN ('待審核','簽核中')`）的程式，組出 `type:"platform_doc"`、`pfDocType`、`id`、`title` 的項目 | 過濾只能有一處，而且要在分組之前：`_queue_visible_to(` 只出現一次（:4349）。守門是 `test_queue_and_feed_scoping:158` |
| B5-b | `routers/quotations.py:4369` `get_approval_queue_count` | 加一句 `SELECT approval_json FROM pf_documents WHERE status IN (...)` | 每一頁的頂欄都會呼叫它（`notif.js`），要保持輕量 |
| B5-c | `routers/quotations.py:5604` `approval_queue_detail` | 加 `platform_doc` 分支，改成呼叫平台 router 的明細函式 | 權限維持「登入即可看」（:5608-5611 docstring），動作權限由平台端點自己把關 |
| B5-d | `frontend/pages/approval-queue.html:1198` `docTypeLabel`、:1228 `apiBase`、:1242 `itemPathId` | 加 `platform_doc` 分支：標籤取 `platform.doc_types` 的 label，API 指向 `/api/platform/docs/{pfDocType}` | 核准的網址組法在 :1590-1594 |
| （選） | `routers/quotations.py:5878` `_REASSIGN_TABLES` | 轉簽要支援平台單據的話，才需要加 | 不在示範主線內 |

- 以上全部屬於 B 類，**已獲使用者同意**，範圍限於這幾處。
- 做法沿用既有 11 種單據的寫法。每種單據各一段 SELECT 是佇列目前的結構（`type` 值見 :3940-4319），這次不重構。

### 5.6 輸出樣板

- **樣板語言**：沿用 `voucher_template.py` 的模式：
  - 封閉的佔位符清單（:37）。
  - 每個佔位符都有取值來源，而且兩個方向都守（`PLACEHOLDER_RESOLVERS` :56）。
  - 單層大括號語法（:78）。
  - **儲存樣板時就驗證**（:100、:112）。
  - 佔位符清單由欄位定義自動產生；`ref` 欄位用點記法，例如 `{客戶.統編}`，只能取 §5.7 白名單內的欄位。
- **渲染**：
  - 平台自己組 HTML，交給 `run_edge_pdf`（`helpers/startup.py:75`，會自動取用 `EDGE_PDF_SEMAPHORE`），並檢查 0 byte。
  - 抬頭用 `apply_snapshot(location_identity(...), payload)`（`company_identity.py:82`、:220）。
  - 抬頭與頁尾的 HTML 可以 import `pdf_gen._identity_head/_foot`（`pdf_gen.py:543/559`，私有函式），也可以平台自己寫一份。
- **一份定義驅動所有出口**：表單、讀回、PDF 都讀同一份凍結定義。
- **歸檔**：`archive._pdf_archive_dirs()`（`archive.py:1116-1131`）寫死 6 類。平台 PDF 要進鏡像歸檔，就得在那份清單加一列，屬於 A 類。示範主線可以先不歸檔。
- **範圍**：依盤點 R1，只做單據 PDF，不做多段式報表。

### 5.7 帶入既有功能的資料（唯讀引用）

**原則**：平台單據只**讀**既有資料，**權限沿用既有守門**，帶入的值**在存檔時凍結**。

**權限怎麼沿用（兩條路都不需要改既有碼）**：

1. **前端挑選**：平台表單的挑選器直接用使用者自己的 token 打既有的 GET 端點。既有的 `require_any_module` 與擁有者檢查會原樣生效。
2. **後端存檔時查核與快照**：平台 router 直接呼叫**同一支既有的路由函式或 helper**，把使用者的 `authorization` 傳進去，讓守門邏輯走同一條路。
   - 例如 `customers.get_customer(cid, authorization)`，或先查出單筆再呼叫 `_check_quotation_owner(row, user)`。
   - **不要自己寫 SELECT 繞過守門。**
   - 前端送來的快照值不可以信任，必須由後端重查。

| 來源（source_type） | 既有端點或函式 | 權限（沿用） | 可帶入的欄位（白名單草案） |
|---|---|---|---|
| `customer` | `GET /api/customers`（`customers.py:26`）、`/api/customers/{cid}`（:48） | `customer`/`case_manage`/`dev_crm`/`procurement` 其中之一（:29、:51） | 名稱、統編、電話、`data_json` 內的地址與聯絡人 |
| `quotation` | `GET /api/quotations`（`quotations.py:699`）；單筆 `/api/quotations/{quote_no}`（:1060） | 清單：非 admin 只看得到自己可見的案件（`_visible_case_filter_sql`，:744-747）；單筆：`_check_quotation_owner`（`helpers/quotations.py:17`） | 單號、專案名稱、客戶名稱、報價日、`tot.total`（唯讀，不可回寫） |
| `supplier` | `GET /api/suppliers`（`suppliers.py:33`） | `customer`/`procurement`/`inventory`；**非 admin 一律回空清單**（:37-38） | 名稱、統編、電話 |
| `part` | `GET /api/parts`（`parts.py:51`） | `procurement`/`case_manage`/`inventory`（:54） | 料號、品名、規格 |
| `vendor_contractor` | `GET /api/vendor-contractors/selectable`（`vendor_contractors.py:192`） | `procurement`/`case_manage`/`contractor_list`（:195） | 名稱、聯絡人、電話 |
| `user` | `GET /api/users/selectable`（`auth.py:1597`） | 登入即可 | 顯示名稱、帳號 |
| `org` | `GET /api/org/tree`（`org_structure.py:40`） | 登入即可 | 處與部門名稱 |
| 既有附件（9 種） | `helpers/voucher_attachments.source_files`（:119，白名單在 :54-64） | ⚠ **這支 helper 本身不檢查權限**，呼叫前要先對它的上層單據做權限檢查（例如先過 `_check_quotation_owner`） | 檔案 metadata；帶入時一律「複製」（:6-15、`copy_into` :250） |

**引用記錄的形狀**：`data_json.refs = [{field, source_type, source_key, label, snapshot:{…}, pickedAt}]`。
- `source_key` 一律存 **TEXT**，才放得下單號與「案件編號_序號」這類組合鍵（`voucher_attachments.py:84`）。
- `snapshot` 只存白名單內的欄位，而且**不重查**（比照 `locationIdentity`）。
- 顯示時可以另外標示「來源已變更」或「來源已刪除」，但 PDF 印的是快照。
- 需要反查「哪些平台單據引用了報價 X」時，再加索引表 `pf_references(from_id, source_type, source_key)`，屬於 A 類。本期不做。

**擋錯人風險**（參考 `auth.py:176-180` 的教訓）：使用者有平台模組，但沒有來源模組（例如沒有 `customer`）時，挑選器會拿到 403。
- 挑選器必須顯示「你沒有引用客戶資料的權限」，**不可以顯示成空清單**。
- 欄位定義頁也要標示每個 `ref` 欄位需要哪個模組。

**JV36 是這個模式的實例**（`docs/windows/SPEC-JV28-ATTACHMENT-PREVIEW.md` 檔尾）：傳票的某一行選到來源 XXX 之後，列出 XXX 的附件，勾選才複製，並記住來源。
- 它的 `source_type`＋`source_key`（TEXT）與上表的引用記錄同形狀。
- ⚠ `voucher_lines.source_id` 是 INTEGER，而且三個 INSERT 都沒有寫入它（`vouchers.py:280/973/1138`，以 `1eaa5d3` 為準）。hichan-0a 已轉告 hichan-61 改用 TEXT 語意。
- 平台層的附件引用可以直接委派給 `source_files`，不改傳票的程式碼。

### 5.8 版型與入口

- **入口**：`sidebar.js` 靜態加一個「自訂功能」項目，指向 `platform-docs.html`（新檔，列出 `platform.doc_types`），屬於 A 類（**B6 定案**）。
  - 平台模組 key（草案 `platform` 與 `platform_admin`）要照 §4 第 8 步，在三處一起登記。
- **新頁版型**：
  - 骨架用 `.pg*`；清單＋明細參照 `payslips.html`；modal 放在 body 直下。
  - 以視窗高度限高的元素寫成 `calc(Nvh / var(--fz,1))`（§2）。
  - 要通過 §4 第 10-12b 步的頁面守門。

### 5.9 接點逐一標類

| # | 接點 | 平台層的用法 | 類別 |
|---|---|---|---|
| 1 | `run_edge_pdf` | 直接 import | A（純引用） |
| 2 | `_identity_head/_foot`（私有函式） | 直接 import，或平台自己寫一份 | A（純引用）；搬到 helper＝B9 |
| 3 | `location_identity/snapshot_for/apply_snapshot` | 直接使用 | A |
| 4 | `tiered_approval` 函式；新增 doc type | 平台單據直接使用；登記三處 | A |
| 5 | 既有單據套用簽核條件 | — | B4（待問） |
| 6 | 簽核佇列 | §5.5 的 B5-a～d | **B5（已同意）** |
| 7 | `_notify`／`_audit` | 直接使用 | A |
| 8 | email 事件 | `EVENT_GROUPS` 加一列 | A |
| 9 | `next_entity_code` | 直接使用，並接住 IntegrityError | A |
| 10 | `save_document_files` | 平台單據上傳附件時使用，呼叫前先驗 `doc_no` | A；在原函式補檢查＝B8（待問） |
| 11 | `_get_setting/_set_setting` | 定義登錄 | A |
| 12 | 模組 key | 平台 key 照 A 類三處登記 | A；收斂成單一來源＝B7（待問） |
| 13 | 選單 | 靜態加「自訂功能」入口 | **A（B6 定案）** |
| 14 | 平台自己的表單與輸出 | 新頁、新 router、平台自己的 PDF | A（取代原本的 B1／B2） |
| 15 | 平台 router 掛載 | `main.py` 加一列 | A |
| 16 | caseRecord 存取 | 只經由 `GET /api/quotations/{no}` 或 `_check_quotation_owner` 後讀取 | A；既有讀取點改走共用存取層＝B10 |
| 17 | 唯讀引用（§5.7） | 呼叫既有 GET 路由函式與權限 helper | A（純引用） |
| 18 | `pf_documents` 新表 | migration、展示分類、備份 | A |

### 5.10 待問清單（B 類）

**更正紀錄**：前一版（`7309971`）的 B1～B3 以「把自訂欄位加進報價單」為前提。依定調，這三項取消，保留原列供查。

| # | 點 | 狀態 | 影響誰 | 替代做法 | 要問使用者的一句話 |
|---|---|---|---|---|---|
| ~~B1~~ | ~~報價表單加 customFields 掛載點~~ | **取消**（定調：平台是獨立功能） | — | 改用平台自己的表單（§5.1 ②） | — |
| ~~B2~~ | ~~正式報價 PDF 印出自訂欄位~~ | **取消** | — | 改用平台自己的 PDF（§5.6） | — |
| ~~B3~~ | ~~報價原本的存檔路徑驗證 `cf_*`~~ | **取消** | — | 驗證只做在平台存檔端點（§5.3） | — |
| **B4** | 既有單據依條件選簽核關卡（各 router 送審那一行；報價另有副本 `quotations.py:179`） | **待問** | 該單據的所有送審 | 條件簽核只給平台單據（§5.5，A 類） | 「依金額或欄位決定簽核關卡，第一版只給自訂單據，還是既有的報價單也要？」 |
| **B5** | 簽核佇列併入平台單據 | **定案：同意**（「併進現有簽核佇列」） | 佇列的所有使用者 | — | —（要改的四處見 §5.5 B5-a～d） |
| **B6** | 選單 | **定案：A 類**（「先集中在『自訂功能』入口」） | — | — | — |
| **B7** | 模組 key 收斂成單一來源，既有 8 處改讀它（§1.1） | **待問** | 全部權限檢查；`test_module_keys_consistency` 要改寫 | 平台 key 照舊三處登記 | 「權限模組清單要整併成一份（動到權限程式），還是維持現狀、新模組照舊登記？」 |
| **B8** | `save_document_files` 補 `doc_no` 穿越檢查（`uploads.py:63`；能否被利用尚未確認，見 N8） | **待問** | 5 個上傳呼叫點 | 平台呼叫前自己檢查 | 「上傳路徑的防護要在共用函式補一次（改既有程式），還是只在新功能自己檢查？」 |
| B9 | `_identity_head/_foot` 搬到 helper | 不問（主線用不到） | pdf_gen 的 9 支 builder | 直接 import 私有函式 | — |
| B10 | 既有 caseRecord 讀取改走共用存取層 | 不問（主線用不到） | 出納、報表、獎金、首頁 | 平台只經由既有端點讀取 | — |

**結論**：示範主線（§5.1 ①～⑥）**只用 A 類就能做完**。第 ⑦ 步送審要動的 B5 已獲同意。仍待使用者回答的只有 B4、B7、B8，三項都不擋主線。

---

## 我沒查什麼

- **行號時效**：
  - §1-§4 以 `1eaa5d3` 為準；§5 以 `7309971` 為準。
  - `1eaa5d3` 到 `7309971` 之間，`quotations.py`、`pdf_gen.py`、`sidebar.js`、`quotation-form.html` 等有位移，**§1-§4 沒有跟著重對**。例如 §1.2 的 `quotations.py:3784` 在新版是 :3904。
  - 第二版的 §1-§4 行號對照，只在該行內容相同時換號，沒有逐行重讀語意。
- **沒有跑任何測試、沒有啟動伺服器。** 「會紅在哪」與 §5.5 B5 的四處改動點都是讀碼推論。
  - `approval-history.html`（簽核歷史頁）是否也要加 `platform_doc` 分支，**沒有查**。
- **§5.7 的權限表**：只讀了各端點函式開頭的守門。
  - 欄位白名單是草案，沒有對照使用者需求。
  - `/api/quotations` 的 `_visible_case_filter_sql` 細節沒有展開。
  - 後端「直接呼叫既有路由函式」這個做法沒有實測：那些函式的簽名是 FastAPI 依賴注入的形式，**直接呼叫時參數預設值（例如 `Header(None)`）要記得明確傳入**。
- **§5.3 `pf_documents` 的欄位**是草案，沒有和 §4 的全部守門逐條推演。例如 `test_system_audit:265` 欄位覆蓋。
- **第一版的蒐集方式**：由 6 個唯讀 agent 蒐集，我抽查約 40 個行號，1 處有錯已更正。第二、三版沒有再派 agent。
- **§5.0 的灰色地帶判定規則**是本文提出的，不是裁示。
- **沿用未查**：
  - 206 個測試檔中，只 grep 了掃描型守門。
  - vh 處數不一致。
  - account-items 的 modal 在深色模式下是否跑版。
  - bonus 不在簽核設定頁是否刻意。
  - `next_entity_code` 撞號時是否回 500。
  - 完工單與薪資單的 PDF 歸檔。
  - `json_extract` 效能、手機版版型。
  - `system_settings` 存定義時的 JSON 大小與同時編輯。
