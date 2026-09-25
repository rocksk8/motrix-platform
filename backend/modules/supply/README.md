# M03 採購・庫存・出貨（supply）

供應商、庫存（入庫批次、序號、採購建議）、出貨單（分層簽核、PDF、匯出紀錄）。

## 端點
- `/api/suppliers`（`api/suppliers.py`）：供應商主檔與往來紀錄
- `/api/inventory`（`api/inventory.py`）：入庫批次、序號、庫存摘要、採購建議
- `/api/shipping-notes`（`api/shipping_notes.py`）：出貨單建立、送審、核准、PDF、匯出紀錄

## 頁面
`suppliers.html`、`supplier-log.html`、`inventory.html`、`shipping-export-history.html`（登記在 `frontend/static/sidebar.js` 的 `MODULE_PAGES`）。
案件頁（M01）的「出貨單」分頁經 IP-18 取資料。

## 資料
表：`suppliers`、`stock_items`、`stock_batches`、`purchase_suggestion_status`、`shipping_notes`（全部 T1，由凍結的 V9 migration 建立）。

## 串接點
- 提供 IP-6 `calendar.writeback`（`shipping_note`）：L1 行事曆建立事件後由本模組回寫 event id
- 提供 IP-18 `shipping.list_for_case`：M01 案件整包的出貨單段
- 提供 IP-19 `stock.serial`：M01 案件設備序號認領／釋放庫存（呼叫端連線、不 commit）

## 本模組不在時
- 案件頁「出貨單」分頁顯示「採購・庫存・出貨模組未安裝：沒有出貨單資料」，不顯示新增鈕
- 案件設備序號照常存檔、不同步庫存；有序號變動時存檔狀態列顯示「已儲存；設備序號未同步庫存：採購・庫存・出貨模組未安裝」
- 側欄不顯示本模組頁面；直接打網址得到提示頁
- 表仍在：M08 儀表板、L1 料號（刪除前檢查序號）、全域搜尋（供應商）、備份匯出照樣讀得到

## 尚未處理
- 出貨單 → M01 `helpers/quotations` 的 `guard_case_access`：C 的案件存取下沉 L1（wip/c-case-access）合回後改從 L1 取
- 讀本模組表的其他地方（M01 `routers/quotations.py` 3 處、L1 `helpers/audit.py`、`helpers/google_calendar.py`、M08 `routers/dashboard.py`、L1 `routers/parts.py`、`routers/search.py`）：唯讀、表不隨模組消失，暫不經連接器（DEPENDENCY-MAP §4）
