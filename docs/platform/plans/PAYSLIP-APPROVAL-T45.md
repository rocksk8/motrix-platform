# 勞報單送審流程＋出納待付款整合＋派發雙向連結（第 45 班設計）

> 狀態：**設計／分析，無程式碼**。作者 hichan-c0，2026-10-07；分支 `wip/t45-payslip-design`（自 origin/platform 036565879，prod 基準 89206122）。
> 涉流程、權限、金額可見：**寫碼前先問使用者**（第 7 節列出待裁示項；🔴＝權限／金額可見）。
> 讀的碼：`backend/modules/payroll/api/payslips.py`、`payslip_payouts.py`、`remit_link.py`、`pdf_gen.py::generate_payslip_pdf_bytes`、`frontend/pages/payslips.html`／`payslip-form.html`、`arap/api/cashier.py`、`case/payables.py`、`helpers/tiered_approval.py`、`payroll/api/bonus.py`（簽核樣板）、`case/material_approval.py`、`subcontract/api/contractor_vouchers.py`。

## 0. 摘要

| # | 結論 |
|---|---|
| 1 | **在程式裡找不到「匯出要求付款日」**：匯出 API、PDF 範本、`payslip-form.html` 的匯出流程都沒有付款日欄位或檢查；付款日只出現在出納 `mark-paid`。使用者看到的很可能是別處（第 1 節列出三個候選，請使用者指出畫面）。我們仍把「匯出不得需要付款日」寫成守門測試。 |
| 2 | 新增狀態 `待審核`、`已核准`（兩個）；**退回＝回草稿**（同獎金分潤）。匯出只准 `已核准` 之後。既有 `已匯出／已簽回／已付款／已作廢` 一律不動。 |
| 3 | 簽核重用獎金分潤樣板（`approval_flow_setting_key("payslip")`、最高管理者限定、無簽核層＝送審即核准、自核規則照 `tiered_approval`）。 |
| 4 | 出納：**建議把勞報單登記進 IP-100 `payables.pending`（名稱 `payroll_payslip`）**，取代並最終退役 IP-103 頁籤；核准後即出現（標「待簽回」），**付款仍須已簽回**。預定付款日／行事曆待辦與第 45 班同一套。 |
| 5 | 派發↔勞報單：**現有只有單向、且在匯款單層**（匯款單 `personnel[].payslipNo`）。建議新增**連結表**（一派發對多勞報單），兩頁互相可點。 |
| 6 | 必要 migration：payroll 0004（只加欄位／表，可回退）；零驚喜：既有 草稿 要多按一次送審（沒設簽核層＝一鍵核准）。 |

## 1. 「匯出要求付款日」查證（逐層）

| 層 | 位置 | 結果 |
|---|---|---|
| UI 匯出 | `payslip-form.html` `confirmExport()`（約 L868）→ `POST /api/payslips/{no}/export`，不帶 body；`previewPdf()` 前檢查只有「請先儲存草稿」 | 無付款日 |
| UI 存檔前檢查 | `payslip-form.html` L804–806：受領人姓名、勞務內容、應付總額 > 0 | 無付款日（有「開單日期 `slipDate`」，預設今天，不擋） |
| API | `payslips.py::record_export`：只檢查存在與非已作廢，寫 `export_count／export_log`、存 PDF 封存、`草稿→已匯出` | 無付款日 |
| PDF 範本 | `pdf_gen.py::_build_payslip_html`（L770–945）欄位：單號、`slipDate`、服務期間、金額…；**沒有付款日欄**（`payableDate／匯款日期` 只在承攬商匯款單／請款單 PDF，L1639、L1666） | 無 |
| 唯一要付款日處 | `payslips.py::payslip_mark_paid`（`payment_date` 必填、`voucher_no` 必填並驗 `voucher.by_no`）；出納頁勞報單頁籤 | 這裡才要，且發生在 **已簽回 → 已付款** |

使用者感受到「匯出要付款日」的**候選**（請使用者確認，需回報畫面）：① 出納頁／勞報單頁在匯出之後還有一步要填付款日＋傳票單號（流程上看起來像匯出的延伸）；② `開單日期` 欄被當成付款日；③ 他看的是承攬商匯款單 PDF（有「應付款日期」「匯款日期」欄）而不是勞報單。
**處置**：不新增任何付款日要求；加守門 `test_payslip_export_needs_no_payment_date`（匯出 API 不帶任何日期、PDF 文字層不含「付款日／匯款日期」），避免以後被加回去。

## 2. 狀態機

現況（`_LOCKED_STATUSES＝已匯出／已簽回／已付款／已作廢`；`草稿` 可改可刪）：

```
草稿 ─匯出→ 已匯出 ─上傳簽回檔→ 已簽回 ─出納 mark-paid→ 已付款
                │  ↑unsign(退回簽回)        ↑ unpay
                └─void→ 已作廢（僅已匯出可作廢）
```

提案：

```
草稿 ─送審→ 待審核 ─(逐層簽核)→ 已核准 ─匯出→ 已匯出 ─簽回檔→ 已簽回 ─出納→ 已付款
  ↑            │退回（必填原因）                              (void／unsign／unpay 不變)
  └────────────┘ 回草稿（approval 歷史保留在 approval_json／稽核）
```

- 新值只有 `待審核`、`已核准`。簽核層進度放 `approval_json.currentTier`（同獎金分潤；**不**另開「簽核中」值，少一個狀態＝少一組守門）。
- 可編輯：`草稿`、（`待審核`→編輯＝撤回並重簽，同獎金分潤「簽核中改動⇒重簽」）；`已核准` 起鎖定（併入 `_LOCKED_STATUSES`）；已核准後想改＝作廢重開（沿用「已匯出可作廢」邏輯，**待問**：已核准、尚未匯出，是否也允許「撤回核准」？見 Q5）。
- 匯出：`record_export` 允許來源狀態＝`已核准`、`已匯出`（重匯）；`草稿／待審核` ⇒ 409「請先送審並核准」。**匯出不要付款日**。
- 作廢：維持「只有已匯出可作廢」；`已核准` 若要作廢（未匯出）見 Q5。
- 簽回：仍只收 `已匯出／已簽回`（簽回＝受領人簽名，是付款憑據；見第 4 節）。
- `GET /api/payslips` 的 `status` 值多兩種；前端列表徽章、篩選補兩個色。

## 3. 簽核基礎設施重用

- **樣板：獎金分潤（`bonus.py`）而非承攬商匯款單**——兩者都是「最高管理者才看得到金額」的單據。勞報單所有端點現為 `require_superadmin=True, module='payslip'`（`payslips.py` 全檔），簽核人必然是最高管理者。
- 重用原語（`helpers/tiered_approval.py`）：`setting_to_active_tiers`、`check_approve_permission`、`sign_first_pending`、`cascade_self_tiers`、`check_reject_permission`、`require_reject_reason`、`check_no_tier_self_approval`、`approval_flow_setting_key`、`register_doc_type`。
- 單據類型代碼 `payslip`（標籤「勞報單」）。**不進統一流程**（同 `bonus`：預設自己一條 `payslip_approval_flow`，可勾選併入；理由同 `tiered_approval.py` L61–65：先做可逆的一邊）→ 簽核設定頁會多一列。
- 鏈解析：`_resolve_payslip_tiers`＝`_resolve_bonus_tiers` 同型：鏈上出現非最高管理者（含代理人解析）⇒ 400（W1）。送審人部門主管層若非最高管理者 ⇒ 同樣 400（與獎金分潤一致）。
- **沒設簽核層 ⇒ 送審即核准**（同 `material_approval`、額外支出 `submit` 自動核准分支）。
- **自核（Q3）**：`check_no_tier_self_approval`＋`cascade_self_tiers`：唯一的最高管理者送審、鏈上只有他 ⇒ 依既有規則（獎金分潤現況）處理；不新增規則。
- 「待我簽核」佇列：新增提供者 `("approval.queue_items","payroll_payslip")`（比照 `bonus_queue.py`；`payroll/__init__.py` ModuleSpec.providers），詳情欄位**不含身分證／地址／電話／銀行帳號**（F2，同 IP-103），金額只給有權者（本單據全員為 superadmin，故不需 `filesNeedMoneyView`）。
- 端點（`payslips.py`，皆 `require_superadmin, module='payslip'`）：`POST /{no}/submit`、`/approve`、`/reject`（body.reason 必填）。權限＝當層簽核人／代理人或 superadmin（`check_*_permission`）。
- 稽核：`payslip.submit／approve／reject`（`_audit`，沿用 `_asum` 不放金額以外的個資）；歷史列寫 `approval_json.history`。

## 4. 核准後推給出納（IP-100 整合）

現況：出納頁已有「勞報單待付款」頁籤＝IP-103 `payslip.payables`（`GET /api/cashier/payslip-queue`，列 `status='已簽回'`）；付款打勞報單自己的 `POST /api/payslips/{no}/mark-paid`（付款日＋**必填**傳票單號並驗證）。與 IP-100（`payables.pending`，額外支出／材料匯款，有預定付款日、行事曆待辦）是**兩條平行的路**。使用者要求「核准後 push 給出納、與出納待付款申請（IP-100）結合、與預定付款日一併設計」。

**建議（方案 B）**：新增 IP-100 提供者 `payroll_payslip`（`ModuleSpec.providers[("payables.pending","payroll_payslip")]`，`modules/payroll/payslip_payables.py`）：

| 項目 | 設計 |
|---|---|
| 列出 | 狀態 `已核准／已匯出／已簽回` 且未付款（已作廢不列）。形狀＝IP-100 既有欄位：`key＝單號`、`sourceLabel＝勞報單`、`title＝勞報單 PS-… 受領人`、`amount＝實付 net`（現金出的是 net，扣繳另繳；不含 gross 以免混淆，gross/tax 放 `extra`）、`payee＝受領人姓名`、`requestedBy`、`approvedAt`、`files＝簽回檔名`、`plannedPayDate`、`kind＝'payslip'`。**不回**身分證／地址／電話／銀行帳號（F2；銀行資料走既有「收款資料」遮蔽端點 `payee-bank`，權限同 IP-100）。 |
| 「待簽回」旗標 | 新增加法欄位 `blocker`（如 `"待簽回"`）：未簽回的列顯示但**付款鈕停用**；`mark_paid` 後端也擋（409「須已簽回」），不只靠前端。 |
| 付款 | IP-100 `mark_paid(conn, key, paid_date, user, remit)` 委派到**同一份實作**（把 `payslip_mark_paid` 的核心抽成函式 `mark_payslip_paid(conn, slip_no, payment_date, voucher_no, who)`；兩個入口只剩薄殼，避免「同一動作兩份實作」）。傳票單號仍必填並驗 `voucher.by_no`（IP-4）：IP-100 目前 `remit` 沒有 `voucherNo` 欄 ⇒ 加法擴充 `remit.voucherNo`（契約版本不變，同 A2-3 追加慣例）。 |
| 付款日 | 只在出納這步填（`paid_date`）；`payment_date` 仍是 IP-9 營運報表歸月依據（`payslip_payouts._expense_entries`），行為不變。 |
| 預定付款日 | `payslips` 加 `planned_pay_date`（YYYY-MM-DD，可空），送審時可填、核准後出納可改（比照 `PATCH …/extra-expenses/{id}/planned-pay-date`）。**行事曆 `payable_due`**：key＝`payroll:<單號>`，核准時 upsert、改日期移動、付款／作廢／清空刪除（`push_event_upsert_for_module`／`push_event_delete_for_module`，commit 之後）；事件**不含金額、不含受領人姓名**（只寫「勞報單待付款 PS-…」）。🔴 現有 `EVENT_TYPES` 描述寫「不含勞報單付款」（`expense_payout`）與使用者 2026-09-29 的「勞報單不進行事曆」類裁示有關，**要使用者明確裁示勞報單可以進 `payable_due`**（Q7）。 |
| 與匯款單路徑 | 勞報單若被承攬商匯款單關聯（`personnel[].payslipNo`），付款走**匯款單**（`remit_link.mark_paid`，付款日＝匯款日、`data_json.paid_via_remit`）。此時 IP-100 列表要**標示「經匯款單 {號} 付款」並停用獨立付款**，否則同一筆錢可被出納付兩次（今天 IP-103 的 `unpay` 已用 `paid_via_remit` 擋回頭路，但正向沒有擋）。 |
| 簽回仍在付款之前？ | **建議是**：簽回檔＝受領人簽名的付款憑據，現制 `mark-paid` 即要求 `已簽回`；本次需求未說要取消。因此出納**在核准後就看得到**（排程、預定付款日），但**付款鈕在已簽回才亮**。Q4 請使用者確認是否要允許「未簽回也能付」（會動法規／內控，不建議預設）。 |
| 權限 🔴 | IP-100 端點用 `has_finance_access`（財務角色＋superadmin，第 42 班）；IP-103／`_require_payer`／`get_signed_file` 仍用 `role=='superadmin' or user_has_module(user,'cashier')`（`cashier.py::_payslip_visible`、`payslips.py::_require_payer`）——**與第 42 班「出納／財務合併」不一致**（舊 cashier 模組勾選）。整合時兩者必須對齊其一。Q1：勞報單（含扣繳金額）財務角色看不看得到？ |
| IP-103 退役 | 先並存（舊頁籤＋端點照舊、IP-103 守門不動），IP-100 版上線並驗收後，下一班移除頁籤（與「額外引用疊加」原則一致；不在本班刪）。 |
| 出納通知 | 核准時：站內通知＋信給 `finance_usernames(conn)`（在職財務角色＋superadmin）：「勞報單 PS-… 已核准，待簽回／待付款」；已簽回時再一次「待付款」。信內**不放金額**（同 `expense_notify`）。 |

方案 A（保留 IP-103，只在核准時多通知出納）較小，但「預定付款日、行事曆、單一出納清單」要再做一次，且兩套付款入口並存；不建議。

## 5. 通知、站內通知、行事曆、稽核

沿用第 44 班統一規範（`expense_notify.doc_ident`：類型＋單號；主旨寫結果；信內不放金額）：

| 事件 | 收件人 | 信件類型（`mail_types.register`，owner="payroll"） | 主旨範例 |
|---|---|---|---|
| 送審 | 當層簽核人（含代理人） | `payslip_submitted` | 勞報單 PS-… 待審核 |
| 下一層 | 下一層簽核人 | `payslip_next_tier` | 勞報單 PS-… 輪到您審核 |
| 核准 | 送審人（＋出納見第 4 節） | `payslip_approved` | 勞報單 PS-… 已核准 |
| 退回 | 送審人（附原因） | `payslip_returned` | 勞報單 PS-… 已退回 |
| 已付款 | 送審人 | `payslip_paid` | 勞報單 PS-… 已付款 |

- 寄送一律走 `email_notify.send_registered`（字面 key，`test_mail_registry` 守門）；寄信是附帶動作，例外只記 log。
- **站內通知**：`_notify(user, type, ref_id, quote_no, message, link="payslips.html?q=PS-…")`（`link=` 為 `wip/t44-inapp-bell` 97e758a03 的 API；核准類型有去重，鈴鐺全角色可見）。訊息帶單號與結果，**無金額**。
- 行事曆：見第 4 節（預定付款日 `payable_due`）；`expense_payout`「不含勞報單付款」維持。
- 稽核：`payslip.submit／approve／reject／export／paid／planned_pay_date`。匯出稽核的 `_asum` 不含個資。
- 與獎金分潤同樣的坑（需守門）：寄給**送審人**的信，送審人＝簽核人（自核）時不重複寄。

## 6. 派發管理 ↔ 勞報單 雙向連結

### 6.1 現有資料（查證）
- 派發 `contractor_dispatches`（`personnel_json`：快照 `{id,name,amount,note}`，id＝`contractors.id`，`contractors` 也是 `payslips.contractor_id`）。
- 承攬商匯款單 `contractor_payment_vouchers`：`dispatch_id UNIQUE NOT NULL`（**與派發 1:1**），`snapshot_json.personnel[]` 可帶 `payslipNo`（R12，IP-105 `payslip.remit`，`PersonnelLinkIn`／`link_personnel_payslip`，UI 在 `case-management-dispatch.js`）。
- 勞報單 **沒有**派發／匯款單外鍵；只有付款後的 `data_json.paid_via_remit`（匯款單號）。
- ⇒ 現有關聯是 **派發 → 匯款單 → personnel[].payslipNo → 勞報單**，且在**匯款單草稿階段才建立**；勞報單端看不到派發，也沒有「還沒開匯款單」的連結。

### 6.2 建議資料模型
新表 `payslip_dispatch_links`（payroll migration 0004，只加表）：`id, slip_no, dispatch_id, voucher_no('' 可空), note, created_by, created_at`，唯一鍵 `(slip_no, dispatch_id)`。理由：
- **一派發對多勞報單**（多位個人外包、或同一人分期／分次）與**一勞報單對多派發**（合併開單）都能表達；匯款單 `payslipNo` 保留（相容），連結表是**較上游的事實**，匯款單關聯時以連結表驗證（勞報單須已連到該派發，否則警告而非擋，避免卡舊流程）。
- 不放 `payslips.data_json`／`contractor_dispatches` 欄位：跨模組（M04↔M07）以提供者互取，不互讀表（既有慣例：`payslip.remit` 為 IP-105）。

### 6.3 跨模組介面（加法）
- 新提供者 IP-106 `payslip.dispatch_links`（M07 提供）：`links_for_dispatch(conn, dispatch_id)`、`links_for_payslip(conn, slip_no)`、`link(conn, slip_no, dispatch_id, user)`、`unlink(...)`；回傳**只含單號、狀態、受領人姓名、開單日期**；金額欄位 `net` **只有有權者才回**（見 6.5）。
- M04（派發頁）取用，M07 不在 ⇒ 區塊顯示「薪資獎金模組未安裝」（不默默略過，同 IP-14／IP-100 慣例）。

### 6.4 UI 位置
- **派發頁**（`case-management-dispatch.js` 的派發詳情／匯款申請區）：「勞報單」區塊列出連結的勞報單（單號可點 → `payslips.html?q=PS-…`、狀態徽章、受領人），有權者可「新增勞報單」（帶 `contractorId／dispatchId／pre-fill 勞務內容、金額＝personnel 的 amount`）與「關聯既有勞報單」。
- **勞報單頁**（`payslips.html` 右側詳情面板、`payslip-form.html` 表頭）：「來源派發」區（派發單號＋案件，可點 → `case-management.html?q=<案號>`，同現有派發連結慣例）。
- 連結建立時機（Q8）：**建議勞報單建立時可選填來源派發**（因為勞報單常是先開、後才有匯款），派發端也可事後關聯；兩端都走同一個 `link()`。不在匯款單階段才建立。

### 6.5 權限／金額可見 🔴
- 派發頁使用者（工務、承攬管理）**不一定是最高管理者**；勞報單端點全是 superadmin。因此：派發頁只顯示**單號＋狀態＋受領人姓名**；**金額、扣繳、銀行**不在派發頁出現（沿用匯款單 personnel 的 `mask_record`）。點進勞報單時，沒權限的人本來就被擋（403），UI 要把連結做成「無權限則只顯示文字」而不是死連結。
- 連結動作（建立／解除）：需要 `payslip` 模組＋superadmin（同勞報單）；派發端「關聯既有勞報單」按鈕只對有權者出現。Q9 請使用者裁示：派發管理者（非最高管理者）是否可以看到「勞報單已核准／已簽回／已付款」狀態（無金額）。

### 6.6 作廢／退回行為
- 勞報單作廢（`已作廢`）：連結保留但標「已作廢」，且不計入派發端「已開勞報單」合計；匯款單若已關聯該號 ⇒ 沿用現有 `check()` 擋（非已簽回）。
- 勞報單被退回（送審→草稿）：連結不動。
- 派發取消／被退回：不自動作廢勞報單；派發頁對已連結且未付款的勞報單顯示警示「派發已取消，請處理勞報單」（只提示，不連動，避免誤作廢已簽回的法定文件）。
- 解除連結：只允許勞報單尚未付款；已付款（含 `paid_via_remit`）不可解除。

## 7. 待使用者裁示

| # | 問題 | 預設（若不答） |
|---|---|---|
| Q0 | 「匯出要求付款日」請指出是哪個畫面（第 1 節三個候選） | 不改匯出行為，只加守門測試 |
| Q1 🔴 | 財務角色（第 42 班）看不看得到勞報單與其金額？出納動作（付款）改用 `has_finance_access`，還是維持「最高管理者＋勾選 cashier」？ | 與 IP-100 一致用財務角色＋superadmin；金額可見範圍＝可付款的人 |
| Q2 | 誰可以送審？目前建立／匯出都是最高管理者。是否放寬給有 `payslip` 模組的人（簽核仍限最高管理者）？ | 不放寬（送審人＝最高管理者） |
| Q3 | 自核：唯一最高管理者自己送審自己核准，是否允許（沿用獎金分潤規則）？ | 沿用既有規則 |
| Q4 🔴 | 付款是否仍須「已簽回」？ | 是（簽回前出納看得到但不能付） |
| Q5 | 已核准、未匯出時是否可「撤回核准」或作廢？ | 可作廢（需原因，同已匯出作廢）；不開撤回 |
| Q6 | 既有 `草稿` 要不要「祖父條款」免送審？ | 不免；沒設簽核層＝一鍵核准 |
| Q7 🔴 | 勞報單預定付款日要不要進行事曆 `payable_due`（現有裁示是勞報單付款不進行事曆）？ | 不進，直到明確裁示；預定付款日欄位與出納清單照做 |
| Q8 | 派發↔勞報單連結：建立時機（勞報單建立時選填、派發端也可補）？ | 兩端皆可 |
| Q9 🔴 | 派發管理者可否看到勞報單狀態（無金額）？ | 可看單號＋狀態＋受領人，無金額 |
| Q10 | 簽核設定頁是否新增「勞報單簽核流程」獨立一列（不併統一流程）？ | 是 |

## 8. Migration、版本、相容

- **payroll migration 0004**（`modules/payroll/migrations/0004_payslip_approval.py`，登記 `payroll/__init__.py::migrations=[…, (4, _m0004.up)]`）：`ALTER TABLE payslips ADD COLUMN approval_json TEXT NOT NULL DEFAULT ''`、`planned_pay_date TEXT NOT NULL DEFAULT ''`、`approved_at TEXT NOT NULL DEFAULT ''`、`approved_by TEXT NOT NULL DEFAULT ''`（`_col_exists` 冪等）；`CREATE TABLE IF NOT EXISTS payslip_dispatch_links …`＋索引。不自己 commit、不 import 會演進的程式碼（`test_module_migrations` 守門）。核心 `db.py` 不動 ⇒ **不取核心 db 版號**；模組版 CHANGELOG 加 `next` 段（`test_module_changelog_follows_code`）、`version_manifest.json` 一筆（列車取號，不手填）。
- **既有資料零驚喜**：不改任何既有列的 `status`；`草稿` 仍 `草稿`（現在需要送審才能匯出，是使用者要的行為變更，寫進 CHANGELOG 與畫面提示）；`已匯出／已簽回／已付款／已作廢` 照舊（含舊 PDF 封存、`export_log`）。`approval_json=''` 的舊列視為「無簽核紀錄」（顯示「舊單（未經簽核）」，不補假紀錄）。
- **向下相容／回滾**：新程式只加欄位／表，回舊程式碼不讀它們。⚠ **回滾缺口**：舊碼不認得 `待審核／已核准`，`_LOCKED_STATUSES` 不含它們 ⇒ 舊碼下這兩種狀態可被編輯／刪除；且舊 `record_export` 對 `已核准` 保持不變（不會變已匯出）。緩解：回滾 SOP 加一句「先處理 待審核／已核准 的勞報單」；或第一階段先只上 DB／唯讀、第二階段才開送審。**需列車／回滾守門決定**（Q11：接受此缺口？）。
- 模組不在：M07 不在 ⇒ 沒有提供者，M05／M04 照 INTEGRATION-POINTS 明講退化（不默默略過）。

## 9. 測試與 e2e 清單

單元（`modules/payroll/tests/`）：
1. 狀態機表：每個合法／非法轉換（草稿→待審核、待審核→已核准／回草稿、已核准→已匯出；其餘 409）。
2. 匯出：`草稿／待審核` ⇒ 409；`已核准` 成功；**不帶任何日期**也成功；PDF 文字層不含「付款日／匯款日期」（`test_payslip_export_needs_no_payment_date`＋突變：加回付款日檢查要紅）。
3. 簽核：有層／無層（送審即核准）／多層順序／同層全簽／代理人／自核／非最高管理者進鏈 ⇒ 400／退回必填原因／退回回草稿保留歷史／簽核中編輯⇒重簽。
4. 權限：非 superadmin 全 403；簽核人以外簽核 403；金額欄位只給有權者。
5. 通知：5 種信的主旨結果字、無 `NT$`、自核不重寄、無收件人只記 log、站內通知帶 `link` 與去重；**真走 API 核准後斷言信件列**（第 44 班請購單教訓：不能只測 notify 單元）。
6. 出納提供者（IP-100 `payroll_payslip`）：列出條件、`blocker` 待簽回、`mark_paid` 擋未簽回、委派同一實作（突變：另寫一份會紅）、傳票單號驗證、`paid_via_remit` 列停用付款、F2 欄位不外洩（含身分證／銀行帳號）、M07 不在時的反向控制（真刪套件）。
7. 預定付款日：欄位、PATCH 權限、（Q7 若同意）行事曆 upsert／移動／刪除、事件不含金額。
8. migration 0004：冪等、舊列不變、可回退（舊碼讀新 DB）；`test_module_migrations`、`test_module_changelog_follows_code`、`test_mail_registry`、`test_approval_doc_type_registry`、route 表黃金檔（`route_table_golden.json` 新增 3＋出納檔案端點）、L1 interface snapshot。
9. 派發連結：連結表 CRUD、一對多／多對一、唯一鍵、解除限制、作廢標示、M07 不在退化、金額不外洩給非最高管理者、匯款單 `payslipNo` 相容。

e2e（Playwright，**一律驗按鈕**）：
1. 勞報單頁：新增草稿→「送審」按鈕可見／匯出鈕在草稿不可用→送審→簽核人簽核→匯出（不出現付款日欄）→上傳簽回檔→出納頁看到→填付款日＋傳票號→已付款；列表徽章與歷史對。
2. 退回流程：退回原因顯示、回草稿可改、重送。
3. 出納頁：核准後即出現、未簽回付款鈕停用、簽回後亮；預定付款日編輯。
4. 派發頁↔勞報單頁互點（有權／無權兩種身分）、無金額洩漏；`pages_without_case_module`、`dark_mode`／`unread_marks` 這類既有 e2e 回歸（新增 UI 區塊）。
5. 站內通知鈴鐺：送審／核准／退回各出現一列、點擊開對的單據。

影響面套件（建包前）：`payroll/tests`、`arap/tests/test_cashier_*`、`case/tests/test_*_payable*`、`subcontract/tests/test_*contractor_voucher*／*remit*`、`tests/platform`（守門全套）、`tests/test_notify_*`、相關 e2e（payslips、cashier、approval-queue、dispatch）。

## 10. 衝突與相依

- 與 `wip/t44-inapp-bell`（`link=`、去重）：依賴其 API；第 44 班落地後 rebase。
- 與第 45 班「預定付款日」（承攬商匯款／材料申請匯款）：同一個 `plannedPayDate` 欄名／出納 PATCH 慣例，勞報單比照，避免三套寫法。
- 與 `case_extra_expenses.py`／`payment-request.html`：本設計不碰。
- 與 `cashier.py`／`cashier.js`：本設計會改（新增提供者的欄位呈現、`blocker`）；與 `wip/t44-attach-views`（出納附件預覽）同檔 ⇒ 排在其合併之後、rebase 重跑。
