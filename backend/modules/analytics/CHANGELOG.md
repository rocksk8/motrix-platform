# 營運分析 更新紀錄

## 1.0.3 — 2026-09-26
- 頁面（`frontend/pages/reports.html`、`js/reports.js`）：M05 不在 ⇒ 收支分頁顯示 `incomeNotice`（`data-testid=income-unavailable`，比照 X-1 的支出）；財務快照的應收應付在出納佇列 404 時顯示原因（端點帶的說明，或「應收應付模組未安裝」），不畫成 NT$ 0

## 1.0.2 — 2026-09-26
- M05 搬遷：`POST /api/reports/bank-reconcile` 收回 M05（`modules/arap/api/cashier.py`，路徑不變），本模組只留一行指路註解；它的 8 題隨之搬進 `modules/arap/tests`
- 收款／銷項發票改取 M05 provider（`receivables.income_items`／`receivables.tax_invoices`）；M05 不在 ⇒ 現金口徑收入附 `incomeNotice`（PDF 空表說明同句）、稅務匯出 404 並明說——不是「這個月沒有收款」

## 1.0.1 — 2026-09-26
- 只改 import 來源（行為不變）：`api/reports.py` 的稅額函式（quote_tax_type、tax_split、LEGACY_TAX_NOTE、invoice_amounts）改自 L1 `helpers.tax_calc` import（C 的 T：稅額純函式自 M01 下沉 L1）⇒ 本模組對 M01 `helpers.quotations` 少一條相依

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/dashboard.py`、`routers/reports.py` 搬入 `modules/analytics/api/`（PLAYBOOK §B，M08）
- 切相依（搬檔前）：
  - GCIS 統編查詢與 `/api/now` 拆到 L1 `routers/company_lookup.py`
  - 應收收入／銷項發票收集下沉 L1 `helpers/receivables.py`（M05／M06 不再 import 本模組）
  - `/api/sales-orders` 移到 M01（資料屬於 M01）
  - 精算快照過期檢查改走 IP-1 `dispatch.row`
  - 首頁、出納頁在本模組不在時明說
- 選單：營運報表、設備登載、保固追蹤、採購管理四項自 `core/menu_l1.json` 移到本模組 `pages[].menu`（欄位逐字不變）；sidebar `MODULE_PAGES` 登記本模組五頁
- `customization` 先寫 schema＋空清單：五頁的可自訂點尚未盤點（待辦，與 SPEC 分號一起）
- `provides.probes`（產品演練用）：`/api/dashboard/stats`、`/api/devices`、`/api/materials-summary`、`/api/reports/ar-aging`（稽核 ⑰ M-3）
- 首頁在本模組不在時，「有效期將屆」「90 天內到期」兩格顯示「—」＋明說，不顯示 0＋「沒有…」（稽核 ⑰ M-4）
- 地圖（map_points、map.html）歸 L1，不隨本模組搬
- V9 之前的歷史見 `docs/quick/changelog*.md`
