# A7 第三期設計：附件前綴、HEIC、`/api/download-name`、郵件附件（僅文件，未跑任何測試）

> 日期：2026-10-13　作者：hichan-98　委託：hichan-1c　前置：A7 第一期（`wip/t57-download-name-p1-r2`）、第二期（`wip/t57-download-name-p2-r2`）
> 範圍：只做**設計**，不寫程式。涉及授權路徑與檔案服務，所有控制點以「**授權先於命名**、名稱永遠來自資料庫中繼資料、不來自請求」為原則；HEIC 受 0d 的安全審查約束。
> **r2（0d 對 r1 的註記 1–4）**：①S7 原本把「非影像／PDF 一律 attachment、全部 nosniff」寫成既有控制——**事實不是**：今天 `open_attachment` 一律以 `application/octet-stream` inline 回應、`serve_upload` 用猜測的 mime 且**沒有** `nosniff`；本版改為明確的**逐路由標頭表**與有意識的行為變更決定（§3b）；②`describe()` 的契約（`user=None`、不決定可讀、只在正規化之後、例外安全）；③`/api/download-name` 的速率限制用**行程內每使用者權杖桶**（現況沒有通用限流器可重用）；④以 `dn.header` 取代標頭時**保留提供者的 disposition 類型**（預覽仍 inline），只改檔名；並明寫預設值的可見度。
> 標記：**UNKNOWN**＝沒有證據，不推測；pd 為我的粗估。

## 0. 結論（先看）

1. **今天有兩條下載路徑，名稱能力不同**：①`GET /api/attachments/open`（附件目錄，`ATTACHMENTS_OPEN_ENABLED = True`）——授權在提供者的 `open()`，**已經回傳原檔名**（`FileResponse(filename=opened.filename)`，inline）；②`GET /api/uploads/{path}`（純路徑；`?pt=` 簽章給 `<img src>`）——**沒有任何單據脈絡**，HEIC 以 `basename`（亂數 uuid）當下載名。
2. **前綴只能加在有脈絡的地方**：路徑 ① 由提供者回報單據脈絡（`quote_no`、文件類型、單號）即可套 `download_name`；路徑 ② 需要一個**新的、只在授權通過之後才呼叫**的 `describe()` 方法（同一個提供者，因為「能不能讀」與「它是哪張單據的哪個檔」是同一份知識），才能取得原檔名與脈絡。
3. **HEIC**：HEIC 的原檔名問題（路徑 ②）與「是否放行 HEIC 上傳」是兩件事；放行本身交 0d 的安全審查（`ftyp` 檔頭、伺服器不解碼、EXIF／GPS 隱私決定），**審查前不動上傳白名單**；本設計只處理「已存在的 HEIC 下載時用什麼名字」。
4. **`/api/download-name`**（前端自行產生的檔案）：新增一條**唯讀**路由，輸入（文件類型、案件編號、單號、副檔名）→ 輸出名稱，**授權與 `download_name.build()` 完全相同**；新路由需重產路由 golden。約 25 個前端點逐一改接。
5. **郵件附件**：目前呼叫端只有月報等**系統產生、非單一案件**的檔案，沒有收件人層級的案件脈絡；結論＝**維持現狀**，並加一條守門：任何將來寄出的**案件文件**附件必須以 `user=None` 呼叫命名（不放案件名）。
6. **工量（估）**：約 **7.25 pd**（契約擴充與提供者 1.5、`open_attachment` 命名 0.5、`describe()`＋HEIC 命名 1.0、`/api/download-name`＋路由 golden＋25 個前端點 2.5、郵件守門 0.25、測試 1.0、書面登記 0.5）。

## 1. 現況盤點（已讀 `33b84b332`／`wip/t57-download-name-p2-r2`）

### 1.1 兩條下載路徑
| 路徑 | 授權 | 回應檔名 | 備註 |
|---|---|---|---|
| `GET /api/attachments/open?type=&doc=&file=`（`routers/attachments.py`） | 提供者 `prov.open(conn, user, type, doc, file)`；看不到＝404 同一句；實體檔必須在 uploads 或提供者宣告的 `ROOTS` 底下 | `OpenedFile.filename`（**原檔名**）；`content_disposition_type="inline"` | 預覽元件使用；不收 `pt` 簽章 |
| `GET /api/uploads/{path}`（`routers/uploads.py`） | `?pt=` 簽章（綁單一路徑、1 小時）**或** `Authorization` ＋ `upload_readable`（`uploads.path_access`）；或簽核佇列情境 | 一般檔 `FileResponse(full)`（無檔名）；**HEIC／HEIF**：`filename=os.path.basename(full)`（亂數 uuid）＋`attachment` | `<img src>` 直連 |

### 1.2 附件資料夾與中繼資料（誰擁有、檔名存哪）
| 資料夾 | 擁有模組 | 原檔名所在 | 備註 |
|---|---|---|---|
| `quotations` | case | `quotations.signed_files_json`（回簽檔） | catalog：`quotation_signed` |
| `quotation_payment_items`、`quotation_materials`、`quotation_materials_invoices` | case | 案件紀錄 `data_json` 內各項的 `files`／`invoiceFiles` | catalog：`payment_item`、`material`、`material_invoice`；路徑鍵 `單號_序號` |
| `case_updates` | case | 動態的檔案清單 | catalog：`case_update` |
| `case_extra_expense`（及舊 `quotation_settlement_extra`） | case | `case_extra_expenses.files_json` | catalog：`extra_expense`；HEIC 唯一放行處 |
| `completion_notes` | case | `completion_notes.signed_files_json` | catalog：`completion_note`（標籤「完工單回簽」） |
| `_pending_case_changes/<id>` | case | 變更申請的待核准附件 | 只有申請人或案件頁可讀 |
| `invoice_vouchers` | arap | 開票申請的檔案欄 | catalog：arap 提供者 |
| `contractor_dispatches`、`contractor_dispatch_invoices` | subcontract | **UNKNOWN**（未逐一讀） | 路徑鍵為派發 id |
| `shipping_notes` | supply | **UNKNOWN** | |
| `custom_records`（`custom_files.py`） | 自訂模組 | `custom_record_files` 表 | 讀檔走 `uploads.path_access`；暫存檔只有上傳者讀得到 |
| `voucher_attachments`（會計）、勞報單回簽檔、工作日誌照片 | accounting／payroll／crm 等 | 各自端點 | **不經 `uploads.path_access`**（各有端點），本期不納入 |

**判讀**：多數資料夾的**原檔名都存在擁有模組自己的 JSON／欄位**，且每個擁有模組已有 `uploads.path_access`（讀取規則）與（多數）`attachments.catalog`（開檔）提供者。所以「由路徑反查原檔名與單據脈絡」的知識**已經在提供者手上**，不需要新資料表。

### 1.3 A7 已有的零件
`helpers/download_name.py::build()`（案件編號／案件名／文件類型／單號、淨化、位元組上限、`user=None` 降級）、`content_disposition()`（RFC 8187＋latin-1 安全退路＋255 位元組上限）、設定群組 `download_name`（21 鍵；**沒有**附件前綴鍵）、前端 `MotrixDownload.nameFrom()`。

## 2. 命名規則（附件）

- **預設**（使用者決定 Q4）：加案件前綴、保留原檔名：`{案件編號}_{案件名}_{文件類型}附件_{單號}_{原檔名}`（案件名依 A7 規則：只有讀得到案件的人才放；單號即案件編號時不重複）。
- **原檔名處理**：先 `_clean`（NFC、非法字元、Cf／覆寫字元、控制字元）、保留**合法副檔名**、主檔名超長時先截（沿用 `_fit` 順序：案件名先縮、原檔名主檔名其次、**副檔名與單號最後**）；淨化後為空 ⇒ `附件_{序號}`。
- **設定**：在 `download_name` 群組新增 `attachment_prefix`（int：0 不加、1 加；**預設 1**＝使用者決定；「不加→加」屬放寬：把案件名帶進附件檔名，沿用 `no_access` 的邏輯，只有讀得到案件者才會得到案件名）；基準檔同步。
- **預設可見度（明寫）**：`attachment_prefix=1`（預設）時，**案件名只顯示給有該案件讀取權限的檢視者**（`no_access` 設定決定其餘人看到什麼，預設保留案件編號、省略案件名）；簽章路徑與郵件附件一律 `user=None`（不放案件名）。
- **不影響**：儲存路徑、`uploads` 實體檔名（仍是亂數）、授權順序；**名稱只是下載時的標頭**。

## 3. 路徑 ①：`/api/attachments/open`

**現況**：提供者 `open()` 回 `OpenedFile(abs_path, filename, mime, size)`。
**設計**：
1. **契約加性擴充（v1.1）**：`OpenedFile` 增加三個**選填**欄位 `quote_no`、`doc_type`（`DOC_TYPES` 鍵）、`doc_no`；舊提供者不填 ⇒ 行為不變（回原檔名，無前綴）。這是 L1 公開介面的新增（次版號升版，快照更新）。
2. **命名在授權之後**：`open_attachment` 在 `prov.open()` 成功、`_inside(...)` 與 `isfile` 通過**之後**才組名：`dn = download_name.build_attachment(original=opened.filename, quote_no=…, doc_type=…, doc_no=…, user=user, conn=…)`，回應標頭用 `dn.header`；任何例外 ⇒ 退回原檔名（現況）。
3. **inline 維持**（預覽元件需要）；新增 `X-Content-Type-Options: nosniff`；`attachment` 與否維持現況（預覽 inline，下載按鈕由前端 `a.download` 指定名稱）。
4. **先做的提供者**：case（回簽檔、款項、叫料、動態、額外支出、完工單回簽）、arap（開票申請）、accounting（若其 catalog 有案件脈絡）；subcontract／supply 的脈絡來源 **UNKNOWN**，逐一核對後再補，沒補的維持原樣。

### 3b. 逐路由標頭表與有意識的行為變更（0d 註記 1）
**現況（已讀）**：
| 路由 | `Content-Type` | `Content-Disposition` | `nosniff` |
|---|---|---|---|
| `GET /api/attachments/open` | **一律 `application/octet-stream`** | **一律 inline**（`filename=原檔名`） | 無 |
| `GET /api/uploads/{path}` 一般檔 | 依副檔名猜測（Starlette `FileResponse`） | 無（瀏覽器依型別決定） | 無 |
| `GET /api/uploads/{path}` HEIC／HEIF | 猜測 | `attachment`，`filename=basename`（uuid） | 無 |
| 會計 `voucher_attachments`、勞報單回簽檔等各自端點 | 各自 | 各自（`inline` 或 `attachment`） | 無 |
**本版決定（行為變更，須使用者知悉）**：
1. **所有檔案服務路由加 `X-Content-Type-Options: nosniff`**（純加標頭，無相容風險）。
2. **`/api/attachments/open`**：`Content-Type` 改為**依白名單副檔名對應的固定 mime**（`.jpg/.jpeg/.png/.pdf`；其餘一律 `application/octet-stream`）；**預覽的 `inline` 只保留給 `image/jpeg`、`image/png`、`application/pdf`**，其他類型（含 xlsx／docx 等額外放行副檔名）改為 **`attachment`**。這是**有意的行為變更**：以前這些檔在預覽元件可能被「開啟」，之後會變成下載；原因＝避免內嵌顯示 Office／HTML 類內容。預覽元件對非影像／PDF 本來就顯示下載連結（UNKNOWN：需核對 `file-preview.js`）。
3. **提供者宣告的 disposition 類型保留**：以 `dn.header` 取代標頭時，**只換檔名**，disposition 類型（inline／attachment）依上列規則決定，不被命名覆蓋。
4. `serve_upload` 一般檔：維持不帶檔名（`<img src>`）；加 `nosniff`；非影像／PDF 副檔名走 `attachment`（與上同）。
5. **測試**：逐路由、逐副檔名的標頭矩陣（類型、disposition、`nosniff`）；`.html` 改名成 `.jpg` 的檔（已被 magic 擋）作為正對照；移除 `nosniff` ⇒ 測試必須紅。

## 4. 路徑 ②：`/api/uploads/{path}`（HEIC 與前綴）

**問題**：只有路徑，沒有脈絡；HEIC 下載名是亂數。
**設計**：
1. 在 `uploads.path_access` 提供者新增**選填方法** `describe(conn, folder, rest, user) -> dict|None`，回 `{filename, quote_no, doc_type, doc_no}`；**契約**：①`user` 可以是 **`None`**（簽章路徑），**每個提供者都必須處理**；②**絕不決定可讀性**（只回中繼資料）；③**只在** `canonical_upload_path`／`upload_owner` 正規化**之後**、且 `upload_readable` 已通過（或簽章已驗）**之後**呼叫；④提供者沒有此方法 ⇒ 維持現況；⑤**例外安全**：`describe()` 丟例外、或回傳含 `
`／U+202E 的名稱 ⇒ 結果仍經 `_clean`＋`content_disposition()`，標頭安全（測試：兩種情形都得到安全的標頭，下載照舊）。
2. `serve_upload` 的 HEIC 分支：授權通過 → `describe()` → `download_name.build_attachment()` → `FileResponse(..., filename=dn.name, content_disposition_type="attachment")`＋`nosniff`；`describe()` 失敗或回 None ⇒ 退回 `basename`（現況）。
3. 非 HEIC 的 `<img src>` 直連維持**不帶檔名**（inline 影像不下載，加前綴沒有意義）。
4. **簽章（`?pt=`）路徑**：簽章只綁路徑，簽發時已查過權限；`describe()` 以**簽發者看得到**為前提——但簽章持有者可能不是簽發者本人（連結外流），因此**簽章路徑不放案件名**（`user=None` 降級，只放文件類型與原檔名）。**帶 `Authorization` 的路徑才放案件名**。
5. **HEIC 上傳白名單不在本設計**：現況只有 `case_extra_expense` 放行 `.heic .heif`；其他資料夾（含完工單驗收照片）要放行需 0d 的威脅審查（`ftyp` 檔頭驗證、伺服器不解碼、EXIF／GPS 去識別化決定）。**審查前不改 `_EXTRA_EXTS_BY_SUBFOLDER`。**

## 5. `/api/download-name`（前端產生的檔案）

**用途**：甘特圖、CSV、瀏覽器端產生的 xlsx 等（約 25 個前端點）沒有伺服器回應可讀標頭，需要向後端問「這個檔該叫什麼」。
**設計**：
- `GET /api/download-name?docType=&quoteNo=&docNo=&ext=`（`docType` 必須在 `DOC_TYPES` 或登記的前端文件類型表內，否則 400）→ `{"name": "…"}`；內部呼叫 `download_name.build()`，**授權與 A7 相同**（`case_page_readable`；沒有案件權限只回案件編號或不含案件欄位）；`ext` 白名單（`pdf xlsx csv png jpg json`）；需登入；**速率限制＝行程內每使用者權杖桶**（現況**沒有**通用的每使用者限流器可重用 ⇒ UNKNOWN；做法：記憶體字典 `user_id → (tokens, 時間戳)`，預設每分鐘 60 次、突發 20；超過回 429；只在單一行程有效——本平台是單一行程部署，足夠；若日後多行程再換）；沿用 A7 的**金額字串白名單**與 255 位元組上限（`_fit_name_bytes`）。
- **不構成存在性探測**：回應中的案件編號是**請求者自己傳入的值**，案件名只有讀得到才出現；不存在的案件與讀不到的案件回應形狀相同。
- 前端 `MotrixDownload.nameFor({docType, quoteNo, docNo, ext}, fallback)`：非同步取名，失敗／逾時（例如 1.5 秒）⇒ 用 `fallback`（下載不能因取名而失敗）；同一頁同參數快取。
- **新路由**：需登錄路由 golden、`INTEGRATION-POINTS`、L1 快照（若為 L1）。
- 約 25 個前端點逐一改接（`git grep -nE "\.download ?=" frontend`），每點一條靜態守門：用到 `a.download = ` 的案件類頁面必須經 `MotrixDownload`。

## 6. 郵件附件

- 現況：`helpers/email_notify.py::_send_with_attachments(to_addrs, subject, html, attachments)` 的呼叫端都在同檔（月報等系統產生檔），檔名由呼叫端給；MIME 標頭已只送 RFC 8187 `filename*`。
- **結論**：本期**不改命名**（月報是期間型，維持現狀，設計 Q7）。
- **守門（新）**：靜態測試——任何在 `email_notify` 之外呼叫它的程式，若附件檔名來自案件文件，必須以 `download_name.build(..., user=None)` 取得名稱（`user=None` ⇒ 不放案件名，因為收件人的案件權限未知）。
- 這與「沒有案件權限的收件人不該看到案件名」一致；將來若要依收件人個別寄送，需逐收件人呼叫 `build(user=收件人)`，屬另案。

## 7. `xlsx_out._pdf_filename`（跟隨來源檔名）
維持跟隨來源的 xlsx 檔名改副檔名；改用 `download_name.content_disposition()` 統一標頭編碼（A7 第二期的掃描器例外項因此可移除）。

## 8. 安全風險與必備控制

| # | 風險 | 控制 | 證明測試（含正對照） |
|---|---|---|---|
| S1 | **授權先於命名**：先組名再授權，會洩漏檔案或單據存在 | 任何命名都在授權通過之後；失敗回同一句 404 | 無權限者請求 ⇒ 404，且回應標頭不含任何名稱（P：把命名移到授權前，測試必須紅） |
| S2 | **名稱來源**：名稱來自請求參數 | 名稱只來自資料庫中繼資料（提供者）；`/api/download-name` 的 `docType` 走白名單、`docNo` 只做淨化後回傳 | 請求帶 `filename=../x` ⇒ 無效；`docNo` 含 CRLF／RTL 覆寫 ⇒ 被淨化 |
| S3 | **標頭注入／同形字偽裝**（原檔名含 `\r\n`、U+202E、Cf） | 一律經 `_clean`＋`content_disposition()`；ASCII 退路 latin-1 安全 | 沿用 A7 的 hostile 名稱題庫套到附件路徑 |
| S4 | **案件名洩漏給只有單據權限的人** | 沿用 `no_access` 設定（預設保留案件編號、省略案件名）；簽章路徑不放案件名 | 角色矩陣：能開附件但無案件讀取權者 ⇒ 名稱不含案件名 |
| S5 | **`describe()` 擴大讀取面** | `describe()` 只回中繼資料、只在授權後呼叫；不得用來決定是否可讀；擲例外 ⇒ 退回原行為 | 提供者 `describe()` 丟例外 ⇒ 下載照舊（原檔名／亂數名），不 500 |
| S6 | **路徑穿越**（`rest` 段） | 沿用 `canonical_upload_path`／`upload_owner` 與 `_safe_save_dir`；`describe()` 不接受未經正規化的路徑 | `..%2f`、反斜線、ADS ⇒ 400／404 |
| S7 | **內容嗅探／XSS**（inline 檔案） | **本版新增**（非既有控制）：§3b 的標頭表——固定 mime、僅影像／PDF inline、全部 `nosniff` | §3b 的逐路由標頭矩陣；`.html` 改名 `.jpg`（已被 magic 擋）作正對照 |
| S8 | **HEIC／EXIF 隱私** | 本設計不放行新資料夾；既有 `case_extra_expense` 的 EXIF（含 GPS）去識別化交 0d 威脅模型 | （0d 範圍） |
| S9 | **存在性探測**（`/api/download-name`） | 回應形狀與**大小**一致；權杖桶速率限制 | 存在／不存在／無權限三種案件的回應形狀、欄位集合與位元組長度相同（依名稱長度的差異只來自請求者自己傳入的欄位）；連續請求超過桶 ⇒ 429（測試用小桶驗證邏輯） |
| S10 | **效能**（`describe()` 多一次 DB 讀） | 只在 HEIC 與需要前綴的下載才呼叫；一次一筆；不在 `<img>` 熱路徑 | 150 張圖列表不觸發 `describe()` |

## 9. 測試（紅 → 綠）
1. `OpenedFile` v1.1：舊提供者不填新欄位 ⇒ 行為不變；填了 ⇒ 前綴正確（涵蓋 case／arap 提供者）。
2. `open_attachment`：授權失敗 404 無名稱；成功回 `案件編號_案件名_文件類型附件_單號_原檔名`；`attachment_prefix=0` ⇒ 原檔名；`no_access` 三種設定下對無案件權限者的名稱。
3. `serve_upload` HEIC：有 `describe()` ⇒ 前綴＋原檔名；簽章路徑不放案件名；`describe()` 拋例外 ⇒ `basename` 退路。
4. `/api/download-name`：docType 白名單、ext 白名單、未登入 401、速率限制、三種案件狀態回應形狀相同、金額字串掃描（永不含金額）。
5. 前端：靜態守門（案件類頁面不得手寫 `a.download = \`${…}.pdf\``）；`nameFor` 純函式題（逾時退回 fallback）。
6. 郵件守門：`email_notify` 外的呼叫端附件檔名來源檢查；`user=None` 不含案件名。
7. 路由 golden／L1 快照／整合點登錄／掃描器 (c) 表登記（新輸出點）。

## 10. 風險與 UNKNOWN
- UNKNOWN：subcontract／supply／crm／工作日誌照片的中繼資料位置與提供者；`attachments.catalog` 列表回傳的欄位是否已含單據脈絡（若已有，`OpenedFile` 擴充可更小）；前端約 45 個 `a.download` 點的完整清單與分類；`_demo_uploads` 前綴對 `describe()` 的影響；HEIC 的安全審查結論與時程。
- 風險：①契約擴充（`OpenedFile` v1.1）需所有提供者核對；②`describe()` 是新增的授權旁路面，必須嚴格「授權後才呼叫」；③前端 25 點改接容易漏，靠靜態守門。

## 11. 需要使用者回答的問題（只列不可逆者）
- 無阻擋性問題。預設（附件加案件前綴、保留原檔名；無案件權限者只保留案件編號）已是使用者決定；簽章路徑不放案件名、HEIC 白名單交安全審查，皆為 PM／安全決定。
