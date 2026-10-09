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
- 出納付款後（`pay` 端點）呼叫 L1 `push_event_delete_for_module("payable_due", "<來源>:<key>")` 收回行事曆「付款待辦」事件；只靠 IP-100 的（來源, key），不讀來源模組的表（2026-10-05）。
- 取用：IP-14 `contractor_voucher.public`（M04：待付款、執行歷史、銀行對帳）、IP-8 `bonus.payouts`（M07：獎金待發放）
- 對方不在時：M04 不在 ⇒ 待付款與銀行對帳 404 並明說；M07 不在 ⇒ 獎金區塊顯示原因

## 第 46～51 班追加（文件同步 DOCSYNC-T52；細節與版本見 CHANGELOG）

- **出納預定付款日**（1.0.41～1.0.45）：`PATCH /api/cashier/pending-payables/{source}/{key}/planned-pay-date` 與 `PATCH /api/cashier/payable-queue/{voucher_no}/planned-pay-date`（承攬商匯款，經 IP-14 `contractor_voucher.set_planned`）——**財務角色／最高管理者**（與登錄付款同一條；沒有放寬任何角色），不經案件守門；已付款 409、提供者不支援 409、與登錄付款同時發生 409；日期沒變 ⇒ 200＋`unchanged: true`，不稽核、不通知、不動行事曆（提供者的冪等 `planned_changed` 仍會呼叫，讓上次失敗的背景推送可重按修復）；commit 之後才對齊行事曆，串接點出錯只記 log、不讓已完成的操作回 500。稽核 `cashier.planned_pay_date`。財務設定／改期／清除 ⇒ 站內通知申請人（type `planned_pay_date`，不含金額；本人改不通知自己）。
- **查看收款人銀行資料**（`GET …/payee-bank`）：嚴格提供者（`FULL_ACCOUNT_STRICT`：勞報單、案件單據）**先寫稽核 `cashier.payee_bank_view`，寫不進去 ⇒ 500 且不回帳號**，回應 `Cache-Control: no-store`。採購單／零用金沒有另存收款人與銀行資料時不再退回申請人的員工收款帳戶，改帶 `payeeNote` 警示；M01 開啟「缺廠商收款帳戶擋付款」時待付款列帶 `blockReason` ⇒ 紅字顯示並停用『登錄付款』（後端 409 為最後防線）。
- **勞報單進待付款**（IP-100 `payroll_payslip`，1.0.42）：已核准／已匯出／已簽回且未付款的勞報單；提供者可選方法 `after_paid`（付款 commit 之後）與屬性 `NO_CALENDAR`（勞報單不進行事曆）；出納頁多「傳票單號」欄（付款時必填）。
- **旗標嚴格解析**（1.0.48）：憑據／請款單 `approve` 的 `cascade` 只收真布林（字串 `"false"` ⇒ 422，什麼都不寫）。

## 本模組不在時（別人怎麼辦）

- M08 營運報表：現金口徑的收入沒有資料來源 ⇒ 回應附 `incomeNotice`（PDF 的空表說明也改成這一句），稅務匯出 404 並明說；權責口徑不受影響（收入來自 M01 的階段）
- M06 T100 匯出：沒有收款事件，預覽的 `notice` 明說
- M01 案件頁的開票／請款段、簽核佇列、M08 報表的出納兩區：前端呼叫本模組端點得到 404 ⇒ 要說「應收應付模組未安裝」（⚠ 尚未處理，見 SPEC.md 待辦）

## 尚未處理

- 其他模組直接讀本模組的兩張表（M01 報價單案件整包、簽核佇列、轉簽；L1 行事曆回寫、附件、封存、PDF）：表在（凍結 migration），讀取不會壞；讀取連接器另開題（同 M04 O-2）
- 前端 404 的提示（上一節最後一條）
