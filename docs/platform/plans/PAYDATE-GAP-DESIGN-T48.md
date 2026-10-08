# 預定付款日缺口（承攬商匯款／叫料匯款）：剩餘範圍設計稿（第 48 班候選；**設計稿，無程式，待確認才實作**）

> 作者：node-ab｜2026-10-08｜基底：`origin/platform` 570c54fa1（第 46 班已上線）｜分支 `wip/t48-paydate-design`
> 來源：待辦「預定付款日缺口：承攬商匯款／材料申請匯款無預定日、舊清單頁無輸入欄、無 e2e、無站內通知」（`START-HERE` 第 45 班範圍、記憶 backlog）。
> 本稿先**盤點現況**（這四項在第 45／46 班之後還剩什麼），再提出剩餘範圍。標記：[讀碼]＝讀過程式；[推論]＝未驗證；[待確認]＝要你或使用者回答。

## 0. 一頁結論

1. 這四項的**大半已在 platform 上**：兩個來源的資料欄（subcontract 0006、case 0008）、出納端改期端點與輸入欄（承攬商匯款佇列、待付款清單）、叫料匯款申請的「預定付款日（選填）」輸入與列表顯示、申請人被通知（`_notify_applicant_planned`）。逾期提醒＋行事曆＋財務站內通知在 **`wip/t45-paydate-l1`（第 47 班 L1）**，尚未進 platform。
2. **剩下的真缺口很小且集中在前端與測試**，且**不需要 migration、不動權限**：
   - **G1** 承攬商匯款「建立」畫面（`case-management-dispatch.js` 的 `confirmCreateContractorVoucher`／`case-management.html` 約 4451 行）**沒有預定付款日輸入**——API 早就接受 `planned_pay_date`（`contractor_vouchers.py:100,382`），但畫面只送 `payable_date`（合約應付款日，不同概念）。申請人現在只能等出納事後補。[讀碼]
   - **G2** 承攬商匯款**清單／卡片**不顯示預定付款日（叫料匯款列表有 `mo-pay-planned-*`；承攬商沒有對應）。[讀碼，grep 無 planned]
   - **G3** e2e 缺：只有 `test_e2e_planned_pay_mine_t45`（請款「我的申請」）。**沒有**：叫料建立帶日期、承攬商建立帶日期、出納兩個佇列改期、提醒信／站內通知。[讀碼]
   - **G4** 站內通知：L1 落地後「逾期／將到／當天」財務站內通知就有了（`payable_due_core` 的 `INAPP_PREFIX` guard）；要補的只有**驗證與 e2e**，以及（若使用者要）**申請人**在「核准後仍沒預定日」時的提醒——[待確認]。
3. **建議順序**：先等第 47 班 L1（`payable_due_core`）上線，再做 G1＋G2（小、純前端＋1 個欄位顯示）、G3 補 e2e、G4 只做驗證。全部屬 L2 模組＋前端，不碰 L1。

## 1. 現況盤點（本稿的依據）

| 項 | 承攬商匯款（M04） | 叫料匯款（M01） | 位置 |
|---|---|---|---|
| 資料欄 | ✅ `contractor_payment_vouchers.planned_pay_date`（0006） | ✅ `case_material_payments.planned_pay_date`（0008） | `modules/*/migrations` |
| 建立時帶入（API） | ✅ `ContractorVoucherIn.planned_pay_date`，`normalize_date` 驗格式 | ✅ `material_payment._planned(body)` | `contractor_vouchers.py:100,382`、`material_payment.py:263` |
| 建立時帶入（**畫面**） | ❌ 只有 `payable_date` | ✅ `case-management.html` 約 2535「預定付款日（選填）」 | **G1** |
| 草稿期修改 | ❌ 沒有 PUT（只有發票、送審…） | ✅ `update_payment` 沒帶欄位 ⇒ 保留原值 | `material_payment.py:336` |
| 清單顯示 | ❌ **G2** | ✅ `mo-pay-planned-*` | |
| 出納端改期 | ✅ `PATCH /api/cashier/payable-queue/{no}/planned-pay-date`＋`cashier.html` 約 366 的輸入 | ✅ `PATCH …/pending-payables/case_material/{id}/planned-pay-date` | `arap/api/cashier.py` |
| 改期通知申請人 | ✅ `_notify_applicant_planned`（站內，不含金額） | ✅ 同 | `cashier.py` |
| 逾期／將到／當天提醒、行事曆、財務站內通知 | ⏳ `wip/t45-paydate-l1`：`subcontract/payable_due.py` | ⏳ `case/material_payable_event.py` | 第 47 班 |
| e2e | ❌ | ❌（只有一般叫料 e2e） | **G3** |

[待確認 C1] 「舊清單頁」指哪幾頁？我找到的候選是承攬商匯款卡片（G2）與 `cashier.html` 的舊頁籤（勞報單舊頁籤已隱藏一班）。若還有別的（例如會計的匯款清單頁），請指名，我再補盤點。

## 2. 範圍（若確認）

### 2.1 做
- **G1**：承攬商匯款建立視窗加「預定付款日（選填）」`<input type="date">`，送 `planned_pay_date`；與「合約應付款日」並列、標籤與 hint 寫清楚兩者不同、**不互相預填**（後端已有此註解）。
- **G2**：承攬商匯款卡片顯示「預定付款日 …」（有才顯示；已匯款顯示為歷史），資料來自既有 `plannedPayDate`（`_voucher_public` 已回，`contractor_vouchers.py:209`）。
- **G3**：e2e（`-m e2e`）：①叫料匯款建立帶日期 → 出納清單看到同一日期；②承攬商匯款建立帶日期 → 核准 → 出納佇列看到並改期 → 資料庫落地；③出納清除日期；④（L1 之後）逾期提醒：以假日期呼叫 `run_reminders(today=…)`，斷言站內通知落地且**內容不含金額／受款人／廠商名**。
- **G4**：L1 上線後驗證（不新增程式）：guard 冪等、尊重 `notification_muted`、M01 不在時 fail-closed。

### 2.2 不做
- 不新增表、不跑 migration（欄位都在）。
- 不改任何權限：誰能建立（現有權限）、誰能改期（財務角色＋超管，`_can_pay`）、誰能看（既有清單權限）一律不變。
- 不改 L1（`payable_due_core` 歸第 47 班）；本稿只在 L2＋前端接線。
- 不做「承攬商匯款草稿期修改預定日」的新端點——現行匯款沒有 PUT，申請人要改只能退回重開或請出納改期（符合現行「出納維護預定日」的裁示）。[待確認 C2：是否要補一個申請人在草稿／待審期可改的 PATCH？建議否]

## 3. 資料模型與遷移
無變更。檢查項：`planned_pay_date` 欄在兩張表都是 `TEXT NOT NULL DEFAULT ''`（0006／0008 冪等 add-only）[讀碼 migration 檔名；欄位型別 [推論]，實作前核對]。

## 4. 與 `payable_due_core` 的銜接
- G1／G2 **不依賴** L1（欄位與 API 現成）；可先於 L1 做，但 e2e 的提醒那一項（G3-④）依賴 L1。
- L1 落地後 `subcontract/payable_due.fire(voucher_no)`（commit 之後呼叫）已接在**作廢、最後一層核准、退回、撤銷核准、標記／取消已匯款**等路徑 [讀 `wip/t45-paydate-l1` 的 `contractor_vouchers.py` diff]；行事曆事件只對「已核准、未匯款」的單存在，
  所以 **G1 讓草稿建立時就帶日期不需要另外接 `fire`**——日期隨單走，核准那一刻 `fire` 才建事件。出納改期後事件由出納端點的 `planned_changed`／`fire` 對齊（L1 已接）。
- 排程：`daily.check` 由 `run_daily_checks` 呼叫（L1 已接）；本稿不新增排程。

## 5. 權限與隱私
- 建立：沿用 `POST /api/contractor-vouchers` 的現有守門（不變）。
- 顯示：預定付款日不是敏感個資；卡片本來就顯示金額給有權限者；**通知與行事曆文字不得含金額／受款人／廠商名**（Q4 裁示，L1 已保證，e2e 加斷言）。
- 出納改期權限不變（財務角色＋超管）；不放寬任何人。

## 6. 測試與守門
- 後端：既有 `test_voucher_planned_pay_date_t45.py`、`test_material_payment_planned_t45.py` 已涵蓋 API；新增「建立帶日期落地」「卡片 payload 含 `plannedPayDate`」各 1 題（已部分涵蓋，實作時先查重）。
- 前端：e2e 4 題（§2.1 G3）；觀測點打資料庫與元件狀態，不打頁面文字。
- 突變：拿掉 `confirmCreateContractorVoucher` 送 `planned_pay_date` 那行 ⇒ e2e ② 轉紅。

## 7. 回滾
純前端＋顯示：程式回退即還原；無資料動作。既有已填的日期保留不動。

## 8. 風險
- **低**：欄位與 API 現成。唯一語意風險是申請人把「合約應付款日」與「預定付款日」填混——畫面標籤與 hint 要明確，且不互相預填。
- 與第 47 班 L1 的**時序**：若 L1 還沒進 platform 就先做 G1，建立後不會有行事曆事件（因為 `fire` 還沒接）；不會出錯，只是提醒晚到。

## 9. 需要你確認才實作
1. **C1** 「舊清單頁」的範圍（§1 末）。
2. **C2** 是否補「申請人草稿期可改預定日」（建議不補）。
3. **C3** G4 是否要「核准後仍沒預定日」的申請人提醒（建議不做：出納會在清單上看到空白日期；多一封信要登記信件類型與矩陣）。
4. 實作時機：等第 47 班 L1 進 platform 之後開工（建議），分支 `wip/t48-paydate-gap`。
