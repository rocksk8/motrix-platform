# M06 會計（accounting）

傳票（建立、送審、簽核、過帳、作廢重開、PDF、附件帶入、摘要來源）、會計科目、T100 傳票匯出。

## 內容

| 檔 | 說明 |
|---|---|
| `api/vouchers.py` | `/api/vouchers*` |
| `api/accounting_export.py` | `/api/reports/t100-export*`、`/api/settings/t100-export-config` |
| `api/account_items.py` | `/api/account-items*` |
| `voucher.py` | 傳票的平衡檢查、狀態、簽核鏈 |
| `voucher_pdf.py` | 傳票 PDF（含附件合併） |
| `voucher_template.py` | 摘要範本 |
| `voucher_attachments.py` | 傳票附件：帶入、預覽；來源檔案經 IP-21 `attachments.for_document` 取得 |

表：`vouchers_all`（VIEW `vouchers`）、`voucher_lines`、`voucher_attachments`、`voucher_edit_log`、`account_items`、`t100_export_confirmations`（凍結 migration 建立）。頁面：`voucher.html`、`account-items.html`（仍在 `frontend/pages/`；模組頁面尚無服務路徑）。

## 串接點

- 提供：IP-2 `voucher.draft`＋`voucher.account_check`、IP-3 `accounting.settings`、IP-4 `voucher.void_draft`＋`voucher.status`（M07 獎金傳票）；IP-22（暫定號）`voucher.by_case`（M01 案件整包）
- 取用：IP-1 `dispatch.row`（M04 派工支出來源）、IP-14 `contractor_voucher.paid_between`（M04：T100 承攬付款）、IP-20 `inventory.paid_batches`（M03：T100 進貨付款）、`receivables.tax_invoices`（M05：T100 收款事件）、IP-21 `attachments.for_document`（M01／M04／M05：附件來源）
- 對方不在時：T100 預覽 `notice` 明說少了哪幾類；附件來源缺席的類別在傳票頁紅字說明（`unavailable`）；因權限沒列出的附件只說類別＋個數（`hidden`）

## 已知例外（到期守門）

`tests/platform/test_accounting_foreign_reads.py`：`api/vouchers.py` 讀 M01 的 `quotations`、`case_extra_expenses`（到期：M01 提供 `case.summary`／`case.extra_expenses`），讀 M04 的 `contractor_dispatches`、`vendor_contractors`（到期：IP-15 成本檢視 `dispatch.cost_for_case`）。

## 本模組不在時（別人怎麼辦）

- M01 案件整包：`parts.vouchers` 404＋「會計傳票模組未安裝：沒有傳票資料」，案件頁不列傳票連結
- M07 獎金：IP-2／IP-4 不在 ⇒ 獎金傳票段說明（M07 自己處理）

## 尚未處理

- 別的頁面直接呼叫本模組端點（M01 case-management-close.js、approval-queue.html → `/api/vouchers`；M01 派工、M03 inventory.html、M05 cashier.js → `/api/reports/t100-export*`）：本模組不在時得到 404，畫面要說「會計模組未安裝」（M06-PLAN §1-C #12，逐頁 e2e）
- M01 簽核佇列與轉簽直讀／直寫 `vouchers_all`（§1-C #8／#9，併 M01 approval 那一包；寫入已登記 table_write_exceptions）
