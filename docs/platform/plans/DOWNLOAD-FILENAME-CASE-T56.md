# 下載檔名帶「案件編號＋案件名稱＋文件類型」——設計筆記（僅文件，未跑任何測試）

> **r2 修訂（依 0d 稽核）**：①掃描器登記／底層全量閘門／L1 快照與路由 golden；②淨化補 Cf 格式字元、位元組上限為實際約束、標頭編碼與 latin-1 退路；③附件下載名只在授權之後處理，HEIC 移第二期；另補 §0.2 措辭、既有測試清單、設定登錄防護。
> 2026-10-12；委託：hichan-1c（使用者新需求：「下載下來的檔案，要有案件編號、案件名稱，跟這是什麼東西」）。底：`origin/platform` c14f0a1df（內容＝正式機 M1-a `4eb521384`；M2／M3 未上線）。
> 標記：**【需使用者回答】**／**【PM 預設】**／**UNKNOWN**（沒查到證據，不推測）。框架優先：檔名格式、文件類型用語、長度上限由管理者在設定中心調整，程式內只留安全底線。

## 0. 結論（先講）

1. **下載檔名散在 ~28 個後端端點＋~45 個前端 `a.download`，沒有共用函式**；絕大多數案件文件只用「單號.pdf」（`CN0007.pdf`），看不出是哪個案件、什麼文件。
2. **關鍵事實：前端是 `fetch`（帶 Bearer）→ `blob()` → `a.href` 下載，這條路徑上瀏覽器沒有回應標頭可用，`a.download` 是檔名的唯一來源**（例：`case-management-close.js:224-234`）。真正的限制是**認證**——下載連結不能直接帶標頭，uploads 的 `?token=` 已於 2026-09-22 拿掉（只剩 `?pt=` 單一路徑簽章）。所以只改後端不會生效，要「後端單一來源＋前端共用下載函式讀回應 `Content-Disposition` 的檔名」，兩邊一起做。
3. **建議**：一支共用後端函式 `helpers/download_name.py::build()`（輸入：文件類型、案件、單號、使用者、副檔名；輸出：安全檔名＋完整 `Content-Disposition`），格式範本與文件類型用語放設定中心（預設 `{案件編號}_{案件名稱}_{文件類型}_{單號}.副檔名`）；前端一支 `MotrixDownload.save(response, fallback)` 讀回應的檔名。分兩期：**第一期＝有案件可查的文件（報價/完工/出貨/請款/開票/承攬商憑證/費用單/獎金分配/勞報單/傳票…）**，第二期＝期間型報表、匯出、純前端產生檔、附件。
4. **權限底線**：案件名稱只在「這個使用者讀得到該案件」時才放進檔名（`case_page_readable`）；讀不到就退回「文件類型＋單號」。**檔名永遠不含金額。**
5. **工量**：第一期 ≈ 5.0 pd，全部 ≈ 9.25 pd（§8）。

## 1. 下載端點盤點

「案件已知？」＝該端點拿得到 `quote_no`（直接或由單據欄位）。「現行規則」取自程式（`檔:行`，底 c14f0a1df）。

### 1.1 有案件可查的文件（第一期）

| # | 端點／檔:行 | 現行檔名 | 案件已知？ | 文件類型用語（預設，可調） |
|---|---|---|---|---|
| 1 | 報價單 PDF `case/api/quotations.py:5525` | `{quote_no}.pdf`／`{quote_no}_內部.pdf` | 是（路徑參數） | 報價單／報價單（內部） |
| 2 | 報價單存檔版本 `quotations.py:5635` | 存檔實體檔名 `os.path.basename(full)` | 是 | 報價單存檔版本（含事件與日期） |
| 3 | 結案報表 PDF `quotations.py:5673` | `{quote_no}_結案報表.pdf` | 是 | 結案報表 |
| 4 | 專案執行報告 PDF `quotations.py:5706` | `{quote_no}_專案執行報告.pdf` | 是 | 專案執行報告 |
| 5 | 完工單 PDF `case/api/completion_notes.py:683` | `{note_no}.pdf` | 是（`quote_no` 欄） | 完工單 |
| 6 | 費用單據 `case/api/expense_form_pdf.py:104` | `"{doc_code}.pdf"`（`filename="…"` 未編碼） | 是（路徑參數） | 費用單（依單據種類：請款/支出…；種類清單 UNKNOWN，需核 `case_extra_expenses.kind`） |
| 7 | 出貨單 PDF `supply/api/shipping_notes.py:757` | `{note_no}.pdf` | 是 | 出貨單 |
| 8 | 請款單 PDF `arap/api/payment_requests.py:871` | `{request_no}.pdf` | 是（`quote_no` 欄） | 請款單 |
| 9 | 開票申請 PDF `arap/api/invoice_vouchers.py:779` | `{voucher_no}.pdf` | 是（`quote_no` 欄） | 開票申請 |
| 10 | 承攬商憑證 PDF `subcontract/api/contractor_vouchers.py:929` | `{voucher_no}.pdf` | 是（`quote_no` 欄） | 承攬商傳票（名稱待核） |
| 11 | 勞報單 PDF `payroll/api/payslips.py:640(inline)／661` | `{slip_no}.pdf`（未編碼）；前端 `payslip(s).html` 另用 `勞報單_{承攬人}_{日期}.pdf` | **間接**（經來源派發 `dispatch_id`→`quote_no`；可為空） | 勞報單 |
| 12 | 獎金分配單 `payroll/api/bonus.py:1067` | `bonus-award-{award_id}.pdf`（未加引號） | 是（`bonus_groups.quote_no`） | 獎金分配單 |
| 13 | 會計傳票 PDF `accounting/api/vouchers.py:1554` | `voucher-{voucher_no}.pdf` | **部分**（傳票可能掛案件；`voucher_attachments.quote_no`；其餘 UNKNOWN） | 傳票 |
| 14 | 叫料單（材料申請）輸出 | **UNKNOWN**：本次盤點未找到獨立下載端點（可能走前端列印/案件整包） | 是 | 叫料單 |
| 15 | 網路規劃表／書 `netplan/api.py:326/348` | `{planNo}_{siteName}_網路架構規劃表.xlsx`／`…規劃書.pdf`（**已有場域名，非案件名**） | 部分（`network_plans.quote_no` 可空） | 網路架構規劃表／規劃書 |

### 1.2 無單一案件／期間型（第二期，通常維持現狀＋統一規則）

| # | 端點／檔:行 | 現行檔名 | 案件已知？ | 建議 |
|---|---|---|---|---|
| 16 | 案件匯出 `quotations.py:6520`（前端 `case-management-list.js:350` 另命名） | `案件匯出_{時間}.xlsx` | 否（多案件） | 維持；加篩選條件摘要與筆數（可調） |
| 17 | 傳票匯出 T100 `accounting_export.py:533` | `MOTRIX_T100傳票匯出_{起}_{迄}.xlsx` | 否 | 維持 |
| 18 | 財務報表／營業稅 `ledger_closing.py:134`、`ledger_tax.py:83` | `財務報表_{年}年度….xlsx`／`營業稅401_…` | 否 | 維持 |
| 19 | 營運報表、銷項發票清單 `analytics/api/reports.py:2550/2589/2828` | `MOTRIX_營運報表_{safe}`／`MOTRIX_銷項發票清單_{label}` | 否 | 維持 |
| 20 | 出納執行紀錄 `arap/api/cashier.py:764` | `MOTRIX_出納執行紀錄_{起}_{迄}.xlsx` | 否 | 維持 |
| 21 | 外包名冊 `subcontract/api/contractors.py:276` | `contractors.xlsx`（前端另有日期版本） | 否 | 改為中文＋日期（小項） |
| 22 | 住宿紀錄 `lodging/api_records.py:246/257` | `lodging-{rid}.json／.csv` | UNKNOWN | 中文化＋類型 |
| 23 | 每日任務歷程 `daily_tasks/api.py:808` | `task_{id}_history.csv` | UNKNOWN | 中文化 |
| 24 | 自訂模組紀錄 PDF `routers/custom_records.py:313` | `{record_no}.pdf`（`filename="…"`） | UNKNOWN | 用模組名當文件類型 |
| 25 | 拓樸圖 `netplan/api.py:491`（前端 `topology-quick.html:448`） | `{title}.pdf` | UNKNOWN | 保留標題 |
| 26 | PDF 轉檔 `helpers/xlsx_out.py:328`（`_pdf_filename`） | 沿用 xlsx 檔名改副檔名 | 繼承來源 | 跟隨來源檔名，不另立規則 |
| 27 | 郵件附件 `helpers/email_notify.py:1762` | 傳入的 `fname` | 依呼叫端 | 呼叫端改用 `build()`；`filename*` 已正確 |

### 1.3 附件（使用者上傳的原檔）

| # | 端點 | 現行檔名 | 說明 |
|---|---|---|---|
| 28 | `routers/uploads.py:204/205` 檔案服務 | 實體路徑 `uploads/{子夾}/{單號}/{uuid}{副檔名}`；僅 HEIC 以 `basename` 當下載名，其餘 `FileResponse(full)` 無檔名 | 實體檔名是亂數，原檔名存在單據的檔案清單（`filename` 欄） |
| 29 | `routers/attachments.py:89` 單據附件 | `opened.filename`（原檔名，inline） | 提供者回原名 |
| 30 | `accounting/api/vouchers.py:549／1443`、`arap/api/cashier.py:186` | 原檔名（`FileResponse(filename=…)`） | 同上 |

> 補充：`routers/system.py:3243` 的 `FileResponse`（品牌圖片 PNG）與本案無關，不改。

### 1.4 前端自訂下載名（要一起收斂）

`a.download` 共約 45 處：案件管理（`case-management-close/core/dispatch/exec(甘特圖)/fin/list/shipping.js`）、`cashier.js`、`ledger-*.js`、`reports.js`、`voucher.js`、`module-builder-output.js`、`file-preview.js`，與頁面內嵌（`quotation-form`×3、`payment-request-form`、`payment-request`、`payslip-form`、`payslips`×4、`network-plan-form`×2、`custom-records`、`daily-tasks`、`lodging-records`、`contractors`、`topology-quick`、`approval-queue`）。**T1 以 `git grep -nE "\.download ?=|a\.download|link\.download" frontend` 重新產生完整清單（約 40 餘處）當作實作檢查表，逐點打勾**。**這些名稱現在全由前端決定**，包含 `payslips` 的 `勞報單_{承攬人}_…`（檔名含人名，現況如此，見 Q6）。

## 2. 共用函式提案（框架優先）

### 2.1 後端：`backend/helpers/download_name.py`（L1 共用；新）
```
build(doc_type, *, quote_no=None, doc_no=None, ext, user=None, conn=None,
      extra=None) -> DownloadName   # .name（Unicode 乾淨名）、.header（完整 Content-Disposition）
content_disposition(name, inline=False) -> str
```
- 輸入 `doc_type`＝**穩定鍵**（程式內常數，例 `quotation`、`completion`、`shipping`…），**顯示用語**取自設定的「文件類型用語表」（鍵→白話名），改用語不改程式。
- 案件資料：`quote_no` → `quotations.project_name`（案件名稱）／`customer_name`（備用，Q2）。一次查詢；查不到＝視為無案件。
- 可見度：用 `case_page_readable(conn, quote_no, user)`（`get_quotation` 同一支）；**讀不到、或 `user` 為 None（排程／郵件等無使用者情境）⇒ 降級，不放案件名稱**（fail closed，§5）。
- 範本取自設定；`build()` 先把各欄位**各自**淨化再套範本，最後整串再淨化＋截長（§4）。
- **不得在模組載入時 import `settings_registry`**（此底上不存在；M2 才有）：設定讀取用受保護的延遲查詢（取不到／模組缺席 ⇒ 常數預設值），預設常數寫在 `download_name.py` 內。
- 失敗一律降級：任何例外 ⇒ 回今天的檔名（`{單號}.{ext}`），不讓下載失敗；記 log 不記內容。

### 2.2 設定（設定中心群組「下載檔名」；M2 的 `settings_registry` 註冊樣式——**M2 設定中心目前只能看，編輯是 S1 以後；在那之前一律預設值＝零行為變更風險**）
| 白話問句 | 預設 | 範圍 |
|---|---|---|
| 下載檔名的排法 | `{案件編號}_{案件名稱}_{文件類型}_{單號}` | 可用欄位：案件編號、案件名稱、客戶名稱、文件類型、單號、日期；分隔符可選（底線／減號／空格） |
| 沒有案件時 | `{文件類型}_{單號}` | 同上（不含案件欄位） |
| 各文件類型的用語 | 報價單、完工單、出貨單、請款單、開票申請、傳票、勞報單、獎金分配單、費用單、叫料單… | 每項 1–10 字，管理者可改 |
| 案件名稱最長保留字數 | 20 | 5–60 |
| 檔名總長上限 | 100 字（不含副檔名） | 40–150 |
| 案件名稱欄位用哪個 | 案件名稱（專案名稱） | 專案名稱／客戶名稱／兩者（Q2） |
| 是否加日期 | 否 | 是／否（內部版/存檔版本固定附事件與日期，沿用今日） |
| 讀不到案件的人，檔名要不要顯示案件編號 | 要（見 Q3） | 要／不要 |

**程式內硬規則（不進設定、有守門題）**：檔名不含金額欄位；不含路徑分隔字元；淨化與長度底線（§4）；`user` 讀不到案件 ⇒ 不放案件名稱；失敗降級為今日檔名。

### 2.3 前端：`frontend/static/download.js`（新；全站引入）
`MotrixDownload.save(response, fallbackName)`：從 `Content-Disposition` 解析 `filename*=UTF-8''…`（退而求其次 `filename="…"`），建 blob 連結下載；沒有標頭才用 `fallbackName`。**之後各頁不再自己拼檔名**。純前端產生檔（甘特圖、CSV、xlsx 在瀏覽器產生者）走 `GET /api/download-name?docType=&quoteNo=&docNo=&ext=` 取名（同一支後端 `build()`，同權限規則），第二期。

## 3. 各端點改法（第一期）

每個點的改動都是同一個樣式：把 `encoded = urlquote(f"{no}.pdf")` ＋手寫 header 換成 `dn = download_name.build("completion", quote_no=…, doc_no=note_no, ext="pdf", user=user, conn=conn)`，回應用 `dn.header`。端點本身的權限檢查、審計、內容一律不動。前端對應頁面的 `a.download = …` 換成 `MotrixDownload.save(resp, '…')`。

## 4. 淨化（Windows／Mac／瀏覽器）

1. **非法字元**：Windows `\ / : * ? " < > |` 與控制字元（含換行，防標頭注入），以及 **Unicode 格式字元（類別 Cf：U+202E 由右至左覆寫、U+200B–U+200F 零寬、U+2060、U+FEFF BOM 等）與其他不可見分隔字元**（用來偽裝副檔名，例如 `…傳票‮fdp.exe`）→ 換成全形或底線（`／：＊？＂＜＞｜` 或 `_`）；Mac 的 `:` 在 Finder 顯示成 `/`，同樣處理。
2. **首尾**：去掉前後空白；結尾的點與空白（Windows 會吃掉）；開頭的點（Mac/Linux 變隱藏檔）。
3. **保留名稱**：`CON PRN AUX NUL COM1–9 LPT1–9`——對**主檔名（去除前後空白與結尾的點之後）不分大小寫**比對（`con`、`Con.txt` 都算）⇒ 加底線。
4. **正規化**：Unicode NFC（Mac 檔案系統用 NFD，混用會出現視覺相同但搜尋不到）；全形空白→半形。
5. **長度**：**實際約束是 UTF-8 位元組**——多數檔案系統單一檔名上限 255 位元組，要扣掉副檔名（`.xlsx` 5 位元組）；中文每字 3 位元組，**100 個中文字＝300 位元組，已超過**，所以「字元數上限」只是設定的使用者介面，**程式以位元組為準**（可用位元組＝255 − 副檔名位元組）。Windows 另有路徑總長 260 字元的限制（下載資料夾已佔一部分），預設字元上限保守。**截斷順序：先截案件名稱，再截其他非必要欄位，絕不截副檔名與單號；若「文件類型用語＋單號」本身就超過可用位元組 ⇒ 硬截斷（從尾端依字元邊界截，不切壞多位元組字元），仍保留副檔名。截斷處不加 `…`，直接截。**
6. **表情符號／罕用字**：保留（現代系統支援），但 ASCII 退路中換成 `_`。
7. **標頭編碼**：`Content-Disposition: attachment; filename="{ASCII退路}"; filename*=UTF-8''{percent-encoded}`（RFC 6266／8187）。`filename*` 的值**除 RFC 8187 attr-char（英數與 `!#$&+-.^_`|~`）外一律百分比編碼**（含空白、`'`、`(`、`)`、`,`、`;`、`=`）。**ASCII 退路必須是 latin-1 可編碼**（Starlette 以 latin-1 編碼標頭值，非 latin-1 會丟例外 ⇒ 下載整個失敗）：非 ASCII 換 `_`，去掉 `"`、`\`、`%` 與控制字元；加測試「任何輸入下標頭值皆可 `.encode("latin-1")`」。`helpers/email_notify.py:1763` 目前只送 `filename*`，保留不動。現行 `filename="…"` 未編碼的點（#6、#11、#12、#13、#24、#22、#23）一併修。
8. **空結果**：淨化後為空 ⇒ 用文件類型＋單號；仍空 ⇒ `download`。
9. **附件（§1.3）**：**一律在授權驗證之後才處理名稱，且名稱絕不用來推導路徑或參與 `_inside` 判斷。** `routers/uploads.py`（約 200–205 行）只認實體路徑——案件編號／文件類型的查詢必須嚴格排在 `_canonical_or_403`／`_resolve_upload_path` 與 `_authorize_read`／`?pt=` 簽章驗證**之後**；`routers/attachments.py:89` 只在 `_inside(opened.abs_path, _roots(prov))` 通過、檔案存在**之後**才裝飾回應檔名；`vouchers.py:549/1443`、`cashier.py:186` 同理。只改**回應的 `Content-Disposition` 檔名**，不動儲存路徑、不動任何路徑守門。名稱＝`{案件編號}_{案件名稱}_{文件類型}_附件_{原檔名}`（原檔名先淨化、保留副檔名；原檔名超長時截主檔名）；是否加前綴為 Q4。**HEIC 的「以 `basename` 當下載名」改為原檔名一事移到第二期**（需要由實體路徑反查單據才拿得到原檔名，牽涉授權路徑，第一期不碰）。

## 5. 金額與權限影響

- **永不含金額**：範本可用欄位白名單只有 案件編號／案件名稱／客戶名稱／文件類型／單號／日期；沒有任何金額欄，設定不能加（守門題：欄位白名單鎖在程式）。
- **案件名稱的敏感度**：案件名稱／客戶名稱本身可能機敏（客戶名、地點）。檔名會被存進下載資料夾、郵件附件、雲端同步、瀏覽器歷史，**比螢幕上的資料擴散得更遠**。所以：
  1. 只有 `case_page_readable(conn, quote_no, user)` 為真才放案件名稱／客戶名稱（與 `GET /api/quotations/{no}` 同一支）；
  2. 讀不到案件但能取得該文件的角色（例：財務看傳票、出納看請款、勞報單經手人）⇒ 只用「文件類型＋單號」（Q3 決定案件編號是否保留）；
  3. 遮蔽帳號（`money_visible` 為否）**不影響**檔名（檔名不含金額）；
  4. demo 帳號沿用現行遮罩規則（若有）。
- **個資**：現行 `payslips` 前端檔名含承攬人姓名，與郵件附件名同理；本案**不新增**人名進檔名，並建議第二期把勞報單檔名改成不含姓名（Q6，【需使用者回答】因會改變財務習慣）。
- **郵件附件**（`email_notify`）：收件人若沒有案件權限，檔名同樣降級；呼叫端須傳收件人的可見度判斷，無法判定 ⇒ 降級（fail closed）。

## 6. 測試

1. `test_download_name_*`（純函式，無 DB）：淨化表（每個非法字元、結尾點/空白、保留名稱、NFC/NFD、換行注入 `\r\n`、`"`、超長 CJK、emoji、純空白、全非法）；位元組與字元雙上限；截斷順序（單號與副檔名不被截）；ASCII 退路；`filename*` 往返解碼。
2. 範本：預設、換分隔符、缺欄位降級、未知欄位被拒（含金額欄位名）。
3. 權限：`case_page_readable` 假→不含案件名稱；真→含；`user=None`（排程）→ 降級；查不到案件→降級；任何例外→今日檔名。
4. 端點（第一期 12 個）：每個回應 `Content-Disposition` 含案件編號/文件類型/單號，且**不含**金額字串（以測試資料的金額數字掃描）；無權限角色的檔名不含案件名稱；既有內容與權限回歸不變。
5. 守門：`grep` 式靜態守門——`routers/modules/**` 不得再手寫 `Content-Disposition`（走 `download_name`）；白名單例外清單（期間型報表在第二期前列例外）。
6. 前端靜態守門：案件類頁面不得再出現 `a.download = \`${…}.pdf\``；`MotrixDownload.save` 解析 `filename*`／退路的單元題（JS 純函式）。
7. 附件：原檔名保留副檔名；前綴開關；路徑穿越 `../`、`..%2f` 的檔名被淨化且儲存路徑不變；HEIC。
8. e2e（單頁）：完工單下載，檔名符合範本。

9. **掃描器登記**：`backend/tests/test_company_setup_output_points_2026_09_28.py` 以 `OUTPUT_PAT`（`Content-Disposition|FileResponse(|…`）掃描每個函式，要求有公司資料閘呼叫或在例外表有登記——`helpers/download_name.py::content_disposition()` 與每個改接的端點都會觸發，需在掃描器 (c) 表逐一登記並寫明理由；加題確認登記完整。
10. **既有測試回歸（T1 重新 grep 所有第一期端點）**：已知會碰檔名／標頭的有 `test_export_pdf_and_audit_2026_09_30.py`（約 286、302 行）、`test_attachments_open_2026_09_30.py`（約 109 行）、e2e 的 `expect_download`（`test_e2e_ledger_tax_wh_annot`、`test_e2e_attach_mine`）；改後逐一確認與更新。
11. 淨化補充題：Cf 字元（U+202E、U+200B、U+FEFF）被移除；`con`／`CON.txt`／` Con. ` 被改名；100 個中文字的輸入 ⇒ 位元組 ≤ 255 − 副檔名；「文件類型＋單號」超長 ⇒ 硬截斷且副檔名仍在；`filename*` 只含 attr-char 與 `%XX`；ASCII 退路 `.encode("latin-1")` 不丟例外；設定缺席（無 `settings_registry`）⇒ 常數預設。

## 7. 風險

1. **前端蓋掉標頭**（§0.2）：若只做後端，使用者看不到變化——必須兩邊一起；第一期先做案件文件頁面。
2. **檔名更長**：Windows 路徑 260 字上限；預設總長 100 字已含餘裕，但使用者下載資料夾很深時仍可能失敗 ⇒ 設定可調、預設保守。
3. **案件名稱外洩**（§5）：以權限守門＋降級處理；仍是「檔名會擴散」的固有風險，需 Q3/Q5 的使用者決定。
4. **改名破壞下游習慣**：既有人工/外部流程若依 `{單號}.pdf` 找檔 ⇒ 單號仍在檔名內、位置固定在尾端；設定可還原為「只用單號」。
5. **同名檔案**：不同案件同單號不可能（單號唯一）；同一文件重複下載由瀏覽器加 `(1)`，不處理。
6. **範圍蔓延**：45 個前端點、28 個後端點，易漏——靠 §6.5 靜態守門與分兩期。
7. **舊瀏覽器**：`filename*` 不支援者讀 ASCII 退路（會看到底線）；可接受。
8. **層級與閘門**：`backend/helpers/**` 在 `bottom_layer.json` 屬底層，整個變更**走完整凍結樹官方閘門**，並須更新 L1 介面快照（`l1_interface_snapshot.json`）與整合點登錄（`INTEGRATION-POINTS.md`）；第二期新增 `/api/download-name` 路由 ⇒ 路由 golden 要重產。
9. **未驗證項**：叫料單下載端點（#14）、傳票與案件的關聯（#13）、`case_extra_expenses.kind` 種類（#6）、`custom_records`／`lodging`／`daily_tasks` 是否有案件（#22–24）——**UNKNOWN**，實作前逐一核。

## 8. 工量（pd）

| 任務 | pd |
|---|---|
| `helpers/download_name.py`（淨化、範本、可見度、降級）＋單元測試 | 1.5 |
| 設定群組註冊（依 M2 登錄）＋預設值守門 | 0.5 |
| 前端 `download.js` ＋ 第一期案件頁面改用（報價/完工/出貨/請款/開票/承攬商/費用單/獎金/勞報單/傳票 ≈ 20 處） | 1.0 |
| 第一期後端 12 端點改接＋回歸測試 | 1.25 |
| 靜態守門（後端/前端）＋e2e | 0.25 |
| 掃描器 (c) 表登記、L1 快照／整合點登錄、既有測試回歸（§6.9–6.10） | 0.5 |
| **第一期小計** | **5.0** |
| 第二期：期間型報表統一 ~10 端點、附件前綴與 HEIC（#28–30）、`/api/download-name`＋純前端產生檔 ~25 處、郵件附件 | 4.0 |
| 第二期：路由 golden 重產（新增路由） | 0.25 |
| **合計** | **9.25**（範圍 8.25–10.25；不含 Q6 勞報單去姓名的財務習慣溝通） |

## 9. 待使用者確認

| # | 問題 | 需使用者？ | 預設／建議 |
|---|---|---|---|
| Q1 | 檔名排法：`案件編號_案件名稱_文件類型_單號`，順序與分隔符是否合意？（例：`案件編號_新竹廠區網路建置_完工單_單號.pdf`） | **【需使用者回答】** | 預設如左；之後可在設定調 |
| Q2 | 「案件名稱」指專案名稱，還是客戶名稱？兩者都放？ | **【需使用者回答】** | 專案名稱；客戶名稱可在設定加 |
| Q3 | 讀不到該案件的人（財務/出納/經手人）下載的檔，要不要還是帶案件編號？（案件名稱一律不帶） | **【需使用者回答】** | 帶編號、不帶名稱 |
| Q4 | 使用者上傳的附件下載時，要不要加案件前綴？（原檔名保留） | **【需使用者回答】** | 要加前綴；可在設定關 |
| Q5 | 案件名稱長度上限（字） | 【PM 預設】 | 20；設定可調 |
| Q6 | 勞報單檔名現在含承攬人姓名，是否改成不含姓名（個資與外洩面）？ | **【需使用者回答】**（影響財務慣用） | 第二期再議；本案不新增姓名 |
| Q7 | 期間型報表（營運報表、出納紀錄等）維持現狀即可？ | 【PM 預設】 | 維持，只統一標頭編碼 |
| Q8 | 第一期先做哪幾類？ | 【PM 預設】 | 報價、完工、出貨、請款、開票、承攬商憑證、費用單、獎金、勞報單、傳票 |

## 10. 依據與限制

- 盤點方法：`git grep` `Content-Disposition／filename／FileResponse／download_name` 於 `backend/**`（排除測試）與 `a.download` 於 `frontend/**`；逐點讀取檔名組裝行。案件欄位以 `db.py` 的 `CREATE TABLE` 掃描（`quote_no` 存在於 `payment_requests／invoice_vouchers／contractor_payment_vouchers／shipping_notes／completion_notes／case_extra_expenses／bonus_groups／network_plans／voucher_attachments／contractor_dispatches`）。
- **沒讀**：各端點的權限檢查細節（只用於判斷「案件是否已知」）、`unified_approval_flow`、M2 `settings_registry` 實際 API（不在此底上）、前端各頁面完整程式；叫料單、傳票與案件的連結見 §7.9 UNKNOWN。
- 沒有跑任何測試或工具；行號取自 `origin/platform` c14f0a1df，實作前重核。
