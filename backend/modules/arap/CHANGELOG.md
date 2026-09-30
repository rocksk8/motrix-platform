# 應收應付 更新紀錄

## 1.0.25 — 2026-09-30（wip/w1-t27fix2）
- 請款單／開票申請的退回與撤銷核准：原因（400「退回要填原因」）改在狀態與權限檢查之後才驗（404／403／409 不再被 400 蓋掉）。

## 1.0.25 — 2026-09-30（暫用號，列車取號；wip/w3-t27fix2）
- 匯出 PDF 姊妹的歸屬區改用常數 `_EXPORT_AREA`（不寫 module 等號字串字面量：test_module_keys_consistency 的後端掃描器會把它當權限 key）；只動寫法，行為與稽核內容不變。

## 1.0.24 — 2026-09-30（暫用號，列車取號；wip/w2-open-bind：附件開檔路徑綁單據（安全審查 W3））
- 附件目錄提供者 `open()` 加路徑綁單據檢查（`helpers.uploads.upload_path_key`）：檔案路徑不在這張單據自己的資料夾 ⇒ 當作沒有這個檔。

## 1.0.23 — 2026-09-30（暫用號，列車取號；wip/w3-export-pdf）
- 匯出規則（使用者 2026-09-30）：出納執行紀錄 Excel 匯出加 PDF 姊妹（`/api/cashier/export/pdf`），每次匯出寫稽核。

## 1.0.22 — 2026-09-30（暫用號，列車取號；wip/w2-gl-warn：已入帳來源的修改提示（MONEY-FLOWS §9 L3））
- 出納頁（`pages/cashier.html`／`js/cashier.js`）：取消或改動已入總帳的收款時，回應帶 `glWarning` ⇒ 頁首行內可關閉提示（不用 alert）。

## 1.0.21 — 2026-09-30（暫用號，列車取號；wip/w1-menu-split 選單拆分）
- 選單：出納排到「財務會計」群組第一項（order 20→10）；perm 不變。

## 1.0.20 — 2026-09-30（暫用號，列車取號；wip/w1-pdf-unapproved）
- 請款單／開票申請：退回（reject）與撤銷核准（revoke-approval）一律要填原因（400「退回要填原因」，`helpers.tiered_approval.require_reject_reason`）；PDF 預覽未核准時有紅色「未核可・僅供預覽」橫幅，預覽視窗有權決定者可「退回修改」。

## 1.0.19 — 2026-09-30（暫用號，列車取號；W4 總帳 R12 畫面）
- 出納頁『標記已匯款』視窗：個人外包人員逐位挑選勞報單（R12，經承攬商匯款單的 `personnel-links`／`personnel-link` 端點），顯示勞報單實付與匯款金額差異；未通過驗證時按鈕停用並顯示原因。純畫面，無新端點、無 migration。

## 1.0.18 — 2026-09-30（暫用號，列車取號；wip/w2-attach-p2：附件目錄 P2）
- 新增 `attachments.py::_ArapCatalog`（`attachments.catalog`／`arap`，IP-105）：開票申請已開立檔案開檔；權限＝`_voucher_readable`（同 IP-21 提供者）。

## 1.0.17 — 2026-09-30（暫用號，列車取號；wip/w1-file-preview 共用檔案預覽 P1）
- 出納頁勞報單簽回檔改用 L1 共用預覽元件（頁內預覽，下方保留「另開新分頁」），不再直接 `window.open(blob)`。

## 1.0.16 — 2026-09-30（暫用號，列車取號；wip/cal-toggle 行事曆推送可選）
- 行事曆「支出付款」（預設關，事件種類開關在 L1）：出納登錄請款付款（`pending-payables/{來源}/{key}/pay`）commit 之後推 `push_event_for_module('expense_payout', …)`，事件日期＝付款日；名目／受款人取提供者回傳（不讀別的模組的表）。勞報單付款走自己的端點，不推。題 `modules/arap/tests/test_expense_payout_calendar_2026_09_30.py`
## 1.0.15 — 2026-09-30（暫用號，列車取號；W4 總帳 C1）
- 新增提供者 `gl.events`（IP-GL1）：銷項發票（E01）與客戶收款（E03）事件，供 M06 總帳引擎產生傳票草稿；唯讀、不寫資料。收款採 W2 語意（實收＋手續費＝含稅收入，手續費另列）；先收款後開票用預收貨款沖轉；實收與發票含稅不一致、缺開立日期、無不可變 id 皆在 notice 明說。
- `receivables.collect_tax_invoices`／`collect_income_items` 的回傳**多帶**欄位（itemId、itemIdx、hasInvoiceDate、invoiceDate、bankAccountCode）；既有呼叫端不讀、行為不變。
## 1.0.14 — 2026-09-30（暫用號，列車取號；wip/sec-p0 安全修正 P0）
- 安全修正 P0：新增提供者 `uploads.path_access`／`arap`（IP-104，`invoice_vouchers._InvoiceVoucherPathAccess`，`ModuleSpec.providers`）：`invoice_vouchers/<開票單號>/` 的已開立檔案只簽給開票申請單筆規則 `_voucher_readable` 放行的人（本單簽核人經簽核佇列情境）。原本任何登入者都拿得到簽章。

## 1.0.13 — 2026-09-30（暫用號，列車取號；wip/w2-report-cash）
- 收款端手續費不再重複扣（使用者 2026-09-30，正式機案件 MQ-202607-045：實收 263,813（銀行入帳，已扣客戶內扣手續費 15）被報表再減 15 成 263,798，且 9 月當月收入是 0（預設權責））：收入明細 `collect_income_items` 的 `amount`＝銀行入帳＋手續費（含稅收入）、`netAmount`＝銀行入帳（L1 `receipt_amounts`）；`collect_tax_invoices` 多回 `feeAmount`／`bankAmount`（T100 收款傳票用）。
- 新增提供者 `expense.entries`／`receipt_fee`（IP-9）：客戶內扣的收款手續費以收款日列營運報表支出（類別「收款手續費」）。
- 出納執行紀錄：已收款「實收金額」＝銀行入帳、另列手續費（頁面與 Excel）；收款視窗標籤說明「銀行實際入帳金額（已扣客戶內扣手續費）」。
## 1.0.12 — 2026-09-30（暫用號，列車取號；W1 wip/w1-remit-fee）
- 稽核補修：登錄付款 `paidDate` 必填（不帶 ⇒ 400，不再默認今天）；審核決定的 403／409 由提供者例外決定；財務總覽顯示手續費在案件管理頁
- W1 出納匯款手續費（暫用號，列車取號）：`pending-payables/…/pay` 收實付／手續費並回差額待審核；新增 IP-102 取用端點 `GET /api/cashier/remit-reviews`、`POST /api/cashier/remit-reviews/{來源}/{key}/decision`（只限 admin+，退回必填原因）；執行紀錄與 Excel 匯出加實付／手續費／差額審核欄與「請款付款明細」；出納頁三個標記已匯款入口加實付／手續費欄、新增「差額審核」頁籤、T100 設定加手續費科目

## 1.0.11 — 2026-09-29（暫用號，列車取號；wip/payslip-void-signed）
- 出納頁新增「勞報單待付款」子頁籤：`GET /api/cashier/payslip-queue`（IP-103 `payslip.payables`；只給最高管理者與出納，財務看不到；薪資獎金模組不在 ⇒ `available:false`＋說明）。標記付款打勞報單那一支 `POST /api/payslips/{單號}/mark-paid`。
- 收款日期歸月：`receivables` 的現金口徑收入與發票期別改用 `helpers.norm_ymd`（「2026/09/01」等寫法不再被排除在月份外）。

## 1.0.10 — 2026-09-28（暫用號，列車取號；E4 wip/e-company-gate-impl 第三段）
- 本公司資料設定閘門第二道（COMPANY-SETUP-GATE §5；D CG5-M1）：開票申請、請款單 PDF 下載端點：`except Exception` 前先 `except HTTPException: raise`（第二道的 428 不被吞成 500）；請款單另驗本公司匯款三欄（L1 pdf_gen `_require_payment_bank`，缺 ⇒ 428 `company_bank_required`）

## 1.0.9 — 2026-09-28（第十四班列車取號，原暫用 1.0.8；B；wip/b-payreq：請款流程）
- 出納「請款待付款」頁籤：`GET /api/cashier/pending-payables`（IP-100 多提供者合併）、`POST /api/cashier/pending-payables/{來源}/{key}/pay`（登錄付款經提供者寫回付款日；admin+／出納，finance 只能看）；M01 不在 ⇒ 200 available:false＋原因。既有 payable-queue（IP-14）與 bonus-queue（IP-8）不動
## 1.0.8 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`cashier.html`、`payment-request-form.html`

## 1.0.7 — 2026-09-27（第十三班列車取號，原暫用 1.0.6；c-queue-json，主持指派）
- 待簽佇列提供者：簽核 JSON 改用 L1 `helpers.approval_queue.approval_json_of` 在 Python 逐筆解析（原本 SQL `json_extract(data_json,'$.approval')` 遇到一筆 malformed JSON ⇒ 整個查詢丟例外 ⇒ 這一類待簽全部靜默消失）；壞的那一筆跳過並記 ERROR（寫單號、不寫內容）
- `queue_detail` docstring：權限、抬頭、遮蔽在 L1（稽核 D AL-O2）

## 1.0.6 — 2026-09-27（第十三班列車取號，原暫用 1.0.5；C，M01-PLAN §5 ④）
- 頁面（稽核 D M4-M2，M01-PLAN §5 ④）：案件模組（M01）不在 ⇒ 請款單「帶入案件資料」與出納「收款／發票登錄」明說原因（判斷＝M01 路由不存在：404＋Not Found；看不到的案件的 404 不算）；e2e `tests/test_e2e_pages_without_case_module_2026_09_27.py`（各含正對照）

## 1.0.5 — 2026-09-26（A，因權限沒列出的附件要明說；主持裁示；第十一班列車取號）
- `api/invoice_vouchers.py::_InvoiceVoucherAttachments.doc_nos_for_case`：逐張過濾時讀不到的附件改算進沒列出的**個數**（`AttachmentNotVisible(visible=readable, hidden=N)`，只有數字，不帶單號、檔名、金額）

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
