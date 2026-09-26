# UNIT-INDEX：L0／L1 單位總索引

由 `python tools/platform/unit_index.py` 產生，**勿手改**；`--check` 驗證（守門 `tests/platform/test_unit_cards.py`）。格式與規則見 PLAYBOOK §G2。
新的 session 先讀這份，再決定要開哪個檔；要看不變式與注意事項，只讀該檔開頭的單位卡。

- 介面＝G1 快照中的頂層公開名稱數；使用者＝dep_scan import 圖中直接 import 它的單位數（不含測試）。
- 用途標「（無單位卡）」＝取自 docstring 第一行，尚未補卡；改到該檔時守門會要求補上。

單位 58 個；有單位卡 13 個。

| 單位 | 層 | 用途 | 介面 | 使用者 | 契約題 |
|---|---|---|---:|---:|---|
| `plat:catalog` | L0 | 能力目錄（CUSTOMIZATION-SPEC P1；CORE-SPEC §7 端點登錄表的擴充）。 | 13 | 3 | `tests/platform/test_platform_catalog.py` |
| `plat:customization` | L0 | L0 模組描述：可自訂點（CUSTOMIZATION-SPEC P3；§8.2 排版器需求）。 | 12 | 2 | `tests/platform/test_platform_catalog.py` |
| `plat:definitions` | L0 | 定義文件庫：草稿、版本、差異、還原（CUSTOMIZATION-SPEC §3.5）。 | 14 | 5 | `tests/test_definitions_store_2026_09_25.py` |
| `plat:events` | L0 | L1 事件匯流排（CUSTOMIZATION-SPEC §6，ROADMAP P6）。 | 9 | 2 | `tests/platform/test_core_events.py` |
| `plat:loader` | L0 | L0 模組載入器：掃 `modules/*/module.json`，相容且匯入成功的才登錄。 | 8 | 2 | `tests/platform/test_core_loader.py` |
| `plat:menu` | L0 | 選單由登錄表產生（階段 C／C3，docs/platform/STAGE-C-DESIGN.md §4）。 | 14 | 1 | `tests/platform/test_menu.py` |
| `plat:migrations` | L0 | 每模組獨立版本的 migration（CORE-SPEC §6）。 | 4 | 1 | `tests/test_definitions_store_2026_09_25.py` |
| `plat:pages` | L0 | 頁面對照與提供（階段 C／C1，docs/platform/STAGE-C-DESIGN.md §3）：`/pages/<檔名>` ⇒ 實體檔、提示頁或 404。 | 15 | 2 | `tests/platform/test_core_pages.py` |
| `plat:paths` | L0 | 資料位置的唯一來源（DATA-COMPAT §4 A-1，CORE-SPEC「使用者裁示」原地讀取）。 | 41 | 21 | `tests/platform/test_core_paths.py`、`tests/platform/test_no_file_relative_data_paths.py` |
| `plat:registry` | L0 | L0 模組登錄表（docs/platform/CORE-SPEC.md §4、§5）。 | 21 | 37 | `tests/platform/test_core_loader.py`、`tests/platform/test_module_selection.py` |
| `plat:source_tree` | L0 | 守門測試要掃的原始碼範圍：唯一來源。 | 11 | 0 | `tests/platform/test_core_loader.py` |
| `plat:txn` | L0 | L1 寫入交易：寫鎖、區塊保證、「拿鎖之後讀過」的觀測（2026-09-25 自 helpers/quotations.py 下沉）。 | 7 | 15 | `tests/platform/test_core_events.py`、`tests/test_begin_only_via_begin_write_2026_09_25.py` |
| `plat:upgrade` | L0 | V9 → 新版 升級轉換與回滾的核心（CORE-SPEC §9b）。L0 工具，不是業務模組。 | 48 | 0 | `tests/platform/test_core_upgrade.py` |
| `core:archive` | L1 | Google Drive archive helpers: real-time, daily, and weekly backups + local SQLite snapshots.（無單位卡） | 22 | 7 | — |
| `core:backup_job` | L1 | MOTRIX ERP 獨立備份腳本（無單位卡） | 1 | 0 | — |
| `core:cloud_storage` | L1 | Pluggable cloud backup storage backend (2026-09-07, architecture map §6.4).（無單位卡） | 9 | 2 | — |
| `core:db` | L1 | DB connection factory, schema initialisation, and numbered migrations.（無單位卡） | 28 | 64 | — |
| `core:heartbeat_job` | L1 | Independent heartbeat pinger: confirms local ERP is responding, then pings an（無單位卡） | 1 | 0 | — |
| `core:main` | L1 | MOTRIX ERP — FastAPI 後端（無單位卡） | 9 | 0 | — |
| `core:pdf_gen` | L1 | Server-side PDF generation via Edge headless print.（無單位卡） | 19 | 14 | — |
| `core:photos` | L1 | Photo upload processing: EXIF GPS extraction and watermarking.（無單位卡） | 2 | 2 | — |
| `core:trail` | L1 | 操作軌跡（`user_request_log`）的共用設定，以及把路徑翻成人話的對照表。（無單位卡） | 23 | 2 | — |
| `helper:audit` | L1 | Audit log and in-app notification helpers.（無單位卡） | 5 | 39 | — |
| `helper:auth` | L1 | Password hashing, session validation, weak-password detection.（無單位卡） | 16 | 51 | — |
| `helper:build_info` | L1 | 這個**行程**載入的是哪一份程式碼（`BR1`）。（無單位卡） | 3 | 2 | — |
| `helper:case_access` | L1 | L1 案件存取守門（主持裁示 2026-09-26，DEPENDENCY-MAP §3 #2「案件可見性規則 → L1 權限」）。（無單位卡） | 7 | 9 | — |
| `helper:case_roles` | L1 | 案件角色（caseRecord.roles 的 filler／sales／executor）的兩種形狀（CM3，2026-09-24）。（無單位卡） | 5 | 3 | — |
| `helper:company_identity` | L1 | §9 QL · 一份單據要印的「公司身分」。（無單位卡） | 14 | 7 | — |
| `helper:custom_fields` | L1 | 自訂欄位命名空間（P4，CUSTOMIZATION-SPEC §3.6）。（無單位卡） | 5 | 2 | — |
| `helper:custom_modules` | L1 | 自訂模組引擎（P8，CUSTOMIZATION-SPEC §1／§3.1／§8.1）：定義是資料，不是程式。（無單位卡） | 36 | 2 | — |
| `helper:daily_checks` | L1 | L1 每日 08:00 檢查執行器（2026-09-26；取代 routers/daily_tasks.py::schedule_overdue_check）。（無單位卡） | 3 | 1 | — |
| `helper:dates` | L1 | Date arithmetic utilities.（無單位卡） | 5 | 10 | — |
| `helper:doc_template` | L1 | L1 輸出引擎：版型定義（資料）＋單據視圖（資料）⇒ HTML（P2，CUSTOMIZATION-SPEC §3.4）。（無單位卡） | 12 | 5 | — |
| `helper:edit_log` | L1 | 逐筆編寫紀錄（`FN4②`）—— **缺「改前值」就寫不進去**。（無單位卡） | 5 | 2 | — |
| `helper:email_notify` | L1 | External email notifications via SMTP (Gmail App Password).（無單位卡） | 59 | 30 | — |
| `helper:errors` | L1 | 例外訊息的去處（`EM3`）：畫面只給代碼，例外全文進 log。（無單位卡） | 1 | 11 | — |
| `helper:financial_mask` | L1 | 案件金額欄位遮蔽（CM13，2026-09-24 使用者裁示「要，後端移除金額欄位」）。（無單位卡） | 13 | 3 | — |
| `helper:formula` | L1 | 安全的公式（CUSTOMIZATION-SPEC §1「積木式、不能寫程式」、§8.1 ②「公式語法檢查回傳錯誤位置」）。（無單位卡） | 8 | 2 | — |
| `helper:geo` | L1 | 地理查詢：地址 → 座標（OSM／Nominatim），以及兩點間的直線距離。（無單位卡） | 67 | 3 | — |
| `helper:google_calendar` | L1 | Google 行事曆整合 — Phase 1（系統 → 行事曆，push only，2026-08-21）。（無單位卡） | 11 | 6 | — |
| `helper:legal_params` | L1 | L1 法規參數服務（R1；規格 CUSTOMIZATION-SPEC §9.1）。（無單位卡） | 27 | 20 | — |
| `helper:licensing` | L1 | 授權金鑰核心（2026-09-21，細線 1 第 1、2 步）。（無單位卡） | 13 | 3 | — |
| `helper:mail_types` | L1 | L1 信件類型登記表（CORE-SPEC「使用者裁示」信件與通知的收件人、用語，2026-09-26）。（無單位卡） | 13 | 7 | — |
| `helper:module_registry` | L1 | 權限模組的**唯一來源**（B7，2026-09-24 使用者裁示「整併成一份」）。（無單位卡） | 11 | 6 | — |
| `helper:module_switches` | L1 | CORE-SPEC §9c ③ 管理者啟停：`system_settings.modules_disabled`（模組 key 陣列）。（無單位卡） | 9 | 2 | — |
| `helper:notification_prefs` | L1 | Per-user email notification opt-out list.（無單位卡） | 3 | 3 | — |
| `helper:part_catalog` | L1 | 料件分類代碼表（L1；DEPENDENCY-MAP §3 #17）。（無單位卡） | 2 | 2 | — |
| `helper:privacy_notice` | L1 | L1 個資蒐集告知（R3；規格 CUSTOMIZATION-SPEC §9.3；個人資料保護法 §8 I）。（無單位卡） | 23 | 12 | — |
| `helper:procurement` | L1 | 採購前置時間與採購建議狀態的判定（2026-09-21，第 3 輪）。（無單位卡） | 11 | 3 | — |
| `helper:receivables` | L1 | L1 薄殼（淘汰中）：收款明細與銷項發票清單——**資料在 M05 應收應付**，這裡只轉呼叫它的 provider。（無單位卡） | 4 | 0 | — |
| `helper:row_access` | L1 | L1 資料列權限（row-level access）：一份宣告，同時產生「單筆判斷」與「SQL 過濾」。（無單位卡） | 8 | 10 | — |
| `helper:settings` | L1 | System settings CRUD (system_settings table).（無單位卡） | 2 | 34 | — |
| `helper:startup` | L1 | Server startup checks: admin seed, weak-password scan, session cleanup, Edge path.（無單位卡） | 16 | 8 | — |
| `helper:system_checks` | L1 | L1 系統健康的每日檢查（2026-09-26 自 routers/daily_tasks.py 搬出，M12 搬遷前置）。（無單位卡） | 8 | 2 | — |
| `helper:tax_calc` | L1 | 稅額純函式（L1；2026-09-26 自 M01 `helpers/quotations.py` 下沉，主持核准「T」）。（無單位卡） | 9 | 7 | — |
| `helper:tiered_approval` | L1 | 共用的 tiers 依序簽核純邏輯（2026-08-22）。（無單位卡） | 28 | 18 | — |
| `helper:uploads` | L1 | 通用「已開立/已回簽單據」附件上傳（2026-08-24）：報價單回簽、出貨單回簽、（無單位卡） | 4 | 9 | — |
| `helper:xlsx_out` | L1 | L1 輸出：Excel 樣式、公式注入防護、匯出速率限制（ROADMAP A8／DEPENDENCY-MAP §3 #10 #13）。（無單位卡） | 7 | 3 | — |
