# A2 最終切片計畫：新增請款（案件額外支出）依類型分支

> 2026-10-01 W1（負責人）。承 `proposal-expense-forms.md` 第二版；使用者已裁示走 A2（不碰 arap 請款單）＋下列決策。
> 文件階段：**在 node-bb 說「unfrozen」且第 28 班上線後**，於 post-28 的 platform 上開分支動工；本文不含任何程式變更。

## 0. 使用者已定的決策（plan-night）→ 對設計的影響

| 決策 | 影響 |
|---|---|
| 四類型簽核＝部門主管 → 最高管理者（超級管理員可在定義裡改） | 每類型預設兩層；流程代碼 `extra_expense:<kind>`（選用），未設＝沿用 `extra_expense` |
| 費用類別獨立清單、以 `gl_category_map` 對應會計科目（需要編輯畫面） | **類別清單＝`gl_category_map` 的 `source='expense'` 列**；一個編輯畫面（W4）同時編類別與科目對應；表單的科目下拉由唯讀 API 供應（`optionsFrom`），不在定義裡另存一份 |
| 綁案件的支出算案件成本、並取代重複的額外支出 | 綁案件的新單據**就是**額外支出列（同表、`quote_no` 有值）⇒ 既有案件成本／結算機制直接算；不會重複 |
| 發票號碼重複＝警告不擋（「收據」免檢） | API 回 `warnings`；不擋送審 |
| 申請人欄位預設鎖定本人，超級管理員可改成可編輯 | 新欄位屬性（A2 定義自有驗證，不動建構器）：必填＋預填＋鎖定；可編輯開關在定義 |
| 收款人＝員工、銀行資料取自「使用者主檔」 | ⚠ **盤點：`users` 表目前沒有任何銀行欄位**（db.py 僅見 totp／部門等欄）；需新增欄位＋維護畫面＋個資分級（見 A2-5b，W3 先驗證；確為沒有才做） |
| 稅：有稅額欄位就拆進項稅額，沒有則整筆含稅 | 定義欄位可標記「稅額欄位」；總帳 E11 有稅額欄位才拆（W4）；預設四類型不含稅額欄位 ⇒ 全額列費用（與 A6 未決一致） |
| 採購單：出納撥款，**匯款日與付款條件由出納填**（不是申請人） | 欄位屬性 `editableBy:"cashier"`（核准後、僅出納／管理員可寫；申請人唯讀）；匯款日＝既有 `paid_date`（IP-100 `mark_paid`），付款條件＝定義欄位 |
| 零用金：只是付款單，付款方式決定貸方、不做餘額管理 | 付款方式欄位 → 總帳貸方 `PETTY`（零用金）或 `BANK` |
| 國外差旅：先只記台幣 | 幣別備註欄、不做匯率 |
| 單號前綴 PR／PO／TE／PC | ⚠ **`PR` 與 arap 請款單 `PR-YYYYMM-NNN` 相同前綴**。緩解：新單號格式 `PR-YYYYMMDD-NNNN`（8 位日期、4 位流水）與舊格式（6 位年月、3 位流水）可區分；審計搜尋、`ref_no` 比對要確認不混（W3 查）。若查出會混，建議請購改 `RQ`（我的範本草稿已用 RQ） |
| 金額可見＝簽核人＋申請人＋財務／出納 | 沿用資料分級；其他人隱藏金額欄（`financial_mask` 沿用） |

## 1. 切片與負責人

> 估算＝工作日（含測試、e2e、截圖、守門）。全程約 **15～18 人日**（A2-5b 若成立再 +1.5）。全量班（L1）。
> 「DoD」＝完成定義；每片都要：§3 的「靜默遺失」檢查清單逐項過、R2（e2e 點每個按鈕、驗 DOM＋DB、截圖）、`pre_train_check` 或局部守門、三項提交。

### A2-1　W2　資料表（migration 0003）＋單號＋模型（約 0.5～0.75 d，L2）
- `modules/case/migrations/0003_expense_types.py`（登記在 `modules/case/__init__.py` migrations）加欄位，**預設＝今天的行為**：
  `kind TEXT NOT NULL DEFAULT ''`、`req_no TEXT NOT NULL DEFAULT ''`（每類型單號：PR-20261001-0001…）、`data_json TEXT NOT NULL DEFAULT '{}'`、`lines_json TEXT NOT NULL DEFAULT '[]'`、`def_version INTEGER NOT NULL DEFAULT 0`、`department_id INTEGER`（成本中心）、收款人欄 `payee_user TEXT DEFAULT ''`、`payee_bank_json TEXT DEFAULT '{}'`（送審時凍結的收款資訊快照）。
- `quote_no` 維持 `NOT NULL`，無案件存 `''`；不重建表。新索引 `(kind)`、`(req_no)`（唯一，僅 `req_no<>''`）。
- 單號：沿用 `next_entity_code` 類機制，各類型獨立流水；只有 `kind<>''` 才配號。
- `ExtraExpenseIn`（pydantic）新增 `kind`、`data`、`lines`、`departmentId`、`payee…`；`kind=''` 時欄位忽略、行為與今天相同。
- DoD：既有約 60 個額外支出測試一個都不用改就綠；migration 測試（舊列預設值、重跑冪等、`test_module_migrations`）。

### A2-2　W1　類型定義＋驗證＋預設四類型（約 2.5～3 d，**L0／L1**）
- 新 `ui_definitions` 種類 `expense_type`（`core/definitions.py` `KINDS` 加一種——L0 契約，照 PLAYBOOK §C-7 升版與快照）；key＝類型代碼（`purchase_req`／`purchase_order`／`travel`／`petty_cash`／`general`）。
- 定義內容：欄位（文字／數字／日期／下拉／單選／日期區間／公式／ref 部門或使用者）、明細表欄、`optionsFrom`（`expense_categories`＝W4 供應的費用類別 API）、必填、預設、`locked`（預填鎖定）、`editableBy:"cashier"`、`payable`（是否進出納；請購單＝否）、流程代碼、稅額欄位標記。
- 驗證與轉型**重用**建構器／`custom_fields` 那一份（`validate_module` 的欄位／明細表／ref、`_coerce／clean`）；另加 `validate_values(def, data, lines)`（送審與儲存時用，W2 的 API 呼叫它）：必填、型別、公式重算（金額一律後端算）、`locked` 欄位以後端預填為準。
- 四個預設定義（取自 `D:\開發測試檔\w1-exp` 的範本草稿：請購／差旅／零用金＋採購）；定義編輯頁 v1（超級管理員；驗證＋預覽；送審規則照 `expense_type` 走未審核直接發布＋稽核，比照其他非自訂模組種類——請使用者確認是否需要第二人審核）。
- DoD：定義 CRUD／版本／還原；`validate_values` 反向題（缺必填、型別錯、`locked` 被改、公式被竄改）；`test_l1_interface_snapshot`、`UNIT-INDEX`。

### A2-3　W2　API：建立／更新／送審／核准／退回吃 kind＋data＋lines（約 2～2.5 d，L2）
- 建立／更新：依 `kind` 取定義（新單＝最新發布版，存 `def_version`）、呼叫 A2-2 的 `validate_values`、`total_cost`＝明細金額合計（`kind<>''`）；`category`＝類型（或主要科目）；逐列科目留在 `lines_json`。
- 簽核：部門主管 → 最高管理者（來源 `department_manager` 由**申請人／費用歸屬單位**解出）；簽核人守門＝簽核鏈成員（不看案件也能簽；見 A2-5）。
- 採購單：`editableBy:"cashier"` 的欄位只允許出納／管理員寫（核准後）；寫入留稽核。
- **修訂（change-request）三處同步＋新欄位**（§3 清單）；**已撥款禁止修訂**（409「已撥款不可修訂」）。
- 發票號碼重複檢查（同 `kind` 內、排除「收據」）⇒ 回 `warnings`，不擋。
- 退回必填原因（沿用 `require_reject_reason`，額外支出目前是自由文字）。
- DoD：四類型建立→送審→核准→退回→修訂→（出納撥款）端到端 API 題；`kind=''` 路徑位元組不變（回歸）。

### A2-4　W1　前端「新增請款」依定義動態表單（約 3～4 d，L1 前端共用／L2）
- `pages/payment-request.html`：先選**類型**（類型由定義清單 API 供應），再依定義渲染欄位、明細表（新增／刪除列、公式即時算、必填標示）、科目下拉（`optionsFrom`）、申請人（鎖定顯示）、費用歸屬單位、收款人（員工＋使用者主檔銀行資料唯讀顯示）、上傳檔案（既有附件：發票類可核准後補）。
- 是否綁案件：選填「案件」（有→算案件成本；無→成本中心＝部門）。
- 案件頁「額外支出」分頁維持舊行為（`kind=''`）不動；新類型的單據在案件頁額外支出列表以類型標籤呈現（唯讀連結到請款頁）——範圍請 W3 互審確認。
- DoD：四類型 e2e（R2）；golden／頁面結構守門（`test_e2e_case_page_golden` 等）；`test_alpine_double_init`、字級、主題守門。

### A2-5　W2＋W3　無案件守門＋出納＋收款人＋報表部門維度（約 2～2.5 d）
- **W2**：`_guard_case`、approve／reject、附件路徑（`modules/case/attachments.py` `_READ_RULE`）、`detail_extra_expense`、待簽佇列（`linkedQuoteNo` 空時不可對所有人 DENY）、`payables.pending`（採購單：出納填匯款日與付款條件；`payable=false` 不列）、`mark_paid` 寫 `payee_bank_json` 快照沿用。
- **W3**：`modules/analytics/api/reports.py` `_quote_in_department` 對無案件列改看 `department_id`（舊單據沒有部門 ⇒ 維持原算法）；`recognition.extra_entries` 回傳加 `kind`、逐列科目（一列單據展開成多筆 entries）、`departmentId`；營運報表支出結構以科目呈現。
- DoD：無案件單據全流程（簽核→出納→報表→不進結案／結算）；配「沒有一般權限的人」正反兩向題（PLAYBOOK §G5 #14）。

### A2-5b　W3 先驗證 → 確有缺才做（約 1.5 d，L1）　使用者主檔銀行資料
- W3 確認 `users` 是否真的沒有銀行欄位（我 grep `db.py` 只見 totp／部門／通知等）。若沒有：新增 `users.bank_name／bank_branch／bank_account_name／bank_account_no`（additive）、使用者管理頁維護欄位、**個資分級**（帳號為敏感資料：只有本人／HR 管理員／出納看得到完整，其他人遮罩）、稽核、匯出排除。
- DoD：欄位遮罩／權限正反向題；單據送審時把收款資訊**快照**進 `payee_bank_json`（之後使用者改帳號不影響已送審單據）。

### A2-6　W4　總帳：費用類別清單＋科目對應＋依科目入帳（約 2～2.5 d，L2＋L1 小勾點）
- **費用類別編輯畫面**（總帳設定頁）：`gl_category_map (source='expense', category, role, account_code, nondeductible)`；這份清單同時是表單「科目」下拉的來源（唯讀 API `GET /api/expense-categories` 供 W1 的 `optionsFrom`）；新增類別不需改程式。
- E11：`kind<>''` 時逐明細列借對應科目（查 `gl_category_map`；沒對應 ⇒ `EXP_OTHER`＋警示），貸 `AP` 合計；無案件借 `EXP_OTHER`、帶部門維度；零用金付款方式 ⇒ E11b 貸 `PETTY`；有標記稅額欄位才拆進項稅額，否則整筆含稅。
- 新來源旗標（預設關；超級管理員在總帳設定開）；`kind=''` 的 E11／E11b 位元組不變。
- DoD：逐列入帳、無案件、零用金貸方、稅額拆／不拆、對應缺漏警示；`test_money_flows_registered`、`MONEY-FLOWS` 更新。

### A2-7　W1（＋W3 互審）　PDF／信件／通知（約 1.5～2 d，L1）
- 每類型輸出版型（`doc_template`，含未核可每頁紅色標示）＋ PDF 端點（額外支出目前沒有單據 PDF）；信件類型：送審／下一層／核准／退回／待撥款／已撥款（`helpers/mail_types.py`、`email_notify.py`、`notification_prefs.py`；接線檢查清單照前一輪：收件設定頁、個人偏好、站內鈴鐺連結、待簽佇列 -R 單號）。
- DoD：六種信件 e2e（記錄寄信呼叫）＋鈴鐺連結；PDF 逐頁標示（已核准無標示）。

### 順序與班次
- **第 29 班**：A2-1、A2-2、A2-3、A2-4、A2-5（＋A2-5b 若成立）＝可用的第一版：四類型開單→簽核→**出納撥款**→營運報表；總帳新來源旗標關。
- **第 30 班**：A2-6、A2-7＋全面 R2／互審。
- 依賴：A2-2（定義與 `validate_values`）是 A2-3／A2-4 的前置；A2-1 是全部的前置。建議第一週先做 A2-1＋A2-2（W2、W1 並行），其餘在其上並行。

## 2. 介面約定（避免各視窗對不起來）
- 類型定義 API（W1）：`GET /api/expense-types`（啟用的類型清單：code、name、payable）、`GET /api/expense-types/{code}`（最新發布版定義，含 `defVersion`）。
- 費用類別 API（W4）：`GET /api/expense-categories` ⇒ `[{category, accountCode, role}]`。
- 額外支出 API（W2）：沿用 `/api/quotations/{quote_no}/extra-expenses…`（有案件）；無案件新增 `/api/expenses`（list／create／update／submit／approve／reject／change-request，與有案件版共用同一批函式，`quote_no=''`）。**路徑與權限請 W2 在 A2-1 定案後回報**。
- 明細列形狀（`lines_json`）：`[{category, item, qty, unitCost, amount, invoiceNo, …定義欄位}]`；`amount` 一律後端重算；`category`＝費用類別名稱。

## 3. 靜默遺失檢查清單（新欄位漏一處＝資料無聲消失；逐項勾）

> 背景：額外支出「已核准後的編輯」走 change-request，提議內容由 `_proposal_from` 組、核准時 `_apply_change` 覆寫回本體、詳情由 `detail_extra_expense` 呈現；三處欄位清單**各自硬編碼**，新欄位漏任何一處 ⇒ 修訂後無聲丟掉或顯示不出。下列每一處都要處理並有題。

| # | 位置 | 要做 | 怎麼驗 |
|---|---|---|---|
| 1 | `ExtraExpenseIn`（`case_extra_expenses.py:75`） | 加 `kind`／`data`／`lines`／`departmentId`／`payee…` | 模型欄位與下列各處清單比對（見 #10 守門） |
| 2 | `create_extra_expense`（INSERT，~266）、`update_extra_expense`（UPDATE，~304） | 欄位寫入／更新；`kind<>''` 時 `total_cost` 由明細算 | API 題：建立→讀回每個新欄位相等 |
| 3 | `_row_to_dict`（:92） | 輸出新欄位（`kind`、`reqNo`、`data`、`lines`、`departmentId`、`payee…`、`defVersion`） | 讀回題；舊列（預設值）輸出不變 |
| 4 | **`_proposal_from`（:809）** | 提議內容加入所有「核准後允許修訂」的新欄位（`data`、`lines`、`departmentId`、`payee…`）；`totalCost` 由明細算 | 題：已核准單據改每一個新欄位 → 提議裡都有 |
| 5 | **`_apply_change`（:844）** | (a) 覆寫 UPDATE 加新欄位；(b) **`total` 目前硬算 `qty × unitCost`——`kind<>''` 必須改為明細合計**；(c) `changeHistory` 的 from／to 加新欄位；(d) 已付款後改金額的 `remit_review='pending'` 判斷用新 total | 題：修訂 → 核准 → 本體新欄位＝提議值、`changeHistory` 有前後值、已付款改金額進差額審核 |
| 6 | **`detail_extra_expense`（`quotations.py:5841`）** | 詳情 `fields` 加類型欄位／明細表摘要／費用歸屬單位／收款人；`changes.before／after` 加新欄位。⚠ **既有瑕疵**：`changes.after` 讀 `chg.get("unit_cost")`／`"total_cost"`（底線），而 `_proposal_from` 存的是 `unitCost`／`totalCost`（駝峰）⇒ 單價與小計的「變更後」現在就是空的，順手修 | 題：送修訂 → 待簽詳情的 before／after 每個欄位都有值 |
| 7 | 待簽佇列項目（`quotations.py` ~4585–4700，含 `extra_expense_change` 類型） | `kind`、類型名稱、`displayNo`（req_no）、`linkedQuoteNo` 可空 | 佇列題（含無案件） |
| 8 | 讀取端：`modules/case/payables.py`（pending／paid／mark_paid）、`recognition.py` `extra_entries`、`gl_events.py`（E11／E11b）、`modules/accounting/api/vouchers.py`／`voucher_summary.py`、`archive.py`（匯出 ~2245）、`pdf_gen.py` ~2314（結案報表）、`quotations.py` 2048／2233／4436（結案閘門、結算、案件財務） | 逐一確認：`kind=''` 路徑不變；`kind<>''` 有對應輸出或明確略過（寫註解＋題） | 各自既有測試＋新增「有 kind 的列」題 |
| 9 | 附件（`modules/case/attachments.py` 路徑存取、`_READ_RULE`；`case_extra_expenses.py` 附件端點） | 無案件的路徑規則（資料夾 `{quote_no}_{id}` → 無案件時的資料夾命名）；核准後發票可補的規則沿用 | 上傳／下載／核准後補發票題（含無案件） |
| 10 | **守門（新增）**：`test_extra_expense_columns_are_carried`（AST／schema 比對） | 讀 `case_extra_expenses` 欄位清單，每個欄位都必須被分類為：「提議帶入」（必須出現在 `_proposal_from` 與 `_apply_change`）或「不可修訂」（列在明確清單並寫理由）；新增欄位沒分類 ⇒ 紅 | 反向控制：新增一個假欄位而不處理 ⇒ 紅 |
| 11 | 定義版本 | `def_version` 於送審凍結；修訂用**原凍結版**還是**最新版**？建議：修訂沿用原 `def_version`（不因定義改版而改變已核准單據的欄位集） | 題：定義發新版後修訂舊單據 ⇒ 欄位集不變 |
| 12 | 總帳／報表的「列」粒度 | 一張單據多列科目 ⇒ `extra_entries`／E11 逐列展開；修訂前後的沖回／重記不重複 | W4／W3 題：修訂（改某一列科目）⇒ 報表／總帳以新值為準且只計一次 |

需要釘住的既有測試（變更時至少跑，摘自盤點）：`test_case_extra_expenses_api_2026_09_11`、`test_xe_change_request_2026_09_11`、`test_extra_expenses_migration_2026_09_11`、`test_e2e_extra_expenses_ui_2026_09_11`、`test_extra_expense_uploads_2026_09_11`、`test_extra_expense_reject_permission_2026_09_24`、`test_extra_expense_tier_record_2026_09_25`、`modules/case/tests/test_payreq_2026_09_27`、`test_e2e_payreq_2026_09_27`、`test_e2e_remit_fee_2026_09_30`、`test_money_guards_l11_l12_2026_09_30`、`modules/arap/tests/test_cashier_pending_payables_2026_09_27`／`test_cashier_remit_fee_2026_09_30`／`test_expense_payout_calendar_2026_09_30`、`modules/accounting/tests/test_ledger_c4b_case_2026_09_30`／`test_ledger_annotations_2026_09_30`、`modules/analytics/tests/test_reports_expenses`／`test_report_recognition_basis_2026_09_24`、`tests/platform/test_case_module_spec`／`test_module_migrations`／`test_approval_queue_l1`／`test_attachments_providers`／`test_accounting_foreign_reads`。

## 4. 風險與守則
- **正式機在用的額外支出**：所有改動＝新欄位＋預設值＝舊行為；`kind=''` 的回應與行為逐位元組不變（有「舊列快照」回歸題）。
- **不碰清單**（arap）：`payment_requests` 表與其 `quote_no NOT NULL`、`pdf_gen._build_payment_request_html`／`_require_payment_bank`（428 閘門）、`quotations.py` `_CLOSE_DOC_TABLES`、待簽類型 `payment_request`、行事曆推送、AR 帳齡與現金部位。
- 未驗證：非擁有者簽核人能否核准額外支出（`row_access.visible(…, scope="owner")`，`case_extra_expenses.py` ~556）——A2-5 先寫測試確認再定守門。
- 總帳稅額未決＝整筆含稅列費用（已有提示）；新來源旗標關著不影響現有帳。
- 本計畫所有估算都是「視窗熟悉該區」的假設；A2-4（動態表單）與 A2-2（L0 種類）是最大不確定項。

## 5. 需要各視窗確認後回報（我不會在此之前動手）
1. W2：無案件的 API 路徑與 `quote_no=''` 的各處影響清單（含 `row_access`、`_guard_case`）；`PR-` 前綴在審計搜尋／`ref_no` 是否與請款單混。
2. W3：`users` 銀行欄位的實況；報表部門維度的介面（`departmentId` 在 entries 的位置）。
3. W4：`gl_category_map` 編輯畫面與 `GET /api/expense-categories` 的形狀；E11 逐列借方的 `gl_events` 介面。
4. node-bb：`expense_type` 是否需要第二人審核（我預設：不需要，稽核留痕）；第 29 班切割是否接受。

## 6. A2-0　底層預留切片（使用者：「都要動到底層了，思考先行預留，避免每次都要碰觸底層」）

> **規則**：L0／L1 只在第 29 班這一個「預留切片」碰一次（全量班）；之後 A2-x／總帳 G-x／建構器／去識別化／檔案中心 P3 **只動模組**（局部班）。
> 預留＝**資料驅動的擴充點**（登記表／提供者／約定發現），不是寫死的分支。只預留 A2＋總帳＋建構器＋deid＋filehub 已具體需要的。
> 彙整自：W1（本人）＋ W2 `w2-expense-slices-design.md` §7 ＋ W4 `GL-BASE-HOOKS.md`（A1～A7、D）。

| # | 觸點（現況：哪裡寫死） | 層 | 預留的鉤子（資料驅動） | 之後誰插入（不再碰底層） | 來源 |
|---|---|---|---|---|---|
| 1 | **簽核單據類型**：`helpers/tiered_approval.py` `APPROVAL_DOC_TYPES`／`DEFAULT_UNIFIED_DOC_TYPES`／`APPROVAL_DOC_TYPE_LABELS`（:58-72）、`routers/approval_queue.py` `_ITEM_TYPE_LABELS`（:201）、`approval-queue.html` `docTypeLabel()`（三處標籤要一致）、`approval-settings.html:461-494`、`helpers/audit.py` `_MODULE_LABELS`／`_DOC_TARGET_TYPES` | L1 | 能力 `approval.doc_types`：模組登記 `{code, label, unified, auditLabel, targetType}`；L1 清單＝靜態預設 ∪ 已登記；A2 各類型（流程代碼 `extra_expense:<kind>`）由 `expense_type` 定義動態登記 | A2（W2／W1）、日後任何新單據、自訂模組 | W1＋W4 A2 |
| 2 | **待簽佇列項目契約**：標籤、開啟／核准／退回的路徑、ID 欄位目前由前端與 `approval_queue.py` 寫死（`ledger_action` 已逼出一次 L1 修改） | L1（`routers/approval_queue.py`、`helpers/approval_queue.py::base_item`、`approval-queue.html`） | 項目自帶 `typeLabel／openUrl／approveUrl／rejectUrl／idField`，前端優先讀它；`linkedQuoteNo=''` 的行為定死（不補案件標頭、不因無案件 DENY 非簽核鏈成員以外的人，標頭用 `subject`）；契約題「無案件項目：佇列＝詳情」 | A2、總帳申請、任何新類型 | W2 C＋W4 A2 |
| 3 | **定義種類**：`core/definitions.py` `KINDS = (4 種)`（L0 固定 tuple） | L0 | `register_kind(kind, validator, default, label)`；既有四種改為登記；`GET /api/definitions/kinds`；`expense_type` 為第一個使用者 | A2-2（W1）、日後任何可編輯定義 | W1 |
| 4 | **資料表欄位**：`case_extra_expenses` 之後每加一欄就一次 migration | L2（一次性） | **0003 一次加齊**：`kind、doc_code、data_json、lines_json、def_version、department_id、payee_*、pay_terms、remit_date、pay_method、pay_account_code、paid_by、pretax、tax、currency、void_reason／voided_by／voided_at`；`data_json／lines_json` 帶 schema 版本，**讀寫都保留未知鍵**（靜默遺失第一條） | A2-3～A2-7 只寫程式不加欄 | W2 A／J |
| 5 | **總帳維度**：`voucher_lines` 只有案件／往來／單據維度（部門要加欄＝底層 migration） | 底層（accounting migration 0003，一次） | `voucher_lines.dim_json`＋`gl_dimensions` 設定表（部門／案件／類別等維度不必再 migration）；事件契約行選填 `dims`；事件行可直接帶 `account_code`；`contract.apply_category_map` 解析器鉤子 | W4 G1～G5、日後任何維度 | W4 A1／W2 G |
| 6 | **信件類型與寄信**：模組登記 mail type 仍逼 L1 編輯（`notification_prefs.EVENT_GROUPS`、`email_notify.notify_*`、守門） | L1 | `notification_prefs` 由 `mail_types` 登記表自動併組；通用寄送 `email_notify.send_registered(mail_key, 收件帳號, 標題, 徽章, 明細列, 連結, 備註)`（模組不必在 L1 檔加 `notify_*`）；**一次登記** `expense_form_submitted／next_tier／approved／returned／payout_pending／paid／payout_review`（信內不放金額） | A2-7、日後任何單據 | W2 D＋W4 A3 |
| 7 | **PDF／輸出**：`pdf_gen.py` 每種單據一支 builder | L1 | 公開 `render_document(definition/template, view, status, doc_no)`（包 `doc_template`＋公司抬頭＋未核可每頁標示）；輸出版型存 `output_template` 定義（種類已有）；A2 類型只登記版型 | A2-7、自訂模組（已有 `render_view`）、日後單據 | W1 |
| 8 | **表單渲染（前端共用）**：動態欄位／明細表／查找目前只在 `custom-records.html`／`form-preview.js` | L1 前端 | 共用元件 `static/definition-form.js`（依定義渲染欄位、明細表、`optionsFrom`、鎖定預填、公式即時算）；登記 modules.json 歸屬 | A2-4（首個使用者）、建構器預覽、日後表單 | W1 |
| 9 | **總帳金流的自訂欄位**：`helpers/custom_finance.gl_lines` 只挑特定屬性（`taxField`／`docTypeField` 等新屬性每次都改 L1＋快照＋UNIT-INDEX） | L1 | 整個 `finance` 屬性字典＋單據資料原樣傳給 provider；provider（模組）自行解讀 | W4 G3、建構器金流 | W4 A4 |
| 10 | **契約（加法，文件先行）**：IP-9 `expense.entries`（加選填 `departmentId／kind`；消費端忽略未知鍵）、IP-100（加 `kind／payee／payeeBank(遮罩)／payTerms`）、新能力 `expense.categories`（單一提供者，代碼穩定）、`tax.input_invoices`（多提供者）、`gl.month_totals(conn,start,end,dims=None)`（回傳含 `contract_version`） | L1（契約文件＋消費端容忍） | `INTEGRATION-POINTS.md` 一次登記；`money_flows.json`／`MONEY-FLOWS.md` 同步 | A2、W3 報表、W4 | W2 G＋W4 C |
| 11 | **費用類別清單**（獨立、代碼穩定、可編輯） | L2（accounting）＋能力 | 新表 `expense_categories(code,name,default_tax,active,sort)`（accounting migration）＋`gl_category_map` 以代碼為鍵；編輯畫面＝總帳設定頁頁籤；能力 `expense.categories` 供 W1 表單 `optionsFrom` 與 W4 對應畫面（代碼發布後永不改） | W4 編輯、W1／W2 消費 | W4／W1 |
| 12 | **個資（收款人銀行）**：`archive.py` F2 個資清單、備份／匿名化／示範庫分類、隱私告知文字目前要改程式 | L1（一次） | ① 模組宣告個資表的登記點（`module.json` 的 `personal_data_tables`＋`backup／anon／demo` 類別，archive／匿名化／示範庫從它讀；W4 已驗證 module.json 可宣告這三類）；② 隱私告知補充鉤子（模組在 `module.json` 宣告 `privacy_notice_addendum`，L1 告知頁彙整）。**表名統一＝`user_bank_accounts`（W3 命名；W2 原提 `user_payment_profiles` 廢棄）**，放 **payroll 模組 migration**（模組內；勞報／獎金也用），不動 `users`；另登記單一提供者能力 `payee.bank_profile(conn, username, viewer)`（依檢視者回完整／遮罩末 4 碼／無權限；出納頁與 A2 撥款讀它，payroll 不在 ⇒ 退回收款人文字）；權限沿用既有 key（`finance`／`cashier`），不新增 | W2 表＋API＋撥款消費端；W3 編輯畫面（模組頁，非 `users.html`）＋遮罩審查 | W2 B／W3 #1／W4 |
| 13 | **權限／選單**：`users.html` 權限目錄、`module_keys` | L1（一次） | 一個權限 key（例 `expense_forms`）涵蓋「新增請款」所有類型；每類型可見性走定義 `visibleTo`；`module_registry` 自提供者讀 key（比照自訂模組 `_permission_keys`）；總帳新功能＝既有頁的頁籤（頁籤標籤由 API 供應） | A2、總帳 | W2 H＋W4 A7 |
| 14 | **守門清單的慣例發現**：`test_wording_guards SCAN_FILES`、`modules.json` 歸屬、`global_tests` 目前要人工列（已造成 3 次列車紅） | tests／tools | 約定：`modules/*/notify.py` 自動入掃描；`modules.json` 以 `modules/<key>/**` 為預設歸屬；`global_tests` 由掃描器推；`bottom_layer.json`／單位卡／L1 快照／`test_extra_expense_columns_are_carried` 一次更新 | 所有模組 | W4 A5 |
| 15 | **附件**（使用者第 2 項） | — | **不需預留**：`uploads.path_access`（IP-104）＋`attachments.catalog`（IP-105）已是提供者制；`upload_path_key` 通用。契約文件註明目錄項目 `quoteNo` 可為 `''`／哨兵 `-`（filehub P3 須處理） | M01 L2 規則、P3 | W2 E |
| 16 | **退回必填原因**（使用者第 1 項） | — | **已通用**（`require_reject_reason` 各端點共用）；新類型端點呼叫即可，不需登記 | A2-3 | — |
| 17 | **共用日期工具**：後端 `_local_date_of` 重複兩份（`pdf_gen.py`、`modules/case/api/quotations.py`）、前端 `MotrixDate` 每次加函式就碰 L1 | L1（一次） | `helpers/dates.local_date_of`（L1 公開新增）＋ `static/motrix-date.js` 補 `monthEnd／weekStart／diffDays／isWeekend`；之後兩處改呼叫共用版 | W3（地圖／報表日期）、A2 日期欄位、日後日期需求 | W3 #5 |
| 18 | **deid（去識別化）prodroot 線**（`wip/w3-prodroot-2`，排第 29 班） | L0／L1（本質如此） | 不需鉤子；**同一個全量班上線**。約束：本批新寫的 L0／L1 程式**不得帶本公司字面值**（跑 sale 掃描器），否則 deid 又要回頭剪 | W3 | W3 #6 |

### 刻意**不**預留（與理由）
- 共用表上的「備用 JSON 袋」（`users`／`quotations` 加 `extra_json`）：目前沒有具體使用者；`data_json` 只放在新欄位集。真有需要時是模組表，不是共用表。
- 建構器欄位層級 `showWhen`（依欄位值顯示）：方案 C 已不採用；A2 的類型分支靠「類型定義＋選類型」，不需要。
- 通用狀態機引擎：A2 沿用額外支出既有狀態（草稿→待審核→簽核中→已核准→已付款）；各類型差異在欄位與簽核層，不在狀態。
- 多幣別／匯率：先只記台幣。
- 新頁面的選單機制：沿用 `module.json pages`；總帳功能一律頁籤。
- `expense_type` 第二人審核：先不做（稽核留痕）；要做時走既有定義送審機制，不需底層。

- `users.html` 模組擴充槽（W3 提案）：**不預留**——銀行資料的本人／管理員編輯畫面做成 payroll 模組的一個頁面（`module.json pages`），不需要在 `users.html` 開槽；若日後有第二個需要在使用者頁長欄位的模組再說。
- `helpers/clock.py`（可測時鐘接縫，W3 提案）：**不預留**——目前無 A2／總帳／P3 的具體需求（產品端 126 處直接 `date.today()`，測試已有 `_clock.py` 守門）；要做是另一個專案，且「正式環境不讀環境變數」的安全設計要單獨審。
- 審計動作標籤：W4 已驗證**可不改底層**（未登記的動作第一段直接顯示原字串）；本表 #1 的 `auditLabel` 只是讓標籤好看，屬加分項，不是硬需求。

### 預留切片的規模與順序
- L0／L1 工時約 **7 人日**（#1 1d、#2 0.75d、#3 0.75d、#6＋#14 1.25d、#7 0.5d、#8 2d〔即 A2-4 的共用元件，提前到此切片〕、#9 0.25d、#10＋#12＋#13 1.25d、#17 0.5d；deid #18 另計，W3）＋ migration（#4 case 0003、#5 accounting 0003、#11）約 1d；**同一班上線**（全量班）。
- 順序：預留切片（第 29 班）＝ A2-1（0003）＋ A2-2（定義種類）＋ 上表 L1 項 ＋ A2-3～A2-5 的模組端；A2-6／A2-7／G1～G5／P3／deid 之後只動模組。
- **本班之後如有人發現還要碰 L0／L1，視為預留清單漏項，要回頭補進本表並說明為什麼當初沒想到。**

## 7. 明細與資料契約（W1 定案 2026-10-01；回覆 W2 四問；W4 對 `accountCode` 快照有否決權）

### 7.1 明細列（`lines_json` 的每一列）——camelCase，與既有額外支出明細一致
| 鍵 | 型別 | 說明 |
|---|---|---|
| `category` | str | **費用類別名稱**（來自 `expense_categories`／`GET /api/expense-categories`）；權威欄位，GL 科目由它經 `gl_category_map` 解出 |
| `accountCode` | str | 科目代碼**快照**：後端在**送審當下**由 `category` 解出並寫入（前端顯示用、唯讀）；之後改對照表不回寫舊單；GL 取快照、沒有才現解（**W4 確認**） |
| `summary` | str | 摘要／品名（定義可把標籤改成「品名」「摘要」） |
| `qty`、`unitCost` | number | 選填；兩者**都有**才參與金額計算 |
| `amount` | number | 行金額 |
| `invoiceNo` | str | 選填；重複＝警告不擋，類別「收據」免檢 |
| `files` | `[{path,name}]` | 選填；路徑規則照案件附件（W2 `_READ_RULE`） |
| 其餘 | — | 定義自訂的明細欄（鍵＝定義欄 key）原樣保留，不得丟（`test_extra_expense_columns_are_carried`） |

**金額權威**：列上 `qty` 與 `unitCost` 都是數字 ⇒ `amount = round_half_up(qty × unitCost)`（忽略前端送來的 amount）；否則 `amount` 為權威（數字、≥0）。`total_cost = Σ amount`（整數 TWD，`round_half_up` 每行一次；國外差旅只收 TWD）。**v1 明細一律含稅**；稅額欄位（定義的 `taxField`）先保留鍵、不參與加總（有稅額欄位才拆進項稅是 W4 G 列，之後再開）。定義驗證：明細表要嘛有 `qty`＋`unitCost` 兩欄，要嘛有 `amount` 欄，不可兩者皆無。

### 7.2 `data_json` 的平台保留鍵（定義可用其他任意 key）
`applicant`（帳號，預設＝登入者，`locked` 可由超級管理員在定義改成可編輯）、`dept`（部門 id；W2 同步寫入 `department_id` 欄）、`cost_dept`（費用歸屬部門 id，選填）、`req_date`（填表日期 `YYYY-MM-DD`）、`pay_date`（支付／預計日期）、`urgency`（一般／急件／特急）、`pay_terms`（付款條件；**出納**填）、`remit_date`（匯款日；**出納**填）。`pay_terms`／`remit_date` 在 `editableBy:"cashier"` 下核准後仍可由出納改（不走變更申請）。保留鍵由 `validate_values` 做型別檢查；自訂鍵依定義欄位型別。

### 7.3 類型代碼與單號
類型代碼（`kind`，＝`expense_type` 定義的 key）：`purchase_req`（請購單）、`purchase_order`（採購單）、`travel`（差旅費用請款單）、`petty_cash`（零用金支付單）；`kind=''`＝既有「一般」額外支出（維持今天的行為，v1 **不另建** `general` 定義）。單號 `doc_code` ＝ `{prefix}-{YYYYMMDD}-{NNNN}`，前綴**取自定義的 `numbering.prefix`**（使用者定案：PR／PO／TE／PC；請購單不再用草稿的 RQ）。⚠ `PR-` 與 arap 請款單 `PR-YYYYMM-NNN` 前綴相同、位數不同（6 位月份 vs 8 位日期）：稽核／全域搜尋／單號解析要以位數分辨——W3／W2 檢查點。W2 暫用常數表 {purchase_req:PR, purchase_order:PO, travel:TE, petty_cash:PC}，A2-2 之後改讀定義。`register_kind` 登記的是**定義種類** `expense_type` 本身，不是各個 kind。

### 7.4 「進出納」宣告
定義頂層 `payable: true|false`：`purchase_order`／`travel`／`petty_cash` ＝ true，`purchase_req` ＝ false（請購單只是核准文件：不進 IP-100、不入營運報表支出）。`kind=''` 維持今天（進出納）。A2-2 交付 L1 helper（供各模組 in-process 呼叫，不走 HTTP）：
- `helpers.expense_types.list_types(conn) -> [{code,name,prefix,payable,defVersion}]`（只含已發布、啟用的）
- `helpers.expense_types.get_type(conn, code, version=None) -> dict|None`（定義本文＋`defVersion`；版本釘在單據的 `def_version`）
- `helpers.expense_types.validate_values(defn, data, lines, *, viewer) -> (clean_data, clean_lines, total_cost, problems)`（金額重算、`locked` 以後端預填為準、保留鍵檢查）
W2 在 helper 到位前用常數集合 `{purchase_order, travel, petty_cash}` 判斷 payable，並把讀取點集中成一個函式，到時一行換掉。

## 8. `expense_type` 定義結構與 API 契約（W1 → W3 編輯頁 v1；2026-10-01）

### 8.1 定義本文（`ui_definitions` kind=`expense_type`，key＝類型代碼 `purchase_req／purchase_order／travel／petty_cash`；公司層 `company`）
```
{
  "name": "請購單",                 // 必填，顯示名稱
  "numbering": {"prefix": "PR"},    // 必填；大寫英文 1~4 碼；單號＝{prefix}-{YYYYMMDD}-{NNNN}
  "payable": false,                 // 必填 bool；true＝核准後進出納（IP-100）
  "docType": "expense_purchase_req",// 必填；簽核單據類型代碼（register_doc_type 已登記的；簽核流程在「簽核設定」頁設）
  "enabled": true,                  // 選填，預設 true；false＝新增表單不列、舊單不受影響
  "fields": [ …欄位… ],             // 同建構器欄位（validate_fields 同一份）；必須含 `lines` 這個 type:"table" 欄位
  "ui": {"form": {"groups": [{"title","fields":[key…]}]}, "list": {"columns":[key…]}},
  "output": {"template": {…輸出版型…}}   // 選填；沒有就用預設版型
}
```
- 欄位：`type` ∈ text／textarea／number／date／daterange／select／radio／ref／formula／table／file；`ref.target` ∈ users／departments；平台保留鍵（§7.2）：`applicant／dept／cost_dept／req_date／pay_date／urgency／pay_terms／remit_date`——定義可以放，型別固定（applicant＝ref users、dept／cost_dept＝ref departments、req_date／pay_date＝date、urgency＝select 含「一般／急件／特急」、pay_terms／remit_date 只在 `editableBy:"cashier"` 下）。
- 欄位專屬屬性：`locked: true`（預填後使用者不可改；例 applicant）、`editableBy: "cashier"`（核准後僅出納可改）、`default: {"$":"requester"|"today"}|值`、`required`。
- `lines` 表格欄位的 `columns`（§7.1）：必含 `category`（type select，`optionsFrom:"expense_categories"`）、`summary`；金額要嘛 `qty`＋`unitCost`＋（公式或唯讀）`amount`，要嘛只有 `amount`；`invoiceNo` 選填；`minRows≥1`。定義驗證（`validate_expense_type(body, key)` → `[{path,message}]`，與建構器同形狀）會擋：缺 prefix／payable／docType／lines、prefix 與別的類型重複、`docType` 未登記、金額欄不成立。

### 8.2 API（全部沿用既有定義庫路由，不新增編輯用端點）
- 清單／草稿／驗證／發布／版本／差異／還原：`/api/definitions/expense_type[/{key}[/draft|/validate|/publish|/versions/{v}|/diff|/restore/{v}]]`（超級管理員；`GET /api/definition-kinds` 列出種類；`expense_type` 由 `register_kind` 登記，驗證器＝`validate_expense_type`）。送審規則：直接發布＋稽核（非自訂模組種類的既有做法）。
- 供表單與列表用（任何登入者；A2-2 我交付）：`GET /api/expense-types` → `[{code,name,prefix,payable,docType,defVersion}]`（已發布且 enabled）；`GET /api/expense-types/{code}` → 最新發布版定義＋`defVersion`；`GET /api/expense-types/{code}?version=N` → 單據釘住的版本。
- 費用類別下拉：`GET /api/expense-categories`（W4）。
- 編輯頁 v1（W3）：清單（類型名稱／prefix／payable／版本／啟用）→ 點入編輯：欄位表（新增／刪除／排序／屬性）＋明細欄表＋`payable`／`docType`（下拉取 `GET /api/settings/approval-doc-types`）／`prefix`／`enabled`＋預覽（呼叫 `/validate`，紅字顯示 `[{path,message}]`）＋發布（填說明）＋版本／還原。頁面＝`frontend/pages/expense-types.html`（選單群組「設定」，權限＝超級管理員；歸屬 modules.json 與路由同 definitions 相關頁——W3 自行向 node-bb 確認頁面歸屬，新增頁面要走 L1 頁面登記）；用 `MotrixFormPreview`（預覽）與既有建構器欄位編輯元件可重用者先重用，不重造。
- 寫入／讀取的正確性守門：編輯頁存的 JSON＝上面 §8.1 形狀；`validate` 綠才能發布（伺服器端驗證為準，前端只顯示）。
