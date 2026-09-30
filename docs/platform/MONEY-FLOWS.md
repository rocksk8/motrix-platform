# 金流串接覆蓋表（MONEY-FLOWS）

> 使用者規則（2026-09-30，計畫檔「金流串接規則」）：**「只要有收入、支出項，都需要跟營運報表或是相關模組數據串接」**。
> 本檔盤點全系統的收入／支出來源，逐一標出：進不進 營運報表（現金／權責）、案件成本、出納、T100 傳票（未來總帳）。
> **缺口標 🔴**；「不是金流」標 ⚪（附理由）；已驗證＝✅；程式或文件查得到但尚未用測試驗證＝🟡（要驗證的地方寫在備註）。
> 產出時間 2026-09-30（基底 origin/train/0930 642b7574）；來源欄的檔案:符號是讀碼位置，不是行號（行號會漂）。
>
> 契約、提供者、冪等規則、旗標、守門測試與「新增金流來源檢查表」集中在 [`FINANCE-INTEGRATION.md`](FINANCE-INTEGRATION.md)（快取檔）。
>
> **這份表也是「財務串接總表」（使用者 2026-09-30）**：每一列另有〈總帳事件碼〉〈分錄〉〈總帳狀態〉〈功能旗標〉四欄，標明它進不進總帳、
> 用哪個事件碼、借貸哪些角色、上線到哪一班或還沒做。總帳的設計細節在 `docs/platform/plans` 的 proposal-general-ledger（02 事件與引擎、10 來源派工單）。

## 0. 怎麼串接（新來源的做法）

| 方向 | 進報表的做法 | 提供者名稱規則 |
|---|---|---|
| 收入 | `receivables.income_items`（現金口徑收入明細；金額語意見 `helpers.tax_calc.receipt_amounts`）／權責另由 M01 `case.recognition` | 收入來源目前只有「案件收款品項」一種 |
| 支出（一般） | IP-9 `expense.entries`：`fn(conn, start, end) -> [{date, quoteNo, desc, amount, category}]`，日期是**現金事件日**；權責／現金兩口徑相同才用這條 | `expense.entries` 的名稱＝來源，例 `bonus`、`payslip`、`remit_fee_contractor`、`receipt_fee` |
| 支出（口徑不同） | 由 M01 `case.recognition` 依口徑決定日期與稅（派工／叫料／額外支出）；其他模組不自己算 | — |
| 出納 | `payables.pending`（待付）／`bonus.payouts`／`payslip.payables`／`remit.reviews`（實付差額審核） | — |
| T100（未來總帳） | `accounting_export._collect_t100_events` 依事件產傳票；新來源要加一段事件，並在 T100 設定加科目 | — |

L2 模組**不互相 import**，一律經 provider；提供者不在 ⇒ 少那一類並「明說」，不是 0。

## 1. 收入

| # | 來源（表／事件） | 讀碼位置 | 營運報表 現金 | 營運報表 權責 | 案件成本／財務 | 出納 | T100 | 備註 | 總帳事件碼 | 分錄（借／貸 角色） | 總帳狀態 | 功能旗標 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | 案件收款品項 `quotations.data_json.caseRecord.payment.items`（已收款、收款日） | `arap/receivables.py::collect_income_items`；`case/recognition.py::accrual_income_items` | ✅ 收入＝銀行入帳＋客戶內扣手續費、依收款日、含稅 | ✅ 依階段完成月、未稅（切換） | ✅ 案件財務 Tab（淨收＝入帳） | ✅ 待收款／已收款 | ✅ 有填發票號碼者 | 未填發票號碼的收款不出 T100 傳票（設計：T100 只做銷項發票事件）。🟡 這類收款要不要另出「無發票收款」傳票＝待使用者／會計確認 | E01 開立發票、E03 客戶收款（arap） | E01：借 AR／貸 REV_SALES＋OUTPUT_TAX；E03：借 BANK＋FEE／貸 AR（未開票貸 ADV_RCPT）；先收後開票另有預收沖轉 | ✅ 已上線（train 25，C1） | `engine_drafts` |
| R2 | 客戶內扣收款手續費（同一品項的 `feeAmount`） | `arap/receivables.py::expense_entries`（IP-9 `receipt_fee`） | ✅ 列支出「收款手續費」，收款日 | ✅ 同（現金事件） | 🔴 案件毛利／精算（settlement）**尚未**把收款手續費列入案件成本；案件財務 Tab 只顯示「另列費用」 | ✅ 已收款明細另列 | ✅ 收款傳票借方拆「手續費」一行（`receiptFeeAccount`） | 缺口見 §4 G1 | E03 的 FEE 行（arap） | 借 FEE（收款手續費，7243）；含稅收入＝實收＋手續費（W2 語意） | ✅ 已上線（train 25，C1） | `engine_drafts` |

## 2. 支出

| # | 來源（表／事件） | 讀碼位置 | 營運報表 現金 | 營運報表 權責 | 案件成本 | 出納 | T100 | 備註 | 總帳事件碼 | 分錄（借／貸 角色） | 總帳狀態 | 功能旗標 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | 承攬商派工／匯款申請 `contractor_payment_vouchers`（`is_paid`、`remit_actual`） | `case/recognition.py::dispatch_entries`；`subcontract/api/contractor_vouchers.py` | ✅ 已匯款日、含稅、實付 | ✅ 發票日、未稅 | ✅ 派工金額（精算 dispatchTotal） | ✅ 待匯款／已匯款 | ✅ `contractor_voucher.paid_between` | — | E04 承攬商發票、E05 匯款、E05b 個人點工（subcontract） | E04：借 COST_PROJECT＋INPUT_TAX／貸 AP（稅額可經 `source_annotations` 補登實際值）；E05：借 AP＋FEE／貸 BANK；實付≠應付且已核可⇒差額入 EXP_OTHER | ✅ 已上線（train 25，C2）；E05b 為歷史未關聯勞報單的補列 | `engine_drafts`（稅額補登另需 `source_annotations`） |
| E2 | 承攬商匯款手續費（`remit_fee`，公司自付） | `subcontract/remit.py::_expense_entries`（IP-9 `remit_fee_contractor`） | ✅ | ✅ | ✅ 精算頁 `remitFeeTotal` | ✅ | ✅ `remitFeeAccount` | 案件管理「財務彙總」（`loadFinanceSummary`）是否含手續費＝🟡 待驗（稽核 S1） | E05 的 FEE 行（subcontract） | 借 FEE（匯款手續費，公司自付）／貸 BANK | ✅ 已上線（train 25，C2） | `engine_drafts` |
| E3 | 案件額外支出 `case_extra_expenses`（`total_cost`、`paid_date`） | `case/recognition.py::extra_entries`；`case/payables.py` | ✅ 付款日 | ✅ 發票日→核准日→憑證日 | ✅ 精算 xeTotal | ✅ `payables.pending` | 🔴 T100 沒有額外支出付款事件 | 缺口 G2 | E11／E11b 額外支出與付款（case） | 借 COST_*／INPUT_TAX 貸 AP；付款借 AP 貸 BANK（設計見 proposal-gl 02 §4） | 🔧 已寫（wip/w4-gl-c3，測試中；C4b） | `engine_drafts` |
| E4 | 額外支出匯款手續費（`remit_fee`） | `case/payables.py::_expense_entries`（IP-9 `remit_fee_case`） | ✅ | ✅ | ✅ | ✅ | 🔴 同 E3 | 缺口 G2 | E11b 的 FEE 行（case） | 借 FEE／貸 BANK | 🔧 已寫（同 E3；C4b） | `engine_drafts` |
| E5 | 叫料（材料訂單） | `case/recognition.py::material_entries` | ✅ 付款日 | ✅ 發票日 | 🟡 精算的「材料」是否含叫料＝待驗 | 🟡 叫料付款是否走出納＝待驗 | 🔴 無 | 缺口 G3 | E12 叫料（case） | 借 COST_*／INPUT_TAX 貸 AP（設計見 proposal-gl 02 §4） | 🔧 已寫（wip/w4-gl-c3，測試中；C4b） | `engine_drafts` |
| E6 | 進貨批次／料件成本 `stock_batches`、`stock_items.cost` | `analytics/api/reports.py::_collect_expenses`（stock_items 段）；`accounting/api/accounting_export.py::_collect_paid_stock_batches` | 🟡 依批次日歸月，**不分口徑**（兩口徑同一數字） | 🟡 同左 | ✅ `stock_items.quote_no` | 🟡 進貨付款 `paid-toggle` 在庫存頁，不在出納頁 | ✅ 已付款批次 | 口徑差異記在 §4 G4 | E08 進貨、E08b 進貨發票、E09 進貨付款、E10 出貨成本（supply） | E08：借 INVENTORY／貸 AP；E08b：借 INPUT_TAX／貸 AP；E09：借 AP／貸 BANK；E10：借 COGS／貸 INVENTORY（移動加權平均） | ✅ 已完成（wip/w4-gl-c3，測試綠；C4）：E08／E08b／E09 與出庫成本 E10（移動加權平均，`mode=stock`）；報廢／盤損尚未自動入帳 | `engine_drafts`（存貨明細／對帳頁另需 `inventory_cost`） |
| E7 | 勞報單 `payslips`（已付款、`gross_amount`） | `payroll/payslip_payouts.py::_expense_entries`（IP-9 `payslip`） | ✅ 付款日、應付總額 | ✅ 同（付款日；不分口徑） | ⚪ 勞報單不掛案件（若有掛案件才會進案件成本＝🟡 待驗） | ✅ `payslip.payables` | 🔴 T100 無勞報單付款事件 | 缺口 G2 | E06 勞報單應付、E06b 勞報單付款（payroll） | E06：借 EXP_LABOR／貸 WITHHOLD_TAX＋WITHHOLD_NHI＋OTHER_PAYABLE；E06b：借 OTHER_PAYABLE／貸 BANK（由匯款單付款者不產生，見 E10） | ✅ 已接受（train 26，C3） | `engine_drafts`（扣繳報表另需 `withholding`） |
| E8 | 獎金分潤發放 | `payroll/bonus_payouts.py::_expense_entries`（IP-9 `bonus`） | ✅ 發放日、案件合計 | ✅ 同 | 🟡 獎金是否列入案件毛利＝待驗 | ✅ `bonus.payouts` | 🔴 T100 無獎金發放事件（`bonus_vouchers.py` 有獎金傳票：權責／發放，可作為總帳來源＝🟡 待接） | 缺口 G2 | E07a 核准應付、E07b 發放（payroll，**native**） | 不由引擎產生：登記獎金模組已開立的傳票（核准：借 6111／貸 2191；發放：借 2191／貸銀行＋代扣 2252）；引擎狀態 `native`，不重複、不改動 | ✅ 已接受（train 26，C3b） | `engine_drafts` |
| E8b | 獎金更正單（已發放獎金的事後更正：補發／追回） | `payroll/bonus_correction.py::expense_entries`（IP-9 `bonus_correction`） | ✅ 補發＝補發日 +補發額；追回＝核准日 −追回額 | ✅ 同 | 🟡 同 E8 | ✅ `bonus.payouts`（kind=correction，補發列） | 🟡 沖轉＋重開應付＝`voucher.draft(reverses_voucher_id)` 草稿；追回＝借其他應收款／貸應付（追回處理方式待確認）；補發＝借應付／貸銀行 | — | 不由引擎產生（native E07a/E07b 列不動；`test_engine_leaves_correction_vouchers_alone`） | 見 §9 W-6／W-7；沖轉被總帳拒絕時不開沖轉也不重開 | ✅ train 28 | `engine_drafts`（僅引擎那一腿） |
| E9 | 自訂模組的金額欄（`number`／`formula` 欄位） | `helpers/custom_modules.py`（欄位型別 `number`、`formula`） | 🔴 沒有「這個欄位是金額、是收入還是支出」的宣告，所以**不可能**進報表 | 🔴 | 🔴 | 🔴 | 🔴 | 缺口 G5：需要欄位型別 `money`（含方向、日期欄）＋提供者 | E20／E21 自訂模組入帳（custom_modules） | 由建構器 outbox 的入帳對應決定（角色＋維度）；來源＝W1 S2.5 的 `custom_record_finance_outbox`（交易內 emit，含 finance_settled 與稅額拆分，R8 已滿足） | 🟡 已排程（C7；W1 S2.5 outbox `custom_record_finance_outbox` 已完成於 wip/w1-builder3-s25，前置解除） | `custom_records`（入帳）＋`engine_drafts` |
| E10 | 承攬商匯款單關聯勞報單（R12：個人外包匯款前必須關聯勞報單，匯款金額＝勞報單實付） | `payroll/remit_link.py`（IP-105 `payslip.remit`）；`subcontract/api/contractor_vouchers.py` | ✅ 同 E1／E7（匯款日；勞報單由匯款單一併記為已付款） | ✅ 同 | ⚪ 勞報單不掛案件 | ✅ 出納頁／案件頁「標記已匯款」視窗挑選勞報單 | 🔴 同 G2 | 匯款標記與勞報單付款同一個交易；取消匯款一併退回；勞報單自己的 unpay 被擋。設定 `remit_require_payslip`（預設開、僅最高管理者可關、寫稽核） | E05（該行借 OTHER_PAYABLE）；該勞報單不產生 E06b | 借 AP（其餘）＋OTHER_PAYABLE（已關聯個人）＋FEE／貸 BANK | 🔧 開發中（train 26 待測試） | `engine_drafts`＋設定 `remit_require_payslip` |

## 3. 不是金流（⚪，附理由）

| 來源 | 理由 |
|---|---|
| 請款單 `payment_requests`（對客戶要款的文件） | 文件；實際收款登錄在案件收款品項（R1）。請款金額不是收入事件 |
| 開票申請 `invoice_vouchers` | 文件；發票號碼寫回收款品項（R1），金額由 R1 承載 |
| 出貨單 `shipping_notes` | 只有品項數量，沒有金額欄（成本由進貨／叫料承載） |
| 標案雷達 `tenders.budget`、`tender_watches.budget_*` | 標案預算是情報，不是本公司收支 |
| 住宿（lodging）官方參考房價、各產品庫 `price_range`／`price_note` | 參考價 |
| 會計傳票 `vouchers`（accounting） | 它就是總帳本身：不是報表的收入／支出來源；金流來源要**產生**傳票，見 T100 欄 |

## 4. 缺口清單（能補的先補；補不了列理由）

| 編號 | 缺口 | 建議做法 | 狀態 |
|---|---|---|---|
| G1 | 客戶內扣收款手續費未進案件成本／毛利 | 案件精算（settlement）與財務彙總把 `receipt_fee` 併入成本；經 `case_finance` 讀 L1 `receipt_amounts`，不 import arap | 待做（本班若時間夠，否則下一班）；涉及毛利定義＝**回報主持定案** |
| G2 | T100 缺：額外支出付款、額外支出手續費、勞報單付款、獎金發放 | 在 `accounting_export._collect_t100_events` 各加一段事件，資料經 provider（`payables.paid`、`payslip.paid`、`bonus.payouts.paid`），並在 T100 設定加科目；借貸相等由測試守 | 下一班（每種一個科目設定＋一段事件＋一組題） |
| G3 | 叫料：案件成本／出納／T100 三格待驗 | 先用測試查清楚現況再決定；查完更新本表 | 待驗 |
| G4 | 進貨批次不分口徑（現金＝權責） | 進貨有付款日（現金）與發票日（權責）：比照叫料改由 `case.recognition` 決定日期；目前用批次日近似 | 記錄；要不要分口徑＝**回報主持定案** |
| G5 | 自訂模組金額欄無法進報表 | 欄位型別 `money`（宣告方向＝收入／支出、日期欄、案件欄）＋自動註冊 `expense.entries`／收入提供者；沒宣告金額語意的模組維持不進報表並在設計頁明說 | 設計中；影響法規以外，回報主持 |
| G6 | 進貨付款不在出納頁 | 出納頁加「進貨待付」（`payables.pending` 提供者由 supply 提供） | 下一班 |

## 5. 守門（`tests/platform/test_money_flows_registered.py`）

- 每個模組的 `module.json` 可宣告 `money_flows`：`[{"key": "payslip", "direction": "expense", "provider": "expense.entries/payslip"}, …]`。
- 守門：宣告的每個 `provider` 必須在該模組 `ModuleSpec.providers` 有登記；反過來，模組登記了 `expense.entries`／`receivables.income_items` 提供者卻沒有宣告 ⇒ 紅（新增金流來源一定要在這裡留名）。
- 反向控制：拿掉某個提供者登記 ⇒ 紅；拿掉某個宣告 ⇒ 紅。
- 新模組有金額欄位就必須登記（規則寫進 MODULE-GUIDE「金流串接」節）。

## 6. 更新這份表

- 新增收入／支出來源的分支：**同一個 commit** 更新本檔與 `module.json` 的 `money_flows`。
- 🟡 的格子被驗證後改成 ✅ 或 🔴 並寫測試名。

## 7. 總帳串接（欄位說明與班次）

- **總帳事件碼**：`gl.events`（IP-GL1，契約 v1）事件的代碼。E01～E03 銷項與收款、E04～E05b 承攬商、E06～E06b 勞報單、E07a／E07b 獎金、E08～E10 存貨、
  E11～E12 案件支出、E20／E21 自訂模組。批次：C4＝存貨（E08～E10）；C4b＝案件額外支出與叫料（E11／E11b／E12，與存貨同批）；C7＝自訂模組（E20／E21，W1 outbox 已完成）與折讓。**native**＝來源模組已自行開立傳票，事件只登記（`mode=native`，引擎不產生、不改動）；其餘由引擎產生 `kind=auto` 草稿走既有簽核。
- **分錄（借／貸 角色）**：事件用「角色」不用科目；角色 → 科目在總帳設定（`gl_account_roles`，可依生效日改）。缺角色 ⇒ 標 `blocked_no_account` 並說明，不猜。
- **總帳狀態**：✅ 已上線／已接受（寫明班次與批次）、🔧 開發中、🟡 規劃中（有批次編號）、🔴 未做。班次：train 25＝總帳 A＋B1～B5＋C1＋C2；train 26＝C3（勞報單）、C3b（獎金 native）、R12（匯款↔勞報單）。
- **功能旗標**：總帳作業（`ledger-hub`）的 `gl_settings` 鍵 `feature.<名稱>`，預設全關，最高管理者開啟。`engine_drafts` 關閉時，引擎與各來源提供者對現有手工傳票沒有任何副作用。
  另有系統設定 `remit_require_payslip`（預設開；緊急開關，僅最高管理者、寫稽核）。
- **來源缺席一律明說**：提供者未安裝、未接入或丟例外 ⇒ 引擎回應與『分錄草稿』頁籤列出原因，不會顯示成「0 筆」。
- **待補登資料**：承攬商發票實際稅額、進貨發票日期／稅額等，來源模組不必加欄位，由會計在 `gl_source_annotations`（旗標 `source_annotations`）補登，補登值優先於來源值。

## 8. 資料流圖（文字版）

```
收入
  案件收款品項（M01 quotations.data_json）──→ arap receivables ──┬─→ 營運報表（現金／權責）
                                                                    ├─→ 案件成本／財務彙總（receipt_fee 缺口 G1）
                                                                    ├─→ 出納（待收）
                                                                    └─→ 總帳 gl.events E01／E03 ──→ 引擎草稿 ──→ 簽核 ──→ 過帳 ──→ 四大表
支出
  承攬商派工／匯款單（M04）───────────────────────────────┬─→ 營運報表（IP-9 expense.entries、case.recognition）
    └─ 個人外包人員 ──(R12 payslip.remit)──→ 勞報單（M07）    ├─→ 案件成本（精算頁）
                                                              ├─→ 出納（payables／remit.reviews）
                                                              └─→ 總帳 E04／E05／(E05b) ；已關聯勞報單者 E05 借 OTHER_PAYABLE
  勞報單（M07 payslips）──────────────────────────────────┬─→ 營運報表（付款日）  ├─→ 出納（payslip.payables）
                                                            └─→ 總帳 E06／E06b（由匯款單付款者只有 E05）
  獎金分潤（M07 bonus）──→ bonus_vouchers 開傳票（origin=bonus_*）──→ 總帳 E07a／E07b（native：登記既有傳票）；營運報表／出納照舊
  額外支出、叫料（M01 case）─→ 營運報表、案件成本、出納 ；總帳 E11／E12 已寫（C4b，測試中）
  進貨／存貨（M03 supply）───→ 營運報表（近似）；總帳 E08～E10 已完成（C4；出庫成本走存貨鏈移動加權平均）
  自訂模組金額欄（建構器）───→ 尚不進報表；總帳 E20／E21 已排程（C7；W1 S2.5 outbox custom_record_finance_outbox 已完成，前置解除）
總帳內部
  gl.events（各提供者，contract.collect）→ 補登覆寫（gl_source_annotations）→ 引擎（冪等、drift、orphan、期間鎖）→ 傳票（voucher_lines）
  → 試算表／總分類帳／明細分類帳／日記帳 → 資產負債表／損益表／權益變動表／現金流量表 → 年度結轉與決算（凍結快照）
```

## 9. 跨模組寫入連結（使用者規則 R1，2026-09-30）

> 規則：一個模組**改另一個模組的資料**（不是只讀）時，寫入點要有註解（`⚠ 跨模組寫入連結`）＋在這裡登記一列（誰寫誰、寫哪些欄位、怎麼寫、交易、反向、守門）。
> 只讀的串接（provider 取數）不算；總帳引擎寫的是總帳自己的表（`gl_*`、`vouchers_all` 草稿）不算跨模組寫入。
> 「註解」欄＝寫入點是否已加註解；未加者標「待補」，由擁有該寫入點的線補（不在本檔範圍動別人的程式）。

| 編號 | 寫入方 → 被寫方 | 連接器 | 被寫的資料（欄位） | 交易／反向 | 寫入點 | 註解 | 守門測試 |
|---|---|---|---|---|---|---|---|
| W-1 | M04 subcontract → M07 payroll | IP-105 `payslip.remit`（`mark_paid`／`unmark_paid`） | `payslips.status`（已簽回⇄已付款）、`payment_date`、`paid_by`、`paid_at`、`data_json.paid_via_remit` | 與匯款單同連線同一次 commit；取消匯款反向退回；勞報單自己的 unpay 被擋（409） | `subcontract/api/contractor_vouchers.py::toggle_paid` | ✅ | `accounting/tests/test_ledger_r12_remit_payslip_2026_09_30.py` |
| W-2 | M07 payroll → M06 accounting | IP-2 `voucher.draft`（`origin` 選填）、IP-4 `voucher.void_draft` | `vouchers_all`／`voucher_lines`（獎金核准應付、發放傳票草稿）；作廢草稿 | 呼叫端連線、不 commit；退回獎金時作廢未送審草稿 | `payroll/bonus_vouchers.py::_make`、`withdraw_accrual` | 待補（payroll 線） | `payroll/tests/test_voucher_connectors.py` |
| W-3 | M05 arap（出納）→ M01 case | IP-100 `payables.pending`（`mark_paid`） | `case_extra_expenses.paid_date`（＋W1 `remit_actual`／`remit_fee`／`remit_review`） | 呼叫端連線、呼叫端 commit | `arap/api/cashier.py`（pending-payables/{來源}/{key}/pay） | 待補（arap／case 線） | `arap/tests/test_cashier_pending_payables_2026_09_27.py` |
| W-4 | M05 arap（出納）→ M04／M01 | IP-102 `remit.reviews`（`decide`） | `contractor_payment_vouchers.remit_review*`、`case_extra_expenses.remit_review*`（核可＝記錄；退回＝回未匯款並清欄位） | 條件式 UPDATE＋rowcount | `arap/api/cashier.py`（remit-reviews/…/decision） | 待補 | subcontract／case 的 remit 題 |
| W-5 | M01 case → M03 supply | IP-19 `stock.serial`（`claim`／`release`） | `stock_items.status`（in_stock⇄installed）、`quote_no`、`case_device_id`、`consumed_at` | 呼叫端連線、與案件資料同一次 commit | `case/api/quotations.py`（設備序號認領／釋放） | 待補（case 線） | supply／case 的序號題 |
| W-6 | M07 payroll → M06 accounting | IP-2 `voucher.draft`（`kind="reversal"`＋`reverses_no` 選填，獎金更正單加） | `vouchers_all`（kind／reverses_no／origin＝`bonus_corr_reversal`／`bonus_corr_accrual`／`bonus_corr_payment`）、`voucher_lines`（沖轉原應付＋重開應付＋補發支出，皆草稿） | 核准與標記補發各在自己的交易內、呼叫端 commit；更正單不可退回（已開沖轉傳票）；補發傳票不自動作廢 | `payroll/bonus_correction.py::open_vouchers`、`create_supplement_payment` | ✅ | `payroll/tests/test_bonus_correction_2026_09_30.py` |
| W-7 | M07 payroll → M08 analytics（讀取面） | IP-9 `expense.entries`（名稱 `bonus_correction`） | （只讀）補發＝補發日 +金額、追回＝核准日 −金額；原單 `bonus` 那筆不動 | 無寫入；狀態生效即讀得到 | `payroll/bonus_correction.py::expense_entries` | ✅ | 同上 |

新增或改動跨模組寫入時：同一個 commit 補註解＋更新本表。

