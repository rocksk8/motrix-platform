# 營運分析 更新紀錄

## 1.0.6 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.4，列車取號）
- 稽核 D M5-S1：從 `reports.html?tab=cashier` 進來時，出納頁籤的待付款／待收款 404 也記原因（`payableSnapMissing`），快照不畫 NT$ 0

## 1.0.5 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.3，列車取號）
- 頁面（`frontend/pages/reports.html`、`js/reports.js`）：M05 不在 ⇒ 收支分頁顯示 `incomeNotice`（`data-testid=income-unavailable`，比照 X-1 的支出）；財務快照的應收應付在出納佇列 404 時顯示原因（端點帶的說明，或「應收應付模組未安裝」），不畫成 NT$ 0

## 1.0.4 — 2026-09-26（C，M05；第九班之後 rebase 重編，原暫用 1.0.2，列車取號）
- M05 搬遷：`POST /api/reports/bank-reconcile` 收回 M05（`modules/arap/api/cashier.py`，路徑不變），本模組只留一行指路註解；它的 8 題隨之搬進 `modules/arap/tests`
- 收款／銷項發票改取 M05 provider（`receivables.income_items`／`receivables.tax_invoices`）；M05 不在 ⇒ 現金口徑收入附 `incomeNotice`（PDF 空表說明同句）、稅務匯出 404 並明說——不是「這個月沒有收款」

## 1.0.3 — 2026-09-26（列車取號；原暫用 1.0.2，與 c-tax-calc-2 的 1.0.2 交會，本段改 1.0.3）
- `_compute_achievement(…, name_to_id=None)`：名字⇒帳號對照可由呼叫端給；沒給才查 `users`（行為不變）。原本無條件查資料庫 ⇒ `test_achievement_uses_same_attribution_as_performance` 不帶 client 單獨跑就紅（A 在 M03 反向控制查到，主持轉 M08）；該題改給空對照，另加「給了對照就用 id 比對」一題（含解析不到的正對照）

## 1.0.2 — 2026-09-26（第八班列車取號；原暫用 1.0.1）
- 只改 import 來源（行為不變）：`api/reports.py` 的稅額函式（quote_tax_type、tax_split、LEGACY_TAX_NOTE、invoice_amounts）改自 L1 `helpers.tax_calc` import（C 的 T：稅額純函式自 M01 下沉 L1）⇒ 本模組對 M01 `helpers.quotations` 少一條相依

## 1.0.1 — 2026-09-26
- 稽核 ⑰（AUDIT-X-B-M08-move）建議與觀察：
  - `sales-orders.html`（轉址到案件管理）改歸 M01：資料端點本來就在 M01，模組不在時舊書籤不應看到「需要營運分析」（S-8）
  - `permissions` 補上本模組頁面實際檢查的 `finance`、`equipment`、`procurement`（O-4；`cashier`、`case_manage` 屬其他模組，不列）
  - dashboard.py 拿掉 GCIS 搬走後沒有用到的 urllib（O-5）
  - `tables_note`／README 寫明：精算快照過期檢查列出有效派工仍直讀 M04 的 `contractor_dispatches`、`vendor_contractors`（S-4，待 M04 提供者）

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
