# M05 應收應付（arap）

出納（待付款、待收款、獎金待發放、執行歷史、匯出、銀行對帳）、開票申請、請款單，以及收款與銷項發票的資料收集。

## 內容

| 檔 | 說明 |
|---|---|
| `api/cashier.py` | `/api/cashier/*`、`POST /api/reports/bank-reconcile` |
| `api/invoice_vouchers.py` | `/api/invoice-vouchers*` |
| `api/payment_requests.py` | `/api/payment-requests*` |
| `receivables.py` | 收款明細、銷項發票清單（讀 M01 報價單的 caseRecord.payment；只讀） |

表：`invoice_vouchers`、`payment_requests`（凍結 migration 建立）。頁面：`cashier.html`、`receivables.html`、`payment-request-form.html`（仍在 `frontend/pages/`；模組頁面尚無服務路徑）。

## 串接點

- 提供：`receivables.income_items`、`receivables.tax_invoices`（見 `docs/platform/INTEGRATION-POINTS.md`，號碼由列車定）
- 取用：IP-14 `contractor_voucher.public`（M04：待付款、執行歷史、銀行對帳）、IP-8 `bonus.payouts`（M07：獎金待發放）
- 對方不在時：M04 不在 ⇒ 待付款與銀行對帳 404 並明說；M07 不在 ⇒ 獎金區塊顯示原因

## 本模組不在時（別人怎麼辦）

- M08 營運報表：現金口徑的收入沒有資料來源 ⇒ 回應附 `incomeNotice`（PDF 的空表說明也改成這一句），稅務匯出 404 並明說；權責口徑不受影響（收入來自 M01 的階段）
- M06 T100 匯出：沒有收款事件，預覽的 `notice` 明說
- M01 案件頁的開票／請款段、簽核佇列、M08 報表的出納兩區：前端呼叫本模組端點得到 404 ⇒ 要說「應收應付模組未安裝」（⚠ 尚未處理，見 SPEC.md 待辦）

## 尚未處理

- 其他模組直接讀本模組的兩張表（M01 報價單案件整包、簽核佇列、轉簽；L1 行事曆回寫、附件、封存、PDF）：表在（凍結 migration），讀取不會壞；讀取連接器另開題（同 M04 O-2）
- 前端 404 的提示（上一節最後一條）
