# 財務串接總覽（FINANCE-INTEGRATION）——快取檔

> 用途（使用者 2026-09-30）：把「錢怎麼從來源模組走到報表、案件成本、出納、總帳」集中在一個檔，後續開發不必再重讀各模組程式碼。
> **這是快取，不是真相**：契約與行為以各 IP 章節（`INTEGRATION-POINTS.md`）、`MONEY-FLOWS.md`（覆蓋表）、程式碼與測試為準；衝突時以它們為準並更新本檔。
> 來源 commit：`wip/w4-gl` 67002ec4（總帳 A＋B＋C1＋C2＋修補）、`wip/w4-gl-c3` 8530b846（C3／C3b／R12）、train/25 dee6bc2b。改了下列任一項就更新本檔並換來源 commit。
> 相關：`MONEY-FLOWS.md`（每個收支來源一列，含總帳事件碼／分錄／狀態）、`backend/modules/accounting/ledger/README.md`（總帳規則快取）、
> 設計稿 `proposal-general-ledger`（02 事件與引擎、10 來源派工單）。

## 1. 串接總表

| 串接 | 編號／能力名 | 提供方 → 使用方 | 資料形狀（重點） | 冪等／反轉規則 | 功能旗標 | 守門測試 |
|---|---|---|---|---|---|---|
| 支出（一般） | IP-9 `expense.entries`（多提供者，名稱＝來源：`bonus`、`payslip`、`remit_fee_contractor`、`remit_fee_case`、`receipt_fee`、`custom_module`） | 各模組 → M08 `analytics/api/reports.py::_collect_expenses`（營運報表、月報信、首頁） | `fn(conn,start,end) -> [{date, quoteNo, desc, amount, category}]`；`date`＝**現金事件日**；權責＝現金才用這條 | 純查詢；來源狀態變了下次就變 | 無 | `payroll/tests/test_payslip_void_signed_paid_2026_09_29.py`、各模組 `*_providers` 題 |
| 收入（現金） | IP-98 `receivables.income_items` | M05 arap → M08 | 已收款品項逐筆（quoteNo、customer、amount＝含稅收入、netAmount＝銀行入帳、feeAmount…）；語意見 `helpers.tax_calc.receipt_amounts` | 純查詢 | 無 | `arap/tests/test_receivables_providers.py` |
| 收入（權責）／支出（口徑不同） | IP-95 `case.recognition` | M01 case → M08 | 權責口徑收入、派工／叫料／額外支出的日期與稅 | 純查詢 | 無 | case 模組題 |
| 出納待付 | IP-100 `payables.pending`（名稱 `case`）；IP-14 承攬商匯款；IP-8 `bonus.payouts`；IP-103 `payslip.payables` | 各模組 → M05 出納 | `pending(conn)` 列已核准未付；`mark_paid(conn,key,date,user)` 寫回（呼叫端 commit） | 條件式 UPDATE＋rowcount，雙擊只成功一次 | 無 | `arap/tests/test_cashier_pending_payables_2026_09_27.py` |
| 匯款差額審核 | IP-102 `remit.reviews`（`contractor_voucher`、`case`） | M04／M01 → M05 | 實付≠應付 ⇒ `remit_review='pending'`，admin 核可／退回 | 退回＝回未匯款並清欄位 | 無 | subcontract／case 的 remit 題 |
| 傳票草稿 | IP-2 `voucher.draft` | M06 → M07（獎金）、總帳引擎 | `fn(conn, *, voucher_date, summary, lines[{account_code,summary,debit,credit,…}], created_by, now, origin="")` ⇒ `{id, voucher_no}`；不 commit | `origin` 標記產生來源（`bonus_accrual`／`bonus_payment`）；借貸不平即拒 | 無 | `payroll/tests/test_voucher_connectors.py` |
| 傳票狀態 | IP-4 `voucher.status`／`voucher.by_no`／`voucher.void_draft` | M06 → M07、引擎 | status ⇒ `{id, voucher_no, status, voided, date}`；`void_draft` 只作廢草稿 | 已作廢＝`gone` | 無 | `payroll/tests/test_voucher_status_connectors.py` |
| **總帳事件** | **IP-GL1 `gl.events`（契約 v1，多提供者，名稱＝來源模組 key）** | arap、subcontract、payroll、supply、case（已接）；custom_modules、fixed_assets（待接）→ M06 `ledger/contract.py::collect`、`ledger/engine.py::run` | 見 §2 | 見 §3 | `engine_drafts`（預設關） | `accounting/tests/test_ledger_a_contract`、`c1_engine`、`c2_subcontract`、`c3_payroll`、`c3b_native`、`r12_remit_payslip` |
| 匯款單 ↔ 勞報單 | IP-105 `payslip.remit`（R12） | M07 payroll → M04 subcontract | `check(conn,slip_no)`；`candidates(conn,contractor_id)`；`mark_paid(conn,slips,remit_no,date,who)`；`unmark_paid(conn,remit_no)`（皆不 commit，與匯款同一交易） | 勞報單 `data_json.paid_via_remit`＝匯款單號；取消匯款一併退回；勞報單自己 unpay 被擋 | `system_settings.remit_require_payslip`（預設開，最高管理者可關、寫稽核） | `accounting/tests/test_ledger_r12_remit_payslip_2026_09_30.py` |
| 上傳檔權限 | IP-104 `uploads.path_access`（sec-p0，與金流無關，僅編號備忘） | 各單據模組 → L1 | — | — | — | sec-p0 題 |
| 自訂模組金流 | `custom_record_finance_outbox`（W1 S2.5，`wip/w1-builder3-s25`）＋IP-9 `custom_module` 提供者 | 建構器 L1 `helpers/custom_finance` → 報表（即時）／總帳（C7 消費 outbox） | outbox：`dedupe_key`（唯一）、`event`（入帳／反轉）、`module_key`、`record_id`、`record_no`、`kind`、`payload_json`、`processed_at`；狀態進入／離開入帳時**同一交易**寫入 | `dedupe_key` 唯一＝重送冪等；`processed_at` 空＝待消費；反轉是另一筆事件 | `custom_records`（C7） | W1 的 `test_custom_finance*`；C7 完成後加總帳題 |

> **總帳不消費 outbox**（主持裁示 2026-09-30）：C7 以『拉取式提供者』讀目前處於入帳狀態的自訂單據（即時集合），事件由引擎冪等產生、單據離開入帳狀態 ⇒ 事件消失 ⇒ 引擎反轉；outbox 只作稽核軌跡。金額欄位 → 科目靠會計維護的 `gl_custom_field_map`，未對應的欄位 ⇒ 事件標 `blocked_no_account` 並說明。
| 補登（不改來源） | `gl_source_annotations`（總帳自有表） | 會計 → 引擎收集 | `(source_type, source_key, field, value)`；認得 `input_tax`（非負整數：覆寫承攬商發票 E04／進貨發票 E08b 的估算稅額，E09 跟著調整；把『未拆稅』的額外支出 E11／叫料 E12 拆成成本＋進項稅額）與 `invoice_date`（E04／E08b 的入帳日） | 補登值不合法 ⇒ 忽略並在事件 `meta.annotation_ignored` 標記；補登改變內容雜湊 ⇒ 已過帳者走 drift | `source_annotations` | `c2_subcontract` |

## 2. `gl.events` 契約 v1（事件形狀）

- 提供者：`registry.provide("gl.events", <模組 key>, fn)`；`fn(start, end, *, changed_since="") -> {"events": [...], "notice": "文字"}`；只讀、不寫資料、不 commit。
- 事件：`{source_type, source_key, event_code, event_date, doc_no, case_no, party:{key,name}, tax_code, mode, lines:[{role, side D|C, amount 非負整數, account_code?, memo?, tax_code?}], meta}`。
  - `source_key` **不可變**（表的 id／單號，不用陣列索引）；沒有不可變 id 的舊資料退回索引並標 `meta.weak_key`，notice 說明。
  - 金額一律整數（新臺幣元）；借貸必須相等；用**角色**（`AP`、`AR`、`BANK`、`FEE`、`INPUT_TAX`、`OUTPUT_TAX`、`COST_PROJECT`、`EXP_LABOR`、`OTHER_PAYABLE`、`WITHHOLD_TAX`、`WITHHOLD_NHI`、`ADV_RCPT`、`INVENTORY`、`COGS`…）不寫科目；角色 → 科目在 `gl_account_roles`（可依生效日改）。要指定實際銀行帳戶時該行帶 `account_code`。
  - 不要把使用者資料放進事件：對象只放代碼＋名稱（勞報單用 `C<contractor_id>`，**不帶身分證字號**）。
- `mode`：`snapshot`（預設；內容整組取代）、`cumulative`、`append`、**`stock`**（存貨出庫 E10：來源只回 `stock_part_no`、`stock_qty`、案件、日期，無 lines、無金額；引擎依 `ledger/inventory.py` 移動加權平均算金額並組成 借 COGS 依案件／貸 INVENTORY；均價變動不算來源變動；來源消失或數量變動 ⇒ 存貨鏈以原金額回沖；在庫不足 ⇒ 狀態 `blocked_inventory`，補跑進貨事件所在期間後自動重試；同一天進貨先於出庫）、**`native`**（來源已自行開了傳票：事件只帶 `native_voucher_id`，無 lines；引擎登記狀態 `native`、不產生不改動；傳票作廢或改指向新傳票 ⇒ 舊列 `superseded`、新列 `native`；例：獎金 E07a／E07b）。
- 內容雜湊：入帳日、各行（角色／方向／金額／案件／對象／稅碼／account_code）、案件、對象、稅碼；`meta` 與說明文字不參與。native 只看傳票 id＋日期。
- **來源缺席一律明說**：提供者未安裝、未接入、丟例外或回 notice ⇒ 出現在引擎回應與『分錄草稿』頁籤，不會顯示成 0 筆。格式不合格的事件列入 `invalid`（含原因），不整批失敗。
- 事件碼對照：E01／E03 銷項發票與客戶收款（arap）、E04／E05／E05b 承攬商發票／匯款／個人點工補列（subcontract）、E06／E06b 勞報單應付／付款（payroll）、E07a／E07b 獎金核准／發放（payroll，native）、E08～E10 存貨（supply，C4）、E11／E11b／E12 案件額外支出與叫料（case，C4b）、E13 固定資產（C6）、E20／E21 自訂模組（C7）。

## 3. 引擎的冪等與反轉規則

- 事件以 `(source_type, source_key, event_code, rev)` 為鍵存在 `gl_source_events`；引擎狀態：`drafted`（草稿）、`posted`、`drift`（來源改了而舊傳票已過帳）、`reversed`、`superseded`、`orphan`（來源消失）、`rejected`（草稿被作廢）、`blocked_closed`（期間已結帳）、`blocked_no_account`（缺角色科目）、`blocked_inventory`（存貨在庫不足）、`native`。
- 同雜湊再跑 ⇒ 什麼都不做（冪等）。雜湊變了：草稿 ⇒ 作廢重建；已過帳 ⇒ **不改舊傳票**，標 drift，另產反向草稿（日期＝今天）與新內容草稿。
- 來源消失（例：勞報單退回簽回、取消收款）：只在該來源本次回應 ok 時才判 orphan（來源壞掉不可誤判成消失）；草稿作廢，已過帳者產反向草稿。
- 引擎產生的傳票 `kind='auto'`、走既有簽核（可設 `voucher_auto_approval_flow`）；整批確認只處理 `auto`／`reversal`，手工與獎金傳票不受影響。
- 期間鎖三層（API 訊息／引擎／8 個 DB 觸發器）：已結帳期間不可過帳、不可作廢已過帳傳票；要更正用反向傳票或由具權限者重開期間並填理由。沒有期間資料＝全部視為開放。
- 個別規則：E03 用 W2 語意（實收＝銀行入帳，手續費另列，含稅收入＝實收＋手續費）；E05 實付≠應付且**已核可**才入帳（差額入 `EXP_OTHER`），待審核不產生並 notice；已關聯勞報單的個人行借 `OTHER_PAYABLE` 而非 `AP`，且該勞報單不再產生 E06b。

## 4. 功能旗標與設定

- **營業稅 401**（`tax401`）：`GET /api/ledger/tax401` 由已過帳分錄（稅碼＋科目類別）彙總，不另讀單據；對帳＝稅額科目、與 arap 發票逐項；`POST …/settlement` 產生期末稅額結轉草稿（E14）。**扣繳清單**（`withholding`）：引擎產生 E06 草稿時記入 `gl_withholding_items`，`GET /api/ledger/withholding`、`POST …/withholding/remit`。新來源若有稅額，事件行/事件要帶稅碼（OUT-*／IN-*），401 才抓得到。
- 總帳作業（`ledger-hub`）的 `gl_settings` 鍵 `feature.<名稱>`，預設全關，最高管理者開：`engine_drafts`、`withholding`、`inventory_cost`、`tax401`、`fixed_assets`、`invoice_adjustments`、`custom_records`、`backfill`、`source_annotations`。旗標關閉時引擎 API 回說明、現有手工傳票行為完全不變。
- `system_settings.remit_require_payslip`：個人外包匯款前必須關聯勞報單（預設開；`PUT /api/contractor-vouchers/settings/remit-require-payslip`，僅最高管理者、寫稽核）。已帶勞報單者不論設定一律驗證（已簽回、受款人相符、金額＝勞報單實付）。
- `voucher_auto_approval_flow`（system_settings）：引擎傳票的簽核流程，未設定＝與手工傳票相同。

## 5. 會被誤觸的全域守門（新增提供者／頁面／端點常見紅燈）

`docs/platform/modules.json` 單元所有權（新檔要登記）｜IP 登記（`test_integration_points_registered`：提供者要有 IP 章節；取用的能力名要是字面值＋provider 形式，不可用變數/格式字串帶出能力名）｜`test_module_changelog_follows_code`（改程式要升 `module.json` 版號＋CHANGELOG）｜
`test_accounting_foreign_reads`（M06 不可新增讀別組的表；基線記錄檔名）｜`test_ship_tier_2026_09_28`（提供者解析）｜`test_company_setup_output_points`（新的檔案輸出點要經第二道 `company_name()` 等）｜`test_ac1_write_actions`（頁面寫入呼叫要有字面 `method: 'POST'`，純查詢頁登記理由）｜
`test_write_endpoints_are_audited`（寫入端點要 `_audit`）｜`test_system_audit`（角色字串比對只准已知角色；帳務角色名用常數比對）｜`test_no_credentials_in_query`（查詢參數不可叫 `key`／`token` 等）｜`test_view_filter_marking`（像篩選的欄位要 `class="filter"` 或 `data-saved-field`）｜
`test_alpine_double_init`（`PAGE_POPULATION` 頁數）｜`test_scope_gate`（掃整棵樹的測試要列進 `bottom_layer.json` 的 `global_tests`）｜產生檔（UNIT-INDEX、dep_graph、test_map）不可由分支 commit。

## 6. 新增一個金流來源的檢查表

1. **盤點語意**：是收入還是支出？現金事件日與權責日各是哪個欄位？金額含稅還是未稅？有沒有手續費／預收／退回？有沒有個資不可進總帳？
2. **MONEY-FLOWS.md 加一列**（同一個 commit）：營運報表現金／權責、案件成本、出納、T100、總帳事件碼／分錄／狀態／旗標；`module.json` 的 `money_flows` 宣告（守門 `test_money_flows_registered`）。
3. **報表側提供者**：一般支出用 IP-9 `expense.entries`（名稱＝來源）；收入用 `receivables.income_items` 或 `case.recognition`；出納用 `payables.pending`。提供者不在 ⇒ 少那一類並**明說**。
4. **總帳提供者** `modules/<key>/gl_events.py`：只讀；事件 `source_key` 用不可變 id；角色＋整數金額；缺資料寫 notice；已由來源模組自己開傳票的用 `mode=native`。在 `ModuleSpec.providers` 登記 `("gl.events", "<key>")`，`INTEGRATION-POINTS.md` 的 IP-GL1「提供方」列加一筆，`docs/platform/modules.json` 加單元。
5. **升版**：`module.json` 版號＋該模組 CHANGELOG；動到 `accounting` 也要升。
6. **測試**（放 `accounting/tests/test_ledger_<批次>_*.py`）：正對照（每個事件碼的分錄、借貸平衡且 `validate_event` 通過）、反向控制（缺席／壞資料 ⇒ notice 不是 0 筆；退回或取消 ⇒ 來源消失 ⇒ 引擎反向）、引擎整合（真提供者跑兩次第二次 created＝0）、邊界（零稅、窗外日期、待審核）。
7. **跑守門**（§5 那串）＋該模組全部測試＋若動到頁面的 e2e；列車跑全量，各線只跑差異題。
8. **文件**：更新本檔 §1 一列、MONEY-FLOWS.md 狀態、`ledger/README.md`（若改了規則）。

## 7. 已知陷阱

- 來源模組不可 import 會計的表（M06 foreign reads 守門）；要傳票日期等資料走提供者（`voucher.status` 已帶 `date`）。
- 提供者要「只讀」：回傳前不 commit、不寫；需要一起變更兩個模組的資料（例：匯款＋勞報單）用 provider 的動作函式，**由呼叫端在同一個交易 commit**。
- 事件的 `lines` 若含 `account_code`，會進雜湊；改銀行帳戶會被視為內容變動（草稿重建／已過帳 drift）。
- 測試日期用遠期年份（2170～2174）避免撞到共用測試庫的既有資料；共用庫的測試要自己清乾淨或作廢自己開的傳票。
- 凍結期間（列車全量跑時）不開 pytest；寫碼與 commit 可以。
