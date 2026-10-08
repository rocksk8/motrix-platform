# A2 費用單據：W2 負責切片的設計（2026-10-01 草稿；只讀調查，未改程式）

基底 origin/platform 37ac3efe（train 28 合入前）。現況依據皆 file:line。決定清單見 node-bb 給 W1 的訊息（簽核 部門主管→最高管理者；發票重複僅警示；有稅額欄才拆稅；零用金只做支付；只 TWD）。

## 0. 現況關鍵事實
- 表 `case_extra_expenses`（db.py:3473，**`quote_no TEXT NOT NULL` 但允許 `''`** ⇒ 不必重建表）；M01 migrations 目前到 `0002`（remit 欄）。
- **所有端點路徑都帶 quote_no**：`/api/quotations/{quote_no}/extra-expenses/...`（case_extra_expenses.py:202–1169，約 25 支）；`_load`（:156）與每個 UPDATE 都 `WHERE id=? AND quote_no=?`；`_guard_case`（:165）要求報價單存在（不存在→404）＋`case_owner_readable`。⇒ 無案件單據**現行路徑根本進不來**。
- 附件：資料夾 `case_extra_expense`、單據鍵 `{quote_no}_{id}`（:729、`attachments.py::_path_bound_to_doc`）；鍵拆解 `_quote_and_index`（attachments.py:27）用 `rpartition('_')`，**`''` 案件得鍵 `_5` 仍可拆**（base=''）——可沿用，但 `upload_readable`/`path_access` 與 `_READ_RULE["extra_expense"]=case_owner_readable` 對空案件要另有規則（見 §2）。
- 簽核：`approval_json` 存 tiers；佇列提供者 `detail_extra_expense`（quotations.py:5824）、`approval_queue_items`（quotations.py:~4490）；L1 佇列權限過濾在 `routers/approval_queue.py`。
- 付款：IP-100 提供者 `modules/case/payables.py::_Payables`（pending:57／paid:65／mark_paid:77；key＝expense id，quoteNo 可空已被出納頁容許）；GL E11／E11b（modules/case/gl_events.py:30–70，`case_no=quote_no or ""`，費用角色固定 `COST_PROJECT`）；營運報表 `expense.entries` 經 case 的 `remit_fee_case`（手續費）與報表自己讀額外支出（reports `_collect_expenses` 對 quoteNo 空＋部門篩選會被排除，reports.py:3418）。
- **使用者主檔沒有銀行欄位**（db.py:519 users 欄位：無 bank；migration 只補過 department_id 等，db.py:1693／2380）。承攬商有銀行欄（subcontract/api/contractors.py）。⇒ 要新增並納入個資分類（F2）。

## 1. 遷移 0003（M01，`modules/case/migrations/0003_expense_forms.py`，只新增欄、冪等、`up(conn)`）
`case_extra_expenses` 加：`kind TEXT NOT NULL DEFAULT ''`（''＝舊版案件額外支出；`req_purchase／travel／po／petty`）、`data_json TEXT NOT NULL DEFAULT '{}'`（超管定義的欄位值）、`lines_json TEXT NOT NULL DEFAULT '[]'`（明細列，含科目代碼）、`def_version INTEGER NOT NULL DEFAULT 0`（建立當下的欄位定義版本）、`department_id INTEGER`（費用歸屬）、`payee_type/payee_name/payee_bank/payee_account`（TEXT，空字串預設）、`pay_terms TEXT`、`remit_date TEXT`（採購單：出納核准後填）。索引 `(kind, status)`。**舊列全部維持原值、行為不變**（kind=''）。
- 不動 V9 凍結表以外的東西：`users` 加銀行欄屬 **L0 migration**（core，需 W3 確認誰擁有 users）⇒ 建議**不加在 users**，改放 `user_payment_profiles(username PK, bank_name, branch, account_no, account_name, updated_by/at)`（core 或 payroll migration；個資分級 F2：備份僅進個資資料夾、API 只回給本人／出納／超管、稽核不記帳號內容、列表遮罩末 4 碼）。
- 備份：`archive.py` 用 `SELECT *` ⇒ 新欄自動匯出；新 profile 表要登記 T2／F2（`BK` 個資規則，見 archive 的 F2 清單）。

## 2. 無案件的守門（`quote_no=''`）
路徑方案（建議 **哨兵路徑段**）：`/api/quotations/-/extra-expenses/...`（`-` 映射為 `''`；新增共用 `_qn(quote_no)`），不複製 25 支端點。風險：(a) `docs/platform/case_read_scope.json` 與 `tests/platform/test_case_read_scope.py` 會列舉「帶案件單號的路由要有案件守門」——要為 `-` 路徑宣告「無案件：改用 `_guard_caseless`」；(b) 稽核 `case_no` 為空（正確）；(c) 報價單路由 `/api/quotations/-` 不可撞到既有靜態路徑。
- `_guard_caseless(conn,row,user)`：可見＝建立者 ∨ **簽核鏈成員（含代理，`is_document_approver`）** ∨ 出納／財務／admin／superadmin；看不到＝404（同 M01-O1）。不用 `case_owner_readable`。
- `_can_modify` 照舊（填寫人或 admin+）；`_load` 改 `WHERE id=? AND quote_no=?` 用 `_qn()` 後的 `''`，**禁止**「`-` 進來卻用別案 id」：id 與 quote_no 兩者都比（現狀已是）。
- 附件：`_path_bound_to_doc` 對 extra_expense 已是 `key == "%s_%s" % (quote_no, doc_no)` ⇒ `''` 時＝`_5`，成立；`_CasePathAccess.readable` 需加「空案件」分支（key 以 `_` 開頭 → 查該 id 的 `quote_no=''` 列，套 `_guard_caseless` 規則，非 `case_owner_readable`）。舊版舊資料夾規則（W2 legacy 分支）不受影響。
- 簽核佇列／詳情：`approval_queue_items`／`detail_extra_expense` 對無案件：`linkedQuoteNo=''`、標題改 kind 標籤（請購／差旅／採購單／零用金）；L1 佇列的案件標頭補全邏輯要容許空案件（檢查 `routers/approval_queue.py` 對 `linkedQuoteNo` 的假設）。
- 營運報表：`expense.entries` 對無案件列 `quoteNo=''`；部門維度用 `department_id`（W3 S5）——**選了部門時無案件列改依 `department_id` 比對**，否則整筆消失。

## 3. 出納撥款（沿用 IP-100 `case` 提供者，擴充而非新提供者）
- `_item`（payables.py:38）加 `kind`、`payee`（員工姓名／廠商）、`payeeBank`（僅出納可見，遮罩）、`payTerms`；`sourceLabel` 依 kind 顯示。案件額外支出（kind=''）行為不變。
- **採購單**：核准後出納填 **匯款日＋付款條件**（`remit_date`／`pay_terms` 欄）再 `mark_paid`；`mark_paid` 對 kind=po 要求這兩欄（或在同一請求帶入）——缺則 400、狀態不變。
- 收款人＝員工時，銀行資料取自 `user_payment_profiles`（無資料 ⇒ 出納頁明示「尚未登錄銀行資料」並擋標記？或允許手填覆蓋——待決）。
- 差額審核／手續費（`parse_remit`、`decide`）對新 kind **原樣有效**：`remit_*` 欄本就在同表。變更申請（`_apply_change` 的 L11 規則）對新 kind 同樣適用。

## 4. 「靜默丟資料」清單（新欄位必須逐一出現在這些地方，各配測試）
| 位置 | 動作 | 測試 |
|---|---|---|
| `ExtraExpenseIn`（:69） | 加 `kind`（僅建立時可設、之後不可改）、`data`、`lines`、`departmentId`、`payee*` | 欄位存在性＋型別／長度驗證（lines ≤200 列、data ≤ 上限，後端驗定義 schema，不信前端） |
| INSERT（create_extra_expense :246）／UPDATE（:285） | 寫入全部新欄 | 建立→讀回逐欄相等 |
| `_row_to_dict`（:92） | 回傳新欄 | 讀回 |
| `_proposal_from`（:809）＋`change_json` | **把新欄納入提議**（否則已核准後的變更申請會靜默丟掉 lines／payee） | 改 lines→核准→DB 與 changeHistory 都有新值 |
| `_apply_change`（:844）UPDATE 與 `changeHistory.from/to` | 新欄覆寫＋前後值記錄 | 同上；未改動的新欄不被清空 |
| `detail_extra_expense`（quotations.py:5824）與「編修後結果」對照 | 顯示 kind 標籤、明細列、收款人、部門 | 佇列詳情逐欄 |
| `payables._item`／`paid()` | 見 §3 | 出納清單逐欄 |
| `gl_events`（E11）| 無案件／kind 的費用角色（`COST_PROJECT` 不適用）⇒ W4 加角色與科目映射；逐列科目（lines 的 account code）入帳 | W4 |
| 結算／匯出／PDF（settlement、case 結案報表讀額外支出） | kind≠'' 不應進**案件**成本（無案件本來就不會；有綁案件的新 kind 要決定是否併入——見決定清單 Q11） | 案件成本不含無案件列 |
| 稽核 | `case_extra_expense.*` 的 detail 不含銀行帳號；ref_no＝單號 | audit 列斷言 |
| 備份匯出 | `SELECT *` 自動含；profile 表登記個資 | archive 欄位清單測試 |

## 5. 測試與驗證計畫（R1／R2／R3）
- API：四種 kind 建立／編輯／送審／核准／駁回／作廢；無案件看得見與看不見的人（建立者、鏈成員、代理、出納、無關者→404）；附件上傳／開檔（路徑綁 `_id`）；舊版案件額外支出（kind=''）全套既有測試不變（`modules/case/tests` 全跑）。
- 出納 e2e（R2）：待付款清單顯示 kind／收款人／遮罩銀行；標記付款（正常、實付≠應付→待審核、同人審核被擋）；採購單缺匯款日／付款條件被拒；付款後不可改。每個按鈕點、驗 DOM＋DB、截圖 `D:\開發測試檔\shots\<分支>\`。
- 變異：移除 `_proposal_from` 的新欄、移除 `_apply_change` 新欄、`_guard_caseless` 改放行所有登入者、`mark_paid` 略過 po 必填、銀行遮罩拿掉。
- 雙向互審：與 W1（範本／定義）、W3（報表部門維度）、W4（GL 角色）。

## 6. 待釐清（需 W1／W3／W4／使用者）
1. users 銀行資料放哪（建議獨立 profile 表，個資 F2）——誰擁有、是否已有人在做（W3）。
2. 定義（欄位 schema）放哪：`def_version` 對應 W1 的欄位定義表；超管改欄位後舊單如何顯示（以建立當下版本）。
3. 哨兵路徑 `-` vs 新路由群：前者改動小但要動 `case_read_scope` 守門；後者乾淨但重複端點。
4. 有綁案件的新 kind 是否併入案件成本（與 Q11 相同）。
5. 列車分類：0003 migration＋case 模組＝L2；profile 表／`routers/approval_queue.py` 空案件假設／mail 新類型＝L1（全量班）。

## 7. 底層預留清單（一次改到位；給 W1 的觸點表；使用者「都要動到底層了，思考先行預留」）
**A. 0003 migration 一次把欄加齊（L2，但之後再加就是第二次 migration）**：`kind`、`doc_code`（人看的單號，用 `next_entity_code(…,code_col="doc_code")`；現行額外支出佇列 doc_no＝id，新 kind 要 RQ-/TE-/PC-/PO- 單號）、`data_json`、`lines_json`、`def_version`、`department_id`、`payee_type/name/bank/account`、`pay_terms`、`remit_date`、`pay_method`（零用金／現金／轉帳→貸方腿）、`pay_account_code`（出納選的銀行／零用金科目）、`paid_by`、`pretax`、`tax`、`currency`（預設 TWD）、**作廢欄 `void_reason/voided_by/voided_at`（extra-expense void 路徑第 29 班要用，現在一起加）**。
**B. 個資表** `user_payment_profiles`（不動 users）：owner＝W2；migration 放 payroll（L2，獎金／勞報也會用）或 core；F2 處理＝備份僅個資資料夾、API 只回本人／出納／超管、列表遮罩末 4 碼、稽核 detail 永不記帳號。若 archive／個資分類沒有「模組宣告個資表」的註冊點 ⇒ **現在就在 L1 補一個註冊點**（否則每加一張個資表都要再動 archive.py）——需確認現況（archive.py 的 F2 清單）。
**C. L1 簽核佇列（`routers/approval_queue.py`、`helpers/approval_queue.py::base_item`）**：(1) 空案件：`_access_step(…linkedQuoteNo…)`（:100–108）與 `case.summary` 補標頭（:123–132）對 `linkedQuoteNo=''` 的行為要明確（不補、不拒、用 `subject`）；(2) 型別標籤固定表（:201 `"extra_expense":"額外支出"`）⇒ 提供者可給 `typeLabel`（依 kind）；(3) 項目要能帶 `subject`／`headline`（無案件時替代「客戶／專案」）；(4) 契約題 `linkedQuoteNo == 詳情 quoteNo` 對空字串的定義；(5) `test_approval_labels_match`／`count_items` 同步。
**D. 信件類型（L1 `helpers/mail_types.py`、`email_notify.py`）**：一次登記 `expense_form_submitted/next_tier/approved/returned` ＋ `expense_payout_pending`（通知出納）、`expense_paid`（通知申請人）、`expense_payout_review`（差額待審）——信內不放金額。
**E. 附件／路徑存取（L1 `helpers/uploads.py` 通用、M01 L2 規則）**：`_path_bound_to_doc`／`upload_path_key` 通用，不需改 L1；`_CasePathAccess.readable` 空案件分支＝M01 L2。若 filehub（P3）要搜無案件文件：目錄項目的 `quoteNo` 允許 `''` 且搜尋／計數不把它歸到任何案件（契約註明）——屬 attachments.catalog 契約說明（文件層）。
**F. 稽核（L1 `helpers/audit.py`）**：`_DOC_TARGET_TYPES` 一次加 `expense_forms`（或沿用 `case_extra_expense`）、`user_payment_profiles`；`case_no` 對無案件為空字串＝正確；detail 上限已有。
**G. 契約（文件＋消費端）**：IP-9 `expense.entries` 項目加選填 `departmentId`、`kind`（加法）；IP-100 項目加 `kind/payee/payeeBank(遮罩)/payTerms`（加法）；GL（W4）：事件行允許直接帶 `account_code`（逐列科目）並有角色預設——契約驗證在 accounting（L2）。全部是**加法**，先寫進 INTEGRATION-POINTS 再實作。
**H. 權限／選單／人員（L1 users.html 權限目錄、core perms）**：新權限 key（例 `expense_forms` 各 kind 或沿用 `custom.<key>`）一次登記；出納看銀行資料＝`cashier`；本人改自己的銀行資料不需特別模組（本人）。
**I. 沒有 L1 也能做、不必預留的**：哨兵路徑 `-`（M01）、`_guard_caseless`（M01）、IP-100 提供者擴充（M01）、出納頁（arap L2）、reports 部門維度（analytics L2）。`case_read_scope.json` 的 `-` 例外（文件＋守門）清單保持明確且最小。
**J. 提醒**：`users` 不動；任何「之後還會再加欄」的 JSON 形狀（`data_json`/`lines_json`）**現在就定 schema 版本欄 `def_version`** 與未知鍵保留規則（讀寫都不得丟未知鍵——silent-data-loss 清單的第一條）。
