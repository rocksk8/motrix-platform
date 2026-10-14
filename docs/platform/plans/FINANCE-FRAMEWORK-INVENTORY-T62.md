# 財務框架化盤點與第一個切片（報價、案件、財務三大模組之「財務」）

> 日期：2026-10-14　作者：hichan-3e（受 hichan-b4 指派，使用者優先序：先框架化最常用的報價／案件管理／財務）　基底 `origin/train/t60-int` 6100c5613　僅讀程式碼，未執行。
> **查證程度**：本文的行號分三種——**(V)** 我親自讀過原始碼確認；**(S)** 由三個唯讀盤點子任務掃出、我只抽查，使用前請以現行程式為準。每節標明。
> 分類：**C**＝值得讓管理者可調　**L**＝法定／帳務固定（稅、捨入、傳票狀態機、連號：**不可設定**）　**S**＝安全固定（誰看得到金額、遮蔽、角色：**不可設定**）。

## 0. 結論

1. 財務這一側**幾乎沒有任何項目可由管理者在系統內調整**；已可調的只有：T100 科目對照與傳票別（`t100_export_config`）、簽核流程（`unified_approval_flow` 等）、營運目標（`operating_targets`）、報價條款預設與條款組（`default_payment_terms`、`quote_terms_presets`）、管銷%／公益基數、會計年度起始月、報表列標籤、科目角色對映、費用類別對映。設定中心（`settings_groups.py`）**沒有任何收款／款項／結算／財務報表群組**。(S)
2. **最值得先做的是『顯示與分組』類參數**（不碰金額、不碰權限、不碰帳務狀態）：應收帳齡區間、款項類別清單、銀行對帳單欄位別名、到期提醒天數。金額遮蔽、稅、捨入、傳票狀態機、單號連號一律不開放。
3. **同一份清單在多處各寫一份**，是框架化的最大風險：款項期別在 `case-management.html:1871` 與 `payment_requests.PAYMENT_STAGES`（`:99-105`）與 `payment-request-form.html:377` 三份且內容不同；「已成案／已結案」在 `gl_events.py:19`、`reports.py:2606`、`dashboard.py:67-68`、`recognition.py:122`、`bonus.py:548`、`settlement_api.py:77` 各寫一份。(V/S)
4. 本次交付的第一個切片：**應收帳齡區間切點**（見 §4），旗標預設關、關閉時報表與今天逐位元相同。

## 1. 可調／固定總表

### 1.1 收款、款項期別、條款、結算（報價單與案件側）
| 項目 | file:line | 現值 | 已可設定？ | 分類 |
|---|---|---|---|---|
| 案件款期名稱下拉（訂金款/交貨款/驗收款/進度款/完工款/收款後出貨/自訂義/其他） | frontend/pages/case-management.html:1871-1872 | 前端硬編；後端不驗證 type | 否 | **C**（與下一列不同清單） |
| 請款單款項類別 `PAYMENT_STAGES`（full/deposit/delivery/acceptance/final＝全額/訂金款/交貨款/驗收款/尾款） | backend/modules/arap/api/payment_requests.py:99-105（V）；:371、:467 用 `not in` 擋；前端 payment-request-form.html:377 另寫一份 | 後端 key 固定、label 與增刪可調 | 否 | **C**（key 進請款單 JSON，案件階段看板讀 `stageLabel`：case-stage-board.html:245） |
| 預設分期樣板 30%/…/40% | frontend/js/case-management-core.js:419-421, 466-474（S） | 前端 | 否 | **C** |
| 付款條件預設 / 條款預設五欄 | backend/modules/case/quote_terms.py:23-45（V）；`default_payment_terms`（routers/system.py:1899-1911） | 付款條件可覆寫；其餘四欄（交貨/驗收/保固/售後）常數 | 部分 | 付款條件已可；其餘 **C**（低） |
| 條款組 `quote_terms_presets`（讀＝全員、寫＝superadmin） | routers/system.py:2339-2450（S） | 空清單退回常數 | **是** | 已完成 |
| 送審原因基準（文字≠預設/條款組⇒需審核） | quote_terms.py:138-190；quotations.py:1548-1553 | 讀上列設定 | 連動 | **耦合點**：改預設會改變『需審核』判定 |
| 標記收款／實收／手續費驗證 | quotations.py:4064-4129（S） | 硬編 | 否 | **L**（金額型別與帳務）；標記權限 **S**（`has_cashier_access`） |
| 已入帳收款改動警示、換發票號碼權限 | quotations.py:4159-4173 | 警示不擋 | 否 | **L／S** |
| 銷帳（沖銷）兩段式：財務申請→superadmin 核准；核准只設 `taxExempt` | quotations.py:4463-4560（S） | 硬編 | 否 | 核准 **S**；「誰可申請」可考慮 C |
| 管銷%（預設 25）、公益%（1）、營業利益率警示（<12 紅） | helpers/profit_rules.py:32-34（S）；JS 孿生 frontend/static/profit-rules.js:10 | 管銷預設與基數已可設；公益比率、12% 否 | 部分 | 管銷/基數已完成；比率與 12% **C**（前後端孿生要同步） |
| 營業稅率 5%、進項估計 1.05、`round_half_up` | helpers/tax_calc.py:27,59；legal_params.py；settlement_actuals.py:50 | 法定版本化 | 稅率版本在 legal_params | **L** |
| 精算完結 gate（deal_tag∈{已成案,已結案}）、`settlement.status`、精算基準 | api/settlement_api.py:77-79（V）；settlement_actuals.py:29,46 | 硬編 | 否 | **L** |

### 1.2 出納、應收應付、報表、遮蔽（S，部分 V）
| 項目 | file:line | 現值 | 已可設定？ | 分類 |
|---|---|---|---|---|
| 銀行對帳 CSV 欄位別名（日期/金額/摘要） | modules/arap/api/cashier.py:771-774（V）；選取 :807-809 | 各銀行格式不同 | 否 | **C**（第二優先切片） |
| 即將到期天數（應付 7 天、預定日 3 天，兩者不一致） | frontend/js/cashier.js:199-203, 354-360；cashier.html:370 | 7／3 | 否 | **C** |
| 收款逾期判定 `expected < today` | cashier.py:476 | 無寬限 | 否 | **C**（低） |
| 已匯款明細匯出欄位／欄寬 | cashier.py:643-644 | 10 欄 | 否 | **C**（低） |
| 匯款差額審核狀態與決定者 | cashier.py:358,386,649 | 待審核/已核可；財務角色＋superadmin | 否 | **L／S** |
| 請款單/開票單狀態（草稿→待審核→簽核中→已核准） | payment_requests.py:478-786；invoice_vouchers.py:546-899 | 硬編 | 簽核層可設 | **L**（其他模組讀這些字串，見 §2） |
| 收款手續費分類 `RECEIPT_FEE_CATEGORY="收款手續費"` | modules/arap/receivables.py:216 | 字串 | 否 | **L**（入帳與費用分類以此字串歸類） |
| 稅碼對照 OUT-5/0/EX/LEGACY | modules/arap/gl_events.py:47 | 硬編 | 否 | **L** |
| **應收帳齡區間 30/60/90、標籤、Excel/PDF 上色** | modules/analytics/api/reports.py:2639, 2654, 1811, 1862-1863（V） | 硬編 | 否 | **C（本次切片）** |
| 帳齡基準日（報價日；解析失敗用今天） | reports.py:2630-2632 | 報價日 | 否 | **C**（可改為預計收款日；影響口徑，另案） |
| 結案未精算清單（無天數門檻） | reports.py:621-636 | 已結案且未完結精算 | 否 | **C**（加「超過 N 天才警示」） |
| 營運目標 | reports.py:2500 | `operating_targets` | **是** | 已完成 |
| 資金水位應付範圍（只含承攬商已核准未付） | reports.py:2686-2740 | 資料範圍限制 | 否 | **L** |
| 財務角色、三鍵、`has_finance_access`、`quote_money_visible`、遮蔽欄位集與遮蔽值 `None` | helpers/auth.py:155-157,312,325,333；financial_mask.py:14-52；audit.py:109 | 角色推導 | 否 | **S：絕不開放**（漏列欄位即洩漏） |

### 1.3 會計（T100、傳票、總帳）（S）
| 項目 | file:line | 已可設定？ | 分類 |
|---|---|---|---|
| T100 科目對照、傳票別預設、料件分類對科目 | modules/accounting/api/accounting_export.py:93-137；PUT :239（僅 superadmin） | **是**（`t100_export_config`） | 已完成 |
| T100 匯出欄位集與順序（11 欄）、檔名 | accounting_export.py:465-466, 529 | 否 | **C**（綁會計師匯入格式：只做欄名／排序對照，不開放增刪）；檔名低優先 |
| 傳票狀態機 `VOUCHER_STATUSES`、可編輯狀態、已過帳不可退回、單號流水 `YYYYMMDD-NNN`、退回版 `-Rn` | modules/accounting/voucher.py:25,36-105,312-345 | 否 | **L：不可設定**（連號與唯一索引） |
| 傳票類別 收/支/轉（商業會計法 §17）與名稱 | voucher.py:175, 201 | 否 | 三類 **L**；顯示名稱可 C |
| 簽名格（記帳格固定在最後） | voucher.py:474-478, 539-561 | 層數由簽核流程決定 | 記帳格 **L**；格名低優先 C |
| 摘要佔位符（範本已是功能，清單寫死） | voucher_template.py:37-70 | 範本已可 | 清單維持程式碼 |
| 科目 source 三態（statutory 由資料層保護）、現金根科目、科目角色預設、科目性質由首碼推導 | api/account_items.py:44-49；voucher.py:178；ledger/roles.py:36-48 | 角色→科目對映表可改 | 預設值 **L** |
| 稅碼、401 欄位代號、稅率 5%、`round_half_up`、期間 open/closed/locked、年度結轉、事件契約 | ledger/tax401.py:27-52；legal_params.py:34；ledger/periods.py:14-17；closing.py:61-67；contract.py:16-31 | 401 欄位對照表可改 | **L** |
| 自動入帳排程 3600 秒／首次延遲 300 秒 | ledger/auto_run.py:19-21 | 否 | **C**（低） |
| 附件來源白名單與排除來源 | voucher_attachments.py:54-74 | 否 | **S／L** |
| 通知文案 | accounting/notify.py:16-36 | 否 | 低 C |
| ⚠️ 疑點：`tax401.py:206` 用內建 `round()`（銀行家捨入），其他處用 `round_half_up` | tax401.py:206 | — | **可能是缺陷**（金額進位口徑不一致），未驗證，轉交會計線確認，**本次不動** |

## 2. 耦合點（改任何一項前先看這裡）
- **狀態字串**：請款/開票狀態（草稿/待審核/簽核中/已核准）被簽核佇列（`approval_queue.ACTIVE_STATUSES`）、應付查詢（reports.py:2686 起）、案件結案閘門（§5）、`settlement*.py::check_finalize` 讀取。→ 不可只改一處；BP-5 已把『資料庫值與顯示名稱分開』列為 P2 前置條件。
- **款項期別名稱**（訂金款、驗收款…）同時被：報價單付款條件預設、案件款項期別、帳齡報表 `type` 欄（reports.py:2647）、出納收款列（cashier.py:473）、案件階段看板使用，且是自由字串。→ 款項類別清單若做成可設定，必須是**單一來源**，三份前後端清單一起換。
- **`quotation_receipt`／`quotation_invoice` 對象鍵**：arap/gl_events.py（E01/E03 漂移沖轉）、db.py、analytics/reports.py、dashboard.py。
- **`taxExempt`／`writeOffStatus`**：helpers/tax_calc.py:149-151、稅務匯出 `_collect_tax_invoices()`、T100（現金基礎用 receivedAt）。
- **遮蔽角色**（財務三鍵）被讀於：quotations.py:372,6829；settlement_actuals.py:28,56；contractor_vouchers.py:84；case_extra_expenses.py:402；payment_requests.py:81；invoice_vouchers.py:105；dashboard.py:62；audit.py:109（通知金額略）；receipt_calendar.py:12（行事曆不含金額）。→ **任何新設定的『值』若是金額或金額衍生，必須在讀取端沿用 `quote_money_visible`／`financial_mask`；本次切片的值是天數，不是金額。**
- **利潤規則孿生**：profit_rules.py ⇄ frontend/static/profit-rules.js；改成設定時需由後端下發。
- **gl_events 提供者**（arap/case/payroll/subcontract/supply/custom_finance）經 `ledger/contract.py`：稅碼、角色名、事件代碼皆為契約。
- **預設條款→送審原因**：改 `default_payment_terms`／條款組會改變報價單『需審核』判定（quotations.py:1548-1553）。

## 3. 建議的切片順序（低風險 → 高）
| # | 切片 | 為何 | 風險 |
|---|---|---|---|
| **F1（本次已做）** | 應收帳齡區間切點（3 個天數，旗標 `finance_reports.custom_aging`） | 最明確、純顯示分組、不碰金額/權限；Excel/PDF 上色聯動 | 低 |
| F2 | 銀行對帳 CSV 欄位別名清單（出納；受治理清單） | 各銀行格式不同；純字串；僅出納可見 | 低 |
| F3 | 到期提醒天數（cashier.js 的 7 與 3，補齊不一致） | 純顯示 | 低 |
| F4 | 款項類別清單單一來源（後端定義 → 前端兩份讀同一 API） | 價值高但牽動三份清單與看板；需先決定 key 是否可增 | 中 |
| F5 | 結案未精算警示天數、報表欄位顯示 | 低優先 | 低 |
| — | 條款其餘四欄的預設文字 | 已有條款組，需求不急 | 低 |
**絕不開放**：金額遮蔽規則與欄位集、角色與三鍵、稅率／稅碼／捨入、傳票狀態機與連號、statutory 科目、期間鎖、簽名格中的記帳格、附件來源白名單、結案閘門中與金額相關的關卡（§5）。

## 4. 第一個切片 F1：應收帳齡區間（已實作）
- **設定群組** `finance_reports`（`helpers/settings_groups.py`）：`custom_aging`（0/1，預設 0）、`aging_day1/2/3`（預設 30/60/90，範圍 1～3650，必須遞增）。預設值＝今天寫死的值；`settings_deploy_baseline.json` 用文字插入加入。
- **單一實作** `helpers/finance_params.py`：`aging_cuts()`（旗標關／讀不到／不合法 ⇒ 30/60/90，不丟例外）、`aging_band(days, cuts)`、`aging_labels(cuts)`（預設逐字等於 `0–30 天／31–60 天／61–90 天／90+ 天`）。
- **接線** `modules/analytics/api/reports.py`：`_compute_ar_aging` 的分組與標籤、Excel 超期上色（原 `days > 90/60`）、PDF 超期上色，全部改讀同一組切點。**區間 key（`0-30`、`31-60`、`61-90`、`90+`）是位置代號，切點改了 key 不變**——前端 `reports.html:1839` 依 key 上色，不需改動；回應形狀不變（沒有新增鍵）。
- **權限與金額**：報表端點的 `_require_reports_access` 不動；切點是天數不是金額；設定中心本來僅最高管理者可改。
- **OFF 相同**：旗標關時 `aging_cuts()` 回預設；等價性測試對 −5～400 天逐天比對舊運算式與標籤字串。
- **測試**：`tests/test_finance_params_2026_10_14.py`：純函式 21 題已用 `--noconftest` 實際執行全綠（含等價性、邊界、不合法切點 12 種、讀設定失敗、原始碼掃描不再有寫死的 30/60/90、設定群組預設值）；需要資料庫的 3 題（API 標籤跟著切點、旗標關回應不變、無權限者被擋）寫好未跑。
- **未做／刻意不做**：帳齡基準日改為預計收款日（會改口徑）；切點改成可增減區間數（key 位置代號會失去意義）。

## 5. 案件結案閘門（1f 的 S-C1）：五個關卡逐一
來源：`modules/case/api/quotations.py` `_CLOSE_DOC_TABLES`（:2230）、`_close_gate_facts`（:2245-2307）、`_gates_from_facts`（:2318-2430）、`_case_close_gates`（:2310）、`_case_close_block_reasons`（:2438）。(V：以下我讀過程式碼)
| # | key／名稱 | 檢查什麼（file:line） | 『無需檢查』條件 | 訊息給誰看 |
|---|---|---|---|---|
| ① | progress／進度 | `case_stages` 全部 done（:2323-2340） | 沒有任何階段 | `value`「7/9」、`reason`「執行管理進度尚未 100%（7/9）」 |
| ② | payment／收款 | `caseRecord.payment.items` 每一期 `received`（:2343-2358） | 沒有任何款項期別 | 「款項明細尚有 N 期未收齊」；`value`「3/5 期」（只有期數，**沒有金額**） |
| ③ | documents／單據 | 報價單、承攬商匯款申請、開票申請、出貨單、請款單、**完工單**六張表中 `status IN ('待審核','簽核中')` 的筆數（:2360-2398；`_CLOSE_DOC_TABLES` :2230-2238）；讀 `$.approval` 帶出當層未簽的簽核人 | 六張表都沒有單據 | 逐表一句「出貨單尚有 2 筆簽核中」；`pendingUsernames`→`pendingApprovers`（顯示名稱） |
| ④ | settlement／精算 | `data_json.settlement.status == 'finalized'`（:2400-2417；2026-09-13 使用者裁示） | 完全沒有精算資料 | 「成本精算尚未完結」 |
| ⑤ | extraExpense／變更 | `case_extra_expenses` 非作廢者中有 `待審核`（:2419-2433）；表不存在視為無 | 無額外支出或表不存在 | 「額外支出尚有 N 筆送審中」 |
**消費者**：`update_deal_tag`（擋『已結案』並通知待簽人＋最高管理員，:2570-2600）、`/api/quotations/{no}/close-gates`（單案，`require_case` 的逐筆權限，:2519）、`gate-matrix`（已成案／已結案案件的矩陣，`row_access` 過濾，:1195-1250）、`case-bundle`（首屏）。**所有訊息只含件數／期數，沒有金額**，因此不涉及遮蔽。
**結案之後依賴它的**：`deal_tag='已結案'` 是獎金母體（payroll/bonus.py:545-564）、收入認列只認『已成案／已結案』（case/recognition.py:122）、精算完結需『已成案／已結案』（settlement_api.py:77）、arap 入帳 `_DEAL_OK`（gl_events.py:19）；結案後案件鎖定，只有 superadmin 能改進度（:2606-2610）。**⇒ 結案閘門保護的是『收入／成本在結案前已確定』。**
**提案（只收緊、放寬需第二位核准＋確認期間，沿用 D-K1）：**
| 關卡 | 可否關閉 | 理由 | 可做成的收緊設定 |
|---|---|---|---|
| ② 收款 | **永不可關** | 現金基礎認列與獎金依據；沒收齊就結案＝收入與獎金事後變動 | 『沒有款項期別也視為未達成』（na→blocked） |
| ③ 單據 | **永不可關** | 六張表都是金額單據；簽核中結案＝成本/收入事後改變 | 追加更多表（只增不減）；『已核准但尚未匯出』也列入 |
| ④ 精算 | **永不可關** | 結案鎖案，精算停在草稿＝永遠算不完的帳；影響獎金 | 『沒有精算資料也視為未達成』 |
| ⑤ 額外支出 | **永不可關** | 未定案成本；結案後才核准會改已結案案件成本 | 把『草稿』也計入 |
| ① 進度 | **可考慮做成選配（唯一候選）** | 不碰金額；有些案件沒有階段管理 | 現況＝必要；改成『選配』是**放寬**（第二位核准＋確認期間）；收緊＝『沒有階段也視為未達成』 |
實作位置：判定本體只有 `_gates_from_facts` 一處，設定讀取應在它之前一次取得（不要逐關讀）。**BP-5 P2 前置條件已寫明**：待簽語意的資料庫值（`待審核`／`簽核中`）不可改，閘門與簽核佇列在流程建構器上線前要改成讀語意。

### 5.1 基礎缺口（04 查出；**行為未改，列為需要使用者決定**）
`_close_gate_facts` 判定第 5 關只數 `case_extra_expenses.status='待審核'`（`pending`），但**多層簽核簽到一半的額外支出狀態是『簽核中』**（`case_extra_expenses.py:1059`：`status = "已核准" if done else "簽核中"`）。所以：①只有一層簽核、剛送出的額外支出會擋結案；②**簽到一半的（簽核中）和草稿都不會擋結案**。關卡文字寫的是「不可停在送審中」，與實際（只擋待審核）有落差。本次**沒有悄悄改基礎行為**：預設結果與過去逐項相同；只在『結案條件加嚴』的選項 `count_unfinished_extra_expenses`（原 `count_extra_expense_drafts`，已改名並加入『簽核中』）開啟時，才把草稿與簽核中也算進去。
**請使用者決定**：結案時，還有額外支出「簽核到一半」的案件，應不應該能結案？（建議：不應該——那是還沒定案的成本，結案後才核准會改已結案案件的成本；若同意，可把基礎行為改成把『簽核中』也算擋，屬於收緊，不需第二位核准，但會讓目前能結案的少數案件暫時不能結。）已駁回（`已駁回`）的額外支出可編輯後重送，目前也不擋，這次同樣未列入選項。

## 6. 需要使用者決定（只列影響範圍者）
1. 帳齡區間可自訂是否同意（本切片，預設關，不影響金額）。
2. 款項類別清單（F4）：key 是否可由管理者新增（建議：只能改 label／排序／停用，不新增 key，因為 key 進請款單 JSON）。
3. 結案閘門：①進度可否做成選配（放寬，需第二位核准）；其餘四關是否同意『永不可關、只可收緊』。
4. `tax401.py:206` 的捨入口徑疑點是否交會計線確認。

## 7. 第二批切片（F2／F3／S-C1，旗標預設關；本節為實作紀錄）
- **F3 出納即將到期天數**：設定群組 `finance_cashier`（`custom_due_soon`、`due_soon_payable_days` 7、`due_soon_planned_days` 3）。`frontend/js/cashier.js` 預設仍是 7／3；頁面載入時**多一次** `GET /api/settings-center/public?groups=finance_cashier`（登入即可讀、非敏感；失敗或旗標關就維持預設，不影響頁面）。這是出納頁唯一多出來的請求（OFF 時也會有，回應內容不影響畫面）。
- **F2 銀行對帳單欄位別名**：同一個群組（`custom_bank_aliases`、`bank_alias_date/amount/desc`，逗號分隔、順序即優先序，最多 20 個、每個 30 字）。`cashier.py::_parse_bank_csv` 改讀 `finance_params.bank_aliases()`；旗標關＝逐字等於原本三個常數（測試對照）；不合法的欄退回該欄預設；找不到金額欄**一樣 400，不猜**。
- **S-C1 結案條件加嚴**：設定群組 `case_close_gates`（`enabled` 主開關＋四個選項：`require_stages`、`require_payment_items`、`require_settlement`、`count_unfinished_extra_expenses`，草稿與簽核中都算），**只能讓更多案件不能結案**；沒有任何選項能關閉收款／單據／精算／額外支出任何一關（測試鎖住選項清單）。每個欄位 `loosen="down"`：關閉主開關或任一選項＝放寬，要第二位最高管理者核准並經確認期間。實作點：`quotations.py::_gates_from_facts(facts, d, opts=None)`（opts 缺省＝過去的路徑，逐項相同）、`_close_gate_facts(..., xe_drafts=False)`（草稿計數只在該選項開啟時才多一句 SQL）、`_close_gate_opts(conn)`。擋結案、`/close-gates`、`gate-matrix`、`case-bundle` 都走同一份判定。**讀不到設定 ⇒ 全部當作開啟（往嚴）**：嚴格讀取優先用 `helpers.settings_strict`，尚未合併時用 `routers.definitions._strict_setting`。
- **測試**：`test_finance_cashier_gates_2026_10_14.py` 純函式 17 題已用 `--noconftest` 執行全綠（含 OFF 逐項相同、**單調性**〔任何選項組合下被擋關卡只增不減〕、每個選項只翻自己那關且只從『無需檢查』翻、讀不到＝全開、草稿計數 SQL 只在開啟時出現）；需要資料庫的 3 題（端點跟著選項、擋結案訊息、放寬走待核准）寫好未跑。

### 7.1 審查後修正（04，r3）
- 帳齡：自訂切點生效（與預設不同）時，`/api/reports/ar-aging` 才多回一個 `cuts: [d1,d2,d3]`（預設時回應鍵與過去相同）；`reports.html` 的超期上色改讀 `arAging.cuts`，沒有就退回 `[30,60,90]`。
- 銀行對帳單別名：每個別名至少 2 個字（單字會在『包含比對』誤配到不相干的欄位），不合法整欄退回預設。
