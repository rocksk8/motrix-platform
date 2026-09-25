# L0／L1 底層 更新紀錄

> 底層穩定契約（MODULE-GUIDE §2）：同一主版號內只准新增。版本＝`core.registry.CORE_VERSION`。

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
