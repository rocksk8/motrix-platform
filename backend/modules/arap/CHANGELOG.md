# 應收應付 更新紀錄

## 1.0.5 — 2026-09-26（A，a-attachments-5 帶入 M06 基底；列車取號）
- 開票申請附件提供者：逐張過濾有讀不到的 ⇒ `AttachmentNotVisible(visible=看得到的, hidden=沒列出的附件個數)`，不再靜默只回看得到的（主持裁示：因權限沒列出要明說，只准類別＋個數）

## 1.0.4 — 2026-09-26（A，IP-21 attachments.for_document；第十班列車取號）
- `api/invoice_vouchers.py` 新增 `_InvoiceVoucherAttachments`（`attachments.for_document` 提供者，開票申請的已上傳檔案來源）
- 抽出 `_voucher_readable`（案件層＋金額層，含本單簽核人例外），與 `_guard_voucher` 共用；`doc_nos_for_case` 逐張過濾（讀不到的不列，整張案件讀不到 raise `AttachmentNotVisible`）
- 附件的可見範圍不可以比原單據寬（稽核 D AT-M1、AT-M1b）

## 1.0.3 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.2，列車取號）
- 簽核佇列詳情（M01-PLAN §3-7，c-approval-2）：單據內容改由本模組提供 `approval.detail`（共同段用 L1 `helpers/approval_queue.snapshot_doc_detail`）；M01 詳情端點不再直讀本模組的表，只做每案權限、案件抬頭、金額遮蔽。本模組不在 ⇒ 詳情 400 並明說

## 1.0.2 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.1，列車取號）
- 待我簽核與轉簽（M01-PLAN §3-7）：本模組提供 `approval.queue_items`（開票申請、請款單的待簽項目，欄位同原 M01 佇列）與 `approval.reassign`（`invoice_voucher`、`payment_request`：`data_json.$.approval` 的讀寫）；M01 佇列、角標、轉簽不再直讀直寫本模組的表。本模組不在 ⇒ 佇列不列、不給轉簽

## 1.0.1 — 2026-09-26（第九班之後 rebase；列車取號）
- 選單（C4 之後）：「出納」項自 L1 `core/menu_l1.json` 移進本模組 `module.json` 的 pages[].menu（模組不在 ⇒ 側欄不出現）
- 題：money_round 拿掉未使用的 `_patch_entries` 匯入（第九班把它移到 M08 的題檔）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/cashier.py`、`routers/invoice_vouchers.py`、`routers/payment_requests.py` 搬入 `modules/arap/api/`（PLAYBOOK §B；多支 router 放 `api/`，CORE-SPEC §3）；由載入器掛載
- 收回 L1 中繼 `helpers/receivables.py` → `modules/arap/receivables.py`（ROADMAP A8b），對外只經 provider：`receivables.income_items`（M08 現金口徑收入）、`receivables.tax_invoices`（M08 稅務匯出、M06 T100 收款事件）
- 收回 `POST /api/reports/bank-reconcile`（自 M08，路徑不變）；比對對象是承攬商匯款申請 ⇒ M04 不在時明說（404，同待付款）
- 對方不在時：M04（IP-14）⇒ 待付款／銀行對帳 404 並明說；M07（IP-8）⇒ 獎金待發放區塊顯示原因（既有）
- 本模組不在時（使用方各自處理）：M08 報表的現金口徑收入附 `incomeNotice`、稅務匯出 404 並明說；M06 T100 預覽的 notice 列出「不含收款事件」
