# A2「新增請款」改版——子視窗 hichan-ae 的三個切片（唯讀調查＋設計；凍結期間只有文件）

> 2026-10-01。讀的是 origin/platform dbd79c4a（train/28 進行中）。**未改任何程式。** 給 W1（主導）與 node-bb。

## 切片 1：使用者有沒有銀行帳號欄位？在哪改？承攬商／勞報單用什麼？（已驗證）

### 事實（file:line，皆 origin/platform）
| 問題 | 答案 | 證據 |
|---|---|---|
| `users` 表有沒有銀行欄位？ | **沒有。** 只有 id／username／password_hash／display_name／role／email／phone／modules／active／created_at／unlock_password_hash／must_change_password／notification_muted，後加 daily_task_pw_hash、totp_*、**department_id**（FK departments） | `backend/db.py` users 建表（約 L1）＋ALTER 清單；grep `bank` 在 users 上 0 命中 |
| 誰能編輯使用者資料？ | **只有超級管理員**，在 `frontend/pages/users.html`（`PUT /api/users/{id}` 只收 display_name／role／email／phone／modules／notification_muted／department_id／password）。**沒有「本人編輯自己的資料」頁**；本人只能改密碼（`PATCH /api/auth/change-password`） | `routers/auth.py:1555–1614`；auth.py:1409 `/api/auth/me` 唯讀 |
| 個資告知機制？ | 使用者姓名／Email／電話已有「個資蒐集告知」紀錄（`privacy_notice_acks`，key `user:<id>`，只有超管可寫，不擋存檔） | `routers/auth.py:1617–1642` |
| 承攬商（個人外包，`contractors`）銀行欄位 | **有**：`bank_code`、`bank_name`、`bank_branch`、`bank_account_name`、`bank_account_number`（另有 id_number、id_card_image、id_card_image_back）。編輯：外包名冊頁（`/api/contractors` POST／PUT）；列表／單筆**直接回完整帳號與證號**（無遮蔽），權限＝`require_superadmin` 或模組 `contractor_list` | `db.py` contractors 建表（bank_* 五欄）；`modules/subcontract/api/contractors.py:115–118,165–185` |
| 承攬商廠商（`vendor_contractors`，公司） | 銀行資料不在欄位，存在 `data_json`（`bankAccountName/Number/Branch/Code`、`bankName`、`bankPassbookImage`），匯款申請**建立當下凍結進 `snapshot_json`**（之後改廠商資料不影響已送出的單） | `db.py` vendor_contractors 建表；匯款單快照（contractor_vouchers.py） |
| 勞報單（`payslips`）銀行 | **沒有自己的欄位**：靠 `contractor_id` 連到 `contractors` 取銀行資料；匯款單快照含 `personnel[].bank*`（CT1，使用者裁示 D2） | `db.py` payslips 建表；queue_items（contractor_vouchers.py）`personnelBanks` |
| 額外支出 `case_extra_expenses` | **沒有收款人銀行欄位**；只有 `payer_username`／`payer_name`（誰墊款）、`quote_no NOT NULL`（必掛案件）、files_json、approval_json | `db.py` case_extra_expenses 建表 |

**結論**：要做「員工代墊款／請款單直接匯給員工」，需要使用者層級的銀行帳號——**目前不存在**，也沒有本人編輯入口。承攬商／外包人員的銀行欄位存在，但**完整帳號回傳給所有有權限者、沒有遮蔽、沒有變更稽核**，這是既有的隱私落差（見下方遮蔽規則，新舊可一起改）。

### 最小可加欄位設計（加法、不改既有欄位語意）
**建議：新表，不是 users 加欄位**（使用者表被 L1 認證大量讀寫，而銀行資料敏感、需要歷史與稽核，不宜混在 session／登入用的列）。

```
user_bank_accounts            -- 每人一個「目前有效」帳戶（UNIQUE user_id where active=1），舊的不刪、標 active=0 留歷史
  id, user_id (FK users), bank_code TEXT(3), bank_name, bank_branch,
  account_name, account_number,            -- 全數字（去空白、去連字號），6–16 碼
  active INTEGER, verified_by TEXT, verified_at TEXT,   -- 財務核對過（選填）
  created_at, created_by, updated_at, updated_by
```
- 放哪：新增表屬 L1 核心（users 相關）⇒ migration 加在 `db.py` 並升 CORE 次版號＋core CHANGELOG＋L1 快照；不影響既有資料。欄位全空＝沒設定（不是錯誤，請款單提交時提示「尚未登錄收款帳號」）。
- **請款單提交時凍結快照**（比照匯款申請 `snapshot_json`）：`expense.payee_bank_snapshot`；之後本人／管理員改帳號不改已送審／已核准的單；若帳號在送審後被改，簽核畫面加「帳號於送審後變更」警示（比對快照與現值）。
- 承攬商（個人）沿用既有 `contractors.bank_*`，不搬；請款單「收款人」是 union：`payee_type ∈ {employee, contractor, vendor, other}` + 對應 id；other＝一次性收款人，帳號只存在該單的快照。

### 編輯介面
- **本人**：新頁「我的資料」（`profile.html`，登入者任何角色可進，**只能改自己的** `user_bank_accounts`；同時顯示 email／phone 唯讀、改密碼連結）。API：`GET/PUT /api/me/bank-account`（token→user_id，不收 user_id 參數，避免 IDOR）。
- **管理員**：`users.html` 抽屜加「收款帳號」區（超級管理員＋模組 `finance`／`cashier` 可看可改；一般管理員看遮蔽版）。API：`GET/PUT /api/users/{id}/bank-account`，每次寫入 audit（`user.bank_account.update`，detail 只記「欄位名稱＋末四碼變化」，不記整號）。
- 變更通知：帳號變更寄信給本人（Email 有設定時）——防止被盜帳號改匯款帳號後請款（信件類型登記進 `mail_types`）。

### 遮蔽（PII）規則
| 角色／情境 | 看到 |
|---|---|
| 本人看自己的 | 完整 |
| 超管、財務（`finance`）、出納（`cashier`）——**付款需要** | 完整（每次「顯示完整帳號」寫 audit `…bank_account.reveal`，前端預設遮蔽、點「顯示」才取） |
| 簽核人（簽核佇列／詳情） | 銀行名稱＋**末四碼**（`****1234`）＋戶名；看得到金額但不必看完整帳號（比照既有 `_mask_money` 遮蔽思路：不是拿掉欄位，是換成遮蔽字串，避免誤判「沒有帳號」） |
| 其他人／列表頁／匯出／信件／PDF 預覽 | 預設遮蔽（末四碼）；Excel／PDF 匯出走既有 `export_logged` 稽核，**不含完整帳號**，除非出納的「付款清單」專用匯出（明示用途、另記 audit） |
| 日誌／稽核 detail／錯誤訊息／前端 console | 永不含帳號全碼（比照稽核 detail 不含個資值的既有規則 `summarize_filters`） |
- 存簿影本圖（若日後加）比照既有 `_stamp_passbook`（蓋「僅供…核對使用」橫幅），且沒有財務檢視權一律拿掉影像（既有 `out["files"]` 過濾 `passbook`／dataUrl 的規則）。
- 驗證：銀行代碼 3 碼數字（可對照代碼表，不強制）；帳號去空白連字號後 6–16 碼數字；戶名必填；**不**自動比對戶名與姓名（外幣／公司戶／代收）。
- 個資告知：把 `user` 目的的告知文字加上「收款帳號」一項（`privacy_notice`）；沒有告知紀錄**不擋存檔**（沿用既有規則），但請款單提交時若收款人是員工且沒告知紀錄，顯示提示。
- 既有承攬商銀行資料的遮蔽落差（list／單筆完整回傳）：建議同批改成「列表遮蔽、單筆需 `contractor_list` 並寫 reveal audit」，但這是**行為變更**，需 node-bb 裁示是否併入 A2。

### 測試（切片 1）
單元：遮蔽函式（各角色×各情境矩陣，含 None／空字串／短於 4 碼）；驗證規則；快照凍結（改帳號不影響已送審單、變更警示出現）；IDOR（`/api/me/bank-account` 不收 user_id；`/api/users/{id}/…` 非授權者 403）；audit detail 不含全碼（字串掃描）；匯出不含全碼。e2e（R2）：本人頁存帳號→重整仍在；管理員抽屜看遮蔽版／點顯示出現全碼且 audit 有 reveal；簽核畫面只見末四碼；變更後簽核畫面出現警示；截圖。

## 切片 2：無案件請款的「部門」維度（設計＋測試）

### 現況（file:line）
- 營運報表支出 `modules/analytics/api/reports.py::_collect_expenses`（L3389）：部門篩選只會用 `quote_no → quotations.sales_person_id → users.department_id`（L3410–3421）。**無案件的支出（quote_no 空）在開啟部門篩選時一律被排除**（`_quote_in_department` 對空 quote_no 回 False；函式註解 L3396–3398 承認「無法歸屬到任何部門」）；不篩選時則只算進總額、沒有部門。
- `case_extra_expenses.quote_no NOT NULL`（db.py 建表）⇒ 目前額外支出**必須**掛案件；A2 要讓它可無案件，就會碰到這個維度缺口。
- 同一邏輯也被首頁儀表板共用（`_collect_expenses(conn=…)`，AC2 註解）。
- 總帳事件目前只帶 `case_no` 維度（`gl.events` Event 形狀），沒有部門維度。

### 設計
1. **資料**：請款／額外支出列新增 `department_id INTEGER NULL`（加法；`case_extra_expenses` ALTER，migration 在 case 模組；既有列維持 NULL＝沿用案件推導）。
2. **歸屬規則**（單一函式 `expense_department(entry, ctx)`，報表／儀表板／日後總帳共用）：
   `entry.department_id`（人工指定）→ 有案件：案件業務的部門（現行推導）→ 無案件：**提交人當下的部門**（`users.department_id`，提交時寫入 `department_id` 凍結，避免日後調職使歷史漂移）→ 仍無：`未分類`（`deptId=None, deptName="未分類"`，與現有 `_row_dept` 同樣的桶名）。
3. **預設與可改**：無案件時表單預設帶提交人部門，欄位可改（限簽核人／出納／財務／超管改，申請人自己可在送審前改）；有案件時預設空（沿用案件推導），可「覆寫」但要填理由（audit）。
4. **報表行為**：部門篩選＝「歸屬函式結果等於該部門」；**不再丟掉無案件支出**；篩選關閉時所有支出都出現且每列有 deptName；新增「未分類」桶（顯示在部門彙總底部，讓使用者看得到有多少沒歸屬）。不變式：**Σ 各部門（含未分類）＝總額**。
5. **介面**：請款表單加「部門」下拉（來源 `/api/org`／departments）；報表支出明細每列顯示部門；報表頁篩選加「未分類」選項。
6. **提供者**：`rec.extra_entries`（M01 recognition）與 `expense.entries` 提供者的回傳 entry 加選填鍵 `departmentId`（舊提供者沒有 ⇒ `None` ⇒ 依案件推導，向下相容）。

### 測試（切片 2）
單元（`tests/test_expense_department_2026_10_xx.py`，資料走真實表）：
- 案件推導（業務在 A 部）→ A；人工指定覆蓋案件 → 指定；
- 無案件＋提交人在 B 部 → B（且提交後換部門，歷史仍 B，凍結）；
- 無案件＋提交人無部門 → 未分類；
- 篩選 A：只有 A 的（案件推導＋指定＋無案件提交人在 A）；篩選 B 不含 A；篩選關閉：全含；
- **守恆**：Σ(各部門＋未分類)＝總額（跨三種來源：承攬商派發／額外支出／叫料＋`expense.entries`）；
- 向下相容：舊提供者回傳無 `departmentId` 的 entry 照舊；`department_id` 為 NULL 的既有列行為不變（現有 `test_reports_*`、`test_visual_management_2026_08_28`、org select 相關題全跑一次）。
e2e（R2）：請款表單無案件→部門預設帶自己；報表部門篩選包含該筆；切「未分類」看到另一筆；截圖（表單、報表篩選前後）。

## 切片 3：R3 交叉驗證與 R2 e2e／截圖規則（我怎麼驗每個切片）
**R3 每個切片的驗證清單（我照這份逐項跑、逐項回 PASS／ISSUE，不修）**：
1. 讀 diff 對照設計：資料表／欄位（加法？migration 可重跑？舊資料不動？）、L1 變更有無升 CORE／CHANGELOG／快照、`**` 與像權限 key 的字串、模組歸屬／產生檔。
2. 權限矩陣：每個 API 用「本人／同部門／他人／簽核人／財務／超管／未登入」逐一打（IDOR、越權、狀態機：送審後不可改、核准後不可改、撤回規則），含直接呼叫 API（不靠畫面）。
3. 金額與帳務：請款→簽核→付款→總帳事件（E11 等）的借貸手算對照（第一原理，不讀引擎）；稅額拆分（含稅未拆）；幣別／小數進位；重送／重複提交（冪等）。
4. PII：遮蔽矩陣、audit／日誌／匯出／信件是否洩漏全碼（字串掃描）、快照凍結。
5. 終點狀態：按鈕按完看 DB 與 DOM 終點（不是只看請求送出），每個按鈕至少一個終點斷言。
6. 反向控制：把新守門／新邏輯拿掉一行，測試必須變紅（突變）。
7. 回歸：動到的頁面既有 e2e（golden、主題、跨模組）＋ `test_module_keys_consistency`／`wording_guards`／`no_credentials_in_query`／spec_coverage／generated_maps／模組 CHANGELOG 守門。
8. 環境（提交規則）：`.venv312`、`MOTRIX_TRAIN=1`、獨立 basetemp、無殘留行程、不在凍結期、只殺自己起的 PID 樹。

**R2 e2e／截圖規則（落地版）**：
- 每個新畫面／按鈕：一支 Playwright e2e 走「真使用者路徑」＋終點斷言＋截圖（預設寫暫存；要留共用夾須設 `MOTRIX_SHOTS_DIR` 並過 BK19 護欄旗標；截圖寫入一律 try/except，不因截圖失敗而紅）。
- 三角色截圖：申請人、簽核人（遮蔽版）、財務（完整版）——同一張單各一張，證明遮蔽真的生效。
- 時間相關：瀏覽器時區 Asia/Taipei＋固定時鐘（本批剛修的本地日期問題：請款日期預設、付款日、報表月份都要在 00:30 台北時間驗）。
- 版面：一般寬度＋窄螢幕（390px）各一張；圖釘／晶片類畫面另量 getBoundingClientRect（不靠肉眼）。
- 我作為驗證者會把每張截圖實際看過（不只看檔案存在），報告附路徑與「看到什麼」。

---
## 附：要一次收掉的 L0／L1 觸點（給 W1 的觸點表；node-bb 2026-10-01 指示）
判斷標準：只動 `modules/*`（含該模組 migration／測試）＝**模組內**；動 `db.py`、`core/`、`helpers/`（L1）、`routers/`、`conftest.py`、共用前端（`static/`、`pages/` 的共用頁）＝**碰底層**，會讓該班變成全量。

| # | 我這條線的項目 | 會不會逼出底層改動 | 能不能做成模組內 | 建議（一次預留的鉤子） |
|---|---|---|---|---|
| 1 | **使用者主檔銀行／PII 欄位**（`user_bank_accounts`） | 若放 `users` 欄位 ⇒ `db.py` migration＋CORE 次版號＋L1 快照（碰底層）。若做成**新表放模組 migration**（payroll 或新的 `finance_profile` 模組；模組 migration 機制已存在：accounting 0002、crm 0001）⇒ 模組內 | **可**：表、API（`/api/me/bank-account`、`/api/users/{id}/bank-account`）、遮蔽函式、mail_types 註冊（`mail_types.register` 是模組可呼叫的公開 API）、audit 寫入全在模組 | 底層只剩兩個**介面缺口**要一次預留：(a) `users.html` 抽屜的**模組擴充槽**（現在沒有；否則每加一個使用者相關面板就改一次 L1 頁）；(b) `privacy_notice` 的「目的文字補充」提供者（現在告知文字在 L1 helper，加「收款帳號」一項要改 L1）。另：「我的資料」頁若要進側欄選單，確認模組可宣告自己的選單項（`/api/platform/menu` 已是宣告式，預期可） |
| 2 | **報表部門維度（無案件請款）** | `case_extra_expenses.department_id`＝case 模組 ALTER migration（模組內）；`_collect_expenses`＝analytics 模組；`rec.extra_entries`＝case 模組；`expense.entries` 提供者契約加**選填鍵** `departmentId`＝只改 INTEGRATION-POINTS／core CHANGELOG 文字（不改程式）；首頁儀表板共用同一函式（analytics 模組） | **可，全模組內** | 只需在 core CHANGELOG 補一行契約說明；`gl.events` 日後若要部門維度＝accounting 模組的事件形狀＋`gl_lines` 欄位（accounting migration，模組內） |
| 3 | **地圖縮放／共用 JS**（`map.html`、`map-google.js`、`map-overlay.js`） | 這三個是 L1 前端，每次調整都碰底層 | **不可**（頁面本身是 L1）；但可把「縮放表／標籤模式」收成單一常數區，降低日後為調參數再開一班的機率 | 已集中在 `_pinSizeFor`／`_chipModeFor`；下一次要動時一併做「圖釘尺寸使用者偏好」等想得到的需求 |
| 4 | **時鐘守門 `_clock.py`／conftest** | 測試基礎設施（conftest、tools/platform）不算產品 L1，但 conftest 是共用檔、`MOTRIX_TEST_TODAY` 改 build 腳本 | 不需產品改動 | 審查意見已送（fake_clock 回傳子類別、collect 檢查範圍）；產品端**沒有全域時鐘接縫**（126 處直接 `date.today()`）——若要真正可測，需一次新增 `helpers/clock.py`（L1，測試可替換的 `today()/now()`，**正式環境不讀環境變數**）；這是「想做就要一次做完」的 L1 項目，建議與本批其他 L1 一起 |
| 5 | **共用日期工具** | 前端 `static/motrix-date.js` 已是 L1；後端 `_local_date_of` 目前**重複兩份**（`pdf_gen.py`、`modules/case/api/quotations.py`，刻意不加 L1 公開名稱） | 重複版本是為了不碰 L1 的權宜 | 預留一次：`helpers/dates.local_date_of`（L1 公開新增）＋ `MotrixDate` 補 `monthEnd／weekStart／diffDays／isWeekend`，之後兩處改呼叫共用版、前端不再每次加函式 |
| 6 | **deid（去識別化）prodroot 線** | 必碰 `db.py`（凍結 migration 的 own 資料檔）、`helpers/auth`、`helpers/own_values`、`tools/build_deploy_package.ps1`、`tools/platform/*`＋`db._frozen_own_payload` 列入 L1 公開＋CORE 1.83 | **不可**（本質是 L0／L1） | 已停放在 `wip/w3-prodroot-2`（2d804b2b），排第 29 班；**這批新寫的 L0/L1 程式不得帶本公司字面值**（跑 sale 掃描器），否則 deid 又要回頭剪 |
| 7 | **pre_train_check／tools/platform** | 是工具樹不是產品；`GUARDS` 清單與 `PLAYBOOK` 是共用檔 | 不影響產品班次 | 每次新增守門都要同時加 `GUARDS` 列；我這批新增的守門（前端日期棘輪、匯出 AST 守門）已在 `tests/`，不需要再改 |
| 8 | **選單／權限 key** | 新增權限 key ⇒ `users.html` 目錄＋`core/registry`（SUPERADMIN_DEFAULT）＋`test_module_keys_consistency`（碰底層） | **可避免**：銀行帳號檢視／請款類權限**沿用既有 key**（`finance`、`cashier`、`case_manage`），不新增 | 若 W1 的請款類型分支需要新 key，請一次列出、同批註冊 |
| 9 | **新簽核單據類型**（A2 請款類型分支） | `helpers/tiered_approval.py` 的 `DOC_TYPES`／類型標籤、`approval-settings.html`、`approval-queue.html` 的 `docTypeLabel`／`typeTagClass` 都是 L1 常數（今天每加一種單據就改一次）；`approval.queue_items`／`approval.detail`／`approval.reassign` 提供者是模組內 | 提供者**模組內**；「類型標籤／流程設定清單」**碰底層** | 預留一次：類型登記改成提供者宣告（標籤／顏色／流程鍵由模組註冊），或先把 A2 會用到的類型一次加進 L1 常數 |
| 10 | **稽核動作標籤**（`helpers/audit._MODULE_LABELS`、`audit-log.html` 動作對照） | 每個新模組動作都要改這兩個 L1 檔（我做匯出稽核時就碰過一次） | 碰底層 | 預留一次：動作標籤由模組提供（registry 能力），或一次補齊 A2 的動作清單（`expense.submit／approve／pay`、`user.bank_account.update／reveal` 等） |
| 11 | **匯出稽核／PDF 姊妹**（`xlsx_out.export_logged／add_pdf_sibling`） | 已是 L1 公開 API | 新請款匯出只需呼叫＝**模組內** | 無需預留 |

**建議的「這一次」底層清單（一批做完）**：① `users.html` 模組擴充槽；② `privacy_notice` 文字補充鉤子；③ `helpers/dates.local_date_of`＋`MotrixDate` 補函式；④ 簽核單據類型與稽核動作標籤改成「模組註冊」；⑤（可選）`helpers/clock.py`；⑥ deid（第 29 班，本質 L0/L1，同批）。其餘（銀行表、部門維度、請款類型、匯出）都能留在模組內。
