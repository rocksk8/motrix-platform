# 預定付款日缺口補齊（第 45 班設計）

> 狀態：**設計／分析，無程式碼**。作者 hichan-ec [c11912]，2026-10-07；分支 `wip/t45-paydate-design`（自 origin/platform 036565879，prod 基準 89206122）。
> 使用者已裁示全部待決題（第 9 節）；可進入實作排班。
> 讀的碼：`case/payables.py`、`payable_calendar.py`、`payable_reminders.py`、`migrations/0007`、`api/case_extra_expenses.py`（`/dates`）、`material_payment_cashier.py`、`api/material_payments.py`、`subcontract/api/contractor_vouchers.py`、`arap/api/cashier.py`、`frontend/js/cashier.js`、`pages/cashier.html`、`payment-request.html`、`helpers/case_access.py`、`origin/wip/t44-inapp-bell`（`audit._notify`）、c0 的 `PAYSLIP-APPROVAL-T45.md`。

## 0. 摘要

| # | 結論 |
|---|---|
| 1 | 第 42 班只做了**案件額外支出**一條線（欄位、提醒信、行事曆、出納編輯）。承攬商匯款（IP-14）、叫料匯款（`case_material_payments`）、勞報單（c0 設計）三條線**沒有任何預定付款日**。 |
| 2 | 承攬商現有的 `payableDate`＝派發上的「應付款日期」，建立匯款單時**凍結進 `snapshot_json`**，之後出納改不了；它也只拿來排序／標逾期，不發信、不進行事曆。**不能直接當預定付款日**（語意是合約應付日，且凍結）⇒ 建議新增可編輯欄位 `planned_pay_date`。 |
| 3 | 出納改預定日現在只認案件額外支出：`savePlannedPayDate` 直接打 `PATCH /api/quotations/{no}/extra-expenses/{id}/dates`（程式註解寫明「來源目前只有案件額外支出」）。其他來源要先有**不經案件守門的出納端點**。 |
| 4 | CM14b 的實況：第 42 班起 `case_owner_readable` 對財務角色放行，所以**額外支出 `/dates` 財務角色其實打得通**；真正的缺口是**案件頁對非成員財務是唯讀（只能改收款）**、以及承攬商／叫料沒有對應端點。解法：預定日一律走出納端點（經提供者），不碰案件頁權限，**不需要放寬 CM14b**。 |
| 5 | 舊清單頁＝`payment-request.html`「我的申請」：**沒有預定付款日欄**（新增表單有，建立後就看不到、改不了）。 |
| 6 | 提醒信（前 3 天＋當天）目前寫死只掃 `case_extra_expenses`。建議**提醒與行事曆改成來源無關**：掃 IP-100 `pending()`（已含 `plannedPayDate`）＋ IP-14，不再各模組各寫一套。 |
| 7 | 站內通知：目前零。44 班鈴鐺（`wip/t44-inapp-bell`，`_notify(..., link)`）合回後可直接用；建議提醒信同步寫財務站內通知、請款人收到「財務排定付款日」通知。 |
| 8 | e2e：預定付款日**沒有任何瀏覽器端對端**（只有單元／API 守門 `test_payable_planned_pay_date_2026_10_05.py`）；第 8 節列補件。 |
| 9 | 與 c0（勞報單）共用同一模型：同欄名 `planned_pay_date`、同鍵 `<來源>:<key>`、同出納端點。勞報單**不進行事曆**（使用者已裁示）；本文 Q3 只問承攬商、叫料。 |

## 1. 現況覆蓋矩陣（✅ 有 ／ ❌ 沒有 ／ ➖ 不適用）

| 能力 | 案件額外支出（M01） | 承攬商匯款（M04 IP-14） | 叫料匯款（M01 `case_material_payments`） | 勞報單（payroll，c0 設計） |
|---|---|---|---|---|
| 欄位 `planned_pay_date` | ✅ case v7 | ❌（只有凍結的 `payableDate` 快照） | ❌ | 設計中（payroll 0004） |
| 申請人填 | ✅ 新增表單；❌ 建立後（我的申請無欄位） | ❌ | ❌ | 設計中（送審時填） |
| 出納填／改 | ✅ `cashier.js::savePlannedPayDate`（走案件 `/dates`） | ❌（只能看 `payableDate`，逾期標紅） | ❌ | 設計中 |
| 出納頁顯示 | ✅ 預定日欄、「已逾預定日」「3 天內到期」 | ◐ 顯示 `payableDate`（`isOverdue/isDueSoon`），無編輯 | ❌ 欄位不在 `pending()` 項目 | 設計中 |
| 提醒信（−3 天＋當天，工作日順延） | ✅ `payable_reminders.run` | ❌ | ❌ | 設計中 |
| 行事曆 `payable_due` | ✅ upsert／改日期／清除／付款／作廢 | ❌（只有付款後的 `contractor_payout`） | ❌ | 設計中（Q7） |
| 站內通知 | ❌ | ❌ | ❌ | ❌ |
| 逾期後續提醒 | ❌（過了就不再提醒，guard 只含 soon／today） | ❌ | ❌ | ❌ |
| 單元／API 守門 | ✅ 約 30 題 | ❌ | ❌ | ➖ |
| e2e | ❌ | ❌ | ❌ | ➖ |

出納端共通點：IP-100 `pending()` 的項目形狀已有 `plannedPayDate`（case 提供者填；叫料提供者 `material_payment_cashier.pending()` 沒填，前端顯示成「—」）。

## 2. 共用模型（與 c0 對齊）

**一個概念、四張表各一欄**：
- 欄位：`planned_pay_date TEXT NOT NULL DEFAULT ''`（`YYYY-MM-DD`；`''`＝沒填）。語意與 case v7 相同：**不是**實際付款日；付款後保留當歷史、不再改。
- 對外鍵：`<來源>:<key>`＝IP-100 既有慣例（`case:123`、`case_material:45`、`payroll_payslip:PS-…`、`subcontract_voucher:CV-…`），**行事曆 `payable_due`、guard key、出納端點全用同一組**。
- 項目形狀：`plannedPayDate`（IP-100 `pending()` 與 IP-14 `_voucher_public` 都帶；加欄位、契約版本不變）。
- 合格判準（`eligible`）：已核准、未付款（叫料＝剩餘應付 > 0）、未作廢、可由出納付款、日期合法。與 `payable_calendar.eligible` 同義；各來源各自實作一個 `planned_eligible(row)`。
- 編輯權限：**出納端點 ＝ 財務角色／superadmin**（`has_cashier_access`，與 `/dates` 現行相同）；申請人本人在**自己的申請**（付款前）可改。

**出納端點（新，來源無關）**
`PATCH /api/cashier/pending-payables/{source}/{key}/planned-pay-date` body `{plannedPayDate}`（`''`＝清除）。
- IP-100 提供者加**可選方法** `set_planned_pay_date(conn, key, value, user) -> {plannedPayDate}`（不 commit；查無 ⇒ `LookupError` 404；已付款／非待付 ⇒ `ValueError` 409）。沒有該方法的提供者 ⇒ 501 風格 409「此來源不支援預定付款日」。
- 承攬商（IP-14，非 IP-100）：`PATCH /api/cashier/payable-queue/{voucher_no}/planned-pay-date`，由 M04 提供 `contractor_voucher.set_planned`（單一提供者，缺席時 404＋`CONTRACTOR_MISSING`，同現行做法）。
- 端點內：驗權限 → 呼叫提供者 → commit → **commit 之後**同步行事曆（`spawn_bg_thread`；寫鎖內不呼叫，`write_txn_scan` 會擋）→ 稽核 `cashier.planned_pay_date`（來源、key、舊→新；不含金額、不含個資）。
- 好處：不經案件守門 ⇒ 不受 CM14b 影響；`savePlannedPayDate` 改打這一支後 `source='case'` 行為不變（內部仍由 case 提供者寫同一欄並呼叫既有 `PC.fire`）。

## 3. 缺口逐項設計

### G1 承攬商匯款：新增預定付款日（含出納編輯）
- **資料**：`contractor_payment_vouchers.planned_pay_date`（subcontract migration 0006）。`_voucher_public` 多回 `plannedPayDate`（加法）。
- **為何不用 `payableDate`**：① 它存在 `snapshot_json`（建立當下凍結，無更新路徑）；② 語意是合約「應付款日期」，出納實際排程可能不同；③ 兩者並存才有「應付日 vs 預定日」落差可看。出納頁兩欄並列：「應付款日（合約）」「預定付款日（可改）」。
- **預填**：建立匯款單時若未帶預定日 ⇒ 空白（**不自動複製** `payableDate`，避免把合約日誤當承諾；Q1 可改為預填）。
- **誰填**：出納（端點如第 2 節）；匯款單建立／送審時的表單可選填（`ContractorVoucherIn` 加 `planned_pay_date`，與 `payable_date` 同一驗證）。
- **合格判準**：`status='已核准' AND is_paid=0 AND voided_at=''`（見 `_payable_queue`）。分期申請（`kind` 非空）同。
- **行事曆**：`payable_due`、key `subcontract_voucher:<voucher_no>`；觸發點＝建立／核准／退回核准／作廢／`paid-toggle`／預定日異動，皆 commit 後。事件**不含金額、不含承攬商人員姓名**（Q4 裁示：只放單號＋名目＋關聯案件，不放廠商名）。付款後的 `contractor_payout`（以匯款日）事件不動，兩者不同種類、不同 key。
- **提醒信**：納入第 4 節的通用掃描。
- **不做**：不改 IP-14 的排序規則（`payableDate` 空值排最後）；預定日只**加**欄，不影響既有排序（Q5：是否改依預定日排序）。

### G2 叫料匯款：新增預定付款日
- **資料**：`case_material_payments.planned_pay_date`（case migration 0008）。範圍＝**每張匯款申請一個日期**（一張申請可分次付款；日期代表「下一次付款預定日」）。
- **提供者**：`material_payment_cashier.pending()` 項目加 `plannedPayDate`；新增 `set_planned_pay_date`。合格判準＝`status='已核准' AND remaining>0`（`MP.remaining_of`）。部分付款後日期保留；若日期已過仍有餘額 ⇒ 出納頁標「已逾預定日」，**不再發信**（同額外支出的「過期不補」；逾期後續提醒見 G6）。
- **申請人**：叫料匯款申請的建立／送審表單（`material_payments.py::create_payment／update_payment`）加選填 `plannedPayDate`（草稿期可改；核准後只有出納／財務可改）。
- **行事曆**：key `case_material:<payment id>`；內容不含金額、不含供應商帳戶（銀行資料屬個資 F2，本來就不外露）。
- **注意**：叫料匯款走分層簽核，出納頁顯示在核准後；日期在簽核中填了就在核准後才生效（沒到 eligible 前不發信、不建事件）。

### G3 舊清單頁（`payment-request.html`「我的申請」）補輸入欄
- 欄位：在表頭「付款日」前加「預定付款日」；`e.plannedPayDate` 已由 `GET /api/extra-expenses/mine` 回傳（`case_extra_expenses.py` L178），**後端不用改**。
- 行為：狀態非「已作廢」且 `paidDate` 空 ⇒ 顯示 `<input type=date>`＋儲存（打現有 `PATCH …/extra-expenses/{id}/dates {plannedPayDate}`；本人／admin／財務可，`_can_modify` 現有判斷）；已付款 ⇒ 唯讀顯示（歷史）。錯誤訊息直接顯示後端 `detail`（含「已登錄付款，預定日保留為歷史」的 409）。
- 順手：`mine` 的承攬商／叫料不在此頁，不處理。
- testid：`pr-mine-planned-<id>`、`pr-mine-planned-save-<id>`。

### G4 通知（站內＋寄信對象）
- **前提**：44 班鈴鐺（`wip/t44-inapp-bell`）已合回後才寫；未合回前只做信（現況）。
- 站內通知（`_notify(username, type, ref_id, label, message, link)`；link＝`cashier.html?tab=payreq`，通過 `_LINK_RE`）：
  1. 提醒觸發時（−3 天／當天）對**財務收件人**各寫一則（收件人解析＝信件同一支 `finance_recipient_emails` 之使用者清單；尊重該類型退訂；`ref_id=<來源>:<key>:<soon|today>:<預定日>` 去重）。
  2. 財務／出納**設定或改預定日** ⇒ 通知**申請人**：「您的請款 <單號> 預定 YYYY-MM-DD 付款」（不含金額）。清除亦通知。申請人＝本人改的不通知自己。
  3. 付款完成 ⇒ 既有 `expense_notify.fire("paid")` 不動；其他來源比照（叫料、承攬商各自既有通知先查再接，不重複）。
- **出納頁本身**：頁籤標題加紅點／計數「已逾預定日 N／3 天內 M」（前端用既有 `plannedState`，純前端，不新增 API）。
- **不放金額**：站內通知文字不含金額（同信件裁示；鈴鐺另有 `_mask_money`）。

### G5 財務角色對他人案件畫面唯讀（CM14b）
- 現況（已實證）：`case_owner_readable` 對 `has_finance_access` 放行（42 班）⇒ 財務可打 `/dates`；案件頁（`quotation-form`）對非成員財務為 `cashierReadOnly`（只能改收款），額外支出／叫料／匯款單的編輯不在案件頁給財務。
- **設計：不放寬 CM14b。** 預定日編輯入口只放在 ① 出納待付款頁（第 2 節端點）② 申請人自己的「我的申請」。案件頁維持唯讀，但**顯示**預定日（若該頁有額外支出清單；目前案件頁只載入合計，**無清單 ⇒ 不用改**）。
- 權限矩陣（預定日）：

| 角色 | 讀 | 改（付款前） |
|---|---|---|
| 申請人本人 | ✅ 自己的 | ✅ 自己的（`/dates`；叫料草稿期） |
| 財務角色／superadmin | ✅ 全部（出納頁） | ✅ 出納端點（任何來源） |
| 案件業務／協作者（非申請人） | ✅（案件頁若有） | ❌ |
| admin（非財務） | 依既有 | ❌（42 班已拿掉 admin 直通） |
| 僅持 `cashier` 模組、非財務角色 | 依 `has_cashier_access` 現行 | 依現行（Q6 確認不改） |

### G6 逾期提醒（Q2 已裁示：納入）
現況：預定日過了未付款 ⇒ 沒有任何提醒（`due_kind` 只有 soon／today）。加第三封 `payable_overdue`：預定日後**第 1 個工作日**寄 1 封，每筆最多 1 封、不週提（Q2）。同樣走工作日、guard、財務群組、不放金額；涵蓋四來源（含勞報單）。

## 4. 通用提醒／行事曆（來源無關）

**問題**：`payable_reminders.run` 與 `payable_calendar.sync` 直接 SELECT `case_extra_expenses`，其他來源要複製一整套（guard、工作日、收件人、逾時上限）才行 ⇒ 三份各自演進。

**設計（建議）**：
1. 提醒掃描搬到 M05（`modules/arap/payable_due_reminders.py`，`daily.check` 登記），資料來源＝`registry.providers("payables.pending")` 的 `pending(conn)` ＋ IP-14 `_payable_queue`，依 `plannedPayDate` 篩候選日（沿用 `_candidate_planned_dates`、`due_kind`、`effective_send_day`、guard、45 秒／120 秒上限，**純函式原封搬**）。
2. guard key：`payable_due_notif.<來源>.<key>.<kind>.<預定日>.<寄信日>`；**case 來源沿用舊 key 格式 `payable_due_notif.<id>.…`**（相容，避免切換當天雙寄；舊 case 掃描在切換版本同步移除）。
3. **每來源行事曆開關**：通用層以來源表 `CALENDAR_SOURCES`（`case`、`subcontract_voucher`、`case_material`）決定哪些來源建 `payable_due` 事件；`payroll_payslip` **不在表內**（使用者裁示不進行事曆），提醒信／站內通知仍照常涵蓋勞報單。守門：勞報單設預定日／核准／付款後，`push_event_*` 一律零呼叫。
3'. 行事曆：L1 薄 helper `helpers/payable_event.py::sync(source, key, item_or_None)`（只包 `push_event_upsert_for_module`／`push_event_delete_for_module`，不查任何 L2 表）；各模組在自己的寫入點 commit 後呼叫（case 現有 `PC.fire` 內部改呼叫它，行為不變）。
4. 信件：沿用 `payable_due_soon`／`payable_due_today`（財務群組、`to_group=True`）；`mail_types.owner` 由 `case` 改 `arap`（`owner` 欄只影響模組卸載時的信件類型清理；改動要連同 `test_mail_types_registered_with_owner_case` 一起改）。
5. **缺席行為**：M05 不在 ⇒ 沒有提醒（原本 M01 自帶）。為免「卸載出納就失去 case 提醒」的回退，**替代方案 B**：保留 case 掃描不動，另在 M04、case_material 各加一支極薄掃描呼叫同一支 L1 純函式庫 `helpers/payable_due_core.py`（工作日／`due_kind`／guard／寄送迴圈放 L1，三個模組各傳 SQL 結果進去）。**建議採 B**（模組可獨立販售，不新增 L2→L2 依賴；memory：模組可拆分串聯）。成本：多一個 L1 檔、三處薄接線。

## 5. 資料與 migration

| 項 | 內容 |
|---|---|
| case 0008 | `case_material_payments ADD COLUMN planned_pay_date TEXT NOT NULL DEFAULT ''`（`PRAGMA table_info` 冪等；表不在 ⇒ 回原因字串、不 commit、不 import 演進中程式；同 0007 寫法） |
| subcontract 0006 | `contractor_payment_vouchers ADD COLUMN planned_pay_date TEXT NOT NULL DEFAULT ''`。⚠ 0005 曾做過**整表重建**（`remit_kinds_voucher_rebuild`，用暫時表）：新欄加在 0006（0005 之後）即可；**之後任何重建都必須帶這一欄**——在 0006 的 docstring 與 `test_module_migrations.py` 加欄位存在斷言 |
| payroll 0004 | c0 設計（`payslips.planned_pay_date`），欄名一致 |
| 回填 | **不回填**（沿用 case v7：舊列全 `''`）。承攬商舊匯款單的 `payableDate` 不複製（Q1） |
| 回退 | 只進不退；舊程式不認得欄位、`SELECT *` 照常、INSERT 不帶有預設值 ⇒ 回滾程式碼不需動資料 |
| 凍結基準 | `tests/_prod_baseline.py`、`tests/platform/test_module_migrations.py`、`l1_interface_snapshot.json`（若新增 L1 helper）要同步；migration 與版號由列車定號，不在分支內自行搶號 |
| 契約 | IP-100：加可選方法 `set_planned_pay_date`＋叫料提供者回 `plannedPayDate`（加法）；IP-14：公開形狀加 `plannedPayDate`、新提供者 `contractor_voucher.set_planned`（加法，契約版本不變）。`INTEGRATION-POINTS.md` 的「預定付款日追加」段改寫成四來源 |

## 6. 實作切片（建議順序，每片可獨立驗證）

1. **S1** 出納端點＋IP-100 可選方法＋`savePlannedPayDate` 改打新端點（case 來源行為不變；回歸＝既有 `test_payable_planned_pay_date_2026_10_05.py` 全綠）。
2. **S2** G3「我的申請」欄位（純前端＋e2e）。
3. **S3** G2 叫料（migration 0008、提供者、申請表單、出納頁顯示）。
4. **S4** G1 承攬商（migration 0006、`_voucher_public`、出納端點、出納頁欄位）。
5. **S5** 通用提醒／行事曆（第 4 節，建議方案 B）。
6. **S6** 站內通知（等 44 班鈴鐺合回）＋出納頁逾期計數。
7. **S7** G6 逾期提醒（Q2 已裁示）。
S1 先於其餘；S3／S4 互不相依，可平行（不同模組、不同 migration 檔）。勞報單（c0）接 S1 之後。

## 7. 測試計畫（合回後才跑；現在測試鎖被 44 班占用，本文只列題目）

**單元／API（每片各一檔，沿用 `_hdr/make_user` 夾具）**
- migration 冪等、表缺席回原因、已登記進 `ModuleSpec`（照 `test_migration_adds_column_idempotently…`）。
- 出納端點：財務可改、非財務 403、案件非成員財務可改（**CM14b 正對照**）、已付款 409、日期格式錯 400、未知來源 404、提供者無方法 409、清除 `''`、稽核有寫且不含金額。
- 各來源 `pending()`／`_voucher_public` 帶 `plannedPayDate`；`eligible`（未核准／已付／作廢／叫料餘額 0 ⇒ 否）。
- 行事曆：開關預設關（零流量）、改日期＝移動同一筆、清除／付款／作廢／退回核准收斂（照 case 現有題目逐一複製到 M04、叫料）；**事件文字無金額**（斷言內文沒有任何數字金額）。
- 提醒：L1 純函式（`due_kind`、`effective_send_day`、假日接縫）已有題目，搬 L1 後**同檔沿用**；新增「來源 A 的 guard 不擋來源 B 同 key」「case 舊 key 相容、切換不雙寄」。
- 通知：寫給財務收件人（退訂者不寫）、申請人收到改日期通知、本人改不通知自己、去重、link 合法、文字無金額。
- **突變**（各 1 條）：端點不驗權限 ⇒ 紅；`pending()` 漏 `plannedPayDate` ⇒ 紅；付款後沒收回事件 ⇒ 紅；寄信前先寫 guard ⇒ 紅。

**e2e（補現有零 e2e；每條斷言**實際可見文字／值**，避免假綠燈：memory「e2e 假綠燈三種寫法」）**
1. `payment-request.html` 我的申請：核准後填預定日 → 重新載入仍在；付款後欄位唯讀。
2. 出納頁：改預定日（案件額外支出、叫料、承攬商各一）→ 標籤「3 天內到期」「已逾預定日」切換正確；財務為**案件非成員**（CM14b 正對照）。
3. 出納頁登錄付款後該列消失、行事曆刪除呼叫被記錄（以 `monkeypatch` 記錄 `push_event_*`，不連 Google）。
4. 鈴鐺：提醒觸發後財務看到通知、點擊開出納頁（等 44 班合回）。
測試預算：每片只跑**自己的檔＋影響面小套件**；共用層（L1 helper）改動才觸發較大套件（memory：模組化為快速驗證；建包測試預算 ≤ 30 分）。

## 8. 風險

| 風險 | 說明／緩解 |
|---|---|
| 切換提醒掃描時雙寄 | case 沿用舊 guard key 格式；切換當版同時移除舊掃描；有「相容」測試 |
| 日期語意混淆（承攬商兩個日期） | 欄名與出納頁標題明寫「應付款日（合約）」vs「預定付款日」；不自動複製（Q1） |
| 叫料分次付款後日期過期無人提醒 | 出納頁標逾期；G6 可選逾期提醒 |
| subcontract 之後再重建 voucher 表漏欄 | 0006 docstring＋遷移測試斷言欄位存在 |
| 通知洗版 | 去重 key、每筆每種類型一則；財務群組退訂尊重 |
| 個資外露 | 事件／通知／信都不含金額、帳戶、人員姓名（承攬商人員、勞報單受領人）；廠商名也不放（Q4） |
| 44 班鈴鐺未合回前依賴它 | S6 擺最後；之前只做信與頁面標示 |
| 共用檔衝突 | `cashier.js`／`cashier.html`／`INTEGRATION-POINTS.md`／`payables.py` 多條線都會動 ⇒ 實作用自己的 worktree、逐 hunk 解衝突（memory：共用 git index／衝突解法） |

## 9. 使用者裁示（2026-10-07，經 hichan-1e 表單；**全部已決**）

| # | 裁示 | 對設計的影響 |
|---|---|---|
| Q1 | 承攬商兩欄分開；新單不預填、舊單不回填 | 照 G1／第 5 節 |
| Q2 | 逾期提醒：預定日後**第 1 個工作日 1 封**，不週提 | G6 納入實作（S7 不再可選）；信件類型 `payable_overdue`（財務群組）；guard 含 overdue 一把；預定日改期 ⇒ key 變、重新計算 |
| Q3 | 承攬商、叫料進行事曆「付款待辦」；**勞報單不進** | 第 4 節 3 的 `CALENDAR_SOURCES` 含 `subcontract_voucher`、`case_material`、`case`，不含 `payroll_payslip` |
| Q4 | 文字只放：單號＋名目＋關聯案件；**不放金額、受款人／承攬商人員姓名、廠商名** | 事件／信／站內通知一律套用；承攬商文字不含廠商名（原 G1 的「可含廠商名」撤回）；case 現有事件的「受款人」「付款條件」行**須移除**（現行 `payable_calendar.compose` 含受款人，與本裁示不符，列入 S1 或 S5 一併修，並補斷言） |
| Q5 | 維持出納排序（承攬商依應付款日） | 只加欄位不改排序 |
| Q6 | 編輯權限維持：財務角色／superadmin＋申請人本人；不放寬 CM14b | 照 G5 矩陣 |
| Q7 | 財務改預定日 ⇒ 通知申請人（不含金額） | G4 第 2 點 |
| Q8 | 方案 B：L1 純函式庫＋各模組薄接線 | 第 4 節 B |

## 10. 與 c0（勞報單）的對齊點

- 欄名 `planned_pay_date`、項目欄 `plannedPayDate`、鍵 `payroll_payslip:<單號>`、出納端點用第 2 節同一支；c0 的「比照額外支出 PATCH」改成「經 IP-100 `set_planned_pay_date`」。
- c0 的 Q7 已由使用者裁示：勞報單不進行事曆；通用層以來源開關排除（第 4 節 3），提醒信／通知仍含勞報單。
- c0 的 IP-100 提供者 `payroll_payslip` 的 `pending()` 需帶 `plannedPayDate`、實作 `set_planned_pay_date`；提醒／行事曆走第 4 節通用層，**不另寫勞報單專用掃描**。
- 勞報單「核准後出納即可見、付款鈕需已簽回」不影響本文：`eligible` 判準對勞報單＝已核准、未付款、未作廢（簽回與否只決定付款鈕，不決定是否提醒預定日）。
