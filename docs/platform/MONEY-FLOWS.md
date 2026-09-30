# 金流串接覆蓋表（MONEY-FLOWS）

> 使用者規則（2026-09-30，計畫檔「金流串接規則」）：**「只要有收入、支出項，都需要跟營運報表或是相關模組數據串接」**。
> 本檔盤點全系統的收入／支出來源，逐一標出：進不進 營運報表（現金／權責）、案件成本、出納、T100 傳票（未來總帳）。
> **缺口標 🔴**；「不是金流」標 ⚪（附理由）；已驗證＝✅；程式或文件查得到但尚未用測試驗證＝🟡（要驗證的地方寫在備註）。
> 產出時間 2026-09-30（基底 origin/train/0930 642b7574）；來源欄的檔案:符號是讀碼位置，不是行號（行號會漂）。

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

| # | 來源（表／事件） | 讀碼位置 | 營運報表 現金 | 營運報表 權責 | 案件成本／財務 | 出納 | T100 | 備註 |
|---|---|---|---|---|---|---|---|---|
| R1 | 案件收款品項 `quotations.data_json.caseRecord.payment.items`（已收款、收款日） | `arap/receivables.py::collect_income_items`；`case/recognition.py::accrual_income_items` | ✅ 收入＝銀行入帳＋客戶內扣手續費、依收款日、含稅 | ✅ 依階段完成月、未稅（切換） | ✅ 案件財務 Tab（淨收＝入帳） | ✅ 待收款／已收款 | ✅ 有填發票號碼者 | 未填發票號碼的收款不出 T100 傳票（設計：T100 只做銷項發票事件）。🟡 這類收款要不要另出「無發票收款」傳票＝待使用者／會計確認 |
| R2 | 客戶內扣收款手續費（同一品項的 `feeAmount`） | `arap/receivables.py::expense_entries`（IP-9 `receipt_fee`） | ✅ 列支出「收款手續費」，收款日 | ✅ 同（現金事件） | 🔴 案件毛利／精算（settlement）**尚未**把收款手續費列入案件成本；案件財務 Tab 只顯示「另列費用」 | ✅ 已收款明細另列 | ✅ 收款傳票借方拆「手續費」一行（`receiptFeeAccount`） | 缺口見 §4 G1 |

## 2. 支出

| # | 來源（表／事件） | 讀碼位置 | 營運報表 現金 | 營運報表 權責 | 案件成本 | 出納 | T100 | 備註 |
|---|---|---|---|---|---|---|---|---|
| E1 | 承攬商派工／匯款申請 `contractor_payment_vouchers`（`is_paid`、`remit_actual`） | `case/recognition.py::dispatch_entries`；`subcontract/api/contractor_vouchers.py` | ✅ 已匯款日、含稅、實付 | ✅ 發票日、未稅 | ✅ 派工金額（精算 dispatchTotal） | ✅ 待匯款／已匯款 | ✅ `contractor_voucher.paid_between` | — |
| E2 | 承攬商匯款手續費（`remit_fee`，公司自付） | `subcontract/remit.py::_expense_entries`（IP-9 `remit_fee_contractor`） | ✅ | ✅ | ✅ 精算頁 `remitFeeTotal` | ✅ | ✅ `remitFeeAccount` | 案件管理「財務彙總」（`loadFinanceSummary`）是否含手續費＝🟡 待驗（稽核 S1） |
| E3 | 案件額外支出 `case_extra_expenses`（`total_cost`、`paid_date`） | `case/recognition.py::extra_entries`；`case/payables.py` | ✅ 付款日 | ✅ 發票日→核准日→憑證日 | ✅ 精算 xeTotal | ✅ `payables.pending` | 🔴 T100 沒有額外支出付款事件 | 缺口 G2 |
| E4 | 額外支出匯款手續費（`remit_fee`） | `case/payables.py::_expense_entries`（IP-9 `remit_fee_case`） | ✅ | ✅ | ✅ | ✅ | 🔴 同 E3 | 缺口 G2 |
| E5 | 叫料（材料訂單） | `case/recognition.py::material_entries` | ✅ 付款日 | ✅ 發票日 | 🟡 精算的「材料」是否含叫料＝待驗 | 🟡 叫料付款是否走出納＝待驗 | 🔴 無 | 缺口 G3 |
| E6 | 進貨批次／料件成本 `stock_batches`、`stock_items.cost` | `analytics/api/reports.py::_collect_expenses`（stock_items 段）；`accounting/api/accounting_export.py::_collect_paid_stock_batches` | 🟡 依批次日歸月，**不分口徑**（兩口徑同一數字） | 🟡 同左 | ✅ `stock_items.quote_no` | 🟡 進貨付款 `paid-toggle` 在庫存頁，不在出納頁 | ✅ 已付款批次 | 口徑差異記在 §4 G4 |
| E7 | 勞報單 `payslips`（已付款、`gross_amount`） | `payroll/payslip_payouts.py::_expense_entries`（IP-9 `payslip`） | ✅ 付款日、應付總額 | ✅ 同（付款日；不分口徑） | ⚪ 勞報單不掛案件（若有掛案件才會進案件成本＝🟡 待驗） | ✅ `payslip.payables` | 🔴 T100 無勞報單付款事件 | 缺口 G2 |
| E8 | 獎金分潤發放 | `payroll/bonus_payouts.py::_expense_entries`（IP-9 `bonus`） | ✅ 發放日、案件合計 | ✅ 同 | 🟡 獎金是否列入案件毛利＝待驗 | ✅ `bonus.payouts` | 🔴 T100 無獎金發放事件（`bonus_vouchers.py` 有獎金傳票：權責／發放，可作為總帳來源＝🟡 待接） | 缺口 G2 |
| E9 | 自訂模組的金額欄（`number`／`formula` 欄位） | `helpers/custom_modules.py`（欄位型別 `number`、`formula`） | 🔴 沒有「這個欄位是金額、是收入還是支出」的宣告，所以**不可能**進報表 | 🔴 | 🔴 | 🔴 | 🔴 | 缺口 G5：需要欄位型別 `money`（含方向、日期欄）＋提供者 |

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
