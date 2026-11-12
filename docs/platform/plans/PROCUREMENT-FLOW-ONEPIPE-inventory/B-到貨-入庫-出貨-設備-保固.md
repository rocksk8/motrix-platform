# 到貨 → 入庫 → 領料/出貨 → 設備登載 → 保固追蹤：現況調查

調查範圍：`D:\Claude-pm\h1-onepipe`（唯讀，未跑 pytest／server）。路徑縮寫：`BE=backend/`、`FE=frontend/`。
標示「（推定）」者為由程式碼推論、未實測；其餘皆有 file:line 佐證。

## 0. 總覽：這段流程在現況其實是兩條互不相連的軌

1. **案件軌（case-level）**：報價單 → 請購單(PR) → 採購單(PO) → 材料申請(叫料)＋審核 → 「確認到貨」→ 材料卡「已到料」＋序號 → 設備登錄 `caseRecord.devices[]`。資料都存在 `quotations.data_json`（JSON，無獨立表）＋疊加表 `case_material_approvals`、`case_extra_expenses`。
2. **庫存軌（stock-level）**：料號主檔(parts) → 庫存頁「進貨」建批次 → `stock_items`（序號級）＋`stock_batches`。出貨單核准會把序號扣成 `shipped`；設備登錄存檔會把序號認領成 `installed`。
3. 兩軌的唯一接點是「序號字串」：案件軌的設備 SN 若剛好等於 `stock_items.serial_no` 才會連動（`BE/modules/case/api/quotations.py:3314-3373`）。案件軌的材料卡只有自由文字品名/型號，沒有 `part_no`（`FE/js/case-management-exec.js:1090-1092`；case 模組 .py 內無 `part_no` 欄位）。

### 側欄入口（`menu_l1.json` 群組＋各 `module.json` 的 `pages[].menu`）

| 頁面 | 側欄群組 → 標籤（order） | perm | 來源 |
|---|---|---|---|
| 案件管理（到貨、出貨、設備登錄實際操作處） | 案件 → 案件管理（10） | `case_manage` | `BE/modules/case/module.json:337-345` |
| 供應商管理 | 採購與庫存 → 供應商管理（20） | `procurement` | `BE/modules/supply/module.json:103` |
| 料號主檔 | 採購與庫存 → 料號主檔（40） | `procurement` | `BE/core/menu_l1.json:80-89` |
| 庫存管理 | 採購與庫存 → 庫存管理（50） | `inventory` | `BE/modules/supply/module.json:110` |
| 採購管理（唯讀進度表） | 採購與庫存 → 採購管理（60） | `procurement` | `BE/modules/analytics/module.json:28` |
| 設備登載（唯讀） | 採購與庫存 → 設備登載（70） | `equipment` | `BE/modules/analytics/module.json:24` |
| 保固追蹤（唯讀） | 採購與庫存 → 保固追蹤（80） | `equipment` | `BE/modules/analytics/module.json:26` |
| 出貨單歷史紀錄（僅 PDF 匯出稽核） | 系統 → 出貨單歷史紀錄（100），另有系統中心卡片 | `shipping_export_log` | `BE/modules/supply/module.json:114,118-130` |
| 銷售訂單 | 無（已退役，只是轉址頁） | — | `FE/pages/sales-orders.html:19`（`location.href='case-management.html'`） |

觀察：側欄「採購與庫存」群組內的 4 個頁面（採購管理／庫存管理／設備登載／保固追蹤）全部不能做主要寫入動作（採購管理、設備登載、保固追蹤純唯讀；庫存管理只能建批次與調整），真正的「到貨」「出貨」「設備登載」都藏在「案件 → 案件管理」的子分頁裡。使用者從側欄看不出流程順序。

---

## 步驟 1：到貨（採購品進場）

案件軌的實際路徑：案件管理 →（財務分頁）材料申請 → 送審/核准 →「確認到貨」；再到（執行分頁 → 材料申請）勾「已到料」。

| 項目 | 內容 |
|---|---|
| 頁面 | 唯讀看板：`FE/pages/procurement.html`（只有 `GET /api/materials-summary`，`procurement.html:304`；每列只有連結「材料申請 →」`procurement.html:149` 導到 `case-management.html?q=`）。真正操作頁：`FE/pages/case-management.html`：①財務分頁「材料申請」區的送審／到貨日期＋「確認到貨」鈕（`case-management.html:2572-2589`、`case-management-exec.js:282-285`）；②執行分頁 → 材料申請子頁的「已申購」「已到料」勾選與設備序號/MAC 列（`case-management.html:1180-1215`）。 |
| 從上一步來的入口 | 上游 PR/PO 在案件的額外支出/單據區建立。材料卡下拉「已核准採購單・尚未申請材料」optgroup 選取即帶入草稿並連結（`case-management.html:1160-1167`）。procurement.html 的案件號與「材料申請 →」連到案件頁（不會定位到該材料）。 |
| DB 表／關鍵欄位 | `case_extra_expenses`（請購單 kind=`purchase_req`、採購單 kind=`purchase_order`；`status`、`doc_code`、`lines_json`、`quote_no`；`BE/db.py:3566`、`modules/case/migrations/0003_expense_forms.py:20`、`modules/case/expense_forms.py:18-19`）。`case_material_approvals`（PK `quote_no,item_id`；`doc_code`、`status`、`received_on/by/at`、`content_hash`；`modules/case/migrations/0004_material_approvals.py:14-35`）。叫料列存在 `quotations.data_json.caseRecord.materialOrders[]`（`itemName, quantity, unit, unitPrice, totalPrice, supplierId, quoteItemId, poDocCode, poLine…`；`modules/case/api/material_orders.py:60-68`）。材料卡存在 `caseRecord.materials[]`（`name, model, qty, unit, ordered, arrived, orderItemId, poLink, devices[], supplier, expectedDate`）。 |
| API | `GET /api/materials-summary`（`modules/analytics/api/dashboard.py:751`；狀態由旗標推出 `:778`）。`PATCH /api/quotations/{q}/material-orders`（`material_orders.py:80`，整份覆蓋）。`POST .../material-orders/{item}/submit`（`material_approvals.py:149`）、`/approve :199`、`/reject :224`、`/withdraw :248`、`/cancel :271`、`/receive :297`、`DELETE /receive :321`。`GET /api/quotations/{q}/material-po-lines`（`material_links.py:25`）。`PATCH /api/quotations/{q}/case-record`（`quotations.py:3598`，存材料卡旗標與序號）。 |
| 權限鍵 | 看板：`procurement` 或 `case_manage`（`dashboard.py:756`）。改叫料清單：admin／財務角色／`project_manage`，且需財務檢視權、案件未結案（`material_orders.py:127-136`）。送審：案件擁有者規則＋財務檢視權、未結案（`material_approvals.py:149-165`）。核准／退回：當層簽核人。到貨確認：案件擁有者規則（`material_approvals.py:297-310`），不簽核。 |
| 狀態值 | 材料申請：草稿／待審核／簽核中／已核准／已退回／已取消（`material_approval.py:29`）。到貨確認＝`received_on` 非空。材料卡旗標 `ordered`→`arrived`；procurement.html 顯示：待採購／已下單／已到料（`dashboard.py:778`）。PR/PO：草稿／待審核／簽核中／已核准／已駁回…（只計 待審核、簽核中、已核准；`recognition.py:416`）。 |
| 下一個該動的人 | 簽核人（當層）；核准後由案件擁有者／業務按「確認到貨」；再由同一人到執行分頁勾「已到料」並逐台填 SN/MAC。 |
| 重複輸入欄位 | ①品名、型號、數量、單位：材料卡可「從報價單匯入」（`exec.js:1086-1094`），但叫料列、PR、PO 各自存一份。②供應商：材料卡自由文字 `mat.supplier`（`case-management.html:1197`）、叫料列 `supplierId`（`:2523`）、庫存批次 `supplier_id`（`inventory.html:202`）三處各填。③到貨日：確認到貨填一次（`:2576`），認列採購單路徑 `poLink.arrivedOn` 再填一次（`:1174`）。④到貨後要在材料卡上再逐台打 SN/MAC（`:1210-1213`）。⑤料號 part_no：案件軌沒有，進庫存時才要選。 |
| 資料帶到下一步？ | 案件軌內部：有（叫料→`orderItemId` 連結材料卡；「已到料」勾選會依 qty 自動產生 N 個 SN 空列 `exec.js:1144-1151`；序號會同步到 `caseRecord.devices` `exec.js:1175-1192`）。**到庫存軌：完全沒有**——全 repo 唯一寫入 `stock_items` 的是庫存頁進貨 `inventory.py:468`（及舊資料回填 `db.py:2619`）。到貨確認不會建庫存批次。 |
| 批次？ | 材料卡勾「已到料」會依數量產生 N 列空白 SN/MAC，但仍須逐列手打；無貼上/匯入/掃碼。叫料／PR／PO 皆整份編輯，無 Excel 匯入。 |
| 斷點 | 見 §斷點清單 #1、#2、#3、#9、#10、#13。 |

另有「庫存補貨循環」的第二種到貨標記：庫存頁「採購建議」→「標記已下單」→「標記已到貨」（`inventory.html:385,388`）→ `POST /api/inventory/purchase-suggestions/{part_no}/status`（`inventory.py:278-352`），僅更新 `purchase_suggestion_status`（`db.py:4028`：`status, ordered_at, received_at…`），**不建立庫存、不連到任何 PO**。狀態：suggested→ordered→received（跳階 409，`inventory.py:279-306`）。

---

## 步驟 2：入庫 / 庫存

| 項目 | 內容 |
|---|---|
| 頁面 | `FE/pages/inventory.html`。入口：側欄「庫存管理」；頁內按鈕「進貨」`:104`、「進貨批次（供應商/付款）」`:102`、「採購建議」`:103`（僅低水位時顯示）；列上「查看序號」`:153`。**無任何來自案件管理或採購管理頁的「到貨→入庫」按鈕**（inventory.html 只對 suppliers.html 有一個連結 `:349`）。 |
| 從上一步來的入口 | 無。使用者必須自己想到去側欄開庫存頁。 |
| DB 表／欄位 | `stock_items`（`part_no, serial_no, mac, status, batch_no, cost, shipping_note_no, quote_no, case_device_id, consumed_at/by`；唯一鍵 `(part_no, serial_no)`；`BE/db.py:3170-3195`）。`stock_batches`（`batch_no PK, part_no, supplier_id, supplier_name, invoice_no, is_paid, paid_at…`；`db.py:2595-2610`）。`parts`（料號主檔）。 |
| API | `GET /api/inventory/parts-summary`（`inventory.py:53`）、`GET /api/inventory/stock-items`（`:354`）、`POST /api/inventory/batches`（`:412`，body：`part_no, serials[{serial_no,mac,note}], cost, supplier_id, invoice_no, note`）、`GET /batches :487`、`GET/PUT /batches/{no} :512/:526`、`POST /batches/{no}/paid-toggle :565`、`POST /stock-items/{id}/adjust :614`（void／return_to_stock／edit_note）、`DELETE /stock-items/{id} :671`。 |
| 權限鍵 | 讀：`inventory`／`procurement`／`case_manage`／`netplan_edit`（`inventory.py:56,357,415`）。**寫（建批次、調整、刪除）另加 `_require_admin`**（`inventory.py:46-50,416,533,618,675`）。側欄 perm 只有 `inventory`。 |
| 狀態值 | `stock_items.status`：`in_stock`／`shipped`／`installed`／`void`（`inventory.py:3-8`；`inventory.html:562` 標籤：在庫／已出貨／已登載／報廢）。批次：`is_paid` 0/1。 |
| 下一個該動的人 | 有權限的 admin 在庫存頁手動建批次；之後由出貨單簽核（→shipped）或案件設備登錄（→installed）改狀態。 |
| 重複輸入欄位 | 料號（要從 `/api/parts` 下拉選，與案件材料卡的自由文字品名無對應）、數量（`intake.qty`）、**每台 SN/MAC**（`inventory.html:221-222`）、供應商（`:197`，與材料申請 `supplierId` 不同欄）、發票號碼（`:205`）、單位成本（預設帶 parts.cost `:199`）。PO 號、案件號、到貨日、採購單金額一律沒有欄位可帶入。 |
| 資料帶到下一步？ | 只經序號字串：出貨單選序號（`case-management-shipping.js:236-279`）→ `items_json[].part_no/serials`；設備登錄 SN 與庫存序號同字串時認領（`quotations.py:3345-3354`）。 |
| 批次？ | 後端 API 一次收陣列（`inventory.py:421-436`）。前端只有「輸入數量 → 產生 N 個空列 → 逐列手打」（`inventory.html:213-226,587-591`），**無貼上多行、CSV/Excel 匯入、掃碼連續輸入**。 |
| 斷點 | #1、#11、#13、#15、#16。 |

---

## 步驟 3：領料 / 出貨

**現況沒有「領料」功能**：grep `領料|領用` 僅命中 procurement.html 的標語「已到料 可領用」與 purchase_items.py（註解），無任何領料單、無扣庫存的領用動作。庫存的消耗只有兩條：出貨單核准（shipped）、設備登錄認領（installed）。

| 項目 | 內容 |
|---|---|
| 頁面 | 案件管理 →「出貨單」分頁（`FE/pages/case-management.html:645` 分頁鈕；`:3306` 內容；`:3324-3326`「新增出貨單」鈕，僅 `superadmin/admin` 顯示）。出貨單彈窗 `:4225+`：按鈕「從報價單匯入品項」`:4308`、「從材料申請帶入」`:4312`、每列「選料號」序號挑選 `:4396`。`shipping-export-history.html` 只是 PDF 匯出稽核表（`FE/pages/shipping-export-history.html:154` 只 GET `/api/shipping-notes/export-history`，案件號連到 case-management），不是出貨作業頁。 |
| 從上一步來的入口 | 「從材料申請帶入」會列出「已核准＋已確認到貨」的材料申請與剩餘可出貨量（`BE/modules/case/material_shippable.py:23-52`、`shipping_notes.py:127-137`、`case-management-shipping.js:157-185`）。「選料號」會列庫存 `in_stock` 序號（`case-management-shipping.js:246-259`）。 |
| DB 表／欄位 | `shipping_notes`（`note_no, quote_no, status, ship_date, customer_name, project_name, recipient, delivery_address, items_json, data_json(approval), is_signed, signed_by/at, signed_files_json, export_count, export_log`；`BE/db.py:3015-3040,2721`）。`items_json[]` 列可帶 `materialLink{materialItemId,docCode,qty}` 或 `part_no+serials`、`quoteItemId`（`material_link.py:1-10`）。 |
| API | `GET/POST /api/shipping-notes`（`shipping_notes.py:102/:290`）、`PUT :327`、`DELETE :357`、`GET /material-shippable :127`、`GET /{no}/material-link-check :223`、`POST /{no}/submit :399`、`/approve :469`、`/revoke-approval :624`、`/reject :686`、`/export :757`、`/signed-toggle :791`、`/signed-files :848`、`GET /export-history :140`。報價品項已出貨數：`GET /api/quotations/{q}/item-shipped`（`material_approvals.py:103`）。 |
| 權限鍵 | 建／改／送審／匯出／回簽／帶入材料申請：全部 `_require_admin`（`shipping_notes.py:60-62,131,292,329,401,759,793`）。核准／退回：當層簽核人（`:469+`）。歷史頁：`shipping_export_log`（`:140-152`）。列表（帶 quote_no）：案件可見或 `case_manage`（`:102-125`）。 |
| 狀態值 | 草稿→待審核→簽核中→已核准（`shipping_notes.py:457,590,613`）；退回／撤銷核准→草稿（`:672,716`）；另有 `is_signed`（回簽）旗標。庫存連動：核准時 `in_stock→shipped`（`:596-599`）；撤銷核准會把 shipped 退回 in_stock（`:666-668`）。 |
| 下一個該動的人 | 管理員（admin）建單並送審 → 簽核人逐層核准 → 管理員上傳回簽檔／按回簽（`signed-toggle`）。核准後沒有任何系統動作指向「設備登載」。 |
| 重複輸入欄位 | 收件人、送貨地址（`ShippingNoteIn.recipient/delivery_address`，`shipping_notes.py:47-56`；客戶／案名只會自動從報價單補，收件人與地址不會）。品項：三種來源擇一（報價匯入／材料申請帶入／庫存序號），報價匯入的列用 `description/brand/qty/unit` 重新存一份（`case-management-shipping.js:189-209`）。若走庫存序號，要再從庫存挑一次料號與 SN（已在庫存頁輸入過）。 |
| 資料帶到下一步？ | 庫存序號列：`stock_items.shipping_note_no/quote_no` 被回填（`shipping_notes.py:596-599`）。材料申請列：只留 `materialLink` 數量，供「已出貨／占用」統計（`material_link.py:150-175`、`material_shipping_view.py`、`item_shipped.py`）。**不會**建立或標記 `caseRecord.devices`，出貨日也不會成為保固起算日（`devices` 於 shipping 檔案內 grep 無命中）。 |
| 批次？ | 序號挑選器可一次勾多個序號（`case-management-shipping.js:236-279`）→ 這是目前唯一的多選。報價單匯入／材料申請帶入可多列勾選匯入。 |
| 斷點 | #4、#5、#6、#8、#9、#11、#12。 |

---

## 步驟 4：設備登載

| 項目 | 內容 |
|---|---|
| 頁面 | **唯讀**：`FE/pages/devices.html`（唯一 fetch 是 `GET /api/devices`，`devices.html:401`；頁內只有「前往案件管理」連結 `:315,326`）。**可編輯處**：案件管理 → 執行分頁 → 「設備登錄」子頁（`case-management.html:901,1258+`）。 |
| 從上一步來的入口 | ①材料申請子頁在有已到料材料時出現「同步至設備登錄」鈕（`:1134-1139`、`exec.js:1153-1173`）；②填 SN/MAC 時 `autoSyncDevice` 自動建立設備列（`exec.js:1175-1192`）；③設備子頁「從報價單匯入」依品項數量建空設備列，單品項上限 50（`exec.js:1126-1137`）。出貨單核准**沒有**入口。 |
| DB 表／欄位 | 無獨立表。存 `quotations.data_json.caseRecord.devices[]`：`id, name, sn, mac, location, warrantyStart, warrantyMonths(預設 12), note, _matId, _devIdx, _groupId…`（`exec.js:1134,1162,1194`）。庫存側回填 `stock_items.case_device_id/quote_no`。 |
| API | 唯讀清單：`GET /api/devices`（`dashboard.py:484-545`，現算 `expiryDate/daysLeft`）。寫入：`PATCH /api/quotations/{q}/case-record`（`quotations.py:3598`），存檔時 `_sync_device_stock`（`quotations.py:3314`，呼叫處 `:3812`）diff 新舊序號：新增 SN→`stock.claim`、移除→`stock.release`（`inventory.py:717-744`）。 |
| 權限鍵 | `GET /api/devices`：`equipment` 或 `case_manage`（`dashboard.py:490`）。寫：案件成員規則（`quotations.py:3598+`，已結案需半解鎖，見下）。側欄「設備登載」perm=`equipment`，但該頁無寫入功能。 |
| 狀態值 | 設備無狀態欄。庫存側：`in_stock→installed`（`inventory.py:728-735`）。保固狀態由日期現算：已過期／30 天內／90 天內／保固中／無紀錄（`warranty.html` 的 `WB_BUCKETS`，`warranty.html:273-279`；後端 `daysLeft`）。 |
| 下一個該動的人 | 業務／案件成員（現場資料需人工填 location、保固起始、月數）。 |
| 重複輸入欄位 | **SN/MAC**：庫存頁進貨打一次、材料卡到貨打一次、設備列再確認一次（材料卡 SN 會自動同步到設備列，但庫存那次不會）。**設備名稱**：由材料卡品名帶入（可）；**客戶、案號**：靠案件自帶。**保固起始日**：不帶任何上游日期（到貨日 `received_on`、出貨日 `ship_date`、完工日 `completion_date` 皆不帶），預設空字串（`exec.js:1134,1162,1183,1194`），須手填或用「一鍵同步保固」。 |
| 資料帶到下一步？ | 保固追蹤與每日檢查直接讀 `caseRecord.devices[]`，所以設備一存檔即可被保固頁看到（FK 式「同一份 JSON」）。但只有填了 `warrantyStart` 與 `warrantyMonths` 才會被通知（見步驟 5）。 |
| 批次？ | 有部分：①「一鍵同步保固」對**全部設備**覆寫同一起始日與月數（`exec.js:1439-1446`，會蓋掉各台既有值）；②從報價單匯入一次建多個設備槽；③設備群組拖曳合併。**SN/MAC 仍逐台手打，無貼上多行／匯入**。 |
| 斷點 | #4、#5、#6、#7、#14、#15、#16。 |

---

## 步驟 5：保固追蹤

| 項目 | 內容 |
|---|---|
| 頁面 | `FE/pages/warranty.html`（純唯讀，只有 `GET /api/devices`，`warranty.html:250`；頁內僅「展開全部／收合全部」兩顆按鈕，案件號是純文字，**沒有連到案件的連結**，與 devices.html 不同；`warranty.html:101-102,170-175`）。設備側的「續保」「延長」沒有任何動作鈕。 |
| 從上一步來的入口 | 側欄「保固追蹤」（需 `equipment`）；設備登錄存檔後資料自動出現（同一來源 `GET /api/devices`）。 |
| DB 表／欄位 | 無表。資料＝`caseRecord.devices[].warrantyStart/warrantyMonths`；每日通知去重記號存在 settings：key `warranty_notif.{quote_no}_{sn}_{threshold}`（`BE/modules/case/case_deadlines.py:283`）。另：完工單 `completion_notes.warranty_months` 與 `completion_date`（`BE/db.py:3702`；`modules/case/api/completion_notes.py:145-152,172-176`）是**另一套保固**。 |
| API／排程 | `GET /api/devices`（`dashboard.py:484`）；儀表板保固統計 `dashboard.py:255-267`、報表 `modules/analytics/api/reports.py:620`。每日檢查：`run_daily_checks → _check_warranty_expiry`（`case_deadlines.py:236-306,399`；`system_checks.py` 只是舊入口 re-export，`system_checks.py:21`）。信件：`_send_warranty_expiry`（`helpers/email_notify.py:1735-1750`）；舊入口 `notify_warranty_expiry`（`email_notify.py:1715`，已不被每日檢查使用）。行事曆：`_sync_warranty_calendar`（`case_deadlines.py:322-361`，預設關）。 |
| 權限鍵 | 看：`equipment` 或 `case_manage`。通知：案件業務（`sales_person_id` 外鍵解出帳號）＋群組收件人（`email_notify.py:1735-1748`）。通知天數設定中心可調，預設 7／30（`helpers/alert_settings.py:44-48`）。 |
| 狀態值 | 已過期／30 天內／90 天內／保固中／無紀錄（缺保固資料）（`warranty.html:273-279`）。信件分「緊急」與「提前」兩級。 |
| 下一個該動的人 | 業務收到信 → 與客戶確認續保；系統沒有續保／展延動作，只能回案件管理手改 `warrantyStart/warrantyMonths`。 |
| 重複輸入欄位 | 保固起始與月數（見步驟 4）。完工單另填完工日＋保固月數（`completion_notes.py:15`，docstring 明寫「刻意**不**自動建立保固追蹤紀錄」，`db.py:3683` 同）。 |
| 資料帶到下一步？ | 無下一步。信件按鈕連到 `quotation-form.html?no=`（報價單頁，不是案件管理、不是保固頁；`email_notify.py:1744`）。 |
| 批次？ | 檢視端無批次動作；修改端見步驟 4。 |
| 斷點 | #7、#12、#14。 |

---

## 斷點清單（依嚴重度）

嚴重度：高＝使用者必須重做工作或資料會分岔；中＝需手動切頁／易漏；低＝邊界情況。

1. **【高】到貨不會變成庫存**。案件軌的「確認到貨」「已到料」（`material_approvals.py:297`、`exec.js:1144`）完全不寫 `stock_items`；全 repo 唯一入庫寫入點是庫存頁進貨（`inventory.py:412-485`，INSERT 在 `:468`）。使用者需另開側欄「庫存管理」重打料號、數量、每台 SN/MAC、供應商、發票。庫存頁「採購建議→標記已到貨」只改 `purchase_suggestion_status`（`inventory.py:278-352`），也不入庫。
2. **【高】「採購管理」與「設備登載」「保固追蹤」是純唯讀看板**（`procurement.html:304`、`devices.html:401`、`warranty.html:250`），側欄放在「採購與庫存」群組，但每個動作都得跳到案件管理子分頁；procurement.html 的「材料申請 →」只導到案件頁、不定位到該材料（`procurement.html:149`）。
3. **【高】到貨要兩次確認＋兩個頁籤**：先在財務分頁「確認到貨」（`case-management.html:2572-2589`），再到執行分頁勾「已到料」；沒做第一步會被後端拒絕（`material_guard.py:403-409`，錯誤碼 `receipt_missing`）。認列採購單路徑又另有到貨日欄（`case-management.html:1174`）。
4. **【高】出貨與設備登載對同一序號互相衝突**：出貨核准把序號設 `shipped`（`shipping_notes.py:596-599`）；設備登錄存檔只認領 `in_stock`（`inventory.py:728-735`），已出貨序號回「衝突」，前端只顯示一行訊息「N 個序號庫存狀態衝突」不阻擋（`case-management-core.js:813-822`）。現實順序「先出貨、再現場登載」在庫存序號路徑下必然報衝突；反向（先登載 installed 再出貨）則出貨核准 409（`shipping_notes.py:581`，「已不在庫」）。
5. **【高】出貨列「材料申請連結」與「庫存序號」互斥**（`material_link.py:64`，UI 在 `case-management.html:4396` 反灰）。走材料申請路徑可追數量卻無序號；走庫存序號路徑有序號卻不連材料申請／採購單。一條線上無法同時有「採購單→序號→出貨」的追溯。
6. **【高】出貨不帶入設備登載、不帶保固起算日**：shipping 相關檔案內沒有任何寫 `devices` 的程式；設備 `warrantyStart` 預設空（`exec.js:1134,1162,1183,1194`），不取到貨日、出貨日或完工日。完工單另有一套保固（完工日起算，`completion_notes.py:15,145-152`），且刻意不寫入設備（同檔 docstring）→ 同一台設備兩套保固來源、需重打。
7. **【高】保固通知與行事曆只掃 `已成案` 案件，不含 `已結案`**（`case_deadlines.py:248`、`:345`）。保固頁面卻標榜含已結案（`warranty.html:98` 副標「含已成案 / 已結案」）；案件一旦結案，保固到期信即停止。另外已結案案件改設備資料要先半解鎖、每筆排 superadmin 審核（`quotations.py:278-290,3598+`），補登保固成本高。
8. **【中】沒有領料功能**：grep 無領料／領用單；庫存消耗只能經出貨單核准或設備登錄認領。procurement.html 把「已到料」標成「可領用」（`procurement.html` 流程帶），但沒有對應動作。
9. **【中】認列採購單（poLink，T57）路徑的「已到料」沒有材料申請審核列，無法被出貨單「從材料申請帶入」**（推定：`material_shippable.py:39` 只收 `已核准`且 `received_on` 非空的材料申請列；poLink 設計為「不建立材料申請」，`material_recognize.py:3-6`）。procurement.html 仍顯示已到料（`dashboard.py:778`）。需實測確認。
10. **【中】不支援分批／實收數量**：`material_shippable.py:12-14,42` 預留 `received_qty` 欄位，但沒有任何 migration 建立（case migrations 0001–0009 無此欄），`receive` 端點只收 `receivedOn`（`material_approvals.py:297-310`、`exec.js:283`）→ 實收＝全部申請量，缺貨／短收只能靠改叫料單。
11. **【中】權限與入口不一致**：庫存頁「進貨」鈕無條件顯示（`inventory.html:104`），後端寫入需 admin（`inventory.py:416,533,618,675`），只有 `inventory` 模組勾選的使用者會點了才 403。出貨單建立／帶入材料申請／送審一律 `_require_admin`（`shipping_notes.py:131,292,401`），且按鈕以角色硬判斷（`case-management.html:3324`），未走模組勾選制。
12. **【中】死連結／誤導入口**：通知與信件指向不存在的 `shipping-notes.html`（`shipping_notes.py:323,393,843`、`helpers/email_notify.py:668,687,705,722`；`frontend/pages` 無此檔）；「出貨單歷史紀錄」只是 PDF 匯出稽核（在「系統」群組）；`sales-orders.html` 為轉址頁；保固信按鈕連到 `quotation-form.html`（`email_notify.py:1744`）；warranty.html 案件號不可點。
13. **【中】同一資訊多處重打**：供應商三欄（材料卡 `mat.supplier`、叫料列 `supplierId`、庫存批次 `supplier_id`）；品名／料號（案件軌自由文字、庫存軌 `part_no`，兩者無對應，`exec.js:1090-1092` 對比 `inventory.html:186`）；SN 在庫存、材料卡、出貨序號挑選（後者為選取，不算重打）、設備列。
14. **【中】保固通知設計漏洞**：去重鍵 `warranty_notif.{quote_no}_{sn}_{threshold}` 不含到期日（`case_deadlines.py:283`）→ 續保（改了起算日）後同門檻不再寄信（推定）；沒填 `warrantyStart` 或 `warrantyMonths` 的設備直接被略過（`case_deadlines.py:273-276`），只在保固頁顯示「無紀錄」，無主動提醒；鍵用 `sn or mac or name` 前 32 字，無序號同名設備會共用記號（推定）。
15. **【中】大量登錄效率低**：SN/MAC 全為逐台手打（庫存進貨 `inventory.html:221-222`、材料卡 `case-management.html:1212-1213`、設備列 `:1330+`）；無貼上多行、Excel／CSV 匯入、掃碼連續輸入。「一鍵同步保固」會覆寫全部設備（`exec.js:1439-1446`）無法只套用選取者；報價匯入設備槽單品項上限 50（`exec.js:1129`）。
16. **【低】序號認領只比對 `serial_no`、忽略 `part_no`**：`claim` 以 `WHERE serial_no=? ORDER BY id LIMIT 1`（`inventory.py:728`），但唯一鍵是 `(part_no, serial_no)`（`db.py:3188`）；不同料號相同序號時會認領到最舊的一筆。
17. **【低】庫存頁關聯欄只顯示文字**：`shipping_note_no || quote_no` 非連結（`inventory.html:262`），從庫存回查出貨單／案件需手動搜尋。

### 若要合併成單一管線（給提案參考，非本次調查範圍的結論）
最短的資料接縫：以「材料申請(叫料列)」為主鍵，到貨確認時一次選料號＋貼上 SN 清單 → 同時寫 `received_on`、建 `stock_items`（`batch_no` 帶 PO/叫料單號與供應商）→ 出貨單核准時改以序號帶出設備 → 設備登載預填保固起算日（出貨日或完工日）→ 每日檢查納入已結案案件。上述 #1、#4、#5、#6、#7 是必須同時處理的五個結構性斷點。
