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

## 9. 寫入連動矩陣（營運報表 ⇄ 總帳；使用者 2026-09-30：「營運報表 vs 財務會計：寫入有沒有連動？有連動就必須互通」）

> 基底 origin/platform 138f3303，逐項讀碼（2026-09-30，W2 hichan-8c；五路讀碼各自附行號，行號會漂，以符號為準）。
> **結論（已驗證）**：兩邊「讀」各自讀來源、互不讀對方；**寫入沒有任何連動**——
> ① 來源寫入（收款、匯款、勞報單…）→ 營運報表**立即**變（報表每次請求即時讀提供者），→ 總帳**不會動**，要等會計到『分錄草稿』頁手動按「執行」；
> ② 總帳側寫入（手工傳票、作廢、結帳、結轉、科目）→ 營運報表**完全不讀**（`analytics` 對 `vouchers_all`／`voucher_lines`／`gl_*`／`ledger` 的引用＝0 筆）；
> ③ 沒有任何畫面比對兩邊（下一步：『與總帳差異』頁，本節 §9.4）。
> 標記：🟡＝讀碼推論、未實跑驗證；行號前有 ~ 者為近似位置。規則：**新的跨模組寫入連結要在寫入處加註解（下游效應：營運報表／總帳／出納）並在本節加一列**（R1，主持 2026-09-30）。

### 9.0 共通事實（每一列都適用，不再重複）

| # | 事實 | 證據 |
|---|---|---|
| F1 | 總帳引擎**只有一個入口**：`POST /api/ledger/engine/run`（要旗標 `engine_drafts`，會計手動按）；沒有排程、沒有任何來源寫入的 hook | `accounting/api/ledger_engine.py:69-83`；前端唯一呼叫 `frontend/js/ledger-hub.js:155`（`engRun()`）；`grep "engine.run"` 全專案僅此處；`modules/accounting` 無 scheduler／Timer |
| F2 | `changed_since` 是**死參數**：契約與 5 個提供者都有簽章，引擎呼叫 `collect(start, end, conn=conn)` 沒傳；`gl_cursors` 表只建表、無讀寫 ⇒ 沒有增量掃描，每次全掃區間 | `ledger/contract.py:8,227,248`；`ledger/engine.py:323`；`migrations/0001_ledger_base.py:94` |
| F3 | 雜湊（日期、各行角色／方向／金額／案件、對象、稅碼）不變 ⇒ 什麼都不做；變了：**草稿**⇒作廢重建（`superseded`）；**已過帳／簽核中**⇒舊傳票不動、標 `drift`、另產**反向草稿（日期＝今天）**＋新草稿；今天落在已結帳期間 ⇒ 不產反向、note 要手工沖轉 | `ledger/engine.py:265-300`；`:218-232` |
| F4 | 來源消失（取消、刪除、退回）⇒ `orphan`：草稿作廢、已過帳產反向草稿。**只判斷「事件原日期落在本次執行區間內」且「該來源本次回應 ok」者**；區間外不會被發現 | `engine.py:301-315`（:302 區間條件、:306 ok 條件） |
| F5 | 總帳的 UI 訊號只有 `ledger-hub`『分錄草稿』頁（11 種狀態標籤、`engBad` 紅標、執行後摘要）。**沒有**「上次執行時間」「N 個來源自上次以來已變動」「草稿已過期」常駐提示（後端 `GET /engine/runs` 存在、前端未用）。來源端頁面（案件管理、出納、勞報單、獎金、庫存、傳票）**沒有任何**「此筆已入總帳／將使引擎 drift」提示 | `ledger-hub.js:133-156`；`grep drift|總帳|過帳` 於 `case-management*.js`、`cashier.js`、`receivables.html`、傳票頁＝0 |
| F6 | 營運報表**每次請求即時讀提供者**（`receivables.income_items`、`case.recognition`、`expense.entries`、`stock_items`），無快取、不讀傳票 | `analytics/api/reports.py:3261`、`:3386-3490`；`grep "vouchers_all|voucher_lines|gl_|ledger|modules.accounting" analytics`＝0 |
| F7 | §2 表 E3／E4／E5 的總帳狀態「🔧 測試中」**已過期**：`("gl.events","case")` 已登記（E11／E11b／E12／E12b）；E08～E10 同（supply） | `modules/case/__init__.py:66`、`modules/supply/__init__.py:22` |

### 9.1 來源寫入 ⇒ 營運報表／總帳

欄位：**報表**＝營運報表（現金／權責）；**總帳**＝引擎（見 F1～F4，下表只寫「該動作造成什麼事件變化」，且一律「下次手動執行才發生」）；**訊號**＝使用者在寫入當下看到什麼；**GAP**＝編號見 §9.3。

#### R1／R2　案件收款品項（`quotations.data_json.caseRecord.payment.items`）

| 動作 | 位置（`modules/case/api/quotations.py`） | 報表 | 總帳 | 訊號 | GAP |
|---|---|---|---|---|---|
| 新增／刪除款項期別、改應收／比例 | `update_case_record` :2629（存 :2776；非 admin 鎖 :2565/:2713） | 立即。現金：只有已收款期別才有影響（`arap/receivables.py:183`）；權責不受影響（權責收入讀階段 `case/recognition.py:139`） | 已收款期別被刪／金額變 ⇒ E03 雜湊變（草稿重建／drift／orphan）；未收款期別無事件 | 無 | L3、L4 |
| 標記收款（已收＋收款日／實收／手續費） | `mark_payment` :3674（`_apply_payment_mark` ~:2980）；UI `cashier.js:578`、`case-management-core.js:605` | 立即：現金依收款日，收入＝實收＋手續費；手續費同日列支出（R2 `receivables.py:219`）；權責不變 | 下次手動執行才出 E03（借 BANK＋FEE／貸 AR，未開票貸 ADV_RCPT）；有發票號碼另有 E01 | 無（成功不提總帳；`alert` 只報錯） | L1 |
| 取消收款 | `_apply_payment_mark` else 分支（~:3000）、`cashier.js:603` | 立即消失（收入與手續費支出皆消失） | E03 來源消失 ⇒ orphan（僅限執行區間含原收款日，F4）；已過帳 ⇒ 反向草稿 | 僅 `confirm()`，不提總帳 | L2、L3 |
| 改收款日 | `update_case_record` :2720（`_validate_changed_receipts`；admin／出納無限制） | 立即換月 | 事件鍵不含日期、日期進雜湊 ⇒ drift／supersede；跨月需**兩次**執行（舊日期 orphan＋新日期新建） | 無 | L2、L3 |
| 改實收／手續費 | 同上；`mark_payment` :3682 | 立即（收入＝實收＋手續費；手續費支出同步） | E03 行金額變 ⇒ 重建或 drift；實收與發票含稅不一致只記 notice（`arap/gl_events.py:85-86`） | 無 | L3 |
| 登錄發票號碼／日期／未稅稅額 | `mark_payment` :3728-3738（**任何登入者**可改）；整包存 :2730-2744 | 現金收入不變；稅務匯出立即變 | 新增／變更 E01；**改發票號碼＝舊鍵 orphan＋新鍵新增**（不是 drift）；缺開立日以收款日認列＋notice | 無 | L3、L12 |
| 稅額沖銷申請／核准（`taxExempt`） | `request_payment_writeoff` :3999、`approve_payment_writeoff` :4060 | 立即：`actualAmount` 空時應收降為未稅（`receivables.py:181`） | E01 用 `apply_tax_exempt=False` 不變；E03 gross（`actualAmount` 空時）變 ⇒ 兩邊含稅金額分歧，只記 notice；**沖銷在總帳沒有對應事件** | 無 | L4 |
| 案件降級（已成案→其他）／結案 | `update_deal_tag` :2286（降級 :2325 admin+，結案 :2297 superadmin） | 降級：整案收入與手續費立即消失（只收已成案／已結案 `receivables.py:161`）；結案不變 | 降級：E03 隨之 orphan，**E01 不會**（`collect_tax_invoices` 無 deal_tag 篩選）⇒ 報表、E03、E01 三者不一致；結案前置檢查不看總帳狀態 | 無 | L8 |
| 已結案半解鎖：變更排隊 ⇒ superadmin 核准套用 | `_gate_case_edit` :283、`_apply_case_change_request` :2834 | 排隊期間不變；核准當下才變（同上各列） | 時間點＝核准當下 | 前端「已送出待審核」；簽核預覽不顯示「此期已過帳」 | L3 |
| 刪除報價單（僅草稿） | `delete_quotation` :2365 | 草稿不在收入範圍 | 無事件 | — | — |

#### E1／E2／E10　承攬商派工／匯款（`contractor_dispatches`、`contractor_payment_vouchers`；`modules/subcontract/api/`）

| 動作 | 位置 | 報表 | 總帳 | 訊號 | GAP |
|---|---|---|---|---|---|
| 新增派工 | `vendor_contractors.py:511-550` | **權責立即**（status≠cancelled，**含草稿派工**，`recognition.py:216-218`） | E04 僅在 accepted／completed 且有發票日（`subcontract/gl_events.py:35`） | 無 | L4 |
| 修改派工（金額／稅率／狀態） | `:553-605`（已有匯款申請 ⇒ 409 :575-580） | 權責立即 | E04 雜湊變（僅限尚無匯款申請者） | 409 訊息 | — |
| 刪除派工 | `:608-632`（有匯款申請 409） | 立即消失 | E04 orphan（僅限無匯款申請者） | confirm（一般） | — |
| 驗收 | `:1027-1070` | 權責不變 | **E04 才開始成立** | 無 | — |
| **改發票日**（有匯款申請／已付款／已過帳後**仍可改**） | `:994-1017`（註解 :997-1001 明說刻意不擋） | 權責立即換月、provisional 旗標消失 | E04 `event_date` 變 ⇒ 草稿重建／已過帳 drift＋反向＋新草稿；清空 ⇒ orphan | 僅 `flashSaved`（`case-management-dispatch.js:237-247`） | **L3** |
| 改承攬商主檔（名稱／統編） | `vendor_contractors.py:262-313` | 權責 desc 用即時名稱；現金用快照 | E04 的 party key＝統編或名稱 ⇒ 已過帳 E04 全部 drift（🟡 推論成立、未實跑）；E05 用快照不受影響 | 無 | L3 |
| 建匯款申請／刪草稿／送審／核准／退回 | `contractor_vouchers.py:265-656` | 無（報表現金只看 `is_paid`） | 無（E05 只看 `is_paid`） | — | — |
| **標記已匯款**（paid_at、remit_actual、remit_fee；實付≠應付 ⇒ review=pending） | `contractor_vouchers.py:881-953`；`remit.py:41-60` | **現金立即**：付款日、金額＝實付（`recognition.py:206`）；手續費另列（`remit.py:158-171`）；pending 照計並標「差額待審核」（`reports.py:3429`） | 下次執行出 E05（借 AP＋FEE／貸 BANK）；**pending 時整筆含手續費都不出**（`gl_events.py:75-77`）＋notice | 頁面通知「匯款差額待審核」`:979-981`；無總帳提示 | **L4**（核可前兩邊同月金額不一致） |
| **取消已匯款** | `:955-975` | 現金立即消失 | 來源消失 ⇒ orphan／反向草稿（限區間，F4）；反向日期＝今天，今天期間已結帳 ⇒ 要手工沖轉 | 僅 `MotrixUI.confirm`「確定取消」`case-management-dispatch.js:465`，**不提總帳** | **L2、L3** |
| 重新匯款（取消後改日期／金額） | 同上 | 現金移到新月份 | 舊事件日期不在新區間 ⇒ 只跑新月份時舊事件不 orphan | 無 | L2 |
| 差額核可／退回 | `remit.py:125-153`、`arap/api/cashier.py:183-200` | 核可：金額不變、撤掉標記；退回＝回未匯款、現金與手續費立即消失 | 核可 ⇒ 下次執行才出 E05（多付少付入 EXP_OTHER）；退回 ⇒ 本來沒有事件 | 出納頁；無總帳提示 | L4 |
| 個人點工關聯勞報單（R12／E10） | `contractor_vouchers.py:826-862`（已匯款 409） | 無 | E05 分錄拆分（AP／OTHER_PAYABLE） | 409 訊息＋稽核 | — |
| R12：匯款 pay ⇒ 勞報單 mark_paid；unpay ⇒ unmark_paid | `payroll/remit_link.py:41-66`；`contractor_vouchers.py:958-960,972-974` | 🟡 **現金口徑可能雙計**：匯款單實付（快照 grandTotal 含個人金額，`:366`）＋勞報單 gross 再算一次（`payslip_payouts.py:40-50`）；`analytics`、`recognition`、`payslip_payouts` 皆搜不到 `paid_via_remit` 排除 | 總帳已處理：E06b 對 `paid_via_remit` 不產生（`payroll/gl_events.py:70`）、E05 已關聯金額借 OTHER_PAYABLE | 無 | **L5** |

#### E7　勞報單（`payslips`；`modules/payroll/api/payslips.py`）

| 動作 | 位置 | 報表 | 總帳 | 訊號 | GAP |
|---|---|---|---|---|---|
| 建立／編輯／匯出／刪除／作廢 | :248、:339-389、:431-464、:412-420、:576-598 | 無（報表只看已付款 `payslip_payouts.py:55-56`） | 無（E06 只取已簽回／已付款 `payroll/gl_events.py:39`；已進 GL 的狀態都鎖死不可改，`:176`） | 409 訊息 | — |
| 上傳簽回檔（→已簽回） | :616-653 | 無 | 下次執行才產 E06（日期＝勞報日，缺則簽回日） | 無 | L1 |
| 刪除簽回檔（刪光 ⇒ 已匯出）／退回簽回 | :695-715、:724-735 | 無 | E06 消失 ⇒ orphan（限區間） | 無 | L2 |
| **出納標記已付款**（必填既有未作廢傳票號） | :749-779（傳票檢查 :762-773） | **立即**：付款日歸月、金額＝gross（`payslip_payouts.py:55-59`、`reports.py:3496-3503`） | 下次執行才產 E06b（付款日、net）；**E06b 不看所填傳票號** | 勞報單頁顯示付款日與傳票號（`payslips.html:198`）；無總帳提示 | **L6** |
| 出納退回已付款 unpay | :790-808（匯款單付款者被擋 :804-806） | 立即消失 | E06b 消失 ⇒ orphan；**手工付款傳票不處理**（傳票號被清、傳票仍在） | 409 訊息指向匯款單 | L2、L6 |

#### E8　獎金分潤（`modules/payroll/api/bonus.py`、`bonus_vouchers.py`）

| 動作 | 位置 | 報表 | 總帳 | 訊號 | GAP |
|---|---|---|---|---|---|
| 建立／編輯／送審／駁回 | :2061-2289、:2359-2365 | 無（只列已發放） | 無（尚無傳票） | 409：待審核且已有傳票不可改（:2120） | — |
| 簽核通過（最後一層 ⇒ 待發放） | :2301-2346 ⇒ `bonus_vouchers.py:94` | 無（待發放不列） | **同交易**開「核准應付」傳票**草稿**；引擎下次執行才登記 native E07a | 回傳 voucher＋notice；獎金頁「已產生的傳票」卡 | — |
| 退回（待發放前任何時點） | :2392-2411 ⇒ `bonus_vouchers.py:139-155` | 無 | 傳票仍草稿 ⇒ `voucher.void_draft` 作廢並解除連結；已送審 ⇒ 不動、只回提示；會計模組不在 ⇒ 保留連結並說明 | 有 notice | **L7**（傳票已送審／已過帳時獎金回草稿，傳票與 native 登記都留著） |
| 出納標記已發放 | :2423-2457 ⇒ `bonus_vouchers.py:116`；`bonus_payouts.py:29-36,86-92` | **立即**：發放日、案件合計金額（不扣代扣） | 同交易開「發放」傳票草稿；引擎下次執行才登記 native E07b（帶代扣資料給扣繳清單） | 傳票卡；無傳票時有 notice | — |
| 已發放後撤銷 | :2406（已發放 409） | 不可能 | — | 409 | **L7**（沒有更正流程，只能手工沖轉） |
| 會計作廢獎金傳票（總帳側） | `accounting/api/voucher_providers.py:72-78`；`engine.py:239-247` | 獎金狀態不變 ⇒ 報表仍算已發放 | 既有 native 列保持 `native`、指向已作廢傳票（🟡 讀碼推論：`sync_statuses` 只處理 drafted／drift／orphan `engine.py:113`，`_orphans` 只掃 drafted／posted `:302`） | 獎金頁傳票卡顯示作廢狀態（`bonus_vouchers.py:173-175`） | **L7** |

#### E3／E4／E5／E6　案件額外支出、叫料、進貨／存貨

| 動作 | 位置 | 報表 | 總帳 | 訊號 | GAP |
|---|---|---|---|---|---|
| 額外支出 新增／編輯（草稿、已駁回）／刪除（草稿、已駁回） | `case/api/case_extra_expenses.py:246-303`、:449-462（409） | 草稿不計 | 無（E11 只收已核准 `case/gl_events.py:28`） | 409 | — |
| **送審** | :471-522（無簽核層 ⇒ 直接已核准 :503） | **立即計入**（待審核／簽核中也計，標 `pending`，`recognition.py:269,295-301`） | 待審核不產生；已核准後下次執行才產 E11 | 報表暫用標示（`reports.html:1004`） | **L4**（報表比總帳早計入） |
| 核准 | :544-601 | 已核准：權責日＝發票日→核准日→憑證日（`recognition.py:295`） | 下次執行才出 E11（日期同報表） | 核准後無「尚未入總帳」提示 | L1 |
| 駁回 | :626-661（僅待審核／簽核中） | 立即移出 | 無 E11 可 orphan | 通知 | — |
| 改發票日／發票號／付款日 | :382-432（已有付款日改動限 admin :409-413；清付款日清 `remit_*`） | 權責：發票日立即歸月；現金：付款日（優先於憑證日） | E11（發票日）／E11b（付款日）：草稿重建／已過帳 drift；日期改到執行區間外 ⇒ 舊事件 orphan、新日期下一區間才建立 | 付款日覆寫寫專用稽核 `paid_date_override`（:443）；無總帳訊號 | L2、L3 |
| 出納登錄付款（`payables.pending` mark_paid） | `case/payables.py:77-105`（條件式 UPDATE :91-93） | 現金改用付款日、金額改用 `remit_actual`（`recognition.py:284-286`），不分差額是否已核可（`remitPending` 只打標） | E11b：差額待審核 ⇒ **不產生**＋notice（`gl_events.py:54-56`） | 出納頁差額欄（`cashier.html:325`） | **L4** |
| 差額核可／退回、手續費（E4） | `payables.py:157-215` | 核可：不變；退回：現金由付款日回憑證日暫用、手續費消失 | 核可 ⇒ 下次執行才出 E11b；退回 ⇒ E11b 若已存在則 orphan | 出納頁 | L4 |
| **變更申請核准**（已核准後改金額／日期／說明） | :889-1071；`_apply_change` :834-872（只要求 `status=='已核准'` :897，**不擋已付款**） | 立即；現金口徑在已付款時仍用 `remit_actual` | E11 雜湊變 ⇒ drift／重建；E11b 的 AP 借方用新 total、BANK 用舊 `remit_actual` ⇒ 含差額行，**但不重走差額審核** | `change_approve` 稽核＋通知；無總帳訊號 | **L11** |
| 已核准額外支出的作廢／取消核准 | （`case_extra_expenses.py` 路由清單無此動作；已核准只能經變更申請改） | — | — | — | L11 |
| 叫料 改清單（整份覆蓋）／改付款狀態 | `case/api/material_orders.py:58-144`（已結案 400 :106） | 權責：`totalPrice`、發票日→付款日；現金：`paidStatus≠pending` 的 `paidAmount`；只計已成案／已結案（`recognition.py:116`） | E12／E12b（鍵 `案件::itemId`；無 `itemId` 者用品名 ⇒ 改名＝orphan＋新建）；拿掉一筆＝orphan；**整份覆蓋對已過帳事件無保護** | 稽核 `material_orders.update`；無總帳訊號 | L3 |
| 叫料 單筆登錄發票日 | `material_orders.py:166-197`（**已結案後仍可**） | 權責立即換月 | E12 日期變 ⇒ drift | 待補登清單（`case-management.html:2354-2360`） | **L3** |
| 進貨 新增批次 | `supply/api/inventory.py:410-478` | 立即，依 `stock_items.created_at`，**不分口徑**（`reports.py:3447-3462`） | E08（入庫，資產）／E08b（有發票號，估稅×5%）；下次執行才出 | 稽核 `inventory.batch_create` | **L4**（報表採購日即費用；總帳此時只增存貨，費用到出貨 E10） |
| 進貨 改批次資料／**新填發票號** | `inventory.py:523-552`（付款後仍可） | 不影響 | 新填發票號 ⇒ 下次執行新增 E08b（稅為估計） | 稽核 | L3 |
| 進貨 標記已付款／取消 | `inventory.py:562-597` | **不影響營運報表** | E09；取消 ⇒ orphan；改付款日 ⇒ drift | 稽核；進貨付款不在出納頁（G6） | L4 |
| 庫存項目 **報廢（void）** | `inventory.py:610-642` | **立即移出**（`reports.py:3453`） | E08 仍含報廢件（`supply/gl_events.py:30-31` 無狀態過濾）⇒ **存貨不減**；`:79-81` 只 notice；報廢損失無自動分錄 | 稽核＋總帳 notice | **L10** |
| 退回庫存／刪除在庫項目 | `inventory.py:647-653`、:664-677 | 退回：不影響；刪除：立即移出 | 退回（已出貨者）：E10 來源消失 ⇒ orphan ⇒ 存貨鏈以原金額回沖；刪除：E08 批次合計變 ⇒ drift（🟡 存貨鏈 receipt 是否跟著調整未逐行驗） | 稽核 | L1 |
| 出貨單核准／撤銷核准；設備序號認領／釋放 | `supply/api/shipping_notes.py:403-594`；`inventory.py:715-733` | 不影響 | E10（mode=stock，移動加權平均）；庫存不足 ⇒ `blocked_inventory`；撤銷／釋放 ⇒ orphan ⇒ 回沖 | 單據通知；`ledger-hub` 顯示 blocked | L1 |

### 9.2 總帳側寫入 ⇒ 營運報表（反方向）

**全部「目前無」**（`grep "vouchers_all|voucher_lines|gl_|ledger|modules.accounting"` 於 `analytics`＝0 筆；報表唯一的 "voucher" 字樣是承攬商匯款單 `contractor_payment_vouchers`，`reports.py:2519-2536`）。

| 總帳側寫入 | 入口（`modules/accounting/api/`） | 對營運報表 | 備註 |
|---|---|---|---|
| 手工傳票 新增／改／送審／核准／退回／過帳 | `vouchers.py:165,920,578,648,732,885` | 無 | 已過帳傳票日期與分錄由 DB 觸發器鎖住 |
| 作廢（含草稿、已過帳） | `vouchers.py:806-884`（只查期間鎖與理由） | 無 | **引擎／獎金傳票作廢無任何「來源將 drift」警告**（傳票頁對 `kind`／`origin`／`gl_event_id` 無標示） |
| 沖轉／反向傳票 | 無手工端點；`reverses_no` 只由引擎寫（`engine.py:85-86,234`） | 無 | 訊息「請手工沖轉」只能靠作廢重開或手開相反傳票 |
| 期間結帳／重開／鎖／解鎖；期初建立／撤銷 | `ledger_periods.py:121,135,149,162,198,214` | 無 | 重開回 `stale_later_periods` |
| 年度結轉與關帳／重開 | `ledger_closing.py:63,76,89` | 無 | 結轉傳票不進損益表 |
| 科目新增／改；角色對應 `gl_account_roles`；報表行對應 `fs_line` | `account_items.py:222,307`；`ledger_reports.py:139,172`；`ledger_settings.py:46` | 無 | 只影響引擎下次產生與財報 |
| 來源補登 `gl_source_annotations` | 讀：`ledger/contract.py:130-136` | 無 | **查無寫入端**（`api/` 無端點、前端無介面；旗標 `source_annotations` 存在）🟡 待確認是否尚未做 |
| T100 匯出確認／取消 | `accounting_export.py:556,617` | 無 | 與引擎草稿各自收集事件，不互通 |
| 稅額結轉、扣繳繳庫／取消、功能旗標 | `ledger_tax.py:85,128,149`；`ledger_settings.py:108` | 無 | — |

### 9.3 缺口清單（GAP；證據見上表與 §9.0）

| 編號 | 缺口 | 影響 | 建議（待主持定案者標 ⚠） |
|---|---|---|---|
| L1 | **來源寫入後總帳沒有任何訊號**：引擎只能手動跑（F1）、無 hook、無「上次執行／N 個來源已變動／草稿已過期」（F5）、`changed_since` 與 `gl_cursors` 是死設計（F2） | 會計不知道何時該跑；報表已變而總帳不變，長期分歧 | ① 來源寫入處加註解＋寫入成功回應帶 `glNotice`（有事件才提示）；② 『分錄草稿』頁常駐「自上次執行後來源已變動 N 筆」（以 `changed_since` 真正落地或以輕量比對）；③ ⚠ 是否加排程自動執行（產生草稿而非過帳，風險低） |
| L2 | drift／orphan **只在執行區間含原事件日期時才偵測**（F4）；跨月改日期／重新匯款需兩次執行 | 區間外的已過帳事件永遠不被反向，帳與報表分歧而無人知 | 引擎每次額外掃「狀態 posted／drafted 且來源本次未回應」的事件（不限區間），或提供「全期重掃」按鈕＋顯示最後全掃時間 |
| L3 | **已過帳來源可被編輯而端點無警示**：取消收款、改收款日／金額、派工發票日（註解明說刻意不擋）、承攬商改名／統編、叫料整份覆蓋與已結案補發票日、進貨補發票號、取消匯款／取消付款 | 產生 drift／反向草稿，使用者編輯當下不知道 | 寫入端查該來源的事件狀態（經 `gl.events` 讀取提供者或引擎讀取 API），`posted`／簽核中時回警告（不擋，或要求確認），寫稽核；先做收款／匯款／派工發票日三處 |
| L4 | **報表與總帳的計入時點／口徑不同，且無對照**：差額待審核（報表現金已用實付、總帳不入帳）、額外支出送審中（報表計、總帳不計）、權責派工含草稿派工（報表計、E04 要驗收＋發票日）、進貨（報表採購日費用、總帳進貨為存貨資產、費用在 E10）、稅額沖銷、勞報單報表 gross／總帳 net | 同一月份兩邊數字不同卻沒有原因說明 | **『與總帳差異』頁**（§9.4；Part B），差異分桶＝未入帳草稿／drift 待處理／稅／口徑／手工傳票／尚未接總帳 |
| L5 | 🟡 **現金口徑報表可能雙計**「經匯款單付款的勞報單」：匯款單實付含個人淨額＋勞報單 gross 又算一次；總帳側已處理（E06b 不產生、E05 借 OTHER_PAYABLE） | 報表支出多計 | 先以測試確認（建匯款單關聯勞報單→兩口徑支出是否雙計）；確認後報表對 `paid_via_remit` 勞報單去重 |
| L6 | 勞報單付款「必填傳票號」與引擎 E06b **不互相檢查**：手工傳票已記付款時引擎會再記一次（程式註解自承「本批不自動偵測」`payroll/gl_events.py:7-9`） | 付款重複入帳 | E06b 見 `voucher_no` 已填且傳票有效 ⇒ 不產生並 notice（或標 native） |
| L7 | 獎金：傳票已送審／已過帳時獎金單退回，傳票與 native 登記都留著；會計作廢獎金傳票 ⇒ 獎金狀態不變、報表仍算發放、native 列殘留無警示；已發放後沒有撤銷／更正流程 | 報表、獎金、總帳三方各說各話 | ⚠ 定義已發放更正流程（反向傳票＋撤銷發放）；作廢獎金傳票時回寫獎金單狀態或在獎金頁明顯警示；引擎對 native 指向已作廢傳票的列標 `orphan` |
| L8 | 案件降級：E03 orphan、**E01 殘留**（`collect_tax_invoices` 無 deal_tag 篩選）⇒ 報表、E03、E01 三者不一致；結案前置檢查不看總帳狀態 | 已開票案件降級後帳與報表分歧 | E01 與報表／E03 同口徑篩選，或降級前警告；結案前置檢查加「有未處理 drift／草稿」提示 |
| L9 | **總帳側寫入對報表零影響，且沒有專用沖轉功能／作廢警告／補登介面**：手工傳票、作廢、結帳、結轉、科目變動都不在報表出現；作廢引擎／獎金傳票無警告；`gl_source_annotations` 無寫入端；`gl_category_map` 只有建表未使用 | 會計做了手工調整，報表看不到也無從對照 | 設計決定：報表不讀總帳（維持）→ 以「差異頁」呈現手工傳票桶（L4）；作廢警告、沖轉功能、補登介面另列工單 |
| L10 | 進貨報廢（void）：報表立即少、總帳 E08 仍含報廢件 ⇒ **存貨不減**，報廢損失無自動分錄 | 存貨帳面高估 | E08 排除 void 件＋報廢事件（借損失／貸存貨） |
| L11 | 額外支出：已核准**沒有作廢／取消核准路徑**；變更申請可改**已付款**的 `total_cost` 而不回審核，E11b 用新 total／舊 `remit_actual` 產生差額行 | 已付款金額被改而無差額審核 | 變更申請對已付款者要求重走差額審核，或禁止改金額 |
| L12 | 發票號碼登錄（`mark_payment`）**任何登入者**可改，改號碼＝已過帳 E01 orphan＋新 E01 | 已過帳銷項發票被任意更換 | 已過帳 E01 後改號碼要 admin＋警告 |

### 9.4 下一步

- **Part B（主持 2026-09-30）**：唯讀『與總帳差異』檢視，放新「經營分析」選單：逐月、逐類別 營運報表 vs 總帳已過帳金額、差額、原因分桶（未入帳草稿／drift 待處理／稅／口徑／手工傳票／尚未接總帳）。後端在 analytics，經新的 accounting 提供者取總帳側（不 import L2）。本節 L4 是它的需求來源。
- 每一個 🟡 ⇒ 補測試後改 ✅／🔴；新增跨模組寫入連結時同一個 commit 更新本節並在寫入處加註解（R1）。
