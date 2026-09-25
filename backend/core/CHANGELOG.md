# L0／L1 底層 更新紀錄

> 底層穩定契約（MODULE-GUIDE §2）：同一主版號內只准新增。版本＝`core.registry.CORE_VERSION`。

## 未發行（待主持決定是否升次版號）
- L0（新增）：`core.upgrade`——V9 → 新版升級轉換與回滾（預檢／備份＋試還原比對雜湊／轉換只准新增／驗證／完整回滾與只回程式）；CLI `tools/platform/upgrade.py`、演練 `tools/platform/upgrade_drill.py`；操作手冊 `docs/platform/UPGRADE-RUNBOOK.md`（CORE-SPEC §9b）

## 1.1 — 2026-09-25
- L0（新增，MODULE-GUIDE §2 升次版號）：`core.registry.provide()`（尚未搬進 modules/ 的模組在匯入時登記提供者）、`single_provider()`（沒有 ⇒ None；多個 ⇒ RuntimeError）；首個串接點 IP-1 `dispatch.row`（INTEGRATION-POINTS.md）

## 1.0 — 2026-09-25
- L0：模組載入器 `core.loader`、登錄表 `core.registry`（ModuleSpec／RuntimeSwitch／providers）、守門掃描範圍 `core.source_tree`（a150e52a）
- L1：寫入交易 `core.txn`（begin_write／write_txn／watch_reads）（7db88381）
- L1：路徑解析層 `core.paths`；主庫不存在即拒絕啟動，除非設 `MOTRIX_CREATE_NEW_DB=1`（bef3e25d、41151687）
- L1：V9 基準 v116 比對；`module_schema_versions`（c057832a）
- L1：資料列權限 `helpers.row_access`（ee5dab65、50e8c2cc、0411f818）
- L1：通知信旗標（`.no_email_send`／`MOTRIX_EMAIL_SEND`）（19fdae7e）
