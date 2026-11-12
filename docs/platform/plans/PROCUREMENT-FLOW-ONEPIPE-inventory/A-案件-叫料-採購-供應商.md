# onepipe-A：案件 → 叫料／材料申請 → 採購 → 供應商 真實流程盤點

範圍：`D:\Claude-pm\h1-onepipe`（唯讀調查，未改任何檔、未跑 pytest／server）。
路徑縮寫：`B/` = `backend/`，`F/` = `frontend/`；`mc/` = `B/modules/case/`；`ms/` = `B/modules/supply/`；`msub/` = `B/modules/subcontract/`。
標註「（推測）」者表示未逐行驗證。

---

## 0. 先講結論：這段流程其實有「三層單據、三個名單、三處到貨」

使用者眼中的一條線「案件 → 叫料 → 採購 → 供應商」，在程式裡實際是：

| 層 | 使用者看到的名字 | 實際資料 | 存在哪 |
|---|---|---|---|
| A | 請購單 PR | `case_extra_expenses` 列，`kind='purchase_req'` | 獨立表（`B/db.py:3566` 建表；`mc/migrations/0003_expense_forms.py:19-38` 加 kind/doc_code/lines_json/payee_*） |
| B | 採購單 PO | 同表，`kind='purchase_order'`，`data_json.vendor`（自由文字） | 同上；`B/helpers/expense_type_defs/purchase_order.json` 欄位 `vendor`=text |
| C | 材料申請（程式叫「叫料」materialOrders） | `quotations.data_json → caseRecord.materialOrders[]`＋疊加審核表 `case_material_approvals` | JSON 內嵌＋薄表（`mc/migrations/0004_material_approvals.py`） |
| D | 材料卡片（執行管理→材料申請清單） | `quotations.data_json → caseRecord.materials[]`（`ordered`/`arrived` 旗標、`orderItemId`、`poLink`） | JSON 內嵌，無表 |
| E | 匯款申請（舊單才用） | `case_material_payments`＋`case_material_payment_lines` | `mc/migrations/0005_material_payments.py` |
| F | 變更申請 | `case_material_changes` | `mc/migrations/0006_material_changes.py` |

三個「廠商」主檔互不相連：`suppliers`（採購供應商，`B/db.py:646`）、`vendor_contractors`（承攬商公司，`B/db.py:807`）、`contractors`（外包人員）。再加 PO 的 `data.vendor` 自由文字、材料卡片 `mat.supplier` 自由文字、`poLink.vendor`。

三處「到貨」：材料申請 `case_material_approvals.received_on`（`mc/material_approval.py:396-420`（`record_receipt`））、材料卡片 `materials[].arrived`（`F/pages/case-management.html:1185`）、PO 的 `data.delivery_date`（預計）；另有庫存側 `purchase_suggestion_status`／`stock_batches` 一條完全獨立的補貨線（見步驟 3 附錄）。

---

## 步驟 1　案件（成案／派工）

### 1-1 報價單 → 成案

| 項目 | 內容 |
|---|---|
| 頁面 | `F/pages/quotations.html`（清單）、`F/pages/quotation-form.html`（單張）、`F/pages/case-management.html`（成案後的案件頁）、`F/pages/case-stage-board.html`（跨案階段看板）；`F/pages/sales-orders.html` 只是導向頁（`location.href='case-management.html'`，`sales-orders.html:20`） |
| 從上一步怎麼進來 | 報價單 `quotation-form.html` 的「案件進度」下拉選「已成案」（`quotation-form.html:978-979`），成案後出現連結 `case-management.html?q=<quoteNo>`（`quotation-form.html:995-996`）。清單頁 `quotations.html` 同樣有下拉（`quotations.html:340-351`），**但沒有任何連到案件頁的連結**（grep `case-management` 於 quotations.html 零命中），要靠側欄「案件管理」。 |
| DB 表／欄 | `quotations`：`quote_no`(UNIQUE)、`status`、`deal_tag`、`sales_person_id`、`sales_person`、`assigned_user_ids`、`data_json`（`B/db.py:584-607`）。`case_stages`（id, quote_no, label, sort_order, done, due_date, assigned_to, depends_on…，`B/db.py:1819-1832`）、`case_stage_visits`（`B/db.py:1837`）。 |
| API（method path file:line） | `PATCH /api/quotations/{no}/deal-tag` `mc/api/quotations.py:3119`；`PATCH /api/quotations/{no}/status` `:2607`（僅 superadmin）；`POST /api/quotations/{no}/approve` `:5346`、`/reject` `:5667`、`/reject-final` `:5759`；`GET /api/quotations` `:871`；`GET /api/quotations/{no}` `:1442`；`GET /api/quotations/stage-board` `:1087`；`PATCH /api/quotations/{no}/case-record` `:3598`；階段 CRUD `mc/api/quotation_stages.py:48-488`；`PATCH /api/quotations/{no}/assigned-users` `:1496` |
| 權限／模組鍵 | 報價單：模組 `quotation`（`mc/module.json` 的 pages menu perm）。標記「已成案／未成案」：僅 admin／superadmin（`quotations.py:3123-3124`；`quotations.html:348-349`；`quotation-form.html:978`）。結案：僅 superadmin（`quotations.py:3127-3133` 區塊註解）。案件頁：模組 `case_manage`（`sidebar.js:575-577`；`module.json` pages）＋逐案可見規則 `CASE_ACCESS`＝本人業務／assigned_user_ids／admin+，另 `cashier` 可唯讀（`B/helpers/case_access.py:117-125`）。 |
| 狀態值 | 報價單 `status`：草稿／待審核／簽核中／已送出／已取消／已拒絕（`quotations.py:2605` 白名單；`PENDING_STATES=("待審核","簽核中")` `mc/content_fp.py:32`）。`deal_tag`：未標記／未提供／已提供／未成案／已成案／已結案（`quotations.html:343-349`、`quotations.py:3144-3152`）。成案前置：`status` 必須是「已送出」（`quotations.py:3144-3147`）；已結案只能從已成案進入（`:3150-3152`）。 |
| 下一個該誰動 | 報價單簽核：當層簽核人（在 `approval-queue.html` 處理，`B/routers/approval_queue.py:164`）；成案：admin／superadmin 手動標；結案：superadmin。 |
| 使用者重打的欄位 | 無（成案是改標籤）。但「執行進度階段」成案後前端 `_seedDefaultStagesIfEmpty()`（`F/js/case-management-core.js:389,500`）才用 API 建 5 個預設階段（不是後端成案時建立，推測：未逐行驗證後端是否另建）。 |
| 自動帶到下一步？ | 案件 = 同一列 `quotations`，以 `quote_no`（TEXT）做所有下游的鍵；**沒有 FK**，下游表只存 `quote_no` 字串。品項由 `data_json.items[]`（`id`、`description`、`brand`、`qty`、`unit`、`cost`）承載。成案時副作用：`notify_module_activity("報價單",…)`（`quotations.py:3183`）、背景 `push_event_for_quotation_won`（`:3186`，Google 行事曆）。**成案不通知採購／工程**（只有模組動態）。 |
| 斷點 | (a) 清單頁無「前往案件」連結（見上）；(b) `?q=` 只開案件、預設 `biz` 分頁、執行子分頁固定 `progress`（`case-management-core.js:172-181,935`），不能深連結到「材料申請」；(c) `case_stages` 無任何欄位連到材料／PO／派工（`B/db.py:1819-1832`），階段完成與到料互不影響。 |

### 1-2 派工（承攬商派發）——與材料線平行、不相交

| 項目 | 內容 |
|---|---|
| 頁面 | 案件頁「承攬商」分頁（`dispatch` tab）；管理頁 `F/pages/vendor-contractors.html`（承攬商公司）、`F/pages/contractors.html`（外包人員名冊）。案件頁表單內有一個文字提示連結「承攬商管理」`href="vendor-contractors.html"`（`case-management.html:4016`）。 |
| DB | `contractor_dispatches`（quote_no, vendor_id FK→vendor_contractors, items_json, total_amount, status…，`B/db.py:821-836`）；`vendor_contractors`（`B/db.py:807-819`）；`contractors`；`contractor_payment_vouchers`。 |
| API | `GET /api/vendor-contractors/selectable` `msub/api/vendor_contractors.py:299`；`POST /api/contractor-dispatches` `:607`；`PUT :653`；`POST /api/contractor-dispatches/{id}/submit|approve|reject|withdraw` `msub/api/dispatch_approval.py:287-305`；完工 `.../completion/request|approve|reject|withdraw` `:334-353`；`POST .../import-to-quote` `vendor_contractors.py:1264`；匯款憑據 `/api/contractor-vouchers…`（`F/js/case-management-dispatch.js:384-797`）。 |
| 權限 | `require_any_module(user, ('procurement','case_manage','contractor_list'),…)`（`vendor_contractors.py:278 等`）；建立／修改派發另需 `_require_admin`（`:611,666`）。側欄：`vendor-contractors.html`→`procurement`、`contractors.html`→`contractor_list`（`sidebar.js:582`、`msub/module.json` pages）。 |
| 狀態 | 作業狀態 `draft/sent/confirmed/pending_acceptance/accepted/completed/cancelled`；審核狀態兩段（派發、完工）各 `''/草稿/待審核/簽核中/已核准/已退回`（`msub/dispatch_flow.py:11-19`）。 |
| 重打欄位 | 派工品項 `description／qty／unit／unitPrice／note` 全部手打（`case-management-dispatch.js:144-165`，`items.push({…description:'',qty:1,unit:'式',unitPrice:''…})`）；**不是**從報價品項挑選。工作範圍 `scope` 另打。 |
| 自動帶入 | 只有反向：`import-to-quote` 把派發回推報價單品項。派工→材料無連結。 |
| 斷點 | 承攬商主檔與供應商主檔是兩張不同的表；PO 要付給「工班」或「材料商」用的是不同入口。 |

---

## 步驟 2　叫料／材料申請

### 2-0 真正的順序（程式強制）

`PO_REQUIRED = True`、`PO_REQUIRED_FROM="2026-10-04"`（`mc/material_approval.py:39-40`）：**新的材料申請必須由「已核准的採購單明細」帶入**；案件頁自己也寫明「新增材料申請：請從已核准的採購單明細帶入（需先申請請購單、再申請採購單）」（`case-management.html:2444`）。所以真實順序是：

案件 → 請購單 PR（核准）→ 採購單 PO（核准）→ 材料申請（再核准一次）→ 確認到貨 →（材料卡片勾已申購／已到料）。

### 2-1 請購單／採購單（`payment-request.html`）——使用者要「離開案件頁」才能做

| 項目 | 內容 |
|---|---|
| 頁面 | `F/pages/payment-request.html`（側欄「新增支出申請」，`mc/module.json` pages，group `mywork`，perm `quotation`）。**案件頁沒有任何連結到這頁**（grep `payment-request.html` 於 `F/js`、`F/pages`、`F/static` 除自身外零命中；案件頁只有連到 `payment-request-form.html`＝收款請款，`case-management.html:1903,2244`）。這頁也不收 `?quote_no=`，只認 `?tab=mine`（`payment-request.html:408`）。使用者要在頁內重新「搜尋案件」：`GET /api/extra-expenses/cases?q=`（`payment-request.html:416`）。 |
| DB | `case_extra_expenses`：`quote_no, kind, doc_code(PR-/PO-), data_json, lines_json, status, approval_json, payee_type/name/bank/account, pay_terms, remit_date, planned_pay_date, department_id…`（`B/db.py:3566-3588`；`mc/migrations/0003`、`0007`）。PR 欄位：applicant, dept, req_date, ptype, remark, urgency, need_period, lines[category,summary,qty,unitCost,amount,invoiceNo]（`purchase_req.json`）。PO 欄位：applicant, dept, req_date, **pr_no**, **vendor(text,必填)**, delivery_date, urgency, remark, lines[…], total, pay_terms, remit_date（`purchase_order.json`）。 |
| API | `GET /api/quotations/{no}/purchase-items`（品項挑選器）`mc/api/case_extra_expenses.py:458`；`GET .../purchase-requests/lines`（從 PR 帶入）`:482`；`POST /api/quotations/{no}/extra-expenses`（建立）`:499`；`PATCH …/{id}` `:565`；`POST …/{id}/submit` `:918`；`/approve` `:1006`；`/reject` `:1094`；`/void` `:859`；`/files` `:1209`；變更申請 `…/change-request*` `:1440-1738`；`GET /api/extra-expenses/mine` `:716`；`GET /api/expense-types`（`payment-request.html:597`）。 |
| 權限 | 建立：任何「看得到該案件」的登入者（`_guard_case`，`case_extra_expenses.py:308-320`；建立端點無模組檢查 `:499-520`）；編輯／刪除／送審：填寫人或 admin+（`_can_modify` `:323-327`）；核准／退回：當層簽核人，不要求 admin（檔頭註解 `:20-23`）。側欄入口需 `quotation` 模組。 |
| 狀態 | `草稿 → 待審核 → 簽核中 → 已核准`，退回為 `已駁回`（可再編輯再送審），另 `已作廢`（`case_extra_expenses.py:10-17,83-85`；`EDITABLE_STATUSES=("草稿","已駁回")` `:83`）。 |
| 下一個該誰動 | 申請人填單送審 → 當層簽核人（`approval-queue.html`）→ 核准後：PR 只供引用不進金流；PO `kind in _PAYABLE_KINDS` 進出納待付款（`expense_forms.py:21`；`mc/payables.py:79`）→ 出納填匯款日／付款條件（PO 核准後由出納填，`0003` 註解第 11 行）。 |
| 使用者重打的欄位 | 申請人／部門／日期（每張單都要填，ref 欄位）；PO 的**廠商（自由文字）**、**廠商銀行名稱／分行／帳號／戶名**（`payment-request.html:89-95` `pr-po-bank-block`）；品名／數量／單價雖可「從案件品項帶入」（`:100`）或「從請購單帶入」（`:218-243`），但需手動勾選。 |
| 自動帶到下一步？ | PR→PO：有，靠 `lines[].prDocCode/prLine` 與 `data.fromPr/pr_no`（`mc/purchase_items.py:317-336` `stamp_from_pr`、`check_from_pr`），價格可複製（有財務檢視權者）。品項→PR/PO：靠 `lines[].itemId`＝報價品項 id（`purchase_items.py:73-88,103-130`）。PO→材料申請：靠 `materialOrders[].poDocCode/poLine/quoteItemId`（見 2-2）。**廠商不帶**：PO 的 `data.vendor` 是文字，不連 `suppliers`。 |
| 通知 | 站內：`extra_expense_approval_request`（`:990,1074`）、`extra_expense_approved`（`:969,1081`）、`extra_expense_rejected`（`:1139`）、`extra_expense_voided`（`:909`）、`extra_expense_change_request/approved/rejected`（`:1639,1714,1782`）。信件：`expense_form_submitted/next_tier/approved/returned/payout_pending/paid`、`expense_change_approved/returned`（`mc/expense_notify.py:25-41`）。**沒有「PO 核准 → 通知採購下單」事件**，通知對象只有申請人與出納。 |
| 斷點 | 見斷點清單 #1、#3、#8。 |

### 2-2 材料申請（叫料）— 案件頁「財務」分頁

| 項目 | 內容 |
|---|---|
| 頁面 | `F/pages/case-management.html`，**位置在「財務」分頁 `#fin-material-orders`（`:2440`）**，不在「執行管理→材料申請清單」（那是材料卡片，見 2-3）。「從採購單明細帶入」鈕 `data-testid="ml-open-po"`（`:2450`）、「帶入已勾選」`ml-import`（`:2472`）、供應商下拉 `mo-supplier`（`:2523`）、送審／撤回／取消 `:2564-2568`、確認到貨 `mo-recv`（`:2576`）、撤銷到貨 `:2583`。前端邏輯 `F/js/case-management-exec.js`（`moSave` `:376`、`moSubmit` `:259`、`moReceive` `:281`）、`F/js/case-management-mlink.js`（`mlOpen` `:43`、`mlImport` `:82`、`_mlPush` `:97`）。 |
| DB | 列本體：`quotations.data_json.caseRecord.materialOrders[]`（itemId, itemName, quantity, unit, unitPrice, totalPrice, paidStatus/paidAmount/paidDate, notes, invoiceDate, **supplierId**, **quoteItemId, poDocCode, poLine**, overPlanReason；模型 `mc/api/material_orders.py:41-68`）。審核疊加表 `case_material_approvals`（PK quote_no+item_id；doc_code `MO-YYYYMMDD-NNNN`、status、approval_json、content_hash、received_on/by/at、cancel_*、version；`mc/migrations/0004_material_approvals.py`）。變更表 `case_material_changes`（doc_code `MC-…`，`0006`）。 |
| API | `PATCH /api/quotations/{no}/material-orders`（整份覆寫）`mc/api/material_orders.py:80`；`GET …/material-orders` `:251`；`PATCH …/material-orders/{item}/invoice-date` `:210`；`GET …/material-order-approvals` `mc/api/material_approvals.py:88`；`POST …/material-orders/{item}/submit|approve|reject|withdraw|cancel` `material_approvals.py:149,199,224,248,271`；`POST|DELETE …/receive` `:297,321`；`GET …/item-shipped` `:103`；採購單明細涵蓋：`GET …/material-po-lines|material-coverage|material-link-status` `mc/api/material_links.py:25,37,50`；變更申請：`GET …/material-changes` `mc/api/material_changes.py:101`、`POST …/changes` `:183`、`…/material-changes/{id}/revise|submit|approve|reject|withdraw` `:210-304`；供應商選單 `GET /api/material-suppliers` `mc/api/material_payments.py:179`。 |
| 權限 | **建立／修改材料申請**：admin／superadmin／財務角色／持 `project_manage` 模組，且 `material_money_visible`（admin/superadmin/sales/財務）（`material_orders.py:128-137`；`mc/material_guard.py:107-112`）；**純 `procurement` 模組使用者做不到**。送審：案件擁有者規則 `require_case`＋`material_money_visible`（`material_approvals.py:157-162`）。核准／退回：當層簽核人。取消已核准：財務角色／superadmin（`mc/material_approval.py:319-325`）。到貨確認：僅 `require_case`（`material_approvals.py:303`），不查模組。供應商下拉：`can_edit_orders` 或財務（`mc/api/material_payments.py:183-185`）。 |
| 狀態 | 材料申請：`草稿／待審核／簽核中／已核准／已退回`＋終態 `已取消`（`mc/material_approval.py:29-30`）。沒有疊加列＝舊單（`status_of` 回 `''`，`:134-136`）。變更申請：`草稿／待審核／簽核中／已核准／已退回／已撤回`（`mc/material_change.py:29-30`）。實質欄位（itemName, quantity, unit, unitPrice, totalPrice, supplierId, quoteItemId, poDocCode, poLine）核准後改動 ⇒ 退回草稿重送審（`material_approval.py:34`、`on_substantive_change` `:344-370`）。成本口徑 `cost_state`：草稿／退回／取消不計、待審／簽核中計入並標示、已核准計入（`:140-146`）。 |
| 下一個該誰動 | 申請人（能編輯者）儲存→送審；當層簽核人核准（`approval-queue.html`，單據類型 `material_order`，`material_approval.py:45-50`）；核准後：到貨確認由案件擁有者（業務／協作者／admin+）按；未設簽核層＝送審即核准（`submit` `:196-205`）。 |
| 使用者重打的欄位 | 供應商（**必選，`SUPPLIER_REQUIRED_ON_NEW=True`**，`material_approval.py:48`；`material_guard.py:241-242` 拒絕；`_mlPush` 帶入時 `supplierId:null`，`case-management-mlink.js:104`）——即使 PO 已打過廠商；到貨日期（`mo-recv-date`，預設今天）；超出計畫量原因（`overPlanReason`）；備註「供應商、單號…」`:2530 一帶 placeholder`。品名／數量／單價／小計已由採購單明細帶入，不需重打（`mlImport` `:82-96`）。 |
| 自動帶到下一步？ | PO→材料申請：複製（非 FK）——`mlImport` 把涵蓋快照 `{name, quantity, unit, unitPrice, totalPrice, quoteItemId, poDocCode, poLine}` 複製成新列（`mlink.js:82-110`）；送審時再存 `linkSnapshot.poSnapshot` 到審核列（`material_approval.py:196,205 一帶 link_snap`、`mc/material_coverage.py:23-33 snapshot_lines`）。分組單位：一個報價品項一組、額外採購以 PO 為單位（`mlink.js:62-70（mlGroupBlock／mlGroupText）`）。材料申請→材料卡片：**靠使用者手動選**（見 2-3）。 |
| 通知 | 站內：`material_order_approval_request`、`material_order_approved`、`material_order_returned`、`material_order_approval_notice`（`material_approvals.py:129-146` 的 `_notify_after`）；信件：`material_order_submitted/next_tier/approved/returned`（`mc/material_notify.py:19-25`）。**到貨確認、撤銷到貨：只寫稽核，沒有任何通知**（`material_approvals.py:297-345`）。 |
| 斷點 | 見 #2、#4、#6、#7。 |

#### 2-2a 匯款申請（`material_payments`）——新單基本上走不到

| 項目 | 內容 |
|---|---|
| 入口 | 材料申請卡「＋開匯款申請」`mo-pay-new`（`case-management.html:2597`），條件 `moCanRequestPay`：`m.poDocCode` 有值就 `return false`（`F/js/case-management-exec.js:151-157`）；後端同規則 409：「這筆材料申請已對應採購單 …請走採購單的請款流程，不能另開匯款申請」（`mc/material_payment.py:280-281`）。因為新單強制對應採購單，**這條只剩舊單可用**。 |
| API／表 | `POST /api/quotations/{no}/material-orders/{item}/payments` `mc/api/material_payments.py:217`；`PATCH /api/material-payments/{pid}` `:264`；`…/submit|approve|reject|withdraw|void` `:287-399`；表 `case_material_payments`(doc_code `MP-…`、supplier_id、amount_approved、snapshot_json、status)、`case_material_payment_lines`（`mc/migrations/0005`）。 |
| 權限 | 建立／修改／送審：**財務角色／superadmin**（`_need_edit`，`material_payments.py:58-61`）。 |
| 狀態 | `草稿／待審核／簽核中／已核准／已退回／作廢`（`mc/material_payment.py:36`）。 |
| 重打欄位 | 銀行代碼、銀行名稱、戶名、帳號（`case-management.html:2628` 一帶）＋「已告知收款人」勾選（`:2641`）。原因：**供應商主檔沒有銀行欄位**（`mc/material_payment.py:195-196` 註解「沒有銀行欄位，帳戶一律填在申請上」）。 |
| 通知 | `material_payment_submitted/next_tier/approved/returned`（`material_notify.py:29-35`）；站內 `material_payment_approval_request/approved/returned`。 |

### 2-3 材料卡片（執行管理→材料申請清單，`caseRecord.materials[]`）

| 項目 | 內容 |
|---|---|
| 頁面 | `case-management.html:1126`（`execSubTab==='materials'`）；入口：案件→「執行管理」→子分頁「材料申請」（`module.json` customization.subtab `materials`）。「從報價單匯入」`:1130`、「新增品項」`:1251`。 |
| DB | `quotations.data_json.caseRecord.materials[]`：`id, name, model, qty, unit, ordered, arrived, devices[], note, supplier(文字), expectedDate, orderItemId, poLink{key,poDocCode,docCodes,name,vendor,arrivedOn,…}, files[], invoiceFiles[]`（`exec.js:1076-1094`；`mc/material_recognize.py:1-30`）。 |
| API | 沒有專屬端點：隨案件存檔 `PATCH /api/quotations/{no}/case-record`（`mc/api/quotations.py:3598`）寫入，伺服器端由 `material_guard.enforce` 把關（`mc/material_guard.py:1-30`）；附件 `POST /api/quotations/{no}/materials/{idx}/files|invoice-files` `quotations.py:4623,4687`。 |
| 權限 | 能存案件的人皆可改卡片欄位；但旗標 `ordered/arrived` 由 false→true 必須有 `orderItemId` 指到**已核准**材料申請，`arrived` 另需該申請已「確認到貨」（`material_guard.py:17-18,403-408`；前端 `matCanTick` `exec.js:287-299`）；認列採購單 `poLink`：預設**只有最高管理者**（`material_recognize.py:12,84`；非最高管理者嘗試 ⇒ 整件取消＋寄信 `material_recognize_denied` 給最高管理者，`material_notify.py:49`）。 |
| 狀態（卡片標籤） | `待材料申請 / 材料申請中 / 到料`（`case-management.html:1151-1152`），由 `ordered/arrived` 旗標推得。 |
| 重打欄位 | 手動「新增品項」要打品名／廠牌型號／數量／單位（`exec.js:1076-1079`）；「從報價單匯入」複製 `description→name, brand→model, qty, unit`（`exec.js:1086-1095`）但**不存 quoteItemId**。「廠商名稱」「預計到料日」又打一次（`case-management.html:1196-1203`，`mat.supplier`／`mat.expectedDate`，與 PO 的 vendor／delivery_date、材料申請的 supplierId 重複）。到貨時 SN／MAC 逐台打（`:1217-1229`）。 |
| 自動連結 | 卡片→材料申請：使用者在下拉「對應材料申請」手選 `orderItemId`（`:1159`）；或系統用**品名／型號字串正規化比對**列出可認列的 PO 分組（`mlCandidatesFor`，`mlink.js:124-130`，用 `_mlNorm(name)` 比對 `g.name`），恰好一個候選才出現一鍵「帶入並連結」（`:1171`）。 |
| 斷點 | 見 #2、#5、#9。 |

---

## 步驟 3　採購

### 3-1 「採購管理」頁 `procurement.html`——純唯讀彙總

| 項目 | 內容 |
|---|---|
| 頁面 | `F/pages/procurement.html`（側欄 group `supply`、perm `procurement`，`B/modules/analytics/module.json:27-28`；`sidebar.js:585`）。 |
| 資料來源 | `GET /api/materials-summary`（`B/modules/analytics/api/dashboard.py:751`）：掃全部有 `caseRecord` 的報價單，攤平 `caseRecord.materials[]`（**材料卡片**，不是材料申請也不是 PO），狀態由旗標推：`arrived→arrived`、`ordered→ordered`、否則 `pending`（`dashboard.py:778`）。回傳還含 `recognized`（poLink）但頁面沒顯示。 |
| DB | 無自有表。讀 `quotations.data_json.caseRecord.materials`。 |
| 權限 | `require_any_module(user,('procurement','case_manage'),…)`（`dashboard.py:756`）；**無逐案可見過濾**（看全部案件的材料卡片）。 |
| 狀態值（此頁自己的字彙） | `待採購／已下單待料／已到料`（`procurement.html:88-103`）——和材料卡片（待材料申請／材料申請中／到料）、材料申請（草稿…已取消）、PO（草稿…已作廢）四套詞彙不一致。 |
| 動作 | **只有一個**：每列「材料申請 →」連結到 `case-management.html?q=<quoteNo>`（`procurement.html:117,172`）。沒有建 PO、沒有下單、沒有到料登錄。 |
| 下一個該誰動 | 頁面不指派任何人；採購看到「待採購」後，必須自行：①跳到 `payment-request.html` 開 PR／PO；②等簽核；③回案件頁用業務／admin 帳號做材料申請。 |
| 重打 | 搜尋框純前端過濾。 |
| 斷點 | 見 #1、#2、#8、#10。 |

### 3-2 PO 之後的付款（出納）

PO 核准後自動進出納待付款（IP-100 `payables.pending`，`mc/payables.py:1-20,79`；出納頁 `F/pages/cashier.html`）。缺廠商收款帳戶可擋付款（`system_settings.po_bank_block_since`，`mc/payables.py:24-60`、`case_extra_expenses.py:669-716`）。

### 附錄 3-A　庫存補貨線（與案件採購完全獨立）

| 項目 | 內容 |
|---|---|
| 頁面 | `F/pages/inventory.html`（側欄 `inventory`，`ms/module.json`）。採購建議列「標記已下單」「標記已到貨」`inventory.html:380-388`。 |
| 表 | `purchase_suggestion_status(part_no PK, status 'suggested'|'ordered'|'received', ordered_at…)`（`B/db.py:4028`）；`stock_batches(batch_no, part_no, supplier_id, supplier_name, invoice_no, is_paid…)`（`B/db.py:2595`）；`stock_items`；`parts`。 |
| API | `GET /api/inventory/purchase-suggestions` `ms/api/inventory.py:140`；`POST …/{part_no}/status` `:278`；`POST /api/inventory/batches` `:412`；`POST …/{batch}/paid-toggle` `:565`。 |
| 權限 | `require_any_module(user,('inventory','procurement','case_manage','netplan_edit'))`（`inventory.py:159,296,415…`）；建立批次另 `_require_admin`（`:416`）。 |
| 與案件採購的關係 | 無：建議量依安全庫存缺口，供應商取「最近一筆進貨批次」（`inventory.py:140-175` docstring）；不產生 PO／材料申請；批次有自己的「已付款」開關（`stock_batches.is_paid`），與出納 PO 付款是**第二條付款線**。 |

---

## 步驟 4　供應商

| 項目 | 內容 |
|---|---|
| 頁面 | `F/pages/suppliers.html`（清單＋詳情，側欄 group `supply`、perm `procurement`、active 含 `supplier-log.html`，`ms/module.json` pages）；`F/pages/supplier-log.html`（拜訪日誌，由 `suppliers.html?:252,357-394,922` 的「日誌」連結進入 `supplier-log.html?id=<sid>`）；`vendor-contractors.html`、`contractors.html`（見步驟 1-2，是別的主檔）。 |
| 從上一步怎麼進來 | **沒有任何入口從步驟 3 或案件頁導向供應商頁**：`suppliers.html`、`supplier-log.html` grep「採購／材料／叫料／purchase／案件」只命中前置時間說明文字（`suppliers.html:673,678,1313`）；`procurement.html` 無供應商欄位也無連結。材料申請的供應商下拉走獨立端點 `GET /api/material-suppliers`（`mc/api/material_payments.py:179`）。 |
| DB | `suppliers`：`id, code(S-…唯一), name, tax_id, phone, lead_time_days, data_json{alias, tags, category, contact, currency, paymentTerms, website, contacts[], visits[], customFields…}, created_at, updated_at`（`B/db.py:646-654`、`:1437-1463`、`:4023-4024`）。**沒有銀行欄位**（`mc/material_payment.py:195-196`）。 |
| API | `GET /api/suppliers` `ms/api/suppliers.py:80`；`POST` `:107`；`PUT /{sid}` `:144`；`DELETE /{sid}` `:176`；`PATCH /{sid}/visits` `:196`；個資告知 `GET …/privacy-notice` `:249`、`POST …/contacts/{ctid}/privacy-notice/ack` `:263`。 |
| 權限 | 能力鍵 `supply.supplier.view/create/edit/delete`，legacy 為 `customer`／`procurement`／`inventory` 任一模組（`ms/module.json` capabilities；`suppliers.py:83,109,146,178`）。**但 `GET /api/suppliers` 對非 admin／superadmin 直接回 `[]`**（`suppliers.py:84-85`；`suppliers.html:873` 註解自己承認「非管理員的 /api/suppliers 本來就回空清單」）。 |
| 狀態 | 無狀態機（`active` 欄位為啟用／停用，屬 data_json）。 |
| 重打欄位 | 新增供應商時可用統編查公司名稱（`/api/company/tax/{id}`，`suppliers.html:1086`）；其餘全手打。收款帳戶不在此主檔，每次 PO／匯款申請重打（見 2-1、2-2a）。 |
| 被引用的地方（皆無 FK） | `materialOrders[].supplierId`（JSON 內）；`case_material_payments.supplier_id`；`stock_batches.supplier_id`。PO 與材料卡片只存文字。 |
| 斷點 | 見 #3、#5、#11、#12。 |

---

## 狀態機與通知事件總表

### 狀態機

| 單據 | 狀態值 | 來源 |
|---|---|---|
| 報價單 status | 草稿／待審核／簽核中／已送出／已取消／已拒絕 | `mc/api/quotations.py:2605`、`content_fp.py:32` |
| 案件 deal_tag | 未標記／未提供／已提供／未成案／已成案／已結案 | `quotations.py:3144-3152`、`quotations.html:343-349` |
| 請購單／採購單（case_extra_expenses） | 草稿／待審核／簽核中／已核准／已駁回／已作廢 | `case_extra_expenses.py:10-17,83-85` |
| 變更申請（支出單據） | change_status：草稿／待審核／簽核中／已駁回 | `B/db.py:3615-3641（_m076）、case_extra_expenses.py:1300` |
| 材料申請 | 草稿／待審核／簽核中／已核准／已退回／已取消（''=舊單） | `mc/material_approval.py:29-30` |
| 材料申請變更 | 草稿／待審核／簽核中／已核准／已退回／已撤回 | `mc/material_change.py:29-30` |
| 材料匯款申請 | 草稿／待審核／簽核中／已核准／已退回／作廢（付款明細另有 remit_review pending/approved） | `mc/material_payment.py:36-40` |
| 材料卡片旗標 | ordered／arrived（布林，由閘門驗證） | `mc/material_guard.py:35,403-408` |
| 承攬商派發 | 作業 draft…cancelled；審核兩段 草稿…已退回 | `msub/dispatch_flow.py:11-19` |
| 採購建議（庫存線） | suggested／ordered／received | `B/db.py:4028-4037` |
| 到料（procurement.html 顯示） | pending／ordered／arrived（由材料卡片旗標推得） | `dashboard.py:778` |

### 通知事件（mail_types key／站內通知 type）

| 範圍 | 信件 key | 站內通知 type | file:line |
|---|---|---|---|
| 報價單 | approval_request, next_tier, approved, returned, approval_review_edit | — | `B/helpers/mail_types.py:100-130`；`mc/review_edit_notify.py:20` |
| PR／PO（費用單據） | expense_form_submitted, expense_form_next_tier, expense_form_approved, expense_form_returned, expense_form_payout_pending（→出納）, expense_form_paid, expense_change_approved, expense_change_returned | extra_expense_approval_request, extra_expense_approved, extra_expense_rejected, extra_expense_voided, extra_expense_change_request/approved/rejected | `mc/expense_notify.py:25-41`；`case_extra_expenses.py:909-1785` |
| 材料申請 | material_order_submitted, material_order_next_tier, material_order_approved, material_order_returned | material_order_approval_request, material_order_approved, material_order_returned, material_order_approval_notice | `mc/material_notify.py:19-25`；`material_approvals.py:129-146` |
| 材料匯款 | material_payment_submitted/next_tier/approved/returned | material_payment_approval_request/approved/returned | `material_notify.py:29-35`；`material_payments.py:68-82` |
| 材料變更 | material_change_submitted/next_tier/approved/returned | （同模式） | `material_notify.py:39-45` |
| 材料卡片認列被拒 | material_recognize_denied（收件：最高管理者） | — | `material_notify.py:49-51` |
| 預定付款日 | payable_due_soon/today/overdue（→財務） | — | `mc/payable_reminders.py:41-45` |
| 發票上傳 | case_invoice_uploaded（→財務＋最高管理者） | — | `mc/invoice_notify.py:25` |
| 承攬商派發 | dispatch_submitted/next_tier/approved/returned、dispatch_completion_* | — | `msub/dispatch_notify.py:17-31` |
| **缺口（沒有事件）** | 成案→通知採購／工程；PO 核准→通知採購下單；材料申請到貨確認；PO／材料申請撤銷；供應商資料異動 | — | 上列檔案皆無對應 `register`／`_notify`（`material_approvals.py:297-345` 到貨確認只 `_audit`） |

簽核人統一在 `F/pages/approval-queue.html`（`B/routers/approval_queue.py:164`）處理；簽核層由設定中心「簽核設定」決定（`resolve_active_flow_setting(DOC_TYPE)`，`material_approval.py:196`）。

---

## 斷點清單

嚴重度：高＝流程斷裂或使用者實際做不到；中＝要切頁／重打／易錯；低＝語意或可視性瑕疵。

| # | 斷點（什麼） | 位置 file:line | 嚴重度 |
|---|---|---|---|
| 1 | **建請購／採購單必須離開案件頁**：案件頁沒有任何連結到 `payment-request.html`，該頁不收 `?quote_no=`、要重新搜尋案件；而材料申請又強制必須有已核准 PO，案件頁只有一行文字提示。 | `F/pages/case-management.html:2444`（提示）、`F/pages/payment-request.html:408,416`（只認 tab、重搜案件）；案件頁連結僅 `payment-request-form.html`（`:1903,2244`） | 高 |
| 2 | **同一筆採購被核准兩次再各自重複記錄**：PO（核准）→ 材料申請（`PO_REQUIRED` 強制從已核准 PO 帶入，內容是複製快照）→ 再核准；到貨又要在材料申請確認、再到材料卡片勾旗標、並可能再填 `poLink.arrivedOn`。三處「到貨」（`received_on`／`materials[].arrived`／`poLink.arrivedOn`）與兩處簽核。 | `mc/material_approval.py:39-40`、`:396-420`；`case-management.html:1185,1211`；`material_guard.py:403-408`；`mlink.js:82-110` | 高 |
| 3 | **供應商主檔對採購者是空的／不連動**：`GET /api/suppliers` 對非 admin 回 `[]`，但側欄「供應商管理」以 `procurement` 模組開放；PO 廠商是自由文字、不連 `suppliers`；供應商頁沒有「相關採購單／材料申請」；刪除供應商不檢查被 `materialOrders.supplierId`／`case_material_payments.supplier_id`／`stock_batches.supplier_id` 引用。 | `ms/api/suppliers.py:83-85,176-193`；`suppliers.html:873`；`ms/module.json` pages；`B/helpers/expense_type_defs/purchase_order.json`（vendor=text） | 高 |
| 4 | **PO 已有廠商，材料申請仍要重選供應商（必填）**：`mlImport` 把 `supplierId` 置 null，後端 `SUPPLIER_REQUIRED_ON_NEW=True` 拒絕未選者；PO 廠商文字與所選 supplierId 不做一致性檢查（推測：未發現比對程式）。 | `mlink.js:104`；`material_approval.py:48`；`material_guard.py:241-242`；`exec.js:387` | 中 |
| 5 | **材料卡片與材料申請／PO 的連結靠手選或字串比對**：卡片「從報價單匯入」不存 `quoteItemId`；候選 PO 以品名／型號正規化字串比對；只有恰好一個候選才一鍵連結。認列 `poLink` 預設只有最高管理者能做，其他人按了整件被取消並寄「被拒」信。 | `exec.js:1086-1095`；`mlink.js:124-130`；`case-management.html:1159-1171`；`material_recognize.py:12,84`；`material_notify.py:49` | 高 |
| 6 | **角色對不上**：建立／修改材料申請需 admin／財務／`project_manage` 且有財務檢視；純 `procurement`（採購）角色只能看 `procurement.html`，無法執行下一步；採購也非案件成員時連案件頁都開不了（逐案 `CASE_ACCESS` 不含 procurement）。 | `material_orders.py:128-137`；`material_guard.py:107-112`；`B/helpers/case_access.py:117-125`；`dashboard.py:756`（materials-summary 無逐案過濾，卻導向案件頁） | 高 |
| 7 | **匯款申請通道對新單已關閉**：新單強制連 PO ⇒ `moCanRequestPay` 回 false，付款走 PO 請款；材料申請上的匯款區塊、`case_material_payments` 全套（含 4 個信件事件）只服務舊單；而供應商無銀行欄位，兩條路都要手打帳戶。 | `exec.js:151-157`；`mc/material_payment.py:195-196,280-281`；`payment-request.html:89-95` | 中 |
| 8 | **採購管理頁是死胡同**：`procurement.html` 只讀材料卡片旗標，唯一動作是連到 `case-management.html?q=`，但 `?q=` 只開 `biz` 分頁，執行子分頁固定 `progress`，要再手點「執行管理→材料申請」；頁面的三態（待採購／已下單／已到料）與其他單據詞彙不一致，且來源是「卡片旗標」而非 PO／材料申請狀態。 | `procurement.html:117,172`；`dashboard.py:751-791`；`case-management-core.js:90-98,172-181,935` | 高 |
| 9 | **同一資訊在卡片、材料申請、PO 各打一遍**：廠商（`mat.supplier`／`supplierId`／PO `vendor`／`poLink.vendor`）、預計到貨（`mat.expectedDate`／PO `delivery_date`）、申請人與部門（每張 PR／PO 重填）、備註「供應商、單號…」。 | `case-management.html:1196-1203,2530`；`purchase_order.json`；`purchase_req.json` | 中 |
| 10 | **缺少事件／通知**：成案不通知採購；PO 核准只通知申請人與出納，沒有「請採購下單」；材料申請核准只通知申請人；到貨確認無任何通知（只寫稽核）。採購要靠自己盯 `procurement.html` 或簽核佇列。 | `quotations.py:3183`（僅模組動態）；`case_extra_expenses.py:969-1085`；`material_approvals.py:129-146,297-345` | 中 |
| 11 | **報價品項 id 為唯一的主幹連結，但斷在卡片層**：PR／PO／材料申請靠 `itemId`／`quoteItemId` 串起計畫量；材料卡片（採購頁讀的那層）不帶 `quoteItemId`，所以「報價品項→採購進度」在 `procurement.html` 無法呈現，只能以字串比對。 | `purchase_items.py:36-48,103-130`；`exec.js:1086-1095` | 中 |
| 12 | **三個廠商主檔且互不連**：`suppliers`／`vendor_contractors`／`contractors`，各有一頁、各自的編碼（S-/V-）、各自的隱私告知；PO 廠商文字不指向任何一個；派工與採購兩種「叫外面做事」走完全不同單據與簽核（`dispatch_approval` vs `extra_expense`）。 | `B/db.py:646,807,1437-1463`；`msub/api/vendor_contractors.py:278`；`case-management.html:4004-4016` | 中 |
| 13 | **庫存補貨線獨立於案件採購**：`purchase_suggestion_status`／`stock_batches` 有自己的「已下單／已到貨／已付款」開關與供應商，不產生 PO、不經簽核、不進出納 PO 付款流程；同一個倉庫料號可能被案件 PO 與庫存建議各採購一次而互不知情。 | `ms/api/inventory.py:140-175,278,412,565`；`B/db.py:2595,4028` | 中 |
| 14 | **材料資料沒有資料表**：`materials[]`／`materialOrders[]` 存在 `data_json` 整份覆寫（`PATCH /material-orders` 為整份取代），需靠 `material_guard` 與 `save_quotation_json` 雙重閘維持不變式；任何要做跨案「單一管線」報表都得掃全部案件 JSON（`materials-summary` 即如此）。 | `material_orders.py:1-24,80-93`；`material_guard.py:1-30`；`dashboard.py:760-777` | 低（對提案是技術債，非使用者斷點） |
| 15 | **階段（case_stages）與材料／採購／派工無任何關聯欄位**：「施工」階段完成不看到料、不看派工；階段看板 `case-stage-board.html` 只連回案件頁。 | `B/db.py:1819-1832`；`case-stage-board.html:484` | 低 |
