# 營運分析 更新紀錄

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
