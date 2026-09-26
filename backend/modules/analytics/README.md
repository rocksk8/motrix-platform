# M08 營運分析（analytics）

首頁儀表板的統計與圖表、營運報表（12 個頁籤與匯出）、設備／保固清單、料件彙總、每月營運報表信。
**只讀**其他模組的資料，不擁有任何表。

## 端點

| 前綴 | 內容 | 權限 |
|---|---|---|
| `/api/dashboard/*` | 首頁統計、月趨勢、支出、漏斗、營運警示、動態 | 登入；金額依 `financial_view` |
| `/api/reports/*` | 營運報表、匯出、稅務匯出、銀行對帳（出納頁用；M05 搬遷時收回） | `reports` 或 `finance`（銀行對帳：`cashier`） |
| `/api/devices` | 設備登載／保固清單 | `equipment` 或 `case_manage` |
| `/api/materials-summary` | 料件彙總 | `procurement` 或 `case_manage` |

⚠ `/api/reports/t100-export/*` 由 M06 `accounting_export` 提供（同一個前綴、不同路徑）。

## 排程

每月 1 日 08:00 寄營運報表信（啟動時補寄漏掉的月份）：`ModuleSpec.schedulers`。

## 拿掉本模組時（PLAYBOOK §B-4：少一個功能，並且明白告知）

| 使用方 | 行為 |
|---|---|
| 首頁（L1 `index.html`） | `/api/dashboard/*` 404 ⇒ 顯示「首頁的統計、圖表與待辦摘要需要『營運分析』模組」，不講成伺服器重啟 |
| 出納（M05 `cashier.js`） | 銀行對帳 404／405 ⇒ 「銀行對帳需要『營運報表』模組」 |
| 出納、會計匯出（M05／M06） | 不受影響：收入與銷項發票收集已下沉 L1 `helpers/receivables.py` |
| 本模組的頁面 | `/pages/reports.html` 等回 404 提示頁（core.pages） |

## 依賴

| 對象 | 方式 |
|---|---|
| M01 案件 | `helpers.quotations`、`helpers.recognition` 的純計算（l2_import_baseline 保留 3 條；M01 搬遷時改用 provider，ROADMAP） |
| M04 外包工班 | IP-1 `dispatch.row`（精算快照過期檢查；不在 ⇒ 明說無法檢查） |
| M07 薪資獎金 | IP-9 `expense.entries`（支出） |
| L1 | `helpers.receivables`、`helpers.xlsx_out`、`helpers.company_identity`、`helpers.row_access`、`routers.company_lookup`（統編查詢與 `/api/now`，已拆出） |

## 資料（MODULE-GUIDE §3）

不擁有表、不存檔案（`data.tables`／`data.files` 皆空）。

## 頁面

`reports.html`、`devices.html`、`warranty.html`、`procurement.html`、`sales-orders.html`（轉址頁）。
實體檔暫留 `frontend/pages/`（core.pages 依 module.json 宣告歸屬本模組；搬進 `modules/analytics/pages/` 屬 STAGE-C C5）。
地圖（`map.html`、`map_points`）是 L1 共用能力，不屬於本模組。
