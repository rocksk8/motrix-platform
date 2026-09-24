# 平台化前置規劃：共用接點、版型、功能地圖、模組檢查清單、自訂前置（2026-09-24）

> **量測基準 HEAD `1eaa5d3e673cc9df8feea56e6992f8c33953a0d7`**：本文所有 `file:line` 都以這一版為準。
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

### 5.0 界線（定案）

> **使用者裁示（N7，2026-09-24 晨間表單，經 hichan-0a 轉達）：「附加登記允許、改行為逐點問」。**

**A 類「附加登記」＝允許**：在既有登記表的尾端加一列，不修改任何既有列，也不改變任何既有邏輯。已知的登記表如下（行號以本版為準）：

| 登記表 | 位置 | 加一列的一致性守門 |
|---|---|---|
| router 掛載 | `main.py:28`（import）、:617-662（include） | `test_router_registration:46/73` |
| migration | `db.py` 新增 `_mNNN`＋`_MIGRATIONS`（:5371-5481）＋`CURRENT_VERSION`（:128） | `test_migration_numbering:54/81/116` |
| 展示分類 | `db.py:342`（或 :334） | `test_demo_reset:223` |
| JSON 備份 | `archive.py:1506` | `test_system_audit:127` |
| 權限目錄 | `users.html:792`（角色樣板 :718） | `test_module_keys_consistency` |
| 選單靜態項目 | `sidebar.js` `buildSidebar`（:685 起）內的 `ni()` 項目 | `test_sidebar_finance:334/500/550` |
| 版本紀錄 | `version_manifest.json` | `test_version_manifest:78/168` |
| 簽核單據類型 | `tiered_approval.py:54`、:64；`approval-settings.html:448` | `test_approval_flow_scope:248` |
| email 事件 | `notification_prefs.py:17` | `test_notification_prefs_coverage:33` |

**A 類的判定規則**（本文提出，用來處理灰色地帶）：

| 動作 | 類別 | 理由 |
|---|---|---|
| 在 tuple／list／dict 常數加一項 | A | 只是登記一列 |
| `CURRENT_VERSION` 加一 | A | 屬於新增 migration 的機械步驟，受 `test_migration_numbering` 守 |
| 用新的 migration 建新表 | A | 不動任何既有表 |
| 在既有函式或 if 鏈裡加一個分支 | **B** | 即使只是「多支援一種」，它也改了那支函式的行為 |
| 對既有資料表 `ALTER` 加欄位 | **B** | 改了既有模組的資料形狀 |
| 修改既有列的值 | **B** | 改的是既有行為，不是新增登記 |

**B 類「改既有行為」＝逐點問**：每一點都列在 **§5.8 待問清單**，各附「影響誰、替代做法、要問使用者的一句話」。

**示範主線**：§5.1 到 §5.5 共用同一個示範案例——**報價單加一個自訂欄位 `cf_site_contact`（現場聯絡人），然後存檔 → 讀回 → PDF 印出**。每一節只寫它負責的那一段。

### 5.1 定義登錄（doc_types／fields／menus）

**做法：第一階段不開新表，存在 `system_settings`，使用 `platform.` 命名空間。**

理由（都是讀碼確認的）：
- `system_settings` 已經在每日 JSON 備份裡（`archive.py:1583-1587`，祕密欄位會先挖掉）。
- 展示重置時會整張清掉（`db.py:364`）。
- 讀寫接點已經存在：`helpers/settings.py:11` `_get_setting`、:28 `_set_setting`。前例是條款組 `quote_terms_presets`（`routers/system.py:1672-1723`）。

⇒ 這樣做**完全不需要 A 類登記**：沒有 migration、不用改展示清單或備份清單。

| key | 形狀（草案） |
|---|---|
| `platform.doc_types` | `{"<docType>": {label, baseDocType?: "quotation"…, moduleKey, numberPrefix, templateId, approvalDocType}}`。有 `baseDocType`＝延伸一張既有單據；沒有＝全新的單據類型（P5） |
| `platform.fields.<docType>` | `[{key:"cf_xxx", label, type:"text\|number\|date\|select\|bool", options?, required?, order, section, showOnPdf}]` |
| `platform.menus` | `[{group, label, href, moduleKey, order}]`，只能追加，不可改寫既有項目 |

**升級條件**：定義量或查詢需求超過單一 JSON 值能承受時，再改成實表 `pf_doc_types`、`pf_fields`、`pf_menus`。改成實表時要做第 4 節的 1-4 步，都屬於 A 類。

**示範案例（定義這一段）**：
- 在 `platform.fields.quotation` 加一筆 `{key:"cf_site_contact", label:"現場聯絡人", type:"text", showOnPdf:true}`。
- A 類登記：無。
- 平台層本身的新 router 要做這些 A 類登記：`main.py`；平台模組 key 要登記到 `users.html:792`、`sidebar.js`、`version_manifest.json`。
- B 類：無。

### 5.2 customFields 命名空間

- **位置**：`data_json.customFields = {"cf_<snake>": value}`。鍵一律以 `cf_` 開頭，確保不會和核心鍵相撞（核心鍵清單見盤點 §2）。
- **只存值、不存標籤**：標籤一律從凍結的樣板版本取（§5.3）。
- **驗證**：只要是平台層自己的寫入路徑，未知的 `cf_*` 一律**拒絕**，不可以靜默丟掉。前例是 `voucher_template.validate_template_body` 在儲存當下驗證（`helpers/voucher_template.py:100`）。
- **反面教材**：`vouchers_all.custom_fields`（`db.py:5265`）有 schema，但全 backend 沒有任何寫入點。

**示範案例（存檔 → 讀回這一段）**：

讀碼確認：**既有報價存檔與讀回的路徑不用改，就會原樣保留 `customFields`。**

| 環節 | 行為 | 證據 |
|---|---|---|
| 後端收件 | 存檔端點的 body 是 `data: dict`，沒有鍵白名單 | `routers/quotations.py:605-608` |
| 後端寫入 | 整包 `json.dumps` 進 `data_json` | `routers/quotations.py:1273` |
| 前端讀回 | 用 `Object.assign(this.q, row.data)` 合併，未知鍵會保留在 `q` 上 | `quotation-form.html:3398` |
| 前端存檔 | 送出 `{ ...this.q, tot }`，未知鍵會原樣送回 | `quotation-form.html:2563` |
| 改前改後紀錄 | 追蹤清單外的變動記成一筆「其他內容」 | `routers/quotations.py:114-120` |

建議的寫入路徑是 **A 類**：平台層新增 `PUT /api/platform/quotations/{no}/custom-fields`，只改寫 `customFields` 這一個鍵，並透過既有的 `save_quotation_json` 存檔（`helpers/quotations.py:427`）。這支端點要自己照抄兩道既有規則：
- **狀態鎖**：報價的 `_LOCKED` 狀態（`routers/quotations.py:1499`）底下拒絕寫入，否則送審後還改得動。
- **同時編輯**：報價表單下一次存檔時，會因為 `_expectedUpdatedAt` 不同而收到 409（`routers/quotations.py:1496-1498`），使用者重新載入後就會拿到新值。這一條不用額外做，既有流程已經擋得住。

會碰到的 B 類：
- **B1**：報價表單上**看得到、改得到**自訂欄位，需要在表單加掛載點。
- **B3**：報價原本的存檔路徑要不要也驗證 `cf_*`。

### 5.3 樣板版本化與凍結

- **表結構前例**：兩表制，`<x>_templates` 管穩定的 id，`<x>_template_versions` 管歷史；每次編輯新增一列，不覆蓋（`db.py:5170-5180` 傳票、`db.py:5041` 獎金）。
- **凍結前例**：`company_identity.snapshot_for` 在送出當下寫入 `data_json["locationIdentity"]`，之後不再重查（`company_identity.py:163-186`）。
- **第一階段存法**：`platform.templates.<docType> = {currentVersion, versions:[{version, fields, output, createdAt, createdBy}]}`，只能 append。
- **單據上的凍結資訊**：`data_json.platformTemplate = {id, version, frozenAt, fields}`。舊單據永遠用自己的快照顯示。這也補上盤點提到的缺口：`FORM_VERSION` 只有顯示、沒有存下來（`quotation-form.html:2224`）。

**示範案例（凍結這一段）**：
- 在「送審當下」凍結，需要掛進報價的送審流程（屬於 B 類）。
- **替代做法（A 類）**：改在「平台端點寫入 `customFields` 的當下」同時寫入 `platformTemplate`。
- 這樣做語意上等同送審凍結，因為送審之後單據進入 `_LOCKED`（`quotations.py:1499`），平台端點也照這條規則拒絕寫入，所以最後一次寫入必定發生在送審之前。
- 結論：**不需要 B 類。**

### 5.4 簽核條件

- **命名草案**：`platform.approval_rules.<docType> = [{when:{field, op:"gt|gte|eq|in", value}, flowKey}]`。由上往下比對，第一條命中的生效；全部沒命中就回到 `resolve_active_flow_setting`（`tiered_approval.py:88`）。
- `flowKey` 指向一把 `system_settings` key，內容形狀和既有 flow 相同（`tiered_approval.py:296-324`），交給 `setting_to_active_tiers` 展開。**引擎本體不改。**
- `field` 只能用核心鍵的唯讀值（例如 `tot.total`）或 `cf_*`。
- **平台新建的單據類型**：直接引用引擎，屬於 A 類（加 doc type 屬於 A 類登記）。
- **既有單據**：流程是在各 router 的送審端點選的（例如 `case_extra_expenses.py:336`、`bonus.py:1171`）；報價單還另外保留一份自己的副本（`quotations.py:178`）。⇒ **要套條件就得改那幾行，屬於 B 類（B4）。**

**示範案例（簽核這一段）**：這條示範主線**不需要簽核條件**，所以不碰。如果要「依 `cf_*` 值決定報價的簽核關卡」，那就是 B4。

### 5.5 輸出樣板

- **樣板語言**：沿用 `voucher_template.py` 的模式：
  - 封閉的佔位符清單（:37）。
  - 每個佔位符都要有取值來源，而且兩個方向都守（`PLACEHOLDER_RESOLVERS` :56）。
  - 單層大括號語法（:78）。
  - **儲存樣板時**就驗證（:100、:112）。
  - 每種 doc type 各有一份佔位符清單，`cf_*` 由欄位定義自動加入。
- **渲染**：
  - 平台層自己組 HTML，但必須走 `run_edge_pdf`（`helpers/startup.py:75`，會自動取用 `EDGE_PDF_SEMAPHORE`），並檢查 0 byte。
  - 抬頭用 `apply_snapshot(location_identity(...), payload)`（`company_identity.py:82`、:220）。
- **一份定義驅動所有出口**：表單、預覽、PDF 都讀 §5.3 的同一份凍結定義。
- **範圍**：依盤點 R1，只做單據 PDF，不做多段式報表。

**示範案例（PDF 印出這一段）**：
- 正式報價 PDF 由 `_build_quote_html`（`pdf_gen.py:96`）的 f-string 產生，有兩個呼叫點（:478、:973）。要讓 `cf_site_contact` 印在**正式報價單上**，就必須改這支函式，屬於 **B2**。
- **替代做法（A 類）**：平台層另外產一張「自訂欄位附頁」PDF。代價是變成兩個檔案。
  - 要合併成一個檔案需要 PDF 函式庫，而 `requirements.txt` 裡沒有（〈我的環境不是產品的環境〉）。
- ⇒ 這一段**一定要先問使用者**：附頁可不可以接受。

**示範主線的總結**：

| 段落 | 只走 A 類能做到的 | 會碰到的 B 類 |
|---|---|---|
| 定義 | 全部 | — |
| 存檔 | 全部（走平台端點） | B3（原存檔路徑是否也驗證） |
| 讀回 | 資料層全部 | B1（表單上看得到） |
| 凍結 | 全部（寫入時凍結） | — |
| PDF | 附頁 | B2（印在正式報價單上） |

⇒ **只用 A 類，就可以做出一條「平台頁面編輯 → 存 → 讀回 → 附頁 PDF」的端到端細線。** 使用者要的「在報價表單上、印在正式 PDF 上」取決於 B1、B2 的裁示。

### 5.6 接點逐一標類

| # | 接點 | 平台層的用法 | 類別 |
|---|---|---|---|
| 1 | `run_edge_pdf`（`startup.py:75`） | 直接 import | **A**（純引用） |
| 2 | `_identity_head/_foot`（`pdf_gen.py:522/538`，私有函式） | 直接 import 私有函式 | **A**（純引用，會綁住私有 API）；搬到 helper＝B9 |
| 3 | `location_identity/snapshot_for/apply_snapshot` | 直接用 | **A** |
| 4 | `tiered_approval` 的函式；新增 doc type | 平台新單據直接用；doc type 加進 `:54`/`:64`/`approval-settings.html:448` | **A** |
| 5 | 既有單據套用簽核條件 | 改各 router 送審的那一行 | **B4** |
| 6 | 簽核佇列（`quotations.py:3784`，每種單據一段 SQL） | 加一段 | **B5** |
| 7 | `_notify`／`_audit`（`helpers/audit.py:11/92`） | 直接用 | **A** |
| 8 | email 事件 | `EVENT_GROUPS`（`notification_prefs.py:17`）加一列 | **A** |
| 9 | `next_entity_code`（`db.py:5486`） | 直接用，自己接住 IntegrityError | **A** |
| 10 | `save_document_files`（`uploads.py:41`） | 呼叫前平台層先驗 `doc_no`；在原函式補檢查＝B8 | **A** |
| 11 | `_get_setting/_set_setting` | 定義登錄的存取層 | **A** |
| 12 | 模組 key 單一來源 | 平台自己的 key 照 A 類三處登記；要既有 8 處改讀單一來源＝B7 | **A** |
| 13 | 選單 | 靜態登記一個「自訂功能」入口＝A；讓使用者自建頁面動態併進主選單＝B6 | **A**／B6 |
| 14 | 報價表單掛載點；正式 PDF hook | 改 `quotation-form.html`；改 `_build_quote_html` | **B1**／**B2** |
| 15 | 平台 router 掛載 | `main.py` 加一列 | **A** |
| 16 | caseRecord 存取層 | 新增唯讀 helper＝A；要既有 5 處改走它＝B10 | **A** |
| 17 | 引用關係（§5.7） | 新表 `pf_references`＋來源解析登錄 | **A**（新表）；改傳票既有欄位的語意＝JV36 自己的範圍，不屬於平台 |

### 5.7 引用關係接點：以 JV36 為例

**JV36 是什麼**（`docs/windows/SPEC-JV28-ATTACHMENT-PREVIEW.md` 檔尾）：傳票某一行的摘要選到一個來源 XXX（案件或支出項）之後，
- 該行下方列出 XXX 的已上傳檔案；
- **勾選才複製**成傳票附件；
- 該行要記住來源，重新開啟時再帶出來。

這是「單據引用另一張單據的附件」的第一個實例。

**既有機制**（讀碼確認）：

| 元件 | 位置 | 可否給平台共用 |
|---|---|---|
| 來源白名單，9 種 | `helpers/voucher_attachments.py:54-64` | 可以直接引用 |
| 明示排除的來源（完工單、出貨單、業務日誌、待核准的暫存附件） | `:74` | 可以直接引用；排除理由（不可以讓未核准的東西變成憑證）要一併沿用 |
| 來源解析 `source_files(conn, source_type, doc_no)` | `:119`；遇到未知類型會 raise 400，不回空清單（:172） | **可以直接呼叫**（A，純引用） |
| 「先全部驗完再複製」的規則 `resolve_picks` | `:198` | 規則沿用 |
| 帶入採「複製」而非「引用」，檔案路徑用 id 不用單號 | `:6-15`、`copy_into` :250 | 規則沿用 |
| 附件列上的決定性來源三欄 `source_type/source_doc_no/source_file_id`，都是 **TEXT** | `db.py:4843-4845` | 形狀可以沿用 |
| 行層級來源 `voucher_lines.source_type/source_id`，其中 `source_id` 是 **INTEGER** | `db.py:5304-5305` | ⚠ 見下方 |

⚠ **型別衝突（要轉給 JV36 的施工者）**：
- `voucher_lines.source_id` 是 INTEGER，而且**三個 INSERT 都沒有寫入它**（`routers/vouchers.py:280`、:973、:1138），是零寫入點。
- JV36 要記住的來源有兩種鍵：
  - 「案件」的鍵是單號（TEXT）。
  - 收款項目、叫料這類來源的鍵是「案件編號_序號」組合鍵（`voucher_attachments.py:84` `_quote_and_index`）。
- **這兩種都放不進 INTEGER 欄位。** 能放進去的只有以整數主鍵為鍵的來源，例如額外支出、派工。
- 這是傳票模組自己的施工決定，不屬於平台層。但如果 JV36 用 `source_id` 硬存，日後平台要讀的時候就得再轉換一次。

**評估結論：可以作為平台「引用關係」接點的規格來源，但不直接共用傳票的資料表。**

建議平台層的形狀：
- **來源登錄**：平台自己的 `SOURCE_RESOLVERS`（新檔，A 類）。
  - 既有 9 種直接委派給 `voucher_attachments.source_files`，屬於 A 類純引用，不改傳票碼。
  - 平台自建的單據類型，在平台檔案裡自己登記解析函式。
  - 遇到未知類型要照 :172 raise，不可以回空清單。
- **引用記錄**：新表 `pf_references(from_type, from_id TEXT, from_line, source_type, source_key TEXT, source_file_id, mode 'copy'|'ref', snapshot_json, created_at, created_by)`。
  - 做法是新 migration 建新表，並登記展示分類與備份，都屬於 A 類。
  - **鍵一律用 TEXT**，才裝得下單號與組合鍵。
- **帶入策略**：預設「複製」，沿用 `voucher_attachments.py:6-15` 的理由。「引用」只給非憑證用途。

**建議轉達 hichan-61（JV36）**：行層級來源請用 TEXT 語意的 `source_type`＋`source_key`，例如沿用附件列 `source_doc_no` 的格式。否則日後平台讀取傳票的引用時，需要多一層轉換。

### 5.8 待問清單（B 類）

| # | 點 | 影響誰 | 替代做法（A 類） | 要問使用者的一句話 |
|---|---|---|---|---|
| **B1** | 報價表單加 `customFields` 掛載點（`quotation-form.html`，Alpine 手寫） | 所有報價表單使用者；這支檔目前是 hichan-8d 的範圍（commit `218d810` 訊息） | 平台獨立頁「報價自訂欄位」，用平台端點編輯。代價是要切換頁面 | 「自訂欄位要直接出現在報價表單裡（要改表單），還是先在另一個獨立頁面編輯？」 |
| **B2** | 正式報價 PDF 印出自訂欄位（`pdf_gen.py:96`，呼叫點 :478、:973） | 所有報價 PDF | 另產一張「自訂欄位附頁」PDF，變成兩個檔 | 「自訂欄位要印在正式報價單 PDF 上（要改 PDF 版面程式），還是先另出一張附頁？」 |
| **B3** | 報價原存檔路徑也驗證 `cf_*`（`quotations.py:1401` 的 PUT） | 所有報價存檔 | 只在平台端點驗證；原路徑照原樣存回 | 「自訂欄位的格式檢查只做在平台頁面，報價單原本的存檔流程不另外檢查，可以嗎？」 |
| **B4** | 既有單據依條件選簽核關卡（各 router 送審那一行；報價另有一份副本 `quotations.py:178`） | 該單據的所有送審 | 條件簽核只給平台新建的單據類型 | 「依金額或欄位決定簽核關卡，第一版只給新建的自訂單據，還是既有的報價單也要？」 |
| **B5** | 簽核佇列加入平台單據（`quotations.py:3784`；受 `test_queue_and_feed_scoping:158` 約束） | 簽核佇列的所有使用者 | 平台單據在自己的頁面列出待簽項目 | 「自訂單據的待簽項目要併進現有的簽核佇列（要改佇列程式），還是先放在自己的頁面？」 |
| **B6** | 使用者自建頁面動態併進主選單（在 `sidebar.js:613` `_navGroups` 渲染前合併；9 支 regex 測試要改寫） | 全站選單 | 靜態登記一個「自訂功能」入口，點進去是平台清單頁 | 「使用者自建的頁面要直接出現在主選單（要改選單程式），還是先集中在一個『自訂功能』入口底下？」 |
| **B7** | 模組 key 收斂成單一來源，既有 8 處改讀它（§1.1） | 全部權限檢查；`test_module_keys_consistency` 要改寫 | 平台 key 照 A 類在三處登記，既有的不動 | 「權限模組清單要整併成一份（動到權限程式），還是維持現狀、新模組照舊登記？」 |
| **B8** | `save_document_files` 補 `doc_no` 穿越檢查（`uploads.py:63`；是否能被利用尚未確認，見 N8） | 5 個上傳呼叫點 | 平台層呼叫前自己檢查 | 「上傳路徑的防護要在共用函式補一次（改既有程式），還是只在新功能自己檢查？」 |
| B9 | `_identity_head/_foot` 搬到 helper | pdf_gen 的 9 支 builder | 直接 import 私有函式 | 現在不問：示範主線用不到 |
| B10 | 既有的 caseRecord 讀取改走共用存取層（§3.4 的 5 處以上） | 出納、報表、獎金、首頁 | 平台只用新增的唯讀 helper | 現在不問：示範主線用不到 |

**建議優先問**：B2、B1（決定示範主線的最終樣子），其次 B5、B6（決定平台單據怎麼被看見）。B3、B7、B8 可以等到細線站穩之後。

---

## 我沒查什麼

- **行號時效**：本版以 `1eaa5d3` 為準。
  - §1-§4 裡位於兩版之間有變動的檔案，用 difflib 做行號對照後改寫。對照結果是「該行內容相同」時就直接換號，**沒有逐行重讀語意**；有變動的內容（字級修正、`.modal-box`、`payslips.html:34`）才重讀過。
  - 沒變動的檔案沿用第一版的行號。
- **沒有跑任何測試、沒有啟動伺服器。**
  - 「會紅在哪」是讀測試原始碼推出來的。
  - §5.2「存檔與讀回原樣保留 `customFields`」是讀碼推論（`Object.assign` 加上 `data: dict`），**沒有實際存一次、讀回一次**。另外，前端還有 `Object.assign(this.q, t)`（`quotation-form.html:3788`，載入範本）等其他合併點，它們會不會帶入或清掉 `customFields`，沒有逐一確認。
- **第一版的抽查範圍**：由 6 個唯讀 agent 蒐集，我抽查約 40 個行號，1 處有錯並已更正。本版沒有再派 agent，§5 的新引用都是我自己讀的。
- **§5.7**：
  - JV36 目前的實作進度（hichan-61 的工作樹 dirty 檔）沒有看，只以 HEAD 上的 schema 與規格為準。
  - `voucher_lines.source_id` 的「零寫入點」只查了 `routers/vouchers.py` 的三個 INSERT，沒有掃其他檔案。
- **§5.0 的判定規則表**是本文提出的，不是使用者裁示。使用者的裁示只有「附加登記允許、改行為逐點問」這一句。
- **沿用第一版、仍未查的項目**：
  - 206 個測試檔中，只 grep 了掃描型守門。
  - vh 處數不一致：commit `218d810` 寫 49 檔 103 處，第一版 agent grep 出 53 檔 134 處。
  - account-items 的 modal 在深色模式下是否跑版。
  - bonus 不在簽核設定頁是否刻意。
  - `next_entity_code` 撞號時是否回 500。
  - 完工單與薪資單的 PDF 歸檔路徑。
  - 其他單據表單的欄位寫死程度、`json_extract` 效能、手機版版型。
  - `system_settings` 存定義時的 JSON 大小與同時編輯。
