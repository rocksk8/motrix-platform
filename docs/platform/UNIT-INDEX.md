# UNIT-INDEX：L0／L1 單位總索引

由 `python tools/platform/unit_index.py` 產生，**勿手改**；`--check` 驗證（守門 `tests/platform/test_unit_cards.py`）。格式與規則見 PLAYBOOK §G2。
新的 session 先讀這份，再決定要開哪個檔；要看不變式與注意事項，只讀該檔開頭的單位卡。

- 介面＝G1 快照中的頂層公開名稱數；使用者＝dep_scan import 圖中直接 import 它的單位數（不含測試）。
- 用途標「（無單位卡）」＝取自 docstring 第一行，尚未補卡；改到該檔時守門會要求補上。

單位 81 個；有單位卡 31 個。

| 單位 | 層 | 用途 | 介面 | 使用者 | 契約題 |
|---|---|---|---:|---:|---|
| `plat:catalog` | L0 | 能力目錄（CUSTOMIZATION-SPEC P1；CORE-SPEC §7 端點登錄表的擴充）。 | 13 | 3 | `tests/platform/test_platform_catalog.py` |
| `plat:customization` | L0 | L0 模組描述：可自訂點（CUSTOMIZATION-SPEC P3；§8.2 排版器需求）。 | 12 | 2 | `tests/platform/test_platform_catalog.py` |
| `plat:definitions` | L0 | 定義文件庫：草稿、版本、差異、還原（CUSTOMIZATION-SPEC §3.5）。 | 25 | 8 | `tests/test_definitions_store_2026_09_25.py` |
| `plat:events` | L0 | L1 事件匯流排（CUSTOMIZATION-SPEC §6，ROADMAP P6）。 | 9 | 2 | `tests/platform/test_core_events.py` |
| `plat:loader` | L0 | L0 模組載入器：掃 `modules/*/module.json`，相容且匯入成功的才登錄。 | 9 | 4 | `tests/platform/test_core_loader.py` |
| `plat:menu` | L0 | 選單由登錄表產生（階段 C／C3，docs/platform/STAGE-C-DESIGN.md §4）。 | 14 | 2 | `tests/platform/test_menu.py` |
| `plat:migrations` | L0 | 每模組獨立版本的 migration（CORE-SPEC §6）。 | 6 | 3 | `tests/test_definitions_store_2026_09_25.py`、`tests/platform/test_migration_incomplete.py` |
| `plat:mounts` | L0 | 內建頁面開放給自訂模組的「掛載點」（建構器方案 B；設計 docs/platform/plans/BUILDER-B-DESIGN.md）。 | 6 | 3 | `tests/test_builder_b_mounts_2026_10_01.py` |
| `plat:pages` | L0 | 頁面對照與提供（階段 C／C1，docs/platform/STAGE-C-DESIGN.md §3）：`/pages/<檔名>` ⇒ 實體檔、提示頁或 404。 | 15 | 2 | `tests/platform/test_core_pages.py` |
| `plat:paths` | L0 | 資料位置的唯一來源（DATA-COMPAT §4 A-1，CORE-SPEC「使用者裁示」原地讀取）。 | 45 | 25 | `tests/platform/test_core_paths.py`、`tests/platform/test_no_file_relative_data_paths.py` |
| `plat:registry` | L0 | L0 模組登錄表（docs/platform/CORE-SPEC.md §4、§5）。 | 21 | 75 | `tests/platform/test_core_loader.py`、`tests/platform/test_module_selection.py` |
| `plat:source_tree` | L0 | 守門測試要掃的原始碼範圍：唯一來源。 | 11 | 0 | `tests/platform/test_core_loader.py` |
| `plat:txn` | L0 | L1 寫入交易：寫鎖、區塊保證、「拿鎖之後讀過」的觀測（2026-09-25 自 modules/case/quotations.py 下沉）。 | 7 | 32 | `tests/platform/test_core_events.py`、`tests/test_begin_only_via_begin_write_2026_09_25.py` |
| `plat:upgrade` | L0 | V9 → 新版 升級轉換與回滾的核心（CORE-SPEC §9b）。L0 工具，不是業務模組。 | 50 | 0 | `tests/platform/test_core_upgrade.py` |
| `core:archive` | L1 | Google Drive archive helpers: real-time, daily, and weekly backups + local SQLite snapshots.（無單位卡） | 24 | 9 | — |
| `core:backup_job` | L1 | MOTRIX ERP 獨立備份腳本（無單位卡） | 1 | 0 | — |
| `core:cloud_storage` | L1 | Pluggable cloud backup storage backend (2026-09-07, architecture map §6.4).（無單位卡） | 9 | 2 | — |
| `core:db` | L1 | DB connection factory, schema initialisation, and numbered migrations.（無單位卡） | 29 | 116 | — |
| `core:heartbeat_job` | L1 | Independent heartbeat pinger: confirms local ERP is responding, then pings an（無單位卡） | 1 | 0 | — |
| `core:main` | L1 | MOTRIX ERP — FastAPI 後端（無單位卡） | 11 | 0 | — |
| `core:pdf_gen` | L1 | Server-side PDF generation via Edge headless print.（無單位卡） | 19 | 16 | — |
| `core:photos` | L1 | Photo upload processing: EXIF GPS extraction and watermarking.（無單位卡） | 2 | 2 | — |
| `core:trail` | L1 | 操作軌跡（`user_request_log`）的共用設定，以及把路徑翻成人話的對照表。（無單位卡） | 23 | 2 | — |
| `helper:approval_queue` | L1 | 「待我簽核」佇列與轉簽的共用形狀（L1；M01-PLAN §3-7，2026-09-26）。（無單位卡） | 11 | 18 | — |
| `helper:attachment_search` | L1 | 附件目錄的搜尋共用件（`attachments.catalog` 契約 v1 的 `search`／`count`；附件目錄 P3， | 10 | 9 | `tests/test_filehub_search_2026_09_30.py` |
| `helper:audit` | L1 | Audit log and in-app notification helpers.（無單位卡） | 11 | 74 | — |
| `helper:auth` | L1 | Password hashing, session validation, weak-password detection.（無單位卡） | 28 | 98 | — |
| `helper:branding` | L1 | 品牌圖檔（主 LOGO／深色底 LOGO／favicon）：上傳驗證、存放、讀取時回預設。 | 16 | 2 | `tests/test_branding_2026_09_27.py` |
| `helper:build_info` | L1 | 這個**行程**載入的是哪一份程式碼（`BR1`）。（無單位卡） | 3 | 2 | — |
| `helper:business_days` | L1 | L1 工作日／假日判斷（第44班：自 M11 標案雷達 `calendar_tw.py` 提升為 L1 共用，供任何模組用——例如 M01 預定付款日提醒、M11 不寄信日）。**純函式，不連網、不讀時鐘（日期由呼叫端給）。**（無單位卡） | 9 | 2 | — |
| `helper:calendar_sync` | L1 | 日期型行事曆事件的每日對帳（L1；MAIL-CAL 階段 2：保固到期／區間事項結束／專案預計完成）。 | 4 | 2 | `tests/test_notify_matrix_phase2_2026_10_06.py` |
| `helper:case_access` | L1 | L1 案件存取守門（主持裁示 2026-09-26，DEPENDENCY-MAP §3 #2「案件可見性規則 → L1 權限」）。（無單位卡） | 20 | 25 | — |
| `helper:case_roles` | L1 | 案件角色（caseRecord.roles 的 filler／sales／executor）的兩種形狀（CM3，2026-09-24）。（無單位卡） | 5 | 3 | — |
| `helper:company_identity` | L1 | §9 QL · 一份單據要印的「公司身分」。（無單位卡） | 19 | 14 | — |
| `helper:company_setup` | L1 | 本公司資料設定閘門：「這個安裝的本公司資料有沒有人確認過」（docs/platform/COMPANY-SETUP-GATE.md §3、§4.3、§6）。 | 66 | 7 | `tests/test_company_setup_core_2026_09_28.py`、`tests/test_company_setup_cli_2026_09_28.py`、`tests/test_company_setup_gate_2026_09_28.py`、`tests/test_company_setup_output_gate_2026_09_28.py` |
| `helper:custom_builder_support` | L1 | 建構器底層支援（建構器第三輪 S2.5／S3／S5，CORE 1.72，只增）。 | 21 | 5 | `tests/test_builder_support_2026_09_30.py` |
| `helper:custom_def_review` | L1 | 自訂模組「定義」的送審流程（建構器第三輪 S4，2026-09-30；使用者：定義送審→退回→修改重送，每次 v1→v2…，退回要填原因）。 | 13 | 2 | `tests/test_builder3_def_review_2026_09_30.py` |
| `helper:custom_fields` | L1 | 自訂欄位命名空間（P4，CUSTOMIZATION-SPEC §3.6）。（無單位卡） | 10 | 2 | — |
| `helper:custom_files` | L1 | 自訂模組附件（file／image 欄位，建構器第三輪 S2；core migration v4 `custom_record_files`）。 | 16 | 3 | `tests/test_builder3_files_2026_09_30.py` |
| `helper:custom_finance` | L1 | 自訂模組的金流（收入／支出）串接（建構器第三輪 S2.5；使用者 2026-09-30：「只要有收入、支出項，都需要跟營運報表或是相關模組數據串接」）。 | 10 | 6 | `tests/test_builder3_finance_2026_09_30.py` |
| `helper:custom_history` | L1 | 自訂模組單據的送簽修訂紀錄（建構器第三輪 S5，2026-09-30；使用者：單據送簽→退回→修改重送，單號加 -R1、-R2 並保留各版內容，可比對差異）。 | 5 | 2 | `tests/test_builder3_history_2026_09_30.py` |
| `helper:custom_module_delete` | L1 | 刪除自訂模組（建構器首頁「刪除模組」）。（無單位卡） | 3 | 1 | — |
| `helper:custom_modules` | L1 | 自訂模組引擎（P8，CUSTOMIZATION-SPEC §1／§3.1／§8.1）：定義是資料，不是程式。（無單位卡） | 55 | 7 | — |
| `helper:daily_checks` | L1 | L1 每日 08:00 檢查執行器（2026-09-26；取代 routers/daily_tasks.py::schedule_overdue_check）。（無單位卡） | 3 | 1 | — |
| `helper:dates` | L1 | Date arithmetic utilities.（無單位卡） | 5 | 16 | — |
| `helper:doc_render` | L1 | L1 單據輸出的公開入口 `render_document`（A2-0 #7）：版型＋單據視圖 ⇒ 完整 HTML（交給 `html_to_pdf_bytes` 轉 PDF）。 | 1 | 2 | `tests/platform/test_doc_render_2026_10_01.py` |
| `helper:doc_template` | L1 | L1 輸出引擎：版型定義（資料）＋單據視圖（資料）⇒ HTML（P2，CUSTOMIZATION-SPEC §3.4）。（無單位卡） | 20 | 8 | — |
| `helper:duty_roles` | L1 | 職責角色化 R1（設計：docs/platform/plans/DUTY-ROLES-DESIGN.md；使用者 2026-10-06 裁示 Q1–Q12、N1–N4）。 | 17 | 2 | `tests/test_duty_roles_r1_2026_10_06.py`、`tests/test_duty_roles_equivalence_2026_10_06.py` |
| `helper:edit_log` | L1 | 逐筆編寫紀錄（`FN4②`）—— **缺「改前值」就寫不進去**。（無單位卡） | 5 | 5 | — |
| `helper:email_notify` | L1 | External email notifications via SMTP (Gmail App Password).（無單位卡） | 71 | 43 | — |
| `helper:errors` | L1 | 例外訊息的去處（`EM3`）：畫面只給代碼，例外全文進 log。（無單位卡） | 1 | 11 | — |
| `helper:expense_types` | L1 | 費用單據的「類型定義」（A2-2）：請購單／採購單／差旅費用請款單／零用金支付單各是一份 `expense_type` 定義。 | 14 | 5 | `tests/platform/test_expense_types_2026_10_01.py` |
| `helper:financial_mask` | L1 | 案件金額欄位遮蔽（CM13，2026-09-24 使用者裁示「要，後端移除金額欄位」）。（無單位卡） | 16 | 8 | — |
| `helper:formula` | L1 | 安全的公式（CUSTOMIZATION-SPEC §1「積木式、不能寫程式」、§8.1 ②「公式語法檢查回傳錯誤位置」）。（無單位卡） | 9 | 3 | — |
| `helper:geo` | L1 | 地理查詢：地址 → 座標（OSM／Nominatim），以及兩點間的直線距離。（無單位卡） | 80 | 5 | — |
| `helper:gl_status` | L1 | [單位] helper:gl_status    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版） | 2 | 3 | `tests/test_gl_source_status_2026_09_30.py` |
| `helper:google_calendar` | L1 | Google 行事曆整合 — Phase 1（系統 → 行事曆，push only，2026-08-21）。（無單位卡） | 19 | 12 | — |
| `helper:legal_params` | L1 | L1 法規參數服務（R1；規格 CUSTOMIZATION-SPEC §9.1）。（無單位卡） | 27 | 32 | — |
| `helper:licensing` | L1 | 授權金鑰核心（2026-09-21，細線 1 第 1、2 步）。（無單位卡） | 13 | 4 | — |
| `helper:mail_types` | L1 | L1 信件類型登記表（CORE-SPEC「使用者裁示」信件與通知的收件人、用語，2026-09-26）。（無單位卡） | 13 | 16 | — |
| `helper:map_overlays` | L1 | L1 地圖覆蓋層（串接點 IP-101 `map.overlay`；docs/platform/LODGING-NEARBY.md §3.6.1，D 稽核 LG-M1／LG2-S1～S3）。 | 5 | 2 | `tests/test_map_overlay_contract_2026_09_28.py`、`tests/test_e2e_map_overlay_contract_2026_09_28.py` |
| `helper:module_registry` | L1 | 權限模組的**唯一來源**（B7，2026-09-24 使用者裁示「整併成一份」）。（無單位卡） | 11 | 8 | — |
| `helper:module_startup` | L1 | 啟動時載入 L2 模組：main.py 與「只做 init_db 的工具」（乾跑 migration、V9→新版轉換）共用同一段。 | 3 | 1 | `tests/platform/test_module_startup.py` |
| `helper:module_switches` | L1 | CORE-SPEC §9c ③ 管理者啟停：`system_settings.modules_disabled`（模組 key 陣列）。（無單位卡） | 9 | 2 | — |
| `helper:notification_prefs` | L1 | Per-user email notification opt-out list.（無單位卡） | 5 | 4 | — |
| `helper:notify_matrix` | L1 | 通知矩陣（信件 × 行事曆）的對照登記（L1；MAIL-CAL 階段 1，設計 docs/platform/plans/MAIL-CAL-MERGE-DESIGN.md）。 | 10 | 2 | `tests/test_notify_matrix_2026_10_05.py` |
| `helper:part_catalog` | L1 | 料件分類代碼表（L1；DEPENDENCY-MAP §3 #17）。（無單位卡） | 2 | 2 | — |
| `helper:prefill_sources` | L1 | 表單「自動帶入」來源的唯一登記處（L1；表單設計器的下拉、定義驗證、伺服器端取值都讀這一份）。（無單位卡） | 8 | 3 | — |
| `helper:privacy_notice` | L1 | L1 個資蒐集告知（R3；規格 CUSTOMIZATION-SPEC §9.3；個人資料保護法 §8 I）。（無單位卡） | 23 | 13 | — |
| `helper:procurement` | L1 | 採購前置時間與採購建議狀態的判定（2026-09-21，第 3 輪）。（無單位卡） | 11 | 3 | — |
| `helper:receivables` | L1 | L1 薄殼（淘汰中）：收款明細與銷項發票清單——**資料在 M05 應收應付**，這裡只轉呼叫它的 provider。（無單位卡） | 4 | 0 | — |
| `helper:recognition_basis` | L1 | 權責／現金口徑的純標籤（L1；2026-09-26 自 M01 modules/case/recognition.py 下沉，M01-PLAN §3-6）。（無單位卡） | 4 | 3 | — |
| `helper:row_access` | L1 | L1 資料列權限（row-level access）：一份宣告，同時產生「單筆判斷」與「SQL 過濾」。（無單位卡） | 8 | 10 | — |
| `helper:settings` | L1 | System settings CRUD (system_settings table).（無單位卡） | 2 | 43 | — |
| `helper:startup` | L1 | Server startup checks: admin seed, weak-password scan, session cleanup, Edge path.（無單位卡） | 23 | 10 | — |
| `helper:storage_locations` | L1 | 儲存位置：雲端存檔根目錄、個資資料夾、更新交付資料夾的**唯一**解析處（CORE-SPEC 裁示表「儲存位置可設定」，2026-09-28）。 | 13 | 2 | `tests/platform/test_storage_locations_2026_09_28.py` |
| `helper:system_checks` | L1 | L1 系統健康的每日檢查（2026-09-26 自 routers/daily_tasks.py 搬出，M12 搬遷前置）。（無單位卡） | 8 | 2 | — |
| `helper:tax_calc` | L1 | 稅額純函式（L1；2026-09-26 自 M01 `helpers/quotations.py` 下沉，主持核准「T」）。（無單位卡） | 12 | 8 | — |
| `helper:tiered_approval` | L1 | 共用的 tiers 依序簽核純邏輯（2026-08-22）。（無單位卡） | 31 | 33 | — |
| `helper:uploads` | L1 | 通用「已開立/已回簽單據」附件上傳（2026-08-24）：報價單回簽、出貨單回簽、（無單位卡） | 19 | 28 | — |
| `helper:xlsx_out` | L1 | L1 輸出：Excel 樣式、公式注入防護、匯出速率限制（ROADMAP A8／DEPENDENCY-MAP §3 #10 #13）。（無單位卡） | 15 | 11 | — |
