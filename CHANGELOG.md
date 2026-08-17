# MOTRIX ERP — 變更記錄

> 允碩整合集創股份有限公司  
> 按版本倒序排列。開發速查請見 `MOTRIX-ERP-QUICK.md`。

---

### 2026-08-17e — 移除業務開發接洽成效總覽「近 30 天最活躍」KPI

- 使用者要求拿掉這張卡片；`dev-crm.html` 移除該 `.dc-act-kpi` 區塊，KPI 列由 3 欄改回 2 欄，一併清掉行動裝置媒體查詢裡變成多餘的欄數覆寫
- 後端 `GET /api/dev-crm/activity-stats` 的 `bySalesperson` 欄位不變（業務員排行榜仍在用），純前端調整
- 已用 `node -e new Function()` 語法檢查與 div 標籤數量核對（165→162，減少的 3 個 div 對應被移除區塊的外層+兩個內層元素，數量吻合）

---

### 2026-08-17d — Asana 風格視覺化整合＋財務儀錶板支出項＋業務開發接洽成效總覽

- **背景**：使用者參考 Asana 官方介面截圖（月曆多天橫條視圖、Board 看板視圖），要求把這種視覺語言套用到任務相關介面；同時要求財務儀錶板新增支出項，並在對話過程中追加案件管理「動態」與業務開發模組的整合需求
- **A. 財務儀錶板支出項**：新增 `GET /api/dashboard/expenses-monthly`，彙整承攬商派發（複用 `vendor_contractors._dispatch_row()` 的 grandTotal 公式，避免重複邏輯）、料件/設備進貨成本（依 `parts.category` 分「設備」網通/監控/交換器/伺服器工控 vs「料件」線材配件/其他）、已精算完結案件的額外支出（`settlement.extraItems`，依 `editHistory` 最後一筆 `settlement_finalized` 時間歸月），近 12 個月，權限比照既有 `dashboard_monthly()`。`index.html` 新增「月支出結構」堆疊長條圖，4 類別配色已用 dataviz skill 的 `validate_palette.js` 驗證通過（CVD 檢查全過）
- **B. 每日工作事項 Asana 化**：`daily-tasks.html` 新增「月曆總覽」（全寬月曆，任務以彩色橫條顯示，同週內連續 occurrence 合併成一條橫條、貪婪演算法分配 lane，跨週斷開）與「看板」（依 category 動態分欄，卡片重用既有 `.dt-card` 系列樣式，`sortablejs` 拖曳跨欄，僅 `superadmin && dtUnlocked` 可拖曳，重建完整 payload PUT）
- **C. 案件甘特圖／專案看板加強**：`case-management.js` 甘特圖 bar 改依主要負責人 hash 上色並加 `custom_popup_html`（顯示負責人/日期/依賴階段）；`projects.html` 看板卡片新增成員頭像 chip（真實欄位 `projects.assigned_user_ids`，非新增資料模型）。三處共用同一組色碼＋hash 演算法（`_avatarColor`），讓同一人跨頁面顏色一致
- **D1. 案件管理「動態」Tab**：新增月曆 mini-grid（純前端統計已載入的 `caseUpdates`，不加 API），點日期篩選；`.feed-avatar` 改依發文者上色（沿用 C 的色碼演算法），事件類型徽章保留原本依來源上色
- **D2. 業務開發跨案件接洽成效總覽**：新增 `GET /api/dev-crm/activity-stats`（`dev_crm.py`），僅計入已核准 `dev_logs`，依既有 `_can_access_case()` 過濾權限，回傳近 60 天每日筆數、近 8 週週彙總、近 30 天業務員/通路排行；`dev-crm.html` 右欄「未選案件」空狀態改為接洽成效儀表板（KPI 卡＋純 CSS 長條趨勢圖＋排行榜），未額外引入圖表函式庫
- **驗證**：`node --check`／`new Function()` 語法檢查全數通過；`ast.parse`/`python -m py_compile` 驗證後端語法；對本機實際跑起來的 server 用 demo session 做完整 curl round-trip（`expenses-monthly`／`activity-stats`／每日工作事項 CRUD＋看板分類搬移 PUT 皆確認資料正確寫入讀出，含中文字元 UTF-8 完整性核對）；`pytest` 106/106 全過；`dashboard/expenses-monthly`／`dev-crm/activity-stats` 兩個新端點的聚合邏輯已對照開發機真實資料手算核對（承攬商派發 grandTotal=175,382／近 8 週接洽 7/18/2/3/1/0/0/0 筆），數字完全吻合
- 無 DB migration（全部復用既有欄位：`projects.assigned_user_ids`、`parts.category`、`contractor_dispatches` 既有欄位、`dev_logs` 既有欄位）；瀏覽器實機畫面驗證由使用者自行確認（Chrome MCP 操作時 plan mode 被反覆觸發，已改為純程式碼層級驗證）

---

### 2026-08-17c — 系統通知信全面補齊完整內容（不再截斷/省略）

- **背景**：使用者反映信件內容不完整，以案件留言板為例——收到新增留言通知信，但看不到留言
  實際寫了什麼，還是得登入系統才知道內容，違背「減少人員進入系統時間」的通知本意
- **根因**：`notify_module_activity()`（跨模組共用的通用活動通知，116 處呼叫）原本只有單行
  「項目」欄位，多處呼叫端把自由文字內容硬塞進這個單行欄位時用 `[:30]`/`[:40]` 截斷，或乾脆
  完全不傳，信件只看得到「誰在哪個模組做了什麼」，看不到實際寫的內容
- **修正**：
  1. `email_notify.py` `notify_module_activity()` 新增 `detail` 參數，獨立渲染「內容」區塊，
     完整呈現、保留換行、不截斷；同時補上 HTML escape（`html.escape`，含 `actor`/`item_label`/
     `detail`），避免留言含 `<`/`&` 等字元讓信件排版跑掉
  2. 逐一修正 9 個檔案共 10 處實際遺漏/截斷內容的呼叫端：
     - `quotations.py` 案件留言板新增留言：改傳完整留言全文，項目欄位補上客戶/專案名稱
     - `system.py` 工作日誌建立：改傳完整日誌內容
     - `dev_crm.py` 業務開發新增拜訪記錄：改傳完整記錄內容，並補回原本完全沒傳的聯絡管道與
       下一步待辦
     - `projects.py` 專案新增工作日誌：改傳完整工作內容
     - `customers.py`／`suppliers.py`／`vendor_contractors.py` 新增拜訪/往來紀錄：改傳最新一筆
       紀錄的完整備註內容（三個檔案是同一套「整份陣列覆寫」的往來紀錄模式，一併修正）
     - `vendor_contractors.py` 承攬商派發建立：項目欄位補上承攬商名稱，並傳入完整工作範圍說明
     - `shipping_notes.py` 出貨單回簽/取消回簽：改傳完整備註內容
  3. 已審查其餘 106 處呼叫（選型資料庫 CRUD、帳號/供應商/料號等結構化主檔異動、報價單狀態
     變更等）——這類動作本身沒有另外的自由文字內容欄位，項目欄位已是完整資訊，不需異動；
     23 個既有專屬 `notify_*` 函式（簽核／工作事項／到期提醒等）原本就傳遞完整內容，未受影響
- **驗證**：直接呼叫真正的 `notify_module_activity()` 攔截輸出，確認完整內容有出現、特殊字元
  正確跳脫（`<`/`&`）、換行轉為 `<br>`；對本機實際跑起來的 server 逐一實測案件留言／業務開發
  拜訪記錄／承攬商派發／往來紀錄四條路徑，皆正常回應無錯誤；`pytest` 106/106 全過

---

### 2026-08-17b — 承攬商派發新增發票號碼欄位

- **背景**：使用者要求承攬商發包需要能填寫發票號碼，所有填寫/顯示派發資訊的位置都要同步新增
- **DB v44**（`_m044_dispatch_invoice_no`）：`contractor_dispatches` 新增 `invoice_no TEXT DEFAULT ''`
- 後端 `vendor_contractors.py`：`DispatchIn` 模型、`_dispatch_row()`、`create_dispatch()`／
  `update_dispatch()` 的 INSERT/UPDATE 皆補上 `invoice_no`（JSON 欄位 `invoiceNo`，比照報價單
  收款品項 `invoiceNo` 的自由文字慣例）
- 前端：
  - `case-management.html` 承攬商派發 Modal（填寫）新增「發票號碼」欄位；派發卡片列表（顯示）
    新增發票號碼行
  - `vendor-contractors.html` 承攬商詳情「派發紀錄」區塊（顯示）新增發票號碼行
  - `settlement.html` 精算頁「三、承攬商派發成本」明細（顯示，唯讀即時讀取）承攬商列下方新增
    發票號碼小字
  - `case-management.js`：`dispatchForm` 狀態、`openEditDispatch()`、`saveDispatch()` 皆同步
    帶入/送出 `invoice_no`
- 已全庫搜尋確認派發相關欄位只出現在上述四個檔案，無遺漏位置；`node -e "new Function(...)"`
  驗證四個檔案內嵌 script 語法皆正確；額外用 Node 直接執行 `case-management.js` 真正的
  `_blankDispatchForm()`／`openEditDispatch()`／`saveDispatch()`（stub `fetch` 攔截送出內容）
  驗證欄位正確帶入與送出；後端用 Python `urllib` 對本機實際跑起來的 server 做完整 CRUD
  round-trip（建立含發票號碼→查詢→更新發票號碼→再查詢→列表端點皆正確反映），全部通過；
  `pytest` 106/106 全過

---

### 2026-08-17a — 修正精算「預估 vs 實際」毛利率公式不對稱

- **背景**：使用者要求複查案件金額／毛利率／報表／儀表板是否同步正確且公式正確。追查發現
  `quotation-form.html` 建立報價單時 `directProfit = pretax − totalCost − totalCost×5%`
  （對品項總成本額外扣一筆 5% 非扣抵進項稅才得出直接毛利），但 `settlement.html` 成本精算的
  每個品項預設 `actualCostTaxMode='pretax'`，`grossProfit = quotedPretax − totalActualCost`
  完全沒有這 5% 的扣除；`reports.py`（Excel「毛利分析」差異(pp)欄、`GET /api/reports/*` 的
  `estimatedMarginPct`/`actualMarginPct`）與 `dashboard.py`（`marginComparison`）都是直接拿
  這兩個公式不對稱的數字相減比較，導致即使案件實際成本跟原始報價完全相同，每一筆已精算案件
  都會系統性顯示「真實毛利率」比「預估毛利率」虛高——以典型 30~40% 毛利率的案件試算，落差約
  3 個百分點；已用 Python 模擬兩種公式驗證：修正前 bias=+3.19pp，修正後 bias=0.00pp
- **修正**（`frontend/pages/settlement.html`）：
  1. 精算品項初始化的預設 `actualCostTaxMode` 由 `'pretax'`（未稅，無調整）改為
     `'taxed_gross'`（含稅5%自動加總），與報價單建立時的假設基準一致；品項仍可個別切換回
     「未稅」或「含稅5%」因應該筆成本實際的稅務性質，只是改變沒有動過的品項的預設行為
  2. 精算頁「原始預估」欄位（`origDirectProfit`／`origMarginPct`／`origAdminCost`／
     `origCharity`／`origNetProfit`／`origNetMarginPct`）原本用 `settlement.items` 的
     `origQty`×`origCost` 重新加總計算，不僅同樣漏掉 5% 進項稅，還完全沒把
     `indirectLogistics`／`indirectInstallation`／`indirectTravel`／`indirectWarranty`／
     `indirectOther` 五個間接成本項目算進去；改為直接讀取報價單建立當下已經算好、存在
     `data_json.tot` 裡的對應欄位（沒有才 fallback 舊算法，相容尚未有此欄位形狀的極舊報價單），
     徹底消除「同一組數字兩處分別計算、公式各自漂移」的根本風險
  3. 只影響**尚未儲存過精算資料的新品項**；既有草稿或已完結（`finalized`）精算紀錄裡每個品項
     已存的 `actualCostTaxMode` 一律沿用不受影響，不回溯更動任何歷史精算快照
- 已用 `node -e "new Function(...)"` 驗證 `settlement.html` 兩個內嵌 `<script>` 區塊語法正確；
  `pytest` 106/106 全過（純前端修正，無 DB migration，後端測試本就不涉及此檔案）

---

### 2026-08-17 — 使用者個別 Email 通知偏好（DB v43）＋首頁最新動態彙整

- **背景**：`email_notify.py` 原本 23 個 `notify_*` 事件的收件人（`_admin_emails()` /
  `_superadmin_emails()` / `_lookup_emails()`）全員一體適用，無法讓特定管理員/使用者關閉自己
  不需要的信件類型；同時首頁缺少跨模組（業務開發／報價單／案件留言／出貨單／工作日誌／
  進出物料）彙整排序的「最新動態」總覽，只能逐一進頁面查看各自的更新
- **DB v43**（`_m043_notification_prefs`）：`users` 新增 `notification_muted TEXT DEFAULT '[]'`
  — 存的是「已關閉」事件 key 的**退訂清單**（非白名單），空陣列／NULL＝全部照舊接收，
  故既有使用者與新建帳號皆不受影響，未來新增事件類型也預設對所有人開啟
- **新模組** `helpers/notification_prefs.py`：`EVENT_GROUPS`（23 個事件 key，比照
  `notify_*` 函式名稱去除前綴，分 5 大類）＋ `is_enabled(muted_json, event_key)`
- `email_notify.py`：`_admin_emails()` / `_superadmin_emails()` / `_lookup_emails()` 三個
  收件人查詢函式加上 `event_key` 參數並依 `notification_muted` 過濾；23 個 `notify_*`
  函式呼叫處逐一補上對應 event_key
- **API**：`UserIn` 新增 `notification_muted`，`GET/POST/PUT /api/users` 同步讀寫
  （JSON 欄位 `notificationMuted`）
- `users.html`：新增／編輯使用者 Modal 內「Email 通知偏好」勾選區塊，比照既有「存取模組」
  手風琴分組 UI 樣式（`allNotifyTypes` / `notifyGroups` / `toggleNotifyType()`）
- **新 API** `GET /api/dashboard/activity-feed`（`routers/dashboard.py`）：彙整
  `case_updates`／`work_logs`／`dev_logs`／`stock_items` 直查 + `audit_log` 白名單動作
  （報價單／業務開發案件／出貨單）共 6 個來源，依時間新到舊合併排序；權限沿用既有規則
  （`can_quotation`／`can_dev_crm`／`_can_access_case()`／非 admin 只看自己名下報價單或
  工作日誌）
- `index.html`：首頁新增「最新動態」卡片，六色 `feed-badge` 依來源分類

---

### 2026-08-13 — 業務開發連結報價單改為審核制（可清空，DB v42）

- **背景**：2026-08-05b 開放的「修改連結」直接覆寫既有 `converted_quote_no`，且欄位必填不可清空；
  但案件變更常導致已連結的報價單被取消，此時需要能解除連結，而這類異動應比照案件刪除走審核，
  不該由單一使用者直接覆寫/清空已成立的連結
- **DB v42**（`_m042_dev_cases_relink_review`）：`dev_cases` 新增 `pending_relink` /
  `relink_requested_by` / `relink_requested_at` / `relink_reason` / `relink_target_quote_no`
  （空字串為合法值＝申請解除連結，非單純「未設定」）
- **新 API**：`POST /api/dev-cases/{id}/request-relink-quote`（admin+ 申請，`quote_no` 留空＝
  申請解除連結）／`POST .../cancel-relink-quote`（申請人或 superadmin 取消）／
  `POST .../approve-relink-quote`（僅 superadmin，核准後套用新單號或清空；清空時案件狀態
  一併退回「洽談中」，避免「成案」狀態掛著卻無對應報價單）
- `PATCH /api/dev-cases/{id}/convert` 加上守門：`converted_quote_no` 已有值時回 409，
  提示改走上述審核流程（原端點僅保留給尚未連結的初次轉建報價單使用）
- `dev-crm.html`：「修改連結」鉛筆按鈕改為開啟申請 modal（可留空、可填原因），案件詳情與
  清單卡片新增「待審核連結異動」標記，superadmin 專屬審核 modal（顯示申請人／原因／異動前後對照）
- Email 通知：`notify_dev_case_relink_request()`（新，仿 `notify_dev_case_delete_request`）

---

### 2026-08-05b — 業務開發×案件管理三項聯動（簽核閘門／連結可修改／動態同步）

- **報價單「已成案」需簽核完成**：`PATCH /api/quotations/{no}/deal-tag` 新增檢查，`deal_tag` 欲
  設為「已成案」時報價單 `status` 必須為「已送出」，否則 400；`quotation-form.html` 下拉選單同步
  disable「已成案」選項並在 `onDealTagChange()` 前端擋一次（雙重防呆，FORM_VERSION → V1.2）
- **業務開發案件連結報價單可修改**：原「轉建報價單」（`PATCH /api/dev-cases/{id}/convert`）僅在
  尚未連結時才顯示、且無法回頭修改；`dev-crm.html` 新增「修改連結」鉛筆按鈕 + 對應 modal
  （`openRelinkModal()`/`doRelink()`），沿用同一個既有端點（本來就允許覆寫，只是前端沒開放入口）
- **業務開發進度同步至案件管理「動態」Tab**：`GET /api/quotations/{no}/updates` 新增兩個來源
  （比照既有 work_logs／daily_task_completions 唯讀卡片模式）——① `dev_logs`（依
  `dev_cases.converted_quote_no` 反查 case_id 後列出）② `dev_case.status` 的 `audit_log`
  紀錄（案件狀態變更事件）；僅在該報價單有業務開發案件連結時才出現
- 用 demo 帳號（隔離空白庫）建立測試報價單/案件/開發記錄，以 curl 驗證三項行為皆正確後才收尾

### 2026-08-05 — 報價單簽核永久卡死：兩個共同根因修復 + 正式機 4 張卡死單查證

**緣起**：使用者回報「系統預設申請人不得自己簽核，但這位申請人送出的報價單，簽核流程設定裡把
這位申請人列為簽核人，導致報價單卡在簽核」，正式機當下已有報價單卡死。用使用者提供的正式機帳號
（`jeff`，superadmin）唯讀查證，確認卡死的是 `MQ-202608-003`～`006` 四張、皆由 `jeff` 直接送審。

- **Bug A**：`update_quotation()` 送審時把 `approval_flow` 設定轉成 tiers 快照，完全沒有排除
  送審人自己；`quotation-form.html` 的 `isCurrentTierApprover()` 寫死擋掉送審人自己的按鈕，但
  `approval-queue.html` 的 `canApprove()` 沒擋，兩頁邏輯矛盾；`approve_quotation()` 有 tiers
  分支原本也無自簽檢查
- **Bug B（比對正式機實際卡死單後發現、更根本的成因）**：正式機那 4 張單的 `approval` JSON
  完全沒有 `tiers` 欄位——`quotation-form.html` 的 `confirmSubmit()` 在「新單不先存草稿、直接
  送審」情境下打的是 `POST /api/quotations`（`create_quotation()`），但這個端點完全沒有 tiers
  建構或通知邏輯（該邏輯只存在於 PUT 的 `update_quotation()`），於是完全繞過已設定的兩層流程
  （`jeff→corbin`），也没有通知任何人（`corbin` 從未被告知要簽核）——任何人「新建報價單直接
  送審」都會中招，不限於送審人與簽核人重疊的情況
- 修法：新增共用 helper `_build_approval_tiers_and_notify()`（含 `_exclude_requester()`），
  `create_quotation()`（`body.status=='待審核'` 時）與 `update_quotation()` 都改呼叫同一段邏輯；
  `approve_quotation()` 補上自簽 403 防禦；`approval-queue.html` `canApprove()` 補上與
  `quotation-form.html` 一致的判斷
- 已用正式機唯讀查到的真實 `approval_flow` 設定（`jeff`/`corbin` 兩層）直接呼叫新 helper 驗證：
  `jeff` 正確被排除、只剩 `corbin` 一層、`corbin` 正確收到通知；全檔語法檢查通過。全程只對正式機
  呼叫唯讀 GET 端點，未寫入任何正式機資料
- 附帶修正：正式機 LAN IP 全站記錄錯誤（`172.16.11.211`→`172.16.10.177`，使用者確認為固定 IP），
  含 CORS 白名單與 email 通知連結預設值（若正式機從未手動設定過，過去簽核信件連結可能都是死連結）
- ⚠️ 尚未在瀏覽器實機重現完整送審流程（本機無 server 可測）；正式機 4 張卡死單不手動改資料庫，
  改為部署此修復後由 `jeff` 逐一「收回草稿」再重新送出，會走已修復的 `update_quotation()` 自動解卡

### 2026-08-04 — 報價單「新增品項」／「新增區段標題」按鈕失效修復

**緣起**：使用者回報報價單編輯頁「新增品項」「新增區段標題」兩個按鈕點擊完全沒反應。

- 根因：`addItem()`/`addHeader()` 呼叫 `crypto.randomUUID()` 產生 id，但此 API 只在安全情境
  （HTTPS 或 `localhost`）下才存在；透過區網 IP（`http://172.16.11.211:666`）以純 HTTP 存取時
  屬非安全情境，呼叫直接拋出 `TypeError`，函式中止在 push 進項目陣列之前
- 新增 `genId()` helper（安全情境下用 `crypto.randomUUID()`，否則 fallback 手動產生 id），檔案
  內 4 處呼叫點（`addItem`/`addHeader`/`loadQuote`/`copyToNew`）全數改用
- ⚠️ 尚未在瀏覽器實機驗證，下次有機會時請在非 `localhost` 位址實測確認

### 2026-08-03i — CRM 搜尋殘留 bug／側邊欄角標時區 bug（既有潛藏問題）／出貨單歷史紀錄

**緣起**：業務開發搜尋仍會出現不符搜尋文字的案件；業務開發／報價單側邊欄角標「仍然顯示但未有
其他更新」；要求新增出貨單歷史紀錄頁面。

- CRM 搜尋：`dev-crm.html` 搜尋框同時綁 `x-model.debounce.400ms` 與 `@input` 兩個監聽器互相打架，
  查詢字串永遠落後輸入一拍；改為 `x-model`（即時寫入）+ `@input.debounce.400ms`（延遲觸發查詢）
- 側邊欄角標時區 bug（既有潛藏問題）：`sidebar.js` 用 `toISOString()`（UTC）寫時間戳，後端存
  台灣本地時間，SQL 字串比較幾乎恆判定「有更新」；新增 `_localISOString()` 取代，連帶修好
  `daily-tasks.html` `isNewTask()` 同一套 bug
- 新增「出貨單歷史紀錄」頁面（`shipping-export-history.html` + `GET /api/shipping-notes/export-history`），
  攤平既有 `export_log` 為事件列表，無 DB migration
- 已用瀏覽器實測三項修改，測試資料已清除還原

### 2026-08-03g — 外包名冊新增「參與案件」聯動

**緣起**：使用者要求外包人員參與哪些案件也要跟承攬商管理一樣聯動，方便後續知道哪些人員參與過
哪些案件。

- `contractors.html` 詳情面板比照 `vendor-contractors.html` 承攬商頁的「派發紀錄」區塊，新增
  「參與案件」——沿用既有 `GET /api/contractor-dispatches`，前端用 `personnel_json` 快照篩出
  該人員實際參與的派發，顯示案號連結、狀態、所屬承攬商（純點工顯示無承攬商）、個人金額
- 已用瀏覽器實測驗證，無 console 錯誤

### 2026-08-03f — 承攬商派發改為選填，支援純外包名單人員點工（DB v37）

**緣起**：使用者反映「某些案件有外包人員，就沒有承攬商，單純點工，目前系統綁死要選擇承攬商」——
上一版加入的外包名單人員功能仍要求必選承攬商，無法涵蓋純點工案件。

- `backend/db.py` 新增 DB v37 migration `_m037_dispatch_vendor_optional`：`contractor_dispatches
  .vendor_id` 由 `NOT NULL` 改為可為空（SQLite 需整表重建，沿用既有建新表手法，冪等）
- `vendor_contractors.py`：`DispatchIn.vendor_id` 改選填；驗證改為「承攬商與外包名單人員至少
  擇一」，兩者皆空 → 400；`vendorName`/`import_dispatch_to_quote` 的 `None` fallback 一併修正
- 前端 Modal 拿掉承攬商必填星號，新增「外包人員（點工）」統一 fallback 顯示；派發卡片列表新增
  外包人員明細表格，金額改用 `grandTotal`（原本只算承攬商部分）；`settlement.html` 精算頁「三、
  承攬商派發成本」無承攬商時不再顯示佔位空列
- **零資料流失驗證**：複製開發庫副本跑新版 `db.py` 的 `init_db()`，確認 migration 前後列數不變、
  逐欄比對無跑位、重跑一次確認冪等；瀏覽器實測建立純外包人員點工派發（無承攬商）全流程正確

### 2026-08-03e — 承攬商派發新增外包名單人員個別計費，同步至財務／精算（DB v36）

**緣起**：使用者要求案件管理／承攬商派發新增「外包名單人員」，且承攬商與人員金額都要同步到
財務／精算顯示。

- `backend/db.py` 新增 DB v36：`contractor_dispatches` 加 `personnel_json`（自包含快照
  `[{id,name,amount,note}]`）；`backend/routers/contractors.py` 新增
  `GET /api/contractors/selectable`（比照 `vendor-contractors/selectable`）；
  `vendor_contractors.py` 補上讀寫與 `personnelTotal`/`grandTotal` 計算欄位
- 前端新增派發 Modal 內「外包名單人員」多選＋個別金額欄位；`settlement.html` 新增「三、承攬商
  派發成本」區塊（即時讀取、排除已取消），`calcSummary()` 併入 `dispatchTotal`；案件管理財務
  Tab 同步顯示
- 實測時發現並修正兩個問題：忘記把 `CURRENT_VERSION` 同步改成 36 導致新 migration 會被永久跳過；
  既有的「外包總成本」彙總算法本來就沒算稅金和人員，一併修正
- 已用瀏覽器完整驗證建立→儲存→精算顯示→已取消排除全流程，無 console 錯誤

### 2026-08-03d — 修復 module_versions 表無限增生 bug（DB v35）

**緣起**：使用者詢問正式機每日備份為何每次 300~400MB。查驗當天雲端備份 db 副本（唯讀，未動
正式機）發現 `module_versions` 表實際 626,725 列，但只有 143 組不同的 `(module, version)`，
佔掉備份 db 301MB 中超過 99% 的空間。

- **根因**：`module_versions` 表 `(module, version)` 從未有 UNIQUE 限制，`_sync_module_versions()`
  （`helpers/startup.py`）每次伺服器啟動用 `INSERT OR IGNORE` 想跳過已存在的紀錄，但沒有
  UNIQUE 可判斷衝突，每次重啟都把 143 筆 manifest 整批重複插入一次；crash-restart 迴圈＋
  歷次升級重啟長期累積出約 4,383 倍的重複
- `backend/db.py`：新增 DB v35 migration，補上 `UNIQUE(module, version)` 並重建表去重
  （優先保留使用者手動建立的紀錄），內含 `VACUUM` 釋放磁碟空間；migration 具冪等性
- `backend/routers/module_versions.py`：手動新增版本紀錄撞到重複 (module, version) 時
  回 409 友善錯誤，不再讓原生 IntegrityError 炸到 500
- **零資料流失驗證**：用當天正式機備份 db 副本實測（全程未連線正式機）——確認全部 626,725
  列皆為系統同步產生（無任何使用者手動輸入的紀錄）；用新版 `db.py` 的 `init_db()` 對備份副本
  跑過遷移，1 秒內完成，db 從 301MB 降至 1.71MB，143 列與 143 組相符（真正去重），逐筆比對
  manifest 內容與 db 內容全部一致（1 筆歷史內容差異屬既有現象，下次部署會自動同步修正，
  與本次遷移無關）；並用 `dbstat` 確認 db 內其餘所有表加總不到 1.5MB，沒有其他表有類似問題
- 尚未部署至正式機，需依 §15 流程由使用者在正式機執行 `apply_update.ps1`

### 2026-08-03c — 案件管理介面優化（5 項）

**緣起**：針對案件管理介面提出的 5 點建議，使用者確認後依序落實。

- `frontend/pages/case-management.html`：執行進度／叫料管控／設備登錄／保固備注 四個一級分頁合併為
  「執行管理」+ 二層子分頁（沿用既有但從未使用的 `.cm-subtabs` CSS），一級分頁 9→6 個；`.cm-tabs`/
  `.cm-subtabs` 補上手機版橫向捲動；拿掉與叫料管控分頁重複的「叫料到料」KPI；卡片新增「負責業務」欄位
- `backend/routers/quotations.py` 新增 `POST /api/quotations/case-activity`：彙整 `case_updates`/
  `work_logs`/`daily_task_completions` 三個不會觸發 `quotations.updated_at` 的動態來源，供案件卡片顯示
  「有新動態」未讀提示；`frontend/js/case-management.js` 比照業務開發 CRM 的「未讀游標＋一鍵已讀」設計
- 實測時發現並修正一個 bug：任務 1 一開始誤改到 `case-management.html` 裡的死碼 `__noop_stub()`（見
  2026-08-02c 條目警告），真正邏輯在 `frontend/js/case-management.js`；已修正並重新驗證
- 無 DB migration

### 2026-08-03b — 業務開發 CRM 新增一鍵已讀／只看未讀篩選

**緣起**：使用者反映業務開發模組「有更新」提示會不斷累積、清不完。追查後發現舊機制的已讀基準
是「上一次頁面載入的時間點」而非「離開時間點」，自己剛編輯的案件下次造訪仍會被判定為未讀，且
該提示原本只有 admin+ 看得到。

- `frontend/pages/dev-crm.html`：已讀基準改為模組專屬的 `localStorage` 游標，只能靠手動點擊
  「一鍵已讀」位移；開放給所有可用本模組的角色；新增「只看未讀」篩選與未讀彙總列；卡片欄寬
  300px→340px，新增業務開發／專案規劃人員姓名顯示
- 實測時發現並修正一個 bug：未讀判斷原本用字串比較時間戳，因後端格式（空格分隔）與
  `toISOString()`（`T` 分隔）在 ASCII 排序下不一致，導致同一天的更新恆判定為「未大於」而永遠不會
  顯示未讀；已改用正規化後的 `Date` 物件比較
- 未改動 `sidebar.js`/`notif.js`，其他模組共用的 sidebar 數字徽章機制不受影響
- 已用 demo 帳號實機驗證：未讀標示／一鍵已讀／只看未讀篩選／持久化皆正常運作

### 2026-07-30c — 場域選型導覽新增「簡易／進階」瀏覽切換

**緣起**：網路架構選型導覽上線後，使用者反應場域選型導覽原本的矩陣＋五組篩選＋搜尋太複雜，
希望比照網路架構選型導覽的「先選方塊、再看卡片」介面。討論後決定：不拿掉原本的進階瀏覽
（跨場域比較、風險/品牌篩選仍有價值），改成**新增一個可切換的簡易模式，兩種並存**。

- `frontend/pages/env-guide.html`：
  - 新增 `browseMode`（'simple'｜'advanced'）狀態，`.envg-hd` 新增「簡易／進階」分頁切換，預設 `simple`
  - 簡易模式：場域方塊（依大類分組：一般物流場/冷鏈/戶外/化工石化/延伸/通用）→ 點選後橫向顯示該場域所有分層的建議卡片（入門/建議/高端＋業界慣例＋特別注意＋產品連結＋缺口/關鍵/需外箱 badge），資料直接複用既有 `envRows`/`recRows`/`linkRows`（Alpine reactive），不碰資料庫、不碰原本的 vanilla JS 渲染邏輯
  - 進階模式：原本的矩陣／卡片／表格／搜尋／五組篩選／縮放／深淺色切換，原封不動保留
  - 簡易模式的卡片樣式與配色直接沿用網路架構選型導覽的 `.fam-tile`/`.gen-card`/`.tag-pill` 等 class（MOTRIX 系統配色，不受 ◐ 深色切換影響，因為這些 class 不在 `.envg` 命名空間內）

### 2026-07-30b — 新增「網路架構選型導覽」（選型資料庫第二類別）

**緣起**：場域選型導覽上線後，確立 ERP 要逐步擴充成涵蓋多產品線的「選型資料庫」（無人載具／
網路架構／監控／門禁／自動化系統…）。網路架構是第二個上線的類別，用來驗證：不同類別的內容
形狀可以差很多，不必硬塞進同一張表——這類是「技術族系→世代演進→產品」（如 Wi-Fi 6→6E→7、
4G→5G→5G mmWave），而非場域選型導覽的「情境×分層×三級」。

**後端（DB v30 → v31）**
- `backend/db.py`：新增 `_m031_netarch_guide` migration，建立 `netarch_families` / `netarch_generations`（FK family_code）/ `netarch_products`（FK generation_id）三表
- `backend/netarch_guide_seed.py`（新檔）：第一批資料——Wi-Fi（6/6E/7）、行動網路（4G LTE/5G Sub-6/5G mmWave），以 UniFi／Omada／Peplink／Netgear 實際產品驗證欄位設計
- `backend/routers/netarch_guide.py`（新檔）：`/api/netarch-guide/{families,generations,products}` CRUD，讀取任何登入者皆可，寫入需 superadmin 或 `netarch_guide_edit` 模組
- `backend/main.py`：掛載 `netarch_guide.router`

**前端**
- `frontend/pages/netarch-guide.html`（新檔）：瀏覽模式改用**先選族系方塊、再看世代橫向對照卡片**的簡化互動（不是場域選型導覽那套矩陣/篩選/搜尋），每張世代卡片含核心規格、比上一代進步、典型情境＋標籤、建議售價區間、依賴/相關備註、注意事項、對應產品；從一開始就用 MOTRIX 系統淺色配色（`--accent`/`--text-*`/`--border-light`），不再像場域選型導覽先做深色再改
- `frontend/static/sidebar.js`：新增 `cNetG` 模組旗標、`netg` 圖示、「業務」區塊新增「網路架構選型導覽」nav 項目
- `frontend/pages/users.html`：`allModules` 新增 `netarch_guide`（檢視）／`netarch_guide_edit`（新增修改刪除）

**文件**
- 新增根目錄 `SELECTION-DB-INDEX.md`（選型資料庫總索引：分類邏輯、類別清單、提需求格式）與 `NETARCH-GUIDE-CONTENT.md`（本類別內容維運手冊）

### 2026-07-30a — 新增「場域選型導覽」模組（原單機工具整合進 ERP）

**緣起**：`場域選型導覽.html` 原為 Claude Desktop 本機代理模式產出的獨立參考工具（無人自動化載具 30 個部署場域 × 分層三級設備建議，Sbjlink／Teltonika／iEi／Southco 原廠規格），資料寫死在 JS 陣列裡。今日整合進 MOTRIX ERP，資料庫化並開放後台編輯。

**後端（DB v29 → v30）**
- `backend/db.py`：新增 `_m030_env_guide` migration，建立 `env_guide_environments` / `env_guide_recommendations`（FK env_code, ON DELETE CASCADE）/ `env_guide_links` 三表；種子資料只在表為空時寫入一次（不覆蓋後續編輯）
- `backend/env_guide_seed.py`（新檔）：原工具的 30 筆場域／80 筆建議／44 筆連結，轉存為 JSON 字串常數供 migration 解析
- `backend/routers/env_guide.py`（新檔）：`/api/env-guide/{environments,recommendations,links}` 讀寫 CRUD；讀取任何登入者皆可，寫入需 superadmin 或 `env_guide_edit` 模組（沿用 `parts.py`／`contractors.py` 慣例，`_require_user`/`_audit`）
- `backend/main.py`：掛載 `env_guide.router`

**前端**
- `frontend/pages/env-guide.html`（新檔）：瀏覽模式完整保留原工具的搜尋／篩選／矩陣／卡片／表格／抽屜互動（vanilla JS 原樣搬遷，只把寫死陣列改成 `fetch()` API 資料），套上 MOTRIX topbar/sidebar 殼；新增「管理」模式做場域/建議/連結的新增修改刪除（Alpine + modal）
- 配色：`.envg` CSS 變數改對應 MOTRIX 系統色票（`--accent`/`--text-*`/`--border-light`/`--font-zh` 等），預設（`data-th="light"`）＝系統配色，原本的深色調保留為 `data-th="dark"` 備用切換（點 ◐ 圖示）
- **Excel 匯出／匯入**：僅 superadmin 可見（`session.role==='superadmin'`），3 個工作表（環境/建議/連結），匯入以代碼／ID 比對更新或新增，沿用單筆 CRUD API（做法比照 `customers.html`）
- `frontend/static/sidebar.js`：新增 `cEnvG` 模組旗標、`envg` 圖示、「業務」區塊新增「場域選型導覽」nav 項目（無 badge）、`_FILE_MODULE` 對應
- `frontend/pages/users.html`：`allModules` 新增 `env_guide`（檢視）／`env_guide_edit`（新增修改刪除，含 Excel 匯出入前提）二選項；`ROLE_MODULES.admin`／`.superadmin` 預設含 `env_guide`

### 2026-07-28a — 系統字體全面改為 LINE Seed TW_OTF（自架字型）

**字型自架（`frontend/fonts/`，新增目錄）**
- 複製 4 個字重的 OTF：`LINESeedTW-Thin.otf` / `-Regular.otf` / `-Bold.otf` / `-ExtraBold.otf`
- 由 `backend/main.py` 既有 `StaticFiles(FRONTEND_DIR)` 掛載自動於 `/fonts/*.otf` 提供，區網各台電腦免個別安裝字型即可看到一致外觀

**`frontend/css/style.css`**
- 新增 4 組 `@font-face`（`font-family: 'LINE Seed TW_OTF'`，`font-weight` 依 Thin 100-300 / Regular 400 / Bold 500-700 / ExtraBold 800-900 對應）
- `--font-en` / `--font-zh` 統一改為 `'LINE Seed TW_OTF', system-ui, sans-serif`（原分別為 Google Fonts CDN 的 `Inter` 與 `'Noto Sans TC', 'Inter'`）

**全站頁面／腳本（34 個 `.html` + `js/*.js` + `static/*.js`）**
- 移除所有頁面 `<head>` 內的 Google Fonts `<link>`（`fonts.googleapis.com` / `fonts.gstatic.com`，涵蓋 Inter / Noto Sans TC / Noto Serif TC）
- 所有內嵌 `font-family: Inter, sans-serif`（及各種空白/引號變體）、`'Noto Sans TC', sans-serif`、`'Noto Serif TC', serif` 統一替換為 `LINE Seed TW_OTF`（含 `quotation-form.html` 報價單 PDF 匯出樣式）
- Chart.js 全域字型設定（`index.html` / `js/reports.js` 的 `Chart.defaults.font.family`）同步更新

**批次取代衍生的字串斷裂修正**
- 以正則批次取代 `Inter,sans-serif` 時，凡原本落在**單引號分隔的 JS 字串**內（`static/sidebar.js` 8 處、`static/notif.js`、`index.html`、`pages/sales-orders.html`、`pages/quotation-form.html` 的 `style.cssText = '...'` 與 Alpine `:style="'...'"` 動態綁定），取代字串本身帶的單引號會提前把 JS 字串截斷、造成語法錯誤
- 修正方式：CSS 允許多字詞 `font-family` 值不加引號（`font-family:LINE Seed TW_OTF, sans-serif` 等價於加引號寫法），故在會截斷字串的位置一律改用不加引號形式
- 驗證：4 個獨立 `.js` 檔以 `node --check` 全數通過；全站所有 `.html` 內嵌 `<script>` 區塊以 `new Function()` 逐一語法解析，全數通過；`curl` 確認 `/fonts/LINESeedTW-Regular.otf` 回應 200（5.2MB）

### 2026-07-21g — 品質掃尾批次（Quality Sweep）

**L2 — SortableJS item key 碰撞修復（`frontend/pages/quotation-form.html`）**
- `addItem()` / `addHeader()` 的 `const id = Date.now()` → `crypto.randomUUID()`
- 複製模板路徑：`id: Date.now() + Math.random()` → `id: crypto.randomUUID()`
- API 載入後補 normalize：`this.q.items.forEach(it => { if (!it.id) it.id = crypto.randomUUID() })`（向後相容無 id 的舊報價單）

**L3 — pytest 覆蓋率擴充（`backend/tests/test_core.py`）**
- 新增 4 個測試類別，共 48 tests（原 25）
  - `TestStepsToTiers`（6 cases）：空陣列 / 單步驟 / 順序 / displayName fallback / userId default / 不保留 status
  - `TestActiveTiers`（5 cases）：空 / modern tiers passthrough / 舊 steps backward-compat / 預設 pending / tiers 優先於 steps
  - `TestCurrentTierIdx`（4 cases）：currentTier / currentStep / 預設 0 / 優先順序
  - `TestPasswordHelpers`（8 cases）：PBKDF2 hash+verify / 錯誤密碼 / 不同 salt / 舊 SHA256 相容 / 弱密碼策略

**確認已施作（無需動作）**
- L1：`notif.js:68` 鈴鐺 unread badge 已排除 `type==='approval_request'`，sidebar 角標與通知鈴鐺互不干擾
- E2：Login 速率限制（5 fails → 15 min lockout）在 `routers/auth.py` 已完整實作，含 DB 持久化
- E3：Session 清理（`_cleanup_sessions()`）在啟動時執行，已在 `helpers/startup.py` 實作

---

### 2026-07-21f — 可靠性強化批次（Reliability Patch Batch）

**H3 — 備份失敗 Email 告警（`archive.py`）**
- 新增 `_send_backup_error_email(reason, ts)` 函式
- `_write_backup_alert()` 在 `level=="ERROR"` 且同日尚未發送時呼叫之
- 收件者：`helpers.email_notify._admin_emails()`（所有 admin/superadmin 的 email）
- 發送方式：`_async_send()`（非同步，不阻塞備份流程）；若 Email 未啟用或無收件人則靜默跳過

**H4 — 匯出端點速率限制（`routers/reports.py`）**
- 新增模組級 `_export_times: dict`、`_export_lock: threading.Lock`、常數 `_EXPORT_COOLDOWN = 60`
- 新增 `_check_export_rate(user_id)` — 60 秒冷卻，違反回傳 HTTP 429
- `GET /api/reports/financial/excel` 和 `GET /api/reports/financial/pdf` 均在 auth 後立即呼叫

**M1 — steps→tiers 共用函式（`helpers/quotations.py` + 兩處呼叫端）**
- 新增 `_steps_to_tiers(steps: list) -> list`（無 status 欄位，純格式轉換）
- `helpers/__init__.py` re-export 新函式
- `routers/system.py._normalize_flow()` 改呼叫 `_steps_to_tiers()` 取代原本 inline comprehension
- `routers/quotations._setting_to_active_tiers()` 改呼叫 `_steps_to_tiers()` 取代原本 `[{"order": i, "approvers": [s]}]`
- `_active_tiers()` 維持獨立（需保留 status/approvedAt，不共用）

**M3 — pytest 單元測試（`backend/tests/test_core.py`）**
- 新增 `backend/pytest.ini`（`pythonpath = .`、`testpaths = tests`）
- 新增 `backend/tests/__init__.py`（空白，標記 package）
- 新增 `backend/tests/test_core.py`：25 個測試全部通過（1.31s）
  - `TestParsePeriod`（9 cases）：年度 / 月份 / 季度 / 閏年解析
  - `TestComputeAchievement`（6 cases）：空目標 / 年份不符 / 單案件 / 業務員分解 / 收款率 / 年份過濾
  - `TestCalc`（10 cases）：扣繳稅率 / 二代健保 / 外籍低薪率 / 有工會免補充費

---

### 2026-07-21e — 安全修補批次（Security Patch Batch）

**1. CSP Header（`main.py`）**
- `security_headers` middleware 新增 `Content-Security-Policy` 標頭（常數 `_CSP`）
- script-src 允許 `unsafe-inline`/`unsafe-eval`（Alpine.js 需求）+ `cdn.jsdelivr.net`；object-src `none`；frame-ancestors `self`

**2. Session Idle Timeout 8h（`main.py` + `db.py` + `routers/auth.py`）**
- DB migration v17：sessions 表新增 `last_active TEXT`
- 登入時（`auth.py`）INSERT 帶 `last_active = now`
- `auth_middleware`：若 `last_active` 已設且閒置 > 8h → 刪除 session + 401（`detail: "閒置超過 8 小時，請重新登入"`）
- 閒置 > 5 分鐘才更新 `last_active`（限制 DB 寫頻率）；首次請求（`last_active IS NULL`）直接 stamp 不拒絕

**3. `_PHOTO_SECRET` 持久化（`routers/projects.py`）**
- 原 `_PHOTO_SECRET = secrets.token_bytes(32)` 改為 `_get_photo_secret()` 函式
- 讀 `system_settings.photo_secret`；不存在時生成 32-byte hex 並儲存；以 `_PHOTO_SECRET_CACHE` 模組快取

**4. `PUT /api/settings/operating-targets` Pydantic Schema（`routers/system.py`）**
- 新增 `OperatingTargetsBody` / `_AnnualTarget` / `_SalespersonTarget` Pydantic 模型
- 替換 `body: dict = Body(...)` → 強型別驗證；同時寫入 audit_log（操作人、年度）

**5. HTML 逸出 in PDF 報表（`routers/reports.py:_build_report_html()`）**
- 函式內新增 `esc()` wrapper（`html.escape(str(v))`）
- 所有 period items / outstanding / case / sales / warranty / achievement 行的使用者資料欄位均套用 `esc()`

**6. AR 帳齡端點（`routers/reports.py`）**
- 新增 `GET /api/reports/ar-aging`（admin+ 權限）
- 返回：`{ asOf, note, bands:[{label, key, count, amount, items:[]}], total:{count,amount} }`
- 帳齡以案件報價日為基準分四區間；不含已收款項目

---

### 2026-07-21d — 財務報表：圖表分析 Tab

**新增 CDN（`reports.html`）**
- `<script src="https://cdn.jsdelivr.net/npm/chart.js@4">` 置於 `reports.js` 之前

**新增 Tab「圖表分析」（`reports.html`）**
- Tab 按鈕加於「目標達成率」之後；面板以 `x-show` 渲染（canvas 始終在 DOM，不影響 `x-ref` 解析）
- CSS 新增 `.chart-2col`（2:1 雙欄格線）、`.chart-card`（白底圓角卡）、`.chart-card__title`；RWD ≤800px 自動退為單欄

**`reports.js` 圖表方法**
- `_charts: {}`：chart 實例倉，供 destroy/resize 生命週期管理
- `initCharts()`：銷毀舊實例 → 設定全域字型（Inter/Noto Sans TC）→ 依序呼叫 5 個 `_build*Chart()`
- `_buildTrendChart()`：近 12 月成案趨勢，混合圖（Bar 件數左軸 + Line 合約金額右軸）；資料從 `casesAll.quoteDate` 分月聚合
- `_buildStatusChart()`：案件狀態分佈（Doughnut 65% cutout）；進行中（#F59E0B）vs 已結案（#6B7280）
- `_buildSalesPerfChart()`：業務員績效比較（Horizontal Grouped Bar）；合約總額 vs 已收款；最多顯示 8 人；高度依人數自動計算（max 180, count×52）
- `_buildTargetChart()`：年度目標達成率（Horizontal Bar + 紅虛線 100% 參考線）；6 指標色碼同 KPI Tab（綠/橘/紅）；`hasTargets=false` 時不渲染
- `_buildMarginChart()`：毛利率比較（Grouped Bar）；依業務員分組平均預估 vs 實際精算毛利率；`marginCases` 為空時不渲染
- `$watch('activeTab')`：切回 charts Tab 時，若實例已存在 → `resize()`；若初次進入 → `initCharts()`
- `$watch('data')`：期間切換後資料更新 → 在 charts Tab 時自動重新產圖

---

### 2026-07-21c — 財務報表：營運目標及達成率

**新 API 端點（`routers/system.py`）**
- `GET /api/settings/operating-targets`：讀年度目標（Bearer 即可）
- `PUT /api/settings/operating-targets`：寫年度目標（superadmin；body: `{year, annual:{revenue,newCases,collectionAmount,collectionRate,avgNetMarginPct,grossProfit}, salesperson:[{name,revenue,cases}]}`）

**後端計算（`routers/reports.py`）**
- 新增 `_compute_achievement(year, targets, cases_all)`：計算 6 大年度指標的 YTD 實績 vs 目標（含達成率、按時間比例目標）+ 業務員個人配額達成
- 新增 `_augment_with_targets(data, d0)`：從 `system_settings` 讀 `operating_targets`，計算 `achievement`，注入 `data["targets"]` / `data["achievement"]`（3 個端點統一呼叫）
- `_build_excel()`：新增 Sheet 2「目標達成率」（6 指標表 + 業務員配額表；達標/追趕/落後三色背景）；原 Sheet 2-7 順移為 Sheet 3-8
- `_build_report_html()`：PDF 新增「年度目標達成率」章節（6 格 KPI 卡片 + 進度條 + 業務員表格）；注入 `{acv_html}` 於執行摘要後

**前端（`reports.html` + `reports.js`）**
- `reports.js`：新增 `targets` / `achievement` getters；`acvGrade/acvColor/acvBarPct` 輔助函式；`openTargetModal / addSpTarget / removeSpTarget / saveTargets` 方法；`targetModal / targetForm / targetSaving` 狀態
- `reports.html`：新增 Tab「目標達成率」（6 大指標 KPI 卡片 + 進度條 + 業務員達成率表格）；目標設定 Modal（superadmin only：年度 + 6 大指標 + 動態業務員配額行）；CSS 新增 `.acv-grid / .acv-card / .acv-bar-track / .acv-bar-fill / .btn-set-target / .tgt-2col / .tgt-sp-row`

**達成率計算邏輯**
- YTD 案件：篩選 `casesAll` 中 `quoteDate` 以目標年份（`d0[:4]`）開頭者
- 按時間比例目標：`target × (今日為今年第 N 天 / 全年天數)`；收款率 / 毛利率無按比例
- 平均淨毛利率：基於 `settleStatus=finalized` 的 YTD 精算案件
- `targets.year` 不符合報表期間年份 → `hasTargets: false` → 顯示「尚未設定」提示

---

### 2026-07-21b — 每日工作事項大幅擴充 + Email 商務改版

**常駐任務（週排程折疊）**
- 左面板拆成「常駐任務」（`.recurring-card`，黃底，每週排程去重只顯示一次）和「單次任務」（日期分組）兩區塊
- 常駐任務卡片：本日 N/M 進度 + `monthRate()` 本月完成率 badge + 指派人員 chips
- `filteredWeeklyTasks()` 去重：同 task.id 只取今日 occurrence（或當月首筆）；`weeklyTodayOcc()` 輔助

**跨日逾期通知**
- `_check_overdue_and_notify()` 每日 08:00 掃描昨日所有任務（once + weekly）所有指派人
- 通知對象：被指派人 + 指定主管（若有，嚴格不 fallback 至所有 admin）；主管無 email 時記 warning
- **修復重啟重寄 Bug**：`_set_setting("dt_overdue_last_check", yesterday)` 移至 try block **之前**（guard 先寫），任何例外都不會重置 guard → 重啟不會重寄
- `schedule_overdue_check()`：新增 `if datetime.now().hour >= 8` 條件，深夜重啟不觸發 catch-up

**指派主管 Email 精確路由**
- `daily_tasks` 新增 `supervisors TEXT NOT NULL DEFAULT '[]'`（DB v16 `_m016_daily_task_supervisors`）
- `notify_daily_task_completed` / `notify_daily_task_overdue`：若 `supervisor_usernames` 有值→ 僅通知指定主管（不 fallback 至全體 admin）；主管無 email 時 log warning 並 return

**歷史紀錄功能**
- `GET /api/daily-tasks/{id}/history?page=&per_page=`：所有歷史 occurrence 分頁，軟刪除後仍可讀
- `GET /api/daily-tasks/{id}/history/export`：UTF-8 BOM CSV（7 欄位）
- 右面板 Tab 切換「本次紀錄」/「歷史紀錄」；歷史 timeline 可展開每人狀態 + 回報；「載入更多」分頁；匯出 CSV 以 `Authorization: Bearer` fetch 再 blob download

**回報彙整視圖（全面重設計）**
- 從頂部按鈕切換，佔滿主畫面；分割面板：左 256px 任務列表 + 右詳情
- 回報文字永遠顯示於人員名稱正下方；當前登入人員的行以紫色左側條標記
- 日期選擇：年份/月份 select + ← → 日期導航；全文搜尋：即時搜尋任務名稱/分類/回報內容

**Email 商務文案全面改版（`helpers/email_notify.py`）**
- 所有 9 個 `notify_*` 函式改用 `【MOTRIX】` 主旨前綴，加 `intro` 問候段落，自訂 `button_text`

---

### 2026-07-21a — 每日工作事項全改版

**Req 1 — `pages/daily-tasks.html` 全新設計**
- UI：固定頂部工具列（月份導航）+ 左右雙欄佈局（左面板 300px 搜尋+任務卡片 / 右面板任務詳情）
- 新增/編輯 Modal：日期/優先級/標題/分類/說明 + 排程設定（單次/每週 + 星期幾圓形按鈕）+ 卡片型式人員選取
- 解鎖 Modal：輸入密碼 → POST /api/auth/verify-daily-task-unlock；428=未設定→自動解鎖；403=錯誤

**Req 2 — 管理視角存取控制**
- DB v15：`users.daily_task_pw_hash TEXT NOT NULL DEFAULT ''`
- 後端 `routers/auth.py`：新增 `POST /api/auth/verify-daily-task-unlock`、`PATCH /api/users/{id}/daily-task-password`

**Req 3 — `pages/users.html` 兩項擴充**
- 每列操作區新增「工作事項」按鈕；編輯 superadmin Modal 新增每日工作事項密碼區塊

**後端修復：週排程（DB v14）**
- `_m014_weekly_recurrence`：`daily_tasks` 新增 `recurrence_type/days/end_date`；重建 `daily_task_completions`（UNIQUE 由 (task_id, username) 改為 (task_id, occurrence_date, username)）

---

### 2026-07-20v — 每日工作事項 + 簽核繞過修復

**每日工作事項（`工作內容` 分類下新頁）**
- DB v13：`_m013_daily_tasks` 新增 `daily_tasks` + `daily_task_completions` + 索引
- 後端 `routers/daily_tasks.py`（新）：6 端點（CRUD + PATCH complete）
- 前端 `pages/daily-tasks.html`（新）：左右雙欄；月份導航；superadmin 人員篩選；完成回報 form

**簽核繞過修復（`routers/quotations.py`）**
- `PATCH /api/quotations/{no}/status` 加前置檢查：若 body.status=="已送出" 且尚有未完成簽核層 → 403

---

### 2026-07-20u — 同一層簽核人必須按順序簽核

- 同層內的審核人必須照陣列順序逐一簽核（1號簽完 → 2號才能簽）
- 後端：先確認用戶在當層，再找 `first_pending`；不是第一位 → 403
- 前端 `quotation-form.html` / `approval-queue.html`：改為只看 `firstPending`

---

### 2026-07-20t — 簽核每層加入拒絕結案鎖死功能

- `quotation-form.html` 新增「拒絕結案」Modal（工具列按鈕 + 預覽 Modal 底部）
- 必填原因 textarea；確認後呼叫 `POST /api/quotations/{no}/reject-final`

---

### 2026-07-20s — 退回改版報價單全狀態 returnInfo 顯示

- 移除 `q.status === '草稿'` 限制，改為 `x-show="q.returnInfo"`，所有狀態均顯示退回橫幅
- `reject_quotation()` 中 `previousItems` 快照新增 `type` 和 `brand` 欄位

---

### 2026-07-20r — 案件管理匯入選取功能 + PDF 隱藏欄位修復

- 「從報價單匯入」改為選取式 Modal（checkbox 品項清單，可全選/清除）
- `pdf_gen.py`：修復 `pdfShow` 設定被完全忽略的問題；6 個欄位改為條件式輸出

---

### 2026-07-20p — 專案管理成員分配功能

- DB v12：`projects.assigned_user_ids TEXT DEFAULT '[]'`
- 後端存取控制：非 admin 使用者只看到其 ID 在 `assigned_user_ids` 內的專案
- 新端點 `PATCH /api/projects/{id}/assigned-users`

---

### 2026-07-20o — 使用者管理模組同步修復

- `case_manage` 補入 allModules；ROLE_MODULES 同步更新
- 空 modules 陣列 bug 修復：`hasAccess()` 改用 length 判斷
- equipment 模組 sidebar gating；`dashboard` 模組支援；ntfy icon 補全
- Async session 同步：每頁背景呼叫 `GET /api/auth/me`，有變動立即更新 localStorage 並重建 sidebar

---

### 2026-07-20n — case-management 端點驗證 + §7.1 修正

- 全 9 端點驗證通過（零斷線）
- 移除錯誤標注的 `PATCH /payment/{idx}`（舊版殘留）

---

### 2026-07-20m — case-management 執行 Tab 扁平化

- 移除「執行」父 Tab 及子 Tab 列；4 個原子 Tab 晉升為頂層

---

### 2026-07-20l — case-management 同步 UI/UX 升級

- 左側卡片色條（CSS `:has()` 選擇器）+ Tab 計數 Badge
- Header 3 列化；狀態變更 Popover；日誌卡片視覺強化

---

### 2026-07-20k — projects.html UI/UX 全面重新設計

- 狀態篩選列改 flex-wrap Pill；卡片左色條（CSS `:has()`，7 種狀態色）
- 右側 Header 3 列化；狀態 Popover；日誌卡片 32px 日期 Icon Block
- JavaScript 0 改動

---

### 2026-07-20j — 報價單列表未成案分類

- 「全部」改名「全部(不含未成案)」並排除未成案
- 新增「未成案」Tab

---

### 2026-07-20i — 簽核 bug 修復、狀態手動調整、設備群組匯入

- 移除「自動跳過自身 tier-0 簽核」邏輯（此邏輯在唯一簽核人即申請人時造成 stuck）
- superadmin 狀態手動調整下拉；設備群組區塊式顯示（可折疊，按 qty 建立 N 台）

---

### 2026-07-20h — reject-final 對接、品項標題行、單項毛利欄、拖曳排序

- `approval-queue.html` 前端對接「拒絕結案」（Modal + API）
- `quotation-form.html` 新增 `type:'header'` 品項；`addHeader()`；`real_idx` 跳過標題行
- 單項毛利欄（amount − qty × cost × 1.05）；SortableJS v1.15.3 拖曳排序
- `pdf_gen.py`：識別標題行，輸出藍色全欄標題行

---

### 2026-07-20g — 退回修改完整流程

- `notify_returned()` / `notify_resubmit_requester()`（新）
- `returnInfo` 快照（退回人/時間/原因/前版品項）
- `quotation-form.html`：退回通知橫幅 + 退回修改 Modal + 簽核按鈕重構

---

### 2026-07-20f — 簽核功能完善版

- 收回草稿（`POST /api/quotations/{no}/recall`）
- Email `from_name` 統一為 `"MOTRIX營運系統"`
- Email 靜默丟棄改為 warning log
- Photo token `@error` retry

---

### 2026-07-20e — 修正版

- 死碼清除：刪除 `frontend/js/` 21 個未被載入的 JS 檔
- settlement.html / approval-settings.html / projects.html 補實作與修正

---

### 2026-07-20d — 驗證修正版

- §2/§7/§9/§11/§13 全面修正（死碼標示、幽靈頁面、SQL fallback、雙路徑風險）

---

### 2026-07-20c — 架構梳理交付版

- 全面讀取後端 11 個 router + 6 個 helpers + archive/pdf_gen
- 新增 §5/§6/§7/§15（共用函式庫、API 端點列表、前端→API 對應、資料流呼叫鏈）

---

### 2026-07-20b — UX P3：簽核佇列警示 + 案件執行階段標籤 + 待精算篩選

- 儀表板 Onboarding 引導條；「待精算」篩選 Tab；簽核佇列紅色警示

---

### 2026-07-20 — UX P1/P2：簽核待辦儀表板 + sidebar 角標 + 通知拆分

- 儀表板「等我簽核」KPI；sidebar 簽核佇列角標；`GET /api/approval-queue/count`

---

### 2026-07-19b — Email 通知修復 + 舊代碼清除

- `is_new_submission` 改查 DB 舊狀態；OPTIONS 放行修正；restart.bat 改 PowerShell

---

### 2026-07-19 — Email 通知功能

- `helpers/email_notify.py`（新）：Gmail SMTP 非同步發信；5 事件函式

---

### 2026-07-18a — 全面安全審查 P0–P3（30 項）

**P0 — 安全漏洞**：多個端點補 `_require_user`；deal-tag 補 Auth header；DELETE 僅草稿

**P1 — 業務邏輯**：解鎖 superadmin 驗證；狀態機白名單；deal_tag 已結案不可逆；settlement 回滾；GET /auth/me 驗 expires_at

**P2 — 邊界案例**：mark_payment 樂觀鎖；delegateNote 寫 audit；已成案降級限 admin+；G: fallback；rate limit 持久化；notif.js DOM API；防重複送出 flag

**P3 — 品質**：JSON 原子寫入；Dashboard sparkline 真實資料；audit-log admin+ only；work-log owner 驗證
