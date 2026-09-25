# L0／L1 底層 更新紀錄

> 底層穩定契約（MODULE-GUIDE §2）：同一主版號內只准新增。版本＝`core.registry.CORE_VERSION`。

## 1.2 — 2026-09-25
> `core.registry.CORE_VERSION` 1.1 → 1.2 由 A 在 9c 分支一併修改（主持裁示）。
- L1（新增）：串接點 IP-5 `daily_task.external`（M12 提供，M01 取用）、IP-6 `calendar.writeback`（M01／M03／M05 提供，L1 `helpers.google_calendar` 取用）；L1 行事曆不再直接寫 L2 表（ROADMAP A11）
- L1（新增）：`db.quick_check(path)`、`core.upgrade.quick_check(path)`；每日快照與啟動做完整性檢查；備份清理「至少保留最新 7 份」（`archive.PRUNE_KEEP_NEWEST`）；月備份同日重試＋上月缺漏告警；備份告警管道各自獨立、寄成功才節流（STATES-DATA-OPS S-CD02／CC07／CC06／CN03／CU10）
- L1（新增）：`helpers.company_identity.contact_line`／`footer_line`／`name_pair`／`short_name`（`pdf_gen._short_name` 改為引用它，唯一來源）；報表與網路規劃不再寫死公司聯絡資料（ROADMAP A8c）
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
