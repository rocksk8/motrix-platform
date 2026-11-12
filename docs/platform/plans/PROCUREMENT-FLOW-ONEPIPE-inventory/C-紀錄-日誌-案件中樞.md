# C 組調查：施工紀錄／日誌／登載 與 案件中樞（唯讀盤點）

範圍：`D:\Claude-pm\h1-onepipe`（FastAPI `backend/` + Alpine 靜態前端 `frontend/pages`）。所有路徑相對於該 worktree。
標記：「已證」＝讀到程式碼；「推測」＝由程式碼推論、未實測；「不確定」＝證據不足。

## 0. 先講結論（資料模型一句話版）

「案件」在本系統只有一個真正的鍵：`quotations.quote_no`（文字）。**所有施工／登載類資料與案件的關係都是鬆散文字欄位，沒有 FK**：

| 資料 | 與案件的關係 | 證據 |
|---|---|---|
| `work_logs.case_no` | 文字、預設 `''`、後端不驗存在也不驗可見 | `backend/db.py:1573-1574`；`backend/routers/system.py:665-669`（只檢查是字串）、`:683-712`（建立時完全不查案件） |
| `case_updates.quote_no` | 文字，端點有 `_guard_case` | `backend/db.py:1559-1567`；`backend/modules/case/api/quotations.py:5825-5832` |
| `daily_tasks.case_no` | 文字（「loose FK」） | `backend/modules/daily_tasks/api.py:59` |
| `case_stage_visits.stage_id` | 真 FK → `case_stages`（再由 `quote_no` 掛案件） | `backend/db.py:1837-1845` |
| `dev_logs.case_id` | FK → `dev_cases`；`dev_cases.converted_quote_no` 才是接到報價單的文字鍵 | `backend/db.py:1536-1551`、`:1523-1534` |
| `customers.data_json.visits[]`／`suppliers.data_json.visits[]` | **完全與案件無關**（掛客戶／供應商）；唯一例外是業務開發記錄會把 `【案名】` 寫進內容文字 | `backend/routers/customers.py:117-143`；`backend/modules/crm/api.py:174-216` |
| `completion_notes.quote_no` | 文字，建立時驗報價單存在 | `backend/db.py:3687-3690`；`backend/modules/case/api/completion_notes.py:432-436` |
| `case_extra_expenses.quote_no` | 文字，空字串＝無案件（哨兵 `-`） | `backend/db.py:3566-3568`；`backend/modules/case/api/case_extra_expenses.py:308-320` |
| `case_action_items.quote_no` | 文字 | `backend/db.py:2177-2180` |

案件頁（`case-management.html`）支援的深連結只有 `?q=<quote_no>` 與 `?tab=<biz|exec|dispatch|shipping|completion|feed|fin|xexp|allfiles>`（`frontend/js/case-management-core.js:90-100`、`:172-181`）。**沒有執行管理子頁籤（進度／材料申請／設備／保固／待辦／成員）的深連結**（`execSubTab` 只在 `core.js:60,935`、`exec.js:1172`、`close.js:68` 設定，不讀 URL）。

---

## 1. 工作日誌 `work-log.html`

| 項目 | 內容 |
|---|---|
| 頁面 | `frontend/pages/work-log.html`（471 行）；選單權限鍵 `work_log`（`frontend/static/sidebar.js:596`、`backend/core/menu_l1.json:92`） |
| 資料表 | `work_logs`：`id, log_date, user_id(FK users), content, hours, created_at, created_by`，後加 `case_no TEXT ''`（`db.py:1573`）、`photos TEXT '[]'`（`db.py:2195-2196`）、`contact_type TEXT ''`（`db.py:2268-2269`）；基表 `db.py:745-754` |
| API | `GET /api/work-logs`（`routers/system.py:591`，可篩 `date/month/user_id/case_no`）；`POST /api/work-logs`（`:674`，支援 `Idempotency-Key`）；`PUT /api/work-logs/{wid}`（`:715`）；`DELETE /api/work-logs/{wid}`（`:751`）；`POST /api/work-logs/{wid}/photos`（`:778`）；`DELETE …/photos/{photo_id}`（`:842`） |
| 權限 | 讀寫皆 `require_any_module(user, ('work_log','case_manage'))`（`system.py:600,684,718,753`）；改／刪別人的：限 admin+（`:724-726,758-760`）；替別人建立／改記錄對象：限 superadmin（`:694-696`、`:735-739`） |
| 誰寫／誰讀 | 寫：持 `work_log` 或 `case_manage` 者；讀：同一把，**GET 沒有依 case 做 row-level 檢查**（`system.py:591-625` 只看模組）。預設角色樣板 工務／業務／採購／PM／財務皆含 `work_log`（`backend/core/migrations.py:421-427`） |
| 與案件的連結 | 只有選填文字 `case_no`。**本頁本身無任何案件欄位**：表單只有 日期／工時／出勤人員／工作內容（`work-log.html:275-301`），送出的 body 就是 `form`（`:432`），不含 `case_no`；列表欄位 出勤人員／工時／內容／建立時間（`:221-225`），不顯示 `case_no`、`contact_type`、`photos` |
| 需重打（本頁） | 案名／客戶／案號完全無法在本頁帶入或選取；人員預設自己（`:398`）、日期預設檢視日（`:397`）算有預填；工時預設 8（`:399`） |
| 深連結帶上下文 | 無。`init()` 不讀 `location.search`（`:342-350`）；只有「前一天／後一天／今天」。儀表板活動流與檔案中心都連到 `work-log.html`（無日期、無 id）：`modules/analytics/api/dashboard.py:908`、`routers/system.py:972` |
| 從案件頁建立 | **有，但走另一條路**：案件頁「動態」分頁的發文框（`case-management.html:3630-3696`）填了 執行時數／聯絡事項／改日期／指定記錄對象 任一項，就改 `POST /api/work-logs` 並帶 `case_no=selected.quote_no`（`frontend/js/case-management-feed.js:168-173,235-249`）；照片另打 `/api/work-logs/{id}/photos`（`feed.js:251-260`）。案件資訊（案號）自動帶入；客戶、案名不需打 |
| 斷點 | ① 在 `work-log.html` 建的日誌永遠 `case_no=''`，案件動態與專案報告看不到它（`quotations.py:5869-5876` 只撈 `WHERE w.case_no=?`、`pdf_gen.py:3151-3156` 同）。② 案件來源的日誌在本頁看不到是哪個案件、也看不到照片（`:229-246`）。③ 案件動態裡的工作日誌 `canDelete:False`（`quotations.py:5888`），案件頁無編輯／刪除，要刪必須回 `work-log.html`——但該頁又認不出是哪案。④ 發文框「純文字」走 `case_updates`、「填時數」走 `work_logs`，同一個框兩種資料表，使用者看不出差異（`feed.js:160-173`）。⑤ 補登日期但沒填時數時 `hours` 被塞成 8（`feed.js:245`，已證）。⑥ `case_no` 不驗存在、不驗呼叫者看得到該案（`system.py:683-712`） |

## 2. 每日工作事項 `daily-tasks.html` + `modules/daily_tasks`

| 項目 | 內容 |
|---|---|
| 頁面 | `frontend/pages/daily-tasks.html`（3769 行）；選單群組 mywork、權限鍵 `daily_task`（`backend/modules/daily_tasks/module.json` pages 區） |
| 資料表 | `daily_tasks`（`task_date,title,description,category,priority,assigned_to JSON,supervisors JSON,recurrence_*,case_no,is_deleted…`）、`daily_task_completions`（`task_id,username,occurrence_date,completed,report,completed_at`，UNIQUE(task,occurrence,user)）、`daily_task_edit_log`；`db.py:842-869`、`modules/daily_tasks/module.json` tables |
| API | `GET /api/daily-tasks`（`api.py:301`，可 `case_no=` 篩）、`GET /{id}`(`:395`)、`POST`(`:416`)、`PUT /{id}`(`:469`)、`DELETE /{id}`(`:549`)、`GET /{id}/history`(`:574`)、`GET /{id}/edit-log`(`:687`)、`PATCH /{id}/complete`(`:871`)；外部提供者 `_external_upsert`(`:1148`，IP-5) |
| 權限 | `require_any_module(('daily_task','case_manage'))`（`api.py:310,398,419…`）。**建立／修改／刪除限 superadmin**（`:420-421,473,553`）；一般人只能對「被指派給自己」的事項回報完成（`:880-884`）；非 superadmin 列表只看得到自己負責或監督的（`:233-241`） |
| 誰寫／讀 | 寫（建任務）：僅最高管理者；寫（完成回報）：被指派人；另有**系統自動建立**：勾選案件階段完成時由 `case_stage_tasks.py` 透過 `daily_task.external` 建一筆已完成的任務（`case_stage_tasks.py:77-130`），`case_no=quote_no`、負責人＝階段負責人或勾選者 |
| 與案件的連結 | `case_no` 文字。建立表單的「關聯案件」下拉來自 `/api/sales-orders` 且只列 `dealTag==='已成案'`（`daily-tasks.html:2350-2358`、`:2646-2657`）；列表上只把 `case_no` 當純文字標籤顯示（`:1690-1692`、`:1756-1758`），不是連結 |
| 需重打 | 標題、說明、分類、日期、負責人皆手打；案名／客戶需從下拉選（下拉列的是「案號 客戶 專案名」）；沒有「材料／設備／階段」的帶入 |
| 深連結 | 只讀 `?username=`（僅 superadmin，且要先解鎖管理視角）（`:2626-2636`）。**不收 `case_no`／`date`／`task` 之類參數**；`openCreate()` 一律空白（`:2995-3004`） |
| 從案件頁建立 | **不能新建**。案件頁底部「今日相關任務」條（`case-management.html:3787-3885`）只列「今天、`case_no`＝本案」的任務（`feed.js:34-49`），可「提交回報／查看記錄」（`feed.js:312-347`）；連結「前往工作事項 →」`../pages/daily-tasks.html` 不帶任何參數，且只在目前有任務時才出現（`:3878-3883`）。案件動態另外把「完成的任務」合併顯示（`quotations.py:5891-5909`） |
| 斷點 | ① 只有 superadmin 能建任務 → 現場／工務無法從案件掛一個「待做事項」（只能用案件的「待辦事項」，見 §8）。② 案件頁沒有「新增工作事項（預填本案）」；daily-tasks 也不接收案件上下文。③ 只列「今天」的任務，過去／未來掛本案的事項在案件頁看不到（`feed.js:39-40`）。④ 事項完成回報 `report` 與 工作日誌 `content` 兩處各打一次同樣的「做了什麼」 |

## 3. 業務開發記錄（dev log）`dev-crm.html` + `modules/crm`

| 項目 | 內容 |
|---|---|
| 頁面 | `frontend/pages/dev-crm.html`（2518 行）；權限鍵 `dev_crm`（`modules/crm/module.json` permissions）；批示另有能力 `crm.dev_log_directive.comment`（同檔 capabilities） |
| 資料表 | `dev_cases`（`case_name,customer_name,customer_id FK customers,status,sales_persons,planners,converted_quote_no,…`，`db.py:1523-1534`）；`dev_logs`（`case_id FK,log_date,log_by,channel,content,next_action,status_snapshot,needs_approval,approved_*,created_*`＋`files_json`，`db.py:1536-1551`、`:118`）；`dev_case_progress`、`dev_log_directive`、`dev_log_directive_target`（`crm/migrations/0003,0004`；設計 `docs/platform/plans/DEV-LOG-DIRECTIVE-PLAN.md`） |
| API（前綴 `/api`，`crm/api.py:26`） | `GET /dev-cases/{id}/logs`(`:1120`)、`POST /dev-cases/{id}/logs`(`:1140`，multipart，可附檔)、`PUT /dev-logs/{id}`(`:1235`)、`DELETE /dev-logs/{id}`(`:1267`)、`PATCH /dev-logs/{id}/approve`(`:1339`)；`PATCH /dev-cases/{id}/convert`(`:851`，寫 `converted_quote_no`)；批示 `GET/POST /dev-cases/{id}/directives`(`:1470,:1482`)、回覆 `POST …/replies`(`:1557`) |
| 權限 | `_require_dev`：admin+ 或 `dev_crm`（`crm/api.py:127-131`）＋ row_access `dev_case`（`:137-143`）。`log_by` 不是自己 ⇒ `needs_approval=1`（`:1170`） |
| 誰寫／讀 | 業務／企劃／被指派人／建立者（`DEV_CASE_ACCESS`，`:137-143`）；admin+ 全看 |
| 與案件的連結 | 開發階段掛 `dev_cases`；**轉成報價單後才用 `converted_quote_no`（文字）接到案件**（`:851-887`，且 409：已連結者要改走審核）。接上後：①案件「動態」分頁唯讀合併顯示這些記錄與狀態變更（`quotations.py:5911-5953`，`canDelete:False`）；②每筆記錄會同步寫進客戶 `visits[]`（`crm/api.py:1216`、`:174-216`）；③跨案時間軸用它畫「業務開發」區段（`quotations.py:1087+` 的 `devStart/devEnd`） |
| 需重打 | 建案件時客戶名可選客戶管理名單帶入 `customer_id`（`dev-crm.html:1250-1267,2186`）。建報價單時 `doConvert()` 開新分頁 `quotation-form.html?customer=…&project=…`（`dev-crm.html:2430-2437`）；**但 `quotation-form.html` 只讀 `id／copy／reviewEdit` 三個參數**（`quotation-form.html:4949-4953,5083`），`customer`／`project` 參數無人讀取（已證：該檔搜尋不到 `get('customer')`），等於預填失效，需手打 |
| 深連結 | `dev-crm.html` 的連結：`quotation-form.html?id=<converted_quote_no>`（`:822`，開新分頁）。案件頁沒有回到開發記錄的連結（`case-management.html` 全檔無 `dev-crm.html`） |
| 從案件頁建立 | 不能（動態分頁只讀）；要加開發記錄須回 `dev-crm.html` 重新找案件 |
| 斷點 | ① 轉案後的跟進記錄要在 `dev-crm.html`（案件頁無入口）。② `dev_logs` 與 `customer visits` 雙寫（`crm/api.py:1216`），內容改在別處不回寫。③ `dev_logs` 非 append-only（PUT／DELETE 原地覆寫／硬刪，設計文件 §0 自述） |

## 4. 客戶日誌 `customer-log.html`／供應商日誌 `supplier-log.html`

| 項目 | 客戶日誌 | 供應商日誌 |
|---|---|---|
| 頁面 | `frontend/pages/customer-log.html`（801 行），由 `customers.html` 的「日誌」按鈕進入：`customers.html:304,398,510,517,538,547` | `frontend/pages/supplier-log.html`（777 行），由 `suppliers.html:252,357,364,385` |
| 資料 | **不是獨立表**：`customers.data_json.visits[]`（整包陣列覆寫） | `suppliers.data_json.visits[]` |
| 欄位 | 日期／類型（現場拜訪／電話聯繫／視訊會議／電子郵件）／出席人／內容／聯絡備註／備註（`customer-log.html:703-735`） | 同型（往來紀錄） |
| API | `GET /api/customers`（`customer-log.html:610`，整包撈再前端 find）；`PATCH /api/customers/{cid}/visits`（`routers/customers.py:117`） | `GET /api/suppliers`（`supplier-log.html:602`）；`PATCH /api/suppliers/{sid}/visits`（`modules/supply/api/suppliers.py:196`） |
| 權限 | `require_any_module(('customer','case_manage','dev_crm','procurement'))`（`customers.py:119`） | `perm.require("supply.supplier.edit")`（`suppliers.py:199`）；**`GET /api/suppliers` 對非 admin／superadmin 一律回 `[]`**（`suppliers.py:84-85`）→ 一般採購開 `supplier-log.html` 會找不到供應商而被導回 `suppliers.html`（`supplier-log.html:605-606`，推測：由程式碼推出，未實測） |
| 與案件連結 | **無**。頁內全無 case／quote 欄位或連結（grep 無命中）；案件頁也沒有連到客戶日誌或供應商日誌（`case-management.html` 無 `customer-log`／`supplier-log`） | 無；案件頁材料卡的「廠商名稱」是自由文字（`case-management.html:1196-1198`），不連 `suppliers` |
| 深連結 | 只收 `?id=<客戶id>`，缺則導回 `customers.html`（`customer-log.html:601-603`） | 同（`supplier-log.html:593-595`） |
| 斷點 | PATCH 送整包 `visits`，頁面沒帶 `expectedUpdatedAt` 樂觀鎖（`customer-log.html:783-787`），與業務開發記錄的自動寫入（`crm/api.py:218+`）可能互蓋（推測）。與施工無關但被使用者視為「又一個紀錄地方」 | 同上 |

## 5. 案件完工單 `completion_notes`（API）＋ `completion-note-form.html`

| 項目 | 內容 |
|---|---|
| 頁面 | 填寫頁 `frontend/pages/completion-note-form.html`（787 行）；清單在案件頁「完工單」分頁（`case-management.html:3473-3570`） |
| 資料表 | `completion_notes`：`note_no UNIQUE, quote_no, status, customer_name, project_name, site_address, start_date, completion_date, site_manager, recipient, items_json, work_summary, test_result, warranty_months, pending_items, notes, data_json, is_signed…`（`db.py:3687-3716`、`contact_phone` 見 `:3734`） |
| API（`modules/case/api/completion_notes.py`） | `GET /api/completion-notes`(`:250`，帶 `quote_no` 走案件守門)、`GET …/quote-items`(`:358`)、`GET /{no}`(`:408`)、`POST`(`:418`)、`PUT`(`:466`)、`DELETE`(`:519`)、`POST /{no}/submit`(`:552`)、`/approve`(`:618`)、`/reject`(`:730`)、`/revoke-approval`(`:773`)、`GET /pdf-download`(`:820`)、`POST /signed-toggle`(`:875`)、`/signed-files`(`:927`) |
| 權限 | 讀：`guard_case_access(allow_module="case_manage")`（`:254-258,275-292`）；**建立／編輯／刪除／送審／帶入項目皆 `_require_admin`（admin+）**（`:364,421,469,522,557`），核准走分層簽核；UI「新增完工單」鈕同樣限 admin+（`case-management.html:3484`） |
| 誰寫／讀 | 寫：管理員（現場工程師預設不能開）；讀：案件可見者 |
| 與案件連結 | `quote_no` 文字，建立時驗報價單存在（`:432-436`）。`completion_sync.py`（純函式）從報價單抓品項（只放行 `id,type,description,brand,qty,unit`，不含金額，`completion_sync.py:12-17`），並算「已完工數」跨單累計（`:121`） |
| 自動預填 | 新增時：客戶／案名／地址／聯絡人／電話／報價品項由 `prefillFromCase()` 帶（`completion-note-form.html:458-470`，資料來自 `/api/completion-notes/quote-items`）；完工日＝今天、現場負責人＝登入者（`:467-468`） |
| 需重打 | **開工日 `start_date`、施工摘要 `work_summary`、測試結果、遺留事項皆手打**——不引用本案的階段出勤（`case_stage_visits`）、工作日誌（`work_logs`）、設備登錄（`caseRecord.devices`）、材料到貨；`start_date` 未預填（`:458-470` 沒設）。保固月數預設 12、與設備登錄每台的 `warrantyStart/warrantyMonths`（`case-management.html:1344-1354`）是**兩份獨立輸入**，docstring 明寫刻意不自動建立保固追蹤（`completion_notes.py:15-17`） |
| 深連結 | 進入：`?q=<quote_no>`（新）／`?no=<note_no>`（既有）（`completion-note-form.html:411-415`；案件頁連結 `case-management.html:3485,3528,3533`）。返回：「← 回案件」只帶 `?q=`（`completion-note-form.html:53`），**不帶 `&tab=completion`** → 回到的是「案件資訊」分頁而非完工單分頁（推測：`tab` 預設 biz，見 `core.js:90-100`）。核准通知連結亦只到 `case-management.html?q=…`（`completion_notes.py:461-463`） |
| 從案件頁建立 | 有：分頁頂部「新增完工單」（admin+）→ 帶 `?q=` |
| PDF | `completion_pdf.py` 只讀 `completion_notes` 那一列（`completion_pdf.py:306-311`）；`completion_sync.py`、`completion_pdf.py` 不查工作日誌／出勤／設備 |
| 斷點 | 見 §10 #3 |

## 6. 案件待辦事項 `case_action_items`

| 項目 | 內容 |
|---|---|
| 頁面 | 無獨立頁，在案件頁「執行管理 → 待辦事項」子頁籤（`case-management.html:903,1494-1533`） |
| 資料表 | `case_action_items`：`quote_no,text,status(pending/stage1_done/done),stage1_approver/at,stage2_approver/at,sort_order,created_by…`（`db.py:2177-2192`） |
| API（`modules/case/api/case_action_items.py`） | `GET /api/quotations/{quote_no}/action-items`(`:89`)、`POST`(`:109`)、`PUT /{id}`(`:137`)、`DELETE /{id}`(`:173`，僅 admin+)、`PATCH /{id}/approve`(`:193`，兩階段：工程主管→業務主管) |
| 權限 | `_guard_action_item_case`（superadmin／`project_approve_eng|biz`／該案業務的部門／處主管直通，其餘走 `guard_case_access(case_manage)`，`:48-67`）；確認權限 `:204-213` |
| 與案件連結 | `quote_no` 文字；審核者由案件業務 → 部門 → 主管推導（`:22-45`） |
| 需重打 | 只有一個純文字 `text`；沒有負責人、日期、關聯階段、關聯材料／設備欄位 |
| 深連結 | 無（子頁籤不可由 URL 指定） |
| 與其他紀錄關係 | 與「每日工作事項」「階段」並存但互不引用；專案報告 PDF 會列（`pdf_gen.py:3139-3149`） |
| 斷點 | 無負責人／到期日，等於清單備忘，與 daily-tasks 的「有人負責的待辦」二選一，使用者不易分辨 |

## 7. 外勤手機端點 `field_cases.py`

| 項目 | 內容 |
|---|---|
| 頁面 | **無**。本 worktree `frontend/` 沒有任何檔案呼叫 `/api/field/`（grep 無命中）；`docs/platform/prod-tasks/20261112-t80-apply.md:23,133` 自述「目前沒有任何畫面使用它（給之後的外勤手機用）」 |
| API | `GET /api/field/cases`(`field_cases.py:204`)、`GET /api/field/cases/{quote_no}`(`:298`)，唯讀、白名單欄位（案號、客戶、案名、狀態、業務、地址、聯絡人／電話、階段清單、最後動態時間） |
| 權限 | 案件成員制（admin／業務／`assigned_user_ids`／`caseRecord.roles`／階段負責人），不吃 `case_manage` 放行（`:16-24`） |
| 寫入能力 | **無任何寫入**（沒有日誌、叫料、回報端點）；只有同批新增的 `Idempotency-Key` 與案件檔案端點在 `quotations.py`（T80 文件 `:47`） |
| 斷點 | 外勤要在現場登載（日誌／照片／叫料）時，目前沒有任何 UI；手機只能開桌面頁面 |

## 8. 案件階段：`case-stage-board.html`、階段出勤（visits）、`case_stage_tasks.py`

注意：`case_stage_tasks.py` **不是**看板，它是「勾選階段完成 → 在每日工作事項建一筆已完成任務」的鏡射（見 §2）。

| 項目 | 看板 `case-stage-board.html` | 階段出勤（案件頁「執行進度」） |
|---|---|---|
| 頁面 | `frontend/pages/case-stage-board.html`（749 行），選單「案件執行看板」，權限 `case_manage`（`modules/case/module.json` pages） | 案件頁 執行管理→執行進度，`case-management.html:979-1110`（visit 列 `:1077-1107`） |
| 資料 | 唯讀攤平 `case_stages` JOIN `quotations`（已成案），含 `visit_start/visit_end`（`quotations.py:1087-1190`） | `case_stage_visits(stage_id, visit_date, visit_people INT, note, created_at)`（`db.py:1837-1845`） |
| API | `GET /api/quotations/stage-board`(`quotations.py:1087`)；指派 `POST/DELETE /api/quotations/{no}/stages/{id}/assignees`(`quotation_stages.py:347,375`，看板 `case-stage-board.html:497`) | `POST/PUT/DELETE /api/quotations/{no}/stages/{sid}/visits[/{vid}]`(`quotation_stages.py:431,457,488`) |
| 權限 | 看板列表走 `row_access.filter_sql("case", scope="read")`（`quotations.py:1118-1121`） | `_guard_case(allow_module="case_manage")`＋案件鎖定檢查（`quotation_stages.py:437-439`） |
| 與案件連結 | `quote_no` | 階段 FK，階段再掛 `quote_no` |
| 需重打 | 看板不能新增記錄；只有「只看我的」「指派」（`:196,247-263`） | **「新增記錄」送空 body**（`exec.js:1019-1029` → `POST …/visits` `{}`）：前往日期空、人次 0、內容空（`quotation_stages.py:441-446`）。日期、人數、人名、內容全手打；沒有人員欄（只有「人次」整數）、沒有工時 |
| 深連結 | `openCase()` → `case-management.html?q=<quoteNo>`（`:483-485`）：**只帶案號，不帶階段，也不帶 `tab=exec`**，落在「案件資訊」分頁 | 無 |
| 斷點 | 同一件「某天某人去現場做了什麼」可能存在三處：階段出勤（日期＋人次）、工作日誌（日期＋人＋工時）、動態留言；三者互不引用。專案報告 PDF 對階段出勤只取最早／最晚日期（`pdf_gen.py:3107-3108`），人次與內容不進報告；階段出勤也不進案件「動態」 |

## 9. 額外支出與費用單據（請購／採購／差旅／零用金）

「叫料」在系統裡實際是一條**跨三個畫面**的鏈：請購單（PR）→ 採購單（PO）→ 材料申請（叫料單，簽核＋到貨確認）→ 案件頁材料卡 → 設備登錄。

| 項目 | 內容 |
|---|---|
| 頁面 | ①案件頁「額外支出」分頁（`case-management.html:663-669,1568+`，`canSeeFinancial()` 才顯示）＝舊式額外支出（`kind=''`）；②**`payment-request.html`「新增支出申請」**（選單群組 mywork、權限 `quotation`，`modules/case/module.json:359-368`）＝建 請購／採購／差旅／零用金 單據（`expense_forms.py:19-20` `KINDS`）；③案件頁財務分頁 `#fin-material-orders`「材料申請」（`case-management.html:2440+`）；④案件頁執行管理→「材料申請」子頁籤（材料卡，`:1126-1255`） |
| 資料表 | `case_extra_expenses`（`quote_no,category,description,qty,unit,unit_cost,total_cost,expense_date,doc_no,files_json,status,approval_json`，另有 `kind,doc_code,data_json,lines_json,department_id,payee_*,planned_pay_date…`；`db.py:3566-3589`、`case_extra_expenses.py:511-540`）；材料申請存 `quotations.data_json.caseRecord.materialOrders`（`material_orders.py:1-24` 自述無獨立表）；材料卡存 `caseRecord.materials`（`exec.js:1076-1078`） |
| API | 額外支出／費用單據：`GET/POST /api/quotations/{no}/extra-expenses`(`case_extra_expenses.py:385,499`)、`PATCH …/{id}`(`:565`)、`submit/approve/reject/void/files`(`:918,1006,1094,859,1209`)、`GET /api/extra-expenses/cases`(`:643`，挑案件)、`GET /api/extra-expenses/mine`(`:716`)；請購／採購挑選器 `GET …/purchase-items`(`:458`)、`…/purchase-requests/lines`(`:482`)。材料申請：`PATCH/GET /api/quotations/{no}/material-orders`(`material_orders.py:80,251`)、審核 `material_approvals.py:149-297`、到貨 `POST …/{item_id}/receive`(`:297`)、採購單帶入 `GET …/material-coverage`(`material_links.py:37`) |
| 權限 | 費用單據建立：登入＋案件可見（`_guard_case`，`case_extra_expenses.py:308-320,515`）；無案件單需 admin+ 或 `expense_forms`（`:303-305`）。**選單入口需 `quotation` 模組**（`module.json:359-368`）；預設「工務」樣板無 `quotation`（`backend/core/migrations.py:423`）→ 預設工務看不到「新增支出申請」入口，也看不到案件頁「額外支出」分頁（`case-management.html:663`）（推測：依預設角色樣板推論，實際看個別授權） |
| 與案件連結 | `quote_no` 文字；材料卡 ↔ 材料申請靠手選下拉 `mat.orderItemId`（`case-management.html:1159-1169`）或「已核准採購單帶入並連結」按鈕（`:1164-1171`），並有認列欄 `mat.poLink`（`:1172-1176`） |
| 需重打 | 在 `payment-request.html` 要**重新搜尋並點選案件**（`:91-95`、`:417-420`）；案件頁材料卡「從報價單匯入」可帶品名／型號／數量／單位（`exec.js:1086-1094`），但廠商（`mat.supplier`）、預計到料日（`mat.expectedDate`）要手打（`case-management.html:1196-1201`）；到貨日可能在兩處各填：材料申請的「到貨確認日期」（`material_approvals.py:297-308`）與材料卡「到貨日」`mat.poLink.arrivedOn`（`case-management.html:1174`）（推測：兩欄語意相近，未驗證是否同步） |
| 深連結 | `payment-request.html` 只讀 `?tab=mine`（`:408`），**不讀 `quote_no`**；全 repo 沒有任何前端連結指向 `payment-request.html`，只有通知連結 `payment-request.html?tab=mine`（`case_extra_expenses.py:910,970,1082,1141,1715,1784`；`expense_notify.py:129-153`） |
| 從案件頁建立 | 舊式「額外支出」：**可**（案件頁 `＋新增支出`，`xexp.js:87-98` 預填日期＝今天、填寫人＝登入者）；請購／採購／差旅／零用金：**不可**。案件頁材料申請寫明「請先申請請購單、再申請採購單」（`case-management.html:2444,2505`）卻沒有跳到申請頁的按鈕 |
| 附帶（客戶端請款，非本主題但易混淆） | 案件頁財務分頁「申請請款單」→ `payment-request-form.html?quote_no=<案號>`（`case-management.html:1903`）：這是對**客戶**請款，與上列**支出**申請不同頁、不同表；案件頁**有**預帶案號 |

## 10. 斷點清單（嚴重度：高＝直接造成「叫料、紀錄、登載零散」；中＝增加重打或迷路；低＝體驗瑕疵）

1. **【高】叫料起點（請購單／採購單）在案件頁外，無入口也不吃案號。** 案件頁材料申請明寫「需先申請請購單、再申請採購單」（`case-management.html:2444,2505`），但沒有跳轉；`payment-request.html` 不讀 `quote_no`（`:408`，只讀 `tab=mine`）要重新搜尋案件（`:417-420`），全 repo 無連結指向它（見 §9）。預設工務樣板還看不到這個選單（`core/migrations.py:423` vs `module.json:359-368`，推測）。
2. **【高】「某天現場做了什麼」散在 4～5 個地方且互不引用。** 階段出勤 `case_stage_visits`（日期＋人次＋內容）、工作日誌 `work_logs`（日期＋人＋工時＋內容＋照片）、案件留言 `case_updates`、每日任務完成回報 `daily_task_completions.report`、客戶日誌 `visits[]`（業務開發雙寫）。使用者要在不同畫面重打同一件事（§1、§2、§8）。
3. **【高】完工單不吃施工資料。** 開工日／施工摘要／測試結果／遺留事項手打；不引用階段出勤、工作日誌、設備登錄；保固月數與設備保固起算日兩份獨立輸入且 docstring 明寫刻意不連動（`completion_notes.py:15-17`、`completion-note-form.html:458-470`）。完工單只有 admin+ 能建（`completion_notes.py:421`）。
4. **【高】`work-log.html` 與案件脫鉤。** 頁面無案件欄、不顯示 `case_no`／照片（`work-log.html:221-246,275-301`），API 雖支援 `case_no`（`system.py:683-712`）；在此頁建的日誌進不了案件動態與專案報告（`quotations.py:5869-5876`、`pdf_gen.py:3151-3156`）。案件頁看得到的工作日誌不可編輯／刪除（`quotations.py:5888`），回 `work-log.html` 又認不出案件。
5. **【高】案件頁沒有「統一登載」入口。** 動態分頁發文框混用 `case_updates`／`work_logs` 兩張表（`feed.js:160-173`）；新增階段出勤送空白（`exec.js:1019-1029`）；新增每日任務不可（§2）；開發記錄不可（§3）；完工單限 admin（§5）。同一個案件頁裡「紀錄」有至少 5 種不同入口。
6. **【中】深連結只到分頁層級，丟失子頁籤與物件。** `?tab=` 有效值不含執行管理子頁籤（`core.js:90-93`、`:60`）；看板 `openCase()`（`case-stage-board.html:483-485`）、設備頁／採購頁（`devices.html:210,250,315,326`；`procurement.html:143,149,184,194`）、完工單返回（`completion-note-form.html:53`）、完工單通知（`completion_notes.py:461-463`）都只帶 `?q=`，落在「案件資訊」分頁。
7. **【中】`daily-tasks.html` 不收案件上下文，且建任務限 superadmin。** 只讀 `?username=`（`daily-tasks.html:2626-2636`）；案件頁「前往工作事項」不帶參數且需先有任務才出現（`case-management.html:3878-3883`）；`POST /api/daily-tasks` 限 superadmin（`api.py:420-421`）。
8. **【中】`work_logs.case_no` 是未驗證的自由文字。** 不驗案件存在、不驗呼叫者可見該案（`system.py:665-669,683-712`）；`GET /api/work-logs` 對持 `work_log` 者不做逐案過濾（`system.py:591-625`）。
9. **【中】兩份材料清單靠手選下拉連結。** 材料卡 `caseRecord.materials` 與材料申請 `caseRecord.materialOrders` 以 `mat.orderItemId` 手選／按鈕連結（`case-management.html:1159-1176`）；到貨日疑似兩處輸入（`material_approvals.py:297-308` vs `case-management.html:1174`，推測）。
10. **【中】設備登錄／保固不帶資料。** `addDevice()` 空白（`exec.js:1192-1194`）、`warrantyStart` 預設空（同檔 `:1194`）；到料時只帶出 SN／MAC 欄位數量（`exec.js:1144-1152`）；案件頁「同步至設備登錄」要手動按（`case-management.html:1134-1139`）。
11. **【中】業務開發 → 報價單預填失效。** `doConvert()` 帶 `customer`／`project` 參數（`dev-crm.html:2430-2437`），`quotation-form.html` 不讀（`:4949-4953`）。
12. **【中】案件頁看不到客戶日誌與供應商日誌，且兩者與案件無鍵。** `case-management.html` 無 `customer-log`／`supplier-log` 連結；供應商日誌對非 admin 可能打不開（`suppliers.py:84-85`，推測）。
13. **【中】專案報告 PDF「叫料管控」欄位對不上材料卡。** PDF 讀 `spec／status／eta`（`pdf_gen.py:3130-3137`），材料卡實際欄位是 `name,model,qty,unit,ordered,arrived,expectedDate,supplier,note`（`exec.js:1078`；`case-management.html:1147-1201`）→ 狀態與到料日在 PDF 可能是空白（推測：靜態比對欄位名，未產出 PDF 驗證）。
14. **【中】外勤手機沒有寫入端點與畫面。** `field_cases.py` 全唯讀、前端無人使用（§7）。
15. **【低】完工單返回案件落在錯誤分頁**（`completion-note-form.html:53` 無 `&tab=completion`）。
16. **【低】客戶／供應商日誌整包覆寫、無樂觀鎖**（`customer-log.html:783-787`；`customers.py:117-143`）。
17. **【低】案件待辦事項無負責人／到期日**（`case_action_items.py:70-86`），與每日工作事項功能重疊。
18. **【低】補登日期未填時數時 hours 被塞 8**（`feed.js:245`）。
19. **【低】「今日相關任務」只列今天**（`feed.js:39-40`）。

## 11. 案件詳情頁現有的跳轉入口（`frontend/pages/case-management.html` ＋ `frontend/js/case-management-*.js`）

「傳遞的上下文」欄：案號＝`quote_no`；「無」＝純導頁。

| # | 位置（檔:行） | 目的頁 | 傳遞的上下文 | 備註 |
|---|---|---|---|---|
| 1 | `case-management.html:457` 空狀態按鈕 | `quotations.html` | 無 | 沒有選案件時的提示 |
| 2 | `:550` 標頭第二列「報價單」 | `quotation-form.html?id=<案號>` | 案號 | 開原始報價單 |
| 3 | `:672-673` 分頁列「精算 ▶」 | `settlement.html?no=<案號>` | 案號 | 僅 `canSeeFinancial()`；精算頁讀 `?no=`（`settlement.html:1314-1315`） |
| 4 | `:2757` 財務分頁「前往精算頁面 ▶」 | `settlement.html?no=<案號>` | 案號 | 同上 |
| 5 | `:702`、`close.js:126-131` 案件資訊「在地圖上看」 | `map.html?focus=cases:<案號>` | 案號（含類型前綴） | 需地圖模組＋有地址 |
| 6 | `:3360` 出貨單列「在地圖上看」 | `map.html?focus=shipping_notes:<id>` | 出貨單 id | |
| 7 | `:705` 案件資訊「獎金分配」 | `bonus.html?q=<案號>` | 案號 | 獎金模組開啟時 |
| 8 | `:708` 案件資訊「傳票 …」 | `voucher.html?id=<傳票 id>` | 傳票 id | |
| 9 | `:1903` 財務分頁「申請請款單」 | `payment-request-form.html?quote_no=<案號>` | 案號 | 對客戶請款；有未存修改會擋（toast） |
| 10 | `:2244` 請款單列 | `payment-request-form.html?id=<請款單號>` | 請款單號 | |
| 11 | `:3149,3168` 派工單勞報單連結 | `payslips.html?q=<勞報單號>` | 單號 | 有權限才顯示 |
| 12 | `:3160` 派工「新增勞報單」 | `payslip-form.html?dispatchId=<派工 id>` | 派工 id | |
| 13 | `:4016` 派工視窗提示 | `vendor-contractors.html` | 無 | 無承攬商資料時 |
| 14 | `:3485` 完工單分頁「新增完工單」 | `completion-note-form.html?q=<案號>` | 案號 | 僅 admin+ |
| 15 | `:3528,3533` 完工單列「開啟／編輯」 | `completion-note-form.html?no=<完工單號>` | 單號 | |
| 16 | `:3879` 「今日相關任務」底部 | `daily-tasks.html` | **無** | 僅有任務時顯示 |
| 17 | `exec.js:1481-1507`、`case-management.html:1281` 設備登錄「網路架構規劃書」 | `network-plan-form.html?id=<規劃書 id>` | 規劃書 id（由案號查／建） | 先打 `/api/quotations/{no}/network-plan` |
| 18 | `:519-524`「更多 → 產生專案報告」 | 下載 PDF（非導頁） | 案號 | `GET /api/quotations/{no}/project-report-pdf`（`quotations.py:6465`） |
| 19 | `:688` 案件健康總覽關卡按鈕 `gotoGate()` | 同頁切分頁 | 關卡→分頁對照（`close.js:7-21,65-71`） | 不導頁 |

**案件頁沒有**指向以下頁面的任何連結：`work-log.html`、`customer-log.html`、`supplier-log.html`、`dev-crm.html`、`payment-request.html`、`case-stage-board.html`、`devices.html`／`warranty.html`／`procurement.html`（grep 無命中）。反方向（別的頁面連進案件頁）：`case-stage-board.html:484`、`devices.html:210,250,315,326`、`procurement.html:143,149,184,194`、`completion-note-form.html:53` 皆為 `?q=<案號>`（不帶 `tab`）。

### 案件頁分頁與子頁籤總覽（供對照）

頂層分頁 `case-management.html:642-674`：案件資訊(`biz`)／執行管理(`exec`)／承攬商(`dispatch`)／出貨單(`shipping`)／完工單(`completion`)／動態(`feed`)／全部附件(`allfiles`，檔案中心在才顯示)／財務(`fin`)／額外支出(`xexp`，財務角色)／精算（連結）。執行管理子頁籤 `:899-904`：執行進度／材料申請／設備登錄／保固備註／待辦事項／成員。分頁的可見度與順序可由版面設定調整（`tShown()`／`tOrder()`），以上為預設結構。

## 12. 未能確認／後續建議查證

- 「材料卡 ↔ 材料申請」兩個到貨日是否自動同步：未讀 `material_recognize.py`，僅由前端欄位推測。
- 專案報告 PDF 叫料管控欄位空白：未實際產出 PDF 驗證。
- 預設工務角色看不到「新增支出申請」：依 `core/migrations.py:423` 的樣板種子與 `module.json` 的選單權限推論；個別帳號可能另有授權。
- 側欄頁面層守門實作細節（`sidebar.js` 的 `ni()`／`_deniedPages`）未逐項展開。
