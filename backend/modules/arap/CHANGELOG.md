# 應收應付 更新紀錄

## 1.0.1 — 2026-09-26
- 待我簽核與轉簽（M01-PLAN §3-7）：本模組提供 `approval.queue_items`（開票申請、請款單的待簽項目，欄位同原 M01 佇列）與 `approval.reassign`（`invoice_voucher`、`payment_request`：`data_json.$.approval` 的讀寫）；M01 佇列、角標、轉簽不再直讀直寫本模組的表。本模組不在 ⇒ 佇列不列、不給轉簽；佇列詳情的單據內容改由本模組提供（`approval.detail`）（不在 ⇒ 詳情 400 並明說）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/cashier.py`、`routers/invoice_vouchers.py`、`routers/payment_requests.py` 搬入 `modules/arap/api/`（PLAYBOOK §B；多支 router 放 `api/`，CORE-SPEC §3）；由載入器掛載
- 收回 L1 中繼 `helpers/receivables.py` → `modules/arap/receivables.py`（ROADMAP A8b），對外只經 provider：`receivables.income_items`（M08 現金口徑收入）、`receivables.tax_invoices`（M08 稅務匯出、M06 T100 收款事件）
- 收回 `POST /api/reports/bank-reconcile`（自 M08，路徑不變）；比對對象是承攬商匯款申請 ⇒ M04 不在時明說（404，同待付款）
- 對方不在時：M04（IP-14）⇒ 待付款／銀行對帳 404 並明說；M07（IP-8）⇒ 獎金待發放區塊顯示原因（既有）
- 本模組不在時（使用方各自處理）：M08 報表的現金口徑收入附 `incomeNotice`、稅務匯出 404 並明說；M06 T100 預覽的 notice 列出「不含收款事件」
