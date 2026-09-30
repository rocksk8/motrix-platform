# L0／L1 底層 更新紀錄

> 底層穩定契約（MODULE-GUIDE §2）：同一主版號內只准新增。版本＝`core.registry.CORE_VERSION`。

## 1.73 — 2026-09-30（W1 建構器第三輪 S1～S3，暫用號；wip/w1-builder3；1.72 已被 wip/sec-p0 取用）
- L1（新增）：`helpers.custom_fields.EXT_TYPES／MODULE_TYPES／OPTION_TYPES`——自訂模組新欄位型別 `textarea`（多行文字）、`radio`（單選）、`checkboxes`（複選）、`multiselect`（下拉複選）、`daterange`（日期時間區間 `{from,to}`）；`validate_definition(…, types=)` 可傳型別集合（預設仍是 P4 的 5 種，內建單據的 customFields 不受影響）；`_coerce` 支援新型別與屬性 `maxLength／min／max／withTime／allowOther／minSelect／maxSelect`（只增）
- L1（新增）：`helpers.custom_modules`——欄位型別 `table`（明細表：逐列逐欄驗證、列內公式、列數限制、索引只記列數）、`clean_table`、`table_columns`、`FINANCE_KINDS`、欄位屬性 `finance:{kind,dateField,cashDateField,caseField}` 與模組層 `finance.postStates` 的發布驗證（金流性質，使用者 2026-09-30 規則；提供者與報表整合在後續段）
- L1（新增）：`helpers.formula`——函式 `total(表,"欄")`、`avg(表,"欄")`、`count(表)`（明細表加總／平均／列數，空值不算 0）、`round_half_up(x[,n])`（與既有 `round` 同為四捨五入的明確別名；`round` 語意不變）；`check(expr, fields, tables=)` 可驗明細表引用
- L1（新增）：core migration v3（建構器 S1～S5 底層，只增）——`ui_definitions` 加 `submitted_by／submitted_at／decision_json`（定義送審／退回）；`custom_records` 加 `base_no／rev／supersedes_id` 與表 `custom_record_revisions`（單據 -R 修訂）；表 `custom_record_finance_outbox`（金流事件，`dedupe_key` 唯一，供 W4 總帳）。明細表值、欄位／選單可見設定、選單群組都在定義／單據 JSON 內，不另建表
- L1（新增）：`helpers.custom_builder_support`——`mask_for／can_see_field／can_see_menu／access_problems／leaking_formulas`（欄位 `access.visibleTo`、選單 `menu.visibleTo` 的後端強制與發布驗證，公式引用受限欄位而可見範圍較大＝洩漏，發布拒絕）；`emit_finance_event／pending_finance_events／mark_finance_processed`（金流 outbox，`EVENT_FINANCE_POSTED／REVERSED`）；`create_revision`（單據 -R 修訂）。`custom_modules.visible_to` 依 `menu.visibleTo` 過濾（沒設＝不變）；`validate_module` 加可見設定驗證
- L1（新增）：組織元件（S2）——`helpers.custom_modules.ref_labels(conn, body, data)`（單據參照欄的顯示名稱）；`ref` 欄位屬性 `multiple`（複選，值＝去重代號清單，逐一驗證存在）；參照對象 `departments`；元件群組 `org` 與元件 `user／users／dept／depts`（都是 `ref` 的預設屬性組）；`get_record` 回傳多 `refLabels`（只增）
- L1（新增）：`helpers.custom_builder_support`（S3）——`hidden_keys／mask_record／mask_records／mask_compute／keep_hidden_values／render_output_for`（欄位可見的後端強制：讀取、列表、寫入回應、即時計算、輸出都拿掉看不到的欄位；受限使用者存檔不會清掉看不到的欄位）；`access_problems` 加「必填欄位不可設成部分人才看得到」。`routers.custom_records` 全部單據端點改走這些函式；`VISIBLE_ROLES`（可見設定可選的角色，同基本角色；目錄 `roles`）；`access_problems` 的問題路徑改用 `fields[i]`（建構器標卡片）並檢查角色在清單內
- L1（新增）：附件欄（S2）——core migration v4 `custom_record_files`（先傳後綁單；T1，實體檔在 `uploads/custom_records/<模組>/`）；`helpers/custom_files`（`accepted_exts／clean_ids／check_files／bind_files／remove_files／remove_staged／purge_stale_staged／register_staged／file_meta／files_of_field／view_names／CustomFilesAccess`，`uploads.path_access` 提供者 `custom_files` 認領資料夾 `custom_records`，IP-104）；欄位型別 `file`／`image`（屬性 `accept`＝白名單子集、`maxFiles`）；端點 `POST /api/custom/{key}/files/{欄位}`、`DELETE /api/custom/{key}/files/{id}`；`get_record` 多 `fileMeta`；`mask_record` 一併拿掉看不到欄位的 `fileMeta`；`db.py`／`archive.py` 登記 v3／v4 新表（demo 重置清單、每日匯出）
- L1（新增）：欄位「改得到」（S3 補完）——`helpers.custom_builder_support.can_edit_field／guard_writes`；欄位屬性 `access.editableTo`（形狀同 `visibleTo`；改得到蘊含看得到；看得到但改不到的欄位，送來的值與既有值不同 ⇒ 建立／修改端點回 403 並列出欄位）；`menu.visibleTo` 也擋直接打單據端點（`routers.custom_records._can_use` ⇒ 404，不只藏選單）；`access_problems` 兩個鍵都驗，必填欄位不可設成部分人看得到或改得到
- L1（新增）：金流串接（S2.5）——`helpers/custom_finance`（`post_states／on_transition／expense_entries／income_items／undated_counts／dup_skipped／case_finance／EVENT_POSTED／EVENT_REVERSED`）；入帳狀態進入／離開時在同一交易寫 `custom_record_finance_outbox`（`custom_module._enter_state` 呼叫）；IP-9 `expense.entries` 多提供者 `custom_module`（entries 多選填鍵 `cashDate／cashAmount`，營運報表現金口徑改用）；營運報表收入併入自訂模組收入（`reports._custom_income`）與「待補登」說明；端點 `GET /api/custom-modules/finance/case/{案件單號}`、`GET /api/custom-modules/finance/summary`；`case_finance` 回傳 `income.skippedTotal`（案件是內建案件時收入行標 `skipped`）；端點 `GET /api/custom-modules/finance/case/{案件單號}` 需查看財務金額權限與案件單據讀取權限；案件財務總覽（M01）與成本精算頁併入自訂模組支出

## 1.72 — 2026-09-30（暫用，列車取號；wip/sec-p0 安全修正 P0）
- L1（新增）：`helpers.uploads.PATH_ACCESS`（＝`"uploads.path_access"`，IP-104）、`canonical_upload_path(raw)`（上傳相對路徑正規化：絕對路徑、`..`、`.`、反斜線、冒號、NUL、空段、只有一段、realpath 與字面不同〔連結／junction〕或跑出 UPLOADS_ROOT ⇒ None）、`upload_owner(rel)`（⇒ `(資料夾, 其餘各段)`，去掉 `_demo_uploads/`、`_demo_projects/`→`projects`）、`upload_readable(conn, rel, user)`（依資料夾找 `uploads.path_access` 提供者、用擁有單據的規則判斷；沒人認領 ⇒ False；提供者例外 ⇒ False＋ERROR）
- L1（行為，安全）：`GET /api/photo-token` 原本對任何路徑簽發（只要求登入）、`GET /api/uploads/{path}` 帶 Authorization 那條也只要求登入 ⇒ 兩者改為 `canonical_upload_path`（不合法 403）＋`upload_readable`，或帶 `type`／`id`（簽核佇列情境）時詳情守門放行且詳情列出該路徑；其餘 404「檔案不存在」（與查無同一句）。簽章改綁正規路徑（`a/b/c`）；已發出的舊簽章（1 小時）部署後失效、重新載入即可
- L1（新增，私有）：`routers/approval_queue._open_detail`（詳情端點的守門抽出，行為不變）、`detail_file_paths`；`routers/system._WorkLogPhotoAccess`（`projects/` 工作日誌照片：`work_log`／`case_manage` 模組，或日誌掛的案件 `case_documents_readable`）
- 頁面：`approval-queue.html` 換簽章時帶目前詳情的 (type, id)
- 〔稽核 W2 補修〕L1（新增端點）：`POST /api/photo-token/batch {paths[], type?, id?}` ⇒ `{tokens:{路徑:簽章}, denied:[路徑], ttl}`（上限 200，超過 400）。規則同單張端點，但簽核佇列情境**一次請求最多跑一次**詳情守門（只有路徑單看擁有單據讀不到時才跑）⇒ 被拒時 audit 一筆。approval-queue 縮圖改用批次（S1：原本 N 張圖＝N 次詳情提供者＋N 筆 audit；20 張量測 589 ms → 58 ms，詳情守門 20 次 → 1 次）；點開單一檔案仍用單張端點（相容保留）。守門 `tests/platform/test_upload_folders_claimed_2026_09_30.py`（S2：每個上傳寫入資料夾都要被提供者認領或明列排除）
- 已知限制：`routers/system.py` 在 import 時以 `registry.provide` 登記 L1 工作日誌提供者（L1 沒有 ModuleSpec；同 `helpers/custom_modules.py` 的既有作法；「不在 import 時登記」的守門只管 M01）
- 已知限制（稽核 S6，不在本包修）：`routers/system._WorkLogPhotoAccess.readable` 每張照片對 `work_logs` 做 `photos LIKE '%…%'` 全表掃描（日誌上千筆＋一次 20～30 張圖＝N 次掃描）；日後改以路徑中的 `worklog_<id>` 直接 `WHERE id=?` 定位

## 1.71 — 2026-09-30（暫用，列車取號；wip/w2-report-cash）
- L1（新增）：`helpers.tax_calc.receipt_amounts(receivable, actual, fee)` ⇒ `(bank, gross, fee)`，經 `helpers` 匯出：已收款項的銀行入帳／收入(含稅)／手續費單一定義（實收＝銀行入帳、收入＝入帳＋手續費、淨額＝入帳不再減手續費）。`summarize_payment_items` 的 `netAmount`／`netCollected` 改用它。
- L1（新增）：`helpers.recognition_basis.DEFAULT_BASIS`（營運報表預設口徑＝`cash`）；`normalize_basis(None)` 回它（原為 accrual）。

## （不升版號：介面不變）— 2026-09-29（wip/cloud-startup-timing：T21-1 啟動逐步耗時）
- L0（行為，私有）：`main.py` 啟動路徑逐段記耗時——每段一行 INFO `STARTUP_STEP <名稱> <毫秒>ms`（距上一段結束），最後一行 `STARTUP_TOTAL <毫秒>ms steps=<段數>`（距 main.py 開始執行；不含 Python／uvicorn 本身載入）。29 段：import_core、import_routers、load_modules、build_info、app_cors、middleware_setup、require_db、init_db_main、init_db_demo、fail_incomplete_modules、integrity_check、company_setup、init_default_admin、init_demo_account、flag_weak_passwords、init_unlock_passwords、cleanup_sessions、schedulers（整個排程閘門區塊，含 GEO 預熱排程）、geo_notice、prune_login_locks、init_rate_limiting、sync_module_versions、include_routers、page_map、mount_modules、module_schedulers、module_states_file、startup_notices、page_and_static_routes。私有 `_startup_step`／`_startup_total`：記錄出錯一律吞掉；`logging.basicConfig` 之前的段先暫存、之後一起印。啟動行為、順序、例外處理不變；排程閘門區塊內部不動（test_geocode_warm_async 逐字執行它）。起因：正式機第二十一班啟動到健檢 14 秒（CORS 行 → GEO 行 11.2 秒）分不出是哪一段。守門 `tests/platform/test_startup_timing_2026_09_29.py`
## 1.70 — 2026-09-29 14:27（雲端暫用，列車取號；wip/cloud-rowaccess-empty-name：舊計畫「顯示名稱為空的使用者，看得到業務名稱為空的舊案件」）
- L1（修正）：`helpers.row_access` 的舊資料名稱比對（`legacy_name_col`，案件＝`sales_person`）——使用者顯示名稱為空字串／None 一律不算相符（`visible` 與 `filter_sql` 同一條：SQL 不再產生該項）。原本空對空相等 ⇒ 顯示名稱空的非 admin 使用者看得到所有 `sales_person_id` 為 NULL、`sales_person` 為空的舊案件。其餘規則（本人 id、協作者、建立者、admin／cashier 直通、顯示名稱有值時的名稱比對）不變。公開介面不變。守門 `tests/test_row_access_empty_name_2026_09_29.py`；`tests/test_row_access_2026_09_25.py` 與凍結舊實作的比對扣掉這一格（`_minus_intended_change_2026_09_29f`）。〔補 D 稽核 RA-M1：扣格只扣「只靠空對空才可見」的列，協作者／直通可見的列不扣；資料加入空名稱使用者當協作者的列〕
## 1.69 — 2026-09-29（暫用，列車取號；wip/payslip-void-signed）
- L1（新增）：`helpers.tax_calc.norm_ymd`（款項日期正規化為 YYYY-MM-DD：接受斜線、點、單位數月日、民國年、「年月日」；讀不懂的原樣截 10 碼、不假造）；`helpers` 匯出 `norm_ymd`。收入報表歸月與儲存端共用。

## 1.68 — 2026-09-28（E 暫用，列車取號；wip/e-company-gate-impl 第一段：本公司資料設定閘門的正式機段）〔core_bump：暫用 1.66 → 1.65〕〔core_bump：暫用 1.65 → 1.67〕〔core_bump：暫用 1.67 → 1.68〕
- L1（新增）：`helpers.company_setup`——判定（`status`：確認紀錄＋安裝識別＋必要欄位雜湊＋開發者指紋需簽章確認檔）、`confirm`、`backfill_once`（每庫一次、不丟例外）、`startup_install_check`（識別檔重建且已有紀錄 ⇒ ERROR＋告警）、暫時放行（`grace_state`、`observe`：有效期＝min(until, first_seen＋72h)）、統編檢查碼 `ubn_valid`、`alert`（每日一次）。設計 docs/platform/COMPANY-SETUP-GATE.md
- L1（新增）：`helpers.company_identity.identity_from_profile(profile, location_id)`（`location_identity` 的純函式版；行為不變）
- L1（新增）：`core.paths.INSTALL_IDENTITY_FILE`／`COMPANY_CONFIRMATION_FILE`／`COMPANY_SETUP_GRACE_FILE`，並登記進 `core.upgrade.CONFIG_FILES`（CG2-M1）；`verify_package` 拒收、`.gitignore`
- 工具：`backend/tools/company_setup_cli.py`（ensure-install-id／preflight／status／grace；UTF-8 輸出）；`apply_update.ps1` 2026-09-28h：停服前預檢（`refused_company_setup`）、套用後本機檢查未通過 ⇒ 自動回滾（`company_setup_rolled_back`，`-SkipAutoRollback` 不適用），無任何略過參數；`deploy_dashboard._STATUS_FAILED` 加兩個出口
- 〔第二段〕L1（新增）：`company_setup.gate`（中介層與輸出端共用、行程內快取、不丟例外：判定失敗 ⇒ `GATE_UNDETERMINED`，Q7＝C）、`compile_allowed`／`is_allowed`（白名單以 Starlette `compile_path` 比對 (方法, 路由樣板)）、`reset_cache` 與常數；`main.auth_middleware`：未設定 ⇒ 白名單外 /api 一律 428 `company_setup_required`；判定失敗／暫時放行 ⇒ 放行＋標頭 `X-Motrix-Company-Setup`；`GET /api/settings/company-setup/status`；`PUT /api/settings/company-profile` 帶 `confirmIdentity` 才寫確認紀錄（先驗後寫）；頁面 `company-setup-required.html`、設定頁確認卡、`notif.js` 導頁與橫幅；demo 帳號暫不擋（第三段種虛構示範公司）
- 〔第三段〕L1（新增）：`company_setup.CompanySetupRequired`（HTTPException 428；`main.py` 專屬 handler 回與中介層同形 JSON）、`require`、demo（`DEMO_INSTALL`／`DEMO_PROFILE`／`DEMO_WATERMARK`／`seed_demo`；`status(demo=)`、`gate(demo=)` demo 與正式分開判定與快取）、`observe_expiry`（簽章檔剩 ≤ 30 天、放行剩 ≤ 6 小時告警；確認檔有效期 365 天，2026-09-29 由 30 天改回）、判定失敗 60 秒快取（`ERROR_CACHE_SECONDS`，CG5-S2）與告警行程內節流；`company_identity.require_for_output(kind, ident)`／`identity_for_output`／`PAYMENT_BANK_FIELDS`／`CODE_BANK_REQUIRED`。**行為變更**：`company_name`／`company_heading`／`contact_line`／`name_pair`／`footer_line` 與 pdf_gen `_identity_head／_identity_foot／_identity_foot_short`、勞報單視圖一進來先問第二道（未設定／判定失敗 ⇒ 428，CG5-M1）；請款單產生另驗匯款三欄（428 `company_bank_required`）；傳票 PDF 與個資告知的公司名改走 company_identity；月報排程被擋 ⇒ 不寄、告警、月份不前進；demo 登入種虛構示範公司、單據加浮水印，中介層不再豁免 demo；`/api/platform/menu` 回 `companySetup`，未設定時只留設定頁入口；已確認後一般存檔改必要欄位 ⇒ 409 `company_setup_reconfirm`（CG5-S1）；`core.upgrade._is_our_install` 只認統編（刪名稱片段，§2-④）
- 〔第三段補（D E4S3-S1／S2）〕L1（新增）：`company_setup.RESERVED_DEMO_UBN`、`payment_bank_missing(profile)`；`required_problems(profile, demo=False)` 非 demo 庫拒收 00000000；`company_setup_cli` 輸出 `payment_bank_missing`；`apply_update.ps1` 2026-09-28j 預檢後印 `::NOTE:: company_bank…`（只報不擋）
- 〔第三段補（§6.7 登記兩步）〕L1（新增）：`company_setup.verified_doc(raw)`（確認檔驗章＋用途；`signed_file_state` 改用它，行為不變）；工具：`company_setup_cli.py sign`（開發機：私鑰以路徑傳入、只簽開發者身分、簽完自驗、不覆蓋；`--days` 預設與上限 365）；`--permanent`（開發者本公司正式機永久確認檔：不寫 expires、只准開發者身分；使用者 2026-09-29「正式機為永久授權」）；L1（新增）`company_setup.is_permanent_doc`，`signed_file_state` 接受永久確認檔（只看簽發日）、`observe_expiry` 不提醒
- 啟動：`main.py` 啟動時做安裝識別檢查＋一次性 backfill（閘門本身尚未擋任何 API；第二段才接中介層）；信件類型 `company_setup_alert`（系統技術，超級管理員）

## 1.67 — 2026-09-28（A 暫用，列車取號；wip/a-api-docs-off：主持裁示）〔core_bump：暫用 1.65 → 1.67〕
- L0（新增）：`main.API_DOCS_ENV`（"MOTRIX_API_DOCS"）、`main._docs_kwargs(environ)`——API 文件頁（/openapi.json、/docs、/docs/oauth2-redirect、/redoc）預設不註冊，只有旗標恰為 "1" 才開；程式內 `app.openapi()` 不受影響

## 1.66 — 2026-09-28（E 暫用，列車取號；wip/e-lodging-impl：第十八班全域守門）
- L1（新增）：`db.demo_module_tables()`——展示重置時，已載入模組 `module.json` 宣告的表依分類處理（T1／T2 清空、T3 保留；規則同每日 JSON 備份），L1 靜態清單不寫 L2 表名；`test_demo_reset` 的分類窮盡題把模組宣告算進去
- 資料：權限目錄釘子題（test_module_registry）與 Alpine 頁面母體（test_alpine_double_init 50→51）因附近旅宿（使用者裁示 09888e19）更新

## 1.65 — 2026-09-28（E 暫用，列車取號；wip/e-lodging-impl：附近旅宿 L1 接點）
- L1（新增）：`helpers.geo.map_request_scope(page_basemap, missing="osm")`＋常數 `MAP_SCOPE_MISSING_SETTING`／`MAP_SCOPE_MISSING_OSM`——地圖頁請求的 Google 範圍判定（頁面底圖只准收窄設定；D 稽核 LG2-M1）。`/api/map/points` 改用它（`missing="setting"`）：None／google／osm 行為不變；**不認得的值（含空字串 `basemap=`）原本可用 Google，現在視同 osm**（收窄，LG3-O1）。守門 `tests/test_map_request_scope_2026_09_28.py`＋既有 GB-M2 題
- L1（新增）：`archive._daily_backup_tables()` 併入**已載入**模組 `module.json` `data.tables` 宣告 T1 的表（鍵 `模組-<key>-<表>`，常數 `archive.MODULE_BACKUP_PREFIX`）；模組未載入＝不列（不誤報 daily_partial）；非法表名、T2 不列並記 ERROR；已在寫死清單的不重複（主持裁示 2026-09-28）。〔補 D 稽核 E3-S1：略過的 T2 寫進彙總檔固定欄位 `skipped_t2`（新增 `archive.module_backup_skipped_t2()`），ERROR 每輪一次〕守門 `tests/test_archive_module_declared_tables_2026_09_28.py`
- L1（資料）：權限目錄 `helpers.module_registry.MODULES` 新增 `lodging`（附近旅宿，業務）
- L1（新增）：地圖覆蓋層串接點 IP-101 `map.overlay`——`helpers.map_overlays`（`declared_overlays`／`script_path`／`OVERLAY_KEY_RE`／`SCRIPT_NAME_RE`／`URL_PREFIX`）、`GET /api/map/overlays`、`main.map_overlay_script`（`/map-overlays/<模組>/<檔名>`）、前端契約 `static/map-overlay.js`（`MotrixMapOverlay`）；`map.html`／`map-google.js` 接生命週期。守門 `tests/test_map_overlay_contract_2026_09_28.py`、`tests/test_e2e_map_overlay_contract_2026_09_28.py`

## 1.64 — 2026-09-28（A 暫用，列車取號；wip/a-gm-raw：正式機 Google 底圖標點消失、取點延遲）
- L1（新增）：`helpers.geo.cache_read_session()`——範圍內 `_cache_get`／`_cache_get_many` 共用一條讀取連線（寫入照舊自己開）；`/api/map/points` 整次取點在範圍內（正式機約 400 地址，原本每個地址開一次連線 ⇒ 2～7 秒；兩種底圖成本相同）
- 頁面：`static/map-google.js` 的 Google 物件建立後標 `__v_skip`、傳給 Google 的 map 經 `Alpine.raw`（Alpine 讀回 Proxy ⇒ 真 Google 不認 map ⇒ 標點全部不見）；標記點擊改 `gmpClickable`＋`addEventListener('gmp-click')`；`map.html` 的 `x-text` 在 `info` 為 null 時不丟錯

## （不升版號：介面不變）— 2026-09-28（B，wip/b-module-delivery-2：B55 單一模組更新包 S2）
- L1（行為，私有）：`core.loader._write_module_states(path)`——啟動完成時寫 `logs/module_states.json`（`{pid, started_at, modules:[{key, state, version, reason}]}`，先寫 .tmp 再改名；寫失敗只記 WARNING）；~~`main.py` 在排程閘門內、`start_schedulers()` 之後呼叫（測試 session 不寫）~~〔更正（S3，稽核 D DB5-S1）：**不綁排程閘門**，`mount_modules()` 之後、以「pytest 不在 sys.modules」為條件呼叫；檔內多記 `schedulers_disabled`（以 DISABLE_SCHEDULERS 啟動的演練也有狀態檔，健檢說得出原因）〕。給單模組更新的健檢讀（稽核 D DB-S4）。loader 的「模組 %s %s 已載入」「模組 %s 未載入：%s」兩行 log 字串列為契約（守門題）
- L1（行為）：`core.upgrade.CONFIG_FILES` 加 `backend/.deployed_modules.json`（單模組包的覆蓋紀錄，與 `.deployed_commit.json` 同類；稽核 D DB-O1）⇒ 完整包刪除計畫與 cleanup-snapshot 不碰它
- 守門 `tests/platform/test_module_states_file_2026_09_28.py`

## （不升版號：介面不變）— 2026-09-28（B，wip/b-warm-async：第十五班緊急修補 B54）
- L1（行為）：`helpers.geo.schedule_geocode_warm()` 改為**立即返回**：第一輪背景定位排進 daemon `threading.Timer`（私有常數 `_GEOCODE_WARM_FIRST_DELAY_SECONDS`＝30 秒）在背景執行緒跑，之後每輪結束（含丟例外）再排下一輪（私有 `_geocode_warm_tick`，重排維持 `finally`）。原本在呼叫當下同步跑第一輪 ⇒ `main.py` 模組層呼叫它時 `import main` 被整輪定位卡住（正式機套用 8b04d99d：333 筆待辦×Nominatim 每秒 1 次 ⇒ 83 秒內 port 666 沒在聽 ⇒ 自動回滾）。守門 `tests/test_geocode_warm_async_2026_09_28.py`

## 1.63 — 2026-09-28（A 暫用，列車取號；wip/a-google-basemap：Google SST §6.2）
- L1（新增）：`helpers.geo.without_google_content()`（contextvar 範圍：cached_only／locate_cached／_stage_allowed 跳過 Google 階與其快取，範圍內不記負快取）、`geo.google_content_blocked()`、`geo.google_basemap()`（地圖底圖是否為 Google；②(b) 前一律 False，切換時只改這一支）、`geo.has_google_coord(address)`
- L1 行為：`/api/map/points` 底圖非 Google ⇒ 點、據點、距離只用免費來源；只有 Google 座標的不畫，回 `googleOnlyHidden` 與 `basemap`；`locationsUnlocated[].googleOnly`。依據 Google Maps Platform SST §6.2 逐字「Customer must not use Google Maps Content from the Geocoding API in conjunction with a non-Google map」
- 頁面：`map.html` 說明未顯示的筆數與原因
- L1 行為（D 稽核 SST-M1）：公司資料存檔的據點自動定位——非 Google 底圖只用免費來源；Google 來源座標不寫進 `company_profile`（SST §6.3.1 30 天）；據點多存 `coord_source`／`coord_precision`（後端推導：新填或改過＝manual，原樣送回沿用）；`geo._locate_locations` 只把 manual（與沒有來源的既有資料）當人工座標
- L1 行為：背景預熱 `warm_geocode_cache()` 在非 Google 底圖時整輪只用免費來源
- L1（新增，②(b) 第一段）：`geo.GOOGLE_BROWSER_KEY_SETTING`、`geo.google_browser_key()`、`geo.USAGE_SKU_DYNAMIC_MAPS`（開圖次數近似 map load）；`geo.google_basemap()` 改為「有地圖（瀏覽器）金鑰」；`GET /api/map/config`（只回瀏覽器金鑰）；公司資料新欄位 `google_maps_browser_key`（遮蔽、不入稽核）；地圖頁專用 CSP
- L1（新增，②(b) 第二、三段）：`geo.GOOGLE_MAP_ID_SETTING`、`geo.google_map_id()`；`/api/map/config` 多回 `mapId`；公司資料新欄位 `google_maps_map_id`（不遮蔽）；頁面 `map.html`（先問 `/api/map/config`，google ⇒ `static/map-google.js` 轉接層＋AdvancedMarkerElement＋markerclusterer 2.6.2 vendor；同畫面不載 OSM；設定取不到不畫）、`company-profile-settings.html`（地圖金鑰與地圖 ID 兩欄、限制說明、Google 標誌不可換品牌）

## （不升版號：介面不變）— 2026-09-28（B，wip/b-geo-warm-fix：第十五班 地圖修正包 ①）
- L1（行為）：`helpers.geo`——①`_locate_nominatim`：`geocode()` 的「查無此地址」（對方回空陣列）不再進 errors ⇒ `locate_cached` 對真的查無會記負快取（原本任何 err 都進 errors ⇒ 負快取在真實路徑上從來沒寫過；既有題的替身回 None 不報錯所以一直綠）；②`_locate_google`：回應不是 JSON、或 status 是 REQUEST_DENIED／OVER_QUERY_LIMIT／INVALID_REQUEST／UNKNOWN_ERROR ⇒ 進 errors（原本回 None 不報錯 ⇒ 被當成查無、記負快取）；③`warm_geocode_cache`：查無（已記負快取）不算連續失敗、計數歸零，只有沒查成功才算；`warm_status()` 多回 `misses`、`failures`（回傳鍵新增，函式介面不變）。④（主持裁示）背景迴圈同一輪 Google 階連續連線失敗／被拒 3 次 ⇒ 本輪其餘地址跳過 Google（contextvar，只在背景迴圈的 context 內，結束還原），停止條件只看免費來源；`warm_status()` 多回 `googleSkipped`、`googleSkipReason`、`googleFailures`。⑤`quota_status()` 多回 `disabledByZero`（額度明填 0 ＝ 停用 Google 定位，不是本週期用完）。⑥（主持派工＋裁示）負快取分兩種：`_MISS_CACHE`＝任何查無（最寬）、`_MISS_CACHE_ALL`＝**Google 實際回了查無**；判斷時 Google 現在問得到（有金鑰且 `_stage_allowed(google)`，含額度、A44 範圍、本輪跳過）只看 ALL，問不到看任何查無。沒金鑰／額度用完／範圍外時的查無不擋日後 Google。⑦（稽核 D GEO-M1）預熱的查無判定不依賴負快取：這次各階都沒回報錯誤 ⇒ miss。守門 `tests/test_geocode_warm_misses_2026_09_28.py`、`tests/test_google_stage_conditions_2026_09_28.py`

## 1.62 — 2026-09-28（主持暫用，列車取號；wip/a-storage-settings：D 稽核 SL-M1）〔core_bump：暫用 1.58 → 1.62〕
- L1（新增，D 稽核 SL-M1）：`helpers.storage_locations.Unreadable`——讀不到設定（庫被鎖、損毀）≠ 沒設定：resolve 回 ""（source="unknown"）、不退回自動判斷、不快取；`configured()` 丟它，設定頁 API 回 503（不顯示空值，避免按儲存把真正的設定蓋掉）
- 頁面（第十四班列車）：`storage-settings.html` 的分頁圖示改讀 `/api/system/branding/favicon`（H10 品牌設定之後才新增的頁面；test_no_our_company_literals 抓到）

## 1.61 — 2026-09-28（A 暫用，列車取號；wip/a-storage-settings：CORE-SPEC 裁示表「儲存位置可設定」）〔core_bump：暫用 1.57 → 1.61〕
- L1（新增）：`helpers.storage_locations`——雲端存檔根目錄、個資資料夾、更新交付資料夾的**唯一**解析處（`resolve`／`path`／`validate`／`create`／`status`／`configured`／`invalidate`）；有設定用設定（不存在回 ""、不退回自動判斷），留空照原本的自動判斷；本檔永不自動建立，只有 `create`（最高管理員在設定頁明確按）只建最後一層
- L1（行為）：`archive._archive_base`／`_pii_archive_root` 改經它（留空時行為不變：掃磁碟機、個資＝根目錄旁）；自動判斷搬到 `archive._auto_archive_base`，只給 storage_locations 呼叫
- L1（新增）：`GET／PUT /api/settings/storage-locations`、`POST /api/settings/storage-locations/create`（最高管理員；儲存驗證存在、可寫、個資與一般／交付不可互相包含；變更與建立寫稽核）；頁面 `storage-settings.html`（系統設定→儲存位置）
- 守門：`tests/platform/test_storage_locations_2026_09_28.py`（讀這三個位置只經解析函式：掃描＋正對照＋反向控制）

## 1.60 — 2026-09-27（暫用，列車取號；a-builder-output＋b-builder-dnd-3 合併為同一個次版號：建構器輸出預覽，使用者 8866 試用回饋）〔core_bump：暫用 1.57 → 1.60〕
- L1（新增）：`helpers.custom_modules.preview_output(body) -> (html, 未完成清單)`——編到一半的草稿照畫：未完成的欄位（沒有 key、公式空白／錯誤、選單沒有選項、型別不認得…）畫成「〈名稱〉尚未完成」；一律走正式匯出的 `render_view`；連一個欄位都畫不出來或版型結構錯 ⇒ `CustomModuleError`（422）
- L1（行為）：`POST /api/custom-modules/{key}/output/preview` 改用它：半成品不再 500（原本欄位層問題沒擋 ⇒ KeyError）；未完成清單放回應標頭 `X-Motrix-Preview-Incomplete`（JSON）；最外層兜底任何例外 ⇒ 422＋記 log；編號規則未完成不再擋預覽（用樣本編號）
- 前端：`static/form-preview.js` 加 `render(el, draft, {mode:'output', key})`
- L1（新增）：自訂模組欄位選填 `help`（文字、最長 `custom_modules.HELP_MAX`＝300 字）；其他型別或過長 ⇒ `fields[i].help` 問題。沒填的定義照舊（只新增）
- 前端（新增，wip/b-builder-dnd-4：使用者第二輪「同頁直接放」）：`static/custom-layout.js` 加 `editorSections`／`placeField`／`sectionOrder`／`moveGroupTo`（建構器畫布＝表單）；表單欄位外觀抽成 `css/custom-form.css`（執行頁與建構器共用）。後端與草稿 JSON 不動

## 1.59 — 2026-09-27（暫用，列車取號；a-prod-status-upgrade：IMPROVEMENT-REPORT §6「prod-status 認不得新升級工具」）〔core_bump：暫用 1.57 → 1.59〕
- L0（新增）：`core.upgrade.write_deployed_marker(root, new_source, now=None)`——轉換完成寫 `backend/.deployed_commit.json`（格式同 apply_update.ps1：commit、commit_short、branch、applied_at、built_at），來源 deploy_manifest.json → backend/.build_commit，都沒有就不寫並回原因
- L0（行為）：`verify_conversion` 的「設定檔不可改寫」不含部署標記；`rollback` 兩種模式都把部署標記還原成備份的那一份（V9 沒有 ⇒ 刪掉），`verify_rollback` 兩種模式都比對它
- `tools/platform/upgrade.py convert` 呼叫它、記進 conversion_log.json、沒寫時印警告 ⇒ 轉換後 `/api/system/deployed-version` 與部署儀表板 prod-status 回新版 commit

## 1.58 — 2026-09-27（B 暫用，列車取號；wip/b-payreq：請款流程，主持裁示模組 migration 順勢補上）
- L0（新增）：`ModuleSpec.migrations: [(版號, 函式)]`——模組自己的 migration；`core.loader.load_all` 在模組**載入時**交給 `core.migrations.register`（停用／未授權／不在包內 ⇒ 不登記、不建表不加欄；再啟用時 `run_all` 從 `module_schema_versions` 記的版本往後補跑）
- L0（新增）：`core.loader.check_migrations(items)`——版號不是從 1 起連續或重複、項目不是 (int, 函式) ⇒ ValueError，該模組載入失敗（原因進狀態表）
- 守門：`tests/platform/test_module_migrations.py`（載入才登記、停用→啟用只跑一次、版號擋、modules/*/migrations 不准 import 會演進的程式碼）
- ⚠ 單模組更新包（`tools/platform/module_update.py`，P7b）仍拒收帶 `migrations/` 的包：帶 migration 的模組只能整包出貨（RUN-PLAN 待辦）
- L0（行為新增，2026-09-28 使用者裁示「該補就補」）：migration 函式**回傳值慣例**——回 `None`＝完成、記版號；回非空字串＝未完成（原因）⇒ 不記版號、記 ERROR、該模組後面的版號這次不跑、其他模組照跑、`run_all` 不丟例外（服務照常起來），下次再試；回其他值＝寫錯、同樣不記。既有 migration 都回 None ⇒ 行為不變。〔更正（B，2026-09-28，稽核 D 後重跑契約題抓到）：這句不完整——產品的 migration（core v1／v2、case v1）確實都回 None，但**寫成 `lambda c: c.execute(...)` 的會回 Cursor ⇒ 1.58 起判成「寫錯＝未完成」**；契約題 tests/test_definitions_store_2026_09_25.py 就是這種寫法，已改成明確回 None。第三方模組照這種寫法寫的 migration 會不記版號、ERROR、該模組下線（看得見，不會靜默）〕守門 `tests/platform/test_migration_incomplete.py`
- L0（新增）：`core.migrations.incomplete(db_path) -> dict[str, tuple[int, str]] | None`——本行程最近一次對該庫 `run_all` 沒完成的 `{模組: (版號, 原因)}`；空 dict＝全部完成；None＝沒對該庫跑過（不是通過）。依庫分開記（主庫、demo 庫互不覆蓋）。apply_update 乾跑以「非空或 None」判失敗（H12 接）
- L1（新增，2026-09-28 主持派工）：`helpers.module_startup.load_modules_like_startup(db_path=None)`——main.py 啟動時「讀停用清單＋load_all(授權、停用、原因)」原段搬出，main.py 改呼叫它（行為不變）。只做 `init_db` 的工具（apply_update 乾跑 migration、`upgrade.py run_migrations`）要先呼叫它、並帶**被試跑的那個庫**，模組 migration 才會登記、停用清單才不會讀到正式庫；呼叫端由 H12 接。守門 `tests/platform/test_module_startup.py`
- L0（行為，2026-09-28 稽核 D PM1）：`run_all` 對 core 以外的模組逐支 `SAVEPOINT`——**丟例外＝未完成**（原因「例外：<型別>: <訊息>」、撤回這一支含 DDL 的寫入、記 ERROR、該模組後面的版號不跑、其他模組照跑、不往上丟）；回原因字串同樣撤回；core 的例外照舊往上丟。一個 L2 migration 壞掉不再讓 init_db／main 起不來，`incomplete` 也不再在例外路徑留下 `{}`（AB-S4 一併關閉）。模組 migration 不准自己 commit（守門 `test_module_migrations::test_module_migrations_do_not_commit_themselves`；repo 外的模組若自己 commit ⇒ savepoint 不在，run_all 記成未完成「違規：自己結束了交易…撤不回」、不往上丟）
- L1（新增，2026-09-28 稽核 A AB-S3；AB-S7 使用者裁示改為主庫決定）：`helpers.module_startup.fail_incomplete_modules(main_db_path, demo_db_path=None) -> {"offline": {...}, "demo_absent": {...}}`——main.py 在 `init_db`（主庫、demo 庫）之後、`mount_modules` 之前呼叫：**主庫** `incomplete` 列到的已載入模組經 `registry.unload` 改記 failed（原因＝migration 回的那句），路由不掛、提供者不在；**只有 demo 庫**未完成 ⇒ 不下線、ERROR，demo 模式打到該模組 API 前綴時 auth middleware 回 404＋原因（`demo_absent_reason(path)`）。`incomplete` 為 None 的庫 ⇒ fail-closed（稽核 D PO1：主庫 ⇒ 所有已載入模組下線；demo 庫 ⇒ demo 模式全部明說缺席）。不動 L0

## 1.57 — 2026-09-27 21:52（暫用號，合回時 core_bump 取號；H10 品牌設定，主持派工）
- 新增 L1 `helpers/branding.py`：品牌圖檔（主 LOGO／深色底 LOGO／favicon）上傳驗證（檔頭判斷 PNG／JPEG／WebP、拒收 SVG、2 MB、單邊 4096）、重新編碼成 PNG 去 metadata、固定存放 `uploads/branding/<kind>.png`、沒上傳回 `frontend/static` 預設檔；版本＝內容 sha256 前 12 碼（設定鍵 `branding_assets`）
- 新增端點（routers/system.py）：`GET /api/system/branding/{kind}`（公開；`?v=` 相符 ⇒ immutable，否則 no-cache＋ETag）、`GET /api/settings/branding`、`PUT`／`DELETE /api/settings/branding/{kind}`（只限 superadmin、展示帳號拒絕、audit `settings.branding.update`）
- `GET /api/system/branding` 回應加 `assets`（三種圖檔帶版本的網址）；`CompanyProfile` 加 `company_name_en`／`phone`／`email`（company_identity 第三層本來就讀這三鍵，原本 PUT 會被靜默丟掉）；改 `name`／`company_name_en`／`tax_id` 時同步已存在的前序別名
- 行為：全新安裝的預設管理員不再寫入本公司人員姓名與 email；拿掉「每次啟動補回 jeff 姓名與 email」
- L1（新增，主持裁示）：`helpers.startup` 的 `install_info`／`builtin_admin_username`／`install_baseline_version`／`version_sort_key`（routers/auth 的版本排序改呼叫它）、`INSTALL_INFO_KEY`／`FRESH_ADMIN_USERNAME`／`LEGACY_ADMIN_USERNAME`；`core.upgrade.INSTALL_ONCE_SETTINGS`（全新安裝才寫一次的設定鍵分類）
- 行為（主持裁示）：全新安裝（users 表是空的）預設管理員改為 `admin`，並寫下安裝資訊 `install_info`（管理員帳號、安裝基準版本）；既有安裝的 `jeff` 不改名、不補值。不可刪除／停用的預設管理員跟著安裝資訊走（`/api/users` 多 `builtinAdmin`，使用者管理頁照它判斷）
- 行為（使用者表單裁示）：`/api/module-versions` 在全新安裝只列安裝基準版本之後的系統紀錄；既有安裝全部顯示；使用者自建的紀錄一律顯示；已出貨條目不改寫
- 刪除一次性工具 `backend/tools/sync_pending_data_20260817.py`（無程式或題引用；內含本公司電話與 email）
- 頁面：57 頁 favicon、上方列、登入頁 LOGO 與副標改讀設定；公司資料設定頁加「品牌與公司名稱」卡、電話／Email 欄；預設 favicon 由 4 MB 壓成 256×256
- 守門：`tests/platform/test_no_our_company_literals.py`（產品碼不可以寫死本公司資料；例外逐筆登記次數與類別）；題 `tests/test_branding_2026_09_27.py`、e2e `tests/test_e2e_branding_2026_09_27.py`

## 1.56 — 2026-09-27（第十三班列車取號，原暫用 1.54；c-approval-l1-4：稽核 D QJ-M1＋孤兒單）
- L1（新增）：`helpers.approval_queue.approval_raw_of(approval_json, doc_type, doc_no)`——欄位版 `approval_json_of`：解析不了 ⇒ None＋ERROR
- L1（行為）：M06 傳票（`modules/accounting/api/vouchers._queue_items`）、自訂模組引擎（`helpers/custom_modules.queue_items`，原本 `json.loads` 沒接 ⇒ 壞一筆整類消失）改用它（主持指派）
- L1（行為）：`_access_step` 加「掛的案件已不存在（孤兒單）⇒ DENY」，佇列一次查完、詳情逐筆，同一個 `_case_names`（§G5 #13）
- 守門：`tests/platform/test_queue_items_malformed_json.py` 改成對**每一個**已註冊提供者驗（不看原始碼特徵；正對照＝驗到的數等於註冊數），不論簽核 JSON 在 data_json 或獨立欄位；反向控制加「tier_fields 吞掉壞 JSON」的合成提供者

## 1.55 — 2026-09-27（第十三班列車取號，原暫用 1.53；c-approval-l1-3：稽核 D AL2-M1＋主持更正）
- L1（行為）：佇列／角標的「點得開才列」判斷改成 `_detail_opens`（與詳情守門同一份）：沒掛案件（linkedQuoteNo 空）的單，每案守門一律查無 ⇒ 只列給簽核鏈上的人與送審人（M01 在不在都一樣）；沒有詳情提供者的類型照列
- §G5 #13（稽核 D AL2-M1 成因）：佇列列出與詳情放行改呼叫同一個 `_access_step(案件單號, 簽核 JSON)`；契約題核對每個提供者的項目 `linkedQuoteNo` ＝ 詳情 `quoteNo`
- `approval_json_of` 說明：〔更正〕跳過壞 JSON 的理由是「列出了也簽不了」，~~不是降級~~；能解析、沒有 approval 的是合法的「沒有設定流程」，照列（契約題加一筆鎖住）

## 1.54 — 2026-09-27（第十三班列車取號，原暫用 1.52；c-queue-json：一筆壞 data_json 讓整類待簽消失；主持指派）
- L1（新增）：`helpers.approval_queue.approval_json_of(data_json, doc_type, doc_no)`——讀不出來 ⇒ None＋ERROR（寫單號），呼叫端跳過那一筆
- 守門：`tests/platform/test_queue_items_malformed_json.py`（對每個已註冊、簽核鏈在 data_json 的 `approval.queue_items` 提供者塞一筆壞的：不丟例外、好的照列、壞的不列、有 ERROR；反向控制＝json_extract 合成提供者必紅）
- 提供者改用它：M01、M03 shipping_note、M04 contractor_voucher、M05 invoice_voucher／payment_request

## 1.53 — 2026-09-27（第十三班列車取號，原暫用 1.51；c-approval-l1-2：稽核 D AL-M1／AL-S1／AL-O3／AL-O4）
- L1（新增）：`routers.approval_queue.detail_not_found_message`、`DETAIL_DENIAL_AUDIT`（`approval.detail_denied`）
- L1（行為）：詳情的「查無」（提供者回 None 或自己丟 404）與「看不到」（每案守門拒絕）一律 404「單據 {id} 不存在」，不帶關聯案件單號；audit 記真正原因（not_found／denied）
- L1（行為）：佇列列出 ⇔ 詳情守門放行——M01 不在時，掛在案件上的單只列給簽核鏈上的人與送審人（`_on_chain`，佇列、角標、詳情共用）
- 題：selfViewBy 兩方向、查無＝看不到、逐格一致性、壞 JSON 的報價單

## 1.52 — 2026-09-27（第十三班列車取號，原暫用 1.50；c-approval-l1，主持裁示）
- 新增 L1 `routers/approval_queue.py`：「待我簽核」佇列、角標、詳情、轉簽（`/api/approval-queue`、`/count`、`/detail`、`/reassign`）自 M01 搬入，路徑不變、前端不改；單據一律經 `approval.queue_items`／`approval.detail`／`approval.reassign` 供應（M01 只是提供者之一），案件資料經 `case.summary`
- 頁面 `approval-queue.html`、選單項「簽核佇列」（`core/menu_l1.json`）、前綴 `/api/approval-queue` 歸回 L1
- `approval.detail` 回傳加可省欄位 `changes`、`selfViewBy`；`helpers/approval_queue.py` 說明改為 L1 彙整

## 1.51 — 2026-09-27（A，IP-96 case.summary 的用途範圍；主持裁示對齊 AT6-O1／JV7；第十二班列車取號，原暫用 1.48）
- L1（新增）：`helpers.case_access.case_summary_scope(user, purpose=None)`（用途 ⇒ "all"／"visible"；權限判斷在 L1）、`SUMMARY_PURPOSE_MODULES`（`voucher_link` ⇒ cashier／finance）、`SUMMARY_LINK_FIELDS`（放寬時只回的摘要欄位）

## 1.50 — 2026-09-27（C，c-case404：M01-O1 看不到＝不存在；疊在 M01 ②；第十二班列車取號，原暫用 1.45 → 1.49）
> 介面只有新增。
- L1（新增）：`helpers.case_access.case_not_found_message`、`deny_case`、`require_case`、`CASE_DENIAL_AUDIT`——案件逐案拒絕一律 404、訊息與查無相同；audit_log 記真正原因（`case.access_denied`，detail.reason＝denied／not_found；背景執行緒寫，避開呼叫端的寫鎖與 rollback）
- L1（行為）：`guard_case_access` 被拒 403 → 404（M03／M04／M05／M10 經它的路徑一併改變）；模組權限的 403 不變
- 規格界線（稽核 D AT6-O1）：只保護沒有傳票權限的角色；傳票 summary-sources 的「案件」頁籤（JV7）照舊對 cashier／finance 列出全部案件
- 守門：`tests/platform/test_case404.py`（同一個回應、audit 原因、正對照、模組權限 403 不變、案件判定之外無逐案 403＋反向控制）；既有 403 斷言 31 行機械替換成 404（改前後同為 559 過）

## 1.49 — 2026-09-27（C，M01-PLAN §3-8 ② M01 本體搬進 modules/case；疊在 c-m01-3；第十二班列車取號，原暫用 1.44 → 1.48）
> 介面沒有變（搬走的全是 M01 的檔，不在 L1 介面裡）。
- L1（移出）：`routers/quotations.py`、`case_action_items.py`、`case_extra_expenses.py`、`completion_notes.py`、`material_orders.py`、`helpers/quotations.py`、`quote_terms.py`、`recognition.py`、`case_deadlines.py`、`case_stage_tasks.py`、`completion_pdf.py` 搬進 `modules/case/`；`main.py` 不再掛這五支 router（載入器依 ModuleSpec 掛載，順序同前）
- L1（宣告）：`core/menu_l1.json` 移出「報價單」「案件管理」「案件執行看板」「簽核佇列」「簽核歷史」五項（改在 `modules/case/module.json`）

## 1.48 — 2026-09-26（C，M01-PLAN §3-8 ① CA-O4：L1 不再 import M01；疊在 c-approval-2；第十一班列車取號，原暫用 1.40 → 1.43 → 1.48）
> 介面只有新增（刪掉的只有 `helpers` 套件對 M01 名稱的再匯出——那些名稱屬 M01，不是 L1 介面）。
- L1（新增，逐字自 M01 `helpers/quotations.py` 下沉，M01 保留同名別名）：`helpers.tax_calc.summarize_payment_items`（`norm_at`、`steps_to_tiers` 已由 1.36 §3-2 下沉）
- `helpers` 套件不再再匯出 M01 的 `SQL_DEAL_TAG`、`SQL_SETTLE_STATUS`、`quote_hot_fields`、`save_quotation_json`、`case_extra_expenses`、`quote_won_month_map`、`validate_invoice_no`／`_amounts`、`validate_quote_tax`、`sync_daily_task_for_case_stage`、`delete_daily_task_for_case_stage`、`daily_task_notice`（呼叫端只有 M01 自己，改 `from helpers.quotations／case_stage_tasks import`）
- 新串接點（M01 提供，暫以 import 時登記）：`case.default_terms`（IP-91 暫定，L1 system 條款端點）、`case.doc_version`（IP-92 暫定，L1 pdf_gen 版本紀錄；pdf_gen 不再寫 quotations）；`case.recognition` 加 `won_month_map`（M08 成案月份）
- 守門：`tests/platform/test_l1_does_not_load_m01.py`、`tests/platform/test_m01_l1_providers.py`

## 1.47 — 2026-09-26（A，因權限沒列出的附件來源要明說；主持裁示；第十一班列車取號，原暫用 1.41）
- L1（新增）：`helpers.uploads.AttachmentNotVisible(visible=None, hidden=0)` 多兩個可選參數：`visible`（逐張過濾時看得到的那幾張）、`hidden`（沒列出的**附件個數**，只有數字；主持裁示：明說只准類別＋個數，不帶單號、檔名、金額）；既有 `raise AttachmentNotVisible()` 寫法不變

## 1.46 — 2026-09-26（A，報價單上的附件用案件頁的讀取規則；稽核 D AT-M1c；第十班列車取號，原暫用 1.40）
- L1（新增）：`helpers.case_access.case_page_readable(conn, quote_no, user)`（案件頁 `GET /api/quotations/{q}` 的讀取規則：row_access `case`／scope="read"，放行 cashier、不放行 case_manage；`get_quotation` 與回簽檔／收款發票／叫料／叫料發票的附件提供者共用同一支）

## 1.45 — 2026-09-26（A，attachments.for_document 依原單據自己的讀取規則；稽核 D AT-M1b；第十班列車取號，原暫用 1.39）
- L1（新增）：`helpers.case_access.case_owner_readable(conn, quote_no, user)`（案件擁有者規則，不放行任何模組；案件額外支出各端點與它的附件提供者共用同一支，附件的可見範圍不可以比原單據寬）

## 1.44 — 2026-09-26（A，attachments.for_document 加權限；稽核 D AT-M1，主持裁示 (b)；第十班列車取號，原暫用 1.38）
- L1（新增）：`helpers.uploads.AttachmentNotVisible`（使用者看不到附件的原單據；取用方列清單時不列、帶入／預覽 403）、`helpers.case_access.case_documents_readable(conn, quote_no, user)`（案件底下的單據准不准讀：與各單據清單同一份規則，`case_access_allowed(..., allow_module="case_manage")`；案件不存在 ⇒ False）

## 1.43 — 2026-09-26（A，attachments.for_document；第十班列車取號，原暫用 1.37）
- L1（新增）：`helpers.uploads.AttachmentSourceError`（附件來源解析不了；訊息給使用者，取用方原樣回 400，不吞成空清單）、`files_from_json_column(conn, table, key_col, key, col)`（某表某列 JSON 欄的檔案清單；列不存在 ⇒ []、壞掉 ⇒ 丟）。給各單據模組實作 `attachments.for_document` 提供者用（主持裁示 M06-b）

## 1.42 — 2026-09-26（C，M01-PLAN §3-7：approval.queue_items／approval.reassign；疊在 c-m01-rec-2）〔core_bump：暫用 1.99 → 1.39〕〔core_bump：暫用 1.39 → 1.42〕
> 介面只有新增。
- L1（新增）：`helpers.approval_queue`——`ACTIVE_STATUSES`、`ApprovalUnreadable`、`active_tiers`／`current_tier_idx`（含舊 steps 相容；自 M01 `routers/quotations._active_tiers`／`_current_tier_idx` 逐字下沉，M01 保留同名別名）、`tier_fields`（原 M01 `_queue_tier_fields`）、`base_item`、`DataJsonApproval(table, key)`
- 新串接點 `approval.reassign`（IP-94 暫定）：各單據模組提供轉簽時的簽核鏈讀寫；M01 轉簽端點不再以 `_REASSIGN_TABLES` 逐表直寫
- IP-10 `approval.queue_items`：M04、M05、M03、M06、M07 各自提供待簽項目；M01 佇列與角標只彙整（佇列回應新增 `reassignTypes`）
- 新串接點 `approval.detail`（IP-93 暫定，c-approval-2）：簽核佇列詳情裡其他模組單據（承攬商匯款申請、開票申請、請款單、出貨單）的內容由擁有模組提供；M01 只做每案權限、案件抬頭、金額遮蔽
- L1（新增，c-approval-2）：`helpers.approval_queue.file_entries`（自 M01 `_file_entries` 逐字下沉，M01 保留別名）、`snapshot_doc_detail(row)`（付款／開票類單據共用的詳情內容，自 M01 詳情端點三表共用段下沉）
- 守門：`tests/platform/test_approval_providers.py`；`tools/check_approval_queue_coverage.py`（AS3）改成也認提供者

## 1.41 — 2026-09-26（C，M01-PLAN §3-6：case.recognition；疊在 c-m01-s3-2）〔core_bump：暫用 1.99 → 1.38〕〔core_bump：暫用 1.38 → 1.41〕
> 介面只有新增。
- L1（新增）：`helpers.recognition_basis`——`BASES`、`BASIS_NOTES`、`normalize_basis`（自 M01 `helpers/recognition.py` 逐字下沉；recognition 保留同名別名）
- M01（新增，暫以 import 時登記）：`case.recognition`（IP-95 暫定）——六個計算方法轉呼叫 `helpers.recognition`；M08 營運報表改經它
- 守門：`tests/platform/test_case_recognition.py`

## 1.40 — 2026-09-26（C，M01-PLAN §3-4：case.summary／case.locations）〔core_bump：暫用 1.99 → 1.35〕〔core_bump：暫用 1.35 → 1.37〕〔core_bump：暫用 1.37 → 1.40〕
> 介面只有新增。
- L1（新增）：`helpers.case_access.SYSTEM`——L1 背景工作取案件資料時的身分（不做逐案權限過濾）；只准 L1 使用（守門 `tests/platform/test_case_summary_locations.py`）
- L1（行為）：`routers/map_points.py` 改走 M01 的 `case.locations`，不再讀 `quotations`（KNOWN_L1 刪 map_points；到期題由紅轉綠）；M01 不在 ⇒ 案件來源 `skipped: module_absent` 並明說（`CASES_MODULE_ABSENT`）
- M01（新增，暫以 import 時登記）：`case.summary`（IP-96 暫定）、`case.locations`（IP-97 暫定）；IP-12 `summary` 轉呼叫 case.summary（淘汰中）
- 稽核 D CS-M1：SYSTEM 守門改成「從 case_access 取得任何名稱、且提到哨兵名字的檔都要查」（6 種寫法納入反向控制）；另加執行期第二道：呼叫端在 `backend/modules/` 傳 SYSTEM ⇒ PermissionError。CS-S1：IP-97 註明 address 屬個資、取用方不可寫進 log／匯出
- 淘汰登記：`helpers/quotations.py::_CaseAccess.summary` 進 `docs/platform/deprecations.json`（remove_at_major 2）；`test_deprecations` 的名稱支援 `Class.member`（合成反向控制）

## 1.39 — 2026-09-26（C，M05 應收應付搬遷；疊在 T 之上）〔core_bump：暫用 1.99 → 1.36〕〔core_bump：暫用 1.36 → 1.39〕
> 介面只有新增（`RECEIVABLES_MISSING`）；`helpers.receivables` 的三支函式名稱與簽章不變，行為改成轉呼叫 M05 的 provider。
- L1（行為）：`helpers.receivables` 改為**薄殼**（淘汰中，**下一個主版號刪除**：`collect_income_items`、`collect_tax_invoices`、`round_half_up_invoice`、`RECEIVABLES_MISSING`）——函式本體收回 `modules/arap/receivables.py`（ROADMAP A8b），殼只轉呼叫 provider `receivables.income_items`／`receivables.tax_invoices`；M05 不在 ⇒ `collect_income_items` 回 `[]`、`collect_tax_invoices` 404「應收應付模組未安裝…」（主持裁示 (a)：直接刪＝主版號，牽動全部模組的 core 範圍）
- L1（新增）：`helpers.receivables.RECEIVABLES_MISSING`
- L1（行為）：M06 `routers/accounting_export.py` 的 T100 收款事件改取 M05 provider；M05 不在 ⇒ 略過收款事件、預覽 `notice` 列出 `T100_RECEIVABLES_MISSING`（與 IP-14 的缺口並列）
- L1（移出）：`routers/cashier.py`、`routers/invoice_vouchers.py`、`routers/payment_requests.py` 搬進 `modules/arap/api/`（M05；不屬於 L1 公開介面）
- 守門：`tests/platform/test_receivables_shim.py`（殼只准轉呼叫 provider；掃描器反向控制；M05 不在 ⇒ `[]`／404；M05 在 ⇒ 轉的就是 provider 的結果）、`tests/platform/test_receivables_absent.py`（M08 incomeNotice、稅務匯出 404、T100 notice）；KNOWN_L1 刪 `helpers/receivables.py`（殼不再讀 quotations）

## 1.38 — 2026-09-26（A，M06 前置：簽核鏈解析下沉 L1；列車上 core_bump 取號）〔core_bump：暫用 1.35 → 1.38〕
- L1（新增）：`helpers.tiered_approval.ApprovalChainUnreadable`、`parse_approval_json(record, *, doc_label="單據")`——單據 `approval_json` 的唯一解析入口（`JV27`），讀不出來 ⇒ 丟（fail-closed，不回 `[]`）。自 M06 `helpers/voucher` 下沉（主持裁示 M06-c），M01 簽核佇列改從 L1 取，不再 import M06；`helpers.voucher` 的 `VoucherChainUnreadable`／`parse_approval_json` 保留為同名別名（淘汰中；例外是同一個類別）

## 1.37 — 2026-09-26（B，C4 選單切換；暫用號，合回時 core_bump 依 origin 取號）〔core_bump：暫用 1.35 → 1.37〕
> STAGE-C C4（主持裁示 A）：選單套用使用者角色的版面。`core.registry.CORE_VERSION` 1.34 → 1.35（只有新增）。
- L1（新增）：`core.catalog.effective_layout_ops(conn, module_key, role)`——resolve（角色＞公司＞預設）＋逐筆 `check_layout`，`GET /api/layout/{module}` 與選單共用這一份
- L1（新增）：`core.menu.apply_layout(groups, ops)`、`core.menu.sidebar_point_id(item)`——側欄點的 hide／show／move{index}；hide 只是顯示、不是權限
- L1（相容擴充）：`GET /api/platform/menu` 多回 `layout`（已套使用者角色版面的選單＋applied／skipped／dropped／errors／sources）；`groups`／`denied` 維持宣告版
- L1（新增）：`core.menu.declaration(l1, mod_items)`——與使用者無關的選單宣告（build 的排序、不過濾、每項帶 perm）；過濾後＝build（同一使用者）
- L1（新增）：`GET /static/sidebar.js` 前置 `window.MOTRIX_MENU = {v, groups, pageModules}`（`routers.platform_menu.sidebar_js_source`；模組狀態與自訂模組不放：要登入才拿得到）
- L1（新增）：`core.menu.merge_custom(groups, customs)`、`core.menu.CUSTOM_DEFAULT_GROUP`——已發布自訂模組併進選單（依 menu.group 顯示名稱併組，否則新開組）
- L1（新增）：`helpers.custom_modules.visible_to(mods, user)`——自訂模組可見性唯一一份；`GET /api/custom-modules` 與選單共用
- L1（相容擴充）：`GET /api/platform/menu` 的 `layout.groups` 併入使用者看得到的自訂模組，另回 `layout.custom`（key 清單）；讀自訂模組失敗 ⇒ 列在 `layout.errors`
- L1（宣告）：`core/menu_l1.json` 系統組新增「模組建構器」（module-builder.html，superadmin；原由 custom-modules-nav.js 追加）
- 前端：`sidebar.js` 改讀 `MOTRIX_MENU`（首屏同步、權限同步過濾），session 後套 `layout`；`<html data-menu-state>`＝declared／layout／layout-failed；序號丟舊回應；`window.MotrixMenu.refresh()`；寫死的選單清單與 `MODULE_PAGES` 表移除；`custom-modules-nav.js` 刪除

## 1.36 — 2026-09-26（C，M01-PLAN §3-2：兩支通用函式下沉 L1；疊在 T 之上）〔core_bump：暫用 1.99 → 1.36〕
> 介面只有新增；舊位置保留同名別名（同一物件）。
- L1（新增）：`helpers.dates.norm_at`、`helpers.tiered_approval.steps_to_tiers`（自 M01 `helpers/quotations.py` 的 `norm_at`、`_steps_to_tiers` 逐字搬入）
- L1（改 import 來源）：`helpers.norm_at` 改自 L1 再匯出（~~`helpers._steps_to_tiers` 也改自 L1 再匯出~~〔更正（rebase 到第六班後）：以底線名轉出 L1 的公開函式會被 b-g1 守門判為未宣告的底線名稱 ⇒ `helpers._steps_to_tiers` 照舊由 M01 的別名轉出（同一物件）〕）；`routers/system` 改自 tiered_approval import ⇒ system 對 M01 只剩 `quote_terms.DEFAULT_TERMS`（CA-O4）
- 守門：`tests/platform/test_m01_sink2_contract.py`（別名同一物件、L1 檔不 import M01、system 不為此 import quotations；突變：別名換複本、system 改回 ⇒ 皆紅）

## 1.35 — 2026-09-26（C，T：稅額純函式下沉 L1；主持核准，M01 步驟表 §3-1）〔core_bump：暫用 1.99 → 1.30〕〔core_bump：暫用 1.30 → 1.35〕
> 介面只有新增；舊位置 `helpers.quotations` 保留同名別名（同一物件），呼叫端不必改。
- L1（新增）：`helpers.tax_calc`——`TAX_TYPES`、`TAX_TYPE_LABELS`、`LEGAL_TAX_RATE`、`LEGACY_TAX_NOTE`、`quote_tax_type`、`tax_split`、`invoice_amounts`、`payment_item_amounts`（自 M01 `helpers/quotations.py` 逐字搬入）
- L1（改 import 來源，行為不變）：`helpers.payment_item_amounts` 改自 tax_calc 再匯出；`pdf_gen`、`routers/invoice_vouchers`、`modules/analytics/api/reports`（第六班自 routers/reports 搬過去；rebase 時 git 的改名偵測帶過去）、`helpers/receivables`（第六班才進 platform，rebase 後補）、`tools/list_payment_anomalies` 改自 tax_calc import ⇒ 這幾支對 M01 的相依只剩別的名稱（CA-O4 的一半）
- L1（修正）：`tax_split` 的錯誤訊息 `1～4%` 沒跳脫 ⇒ 原本丟 TypeError 而不是 ValueError；呼叫端都先排除 legacy，行為面無影響
- 守門：`tests/platform/test_tax_calc_contract.py`（不讀表、不 import M01、別名是同一物件；掃描器正對照；突變：別名指錯、換成複本、函式讀表、延遲 import M01 ⇒ 皆紅）

## 1.34 — 2026-09-26（A，稽核 D O-4，wip/a-m10 68f16342；第六班列車取號）〔core_bump：暫用 1.99 → 1.34〕
> 介面不變。原 commit 改寫的是 1.17（今 1.26）段落那一行；列車上改為新增本段、不改寫已合回的歷史段落。
- L0（行為）：`core.source_tree.module_installed(path)` 的「在」改為 `modules/<key>/module.json` 存在（與載入器、`module_dirs()` 同一個判準）；只剩 `__pycache__` 的空資料夾不算在；`modules/`（沒有 key）一律 True

## 1.33 — 2026-09-26（B，M08 搬遷；暫用號，合回時 core_bump 依 origin 取號）〔core_bump：暫用 1.30 → 1.33〕
> M08 搬遷 ③（主持裁示 a）：應收收入與銷項發票的資料收集自 routers/reports.py 下沉 L1。`core.registry.CORE_VERSION` 1.29 → 1.30（只有新增）。
- L1（新增）：`helpers.receivables`——`collect_income_items`／`collect_tax_invoices`／`round_half_up_invoice`（函式本體與原本逐字相同）；M05 cashier、M06 accounting_export 改從這裡取，不再 import M08（ROADMAP A8b 中繼，M05 搬遷時收回）
- L1（新增）：`routers/company_lookup.py`——`/api/now`、`/api/company/tax/{tax_id}`、`/api/company/search`（GCIS 統編／公司名稱查詢）自 `routers/dashboard.py` 拆出（路徑、權限、額度設定鍵不變；M08 搬遷 ②）

## 1.32 — 2026-09-26（C，M07 搬遷前置）〔core_bump：暫用 1.99 → 1.30〕〔core_bump：暫用 1.30 → 1.32〕
> M07 薪資獎金搬進 modules/ 的前置：切斷 M07 → M06 與 L1 → M07。只有新增。
- L1（新增）：`helpers.tiered_approval.resolve_display_names`（自 M06 `helpers/voucher.py` 下沉，簽核格帳號 → 顯示名稱；voucher 保留同名匯入）、`pdf_gen.fmt_money_blank_zero`（自 M06 `helpers/voucher_pdf.py._fmt_money` 下沉，0 印空白）
- L1（行為）：`/api/system/bonus-module-status` 改走新串接點 IP-16 `bonus.module_status`（M07 → L1；編號暫定，列車定號）；M07 不在 ⇒ `{"enabled": false, "notice": …}`
- M07（行為）：獎金分潤單預覽／PDF 不再需要 M06（原本 M06 不在回 503「會計模組未安裝」）；公司抬頭改用 L1 `company_identity.company_name()`（主要據點名稱，QL8；原本讀 `company_profile.name`，設了據點的安裝抬頭會改成主要據點的公司名）
- 守門（PLAYBOOK §B-11）：begin_write 白名單、頁面路徑基線、資料路徑已知呼叫端、D7 冒煙清單在模組不在時不算過期（判準 `source_tree.module_installed`）；D7 冒煙加回定義文件庫

## 1.31 — 2026-09-26（C，M04 搬遷前置）〔core_bump：暫用 1.99 → 1.31〕
> M04 外包工班搬進 modules/subcontract 的 L1 前置。只有新增。
- L1（新增）：`helpers.dates.normalize_date`（自 M01 `helpers/recognition.py` 下沉；recognition 保留同名匯入）

## 1.30 — 2026-09-26（C，案件存取守門下沉）〔core_bump：暫用 1.99 → 1.30〕
> 主持裁示：案件存取守門自 M01 下沉 L1，M01／M03／M05／M10 與 M04 搬遷都依賴它。只有新增。
- L1（新增）：`helpers.case_access`——`CASE_ACCESS`（row_access `case` 規則，登錄照舊）、`is_document_approver`、`case_access_allowed`、`guard_case_access`、`case_module_present()`；`helpers.quotations` 與 `helpers` 保留同名匯入（同一個物件）
- L1（行為）：M01 不在 ⇒ `guard_case_access` 404、`case_access_allowed` False（表與資料在也一樣）；「在不在」看 M01 提供的 `case.access`（IP-12，主持裁示只留一個訊號，稽核 D CA-M1）；只有 `no such table` 當查無此案，其他資料庫錯誤照樣丟出（CA-S2）
- 已知例外：L1 讀寫 M01 `quotations` 只准經本檔（DEPENDENCY-MAP §3.2，守門 `test_case_access_l1`，判準用 dep_scan 的 SQL 解析＋逗號 join，含 L0 core/）

## 1.29 — 2026-09-26（C，參照選項權限）〔core_bump：暫用 1.99 → 1.21〕〔core_bump：暫用 1.21 → 1.29〕
> P8 前端代理回報：參照欄選項只檢查目前模組的權限。只有新增與收緊。
- L1（新增）：`helpers.custom_modules.register_ref_target(..., modules=)`（讀這個對象需要的權限）、`ref_target_modules(target)`
- L1（行為）：`GET /api/custom/{key}/ref-options/{field}` 也檢查被參照那一方的讀取權限：`custom:<模組>` 要有該模組權限、`customers` 要有客戶相關權限；沒有 ⇒ 403

## 1.28 — 2026-09-26（C，稽核 D C-M4，wip/c-audit-d-2；列車取號）〔core_bump：暫用 1.99 → 1.28〕
> 同批的 C-M3／C-M5／C-S1～S5／C-O1／U14 已隨第三班以 1.22 合回；本段只有 C-M4。介面不變。
- L1（行為）：公式 `round` 改為四捨五入（`helpers.legal_params.round_half_up`；原本是內建的銀行家捨入，C-M4）

## 1.27 — 2026-09-26（P9 拖曳排版器，wip/h-p9；⚠ 暫用號：列車上依 origin 重定）〔core_bump：暫用 1.99 → 1.21〕〔core_bump：暫用 1.21 → 1.27〕
> 只有新增。
- L1（新增）：定義文件庫 `layout` kind 的驗證器與程式預設（`routers/definitions.py`）——key＝`module:<模組>`、body＝`{"ops": [...]}`；發布／還原前經 `core.catalog.check_layout`（P3 排版守門第一個產品呼叫者），問題路徑 `ops[i].…`；程式預設＝`{"ops": []}`（模組未載入 ⇒ 沒有預設）
- L1（新增）：端點 `GET /api/layout/{module}`——任何登入者讀自己角色的版面（`resolve`：角色 ＞ 公司 ＞ 程式預設）＋該模組的可自訂點；`?role=` 僅超級管理員（排版器的「以某角色預覽」）；現在不合法的已發布操作不套用、列在 `dropped`；讀定義失敗 ⇒ 程式預設＋`error`
- L1（新增，前端）：`static/custom-layout.js` 排版模型（`MotrixCustomLayout.pageModel／applyOps／compileOps／describeDiff／applyPersonal`）、`static/layout-runtime.js`（Alpine store `layout`：執行時套用＋個人層）、`static/layout-editor.js`（同頁編輯模式）

## 1.26 — 2026-09-26（A，M10 搬遷；列車上 core_bump 取號）〔core_bump：暫用 1.96 → 1.17〕〔core_bump：暫用 1.17 → 1.26〕
- L0（新增）：`core.source_tree.module_installed(path)`——守門判斷「清單上的模組檔所屬模組在不在」的唯一實作（模組被拿掉時，它的條目不算幽靈；PLAYBOOK §B 步驟 11）

## 1.25 — 2026-09-26（A，M12 搬遷前置；列車上 core_bump 取號）〔core_bump：暫用 1.98 → 1.14〕〔core_bump：暫用 1.14 → 1.16〕〔core_bump：暫用 1.16 → 1.25〕
- L1（新增）：`helpers.daily_checks`——每日 08:00 執行器（`schedule_daily_checks`／`run_once`／`run_module_checks`）；模組以提供者 `daily.check` 登記（INTEGRATION-POINTS IP-11）
- L1（新增）：`helpers.system_checks`——憑證到期、備份新鮮度、磁碟、測試暫存、簽核催辦、請求紀錄清理（自 `routers/daily_tasks.py` 逐字搬出；`run_all(prune)`）；不依賴任何 L2 模組
- main.py：啟動改呼叫 `helpers.daily_checks.schedule_daily_checks()`（原 `routers.daily_tasks.schedule_overdue_check()` 移除）

## 1.24 — 2026-09-26（C，模組檔案清單單一來源）〔core_bump：暫用 1.99 → 1.21〕〔core_bump：暫用 1.21 → 1.24〕
> 主持裁示：「模組裡有哪些檔」只有一份定義。A 的 M03、C 的 M04、B 的 M08 把多支 router 放在 `api/`（CORE-SPEC §3）都依賴它。只有新增。
- L0（新增）：`core.source_tree.module_files(d)`——模組資料夾所有層的 `*.py`，排除 tests／migrations；`router_files`／`logic_files` 與 tools/platform/dep_scan.py 都用它
- 工具：dep_scan 的模組單位名稱 `mod:<key>/<相對路徑>`（第一層不變，例 `mod:tender_radar/api`；子目錄例 `mod:<key>/api/orders`）；`modules.<key>.<子目錄>.<檔>` 的 import 指到那個檔

## 1.23（暫用號，合回時對照 origin 再定；PLAYBOOK §C-7）— 2026-09-26（cloud-pii）〔core_bump：暫用 1.10 → 1.12〕〔core_bump：暫用 1.12 → 1.13〕〔core_bump：暫用 1.13 → 1.14〕〔core_bump：暫用 1.14 → 1.16〕〔core_bump：暫用 1.16 → 1.23〕
> `core.registry.CORE_VERSION` 1.15 → 1.16（G1 快照要求升次版號；只有新增。分支先後暫用 1.8、1.10、1.12、1.13、1.14，版號由 core_bump 依 origin 取）。
- L1（相容擴充）：`static/privacy-notice.js` 新增 `subjectState()`——單據上手動輸入的聯絡人（報價單、案件、完工單、網路規劃書）的告知狀態；紀錄鍵含聯絡人姓名，伺服器只接受已存檔的那一位（2026-09-26 主持裁示）
- L1（新增）：`helpers.privacy_notice` 個資蒐集告知擴大到其他表單（CUSTOMIZATION-SPEC §9.3）——`CONTACT_TEMPLATE`／`USER_TEMPLATE`／`PURPOSES`／`purpose_template_for`／`purpose_notice_text`／`current_purpose_notice`／`record_purpose_ack`／`acks_with_prefix`；既有函式簽章不變
- L1（相容擴充）：`GET /api/legal-params/privacy-notice?purpose=contractor|contact|user`（沒帶＝`contractor`，與 1.7 相同；不認得的用途 400）；前端元件 `static/privacy-notice.js` 的 `load(token, purpose?)`、新增 `contactsState()`
- L1（新增欄位）：`company_profile.privacy_notice_contact`、`company_profile.privacy_notice_user`；設定鍵 `privacy_notice_acks` 新增鍵形 `customer_contact:`／`supplier_contact:`／`vendor_contractor:`／`user:`
- 清單 `docs/platform/pii_forms.json`＋守門 `tests/platform/test_pii_forms_notice.py`（MODULE-GUIDE §11）

## 1.22 — 2026-09-26（C，稽核 D 修正）〔core_bump：暫用 1.99 → 1.15〕〔core_bump：暫用 1.15 → 1.22〕
> C（AUDIT-D-C-P4P5P8 必修 C-M3／C-M5、建議 C-S1～S5、觀察 C-O1、使用者裁示 U14）。只有新增與收緊驗證。
- L1（新增）：`helpers.custom_modules.sample_values`（發布時試算用的樣本值）、`can_edit_draft(rec, body, user)`（U14：草稿只有建立者與超級管理員可以修改、送出）；讀單回 `canEdit`
- L1（行為）：自訂模組發布驗證多擋 on_approved 循環、起始狀態掛簽核、permission 用內建 key 或與已發布模組共用、公式與條件的樣本試算錯誤；執行時自動通過最多連跳 20 次（超過 409）；數字欄位拒收 NaN／inf（寫入時 `allow_nan=False` 第二道），舊資料讀出為空值；代理人可讀單與輸出；別人的草稿 update／transition 回 403
- L1（行為）：`core.definitions.publish`／`restore` 先拿寫鎖（`begin_write`）；`restore` 回傳多 `draftPending`（C-O1）

## 1.21 — 2026-09-26（C，K-O2 wip/c-ko2；列車取號）〔core_bump：暫用 1.99 → 1.21〕
> 原寫在 1.14（D7）段落內；D7 已於第二班以 1.17 合回，不改寫 ⇒ 另立一段。
- L1（新增）：`helpers.startup._prune_login_locks`（自 `routers/auth.init_rate_limiting` 移入，後者改為只讀）——CORE-SPEC 裁示 K-O2：啟動時寫 DB 只能經 `helpers/startup.py`；守門 `tests/platform/test_startup_writes_only_via_startup.py` 實際啟動兩次、記下每句寫入的呼叫堆疊（工具 `tools/platform/startup_writes.py`）

## 1.20 — 2026-09-26（P1／P3，wip/cloud-p1p3＋稽核修正 wip/x-p1p3-fix；⚠ 暫用號：列車上依 origin 重定）〔core_bump：暫用 1.8 → 1.15〕〔core_bump：暫用 1.15 → 1.20〕
> `core.registry.CORE_VERSION` 1.19 → 1.20（只有新增）。
- L0（新增）：`core.customization`——module.json 可自訂點（P3）：`SCHEMA_VERSIONS`／`PAGE_KINDS`／`OPS_*`／`EXPORT_FORMATS`、`OP_KEYS`／`MOVE_DEST_KINDS`、`validate_manifest(manifest)`、`require_valid(manifest)`、`core_fields(manifest)`、`endpoint_parts(spec)`。攤平與排版檢查是私有的（`_raw_points`、`_check_ops`），對外只經 `core.catalog`（稽核 P-M1）
- L0（行為，相容擴充）：`core.loader.load_all()` 載入前呼叫 `customization.require_valid`；`customization` 格式錯誤 ⇒ 模組不載入（state＝failed，reason 帶前三項問題位置）。沒有 `customization` 鍵 ⇒ 照常載入
- L1（新增）：`core.catalog`——能力目錄（P1）：`CATALOG_VERSION`、`EXPECTED_SECTIONS`、`register_section(name, owner, fn)`、`section(name)`、`build()`、`module_endpoints(spec)`、`endpoint_problems`、`output_problems`；同一區段兩個擁有者 ⇒ ValueError；**可自訂點唯一入口** `layout_points(module_key=None)`（藏起引用不存在端點／版型的點、選單去掉被藏起的按鈕、未載入模組沒有點）與排版守門 `check_layout(module_key, ops)`（每種操作限定鍵、move 限定容器、select_template 限定程式提供的版型）
- L1（新增）：端點 `GET /api/platform/catalog`（僅超級管理員，唯讀；`routers/platform_catalog.py`，並把 `helpers.doc_template` 登記成 `outputs` 區段）

## 1.19 — 2026-09-26（A，信件稽核修正 wip/a-mail-fix；列車取號）〔core_bump：暫用 1.99 → 1.19〕
- L1（新增）：`helpers.mail_types.MANAGED_ELSEWHERE`——收件人由別處維護、不在信件設定頁覆寫的類型（每月營運報表；稽核 M-S3）

## 1.18 — 2026-09-26（C）〔core_bump：暫用 1.99 → 1.14〕〔core_bump：暫用 1.14 → 1.18〕
> C（P8 前端缺口 #3～#7、P2 開票憑據稅別依據、P2 第二份單據勞務報酬單＋R3 個資告知）。
- L1（新增）：串接點 IP-10 `approval.queue_items`——「待我簽核」佇列與角標收其他模組的待簽項目（M01 取用；L1 自訂模組引擎提供 `custom_modules.queue_items`）；自訂模組通知的 ref_id＝`custom:<模組>:<單號>`（`notify_ref`）
- L1（新增）：`core.definitions.list_definitions`／`delete_draft`；API `GET /api/definitions/{kind}`、`DELETE /api/definitions/{kind}/{key}/draft`
- L1（新增）：`helpers.doc_template.BLOCK_SPECS`／`BLOCK_ITEM_SPECS`／`FORMATS`／`COLUMN_FORMATS`（建構器的積木參數規格）；積木 `doc_header`、`section_title`、`part`、`kv_table`、`footer_text`、`text_page`；`sign_boxes` 的 `variant: named`；格式 `ntd`；條件 `present`；主題可自帶外框（`frame`）與 `after_root`；主題 `payslip`
- L1（新增）：`helpers.custom_modules.ref_options`／`APPROVER_SOURCES`；API `GET /api/custom/{key}/ref-options/{field}`；能力目錄補積木規格、主題、輸出格式、欄位格式、簽核人來源；自訂模組與輸出版型預覽可 `?format=pdf`
- L1（行為）：開票申請憑據印出零稅率／免稅依據（R2）；勞務報酬單改由版型產生（`helpers/output_templates/payslip.json`，可覆寫與預覽），並加個資蒐集告知（R3：已告知印時間與人員，否則附告知事項全文）

## 1.17 — 2026-09-26（C，D7）〔core_bump：暫用 1.99 → 1.14〕〔core_bump：暫用 1.14 → 1.17〕
> C（D7 預演抓到的升級阻擋點）。
- L0（新增）：`core.upgrade.RUNTIME_STATE_SETTINGS`——啟動時就會更新的執行期狀態（每日掃描的節流日期）；`settings_changes` 只在值是日期且沒有往回走時放行，其他鍵照舊逐一比對。原本真實庫的舊日期會讓新版啟動後的驗證判定「改寫既有設定」⇒ 正式機升級被判失敗而回滾

## 1.16 — 2026-09-26（B）〔core_bump：暫用 1.11 → 1.14〕〔core_bump：暫用 1.14 → 1.16〕
> 階段 C／C3：選單由登錄表產生。只有新增。
- L1（新增）：`core.menu`——`load_l1`／`module_items`／`validate`／`visible`／`build`／`denied`／`MENU_L1`／`ITEM_KEYS`；資料 `core/menu_l1.json`（群組固定鍵＋L1 選單項）；模組以 module.json `pages[].menu` 宣告自己的選單項
- L1（新增）：端點 `GET /api/platform/menu`（`routers/platform_menu.py`）——目前使用者看得到的選單；C3 期間與 sidebar.js 舊選單並行，對等守門 `tests/platform/test_menu_parity.py`
- L1（新增）：`core.pages.L1_PAGES_FILE`／`load_l1_pages()`、資料 `core/l1_pages.json`；`collect(…, l1_pages=None)`（相容擴充）——模組宣告 L1 頁面一律算衝突（稽核 D P-M1）

## 1.15 — 2026-09-26（X-R）〔core_bump：暫用 1.10 → 1.12〕〔core_bump：暫用 1.12 → 1.15〕
> 稽核 AUDIT-D-R1-R3-legal 的修正（D-1、D-2、S-1～S-6、O-3、O-4）。暫用 1.10：合回時依 origin 取下一號。只有新增；行為修正列在下面。
- L1（新增）：`helpers.legal_params.round_half_up(amount, rate=1)`（四捨五入到元，補充保費）、`floor_amount(amount, rate=1)`（元以下捨去，扣繳）——法規金額捨入的唯一來源（IP-7 契約 1.2）；前端 `static/legal-round.js`（`MotrixLegalRound.halfUp／floor／taipeiToday`）
- L1（新增）：`helpers.legal_params.ARTICLE_8_ITEMS`／`ARTICLE_8_SOURCE`／`ARTICLE_8_DELETED`／`LEGACY_TAX_BASIS_LABELS`；`TAX_BASIS_OPTIONS["exempt"]` 改成 §8 第 1～32 款逐字（代碼 `8-N`），`8` 移出選項（只剩顯示用的舊標籤）；`/api/legal-params/tax-basis-options` 多 `sources`
- L1（新增）：`helpers.privacy_notice.AcksCorrupted`、`TEXTS_KEY`、`archive_text(conn, text)`、`text_for_hash(h)`；端點 `GET /api/legal-params/privacy-notice/texts/{hash}`；設定鍵 `privacy_notice_texts`
- L1（修改行為，介面不變）：`record_ack`／`get_ack` 讀不懂設定值 ⇒ `AcksCorrupted`（原本當成空的整份覆寫）；`record_ack` 新紀錄同時存告知全文；`privacy-notice.js` 告知書日期改台北時間
- 勞報單（M07，行為修正）：補充保費四捨五入（原為銀行家捨入）；`update_payslip` 讀、改、寫在同一個 `write_txn`；新單日期預設台北時間

## 1.14 — 2026-09-26（A，信件與通知收件設定；合回時 core_bump 取號）〔core_bump：暫用 1.99 → 1.13〕〔core_bump：暫用 1.13 → 1.14〕
- L1（新增）：`helpers.mail_types` 信件類型登記表——`register`／`get`／`all_types`／`keys`／`subject`／`CATEGORIES`／`GROUPS`／`MODES`／`ROLES`／`OVERRIDES_KEY`／`SUBJECT_PREFIX`／`MailType`；模組可在載入時登記自己的信件類型
- L1（新增）：`helpers.email_notify._group_emails(key)`（群組收件人，依登記表與覆寫）；`_admin_emails`／`_superadmin_emails` 改為它的相容名稱；`_lookup_emails`／`_department_manager_emails`／每月報表收件人套用覆寫；未登記 key fail closed（只寄超級管理員）
- L1（修改，相容）：`helpers.email_notify._build_html(mail_key, …, impact=None, action=None)`——第一個參數改為信件類型 key，內文固定「事由、影響、建議處理、發送時間與來源」；主旨一律 `mail_types.subject(key, 事由)`
- L1（新增）：端點 `/api/mail-types`（GET）、`/api/mail-types/{key}/recipients`（PUT）、`/api/mail-types/receivable`（GET）；頁面 `mail-settings.html`
- 修正：`helpers.geo.notify_quota_warning` 原本呼叫 `_send_raising(subject, body)` 少了收件人參數，執行即 TypeError（額度警戒信從未寄出）

## 1.13 — 2026-09-26（B）〔core_bump：暫用 1.10 → 1.12〕〔core_bump：暫用 1.12 → 1.13〕
> rebase 時 1.8、1.9 已被 X-9b、A 使用 ⇒ 1.10（PLAYBOOK §C-7）。只有新增。
- L1（新增）：`core.pages` 頁面對照與提供（階段 C／C1，STAGE-C-DESIGN §3）——`collect`／`build_page_map`／`lookup`／`resolve`／`page_response`／`notice_kind`／`notice_html`／`read_manifests`／`check_and_register`／`valid_name`／`PageConflict`／`PAGE_NAME`／`NOTICE`
- L0（新增）：`core.paths.FRONTEND_PAGES_DIR`
- 行為（main.py）：`GET|HEAD /pages/{name}` 由 `core.pages` 提供（StaticFiles 之前）——模組已載入 ⇒ 檔案；沒有載入 ⇒ **HTTP 404＋伺服器提示頁**（停用／未授權／失敗／未安裝，裁示 D2 選項 A，與 P-FE-03 並存）；頁面衝突比照 P-LD-07：在 `mount_modules` 之前檢查，後到的模組整個記 failed、不掛
- L0（新增）：`core.source_tree.FRONTEND_PAGES`／`page_file(name)`／`page_files()`——讀頁面原始碼的唯一入口（C2，頁面搬進模組資料夾後照樣找得到；守門 tests/platform/test_page_paths_centralized.py）

## 1.12 — 2026-09-26（A，獎金分潤）〔core_bump：暫用 1.10 → 1.12〕
- L1（新增）：`helpers.email_notify.notify_bonus_submitted`（獎金分潤輪到的簽核人＋代理人）、`notify_bonus_payout_ready`（核准待發放 → 出納）；信中不含金額。通知設定新增 `bonus_submitted`、`bonus_payout_ready` 兩個可個別關閉的事件（CORE-SPEC「使用者裁示」獎金分潤：通知）
- 串接點（新增，L2 之間）：IP-8 `bonus.payouts`（M07 → M05 出納）、IP-9 `expense.entries`（M07 → M08 報表）；U4 經 IP-7 `helpers.legal_params` 依撥付日選版，讀不到或欄位不齊 ⇒ 拒絕撥付

## 1.11 — 2026-09-26〔core_bump：暫用 1.99 → 1.11〕
> C（P4／P5 定義文件庫＋自訂欄位、P8 自訂模組引擎、A8d branding、S-CC07 N-1；原排 1.5，合回時 1.5～1.9 已被使用，依 §C-7 取下一號）。
- L1（新增）：公開端點 `/api/system/branding`（公司名稱／簡稱；統編只在帶有效登入時回，ROADMAP A8d）
- L1（新增）：`helpers.module_registry.register_key_source`／`dynamic_modules`／`known_keys`——動態權限 key 來源（已發布的自訂模組各一個 `custom.<key>`）；權限目錄與 `refuse_unknown_new_keys` 都認得；來源失敗 ⇒ 擋下新授權
- L1（行為）：備份清理 S-CC07 N-1——最新一份（今天以外）距今天超過 2 天（週／月層 2 個週期）⇒ 暫停清理、寫 `.prune_hold`、每輪告警
- L1（新增）：`core.definitions`——定義文件庫（CUSTOMIZATION-SPEC §3.5；P5 版面、P2 輸出版型覆寫、P4 自訂欄位、P8 自訂模組共用）：`save_draft`／`get`／`versions`／`publish`（先過驗證器，不過不發布並回帶位置的問題）／`restore`（不改歷史，再發布成新版）／`resolve`（role＞company＞程式預設）／`diff`（JSON 路徑）／`validate`、`register_validator`、`register_default`、`KINDS`、`DefinitionError`；表 `ui_definitions`（T1，每日 JSON 匯出，demo 清空）
- L1（新增）：`core.migrations`——每模組獨立版本的 migration 執行器（CORE-SPEC §6）：`register`／`registered`／`current_version`／`run_all`（版本須從 1 連續；每支跑完立刻記版本，中途失敗停在上一版）；`init_db` 在 `module_schema_versions` 之後執行；`core` v1＝`ui_definitions`。V9 基準 v116 不動
- L1（新增）：`helpers.custom_fields`——自訂欄位命名空間（P4，§3.6）：`validate_definition`（帶位置；不可與核心欄位同名）、`clean`（型別正規化、必填、預設值；未定義的鍵丟掉並回報）、`TYPES`／`DATA_CLASSES`／`KEY_RE`
- L1（新增）：`helpers.doc_template.problems()`（同 `validate`，每一項帶 JSON 路徑）；開票申請憑據輸出改依「單據凍結的版本＞公司最新發布版＞程式預設」套版，讀定義失敗 ⇒ 程式預設＋WARNING
- L1（新增）：API `/api/definitions/{kind}/{key}`（GET、`/draft` PUT、`/validate`、`/publish`、`/versions/{v}`、`/diff`、`/restore/{v}`、`/resolve`）、`/api/definitions/output_template/{key}/preview`（樣本資料預覽）；僅超級管理員
- L1（新增）：`helpers.formula`——安全公式（`check` 回錯誤位置、`evaluate`、`references`、`evaluation_order` 循環偵測；空值不等於 0、除以 0 回報；不允許屬性／索引／次方／其他函式）
- L1（新增）：`helpers.custom_modules`——自訂模組引擎（P8）：`validate_module`（欄位、公式、參照、流程可達性、簽核層與條件、輸出版型，每項帶位置）、文件式單據 `create_record`／`update_record`（只限起始狀態）／`transition`／`decide`（分層簽核沿用 `helpers.tiered_approval`，層可帶條件公式）／`get_record`／`list_records`／`render_output`／`rebuild_index`（欄位索引不匯出，從單據重建）；單據凍結在建立時的定義版本；通知與事件 `custom_module.transitioned` 在 commit 之後才送；個資（F2）欄位在分流接上前一律拒絕；`register_ref_target`
- L1（新增）：core migration v2——`custom_records`／`custom_record_values`（欄位索引）／`custom_record_counters`／`custom_record_log`（T1，每日 JSON 匯出，demo 清空）；API `/api/custom-modules`（清單、能力目錄、公式檢查、編號預覽、輸出預覽）與 `/api/custom/{key}/…`（單據 CRUD、轉換、核准／退回、輸出 HTML／PDF）；`pdf_gen.html_to_pdf_bytes()`
- L1（新增）：自訂模組單據讀取帶回該版定義（`definition`）；`GET /api/custom/{key}/meta?version=`

## 1.10 — 2026-09-26
> 主持（稽核 D 主持份 H-M1／H-S1／H-S2 與確認時的 N-1／N-2）。介面不變，只有行為。
- L1（修改行為，介面不變）：`core.events.publish` 給每個訂閱者 JSON 來回的完整副本（原本 `dict(payload)` 是淺拷貝，巢狀資料會被訂閱者改掉，發佈方的物件也會）；payload 必須是 JSON 可序列化、而且來回不變的值（tuple、非字串的鍵都算違約）；同一條執行緒還開著 `begin_write` 的寫交易時發佈也算違約（測試 raise、產品記 ERROR 照送）；訂閱者超過 0.2 秒記 WARNING
- L1（修改行為，介面不變）：`core.txn.begin_write` 的交易狀態多記一個 `thread`（給 core.events 判斷用）

## 1.9 — 2026-09-26
> A（STATES-PLATFORM §9 修正：路由衝突、停用清單讀不到、模組入口與提示頁、地圖、授權變更提示）。
- L0（新增）：`core.loader.mount_modules(app)`——在所有 L1 router 之後掛模組路由；模組任一條路由會被既有路由（L1 或先掛的模組）完整接住 ⇒ 該模組整個不掛、記 failed＋原因（P-LD-07）；以 starlette `route.matches()` 探測，FastAPI 新舊版（0.133／0.141）都成立；router 讀不出路徑 ⇒ 不掛；`main.py` 的模組排程與啟動提示移到它之後
- L0（新增）：`core.registry.unload(key, reason)`、`set_disabled_list()`／`disabled_list()`（snapshot／restore 一併涵蓋）；`core.loader.ALL`、`DISABLED_REASON`、`load_all(…, disabled_reason=…)`（全部停用＋原因）
- L1（新增）：`core.paths.modules_disabled_cache(db_path)`（主庫旁 `<db>.modules_disabled.json`，F4）；`helpers.module_switches.read_disabled_list()` → `DisabledList(keys, all_disabled, source, message)`：讀不到 ⇒ 有上限重試 ⇒ 沿用快取 ⇒ 沒有快取就全部停用（P-SW-05）；內容壞掉同樣處理（P-SW-07）；`set_enabled` 同步更新快取；`read_disabled_at_startup()` 保留（讀不到且沒有快取時改回所有模組資料夾名，不再回空集合）
- L1（新增）：API `/api/system/modules/availability`（登入即可，`{key: {state, label, name}}`，不回原因）側欄改用它；舊的 `/api/system/modules/unavailable-pages` 保留相容（同一主版號內不刪，列不出不在安裝包的模組，新程式不要用）；`/api/system/modules` 加 `disabledList`、各列 `licenseChanged`／`licenseNote`（P-SW-03）
- L1（修改行為）：地圖在標案雷達未載入時不列標案，`sources` 標 `module_not_loaded`（P-DT-01）

## 1.8 — 2026-09-26
> rebase 時 1.7 已被 R 使用 ⇒ 1.8。稽核 X-9b O-9（使用者表單裁示）與 STATES-DATA-OPS S-CU12。介面不變，只有行為。
- L1（修改行為，介面不變）：`archive._F2_FIELDS` 加 `協力廠商`（`vendor_contractors.data_json` 的戶名／帳號／存摺影像），`承攬付款憑據` 另加 `snapshot_json` 最上層同三鍵——協力廠商（承攬商本身）的帳戶一律當個資：一般每日／月 JSON 拿掉，完整列只進個資資料夾（O-9）
- L0（修改行為，介面不變）：`core.upgrade.CONFIG_FILES` 拿掉 `.build_commit` ⇒ 歸類成程式：轉換隨新版包安裝、兩種回滾還原成 V9 那一份；原本轉換後版本端點仍回 V9 的 commit（S-CU12）

## 1.7 — 2026-09-25（R）
> `core.registry.CORE_VERSION` 1.6 → 1.7（G1 快照要求升次版號；R 對 `core/registry.py` 只改這一行）。
- L1（新增）：`helpers.legal_params` 法規參數服務（R1，CUSTOMIZATION-SPEC §9.1）——`load_versions`／`save_versions`／`rules_for_date`／`rules_by_version`／`validate_version(s)`／`frozen_changes`／`year_status`／`minimum_wage_mismatch`／`today`；零稅率／免稅依據 `TAX_BASIS_OPTIONS`／`tax_basis_error`／`tax_basis_label`（R2，§9.2）
- L1（新增）：`helpers.privacy_notice` 個資蒐集告知（R3，§9.3）——`TEMPLATE`／`template_for`／`notice_text`／`current_notice`／`notice_hash`／`merge_ack`／`get_ack`／`record_ack`
- L1（新增）：端點 `/api/legal-params/tax-rules`（GET／PUT）、`/api/legal-params/tax-basis-options`、`/api/legal-params/privacy-notice`；頁面 `legal-params.html`；前端元件 `static/privacy-notice.js`
- L1（新增欄位）：`company_profile.privacy_notice`；設定鍵 `tax_rules_versions`、`privacy_notice_acks`

## 1.6 — 2026-09-25
> 稽核 X-9b（AUDIT-X-9b-upgrade-paths-pii.md）與 X-C-batch1 B-2 的修正。只有新增與相容擴充（選填參數）。
- L0（新增）：`core.upgrade.settings_changes()`——轉換後驗證與新版啟動後比對共用的設定判準（補空值不算改寫，含「鍵在、值是空字串」）（M-1、B-2）
- L0（新增）：`core.upgrade.data_changes()`；`rollback(..., info=None)`／`verify_rollback(..., info=None)`（相容擴充）——回滾只核對備份時就在的資料檔，新增的列成資訊、本機快照輪替不算失敗（M-2）
- L0（新增）：`core.upgrade.PACKAGE_DEFAULT_CONFIG`、`sync_package_default_config()`；`core.paths.AUTOSTART_BAT`——`autostart.bat` 歸類為設定，轉換保留機器版本；`verify_conversion` 另比設定檔（M-4）
- L0（新增）：`core.upgrade.check_backup()`——轉換與回滾動手前重驗備份（安裝根目錄、逐檔雜湊、試還原）（S-1）；`TOOL_LOG_NAMES`（試還原可重跑）、demo 庫 integrity、讀不了的庫列成問題（S-2、O-7）
- L0（新增）：`core.upgrade.table_digests()`、`logical_digest()`、`record_post_conversion()`、`changes_since_conversion()`、`has_changes()`、`POST_CONVERT_NAME`——「只准新增」驗內容；完整回滾前列出轉換後才寫入的資料；完整回滾以備份時原檔的邏輯內容驗收（S-3、O-1）
- L0（新增）：`core.upgrade.manifest_sha256()`（O-2）；`replace_program()` 回傳多 `removed_without_replacement`（S-7）
- L1（新增）：`archive.PiiFolderMissing`；個資資料夾只准往下逐層建（`os.mkdir`），根目錄不在 ⇒ 失敗並告警，不建回來（S-5）
- L1（行為）：`archive._F2_FIELDS` 加 `承攬付款憑據`（`snapshot_json.personnel[]` 的外包人員帳戶），一般份拿掉、完整列進個資資料夾；`merge_general_and_pii` 支援（M-3）
- CLI `tools/platform/upgrade.py`：驗證不過印建議回滾與指令（不自動回滾）；回滾後自動啟動 V9 ping、只印結果（`--ping-port`／`--no-ping`；exit 6／7）（CORE-SPEC §9b 主持裁示）

## 1.5 — 2026-09-25
> X9（AUDIT-X-9c 修正：A-2 守門不綁 L2 模組、A-3 授權檢查未啟用要看得到、B-1～B-4、C-4）。
- L0（新增）：`core.loader.MODULES_PACKAGE`；`load_all()` 的 `modules_dir`／`package` 沒給時讀**呼叫當下**的 `MODULES_DIR`／`MODULES_PACKAGE`（原本綁在預設參數上，子行程守門換不掉）
- L0（新增）：`core.loader.start_schedulers()`——啟動已載入模組的排程、回傳呼叫數；`main.py` 在排程閘門內改呼叫它（子行程守門驗同一條路）
- L0（新增）：`core.registry.set_state(…, note=…)`；狀態多一個 `note` 欄位（不是問題但要讓人看到的狀態，例：`授權檢查未啟用`）。`reason` 維持「非空＝有問題」；`/api/system/modules` 每列帶 `note`，模組管理頁顯示在狀態格＋頂端提示
- L1（修改行為，介面不變）：`helpers.licensing.module_licensed()` 的金鑰 `modules` 不是 `list[str]` ⇒ 未授權（原本字串會變成子字串比對）
- L1（修改行為，介面不變）：`helpers.module_switches.set_enabled()` 讀改寫在同一個 `BEGIN IMMEDIATE` 交易裡（同時切換不會互相蓋掉）

## 1.4 — 2026-09-25
- L1（新增）：`helpers.doc_template`——輸出引擎（P2，CUSTOMIZATION-SPEC §3.4）：`render(template, view, parts)`、`render_blocks`、`load_default(key)`、`validate(template, sample_view)`、`BLOCKS`（積木目錄 v1）、`THEMES`、`TemplateError`；預設版型 `helpers/output_templates/invoice_voucher.json`；`pdf_gen._build_invoice_voucher_html(v, template=None)` 可吃覆寫版型

## 1.3 — 2026-09-25
> C（A11／STATES／A8c 合回，G1 快照要求升次版號）。
- L1（新增）：串接點 IP-5 `daily_task.external`（M12 提供，M01 取用）、IP-6 `calendar.writeback`（M01／M03／M05 提供，L1 `helpers.google_calendar` 取用）；L1 行事曆不再直接寫 L2 表（ROADMAP A11）
- L1（新增）：`db.quick_check(path)`、`core.upgrade.quick_check(path)`；每日快照與啟動做完整性檢查；備份清理「至少保留最新 7 份」（`archive.PRUNE_KEEP_NEWEST`）；月備份同日重試＋上月缺漏告警；備份告警管道各自獨立、寄成功才節流（STATES-DATA-OPS S-CD02／CC07／CC06／CN03／CU10）
- L1（新增）：`helpers.company_identity.contact_line`／`footer_line`／`name_pair`／`short_name`（`pdf_gen._short_name` 改為引用它，唯一來源）；報表與網路規劃不再寫死公司聯絡資料（ROADMAP A8c）
- L1（新增）：`helpers.company_identity.contact_info_parts()`；公司名別名加 `name`、電話／email 以設定頁「聯絡方式」為最後後備（設定頁最上方欄位原本讀不到）
- L0（新增）：`core.upgrade.fill_company_profile_blanks()`／`V9_COMPANY_DEFAULTS`（轉換時只補空值、只補本公司安裝）；`archive.PRUNE_KEEP_NEWEST`

## 1.2 — 2026-09-25
> `core.registry.CORE_VERSION` 1.1 → 1.2 由 A 在 9c 分支一併修改（主持裁示）。
- L0（新增）：`core.upgrade`——V9 → 新版升級轉換與回滾（預檢／備份＋試還原比對雜湊／轉換只准新增／驗證／完整回滾與只回程式）；CLI `tools/platform/upgrade.py`、演練 `tools/platform/upgrade_drill.py`；操作手冊 `docs/platform/UPGRADE-RUNBOOK.md`（CORE-SPEC §9b）；安裝目錄以外的 `*_pdf_base_path` 只記摘要（檔案數／大小／mtime），驗證只比不變少，連不到＝警告
- L1（新增）：`core.events` 事件匯流排（P6，CUSTOMIZATION-SPEC §6）——`declare`／`publish`／`subscribe`／`declarations`／`recent_failures`；訂閱者隔離、給副本、契約檢查（測試嚴格、產品記 ERROR 照送）；`snapshot`／`restore` 供測試
- L0（新增）：`core.registry.snapshot()`／`restore()`——測試夾具保存與還原整份登錄表（不自己列舉內部表）
- L0（新增，CORE-SPEC §9c ②③）：`core.loader.load_all(license_check=…, disabled=…)`（優先順序：不在包內＞未授權＞管理者停用；②③ 都不 import 該模組）；`core.registry.set_state()`／`module_states()`／`STATES`（loaded／unlicensed／disabled／failed，附原因與頁面）
- L1（新增）：`helpers.licensing.module_licensed()`／`module_license_check()`（授權單位＝模組 `license_key`，`*` 全開；開關關閉＝不檢查）；`helpers.module_switches`（`system_settings.modules_disabled`，重啟後生效）；API `/api/system/modules`（superadmin）、`/api/system/modules/unavailable-pages`

## 1.1 — 2026-09-25
- L0（新增，MODULE-GUIDE §2 升次版號）：`core.registry.provide()`（尚未搬進 modules/ 的模組在匯入時登記提供者）、`single_provider()`（沒有 ⇒ None；多個 ⇒ RuntimeError）；首個串接點 IP-1 `dispatch.row`（INTEGRATION-POINTS.md）
- L0（修正，介面不變）：`core.source_tree.product_files()` 排除 backend 根目錄的 `conftest.py`（測試設定自 `tests/` 上移到 `backend/` 後，不可被當成產品碼掃描）

## 1.0 — 2026-09-25
- L0：模組載入器 `core.loader`、登錄表 `core.registry`（ModuleSpec／RuntimeSwitch／providers）、守門掃描範圍 `core.source_tree`（a150e52a）
- L1：寫入交易 `core.txn`（begin_write／write_txn／watch_reads）（7db88381）
- L1：路徑解析層 `core.paths`；主庫不存在即拒絕啟動，除非設 `MOTRIX_CREATE_NEW_DB=1`（bef3e25d、41151687）
- L1：V9 基準 v116 比對；`module_schema_versions`（c057832a）
- L1：資料列權限 `helpers.row_access`（ee5dab65、50e8c2cc、0411f818）
- L1：通知信旗標（`.no_email_send`／`MOTRIX_EMAIL_SEND`）（19fdae7e）
