# 應收應付 更新紀錄

## 1.0.51 — 2026-10-10（wip/t50-int；第 50 班）
- **（併入）(next) — 2026-10-10（wip/t53-05-rb-adapters）：請款單、開票申請憑據進刪除暫存區（IP-RB1 adapter；第 53 班 P1）**
- 新 `recycle_adapter.py`（`payment_request`、`invoice_voucher` 兩個 adapter，`ModuleSpec.providers[("recyclebin.adapter", …)]`）：快照＝單據列＋（開票申請）已開立附件清單；還原＝單號被占 ⇒ `conflict:`、案件不在 ⇒ `parent_missing:`、附件原路徑被占用 ⇒ 改寫 `issued_files_json` 並註記。
- `DELETE /api/payment-requests/{no}`、`DELETE /api/invoice-vouchers/{no}`：規則不變（只准草稿、財務角色／最高管理者），刪除改呼叫 `recycle_bin.delete()`（同一個寫交易，進暫存區可還原）；回應多 `recycled`。暫存區模組不在 ⇒ 照舊硬刪（同一段 `delete_in_tx`），`recycled:false`，稽核標籤註明「暫存區未啟用，已直接刪除」。
- 『刪除已核可』（最高管理者，`POST /api/recycle-bin/delete-approved`）：兩種單據只收『已核准』；影響清單＝已匯出次數、已開立附件數、行事曆事件（皆資訊性，不擋——這兩種單據沒有收款／總帳／獎金下游）。
- 無 migration、無權限變更、無 schema 變更。守門基線 `recyclebin_baseline_t53.json` 移除這兩種單據的 `routes`／`delete_from` 項目。

## 1.0.50 — 2026-10-10（wip/t51-05-status-colors）：`payment-request-form.html` 狀態徽章補「已駁回」「已作廢」顏色
- 頁首狀態徽章的對照表原本只有 4 個狀態，已駁回／已作廢掉成無底色灰字；補上 `badge--rejected`／`badge--lost`。純畫面。

## 1.0.49 — 2026-10-10（wip/t50-int；第 50 班）
- **（併入）(next) — 2026-10-09（wip/t49-05-bonus-cleanup）：移除憑據／請款單詳情與 PDF 端點裡不可達的 `if not row`；併 2026-10-09(wip/t48-po-bank-block)**
- **（併入）(next) — 2026-10-09（wip/t48-po-bank-block）：出納待付款——採購單缺廠商收款帳戶時顯示原因並停用『登錄付款』**
- `cashier.html`：待付款申請列有 `blockReason`（M01 提供者在『缺廠商收款帳戶擋付款』開啟、且為其切換時間點之後建立的採購單缺銀行／帳號時給）⇒ 紅字顯示並停用『登錄付款』（後端 409 為最後防線）。開關預設關；細節見 case CHANGELOG。

## 1.0.48 — 2026-10-09（wip/t49b-1d-strictbool2；W1c-P2b 旗標嚴格解析補丁）
- `POST /api/invoice-vouchers/{no}/approve`、`POST /api/payment-requests/{no}/approve` 的 `cascade`（『同一人連任多層時一次簽完』）：字串 `"false"` 以前會替簽核人自動簽完剩下的連續層。 旗標只收真布林（`helpers.validation.body_flag`）：JSON 字串 `"false"`／`"0"`／`""` 以前是 truthy，現在回 422、什麼都不寫（先驗旗標，再碰資料庫與簽核鏈）；真布林與沒帶（預設 false）行為不變。測試：`tests/test_strict_bool_cascade_t49b.py`。

## 1.0.47 — 2026-10-09（wip/t49-05-bonus-cleanup）：移除憑據／請款單詳情與 PDF 端點裡不可達的 `if not row`
- `api/invoice_vouchers.py`、`api/payment_requests.py`：`get_*`／`download_*_pdf` 在 `_guard_voucher` 與 `conn.close()` 之後的 `if not row: raise 404`（上方已處理 `not row`，永遠進不來）共 4 處刪除；行為不變。

## 1.0.46 — 2026-10-08（第 47 班整合）：出納 hook 記錄標籤微調
- `api/cashier.py`：承攬商匯款改預定日後呼叫提供者的記錄標籤由 `contractor_voucher.planned_changed` 改為「承攬商匯款 planned_changed」（原標籤與串接能力名同字串，被船運分級守門判成未解析取用）；行為不變。

## 1.0.45 — 2026-10-08（wip/t47-audit-fixes）：出納端點跟進第 46 班稽核（S5／S8）；併 wip/t47-paydate-l1
- `PATCH …/pending-payables/{source}/{key}/planned-pay-date`：日期沒變時仍呼叫提供者的（冪等）`planned_changed`，上次背景行事曆推送失敗時重按一次能修復；稽核與通知照樣略過。
- `GET …/payee-bank`：嚴格提供者（`FULL_ACCOUNT_STRICT`，勞報單）先寫稽核、寫不進去 ⇒ 500 且不回帳號；回應加 `Cache-Control: no-store`。
- `api/cashier.py`：付款後的行事曆「付款待辦」收回／保留改為提供者 `planned_changed`（commit 之後）優先，沒有的來源走 L1 `payable_due_core.sync_event`；`NO_CALENDAR` 的來源（勞報單）仍完全不進行事曆（第 46 班 Q7，行為不變）。叫料分次付款仍有餘額時事件保留。
- **獨立稽核跟進（ab）**：出納付款／改預定日端點在 commit 之後呼叫的串接點（`planned_changed`、`contractor_voucher.planned_changed`）出錯只記 log，不讓已完成的操作回 500。

## 1.0.44 — 2026-10-08（fix/t45-audit-followups）：出納預定付款日端點遇到「沒變」直接回（第 45 班稽核 S3）
- `PATCH …/planned-pay-date`（兩條）：提供者回 `unchanged` ⇒ 回 200＋`unchanged: true`，不寫稽核、不通知申請人、不動行事曆。

## 1.0.43 — 2026-10-08（fix/pr-remark-in-queue）：出納對表單收款對象的警示
- 出納頁待付款表：項目帶 `payeeNote` 時（採購單／零用金、收款對象填在表單且沒有另存收款人與銀行資料）在付款鈕旁以文字顯示警示；`GET …/payee-bank` 的說明改用提供者的 `note`（不再退回申請人的員工收款帳戶）。不擋付款，權限規則不變。

## 1.0.42 — 2026-10-08（wip/t46-payslip-impl）：勞報單進出納待付款（IP-100 payroll_payslip）
- 第46班：IP-100 提供者可選方法 `after_paid`（付款 commit 之後）與屬性 `NO_CALENDAR`（勞報單不進行事曆：不建「支出付款」事件、不收「付款待辦」）；出納頁待付款表對勞報單顯示「傳票單號」欄與已簽回／未簽回小標（不影響付款），舊「勞報單待付款」頁籤隱藏一班；`/api/cashier/payslip-queue` 可見範圍改為財務角色＋最高管理者（**權限變更**）。

## 1.0.41 — 2026-10-07（wip/t45-paydate-impl）：出納預定付款日端點（來源無關、承攬商匯款）與通知申請人（含出納頁提示色改語意 token）
- `api/cashier.py`：新增 `PATCH /api/cashier/pending-payables/{source}/{key}/planned-pay-date`（財務角色／superadmin；經提供者 `set_planned_pay_date`，不經案件守門；已付款 409；提供者不支援 409；commit 之後才對齊行事曆；稽核 `cashier.planned_pay_date`，不含金額）。出納頁 `savePlannedPayDate` 改打此端點。
- 新增 `PATCH /api/cashier/payable-queue/{voucher_no}/planned-pay-date`（承攬商匯款；經 IP-14 `contractor_voucher.set_planned`；M04 不在 ⇒ 404＋既有「外包工班模組未安裝」訊息）。出納頁待付款表新增「預定付款日」欄（可改、已逾／3 天內標示），原欄改名「應付款日（合約）」。
- Q7：財務設定／改期／清除預定付款日 ⇒ 站內通知申請人（type `planned_pay_date`；文字「您的請款 <單號> 預定 <日期> 付款」，不含金額；申請人本人改不通知自己；三個來源皆然；提供者回傳 `applicant`／`docCode`／`link`）。
- **權限**：與登錄付款同一條（財務角色／superadmin）；未新增任何角色的可視範圍。

## 1.0.40 — 2026-10-06（wip/t44-attach-views）：出納唯讀看待付款申請附件（頁面改行內錯誤訊息）
- `api/cashier.py`：新增 `GET /api/cashier/pending-payables/{source}/{key}/files/{file_id}`（與待付款清單同權限＝財務角色／superadmin；檔案由提供者 `file_open` 認領，其餘一律同一句 404；回 octet-stream＋inline；每次開檔留稽核 `cashier.payable_file_view`，不記內容）。前端 `cashier.js`／`cashier.html` 顯示附件清單（只讀）。

## 1.0.39 — 2026-10-06（wip/t44-fin-fixes）：匯款差額退回後重建行事曆「付款待辦」；併入 wip/t44-settle-terms（字樣）
- `api/cashier.py`：`decide_remit_review` 退回後，若提供者回傳 `payableEvent`，commit 後背景呼叫 L1 `push_event_upsert_for_module` 重建（該鍵不外洩到回應）；事件種類關閉時不碰 Google。核可不重建。
- `cashier.py`：404 提示「找不到申請來源」、稽核與通知標籤「支出申請付款」、匯出分頁「支出申請付款明細」。客戶「請款單」不動。

## 1.0.38 — 2026-10-05（wip/t42-finance-role）：財務角色
- 出納頁與開票／請款憑證的財務動作改由「財務」角色決定：`_require_view_access`／`_can_pay`／差額核可（`canDecide`）／銀行對帳／完整銀行帳號，以及開票申請憑據、請款單的 `_require_admin`（建立／送審／作廢／匯出）一律 `has_finance_access`／`has_cashier_access`（僅 `finance` 角色與 superadmin；admin 直通拿掉）。付款／匯款差額通知改寄財務角色（`notify_module_activity(audience="finance")`）。前端 `cashier.js`／`reports.js` 同步。

## 1.0.37 — 2026-10-05（wip/t42-planned-pay-date）：出納付款後收回行事曆「付款待辦」
- `api/cashier.py`：登錄付款（`pay`）成功後，背景呼叫 L1 `push_event_delete_for_module("payable_due", "<來源>:<key>")` 收回該筆的行事曆「付款待辦」事件；只靠 IP-100 的（來源, key），不讀來源模組的表；事件種類關閉時不碰 Google。註解的「請款待付款」同步改稱「待付款申請」。
- 測試：`modules/case/tests/test_payable_planned_pay_date_2026_10_05.py::test_calendar_deleted_when_cashier_pays`。

## 1.0.36 — 2026-10-05（wip/quick2-wording，併入 t41）：出納「請款待付款」改稱「待付款申請」
- `cashier.html` 分頁「待付款申請」、空狀態「目前沒有待付款的申請」、欄名「申請內容」；模組未安裝提示同步。只改畫面文字。

## 1.0.35 — 2026-10-03（wip/t34-cashier-kinds-a3）：出納待付款顯示分期申請的款別／期別
- 出納頁「待付款」與「執行歷史」的承攬商匯款列、以及「標記已匯款」視窗標題，分期申請多顯示「款別 第 N 期」（舊式整筆不顯示）；出納分得出同一承攬商同一案件的訂金／進度款，避免付錯。資料來自 IP-14 `contractor_voucher.public` 已有的 `kindName／seq`，後端不變。
- 測試：`test_e2e_cashier_installment_label_2026_10_03.py`（含截圖）。

## 1.0.34 — 2026-10-02（wip/t32-fixes-d7）
- 出納 `payee-bank` 端點：請款來源提供者可宣告 `FULL_ACCOUNT_STRICT`（目前只有材料申請），宣告後完整帳號只給最高管理者與出納，一般管理員只看遮罩；其他來源行為不變。
- 差額審核表「差額」欄可顯示審核原因（`reason`，例如手續費偏高）。

## 1.0.33 — 2026-10-01（wip/w1-attach-p3-a3：附件目錄 P3）
- 附件目錄 P3：`_ArapCatalog` 加 `search`／`count`（開票申請已開立檔案；權限＝`_voucher_readable` 逐張）。

## 1.0.32 — 2026-10-01（暫用號，列車取號；wip/w2-expense-a2：A2-3 出納頁）
- 出納「請款待付款」：費用單據（採購單匯款日＋付款條件、零用金付款方式、其他可選付款方式）、類型標籤、收款人銀行資料遮罩＋「查看收款人資料」（`GET …/payee-bank`，只限能付款者、每次留稽核、不記帳號）；付款科目（`payAccountCode`）用會計連接器驗證。下游效應（R1）：付款日與金額規則不變。

## 1.0.31 — 2026-10-01（暫用號，列車取號；wip/w3-local-date）
- 本地日期（使用者 2026-10-01：凌晨建的單日期變前一天）：出納頁（T100 起迄日、檔名日期）等「今天」預設值改用本地日期（static/motrix-date.js）。

## 1.0.30 — 2026-09-30（暫用號，列車取號；wip/w2-bonus-correction：獎金更正單）
出納「獎金待發放」與發放紀錄納入獎金更正單的補發列（kind=correction）：連結（testid `cashier-bonus-corr-<更正單號>`）到更正單頁處理，不在出納頁直接標記。

## 1.0.29 — 2026-09-30（wip/w4-l-gaps-4：E01 deal_tag 篩選改逐筆解析）
- 內部：`gl_events._deal_ok_quotes` 不再用資料庫 JSON 函式，改為取出每筆 `data_json` 後在程式內逐筆解析（壞 JSON 視為沒有標籤）；判斷語意不變（欄位優先，其次 data_json.dealTag；已成案／已結案）。

## 1.0.28 — 2026-09-30（暫用號，列車取號；W4 修正）
- E01 案件狀態篩選改在 Python 逐列解析 data_json（不用 SQL json_extract，守門棘輪）；行為不變。

## 1.0.27 — 2026-09-30（wip/w1-t27fix2）
- 請款單／開票申請的退回與撤銷核准：原因（400「退回要填原因」）改在狀態與權限檢查之後才驗（404／403／409 不再被 400 蓋掉）。

## 1.0.26 — 2026-09-30（暫用號，列車取號；wip/w3-t27fix2）
- 匯出 PDF 姊妹的歸屬區改用常數 `_EXPORT_AREA`（不寫 module 等號字串字面量：test_module_keys_consistency 的後端掃描器會把它當權限 key）；只動寫法，行為與稽核內容不變。

## 1.0.25 — 2026-09-30（暫用號，列車取號；W4 寫入串接缺口 L1／L2／L6／L8／L9／L10）
- L8：銷項發票事件 E01 與收款事件 E03、營運報表同一口徑——案件狀態不是「已成案／已結案」（例如已降級）時不入帳（notice 說明）；已過帳的由引擎判來源消失、產生反向草稿。

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
