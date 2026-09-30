# 總帳（GL）預留底層掛鉤清單（W4 → W1 觸點表）

> 2026-10-01，使用者：「底層（L0／L1／migration／共用 js／共用頁）一次預留好，之後只動模組」。
> 原則：凡是**新增一種東西**（事件碼、科目對應、稅碼、頁籤、簽核類型、信件類型、功能旗標…）都改成 **資料／設定／提供者驅動**，新增時只動 `modules/accounting`（L2）與它自己的頁面（行內元件）。
> 下表每列＝「若不預留，之後會逼出一次底層改動」＋「建議的一次性預留（底層只動這一次）」＋「現況」。標 🔴＝**這一班就該動底層**（否則下一班必須再動）；🟡＝可等、但要在觸點表登記；✅＝已經不需要底層。

## A. 需要這一次底層改動才能預留的（🔴）

| # | 項目 | 不預留的後果 | 一次性預留（建議） | 層級 |
|---|---|---|---|---|
| A1 | **分錄維度欄位**（部門、專案、費用類別…） | 費用單要部門維度、報表要依部門分 ⇒ 每加一個維度就是一支 `voucher_lines` migration（bottom） | accounting 下一支 migration（**只做這一次**）：`voucher_lines.dim_json TEXT NOT NULL DEFAULT '{}'`（鍵＝維度代碼，值＝字串）＋ `gl_dimensions(code, label, is_active)` 設定表；事件契約的行可帶 `dims`；試算表／分類帳可依任一維度篩。之後新增維度＝設定表加一列 | 模組 migration（底層） |
| A2 | **簽核佇列的新單據類型**（`ledger_action` 已經逼出一次 `approval-queue.html`＋`routers/approval_queue.py` 改動） | 每個新類型（費用單、採購單、定義送審…）都要改共用頁與標籤表 | 佇列項目自帶顯示資訊：`typeLabel`、`openUrl`、`approveUrl`、`rejectUrl`（含方法與 body 欄位名）、`idField`；`approval-queue.html` 與 `_ITEM_TYPE_LABELS` 改成**讀項目上的欄位**（找不到才退回現有硬編碼）。提供者回傳即可，不必再改頁面 | L1 頁＋router（一次） |
| A3 | **信件類型要在個人通知偏好登記**（`helpers/notification_prefs.EVENT_GROUPS` 是 L1；`test_every_registered_key_is_mutable` 逼每個模組登記的信件類型都要加進去） | 每個模組加信件類型就要動 L1 | `EVENT_GROUPS` 改成「靜態群組＋**自動併入** `mail_types` 登記表中 `category='approval'／'business'` 的模組登記項」；守門題改驗「登記表 ⊆ 偏好表（含自動併入）」 | L1 helper＋守門 |
| A4 | **`helpers/custom_finance.gl_lines` 只暴露固定欄位**（C7 要加 `taxField`／`docTypeField`，之後還會有更多 finance 屬性） | 每個新 finance 屬性都要改 L1 helper＋介面快照＋UNIT-INDEX | 這次就讓 `gl_lines` 原樣帶出該欄位的整個 `finance` 屬性字典（`line["finance"]`）與單據 `data`（唯讀副本）；總帳側自己挑要用的鍵。之後新增屬性只動 `modules/accounting` | L1 helper（一次） |
| A5 | **守門的清單式登記**：`test_wording_guards` 的 `SCAN_FILES`、`docs/platform/modules.json` 的單位逐檔列、`bottom_layer` 的 `global_tests`…每個新檔（`notify.py`、`custom_events.py`…）都要人工登記，漏了列車才紅（本次 27／28 班就紅了 3 次） | 每新增一個模組檔＝一個紅燈＋底層（tools／tests／docs）改動 | 改成**慣例自動發現**：`SCAN_FILES` 自動含 `modules/*/notify.py`；`modules.json` 單位歸屬規則化（`modules/<key>/**` 預設屬該模組，只有例外才列）；`global_tests` 由掃描器產生 | tools／tests／docs（一次） |
| A6 | **總帳頁籤的共用 js 狀態**（`frontend/js/ledger-hub.js` 每個頁籤一組 state：`tax`、`wh`、`an`、`eng`；`anKind`／`statusLabel` 標籤硬編碼） | 新頁籤（類別對應、固定資產、自訂模組入帳、發票折讓…）都要改 L1 js | 規定並示範：**新頁籤一律用頁面內自足的行內元件**（像引擎橫幅 `glEngineBanner()`），`ledger-hub.js` 只留「功能清單＋切頁籤」；標籤改由 API 回傳（`*_label`，我已對補登清單這樣做）。`ledger-hub.js` 這次把 `anKind`／`statusLabel` 的硬編碼改成讀 API 的標籤欄位後，不再因新增頁籤而動 | L1 js（一次） |
| A7 | **選單／側欄項目**（`static/sidebar.js` 與頁面清單） | 新的總帳頁（例：費用類別對應若不做成頁籤）要改 L1 | 原則：**不新增頁面，只加既有頁面的頁籤**（ledger-hub／ledger-settings）；若 W1 要新頁，選單由 `module.json.pages` 宣告驅動（核對目前是否已是如此，不是就列一項 L1 改動） | 規則＋必要時 L1 一次 |

## B. 已經不需要底層（✅，但要守住「只動模組」的做法）

| # | 項目 | 為什麼不需要底層 | 要守的規則 |
|---|---|---|---|
| B1 | **事件碼（E20、E20b…）** | 引擎與契約對 `event_code` 是自由字串（E20 上線時零底層改動）；本體標籤屬 accounting | 新事件碼只在提供者與 `accounting` 的標籤表登記；畫面標籤由 API 回（`event_label`），不寫進共用 js |
| B2 | **`gl_category_map` 讀取路徑**（W1 費用類別→科目） | 表在 accounting 0001 已存在；解析器 `ledger/category_map.py`＋`contract.apply_category_map`（比照 `apply_annotations`）＋API＋頁籤皆在 accounting | 來源模組只回**類別代碼**，不知道任何科目；新增類別只改對應表資料 |
| B3 | **稅碼／401 欄位對照** | `gl_tax401_map` 是資料表；稅碼是字串 | 新稅碼＝對照表加一列；進項憑證來源走 provider（見 C2），不新增底層 |
| B4 | **固定資產 C6** | `fa_*` 表在 0001 已建；事件 E13 由 accounting 自己提供者產生；頁籤用行內元件；旗標 `fixed_assets` | 不要為 C6 再開 migration；需要新欄位走 `data` JSON 欄 |
| B5 | **功能旗標／READY** | `gl_settings`＋`features.py`（accounting） | 新功能＝`FEATURES` 加一列＋`READY` 加鍵；UI 已由 `/features` 清單驅動 |
| B6 | **報表結構（fs_lines、現金流分類）** | 設定表 | 新科目歸屬改 `gl_account_meta`，不改程式 |
| B7 | **排程（引擎自動執行）** | `ModuleSpec.schedulers` | 新排程加進 accounting 的 schedulers |
| B8 | **稽核 `module`／`case_no` 衍生** | 由 action 前綴自動衍生（`ledger.*`→`ledger`） | 新動作沿用 `ledger.<名詞>.<動作>` 命名 |
| B9 | **備份／匿名化分級／demo 清除** | `module.json` 的 `tables`＋`data.tables[].class` 即可（gl_action_requests 已驗證，不需動 `archive.py`／`db.py`） | 新表一律在 module.json 宣告分級；不要為 gl_ 表動 `DEMO_CLEARED_TABLES` |

## C. 要在觸點表登記的「契約」（🟡：現在定義成可擴充，之後不必升版）

| # | 契約 | 現況 | 預留做法 |
|---|---|---|---|
| C1 | **`gl.source_status`**（W2，IP-106）與未來 **`month_totals`**（逐月逐類別總帳數字，供 recon／營運報表） | `source_status(conn, source_type, source_key, prefix=False)` ⇒ `[{event_code,status,voucher_no,event_date}]` | 回傳一律是「字典清單」、消費端**忽略未知鍵**；`month_totals(conn, start, end, dims=None)` 先把簽名定成帶 `dims`（對應 A1）；契約版本寫進回傳（`contract_version`），消費端不因多鍵而壞 |
| C2 | **進項憑證來源**（401 進項發票對比、費用單發票） | 只有銷項 `receivables.tax_invoices`（arap）；進項對比目前讀帳上稅碼列 | 定義多提供者 capability `tax.input_invoices`（`registry.providers`，鍵＝來源模組）：`fn(start, end) -> [{invoiceNo, invoiceDate, pretax, tax, deductible, source}]`；401 彙總讀所有提供者。能力名稱現在登記進 INTEGRATION-POINTS（未實作也先登記），之後各模組自己接 |
| C3 | **`expense.categories`**（W1 定義：所有費用類別代碼＋名稱＋預設稅別） | 尚無 | 單一提供者、回傳清單、代碼發布後不可改；科目對應畫面靠它列出「未設定」 |
| C4 | **事件契約 v1 的 `dims`／`meta` 擴充** | `meta` 自由、行只有 role/side/amount/memo/account_code/tax_code/case_no | 行加選填 `dims`（A1 之後生效）；契約版本不升（選填欄位）；驗證器忽略未知鍵但記錄 |
| C5 | **`voucher.draft`（IP-2）選填參數** | 已加 `reverses_voucher_id`；回 `{"blocked":…}` 慣例 | 之後新增參數一律選填＋回傳維持 `{"id","voucher_no"}`／`{"blocked"}` 兩型 |
| C6 | **`features` API 的欄位** | `key,label,batch,description,enabled,ready` | 新增 `view`（`tab`／`none`）與 `needs`（依賴旗標）選填欄位，UI 忽略未知鍵 |

## D. 建議的「這一班底層一次到位」包（給 W1 合併進觸點表）

1. **accounting migration 0003**（bottom，一次）：`voucher_lines.dim_json`、`gl_dimensions`；（若 W1 同班也有 core／case migration，同一班上線）。
2. **L1 js／頁**：`ledger-hub.js` 標籤改讀 API；`approval-queue.html`＋`routers/approval_queue.py` 改讀項目上的 `typeLabel/openUrl/approveUrl/rejectUrl`（A2）。
3. **L1 helper**：`custom_finance.gl_lines` 帶出完整 `finance` 與 `data`（A4）；`notification_prefs` 自動併入登記信件類型（A3）。
4. **tools／tests／docs**：`SCAN_FILES` 與 `modules.json` 改慣例發現（A5）；INTEGRATION-POINTS 登記 `tax.input_invoices`、`expense.categories`、`gl.month_totals` 三個能力名稱（C2、C3、C1）。
5. 之後 G1–G5（費用單入帳）、C6、C7、recon 對照等**只動 `modules/accounting`＋`modules/case` 與頁面行內元件**，不再碰 L0／L1。

## E. 我（W4）這邊要配合的程式（解凍後）
- 規則化 `features`／事件標籤 API 回傳（`*_label`）、`category_map` 解析器與 API、`dims` 讀寫（migration 0003 之後）、`tax.input_invoices` 彙總讀取（沒有提供者時退化為現況）。
- 每項預留都要有**反向測試**（例：拿掉自動併入信件類型 ⇒ 守門紅；拿掉 `approveUrl` 讀取 ⇒ 新類型佇列項目按不動）。
